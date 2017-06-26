import bpy
import math
from .rftool import RFTool, dirty_when_done
from .rfwidget_circle import RFWidget_Circle
from ..common.maths import Point,Point2D,Vec2D,Vec

class RFTool_Tweak(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['tweak'] = self.modal_tweak
        self.FSM['resize'] = lambda: RFWidget_Circle().modal_resize('main')
        self.FSM['restrength'] = lambda: RFWidget_Circle().modal_restrength('main')
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.bmverts = []
    
    ''' Returns type of cursor to display '''
    def rfwidget(self):
        return RFWidget_Circle()
    
    def modal_main(self):
        if self.rfcontext.eventd.press in {'LEFTMOUSE'}: #,'SHIFT+LEFTMOUSE'}:
            radius = RFWidget_Circle().get_scaled_radius()
            nearest = self.rfcontext.target_nearest_bmverts_mouse(radius)
            self.bmverts = [(bmv, Point(bmv.co), d3d) for bmv,d3d in nearest]
            self.rfcontext.undo_push("tweak")
            #self.rfcontext.select(self.bmverts, only=not self.rfcontext.eventd.shift)
            return 'tweak'
        
        if self.rfcontext.eventd.press in {'RIGHTMOUSE'}:
            return 'resize'
        
        if self.rfcontext.eventd.press in {'SHIFT+RIGHTMOUSE'}:
            return 'restrength'
        
        return ''
    
    @dirty_when_done
    def modal_tweak(self):
        if self.rfcontext.eventd.release in {'LEFTMOUSE'}:
            return 'main'
        
        if self.rfcontext.eventd.release in {'ESC'}:
            self.rfcontext.undo_cancel()
            return 'main'
        
        delta = Vec2D(self.rfcontext.eventd.mouse - self.rfcontext.eventd.mousedown_left)
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        raycast_sources_Point2D = self.rfcontext.raycast_sources_Point2D
        get_strength_dist = RFWidget_Circle().get_strength_dist
        
        for bmv,oco,d3d in self.bmverts:
            oco_screen = Point_to_Point2D(oco) + delta * get_strength_dist(d3d)
            p,_,_,_ = raycast_sources_Point2D(oco_screen)
            if p is None: continue
            bmv.co = p
        
        return ''
    
    def draw_postview(self): pass
    def draw_postpixel(self): pass
    
