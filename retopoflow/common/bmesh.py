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
import heapq
from bpy.types import Mesh, Context, MirrorModifier
from bmesh.types import BMVert, BMEdge, BMFace, BMesh, BMLayerCollection, BMLayerItem
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils.bvhtree import BVHTree
from mathutils import Vector, Matrix
from enum import IntEnum
from math import inf, isnan, cos, radians
from typing import cast, override, TypeVar, TypeAlias, Generic
from collections.abc import Sequence, Iterator, Callable

from ...addon_common.common.decorators import add_cache
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import clamp, closest_point_segment
from .maths import (
    view_forward_direction,
    distance_point_linesegment,
    distance_point_bmedge,
    distance2d_point_bmedge,
    closest_point_linesegment,
    proportional_edit,
    Point,
    xform_point, xform_vector, xform_direction, xform_normal,
)
from .raycast import nearest_normal_valid_sources

from .drawing import Drawing

def get_bmesh_emesh(context:Context, *, ensure_lookup_tables:bool=False) -> tuple[BMesh, Mesh]:
    assert context.edit_object, 'Expected to be editing a mesh'
    em = context.edit_object.data
    assert isinstance(em, Mesh), 'Expected to be editing a mesh'
    bm = bmesh.from_edit_mesh(em)
    if ensure_lookup_tables:
        bm.verts.ensure_lookup_table()
        bm.verts.index_update()

        bm.edges.ensure_lookup_table()
        bm.edges.index_update()

        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
    return (bm, em)

def iter_mirror_modifiers(obj : bpy.types.Object|None) -> Iterator[MirrorModifier]:
    if not obj: return
    for mod in obj.modifiers:
        if mod.type != 'MIRROR': continue
        # if not isinstance(mod, MirrorModifier): continue
        if not mod.show_render and not mod.show_viewport: continue
        yield mod                                                                       # pyright: ignore [reportReturnType]

def mirror_threshold(context: Context) -> float|None:
    return next((mod.merge_threshold for mod in iter_mirror_modifiers(context.edit_object)), None)
def has_mirror_x(context:Context) -> bool:
    return any(mod.use_axis[0] for mod in iter_mirror_modifiers(context.edit_object))   # pyright: ignore [reportIndexIssue]
def has_mirror_y(context:Context) -> bool:
    return any(mod.use_axis[1] for mod in iter_mirror_modifiers(context.edit_object))   # pyright: ignore [reportIndexIssue]
def has_mirror_z(context:Context) -> bool:
    return any(mod.use_axis[2] for mod in iter_mirror_modifiers(context.edit_object))   # pyright: ignore [reportIndexIssue]

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

def clear_object_bmesh():
    get_object_bmesh.cache.clear() # pyright: ignore[reportFunctionMemberAccess]
    try:
        from .accel import SourceMeshCache
        SourceMeshCache.clear()
    except Exception:
        pass


def clean_select_layers(bm : BMesh):
    def del_int_layer(
        layers : BMLayerCollection, # pyright: ignore[reportMissingTypeArgument, reportUnknownParameterType]
        name : str,
    ):
        if isinstance(layer := layers.get(name), BMLayerItem):
            layers.remove(layer)
    del_int_layer(bm.verts.layers.int, 'rf_vert_select_after_move')
    del_int_layer(bm.edges.layers.int, 'rf_edge_select_after_move')
    del_int_layer(bm.faces.layers.int, 'rf_face_select_after_move')


class BMVertLayer_Int:
    bm : BMesh
    layer : BMLayerItem

    @staticmethod
    def remove(bm : BMesh, layer_name : str):
        layers = bm.verts.layers.int
        if isinstance(layer := layers.get(layer_name), BMLayerItem):
            layers.remove(layer)

    def __init__(self, bm : BMesh, layer_name : str):
        self.bm = bm
        layers = bm.verts.layers.int
        if layer_name not in layers:
            layer = layers.new(layer_name)
        else:
            layer = layers[layer_name]
        assert isinstance(layer, BMLayerItem)
        self.layer = layer

    def __iter__(self) -> Iterator[tuple[BMVert, int]]:
        layer = self.layer
        for bmv in self.bm.verts:
            yield (bmv, cast(int, cast(object, bmv[layer])))

    def __getitem__(self, bmv : BMVert) -> int:
        return cast(int, cast(object, bmv[self.layer]))

    def __setitem__(self, bmv : BMVert, val : int):
        bmv[self.layer] = val


IE = TypeVar('IE', bound=IntEnum)

class BMVertLayer_IntEnum(Generic[IE]):
    bm : BMesh
    layer : BMLayerItem
    enum_cls : type[IE]
    default : IE

    @staticmethod
    def remove(bm : BMesh, layer_name : str):
        layers = bm.verts.layers.int
        if isinstance(layer := layers.get(layer_name), BMLayerItem):
            layers.remove(layer)

    def __init__(self, bm : BMesh, layer_name : str, enum_cls : type[IE], default : IE):
        self.bm = bm
        layers = bm.verts.layers.int
        if layer_name not in layers:
            layer = layers.new(layer_name)
        else:
            layer = layers[layer_name]
        assert isinstance(layer, BMLayerItem)
        self.layer = layer
        self.enum_cls = enum_cls
        self.default = default

    def __iter__(self) -> Iterator[tuple[BMVert, IE]]:
        layer = self.layer
        enum_cls = self.enum_cls
        for bmv in self.bm.verts:
            yield (bmv, enum_cls(cast(int, cast(object, bmv[layer]))))

    def __getitem__(self, bmv: BMVert) -> IE:
        val = cast(int, cast(object, bmv[self.layer]))
        try:
            return self.enum_cls(val)
        except ValueError:
            return self.default

    def __setitem__(self, bmv : BMVert, val : IE):
        bmv[self.layer] = val




@add_cache('triangle_inds', [])
def verts_to_triangles(count):
    if count > len(verts_to_triangles.triangle_inds):
        verts_to_triangles.triangle_inds = [[i,i,i] for i in range(count*2)]
    return verts_to_triangles.triangle_inds[:count]


def bmv_co_isnan(bmv:BMVert) -> bool:
    x,y,z = bmv.co
    return isnan(x+y+z)

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

def ensure_correct_normals(bm:BMesh, bmfs:list[BMFace], use_centroid:bool=False, flip:bool=False, check_snap:bool=False):
    if not bmfs: return
    bmesh.ops.recalc_face_normals(bm, faces=bmfs)

    if use_centroid:
        # Compare against centroid since object origin can be far away
        face_centers = [bmf_midpoint(bmf) for bmf in bmfs]
        centroid = sum(face_centers, Vector((0, 0, 0))) / len(face_centers)
        outward_count = sum(1 for bmf, fc in zip(bmfs, face_centers) if bmf.normal.dot(fc - centroid) >= 0)
        if outward_count < len(bmfs) / 2:
            for bmf in bmfs:
                bmf.normal_flip()

    if flip:
        for bmf in bmfs:
            bmf.normal_flip()

    if check_snap:
        M_local = bpy.context.edit_object.matrix_world
        Mt_local = M_local.transposed()
        for bmf in bmfs:
            avg_local = Point.average((bmv.co for bmv in bmf.verts))
            pts = []
            pts += [bmf_midpoint(bmf)]
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


def bmvs_share_bmf(bmv0, bmv1):
    return any(bmf in bmv1.link_faces for bmf in bmv0.link_faces)

def bmes_share_face(bme0, bme1):
    return any(bmf in bme1.link_faces for bmf in bme0.link_faces)

def bme_midpoint(bme : BMEdge) -> Vector:
    bmv0,bmv1 = bme.verts
    return (bmv0.co + bmv1.co) / 2
# def bme_other_bmv(bme, bmv):
#     return next((bmv_ for bmv_ in bme.verts if bmv_ != bmv), None)
def bme_other_bmv(bme : BMEdge, bmv : BMVert) -> BMVert|None:
    bmv0, bmv1 = bme.verts
    if bmv != bmv0 and bmv != bmv1:
        return None
    return bmv0 if bmv1 == bmv else bmv1
def bme_other_bmf(bme : BMEdge, bmf : BMFace) -> BMFace|None:
    return next((bmf_ for bmf_ in bme.link_faces if bmf_ != bmf), None)
def bmes_share_bmv(bme0 : BMEdge | None, bme1 : BMEdge | None) -> bool:
    if not bme0 or not bme1: return False
    a0,a1 = bme0.verts
    b0,b1 = bme1.verts
    return (a0==b0) or (a0==b1) or (a1==b0) or (a1==b1)
def bmes_shared_bmv(bme0 : BMEdge, bme1 : BMEdge) -> BMVert | None:
    v00, v01 = bme0.verts
    v10, v11 = bme1.verts
    if v00 == v10 or v00 == v11:
        return v00
    if v01 == v10 or v01 == v11:
        return v01
    return None
def bme_unshared_bmv(bme, bme_other):
    bmv0, bmv1 = bme.verts
    return bmv0 if bmv1 in bme_other.verts else bmv1
def bmvs_shared_bme(bmv0 : BMVert, bmv1 : BMVert) -> BMEdge | None:
    return next((bme for bme in bmv0.link_edges if bmv1 in bme.verts), None)
def bmfs_shared_bme(bmf0 : BMFace, bmf1 : BMFace) -> BMEdge | None:
    return next((bme for bme in bmf0.edges if bme in bmf1.edges), None)
def bmfs_share_bmv(bmf0 : BMFace, bmf1 : BMFace) -> bool:
    return not set(bmf0.verts).isdisjoint(bmf1.verts)

def bme_vector(bme:BMEdge) -> Vector:
    bmv0,bmv1 = bme.verts
    return bmv1.co - bmv0.co

def bme_length(bme:BMEdge) -> float:
    bmv0,bmv1 = bme.verts
    return (bmv0.co - bmv1.co).length

def bme_cos(bme : BMEdge) -> tuple[Vector, Vector]:
    bmv0, bmv1 = bme.verts
    return (bmv0.co, bmv1.co)

def bmf_midpoint(bmf : BMFace) -> Vector:
    return sum((bmv.co for bmv in bmf.verts), Vector((0,0,0))) / len(bmf.verts)
def bmf_radius(bmf : BMFace) -> float:
    mid = bmf_midpoint(bmf)
    return max((bmv.co - mid).length for bmv in bmf.verts)
def bmf_radius_squared(bmf : BMFace) -> float:
    mid = bmf_midpoint(bmf)
    return max((bmv.co - mid).length_squared for bmv in bmf.verts)
def bmf_midpoint_radius(bmf):
    mid = bmf_midpoint(bmf)
    rad = max((bmv.co - mid).length for bmv in bmf.verts)
    return (mid, rad)

def bmf_is_tri(bmf:BMFace) -> bool:
    return len(bmf.edges) == 3
def bmf_is_quad(bmf:BMFace) -> bool:
    return len(bmf.edges) == 4
def bmf_is_pentagon(bmf:BMFace) -> bool:
    return len(bmf.edges) == 5

def bmf_compute_normal(bmf:BMFace) -> Vector:
    ''' computes normal based on verts '''
    # TODO: should use loop rather than verts?
    an = Vector((0,0,0))
    vs = list(bmf.verts)
    bmv1, bmv2 = vs[-2], vs[-1]
    v1 = bmv2.co - bmv1.co
    for bmv in vs:
        bmv0, bmv1, bmv2 = bmv1, bmv2, bmv
        v0, v1 = -v1, bmv2.co - bmv1.co
        an = an + v0.cross(v1).normalized()
    return an.normalized()

def bmv_compute_normal(bmv):
    ''' computes normal based on faces. Used when bmv.normal is stale '''
    n = Vector((0.0, 0.0, 0.0))
    for f in bmv.link_faces:
        n += f.normal
    ln = n.length
    return n / ln if ln > 1e-8 else Vector(bmv.normal)

def bmf_is_flipped(bmf:BMFace) -> bool:
    fn = bmf_compute_normal(bmf)
    return any(v.normal.dot(fn) <= 0 for v in bmf.verts)


def index_of(item, items) -> int:
    for index, ii in enumerate(items):
        if ii == item: return index
    return -1
def bmf_opposite_bmelem(bmf:BMFace, bmelem:BMVert|BMEdge) -> BMVert | BMEdge | None:
    try:
        l = len(bmf.edges)
        if l % 2 == 0:
            # even-sided face
            o = l // 2                          # offset
            if isinstance(bmelem, BMEdge):
                idx0 = index_of(bmelem, bmf.edges)
                idx1 = (idx0 + o) % l
                return bmf.edges[idx1]
            elif isinstance(bmelem, BMVert):
                idx0 = index_of(bmelem, bmf.verts)
                idx1 = (idx0 + o) % l
                return bmf.verts[idx1]
        else:
            # odd-sided face
            o1, o2 = l // 2, l // 2 + 1         # offsets
            if isinstance(bmelem, BMEdge):
                idx0 = index_of(bmelem, bmf.edges)
                idx1, idx2 = (idx0 + o1) % l, (idx0 + o2) % l
                return bmes_shared_bmv(bmf.edges[idx1], bmf.edges[idx2])
            elif isinstance(bmelem, BMVert):
                idx0 = index_of(bmelem, bmf.verts)
                idx1, idx2 = (idx0 + o1) % l, (idx0 + o2) % l
                return bmvs_shared_bme(bmf.verts[idx1], bmf.verts[idx2])
    except Exception as e:
        print(e)
        return None


def bmf_opposite_bme(bmf:BMFace, bme:BMEdge) -> BMEdge | None:
    # assumes bmf is a quad
    return next(
        ( bme_other for bme_other in bmf.edges if not bmes_share_bmv(bme, bme_other) ),
        None,
    )

def quad_bmf_opposite_bme(bmf : BMFace, bme : BMEdge) -> BMEdge:
    return next(bme_ for bme_ in bmf.edges if not bmes_share_bmv(bme, bme_))

def is_bmv_end(bmv, bmes):
    return len(set(bmv.link_edges) & bmes) != 2

def get_boundary_strips_cycles(bmes : Sequence[BMEdge]) -> tuple[list[list[BMEdge]], list[list[BMEdge]]]:
    if not bmes: return ([], [])

    bmes_set = set(bmes)

    strips : list[list[BMEdge]] = []
    cycles : list[list[BMEdge]] = []

    # first start with bmvert ends to find strips
    bmv_ends = { bmv for bme in bmes_set for bmv in bme.verts if is_bmv_end(bmv, bmes_set) }
    while True:
        current_strip : list[BMEdge] = []
        bmv = next(( bmv for bme in bmes_set for bmv in bme.verts if bmv in bmv_ends ), None)
        if not bmv: break
        bme = None
        while True:
            bme : BMEdge | None = next(iter(set(bmv.link_edges) & bmes_set - {bme}), None)
            if not bme: break
            current_strip += [bme]
            bmv = bme_other_bmv(bme, bmv)
            if not bmv or bmv in bmv_ends: break
        bmes_set -= set(current_strip)
        strips += [current_strip]

    # some of the strips may actually be cycles...
    for strip in list(strips):
        if len(strip) > 3 and bmes_share_bmv(strip[0], strip[-1]):
            strips.remove(strip)
            cycles.append(strip)

    # any bmedges still in bmes_set _should_ be part of cycles
    while True:
        current_cycle = []
        bmv = next(( bmv for bme in bmes_set for bmv in bme.verts ), None)
        if not bmv: break
        bme = None
        while True:
            bme = next(iter(set(bmv.link_edges) & bmes_set - {bme}), None)
            if not bme or bme in current_cycle: break
            current_cycle += [bme]
            bmv = bme_other_bmv(bme, bmv)
            if not bmv: break
        bmes_set -= set(current_cycle)
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


def get_bmv_avg_edge_len(bmv):
    links = bmv.link_edges
    return (sum(bme_length(bme) for bme in links) / len(links)) if links else 0.0


def get_bmv_loop_pairs(bmv: BMVert) -> tuple[tuple[BMVert, BMVert], ...] | None:
    link_edges = list(bmv.link_edges)
    if len(link_edges) != 4 or len(bmv.link_faces) != 4:
        return None
    pairs = []
    used  = set()
    for i in range(4):
        if i in used: continue
        fi  = set(link_edges[i].link_faces)
        opp = next((j for j in range(4)
                    if j != i and j not in used
                    and fi.isdisjoint(link_edges[j].link_faces)), -1)
        if opp < 0: return None
        used.add(i); used.add(opp)
        pairs.append((link_edges[i].other_vert(bmv),
                      link_edges[opp].other_vert(bmv)))
    return tuple(pairs) if len(pairs) == 2 else None


def get_bmv_next_loop_vert(prev : BMVert, cur : BMVert, walk_boundaries:bool=True, pole_angle_threshold:float=0) -> BMVert|None:
    ''' The next vert in an edge loop arriving at `cur` from `prev`. '''
    bme : BMEdge

    if walk_boundaries and any(bme.is_boundary for bme in cur.link_edges):
        prev_edge = next((bme for bme in cur.link_edges if bme.other_vert(cur) is prev), None)
        if prev_edge is None or not prev_edge.is_boundary:
            return None
        for bme in cur.link_edges:
            if bme is not prev_edge and bme.is_boundary:
                return bme.other_vert(cur)
        return None

    bme_in : BMEdge | None = next((bme for bme in cur.link_edges if bme.other_vert(cur) == prev), None)
    if bme_in is None: return None
    in_faces : set[BMFace] = set(bme_in.link_faces)
    clean : list[BMVert|None] = [
        bme.other_vert(cur) for bme in cur.link_edges
        if bme.other_vert(cur) != prev
        and not any(bmf in in_faces for bmf in bme.link_faces)
    ]
    if len(clean) == 1:
        return clean[0]

    if pole_angle_threshold <= 0: return None
    d_in = cur.co - prev.co
    if d_in.length < 1e-12: return None

    # Project directions onto the tangent plane at cur so the straightness
    # check works correctly on curved surfaces.
    n = cur.normal
    d_in_t = d_in - d_in.dot(n) * n
    if d_in_t.length < 1e-12:
        d_in_t = d_in  # incoming edge nearly parallel to normal so fall back to 3D
    d_in_t = d_in_t.normalized()
    best, best_dot = None, cos(radians(pole_angle_threshold))
    for bme in cur.link_edges:
        o = bme.other_vert(cur)
        if not o or o == prev: continue
        d_out = o.co - cur.co
        if d_out.length < 1e-12: continue
        d_out_t = d_out - d_out.dot(n) * n
        if d_out_t.length < 1e-12: continue
        dot = d_in_t.dot(d_out_t.normalized())
        if dot > best_dot:
            best_dot, best = dot, o
    return best


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
    bm : BMesh
    matrix : Matrix
    matrix_inv : Matrix
    bvh_faces : BVHTree

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
    loose_bmvs : list[BMVert]
    bvh_verts : BVHTree
    bmv : BMVert | None

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

    def update(self, context, co, *, distance:float=1.84467e19, distance2d:float=10, filter_selected=True, filter_fn=None):
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
        if dist <= (Drawing.scale(distance2d) or 0):
            self.bmv = bmv


def edges_to_triangles(count:int, *, triangle_inds:list[tuple[int,int,int]]=[]) -> list[tuple[int,int,int]]:  # pyright: ignore [reportCallInDefaultInitializer]
    if count > len(triangle_inds):
        triangle_inds.extend([
            (i*2+0, i*2+1, i*2+1)     # IMPORTANT: first two have to be different, otherwise BVH cannot see it?
            for i in range(len(triangle_inds), count*2)
        ])
    return triangle_inds[:count]


class NearestBMEdge(NearestElem):
    bvh_edges : BVHTree
    loose_bmes : list[BMEdge]
    bme : BMEdge | None
    co2d : Vector | None

    def __init__(self, bm:BMesh, matrix:Matrix, matrix_inv:Matrix, *, ensure_lookup_tables:bool=True):
        super().__init__(bm, matrix, matrix_inv, ensure_lookup_tables=ensure_lookup_tables)

        # assuming there are relatively few loose bmes (bmedge that is not part of a bmface)
        self.loose_bmes = [bme for bme in self.bm.edges if not bme.link_faces]
        loose_bme_cos : list[Sequence[float]] = [bmv.co for bme in self.loose_bmes for bmv in bme.verts]
        self.bvh_edges = BVHTree.FromPolygons(loose_bme_cos, edges_to_triangles(len(self.loose_bmes)), all_triangles=True)

        self.bme = None
        self.co2d = None

    @property
    def is_valid(self):
        return all((
            self.bm.is_valid,
            (self.bme is None or self.bme.is_valid),
            all(bme.is_valid for bme in self.loose_bmes),
        ))

    def update(self, context:Context, co:Vector|None, *, distance:float=1.84467e19, distance2d:float=10, ignore_selected:bool=True, filter_fn:None|Callable[[BMEdge], bool]=None) -> BMEdge|None:
        # NOTE: distance here is local to object!!!  target object could be scaled!
        # even stranger is if target is non-uniformly scaled

        self.bme = None
        scaled_distance2d = Drawing.scale(distance2d)
        if not self.is_valid or not co or not scaled_distance2d:
            return None

        _, _, bme_idx, _ = self.bvh_edges.find_nearest(co, distance) # distance=1.0
        _, _, bmf_idx, _ = self.bvh_faces.find_nearest(co, distance) # distance=1.0

        bmes : list[BMEdge] = []
        if bme_idx is not None:
            bmes.append(self.loose_bmes[bme_idx])
        if bmf_idx is not None:
            bmes.extend(self.bm.faces[bmf_idx].edges)
        if filter_fn:
            bmes = [bme for bme in bmes if filter_fn(bme)]
        if ignore_selected:
            bmes = [bme for bme in bmes if not any(bmv.select for bmv in bme.verts)]
        if not bmes:
            return None

        co2d = location_3d_to_region_2d(context.region, context.region_data, self.matrix @ co)
        co2ds = [
            ( location_3d_to_region_2d(context.region, context.region_data, self.matrix @ bmv.co) for bmv in bme.verts )
            for bme in bmes
        ]
        dists = [distance_point_linesegment(co2d, *co2d_) for co2d_ in co2ds]
        bme,dist = min(zip(bmes, dists), key=(lambda bme_dist: bme_dist[1]))
        if dist > scaled_distance2d:
            return None

        self.bme = bme
        co2d0, co2d1 = [location_3d_to_region_2d(context.region, context.region_data, self.matrix @ bmv.co) for bmv in bme.verts]
        co2d = closest_point_linesegment(co2d, co2d0, co2d1)
        if not co2d: return None
        self.co2d = co2d
        return self.bme

class NearestBMFace(NearestElem):
    bmf : BMFace | None

    def __init__(self, bm:BMesh, matrix:Matrix, matrix_inv:Matrix, *, ensure_lookup_tables:bool=True):
        super().__init__(bm, matrix, matrix_inv, ensure_lookup_tables=ensure_lookup_tables)

        self.bmf = None

    @property
    def is_valid(self):
        return all((
            self.bm.is_valid,
            (self.bmf is None or self.bmf.is_valid),
        ))

    def update(self, context:Context, co:Vector|None, *, distance:float=1.84467e19, distance2d:int=10, filter_selected:bool=True, filter_fn:Callable[[BMFace],bool]|None=None):
        # NOTE: distance here is local to object!!!  target object could be scaled!
        # even stranger is if target is non-uniformly scaled

        self.bmf = None
        scaled_distance2d = Drawing.scale(distance2d)
        if not self.is_valid or not co or not scaled_distance2d:
            return

        bmf_co, _, bmf_idx, _ = self.bvh_faces.find_nearest(co, distance) # distance=1.0
        if bmf_co is None or bmf_idx is None: return

        co2d = location_3d_to_region_2d(context.region, context.region_data, self.matrix @ co)
        bmf_co2d = location_3d_to_region_2d(context.region, context.region_data, self.matrix @ bmf_co)
        if not co2d or not bmf_co2d: return
        if (co2d - bmf_co2d).length < scaled_distance2d:
            try:
                self.bmf = self.bm.faces[bmf_idx]
            except IndexError:
                print(f'WARN: ftable is outdated. bmf_idx={bmf_idx}, face_count={len(self.bm.faces)}')
                self.bm.faces.ensure_lookup_table()  # Fix 1617
                self.bmf = self.bm.faces[bmf_idx]

        if filter_fn and self.bmf:
            if not filter_fn(self.bmf):
                self.bmf = None
        elif filter_selected and self.bmf:
            if self.bmf.select:
                self.bmf = None



def is_bmedge_boundary(bme:BMEdge, mirror:set[str], threshold:Vector, clip:bool, *, include_hidden_boundary:bool=True):
    if bme.hide:
        return False

    if not bme.is_boundary and include_hidden_boundary:
        return any(bmf.hide for bmf in bme.link_faces)

    if not bme.is_boundary:
        return False

    if clip:
        tx, ty, tz = threshold
        co0, co1 = bme_cos(bme)
        if 'x' in mirror and abs(co0.x) <= tx and abs(co1.x) <= tx: return False
        if 'y' in mirror and abs(co0.y) <= ty and abs(co1.y) <= ty: return False
        if 'z' in mirror and abs(co0.z) <= tz and abs(co1.z) <= tz: return False

    return True

def is_bmvert_boundary(bmv:BMVert, mirror:set[str], threshold:Vector, clip:bool, *, include_hidden_boundary:bool=True):
    if bmv.hide: return False
    if not bmv.is_boundary and include_hidden_boundary: return any(bme.hide for bme in bmv.link_edges)
    if not bmv.is_boundary: return False
    if not clip: return True
    if 'x' in mirror and abs(bmv.co.x) <= threshold.x: return False
    if 'y' in mirror and abs(bmv.co.y) <= threshold.y: return False
    if 'z' in mirror and abs(bmv.co.z) <= threshold.z: return False
    return True

def is_bmvert_corner(bmv : BMVert) -> bool:
    return (
        len(bmv.link_edges) == 2 or
        len(bmv.link_edges) == 4 and len(bmv.link_faces) == 3
    )

def is_bmvert_on_ngon(bmv : BMVert) -> bool:
    return any(len(bmf.edges) > 4 for bmf in bmv.link_faces)


def get_vert_connected(verts):
    ''' Split a vertex collection into connected islands via shared edges.
    Returns a list of vertex lists, one per island. '''
    sel_set = set(verts)
    edges   = {e for v in verts for e in v.link_edges}
    adj     = {}
    for e in edges:
        v0, v1 = e.verts
        if v0 not in sel_set or v1 not in sel_set:
            continue
        adj.setdefault(v0, []).append(v1)
        adj.setdefault(v1, []).append(v0)

    visited = set()
    components = []
    for start in verts:
        if start in visited: continue
        visited.add(start)
        component = [start]
        queue = list(adj.get(start, []))
        qi = 0
        while qi < len(queue):
            nb = queue[qi]; qi += 1
            if nb in visited: continue
            visited.add(nb)
            component.append(nb)
            queue.extend(adj.get(nb, []))
        components.append(component)
    return components


def get_falloff_verts(verts, mw, radius, falloff_type='SMOOTH', skip_hidden=True):
    ''' Dijkstra BFS from verts. Returns {vert: falloff_weight} map, excluding verts beyond radius. '''
    visited = {}
    queue   = [(0.0, v.index, v) for v in verts]
    while queue:
        d, _, v = heapq.heappop(queue)
        if v in visited:
            continue
        visited[v] = d
        for e in v.link_edges:
            nb = e.other_vert(v)
            if skip_hidden and nb.hide:
                continue
            d_new = d + (mw @ v.co - mw @ nb.co).length
            if d_new <= radius and nb not in visited:
                heapq.heappush(queue, (d_new, nb.index, nb))
    return {v: proportional_edit(falloff_type, 1.0 - d / radius) for v, d in visited.items()}


def get_faces_of_verts(verts):
    ''' Return the set of faces whose verts are all in `verts`. '''
    vert_set   = set(verts)
    seen_faces = set()
    result     = set()
    for v in verts:
        for f in v.link_faces:
            if f in seen_faces:
                continue
            seen_faces.add(f)
            if all(fv in vert_set for fv in f.verts):
                result.add(f)
    return result
