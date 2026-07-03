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
from bmesh.types import BMesh, BMFace, BMEdge, BMVert
from bpy.types import Context

from .curve_chain_providers import find_quadstrip_chains
from ..common.bmesh import (
    bme_midpoint,
    bme_length,
    bmfs_shared_bme,
    quad_bmf_opposite_bme,
    has_mirror_x, has_mirror_y, has_mirror_z, mirror_threshold,
)
from ..common.bmesh_maths import check_bmf_normals
from ..common.curve_fit import fit_centerline_spline, density_to_bend_tolerance
from ..common.maths import view_forward_direction, xform_direction
from ..common.raycast import nearest_point_valid_sources, nearest_normal_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import Direction, sign_threshold
from ...addon_common.common.utils import dedup


# minimum quads a resegmented strip may have -- matches PolyStrips' own floor
# (see polystrips_logic count_mins) so scrolling down can't collapse a strip
# into a single stretched quad
MIN_COUNT = 2


class SegmentRecipe:
    '''
    Everything the rebuild needs to recreate a strip of a chosen segment count
    while keeping its shape. The shape data (centerline_cos, half_widths,
    arc_fracs) is pure Vectors/floats; the live BMesh refs (strip_faces/verts,
    end?_verts) are captured fresh each operator run and consumed within that
    same run -- the Adjust Segment Count operator re-detects and re-captures on
    every scroll (its undo-collapse restores the pristine strip first), so a
    recipe is never held across an undo, and there are no stale-ref hazards.
    '''
    __slots__ = (
        'coupled',            # True = edge loop (points ARE verts); False = quad strip
        'cyclic',             # ring/loop with no end interfaces
        'current_count',      # N segments (quads) the strip currently has
        'centerline_cos',     # list[Vector]: the spine to preserve (rung midpoints)
        'half_widths',        # list[float]: half the rung width at each spine point
        'arc_fracs',          # list[float]: each spine point's chord fraction in [0,1]
        'end0_cos', 'end1_cos',   # (Vector, Vector): the two verts of each end rung; None if cyclic
        'end0_verts', 'end1_verts',  # (BMVert, BMVert) live refs to reuse if welded; None if cyclic
        'strip_faces',        # list[BMFace]: the strip's own faces (to delete)
        'strip_verts',        # list[BMVert]: the strip's verts (delete only if wireless)
        'mirror_axes',        # frozenset[str]: mirror axes to keep new verts pinned onto
        'bend_tolerance_factor', 'sharp_angle',  # curve-fit tunables (match the overlay)
    )

    def __init__(self, **kwargs):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k))


class SegmentGeometryProvider:
    '''
    Strategy the Adjust Segment Count operator calls into. A provider knows how
    to recognise one kind of adjustable geometry in the selection (quad strip
    now; edge loop later -- see EdgeLoopProvider), capture its shape into a
    SegmentRecipe, and rebuild it at a new segment count. The operator never
    branches on the concrete kind -- it just calls detect -> capture -> rebuild.
    '''

    def detect(self, context : Context, bm : BMesh):
        ''' Return a lightweight descriptor for the single adjustable chain in
        the selection, or None (nothing usable / ambiguous). '''
        raise NotImplementedError

    def capture(self, context : Context, bm : BMesh, descriptor) -> SegmentRecipe:
        ''' Build the geometry-independent shape recipe from live geometry. '''
        raise NotImplementedError

    def rebuild(self, context : Context, bm : BMesh, recipe : SegmentRecipe, count : int) -> list[BMFace]:
        ''' Replace the strip with `count` segments, retaining shape and every
        external connection. Returns the new faces to select. '''
        raise NotImplementedError


# ------------------------------------------------------------------ helpers

def _ordered_rungs(faces : list[BMFace], cyclic : bool) -> list[BMEdge]:
    '''
    The perpendicular edges crossing the strip, in order: the boundary cap at
    each open end, plus the edge shared by each consecutive face pair between.
    (Same construction as curve_chain_providers._quad_chain_rung_map, but kept
    as an ordered edge list so we can read per-rung width/position.) For N
    faces: N+1 rungs open, N rungs cyclic.
    '''
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


def _interp(fracs : list[float], values : list[float], f : float) -> float:
    ''' Piecewise-linear lookup of `values` (indexed by the monotonic `fracs`
    in [0,1]) at fraction f -- preserves a strip's width taper under resample. '''
    if f <= fracs[0]:  return values[0]
    if f >= fracs[-1]: return values[-1]
    for i in range(1, len(fracs)):
        if f <= fracs[i]:
            f0, f1 = fracs[i - 1], fracs[i]
            span = f1 - f0
            t = 0.0 if span < 1e-12 else (f - f0) / span
            return values[i - 1] * (1 - t) + values[i] * t
    return values[-1]


def _vert_is_external(v : BMVert, strip_faces : set) -> bool:
    return any(f not in strip_faces for f in v.link_faces)


# ------------------------------------------------------------------ quad strip

class QuadStripProvider(SegmentGeometryProvider):
    '''
    A single selected quad strip (open chain) or ring (cyclic). Its shape is
    the polyline through the rung midpoints -- fit to a curve and resampled to
    the new count. See the module docstring for the topology-safety rule that
    keeps every externally-connected vert/edge locked.
    '''

    MAX_FACES = 1000

    def detect(self, context, bm):
        sel = [f for f in bmops.get_all_selected_bmfaces(bm) if len(f.edges) == 4]
        if not sel or len(sel) > self.MAX_FACES:
            return None

        open_chains, rings = find_quadstrip_chains(sel)
        if len(open_chains) + len(rings) != 1:
            return None  # zero, or more than one, adjustable chain -- ambiguous

        if open_chains:
            seg_faces = open_chains[0]['segment_faces']
            if len(seg_faces) != 1:
                return None  # v1: single topological sub-chain only (no spatial seam)
            faces = list(seg_faces[0])
            cyclic = False
        else:
            faces = list(rings[0])
            cyclic = True

        if len(faces) < 2 or set(faces) != set(sel):
            return None  # chain must cover exactly the selection

        rungs = _ordered_rungs(faces, cyclic)
        expected = len(faces) if cyclic else len(faces) + 1
        if len(rungs) != expected:
            return None  # unexpected topology (branch/non-ladder) -- bail

        # topology-safety lock rule: only the two end-cap rungs may connect to
        # geometry outside the strip. Any other external vert (a rail edge or
        # interior rung tied into other topology, a ring welded along its long
        # side) means the free region isn't a single clean span -- no-op.
        strip_faces = set(faces)
        allowed_external = set() if cyclic else (set(rungs[0].verts) | set(rungs[-1].verts))
        strip_verts = {v for f in faces for v in f.verts}
        for v in strip_verts:
            if v not in allowed_external and _vert_is_external(v, strip_faces):
                return None

        return {'faces': faces, 'cyclic': cyclic, 'rungs': rungs}

    def capture(self, context, bm, descriptor, *, shape_of : SegmentRecipe | None = None) -> SegmentRecipe:
        '''
        `shape_of`, if given, is a previously captured recipe for what a prior
        detect() confirmed (via is_same_chain) is THIS SAME strip -- its shape
        fields (centerline_cos/half_widths/arc_fracs/end?_cos/tunables) are
        reused verbatim instead of re-derived from the current (already-
        resegmented) geometry. This is what keeps a run of repeated adjusts
        from shrinking the strip: without it, each rebuild would fit a curve
        to the PREVIOUS rebuild's rung midpoints, and a fit is generally a
        little shorter than the polyline it's fit through (it smooths corners)
        -- fitting a fit's output, over and over, compounds that shrink every
        single scroll. Reusing the one true original shape means the curve is
        only ever fit once per session; every scroll just resamples it at a
        different count, which does not change its length. Only the LIVE
        handles (strip_faces/strip_verts/end?_verts) are ever taken fresh here
        -- those must track the actual current geometry so deletion/reuse
        targets the real verts, not stale references from a prior capture.
        '''
        faces  = descriptor['faces']
        cyclic = descriptor['cyclic']
        rungs  = descriptor['rungs']

        end0_verts = None if cyclic else (rungs[0].verts[0], rungs[0].verts[1])
        end1_verts = None if cyclic else (rungs[-1].verts[0], rungs[-1].verts[1])
        strip_faces = list(faces)
        strip_verts = list({v for f in faces for v in f.verts})

        if shape_of is not None:
            return SegmentRecipe(
                coupled=False,
                cyclic=cyclic,
                current_count=len(faces),
                centerline_cos=shape_of.centerline_cos,
                half_widths=shape_of.half_widths,
                arc_fracs=shape_of.arc_fracs,
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
            end0_cos=None if cyclic else (Vector(end0_verts[0].co), Vector(end0_verts[1].co)),
            end1_cos=None if cyclic else (Vector(end1_verts[0].co), Vector(end1_verts[1].co)),
            end0_verts=end0_verts,
            end1_verts=end1_verts,
            strip_faces=strip_faces,
            strip_verts=strip_verts,
            mirror_axes=frozenset(mirror_axes),
            bend_tolerance_factor=density_to_bend_tolerance(props.curve_handle_density),
            sharp_angle=props.curve_corner_angle,
        )

    def is_same_chain(self, cached : SegmentRecipe, fresh : SegmentRecipe) -> bool:
        '''
        Coarse fingerprint check: does `fresh` (just detected/captured from the
        live selection) look like the same strip `cached` came from, so its
        shape data is safe to reuse instead of re-deriving it (see capture's
        `shape_of`)? Guards the undo-collapse in polystrips.py against
        accidentally applying one strip's cached shape to a different one --
        e.g. the user adjusts strip A, then selects and scrolls strip B before
        doing anything else RF would otherwise notice as "a new session".
        '''
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

    def rebuild(self, context, bm, recipe, count) -> list[BMFace]:
        count  = max(MIN_COUNT, int(count))
        cyclic = recipe.cyclic
        Mw     = context.edit_object.matrix_world
        fn     = lambda a, b: (a - b).length

        # --- fit the shape-preserving centerline curve
        spline = fit_centerline_spline(
            recipe.centerline_cos, cyclic=cyclic,
            bend_tolerance_factor=recipe.bend_tolerance_factor,
            sharp_angle=recipe.sharp_angle,
        )
        if len(spline) == 0:
            return []

        # --- sample count(+1) arc-length-uniform stations along the curve
        total = spline.approximate_totlength_uniform(fn) or 1e-6
        nstations = count + 1 if not cyclic else count
        fracs = [j / count for j in range(nstations)]
        ts = spline.approximate_ts_at_intervals_uniform([f * total for f in fracs], fn)
        stations = [Vector(spline.eval(t)) for t in ts]
        stations = [
            (nearest_point_valid_sources(context, Mw @ p, world=False, respect_clip_planes=True) or p)
            for p in stations
        ]

        # --- per-station frame (mirror PolyStrips' right-vector construction)
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
        # sign-propagate the right vectors so "rail 0" stays on one side the
        # whole way (no pinch/twist) regardless of per-station cross-product sign
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

        # --- resample the width taper at the new stations
        widths = [_interp(recipe.arc_fracs, recipe.half_widths, f) for f in fracs]

        # --- delete the old strip, keeping every externally-connected vert
        # (delete a strip vert only once it is wireless -- welded end-cap verts
        # still link a neighbor face, so they survive automatically)
        for f in recipe.strip_faces:
            if f.is_valid:
                bm.faces.remove(f)
        for v in recipe.strip_verts:
            if v.is_valid and not v.link_faces:
                bm.verts.remove(v)

        # --- build the two new rails, reusing any surviving (welded) end verts
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

        # --- snap new verts to the source, then pin any that land on a mirror plane
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

        # --- create the quads
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
                # face already exists (degenerate overlap on a very tight bend) -- skip
                continue
        fwd = xform_direction(Mw.inverted_safe(), view_forward_direction(context))
        check_bmf_normals(fwd, new_faces)

        return new_faces


class EdgeLoopProvider(SegmentGeometryProvider):
    '''
    FUTURE (not yet implemented). An edge loop/strip is `coupled` -- its points
    ARE the verts -- so capture stores centerline_cos = [v.co for v in strip]
    with no width_profile/frame, and rebuild fits the same curve, resamples to
    count+1 stations, and creates ONE vert per station joined by `count` edges,
    reusing the two endpoint verts. No rails, no rung recentering; `count`
    counts edges, min 1. detect would collect one boundary strip/cycle via
    curve_chain_providers.LoopStripChainProvider's machinery. Everything else
    (undo-collapse, keymap gating) is provider-agnostic and unchanged.
    '''
    pass
