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
from bmesh.utils import edge_split
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_line_2d
from mathutils.bvhtree import BVHTree

import math
import time
from enum import auto
from typing import List

from ..preferences import RF_Prefs

from ..rftool_base import RFTool_Base
from ..common.bmesh import (
    get_bmesh_emesh,
    clean_select_layers,
    NearestBMVert,
    NearestBMEdge,
    has_mirror_x, has_mirror_y, has_mirror_z, mirror_threshold,
)
from ..common.bmesh_maths import is_bmvert_hidden
from ..common.enums import ValueIntEnum
from ..common.operator import invoke_operator, execute_operator, RFOperator
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event
from ..common.maths import (
    view_forward_direction,
    distance_point_linesegment,
    distance_point_bmedge,
    distance2d_point_bmedge,
    clamp, xform_direction,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.maths import intersection2d_line_line, sign_threshold
from ...addon_common.common.colors import Color4
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



class PP_Action(ValueIntEnum):
    NONE           = auto()  # do not do anything (could not determine what to do)
    VERT           = auto()  # insert new vert
    VERT_EDGE      = auto()  # extrude vert into edge
    EDGE_TRI       = auto()  # create triangle from selected edge and new/hovered vert
    EDGE_QUAD      = auto()  # create new edge and bridge with selected to create quad
    EDGE_QUAD_EDGE = auto()  # bridge selected and hover edge into quad
    TRI_QUAD       = auto()  # insert vert into edge of triangle to turn into quad
    EDGE_VERT      = auto()  # split hovered edge
    VERT_EDGE_EDGE = auto()  # split hovered edge and connect to nearest selected vert



class PP_Logic:
    def __init__(self, context, event):
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.update_bmesh_selection = False
        self.mouse = None
        self.insert_mode = None
        self.parallel_stable = None
        self.reset()
        self.update(context, event, None, 1.00)

    def reset(self):
        self.bm = None
        self.em = None
        self.nearest = None
        self.selected = None

    def cleanup(self):
        if not self.bm: return
        clean_select_layers(self.bm)

    def update(self, context, event, insert_mode, parallel_stable):
        # update previsualization and commit data structures with mouse position
        # ex: if triangle is selected, determine which edge to split to make quad
        # print('UPDATE')

        self.insert_mode = insert_mode
        self.parallel_stable = parallel_stable

        if not self.bm or not self.bm.is_valid:
            self.bm, self.em = get_bmesh_emesh(context)
            self.layer_sel_vert, self.layer_sel_edge, self.layer_sel_face = bmops.get_select_layers(self.bm)
            self.selected = None
            self.nearest = None
            self.nearest_bme = None

        if self.update_bmesh_selection:
            self.update_bmesh_selection = False
            self.bm.select_history.validate()
            active = self.bm.select_history.active
            for bmv in self.bm.verts:
                if bmv[self.layer_sel_vert] == 0: continue
                # bmv.select_set(bmv[self.layer_sel_vert] == 1)
                bmops.select(self.bm, bmv)
                bmv[self.layer_sel_vert] = 0
            for bme in self.bm.edges:
                if bme[self.layer_sel_edge] == 0: continue
                for bmv in bme.verts:
                    # bmv.select_set(True)
                    bmops.select(self.bm, bmv)
                bme[self.layer_sel_edge] = 0
            for bmf in self.bm.faces:
                if bmf[self.layer_sel_face] == 0: continue
                for bmv in bmf.verts:
                    # bmv.select_set(True)
                    bmops.select(self.bm, bmv)
                bmf[self.layer_sel_face] = 0
            if active: bmops.reselect(self.bm, active)
            bmops.flush_selection(self.bm, self.em)
            # bpy.ops.mesh.normals_make_consistent('EXEC_DEFAULT', False)
            # bpy.ops.ed.undo_push(message='Selected geometry after move')
            self.selected = None

        if self.nearest is None or not self.nearest.is_valid:
            self.nearest = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv)
        if self.nearest_bme is None or not self.nearest_bme.is_valid:
            self.nearest_bme = NearestBMEdge(self.bm, self.matrix_world, self.matrix_world_inv)

        if self.selected is None:
            self.selected = bmops.get_all_selected(self.bm)

        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        # update commit data structure with mouse position
        self.state = PP_Action.NONE
        hit = raycast_valid_sources(context, mouse_from_event(event))
        if hit:
            self.hit = hit['co_local']
        else:
            self.hit = None
            return

        self.nearest.update(
            context,
            self.hit,
            filter_fn=lambda bmv: not is_bmvert_hidden(context, bmv),
        )
        if self.nearest.bmv:
            self.hit = Vector(self.nearest.bmv.co)

        self.nearest_bme.update(
            context,
            self.hit,
            ignore_selected=False,
            filter_fn=lambda bme: not any(map(lambda bmv:is_bmvert_hidden(context, bmv), bme.verts)),
        )


        ###########################################################################################
        # determine state of polypen based on selected geo, hovered geo, and insert mode

        if insert_mode is None or insert_mode == 'VERT-ONLY':
            self.state = PP_Action.VERT
            return

        if len(self.selected[BMVert]) == 0:
            # inserting vertex
            if not self.nearest.bmv and self.nearest_bme.bme:
                self.state = PP_Action.EDGE_VERT
            else:
                self.state = PP_Action.VERT
            return

        if self.nearest_bme.bme:
            if self.nearest_bme.bme.select and not self.nearest_bme.bme.hide:
                self.state = PP_Action.EDGE_VERT
                return

        if len(self.selected[BMEdge]) == 0 or insert_mode == 'EDGE-ONLY':
            if not self.nearest.bmv and self.nearest_bme.bme:
                self.state = PP_Action.VERT_EDGE_EDGE
            else:
                self.state = PP_Action.VERT_EDGE
            # find closest selected BMVert from which to extrude
            self.bmv = min(
                self.selected[BMVert],
                key=(lambda bmv:(self.hit - bmv.co).length),
            )
            return

        if insert_mode in {'TRI/QUAD', 'QUAD-ONLY'} and self.nearest_bme.bme and not self.nearest.bmv:
            # find hovered bme but make sure it doesn't share a face with selected bme
            sel_bme = min(
                self.selected[BMEdge],
                key=(lambda bme:distance2d_point_bmedge(context, self.matrix_world, self.hit, bme)),
            )
            sel_bmf = next((bmf for bmf in sel_bme.link_faces if bmf.select), None)
            if insert_mode == 'QUAD-ONLY' or (not sel_bmf or len(sel_bmf.verts) != 3):
                hov_bme = self.nearest_bme.bme
                if not any(hov_bme in bmf.edges for bmf in sel_bme.link_faces):
                    hov_bmv0, hov_bmv1 = hov_bme.verts
                    if hov_bmv0 in sel_bme.verts or hov_bmv1 in sel_bme.verts:
                        # hovered edge shares vert with selected edge!  (issue #1443)
                        # treat this as though the artist is hovering the other vert
                        self.state = PP_Action.EDGE_TRI
                        return

                    self.state = PP_Action.EDGE_QUAD_EDGE
                    self.bme = sel_bme
                    self.bme_hovered = hov_bme

                    bmv0, bmv1 = self.bme.verts
                    bmv2, bmv3 = self.bme_hovered.verts
                    p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                    p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                    p2 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv2.co)
                    p3 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv3.co)
                    if not (p0 and p1 and p2 and p3): return

                    # ensure verts order makes a nice looking quad
                    v01 = (p1 - p0)
                    dotdir = v01.dot(p2 - p0) - v01.dot(p3 - p0)
                    if dotdir < 0:
                        p2, p3 = p3, p2
                        bmv2, bmv3 = bmv3, bmv2
                    # but swap verts if line segments are crossing
                    if intersect_line_line_2d(p0, p3, p1, p2):
                        p2, p3 = p3, p2
                        bmv2, bmv3 = bmv3, bmv2
                    self.bme_hovered_bmvs = [bmv2, bmv3]

                    return

        if insert_mode == 'QUAD-ONLY':
            sel_bme = min(
                self.selected[BMEdge],
                key=(lambda bme:distance2d_point_bmedge(context, self.matrix_world, self.hit, bme)),
            )
            bmv0, bmv1 = sel_bme.verts
            p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
            p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
            hit2, hit3 = PP_get_edge_quad_verts(context, p0, p1, self.mouse, self.matrix_world, self.parallel_stable)
            p2 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ hit2)
            p3 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ hit3)
            if not (p0 and p1 and p2 and p3): return

            # ensure verts order makes a nice looking quad
            v01 = (p1 - p0)
            dotdir = v01.dot(p2 - p0) - v01.dot(p3 - p0)
            if dotdir < 0:
                p2, p3 = p3, p2
                hit2, hit3 = hit3, hit2
            # but swap verts if line segments are crossing
            if intersect_line_line_2d(p0, p3, p1, p2):
                p2, p3 = p3, p2
                hit2, hit3 = hit3, hit2

            self.bmv2 = None
            self.bmv3 = None
            self.nearest.update(context, hit2)
            if self.nearest.bmv:
                self.bmv2 = self.nearest.bmv
                hit2 = self.nearest.bmv.co
            self.nearest.update(context, hit3)
            if self.nearest.bmv:
                self.bmv3 = self.nearest.bmv
                hit3 = self.nearest.bmv.co
            self.nearest.bmv = None

            self.state = PP_Action.EDGE_QUAD
            self.bme = sel_bme
            self.hit2, self.hit3 = hit2, hit3
            return

        if insert_mode == 'TRI/QUAD' and len(self.selected[BMFace]) == 1 and len(next(iter(self.selected[BMFace])).edges) == 3:
            self.state = PP_Action.TRI_QUAD
            self.bmf = next(iter(self.selected[BMFace]))
            self.bme = min(
                self.bmf.edges,
                key=(lambda bme:distance2d_point_bmedge(context, self.matrix_world, self.hit, bme)),
            )
            return

        if len(self.selected[BMVert]) == 2 and len(self.selected[BMEdge]) == 1:
            self.state = PP_Action.EDGE_TRI
            self.bme = next(iter(self.selected[BMEdge]), None)
            return

        if len(self.selected[BMEdge]) > 1:
            self.state = PP_Action.EDGE_TRI
            self.bme = min(
                self.selected[BMEdge],
                key=(lambda bme:distance2d_point_bmedge(context, self.matrix_world, self.hit, bme)),
            )
            return


    def draw(self, context):
        # draw previsualization
        if not self.mouse: return
        if not self.hit: return
        if not self.bm or not self.bm.is_valid: return
        if not self.nearest or not self.nearest.is_valid: return
        if not self.nearest_bme or not self.nearest_bme.is_valid: return

        theme = context.preferences.themes[0].view_3d
        props = RF_Prefs.get_prefs(context)
        highlight = props.highlight_color

        color_point =               Color4((highlight[0], highlight[1], highlight[2], 1))
        color_border_transparent =  Color4((highlight[0], highlight[1], highlight[2], 0))
        color_border_mesh =         Color4((theme.edge_select[0], theme.edge_select[1], theme.edge_select[2], 1))
        color_border_open =         Color4((highlight[0], highlight[1], highlight[2], 1.0))
        color_stipple =             Color4((theme.face_select[0], theme.face_select[1], theme.face_select[2], 0))
        color_mesh = theme.face_select
        vertex_size = theme.vertex_size

        if self.nearest.bmv:
            co = self.matrix_world @ self.nearest.bmv.co
            p = location_3d_to_region_2d(context.region, context.region_data, co)
            with Drawing.draw(context, CC_2D_POINTS) as draw:
                draw.point_size(vertex_size + 4)
                draw.border(width=2, color=color_point)
                draw.color(color_border_transparent)
                draw.vertex(p)


        match self.state:
            case PP_Action.VERT:
                pt = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.hit)
                if not pt: return
                if self.nearest.bmv: return

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_point)
                    draw.vertex(pt)

            case PP_Action.EDGE_VERT:
                if not self.nearest_bme.bme: return
                bmv0, bmv1 = self.nearest_bme.bme.verts
                pt = self.nearest_bme.co2d
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                # pt = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.bme)
                d01 = (p1 - p0).normalized() * Drawing.scale(8)

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_border_open)
                    draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_mesh)
                    draw.vertex(p0 + d01).vertex(pt - d01)
                    draw.vertex(p1 - d01).vertex(pt + d01)

            case PP_Action.VERT_EDGE_EDGE:
                if not self.nearest_bme.bme: return
                bmv0, bmv1 = self.nearest_bme.bme.verts
                pt = self.nearest_bme.co2d
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                pn = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.bmv.co)
                # pt = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.bme)
                d01 = (p1 - p0).normalized() * Drawing.scale(8)

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_border_open)
                    draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)

                    draw.vertex(pn)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_mesh)
                    draw.vertex(p0 + d01).vertex(pt - d01)
                    draw.vertex(p1 - d01).vertex(pt + d01)

                    draw.vertex(pn).vertex(pt)

            case PP_Action.VERT_EDGE:
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.bmv.co)
                pt = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.hit)
                if not (p0 and pt): return
                diff = pt - p0
                d = diff.normalized() * Drawing.scale(8)

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)

                    if not self.nearest.bmv:
                        draw.color(color_border_open)
                        draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)

                if diff.length > Drawing.scale(8):
                    with Drawing.draw(context, CC_2D_LINES) as draw:
                        draw.line_width(2)
                        draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                        draw.color(color_border_open)
                        draw.vertex(p0 + d).vertex(pt - d)

            case PP_Action.EDGE_TRI:
                bmv0, bmv1 = self.bme.verts
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                pt = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.hit)
                if not (p0 and p1 and pt): return
                d0t = (pt - p0).normalized() * Drawing.scale(8)
                d1t = (pt - p1).normalized() * Drawing.scale(8)
                d01 = (p1 - p0).normalized() * Drawing.scale(8)

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)

                    if not self.nearest.bmv:
                        draw.color(color_border_open)
                        draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    draw.vertex(p0 + d0t).vertex(pt - d0t)
                    draw.vertex(p1 + d1t).vertex(pt - d1t)

                    draw.color(color_border_mesh)
                    draw.vertex(p0 + d01).vertex(p1 - d01)

                with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                    draw.color(color_mesh)
                    draw.vertex(pt).vertex(p0).vertex(p1)

            case PP_Action.EDGE_QUAD_EDGE:
                bmv0, bmv1 = self.bme.verts
                bmv2, bmv3 = self.bme_hovered_bmvs
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                p2 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv2.co)
                p3 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv3.co)
                if not (p0 and p1 and p2 and p3): return

                d01 = (p1 - p0).normalized() * Drawing.scale(8)
                d12 = (p2 - p1).normalized() * Drawing.scale(8)
                d23 = (p3 - p2).normalized() * Drawing.scale(8)
                d30 = (p0 - p3).normalized() * Drawing.scale(8)

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)
                    draw.vertex(p2)
                    draw.vertex(p3)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    draw.vertex(p0 - d30).vertex(p3 + d30)
                    draw.vertex(p1 + d12).vertex(p2 - d12)

                    draw.color(color_border_mesh)
                    draw.vertex(p0 + d01).vertex(p1 - d01)
                    draw.vertex(p2 + d23).vertex(p3 - d23)

                with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                    draw.color(color_mesh)
                    draw.vertex(p0).vertex(p1).vertex(p2)
                    draw.vertex(p0).vertex(p2).vertex(p3)

            case PP_Action.EDGE_QUAD:
                bmv0, bmv1 = self.bme.verts
                hit2, hit3 = self.hit2, self.hit3
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                p2 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ hit2)
                p3 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ hit3)
                if not (p0 and p1 and p2 and p3): return

                v01, v12, v23, v30 = (p1 - p0), (p2 - p1), (p3 - p2), (p0 - p3)
                d01 = v01.normalized() * Drawing.scale(8)
                d12 = v12.normalized() * Drawing.scale(8)
                d23 = v23.normalized() * Drawing.scale(8)
                d30 = v30.normalized() * Drawing.scale(8)

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_border_open)
                    if not self.bmv2: draw.vertex(p2)
                    if not self.bmv3: draw.vertex(p3)
                    draw.color(color_stipple)
                    draw.border(width=2, color=color_point)
                    draw.vertex(p0)
                    draw.vertex(p1)
                    if self.bmv2: draw.vertex(p2)
                    if self.bmv3: draw.vertex(p3)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    if v30.length > Drawing.scale(8): draw.vertex(p0 - d30).vertex(p3 + d30)
                    if v12.length > Drawing.scale(8): draw.vertex(p1 + d12).vertex(p2 - d12)
                    draw.vertex(p2 + d23).vertex(p3 - d23)

                    draw.color(color_border_mesh)
                    draw.vertex(p0 + d01).vertex(p1 - d01)

                with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                    draw.color(color_mesh)
                    draw.vertex(p0).vertex(p1).vertex(p2)
                    draw.vertex(p0).vertex(p2).vertex(p3)


            case PP_Action.TRI_QUAD:
                bmev0, bmev1 = self.bme.verts
                bmv0, bmv1, bmv2 = self.bmf.verts
                if (bmev0 == bmv0 and bmev1 == bmv1) or (bmev0 == bmv1 and bmev1 == bmv0):
                    pass
                elif (bmev0 == bmv1 and bmev1 == bmv2) or (bmev0 == bmv2 and bmev1 == bmv1):
                    bmv0, bmv1, bmv2 = bmv1, bmv2, bmv0
                else:
                    bmv0, bmv1, bmv2 = bmv2, bmv0, bmv1
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                p2 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv2.co)
                pt = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.hit)
                if not (p0 and p1 and p2 and pt): return
                d0t = (pt - p0).normalized() * Drawing.scale(8)
                d1t = (pt - p1).normalized() * Drawing.scale(8)
                d01 = (p1 - p0).normalized() * Drawing.scale(8)
                d02 = (p2 - p0).normalized() * Drawing.scale(8)
                d12 = (p2 - p1).normalized() * Drawing.scale(8)

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)

                    if not self.nearest.bmv:
                        draw.color(color_border_open)
                        draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)
                    draw.vertex(p2)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    draw.vertex(p0 + d0t).vertex(pt - d0t)
                    draw.vertex(p1 + d1t).vertex(pt - d1t)

                    draw.color(color_border_mesh)
                    # draw.vertex(p0 + d01).vertex(p1 - d01)
                    draw.vertex(p0 + d02).vertex(p2 - d02)
                    draw.vertex(p1 + d12).vertex(p2 - d12)

                with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                    draw.color(color_mesh)
                    draw.vertex(p0).vertex(pt).vertex(p1)
                    draw.vertex(p0).vertex(p1).vertex(p2)

            case _:
                pass

    def correct_mirror_side(self, context, co, bmvs_based):
        # make sure co is on same side of mirror as bmvs_based
        mirror = set()
        if has_mirror_x(context): mirror.add('x')
        if has_mirror_y(context): mirror.add('y')
        if has_mirror_z(context): mirror.add('z')
        if not mirror: return co
        mt = mirror_threshold(context)
        signs = [
            Vector((sign_threshold(bmv.co.x, mt), sign_threshold(bmv.co.y, mt), sign_threshold(bmv.co.z, mt)))
            for bmv in bmvs_based
        ]
        sx,sy,sz = (
            next((s.x for s in signs if s.x != 0), 0),
            next((s.y for s in signs if s.y != 0), 0),
            next((s.z for s in signs if s.z != 0), 0),
        )
        # if using scale * mt * 2, the vert will be created far enough away from mirror to move freely
        # if using 0, the vert is created at mirror, and it will not be allowed to move away from mirror if clipping is enabled
        if 'x' in mirror and sign_threshold(co.x, mt) != sx: co.x = 0 # sx * mt * 2
        if 'y' in mirror and sign_threshold(co.y, mt) != sy: co.y = 0 # sy * mt * 2
        if 'z' in mirror and sign_threshold(co.z, mt) != sz: co.z = 0 # sz * mt * 2
        return co

    def commit(self, context, event):
        # apply the change

        if self.state == PP_Action.NONE: return
        # TODO: UNDO NOT PUSHING ON MULTIPLE TIMES!?!?!
        # bpy.ops.ed.undo_push(message=f'PolyPen commit {time.time()}')

        # make sure artist can see the vert
        context.tool_settings.mesh_select_mode[0] = True

        select_now = []     # to be selected before move
        select_later = []   # to be selected after move

        match self.state:
            case PP_Action.VERT:
                # create new detached vertex
                if self.nearest.bmv:
                    bmv = self.nearest.bmv
                else:
                    bmv = self.bm.verts.new(self.hit)
                select_now = [bmv]

            case PP_Action.EDGE_VERT:
                # split hovered edge
                bme = self.nearest_bme.bme
                bmev0, bmev1 = bme.verts
                bme_new, bmv_new = edge_split(bme, bmev0, 0.5)
                bmv_new.co = self.hit
                select_now = [bmv_new]
                select_later = []

            case PP_Action.VERT_EDGE:
                # create new edge between selected vert and current mouse position
                bmv0 = self.bmv
                if self.nearest.bmv:
                    bmv1 = self.nearest.bmv
                else:
                    co = self.correct_mirror_side(context, self.hit, [bmv0])
                    bmv1 = self.bm.verts.new(co)
                bmf_split = next((bmf for bmf in bmv0.link_faces if bmv1 in bmf.verts), None)
                bme = None
                if bmf_split:
                    bme = next(iter(bmesh.ops.connect_verts(self.bm, verts=[bmv0, bmv1])), None)
                if not bme:
                    bme = next(iter(bmops.shared_link_edges([bmv0, bmv1])), None)
                if not bme:
                    bme = self.bm.edges.new((bmv0, bmv1))
                select_now = [bmv1]
                select_later = [bme] if self.insert_mode != 'EDGE-ONLY' else []

            case PP_Action.VERT_EDGE_EDGE:
                # split hovered edge and create new edge from selected vert
                bme = self.nearest_bme.bme
                bmev0, bmev1 = bme.verts
                bme_new, bmv_new = edge_split(bme, bmev0, 0.5)
                bmv_new.co = self.hit
                bmf_split = next((bmf for bmf in self.bmv.link_faces if bmv_new in bmf.verts), None)
                if bmf_split:
                    bmesh.ops.connect_verts(self.bm, verts=[self.bmv, bmv_new])
                else:
                    bme_new = self.bm.edges.new((self.bmv, bmv_new))
                select_now = [bmv_new]
                select_later = []

            case PP_Action.EDGE_TRI:
                # create triangle from selected edge and current mouse position
                bmv0, bmv1 = self.bme.verts
                if self.nearest.bmv:
                    bmv = self.nearest.bmv
                else:
                    co = self.correct_mirror_side(context, self.hit, self.bme.verts)
                    bmv = self.bm.verts.new(co)
                bmf = next(iter(bmops.shared_link_faces([bmv0, bmv1, bmv])), None)
                select_now = [bmv]
                select_later = []
                if bmf:
                    # split face
                    if not bmops.shared_link_edges([bmv0, bmv]):
                        bmf0, _ = bmesh.utils.face_split(bmf, bmv0, bmv)
                        select_later += [bmf0]
                        # don't know which face is touching bmv1 (bmvf or bmf0), so just grab again
                        bmf = next(iter(bmops.shared_link_faces([bmv1, bmv])), None)
                    if not bmops.shared_link_edges([bmv1, bmv]):
                        bmf1, _ = bmesh.utils.face_split(bmf, bmv1, bmv)
                        select_later += [bmf1]
                else:
                    bmf = self.bm.faces.new((bmv0,bmv1,bmv))
                    bmf.normal_update()
                    if xform_direction(self.matrix_world_inv, view_forward_direction(context)).dot(bmf.normal) > 0:
                        bmf.normal_flip()
                select_later += [bmf]

            case PP_Action.EDGE_QUAD_EDGE:
                # create quad between selected and hovered edges
                bmv0, bmv1 = self.bme.verts
                bmv2, bmv3 = self.bme_hovered_bmvs
                bmf = self.bm.faces.new((bmv0, bmv1, bmv2, bmv3))
                bmf.normal_update()
                if xform_direction(self.matrix_world_inv, view_forward_direction(context)).dot(bmf.normal) > 0:
                    bmf.normal_flip()
                select_now = [bmv2, bmv3]
                select_later = [bmf]

            case PP_Action.EDGE_QUAD:
                # create quad from selected edge and current mouse position
                bmv0, bmv1 = self.bme.verts
                if self.bmv2:
                    bmv2 = self.bmv2
                else:
                    co2 = self.correct_mirror_side(context, self.hit2, self.bme.verts)
                    bmv2 = self.bm.verts.new(co2)
                if self.bmv3:
                    bmv3 = self.bmv3
                else:
                    co3 = self.correct_mirror_side(context, self.hit3, self.bme.verts)
                    bmv3 = self.bm.verts.new(co3)
                bmf = self.bm.faces.new((bmv0, bmv1, bmv2, bmv3))
                bmf.normal_update()
                if xform_direction(self.matrix_world_inv, view_forward_direction(context)).dot(bmf.normal) > 0:
                    bmf.normal_flip()
                select_now = [bmv2, bmv3]
                select_later = [bmf]

            case PP_Action.TRI_QUAD:
                # convert selected triangle into quad
                bmev0, bmev1 = self.bme.verts
                bmv0, bmv1, bmv2 = self.bmf.verts
                if (bmev0 == bmv0 and bmev1 == bmv1) or (bmev0 == bmv1 and bmev1 == bmv0):
                    pass
                elif (bmev0 == bmv1 and bmev1 == bmv2) or (bmev0 == bmv2 and bmev1 == bmv1):
                    bmv0, bmv1, bmv2 = bmv1, bmv2, bmv0
                else:
                    bmv0, bmv1, bmv2 = bmv2, bmv0, bmv1
                if self.nearest.bmv:
                    bmv = self.nearest.bmv
                else:
                    co = self.correct_mirror_side(context, self.hit, self.bmf.verts)
                    bmv = self.bm.verts.new(co)
                bme_new, bmv_new = edge_split(self.bme, bmev0, 0.5)
                bmesh.ops.weld_verts(self.bm, targetmap={bmv_new: bmv})
                select_now = [bmv]
                select_later = [self.bmf]

            case _:
                assert False, f'Unhandled PolyPen state {PP_Action[self.state]}'

        bmops.deselect_all(self.bm)
        for bmelem in select_now:
            bmops.select(self.bm, bmelem)
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

        bpy.ops.retopoflow.translate_screenspace('INVOKE_DEFAULT', False, move_hovered=False)

        # NOTE: the select-later property is _not_ transferred to the vert into which the moved vert is auto-merged...
        #       this is handled if a BMEdge or BMFace is to be selected later, but it is not handled if only a BMVert
        #       is created and then merged into existing geometry


def PP_get_edge_quad_verts(context, p0, p1, mouse, matrix_world, parallel_stable, *, min_dist_ratio=1.1):
    '''
    this function is used in quad-only mode to find positions of quad verts based on selected edge and mouse position
    a Desmos construction of how this works: https://www.desmos.com/geometry/5w40xowuig
    '''
    if not p0 or not p1 or not mouse: return None, None
    v01 = p1 - p0
    dist01 = v01.length
    d01 = v01 / dist01
    mid01 = p0 + v01 / 2
    mid23 = mouse
    between = mid23 - mid01
    if between.length < 0.0001: return None, None

    mid0123 = mid01 + between * clamp(parallel_stable, 0.01, 0.99)  # [0,1] larger => more parallel to original
    perp = Vector((-between.y, between.x))
    if perp.dot(v01) < 0: perp.negate()
    intersection = intersection2d_line_line(p0, p1, mid0123, mid0123 + perp)
    if not intersection: return None, None

    dist = d01.dot(intersection - mid01)
    if abs(dist) < dist01 * min_dist_ratio:
        dist = dist01 * min_dist_ratio * (1 if dist > 0 else -1)
        intersection = mid01 + d01 * dist

    toward = (mid23 - intersection).normalized()
    if toward.dot(perp) < 0: dist01 = -dist01

    between_len = between.length * v01.normalized().dot(perp)

    for tries in range(32):
        p2, p3 = mid23 + toward * (dist01 / 2), mid23 - toward * (dist01 / 2)
        hit2 = raycast_point_valid_sources(context, p2)
        hit3 = raycast_point_valid_sources(context, p3)
        if hit2 and hit3:
            Mi = matrix_world.inverted()
            return Mi @ hit2, Mi @ hit3
        dist01 /= 2
    return None, None

