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
from bmesh.types import BMesh, BMFace, BMVert, BMEdge
from bpy.types import Context

from ..common.bmesh import (
    get_bmesh_emesh,
    bme_midpoint,
    bme_length,
    get_boundary_strips_cycles,
    has_mirror_x, has_mirror_y, has_mirror_z, mirror_threshold,
)
from ..common.bmesh_maths import orient_bmf_normals
from ..common.curves import (
    find_quadstrip_chains, fit_centerline_spline, ordered_rung_rails, ordered_rungs,
    ordered_strip_bmvs, sharp_angle_indices,
)
from ..common.maths import lerp, clamp, interp_direction, interp_piecewise
from ..common.raycast import nearest_point_valid_sources, nearest_normal_valid_sources
from ..common.accel import SourceCache
from ..common.snapping import (
    fold_crease, smoothed_normals, snap_along_normal, source_snap_radius, source_snap_settings,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import Direction, sign_threshold
from ...addon_common.common.utils import dedup


# minimum quads a resegmented strip may have so it can't collapse into a single stretched quad
MIN_COUNT = 2


class SegmentRecipe:
    ''' Everything the rebuild needs to recreate a strip of a chosen segment count while keeping its shape. '''
    __slots__ = (
        'coupled',            # True = edge loop (points ARE verts), False = quad strip
        'cyclic',
        'current_count',
        'centerline_cos',     # list[Vector]: the rung midpoints spine to preserve
        'half_widths',        # list[float]: half the rung width at each spine point
        'rung_dirs',          # list[Vector]: across-the-strip direction, every one off the same rail
        'rung_tangents',      # list[Vector]: centerline tangent, over the same baseline rebuild uses
        'rung_normals',       # list[Vector]: tangent x dir, so a rung is perpendicular to its own normal
        'arc_fracs',          # list[float]: each spine point's chord fraction
        'corner_indices',     # frozenset[int]: centerline_cos/arc_fracs indices known from topology to bound a sharp corner
        'end0_cos', 'end1_cos',   # (Vector, Vector): the two verts of each end rung, None if cyclic
        'end0_verts', 'end1_verts',  # (BMVert, BMVert) live refs to reuse if welded, None if cyclic
                                     # coupled runs have a single vert per end, so both are 1-tuples
        'strip_faces',        # list[BMFace]: the strip's own faces (to delete)
        'strip_edges',        # list[BMEdge]: a coupled run's own edges (to delete), None for a quad strip
        'strip_verts',        # list[BMVert]: the strip's verts (delete only if wireless)
        'mirror_axes',        # frozenset[str]: mirror axes to keep new verts pinned onto
        'bend_tolerance_factor', 'sharp_angle',  # curve-fit tunables (match the overlay)
    )

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k))


# ------------------------------------------------------------------ helpers

def vert_is_external(v : BMVert, strip_faces : set) -> bool:
    return any(f not in strip_faces for f in v.link_faces)


def chord_fracs(cos : list, cyclic : bool) -> list[float]:
    ''' Each point's chord fraction along the polyline. '''
    cumul = [0.0]
    pts = list(cos) + ([cos[0]] if cyclic else [])
    for a, b in zip(pts[:-1], pts[1:]):
        cumul.append(cumul[-1] + (Vector(a) - Vector(b)).length)
    total = cumul[-1] or 1e-6
    return [c / total for c in cumul[:len(cos)]]


def active_mirror_axes(context : Context) -> frozenset[str]:
    axes = set()
    if has_mirror_x(context): axes.add('x')
    if has_mirror_y(context): axes.add('y')
    if has_mirror_z(context): axes.add('z')
    return frozenset(axes)


def pin_to_mirror_planes(context : Context, verts, mirror_axes : frozenset):
    ''' Move any vert that landed within the mirror threshold of an active mirror plane exactly onto it. '''
    if not mirror_axes: return
    mt = mirror_threshold(context)
    for v in verts:
        co = v.co
        v.co = Vector((
            0 if 'x' in mirror_axes and sign_threshold(co.x, mt) == 0 else co.x,
            0 if 'y' in mirror_axes and sign_threshold(co.y, mt) == 0 else co.y,
            0 if 'z' in mirror_axes and sign_threshold(co.z, mt) == 0 else co.z,
        ))


def ts_at_arc_fracs(spline, fracs : list[float]) -> list[float]:
    ''' Spline t for each 0 to 1 fraction of the spline's total arc length. '''
    # not the spline's own approximate_ts_at_intervals_uniform: that snaps to one of
    # `split` discrete ts per segment and never returns t=0, bunching the first sample
    lengths = spline.approximate_lengths_uniform()
    total = sum(lengths) or 1e-6
    last = len(lengths) - 1
    ts = []
    for f in fracs:
        target = clamp(f, 0.0, 1.0) * total
        for i, length in enumerate(lengths):
            if target <= length or i == last:
                local = clamp(target / length, 0.0, 1.0) if length > 1e-9 else 0.0
                ts.append(i + spline[i].approximate_t_at_arc_length_fraction(local))
                break
            target -= length
    return ts


def reserved_arc_fracs(recipe : SegmentRecipe) -> tuple[set[float], set[float]]:
    ''' (crease fractions, all reserved fractions) a rebuild must land a station on,
    so no crease or topology corner is lost at a low count. '''
    # a cyclic chain never turns, so it reserves nothing and stays uniform
    if recipe.cyclic:
        return set(), set()
    sharp_fracs = {
        recipe.arc_fracs[i]
        for i in sharp_angle_indices(recipe.centerline_cos, len(recipe.centerline_cos), False, recipe.sharp_angle)
        if 0 <= i < len(recipe.arc_fracs)
    }
    corner_fracs = {
        recipe.arc_fracs[i] for i in (recipe.corner_indices or ()) if 0 <= i < len(recipe.arc_fracs)
    }
    return sharp_fracs, sharp_fracs | corner_fracs


def min_segment_count(recipe : SegmentRecipe) -> int:
    ''' Lowest count this chain can be rebuilt at without dropping a crease or corner. '''
    # a 2 edge cycle would be a doubled edge, so a coupled ring floors one higher
    base = 3 if (recipe.coupled and recipe.cyclic) else MIN_COUNT
    return max(base, len(reserved_arc_fracs(recipe)[1]) + 1)


def filled_directions(vecs : list[Vector]) -> list[Vector]:
    first = next((v for v in vecs if v.length > 1e-9), None)
    if first is None:
        return []
    out, prev = [], first.normalized()
    for v in vecs:
        if v.length > 1e-9:
            prev = v.normalized()
        out.append(Vector(prev))
    return out


def frame_baseline(points : list[Vector], half_widths : list[float]) -> float:
    ''' Arclength either side of a point to measure its tangent over. '''
    # Scaled to the strip's width so a resampled centerline is measured the same way
    base_half = (sum(half_widths) / len(half_widths)) if half_widths else 0.1
    span = sum((Vector(b) - Vector(a)).length for a, b in zip(points[:-1], points[1:])) or 1e-6
    return min(2 * base_half, 0.25 * span)


def baseline_tangents(points : list[Vector], cyclic : bool, baseline : float) -> list[Vector]:
    ''' Unit tangent at each point, from a chord spanning `baseline` of arclength either side. '''
    n = len(points)
    if n < 2:
        return []
    cumul = [0.0]
    for a, b in zip(points[:-1], points[1:]):
        cumul.append(cumul[-1] + (Vector(b) - Vector(a)).length)
    out = []
    for i in range(n):
        lo = hi = i
        while lo > 0 and cumul[i] - cumul[lo] < baseline: lo -= 1
        while hi < n - 1 and cumul[hi] - cumul[i] < baseline: hi += 1
        if cyclic and lo == hi:
            lo, hi = (i - 1) % n, (i + 1) % n
        out.append(Vector(points[hi]) - Vector(points[lo]))
    return filled_directions(out)


def rung_frames(rungs, centerline_cos : list[Vector], half_widths : list[float], cyclic : bool):
    ''' (dirs, tangents, normals): the strip's frame at each rung. '''
    rails = ordered_rung_rails(rungs, cyclic)
    if rails is None or len(centerline_cos) != len(rungs):
        return [], [], []
    dirs = filled_directions([Vector(bmv0.co) - Vector(bmv1.co) for bmv0, bmv1 in zip(*rails)])
    tangents = baseline_tangents(centerline_cos, cyclic, frame_baseline(centerline_cos, half_widths))
    if not dirs or len(tangents) != len(dirs):
        return [], [], []
    normals = filled_directions([t.cross(r) for t, r in zip(tangents, dirs)])
    if not normals:
        return [], [], []
    return dirs, tangents, normals


def rung_frame_components(dirs : list[Vector], tangents : list[Vector], normals : list[Vector]):
    ''' Each captured rung resolved into its own frame: (across, along).
    `across` is how much of the rung lies square to the centerline,
    `along` how far it leans up or down the strip. '''
    across, along = [], []
    for r, t, n in zip(dirs, tangents, normals):
        b = Vector(n).cross(Vector(t))
        across.append(Vector(r).dot(b.normalized()) if b.length > 1e-9 else 1.0)
        along.append(Vector(r).dot(Vector(t)))
    return across, along


def rung_dir_from_frame(t : Vector, n : Vector, across : float, along : float) -> Vector | None:
    ''' Rebuild a rung direction from an interpolated frame and its two components. '''
    if t is None or n is None:
        return None
    t = Vector(t)
    n = Vector(n) - t * Vector(n).dot(t)   # re-square: interpolating two frames tilts it slightly
    if n.length < 1e-9:
        return None
    b = n.normalized().cross(t)
    if b.length < 1e-9:
        return None
    out = b.normalized() * across + t * along
    return out.normalized() if out.length > 1e-9 else None


def end_center(verts_or_cos) -> Vector:
    ''' Midpoint of an end handle: a rung's two verts, or a coupled run's single one. '''
    pts = [Vector(x.co if hasattr(x, 'co') else x) for x in verts_or_cos]
    return sum(pts, Vector()) / max(len(pts), 1)


def same_end(cos_a, cos_b, tol : float) -> bool:
    ''' Do these two end handles sit on the same spot, in either vert order? '''
    if cos_a is None or cos_b is None or len(cos_a) != len(cos_b):
        return False
    a = [Vector(c) for c in cos_a]
    b = [Vector(c) for c in cos_b]
    if len(a) == 1:
        return (a[0] - b[0]).length < tol
    return (
        ((a[0] - b[0]).length < tol and (a[1] - b[1]).length < tol) or
        ((a[0] - b[1]).length < tol and (a[1] - b[0]).length < tol)
    )


def aligned_end_handles(shape_of : SegmentRecipe, end0, end1):
    ''' (end0, end1) swapped if needed so end0 is the one at the cached shape's start. '''
    cos = shape_of.centerline_cos if shape_of else None
    if not cos or end0 is None or end1 is None:
        return end0, end1
    c0, c1 = Vector(cos[0]), Vector(cos[-1])
    p0, p1 = end_center(end0), end_center(end1)
    straight = (p0 - c0).length + (p1 - c1).length
    flipped  = (p1 - c0).length + (p0 - c1).length
    return (end1, end0) if flipped < straight else (end0, end1)


def same_chain_shape(cached : SegmentRecipe, fresh : SegmentRecipe, *, tol : float = 1e-4) -> bool:
    ''' Are these two recipes the same chain? '''
    if cached is None or cached.cyclic != fresh.cyclic or cached.coupled != fresh.coupled:
        return False
    if not cached.cyclic:
        if cached.end0_cos is None or fresh.end0_cos is None:
            return False
        # the walk's direction and a rung's vert order are both arbitrary, so match
        # the ends as a pair of unordered handles. capture() re-anchors the direction
        return (
            (same_end(cached.end0_cos, fresh.end0_cos, tol) and same_end(cached.end1_cos, fresh.end1_cos, tol)) or
            (same_end(cached.end0_cos, fresh.end1_cos, tol) and same_end(cached.end1_cos, fresh.end0_cos, tol))
        )
    # a cyclic chain has no fixed end to compare, so fingerprint it instead
    def centroid(cos): return sum((Vector(c) for c in cos), Vector()) / max(len(cos), 1)
    def total_len(cos): return sum((Vector(a) - Vector(b)).length for a, b in zip(cos, cos[1:] + cos[:1]))
    return (
        (centroid(cached.centerline_cos) - centroid(fresh.centerline_cos)).length < tol and
        abs(total_len(cached.centerline_cos) - total_len(fresh.centerline_cos)) < tol
    )


def stations_with_reserved_fracs(nstations : int, reserved_fracs : list[float]) -> list[float]:
    ''' `nstations` ascending fractions in [0,1] (first 0, last 1) that always
    land on every `reserved_fracs` value, so resampling only grows/shrinks the
    spans between reserved points (e.g. corners) and never displaces one. '''
    boundaries = sorted({0.0, 1.0} | {clamp(f, 0.0, 1.0) for f in reserved_fracs})
    if nstations < len(boundaries):
        return [i / max(1, nstations - 1) for i in range(nstations)]  # no room to reserve, uniform

    # spread the leftover stations across the spans by length (largest-remainder)
    extra_total = nstations - len(boundaries)
    lengths = [b1 - b0 for b0, b1 in zip(boundaries[:-1], boundaries[1:])]
    total_len = sum(lengths) or 1.0
    raw_shares = [extra_total * l / total_len for l in lengths]
    extra = [int(s) for s in raw_shares]
    leftover = extra_total - sum(extra)
    order = sorted(range(len(lengths)), key=lambda i: raw_shares[i] - extra[i], reverse=True)
    for i in order[:leftover]:
        extra[i] += 1

    fracs = [boundaries[0]]
    for i, (b0, b1) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        n_sub = extra[i] + 1  # sub-intervals within this span
        fracs += [b0 + (b1 - b0) * (k / n_sub) for k in range(1, n_sub + 1)]
    return fracs


# ------------------------------------------------------------------ quad strip

class QuadStripProvider:
    ''' Fit a curve through a strip or ring's rung midpoints and resample to the new count. '''

    MAX_FACES = 1000
    has_width = True  # rail-to-rail width Adjust Strip Width can scale

    def detect(self, context, bm):
        sel = [f for f in bmops.get_all_selected_bmfaces(bm) if len(f.edges) == 4]
        if not sel or len(sel) > self.MAX_FACES:
            return None

        open_chains, rings = find_quadstrip_chains(sel)
        if len(open_chains) + len(rings) != 1:
            return None  # zero, or more than one, adjustable chain - ambiguous

        if open_chains:
            seg_faces = open_chains[0]['segment_faces']
            if len(seg_faces) != 1:
                return None  # v1: single topological sub-chain only (no spatial seam)
            faces = list(seg_faces[0])
            cyclic = False
            # L-corner pivot positions from the chain walk (find_quadstrip_chains);
            # rings never turn, so they get none below
            corner_face_positions = frozenset(open_chains[0]['corner_face_positions'])
        else:
            faces = list(rings[0])
            cyclic = True
            corner_face_positions = frozenset()

        if len(faces) < 2 or set(faces) != set(sel):
            return None  # chain must cover exactly the selection

        rungs = ordered_rungs(faces, cyclic)
        expected = len(faces) if cyclic else len(faces) + 1
        if len(rungs) != expected:
            return None  # unexpected topology (branch/non-ladder) - bail

        # only the two end-cap rungs may connect to geometry outside the strip;
        # any other external vert means the region isn't a clean span - bail
        strip_faces = set(faces)
        allowed_external = set() if cyclic else (set(rungs[0].verts) | set(rungs[-1].verts))
        strip_verts = {v for f in faces for v in f.verts}
        for v in strip_verts:
            if v not in allowed_external and vert_is_external(v, strip_faces):
                return None

        return {'faces': faces, 'cyclic': cyclic, 'rungs': rungs, 'corner_face_positions': corner_face_positions}

    def capture(self, context, bm, descriptor, *, shape_of : SegmentRecipe | None = None) -> SegmentRecipe:
        faces  = descriptor['faces']
        cyclic = descriptor['cyclic']
        rungs  = descriptor['rungs']

        # live BMesh handles are always taken fresh, even when reusing shape_of --
        # deletion/reuse must target the current verts, not stale prior refs
        end0_verts = None if cyclic else (rungs[0].verts[0], rungs[0].verts[1])
        end1_verts = None if cyclic else (rungs[-1].verts[0], rungs[-1].verts[1])
        strip_faces = list(faces)
        strip_verts = list({v for f in faces for v in f.verts})

        if shape_of is not None:
            # the fresh walk may run either way down the chain, so re-anchor the live
            # ends onto the cached centerline before pairing them with its stations
            if not cyclic:
                end0_verts, end1_verts = aligned_end_handles(shape_of, end0_verts, end1_verts)
            # Reuse the previous shape to avoid compounded shrinking
            return SegmentRecipe(
                coupled=False,
                cyclic=cyclic,
                current_count=len(faces),
                centerline_cos=shape_of.centerline_cos,
                half_widths=shape_of.half_widths,
                rung_dirs=shape_of.rung_dirs,
                rung_tangents=shape_of.rung_tangents,
                rung_normals=shape_of.rung_normals,
                arc_fracs=shape_of.arc_fracs,
                corner_indices=shape_of.corner_indices,
                end0_cos=None if cyclic else tuple(Vector(v.co) for v in end0_verts), # read from the live verts
                end1_cos=None if cyclic else tuple(Vector(v.co) for v in end1_verts),
                end0_verts=end0_verts,
                end1_verts=end1_verts,
                strip_faces=strip_faces,
                strip_verts=strip_verts,
                mirror_axes=shape_of.mirror_axes,
                bend_tolerance_factor=shape_of.bend_tolerance_factor,
                sharp_angle=shape_of.sharp_angle,
            )

        centerline_cos = [bme_midpoint(r) for r in rungs]
        half_widths    = [bme_length(r) / 2 for r in rungs]
        arc_fracs      = chord_fracs(centerline_cos, cyclic)
        rung_dirs, rung_tangents, rung_normals = rung_frames(rungs, centerline_cos, half_widths, cyclic)

        # a corner face at position c is bounded by rungs c and c+1; force both
        # as knots so the fit doesn't round the turn (rebuild() also pins a
        # station at each, keeping the corner's own quad intact)
        corner_indices = frozenset(
            i for c in descriptor['corner_face_positions'] for i in (c, c + 1)
        )

        props = context.scene.retopoflow.curve_handles

        return SegmentRecipe(
            coupled=False,
            cyclic=cyclic,
            current_count=len(faces),
            centerline_cos=centerline_cos,
            half_widths=half_widths,
            rung_dirs=rung_dirs,
            rung_tangents=rung_tangents,
            rung_normals=rung_normals,
            arc_fracs=arc_fracs,
            corner_indices=corner_indices,
            end0_cos=None if cyclic else (Vector(end0_verts[0].co), Vector(end0_verts[1].co)),
            end1_cos=None if cyclic else (Vector(end1_verts[0].co), Vector(end1_verts[1].co)),
            end0_verts=end0_verts,
            end1_verts=end1_verts,
            strip_faces=strip_faces,
            strip_verts=strip_verts,
            mirror_axes=active_mirror_axes(context),
            bend_tolerance_factor=props.bend_tolerance_factor,
            sharp_angle=props.curve_corner_angle,
        )

    def rebuild(self, context, bm, recipe, count, *, scale_start : float = 1.0, scale_end : float = 1.0) -> list[BMFace]:
        cyclic = recipe.cyclic
        Mw     = context.edit_object.matrix_world
        Mwi    = Mw.inverted_safe()

        # Preserve sharp bends and sharp corners by pinning a station at each.
        # A rung then lands on every crease at any count.
        # Floor the count so a low request can't drop one. Open chains only, rings stay uniform.
        sharp_fracs, reserved_fracs = reserved_arc_fracs(recipe)
        count = max(min_segment_count(recipe), int(count))

        # source accel + feature radius for pinning fold rungs exactly onto the crease
        source_accel = SourceCache.get(context)
        feature_radius = 0.0
        if source_accel and recipe.half_widths:
            use_fixed, fixed_distance, proximity = source_snap_settings(context)
            scale_avg = sum(Mw.to_scale()) / 3
            mean_full_width = (sum(recipe.half_widths) / len(recipe.half_widths)) * 2 * scale_avg
            feature_radius = source_snap_radius(mean_full_width, use_fixed=use_fixed, fixed_distance=fixed_distance, avg_edge_factor=proximity)

        # Fit the shape-preserving centerline.
        spline = fit_centerline_spline(
            recipe.centerline_cos, cyclic=cyclic,
            bend_tolerance_factor=recipe.bend_tolerance_factor,
            sharp_angle=recipe.sharp_angle,
            forced_sharp_indices=recipe.corner_indices or frozenset(),
        )
        if len(spline) == 0:
            return []

        # Sample arc-length stations. Open chains pin one at each corner's
        # arc fraction so its quad survives any count and rings stay uniform.
        nstations = count + 1 if not cyclic else count
        if cyclic:
            fracs = [j / count for j in range(nstations)]
        else:
            fracs = stations_with_reserved_fracs(nstations, reserved_fracs)
        raw = [Vector(spline.eval(t)) for t in ts_at_arc_fracs(spline, fracs)]
        base_half = (sum(recipe.half_widths) / len(recipe.half_widths)) if recipe.half_widths else 0.1

        # from the unsnapped stations
        normals_raw = [
            Vector(nearest_normal_valid_sources(context, Mw @ p, world=False) or Vector((0, 0, 1)))
            for p in raw
        ]
        # smooth over a full strip width to keep scan noise out of the rung frame
        normals = [Direction(n) for n in smoothed_normals(raw, normals_raw, 4 * base_half)]
        stations = [
            (snap_along_normal(context, p, Mw, Mwi, along_local=Vector(n),
                               max_correction=2 * base_half) or p)
            for p, n in zip(raw, normals)
        ]

        # Pin fold stations onto the source crease and remember the crease direction so the rung can lay along it.
        fold_station_indices = [] if cyclic else [
            i for i, f in enumerate(fracs)
            if 0 < i < nstations - 1 and any(abs(f - sf) < 1e-6 for sf in sharp_fracs)
        ]
        fold_dirs = {}
        for i in fold_station_indices:
            # Raw normals here, never smoothed ones. This intersects the two adjacent
            # face planes to find the crease, and smoothing destroys exactly that signal
            crease = fold_crease(
                stations[i], stations[i - 1], normals_raw[i - 1], stations[i + 1], normals_raw[i + 1],
                Mw, Mwi, source_accel=source_accel, feature_radius=feature_radius,
                max_plane_dist=2 * base_half,
            )
            if crease is not None:
                stations[i], fold_dirs[i] = crease

        # Rung direction, interpolated the captured frame.
        rung_across, rung_along = rung_frame_components(
            recipe.rung_dirs or [], recipe.rung_tangents or [], recipe.rung_normals or [])
        tangents = baseline_tangents(stations, cyclic, frame_baseline(stations, recipe.half_widths))

        r_signed = []
        for i in range(nstations):
            f = fracs[i]
            r = rung_dir_from_frame(
                interp_direction(recipe.arc_fracs, recipe.rung_tangents or [], f, cyclic=cyclic),
                interp_direction(recipe.arc_fracs, recipe.rung_normals  or [], f, cyclic=cyclic),
                interp_piecewise(recipe.arc_fracs, rung_across, f, cyclic=cyclic) if rung_across else 1.0,
                interp_piecewise(recipe.arc_fracs, rung_along,  f, cyclic=cyclic) if rung_along  else 0.0,
            ) if rung_across else None
            if r is None:
                # no captured frame to inherit, so fall back to the local surface frame
                # and keep it locally consistent by sign-propagating along the strip
                n = Vector(normals[i])
                t = tangents[i] if i < len(tangents) else None
                c = Vector(t).cross(n) if t is not None else Vector()
                if c.length > 1e-9:
                    r = c.normalized()
                elif r_signed:
                    r = Vector(r_signed[-1])
                else:
                    c = n.cross(Vector((0, 0, 1)))
                    if c.length < 1e-9:
                        c = n.cross(Vector((0, 1, 0)))
                    r = c.normalized()
                if r_signed and r.dot(r_signed[-1]) < 0:
                    r = -r
            r_signed.append(r)

        # A fold rung lies along the crease so both verts sit on the edge.
        # Sign-matched to the propagated right so the rails don't swap.
        # Skip near-grazing crossings.
        for i, cdir in fold_dirs.items():
            align = cdir.dot(r_signed[i])
            if abs(align) < 0.2: continue
            r_signed[i] = Vector(cdir if align >= 0 else -cdir).normalized()

        # Resample the width taper, scaled start -> end along the strip
        widths = [
            interp_piecewise(recipe.arc_fracs, recipe.half_widths, f, cyclic=cyclic) * (scale_start if cyclic else lerp(f, scale_start, scale_end))
            for f in fracs
        ]

        # Delete the old strip, keeping externally-connected verts
        for f in recipe.strip_faces:
            if f.is_valid:
                bm.faces.remove(f)
        for v in recipe.strip_verts:
            if v.is_valid and not v.link_faces:
                bm.verts.remove(v)

        # Build the two new rails, reusing any welded end verts
        new_verts : list[BMVert] = []
        rail_snaps : list[tuple] = []   # (vert, rung normal, cap) -- welded end verts stay out of it

        def rail_pair(i):
            p, r, w = stations[i], r_signed[i], widths[i]
            slot0_pos, slot1_pos = p + r * w, p - r * w
            cap = None
            if not cyclic and i == 0:
                cap = (recipe.end0_cos, recipe.end0_verts)
            elif not cyclic and i == nstations - 1:
                cap = (recipe.end1_cos, recipe.end1_verts)
            if cap and cap[0] is not None:
                (coA, coB), (vA, vB) = cap
                # assign the two end-cap verts to the +r / -r slots by position
                if (Vector(coA) - p).dot(r) >= 0:
                    for0, for1 = vA, vB
                else:
                    for0, for1 = vB, vA
                v0 = for0 if (for0 is not None and for0.is_valid) else _new_vert(slot0_pos, i)
                v1 = for1 if (for1 is not None and for1.is_valid) else _new_vert(slot1_pos, i)
                return v0, v1
            return _new_vert(slot0_pos, i), _new_vert(slot1_pos, i)

        def _new_vert(co, i):
            nv = bm.verts.new(co)
            new_verts.append(nv)
            rail_snaps.append((nv, Vector(normals[i]), 2 * widths[i]))
            return nv

        rail0, rail1 = [], []
        for i in range(nstations):
            v0, v1 = rail_pair(i)
            rail0.append(v0)
            rail1.append(v1)

        # Snap new verts to the source, then pin any that land on a mirror plane
        for v, n, cap in rail_snaps:
            if snapped := snap_along_normal(context, v.co, Mw, Mwi, along_local=n, max_correction=cap):
                v.co = snapped
        pin_to_mirror_planes(context, new_verts, recipe.mirror_axes)

        # Create the quads
        bmfs : list[BMFace] = []
        npairs = nstations if cyclic else nstations - 1
        for i in range(npairs):
            j = (i + 1) % nstations
            verts = dedup(rail0[i], rail0[j], rail1[j], rail1[i])
            if len(verts) < 3:
                continue
            try:
                bmfs.append(bm.faces.new(verts))
            except ValueError:
                # Face already exists, probably degenerate overlap on a very tight bend
                continue
        orient_bmf_normals(context, bmfs, new_faces=True)

        return bmfs


# ------------------------------------------------------------------ wire edge run

class EdgeLoopProvider:
    ''' Fit a curve through a wire edge run's verts and resample to the new count.
    Its points are its verts, so rebuild just respaces verts along the fitted curve. '''

    MAX_EDGES = 1000
    has_width = False  # a run of edges has no rail-to-rail width to scale

    def detect(self, context, bm):
        if bmops.get_all_selected_bmfaces(bm):
            return None  # selected faces mean this is a strip, not a bare run

        sel = list(bmops.get_all_selected_bmedges(bm))
        if not sel or len(sel) > self.MAX_EDGES:
            return None
        if any(not bme.is_wire for bme in sel):
            return None  # resegmenting an edge that has faces would tear them

        strips, cycles = get_boundary_strips_cycles(sel)
        if len(strips) + len(cycles) != 1:
            return None  # zero, or more than one, adjustable run - ambiguous

        cyclic = bool(cycles)
        edges = (cycles or strips)[0]
        if set(edges) != set(sel):
            return None  # run must cover exactly the selection

        verts = ordered_strip_bmvs(edges, cyclic=cyclic)
        expected = len(edges) if cyclic else len(edges) + 1
        if len(verts) != expected or len(set(verts)) != len(verts):
            return None  # the walk doubled back - branched or otherwise not a simple run

        # only an open run's two end verts may carry anything outside the run;
        # any other connection means this isn't a clean span - bail
        run_edges = set(edges)
        interior = verts if cyclic else verts[1:-1]
        for v in interior:
            if v.link_faces or len(v.link_edges) != 2 or any(e not in run_edges for e in v.link_edges):
                return None

        return {'edges': edges, 'verts': verts, 'cyclic': cyclic}

    def capture(self, context, bm, descriptor, *, shape_of : SegmentRecipe | None = None) -> SegmentRecipe:
        edges  = descriptor['edges']
        verts  = descriptor['verts']
        cyclic = descriptor['cyclic']

        # live BMesh handles are always taken fresh, even when reusing shape_of --
        # deletion/reuse must target the current geometry, not stale prior refs.
        # A coupled run has one vert per end rather than a rung pair.
        end0_verts = None if cyclic else (verts[0],)
        end1_verts = None if cyclic else (verts[-1],)
        # the fresh walk may run either way down the run, so re-anchor the live ends
        # onto the cached centerline before pairing them with its stations
        if shape_of is not None and not cyclic:
            end0_verts, end1_verts = aligned_end_handles(shape_of, end0_verts, end1_verts)

        common = dict(
            coupled=True,
            cyclic=cyclic,
            current_count=len(edges),
            rung_dirs=[], rung_tangents=[], rung_normals=[],  # a run of edges has no rung to orient
            corner_indices=frozenset(),
            end0_verts=end0_verts,
            end1_verts=end1_verts,
            strip_faces=[],
            strip_edges=list(edges),
            strip_verts=list(verts),
        )

        if shape_of is not None:
            # Reuse the previous shape to avoid compounded smoothing
            return SegmentRecipe(
                **common,
                centerline_cos=shape_of.centerline_cos,
                half_widths=shape_of.half_widths,
                arc_fracs=shape_of.arc_fracs,
                # read off the live verts, never carried over from shape_of
                end0_cos=None if cyclic else tuple(Vector(v.co) for v in end0_verts),
                end1_cos=None if cyclic else tuple(Vector(v.co) for v in end1_verts),
                mirror_axes=shape_of.mirror_axes,
                bend_tolerance_factor=shape_of.bend_tolerance_factor,
                sharp_angle=shape_of.sharp_angle,
            )

        centerline_cos = [Vector(v.co) for v in verts]
        props = context.scene.retopoflow.curve_handles

        return SegmentRecipe(
            **common,
            centerline_cos=centerline_cos,
            half_widths=[],
            arc_fracs=chord_fracs(centerline_cos, cyclic),
            end0_cos=None if cyclic else (Vector(verts[0].co),),
            end1_cos=None if cyclic else (Vector(verts[-1].co),),
            mirror_axes=active_mirror_axes(context),
            bend_tolerance_factor=props.bend_tolerance_factor,
            sharp_angle=props.curve_corner_angle,
        )

    def rebuild(self, context, bm, recipe, count, *, scale_start : float = 1.0, scale_end : float = 1.0) -> list[BMEdge]:
        # scale_start/scale_end are width knobs and a run of edges has no width, so they're ignored
        cyclic = recipe.cyclic
        Mw     = context.edit_object.matrix_world

        # Preserve sharp bends by pinning a station at each, so a vert lands on
        # every crease at any count. Floor the count so a low request can't drop one.
        _, reserved_fracs = reserved_arc_fracs(recipe)
        count = max(min_segment_count(recipe), int(count))

        spline = fit_centerline_spline(
            recipe.centerline_cos, cyclic=cyclic,
            bend_tolerance_factor=recipe.bend_tolerance_factor,
            sharp_angle=recipe.sharp_angle,
        )
        if len(spline) == 0:
            return []

        # Sample arc-length stations. Open runs pin one at each crease so it
        # survives any count; cyclic runs stay uniform.
        nstations = count if cyclic else count + 1
        fracs = [j / count for j in range(nstations)] if cyclic else stations_with_reserved_fracs(nstations, reserved_fracs)
        stations = [
            (nearest_point_valid_sources(context, Mw @ p, world=False, respect_clip_planes=True) or p)
            for p in (Vector(spline.eval(t)) for t in ts_at_arc_fracs(spline, fracs))
        ]

        # Delete the old run, keeping verts that still hold other geometry
        for bme in (recipe.strip_edges or []):
            if bme.is_valid:
                bm.edges.remove(bme)
        for v in recipe.strip_verts:
            if v.is_valid and not v.link_edges and not v.link_faces:
                bm.verts.remove(v)

        # Build the new run, reusing the surviving end verts so whatever they
        # were welded to stays welded (they keep their own positions, anchoring the ends)
        new_verts : list[BMVert] = []

        def vert_at(i):
            if not cyclic:
                reuse = recipe.end0_verts if i == 0 else (recipe.end1_verts if i == nstations - 1 else None)
                if reuse and reuse[0] is not None and reuse[0].is_valid:
                    return reuse[0]
            nv = bm.verts.new(stations[i])
            new_verts.append(nv)
            return nv

        run_verts = [vert_at(i) for i in range(nstations)]
        pin_to_mirror_planes(context, new_verts, recipe.mirror_axes)

        bmes : list[BMEdge] = []
        npairs = nstations if cyclic else nstations - 1
        for i in range(npairs):
            j = (i + 1) % nstations
            if run_verts[i] == run_verts[j]:
                continue
            try:
                bmes.append(bm.edges.new((run_verts[i], run_verts[j])))
            except ValueError:
                # Edge already exists, probably a degenerate overlap on a very tight bend
                continue
        return bmes


# Tried in order, first to recognise the selection wins.
# Shared by every strip related operator so they agree on what's adjustable.
# A provider is any object with detect / capture / rebuild and a has_width flag.
ADJUSTABLE_PROVIDERS = [QuadStripProvider(), EdgeLoopProvider()]


def detect_adjustable_strip(context : Context):
    ''' Find the single adjustable chain in the current selection. Returns
    (bm, em, provider, descriptor) or None. '''
    bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
    for provider in ADJUSTABLE_PROVIDERS:
        descriptor = provider.detect(context, bm)
        if descriptor is not None:
            return bm, em, provider, descriptor
    return None
