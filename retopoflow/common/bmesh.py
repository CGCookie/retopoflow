'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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
import bmesh
from bmesh.types import BMVert, BMEdge, BMFace
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils.bvhtree import BVHTree
from mathutils import Vector, Matrix

from ...addon_common.common.decorators import add_cache
from ..common.maths import (
    view_forward_direction,
    distance_point_linesegment,
    distance_point_bmedge,
    distance2d_point_bmedge,
    closest_point_linesegment,
)

from .drawing import Drawing


def get_bmesh_emesh(context):
    em = context.edit_object.data
    bm = bmesh.from_edit_mesh(em)
    return (bm, em)

def iter_mirror_modifiers(obj):
    yield from (
        mod
        for mod in obj.modifiers
        if mod.type == 'MIRROR' and mod.show_viewport and mod.show_in_editmode and mod.show_on_cage
    )
def mirror_threshold(context):
    return next((mod.merge_threshold for mod in iter_mirror_modifiers(context.edit_object)), None)
def has_mirror_x(context):
    return any(mod.use_axis[0] for mod in iter_mirror_modifiers(context.edit_object))
def has_mirror_y(context):
    return any(mod.use_axis[1] for mod in iter_mirror_modifiers(context.edit_object))
def has_mirror_z(context):
    return any(mod.use_axis[2] for mod in iter_mirror_modifiers(context.edit_object))

@add_cache('cache', {})
def get_object_bmesh(obj):
    bm = get_object_bmesh.cache.get(obj, None)
    if bm and not bm.is_valid: bm = None
    if not bm:
        bm = bmesh.new()
        # bm.from_mesh(obj.data)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        bm.from_object(obj, depsgraph)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        get_object_bmesh.cache[obj] = bm
    return bm

def clean_select_layers(bm):
    if 'rf_vert_select_after_move' in bm.verts.layers.int:
        bm.verts.layers.int.remove(bm.verts.layers.int.get('rf_vert_select_after_move'))
    if 'rf_edge_select_after_move' in bm.edges.layers.int:
        bm.edges.layers.int.remove(bm.edges.layers.int.get('rf_edge_select_after_move'))
    if 'rf_face_select_after_move' in bm.faces.layers.int:
        bm.faces.layers.int.remove(bm.faces.layers.int.get('rf_face_select_after_move'))


@add_cache('triangle_inds', [])
def verts_to_triangles(count):
    if count > len(verts_to_triangles.triangle_inds):
        verts_to_triangles.triangle_inds = [[i,i,i] for i in range(count*2)]
    return verts_to_triangles.triangle_inds[:count]

def bme_other_bmv(bme, bmv):
    return next((bmv_ for bmv_ in bme.verts if bmv_ != bmv), None)

def shared_bmv(bme0, bme1):
    bmv0, bmv1 = bme0.verts
    if bmv0 in bme1.verts: return bmv0
    if bmv1 in bme1.verts: return bmv1
    return None

def crossed_quad(pt0, pt1, pt2, pt3):
    v01 = pt1 - pt0
    v12 = pt2 - pt1
    v23 = pt3 - pt2
    v30 = pt0 - pt3
    n0 = v01.cross(-v30)
    n1 = v12.cross(-v01)
    n2 = v23.cross(-v12)
    n3 = v30.cross(-v23)
    return n0.dot(n1) < 0 or n0.dot(n2) < 0 or n0.dot(n3) < 0 or n1.dot(n2) < 0 or n1.dot(n3) < 0 or n2.dot(n3) < 0

class NearestBMVert:
    def __init__(self, bm, matrix, matrix_inv):
        self.bm = bm
        self.matrix = matrix
        self.matrix_inv = matrix_inv
        self.bm.verts.ensure_lookup_table()
        self.bm.edges.ensure_lookup_table()
        self.bm.faces.ensure_lookup_table()

        # assuming there are relatively few loose bmvs (bmvert that is not part of a bmface)
        self.loose_bmvs = [bmv for bmv in self.bm.verts if not bmv.link_faces]
        loose_bmv_cos = [bmv.co for bmv in self.loose_bmvs]

        self.bvh_verts = BVHTree.FromPolygons(loose_bmv_cos, verts_to_triangles(len(self.loose_bmvs)), all_triangles=True)
        self.bvh_faces = BVHTree.FromBMesh(self.bm)

        self.bmv = None

    @property
    def is_valid(self):
        return all((
            self.bm.is_valid,
            (self.bmv is None or self.bmv.is_valid),
            all(bmv.is_valid for bmv in self.loose_bmvs),
        ))

    def update(self, context, co, *, distance=1.84467e19, distance2d=10):
        # NOTE: distance here is local to object!!!  target object could be scaled!
        # even stranger is if target is non-uniformly scaled

        self.bmv = None
        if not self.is_valid: return
        if not co: return

        bmv_co, bmv_norm, bmv_idx, bmv_dist = self.bvh_verts.find_nearest(co, distance) # distance=1.0
        bmf_co, bmf_norm, bmf_idx, bmf_dist = self.bvh_faces.find_nearest(co, distance) # distance=1.0

        bmvs = []
        if bmv_idx is not None: bmvs += [self.loose_bmvs[bmv_idx]]
        if bmf_idx is not None: bmvs += self.bm.faces[bmf_idx].verts
        bmvs = [bmv for bmv in bmvs if not bmv.select]
        if not bmvs: return

        inf = float('inf')
        co2d = location_3d_to_region_2d(context.region, context.region_data, self.matrix @ co)
        co2ds = [location_3d_to_region_2d(context.region, context.region_data, self.matrix @ bmv.co) for bmv in bmvs]
        dists = [(co2d - co2d_).length if co2d_ else inf for co2d_ in co2ds]
        bmv,dist = min(zip(bmvs, dists), key=(lambda bmv_dist: bmv_dist[1]))
        if dist <= Drawing.scale(distance2d):
            self.bmv = bmv


@add_cache('triangle_inds', [])
def edges_to_triangles(count):
    if count > len(edges_to_triangles.triangle_inds):
        edges_to_triangles.triangle_inds = [
            [i*2+0, i*2+1, i*2+1]     # IMPORTANT: first two have to be different, otherwise BVH cannot see it?
            for i in range(count*2)
        ]
    return edges_to_triangles.triangle_inds[:count]

class NearestBMEdge:
    def __init__(self, bm, matrix, matrix_inv):
        self.bm = bm
        self.matrix = matrix
        self.matrix_inv = matrix_inv
        self.bm.verts.ensure_lookup_table()
        self.bm.edges.ensure_lookup_table()
        self.bm.faces.ensure_lookup_table()

        # assuming there are relatively few loose bmes (bmedge that is not part of a bmface)
        self.loose_bmes = [bme for bme in self.bm.edges if not bme.link_faces]
        loose_bme_cos = [bmv.co for bme in self.loose_bmes for bmv in bme.verts]

        self.bvh_edges = BVHTree.FromPolygons(loose_bme_cos, edges_to_triangles(len(self.loose_bmes)), all_triangles=True)
        self.bvh_faces = BVHTree.FromBMesh(self.bm)

        self.bme = None

    @property
    def is_valid(self):
        return all((
            self.bm.is_valid,
            (self.bme is None or self.bme.is_valid),
            all(bme.is_valid for bme in self.loose_bmes),
        ))

    def update(self, context, co, *, distance=1.84467e19, distance2d=10):
        # NOTE: distance here is local to object!!!  target object could be scaled!
        # even stranger is if target is non-uniformly scaled

        self.bme = None
        if not self.is_valid: return

        bme_co, bme_norm, bme_idx, bme_dist = self.bvh_edges.find_nearest(co, distance) # distance=1.0
        bmf_co, bmf_norm, bmf_idx, bmf_dist = self.bvh_faces.find_nearest(co, distance) # distance=1.0

        bmes = []
        if bme_idx is not None: bmes += [self.loose_bmes[bme_idx]]
        if bmf_idx is not None: bmes += self.bm.faces[bmf_idx].edges
        bmes = [bme for bme in bmes if not any(bmv.select for bmv in bme.verts)]
        if not bmes: return

        inf = float('inf')
        co2d = location_3d_to_region_2d(context.region, context.region_data, self.matrix @ co)
        co2ds = [
            ( location_3d_to_region_2d(context.region, context.region_data, self.matrix @ bmv.co) for bmv in bme.verts )
            for bme in bmes
        ]
        dists = [distance_point_linesegment(co2d, *co2d_) for co2d_ in co2ds]
        bme,dist = min(zip(bmes, dists), key=(lambda bme_dist: bme_dist[1]))
        if dist > Drawing.scale(distance2d): return

        self.bme = bme
        co2d0, co2d1 = [location_3d_to_region_2d(context.region, context.region_data, self.matrix @ bmv.co) for bmv in bme.verts]
        self.co2d = closest_point_linesegment(co2d, co2d0, co2d1)
