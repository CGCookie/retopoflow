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
from mathutils import Vector, Matrix

import math
from ..rfbrush_base import RFBrush_Base
from ..common.drawing import (
    Drawing,
)
from ..common.operator import RFOperator, execute_operator
from ..common.raycast import raycast_valid_sources, size2D_to_size, mouse_from_event
from ..common.maths import lerp
from ...addon_common.common.maths import Color, clamp
from ...addon_common.common import gpustate
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D
from ..common.easing import CubicEaseIn


def create_falloff_brush(idname, label, **kwargs):
    fn_disable = kwargs.get('fn_disable', None)

    class RFBrush_Falloff(RFBrush_Base):
        # brush settings
        radius   = kwargs.get('radius',   100)
        falloff  = kwargs.get('falloff',  1.00)
        strength = kwargs.get('strength', 0.75)

        # brush visualization settings
        color           = kwargs.get('color',  Color.from_ints(0, 135, 255, 255))
        below_alpha     = Color((1,1,1,0.25))  # multiplied against color when occluded
        brush_min_alpha = 0.100
        brush_max_alpha = 0.700
        depth_fill      = 0.998 # see note on gl_FragDepth in circle_3D.glsl
        depth_border    = 0.996 # see note on gl_FragDepth in circle_3D.glsl

        # hack to know which areas the mouse is in
        mouse_areas = set()

        operator = None

        @classmethod
        def set_operator(cls, operator):
            cls.operator = operator

        @classmethod
        def is_top_modal(cls, context):
            op_name = cls.operator.bl_label
            ops = context.window.modal_operators
            if not ops: return False
            if ops[0].name == op_name: return True
            if len(ops) >= 2 and ops[0].name == 'Screencast Keys' and ops[1].name == op_name: return True
            return False

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
            self.disabled = False


        def get_scaled_radius(self):
            if not self.hit_scale: return 0.0 # Handle case where hit_scale might not be set yet
            return self.hit_scale * self.radius

        def get_strength_dist(self, dist: float):
            scaled_radius = self.get_scaled_radius()
            # Avoid division by zero or negative radius!
            if scaled_radius <= 0: return 0.0

            # Brush strength, values between [0, 1].
            strength = self.strength

            # Brush falloff, values between [0, 1]:
            # - 0.0: no-falloff, affects with the same strength no matter the distance from the center.
            # - 1.0: max falloff effect, the more 'dist' is closed to the center, the more strength is has.
            falloff = self.falloff

            # Normalized [0.0, 1.0] distance factor (0 at center, 1 at edge).
            normalized_dist_factor = clamp(dist / scaled_radius, 0.0, 1.0)

            # Apply cubic ease curve to the falloff using CubicEaseIn
            # This creates a smooth transition between center and edge with a convex curve
            cubic_ease = CubicEaseIn()
            falloff_factor = cubic_ease(normalized_dist_factor)

            # Apply falloff to strength...
            # When falloff is 0, strength is constant
            # When falloff is 1, strength follows the cubic curve
            strength_in_dist = strength * (1.0 - falloff * falloff_factor)

            # Clamp result to [0, 1]?, ideally we could map range, based on min/max values to [0, 1] range,
            # in order to ensure a richer range of values without clipping, but that's something todo at tool level.
            strength_in_dist = clamp(strength_in_dist, 0.0, 1.0)

            return strength_in_dist

        def get_strength_Point(self, point:Point):
            if not self.hit_p: return 0.0
            return self.get_strength_dist((point - self.hit_p).length)

        def update(self, context, event, *, force=False):
            if fn_disable:
                d = fn_disable(event)
                if self.disabled != d: context.area.tag_redraw()
                self.disabled = d
            if self.disabled: return

            if not force:
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
            if force: self._update(context)

        def _update(self, context):
            if context.area not in self.mouse_areas: return
            self.hit = False
            if not self.mouse: return
            # print(f'RFBrush_Falloff.update {(event.mouse_region_x, event.mouse_region_y)}') #{context.region=} {context.region_data=}')
            hit = raycast_valid_sources(context, self.mouse)
            # print(f'  {hit=}')
            if not hit: return
            #scale = size2D_to_size_point(context, self.mouse, hit['co_world'])
            self.offset = min(hit['distance'] * 0.75, 1.05 * context.space_data.overlay.retopology_offset)
            scale = size2D_to_size(context, hit['distance'], pt=self.mouse)
            scale_offset = size2D_to_size(context, hit['distance'] - self.offset, pt=self.mouse)
            # print(f'  {scale=}')
            if scale is None or scale_offset is None: return

            n = hit['no_local']
            rmat = Matrix.Rotation(Direction.Z.angle(n), 4, Direction.Z.cross(n))

            self.hit = True
            self.hit_ray = hit['ray_world']
            self.hit_scale = scale
            self.hit_scale_offset = scale_offset
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
            if self.disabled: return

            if RFBrush_Falloff.operator.is_active() or RFOperator_FalloffBrush_Adjust.is_active():
                active_op = RFOperator.active_operator()
            else:
                active_op = None
            adjust = active_op.adjust if active_op is not None else ''

            center2D = self.center2D

            r = self.radius if adjust == 'RADIUS' else context.region.height * 0.25 * 0.5
            color = self.color

            # Inner radius should be based on strength instead of falloff
            # Clamp inner radius between min_radius (0.24*r) and outer radius (r)
            min_radius = 0.24 * r
            # With inverted mapping: strength 0.0 → min_radius, strength 1.0 → max_radius
            inner_radius = min_radius + self.strength * (r - min_radius)

            # Calculate falloff for filled area
            gpustate.blend('ALPHA')

            text_value = None

            # Draw - falloff - filled circle ring
            if adjust == 'FALLOFF':
                fillscale = Color((1, 1, 1, .64))
                center_color = color * fillscale
                edge_color = (center_color[0], center_color[1], center_color[2], 0.0)
                Drawing.draw2D_radial_gradient(context, center2D, r, center_color, edge_color, t=self.falloff, easing_type=2)  # 2 == cubic easing function.
                # Draw circle (40% of radius) for brush-falloff reference for 0.0-2.0 range reference.
                Drawing.draw2D_smooth_circle(context, center2D, r * 0.4, color, width=0.5)
                text_value = f"{round(self.falloff, 2)}"

            if adjust == 'RADIUS':
                Drawing.draw2D_smooth_circle(context, center2D, active_op.prev_radius, color, width=0.5)

            # Draw outer - brush radius - circle border
            Drawing.draw2D_smooth_circle(context, center2D, r, color, width=2 if adjust == 'RADIUS' else 0.5)

            if adjust == 'STRENGTH':
                # Draw inner - strength-based - circle border
                Drawing.draw2D_smooth_circle(context, center2D, inner_radius, color, width=2)
                # Draw minimum circle (10% of radius) for brush-trength control.
                Drawing.draw2D_smooth_circle(context, center2D, min_radius, color, width=0.5)

                text_value = f"{round(self.strength, 2)}"

            if text_value:
                text_w = Drawing.get_text_width(text_value)
                text_h = Drawing.get_line_height(text_value)
                Drawing.text_draw2D_simple(text_value, center2D + Vector((-text_w, text_h)) * 0.5)

            # Draw center dot (well, skipping it since Blender brushes does not draw this).
            # Drawing.draw2D_circle(context, center2D, 2, cm, width=1)

        def draw_postview(self, context):
            if context.area not in self.mouse_areas: return
            if RFOperator_FalloffBrush_Adjust.is_active(): return
            if not self.RFCore or not (self.RFCore.is_top_modal(context) or self.is_top_modal(context)): return
            if self.disabled: return
            self._update(context)
            if not self.hit or self.hit_n is None: return # Ensure we have a hit and a normal

            # Calculate position and orientation
            p = self.hit_p - self.hit_ray[1].xyz * self.offset
            n = self.hit_n

            # Calculate outer radius based on actual brush radius and scale
            ro = self.radius

            # Calculate minimum radius (24% of outer radius)
            rmin = 0.24 * ro

            # Calculate inner radius based on strength
            # Map strength 0.0 → min_radius, strength 1.0 → outer_radius
            ri = rmin + self.strength * (ro - rmin)

            # Color.
            color = self.color
            # Ensure below_alpha has alpha component 'a'
            below_alpha_val = self.below_alpha.a if hasattr(self.below_alpha, 'a') else self.below_alpha[3] if isinstance(self.below_alpha, (list, tuple)) and len(self.below_alpha) == 4 else 0.25

            gpustate.blend('ALPHA')
            gpustate.depth_mask(True) # Keep depth mask enabled

            viewport_size = (context.region.width, context.region.height)

            # draw above
            gpustate.depth_test('LESS_EQUAL')
            Drawing.draw_circle_3d(position=p, normal=n, color=color, radius=ro, thickness=2, scale=self.hit_scale_offset, segments=None, viewport_size=viewport_size)
            Drawing.draw_circle_3d(position=p, normal=n, color=color, radius=ri, thickness=1, scale=self.hit_scale_offset, segments=None, viewport_size=viewport_size)

            # draw below
            gpustate.depth_test('GREATER')
            # Adjust alpha for drawing below
            color_below = Color((*color[:3], color.a * below_alpha_val))
            Drawing.draw_circle_3d(position=p, normal=n, color=color_below, radius=ro, thickness=2, scale=self.hit_scale_offset, segments=None, viewport_size=viewport_size)
            Drawing.draw_circle_3d(position=p, normal=n, color=color_below, radius=ri, thickness=1, scale=self.hit_scale_offset, segments=None, viewport_size=viewport_size)

            # reset
            gpustate.depth_test('LESS_EQUAL')
            # gpustate.depth_mask(False) # Optionally disable depth mask if needed after drawing

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
                ('NONE',     'None',     f'Adjust Nothing',          -1), # prevents default
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

        def get_vis_radius(self, context):
            return context.region.height * 0.25 * 0.5

        def dist_to_radius(self, d, context=None):
            RFBrush_Falloff.radius = max(5, int(d))

        def radius_to_dist(self, context=None):
            return RFBrush_Falloff.radius

        def dist_to_strength(self, d, context):
            # Use visualization radius instead of actual brush radius
            vis_radius = self.get_vis_radius(context)
            min_radius = 0.24 * vis_radius
            max_radius = vis_radius

            # Map distance d to a strength value:
            # - When d is near min_radius, strength should be 0.0
            # - When d is near max_radius, strength should be 1.0
            # - Ensure that at max_radius we get exactly 1.0
            normalized_dist = clamp((d - min_radius) / (max_radius - min_radius), 0.0, 1.0)
            RFBrush_Falloff.strength = normalized_dist

        def strength_to_dist(self, context):
            # Use visualization radius instead of actual brush radius
            vis_radius = self.get_vis_radius(context)
            min_radius = 0.24 * vis_radius
            max_radius = vis_radius
            # Convert strength to distance based on the same mapping:
            # strength 0.0 → min_radius, strength 1.0 → max_radius
            return min_radius + RFBrush_Falloff.strength * (max_radius - min_radius)

        def dist_to_falloff(self, d, context):
            # Use visualization radius instead of actual brush radius
            vis_radius = self.get_vis_radius(context)

            # Normalize distance as percentage of visualization radius (0.0 to 1.0)
            norm_dist = clamp(d / vis_radius, 0.0, 1.0)

            # Map distance directly to falloff value (0.0 to 1.0)
            # - 0.0 distance = 0.0 falloff (no falloff)
            # - 1.0 distance = 1.0 falloff (maximum falloff)
            RFBrush_Falloff.falloff = norm_dist

        def falloff_to_dist(self, context):
            # Use visualization radius instead of actual brush radius
            vis_radius = self.get_vis_radius(context)

            # Get current falloff value (should be between 0.0 and 1.0)
            falloff = clamp(RFBrush_Falloff.falloff, 0.0, 1.0)

            # Map falloff directly to distance
            # - 0.0 falloff = 0.0 distance (no falloff)
            # - 1.0 falloff = 1.0 distance (maximum falloff)
            return falloff * vis_radius

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

            # Get the initial value and convert it to distance
            dist = self._var_to_dist_fn(context)

            # Store the initial radius for radius adjustment
            self.prev_radius = RFBrush_Falloff.radius

            # Store the initial value for potential cancellation
            self._change_pre = dist

            # Get the mouse position
            mouse = Point2D((event.mouse_region_x, event.mouse_region_y))

            # Set the center point for the adjustment
            # For radius adjustment, we want to start from the current radius
            # For strength and falloff, we want to start from the current value's position
            if self.adjust == 'RADIUS':
                RFBrush_Falloff.center2D = mouse - Vec2D((dist, 0))
            else:
                # For strength and falloff, calculate the center based on the current value
                # This ensures that moving to the edge will reach the maximum value
                angle = 0.0  # We'll use horizontal direction for consistency
                RFBrush_Falloff.center2D = mouse - Vec2D((dist * math.cos(angle), dist * math.sin(angle)))

            context.area.tag_redraw()

        def update(self, context, event):
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                return {'FINISHED'}
            if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
                self._dist_to_var_fn(self._change_pre, context)
                return {'CANCELLED'}
            if event.type == 'ESC' and event.value == 'PRESS':
                self._dist_to_var_fn(self._change_pre, context)
                return {'CANCELLED'}

            if event.type == 'MOUSEMOVE':
                mouse = Point2D((event.mouse_region_x, event.mouse_region_y))

                # Calculate distance from center to mouse
                dist = (RFBrush_Falloff.center2D - mouse).length

                # For radius adjustment, we want to use the raw distance
                # For strength and falloff, we want to ensure we can reach the maximum value
                if self.adjust != 'RADIUS':
                    # For strength and falloff, we want to ensure that reaching the edge
                    # of the circle gives us the maximum value
                    max_dist = self.get_vis_radius(context)
                    dist = min(dist, max_dist)

                self._dist_to_var_fn(dist, context)
                context.area.tag_redraw()
                return {'PASS_THROUGH'}

            return {'RUNNING_MODAL'} # allow other operators, such as UNDO!!!

    return (RFBrush_Falloff, RFOperator_FalloffBrush_Adjust)
