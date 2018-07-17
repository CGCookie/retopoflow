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