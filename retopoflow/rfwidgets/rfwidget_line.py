'''
Copyright (C) 2020 CG Cookie
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
from ...addon_common.common.maths import Vec, Point, Point2D, Direction, Color
from ...config.options import themes

class RFW_Line_Common:
    pass


class RFW_Line_Contours(RFWidget, RFW_Line_Common):
    rfw_name = 'Line'
    rfw_cursor = 'CROSSHAIR'
    line_color = Color.white

class RFWidget_Line_Contours(RFW_Line_Contours):
    @RFW_Line_Contours.on_init
    def init(self):
        self.line2D = [None, None]

    @RFW_Line_Contours.FSM_State('main')
    def modal_main(self):
        if self.actions.pressed('insert'):
            return 'line'

    @RFW_Line_Contours.FSM_State('line', 'enter')
    def modal_line_enter(self):
        self.line2D = [self.actions.mouse, None]
        tag_redraw_all('Line line_enter')

    @RFW_Line_Contours.FSM_State('line')
    def modal_line(self):
        if self.actions.released('insert'):
            print('INSERT')
            self.callback_actions()
            return 'main'

        if self.actions.pressed('cancel'):
            self.line2D = [None, None]
            return 'main'

        if self.line2D[1] != self.actions.mouse:
            self.line2D[1] = self.actions.mouse
            tag_redraw_all('Line line')

    @RFW_Line_Contours.FSM_State('line', 'exit')
    def modal_line_exit(self):
        tag_redraw_all('Line line_exit')

    @RFW_Line_Contours.Draw('post2d')
    @RFW_Line_Contours.FSM_OnlyInState('line')
    def draw_line(self):
        #cr,cg,cb,ca = self.line_color
        p0,p1 = self.line2D
        ctr = p0 + (p1-p0)/2

        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        Globals.drawing.draw2D_line(p0, p1, themes['stroke'], width=2, stipple=[2, 2])  # self.line_color)
        Globals.drawing.draw2D_circle(ctr, 10, (0,0,0,0.5), width=3)
        Globals.drawing.draw2D_circle(ctr, 10, (1,1,1,0.5), width=1)


class RFW_Line_Loops(RFWidget, RFW_Line_Common):
    rfw_name = 'Line'
    rfw_cursor = 'CROSSHAIR'
    line_color = Color.white

class RFWidget_Line_Loops(RFW_Line_Loops):
    @RFW_Line_Loops.on_init
    def init(self):
        self.line2D = [None, None]

    @RFW_Line_Loops.FSM_State('main')
    def modal_main(self):
        if self.actions.pressed('insert'):
            return 'line'

    @RFW_Line_Loops.FSM_State('line', 'enter')
    def modal_line_enter(self):
        self.line2D = [self.actions.mouse, None]
        tag_redraw_all('Line line_enter')

    @RFW_Line_Loops.FSM_State('line')
    def modal_line(self):
        if self.actions.released('insert'):
            print('INSERT')
            self.callback_actions()
            return 'main'

        if self.actions.pressed('cancel'):
            self.line2D = [None, None]
            return 'main'

        if self.line2D[1] != self.actions.mouse:
            self.line2D[1] = self.actions.mouse
            tag_redraw_all('Line line')

    @RFW_Line_Loops.FSM_State('line', 'exit')
    def modal_line_exit(self):
        tag_redraw_all('Line line_exit')

    @RFW_Line_Loops.Draw('post2d')
    @RFW_Line_Loops.FSM_OnlyInState('line')
    def draw_line(self):
        #cr,cg,cb,ca = self.line_color
        p0,p1 = self.line2D
        ctr = p0 + (p1-p0)/2

        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        Globals.drawing.draw2D_line(p0, p1, themes['stroke'], width=2, stipple=[2, 2])  # self.line_color)
        Globals.drawing.draw2D_circle(ctr, 10, (0,0,0,0.5), width=3)
        Globals.drawing.draw2D_circle(ctr, 10, (1,1,1,0.5), width=1)
