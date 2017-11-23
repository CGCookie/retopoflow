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
import bgl
import blf
import os
import math
from itertools import chain
from .rftool import RFTool
from ..lib.common_utilities import showErrorMessage
from ..lib.classes.profiler.profiler import profiler
from ..common.utils import max_index
from ..common.maths import Point,Point2D,Vec2D,Vec,Plane
from ..common.ui import UI_Label, UI_IntValue, UI_Image
from .rftool_contours_utils import *
from mathutils import Matrix

class RFTool_Contours_Ops:
    def line(self):
        xy0,xy1 = self.rfwidget.line2D
        if (xy1-xy0).length < 0.001: return
        xy01 = xy0 + (xy1-xy0) / 2
        plane = self.rfcontext.Point2D_to_Plane(xy0, xy1)
        ray = self.rfcontext.Point2D_to_Ray(xy01)
        self.new_cut(ray, plane, walk=False, check_hit=xy01)
    
    def change_count(self, delta):
        sel_edges = self.rfcontext.get_selected_edges()
        loops = find_loops(sel_edges)
        if len(loops) != 1: return
        loop = loops[0]
        count = len(loop)
        count_new = max(3, count+delta)
        if count == count_new: return
        if any(len(v.link_edges) != 2 for v in loop): return
        cl = Contours_Loop(loop, True)
        avg = Point.average(v.co for v in loop)
        plane = cl.plane
        ray = self.rfcontext.Point2D_to_Ray(self.rfcontext.Point_to_Point2D(avg))
        self.rfcontext.delete_edges(e for v in loop for e in v.link_edges)
        self.new_cut(ray, plane, walk=True, count=count_new)
    
    @RFTool.dirty_when_done
    def new_cut(self, ray, plane, count=None, walk=True, check_hit=None):
        self.pts = []
        self.cut_pts = []
        self.cuts = []
        self.connected = False
        
        crawl = self.rfcontext.plane_intersection_crawl(ray, plane, walk=walk)
        if not crawl: return
        
        # get crawl data (over source)
        pts = [c for (f0,e,f1,c) in crawl]
        connected = crawl[0][0] is not None
        pts,connected = self.rfcontext.clip_pointloop(pts, connected)
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
            hit_face = self.rfcontext.nearest2D_face(point=check_hit, faces=visible_faces)
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
            sel_loop_planes = [loop_plane(loop) for loop in sel_loops]
            sel_loops_pos = sorted([
                (loop, plane.distance_to(p.o), len(loop), loop_length(loop))
                for loop,p in zip(sel_loops, sel_loop_planes) if plane.side(p.o) > 0
                ], key=lambda data:data[1])
            sel_loops_neg = sorted([
                (loop, plane.distance_to(p.o), len(loop), loop_length(loop))
                for loop,p in zip(sel_loops, sel_loop_planes) if plane.side(p.o) < 0
                ], key=lambda data:data[1])
            sel_loop_pos = next(iter(sel_loops_pos), None)
            sel_loop_neg = next(iter(sel_loops_neg), None)
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
        
        count = count or self.count
        count = sel_loop_pos[2] if sel_loop_pos else sel_loop_neg[2] if sel_loop_neg else count
        count = sel_string_pos[2] if sel_string_pos else sel_string_neg[2] if sel_string_neg else count
        
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
                cl_neg.align_to(cl_pos)
                cl_cut.align_to(cl_pos)
                lc,lp,ln = cl_cut.circumference,cl_pos.circumference,cl_neg.circumference
                dists = [0] + [lc * (d0/lp + d1/ln)/2 for d0,d1 in zip(cl_pos.dists,cl_neg.dists)]
                dists = dists[:-1]
            elif cl_pos:
                cl_cut.align_to(cl_pos)
                lc,lp = cl_cut.circumference,cl_pos.circumference
                dists = [0] + [lc * (d/lp) for d in cl_pos.dists]
                dists = dists[:-1]
            elif cl_neg:
                cl_cut.align_to(cl_neg)
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
            d = (c1-c0).length
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
        self.update()
    
    @RFTool.dirty_when_done
    def dissolve_loops(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        if not sel_loops: return
        
        self.rfcontext.undo_push('dissolve')
        while sel_loops:
            ploop = None
            for loop in sel_loops:
                sloop = set(loop)
                # find a parallel loop next to loop
                adj_verts = {e.other_vert(v) for v in loop for e in v.link_edges} - sloop
                adj_verts = {v for v in adj_verts if v.is_valid}
                parallel_edges = [e for v in adj_verts for e in v.link_edges if e.other_vert(v) in adj_verts]
                parallel_loops = find_loops(parallel_edges)
                if len(parallel_loops) != 2: continue
                ploop = parallel_loops[0]
                break
            if not ploop: break
            # merge loop into ploop
            eloop = [v0.shared_edge(v1) for v0,v1 in iter_pairs(loop, wrap=True)]
            self.rfcontext.deselect(loop)
            self.rfcontext.deselect(eloop)
            self.rfcontext.deselect([f for e in eloop for f in e.link_faces])
            v01 = {v0:next(v1 for v1 in ploop if v0.share_edge(v1)) for v0 in loop}
            edges = [v0.shared_edge(v1) for v0,v1 in v01.items()]
            self.rfcontext.delete_edges(edges)
            touched = set()
            for v0,v1 in v01.items():
                v1.merge(v0)
                touched.add(v1)
            for v in touched:
                self.rfcontext.clean_duplicate_bmedges(v)
            # remove dissolved loop
            sel_loops = [l for l in sel_loops if l != loop]
        
        self.update()


