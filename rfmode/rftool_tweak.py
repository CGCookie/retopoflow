import bpy
import math
from .rftool import RFTool
from .load_icon import load_icon
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.ui import UI_Image

@RFTool.action_call('move tool')
class RFTool_Tweak(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['move'] = self.modal_move
    
    def name(self): return "Tweak"
    def icon(self): return "rf_tweak_icon"
    def description(self): return 'Moves vertices with falloff'
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('brush falloff', color=(0.5, 0.5, 1.0))
    
    def get_ui_icon(self):
        icon = load_icon('tweak_32.png')
        self.ui_icon = UI_Image(icon)
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    def modal_main(self):
        if self.rfcontext.actions.pressed('action'):
            self.rfcontext.undo_push('tweak move')
            radius = self.rfwidget.get_scaled_radius()
            nearest = self.rfcontext.nearest_verts_mouse(radius)
            if not nearest:
                self.rfcontext.undo_cancel()
                return
            Point_to_Point2D = self.rfcontext.Point_to_Point2D
            get_strength_dist = self.rfwidget.get_strength_dist
            self.bmverts = [(bmv, Point_to_Point2D(bmv.co), get_strength_dist(d3d)) for bmv,d3d in nearest]
            self.bmfaces = set([f for bmv,_ in nearest for f in bmv.link_faces])
            #self.rfcontext.select([bmv for bmv,_,_ in self.bmverts])
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
        update_face_normal = self.rfcontext.update_face_normal
        
        for bmv,xy,strength in self.bmverts:
            set2D_vert(bmv, xy + delta*strength)
        for bmf in self.bmfaces:
            update_face_normal(bmf)
    
    def draw_postview(self): pass
    def draw_postpixel(self): pass
    
