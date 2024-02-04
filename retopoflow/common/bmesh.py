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

from .drawing import Drawing


def get_bmesh_emesh(context):
    em = context.active_object.data
    bm = bmesh.from_edit_mesh(em)
    return (bm, em)

def get_select_layers(bm):
    if 'rf: select after move' not in bm.verts.layers.int:
        bm.verts.layers.int.new('rf: select after move')
    if 'rf: select after move' not in bm.edges.layers.int:
        bm.edges.layers.int.new('rf: select after move')
    if 'rf: select after move' not in bm.faces.layers.int:
        bm.faces.layers.int.new('rf: select after move')
    layer_sel_vert = bm.verts.layers.int.get('rf: select after move')
    layer_sel_edge = bm.edges.layers.int.get('rf: select after move')
    layer_sel_face = bm.faces.layers.int.get('rf: select after move')
    return (layer_sel_vert, layer_sel_edge, layer_sel_face)



triangle_inds = []
def verts_to_triangles(count):
    global triangle_inds
    if count > len(triangle_inds):
        triangle_inds = [[i,i,i] for i in range(count*2)]
    return triangle_inds[:count]

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
