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

import bpy
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.types import Context, Event

from typing import ClassVar
from collections.abc import Sequence

from .overlays import overlay_names

from ..common.bpy_helper import bpy_ops_retopoflow
from ..rfglobals import RFGlobals
from ..rfoverlay_base import RFOverlay_Base
from ..common.operator import RFOperator
from ..common.bmesh import get_bmesh_emesh, bme_midpoint, get_boundary_strips_cycles
from ..common.drawing import Drawing
from ..common.raycast import is_point_hidden
from ...addon_common.common import bmesh_ops as bmops


def get_label_pos(context : Context, label : str, mids : Sequence[Vector], corners : Sequence[Vector]) -> Vector | None:
    if not context.edit_object:
        return None

    M = context.edit_object.matrix_world
    rgn, r3d = context.region, context.region_data

    boundary = [pt for pt in mids if not is_point_hidden(context, pt)]
    if len(boundary) == 0:
        boundary = [pt for pt in corners if not is_point_hidden(context, pt)]
        if len(boundary) == 0:
            return None

    match label:
        case 'Strip':
            mid = sum(boundary, Vector((0,0,0))) / len(boundary)
            pt3d = min(boundary, key=lambda pt:(pt - mid).length)
            return location_3d_to_region_2d(rgn, r3d, M @ pt3d)

        case 'Loop':
            pts2d = [pt2d for pt in boundary if (pt2d := location_3d_to_region_2d(rgn, r3d, M @ pt)) is not None]
            return max(pts2d, default=None, key=lambda pt2d:pt2d.y)

        case _:
            assert False, f'Unhandled {label=}'


def create_loopstrip_selection_overlay(
    opname : str,
    rftool_idname : str,
    idname : str,
    label : str,
    only_boundary : bool
) -> type[RFOverlay_Base]:

    overlay_names.add(label)

    class RFOperator_LoopStrip_Selection_Overlay(RFOverlay_Base):
        bl_idname : ClassVar[str] = f'retopoflow.{idname}'
        bl_label : ClassVar[str] = label
        bl_description : ClassVar[str] = 'Overlay info about selected loops and strips'
        bl_options : ClassVar[set[str]] = { 'INTERNAL' }

        depsgraph_version : None | int = None
        selected_boundaries : tuple[list[tuple[list[Vector], list[Vector]]], list[tuple[list[Vector], list[Vector]]]] = ([],[])

        def is_done(self):
            RFCore = RFGlobals.RFCore_None
            return RFCore.selected_RFTool_idname != rftool_idname if RFCore else True

        @classmethod
        def activate(cls):
            _ = bpy_ops_retopoflow(idname, 'INVOKE_DEFAULT')

        def init(self, _context : Context, _event : Event):
            self.depsgraph_version = None

        def update(self, _context : Context, _event : Event) -> set[str]:
            return {'CANCELLED'} if self.is_done() else {'PASS_THROUGH'}

        def draw_postpixel_overlay(self):
            RFCore = RFGlobals.RFCore_None
            if not RFCore:
                return

            if self.is_done():
                return

            if self.depsgraph_version != RFCore.depsgraph_version:
                # depsgraph changed, so recollect boundary details

                self.depsgraph_version = RFCore.depsgraph_version

                # find selected boundary strips
                bm, _ = get_bmesh_emesh(bpy.context)
                sel_bmes = [ bme for bme in bmops.get_all_selected_bmedges(bm) ]
                if only_boundary or any(bme.is_wire or bme.is_boundary for bme in sel_bmes):
                    # filter selected edges to only boundaries
                    sel_bmes = [ bme for bme in sel_bmes if bme.is_wire or bme.is_boundary ]
                if len(sel_bmes) < 1000:
                    bmes_strips, bmes_cycles = get_boundary_strips_cycles(sel_bmes)
                    strips = [
                        ([bme_midpoint(bme) for bme in strip], [bmv.co for bme in strip for bmv in bme.verts])
                        for strip in bmes_strips
                    ]
                    cycles = [
                        ([bme_midpoint(bme) for bme in cycle], [bmv.co for bme in cycle for bmv in bme.verts])
                        for cycle in bmes_cycles
                    ]
                    if len(strips) + len(cycles) <= 5:
                        self.selected_boundaries = (strips, cycles)
                    else:
                        self.selected_boundaries = ([], [])
                else:
                    self.selected_boundaries = ([], [])

            # draw info about each selected boundary strip
            is_vertex_select = bpy.context.tool_settings.mesh_select_mode[0]
            for (lbl, boundaries) in zip(['Strip', 'Loop'], self.selected_boundaries):
                for (mids, corners) in boundaries:
                    lbl_pos = get_label_pos(bpy.context, lbl, mids, corners)
                    if not lbl_pos:
                        continue
                    count = len(mids)
                    if is_vertex_select and lbl != 'Loop':
                        count += 1
                    if count == 1:
                        continue
                    text = f'{lbl}: {count}' if lbl == 'Loop' else str(count)
                    tw, th = Drawing.get_text_width(text), Drawing.get_text_height(text)
                    lbl_pos -= Vector((tw / 2, -th / 2))
                    Drawing.text_draw2D(text, lbl_pos.xy, color=(1,1,0,1), dropshadow=(0,0,0,0.75))

    return type(opname, (RFOperator_LoopStrip_Selection_Overlay, RFOperator), {})
