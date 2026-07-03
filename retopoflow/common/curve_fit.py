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

from mathutils import Vector

from .bmesh_maths import rdp_corner_indices
from .maths import map_range, clamp
from ...addon_common.common.bezier import CubicBezierSpline


def density_to_bend_tolerance(density : float) -> float:
    '''
    Maps the curve_handle_density property (0.1 to 1.0) to the bend tolerance
    factor passed to rdp_corner_indices, geometrically (not linearly)
    interpolated between 0.5 (few control points) and 0.01 (more): tolerance is
    a threshold RDP compares a deviation against multiplicatively, so a
    proportional step in density should be a proportional -- not additive --
    step in tolerance. A linear interpolation would spend most of the slider
    barely changing anything then collapse abruptly near the top; geometric
    interpolation keeps each step across the whole slider similarly responsive.
    '''
    t = map_range(clamp(density, 0.1, 1.0), 0.1, 1.0, 0.0, 1.0)
    lo, hi = 0.5, 0.01  # lo = few control points, hi = more
    return lo * (hi / lo) ** t

# Shared centerline curve-fitting: derive knot placement (sharp-angle + RDP
# corner detection, local-extremum snapping, long-span auto-knots) from a
# polyline of points, and fit a CubicBezierSpline through it. Extracted from
# curve_overlay.RFOperator_Curve_Overlay._build_curve so the curve overlay and
# the Adjust Segment Count operator (rfoperators/adjust_segment_count.py) derive
# knots and fit IDENTICALLY -- see _build_curve for the caching/handle-type
# machinery that wraps derive_centerline_knots there.

# max span between two knots before a backstop auto-knot is inserted, as a
# fraction of the chain's own total length (NOT a vert count): avg edge length
# shrinks under subdivision (same shape, more/shorter edges), which would make
# auto-knot spans trigger for a curve whose geometry hasn't changed at all. 0.6
# was picked by sweeping candidate values against a batch of synthetic bend
# shapes -- it minimized the worst observed handle-to-chord ratio across all
# density settings without inflating knot count.
AUTO_KNOT_MAX_SPAN_FACTOR = 0.6
# min corner spacing, as a fraction of the chain's own total length -- same
# length-based reasoning as AUTO_KNOT_MAX_SPAN_FACTOR (the corner *tolerance*
# itself is user-tunable via bend_tolerance_factor).
CORNER_MIN_SPACING_FACTOR = 0.01


def deflection_angle(cos, k, n, cyclic):
    '''
    Angle between vert k's incoming and outgoing edges, using its immediate
    neighbors only (not RDP or any chord) -- None for an open strip's own
    endpoint (no second arm to measure against) or a degenerate (zero-length)
    neighboring edge, where "angle" isn't a meaningful question.
    '''
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
    ''' Every vert whose own local deflection angle already exceeds
    `sharp_angle`, independent of RDP's chord-deviation test -- see the call
    site in derive_centerline_knots for why that independence matters. '''
    return {
        k for k in range(n)
        if (angle := deflection_angle(cos, k, n, cyclic)) is not None and angle > sharp_angle
    }


def max_dev_index(cos, ka, kb, n):
    '''
    Index in (ka, kb) -- an extended index range where kb may be >= n for a
    cyclic wrap -- whose vert has max perpendicular distance from chord
    cos[ka]-cos[kb]. This is the local "extremum" of that run. Returns None
    if there's no interior point.
    '''
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


def snap_to_local_extrema(cos, knots, n, cyclic, locked, iterations=2):
    knots = sorted(set(knots))
    if len(knots) < 3:
        return knots
    for _ in range(iterations):
        m = len(knots)
        refined = list(knots)
        changed = False
        for idx in range(m):
            k = knots[idx]
            if k in locked:
                continue
            ka = knots[(idx - 1) % m]
            kb = knots[(idx + 1) % m]
            if idx == 0:
                ka -= n
            if idx == m - 1:
                kb += n
            best = max_dev_index(cos, ka, kb, n)
            if best is None:
                continue
            new_k = best % n
            if new_k != k:
                changed = True
            refined[idx] = new_k
        knots = sorted(set(refined))
        if not changed:
            break
    return knots


def arc_length(cos, ka, kb, n):
    return sum((Vector(cos[k % n]) - Vector(cos[(k - 1) % n])).length for k in range(ka + 1, kb + 1))


def split_long_span(cos, ka, kb, n, max_span, tol, result):
    if arc_length(cos, ka, kb, n) <= max_span:
        return
    # place the extra knot at the run's true local extremum, not just its
    # midpoint by vert count, so long bends still get a knot at their apex
    best = max_dev_index(cos, ka, kb, n)
    if best is None:
        return
    # a span this long only earns a backstop knot if it's ALSO measurably not
    # straight -- using the same tolerance RDP itself uses. A perfectly (or
    # nearly) straight run has nothing to gain from extra resolution no matter
    # how long it runs, since a single cubic segment already represents a
    # straight line exactly; without this check, any cornerless straight strip
    # longer than one span would always get split purely because its one
    # segment trivially covers 100% of its own stroke length.
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
    # a fraction of the chain's own total length, not a vert count, so
    # subdividing (same shape, more/shorter edges) doesn't add auto-knots
    # that weren't warranted by the curve's actual geometry
    max_span = max(stroke_length * AUTO_KNOT_MAX_SPAN_FACTOR, 1e-6)
    result = set(knots)
    pairs = list(zip(knots[:-1], knots[1:]))
    if cyclic:
        pairs.append((knots[-1], knots[0] + n))  # closing run wraps past the end
    for ka, kb in pairs:
        split_long_span(cos, ka, kb, n, max_span, tol, result)
    return sorted(result)


def derive_centerline_knots(cos, *, cyclic, bend_tolerance_factor, sharp_angle):
    '''
    Derive knot indices (and the true geometric corner set among them) for a
    polyline `cos`. Sharp verts are found by angle first and forced in as RDP
    seeds so a genuine corner always gets a knot regardless of how loose
    bend_tolerance_factor is; RDP then adds chord-deviation corners, each
    snapped to its local extremum; finally long straight-ish spans get backstop
    auto-knots. Returns (knots, corner_set) where corner_set is the knots that
    landed on a geometrically sharp vert (they get independent/Vector handles).
    '''
    n = len(cos)
    # thresholds below are fractions of the chain's OWN total length, not of an
    # avg per-edge length (which shrinks under subdivision), so the same shape
    # yields the same knots whether it has few or many verts.
    stroke_length = sum(
        (Vector(cos[(i + 1) % n]) - Vector(cos[i])).length
        for i in range(n if cyclic else n - 1)
    )
    tol = max(stroke_length * bend_tolerance_factor, 1e-6)

    sharp_indices = sharp_angle_indices(cos, n, cyclic, sharp_angle)
    seed = ({0, n - 1} if not cyclic else set()) | sharp_indices
    corners = rdp_corner_indices(
        cos, tol,
        seed_indices=seed,
        min_spacing=stroke_length * CORNER_MIN_SPACING_FACTOR,
        force_endpoints=not cyclic,
    )

    # RDP picks each corner by max deviation from a chord that may span far
    # beyond its local bend, so the pick can land beside the true apex. Snap
    # each (non-endpoint, non-sharp) corner to the point of max deviation from
    # the chord between its own immediate neighbors -- the true local extremum.
    locked = ({0, n - 1} if not cyclic else set()) | sharp_indices
    corners = snap_to_local_extrema(cos, corners, n, cyclic, locked)

    # Only verts with a geometrically sharp deflection angle get vector
    # (independent) handles. RDP knots at smooth verts still get G1 handles.
    corner_set = set(corners) & sharp_indices

    knots = list(corners)
    if cyclic and len(knots) < 2:
        # ensure enough knots around a smooth loop to capture its shape
        step = max(1, n // 4)
        knots = sorted(set(knots) | set(range(0, n, step)))

    knots = insert_auto_knots(cos, knots, n, cyclic, stroke_length, tol)
    return knots, corner_set


def fit_centerline_spline(cos, *, cyclic, bend_tolerance_factor, sharp_angle):
    '''
    Fit a CubicBezierSpline through the polyline `cos`, retaining its shape.
    Convenience wrapper over derive_centerline_knots + create_catmull_rom for
    callers (e.g. the Adjust Segment Count operator) that only need the fitted
    curve, not the overlay's caching/handle-type/incremental-refit machinery.
    Open chains force Vector handles at their own endpoints (as the overlay
    does); geometric corners get independent arms; every other knot is smooth.
    '''
    n = len(cos)
    knots, corner_set = derive_centerline_knots(
        cos, cyclic=cyclic,
        bend_tolerance_factor=bend_tolerance_factor,
        sharp_angle=sharp_angle,
    )
    corners_for_fit = set(corner_set) | ({0, n - 1} if not cyclic else set())
    return CubicBezierSpline.create_catmull_rom(
        cos, knots, cyclic=cyclic, corner_indices=corners_for_fit,
    )
