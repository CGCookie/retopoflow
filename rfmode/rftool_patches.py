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
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.ui import UI_Image, UI_BoolValue, UI_Label
from ..options import options, help_patches
from ..lib.common_utilities import dprint


@RFTool.action_call('patches tool')
class RFTool_Patches(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        pass
    
    def name(self): return "Patches"
    def icon(self): return "rf_patches_icon"
    def description(self): return 'Patches'
    def helptext(self): return help_patches
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('default')
        self.update_tool_options()
    
    def get_ui_icon(self):
        self.ui_icon = UI_Image('patches_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    def modal_main(self):
        if self.rfcontext.actions.pressed({'select', 'select add'}, unpress=False):
            sel_only = self.rfcontext.actions.pressed('select')
            self.rfcontext.actions.unpress()
            
            if sel_only: self.rfcontext.undo_push('select')
            else: self.rfcontext.undo_push('select add')
            
            edges = self.rfcontext.visible_edges()
            edges = [edge for edge in edges if len(edge.link_faces) == 1]
            edge,_ = self.rfcontext.nearest2D_edge(edges=edges, max_dist=10)
            if not edge:
                self.rfcontext.deselect_all()
            else:
                self.rfcontext.select_inner_edge_loop(edge, supparts=False, only=sel_only)
        
        if self.rfcontext.actions.pressed('fill'):
            self.fill_patch()
    
    @RFTool.dirty_when_done
    def fill_patch(self):
        # get strips of edges.  an edge is in a strip if a linked face neighbors a linked face
        # of an edge in the strip
        
        remaining_edges = set(self.rfcontext.get_selected_edges())
        all_edges = set(remaining_edges)
        strips = []
        neighbors = {}
        while remaining_edges:
            strip = set()
            working = { next(iter(remaining_edges)) }
            while working:
                edge = working.pop()
                strip.add(edge)
                remaining_edges.remove(edge)
                if len(edge.link_faces) != 1:
                    self.rfcontext.alert_user('Patches', 'A selected edge is not on the boundary', level='note')
                    return
                v0,v1 = edge.verts
                face = next(iter(edge.link_faces))
                neighbors[edge] = []
                for adj_edge in face.edges:
                    if adj_edge == edge: continue
                    if v0 not in adj_edge.verts and v1 not in adj_edge.verts: continue
                    neighbor_face = next((f for f in adj_edge.link_faces if f != face), None)
                    if not neighbor_face: continue
                    next_edge = next((e for e in neighbor_face.edges if e in all_edges), None)
                    if not next_edge: continue
                    neighbors[edge] += [next_edge]
                    if next_edge not in remaining_edges: continue
                    working.add(next_edge)
            strips += [strip]
        
        def order_edge_strip(edges):
            nonlocal neighbors
            if len(edges) == 1: return list(edges)
            l = [next(e for e in edges if len(neighbors[e])==1)]
            l += [neighbors[l[0]][0]]
            while True:
                l0,l1 = l[-2],l[-1]
                if len(neighbors[l1]) == 1: break
                edge = next((e for e in neighbors[l1] if e != l0), None)
                if not self.rfcontext.alert_assert(edge, throw=False):
                    # should not ever reach here!
                    break
                l += [edge]
            #assert len(l) == len(edges)
            return l
        strips = [order_edge_strip(edges) for edges in strips]
        
        def touching_strips(strip0, strip1):
            # do the strips share a vert?
            e00,e01 = strip0[0],strip0[-1]
            e10,e11 = strip1[0],strip1[-1]
            v0 = set(e00.verts) | set(e01.verts)
            v1 = set(e10.verts) | set(e11.verts)
            return len(v0 & v1) > 0
        def strip_vector(strip):
            if len(strip) == 1:
                v0,v1 = strip[0].verts
            else:
                e0,e1 = strip[0],strip[1]
                v0 = e0.other_vert(e0.shared_vert(e1))
                e0,e1 = strip[-1],strip[-2]
                v1 = e0.other_vert(e0.shared_vert(e1))
            return v1.co - v0.co
        def get_verts(strip, rev):
            if len(strip) == 1:
                l = list(strip[0].verts)
                if rev: l.reverse()
            else:
                l = [e0.shared_vert(e1) for e0,e1 in zip(strip[:-1],strip[1:])]
                l = [strip[0].other_vert(l[0])] + l + [strip[-1].other_vert(l[-1])]
            #if start_verts and l[0] not in start_verts: l.reverse()
            return l
        def make_strips_L(strip0, strip1):
            # possibly reverse strip0 and/or strip1 so strip0[0] and strip1[0] share a vertex, forming L
            if   strip0[0].shared_vert(strip1[0]): pass             # no need to reverse strips
            elif strip0[-1].shared_vert(strip1[0]): strip0.reverse()
            elif strip0[0].shared_vert(strip1[-1]): strip1.reverse()
            else:
                strip0.reverse()
                strip1.reverse()
            rev0 = strip0[0].verts[0] not in strip1[0].verts
            rev1 = strip1[0].verts[0] not in strip0[0].verts
            return (rev0,rev1)
        def align_strips(strip0, strip1, rev):
            if strip_vector(strip0).dot(strip_vector(strip1)) < 0:
                strip1.reverse()
                rev = not rev
            return rev
        
        # TODO: ensure that sides have appropriate counts!
        
        self.rfcontext.undo_push('patch')
        
        dprint('len(strips) = %d' % len(strips))
        
        if len(strips) == 2:
            s0,s1 = strips
            if touching_strips(s0,s1):
                # L-shaped
                rev0,rev1 = make_strips_L(s0, s1)
                
                def duplicate_strip(strip, from_bmv, rev, to_bmv=None):
                    lverts = get_verts(strip, rev)
                    nstrip = []
                    pairs = zip(lverts[:-1],lverts[1:]) if not to_bmv else zip(lverts[:-2],lverts[1:-1])
                    for v10,v11 in pairs:
                        diff = v11.co - v10.co
                        nv = self.rfcontext.new_vert_point(from_bmv.co + diff)
                        ne = self.rfcontext.new_edge([from_bmv,nv])
                        nstrip += [ne]
                        from_bmv = nv
                    if to_bmv:
                        nv = to_bmv
                        ne = self.rfcontext.new_edge([from_bmv,nv])
                        nstrip += [ne]
                    return (nstrip,nv)
                
                # generate other 2 sides, creating a rectangle that is filled below
                lv0,lv1 = get_verts(s0, rev0),get_verts(s1, rev1)
                v01,v11 = lv0[-1],lv1[-1]
                s2,last_bmv = duplicate_strip(s0, v11, rev0)
                s3,last_bmv = duplicate_strip(s1, v01, rev1, to_bmv=last_bmv)
                strips += [s2, s3]
            else:
                # ||-shaped
                self.rfcontext.alert_user('Patches', '||-shaped selections not yet handled', level='note')
                self.rfcontext.undo_cancel()
        
        if len(strips) == 3:
            s0,s1,s2 = strips
            t01,t02,t12 = touching_strips(s0,s1),touching_strips(s0,s2),touching_strips(s1,s2)
            if t01 and t02 and t12:
                self.rfcontext.alert_user('Patches', 'Triangle selections not yet handled', level='note')
                self.rfcontext.undo_cancel()
            elif t01 and t02 and not t12:
                self.rfcontext.alert_user('Patches', 'C-shaped selections not yet handled', level='note')
                self.rfcontext.undo_cancel()
            elif t01 and t12 and not t02:
                self.rfcontext.alert_user('Patches', 'C-shaped selections not yet handled', level='note')
                self.rfcontext.undo_cancel()
            elif t02 and t12 and not t01:
                self.rfcontext.alert_user('Patches', 'C-shaped selections not yet handled', level='note')
                self.rfcontext.undo_cancel()
            else:
                self.rfcontext.alert_user('Patches', 'Unhandled shape of three selected strips', level='warning')
                self.rfcontext.undo_cancel()
            return
        
        if len(strips) == 4:
            s0,s1,s2,s3 = strips
            t01,t02,t03 = touching_strips(s0,s1),touching_strips(s0,s2),touching_strips(s0,s3)
            t12,t13,t23 = touching_strips(s1,s2),touching_strips(s1,s3),touching_strips(s2,s3)
            ct = sum(1 if t else 0 for t in [t01,t02,t03,t12,t13,t23])
            if ct != 4:
                self.rfcontext.alert_user('Patches', 'Unhandled shape of four selected strips', level='warning')
                dprint('unhandled len(strips) == 4, ct = %d' % ct)
                self.rfcontext.undo_cancel()
                return
            
            # rectangle
            
            # permute strips so they are in the following configuration
            # note: don't know rotation order, yet; may be flipped, but s0/s2 and s1/s3 are opposite
            #       s1
            #     V----V
            #  s0 |    | s2
            #     V----V
            #       s3
            if   not t01: s0,s1,s2,s3 = s0,s2,s1,s3
            elif not t02: s0,s1,s2,s3 = s0,s1,s2,s3
            elif not t03: s0,s1,s2,s3 = s0,s1,s3,s2
            
            # ensure counts are same!
            if len(s0) != len(s2) or len(s1) != len(s3):
                self.rfcontext.alert_user('Patches', 'Opposite strips must have same edge count', level='warning')
                self.rfcontext.undo_cancel()
                return
            
            rev0,rev1 = make_strips_L(s0, s1)   # ensure that s0[0] and s1[0] share a vertex
            rev2 = align_strips(s0, s2, rev0)    # align s2 to s0
            rev3 = align_strips(s1, s3, rev1)    # align s3 to s1
            
            # construct new points
            lv0,lv1,lv2,lv3 = get_verts(s0,rev0),get_verts(s1,rev1),get_verts(s2,rev2),get_verts(s3,rev3)
            pts = {}
            for i in range(0,len(s0)+1):
                v0,v2 = lv0[i],lv2[i]
                for j in range(0,len(s1)+1):
                    v1,v3 = lv1[j],lv3[j]
                    if   i == 0:       pts[(i,j)] = v1
                    elif i == len(s0): pts[(i,j)] = v3
                    elif j == 0:       pts[(i,j)] = v0
                    elif j == len(s1): pts[(i,j)] = v2
                    else:
                        pi,pj = i / len(s0),j / len(s1)
                        pti = v0.co + (v2.co - v0.co) * pj
                        ptj = v1.co + (v3.co - v1.co) * pi
                        pt = pti + (ptj - pti) * 0.5
                        pts[(i,j)] = self.rfcontext.new_vert_point(pt)
            
            # construct new faces
            for i0 in range(0,len(s0)):
                i1 = i0 + 1
                for j0 in range(0,len(s1)):
                    j1 = j0 + 1
                    verts = [pts[(i0,j0)], pts[(i1,j0)], pts[(i1,j1)], pts[(i0,j1)]]
                    self.rfcontext.new_face(verts)
            return
        
        self.rfcontext.alert_user('Patches', 'Unhandled strip count', level='warning')
        dprint('unhandled len(strips) == %d' % len(strips))
        self.rfcontext.undo_cancel()
        return
        
    
    def draw_postview(self): pass
    def draw_postpixel(self): pass
    
