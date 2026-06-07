'''
Copyright (C) 2026 CG Cookie
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

import math, time
from math import inf, isnan
from typing import Iterator

import bmesh
from bpy.types import Context
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from bmesh.types import BMesh, BMVert

from ...addon_common.common.maths import clamp_int
from .iter_utils import AttrIter, CastIter
from .bmesh import edges_to_triangles, is_bmedge_boundary, bme_cos
from .bmesh_maths import is_bmedge_edgemark, BMMarking
from .maths import point_to_bvec3
from .raycast import iter_all_valid_sources

class Accel:
    BINS_COUNT : int = 10
    MIN_REBUILD_TIME : float = 2.0

    bmverts : list[BMVert]
    matrix_world : Matrix
    min_x : float
    min_y : float
    min_z : float
    max_x : float
    max_y : float
    max_z : float
    _bin_scale_x : float
    _bin_scale_y : float
    _bin_scale_z : float
    time : float
    bins : list[list[list[list[BMVert]]]]

    def __init__(self, context:Context, bmverts:list[BMVert], matrix_world:Matrix, *, bbox:list[Vector]|None=None):
        self.bmverts = bmverts
        self.matrix_world = matrix_world
        self.min_x, self.min_y, self.min_z = 0, 0, 0
        self.max_x, self.max_y, self.max_z = 0, 0, 0
        self._bin_scale_x, self._bin_scale_y, self._bin_scale_z = 0, 0, 0
        self.time = time.time() - 1000
        self.rebuild(context)

    def rebuild(self, context:Context):
        if time.time() - self.time < Accel.MIN_REBUILD_TIME:
            return
        if len(self.bmverts) == 0:
            return

        depsgraph = context.evaluated_depsgraph_get()
        object_evaluated = context.edit_object.evaluated_get(depsgraph)
        bbox : list[Vector]|None = list(object_evaluated.bound_box)

        # Check if any corner has NaN values.
        for corner in bbox:
            if isnan(corner[0]) or isnan(corner[1]) or isnan(corner[2]):
                print('RelaxLogic.Accel.rebuild: NaN values were found in bbox: ' + str(corner))
                bbox = None  # fallback to using bmesh verts (slower but already filtered for NaN values)
                break

        # Initilization.
        MW = self.matrix_world
        loc_points : Iterator[Vector] = AttrIter(self.bmverts, 'co') if bbox is None else CastIter(bbox, Vector)
        self.time = time.time()
        self.bins = [[[[] for _ in range(Accel.BINS_COUNT)] for _ in range(Accel.BINS_COUNT)] for _ in range(Accel.BINS_COUNT)]
        self.min_x, self.min_y, self.min_z = inf, inf, inf
        self.max_x, self.max_y, self.max_z = -inf, -inf, -inf
        bins = self.bins
        get_index = self.index

        # Calculate the min/max.
        for lpt in loc_points:
            wpt = MW @ lpt
            self.min_x = min(self.min_x, wpt.x)
            self.min_y = min(self.min_y, wpt.y)
            self.min_z = min(self.min_z, wpt.z)
            self.max_x = max(self.max_x, wpt.x)
            self.max_y = max(self.max_y, wpt.y)
            self.max_z = max(self.max_z, wpt.z)

        # Calculate the size.
        dx, dy, dz = self.max_x - self.min_x, self.max_y - self.min_y, self.max_z - self.min_z
        max_Dxyz = max(dx, dy, dz)
        if dx < 0.001: self.min_x, self.max_x = self.min_x - max_Dxyz * 0.001, self.max_x + max_Dxyz * 0.001
        if dy < 0.001: self.min_y, self.max_y = self.min_y - max_Dxyz * 0.001, self.max_y + max_Dxyz * 0.001
        if dz < 0.001: self.min_z, self.max_z = self.min_z - max_Dxyz * 0.001, self.max_z + max_Dxyz * 0.001

        # Precompute bin scales.
        denom_x = max(0.001, self.max_x - self.min_x)
        denom_y = max(0.001, self.max_y - self.min_y)
        denom_z = max(0.001, self.max_z - self.min_z)
        self._bin_scale_x = Accel.BINS_COUNT / denom_x
        self._bin_scale_y = Accel.BINS_COUNT / denom_y
        self._bin_scale_z = Accel.BINS_COUNT / denom_z

        # Populate the bins.
        for bmv in self.bmverts:
            ix, iy, iz = get_index(MW @ bmv.co)
            bins[ix][iy][iz].append(bmv)

    def index(self, co_world: Vector) -> tuple[int, int, int]:
        max_bin_index = Accel.BINS_COUNT - 1
        ix = clamp_int(int((co_world.x - self.min_x) * self._bin_scale_x), 0, max_bin_index)
        iy = clamp_int(int((co_world.y - self.min_y) * self._bin_scale_y), 0, max_bin_index)
        iz = clamp_int(int((co_world.z - self.min_z) * self._bin_scale_z), 0, max_bin_index)
        return (ix, iy, iz)

    def get(self, co_world:Vector, radius_world:float) -> set[BMVert]:
        M = self.matrix_world
        r2 = radius_world * radius_world
        min_ix, min_iy, min_iz = self.index(co_world - Vector((radius_world, radius_world, radius_world)))
        max_ix, max_iy, max_iz = self.index(co_world + Vector((radius_world, radius_world, radius_world)))
        return {
            v
            for ix in range(min_ix, max_ix+1)
            for iy in range(min_iy, max_iy+1)
            for iz in range(min_iz, max_iz+1)
            for v in self.bins[ix][iy][iz]
            if (M @ v.co - co_world).length_squared <= r2
        }


class EdgeMarkAccel:
    verts     : set[BMVert]
    bvh       : 'BVHTree | None'
    _segments : list[tuple[Vector, Vector]]

    def __init__(
        self,
        segments : list[tuple[Vector, Vector]],
        verts    : 'set[BMVert] | None' = None,
    ):
        self.verts = verts if verts is not None else set()
        self._segments = list(segments)
        self.bvh = BVHTree.FromPolygons(
            [v for vs in segments for v in vs],   # pyright: ignore [reportArgumentType]
            edges_to_triangles(len(segments)),
            all_triangles=True,
        ) if segments else None

    def __bool__(self) -> bool:
        return self.bvh is not None

    def closest_point(self, co: Vector) -> 'Vector | None':
        if self.bvh is None: return None
        return self.bvh.find_nearest(co)[0]

    def closest_point_with_tangent(self, co: Vector) -> 'tuple[Vector, Vector] | None':
        '''Returns (closest_point, edge_tangent_normalized) or None.
        The poly index from find_nearest maps 1-to-1 onto self._segments
        because edges_to_triangles creates exactly one triangle per segment.
        '''
        if self.bvh is None: return None
        loc, _normal, poly_idx, _dist = self.bvh.find_nearest(co)
        if loc is None or poly_idx is None or poly_idx >= len(self._segments): return None
        v0, v1 = self._segments[poly_idx]
        edge_vec = Vector(v1) - Vector(v0)
        length = edge_vec.length
        if length < 1e-8: return None
        return (Vector(loc), edge_vec / length)

    @classmethod
    def from_bmedges(cls, edges: list) -> 'EdgeMarkAccel':
        '''Build from a list of BMEdge objects.'''
        if not edges:
            return cls([])
        return cls([bme_cos(bme) for bme in edges], {bmv for bme in edges for bmv in bme.verts})

    @classmethod
    def build_all(
        cls,
        bm               : BMesh,
        mirror           : set[str],
        mirror_threshold : Vector,
        mirror_clip      : bool,
        *,
        slide_boundary   : bool = False,
        slide_creases    : bool = False,
        slide_sharps     : bool = False,
        slide_seams      : bool = False,
    ) -> 'tuple':

        # Each element unpacks as (verts, accel)
        def pack(edges: list) -> 'tuple[set, EdgeMarkAccel]':
            accel = cls.from_bmedges(edges)
            return accel.verts, accel

        # Fetch the layer here and skip the scan if it is absent
        crease_layer = bm.edges.layers.float.get('crease_edge') if slide_creases else None

        return (
            pack([bme for bme in bm.edges if is_bmedge_boundary(bme, mirror, mirror_threshold, mirror_clip)] if slide_boundary else []),
            pack([bme for bme in bm.edges if bme[crease_layer]] if crease_layer else []),
            pack([bme for bme in bm.edges if not bme.smooth]    if slide_sharps else []),
            pack([bme for bme in bm.edges if bme.seam]          if slide_seams  else []),
        )


class SourceAccel:
    cache_key: tuple | None = None
    cache_val: 'SourceAccel | None' = None
    edge_accel : 'EdgeMarkAccel | None'
    corner_kd  : 'KDTree | None'

    def __init__(self, edge_accel: 'EdgeMarkAccel | None', corner_kd: 'KDTree | None'):
        self.edge_accel = edge_accel
        self.corner_kd  = corner_kd

    def __bool__(self) -> bool:
        '''True when at least one feature edge was found.'''
        return self.edge_accel is not None

    def closest_point(self, co: Vector) -> 'Vector | None':
        return self.edge_accel.closest_point(co) if self.edge_accel else None

    def closest_point_with_tangent(self, co: Vector) -> 'tuple[Vector, Vector] | None':
        return self.edge_accel.closest_point_with_tangent(co) if self.edge_accel else None

    def closest_point_in_threshold(
        self,
        co_local : Vector,
        matrix_world : Matrix,
        matrix_world_inv : Matrix,
        threshold: float,
    ) -> 'Vector | None':
        ''' Transforms co_local to world, finds closest point, returns it in local space if in threshold. '''
        co_world = point_to_bvec3((matrix_world @ Vector((*co_local, 1.0))).xyz)
        p = self.closest_point(co_world)
        if p is None: return None
        closest_p = matrix_world_inv @ Vector(p)
        return closest_p if (closest_p - co_local).length <= threshold else None

    def find_corner(self, co: Vector) -> 'tuple[Vector, int, float] | None':
        return self.corner_kd.find(Vector((co[0], co[1], co[2]))) if self.corner_kd else None

    @classmethod
    def build(
        cls,
        context: Context,
        sources: list = [],
        sharp_threshold: float = math.pi,
        include_sharps: bool = False,
        include_seams: bool = False,
        include_creases: bool = False,
    ) -> 'SourceAccel':
        if not (include_sharps or include_seams or include_creases or sharp_threshold < math.pi):
            return cls(None, None)
        if not sources:
            sources = list(iter_all_valid_sources(context))
        cache_key = (
            frozenset(obj.name for obj in sources),
            sharp_threshold,
            include_sharps,
            include_seams,
            include_creases,
        )
        if cls.cache_key == cache_key and cls.cache_val is not None:
            return cls.cache_val

        cos_threshold = math.cos(sharp_threshold)
        segments: list[tuple[Vector, Vector]] = []
        vert_feature_count: dict[int, int] = {}
        vert_world_pos: dict[int, Vector] = {}
        depsgraph = context.evaluated_depsgraph_get()

        for obj in sources:
            M = obj.matrix_world
            bm = bmesh.new()
            try:
                bm.from_object(obj.evaluated_get(depsgraph), depsgraph)
                bm.verts.ensure_lookup_table()
                bm.edges.ensure_lookup_table()
                for bme in bm.edges:
                    is_feature = include_sharps and is_bmedge_edgemark(bm, bme, BMMarking.sharp)
                    if not is_feature and include_seams:
                        is_feature = is_bmedge_edgemark(bm, bme, BMMarking.seam)
                    if not is_feature and include_creases:
                        is_feature = is_bmedge_edgemark(bm, bme, BMMarking.crease)
                    if not is_feature and len(bme.link_faces) == 2:
                        n0 = bme.link_faces[0].normal
                        n1 = bme.link_faces[1].normal
                        if n0.length > 0 and n1.length > 0:
                            is_feature = n0.normalized().dot(n1.normalized()) < cos_threshold
                    if is_feature:
                        v0, v1 = bme.verts
                        v0w = point_to_bvec3((M @ Vector((*v0.co, 1.0))).xyz)
                        v1w = point_to_bvec3((M @ Vector((*v1.co, 1.0))).xyz)
                        segments.append((v0w, v1w))
                        for v, vw in ((v0, v0w), (v1, v1w)):
                            idx = v.index
                            vert_feature_count[idx] = vert_feature_count.get(idx, 0) + 1
                            vert_world_pos[idx] = vw

                # 5+ edge poles whose total face-angle curvature exceeds
                # sharp_threshold are treated as corners. This catches cone tips.
                for bmv in bm.verts:
                    if len(bmv.link_edges) < 5:
                        continue
                    idx = bmv.index
                    if vert_feature_count.get(idx, 0) >= 3:
                        continue  # already registered as a corner via feature edges
                    total_curvature = sum(
                        bme.calc_face_angle(0.0)
                        for bme in bmv.link_edges
                        if len(bme.link_faces) == 2
                    )
                    if total_curvature > sharp_threshold:
                        vw = point_to_bvec3((M @ Vector((*bmv.co, 1.0))).xyz)
                        vert_world_pos[idx] = vw
                        vert_feature_count[idx] = 3  # satisfy the corner threshold
            finally:
                bm.free()

        edge_accel = EdgeMarkAccel(segments) if segments else None

        corner_pts = [pos for k, pos in vert_world_pos.items() if vert_feature_count[k] >= 3]
        corner_kd: KDTree | None = None
        if corner_pts:
            corner_kd = KDTree(len(corner_pts))
            for i, pos in enumerate(corner_pts):
                corner_kd.insert(pos, i)
            corner_kd.balance()

        instance = cls(edge_accel, corner_kd)
        cls.cache_key = cache_key
        cls.cache_val = instance
        return instance

    @classmethod
    def build_from_tool(cls, context: Context, tool, sources: list) -> 'SourceAccel | None':
        ''' Build from a tool's `source_edge_*` operator properties.  Returns None when
        feature snapping is disabled or no feature type is selected.  `sources` is the
        precomputed [(obj, M, Mi, Mi_3x3), ...] list built in the tool's __init__. '''
        source_angle   = getattr(tool, 'source_edge_angle', math.pi)
        if not getattr(tool, 'source_edge_angle_enabled', True):
            source_angle = math.pi
        source_sharps  = getattr(tool, 'source_edge_sharps',  False)
        source_seams   = getattr(tool, 'source_edge_seams',   False)
        source_creases = getattr(tool, 'source_edge_creases', False)
        if not (source_sharps or source_seams or source_creases or source_angle < math.pi):
            return None
        return cls.build(
            context, [src[0] for src in sources], source_angle, source_sharps, source_seams, source_creases,
        )
