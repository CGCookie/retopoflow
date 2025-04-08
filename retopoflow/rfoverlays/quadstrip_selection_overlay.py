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
import bmesh
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d

from ..common.operator import RFOperator
from ..common.bmesh import get_bmesh_emesh, bme_midpoint, get_boundary_strips_cycles, bmfs_shared_bme, quad_bmf_opposite_bme
from ..common.drawing import Drawing
from ..common.maths import point_to_bvec4, view_forward_direction
from ..common.raycast import is_point_hidden, mouse_from_event, nearest_point_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bezier import CubicBezier
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.maths import Frame
from ...addon_common.common.utils import iter_pairs


def get_label_pos(context, strip):
    M = context.edit_object.matrix_world
    rgn, r3d = context.region, context.region_data

    centers = [pt for pt in strip if not is_point_hidden(context, pt)]
    if len(centers) == 0: return None

    mid = sum(centers, Vector((0,0,0))) / len(centers)
    pt3d = min(centers, key=lambda pt:(pt - mid).length)
    return location_3d_to_region_2d(rgn, r3d, M @ pt3d)

def get_quadstrips(bmfs):
    bmfs = set(bmfs)
    network = {
        bmf: {
            bme.link_faces[0] if bme.link_faces[1] == bmf else bme.link_faces[1]
            for bme in bmf.edges
            if len(bme.link_faces) == 2 and all(bmef in bmfs for bmef in bme.link_faces)
        }
        for bmf in bmfs
    }
    strips = []
    working = { bmf for bmf in bmfs if len(network[bmf]) == 1 }
    touched = set()
    while working:
        pre, cur = None, working.pop()
        if cur in touched: continue
        strip = [ cur ]
        while True:
            bmfs_next = [ n for n in network[cur] if not pre or len(set(n.verts) & set(pre.verts)) == 0 ]
            if not bmfs_next: break
            pre, cur = cur, bmfs_next[0]
            strip += [ cur ]
        touched |= set(strip)
        strips += [strip]
    return strips

def create_quadstrip_selection_overlay(opname, rftool_idname, idname, label, only_boundary):
    paused_update = False
    paused_overlay = False

    class RFOperator_QuadStrip_Selection_Overlay:
        bl_idname = f'retopoflow.{idname}'
        bl_label = label
        bl_description = 'Overlay info about selected loops and strips'
        bl_options = { 'INTERNAL' }

        instance = None
        hovering = None  # needed for very first start

        @staticmethod
        def pause_update(): nonlocal paused_update; paused_update = True
        @staticmethod
        def unpause_update(): nonlocal paused_update; paused_update = False

        @staticmethod
        def pause_overlay(): nonlocal paused_overlay; paused_overlay = True
        @staticmethod
        def unpause_overlay(): nonlocal paused_overlay; paused_overlay = False

        @staticmethod
        def activate():
            op_self = getattr(bpy.ops.retopoflow, idname)
            op_self('INVOKE_DEFAULT')

        def init(self, context, event):
            self.depsgraph_version = None
            type(self).instance = self

        def finish(self, context):
            type(self).instance = None

        def update(self, context, event):
            is_done = (self.RFCore.selected_RFTool_idname != rftool_idname)
            if is_done: return {'CANCELLED'}
            if paused_overlay: return {'PASS_THROUGH'}

            mouse = mouse_from_event(event)
            self.hovering = self.hovered_handle(context, mouse)
            if self.hovering: Cursors.set('hand')
            else:             Cursors.restore()

            return {'PASS_THROUGH'}


        def update_data(self):
            nonlocal paused_update
            if self.depsgraph_version == self.RFCore.depsgraph_version and hasattr(self, 'curves'): return True
            if paused_update: return False

            # depsgraph changed, so recollect quad details

            self.depsgraph_version = self.RFCore.depsgraph_version

            # find selected quad strips
            bm, _ = get_bmesh_emesh(bpy.context, ensure_lookup_tables=True)
            # only considering selected quads
            sel_bmfs = [ bmf for bmf in bmops.get_all_selected_bmfaces(bm) if len(bmf.edges) == 4 ]
            if len(sel_bmfs) > 1000:
                # too many to be useful
                self.selected_strips = []
                self.strips_indices = []
                self.curves = []
                return
            # crawl sel_bmfs to find strips
            strips = get_quadstrips(sel_bmfs)
            self.selected_strips = [
                [
                    bme_midpoint(quad_bmf_opposite_bme(strip[0], bmfs_shared_bme(strip[0], strip[1])))
                ] + [
                    bme_midpoint(bmfs_shared_bme(bmf0, bmf1))
                    for (bmf0, bmf1) in iter_pairs(strip, False)
                ] + [
                    bme_midpoint(quad_bmf_opposite_bme(strip[-1], bmfs_shared_bme(strip[-1], strip[-2])))
                ]
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

        def hovered_handle(self, context, mouse, *, distance2D=10):
            if not self.update_data(): return False
            rgn, r3d = context.region, context.region_data
            if not r3d: return False
            mouse = Vector(mouse)
            M = context.edit_object.matrix_world
            d = Drawing.scale(distance2D)
            for i, curve in enumerate(self.curves):
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ curve.p0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ curve.p1)
                pt2 = location_3d_to_region_2d(rgn, r3d, M @ curve.p2)
                pt3 = location_3d_to_region_2d(rgn, r3d, M @ curve.p3)
                prev = [curve.p0, curve.p1, curve.p2, curve.p3]
                if (pt0 - mouse).length < d: return (i, 0, prev)
                if (pt1 - mouse).length < d: return (i, 1, prev)
                if (pt2 - mouse).length < d: return (i, 2, prev)
                if (pt3 - mouse).length < d: return (i, 3, prev)
            return None

        def draw_postpixel_overlay(self):
            is_done = (self.RFCore.selected_RFTool_idname != rftool_idname)
            if is_done: return
            if paused_overlay: return

            if not self.update_data(): return

            for strip in self.selected_strips:
                lbl_pos = get_label_pos(bpy.context, strip)
                if not lbl_pos: continue
                text = f'Strip: {len(strip)-1}'
                tw, th = Drawing.get_text_width(text), Drawing.get_text_height(text)
                lbl_pos -= Vector((tw / 2, -th / 2))
                Drawing.text_draw2D(text, lbl_pos.xy, color=(1,1,0,1), dropshadow=(0,0,0,0.75))
            context = bpy.context
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
