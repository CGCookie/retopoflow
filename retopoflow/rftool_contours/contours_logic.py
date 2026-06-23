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
import math
import bmesh
import time
import numpy as np
from itertools import chain
from collections import defaultdict
from collections.abc import Sequence, Iterator
from math import isclose
from typing import Literal
from bmesh.types import BMVert, BMEdge, BMFace, BMesh
from bpy.types import Context, Mesh
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Matrix, Vector
from ..common.bmesh import (
    get_bmesh_emesh, get_object_bmesh,
    has_mirror_x, has_mirror_y, has_mirror_z,
    bmf_midpoint_radius, bme_other_bmf, bmf_is_quad, quad_bmf_opposite_bme,
    ensure_correct_normals,
    find_selected_cycle_or_path,
)
from ..common.maths import (
    bvec_to_point, point_to_bvec3,
    pt_x0, pt_y0, pt_z0,
    lerp, get_closest_axis, snap_plane_to_direction,
    closest_point_linesegment, map_range
)
from ..common.accel import SourceMeshCache
from ..common.raycast import raycast_ray_valid_sources, nearest_point_valid_sources, nearest_normal_valid_sources, raycast_multiple_hits
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.debug import debugger
from ...addon_common.terminal import term_printer
from ...addon_common.common.maths import Point, Plane
from ...addon_common.common.utils import iter_pairs
from ...addon_common.ext.circle_fit import hyperLSQ


DEBUG_CREATE_OBJECTS = False
DEBUG_PRINT_TIMINGS = False
DEBUG_PRINT_SPACING = False
DEBUG_SKIP_BRIDGE_SNAP = False   # set True to see raw xform result (before ring-normal snap)
DEBUG_SKIP_REDISTRIBUTE = False  # set True to see raw Stage-2 snap result without any redistribution

# proportional_redistribute promotion / best-of-three reseat tuning (normalised RDP score units, 0..1):
MATCH_TOLERANCE         = 0.20  # a vert is "well-seated" when |slot score - reference score| is within this
SHIFT_MARGIN            = 0.10  # a neighbour slot must beat the current slot's match by this to reseat onto it
PROMOTE_DISTINCT_MARGIN = 0.10  # reference must differ from a neighbour's by this to count as a distinctive feature

# Per-vert curvature engagement: a feature begins sliding onto its cross-section slot once curvature_bias
# passes its activation (sharper features engage earlier) and is fully on it at curvature_bias = 1.  A
# reference RDP score of CORNER_FLOOR_FLAT engages from bias 0; CORNER_FLOOR_SHARP engages only by bias 1.
# (These are the old get_corner_threshold endpoints — now a smooth per-vert ramp instead of a moving floor.)
CORNER_FLOOR_SHARP = 0.10
CORNER_FLOOR_FLAT  = 0.75
# How quickly a feature, once engaged, finishes sliding onto its slot.  A feature reaches full snap at
# curvature_bias = activation + ENGAGE_FRACTION*(1 - activation): a sharp corner (activation 0) lands by
# ENGAGE_FRACTION (≈half the slider), softer features finish progressively later, the flattest only at 1.
ENGAGE_FRACTION = 0.5

# Minimum edge length for curvature placement = path_length / vertex_count / MIN_EDGE_LENGTH_DIVISOR.
# Caps how tightly curvature can cluster verts (even spacing would give path_length/vertex_count).
MIN_EDGE_LENGTH_DIVISOR = 3

# Weight of curvature-change (dκ/ds) signal relative to RDP in sample_curvature greedy selection.
# 0.0 = pure RDP; 1.0 = equal weight. Scales with curvature_bias so it has no effect at bias=0.
TRANSITION_WEIGHT = 0.15
# dκ/ds gate: suppress the dκ boost wherever any path point within TRANSITION_WINDOW indices has a
# turning angle (measured as sin) at or above TRANSITION_ANGLE_GATE.  This keeps dκ out of the
# pre-corner flanking region (which has large angles nearby even though the dκ peak itself is gentle)
# while still letting it fire at soft-bevel boundaries (small angles throughout the neighbourhood).
#   TRANSITION_ANGLE_GATE: sin(angle) threshold — sin(30°)≈0.50, sin(45°)≈0.71, sin(20°)≈0.34.
#     Raise if moderate corners still cluster; lower if soft bevels are missed.
#   TRANSITION_WINDOW: how many input-path indices to check each side of a candidate.
#     Raise if the dκ peak can be far from the corner in the raw path.
TRANSITION_ANGLE_GATE = 0.50   # sin(30°) — suppress dκ if any nearby point turns more than ~30°
TRANSITION_WINDOW     = 3      # check ±3 input-path indices around each candidate


###############################################################################
# Spacing-mode helper functions (module-level, used by Contours_Logic)
###############################################################################

def arc_fracs(points: list, cyclic: bool) -> list:
    """Return the fractional arc-length position [0..1] for each point.

    For cyclic paths the closing segment (points[-1] -> points[0]) is included
    in the total path length, so fracs[-1] < 1.0.
    """
    n = len(points)
    if n == 0:
        return []
    n_segs = n if cyclic else n - 1
    seg_lens = [(points[(i + 1) % n] - points[i]).length for i in range(n_segs)]
    total = sum(seg_lens)
    if total < 1e-10:
        return [0.0] * n
    cum = [0.0]
    for sl in seg_lens:
        cum.append(cum[-1] + sl / total)
    return cum[:n]


def fracs_to_positions(points: list, fracs: list, cyclic: bool) -> list:
    """Return 3D positions on the polyline at the given arc-length fractions."""
    n = len(points)
    if n == 0:
        return []
    n_segs = n if cyclic else n - 1
    seg_lens = [(points[(i + 1) % n] - points[i]).length for i in range(n_segs)]
    total = sum(seg_lens)
    if total < 1e-10:
        return [Vector(points[0]) for _ in fracs]
    cum_seg = [0.0]
    for sl in seg_lens:
        cum_seg.append(cum_seg[-1] + sl / total)
    result = []
    for frac in fracs:
        frac = max(0.0, min(1.0, frac))
        seg_idx = n_segs - 1
        for i in range(n_segs):
            if cum_seg[i + 1] >= frac - 1e-10:
                seg_idx = i
                break
        f0, f1 = cum_seg[seg_idx], cum_seg[seg_idx + 1]
        p0 = Vector(points[seg_idx % n])
        p1 = Vector(points[(seg_idx + 1) % n])
        if f1 - f0 < 1e-10:
            result.append(p0)
        else:
            result.append(p0.lerp(p1, max(0.0, min(1.0, (frac - f0) / (f1 - f0)))))
    return result


def project_co_to_frac(co, points: list, cyclic: bool, pt_fracs: list) -> float:
    """Project a local-space coordinate onto the polyline path.

    Returns its fractional arc-length position using the precomputed pt_fracs
    from _arc_fracs().
    """
    n = len(points)
    n_segs = n if cyclic else n - 1
    best_frac = 0.0
    best_dist2 = float('inf')
    co_v = Vector(co)
    for i in range(n_segs):
        p0 = Vector(points[i])
        p1 = Vector(points[(i + 1) % n])
        seg = p1 - p0
        seg_len2 = seg.length_squared
        if seg_len2 < 1e-20:
            continue
        t = max(0.0, min(1.0, (co_v - p0).dot(seg) / seg_len2))
        d2 = (co_v - p0.lerp(p1, t)).length_squared
        if d2 < best_dist2:
            best_dist2 = d2
            f1 = pt_fracs[i + 1] if i + 1 < n else 1.0
            best_frac = pt_fracs[i] + t * (f1 - pt_fracs[i])
    return best_frac


def axis_projected_frac(co, direction, plane_fit, points: list, cyclic: bool, pt_fracs: list) -> float:
    """Arc-frac on `points` of `co` projected along `direction` onto the cut plane.

    Projecting along the inter-loop axis (the offset between the two loops) rather than the cut-plane
    normal makes the connecting rung from `co`'s parent run parallel to that axis — vertical on a
    tilted cylindrical cut — instead of perpendicular to the tilted plane, which splays the rungs.
    Falls back to a normal projection if `direction` lies in the plane (degenerate).
    """
    c = Vector(co)
    n = Vector(plane_fit.n)
    d = Vector(direction)
    denom = d.dot(n)
    if abs(denom) < 1e-9:
        on_plane = c - plane_fit.signed_distance_to(c) * n
    else:
        on_plane = c - (plane_fit.signed_distance_to(c) / denom) * d
    return project_co_to_frac(on_plane, points, cyclic, pt_fracs)


def score_at_frac(frac: float, fracs: list, scores: list, cyclic: bool) -> float:
    """Linearly interpolate an RDP score at a given arc-length fraction.

    fracs and scores must be parallel and in arc-length order (as returned by
    sample_curvature via out_scores / project_co_to_frac on target_pts).
    """
    n = len(fracs)
    if n == 0:
        return 0.0
    if n == 1:
        return scores[0]
    if cyclic:
        for i in range(n):
            f0 = fracs[i]
            f1 = fracs[(i + 1) % n]
            gap = (f1 - f0) % 1.0
            if gap < 1e-10:
                continue
            d = (frac - f0) % 1.0
            if d <= gap:
                t = d / gap
                return scores[i] + t * (scores[(i + 1) % n] - scores[i])
    else:
        if frac <= fracs[0]:  return scores[0]
        if frac >= fracs[-1]: return scores[-1]
        for i in range(n - 1):
            if fracs[i] <= frac <= fracs[i + 1]:
                gap = fracs[i + 1] - fracs[i]
                t = (frac - fracs[i]) / gap if gap > 1e-10 else 0.0
                return scores[i] + t * (scores[i + 1] - scores[i])
    return scores[-1]


def lerp_frac(a: float, b: float, t: float, cyclic: bool) -> float:
    """Interpolate between two arc-length fractions, taking the shorter way for cyclic paths."""
    if cyclic:
        d = b - a
        if d >  0.5: d -= 1.0
        elif d < -0.5: d += 1.0
        return (a + t * d) % 1.0
    return a + t * (b - a)


def rdp_point_scores(points: list, cyclic: bool) -> list:
    """Normalised [0,1] RDP corner score for every point (1 = sharp corner, 0 = flat).

    This is the same Ramer-Douglas-Peucker perpendicular-deviation metric sample_curvature uses
    to place verts, but evaluated for every input point (not a selected subset) — so a reference
    loop's corner scores are directly comparable to the new cross-section's rdp_scores.  Used to
    measure a bridge reference vert's corner-ness from the parent loop's own geometry, which is
    robust where projecting the off-plane parent onto the new cross-section is not.
    """
    n = len(points)
    if n < 3:
        return [0.0] * n
    scores = [0.0] * n

    def rdp_score(i0: int, i1: int) -> None:
        stack = [(i0, i1)]
        while stack:
            a, b = stack.pop()
            if b - a <= 1:
                continue
            p0 = Vector(points[a % n])
            p1 = Vector(points[b % n])
            seg = p1 - p0
            seg_len2 = seg.length_squared
            max_dist, max_k = -1.0, a + 1
            for k in range(a + 1, b):
                p = Vector(points[k % n])
                if seg_len2 < 1e-20:
                    d = (p - p0).length
                else:
                    t = max(0.0, min(1.0, (p - p0).dot(seg) / seg_len2))
                    d = (p - p0.lerp(p1, t)).length
                if d > max_dist:
                    max_dist, max_k = d, k
            if max_dist > 0:
                scores[max_k % n] = max_dist
            stack.append((a, max_k))
            stack.append((max_k, b))

    if cyclic:
        centroid = Vector((0.0, 0.0, 0.0))
        for p in points:
            centroid += Vector(p)
        centroid /= n
        i0 = max(range(n), key=lambda i: (Vector(points[i]) - centroid).length_squared)
        i1 = max(range(n), key=lambda i: (Vector(points[i]) - Vector(points[i0])).length_squared)
        if i1 < i0:
            i0, i1 = i1, i0
        scores[i0] = float('inf')
        scores[i1] = float('inf')
        rdp_score(i0, i1)
        rdp_score(i1, i0 + n)
    else:
        scores[0] = float('inf')
        scores[n - 1] = float('inf')
        rdp_score(0, n - 1)

    max_finite = max((s for s in scores if s < float('inf')), default=1.0)
    if max_finite < 1e-12:
        max_finite = 1.0
    return [min((max_finite if s >= float('inf') else s) / max_finite, 1.0) for s in scores]


def curvature_change_scores(points: list, cyclic: bool, pt_fracs: list) -> tuple:
    """Rate-of-curvature-change scores and per-point turning angles for every point.

    Returns (sin_angles, dk_norm) where:
      sin_angles[i] — sin of the turning angle at point i (cross-product magnitude of the two
                      unit edge vectors meeting at i).  0 = perfectly flat, 1 = 90° corner.
                      Used as the angle gate in sample_curvature to suppress dκ near sharp corners.
      dk_norm[i]    — normalised [0,1] dκ/ds score.  Peaks at flat→bevel transition boundaries
                      even when per-point RDP scores are low.
    """
    n = len(points)
    if n < 3:
        return [0.0] * n, [0.0] * n

    sin_angles = [0.0] * n
    kappa      = [0.0] * n
    for i in range(n):
        if not cyclic and (i == 0 or i == n - 1):
            continue
        im1, ip1 = (i - 1) % n, (i + 1) % n
        t1 = Vector(points[i]) - Vector(points[im1])
        t2 = Vector(points[ip1]) - Vector(points[i])
        l1, l2 = t1.length, t2.length
        if l1 < 1e-10 or l2 < 1e-10:
            continue
        cross_mag      = t1.cross(t2).length / (l1 * l2)   # = sin(turning angle)
        sin_angles[i]  = cross_mag
        mean_len       = (l1 + l2) * 0.5
        kappa[i]       = cross_mag / mean_len if mean_len > 1e-10 else 0.0

    dk = [0.0] * n
    for i in range(n):
        if not cyclic and (i == 0 or i == n - 1):
            continue
        im1, ip1 = (i - 1) % n, (i + 1) % n
        ds    = (pt_fracs[ip1] - pt_fracs[im1]) % 1.0 if cyclic else (pt_fracs[ip1] - pt_fracs[im1])
        dk[i] = abs(kappa[ip1] - kappa[im1]) / ds if ds > 1e-10 else 0.0

    max_dk = max(dk, default=0.0)
    if max_dk < 1e-12:
        return sin_angles, [0.0] * n
    return sin_angles, [d / max_dk for d in dk]


def loop_scores_by_vert(vert_set: set, cyclic: bool) -> dict:
    """Map every vert in vert_set to its RDP corner score, scoring each connected loop on its own
    geometry.  vert_set may hold more than one disjoint loop (e.g. the two reference loops on either
    side of a loop cut) — each connected component is ordered and scored independently.
    """
    result = {}
    remaining = set(vert_set)
    while remaining:
        comp = ordered_ring_verts(remaining, cyclic)
        if not comp:
            break
        for v, s in zip(comp, rdp_point_scores([Vector(v.co) for v in comp], cyclic)):
            result[v] = s
        remaining.difference_update(comp)
    return result


def topological_reference_data(verts: list, nbmvs_set: set, cyclic: bool) -> dict:
    """Return {new_vert: (ref_point, ref_score)} for each new vert, references found purely by
    topology — the vert(s) on the neighbouring loop(s) directly connected to it by a single edge
    (any connected vert that is not itself a new vert).  No projection, plane-distance
    interpolation, or other positional calculation is used to find the reference.

    A bridge/extrusion vert has exactly one such reference; a loop-cut vert has two (one per side).
    Where there are two, their positions are averaged and the stronger corner score is taken.
    Corner-ness (ref_score) is measured from each reference loop's own geometry, never the new
    cross-section, so it is meaningful even for an off-plane bridge parent.  Keyed by vert so the
    result can be read in any vert order (ordered ring for the rotation search, the chosen
    assignment for the promotion).
    """
    all_refs = {
        ov for v in verts for bme in v.link_edges
        if (ov := bme.other_vert(v)) not in nbmvs_set
    }
    score_by_vert = loop_scores_by_vert(all_refs, cyclic)
    data = {}
    for v in verts:
        refs = [bme.other_vert(v) for bme in v.link_edges if bme.other_vert(v) not in nbmvs_set]
        if refs:
            data[v] = (
                sum((Vector(r.co) for r in refs), Vector()) / len(refs),
                max(score_by_vert.get(r, 0.0) for r in refs),
            )
        else:
            data[v] = (Vector(v.co), 0.0)
    return data


def corner_indices(scores: list, cyclic: bool, floor: float) -> list:
    """Indices that are corners: a local maximum of `scores` (a peak, >= both neighbours) that is
    also at or above `floor`.  Using peaks rather than a bare threshold makes detection robust to
    how the scores happen to be normalised — a chamfer's moderate-but-peaked score is caught, while
    the gently-varying scores along a smooth arc are not (they are not local maxima above the floor).
    """
    n = len(scores)
    out = []
    for i in range(n):
        if scores[i] < floor:
            continue
        left  = scores[(i - 1) % n] if (cyclic or i > 0)     else -1.0
        right = scores[(i + 1) % n] if (cyclic or i < n - 1) else -1.0
        if scores[i] >= left and scores[i] >= right:
            out.append(i)
    return out


def assign_corner_pins(N: int, cyclic: bool, slot_scores: list, ref_scores: list,
                       corner_threshold: float, window: int = 2) -> list:
    """Promotion step: assign each corner vert to the cross-section corner it should hold.

    A "corner vert" is one whose reference vert is a corner (a peak in ref_scores above the floor);
    a "corner slot" is a corner position on the new cross-section (a peak in slot_scores).  Corner
    verts are matched to corner slots with an order-preserving, minimum-displacement matching
    (within `window` slots).  Because the matching keeps ring order, a run of corner verts shifts
    *together* to align with a run of corner slots:

        e.g. a chamfer — verts A,B whose references are the two chamfer edges get pulled onto the
        two cross-section chamfer-edge slots (A->left, B->right) instead of one vert sitting on
        the wrong edge.  A flat-reference vert pushed off a corner is simply left free.

    Returns pin_slot[i] = the slot vert i is pinned to (its original slot i for an in-place
    promotion, a neighbour slot for a shift), or None if vert i is free.
    """
    pin = [None] * N
    corner_verts = corner_indices(ref_scores, cyclic, corner_threshold)
    corner_slots = corner_indices(slot_scores, cyclic, corner_threshold)
    if not corner_verts or not corner_slots:
        return pin
    is_corner = set(corner_verts) | set(corner_slots)

    # Linearise: for cyclic loops start the sweep at a flat gap — an index that is neither a corner
    # vert nor a corner slot — so neither a corner-vert run nor a corner-slot run is split across the
    # wrap seam (splitting a slot run would invert the matching).  pos() gives the sweep position.
    if cyclic:
        start = next(
            (k for k in range(N) if k not in is_corner),
            next((k for k in range(N) if k not in set(corner_verts)), 0),
        )
    else:
        start = 0
    def pos(idx): return (idx - start) % N if cyclic else idx
    V = sorted(corner_verts, key=pos)
    S = sorted(corner_slots, key=pos)
    posV = [pos(v) for v in V]
    posS = [pos(s) for s in S]
    m, p = len(V), len(S)

    # Order-preserving min-cost matching (sequence alignment).  Matching costs slot displacement;
    # leaving a corner vert or slot unmatched costs SKIP, set just above `window` so any in-window
    # pairing is preferred over dropping it.
    SKIP = window + 1
    dp = [[0.0] * (p + 1) for _ in range(m + 1)]
    ch = [[-1]  * (p + 1) for _ in range(m + 1)]
    for a in range(m, -1, -1):
        for b in range(p, -1, -1):
            if a == m and b == p:
                continue
            best, c = float('inf'), -1
            if a < m and dp[a + 1][b] + SKIP < best:
                best, c = dp[a + 1][b] + SKIP, 0      # skip corner vert V[a]
            if b < p and dp[a][b + 1] + SKIP < best:
                best, c = dp[a][b + 1] + SKIP, 1      # skip corner slot S[b]
            if a < m and b < p:
                d = abs(posV[a] - posS[b])
                if d <= window and dp[a + 1][b + 1] + d < best:
                    best, c = dp[a + 1][b + 1] + d, 2  # match V[a] -> S[b]
            dp[a][b], ch[a][b] = best, c

    a, b = 0, 0
    while a < m and b < p:
        c = ch[a][b]
        if c == 2:
            pin[V[a]] = S[b]; a += 1; b += 1
        elif c == 0:
            a += 1
        else:
            b += 1
    return pin


def relax_between_pins(N: int, cyclic: bool, base_fracs: list, pin_frac: list, ref_gaps: list) -> list:
    """Distribute free verts so their arc-frac gaps are proportional to reference edge lengths.

    pin_frac[i] is the pinned arc-frac of vert i (or None if it is free).  Each run of free verts
    between two consecutive pinned verts is laid out so the cumulative arc-frac distance from the
    left pin matches the cumulative reference edge length (ref_gaps[i] = reference length from
    vert i to vert i+1) — i.e. each free vert's left/right edge ratio matches its reference vert's.

    base_fracs (curvature placement) anchors strip endpoints and the pin-less fallback.  Order is
    preserved (free verts stay strictly between their enclosing pins), so it can't wind inside-out.
    """
    result = [pin_frac[i] if pin_frac[i] is not None else base_fracs[i] for i in range(N)]
    pins = [i for i in range(N) if pin_frac[i] is not None]

    if cyclic:
        if not pins:
            # No corner pins: lay every vert out by reference proportions around the full loop,
            # anchored at vert 0's curvature frac so the base rotation is preserved.
            total = sum(ref_gaps)
            if total < 1e-12:
                return result
            fa, run = base_fracs[0], 0.0
            result[0] = fa
            for i in range(1, N):
                run += ref_gaps[i - 1]
                result[i] = (fa + run / total) % 1.0
            return result
        P = len(pins)
        for s in range(P):
            a = pins[s]
            b = pins[(s + 1) % P]
            fa = pin_frac[a]
            span = (pin_frac[b] - fa) % 1.0 if P > 1 else 1.0
            # Walk a -> b collecting the reference gaps crossed and the free verts between.
            free, steps, k = [], [], a
            while True:
                steps.append(ref_gaps[k])       # gap from vert k to k+1
                k = (k + 1) % N
                if k == b:
                    break
                free.append(k)
            if not free:
                continue
            total = sum(steps)
            if total < 1e-12:
                mm = len(free)
                for idx, fk in enumerate(free):
                    result[fk] = (fa + span * (idx + 1) / (mm + 1)) % 1.0
            else:
                run = 0.0
                for idx, fk in enumerate(free):
                    run += steps[idx]           # cumulative reference length from pin a to vert fk
                    result[fk] = (fa + span * (run / total)) % 1.0
    else:
        anchors = sorted(set([0, N - 1] + pins))   # strip endpoints are always anchors
        for s in range(len(anchors) - 1):
            a, b = anchors[s], anchors[s + 1]
            fa, fb = result[a], result[b]
            span = fb - fa
            free = list(range(a + 1, b))
            if not free:
                continue
            steps = [ref_gaps[j] for j in range(a, b)]
            total = sum(steps)
            if total < 1e-12:
                mm = len(free)
                for idx, fk in enumerate(free):
                    result[fk] = fa + span * (idx + 1) / (mm + 1)
            else:
                run = 0.0
                for idx, fk in enumerate(free):
                    run += steps[idx]
                    result[fk] = fa + span * (run / total)
    return result


def proportional_redistribute(
    cyclic: bool, target_fracs: list, rdp_scores: list,
    ref_points: list, ref_scores: list, interpolation_factor: float, curvature_bias: float,
    parent_fracs: list = None, vert_indices: list = None,
) -> list:
    """Place each vert by easing it from a spacing position onto its curvature feature.

    target_fracs[i] / rdp_scores[i] describe slot i on the new cross-section.  ref_points[i] /
    ref_scores[i] are the position and corner-ness of the vert-that-owns-slot-i's reference (its
    topological neighbour(s) on the parent loop).  Corner identification and the rotation upstream use
    the FULL rdp_scores, so the assignment is curvature-independent (stable, no threshold to cross).

    Two knobs, applied as continuous slides (no on/off thresholds, so dragging either slider never
    snaps):
      * interpolation_factor — the *spacing* of free verts, from even arc-length (0) to parent-matched
        (1).  This is the baseline position every vert starts from.
      * curvature_bias — how far each *feature* vert eases off that baseline and onto its cross-section
        feature slot.  Each feature has an activation set by its reference sharpness (CORNER_FLOOR_FLAT
        engages from bias 0, CORNER_FLOOR_SHARP only by bias 1) and slides from 0 at its activation to
        fully seated at bias 1 — so sharper features engage earlier, all without a moving floor.

    A vert whose reference is flat or matches its neighbours' equally well (not *distinctive*) is never
    a feature and just rides the spacing baseline.  Returns final arc-fracs in slot order.
    """
    N = len(target_fracs)
    if N == 0:
        return []
    ref_gaps = [(Vector(ref_points[(i + 1) % N]) - Vector(ref_points[i])).length for i in range(N)]
    parent_gaps = None
    if parent_fracs:
        if cyclic:
            parent_gaps = [(parent_fracs[(i + 1) % N] - parent_fracs[i]) % 1.0 for i in range(N)]
        else:
            parent_gaps = [parent_fracs[i + 1] - parent_fracs[i] for i in range(N - 1)] + [0.0]

    def neighbours(i):
        if cyclic:
            return [(i - 1) % N, (i + 1) % N]
        return [j for j in (i - 1, i + 1) if 0 <= j < N]
    def match_cost(i, s):
        return abs(rdp_scores[s] - ref_scores[i])

    # --- Identify each feature vert's slot (curvature-independent: full scores, fixed low floor) ---
    # A vert is "well-seated" when its slot's corner-ness already matches its reference's.
    good = [match_cost(i, i) <= MATCH_TOLERANCE for i in range(N)]
    # Distinctive: the reference's corner-ness stands out from a neighbour's.  Flat / evenly-curved runs
    # have near-equal reference scores -> not distinctive -> never features -> ride the spacing baseline.
    distinctive = [
        any(abs(ref_scores[i] - ref_scores[j]) >= PROMOTE_DISTINCT_MARGIN for j in neighbours(i))
        for i in range(N)
    ]
    floor = CORNER_FLOOR_SHARP   # identify every potential feature; the per-vert slide gates engagement
    desired = [None] * N
    for i in range(N):
        if ref_scores[i] < floor or not distinctive[i]:
            continue
        nbrs = neighbours(i)
        best = min([i] + nbrs, key=lambda s: match_cost(i, s))
        if best != i and rdp_scores[best] >= floor and match_cost(i, best) + SHIFT_MARGIN < match_cost(i, i):
            desired[i] = best                          # reseat onto the better-matching neighbour slot
        elif good[i] and all(good[j] for j in nbrs):
            desired[i] = i                             # hold its own slot (well-seated, neighbours agree)

    # Resolve collisions: a slot is held by at most one vert (the best match); the rest go free.
    slot_owner = {}
    for i in range(N):
        s = desired[i]
        if s is None:
            continue
        owner = slot_owner.get(s)
        if owner is None or match_cost(i, s) < match_cost(owner, s):
            slot_owner[s] = i
    pin_slot = [None] * N
    for s, i in slot_owner.items():
        pin_slot[i] = s
    # Uncross any mutual adjacent swap (see relax notes): reseats move at most one slot.
    for a in range(N if cyclic else N - 1):
        b = (a + 1) % N
        if pin_slot[a] == b and pin_slot[b] == a:
            pin_slot[a], pin_slot[b] = a, b

    # --- Spacing baseline: where every vert sits with NO feature pinning (even <-> parent by interp) ---
    w = max(0.0, min(1.0, interpolation_factor))
    even_free = relax_between_pins(N, cyclic, target_fracs, [None] * N, [1.0] * N)
    parent_free = relax_between_pins(N, cyclic, parent_fracs if parent_fracs else target_fracs,
                                     [None] * N, parent_gaps if parent_fracs else ref_gaps)
    spacing_pos = [lerp_frac(even_free[i], parent_free[i], w, cyclic) for i in range(N)]

    # --- Per-vert curvature slide: each feature eases from its spacing position onto its slot ---
    cb = max(0.0, min(1.0, curvature_bias))
    span = CORNER_FLOOR_FLAT - CORNER_FLOOR_SHARP
    pin_frac = [None] * N
    engage = {}
    for i in range(N):
        if pin_slot[i] is None:
            continue
        activation = max(0.0, min(1.0, (CORNER_FLOOR_FLAT - ref_scores[i]) / span)) if span > 1e-9 else 0.0
        # Reach full snap partway between activation and 1, so sharp features land by mid-slider.
        denom = ENGAGE_FRACTION * (1.0 - activation)
        blend = max(0.0, min(1.0, (cb - activation) / denom)) if denom > 1e-9 else (1.0 if cb >= activation else 0.0)
        pin_frac[i] = lerp_frac(spacing_pos[i], target_fracs[pin_slot[i]], blend, cyclic)
        engage[i] = round(blend, 2)

    # Clamp blended pins to forward-monotonic ring order — a per-vert slide can momentarily reorder two
    # close features; this keeps them ordered so free verts relax cleanly between with no crossing.
    pinned = [i for i in range(N) if pin_frac[i] is not None]
    P = len(pinned)
    if P >= 2:
        if cyclic:
            gaps = [(pin_frac[pinned[(k + 1) % P]] - pin_frac[pinned[k]]) % 1.0 for k in range(P)]
            seam = max(range(P), key=lambda k: gaps[k])     # start after the widest gap (the slack seam)
            order = [pinned[(seam + 1 + k) % P] for k in range(P)]
        else:
            order = pinned
        for k in range(1, len(order)):
            prev, cur = pin_frac[order[k - 1]], pin_frac[order[k]]
            backward = ((cur - prev) % 1.0 > 0.5) if cyclic else (cur < prev)
            if backward:
                pin_frac[order[k]] = prev

    if DEBUG_PRINT_SPACING:
        feature_slots = {i: pin_slot[i] for i in range(N) if pin_slot[i] is not None}
        print(f'[Contours spacing] N={N} cyclic={cyclic} interp={w:.2f} curvature={cb:.2f}')
        print(f'  slot index         = {list(range(N))}')
        if vert_indices is not None:
            print(f'  slot -> vert index = {vert_indices}')
        print(f'  rdp_scores (slots) = {[round(s, 2) for s in rdp_scores]}')
        print(f'  ref_scores (refs)  = {[round(s, 2) for s in ref_scores]}')
        pin_fracs_dbg = {i: round(pin_frac[i], 3) for i in range(N) if pin_frac[i] is not None}
        print(f'  good={[int(g) for g in good]} distinctive={[int(d) for d in distinctive]}')
        print(f'  target_fracs (slots)        = {[round(f, 3) for f in target_fracs]}')
        print(f'  feature slot (vert->slot)   = {feature_slots}')
        print(f'  feature slide (vert->blend) = {engage}')
        print(f'  pin_frac (vert->frac)       = {pin_fracs_dbg}')

    # Free verts relax between the (blended) feature pins, even <-> parent by interpolation.
    even = relax_between_pins(N, cyclic, target_fracs, pin_frac, [1.0] * N)
    parent_target = relax_between_pins(N, cyclic, parent_fracs if parent_fracs else target_fracs,
                                       pin_frac, parent_gaps if parent_fracs else ref_gaps)
    return [
        pin_frac[i] if pin_frac[i] is not None
        else lerp_frac(even[i], parent_target[i], w, cyclic)
        for i in range(N)
    ]


def ordered_ring_verts(nbmvs_set: set, cyclic: bool) -> list:
    """Walk BMesh edge connectivity within nbmvs_set and return verts in order.

    For non-cyclic strips, starts from an endpoint (degree-1 vert in the set).
    """
    if not nbmvs_set:
        return []
    adj = {
        bmv: [bme.other_vert(bmv) for bme in bmv.link_edges if bme.other_vert(bmv) in nbmvs_set]
        for bmv in nbmvs_set
    }
    start = next((bmv for bmv in nbmvs_set if len(adj[bmv]) == 1), next(iter(nbmvs_set)))
    ordered = [start]
    visited = {start}
    while True:
        nexts = [v for v in adj[ordered[-1]] if v not in visited]
        if not nexts:
            break
        ordered.append(nexts[0])
        visited.add(nexts[0])
    return ordered





def enforce_min_gap(fracs: list, cyclic: bool, min_gap: float) -> list:
    """Spread arc-fracs so no two consecutive verts are closer than min_gap, staying as close to the
    input as possible (least-squares) and preserving order.

    Curvature placement can pile several verts onto one feature (a sharp corner or the flanks of a soft
    bevel); this caps how tight a cluster can get without otherwise disturbing the distribution.  Uses
    Pool-Adjacent-Violators on u[i] = pos[i] - i*min_gap, whose non-decreasing projection is exactly
    the closest min-gap-feasible placement.  Cyclic paths are cut at their largest gap first (the most
    slack), so the wrap-around seam stays >= min_gap.
    """
    n = len(fracs)
    if n < 2 or min_gap <= 0.0 or n * min_gap >= 1.0:
        return fracs   # nothing to do, or infeasibly large min_gap — leave untouched

    if cyclic:
        # Cut at the largest gap, unwrap to a monotonic chain, PAVA, rewrap.  No fixed endpoints, so
        # the least-squares (closest) solution is valid and the slack seam keeps the wrap >= min_gap.
        gaps = [(fracs[(i + 1) % n] - fracs[i]) % 1.0 for i in range(n)]
        cut = max(range(n), key=lambda i: gaps[i])
        order = [(cut + 1 + k) % n for k in range(n)]
        pos = [fracs[order[0]]]
        for k in range(1, n):
            pos.append(pos[-1] + (fracs[order[k]] - fracs[order[k - 1]]) % 1.0)
        # PAVA: closest non-decreasing fit to u[i] = pos[i] - i*min_gap  ->  gaps >= min_gap.
        u = [pos[i] - i * min_gap for i in range(n)]
        vals, cnts = [], []
        for x in u:
            vals.append(x); cnts.append(1)
            while len(vals) >= 2 and vals[-2] > vals[-1]:
                x2, c2 = vals.pop(), cnts.pop()
                x1, c1 = vals.pop(), cnts.pop()
                c = c1 + c2
                vals.append((x1 * c1 + x2 * c2) / c); cnts.append(c)
        u_iso = []
        for v, c in zip(vals, cnts):
            u_iso.extend([v] * c)
        result = list(fracs)
        for k, idx in enumerate(order):
            result[idx] = (u_iso[k] + k * min_gap) % 1.0
        return result

    # Open strip: endpoints are fixed path ends, so spread the interior with a forward then backward
    # min-gap clamp anchored at fracs[0]/fracs[-1] (a free least-squares fit could push past an end).
    result = list(fracs)
    lo, hi, prev = result[0], result[-1], result[0] - min_gap
    for i in range(n):
        result[i] = max(result[i], prev + min_gap); prev = result[i]
    nxt = hi + min_gap
    for i in range(n - 1, -1, -1):
        result[i] = min(result[i], nxt - min_gap); nxt = result[i]
    return result


def sample_even(points: list, cyclic: bool, vertex_count: int, path_length: float) -> list | None:
    """Uniform arc-length sampling: iterative bisection to place exactly vertex_count points.

    Returns a list of Vectors or None on failure.
    """
    segment_count = vertex_count if cyclic else vertex_count - 1
    if segment_count <= 0 or path_length < 1e-10:
        return None
    true_segment_length = path_length / segment_count
    factor_min, factor_max = 0.8, 1.2
    best_npts = None
    for _ in range(10):
        factor = (factor_min + factor_max) / 2
        segment_length = true_segment_length * factor
        dist, npts = 0.0, []
        for pt0, pt1 in iter_pairs(points, cyclic):
            vec01 = pt1 - pt0
            len01 = vec01.length
            if dist > len01:
                dist -= len01
                continue
            dir01 = vec01 / len01
            pt = pt0
            while dist <= len01:
                pt = pt + dir01 * dist
                npts.append(pt)
                len01 -= dist
                dist = segment_length
            dist -= len01
        if not cyclic:
            npts.append(points[-1])
        if len(npts) == vertex_count:
            best_npts = npts
            final_dist = (npts[0] - npts[-1]).length if cyclic else (npts[-1] - npts[-2]).length
            if final_dist < true_segment_length:
                factor_min, factor_max = factor_min, factor
            else:
                factor_min, factor_max = factor, factor_max
        elif len(npts) < vertex_count:
            factor_min, factor_max = factor_min, factor
        else:
            factor_min, factor_max = factor, factor_max
            if not best_npts or len(npts) <= len(best_npts):
                best_npts = npts
    return best_npts


def sample_curvature(points: list, cyclic: bool, vertex_count: int, path_length: float, curvature_bias: float = 0, out_scores: list | None = None) -> list:
    """Simplify the cross-section path with Ramer-Douglas-Peucker to choose exactly
    vertex_count positions that best preserve the visible shape.

    This mirrors Blender's Grease Pencil Simplify modifier Adaptive mode: each point is
    scored by its perpendicular deviation from the chord connecting the two endpoints of
    the sub-segment in which it is the farthest outlier.  Both sharp corners (large local
    angle) and gentle arcs spanning a long chord (small individual angles but large
    aggregate deviation) receive appropriate importance, so neither type of feature is
    starved of vertices.
    """
    n = len(points)
    if n < 3 or vertex_count <= 0 or path_length < 1e-10:
        return sample_even(points, cyclic, vertex_count, path_length) or []
    if vertex_count >= n:
        return [Vector(p) for p in points]

    scores = [0.0] * n

    def rdp_score(i0: int, i1: int) -> None:
        """Iterative RDP: assign each interior point a score equal to its perpendicular
        distance from the chord i0→i1.  Uses linear indices; actual array access is k%n
        so the function handles both halves of a cyclic split without special-casing.
        """
        stack = [(i0, i1)]
        while stack:
            a, b = stack.pop()
            if b - a <= 1:
                continue
            p0 = Vector(points[a % n])
            p1 = Vector(points[b % n])
            seg = p1 - p0
            seg_len2 = seg.length_squared
            max_dist, max_k = -1.0, a + 1
            for k in range(a + 1, b):
                p = Vector(points[k % n])
                if seg_len2 < 1e-20:
                    d = (p - p0).length
                else:
                    t = max(0.0, min(1.0, (p - p0).dot(seg) / seg_len2))
                    d = (p - p0.lerp(p1, t)).length
                if d > max_dist:
                    max_dist, max_k = d, k
            if max_dist > 0:
                scores[max_k % n] = max_dist
            stack.append((a, max_k))
            stack.append((max_k, b))

    if cyclic:
        # Find two farthest-apart points as virtual endpoints; score both arcs separately.
        centroid = Vector((0.0, 0.0, 0.0))
        for p in points:
            centroid += Vector(p)
        centroid /= n
        i0 = max(range(n), key=lambda i: (Vector(points[i]) - centroid).length_squared)
        i1 = max(range(n), key=lambda i: (Vector(points[i]) - Vector(points[i0])).length_squared)
        if i1 < i0:
            i0, i1 = i1, i0
        scores[i0] = float('inf')
        scores[i1] = float('inf')
        rdp_score(i0, i1)
        rdp_score(i1, i0 + n)  # second arc wraps; interior indices accessed as k % n
    else:
        scores[0] = float('inf')
        scores[n - 1] = float('inf')
        rdp_score(0, n - 1)

    # Frac-blend approach:
    #   1. Compute RDP selection with a spreading tiebreaker → rdp_fracs
    #   2. Compute ideal uniform fracs → even_fracs (exactly what sample_even produces)
    #   3. Align rdp_fracs to even_fracs by finding the best cyclic rotation (cyclic only)
    #   4. Lerp each pair by curvature_bias in arc-length fraction space
    #   5. fracs_to_positions → interpolated 3D positions on the polyline
    #
    # curvature_bias=0 → identical to Even mode (exact arc-length uniform spacing)
    # curvature_bias=1 → RDP curvature placement selected with a spreading tiebreaker
    # 0<curvature_bias<1 → smooth positional blend, no greedy approximation artefacts.
    #
    # The tiebreaker is always active in the RDP selection: when two candidates have
    # similar RDP scores (flat regions), the one farthest from already-selected verts
    # wins.  The tiebreaker weight is at most TIEBREAK_FRAC of max_finite so it never
    # overrides genuine curvature differences, but on flat geometry (all scores ≈ 0)
    # it dominates and produces even selection order.
    TIEBREAK_FRAC = 0.1

    pt_fracs = arc_fracs(points, cyclic)

    # --- RDP greedy selection with spreading tiebreaker ---
    if cyclic:
        rdp_selected = sorted([i0, i1])
        rdp_candidates = [i for i in range(n) if i != i0 and i != i1]
    else:
        rdp_selected = [0, n - 1]
        rdp_candidates = list(range(1, n - 1))

    # Normalise the inf anchor seeds to finite so they participate in scoring.
    max_finite = max((s for s in scores if s < float('inf')), default=1.0)
    for i in range(n):
        if scores[i] >= float('inf'):
            scores[i] = max_finite

    # Augment RDP scores with the rate-of-curvature-change (dκ/ds) signal at FULL, curvature-INDEPENDENT
    # weight.  This boosts points at flat→bevel transition boundaries so they're chosen even when their
    # individual RDP deviation is low.  Crucially the weight does NOT scale with curvature_bias: the set
    # of points selected must be stable across the slider.  A curvature-scaled weight tips the greedy
    # near a tie and rotates the whole selection by a slot as you drag — which then makes the rotation
    # search reassign every vert (the assignment "hops").  Curvature controls where verts go (the slide
    # in proportional_redistribute and the even↔feature blend below), never which points are chosen.
    sin_angles, dk = curvature_change_scores(points, cyclic, pt_fracs)
    dk_weight    = max_finite * TRANSITION_WEIGHT
    pre_selected = set(rdp_selected)
    # Gate dκ on the maximum turning angle in a local window.  A dκ peak that flanks a sharp corner
    # (even 2-3 path-points away) will have a large sin(angle) somewhere in its window — so it is
    # suppressed.  A soft-bevel boundary has small angles throughout, so it passes the gate.
    for i in range(n):
        if i not in pre_selected:
            win = (
                [(i + d) % n for d in range(-TRANSITION_WINDOW, TRANSITION_WINDOW + 1)]
                if cyclic else
                [max(0, min(n - 1, i + d)) for d in range(-TRANSITION_WINDOW, TRANSITION_WINDOW + 1)]
            )
            if max(sin_angles[j] for j in win) < TRANSITION_ANGLE_GATE:
                scores[i] += dk[i] * dk_weight
    max_finite = max((s for s in scores), default=1.0) or 1.0

    tiebreak_scale = max(max_finite * TIEBREAK_FRAC, 1e-9)
    selected_fracs_rdp = [pt_fracs[i] for i in rdp_selected]

    while len(rdp_selected) < vertex_count and rdp_candidates:
        def rdp_key(i):
            f = pt_fracs[i]
            if selected_fracs_rdp:
                if cyclic:
                    dist = min(min(abs(f - sf), 1.0 - abs(f - sf)) for sf in selected_fracs_rdp)
                else:
                    dist = min(abs(f - sf) for sf in selected_fracs_rdp)
            else:
                dist = 1.0
            norm_even = min(dist * vertex_count, 1.0)
            return scores[i] + norm_even * tiebreak_scale

        best_i = max(rdp_candidates, key=rdp_key)
        rdp_selected.append(best_i)
        selected_fracs_rdp.append(pt_fracs[best_i])
        rdp_candidates.remove(best_i)

    rdp_selected.sort()
    rdp_fracs  = [pt_fracs[i] for i in rdp_selected]
    rdp_norm_scores = [min(scores[i] / max_finite, 1.0) for i in rdp_selected]

    N = len(rdp_selected)
    if N < 1:
        return []

    if curvature_bias <= 0.0:
        even_fracs = [k / N for k in range(N)] if cyclic else ([k / (N - 1) for k in range(N)] if N > 1 else [0.0])
        if out_scores is not None:
            # Full scores even at bias 0, so the rotation/corner-ID stay stable across the 0 boundary
            # (the per-vert slide keeps every feature at its parent-matched spot at bias 0 regardless).
            out_scores.extend(rdp_norm_scores)
        return fracs_to_positions(points, even_fracs, cyclic)

    # --- Pin / free classification ---
    # Verts whose normalised RDP score >= pin_threshold are "pinned" — they keep their
    # RDP arc-length fraction exactly.  The rest are "free" and are redistributed
    # evenly within the gap between their two enclosing pinned verts.
    #
    # curvature_bias = 1.0 → threshold = FLAT_THRESHOLD (only flat verts freed)
    # curvature_bias = 0.5 → threshold = 0.5 (top 50% pinned, bottom 50% freed)
    # curvature_bias = 0.0 → pure even spacing (handled above)
    #
    # FLAT_THRESHOLD: minimum threshold kept even at curvature_bias=1.0. Verts with
    # normalised RDP score below this are always considered flat and redistributed
    # evenly between surrounding pinned anchors regardless of curvature_bias.
    # Raise toward 0.3 to free moderately-curved verts; lower toward 0.01 to free
    # only near-perfectly-flat verts.
    FLAT_THRESHOLD = 0.01 # map_range(curvature_bias, 0, 1, 0.25, 0.05)
    pin_threshold = map_range(curvature_bias, 0, 1, 0.5, FLAT_THRESHOLD)
    is_pinned = [s >= pin_threshold for s in rdp_norm_scores]
    if not cyclic:
        is_pinned[0] = True   # path endpoints are always anchors on open strips
        is_pinned[-1] = True

    final_fracs = list(rdp_fracs)
    pinned_indices = [k for k in range(N) if is_pinned[k]]

    if not pinned_indices:
        # Fallback: no pins at all → pure even
        even_fracs = [k / N for k in range(N)] if cyclic else ([k / (N - 1) for k in range(N)] if N > 1 else [0.0])
        return fracs_to_positions(points, even_fracs, cyclic)

    # Redistribute free verts evenly within each gap between consecutive pinned verts.
    if cyclic:
        n_pins = len(pinned_indices)
        for seg in range(n_pins):
            pa = pinned_indices[seg]
            pb = pinned_indices[(seg + 1) % n_pins]

            free_in_gap = []
            k = (pa + 1) % N
            while k != pb:
                if not is_pinned[k]:
                    free_in_gap.append(k)
                k = (k + 1) % N

            if not free_in_gap:
                continue

            fa, fb = rdp_fracs[pa], rdp_fracs[pb]
            gap = (fb - fa) % 1.0
            n_free = len(free_in_gap)
            for j, k in enumerate(free_in_gap):
                final_fracs[k] = (fa + gap * (j + 1) / (n_free + 1)) % 1.0
    else:
        for seg in range(len(pinned_indices) - 1):
            pa = pinned_indices[seg]
            pb = pinned_indices[seg + 1]

            free_in_gap = [k for k in range(pa + 1, pb) if not is_pinned[k]]
            if not free_in_gap:
                continue

            fa, fb = rdp_fracs[pa], rdp_fracs[pb]
            gap = fb - fa
            n_free = len(free_in_gap)
            for j, k in enumerate(free_in_gap):
                final_fracs[k] = fa + gap * (j + 1) / (n_free + 1)

    # --- Lerp with pure even spacing for bias in [0, 0.5] ---
    # bias=0.0 → pure even;  bias=0.5 → current result;  bias>0.5 → current result unchanged.
    smooth_range = 0.5
    if curvature_bias < smooth_range:
        t = curvature_bias / smooth_range
        if cyclic:
            even_fracs = [k / N for k in range(N)]
        else:
            even_fracs = [k / (N - 1) for k in range(N)] if N > 1 else [0.0]

        if cyclic:
            # Align even_fracs rotation to final_fracs so lerp pairs the right verts.
            best_rot, best_cost = 0, float('inf')
            for rot in range(N):
                cost = sum(
                    min(abs(final_fracs[k] - even_fracs[(k + rot) % N]),
                        1.0 - abs(final_fracs[k] - even_fracs[(k + rot) % N])) ** 2
                    for k in range(N)
                )
                if cost < best_cost:
                    best_cost, best_rot = cost, rot
            even_fracs = even_fracs[best_rot:] + even_fracs[:best_rot]

        blended = []
        for e, f in zip(even_fracs, final_fracs):
            if cyclic:
                d = f - e
                if d >  0.5: d -= 1.0
                elif d < -0.5: d += 1.0
                blended.append((e + d * t) % 1.0)
            else:
                blended.append(e + (f - e) * t)
        final_fracs = blended

    if out_scores is not None:
        # Per-vert normalised RDP corner score in arc-length order (matches the returned positions).
        # Reported at FULL strength (not faded) so the rotation search and corner identification in
        # proportional_redistribute are curvature-independent — a stable assignment with no threshold to
        # cross as the slider moves.  The curvature ramp instead lives in the per-vert slide there: each
        # feature eases from its parent-matched position onto its slot as curvature_bias rises.
        out_scores.extend(rdp_norm_scores)

    # Cap clustering: no edge shorter than path_length / vertex_count / MIN_EDGE_LENGTH_DIVISOR.
    # (Even spacing already exceeds this, so it only ever loosens curvature clusters.)
    final_fracs = enforce_min_gap(final_fracs, cyclic, 1.0 / (vertex_count * MIN_EDGE_LENGTH_DIVISOR))
    return fracs_to_positions(points, final_fracs, cyclic)



def snap_redistribute(
    context, nbmvs: list, target_cos: list,
    matrix_world, matrix_world_inv,
    sym_verts: set, mx: bool, my: bool, mz: bool,
) -> None:
    """Move each vert to target_cos[i] (local space), snap to source, re-pin sym verts,
    then refresh the affected normals so the viewport reshades after the move."""
    new_cos = {}
    for bmv, co in zip(nbmvs, target_cos):
        npt_world = point_to_bvec3(matrix_world @ bvec_to_point(Vector(co)))
        snapped = nearest_point_valid_sources(context, npt_world, world=True, respect_clip_planes=True)
        new_cos[bmv] = matrix_world_inv @ snapped if snapped is not None else Vector(co)
    for bmv, co in new_cos.items():
        bmv.co = co
    for bmv in sym_verts:
        if mx: bmv.co.x = 0
        if my: bmv.co.y = 0
        if mz: bmv.co.z = 0

    # The verts moved, so the cached face/vert normals are stale.  Recompute them on the touched
    # faces (and their verts) so viewport shading updates after redistribution.  normal_update only
    # refreshes the normal vectors from the current geometry — it never flips winding, unlike
    # recalc_face_normals — so it can't invert a face that was already wound correctly on creation.
    faces = {bmf for bmv in nbmvs for bmf in bmv.link_faces}
    for bmf in faces:
        bmf.normal_update()
    for bmv in {v for bmf in faces for v in bmf.verts}:
        bmv.normal_update()


class Contours_Logic:
    matrix_world : Matrix | None
    matrix_world_inv : Matrix | None
    bm : BMesh | None
    em : Mesh | None

    hit : dict[str, ...]
    hits : list[dict[str, ...]]
    plane : Plane
    plane_original : Plane
    circle_hit : tuple[float, ...]
    cut_orientation : str
    initial : bool

    process_source_method : str
    last_process_source_method : str | None
    fast_depth : int
    last_fast_depth : int | None
    sample_points : int
    last_sample_points : int | None
    fast_refine_steps : int
    last_fast_refine_steps : int | None
    sdf_refine_steps : int
    last_sdf_refine_steps : int | None
    skip_step_size : float
    last_skip_step_size : float | None
    sdf_resolution : int
    last_sdf_resolution : int | None
    sdf_subdivisions : int
    last_sdf_subdivisions : int | None
    sdf_extent_scale : float
    last_sdf_extent_scale : float | None
    last_cut_orientation : str | None

    action : Literal['Loop Cut', 'Strip Cut', 'Extrude Loop', 'Extrude Strip', 'New Loop', 'New Strip' ]
    show_span_count : bool
    span_count : int
    show_twist : bool
    twist : float
    show_loop_count : bool
    loop_count : int
    cyclic : bool
    curvature_bias : float
    interpolation_factor : float

    edge_ring : set[BMEdge] | None
    cyclic_ring : bool
    sel_path : list[BMEdge] | None
    sel_cyclic : bool | None
    bridge : bool | None

    points : list[Vector] | None
    plane_fit : Plane | None
    circle_fit : tuple[float, ...] | None
    path_length : float | None
    mirror_clipped_loop : bool | None

    def __init__(self, context:Context, hit:dict[str,...], plane:Plane, circle_points:list[Vector], span_count:int,
                 process_source_method:str, hits:list[dict[str, ...]], cut_orientation:str='stroke', fast_depth:int=1,
                 sample_points:int=50, fast_refine_steps:int=5, sdf_refine_steps:int=3, skip_step_size:float=0.5, sdf_resolution:int=20,
                 sdf_subdivisions:int=0, sdf_extent_scale:float=1.5,
                 curvature_bias:float=0.7, interpolation_factor:float=1.0):
        self.hit = hit
        self.hits = hits
        self.cut_orientation = cut_orientation
        self.last_cut_orientation = None
        self.plane_original = plane
        self.plane = snap_plane_to_direction(plane, hit, cut_orientation)
        self.circle_hit = hyperLSQ([list(self.plane.w2l_point(pt).xy) for pt in circle_points if pt])
        if not math.isfinite(self.circle_hit[0]) or not math.isfinite(self.circle_hit[1]):
            # fall back to the stroke hit projected onto the cut plane
            hit_local = self.plane.w2l_point(hit['co_world'])
            self.circle_hit = (hit_local.x, hit_local.y, 0.0, 0.0)
        self.process_source_method = process_source_method
        self.last_process_source_method = None
        self.fast_depth = fast_depth
        self.last_fast_depth = None
        self.sample_points = sample_points
        self.last_sample_points = None
        self.fast_refine_steps = fast_refine_steps
        self.last_fast_refine_steps = None
        self.sdf_refine_steps = sdf_refine_steps
        self.last_sdf_refine_steps = None
        self.skip_step_size = skip_step_size
        self.last_skip_step_size = None
        self.sdf_resolution = sdf_resolution
        self.last_sdf_resolution = None
        self.sdf_subdivisions = sdf_subdivisions
        self.last_sdf_subdivisions = None
        self.sdf_extent_scale = sdf_extent_scale
        self.last_sdf_extent_scale = None
        self.curvature_bias = curvature_bias
        self.interpolation_factor = interpolation_factor

        self.action = ''
        self.initial = True

        self.show_span_count = False
        self.span_count = span_count

        self.show_twist = False
        self.twist = 0

        self.show_loop_count = False
        self.loop_count = 1

        self.cyclic = False
        self.bm, self.em = None, None
        self.matrix_world, self.matrix_world_inv = None, None

        self.edge_ring = None
        self.cyclic_ring = False
        self.sel_path = None
        self.sel_cyclic = None
        self.bridge = None
        self.points = None
        self.plane_fit = None
        self.circle_fit = None
        self.path_length = None
        self.mirror_clipped_loop = None

    def update(self, context:Context):
        self.bm, self.em = get_bmesh_emesh(context)
        bmops.flush_selection(self.bm, self.em)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe() if self.matrix_world else None

        try:
            if not self.process_source(context): return
            self.process_target(context)
            self.find_boundary_for_bridging(context)
            self.insert(context)
        except Exception as e:
            print(f'Exception caught: {e}')
            debugger.print_exception()

        self.initial = False

    def process_source(self, context:Context) -> bool:
        # process source only once, unless settings have changed
        if (not self.initial and
            self.last_process_source_method == self.process_source_method and
            self.last_fast_depth == self.fast_depth and
            self.last_sample_points == self.sample_points and
            self.last_fast_refine_steps == self.fast_refine_steps and
            self.last_sdf_refine_steps == self.sdf_refine_steps and
            self.last_skip_step_size == self.skip_step_size and
            self.last_sdf_resolution == self.sdf_resolution and
            self.last_sdf_subdivisions == self.sdf_subdivisions and
            self.last_sdf_extent_scale == self.sdf_extent_scale and
            self.last_cut_orientation == self.cut_orientation
        ):
            # print(f'skipping re-processing source')
            return True
        self.last_process_source_method = self.process_source_method
        self.last_fast_depth = self.fast_depth
        self.last_sample_points = self.sample_points
        self.last_fast_refine_steps = self.fast_refine_steps
        self.last_sdf_refine_steps = self.sdf_refine_steps
        self.last_skip_step_size = self.skip_step_size
        self.last_sdf_resolution = self.sdf_resolution
        self.last_sdf_subdivisions = self.sdf_subdivisions
        self.last_sdf_extent_scale = self.sdf_extent_scale
        self.last_cut_orientation = self.cut_orientation
        self.plane = snap_plane_to_direction(self.plane_original, self.hit, self.cut_orientation)

        match self.process_source_method:
            case 'fast':
                return self.process_source_fast(context)
            case 'skip':
                return self.process_source_skip(context)
            case 'walk':
                return self.process_source_walk(context)
            case 'sdf':
                return self.process_source_sdf(context)
            case _:
                assert False, f'Unhandled source processing method "{self.process_source_method}"'

    def process_target(self, context:Context):
        # did we hit current geometry and need to insert an edge loop?
        self.edge_ring = None
        self.cyclic_ring = False
        self.sel_path = None
        self.sel_cyclic = False
        self.bridge = None

        if not self.bm.verts:
            return
        if self.plane_fit is None:
            return

        M = self.matrix_world
        rgn, r3d = context.region, context.region_data

        #################################################################################
        # determine if cutting existing geometry by:
        # - find quad-only bmface that crosses the plane and is under mouse
        # - walk around geometry to find edges that should be cut
        hit_co3 = self.hit['co_local']
        hit_co2 = location_3d_to_region_2d(rgn, r3d, self.hit['co_world'])  # same as mouse unless view changes
        if hit_co2 is None:
            return

        inf = float('inf')
        plane_fit = self.plane_fit
        def distance_to_hit(bmf):
            if not bmf_is_quad(bmf): return inf
            center3, radius3 = bmf_midpoint_radius(bmf)
            dist3 = (hit_co3 - center3).length
            if dist3 > radius3: return inf
            center2 = location_3d_to_region_2d(rgn, r3d, M @ center3)
            if center2 is None:
                return inf
            return (hit_co2 - center2).length
        bmf = min(self.bm.faces, default=None, key=distance_to_hit)
        if bmf and math.isfinite(distance_to_hit(bmf)):
            # hit bmface!
            self.edge_ring = set()
            self.cyclic_ring = False
            first_attempt = True
            for bme in bmf.edges:
                if not plane_fit.bme_crosses(bme): continue  # ignore edges that do not cross plane
                pre_bmf = bmf
                while True:
                    if bme in self.edge_ring:
                        if first_attempt: self.cyclic_ring = True
                        break
                    self.edge_ring.add(bme)
                    next_bmf = bme_other_bmf(bme, pre_bmf)
                    if not next_bmf or not bmf_is_quad(next_bmf): break
                    bme = quad_bmf_opposite_bme(next_bmf, bme)
                    pre_bmf = next_bmf
                first_attempt = False
            if self.edge_ring:
                # update cyclic to match cut-into geometry
                # TODO: DO NOT OVERRIDE THIS HERE...
                self.cyclic = self.cyclic_ring

        # should we bridge with currently selected geometry?
        self.sel_path, self.sel_cyclic = find_selected_cycle_or_path(self.bm, hit_co3, only_boundary=False)
        self.bridge = bool(self.sel_path) and (self.cyclic == self.sel_cyclic)

    def find_boundary_for_bridging(self, context:Context):
        if not self.bridge or not self.sel_path:
            return

        # print(f'-----------------------------------------------------')

        sel_paths = []

        if any(len(bme.link_faces) == 0 for bme in self.sel_path):
            # all are wires; no walking needed
            return
        if all(len(bme.link_faces) == 1 for bme in self.sel_path):
            # print(f'selection is a boundary')
            sel_paths.append((self.sel_path, self.sel_cyclic))
        touched = set()
        working = set(self.sel_path)
        while working:
            # step out 1 ring
            # print(f'stepping out 1 ring {len(working)=}')
            nworking = set()
            for bme0 in working:
                if bme0 in touched: continue
                touched.add(bme0)
                for bmf in bme0.link_faces:
                    if not bmf_is_quad(bmf): continue
                    bme1 = quad_bmf_opposite_bme(bmf, bme0)
                    if bme1 in touched: continue
                    nworking.add(bme1)
            # crawl around boundary
            boundary = {
                bme for bme in nworking
                if bme.is_boundary
            }
            # print(f'{len(nworking)=} {len(boundary)=} {boundary=}')
            touched_boundary = set()
            for bme_init in boundary:
                if bme_init in touched_boundary: continue
                current = [bme_init]
                boundary_cyclic = False
                for i in range(2):
                    while True:
                        bme0 = current[-1]
                        if bme0 in touched_boundary:
                            boundary_cyclic = True
                            break
                        touched_boundary.add(bme0)
                        for bme1 in [bme for bmv in bme0.verts for bme in bmv.link_edges]:
                            if bme1 not in boundary: continue
                            if bme1 in touched_boundary: continue
                            current.append(bme1)
                            break
                    current.reverse()
                    if i == 0:
                        touched_boundary.remove(current[-1])  # remove so we can walk the other direction
                touched_boundary.add(bme_init)
                sel_paths.append((current, boundary_cyclic))
            working = nworking
        # print(f'found {len(sel_paths)} possible boundaries')
        # for p in sel_paths: print(f'- {len(p[0])=} {p}')
        best_path, best_cyclic, best_dist = None, None, float('inf')
        for (bmes, cyclic) in sel_paths:
            d = min(((self.hit['co_local'] - bmv.co).length for bme in bmes for bmv in bme.verts))
            if d > best_dist: continue
            best_path, best_cyclic, best_dist = bmes, cyclic, d
        self.sel_path, self.sel_cyclic = best_path, best_cyclic

    def insert(self, context: Context):
        if self.edge_ring:
            # cut in new edge loop
            self.insert_edge_ring(context)
        elif self.bridge:
            # extrude selection to cut
            self.insert_bridge(context)
        else:
            self.insert_new_cut(context)
        bmops.flush_selection(self.bm, self.em)

    def get_corner_threshold(self):
        ''' Determines how sharp a corner must be in order for a vert to stick to in rather than move towards ideal spacing.
        The lower the value the shallower the angle that can be sticky. Setting here so it can be tuned once for both functions '''
        return map_range(self.curvature_bias, 0, 1, 0.75, 0.1)

    def insert_edge_ring(self, context: Context):
        if self.edge_ring is None:
            return

        # Precompute path fracs — used by Interpolate mode and by Curvature when
        # interpolation_factor < 1 to blend toward neighbor-matched positions.
        pt_fracs = None
        if self.points:
            pt_fracs = arc_fracs(self.points, self.cyclic)

        # USE SELECTION TO FIGURE OUT WHICH VERTS ARE NEW!
        # select only the edges on either side of cut
        bmeloops = {
            bme_
            for bme in self.edge_ring
            for bmf in bme.link_faces
            for bme_ in bmf.edges
        } - self.edge_ring
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmeloops)
        nbmelems = bmesh.ops.subdivide_edgering(self.bm, edges=list(self.edge_ring), cuts=1)['faces']
        # newly created verts will not be selected
        nbmvs = list({ bmv for bmf in nbmelems for bmv in bmf.verts if not bmv.select })

        self.finish_edgering_bridge(context, nbmelems, nbmvs)
        if DEBUG_SKIP_REDISTRIBUTE: return

        # Redistribute: curvature first (pins feature verts to path corners), then Space Evenly
        # distributes free verts between the pins.  At both=0 nothing moves.
        if self.points and self.path_length and (self.curvature_bias > 0 or self.interpolation_factor > 0):
            nbmvs_set = set(nbmvs)
            ordered_nbmvs = ordered_ring_verts(nbmvs_set, self.cyclic)
            if ordered_nbmvs:
                n = len(ordered_nbmvs)
                mx, my, mz = has_mirror_x(context), has_mirror_y(context), has_mirror_z(context)
                sym_verts = {
                    bmv for bmv in ordered_nbmvs
                    if (mx and abs(bmv.co.x) < 1e-4)
                    or (my and abs(bmv.co.y) < 1e-4)
                    or (mz and abs(bmv.co.z) < 1e-4)
                }
                # Arc-fracs of ring verts after the bridge snap — the baseline each vert starts from.
                current_fracs = [
                    project_co_to_frac(Vector(v.co), self.points, self.cyclic, pt_fracs)
                    for v in ordered_nbmvs
                ]
                # Traversal direction for cyclic rings: fwd_total ≈ 1.0 = forward, ≈ n-1 = backward.
                if self.cyclic:
                    fwd_total = sum((current_fracs[(i+1) % n] - current_fracs[i]) % 1.0 for i in range(n))
                    step = (1.0 / n) if fwd_total <= n / 2 else (-1.0 / n)

                # --- Curvature: pin feature verts to path corners ---
                pin_frac = [None] * n
                if self.curvature_bias > 0:
                    path_scores = rdp_point_scores(self.points, self.cyclic)
                    threshold = CORNER_FLOOR_FLAT - self.curvature_bias * (CORNER_FLOOR_FLAT - CORNER_FLOOR_SHARP)
                    corner_list = [
                        (pt_fracs[j], path_scores[j])
                        for j in range(len(self.points)) if path_scores[j] >= threshold
                    ]
                    half_slot = 0.5 / n
                    used_verts = set()
                    for cfrac, cscore in sorted(corner_list, key=lambda x: -x[1]):  # sharpest first
                        best_i, best_d = None, float('inf')
                        for i, vf in enumerate(current_fracs):
                            if i in used_verts:
                                continue
                            d = min((vf - cfrac) % 1.0, (cfrac - vf) % 1.0) if self.cyclic else abs(vf - cfrac)
                            if d < half_slot and d < best_d:
                                best_d, best_i = d, i
                        if best_i is not None:
                            pin_frac[best_i] = lerp_frac(current_fracs[best_i], cfrac, self.curvature_bias, self.cyclic)
                            used_verts.add(best_i)

                post_curvature = [pin_frac[i] if pin_frac[i] is not None else current_fracs[i] for i in range(n)]

                # --- Space Evenly: distribute free verts evenly between the pins ---
                # Cyclic: compute span-by-span with direction-aware step; relax_between_pins always
                # distributes forward and would flip backward rings, so we bypass it here.
                # Non-cyclic: relax_between_pins handles signed spans correctly, so use it directly.
                w = max(0.0, min(1.0, self.interpolation_factor))
                if w > 0:
                    if self.cyclic:
                        pins_list = sorted([(i, pin_frac[i]) for i in range(n) if pin_frac[i] is not None])
                        even_fracs = [None] * n
                        if not pins_list:
                            even_fracs = [(current_fracs[0] + i * step) % 1.0 for i in range(n)]
                        else:
                            P_ev = len(pins_list)
                            for s in range(P_ev):
                                ai, af = pins_list[s]
                                bi, bf = pins_list[(s + 1) % P_ev]
                                free_verts = []
                                k = (ai + 1) % n
                                while k != bi:
                                    free_verts.append(k)
                                    k = (k + 1) % n
                                nf = len(free_verts)
                                if not nf:
                                    continue
                                span = (bf - af) % 1.0 if step > 0 else (af - bf) % 1.0
                                for j, idx in enumerate(free_verts):
                                    t = (j + 1) / (nf + 1)
                                    even_fracs[idx] = (af + span * t * (1 if step > 0 else -1)) % 1.0
                    else:
                        even_fracs = relax_between_pins(n, False, list(post_curvature), pin_frac, [1.0] * n)
                    final_fracs = [
                        pin_frac[i] if pin_frac[i] is not None
                        else lerp_frac(post_curvature[i], even_fracs[i] if even_fracs[i] is not None else post_curvature[i], w, self.cyclic)
                        for i in range(n)
                    ]
                else:
                    final_fracs = post_curvature

                target_pts = fracs_to_positions(self.points, final_fracs, self.cyclic)
                snap_redistribute(
                    context, ordered_nbmvs, target_pts[:n],
                    self.matrix_world, self.matrix_world_inv, sym_verts, mx, my, mz,
                )

        self.action = 'Loop Cut' if self.cyclic else 'Strip Cut'
        self.show_twist = self.cyclic

    def insert_bridge(self, context:Context):
        orig_verts = {bv for bme in self.sel_path for bv in bme.verts}

        if self.points:
            pt_fracs = arc_fracs(self.points, self.cyclic)

        nbmelems = bmesh.ops.extrude_edge_only(self.bm, edges=self.sel_path)['geom']
        nbmvs = [bmelem for bmelem in nbmelems if type(bmelem) is BMVert]

        self.finish_edgering_bridge(context, nbmelems, nbmvs)
        if DEBUG_SKIP_REDISTRIBUTE: return

        # Redistribute: curvature first (pins feature verts to path corners), then Space Evenly
        # distributes free verts between the pins.  At both=0 nothing moves.
        if self.points and self.path_length and (self.curvature_bias > 0 or self.interpolation_factor > 0):
            nbmvs_set = set(nbmvs)
            ordered_nbmvs = ordered_ring_verts(nbmvs_set, self.cyclic)
            if ordered_nbmvs:
                n = len(ordered_nbmvs)
                mx, my, mz = has_mirror_x(context), has_mirror_y(context), has_mirror_z(context)
                sym_verts = {
                    bmv for bmv in ordered_nbmvs
                    if (mx and abs(bmv.co.x) < 1e-4)
                    or (my and abs(bmv.co.y) < 1e-4)
                    or (mz and abs(bmv.co.z) < 1e-4)
                }
                current_fracs = [
                    project_co_to_frac(Vector(v.co), self.points, self.cyclic, pt_fracs)
                    for v in ordered_nbmvs
                ]
                # Traversal direction for cyclic rings: fwd_total ≈ 1.0 = forward, ≈ n-1 = backward.
                if self.cyclic:
                    fwd_total = sum((current_fracs[(i+1) % n] - current_fracs[i]) % 1.0 for i in range(n))
                    step = (1.0 / n) if fwd_total <= n / 2 else (-1.0 / n)

                # --- Curvature: pin feature verts to path corners ---
                pin_frac = [None] * n
                if self.curvature_bias > 0:
                    path_scores = rdp_point_scores(self.points, self.cyclic)
                    threshold = CORNER_FLOOR_FLAT - self.curvature_bias * (CORNER_FLOOR_FLAT - CORNER_FLOOR_SHARP)
                    corner_list = [
                        (pt_fracs[j], path_scores[j])
                        for j in range(len(self.points)) if path_scores[j] >= threshold
                    ]
                    half_slot = 0.5 / n
                    used_verts = set()
                    for cfrac, cscore in sorted(corner_list, key=lambda x: -x[1]):  # sharpest first
                        best_i, best_d = None, float('inf')
                        for i, vf in enumerate(current_fracs):
                            if i in used_verts:
                                continue
                            d = min((vf - cfrac) % 1.0, (cfrac - vf) % 1.0) if self.cyclic else abs(vf - cfrac)
                            if d < half_slot and d < best_d:
                                best_d, best_i = d, i
                        if best_i is not None:
                            pin_frac[best_i] = lerp_frac(current_fracs[best_i], cfrac, self.curvature_bias, self.cyclic)
                            used_verts.add(best_i)

                post_curvature = [pin_frac[i] if pin_frac[i] is not None else current_fracs[i] for i in range(n)]

                # --- Space Evenly: distribute free verts evenly between the pins ---
                # Cyclic: compute span-by-span with direction-aware step; relax_between_pins always
                # distributes forward and would flip backward rings, so we bypass it here.
                # Non-cyclic: relax_between_pins handles signed spans correctly, so use it directly.
                w = max(0.0, min(1.0, self.interpolation_factor))
                if w > 0:
                    if self.cyclic:
                        pins_list = sorted([(i, pin_frac[i]) for i in range(n) if pin_frac[i] is not None])
                        even_fracs = [None] * n
                        if not pins_list:
                            even_fracs = [(current_fracs[0] + i * step) % 1.0 for i in range(n)]
                        else:
                            P_ev = len(pins_list)
                            for s in range(P_ev):
                                ai, af = pins_list[s]
                                bi, bf = pins_list[(s + 1) % P_ev]
                                free_verts = []
                                k = (ai + 1) % n
                                while k != bi:
                                    free_verts.append(k)
                                    k = (k + 1) % n
                                nf = len(free_verts)
                                if not nf:
                                    continue
                                span = (bf - af) % 1.0 if step > 0 else (af - bf) % 1.0
                                for j, idx in enumerate(free_verts):
                                    t = (j + 1) / (nf + 1)
                                    even_fracs[idx] = (af + span * t * (1 if step > 0 else -1)) % 1.0
                    else:
                        even_fracs = relax_between_pins(n, False, list(post_curvature), pin_frac, [1.0] * n)
                    final_fracs = [
                        pin_frac[i] if pin_frac[i] is not None
                        else lerp_frac(post_curvature[i], even_fracs[i] if even_fracs[i] is not None else post_curvature[i], w, self.cyclic)
                        for i in range(n)
                    ]
                else:
                    final_fracs = post_curvature

                target_pts = fracs_to_positions(self.points, final_fracs, self.cyclic)
                snap_redistribute(
                    context, ordered_nbmvs, target_pts[:n],
                    self.matrix_world, self.matrix_world_inv, sym_verts, mx, my, mz,
                )

        if self.loop_count > 1:
            # Add more loop cuts to the bridge
            new_verts_set = set(nbmvs)
            lateral_edges = list({
                bme
                for bmv in nbmvs
                for bme in bmv.link_edges
                if any(bv in orig_verts for bv in bme.verts)
            })
            if lateral_edges:
                result = bmesh.ops.subdivide_edgering(
                    self.bm,
                    edges=lateral_edges,
                    cuts=self.loop_count - 1,
                )
                intermediate_verts = list({
                    bv
                    for bmf in result['faces']
                    for bv in bmf.verts
                    if bv not in orig_verts and bv not in new_verts_set
                })
                # Find final positions before moving any vert so loop normals are accurate
                new_cos = {}
                for bmv in intermediate_verts:
                    npt_world = point_to_bvec3(self.matrix_world @ bvec_to_point(bmv.co))
                    # Find nearest surface point as reference / fallback.
                    nearest = nearest_point_valid_sources(context, npt_world, world=True, respect_clip_planes=True)
                    npt_snapped = nearest
                    # Get the outward surface normal at that nearest point.
                    surface_normal = nearest_normal_valid_sources(context, npt_world, world=True)
                    if surface_normal is not None and nearest is not None:
                        # Raycast in both directions and pick whichever hit is closest to the nearest surface.
                        hits = []
                        for sign in (1, -1):
                            ray_dir = Vector((*(surface_normal * sign), 0.0))
                            hit = raycast_ray_valid_sources(context, (Vector((*npt_world, 1.0)), ray_dir), world=True, respect_clip_planes=True)
                            if hit is not None:
                                hits.append(hit)
                        if hits:
                            npt_snapped = min(hits, key=lambda h: (h - nearest).length)
                    if npt_snapped is not None:
                        new_cos[bmv] = self.matrix_world_inv @ npt_snapped
                # Apply all positions at once.
                for bmv, co in new_cos.items():
                    bmv.co = co
                ensure_correct_normals(self.bm, result['faces'])

        self.action = 'Extrude Loop' if self.cyclic else 'Extrude Strip'
        self.show_twist = self.cyclic
        self.show_loop_count = True

    def finish_edgering_bridge(self, context:Context, nbmelems:Sequence[BMVert|BMEdge|BMFace], nbmvs:Sequence[BMVert]):
        if self.points is None or self.plane_fit is None or self.circle_fit is None:
            return

        plane_fit = self.plane_fit
        circle_fit = self.circle_fit

        # compute useful statistics about newly created geometry
        npoints = [Point(bmv.co) for bmv in nbmvs]
        try:
            if len(npoints) < 3:
                raise Exception(f'Not enough points to fit plane: {len(npoints)}')
            nplane_fit = Plane.fit_to_points(npoints)   # local space
            if plane_fit.n.dot(nplane_fit.n) < 0:
                nplane_fit.n.negate()  # make sure both planes are oriented the same
            ncircle_fit = hyperLSQ([list(nplane_fit.w2l_point(pt).xy) for pt in npoints])
        except Exception as e:
            print(f'CONTOURS WARNING: failed to fit plane/circle for bridge: {e}')
            nplane_fit = plane_fit
            ncircle_fit = circle_fit

        # identify symmetry plane verts before any transformation so we can re-pin them after
        mx, my, mz = has_mirror_x(context), has_mirror_y(context), has_mirror_z(context)
        sym_verts = set()
        if mx or my or mz:
            threshold = 1e-4
            for bmv in nbmvs:
                if mx and abs(bmv.co.x) < threshold: sym_verts.add(bmv)
                if my and abs(bmv.co.y) < threshold: sym_verts.add(bmv)
                if mz and abs(bmv.co.z) < threshold: sym_verts.add(bmv)

        center_new = Vector((0.0, 0.0, 0.0))
        for bmv in nbmvs:
            center_new += Vector(bmv.co)
        center_new /= len(nbmvs)
        # Use world-space bounding-box centre, converted back to local, as center_src.
        # The arithmetic mean (plane_fit.o) is biased when sampling is non-uniform.
        # The bbox midpoint is sampling-agnostic for symmetric shapes (always (max+min)/2).
        # We must compute the bbox in world space: the bbox operation is not rotation-invariant,
        # so a local-axis bbox on a rotated retopo mesh gives a different answer from what the
        # viewport shows.  The ring appears at matrix_world @ center_src_local, so we need
        # center_src_local = matrix_world_inv @ world_bbox_center to land at the right spot.
        _M  = self.matrix_world
        _Mi = self.matrix_world_inv
        _pts_w = [_M @ Vector(pt) for pt in self.points]
        _cx = (max(p.x for p in _pts_w) + min(p.x for p in _pts_w)) * 0.5
        _cy = (max(p.y for p in _pts_w) + min(p.y for p in _pts_w)) * 0.5
        _cz = (max(p.z for p in _pts_w) + min(p.z for p in _pts_w)) * 0.5
        center_src = _Mi @ Vector((_cx, _cy, _cz))

        # Compute xforms to roughly move new geometry to match cut:
        #   T0  — translate parent ring to origin
        #   S   — scale to match path radius
        #   Sh  — shear parent ring plane onto cut plane: keeps each vert's position along the
        #          planes' intersection axis fixed, shifting only the perpendicular component.
        #          This preserves angular correspondence (important for ring-normal snap).
        #   RT  — apply user twist in the cut plane
        #   T1  — translate ring centre to path centroid
        #
        # Math: for p in plane n1 (relative to center):
        #   shear_dir = in-plane unit ⊥ to intersection axis = (n1 × (n1×n2)).normalized()
        #   shear_vec = -(shear_dir·n2)/(n1·n2) * n1   ensures (p + (shear_dir·p)*shear_vec)·n2=0
        T0 = Matrix.Translation(-center_new)
        path_r = sum((Vector(p) - center_src).length for p in self.points) / max(1, len(self.points))
        ring_r = sum((Vector(bmv.co) - center_new).length for bmv in nbmvs) / max(1, len(nbmvs))
        S  = Matrix.Scale(path_r / ring_r, 4) if ring_r > 1e-6 else Matrix.Scale(1.0, 4)
        n1 = Vector(nplane_fit.n)
        n2 = Vector(plane_fit.n)
        cross = n1.cross(n2)
        dot_n1_n2 = n1.dot(n2)
        if cross.length > 1e-9 and abs(dot_n1_n2) > 1e-9:
            axis_vec    = cross.normalized()
            shear_dir   = n1.cross(axis_vec).normalized()
            shear_coeff = -(shear_dir.dot(n2)) / dot_n1_n2
            shear_vec   = shear_coeff * n1
            Sh = Matrix.Identity(4)
            for row in range(3):
                for col in range(3):
                    Sh[row][col] += shear_vec[row] * shear_dir[col]
        else:
            Sh = Matrix.Identity(4)

        RT = Matrix.Rotation(self.twist, 4, plane_fit.n)
        T1 = Matrix.Translation(center_src)
        xform = T1 @ RT @ Sh @ S @ T0


        # Project each vert onto the cross-section path along its ring's 2D normal.
        # For each new vert: compute the ring tangent from the two adjacent new verts, derive the
        # in-plane normal (plane_n × tangent), then shoot a bidirectional ray and pick the closest
        # path-segment hit.  This avoids the nearest-point corner ambiguity and works on non-convex
        # paths where a centroid-based ray would fail.
        #
        # Nearest-point is always computed first and used as both a pre-check and a fallback:
        #   • If the vert is already on the path (nearest_dist < ON_PATH_EPS), keep it there and
        #     skip the raycast entirely.  The ray would start on a segment, making denom≈0 for
        #     that segment (ray parallel when ring tangent ⊥ path tangent) — skipping it and
        #     potentially landing on the wrong segment on the far side of the loop.
        #   • If the ring tangent can't be computed (strip endpoints) or no segment is hit,
        #     fall through to nearest-point, then the world-space snap as a last resort.
        pts = self.points
        n_pts = len(pts)
        n_segs = n_pts if self.cyclic else n_pts - 1
        plane_n = n2  # cut-plane normal (= plane_fit.n)
        ON_PATH_EPS = 1e-6  # distance threshold: treat vert as already-on-path below this

        # Pass 1: apply xform so that ring-neighbor positions are up-to-date before normals are read.
        nbmvs_set_snap = set(nbmvs)
        for bmv in nbmvs:
            bmv.co = xform @ bmv.co


        # Bbox correction: pin the ring's world-bbox centre to the path's world-bbox centre.
        # center_src was derived from the world-axis bbox of self.points, so we must compare
        # like-with-like: compute the ring's world bbox after the xform and correct that,
        # NOT the arithmetic mean.  For non-uniformly sampled rings, mean ≠ bbox centre, so
        # a mean-based correction would leave the visual (bbox) centre offset.
        _ring_cos_w = [_M @ Vector(bmv.co) for bmv in nbmvs]
        _rbx = (max(c.x for c in _ring_cos_w) + min(c.x for c in _ring_cos_w)) * 0.5
        _rby = (max(c.y for c in _ring_cos_w) + min(c.y for c in _ring_cos_w)) * 0.5
        _rbz = (max(c.z for c in _ring_cos_w) + min(c.z for c in _ring_cos_w)) * 0.5
        ring_world_bbox = Vector((_rbx, _rby, _rbz))
        path_world_bbox = _M @ center_src  # world-space version of center_src
        world_correction = path_world_bbox - ring_world_bbox
        # Convert world-space correction to local space: delta_local s.t. R @ delta_local = delta_world
        centroid_offset = _Mi.to_3x3() @ world_correction
        if centroid_offset.length > 1e-9:
            for bmv in nbmvs:
                bmv.co += centroid_offset

        if DEBUG_PRINT_SPACING:
            s_val = path_r / ring_r if ring_r > 1e-6 else 1.0
            print(f'[Bridge] center_new:      {center_new}  (arith mean of parent ring)')
            print(f'[Bridge] center_src:      {center_src}  (world bbox → local)')
            print(f'[Bridge] path_world_bbox: {path_world_bbox}')
            print(f'[Bridge] ring_world_bbox: {ring_world_bbox}  (after xform, before correction)')
            print(f'[Bridge] plane_fit.o:     {Vector(plane_fit.o)}  (arith mean of path)')
            print(f'[Bridge] path mean_r:     {path_r:.4f}  ring mean_r: {ring_r:.4f}  S={s_val:.4f}')
            print(f'[Bridge] n1·n2 (dot):     {dot_n1_n2:.4f}  cross len: {cross.length:.4f}  shear applied: {cross.length > 1e-9 and abs(dot_n1_n2) > 1e-9}')
            print(f'[Bridge] world_correction: {world_correction.length:.8f}  local_correction: {centroid_offset.length:.8f}')

        if DEBUG_SKIP_BRIDGE_SNAP: return

        # Pass 2: project each vert along its ring normal onto the path.
        for bmv in nbmvs:
            v = Vector(bmv.co)

            # Nearest point on path (raw Vector math — no bvec_to_point type conversion needed).
            nearest_pt  = None
            nearest_dist = float('inf')
            for i in range(n_segs):
                a = Vector(pts[i])
                b = Vector(pts[(i + 1) % n_pts])
                ab = b - a
                ab_len2 = ab.length_squared
                if ab_len2 < 1e-10:
                    cand = a
                else:
                    f = max(0.0, min(1.0, ab.dot(v - a) / ab_len2))
                    cand = a + ab * f
                d = (cand - v).length
                if d < nearest_dist:
                    nearest_dist = d
                    nearest_pt   = cand

            # If already on the path, keep position and skip the raycast.
            if nearest_dist < ON_PATH_EPS:
                if nearest_pt is not None:
                    bmv.co = nearest_pt
                continue

            # Ring tangent from the two adjacent new verts (edges that stay within the new ring).
            ring_nbrs = [e.other_vert(bmv) for e in bmv.link_edges if e.other_vert(bmv) in nbmvs_set_snap]
            if len(ring_nbrs) >= 2:
                tangent = Vector(ring_nbrs[1].co) - Vector(ring_nbrs[0].co)
            elif len(ring_nbrs) == 1:
                tangent = Vector(ring_nbrs[0].co) - v
            else:
                tangent = None

            best_pt = None
            if tangent and tangent.length > 1e-9:
                # In-plane normal = plane_n × tangent (perpendicular to ring tangent, within cut plane).
                # Direction doesn't matter — we shoot bidirectionally and pick the closest hit.
                ring_normal = plane_n.cross(tangent).normalized()

                # Bidirectional ray v + t*ring_normal.  Don't gate on t sign — both directions are
                # valid.  Only s ∈ [0,1] matters (intersection must lie on the actual segment).
                # s tolerance 1e-4: tighter than 1e-6 would miss corner vertices after rotation/scale
                # float32 accumulation.
                best_dist = float('inf')
                for i in range(n_segs):
                    a = Vector(pts[i])
                    b = Vector(pts[(i + 1) % n_pts])
                    q = b - a
                    p = a - v  # vector from ray origin to segment start
                    # 3D perp-dot in the cut plane: (u × v) · plane_n
                    denom = ring_normal.cross(q).dot(plane_n)
                    if abs(denom) < 1e-9:
                        continue  # ray parallel to segment
                    s = -ring_normal.cross(p).dot(plane_n) / denom
                    if s < -1e-4 or s > 1.0 + 1e-4:
                        continue  # intersection outside segment extent
                    s = max(0.0, min(1.0, s))
                    snap_pt = a + s * q
                    dist = (snap_pt - v).length
                    if dist < best_dist:
                        best_dist = dist
                        best_pt = snap_pt

            if best_pt is not None:
                bmv.co = best_pt
            elif nearest_pt is not None:
                # Fallback: nearest point already computed above (no extra loop needed).
                bmv.co = nearest_pt
            else:
                # Last resort: world-space snap.
                npt_local = bvec_to_point(v)
                npt_world = point_to_bvec3(self.matrix_world @ npt_local)
                npt_world_snapped = nearest_point_valid_sources(context, npt_world, world=True, respect_clip_planes=True)
                npt_world_new = npt_world_snapped if npt_world_snapped else npt_world
                bmv.co = self.matrix_world_inv @ npt_world_new if npt_world_new is not None else npt_local

        # re-pin any verts that were on a symmetry plane so twist can't move them off
        for bmv in sym_verts:
            if mx: bmv.co.x = 0
            if my: bmv.co.y = 0
            if mz: bmv.co.z = 0

        if not self.cyclic:
            # snap ends
            if self.edge_ring:
                bmv_ends = [bmv for bmv in nbmvs if len(bmv.link_faces) == 2]
            else:
                bmv_ends = [bmv for bmv in nbmvs if len(bmv.link_faces) == 1]

            if len(bmv_ends) != 2:
                print(f'CONTOURS WARNING: FOUND {len(bmv_ends)} ENDS ON NON-CYCLIC PATH!?')
            else:
                bmv0, bmv1 = bmv_ends
                co0, co1 = bmv0.co, bmv1.co
                pt0, pt1 = self.points[0], self.points[-1]
                if (co0 - pt0).length + (co1 - pt1).length < (co0 - pt1).length + (co1 - pt0).length:
                    bmv0.co, bmv1.co = pt0, pt1
                else:
                    bmv0.co, bmv1.co = pt1, pt0

        # make sure face normals are correct.  cannot do this earlier, because
        # faces have no defined normal (verts overlap)
        nbmfs = [bmelem for bmelem in nbmelems if type(bmelem) is BMFace]
        ensure_correct_normals(self.bm, nbmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, nbmvs)


    def insert_new_cut(self, context:Context):
        M, Mi = self.matrix_world, self.matrix_world_inv
        path_length = self.path_length

        if self.points is None or M is None or Mi is None or path_length is None:
            return

        points : list[Vector] = []
        for pt in self.points:
            if points and (points[-1] - pt).length == 0: continue
            points += [pt]

        if self.cyclic and not self.mirror_clipped_loop and self.twist and path_length > 0:
            offset = (self.twist % (2 * math.pi)) / (2 * math.pi) * path_length
            acc = 0.0
            n = len(points)
            for i in range(n):
                pt0 = points[i]
                pt1 = points[(i + 1) % n]
                seg = (pt1 - pt0).length
                if acc + seg >= offset:
                    t = (offset - acc) / seg if seg > 0 else 0.0
                    new_start = pt0 + (pt1 - pt0) * t
                    points = [new_start] + points[i + 1:] + points[:i + 1]
                    break
                acc += seg

        segment_count = self.span_count
        vertex_count = self.span_count if self.cyclic else self.span_count + 1
        if self.mirror_clipped_loop:
            # update vertex count, because the loop crosses mirror
            vertex_count = vertex_count // 2 + 1
            segment_count = vertex_count - 1

        # find pts for new geometry; interpolation_factor has no effect on new cuts (no surrounding topology)
        npts = sample_curvature(points, self.cyclic, vertex_count, path_length, self.curvature_bias)
        assert npts, f'Could not find enough points!?'
        assert len(npts) >= vertex_count
        npts = [
            Mi @ snapped if (snapped := nearest_point_valid_sources(context, M @ pt, world=True, respect_clip_planes=True)) is not None else pt
            for pt in npts
        ]

        # create geometry!
        nbmvs = [ self.bm.verts.new(pt) for pt in npts[:vertex_count] ]
        bmes = [self.bm.edges.new((bmv0, bmv1)) for (bmv0, bmv1) in iter_pairs(nbmvs, self.cyclic)]

        if not self.cyclic:
            # snap ends
            bmv_ends = [bmv for bmv in nbmvs if len(bmv.link_edges) == 1]
            if len(bmv_ends) != 2:
                print(f'CONTOURS WARNING: FOUND {len(bmv_ends)} ENDS ON NON-CYCLIC PATH!?')
            else:
                bmv0, bmv1 = bmv_ends
                co0, co1 = bmv0.co, bmv1.co
                pt0, pt1 = points[0], points[-1]
                if (co0 - pt0).length + (co1 - pt1).length < (co0 - pt1).length + (co1 - pt0).length:
                    bmv0.co, bmv1.co = pt0, pt1
                else:
                    bmv0.co, bmv1.co = pt1, pt0

        if self.cyclic:
            self.action = 'New Loop'
        else:
            self.action = 'New Strip'
        self.show_span_count = True
        self.show_twist = self.cyclic

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, nbmvs)


    #######################################################
    # different methods for processing source

    def refine_loop(self, context:Context, points_world:list, plane_normal_world:Vector, steps:int) -> list:
        '''Cut line surface refinement pass shared by Fast and SDF.'''
        plane_cut = self.plane

        def _on_plane(pt):
            lp = plane_cut.w2l_point(pt); lp.z = 0
            return Vector(plane_cut.l2w_point(lp))

        pts_w = [Vector(p) for p in points_world]

        # correct jagged path from SDF tracing before subdividing
        if self.process_source_method == 'sdf':
            for _ in range(steps):
                corrected = []
                for p in pts_w:
                    p_plane = _on_plane(p)
                    npt = nearest_point_valid_sources(context, p_plane, world=True, respect_clip_planes=False)
                    corrected.append(_on_plane(Vector(npt)) if npt is not None else p_plane)
                pts_w = corrected

        # Subdivide the longest edges in the path (inherently the least accurate) and snap again
        for _ in range(steps):
            n_w = len(pts_w)
            lengths = [(pts_w[(i+1) % n_w] - pts_w[i]).length for i in range(n_w)]
            threshold = sorted(lengths)[int(0.75 * n_w)]
            new_pts_w = []
            for i in range(n_w):
                p0 = pts_w[i]
                p1 = pts_w[(i+1) % n_w]
                # Existing verts on the plane are left untouched.
                # Drifted verts are reprojected and re-snapped via nearest point
                if abs(plane_cut.w2l_point(p0).z) > 1e-6:
                    p0 = _on_plane(p0)
                    npt = nearest_point_valid_sources(context, p0, world=True, respect_clip_planes=False)
                    if npt is not None:
                        p0 = _on_plane(Vector(npt))
                new_pts_w.append(p0)
                if lengths[i] < threshold: continue
                m = _on_plane((p0 + p1) / 2)

                if self.process_source_method == 'sdf':
                    # Nearest-point avoids unstable 2D normals issues from the jagged grid boundary
                    npt = nearest_point_valid_sources(context, m, world=True, respect_clip_planes=False)
                    new_pts_w.append(_on_plane(Vector(npt)) if npt is not None else m)
                else:
                    # For Fast: raycast since the 2D normals are already facing the proper direction
                    m_snapped = nearest_point_valid_sources(context, m, world=True, respect_clip_planes=False)
                    if m_snapped is not None and (Vector(m_snapped) - m).length < lengths[i] * 0.05:
                        new_pts_w.append(_on_plane(Vector(m_snapped)))
                        continue
                    seg = p1 - p0
                    inplane_n = plane_normal_world.cross(seg)
                    if inplane_n.length_squared < 1e-12:
                        new_pts_w.append(m)
                        continue
                    inplane_n.normalize()
                    nudge = max(1e-4, seg.length * 1e-3)
                    hit_a = raycast_ray_valid_sources(context, (m + inplane_n * nudge,  inplane_n),  world=True, respect_clip_planes=True)
                    hit_b = raycast_ray_valid_sources(context, (m - inplane_n * nudge, -inplane_n), world=True, respect_clip_planes=True)
                    candidates = []
                    for h in (hit_a, hit_b):
                        if h is None: continue
                        lp = plane_cut.w2l_point(h); lp.z = 0
                        candidates.append(Vector(plane_cut.l2w_point(lp)))
                    new_pts_w.append(min(candidates, key=lambda h: (h - m).length_squared) if candidates else m)
            pts_w = new_pts_w

        return pts_w

    def get_volume_center(self, context:Context, plane_cut) -> tuple[Vector, Vector]:
        '''Compute the plane-local and world-space center for the cut.'''
        center_plane = Vector((self.circle_hit[0], self.circle_hit[1], 0, 1))
        if self.fast_depth > 1:
            hit_world = self.hit['co_world']
            no_world = Vector(self.hit['no_world']).normalized()
            plane_n = Vector(plane_cut.n).normalized()
            # Project no_world onto the cut plane so the cast stays within the cross-section.
            inward = no_world - no_world.dot(plane_n) * plane_n
            inward.negate()
            if inward.length > 1e-6:
                n_inward = 2 * (self.fast_depth - 1) + 1
                inward_hits = raycast_multiple_hits(context, hit_world, inward.normalized(), n_inward)
                if inward_hits:
                    midpoint = (hit_world + inward_hits[-1]) / 2
                    midpoint_local = plane_cut.w2l_point(midpoint)
                    center_plane = Vector((midpoint_local.x, midpoint_local.y, 0, 1))
        center_world = plane_cut.l2w_point(center_plane)
        return center_plane, center_world

    def normalize_winding(self, points_world: list, plane_cut) -> list:
        '''Ensure the winding order of a world space loop is consistent with the cut plane normal.'''
        if len(points_world) <= 2:
            return points_world
        plane_n = Vector(plane_cut.l2w_direction(Vector((0, 0, 1))))
        comps = [abs(plane_n.x), abs(plane_n.y), abs(plane_n.z)]
        dom = comps.index(max(comps))
        want_ccw = (plane_n.x, plane_n.y, plane_n.z)[dom] > 0
        pts_local = [plane_cut.w2l_point(Vector(p)) for p in points_world]
        n_ring = len(pts_local)
        signed_area = sum(
            pts_local[i].x * pts_local[(i+1) % n_ring].y - pts_local[(i+1) % n_ring].x * pts_local[i].y
            for i in range(n_ring)
        ) / 2
        if (signed_area > 0) != want_ccw:
            return [points_world[0]] + list(reversed(points_world[1:]))
        return points_world

    def process_source_fast(self, context:Context) -> bool:
        if DEBUG_PRINT_TIMINGS: timers = [('start', time.perf_counter())]
        plane_cut = self.plane
        center_plane, center_world = self.get_volume_center(context, plane_cut)

        if DEBUG_PRINT_TIMINGS: timers.append(('center/depth', time.perf_counter()))
        nsamples = self.sample_points
        dirs_plane = [
            Vector((math.cos(2 * math.pi * d/nsamples), math.sin(2 * math.pi * d/nsamples), 0, 0))
            for d in range(nsamples)
        ]

        dirs_world = [ plane_cut.l2w_direction(dir_plane) for dir_plane in dirs_plane ]

        if self.fast_depth <= 1:
            rays_world = [ (center_world, dir_world) for dir_world in dirs_world ]
            points_world = [
                raycast_ray_valid_sources(context, ray_world, world=True, respect_clip_planes=True)
                for ray_world in rays_world
            ]
        else:
            # Pass through the first surfaces and use the next hit.
            # Depth = 2 on a solidified mesh skips the inner wall and lands on the outer wall.
            # Fall back to a shallower hit if the mesh has fewer surfaces than requested.
            points_world = []
            for dir_world in dirs_world:
                hits = raycast_multiple_hits(context, center_world, dir_world, 2 * (self.fast_depth - 1))
                points_world.append(hits[-1] if hits else None)

        points_world = [pt for pt in points_world if pt is not None]

        if DEBUG_PRINT_TIMINGS: timers.append((f'radial rays ({nsamples})', time.perf_counter()))
        points_world = self.normalize_winding(points_world, plane_cut)

        if self.fast_refine_steps > 0 and len(points_world) >= 3:
            plane_normal_world = Vector(plane_cut.l2w_direction(Vector((0, 0, 1))))
            points_world = self.refine_loop(context, points_world, plane_normal_world, self.fast_refine_steps)

        if DEBUG_PRINT_TIMINGS: timers.append((f'refinement ({self.fast_refine_steps} steps)', time.perf_counter()))
        points = [ self.matrix_world_inv @ pt_world for pt_world in points_world if pt_world ]
        cyclic = True
        mirror_clipped_loop = False

        ####################################################################################################
        # handle cutting across mirror planes

        points, mirror_clipped_loop = self.handle_mirrors(context, points)
        if mirror_clipped_loop: cyclic = False

        if len(points) < 3:
            print(f'CONTOURS: TOO FEW POINTS FOUND TO FIT PLANE')
            return False

        ####################################################################################################
        # compute useful statistics about points

        plane_fit = Plane.fit_to_points(points)
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        if circle_fit[3] > circle_fit[2]:
            print(
                f'CONTOURS FAST: poor circle fit (sigma={circle_fit[3]:.4f} > ' +
                f'radius={circle_fit[2]:.4f}) — {len(points)} pts, depth={self.fast_depth}'
            )

        self.points = points                            # points where cut crosses source (target space)
        self.cyclic = cyclic                            # is cut cyclic (loop) or a strip?
        self.plane_fit = plane_fit                      # plane that fits cut points (target space)
        self.circle_fit = circle_fit                    # circle that fits points (plane_fit space)
        self.path_length = path_length                  # length of path of points (target space)
        self.mirror_clipped_loop = mirror_clipped_loop  # did cyclic loop cross mirror plane?

        if DEBUG_PRINT_TIMINGS:
            timers.append(('finalize', time.perf_counter()))
            _total = timers[-1][1] - timers[0][1]
            _report = [
                f'{t1-t0:.4f}s  {lbl}'
                for (lbl, t0), (_, t1) in zip(timers[:-1], timers[1:])
            ] + ['--------  ---------------', f'{_total:.4f}s  total']
            term_printer.boxed(*_report, title=f'FAST  depth={self.fast_depth}  samples={nsamples}  refine={self.fast_refine_steps}')
        return True

    def process_source_sdf(self, context:Context) -> bool:
        '''Build a coarse occupancy grid on the cut plane, trace the boundary, then snap and smooth that loop.'''
        if DEBUG_PRINT_TIMINGS: timers = [('start', time.perf_counter())]
        plane_cut = self.plane
        center_plane, center_world = self.get_volume_center(context, plane_cut)

        if DEBUG_PRINT_TIMINGS: timers.append(('center/depth', time.perf_counter()))
        nsamples = 25 # Only used to compute grid size, so can be sparse
        hit_local = plane_cut.w2l_point(Vector(self.hit['co_world']))
        xs = [center_plane.x, hit_local.x]
        ys = [center_plane.y, hit_local.y]
        angles = (2 * math.pi * np.arange(nsamples, dtype=np.float64)) / nsamples
        for c, s in zip(np.cos(angles), np.sin(angles)):
            dp = Vector((float(c), float(s), 0, 0))
            dw = plane_cut.l2w_direction(dp)
            rh = raycast_ray_valid_sources(context, (center_world, dw), world=True, respect_clip_planes=True)
            if rh is None: continue
            lp = plane_cut.w2l_point(rh)
            xs.append(lp.x); ys.append(lp.y)
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        width, height = xmax - xmin, ymax - ymin
        if width < 1e-6 or height < 1e-6:
            print('CONTOURS SDF: degenerate extent, falling back to Fast')
            return self.process_source_fast(context)
        # scale the bbox since exterior is usually bigger than measured interior
        _cx, _cy = (xmin + xmax) / 2, (ymin + ymax) / 2
        _scale = max(0.5, float(self.sdf_extent_scale))
        xmin, xmax = _cx - width * _scale / 2, _cx + width * _scale / 2
        ymin, ymax = _cy - height * _scale / 2, _cy + height * _scale / 2
        width, height = xmax - xmin, ymax - ymin

        if DEBUG_PRINT_TIMINGS: timers.append((f'extent ({nsamples} rays)', time.perf_counter()))
        # Grid dimensions. Resolution on the long axis, short axis by aspect ratio
        res: int = self.sdf_resolution
        if width >= height:
            res_x, res_y = res, max(3, round(res * height / width))
        else:
            res_y, res_x = res, max(3, round(res * width / height))
        fine_count: int = 3 ** max(0, int(self.sdf_subdivisions))
        RX, RY = res_x * fine_count, res_y * fine_count
        fcw, fch = width / RX, height / RY  # fine cell size
        base_radius = 0.5 * math.hypot(width / res_x, height / res_y) # coarse cell half-diagonal

        # Find cells near the surface
        near       = np.zeros((RX, RY), dtype=bool)
        block_size = np.full((RX, RY), fine_count, dtype=np.int16) # effective block size per fine cell (for debug)

        def classify_cell(fi, fj, radius):
            cx = xmin + (fi + 0.5) * fcw
            cy = ymin + (fj + 0.5) * fch
            c = plane_cut.l2w_point(Vector((cx, cy, 0)))
            npt = nearest_point_valid_sources(context, c, world=True, respect_clip_planes=True)
            if npt is None: return False
            npt_local = plane_cut.w2l_point(Vector(npt))
            if abs(npt_local.z) >= radius: return False
            return math.hypot(npt_local.x - cx, npt_local.y - cy) < radius

        def fill_block_uniform(fi0, fj0, sz, n_val):
            near[fi0:fi0 + sz, fj0:fj0 + sz] = n_val
            block_size[fi0:fi0 + sz, fj0:fj0 + sz] = sz

        # Large initial cells first
        for bi in range(res_x):
            for bj in range(res_y):
                n_ = classify_cell(bi * fine_count + fine_count // 2, bj * fine_count + fine_count // 2, base_radius)
                fill_block_uniform(bi * fine_count, bj * fine_count, fine_count, n_)

        # Iteratively refine by subdividing hit cells and having each smaller cell search again
        max_cell_queries = 1_000_000
        total_cell_queries = res_x * res_y  # Phase 1 already classified this many
        cur_size, cur_radius = fine_count, base_radius
        for subdiv_level in range(self.sdf_subdivisions):
            if cur_size < 3: break
            sub_size   = cur_size // 3
            sub_radius = cur_radius / 3.0
            center_off = cur_size // 2
            fi_centers = np.arange(center_off, RX, cur_size, dtype=np.int32)
            fj_centers = np.arange(center_off, RY, cur_size, dtype=np.int32)
            center_block_size = block_size[np.ix_(fi_centers, fj_centers)]
            center_near = near[np.ix_(fi_centers, fj_centers)]
            bi_idx, bj_idx = np.nonzero((center_block_size == cur_size) & center_near)
            to_refine = [
                (int(fi_centers[i] - center_off), int(fj_centers[j] - center_off))
                for i, j in zip(bi_idx, bj_idx)
            ]
            if subdiv_level > 1 and total_cell_queries + len(to_refine) * 9 > max_cell_queries:
                print(f'CONTOURS SDF: pixel refinement capped (would exceed {max_cell_queries} cell queries)')
                break
            total_cell_queries += len(to_refine) * 9
            for fi0, fj0 in to_refine:
                for di in range(3):
                    for dj in range(3):
                        sfi0, sfj0 = fi0 + di * sub_size, fj0 + dj * sub_size
                        n_ = classify_cell(sfi0 + sub_size // 2, sfj0 + sub_size // 2, sub_radius)
                        fill_block_uniform(sfi0, sfj0, sub_size, n_)
            cur_size, cur_radius = sub_size, sub_radius

        if DEBUG_PRINT_TIMINGS: timers.append((f'grid classify ({RX}x{RY} cells, {res_x}x{res_y} coarse, fine_count={fine_count})', time.perf_counter()))
        # Create solid outlines to trace
        exterior = np.zeros((RX, RY), dtype=bool)
        empty = ~near
        stack = []
        for i in np.flatnonzero(empty[:, 0]):
            i = int(i)
            if not exterior[i, 0]:
                exterior[i, 0] = True
                stack.append((i, 0))
        for i in np.flatnonzero(empty[:, RY - 1]):
            i = int(i)
            if not exterior[i, RY - 1]:
                exterior[i, RY - 1] = True
                stack.append((i, RY - 1))
        for j in np.flatnonzero(empty[0, :]):
            j = int(j)
            if not exterior[0, j]:
                exterior[0, j] = True
                stack.append((0, j))
        for j in np.flatnonzero(empty[RX - 1, :]):
            j = int(j)
            if not exterior[RX - 1, j]:
                exterior[RX - 1, j] = True
                stack.append((RX - 1, j))
        while stack:
            i, j = stack.pop()
            ni = i + 1
            if ni < RX and not exterior[ni, j] and empty[ni, j]:
                exterior[ni, j] = True
                stack.append((ni, j))
            ni = i - 1
            if ni >= 0 and not exterior[ni, j] and empty[ni, j]:
                exterior[ni, j] = True
                stack.append((ni, j))
            nj = j + 1
            if nj < RY and not exterior[i, nj] and empty[i, nj]:
                exterior[i, nj] = True
                stack.append((i, nj))
            nj = j - 1
            if nj >= 0 and not exterior[i, nj] and empty[i, nj]:
                exterior[i, nj] = True
                stack.append((i, nj))
        solid = ~exterior

        # Isolate shape containing the original surface hit
        hi = int(np.clip((hit_local.x - xmin) / fcw, 0, RX - 1))
        hj = int(np.clip((hit_local.y - ymin) / fch, 0, RY - 1))
        if not solid[hi, hj]:
            idx = np.argwhere(solid)
            if idx.size == 0:
                print('CONTOURS SDF: no hit cells found, falling back to Fast')
                return self.process_source_fast(context)
            d2 = (idx[:, 0] - hi) ** 2 + (idx[:, 1] - hj) ** 2
            hi, hj = (int(v) for v in idx[np.argmin(d2)])

        blob = np.zeros((RX, RY), dtype=bool)
        stack = [(hi, hj)]; blob[hi, hj] = True
        touches_border = False
        while stack:
            i, j = stack.pop()
            if i == 0 or j == 0 or i == RX - 1 or j == RY - 1:
                touches_border = True
            ni = i + 1
            if ni < RX and not blob[ni, j] and solid[ni, j]:
                blob[ni, j] = True
                stack.append((ni, j))
            ni = i - 1
            if ni >= 0 and not blob[ni, j] and solid[ni, j]:
                blob[ni, j] = True
                stack.append((ni, j))
            nj = j + 1
            if nj < RY and not blob[i, nj] and solid[i, nj]:
                blob[i, nj] = True
                stack.append((i, nj))
            nj = j - 1
            if nj >= 0 and not blob[i, nj] and solid[i, nj]:
                blob[i, nj] = True
                stack.append((i, nj))

        # Trace the outer boundary as an ordered loop of lattice corners
        blob_pad = np.pad(blob, ((1, 1), (1, 1)), mode='constant', constant_values=False)

        def boundary_dirs(cx, cy):
            # Use a padded blob mask so corner adjacency lookups never need bounds checks.
            px, py = cx + 1, cy + 1
            sw, se = bool(blob_pad[px - 1, py - 1]), bool(blob_pad[px, py - 1])
            nw, ne = bool(blob_pad[px - 1, py]),     bool(blob_pad[px, py])
            ds = []
            if nw != ne: ds.append((0, 1))    # N
            if sw != se: ds.append((0, -1))   # S
            if se != ne: ds.append((1, 0))    # E
            if sw != nw: ds.append((-1, 0))   # W
            return ds
        right_turn = {(0,1):(1,0), (1,0):(0,-1), (0,-1):(-1,0), (-1,0):(0,1)}

        start_flat = np.flatnonzero(blob)
        if start_flat.size == 0:
            print('CONTOURS SDF: empty blob, falling back to Fast')
            return self.process_source_fast(context)
        start = tuple(int(v) for v in np.unravel_index(start_flat[0], blob.shape))  # leftmost-lowest blob cell -> its lower-left corner is on the boundary
        bdirs = boundary_dirs(*start)
        if not bdirs:
            print('CONTOURS SDF: degenerate boundary, falling back to Fast')
            return self.process_source_fast(context)
        cur_dir = (0, 1) if (0, 1) in bdirs else bdirs[0]
        corners = []
        P = start
        max_steps = 4 * (RX + 1) * (RY + 1) + 16
        for _ in range(max_steps):
            corners.append(P)
            P = (P[0] + cur_dir[0], P[1] + cur_dir[1])
            if P == start:
                break
            # Grid edge reached, break so the search doesn't bounce back
            if P[0] == 0 or P[0] == RX or P[1] == 0 or P[1] == RY:
                corners.append(P)
                break
            bdirs = boundary_dirs(*P)
            rev = (-cur_dir[0], -cur_dir[1])
            cands = [d for d in bdirs if d != rev]
            if not cands:
                break
            if len(cands) == 1:
                cur_dir = cands[0]
            else:
                rt = right_turn[cur_dir] # consistent turn keeps to one side
                cur_dir = rt if rt in cands else cands[0]

        if DEBUG_PRINT_TIMINGS: timers.append((f'boundary march ({len(corners)} corners)', time.perf_counter()))
        if DEBUG_CREATE_OBJECTS:
            _raw_corners = list(corners)  # save full staircase before downsample for debug path
            _debug_saved_hide = {}
            for _dname in ('SDF_Debug_Grid', 'SDF_Debug_Path', 'SDF_Debug_Snapped', 'SDF_Debug_Refined'):
                _dobj = bpy.data.objects.get(_dname)
                if _dobj is not None:
                    _debug_saved_hide[_dname] = _dobj.hide_viewport
                    _dobj.hide_viewport = True # Makes sure they don't get snapped to

            def _update_debug_object(name, new_mesh):
                obj = bpy.data.objects.get(name)
                if obj is not None:
                    old_mesh = obj.data
                    obj.data = new_mesh
                    bpy.data.meshes.remove(old_mesh)
                    obj.hide_viewport = _debug_saved_hide.get(name, False)
                else:
                    obj = bpy.data.objects.new(name, new_mesh)
                    bpy.context.scene.collection.objects.link(obj)

        # Downsample the staircase to avoid hundreds of zig-zag steps
        target_count = max(16, 4 * (res_x + res_y))
        if len(corners) > target_count:
            step = len(corners) / target_count
            idx = np.rint(np.arange(target_count, dtype=np.float64) * step).astype(np.int32) % len(corners)
            corners = [corners[int(i)] for i in idx]

        points_world = [
            plane_cut.l2w_point(Vector((xmin + cx * fcw, ymin + cy * fch, 0)))
            for (cx, cy) in corners
        ]

        # Snap each boundary point to the nearest surface point
        plane_normal_world = Vector(plane_cut.l2w_direction(Vector((0, 0, 1))))
        snapped = []
        for pw in points_world:
            p = Vector(pw)
            npt = nearest_point_valid_sources(context, p, world=True, respect_clip_planes=False)
            snapped.append(Vector(npt) if npt is not None else p)
        points_world = snapped

        # drop coincident neighbors as the staircase + snapping can collapse points together
        ts = context.scene.tool_settings
        merge_dist = ts.double_threshold if ts.use_mesh_automerge else 1e-6
        merge_dist_sq = merge_dist * merge_dist
        deduped = []
        for p in points_world:
            if not deduped or (p - deduped[-1]).length_squared > merge_dist_sq:
                deduped.append(p)
        if len(deduped) >= 2 and (deduped[0] - deduped[-1]).length_squared <= merge_dist_sq:
            deduped.pop()
        points_world = deduped
        if len(points_world) < 3:
            print('CONTOURS SDF: too few points after snapping, falling back to Fast')
            return self.process_source_fast(context)

        if DEBUG_PRINT_TIMINGS: timers.append((f'snap ({len(points_world)} pts)', time.perf_counter()))
        if DEBUG_CREATE_OBJECTS:
            # Post-snap / pre-refinement path — every point here should lie exactly on the surface.
            _sm = bpy.data.meshes.new('SDF_Debug_Snapped')
            _bm_s = bmesh.new()
            _sverts = [_bm_s.verts.new(Vector(p)) for p in points_world]
            _bm_s.verts.ensure_lookup_table()
            _n_s = len(_sverts)
            for _k in range(_n_s if not touches_border else _n_s - 1):
                _bm_s.edges.new([_sverts[_k], _sverts[(_k + 1) % _n_s]])
            _bm_s.to_mesh(_sm)
            _bm_s.free()
            _update_debug_object('SDF_Debug_Snapped', _sm)

            _gm = bpy.data.meshes.new('SDF_Debug_Grid')
            _bm = bmesh.new()
            _emitted = np.zeros((RX, RY), dtype=bool)
            for _fi in range(RX):
                for _fj in range(RY):
                    if _emitted[_fi, _fj]: continue
                    _sz = int(block_size[_fi, _fj])
                    # clamp so blocks that reach the grid edge don't go OOB
                    _sz_x = min(_sz, RX - _fi)
                    _sz_y = min(_sz, RY - _fj)
                    _v0 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + _fi           * fcw, ymin + _fj           * fch, 0))))
                    _v1 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + (_fi + _sz_x) * fcw, ymin + _fj           * fch, 0))))
                    _v2 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + (_fi + _sz_x) * fcw, ymin + (_fj + _sz_y) * fch, 0))))
                    _v3 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + _fi           * fcw, ymin + (_fj + _sz_y) * fch, 0))))
                    _bm.faces.new([_v0, _v1, _v2, _v3]).select = bool(solid[_fi + _sz_x // 2, _fj + _sz_y // 2])
                    for _dfi in range(_sz_x):
                        for _dfj in range(_sz_y):
                            _emitted[_fi + _dfi, _fj + _dfj] = True
            _bm.to_mesh(_gm)
            _bm.free()
            _update_debug_object('SDF_Debug_Grid', _gm)

            # Raw traced path mesh: full pre-downsample staircase corners, edges connecting them.
            _raw_pts = [
                plane_cut.l2w_point(Vector((xmin + cx * fcw, ymin + cy * fch, 0)))
                for (cx, cy) in _raw_corners
            ]
            _pm = bpy.data.meshes.new('SDF_Debug_Path')
            _bm2 = bmesh.new()
            _pverts = [_bm2.verts.new(_p) for _p in _raw_pts]
            _bm2.verts.ensure_lookup_table()
            for _k in range(len(_pverts)):
                _bm2.edges.new([_pverts[_k], _pverts[(_k + 1) % len(_pverts)]])
            _bm2.to_mesh(_pm)
            _bm2.free()
            _update_debug_object('SDF_Debug_Path', _pm)
            # ---- END DEBUG ----

        points_world = self.normalize_winding(points_world, plane_cut)

        if self.sdf_refine_steps > 0:
            points_world = self.refine_loop(context, points_world, plane_normal_world, self.sdf_refine_steps)

        if DEBUG_PRINT_TIMINGS: timers.append((f'refinement ({self.sdf_refine_steps} steps)', time.perf_counter()))
        if DEBUG_CREATE_OBJECTS and len(points_world) >= 2:
            _rm = bpy.data.meshes.new('SDF_Debug_Refined')
            _bm_r = bmesh.new()
            _rverts = [_bm_r.verts.new(Vector(p)) for p in points_world]
            _bm_r.verts.ensure_lookup_table()
            _n_r = len(_rverts)
            for _k in range(_n_r if not touches_border else _n_r - 1):
                _bm_r.edges.new([_rverts[_k], _rverts[(_k + 1) % _n_r]])
            _bm_r.to_mesh(_rm)
            _bm_r.free()
            _update_debug_object('SDF_Debug_Refined', _rm)

        points = [ self.matrix_world_inv @ pt_world for pt_world in points_world if pt_world ]
        cyclic = not touches_border

        points, mirror_clipped_loop = self.handle_mirrors(context, points)
        if mirror_clipped_loop: cyclic = False

        if len(points) < 3:
            print('CONTOURS SDF: too few points found to fit plane')
            return False

        plane_fit = Plane.fit_to_points(points)
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        if circle_fit[3] > circle_fit[2]:
            print(
                f'CONTOURS SDF: poor circle fit (sigma={circle_fit[3]:.4f} > radius={circle_fit[2]:.4f}) — ' +
                f'{len(points)} pts, grid={res_x}x{res_y}'
            )

        self.points = points
        self.cyclic = cyclic
        self.plane_fit = plane_fit
        self.circle_fit = circle_fit
        self.path_length = path_length
        self.mirror_clipped_loop = mirror_clipped_loop

        if DEBUG_PRINT_TIMINGS:
            timers.append(('finalize', time.perf_counter()))
            _total = timers[-1][1] - timers[0][1]
            _report = [
                f'{t1-t0:.4f}s  {lbl}'
                for (lbl, t0), (_, t1) in zip(timers[:-1], timers[1:])
            ] + ['--------  ---------------', f'{_total:.4f}s  total']
            term_printer.boxed(*_report, title=f'SDF  grid={res_x}x{res_y}  fine_count={fine_count}  refine={self.sdf_refine_steps}')
        return True

    def process_source_skip(self, context:Context) -> bool:
        plane_cut = self.plane

        pt = self.hit['co_world']
        pt0, pt1 = self.hits[0]['co_world'], self.hits[-1]['co_world']
        dist = ((pt - pt0).length + (pt - pt1).length) / 4 * self.skip_step_size

        init_step = pt1 - pt # pt1 = hits[-1] is the farthest positive hit
        if init_step.length_squared < 1e-12:
            print('CONTOURS SKIP: degenerate initial direction')
            return False
        direction = init_step.normalized()
        pt_start = pt
        dist_pre = 0

        points = [pt]
        has_shrunk = False
        for i in range(10000):
            # print(f'{pt=} {direction=}')
            pt_next = pt + direction * dist
            for _ in range(10):
                snapped = nearest_point_valid_sources(context, pt_next, world=True, respect_clip_planes=True)
                if snapped is None: break
                pt_next = snapped
                pt_next = plane_cut.w2l_point(pt_next)
                pt_next.z = 0
                pt_next = Vector(plane_cut.l2w_point(pt_next))
            dist_next = (pt_next - pt_start).length
            if dist_next < dist_pre:
                has_shrunk = True
            elif has_shrunk:
                if dist_next > dist * 4:
                    has_shrunk = False  # false alarm, still far from start, keep walking
                else:
                    print(f'WRAPPED AFTER {i}!')
                    break
            step = pt_next - pt
            if step.length_squared < 1e-12:
                print(f'CONTOURS SKIP: stalled at step {i}')
                return False
            points += [pt_next]
            direction = step.normalized()
            # print(f'{pt=} {pt_next=} {direction=}')
            pt = pt_next
            dist_pre = dist_next
        else:
            print('CONTOURS SKIP: did not wrap after 10000 steps. Gah!')
            return False

        cyclic = True
        mirror_clipped_loop = False

        ####################################################################################################
        # handle cutting across mirror planes

        points = [self.matrix_world_inv @ pt for pt in points]
        points, mirror_clipped_loop = self.handle_mirrors(context, points)
        if mirror_clipped_loop: cyclic = False

        if len(points) < 3:
            print(f'CONTOURS: TOO FEW POINTS FOUND TO FIT PLANE')
            return False


        ####################################################################################################
        # compute useful statistics about points
        plane_fit = Plane.fit_to_points(points)
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        self.points = points
        self.cyclic = cyclic
        self.plane_fit = plane_fit                      # plane that fits cut points (target space)
        self.circle_fit = circle_fit                    # circle that fits points (plane_fit space)
        self.path_length = path_length                  # length of path of points (target space)
        self.mirror_clipped_loop = mirror_clipped_loop  # did cyclic loop cross mirror plane?

        return True

    def walk_bmesh(self, context:Context, timers:list) -> 'tuple[list[Vector], bool, list[Vector], str] | bool':
        ''' Graph walk using BMesh objects. Returns (points, cyclic, end_pts, timing_title) or False. '''
        plane_cut  = self.plane
        hit_obj    = self.hit['object']
        M          = hit_obj.matrix_world
        hit_bm     = get_object_bmesh(hit_obj)
        face_index = self.hit['face_index']
        if face_index >= len(hit_bm.faces):
            # cache is stale, source mesh changed face count
            get_object_bmesh.cache.pop(hit_obj, None)
            hit_bm = get_object_bmesh(hit_obj)
        if face_index >= len(hit_bm.faces):
            print(f'CONTOURS: face_index {face_index} out of range for mesh with {len(hit_bm.faces)} faces')
            return False
        hit_bmf = hit_bm.faces[face_index]

        # TODO: walk from hit_bmf to find bmf that crosses plane_cut


        ####################################################################################################
        # walk hit object to find all geometry connected to hit_bmf that intersects cut plane
        # note: this will stop at holes that intersect the cut plane (will _not_ walk around them)

        def point_plane_signed_dist(pt : Vector) -> float:
            return plane_cut.signed_distance_to(pt)
        def bmv_plane_signed_dist(bmv:BMVert) -> float:
            return point_plane_signed_dist(M @ bmv.co)
        def bmv_intersect_plane(bmv : BMVert) -> Vector|None:
            if not isclose(bmv_plane_signed_dist(bmv), 0):
                return None
            return M @ bmv.co
        def bme_intersect_plane(bme : BMEdge) -> Vector|None:
            co0, co1 = ((M @ bmv.co) for bmv in bme.verts)
            s0, s1 = point_plane_signed_dist(co0), point_plane_signed_dist(co1)
            if (s0 <= 0 and s1 <= 0) or (s0 >= 0 and s1 >= 0):
                return None
            return co0 + (co1 - co0) * (s0 / (s0 - s1))
        def intersect_plane(bmelem : BMVert|BMEdge) -> Vector|None:
            if isinstance(bmelem, BMVert):
                return bmv_intersect_plane(bmelem)
            if isinstance(bmelem, BMEdge):
                return bme_intersect_plane(bmelem)
            assert False, f'Unexpected type {type(bmelem)} ({bmelem})'

        bmf_graph : dict[BMFace, set[BMFace]] = {}
        bmf_intersections : dict[BMFace, dict[BMVert|BMEdge|BMFace, Vector]] = defaultdict(dict)
        working : set[BMFace] = { hit_bmf }
        while working:
            bmf = working.pop()
            if bmf in bmf_graph:
                # already processed
                continue
            bmf_graph[bmf] = set()
            for bmelem in chain(bmf.verts, bmf.edges):
                co = intersect_plane(bmelem)
                if not co:
                    continue
                bmfs = set(bmelem.link_faces) - { bmf }
                working |= bmfs
                bmf_graph[bmf] |= bmfs
                bmf_intersections[bmf][bmelem] = co
                for bmf_ in bmfs:
                    bmf_intersections[bmf][bmf_] = co
                    bmf_intersections[bmf_][bmf] = co

        if DEBUG_PRINT_TIMINGS: timers.append((f'face graph ({len(bmf_graph)} faces)', time.perf_counter()))
        ####################################################################################################
        # find longest cycle or path in bmf_graph

        def find_cycle_or_path() -> tuple[list[BMFace], bool]:
            longest_path : list[BMFace] = []
            longest_cycle : list[BMFace] = []

            start_bmfs : set[BMFace] = {
                bmf for bmf in bmf_intersections
                if any(
                    (type(bmelem) is BMVert) or (type(bmelem) is BMEdge and len(bmelem.link_faces) == 1)
                    for bmelem in bmf_intersections[bmf]
                )
            }
            if not start_bmfs:
                start_bmfs = set(bmf_graph.keys())

            for start_bmf in start_bmfs:
                working : list[tuple[BMFace, Iterator[dict[BMFace, set[BMFace]]]]] = [(start_bmf, iter(bmf_graph[start_bmf]))]
                touched : set[BMFace] = { start_bmf }
                # limiting the number of finds we search for to prevent really long searches!
                # see https://github.com/CGCookie/retopoflow/issues/1773
                limit_finds = 10

                while working and limit_finds > 0:
                    cur_bmf, cur_iter = working[-1]
                    next_bmf = next(cur_iter, None)

                    if not next_bmf:
                        if len(working) > len(longest_path):
                            # found new longest path!
                            longest_path = [bmf for (bmf, _) in working]

                        working.pop()
                        touched.remove(cur_bmf)
                        limit_finds -= 1
                        continue

                    if next_bmf in touched:
                        # already in path/cycle
                        if next_bmf == start_bmf and len(working) > 2 and len(working) > len(longest_cycle):
                            # found new longest cycle!
                            longest_cycle = [bmf for (bmf, _) in working]
                        continue

                    touched.add(next_bmf)
                    working.append((next_bmf, iter(bmf_graph[next_bmf])))

                # if we found a large enough cycle, we can declare victory!
                # NOTE: we cannot do the same for path, because we might have
                #       started crawling in the middle of the path
                if len(longest_cycle) > 50:
                    break

            is_cyclic = len(longest_cycle) >= len(longest_path) * 0.5
            return (longest_cycle if is_cyclic else longest_path, is_cyclic)

        path, cyclic = find_cycle_or_path()
        if len(path) < 2:
            print(f'CONTOURS ERROR: PATH IS UNEXPECTEDLY TOO SHORT')
            return False

        if DEBUG_PRINT_TIMINGS: timers.append((f'find path/cycle ({len(path)} faces, cyclic={cyclic})', time.perf_counter()))
        ####################################################################################################
        # find points in order

        def add_path_end(bmf:BMFace) -> list[Vector]:
            bmelem = next((
                bmelem for bmelem in bmf_intersections[bmf]
                if type(bmelem) != BMFace and len(bmelem.link_faces) == 1
            ), None)
            return [ self.matrix_world_inv @ bmf_intersections[bmf][bmelem] ] if bmelem else []

        points: list[Vector] = []
        if not cyclic:
            points += add_path_end(path[0])
        points += [
            self.matrix_world_inv @ bmf_intersections[bmf0][bmf1]
            for (bmf0, bmf1) in iter_pairs(path, cyclic)
        ]
        if not cyclic:
            points += add_path_end(path[-1])

        end_pts = add_path_end(path[-1]) if not cyclic else []
        timing_title = f'WALK  faces={len(hit_bm.faces)}  path={len(path)}  cyclic={cyclic}'
        return points, cyclic, end_pts, timing_title

    def walk_accel(self, context:Context, md, face_index:int, timers:list) -> 'tuple[list[Vector], bool, list[Vector], str] | bool':
        ''' Graph walk using SourceMeshCache flat arrays. Returns (points, cyclic, end_pts, timing_title) or False. '''
        plane_cut = self.plane

        ####################################################################################################
        # Lazy per-vertex signed distance and edge intersection
        # Distances are computed on first access and memoised — no global broadcast.

        pn = np.array(plane_cut.n, dtype=np.float64)
        pd = float(plane_cut.d)
        EPS = 1e-6

        dist_cache: dict[int, float] = {}

        def vert_dist(vi: int) -> float:
            d = dist_cache.get(vi)
            if d is None:
                w = md.world[vi]
                d = float(w[0] * pn[0] + w[1] * pn[1] + w[2] * pn[2]) - pd
                dist_cache[vi] = d
            return d

        def edge_isect(ei: int) -> 'tuple[Vector, bool, bool] | None':
            ''' Returns (world_pt, is_vert0_on_plane, is_vert1_on_plane) or None if no crossing.
            "On plane" cases are tracked so callers know to propagate through the vertex. '''
            vi0, vi1 = int(md.edge_verts[ei, 0]), int(md.edge_verts[ei, 1])
            d0, d1   = vert_dist(vi0), vert_dist(vi1)
            on0, on1 = abs(d0) < EPS, abs(d1) < EPS
            if on0:
                return Vector(md.world[vi0]), True, False
            if on1:
                return Vector(md.world[vi1]), False, True
            if (d0 > 0.0) == (d1 > 0.0):
                return None  # same side
            t  = d0 / (d0 - d1)
            w0 = md.world[vi0]
            w1 = md.world[vi1]
            return Vector(w0 + t * (w1 - w0)), False, False

        def edge_face_neighbors(ei: int, exclude_fi: int) -> list[int]:
            cnt = int(md.edge_face_counts[ei])
            if cnt < 2:
                return []
            off = int(md.edge_face_offsets[ei])
            return [int(md.sorted_faces[off + k]) for k in range(cnt)
                    if int(md.sorted_faces[off + k]) != exclude_fi]

        def vert_face_neighbors(vi: int, exclude_fi: int) -> list[int]:
            cnt = int(md.vert_face_counts[vi])
            off = int(md.vert_face_offsets[vi])
            return [int(md.vert_sorted_faces[off + k]) for k in range(cnt)
                    if int(md.vert_sorted_faces[off + k]) != exclude_fi]

        ####################################################################################################
        # BFS — only visits faces the cut actually crosses

        face_graph: dict[int, set[int]] = {}
        face_isect: dict[tuple, Vector] = {}  # (fi, fj|str) → world pt

        working_set: set[int] = {face_index}
        while working_set:
            fi = working_set.pop()
            if fi in face_graph:
                continue
            face_graph[fi] = set()

            s = int(md.face_start[fi])
            t = int(md.face_total[fi])
            face_loop_edges = md.loop_edge[s : s + t]

            visited_verts_on_plane: set[int] = set()

            for ei in face_loop_edges:
                result = edge_isect(int(ei))
                if result is None:
                    continue
                pt, on_v0, on_v1 = result

                if on_v0 or on_v1:
                    # Intersection is exactly at a vertex — propagate through all faces
                    # sharing that vertex (not just the two edge-adjacent faces).
                    vi = int(md.edge_verts[ei, 0] if on_v0 else md.edge_verts[ei, 1])
                    if vi in visited_verts_on_plane:
                        continue
                    visited_verts_on_plane.add(vi)
                    face_isect[(fi, f'vert:{vi}')] = pt
                    for fj in vert_face_neighbors(vi, fi):
                        face_graph[fi].add(fj)
                        face_isect[(fi, fj)] = pt
                        face_isect[(fj, fi)] = pt
                        working_set.add(fj)
                else:
                    # Interpolated crossing — propagate only to the (up to 1) other face
                    # sharing this edge.
                    is_boundary = bool(md.boundary[ei])
                    for fj in edge_face_neighbors(int(ei), fi):
                        face_graph[fi].add(fj)
                        face_isect[(fi, fj)] = pt
                        face_isect[(fj, fi)] = pt
                        working_set.add(fj)
                    if is_boundary:
                        face_isect[(fi, f'boundary:{ei}')] = pt

        if DEBUG_PRINT_TIMINGS: timers.append((f'BFS ({len(face_graph)} faces, {len(dist_cache)} dists)', time.perf_counter()))

        ####################################################################################################
        # find longest cycle or path (same logic as bmesh walk, over int keys)

        def find_cycle_or_path() -> tuple[list[int], bool]:
            longest_path : list[int] = []
            longest_cycle: list[int] = []

            endpoint_faces: set[int] = set()
            for key in face_isect:
                if isinstance(key[0], int) and isinstance(key[1], str):
                    endpoint_faces.add(key[0])
            start_faces = endpoint_faces if endpoint_faces else set(face_graph.keys())

            for start_fi in start_faces:
                stack: list[tuple[int, Iterator]] = [(start_fi, iter(face_graph[start_fi]))]
                touched: set[int] = {start_fi}
                limit_finds = 10
                while stack and limit_finds > 0:
                    cur_fi, cur_iter = stack[-1]
                    next_fi = next(cur_iter, None)
                    if next_fi is None:
                        if len(stack) > len(longest_path):
                            longest_path = [f for (f, _) in stack]
                        stack.pop()
                        touched.discard(cur_fi)
                        limit_finds -= 1
                        continue
                    if next_fi in touched:
                        if next_fi == start_fi and len(stack) > 2 and len(stack) > len(longest_cycle):
                            longest_cycle = [f for (f, _) in stack]
                        continue
                    touched.add(next_fi)
                    stack.append((next_fi, iter(face_graph[next_fi])))
                if len(longest_cycle) > 50:
                    break

            is_cyclic = len(longest_cycle) >= len(longest_path) * 0.5
            return (longest_cycle if is_cyclic else longest_path, is_cyclic)

        path, cyclic = find_cycle_or_path()
        if len(path) < 2:
            print('CONTOURS ERROR: PATH IS UNEXPECTEDLY TOO SHORT')
            return False

        if DEBUG_PRINT_TIMINGS: timers.append((f'find path/cycle ({len(path)} faces, cyclic={cyclic})', time.perf_counter()))

        ####################################################################################################
        # ordered points

        MWI = self.matrix_world_inv

        def add_path_end(fi: int) -> list[Vector]:
            for key, pt in face_isect.items():
                if key[0] == fi and isinstance(key[1], str):
                    return [MWI @ pt]
            return []

        points: list[Vector] = []
        if not cyclic:
            points += add_path_end(path[0])
        for fi0, fi1 in iter_pairs(path, cyclic):
            pt = face_isect.get((fi0, fi1))
            if pt is not None:
                points.append(MWI @ pt)
        if not cyclic:
            points += add_path_end(path[-1])

        end_pts = add_path_end(path[-1]) if not cyclic else []
        timing_title = f'WALK(lazy)  mesh={md.n_faces}  path={len(path)}  dists={len(dist_cache)}  cyclic={cyclic}'
        return points, cyclic, end_pts, timing_title

    def process_source_walk(self, context:Context) -> bool:
        ''' Walk the mesh along the cut one face at a time until finding a boundary or returning to the start. '''
        timers     = [('start', time.perf_counter())] if DEBUG_PRINT_TIMINGS else []
        hit_obj    = self.hit['object']
        face_index = self.hit['face_index']
        skip_accel = False # For debugging / testing timing

        if not skip_accel:
            depsgraph = context.evaluated_depsgraph_get()
            md = SourceMeshCache.get(hit_obj, depsgraph)
            if md is None or face_index >= md.n_faces:
                SourceMeshCache.evict(hit_obj.name)
                md = SourceMeshCache.get(hit_obj, depsgraph)

        if skip_accel or md is None or face_index >= md.n_faces:
            print(f'CONTOURS: SourceMeshCache unavailable for {hit_obj.name!r}, falling back to bmesh walk')
            result = self.walk_bmesh(context, timers)
        else:
            # Warm any other uncached sources in the background while the user is working.
            SourceMeshCache.request_warmup(context)
            result = self.walk_accel(context, md, face_index, timers)

        if result is False: return False

        points, cyclic, end_pts, timing_title = result

        ####################################################################################################
        # subdivide for better circle-fitting
        subdiv = 10
        points = [
            pt
            for (p0, p1) in iter_pairs(points, cyclic)
            for pt in (lerp(i / subdiv, p0, p1) for i in range(subdiv))
        ]
        if not cyclic:
            points += end_pts
        points = [p0 for (p0, p1) in iter_pairs(points, cyclic) if (p0 - p1).length > 0]

        ####################################################################################################
        # handle cutting across mirror planes

        points, mirror_clipped_loop = self.handle_mirrors(context, points)
        if mirror_clipped_loop: cyclic = False

        if len(points) < 3:
            print(f'CONTOURS: TOO FEW POINTS FOUND TO FIT PLANE')
            return False


        ####################################################################################################
        # compute useful statistics about points

        plane_fit = Plane.fit_to_points(points)
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        self.points = points                            # points where cut crosses source (target space)
        self.cyclic = cyclic                            # is cut cyclic (loop) or a strip?
        self.plane_fit = plane_fit                      # plane that fits cut points (target space)
        self.circle_fit = circle_fit                    # circle that fits points (plane_fit space)
        self.path_length = path_length                  # length of path of points (target space)
        self.mirror_clipped_loop = mirror_clipped_loop  # did cyclic loop cross mirror plane?

        if DEBUG_PRINT_TIMINGS:
            timers.append(('finalize', time.perf_counter()))
            _total = timers[-1][1] - timers[0][1]
            _report = [
                f'{t1-t0:.4f}s  {lbl}'
                for (lbl, t0), (_, t1) in zip(timers[:-1], timers[1:])
            ] + ['--------  ---------------', f'{_total:.4f}s  total']
            term_printer.boxed(*_report, title=timing_title)
        return True


    def handle_mirrors(self, context:Context, points:list[Vector]) -> tuple[list[Vector], bool]:
        mirror_clipped_loop = False

        mx, my, mz = has_mirror_x(context), has_mirror_y(context), has_mirror_z(context)

        sel_bmvs = bmops.get_all_selected_bmverts(self.bm)
        if sel_bmvs:
            # use selected geometry to find side
            sx = next(((1 if not mx or bmv.co.x > 0 else -1) for bmv in sel_bmvs if not mx or bmv.co.x != 0), 1)
            sy = next(((1 if not my or bmv.co.y > 0 else -1) for bmv in sel_bmvs if not my or bmv.co.y != 0), 1)
            sz = next(((1 if not mz or bmv.co.z > 0 else -1) for bmv in sel_bmvs if not mz or bmv.co.z != 0), 1)
        else:
            # use cut to determine side
            co = self.hit['co_local']
            sx = 1 if not mx or co.x > 0 else -1
            sy = 1 if not my or co.y > 0 else -1
            sz = 1 if not mz or co.z > 0 else -1

        def correct_x(co:Vector) -> bool:
            return not mx or (1 if co.x > 0 else -1) == sx
        def correct_y(co:Vector) -> bool:
            return not my or (1 if co.y > 0 else -1) == sy
        def correct_z(co:Vector) -> bool:
            return not mz or (1 if co.z > 0 else -1) == sz

        def clip_loop(pts, correct_fn, boundary_fn):
            l = len(pts)
            idx = next((i for i in range(l) if not correct_fn(pts[i]) and correct_fn(pts[(i+1)%l])), 0)
            pts = pts[idx:] + pts[:idx]
            cut = next((i for i in range(1, l) if correct_fn(pts[i-1]) and not correct_fn(pts[i])), None)
            if cut is None:
                if len(pts) < 2: return pts
                return [boundary_fn(pts[0], pts[1])] + pts[1:-1] + [boundary_fn(pts[-1], pts[0])]
            pts = pts[:cut+1]
            if len(pts) < 2: return pts
            return [boundary_fn(pts[0], pts[1])] + pts[1:-2] + [boundary_fn(pts[-2], pts[-1])]

        def clip_path(pts, correct_fn, boundary_fn):
            result = []
            for i, cur in enumerate(pts):
                if i == 0:
                    if correct_fn(cur): result.append(cur)
                else:
                    prev, prev_ok, cur_ok = pts[i-1], correct_fn(pts[i-1]), correct_fn(cur)
                    if not prev_ok and cur_ok:
                        result.append(boundary_fn(prev, cur))
                        result.append(cur)
                    elif prev_ok and not cur_ok:
                        result.append(boundary_fn(prev, cur))
                    elif cur_ok:
                        result.append(cur)
            return result

        for active, correct_fn, boundary_fn in [
            (mx, correct_x, pt_x0),
            (my, correct_y, pt_y0),
            (mz, correct_z, pt_z0),
        ]:
            if not active: continue
            if not any(not correct_fn(p) for p in points): continue
            if not any(correct_fn(p) for p in points): continue
            points = (clip_path if mirror_clipped_loop else clip_loop)(points, correct_fn, boundary_fn)
            mirror_clipped_loop = True

        return (points, mirror_clipped_loop)
