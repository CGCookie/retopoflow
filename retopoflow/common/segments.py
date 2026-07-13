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
from bmesh.types import BMesh, BMFace, BMVert
from bpy.types import Context

from ..common.bmesh import (
    get_bmesh_emesh,
    bme_midpoint,
    bme_length,
    has_mirror_x, has_mirror_y, has_mirror_z, mirror_threshold,
)
from ..common.bmesh_maths import check_bmf_normals
from ..common.curves import find_quadstrip_chains, fit_centerline_spline, ordered_rungs
from ..common.maths import view_forward_direction, xform_direction, lerp, clamp, interp_piecewise
from ..common.raycast import nearest_point_valid_sources, nearest_normal_valid_sources
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
        'arc_fracs',          # list[float]: each spine point's chord fraction
        'corner_indices',     # frozenset[int]: centerline_cos/arc_fracs indices known from topology to bound a sharp corner
        'end0_cos', 'end1_cos',   # (Vector, Vector): the two verts of each end rung, None if cyclic
        'end0_verts', 'end1_verts',  # (BMVert, BMVert) live refs to reuse if welded, None if cyclic
        'strip_faces',        # list[BMFace]: the strip's own faces (to delete)
        'strip_verts',        # list[BMVert]: the strip's verts (delete only if wireless)
        'mirror_axes',        # frozenset[str]: mirror axes to keep new verts pinned onto
        'bend_tolerance_factor', 'sharp_angle',  # curve-fit tunables (match the overlay)
    )

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k))


class SegmentGeometryProvider:
    ''' Strategy the Adjust Segment Count operator calls into: detect an adjustable chain
    in the selection, capture its shape into a SegmentRecipe, and rebuild it at a new count. '''

    def detect(self, context : Context, bm : BMesh):
        ''' Return a lightweight descriptor for the single adjustable chain in
        the selection, or None (nothing usable / ambiguous). '''
        raise NotImplementedError

    def capture(self, context : Context, bm : BMesh, descriptor) -> SegmentRecipe:
        ''' Build the geometry-independent shape recipe from live geometry. '''
        raise NotImplementedError

    def rebuild(self, context : Context, bm : BMesh, recipe : SegmentRecipe, count : int, *, scale_start : float = 1.0, scale_end : float = 1.0) -> list[BMFace]:
        ''' Replace the strip with `count` segments, its rail-to-rail width
        scaled by `scale_start` at its own start lerping to `scale_end` at its
        own end, retaining shape and every external connection. Returns the
        new faces to select. '''
        raise NotImplementedError


# ------------------------------------------------------------------ helpers

def _vert_is_external(v : BMVert, strip_faces : set) -> bool:
    return any(f not in strip_faces for f in v.link_faces)


def _stations_with_reserved_fracs(nstations : int, reserved_fracs : list[float]) -> list[float]:
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

class QuadStripProvider(SegmentGeometryProvider):
    ''' Fit a curve through a strip or ring's rung midpoints and resample to the new count. '''

    MAX_FACES = 1000

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
            if v not in allowed_external and _vert_is_external(v, strip_faces):
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
            # Reuse the previous shape to avoid compounded shrinking
            return SegmentRecipe(
                coupled=False,
                cyclic=cyclic,
                current_count=len(faces),
                centerline_cos=shape_of.centerline_cos,
                half_widths=shape_of.half_widths,
                arc_fracs=shape_of.arc_fracs,
                corner_indices=shape_of.corner_indices,
                end0_cos=shape_of.end0_cos,
                end1_cos=shape_of.end1_cos,
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

        # chord fraction of each rung midpoint along the spine (open: 0..1;
        # cyclic: fraction of the closed loop, last point wraps to start)
        cum = [0.0]
        pts = centerline_cos + ([centerline_cos[0]] if cyclic else [])
        for a, b in zip(pts[:-1], pts[1:]):
            cum.append(cum[-1] + (Vector(a) - Vector(b)).length)
        total = cum[-1] or 1e-6
        arc_fracs = [c / total for c in cum[:len(centerline_cos)]]

        # a corner face at position c is bounded by rungs c and c+1; force both
        # as knots so the fit doesn't round the turn (rebuild() also pins a
        # station at each, keeping the corner's own quad intact)
        corner_indices = frozenset(
            i for c in descriptor['corner_face_positions'] for i in (c, c + 1)
        )

        mirror_axes = set()
        if has_mirror_x(context): mirror_axes.add('x')
        if has_mirror_y(context): mirror_axes.add('y')
        if has_mirror_z(context): mirror_axes.add('z')

        props = context.scene.retopoflow.curve_handles

        return SegmentRecipe(
            coupled=False,
            cyclic=cyclic,
            current_count=len(faces),
            centerline_cos=centerline_cos,
            half_widths=half_widths,
            arc_fracs=arc_fracs,
            corner_indices=corner_indices,
            end0_cos=None if cyclic else (Vector(end0_verts[0].co), Vector(end0_verts[1].co)),
            end1_cos=None if cyclic else (Vector(end1_verts[0].co), Vector(end1_verts[1].co)),
            end0_verts=end0_verts,
            end1_verts=end1_verts,
            strip_faces=strip_faces,
            strip_verts=strip_verts,
            mirror_axes=frozenset(mirror_axes),
            bend_tolerance_factor=props.bend_tolerance_factor,
            sharp_angle=props.curve_corner_angle,
        )

    def is_same_chain(self, cached : SegmentRecipe, fresh : SegmentRecipe) -> bool:
        ''' Is `fresh` the same strip as `cached`? Guards polystrips's undo-collapse from applying one strip's cached shape to a different one. '''
        if cached is None or cached.cyclic != fresh.cyclic:
            return False
        tol = 1e-4
        if not cached.cyclic:
            if cached.end0_cos is None or fresh.end0_cos is None:
                return False
            def close(a, b): return (Vector(a) - Vector(b)).length < tol
            return (
                close(cached.end0_cos[0], fresh.end0_cos[0]) and close(cached.end0_cos[1], fresh.end0_cos[1]) and
                close(cached.end1_cos[0], fresh.end1_cos[0]) and close(cached.end1_cos[1], fresh.end1_cos[1])
            )
        # cyclic has no fixed end reference -- compare a coarse fingerprint
        # (centroid + total spine length) instead
        def centroid(cos): return sum((Vector(c) for c in cos), Vector()) / max(len(cos), 1)
        def total_len(cos): return sum((Vector(a) - Vector(b)).length for a, b in zip(cos, cos[1:] + cos[:1]))
        return (
            (centroid(cached.centerline_cos) - centroid(fresh.centerline_cos)).length < tol and
            abs(total_len(cached.centerline_cos) - total_len(fresh.centerline_cos)) < tol
        )

    def rebuild(self, context, bm, recipe, count, *, scale_start : float = 1.0, scale_end : float = 1.0) -> list[BMFace]:
        cyclic = recipe.cyclic
        Mw     = context.edit_object.matrix_world
        fn     = lambda a, b: (a - b).length

        # Floor the count at one quad per corner, so a low request can't fall back to corner-losing uniform spacing
        corner_fracs = set() if cyclic else {
            recipe.arc_fracs[i] for i in (recipe.corner_indices or ()) if 0 <= i < len(recipe.arc_fracs)
        }
        min_count = max(MIN_COUNT, len(corner_fracs) + 1)
        count = max(min_count, int(count))

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
        total = spline.approximate_totlength_uniform(fn) or 1e-6
        nstations = count + 1 if not cyclic else count
        if cyclic:
            fracs = [j / count for j in range(nstations)]
        else:
            fracs = _stations_with_reserved_fracs(nstations, corner_fracs)
        ts = spline.approximate_ts_at_intervals_uniform([f * total for f in fracs], fn)
        stations = [Vector(spline.eval(t)) for t in ts]
        stations = [
            (nearest_point_valid_sources(context, Mw @ p, world=False, respect_clip_planes=True) or p)
            for p in stations
        ]

        # Per-station frame (mirror PolyStrips' right-vector construction)
        normals = [Direction(nearest_normal_valid_sources(context, Mw @ p, world=False) or Vector((0, 0, 1))) for p in stations]
        forwards, backwards = [], []
        for i in range(nstations):
            if cyclic:
                nxt, prv = stations[(i + 1) % nstations], stations[(i - 1) % nstations]
            else:
                nxt = stations[i + 1] if i + 1 < nstations else stations[i]
                prv = stations[i - 1] if i - 1 >= 0 else stations[i]
            fvec, bvec = nxt - stations[i], prv - stations[i]
            forwards.append(Direction(fvec) if fvec.length > 1e-9 else normals[i])
            if bvec.length > 1e-9:
                backwards.append(Direction(bvec))
            elif fvec.length > 1e-9:
                backwards.append(Direction(-fvec))
            else:
                backwards.append(normals[i])
        rights = [
            (Vector(f.cross(n)).normalized() + Vector(n.cross(b)).normalized())
            for (b, f, n) in zip(backwards, forwards, normals)
        ]
        # Sign-propagate so "rail 0" stays on one side the whole way regardless of each station's cross-product sign
        r_signed = []
        for i, r in enumerate(rights):
            if r.length > 1e-9:
                r = r.normalized()
            elif r_signed:
                r = Vector(r_signed[-1])
            else:
                f = Vector(forwards[i])
                r = f.cross(Vector((0, 0, 1)))
                if r.length < 1e-9:
                    r = f.cross(Vector((0, 1, 0)))
                r = r.normalized()
            if i > 0 and r.dot(r_signed[-1]) < 0:
                r = -r
            r_signed.append(r)

        # Resample the width taper, scaled start -> end along the strip
        widths = [
            interp_piecewise(recipe.arc_fracs, recipe.half_widths, f) * (scale_start if cyclic else lerp(f, scale_start, scale_end))
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
                v0 = for0 if (for0 is not None and for0.is_valid) else _new_vert(slot0_pos)
                v1 = for1 if (for1 is not None and for1.is_valid) else _new_vert(slot1_pos)
                return v0, v1
            return _new_vert(slot0_pos), _new_vert(slot1_pos)

        def _new_vert(co):
            nv = bm.verts.new(co)
            new_verts.append(nv)
            return nv

        rail0, rail1 = [], []
        for i in range(nstations):
            v0, v1 = rail_pair(i)
            rail0.append(v0)
            rail1.append(v1)

        # Snap new verts to the source, then pin any that land on a mirror plane
        mt = mirror_threshold(context)
        for v in new_verts:
            if snapped := nearest_point_valid_sources(context, Mw @ v.co, world=False, respect_clip_planes=True):
                v.co = snapped
            co = v.co
            v.co = Vector((
                0 if 'x' in recipe.mirror_axes and sign_threshold(co.x, mt) == 0 else co.x,
                0 if 'y' in recipe.mirror_axes and sign_threshold(co.y, mt) == 0 else co.y,
                0 if 'z' in recipe.mirror_axes and sign_threshold(co.z, mt) == 0 else co.z,
            ))

        # Create the quads
        new_faces : list[BMFace] = []
        npairs = nstations if cyclic else nstations - 1
        for i in range(npairs):
            j = (i + 1) % nstations
            verts = dedup(rail0[i], rail0[j], rail1[j], rail1[i])
            if len(verts) < 3:
                continue
            try:
                new_faces.append(bm.faces.new(verts))
            except ValueError:
                # Face already exists, probably degenerate overlap on a very tight bend
                continue
        fwd = xform_direction(Mw.inverted_safe(), view_forward_direction(context))
        check_bmf_normals(fwd, new_faces)

        return new_faces


# tried in order, first to recognise the selection wins.
# Shared by every strip related operator so they agree on what's adjustable.
ADJUSTABLE_PROVIDERS = [QuadStripProvider()]


def detect_adjustable_strip(context : Context):
    ''' Find the single adjustable chain in the current selection. Returns
    (bm, em, provider, descriptor) or None. '''
    bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
    for provider in ADJUSTABLE_PROVIDERS:
        descriptor = provider.detect(context, bm)
        if descriptor is not None:
            return bm, em, provider, descriptor
    return None


class EdgeLoopProvider(SegmentGeometryProvider):
    '''
    FUTURE (not implemented). An edge loop is `coupled` (points ARE verts), so
    capture stores centerline_cos = [v.co for v in strip] and rebuild resamples
    the curve to count+1 verts joined by `count` edges, reusing the endpoints --
    no rails or rung recentering. detect via curves.LoopStripChainProvider.
    '''
    pass
