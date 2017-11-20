import bpy
import math
from .rftool import RFTool
from .load_image import load_image_png
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.ui import UI_Image,UI_BoolValue,UI_Label
from ..options import help_relax

@RFTool.action_call('relax tool')
class RFTool_Relax(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['relax'] = self.modal_relax
        self.FSM['relax selected'] = self.modal_relax_selected
        self.move_boundary = False
        self.move_hidden = False
    
    def name(self): return "Relax"
    def icon(self): return "rf_relax_icon"
    def description(self): return 'Relax topology by changing length of edges to average'
    def helptext(self): return help_relax
    
    def get_move_boundary(self): return self.move_boundary
    def set_move_boundary(self, v): self.move_boundary = v
    def get_move_hidden(self): return self.move_hidden
    def set_move_hidden(self, v): self.move_hidden = v
    def get_ui_options(self):
        return [
            UI_Label('Move:'),
            UI_BoolValue('Boundary', self.get_move_boundary, self.set_move_boundary),
            UI_BoolValue('Hidden', self.get_move_hidden, self.set_move_hidden),
        ]
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('brush falloff', color=(0.5, 1.0, 0.5))
        # scan through all edges, finding all non-manifold edges
        self.verts_nonmanifold = {
            v for e in self.rfcontext.rftarget.get_edges()
            for v in e.verts if len(e.link_faces) != 2
            }
    
    def get_ui_icon(self):
        icon = load_image_png('relax_32.png')
        self.ui_icon = UI_Image(icon)
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    def modal_main(self):
        if self.rfcontext.actions.pressed('action'):
            self.rfcontext.undo_push('relax')
            return 'relax'
        
        if self.rfcontext.actions.pressed('relax selected'):
            self.rfcontext.undo_push('relax selected')
            self.sel_verts = self.rfcontext.get_selected_verts()
            self.selected = [(v,0.0) for v in self.sel_verts]
            self.sel_edges = self.rfcontext.get_selected_edges()
            self.sel_faces = self.rfcontext.get_selected_faces()
            return 'relax selected'
    
    @RFTool.dirty_when_done
    def modal_relax(self):
        if self.rfcontext.actions.released('action'):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'
        
        if not self.rfcontext.actions.timer: return
        
        hit_pos = self.rfcontext.actions.hit_pos
        if not hit_pos: return
        
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_point(hit_pos, radius)
        # collect data for smoothing
        verts,edges,faces,vert_dist = set(),set(),set(),dict()
        for bmv,d in nearest:
            verts.add(bmv)
            edges.update(bmv.link_edges)
            faces.update(bmv.link_faces)
            vert_dist[bmv] = self.rfwidget.get_strength_dist(d) #/radius
        self._relax(verts, edges, faces, vert_dist)
    
    @RFTool.dirty_when_done
    def modal_relax_selected(self):
        if self.rfcontext.actions.released('relax selected'):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'
        if not self.rfcontext.actions.timer: return
        self._relax(self.sel_verts, self.sel_edges, self.sel_faces)
    
    def _relax(self, verts, edges, faces, vert_dist=None):
        if not verts or not edges: return
        vert_dist = vert_dist or {}
        
        time_delta = self.rfcontext.actions.time_delta
        strength = 100.0 * self.rfwidget.strength * time_delta
        radius = self.rfwidget.get_scaled_radius()
        
        # compute average edge length
        avgDist = sum(bme.calc_length() for bme in edges) / len(edges)
        
        # capture all verts involved in relaxing
        chk_verts = set(verts)
        chk_verts |= {bmv for bme in edges for bmv in bme.verts}
        chk_verts |= {bmv for bmf in faces for bmv in bmf.verts}
        divco = {bmv:Point(bmv.co) for bmv in chk_verts}
        
        # perform smoothing
        touched = set()
        for bmv0 in verts:
            d = vert_dist.get(bmv0, 0)
            lbme,lbmf = bmv0.link_edges,bmv0.link_faces
            if not lbme: continue
            # push edges closer to average edge length
            for bme in lbme:
                if bme not in edges: continue
                if bme in touched: continue
                touched.add(bme)
                bmv1 = bme.other_vert(bmv0)
                diff = bmv1.co - bmv0.co
                m = (avgDist - diff.length) * (1.0 - d) * 0.1
                divco[bmv1] += diff * m * strength
                divco[bmv0] -= diff * m * strength
            # attempt to "square" up the faces
            for bmf in lbmf:
                if bmf not in faces: continue
                if bmf in touched: continue
                touched.add(bmf)
                cnt = len(bmf.verts)
                ctr = sum([bmv.co for bmv in bmf.verts], Vec((0,0,0))) / cnt
                fd = sum((ctr-bmv.co).length for bmv in bmf.verts) / cnt
                for bmv in bmf.verts:
                    diff = (bmv.co - ctr)
                    m = (fd - diff.length)* (1.0- d) / cnt
                    divco[bmv] += diff * m * strength
        
        # update
        for bmv,co in divco.items():
            if bmv not in verts: continue
            if not self.move_boundary:
                if bmv in self.verts_nonmanifold: continue
            if not self.move_hidden:
                if not self.rfcontext.is_visible(bmv.co, bmv.normal): continue
            p,_,_,_ = self.rfcontext.nearest_sources_Point(co)
            bmv.co = p
