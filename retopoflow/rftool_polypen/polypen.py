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

import blf
import bmesh
import bpy
import gpu
from bmesh.types import BMVert, BMEdge, BMFace
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

import math
from typing import List
from enum import Enum

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, get_select_layers
from ..common.operator import invoke_operator, execute_operator, RFOperator
from ..common.raycast import raycast_mouse_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import clamp
from ...addon_common.common.utils import iter_pairs

from ..common.drawing import (
    Drawing,
    CC_2D_POINTS,
    CC_2D_LINES,
    CC_2D_LINE_STRIP,
    CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES,
    CC_2D_TRIANGLE_FAN,
    CC_3D_TRIANGLES,
)

reseter = Reseter()

translate_options = {
    # 'snap': True,
    'use_snap_project': True,
    'use_snap_self': False, # True,
    'use_snap_edit': False, # True,
    'use_snap_nonedit': True,
    'use_snap_selectable': True,
    'snap_elements': {'FACE_PROJECT', 'FACE_NEAREST'}, #, 'VERTEX'},
    'snap_target': 'CLOSEST',
    # 'release_confirm': True,
}

class PP_Action(Enum):
    NONE = -1
    VERT = 0
    VERT_EDGE = 1
    EDGE_TRIANGLE = 2



triangle_inds = []
def verts_to_triangles(count):
    global triangle_inds
    if count > len(triangle_inds):
        triangle_inds = [[i,i,i] for i in range(count*2)]
    return triangle_inds[:count]

class NearestBMVert:
    def __init__(self, bm, matrix, matrix_inv):
        self.bm = bm
        self.matrix = matrix
        self.matrix_inv = matrix_inv
        self.bm.verts.ensure_lookup_table()
        self.bm.edges.ensure_lookup_table()
        self.bm.faces.ensure_lookup_table()

        # assuming there are relatively few loose bmvs (bmvert that is not part of a bmface)
        self.loose_bmvs = [bmv for bmv in self.bm.verts if not bmv.link_faces]
        loose_bmv_cos = [bmv.co for bmv in self.loose_bmvs]

        self.bvh_verts = BVHTree.FromPolygons(loose_bmv_cos, verts_to_triangles(len(self.loose_bmvs)), all_triangles=True)
        self.bvh_faces = BVHTree.FromBMesh(self.bm)

        self.bmv = None

    @property
    def is_valid(self):
        return all((
            self.bm.is_valid,
            (self.bmv is None or self.bmv.is_valid),
            all(bmv.is_valid for bmv in self.loose_bmvs),
        ))

    def update(self, context, co, *, distance=1.84467e19, distance2d=10):
        # NOTE: distance here is local to object!!!  target object could be scaled!
        # even stranger is if target is non-uniformly scaled

        self.bmv = None
        if not self.is_valid: return

        bmv_co, bmv_norm, bmv_idx, bmv_dist = self.bvh_verts.find_nearest(co, distance) # distance=1.0
        bmf_co, bmf_norm, bmf_idx, bmf_dist = self.bvh_faces.find_nearest(co, distance) # distance=1.0

        bmvs = []
        if bmv_idx is not None: bmvs += [self.loose_bmvs[bmv_idx]]
        if bmf_idx is not None: bmvs += self.bm.faces[bmf_idx].verts
        bmvs = [bmv for bmv in bmvs if not bmv.select]
        if not bmvs: return

        inf = float('inf')
        co2d = location_3d_to_region_2d(context.region, context.region_data, self.matrix @ co)
        co2ds = [location_3d_to_region_2d(context.region, context.region_data, self.matrix @ bmv.co) for bmv in bmvs]
        dists = [(co2d - co2d_).length if co2d_ else inf for co2d_ in co2ds]
        bmv,dist = min(zip(bmvs, dists), key=(lambda bmv_dist: bmv_dist[1]))
        if dist <= Drawing.scale(distance2d):
            self.bmv = bmv

def distance_point_linesegment(pt, p0, p1):
    dv = p1 - p0
    ld = dv.length
    if abs(ld) <= 0.00001:
        p = p0
    else:
        dd = dv / ld
        v = pt - p0
        p = p0 + dd * clamp(dd.dot(v), 0, ld)
    return (pt - p).length
def distance_point_bmedge(pt, bme):
    bmv0, bmv1 = bme.verts
    return distance_point_linesegment(pt, bmv0.co, bmv1.co)

class PP_Logic:
    def __init__(self, context, event):
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.update_bmesh_selection = False
        self.mouse = None
        self.reset()
        self.update(context, event)

    def reset(self):
        self.bm = None
        self.em = None
        self.nearest = None
        self.selected = None

    def update(self, context, event):
        # update previsualization and commit data structures with mouse position
        # ex: if triangle is selected, determine which edge to split to make quad
        # print('UPDATE')

        if not self.bm or not self.bm.is_valid:
            self.bm, self.em = get_bmesh_emesh(context)
            self.layer_sel_vert, self.layer_sel_edge, self.layer_sel_face = get_select_layers(self.bm)
            self.selected = None
            self.nearest = None

        if self.update_bmesh_selection:
            self.update_bmesh_selection = False
            for bmv in self.bm.verts:
                bmv.select_set(bmv[self.layer_sel_vert] == 1)
                bmv[self.layer_sel_vert] = 0
            for bme in self.bm.edges:
                if bme[self.layer_sel_edge] == 0: continue
                for bmv in bme.verts:
                    bmv.select_set(True)
                bme[self.layer_sel_edge] = 0
            for bmf in self.bm.faces:
                if bmf[self.layer_sel_face] == 0: continue
                for bmv in bmf.verts:
                    bmv.select_set(True)
                bmf[self.layer_sel_face] = 0
            bmops.flush_selection(self.bm, self.em)
            bpy.ops.mesh.normals_make_consistent('EXEC_DEFAULT', False)
            bpy.ops.ed.undo_push(message='Selected geometry after move')
            self.selected = None

        if self.nearest is None or not self.nearest.is_valid:
            self.nearest = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv)

        if self.selected is None:
            self.selected = bmops.get_all_selected(self.bm)

        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        # update commit data structure with mouse position
        self.state = PP_Action.NONE
        self.hit = raycast_mouse_valid_sources(context, event)
        if not self.hit:
            # Cursors.restore()
            return
        # Cursors.set('NONE')

        self.nearest.update(context, self.matrix_world_inv @ self.hit)
        if self.nearest.bmv:
            # co = self.matrix_world @ self.nearest.bmv.co
            # p = location_3d_to_region_2d(context.region, context.region_data, co)
            # if (p - self.mouse).length < Drawing.scale(10):
            #     self.hit = self.nearest.bmv.co
            self.hit = self.nearest.bmv.co

        # TODO: update previsualizations

        if len(self.selected[BMVert]) == 0:
            self.state = PP_Action.VERT

        elif len(self.selected[BMVert]) == 1:
            self.state = PP_Action.VERT_EDGE
            self.bmv = next(iter(self.selected[BMVert]), None)

        elif len(self.selected[BMVert]) == 2 and len(self.selected[BMEdge]) == 1:
            self.state = PP_Action.EDGE_TRIANGLE
            self.bme = next(iter(self.selected[BMEdge]), None)

        elif len(self.selected[BMEdge]) > 1:
            self.state = PP_Action.EDGE_TRIANGLE
            # SHOULD CHECK IN SCREEN
            self.bme = min(self.selected[BMEdge], key=lambda bme:distance_point_bmedge(self.hit, bme))

    def draw(self, context):
        # draw previsualization
        if not self.mouse: return
        if not self.hit: return
        if not self.bm.is_valid: return
        if not self.nearest or not self.nearest.is_valid: return

        if self.nearest.bmv:
            co = self.matrix_world @ self.nearest.bmv.co
            p = location_3d_to_region_2d(context.region, context.region_data, co)
            # if (p - self.mouse).length < Drawing.scale(10):
            #     with Drawing.draw(context, CC_2D_POINTS) as draw:
            #         draw.point_size(8)
            #         draw.border(width=2, color=Color4((40/255, 255/255, 255/255, 0.5)))
            #         draw.color(Color4((40/255, 255/255, 255/255, 0.0)))
            #         # print((self.hit, self.nearest.co))
            #         draw.vertex(p)
            with Drawing.draw(context, CC_2D_POINTS) as draw:
                draw.point_size(8)
                draw.border(width=2, color=Color4((40/255, 255/255, 255/255, 0.5)))
                draw.color(Color4((40/255, 255/255, 255/255, 0.0)))
                draw.vertex(p)


        match self.state:
            case PP_Action.VERT:
                pt = location_3d_to_region_2d(context.region, context.region_data, self.hit)
                if not pt: return
                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(8)
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.vertex(pt)

            case PP_Action.VERT_EDGE:
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.bmv.co)
                pt = location_3d_to_region_2d(context.region, context.region_data, self.hit)
                if not (p0 and pt): return
                d = (pt - p0).normalized() * Drawing.scale(8)
                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(8)
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.vertex(pt)

                    draw.border(width=2, color=Color4((40/255, 255/255, 40/255, 0.5)))
                    draw.color(Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.vertex(p0)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.vertex(p0 + d).vertex(pt - d)

            case PP_Action.EDGE_TRIANGLE:
                bmv0, bmv1 = self.bme.verts
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                pt = location_3d_to_region_2d(context.region, context.region_data, self.hit)
                if not (p0 and p1 and pt): return
                d0t = (pt - p0).normalized() * Drawing.scale(8)
                d1t = (pt - p1).normalized() * Drawing.scale(8)
                d01 = (p1 - p0).normalized() * Drawing.scale(8)

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(8)
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.vertex(pt)

                    draw.border(width=2, color=Color4((40/255, 255/255, 40/255, 0.5)))
                    draw.color(Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.vertex(p0)
                    draw.vertex(p1)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.vertex(p0 + d0t).vertex(pt - d0t)
                    draw.vertex(p1 + d1t).vertex(pt - d1t)

                    draw.color(Color4((40/255, 255/255, 40/255, 0.5)))
                    draw.vertex(p0 + d01).vertex(p1 - d01)

                with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                    draw.color(Color4((40/255, 255/255, 40/255, 0.25)))
                    draw.vertex(pt).vertex(p0).vertex(p1)

            case _:
                pass


    def commit(self, context, event):
        # apply the change

        if self.state == PP_Action.NONE: return

        # make sure artist can see the vert
        bpy.ops.mesh.select_mode(type='VERT', use_extend=True, action='ENABLE')

        select_now = []     # to be selected before move
        select_later = []   # to be selected after move

        match self.state:
            case PP_Action.VERT:
                if self.nearest.bmv:
                    bmv = self.nearest.bmv
                else:
                    bmv = self.bm.verts.new(self.matrix_world_inv @ self.hit)
                select_now = [bmv]

            case PP_Action.VERT_EDGE:
                bmv0 = self.bmv
                if self.nearest.bmv:
                    bmv1 = self.nearest.bmv
                else:
                    bmv1 = self.bm.verts.new(self.matrix_world_inv @ self.hit)
                bme = next(iter(bmops.shared_link_edges([bmv0, bmv1])), None)
                if not bme:
                    bme = self.bm.edges.new((bmv0, bmv1))
                select_now = [bmv1]
                select_later = [bme]

            case PP_Action.EDGE_TRIANGLE:
                bmv0, bmv1 = self.bme.verts
                if self.nearest.bmv:
                    bmv = self.nearest.bmv
                else:
                    bmv = self.bm.verts.new(self.matrix_world_inv @ self.hit)
                bmf = next(iter(bmops.shared_link_faces([bmv0, bmv1, bmv])), None)
                if not bmf:
                    bmf = self.bm.faces.new((bmv0,bmv1,bmv))
                select_now = [bmv]
                select_later = [bmf]

            case _:
                assert False, f'Unhandled PolyPen state {self.state}'

        bmops.deselect_all(self.bm)
        for bmelem in select_now:
            bmelem.select_set(True)
        for bmelem in select_later:
            match bmelem:
                case BMVert():
                    bmelem[self.layer_sel_vert] = 1
                case BMEdge():
                    bmelem[self.layer_sel_edge] = 1
                    for bmv in bmelem.verts:
                        bmv[self.layer_sel_vert] = 1
                case BMFace():
                    bmelem[self.layer_sel_face] = 1
                    for bmv in bmelem.verts:
                        bmv[self.layer_sel_vert] = 1
        self.update_bmesh_selection = bool(select_later)
        self.nearest = None
        self.hit = None

        bmops.flush_selection(self.bm, self.em)

        bpy.ops.transform.transform('INVOKE_DEFAULT', False, mode='TRANSLATION', snap=not event.ctrl, **translate_options)
        # NOTE: the select-later property is _not_ transferred to the vert into which the moved vert is auto-merged...
        #       this is handled if a BMEdge or BMFace is to be selected later, but it is not handled if only a BMVert
        #       is created and then merged into existing geometry


class RFOperator_PolyPen(RFOperator):
    bl_idname = "retopoflow.polypen"
    bl_label = 'PolyPen'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymap = {'type': 'LEFT_CTRL', 'value': 'PRESS'}
    rf_status = ['LMB: Insert', 'MMB: (nothing)', 'RMB: (nothing)']

    def init(self, context, event):
        print(f'STARTING POLYPEN')
        self.logic = PP_Logic(context, event)
        context.area.tag_redraw()
        self.last_op = None

    def reset(self):
        self.logic.reset()

    def update(self, context, event):
        self.logic.update(context, event)

        if not event.ctrl:
            print(F'LEAVING POLYPEN')
            return {'FINISHED'}

        if event.type == 'LEFTMOUSE':
            self.logic.commit(context, event)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            context.area.tag_redraw()

        return {'PASS_THROUGH'}

    def draw_postpixel(self, context):
        # print(f'post pixel')
        self.logic.draw(context)


class RFTool_PolyPen(RFTool_Base):
    bl_idname = "retopoflow.polypen"
    bl_label = "PolyPen"
    bl_description = "Create complex topology on vertex-by-vertex basis"
    bl_icon = "ops.generic.select_circle"
    bl_widget = None

    bl_keymap = (
        (RFOperator_PolyPen.bl_idname, RFOperator_PolyPen.rf_keymap, None),
    )

    @classmethod
    def activate(cls, context):
        reseter['context.tool_settings.use_mesh_automerge'] = True
        reseter['context.tool_settings.double_threshold'] = 0.01
        # reseter['context.tool_settings.snap_elements_base'] = {'VERTEX'}
        reseter['context.tool_settings.snap_elements_individual'] = {'FACE_PROJECT', 'FACE_NEAREST'}
        reseter['context.tool_settings.mesh_select_mode'] = [True, True, True]

    @classmethod
    def deactivate(cls, context):
        reseter.reset()
