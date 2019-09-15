'''
Copyright (C) 2019 CG Cookie
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

class Contours_Utils:
    def filter_edge_selection(self, bme, no_verts_select=True, ratio=0.33):
        if bme.select:
            # edge is already selected
            return True
        bmv0, bmv1 = bme.verts
        s0, s1 = bmv0.select, bmv1.select
        if s0 and s1:
            # both verts are selected, so return True
            return True
        if not s0 and not s1:
            if no_verts_select:
                # neither are selected, so return True by default
                return True
            else:
                # return True if none are selected; otherwise return False
                return self.rfcontext.none_selected()
        # if mouse is at least a ratio of the distance toward unselected vert, return True
        if s1: bmv0, bmv1 = bmv1, bmv0
        p = self.actions.mouse
        p0 = self.rfcontext.Point_to_Point2D(bmv0.co)
        p1 = self.rfcontext.Point_to_Point2D(bmv1.co)
        v01 = p1 - p0
        l01 = v01.length
        d01 = v01 / l01
        dot = d01.dot(p - p0)
        return dot / l01 > ratio

    #def get_count(self): return 


import math
from itertools import chain
from mathutils import Vector, Quaternion

import bpy
import bgl

from ..rfmesh.rfmesh import RFVert
from ...addon_common.common.blender import quat_vector_mult
from ...addon_common.common.utils import iter_pairs, max_index
from ...addon_common.common.hasher import hash_cycle
from ...addon_common.common.maths import (
    Point, Vec, Normal, Direction,
    Point2D, Vec2D,
    Plane, Frame,
)
from ...addon_common.common.profiler import profiler


def draw2D_arrow(p0:Point2D, p1:Point2D):
    d = (p0 - p1) * 0.25
    c = Vec2D((d.y,-d.x))
    p2 = p1 + d + c
    p3 = p1 + d - c

    bgl.glBegin(bgl.GL_LINE_STRIP)
    bgl.glVertex2f(*p0)
    bgl.glVertex2f(*p1)
    bgl.glVertex2f(*p2)
    bgl.glVertex2f(*p1)
    bgl.glVertex2f(*p3)
    bgl.glEnd()

def to_point(item):
    t = type(item)
    if t is RFVert: return item.co
    if t is Point or t is Vector or t is Vec: return item
    if t is tuple: return Point(item)
    return item.co


def next_edge_in_string(edge0, vert01, ignore_two_faced=False):
    faces0 = edge0.link_faces
    edges1 = vert01.link_edges
    # ignore edge0
    edges1 = [edge for edge in edges1 if edge != edge0]
    if ignore_two_faced:
        # ignore edges that have two faces already
        edges1 = [edge for edge in edges1 if len(edge.link_faces) <= 1]
    # ignore edges that share face with previous edge
    edges1 = [edge for edge in edges1 if not faces0 or not any(f in faces0 for f in edge.link_faces)]
    return edges1[0] if len(edges1) == 1 else []

def find_loops(edges):
    if not edges: return []
    touched,loops = set(),[]

    def crawl(v0, edge01, vert_list):
        nonlocal edges, touched
        # ... -- v0 -- edge01 -- v1 -- edge12 -- ...
        #  > came-^-from-^        ^-going-^-to >
        vert_list.append(v0)
        touched.add(edge01)
        v1 = edge01.other_vert(v0)
        if v1 == vert_list[0]: return vert_list
        next_edges = [e for e in v1.link_edges if e in edges and e != edge01]
        if not next_edges: return []
        if len(next_edges) == 1: edge12 = next_edges[0]
        else: edge12 = next_edge_in_string(edge01, v1)
        if not edge12 or edge12 in touched or edge12 not in edges: return []
        return crawl(v1, edge12, vert_list)

    for edge in edges:
        if edge in touched: continue
        vert_list = crawl(edge.verts[0], edge, [])
        if vert_list:
            loops.append(vert_list)

    return loops

def find_parallel_loops(loop, wrap=True):
    def find_opposite_loop(loop, bmf):
        # find edge loop on opposite side of given face from given edge
        bmv0,bmv1 = loop[:2]
        bme01 = bmv0.shared_edge(bmv1)
        bme03 = next((bme for bme in bmf.neighbor_edges(bme01) if bmv0 in bme.verts), None)
        if not bme03: return None
        bmv_opposite = bme03.other_vert(bmv0)
        ploop = []
        for bmv0,bmv1 in iter_pairs(loop, wrap):
            if not bmf: return None
            if len(bmf.verts) != 4: return None
            ploop.append(bmv_opposite)
            bmv_opposite = next(iter(set(bmf.verts)-{bmv0,bmv1,bmv_opposite}), None)
            if not bmv_opposite: return None
            bme = bmv1.shared_edge(bmv_opposite)
            if not bme: return None
            bmf = next(iter(set(bme.link_faces) - {bmf}), None)
        if not ploop: return None
        if not wrap: ploop.append(bmv_opposite)
        return ploop

    ploops = []

    bmv0,bmv1 = loop[:2]
    bme01 = bmv0.shared_edge(bmv1)
    bmfs = [bmf for bmf in bme01.link_faces]
    touched = set()
    for bmf in bmfs:
        bme0 = bme01
        lloop = loop
        while bmf:
            if bmf in touched: break
            touched.add(bmf)
            ploop = find_opposite_loop(lloop, bmf)
            if not ploop: break
            ploops.append(ploop)
            bme1 = bmf.opposite_edge(bme0)
            if not bme1: break
            bmf = next((bmf_ for bmf_ in bme1.link_faces if bmf_ != bmf), None)
            bme0 = bme1
            lloop = ploop

    return ploops

def find_strings(edges, min_length=3):
    if not edges: return []
    touched,strings = set(),[]

    def crawl(v0, edge01, vert_list):
        nonlocal edges, touched
        # ... -- v0 -- edge01 -- v1 -- edge12 -- ...
        #    came ^ from ^
        vert_list.append(v0)
        touched.add(edge01)
        v1 = edge01.other_vert(v0)
        if v1 == vert_list[0]: return []
        edge12 = next_edge_in_string(edge01, v1)
        if not edge12 or edge12 not in edges: return vert_list + [v1]
        return crawl(v1, edge12, vert_list)

    for edge in edges:
        if edge in touched: continue
        vert_list0 = crawl(edge.verts[0], edge, [])
        vert_list1 = crawl(edge.verts[1], edge, [])
        vert_list = list(reversed(vert_list0)) + vert_list1[2:]
        if len(vert_list) >= min_length: strings.append(vert_list)

    return strings

def find_cycles(edges, max_loops=10):
    # searches through edges to find loops
    # first, break into connected components
    # then, find all the junctions (verts with more than two connected edges)
    # sequence of edges between junctions can be reduced to single edge
    # find cycles in graph

    if not edges: return []

    vert_edges = {}
    for edge in edges:
        v0,v1 = edge.verts
        vert_edges[v0] = vert_edges.get(v0, []) + [(edge,v1)]
        vert_edges[v1] = vert_edges.get(v1, []) + [(edge,v0)]
    touched_edges = set()
    touched_verts = set()
    cycles = []
    cycle_hashes = set()
    def crawl(v0, vert_list):
        touched_verts.add(v0)
        vert_list.append(v0)
        for edge,v1 in vert_edges[v0]:
            if edge in touched_edges: continue
            touched_edges.add(edge)
            if v1 in vert_list:
                # found cycle!
                cycle = list(reversed(vert_list))
                while cycle[-1] != v1: cycle.pop()
                h = hash_cycle(cycle)
                if h not in cycle_hashes:
                    cycle_hashes.add(h)
                    cycles.append(cycle)
            else:
                crawl(v1, vert_list)
            touched_edges.remove(edge)
            if len(cycles) == max_loops: return
        vert_list.pop()
    for v in vert_edges.keys():
        if v in touched_verts: continue
        crawl(v, [])
    if len(cycles) == max_loops: print('max loop count reached')
    return cycles

def edges_of_loop(vert_loop):
    edges = []
    for v0,v1 in iter_pairs(vert_loop, True):
        e0 = set(v0.link_edges)
        e1 = set(v1.link_edges)
        edges += list(e0 & e1)
    return edges

def verts_of_loop(edge_loop):
    verts = []
    for e0,e1 in iter_pairs(edge_loop, False):
        if not verts:
            v0 = e0.shared_vert(e1)
            verts += [e0.other_vert(v0), v0]
        verts += [e1.other_vert(verts[-1])]
    if len(verts) > 1 and verts[0] == verts[-1]: return verts[:-1]
    return verts

def loop_plane(vert_loop):
    # average co is pt on plane
    # average cross product (point in same direction) is normal
    if not vert_loop: return None
    vert_loop = [to_point(v) for v in vert_loop]
    pt = sum((Vector(vert) for vert in vert_loop), Vector()) / len(vert_loop)
    n,cnt = None,0
    for vert0,vert1 in zip(vert_loop[:-1], vert_loop[1:]):
        c = Vec((vert0-pt).cross(vert1-pt)).normalize()
        n = n+c if n else c
    if not n: return Plane(pt, Normal())
    return Plane(pt, Normal(n).normalize())

def loop_radius(vert_loop):
    pt = sum((Vector(to_point(vert)) for vert in vert_loop), Vector()) / len(vert_loop)
    rad = sum((to_point(vert) - pt).length for vert in vert_loop) / len(vert_loop)
    return rad

def loop_length(vert_loop):
    return sum((to_point(v0)-to_point(v1)).length for v0,v1 in zip(vert_loop, chain(vert_loop[1:], vert_loop[:1])))

def loops_connected(vert_loop0, vert_loop1):
    if not vert_loop0 or not vert_loop1: return False
    v0 = vert_loop0
    v0_connected = { e.other_vert(v0) for e in v0.link_edges }
    return any(v1 in v0_connected for v1 in vert_loop1)

def edges_between_loops(vert_loop0, vert_loop1):
    loop1 = set(vert_loop1)
    return [e for v0 in vert_loop0 for e in v0.link_edges if e.other_vert(v0) in loop1]

def faces_between_loops(vert_loop0, vert_loop1):
    loop1 = set(vert_loop1)
    return [f for v0 in vert_loop0 for f in v0.link_faces if any(fv in loop1 for fv in f.verts)]

def string_length(vert_loop):
    return sum((to_point(v0)-to_point(v1)).length for v0,v1 in zip(vert_loop[:-1], vert_loop[1:]))

def project_loop_to_plane(vert_loop, plane):
    return [plane.project(to_point(v)) for v in vert_loop]



class Contours_Loop:
    def __init__(self, vert_loop, connected, offset=0):
        self.connected = connected
        self.set_vert_loop(vert_loop, offset)

    def __repr__(self):
        return '<Contours_Loop: %d,%s,%s>' % (len(self.verts), str(self.connected), str(self.verts))

    @profiler.function
    def set_vert_loop(self, vert_loop, offset):
        self.verts = vert_loop
        self.offset = offset
        self.pts = [to_point(bmv) for bmv in self.verts]
        self.count = len(self.pts)
        self.plane = loop_plane(self.pts)
        if not self.connected:
            self.plane.o = self.pts[0] + (self.pts[-1] - self.pts[0]) / 2
        self.up_dir = Direction(self.pts[0] - self.plane.o)
        self.frame = Frame.from_plane(self.plane, y=self.up_dir)

        proj = self.plane.project
        self.dists = [(proj(p0)-proj(p1)).length for p0,p1 in iter_pairs(self.pts, self.connected)]
        self.proj_dists = [self.plane.signed_distance_to(p) for p in self.pts]
        self.circumference = sum(self.dists)
        self.radius = sum(self.w2l_point(pt).length for pt in self.pts) / self.count

    def get_origin(self): return self.plane.o
    def get_normal(self): return self.plane.n
    def get_local_by_index(self, idx): return self.w2l_point(self.pts[idx])
    def w2l_point(self, co): return self.frame.w2l_point(to_point(co))
    def l2w_point(self, co): return self.frame.l2w_point(to_point(co))
    def get_index_of_top(self, pts):
        pts_local = [self.w2l_point(pt+self.frame.o) for pt in pts]
        idx = max_index(pts_local, key=lambda pt:pt.y)
        t = pts_local[idx]
        #print(pts_local, idx, t)
        offset = ((math.pi/2 - math.atan2(t.y, t.x)) * self.circumference / (math.pi*2)) % self.circumference
        return (idx,offset)

    def align_to(self, other):
        n0, n1 = self.get_normal(), other.get_normal()
        is_opposite = n0.dot(n1) < 0
        vert_loop = list(reversed(self.verts)) if is_opposite else self.verts
        if not self.connected:
            self.set_vert_loop(vert_loop, 0)
            return
        if is_opposite: n0 = -n0

        # issue #659
        angle = 0 if n0.length_squared == 0 or n1.length_squared == 0 else n0.angle(n1)
        q = Quaternion(n0.cross(n1), angle)

        # rotate to align "topmost" vertex
        rel_pos = [Vec(quat_vector_mult(q, (to_point(p) - self.frame.o))) for p in vert_loop]
        rot_by,offset = other.get_index_of_top(rel_pos)
        vert_loop = vert_loop[rot_by:] + vert_loop[:rot_by]
        offset = (offset * self.circumference / other.circumference)
        self.set_vert_loop(vert_loop, offset)

    def get_closest_point(self, point):
        point = to_point(point)
        cp,cd = None,None
        for p0,p1 in iter_pairs(self.pts, self.connected):
            diff = p1 - p0
            l = diff.length
            d = diff / l
            pp = p0 + d * max(0, min(l, (point - p0).dot(d)))
            dist = (point - pp).length
            if not cp or dist < cd: cp,cd = pp,dist
        return cp

    def get_points_relative_to(self, other):
        scale = other.radius / self.radius
        return [other.l2w_point(Vector(self.w2l_point(pt)) * scale) for pt in self.pts]

    def iter_pts(self, repeat=False):
        return iter_pairs(self.pts, self.connected, repeat=repeat)

    def move_2D(self, xy_delta:Vec2D):
        pass
