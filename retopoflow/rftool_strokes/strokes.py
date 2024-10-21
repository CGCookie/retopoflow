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
from ..common.bmesh import get_bmesh_emesh, nearest_bmv_world, nearest_bme_world
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

# from .contours_logic import Contours_Logic

import random


class RFBrush_Strokes(RFBrush_Base):
    # brush settings
    radius = 40

    # brush visualization settings
    outer_color     = Color((1,1,1,1))
    below_alpha     = Color((1,1,1,0.25))
    depth_border    = 0.994

    # hack to know which areas the mouse is in
    mouse_areas = set()

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

    def update(self, context, event):
        if not event.ctrl:
            if self.mouse:
                self.mouse = None
                self.hit = False
                context.area.tag_redraw()
            return

        if self.mouse and event.type != 'MOUSEMOVE':
            return

        mouse = mouse_from_event(event)

        if RFOperator_Strokes.is_active() or RFOperator_StrokesBrush_Adjust.is_active():
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
        if context.area not in self.mouse_areas: return
        if not RFOperator_StrokesBrush_Adjust.is_active(): return
        center2D = self.center2D
        r = self.radius
        co = self.outer_color
        gpustate.blend('ALPHA')
        Drawing.draw2D_circle(context, center2D, r, co, width=1)

    def draw_postview(self, context):
        if context.area not in self.mouse_areas: return
        if RFOperator_StrokesBrush_Adjust.is_active(): return
        # print(f'RFBrush_Strokes.draw_postview {random()}')
        # print(f'RFBrush_Strokes.draw_postview {self.hit=}')
        self._update(context)
        if not self.hit: return

        p, n = self.hit_p, self.hit_n
        ro = self.radius * self.hit_scale
        rt = (2 + 2 * (1 + self.hit_n.dot(self.hit_ray[1]))) * self.hit_scale
        co = self.outer_color
        #print(self.hit_n, self.hit_ray[1], self.hit_n.dot(self.hit_ray[1]))

        gpustate.blend('ALPHA')
        gpustate.depth_mask(False)

        # draw below
        gpustate.depth_test('GREATER')
        Drawing.draw3D_circle(context, p, ro, co * self.below_alpha, n=n, width=rt, depth_far=self.depth_border)

        # draw above
        gpustate.depth_test('LESS_EQUAL')
        Drawing.draw3D_circle(context, p, ro, co, n=n, width=rt, depth_far=self.depth_border)

        # reset
        gpustate.depth_test('LESS_EQUAL')
        gpustate.depth_mask(True)

class RFOperator_StrokesBrush_Adjust(RFOperator):
    bl_idname = 'retopoflow.strokes_brush'
    bl_label = 'Strokes Brush'
    bl_description = 'Adjust properties of strokes brush'
    bl_space_type = 'VIEW_3D'
    bl_space_type = 'TOOLS'
    bl_options = set()

    rf_keymaps = [
        ('retopoflow.strokes_brush', {'type': 'F', 'value': 'PRESS', 'ctrl': 0, 'shift': 0}, None),
    ]
    rf_status = ['LMB: Commit', 'RMB: Cancel']

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






class RFOperator_Strokes(RFOperator):
    bl_idname = 'retopoflow.strokes'
    bl_label = 'Strokes'
    bl_description = 'Insert edge strips and extrude edges into a patch'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),

        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, None),

        ('mesh.loop_multi_select', {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, None),
    ]

    rf_status = ['LMB: Insert']

    span_insert_mode: bpy.props.EnumProperty(
        name='Strokes Span Insert Mode',
        description='Controls span count when inserting',
        items=[
            ('BRUSH', 'Brush Size', 'Insert spans based on brush size', 0),
            ('FIXED', 'Fixed',      'Insert fixed number of spans',     1),
        ],
        default='BRUSH',
    )

    initial_cut_count: bpy.props.IntProperty(
        name='Initial Count',
        description='Number of vertices to create in a new cut',
        default=8,
        min=3,
        max=100,
    )

    def init(self, context, event):
        # self.logic = Contours_Logic(context, event)
        self.tickle(context)

    def reset(self):
        # self.logic.reset()
        pass

    def update(self, context, event):
        # print(f'updating strokes rfop {random.random()}')
        # self.logic.update(context, event, self)

        # if self.logic.mousedown:
        #     return {'RUNNING_MODAL'}

        if not event.ctrl:
            # self.logic.cleanup()
            Cursors.restore()
            self.tickle(context)
            # print(f'ending')
            return {'FINISHED'}

        Cursors.set('CROSSHAIR')
        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!

    def draw_postpixel(self, context):
        # self.logic.draw(context)
        pass


class RFTool_Strokes(RFTool_Base):
    bl_idname = "retopoflow.strokes"
    bl_label = "Strokes"
    bl_description = "Insert edge strips and extrude edges into a patch"
    bl_icon = get_path_to_blender_icon('strokes')
    bl_widget = None
    bl_operator = 'retopoflow.strokes'

    rf_brush = RFBrush_Strokes()

    bl_keymap = chain_rf_keymaps(
        RFOperator_Strokes,
        RFOperator_StrokesBrush_Adjust,
        # RFOperator_Translate_BoundaryLoop,
    )

    def draw_settings(context, layout, tool):
        layout.label(text="Spans:")
        props = tool.operator_properties(RFOperator_Strokes.bl_idname)
        layout.prop(props, 'span_insert_mode', text='')

    @classmethod
    def activate(cls, context):
        cls.reseter = Reseter()
        cls.reseter['context.tool_settings.use_mesh_automerge'] = True
        cls.reseter['context.tool_settings.snap_elements_individual'] = {'FACE_PROJECT'}

    @classmethod
    def deactivate(cls, context):
        cls.reseter.reset()
