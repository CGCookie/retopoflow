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
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event
from ..common.maths import view_forward_direction
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


class RFOperator_Translate(RFOperator):
    bl_idname = "retopoflow.translate"
    bl_label = 'Translate'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'G',         'value': 'PRESS'}, None),
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK_DRAG'}, None),
    ]
    rf_status = ['LMB: Commit', 'MMB: (nothing)', 'RMB: Cancel']

    move_hovered: bpy.props.BoolProperty(
        name='Select and Move Hovered',
        description='If False, currently selected geometry is moved.  If True, hovered geometry is selected then moved.',
        default=True,
    )


    def init(self, context, event):
        # print(f'STARTING TRANSLATE')
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.bm, self.em = get_bmesh_emesh(context)
        self.nearest = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv)

        if self.move_hovered:
            hit = raycast_valid_sources(context, mouse_from_event(event))
            if hit:
                co = hit['co_local']
                self.nearest.update(context, co)
                # print(f'  SELECT HOVERED {self.nearest.bmv}')
                # select hovered geometry
                if self.nearest.bmv:
                    bmops.deselect_all(self.bm)
                    bmops.select(self.bm, self.nearest.bmv)
                    #self.bm.select_history.validate()
                    bmops.flush_selection(self.bm, self.em)

        self.bmvs = list(bmops.get_all_selected_bmverts(self.bm))
        self.bmvs_co_orig = [Vector(bmv.co) for bmv in self.bmvs]
        self.bmvs_co2d_orig = [location_3d_to_region_2d(context.region, context.region_data, (self.matrix_world @ Vector((*bmv.co, 1.0))).xyz) for bmv in self.bmvs]

        self.bmfs = [(bmf, Vector(bmf.normal)) for bmf in { bmf for bmv in self.bmvs for bmf in bmv.link_faces }]
        self.mouse = Vector((event.mouse_x, event.mouse_y))
        self.mouse_orig = Vector((event.mouse_x, event.mouse_y))
        self.mouse_prev = Vector((event.mouse_x, event.mouse_y))
        self.mouse_center = Vector((context.window.width // 2, context.window.height // 2))
        # self.RFCore.cursor_warp(context, self.mouse_center)  # NOTE: initial warping might not happen right away
        self.delay_delta_update = True
        self.delta = Vector((0, 0))

        self.highlight = set()

        # Cursors.set('NONE')  # PAINT_CROSS

    def update(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.cancel_reset(context, event)
            # self.RFCore.cursor_warp(context, self.mouse_orig)
            # print(f'CANCEL TRANSLATE')
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE':
            # HANDLE MERGE!!!
            self.automerge(context, event)
            # self.RFCore.cursor_warp(context, self.mouse_orig)
            bpy.ops.ed.undo_push(message='Transform')
            # print(f'COMMIT TRANSLATE')
            return {'FINISHED'}

        if self.delay_delta_update:
            self.delay_delta_update = False
        elif event.type == 'MOUSEMOVE':
            self.mouse_prev = self.mouse
            self.mouse = Vector((event.mouse_x, event.mouse_y))
            self.translate(context, event)

        return {'RUNNING_MODAL'}

    def draw_postpixel(self, context):
        if not self.highlight: return
        with Drawing.draw(context, CC_2D_POINTS) as draw:
            draw.point_size(8)
            draw.border(width=2, color=Color4((40/255, 255/255, 40/255, 0.5)))
            draw.color(Color4((40/255, 255/255, 255/255, 0.0)))
            for bmv in self.highlight:
                co = self.matrix_world @ bmv.co
                p = location_3d_to_region_2d(context.region, context.region_data, co)
                draw.vertex(p)

    def automerge(self, context, event):
        merging = {}
        for bmv in self.bmvs:
            self.nearest.update(context, bmv.co)
            if not self.nearest.bmv: continue
            bmv_into = self.nearest.bmv
            merging[bmv_into] = bmv
        bmesh.ops.weld_verts(self.bm, targetmap=merging)

        self.update_normals(context, event)

        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def cancel_reset(self, context, event):
        for bmv, co_orig in zip(self.bmvs, self.bmvs_co_orig):
            bmv.co = co_orig
        for bmf, norm_orig in self.bmfs:
            bmf.normal_update()
            if norm_orig.dot(bmf.normal) < 0: bmf.normal_flip()
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def translate(self, context, event):
        # self.delta += self.mouse - self.mouse_center
        # self.RFCore.cursor_warp(context, self.mouse_center)
        # self.delta = self.mouse - self.mouse_orig
        self.delta += self.mouse - self.mouse_prev

        # TODO: not respecting the mirror modifier clip setting!

        factor = 1.0
        while factor > 0.0:
            if all(raycast_point_valid_sources(context, co2d_orig + self.delta * factor) for co2d_orig in self.bmvs_co2d_orig):
                break
            factor -= 0.01
        if factor <= 0.0: return

        self.highlight = set()
        for bmv, co2d_orig in zip(self.bmvs, self.bmvs_co2d_orig):
            co = raycast_point_valid_sources(context, co2d_orig + self.delta * factor, world=False)
            self.nearest.update(context, co)
            if self.nearest.bmv:
                co = self.nearest.bmv.co
                self.highlight.add(self.nearest.bmv)
            bmv.co = co

        self.update_normals(context, event)

        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def update_normals(self, context, event):
        forward = (self.matrix_world_inv @ Vector((*view_forward_direction(context), 0.0))).xyz
        for bmf, _ in self.bmfs:
            if not bmf.is_valid: continue
            bmf.normal_update()
            if forward.dot(bmf.normal) > 0:
                bmf.normal_flip()

