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
import bmesh
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from ..rftool_base import RFTool_Base
from ..rfbrush_base import RFBrush_Base
from ..common.bmesh import get_bmesh_emesh, nearest_bmv_world, nearest_bme_world, NearestBMVert
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
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, size2D_to_size, vec_forward, mouse_from_event
from ..common.maths import view_forward_direction, lerp
from ..common.operator import (
    invoke_operator, execute_operator,
    RFOperator, RFRegisterClass,
    chain_rf_keymaps, wrap_property,
)
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event, nearest_point_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common import gpustate
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.maths import Color, Frame
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D
from ...addon_common.common.reseter import Reseter

from ..rfoperators.transform import RFOperator_Translate_BoundaryLoop


#########################################################
# TODO: This RFBrush is a mess!  rewrite using states?
#########################################################

def filter_bmvs(bmvs):
    return [ bmv for bmv in bmvs if bmv.is_boundary or bmv.is_wire ]

class RFBrush_Strokes(RFBrush_Base):
    # brush settings
    radius = 40
    snap_distance  = 10  # pixel distance when to consider snapping to vert or stroke end (cycle)
    far_distance   = 20  # mouse must move this far away from stroke start to start considering cycle

    # brush visualization settings
    outer_color     = Color((1,1,1,1))
    below_alpha     = Color((1,1,1,0.25))
    inner_color     = Color((1,1,1,0.10))
    stroke_color    = Color.from_ints(255,255,0,255)
    snap_color      = Color.from_ints(255,255,0,255)
    cycle_color     = Color.from_ints(255,255,0,255)
    push_above      = 0.01
    shrink_below    = 0.80
    stroke_smooth   = 0.15  # [0,1], lower => more smoothing

    # hack to know which areas the mouse is in
    mouse_areas = set()  # TODO: make sure this actually works with multiple areas / quad

    def init(self):
        self.mouse = None

        self.hit = False
        self.hit_p = None
        self.hit_n = None
        self.hit_pl = None
        self.hit_scale = None
        self.hit_depth = None
        self.hit_x = None
        self.hit_y = None
        self.hit_z = None
        self.hit_rmat = None

        self.nearest = None
        self.snap_bmv0 = None
        self.snap_bmv1 = None

        self.stroke = None
        self.stroke_far = False    # True when stroke has gone "far enough" away to consider cycle
        self.stroke_cycle = False  # True when stroke has formed a cycle with self
        self.operator = None

    def set_operator(self, operator, context):
        # this is called whenever operator using brush is started
        # note: artist just used another operator, so the data likely changed.
        #       reset nearest info so that we can rebuild structure!
        self.operator = operator
        self.reset_nearest(context)

    def reset(self):
        self.nearest = None
        self.snap_bmv0 = None
        self.snap_bmv1 = None

    def reset_nearest(self, context):
        if self.operator:
            self.matrix_world = context.edit_object.matrix_world
            self.matrix_world_inv = self.matrix_world.inverted()
            self.bm, self.em = get_bmesh_emesh(context)
            self.nearest = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv)
        else:
            self.matrix_world = None
            self.matrix_world_inv = None
            self.bm, self.em = None, None
            self.nearest = None

        self.snap_bmv0 = None
        self.snap_bmv1 = None

    def get_scaled_radius(self):
        return self.hit_scale * self.radius

    def is_stroking(self):
        return self.stroke is not None

    def update(self, context, event):
        if not self.RFCore.is_current_area(context):
            self.reset()
            return

        if self.snap_bmv0 and not self.snap_bmv0.is_valid: self.snap_bmv0 = None
        if self.snap_bmv1 and not self.snap_bmv1.is_valid: self.snap_bmv1 = None

        if not self.is_stroking():
            if not event.ctrl or not self.operator:
                if self.mouse:
                    self.mouse = None
                    self.hit = False
                    context.area.tag_redraw()
                return

        mouse = mouse_from_event(event)

        if self.operator and self.operator.is_active():
            if not self.nearest:
                self.reset_nearest(context)
            self.nearest.update(context, self.hit_pl, filter_fn=(lambda bmv:bmv.is_boundary or bmv.is_wire), distance2d=self.snap_distance)
            if not self.is_stroking():
                self.snap_bmv0 = self.nearest.bmv
                self.snap_bmv1 = None
            elif self.snap_bmv0 != self.nearest.bmv:
                self.snap_bmv1 = self.nearest.bmv
            else:
                self.snap_bmv1 = None

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self.mouse = mouse
                self.mousedown = mouse
                self.stroke = [Point2D(mouse)]
                self.stroke_far = False
                self.stroke_cycle = False

            elif event.value == 'RELEASE':
                if self.is_stroking():
                    self.stroke += [Point2D(mouse)]
                    self.operator.process_stroke(context, self.radius, self.stroke, self.stroke_cycle, self.snap_bmv0, self.snap_bmv1)
                    self.stroke = None
                    self.stroke_cycle = None
                    self.nearest = None
                    self.snap_bmv0 = None
                    self.snap_bmv1 = None

            context.area.tag_redraw()

        if self.mouse and event.type != 'MOUSEMOVE':
            return

        if self.is_stroking():
            pre = self.stroke[-1]
            cur = Point2D(mouse)
            pt = pre + (cur - pre) * RFBrush_Strokes.stroke_smooth
            if raycast_valid_sources(context, pt):
                self.stroke += [pt]
            if (self.stroke[0] - self.stroke[-1]).length > Drawing.scale(self.far_distance):
                self.stroke_far = True
            if self.stroke_far and not self.snap_bmv0 and not self.snap_bmv1:
                self.stroke_cycle = (self.stroke[0] - self.stroke[-1]).length < Drawing.scale(self.snap_distance)

        if self.operator.is_active() or RFOperator_StrokesBrush_Adjust.is_active():
            # artist is actively stroking or adjusting brush properties, so always consider us inside if we're in the same area
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
        # print(f'RFBrush_Strokes.update {(event.mouse_region_x, event.mouse_region_y)}') #{context.region=} {context.region_data=}')
        hit = raycast_valid_sources(context, self.mouse)
        # print(f'  {hit=}')
        if not hit: return
        scale_below = size2D_to_size(context, hit['distance'])
        scale_above = size2D_to_size(context, hit['distance'] - self.push_above)
        # print(f'  {scale=}')
        if not scale_below or not scale_above: return

        n = hit['no_local']
        rmat = Matrix.Rotation(Direction.Z.angle(n), 4, Direction.Z.cross(n))

        self.hit = True
        self.hit_ray = hit['ray_world']
        self.hit_scale_below = scale_below
        self.hit_scale_above = scale_above
        self.hit_p = hit['co_world']
        self.hit_n = hit['no_world']
        self.hit_pl = hit['co_local']
        self.hit_depth = hit['distance']
        self.hit_x = Vec(rmat @ Direction.X)
        self.hit_y = Vec(rmat @ Direction.Y)
        self.hit_z = Vec(rmat @ Direction.Z)
        self.hit_rmat = rmat

    def draw_postpixel(self, context):
        if not self.RFCore.is_current_area(context): return
        #if context.area not in self.mouse_areas: return

        gpustate.blend('ALPHA')

        if not RFOperator_StrokesBrush_Adjust.is_active() and self.mouse:
            if (not self.is_stroking() and self.snap_bmv0) or (self.is_stroking() and self.snap_bmv1):
                Drawing.draw2D_circle(context, Point2D(self.mouse), self.snap_distance, self.snap_color, width=1)
            elif self.stroke_cycle:
                Drawing.draw2D_circle(context, Point2D(self.mouse), self.snap_distance, self.cycle_color, width=1)
            else:
                Drawing.draw2D_circle(context, Point2D(self.mouse), self.snap_distance, self.inner_color, width=1)

        if self.operator and self.operator.is_active() and self.is_stroking():
            Drawing.draw2D_linestrip(context, self.stroke, self.stroke_color, width=2, stipple=[5,5])
            if self.stroke_cycle:
                Drawing.draw2D_linestrip(context, [self.stroke[0], self.stroke[-1]], self.cycle_color, width=2)

        if self.nearest:
            if self.is_stroking():
                if self.snap_bmv0 and self.snap_bmv0.is_valid:
                    co = self.matrix_world @ self.snap_bmv0.co
                    p2d = location_3d_to_region_2d(context.region, context.region_data, co)
                    Drawing.draw2D_linestrip(context, [self.stroke[0], p2d], self.snap_color, width=2)
                if self.snap_bmv1 and self.snap_bmv1.is_valid:
                    co = self.matrix_world @ self.snap_bmv1.co
                    p2d = location_3d_to_region_2d(context.region, context.region_data, co)
                    Drawing.draw2D_linestrip(context, [self.stroke[-1], p2d], self.snap_color, width=2)
            else:
                if self.mouse and self.snap_bmv0 and self.snap_bmv0.is_valid:
                    co = self.matrix_world @ self.snap_bmv0.co
                    p2d = location_3d_to_region_2d(context.region, context.region_data, co)
                    Drawing.draw2D_linestrip(context, [Point2D(self.mouse), p2d], self.snap_color, width=2)

        if RFOperator_StrokesBrush_Adjust.is_active():
            center2D = self.center2D
            r = self.radius
            co = self.outer_color
            Drawing.draw2D_circle(context, center2D, r, co, width=1)

    def draw_postview(self, context):
        if not self.RFCore.is_current_area(context): return
        if context.area not in self.mouse_areas: return
        if RFOperator_StrokesBrush_Adjust.is_active(): return
        self._update(context)
        if not self.hit: return

        pb, n = self.hit_p, self.hit_n
        ra = self.radius * self.hit_scale_above
        rb = self.radius * self.hit_scale_below
        rt = (2 + 4 * (1 - abs(self.hit_n.dot(self.hit_ray[1])))) * self.hit_scale_above
        co = self.outer_color
        pa = pb - self.push_above * self.hit_ray[1].xyz # * context.region_data.view_distance

        gpustate.blend('ALPHA')
        gpustate.depth_mask(False)

        # draw below
        gpustate.depth_test('GREATER')
        Drawing.draw3D_circle(context, pb, rb, co * self.below_alpha, n=n, width=rt)

        # draw above
        gpustate.depth_test('LESS_EQUAL')
        Drawing.draw3D_circle(context, pa, ra, co, n=n, width=rt)

        # reset
        gpustate.depth_test('LESS_EQUAL')
        gpustate.depth_mask(True)


class RFOperator_StrokesBrush_Adjust(RFOperator):
    '''
    Handles resizing of Strokes Brush
    '''
    bl_idname = 'retopoflow.strokes_brush'
    bl_label = 'Strokes Brush'
    bl_description = 'Adjust properties of strokes brush'
    bl_space_type = 'VIEW_3D'
    bl_space_type = 'TOOLS'
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'F', 'value': 'PRESS'}, None),  #, 'ctrl': False, 'shift': False
    ]
    rf_status = ['LMB: Commit', 'RMB: Cancel']

    def can_init(self, context, event):
        return not any(
            instance.is_stroking()
            for instance in RFBrush_Strokes.get_instances()
        )

    def init(self, context, event):
        dist = self.radius_to_dist()
        self.prev_radius = RFBrush_Strokes.radius
        self._change_pre = dist
        mouse = Point2D((event.mouse_region_x, event.mouse_region_y))
        RFBrush_Strokes.center2D = mouse - Vec2D((dist, 0))
        context.area.tag_redraw()

    def dist_to_radius(self, d):
        RFBrush_Strokes.radius = max(5, int(d))
    def radius_to_dist(self):
        return RFBrush_Strokes.radius

    def update(self, context, event):
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            return {'FINISHED'}
        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            self.dist_to_radius(self._change_pre)
            return {'CANCELLED'}
        if event.type == 'ESC' and event.value == 'PRESS':
            self.dist_to_radius(self._change_pre)
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE':
            mouse = Point2D((event.mouse_region_x, event.mouse_region_y))
            dist = (RFBrush_Strokes.center2D - mouse).length
            self.dist_to_radius(dist)
            context.area.tag_redraw()
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'} # allow other operators, such as UNDO!!!

