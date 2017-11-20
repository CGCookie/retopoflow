import bpy
import math
import random
import bgl
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec,Accel2D
from ..common.ui import UI_Image,UI_BoolValue,UI_Label
from ..lib.common_utilities import dprint
from ..lib.classes.profiler.profiler import profiler
from .rfmesh import RFVert, RFEdge, RFFace
from ..common.utils import iter_pairs
from ..lib.common_drawing_bmesh import glEnableStipple
from ..options import help_loops

@RFTool.action_call('loops tool')
class RFTool_Loops(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['slide'] = self.modal_slide
    
    def name(self): return "Loops"
    def icon(self): return "rf_loops_icon"
    def description(self): return 'Loops creation, shifting, and deletion'
    def helptext(self): return help_loops
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('default')
        
        self.accel2D = None
        self.target_version = None
        self.view_version = None
        self.mouse_prev = None
        self.recompute = True
        self.defer_recomputing = False
        self.nearest_edge = None
    
    def get_ui_icon(self):
        self.ui_icon = UI_Image('loops_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    @profiler.profile
    def update(self):
        # selection has changed, undo/redo was called, etc.
        #self.target_version = None
        self.set_next_state()
    
    @profiler.profile
    def set_next_state(self):
        # TODO: optimize this!!!
        target_version = self.rfcontext.get_target_version()
        view_version = self.rfcontext.get_view_version()
        
        mouse_cur = self.rfcontext.actions.mouse
        mouse_prev = self.mouse_prev
        mouse_moved = 1 if not mouse_prev else mouse_prev.distance_squared_to(mouse_cur)
        self.mouse_prev = mouse_cur
        
        recompute = self.recompute
        recompute |= self.target_version != target_version
        recompute |= self.view_version != view_version
        
        if mouse_moved > 0:
            # mouse is still moving, so defer recomputing until mouse has stopped
            self.recompute = recompute
            return
        
        self.recompute = False
        
        if recompute and not self.defer_recomputing:
            self.target_version = target_version
            self.view_version = view_version
            
            # get visible geometry
            pr = profiler.start('determining visible geometry')
            self.vis_verts = self.rfcontext.visible_verts()
            self.vis_edges = self.rfcontext.visible_edges(verts=self.vis_verts)
            self.vis_faces = self.rfcontext.visible_faces(verts=self.vis_verts)
            pr.done()
            
            pr = profiler.start('creating 2D acceleration structure')
            p2p = self.rfcontext.Point_to_Point2D
            self.accel2D = Accel2D(self.vis_verts, self.vis_edges, self.vis_faces, p2p)
            pr.done()
        
        max_dist = self.drawing.scale(10)
        geom = self.accel2D.get(mouse_cur, max_dist)
        verts,edges,faces = ([g for g in geom if type(g) is t] for t in [RFVert,RFEdge,RFFace])
        nearby_edges = self.rfcontext.nearest2D_edges(edges=edges, max_dist=10)
        hover_edges = [e for e,_ in sorted(nearby_edges, key=lambda ed:ed[1])]
        self.nearest_edge = next(iter(hover_edges), None)
        
        self.percent = 0
        self.edges = None
        
        if self.nearest_edge:
            self.edges,self.edge_loop = self.rfcontext.get_face_loop(self.nearest_edge)
            vp0,vp1 = self.edges[0].verts
            cp0,cp1 = vp0.co,vp1.co
            def get(ep,ec):
                nonlocal cp0, cp1
                vc0,vc1 = ec.verts
                cc0,cc1 = vc0.co,vc1.co
                if (cp1-cp0).dot(cc1-cc0) < 0: cc0,cc1 = cc1,cc0
                cp0,cp1 = cc0,cc1
                return (ec,cc0,cc1)
            edge0 = self.edges[0]
            self.edges_ = [get(e0,e1) for e0,e1 in zip([self.edges[0]] + self.edges,self.edges)]
            c0,c1 = next((c0,c1) for e,c0,c1 in self.edges_ if e == self.nearest_edge)
            c0,c1 = self.rfcontext.Point_to_Point2D(c0),self.rfcontext.Point_to_Point2D(c1)
            a,b = c1 - c0, mouse_cur - c0
            self.percent = a.dot(b) / a.dot(a);
        
    def modal_main(self):
        self.set_next_state()
        
        if self.rfcontext.actions.pressed(['select', 'select add'], unpress=False):
            sel_only = self.rfcontext.actions.pressed('select')
            self.rfcontext.actions.unpress()
            
            if sel_only: self.rfcontext.undo_push('select')
            else: self.rfcontext.undo_push('select add')
            
            edges = self.rfcontext.visible_edges()
            edge,_ = self.rfcontext.nearest2D_edge(edges=edges, max_dist=10)
            if not edge:
                if sel_only: self.rfcontext.deselect_all()
                return
            self.rfcontext.select_edge_loop(edge, only=sel_only)
            self.update()
            return
        
        if self.rfcontext.actions.pressed('slide'):
            ''' slide edge loop or strip between neighboring edges '''
            return self.prep_slide()
        
        if self.rfcontext.actions.pressed('insert'):
            # insert edge loop / strip, select it, prep slide!
            if not self.edges_: return
            
            self.rfcontext.undo_push('insert edge %s' % ('loop' if self.edge_loop else 'strip'))
            
            new_verts = []
            new_edges = []
            # create new verts by splitting all the edges
            for e,c0,c1 in self.edges_:
                c = c0 + (c1 - c0) * self.percent
                ne,nv = e.split()
                nv.co = c
                self.rfcontext.snap_vert(nv)
                new_verts += [nv]
            # create new edges by connecting newly created verts and splitting faces
            for v0,v1 in iter_pairs(new_verts, self.edge_loop):
                f0 = v0.shared_faces(v1)[0]
                f1 = f0.split(v0, v1)
                new_edges += [f0.shared_edge(f1)]
            self.rfcontext.dirty()
            self.rfcontext.select(new_edges)
            return self.prep_slide()
        
        # if self.rfcontext.actions.pressed('action'):
        #     self.rfcontext.undo_push('relax')
        #     return 'relax'
        
        # if self.rfcontext.actions.pressed('relax selected'):
        #     self.rfcontext.undo_push('relax selected')
        #     self.sel_verts = self.rfcontext.get_selected_verts()
        #     self.selected = [(v,0.0) for v in self.sel_verts]
        #     self.sel_edges = self.rfcontext.get_selected_edges()
        #     self.sel_faces = self.rfcontext.get_selected_faces()
        #     return 'relax selected'
    
    def prep_slide(self):
        # make sure that the selected edges form an edge loop or strip
        # TODO: make this more sophisticated, allowing for two or more non-intersecting loops/strips to be slid
        
        sel_verts = self.rfcontext.get_selected_verts()
        sel_edges = self.rfcontext.get_selected_edges()
        
        def all_connected():
            touched = set()
            working = { next(iter(sel_verts)) }
            while working:
                cur = working.pop()
                if cur in touched: continue
                touched.add(cur)
                for e in cur.link_edges:
                    if e not in sel_edges: continue
                    v = e.other_vert(cur)
                    working.add(v)
            return len(touched) == len(sel_verts)
        
        if not sel_verts: return
        if not all_connected(): return
        
        # each selected edge should have two unselected faces
        # each selected vert should have exactly two unselected edges that act as neighbors
        neighbors = {}
        for bme in sel_edges:
            lbmf = [bmf for bmf in bme.link_faces if bmf.select == False]
            if len(lbmf) != 2:
                dprint('edge has %d!=2 unselected faces' % len(lbmf))
                return
            bmv0,bmv1 = bme.verts
            for bmv in bme.verts:
                for bmv_e in bmv.link_edges:
                    if bmv_e.select: continue
                    if any(bmv_e_f in lbmf for bmv_e_f in bmv_e.link_faces):
                        if bmv not in neighbors: neighbors[bmv] = set()
                        neighbors[bmv].add(bmv_e.other_vert(bmv))
        for bmv in neighbors:
            if len(neighbors[bmv]) != 2:
                dprint('vert has %d!=2 neighbors' % len(neighbors[bmv]))
                return
            neighbors[bmv] = list(neighbors[bmv])
        
        for bme in sel_edges:
            bmv0,bmv1 = bme.verts
            bmf0,bmf1 = bme.link_faces
            
            # if type(neighbors[bmv0]) is set:
            # ne0,ne1 = neighbors[bmv]
            # c,n = bmv.co,bmv.normal
            # c0,c1 = ne0.co,ne1.co
            # if n.dot()
        
        # give neighbors a "side"
        
        self.rfcontext.undo_push('slide edge loop/strip')
        dprint('good!')
        
        #sel_loops = find_loops(sel_edges)
        return
    
    def modal_slide(self):
        pass
    
    @profiler.profile
    def draw_postview(self):
        if self.rfcontext.nav: return
        #hit_pos = self.rfcontext.actions.hit_pos
        #if not hit_pos: return
        self.set_next_state()
        if not self.nearest_edge: return
        if self.rfcontext.actions.ctrl:
            # draw new edge strip/loop
            
            def draw():
                if not self.edges: return
                glEnableStipple(enable=True)
                if self.edge_loop:
                    bgl.glBegin(bgl.GL_LINE_LOOP)
                else:
                    bgl.glBegin(bgl.GL_LINE_STRIP)
                for _,c0,c1 in self.edges_:
                    c = c0 + (c1 - c0) * self.percent
                    bgl.glVertex3f(*c)
                bgl.glEnd()
                glEnableStipple(enable=False)
                
            
            self.drawing.point_size(5.0)
            self.drawing.line_width(2.0)
            bgl.glDisable(bgl.GL_CULL_FACE)
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glDepthMask(bgl.GL_FALSE)
            bgl.glDepthRange(0, 0.9990)     # squeeze depth just a bit 
            
            # draw above
            bgl.glEnable(bgl.GL_DEPTH_TEST)
            bgl.glDepthFunc(bgl.GL_LEQUAL)
            bgl.glColor4f(0.15, 1.00, 0.15, 1.00)
            draw()
            
            # draw below
            bgl.glDepthFunc(bgl.GL_GREATER)
            bgl.glColor4f(0.15, 1.00, 0.15, 0.25)
            draw()
            
            bgl.glEnable(bgl.GL_CULL_FACE)
            bgl.glDepthMask(bgl.GL_TRUE)
            bgl.glDepthFunc(bgl.GL_LEQUAL)
            bgl.glDepthRange(0, 1)
            
        
    # @RFTool.dirty_when_done
    # def modal_relax(self):
    #     if self.rfcontext.actions.released('action'):
    #         return 'main'
    #     if self.rfcontext.actions.pressed('cancel'):
    #         self.rfcontext.undo_cancel()
    #         return 'main'
        
    #     if not self.rfcontext.actions.timer: return
        
    #     hit_pos = self.rfcontext.actions.hit_pos
    #     if not hit_pos: return
        
    #     radius = self.rfwidget.get_scaled_radius()
    #     nearest = self.rfcontext.nearest_verts_point(hit_pos, radius)
    #     # collect data for smoothing
    #     verts,edges,faces,vert_dist = set(),set(),set(),dict()
    #     for bmv,d in nearest:
    #         verts.add(bmv)
    #         edges.update(bmv.link_edges)
    #         faces.update(bmv.link_faces)
    #         vert_dist[bmv] = self.rfwidget.get_strength_dist(d) #/radius
    #     self._relax(verts, edges, faces, vert_dist)
    
    # @RFTool.dirty_when_done
    # def modal_relax_selected(self):
    #     if self.rfcontext.actions.released('relax selected'):
    #         return 'main'
    #     if self.rfcontext.actions.pressed('cancel'):
    #         self.rfcontext.undo_cancel()
    #         return 'main'
    #     if not self.rfcontext.actions.timer: return
    #     self._relax(self.sel_verts, self.sel_edges, self.sel_faces)
    
    # def _relax(self, verts, edges, faces, vert_dist=None):
    #     if not verts or not edges: return
    #     vert_dist = vert_dist or {}
        
    #     time_delta = self.rfcontext.actions.time_delta
    #     strength = 100.0 * self.rfwidget.strength * time_delta
    #     radius = self.rfwidget.get_scaled_radius()
        
    #     # compute average edge length
    #     avgDist = sum(bme.calc_length() for bme in edges) / len(edges)
        
    #     # capture all verts involved in relaxing
    #     chk_verts = set(verts)
    #     chk_verts |= {bmv for bme in edges for bmv in bme.verts}
    #     chk_verts |= {bmv for bmf in faces for bmv in bmf.verts}
    #     divco = {bmv:Point(bmv.co) for bmv in chk_verts}
        
    #     # perform smoothing
    #     touched = set()
    #     for bmv0 in verts:
    #         d = vert_dist.get(bmv0, 0)
    #         lbme,lbmf = bmv0.link_edges,bmv0.link_faces
    #         if not lbme: continue
    #         # push edges closer to average edge length
    #         for bme in lbme:
    #             if bme not in edges: continue
    #             if bme in touched: continue
    #             touched.add(bme)
    #             bmv1 = bme.other_vert(bmv0)
    #             diff = bmv1.co - bmv0.co
    #             m = (avgDist - diff.length) * (1.0 - d) * 0.1
    #             divco[bmv1] += diff * m * strength
    #             divco[bmv0] -= diff * m * strength
    #         # attempt to "square" up the faces
    #         for bmf in lbmf:
    #             if bmf not in faces: continue
    #             if bmf in touched: continue
    #             touched.add(bmf)
    #             cnt = len(bmf.verts)
    #             ctr = sum([bmv.co for bmv in bmf.verts], Vec((0,0,0))) / cnt
    #             fd = sum((ctr-bmv.co).length for bmv in bmf.verts) / cnt
    #             for bmv in bmf.verts:
    #                 diff = (bmv.co - ctr)
    #                 m = (fd - diff.length)* (1.0- d) / cnt
    #                 divco[bmv] += diff * m * strength
        
    #     # update
    #     for bmv,co in divco.items():
    #         if bmv not in verts: continue
    #         if not self.move_boundary:
    #             if bmv in self.verts_nonmanifold: continue
    #         if not self.move_hidden:
    #             if not self.rfcontext.is_visible(bmv.co, bmv.normal): continue
    #         p,_,_,_ = self.rfcontext.nearest_sources_Point(co)
    #         bmv.co = p
