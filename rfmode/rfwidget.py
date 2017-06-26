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
from ..common.maths import Vec, Point, Point2D

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
    def clear(cls):
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
        cls.radius = 50.0
        cls.strength = 1.5
        cls.draw_mode = 'view'
    
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
        cls.s = cls.rfcontext.size2D_to_size(1.0, xy, cls.rfcontext.Point_to_depth(p))
        cls.x = Vec(rmat * Vector((1,0,0)))
        cls.y = Vec(rmat * Vector((0,1,0)))
        cls.hit = True
    
    @classmethod
    def clear(cls):
        cls.hit = False
    
    @classmethod
    def mouse_cursor(cls):
        if cls.draw_mode == 'view':
             return 'NONE' if cls.hit else 'CROSSHAIR'
        return 'MOVE_X'
    
    @classmethod
    def get_scaled_radius(cls):
        return cls.s * cls.radius
    
    @classmethod
    def get_strength_dist(cls, dist:float):
        return 1.0 - math.pow(dist / cls.get_scaled_radius(), cls.strength)
    
    @classmethod
    def get_strength_Point(cls, point:Point):
        return self.get_strength_dist((point - cls.p).length)
    
    @classmethod
    def draw_postview(cls):
        if cls.draw_mode != 'view': return
        if not cls.hit: return
        cx,cy,cp = cls.x,cls.y,cls.p
        cs_outer = cls.s * cls.radius
        cs_inner = cls.s * cls.radius * math.pow(0.5, 1.0 / cls.strength)
        
        bgl.glDepthRange(0, 0.999)      # squeeze depth just a bit 
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glLineWidth(2.0)
        bgl.glPointSize(3.0)
        
        ######################################
        # draw in front of geometry
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
        
        bgl.glColor4f(1, 1, 1, 1)       # outer ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in cls.points:
            p = (cs_outer * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()
        
        bgl.glColor4f(1, 1, 1, 0.5)     # inner ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in cls.points:
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
        
        bgl.glColor4f(1, 1, 1, 0.05)    # outer ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in cls.points:
            p = (cs_outer * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()
        
        bgl.glColor4f(1, 1, 1, 0.025)   # inner ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in cls.points:
            p = (cs_inner * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()
        
        ######################################
        # reset to defaults
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_TRUE)
        
        bgl.glDepthRange(0, 1)
    
    @classmethod
    def draw_postpixel(cls):
        if cls.draw_mode != 'pixel': return
        
        w,h = cls.rfcontext.eventd.width,cls.rfcontext.eventd.height
        
        cx,cy,cp = Vector((1,0)),Vector((0,1)),Vector((w/2,h/2))
        cs_outer = cls.radius
        cs_inner = cls.radius * math.pow(0.5, 1.0 / cls.strength)
        
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glLineWidth(2.0)
        
        bgl.glColor4f(1, 1, 1, 1)                       # outer ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in cls.points:
            p = (cs_outer * ((cx * x) + (cy * y))) + cp
            bgl.glVertex2f(*p)
        bgl.glEnd()
        
        bgl.glColor4f(1, 1, 1, 0.5)                     # inner ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in cls.points:
            p = (cs_inner * ((cx * x) + (cy * y))) + cp
            bgl.glVertex2f(*p)
        bgl.glEnd()
    
    @classmethod
    def cursor_warp(cls, xy:Point2D):
        eventd = cls.rfcontext.eventd
        x,y = eventd.region.x,eventd.region.y
        mx,my = xy
        eventd.context.window.cursor_warp(x + mx, y + my)
        eventd.mouse = xy
    
    @classmethod
    def modal_resize(cls, ret_mode):
        eventd = cls.rfcontext.eventd
        w,h = eventd.width,eventd.height
        center = Point2D((w/2, h/2))
        
        if cls.draw_mode == 'view':
            # first time
            cls.mousepre = Point2D(eventd.mouse)
            cls.cursor_warp(Point2D((w/2 + cls.radius, h/2)))
            cls.draw_mode = 'pixel'
            return ''
        
        if eventd.press == 'LEFTMOUSE':
            cls.draw_mode = 'view'
            cls.cursor_warp(cls.mousepre)
            return ret_mode
        
        cls.radius = (center - eventd.mouse).length
        return ''
        
    @classmethod
    def modal_restrength(cls, ret_mode):
        eventd = cls.rfcontext.eventd
        w,h = eventd.width,eventd.height
        center = Point2D((w/2, h/2))
        
        if cls.draw_mode == 'view':
            # first time
            cls.mousepre = Point2D(eventd.mouse)
            cls.cursor_warp(Point2D((w/2 + cls.radius * math.pow(0.5, 1.0 / cls.strength), h/2)))
            cls.draw_mode = 'pixel'
            return ''
        
        if eventd.press == 'LEFTMOUSE':
            cls.draw_mode = 'view'
            cls.cursor_warp(cls.mousepre)
            return ret_mode
        
        dist = (center - eventd.mouse).length
        ratio = max(0.0001, min(0.9999, dist / cls.radius))
        
        cls.strength = math.log(0.5) / math.log(ratio)
        return ''
        