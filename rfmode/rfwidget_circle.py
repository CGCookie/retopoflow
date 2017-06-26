import math
import bgl
from mathutils import Matrix, Vector
from ..common.maths import Vec, Point, Point2D

from .rfwidget import RFWidget

class RFWidget_Circle(RFWidget):
    def __init__(self):
        self.points = [(math.cos(r*math.pi/180.0),math.sin(r*math.pi/180.0)) for r in range(0,361,10)]
        self.hit = False
        self.radius = 50.0
        self.strength = 1.5
        self.draw_mode = 'view'
    
    def update(self):
        p,n,_,_ = self.rfcontext.raycast_sources_mouse()
        if p is None or n is None:
            self.hit = False
            return
        xy = self.rfcontext.eventd.mouse
        z = Vector((0,0,1))
        n = Vector(n)
        rmat = Matrix.Rotation(z.angle(n), 4, z.cross(n).normalized())
        self.p = p
        self.s = self.rfcontext.size2D_to_size(1.0, xy, self.rfcontext.Point_to_depth(p))
        self.x = Vec(rmat * Vector((1,0,0)))
        self.y = Vec(rmat * Vector((0,1,0)))
        self.hit = True
    
    def clear(self):
        self.hit = False
    
    def mouse_cursor(self):
        if self.draw_mode == 'view':
             return 'NONE' if self.hit else 'CROSSHAIR'
        return 'MOVE_X'
    
    def get_scaled_radius(self):
        return self.s * self.radius
    
    def get_strength_dist(self, dist:float):
        return 1.0 - math.pow(dist / self.get_scaled_radius(), self.strength)
    
    def get_strength_Point(self, point:Point):
        return self.get_strength_dist((point - self.p).length)
    
    def draw_postview(self):
        if self.draw_mode != 'view': return
        if not self.hit: return
        cx,cy,cp = self.x,self.y,self.p
        cs_outer = self.s * self.radius
        cs_inner = self.s * self.radius * math.pow(0.5, 1.0 / self.strength)
        
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
        for x,y in self.points:
            p = (cs_outer * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()
        
        bgl.glColor4f(1, 1, 1, 0.5)     # inner ring
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
        
        bgl.glColor4f(1, 1, 1, 0.05)    # outer ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in self.points:
            p = (cs_outer * ((cx * x) + (cy * y))) + cp
            bgl.glVertex3f(*p)
        bgl.glEnd()
        
        bgl.glColor4f(1, 1, 1, 0.025)   # inner ring
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
    
    def draw_postpixel(self):
        if self.draw_mode != 'pixel': return
        
        w,h = self.rfcontext.eventd.width,self.rfcontext.eventd.height
        
        cx,cy,cp = Vector((1,0)),Vector((0,1)),Vector((w/2,h/2))
        cs_outer = self.radius
        cs_inner = self.radius * math.pow(0.5, 1.0 / self.strength)
        
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glLineWidth(2.0)
        
        bgl.glColor4f(1, 1, 1, 1)                       # outer ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in self.points:
            p = (cs_outer * ((cx * x) + (cy * y))) + cp
            bgl.glVertex2f(*p)
        bgl.glEnd()
        
        bgl.glColor4f(1, 1, 1, 0.5)                     # inner ring
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for x,y in self.points:
            p = (cs_inner * ((cx * x) + (cy * y))) + cp
            bgl.glVertex2f(*p)
        bgl.glEnd()
    
    def cursor_warp(self, xy:Point2D):
        eventd = self.rfcontext.eventd
        x,y = eventd.region.x,eventd.region.y
        mx,my = xy
        eventd.context.window.cursor_warp(x + mx, y + my)
        eventd.mouse = xy
    
    def modal_resize(self, ret_mode):
        eventd = self.rfcontext.eventd
        w,h = eventd.width,eventd.height
        center = Point2D((w/2, h/2))
        
        if self.draw_mode == 'view':
            # first time
            self.mousepre = Point2D(eventd.mouse)
            self.cursor_warp(Point2D((w/2 + self.radius, h/2)))
            self.draw_mode = 'pixel'
            return ''
        
        if eventd.press == 'LEFTMOUSE':
            self.draw_mode = 'view'
            self.cursor_warp(self.mousepre)
            return ret_mode
        
        self.radius = (center - eventd.mouse).length
        return ''
        
    def modal_restrength(self, ret_mode):
        eventd = self.rfcontext.eventd
        w,h = eventd.width,eventd.height
        center = Point2D((w/2, h/2))
        
        if self.draw_mode == 'view':
            # first time
            self.mousepre = Point2D(eventd.mouse)
            self.cursor_warp(Point2D((w/2 + self.radius * math.pow(0.5, 1.0 / self.strength), h/2)))
            self.draw_mode = 'pixel'
            return ''
        
        if eventd.press == 'LEFTMOUSE':
            self.draw_mode = 'view'
            self.cursor_warp(self.mousepre)
            return ret_mode
        
        dist = (center - eventd.mouse).length
        ratio = max(0.0001, min(0.9999, dist / self.radius))
        
        self.strength = math.log(0.5) / math.log(ratio)
        return ''
        