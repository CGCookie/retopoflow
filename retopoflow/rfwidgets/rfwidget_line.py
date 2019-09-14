'''
Copyright (C) 2019 CG Cookie
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
from mathutils import Matrix, Vector

from ..rfwidget import RFWidget

from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.maths import Vec, Point, Point2D, Direction
from ...config.options import themes

class RFW_Line(RFWidget):
    rfw_name = 'Line'
    rfw_cursor = 'CROSSHAIR'

class RFWidget_Line(RFW_Line):
    @RFW_Line.on_init
    def init(self):
        self.line2D = [None, None]

    @RFW_Line.FSM_State('main')
    def modal_main(self):
        if self.actions.pressed('insert'):
            return 'line'

    @RFW_Line.FSM_State('line', 'enter')
    def model_line_enter(self):
        self.line2D = [self.actions.mouse, None]
        tag_redraw_all()

    @RFW_Line.FSM_State('line')
    def modal_line(self):
        if self.actions.released('insert'):
            self.callback_actions()
            return 'main'

        if self.actions.pressed('cancel'):
            self.line2D = [None, None]
            return 'main'

        if self.line2D[1] != self.actions.mouse:
            self.line2D[1] = self.actions.mouse
            tag_redraw_all()

    @RFW_Line.Draw('post2d')
    @RFW_Line.FSM_OnlyInState('line')
    def draw_line(self):
        # cr,cg,cb = self.color
        # p0,p1 = self.line2D
        # ctr = p0 + (p1-p0)/2

        # bgl.glEnable(bgl.GL_BLEND)
        # self.drawing.line_width(2.0)

        # self.drawing.enable_stipple()
        # bgl.glColor4f(*themes['stroke'])
        # bgl.glBegin(bgl.GL_LINE_STRIP)
        # bgl.glVertex2f(*p0)
        # bgl.glVertex2f(*p1)
        # bgl.glEnd()
        # self.drawing.disable_stipple()

        # # self.drawing.line_width(1.0)
        # bgl.glColor4f(cr, cg, cb, 0.25)
        # bgl.glBegin(bgl.GL_LINE_STRIP)
        # for px,py in self.points:
        #     x = ctr.x + px * 10
        #     y = ctr.y + py * 10
        #     bgl.glVertex2f(x, y)
        # bgl.glEnd()
        pass
