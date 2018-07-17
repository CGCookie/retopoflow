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

import bgl
import bpy
import math
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_line_2d
from .rftool import RFTool
from ..common.debug import dprint
from ..common.maths import Point,Point2D,Vec2D,Vec, Normal, clamp
from ..common.bezier import CubicBezierSpline, CubicBezier
from ..common.utils import iter_pairs


def process_stroke_filter(stroke, min_distance=1.0, max_distance=2.0):
    ''' filter stroke to pts that are at least min_distance apart '''
    nstroke = stroke[:1]
    for p in stroke[1:]:
        v = p - nstroke[-1]
        l = v.length
        if l < min_distance: continue
        d = v / l
        while l > 0:
            q = nstroke[-1] + d * min(l, max_distance)
            nstroke.append(q)
            l -= max_distance
    return nstroke

def process_stroke_source(stroke, raycast, is_point_on_mirrored_side):
    ''' filter out pts that don't hit source on non-mirrored side '''
    pts = [(pt, raycast(pt)[0]) for pt in stroke]
    return [pt for pt,p3d in pts if p3d and not is_point_on_mirrored_side(p3d)]

def find_edge_cycles(edges):
    edges = set(edges)
    verts = {v: set() for e in edges for v in e.verts}
    for e in edges:
        for v in e.verts:
            verts[v].add(e)
    in_cycle = set()
    for vstart in verts:
        if vstart in in_cycle: continue
        for estart in vstart.link_edges:
            if estart not in edges: continue
            if estart in in_cycle: continue
            q = [(estart, vstart, None)]
            found = None
            trace = {}
            while q:
                ec, vc, ep = q.pop(0)
                if ec in trace: continue
                trace[ec] = (vc, ep)
                vn = ec.other_vert(vc)
                if vn == vstart:
                    found = ec
                    break
                q += [(en, vn, ec) for en in vn.link_edges if en in edges]
            if not found: continue
            l = [found]
            in_cycle.add(found)
            while True:
                vn, ep = trace[l[-1]]
                in_cycle.add(vn)
                in_cycle.add(ep)
                if vn == vstart: break
                l.append(ep)
            yield l

def find_edge_strips(edges):
    ''' find edge strips '''
    edges = set(edges)
    verts = {v: set() for e in edges for v in e.verts}
    for e in edges:
        for v in e.verts:
            verts[v].add(e)
    ends = [v for v in verts if len(verts[v]) == 1]
    def get_edge_sequence(v0, v1):
        trace = {}
        q = [(None, v0)]
        while q:
            vf,vt = q.pop(0)
            if vt in trace: continue
            trace[vt] = vf
            if vt == v1: break
            for e in verts[vt]:
                q.append((vt, e.other_vert(vt)))
        if v1 not in trace: return []
        l = []
        while v1 is not None:
            l.append(v1)
            v1 = trace[v1]
        l.reverse()
        return [v0.shared_edge(v1) for (v0, v1) in iter_pairs(l, wrap=False)]
    for i0 in range(len(ends)):
        for i1 in range(i0+1,len(ends)):
            l = get_edge_sequence(ends[i0], ends[i1])
            if l: yield l

def get_strip_verts(edge_strip):
    l = len(edge_strip)
    if l == 0: return []
    if l == 1: return edge_strip[0].verts
    vs = []
    for e0, e1 in iter_pairs(edge_strip, wrap=False):
        vs.append(e0.shared_vert(e1))
    vs = [edge_strip[0].other_vert(vs[0])] + vs + [edge_strip[-1].other_vert(vs[-1])]
    return vs


def restroke(stroke, percentages):
    lens = [(s0 - s1).length for (s0, s1) in iter_pairs(stroke, wrap=False)]
    total_len = sum(lens)
    stops = [max(0, min(1, p)) * total_len for p in percentages]
    dist = 0
    istroke = 0
    istop = 0
    nstroke = []
    while istroke + 1 < len(stroke) and istop < len(stops):
        if lens[istroke] <= 0:
            istroke += 1
            continue
        t = (stops[istop] - dist) / lens[istroke]
        if t < 0:
            istop += 1
        elif t > 1.000001:
            dist += lens[istroke]
            istroke += 1
        else:
            s0, s1 = stroke[istroke], stroke[istroke + 1]
            nstroke.append(s0 + (s1 - s0) * t)
            istop += 1
    return nstroke

def walk_to_corner(from_vert, to_edges):
    to_verts = {v for e in to_edges for v in e.verts}
    edges = [
        (e, from_vert, None)
        for e in from_vert.link_edges
        if not e.is_manifold
    ]
    touched = {}
    found = None
    while edges:
        ec, v0, ep = edges.pop(0)
        if ec in touched: continue
        touched[ec] = (v0, ep)
        v1 = ec.other_vert(v0)
        if v1 in to_verts:
            found = ec
            break
        nedges = [
            (en, v1, ec)
            for en in v1.link_edges
            if en != ec and not en.is_manifold
        ]
        edges += nedges
    if not found: return None
    # walk back
    walk = [found]
    while True:
        ec = walk[-1]
        v0, ep = touched[ec]
        if v0 == from_vert:
            break
        walk.append(ep)
    return walk
