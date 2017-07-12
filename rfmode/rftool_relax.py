import bpy
import math
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec

@RFTool.action_call('relax tool')
class RFTool_Relax(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['relax'] = self.modal_relax
        self.FSM['relax selected'] = self.modal_relax_selected
    
    def name(self): return "Relax"
    def icon(self): return "rf_relax_icon"
    def description(self): return 'Relax topology by changing length of edges to average'
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('brush falloff', color=(0.5, 1.0, 0.5))
    
    def modal_main(self):
        if self.rfcontext.actions.pressed('action'):
            self.rfcontext.undo_push('relax')
            return 'relax'
        
        if self.rfcontext.actions.pressed('relax selected'):
            self.rfcontext.undo_push('relax selected')
            self.selected = [(v,0.0) for v in self.rfcontext.get_selected_verts()]
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
        self._relax(nearest)
    
    @RFTool.dirty_when_done
    def modal_relax_selected(self):
        if self.rfcontext.actions.released('relax selected'):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'
        if not self.rfcontext.actions.timer: return
        self._relax(self.selected)
        
    
    def _relax(self, nearest):
        time_delta = self.rfcontext.actions.time_delta
        strength = 100.0 * self.rfwidget.strength * time_delta
        radius = self.rfwidget.get_scaled_radius()
        
        avgDist,avgCount,divco = 0,0,{}
        
        # collect data for smoothing
        edges,faces = set(),set()
        for bmv0,d in nearest:
            edges.update(bmv0.link_edges)
            faces.update(bmv0.link_faces)
        if not edges: return
        
        # compute average edge length
        for bme in edges: avgDist += bme.calc_length()
        avgDist /= len(edges)
        
        for bme in edges:
            for bmv in bme.verts:
                divco[bmv] = Point(bmv.co)
        for bmf in faces:
            for bmv in bmf.verts:
                divco[bmv] = Point(bmv.co)
        
        # perform smoothing
        touched = set()
        for bmv0,d in nearest:
            lbme,lbmf = bmv0.link_edges,bmv0.link_faces
            if not lbme: continue
            # push edges closer to average edge length
            for bme in lbme:
                if bme in touched: continue
                bmv1 = bme.other_vert(bmv0)
                diff = bmv1.co - bmv0.co
                m = (avgDist - diff.length) * (1.0 - d) * 0.1
                divco[bmv1] += diff * m * strength
                divco[bmv0] -= diff * m * strength
            # attempt to "square" up the faces
            for bmf in lbmf:
                cnt = len(bmf.verts)
                ctr = sum([bmv.co for bmv in bmf.verts], Vec((0,0,0))) / cnt
                fd = sum((ctr-bmv.co).length for bmv in bmf.verts) / cnt
                for bmv in bmf.verts:
                    diff = (bmv.co - ctr)
                    m = (fd - diff.length)* (1.0- d) / cnt
                    divco[bmv] += diff * m * strength
        
        # update
        for bmv,co in divco.items():
            p,_,_,_ = self.rfcontext.nearest_sources_Point(co)
            bmv.co = p
