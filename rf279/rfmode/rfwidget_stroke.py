'''
Copyright (C) 2017 CG Cookie
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
from ..common.maths import Vec, Point, Point2D, Direction
from ..common.shaders import brushStrokeShader
from ..options import themes

class RFWidget_Stroke:
    def stroke_modal_main(self):
        if self.rfcontext.actions.pressed('insert'):
            self.stroke2D.clear()
            self.stroke2D_left.clear()
            self.stroke2D_right.clear()
            return 'stroke'

    def modal_stroke(self):
        actions = self.rfcontext.actions

        if actions.released('insert'):
            if not self.stroke2D: return 'main'
            # continue stroke to current mouse location
            p,m = self.stroke2D[-1],actions.mouse
            v = m - p
            l = v.length
            steps = 1 + math.ceil(l*2)
            d = v / steps
            for i in range(1, int(steps)+1): self.stroke2D.append(p + d * i)
            if self.stroke_callback: self.stroke_callback()
            return 'main'

        if actions.pressed('cancel'):
            self.stroke2D.clear()
            return 'main'

        if False:
            self.stroke2D.append(actions.mouse)
            if len(self.stroke2D) > 5:
                delta = actions.mouse - self.stroke2D[-5]
                if abs(delta.x) > 2 or abs(delta.y) > 2:
                    delta = delta.normalized() * self.get_scaled_radius()
                    ortho = Vec2D((-delta.y, delta.x))
                    self.stroke2D_left.append(actions.mouse + ortho)
                    self.stroke2D_right.append(actions.mouse - ortho)

        if not self.stroke2D:
            self.stroke2D.append(actions.mouse)
        else:
            lstpos,curpos = self.stroke2D[-1],actions.mouse
            diff = curpos - lstpos
            newpos = lstpos + diff * (1 - self.tightness)
            self.stroke2D.append(newpos)

    def stroke_mouse_cursor(self):
        if self.mode in {'main','stroke'}:
             return 'NONE' if self.hit else 'CROSSHAIR'
        return 'MOVE_X'

    def stroke_postview(self):
        if self.mode not in {'main','stroke'}: return
        if not self.hit: return
        cx,cy,cp = self.hit_x,self.hit_y,self.hit_p
        cs_outer = self.scale * 20
        cs_inner = self.scale * 20 * 0.5
        cr,cg,cb = self.color

        bgl.glDepthRange(0, 0.999)      # squeeze depth just a bit
        bgl.glEnable(bgl.GL_BLEND)
        self.drawing.line_width(2.0)
        self.drawing.point_size(3.0)

        ######################################
        # draw in front of geometry

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth

        bgl.glColor4f(cr, cg, cb, 1.0)       # outer ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in self.points:
            p = (cs_outer * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()

        bgl.glColor4f(cr, cg, cb, 0.1)     # inner ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in self.points:
            p = (cs_inner * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()

        bgl.glColor4f(1, 1, 1, 0.25)    # center point
        bgl.glBegin(bgl.GL_POINTS)
        bgl.glVertex3f(*cp)
        bgl.glEnd()

        ######################################
        # draw behind geometry (hidden below)

        bgl.glDepthFunc(bgl.GL_GREATER)
        bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth

        bgl.glColor4f(cr, cg, cb, 0.05)    # outer ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in self.points:
            p = (cs_outer * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()

        bgl.glColor4f(cr, cg, cb, 0.01)   # inner ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in self.points:
            p = (cs_inner * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()

        ######################################
        # reset to defaults

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_TRUE)

        bgl.glDepthRange(0, 1)

    def stroke_postpixel(self):
        w,h = self.rfcontext.actions.size

        bgl.glEnable(bgl.GL_BLEND)

        if self.mode == 'main':
            return

        if self.mode == 'stroke':
            brushStrokeShader.enable()
            brushStrokeShader['uMVPMatrix'] = self.drawing.get_pixel_matrix_buffer()
            self.drawing.line_width(2.0)
            #self.drawing.enable_stipple()
            #bgl.glColor4f(*themes['stroke'])
            brushStrokeShader['vColor'] = themes['stroke']
            bgl.glBegin(bgl.GL_LINE_STRIP)
            d = 0
            px,py = None,None
            for x,y in self.stroke2D:
                brushStrokeShader['vDistAccum'] = d
                bgl.glVertex2f(x,y)
                if px is not None:
                    d += math.sqrt((px-x)**2+(py-y)**2)
                px,py = x,y
            bgl.glEnd()
            brushStrokeShader.disable()
            return

