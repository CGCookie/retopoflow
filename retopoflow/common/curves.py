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

from __future__ import annotations

from collections.abc import Callable, Sequence

from mathutils import Vector
from bmesh.types import BMesh, BMFace, BMEdge, BMVert
from bpy.types import Context

from .bmesh import (
    bme_length,
    bme_midpoint,
    bmf_midpoint,
    bmfs_shared_bme,
    bmfs_share_bmv,
    quad_bmf_opposite_bme,
    get_boundary_strips_cycles,
    bme_unshared_bmv,
    bmes_shared_bmv,
    get_bmesh_emesh,
)
from .bmesh_maths import rdp_corner_indices, get_strip_bmvs, orient_bmf_normals
from .topology_corners import corner_reroute_is_legal, insert_corner, remove_corner
from .raycast import nearest_point_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bezier import CubicBezierSpline
from ...addon_common.common.utils import iter_pairs


# =============================================================================
# Centerline curve fitting.
# =============================================================================

AUTO_KNOT_MAX_SPAN_FACTOR = 0.6 # max fraction of the chain length between two knots before an auto-knot is allowed to be inserted
CORNER_MIN_SPACING_FACTOR = 0.01


def deflection_angle(cos, k, n, cyclic):
    ''' Angle between vert k's incoming and outgoing edges. Returns None
    for an open strip's own endpoint or a degenerate neighboring edge.'''
    if not cyclic and (k == 0 or k == n - 1):
        return None
    prev_k = (k - 1) % n if cyclic else k - 1
    next_k = (k + 1) % n if cyclic else k + 1
    v_in  = Vector(cos[k])      - Vector(cos[prev_k])
    v_out = Vector(cos[next_k]) - Vector(cos[k])
    if v_in.length < 1e-9 or v_out.length < 1e-9:
        return None
    return v_in.angle(v_out)


def sharp_angle_indices(cos, n, cyclic, sharp_angle):
    ''' Every vert whose own local deflection angle exceeds `sharp_angle`. '''
    return {
        k for k in range(n)
        if (angle := deflection_angle(cos, k, n, cyclic)) is not None and angle > sharp_angle
    }


def max_dev_index(cos, ka, kb, n):
    ''' Index in (ka, kb), an extended index range where kb may be >= n for a cyclic wrap,
    whose vert has max perpendicular distance from chord cos[ka]-cos[kb].
    This is the local extreme of that run. Returns None if there's no interior point. '''
    if kb - ka < 2:
        return None
    p0, p1 = Vector(cos[ka % n]), Vector(cos[kb % n])
    seg = p1 - p0
    seg_len2 = seg.length_squared
    best_k, best_d = None, -1.0
    for kk in range(ka + 1, kb):
        p = Vector(cos[kk % n])
        if seg_len2 < 1e-12:
            d = (p - p0).length
        else:
            t = max(0.0, min(1.0, (p - p0).dot(seg) / seg_len2))
            d = (p - (p0 + t * seg)).length
        if d > best_d:
            best_d, best_k = d, kk
    return best_k


def snap_to_local_extreme(cos, knots, n, locked, iterations=2):
    knots = sorted(set(knots))
    if len(knots) < 3:
        return knots
    for _ in range(iterations):
        m = len(knots)
        refined = list(knots)
        changed = False
        for idx in range(m):
            k = knots[idx]
            if k in locked: continue
            ka = knots[(idx - 1) % m]
            kb = knots[(idx + 1) % m]
            if idx == 0: ka -= n
            if idx == m - 1: kb += n
            best = max_dev_index(cos, ka, kb, n)
            if best is None: continue
            new_k = best % n
            if new_k != k: changed = True
            refined[idx] = new_k
        knots = sorted(set(refined))
        if not changed:
            break
    return knots


def split_long_span(cos, ka, kb, n, max_span, tol, result):
    arc_length = sum(
        (Vector(cos[k % n]) - Vector(cos[(k - 1) % n])).length
        for k in range(ka + 1, kb + 1)
    )
    if arc_length <= max_span:
        return
    # Place the extra knot at the run's local extreme, not its vert count midpoint
    best = max_dev_index(cos, ka, kb, n)
    if best is None:
        return
    # A long span only gets an auto-knot if it's sufficiently curved
    p0, p1 = Vector(cos[ka % n]), Vector(cos[kb % n])
    seg = p1 - p0
    seg_len2 = seg.length_squared
    p = Vector(cos[best % n])
    if seg_len2 < 1e-12:
        dev = (p - p0).length
    else:
        t = max(0.0, min(1.0, (p - p0).dot(seg) / seg_len2))
        dev = (p - (p0 + t * seg)).length
    if dev < tol:
        return
    result.add(best % n)
    split_long_span(cos, ka, best, n, max_span, tol, result)
    split_long_span(cos, best, kb, n, max_span, tol, result)


def insert_auto_knots(cos, knots, n, cyclic, stroke_length, tol):
    knots = sorted(set(knots))
    if not knots:
        return knots
    # A fraction of the chain's own total length, not a vert count
    max_span = max(stroke_length * AUTO_KNOT_MAX_SPAN_FACTOR, 1e-6)
    result = set(knots)
    pairs = list(zip(knots[:-1], knots[1:]))
    if cyclic:
        pairs.append((knots[-1], knots[0] + n))  # closing run wraps past the end
    for ka, kb in pairs:
        split_long_span(cos, ka, kb, n, max_span, tol, result)
    return sorted(result)


def derive_centerline_knots(coords, *, cyclic, bend_tolerance_factor, sharp_angle, forced_sharp_indices=frozenset(), corners_from_forced_only=False):
    ''' Derive knot indices for a polyline `coords`. `corners_from_forced_only`: For face strips. Only
    knots forced by topology become Vector corners regardless of curve angles. '''
    n = len(coords)
    # Thresholds below are fractions of the chain's total length
    # so the same shape yields the same knots regardless of vert count.
    stroke_length = sum(
        (Vector(coords[(i + 1) % n]) - Vector(coords[i])).length
        for i in range(n if cyclic else n - 1)
    )
    tol = max(stroke_length * bend_tolerance_factor, 1e-6)

    sharp_indices = sharp_angle_indices(coords, n, cyclic, sharp_angle) | (set(forced_sharp_indices) & set(range(n)))
    seed = ({0, n - 1} if not cyclic else set()) | sharp_indices
    corners = rdp_corner_indices(
        coords, tol,
        seed_indices=seed,
        min_spacing=stroke_length * CORNER_MIN_SPACING_FACTOR,
        force_endpoints=not cyclic,
    )

    # Snap each (non-endpoint, non-sharp) corner to the point of max RDP deviation
    # from the chord between its own immediate neighbors.
    locked = ({0, n - 1} if not cyclic else set()) | sharp_indices
    corners = snap_to_local_extreme(coords, corners, n, locked)

    # Which knots become Vector corners. Angle based for edge loops, topology based for face loops.
    forced = set(forced_sharp_indices) & set(range(n))
    corner_set = set(corners) & (forced if corners_from_forced_only else sharp_indices)

    knots = list(corners)
    if cyclic and len(knots) < 2:
        # ensure enough knots around a smooth loop to capture its shape
        step = max(1, n // 4)
        knots = sorted(set(knots) | set(range(0, n, step)))

    knots = insert_auto_knots(coords, knots, n, cyclic, stroke_length, tol)
    return knots, corner_set


def fit_centerline_spline(coords, *, cyclic, bend_tolerance_factor, sharp_angle, forced_sharp_indices=frozenset()):
    ''' Fit a CubicBezierSpline through the polyline `coords`, retaining its shape. '''
    n = len(coords)
    knots, corner_set = derive_centerline_knots(
        coords, cyclic=cyclic,
        bend_tolerance_factor=bend_tolerance_factor,
        sharp_angle=sharp_angle,
        forced_sharp_indices=forced_sharp_indices,
    )
    corners_for_fit = set(corner_set) | ({0, n - 1} if not cyclic else set())
    return CubicBezierSpline.create_catmull_rom(
        coords, knots, cyclic=cyclic, corner_indices=corners_for_fit,
    )


# =============================================================================
# Chain providers
# =============================================================================

class ChainSpec:
    ''' Provider-agnostic description of one curve chain. '''
    __slots__ = (
        'points', 'cyclic', 'cache_key', 'deform_bmv_indices', 'label',
        'min_spline_points', 'coupled', 'avg_len', 'current_points',
        'interior_bmv_indices', 'deform_bmv_rungs', 'forced_sharp_indices',
        'corner_eligible_knots', 'corner_removable_knots',
    )

    def __init__(
        self, *,
        points : list[Vector],
        cyclic : bool,
        cache_key : tuple,
        deform_bmv_indices : list[int],
        label : tuple[str, int],
        min_spline_points : int,
        coupled : bool,
        avg_len : float,
        current_points : Callable[[BMesh], list[Vector] | None],
        interior_bmv_indices : list[int] = (),
        deform_bmv_rungs : dict[int, tuple[Vector, float, bool]] | None = None,
        forced_sharp_indices : Sequence[int] = (),
        corner_eligible_knots : Sequence[int] = (),
        corner_removable_knots : Sequence[int] = (),
    ):
        self.points = points
        self.cyclic = cyclic
        self.cache_key = cache_key
        self.deform_bmv_indices = deform_bmv_indices
        self.label = label
        self.min_spline_points = min_spline_points
        self.coupled = coupled
        self.avg_len = avg_len
        self.current_points = current_points
        self.forced_sharp_indices = tuple(forced_sharp_indices)
        self.deform_bmv_rungs = deform_bmv_rungs or {} # Empty for a coupled chain
        self.interior_bmv_indices = list(interior_bmv_indices) # Empty when nothing's enclosed
        self.corner_eligible_knots = set(corner_eligible_knots)
        self.corner_removable_knots = set(corner_removable_knots)


class ChainProvider:
    ''' Strategy interface the shared curve overlay calls into to collect ChainSpecs from the current selection. '''

    def collect(self, context : Context, bm : BMesh) -> list[ChainSpec] | None:
        raise NotImplementedError # Each instance needs its own collect function


def enclosed_selected_faces(loop_bmes, sel_bmfs : set) -> set:
    # Flood-fill from the selected faces touching the loop's edges,
    # through other selected faces, without crossing the loop.
    # Per-loop so two multiple patches stay scoped to their own interior.
    loop_edge_set = set(loop_bmes)
    seeds = { f for bme in loop_bmes for f in bme.link_faces if f in sel_bmfs }
    visited = set(seeds)
    queue = list(seeds)
    while queue:
        f = queue.pop()
        for e in f.edges:
            if e in loop_edge_set:
                continue  # don't cross the boundary being edited
            for nf in e.link_faces:
                if nf in sel_bmfs and nf not in visited:
                    visited.add(nf)
                    queue.append(nf)
    return visited


def ordered_strip_bmvs(strip : Sequence[BMEdge], *, cyclic : bool) -> list[BMVert]:
    ''' Walk a chain of edges into its BMVerts in order. A cyclic chain's verts
    are returned once each (the wrap vert is not repeated at the end). '''
    if not strip:
        return []
    if len(strip) == 1:
        return list(strip[0].verts)
    if cyclic:
        start = bmes_shared_bmv(strip[-1], strip[0])
        if not start:
            return []
        bmvs = get_strip_bmvs(strip, start)
        if len(bmvs) > 1 and bmvs[0] == bmvs[-1]:
            bmvs = bmvs[:-1]  # drop duplicated wrap vert
        return bmvs
    start = bme_unshared_bmv(strip[0], strip[1])
    return get_strip_bmvs(strip, start)


class LoopStripChainProvider(ChainProvider):
    ''' Selected edges -> open strips and closed loops of BMVerts. '''

    def __init__(self, only_boundary : bool):
        self.only_boundary = only_boundary

    def _is_selection_boundary(self, bme, sel_bmfs : set) -> bool:
        # Selection boundary, not topology boundary
        linked = bme.link_faces
        if bme.is_wire or len(linked) < 2:
            return True
        return not (linked[0] in sel_bmfs and linked[1] in sel_bmfs)

    def collect(self, context : Context, bm : BMesh) -> list[ChainSpec] | None:
        sel_bmes = list(bmops.get_all_selected_bmedges(bm))
        sel_bmfs = set(bmops.get_all_selected_bmfaces(bm))
        if self.only_boundary or any(self._is_selection_boundary(bme, sel_bmfs) for bme in sel_bmes):
            sel_bmes = [bme for bme in sel_bmes if self._is_selection_boundary(bme, sel_bmfs)]

        if not sel_bmes or len(sel_bmes) >= 1000:
            return None

        strips, cycles = get_boundary_strips_cycles(sel_bmes)
        if len(strips) + len(cycles) > 5:
            return None

        avg_len = sum(bme_length(bme) for bme in sel_bmes) / len(sel_bmes)

        specs = []
        for strip in strips:
            spec = self._make_spec(ordered_strip_bmvs(strip, cyclic=False), cyclic=False, avg_len=avg_len)
            if spec: specs.append(spec)
        for cycle in cycles:
            spec = self._make_spec(
                ordered_strip_bmvs(cycle, cyclic=True), cyclic=True, avg_len=avg_len,
                loop_bmes=cycle, sel_bmfs=sel_bmfs,
            )
            if spec: specs.append(spec)
        return specs

    def _make_spec(self, bmvs, *, cyclic, avg_len, loop_bmes=None, sel_bmfs=None) -> ChainSpec | None:
        if not bmvs:
            return None
        cos = [bmv.co.copy() for bmv in bmvs]
        bmv_indices = [bmv.index for bmv in bmvs]
        label = ('Loop', len(bmvs)) if cyclic else ('Strip', len(bmvs) - 1)

        interior_bmv_indices = []
        if cyclic and loop_bmes and sel_bmfs:
            enclosed = enclosed_selected_faces(loop_bmes, sel_bmfs)
            interior_bmv_indices = sorted({v.index for f in enclosed for v in f.verts} - set(bmv_indices))

        def current_points(bm : BMesh, _indices : tuple = tuple(bmv_indices)) -> list[Vector] | None:
            return [bm.verts[i].co.copy() for i in _indices]

        return ChainSpec(
            points=cos,
            cyclic=cyclic,
            cache_key=('verts', *bmv_indices),
            deform_bmv_indices=bmv_indices,
            label=label,
            min_spline_points=5,
            coupled=True,
            avg_len=avg_len,
            current_points=current_points,
            interior_bmv_indices=interior_bmv_indices,
        )


def interleaved_centerline(faces : list[BMFace], *, cyclic : bool) -> list[Vector]:
    ''' Centerline as an alternating run of face midpoints and shared-edge midpoints.
    Faces must be edge-adjacent. A spatially-joined seam is bridged by quad_chain_centerline instead. '''
    n = len(faces)
    n_edges = n if cyclic else n - 1
    pts : list[Vector] = []
    for i in range(n):
        pts.append(bmf_midpoint(faces[i]))
        if i < n_edges and (bme := bmfs_shared_bme(faces[i], faces[(i + 1) % n])):
            pts.append(bme_midpoint(bme))
    return pts


def quad_chain_centerline(segment_faces : Sequence[list[BMFace]], *, cyclic : bool) -> list[Vector]:
    ''' Interleaved centerline over one or more sub-chains.
    A single sub-chain (or any ring) is one interleaved run. Multiple sub-chains are each interleaved,
    then bridged at their coincident outer-boundary midpoint - the true corner apex, which no face center sits on.
    '''

    def _corner_seam_point(end_mid : Vector | None, start_mid : Vector | None, fallback : Vector) -> Vector:
        # Averages the two sides' coincident-but-separate boundary midpoints so any residual snap discrepancy is split evenly
        candidates = [p for p in (end_mid, start_mid) if p is not None]
        if not candidates: return fallback # Neither side has a midpoint
        return sum(candidates, Vector((0, 0, 0))) / len(candidates)

    if cyclic:
        return interleaved_centerline(segment_faces[0], cyclic=True)
    pts : list[Vector] = []
    prev_faces = None
    for seg in segment_faces:
        seg_pts = interleaved_centerline(seg, cyclic=False)
        if prev_faces is not None:
            pts.append(_corner_seam_point(
                quad_outer_edge_midpoint(prev_faces, at_start=False),
                quad_outer_edge_midpoint(seg, at_start=True),
                (pts[-1] + seg_pts[0]) / 2,
            ))
        pts += seg_pts
        prev_faces = seg
    return pts


def ordered_rungs(faces : list[BMFace], cyclic : bool) -> list[BMEdge]:
    ''' The perpendicular edges crossing a quad strip, in order: the boundary
    cap at each open end, plus the edge shared by each consecutive face pair
    between. For N faces (N >= 2): N+1 rungs open, N rungs cyclic. '''
    rungs : list[BMEdge] = []
    n = len(faces)
    if cyclic:
        for i in range(n):
            if bme := bmfs_shared_bme(faces[i], faces[(i + 1) % n]):
                rungs.append(bme)
    else:
        if (shared_first := bmfs_shared_bme(faces[0], faces[1])) and (cap0 := quad_bmf_opposite_bme(faces[0], shared_first)):
            rungs.append(cap0)
        for i in range(n - 1):
            if bme := bmfs_shared_bme(faces[i], faces[i + 1]):
                rungs.append(bme)
        if (shared_last := bmfs_shared_bme(faces[-2], faces[-1])) and (capN := quad_bmf_opposite_bme(faces[-1], shared_last)):
            rungs.append(capN)
    return rungs


def quad_chain_rung_map(segment_faces : Sequence[list[BMFace]], *, cyclic : bool) -> dict[int, tuple[Vector, float, bool]]:
    ''' Returns {vert index: (rung midpoint, distance in rungs from the nearest open end, is that rung a mesh boundary edge)}.  '''
    rung_map : dict[int, tuple[Vector, float, bool]] = {}
    for seg in segment_faces:
        if len(seg) < 2:
            continue  # lone face, no neighbor to define a rung
        rungs = ordered_rungs(seg, cyclic)
        nr = len(rungs)
        for ri, bme in enumerate(rungs):
            mid = bme_midpoint(bme)
            # ring has no ends, large distance disables end-of-chain handling
            end_dist = float(nr) if cyclic else float(min(ri, nr - 1 - ri))
            is_boundary = len(bme.link_faces) <= 1  # only used at a chain end
            for v in bme.verts:
                # clean ladders don't share verts between rungs; if they do,
                # keep the nearer-to-end anchor so the taper stays conservative
                prev = rung_map.get(v.index)
                if prev is None or end_dist < prev[1]:
                    rung_map[v.index] = (mid, end_dist, is_boundary)
    return rung_map


def quad_outer_edge_midpoint(faces : list[BMFace], *, at_start : bool) -> Vector | None:
    ''' The strip end's outer boundary-edge midpoint, the true end location,
    unlike the end face's centroid which is offset ~ half a quad inward.
    Two strips meeting at a corner share this point but have very different centroids, so
    it's what corner-coincidence tests must compare. '''
    if len(faces) < 2:
        return None
    end_face, near_face = (faces[0], faces[1]) if at_start else (faces[-1], faces[-2])
    near_edge = bmfs_shared_bme(end_face, near_face)
    if not near_edge:
        return None
    far_edge = quad_bmf_opposite_bme(end_face, near_edge)
    return bme_midpoint(far_edge) if far_edge else None


# Endpoint coincidence threshold for joining two open chains at a corner.
# This can happen if PolyStrips fails to snap.
# Fractional because snap drift accumulates along a multi-bend stroke,
# so a strip's later corners need a looser epsilon than its first.
CORNER_MERGE_FRACTION = 0.1
CORNER_MERGE_MIN_EPSILON = 1e-5 # absolute floor, for the degenerate ~ zero-spacing chain


def chain_point_scale(points : list[Vector]) -> float:
    if len(points) < 2: return 0.0
    return sum((a - b).length for a, b in iter_pairs(points, False)) / (len(points) - 1)


def reversed_quad_chain(chain : dict) -> dict:
    seg_faces = [list(reversed(seg)) for seg in reversed(chain['segment_faces'])]
    return {
        'segment_faces': seg_faces,
        'points': quad_chain_centerline(seg_faces, cyclic=False),
        'start_edge_mid': chain['end_edge_mid'],
        'end_edge_mid': chain['start_edge_mid'],
    }


def join_quad_chains(a : dict, b : dict) -> dict:
    ''' Joins b after a (caller ensures a's end meets b's start), keeping them
    as separate sub-chains so the centerline bridges the seam at its true apex. '''
    seg_faces = a['segment_faces'] + b['segment_faces']
    return {
        'segment_faces': seg_faces,
        'points': quad_chain_centerline(seg_faces, cyclic=False),
        'start_edge_mid': a['start_edge_mid'],
        'end_edge_mid': b['end_edge_mid'],
    }


def try_join_quad_chains(a : dict, b : dict) -> dict | None:
    eps = max(
        CORNER_MERGE_FRACTION * min(chain_point_scale(a['points']), chain_point_scale(b['points'])),
        CORNER_MERGE_MIN_EPSILON,
    )
    ea, sa = a['end_edge_mid'], a['start_edge_mid']
    eb, sb = b['end_edge_mid'], b['start_edge_mid']
    if ea is not None and sb is not None and (ea - sb).length <= eps:
        return join_quad_chains(a, b)
    if ea is not None and eb is not None and (ea - eb).length <= eps:
        return join_quad_chains(a, reversed_quad_chain(b))
    if sa is not None and eb is not None and (sa - eb).length <= eps:
        return join_quad_chains(b, a)
    if sa is not None and sb is not None and (sa - sb).length <= eps:
        return join_quad_chains(reversed_quad_chain(b), a)
    return None


def quad_face_network(bmfs_set : set[BMFace]) -> dict[BMFace, set[BMFace]]:
    ''' Each of the selected quads mapped to the selected quads sharing one of its edges. '''
    return {
        bmf: {
            bme.link_faces[0] if bme.link_faces[1] == bmf else bme.link_faces[1]
            for bme in bmf.edges
            if len(bme.link_faces) == 2 and all(bmef in bmfs_set for bmef in bme.link_faces)
        }
        for bmf in bmfs_set
    }


def selection_has_patch(bmfs : Sequence[BMFace]) -> bool:
    ''' True when some connected run of the selected quads is more than one face wide. '''
    bmfs_set = set(bmfs)
    network = quad_face_network(bmfs_set)
    if any(len(neighbors) >= 3 for neighbors in network.values()):
        return True
    return any(
        len(bmv.link_faces) == 4 and all(f in bmfs_set and len(network[f]) == 2 for f in bmv.link_faces)
        for bmf in bmfs_set for bmv in bmf.verts
    )


def find_quadstrip_chains(bmfs : Sequence[BMFace]) -> tuple[list[dict], list[list[BMFace]]]:
    ''' Discover chains of edge-adjacent selected quads, open chains and closed rings. '''
    bmfs_set : set[BMFace] = set(bmfs)
    network = quad_face_network(bmfs_set)

    def walk_chain(start : BMFace) -> tuple[list[BMFace], set[int]]:
        # Prefer a straight continuation and turn through an L-attached corner when there's none.
        # Returns the face sequence and the positions of pivot faces turned through.
        pre, cur = None, start
        chain = [cur]
        visited = {cur}
        corners : set[int] = set()
        while True:
            unvisited = [bmf_next for bmf_next in network[cur] if bmf_next not in visited]
            # a straight run's next face never touches the face before last, so
            # excluding pre's vert-neighbors both prevents doubling back and disambiguates a branch
            straight = [bmf_next for bmf_next in unvisited if not pre or not bmfs_share_bmv(bmf_next, pre)]
            if straight:
                nxt = straight[0]
            elif pre and unvisited:
                nxt = unvisited[0]
                corners.add(len(chain) - 1)  # pivot = the face turned from
            else:
                return chain, corners
            pre, cur = cur, nxt
            chain.append(cur)
            visited.add(cur)

    def walk_ring(start : BMFace) -> tuple[list[BMFace], bool]:
        # A ring is a uniform degree-2 cycle, so exclude `pre` by identity, not by vertex-sharing.
        # walk_chain's vertex test would misfire on a small ring, where a legitimate forward face
        # two steps away can still share a vert with `pre`.
        # Returns (faces, looped-back-to-start?).
        pre, cur = None, start
        chain = [cur]
        while True:
            if len(network[cur]) != 2:
                return chain, False
            bmfs_next = [bmf_next for bmf_next in network[cur] if bmf_next is not pre]
            if not bmfs_next:
                return chain, False
            pre, cur = cur, bmfs_next[0]
            if cur == start:
                return chain, True
            chain.append(cur)

    chains : list[list[BMFace]] = []
    chain_corners : list[set[int]] = []
    touched : set[BMFace] = set()
    working = { bmf for bmf in bmfs_set if len(network[bmf]) == 1 }
    while working:
        cur = working.pop()
        if cur in touched:
            continue
        chain, corners = walk_chain(cur)
        touched |= set(chain)
        chains.append(chain)
        chain_corners.append(corners)

    rings : list[list[BMFace]] = []
    remaining = bmfs_set - touched
    while remaining:
        start = remaining.pop()
        if len(network[start]) != 2:
            continue  # not part of a uniform 2-neighbor cycle
        ring, closed = walk_ring(start)
        remaining -= set(ring)
        if closed and len(ring) >= 3:
            rings.append(ring)

    open_chains = [
        {
            'segment_faces': [chain],
            'points': quad_chain_centerline([chain], cyclic=False),
            'start_edge_mid': quad_outer_edge_midpoint(chain, at_start=True),
            'end_edge_mid': quad_outer_edge_midpoint(chain, at_start=False),
            'corner_face_positions': corners,
        }
        for chain, corners in zip(chains, chain_corners)
    ]

    # fallback for corners that aren't topologically attached: join any two
    # chains whose outer boundaries spatially coincide, until no pair does
    joined_something = True
    while joined_something:
        joined_something = False
        for i in range(len(open_chains)):
            for j in range(len(open_chains)):
                if i == j:
                    continue
                combined = try_join_quad_chains(open_chains[i], open_chains[j])
                if combined is None:
                    continue
                open_chains = [c for k, c in enumerate(open_chains) if k not in (i, j)] + [combined]
                joined_something = True
                break
            if joined_something:
                break

    return open_chains, rings


class QuadStripChainProvider(ChainProvider):
    ''' Selected quad faces -> quad chains and rings, represented by their centerlines. '''

    MAX_FACES = 1000  # cap total faces, not chain count (matches legacy PolyStrips)
    MIN_STRIP_FACES = 3  # two faces make one bend, which the two faces' own verts already describe

    def collect(self, context : Context, bm : BMesh) -> list[ChainSpec] | None:
        sel_bmfs = [bmf for bmf in bmops.get_all_selected_bmfaces(bm) if len(bmf.edges) == 4]
        if not sel_bmfs or len(sel_bmfs) > self.MAX_FACES:
            return None
        if selection_has_patch(sel_bmfs):
            return None

        open_chains, rings = find_quadstrip_chains(sel_bmfs)

        specs = []
        for open_chain in open_chains:
            spec = self._make_open_spec(open_chain)
            if spec: specs.append(spec)
        for ring in rings:
            spec = self._make_ring_spec(ring)
            if spec: specs.append(spec)
        return specs

    def _make_open_spec(self, open_chain : dict) -> ChainSpec | None:
        points = open_chain['points']
        if len(points) < 2:
            return None
        # face indices per sub-chain, multiple only in the spatial-join fallback
        segments = [[f.index for f in seg] for seg in open_chain['segment_faces']]
        bmf_indices = [i for seg in segments for i in seg]
        n = sum(len(seg) for seg in open_chain['segment_faces'])
        if n < self.MIN_STRIP_FACES:
            return None
        avg_len = max(sum((a - b).length for a, b in iter_pairs(points, False)) / max(len(points) - 1, 1), 1e-6)
        deform_bmv_indices = sorted({
            bmv.index for f in
            [f for seg in open_chain['segment_faces'] for f in seg]
            for bmv in f.verts
        })
        rung_map = quad_chain_rung_map(open_chain['segment_faces'], cyclic=False)
        label = ('Strip', n)

        # even = face centers, odd = edge midpoints.
        # Single-sub-chain only as the spatial-join fallback bridges its own apexes.
        single_subchain = len(open_chain['segment_faces']) == 1
        corner_positions = set(open_chain['corner_face_positions'])
        forced_sharp_indices = (
            [2 * k for k in corner_positions] if single_subchain else ()
        )

        # Corner toggle eligibility (2*face_pos knot indices), single sub-chain only.
        # A non-corner interior face whose reroute is legal can gain a corner and an existing corner whose
        # reroute is legal can lose one. Attached geometry makes the reroute illegal and not listed.
        corner_eligible_knots : set[int] = set()
        corner_removable_knots : set[int] = set()
        if single_subchain:
            seg = open_chain['segment_faces'][0]
            seg_rungs = ordered_rungs(seg, False)
            for face_pos in range(1, len(seg) - 1):
                if not corner_reroute_is_legal(seg, seg_rungs, face_pos, cyclic=False):
                    continue
                target = corner_removable_knots if face_pos in corner_positions else corner_eligible_knots
                # S knot at this pivot's face center (2*k) or at the bend rung feeding it (2*k - 1) can toggle the corner.
                # Both round back to face_pos in _reroute_corner.
                # Quad strips bend at rungs and auto knots on a smooth curve land on odd indices.
                target.add(2 * face_pos)
                target.add(2 * face_pos - 1)

        def current_points(bm : BMesh, _segments : tuple = tuple(map(tuple, segments))) -> list[Vector] | None:
            try:
                seg_faces = [[bm.faces[i] for i in seg] for seg in _segments]
            except IndexError:
                return None
            return quad_chain_centerline(seg_faces, cyclic=False)

        return ChainSpec(
            points=points,
            cyclic=False,
            cache_key=('faces', *bmf_indices),
            deform_bmv_indices=deform_bmv_indices,
            label=label,
            min_spline_points=2,
            coupled=False,
            avg_len=avg_len,
            current_points=current_points,
            forced_sharp_indices=forced_sharp_indices,
            corner_eligible_knots=corner_eligible_knots,
            corner_removable_knots=corner_removable_knots,
            deform_bmv_rungs=rung_map,
        )

    def _make_ring_spec(self, faces : list[BMFace]) -> ChainSpec | None:
        points = quad_chain_centerline([faces], cyclic=True)
        if len(points) < 2:
            return None
        avg_len = max(sum((a - b).length for a, b in iter_pairs(points, True)) / max(len(points), 1), 1e-6)
        bmf_indices = [bmf.index for bmf in faces]
        deform_bmv_indices = sorted({bmv.index for bmf in faces for bmv in bmf.verts})
        rung_map = quad_chain_rung_map([faces], cyclic=True)
        label = ('Loop', len(faces))

        def current_points(bm : BMesh, _indices : tuple = tuple(bmf_indices)) -> list[Vector] | None:
            try:
                faces = [bm.faces[i] for i in _indices]
            except IndexError:
                return None
            return quad_chain_centerline([faces], cyclic=True)

        return ChainSpec(
            points=points,
            cyclic=True,
            cache_key=('faces', *bmf_indices),
            deform_bmv_indices=deform_bmv_indices,
            label=label,
            min_spline_points=2,
            coupled=False,
            avg_len=avg_len,
            current_points=current_points,
            deform_bmv_rungs=rung_map,
        )


# =============================================================================
# Curve-handle editing
# =============================================================================

def relax_interior_verts(bm, interior, iterations):
    ''' Laplacian relaxation of a patch's interior verts as its boundary moves. '''
    indices = interior['indices']
    neighbors = interior['neighbors']
    orig_co = interior['orig_co']
    displacement = interior['displacement']
    boundary_orig_co = interior['boundary_orig_co']
    for _ in range(iterations):
        for idx in indices:
            nbrs = neighbors[idx]
            if not nbrs:
                continue
            total = Vector((0.0, 0.0, 0.0))
            weight_sum = 0.0
            for (n, w) in nbrs:
                d = displacement[n] if n in displacement else (bm.verts[n].co - boundary_orig_co[n])
                total = total + d * w
                weight_sum += w
            # Weighted by original edge length to reduce fold-over under large deformations
            displacement[idx] = total / weight_sum
            bm.verts[idx].co = orig_co[idx] + displacement[idx]


def segment_arc_length(cb):
    return sum(d for _, _, d in cb.get_tessellate_uniform())


def cumulative_lengths(cbs, segs):
    ''' Running total arc length at each boundary of `segs` (len(segs)+1 entries, starting at 0). '''
    cumul = [0.0]
    for seg in segs:
        cumul.append(cumul[-1] + segment_arc_length(cbs[seg]))
    return cumul


def walk_free_run(start, step, nseg, cyclic, free_at_seg_p0, visited):
    ''' Walks `visited` outward from `start` (step = -1/+1), one segment at a time,
    for as long as the knot crossed at each step is free. Returns the new segments
    in walk order; `visited` grows so the opposite walk can't cross back in. '''
    result = []
    cur = start
    while True:
        nxt = (cur + step) % nseg if cyclic else cur + step
        if not cyclic and not (0 <= nxt < nseg):
            break
        if nxt in visited:
            break
        # the boundary knot between cur and nxt is "at p0" of whichever one
        # comes later in forward (increasing-index) order
        if not free_at_seg_p0.get(nxt if step > 0 else cur, False):
            break
        result.append(nxt)
        visited.add(nxt)
        cur = nxt
    return result


def hovered_toggleable_knot(overlay):
    ''' The hovered (chain, handle) if it's a knot whose type can be toggled, else None. '''
    if not overlay or not overlay.hovering:
        return None
    chain_idx, handle_idx, _snapshot = overlay.hovering
    chain = overlay.chains[chain_idx]
    handle = chain['handles'][handle_idx]
    if handle['kind'] != 'knot' or not handle.get('can_toggle', False):
        return None
    return chain, handle


def reroute_corner(context, overlay, chain, handle):
    ''' Insert or remove a topological L-corner on a face strip. '''
    cache_key = chain['cache_key']
    # even knot (face center 2k) -> face k, keeping the knot marker in place
    # odd knot (bend rung 2k-1) -> face k, so the corner's pivot vertex lands on that bend rung.
    # Matches the eligibility indices in QuadStripChainProvider.
    ci = handle['vert_index']
    face_pos = (ci + (ci & 1)) // 2
    is_corner = handle.get('handle_type') == 'vector'

    bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
    try:
        faces = [bm.faces[i] for i in cache_key[1:]]
    except IndexError:
        return {'CANCELLED'}
    if not (1 <= face_pos <= len(faces) - 2):
        return {'CANCELLED'}
    rungs = ordered_rungs(faces, False)

    M = context.edit_object.matrix_world

    edit = remove_corner if is_corner else insert_corner
    result = edit(bm, faces, rungs, face_pos)
    if result is None:
        return {'CANCELLED'}  # attached to existing geometry / degenerate so leave unchanged

    # the squared corner verts were placed in-plane, pull them onto the source
    for bmv in result.get('moved_verts', ()):
        if snapped := nearest_point_valid_sources(context, M @ bmv.co, world=False, respect_clip_planes=True):
            bmv.co = snapped

    # only decide the normal after it is on the surface
    orient_bmf_normals(context, [result['new_face']] if result.get('new_face') is not None else [], new_faces=True)

    # reselect the whole resulting strip so the overlay re-detects the same chain
    new_faces = [f for f in faces if f.is_valid]
    if result.get('new_face') is not None:
        new_faces.append(result['new_face'])
    bmops.deselect_all(bm)
    bmops.select_iter(bm, new_faces)
    bmops.flush_selection(bm, em)  # also calls bmesh.update_edit_mesh

    # force the overlay to re-collect and rebuild and drop cache keyed by the now-stale face indices
    type(overlay).depsgraph_version = -42
    overlay._curve_struct_cache.pop(cache_key, None)
    overlay._handle_type_overrides.pop(cache_key, None)
    context.area.tag_redraw()
    return {'FINISHED'}


def toggle_hovered_handle(context, overlay):
    ''' Cycle the hovered knot's handle type. Returns FINISHED only when the mesh's
    topology changed (a face-strip corner was inserted or removed); every pure
    handle-type change returns CANCELLED, so the caller can key undo off the result. '''
    found = hovered_toggleable_knot(overlay)
    if found is None:
        return {'CANCELLED'}
    chain, handle = found
    cache_key, k = chain['cache_key'], handle['vert_index']
    current = handle.get('handle_type', 'automatic')

    if chain.get('coupled', True):
        # Edge loops: the pure handle-type cycle. No vert ever moves, so the toggle is perfectly reversible.
        overlay.toggle_handle_type(cache_key, k)
        context.area.tag_redraw()
        return {'CANCELLED'}

    if current == 'aligned':
        if handle.get('corner_eligible', False):
            return reroute_corner(context, overlay, chain, handle)  # -> vector (insert corner)
        new_type = 'automatic'  # no corner possible here: skip Vector in the cycle
    elif current == 'vector':
        if handle.get('corner_eligible', False):
            return reroute_corner(context, overlay, chain, handle)  # -> automatic (remove corner)
        return {'CANCELLED'}  # corner attached to existing geometry so leave unchanged
    else:  # automatic
        new_type = 'aligned'
    overlay.set_handle_type(cache_key, k, new_type, reposition=True)
    context.area.tag_redraw()
    return {'CANCELLED'}
