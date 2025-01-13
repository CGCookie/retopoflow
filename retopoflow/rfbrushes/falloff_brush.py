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
from ..rfbrush_base import RFBrush_Base
from ..common.bmesh import get_bmesh_emesh, NearestBMVert
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


def create_falloff_brush(idname, label, **kwargs):
    class RFBrush_Falloff(RFBrush_Base):
        # brush settings
        radius   = kwargs.get('radius',   200)
        falloff  = kwargs.get('falloff',  1.5)
        strength = kwargs.get('strength', 0.75)

        # brush visualization settings
        fill_color      = kwargs.get('fill_color',  Color.from_ints(0, 135, 255, 255))
        outer_color     = Color((1,1,1,1))     # outer circle
        inner_color     = Color((1,1,1,0.5))   # inner circle
        min_color       = Color((1,1,1,0.5))   # tiny circle at very center (only when adjusting)
        below_alpha     = Color((1,1,1,0.25))  # multiplied against fill_color when occluded
        brush_min_alpha = 0.100
        brush_max_alpha = 0.700
        depth_fill      = 0.998
        depth_border    = 0.996

        # hack to know which areas the mouse is in
        mouse_areas = set()

        operator = None

        @classmethod
        def set_operator(cls, operator):
            cls.operator = operator

        @classmethod
        def is_top_modal(cls, context):
            return context.window.modal_operators[0].name == cls.operator.bl_label

        def init(self):
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
            if not RFBrush_Falloff.operator: return
            if event.type != 'MOUSEMOVE': return

            mouse = mouse_from_event(event)

            if RFBrush_Falloff.operator.is_active() or RFOperator_FalloffBrush_Adjust.is_active():
                active_op = RFOperator.active_operator()
                # artist is actively brushing or adjusting brush properties, so always consider us inside if we're in the same area
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
            # print(f'RFBrush_Falloff.update {(event.mouse_region_x, event.mouse_region_y)}') #{context.region=} {context.region_data=}')
            hit = raycast_valid_sources(context, self.mouse)
            # print(f'  {hit=}')
            if not hit: return
            scale = size2D_to_size(context, hit['distance'])
            # print(f'  {scale=}')
            if scale is None: return

            n = hit['no_local']
            rmat = Matrix.Rotation(Direction.Z.angle(n), 4, Direction.Z.cross(n))

            self.hit = True
            self.hit_ray = hit['ray_world']
            self.hit_scale = scale
            self.hit_p = hit['co_world']
            self.hit_n = hit['no_world']
            self.hit_depth = hit['distance']
            self.hit_x = Vec(rmat @ Direction.X)
            self.hit_y = Vec(rmat @ Direction.Y)
            self.hit_z = Vec(rmat @ Direction.Z)
            self.hit_rmat = rmat

        def draw_postpixel(self, context):
            if not RFBrush_Falloff.operator: return
            if context.area not in self.mouse_areas: return
            if not RFOperator_FalloffBrush_Adjust.is_active(): return
            center2D = self.center2D
            fillscale = Color((1, 1, 1, lerp(self.strength, self.brush_min_alpha, self.brush_max_alpha)))
            r = self.radius
            co, ci, cf = self.outer_color, self.inner_color, self.fill_color * fillscale
            cm = self.min_color
            ff = math.pow(0.5, 1.0 / max(self.falloff, 0.0001))
            fs = (1-ff) * self.radius
            gpustate.blend('ALPHA')
            Drawing.draw2D_circle(context, center2D, r-fs/2, cf, width=fs)
            Drawing.draw2D_circle(context, center2D, r,      co, width=1)
            Drawing.draw2D_circle(context, center2D, r*ff,   ci, width=1)
            Drawing.draw2D_circle(context, center2D, 2,      cm, width=1)

        def draw_postview(self, context):
            if context.area not in self.mouse_areas: return
            if RFOperator_FalloffBrush_Adjust.is_active(): return
            if not (self.RFCore.is_top_modal(context) or self.is_top_modal(context)): return
            # print(f'RFBrush_Falloff.draw_postview {random()}')
            # print(f'RFBrush_Falloff.draw_postview {self.hit=}')
            self._update(context)
            if not self.hit: return

            fillscale = Color((1, 1, 1, lerp(self.strength, self.brush_min_alpha, self.brush_max_alpha)))

            ff = math.pow(0.5, 1.0 / max(self.falloff, 0.0001))
            p, n = self.hit_p, self.hit_n
            ro = self.radius * self.hit_scale
            ri = ro * ff
            rm, rd = (ro + ri) / 2.0, (ro - ri)
            rt = (2 + 2 * (1 + self.hit_n.dot(self.hit_ray[1]))) * self.hit_scale
            co, ci, cf = self.outer_color, self.inner_color, self.fill_color * fillscale
            #print(self.hit_n, self.hit_ray[1], self.hit_n.dot(self.hit_ray[1]))

            gpustate.blend('ALPHA')
            gpustate.depth_mask(False)

            # draw below
            gpustate.depth_test('GREATER')
            Drawing.draw3D_circle(context, p, rm, cf * self.below_alpha, n=n, width=rd, depth_far=self.depth_fill)
            Drawing.draw3D_circle(context, p, ro, co * self.below_alpha, n=n, width=rt, depth_far=self.depth_border)
            Drawing.draw3D_circle(context, p, ri, ci * self.below_alpha, n=n, width=rt, depth_far=self.depth_border)

            # draw above
            gpustate.depth_test('LESS_EQUAL')
            Drawing.draw3D_circle(context, p, rm, cf, n=n, width=rd, depth_far=self.depth_fill)
            Drawing.draw3D_circle(context, p, ro, co, n=n, width=rt, depth_far=self.depth_border)
            Drawing.draw3D_circle(context, p, ri, ci, n=n, width=rt, depth_far=self.depth_border)

            # reset
            gpustate.depth_test('LESS_EQUAL')
            gpustate.depth_mask(True)

    class RFOperator_FalloffBrush_Adjust(RFOperator):
        bl_idname      = f'retopoflow.{idname}'
        bl_label       = label
        bl_description = f'Adjust properties of {label}'
        bl_space_type  = 'VIEW_3D'
        bl_space_type  = 'TOOLS'
        bl_options     = set()

        rf_keymaps = [
            # see hacks below
            (f'retopoflow.{idname}_radius',   {'type': 'F', 'value': 'PRESS', 'ctrl': 0, 'shift': 0}, None),
            (f'retopoflow.{idname}_falloff',  {'type': 'F', 'value': 'PRESS', 'ctrl': 1, 'shift': 0}, None),
            (f'retopoflow.{idname}_strength', {'type': 'F', 'value': 'PRESS', 'ctrl': 0, 'shift': 1}, None),
        ]
        rf_status = ['LMB: Commit', 'RMB: Cancel']

        adjust: bpy.props.EnumProperty(
            name=f'{label} Property',
            description=f'Property of {label} to adjust',
            items=[
                ('NONE',     'None',     f'Adjust Nothing',              -1), # prevents default
                ('RADIUS',   'Radius',   f'Adjust {label} Radius',    0),
                ('STRENGTH', 'Strength', f'Adjust {label} Strength',  1),
                ('FALLOFF',  'Falloff',  f'Adjust {label} Falloff',   2),
            ],
            default='NONE',
        )

        #################################################################################
        # these are hacks to launch falloff brush operator with certain set properties
        @staticmethod
        @execute_operator(f'{idname}_radius',   f'Adjust {label} Radius')
        def adjust_radius(context):
            op = getattr(bpy.ops.retopoflow, f'{idname}')
            op('INVOKE_DEFAULT', adjust='RADIUS')
        @staticmethod
        @execute_operator(f'{idname}_strength', f'Adjust {label} Strength')
        def adjust_strength(context):
            op = getattr(bpy.ops.retopoflow, f'{idname}')
            op('INVOKE_DEFAULT', adjust='STRENGTH')
        @staticmethod
        @execute_operator(f'{idname}_falloff',  f'Adjust {label} Falloff')
        def adjust_falloff(context):
            op = getattr(bpy.ops.retopoflow, f'{idname}')
            op('INVOKE_DEFAULT', adjust='FALLOFF')
        #################################################################################

        def can_init(self, context, event):
            if self.adjust == 'NONE': return False

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

            dist = self._var_to_dist_fn()
            self.prev_radius = RFBrush_Falloff.radius
            self._change_pre = dist
            mouse = Point2D((event.mouse_region_x, event.mouse_region_y))
            RFBrush_Falloff.center2D = mouse - Vec2D((dist, 0))
            context.area.tag_redraw()

        def dist_to_radius(self, d):
            RFBrush_Falloff.radius = max(5, int(d))
        def radius_to_dist(self):
            return RFBrush_Falloff.radius
        def dist_to_strength(self, d):
            RFBrush_Falloff.strength = 1.0 - max(0.01, min(1.0, d / RFBrush_Falloff.radius))
        def strength_to_dist(self):
            return RFBrush_Falloff.radius * (1.0 - RFBrush_Falloff.strength)
        def dist_to_falloff(self, d):
            RFBrush_Falloff.falloff = math.log(0.5) / math.log(max(0.01, min(0.99, d / RFBrush_Falloff.radius)))
        def falloff_to_dist(self):
            return RFBrush_Falloff.radius * math.pow(0.5, 1.0 / max(RFBrush_Falloff.falloff, 0.0001))

        def update(self, context, event):
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                return {'FINISHED'}
            if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
                self._dist_to_var_fn(self._change_pre)
                return {'CANCELLED'}
            if event.type == 'ESC' and event.value == 'PRESS':
                self._dist_to_var_fn(self._change_pre)
                return {'CANCELLED'}

            if event.type == 'MOUSEMOVE':
                mouse = Point2D((event.mouse_region_x, event.mouse_region_y))
                dist = (RFBrush_Falloff.center2D - mouse).length
                self._dist_to_var_fn(dist)
                context.area.tag_redraw()
                return {'PASS_THROUGH'}

            return {'RUNNING_MODAL'} # allow other operators, such as UNDO!!!

    return (RFBrush_Falloff, RFOperator_FalloffBrush_Adjust)