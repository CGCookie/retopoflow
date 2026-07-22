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
from bpy.types import Context, Event, Area, SpaceView3D, View3DOverlay
from mathutils import Vector, Matrix

from typing import Protocol, cast
from collections.abc import Sequence, Callable

import math
from ..rfglobals import RFGlobals
from ..rfbrush_base import RFBrush_Base
from ..common.bpy_helper import bpy_ops_retopoflow
from ..common.drawing import Drawing
from ..common.operator import RFOperator, execute_operator, RFKeyMaps
from ..common.raycast import raycast_valid_sources, size2D_to_size, mouse_from_event
from ...addon_common.common.maths import Color, clamp
from ...addon_common.common import gpustate
from ...addon_common.common.maths import Direction, Vec, Point, Point2D, Vec2D
from ..common.easing import CubicEaseIn

class ConvertSetCallable(Protocol):
    def __call__(self, distance : float, context : Context):
        pass

class ConvertGetCallable(Protocol):
    def __call__(self, context : Context) -> float:
        return 0


def create_falloff_brush(
    idname : str,
    label : str,
    *,
    fn_disable : Callable[[Event], bool] | None = None,
    radius : float = 100.0,
    falloff : float = 1.00,
    strength : float = 0.75,
    color : Color | None = None,
) -> tuple[type[RFBrush_Base], type[RFOperator]]:

    # relabel these variables so that we can reference them in class definition below
    arg_radius = radius
    arg_falloff = falloff
    arg_strength = strength
    arg_color : Color = color or Color.from_ints(0, 135, 255, 255)

    class RFBrush_Falloff(RFBrush_Base):
        # brush settings
        radius   : float = arg_radius
        falloff  : float = arg_falloff
        strength : float = arg_strength

        # brush visualization settings
        color           : Color = arg_color
        below_alpha     : Color = Color((1,1,1,0.25))  # multiplied against color when occluded
        brush_min_alpha : float = 0.100
        brush_max_alpha : float = 0.700
        depth_fill      : float = 0.998 # see note on gl_FragDepth in circle_3D.glsl
        depth_border    : float = 0.996 # see note on gl_FragDepth in circle_3D.glsl

        # hack to know which areas the mouse is in
        mouse_areas : set[Area] = set()

        operator : RFOperator | None = None

        mouse : tuple[int, int] | None = None
        hit_ray : tuple[Vector,Vector] | None = None
        hit : bool = False
        hit_p : Vector | None = None
        hit_n : Vector | None = None
        hit_scale : float | None = None
        hit_depth : float | None = None
        hit_x : Direction | None = None
        hit_y : Direction | None = None
        hit_z : Direction | None = None
        hit_rmat : Matrix | None = None
        disabled : bool = False
        offset : float = 0.0
        hit_scale_offset : float = 0.0
        center2D : Vector | None = None

        @classmethod
        def set_operator(cls, operator : RFOperator | None):
            cls.operator = operator

        @classmethod
        def is_top_modal(cls, context : Context):
            if not cls.operator: return False
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

        def stop(self):
            self.set_operator(None)

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

        def update(self, context : Context, event : Event, *, force : bool = False) -> None:
            if RFOperator_FalloffBrush_Adjust.is_active():
                self.disabled = False
            elif fn_disable:
                d = fn_disable(event)
                if self.disabled != d: context.area.tag_redraw()
                self.disabled = d
            else:
                self.disabled = False
            if self.disabled: return

            if not force:
                if not RFBrush_Falloff.operator: return

                if event.type != 'MOUSEMOVE': return

            if not RFBrush_Falloff.operator: return

            mouse = mouse_from_event(event)
            mouse_inside : bool = False
            if RFBrush_Falloff.operator.is_active() or RFOperator_FalloffBrush_Adjust.is_active():
                if active_op := RFOperator.active_operator():
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

        def _update(self, context : Context):
            if context.area not in self.mouse_areas:
                return
            if not isinstance(context.space_data, SpaceView3D):
                return
            self.hit = False
            if not self.mouse: return
            # print(f'RFBrush_Falloff.update {(event.mouse_region_x, event.mouse_region_y)}') #{context.region=} {context.region_data=}')
            hit = raycast_valid_sources(context, self.mouse, respect_clip_planes=True)
            # print(f'  {hit=}')
            if not hit:
                return
            #scale = size2D_to_size_point(context, self.mouse, hit['co_world'])
            distance : float = hit['distance']
            space : SpaceView3D = context.space_data
            overlay : View3DOverlay = space.overlay
            self.offset = min(distance * 0.75, 1.05 * overlay.retopology_offset)
            scale = size2D_to_size(context, distance, pt=self.mouse)
            scale_offset = size2D_to_size(context, distance - self.offset, pt=self.mouse)
            # print(f'  {scale=}')
            if scale is None or scale_offset is None: return

            n : Vector = hit['no_local']
            rmat = Matrix.Rotation(Direction.Z().angle(n), 4, Direction.Z().cross(n))

            self.hit = True
            self.hit_ray = hit['ray_world']
            self.hit_scale = scale
            self.hit_scale_offset = scale_offset
            self.hit_p = hit['co_world']
            self.hit_n = hit['no_world']
            self.hit_depth = hit['distance']
            self.hit_x = Direction(rmat @ Direction.X())
            self.hit_y = Direction(rmat @ Direction.Y())
            self.hit_z = Direction(rmat @ Direction.Z())
            self.hit_rmat = rmat

        def draw_postpixel(self, context : Context):
            if not RFBrush_Falloff.operator:
                return
            if context.area not in self.mouse_areas:
                return
            if not RFOperator_FalloffBrush_Adjust.is_active():
                return
            if self.disabled:
                return

            if not RFBrush_Falloff.operator.is_active() and not RFOperator_FalloffBrush_Adjust.is_active():
                return

            center2D = self.center2D
            if center2D is None:
                return

            active_op = RFOperator.active_operator()
            adjust = active_op.adjust if active_op is not None else ''

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
                Drawing.draw2D_smooth_circle(context, center2D, active_op.prev_radius, color, width=0.5, apply_ui_scale=False)

            # Draw outer - brush radius - circle border
            Drawing.draw2D_smooth_circle(context, center2D, r, color, width=2 if adjust == 'RADIUS' else 0.5, apply_ui_scale=(adjust != 'RADIUS'))

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

        def draw_postview(self, context : Context):
            RFCore = RFGlobals.RFCore_None
            if not RFCore:
                return
            if context.area not in self.mouse_areas:
                return
            if RFOperator_FalloffBrush_Adjust.is_active():
                return
            if not RFCore or not (RFCore.is_top_modal(context) or self.is_top_modal(context)):
                return
            if self.disabled:
                return

            self._update(context)
            if not self.hit or not self.hit_p or not self.hit_n or not self.hit_ray:
                return # Ensure we have a hit and a normal

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
            color : Color = self.color
            # Ensure below_alpha has alpha component 'a'
            below_alpha_val = (
                self.below_alpha.a if hasattr(self.below_alpha, 'a') else (
                    self.below_alpha[3] if isinstance(self.below_alpha, (list, tuple)) and len(self.below_alpha) == 4 else 0.25
                )
            )

            gpustate.blend('ALPHA')
            gpustate.depth_mask(True) # Keep depth mask enabled

            viewport_size : tuple[float, float] = (context.region.width, context.region.height)

            # draw above
            gpustate.depth_test('LESS_EQUAL')
            Drawing.draw_circle_3d(position=p, normal=n, color=color, radius=ro, thickness=2, scale=self.hit_scale_offset, segments=None, viewport_size=viewport_size)
            Drawing.draw_circle_3d(position=p, normal=n, color=color, radius=ri, thickness=1, scale=self.hit_scale_offset, segments=None, viewport_size=viewport_size)

            # draw below
            gpustate.depth_test('GREATER')
            # Adjust alpha for drawing below
            color_below = Color((color.r, color.g, color.b, color.a * below_alpha_val))
            Drawing.draw_circle_3d(position=p, normal=n, color=color_below, radius=ro, thickness=2, scale=self.hit_scale_offset, segments=None, viewport_size=viewport_size)
            Drawing.draw_circle_3d(position=p, normal=n, color=color_below, radius=ri, thickness=1, scale=self.hit_scale_offset, segments=None, viewport_size=viewport_size)

            # reset
            gpustate.depth_test('LESS_EQUAL')
            # gpustate.depth_mask(False) # Optionally disable depth mask if needed after drawing

    class RFOperator_FalloffBrush_Adjust(RFOperator):
        bl_idname      : str = f'retopoflow.{idname}'
        bl_label       : str = label
        bl_description : str = f'Adjust properties of {label}'
        bl_space_type  : str = 'VIEW_3D'
        bl_region_type : str = 'TOOLS'
        bl_options     : set[str] = set()

        rf_keymaps : RFKeyMaps = [
            # see hacks below
            (f'retopoflow.{idname}_radius',   {'type': 'F', 'value': 'PRESS', 'ctrl': 0, 'shift': 0}, {'km_context': 'init', 'km_label': 'Adjust Radius', 'km_extra_icons': ['EVENT_LEFTBRACKET', 'EVENT_RIGHTBRACKET']}),
            (f'retopoflow.{idname}_falloff',  {'type': 'F', 'value': 'PRESS', 'ctrl': 1, 'shift': 0}, {'km_context': 'init', 'km_label': 'Adjust Falloff'}),
            (f'retopoflow.{idname}_strength', {'type': 'F', 'value': 'PRESS', 'ctrl': 0, 'shift': 1}, {'km_context': 'init', 'km_label': 'Adjust Strength'}),
            (f'retopoflow.{idname}_radius_decrease', {'type': 'LEFT_BRACKET',  'value': 'PRESS'}, None),
            (f'retopoflow.{idname}_radius_increase', {'type': 'RIGHT_BRACKET', 'value': 'PRESS'}, None),
        ]
        rf_status : dict[str, Sequence[str]] = {
            'adjust': ('LMB: Commit', 'RMB: Cancel')
        }

        adjust: bpy.props.EnumProperty( # pyright: ignore[reportUninitializedInstanceVariable]
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

        _dist_to_var_fn : ConvertSetCallable # pyright: ignore[reportUninitializedInstanceVariable]
        _var_to_dist_fn : ConvertGetCallable # pyright: ignore[reportUninitializedInstanceVariable]
        prev_radius : float # pyright: ignore[reportUninitializedInstanceVariable]
        _change_pre : float # pyright: ignore[reportUninitializedInstanceVariable]

        #################################################################################
        # these are hacks to launch falloff brush operator with certain set properties

        @execute_operator(f'{idname}_radius',   f'Adjust {label} Radius')
        @staticmethod
        def adjust_radius(_context : Context):
            _ = bpy_ops_retopoflow(idname, 'INVOKE_DEFAULT', adjust='RADIUS')

        @execute_operator(f'{idname}_strength', f'Adjust {label} Strength')
        @staticmethod
        def adjust_strength(_context : Context):
            _ = bpy_ops_retopoflow(idname, 'INVOKE_DEFAULT', adjust='STRENGTH')

        @execute_operator(f'{idname}_falloff',  f'Adjust {label} Falloff')
        @staticmethod
        def adjust_falloff(_context : Context):
            _ = bpy_ops_retopoflow(idname, 'INVOKE_DEFAULT', adjust='FALLOFF')

        @execute_operator(f'{idname}_radius_increase', f'Increase {label} Radius')
        @staticmethod
        def increase_radius(context : Context):
            RFBrush_Falloff.radius = min(1000, max(RFBrush_Falloff.radius + 1, round(RFBrush_Falloff.radius * 1.1)))
            if context.area: context.area.tag_redraw()

        @execute_operator(f'{idname}_radius_decrease', f'Decrease {label} Radius')
        @staticmethod
        def decrease_radius(context : Context):
            RFBrush_Falloff.radius = max(5, min(RFBrush_Falloff.radius - 1, round(RFBrush_Falloff.radius / 1.1)))
            if context.area: context.area.tag_redraw()


        #################################################################################

        def get_vis_radius(self, context : Context) -> float:
            return context.region.height * 0.25 * 0.5

        def dist_to_radius(self, distance : float, context : Context):
            RFBrush_Falloff.radius = max(5, int(distance))

        def radius_to_dist(self, context : Context) -> float:
            return RFBrush_Falloff.radius

        def dist_to_strength(self, distance : float, context : Context):
            # Use visualization radius instead of actual brush radius
            vis_radius = self.get_vis_radius(context)
            min_radius = 0.24 * vis_radius
            max_radius = vis_radius

            # Map distance d to a strength value:
            # - When d is near min_radius, strength should be 0.0
            # - When d is near max_radius, strength should be 1.0
            # - Ensure that at max_radius we get exactly 1.0
            normalized_dist = clamp((distance - min_radius) / (max_radius - min_radius), 0.0, 1.0)
            RFBrush_Falloff.strength = normalized_dist

        def strength_to_dist(self, context : Context) -> float:
            # Use visualization radius instead of actual brush radius
            vis_radius = self.get_vis_radius(context)
            min_radius = 0.24 * vis_radius
            max_radius = vis_radius
            # Convert strength to distance based on the same mapping:
            # strength 0.0 → min_radius, strength 1.0 → max_radius
            return min_radius + RFBrush_Falloff.strength * (max_radius - min_radius)

        def dist_to_falloff(self, distance : float, context : Context):
            # Use visualization radius instead of actual brush radius
            vis_radius = self.get_vis_radius(context)

            # Normalize distance as percentage of visualization radius (0.0 to 1.0)
            norm_dist = clamp(distance / vis_radius, 0.0, 1.0)

            # Map distance directly to falloff value (0.0 to 1.0)
            # - 0.0 distance = 0.0 falloff (no falloff)
            # - 1.0 distance = 1.0 falloff (maximum falloff)
            RFBrush_Falloff.falloff = norm_dist

        def falloff_to_dist(self, context : Context) -> float:
            # Use visualization radius instead of actual brush radius
            vis_radius = self.get_vis_radius(context)

            # Get current falloff value (should be between 0.0 and 1.0)
            falloff = clamp(RFBrush_Falloff.falloff, 0.0, 1.0)

            # Map falloff directly to distance
            # - 0.0 falloff = 0.0 distance (no falloff)
            # - 1.0 falloff = 1.0 distance (maximum falloff)
            return falloff * vis_radius

        def can_init(self, _context : Context, _event : Event) -> bool:
            return self.adjust != 'NONE'

        def init(self, context, event):
            self.set_statusbar_override(self.rf_status['adjust'])

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

        def finish(self, context : Context, cancel=False):
            if cancel:
                self._dist_to_var_fn(self._change_pre, context)
            self.set_statusbar_override(None)

        def update(self, context, event):
            if event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
                cancel = event.type in {'RIGHTMOUSE', 'ESC'}
                self.finish(context, cancel=cancel)
                return {'CANCELLED'} if cancel else {'FINISHED'}

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
