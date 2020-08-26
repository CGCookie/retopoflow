'''
Copyright (C) 2020 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import os
import math
from itertools import chain

import bpy
import bgl
from mathutils import Matrix

from ..rftool import RFTool, rftools

from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import max_index, iter_pairs
from ...addon_common.common.maths import Point,Point2D,Vec2D,Vec,Plane
from ...config.options import options

from .contours_utils import (
    Contours_Loop,
    find_loops, find_strings, find_parallel_loops,
    loop_plane, loop_length, string_length,
    edges_between_loops,
)

RFTool_Contours = rftools['RFTool_Contours']

class Contours_Ops:
    @RFTool_Contours.dirty_when_done
    def new_cut(self, ray, plane, count=None, walk_to_plane=True, check_hit=None, perform_nonmanifold_check=None):
        self.pts = []
        self.cut_pts = []
        self.cuts = []
        self.connected = False

        crawl = self.rfcontext.plane_intersection_crawl(ray, plane, walk_to_plane=walk_to_plane)
        if not crawl: return

        # get crawl data (over source)
        pts = [c for (f0,c,f1) in crawl]
        connected_preclip = crawl[0][0] is not None
        center = Point.average(pts)
        pts,connected = self.rfcontext.clip_pointloop(pts, connected_preclip)
        if not pts: return

        self.rfcontext.undo_push('cut')

        cl_cut = Contours_Loop(pts, connected)
        self.cuts = [cl_cut]
        self.cut_pts = pts
        self.connected = connected
        sel_edges = self.rfcontext.get_selected_edges()

        if check_hit:
            # if ray hits target, include the loops, too!
            visible_faces = self.rfcontext.visible_faces()
            hit_face,_ = self.rfcontext.nearest2D_face(point=check_hit, faces=visible_faces)
            if hit_face and hit_face.is_quad():
                # considering loops only at the moment
                edges = hit_face.edges
                eseqs = [self.rfcontext.get_quadwalk_edgesequence(edge) for edge in edges]
                eloops = [eseq.get_edges() if len(eseq) else None for eseq in eseqs]
                cloops = [Contours_Loop(eseq.get_verts(), eseq.is_loop()) if eseq else None for eseq in eseqs]

                # use loop that is most parallel to cut
                norm = cl_cut.plane.n
                idx0 = max_index([abs(norm.dot(cloop.plane.n)) if cloop else -1 for cloop in cloops])
                idx1 = (idx0 + 2) % 4
                sel_edges |= set(eloops[idx0]) | set(eloops[idx1])

        sel_loop_pos,sel_loop_neg = None,None
        sel_string_pos,sel_string_neg = None,None

        if connected:
            # find two closest selected loops, one on each side
            sel_loops = find_loops(sel_edges)
            # find loops running parallel to selection
            par_loops = [ploop for loop in sel_loops for ploop in find_parallel_loops(loop)]

            sel_loop_planes = [(loop, loop_plane(loop)) for loop in sel_loops]
            par_loop_planes = [(loop, loop_plane(loop)) for loop in par_loops]

            def get_closest(loop_planes, positive):
                nonlocal center, plane
                mult = 1 if positive else -1
                loops = sorted([
                    # loop, distance to loop, segment count of loop, loop circumference
                    #(loop, plane.distance_to(p.o), len(loop), loop_length(loop))
                    (loop, (loop_plane.o - center).length, len(loop), loop_length(loop))
                    for loop,loop_plane in loop_planes if plane.side(loop_plane.o)*mult > 0
                    ], key=lambda data:data[1])
                return next(iter(loops), None)
            # (loop, plane.distance_to(p.o), len(loop), loop_length(loop))
            # for loop,p in zip(sel_loops, sel_loop_planes) if plane.side(p.o) > 0

            sel_loop_pos = get_closest(sel_loop_planes, True)
            sel_loop_neg = get_closest(sel_loop_planes, False)
            par_loop_pos = get_closest(par_loop_planes, True)
            par_loop_neg = get_closest(par_loop_planes, False)

            # if we've got only one selected loop, see if any parallel loops are closer
            if sel_loop_pos and par_loop_pos:
                if par_loop_pos[1] < sel_loop_pos[1]:
                    sel_loop_pos = par_loop_pos
            if sel_loop_neg and par_loop_neg:
                if par_loop_neg[1] < sel_loop_neg[1]:
                    sel_loop_neg = par_loop_neg

            if sel_loop_pos and sel_loop_neg:
                if sel_loop_pos[2] != sel_loop_neg[2]:
                    # selected loops do not have same count of vertices
                    # choosing the closer loop
                    if sel_loop_pos[1] < sel_loop_neg[1]:
                        sel_loop_neg = None
                    else:
                        sel_loop_pos = None
        else:
            # find two closest selected strings, one on each side
            sel_strings = find_strings(sel_edges)
            parallel_strings = [pstring for string in sel_strings for pstring in find_parallel_loops(string, False)]
            sel_strings += parallel_strings

            sel_string_planes = [loop_plane(string) for string in sel_strings]
            sel_strings_pos = sorted([
                (string, plane.distance_to(p.o), len(string), string_length(string))
                for string,p in zip(sel_strings, sel_string_planes) if plane.side(p.o) > 0
                ], key=lambda data:data[1])
            sel_strings_neg = sorted([
                (string, plane.distance_to(p.o), len(string), string_length(string))
                for string,p in zip(sel_strings, sel_string_planes) if plane.side(p.o) < 0
                ], key=lambda data:data[1])
            sel_string_pos = next(iter(sel_strings_pos), None)
            sel_string_neg = next(iter(sel_strings_neg), None)
            if sel_string_pos and sel_string_neg:
                if sel_string_pos[2] != sel_string_neg[2]:
                    # selected strings do not have same count of vertices
                    # choosing the closer string
                    if sel_string_pos[1] < sel_string_neg[1]:
                        sel_string_neg = None
                    else:
                        sel_string_pos = None

        if not count:
            count = self._var_init_count.value
            if connected != connected_preclip:
                count = int(math.ceil(count / 2)) + 1
        #count = count or self.get_count()
        count = sel_loop_pos[2] if sel_loop_pos else sel_loop_neg[2] if sel_loop_neg else count
        count = sel_string_pos[2] if sel_string_pos else sel_string_neg[2] if sel_string_neg else count

        if count <= 2:
            # too few verts for a cut!  need at least 3
            # possible fix for issue #856
            return

        if connected:
            cl_pos = Contours_Loop(sel_loop_pos[0], True) if sel_loop_pos else None
            cl_neg = Contours_Loop(sel_loop_neg[0], True) if sel_loop_neg else None
        else:
            cl_pos = Contours_Loop(sel_string_pos[0], False) if sel_string_pos else None
            cl_neg = Contours_Loop(sel_string_neg[0], False) if sel_string_neg else None

        if cl_pos: self.cuts += [cl_pos]
        if cl_neg: self.cuts += [cl_neg]

        if connected:
            if cl_pos and cl_neg:
                verts0 = list(cl_pos.verts)
                verts1 = list(cl_neg.verts)
                v0 = verts0[0]
                offset = None
                for i,v1 in enumerate(verts1):
                    if v0.share_edge(v1): offset = i
                if offset is not None:
                    verts1 = verts1[offset:] + verts1[:offset]
                    if verts0[1].share_edge(verts1[-1]):
                        verts1 = [verts1[0]] + list(reversed(verts1[1:]))

                    new_edges = []
                    def split_face(v0, v1):
                        nonlocal new_edges
                        f0 = next(iter(v0.shared_faces(v1)), None)
                        if not f0:
                            self.rfcontext.alert_user('Something unexpected happened in trying to create a new cut', level='warning')
                            self.rfcontext.undo_cancel()
                            return
                        f1 = f0.split(v0, v1)
                        new_edges.append(f0.shared_edge(f1))

                    nvs = []
                    for v0,v2 in zip(verts0, verts1):
                        e1 = v0.shared_edge(v2)
                        assert e1
                        intersection = cl_cut.plane.line_intersection(v0.co, v2.co)
                        v0,v2 = e1.verts
                        e0,v1 = e1.split()
                        assert v0 in e0.verts
                        assert v2 in e1.verts
                        v1.co = intersection
                        self.rfcontext.snap_vert(v1)
                        nvs.append(v1)

                    for v0,v1 in iter_pairs(nvs, wrap=True):
                        split_face(v0, v1)

                    self.rfcontext.select(new_edges)
                    #self.update()

                    return

                cl_neg.align_to(cl_pos)
                cl_cut.align_to(cl_pos)
                if options['contours uniform']:
                    step_size = cl_cut.circumference / count
                    dists = [0] + [step_size for i in range(count-1)]
                else:
                    lc,lp,ln = cl_cut.circumference,cl_pos.circumference,cl_neg.circumference
                    dists = [0] + [lc * (d0/lp + d1/ln)/2 for d0,d1 in zip(cl_pos.dists,cl_neg.dists)]
                    dists = dists[:-1]
            elif cl_pos:
                cl_cut.align_to(cl_pos)
                if options['contours uniform']:
                    step_size = cl_cut.circumference / count
                    dists = [0] + [step_size for i in range(count-1)]
                else:
                    lc,lp = cl_cut.circumference,cl_pos.circumference
                    dists = [0] + [lc * (d/lp) for d in cl_pos.dists]
                    dists = dists[:-1]
            elif cl_neg:
                cl_cut.align_to(cl_neg)
                if options['contours uniform']:
                    step_size = cl_cut.circumference / count
                    dists = [0] + [step_size for i in range(count-1)]
                else:
                    lc,ln = cl_cut.circumference,cl_neg.circumference
                    dists = [0] + [lc * (d/ln) for d in cl_neg.dists]
                    dists = dists[:-1]
            else:
                step_size = cl_cut.circumference / count
                dists = [0] + [step_size for i in range(count-1)]
        else:
            if cl_pos and cl_neg:
                cl_neg.align_to(cl_pos)
                cl_cut.align_to(cl_pos)
                lc,lp,ln = cl_cut.circumference,cl_pos.circumference,cl_neg.circumference
                dists = [0] + [0.999 * lc * (d0/lp + d1/ln)/2 for d0,d1 in zip(cl_pos.dists,cl_neg.dists)]
            elif cl_pos:
                cl_cut.align_to(cl_pos)
                lc,lp = cl_cut.circumference,cl_pos.circumference
                dists = [0] + [0.999 * lc * (d/lp) for d in cl_pos.dists]
            elif cl_neg:
                cl_cut.align_to(cl_neg)
                lc,ln = cl_cut.circumference,cl_neg.circumference
                dists = [0] + [0.999 * lc * (d/ln) for d in cl_neg.dists]
            else:
                step_size = cl_cut.circumference / (count-1)
                dists = [0] + [0.999 * step_size for i in range(count-1)]
        dists[0] = cl_cut.offset

        # where new verts, edges, and faces are stored
        verts,edges,faces = [],[],[]

        if sel_loop_pos and sel_loop_neg:
            edges_between = edges_between_loops(sel_loop_pos[0], sel_loop_neg[0])
            self.rfcontext.delete_edges(edges_between)
        if sel_string_pos and sel_string_neg:
            edges_between = edges_between_loops(sel_string_pos[0], sel_string_neg[0])
            self.rfcontext.delete_edges(edges_between)

        i,dist = 0,dists[0]
        for c0,c1 in cl_cut.iter_pts(repeat=True):
            if c0 == c1: continue
            d = (c1 - c0).length
            while dist - d <= 0:
                # create new vert between c0 and c1
                p = c0 + (c1 - c0) * (dist / d)
                self.pts += [p]
                verts += [self.rfcontext.new_vert_point(p)]
                i += 1
                if i == len(dists): break
                dist += dists[i]
            dist -= d
            if i == len(dists): break
        assert len(dists)==len(verts), '%d != %d' % (len(dists), len(verts))
        for v0,v1 in iter_pairs(verts, connected):
            edges += [self.rfcontext.new_edge((v0, v1))]

        if cl_pos: self.rfcontext.bridge_vertloop(verts, cl_pos.verts, connected)
        if cl_neg: self.rfcontext.bridge_vertloop(verts, cl_neg.verts, connected)

        self.rfcontext.select(edges)

        if perform_nonmanifold_check is None or perform_nonmanifold_check:
            if options['contours non-manifold check'] and not connected and (verts[0].co - verts[-1].co).length < 0.01:
                self.rfcontext.alert_user('\n'.join([
                    'It seems the stroke has cut across a non-manifold edge in the source mesh.',
                    '',
                    '''<input type="checkbox" value="options['contours non-manifold check']">Perform this check</input>'''
                ]), level='warning')

    @RFTool_Contours.dirty_when_done
    def fill(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)

        if len(sel_loops) != 2:
            self.rfcontext.alert_user('In order to fill, select exactly 2 loops of the same edge count')
            return
        loop0, loop1 = sel_loops
        if len(loop0) != len(loop1):
            self.rfcontext.alert_user('In order to fill, select exactly 2 loops of the same edge count')
            return
        if any(v0.share_edge(v1) for v0 in loop0 for v1 in loop1):
            self.rfcontext.alert_user('In order to fill, the 2 selected loops cannot share an edge')
            return

        self.rfcontext.undo_push('fill')
        cl_pos = Contours_Loop(loop0, True)
        cl_neg = Contours_Loop(loop1, True)
        cl_neg.align_to(cl_pos)
        faces = self.rfcontext.bridge_vertloop(cl_neg.verts, cl_pos.verts, True)
        #self.dirty()
        #self.rfcontext.select(faces)

    @RFTool_Contours.dirty_when_done
    def change_count(self, *, count=None, delta=None):
        assert count is not None or delta is not None, 'Contours.change_count: Must specify either count or delta!'
        sel_edges = self.rfcontext.get_selected_edges()
        loops = find_loops(sel_edges)
        strings = find_strings(sel_edges)
        if len(loops) == 1 and len(strings) == 0:
            self._change_loop_count(loops[0], count=count, delta=delta)
        elif len(strings) == 1 and len(loops) == 0:
            self._change_string_count(strings[0], count=count, delta=delta)
        else:
            print('Contours.change_count: expected either 1 loop+0 strings or 1 string+0 loops, but found %d loops and %d strings' % (len(loops), len(strings)))

    def _change_loop_count(self, loop, *, count=None, delta=None):
        count_cur = len(loop)
        if count is not None: count_new = count
        else: count_new = count_cur + delta
        count_new = max(3, count_new)
        if count_cur == count_new: return
        if any(len(v.link_edges) != 2 for v in loop): return
        cl = Contours_Loop(loop, True)
        avg = Point.average(v.co for v in loop)
        plane = cl.plane
        ray = self.rfcontext.Point2D_to_Ray(self.rfcontext.Point_to_Point2D(avg))
        self.rfcontext.delete_edges(e for v in loop for e in v.link_edges)
        self.new_cut(ray, plane, walk_to_plane=True, count=count_new)

    def _change_string_count(self, string, *, count=None, delta=None):
        count_cur = len(string)
        if count is not None: count_new = count
        else: count_new = count_cur + delta
        count_new = max(3, count_new)
        if count_cur == count_new: return
        if any(len(v.link_edges) != 2 for v in string[1:-1]):
            print('Contours._change_string_count: string is connected to other geometry')
            return
        if any(len(v.link_edges) != 1 for v in string[:1] + string[-1:]):
            print('Contours._change_string_count: string is connected to other geometry')
            return
        cl = Contours_Loop(string, False)
        avg = Point.average(v.co for v in string)
        plane = cl.plane
        ray = self.rfcontext.Point2D_to_Ray(self.rfcontext.Point_to_Point2D(avg))
        self.rfcontext.delete_edges(e for v in string for e in v.link_edges)
        self.new_cut(ray, plane, walk_to_plane=True, count=count_new, perform_nonmanifold_check=False)




