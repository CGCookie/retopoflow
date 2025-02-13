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

from ..common.operator import RFOperator
from ..common.bmesh import get_bmesh_emesh, bme_midpoint, get_boundary_strips_cycles
from ..common.drawing import Drawing
from ..common.maths import point_to_bvec4
from ..common.raycast import is_point_hidden
from ...addon_common.common import bmesh_ops as bmops


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
    class RFOperator_QuadStrip_Selection_Overlay(RFOperator):
        bl_idname = f'retopoflow.{idname}'
        bl_label = label
        bl_description = 'Overlay info about selected loops and strips'
        bl_options = { 'INTERNAL' }

        @staticmethod
        def activate():
            getattr(bpy.ops.retopoflow, idname)('INVOKE_DEFAULT')

        def init(self, context, event):
            self.depsgraph_version = None

        def update(self, context, event):
            is_done = (self.RFCore.selected_RFTool_idname != rftool_idname)
            return {'CANCELLED'} if is_done else {'PASS_THROUGH'}

        def update_data(self):
            if self.depsgraph_version == self.RFCore.depsgraph_version: return

            # depsgraph changed, so recollect quad details

            self.depsgraph_version = self.RFCore.depsgraph_version

            # find selected quad strips
            bm, _ = get_bmesh_emesh(bpy.context)
            # only considering selected quads
            sel_bmfs = [ bmf for bmf in bmops.get_all_selected_bmfaces(bm) if len(bmf.edges) == 4 ]
            if len(sel_bmfs) > 1000:
                # too many to be useful
                self.selected_strips = []
                return
            # crawl sel_bmfs to find strips
            strips = get_quadstrips(sel_bmfs)
            self.selected_strips = [
                [ bmf.calc_center_median() for bmf in strip ]
                for strip in strips
            ]

        def draw_postpixel_overlay(self):
            is_done = (self.RFCore.selected_RFTool_idname != rftool_idname)
            if is_done: return

            self.update_data()

            for strip in self.selected_strips:
                lbl_pos = get_label_pos(bpy.context, strip)
                if not lbl_pos: continue
                text = f'Strip: {len(strip)}'
                tw, th = Drawing.get_text_width(text), Drawing.get_text_height(text)
                lbl_pos -= Vector((tw / 2, -th / 2))
                Drawing.text_draw2D(text, lbl_pos.xy, color=(1,1,0,1), dropshadow=(0,0,0,0.75))

            # # draw info about each selected boundary strip
            # for (lbl, boundaries) in zip(['Strip', 'Loop'], self.selected_boundaries):
            #     for boundary in boundaries:
            #         lbl_pos = get_label_pos(bpy.context, lbl, boundary)
            #         if not lbl_pos: continue
            #         text = f'{lbl}: {len(boundary)}'
            #         tw, th = Drawing.get_text_width(text), Drawing.get_text_height(text)
            #         lbl_pos -= Vector((tw / 2, -th / 2))
            #         Drawing.text_draw2D(text, lbl_pos.xy, color=(1,1,0,1), dropshadow=(0,0,0,0.75))
    RFOperator_QuadStrip_Selection_Overlay.__name__ = opname

    return RFOperator_QuadStrip_Selection_Overlay
