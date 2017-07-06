import bgl
import bpy
import math
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.bezier import CubicBezierSpline

class RFTool_State():
    def __init__(self, **kwargs):
        self.update(kwargs)
    def update(self, kv):
        for k,v in kv.items():
            self.__setattr__(k, v)

@RFTool.action_call('polystrips tool')
class RFTool_PolyStrips(RFTool):
    def init(self):
        pass
    
    def name(self): return "PolyStrips"
    def icon(self): return "rf_polystrips_icon"
    def description(self): return 'Strips of quads made easy'
    
    def start(self):
        self.rfwidget.set_widget('brush stroke', color=(1.0, 0.5, 0.5))
        self.rfwidget.set_stroke_callback(self.stroke)
        self.update()
    
    def update(self):
        self.cbs = None
    
    @RFTool.dirty_when_done
    def stroke(self):
        self.rfcontext.undo_push('stroke')
        
        radius = self.rfwidget.radius #get_scaled_radius()
        stroke2D = self.rfwidget.stroke2D
        stroke_len = len(stroke2D)
        bmfaces = []
        
        strokes = []
        cur_stroke = []
        for pt2D in stroke2D:
            pt = self.rfcontext.get_point3D(pt2D)
            if not pt:
                if cur_stroke: strokes += [cur_stroke]
                cur_stroke = []
                continue
            cur_stroke += [pt]
        if cur_stroke: strokes += [cur_stroke]
        
        self.cbs = CubicBezierSpline.create_from_points(strokes, radius/2000.0)
        
        mini_stroke = [stroke2D[i] for i in range(0, stroke_len, int(stroke_len/10))]
        left,right = [],[]
        
        for c0,c1 in zip(mini_stroke[:-1],mini_stroke[1:]):
            d = c1 - c0
            ortho = Vec2D((-d.y, d.x)).normalized() * radius
            lpt = self.rfcontext.get_point3D(c0+ortho)
            rpt = self.rfcontext.get_point3D(c0-ortho)
            if lpt and rpt:
                left.append(self.rfcontext.new_vert_point(lpt))
                right.append(self.rfcontext.new_vert_point(rpt))
        
        for i in range(len(left)-1):
            l0,r0 = left[i],right[i]
            l1,r1 = left[i+1],right[i+1]
            bmfaces.append(self.rfcontext.new_face([l1,l0,r0,r1]))
        
        self.rfcontext.select(bmfaces)
    
    def modal_main(self):
        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('select')
            bmf = self.rfcontext.nearest2D_face_mouse()
            if bmf:
                self.rfcontext.select(bmf)
                self.update()
            return
        if self.rfcontext.actions.using('select add'):
            self.rfcontext.undo_push('select add')
            bmf = self.rfcontext.nearest2D_face_mouse()
            if bmf:
                self.rfcontext.select(bmf, only=False)
                self.update()
            return
    
    def draw_postview(self):
        self.draw_spline()
    
    def draw_spline(self):
        if not self.cbs: return
        
        bgl.glDepthRange(0, 0.9999)     # squeeze depth just a bit 
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glLineWidth(2.0)
        bgl.glPointSize(10.0)
        bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
        bgl.glEnable(bgl.GL_DEPTH_TEST)

        ######################################
        # draw in front of geometry

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glColor4f(1,1,1,0.5)
        bgl.glBegin(bgl.GL_POINTS)
        for cb in self.cbs:
            p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
            bgl.glVertex3f(*p0)
            bgl.glVertex3f(*p1)
            bgl.glVertex3f(*p2)
            bgl.glVertex3f(*p3)
        bgl.glEnd()
        bgl.glColor4f(1,1,1,0.5)
        bgl.glBegin(bgl.GL_LINES)
        for cb in self.cbs:
            p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
            bgl.glVertex3f(*p0)
            bgl.glVertex3f(*p1)
            bgl.glVertex3f(*p1)
            bgl.glVertex3f(*p2)
            bgl.glVertex3f(*p2)
            bgl.glVertex3f(*p3)
        bgl.glEnd()
    
        bgl.glDepthFunc(bgl.GL_GREATER)
        bgl.glColor4f(1,1,1,0.05)
        bgl.glBegin(bgl.GL_POINTS)
        for cb in self.cbs:
            p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
            bgl.glVertex3f(*p0)
            bgl.glVertex3f(*p1)
            bgl.glVertex3f(*p2)
            bgl.glVertex3f(*p3)
        bgl.glEnd()
        bgl.glColor4f(1,1,1,0.05)
        bgl.glBegin(bgl.GL_LINES)
        for cb in self.cbs:
            p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
            bgl.glVertex3f(*p0)
            bgl.glVertex3f(*p1)
            bgl.glVertex3f(*p1)
            bgl.glVertex3f(*p2)
            bgl.glVertex3f(*p2)
            bgl.glVertex3f(*p3)
        bgl.glEnd()
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glDepthMask(bgl.GL_TRUE)
    
    def draw_postpixel(self): pass
    
