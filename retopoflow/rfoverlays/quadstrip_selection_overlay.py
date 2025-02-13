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
    class RFOperator_QuadStrip_Selection_Overlay(RFOperator):
        bl_idname = f'retopoflow.{idname}'
        bl_label = label
        bl_description = 'Overlay info about selected loops and strips'
        bl_options = { 'INTERNAL' }

        pause_overlay = False

        @staticmethod
        def activate():
            getattr(bpy.ops.retopoflow, idname)('INVOKE_DEFAULT')

        def init(self, context, event):
            self.depsgraph_version = None
            self.state = 'idle'

        def update(self, context, event):
            is_done = (self.RFCore.selected_RFTool_idname != rftool_idname)
            if is_done: return {'CANCELLED'}
            match self.state:
                case 'idle':
                    return self.update_idle(context, event)
                case 'grab':
                    return self.update_grab(context, event)

        def update_idle(self, context, event):
            if self.pause_overlay: return {'PASS_THROUGH'}

            mouse = mouse_from_event(event)
            hovering = self.hovered_handle(context, mouse)
            if hovering: Cursors.set('hand')
            else:        Cursors.restore()

            if hovering and event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                print('GRABBING!')
                self.state = 'grab'
                self.init_grab(context, event, mouse, hovering)
                return {'RUNNING_MODAL'}

            return {'PASS_THROUGH'}

        def init_grab(self, context, event, mouse, hovering):
            bm, _ = get_bmesh_emesh(bpy.context, ensure_lookup_tables=True)
            M, Mi = context.edit_object.matrix_world, context.edit_object.matrix_world.inverted()
            fwd = (Mi @ view_forward_direction(context)).normalized()
            curve = self.curves[hovering[0]]
            curve.tessellate_uniform()
            strip_inds = self.strips_indices[hovering[0]]
            bmfs = [ bm.faces[i] for i in strip_inds]
            bmvs = { bmv for bmf in bmfs for bmv in bmf.verts }
            # all data is local to edit!
            data = {}
            for bmv in bmvs:
                t = curve.approximate_t_at_point_tessellation(bmv.co)
                o = curve.eval(t)
                z = Vector(curve.eval_derivative(t)).normalized()
                f = Frame(o, x=fwd, z=z)
                data[bmv.index] = (t, f.w2l_point(bmv.co), Vector(bmv.co))
            self.grab = {
                'mouse':  Vector(mouse),
                'curve':  hovering[0],
                'handle': hovering[1],
                'prev':   hovering[2],
                'data':   data,
                'matrices': [M, Mi],
                'fwd': fwd,
            }

        def update_grab(self, context, event):
            curve = self.curves[self.grab['curve']]
            data = self.grab['data']
            bm, em = get_bmesh_emesh(bpy.context, ensure_lookup_tables=True)

            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                self.state = 'idle'
                print('DONE!')
                return {'RUNNING_MODAL'}  # CONTINUE RUNNING MODAL TO EAT EVENT!
            if event.type in {'ESC', 'RIGHTMOUSE'}:
                curve.p0, curve.p1, curve.p2, curve.p3 = self.grab['prev']
                for bmv_idx in data:
                    bm.verts[bmv_idx].co = data[bmv_idx][2]
                bmesh.update_edit_mesh(em)
                context.area.tag_redraw()
                self.state = 'idle'
                print('CANCELLED!')
                return {'RUNNING_MODAL'}  # CONTINUE RUNNING MODAL TO EAT EVENT!

            mouse = mouse_from_event(event)
            delta = Vector(mouse) - self.grab['mouse']
            rgn, r3d = context.region, context.region_data
            M, Mi = self.grab['matrices']
            fwd = self.grab['fwd']

            def xform(pt0_edit):
                pt0_world  = M @ pt0_edit
                pt0_screen = location_3d_to_region_2d(rgn, r3d, pt0_world)
                pt1_screen = pt0_screen + delta
                pt1_world  = region_2d_to_location_3d(rgn, r3d, pt1_screen, pt0_world)
                pt1_edit   = Mi @ pt1_world
                return pt1_edit

            p0, p1, p2, p3 = self.grab['prev']
            curve = self.curves[self.grab['curve']]
            if self.grab['handle'] == 0: curve.p0, curve.p1 = xform(p0), xform(p1)
            if self.grab['handle'] == 1: curve.p1 = xform(p1)
            if self.grab['handle'] == 2: curve.p2 = xform(p2)
            if self.grab['handle'] == 3: curve.p2, curve.p3 = xform(p2), xform(p3)

            for bmv_idx in data:
                bmv = bm.verts[bmv_idx]
                t, pt, _ = data[bmv_idx]
                o = curve.eval(t)
                z = Vector(curve.eval_derivative(t)).normalized()
                f = Frame(o, x=fwd, z=z)
                bmv.co = nearest_point_valid_sources(context, M @ f.l2w_point(pt), world=False)

            bmesh.update_edit_mesh(em)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        def update_data(self):
            if self.depsgraph_version == self.RFCore.depsgraph_version: return
            if self.state == 'grab': return

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
            print(self.curves)

        def hovered_handle(self, context, mouse, *, distance2D=10):
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
            if self.pause_overlay: return

            self.update_data()

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
                Drawing.draw2D_linestrip(context, pts, (0.1, 1.0, 0.1, 0.5), width=2)
                pts = [
                    location_3d_to_region_2d(rgn, r3d, M @ curve.p0),
                    location_3d_to_region_2d(rgn, r3d, M @ curve.p1),
                    location_3d_to_region_2d(rgn, r3d, M @ curve.p2),
                    location_3d_to_region_2d(rgn, r3d, M @ curve.p3),
                ]
                Drawing.draw2D_points(context, pts, (1.0, 1.0, 0.1, 1.0), radius=8)
                Drawing.draw2D_linestrip(context, pts, (1.0, 1.0, 0.1, 0.5), width=1)

    RFOperator_QuadStrip_Selection_Overlay.__name__ = opname

    return RFOperator_QuadStrip_Selection_Overlay
