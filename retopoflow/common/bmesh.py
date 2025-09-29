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
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import clamp
from .maths import (
    view_forward_direction,
    distance_point_linesegment,
    distance_point_bmedge,
    distance2d_point_bmedge,
    closest_point_linesegment,
    Point,
    xform_point, xform_vector, xform_direction, xform_normal,
)
from .raycast import nearest_normal_valid_sources

from .drawing import Drawing

def get_bmesh_emesh(context, *, ensure_lookup_tables=False) -> tuple[bmesh.types.BMesh, bpy.types.Mesh]:
    em = context.edit_object.data
    bm = bmesh.from_edit_mesh(em)
    if ensure_lookup_tables:
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()

        bm.edges.ensure_lookup_table()
        bm.edges.index_update()

        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
    return (bm, em)

def iter_mirror_modifiers(obj):
    yield from (
        mod
        for mod in obj.modifiers
        if mod.type == 'MIRROR' and (mod.show_render or mod.show_viewport)
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
        depsgraph = bpy.context.evaluated_depsgraph_get()
        if obj.type == 'MESH':
            bm.from_object(obj, depsgraph)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            get_object_bmesh.cache[obj] = bm
        else:
            eval_obj = obj.evaluated_get(depsgraph)
            mesh = eval_obj.to_mesh()
            bm.from_mesh(mesh)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()
            bm.faces.ensure_lookup_table()
            get_object_bmesh.cache[obj] = bm
            eval_obj.to_mesh_clear()
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

def ensure_correct_normals(bm, bmfs):
    M_local = bpy.context.edit_object.matrix_world
    Mi_local = M_local.inverted()
    Mt_local = M_local.transposed()
    bmesh.ops.recalc_face_normals(bm, faces=bmfs)
    for bmf in bmfs:
        avg_local = Point.average((bmv.co for bmv in bmf.verts))
        pts = [bmf_midpoint(bmf)]
        pts += [bme_midpoint(bme) for bme in bmf.edges]
        pts += [bmv.co for bmv in bmf.verts]
        no_local_sum = Vector((0,0,0))
        for pt_local in pts:
            pt_world = xform_point(M_local, pt_local)
            no_world = nearest_normal_valid_sources(bpy.context, pt_world, world=True)
            no_local = xform_normal(Mt_local, no_world)
            no_local_sum += no_local
        no_local = no_local_sum / len(pts)
        if bmf.normal.dot(no_local) < 0:
            bmf.normal_flip()

def bmes_share_face(bme0, bme1):
    return any(bmf in bme1.link_faces for bmf in bme0.link_faces)

def bme_midpoint(bme):
    bmv0,bmv1 = bme.verts
    return (bmv0.co + bmv1.co) / 2
# def bme_other_bmv(bme, bmv):
#     return next((bmv_ for bmv_ in bme.verts if bmv_ != bmv), None)
def bme_other_bmv(bme, bmv):
    bmv0, bmv1 = bme.verts
    if bmv != bmv0 and bmv != bmv1: return None
    return bmv0 if bmv1 == bmv else bmv1
def bme_other_bmf(bme, bmf):
    return next((bmf_ for bmf_ in bme.link_faces if bmf_ != bmf), None)
def bmes_share_bmv(bme0, bme1):
    a0,a1 = bme0.verts
    b0,b1 = bme1.verts
    return (a0==b0) or (a0==b1) or (a1==b0) or (a1==b1)
def bmes_shared_bmv(bme0, bme1):
    return next(iter(set(bme0.verts) & set(bme1.verts)), None)
def bme_unshared_bmv(bme, bme_other):
    bmv0, bmv1 = bme.verts
    return bmv0 if bmv1 in bme_other.verts else bmv1
def bmes_share_bmv(bme0, bme1):
    return bool(set(bme0.verts) & set(bme1.verts))
def bmvs_shared_bme(bmv0, bmv1):
    return next((bme for bme in bmv0.link_edges if bmv1 in bme.verts), None)
def bmfs_shared_bme(bmf0, bmf1):
    return next((bme for bme in bmf0.edges if bme in bmf1.edges), None)
def bme_vector(bme):
    return (bme.verts[1].co - bme.verts[0].co)
def bme_length(bme):
    bmv0,bmv1 = bme.verts
    return (bmv0.co - bmv1.co).length

def bmf_midpoint(bmf):
    return sum((bmv.co for bmv in bmf.verts), Vector((0,0,0))) / len(bmf.verts)
def bmf_radius(bmf):
    mid = bmf_midpoint(bmf)
    return max((bmv.co - mid).length for bmv in bmf.verts)
def bmf_midpoint_radius(bmf):
    mid = bmf_midpoint(bmf)
    rad = max((bmv.co - mid).length for bmv in bmf.verts)
    return (mid, rad)

def bmf_is_quad(bmf):
    return len(bmf.edges) == 4

def quad_bmf_opposite_bme(bmf, bme):
    return next(bme_ for bme_ in bmf.edges if not bmes_share_bmv(bme, bme_))

def is_bmv_end(bmv, bmes):
    return len(set(bmv.link_edges) & bmes) != 2

def get_boundary_strips_cycles(bmes):
    if not bmes: return ([], [])

    bmes = set(bmes)

    strips, cycles = [], []

    # first start with bmvert ends to find strips
    bmv_ends = { bmv for bme in bmes for bmv in bme.verts if is_bmv_end(bmv, bmes) }
    while True:
        current_strip = []
        bmv = next(( bmv for bme in bmes for bmv in bme.verts if bmv in bmv_ends ), None)
        if not bmv: break
        bme = None
        while True:
            bme = next(iter(set(bmv.link_edges) & bmes - {bme}), None)
            current_strip += [bme]
            bmv = bme_other_bmv(bme, bmv)
            if bmv in bmv_ends: break
        bmes -= set(current_strip)
        strips += [current_strip]

    # some of the strips may actually be cycles...
    for strip in list(strips):
        if len(strip) > 3 and bmes_share_bmv(strip[0], strip[-1]):
            strips.remove(strip)
            cycles.append(strip)

    # any bmedges still in bmes _should_ be part of cycles
    while True:
        current_cycle = []
        bmv = next(( bmv for bme in bmes for bmv in bme.verts ), None)
        if not bmv: break
        bme = None
        while True:
            bme = next(iter(set(bmv.link_edges) & bmes - {bme}), None)
            if not bme or bme in current_cycle: break
            current_cycle += [bme]
            bmv = bme_other_bmv(bme, bmv)
        bmes -= set(current_cycle)
        cycles += [current_cycle]

    strips.sort(key=lambda strip:len(strip))
    cycles.sort(key=lambda cycle:len(cycle))

    # try to have strips point in the same direction
    for strip in strips:
        if len(strip) == 1: continue
        v = bme_midpoint(strip[-1]) - bme_midpoint(strip[0])
        if v.x + v.y + v.z < 0: strip.reverse()

    return (strips, cycles)



# finds closest path of selected, connected, boundary/wire BMEdges
def find_selected_cycle_or_path(bm, point_closest, *, only_boundary=True):
    selected = bmops.get_all_selected(bm)

    # find edge loop on boundary or are wires
    t = mirror_threshold(bpy.context)
    def use_bme(bme):
        if bme not in selected[BMEdge]: return False
        if only_boundary and len(bme.link_faces) > 1: return False
        if has_mirror_x(bpy.context) and all(abs(bmv.co.x) <= t for bmv in bme.verts): return False
        return True

    all_boundary_bmes = { bme for bme in selected[BMEdge] if use_bme(bme) }
    # separate into connected parts, and grab connected part that is closest to point
    touched = set()
    closest = None
    for bme_start in all_boundary_bmes:
        if bme_start in touched: continue
        bmes = set()
        working = { bme_start }
        while working:
            bme = working.pop()
            if bme in touched: continue
            touched.add(bme)
            bmes.add(bme)
            working |= {
                bme_ for bmv in bme.verts for bme_ in bmv.link_edges
                if use_bme(bme_) and not bmes_share_face(bme, bme_)
            }
        dist = min(distance_point_bmedge(point_closest, bme) for bme in bmes)
        if closest and closest['dist'] <= dist: continue
        closest = {
            'dist': dist,
            'bmes': bmes,
        }

    if not closest: return ([], False)

    selected = {
        BMVert: { bmv for bme in closest['bmes'] for bmv in bme.verts },
        BMEdge: closest['bmes'],
    }

    longest_path = []
    longest_cycle = []

    def vert_selected(bme):
        yield from (bmv for bmv in bme.verts if bmv in selected[BMVert])
    def link_edge_selected(bmv):
        yield from (bme for bme in bmv.link_edges if bme in selected[BMEdge])
    def adjacent_selected_bmedges(bme):
        for bmv in bme.verts:
            if bmv not in selected[BMVert]: continue
            for bme_ in bmv.link_edges:
                if bme_ not in selected[BMEdge]: continue
                if bme_ == bme: continue
                yield bme_
    start_bmes = {
        bme for bme in selected[BMEdge]
        if len(list(adjacent_selected_bmedges(bme))) == 1
    }
    if not start_bmes: start_bmes = selected[BMEdge]
    for start_bme in start_bmes:
        working = [(start_bme, adjacent_selected_bmedges(start_bme))]
        touched = {start_bme}
        while working:
            cur_bme, cur_iter = working[-1]
            next_bme = next(cur_iter, None)
            if not next_bme:
                if len(working) > len(longest_path):
                    longest_path = [bme for (bme,_) in working]
                working.pop()
                touched.remove(cur_bme)
                continue
            if next_bme in touched:
                if next_bme == start_bme and len(working) > 2 and len(working) > len(longest_cycle):
                    longest_cycle = [bme for (bme,_) in working]
                continue
            touched.add(next_bme)
            working.append((next_bme, adjacent_selected_bmedges(next_bme)))
        if len(longest_cycle) > 50:
            break
    is_cyclic = len(longest_cycle) >= len(longest_path) * 0.5
    return (longest_cycle if is_cyclic else longest_path, is_cyclic)


def nearest_bmv_world(context, bm, matrix, matrix_inv, co_world, *, distance=1.84467e19, distance2d=10):
    # note: xform co local, so technically we are not finding the closest in world-space
    #       as object could be scaled non-uniformly, but this is faster!
    co_2d = location_3d_to_region_2d(context.region, context.region_data, co_world)
    if not co_2d: return None
    co_local = (matrix_inv @ Vector((*co_world.xyz, 1.0))).xyz
    distance_squared, distance2d_squared = distance ** 2, distance2d ** 2
    closest, closest_dist = None, float('inf')
    for bmv in bm.verts:
        bmvco_2d = location_3d_to_region_2d(context.region, context.region_data, (matrix @ Vector((*bmv.co.xyz, 1.0))).xyz)
        if not bmvco_2d: continue
        if (bmvco_2d.xy - co_2d.xy).length_squared > distance2d_squared: continue
        dist = (bmv.co - co_local).length_squared
        if dist > distance_squared: continue
        if dist >= closest_dist: continue
        closest, closest_dist = bmv, dist
    return closest

def nearest_bme_world(context, bm, matrix, matrix_inv, co_world, *, distance=1.84467e19, distance2d=10):
    # note: xform co local, so technically we are not finding the closest in world-space
    #       as object could be scaled non-uniformly, but this is faster!
    co_2d = location_3d_to_region_2d(context.region, context.region_data, co_world)
    if not co_2d: return None
    co_local = (matrix_inv @ Vector((*co_world.xyz, 1.0))).xyz
    distance_squared, distance2d_squared = distance ** 2, distance2d ** 2
    closest, closest_dist = None, float('inf')
    for bme in bm.edges:
        bmv0, bmv1 = bme.verts
        co0, co1 = bmv0.co, bmv1.co

        co0_2d = location_3d_to_region_2d(context.region, context.region_data, (matrix @ Vector((*co0.xyz, 1.0))).xyz)
        co1_2d = location_3d_to_region_2d(context.region, context.region_data, (matrix @ Vector((*co1.xyz, 1.0))).xyz)
        av, bv = co1_2d - co0_2d, co_2d - co0_2d
        bl = bv.length
        bd = bv / bl
        p = co0_2d + bd * clamp(av.dot(bd), 0, bl)
        if (p - co_2d.xy).length_squared > distance2d_squared: continue  # check against screen-space distance

        av, bv = co1 - co0, co_local - co0
        bl = bv.length
        bd = bv / bl
        p = co0 + bd * clamp(av.dot(bd), 0, bl)
        dist = (p - co_local).length_squared
        if dist > distance_squared: continue  # check against world-space distance
        if dist >= closest_dist: continue
        closest, closest_dist = bme, dist
    return closest


class NearestElem:
    def __init__(self, bm, matrix, matrix_inv, *, ensure_lookup_tables=True):
        self.bm = bm
        self.matrix = matrix
        self.matrix_inv = matrix_inv
        if ensure_lookup_tables:
            self.bm.verts.ensure_lookup_table()
            self.bm.edges.ensure_lookup_table()
            self.bm.faces.ensure_lookup_table()
        self.bvh_faces = BVHTree.FromBMesh(self.bm)


class NearestBMVert(NearestElem):
    def __init__(self, bm, matrix, matrix_inv, *, ensure_lookup_tables=True):
        super().__init__(bm, matrix, matrix_inv, ensure_lookup_tables=ensure_lookup_tables)

        # assuming there are relatively few loose bmvs (bmvert that is not part of a bmface)
        self.loose_bmvs = [bmv for bmv in self.bm.verts if not bmv.link_faces]
        loose_bmv_cos = [bmv.co for bmv in self.loose_bmvs]

        self.bvh_verts = BVHTree.FromPolygons(loose_bmv_cos, verts_to_triangles(len(self.loose_bmvs)), all_triangles=True)

        self.bmv = None

    @property
    def is_valid(self):
        return all((
            self.bm.is_valid,
            (self.bmv is None or self.bmv.is_valid),
            all(bmv.is_valid for bmv in self.loose_bmvs),
        ))

    def update(self, context, co, *, distance=1.84467e19, distance2d=10, filter_selected=True, filter_fn=None):
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
        if filter_fn:
            bmvs = [bmv for bmv in bmvs if filter_fn(bmv)]
        elif filter_selected:
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

class NearestBMEdge(NearestElem):
    def __init__(self, bm, matrix, matrix_inv, *, ensure_lookup_tables=True):
        super().__init__(bm, matrix, matrix_inv, ensure_lookup_tables=ensure_lookup_tables)

        # assuming there are relatively few loose bmes (bmedge that is not part of a bmface)
        self.loose_bmes = [bme for bme in self.bm.edges if not bme.link_faces]
        loose_bme_cos = [bmv.co for bme in self.loose_bmes for bmv in bme.verts]

        self.bvh_edges = BVHTree.FromPolygons(loose_bme_cos, edges_to_triangles(len(self.loose_bmes)), all_triangles=True)

        self.bme = None

    @property
    def is_valid(self):
        return all((
            self.bm.is_valid,
            (self.bme is None or self.bme.is_valid),
            all(bme.is_valid for bme in self.loose_bmes),
        ))

    def update(self, context, co, *, distance=1.84467e19, distance2d=10, ignore_selected=True, filter_fn=None):
        # NOTE: distance here is local to object!!!  target object could be scaled!
        # even stranger is if target is non-uniformly scaled

        self.bme = None
        if not self.is_valid: return None

        bme_co, bme_norm, bme_idx, bme_dist = self.bvh_edges.find_nearest(co, distance) # distance=1.0
        bmf_co, bmf_norm, bmf_idx, bmf_dist = self.bvh_faces.find_nearest(co, distance) # distance=1.0

        bmes = []
        if bme_idx is not None: bmes += [self.loose_bmes[bme_idx]]
        if bmf_idx is not None: bmes += self.bm.faces[bmf_idx].edges
        if filter_fn:
            bmes = [bme for bme in bmes if filter_fn(bme)]
        if ignore_selected:
            bmes = [bme for bme in bmes if not any(bmv.select for bmv in bme.verts)]
        if not bmes: return None

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
        return self.bme

class NearestBMFace(NearestElem):
    def __init__(self, bm, matrix, matrix_inv, *, ensure_lookup_tables=True):
        super().__init__(bm, matrix, matrix_inv, ensure_lookup_tables=ensure_lookup_tables)

        self.bmf = None

    @property
    def is_valid(self):
        return all((
            self.bm.is_valid,
            (self.bmf is None or self.bmf.is_valid),
        ))

    def update(self, context, co, *, distance=1.84467e19, distance2d=10, filter_selected=True, filter_fn=None):
        # NOTE: distance here is local to object!!!  target object could be scaled!
        # even stranger is if target is non-uniformly scaled

        self.bmf = None
        if not self.is_valid: return
        if not co: return

        bmf_co, bmf_norm, bmf_idx, bmf_dist = self.bvh_faces.find_nearest(co, distance) # distance=1.0

        if bmf_idx is not None:
            co2d = location_3d_to_region_2d(context.region, context.region_data, self.matrix @ co)
            bmf_co2d = location_3d_to_region_2d(context.region, context.region_data, self.matrix @ bmf_co)
            if (co2d - bmf_co2d).length < Drawing.scale(distance2d):
                try:
                    self.bmf = self.bm.faces[bmf_idx]
                except IndexError:
                    print(f'WARN: ftable is outdated. bmf_idx={bmf_idx}, face_count={len(self.bm.faces)}')
                    self.bm.faces.ensure_lookup_table()  # Fix 1617
                    self.bmf = self.bm.faces[bmf_idx]
        if filter_fn and self.bmf:
            if not filter_fn(self.bmf): self.bmf = None
        elif filter_selected and self.bmf:
            if self.bmf.select: self.bmf = None



def is_bmedge_boundary(bme, mirror, threshold, clip):
    if not bme.is_boundary: return False
    if not clip: return True
    bmv0, bmv1 = bme.verts
    co0, co1 = bmv0.co, bmv1.co
    if 'x' in mirror and abs(co0.x) <= threshold.x and abs(co1.x) <= threshold.x: return False
    if 'y' in mirror and abs(co0.y) <= threshold.y and abs(co1.y) <= threshold.y: return False
    if 'z' in mirror and abs(co0.z) <= threshold.z and abs(co1.z) <= threshold.z: return False
    return True

def is_bmvert_boundary(bmv, mirror, threshold, clip):
    if not bmv.is_boundary: return False
    if not clip: return True
    if 'x' in mirror and abs(bmv.co.x) <= threshold.x: return False
    if 'y' in mirror and abs(bmv.co.y) <= threshold.y: return False
    if 'z' in mirror and abs(bmv.co.z) <= threshold.z: return False
    return True
