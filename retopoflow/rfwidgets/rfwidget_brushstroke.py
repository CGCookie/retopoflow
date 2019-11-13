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
from ...addon_common.common.maths import Vec, Point, Point2D, Direction, Color, Vec2D
from ...config.options import themes

class RFW_BrushStroke(RFWidget):
    rfw_name = 'Brush Stroke'
    rfw_cursor = 'CROSSHAIR'
    color_outer = Color((1.0, 1.0, 1.0, 1.0))
    color_inner = Color((1.0, 1.0, 1.0, 0.5))

class RFWidget_BrushStroke(RFW_BrushStroke):
    @RFW_BrushStroke.on_init
    def init(self):
        print('*'*50)
        print('BRUSHSTROKE INIT!')
        print('*'*50)
        self.stroke2D = []
        self.tightness = 0.95
        self.size = 40.0
        self.redraw_on_mouse = True
        self.sizing_pos = None

    @RFW_BrushStroke.FSM_State('main', 'enter')
    def modal_main_enter(self):
        self.rfw_cursor = 'CROSSHAIR'
        tag_redraw_all()

    @RFW_BrushStroke.FSM_State('main')
    def modal_main(self):
        if self.actions.pressed('insert'):
            return 'stroking'
        if self.actions.pressed('brush size'):
            return 'brush sizing'


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


    @RFW_BrushStroke.FSM_State('brush sizing', 'enter')
    def modal_brush_sizing_enter(self):
        if self.actions.mouse.x > self.actions.size.x / 2:
            self.sizing_pos = self.actions.mouse - Vec2D((self.size, 0))
        else:
            self.sizing_pos = self.actions.mouse + Vec2D((self.size, 0))
        self.rfw_cursor = 'MOVE_X'
        tag_redraw_all()

    @RFW_BrushStroke.FSM_State('brush sizing')
    def modal_brush_sizing(self):
        if self.actions.pressed('confirm'):
            self.size = (self.sizing_pos - self.actions.mouse).length
            return 'main'
        if self.actions.pressed('cancel'):
            return 'main'


    @RFW_BrushStroke.Draw('post3d')
    @RFW_BrushStroke.FSM_OnlyInState({'main','stroking'})
    def draw_brush(self):
        xy = self.rfcontext.actions.mouse
        p,n,_,_ = self.rfcontext.raycast_sources_mouse()
        if not p: return
        depth = self.rfcontext.Point_to_depth(p)
        if not depth: return
        self.scale = self.rfcontext.size2D_to_size(1.0, xy, depth)

        bgl.glDepthRange(0.0, 0.99995)
        Globals.drawing.draw3D_circle(p, self.size*self.scale*1.0, self.color_outer, n=n, width=2*self.scale)
        Globals.drawing.draw3D_circle(p, self.size*self.scale*0.5, self.color_inner, n=n, width=2*self.scale)
        bgl.glDepthRange(0.0, 1.0)

    @RFW_BrushStroke.Draw('post2d')
    @RFW_BrushStroke.FSM_OnlyInState('stroking')
    def draw_line(self):
        # draw brush strokes (screen space)
        #cr,cg,cb,ca = self.line_color
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        Globals.drawing.draw2D_linestrip(self.stroke2D, themes['stroke'], width=2, stipple=[5, 5])

    @RFW_BrushStroke.Draw('post2d')
    @RFW_BrushStroke.FSM_OnlyInState('brush sizing')
    def draw_brush_sizing(self):
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        r = (self.sizing_pos - self.actions.mouse).length
        Globals.drawing.draw2D_circle(self.sizing_pos, r*1.0, self.color_outer, width=1)
        Globals.drawing.draw2D_circle(self.sizing_pos, r*0.5, self.color_inner, width=1)

