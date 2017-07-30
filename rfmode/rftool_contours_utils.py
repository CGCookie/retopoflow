import bpy
import bgl
import math
from itertools import chain
from mathutils import Vector
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec,Normal,Plane,Frame, Direction

def to_point(item):
    t = type(item)
    if t is Point or t is Vector: return item
    return item.co

def iter_pairs(items, wrap):
    for i0,i1 in zip(items[:-1],items[1:]): yield i0,i1
    if wrap: yield items[-1],items[0]

def rotcycle(cycle, offset):
    l = len(cycle)
    return [cycle[(l + ((i - offset) % l)) % l] for i in range(l)]

def hash_cycle(cycle):
    l = len(cycle)
    h = [hash(v) for v in cycle]
    m = min(h)
    mi = h.index(m)
    h = rotcycle(h, -mi)
    if h[1] > h[-1]:
       h.reverse()
       h = rotcycle(h, 1)
    return ' '.join(str(c) for c in h)

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

def find_strings(edges, min_length=4):
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

def loop_plane(vert_loop):
    # average co is pt on plane
    # average cross product (point in same direction) is normal
    pt = sum((Vector(to_point(vert)) for vert in vert_loop), Vector()) / len(vert_loop)
    n,cnt = None,0
    for i0,vert0 in enumerate(vert_loop[:-1]):
        v0 = to_point(vert0) - pt
        for vert1 in vert_loop[i0+1:]:
            v1 = to_point(vert1) - pt
            c = Vec(v0.cross(v1)).normalize()
            if cnt == 0: n = c
            else:
                if n.dot(c) < 0: n -= c
                else: n += c
            cnt += 1
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
    def __init__(self, vert_loop):
        self.set_vert_loop(vert_loop)
    
    def __str__(self):
        return '<Contours_Loop: %s>' % str(self.verts)

    def set_vert_loop(self, vert_loop):
        self.verts = vert_loop
        self.pts = [to_point(bmv) for bmv in self.verts]
        self.count = len(self.verts)
        self.plane = loop_plane(self.verts)
        self.up_dir = Direction(self.pts[0] - self.plane.o).normalize()
        self.frame = Frame.from_plane(self.plane, y=self.up_dir)
        self.pts_local = [self.frame.w2l_point(pt) for pt in self.pts]

        self.radius = sum(pt.length for pt in self.pts_local) / self.count
        self.dists = [(p0-p1).length for p0,p1 in iter_pairs(self.pts, True)]
        self.length = sum(self.dists)

    def get_origin(self): return self.plane.o
    def get_normal(self): return self.plane.n
    def get_local_by_index(self, idx): return self.pts_local[idx]
    def w2l_point(self, co): return self.frame.w2l_point(to_point(co))
    def l2w_point(self, co): return self.frame.l2w_point(to_point(co))
    def get_index_of_top(self, pts):
        ys = map(self.w2l_point, pts)
        i,_ = max(enumerate(ys), key=lambda iy:iy[1].y)
        return i

    def align_to(self, other):
        opposite = self.get_normal().dot(other.get_normal()) < 0
        vert_loop = list(reversed(self.verts)) if opposite else self.verts
        rot_by = other.get_index_of_top(vert_loop)
        vert_loop = vert_loop[rot_by:] + vert_loop[:rot_by]
        self.set_vert_loop(vert_loop)
    
    def get_closest_point(self, point):
        point = to_point(point)
        cp,cd = None,None
        for p0,p1 in iter_pairs(self.pts, wrap=True):
            diff = p1 - p0
            l = diff.length
            d = diff / l
            pp = p0 + d * max(0, min(l, (point - p0).dot(d)))
            dist = (point - pp).length
            if not cp or dist < cd: cp,cd = pp,dist
        return cp
    
    def get_points_relative_to(self, other):
        scale = other.radius / self.radius
        return [other.l2w_point(Vector(pt) * scale) for pt in self.pts_local]
    
    def move_2D(self, xy_delta:Vec2D):
        pass
