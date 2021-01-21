'''
Copyright (C) 2021 CG Cookie
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
import bgl
import random
from mathutils import Matrix, Vector

from ..rfwidget import RFWidget

from ...addon_common.common.globals import Globals
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat
from ...addon_common.common.maths import Vec, Point, Point2D, Direction, Color, Vec2D
from ...config.options import themes


class RFWidget_BrushStroke_Factory:
    '''
    This is a class factory.  It is needed, because the FSM is shared across instances.
    RFTools might need to share RFWidges that are independent of each other.
    '''

    @staticmethod
    def create(radius, outer_border_color=Color((0,0,0,0.5)), outer_color=Color((1,1,1,1)), inner_color=Color((1,1,1,0.5))):

        class RFW_BrushStroke(RFWidget):
            rfw_name = 'Brush Stroke'
            rfw_cursor = 'CROSSHAIR'

        class RFWidget_BrushStroke(RFW_BrushStroke):
            @RFW_BrushStroke.on_init
            def init(self):
                self.stroke2D = []
                self.tightness = 0.95
                self.redraw_on_mouse = True
                self.sizing_pos = None
                self.outer_border_color = outer_border_color
                self.outer_color = outer_color
                self.inner_color = inner_color

            @RFW_BrushStroke.FSM_State('main', 'enter')
            def modal_main_enter(self):
                self.rfw_cursor = 'CROSSHAIR'
                tag_redraw_all('BrushStroke_PolyStrips main_enter')

            @RFW_BrushStroke.FSM_State('main')
            def modal_main(self):
                if self.actions.pressed('insert'):
                    return 'stroking'
                if self.actions.pressed('brush radius'):
                    return 'brush sizing'

            def inactive_passthrough(self):
                if self.actions.pressed('brush radius'):
                    self._fsm.force_set_state('brush sizing')
                    return True

            @RFW_BrushStroke.FSM_State('stroking', 'enter')
            def modal_line_enter(self):
                self.stroke2D = [self.actions.mouse]
                tag_redraw_all('BrushStroke_PolyStrips line_enter')

            @RFW_BrushStroke.FSM_State('stroking')
            def modal_line(self):
                if self.actions.released('insert'):
                    # TODO: tessellate the last steps?
                    self.stroke2D.append(self.actions.mouse)
                    self.callback_actions()
                    return 'main'

                if self.actions.pressed('cancel'):
                    self.stroke2D = []
                    return 'main'

                lpos, cpos = self.stroke2D[-1], self.actions.mouse
                npos = lpos + (cpos - lpos) * (1 - self.tightness)
                self.stroke2D.append(npos)
                tag_redraw_all('BrushStroke_PolyStrips line')
                self.callback_actioning()

            @RFW_BrushStroke.FSM_State('stroking', 'exit')
            def modal_line_exit(self):
                tag_redraw_all('BrushStroke_PolyStrips line_exit')

            @RFW_BrushStroke.FSM_State('brush sizing', 'enter')
            def modal_brush_sizing_enter(self):
                if self.actions.mouse.x > self.actions.size.x / 2:
                    self.sizing_pos = self.actions.mouse - Vec2D((self.radius, 0))
                else:
                    self.sizing_pos = self.actions.mouse + Vec2D((self.radius, 0))
                self.rfw_cursor = 'MOVE_X'
                tag_redraw_all('BrushStroke_PolyStrips brush_sizing_enter')

            @RFW_BrushStroke.FSM_State('brush sizing')
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

            @RFW_BrushStroke.Draw('post3d')
            @RFW_BrushStroke.FSM_OnlyInState({'main','stroking'})
            def draw_brush(self):
                xy = self.rfcontext.actions.mouse
                p,n,_,_ = self.rfcontext.raycast_sources_mouse()
                if not p: return
                depth = self.rfcontext.Point_to_depth(p)
                if not depth: return
                self.scale = self.rfcontext.size2D_to_size(1.0, xy, depth)

                bgl.glDepthRange(0.0, 0.99996)
                Globals.drawing.draw3D_circle(p, (self.radius-3)*self.scale*1.0, self.outer_border_color, n=n, width=8*self.scale)
                bgl.glDepthRange(0.0, 0.99995)
                Globals.drawing.draw3D_circle(p, self.radius*self.scale*1.0, self.outer_color, n=n, width=2*self.scale)
                Globals.drawing.draw3D_circle(p, self.radius*self.scale*0.5, self.inner_color, n=n, width=2*self.scale)
                bgl.glDepthRange(0.0, 1.0)

            @RFW_BrushStroke.Draw('post2d')
            @RFW_BrushStroke.FSM_OnlyInState('stroking')
            def draw_line(self):
                # draw brush strokes (screen space)
                #cr,cg,cb,ca = self.line_color
                bgl.glEnable(bgl.GL_BLEND)
                # bgl.glEnable(bgl.GL_MULTISAMPLE)
                Globals.drawing.draw2D_linestrip(self.stroke2D, themes['stroke'], width=2, stipple=[5, 5])

            @RFW_BrushStroke.Draw('post2d')
            @RFW_BrushStroke.FSM_OnlyInState('brush sizing')
            def draw_brush_sizing(self):
                bgl.glEnable(bgl.GL_BLEND)
                # bgl.glEnable(bgl.GL_MULTISAMPLE)
                r = (self.sizing_pos - self.actions.mouse).length

                # Globals.drawing.draw2D_circle(self.sizing_pos, r*0.75, self.fill_color, width=r*0.5)
                Globals.drawing.draw2D_circle(self.sizing_pos, r*1.0, self.outer_border_color, width=7)
                Globals.drawing.draw2D_circle(self.sizing_pos, r*1.0, self.outer_color, width=1)
                Globals.drawing.draw2D_circle(self.sizing_pos, r*0.5, self.inner_color, width=1)

        return RFWidget_BrushStroke
