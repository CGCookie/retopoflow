import math
import bgl
from mathutils import Matrix, Vector
from ..common.maths import Vec, Point, Point2D, Direction
from ..lib.common_drawing_bmesh import glEnableStipple

class RFWidget_Line:
    def line_modal_main(self):
        if self.rfcontext.actions.pressed('insert'):
            self.line2D = [self.rfcontext.actions.mouse] * 2
            return 'line'
    
    def modal_line(self):
        actions = self.rfcontext.actions
        
        if actions.released('insert'):
            if self.line_callback: self.line_callback()
            return 'main'
        
        if actions.pressed('cancel'):
            self.line2D.clear()
            return 'main'
        
        self.line2D[1] = actions.mouse
    
    def line_mouse_cursor(self): return 'CROSSHAIR'
    
    def line_postview(self): pass
    
    def line_postpixel(self):
        if self.mode == 'main': return
        
        cr,cg,cb = self.color
        p0,p1 = self.line2D
        ctr = p0 + (p1-p0)/2
        
        bgl.glEnable(bgl.GL_BLEND)
        self.drawing.line_width(2.0)
        
        glEnableStipple(enable=True)
        bgl.glColor4f(1,1,1,0.5)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        bgl.glVertex2f(*p0)
        bgl.glVertex2f(*p1)
        bgl.glEnd()
        glEnableStipple(enable=False)
        
        # self.drawing.line_width(1.0)
        bgl.glColor4f(cr, cg, cb, 0.25)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for px,py in self.points:
            x = ctr.x + px * 10
            y = ctr.y + py * 10
            bgl.glVertex2f(x, y)
        bgl.glEnd()
