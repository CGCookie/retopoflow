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

import math
from itertools import chain

import bgl
import bpy
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_point_tri_2d

from .rftool import RFTool

from ..common.debug import dprint
from ..common.profiler import profiler
from ..common.logger import Logger
from ..common.maths import (
    Point, Vec, Direction,
    Point2D, Vec2D,
    Accel2D,
    clamp, mid,
)
from ..common.bezier import CubicBezierSpline, CubicBezier
from ..common.shaders import circleShader, edgeShortenShader, arrowShader
from ..common.utils import iter_pairs, iter_running_sum, min_index, max_index
from ..common.ui import (
    UI_Image, UI_IntValue, UI_BoolValue,
    UI_Button, UI_Label,
    UI_Container, UI_EqualContainer
    )
from ..keymaps import default_rf_keymaps
from ..options import options, themes
from ..help import help_patches


@RFTool.action_call('patches tool')
class RFTool_Patches(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['selectadd/deselect'] = self.modal_selectadd_deselect
        self.FSM['select'] = self.modal_select
        self._clear_shapes()
        self.FSM['move']   = self.modal_move
        # self.FSM['rotate'] = self.modal_rotate
        # self.FSM['scale']  = self.modal_scale

    def name(self): return "Patches"
    def icon(self): return "rf_patches_icon"
    def description(self): return 'Patches'
    def helptext(self): return help_patches
    def get_label(self): return 'Patches (%s)' % ','.join(default_rf_keymaps['patches tool'])
    def get_tooltip(self): return 'Patches (%s)' % ','.join(default_rf_keymaps['patches tool'])

    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('default')
        self.crosses = None

    def get_ui_icon(self):
        self.ui_icon = UI_Image('patches_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon

    def get_ui_options(self):
        def get_crosses():
            return (getattr(self, 'crosses', None) or 1) - 1
        def set_crosses(v):
            nv = max(2, int(v+1))
            if self.crosses == nv: return
            self.crosses = nv
            self.recompute()
        def get_angle():
            return options['patches angle']
        def set_angle(v):
            v = mid(int(v), 0, 180)
            if options['patches angle'] == v: return
            options['patches angle'] = v
            self.update()
        self.ui_crosses = UI_IntValue('Crosses', get_crosses, set_crosses)
        return [
            UI_IntValue('Angle', get_angle, set_angle, tooltip='A vertex between connected edges that form an angles below this threshold is a corner'),
            self.ui_crosses,
        ]

    def update_ui(self):
        self.ui_crosses.visible = getattr(self, 'crosses', None) is not None

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
            'corners': [],
        }
        self.previz = []

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
            - I-shaped  (find two parallel I-shaped strips ||)
            - L-shaped
            - C-shaped
            - other     <- not handled

        note: could visualize the found patch regions?
        '''

        self.crosses = None
        self.recompute()
        self.update_ui()


    def recompute(self):
        min_angle = options['patches angle']
        nearest_sources_Point = self.rfcontext.nearest_sources_Point

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
                for e in chain(v0.link_edges, v1.link_edges):
                    if e not in remaining_edges: continue
                    bmv1 = edge.shared_vert(e)
                    bmv0 = edge.other_vert(bmv1)
                    bmv2 = e.other_vert(bmv1)
                    d10 = Direction(bmv0.co-bmv1.co)
                    d12 = Direction(bmv2.co-bmv1.co)
                    angle = math.degrees(math.acos(mid(-1,1,d10.dot(d12))))
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
                isbad = False
                while remaining_edges:
                    next_edges = [edge for edge in neighbors[strip[-1]] if edge in remaining_edges]
                    if len(next_edges) != 1:
                        # unexpected number of edges found!
                        isbad = True
                        break
                    strip.append(next_edges[0])
                    remaining_edges.remove(next_edges[0])
                if isbad: continue
                self.shapes['O'].append(strip)
                continue
            strip = [end_edges[0]]
            remaining_edges = set(edges) - set(strip)
            isbad = False
            while remaining_edges:
                next_edges = [edge for edge in neighbors[strip[-1]] if edge in remaining_edges]
                if len(next_edges) != 1:
                    # unexpected number of edges found
                    # see GitHub issue #481 (https://github.com/CGCookie/retopoflow/issues/481)
                    isbad = True
                    break
                strip.append(next_edges[0])
                remaining_edges.remove(next_edges[0])
            if isbad: continue
            v0 = strip[0].other_vert(strip[0].shared_vert(strip[1]))
            v1 = strip[-1].other_vert(strip[-1].shared_vert(strip[-2]))
            corners[v0] = corners.get(v0, []) + [strip]
            corners[v1] = corners.get(v1, []) + [strip]
            nstrips.append(strip)
        strips = nstrips


        ##################################################################
        # find all strings (I,L,C,else) and loops (cat,tri,rect,ngon)
        # note: all corner verts with one strip are *not* in a loop

        # ignore corners with 3+ strips
        ignore_corners = {c for c in corners if len(corners[c]) > 2}

        def align_strips(strips):
            ''' make sure that the edges at the end of adjacent strips share a vertex '''
            if len(strips) == 1: return strips
            strip0,strip1 = strips[:2]
            if strip0[0].share_vert(strip1[0]) or strip0[0].share_vert(strip1[-1]): strip0.reverse()
            assert strip0[-1].share_vert(strip1[0]) or strip0[-1].share_vert(strip1[-1])
            for strip0,strip1 in zip(strips[:-1],strips[1:]):
                if strip1[-1].share_vert(strip0[-1]): strip1.reverse()
                assert strip1[0].share_vert(strip0[-1])
            return strips

        remaining_corners = set(corners.keys())
        string_corners = set()
        loop_corners = set()
        strings_strips = list()
        loops_strips = list(self.shapes['O'])

        # find strips
        while remaining_corners:
            c = next((c for c in remaining_corners if len(corners[c]) == 1), None)
            if not c: break
            remaining_corners.remove(c)
            string_corners.add(c)
            string_strips = [corners[c][0]]
            ignore = c in ignore_corners
            while True:
                s = string_strips[-1]
                c = next((c for c in remaining_corners if s in corners[c]), None)
                if not c: break
                ignore |= c in ignore_corners
                remaining_corners.remove(c)
                string_corners.add(c)
                if len(corners[c]) != 2: break
                ns = next(ns for ns in corners[c] if ns != s)
                string_strips.append(ns)
            string_strips = align_strips(string_strips)
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

        # find loops
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
            loop_strips = align_strips(loop_strips)
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

        self.shapes['corners'] = list(string_corners | loop_corners)

        ###################
        # generate previz

        def get_verts(strip, rev=False):
            if len(strip) == 1: return list(strip[0].verts)
            bmvs = [strip[0].nonshared_vert(strip[1])]
            bmvs += [e0.shared_vert(e1) for e0,e1 in zip(strip[:-1], strip[1:])]
            bmvs += [strip[-1].nonshared_vert(strip[-2])]
            if rev: bmvs.reverse()
            return bmvs

        # rect
        for shape in self.shapes['rect']:
            s0,s1,s2,s3 = shape
            if len(s0) != len(s2) or len(s1) != len(s3): continue   # invalid rect
            sv0,sv1,sv2,sv3 = get_verts(s0),get_verts(s1),get_verts(s2,True),get_verts(s3,True)
            l0,l1 = len(sv0),len(sv1)

            # single edge strips: edge may be "facing" the wrong way
            if l0==2 and sv0[1] not in sv1: sv0.reverse()
            if l1==2 and sv1[0] not in sv0: sv1.reverse()
            if l0==2 and sv2[0] not in sv1: sv2.reverse()
            if l1==2 and sv3[0] not in sv2: sv3.reverse()

            verts,edges,faces = [],[],[]
            for i in range(l0):
                l,r = sv0[i],sv2[i]
                for j in range(l1):
                    t,b = sv1[j],sv3[j]
                    if   i == 0:    verts += [b]
                    elif i == l0-1: verts += [t]
                    elif j == 0:    verts += [l]
                    elif j == l1-1: verts += [r]
                    else:
                        pi,pj = i / (l0-1), j / (l1-1)
                        lr = Vec(l.co)*(1-pj) + Vec(r.co)*pj
                        tb = Vec(b.co)*(1-pi) + Vec(t.co)*pi
                        verts += [nearest_sources_Point((lr+tb)/2.0)[0]]
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(1,l0-1) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1,l1-1) for i in range(l0-1)]
            faces += [( (i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1) ) for i in range(l0-1) for j in range(l1-1)]

            self.previz += [{ 'type': 'rect', 'data': shape, 'verts': verts, 'edges': edges, 'faces': faces }]

        for shape in self.shapes['L']:
            s0,s1 = shape
            sv0,sv1 = get_verts(s0),get_verts(s1)
            l0,l1 = len(sv0),len(sv1)

            # single edge strips: edge may be "facing" the wrong way
            if l0==2 and sv0[1] not in sv1: sv0.reverse()
            if l1==2 and sv1[0] not in sv0: sv1.reverse()

            off0,off1 = sv0[-1].co-sv0[0].co, sv1[-1].co-sv1[0].co

            verts,edges,faces = [],[],[]
            for i in range(l0):
                for j in range(l1):
                    if   i == l0-1: verts += [sv1[j]]
                    elif j == 0:    verts += [sv0[i]]
                    else:
                        l,r = sv0[i].co,sv0[i].co+off1
                        t,b = sv1[j].co,sv1[j].co-off0
                        pi,pj = i / (l0-1), j / (l1-1)
                        lr = Vec(l)*(1-pj) + Vec(r)*pj
                        tb = Vec(b)*(1-pi) + Vec(t)*pi
                        verts += [nearest_sources_Point((lr+tb)/2.0)[0]]
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(l0-1) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1,l1) for i in range(l0-1)]
            faces += [( (i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1) ) for i in range(l0-1) for j in range(l1-1)]

            self.previz += [{ 'type': 'L', 'data': shape, 'verts': verts, 'edges': edges, 'faces': faces }]

        for shape in self.shapes['C']:
            s0,s1,s2 = shape
            if len(s0) != len(s2): continue     # invalid C-shape
            sv0,sv1,sv2 = get_verts(s0),get_verts(s1),get_verts(s2,True)
            l0,l1 = len(sv0),len(sv1)

            # single edge strips: edge may be "facing" the wrong way
            if l0==2 and sv0[1] not in sv1: sv0.reverse()
            if l1==2 and sv1[0] not in sv0: sv1.reverse()
            if l0==2 and sv2[-1] not in sv1: sv2.reverse()

            off0,off2 = sv0[0].co-sv0[-1].co, sv2[0].co-sv2[-1].co

            verts,edges,faces = [],[],[]
            for i in range(l0):
                for j in range(l1):
                    if   i == l0-1: verts += [sv1[j]]
                    elif j == 0:    verts += [sv0[i]]
                    elif j == l1-1: verts += [sv2[i]]
                    else:
                        pi,pj = i / (l0-1), j / (l1-1)
                        off = off0*(1-pj)+off2*pj
                        l,r = sv0[i].co,sv2[i].co
                        t,b = sv1[j].co,sv1[j].co+off
                        lr = Vec(l)*(1-pj) + Vec(r)*pj
                        tb = Vec(b)*(1-pi) + Vec(t)*pi
                        verts += [nearest_sources_Point((lr+tb)/2.0)[0]]
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(l0-1) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1,l1-1) for i in range(l0-1)]
            faces += [( (i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1) ) for i in range(l0-1) for j in range(l1-1)]

            self.previz += [{ 'type': 'C', 'data': shape, 'verts': verts, 'edges': edges, 'faces': faces }]

        # TODO: check sides to make sure that we aren't creating geometry
        #       on a side that already has geometry!
        for i0,shape0 in enumerate(self.shapes['I']):
            sv0 = get_verts(shape0[0])
            dir0 = Direction(sv0[0].co-sv0[-1].co)
            best_sv1,best_dist = None,0
            for i1,shape1 in enumerate(self.shapes['I']):
                if i1 <= i0: continue
                sv1 = get_verts(shape1[0])
                dir1 = Direction(sv1[0].co-sv1[-1].co)
                if len(sv0) != len(sv1): continue
                if dir0.dot(dir1) < 0:
                    sv1 = list(reversed(sv1))
                    dir1.reverse()
                if math.degrees(dir0.angleBetween(dir1)) > 45: continue     # make sure strips are parallel enough
                if math.degrees(dir0.angleBetween(Direction(sv1[0].co-sv0[0].co))) < 45: continue
                if math.degrees(dir1.angleBetween(Direction(sv0[0].co-sv1[0].co))) < 45: continue
                dist = min((v0.co-v1.co).length for v0 in sv0 for v1 in sv1)
                if best_sv1 and best_dist < dist: continue
                best_sv1 = sv1
                best_dist = dist
            if not best_sv1: continue
            sv1,dist = best_sv1,best_dist
            avg0 = (sv0[0].co-sv0[-1].co).length / (len(sv0)-1)
            avg1 = (sv1[0].co-sv1[-1].co).length / (len(sv1)-1)

            l0 = len(sv0)
            if getattr(self, 'crosses', None) is None:
                self.crosses = max(2, math.floor(dist / max(avg0,avg1)))
            l1 = self.crosses

            verts,edges,faces = [],[],[]
            for i in range(l0):
                for j in range(l1):
                    if   j == 0:    verts += [sv0[i]]
                    elif j == l1-1: verts += [sv1[i]]
                    else:
                        pi,pj = i / (l0-1), j / (l1-1)
                        l,r = sv0[i].co,sv1[i].co
                        lr = Vec(l)*(1-pj) + Vec(r)*pj
                        verts += [nearest_sources_Point(lr)[0]]
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(l0) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1,l1-1) for i in range(l0-1)]
            faces += [( (i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1) ) for i in range(l0-1) for j in range(l1-1)]

            self.previz += [{ 'type': 'I', 'data': shape0, 'verts': verts, 'edges': edges, 'faces': faces }]


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
            selectable_edges = [e for e in self.rfcontext.visible_edges() if e.is_boundary]
            edge,_ = self.rfcontext.nearest2D_edge(edges=selectable_edges, max_dist=10)
            if not edge: return
            self.rfcontext.select_inner_edge_loop(edge, supparts=False, only=sel_only)

        if self.rfcontext.actions.pressed('fill'):
            self.fill_patch()

        if self.rfcontext.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move'

        if self.rfcontext.actions.pressed('increase count'):
            if self.crosses is not None:
                self.crosses += 1
                self.recompute()

        if self.rfcontext.actions.pressed('decrease count'):
            if self.crosses is not None and self.crosses > 2:
                self.crosses -= 1
                self.recompute()


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


    @profiler.profile
    def prep_move(self, bmverts=None, defer_recomputing=True):
        self.sel_verts = self.rfcontext.get_selected_verts()
        self.vis_accel = self.rfcontext.get_vis_accel()
        self.vis_verts = self.rfcontext.accel_vis_verts
        Point_to_Point2D = self.rfcontext.Point_to_Point2D

        if not bmverts: bmverts = self.sel_verts
        self.bmverts = [(bmv, Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.vis_bmverts = [(bmv, Point_to_Point2D(bmv.co)) for bmv in self.vis_verts if bmv and bmv not in self.sel_verts]
        self.mousedown = self.rfcontext.actions.mouse
        self.defer_recomputing = defer_recomputing

    @RFTool.dirty_when_done
    @profiler.profile
    def modal_move(self):
        released = self.rfcontext.actions.released
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            self.defer_recomputing = False
            self.update()
            #self.mergeSnapped()
            return 'main'
        if self.move_done_released and all(released(item) for item in self.move_done_released):
            self.defer_recomputing = False
            self.update()
            #self.mergeSnapped()
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.defer_recomputing = False
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            xy_updated = xy + delta
            # check if xy_updated is "close" to any visible verts (in image plane)
            # if so, snap xy_updated to vert position (in image plane)
            if options['polypen automerge']:
                for bmv1,xy1 in self.vis_bmverts:
                    if (xy_updated - xy1).length < self.rfcontext.drawing.scale(10):
                        set2D_vert(bmv, xy1)
                        break
                else:
                    set2D_vert(bmv, xy_updated)
            else:
                set2D_vert(bmv, xy_updated)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)

    @RFTool.dirty_when_done
    def fill_patch(self):
        if not self.previz: return

        new_vert = self.rfcontext.new_vert_point
        new_face = self.rfcontext.new_face

        self.rfcontext.undo_push('fill')
        for previz in self.previz:
            verts,faces = previz['verts'],previz['faces']
            verts = [(new_vert(v) if type(v) is Point else v) for v in verts]
            for face in faces: new_face([verts[iv] for iv in face])

        self.update()

    def draw_previz(self, previz, poly_alpha=0.2):
        point_to_point2D = self.rfcontext.Point_to_Point2D
        line_color = themes['new']
        poly_color = [line_color[0], line_color[1], line_color[2], line_color[3] * poly_alpha]

        verts = [point_to_point2D(v if type(v) is Point else v.co) for v in previz['verts']]

        bgl.glColor4f(*line_color)
        bgl.glBegin(bgl.GL_LINES)
        for i0,i1 in previz['edges']:
            bgl.glVertex2f(*verts[i0])
            bgl.glVertex2f(*verts[i1])
        bgl.glEnd()

        bgl.glColor4f(*poly_color)
        bgl.glBegin(bgl.GL_TRIANGLES)
        for f in previz['faces']:
            co0 = verts[f[0]]
            for i1,i2 in zip(f[1:-1],f[2:]):
                bgl.glVertex2f(*co0)
                bgl.glVertex2f(*verts[i1])
                bgl.glVertex2f(*verts[i2])
        bgl.glEnd()

    def draw_postpixel(self):
        point_to_point2D = self.rfcontext.Point_to_Point2D
        self.rfcontext.drawing.set_font_size(12)

        def get_pos(strips):
            #xy = max((point_to_point2D(bmv.co) for strip in strips for bme in strip for bmv in bme.verts), key=lambda xy:xy.y+xy.x/2)
            bmvs = [bmv for strip in strips for bme in strip for bmv in bme.verts]
            vs = [point_to_point2D(bmv.co) for bmv in bmvs]
            vs = [Vec2D(v) for v in vs if v]
            if not vs: return None
            xy = sum(vs, Vec2D((0,0))) / len(vs)
            return xy+Vec2D((2,14))
        def text_draw2D(s, strips):
            if not strips: return
            xy = get_pos(strips)
            if not xy: return
            self.rfcontext.drawing.text_draw2D(s, xy, (1,1,0,1), dropshadow=(0,0,0,0.5))

        for rect_strips in self.shapes['rect']:
            c0,c1,c2,c3 = map(len, rect_strips)
            if c0==c2 and c1==c3:
                s = 'rect: %dx%d' % (c0,c1)
                text_draw2D(s, rect_strips)
            else:
                for strip in rect_strips:
                    s = 'bad rect: %d' % len(strip)
                    text_draw2D(s, [strip])

        for I_strips in self.shapes['I']:
            c = len(I_strips[0])
            s = 'I: %d' % (c,)
            text_draw2D(s, I_strips)
        for L_strips in self.shapes['L']:
            c0,c1 = map(len, L_strips)
            s = 'L: %dx%d' % (c0,c1)
            text_draw2D(s, L_strips)
        for C_strips in self.shapes['C']:
            c0,c1,c2 = map(len, C_strips)
            if c0==c2:
                s = 'C: %dx%d' % (c0,c1)
                text_draw2D(s, C_strips)
            else:
                for strip in C_strips:
                    s = 'bad C: %d' % len(strip)
                    text_draw2D(s, [strip])

        self.drawing.enable_stipple()
        self.drawing.line_width(2.0)
        self.drawing.point_size(4.0)
        bgl.glEnable(bgl.GL_BLEND)

        for previz in self.previz: self.draw_previz(previz)

        self.drawing.disable_stipple()

        self.drawing.point_size(6.0)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glColor4f(1,1,0.1,1.0)
        bgl.glBegin(bgl.GL_POINTS)
        for corner in self.shapes['corners']:
            bgl.glVertex2f(*point_to_point2D(corner.co))
        bgl.glEnd()
