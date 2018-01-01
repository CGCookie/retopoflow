'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import bpy
import math
import random
import bgl
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec,Accel2D,Direction2D, clamp
from ..common.ui import UI_Image,UI_BoolValue,UI_Label
from ..lib.common_utilities import dprint
from ..lib.classes.profiler.profiler import profiler
from .rfmesh import RFVert, RFEdge, RFFace
from ..common.utils import iter_pairs
from ..options import help_loops

@RFTool.action_call('loops tool')
class RFTool_Loops(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['slide'] = self.modal_slide
        self.FSM['slide after select'] = self.modal_slide_after_select
    
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
        self.edges_ = None
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
        
        if not self.nearest_edge: return
        
        self.edges,self.edge_loop = self.rfcontext.get_face_loop(self.nearest_edge)
        if not self.edges:
            print('nearest, but no loop')
            return
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
        adota = a.dot(a)
        if adota <= 0.0000001:
            self.percent = 0
            self.edges = None
            return
        self.percent = a.dot(b) / adota;
        
    def modal_main(self):
        self.set_next_state()
        
        if self.rfcontext.actions.pressed('select', unpress=False):
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
            
            self.prep_edit()
            if not self.edit_ok: return
            return 'slide after select'
        
        if self.rfcontext.actions.pressed('slide'):
            ''' slide edge loop or strip between neighboring edges '''
            self.prep_edit()
            if not self.edit_ok: return
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            self.rfcontext.undo_push('slide edge loop/strip')
            return 'slide'
        
        if self.rfcontext.actions.pressed('insert'):
            # insert edge loop / strip, select it, prep slide!
            if not self.edges_: return
            
            self.rfcontext.undo_push('insert edge %s' % ('loop' if self.edge_loop else 'strip'))
            
            # if quad strip is a loop, then need to connect first and last new verts
            is_looped = self.rfcontext.is_quadstrip_looped(self.nearest_edge)
            
            def split_face(v0, v1):
                nonlocal new_edges
                f0 = next(iter(v0.shared_faces(v1)), None)
                if not f0:
                    self.rfcontext.alert_user('Loops', 'Something unexpected happened', level='warning')
                    self.rfcontext.undo_cancel()
                    return
                f1 = f0.split(v0, v1)
                new_edges.append(f0.shared_edge(f1))
            
            # create new verts by splitting all the edges
            new_verts, new_edges = [],[]
            for e,flipped in self.rfcontext.iter_quadstrip(self.nearest_edge):
                bmv0,bmv1 = e.verts
                if flipped: bmv0,bmv1 = bmv1,bmv0
                ne,nv = e.split()
                nv.co = bmv0.co + (bmv1.co - bmv0.co) * self.percent
                self.rfcontext.snap_vert(nv)
                if new_verts: split_face(new_verts[-1], nv)
                new_verts.append(nv)
            
            if is_looped and len(new_verts) > 2: split_face(new_verts[-1], new_verts[0])
            
            self.rfcontext.dirty()
            self.rfcontext.select(new_edges)
            
            self.prep_edit()
            if not self.edit_ok: return
            self.move_done_pressed = None
            self.move_done_released = ['insert', 'insert alt0']
            self.move_cancelled = 'cancel'
            self.rfcontext.undo_push('slide edge loop/strip')
            return 'slide'
        
        if self.rfcontext.actions.pressed('dissolve'):
            self.prep_edit()
            if not self.edit_ok: return
            self.rfcontext.undo_push('dissolve')
            # dissolve each key of neighbors into its right neighbor (arbitrarily chosen, but it's the right one!)
            for bmv in self.neighbors.keys():
                _,bmvr = self.neighbors[bmv]
                bmv.co = bmvr.co
                bme = bmv.shared_edge(bmvr)
                bmv = bme.collapse()
                self.rfcontext.clean_duplicate_bmedges(bmv)
            self.rfcontext.deselect_all()
            self.rfcontext.dirty()
        
        if self.rfcontext.actions.pressed('delete'):
            self.rfcontext.undo_push('delete')
            self.rfcontext.delete_selection()
            self.rfcontext.dirty()
            return
    
    def prep_edit(self):
        # make sure that the selected edges form an edge loop or strip
        # TODO: make this more sophisticated, allowing for two or more non-intersecting loops/strips to be slid
        
        self.edit_ok = False
        
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
                self.rfcontext.alert_user('Loops', 'A selected edge has %d unselected faces (expected 2)' % len(lbmf))
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
                self.rfcontext.alert_user('Loops', 'A vertex has %d neighbors (expected 2)' % len(neighbors[bmv]))
                return
            neighbors[bmv] = list(neighbors[bmv])
        
        # swap neighbors to place neighbors on corresponding sides
        bmv0 = next(iter(sel_verts))
        touched = set()
        working = { bmv0 }
        while working:
            bmv0 = working.pop()
            if bmv0 in touched: continue
            touched.add(bmv0)
            bmv0l,_ = neighbors[bmv0]
            bmfls = bmv0.shared_faces(bmv0l)
            for bmfl in bmfls:
                bmv1s = [bmv for bmv in bmfl.verts if bmv != bmv0 and bmv in neighbors]
                if len(bmv1s) != 1:
                    self.rfcontext.alert_user('Loops', 'Face has an unexpected count of valid candidates (%d)' % len(bmv1s))
                    return
                bmv1 = bmv1s[0]
                bmv1l,bmv1r = neighbors[bmv1]
                if bmv1l not in bmfl.verts:
                    # swap!
                    neighbors[bmv1] = [bmv1r,bmv1l]
                working.add(bmv1)
            
        nearest_sel_vert,_ = self.rfcontext.nearest2D_vert(verts=sel_verts)
        v0,v1 = neighbors[nearest_sel_vert]
        cc = self.rfcontext.Point_to_Point2D(nearest_sel_vert.co)
        c0,c1 = self.rfcontext.Point_to_Point2D(v0.co),self.rfcontext.Point_to_Point2D(v1.co)
        self.vector = c1 - c0
        self.tangent = Direction2D(self.vector)
        self.neighbors = neighbors
        self.mouse_down = self.rfcontext.actions.mouse
        a,b = c1 - c0, cc - c0
        self.percent_start = a.dot(b) / a.dot(a)
        self.edit_ok = True
    
    @profiler.profile
    def modal_slide_after_select(self):
        if self.rfcontext.actions.released(['select','select add']):
            return 'main'
        if (self.rfcontext.actions.mouse - self.mouse_down).length > 7:
            self.move_done_pressed = 'confirm'
            self.move_done_released = ['select']
            self.move_cancelled = 'cancel no select'
            self.rfcontext.undo_push('slide edge loop/strip')
            return 'slide'
    
    @RFTool.dirty_when_done
    @profiler.profile
    def modal_slide(self):
        released = self.rfcontext.actions.released
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            #self.defer_recomputing = False
            #self.mergeSnapped()
            return 'main'
        if self.move_done_released and all(released(item) for item in self.move_done_released):
            #self.defer_recomputing = False
            #self.mergeSnapped()
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            #self.defer_recomputing = False
            self.rfcontext.undo_cancel()
            return 'main'
        
        mouse_delta = self.rfcontext.actions.mouse - self.mouse_down
        a,b = self.vector, self.tangent.dot(mouse_delta) * self.tangent
        percent = clamp(self.percent_start + a.dot(b) / a.dot(a), 0, 1)
        for v in self.neighbors.keys():
            v0,v1 = self.neighbors[v]
            v.co = v0.co + (v1.co - v0.co) * percent
            self.rfcontext.snap_vert(v)
    
    @profiler.profile
    def draw_postview(self):
        if self.rfcontext.nav: return
        #hit_pos = self.rfcontext.actions.hit_pos
        #if not hit_pos: return
        self.set_next_state()
        if not self.nearest_edge: return
        if self.rfcontext.actions.ctrl and self.mode == 'main':
            # draw new edge strip/loop
            
            def draw():
                if not self.edges_: return
                self.drawing.enable_stipple()
                if self.edge_loop:
                    bgl.glBegin(bgl.GL_LINE_LOOP)
                else:
                    bgl.glBegin(bgl.GL_LINE_STRIP)
                for _,c0,c1 in self.edges_:
                    c = c0 + (c1 - c0) * self.percent
                    bgl.glVertex3f(*c)
                bgl.glEnd()
                self.drawing.disable_stipple()
            
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
            
