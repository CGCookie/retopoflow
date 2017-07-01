import bpy
import math
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec

@RFTool.action_call('move tool')
class RFTool_Move(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['move'] = self.modal_move
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('brush falloff', color=(0.5, 0.5, 1.0))
    
    def modal_main(self):
        if self.rfcontext.actions.pressed('action'):
            self.rfcontext.undo_push('tweak move')
            radius = self.rfwidget.get_scaled_radius()
            nearest = self.rfcontext.nearest_verts_mouse(radius)
            Point_to_Point2D = self.rfcontext.Point_to_Point2D
            get_strength_dist = self.rfwidget.get_strength_dist
            self.bmverts = [(bmv, Point_to_Point2D(bmv.co), get_strength_dist(d3d)) for bmv,d3d in nearest]
            self.rfcontext.select([bmv for bmv,_,_ in self.bmverts])
            self.mousedown = self.rfcontext.actions.mousedown
            return 'move'
        
        # if self.rfcontext.eventd.press in {'RIGHTMOUSE'}:
        #     self.rfcontext.undo_push('tweak move single')
        #     bmv,d3d = self.rfcontext.nearest2D_vert_mouse()
        #     self.bmverts = [(bmv, Point(bmv.co), 0.0)]
        #     self.rfcontext.select(bmv)
        #     self.mousedown = self.rfcontext.eventd.mousedown
        #     return 'move'
        
    
    @RFTool.dirty_when_done
    def modal_move(self):
        if self.rfcontext.actions.released('action'):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'
        
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        
        for bmv,xy,strength in self.bmverts:
            set2D_vert(bmv, xy + delta*strength)
    
    def draw_postview(self): pass
    def draw_postpixel(self): pass
    
