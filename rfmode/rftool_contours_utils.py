import bpy
import bgl
import math
from mathutils import Vector
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec,Plane

def iter_pairs(items, wrap):
    for i0,i1 in zip(items[:-1],items[1:]): yield i0,i1
    if wrap: yield items[-1],items[0]

def rotcycle(cycle, offset):
    l = len(cycle)
    return [cycle[(l + ((i - offset) % l)) % l] for i in range(l)]

def hash_loop(cycle):
    l = len(cycle)
    h = [hash(v) for v in cycle]
    m = min(h)
    mi = h.index(m)
    h = rotcycle(h, -mi)
    if h[1] > h[-1]:
       h.reverse()
       h = rotcycle(h, 1)
    return ' '.join(str(c) for c in h)

def find_loops(edges, max_loops=10):
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
                h = hash_loop(cycle)
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
    pt = sum((Vector(vert.co) for vert in vert_loop), Vector()) / len(vert_loop)
    n,cnt = Vector(),0
    for i0,vert0 in enumerate(vert_loop[:-1]):
        v0 = vert0.co - pt
        for vert1 in vert_loop[i0+1:]:
            v1 = vert1.co - pt
            c = v0.cross(v1).normalized()
            if cnt == 0: n = c
            else:
                if n.dot(c) < 0: n -= c
                else: n += c
            cnt += 1
    return Plane(pt, n.normalized())