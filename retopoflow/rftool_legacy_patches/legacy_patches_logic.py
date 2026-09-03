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

# Legacy Patches: the RetopoFlow 3 Patches tool on v4 plumbing. Strip detection and the
# I/L/C/rect classification are v3's, kept close to the original so the tool behaves the way
# users remember. The new v4 Patches tool lives in rftool_patches/ and is unrelated.

# pyright: reportUnannotatedClassAttribute = false

import math
from dataclasses import dataclass, fields, replace
from itertools import chain, combinations
from typing import ClassVar

import bpy
import bmesh
import numpy as np
from bmesh.types import BMVert
from bpy.types import Context, Event
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Matrix, Vector

from ..rfglobals import RFGlobals
from ..rfoverlay_base import RFOverlay_Base
from ..preferences import RF_Prefs
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import sign_threshold, point_inside_face_2d
from ...addon_common.common.blender_preferences import mouse_drag
from ..common.bmesh import (
    get_bmesh_emesh, BMVertLayer_Int, mirror_threshold, is_bmvert_corner,
    bmes_shared_bmv, bme_unshared_bmv, bmvs_shared_bme,
)
from ..common.bmesh_maths import orient_bmf_normals, fit_plane_of_verts, compute_n
from ..common.bpy_helper import bpy_ops_retopoflow
from ..common.drawing import Drawing, CC_2D_LINES, CC_2D_POINTS, CC_2D_TRIANGLES
from ..common.operator import RFOperator
from ..common.raycast import (
    nearest_point_valid_sources, nearest_point_normal_valid_sources, raycast_ray_valid_sources,
    iter_all_valid_sources, mouse_from_event, is_point_occluded, raycast_point_valid_sources,
)
from ..common.segments import active_mirror_axes, pin_to_mirror_planes


MAIN_OP_IDNAME = 'retopoflow.legacy_patches'

# Corner overrides live in a per-vert int layer, so they survive depsgraph updates and undo
CORNER_LAYER = 'rf_legacy_patches_corner'
CORNER_AUTO, CORNER_FORCED, CORNER_SMOOTH = 0, 1, 2


@dataclass
class PatchSettings:
    ''' Everything the rebuild reads off the tool, compared as a whole to decide staleness. The
    defaults here are also the defaults of the matching tool properties. '''
    split_angle      : float = math.radians(60)   # deviation from straight that makes a boundary vert a corner
    smooth           : int = 0
    span_insert_mode : str = 'AVERAGE'
    crosses          : int = 0
    span_length      : float = 0.1
    solution         : int = 1      # grid fill: 1 is the best split, higher flips through the rest, wrapping
    offset           : int = 0      # grid fill: rotate the chosen corners this many verts
    twist            : int = 0      # loft: rotate the loop pairing this many verts
    steps            : int = 1      # offset: rows of quads to step outward

PATCH_SETTING_NAMES = tuple(f.name for f in fields(PatchSettings))


##############################################
# geometry helpers

def _angle_deg(d0, d1):
    return math.degrees(math.acos(max(-1.0, min(1.0, d0.dot(d1)))))

def _side2d(pa, pb, p):
    ''' Which side of the screen line pa->pb the point p is on: +1, -1, or 0 on the line. '''
    c = (pb.x - pa.x) * (p.y - pa.y) - (pb.y - pa.y) * (p.x - pa.x)
    return 0 if abs(c) < 1e-6 else (1 if c > 0 else -1)

def _co(pt):
    ''' A patch corner is either an existing BMVert or the coordinate of a vert Fill will create. '''
    return pt.co if isinstance(pt, BMVert) else pt

def _dist2d_point_segment(p, a, b):
    d = b - a
    dd = d.length_squared
    if dd < 1e-12: return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(d) / dd))
    return (p - (a + d * t)).length

def _plane_frame(n, ref):
    ''' Unit vectors (u, w) spanning the plane normal to n, with u along ref. None when degenerate. '''
    u = ref - n * ref.dot(n)
    if u.length_squared < 1e-18: return None
    u.normalize()
    return u, n.cross(u)

def _on_faced_side(bme, co):
    ''' Whether co lies on the same side of a one-faced edge as that face, or None when it cannot
    be told. Measured across the edge, in the plane the face and the point span. '''
    va, vb = bme.verts
    along = vb.co - va.co
    if along.length_squared < 1e-14: return None
    along.normalize()
    mid = (va.co + vb.co) / 2
    to_face = bme.link_faces[0].calc_center_median() - mid
    to_co = co - mid
    to_face -= along * to_face.dot(along)
    to_co -= along * to_co.dot(along)
    if to_face.length_squared < 1e-14 or to_co.length_squared < 1e-14: return None
    return to_face.dot(to_co) > 0

def _quad_area3d(cos):
    # exact for a planar quad, close enough for the nearly planar ones the shape test lets through
    return 0.5 * (cos[2] - cos[0]).cross(cos[3] - cos[1]).length

def _is_convex_2d(pts):
    ''' Whether four screen points in ring order make a convex quad: every turn goes the same way. '''
    signs = { _side2d(pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]) for i in range(4) }
    return 0 not in signs and len(signs) == 1

def _quad_squareness(q):
    ''' How square a quad is, 1.0 for a perfect square, given its corners in ring order. None when
    it is a thin diamond, a long strip, or folded over a crease. Measured in 3D. '''
    MIN_ANGLE, MAX_ANGLE = 30.0, 150.0   # wider than the usual 45-135: retopo quads on a curved surface skew more
    MAX_EDGE_RATIO = 4.0                 # longest side over shortest; catches the long strip the angle test passes
    MAX_WARP = 45.0                      # angle between the triangle normals across a diagonal
    # Skew (a rhombus) is punished harder than aspect (a rectangle): a leaning quad is rarely wanted,
    # a 2:1 quad is ordinary retopo. With the caller dividing area by this, a square beats a 45
    # degree rhombus up to 4x its area and a 2:1 rectangle up to 1.7x.
    SKEW_WEIGHT, ASPECT_WEIGHT = 2.0, 0.75

    sides = [q[(i + 1) % 4] - q[i] for i in range(4)]
    lens = [s.length for s in sides]
    if min(lens) < 1e-9: return None
    if max(lens) / min(lens) > MAX_EDGE_RATIO: return None

    worst_corner = 0.0
    for i in range(4):
        ang = _angle_deg(-sides[i - 1].normalized(), sides[i].normalized())
        if ang < MIN_ANGLE or ang > MAX_ANGLE: return None
        worst_corner = max(worst_corner, abs(ang - 90.0))

    for d in (0, 1):
        n0 = (q[(d + 1) % 4] - q[d]).cross(q[(d + 2) % 4] - q[d])
        n1 = (q[(d + 2) % 4] - q[d]).cross(q[(d + 3) % 4] - q[d])
        if n0.length_squared < 1e-18 or n1.length_squared < 1e-18: return None
        if _angle_deg(n0.normalized(), n1.normalized()) > MAX_WARP: return None

    return (1.0 - worst_corner / 90.0) ** SKEW_WEIGHT * (min(lens) / max(lens)) ** ASPECT_WEIGHT

def _tri_shape_ok(cos):
    ''' Whether three points make a triangle worth filling rather than a sliver. Verts taken from a
    run along a strip are nearly straight, and the triangle across them is all sliver; stepping the
    strip is what was wanted there, so this refuses them. '''
    MIN_ANGLE = 20.0    # a triangle this pointed is a sliver whatever its longest side does
    sides = [cos[(i + 1) % 3] - cos[i] for i in range(3)]
    if min(s.length for s in sides) < 1e-9: return False
    return all(_angle_deg(-sides[i - 1].normalized(), sides[i].normalized()) >= MIN_ANGLE for i in range(3))

def _quad_from_points(pts2d, cos3d, mouse):
    ''' Order four points into a quad and score it. pts2d are screen positions, cos3d world
    positions. Returns (order, score) with order indexing the inputs, lower score better; None
    when the four make no quad worth offering. '''
    HOVER_SLOP = 0.25       # how far outside the outline the cursor may sit, in mean side lengths
    MIN_SQUARENESS = 0.15   # floor, so a barely passing shape cannot lose to a far larger quad on shape alone

    # sorting by angle round the centroid is the one order that does not self-intersect
    centre2d = sum(pts2d, Vector((0, 0))) / 4
    order = sorted(range(4), key=lambda k: math.atan2(pts2d[k].y - centre2d.y, pts2d[k].x - centre2d.x))
    p = [pts2d[k] for k in order]
    if not _is_convex_2d(p): return None

    # four nearby points pair up several ways; the cursor says which quad is meant, as in Maya
    mean_side = sum((p[(i + 1) % 4] - p[i]).length for i in range(4)) / 4
    inside = point_inside_face_2d(mouse, p)
    if not inside:
        if min(_dist2d_point_segment(mouse, p[i], p[(i + 1) % 4]) for i in range(4)) > HOVER_SLOP * mean_side:
            return None

    # shape in 3D, where the quad lives: a quad can look square on screen and be a sliver seen face-on
    squareness = _quad_squareness([cos3d[k] for k in order])
    if squareness is None: return None

    # Screen area over squareness. The smallest quad holding the cursor is usually the one meant,
    # but size alone kept offering rhombuses, and shape alone reached clean across the mesh.
    area = abs(sum(p[i].x * p[(i + 1) % 4].y - p[(i + 1) % 4].x * p[i].y for i in range(4))) / 2
    cost = area / max(squareness, MIN_SQUARENESS)
    dist = sum((pt - mouse).length_squared for pt in p)
    return order, (0 if inside else 1, cost, dist)

def _corner_overlaps_faces(bmv, co_prev, co_next, *, tol_deg=5.0):
    ''' Whether the wedge a new quad would take up at bmv overlaps a face already there. Each face
    round a vert takes a slice of the directions leaving it; so does the new quad. Sharing an edge
    is not an overlap, which is what the tolerance allows. '''
    faces = [ f for f in bmv.link_faces if not f.hide ]
    if not faces: return False
    n = sum((f.normal for f in faces), Vector())
    if n.length_squared < 1e-18: return False
    n.normalize()
    frame = _plane_frame(n, co_prev - bmv.co)
    if frame is None: return False
    u, w = frame

    def angle_of(co):
        d = co - bmv.co
        d = d - n * d.dot(n)
        if d.length_squared < 1e-18: return None
        return math.degrees(math.atan2(d.dot(w), d.dot(u)))

    def wrap(a):
        return (a + 180.0) % 360.0 - 180.0

    def arc(co_a, co_b):
        # (centre, width) of the slice between two directions, the short way round
        a0, a1 = angle_of(co_a), angle_of(co_b)
        if a0 is None or a1 is None: return None
        span = wrap(a1 - a0)
        return wrap(a0 + span / 2), abs(span)

    new_arc = arc(co_prev, co_next)
    if new_arc is None: return False
    for f in faces:
        nbrs = [ bme.other_vert(bmv) for bme in bmv.link_edges if bme in f.edges ]
        if len(nbrs) != 2: continue
        f_arc = arc(nbrs[0].co, nbrs[1].co)
        if f_arc is None: continue
        gap = abs(wrap(new_arc[0] - f_arc[0]))
        if gap < (new_arc[1] + f_arc[1]) / 2 - tol_deg: return True
    return False

def _mesh_juts_into_face(verts, cos, is_existing, *, depth=3):
    ''' Whether an existing vert lies inside the face or an existing edge crosses one of its sides,
    judged in the face's plane. Looks a few edges out from the face's existing corners, plus any
    loose points the candidate cache knows about nearby. '''
    n_pts = len(cos)
    centre = sum(cos, Vector()) / n_pts
    # crossing a quad's diagonals averages out its warp; a triangle is flat, so two of its sides do
    n = (cos[2] - cos[0]).cross(cos[3] - cos[1]) if n_pts == 4 else (cos[1] - cos[0]).cross(cos[2] - cos[0])
    if n.length_squared < 1e-18: return False
    n.normalize()
    frame = _plane_frame(n, cos[1] - cos[0])
    if frame is None: return False
    u, w = frame
    mean_side = sum((cos[(i + 1) % n_pts] - cos[i]).length for i in range(n_pts)) / n_pts
    thick = 0.5 * mean_side    # how far off the plane a vert may be and still count as in it
    eps = 0.02 * mean_side     # verts sitting on a side are the side test's business

    def to2d(co):
        d = co - centre
        return Vector((d.dot(u), d.dot(w))), abs(d.dot(n))
    poly = [ to2d(c)[0] for c in cos ]

    def inside(p):
        if not point_inside_face_2d(p, poly): return False
        return min(_dist2d_point_segment(p, poly[i], poly[(i + 1) % n_pts]) for i in range(n_pts)) > eps

    def crosses(pa, pb):
        for i in range(n_pts):
            qa, qb = poly[i], poly[(i + 1) % n_pts]
            s1, s2 = _side2d(pa, pb, qa), _side2d(pa, pb, qb)
            s3, s4 = _side2d(qa, qb, pa), _side2d(qa, qb, pb)
            if s1 and s2 and s3 and s4 and s1 != s2 and s3 != s4: return True
        return False

    corners = { v for v, existing in zip(verts, is_existing) if existing }
    seen, frontier = set(corners), list(corners)
    for _ in range(depth):
        nxt = []
        for v in frontier:
            for bme in v.link_edges:
                o = bme.other_vert(v)
                if o in seen: continue
                seen.add(o)
                nxt.append(o)
        frontier = nxt
    near = seen - corners
    for v in near:
        p, h = to2d(v.co)
        if h <= thick and inside(p): return True
    for v in near:
        pa, ha = to2d(v.co)
        if ha > thick: continue
        for bme in v.link_edges:
            o = bme.other_vert(v)
            if o in corners: continue
            pb, hb = to2d(o.co)
            if hb <= thick and crosses(pa, pb): return True

    L = LegacyPatches_Logic
    if L.cand_cos is not None and len(L.cand_cos):
        lo = np.array([min(c[k] for c in cos) - thick for k in range(3)])
        hi = np.array([max(c[k] for c in cos) + thick for k in range(3)])
        box = np.flatnonzero(np.all((L.cand_cos >= lo) & (L.cand_cos <= hi), axis=1))
        corner_idx = { v.index for v in corners }
        for k in box:
            if L.cand_idx[k] in corner_idx: continue
            p, h = to2d(Vector(L.cand_cos[k]))
            if h <= thick and inside(p): return True
    return False

def _face_is_placeable(bm, verts):
    ''' Whether a face on these corners, in this order, leaves the mesh making sense: no third face
    on an edge, no face already there, none laid over existing geometry, no diagonal that is really
    an edge of the mesh. A corner may be a plain Vector for a vert the fill will create; it has no
    history, so only the tests about existing corners apply to it. Triangles and quads. '''
    SIDE_OVER_VERT_ANGLE = 120.0    # a new side whose ends share a neighbour this straight runs over that neighbour

    n = len(verts)
    if len({ id(v) for v in verts }) != n: return False
    is_existing = [ isinstance(v, BMVert) for v in verts ]
    if all(is_existing) and bm.faces.get(verts): return False

    cos = [ _co(v) for v in verts ]
    centre = sum(cos, Vector()) / n
    for i in range(n):
        j = (i + 1) % n
        if not (is_existing[i] and is_existing[j]): continue
        va, vb = verts[i], verts[j]
        bme = bmvs_shared_bme(va, vb)
        if bme is not None:
            if len(bme.link_faces) >= 2: return False
            if bme.link_faces and _on_faced_side(bme, centre): return False
            continue
        # this side would be created: refuse it when it runs straight over a shared neighbour, which
        # means the face skipped a row of the mesh
        for w in { e.other_vert(va) for e in va.link_edges } & { e.other_vert(vb) for e in vb.link_edges }:
            if w in verts: continue
            d0, d1 = va.co - w.co, vb.co - w.co
            if d0.length_squared < 1e-14 or d1.length_squared < 1e-14: continue
            if _angle_deg(d0.normalized(), d1.normalized()) >= SIDE_OVER_VERT_ANGLE: return False

    # a faced diagonal means the face straddles a fold: the pieces either side are the real surface
    for a, b in combinations(range(n), 2):
        if (b - a) % n in (1, n - 1): continue      # a side, not a diagonal (a triangle has none)
        if is_existing[a] and is_existing[b]:
            bme = bmvs_shared_bme(verts[a], verts[b])
            if bme is not None and bme.link_faces: return False

    # two corners on one face without an edge of that face joining them means the face cuts across it
    for a, b in combinations(range(n), 2):
        if not (is_existing[a] and is_existing[b]): continue
        va, vb = verts[a], verts[b]
        for bmf in set(va.link_faces) & set(vb.link_faces):
            if not any(set(bme.verts) == {va, vb} for bme in bmf.edges): return False

    for i in range(n):
        if is_existing[i] and _corner_overlaps_faces(verts[i], cos[i - 1], cos[(i + 1) % n]): return False

    return not _mesh_juts_into_face(verts, cos, is_existing)

def _complete_quad(bm, known, slots, *, min_squareness):
    ''' Finish a quad from existing verts. `known` are the corners already decided, in ring order;
    `slots` holds candidate verts for each open corner, in ring order after the known ones. Every
    assignment is judged the way the cursor pick judges quads. Returns (verts, cost) or None. '''
    n_open = len(slots)
    if n_open not in (1, 2) or len(known) + n_open != 4: return None
    best = None

    def consider(verts):
        nonlocal best
        cos = [ _co(v) for v in verts ]
        squareness = _quad_squareness(cos)
        if squareness is None or squareness < min_squareness: return
        if not _face_is_placeable(bm, verts): return
        cost = _quad_area3d(cos) / squareness
        if best is None or cost < best[1]: best = (list(verts), cost)

    if n_open == 1:
        for w in slots[0]:
            if w not in known: consider(known + [w])
    else:
        for w0 in slots[0]:
            if w0 in known: continue
            for w1 in slots[1]:
                if w1 not in known and w1 is not w0: consider(known + [w0, w1])
    return best

def _grid_topology(verts, l0, l1, *, cyclic_i=False):
    ''' Faces of an l0 x l1 grid of verts (row-major, k = i * l1 + j) and the edges the preview
    draws: every grid edge not already in the mesh. '''
    def is_new(a, b):
        va, vb = verts[a], verts[b]
        if not (isinstance(va, BMVert) and isinstance(vb, BMVert)): return True
        return bmvs_shared_bme(va, vb) is None
    rows = range(l0) if cyclic_i else range(l0 - 1)
    nxt = lambda i: (i + 1) % l0
    faces = [ (i*l1+j, nxt(i)*l1+j, nxt(i)*l1+j+1, i*l1+j+1) for i in rows for j in range(l1 - 1) ]
    edges = [ (i*l1+j, i*l1+j+1) for i in range(l0) for j in range(l1 - 1) if is_new(i*l1+j, i*l1+j+1) ]
    edges += [ (i*l1+j, nxt(i)*l1+j) for i in rows for j in range(l1) if is_new(i*l1+j, nxt(i)*l1+j) ]
    return edges, faces

def _smooth_path(pts, passes=2):
    ''' Lightly smoothed copy of a polyline, endpoints kept. Display only. '''
    out = list(pts)
    for _ in range(passes):
        if len(out) < 3: break
        out = [out[0]] + [ ((out[i - 1][0] + 2 * out[i][0] + out[i + 1][0]) / 4,
                            (out[i - 1][1] + 2 * out[i][1] + out[i + 1][1]) / 4)
                           for i in range(1, len(out) - 1) ] + [out[-1]]
    return out


##############################################
# curved-surface helpers: fit a sphere to two points and their normals, then move along it

def _fit_sphere_centre(p_a, n_a, p_b, n_b):
    ''' Centre of the sphere through two points with the given normals, or None when the surface
    between them is flat. Same fit Relax uses for Interpolate Loops; the radius is signed. '''
    d = n_b - n_a
    dd = d.dot(d)
    if dd < 1e-10: return None
    r = (p_b - p_a).dot(d) / dd
    if abs(r) < 1e-10: return None
    return p_a - n_a * r

def _arc_rotation(centre, p_a, p_b, t=1.0):
    ''' Rotation about centre carrying p_a a fraction t of the way to p_b, or None when collinear. '''
    va, vb = p_a - centre, p_b - centre
    axis = va.cross(vb)
    if axis.length_squared < 1e-14 or va.length_squared < 1e-14 or vb.length_squared < 1e-14: return None
    return Matrix.Rotation(va.angle(vb) * t, 3, axis.normalized())

def _bend_along(p_a, n_a, p_b, n_b, x):
    ''' Move x the way the surface carries p_a to p_b: the parallelogram completion bent to the
    fitted sphere, or the plain translation when flat. '''
    centre = _fit_sphere_centre(p_a, n_a, p_b, n_b) if (n_a is not None and n_b is not None) else None
    rot = _arc_rotation(centre, p_a, p_b) if centre is not None else None
    if rot is None: return x + (p_b - p_a)
    return centre + rot @ (x - centre)

def _arc_between(p_a, n_a, p_b, n_b, fracs):
    ''' (point, normal) at each fraction along the arc from p_a to p_b on the fitted sphere, or
    along the straight line with lerped normals when flat. '''
    centre = _fit_sphere_centre(p_a, n_a, p_b, n_b) if (n_a is not None and n_b is not None) else None
    out = []
    for t in fracs:
        rot = _arc_rotation(centre, p_a, p_b, t) if centre is not None else None
        if rot is None:
            n = None
            if n_a is not None and n_b is not None:
                n = n_a.lerp(n_b, t)
                n = n.normalized() if n.length_squared > 1e-12 else None
            out.append((p_a.lerp(p_b, t), n))
        else:
            out.append((centre + rot @ (p_a - centre), (rot @ n_a).normalized()))
    return out

def _bezier(p0, p1, p2, p3, t):
    u = 1.0 - t
    return p0 * (u*u*u) + p1 * (3*u*u*t) + p2 * (3*u*t*t) + p3 * (t*t*t)

def _mirror_curve(p0, t0, p3):
    ''' Control points of a cubic leaving p0 along t0 and arriving at p3 along t0 mirrored across
    the chord, so the curve bows evenly and never curls. Returns (p1, p2, arrival direction). '''
    HANDLE_AT_START, HANDLE_AT_END = 0.25, 0.15     # fractions of the chord; shorter at the end so two sides meeting there do not pinch
    chord = p3 - p0
    length = chord.length
    if length < 1e-9: return p0, p3, t0
    c = chord / length
    t3 = c * (2.0 * t0.dot(c)) - t0
    t3 = t3.normalized() if t3.length_squared > 1e-12 else c
    return p0 + t0 * (HANDLE_AT_START * length), p3 - t3 * (HANDLE_AT_END * length), t3

def _cumulative_fracs(cos):
    ''' Fraction of the polyline length reached at each point, 0 at the first and 1 at the last. '''
    seg = [ (cos[k + 1] - cos[k]).length for k in range(len(cos) - 1) ]
    total = sum(seg) or 1.0
    out, acc = [0.0], 0.0
    for l in seg:
        acc += l
        out.append(acc / total)
    out[-1] = 1.0
    return out

def _turn_sharpness(cos):
    ''' How sharply a closed loop turns at each vert: 0 straight, 2 doubled back. '''
    n = len(cos)
    out = []
    for i in range(n):
        d0 = (cos[i] - cos[(i - 1) % n]).normalized()
        d1 = (cos[(i + 1) % n] - cos[i]).normalized()
        out.append(1.0 - max(-1.0, min(1.0, d0.dot(d1))))
    return out

def _grid_snap_noise(cos, raws, l0, l1, *, cyclic_i=False):
    ''' Mean disagreement between neighbouring verts' snap displacements, in quad widths. A patch
    draped over a curved surface moves far but moves together (a steep dome reads ~0.25); a patch
    whose verts each find their own piece of the source reads 1.0 or more. '''
    disp = { k: cos[k] - raws[k] for k in range(len(cos)) if raws[k] is not None }
    if len(disp) < 2: return 0.0
    steps = [ (cos[i*l1+j] - cos[i*l1+j+1]).length for i in range(l0) for j in range(l1 - 1) ]
    spacing = (sum(steps) / len(steps)) if steps else 0.0
    if spacing <= 1e-9: return 0.0
    diffs = []
    for i in range(l0):
        for j in range(l1):
            k = i * l1 + j
            if k not in disp: continue
            ni = (i + 1) % l0 if cyclic_i else i + 1
            for (ai, aj) in ((ni, j), (i, j + 1)):
                if ai >= l0 or aj >= l1: continue
                ak = ai * l1 + aj
                if ak in disp: diffs.append((disp[k] - disp[ak]).length)
    if not diffs: return 0.0
    return (sum(diffs) / len(diffs)) / spacing


@dataclass
class Previz:
    kind     : str          # 'rect' | 'L' | 'C' | 'I' | 'loft' | 'grid' | 'bridge' | 'offset' | 'corner' | 'nearest' | 'quad' | 'triangle'
    vert_idx : list         # bm vert index for existing verts, None for verts Fill will create
    vert_co  : list         # local-space coords (copies for existing verts)
    edges    : list         # index pairs into vert_co, new edges only (the dashed preview)
    faces    : list         # index tuples into vert_co
    open_idx : tuple = ()   # new verts on the patch boundary, i.e. on a side being created
    row_idx  : tuple = ()   # offset step: the row to leave selected after Fill, so the next step is offered at once
    hover    : bool = False # built from the cursor with nothing selected; Fill then leaves nothing selected


class LegacyPatches_Logic:
    ''' Rebuilds the patch preview from the selection and cursor, draws it, and fills it. The state
    is class-level because there is no running main operator: the overlay, the fill operator and
    the F quick switch all share the one preview. '''

    depsgraph_version : ClassVar[int] = -1
    last_settings     : ClassVar[PatchSettings | None] = None
    dirty             : ClassVar[bool] = True

    # Products of the last rebuild. Plain data only: BMesh element refs die on every depsgraph update.
    boundary_verts : ClassVar[dict[int, Vector]] = {}      # vert index -> local co, for corner picking
    corner_indices : ClassVar[set[int]] = set()
    labels         : ClassVar[list[tuple[str, list[Vector]]]] = []
    previz         : ClassVar[list[Previz]] = []
    has_bridge     : ClassVar[bool] = False
    has_loft       : ClassVar[bool] = False
    has_grid       : ClassVar[bool] = False
    has_offset     : ClassVar[bool] = False
    has_quad       : ClassVar[bool] = False                # a single quad: cursor, four verts, or a corner
    has_manual_corners : ClassVar[bool] = False            # any corner override on the selected boundary
    wire_runs      : ClassVar[list] = []                   # (chord co0, chord co1, mouse side) per wire offset, watched by track_mouse
    grid_last      : ClassVar[tuple[int, int] | None] = None   # (span, offset) used
    grid_ranked    : ClassVar[list] = []                       # (span, offset) of every split, best first
    grid_sig       : ClassVar[tuple | None] = None             # selection the solutions were ranked for
    loops_last     : ClassVar[int | None] = None               # loops the last bridge or loft used
    error          : ClassVar[str | None] = None

    # Property writes that have not landed yet. The rebuild runs in a draw callback, which cannot
    # write properties, so writes go through a timer and these stand in for the value until then.
    solution_pending : ClassVar[int | None] = None
    solution_stale   : ClassVar[int | None] = None             # what the property held when the write was scheduled
    steps_pending    : ClassVar[int | None] = None

    # Selection bookkeeping
    sel_sig        : ClassVar[tuple | None] = None             # selection the last live rebuild ran on
    filled_sig     : ClassVar[tuple | None] = None             # selection left behind by the last fill; not offered again
    filled_flags   : ClassVar[tuple] = (False, False, False, False, False)   # (bridge, grid, loft, offset, quad) of the last fill, for its redo panel
    filled_loops   : ClassVar[int] = 0
    filled_solutions : ClassVar[int] = 1

    # Cursor and Ctrl, in window space. The *_locked values are what they were when the last fill
    # started: a redo re-runs the whole rebuild later and must not read where the cursor has gone since,
    # or a wire run would step to its other side.
    mouse          : ClassVar[tuple[int, int] | None] = None
    mouse_locked   : ClassVar[tuple[int, int] | None] = None
    ctrl           : ClassVar[bool] = False                 # the cursor pick only runs while Ctrl is held, like PolyPen's insert
    ctrl_locked    : ClassVar[bool | None] = None
    ctrl_forced    : ClassVar[bool] = False                 # F held from another tool stands in for Ctrl; owned by the quick switch, so reset_session leaves it alone

    # Cursor pick caches. Kept across rebuilds (not cleared by _clear_products): they only go stale
    # when the mesh or the view changes. Indices and copied coords only.
    cand_key       : ClassVar[tuple | None] = None       # (depsgraph_version, edit object name)
    cand_idx       : ClassVar[list[int]] = []            # candidate vert indices
    cand_cos       : ClassVar[object] = None             # (N,3) local coords
    cand_edges     : ClassVar[object] = None             # (M,2) rows into the candidate arrays: the open edges
    cand_open      : ClassVar[object] = None             # (N,) open edge count per candidate
    proj_key       : ClassVar[tuple | None] = None       # cand_key + view matrix + region size
    proj_px        : ClassVar[object] = None             # (N,2) region pixels, NaN behind the camera
    vis_cache      : ClassVar[dict] = {}                 # candidate row -> visible, for the current proj_key
    vis_key        : ClassVar[tuple | None] = None
    nearest_active : ClassVar[bool] = False              # the cursor pick is on
    nearest_sig    : ClassVar[frozenset | None] = None   # vert indices of the quad on offer
    hover_sig      : ClassVar[tuple | None] = None       # ('edge'|'vert', index) the hover extend is showing for
    drag_path      : ClassVar[list] = []                 # window-space points of the Ctrl+LMB drag being drawn
    drag_last      : ClassVar[list | None] = None        # face outlines of the last patch a drag made; nothing happens until the cursor leaves them
    drag_cand      : ClassVar[tuple | None] = None       # (key of the preview the drag is in, where the cursor entered it)

    @staticmethod
    def reset_session():
        L = LegacyPatches_Logic
        L.depsgraph_version = -1
        L.last_settings = None
        L.sel_sig = None
        L.steps_pending = None
        L.filled_sig = None
        L.filled_flags = (False, False, False, False, False)
        L.filled_loops, L.filled_solutions = 0, 1
        L.grid_sig = None
        L.solution_pending = L.solution_stale = None
        L.mouse = L.mouse_locked = None
        L.cand_key = None
        L.cand_idx = []
        L.cand_cos = L.cand_edges = L.cand_open = None
        L.proj_key = L.proj_px = None
        L.vis_cache = {}
        L.vis_key = None
        L.nearest_active = False
        L.nearest_sig = L.hover_sig = None
        L.drag_path = []
        L.drag_last = L.drag_cand = None
        L.ctrl = False
        L.ctrl_locked = None
        L.dirty = True
        L._clear_products()

    @staticmethod
    def _clear_products():
        L = LegacyPatches_Logic
        L.boundary_verts = {}
        L.corner_indices = set()
        L.labels = []
        L.previz = []
        L.has_bridge = L.has_loft = L.has_grid = L.has_offset = L.has_quad = False
        L.has_manual_corners = False
        L.grid_last = None
        L.grid_ranked = []
        L.loops_last = None
        L.wire_runs = []
        L.error = None

    @staticmethod
    def selection_signature(bm, edges) -> tuple:
        # the face count catches unrelated edits that leave the same edges selected
        return (len(bm.faces), frozenset(e.index for e in edges))

    ##############################################
    # tool properties

    @staticmethod
    def tool_props(context : Context):
        # the main operator never runs; its properties are only a settings store on the workspace tool
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        if not tool or tool.idname != MAIN_OP_IDNAME: return None
        try:
            return tool.operator_properties(MAIN_OP_IDNAME)
        except Exception:
            return None

    @staticmethod
    def read_settings(context : Context) -> PatchSettings:
        L = LegacyPatches_Logic
        props = L.tool_props(context)
        if not props: return PatchSettings()
        try:
            values = { name: getattr(props, name) for name in PATCH_SETTING_NAMES }
            values['steps'] = L.settled_steps(int(values['steps']))
            return PatchSettings(**values)
        except Exception:
            return PatchSettings()

    @staticmethod
    def settled_steps(steps : int) -> int:
        L = LegacyPatches_Logic
        if L.steps_pending is not None:
            if steps == L.steps_pending: L.steps_pending = None
            else: return L.steps_pending
        return max(1, steps)

    @staticmethod
    def _write_tool_prop_later(name : str, value_of):
        # the rebuild runs inside a draw callback, which may not write properties, so writes go through a timer
        def write():
            try:
                props = LegacyPatches_Logic.tool_props(bpy.context)
                value = value_of()
                if props is not None and value is not None and getattr(props, name) != value:
                    setattr(props, name, value)
            except Exception:
                pass
            return None
        bpy.app.timers.register(write, first_interval=0.0)

    @staticmethod
    def push_steps(value : int):
        LegacyPatches_Logic.steps_pending = value
        LegacyPatches_Logic._write_tool_prop_later('steps', lambda: value)

    @staticmethod
    def push_solution(value : int, stale : int):
        L = LegacyPatches_Logic
        L.solution_pending, L.solution_stale = value, stale
        L._write_tool_prop_later('solution', lambda: L.solution_pending)

    # Ctrl+Scroll drives the count knob and Shift+Scroll the offset knob, as in Contours. Which knob
    # is live depends on what the selection produced; a loft and a grid fill never coexist.

    @staticmethod
    def adjust_count(context : Context, delta : int) -> bool:
        L = LegacyPatches_Logic
        props = L.tool_props(context)
        if not props: return False
        if L.has_bridge and L.loops_last is not None:
            # scrolling is an explicit count, so stop deriving one
            props.span_insert_mode = 'FIXED'
            props.crosses = max(0, L.loops_last + delta)
        elif L.has_grid and L.grid_ranked:
            props.solution = (props.solution - 1 + delta) % len(L.grid_ranked) + 1
        elif L.has_quad:
            props.crosses = max(0, props.crosses + delta)
        elif L.has_offset:
            # last, so a patch that is also on screen keeps its own knob
            props.steps = max(1, props.steps + delta)
        else:
            return False
        L.dirty = True
        return True

    @staticmethod
    def adjust_offset(context : Context, delta : int) -> bool:
        L = LegacyPatches_Logic
        props = L.tool_props(context)
        if not props: return False
        if L.has_loft:
            props.twist += delta
        elif L.has_grid:
            props.offset += delta
        else:
            return False
        L.dirty = True
        return True

    ##############################################
    # rebuild

    @staticmethod
    def foreign_operator_running() -> bool:
        # Transform, TopoRotate and the like move geometry every frame, so the preview is neither
        # rebuilt nor drawn while they run. An operator that only holds a key down flags itself passive.
        return any(not isinstance(op, RFOverlay_Base) and not getattr(op, 'rf_patches_passive', False)
                   for op in RFOperator.active_operators)

    @staticmethod
    def update(context : Context):
        L = LegacyPatches_Logic
        RFCore = RFGlobals.RFCore_None
        if not RFCore or not context.edit_object: return
        if L.foreign_operator_running(): return

        if L.depsgraph_version != RFCore.depsgraph_version:
            L.depsgraph_version = RFCore.depsgraph_version
            L.dirty = True

        settings = L.read_settings(context)
        if settings != L.last_settings:
            L.last_settings = settings
            L.dirty = True

        if not L.dirty: return
        L.dirty = False
        try:
            L._recompute(context, settings, live=True)
        except ReferenceError:
            # the bmesh was swapped out mid-frame; rebuild on the next one
            L._clear_products()
            L.dirty = True

    @staticmethod
    def _recompute(context : Context, settings : PatchSettings, *, live : bool = False):
        L = LegacyPatches_Logic
        MAX_SELECTED_EDGES = 1000       # same bail-out as the loop/strip selection overlay
        MAX_NEW_VERTS = 20000           # each new vert costs one closest-point query per source
        SNAP_CAP_EDGES = 2.0            # how far a new vert may be projected, in mean boundary edge lengths, so it cannot land on the far side of a form
        MAX_SNAP_NOISE = 0.7            # _grid_snap_noise above this means the fill bears no relation to the source
        GUIDE_MAX_ALONG = 0.7           # |cos| above which an existing edge runs along the strip and cannot guide a new side
        WELD_FIT_RADIUS = 0.6           # how far from where a new vert would land an existing one may sit, in step lengths
        WELD_FIT_MIN_SQUARENESS = 0.45  # below this a fresh vert makes a better quad than the existing one would
        LOFT_PARALLEL = LOFT_STACKED = 0.5  # two loops loft only when they face the same way and are stacked along their normals

        # v3 compared the interior angle to a threshold; Split Angle states the same test as a deviation from straight
        min_angle = 180.0 - math.degrees(settings.split_angle)
        L.nearest_active = False
        # a live rebuild follows the cursor; a fill, and every redo of it, uses the cursor the fill started with
        mouse_at = L.mouse if live else (L.mouse_locked if L.mouse_locked is not None else L.mouse)
        ctrl_at = (L.ctrl or L.ctrl_forced) if live else (L.ctrl_locked if L.ctrl_locked is not None else L.ctrl)
        L._clear_products()

        edit_object = context.edit_object
        assert edit_object
        M = edit_object.matrix_world
        bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)

        # read-only: this runs from a draw callback, so only toggle_corner() ever creates the layer
        layer = bm.verts.layers.int.get(CORNER_LAYER)
        def override(bmv):
            return bmv[layer] if layer else CORNER_AUTO

        ##############################################
        # read the selection

        edges = { e for e in bmops.get_all_selected_bmedges(bm) if len(e.link_faces) < 2 and not e.hide }
        # only as many selected verts as it takes to tell none, one, three, four and more apart
        sel_verts = []
        for bmv in bm.verts:
            if not bmv.select or bmv.hide: continue
            sel_verts.append(bmv)
            if len(sel_verts) > 4: break
        lone_bmv = sel_quad = sel_tri = None

        # Four selected verts with at least one on no selected edge are a picked quad. Every vert of
        # an L or C is on a selected edge, and two separate edges are a bridge with its count knob.
        if len(sel_verts) == 4 and any(not any(e in edges for e in v.link_edges) for v in sel_verts):
            sel_quad = L._selected_quad(bm, sel_verts, context.region, context.region_data, M)
            if sel_quad is not None:
                edges = set()   # the quad is the whole fill; a selected edge among the four must not also step
        # Three selected verts are a triangle whenever they make a real one, connected or not: an edge
        # and a vert off to its side, three loose verts, or a run bent sharply enough to be a corner.
        # Only the shape decides, so a gentle run stays a strip to step and a sharp one does not.
        if sel_quad is None and len(sel_verts) == 3:
            sel_tri = L._selected_tri(bm, sel_verts, M)
            if sel_tri is not None:
                edges = set()   # the triangle wins over stepping or cornering the edges it was picked with
        if not edges and sel_quad is None and len(sel_verts) == 1:
            lone_bmv = sel_verts[0]     # a lone vert with two open edges is a corner of a quad
        # anything else that gives no preview falls through to the cursor pick at the end

        sel_edges = frozenset(edges)
        L.has_manual_corners = layer is not None and any(bmv[layer] != CORNER_AUTO for bme in sel_edges for bmv in bme.verts)
        if len(edges) > MAX_SELECTED_EDGES:
            L.error = f'Patches: too many selected boundary edges ({len(edges)})'
            return

        sig = L.selection_signature(bm, edges)
        if edges and sig == L.filled_sig:
            edges = set()   # the patch just built is still selected: do not stack a second one on it
        if live and sig != L.sel_sig:
            # a new selection starts over at one step, so a count scrolled up for one run does not carry to the next
            L.sel_sig = sig
            if settings.steps != 1:
                L.push_steps(1)
                settings = replace(settings, steps=1)   # update() holds this same object, so never mutate it

        L.boundary_verts = { v.index: v.co.copy() for e in edges for v in e.verts }

        shapes = {
            'O': [], 'eye': [], 'tri': [], 'rect': [], 'ngon': [],   # loops
            'C': [], 'L': [], 'I': [], 'else': [],                    # strings
        }

        ##############################################
        # group the edges into strips, splitting at corners (v3)

        remaining_edges = set(edges)
        strips = []
        neighbors = { e: [] for e in edges }
        while remaining_edges:
            strip = set()
            working = { next(iter(remaining_edges)) }
            while working:
                edge = working.pop()
                strip.add(edge)
                remaining_edges.discard(edge)
                v0, v1 = edge.verts
                for e in chain(v0.link_edges, v1.link_edges):
                    if e not in remaining_edges: continue
                    bmv1 = bmes_shared_bmv(edge, e)
                    if bmv1 is None: continue
                    mode = override(bmv1)
                    if mode == CORNER_FORCED: continue
                    bmv0 = edge.other_vert(bmv1)
                    bmv2 = e.other_vert(bmv1)
                    d10 = (bmv0.co - bmv1.co).normalized()
                    d12 = (bmv2.co - bmv1.co).normalized()
                    if mode != CORNER_SMOOTH and _angle_deg(d10, d12) < min_angle: continue
                    neighbors[edge].append(e)
                    neighbors[e].append(edge)
                    working.add(e)
            strips.append(strip)

        # order each strip end to end; a strip with no ends is an O
        ordered_strips = []
        corners = dict()
        for sedges in strips:
            if len(sedges) == 1:
                edge = next(iter(sedges))
                strip = [edge]
                v0, v1 = edge.verts
                ordered_strips.append(strip)
                corners.setdefault(v0, []).append(strip)
                corners.setdefault(v1, []).append(strip)
                continue
            end_edges = [edge for edge in sedges if len(neighbors[edge]) == 1]
            if not end_edges:
                strip = [next(iter(sedges))]
                strip.append(next(iter(neighbors[strip[0]])))
                rem = set(sedges) - set(strip)
                isbad = False
                while rem:
                    next_edges = [edge for edge in neighbors[strip[-1]] if edge in rem]
                    if len(next_edges) != 1:
                        isbad = True
                        break
                    strip.append(next_edges[0])
                    rem.remove(next_edges[0])
                if isbad: continue
                shapes['O'].append(strip)
                cos = [ bmv.co for bme in strip for bmv in bme.verts ]
                L.labels.append((str(len(strip)), [sum(cos, Vector()) / len(cos)]))
                continue
            strip = [end_edges[0]]
            rem = set(sedges) - set(strip)
            isbad = False
            while rem:
                next_edges = [edge for edge in neighbors[strip[-1]] if edge in rem]
                if len(next_edges) != 1:
                    isbad = True    # see GitHub issue #481
                    break
                strip.append(next_edges[0])
                rem.remove(next_edges[0])
            if isbad: continue
            v0 = strip[0].other_vert(bmes_shared_bmv(strip[0], strip[1]))
            v1 = strip[-1].other_vert(bmes_shared_bmv(strip[-1], strip[-2]))
            corners.setdefault(v0, []).append(strip)
            corners.setdefault(v1, []).append(strip)
            ordered_strips.append(strip)
        strips = ordered_strips
        for strip in strips:
            # the count sits on the strip's middle edge; a single edge says nothing with its count
            if len(strip) < 2: continue
            mid = strip[len(strip) // 2]
            L.labels.append((str(len(strip)), [(mid.verts[0].co + mid.verts[1].co) / 2]))

        ##############################################
        # chain strips through their corners into strings (I, L, C) and loops (eye, tri, rect, ngon) (v3)

        ignore_corners = { c for c in corners if len(corners[c]) > 2 }

        def align_strips(strips):
            ''' Reverse strips as needed so each one ends where the next begins. None when they do not chain. '''
            if len(strips) == 1: return strips
            strip0, strip1 = strips[:2]
            if bmes_shared_bmv(strip0[0], strip1[0]) or bmes_shared_bmv(strip0[0], strip1[-1]): strip0.reverse()
            if not (bmes_shared_bmv(strip0[-1], strip1[0]) or bmes_shared_bmv(strip0[-1], strip1[-1])): return None
            for strip0, strip1 in zip(strips[:-1], strips[1:]):
                if bmes_shared_bmv(strip1[-1], strip0[-1]): strip1.reverse()
                if not bmes_shared_bmv(strip1[0], strip0[-1]): return None
            return strips

        remaining_corners = set(corners.keys())
        string_corners = set()
        loop_corners = set()

        while remaining_corners:
            c = next((c for c in remaining_corners if len(corners[c]) == 1), None)
            if not c: break
            remaining_corners.remove(c)
            string_corners.add(c)
            string_strips = [corners[c][0]]
            ignore = c in ignore_corners
            while True:
                s = string_strips[-1]
                c = next((c for c in remaining_corners if s in corners[c]), None)
                if not c: break
                ignore |= c in ignore_corners
                remaining_corners.remove(c)
                string_corners.add(c)
                if len(corners[c]) != 2: break
                ns = next(ns for ns in corners[c] if ns != s)
                string_strips.append(ns)
            string_strips = align_strips(string_strips)
            if ignore or string_strips is None: continue
            kind = { 1: 'I', 2: 'L', 3: 'C' }.get(len(string_strips), 'else')
            shapes[kind].append(string_strips)

        while remaining_corners:
            c = next(iter(remaining_corners))
            remaining_corners.remove(c)
            loop_corners.add(c)
            loop_strips = [corners[c][0]]
            ignore = c in ignore_corners
            while True:
                s = loop_strips[-1]
                c = next((c for c in remaining_corners if s in corners[c]), None)
                if not c: break
                ignore |= c in ignore_corners
                remaining_corners.remove(c)
                loop_corners.add(c)
                ns = next((ns for ns in corners[c] if ns != s), None)
                if not ns: break
                loop_strips.append(ns)
            loop_strips = align_strips(loop_strips)
            if ignore or loop_strips is None: continue
            s0, s1 = loop_strips[0], loop_strips[-1]
            shared_verts = sum(1 for e0 in s0 for e1 in s1 if bmes_shared_bmv(e0, e1))
            if len(loop_strips) == 2 and shared_verts != 2: continue   # not closed
            if len(loop_strips) > 2 and shared_verts != 1: continue
            kind = { 2: 'eye', 3: 'tri', 4: 'rect' }.get(len(loop_strips), 'ngon')
            shapes[kind].append(loop_strips)

        L.corner_indices = { c.index for c in (string_corners | loop_corners) }

        ##############################################
        # snapping and mirror helpers, set up once per rebuild

        Mi = M.inverted_safe()
        sources = [ (o, o.matrix_world, o.matrix_world.inverted_safe()) for o in iter_all_valid_sources(context) ]
        mirror_axes = active_mirror_axes(context)
        mirror_tol = mirror_threshold(context) or 0.0

        def snap(co_local, normal_world=None, cap=None, *, ray=True, missed=None):
            # With a normal, cast along it both ways first: nearest point drags an off-surface point
            # sideways, a ray keeps its in-surface position. The cap rejects hits on unrelated far
            # surfaces. A step passes ray=False: it is barely off the surface, and a ray leaving the
            # edge of the source lands on whatever is behind it. `missed` collects a flag when nothing
            # was found, so a caller can stop rather than leave a vert hanging in the air.
            def refused():
                if missed is not None: missed.append(True)
                return co_local.copy()
            co_world = M @ co_local
            if ray and normal_world is not None and cap:
                origin = Vector((*co_world, 1.0))
                best = None
                for d in (normal_world, -normal_world):
                    hit = raycast_ray_valid_sources(context, (origin, Vector((*d, 0.0))), world=True, sources=sources)
                    if hit is None: continue
                    dist = (hit - co_world).length
                    if dist <= cap and (best is None or dist < best[0]):
                        best = (dist, hit)
                if best: return Mi @ best[1]
            if normal_world is not None or cap:
                # nearest point has no sense of direction: refuse a hit that is far away or faces
                # the other way, which is how a patch used to fold onto the back of a form
                r = nearest_point_normal_valid_sources(context, co_world)
                if r is None: return refused()
                hit, hit_n = r
                if cap and (hit - co_world).length > cap: return refused()
                if normal_world is not None and hit_n.dot(normal_world) < 0: return refused()
                return Mi @ hit
            co = nearest_point_valid_sources(context, co_world, world=False, sources=sources)
            return Vector(co) if co else refused()

        def sym_axes(co):
            ''' Mirror planes this point sits on. '''
            return frozenset(a for a in mirror_axes if sign_threshold(getattr(co, a), mirror_tol) == 0)

        def to_planes(co, axes):
            ''' Pin onto the given mirror planes, re-snapping so the point stays on the source. '''
            if not axes: return co
            for a in axes: setattr(co, a, 0.0)
            co = snap(co)
            for a in axes: setattr(co, a, 0.0)
            return co

        def shape_side(pts):
            ''' Per mirror axis, which side of the plane the shape's boundary is on; 0 when it straddles it. '''
            side = {}
            for a in mirror_axes:
                votes = [ s for v in pts if (s := sign_threshold(getattr(_co(v), a), mirror_tol)) != 0 ]
                pos = sum(1 for s in votes if s > 0)
                neg = len(votes) - pos
                side[a] = 1 if not votes else (0 if (pos and neg) else (1 if pos else -1))
            return side

        def shape_cap(pts):
            ''' World-space limit on how far a new vert may be projected: a few mean boundary edge lengths. '''
            cos = [ M @ _co(v) for v in pts ]
            lens = [ l for a, b in zip(cos, cos[1:]) if (l := (b - a).length) > 1e-9 ]
            if not lens: return None
            return SNAP_CAP_EDGES * sum(lens) / len(lens)

        def new_point(co, side, normal_world=None, cap=None, *, ray=True, missed=None):
            ''' Snap a blended coordinate, then keep it on its shape's side of each mirror plane. '''
            co = snap(co, normal_world, cap, ray=ray, missed=missed)
            for a, s in side.items():
                if not s: continue
                sv = sign_threshold(getattr(co, a), mirror_tol)
                if sv == 0:
                    setattr(co, a, 0.0)
                elif sv == -s:
                    co = to_planes(co, (a,))    # landed on the wrong side: clamp onto the plane
            return co

        # normals come from the source under each boundary point, since target faces may be missing
        # or flipped, and are blended like positions to give each new vert a casting direction
        normal_cache = {}
        def source_normal(pt):
            key = ('v', pt.index) if isinstance(pt, BMVert) else ('c', tuple(round(c, 6) for c in pt))
            if key not in normal_cache:
                r = nearest_point_normal_valid_sources(context, M @ _co(pt))
                normal_cache[key] = r[1].normalized() if (r and r[1].length_squared > 0) else None
            return normal_cache[key]

        def normal_fn(pts):
            ''' source_normal with the mean normal of `pts` as the fallback. '''
            known = [ n for v in pts if (n := source_normal(v)) is not None ]
            fallback = sum(known, Vector()).normalized() if known else None
            if fallback is not None and fallback.length_squared == 0: fallback = None
            def nrm(pt):
                n = source_normal(pt)
                return n if n is not None else fallback
            return nrm

        def coons(l, r, b, t, c00, c10, c01, c11, pi, pj):
            # transfinite blend: both rulings minus the bilinear corner term, so every boundary curve is
            # reproduced exactly. v3 averaged the rulings, which pulled interior loops toward the chords
            lr = l * (1 - pj) + r * pj
            tb = b * (1 - pi) + t * pi
            bl = c00 * ((1 - pi) * (1 - pj)) + c10 * (pi * (1 - pj)) + c01 * ((1 - pi) * pj) + c11 * (pi * pj)
            return lr + tb - bl

        def blend_pair(na, nb, t):
            if na is None or nb is None: return None
            n = na * (1 - t) + nb * t
            return n.normalized() if n.length_squared > 1e-12 else None

        def blend_normal(*args):
            if any(a is None for a in args[:8]): return None
            n = coons(*args)
            return n.normalized() if n.length_squared > 1e-12 else None

        def guide_direction(bmv, n, along, toward):
            ''' Direction a new side should leave a free corner in: the existing unselected edge there
            that does not run along the strip. An edge heading into the hole is followed; one heading
            away is continued straight through the corner. None when there is no such edge. '''
            if toward is None: return None
            if n is not None: toward = toward - n * toward.dot(n)
            if toward.length_squared < 1e-12: return None
            toward = toward.normalized()
            best, best_score = None, 0.0
            for e in bmv.link_edges:
                if e in sel_edges: continue
                d = e.other_vert(bmv).co - bmv.co
                if n is not None: d = d - n * d.dot(n)
                if d.length_squared < 1e-12: continue
                d.normalize()
                if along is not None and abs(d.dot(along)) > GUIDE_MAX_ALONG: continue
                dt = d.dot(toward)
                score = dt if dt > 0 else -dt * 0.999    # an edge heading into the hole wins a tie
                if score > best_score:
                    best, best_score = (d if dt > 0 else -d), score
            return best

        def smooth_grid(verts, normals, l0, l1, side, cap, fixed, *, cyclic_i=False):
            # Laplacian smoothing of the new verts with the boundary fixed, re-snapped after each pass.
            # Only axes with a neighbour on both sides count, so the open rows of a bridge stay put.
            for _ in range(settings.smooth):
                moved = {}
                for i in range(l0):
                    for j in range(l1):
                        k = i * l1 + j
                        if k in fixed: continue
                        acc, n = Vector(), 0
                        if cyclic_i:
                            acc += _co(verts[((i - 1) % l0) * l1 + j]) + _co(verts[((i + 1) % l0) * l1 + j])
                            n += 2
                        elif 0 < i < l0 - 1:
                            acc += _co(verts[(i - 1) * l1 + j]) + _co(verts[(i + 1) * l1 + j])
                            n += 2
                        if 0 < j < l1 - 1:
                            acc += _co(verts[i * l1 + (j - 1)]) + _co(verts[i * l1 + (j + 1)])
                            n += 2
                        if n: moved[k] = acc / n
                for k, co in moved.items():
                    verts[k] = new_point(co, side, normals[k], cap)

        def over_existing_faces(verts, faces):
            ''' Whether the patch sits on top of the mesh rather than filling the empty side of its
            boundary, as when the outline of an island is selected: most new faces land on the same
            side of their one-faced boundary edges as the existing face. '''
            same, other = 0, 0
            for f in faces:
                centre = sum((_co(verts[k]) for k in f), Vector()) / len(f)
                for a, b in zip(f, f[1:] + f[:1]):
                    va, vb = verts[a], verts[b]
                    if not (isinstance(va, BMVert) and isinstance(vb, BMVert)): continue
                    bme = bmvs_shared_bme(va, vb)
                    if bme is None or len(bme.link_faces) != 1: continue
                    faced = _on_faced_side(bme, centre)
                    if faced is None: continue
                    if faced: same += 1
                    else: other += 1
            return same > other

        def add_previz(kind, verts, edges, faces, open_idx=(), row_idx=()):
            L.previz.append(Previz(
                kind,
                [ (v.index if isinstance(v, BMVert) else None) for v in verts ],
                [ (v.co.copy() if isinstance(v, BMVert) else v) for v in verts ],
                edges,
                faces,
                tuple(open_idx),
                tuple(row_idx),
            ))

        n_new = 0
        def budget(count):
            ''' Cap the total number of new (snapped) verts so a huge selection cannot stall the viewport. '''
            nonlocal n_new
            n_new += count
            if n_new <= MAX_NEW_VERTS: return True
            L.error = 'Patches: selection too large to preview'
            return False

        def build_grid(kind, l0, l1, boundary_at, interior_at, side, cap, *, cyclic_i=False, pin=None, checks=True):
            ''' Fill an l0 x l1 grid and add it to the preview. boundary_at(i, j) returns the existing
            corner there or None; interior_at(i, j) returns (blended co, normal) for the rest. pin, if
            given, adjusts a new interior point after snapping. With checks, a patch that snapped too
            noisily or that would sit over existing faces is dropped. '''
            verts, normals, raws, fixed = [], [], [], set()
            for i in range(l0):
                for j in range(l1):
                    existing = boundary_at(i, j)
                    if existing is not None:
                        fixed.add(i * l1 + j)
                        verts.append(existing); normals.append(None); raws.append(None)
                        continue
                    co, n = interior_at(i, j)
                    pt = new_point(co, side, n, cap)
                    if pin: pt = pin(i, j, pt)
                    verts.append(pt); normals.append(n); raws.append(co)
            if checks and _grid_snap_noise([ _co(v) for v in verts ], raws, l0, l1, cyclic_i=cyclic_i) > MAX_SNAP_NOISE:
                return
            smooth_grid(verts, normals, l0, l1, side, cap, fixed, cyclic_i=cyclic_i)
            edges, faces = _grid_topology(verts, l0, l1, cyclic_i=cyclic_i)
            if checks and over_existing_faces(verts, faces): return
            # new boundary verts belong to a side this fill creates; without them the quads there read as triangles
            open_idx = [ k for k in sorted(fixed) if not isinstance(verts[k], BMVert) ]
            add_previz(kind, verts, edges, faces, open_idx)

        def get_verts(strip, rev=False):
            if len(strip) == 1: return list(strip[0].verts)
            bmvs = [bme_unshared_bmv(strip[0], strip[1])]
            bmvs += [bmes_shared_bmv(e0, e1) for e0, e1 in zip(strip[:-1], strip[1:])]
            bmvs += [bme_unshared_bmv(strip[-1], strip[-2])]
            if rev: bmvs.reverse()
            return bmvs

        def derive_loops(dist, avg_len):
            ''' Loops to insert between two facing sides; 0 bridges them with one band of quads. Mirrors Contours. '''
            if settings.span_insert_mode == 'FIXED': return max(0, settings.crosses)
            ref = settings.span_length if settings.span_insert_mode == 'LENGTH' else avg_len
            return max(0, round(dist / max(ref, 1e-9)) - 1)

        def mouse_side(co_a, co_b, co_mid, out):
            ''' (sign to give `out` so a wire run steps toward the mouse, side of the chord a-b the
            mouse is on). (1, 0) when the mouse or view is unknown, keeping the geometric side. '''
            rgn, r3d = context.region, context.region_data
            if mouse_at is None or not rgn or not r3d: return 1, 0
            mouse = Vector((mouse_at[0] - rgn.x, mouse_at[1] - rgn.y))
            pa, pb = location_3d_to_region_2d(rgn, r3d, M @ co_a), location_3d_to_region_2d(rgn, r3d, M @ co_b)
            pm = location_3d_to_region_2d(rgn, r3d, M @ co_mid)
            po = location_3d_to_region_2d(rgn, r3d, M @ (co_mid + out))
            if not (pa and pb and pm and po): return 1, 0
            s_mouse, s_out = _side2d(pa, pb, mouse), _side2d(pa, pb, po - pm + pa)
            if not s_mouse or not s_out: return 1, 0
            return (1 if s_mouse == s_out else -1), s_mouse

        ##############################################
        # patch emitters

        def emit_rect_grid(sv0, sv1, sv2, sv3, kind):
            ''' Coons-fill a four-sided region. sv0/sv2 run along i and have equal length, sv1/sv3
            along j. Sides share endpoints: sv0[0]==sv3[0], sv0[-1]==sv1[0], sv2[0]==sv3[-1], sv2[-1]==sv1[-1]. '''
            l0, l1 = len(sv0), len(sv1)
            if l0 < 2 or l1 < 2: return True
            if not budget(max(0, (l0 - 2) * (l1 - 2))): return False
            boundary = sv0 + sv1 + sv2 + sv3
            nrm = normal_fn(boundary)
            c00, c10, c01, c11 = sv0[0], sv0[-1], sv2[0], sv2[-1]

            def boundary_at(i, j):
                if i == 0: return sv3[j]
                if i == l0 - 1: return sv1[j]
                if j == 0: return sv0[i]
                if j == l1 - 1: return sv2[i]
                return None

            def interior_at(i, j):
                pi, pj = i / (l0 - 1), j / (l1 - 1)
                l, r, b, t = sv0[i], sv2[i], sv3[j], sv1[j]
                n = blend_normal(nrm(l), nrm(r), nrm(b), nrm(t), nrm(c00), nrm(c10), nrm(c01), nrm(c11), pi, pj)
                co = coons(_co(l), _co(r), _co(b), _co(t), _co(c00), _co(c10), _co(c01), _co(c11), pi, pj)
                return co, n

            build_grid(kind, l0, l1, boundary_at, interior_at, shape_side(boundary), shape_cap(boundary))
            return True

        def emit_span(kind, sv0, sv1, l1, boundary, *, cyclic_i=False, checks=True):
            ''' Straight blend between two sides of equal count, sv0[i] paired with sv1[i], with l1 - 2
            new verts across. `boundary` is what the snap cap, mirror side and normals are taken from. '''
            l0 = len(sv0)
            if not budget(l0 * max(0, l1 - 2)): return False
            nrm = normal_fn(boundary)

            def boundary_at(i, j):
                return sv0[i] if j == 0 else sv1[i] if j == l1 - 1 else None

            def interior_at(i, j):
                pj = j / (l1 - 1)
                co = _co(sv0[i]) * (1 - pj) + _co(sv1[i]) * pj
                return co, blend_pair(nrm(sv0[i]), nrm(sv1[i]), pj)

            build_grid(kind, l0, l1, boundary_at, interior_at, shape_side(boundary), shape_cap(boundary),
                       cyclic_i=cyclic_i, checks=checks)
            return True

        def cycle_bmvs(bmes):
            ''' Ordered verts around a closed edge cycle, or None if these edges are not one. '''
            es = set(bmes)
            if len(es) < 3: return None
            start = next(iter(es)).verts[0]
            order, cur_v, cur_e = [start], start, None
            while True:
                nxt = next((e for e in cur_v.link_edges if e in es and e is not cur_e), None)
                if nxt is None: return None
                cur_v, cur_e = nxt.other_vert(cur_v), nxt
                if cur_v is start: break
                order.append(cur_v)
                if len(order) > len(es): return None
            return order if len(order) == len(es) else None

        def cycle_bmes(bmvs):
            ''' The edges joining a closed run of verts, in order; None if any is missing. '''
            out = []
            for a, b in zip(bmvs, bmvs[1:] + bmvs[:1]):
                bme = bmvs_shared_bme(a, b)
                if bme is None: return None
                out.append(bme)
            return out

        def emit_loft(bmvs_a, bmvs_b, axis):
            ''' Bridge two closed loops of equal count: the I grid, wrapped around. '''
            LOFT_CORNER_WEIGHT = 0.5    # how far matching sharp corners may outweigh a closer vertex pairing
            bmvs0, bmvs1 = list(bmvs_a), list(bmvs_b)
            n = len(bmvs0)

            # wind both loops the same way around the axis, or every quad comes out crossed
            n0 = compute_n([v.co for v in bmvs0])
            n1 = compute_n([v.co for v in bmvs1])
            if n0.length_squared > 1e-12 and n0.dot(axis) < 0: bmvs0.reverse()
            if n1.length_squared > 1e-12 and n1.dot(axis) < 0: bmvs1.reverse()

            # Rotate loop B onto loop A. Closest-vertex pairing alone twists the bridge when the loops
            # differ in size or sit off-axis, so matching sharp corners gets a say too, as in Contours.
            cos0 = [v.co for v in bmvs0]
            cos1 = [v.co for v in bmvs1]
            sharp0, sharp1 = _turn_sharpness(cos0), _turn_sharpness(cos1)
            dists   = [ sum((cos0[i] - cos1[(i + j) % n]).length_squared for i in range(n)) for j in range(n) ]
            corners = [ sum(sharp0[i] * sharp1[(i + j) % n] for i in range(n)) for j in range(n) ]
            d_min = min(dists) or 1e-9
            c_max = max(corners) or 1e-9
            best_j = min(range(n), key=lambda j: dists[j] / d_min - LOFT_CORNER_WEIGHT * (corners[j] / c_max))
            j0 = (best_j + settings.twist) % n
            bmvs1 = bmvs1[j0:] + bmvs1[:j0]

            dist = sum((bmvs0[i].co - bmvs1[i].co).length for i in range(n)) / n
            per0 = sum((bmvs0[i].co - bmvs0[(i + 1) % n].co).length for i in range(n))
            per1 = sum((bmvs1[i].co - bmvs1[(i + 1) % n].co).length for i in range(n))
            loops = derive_loops(dist, (per0 + per1) / (2 * n))
            L.has_bridge = L.has_loft = True
            L.loops_last = loops
            return emit_span('loft', bmvs0, bmvs1, loops + 2, bmvs0 + bmvs1, cyclic_i=True)

        def emit_grid_fill(bmvs, kind):
            ''' Fill a closed loop of any even count the way Blender's Grid Fill does: as a span x
            (half - span) rectangle, choosing where its four corners sit round the loop. Hands the
            result to the Coons fill, so an uneven or non-quadrilateral loop still previews and snaps. '''
            n = len(bmvs)
            cos = [_co(v) for v in bmvs]
            if n < 4 or n % 2: return True    # an odd loop cannot be closed with quads alone
            half = n // 2

            sharp = _turn_sharpness(cos)
            def side_mid(a, cnt):
                # middle of the side running cnt edges from vert a
                k = a + cnt // 2
                return cos[k % n] if cnt % 2 == 0 else (cos[k % n] + cos[(k + 1) % n]) / 2

            # every distinct split is a solution: for each span, the corner placement scoring best.
            # Ranked best first, so Solution 1 is the automatic choice
            ranked, seen = [], set()
            for span in range(1, half):
                best = None
                for off in range(n):
                    # cell size measured across the patch: boundary edge lengths cannot tell a 1x6
                    # strip from a 3x4 grid on a round loop, the distance across can
                    w = (side_mid(off + span, half - span) - side_mid(off + half + span, half - span)).length / span
                    h = (side_mid(off, span) - side_mid(off + half, span)).length / (half - span)
                    aspect = max(w, h) / max(1e-9, min(w, h))     # 1.0 means square quads
                    corner = sum(sharp[(off + k) % n] for k in (0, span, half, half + span))
                    score = aspect - 2.0 * corner                 # corners at real bends are worth a lot
                    if best is None or score < best[0]: best = (score, span, off)
                if best is None: continue
                # span s and span half-s at matching offsets are the same four corners
                corner_set = frozenset((best[2] + k) % n for k in (0, span, half, half + span))
                if corner_set in seen: continue
                seen.add(corner_set)
                ranked.append(best)
            if not ranked: return True
            ranked.sort(key=lambda r: (round(r[0], 6), abs(r[1] - half / 2)))    # ties go to the squarest count
            L.grid_ranked = [ (span, off) for _, span, off in ranked ]

            # a new selection always starts at Solution 1, and the property is brought back to match
            sig = L.selection_signature(bm, sel_edges)
            fresh = sig != L.grid_sig
            L.grid_sig = sig
            if fresh:
                choice = 1
                if settings.solution != 1: L.push_solution(1, settings.solution)
            elif L.solution_pending is not None and settings.solution == L.solution_stale:
                choice = L.solution_pending                   # not yet landed in the property
            else:
                L.solution_pending = L.solution_stale = None  # the property has moved on and drives
                choice = settings.solution
            span, off = L.grid_ranked[(choice - 1) % len(L.grid_ranked)]
            off = (off + settings.offset) % n
            L.has_grid = True
            L.grid_last = (span, settings.offset)

            def side_verts(a, cnt):
                return [ bmvs[(a + k) % n] for k in range(cnt + 1) ]
            sv0 = side_verts(off, span)                              # c00 -> c10
            sv1 = side_verts(off + span, half - span)                # c10 -> c11
            sv2 = side_verts(off + half, span)[::-1]                 # c01 -> c11
            sv3 = side_verts(off + half + span, half - span)[::-1]   # c00 -> c01
            return emit_rect_grid(sv0, sv1, sv2, sv3, kind)

        def emit_offset(sv, bmes, *, cyclic=False):
            ''' Rows of quads stepped out from a run of boundary edges that has nothing to fill: an open
            strip with no partner, or a closed loop whose inside is already faces. Each vert steps the
            way the quads already on the run lean, or straight out across the run where there is none.
            An end that turns a corner onto an existing open edge welds onto that edge's far vert
            instead of extruding, so stepping along a boundary knits into what is already there. '''
            MITER_LIMIT = 3.0   # cap on the corner stretch 1/sin(half angle); Split Angle's 135 degree cap needs 2.61
            STEP_STALL = 0.25   # a vert travelling less than this fraction of its step means the row has run out of source
            WELD_MAX_ANGLE = 150.0  # a weld rung this far round from the run darts the first quad; matches _quad_squareness
            n = len(sv)
            if n < 3 if cyclic else n < 2: return True
            nseg = n if cyclic else n - 1      # bmes[k] joins sv[k] and sv[k+1]
            steps = max(1, settings.steps)
            run_verts, run_edges = set(sv), set(bmes)
            cos = [ v.co for v in sv ]
            nxt = lambda i: (i + 1) % n

            # tangent of the run at every vert
            along = []
            for i in range(n):
                a = cos[(i - 1) % n] if (cyclic or i > 0) else cos[i]
                b = cos[nxt(i)] if (cyclic or i < n - 1) else cos[i]
                t = b - a
                if t.length_squared < 1e-14:
                    t = cos[-1] - cos[0]
                    if t.length_squared < 1e-14: return True
                along.append(t.normalized())

            d_mean = sum((cos[nxt(k)] - cos[k]).length for k in range(nseg)) / nseg
            if d_mean < 1e-9: return True

            # straight out across the run and in the surface, at every vert
            nrm = normal_fn(sv)
            perps, prev_n = [], None
            for i, v in enumerate(sv):
                nv = nrm(v)
                if nv is None:
                    bmfs = [ bmf for bme in v.link_edges if bme in run_edges for bmf in bme.link_faces ]
                    nv = next((f.normal for f in bmfs if f.normal.length_squared > 0), None)
                if nv is None: return True     # no source and no face: nothing to lean on
                # keep the normal continuous along the run, so two verts finding opposite faces of a
                # thin surface do not put the row on both sides
                if prev_n is not None and nv.dot(prev_n) < 0: nv = -nv
                prev_n = nv
                p = along[i].cross(nv)
                if p.length_squared < 1e-12: return True
                perps.append(p.normalized())

            # Which side is out, settled one vert at a time: away from the faces that vert's own run
            # edges carry. One vote for the whole run trusts the perps to agree end to end, and across
            # a crease they need not.
            def face_sign(i):
                acc = 0.0
                for bme in (bmes[(i - 1) % n] if (cyclic or i > 0) else None,
                            bmes[i] if (cyclic or i < n - 1) else None):
                    if bme is None or len(bme.link_faces) != 1: continue
                    va, vb = bme.verts
                    al = vb.co - va.co
                    if al.length_squared < 1e-14: continue
                    al = al.normalized()
                    to_old = bme.link_faces[0].calc_center_median() - (va.co + vb.co) / 2
                    to_old -= al * to_old.dot(al)
                    acc += to_old.dot(perps[i])
                return -1 if acc > 0 else (1 if acc < 0 else 0)

            signs = [ face_sign(i) for i in range(n) ]
            if any(signs):
                # a vert whose own edges carry no face takes the side of the nearest one that does
                for order in (range(n), range(n - 1, -1, -1)):
                    last = 0
                    for i in order:
                        if signs[i]: last = signs[i]
                        elif last: signs[i] = last
                perps = [ p * signs[i] for i, p in enumerate(perps) ]
            else:
                # a wire run has no faces to step away from, so it steps toward the mouse
                mid_i = n // 2
                side_sign, s_mouse = mouse_side(cos[0], cos[mid_i if cyclic else -1], cos[mid_i],
                                                perps[mid_i] * d_mean)
                if s_mouse and not cyclic: L.wire_runs.append((cos[0].copy(), cos[-1].copy(), s_mouse))
                if side_sign < 0: perps = [ -p for p in perps ]

            # Step direction per vert: the quad's edge leaving the run there. Each of the vert's two run
            # edges gets one vote and the two are averaged, so where the run turns between two poles the
            # rail between them lands between what each side wants. A side edge running along the run, a
            # non-quad, or a quad on the far side leaves that side with nothing to say; it then votes for
            # the perp rather than standing aside, which would hand the whole direction to the other side.
            dirs = []
            for i, v in enumerate(sv):
                acc = Vector()
                for bme in (bmes[(i - 1) % n] if (cyclic or i > 0) else None,
                            bmes[i] if (cyclic or i < n - 1) else None):
                    if bme is None: continue    # the end of an open run has only the one side
                    lean = Vector()
                    for bmf in bme.link_faces:
                        if len(bmf.verts) != 4: continue
                        side_e = next((fe for fe in bmf.edges if fe is not bme and v in fe.verts), None)
                        if side_e is None: continue
                        d = v.co - side_e.other_vert(v).co
                        if d.length_squared < 1e-14: continue
                        d.normalize()
                        if abs(d.dot(along[i])) > GUIDE_MAX_ALONG: continue
                        if d.dot(perps[i]) <= 0: continue
                        lean += d
                    acc += lean.normalized() if lean.length_squared > 1e-12 else perps[i]
                dirs.append(acc.normalized() if acc.length_squared > 1e-12 else perps[i])

            # a vert where the run turns has to reach further than one where it runs straight, or the
            # new row pinches in at every corner
            miter = []
            for i in range(n):
                u = (cos[(i - 1) % n] - cos[i]) if (cyclic or i > 0) else None
                w = (cos[nxt(i)] - cos[i]) if (cyclic or i < n - 1) else None
                if u is None or w is None or u.length_squared < 1e-14 or w.length_squared < 1e-14:
                    miter.append(1.0)
                    continue
                c = max(-1.0, min(1.0, u.normalized().dot(w.normalized())))
                sin_half = math.sqrt(max(0.0, (1.0 - c) / 2.0))
                miter.append(MITER_LIMIT if sin_half < 1e-6 else min(MITER_LIMIT, 1.0 / sin_half))

            def open_edges_at(bmv, skip_faces_of):
                ''' Candidate rails leaving a vert: unselected, still open, and not in a face the run
                (or the rail so far) already occupies there. Yields (edge, far vert). '''
                skip = { fe for bme in skip_faces_of for bmf in bme.link_faces for fe in bmf.edges }
                for bme in bmv.link_edges:
                    if bme in sel_edges or bme.hide or len(bme.link_faces) >= 2: continue
                    if bme in skip: continue
                    yield bme, bme.other_vert(bmv)

            def weld_target(i_end, i_prev, used):
                ''' An open edge leaving the end of the run whose far vert lies outward, when that end
                is a corner: topologically, or by bending past Split Angle like the strips were split. '''
                v = sv[i_end]
                arrive = v.co - sv[i_prev].co
                if arrive.length_squared < 1e-14: return None
                arrive.normalize()
                topo_corner = bool(v.link_faces) and is_bmvert_corner(v)
                out = dirs[i_end]
                best, best_dot = None, 0.0
                for _bme, w in open_edges_at(v, (bmes[-1] if i_end == n - 1 else bmes[0],)):
                    if w in run_verts or w in used: continue
                    d = w.co - v.co
                    if d.length_squared < 1e-14: continue
                    d = d.normalized()
                    if d.dot(out) <= 0: continue
                    # The rung has to lie outward of the run, not merely the way the mesh flows. A
                    # rung on the inward side puts the first quad's corner here past 180 degrees, and
                    # the quad comes out concave; `out` alone lets that through wherever a pole tilts
                    # the flow round far enough to still agree with it.
                    if d.dot(perps[i_end]) <= 0: continue
                    # the same corner, still convex but opened out until the quad is a dart
                    ang = _angle_deg(-arrive, d)
                    if ang >= WELD_MAX_ANGLE: continue
                    # without topology to say corner, the boundary itself has to turn, or w is nothing
                    # but the run carrying on and there is no corner here to weld round
                    if not topo_corner and ang >= min_angle: continue
                    if d.dot(out) > best_dot: best, best_dot = w, d.dot(out)
                return best

            def rail_next(bmv, from_co, came_along, used):
                ''' Once a row has welded onto a rail, later rows keep following it: the straightest open
                edge on from here. '''
                travel = bmv.co - from_co
                if travel.length_squared < 1e-14: return None
                travel.normalize()
                best, best_dot = None, 0.0
                for _bme, w in open_edges_at(bmv, (came_along,) if came_along else ()):
                    if w in run_verts or w in used: continue
                    d = w.co - bmv.co
                    if d.length_squared < 1e-14: continue
                    d = d.normalized()
                    if d.dot(travel) > best_dot: best, best_dot = w, d.dot(travel)
                return best

            used_welds = set()
            weld0 = weld1 = None
            if not cyclic:
                weld0 = weld_target(0, 1, used_welds)
                weld1 = weld_target(n - 1, n - 2, used_welds)
                if weld0 is not None and weld0 is weld1: return True   # both ends fold onto one vert: not a row of quads
            row0_welds = { i: w for i, w in ((0, weld0), (n - 1, weld1)) if w is not None }

            def row_base(prev_cos, welds):
                ''' Step vector for each vert of the previous row. A welded end must land exactly on its
                weld, so its own offset is used unmitered and whatever its direction could not account
                for is carried across the run, fading out. '''
                if not welds:
                    return [ dirs[i] * (d_mean * miter[i]) for i in range(n) ]
                fr = _cumulative_fracs(prev_cos)
                scale = lambda i, l: dirs[i] * (l * (1.0 if i in welds else miter[i]))
                if len(welds) == 1:
                    i_w, w = next(iter(welds.items()))
                    D = w.co - prev_cos[i_w]
                    r = D - dirs[i_w] * D.length
                    return [ scale(i, D.length) + r * (fr[i] if i_w else 1 - fr[i]) for i in range(n) ]
                D0, D1 = welds[0].co - prev_cos[0], welds[n - 1].co - prev_cos[-1]
                r0, r1 = D0 - dirs[0] * D0.length, D1 - dirs[-1] * D1.length
                return [ scale(i, D0.length * (1 - fr[i]) + D1.length * fr[i]) + r0 * (1 - fr[i]) + r1 * fr[i]
                         for i in range(n) ]

            def trace_boundary_loop(limit):
                ''' Walk the open boundary out from the far end of the run and round to the near end.
                Returns the closed loop (starting with the run) or None when the boundary forks,
                dead-ends or pinches. '''
                loop, seen, came, cur = list(sv), set(sv), None, sv[-1]
                while len(loop) < limit:
                    step_to = [ w for bme, w in open_edges_at(cur, ())
                                if bme not in run_edges and w is not came ]
                    if len(step_to) != 1: return None
                    w = step_to[0]
                    if w is sv[0]: return loop
                    if w in seen: return None
                    loop.append(w); seen.add(w)
                    came, cur = cur, w
                return None

            # Stepping across a hole runs out of hole: stop at the row that lands opposite. When the far
            # side has as many edges as the run, that row IS the far side and the hole welds shut.
            far_row = None
            if not cyclic:
                loop = trace_boundary_loop(2 * nseg + 2 * steps)
                if loop:
                    ltot = len(loop)
                    here = sum(cos, Vector()) / n
                    ahead = sum(dirs, Vector())
                    for k in range(1, steps + 1):
                        rest = ltot - nseg - 2 * k        # edges of the loop still unaccounted for
                        if rest > nseg: continue
                        far = loop[n - 1 + k : ltot - k + 1]
                        if not far: break
                        # a strip's boundary walk comes round its own other side, with solid mesh in
                        # between; only a far side lying the way the run steps is one it is closing on
                        if (sum((v.co for v in far), Vector()) / len(far) - here).dot(ahead) <= 0: break
                        if rest == nseg:
                            far_row = list(reversed(far))
                            steps = k
                        else:
                            steps = k - 1   # the sides cannot meet in quads: stop short and leave the gap
                        break
            if steps < 1: return True
            if not budget(steps * n): return False

            side = shape_side(sv + list(row0_welds.values()))
            # an axis the whole run lies in is the plane it steps away from, so it must not pin to it
            run_axes = frozenset.intersection(*[ sym_axes(c) for c in cos ]) if mirror_axes else frozenset()
            for a in run_axes: side[a] = 0
            cos_w = [ M @ c for c in cos ]
            span_w = sum((cos_w[nxt(k)] - cos_w[k]).length for k in range(nseg)) / nseg
            M3 = M.to_3x3()

            def folds_back(before, after):
                return any((after[nxt(i)] - after[i]).dot(before[nxt(i)] - before[i]) <= 0
                           for i in range(nseg))

            def stalled(before, after, base):
                return any((after[i] - before[i]).length < STEP_STALL * b
                           for i in range(n) if (b := base[i].length) > 1e-9)

            def weld_fit_row0(base, welds, intended):
                ''' Before making the first row, look for existing points that make a good quad with each
                run edge and step onto them instead of extruding over them. Only the first row can be
                judged: later rows stand on verts not yet in the mesh. Mutates base and welds. '''
                proposals = {}      # run index -> [(cost, vert)]
                for a in range(nseg):
                    b = nxt(a)
                    ring = [sv[a], sv[b], welds.get(b), welds.get(a)]
                    open_i = [ i for i, c in zip((b, a), ring[2:]) if c is None ]
                    if not open_i: continue
                    slots = []
                    for i in open_i:
                        r = WELD_FIT_RADIUS * base[i].length
                        slots.append([ w for w in L._candidates_near(context, bm, intended[i], r)
                                       if w not in run_verts and w not in used_welds ])
                    if not all(slots): continue
                    if len(open_i) == 1 and open_i[0] == b:
                        known = [ring[3], sv[a], sv[b]]     # rotate the ring so the open corner is last
                    else:
                        known = [ c for c in ring if c is not None ]
                    res = _complete_quad(bm, known, slots, min_squareness=WELD_FIT_MIN_SQUARENESS)
                    if res is None: continue
                    verts_q, cost = res
                    for i, w in zip(open_i, verts_q[len(known):]):
                        proposals.setdefault(i, []).append((cost, w))
                if not proposals: return
                # each vert takes the best quad proposed for it, and no vert is landed on twice
                chosen, taken = {}, set()
                for i, opts in sorted(proposals.items(), key=lambda kv: min(kv[1])[0]):
                    for cost, w in sorted(opts, key=lambda cw: cw[0]):
                        if w in taken: continue
                        chosen[i] = w
                        taken.add(w)
                        break
                # a segment whose quad no longer holds up with the corners as resolved lets go and steps free
                for a in range(nseg):
                    b = nxt(a)
                    if a not in chosen and b not in chosen: continue
                    def corner(i):
                        return chosen[i] if i in chosen else welds[i] if i in welds else intended[i]
                    q = [sv[a], sv[b], corner(b), corner(a)]
                    if _quad_squareness([ _co(c) for c in q ]) is None or not _face_is_placeable(bm, q):
                        chosen.pop(a, None)
                        chosen.pop(b, None)
                for i, w in chosen.items():
                    welds[i] = w
                    base[i] = w.co - prev_cos[i]
                used_welds.update(chosen.values())

            # each row steps from the one before it and is snapped there, so a run of steps follows the
            # source round a curve, and each row asks again whether its ends have a rail to weld onto
            rows, prev_row, prev_cos, prev_prev_cos = [], list(sv), list(cos), None
            for k in range(steps):
                if k == 0:
                    welds = dict(row0_welds)
                else:
                    welds = {}
                    if not cyclic:
                        for i_end in (0, n - 1):
                            anchor = prev_row[i_end]
                            if not isinstance(anchor, BMVert): continue   # this end stepped free already
                            came = next((e for e in anchor.link_edges
                                         if (e.other_vert(anchor).co - prev_prev_cos[i_end]).length_squared < 1e-12), None)
                            w = rail_next(anchor, prev_prev_cos[i_end], came, used_welds)
                            if w is not None: welds[i_end] = w
                        if len(welds) == 2 and welds[0] is welds[n - 1]: welds = {}
                used_welds |= set(welds.values())

                base = row_base(prev_cos, welds)
                if max(b.length for b in base) < 1e-9: return True
                if k == 0 and (far_row is None or steps != 1):
                    weld_fit_row0(base, welds, [ prev_cos[i] + base[i] for i in range(n) ])

                # snap cap: a couple of this row's own steps, averaged rather than maxed so a mitered
                # corner does not set the cap for the whole row. Past it a vert stays where the step put it.
                cap = SNAP_CAP_EDGES * max(span_w, sum((M3 @ b).length for b in base) / n)

                if far_row is not None and k == steps - 1:
                    row, missed = list(far_row), []   # the last row IS the far side of the hole
                else:
                    row, missed = [], []
                    for i in range(n):
                        if i in welds:
                            row.append(welds[i])
                            continue
                        nb = source_normal(prev_row[i]) or nrm(sv[i])
                        pt = new_point(prev_cos[i] + base[i], side, nb, cap, ray=False, missed=missed)
                        if not cyclic and i in (0, n - 1): pt = to_planes(pt, sym_axes(cos[i]) - run_axes)
                        row.append(pt)
                row_cos = [ _co(pt) for pt in row ]
                if far_row is None or k != steps - 1:
                    # a row that found no source, folded back on itself, or stopped advancing leaves the
                    # quads from here on unusable: keep what is good and stop
                    if ((sources and missed)
                            or folds_back(prev_cos, row_cos) or stalled(prev_cos, row_cos, base)):
                        steps = k
                        break
                rows.append(row)
                prev_row, prev_prev_cos, prev_cos = row, prev_cos, row_cos

            if not rows: return True
            # no over_existing_faces check: the step is aimed away from the run's own faces by construction
            verts = list(sv) + [ pt for row in rows for pt in row ]
            faces = [ ((k - 1) * n + i, (k - 1) * n + nxt(i), k * n + nxt(i), k * n + i)
                      for k in range(1, steps + 1) for i in range(nseg) ]

            def is_new_edge(a, b):
                va, vb = verts[a], verts[b]
                if not (isinstance(va, BMVert) and isinstance(vb, BMVert)): return True
                return bmvs_shared_bme(va, vb) is None
            edges = []
            for k in range(1, steps + 1):
                edges += [ (k * n + i, k * n + nxt(i)) for i in range(nseg) if is_new_edge(k * n + i, k * n + nxt(i)) ]
                edges += [ ((k - 1) * n + i, k * n + i) for i in range(n) if is_new_edge((k - 1) * n + i, k * n + i) ]

            L.has_offset = True
            outer = range(steps * n, (steps + 1) * n)
            if steps > 1:   # the count appears once it is scrolled; the default needs no announcing
                L.labels.append((str(steps), [ sum((_co(verts[k]) for k in outer), Vector()) / n ]))
            add_previz('offset', verts, edges, faces,
                       [ k for k in outer if not isinstance(verts[k], BMVert) ], outer)
            return True

        def emit_quad_strip(q, kind):
            ''' One quad on four corners (BMVerts, or a Vector for a corner the fill creates), cut into
            `crosses + 1` quads across its longer dimension. Interior points are blended between the
            two short sides and snapped, as a bridge's are. '''
            cos = [ _co(v) for v in q ]
            la = ((cos[1] - cos[0]).length + (cos[2] - cos[3]).length) / 2   # sides 0-1 and 3-2
            lb = ((cos[3] - cos[0]).length + (cos[2] - cos[1]).length) / 2   # sides 0-3 and 1-2
            if la >= lb: sv0, sv1 = [q[0], q[3]], [q[1], q[2]]   # the strips are the short sides
            else:        sv0, sv1 = [q[0], q[1]], [q[3], q[2]]
            existing = [ v for v in q if isinstance(v, BMVert) ]
            if not emit_span(kind, sv0, sv1, max(1, settings.crosses + 1) + 1, existing, checks=False): return False
            L.has_quad = True
            return True

        def emit_tri(verts):
            ''' Three selected verts as one triangle. Nothing new is created but the face and whichever
            of its three sides are not already edges. '''
            new_edges = [ (a, b) for a, b in ((0, 1), (1, 2), (2, 0))
                          if bmvs_shared_bme(verts[a], verts[b]) is None ]
            add_previz('triangle', verts, new_edges, [(0, 1, 2)])

        def emit_corner_quad(bmv):
            ''' F2's quad from a vertex: two open edges leaving a corner are two sides of a quad and the
            fourth corner is their parallelogram completion. Edges already sharing a face have no gap
            between them to fill. The cursor picks between pairings, as F2 does. '''
            opens = [ bme for bme in bmv.link_edges if len(bme.link_faces) < 2 and not bme.hide ]
            if len(opens) < 2: return True
            rgn, r3d = context.region, context.region_data
            use_mouse = mouse_at is not None and rgn and r3d
            mouse = Vector((mouse_at[0] - rgn.x, mouse_at[1] - rgn.y)) if use_mouse else None

            best = None
            for bme_a, bme_b in combinations(opens, 2):
                if set(bme_a.link_faces) & set(bme_b.link_faces): continue
                va, vb = bme_a.other_vert(bmv), bme_b.other_vert(bmv)
                if va is vb: continue
                da, db = va.co - bmv.co, vb.co - bmv.co
                if da.length_squared < 1e-14 or db.length_squared < 1e-14: continue
                co = va.co + vb.co - bmv.co
                if use_mouse:
                    pt = location_3d_to_region_2d(rgn, r3d, M @ co)
                    if not pt: continue
                    score = (pt - mouse).length
                else:
                    score = abs(da.normalized().dot(db.normalized()))     # no cursor: the squarest corner wins
                if best is None or score < best[0]: best = (score, va, vb, co)
            if best is None: return True
            _, va, vb, co = best
            da, db = va.co - bmv.co, vb.co - bmv.co

            # where two strips meet at this vert the fourth corner is already there
            nbrs_b = { bme.other_vert(vb) for bme in vb.link_edges }
            corner = next((w for bme in va.link_edges
                           if (w := bme.other_vert(va)) is not bmv and w in nbrs_b), None)
            if corner is None:
                # or a point the artist already dropped about where the corner would go
                r = WELD_FIT_RADIUS * (da.length + db.length) / 2
                cands = [ w for w in L._candidates_near(context, bm, co, r) if w not in (va, vb, bmv) ]
                res = _complete_quad(bm, [va, bmv, vb], [cands], min_squareness=WELD_FIT_MIN_SQUARENESS) if cands else None
                if res is not None: corner = res[0][3]
            if corner is None:
                if not budget(1): return False
                boundary = [va, bmv, vb]
                nrm = normal_fn(boundary)
                cap = SNAP_CAP_EDGES * max((M @ va.co - M @ bmv.co).length, (M @ vb.co - M @ bmv.co).length)
                corner = new_point(co, shape_side(boundary), nrm(bmv), cap, ray=False)

            verts = [va, bmv, vb, corner]
            if len({ id(v) for v in verts }) != 4: return True

            # held to the same standard as a quad picked by the cursor: convex on screen, a shape worth
            # having in 3D, and legal against the mesh
            q = [ M @ _co(v) for v in verts ]
            if _quad_squareness(q) is None: return True
            if rgn and r3d:
                pts = [ location_3d_to_region_2d(rgn, r3d, co) for co in q ]
                if all(pts) and not _is_convex_2d(pts): return True
            if not _face_is_placeable(bm, verts): return True

            return emit_quad_strip(verts, 'corner')

        ##############################################
        # closed loops: loft a stacked pair, else fill each on its own

        cycles = []
        for kind in ('O', 'eye', 'tri', 'rect', 'ngon'):
            for shape in shapes[kind]:
                bmes = shape if kind == 'O' else [ bme for strip in shape for bme in strip ]
                bmvs = cycle_bmvs(bmes)
                if bmvs: cycles.append((kind, shape, bmvs))

        lofted = False
        if len(cycles) == 2 and len(cycles[0][2]) == len(cycles[1][2]) >= 3:
            bmvs_a, bmvs_b = cycles[0][2], cycles[1][2]
            na, ctr_a = fit_plane_of_verts(bmvs_a)
            nb, ctr_b = fit_plane_of_verts(bmvs_b)
            if na and nb and ctr_a and ctr_b:
                axis = ctr_b - ctr_a
                if axis.length > 1e-9:
                    axis = axis.normalized()
                    if (abs(na.dot(nb)) >= LOFT_PARALLEL
                            and abs(na.dot(axis)) >= LOFT_STACKED
                            and abs(nb.dot(axis)) >= LOFT_STACKED):
                        lofted = True
                        emit_loft(bmvs_a, bmvs_b, axis)

        if not lofted:
            for kind, shape, bmvs in cycles:
                before = len(L.previz)
                tried = False
                if kind == 'rect':
                    c0, c1, c2, c3 = map(len, shape)
                    if c0 == c2 and c1 == c3:
                        s0, s1, s2, s3 = shape
                        sv0, sv1, sv2, sv3 = get_verts(s0), get_verts(s1), get_verts(s2, True), get_verts(s3, True)
                        if sv0[-1] not in sv1: sv0.reverse()
                        if sv1[-1] not in sv2: sv1.reverse()
                        if sv2[-1] not in sv1: sv2.reverse()
                        if sv3[-1] not in sv2: sv3.reverse()
                        if not emit_rect_grid(sv0, sv1, sv2, sv3, 'rect'): break
                        tried = True
                if not tried:
                    # unequal opposite sides, or not four-sided: grid fill
                    if not emit_grid_fill(bmvs, 'grid'): break
                if len(L.previz) > before: continue
                # nothing to fill inside (already faces, or not griddable): step the loop outward instead
                bmes = cycle_bmes(bmvs)
                if bmes and not emit_offset(bmvs, bmes, cyclic=True): break

        ##############################################
        # L: two strips meeting at a corner; the other two sides are created

        for shape in shapes['L']:
            CONCAVE_PULL = 0.5      # how far a side leaning into the patch pulls the fourth corner in, per unit of lean
            s0, s1 = shape
            sv0, sv1 = get_verts(s0), get_verts(s1)
            l0, l1 = len(sv0), len(sv1)
            if sv0[-1] not in sv1: sv0.reverse()
            if sv1[0] not in sv0: sv1.reverse()

            symmetry0 = sym_axes(sv0[0].co)
            symmetry1 = sym_axes(sv1[-1].co)
            if symmetry0 and symmetry1: continue    # both free ends on the mirror plane: a triangle, which this cannot fill
            if not budget((l0 - 1) * (l1 - 1)): break

            boundary = sv0 + sv1
            side, cap = shape_side(boundary), shape_cap(boundary)
            nrm = normal_fn(boundary)
            n00, n10, n11 = nrm(sv0[0]), nrm(sv0[-1]), nrm(sv1[-1])
            c00, c10, c11 = sv0[0].co, sv0[-1].co, sv1[-1].co

            # Fourth corner: the parallelogram completion bent to the surface. Each strip's end normals
            # fit a sphere, and the rotation carrying one end to the other is applied to the far corner
            # of the other strip.
            guess_a = _bend_along(c10, n10, c00, n00, c11)     # c11 carried the way sv0 bends
            guess_b = _bend_along(c10, n10, c11, n11, c00)     # c00 carried the way sv1 bends
            n01 = None
            if n00 is not None and n11 is not None:
                n01 = n00 + n11
                n01 = n01.normalized() if n01.length_squared > 1e-12 else n00
            c01 = to_planes(new_point((guess_a + guess_b) / 2, side, n01, cap), symmetry0 | symmetry1)
            n01 = source_normal(c01) or n01

            # The new sides are curves. Each leaves its attached corner along the existing edge there,
            # so the mesh flow carries on through the corner, and arrives mirrored so it bows evenly.
            # The corner stays where the estimate above put it; letting the curves move it made a needle.
            guide_r = guide_direction(sv1[-1], n11, (c11 - sv1[-2].co).normalized(), guess_a - c11)
            guide_b = guide_direction(sv0[0],  n00, (sv0[1].co - c00).normalized(),  guess_b - c00)
            fracs_r = _cumulative_fracs([sv0[k].co for k in range(l0 - 1, -1, -1)])   # from c11 outward
            fracs_b = _cumulative_fracs([v.co for v in sv1])                          # from c00 outward

            # a side whose tangent leans into the patch swoops inward, and two such sides meet the
            # parallelogram corner in a needle: bring the corner in along each chord by the lean
            pull = Vector()
            for (c_att, t0, c_across) in ((c11, guide_r, c00), (c00, guide_b, c11)):
                if t0 is None: continue
                chord = c01 - c_att
                if chord.length_squared < 1e-12: continue
                c = chord.normalized()
                inward = (c_across - c_att) - c * (c_across - c_att).dot(c)
                if inward.length_squared < 1e-12: continue
                lean = t0.dot(inward.normalized())
                if lean > 0: pull -= c * (chord.length * lean * CONCAVE_PULL)
            if pull.length_squared > 1e-14:
                c01 = to_planes(new_point(c01 + pull, side, n01, cap), symmetry0 | symmetry1)
                n01 = source_normal(c01) or n01

            def side_curve(p0, t0, n0, p3, n3, fracs):
                p1, p2, _ = _mirror_curve(p0, t0, p3)
                return ([ _bezier(p0, p1, p2, p3, t) for t in fracs ],
                        [ blend_pair(n0, n3, t) for t in fracs ])

            if guide_r is not None:
                pts, ns = side_curve(c11, guide_r, n11, c01, n01, fracs_r)
                side_r = [ new_point(co, side, n, cap) for co, n in zip(pts, ns) ][::-1]   # indexed by i
            else:
                side_r = [ new_point(co, side, n, cap) for (co, n) in
                           _arc_between(c01, n01, c11, n11, _cumulative_fracs([v.co for v in sv0])) ]
            if guide_b is not None:
                pts, ns = side_curve(c00, guide_b, n00, c01, n01, fracs_b)
                side_b = [ new_point(co, side, n, cap) for co, n in zip(pts, ns) ]          # indexed by j
            else:
                side_b = [ new_point(co, side, n, cap) for (co, n) in
                           _arc_between(c00, n00, c01, n01, fracs_b) ]
            # the ends are the corners themselves, so pin them rather than trusting a snap
            side_r[0], side_r[-1] = c01, c11
            side_b[0], side_b[-1] = c00, c01

            def boundary_at(i, j):
                if i == l0 - 1: return sv1[j]
                if j == 0: return sv0[i]
                return None

            def interior_at(i, j):
                pi, pj = i / (l0 - 1), j / (l1 - 1)
                nl, nt = nrm(sv0[i]), nrm(sv1[j])
                n = blend_normal(nl, nl, nt, nt, n00, n10, n01, n11, pi, pj)
                co = coons(sv0[i].co, side_r[i], side_b[j], sv1[j].co, c00, c10, c01, c11, pi, pj)
                return co, n

            def pin(i, j, pt):
                if i == 0:      pt = to_planes(pt, symmetry0)
                if j == l1 - 1: pt = to_planes(pt, symmetry1)
                return pt

            build_grid('L', l0, l1, boundary_at, interior_at, side, cap, pin=pin)

        ##############################################
        # C: three strips; the missing side is the middle strip carried across by the end strips

        for shape in shapes['C']:
            s0, s1, s2 = shape
            c0, c1, c2 = map(len, shape)
            if c0 != c2: continue
            sv0, sv1, sv2 = get_verts(s0), get_verts(s1), get_verts(s2, True)
            l0, l1 = len(sv0), len(sv1)
            if not budget((l0 - 1) * (l1 - 2)): break
            if sv0[-1] not in sv1: sv0.reverse()
            if sv1[-1] not in sv2: sv1.reverse()
            if sv2[-1] not in sv1: sv2.reverse()

            symmetry0 = sym_axes(sv0[0].co)
            symmetry2 = sym_axes(sv2[0].co)
            use_symmetry = (symmetry0 == symmetry2)

            off0, off2 = sv0[0].co - sv0[-1].co, sv2[0].co - sv2[-1].co
            boundary = sv0 + sv1 + sv2
            nrm = normal_fn(boundary)
            c00, c10, c01, c11 = sv0[0], sv0[-1], sv2[0], sv2[-1]
            n00, n10, n01, n11 = nrm(c00), nrm(c10), nrm(c01), nrm(c11)

            def boundary_at(i, j):
                if i == l0 - 1: return sv1[j]
                if j == 0: return sv0[i]
                if j == l1 - 1: return sv2[i]
                return None

            def interior_at(i, j):
                pi, pj = i / (l0 - 1), j / (l1 - 1)
                off = off0 * (1 - pj) + off2 * pj
                nb = None
                if n00 is not None and n01 is not None:
                    nb = n00 * (1 - pj) + n01 * pj
                n = blend_normal(nrm(sv0[i]), nrm(sv2[i]), nb, nrm(sv1[j]), n00, n10, n01, n11, pi, pj)
                co = coons(sv0[i].co, sv2[i].co, sv1[j].co + off, sv1[j].co, c00.co, c10.co, c01.co, c11.co, pi, pj)
                return co, n

            def pin(i, j, pt):
                return to_planes(pt, symmetry0) if (use_symmetry and i == 0) else pt

            build_grid('C', l0, l1, boundary_at, interior_at, shape_side(boundary), shape_cap(boundary), pin=pin)

        ##############################################
        # I: bridge pairs of facing strips; a strip with no partner steps outward

        # TODO (from v3): check that the bridge is not created on a side that already has geometry
        bridged = set()
        for i0, shape0 in enumerate(shapes['I']):
            sv0 = get_verts(shape0[0])
            dir0 = (sv0[0].co - sv0[-1].co).normalized()
            best_sv1, best_dist, best_i1 = None, 0, None
            for i1, shape1 in enumerate(shapes['I']):
                if i1 <= i0: continue
                sv1 = get_verts(shape1[0])
                dir1 = (sv1[0].co - sv1[-1].co).normalized()
                if dir0.dot(dir1) < 0:
                    sv1 = list(reversed(sv1))
                    dir1 = -dir1
                # the strips must face each other, not lie end to end
                if _angle_deg(dir0, (sv1[0].co - sv0[0].co).normalized()) < 45: continue
                if _angle_deg(dir1, (sv0[0].co - sv1[0].co).normalized()) < 45: continue
                dist = min((v0.co - v1.co).length for v0 in sv0 for v1 in sv1)
                if best_sv1 and best_dist < dist: continue
                best_sv1 = sv1
                best_dist = dist
                best_i1 = i1
            if not best_sv1: continue
            # both strips are spoken for even if the bridge is refused below: two strips lined up ask
            # for a bridge, not for each to step outward on its own
            bridged |= {i0, best_i1}
            sv1, dist = best_sv1, best_dist
            avg0 = (sv0[0].co - sv0[-1].co).length / max(1, len(sv0) - 1)
            avg1 = (sv1[0].co - sv1[-1].co).length / max(1, len(sv1) - 1)
            gap = derive_loops(dist, max(avg0, avg1)) + 1    # edges across the gap
            L.has_bridge = True
            L.loops_last = gap - 1
            boundary = sv0 + sv1

            if len(sv0) != len(sv1):
                # uneven sides: the two sides this fill creates close the region into a four-cornered
                # loop, which is the grid fill's problem
                if (len(sv0) + len(sv1)) % 2: continue    # odd perimeter however many loops are added
                if not budget(2 * max(0, gap - 1)): break
                side, cap = shape_side(boundary), shape_cap(boundary)
                nrm = normal_fn(boundary)
                def connect(a, b, _gap=gap, _side=side, _cap=cap, _nrm=nrm):
                    # interior points of one of the created sides, from a to b
                    return [ new_point(a.co * (1 - t / _gap) + b.co * (t / _gap), _side,
                                       blend_pair(_nrm(a), _nrm(b), t / _gap), _cap)
                             for t in range(1, _gap) ]
                loop = (list(sv0) + connect(sv0[-1], sv1[-1])
                        + list(reversed(sv1)) + connect(sv1[0], sv0[0]))
                if not emit_grid_fill(loop, 'bridge'): break
                continue

            if not emit_span('I', sv0, sv1, gap + 1, boundary): break

        for i0, shape0 in enumerate(shapes['I']):
            if i0 in bridged: continue
            if not emit_offset(get_verts(shape0[0]), shape0[0]): break

        if sel_quad is not None: emit_quad_strip(sel_quad, 'quad')
        if sel_tri is not None: emit_tri(sel_tri)
        if lone_bmv is not None: emit_corner_quad(lone_bmv)

        ##############################################
        # cursor pick: while Ctrl (or F from another tool) is held and the selection previews nothing,
        # the cursor picks a quad from the verts nearest it, or extends the nearest open edge or corner.
        # Gated on the selection's preview, not on there being a selection, so a stray selected vert
        # does not switch the hover off.

        L.nearest_sig = L.hover_sig = None
        if L.previz or not ctrl_at or L.error: return
        # Two or more selected verts are a selection Blender's own F can act on, so with nothing to
        # fill the key belongs to it, not to a quad guessed from whatever the cursor is near. One
        # stray vert is not enough for Blender's F, so the pick still runs there.
        if len(sel_verts) >= 2: return
        key = L._candidate_key(context)
        if key is None: return
        if key != L.cand_key: L._collect_candidates(bm, key)
        # on from here whatever is offered: track_mouse re-picks per move only while this is set, and a
        # drag that has just made a patch relies on that to notice the cursor leaving it
        L.nearest_active = True
        if L.drag_last is not None and L._cursor_in_polys(context, mouse_at, L.drag_last): return
        pv = L.pick_nearest_quad(context, bm, M, mouse_at)
        if pv is not None:
            L.nearest_sig = frozenset(pv.vert_idx)
            emit_quad_strip([ bm.verts[i] for i in pv.vert_idx ], 'nearest')
        else:
            hit = L.pick_nearest_extend(context, bm, M, mouse_at)
            if hit is None: return
            kind, elem = hit
            L.hover_sig = (kind, elem.index)
            if kind == 'edge':
                v0, v1 = elem.verts
                emit_offset([v0, v1], [elem])
            else:
                emit_corner_quad(elem)
        for pv in L.previz: pv.hover = True

    ##############################################
    # events from the overlay

    @staticmethod
    def track_ctrl(context : Context, event : Event) -> bool:
        ''' Follow the Ctrl key, which turns the cursor pick on and off. True when the preview changed. '''
        L = LegacyPatches_Logic
        held = bool(event.ctrl) or L.ctrl_forced
        if held == L.ctrl: return False
        L.ctrl = held
        if held:
            L.dirty = True      # the rebuild works out that nothing is selected and turns the pick on
        elif L.nearest_active:
            # only the cursor pick can be showing with nothing selected, so drop it
            L.previz = []
            L.nearest_sig = L.hover_sig = None
            L.nearest_active = False
        return True

    @staticmethod
    def track_mouse(context : Context, event : Event) -> bool:
        ''' Follow the cursor. A wire run steps toward the mouse and the cursor pick follows it, but a
        full rebuild per move would cost a snap per vert per frame, so this only goes dirty when the
        answer changes. True when the caller should redraw. '''
        L = LegacyPatches_Logic
        L.mouse = (event.mouse_x, event.mouse_y)
        if not context.edit_object: return False
        rgn, r3d = context.region, context.region_data
        if not rgn or not r3d: return False
        M = context.edit_object.matrix_world

        if (L.ctrl or L.ctrl_forced) and L.nearest_active and L.cand_key is not None and L.cand_key == L._candidate_key(context):
            if L.drag_last is not None and L._cursor_in_polys(context, L.mouse, L.drag_last):
                # a drag still inside the patch it just made shows nothing
                if not L.previz and L.nearest_sig is None and L.hover_sig is None: return False
                L.previz = []
                L.nearest_sig = L.hover_sig = None
                return True
            # Re-pick per move: the candidates are already projected and nothing here snaps a vert.
            # Deliberately does not set dirty, since a rebuild would re-scan the mesh for the same
            # answer; a mesh edit fails the key test above and the next update() rebuilds.
            try:
                bm = bmesh.from_edit_mesh(context.edit_object.data)
                bm.verts.ensure_lookup_table()
                pv = L.pick_nearest_quad(context, bm, M, L.mouse)
                hit = L.pick_nearest_extend(context, bm, M, L.mouse) if pv is None else None
            except (ReferenceError, RuntimeError):
                pv, hit = None, None
            hsig = (hit[0], hit[1].index) if hit is not None else None
            if hsig != L.hover_sig:
                # a new edge or corner to extend: its step snaps new verts, so only a rebuild can build it
                L.hover_sig = hsig
                L.dirty = True
                return True
            if hsig is None:
                sig = frozenset(pv.vert_idx) if pv is not None else None
                if sig != L.nearest_sig:
                    # show the plain quad at once, and rebuild too, which is what snaps its cuts
                    L.previz = [pv] if pv is not None else []
                    L.nearest_sig = sig
                    L.dirty = True
                    return True
                return False
            # an extend preview is showing: a wire edge among them still follows the cursor's side below

        if not L.wire_runs: return False
        mouse = Vector(mouse_from_event(event))
        for co_a, co_b, sign in L.wire_runs:
            pa, pb = location_3d_to_region_2d(rgn, r3d, M @ co_a), location_3d_to_region_2d(rgn, r3d, M @ co_b)
            if not pa or not pb: continue
            s = _side2d(pa, pb, mouse)
            if s and s != sign:
                L.dirty = True
                return True
        return False

    ##############################################
    # cursor pick candidates

    @staticmethod
    def _candidate_key(context : Context) -> tuple | None:
        RFCore = RFGlobals.RFCore_None
        obj = context.edit_object
        if not RFCore or not obj: return None
        return (RFCore.depsgraph_version, obj.name)

    @staticmethod
    def _collect_candidates(bm, key : tuple):
        ''' Verts the cursor pick may use: loose points and verts on an open border, so a quad can
        close onto existing geometry. Interior verts are excluded since a quad there would overlap the
        mesh. One O(V) pass, kept until the mesh changes. '''
        L = LegacyPatches_Logic
        flat, idx = [], []
        for bmv in bm.verts:
            if bmv.hide: continue
            # an isolated vert has is_wire and is_boundary both False, so test link_faces first;
            # is_manifold is no good since a vert on an open border is manifold
            if bmv.link_faces and not bmv.is_boundary: continue
            idx.append(bmv.index)
            flat.extend(bmv.co)
        L.cand_idx = idx
        L.cand_cos = np.array(flat, dtype=np.float64).reshape(len(idx), 3) if idx else None
        # the open edges, for the hover extend; both ends of an open edge are always candidates
        pos = { vi: k for k, vi in enumerate(idx) }
        open_count, pairs = [0] * len(idx), []
        for bme in bm.edges:
            if bme.hide or len(bme.link_faces) >= 2: continue
            ka, kb = pos.get(bme.verts[0].index), pos.get(bme.verts[1].index)
            if ka is None or kb is None: continue
            open_count[ka] += 1
            open_count[kb] += 1
            pairs.append((ka, kb))
        L.cand_open = np.array(open_count, dtype=np.int64) if idx else None
        L.cand_edges = np.array(pairs, dtype=np.int64).reshape(-1, 2)
        L.cand_key = key
        L.proj_key = None

    @staticmethod
    def _candidates_near(context : Context, bm, co_local, radius : float, k : int = 8) -> list:
        ''' Candidate verts within radius (local units) of a point, nearest first, at most k. '''
        L = LegacyPatches_Logic
        key = L._candidate_key(context)
        if key is None or radius <= 0: return []
        if key != L.cand_key: L._collect_candidates(bm, key)
        if L.cand_cos is None: return []
        d2 = ((L.cand_cos - np.array(co_local, dtype=np.float64)) ** 2).sum(axis=1)
        near = np.flatnonzero(d2 <= radius * radius)
        if len(near) == 0: return []
        if len(near) > k:
            near = near[np.argpartition(d2[near], k)[:k]]
        near = near[np.argsort(d2[near])]
        out = []
        try:
            nverts = len(bm.verts)
            for j in near:
                vi = L.cand_idx[j]
                if vi >= nverts: continue
                bmv = bm.verts[vi]
                if not bmv.is_valid or bmv.hide: continue
                if (bmv.co - Vector(L.cand_cos[j])).length_squared > 1e-8: continue
                out.append(bmv)
        except ReferenceError:
            return []
        return out

    @staticmethod
    def _project_candidates(context : Context, M : Matrix):
        ''' Candidates in region pixels, NaN behind the camera: location_3d_to_region_2d as one array
        op, cached until the view or the mesh changes. '''
        L = LegacyPatches_Logic
        if L.cand_cos is None: return None
        rgn, r3d = context.region, context.region_data
        if not rgn or not r3d: return None
        key = (L.cand_key, r3d.perspective_matrix.copy().freeze(), rgn.width, rgn.height)
        if key == L.proj_key and L.proj_px is not None: return L.proj_px

        M3 = np.array(M.to_3x3(), dtype=np.float64)
        Mt = np.array(M.translation, dtype=np.float64)
        world = L.cand_cos @ M3.T + Mt
        P = np.array(r3d.perspective_matrix, dtype=np.float64)
        clip = np.concatenate([world, np.ones((len(world), 1))], axis=1) @ P.T
        w = clip[:, 3]
        ok = w > 1e-6       # perspective: behind the eye; orthographic: w is always 1
        w = np.where(ok, w, 1.0)
        px = (clip[:, :2] / w[:, None] + 1.0) * 0.5 * np.array([rgn.width, rgn.height])
        px[~ok] = np.nan
        L.proj_px, L.proj_key = px, key
        return px

    @staticmethod
    def _visible(context : Context, k : int, bmv, M : Matrix) -> bool:
        ''' Whether candidate k is not behind the source from the view. One raycast per candidate per
        view, cached against proj_key; only the few nearest candidates of a pick are ever asked. '''
        L = LegacyPatches_Logic
        if L.vis_key != L.proj_key:
            L.vis_cache, L.vis_key = {}, L.proj_key
        vis = L.vis_cache.get(k)
        if vis is None:
            try:
                vis = not is_point_occluded(context, M @ bmv.co, use_xray=True)
            except Exception:
                vis = True
            L.vis_cache[k] = vis
        return vis

    @staticmethod
    def pick_nearest_quad(context : Context, bm, M : Matrix, mouse_win, *, strict : bool = False) -> Previz | None:
        ''' The quad the cursor is in, out of the candidate verts nearest it. Nothing is created, so
        there is no snapping to do. `strict` drops the outline slop: a drag only makes the cells its
        path passes through. '''
        RADIUS_PX = 250     # screen radius a candidate may be from the cursor; generous, since the cursor-inside test does the picking
        K = 8               # nearest candidates whose four-subsets are tried: 70 combinations
        REACH_3D = 1.0      # every corner must be within this many mean side lengths of the surface point under the cursor
        L = LegacyPatches_Logic
        rgn, r3d = context.region, context.region_data
        if mouse_win is None or not rgn or not r3d: return None
        px = L._project_candidates(context, M)
        if px is None or len(px) < 4: return None
        mouse = Vector((mouse_win[0] - rgn.x, mouse_win[1] - rgn.y))

        d2 = np.nansum((px - np.array([mouse.x, mouse.y])) ** 2, axis=1)
        d2 = np.where(np.isnan(px[:, 0]), np.inf, d2)
        radius = Drawing.scale(RADIUS_PX) or RADIUS_PX
        near = np.flatnonzero(d2 <= radius * radius)
        if len(near) < 4: return None
        near = near[np.argsort(d2[near])]

        # resolve cached indices nearest first until K usable ones are in hand. A moved coordinate
        # means the cache predates an edit the rebuild has not caught up with, so offer nothing.
        # Hidden or occluded verts are simply passed over.
        try:
            bmvs, pts2d, cos3d = [], [], []
            nverts = len(bm.verts)
            for k in near:
                if len(bmvs) >= K: break
                vi = L.cand_idx[k]
                if vi >= nverts: return None
                bmv = bm.verts[vi]
                if not bmv.is_valid: return None
                if bmv.hide: continue
                if (bmv.co - Vector(L.cand_cos[k])).length_squared > 1e-8: return None
                if not L._visible(context, k, bmv, M): continue
                bmvs.append(bmv)
                pts2d.append(Vector((px[k][0], px[k][1])))
                cos3d.append(M @ bmv.co)
        except ReferenceError:
            return None

        n = len(bmvs)
        if n < 4: return None
        ranked = []
        for combo in combinations(range(n), 4):
            r = _quad_from_points([pts2d[i] for i in combo], [cos3d[i] for i in combo], mouse)
            if r is None: continue
            order, score = r
            ranked.append((score, tuple(combo[o] for o in order)))
        if not ranked: return None
        ranked.sort(key=lambda e: e[0])

        # the surface point under the cursor anchors the 3D check; off the source the screen tests stand alone
        anchor = raycast_point_valid_sources(context, mouse)

        for score, quad in ranked:
            verts = [bmvs[i] for i in quad]
            if score[0] == 1:
                if strict: break
            elif bm.faces.get(verts):
                # the cursor is inside an existing face; what is left in the running are wide quads
                # reached through the outline slop from the cell next door, so offer nothing
                return None
            if not _face_is_placeable(bm, verts): continue
            if anchor is not None:
                q = [cos3d[i] for i in quad]
                mean_side = sum((q[(i + 1) % 4] - q[i]).length for i in range(4)) / 4
                if any((c - anchor).length > REACH_3D * mean_side for c in q): continue
            edges_out = [ (i, (i + 1) % 4) for i in range(4)
                          if bmvs_shared_bme(verts[i], verts[(i + 1) % 4]) is None ]
            return Previz(
                'nearest',
                [ v.index for v in verts ],
                [ v.co.copy() for v in verts ],
                edges_out,
                [(0, 1, 2, 3)],
                (),
                (),
                hover=True,
            )
        return None

    @staticmethod
    def pick_nearest_extend(context : Context, bm, M : Matrix, mouse_win) -> tuple | None:
        ''' What the cursor would extend when it is in no quad: ('vert', bmv) for a boundary corner
        near it, else ('edge', bme) for a nearby open edge, else None. The vert wins when in range: it
        is the smaller target and always the end of some edge that would otherwise win. '''
        VERT_PX, EDGE_PX = 15, 40   # ui-scaled pick radii
        REACH_3D = 2.0              # the element must be within this many of its own edge lengths of the surface point under the cursor
        L = LegacyPatches_Logic
        rgn, r3d = context.region, context.region_data
        if mouse_win is None or not rgn or not r3d: return None
        px = L._project_candidates(context, M)
        if px is None or len(px) == 0: return None
        mouse = np.array([mouse_win[0] - rgn.x, mouse_win[1] - rgn.y], dtype=np.float64)
        mouse_v = Vector((mouse[0], mouse[1]))

        def resolve(k):
            vi = L.cand_idx[k]
            if vi >= len(bm.verts): return None
            bmv = bm.verts[vi]
            if not bmv.is_valid or bmv.hide: return None
            if (bmv.co - Vector(L.cand_cos[k])).length_squared > 1e-8: return None
            if not L._visible(context, k, bmv, M): return None
            return bmv

        def on_open_side(bme, pa, pb):
            # a row can only go away from the face the edge already has, so a cursor over the mesh is
            # not asking for this edge to step
            if not bme.link_faces: return True
            pf = location_3d_to_region_2d(rgn, r3d, M @ bme.link_faces[0].calc_center_median())
            if pf is None: return True
            return _side2d(pa, pb, mouse_v) != _side2d(pa, pb, pf)

        anchor = raycast_point_valid_sources(context, mouse_v)

        def within_reach(bmv, scale):
            # a far element that is close only on screen is not what the cursor is beside
            return anchor is None or (M @ bmv.co - anchor).length <= REACH_3D * scale

        try:
            d2 = np.nansum((px - mouse) ** 2, axis=1)
            d2 = np.where(np.isnan(px[:, 0]), np.inf, d2)
            if L.cand_open is not None:
                # a corner: two or more open edges meet there. Not while the cursor is over one of its faces.
                corner_d2 = np.where(L.cand_open >= 2, d2, np.inf)
                vert_radius = Drawing.scale(VERT_PX) or VERT_PX
                for k in np.argsort(corner_d2)[:4]:
                    if corner_d2[k] > vert_radius * vert_radius: break
                    bmv = resolve(k)
                    if bmv is None: continue
                    opens = [ (M @ e.other_vert(bmv).co - M @ bmv.co).length for e in bmv.link_edges if len(e.link_faces) < 2 ]
                    if opens and not within_reach(bmv, sum(opens) / len(opens)): continue
                    over_face = False
                    for bmf in bmv.link_faces:
                        pts = [ location_3d_to_region_2d(rgn, r3d, M @ v.co) for v in bmf.verts ]
                        if all(pts) and point_inside_face_2d(mouse_v, pts): over_face = True; break
                    if not over_face: return ('vert', bmv)
            if L.cand_edges is None or len(L.cand_edges) == 0: return None
            A, B = px[L.cand_edges[:, 0]], px[L.cand_edges[:, 1]]
            AB = B - A
            ab2 = (AB ** 2).sum(axis=1)
            ab2 = np.where(ab2 < 1e-12, 1.0, ab2)
            t = np.clip(((mouse - A) * AB).sum(axis=1) / ab2, 0.0, 1.0)
            edge_d2 = ((A + AB * t[:, None] - mouse) ** 2).sum(axis=1)
            edge_d2 = np.where(np.isnan(edge_d2), np.inf, edge_d2)
            edge_radius = Drawing.scale(EDGE_PX) or EDGE_PX
            for k in np.argsort(edge_d2)[:4]:
                if edge_d2[k] > edge_radius * edge_radius: break
                va, vb = resolve(L.cand_edges[k, 0]), resolve(L.cand_edges[k, 1])
                if va is None or vb is None: continue
                bme = bmvs_shared_bme(va, vb)
                if bme is None or bme.hide or len(bme.link_faces) >= 2: continue
                elen = (M @ va.co - M @ vb.co).length
                if not (within_reach(va, elen) and within_reach(vb, elen)): continue
                if not on_open_side(bme, Vector((A[k][0], A[k][1])), Vector((B[k][0], B[k][1]))): continue
                return ('edge', bme)
            return None
        except ReferenceError:
            return None

    @staticmethod
    def _selected_quad(bm, sel_verts, rgn, r3d, M : Matrix) -> list | None:
        ''' Four selected verts as one quad in ring order, when they make a good and legal one. Ordered
        on screen when there is a view, else in the plane the four roughly lie in. '''
        pts = [ location_3d_to_region_2d(rgn, r3d, M @ v.co) for v in sel_verts ] if (rgn and r3d) else [None] * 4
        if all(pts):
            c = sum(pts, Vector((0, 0))) / 4
            order = sorted(range(4), key=lambda k: math.atan2(pts[k].y - c.y, pts[k].x - c.x))
            if not _is_convex_2d([pts[k] for k in order]): return None
        else:
            cos = [ v.co for v in sel_verts ]
            c = sum(cos, Vector()) / 4
            n = Vector()
            for a, b in combinations(range(4), 2):
                for d in range(4):
                    if d in (a, b): continue
                    n += (cos[a] - cos[d]).cross(cos[b] - cos[d])
            if n.length_squared < 1e-18: return None
            n.normalize()
            frame = _plane_frame(n, cos[0] - c)
            if frame is None: return None
            u, w = frame
            order = sorted(range(4), key=lambda k: math.atan2((cos[k] - c).dot(w), (cos[k] - c).dot(u)))
        verts = [ sel_verts[k] for k in order ]
        if _quad_squareness([ M @ v.co for v in verts ]) is None: return None
        if not _face_is_placeable(bm, verts): return None
        return verts

    @staticmethod
    def _selected_tri(bm, sel_verts, M : Matrix) -> list | None:
        ''' Three selected verts as one triangle, when they make a real one and the mesh has room for
        it. No ordering to work out: every pair of a triangle's corners is a side of it. '''
        if not _tri_shape_ok([ M @ v.co for v in sel_verts ]): return None
        if not _face_is_placeable(bm, sel_verts): return None
        return list(sel_verts)

    ##############################################
    # clicks

    @staticmethod
    def mouse_over_previz(context : Context, *, radius2d : float = 10) -> bool:
        ''' Whether the cursor is inside a previewed patch and not on a selected boundary vert, whose
        corner the same click would toggle instead. '''
        L = LegacyPatches_Logic
        edit_object = context.edit_object
        rgn, r3d = context.region, context.region_data
        if not L.previz or not edit_object or not rgn or not r3d: return False
        if L.mouse is None: return False
        # a cursor pick is only offered with the cursor on it, and there is no selected corner to
        # toggle, so measuring again could only disagree and swallow the click
        if all(pv.hover for pv in L.previz): return True

        M = edit_object.matrix_world
        mouse = Vector((L.mouse[0] - rgn.x, L.mouse[1] - rgn.y))
        try:
            r = (Drawing.scale(radius2d) or radius2d) ** 2
            for co in L.boundary_verts.values():
                p = location_3d_to_region_2d(rgn, r3d, M @ co)
                if p and (p - mouse).length_squared < r: return False
            for pv in L.previz:
                pts = {}
                for f in pv.faces:
                    for i in f:
                        if i not in pts: pts[i] = location_3d_to_region_2d(rgn, r3d, M @ pv.vert_co[i])
                    if point_inside_face_2d(mouse, [pts[i] for i in f]): return True
            return False
        except ReferenceError:
            return False

    @staticmethod
    def pick_selected_vert(context : Context, event : Event, *, radius2d : float = 10) -> int | None:
        ''' Index of the selected boundary vert under the cursor, if any. '''
        L = LegacyPatches_Logic
        edit_object = context.edit_object
        if not edit_object or not L.boundary_verts: return None
        rgn, r3d = context.region, context.region_data
        M = edit_object.matrix_world
        mouse = Vector(mouse_from_event(event))
        best, best_d = None, (Drawing.scale(radius2d) or radius2d) ** 2
        for idx, co in L.boundary_verts.items():
            p = location_3d_to_region_2d(rgn, r3d, M @ co)
            if not p: continue
            d = (p - mouse).length_squared
            if d < best_d:
                best, best_d = idx, d
        return best

    @staticmethod
    def toggle_corner(context : Context, event : Event) -> bool:
        L = LegacyPatches_Logic
        L.update(context)
        idx = L.pick_selected_vert(context, event)
        if idx is None: return False

        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        layer = BMVertLayer_Int(bm, CORNER_LAYER)   # may create the layer, which invalidates element refs
        bm.verts.ensure_lookup_table()
        if idx >= len(bm.verts): return False
        bmv = bm.verts[idx]
        if not bmv.select: return False

        # v3: a detected corner becomes forced smooth; otherwise flip between forced corner and forced smooth
        if idx in L.corner_indices:
            layer[bmv] = CORNER_SMOOTH
        else:
            layer[bmv] = CORNER_SMOOTH if layer[bmv] == CORNER_FORCED else CORNER_FORCED

        # the rebuild cannot write, so overrides on unselected verts are pruned here instead
        for other, val in layer:
            if val != CORNER_AUTO and not other.select:
                layer[other] = CORNER_AUTO

        bmesh.update_edit_mesh(em)
        L.dirty = True
        return True

    @staticmethod
    def clear_corners(context : Context) -> bool:
        L = LegacyPatches_Logic
        try:
            if not context.edit_object or context.mode != 'EDIT_MESH': return False
            bm, em = get_bmesh_emesh(context)
            if bm.verts.layers.int.get(CORNER_LAYER) is None: return False
            BMVertLayer_Int.remove(bm, CORNER_LAYER)
            bmesh.update_edit_mesh(em)
            L.dirty = True
            return True
        except Exception as e:
            print(f'LegacyPatches: could not clear corner layer: {e}')
            return False

    ##############################################
    # fill

    @staticmethod
    def fill(context : Context, settings : PatchSettings | None = None) -> bool:
        L = LegacyPatches_Logic
        # rebuild against the settings being applied: on a redo they come from the redo panel
        try:
            L._recompute(context, settings if settings is not None else L.read_settings(context))
        except ReferenceError:
            L._clear_products()
            L.dirty = True
            return False
        if not L.previz: return False
        # the rebuild after a fill previews nothing, so the redo panel and the scroll shortcuts read these
        L.filled_flags = (L.has_bridge, L.has_grid, L.has_loft, L.has_offset, L.has_quad)
        L.filled_loops = L.loops_last or 0
        L.filled_solutions = max(1, len(L.grid_ranked))

        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        nverts = len(bm.verts)

        # resolve every existing vert before creating any, since verts.new() dirties the lookup table
        existing = []
        for pv in L.previz:
            row = []
            for idx, co in zip(pv.vert_idx, pv.vert_co):
                if idx is None:
                    row.append(None)
                    continue
                if idx >= nverts:
                    L.dirty = True
                    return False
                bmv = bm.verts[idx]
                # a step welds onto unselected verts past a corner, so it cannot be held to being selected
                selected = bmv.select or pv.hover or pv.kind in ('offset', 'corner')
                if not bmv.is_valid or not selected or (bmv.co - co).length_squared > 1e-8:
                    L.dirty = True      # stale preview; the next frame rebuilds it
                    return False
                row.append(bmv)
            existing.append(row)

        new_bmvs, new_bmfs, built = [], [], []
        for pv, row in zip(L.previz, existing):
            bmvs = []
            for bmv, co in zip(row, pv.vert_co):
                if bmv is None:
                    bmv = bm.verts.new(co)
                    new_bmvs.append(bmv)
                bmvs.append(bmv)
            built.append(bmvs)
            for f in pv.faces:
                vs = [bmvs[i] for i in f]
                if len(vs) < 3 or len(set(vs)) != len(vs): continue   # faces.new() rejects repeated verts
                if bm.faces.get(vs): continue
                new_bmfs.append(bm.faces.new(vs))

        pin_to_mirror_planes(context, new_bmvs, active_mirror_axes(context))
        orient_bmf_normals(context, new_bmfs, new_faces=True)

        stepped = [ (pv, bmvs) for pv, bmvs in zip(L.previz, built) if pv.kind == 'offset' ]
        hovered = all(pv.hover for pv in L.previz)
        bmops.deselect_all(bm)
        if hovered:
            pass    # a cursor pick was built from nothing selected, and the next one is picked the same way
        elif stepped:
            # only the new row stays selected, so the next rebuild offers the step after it and F walks outward
            for pv, bmvs in stepped:
                bmops.select_iter(bm, [ bmvs[k] for k in pv.row_idx ])
        else:
            bmops.select_iter(bm, new_bmvs)
            bmops.select_iter(bm, new_bmfs)
        BMVertLayer_Int.remove(bm, CORNER_LAYER)    # the overrides only applied to the boundary just filled
        bmops.flush_selection(bm, em)

        # the new patch's own boundary is still selected and still qualifies, so remember it or the
        # next rebuild would offer to fill it again. A step's row is meant to be offered again.
        if stepped or hovered:
            L.filled_sig = None
        else:
            bm.edges.index_update()
            left = [ e for e in bmops.get_all_selected_bmedges(bm) if len(e.link_faces) < 2 and not e.hide ]
            L.filled_sig = L.selection_signature(bm, left)
        L.nearest_sig = L.hover_sig = None
        L.dirty = True
        return True

    ##############################################
    # Ctrl+LMB drag: create what the cursor passes over

    @staticmethod
    def _cursor_in_polys(context : Context, mouse_win, polys) -> bool:
        ''' Whether the cursor is inside any of some local-space face outlines, on screen. '''
        edit_object = context.edit_object
        rgn, r3d = context.region, context.region_data
        if not polys or not edit_object or not rgn or not r3d: return False
        M = edit_object.matrix_world
        m = Vector((mouse_win[0] - rgn.x, mouse_win[1] - rgn.y))
        for poly in polys:
            pts = [ location_3d_to_region_2d(rgn, r3d, M @ co) for co in poly ]
            if all(pts) and point_inside_face_2d(m, pts): return True
        return False

    @staticmethod
    def accept_current(context : Context, mouse_win, *, drag : bool = False) -> bool:
        ''' Create whatever is previewed under the cursor, the way a click would. A drag is stricter:
        the cursor must be inside a face of the preview, not merely near it, and nothing is made
        until the cursor has left the last patch the drag made, so one area gets one patch. '''
        L = LegacyPatches_Logic
        L.mouse = (int(mouse_win[0]), int(mouse_win[1]))
        if not L.previz: return False
        if drag:
            if L._cursor_in_polys(context, L.mouse, L.drag_last): return False
            polys = [ [ pv.vert_co[i] for i in f ] for pv in L.previz for f in pv.faces ]
            if not L._cursor_in_polys(context, L.mouse, polys): return False
        elif not L.mouse_over_previz(context):
            return False
        L.mouse_locked = L.mouse
        L.ctrl_locked = True
        made = L.fill(context, L.read_settings(context))
        if made:
            L.cand_key = None   # the mesh changed under a cache keyed on a version that only bumps after this event
            if drag: L.drag_last = polys
        return made

    @staticmethod
    def drag_start(context : Context, pt, previz) -> bool:
        ''' The stroke began on a preview: make it outright. The fill leaves its geometry selected so
        F can walk on from it, but a drag needs nothing selected or the cursor pick never switches on,
        so that selection is dropped. True when made. '''
        L = LegacyPatches_Logic
        pt = (int(pt[0]), int(pt[1]))
        L.previz = list(previz)
        L.mouse = pt
        if not previz: return False
        polys = [ [ pv.vert_co[i] for i in f ] for pv in previz for f in pv.faces ]
        if not (L._cursor_in_polys(context, pt, polys) or L.mouse_over_previz(context)): return False
        L.mouse_locked = pt
        L.ctrl_locked = True
        if not L.fill(context, L.read_settings(context)): return False
        L.cand_key = None
        L.drag_last = polys
        L.drag_cand = None
        try:
            bm, em = get_bmesh_emesh(context)
            bmops.deselect_all(bm)
            bmops.flush_selection(bm, em)
        except ReferenceError:
            pass
        L.filled_sig = None
        L.dirty = True
        return True

    @staticmethod
    def drag_step(context : Context, pt, previz) -> bool:
        ''' One point of a drag against the preview showing there. A preview becomes a candidate when
        the cursor enters it and is made once the cursor has travelled a fraction of the preview's
        extent in that direction, so brushing into a cell is not the same as drawing through it. '''
        ACCEPT_FRAC = 0.25
        L = LegacyPatches_Logic
        pt = (int(pt[0]), int(pt[1]))
        if not previz or (L.drag_last is not None and L._cursor_in_polys(context, pt, L.drag_last)):
            L.drag_cand = None
            return False
        # order-free key: the per-move pick and the rebuilt preview list the same verts in different orders
        key = tuple(sorted((pv.kind, tuple(sorted(i for i in pv.vert_idx if i is not None))) for pv in previz))
        if L.drag_cand is None or L.drag_cand[0] != key:
            L.drag_cand = (key, pt)
            return False
        entry = L.drag_cand[1]
        travel = Vector((pt[0] - entry[0], pt[1] - entry[1]))
        if travel.length < 1.0: return False
        edit_object = context.edit_object
        rgn, r3d = context.region, context.region_data
        if not edit_object or not rgn or not r3d: return False
        M = edit_object.matrix_world
        d = travel.normalized()
        along = [ p.dot(d) for pv in previz for co in pv.vert_co if (p := location_3d_to_region_2d(rgn, r3d, M @ co)) ]
        if not along: return False
        extent = max(along) - min(along)
        if travel.length < ACCEPT_FRAC * extent: return False
        L.previz = list(previz)
        made = L.accept_current(context, pt, drag=True)
        if made: L.drag_cand = None
        return made

    @staticmethod
    def accept_along(context : Context, p0, p1) -> int:
        ''' Sample the cursor's path between two drag positions so a fast sweep skips no cell, and put
        each sample through drag_step. Only quads whose four verts exist are picked here; an extend
        preview needs the full rebuild, which happens at the event position. Returns how many were
        made. The end point is left for the caller. '''
        SAMPLE_PX = 6
        L = LegacyPatches_Logic
        edit_object = context.edit_object
        if not edit_object: return 0
        M = edit_object.matrix_world
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        steps = max(1, int(math.hypot(dx, dy) // SAMPLE_PX))
        made = 0
        for s in range(1, steps):
            pt = (p0[0] + dx * s / steps, p0[1] + dy * s / steps)
            if L._cursor_in_polys(context, pt, L.drag_last): continue
            try:
                key = L._candidate_key(context)
                if key is None: return made
                if key != L.cand_key or L.cand_cos is None:
                    # indices must be current here: a fill just added verts
                    bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)
                    L._collect_candidates(bm, key)
                else:
                    bm = bmesh.from_edit_mesh(edit_object.data)
                    bm.verts.ensure_lookup_table()
                pv = L.pick_nearest_quad(context, bm, M, pt, strict=True)
            except (ReferenceError, RuntimeError):
                return made
            if L.drag_step(context, pt, [pv] if pv is not None else []): made += 1
        return made

    ##############################################
    # drawing

    @staticmethod
    def draw(context : Context):
        # styled like PolyPen's previews: theme face-select fill, highlight dashed edges, corners as solid points
        L = LegacyPatches_Logic
        edit_object = context.edit_object
        rgn, r3d = context.region, context.region_data
        if not edit_object or not rgn or not r3d: return
        if L.foreign_operator_running(): return
        M = edit_object.matrix_world

        def proj(co):
            return location_3d_to_region_2d(rgn, r3d, M @ co)

        theme = context.preferences.themes[0].view_3d
        highlight = RF_Prefs.get_prefs(context).highlight_color
        color_point   = Color4((highlight[0], highlight[1], highlight[2], 1))
        color_stipple = Color4((theme.face_select[0], theme.face_select[1], theme.face_select[2], 0))
        color_open    = Color4((theme.vertex_select[0], theme.vertex_select[1], theme.vertex_select[2], 1))
        color_mesh    = theme.face_select
        vertex_size   = theme.vertex_size
        color_label   = (1, 1, 0, 1)
        color_shadow  = (0, 0, 0, 0.75)

        try:
            for pv in L.previz:
                pts = [proj(co) for co in pv.vert_co]

                with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                    draw.color(color_mesh)
                    for f in pv.faces:
                        coords = [pts[i] for i in f]
                        if not all(coords): continue
                        c0 = coords[0]
                        for i in range(1, len(coords) - 1):
                            draw.vertex(c0).vertex(coords[i]).vertex(coords[i + 1])

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5, 5], offset=0, color=color_stipple)
                    draw.color(color_point)
                    for i0, i1 in pv.edges:
                        p0, p1 = pts[i0], pts[i1]
                        if p0 and p1: draw.vertex(p0).vertex(p1)

                if pv.open_idx:
                    with Drawing.draw(context, CC_2D_POINTS) as draw:
                        draw.point_size(vertex_size)
                        draw.color(color_open)
                        for k in pv.open_idx:
                            p = pts[k]
                            if p: draw.vertex(p)

            if len(L.drag_path) > 1:
                Drawing.draw2D_linestrip(context, [ Vector((x - rgn.x, y - rgn.y)) for x, y in _smooth_path(L.drag_path) ],
                                         (1, 1, 0, 1), width=2, stipple=[5, 5])

            if L.corner_indices:
                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_point)
                    for idx in L.corner_indices:
                        co = L.boundary_verts.get(idx)
                        if co is None: continue
                        p = proj(co)
                        if p: draw.vertex(p)

            # text last, so it sits on top of the face fill
            for text, cos in L.labels:
                pts = [p for co in cos if (p := proj(co))]
                if not pts: continue
                xy = sum(pts, Vector((0, 0))) / len(pts)
                tw, th = Drawing.get_text_width(text), Drawing.get_text_height(text)
                xy -= Vector((tw / 2, -th / 2))
                Drawing.text_draw2D(text, xy, color=color_label, dropshadow=color_shadow)
            if L.error:
                x = rgn.width / 2 - Drawing.get_text_width(L.error) / 2
                Drawing.text_draw2D(L.error, (x, rgn.height - 60), color=(1, 0.6, 0.6, 1), dropshadow=color_shadow)
        except ReferenceError:
            pass


class DrawGesture:
    ''' The LMB gesture shared by Ctrl held (RFOperator_LegacyPatches_Draw) and F held from another
    tool (the quick switch): a click fills the previewed patch or toggles a corner, a drag draws a
    path and makes whatever the cursor passes over. The owner says which modifier state may start a
    press; once pressed, the rest of the gesture is handled here whatever the modifiers do. '''

    def __init__(self):
        self.pressed = self.dragging = False
        self.press_xy = self.prev_xy = (0, 0)
        self.press_previz = []      # what was previewed under the press; made outright if this becomes a drag
        self.made = 0
        self.used = False           # a click or drag happened at all

    def handle(self, context : Context, event : Event, *, accept_press : bool) -> set[str] | None:
        ''' None when the event is not this gesture's business, else what the modal should return. '''
        L = LegacyPatches_Logic
        mouse = (event.mouse_x, event.mouse_y)

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                if self.pressed or not accept_press: return None
                if not L.previz: L.update(context)    # the preview may not have been drawn yet
                self.pressed, self.dragging = True, False
                self.press_xy = self.prev_xy = mouse
                self.press_previz = list(L.previz)
                self.made = 0
                L.drag_path = [mouse]
                L.drag_last = L.drag_cand = None
                return {'RUNNING_MODAL'}
            if event.value == 'RELEASE':
                if not self.pressed: return None
                self.pressed = False
                self.used = True
                if self.dragging: self._end_drag(context)
                else: self._click(context, event)
                L.drag_path = []
                if context.area: context.area.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.value in {'CLICK', 'DOUBLE_CLICK', 'CLICK_DRAG'} and accept_press:
                return {'RUNNING_MODAL'}    # the press was ours; otherwise the click falls through to shortest-path select
            return None

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'} and self.pressed:
            # the owning modal sits above the overlay, so bring the preview up to date first
            L.track_mouse(context, event)
            if L.dirty: L.update(context)
            L.drag_path.append(mouse)
            if not self.dragging:
                dx, dy = mouse[0] - self.press_xy[0], mouse[1] - self.press_xy[1]
                if dx * dx + dy * dy > mouse_drag() ** 2:
                    self.dragging = True
                    if L.drag_start(context, self.press_xy, self.press_previz):
                        self.made += 1
                        L.update(context)
            if self.dragging:
                n = L.accept_along(context, self.prev_xy, mouse)
                if n:
                    L.update(context)
                    self.made += n
                if L.drag_step(context, mouse, L.previz): self.made += 1
            self.prev_xy = mouse
            if context.area: context.area.tag_redraw()
            return {'PASS_THROUGH'}

        return None

    def finish(self, context : Context):
        ''' The owner is ending: close any drag in progress and clear the drawn path. '''
        if self.dragging: self._end_drag(context)
        self.pressed = False
        LegacyPatches_Logic.drag_path = []

    def _click(self, context : Context, event : Event):
        # a selected boundary vert under the cursor is a corner to toggle; otherwise the click confirms
        # whatever is previewed, wherever it lands. Both go through operators so each is one undo step
        L = LegacyPatches_Logic
        if L.pick_selected_vert(context, event) is not None:
            _ = bpy_ops_retopoflow('legacy_patches_toggle_corner', 'INVOKE_DEFAULT', True)
        elif L.previz:
            _ = bpy_ops_retopoflow('legacy_patches_fill', 'INVOKE_DEFAULT', True)

    def _end_drag(self, context : Context):
        self.dragging = False
        LegacyPatches_Logic.drag_last = LegacyPatches_Logic.drag_cand = None
        if self.made:
            try:
                bpy.ops.ed.undo_push(message='Patches: draw quads')
            except RuntimeError:
                pass
        self.made = 0
