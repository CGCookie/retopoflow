import bpy
import math
from .rftool import RFTool
from .rfwidget_circle import RFWidget_Circle
from ..common.maths import Point,Point2D,Vec2D,Vec

@RFTool.action_call({'T'})
class RFTool_Tweak_Move(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['move']     = self.modal_move
        self.FSM['size']     = lambda: RFWidget_Circle().modal_size('main')
        self.FSM['strength'] = lambda: RFWidget_Circle().modal_strength('main')
        self.FSM['falloff']  = lambda: RFWidget_Circle().modal_falloff('main')
    
    ''' Called the tool is being switched into '''
    def start(self):
        RFWidget_Circle().color = (0.5, 0.5, 1.0)
    
    ''' Returns type of cursor to display '''
    def rfwidget(self):
        return RFWidget_Circle()
    
    def modal_main(self):
        if self.rfcontext.eventd.press in self.rfcontext.keymap['action']:
            self.rfcontext.undo_push('tweak move')
            radius = RFWidget_Circle().get_scaled_radius()
            nearest = self.rfcontext.target_nearest_bmverts_mouse(radius)
            self.bmverts = [(bmv, Point(bmv.co), d3d) for bmv,d3d in nearest]
            self.rfcontext.select([bmv for bmv,_,_ in self.bmverts])
            self.mousedown = self.rfcontext.eventd.mousedown
            return 'move'
        
        # if self.rfcontext.eventd.press in {'RIGHTMOUSE'}:
        #     self.rfcontext.undo_push('tweak move single')
        #     bmv,d3d = self.rfcontext.target_nearest2D_bmvert_mouse()
        #     self.bmverts = [(bmv, Point(bmv.co), 0.0)]
        #     self.rfcontext.select(bmv)
        #     self.mousedown = self.rfcontext.eventd.mousedown
        #     return 'move'
        
        if self.rfcontext.eventd.press in self.rfcontext.keymap['brush size']:
            return 'size'
        if self.rfcontext.eventd.press in self.rfcontext.keymap['brush strength']:
            return 'strength'
        if self.rfcontext.eventd.press in self.rfcontext.keymap['brush falloff']:
            return 'falloff'
    
    @RFTool.dirty_when_done
    def modal_move(self):
        if self.rfcontext.eventd.release in self.rfcontext.keymap['action']:
            return 'main'
        if self.rfcontext.eventd.release in self.rfcontext.keymap['cancel']:
            self.rfcontext.undo_cancel()
            return 'main'
        
        delta = Vec2D(self.rfcontext.eventd.mouse - self.mousedown)
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        raycast_sources_Point2D = self.rfcontext.raycast_sources_Point2D
        get_strength_dist = RFWidget_Circle().get_strength_dist
        
        for bmv,oco,d3d in self.bmverts:
            oco_screen = Point_to_Point2D(oco) + delta * get_strength_dist(d3d)
            p,_,_,_ = raycast_sources_Point2D(oco_screen)
            if p is None: continue
            bmv.co = p
    
    def draw_postview(self): pass
    def draw_postpixel(self): pass
    
