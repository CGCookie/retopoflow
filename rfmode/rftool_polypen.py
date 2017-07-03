import bpy
import math
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec

@RFTool.action_call('polypen tool')
class RFTool_PolyPen(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['insert'] = self.modal_insert
        self.FSM['move']  = self.modal_move
        self.FSM['select move'] = self.modal_select_move
        self.FSM['place'] = self.modal_place
    
    def name(self): return "PolyPen"
    
    def start(self):
        self.rfwidget.set_widget('default', color=(1.0, 1.0, 1.0))

    def modal_main(self):
        if self.rfcontext.actions.pressed('insert'):
            return 'insert'
        
        # if self.rfcontext.actions.pressed('action'):
        #     self.rfcontext.undo_push('polypen place vert')
        #     radius = self.rfwidget.get_scaled_radius()
        #     nearest = self.rfcontext.nearest_verts_mouse(radius)
        #     if not nearest:
        #         self.rfcontext.undo_cancel()
        #         return
        #     self.bmverts = [(bmv, Point(bmv.co), d3d) for bmv,d3d in nearest]
        #     self.rfcontext.select([bmv for bmv,_,_ in self.bmverts])
        #     self.mousedown = self.rfcontext.actions.mousedown
        #     return 'move'
        
        if self.rfcontext.actions.pressed('select add'):
            self.rfcontext.undo_push('select add')
            bmv,d3d = self.rfcontext.nearest2D_vert_mouse()
            self.rfcontext.select(bmv, only=False)
            return
            
        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('move single')
            bmv,d3d = self.rfcontext.nearest2D_vert_mouse()
            self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co))]
            self.rfcontext.select(bmv)
            self.mousedown = self.rfcontext.actions.mousedown
            return 'select move'
    
    @RFTool.dirty_when_done
    def modal_insert(self):
        self.rfcontext.undo_push('insert')
        
        sel_verts = self.rfcontext.rftarget.get_selected_verts()
        sel_edges = self.rfcontext.rftarget.get_selected_edges()
        sel_faces = self.rfcontext.rftarget.get_selected_faces()
        num_verts = len(sel_verts)
        num_edges = len(sel_edges)
        num_faces = len(sel_faces)
        
        if num_verts == 1 and num_edges == 0 and num_faces == 0:
            bmv0 = next(iter(sel_verts))
            bmv1 = self.rfcontext.new2D_vert_mouse()
            if not bmv1:
                self.rfcontext.undo_cancel()
                return 'main'
            bme = self.rfcontext.new_edge((bmv0, bmv1))
            self.rfcontext.select(bme)
            self.mousedown = self.rfcontext.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv1.co)
            if not xy:
                print('Could not insert: ' + str(bmv1.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv1, xy)]
            return 'move'
        
        if num_edges == 1 and num_faces == 0:
            bme = next(iter(sel_edges))
            bmv0,bmv1 = bme.verts
            bmv2 = self.rfcontext.new2D_vert_mouse()
            if not bmv2:
                self.rfcontext.undo_cancel()
                return 'main'
            bmf = self.rfcontext.new_face([bmv0, bmv1, bmv2])
            self.rfcontext.select(bmf)
            self.mousedown = self.rfcontext.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv2.co)
            if not xy:
                print('Could not insert: ' + str(bmv2.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv2, xy)]
            return 'move'
        
        bmv = self.rfcontext.new2D_vert_mouse()
        if not bmv:
            self.rfcontext.undo_cancel()
            return 'main'
        self.rfcontext.select(bmv)
        self.mousedown = self.rfcontext.actions.mousedown
        xy = self.rfcontext.Point_to_Point2D(bmv.co)
        if not xy:
            print('Could not insert: ' + str(bmv.co))
            self.rfcontext.undo_cancel()
            return 'main'
        self.bmverts = [(bmv, xy)]
        return 'move'
    
    @RFTool.dirty_when_done
    def modal_move(self):
        if self.rfcontext.actions.released('insert'):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            set2D_vert(bmv, xy + delta)
        for bmv,_ in self.bmverts:
            for f in bmv.link_faces:
                self.rfcontext.update_face_normal(f)
    @RFTool.dirty_when_done
    def modal_select_move(self):
        if self.rfcontext.actions.released('select'):
            return 'main'
        if self.rfcontext.actions.pressed('cancel no select'):
            self.rfcontext.undo_cancel()
            return 'main'
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            set2D_vert(bmv, xy + delta)
        for bmv,_ in self.bmverts:
            for f in bmv.link_faces:
                self.rfcontext.update_face_normal(f)

    @RFTool.dirty_when_done
    def modal_place(self):
        if self.rfcontext.actions.released('action'):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

    def draw_postview(self): pass
    def draw_postpixel(self): pass