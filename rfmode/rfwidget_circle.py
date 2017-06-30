import math
import bgl
from mathutils import Matrix, Vector
from ..common.maths import Vec, Point, Point2D, Direction

from .rfwidget import RFWidget

class RFWidget_Circle(RFWidget):
    def __init__(self):
        self.points = [(math.cos(r*math.pi/180.0),math.sin(r*math.pi/180.0)) for r in range(0,361,10)]
        self.hit = False
        self.radius = 50.0
        self.strength = 0.5
        self.falloff = 1.5
        self.draw_mode = 'view'
        self.ox = Direction((1,0,0))
        self.oy = Direction((0,1,0))
        self.oz = Direction((0,0,1))
        self.color = (1,1,1)
    
    def update(self):
        p,n = self.rfcontext.hit_pos,self.rfcontext.hit_norm
        if p is None or n is None:
            self.hit = False
            return
        xy = self.rfcontext.actions.mouse
        rmat = Matrix.Rotation(self.oz.angle(n), 4, self.oz.cross(n))
        self.p = p
        self.s = self.rfcontext.size2D_to_size(1.0, xy, self.rfcontext.Point_to_depth(p))
        self.x = Vec(rmat * self.ox)
        self.y = Vec(rmat * self.oy)
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
        return (1.0 - math.pow(dist / self.get_scaled_radius(), self.falloff)) * self.strength
    
    def get_strength_Point(self, point:Point):
        return self.get_strength_dist((point - self.p).length)
    
    def draw_postview(self):
        if self.draw_mode != 'view': return
        if not self.hit: return
        cx,cy,cp = self.x,self.y,self.p
        cs_outer = self.s * self.radius
        cs_inner = self.s * self.radius * math.pow(0.5, 1.0 / self.falloff)
        cr,cg,cb = self.color
        
        bgl.glDepthRange(0, 0.999)      # squeeze depth just a bit 
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glLineWidth(2.0)
        bgl.glPointSize(3.0)
        
        ######################################
        # draw in front of geometry
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
        
        bgl.glColor4f(cr, cg, cb, 0.75 * self.strength)
        bgl.glBegin(bgl.GL_TRIANGLES)
        for p0,p1 in zip(self.points[:-1], self.points[1:]):
            x0,y0 = p0
            x1,y1 = p1
            outer0 = (cs_outer * ((cx * x0) + (cy * y0))) + cp
            outer1 = (cs_outer * ((cx * x1) + (cy * y1))) + cp
            inner0 = (cs_inner * ((cx * x0) + (cy * y0))) + cp
            inner1 = (cs_inner * ((cx * x1) + (cy * y1))) + cp
            bgl.glVertex3f(*outer0)
            bgl.glVertex3f(*outer1)
            bgl.glVertex3f(*inner0)
            bgl.glVertex3f(*outer1)
            bgl.glVertex3f(*inner1)
            bgl.glVertex3f(*inner0)
        bgl.glEnd()
        
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
        
        bgl.glColor4f(cr, cg, cb, 0.10 * self.strength)
        bgl.glBegin(bgl.GL_TRIANGLES)
        for p0,p1 in zip(self.points[:-1], self.points[1:]):
            x0,y0 = p0
            x1,y1 = p1
            outer0 = (cs_outer * ((cx * x0) + (cy * y0))) + cp
            outer1 = (cs_outer * ((cx * x1) + (cy * y1))) + cp
            inner0 = (cs_inner * ((cx * x0) + (cy * y0))) + cp
            inner1 = (cs_inner * ((cx * x1) + (cy * y1))) + cp
            bgl.glVertex3f(*outer0)
            bgl.glVertex3f(*outer1)
            bgl.glVertex3f(*inner0)
            bgl.glVertex3f(*outer1)
            bgl.glVertex3f(*inner1)
            bgl.glVertex3f(*inner0)
        bgl.glEnd()
        
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
        
        w,h = self.rfcontext.actions.size
        
        cx,cy,cp = Vector((1,0)),Vector((0,1)),Vector((w/2,h/2))
        cs_outer = self.radius
        cs_inner = self.radius * math.pow(0.5, 1.0 / self.falloff)
        cr,cg,cb = self.color
        
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glLineWidth(2.0)
        
        bgl.glColor4f(cr, cg, cb, 0.75 * self.strength)
        bgl.glBegin(bgl.GL_TRIANGLES)
        for p0,p1 in zip(self.points[:-1], self.points[1:]):
            x0,y0 = p0
            x1,y1 = p1
            outer0 = (cs_outer * ((cx * x0) + (cy * y0))) + cp
            outer1 = (cs_outer * ((cx * x1) + (cy * y1))) + cp
            inner0 = (cs_inner * ((cx * x0) + (cy * y0))) + cp
            inner1 = (cs_inner * ((cx * x1) + (cy * y1))) + cp
            bgl.glVertex2f(*outer0)
            bgl.glVertex2f(*outer1)
            bgl.glVertex2f(*inner0)
            bgl.glVertex2f(*outer1)
            bgl.glVertex2f(*inner1)
            bgl.glVertex2f(*inner0)
        bgl.glEnd()
        
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
    
    def modal_size(self, ret_mode):
        actions = self.rfcontext.actions
        w,h = actions.size
        center = Point2D((w/2, h/2))
        
        if self.draw_mode == 'view':
            # first time
            self.mousepre = Point2D(actions.mouse)
            actions.warp_mouse(Point2D((w/2 + self.radius, h/2)))
            self.draw_mode = 'pixel'
            self.radiuspre = self.radius
            return ''
        
        if actions.pressed({'cancel','confirm'}, unpress=False):
            if actions.pressed('cancel'): self.radius = self.radiuspre
            actions.unpress()
            self.draw_mode = 'view'
            actions.warp_mouse(self.mousepre)
            return ret_mode
        
        self.radius = (center - actions.mouse).length
        return ''
    
    def modal_falloff(self, ret_mode):
        actions = self.rfcontext.actions
        w,h = actions.size
        center = Point2D((w/2, h/2))
        
        if self.draw_mode == 'view':
            # first time
            self.mousepre = Point2D(actions.mouse)
            actions.warp_mouse(Point2D((w/2 + self.radius * math.pow(0.5, 1.0 / self.falloff), h/2)))
            self.draw_mode = 'pixel'
            self.falloffpre = self.falloff
            return ''
        
        if actions.pressed('cancel'):
            self.falloff = self.falloffpre
            self.draw_mode = 'view'
            actions.warp_mouse(self.mousepre)
            return ret_mode
        
        if actions.pressed('confirm'):
            self.draw_mode = 'view'
            actions.warp_mouse(self.mousepre)
            return ret_mode
        
        dist = (center - actions.mouse).length
        ratio = max(0.0001, min(0.9999, dist / self.radius))
        
        self.falloff = math.log(0.5) / math.log(ratio)
        return ''
    
    def modal_strength(self, ret_mode):
        actions = self.rfcontext.actions
        w,h = actions.size
        center = Point2D((w/2, h/2))
        
        if self.draw_mode == 'view':
            # first time
            self.mousepre = Point2D(actions.mouse)
            actions.warp_mouse(Point2D((w/2 + self.radius * self.strength, h/2)))
            self.draw_mode = 'pixel'
            self.strengthpre = self.strength
            return ''
        
        if actions.pressed('cancel'):
            self.strength = self.strengthpre
            self.draw_mode = 'view'
            actions.warp_mouse(self.mousepre)
            return ret_mode
        
        if actions.pressed('confirm'):
            self.draw_mode = 'view'
            actions.warp_mouse(self.mousepre)
            return ret_mode
        
        dist = (center - actions.mouse).length
        ratio = max(0.0001, min(1.0, dist / self.radius))
        
        self.strength = ratio
        return ''
        