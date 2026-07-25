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

import heapq
import math, time
from math import inf, isnan
from typing import Iterator

import bpy
import bmesh
import numpy as np
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
from ..rfglobals import RFGlobals

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

    def closest_point_with_index(self, co: Vector) -> 'tuple[Vector, Vector, int] | None':
        '''Returns (closest_point, edge_tangent_normalized, segment_index) or None.'''
        if self.bvh is None: return None
        loc, _normal, poly_idx, _dist = self.bvh.find_nearest(co)
        if loc is None or poly_idx is None or poly_idx >= len(self._segments): return None
        v0, v1 = self._segments[poly_idx]
        edge_vec = Vector(v1) - Vector(v0)
        length = edge_vec.length
        if length < 1e-8: return None
        return (Vector(loc), edge_vec / length, poly_idx)

    def closest_point_in_segments(self, co: Vector, seg_indices: 'set[int]') -> 'tuple[Vector, Vector] | None':
        '''Nearest point constrained to a subset of segments. Returns (closest_point, tangent) or None.
        Fastest path is when the unconstrained nearest already lies on the subset. Otherwise, brute-force the subset. '''
        if self.bvh is None or not seg_indices: return None
        loc, _normal, poly_idx, _dist = self.bvh.find_nearest(co)
        if loc is not None and poly_idx is not None and poly_idx in seg_indices:
            v0, v1 = self._segments[poly_idx]
            edge_vec = Vector(v1) - Vector(v0)
            length = edge_vec.length
            if length >= 1e-8:
                return (Vector(loc), edge_vec / length)
        co = Vector(co)
        best_pt, best_tan, best_d2 = None, None, float('inf')
        for idx in seg_indices:
            if idx >= len(self._segments): continue
            v0, v1 = self._segments[idx]
            p0, seg = Vector(v0), Vector(v1) - Vector(v0)
            seg_len2 = seg.length_squared
            if seg_len2 < 1e-16: continue
            t = max(0.0, min(1.0, (co - p0).dot(seg) / seg_len2))
            pt = p0 + seg * t
            d2 = (pt - co).length_squared
            if d2 < best_d2:
                best_pt, best_tan, best_d2 = pt, seg / math.sqrt(seg_len2), d2
        if best_pt is None: return None
        return (best_pt, best_tan)

    def segments_in_range(self, co: Vector, radius: float) -> 'list[tuple[int, Vector, float]]':
        '''(segment index, closest point on it, distance) for every feature segment with a point within
        radius of co, not just the nearest one. Lets a caller see a feature it is near even where
        another feature is the closer one, and compare them.'''
        if self.bvh is None: return []
        return [
            (idx, Vector(loc), dist)
            for (loc, _normal, idx, dist) in self.bvh.find_nearest_range(co, radius)
            if idx is not None and idx < len(self._segments)
        ]

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


USE_VECTORIZED_SOURCE_BUILD = True
class SourceAccel:
    '''Builder for source feature detection data. Caching/lifetime is owned by SourceCache (below)
    so a single cache can be shared across tools and persisted across RF enter/exit. Don't add a cache here. '''
    edge_accel : 'EdgeMarkAccel | None'
    corner_kd  : 'KDTree | None'

    CORNER_POLE_CHORD_RATIO = 0.15 # How far, in avg edge lengths, should a corner be from a straight line between its neighbors

    def __init__(self, edge_accel: 'EdgeMarkAccel | None', corner_kd: 'KDTree | None'):
        self.edge_accel = edge_accel
        self.corner_kd  = corner_kd
        # Feature-run topology
        self._seg_keys    : 'list[tuple[tuple, tuple]]' = []
        self._seg_lengths : 'list[float]' = []
        self._seg_adjacency : 'dict[tuple, list[int]]' = {}
        self._junction_keys   : 'set[tuple]' = set()

    def __bool__(self) -> bool:
        '''True when at least one feature edge was found.'''
        return self.edge_accel is not None

    def closest_point(self, co: Vector) -> 'Vector | None':
        return self.edge_accel.closest_point(co) if self.edge_accel else None

    def closest_point_with_tangent(self, co: Vector) -> 'tuple[Vector, Vector] | None':
        return self.edge_accel.closest_point_with_tangent(co) if self.edge_accel else None

    def closest_point_with_index(self, co: Vector) -> 'tuple[Vector, Vector, int] | None':
        return self.edge_accel.closest_point_with_index(co) if self.edge_accel else None

    def closest_point_in_segments(self, co: Vector, seg_indices: 'set[int]') -> 'tuple[Vector, Vector] | None':
        return self.edge_accel.closest_point_in_segments(co, seg_indices) if self.edge_accel else None

    def segments_in_range(self, co: Vector, radius: float) -> 'list[tuple[int, Vector, float]]':
        return self.edge_accel.segments_in_range(co, radius) if self.edge_accel else []

    @staticmethod
    def _get_endpoint_hash(co) -> tuple:
        return (round(co[0], 9), round(co[1], 9), round(co[2], 9))

    def _build_run_topology(self, segments: list, corner_pts: list):
        ''' Precompute segment endpoint adjacency, arc lengths, and junctions. '''
        q = self._get_endpoint_hash
        self._seg_keys = []
        self._seg_lengths = []
        self._seg_adjacency = {}
        for idx, (v0, v1) in enumerate(segments):
            k0, k1 = q(v0), q(v1)
            self._seg_keys.append((k0, k1))
            self._seg_lengths.append((Vector(v1) - Vector(v0)).length)
            self._seg_adjacency.setdefault(k0, []).append(idx)
            self._seg_adjacency.setdefault(k1, []).append(idx)
        # Runs terminate at detected poles and dead ends
        self._junction_keys = {q(p) for p in corner_pts}
        self._junction_keys.update(k for k, segs in self._seg_adjacency.items() if len(segs) != 2)

    def corner_on_segments(self, corner_co, seg_indices: 'set[int]') -> bool:
        ''' True when corner_co coincides with an endpoint of any of the given segments,
        i.e. the corner belongs to that run of feature edges. '''
        key = self._get_endpoint_hash(corner_co)
        keys = self._seg_keys
        return any(key in keys[idx] for idx in seg_indices if idx < len(keys))

    def local_runs(self, seed_seg_indices: 'set[int]', margin_world: float) -> 'tuple[dict[int, int], dict[int, set[int]]]':
        ''' Label locally connected runs of feature segments around the given seeds.
        Expands each seed along the feature, never through a pole, up to margin_world of accumulated arc length,
        then labels connected components of the expanded set. Returns (seg_idx -> run_id, run_id -> set of seg_idx). '''
        adjacency, keys, lengths = self._seg_adjacency, self._seg_keys, self._seg_lengths
        if not adjacency or not seed_seg_indices:
            return {}, {}
        walls = self._junction_keys

        # Multi-source expansion by accumulated arc length from the nearest seed.
        dist = {idx: 0.0 for idx in seed_seg_indices if idx < len(keys)}
        heap = [(0.0, idx) for idx in dist]
        heapq.heapify(heap)
        while heap:
            d, idx = heapq.heappop(heap)
            if d > dist.get(idx, float('inf')):
                continue
            d_next = d + lengths[idx]
            if d_next > margin_world:
                continue
            for k in keys[idx]:
                if k in walls: continue
                for nb in adjacency.get(k, ()):
                    if d_next < dist.get(nb, float('inf')):
                        dist[nb] = d_next
                        heapq.heappush(heap, (d_next, nb))

        # Connected components of the expanded set become the runs.
        expanded = set(dist)
        seg_run: dict[int, int] = {}
        run_segs: dict[int, set[int]] = {}
        run_id = 0
        for start in expanded:
            if start in seg_run: continue
            component = {start}
            stack = [start]
            while stack:
                idx = stack.pop()
                seg_run[idx] = run_id
                for k in keys[idx]:
                    if k in walls: continue
                    for nb in adjacency.get(k, ()):
                        if nb in expanded and nb not in component:
                            component.add(nb)
                            stack.append(nb)
            run_segs[run_id] = component
            run_id += 1
        return seg_run, run_segs

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

    @staticmethod
    def has_line_through(v_pos, nbr_positions) -> bool:
        ''' True if the vert sits close to the chord between a pair of neighbors, i.e. a straight line runs through it. '''
        ratio = SourceAccel.CORNER_POLE_CHORD_RATIO
        k = len(nbr_positions)
        for i in range(k):
            P = nbr_positions[i]
            for j in range(i + 1, k):
                Q = nbr_positions[j]
                PQ = Q - P
                L2 = float(PQ @ PQ)
                if L2 < 1e-18: continue
                t = float((v_pos - P) @ PQ) / L2
                if t < 0.05 or t > 0.95: continue  # vert must lie between the two neighbors
                perp = v_pos - (P + t * PQ)
                if math.sqrt(float(perp @ perp) / L2) < ratio:
                    return True
        return False

    @staticmethod
    def bmv_has_line_through(bmv, M) -> bool:
        ''' has_line_through for a BMVert, gathering its neighbors from link_edges in world space. '''
        Mnp = np.array(M, dtype=np.float64)
        R, t = Mnp[:3, :3], Mnp[:3, 3]
        w = lambda co: R @ np.array((co[0], co[1], co[2]), dtype=np.float64) + t
        v_pos = w(bmv.co)
        nbrs = [w(e.other_vert(bmv).co) for e in bmv.link_edges]
        return SourceAccel.has_line_through(v_pos, nbrs)

    @staticmethod
    def verts_without_line_through(cand_idx, world, edges):
        ''' Drop candidate verts that have a smooth line running through them. `cand_idx` is a numpy array of vert indices.
        `edges` is the Nx2 edge->verts array whose adjacency defines the "line". Returns the surviving subset. '''
        if not len(cand_idx):
            return cand_idx
        cand_mask = np.zeros(len(world), dtype=bool)
        cand_mask[cand_idx] = True
        incident = edges[cand_mask[edges[:, 0]] | cand_mask[edges[:, 1]]] if len(edges) else edges
        adj: dict[int, list[int]] = {int(v): [] for v in cand_idx}
        for a, b in incident:
            a, b = int(a), int(b)
            if a in adj: adj[a].append(b)
            if b in adj: adj[b].append(a)
        keep = []
        for v in cand_idx:
            vi = int(v)
            nbrs = [world[nb] for nb in adj[vi]]
            if not SourceAccel.has_line_through(world[vi], nbrs):
                keep.append(vi)
        return np.array(keep, dtype=np.int64)

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
        ''' Synchronous build over all sources. SourceCache drives an incremental version of this,
        chunked over timer ticks, for heavy sources. This is the one-shot version for operators. '''
        if not (include_sharps or include_seams or include_creases or sharp_threshold < math.pi):
            return cls(None, None)
        if not sources:
            sources = list(iter_all_valid_sources(context))

        cos_threshold = math.cos(sharp_threshold)
        depsgraph = context.evaluated_depsgraph_get()
        segments: list[tuple[Vector, Vector]] = []
        corner_pts: list[Vector] = []
        for obj in sources:
            segs, corners = cls.extract_object_features(
                obj, depsgraph, cos_threshold, sharp_threshold,
                include_sharps, include_seams, include_creases,
            )
            segments.extend(segs)
            corner_pts.extend(corners)
        return cls.finalize(segments, corner_pts)

    @classmethod
    def extract_object_features(
        cls, obj, depsgraph, cos_threshold: float, sharp_threshold: float,
        include_sharps: bool, include_seams: bool, include_creases: bool,
    ) -> 'tuple[list, list]':
        ''' Detect features on one source object. Returns (segments, corner_positions) in world space.
        Vectorized (numpy) by default, falling back to the bmesh scan if the fast path fails. '''
        M = obj.matrix_world
        if USE_VECTORIZED_SOURCE_BUILD:
            try:
                return cls.extract_object_vectorized(
                    obj, depsgraph, M, cos_threshold, sharp_threshold, include_sharps, include_seams, include_creases
                )
            except Exception as e:
                print(f'SourceAccel: vectorized extract failed on {obj.name!r} ({e}); using bmesh fallback')
        return cls.extract_object_bmesh(
            obj, depsgraph, M, cos_threshold, sharp_threshold, include_sharps, include_seams, include_creases
        )

    @staticmethod
    def extract_object_bmesh(obj, depsgraph, M, cos_threshold, sharp_threshold, include_sharps, include_seams, include_creases):
        ''' Reference per-object detection using bmesh. '''
        segments: list[tuple[Vector, Vector]] = []
        vert_feature_count: dict[int, int] = {}
        vert_world_pos: dict[int, Vector] = {}
        feature_edges: set[int] = set()
        feature_adj: dict[int, list[int]] = {}
        pole_corners: set[int] = set()
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
                    feature_edges.add(bme.index)
                    v0, v1 = bme.verts
                    feature_adj.setdefault(v0.index, []).append(v1.index)
                    feature_adj.setdefault(v1.index, []).append(v0.index)
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
                # Exclude feature edges, their sharpness is already handled above. Counting it here
                # would flag every mid-crease vert on a triangulated mesh once it has 5+ edges.
                total_curvature = sum(
                    bme.calc_face_angle(0.0)
                    for bme in bmv.link_edges
                    if len(bme.link_faces) == 2 and bme.index not in feature_edges
                )
                # Only accept poles with no straight lines running through them.
                if total_curvature > sharp_threshold and not SourceAccel.bmv_has_line_through(bmv, M):
                    vert_world_pos[idx] = point_to_bvec3((M @ Vector((*bmv.co, 1.0))).xyz)
                    pole_corners.add(idx)
        finally:
            bm.free()

        # Junctions are corners only if no feature line runs straight through them
        _np = lambda p: np.array((p[0], p[1], p[2]), dtype=np.float64)
        corner_pts = []
        for k, pos in vert_world_pos.items():
            if k in pole_corners:
                corner_pts.append(pos)
            elif vert_feature_count.get(k, 0) >= 3:
                nbrs = [_np(vert_world_pos[n]) for n in feature_adj.get(k, []) if n in vert_world_pos]
                if not SourceAccel.has_line_through(_np(pos), nbrs):
                    corner_pts.append(pos)
        return segments, corner_pts

    @staticmethod
    def extract_object_features_incremental(obj, depsgraph, M, cos_threshold, sharp_threshold, include_sharps,
                                            include_seams, include_creases, edge_batch_size: int = 8192, vert_batch_size: int = 4096):
        ''' Incremental extractor for one source object.
        Yields (progress_0_to_1, segments_or_none, corners_or_none) so callers can animate
        progress and keep the UI responsive while very dense meshes are processed. '''
        if USE_VECTORIZED_SOURCE_BUILD:
            try:
                yield from SourceAccel.extract_object_vectorized_incremental(
                    obj, depsgraph, M, cos_threshold, sharp_threshold,
                    include_sharps, include_seams, include_creases,
                    batch_size=edge_batch_size,
                )
                return
            except Exception as e:
                print(f'SourceAccel: vectorized incremental extract failed on {obj.name!r} ({e}); using bmesh fallback')

        yield from SourceAccel.extract_object_bmesh_incremental(
            obj, depsgraph, M, cos_threshold, sharp_threshold,
            include_sharps, include_seams, include_creases,
            edge_batch_size=edge_batch_size,
            vert_batch_size=vert_batch_size,
        )

    @staticmethod
    def extract_object_bmesh_incremental(
        obj,
        depsgraph,
        M,
        cos_threshold,
        sharp_threshold,
        include_sharps,
        include_seams,
        include_creases,
        *,
        edge_batch_size: int,
        vert_batch_size: int,
    ):
        ''' Incremental bmesh fallback extractor for one source object. '''
        segments: list[tuple[Vector, Vector]] = []
        vert_feature_count: dict[int, int] = {}
        vert_world_pos: dict[int, Vector] = {}
        feature_edges: set[int] = set()
        feature_adj: dict[int, list[int]] = {}
        pole_corners: set[int] = set()

        bm = bmesh.new()
        try:
            bm.from_object(obj.evaluated_get(depsgraph), depsgraph)
            bm.verts.ensure_lookup_table()
            bm.edges.ensure_lookup_table()

            n_edges = len(bm.edges)
            n_verts = len(bm.verts)
            total_work = max(1, n_edges + n_verts)
            processed = 0

            for edge_start in range(0, n_edges, edge_batch_size):
                edge_end = min(edge_start + edge_batch_size, n_edges)
                for bme in bm.edges[edge_start:edge_end]:
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
                        feature_edges.add(bme.index)
                        v0, v1 = bme.verts
                        feature_adj.setdefault(v0.index, []).append(v1.index)
                        feature_adj.setdefault(v1.index, []).append(v0.index)
                        v0w = point_to_bvec3((M @ Vector((*v0.co, 1.0))).xyz)
                        v1w = point_to_bvec3((M @ Vector((*v1.co, 1.0))).xyz)
                        segments.append((v0w, v1w))
                        for v, vw in ((v0, v0w), (v1, v1w)):
                            idx = v.index
                            vert_feature_count[idx] = vert_feature_count.get(idx, 0) + 1
                            vert_world_pos[idx] = vw

                processed += edge_end - edge_start
                yield processed / total_work, None, None

            for vert_start in range(0, n_verts, vert_batch_size):
                vert_end = min(vert_start + vert_batch_size, n_verts)
                for bmv in bm.verts[vert_start:vert_end]:
                    if len(bmv.link_edges) < 5:
                        continue
                    idx = bmv.index
                    if vert_feature_count.get(idx, 0) >= 3:
                        continue  # already registered as a corner via feature edges
                    # Exclude feature edges from pole curvature, otherwise
                    # every mid-crease vert on a triangulated mesh is misclassified as a corner.
                    total_curvature = sum(
                        bme.calc_face_angle(0.0)
                        for bme in bmv.link_edges
                        if len(bme.link_faces) == 2 and bme.index not in feature_edges
                    )
                    # Reject poles with a smooth line running through them.
                    if total_curvature > sharp_threshold and not SourceAccel.bmv_has_line_through(bmv, M):
                        vert_world_pos[idx] = point_to_bvec3((M @ Vector((*bmv.co, 1.0))).xyz)
                        pole_corners.add(idx)

                processed += vert_end - vert_start
                yield processed / total_work, None, None
        finally:
            bm.free()

        # Junctions are corners only if no feature line runs straight through them.
        _np = lambda p: np.array((p[0], p[1], p[2]), dtype=np.float64)
        corner_pts = []
        for k, pos in vert_world_pos.items():
            if k in pole_corners:
                corner_pts.append(pos)
            elif vert_feature_count.get(k, 0) >= 3:
                nbrs = [_np(vert_world_pos[n]) for n in feature_adj.get(k, []) if n in vert_world_pos]
                if not SourceAccel.has_line_through(_np(pos), nbrs):
                    corner_pts.append(pos)
        yield 1.0, segments, corner_pts

    @staticmethod
    def extract_object_vectorized_incremental(obj, depsgraph, M, cos_threshold, sharp_threshold, include_sharps,
                                                include_seams, include_creases, batch_size: int = 8192):
        ''' Incremental numpy/blender mesh extractor for one source object. '''
        yield 0.0, None, None # Yield at the start so the progress bar renders before work begins.

        needs_evaluated_mesh = bool(obj.modifiers) # Skip evaluated_get() and to_mesh() when obj has no modifiers
        if needs_evaluated_mesh:
            obj_eval   = obj.evaluated_get(depsgraph)
            mesh       = obj_eval.to_mesh()
            clear_mesh = obj_eval.to_mesh_clear
        else:
            mesh       = obj.data
            clear_mesh = lambda: None   # nothing to clear

        try:
            n_verts = len(mesh.vertices)
            n_edges = len(mesh.edges)
            n_polys = len(mesh.polygons)
            n_loops = len(mesh.loops)
            if n_verts == 0 or n_edges == 0:
                yield 1.0, [], []
                return

            batch_size = max(256, int(batch_size))
            total_work = max(1, n_edges + n_verts)
            edge_progress_end = n_edges / total_work
            setup_cap   = min(0.25, edge_progress_end * 0.5) # Setup steps share the first 25% of progress
            setup_steps = 4
            setup_step  = 0

            def _yield_setup():
                nonlocal setup_step
                setup_step += 1
                return setup_cap * (setup_step / setup_steps)

            # vertex coords (local) -> world (affine: world = co @ R^T + t)
            co = np.empty(n_verts * 3, dtype=np.float64)
            mesh.vertices.foreach_get('co', co)
            yield _yield_setup(), None, None
            co = co.reshape(n_verts, 3)
            Mnp  = np.array(M, dtype=np.float64)
            world = co @ Mnp[:3, :3].T + Mnp[:3, 3]

            # edge -> vertex indices
            edge_verts = np.empty(n_edges * 2, dtype=np.int64)
            mesh.edges.foreach_get('vertices', edge_verts)
            yield _yield_setup(), None, None
            edge_verts = edge_verts.reshape(n_edges, 2)

            # feature mask from edge marks
            feat = np.zeros(n_edges, dtype=bool)
            if include_sharps:
                sharp = np.empty(n_edges, dtype=bool)
                mesh.edges.foreach_get('use_edge_sharp', sharp)
                feat |= sharp
            if include_seams:
                seam = np.empty(n_edges, dtype=bool)
                mesh.edges.foreach_get('use_seam', seam)
                feat |= seam
            if include_creases:
                attr = mesh.attributes.get('crease_edge')
                if attr is not None:
                    crease = np.empty(n_edges, dtype=np.float64)
                    attr.data.foreach_get('value', crease)
                    feat |= (crease > 0.0)
            yield _yield_setup(), None, None

            edge_angle = np.zeros(n_edges, dtype=np.float64)
            if n_loops and n_polys:
                loop_edge = np.empty(n_loops, dtype=np.int64)
                mesh.loops.foreach_get('edge_index', loop_edge)
                loop_total = np.empty(n_polys, dtype=np.int64)
                mesh.polygons.foreach_get('loop_total', loop_total)
                loop_poly = np.repeat(np.arange(n_polys, dtype=np.int64), loop_total)
                pn = np.empty(n_polys * 3, dtype=np.float64)
                mesh.polygons.foreach_get('normal', pn)
                pn = pn.reshape(n_polys, 3)
                yield _yield_setup(), None, None

                counts = np.bincount(loop_edge, minlength=n_edges)
                order  = np.argsort(loop_edge, kind='stable')
                sorted_polys = loop_poly[order]
                offsets = np.zeros(n_edges, dtype=np.int64)
                if n_edges > 1:
                    np.cumsum(counts[:-1], out=offsets[1:])
                manifold = np.nonzero(counts == 2)[0]

                if manifold.size:
                    mcount = manifold.size
                    for mstart in range(0, mcount, batch_size):
                        mend = min(mstart + batch_size, mcount)
                        me   = manifold[mstart:mend]
                        f0, f1 = sorted_polys[offsets[me]], sorted_polys[offsets[me] + 1]
                        n0, n1 = pn[f0], pn[f1]
                        n0len  = np.einsum('ij,ij->i', n0, n0)
                        n1len  = np.einsum('ij,ij->i', n1, n1)
                        valid  = (n0len > 1e-12) & (n1len > 1e-12)
                        if np.any(valid):
                            me_valid = me[valid]
                            dots = np.clip(np.einsum('ij,ij->i', n0[valid], n1[valid]), -1.0, 1.0)
                            edge_angle[me_valid] = np.arccos(dots)
                            feat[me_valid] |= (dots < cos_threshold)
                        yield setup_cap + (edge_progress_end - setup_cap) * (mend / mcount), None, None

            if setup_step < setup_steps:
                yield edge_progress_end, None, None

            # segments from feature edges (converted in batches)
            fe = np.nonzero(feat)[0]
            segments: list[tuple[Vector, Vector]] = []
            for start in range(0, fe.size, batch_size):
                end = min(start + batch_size, fe.size)
                idx = fe[start:end]
                segments.extend((Vector(a), Vector(b)) for a, b in world[edge_verts[idx]])

            # corners are verts touched by >=3 feature edges or high-curvature 5+ poles
            vfc = np.bincount(edge_verts[fe].ravel(), minlength=n_verts) if fe.size else np.zeros(n_verts, dtype=np.int64)
            vert_edge_count = np.bincount(edge_verts.ravel(), minlength=n_verts)
            # Pole curvature excludes feature edges, otherwise every
            # mid-crease vert on a triangulated mesh is flagged as a corner.
            pole_edge_angle = np.where(feat, 0.0, edge_angle)
            vert_curv = np.zeros(n_verts, dtype=np.float64)
            np.add.at(vert_curv, edge_verts.ravel(), np.repeat(pole_edge_angle, 2))

            corner_mask = vfc >= 3
            pole_mask = (vert_edge_count >= 5) & (~corner_mask) & (vert_curv > sharp_threshold)
            # Junctions gated by feature line-through, poles by surface line-through.
            junction_idx = SourceAccel.verts_without_line_through(np.nonzero(corner_mask)[0], world, edge_verts[fe])
            pole_idx = SourceAccel.verts_without_line_through(np.nonzero(pole_mask)[0], world, edge_verts)
            corner_idx = np.concatenate((junction_idx, pole_idx))

            corner_pts: list[Vector] = []
            for start in range(0, corner_idx.size, batch_size):
                corner_pts.extend(Vector(p) for p in world[corner_idx[start:start + batch_size]])
                yield (n_edges + n_verts * min(start + batch_size, corner_idx.size) / max(corner_idx.size, 1)) / total_work, None, None
        finally:
            clear_mesh()

        yield 1.0, segments, corner_pts

    @staticmethod
    def extract_object_vectorized(obj, depsgraph, M, cos_threshold, sharp_threshold, include_sharps, include_seams, include_creases):
        obj_eval = obj.evaluated_get(depsgraph)
        mesh = obj_eval.to_mesh()
        try:
            n_verts = len(mesh.vertices)
            n_edges = len(mesh.edges)
            n_polys = len(mesh.polygons)
            n_loops = len(mesh.loops)
            if n_verts == 0 or n_edges == 0:
                return [], []

            # vertex coords (local) -> world (affine: world = co @ R^T + t)
            co = np.empty(n_verts * 3, dtype=np.float64)
            mesh.vertices.foreach_get('co', co)
            co = co.reshape(n_verts, 3)
            Mnp = np.array(M, dtype=np.float64)  # 4x4, rows are matrix rows
            world = co @ Mnp[:3, :3].T + Mnp[:3, 3]

            # edge -> vertex indices
            edge_verts = np.empty(n_edges * 2, dtype=np.int64)
            mesh.edges.foreach_get('vertices', edge_verts)
            edge_verts = edge_verts.reshape(n_edges, 2)

            # feature mask from edge marks
            feat = np.zeros(n_edges, dtype=bool)
            if include_sharps:
                sharp = np.empty(n_edges, dtype=bool)
                mesh.edges.foreach_get('use_edge_sharp', sharp)
                feat |= sharp
            if include_seams:
                seam = np.empty(n_edges, dtype=bool)
                mesh.edges.foreach_get('use_seam', seam)
                feat |= seam
            if include_creases:
                attr = mesh.attributes.get('crease_edge')
                if attr is not None:
                    crease = np.empty(n_edges, dtype=np.float64)
                    attr.data.foreach_get('value', crease)
                    feat |= (crease > 0.0)

            # edge -> the (up to 2) adjacent faces, reconstructed from loops, for the dihedral angle between face normals.
            edge_angle = np.zeros(n_edges, dtype=np.float64) # stays 0 for boundary or non-manifold edges
            if n_loops and n_polys:
                loop_edge = np.empty(n_loops, dtype=np.int64)
                mesh.loops.foreach_get('edge_index', loop_edge)
                loop_total = np.empty(n_polys, dtype=np.int64)
                mesh.polygons.foreach_get('loop_total', loop_total)
                loop_poly = np.repeat(np.arange(n_polys, dtype=np.int64), loop_total)
                pn = np.empty(n_polys * 3, dtype=np.float64)
                mesh.polygons.foreach_get('normal', pn) # polygon normals are unit length
                pn = pn.reshape(n_polys, 3)

                counts = np.bincount(loop_edge, minlength=n_edges)
                order = np.argsort(loop_edge, kind='stable')  # loop indices grouped by edge
                sorted_polys = loop_poly[order]
                offsets = np.zeros(n_edges, dtype=np.int64)  # start of each edge's run
                if n_edges > 1:
                    np.cumsum(counts[:-1], out=offsets[1:])
                manifold = np.nonzero(counts == 2)[0]
                if manifold.size:
                    f0 = sorted_polys[offsets[manifold]]
                    f1 = sorted_polys[offsets[manifold] + 1]
                    n0, n1 = pn[f0], pn[f1]
                    n0len = np.einsum('ij,ij->i', n0, n0)
                    n1len = np.einsum('ij,ij->i', n1, n1)
                    valid = (n0len > 1e-12) & (n1len > 1e-12)   # skip zero normals
                    dots = np.clip(np.einsum('ij,ij->i', n0, n1), -1.0, 1.0)
                    me = manifold[valid]
                    edge_angle[me] = np.arccos(dots[valid])
                    if sharp_threshold < math.pi:
                        feat[me] |= (dots[valid] < cos_threshold)

            # segments are world coords of each feature edge's two verts
            fe = np.nonzero(feat)[0]
            segments = [(Vector(a), Vector(b)) for a, b in world[edge_verts[fe]]] if fe.size else []

            # corners are verts touched by >=3 feature edges or high-curvature 5+ poles
            vfc = np.bincount(edge_verts[fe].ravel(), minlength=n_verts) if fe.size else np.zeros(n_verts, dtype=np.int64)
            corner_mask = vfc >= 3
            vert_edge_count = np.bincount(edge_verts.ravel(), minlength=n_verts)
            pole_edge_angle = np.where(feat, 0.0, edge_angle)
            vert_curv = np.zeros(n_verts, dtype=np.float64)
            np.add.at(vert_curv, edge_verts.ravel(), np.repeat(pole_edge_angle, 2))
            pole_mask = (vert_edge_count >= 5) & (~corner_mask) & (vert_curv > sharp_threshold)
            # Drop false positive corners
            junction_idx = SourceAccel.verts_without_line_through(np.nonzero(corner_mask)[0], world, edge_verts[fe])
            pole_idx = SourceAccel.verts_without_line_through(np.nonzero(pole_mask)[0], world, edge_verts)
            corner_idx = np.concatenate((junction_idx, pole_idx))
            corner_pts = [Vector(p) for p in world[corner_idx]]
            return segments, corner_pts
        finally:
            obj_eval.to_mesh_clear()

    @staticmethod
    def _dedupe_features(segments: list, corner_pts: list) -> 'tuple[list, list]':
        ''' Drop duplicate feature segments and corner points. Each detection type is scanned in
        its own pass (sharps / seams / creases / angle), so an edge matching several criteria is
        reported once per pass. Consumers assume segment uniqueness — e.g. run-topology walls
        count endpoint incidence, and doubled segments would make every interior endpoint of a
        feature chain look like a junction. '''
        q = SourceAccel._get_endpoint_hash
        seen_segs = set()
        unique_segments = []
        for seg in segments:
            k0, k1 = q(seg[0]), q(seg[1])
            key = (k0, k1) if k0 <= k1 else (k1, k0)
            if key in seen_segs: continue
            seen_segs.add(key)
            unique_segments.append(seg)
        seen_pts = set()
        unique_corners = []
        for p in corner_pts:
            key = q(p)
            if key in seen_pts: continue
            seen_pts.add(key)
            unique_corners.append(p)
        return unique_segments, unique_corners

    @staticmethod
    def finalize(segments: list, corner_pts: list) -> 'SourceAccel':
        ''' Assemble the feature-edge BVH + corner KDTree from accumulated per-object results. '''
        segments, corner_pts = SourceAccel._dedupe_features(segments, corner_pts)
        edge_accel = EdgeMarkAccel(segments) if segments else None
        corner_kd: KDTree | None = None
        if corner_pts:
            corner_kd = KDTree(len(corner_pts))
            for i, pos in enumerate(corner_pts):
                corner_kd.insert(pos, i)
            corner_kd.balance()
        accel = SourceAccel(edge_accel, corner_kd)
        if segments:
            accel._build_run_topology(segments, corner_pts or [])
        return accel

    @classmethod
    def build_from_tool(cls, context: Context, tool, sources: list) -> 'SourceAccel | None':
        ''' Build from a tool's `source_edge_*` operator properties.
        Returns None when feature snapping is disabled or no feature type is selected.
        `sources` is the precomputed [(obj, M, Mi, Mi_3x3), ...] list built in the tool's __init__. '''
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

    @staticmethod
    def warmup(context, frames: int = 3):
        ''' Register a timer that warms up all source caches after `frames`.
        Triggers SourceCache rebuild and schedules SourceMeshCache background builds as needed.
        Safe to call from update callbacks and activate hooks. '''
        import bpy
        delay = frames / 60.0
        def _kick():
            try:
                ctx = bpy.context
                SourceMeshCache.request_warmup(ctx)
                if SourceCache.dirty and SourceCache.auto_rebuild_enabled(ctx):
                    SourceCache.request_rebuild(ctx)
            except Exception:
                pass
            return None
        bpy.app.timers.register(_kick, first_interval=delay)


DEBUG_SOURCE_CACHE = False  # flip on to trace every dirty/rebuild. mark_dirty fires per slider tick

EMPTY_ACCEL = SourceAccel(None, None)  # shared falsy accel served while a first build is pending


class SourceMeshData:
    ''' Flat numpy arrays for one evaluated source object, used by the Contours Walk method.
    All geometry is stored in world space so no per-stroke matrix math is needed. '''
    __slots__ = (
        'world', 'edge_verts',
        'loop_edge', 'loop_face', 'face_start', 'face_total',
        'sorted_faces', 'edge_face_offsets', 'edge_face_counts', 'boundary',
        'vert_sorted_faces', 'vert_face_offsets', 'vert_face_counts',
        'n_verts', 'n_edges', 'n_faces',
    )

    def __init__( self, world, edge_verts, loop_edge, loop_face, face_start, face_total, sorted_faces,
                 edge_face_offsets, edge_face_counts, boundary, vert_sorted_faces, vert_face_offsets, vert_face_counts):
        self.world             = world
        self.edge_verts        = edge_verts
        self.loop_edge         = loop_edge
        self.loop_face         = loop_face
        self.face_start        = face_start
        self.face_total        = face_total
        self.sorted_faces      = sorted_faces
        self.edge_face_offsets = edge_face_offsets
        self.edge_face_counts  = edge_face_counts
        self.boundary          = boundary
        self.vert_sorted_faces = vert_sorted_faces
        self.vert_face_offsets = vert_face_offsets
        self.vert_face_counts  = vert_face_counts
        self.n_verts           = len(world)
        self.n_edges           = len(edge_verts)
        self.n_faces           = len(face_start)


class SourceMeshCache:
    ''' Per-object flat-mesh cache for Contours Walk.
    Stores the evaluated mesh topology as numpy arrays so Walk can compute all plane
    intersections vectorially once per stroke and navigate adjacency via integer arrays.
    Key: (obj_name, mesh_name) → SourceMeshData
    Invalidated by depsgraph geometry update and clear() on RF unregister. '''
    _cache: 'dict[tuple[str,str], SourceMeshData]' = {}
    _warmup_queue: list = []  # bpy.types.Object refs pending background build

    @classmethod
    def get(cls, obj, depsgraph) -> 'SourceMeshData | None':
        mesh_name = getattr(obj.data, 'name', None)
        key       = (obj.name, mesh_name)
        cached    = cls._cache.get(key)
        if cached is not None:
            return cached
        data = cls._build(obj, depsgraph)
        if data is not None:
            cls._cache[key] = data
        return data

    @classmethod
    def _build(cls, obj, depsgraph) -> 'SourceMeshData | None':
        needs_eval = bool(obj.modifiers)
        if needs_eval:
            obj_eval = obj.evaluated_get(depsgraph)
            mesh = obj_eval.to_mesh()
            clear_mesh = obj_eval.to_mesh_clear
        else:
            mesh = obj.data
            clear_mesh = lambda: None
        try:
            n_v = len(mesh.vertices)
            n_e = len(mesh.edges)
            n_f = len(mesh.polygons)
            n_l = len(mesh.loops)
            if n_v == 0 or n_e == 0 or n_f == 0:
                return None

            # Vertex positions → world space
            co = np.empty(n_v * 3, dtype=np.float64)
            mesh.vertices.foreach_get('co', co)
            co = co.reshape(n_v, 3)
            M  = np.array(obj.matrix_world, dtype=np.float64)
            world = co @ M[:3, :3].T + M[:3, 3]

            # Edge → vertex indices
            ev = np.empty(n_e * 2, dtype=np.int32)
            mesh.edges.foreach_get('vertices', ev)
            edge_verts = ev.reshape(n_e, 2)

            # Face loop start + total
            face_start = np.empty(n_f, dtype=np.int32)
            face_total = np.empty(n_f, dtype=np.int32)
            mesh.polygons.foreach_get('loop_start', face_start)
            mesh.polygons.foreach_get('loop_total',  face_total)

            # Loop → edge + vert + face
            loop_edge = np.empty(n_l, dtype=np.int32)
            loop_vert = np.empty(n_l, dtype=np.int32)
            mesh.loops.foreach_get('edge_index',   loop_edge)
            mesh.loops.foreach_get('vertex_index', loop_vert)
            loop_face = np.repeat(np.arange(n_f, dtype=np.int32), face_total)

            # Edge → adjacent faces
            edge_face_counts = np.bincount(loop_edge, minlength=n_e).astype(np.int64)
            e_order          = np.argsort(loop_edge, kind='stable')
            sorted_faces     = loop_face[e_order]
            edge_face_offsets = np.zeros(n_e, dtype=np.int64)
            if n_e > 1:
                np.cumsum(edge_face_counts[:-1], out=edge_face_offsets[1:])
            boundary = (edge_face_counts == 1)

            # Vertex → adjacent faces (O(1) lookup per vert during BFS)
            vert_face_counts = np.bincount(loop_vert, minlength=n_v).astype(np.int64)
            v_order          = np.argsort(loop_vert, kind='stable')
            vert_sorted_faces = loop_face[v_order]
            vert_face_offsets = np.zeros(n_v, dtype=np.int64)
            if n_v > 1:
                np.cumsum(vert_face_counts[:-1], out=vert_face_offsets[1:])

            return SourceMeshData(
                world, edge_verts,
                loop_edge, loop_face, face_start, face_total,
                sorted_faces, edge_face_offsets, edge_face_counts, boundary,
                vert_sorted_faces, vert_face_offsets, vert_face_counts,
            )
        except Exception as e:
            print(f'SourceMeshCache: build failed for {obj.name!r}: {e}')
            return None
        finally:
            clear_mesh()

    @classmethod
    def evict(cls, obj_name: str):
        cls._cache = {k: v for k, v in cls._cache.items() if k[0] != obj_name}
        # Also remove from warmup queue in case it was pending.
        cls._warmup_queue = [o for o in cls._warmup_queue if getattr(o, 'name', None) != obj_name]

    @classmethod
    def cached_object_names(cls) -> list:
        ''' Sorted list of unique object names in the Walk flat-mesh cache. '''
        return sorted({k[0] for k in cls._cache})

    @classmethod
    def request_warmup(cls, context):
        ''' Schedule incremental background builds for all valid source objects not yet in the cache.
        Safe to call speculatively. Builds one object per timer tick so the UI stays responsive. '''
        try:
            sources = list(iter_all_valid_sources(context))
        except Exception:
            return
        pending = [
            obj for obj in sources
            if (obj.name, getattr(obj.data, 'name', None)) not in cls._cache
        ]
        if not pending:
            return
        existing = {getattr(o, 'name', None) for o in cls._warmup_queue}
        cls._warmup_queue.extend(o for o in pending if o.name not in existing)
        if not bpy.app.timers.is_registered(_source_mesh_cache_warmup_timer):
            bpy.app.timers.register(_source_mesh_cache_warmup_timer, first_interval=0.05)

    @classmethod
    def _warmup_step(cls) -> 'float | None':
        while cls._warmup_queue:
            obj = cls._warmup_queue.pop(0)
            try:
                name = obj.name   # raises ReferenceError if object was deleted
            except ReferenceError:
                continue
            mesh_name = getattr(obj.data, 'name', None)
            key = (name, mesh_name)
            if key in cls._cache:
                continue   # already built (e.g. by a synchronous get() during a stroke)
            try:
                depsgraph = bpy.context.evaluated_depsgraph_get()
                data = cls._build(obj, depsgraph)
                if data:
                    cls._cache[key] = data
                    print(f'SourceMeshCache: warmed {name!r}')
            except Exception as e:
                print(f'SourceMeshCache: warmup failed for {name!r}: {e}')
            # Yield back to Blender for at least one frame between sources.
            return 0.05 if cls._warmup_queue else None
        return None

    @classmethod
    def clear(cls):
        cls._cache.clear()
        cls._warmup_queue.clear()



def _source_mesh_cache_warmup_timer():
    ''' Timer entry point for SourceMeshCache background warmup. Stable identity so
    bpy.app.timers.is_registered() works correctly across calls. '''
    return SourceMeshCache._warmup_step()


def _source_cache_timer():
    ''' Module level timer entry point. Kept as a plain function so it can
    be reliably registered/unregistered with bpy.app.timers. '''
    return SourceCache._step()


class SourceCache:
    ''' The single, tool-agnostic cache of source feature-detection data. Survives tool switches and RF enter/exit.
    Rebuilds run incrementally on a timer so the UI stays interactive. The previous result is served until the new one is ready. '''
    accel : 'SourceAccel | None' = None       # last built feature data, empty SourceAccel when no features
    dirty : bool = True                       # a trigger fired or never built so rebuild on next get()
    source_datablock_names : frozenset = frozenset()  # object + mesh names tracked for source-edit detection

    # incremental build state
    building : bool = False
    progress : float = 0.0
    _gen = None                                # active build generator, or None
    _cancel : bool = False
    _dirty_token : int = 0                     # bumped on every mark_dirty
    _build_token : int = 0                     # _dirty_token captured when the in-flight build started
    _build_settings : tuple = ()
    _build_sources : list = []
    _pending_accel : 'SourceAccel | None' = None
    _pending_names : frozenset = frozenset()
    _tick_interval: float = 1.0 / 120.0        # small delay so heavy rebuilds spread over visible frames
    _committed_detection_settings : 'tuple | None' = None  # (angle, sharps, seams, creases) of last successful build
    # Per-object, per-type cache.  Key: (type_key, obj_name, mesh_name).  Value: (segments, corners).
    # Adding a new source only requires scanning that object; existing entries are reused unchanged.
    _obj_type_cache : dict = {}
    _pending_obj_data : dict = {}  # staged during in-flight build and committed to _obj_type_cache on success

    @staticmethod
    def auto_rebuild_enabled(context: Context) -> bool:
        try:
            return bool(context.scene.retopoflow.snapping.source_feature_auto_rebuild)
        except AttributeError:
            return True

    @staticmethod
    def detection_enabled(context: Context) -> bool:
        ''' True when any source feature-detection type is on in the scene snapping settings.
        Lets callers skip kicking a build that would detect nothing. '''
        try: s = context.scene.retopoflow.snapping
        except AttributeError: return False
        angle = s.source_edge_angle if s.source_edge_angle_enabled else math.pi
        return bool(s.source_edge_sharps or s.source_edge_seams or s.source_edge_creases or angle < math.pi)

    @classmethod
    def mark_dirty(cls, reason: str = ''):
        ''' Record that the cache is stale. get() decides whether to act on it and the manual rebuild op bypasses that gate. '''
        cls.dirty = True
        cls._dirty_token += 1
        if DEBUG_SOURCE_CACHE:
            print(f'SourceCache: marked dirty ({reason})')

    @classmethod
    def mark_dirty_geometry_changed(cls, reason: str = '', *, obj_name: str = ''):
        ''' Source geometry or the source object set changed.
        If `obj_name` is given, only that object's entries are evicted from the per-object cache and all other objects' cached data remains.
        If `obj_name` is empty, no cache is cleared. New objects have no entry and will be scanned.
        Removed objects stale entries are pruned when the next build commits. '''
        if obj_name:
            cls._obj_type_cache = {k: v for k, v in cls._obj_type_cache.items()
                                   if k[1] != obj_name and k[2] != obj_name}
        cls.mark_dirty(reason)

    @classmethod
    def _requires_rebuild_for_settings(cls, desired: tuple) -> bool:
        ''' True if desired setting needs data not present in the cache. '''
        if cls.accel is None or cls._committed_detection_settings is None:
            return True
        c_angle, c_sharps, c_seams, c_creases = cls._committed_detection_settings
        d_angle, d_sharps, d_seams, d_creases = desired
        if d_sharps  and not c_sharps:   return True   # newly enabled feature type
        if d_seams   and not c_seams:    return True
        if d_creases and not c_creases:  return True
        if d_angle < c_angle - 1e-6:     return True   # smaller threshold = more edges needed
        return False

    @classmethod
    def mark_dirty_if_settings_changed(cls, context: Context):
        ''' Alias kept for any remaining call-sites; delegates to mark_dirty_settings_changed. '''
        cls.mark_dirty_settings_changed(context)

    @classmethod
    def mark_dirty_settings_changed(cls, context: Context):
        ''' Called when a feature detection setting changes. Removes only the per-type cache entries that would need fresh data,
        then marks dirty if any rebuild is required. Disabling a type or tightening the threshold keeps the per-type cache
        (re-enabling stays instant) but still rebuilds the combined accel so tools stop snapping to the removed features. '''
        try:
            s       = context.scene.retopoflow.snapping
            angle   = s.source_edge_angle if s.source_edge_angle_enabled else math.pi
            desired = (angle, bool(s.source_edge_sharps), bool(s.source_edge_seams), bool(s.source_edge_creases))
        except Exception:
            cls.mark_dirty('detection settings changed (fallback)')
            return
        if cls._committed_detection_settings is None or cls.accel is None:
            cls.mark_dirty('no committed cache')
            if cls.auto_rebuild_enabled(context):
                cls.request_rebuild(context)
            return
        c_angle, c_sharps, c_seams, c_creases = cls._committed_detection_settings
        d_angle, d_sharps, d_seams, d_creases = desired
        needs_rebuild = False
        if d_sharps  and not c_sharps:
            cls._obj_type_cache = {k: v for k, v in cls._obj_type_cache.items() if k[0] != 'sharps'}
            needs_rebuild = True
        if d_seams   and not c_seams:
            cls._obj_type_cache = {k: v for k, v in cls._obj_type_cache.items() if k[0] != 'seams'}
            needs_rebuild = True
        if d_creases and not c_creases:
            cls._obj_type_cache = {k: v for k, v in cls._obj_type_cache.items() if k[0] != 'creases'}
            needs_rebuild = True
        if d_angle < c_angle - 1e-6:    # more permissive angle — need extra edges
            old_angle_key = ('angle', round(c_angle, 9))
            cls._obj_type_cache = {k: v for k, v in cls._obj_type_cache.items() if k[0] != old_angle_key}
            needs_rebuild = True
        removed_features = (
            (c_sharps  and not d_sharps)  or
            (c_seams   and not d_seams)   or
            (c_creases and not d_creases) or
            (d_angle > c_angle + 1e-6)
        )
        # With every type off, skip the rebuild and keep the committed accel intact to re-serve it instantly when possible
        if not (d_sharps or d_seams or d_creases or d_angle < math.pi):
            removed_features = False
        if needs_rebuild or removed_features:
            cls.mark_dirty('detection settings require new data' if needs_rebuild else 'detection settings removed features')
            if cls.auto_rebuild_enabled(context):
                cls.request_rebuild(context)
        elif DEBUG_SOURCE_CACHE:
            print('SourceCache: Settings changed but per-type cache covers all needs. No rebuild')

    @classmethod
    def get(cls, context: Context) -> 'SourceAccel':
        ''' Return the shared feature accel, kicking off a (non-blocking) rebuild if needed.
        Always returns a SourceAccel, the previous one while a rebuild is in flight, or an
        empty one until the first build finishes, so callers can decide whether feature snapping is active. '''
        if not cls.detection_enabled(context):
            # Every detection type is off, so feature snapping is inactive. The now stale cache must not be served.
            return EMPTY_ACCEL
        if not cls.building and (cls.accel is None or (cls.dirty and cls.auto_rebuild_enabled(context))):
            cls.request_rebuild(context)
        return cls.accel if cls.accel is not None else EMPTY_ACCEL

    @classmethod
    def request_rebuild(cls, context: Context, *, restart: bool = False, manual: bool = False):
        ''' Start an incremental rebuild on a timer. No-op if one is already running unless `restart=True`.
        Inputs are snapshotted here on the main thread and the timer steps over them across frames.
        `manual=True` marks the build as user-initiated so unused entries can be pruned. '''
        if cls.building and not restart: return
        snapping = context.scene.retopoflow.snapping
        angle = snapping.source_edge_angle if snapping.source_edge_angle_enabled else math.pi
        cls._build_settings = (
            angle,
            bool(snapping.source_edge_sharps),
            bool(snapping.source_edge_seams),
            bool(snapping.source_edge_creases),
            12 ** int(getattr(snapping, 'source_feature_batch_power', 3)),
        )
        cls._manual_rebuild = manual
        cls._build_sources = list(iter_all_valid_sources(context))
        cls._build_token = cls._dirty_token
        cls._cancel = False
        cls._gen = cls._build_steps()
        cls.building = True
        cls.progress = 0.0
        if not bpy.app.timers.is_registered(_source_cache_timer):
            bpy.app.timers.register(_source_cache_timer)

    @classmethod
    def _build_steps(cls):
        ''' Generator that builds feature data for each (type, object) pair not already in _obj_type_cache.
        Per-object cached results are reused directly. Adding a new source only scans that object.
        Touching existing sources' geometry only evicts those entries. '''
        angle, inc_sharps, inc_seams, inc_creases, batch_size = cls._build_settings
        sources = cls._build_sources
        names = frozenset(
            name
            for obj in sources
            for name in (obj.name, getattr(obj.data, 'name', None))
            if name
        )
        cls._pending_obj_data = {}
        if not (inc_sharps or inc_seams or inc_creases or angle < math.pi) or not sources:
            cls._pending_accel = SourceAccel(None, None)
            cls._pending_names = names
            yield 1.0
            return

        angle_key = ('angle', round(angle, 9)) if angle < math.pi else None
        active_types = []  # (type_key, do_sharps, do_seams, do_creases, type_angle)
        if inc_sharps:  active_types.append(('sharps',  True,  False, False, math.pi))
        if inc_seams:   active_types.append(('seams',   False, True,  False, math.pi))
        if inc_creases: active_types.append(('creases', False, False, True,  math.pi))
        if angle_key:   active_types.append((angle_key, False, False, False, angle))

        all_segments: list = []
        all_corners : list = []
        n  = len(sources)
        nt = max(1, len(active_types))
        for ti, (type_key, do_sharps, do_seams, do_creases, type_angle) in enumerate(active_types):
            type_cos = math.cos(type_angle) if type_angle < math.pi else -2.0
            for i, obj in enumerate(sources):
                mesh_name  = getattr(obj.data, 'name', None)
                cache_key  = (type_key, obj.name, mesh_name)
                cached     = cls._obj_type_cache.get(cache_key)
                if cached is not None:
                    all_segments.extend(cached[0])
                    all_corners.extend(cached[1])
                    if DEBUG_SOURCE_CACHE:
                        print(f'SourceCache: reusing {cache_key!r}')
                    yield (ti * n + i + 1.0) / (nt * n + 1)
                    continue
                # Not cached — scan this object for this feature type.
                obj_segs: list = []
                obj_crns: list = []
                depsgraph = bpy.context.evaluated_depsgraph_get()
                try:
                    M = obj.matrix_world
                    for obj_progress, segs, corners in SourceAccel.extract_object_features_incremental(
                        obj, depsgraph, M, type_cos, type_angle,
                        do_sharps, do_seams, do_creases,
                        edge_batch_size=batch_size,
                        vert_batch_size=batch_size,
                    ):
                        if segs is not None:
                            obj_segs.extend(segs)
                            obj_crns.extend(corners)
                        yield (ti * n + i + obj_progress) / (nt * n + 1)
                except Exception as e:
                    print(f'SourceCache: skipping source {getattr(obj, "name", "?")!r} ({e})')
                all_segments.extend(obj_segs)
                all_corners.extend(obj_crns)
                cls._pending_obj_data[cache_key] = (obj_segs, obj_crns)

        cls._pending_accel = SourceAccel.finalize(all_segments, all_corners)
        cls._pending_names = names
        yield 1.0

    @classmethod
    def _step(cls):
        ''' Advance one chunk, then yield to Blender. Returns the delay until the next tick, or None to stop and unregister the timer. '''
        if cls._gen is None or cls._cancel:
            cls._finish(commit=False)
            return None
        try:
            cls.progress = next(cls._gen)
        except StopIteration:
            cls._finish(commit=True)
            return None
        except Exception as e:
            print(f'SourceCache: build error ({e})')
            cls._finish(commit=False)
            return None
        cls._tag_redraw()
        return cls._tick_interval

    @classmethod
    def _finish(cls, *, commit: bool):
        cls._gen = None
        cls.building = False
        if commit and cls._pending_accel is not None:
            cls.accel = cls._pending_accel
            cls.source_datablock_names = cls._pending_names
            # Merge newly scanned per-object data into the persistent per-object cache.
            for key, (segs, crns) in cls._pending_obj_data.items():
                cls._obj_type_cache[key] = (segs, crns)
            # Prune cache entries for objects no longer in the source set.
            current_obj_names = {obj.name for obj in cls._build_sources}
            cls._obj_type_cache = {k: v for k, v in cls._obj_type_cache.items()
                                   if k[1] in current_obj_names}
            # On a manual rebuild, prune cache entries for feature types that are no longer enabled
            # Automatic rebuilds keep stale type entries so they remain available if the type is re-enabled
            if getattr(cls, '_manual_rebuild', False):
                _b_angle, _b_sharps, _b_seams, _b_creases = cls._build_settings[:4]
                active_type_keys = set()
                if _b_sharps:           active_type_keys.add('sharps')
                if _b_seams:            active_type_keys.add('seams')
                if _b_creases:          active_type_keys.add('creases')
                if _b_angle < math.pi:  active_type_keys.add(('angle', round(_b_angle, 9)))
                cls._obj_type_cache = {k: v for k, v in cls._obj_type_cache.items()
                                       if k[0] in active_type_keys}
            # Record what was actually built so future settings changes can be compared.
            cls._committed_detection_settings = cls._build_settings[:4]  # (angle, sharps, seams, creases)
            if cls._dirty_token == cls._build_token:
                cls.dirty = False
            cls.progress = 1.0
            print(f'SourceCache: build committed; features={"yes" if cls.accel else "no"}')
        else:
            cls.progress = 0.0
        cls._pending_accel = None
        cls._pending_names = frozenset()
        cls._pending_obj_data = {}
        cls._tag_redraw()

    @classmethod
    def cached_object_names(cls) -> list:
        return sorted({k[1] for k in cls._obj_type_cache})

    @classmethod
    def cached_types_for_object(cls, obj_name: str) -> list:
        ''' List of feature types cached for this object, used by the UI to show cache state. '''
        keys = {k[0] for k in cls._obj_type_cache if k[1] == obj_name}
        labels = []
        if 'sharps'  in keys: labels.append('Sharps')
        if 'seams'   in keys: labels.append('Seams')
        if 'creases' in keys: labels.append('Creases')
        if any(isinstance(k, tuple) for k in keys): labels.append('Angle')
        return labels

    @classmethod
    def evict_object(cls, obj_name: str):
        cls._obj_type_cache = {k: v for k, v in cls._obj_type_cache.items() if k[1] != obj_name}
        cls.mark_dirty(f'evicted {obj_name!r} from cache')

    @classmethod
    def cancel_rebuild(cls):
        if cls.building: cls._cancel = True

    @staticmethod
    def _tag_redraw():
        wm = bpy.context.window_manager
        if wm:
            for win in wm.windows:
                for area in win.screen.areas:
                    if area.type in {'VIEW_3D', 'PROPERTIES'}:
                        area.tag_redraw()
        rfcore = RFGlobals.RFCore_None
        if rfcore is not None:
            try: rfcore.refresh_statusbar()
            except Exception: pass

    @classmethod
    def note_depsgraph_update(cls, context: Context, depsgraph) -> None:
        ''' Auto-rebuild trigger for source geometry edits. Marks the cache dirty when a source object's geometry changed. '''
        if not cls.auto_rebuild_enabled(context): return
        if not cls.source_datablock_names: return
        for update in depsgraph.updates:
            if not getattr(update, 'is_updated_geometry', False): continue
            name = getattr(getattr(update, 'id', None), 'name', None)
            if name and name in cls.source_datablock_names:
                cls.mark_dirty_geometry_changed(f'source geometry edited ({name})', obj_name=name)
                SourceMeshCache.evict(name)
                return

    @classmethod
    def clear(cls):
        ''' Drop the cache and stop any in-flight build. '''
        cls._cancel = True
        cls._gen = None
        cls.building = False
        cls.progress = 0.0
        cls._committed_detection_settings = None
        cls._obj_type_cache.clear()
        cls._pending_obj_data.clear()
        if bpy.app.timers.is_registered(_source_cache_timer):
            try: bpy.app.timers.unregister(_source_cache_timer)
            except Exception: pass
        cls.accel = None
        cls.dirty = True
        cls.source_datablock_names = frozenset()
        cls._pending_accel = None
        cls._pending_names = frozenset()
        SourceMeshCache.clear()
