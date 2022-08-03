'''
Copyright (C) 2022 CG Cookie
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

from ...addon_common.common.fsm import FSM
from ...addon_common.common.globals import Globals
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.drawing import DrawCallbacks
from ...addon_common.common.maths import Vec, Point, Point2D, Direction, Color
from ...config.options import themes


'''
RFWidget_LineCut handles a line cut in screen space.
When cutting, a line segment is drawn from mouse down to current mouse position with a small circle at the very center
'''

class RFWidget_LineCut_Factory:
    '''
    This function is a class factory.  It is needed, because the FSM is shared across instances.
    RFTools might need to share RFWidgets that are independent of each other.
    '''

    @staticmethod
    def create(action_name, line_color=None, circle_color=Color((1,1,1,0.5)), circle_border_color=Color((0,0,0,0.5))):
        class RFWidget_LineCut(RFWidget):
            rfw_name = 'Line'
            rfw_cursor = 'CROSSHAIR'

            @RFWidget.on_init
            def init(self):
                self.action_name = action_name
                self.line2D = [None, None]
                self.line_color = line_color
                self.circle_color = circle_color
                self.circle_border_color = circle_border_color

            @FSM.on_state('main')
            def modal_main(self):
                if self.actions.pressed('insert'):
                    return 'line'

            @FSM.on_state('line', 'enter')
            def modal_line_enter(self):
                self.line2D = [self.actions.mouse, None]
                tag_redraw_all('Line line_enter')

            @FSM.on_state('line')
            def modal_line(self):
                if self.actions.released('insert'):
                    self.callback_actions(self.action_name)
                    return 'main'

                if self.actions.pressed('cancel'):
                    self.line2D = [None, None]
                    return 'main'

                if self.line2D[1] != self.actions.mouse:
                    self.line2D[1] = self.actions.mouse
                    tag_redraw_all('Line line')
                    self.callback_actioning(self.action_name)

            @FSM.on_state('line', 'exit')
            def modal_line_exit(self):
                tag_redraw_all('Line line_exit')

            @DrawCallbacks.on_draw('post2d')
            @FSM.onlyinstate('line')
            def draw_line(self):
                #cr,cg,cb,ca = self.line_color
                p0,p1 = self.line2D
                ctr = p0 + (p1-p0)/2

                bgl.glEnable(bgl.GL_BLEND)
                bgl.glEnable(bgl.GL_MULTISAMPLE)
                Globals.drawing.draw2D_line(p0, p1, self.line_color or themes['stroke'], width=2, stipple=[2, 2])  # self.line_color)
                Globals.drawing.draw2D_circle(ctr, 10, self.circle_border_color, width=3) # dark rim
                Globals.drawing.draw2D_circle(ctr, 10, self.circle_color, width=1) # light center

        return RFWidget_LineCut

