import bpy
import math
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec

@RFTool.action_call('polypen tool')
class RFTool_PolyPen(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['move']  = self.modal_move
        self.FSM['place'] = self.modal_place
    
    def name(self): return "PolyPen"
    
    def start(self):
        self.rfwidget.set_widget('default', color=(1.0, 1.0, 1.0))

    def modal_main(self):
        if self.rfcontext.actions.pressed('insert'):
            self.rfcontext.undo_push('polypen insert')
            bmv = self.rfcontext.new2D_vert_mouse()
            self.rfcontext.select(bmv)
            self.rfcontext.dirty()
            return
        
        if self.rfcontext.actions.pressed('action'):
            self.rfcontext.undo_push('polypen place vert')
            radius = self.rfwidget.get_scaled_radius()
            nearest = self.rfcontext.nearest_verts_mouse(radius)
            self.bmverts = [(bmv, Point(bmv.co), d3d) for bmv,d3d in nearest]
            self.rfcontext.select([bmv for bmv,_,_ in self.bmverts])
            self.mousedown = self.rfcontext.actions.mousedown
            return 'place'
        
        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('polypen move single')
            bmv,d3d = self.rfcontext.nearest2D_vert_mouse()
            self.bmverts = [(bmv, Point(bmv.co), 0.0)]
            self.rfcontext.select(bmv)
            self.mousedown = self.rfcontext.actions.mousedown
            return 'move'

    @RFTool.dirty_when_done
    def modal_move(self):
        if self.rfcontext.actions.released('action'):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        raycast_sources_Point2D = self.rfcontext.raycast_sources_Point2D
        get_strength_dist = self.rfwidget.get_strength_dist

        for bmv,oco,d3d in self.bmverts:
            oco_screen = Point_to_Point2D(oco) + delta * get_strength_dist(d3d)
            p,_,_,_ = raycast_sources_Point2D(oco_screen)
            if p is None: continue
            bmv.co = p

    @RFTool.dirty_when_done
    def modal_place(self):
        if self.rfcontext.actions.released('action'):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

    def draw_postview(self): pass
    def draw_postpixel(self): pass