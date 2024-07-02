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
import os
from random import random
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
from ..common.icons import get_path_to_blender_icon
from ..common.operator import invoke_operator, execute_operator, RFOperator
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, size2D_to_size, vec_forward, mouse_from_event
from ..common.maths import view_forward_direction
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.maths import Color, Frame
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import clamp, Direction, Vec
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.timerhandler import TimerHandler

from ..rfoperators.transform import RFOperator_Translate

from .relax_logic import Relax_Logic



class RFOperator_Relax(RFOperator):
    bl_idname = "retopoflow.relax"
    bl_label = 'Relax'
    bl_description = 'Relax the vertex positions to smooth out topology'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS'}, None),
        # (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY'}, None),
    ]
    # rf_status = ['LMB: Insert', 'MMB: (nothing)', 'RMB: (nothing)']

    def init(self, context, event):
        # print(f'STARTING POLYPEN')
        self.logic = Relax_Logic(context, event)
        self.tickle(context)
        self.timer = TimerHandler(120, context=context, enabled=True)

    def reset(self):
        # self.logic.reset()
        pass

    def update(self, context, event):
        # print('update')
        self.logic.update(context, event)
        # self.logic.update(context, event, self.insert_mode)

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.timer.stop()
            return {'FINISHED'}

        # if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
        #     # self.logic.commit(context, event)
        #     return {'RUNNING_MODAL'}

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            context.area.tag_redraw()
            return {'PASS_THROUGH'}

        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!

    def draw_postpixel(self, context):
        self.logic.draw(context)
        pass


class RFBrush_Falloff:
    def __init__(self):
        self.mouse = None
        self.hit = False
        self.hit_p = None
        self.hit_n = None
        self.hit_depth = None
        self.hit_x = None
        self.hit_y = None
        self.hit_z = None
        self.hit_rmat = None

        self.falloff = 0.5
        self.radius = 50
        self.strength = 0.5
        self.fill_color = Color.from_ints(  0, 135, 255, 255)
        self.outer_color = Color((1,1,1,1))
        self.inner_color = Color((1,1,1,0.5))
        self.below_alpha = Color((1,1,1,0.25))
        self.brush_max_alpha = 0.7
        self.brush_min_alpha = 0.1

    def update(self, context, event):
        if event.type != 'MOUSEMOVE': return
        self.mouse = mouse_from_event(event)
        self._update(context)

    def _update(self, context):
        self.hit = False
        context.area.tag_redraw()
        if not self.mouse: return
        # print(f'RFBrush_Falloff.update {(event.mouse_region_x, event.mouse_region_y)}') #{context.region=} {context.region_data=}')
        hit = raycast_valid_sources(context, self.mouse)
        # print(f'  {hit=}')
        if not hit: return
        scale = size2D_to_size(context, 1.0, hit['distance'])
        # print(f'  {scale=}')
        if scale is None: return

        n = hit['no_local']
        rmat = Matrix.Rotation(Direction.Z.angle(n), 4, Direction.Z.cross(n))

        self.hit = True
        self.hit_scale = scale
        self.hit_p = hit['co_local']
        self.hit_n = hit['no_local']
        self.hit_depth = hit['distance']
        self.hit_x = Vec(rmat @ Direction.X)
        self.hit_y = Vec(rmat @ Direction.Y)
        self.hit_z = Vec(rmat @ Direction.Z)
        self.hit_rmat = rmat

    def draw_postview(self, context):
        # print(f'RFBrush_Falloff.draw_postview {random()}')
        # print(f'RFBrush_Falloff.draw_postview {self.hit=}')
        self._update(context)
        if not self.hit: return

        fillscale = Color((1, 1, 1, self.strength * (self.brush_max_alpha - self.brush_min_alpha) + self.brush_min_alpha))

        ff = math.pow(0.5, 1.0 / max(self.falloff, 0.0001))
        p, n = self.hit_p, self.hit_n
        ro = self.radius * self.hit_scale
        ri = ro * ff
        rm = (ro + ri) / 2.0
        co, ci, cc = self.outer_color, self.inner_color, self.fill_color * fillscale

        fwd = Direction(vec_forward(context)) * (self.hit_depth * 0.0005)

        # draw below
        gpustate.depth_mask(False)
        gpustate.depth_test('GREATER')
        Drawing.draw3D_circle(context, p-fwd*1.0, rm, cc * self.below_alpha, n=n, width=ro - ri)
        Drawing.draw3D_circle(context, p-fwd*2.0, ro, co * self.below_alpha, n=n, width=2*self.hit_scale)
        Drawing.draw3D_circle(context, p-fwd*2.0, ri, ci * self.below_alpha, n=n, width=2*self.hit_scale)

        # draw above
        gpustate.depth_test('LESS_EQUAL')
        Drawing.draw3D_circle(context, p-fwd*1.0, rm, cc, n=n, width=ro - ri)
        Drawing.draw3D_circle(context, p-fwd*2.0, ro, co, n=n, width=2*self.hit_scale)
        Drawing.draw3D_circle(context, p-fwd*2.0, ri, ci, n=n, width=2*self.hit_scale)

        # reset
        gpustate.depth_test('LESS_EQUAL')
        gpustate.depth_mask(True)


class RFTool_Relax(RFTool_Base):
    bl_idname = "retopoflow.relax"
    bl_label = "Relax"
    bl_description = "Relax the vertex positions to smooth out topology"
    bl_icon = get_path_to_blender_icon('relax')
    bl_widget = None
    bl_operator = 'retopoflow.relax'
    rf_brush = RFBrush_Falloff()

    bl_keymap = (
        *[ keymap for keymap in RFOperator_Relax.rf_keymaps ],
    )

    def draw_settings(context, layout, tool):
        # layout.label(text="PolyPen")
        props = tool.operator_properties(RFOperator_Relax.bl_idname)
        # layout.prop(props, 'insert_mode')

    @classmethod
    def activate(cls, context):
        # TODO: some of the following might not be needed since we are creating our
        #       own transform operators
        cls.reseter = Reseter()
        cls.reseter['context.tool_settings.use_mesh_automerge'] = True
        cls.reseter['context.tool_settings.double_threshold'] = 0.01
        # cls.reseter['context.tool_settings.snap_elements_base'] = {'VERTEX'}
        cls.reseter['context.tool_settings.snap_elements_individual'] = {'FACE_PROJECT', 'FACE_NEAREST'}
        cls.reseter['context.tool_settings.mesh_select_mode'] = [True, True, True]

    @classmethod
    def deactivate(cls, context):
        cls.reseter.reset()
