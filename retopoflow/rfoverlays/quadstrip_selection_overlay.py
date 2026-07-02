'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

from __future__ import annotations

import bpy
from mathutils import Vector, Matrix
from bmesh.types import BMFace
from bpy.types import Context, Event
from bpy_extras.view3d_utils import location_3d_to_region_2d

from typing import ClassVar
from collections.abc import Sequence

from ..rfoverlay_base import RFOverlay_Base
from .overlays import overlay_names

from ..rfglobals import RFGlobals
from ..common.bpy_helper import bpy_ops_retopoflow
from ..common.operator import RFOperator
from ..common.bmesh import get_bmesh_emesh, bme_midpoint, bmf_midpoint, bmfs_shared_bme
from ..common.drawing import Drawing
from ..common.raycast import is_point_hidden, mouse_from_event
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bezier import CubicBezier
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.utils import iter_pairs


def get_label_pos(context : Context, strip : Sequence[Vector]) -> Vector | None:
    assert context.edit_object
    M = context.edit_object.matrix_world
    rgn, r3d = context.region, context.region_data

    centers = [pt for pt in strip if not is_point_hidden(context, pt)]
    if len(centers) == 0:
        return None

    mid = sum(centers, Vector((0,0,0))) / len(centers)
    pt3d = min(centers, key=lambda pt:(pt - mid).length)
    return location_3d_to_region_2d(rgn, r3d, M @ pt3d)

def get_quadstrips(bmfs : Sequence[BMFace]) -> list[list[BMFace]]:
    bmfs_set : set[BMFace] = set(bmfs)
    network : dict[BMFace, set[BMFace]] = {
        bmf: {
            bme.link_faces[0] if bme.link_faces[1] == bmf else bme.link_faces[1]
            for bme in bmf.edges
            if len(bme.link_faces) == 2 and all(bmef in bmfs for bmef in bme.link_faces)
        }
        for bmf in bmfs_set
    }
    strips : list[list[BMFace]] = []
    working : set[BMFace] = { bmf for bmf in bmfs_set if len(network[bmf]) == 1 }
    touched : set[BMFace] = set()

    while working:
        pre : None | BMFace = None
        cur : BMFace = working.pop()

        if cur in touched:
            continue

        strip : list[BMFace] = [ cur ]

        while True:
            bmfs_next : list[BMFace] = [
                bmf_next
                for bmf_next in network[cur]
                if not pre or len(set(bmf_next.verts) & set(pre.verts)) == 0
            ]

            if not bmfs_next:
                break

            pre, cur = cur, bmfs_next[0]
            strip.append(cur)

        touched |= set(strip)
        strips.append(strip)

    return strips

def create_quadstrip_selection_overlay(
    opname : str,
    rftool_idname : str,
    idname : str,
    label : str,
    _only_boundary : bool,  # TODO: this is unused??
) -> type[RFOverlay_Base]:

    overlay_names.add(label)

    class RFOperator_QuadStrip_Selection_Overlay(RFOverlay_Base):
        bl_idname : ClassVar[str] = f'retopoflow.{idname}'
        bl_label : ClassVar[str] = label
        bl_description : ClassVar[str] = 'Overlay info about selected loops and strips'
        bl_options : ClassVar[set[str]] = { 'INTERNAL' }

        instance : ClassVar[object | None] = None
        depsgraph_version : ClassVar[int] = -42
        paused_update : ClassVar[bool] = False
        paused_overlay : ClassVar[bool] = False

        hovering : tuple[int, int, list[Vector]] | None = None  # needed for very first start

        selected_strips : list[list[Vector]]
        strips_indices : list[list[int]]
        curves : list[CubicBezier]

        @classmethod
        def pause_update(cls):
            cls.paused_update = True
        @classmethod
        def unpause_update(cls):
            cls.paused_update = False

        @classmethod
        def pause_overlay(cls):
            cls.paused_overlay = True
        @classmethod
        def unpause_overlay(cls):
            cls.paused_overlay = False

        @classmethod
        def activate(cls):
            _ = bpy_ops_retopoflow(idname, 'INVOKE_DEFAULT')

        def __init__(self, *args : ..., **kwargs : dict[str, ...]):
            super().__init__(*args, **kwargs)

            cls = type(self)
            cls.instance = self
            cls.depsgraph_version = -42
            self.selected_strips = []
            self.strips_indices = []
            self.curves = []

        def init(self, _context : Context, _event : Event):
            cls = type(self)
            cls.depsgraph_version = -42
            cls.instance = self

        def finish(self, _context : Context):
            cls = type(self)
            cls.instance = None

        def update(self, context : Context, event : Event) -> set[str]:
            RFCore = RFGlobals.RFCore_None
            if not RFCore:
                return {'CANCELLED'}

            is_done = (RFCore.selected_RFTool_idname != rftool_idname)
            if is_done:
                return {'CANCELLED'}

            if self.paused_overlay:
                return {'PASS_THROUGH'}

            mouse = mouse_from_event(event)
            was_hovering = self.hovering
            self.hovering = self.hovered_handle(context, mouse)
            if self.hovering:
                if not was_hovering:
                    self.set_statusbar_override(('LMB: Edit Strip', ))
                Cursors.set('hand')
            else:
                if was_hovering:
                    self.set_statusbar_override(None)
                Cursors.restore()

            return {'PASS_THROUGH'}


        def update_data(self, context : Context) -> bool:
            RFCore = RFGlobals.RFCore_None
            if not RFCore: return False
            if self.depsgraph_version == RFCore.depsgraph_version and hasattr(self, 'curves'): return True
            if self.paused_update: return False

            # depsgraph changed, so recollect quad details

            cls = type(self)
            cls.depsgraph_version = RFCore.depsgraph_version

            # find selected quad strips
            bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)

            # only considering selected quads
            sel_bmfs = [ bmf for bmf in bmops.get_all_selected_bmfaces(bm) if len(bmf.edges) == 4 ]
            if len(sel_bmfs) > 1000:
                # too many to be useful
                self.selected_strips = []
                self.strips_indices = []
                self.curves = []
                return False

            # crawl sel_bmfs to find strips
            strips = get_quadstrips(sel_bmfs)
            self.selected_strips = [
                [ bmf_midpoint(strip[0]) ] +
                [
                    bme_midpoint(bme01)
                    for (bmf0, bmf1) in iter_pairs(strip, False)
                    if (bme01 := bmfs_shared_bme(bmf0, bmf1))
                ] +
                [ bmf_midpoint(strip[-1]) ]
                for strip in strips
            ]
            self.strips_indices = [
                [ bmf.index for bmf in strip ]
                for strip in strips
            ]
            self.curves = [
                CubicBezier.create_from_points(strip)
                for strip in self.selected_strips
            ]

            return True

        def hovered_handle(
            self,
            context : Context,
            mouse : Sequence[float] | Vector,
            *,
            distance2D : float = 10,
        ) -> tuple[int, int, list[Vector]] | None:
            if not context.edit_object:
                return None
            if not self.update_data(context):
                return None
            rgn, r3d = context.region, context.region_data
            if not r3d:
                return None
            m = Vector(mouse)
            M : Matrix = context.edit_object.matrix_world
            d = Drawing.scale(distance2D)
            if d is None:
                return None
            for i, curve in enumerate(self.curves):
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ curve.p0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ curve.p1)
                pt2 = location_3d_to_region_2d(rgn, r3d, M @ curve.p2)
                pt3 = location_3d_to_region_2d(rgn, r3d, M @ curve.p3)
                if not pt0 or not pt1 or not pt2 or not pt3:
                    continue
                prev = [curve.p0, curve.p1, curve.p2, curve.p3]
                if (pt0 - m).length < d:
                    return (i, 0, prev)
                if (pt1 - m).length < d:
                    return (i, 1, prev)
                if (pt2 - m).length < d:
                    return (i, 2, prev)
                if (pt3 - m).length < d:
                    return (i, 3, prev)
            return None

        def draw_postpixel_overlay(self):
            RFCore = RFGlobals.RFCore_None
            if not RFCore: return
            is_done = (RFCore.selected_RFTool_idname != rftool_idname)
            if is_done: return
            if self.paused_overlay: return

            context = bpy.context
            if not context.edit_object:
                return
            if not self.update_data(context):
                return

            for strip in self.selected_strips:
                lbl_pos = get_label_pos(bpy.context, strip)
                if not lbl_pos: continue
                text = f'Strip: {len(strip)-1}'
                tw, th = Drawing.get_text_width(text), Drawing.get_text_height(text)
                lbl_pos -= Vector((tw / 2, -th / 2))
                Drawing.text_draw2D(text, lbl_pos.xy, color=(1,1,0,1), dropshadow=(0,0,0,0.75))

            M = context.edit_object.matrix_world
            rgn, r3d = context.region, context.region_data
            for curve in self.curves:
                pts = [
                    location_3d_to_region_2d(rgn, r3d, M @ curve.eval(v / 20))
                    for v in range(21)
                ]
                Drawing.draw2D_linestrip(context, pts, (1.0, 1.0, 0.0, 0.5), width=2, stipple=[5,5])
                pts = [
                    location_3d_to_region_2d(rgn, r3d, M @ curve.p0),
                    location_3d_to_region_2d(rgn, r3d, M @ curve.p1),
                    location_3d_to_region_2d(rgn, r3d, M @ curve.p2),
                    location_3d_to_region_2d(rgn, r3d, M @ curve.p3),
                ]
                Drawing.draw2D_lines(context, pts, (1.0, 1.0, 1.0, 0.5), width=2)
                Drawing.draw2D_points(context, [pts[0], pts[3]], (1.0, 1.0, 1.0, 1.0), radius=16, border=2, borderColor=(0,0,0,0.5))
                Drawing.draw2D_points(context, [pts[1], pts[2]], (0.0, 0.0, 0.0, 0.75), radius=16, border=2, borderColor=(1,1,1,0.5))

    return type(opname, (RFOperator_QuadStrip_Selection_Overlay, RFOperator), {})
