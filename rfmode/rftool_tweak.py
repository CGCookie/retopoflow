import bpy
import math
from .rftool import RFTool
from .rfwidget import RFWidgetDefault, RFWidgetCircle
from ..common.maths import Point,Point2D,Vec2D,Vec

class RFTool_Tweak(RFTool):
    ''' Called when RetopoFlow plugin is '''
    def init_tool(self):
        self.FSM['tweak'] = self.modal_tweak
        pass
    
    def init(self):
        ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
        pass
    
    def start(self):
        ''' Called the tool is being switched into '''
        self.bmverts = []
        pass
    
    def rfwidget(self):
        ''' Returns type of cursor to display '''
        #if self.mode in 'tweak':
        #    return RFWidgetDefault
        return RFWidgetCircle
    
    def modal_main(self):
        if self.rfcontext.eventd.press in {'LEFTMOUSE'}: #,'SHIFT+LEFTMOUSE'}:
            nearest = self.rfcontext.target_nearest_bmverts_mouse(RFWidgetCircle.s)
            self.bmverts = [(bmv, Point(bmv.co), d3d / RFWidgetCircle.s) for bmv,d3d in nearest]
            #self.rfcontext.select(self.bmverts, only=not self.rfcontext.eventd.shift)
            return ('tweak', True)
        return ('', True)
    
    def modal_tweak(self):
        if self.rfcontext.eventd.release in {'LEFTMOUSE'}:
            print('done!')
            return ('main', True)
        delta = Vec2D(self.rfcontext.eventd.mouse - self.rfcontext.eventd.mousedown)
        l2w_point = self.rfcontext.rftarget.xform.l2w_point
        w2l_point = self.rfcontext.rftarget.xform.w2l_point
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        raycast_sources_Point2D = self.rfcontext.raycast_sources_Point2D
        
        for bmv,oco,d3d in self.bmverts:
            oco_world = l2w_point(oco)
            oco_screen = Point_to_Point2D(oco_world)
            oco_screen += delta * (1.0 - math.pow(d3d,0.5))
            p,_,_,_ = raycast_sources_Point2D(oco_screen)
            if p is None: continue
            bmv.co = w2l_point(p)
        
        self.rfcontext.rftarget.dirty()
        return ('', True)
    
    def draw_postview(self): pass
    def draw_postpixel(self): pass
    
