import bpy
import math
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec

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
    
    @RFTool.dirty_when_done
    def stroke(self):
        self.rfcontext.undo_push('stroke')
        
        radius = self.rfwidget.radius #get_scaled_radius()
        stroke = self.rfwidget.stroke2D
        stroke_len = len(stroke)
        bmfaces = []
        
        mini_stroke = [stroke[i] for i in range(0, stroke_len, int(stroke_len/10))]
        left,right = [],[]
        
        for c0,c1 in zip(mini_stroke[:-1],mini_stroke[1:]):
            d = c1 - c0
            ortho = Vec2D((-d.y, d.x)).normalized() * radius
            left.append(self.rfcontext.new2D_vert_point(c0+ortho))
            right.append(self.rfcontext.new2D_vert_point(c0-ortho))
        
        for i in range(len(left)-1):
            l0,r0 = left[i],right[i]
            l1,r1 = left[i+1],right[i+1]
            bmfaces.append(self.rfcontext.new_face([l1,l0,r0,r1]))
        
        self.rfcontext.select(bmfaces)
    
    def modal_main(self):
        pass
    
    def draw_postview(self): pass
    def draw_postpixel(self): pass
    
