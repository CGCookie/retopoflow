'''
Copyright (C) 2017 Taylor University, CG Cookie

Created by Dr. Jon Denning and Spring 2015 COS 424 class

Some code copied from CG Cookie Retopoflow project
https://github.com/CGCookie/retopoflow

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
from ..common.maths import Vec

from ..common.registerclasses import RegisterClasses



class RFWidget(metaclass=RegisterClasses):
    @staticmethod
    def init_widgets(rfcontext):
        class_methods = ['init', 'mouse_cursor']
        RFWidget.rfcontext = rfcontext
        for cwidget in RFWidget:
            cwidget.init()
    
    def __init__(self, rfcontext):
        assert False, "do not instantiate RFWidget"
    
    @classmethod
    def init(cls):
        ''' Called when RetopoFlow is started, but not necessarily when the cursor is used '''
        pass
    
    @classmethod
    def update(cls):
        pass
    
    @classmethod
    def mouse_cursor(cls):
        # DEFAULT, NONE, WAIT, CROSSHAIR, MOVE_X, MOVE_Y, KNIFE, TEXT, PAINT_BRUSH, HAND, SCROLL_X, SCROLL_Y, SCROLL_XY, EYEDROPPER
        return 'DEFAULT'
    
    @classmethod
    def draw_postview(cls):
        pass
    
    @classmethod
    def draw_postpixel(cls):
        pass



class RFWidgetDefault(RFWidget):
    @classmethod
    def mouse_cursor(cls):
        return 'CROSSHAIR'


class RFWidgetCircle(RFWidget):
    @classmethod
    def init(cls):
        cls.hit = False
        cls.points = [(math.cos(r*math.pi/180.0),math.sin(r*math.pi/180.0)) for r in range(0,361,10)]
    
    @classmethod
    def update(cls):
        p,n,_,_ = cls.rfcontext.raycast_sources_mouse()
        if p is None or n is None:
            cls.hit = False
            return
        xy = cls.rfcontext.eventd.mouse
        z = Vector((0,0,1))
        n = Vector(n)
        rmat = Matrix.Rotation(z.angle(n), 4, z.cross(n).normalized())
        cls.p = p
        cls.s = cls.rfcontext.size2D_to_size(50, xy, cls.rfcontext.Point_to_depth(p))
        cls.x = Vec(rmat * Vector((1,0,0)))
        cls.y = Vec(rmat * Vector((0,1,0)))
        cls.hit = True
    
    @classmethod
    def mouse_cursor(cls):
        return 'NONE' if cls.hit else 'CROSSHAIR'
    
    @classmethod
    def draw_postview(cls):
        if not cls.hit: return
        cs,cx,cy,cp = cls.s,cls.x,cls.y,cls.p
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_FALSE)
        
        bgl.glColor4f(1, 1, 1, 1)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in cls.points:
            p = (cs * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()
        
        bgl.glColor4f(1, 1, 1, 0.5)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in cls.points:
            p = (0.1 * cs * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()
        
        bgl.glDepthFunc(bgl.GL_GREATER)
        bgl.glDepthMask(bgl.GL_FALSE)
        
        bgl.glColor4f(1, 1, 1, 0.05)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in cls.points:
            p = (cs * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()
        
        bgl.glColor4f(1, 1, 1, 0.025)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in cls.points:
            p = (0.1 * cs * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_TRUE)
    
    @classmethod
    def draw_postpixel(cls):
        pass