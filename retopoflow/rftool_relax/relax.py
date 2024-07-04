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
from itertools import chain
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
from ..common.operator import RFOperator, wrap_property, chain_rf_keymaps, execute_operator
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, size2D_to_size, vec_forward, mouse_from_event
from ..common.maths import view_forward_direction, lerp
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.maths import Color, Frame
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.timerhandler import TimerHandler

from ..rfoperators.transform import RFOperator_Translate

from .relax_logic import Relax_Logic


class RF_Relax_Brush:
    # brush settings
    radius   = 200
    falloff  = 1.5
    strength = 0.75

    # brush visualization settings
    fill_color      = Color.from_ints(0, 135, 255, 255)
    outer_color     = Color((1,1,1,1))
    inner_color     = Color((1,1,1,0.5))
    below_alpha     = Color((1,1,1,0.25))
    brush_min_alpha = 0.10
    brush_max_alpha = 0.70
    depth_fill      = 0.998
    depth_border    = 0.996

    # hack to know which areas the mouse is in
    mouse_areas = set()

    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RF_Relax_Brush, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self.mouse = None
        self.hit = False
        self.hit_p = None
        self.hit_n = None
        self.hit_scale = None
        self.hit_depth = None
        self.hit_x = None
        self.hit_y = None
        self.hit_z = None
        self.hit_rmat = None

    def get_scaled_radius(self):
        return self.hit_scale * self.radius
    def get_strength_dist(self, dist:float):
        return max(0.0, min(1.0, (1.0 - math.pow(dist / self.get_scaled_radius(), self.falloff)))) * self.strength
    def get_strength_Point(self, point:Point):
        if not self.hit_p: return 0.0
        return self.get_strength_dist((point - self.hit_p).length)

    def update(self, context, event):
        if event.type != 'MOUSEMOVE': return

        mouse = mouse_from_event(event)

        if RFOperator_Relax.is_active() or RFOperator_Relax_Brush.is_active():
            # artist is actively relaxing or adjusting brush properties, so always consider us inside if we're in the same area
            active_op = RFOperator.active_operator()
            mouse_inside = (context.area == active_op.working_area) and (context.window == active_op.working_window)
        else:
            mouse_inside = (0 <= mouse[0] < context.area.width) and (0 <= mouse[1] < context.area.height)

        if not mouse_inside:
            if context.area in self.mouse_areas:
                # we were inside this area, but not anymore.  tag for redraw to remove brush
                self.mouse_areas.remove(context.area)
                context.area.tag_redraw()
            return

        if context.area not in self.mouse_areas:
            # we were outside this area before, but now we're in
            self.mouse_areas.add(context.area)

        self.mouse = mouse
        context.area.tag_redraw()

    def _update(self, context):
        if context.area not in self.mouse_areas: return
        self.hit = False
        if not self.mouse: return
        # print(f'RF_Relax_Brush.update {(event.mouse_region_x, event.mouse_region_y)}') #{context.region=} {context.region_data=}')
        hit = raycast_valid_sources(context, self.mouse)
        # print(f'  {hit=}')
        if not hit: return
        scale = size2D_to_size(context, hit['distance'])
        # print(f'  {scale=}')
        if scale is None: return

        n = hit['no_local']
        rmat = Matrix.Rotation(Direction.Z.angle(n), 4, Direction.Z.cross(n))

        self.hit = True
        self.hit_scale = scale
        self.hit_p = hit['co_world']
        self.hit_n = hit['no_world']
        self.hit_depth = hit['distance']
        self.hit_x = Vec(rmat @ Direction.X)
        self.hit_y = Vec(rmat @ Direction.Y)
        self.hit_z = Vec(rmat @ Direction.Z)
        self.hit_rmat = rmat

    def draw_postpixel(self, context):
        if context.area not in self.mouse_areas: return
        if not RFOperator_Relax_Brush.is_active(): return
        fillscale = Color((1, 1, 1, lerp(self.strength, self.brush_min_alpha, self.brush_max_alpha)))
        r = self.radius
        co, ci, cf = self.outer_color, self.inner_color, self.fill_color * fillscale
        ff = math.pow(0.5, 1.0 / max(self.falloff, 0.0001))
        fs = (1-ff) * self.radius
        gpustate.blend('ALPHA')
        Drawing.draw2D_circle(context, self._change_center, r-fs/2, cf, width=fs)
        Drawing.draw2D_circle(context, self._change_center, r,      co, width=1)
        Drawing.draw2D_circle(context, self._change_center, r*ff,   ci, width=1)

    def draw_postview(self, context):
        if context.area not in self.mouse_areas: return
        if RFOperator_Relax_Brush.is_active(): return
        # print(f'RF_Relax_Brush.draw_postview {random()}')
        # print(f'RF_Relax_Brush.draw_postview {self.hit=}')
        self._update(context)
        if not self.hit: return

        fillscale = Color((1, 1, 1, lerp(self.strength, self.brush_min_alpha, self.brush_max_alpha)))

        ff = math.pow(0.5, 1.0 / max(self.falloff, 0.0001))
        p, n = self.hit_p, self.hit_n
        ro = self.radius * self.hit_scale
        ri = ro * ff
        rm = (ro + ri) / 2.0
        co, ci, cf = self.outer_color, self.inner_color, self.fill_color * fillscale

        gpustate.blend('ALPHA')
        gpustate.depth_mask(False)

        # draw below
        gpustate.depth_test('GREATER')
        Drawing.draw3D_circle(context, p, rm, cf * self.below_alpha, n=n, width=ro - ri, depth_far=self.depth_fill)
        Drawing.draw3D_circle(context, p, ro, co * self.below_alpha, n=n, width=2*self.hit_scale, depth_far=self.depth_border)
        Drawing.draw3D_circle(context, p, ri, ci * self.below_alpha, n=n, width=2*self.hit_scale, depth_far=self.depth_border)

        # draw above
        gpustate.depth_test('LESS_EQUAL')
        Drawing.draw3D_circle(context, p, rm, cf, n=n, width=ro - ri, depth_far=self.depth_fill)
        Drawing.draw3D_circle(context, p, ro, co, n=n, width=2*self.hit_scale, depth_far=self.depth_border)
        Drawing.draw3D_circle(context, p, ri, ci, n=n, width=2*self.hit_scale, depth_far=self.depth_border)

        # reset
        gpustate.depth_test('LESS_EQUAL')
        gpustate.depth_mask(True)

class RFOperator_Relax_Brush(RFOperator):
    bl_idname = 'retopoflow.relax_brush'
    bl_label = 'Relax Brush'
    bl_description = 'Adjust properties of relax brush'
    bl_space_type = 'VIEW_3D'
    bl_space_type = 'TOOLS'
    bl_options = set()

    rf_status = ['LMB: Commit', 'RMB: Cancel']

    adjust: bpy.props.EnumProperty(
        name='Relax Brush Property',
        description='Property of Relax Brush to adjust',
        items=[
            ('RADIUS',   'Radius',   'Adjust Relax Brush Radius',   1),
            ('STRENGTH', 'Strength', 'Adjust Relax Brush Strength', 2),
            ('FALLOFF',  'Falloff',  'Adjust Relax Brush Falloff',  3),
        ],
        default='RADIUS',
    )

    def init(self, context, event):
        match self.adjust:
            case 'RADIUS':
                self._dist_to_var_fn = self.dist_to_radius
                self._var_to_dist_fn = self.radius_to_dist
            case 'STRENGTH':
                self._dist_to_var_fn = self.dist_to_strength
                self._var_to_dist_fn = self.strength_to_dist
            case 'FALLOFF':
                self._dist_to_var_fn = self.dist_to_falloff
                self._var_to_dist_fn = self.falloff_to_dist
            case _:
                assert False, f'Unhandled {self.adjust=}'

        self.brush = RF_Relax_Brush()
        dist = self._var_to_dist_fn()
        self.prev_radius = self.brush.radius
        self._change_pre = dist
        mouse = Point2D((event.mouse_region_x, event.mouse_region_y))
        self.brush._change_center = mouse - Vec2D((dist, 0))
        context.area.tag_redraw()

    def dist_to_radius(self, d):
        type(self.brush).radius = max(1, int(d))
    def radius_to_dist(self):
        return self.brush.radius
    def dist_to_strength(self, d):
        type(self.brush).strength = 1.0 - max(0.01, min(1.0, d / self.brush.radius))
    def strength_to_dist(self):
        return self.brush.radius * (1.0 - self.brush.strength)
    def dist_to_falloff(self, d):
        type(self.brush).falloff = math.log(0.5) / math.log(max(0.01, min(0.99, d / self.brush.radius)))
    def falloff_to_dist(self):
        return self.brush.radius * math.pow(0.5, 1.0 / max(self.brush.falloff, 0.0001))

    def update(self, context, event):
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            return {'FINISHED'}
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            self._dist_to_var_fn(self._change_pre)
            # type(self.brush).radius = self.prev_radius
            return {'CANCELLED'}
        if event.type == 'ESC' and event.value == 'PRESS':
            self._dist_to_var_fn(self._change_pre)
            # type(self.brush).radius = self.prev_radius
            return {'CANCELLED'}

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            mouse = Point2D((event.mouse_region_x, event.mouse_region_y))
            dist = (self.brush._change_center - mouse).length
            self._dist_to_var_fn(dist)
            # type(self.brush).radius = int(dist)
            context.area.tag_redraw()
            return {'PASS_THROUGH'}

        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!


@execute_operator('relax_brush_radius', 'Adjust Relax Brush Radius')
def relax_brush_radius(context):
    bpy.ops.retopoflow.relax_brush('INVOKE_DEFAULT', adjust='RADIUS')
@execute_operator('relax_brush_strength', 'Adjust Relax Brush Strength')
def relax_brush_strength(context):
    bpy.ops.retopoflow.relax_brush('INVOKE_DEFAULT', adjust='STRENGTH')
@execute_operator('relax_brush_falloff', 'Adjust Relax Brush Falloff')
def relax_brush_falloff(context):
    bpy.ops.retopoflow.relax_brush('INVOKE_DEFAULT', adjust='FALLOFF')





class RFOperator_Relax(RFOperator):
    bl_idname = "retopoflow.relax"
    bl_label = 'Relax'
    bl_description = 'Relax the vertex positions to smooth out topology'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS'}, None),
        ('retopoflow.relax_brush_radius',   {'type': 'F', 'value': 'PRESS', 'ctrl': 0, 'shift': 0}, None),
        ('retopoflow.relax_brush_falloff',  {'type': 'F', 'value': 'PRESS', 'ctrl': 1, 'shift': 0}, None),
        ('retopoflow.relax_brush_strength', {'type': 'F', 'value': 'PRESS', 'ctrl': 0, 'shift': 1}, None),
    ]
    rf_status = ['LMB: Relax']

    brush_radius: wrap_property(
        RF_Relax_Brush, 'radius', 'int',
        name='Radius',
        description='Radius of Brush',
        min=1,
        max=1000,
    )
    brush_falloff: wrap_property(
        RF_Relax_Brush, 'falloff', 'float',
        name='Falloff',
        description='Falloff of Brush',
        min=0.00,
        max=100.00,
    )
    brush_strength: wrap_property(
        RF_Relax_Brush, 'strength', 'float',
        name='Strength',
        description='Strength of Brush',
        min=0.01,
        max=1.00,
    )

    mask_boundary: bpy.props.EnumProperty(
        name='Mask: Boundary',
        description='Mask: Boundary',
        items=[
            ('EXCLUDE', 'Exclude', 'Relax vertices not along boundary', 0),
            ('SLIDE',   'Slide',   'Relax vertices along boundary, but move them by sliding along boundary', 1),
            ('INCLUDE', 'Include', 'Relax all vertices within brush, regardless of being along boundary', 2),
        ],
        default='INCLUDE',
    )

    def init(self, context, event):
        # print(f'STARTING POLYPEN')
        self.logic = Relax_Logic(context, event, RFTool_Relax.rf_brush, self)
        self.tickle(context)
        self.timer = TimerHandler(120, context=context, enabled=True)

    def reset(self):
        # self.logic.reset()
        pass

    def update(self, context, event):
        # print('update')
        self.logic.update(context, event, RFTool_Relax.rf_brush, self)
        # self.logic.update(context, event, self.insert_mode)

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.timer.stop()
            return {'FINISHED'}

        if event.type == 'Z' and event.ctrl:
            # hack to prevent crashing blender when undoing while still running modal
            # TODO: look at keymap for undo!
            self.timer.stop()
            return {'CANCELLED'}

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




class RFTool_Relax(RFTool_Base):
    bl_idname = "retopoflow.relax"
    bl_label = "Relax"
    bl_description = "Relax the vertex positions to smooth out topology"
    bl_icon = get_path_to_blender_icon('relax')
    bl_widget = None
    bl_operator = 'retopoflow.relax'

    rf_brush = RF_Relax_Brush()

    bl_keymap = chain_rf_keymaps(RFOperator_Relax)

    def draw_settings(context, layout, tool):
        layout.label(text="Brush:")
        props = tool.operator_properties(RFOperator_Relax.bl_idname)
        layout.prop(props, 'brush_radius')
        layout.prop(props, 'brush_falloff')
        layout.prop(props, 'brush_strength')

        # TOOL_HEADER: 3d view > toolbar
        # UI: 3d view > n-panel
        # WINDOW: properties > tool
        if context.region.type == 'TOOL_HEADER':
            pass
        elif context.region.type in {'UI', 'WINDOW'}:
            layout.label(text="Masking Options")
            layout.prop(props, 'mask_boundary', text="Boundary")
        else:
            print(f'RFTool_Relax.draw_settings: {context.region.type=}')

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
