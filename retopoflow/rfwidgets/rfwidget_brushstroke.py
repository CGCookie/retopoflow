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
import random
from mathutils import Matrix, Vector

from ..rfwidget import RFWidget

from ...addon_common.common.globals import Globals
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.maths import Vec, Point, Point2D, Direction, Color
from ...config.options import themes

class RFW_BrushStroke(RFWidget):
    rfw_name = 'Brush Stroke'
    rfw_cursor = 'CROSSHAIR'
    line_color = Color.white

class RFWidget_BrushStroke(RFW_BrushStroke):
    @RFW_BrushStroke.on_init
    def init(self):
        self.stroke2D = []
        self.tightness = 0.95
        self.size = 20.0

    @RFW_BrushStroke.FSM_State('main')
    def modal_main(self):
        if self.actions.pressed('insert'):
            return 'stroking'

    @RFW_BrushStroke.FSM_State('stroking', 'enter')
    def modal_line_enter(self):
        self.stroke2D = [self.actions.mouse]
        tag_redraw_all()

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
        tag_redraw_all()

    @RFW_BrushStroke.FSM_State('stroking', 'exit')
    def modal_line_exit(self):
        tag_redraw_all()

    @RFW_BrushStroke.Draw('post2d')
    @RFW_BrushStroke.FSM_OnlyInState('stroking')
    def draw_line(self):
        #cr,cg,cb,ca = self.line_color
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        Globals.drawing.draw2D_linestrip(self.stroke2D, themes['stroke'], width=2, stipple=[5, 5])  # self.line_color)
