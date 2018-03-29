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
from itertools import chain
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec,Direction, mid
from ..common.ui import UI_Image, UI_BoolValue, UI_Label
from ..options import options
from ..help import help_patches
from ..lib.common_utilities import dprint
from .rfcontext_actions import Actions
from ..lib.classes.profiler.profiler import profiler
from ..common.ui import (
    UI_Image, UI_IntValue, UI_BoolValue,
    UI_Button, UI_Label,
    UI_Container, UI_EqualContainer
    )


@RFTool.action_call('patches tool')
class RFTool_Patches(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['selectadd/deselect'] = self.modal_selectadd_deselect
        self.FSM['select'] = self.modal_select
        self._clear_shapes()
    
    def name(self): return "Patches"
    def icon(self): return "rf_patches_icon"
    def description(self): return 'Patches'
    def helptext(self): return help_patches
    def get_tooltip(self): return 'Patches (%s)' % ','.join(Actions.default_keymap['patches tool'])
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('default')
    
    def get_ui_icon(self):
        self.ui_icon = UI_Image('patches_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    def get_angle(self): return options['patches angle']
    def set_angle(self, v):
        options['patches angle'] = mid(0, 180, int(v))
        self.update()
    def get_ui_options(self):
        return [
            UI_IntValue('Angle', self.get_angle, self.set_angle, tooltip='Minimum angle for edges to be in same strip'),
            ]
    
    def _clear_shapes(self):
        self.shapes = {
            'O':    [],     # special loop
            'eye':  [],     # loops
            'tri':  [],
            'rect': [],
            'ngon': [],
            'C':    [],     # strings
            'L':    [],
            'I':    [],
            'else': [],
        }
    
    def update(self):
        '''
        1. filter selected edges to those with no more than 1 link_face
        2. given filtered selected edges, find all of the strips
        3. order edges in strips to find corners and O-shapes
            - O-shaped  <- not handled
        4. find all of the loops (patch regions)
            - cat-eye   <- not handled
            - triangle  <- not handled
            - rectangle
            - n-gon     <- not handled
        5. given remaining strips (not in a loop), find all potential patch regions
            - I-shaped  (find two parallel I-shaped strips)
            - L-shaped
            - C-shaped
            - other     <- not handled
        
        note: could visualize the found patch regions?
        '''
        
        min_angle = self.get_angle()
        
        self._clear_shapes()
        
        ##############################################
        # find edges that could be part of a strip
        edges = set(e for e in self.rfcontext.get_selected_edges() if len(e.link_faces) <= 1)
        
        ###################
        # find strips
        remaining_edges = set(edges)
        strips = []
        neighbors = { e:[] for e in edges }
        while remaining_edges:
            strip = set()
            working = { next(iter(remaining_edges)) }
            while working:
                edge = working.pop()
                strip.add(edge)
                remaining_edges.remove(edge)
                v0,v1 = edge.verts
                face = next(iter(edge.link_faces), None)
                for e in chain(v0.link_edges, v1.link_edges):
                    if e not in remaining_edges: continue
                    f = next(iter(e.link_faces), None)
                    if face:
                        if not f: continue
                        if face == f: continue
                        if not face.share_edge(f): continue
                    else:
                        if f: continue
                        bmv1 = edge.shared_vert(e)
                        bmv0 = edge.other_vert(bmv1)
                        bmv2 = e.other_vert(bmv1)
                        d10 = Direction(bmv0.co-bmv1.co)
                        d12 = Direction(bmv2.co-bmv1.co)
                        angle = math.degrees(math.acos(d10.dot(d12)))
                        if angle < min_angle: continue
                    neighbors[edge].append(e)
                    neighbors[e].append(edge)
                    working.add(e)
            strips += [strip]
        
        ##############################################
        # order strips to find corners and O-shapes
        nstrips = []
        corners = dict()
        for edges in strips:
            if len(edges) == 1:
                # single edge in strip
                edge = next(iter(edges))
                strip = [edge]
                v0,v1 = edge.verts
                nstrips.append(strip)
                corners[v0] = corners.get(v0, []) + [strip]
                corners[v1] = corners.get(v1, []) + [strip]
                continue
            end_edges = [edge for edge in edges if len(neighbors[edge])==1]
            if not end_edges:
                # could not find corners: O-shaped!
                strip = [next(iter(edges))]
                strip.append(next(iter(neighbors[strip[0]])))
                remaining_edges = set(edges) - set(strip)
                while remaining_edges:
                    next_edges = [edge for edge in neighbors[strip[-1]] if edge in remaining_edges]
                    assert len(next_edges) == 1
                    strip.append(next_edges[0])
                    remaining_edges.remove(next_edges[0])
                self.shapes['O'].append(strip)
                continue
            strip = [end_edges[0]]
            remaining_edges = set(edges) - set(strip)
            while remaining_edges:
                next_edges = [edge for edge in neighbors[strip[-1]] if edge in remaining_edges]
                assert len(next_edges) == 1
                strip.append(next_edges[0])
                remaining_edges.remove(next_edges[0])
            v0 = strip[0].other_vert(strip[0].shared_vert(strip[1]))
            v1 = strip[-1].other_vert(strip[-1].shared_vert(strip[-2]))
            corners[v0] = corners.get(v0, []) + [strip]
            corners[v1] = corners.get(v1, []) + [strip]
            nstrips.append(strip)
        strips = nstrips
        
        ##################################
        # ignore corners with 3+ strips
        ignore_corners = {c for c in corners if len(corners[c]) > 2}
        
        ##################################################################
        # find all strings (I,L,C,else) and loops (cat,tri,rect,ngon)
        # note: all corner verts with one strip are *not* in a loop
        remaining_corners = set(corners.keys())
        string_corners = set()
        loop_corners = set()
        strings_strips = list()
        loops_strips = list(self.shapes['O'])
        while remaining_corners:
            c = next((c for c in remaining_corners if len(corners[c]) == 1), None)
            if not c: break
            remaining_corners.remove(c)
            string_corners.add(c)
            string_strips = [corners[c][0]]
            ignore = c in ignore_corners
            while True:
                s = string_strips[-1]
                c = next(c for c in remaining_corners if s in corners[c])
                ignore |= c in ignore_corners
                remaining_corners.remove(c)
                string_corners.add(c)
                if len(corners[c]) != 2: break
                ns = next(ns for ns in corners[c] if ns != s)
                string_strips.append(ns)
            if ignore: continue
            strings_strips.append(string_strips)
            if len(string_strips) == 1:
                self.shapes['I'].append(string_strips)
            elif len(string_strips) == 2:
                self.shapes['L'].append(string_strips)
            elif len(string_strips) == 3:
                self.shapes['C'].append(string_strips)
            else:
                self.shapes['else'].append(string_strips)
        while remaining_corners:
            c = next(iter(remaining_corners))
            remaining_corners.remove(c)
            loop_corners.add(c)
            loop_strips = [corners[c][0]]
            ignore = c in ignore_corners
            while True:
                s = loop_strips[-1]
                c = next((c for c in remaining_corners if s in corners[c]), None)
                if not c: break
                ignore |= c in ignore_corners
                remaining_corners.remove(c)
                loop_corners.add(c)
                ns = next((ns for ns in corners[c] if ns != s), None)
                if not ns: break
                loop_strips.append(ns)
            if ignore: continue
            # make sure loop is actually closed
            s0,s1 = loop_strips[0],loop_strips[-1]
            shared_verts = sum(1 if e0.share_vert(e1) else 0 for e0 in s0 for e1 in s1)
            if len(loop_strips) == 2 and shared_verts != 2: continue
            if len(loop_strips) > 2 and shared_verts != 1: continue
            loops_strips.append(loop_strips)
            if len(loop_strips) == 2:
                self.shapes['eye'].append(loop_strips)
            elif len(loop_strips) == 3:
                self.shapes['tri'].append(loop_strips)
            elif len(loop_strips) == 4:
                self.shapes['rect'].append(loop_strips)
            else:
                self.shapes['ngon'].append(loop_strips)
        
        if False:
            print('')
            print('patches info:')
            print('  %d edges' % len(edges))
            print('  %d strips' % len(strips))
            print('  %d corners' % len(corners))
            print('  %d string corners' % len(string_corners))
            print('  %d loop corners' % len(loop_corners))
            print('  %d strings' % len(strings_strips))
            print('  %d loops' % len(loops_strips))
            for d,k in [('loop','O'),('loop','eye'),('loop','tri'),('loop','rect'),('loop','ngon'),('string','I'),('string','L'),('string','C'),('string','else')]:
                print('  %d %s-shaped %s' % (len(self.shapes[k]), k, d))
    
    def modal_main(self):
        if self.rfcontext.actions.using('select'):
            self.rfcontext.undo_push('select')
            self.rfcontext.deselect_all()
            return 'select'
        
        if self.rfcontext.actions.using('select add'):
            edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if not edge: return
            if edge.select:
                self.mousedown = self.rfcontext.actions.mouse
                return 'selectadd/deselect'
            return 'select'
        
        if self.rfcontext.actions.pressed({'select smart', 'select smart add'}, unpress=False):
            sel_only = self.rfcontext.actions.pressed('select smart')
            self.rfcontext.actions.unpress()
            
            self.rfcontext.undo_push('select smart')
            selectable_edges = [e for e in self.rfcontext.visible_edges() if len(e.link_faces)<=1]
            edge,_ = self.rfcontext.nearest2D_edge(edges=selectable_edges, max_dist=10)
            if not edge: return
            self.rfcontext.select_inner_edge_loop(edge, supparts=False, only=sel_only)
        
        if self.rfcontext.actions.pressed('fill'):
            self.fill_patch()
    
    @profiler.profile
    def modal_selectadd_deselect(self):
        if not self.rfcontext.actions.using(['select','select add']):
            self.rfcontext.undo_push('deselect')
            bme,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if bme and bme.select: self.rfcontext.deselect(bme)
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
                    self.rfcontext.alert_user('Patches', 'A selected edge is not on the boundary')
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
            e_first = next((e for e in edges if len(neighbors[e])==1), None)
            if not e_first:
                # could not find corner (selection is a loop?)
                return None
            l = [e_first, neighbors[e_first][0]]
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
        if any(strip is None for strip in strips):
            self.rfcontext.alert_user('Patches', 'Cannot fill loops, yet')
            return
        
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
        def create_strip(v0, v1, count):
            nstrip = []
            pt0,vec10 = v0.co, v1.co - v0.co
            for i in range(count-1):
                p = (i+1) / count
                nv = self.rfcontext.new_vert_point(pt0 + vec10 * p)
                ne = self.rfcontext.new_edge([v0, nv])
                nstrip += [ne]
                v0 = nv
            ne = self.rfcontext.new_edge([v0, v1])
            nstrip += [ne]
            return nstrip
        
        # TODO: ensure that sides have appropriate counts!
        
        self.rfcontext.undo_push('patch')
        
        dprint('len(strips) = %d' % len(strips))
        
        if len(strips) == 2:
            s0,s1 = strips
            if touching_strips(s0,s1):
                # L-shaped
                rev0,rev1 = make_strips_L(s0, s1)
                # generate other 2 sides, creating a rectangle that is filled below
                lv0,lv1 = get_verts(s0, rev0),get_verts(s1, rev1)
                v01,v11 = lv0[-1],lv1[-1]
                s2,last_bmv = duplicate_strip(s0, v11, rev0)
                s3,last_bmv = duplicate_strip(s1, v01, rev1, to_bmv=last_bmv)
                strips += [s2, s3]
            else:
                # ||-shaped
                # ensure counts are same!
                if len(s0) != len(s1):
                    self.rfcontext.alert_user('Patches', 'Opposite strips must have same edge count', level='warning')
                    self.rfcontext.undo_cancel()
                    return
                # generate connecting 2 sides, creating a rectangle that is filled below
                rev1 = align_strips(s0, s1, False)
                lv0,lv1 = get_verts(s0,False),get_verts(s1,rev1)
                v00,v01,v10,v11 = lv0[0],lv0[-1],lv1[0],lv1[-1]
                d23 = ((v10.co - v00.co).length + (v11.co - v01.co).length) / 2
                d01 = ((v01.co - v00.co).length + (v11.co - v10.co).length) / 2
                count = max(1, round(d23 * len(s0) / d01))
                dprint('count = %d' % count)
                s2 = create_strip(v00, v10, count)
                s3 = create_strip(v01, v11, count)
                strips += [s2, s3]
                #self.rfcontext.alert_user('Patches', '||-shaped selections not yet handled')
                #self.rfcontext.undo_cancel()
        
        if len(strips) == 3:
            s0,s1,s2 = strips
            t01,t02,t12 = touching_strips(s0,s1),touching_strips(s0,s2),touching_strips(s1,s2)
            if t01 and t02 and t12:
                self.rfcontext.alert_user('Patches', 'Triangle selections not yet handled')
                self.rfcontext.undo_cancel()
            elif t01 and t02 and not t12:
                self.rfcontext.alert_user('Patches', 'C-shaped selections not yet handled')
                self.rfcontext.undo_cancel()
            elif t01 and t12 and not t02:
                self.rfcontext.alert_user('Patches', 'C-shaped selections not yet handled')
                self.rfcontext.undo_cancel()
            elif t02 and t12 and not t01:
                self.rfcontext.alert_user('Patches', 'C-shaped selections not yet handled')
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
    
    def draw_postpixel(self):
        point_to_point2d = self.rfcontext.Point_to_Point2D
        up = self.rfcontext.Vec_up()
        size_to_size2D = self.rfcontext.size_to_size2D
        text_draw2D = self.rfcontext.drawing.text_draw2D
        self.rfcontext.drawing.text_size(12)
        
        def get_pos(strips):
            xy = max((point_to_point2d(bmv.co) for strip in strips for bme in strip for bmv in bme.verts), key=lambda xy:xy.y+xy.x/2)
            return xy+Vec2D((2,14))
        
        for rect_strips in self.shapes['rect']:
            c0,c1,c2,c3 = map(len, rect_strips)
            if c0==c2 and c1==c3: s = 'rect: %dx%d' % (c0,c1)
            else: s = 'rect: bad (%d,%d,%d,%d)' % (c0,c1,c2,c3)
            text_draw2D(s, get_pos(rect_strips), (1,1,0,1), dropshadow=(0,0,0,0.5))
        
        for I_strips in self.shapes['I']:
            c = len(I_strips[0])
            s = 'I: %d' % (c,)
            text_draw2D(s, get_pos(I_strips), (1,1,0,1), dropshadow=(0,0,0,0.5))
        for L_strips in self.shapes['L']:
            c0,c1 = map(len, L_strips)
            s = 'L: %dx%d' % (c0,c1)
            text_draw2D(s, get_pos(L_strips), (1,1,0,1), dropshadow=(0,0,0,0.5))
        for C_strips in self.shapes['C']:
            c0,c1,c2 = map(len, C_strips)
            if c0==c2: s = 'C: %dx%d' % (c0,c1)
            else: s = 'C: bad (%d,%d,%d)' % (c0,c1,c2)
            text_draw2D(s, get_pos(C_strips), (1,1,0,1), dropshadow=(0,0,0,0.5))

