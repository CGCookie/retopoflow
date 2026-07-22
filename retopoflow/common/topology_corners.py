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
from mathutils.geometry import intersect_line_line, intersect_point_line
from bmesh.types import BMesh, BMFace, BMEdge, BMVert

from .bmesh import (
    bmf_midpoint,
    bme_length,
    bmfs_shared_bme,
    quad_bmf_opposite_bme,
    bmvs_shared_bme,
    bmes_shared_bmv,
    bme_other_bmv,
)
from .bmesh_maths import check_bmf_normals
from ...addon_common.common.utils import dedup


def _same_side_vert(v_from : BMVert, rung_to : BMEdge, face : BMFace) -> BMVert | None:
    ''' The vert of `rung_to` joined to `v_from` by an edge of `face`, i.e. the next vert along the same rail. '''
    for v in rung_to.verts:
        e = bmvs_shared_bme(v_from, v)
        if e is not None and e in face.edges:
            return v
    return None


def _strip_rails(faces, rungs, k):
    ''' Build the two rails spanning face k and its downstream neighbor as (rung_in vert, rung_out vert, rung_next vert) triples.
    Returns (rail_a, rail_b, C, downstream) or None if the local topology isn't a clean ladder. '''
    if k + 2 >= len(rungs) or k + 1 >= len(faces):
        return None  # not a clean ladder around the pivot
    C = faces[k]
    downstream = faces[k + 1]
    rung_in, rung_out, rung_next = rungs[k], rungs[k + 1], rungs[k + 2]
    if not (rung_in and rung_out and rung_next):
        return None

    a0, a1 = rung_in.verts
    b0 = _same_side_vert(a0, rung_out, C)
    b1 = _same_side_vert(a1, rung_out, C)
    if b0 is None or b1 is None or b0 == b1:
        return None
    c0 = _same_side_vert(b0, rung_next, downstream)
    c1 = _same_side_vert(b1, rung_next, downstream)
    if c0 is None or c1 is None or c0 == c1:
        return None
    return (a0, b0, c0), (a1, b1, c1), C, downstream


def _hermite_pts(a : Vector, b : Vector, dir_in : Vector | None, dir_out : Vector | None, ts):
    ''' Points along a cubic Hermite from `a` to `b` whose end tangents continue
    the given directions, each scaled to the chord length or chord when missing. '''
    chord = b - a
    L = chord.length
    m0 = dir_in.normalized() * L if (dir_in is not None and dir_in.length > 1e-9) else chord
    m1 = dir_out.normalized() * L if (dir_out is not None and dir_out.length > 1e-9) else chord
    pts = []
    for t in ts:
        t2, t3 = t * t, t * t * t
        pts.append(a * (2*t3 - 3*t2 + 1) + m0 * (t3 - 2*t2 + t) + b * (-2*t3 + 3*t2) + m1 * (t3 - t2))
    return pts


def corner_reroute_is_legal(faces, rungs, k, *, cyclic : bool) -> bool:
    ''' A corner may be inserted/removed at pivot face `k` only when that section is not attached to existing geo. '''
    n = len(faces)
    if cyclic or n < 3:
        return False
    if not (1 <= k <= n - 2):
        return False  # need a face on each side of the pivot
    if k + 2 >= len(rungs):
        return False  # not a clean ladder, unexpected rung count
    strip_faces = set(faces)
    touched = set(faces[k].verts) | set(faces[k + 1].verts)
    for v in touched:
        if any(f not in strip_faces for f in v.link_faces):
            return False
    return True


def insert_corner(bm : BMesh, faces, rungs, k, *, fwd : Vector) -> dict | None:
    ''' Turn the strip into an L at pivot face `faces[k]`, restitching the single downstream face `faces[k+1]`.
    The turn follows the strip's existing geometric bend. Returns {'pivot_vert', 'cap_vert', 'new_face'} or None. '''
    if not corner_reroute_is_legal(faces, rungs, k, cyclic=False):
        return None
    built = _strip_rails(faces, rungs, k)
    if built is None:
        return None
    rail0, rail1, C, downstream = built

    # Pick the pivot rail = the inner (concave) side of the existing bend, using
    # PolyStrips' turn-side test. The inner corner is where the 3-face pivot forms.
    Cc = bmf_midpoint(C)
    incoming = Cc - bmf_midpoint(faces[k - 1])
    outgoing = bmf_midpoint(downstream) - Cc
    C.normal_update()
    side = incoming.cross(C.normal)
    concave = side if side.dot(outgoing) >= 0 else -side
    score0 = concave.dot(rail0[1].co - Cc)
    score1 = concave.dot(rail1[1].co - Cc)
    P, Q = (rail0, rail1) if score0 >= score1 else (rail1, rail0)

    # Elbow quad B_0 = cycle(pivot, junction-outer, other-rail far, pivot-rail far).
    # The rail families cross at a corner. The pivot pairs with its own rail's far vert,
    # and the junction's outer vert (P[1]) pairs with the other rail's far vert (Q[2]).
    new_verts = dedup(P[0], P[1], Q[2], P[2])
    if len(new_verts) != 4:
        return None
    # Both of the removed face's rail edges go loose and only its far rung survives, in B_0
    loose_edges = [bmvs_shared_bme(Q[1], Q[2]), bmvs_shared_bme(P[1], P[2])]

    bm.faces.remove(downstream)
    try:
        nf = bm.faces.new(new_verts)
    except ValueError:
        # degenerate / already-existing face on a tight bend: restore the original
        try: bm.faces.new([P[1], P[2], Q[2], Q[1]])
        except ValueError: pass
        return None
    for e in loose_edges:
        if e is not None and e.is_valid and not e.link_faces:
            bm.edges.remove(e)

    # The corner quad is the crossing of the two arms' extrapolated rail lines.
    # Every corner vert should land on an extrapolated rail line whenever possible.
    pivot_old = P[0].co.copy()
    wA = bme_length(rungs[k])      # arm A width, measured before anything moves
    wB = bme_length(rungs[k + 2])  # arm B width

    def rail_line(v_near, rung_far, face_far, fallback_dir):
        # (point, direction) of one rail extended toward the corner
        if v_near is None:
            return None
        v_far = _same_side_vert(v_near, rung_far, face_far) if (rung_far is not None and face_far is not None) else None
        d = (v_near.co - v_far.co) if v_far is not None else fallback_dir
        return (v_near.co, d) if (d is not None and d.length > 1e-9) else None

    def cross_point(la, lb):
        if la is None or lb is None:
            return None
        hit = intersect_line_line(la[0], la[0] + la[1], lb[0], lb[0] + lb[1])
        if hit is None:
            return None  # parallel rails
        pt = (hit[0] + hit[1]) / 2
        if (pt - pivot_old).length > 4 * max(wA, wB):
            return None  # near-parallel arms send the crossing far away
        return pt

    p_prev = _same_side_vert(P[0], rungs[k - 1], faces[k - 1])
    q_prev = bme_other_bmv(rungs[k - 1], p_prev) if p_prev is not None else None
    rung_m2 = rungs[k - 2] if k >= 2 else None
    face_m2 = faces[k - 2] if k >= 2 else None
    rung_p3 = rungs[k + 3] if k + 3 < len(rungs) else None
    face_p2 = faces[k + 2] if k + 2 < len(faces) else None

    a_in  = rail_line(p_prev, rung_m2, face_m2, (P[0].co - p_prev.co) if p_prev is not None else None)
    a_out = rail_line(q_prev, rung_m2, face_m2, (Q[0].co - q_prev.co) if q_prev is not None else None)
    b_in  = rail_line(P[2], rung_p3, face_p2, pivot_old - P[2].co)
    b_out = rail_line(Q[2], rung_p3, face_p2, Q[0].co - Q[2].co)

    new_pivot = cross_point(a_in, b_in)
    new_junc  = cross_point(a_in, b_out)
    new_rung  = cross_point(a_out, b_in)
    new_cap   = cross_point(a_out, b_out)
    if None not in (new_pivot, new_junc, new_rung, new_cap):
        # Slide the attachment verts inward along the outer rails to make the corner more square
        corner_slide = 0.5
        if corner_slide > 0:
            foot_rung, _ = intersect_point_line(new_pivot, a_out[0], a_out[0] + a_out[1])
            foot_junc, _ = intersect_point_line(new_pivot, b_out[0], b_out[0] + b_out[1])
            new_rung = new_rung.lerp(foot_rung, corner_slide)
            new_junc = new_junc.lerp(foot_junc, corner_slide)
            new_cap = new_rung + (new_junc - new_pivot)
        P[0].co, P[1].co, Q[0].co, Q[1].co = new_pivot, new_junc, new_rung, new_cap
    else:
        # fallback: continue each arm's nearest rung direction from the old pivot
        dirA = (q_prev.co - p_prev.co) if q_prev is not None else (Q[0].co - P[0].co)
        dirB = Q[2].co - P[2].co
        if dirA.length > 1e-9 and dirB.length > 1e-9:
            dirA.normalize()
            dirB.normalize()
            Q[0].co = pivot_old + dirA * wA
            P[1].co = pivot_old + dirB * wB
            Q[1].co = pivot_old + dirA * wA + dirB * wB

    check_bmf_normals(fwd, [nf])
    return {'pivot_vert': P[0], 'cap_vert': Q[1], 'new_face': nf, 'moved_verts': [P[0], P[1], Q[0], Q[1]]}


def remove_corner(bm : BMesh, faces, rungs, k, *, fwd : Vector) -> dict | None:
    ''' Straighten the L-corner at pivot face `faces[k]` back into a plain ladder,
    restitching the downstream neighbor `faces[k+1]`. Inverse of insert_corner.
    Returns {'pivot_vert', 'new_face'} or None if `faces[k]` isn't a corner. '''
    if not corner_reroute_is_legal(faces, rungs, k, cyclic=False):
        return None
    C, E, prev = faces[k], faces[k + 1], faces[k - 1]
    shared_E = bmfs_shared_bme(C, E)
    shared_prev = bmfs_shared_bme(C, prev)
    if not shared_E or not shared_prev:
        return None
    pivot = bmes_shared_bmv(shared_E, shared_prev)
    if pivot is None:
        return None  # neighbors meet across opposite edges -> already straight, not a corner
    elbow = bme_other_bmv(shared_E, pivot)

    # cap = the corner quad's fourth vertex (not on either shared edge)
    used = set(shared_E.verts) | set(shared_prev.verts)
    caps = [v for v in C.verts if v not in used]
    if len(caps) != 1:
        return None
    cap = caps[0]

    rung_next = quad_bmf_opposite_bme(E, shared_E)
    if not rung_next:
        return None
    p_next = _same_side_vert(elbow, rung_next, E)
    if p_next is None:
        return None
    q_next = bme_other_bmv(rung_next, p_next)
    if q_next is None:
        return None

    # Straightened quad = cycle(elbow, far-on-pivot-rail, far-on-elbow-side, cap).
    # The rails un-cross, elbow pairs with q_next and cap with p_next, rebuilding the two ladder rail edges.
    new_verts = dedup(elbow, q_next, p_next, cap)
    if len(new_verts) != 4:
        return None
    # both crossed side edges of the elbow quad go loose, only its far rung survives
    loose_edges = [bmvs_shared_bme(pivot, q_next), bmvs_shared_bme(elbow, p_next)]

    bm.faces.remove(E)
    try:
        nf = bm.faces.new(new_verts)
    except ValueError:
        # restore the original elbow face on failure
        try: bm.faces.new([pivot, elbow, p_next, q_next])
        except ValueError: pass
        return None
    for e in loose_edges:
        if e is not None and e.is_valid and not e.link_faces:
            bm.edges.remove(e)

    # Blend the straightened region back into one smooth path by interpolation.
    # Per rail, the two middle verts land at 1/3 and 2/3 along a Hermite whose end tangents
    # continue that rail's own direction on each arm. Rails here:
    # a1 -> pivot -> elbow -> q_next, and a2 -> outer0 -> cap -> p_next.
    outer0 = bme_other_bmv(shared_prev, pivot)
    a1 = _same_side_vert(pivot, rungs[k - 1], faces[k - 1])
    a2 = _same_side_vert(outer0, rungs[k - 1], faces[k - 1]) if outer0 is not None else None
    rung_m2 = rungs[k - 2] if k >= 2 else None
    face_m2 = faces[k - 2] if k >= 2 else None
    rung_p3 = rungs[k + 3] if k + 3 < len(rungs) else None
    face_p2 = faces[k + 2] if k + 2 < len(faces) else None

    moved_verts = []
    for a, v13, v23, b in ((a1, pivot, elbow, q_next), (a2, outer0, cap, p_next)):
        if a is None or b is None:
            continue
        before_a = _same_side_vert(a, rung_m2, face_m2) if (rung_m2 is not None and face_m2 is not None) else None
        after_b = _same_side_vert(b, rung_p3, face_p2) if (rung_p3 is not None and face_p2 is not None) else None
        dir_in = (a.co - before_a.co) if before_a is not None else None
        dir_out = (after_b.co - b.co) if after_b is not None else None
        v13.co, v23.co = _hermite_pts(a.co, b.co, dir_in, dir_out, (1/3, 2/3))
        moved_verts += [v13, v23]

    check_bmf_normals(fwd, [nf])
    return {'pivot_vert': pivot, 'new_face': nf, 'moved_verts': moved_verts}
