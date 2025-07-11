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
from ..common.maths import view_forward_direction, lerp
from ..common.operator import (
    invoke_operator, execute_operator,
    RFOperator, RFRegisterClass,
    chain_rf_keymaps, wrap_property,
)
from ..common.raycast import (
    raycast_valid_sources, raycast_point_valid_sources, mouse_from_event, nearest_point_valid_sources,
    plane_normal_from_points,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common import gpustate
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.maths import Color, Frame, clamp, Direction, Vec, Point, Point2D, Vec2D, Plane
from ...addon_common.common.timerhandler import TimerHandler
import time


class RFBrush_Cut(RFBrush_Base):
    # brush visualization settings
    hit_line_color    = Color.from_ints(255, 255,  0, 255)
    hit_circle_color  = Color.from_ints(255, 255, 255, 255)
    miss_line_color   = Color.from_ints(192,  30,  30, 128)
    miss_circle_color = Color.from_ints(255,  40,  40, 255)

    stipple_mult = Color((1,1,1,0))

    # hack to know which areas the mouse is in
    mouse_areas = set()  # TODO: make sure this actually works with multiple areas / quad

    def init(self):
        self.operator = None
        self.reset()
        self.shift_held = False

    def set_operator(self, operator):
        # this is called whenever operator using brush is started
        # note: artist just used another operator, so the data likely changed.
        #       reset nearest info so that we can rebuild structure!
        self.operator = operator
        self.reset()

    def reset(self):
        self.mousedown = None
        self.mousemiddle = None
        self.mouse = None
        self.hit = None
        self.is_cancelled = False

    def is_stroking(self):
        return self.operator and self.operator.is_active() and self.mousedown is not None

    def update(self, context, event):
        if not self.RFCore.is_current_area(context):
            self.reset()
            return

        if event.shift != self.shift_held:
            self.shift_held = event.shift
            context.area.tag_redraw()
        if self.shift_held: return {'PASS_THROUGH'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self.reset()
            self.is_cancelled = True
            context.area.tag_redraw()
            return

        self.mouse = Vector(mouse_from_event(event))

        if self.operator and self.operator.is_active():
            if event.type == 'LEFTMOUSE':
                if event.value == 'PRESS':
                    self.mousedown = self.mouse
                elif event.value == 'RELEASE' and self.is_stroking():
                    if self.hit and (self.mouse - self.mousedown).length > 0:
                        plane = Plane(self.hit['co_world'], plane_normal_from_points(context, self.mousedown, self.mouse))
                        self.operator.process_cut(context, self.hit, plane, self.mousedown, self.mouse)
                    self.reset()
                context.area.tag_redraw()

            if event.type == 'MOUSEMOVE' and self.is_stroking():
                self.mousemiddle = Point2D.average((self.mouse, self.mousedown))
                self.hit = raycast_valid_sources(context, self.mousemiddle)
                context.area.tag_redraw()

    def draw_postpixel(self, context):
        if not self.RFCore.is_current_area(context): return
        #if context.area not in self.mouse_areas: return
        if self.shift_held: return

        gpustate.blend('ALPHA')

        if not self.mousedown: return
        p0 = self.mousedown
        p1 = self.mouse
        pm = Point2D.average((p0, p1))
        d01 = (p1 - p0).normalized() * Drawing.scale(8)

        with Drawing.draw(context, CC_2D_LINES) as draw:
            draw.line_width(2)
            if self.hit:
                draw.color(RFBrush_Cut.hit_line_color)
                draw.stipple(pattern=[5,5], offset=0, color=RFBrush_Cut.hit_line_color * RFBrush_Cut.stipple_mult)
            else:
                draw.color(RFBrush_Cut.miss_line_color)
                draw.stipple(pattern=[5,5], offset=0, color=RFBrush_Cut.miss_line_color * RFBrush_Cut.stipple_mult)
            draw.vertex(pm-d01).vertex(p0)
            draw.vertex(pm+d01).vertex(p1)

        with Drawing.draw(context, CC_2D_POINTS) as draw:
            draw.point_size(8)
            draw.color(RFBrush_Cut.hit_circle_color if self.hit else RFBrush_Cut.miss_circle_color)
            draw.vertex(pm)

            draw.vertex(self.operator.v_to_point(-1, self.mousedown, self.mouse))
            draw.vertex(self.operator.v_to_point(+1, self.mousedown, self.mouse))