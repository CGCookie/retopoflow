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
import time
from typing import List
from enum import Enum

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, get_select_layers, NearestBMVert
from ..common.operator import invoke_operator, execute_operator, RFOperator
from ..common.raycast import raycast_mouse_valid_sources, raycast_point_valid_sources
from ..common.maths import view_forward_direction
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import clamp
from ...addon_common.common.utils import iter_pairs

from ..rfoperators.transform import RFOperator_Translate

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

class PP_Action(Enum):
    NONE = -1
    VERT = 0
    VERT_EDGE = 1
    EDGE_TRIANGLE = 2



def distance_point_linesegment(pt, p0, p1):
    dv = p1 - p0
    ld = dv.length
    if abs(ld) <= 0.00001:
        p = p0
    else:
        dd = dv / ld
        v = pt - p0
        p = p0 + dd * clamp(dd.dot(v), 0.05, ld * 0.95)
    return (pt - p).length

def distance_point_bmedge(pt, bme):
    bmv0, bmv1 = bme.verts
    return distance_point_linesegment(pt, bmv0.co, bmv1.co)

def distance2d_point_bmedge(context, matrix, pt, bme):
    bmv0, bmv1 = bme.verts
    p  = matrix @ pt
    p0 = matrix @ bmv0.co
    p1 = matrix @ bmv1.co
    return distance_point_linesegment(p, p0, p1)


class PP_Logic:
    def __init__(self, context, event):
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.update_bmesh_selection = False
        self.mouse = None
        self.reset()
        self.update(context, event, None)

    def reset(self):
        self.bm = None
        self.em = None
        self.nearest = None
        self.selected = None

    def update(self, context, event, insert_mode):
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
            # bpy.ops.mesh.normals_make_consistent('EXEC_DEFAULT', False)
            bpy.ops.ed.undo_push(message='Selected geometry after move')
            self.selected = None

        if self.nearest is None or not self.nearest.is_valid:
            self.nearest = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv)

        if self.selected is None:
            self.selected = bmops.get_all_selected(self.bm)

        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        # update commit data structure with mouse position
        self.state = PP_Action.NONE
        self.hit = raycast_mouse_valid_sources(context, event, world=False)
        if not self.hit:
            # Cursors.restore()
            return
        # Cursors.set('NONE')

        self.nearest.update(context, self.hit)
        if self.nearest.bmv:
            self.hit = self.nearest.bmv.co

        # TODO: update previsualizations

        if len(self.selected[BMVert]) == 0:
            self.state = PP_Action.VERT

        elif len(self.selected[BMEdge]) == 0 or insert_mode == 'EDGE-ONLY':
            self.state = PP_Action.VERT_EDGE
            self.bmv = min(
                self.selected[BMVert],
                key=(lambda bmv:(self.hit - bmv.co).length),
            )

        elif len(self.selected[BMVert]) == 2 and len(self.selected[BMEdge]) == 1:
            self.state = PP_Action.EDGE_TRIANGLE
            self.bme = next(iter(self.selected[BMEdge]), None)

        elif len(self.selected[BMEdge]) > 1:
            self.state = PP_Action.EDGE_TRIANGLE
            self.bme = min(
                self.selected[BMEdge],
                key=(lambda bme:distance2d_point_bmedge(context, self.matrix_world, self.hit, bme)),
            )

    def draw(self, context):
        # draw previsualization
        if not self.mouse: return
        if not self.hit: return
        if not self.bm.is_valid: return
        if not self.nearest or not self.nearest.is_valid: return

        if self.nearest.bmv:
            co = self.matrix_world @ self.nearest.bmv.co
            p = location_3d_to_region_2d(context.region, context.region_data, co)
            with Drawing.draw(context, CC_2D_POINTS) as draw:
                draw.point_size(8)
                draw.border(width=2, color=Color4((40/255, 255/255, 40/255, 0.5)))
                draw.color(Color4((40/255, 255/255, 255/255, 0.0)))
                draw.vertex(p)


        match self.state:
            case PP_Action.VERT:
                pt = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.hit)
                if not pt: return
                if self.nearest.bmv: return

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(8)
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.vertex(pt)

            case PP_Action.VERT_EDGE:
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.bmv.co)
                pt = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.hit)
                if not (p0 and pt): return
                d = (pt - p0).normalized() * Drawing.scale(8)

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(8)

                    if not self.nearest.bmv:
                        draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                        draw.vertex(pt)

                    draw.border(width=2, color=Color4((40/255, 255/255, 40/255, 0.5)))
                    draw.color(Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.vertex(p0)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.vertex(p0 + d).vertex(pt - d)

            case PP_Action.EDGE_TRIANGLE:
                bmv0, bmv1 = self.bme.verts
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                pt = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.hit)
                if not (p0 and p1 and pt): return
                d0t = (pt - p0).normalized() * Drawing.scale(8)
                d1t = (pt - p1).normalized() * Drawing.scale(8)
                d01 = (p1 - p0).normalized() * Drawing.scale(8)

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(8)

                    if not self.nearest.bmv:
                        draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                        draw.vertex(pt)

                    draw.border(width=2, color=Color4((40/255, 255/255, 40/255, 0.5)))
                    draw.color(Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.vertex(p0)
                    draw.vertex(p1)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=Color4((40/255, 255/255, 40/255, 0.0)))

                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
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
        context.tool_settings.mesh_select_mode[0] = True

        select_now = []     # to be selected before move
        select_later = []   # to be selected after move

        match self.state:
            case PP_Action.VERT:
                if self.nearest.bmv:
                    bmv = self.nearest.bmv
                else:
                    bmv = self.bm.verts.new(self.hit)
                select_now = [bmv]

            case PP_Action.VERT_EDGE:
                bmv0 = self.bmv
                if self.nearest.bmv:
                    bmv1 = self.nearest.bmv
                else:
                    bmv1 = self.bm.verts.new(self.hit)
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
                    bmv = self.bm.verts.new(self.hit)
                bmf = next(iter(bmops.shared_link_faces([bmv0, bmv1, bmv])), None)
                if not bmf:
                    bmf = self.bm.faces.new((bmv0,bmv1,bmv))
                    bmf.normal_update()
                    if view_forward_direction(context).dot(bmf.normal) > 0:
                        bmf.normal_flip()
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
        self.selected = None

        bmops.flush_selection(self.bm, self.em)

        bpy.ops.retopoflow.translate('INVOKE_DEFAULT', False)

        # NOTE: the select-later property is _not_ transferred to the vert into which the moved vert is auto-merged...
        #       this is handled if a BMEdge or BMFace is to be selected later, but it is not handled if only a BMVert
        #       is created and then merged into existing geometry

