'''
Copyright (C) 2023 CG Cookie
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
import copy
import heapq
import numpy as np
import random
from dataclasses import dataclass, field
from itertools import takewhile, filterfalse

import bpy
import bmesh
from bmesh.types import BMVert, BMEdge, BMFace
from bmesh.ops import (
    bisect_plane, holes_fill,
    dissolve_verts, dissolve_edges, dissolve_faces,
    remove_doubles, mirror, recalc_face_normals,
    pointmerge,
)
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from mathutils.geometry import normal as compute_normal, intersect_point_tri, intersect_point_tri_2d

from ...addon_common.common.blender import ModifierWrapper_Mirror
from ...addon_common.common.maths import Point, Normal, Direction
from ...addon_common.common.maths import Point2D
from ...addon_common.common.maths import Ray, XForm, BBox, Plane
from ...addon_common.common.hasher import hash_object, Hasher
from ...addon_common.common.utils import min_index, UniqueCounter, iter_pairs, accumulate_last, deduplicate_list, has_duplicates
from ...addon_common.common.decorators import stats_wrapper, blender_version_wrapper
from ...addon_common.common.debug import dprint
from ...addon_common.common.profiler import profiler, time_it, timing
from ...addon_common.terminal import term_printer

from ...addon_common.common.useractions import Actions

from ...config.options import options

from .rfmesh_wrapper import (
    BMElemWrapper, RFVert, RFEdge, RFFace, RFEdgeSequence
)

try:
    from ..cy.bmesh_visibility import compute_visible_vertices
    USE_CYTHON = True
except ImportError:
    USE_CYTHON = False


class RFMesh():
    '''
    RFMesh wraps a mesh object, providing extra machinery such as
    - computing hashes on the object (know when object has been modified)
    - maintaining a corresponding bmesh and bvhtree of the object
    - handling snapping and raycasting
    - translates to/from local space (transformations)
    '''

    create_count = 0
    delete_count = 0

    def __init__(self):
        assert False, 'Do not create new RFMesh directly!  Use RFSource.new() or RFTarget.new()'

    def __deepcopy__(self, memo):
        assert False, 'Do not copy me'

    @staticmethod
    @profiler.function
    def get_bmesh_from_object(obj, deform=False):
        bme = bmesh.new()
        if deform:
            depsgraph = bpy.context.evaluated_depsgraph_get()
            bme.from_object(obj, depsgraph)
        else:
            bme.from_mesh(obj.data)
        return bme

    @stats_wrapper
    @profiler.function
    def __setup__(
        self, obj,
        deform=False, bme=None, triangulate=False,
        selection=True, keepeme=False
    ):
        # checking for NaNs
        # print('RFMesh.__setup__: checking for NaNs')
        hasnan = any(
            math.isnan(v)
            for emv in obj.data.vertices
            for v in emv.co
        )
        if hasnan:
            # print('RFMesh.__setup__: Mesh data contains NaN in vertex coordinate! Cleaning and validating mesh...')
            obj.data.validate(verbose=True, clean_customdata=False)
        else:
            # cleaning mesh quietly
            # print('skipping mesh validation')
            # print('RFMesh.__setup__: validating')
            obj.data.validate(verbose=False, clean_customdata=False)

        # setup init
        self.obj = obj
        self.xform = XForm(self.obj.matrix_world)
        self.hash = hash_object(self.obj)
        self._version = None
        self._version_selection = None

        if bme is not None:
            self.bme = bme
        else:
            # print('RFMesh.__setup__: creating bmesh from object')
            self.bme = self.get_bmesh_from_object(self.obj, deform=deform)

            if selection:
                # print('RFMesh.__setup__: copying selection')
                with profiler.code('copying selection'):
                    self.bme.select_mode = {'FACE', 'EDGE', 'VERT'}
                    # copy selection from editmesh
                    for bmf, emf in zip(self.bme.faces, self.obj.data.polygons):
                        bmf.select = emf.select
                    for bme, eme in zip(self.bme.edges, self.obj.data.edges):
                        bme.select = eme.select
                    for bmv, emv in zip(self.bme.verts, self.obj.data.vertices):
                        bmv.select = emv.select
            else:
                self.deselect_all()

        if triangulate:
            # print('RFMesh.__setup__: triangulating')
            self.triangulate()

        for bmv in self.bme.verts:
            if not bmv.is_wire:
                bmv.normal_update()

        # setup finishing
        self.selection_center = Point((0, 0, 0))
        self.store_state()
        self.dirty()
        if False:
            term_printer.boxed(
                f'{obj.name}',
                f'Options: {deform=} {triangulate=} {selection=} {keepeme=}',
                f'Counts: v={len(self.bme.verts)} e={len(self.bme.edges)} f={len(self.bme.faces)}',
                title=f'RFMesh.setup',
            )

    def __del__(self):
        RFMesh.delete_count += 1
        # print('RFMesh.__del__', self, RFMesh.create_count, RFMesh.delete_count)
        self.bme.free()

    ##########################################################

    def get_frame(self): return self.xform.to_frame()

    def w2l_point(self, p): return self.xform.w2l_point(p)
    def w2l_normal(self, n): return self.xform.w2l_normal(n)
    def w2l_vec(self, v): return self.xform.w2l_vector(v)
    def w2l_direction(self, d): return self.xform.w2l_direction(d)

    def l2w_point(self, p): return self.xform.l2w_point(p)
    def l2w_normal(self, n): return self.xform.l2w_normal(n)
    def l2w_vec(self, v): return self.xform.l2w_vector(v)
    def l2w_direction(self, d): return self.xform.l2w_direction(d)

    ##########################################################

    def dirty(self, selectionOnly=False):
        if not selectionOnly:
            if hasattr(self, 'bvh'): del self.bvh
            self._version = UniqueCounter.next()
        self._version_selection = UniqueCounter.next()

    def clean(self):
        pass

    def get_version(self, selection=True):
        return Hasher(self._version, (self._version_selection if selection else 0))

    @profiler.function
    def get_bvh(self):
        ver = self.get_version(selection=False)
        if not hasattr(self, 'bvh') or self.bvh_version != ver:
            self.bvh = BVHTree.FromBMesh(self.bme)
            self.bvh_version = ver
        return self.bvh

    @profiler.function
    def get_bbox(self):
        ver = self.get_version(selection=False)
        if not hasattr(self, 'bbox') or self.bbox_version != ver:
            self.bbox = BBox(from_object=self.obj, xform_point=self.l2w_point)
            self.bbox_version = ver
        return self.bbox

    @profiler.function
    def get_local_bbox(self, w2l_point):
        ver = self.get_version(selection=False)
        if not hasattr(self, 'local_bbox') or self.local_bbox_version != ver or self.local_w2l_point != w2l_point:
            fn = lambda p: w2l_point(self.l2w_point(p))
            # self.local_bbox = BBox(from_bmverts=self.bme.verts, xform_point=fn)
            self.local_bbox = BBox(from_object=self.obj, xform_point=fn)
            self.local_bbox_version = ver
            self.local_w2l_point = w2l_point
        return self.local_bbox

    @profiler.function
    def get_kdtree(self):
        ver = self.get_version(selection=False)
        if not hasattr(self, 'kdt') or self.kdt_version != ver:
            self.kdt = KDTree(len(self.bme.verts))
            for i, bmv in enumerate(self.bme.verts):
                self.kdt.insert(bmv.co, i)
            self.kdt.balance()
            self.kdt_version = ver
        return self.kdt

    def get_geometry_counts(self):
        ver = self.get_version(selection=False)
        if not hasattr(self, 'geocounts') or self.geocounts_version != ver:
            nv = len(self.bme.verts)
            ne = len(self.bme.edges)
            nf = len(self.bme.faces)
            self.geocounts = (nv,ne,nf)
            self.geocounts_version = ver
        return self.geocounts

    ##########################################################

    def store_state(self):
        attributes = ['viewport_hide', 'render_hide']    # list of attributes to remember
        self.prev_state = { attr: self.obj_attr_get(attr) for attr in attributes }

    def restore_state(self):
        for attr, val in self.prev_state.items():
            self.obj_attr_set(attr, val)

    def get_obj_name(self):
        return self.obj.name

    def obj_viewport_hide_get(self): return self.obj.hide_viewport
    def obj_viewport_hide_set(self, v): self.obj.hide_viewport = v

    def obj_select_get(self): return self.obj.select_get()
    def obj_select_set(self, v): self.obj.select_set(v)

    def obj_render_hide_get(self): return self.obj.hide_render
    def obj_render_hide_set(self, v): self.obj.hide_render = v

    def obj_viewport_hide(self):   self.obj_viewport_hide_set(True)
    def obj_viewport_unhide(self): self.obj_viewport_hide_set(False)

    def obj_render_hide(self):   self.obj_render_hide_set(True)
    def obj_render_unhide(self): self.obj_render_hide_set(False)

    def obj_select(self):   self.obj_select_set(True)
    def obj_unselect(self): self.obj_select_set(False)

    def obj_attr_get(self, attr): return getattr(self, 'obj_%s_get'%attr)()
    def obj_attr_set(self, attr, v): getattr(self, 'obj_%s_set'%attr)(v)


    ##########################################################

    def ensure_lookup_tables(self):
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.faces.ensure_lookup_table()

    @property
    def tag(self):
        return self.obj.data.tag

    @tag.setter
    def tag(self, v):
        self.obj.data.tag = v

    ##########################################################

    @profiler.function
    def triangulate(self):
        # faces = [face for face in self.bme.faces if len(face.verts) != 3]
        # print('RFMesh.triangulate: found %d non-triangles' % len(faces))
        # bmesh.ops.triangulate(self.bme, faces=faces)
        bmesh.ops.triangulate(self.bme, faces=self.bme.faces)

    @profiler.function
    def plane_split(self, plane: Plane):
        plane_local = self.xform.w2l_plane(plane)
        dist = 0.00000001
        geom = (
            list(self.bme.verts) +
            list(self.bme.edges) +
            list(self.bme.faces)
        )
        bisect_plane(
            self.bme,
            geom=geom, dist=dist,
            plane_co=plane_local.o, plane_no=plane_local.n,
            use_snap_center=True,
            clear_outer=False, clear_inner=False
        )

    @profiler.function
    def plane_intersection(self, plane: Plane):
        # TODO: do not duplicate vertices!
        l2w_point = self.xform.l2w_point
        plane_local = self.xform.w2l_plane(plane)
        side = plane_local.side
        triangle_intersection = plane_local.triangle_intersection

        # vert sides
        vert_side = {
            bmv: side(bmv.co)
            for bmv in self.bme.verts
        }
        # split edges
        edges = {
            bme
            for bme in self.bme.edges
            if vert_side[bme.verts[0]] != vert_side[bme.verts[1]]
        }
        # split faces
        faces = {
            bmf
            for bme in edges
            for bmf in bme.link_faces
        }
        # intersections
        yield from (
            (l2w_point(p0), l2w_point(p1))
            for bmf in faces
            for (p0, p1) in triangle_intersection([
                bmv.co for bmv in bmf.verts
            ])
        )

    def get_xy_plane(self):
        o = self.xform.l2w_point(Point((0, 0, 0)))
        n = self.xform.l2w_normal(Normal((0, 0, 1)))
        return Plane(o, n)

    def get_xz_plane(self):
        o = self.xform.l2w_point(Point((0, 0, 0)))
        n = self.xform.l2w_normal(Normal((0, 1, 0)))
        return Plane(o, n)

    def get_yz_plane(self):
        o = self.xform.l2w_point(Point((0, 0, 0)))
        n = self.xform.l2w_normal(Normal((1, 0, 0)))
        return Plane(o, n)

    @profiler.function
    def _crawl(self, bmf_start, plane):
        '''
        crawl about RFMesh along plane starting with bmf
        returns list of tuples (face0, edge between face0 and face1, face1, intersection of edge and plane)
        '''

        def intersect_edge(bme):
            nonlocal plane
            bmv0, bmv1 = bme.verts
            return plane.edge_intersection(bmv0.co, bmv1.co)
        def intersect_face(bmf):
            crosses = [(bme, intersect_edge(bme)) for bme in bmf.edges]
            return [(bme, cross) for (bme, cross) in crosses if cross]
        def intersected_face(bmf):
            nonlocal plane
            sides = [plane.side(bmv.co, threshold=0) for bmv in bmf.verts]
            if any(s == 0 for s in sides): return True
            return any(s0 != s1 for (s0, s1) in iter_pairs(sides, True))
        def adjacent_faces(bmf):
            return {bmf_adj for bmv in bmf.verts for bmf_adj in bmv.link_faces}
        def next_face(bmf, bme):
            return next((bmf_other for bmf_other in bme.link_faces if bmf_other != bmf), None)

        ###########################################################

        # find all bmfaces that are connected to bmf_start and the plane intersects
        bmfs_intersect = set()
        bmfs_touched = set()
        bmfs_working = { bmf_start }
        while bmfs_working:
            bmf = bmfs_working.pop()
            if bmf in bmfs_touched: continue
            bmfs_touched.add(bmf)
            if not intersected_face(bmf): continue
            bmfs_intersect.add(bmf)
            bmfs_working.update(adjacent_faces(bmf))

        # find all bmverts and bmedges that intersect plane and compute the corresponding intersection point
        points = {}
        bmvs_touched = set()
        bmes_touched = set()
        for bmf in bmfs_intersect:
            points[bmf] = []
            for bmv in bmf.verts:
                if bmv in points:
                    pt,l = points[bmv]
                    points[bmf].append((pt, bmv))
                    l.append(bmf)
                    continue
                if bmv in bmvs_touched: continue
                bmvs_touched.add(bmv)
                if plane.side(bmv.co, threshold=0) != 0: continue
                pt = bmv.co
                points[bmf].append((pt, bmv))
                points[bmv] = (pt, [bmf])
            for bme in bmf.edges:
                if bme in points:
                    pt,l = points[bme]
                    points[bmf].append((pt, bme))
                    l.append(bmf)
                if bme in bmes_touched: continue
                bmes_touched.add(bme)
                v0, v1 = bme.verts
                if v0 in points or v1 in points: continue
                pt = plane.edge_intersection(v0.co, v1.co, threshold=0)
                if not pt: continue
                points[bmf].append((pt, bme))
                points[bme] = (pt, [bmf])

        bmfs_intersect = {bmf for bmf in bmfs_intersect if len(points[bmf]) == 2}
        for bmv in bmvs_touched:
            if bmv not in points: continue
            pt, l = points[bmv]
            l = [bmf for bmf in l if bmf in bmfs_intersect]
            if len(l) in {1,2}: points[bmv] = (pt, l)
            else: del points[bmv]
        for bme in bmes_touched:
            if bme not in points: continue
            pt, l = points[bme]
            l = [bmf for bmf in l if bmf in bmfs_intersect]
            if len(l) in {1,2}: points[bme] = (pt, l)
            else: del points[bme]
        if not bmfs_intersect: return [] # something bad happened
        if bmf_start not in bmfs_intersect:
            # bmf_start must have had only one intersection point, so pick any other to be new bmf_start
            bmf_start = next(iter(bmfs_intersect))

        # create adjacency graph that we'll use to crawl over
        graph = {}
        # graph.update({ bmf:adjacent_faces(bmf) for bmf in bmfs_intersect })
        graph.update({ bmv:[bmf for bmf in bmv.link_faces if bmf in bmfs_intersect] for bmv in bmvs_touched })
        graph.update({ bme:[bmf for bmf in bme.link_faces if bmf in bmfs_intersect] for bme in bmes_touched })
        graph = { k:v for (k,v) in graph.items() if v }

        ret = []
        def crawl(i_current):
            nonlocal ret, bmf_start, points, graph
            bmf_current = bmf_start
            while True:
                pt_current, bmelem_current = i_current
                bmfs_adj = points[bmelem_current][1] if bmelem_current in points else []
                bmf_next = next((bmf_adj for bmf_adj in bmfs_adj if bmf_adj != bmf_current), None)
                ret.append((bmf_current, pt_current, bmf_next))
                if bmf_next is None: return False
                if bmf_next == bmf_start: return True
                i0, i1 = points[bmf_next]
                i_current = i0 if i_current == i1 else i1
                bmf_current = bmf_next
        wrapped = crawl(points[bmf_start][0])
        if not wrapped:
            # did not wrap, so switch directions
            ret = [(f1,c,f0) for (f0,c,f1) in reversed(ret)]
            crawl(points[bmf_start][1])
        return ret

        # crosses = intersect_face(bmf_start)     # assuming all faces are triangles!
        # if len(crosses) != 2: return []         # face does not cross plane
        # bme_start0, cross0 = crosses[0]
        # bme_start1, cross1 = crosses[1]

        # ret = []
        # bme_next = bme_start0
        # cross = cross0

        # def crawl(bme_next, cross_next):
        #     nonlocal ret, bmf_start
        #     bmf_current = bmf_start
        #     while True:
        #         bmf_next = next_face(bmf_current, bme_next)
        #         if bmf_next:
        #             crosses = intersect_face(bmf_next)
        #             if len(crosses) != 2: bmf_next = None           # bmvert of bmf_next lies on plane
        #         ret += [(bmf_current, bme_next, bmf_next, cross_next)]
        #         if not bmf_next: return False                       # cannot continue this direction
        #         if bmf_next == bmf_start: return True               # wrapped around!
        #         bmf_current = bmf_next
        #         bme_next, cross_next = next(((e,c) for (e,c) in crosses if e != bme_next), (None, None))
        #         if not bme_next: return False                       # something bad happened!
        #     return False

        # wrapped = crawl(bme_start0, cross0)                                 # crawl one direction
        # if not wrapped:
        #     # did not wrap around, so should continue crawling the other way
        #     ret = [(f1, e, f0, c) for (f0, e, f1, c) in reversed(ret)]      # reverse results
        #     crawl(bme_start1, cross1)                                       # crawl other direction
        # return ret

    @profiler.function
    def plane_intersection_crawl(self, ray:Ray, plane:Plane, walk_to_plane:bool=False):
        '''
        intersect object with ray, (possibly) walk to plane, then crawl about
        '''
        # intersect self with ray
        ray,plane = self.xform.w2l_ray(ray),self.xform.w2l_plane(plane)
        _,_,i,_ = self.get_bvh().ray_cast(ray.o, ray.d, ray.max)
        bmf = self.bme.faces[i]

        if walk_to_plane:
            # follow link_faces of verts that walk us toward the plane until we find a bmface that crosses/touches
            # we have two different greedy implementations.  one follows bmfaces and uses a heap; the other greedily
            # follows bmedges one at a time.

            # https://docs.python.org/3.8/library/heapq.html#priority-queue-implementation-notes
            @dataclass(order=True)
            class PrioritizedBMV:
                dot: float
                bmv: BMVert=field(compare=False)
                def __init__(self, bmv, dot):
                    self.dot = dot
                    self.bmv = bmv
            def walk_to_plane_heap(bmf, ignore_touching=False):
                '''
                this implementation uses a heap (priority queue) to greedily follow link_faces of bmverts.
                NOTE: the route taken is not necessarily the shortest in terms of
                      edge lengths or distance to from initial to final bmf!
                if ignore_touching: do not consider bmverts that lie exactly on plane.  this is useful because _crawl (above)
                assumes that there will be exactly two bmedges of the bmface that cross the plane
                '''
                bmvs = [bmv for bmv in bmf.verts]
                bmvs_dot = [plane.signed_distance_to(bmv.co) for bmv in bmvs]   # which side of plane are bmverts?
                if max(bmvs_dot) >= 0 and min(bmvs_dot) <= 0: return bmf        # bmf crosses/touches plane already!
                sign = -1 if bmvs_dot[0] < 0 else 1                             # indicates direction that we need to walk
                bmv_heap = []
                touched = { bmf }
                for bmv,bmv_dot in zip(bmvs, bmvs_dot):
                    heapq.heappush(bmv_heap, PrioritizedBMV(bmv, abs(bmv_dot)))
                    touched.add(bmv)
                while True:
                    if not bmv_heap: return None
                    data = heapq.heappop(bmv_heap)          # get next bmvert to process
                    bmv,bmv_dot = data.bmv, data.dot
                    if bmv_dot <= 0: break                  # found a vert at or across the plane!
                    for bmf in bmv.link_faces:
                        if bmf in touched: continue
                        touched.add(bmf)
                        for bmv in bmf.verts:
                            if bmv in touched: continue
                            touched.add(bmv)
                            bmv_dot = plane.signed_distance_to(bmv.co)
                            bmv_dot = abs(bmv_dot) if ignore_touching else bmv_dot*sign
                            heapq.heappush(bmv_heap, PrioritizedBMV(bmv, bmv_dot))
                # find a bmface adjacent to bmv that crosses the plane
                for bmf in bmv.link_faces:
                    bmvs = [bmv for bmv in bmf.verts]
                    bmvs_dot = [plane.signed_distance_to(bmv.co) for bmv in bmvs]   # which side of plane are bmverts?
                    if max(bmvs_dot) >= 0 and min(bmvs_dot) <= 0: return bmf        # bmf crosses/touches plane!
                assert False

            def walk_to_plane_single(bmf):
                '''
                this implementation uses a greedy algorithm to follow link_edges of bmverts.
                NOTE: the route taken is not necessarily the shortest in terms of
                      edge lengths or distance to from initial to final bmf!
                '''
                bmvs = [bmv for bmv in bmf.verts]
                bmvs_dot = [plane.signed_distance_to(bmv.co) for bmv in bmvs]
                if max(bmvs_dot) >= 0 and min(bmvs_dot) <= 0:
                    # bmf crosses plane already
                    return bmf
                idx = min_index(bmvs_dot)
                bmv,bmv_dot,sign = bmvs[idx],abs(bmvs_dot[idx]),(-1 if bmvs_dot[idx] < 0 else 1)
                touched = set()
                while True:
                    # search all verts that are connected to bmv (via an edge) and find
                    # the other vert that gets us closer to the plane.  if the other vert
                    # allows us to cross the plane, we're done!
                    touched.add(bmv)
                    obmvs = [bme.other_vert(bmv) for bme in bmv.link_edges]
                    obmvs = [obmv for obmv in obmvs if obmv not in touched]
                    if not obmvs: return None
                    obmvs_dot = [plane.signed_distance_to(obmv.co)*sign for obmv in obmvs]
                    idx = min_index(obmvs_dot)
                    obmv,obmv_dot = obmvs[idx],obmvs_dot[idx]
                    if obmv_dot <= 0:
                        # found plane!
                        return next(iter(set(bmv.link_faces) & set(obmv.link_faces)))
                    if obmv_dot > bmv_dot: return None
                    bmv = obmv
                    bmv_dot = obmv_dot

            bmf = walk_to_plane_heap(bmf)  # walk_to_plane_single(bmf)
            if not bmf: return None

        # crawl about self along plane
        ret = self._crawl(bmf, plane)
        w,l2w_point = self._wrap,self.xform.l2w_point
        ret = [(w(f0),l2w_point(c),w(f1)) for (f0,c,f1) in ret]
        return ret

    @profiler.function
    def plane_intersections_crawl(self, plane:Plane):
        plane = self.xform.w2l_plane(plane)
        w,l2w_point = self._wrap,self.xform.l2w_point

        # find all faces that cross the plane
        # finding all edges crossing plane
        dot = plane.n.dot
        o = dot(plane.o)
        edges = [bme for bme in self.bme.edges if (dot(bme.verts[0].co)-o) * (dot(bme.verts[1].co)-o) <= 0]

        # finding faces crossing plane
        faces = set(bmf for bme in edges for bmf in bme.link_faces)

        # crawling faces along plane
        rets = []
        touched = set()
        for bmf in faces:
            if bmf in touched: continue
            ret = self._crawl(bmf, plane)
            touched |= set(f0 for f0,_,_,_ in ret if f0)
            touched |= set(f1 for _,_,f1,_ in ret if f1)
            ret = [(w(f0),w(e),w(f1),l2w_point(c)) for f0,e,f1,c in ret]
            rets.append(ret)

        return rets


    ##########################################################

    @staticmethod
    def _wrap(bmelem):
        match bmelem:
            case None:     return None
            case BMVert(): return RFVert(bmelem)
            case BMEdge(): return RFEdge(bmelem)
            case BMFace(): return RFFace(bmelem)
            case _:        assert False
    @staticmethod
    def _wrap_bmvert(bmv): return RFVert(bmv)
    @staticmethod
    def _wrap_bmedge(bme): return RFEdge(bme)
    @staticmethod
    def _wrap_bmface(bmf): return RFFace(bmf)
    @staticmethod
    def _unwrap(elem): return elem if not hasattr(elem, 'bmelem') else elem.bmelem


    ##########################################################

    def raycast(self, ray:Ray, *, ignore_backface=False, backface_push=0.00001, max_backface_pushes=20):
        ray_local = self.xform.w2l_ray(ray)
        for _ in range(max_backface_pushes):
            p,n,i,d = self.get_bvh().ray_cast(ray_local.o, ray_local.d, ray_local.max)
            if not p: return (None, None, None, None)
            if not (ignore_backface and n.dot(ray_local.d) > 0): break
            ray_local.max -= (p - ray_local.o).length
            ray_local.o = p + ray_local.d * backface_push
        else:
            return (None, None, None, None)
        p_w,n_w = self.xform.l2w_point(p), self.xform.l2w_normal(n)
        d_w = (ray.o - p_w).length
        if math.isinf(d_w) or math.isnan(d_w): return (None, None, None, None)
        return (p_w,n_w,i,d_w)

    def raycast_all(self, ray:Ray):
        l2w_point,l2w_normal = self.xform.l2w_point,self.xform.l2w_normal
        ray_local = self.xform.w2l_ray(ray)
        hits = []
        origin,direction,maxdist = ray_local.o,ray_local.d,ray_local.max
        dist = 0
        while True:
            p,n,i,d = self.get_bvh().ray_cast(origin, direction, maxdist)
            if not p: break
            p,n = l2w_point(p),l2w_normal(n)
            d = (origin - p).length
            dist += d
            hits.append((p, n, i, dist))
            origin += direction * (d + 0.00001)
            maxdist -= d
        return hits

    @profiler.function
    def raycast_hit(self, ray:Ray, *, ignore_backface=False, backface_push=0.00001, max_backface_pushes=20):
        ray_local = self.xform.w2l_ray(ray)
        for _ in range(max_backface_pushes):
            p,n,i,d = self.get_bvh().ray_cast(ray_local.o, ray_local.d, ray_local.max)
            if not p: return False
            if not (ignore_backface and n.dot(ray_local.d) > 0): break
            ray_local.max -= (p - ray_local.o).length
            ray_local.o = p + ray_local.d * backface_push
        else:
            return False
        return True

    def nearest(self, point:Point, max_dist=float('inf')): #sys.float_info.max):
        point_local = self.xform.w2l_point(point)
        p,n,i,_ = self.get_bvh().find_nearest(point_local, max_dist)
        if p is None: return (None,None,None,None)
        wp,wn = self.xform.l2w_point(p), self.xform.l2w_normal(n)
        d = (point - wp).length
        return (wp,wn,i,d)

    def nearest_bmvert_Point(self, point:Point, verts=None):
        if verts is None:
            verts = [bmv for bmv in self.bme.verts if bmv.is_valid and not bmv.hide]
        else:
            verts = [self._unwrap(bmv) for bmv in verts if bmv.is_valid and not bmv.hide]
        point_local = self.xform.w2l_point(point)
        bv,bd = None,None
        for bmv in verts:
            d3d = (bmv.co - point_local).length
            if bv is None or d3d < bd: bv,bd = bmv,d3d
        bmv_world = self.xform.l2w_point(bv.co)
        return (self._wrap_bmvert(bv),(point-bmv_world).length)

    def nearest_bmverts_Point(self, point:Point, dist3d:float, bmverts=None):
        nearest = []
        unwrap = bmverts is not None
        for bmv in (bmverts or self.bme.verts):
            if bmv.hide: continue
            if not bmv.is_valid: continue
            if unwrap: bmv = self._unwrap(bmv)
            bmv_world = self.xform.l2w_point(bmv.co)
            d3d = (bmv_world - point).length
            if d3d > dist3d: continue
            nearest.append((self._wrap_bmvert(bmv), d3d))
        return nearest

    def nearest_bmedge_Point(self, point:Point, edges=None):
        if edges is None:
            edges = [bme for bme in self.bme.edges if bme.is_valid and not bme.hide]
        else:
            edges = [self._unwrap(bme) for bme in edges if bme.is_valid and not bme.hide]
        l2w_point = self.xform.l2w_point
        be,bd,bpp = None,None,None
        for bme in self.bme.edges:
            bmv0,bmv1 = l2w_point(bme.verts[0].co), l2w_point(bme.verts[1].co)
            diff = bmv1 - bmv0
            l = diff.length
            d = diff / l
            pp = bmv0 + d * max(0, min(l, (point - bmv0).dot(d)))
            dist = (point - pp).length
            if be is None or dist < bd: be,bd,bpp = bme,dist,pp
        if be is None: return (None,None)
        return (self._wrap_bmedge(be), (point-self.xform.l2w_point(bpp)).length)

    def nearest_bmedges_Point(self, point:Point, dist3d:float):
        l2w_point = self.xform.l2w_point
        nearest = []
        for bme in self.bme.edges:
            if not bme.is_valid: continue
            if bme.hide: continue
            bmv0,bmv1 = l2w_point(bme.verts[0].co), l2w_point(bme.verts[1].co)
            diff = bmv1 - bmv0
            l = diff.length
            d = diff / l
            pp = bmv0 + d * max(0, min(l, (point - bmv0).dot(d)))
            dist = (point - pp).length
            if dist > dist3d: continue
            nearest.append((self._wrap_bmedge(bme), dist))
        return nearest

    def nearest2D_bmverts_Point2D(self, xy:Point2D, dist2D:float, Point_to_Point2Ds, *, verts=None, fwd=None):
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        if verts is None:
            verts = [bmv for bmv in self.bme.verts if bmv.is_valid and not bmv.hide]
        else:
            verts = [self._unwrap(bmv) for bmv in verts if bmv.is_valid and not bmv.hide]
        l2w_point, l2w_normal = self.xform.l2w_point, self.xform.l2w_normal
        nearest = []
        for bmv in verts:
            co, no = l2w_point(bmv.co), l2w_normal(bmv.normal)
            for p2d in Point_to_Point2Ds(co, no, fwd=fwd):
                if p2d is None: continue
                if (p2d - xy).length > dist2D: continue
                d3d = 0
                nearest.append((self._wrap_bmvert(bmv), d3d))
        return nearest

    def nearest2D_bmvert_Point2D(self, xy:Point2D, Point_to_Point2Ds, *, verts=None, max_dist=None, fwd=None):
        if not max_dist or max_dist < 0: max_dist = float('inf')
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        if verts is None:
            verts = [bmv for bmv in self.bme.verts if bmv.is_valid and not bmv.hide]
        else:
            verts = [self._unwrap(bmv) for bmv in verts if bmv.is_valid and not bmv.hide]
        l2w_point, l2w_normal = self.xform.l2w_point, self.xform.l2w_normal
        bv,bd = None,None
        for bmv in verts:
            co, no = l2w_point(bmv.co), l2w_normal(bmv.normal)
            for p2d in Point_to_Point2Ds(co, no, fwd=fwd):
                if p2d is None: continue
                d2d = (xy - p2d).length
                if d2d > max_dist: continue
                if bv is None or d2d < bd: bv,bd = bmv,d2d
        if bv is None: return (None,None)
        return (self._wrap_bmvert(bv),bd)

    def nearest2D_bmedges_Point2D(self, xy:Point2D, dist2D:float, Point_to_Point2Ds, *, edges=None, shorten=0.01, fwd=None):
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        if edges is None:
            edges = [bme for bme in self.bme.edges if bme.is_valid and not bme.hide]
        else:
            edges = [self._unwrap(bme) for bme in edges if bme.is_valid and not bme.hide]
        l2w_point, l2w_normal = self.xform.l2w_point, self.xform.l2w_normal
        nearest = []
        dist2D2 = dist2D**2
        s0,s1 = shorten/2,1-shorten/2
        for bme in edges:
            bmv0, bmv1 = bme.verts
            co0, no0 = l2w_point(bmv0.co), l2w_normal(bmv0.normal)
            co1, no1 = l2w_point(bmv1.co), l2w_normal(bmv1.normal)
            for v0, v1 in zip(Point_to_Point2Ds(co0, no0, fwd=fwd), Point_to_Point2Ds(co1, no1, fwd=fwd)):
                if not v0 or not v1: continue
                l = v0.distance_to(v1)
                if l == 0:
                    pp = v0
                else:
                    d = (v1 - v0) / l
                    pp = v0 + d * max(l*s0, min(l*s1, d.dot(xy-v0)))
                dist2 = pp.distance_squared_to(xy)
                if dist2 > dist2D2: continue
                nearest.append((self._wrap_bmedge(bme), math.sqrt(dist2)))
        return nearest

    def nearest2D_bmedge_Point2D(self, xy:Point2D, Point_to_Point2Ds, *, edges=None, shorten=0.01, max_dist=None, fwd=None):
        if not max_dist or max_dist < 0: max_dist = float('inf')
        if edges is None:
            edges = [bme for bme in self.bme.edges if bme.is_valid and not bme.hide]
        else:
            edges = [self._unwrap(bme) for bme in edges if bme.is_valid and not bme.hide]
        l2w_point, l2w_normal = self.xform.l2w_point, self.xform.l2w_normal
        be,bd,bpp = None,None,None
        for bme in edges:
            bmv0, bmv1 = bme.verts
            co0, no0 = l2w_point(bmv0.co), l2w_normal(bmv0.normal)
            co1, no1 = l2w_point(bmv1.co), l2w_normal(bmv1.normal)
            for v0, v1 in zip(Point_to_Point2Ds(co0, no0, fwd=fwd), Point_to_Point2Ds(co1, no1, fwd=fwd)):
                if v0 is None or v1 is None: continue
                diff = v1 - v0
                l = diff.length
                if l == 0:
                    dist = (xy - v0).length
                    pp = v0
                else:
                    d = diff / l
                    margin = l * shorten / 2
                    pp = v0 + d * max(margin, min(l-margin, (xy - v0).dot(d)))
                    dist = (xy - pp).length
                if dist > max_dist: continue
                if be is None or dist < bd: be,bd,bpp = bme,dist,pp
        if be is None: return (None,None)
        return (self._wrap_bmedge(be), (xy-bpp).length)

    def nearest2D_bmfaces_Point2D(self, xy:Point2D, Point_to_Point2Ds, *, faces=None, fwd=None):
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        if faces is None:
            faces = [bmf for bmf in self.bme.faces if bmf.is_valid and not bmf.hide]
        else:
            faces = [self._unwrap(bmf) for bmf in faces if bmf.is_valid and not bmf.hide]
        l2w_point, l2w_normal = self.xform.l2w_point, self.xform.l2w_normal
        nearest = []
        for bmf in faces:
            ptsets = [Point_to_Point2Ds(l2w_point(bmv.co), l2w_normal(bmv.normal), fwd=fwd) for bmv in bmf.verts]
            ptsets = list(zip(*ptsets))
            for pts in ptsets:
                pts = [pt for pt in pts if pt]
                if len(pts) < 3: continue
                pt0 = pts[0]
                # TODO: Get dist?
                for pt1,pt2 in zip(pts[1:-1],pts[2:]):
                    if intersect_point_tri_2d(xy, pt0, pt1, pt2):
                        nearest.append((self._wrap_bmface(bmf), dist))
        return nearest

    def nearest2D_bmface_Point2D(self, forward:Direction, xy:Point2D, Point_to_Point2Ds, *, faces=None, fwd=None):
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        if faces is None:
            faces = [bmf for bmf in self.bme.faces if bmf.is_valid and not bmf.hide]
        else:
            faces = [self._unwrap(bmf) for bmf in faces if bmf.is_valid and not bmf.hide]
        l2w_point, l2w_normal = self.xform.l2w_point, self.xform.l2w_normal
        bv,bd = None,None
        best_d = float('inf')
        best_f = None
        for bmf in faces:
            ptsets = [Point_to_Point2Ds(l2w_point(bmv.co), l2w_normal(bmv.normal), fwd=fwd) for bmv in bmf.verts]
            ptsets = list(zip(*ptsets))
            for pts in ptsets:
                pts = [pt for pt in pts if pt]
                if len(pts) < 3: continue
                pt0 = pts[0]
                for pt1,pt2 in zip(pts[1:-1],pts[2:]):
                    if intersect_point_tri_2d(xy, pt0, pt1, pt2):
                        f = self._wrap_bmface(bmf)
                        d = forward.dot(f.center())
                        if d < best_d: best_d, best_f = d, f
        if not best_f: return (None, None)
        return (best_f, 0)


    ##########################################################

    fn_is_valid               = lambda bmelem: bmelem.is_valid
    fn_is_hidden              = lambda bmelem: bmelem.is_valid and bmelem.hide
    fn_is_revealed            = lambda bmelem: not bmelem.hide
    fn_is_valid_revealed      = lambda bmelem: bmelem.is_valid and not bmelem.hide
    fn_is_selected            = lambda bmelem: bmelem.is_valid and bmelem.select
    fn_is_unselected          = lambda bmelem: bmelem.is_valid and not bmelem.select
    fn_is_selected_revealed   = lambda bmelem: bmelem.is_valid and bmelem.select     and not bmelem.hide
    fn_is_unselected_revealed = lambda bmelem: bmelem.is_valid and not bmelem.select and not bmelem.hide

    def _iter_visible_verts(self, is_vis, bmvs=None):
        if bmvs is None: bmvs = self.bme.verts
        return filter(is_vis, filter(RFMesh.fn_is_revealed, bmvs))

    def _iter_visible_edges(self, is_vis, bmvs=None, bmes=None):
        if bmvs is None: bmvs = set(self._iter_visible_verts(is_vis))
        if bmes is None: bmes = self.bme.edges
        has_vis_verts = lambda bme: all(bmv in bmvs for bmv in bme.verts)
        return filter(has_vis_verts, filter(RFMesh.fn_is_revealed, bmes))

    def _iter_visible_faces(self, is_vis, bmvs=None):
        if bmvs is None: bmvs = set(self._iter_visible_verts(is_vis))
        has_vis_verts = lambda bmf: all(bmv in bmvs for bmv in bmf.verts)
        return filter(has_vis_verts, filter(RFMesh.fn_is_revealed, self.bme.faces))

    def _gen_is_vis(self, is_visible):
        l2w_point, l2w_normal = self.xform.l2w_point, self.xform.l2w_normal
        m = 0.002 * options['normal offset multiplier']
        is_valid_revealed = RFMesh.fn_is_valid_revealed
        def is_vis(bmv):
            if not is_valid_revealed(bmv): return False
            p, n = l2w_point(bmv.co), l2w_normal(bmv.normal)
            return is_visible(p, n) or is_visible(p + m * n, n)
        return is_vis

    def _gen_is_vis_fast(self, screen_margin=0) -> callable:
        # Get mesh data
        matrix_world = self.obj.matrix_world
        matrix_normal = matrix_world.inverted_safe().transposed().to_3x3()
        
        # Get view parameters
        actions = Actions.get_instance(None)
        if actions is None:
            raise Exception("No actions instance found")
        r3d = actions.r3d
        view_matrix = r3d.view_matrix
        proj_matrix = r3d.window_matrix @ view_matrix

        # Get view direction based on view type
        if r3d.is_perspective:
            view_position = r3d.view_matrix.inverted().translation
        else:
            view_vector = r3d.view_matrix.inverted().col[2].xyz

        vis_func = RFMesh.fn_is_valid_revealed

        def _check_vert_vis(v: RFVert | BMVert) -> bool:
            if not vis_func(v):
                return False

            # Get world space position and normal
            world_pos = matrix_world @ v.co
            world_normal = (matrix_normal @ v.normal).normalized()

            # Check normal direction relative to view
            if r3d.is_perspective:
                view_dir = (world_pos - view_position).normalized()
            else:
                view_dir = view_vector

            # Skip if normal is facing away (dot product > 0 means angle > 90°)
            if world_normal.dot(view_dir) > 0:
                return False

            # Project point to screen space
            screen_pos = proj_matrix @ world_pos.to_4d()
            if screen_pos.w <= 0.0:  # Behind camera
                return False

            # Perform perspective divide
            screen_pos = screen_pos.to_3d() / screen_pos.w

            # Check if point is within view bounds (including margin)
            if abs(screen_pos.x) > 1 + screen_margin or \
            abs(screen_pos.y) > 1 + screen_margin:
                return False

            return True

        return _check_vert_vis

    @timing
    def visible_verts(self, is_visible, verts=None):
        if USE_CYTHON:
            # NEW - faster - METHOD. :D
            if verts is None or len(verts) == 0:
                if len(self.bme.verts) == 0:
                    return set()
                try:
                    self.bme.verts[0]
                except IndexError:
                    # BMElemSeq[index]: outdated internal index table, run ensure_lookup_table() first
                    self.bme.verts.ensure_lookup_table()
                verts = self.bme.verts

            '''is_vis = self._gen_is_vis()
            return {bmv for bmv in verts if is_vis(bmv)}'''

            return self.get_visible_vertices(verts)

        else:
            # OLD - slower - METHOD. D:
            is_vis = self._gen_is_vis(is_visible)
            verts = self.bme.verts if verts is None else map(self._unwrap, verts)
            return { self._wrap_bmvert(bmv) for bmv in filter(is_vis, verts) }

    @timing
    def get_visible_vertices(self, verts, screen_margin=0):
        """
        Get list of visible vertex indices for an object in the current 3D view.
        """
        # Add check for empty mesh
        mesh = self.obj.data
        if len(mesh.vertices) == 0:
            return set()  # Return empty set if no vertices exist

        with time_it("prepare data", enabled=True):
            # Get mesh data
            matrix_world = np.array(self.obj.matrix_world, dtype=np.float32)
            matrix_normal = np.array(self.obj.matrix_world.inverted_safe().transposed().to_3x3(), dtype=np.float32)
            
            # Get view parameters
            actions = Actions.get_instance(None)
            if actions is None:
                raise Exception("No actions instance found")
            r3d = actions.r3d
            
            # Pre-compute matrices and view parameters
            view_matrix = r3d.view_matrix
            proj_matrix = np.array(r3d.window_matrix @ view_matrix, dtype=np.float32)
            is_perspective = r3d.is_perspective
            
            if is_perspective:
                view_pos = np.array(view_matrix.inverted().translation, dtype=np.float32)
            else:
                view_pos = np.array(view_matrix.inverted().col[2].xyz, dtype=np.float32)

            ''' # rfmesh_visibility.pyx
            verts_list = list(verts) if isinstance(verts, set) else verts

            # Get mesh vertex data pointers
            vert_ptr = mesh.vertices[0].as_pointer()
            norm_ptr = mesh.vertex_normals[0].as_pointer()
            num_vertices = len(mesh.vertices)

            # Create mapping from vertex index to position in verts_list
            vert_indices = np.array([v.index for v in verts_list], dtype=np.int32)
            process_all_verts = len(mesh.vertices) == len(verts_list)
            '''

        with time_it("compute visible vertices (Cython):", enabled=True):
            return compute_visible_vertices(
                self.bme,
                list(verts),  # RF's BMVert
                matrix_world,
                matrix_normal,
                proj_matrix,
                view_pos,
                is_perspective,
                float(1 + screen_margin)
            )

        ''' # rfmesh_visibility.pyx
            visible_flags = compute_visible_vertices(
                vert_ptr,
                norm_ptr, 
                num_vertices,
                process_all_verts,
                vert_indices,
                matrix_world,
                matrix_normal,
                proj_matrix,
                view_pos,
                is_perspective,
                float(1 + screen_margin)
            )
        
        # Convert visibility flags to vertex set
        if len(visible_flags) == 0:
            return set()

        with time_it("convert indices to vertex set", enabled=True):
            # Create mapping from vertex index to verts_list position
            vert_idx_to_pos = {v.index: i for i, v in enumerate(verts_list)}
            # Get indices where visible_flags is 1
            visible_indices = np.where(visible_flags)[0]
            # Convert vertex indices to verts_list positions
            visible_positions = [vert_idx_to_pos[i] for i in visible_indices if i in vert_idx_to_pos]
            return {verts_list[i] for i in visible_positions}
        '''

    @timing
    def visible_edges(self, is_visible, verts=None, edges=None):
        if USE_CYTHON:
            if edges is None or len(edges) == 0:
                if len(self.bme.edges) == 0:
                    return set()
                try:
                    self.bme.edges[0]
                except IndexError:
                    # BMElemSeq[index]: outdated internal index table, run ensure_lookup_table() first
                    self.bme.edges.ensure_lookup_table()
                edges = map(self._wrap_bmedge, self.bme.edges)

            is_valid = RFMesh.fn_is_valid

            # Edge is visible if ANY of its vertices are visible
            if verts is None:
                verts = self.visible_verts(None)
            return set([bme for bme in edges if is_valid(bme) and\
                (bme.verts[0] in verts or bme.verts[1] in verts)])
            
            '''
            is_vis = self._gen_is_vis()
            
            return {bme for bme in edges if is_valid(bme) and\
                (is_vis(bme.verts[0]) or is_vis(bme.verts[1]))}
            '''
        else:
            is_valid = RFMesh.fn_is_valid

            # Get visible vertices first
            if verts:
                vis_verts = set(map(self._unwrap, verts))
            else:
                is_vert_vis = self._gen_is_vis(is_visible)
                vis_verts = set(bmv for bmv in self.bme.verts if is_vert_vis(bmv))

            is_edge_vis = lambda bme: is_valid(bme) and any(bmv in vis_verts for bmv in bme.verts)
            edges = self.bme.edges if edges is None else map(self._unwrap, edges)
            return { self._wrap_bmedge(bme) for bme in filter(is_edge_vis, edges) }

    @timing
    def visible_faces(self, is_visible, verts=None, faces=None):
        if USE_CYTHON:
            if faces is None or len(faces) == 0:
                if len(self.bme.faces) == 0:
                    return set()
                try:
                    self.bme.faces[0]
                except IndexError:
                    # BMElemSeq[index]: outdated internal index table, run ensure_lookup_table() first
                    self.bme.faces.ensure_lookup_table()
                faces = map(self._wrap_bmface, self.bme.faces)

            is_valid = RFMesh.fn_is_valid

            # Edge is visible if ANY of its vertices are visible
            if verts is None:
                verts = self.visible_verts(None)

            def _check_face_verts_vis(face: RFFace) -> bool:
                # iterate with break if any vert is visible.
                for bmv in face.verts:
                    if bmv in verts:
                        return True
                return False

            return set([face for face in faces if is_valid(face) and _check_face_verts_vis(face)])
            '''
            
            is_vis = self._gen_is_vis()
            return {face for face in faces if is_valid(face) and\
                (is_vis(face.verts[0]) or is_vis(face.verts[2]) or\
                is_vis(face.verts[1]) or is_vis(face.verts[3]))}
            '''

        else:
            is_valid = RFMesh.fn_is_valid

            # Get visible vertices first
            if verts:
                verts = set(map(self._unwrap, verts))
            else:
                is_vert_vis = self._gen_is_vis(is_visible)
                verts = set(bmv for bmv in self.bme.verts if is_vert_vis(bmv))

            is_face_vis = lambda bmf: is_valid(bmf) and all(bmv in verts for bmv in bmf.verts)
            faces = self.bme.faces if faces is None else map(self._unwrap, faces)
            return { self._wrap_bmface(bme) for bme in filter(is_face_vis, faces) }


    ##########################################################

    def iter_wrap(self, bmelems, *, wrap_fn=None):
        if wrap_fn is None: wrap_fn = self._wrap
        yield from map(wrap_fn, bmelems)
    def set_wrap(self, bmelems, *, wrap_fn=None):
        if wrap_fn is None: wrap_fn = self._wrap
        return { wrap_fn(bmelem) for bmelem in bmelems }
    def list_wrap(self, bmelems, *, wrap_fn=None):
        if wrap_fn is None: wrap_fn = self._wrap
        return [ wrap_fn(bmelem) for bmelem in bmelems ]

    def iter_verts(self): yield from self.iter_wrap(filter(RFMesh.fn_is_valid_revealed, self.bme.verts), wrap_fn=self._wrap_bmvert)
    def iter_edges(self): yield from self.iter_wrap(filter(RFMesh.fn_is_valid_revealed, self.bme.edges), wrap_fn=self._wrap_bmedge)
    def iter_faces(self): yield from self.iter_wrap(filter(RFMesh.fn_is_valid_revealed, self.bme.faces), wrap_fn=self._wrap_bmvert)

    def get_verts(self): return list(self.iter_verts())
    def get_edges(self): return list(self.iter_edges())
    def get_faces(self): return list(self.iter_faces())

    def get_vert_count(self): return len(self.bme.verts)
    def get_edge_count(self): return len(self.bme.edges)
    def get_face_count(self): return len(self.bme.faces)

    # NOTE: self.bme.select_history does _NOT_ work
    def get_selected_verts(self):   return set(map(self._wrap_bmvert, filter(RFMesh.fn_is_selected_revealed,   self.bme.verts)))
    def get_selected_edges(self):   return set(map(self._wrap_bmedge, filter(RFMesh.fn_is_selected_revealed,   self.bme.edges)))
    def get_selected_faces(self):   return set(map(self._wrap_bmface, filter(RFMesh.fn_is_selected_revealed,   self.bme.faces)))
    def get_unselected_verts(self): return set(map(self._wrap_bmvert, filter(RFMesh.fn_is_unselected_revealed, self.bme.verts)))
    def get_unselected_edges(self): return set(map(self._wrap_bmedge, filter(RFMesh.fn_is_unselected_revealed, self.bme.edges)))
    def get_unselected_faces(self): return set(map(self._wrap_bmface, filter(RFMesh.fn_is_unselected_revealed, self.bme.faces)))

    def get_hidden_verts(self):   return set(map(self._wrap_bmvert, filter(RFMesh.fn_is_hidden,   self.bme.verts)))
    def get_hidden_edges(self):   return set(map(self._wrap_bmedge, filter(RFMesh.fn_is_hidden,   self.bme.edges)))
    def get_hidden_faces(self):   return set(map(self._wrap_bmface, filter(RFMesh.fn_is_hidden,   self.bme.faces)))
    def get_revealed_verts(self): return set(map(self._wrap_bmvert, filter(RFMesh.fn_is_valid_revealed, self.bme.verts)))
    def get_revealed_edges(self): return set(map(self._wrap_bmedge, filter(RFMesh.fn_is_valid_revealed, self.bme.edges)))
    def get_revealed_faces(self): return set(map(self._wrap_bmface, filter(RFMesh.fn_is_valid_revealed, self.bme.faces)))

    def any_verts_selected(self): return any(bmv.select for bmv in self.bme.verts if bmv.is_valid and not bmv.hide)
    def any_edges_selected(self): return any(bme.select for bme in self.bme.edges if bme.is_valid and not bme.hide)
    def any_faces_selected(self): return any(bmf.select for bmf in self.bme.faces if bmf.is_valid and not bmf.hide)
    def any_selected(self):       return self.any_verts_selected() or self.any_edges_selected() or self.any_faces_selected()

    def get_selection_center(self):
        v,c = Vector(),0
        for bmv in self.bme.verts:
            if not bmv.select or not bmv.is_valid: continue
            v += bmv.co
            c += 1
        if c: self.selection_center = v / c
        return self.xform.l2w_point(self.selection_center)
    def get_selection_bbox(self):
        l2w_point = self.xform.l2w_point
        coords = [l2w_point(bmv.co) for bmv in self.bme.verts if bmv.is_valid and bmv.select]
        #if not coords: return self.get_bbox()
        return BBox(from_coords=coords)

    def deselect_all(self):
        for bmv in self.bme.verts: bmv.select = False
        for bme in self.bme.edges: bme.select = False
        for bmf in self.bme.faces: bmf.select = False
        self.dirty(selectionOnly=True)

    def deselect(self, elems, supparts=True, subparts=True):
        if elems is None: return
        if not hasattr(elems, '__len__'): elems = [elems]
        elems = { e for e in elems if e and e.is_valid }
        nelems = set(elems)
        if supparts:
            for elem in elems:
                t = type(elem)
                if t is BMVert or t is RFVert:
                    nelems.update(elem.link_edges)
                    nelems.update(elem.link_faces)
                elif t is BMEdge or t is RFEdge:
                    nelems.update(elem.link_faces)
                elif t is BMFace or t is RFFace:
                    pass
        nelems = { e for e in nelems if e.select }
        selems = set()
        for elem in nelems-elems:
            t = type(elem)
            if t is BMEdge or t is RFEdge:
                selems.update(elem.verts)
            elif t is BMFace or t is RFFace:
                selems.update(elem.verts)
                selems.update(e for e in elem.edges if not (set(e.verts)&elems))
        selems = selems - elems
        selems = { e for e in selems if e.select }
        for elem in nelems: elem.select = False
        for elem in selems: elem.select = True
        if subparts:
            nelems = set()
            for elem in elems:
                t = type(elem)
                if t is BMFace or t is RFFace:
                    for bme in elem.edges:
                        if not bme.select: continue
                        if any(f.select for f in bme.link_faces): continue
                        nelems.add(bme)
                    for bmv in elem.verts:
                        if not bmv.select: continue
                        if any(e.select for e in bmv.link_edges): continue
                        if any(f.select for f in bmv.link_faces): continue
                        nelems.add(bmv)
                if t is BMEdge or t is RFEdge:
                    for bmv in elem.verts:
                        if not bmv.select: continue
                        if any(e.select for e in bmv.link_edges): continue
                        if any(f.select for f in bmv.link_faces): continue
                        nelems.add(bmv)
            for elem in nelems:
                elem.select = False
        self.dirty(selectionOnly=True)

    def select(self, elems, supparts=True, subparts=True, only=True):
        if only: self.deselect_all()
        if elems is None: return
        if not hasattr(elems, '__len__'): elems = [elems]
        elems = [e for e in elems if e and e.is_valid]
        if subparts:
            nelems = set(elems)
            for elem in elems:
                t = type(elem)
                if t is BMVert or t is RFVert:
                    pass
                elif t is BMEdge or t is RFEdge:
                    nelems.update(e for e in elem.verts)
                elif t is BMFace or t is RFFace:
                    nelems.update(e for e in elem.verts)
                    nelems.update(e for e in elem.edges)
            elems = nelems
        for elem in elems: elem.select = True
        if supparts:
            for elem in elems:
                t = type(elem)
                if t is not BMVert and t is not RFVert: continue
                for bme in elem.link_edges:
                    if all(bmv.select for bmv in bme.verts):
                        bme.select = True
                for bmf in elem.link_faces:
                    if all(bmv.select for bmv in bmf.verts):
                        bmf.select = True
        self.dirty(selectionOnly=True)

    def get_quadwalk_edgesequence(self, edge):
        bme = self._unwrap(edge)
        touched = set()
        edges = []
        def crawl(bme0, bmv01):
            nonlocal edges
            if bme0 not in touched: edges.append(bme0)
            if bmv01 in touched: return True        # wrapped around the loop
            touched.add(bmv01)
            touched.add(bme0)
            if len(bmv01.link_edges) > 4: return False
            if len(bmv01.link_faces) > 4: return False
            bmf0 = bme0.link_faces
            for bme1 in bmv01.link_edges:
                if any(f in bmf0 for f in bme1.link_faces): continue
                bmv2 = bme1.other_vert(bmv01)
                return crawl(bme1, bmv2)
            return False
        if not crawl(bme, bme.verts[0]):
            # did not loop back around, so go other direction
            edges.reverse()
            crawl(bme, bme.verts[1])
        return RFEdgeSequence(edges)

    def _crawl_quadstrip_next(self, bme0, bmf0):
        bmes = set(bmf0.edges) - { bme for bmv in bme0.verts for bme in bmv.link_edges }
        if len(bmes) != 1: return (None,None)
        bme1 = bmes.pop()
        bmf1 = next(iter(set(bme1.link_faces) - { bmf0 }), None)
        return (bme1, bmf1)

    def _are_edges_flipped(self, bme0, bme1):
        bmv00,bmv01 = bme0.verts
        bmv10,bmv11 = bme1.verts
        return ((bmv01.co - bmv00.co).dot(bmv11.co - bmv10.co)) < 0

    def _crawl_quadstrip_to_loopend(self, bme_start, bmf_start=None):
        '''
        returns tuple (bme, flipped, bmf, looped) where bme is
        1. at one end of a quad strip (looped == False), or
        2. bme is bme0 because quad strip is loop (looped == True)
        bmf is the next face going back (for retracing)
        flipped indicates if bme is revered wrt to bme_start
        '''

        # choose one of the faces
        if not bmf_start: bmf_start = next(iter(bme_start.link_faces), None)
        if not bmf_start: return (None, False, None, False)

        bme0,bmf0,flipped = bme_start,bmf_start,False
        touched = set() # just in case!
        '''
        ....
        O--O
        |  |
        O--O <- bme0
        |  | <- bmf0
        O--O <- bme1
        |  | <- bmf1
        O--O
        ....
        O--O <- bme0'
        |  | <- bmf0'
        O--O <- bme1', which is end of quad-strip!
        '''
        while bme0 not in touched:
            touched.add(bme0)
            bme1,bmf1 = self._crawl_quadstrip_next(bme0, bmf0)
            if not bme1:
                # bmf0 is not None, but couldn't find bme1, means that we bmf0 is not a quad
                bmf_prev = next(iter(set(bme0.link_faces) - { bmf0 }), None)
                return (bme0, flipped, bmf_prev, False)
            if self._are_edges_flipped(bme0, bme1): flipped = not flipped
            if not bmf1:
                # hit end of quad-strip
                return (bme1, flipped, bmf0, False)
            if bme1 == bme_start:
                # looped back around
                return (bme_start, False, bmf_start, True)
            bme0,bmf0 = bme1,bmf1
        # we wrapped back around
        return (bme0, flipped, bmf0, True)

    def is_quadstrip_looped(self, edge):
        edge = self._unwrap(edge)
        _,_,_,looped = self._crawl_quadstrip_to_loopend(edge)
        return looped

    def iter_quadstrip(self, edge):
        # crawl around until either 1) loop back around, or 2) hit end
        # then, go back the other direction
        # note: the bmesh may change while crawling!
        edge = self._unwrap(edge)
        bme,flipped,bmf,looped = self._crawl_quadstrip_to_loopend(edge)
        if not bme: return
        bme_start = bme
        bmf_start = bmf
        touched = set()
        while bmf not in touched and bme not in touched:
            touched.add(bmf)
            touched.add(bme)
            # find next bme and bmf, in case bmesh is edited!
            if bmf: bme_next,bmf_next = self._crawl_quadstrip_next(bme, bmf)
            yield (self._wrap_bmedge(bme), flipped)
            if not bmf: break
            if not bme_next: break
            if bme_next == bme_start: break
            if bmf_next == bmf_start: break
            if self._are_edges_flipped(bme, bme_next): flipped = not flipped
            bme,bmf = bme_next,bmf_next

    def get_face_loop(self, edge):
        r'''
              +--  this diamond quad causes problems!
              |
              V
        O-----O-----O
        |    / \    |
        O---O   O---O
           / \ / \
          /   O   \
         /   / \   \
        O---O   O---O
         \   \ /   /
          \   O   /
           \  |  /
            \ | /
             \|/
              O
        '''
        is_looped = self.is_quadstrip_looped(edge)
        edges = list(bme for bme,_ in self.iter_quadstrip(edge))
        return (edges, is_looped)

    def get_edge_loop(self, edge):
        touched = set()
        edges = [edge]

        r'''
        description of crawl(bme0, bmv01) below...
        given: bme0=A, bmv01=B
        find:  bme1=C, bmv12=D

        O-----O-----O...     O-----O-----O...
        |     |     |        |     |     |
        O--A--B--C--D...     O--A--B--C--O...
        |  ^0 |  ^1 |        |     |\
        O-----O-----O...     O-----O O...
                                    \|
                                     O...
               crawl dir: ======>

        left : "normal" case, where B is part of 4 touching quads
        right: here, find the edge with the direction most similarly
               pointing in same direction
        '''
        def crawl(bme0, bmv01):
            nonlocal edges, touched
            while True:
                bme1 = bme0.get_next_edge_in_strip(bmv01)
                if not bme1:
                    # could not find next edge to continue crawling
                    # hit edge of mesh?
                    return False
                if bme1 in touched:
                    # wrapped around (edge loop)!
                    # NOTE: should trim off any strip not part of loop?  ex: P-shaped
                    return True
                edges.append(bme1)
                touched.add(bme1)
                bmv01 = bme1.other_vert(bmv01)
                bme0 = bme1
        loop = crawl(edge, edge.verts[0])
        if not loop:
            # edge strip
            edges.reverse()
            loop = crawl(edge, edge.verts[1])
        return (edges, loop)

    def get_inner_edge_loop(self, edge):
        # returns edge loop that follows the inside, boundary
        bme = self._unwrap(edge)
        if len(bme.link_faces) != 1: return ([], False)
        touched = set()
        edges = []
        def crawl(bme0, bmv01):
            nonlocal edges
            if bme0 not in touched: edges.append(self._wrap_bmedge(bme0))
            if bmv01 in touched: return True
            touched.add(bmv01)
            touched.add(bme0)
            bmf0 = bme0.link_faces
            for bme1 in bmv01.link_edges:
                if bme1 == bme0: continue
                if len(bme1.link_faces) != 1: continue
                if any(f in bmf0 for f in bme1.link_faces): continue
                bmv2 = bme1.other_vert(bmv01)
                return crawl(bme1, bmv2)
            return False
        if crawl(bme, bme.verts[0]): return (edges, True)
        edges.reverse()
        crawl(bme, bme.verts[1])
        return (edges, False)

    def select_all(self):
        for bmv in self.bme.verts: bmv.select = True
        for bme in self.bme.edges: bme.select = True
        for bmf in self.bme.faces: bmf.select = True
        self.dirty(selectionOnly=True)

    def select_toggle(self):
        sel = self.any_verts_selected() or self.any_edges_selected() or self.any_faces_selected()
        if sel: self.deselect_all()
        else:   self.select_all()

    def select_invert(self):
        if True:
            sel_verts = [bmv for bmv in self.bme.verts if not bmv.select]
            for bmf in self.bme.faces: bmf.select = all(bmv in sel_verts for bmv in bmf.verts)
            for bme in self.bme.edges: bme.select = all(bmv in sel_verts for bmv in bme.verts)
            for bmv in self.bme.verts: bmv.select = (bmv in sel_verts)
        else:
            for bmv in self.bme.verts: bmv.select = not bmv.select
            for bme in self.bme.edges: bme.select = not bme.select
            for bmf in self.bme.faces: bmf.select = not bmf.select
        self.dirty()

    def select_linked(self, *, select=True, connected_to=None):
        if connected_to is None:
            # if None, use current selection
            working = set(self.get_selected_verts())
        elif type(connected_to) is set or type(connected_to) is list:
            working = set(connected_to)
        elif isinstance(connected_to, RFVert) or isinstance(connected_to, RFEdge) or isinstance(connected_to, RFFace):
            working = { connected_to }
        else:
            assert False, f'Unhandled type of connected_to: {connected_to}'
        pworking, working = working, set()
        for e in pworking:
            if isinstance(e, RFVert) or isinstance(e, BMVert):
                working.add(e)
            else:
                for v in e.verts:
                    working.add(v)
        linked_verts = set(working)
        while working:
            bmv = working.pop()
            for bme in bmv.link_edges:
                bmvo = bme.other_vert(bmv)
                if bmvo in linked_verts: continue
                working.add(bmvo)
                linked_verts.add(bmvo)
        for bmv in linked_verts:
            bmv.select = select
            for bme in bmv.link_edges:
                bme.select = select
            for bmf in bmv.link_faces:
                bmf.select = select
        self.dirty()


class RFSource(RFMesh):
    '''
    RFSource is a source object for RetopoFlow.  Source objects
    are the high-resolution meshes being retopologized.
    '''

    __cache = {}

    @staticmethod
    @profiler.function
    def new(obj:bpy.types.Object):
        # TODO: REIMPLEMENT CACHING!!
        #       HAD TO DISABLE THIS BECAUSE 2.83 AND 2.90 WOULD CRASH
        #       WHEN RESTARTING RF.  PROBABLY DUE TO HOLDING REFS TO
        #       OLD DATA (CRASH DUE TO FREEING INVALID DATA??)

        assert type(obj) is bpy.types.Object and type(obj.data) is bpy.types.Mesh, 'obj must be mesh object'

        # check cache
        rfsource = None
        if False:
            if obj.data.name in RFSource.__cache:
                # does cache match current state?
                rfsource = RFSource.__cache[obj.data.name]
                hashed = hash_object(obj)
                if rfsource.hash != hashed:
                    rfsource = None
            if not rfsource:
                # need to (re)generate RFSource object
                RFSource.creating = True
                rfsource = RFSource()
                del RFSource.creating
                rfsource.__setup__(obj)
                RFSource.__cache[obj.data.name] = rfsource
            else:
                rfsource = RFSource.__cache[obj.data.name]
        else:
            RFSource.creating = True
            rfsource = RFSource()
            del RFSource.creating
            rfsource.__setup__(obj)

        return rfsource

    def __init__(self):
        assert hasattr(RFSource, 'creating'), 'Do not create new RFSource directly!  Use RFSource.new()'
        RFMesh.create_count += 1
        # print('RFSource.__init__', RFMesh.create_count, RFMesh.delete_count)

    def __setup__(self, obj:bpy.types.Object):
        super().__setup__(obj, deform=True, triangulate=True, selection=False, keepeme=True)
        self.mirror_mod = None
        self.ensure_lookup_tables()

    def __str__(self):
        return '<RFSource %s>' % self.obj.name

    @property
    def layer_pin(self):
        return None



class RFTarget(RFMesh):
    '''
    RFTarget is a target object for RetopoFlow.  Target objects
    are the low-resolution, retopologized meshes.
    '''

    @staticmethod
    @profiler.function
    def new(obj:bpy.types.Object, unit_scaling_factor):
        assert type(obj) is bpy.types.Object and type(obj.data) is bpy.types.Mesh, f'{obj} must be mesh object'

        RFTarget.creating = True
        rftarget = RFTarget()
        del RFTarget.creating
        rftarget.__setup__(obj, unit_scaling_factor=unit_scaling_factor)
        rftarget.rewrap()

        return rftarget

    def __init__(self):
        assert hasattr(RFTarget, 'creating'), 'Do not create new RFTarget directly!  Use RFTarget.new()'
        RFMesh.create_count += 1
        # print('RFTarget.__init__', RFMesh.create_count, RFMesh.delete_count)

    def __str__(self):
        return '<RFTarget %s>' % self.obj.name

    def __setup__(self, obj:bpy.types.Object, unit_scaling_factor:float, rftarget_copy=None):
        bme = rftarget_copy.bme.copy() if rftarget_copy else None
        xy_symmetry_accel = rftarget_copy.xy_symmetry_accel if rftarget_copy else None
        xz_symmetry_accel = rftarget_copy.xz_symmetry_accel if rftarget_copy else None
        yz_symmetry_accel = rftarget_copy.yz_symmetry_accel if rftarget_copy else None

        super().__setup__(obj, bme=bme, deform=False)
        # if Mirror modifier is attached, set up symmetry to match
        self.setup_mirror()
        self.setup_displace()

        self.editmesh_version = None
        self.xy_symmetry_accel = xy_symmetry_accel
        self.xz_symmetry_accel = xz_symmetry_accel
        self.yz_symmetry_accel = yz_symmetry_accel
        self.unit_scaling_factor = unit_scaling_factor

    @property
    def layer_pin(self):
        il = self.bme.verts.layers.int
        return il['pin'] if 'pin' in il else il.new('pin')

    def setup_mirror(self):
        self.mirror_mod = ModifierWrapper_Mirror.get_from_object(self.obj)
        if not self.mirror_mod:
            self.mirror_mod = ModifierWrapper_Mirror.create_new(self.obj)

    def setup_displace(self):
        self.displace_mod = None
        self.displace_strength = 0.020
        for mod in self.obj.modifiers:
            if mod.type == 'DISPLACE':
                self.displace_mod = mod
                self.displace_strength = mod.strength
        if not self.displace_mod:
            bpy.ops.object.modifier_add(type='DISPLACE')
            self.displace_mod = self.obj.modifiers[-1]
            self.displace_mod.show_expanded = False
            self.displace_mod.strength = self.displace_strength
            self.displace_mod.show_render = False
            self.displace_mod.show_viewport = False

    def set_symmetry_accel(self, xy_symmetry_accel, xz_symmetry_accel, yz_symmetry_accel):
        self.xy_symmetry_accel = xy_symmetry_accel
        self.xz_symmetry_accel = xz_symmetry_accel
        self.yz_symmetry_accel = yz_symmetry_accel

    def get_point_symmetry(self, point, from_world=True):
        if from_world: point = self.xform.w2l_point(point)
        px,py,pz = point
        threshold = self.mirror_mod.symmetry_threshold * self.unit_scaling_factor / 2.0
        symmetry = set()
        if self.mirror_mod.x and  px <= threshold: symmetry.add('x')
        if self.mirror_mod.y and -py <= threshold: symmetry.add('y')
        if self.mirror_mod.z and  pz <= threshold: symmetry.add('z')
        return symmetry

    def check_symmetry(self):
        threshold = self.mirror_mod.symmetry_threshold * self.unit_scaling_factor / 2.0
        ret = list()
        if self.mirror_mod.x and any(bmv.co.x < -threshold for bmv in self.bme.verts): ret.append('X')
        if self.mirror_mod.y and any(bmv.co.y >  threshold for bmv in self.bme.verts): ret.append('Y')
        if self.mirror_mod.z and any(bmv.co.z < -threshold for bmv in self.bme.verts): ret.append('Z')
        return ret

    def select_bad_symmetry(self):
        threshold = self.mirror_mod.symmetry_threshold * self.unit_scaling_factor / 2.0
        for bmv in self.bme.verts:
            if self.mirror_mod.x and bmv.co.x < -threshold: bmv.select = True
            if self.mirror_mod.y and bmv.co.y >  threshold: bmv.select = True
            if self.mirror_mod.z and bmv.co.z < -threshold: bmv.select = True

    def snap_to_symmetry(self, point, symmetry, from_world=True, to_world=True):
        if not symmetry and from_world == to_world: return point
        if from_world: point = self.xform.w2l_point(point)
        if symmetry:
            dist = lambda p: (p - point).length_squared
            px,py,pz = point
            if 'x' in symmetry:
                edges = self.yz_symmetry_accel.get_edges(Point2D((py, pz)), -px)
                point = min((e.closest(point) for e in edges), key=dist, default=Point((0, py, pz)))
                px,py,pz = point
            if 'y' in symmetry:
                edges = self.xz_symmetry_accel.get_edges(Point2D((px, pz)), py)
                point = min((e.closest(point) for e in edges), key=dist, default=Point((px, 0, pz)))
                px,py,pz = point
            if 'z' in symmetry:
                edges = self.xy_symmetry_accel.get_edges(Point2D((px, py)), -pz)
                point = min((e.closest(point) for e in edges), key=dist, default=Point((px, py, 0)))
                px,py,pz = point
        if to_world: point = self.xform.l2w_point(point)
        return point

    def symmetry_real(self, point:Point, from_world=True, to_world=True):
        if from_world: point = self.xform.w2l_point(point)
        dist = lambda p: (p - point).length_squared
        px,py,pz = point
        threshold = self.mirror_mod.symmetry_threshold * self.unit_scaling_factor / 2.0
        if self.mirror_mod.x and px <= threshold:
            edges = self.yz_symmetry_accel.get_edges(Point2D((py, pz)), -px)
            point = min((e.closest(point) for e in edges), key=dist, default=Point((0, py, pz)))
            px,py,pz = point
        if self.mirror_mod.y and py >= threshold:
            edges = self.xz_symmetry_accel.get_edges(Point2D((px, pz)), py)
            point = min((e.closest(point) for e in edges), key=dist, default=Point((px, 0, pz)))
            px,py,pz = point
        if self.mirror_mod.z and pz <= threshold:
            edges = self.xy_symmetry_accel.get_edges(Point2D((px, py)), -pz)
            point = min((e.closest(point) for e in edges), key=dist, default=Point((px, py, 0)))
            px,py,pz = point
        if to_world: point = self.xform.l2w_point(point)
        return point

    def __deepcopy__(self, memo):
        '''
        custom deepcopy method, because BMesh and BVHTree are not copyable
        '''
        rftarget = RFTarget.__new__(RFTarget)
        memo[id(self)] = rftarget
        rftarget.__setup__(self.obj, self.unit_scaling_factor, rftarget_copy=self)
        # deepcopy all remaining settings
        for k,v in self.__dict__.items():
            if k not in {'prev_state'} and k in rftarget.__dict__: continue
            setattr(rftarget, k, copy.deepcopy(v, memo))
        return rftarget

    def to_json(self):
        data = {
            'verts': None,
            'edges': None,
            'faces': None,
            'symmetry': list(self.mirror_mod.xyz)
        }
        self.bme.verts.ensure_lookup_table()
        data['verts'] = [list(bmv.co) for bmv in self.bme.verts]
        data['edges'] = [list(bmv.index for bmv in bme.verts) for bme in self.bme.edges]
        data['faces'] = [list(bmv.index for bmv in bmf.verts) for bmf in self.bme.faces]
        return data

    def rewrap(self):
        BMElemWrapper.wrap(self)

    def commit(self):
        self.restore_state()

    def cancel(self):
        self.restore_state()


    def clean(self):
        super().clean()

        version = self.get_version()
        if self.editmesh_version == version: return
        self.editmesh_version = version

        try:
            self._clean_mesh()
            self._clean_selection()
            self._clean_mirror()
            self._clean_displace()
        except Exception as e:
            print(f'Caught Exception while trying to clean RFTarget: {e}')
            self.handle_exception(e)

    def _clean_mesh(self):
        prev_mesh = self.obj.data
        prev_mesh_name = prev_mesh.name
        new_mesh = self.obj.data.copy()
        self.bme.to_mesh(new_mesh)
        self.obj.data = new_mesh
        bpy.data.meshes.remove(prev_mesh)
        new_mesh.name = prev_mesh_name

    def _clean_selection(self):
        for bmv,emv in zip(self.bme.verts, self.obj.data.vertices):
            emv.select = bmv.select
        for bme,eme in zip(self.bme.edges, self.obj.data.edges):
            eme.select = bme.select
        for bmf,emf in zip(self.bme.faces, self.obj.data.polygons):
            emf.select = bmf.select

    def _clean_mirror(self):
        self.mirror_mod.write()

    def _clean_displace(self):
        self.displace_mod.strength = self.displace_strength


    def enable_symmetry(self, axis): self.mirror_mod.enable_axis(axis)
    def disable_symmetry(self, axis): self.mirror_mod.disable_axis(axis)
    def has_symmetry(self, axis): return self.mirror_mod.is_enabled_axis(axis)

    def apply_mirror_symmetry(self, nearest):
        out = []
        def apply_mirror_and_return_geom(axis):
            return mirror(
                self.bme,
                geom=list(self.bme.verts) + list(self.bme.edges) + list(self.bme.faces),
                merge_dist=self.mirror_mod.symmetry_threshold,
                axis=axis,
            )['geom']
        if self.mirror_mod.x: out += apply_mirror_and_return_geom('X')
        if self.mirror_mod.y: out += apply_mirror_and_return_geom('Y')
        if self.mirror_mod.z: out += apply_mirror_and_return_geom('Z')
        self.mirror_mod.x = False
        self.mirror_mod.y = False
        self.mirror_mod.z = False
        for bmv in (e for e in out if type(e) is BMVert):
            rfvert = self._wrap_bmvert(bmv)
            xyz, norm, _, _ = nearest(rfvert.co)
            if xyz is None: continue
            rfvert.co = xyz
            rfvert.normal = norm
        self.recalculate_face_normals(verts=[e for e in out if type(e) is BMVert], faces=[e for e in out if type(e) is BMFace])

    def flip_symmetry_verts_to_correct_side(self):
        for bmv in self.bme.verts:
            if self.mirror_mod.x and bmv.co.x < 0:
                bmv.co.x = -bmv.co.x
                bmv.normal.x = -bmv.normal.x
            if self.mirror_mod.y and bmv.co.y > 0:
                bmv.co.y = -bmv.co.y
                bmv.normal.y = -bmv.normal.y
            if self.mirror_mod.z and bmv.co.z < 0:
                bmv.co.z = -bmv.co.z
                bmv.normal.z = -bmv.normal.z

    def new_vert(self, co, norm):
        # assuming co and norm are in world space!
        # so, do not set co directly; need to xform to local first.
        bmv = self.bme.verts.new((0,0,0))
        rfv = self._wrap_bmvert(bmv)
        rfv.co = co
        rfv.normal = norm
        return rfv

    def new_edge(self, verts):
        verts = [self._unwrap(v) for v in verts]
        bme = self.bme.edges.new(verts)
        return self._wrap_bmedge(bme)

    def new_face(self, verts):
        # see if a face happens to exist already...
        verts = [v for v in verts if v]
        face_in_common = accumulate_last(
            (
                set(f for f in v.link_faces if f.is_valid)
                for v in verts if v.is_valid
            ), lambda s0,s1: s0 & s1
        )
        if face_in_common: return next(iter(face_in_common))
        verts = [self._unwrap(v) for v in verts]
        # make sure there are no duplicate verts (issue #957)
        # however, this _could_ reduce vert count < 3
        nverts = deduplicate_list(verts)
        if len(nverts) < 3: return None
        bmf = self.bme.faces.new(nverts)
        self.update_face_normal(bmf)
        return self._wrap_bmface(bmf)

    def merge_vertices(self, vert1, vert2, merge_point: str = 'CENTER'):
        """
        Merge two vertices together at specified position

        Args:
            vert1: First RFVert to merge
            vert2: Second RFVert to merge
            merge_point: Merge location ('CENTER', 'FIRST', or 'LAST')
        Returns:
            RFVert: The resulting merged vertex
        """
        bmv1 = self._unwrap(vert1)
        bmv2 = self._unwrap(vert2)

        # Get the merge position and normal
        if merge_point == 'CENTER':
            pos = (bmv1.co + bmv2.co) / 2
            norm = (bmv1.normal + bmv2.normal).normalized()
        elif merge_point == 'FIRST':
            pos = bmv1.co
            norm = bmv1.normal
        else:  # LAST
            pos = bmv2.co
            norm = bmv2.normal

        # Use bmesh ops to merge the verts
        pointmerge(
            self.bme,
            verts=[bmv1, bmv2],
            merge_co=pos
        )

        # Update the normal
        bmv1.normal = norm
        self.bme.normal_update()
        
        # Return wrapped vert
        return self._wrap_bmvert(bmv1)

    def holes_fill(self, edges, sides):
        edges = list(map(self._unwrap, edges))
        ret = holes_fill(self.bme, edges=edges, sides=sides)
        print('RetopoFlow holes_fill', ret)


    def merge_at_center(self, nearest):
        rfvs = list(self.get_selected_verts())
        co, norm, _, _ = nearest(Point.average(v.co for v in rfvs))
        if not co or not norm: return None
        bmvs = [self._unwrap(v) for v in rfvs]
        pointmerge(self.bme, verts=bmvs)
        rfv = self._wrap_bmvert(bmvs[0])
        rfv.co = co
        rfv.normal = norm
        rfv.select = True
        self.update_verts_faces([rfv])
        return rfv

    def collapse_edges_faces(self, nearest):
        # find all connected components
        # for each component:
        #     compute average vert position
        #     merge all selected verts to point located at average
        verts = set(self.get_selected_verts())
        edges = set(self.get_selected_edges())
        faces = set(self.get_selected_faces())
        remaining = set(verts)
        while remaining:
            working = set()
            working_next = set([ next(iter(remaining)) ])
            while working_next:
                v = working_next.pop()
                if v not in remaining: continue
                remaining.remove(v)
                working.add(v)
                for e in v.link_edges:
                    if e not in edges: continue
                    working_next |= {v_ for v_ in e.verts if v_ in remaining}
                for f in v.link_faces:
                    if f not in faces: continue
                    working_next |= {v_ for v_ in f.verts if v_ in remaining}
            average = Point.average(v.co for v in working)
            p, n, _, _ = nearest(average)
            rfv = self.new_vert(p, n)
            for v in working:
                rfv = rfv.merge_robust(v)
            rfv.co = p
            rfv.normal = n
            rfv.select = True


    def delete_selection(self, del_empty_edges=True, del_empty_verts=True, del_verts=True, del_edges=True, del_faces=True):
        if del_faces:
            faces = { f for f in self.bme.faces if f.select }
            self.delete_faces(faces, del_empty_edges=del_empty_edges, del_empty_verts=del_empty_verts)
        if del_edges:
            edges = { e for e in self.bme.edges if e.select }
            self.delete_edges(edges, del_empty_verts=del_empty_verts)
        if del_verts:
            verts = { v for v in self.bme.verts if v.select }
            self.delete_verts(verts)


    def delete_verts(self, verts):
        for bmv in map(self._unwrap, verts):
            if bmv.is_valid and not bmv.hide: self.bme.verts.remove(bmv)

    def delete_edges(self, edges, del_empty_verts=True):
        edges = { self._unwrap(e) for e in edges if e.is_valid and not e.hide }
        verts = { v for e in edges for v in e.verts }
        for bme in edges: self.bme.edges.remove(bme)
        if del_empty_verts:
            for bmv in verts:
                if len(bmv.link_edges) == 0: self.bme.verts.remove(bmv)

    def delete_faces(self, faces, del_empty_edges=True, del_empty_verts=True):
        faces = { self._unwrap(f) for f in faces if f.is_valid and not f.hide }
        edges = { e for f in faces for e in f.edges }
        verts = { v for f in faces for v in f.verts }
        for bmf in faces: self.bme.faces.remove(bmf)
        if del_empty_edges:
            for bme in edges:
                if len(bme.link_faces) == 0: self.bme.edges.remove(bme)
        if del_empty_verts:
            for bmv in verts:
                if len(bmv.link_faces) == 0: self.bme.verts.remove(bmv)

    def dissolve_verts(self, verts, use_face_split=False, use_boundary_tear=False):
        verts = [ self._unwrap(v) for v in verts if v.is_valid and not v.hide ]
        dissolve_verts(self.bme, verts=verts, use_face_split=use_face_split, use_boundary_tear=use_boundary_tear)

    def dissolve_edges(self, edges, use_verts=True, use_face_split=False):
        edges = [ self._unwrap(e) for e in edges if e.is_valid and not e.hide ]
        dissolve_edges(self.bme, edges=edges, use_verts=use_verts, use_face_split=use_face_split)

    def dissolve_faces(self, faces, use_verts=True):
        faces = [ self._unwrap(f) for f in faces if f.is_valid and not f.hide ]
        dissolve_faces(self.bme, faces=faces, use_verts=use_verts)

    def update_verts_faces(self, verts):
        faces = { f for v in verts if v.is_valid for f in self._unwrap(v).link_faces }
        for bmf in faces:
            n = compute_normal(v.co for v in bmf.verts)
            vnorm = sum((v.normal for v in bmf.verts), Vector())
            if n.dot(vnorm) < 0:
                bmf.normal_flip()
            bmf.normal_update()

    def update_face_normal(self, face):
        bmf = self._unwrap(face)
        n = compute_normal(v.co for v in bmf.verts)
        vnorm = sum((v.normal for v in bmf.verts), Vector())
        if n.dot(vnorm) < 0:
            bmf.normal_flip()
        bmf.normal_update()

    def clean_duplicate_bmedges(self, vert):
        if not vert.is_valid: return {}
        bmv = self._unwrap(vert)
        # search for two edges between the same pair of verts
        lbme = list(bmv.link_edges)
        lbme_dup = []
        for i0,bme0 in enumerate(lbme):
            for i1,bme1 in enumerate(lbme):
                if i1 <= i0: continue
                if bme0.other_vert(bmv) == bme1.other_vert(bmv):
                    lbme_dup.append((bme0,bme1))
        mapping = {}
        for bme0,bme1 in lbme_dup:
            if not bme0.is_valid or not bme1.is_valid: continue
            l0,l1 = len(bme0.link_faces), len(bme1.link_faces)
            bme0.select |= bme1.select
            bme1.select |= bme0.select
            handled = False
            if l0 == 0:
                self.bme.edges.remove(bme0)
                handled = True
            if l1 == 0:
                self.bme.edges.remove(bme1)
                handled = True
            if l0 == 1 and l1 == 1:
                # remove bme1 and recreate attached faces
                lbmv = list(bme1.link_faces[0].verts)
                bmf = self._wrap_bmface(bme1.link_faces[0])
                s = bmf.select
                self.bme.edges.remove(bme1)
                nf = self.new_face(lbmv)
                if not nf:
                    print(f'clean_duplicate_bmedges: could not create new bmface: {lbmv}')
                else:
                    mapping[bmf] = nf
                    mapping[bmf].select = s
                handled = True
            if not handled:
                # assert handled, 'unhandled count of linked faces %d, %d' % (l0,l1)
                print('clean_duplicate_bmedges: unhandled count of linked faces %d, %d' % (l0,l1))
        return mapping

    def remove_duplicate_bmfaces(self, vert):
        bmv = self._unwrap(vert)
        mapping = {}
        check = True
        while check:
            check = False
            bmfs = list(bmv.link_faces)
            for i0,bmf0 in enumerate(bmfs):
                for i1,bmf1 in enumerate(bmfs):
                    if i1 <= i0: continue
                    if set(bmf0.verts) ^ set(bmf1.verts): continue
                    # bmf0 and bmf1 have exactly the same verts! delete one!
                    mapping[bmf1] = bmf0
                    self.delete_faces([bmf1])
                    check = True
                    break
                if check: break
        return mapping

    def snap_verts_filter(self, nearest, fn_filter):
        '''
        snap verts when fn_filter returns True
        '''
        for rfv in self.iter_verts():
            if not fn_filter(rfv): continue
            xyz,norm,_,_ = nearest(rfv.co)
            rfv.co = xyz
            rfv.normal = norm
        self.dirty()

#    def snap_all_verts(self, nearest):
#        self.snap_verts_filter(nearest, lambda _: True)

    def snap_all_nonhidden_verts(self, nearest):
        self.snap_verts_filter(nearest, lambda v: not v.hide)

    def snap_selected_verts(self, nearest):
        self.snap_verts_filter(nearest, lambda v: v.select)

#     def snap_unselected_verts(self, nearest):
#         self.snap_verts_filter(nearest, lambda v: v.unselect)

    def pin_selected(self):
        for v in self.iter_verts():
            if v.select: v.pinned = True
    def unpin_selected(self):
        for v in self.iter_verts():
            if v.select: v.pinned = False
    def unpin_all(self):
        for v in self.iter_verts():
            v.pinned = False

    def mark_seam_selected(self):
        for v in self.iter_edges():
            if v.select: v.seam = True
    def clear_seam_selected(self):
        for v in self.iter_edges():
            if v.select: v.seam = False

    def remove_all_doubles(self, dist):
        bmv = [v for v in self.bme.verts if not v.hide]
        remove_doubles(self.bme, verts=bmv, dist=dist)
        self.dirty()

    def remove_selected_doubles(self, dist):
        remove_doubles(self.bme, verts=[bmv for bmv in self.bme.verts if bmv.select], dist=dist)
        self.dirty()

    def remove_by_distance(self, verts, dist):
        remove_doubles(self.bme, verts=[self._unwrap(v) for v in verts], dist=dist)
        self.dirty()

    def flip_face_normals(self):
        verts = set()
        for bmf in self.get_selected_faces():
            bmf.normal_flip()
            for bmv in bmf.verts: verts.add(bmv)
        for bmv in verts:
            if not bmv.is_wire:
                bmv.normal_update()
        self.dirty()

    def recalculate_face_normals(self, *, verts=None, faces=None):
        if faces is None: faces = { bmf for bmf in self.bme.faces if bmf.select }
        else:             faces = { self._unwrap(bmf) for bmf in faces }
        if verts:         faces |= { self._unwrap(bmf) for bmv in verts for bmf in bmv.link_faces}
        recalc_face_normals(self.bme, faces=list(faces))
        for bmv in (bmv for bmf in faces for bmv in bmf.verts): bmv.normal_update()
        self.dirty()
