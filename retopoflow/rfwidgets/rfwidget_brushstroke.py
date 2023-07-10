'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

import math
import random
from mathutils import Matrix, Vector

from ..rfwidget import RFWidget

from ...addon_common.common.fsm import FSM
from ...addon_common.common.globals import Globals
from ...addon_common.common import gpustate
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.drawing import DrawCallbacks
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat
from ...addon_common.common.maths import Vec, Point, Point2D, Direction, Color, Vec2D
from ...config.options import themes


class RFWidget_BrushStroke_Factory:
    '''
    This is a class factory.  It is needed, because the FSM is shared across instances.
    RFTools might need to share RFWidgets that are independent of each other.
    '''

    @staticmethod
    def create(action_name, radius, outer_border_color=Color((0,0,0,0.5)), outer_color=Color((1,1,1,1)), inner_color=Color((1,1,1,0.5)), below_alpha=Color((1,1,1,0.25))):
        class RFWidget_BrushStroke(RFWidget):
            rfw_name = 'Brush Stroke'
            rfw_cursor = 'CROSSHAIR'

            @RFWidget.on_init
            def init(self):
                self.action_name = action_name
                self.stroke2D = []
                self.tightness = 0.95
                self.redraw_on_mouse = True
                self.sizing_pos = None
                self.outer_border_color = outer_border_color
                self.outer_color = outer_color
                self.inner_color = inner_color
                self.color_mult_below = below_alpha
                self.last_mouse = None
                self.last_view = None
                self.hit = False
                self.hit_scale = 1.0

            @FSM.on_state('main', 'enter')
            def modal_main_enter(self):
                self.rfw_cursor = 'CROSSHAIR'
                tag_redraw_all('BrushStroke main_enter')

            @FSM.on_state('main')
            def modal_main(self):
                self.update_mouse()

                if self.actions.pressed('insert'):
                    return 'stroking'

                if self.rfcontext.actions.pressed('brush radius increase'):
                    self.radius += 10
                    tag_redraw_all('BrushStroke increase radius')
                    return
                if self.rfcontext.actions.pressed('brush radius decrease'):
                    self.radius -= 10
                    tag_redraw_all('BrushStroke decrease radius')
                    return

                if self.actions.pressed('brush radius'):
                    return 'brush sizing'

            def inactive_passthrough(self):
                if self.actions.pressed('brush radius'):
                    self._fsm.force_set_state('brush sizing')
                    return True

            @FSM.on_state('stroking', 'enter')
            def modal_line_enter(self):
                self.stroke2D = [self.actions.mouse]
                tag_redraw_all('BrushStroke line_enter')

            @FSM.on_state('stroking')
            def modal_line(self):
                self.update_mouse()

                if self.actions.released('insert'):
                    # TODO: tessellate the last steps?
                    self.stroke2D.append(self.actions.mouse)
                    self.callback_actions(self.action_name)
                    return 'main'

                if self.actions.pressed('cancel'):
                    self.stroke2D = []
                    self.actions.unuse('insert', ignoremods=True, ignoremulti=True)
                    return 'main'

                lpos, cpos = self.stroke2D[-1], self.actions.mouse
                npos = lpos + (cpos - lpos) * (1 - self.tightness)
                self.stroke2D.append(npos)
                tag_redraw_all('BrushStroke line')
                self.callback_actioning(self.action_name)

            @FSM.on_state('stroking', 'exit')
            def modal_line_exit(self):
                tag_redraw_all('BrushStroke line_exit')

            @FSM.on_state('brush sizing', 'enter')
            def modal_brush_sizing_enter(self):
                if self.actions.mouse.x > self.actions.size.x / 2:
                    self.sizing_pos = self.actions.mouse - Vec2D((self.radius, 0))
                else:
                    self.sizing_pos = self.actions.mouse + Vec2D((self.radius, 0))
                self.rfw_cursor = 'MOVE_X'
                tag_redraw_all('BrushStroke brush_sizing_enter')

            @FSM.on_state('brush sizing')
            def modal_brush_sizing(self):
                if self.actions.pressed('confirm'):
                    self.radius = (self.sizing_pos - self.actions.mouse).length
                    return 'main'
                if self.actions.pressed('cancel'):
                    return 'main'


            ###################
            # radius

            @property
            def radius(self):
                return radius.get()
            @radius.setter
            def radius(self, v):
                radius.set(max(1, float(v)))

            def get_radius_boundvar(self):
                return radius


            ###################
            # draw functions

            @DrawCallbacks.on_draw('post3d')
            @FSM.onlyinstate({'main','stroking'})
            def draw_brush(self):
                if not self.hit: return

                p, n = self.hit_p, self.hit_n
                ro = self.radius * self.hit_scale
                rh = ro * 0.5
                co, ci, cb = self.outer_color, self.inner_color, self.outer_border_color

                gpustate.depth_mask(False)

                fwd = Direction(self.rfcontext.Vec_forward()) * (self.hit_depth * 0.0005)

                # draw below
                gpustate.depth_test('GREATER_EQUAL')
                Globals.drawing.draw3D_circle(p - fwd * 1.0, ro, cb * self.color_mult_below, n=n, width=8*self.hit_scale)
                Globals.drawing.draw3D_circle(p - fwd * 2.0, ro, co * self.color_mult_below, n=n, width=2*self.hit_scale)
                Globals.drawing.draw3D_circle(p - fwd * 2.0, rh, ci * self.color_mult_below, n=n, width=2*self.hit_scale)

                # draw above
                gpustate.depth_test('LESS_EQUAL')
                Globals.drawing.draw3D_circle(p - fwd * 1.0, ro, cb, n=n, width=8*self.hit_scale)
                Globals.drawing.draw3D_circle(p - fwd * 2.0, ro, co, n=n, width=2*self.hit_scale)
                Globals.drawing.draw3D_circle(p - fwd * 2.0, rh, ci, n=n, width=2*self.hit_scale)

                # reset
                gpustate.depth_test('LESS_EQUAL')
                gpustate.depth_mask(True)

            @DrawCallbacks.on_draw('post2d')
            @FSM.onlyinstate('stroking')
            def draw_line(self):
                # draw brush strokes (screen space)
                #cr,cg,cb,ca = self.line_color
                gpustate.blend('ALPHA')
                Globals.drawing.draw2D_linestrip(self.stroke2D, themes['stroke'], width=2, stipple=[5, 5])

            @DrawCallbacks.on_draw('post2d')
            @FSM.onlyinstate('brush sizing')
            def draw_brush_sizing(self):
                gpustate.blend('ALPHA')
                r = (self.sizing_pos - self.actions.mouse).length

                # Globals.drawing.draw2D_circle(self.sizing_pos, r*0.75, self.fill_color, width=r*0.5)
                Globals.drawing.draw2D_circle(self.sizing_pos, r*1.0, self.outer_border_color, width=7)
                Globals.drawing.draw2D_circle(self.sizing_pos, r*1.0, self.outer_color, width=1)
                Globals.drawing.draw2D_circle(self.sizing_pos, r*0.5, self.inner_color, width=1)

            ##################
            # mouse

            def update_mouse(self):
                recompute = False
                recompute |= (self.last_mouse != self.actions.mouse)
                recompute |= (self.last_view  != self.rfcontext.get_view_version())
                if not recompute: return
                self.last_mouse = self.actions.mouse
                self.last_view  = self.rfcontext.get_view_version()

                self.hit = False

                xy = self.rfcontext.actions.mouse
                p,n,_,_ = self.rfcontext.raycast_sources_mouse()
                if not p: return
                depth = self.rfcontext.Point_to_depth(p)
                if not depth: return
                scale = self.rfcontext.size2D_to_size(1.0, depth)
                if scale is None: return

                self.hit = True
                self.hit_scale = scale
                self.hit_p = p
                self.hit_n = n
                self.hit_depth = depth

        return RFWidget_BrushStroke
