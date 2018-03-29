'''
Copyright (C) 2018 CG Cookie
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
from ..help import help_loops
from .rfcontext_actions import Actions

@RFTool.action_call('loops tool')
class RFTool_Loops(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['selectadd/deselect'] = self.modal_selectadd_deselect
        self.FSM['select'] = self.modal_select
        self.FSM['slide'] = self.modal_slide
        self.FSM['slide after select'] = self.modal_slide_after_select
    
    def name(self): return "Loops"
    def icon(self): return "rf_loops_icon"
    def description(self): return 'Loops creation, shifting, and deletion'
    def helptext(self): return help_loops
    def get_tooltip(self): return 'Loops (%s)' % ','.join(Actions.default_keymap['loops tool'])
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('default')
        
        self.nearest_edge = None
    
    def get_ui_icon(self):
        self.ui_icon = UI_Image('loops_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    @profiler.profile
    def update(self):
        # selection has changed, undo/redo was called, etc.
        pass
    
    @profiler.profile
    def set_next_state(self):
        self.edges_ = None
        
        self.nearest_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
        
        self.percent = 0
        self.edges = None
        
        if not self.nearest_edge: return
        
        self.edges,self.edge_loop = self.rfcontext.get_face_loop(self.nearest_edge)
        if not self.edges:
            # nearest, but no loop
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
        a,b = c1 - c0, self.rfcontext.actions.mouse - c0
        adota = a.dot(a)
        if adota <= 0.0000001:
            self.percent = 0
            self.edges = None
            return
        self.percent = a.dot(b) / adota;
        
    def modal_main(self):
        self.set_next_state()
        
        if self.rfcontext.actions.pressed('action'):
            self.rfcontext.undo_push('select and grab')
            edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if not edge:
                if sel_only: self.rfcontext.deselect_all()
                return
            self.rfcontext.select_edge_loop(edge, supparts=False, only=True)
            self.set_next_state()
            self.prep_edit()
            if not self.edit_ok: return
            return 'slide after select'
        
        if self.rfcontext.actions.pressed(['select smart', 'select smart add'], unpress=False):
            sel_only = self.rfcontext.actions.pressed('select smart')
            self.rfcontext.actions.unpress()
            self.rfcontext.undo_push('select smart')
            edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if not edge:
                if sel_only: self.rfcontext.deselect_all()
                return
            self.rfcontext.select_edge_loop(edge, supparts=False, only=sel_only)
            return
        
        if self.rfcontext.actions.pressed('select add'):
            edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if not edge: return
            if edge.select:
                self.mousedown = self.rfcontext.actions.mouse
                return 'selectadd/deselect'
            return 'select'
        
        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('select')
            self.rfcontext.deselect_all()
            return 'select'
        
        if self.rfcontext.actions.pressed('slide'):
            ''' slide edge loop or strip between neighboring edges '''
            self.rfcontext.undo_push('slide edge loop/strip')
            self.prep_edit()
            if not self.edit_ok:
                self.rfcontext.undo_cancel()
                return
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
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
            
            def compute_percent():
                v0,v1 = self.nearest_edge.verts
                c0,c1 = self.rfcontext.Point_to_Point2D(v0.co),self.rfcontext.Point_to_Point2D(v1.co)
                a,b = c1 - c0, self.rfcontext.actions.mouse - c0
                adota = a.dot(a)
                if adota <= 0.0000001: return 0
                return a.dot(b) / adota;
            percent = compute_percent()
            
            for e,flipped in self.rfcontext.iter_quadstrip(self.nearest_edge):
                bmv0,bmv1 = e.verts
                if flipped: bmv0,bmv1 = bmv1,bmv0
                ne,nv = e.split()
                nv.co = bmv0.co + (bmv1.co - bmv0.co) * percent
                self.rfcontext.snap_vert(nv)
                if new_verts: split_face(new_verts[-1], nv)
                new_verts.append(nv)
            
            # connecting first and last new verts if quad strip is looped
            if is_looped and len(new_verts) > 2: split_face(new_verts[-1], new_verts[0])
            
            self.rfcontext.dirty()
            self.rfcontext.select(new_edges)
            
            self.prep_edit()
            if not self.edit_ok:
                self.rfcontext.undo_cancel()
                return
            self.move_done_pressed = None
            self.move_done_released = ['insert', 'insert alt0']
            self.move_cancelled = 'cancel'
            self.rfcontext.undo_push('slide edge loop/strip')
            return 'slide'
    
    @profiler.profile
    def modal_selectadd_deselect(self):
        if not self.rfcontext.actions.using(['select','select add']):
            self.rfcontext.undo_push('deselect')
            edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if edge and edge.select: self.rfcontext.deselect(edge)
            return 'main'
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        if delta.length > self.drawing.scale(5):
            self.rfcontext.undo_push('select add')
            return 'select'

    @profiler.profile
    def modal_select(self):
        if not self.rfcontext.actions.using(['select','select add']):
            return 'main'
        bme,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
        if not bme or bme.select: return
        self.rfcontext.select(bme, supparts=False, only=False)
    
    def prep_edit(self):
        self.edit_ok = False
        
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        
        sel_verts = self.rfcontext.get_selected_verts()
        sel_edges = self.rfcontext.get_selected_edges()
        
        # slide_data holds info on left,right vectors for moving
        slide_data = {}
        working = set(sel_edges)
        while working:
            nearest_edge,_ = self.rfcontext.nearest2D_edge(edges=working)
            crawl_set = { (nearest_edge, 1) }
            while crawl_set:
                bme,side = crawl_set.pop()
                v0,v1 = bme.verts
                co0,co1 = v0.co,v1.co
                if bme not in working: continue
                working.discard(bme)
                
                # add verts of edge if not already added
                for bmv in bme.verts:
                    if bmv in slide_data: continue
                    slide_data[bmv] = { 'left':[], 'orig':bmv.co, 'right':[], 'other':set() }
                
                # process edge
                bmfl,bmfr = bme.get_left_right_link_faces()
                bmefln = bmfl.neighbor_edges(bme) if bmfl else None
                bmefrn = bmfr.neighbor_edges(bme) if bmfr else None
                bmel0,bmel1 = bmefln or (None, None)
                bmer0,bmer1 = bmefrn or (None, None)
                bmvl0 = bmel0.other_vert(v0) if bmel0 else None
                bmvl1 = bmel1.other_vert(v1) if bmel1 else None
                bmvr0 = bmer1.other_vert(v0) if bmer1 else None
                bmvr1 = bmer0.other_vert(v1) if bmer0 else None
                col0 = bmvl0.co if bmvl0 else None
                col1 = bmvl1.co if bmvl1 else None
                cor0 = bmvr0.co if bmvr0 else None
                cor1 = bmvr1.co if bmvr1 else None
                if col0 and cor0: pass              # found left and right sides!
                elif col0: cor0 = co0 + (co0 - col0)  # cor0 is missing, guess
                elif cor0: col0 = co0 + (co0 - cor0)  # col0 is missing, guess
                else:                               # both col0 and cor0 are missing
                    # use edge perpendicular and length to guess at col0 and cor0
                    #assert False, "XXX: Not implemented yet!"
                    continue
                if col1 and cor1: pass              # found left and right sides!
                elif col1: cor1 = co1 + (co1 - col1)  # cor1 is missing, guess
                elif cor1: col1 = co1 + (co1 - cor1)  # col1 is missing, guess
                else:                               # both col1 and cor1 are missing
                    # use edge perpendicular and length to guess at col1 and cor1
                    #assert False, "XXX: Not implemented yet!"
                    continue
                if side < 0:
                    # edge direction is reversed, so swap left and right sides
                    col0,cor0 = cor0,col0
                    col1,cor1 = cor1,col1
                if bmvl0 not in slide_data[v0]['other']:
                    slide_data[v0]['left'].append(col0-co0)
                    slide_data[v0]['other'].add(bmvl0)
                if bmvr0 not in slide_data[v0]['other']:
                    slide_data[v0]['right'].append(co0-cor0)
                    slide_data[v0]['other'].add(bmvr0)
                if bmvl1 not in slide_data[v1]['other']:
                    slide_data[v1]['left'].append(col1-co1)
                    slide_data[v1]['other'].add(bmvl1)
                if bmvr1 not in slide_data[v1]['other']:
                    slide_data[v1]['right'].append(co1-cor1)
                    slide_data[v1]['other'].add(bmvr1)
                
                # crawl to neighboring edges in strip/loop
                bmes_next = { bme.get_next_edge_in_strip(bmv) for bmv in bme.verts }
                for bme_next in bmes_next:
                    if bme_next not in working: continue    # note: None will skipped, too
                    v0_next,v1_next = bme_next.verts
                    side_next = side * (1 if (v1 == v0_next or v0 == v1_next) else -1)
                    crawl_set.add((bme_next, side_next))
        
        # find nearest selected edge
        #   vector is perpendicular to edge
        #   tangent is vector with unit length
        nearest_edge,_ = self.rfcontext.nearest2D_edge(edges=sel_edges)
        if not nearest_edge: return
        bmv0,bmv1 = nearest_edge.verts
        co0,co1 = self.rfcontext.Point_to_Point2D(bmv0.co),self.rfcontext.Point_to_Point2D(bmv1.co)
        diff = co1 - co0
        self.tangent = Direction2D((-diff.y, diff.x))
        self.vector = self.tangent * self.drawing.scale(40)
        self.slide_data = slide_data
        self.mouse_down = self.rfcontext.actions.mouse
        self.percent_start = 0.0
        self.edit_ok = True
    
    @profiler.profile
    def modal_slide_after_select(self):
        if self.rfcontext.actions.released('action'):
            return 'main'
        if (self.rfcontext.actions.mouse - self.mouse_down).length > self.drawing.scale(7):
            self.move_done_pressed = None
            self.move_done_released = 'action' #['select','select add','select smart']
            self.move_cancelled = 'cancel'
            self.rfcontext.undo_push('slide edge loop/strip')
            return 'slide'
    
    @RFTool.dirty_when_done
    @profiler.profile
    def modal_slide(self):
        released = self.rfcontext.actions.released
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'
        
        mouse_delta = self.rfcontext.actions.mouse - self.mouse_down
        a,b = self.vector, self.tangent.dot(mouse_delta) * self.tangent
        percent = clamp(self.percent_start + a.dot(b) / a.dot(a), -1, 1)
        for bmv in self.slide_data.keys():
            vecs = self.slide_data[bmv]['left' if percent > 0 else 'right']
            co = self.slide_data[bmv]['orig']
            delta = sum((v*percent for v in vecs), Vec((0,0,0))) / len(vecs)
            bmv.co = co + delta
            self.rfcontext.snap_vert(bmv)
    
    @profiler.profile
    def draw_postview(self):
        if self.rfcontext.nav: return
        if not self.nearest_edge: return
        if self.rfcontext.actions.ctrl and not self.rfcontext.actions.shift and self.mode == 'main':
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
            
