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
    get_bmesh_emesh, BMVertLayer_Int, is_bmvert_corner,
    bmes_shared_bmv, bme_unshared_bmv, bmvs_shared_bme, wind_bmfs_to_match_neighbors,
)
from ..common.object import mirror_threshold
from ..common.bmesh_maths import (
    orient_bmf_normals, check_bmf_normals, fit_plane_of_verts, compute_n, order_rings_along_axis,
)
from ..common.bpy_helper import bpy_ops_retopoflow
from ..common.drawing import Drawing, CC_2D_LINES, CC_2D_TRIANGLES
from ..common.maths import view_forward_direction
from ..common.operator import RFOperator, rf_is_running
from ..common.raycast import (
    nearest_point_valid_sources, nearest_point_normal_valid_sources, raycast_ray_valid_sources,
    iter_all_valid_sources, mouse_from_event, is_point_occluded, raycast_point_valid_sources,
    region_2d_to_location_3d_stable,
)
from ..common.segments import active_mirror_axes, pin_to_mirror_planes
from ..common.accel import SourceCache
from ..common.snapping import source_snap_radius, source_snap_settings
from . import ngon_layout as NL


MAIN_OP_IDNAME = 'retopoflow.legacy_patches'

DEBUG_OFFSET = False     # print how a run steps: its shape, welds, direction, and why a row is refused
DEBUG_NOTCH  = False     # print the arms a notched hole is squared by, and where the pass gave up
DEBUG_FILL   = False     # print why a closed loop's fill was refused: snap noise, drift, existing faces, folds

CORNER_PICK_PX = 18      # how near a Ctrl+click must land to a selected boundary vert to toggle it as a corner; a near miss must not fill instead
POLE_PICK_PX = 14        # how near the cursor must be to an n-sided fill's pole handle for LMB to drag it rather than select

# Corner overrides live in a per-vert int layer, so they survive depsgraph updates and undo
CORNER_LAYER = 'rf_legacy_patches_corner'
CORNER_AUTO, CORNER_FORCED, CORNER_SMOOTH = 0, 1, 2


@dataclass
class PatchSettings:
    ''' Settings read by rebuild checks; these also match the tool properties. '''
    split_angle      : float = math.radians(60)   # deviation from straight that makes a boundary vert a corner
    smooth           : int = 3
    span_insert_mode : str = 'FIXED'
    crosses          : int = 0
    span_length      : float = 0.1
    solution         : int = 1      # which of a loop's ranked fills, 1 the best, wrapping
    offset           : int = 0      # which placement of that fill: a grid's corners, a pole's spokes, a junction's column
    twist            : int = 0      # loft: rotate the loop pairing this many verts
    steps            : int = 1      # offset: rows of quads to step outward
    step_scale       : float = 1.0  # offset: scales how far a row that extrudes freely reaches
    solve            : str = ''     # which kind of fill, where the selection could take more than one

PATCH_SETTING_NAMES = tuple(f.name for f in fields(PatchSettings))

SOLVE_LABELS = {    # Solve enum: what each kind of fill is called and what it does
    'LOFT':   ('Loft',      'Bridge each selected loop to the next'),
    'BRIDGE': ('Bridge',    'Bridge the two selected strips to each other'),
    'FILL':   ('Grid Fill', 'Fill the area the selection encloses with quads'),
    'FACE':   ('N-Gon',     'Close the area the selection encloses with one face'),
    'STEP':   ('Face Step', 'Step the selection outward into a new row of faces'),
}

LOOP_FLATNESS = 0.2     # how far off its own plane a loop may wander, against its width, and still read as flat

def loop_is_flat(cos):
    ''' Whether a closed run of points lies near enough to one plane to be worth covering with a patch.
    A flat loop is a hole asking to be filled; one that wanders is the mouth of a form, where a fill
    would cut the corner and stepping it outward is usually what was wanted. '''
    n = len(cos)
    if n < 3: return False
    ctr = sum(cos, Vector()) / n
    nrm = compute_n(cos)
    if nrm.length_squared < 1e-12: return False
    span = max((co - ctr).length for co in cos)
    if span < 1e-9: return False
    return max(abs((co - ctr).dot(nrm)) for co in cos) <= LOOP_FLATNESS * span


def loop_area_normal(cos):
    ''' Vector area of a closed run of points. '''
    # The normal of the plane it lies in, scaled by the area it encloses and signed
    # by the way it winds, so the loop runs counter-clockwise about it.
    n = Vector()
    for a, b in zip(cos, cos[1:] + cos[:1]): n += a.cross(b)
    return n / 2


##############################################
# geometry helpers

def angle_deg(d0, d1):
    return math.degrees(math.acos(max(-1.0, min(1.0, d0.dot(d1)))))

def side2d(pa, pb, p):
    ''' Side of the line pa->pb that p lies on: +1, -1, or 0. '''
    c = (pb.x - pa.x) * (p.y - pa.y) - (pb.y - pa.y) * (p.x - pa.x)
    return 0 if abs(c) < 1e-6 else (1 if c > 0 else -1)

def segments_cross2d(p0, p1, q0, q1):
    ''' Whether two 2D segments properly cross: each has the other's ends on opposite sides of it.
    Touching or collinear ends do not count. '''
    s1, s2 = side2d(p0, p1, q0), side2d(p0, p1, q1)
    s3, s4 = side2d(q0, q1, p0), side2d(q0, q1, p1)
    return bool(s1 and s2 and s3 and s4 and s1 != s2 and s3 != s4)

def polys_overlap2d(a, b, *, eps=0.5):
    ''' Whether two 2D outlines overlap. '''
    ca = sum(a, Vector((0, 0))) / len(a)
    cb = sum(b, Vector((0, 0))) / len(b)
    if point_inside_face_2d(ca, b) or point_inside_face_2d(cb, a): return True
    for i in range(len(a)):
        p0, p1 = a[i], a[(i + 1) % len(a)]
        for j in range(len(b)):
            q0, q1 = b[j], b[(j + 1) % len(b)]
            if any((p - q).length < eps for p in (p0, p1) for q in (q0, q1)): continue     # sides sharing a corner: a proper tiling does that everywhere
            if segments_cross2d(p0, p1, q0, q1): return True
    return False

def same_side_of_edge(co_a, co_b, centres_a, centres_b) -> bool:
    ''' Whether two face groups lie on the same side of edge a-b. '''
    d = co_b - co_a
    if d.length_squared < 1e-14: return False
    def arm(c):
        # the cross of the edge with the direction to a centre points one way per side, so no normal or view is needed
        r = d.cross(c - co_a)
        return r if r.length_squared > 1e-14 else None
    arms_b = [ r for c in centres_b if (r := arm(c)) is not None ]
    if not arms_b: return False
    return any(ra.dot(rb) > 0
               for c in centres_a if (ra := arm(c)) is not None
               for rb in arms_b)

def co_of(pt):
    ''' Coordinate for a patch corner, whether it already exists or will be created. '''
    return pt.co if isinstance(pt, BMVert) else pt

def point_in_polygon_2d(q, poly):
    ''' Even-odd test, so a concave outline reads right. '''
    inside = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a.y > q.y) != (b.y > q.y) and q.x < a.x + (b.x - a.x) * (q.y - a.y) / (b.y - a.y): inside = not inside
    return inside

def dist2d_point_segment(p, a, b):
    d = b - a
    dd = d.length_squared
    if dd < 1e-12: return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(d) / dd))
    return (p - (a + d * t)).length

def plane_frame(n, ref):
    ''' Unit vectors spanning the plane normal to n, with u along ref. '''
    u = ref - n * ref.dot(n)
    if u.length_squared < 1e-18: return None
    u.normalize()
    return u, n.cross(u)

OVER_FACE_MAX_TILT = 45.0   # degrees a point may rise out of a one-sided edge's face plane and still lie over that face

def on_faced_side(bme, co):
    ''' Whether co lies over the face of a one-sided edge: on the face's side of it and near the face's
    plane. None when there is no telling. '''
    va, vb = bme.verts
    along = vb.co - va.co
    if along.length_squared < 1e-14: return None
    along.normalize()
    mid = (va.co + vb.co) / 2
    bmf = bme.link_faces[0]
    to_face = bmf.calc_center_median() - mid
    to_co = co - mid
    to_face -= along * to_face.dot(along)
    to_co -= along * to_co.dot(along)
    if to_face.length_squared < 1e-14 or to_co.length_squared < 1e-14: return None
    if to_face.dot(to_co) <= 0: return False
    # A patch closing a box across its rim snaps onto the source a hair below the rim. What tells it from a
    # patch laid over an island is that it leaves the walls' planes steeply rather than lying in them.
    n = bmf.normal if bmf.normal.length_squared > 1e-12 else compute_n([ v.co for v in bmf.verts ])
    if n.length_squared < 1e-12: return True
    return abs(to_co.normalized().dot(n.normalized())) <= math.sin(math.radians(OVER_FACE_MAX_TILT))

def quad_crosses_itself(cos):
    ''' Whether a quad is a bowtie: two of its sides cross and it faces both ways at once.  '''
    if len(cos) != 4: return False
    nrm = (cos[2] - cos[0]).cross(cos[3] - cos[1])
    if nrm.length_squared < 1e-18: return False
    frm = plane_frame(nrm.normalized(), cos[1] - cos[0])
    if frm is None: return False
    u, w = frm
    # in units of the quad's own size, so side2d's absolute tolerance reads the same at any mesh scale
    scale = 1 / math.sqrt(nrm.length)
    p = [ Vector((co.dot(u), co.dot(w))) * scale for co in cos ]
    return segments_cross2d(p[0], p[1], p[2], p[3]) or segments_cross2d(p[1], p[2], p[3], p[0])

def quad_area3d(cos):
    # exact for a planar quad, close enough for the nearly planar ones the shape test lets through
    return 0.5 * (cos[2] - cos[0]).cross(cos[3] - cos[1]).length

def is_convex_2d(pts):
    ''' Whether four points in ring order form a convex quad. '''
    signs = { side2d(pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]) for i in range(4) }
    return 0 not in signs and len(signs) == 1

def quad_squareness(q):
    ''' Quad score, where 1.0 is a perfect square. Returns None for poor fits. '''
    MIN_SQUARENESS = 0.15                # floor on the score: a 55 degree lean on a square, 45 on a 2:1, 37 on a 3:1
    MAX_EDGE_RATIO = 3.5                 # longest side over shortest; aspect weighs lightly in the score, so a long strip needs its own limit
    MAX_WARP = 45.0                      # angle between the triangle normals across a diagonal
    # Skew (a rhombus) is punished harder than aspect (a rectangle): a leaning quad is rarely wanted,
    # a 2:1 quad is ordinary retopo. With the caller dividing area by this, a square beats a 45
    # degree rhombus up to 4x its area and a 2:1 rectangle up to 1.7x.
    SKEW_WEIGHT, ASPECT_WEIGHT = 2.0, 0.75

    sides = [q[(i + 1) % 4] - q[i] for i in range(4)]
    lens = [s.length for s in sides]
    if min(lens) < 1e-9: return None
    if max(lens) / min(lens) > MAX_EDGE_RATIO: return None

    # a corner at 0 or 180 scores nothing, so collinear corners fall through the floor without a test of their own
    worst_corner = max(abs(angle_deg(-sides[i - 1].normalized(), sides[i].normalized()) - 90.0) for i in range(4))

    for d in (0, 1):
        n0 = (q[(d + 1) % 4] - q[d]).cross(q[(d + 2) % 4] - q[d])
        n1 = (q[(d + 2) % 4] - q[d]).cross(q[(d + 3) % 4] - q[d])
        if n0.length_squared < 1e-18 or n1.length_squared < 1e-18: return None
        if angle_deg(n0.normalized(), n1.normalized()) > MAX_WARP: return None

    score = (1.0 - worst_corner / 90.0) ** SKEW_WEIGHT * (min(lens) / max(lens)) ** ASPECT_WEIGHT
    return score if score >= MIN_SQUARENESS else None

def solved_loft_band(bm, sel_bmes):
    """ Already-solved loft band as (faces, inner edges) by vertex index. """
    sel = set(sel_bmes)
    NOTHING = ((), ())
    if not sel: return NOTHING

    # the selected edges as runs, each one a loop only when every vert on it meets two of them
    run_of, met = {}, {}
    for bme in sel:
        for bmv in bme.verts: met[bmv] = met.get(bmv, 0) + 1
    root = { bmv: bmv for bmv in met }
    def root_of(bmv):
        while root[bmv] is not bmv:
            root[bmv] = root[root[bmv]]
            bmv = root[bmv]
        return bmv
    for bme in sel:
        a, b = root_of(bme.verts[0]), root_of(bme.verts[1])
        if a is not b: root[a] = b
    runs = {}
    for bmv, n in met.items(): runs.setdefault(root_of(bmv), []).append(n)
    closed = { r for r, ns in runs.items() if all(n == 2 for n in ns) }
    if len(closed) < 2: return NOTHING
    for bme in sel: run_of[bme] = root_of(bme.verts[0])

    # Loops that are all open boundaries should fill their holes instead
    if all(all(len(e.link_faces) < 2 for e in sel if run_of[e] is r) for r in closed):
        return NOTHING

    # face regions that stop at the selected edges, keeping the ones walled in by two or more loops
    seen, kept = set(), []
    for bme in sel:
        for start in bme.link_faces:
            if start in seen: continue
            region, stack, touched, open_rim = set(), [start], set(), False
            while stack:
                bmf = stack.pop()
                if bmf in region: continue
                region.add(bmf)
                for e in bmf.edges:
                    if e in sel:
                        touched.add(run_of[e])
                        continue
                    if len(e.link_faces) < 2: open_rim = True   # runs off a rim of its own, not walled in
                    stack.extend(g for g in e.link_faces if g is not bmf)
            seen |= region
            if not open_rim and len(touched & closed) >= 2: kept.append(region)

    # a stack of n loops has n - 1 gaps; more regions than that is not a stack
    if len(kept) != len(closed) - 1: return NOTHING

    # The old solution goes whole: its faces, and the edges inside it that the loops do not own. Any
    # ring it left between the loops hangs off those alone, so it goes with them rather than staying
    # behind as loose wire inside the new loft.
    faces = [ f for region in kept for f in region ]
    inner = { e for f in faces for e in f.edges if e not in sel }
    return (tuple(tuple(v.index for v in f.verts) for f in faces),
            tuple((e.verts[0].index, e.verts[1].index) for e in inner))


def delete_band(bm, band, *, faces_only=False):
    """ Remove a solved loft band from `bm`. Returns False if it is already gone. """
    faces, inner = band
    doomed = []
    for idxs in faces:
        bmf = bm.faces.get([ bm.verts[i] for i in idxs ])
        if bmf is None: return False
        doomed.append(bmf)
    bmesh.ops.delete(bm, geom=doomed, context='FACES_ONLY')
    if faces_only: return True
    bmes = [ e for a, b in inner if (e := bm.edges.get((bm.verts[a], bm.verts[b]))) ]
    if bmes: bmesh.ops.delete(bm, geom=bmes, context='EDGES')
    return True


def blend_handle_length(co_a, no_a, co_b, no_b):
    ''' Length for the two Bezier handles joining co_a to co_b along the tangents no_a and no_b, both
    pointing at the other end, sized so the curve is the cubic approximation of the circular arc those
    tangents describe. '''
    # For a turn angle phi, the cubic approximation uses a 4/3 handle scale.
    ARC_FAC = 4.0 / 3.0
    # across the plane the two tangents span, so the ends sitting off to one side of each other
    # does not inflate the handles
    d = co_b - co_a
    perp = no_a.cross(no_b)
    if perp.length_squared > 1e-12:
        perp.normalize()
        d = d - perp * d.dot(perp)
    phi = math.acos(max(-1.0, min(1.0, -no_a.dot(no_b))))
    # both ends of the ratio go to zero with phi, where the arc is a straight line and the limit is 1/2
    shape = math.tan(phi / 4) / math.sin(phi / 2) if phi > 1e-6 else 0.5
    return d.length * 0.5 * ARC_FAC * shape


def surface_tangent(bme):
    ''' Tangent of the face that continues past a single-sided edge. '''
    if len(bme.link_faces) != 1: return None
    bmf = bme.link_faces[0]
    d = bme.verts[1].co - bme.verts[0].co
    if d.length_squared < 1e-18: return None
    w = bme.verts[0].co - sum((v.co for v in bmf.verts), Vector()) / len(bmf.verts)
    w = w - d * (w.dot(d) / d.length_squared)
    return w.normalized() if w.length_squared > 1e-18 else None


def run_surface_tangents(sv, toward):
    ''' Surface tangents for a run of verts, aligned with the bridge direction. '''
    tans = []
    for i, bmv in enumerate(sv):
        acc = Vector()
        for other in (sv[i - 1] if i else None, sv[i + 1] if i + 1 < len(sv) else None):
            if not (isinstance(bmv, BMVert) and isinstance(other, BMVert)): continue
            bme = bmvs_shared_bme(bmv, other)
            if bme and (t := surface_tangent(bme)) is not None: acc += t
        tans.append(acc.normalized() if acc.length_squared > 1e-18 else None)
    if all(t is None for t in tans): return None
    # one sign for the whole run: flipping per vert would kink the bridge wherever the surface turns over
    if sum(t.dot(u) for t, u in zip(tans, toward) if t is not None) < 0:
        tans = [ (-t if t is not None else None) for t in tans ]
    return tans


def tri_shape_ok(cos):
    ''' Whether three points make a usable triangle. '''
    MIN_ANGLE = 20.0    # three verts along a strip are nearly straight: stepping the strip was wanted there, not a sliver across them
    sides = [cos[(i + 1) % 3] - cos[i] for i in range(3)]
    if min(s.length for s in sides) < 1e-9: return False
    return all(angle_deg(-sides[i - 1].normalized(), sides[i].normalized()) >= MIN_ANGLE for i in range(3))

def quad_from_points(pts2d, cos3d, mouse):
    ''' Quad fit for four points, returning order, score, and cost or None. '''
    HOVER_SLOP = 0.25       # how far outside the outline the cursor may sit, in mean side lengths

    # sorting by angle round the centroid is the one order that does not self-intersect
    centre2d = sum(pts2d, Vector((0, 0))) / 4
    order = sorted(range(4), key=lambda k: math.atan2(pts2d[k].y - centre2d.y, pts2d[k].x - centre2d.x))
    p = [pts2d[k] for k in order]
    if not is_convex_2d(p): return None

    # four nearby points pair up several ways; the cursor says which quad is meant, as in Maya
    mean_side = sum((p[(i + 1) % 4] - p[i]).length for i in range(4)) / 4
    inside = point_inside_face_2d(mouse, p)
    if not inside:
        if min(dist2d_point_segment(mouse, p[i], p[(i + 1) % 4]) for i in range(4)) > HOVER_SLOP * mean_side:
            return None

    # shape in 3D, where the quad lives: a quad can look square on screen and be a sliver seen face-on
    squareness = quad_squareness([cos3d[k] for k in order])
    if squareness is None: return None

    # Screen area over squareness. The smallest quad holding the cursor is usually the one meant,
    # but size alone kept offering rhombuses, and shape alone reached clean across the mesh. The
    # shape floor in quad_squareness keeps a barely passing sliver from winning on size alone.
    area = abs(sum(p[i].x * p[(i + 1) % 4].y - p[(i + 1) % 4].x * p[i].y for i in range(4))) / 2
    cost = area / squareness
    dist = sum((pt - mouse).length_squared for pt in p)
    return order, (0 if inside else 1, cost, dist)

def corner_overlaps_faces(bmv, co_prev, co_next, *, tol_deg=5.0):
    ''' Whether the wedge of directions a new quad takes up at bmv overlaps a face already there,
    beyond the tolerance that lets them share an edge. '''
    faces = [ f for f in bmv.link_faces if not f.hide ]
    if not faces: return False
    n = sum((f.normal for f in faces), Vector())
    if n.length_squared < 1e-18: return False
    n.normalize()
    frame = plane_frame(n, co_prev - bmv.co)
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

def mesh_juts_into_face(verts, cos, is_existing, *, depth=3):
    ''' Whether an existing vert lies inside the face or an existing edge crosses one of its sides,
    judged in the face's plane, among the mesh a few edges out from its corners and the loose
    points the candidate cache knows nearby. '''
    n_pts = len(cos)
    centre = sum(cos, Vector()) / n_pts
    # crossing a quad's diagonals averages out its warp; a triangle is flat, so two of its sides do
    n = (cos[2] - cos[0]).cross(cos[3] - cos[1]) if n_pts == 4 else (cos[1] - cos[0]).cross(cos[2] - cos[0])
    if n.length_squared < 1e-18: return False
    n.normalize()
    frame = plane_frame(n, cos[1] - cos[0])
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
        return min(dist2d_point_segment(p, poly[i], poly[(i + 1) % n_pts]) for i in range(n_pts)) > eps

    def crosses(pa, pb):
        for i in range(n_pts):
            qa, qb = poly[i], poly[(i + 1) % n_pts]
            s1, s2 = side2d(pa, pb, qa), side2d(pa, pb, qb)
            s3, s4 = side2d(qa, qb, pa), side2d(qa, qb, pb)
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

def face_is_placeable(bm, verts):
    ''' face_is_placeable_now, remembered while a stroke is down: the mesh cannot change then, and the
    weld fit asks the same of the same corners on every rebuild. '''
    stroke = LegacyPatches_Logic.stroke
    if stroke is None: return face_is_placeable_now(bm, verts)
    key = tuple((v.index if isinstance(v, BMVert) else tuple(round(c, 6) for c in v)) for v in verts)
    hit = stroke.placeable.get(key)
    if hit is None: hit = stroke.placeable[key] = face_is_placeable_now(bm, verts)
    return hit

def face_is_placeable_now(bm, verts):
    ''' Whether a triangle or quad on these corners, in this order, leaves the mesh making sense: no
    third face on an edge, no face already there, none laid over existing geometry, no diagonal that
    is an edge of the mesh. A corner may be a Vector for a vert the fill creates, which only the tests
    about existing corners skip. '''
    SIDE_OVER_VERT_ANGLE = 120.0    # a new side whose ends share a neighbour this straight runs over that neighbour

    n = len(verts)
    if len({ id(v) for v in verts }) != n: return False
    is_existing = [ isinstance(v, BMVert) for v in verts ]
    if all(is_existing) and bm.faces.get(verts): return False

    cos = [ co_of(v) for v in verts ]
    centre = sum(cos, Vector()) / n
    for i in range(n):
        j = (i + 1) % n
        if not (is_existing[i] and is_existing[j]): continue
        va, vb = verts[i], verts[j]
        bme = bmvs_shared_bme(va, vb)
        if bme is not None:
            if len(bme.link_faces) >= 2: return False
            if bme.link_faces and on_faced_side(bme, centre): return False
            continue
        # this side would be created: refuse it when it runs straight over a shared neighbour, which
        # means the face skipped a row of the mesh
        for w in { e.other_vert(va) for e in va.link_edges } & { e.other_vert(vb) for e in vb.link_edges }:
            if w in verts: continue
            d0, d1 = va.co - w.co, vb.co - w.co
            if d0.length_squared < 1e-14 or d1.length_squared < 1e-14: continue
            if angle_deg(d0.normalized(), d1.normalized()) >= SIDE_OVER_VERT_ANGLE: return False

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
        if is_existing[i] and corner_overlaps_faces(verts[i], cos[i - 1], cos[(i + 1) % n]): return False

    return not mesh_juts_into_face(verts, cos, is_existing)

def complete_quad(bm, known, slots, *, min_squareness):
    ''' (verts, cost) of the best quad finishing the `known` corners (in ring order) with a candidate
    vert from each of `slots` (in ring order after them), judged as the cursor pick judges quads, or
    None. '''
    n_open = len(slots)
    if n_open not in (1, 2) or len(known) + n_open != 4: return None
    best = None

    def consider(verts):
        nonlocal best
        cos = [ co_of(v) for v in verts ]
        squareness = quad_squareness(cos)
        if squareness is None or squareness < min_squareness: return
        if not face_is_placeable(bm, verts): return
        cost = quad_area3d(cos) / squareness
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

def grid_topology(verts, l0, l1, *, cyclic_i=False):
    ''' (edges not already in the mesh, faces) of an l0 x l1 grid of verts, row-major, k = i * l1 + j. '''
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

def smooth_path(pts, passes=2):
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

def fit_sphere_centre(p_a, n_a, p_b, n_b):
    ''' Centre of the sphere through two points with the given normals (Relax's Interpolate Loops
    fit, radius signed), or None when the surface between them is flat. '''
    d = n_b - n_a
    dd = d.dot(d)
    if dd < 1e-10: return None
    r = (p_b - p_a).dot(d) / dd
    if abs(r) < 1e-10: return None
    return p_a - n_a * r

def arc_rotation(centre, p_a, p_b, t=1.0):
    ''' Rotation about centre carrying p_a a fraction t of the way to p_b, or None when collinear. '''
    va, vb = p_a - centre, p_b - centre
    axis = va.cross(vb)
    if axis.length_squared < 1e-14 or va.length_squared < 1e-14 or vb.length_squared < 1e-14: return None
    return Matrix.Rotation(va.angle(vb) * t, 3, axis.normalized())

def bend_along(p_a, n_a, p_b, n_b, x):
    ''' x moved the way the surface carries p_a to p_b: rotated about the fitted sphere, or
    translated when flat. '''
    centre = fit_sphere_centre(p_a, n_a, p_b, n_b) if (n_a is not None and n_b is not None) else None
    rot = arc_rotation(centre, p_a, p_b) if centre is not None else None
    if rot is None: return x + (p_b - p_a)
    return centre + rot @ (x - centre)

def arc_between(p_a, n_a, p_b, n_b, fracs):
    ''' (point, normal) at each fraction along the arc from p_a to p_b on the fitted sphere, or
    along the straight line with lerped normals when flat. '''
    centre = fit_sphere_centre(p_a, n_a, p_b, n_b) if (n_a is not None and n_b is not None) else None
    out = []
    for t in fracs:
        rot = arc_rotation(centre, p_a, p_b, t) if centre is not None else None
        if rot is None:
            n = None
            if n_a is not None and n_b is not None:
                n = n_a.lerp(n_b, t)
                n = n.normalized() if n.length_squared > 1e-12 else None
            out.append((p_a.lerp(p_b, t), n))
        else:
            out.append((centre + rot @ (p_a - centre), (rot @ n_a).normalized()))
    return out

def bezier(p0, p1, p2, p3, t):
    u = 1.0 - t
    return p0 * (u*u*u) + p1 * (3*u*u*t) + p2 * (3*u*t*t) + p3 * (t*t*t)

def mirror_curve(p0, t0, p3):
    ''' (p1, p2, arrival direction) of a cubic leaving p0 along t0 and arriving at p3 along t0
    mirrored across the chord, which bows evenly and never curls. '''
    HANDLE_AT_START, HANDLE_AT_END = 0.25, 0.15     # fractions of the chord; shorter at the end so two sides meeting there do not pinch
    chord = p3 - p0
    length = chord.length
    if length < 1e-9: return p0, p3, t0
    c = chord / length
    t3 = c * (2.0 * t0.dot(c)) - t0
    t3 = t3.normalized() if t3.length_squared > 1e-12 else c
    return p0 + t0 * (HANDLE_AT_START * length), p3 - t3 * (HANDLE_AT_END * length), t3

def cumulative_fracs(cos):
    ''' Fraction of the polyline length reached at each point, 0 at the first and 1 at the last. '''
    seg = [ (cos[k + 1] - cos[k]).length for k in range(len(cos) - 1) ]
    total = sum(seg) or 1.0
    out, acc = [0.0], 0.0
    for l in seg:
        acc += l
        out.append(acc / total)
    out[-1] = 1.0
    return out

def turn_sharpness(cos):
    ''' How sharply a closed loop turns at each vert: 0 straight, 2 doubled back. '''
    n = len(cos)
    out = []
    for i in range(n):
        d0 = (cos[i] - cos[(i - 1) % n]).normalized()
        d1 = (cos[(i + 1) % n] - cos[i]).normalized()
        out.append(1.0 - max(-1.0, min(1.0, d0.dot(d1))))
    return out

def grid_snap_noise(cos, raws, l0, l1, *, cyclic_i=False):
    ''' Mean disagreement between neighbouring verts' snap displacements, in quad widths: a patch
    draped over a curve moves together (a steep dome reads ~0.25), one whose verts each find their
    own piece of the source reads 1.0 or more. '''
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


def layout_topology(verts, edges):
    ''' The edges of an n-sided layout the preview draws: every one not already in the mesh. '''
    def is_new(a, b):
        va, vb = verts[a], verts[b]
        if not (isinstance(va, BMVert) and isinstance(vb, BMVert)): return True
        return bmvs_shared_bme(va, vb) is None
    return [ (a, b) for a, b in edges if is_new(a, b) ]


def layout_snap_noise(cos, raws, edges):
    ''' grid_snap_noise for an n-sided layout, whose neighbourhood is its edge list. '''
    disp = { k: cos[k] - raws[k] for k in range(len(cos)) if raws[k] is not None }
    if len(disp) < 2: return 0.0
    steps = [ (cos[a] - cos[b]).length for a, b in edges ]
    spacing = (sum(steps) / len(steps)) if steps else 0.0
    if spacing <= 1e-9: return 0.0
    diffs = [ (disp[a] - disp[b]).length for a, b in edges if a in disp and b in disp ]
    if not diffs: return 0.0
    return (sum(diffs) / len(diffs)) / spacing


def snap_drift(cos, raws, plane_n, steps):
    ''' How far the worst new vert had to slide across the patch to find the source, in quad widths. '''
    if plane_n is None or plane_n.length_squared < 1e-12: return 0.0
    spacing = (sum(steps) / len(steps)) if steps else 0.0
    if spacing <= 1e-9: return 0.0
    worst = 0.0
    for k, raw in enumerate(raws):
        if raw is None: continue
        d = cos[k] - raw
        worst = max(worst, (d - plane_n * d.dot(plane_n)).length)
    return worst / spacing


def shared_side_fold(idx_a, cos_a, idx_b, cos_b):
    ''' Whether two faces sharing a side lie on the same side of it, a fold; None when they share no
    side. Faces are vert indices (None for a vert not yet made) and positions. '''
    shared = { i for i in idx_a if i is not None } & { i for i in idx_b if i is not None }
    if len(shared) != 2: return None
    ia, ib = tuple(shared)
    def is_side(idx):
        return (idx.index(ia) - idx.index(ib)) % len(idx) in (1, len(idx) - 1)
    if not (is_side(idx_a) and is_side(idx_b)): return None
    ca, cb = sum(cos_a, Vector()) / len(cos_a), sum(cos_b, Vector()) / len(cos_b)
    return same_side_of_edge(cos_a[idx_a.index(ia)], cos_a[idx_a.index(ib)], [ca], [cb])


def faces_overlap(idx_a, cos_a, idx_b, cos_b) -> bool:
    ''' Whether two faces, each as vert indices (None for a vert not yet made) and positions, would
    lie over each other. Needs no view. '''
    na, nb = len(cos_a), len(cos_b)
    ca, cb = sum(cos_a, Vector()) / na, sum(cos_b, Vector()) / nb
    ra = max((c - ca).length for c in cos_a)
    rb = max((c - cb).length for c in cos_b)
    if (cb - ca).length > ra + rb: return False    # nowhere near each other
    shared = { i for i in idx_a if i is not None } & { i for i in idx_b if i is not None }
    if len(shared) >= 3: return True     # one quad laid across the other's diagonal
    if len(shared) == 2:
        fold = shared_side_fold(idx_a, cos_a, idx_b, cos_b)
        if fold is not None: return fold
    # anything else is laid flat in the first face's plane and the outlines compared, which catches one cutting
    # across the other whatever corners they share
    n = (cos_a[2] - cos_a[0]).cross(cos_a[3] - cos_a[1]) if na == 4 else (cos_a[1] - cos_a[0]).cross(cos_a[2] - cos_a[0])
    if n.length_squared < 1e-18: return False
    n.normalize()
    frame = plane_frame(n, cos_a[1] - cos_a[0])
    if frame is None: return False
    u, w = frame
    mean_side = sum((cos_a[(i + 1) % na] - cos_a[i]).length for i in range(na)) / na
    if all(abs((c - ca).dot(n)) > 0.5 * mean_side for c in cos_b): return False    # another layer of the surface
    to2d = lambda c: Vector(((c - ca).dot(u), (c - ca).dot(w)))
    return polys_overlap2d([ to2d(c) for c in cos_a ], [ to2d(c) for c in cos_b ], eps=1e-3 * mean_side)


def corner_pairing(bmv, mouse, rgn, r3d, M):
    ''' The far verts (va, vb) of the two open edges at a corner vert that F2's quad would close: the
    pair whose parallelogram completion the cursor is nearest, or the squarest pair without a cursor.
    None when the vert is no corner. '''
    opens = [ bme for bme in bmv.link_edges if len(bme.link_faces) < 2 and not bme.hide ]
    if len(opens) < 2: return None
    best = None
    for bme_a, bme_b in combinations(opens, 2):
        if set(bme_a.link_faces) & set(bme_b.link_faces): continue   # already share a face: no gap between them
        va, vb = bme_a.other_vert(bmv), bme_b.other_vert(bmv)
        if va is vb: continue
        da, db = va.co - bmv.co, vb.co - bmv.co
        if da.length_squared < 1e-14 or db.length_squared < 1e-14: continue
        if mouse is not None and rgn and r3d:
            pt = location_3d_to_region_2d(rgn, r3d, M @ (va.co + vb.co - bmv.co))
            if not pt: continue
            score = (pt - mouse).length
        else:
            score = abs(da.normalized().dot(db.normalized()))
        if best is None or score < best[0]: best = (score, va, vb)
    return (best[1], best[2]) if best else None


def edge_chains(bmes) -> list:
    ''' The edges as connected runs, (verts in order, edges in order, cyclic); a vert with three or
    more of the edges ends every run reaching it. '''
    at = {}
    for bme in bmes:
        for v in bme.verts: at.setdefault(v, []).append(bme)
    left, out = set(bmes), []

    def walk(v, bme):
        sv, run = [v], []
        while bme is not None:
            left.discard(bme)
            run.append(bme)
            v = bme.other_vert(v)
            sv.append(v)
            more = [ e for e in at[v] if e in left ]
            bme = more[0] if len(at[v]) == 2 and len(more) == 1 else None
        return sv, run

    for v, es in at.items():            # open runs, from their ends and forks
        if len(es) == 2: continue
        for bme in es:
            if bme in left: out.append(walk(v, bme) + (False,))
    while left:                         # whatever is left closes on itself
        bme = next(iter(left))
        sv, run = walk(bme.verts[0], bme)
        out.append((sv[:-1], run, True) if sv[0] is sv[-1] and len(run) >= 3 else (sv, run, False))
    return out


def offer_key(offer):
    ''' Order-free identity of an offer; what Previz.face_src carries. '''
    if offer is None: return None
    if offer[0] == 'e': return ('e', frozenset(offer[1:3]))
    if offer[0] == 'q': return ('q', frozenset(offer[1]))
    return ('c', offer[1])


class Stroke:
    ''' What a Ctrl+LMB stroke has collected, as the boundary elements its faces are made from: open
    edges to step, quads picked over existing verts, notch corners to close. Indices only, resolved
    on every rebuild; the mesh cannot change while a stroke is down, so what is worked out from it is
    kept for the stroke's lifetime. '''
    # the preview and the commit are one rebuild over the whole set, so a run of stepped edges is offset as one run,
    # its rungs blended where edges meet as a selected run's are, and every picked quad hands its verts to the runs
    # ending beside it. Realising each face as it was taken lost that blending; holding the faces as separate
    # previews to merge later left the pick blind to what the stroke had decided

    def __init__(self):
        self.edges   = set()    # frozenset({ia, ib}): open boundary edges to step
        self.quads   = {}       # frozenset(indices) -> (indices in ring order, the pick's cost)
        self.quad_geo = {}      # frozenset(indices) -> (positions, centre, radius) of that quad
        self.corners = {}       # corner vert index -> (va, vb) indices, the pairing the pick chose
        self.corner_faces = {}  # corner vert index -> (indices, positions) of its quad from the last rebuild
        self.step_faces = []    # (edge key, indices, positions) of every face the stepped edges made in the last rebuild
        self.covered = set()    # frozenset pairs: existing edges a stepped row lies along (a weld, a closed far side), filled by that step
        self.face_sides = set() # frozenset pairs: every side of every quad and notch quad taken
        self.runs    = {}       # offer key -> px of the stroke that has run inside that offer's faces
        self.prev    = None     # the stroke's previous sample point, window px
        self.chains  = {}       # run key -> the previews emit_offset made for it, reused while the run is unchanged
        self.normals = {}       # source-normal cache shared by every rebuild of the stroke
        self.placeable = {}     # face_is_placeable results, likewise

    def is_empty(self) -> bool:
        return not (self.edges or self.quads or self.corners)

    def has(self, key) -> bool:
        kind, ident = key
        if kind == 'e': return ident in self.edges
        if kind == 'q': return ident in self.quads
        return ident in self.corners

    def spoken_for(self, ia : int, ib : int, *, by_faces_only : bool = False) -> bool:
        ''' Whether the edge between two verts is already in the stroke: as a side of a quad or notch
        quad it has taken, as an existing edge one of its stepped rows lies along, or (unless
        by_faces_only) as an edge it is stepping. '''
        e = frozenset((ia, ib))
        return e in self.face_sides or e in self.covered or (not by_faces_only and e in self.edges)

    def _rebuild_sides(self):
        sides = set()
        for ring, _cost in self.quads.values():
            n = len(ring)
            sides.update(frozenset((ring[k], ring[(k + 1) % n])) for k in range(n))
        for c, (va, vb) in self.corners.items():
            sides.add(frozenset((c, va)))
            sides.add(frozenset((c, vb)))
        self.face_sides = sides

    def clashes(self, idx, cos) -> tuple:
        ''' (keys of the taken quads a face over these verts cannot sit beside, whether it clashes with
        something it cannot replace), in exact geometry: every vert involved is in the mesh or the preview. '''
        centre = sum(cos, Vector()) / len(cos)
        radius = max((c - centre).length for c in cos)
        quads = []
        for key, (ring, _cost) in self.quads.items():
            qcos, qc, qr = self.quad_geo[key]
            if (qc - centre).length > qr + radius: continue
            if faces_overlap(idx, cos, ring, qcos): quads.append(key)
        # a notch quad is a clash on any overlap. A stepped edge's face only when the two share a side and lie on the
        # same side of it: a picked quad beside a run moves the run's rung onto its own vert, so a slight overlap with
        # the rung as it stands is no objection. A quad over a stepped edge takes the edge over and its face goes
        blocked = any(faces_overlap(idx, cos, cidx, ccos) for cidx, ccos in self.corner_faces.values())
        if not blocked:
            n = len(idx)
            sides = { frozenset((idx[k], idx[(k + 1) % n])) for k in range(n) if idx[k] is not None and idx[(k + 1) % n] is not None }
            blocked = any(shared_side_fold(idx, cos, sidx, scos)
                          for ekey, sidx, scos in self.step_faces if ekey not in sides)
        return quads, blocked

    def allows_quad(self, bm, ring, cost : float) -> bool:
        ''' Whether a quad over these verts may be offered: not taken already, and if it lies over a
        taken quad, the better fit of the two, since taking it would replace what it lies over. '''
        if frozenset(ring) in self.quads: return False
        nverts = len(bm.verts)
        if any(i >= nverts for i in ring): return False
        quads, blocked = self.clashes(ring, [ bm.verts[i].co for i in ring ])
        return not blocked and all(cost < self.quads[k][1] for k in quads)

    def take(self, bm, offer, faces=()) -> bool:
        ''' Collect an offer; True when the stroke changed. A quad laid over a worse quad already
        taken replaces it, over a better one or a notch quad it is refused. `faces` are the offer's
        previewed faces as (indices, positions), which is how a notch quad is judged. '''
        kind = offer[0]
        if kind == 'e':
            key = frozenset(offer[1:3])
            if key in self.edges or key in self.covered: return False
            self.edges.add(key)
            return True
        if kind == 'c':
            if offer[1] in self.corners: return False
            for idx, cos in faces:
                quads, blocked = self.clashes(idx, cos)
                if quads or blocked: return False
            self.corners[offer[1]] = (offer[2], offer[3])
            self._rebuild_sides()
            return True
        ring, cost = tuple(offer[1]), offer[2]
        if not self.allows_quad(bm, ring, cost): return False
        cos = [ bm.verts[i].co.copy() for i in ring ]
        quads, _blocked = self.clashes(ring, cos)
        for k in quads:
            del self.quads[k]
            del self.quad_geo[k]
        centre = sum(cos, Vector()) / len(cos)
        self.quads[frozenset(ring)] = (ring, cost)
        self.quad_geo[frozenset(ring)] = (cos, centre, max((c - centre).length for c in cos))
        self._rebuild_sides()
        return True


@dataclass
class FillSolution:
    ''' One way to fill a closed loop, as the Solution property offers them. '''
    tag        : object                 # what grid_last records: a grid span, a plan kind, or a junction's name
    degenerate : bool = False           # makes a quad that reads as a triangle, or is concave, at the boundary: ranks last
    odd        : bool = False           # closes an odd loop with one triangle or n-gon: ranks behind the quad fills
    hint       : str | None = None      # shown while this fill is the one built
    build      : object = None          # () -> True built, False refused by its checks, None when the vert budget is spent
    plans      : tuple = ()             # a pole fill: the ngon_layout.Plans Offset steps through, or the dragged pole picks from
    split      : tuple | None = None    # a grid fill: its (span, offset into the loop) at Offset 0
    offsets    : int = 1                # distinct values Offset can take here; a junction counts its own once built


@dataclass
class Previz:
    kind     : str          # 'rect' | 'L' | 'C' | 'I' | 'loft' | 'grid' | 'ngon' | 'bridge' | 'offset' | 'corner' | 'nearest' | 'quad' | 'triangle'
    vert_idx : list         # bm vert index for existing verts, None for verts Fill will create
    vert_co  : list         # local-space coords (copies for existing verts)
    edges    : list         # index pairs into vert_co, new edges only (the dashed preview)
    faces    : list         # index tuples into vert_co
    open_idx : tuple = ()   # new verts on the patch boundary, i.e. on a side being created
    row_idx  : tuple = ()   # offset step: the row to leave selected after Fill, so the next step is offered at once
    hover    : bool = False # built from the cursor with nothing selected; Fill then leaves nothing selected
    face_src : tuple = ()   # per face, the offer key it came from (a stroke needs to know which faces are which)
    cost     : float = 0.0  # the cursor pick's score for a quad over existing verts, lower better
    mark     : tuple = ()   # faces drawn in a warning colour: the one non-quad an odd loop is closed with


def fuse_previz(previz : list, *, kind : str = 'stroke', hover : bool = True) -> Previz:
    ''' One preview out of several sharing verts, existing ones by index and new ones by position, so
    a run's rung and the notch quad it was pinned to are one vert, drawn once and built once. Fill
    creates a vert per preview that names one, so anything whose pieces share a vert has to come
    through here or it is built twice, once for each side of the seam. '''
    slots, idx, cos, edges, seen, faces, srcs, open_idx, marks = {}, [], [], [], set(), [], [], [], []
    for pv in previz:
        remap = []
        n_faces = len(faces)
        for i, co in zip(pv.vert_idx, pv.vert_co):
            key = ('i', i) if i is not None else ('c', tuple(round(c, 6) for c in co))
            k = slots.get(key)
            if k is None:
                k = slots[key] = len(idx)
                idx.append(i)
                cos.append(co)
            remap.append(k)
        for a, b in pv.edges:
            e = frozenset((remap[a], remap[b]))
            if len(e) == 2 and e not in seen:
                seen.add(e)
                edges.append((remap[a], remap[b]))
        for f, src in zip(pv.faces, pv.face_src or (None,) * len(pv.faces)):
            faces.append(tuple(remap[i] for i in f))
            srcs.append(src)
        for k in pv.open_idx:
            if remap[k] not in open_idx: open_idx.append(remap[k])
        marks.extend(n_faces + k for k in pv.mark)
    # a vert two of the pieces shared is inside the one they fuse into, whatever it was to either
    counts = {}
    for f in faces:
        for e in zip(f, f[1:] + f[:1]): counts[frozenset(e)] = counts.get(frozenset(e), 0) + 1
    rim = { k for e, c in counts.items() if c == 1 for k in e }
    open_idx = [ k for k in open_idx if k in rim ]
    return Previz(kind, idx, cos, edges, faces, tuple(open_idx), (), hover=hover, face_src=tuple(srcs), mark=tuple(marks))


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
    corner_chains  : ClassVar[list] = []                       # (vert indices in order, corner positions, cyclic) per loop and string: the curve the corners control
    labels         : ClassVar[list[tuple[str, list[Vector]]]] = []
    previz         : ClassVar[list[Previz]] = []
    has_bridge     : ClassVar[bool] = False
    has_loft       : ClassVar[bool] = False
    has_grid       : ClassVar[bool] = False
    has_offset     : ClassVar[bool] = False
    has_free_step  : ClassVar[bool] = False                # an offset row extruded rather than welding, so its distance is the artist's to set
    has_smoothing  : ClassVar[bool] = False                # a patch with a vert the grid smoother can actually move
    has_quad       : ClassVar[bool] = False                # a single quad: cursor, four verts, or a corner
    has_manual_corners : ClassVar[bool] = False            # any corner override on the selected boundary
    wire_runs      : ClassVar[list] = []                   # (chord co0, chord co1, mouse side) per wire offset, watched by track_mouse
    grid_last      : ClassVar[tuple | None] = None             # (tag of the fill built, Offset); for an O loop the tag is its grid span
    offsets        : ClassVar[int] = 1                         # 2 when a second placement of the fill built is known to build, else 1: the Offset knob is offered only then
    solution_notes : ClassVar[dict] = {}                       # loop key -> Solution key -> {'valid', 'invalid': placements tried, 'count'}: kept for the selection, so each placement is built at most once to learn its fate
    solution_shown : ClassVar[dict] = {}                       # loop key -> Solution key on screen: a setting change that revives a dropped Solution must not displace it
    solution_built : ClassVar[tuple | None] = None             # (loop key, Solution key, placement) emit_ranked last built, for a pass to strike when the fill will not hold
    grid_ranked    : ClassVar[list] = []                       # the loop's FillSolutions, ranked; an O loop's ('grid', span, offset) splits
    grid_sig       : ClassVar[tuple | None] = None             # selection the solutions were ranked for
    ngon_cuts      : ClassVar[dict] = {}                       # (loop nodes, corners) -> cut plans, the one search too slow to redo every rebuild
    pole_pos       : ClassVar[dict] = {}                       # loop key -> (Solution and Offset it was made under, local co): where a drag put the pole; it stays there, excluded from smoothing
    pole_drag      : ClassVar[tuple | None] = None             # (loop key, local co) while LMB drags a pole handle
    pole_drag_prev : ClassVar[tuple | None] = None             # the position before the drag, put back on cancel
    loops_last     : ClassVar[int | None] = None               # loops the last bridge or loft used
    error          : ClassVar[str | None] = None
    pole_handles   : ClassVar[list] = []                       # (local co, loop key) per n-sided fill whose pole has somewhere else to go: the handle LMB drags
    hint           : ClassVar[str | None] = None            # why a loop got a lesser fill than its corners asked for; does not block anything

    # Property writes that have not landed yet. The rebuild runs in a draw callback, which cannot
    # write properties, so writes go through a timer and these stand in for the value until then.
    solution_pending : ClassVar[int | None] = None
    solution_stale   : ClassVar[int | None] = None             # what the property held when the write was scheduled
    solution_seen    : ClassVar[int | None] = None             # the Solution last built, so a change of it can put Offset back to 0
    offset_seen      : ClassVar[int] = 0                       # the Offset last built at, so a refused one can be skipped the way the knob was turned
    prop_pending     : ClassVar[dict] = {}                     # tool property -> (value written but not landed yet, what it held when the write was scheduled)

    # Selection bookkeeping
    sel_sig        : ClassVar[tuple | None] = None             # selection the last live rebuild ran on
    filled_sig     : ClassVar[tuple | None] = None             # selection left behind by the last fill; not offered again
    ngon_verts     : ClassVar[tuple | None] = None             # vert indices of a lone selected n-gon the preview replaces
    replaced_band  : ClassVar[tuple] = ((), ())                # (faces, inner edges) by vert index of the solved loft the preview replaces
    filled_flags   : ClassVar[tuple] = (False, False, False, False, False)   # (bridge, grid, loft, offset, quad) of the last fill, for its redo panel
    filled_loops   : ClassVar[int] = 0
    filled_solutions : ClassVar[int] = 1
    filled_free_step : ClassVar[bool] = False                  # has_free_step of the last fill, for its redo panel
    filled_smoothing : ClassVar[bool] = False                  # has_smoothing of the last fill, likewise
    filled_offsets : ClassVar[int] = 1                         # offsets of the last fill, likewise
    solved_as      : ClassVar[str] = ''                        # the kind the last rebuild actually built
    solve_ranked   : ClassVar[list] = []                       # kinds of fill this selection could take, best first
    solve_sig      : ClassVar[tuple | None] = None             # selection that ranking was made for
    filled_solve_ranked : ClassVar[list] = []                  # solve_ranked of the last fill, for its redo panel

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
    offer          : ClassVar[tuple | None] = None       # what the cursor asks for: ('q', ring, cost), ('e', ia, ib) or ('c', C, va, vb)
    drag_path      : ClassVar[list] = []                 # window-space points of the Ctrl+LMB drag being drawn
    stroke         : ClassVar[object | None] = None      # Stroke while a Ctrl+LMB drag is down: what it has collected so far

    @staticmethod
    def reset_session():
        L = LegacyPatches_Logic
        L.depsgraph_version = -1
        L.last_settings = None
        L.sel_sig = None
        L.prop_pending = {}
        L.filled_sig = None
        L.filled_flags = (False, False, False, False, False)
        L.filled_loops, L.filled_solutions = 0, 1
        L.filled_free_step = L.filled_smoothing = False
        L.filled_offsets = 1
        L.solve_ranked = L.filled_solve_ranked = []
        L.solve_sig = None
        L.solved_as = ''
        L.grid_sig = None
        L.ngon_cuts = {}
        L.pole_pos = {}
        L.pole_drag = L.pole_drag_prev = None
        L.solution_pending = L.solution_stale = L.solution_seen = None
        L.offset_seen = 0
        L.solution_notes = {}
        L.solution_shown = {}
        L.mouse = L.mouse_locked = None
        L.cand_key = None
        L.cand_idx = []
        L.cand_cos = L.cand_edges = L.cand_open = None
        L.proj_key = L.proj_px = None
        L.vis_cache = {}
        L.vis_key = None
        L.nearest_active = False
        L.offer = None
        L.drag_path = []
        L.stroke = None
        L.ctrl = False
        L.ctrl_locked = None
        L.dirty = True
        L._clear_products()

    @staticmethod
    def _clear_products():
        L = LegacyPatches_Logic
        L.boundary_verts = {}
        L.corner_indices = set()
        L.corner_chains = []
        L.labels = []
        L.previz = []
        L.has_bridge = L.has_loft = L.has_grid = L.has_offset = L.has_quad = False
        L.has_free_step = False
        L.has_smoothing = False
        L.has_manual_corners = False
        L.grid_last = None
        L.grid_ranked = []
        L.offsets = 1
        L.solution_built = None
        L.solve_ranked = []
        L.loops_last = None
        L.wire_runs = []
        L.offer = None
        L.error = None
        L.hint = None
        L.pole_handles = []
        L.ngon_verts = None
        L.replaced_band = ((), ())

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
            values = { name: getattr(props, name) for name in PATCH_SETTING_NAMES if name != 'solve' }
            values['steps'] = max(1, L.settled('steps', int(values['steps'])))
            values['step_scale'] = L.settled('step_scale', float(values['step_scale']))
            values['offset'] = int(L.settled('offset', int(values['offset'])))
            # Solve is a dynamic enum, which keeps its index when the items change under it, so a read
            # can fail outright. The best fill stands in until _recompute puts the index back.
            try: values['solve'] = L.settled('solve', props.solve)
            except Exception: values['solve'] = ''
            return PatchSettings(**values)
        except Exception:
            return PatchSettings()

    @staticmethod
    def settled(name : str, value):
        ''' What a property will read once a write of ours has landed: until then it still holds the
        old value, and a rebuild in between would work from that. '''
        L = LegacyPatches_Logic
        pending = L.prop_pending.get(name)
        if pending is None: return value
        want, stale = pending
        landed = L._prop_same(value, want) or (stale is not None and not L._prop_same(value, stale))
        if not landed: return want
        del L.prop_pending[name]
        return value

    @staticmethod
    def _prop_same(a, b) -> bool:
        # a FloatProperty is single precision, so 1.1 written comes back a hair off; an exact test would pin a pending value for good
        if a is None or b is None: return False
        return abs(a - b) <= 1e-5 * max(1.0, abs(b)) if isinstance(b, float) else a == b

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
    def push_prop(name : str, value, stale=None):
        ''' Write a tool property from a rebuild, `stale` being what it holds now: the write is dropped
        if the artist moves the property first. '''
        L = LegacyPatches_Logic
        L.prop_pending[name] = (value, stale)
        def value_of():
            pending = L.prop_pending.get(name)
            if pending is None: return None
            want, was = pending
            props = L.tool_props(bpy.context)
            if was is not None and props is not None and not L._prop_same(getattr(props, name), was):
                del L.prop_pending[name]
                return None
            return want
        L._write_tool_prop_later(name, value_of)

    @staticmethod
    def solve_items(*, redo : bool = False):
        ''' Items for the Solve enum: the live ranking on the tool, the last fill's on its redo panel.
        Numbered by position, so index 0 is always the best fill on offer and a fresh selection lands
        there. '''
        L = LegacyPatches_Logic
        ranked = L.filled_solve_ranked if redo else L.solve_ranked
        # a name it does not know would raise inside a draw callback, so unknown kinds drop out
        return [ (kind, *SOLVE_LABELS[kind], i)
                 for i, kind in enumerate(k for k in ranked if k in SOLVE_LABELS) ]

    @staticmethod
    def push_solution(value : int, stale : int):
        L = LegacyPatches_Logic
        L.solution_pending, L.solution_stale = value, stale
        L._write_tool_prop_later('solution', lambda: L.solution_pending)

    # Ctrl+Scroll drives the count knob and Shift+Scroll the offset knob, as in Contours. Which knob
    # is live depends on what the selection produced; a loft and a grid fill never coexist.

    STEP_SCALE_TICK : ClassVar[float] = 0.1     # a scroll tick is a tenth of the run's own spacing
    STEP_SCALE_MAX  : ClassVar[float] = 16.0    # the property's own ceiling

    @staticmethod
    def scaled_step(value : float, delta : int) -> float:
        ''' The step distance a scroll tick away, snapped to the tick grid so a typed value comes back
        to round numbers. '''
        L = LegacyPatches_Logic
        return max(L.STEP_SCALE_TICK,
                   min(L.STEP_SCALE_MAX, round(value / L.STEP_SCALE_TICK + delta) * L.STEP_SCALE_TICK))

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
        elif L.has_free_step:
            # a row that extrudes has a distance to set and nothing to rotate, so the knob is free.
            # Through the pending table, or a reset scheduled a moment ago lands on top of this.
            L.push_prop('step_scale', L.scaled_step(L.read_settings(context).step_scale, delta))
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
            L.solution_notes = {}      # the mesh, or the selection, changed: what refused may build now
            L.solution_shown = {}
            L.dirty = True

        settings = L.read_settings(context)
        if settings != L.last_settings:
            # Solution and Offset pick among the fills the notes are about; anything else reshapes them
            if L.last_settings is None or replace(settings, solution=0, offset=0) != replace(L.last_settings, solution=0, offset=0):
                L.solution_notes = {}
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
    def _recompute(context : Context, settings : PatchSettings, *, live : bool = False, stroke_offer : str | None = 'pick'):
        L = LegacyPatches_Logic
        MAX_SELECTED_EDGES = 250        # same bail-out as the loop/strip selection overlay
        MAX_LOFT_LOOPS = 12             # loops in one stack of lofts, the only selection of more than two shapes there is
        MAX_NEW_VERTS = 5000            # each new vert costs one closest-point query per source
        SNAP_CAP_EDGES = 2.0            # how far a new vert may be projected, in mean boundary edge lengths, so it cannot land on the far side of a form
        MAX_SNAP_NOISE = 0.7            # grid_snap_noise above this means the fill bears no relation to the source
        MAX_SNAP_DRIFT = 0.75           # snap_drift above this: the fill spans nothing and the loop is better stepped. Source feature snapping drifts a quarter quad at the default proximity; the coarse fills grid_snap_noise still reads as clean drift well past that (an 8-vert belt round a cube reads 0.88, a 3x3 ring round the mouth of a tube 1.02)
        GUIDE_MAX_ALONG = 0.7           # |cos| above which an existing edge runs along the strip and cannot guide a new side
        WELD_FIT_RADIUS = 0.6           # how far from where a new vert would land an existing one may sit, in step lengths
        WELD_FIT_MIN_SQUARENESS = 0.45  # below this a fresh vert makes a better quad than the existing one would
        LOFT_PARALLEL = LOFT_STACKED = 0.5  # two loops loft only when they face the same way and are stacked along their normals
        NGON_LAYOUT_PASSES = 8          # relax passes on an n-sided fill's pole and spokes before Smooth; the interiors are re-blended from them. Three left a bridge's pole short of where it settles
        NGON_MAX_FLIPPED = 0.1          # share of an n-sided fill's quads allowed to face the other way before it is refused as folded
        NORMAL_INSET = 0.25             # how far inside the patch, in mean boundary edges, a boundary point's source normal is checked against
        NORMAL_CREASE = 45.0            # degrees the two may differ before the point is taken to sit on a crease and the inside one used
        NGON_MAX_ALTERNATIVES = 4       # corner-demotion and cut Solutions offered, each, and an odd loop's demoted fills; one Solution is every plan of one shape (ngon_layout.plan_shape, phantom_shape)
        NGON_POLE_MARGIN = 0.75         # a pole stays at least this many mean boundary edges inside the loop, or its ring of quads collapses into slivers
        NGON_POLE_STRAY = 0.5           # share of that margin a pole may relax past the line and be held; one wanting further in is a layout that does not fit, refused
        NOTCH_ANGLE = 30.0              # degrees. A bend turning out of the hole sharper than this makes it a notched one, and a vert a stepped row lands on that bends this much is a corner of what is left
        NOTCH_COVER_SLACK = 0.02        # how far past the hole its own quads may reach, against its area, before the pass is dropped as spilling out of it
        CLEFT_ANGLE = 60.0              # degrees. A boundary vert bending out of the hole this sharply, with no arm to square off, is a cleft the hole is cut at before filling
        CLEFT_AIM = 35.0                # degrees the cut may leave the cleft's bisector by: farther round and it runs along one lobe rather than between them
        MAX_GRID_ASPECT = 3.0           # a grid split whose quads would be longer than this across is a sliver, not a Solution (the best split is always kept)
        NGON_EQUALIZE = 0.5             # how much of each relax step pulls a vert toward equal distance from its face centres, against the plain average of its neighbours
        NGON_MAX_CUT_VERTS = 120        # boundary verts above which the cut search (roughly cubic in them, ~0.7s here) is skipped
        BOW_CORNER_MIN_DEG = 60.0       # a bow hangs off the short side only while both its corners are at least this open; see emit_junction
        SMOOTH_ARC_UNIT = 5             # Smooth at which a blend is exactly the circular arc through its two ends; half the slider, so the default sits a little under it
        SMOOTH_BOW_MAX = 10             # the Smooth slider's own soft max: past it a bow only folds through itself

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

        # A stroke previews what it has collected, not what is selected: always one row deep and uncut,
        # since its faces have to meet the faces beside them
        stroke = L.stroke
        if stroke is not None: settings = replace(settings, steps=1, crosses=0)

        # read-only: this runs from a draw callback, so only toggle_corner() ever creates the layer
        layer = bm.verts.layers.int.get(CORNER_LAYER)
        def override(bmv):
            return bmv[layer] if (layer and isinstance(bmv, BMVert)) else CORNER_AUTO
        def is_corner(bmv1, bmv0, bmv2):
            ''' Whether the boundary turns a corner at bmv1, arriving from bmv0 and leaving for bmv2.
            Toggled to one, or bending past Split Angle and not toggled smooth. Any of the three may be
            a point a fill has yet to create, which has no toggle and is read by its position alone. '''
            mode = override(bmv1)
            if mode == CORNER_FORCED: return True
            if mode == CORNER_SMOOTH: return False
            d10 = (co_of(bmv0) - co_of(bmv1)).normalized()
            d12 = (co_of(bmv2) - co_of(bmv1)).normalized()
            return angle_deg(d10, d12) < min_angle

        ##############################################
        # read the selection

        sel_bmes = [ e for e in bmops.get_all_selected_bmedges(bm) if not e.hide ]
        edges = { e for e in sel_bmes if len(e.link_faces) < 2 }
        # Multiple selected faces should fall through be joined to an n-gon with Blender's fill
        if edges and all(any(f.select for f in e.link_faces) for e in sel_bmes): edges = set()
        # A single n-gon should be replaced with a fill if possible
        sel_bmfs = bmops.get_all_selected_bmfaces(bm)
        if len(sel_bmfs) == 1 and stroke is None:
            ngon = next(iter(sel_bmfs))
            if len(ngon.verts) > 4 and set(sel_bmes) <= set(ngon.edges):
                L.ngon_verts = tuple(v.index for v in ngon.verts)
                bm = bm.copy()
                for seq in (bm.verts, bm.edges, bm.faces): seq.ensure_lookup_table()
                ngon = bm.faces.get([ bm.verts[i] for i in L.ngon_verts ])
                edges = set(ngon.edges)
                bm.faces.remove(ngon)
                layer = bm.verts.layers.int.get(CORNER_LAYER)     # the copy's own
        # Loops with faces between them are a loft that was already solved: drop the band on a copy so
        # the rest of the rebuild reads bare loops and lofts them afresh, and remember it for the fill
        # to delete for real. The copy is what the n-gon path above does, for the same reason.
        if stroke is None and L.ngon_verts is None:
            band = solved_loft_band(bm, sel_bmes)
            if band[0]:
                L.replaced_band = band
                bm = bm.copy()
                for seq in (bm.verts, bm.edges, bm.faces): seq.ensure_lookup_table()
                delete_band(bm, band, faces_only=True)
                for seq in (bm.verts, bm.edges, bm.faces): seq.ensure_lookup_table()
                sel_bmes = [ e for e in bmops.get_all_selected_bmedges(bm) if not e.hide ]
                edges = { e for e in sel_bmes if len(e.link_faces) < 2 }
                layer = bm.verts.layers.int.get(CORNER_LAYER)     # the copy's own

        # only as many selected verts as it takes to tell none, one, three, four and more apart
        sel_verts = []
        for bmv in bm.verts:
            if not bmv.select or bmv.hide: continue
            sel_verts.append(bmv)
            if len(sel_verts) > 4: break
        if stroke is not None: edges, sel_verts = set(), []
        lone_bmv = sel_quad = sel_tri = None

        def open_run(bmvs, bmes):
            ''' Whether four verts are one open run of three of the edges. '''
            if len(bmes) != 3: return False
            at = { v: [ e for e in bmes if v in e.verts ] for v in bmvs }
            return sorted(len(es) for es in at.values()) == [1, 1, 2, 2]

        # Four selected verts with at least one on no selected edge are a picked quad. Every vert of
        # an L or C is on a selected edge, and two separate edges are a bridge with its count knob.
        # A run of three edges is a quad too when the four make a good one; when they make a poor
        # one, leaning or thin, the run is filled as the strip it is, and the quad stays on offer as
        # a Type, since four verts can always be closed with one face whatever their angles.
        # Loose corners are always filled with a quad.
        loose_corners = any(not any(e in edges for e in v.link_edges) for v in sel_verts)
        quad_option = None
        if len(sel_verts) == 4 and (loose_corners or open_run(sel_verts, edges)):
            sel_quad = L._selected_quad(bm, sel_verts, context.region, context.region_data, M,
                                        fit=not loose_corners)
            if sel_quad is not None:
                edges = set()   # the quad is the whole fill; a selected edge among the four must not also step
            elif not loose_corners:
                quad_option = L._selected_quad(bm, sel_verts, context.region, context.region_data, M, fit=False)
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
            if DEBUG_FILL: print('[fill] this boundary was the last fill\'s: nothing offered')
            edges = set()   # the patch just built is still selected: do not stack a second one on it
        if live and stroke is None and sig != L.sel_sig:
            # a new selection starts over at one step at the run's own spacing, so a count or a distance
            # scrolled for one run does not carry to the next. Not while a stroke is down: its rebuild
            # empties `edges`, which reads as a new selection every frame.
            L.sel_sig = sig
            if settings.steps != 1:
                L.push_prop('steps', 1)
                settings = replace(settings, steps=1)   # update() holds this same object, so never mutate it
            if settings.step_scale != 1.0:
                L.push_prop('step_scale', 1.0)
                settings = replace(settings, step_scale=1.0)

        # Patches acts on one shape, or on the two that pair into a loft or a bridge. Anything past that
        # should return early so that select all doesn't slow things to a crawl. The one exception is a
        # stack of closed loops, that should count as one loft shape.
        met = {}
        for bme in edges:
            for bmv in bme.verts: met[bmv] = met.get(bmv, 0) + 1
        root = { bmv: bmv for bmv in met }
        def root_of(bmv):
            while root[bmv] is not bmv:
                root[bmv] = root[root[bmv]]     # halving the path as it goes keeps this all but linear
                bmv = root[bmv]
            return bmv
        for bme in edges:
            a, b = root_of(bme.verts[0]), root_of(bme.verts[1])
            if a is not b: root[a] = b
        runs = {}
        for bmv, n in met.items(): runs.setdefault(root_of(bmv), []).append(n)
        # a run closes when every vert on it meets two of the edges
        loft_stack = (2 < len(runs) <= MAX_LOFT_LOOPS
                      and all(all(n == 2 for n in ns) for ns in runs.values()))
        if len(runs) > 2 and not loft_stack: return
        # a loop and a strip do not pair
        if len({ all(n == 2 for n in ns) for ns in runs.values() }) > 1: return

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
                    if is_corner(bmv1, edge.other_vert(bmv1), e.other_vert(bmv1)): continue
                    neighbors[edge].append(e)
                    neighbors[e].append(edge)
                    working.add(e)
            strips.append(strip)

        def order_strip(first, strip_edges):
            # the strip's edges end to end from `first` on; None when it forks (GitHub issue #481)
            strip = list(first)
            remaining = set(strip_edges) - set(strip)
            while remaining:
                next_edges = [edge for edge in neighbors[strip[-1]] if edge in remaining]
                if len(next_edges) != 1: return None
                strip.append(next_edges[0])
                remaining.remove(next_edges[0])
            return strip

        # order each strip end to end; a strip with no ends is an O
        ordered_strips = []
        corners = dict()
        for strip_edges in strips:
            if len(strip_edges) == 1:
                edge = next(iter(strip_edges))
                strip = [edge]
                v0, v1 = edge.verts
                ordered_strips.append(strip)
                corners.setdefault(v0, []).append(strip)
                corners.setdefault(v1, []).append(strip)
                continue
            end_edges = [edge for edge in strip_edges if len(neighbors[edge]) == 1]
            if not end_edges:
                first = next(iter(strip_edges))
                strip = order_strip([first, next(iter(neighbors[first]))], strip_edges)
                if strip is None: continue
                shapes['O'].append(strip)
                cos = [ bmv.co for bme in strip for bmv in bme.verts ]
                L.labels.append((str(len(strip)), [sum(cos, Vector()) / len(cos)]))
                continue
            strip = order_strip([end_edges[0]], strip_edges)
            if strip is None: continue
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
                strip = string_strips[-1]
                c = next((c for c in remaining_corners if strip in corners[c]), None)
                if not c: break
                ignore |= c in ignore_corners
                remaining_corners.remove(c)
                string_corners.add(c)
                if len(corners[c]) != 2: break
                string_strips.append(next(other for other in corners[c] if other != strip))
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
                strip = loop_strips[-1]
                c = next((c for c in remaining_corners if strip in corners[c]), None)
                if not c: break
                ignore |= c in ignore_corners
                remaining_corners.remove(c)
                loop_corners.add(c)
                next_strip = next((other for other in corners[c] if other != strip), None)
                if not next_strip: break
                loop_strips.append(next_strip)
            loop_strips = align_strips(loop_strips)
            if ignore or loop_strips is None: continue
            s0, s1 = loop_strips[0], loop_strips[-1]
            shared_verts = sum(1 for e0 in s0 for e1 in s1 if bmes_shared_bmv(e0, e1))
            if len(loop_strips) == 2 and shared_verts != 2: continue   # not closed
            if len(loop_strips) > 2 and shared_verts != 1: continue
            kind = { 1: 'eye', 2: 'eye', 3: 'tri', 4: 'rect' }.get(len(loop_strips), 'ngon')
            shapes[kind].append(loop_strips)

        L.corner_indices = { c.index for c in (string_corners | loop_corners) }
        if DEBUG_OFFSET: print(f'[offset] {len(edges)} selected edges -> ' + (' '.join(f'{k}:{len(v)}' for k, v in shapes.items() if v) or 'no shape'))

        ##############################################
        # snapping and mirror helpers, set up once per rebuild

        Mi = M.inverted_safe()
        sources = ([ (o, o.matrix_world, o.matrix_world.inverted_safe()) for o in iter_all_valid_sources(context) ]
                   if rf_is_running() else [])
        mirror_axes = active_mirror_axes(context)
        mirror_tol = mirror_threshold(context) or 0.0

        # Source feature snapping
        feature_accel = SourceCache.get(context) if sources else None
        if feature_accel:
            use_fixed, fixed_distance, proximity = source_snap_settings(context)
            edge_lens = [ ((M @ e.verts[0].co) - (M @ e.verts[1].co)).length for e in edges ]
            mean_edge_world = sum(edge_lens) / len(edge_lens) if edge_lens else 0.0

        def feature_snap(co_local, cap=None):
            if not feature_accel: return co_local
            ref = cap / SNAP_CAP_EDGES if cap else mean_edge_world
            radius = source_snap_radius(ref, use_fixed=use_fixed, fixed_distance=fixed_distance, avg_edge_factor=proximity)
            if radius <= 0: return co_local
            co_world = M @ co_local
            corner = feature_accel.find_corner(co_world)
            if corner and corner[2] <= radius: return Mi @ Vector(corner[0])
            closest = feature_accel.closest_point(co_world)
            if closest and (Vector(closest) - co_world).length <= radius: return Mi @ Vector(closest)
            return co_local

        def snap(co_local, normal_world=None, cap=None, *, ray=True, missed=None):
            ''' Onto the source surface, then onto a source feature if one is in reach. A point the
            surface refused is left where it is, so the feature pass cannot rescue a vert that
            should have stopped the fill. '''
            refused = []
            co = surface_snap(co_local, normal_world, cap, ray=ray, missed=refused)
            if refused:
                if missed is not None: missed.append(True)
                return co
            return feature_snap(co, cap)

        def surface_snap(co_local, normal_world=None, cap=None, *, ray=True, missed=None):
            if not sources: return co_local.copy()
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
                votes = [ s for v in pts if (s := sign_threshold(getattr(co_of(v), a), mirror_tol)) != 0 ]
                pos = sum(1 for s in votes if s > 0)
                neg = len(votes) - pos
                side[a] = 1 if not votes else (0 if (pos and neg) else (1 if pos else -1))
            return side

        def shape_cap(pts):
            ''' World-space limit on how far a new vert may be projected: a few mean boundary edge lengths. '''
            cos = [ M @ co_of(v) for v in pts ]
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
        normal_cache = stroke.normals if stroke is not None else {}    # the mesh cannot change while a stroke is down
        def source_normal(pt):
            if not sources: return None
            key = ('v', pt.index) if isinstance(pt, BMVert) else ('c', tuple(round(c, 6) for c in pt))
            if key not in normal_cache:
                r = nearest_point_normal_valid_sources(context, M @ co_of(pt))
                normal_cache[key] = r[1].normalized() if (r and r[1].length_squared > 0) else None
            return normal_cache[key]

        def normal_fn(pts):
            ''' source_normal for the boundary points `pts`, with their mean as the fallback for any other
            point. A boundary vert on a crease of the source has two normals under it and the query answers
            with either: the n-gon on a box top read its walls', and the patch cast sideways onto them.
            Where the normal a little inside the patch disagrees that much, it is the one the quads follow;
            elsewhere the vert's own is exact, which the arcs a corner is placed from rely on. '''
            def key(v):
                return ('v', v.index) if isinstance(v, BMVert) else id(v)
            cos = [ co_of(v) for v in pts ]
            centre = sum(cos, Vector()) / len(cos)
            lens = [ l for a, b in zip(cos, cos[1:]) if (l := (b - a).length) > 1e-9 ]
            inset = NORMAL_INSET * (sum(lens) / len(lens)) if lens else 0.0
            min_agree = math.cos(math.radians(NORMAL_CREASE))
            chosen = {}
            for v, co in zip(pts, cos):
                n = source_normal(v)
                d = centre - co
                # a run's own points all lie on it, so its centre is no way in: those keep their own
                if n is not None and d.length > inset:
                    inner = source_normal(co + d * (inset / d.length))
                    if inner is not None and n.dot(inner) < min_agree: n = inner
                chosen[key(v)] = n
            known = [ n for n in chosen.values() if n is not None ]
            fallback = sum(known, Vector()).normalized() if known else None
            if fallback is not None and fallback.length_squared == 0: fallback = None
            def nrm(pt):
                k = key(pt)
                n = chosen[k] if k in chosen else source_normal(pt)
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
                            acc += co_of(verts[((i - 1) % l0) * l1 + j]) + co_of(verts[((i + 1) % l0) * l1 + j])
                            n += 2
                        elif 0 < i < l0 - 1:
                            acc += co_of(verts[(i - 1) * l1 + j]) + co_of(verts[(i + 1) * l1 + j])
                            n += 2
                        if 0 < j < l1 - 1:
                            acc += co_of(verts[i * l1 + (j - 1)]) + co_of(verts[i * l1 + (j + 1)])
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
                centre = sum((co_of(verts[k]) for k in f), Vector()) / len(f)
                for a, b in zip(f, f[1:] + f[:1]):
                    va, vb = verts[a], verts[b]
                    if not (isinstance(va, BMVert) and isinstance(vb, BMVert)): continue
                    bme = bmvs_shared_bme(va, vb)
                    if bme is None or len(bme.link_faces) != 1: continue
                    faced = on_faced_side(bme, centre)
                    if faced is None: continue
                    if faced: same += 1
                    else: other += 1
            if DEBUG_FILL and same: print(f'[fill] over existing faces? {same} edge(s) say so, {other} say not')
            return same > other

        def add_previz(kind, verts, edges, faces, open_idx=(), row_idx=(), mark=()):
            L.previz.append(Previz(
                kind,
                [ (v.index if isinstance(v, BMVert) else None) for v in verts ],
                [ (v.co.copy() if isinstance(v, BMVert) else v) for v in verts ],
                edges,
                faces,
                tuple(open_idx),
                tuple(row_idx),
                mark=tuple(mark),
            ))

        n_new = 0
        def mark():
            ''' Where the preview stands, for rewind(). '''
            return (len(L.previz), len(L.labels), len(L.pole_handles))

        def rewind(m):
            ''' Take back everything a fill added to the preview since mark() returned m: its patches, its
            labels and its pole handles. A handle left behind by a fill that was dropped draws off the mesh. '''
            del L.previz[m[0]:]
            del L.labels[m[1]:]
            del L.pole_handles[m[2]:]

        def dry_run(fn):
            ''' Whether a fill would build, keeping nothing it makes: the preview, labels, flags and the
            vert budget are put back as they were. '''
            nonlocal n_new
            at = mark()
            saved = (L.has_offset, L.has_free_step, n_new)
            ok = fn()
            built = len(L.previz) > at[0]
            rewind(at)
            L.has_offset, L.has_free_step, n_new = saved
            return ok is not False and built

        def budget(count):
            ''' Cap the total number of new (snapped) verts so a huge selection cannot stall the viewport. '''
            nonlocal n_new
            n_new += count
            if n_new <= MAX_NEW_VERTS: return True
            L.error = 'Patches: selection too large to preview'
            return False

        def build_grid(kind, l0, l1, boundary_at, interior_at, side, cap, *, cyclic_i=False, pin=None, checks=True, hold=(), plane=None, relax=True):
            ''' Fill an l0 x l1 grid and add it to the preview. boundary_at(i, j) returns the existing
            corner there or None; interior_at(i, j) returns (blended co, normal) for the rest. pin, if
            given, adjusts a new interior point after snapping. `hold` names new verts that smoothing
            leaves where the blend put them. `plane` is the normal of the closed boundary, which is what
            snap_drift measures across. Without `relax` the blend is the answer and Smooth means
            something the caller has already applied to it. With checks, a patch that snapped too
            noisily, whose verts slid across the form to reach it, or that would sit over existing
            faces is dropped. '''
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
            if checks and sources:
                cos = [ co_of(v) for v in verts ]
                noise = grid_snap_noise(cos, raws, l0, l1, cyclic_i=cyclic_i)
                spans = [ (cos[i*l1+j] - cos[i*l1+j+1]).length for i in range(l0) for j in range(l1 - 1) ]
                drift = snap_drift(cos, raws, plane, spans)
                if DEBUG_FILL: print(f'[fill] {kind} grid {l0}x{l1}: snap noise {noise:.3f} (max {MAX_SNAP_NOISE}), drift {drift:.3f} (max {MAX_SNAP_DRIFT})')
                if noise > MAX_SNAP_NOISE or drift > MAX_SNAP_DRIFT: return
            held = fixed | set(hold)
            if relax: smooth_grid(verts, normals, l0, l1, side, cap, held, cyclic_i=cyclic_i)
            edges, faces = grid_topology(verts, l0, l1, cyclic_i=cyclic_i)
            if checks and over_existing_faces(verts, faces):
                if DEBUG_FILL: print(f'[fill] {kind} grid {l0}x{l1}: refused, over existing faces')
                return
            # the same test smooth_grid moves a vert on, so Smooth is only offered where it does something
            if relax and any((cyclic_i or 0 < i < l0 - 1) or (0 < j < l1 - 1)
                             for i in range(l0) for j in range(l1) if i * l1 + j not in held):
                L.has_smoothing = True
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
            s_mouse, s_out = side2d(pa, pb, mouse), side2d(pa, pb, po - pm + pa)
            if not s_mouse or not s_out: return 1, 0
            return (1 if s_mouse == s_out else -1), s_mouse

        def chain_sides(shape):
            ''' Verts of each strip of a closed loop, oriented head to tail so sides[k][-1] is
            sides[k+1][0]. None when the strips do not chain. '''
            sides = [ get_verts(strip) for strip in shape ]
            n = len(sides)
            if n < 1:
                return None
            if n == 1:
                return sides if sides[0][0] == sides[0][-1] else None
            if sides[0][-1] not in (sides[1][0], sides[1][-1]): sides[0].reverse()
            for k in range(1, n):
                if sides[k][0] != sides[k - 1][-1]: sides[k].reverse()
                if sides[k][0] != sides[k - 1][-1]: return None
            if sides[-1][-1] != sides[0][0]: return None
            return sides

        def build_layout_previz(kind, layout, bmv_of, boundary, *, checks=True, handle=None, pole_co=None, pole_fixed=False, seed=None, pole_clamp=None, pole_margin=0.0):
            ''' Fill an n-sided layout (ngon_layout.build_layout) whose existing nodes are the loop's own
            verts, and add it to the preview: True when added, False when the checks refused it, None when
            the vert budget is spent. `seed` (node index -> (co, normal)) places nodes before anything else;
            `handle`, a loop key, records the pole as a draggable handle; `pole_co` is where the pole starts,
            else the mean of its split verts, and with `pole_fixed` it stays there through every pass;
            `pole_clamp` holds a pole where it may go, `pole_margin` being how far inside the boundary that is;
            a layout whose pole relaxes more than NGON_POLE_STRAY of that past the line is refused. '''
            nodes = layout.nodes
            N = len(nodes)
            synthetic = [ k for k in range(N) if k not in layout.existing ]
            if not budget(len(synthetic)): return None
            side, cap = shape_side(boundary), shape_cap(boundary)
            nrm = normal_fn(boundary)
            verts, normals, raws = [None] * N, [None] * N, [None] * N
            for k in layout.existing:
                verts[k] = bmv_of[nodes[k]]
                normals[k] = nrm(verts[k])
            fixed = set(layout.existing)
            neighbours = [ [] for _ in range(N) ]
            for a, b in layout.edges:
                neighbours[a].append(b)
                neighbours[b].append(a)

            def place(k, co, n):
                normals[k] = n if n is not None else nrm(co)
                raws[k] = co
                verts[k] = new_point(co, side, normals[k], cap)

            def place_line(line):
                # both ends are placed; the run between follows the surface arc, or the chord when flat
                if len(line) < 3: return
                a, b = line[0], line[-1]
                fracs = [ k / (len(line) - 1) for k in range(len(line)) ]
                pts = arc_between(co_of(verts[a]), normals[a], co_of(verts[b]), normals[b], fracs)
                for k, (co, n) in zip(line[1:-1], pts[1:-1]):
                    if k not in fixed: place(k, co, n)    # a spoke can run along the boundary when the pole sits on it

            # cut runs, poles and spokes are placed first and relaxed on their own, pole included, the region interiors
            # re-blended from them after each pass, so at Smooth 0 the interiors are still pure Coons blends; Smooth then
            # relaxes every new vert. Seeds relax with the spokes: a junction has no pole and spokes to place from
            for k, (co, n) in (seed or {}).items(): place(k, co, n)
            for k, a, b in layout.helpers:
                if verts[k] is None: place(k, (co_of(verts[a]) + co_of(verts[b])) / 2, blend_pair(normals[a], normals[b], 0.5))
            for line in layout.cuts: place_line(line)
            for pole in layout.poles:
                if verts[pole] is not None: continue    # on the boundary or on a cut
                starts = [ line[0] for line in layout.polylines if line[-1] == pole ]
                if not starts or any(verts[k] is None for k in starts): return False
                co = pole_co if pole_co is not None else sum((co_of(verts[k]) for k in starts), Vector()) / len(starts)
                ns = [ normals[k] for k in starts if normals[k] is not None ]
                n = sum(ns, Vector()) if ns else None
                place(pole, co, n.normalized() if (n is not None and n.length_squared > 1e-12) else None)
            for line in layout.polylines: place_line(line)
            seams = [ k for k in synthetic if verts[k] is not None ]

            def place_interiors():
                # each corner region is a Coons blend of its two boundary runs and two spokes, as emit_rect_grid
                for grid in layout.regions:
                    l0, l1 = len(grid), len(grid[0])
                    if l0 < 3 or l1 < 3: continue
                    c00, c10, c01, c11 = grid[0][0], grid[l0 - 1][0], grid[0][l1 - 1], grid[l0 - 1][l1 - 1]
                    for u in range(1, l0 - 1):
                        for v in range(1, l1 - 1):
                            k = grid[u][v]
                            if k in fixed: continue
                            pu, pv = u / (l0 - 1), v / (l1 - 1)
                            ring = (grid[u][0], grid[u][l1 - 1], grid[0][v], grid[l0 - 1][v], c00, c10, c01, c11)
                            n = blend_normal(*(normals[i] for i in ring), pu, pv)
                            co = coons(*(co_of(verts[i]) for i in ring), pu, pv)
                            place(k, co, n)

            faces_of = [ [] for _ in range(N) ]
            for fi, f in enumerate(layout.faces):
                for k in f: faces_of[k].append(fi)

            def relax(which, hold=False):
                # the plain neighbour average, blended with Relax's equalize-faces pull: each vert toward
                # the same distance from its face centres, those distances drawn toward the mean over all
                # faces, which is what keeps the triangle and the n-gon from crushing or ballooning
                placed = [ f for f in layout.faces if all(verts[k] is not None for k in f) ]
                centres = { id(f): sum((co_of(verts[k]) for k in f), Vector()) / len(f) for f in placed }
                radii = { id(f): sum((co_of(verts[k]) - centres[id(f)]).length for k in f) / len(f) for f in placed }
                mean_r = (sum(radii.values()) / len(radii)) if radii else 0.0
                moved = {}
                for k in which:
                    nb = [ co_of(verts[j]) for j in neighbours[k] if verts[j] is not None ]
                    if not nb: continue
                    lap = sum(nb, Vector()) / len(nb)
                    pulls = []
                    for fi in faces_of[k]:
                        f = layout.faces[fi]
                        if id(f) not in centres: continue
                        c = centres[id(f)]
                        rel = co_of(verts[k]) - c
                        if rel.length_squared < 1e-18: continue
                        pulls.append(c + rel.normalized() * (0.5 * radii[id(f)] + 0.5 * mean_r))
                    eq = (sum(pulls, Vector()) / len(pulls)) if pulls else lap
                    moved[k] = lap.lerp(eq, NGON_EQUALIZE)
                for k, co in moved.items():
                    if hold and pole_clamp is not None and k in layout.poles: co = pole_clamp(co)
                    raws[k] = co    # the noise check compares each vert with where the relax put it: relaxing is not noise
                    verts[k] = new_point(co, side, normals[k], cap)

            place_interiors()
            # the pole settles with its spokes: the estimate only starts it, and where it ends up is what
            # smoothing used to have to correct. A pole the artist placed stays where they put it
            settling = [ k for k in seams if not (pole_fixed and k in layout.poles) ]
            for _ in range(NGON_LAYOUT_PASSES):
                relax(settling)
                place_interiors()
            # Where the pole settled says whether the layout fits the loop. One drawn to a side settles on
            # the boundary, its spoke there squashed to slivers and the fan round it folded over the side;
            # holding it at the margin its estimate kept only hides that. A pole a little past the margin
            # is held there; one wanting further in is refused, and the loop takes another Solution
            if pole_clamp is not None and not pole_fixed:
                for pole in layout.poles:
                    if pole in fixed or verts[pole] is None: continue
                    co = co_of(verts[pole])
                    held = pole_clamp(co)
                    stray = (held - co).length
                    if stray > NGON_POLE_STRAY * pole_margin:
                        if DEBUG_FILL: print(f'[fill] {kind} layout: refused, its pole settled {stray / pole_margin:.2f} of the margin past the line')
                        return False
                    if stray > 1e-12:
                        place(pole, held, normals[pole])
                        place_interiors()
            smoothed = [ k for k in synthetic if k not in layout.poles ] if pole_fixed else synthetic
            for _ in range(settings.smooth): relax(smoothed, hold=True)
            if synthetic: L.has_smoothing = True
            if any(v is None for v in verts): return False

            cos = [ co_of(v) for v in verts ]
            if checks and sources:
                noise = layout_snap_noise(cos, raws, layout.edges)
                drift = snap_drift(cos, raws, compute_n([ co_of(v) for v in boundary ]), [ (cos[a] - cos[b]).length for a, b in layout.edges ])
                if DEBUG_FILL: print(f'[fill] {kind} layout of {len(layout.faces)} faces: snap noise {noise:.3f} (max {MAX_SNAP_NOISE}), drift {drift:.3f} (max {MAX_SNAP_DRIFT})')
                if noise > MAX_SNAP_NOISE or drift > MAX_SNAP_DRIFT: return False
            if checks and over_existing_faces(verts, list(layout.faces)):
                if DEBUG_FILL: print(f'[fill] {kind} layout: refused, over existing faces')
                return False
            if checks and all(n is not None for n in normals):
                # a folded fill has quads facing both ways; the loop's own winding is not known, so count the minority
                agree = [ compute_n([ cos[k] for k in f ]).dot(sum((normals[k] for k in f), Vector())) for f in layout.faces ]
                flipped = min(sum(1 for a in agree if a > 0), sum(1 for a in agree if a < 0))
                if flipped > NGON_MAX_FLIPPED * len(layout.faces):
                    if DEBUG_FILL: print(f'[fill] {kind} layout: refused, {flipped} of {len(layout.faces)} faces face the other way')
                    return False
            # a dissolved spoke's nodes only helped place the rest; they are not built
            keep = [ k for k in range(N) if k not in layout.unused ]
            remap = { k: i for i, k in enumerate(keep) }
            faces = [ tuple(remap[k] for k in f) for f in layout.faces ]
            edges = [ (remap[a], remap[b]) for a, b in layout.edges ]
            kept_verts = [ verts[k] for k in keep ]
            marks = [ i for i, f in enumerate(faces) if len(f) != 4 ]
            # a boundary node that is a point rather than a vert is on a side this fill creates, as a bridge's rails are
            open_idx = [ i for i, k in enumerate(keep) if k in fixed and not isinstance(verts[k], BMVert) ]
            add_previz(kind, kept_verts, layout_topology(kept_verts, edges), faces, open_idx, mark=marks)
            if handle is not None and layout.poles[0] not in fixed:
                # the pole, or where it was dissolved into the one n-gon; a pole on a boundary vert is just that
                # vert. So is one with four spokes: corners demoted down to a four-sided loop leave a layout that
                # is a plain grid, and its "pole" an ordinary vert with nothing to drag
                pole = layout.poles[0]
                spokes = sum(1 for a, b in layout.edges if pole in (a, b))
                if pole in remap: at = cos[pole] if spokes != 4 else None
                elif marks: at = sum((cos[keep[k]] for k in faces[marks[0]]), Vector()) / len(faces[marks[0]])
                else: at = None
                if at is not None: L.pole_handles.append((at.copy(), handle))
            return True

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
                co = coons(co_of(l), co_of(r), co_of(b), co_of(t), co_of(c00), co_of(c10), co_of(c01), co_of(c11), pi, pj)
                return co, n

            # the rim walked round, c00 -> c10 -> c11 -> c01, for the plane snap_drift measures across
            rim = [ co_of(v) for v in sv0 + sv1[1:] + sv2[::-1][1:] + sv3[::-1][1:-1] ]
            build_grid(kind, l0, l1, boundary_at, interior_at, shape_side(boundary), shape_cap(boundary),
                       plane=compute_n(rim))
            return True

        def emit_span(kind, sv0, sv1, l1, boundary, *, cyclic_i=False, checks=True, hold_i=(), bow=None, relax=True):
            ''' Blend between two sides of equal count, sv0[i] paired with sv1[i], with l1 - 2 new verts
            across. `boundary` is what the snap cap, mirror side and normals are taken from. `hold_i`
            names rows whose run across stays on the blend rather than being smoothed. `bow` is a pair
            of per-vert unit tangents, each pointing at the other side, that the runs across leave along:
            the blend then follows a Bezier rather than the chord, scaled by Smooth. A None tangent
            leaves that end on the chord, so a run with a surface on one side only bends there and
            arrives straight at the other. '''
            l0 = len(sv0)
            if not budget(l0 * max(0, l1 - 2)): return False
            nrm = normal_fn(boundary)
            bow_fac = (min(settings.smooth, SMOOTH_BOW_MAX) / SMOOTH_ARC_UNIT) if bow else 0.0
            if bow and l1 > 2: L.has_smoothing = True

            def boundary_at(i, j):
                return sv0[i] if j == 0 else sv1[i] if j == l1 - 1 else None

            def bow_offset(i, a, b, t):
                ''' How far off the chord the Bezier sits at t, across the chord only: the run keeps the
                chord's own even spacing and only bends away from it. '''
                chord = b - a
                if chord.length_squared < 1e-18: return Vector()
                u = chord.normalized()
                no_a = bow[0][i] if bow[0][i] is not None else u
                no_b = bow[1][i] if bow[1][i] is not None else -u
                h = blend_handle_length(a, no_a, b, no_b) * bow_fac
                p1, p2 = a + no_a * h, b + no_b * h
                mt = 1.0 - t
                at = a * mt**3 + p1 * (3 * mt * mt * t) + p2 * (3 * mt * t * t) + b * t**3
                d = at - (a * mt + b * t)
                return d - u * d.dot(u)

            def interior_at(i, j):
                pj = j / (l1 - 1)
                a, b = co_of(sv0[i]), co_of(sv1[i])
                co = a * (1 - pj) + b * pj
                if bow_fac: co = co + bow_offset(i, a, b, pj)
                return co, blend_pair(nrm(sv0[i]), nrm(sv1[i]), pj)

            build_grid(kind, l0, l1, boundary_at, interior_at, shape_side(boundary), shape_cap(boundary),
                       cyclic_i=cyclic_i, checks=checks, relax=relax,
                       hold={ i * l1 + j for i in hold_i for j in range(l1) })
            return True

        def run_bows(sv0, sv1):
            ''' The `bow` pair for a bridge between two open runs: each run's surface tangents, turned at
            the other run. None when neither run has a face to carry on from. '''
            toward = []
            for a, b in zip(sv0, sv1):
                d = co_of(b) - co_of(a)
                toward.append(d.normalized() if d.length_squared > 1e-18 else Vector())
            bow0 = run_surface_tangents(sv0, toward)
            bow1 = run_surface_tangents(sv1, [ -d for d in toward ])
            if not (bow0 or bow1): return None
            return (bow0 or [None] * len(sv0), bow1 or [None] * len(sv1))

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
            sharp0, sharp1 = turn_sharpness(cos0), turn_sharpness(cos1)
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
            # Smooth on a loft is how smoothly it blends between the two loops, not a relax pass over
            # the verts between them: each run leaves its loop along that loop's own plane normal, so
            # a loft round a bend curves through it instead of shearing across the chord. Relaxing
            # here instead pulled every interior loop toward the mean of its neighbours, which shrinks
            # a curved loop by (1 - cos(turn per edge)) a pass -- a waist on anything tightly curved,
            # and nothing to pull it back out without a source under it. It also leaves the corner
            # runs between matching sharp corners alone, which the relax pass had to be told to hold.
            def toward(nrm_loop, sign):
                if nrm_loop.length_squared < 1e-12: return None
                nrm_loop = nrm_loop.normalized()
                return nrm_loop if nrm_loop.dot(axis) * sign > 0 else -nrm_loop
            bow_a, bow_b = toward(n0, 1), toward(n1, -1)
            bow = ([bow_a] * n, [bow_b] * n) if (bow_a and bow_b) else None
            return emit_span('loft', bmvs0, bmvs1, loops + 2, bmvs0 + bmvs1, cyclic_i=True,
                             bow=bow, relax=False)

        def rank_grid_splits(bmvs):
            ''' Every distinct way to fill a closed even loop the way Blender's Grid Fill does, as a
            span x (half - span) rectangle with its four corners somewhere round the loop: (span,
            offset into bmvs) pairs, best first, so Solution 1 is the automatic choice. '''
            n = len(bmvs)
            cos = [co_of(v) for v in bmvs]
            if n < 4 or n % 2: return []    # an odd loop cannot be closed with quads alone
            half = n // 2

            sharp = turn_sharpness(cos)
            def side_mid(a, cnt):
                # middle of the side running cnt edges from vert a
                k = a + cnt // 2
                return cos[k % n] if cnt % 2 == 0 else (cos[k % n] + cos[(k + 1) % n]) / 2

            # every distinct split is a solution: for each span, the corner placement scoring best
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
                    if best is None or score < best[0]: best = (score, span, off, aspect)
                if best is None: continue
                # span s and span half-s at matching offsets are the same four corners
                corner_set = frozenset((best[2] + k) % n for k in (0, span, half, half + span))
                if corner_set in seen: continue
                seen.add(corner_set)
                ranked.append(best)
            ranked.sort(key=lambda r: (round(r[0], 6), abs(r[1] - half / 2)))    # ties go to the squarest count
            # a split of long slivers is no answer, unless it is the only one
            kept = [ r for r in ranked if r[3] <= MAX_GRID_ASPECT ] or ranked[:1]
            return [ (span, off) for _, span, off, _ in kept ]

        def choose_solution(count, prefer=None):
            ''' Which of `count` ranked solutions the Solution property picks, 1-based and wrapped. A
            new selection always starts at 1, and the property is brought back to match; a scheduled
            write stands in for the property until it lands. `prefer` is the number the Solution on
            screen holds now, when the list was renumbered under it: unless the artist moved the
            property, that Solution keeps the screen and the property follows it. '''
            sig = L.selection_signature(bm, sel_edges)
            fresh = sig != L.grid_sig
            L.grid_sig = sig
            if fresh:
                choice = 1
                L.pole_pos = {}
                if settings.solution != 1: L.push_solution(1, settings.solution)
            elif L.solution_pending is not None and settings.solution == L.solution_stale:
                choice = L.solution_pending                   # not yet landed in the property
            else:
                L.solution_pending = L.solution_stale = None  # the property has moved on and drives
                choice = settings.solution
            renumbered = not fresh and prefer is not None and choice == L.solution_seen and prefer != choice
            if renumbered:
                choice = prefer
                L.push_solution(prefer, settings.solution)
            choice = (choice - 1) % count + 1
            if (fresh or (choice != L.solution_seen and not renumbered)) and settings.offset != 0:
                # a Solution starts at Offset 0, its automatic placement; the knob follows the rebuild
                L.push_prop('offset', 0, settings.offset)
                settings.offset = 0
            L.solution_seen = choice
            return choice

        def strips_face(sv0, sv1):
            ''' sv1 turned to run the same way as sv0, when the two strips face each other across a gap
            rather than lying end to end. None when they do not, and so do not ask to be bridged. '''
            dir0 = (sv0[0].co - sv0[-1].co).normalized()
            dir1 = (sv1[0].co - sv1[-1].co).normalized()
            # The ends pair the way that keeps the outer rungs from crossing. Two strips at right angles,
            # an L that was never joined, have no common direction to go by, and the sign of the one they
            # have is noise: the pairing with the shorter rungs is the one an artist would draw
            same = (sv0[0].co - sv1[0].co).length + (sv0[-1].co - sv1[-1].co).length
            crossed = (sv0[0].co - sv1[-1].co).length + (sv0[-1].co - sv1[0].co).length
            tie = abs(crossed - same) <= 1e-6 * max(same, crossed)
            if (crossed < same and not tie) or (tie and dir0.dot(dir1) < 0):
                sv1 = list(reversed(sv1))
                dir1 = -dir1
            # strips lying end to end along one line are one strip with a gap in it, not a bridge; only
            # strips running near enough parallel can lie that way
            if abs(dir0.dot(dir1)) > math.cos(math.radians(45)):
                if angle_deg(dir0, (sv1[0].co - sv0[0].co).normalized()) < 45: return None
                if angle_deg(dir1, (sv0[0].co - sv1[0].co).normalized()) < 45: return None
            return sv1

        def choose_solve(kinds):
            ''' Which of `kinds` the Solve property picks, best first, and the ranking its own items are
            built from. A new selection starts at the best, as a Solution does, and so does a choice
            this selection cannot take; the property is brought back to it either way. '''
            L.solve_ranked = list(kinds)
            if not kinds: return None
            sig = L.selection_signature(bm, sel_edges)
            fresh = sig != L.solve_sig
            L.solve_sig = sig
            if fresh or settings.solve not in kinds:
                if settings.solve != kinds[0]: L.push_prop('solve', kinds[0], settings.solve)
                return kinds[0]
            return settings.solve

        def emit_grid_split(bmvs, span, off, kind):
            ''' Coons-fill a closed loop as the span x (half - span) rectangle whose first corner is bmvs[off]. '''
            n = len(bmvs)
            half = n // 2
            def side_verts(a, cnt):
                return [ bmvs[(a + k) % n] for k in range(cnt + 1) ]
            sv0 = side_verts(off, span)                              # c00 -> c10
            sv1 = side_verts(off + span, half - span)                # c10 -> c11
            sv2 = side_verts(off + half, span)[::-1]                 # c01 -> c11
            sv3 = side_verts(off + half + span, half - span)[::-1]   # c00 -> c01
            return emit_rect_grid(sv0, sv1, sv2, sv3, kind)

        def emit_grid_fill(bmvs, kind):
            ''' Blender's Grid Fill for a closed loop with no corners, the Solution property choosing
            among the distinct splits, each Coons-filled and snapped. '''
            if loop_is_rim(list(bmvs)): return True    # the outline of an island: nothing to fill, whichever way round the grid goes
            ranked = rank_grid_splits(bmvs)
            if not ranked: return True
            L.grid_ranked = [ ('grid', span, off) for span, off in ranked ]
            _, span, off = L.grid_ranked[choose_solution(len(ranked)) - 1]
            L.has_grid = True
            L.grid_last = (span, settings.offset)
            L.offset_seen = settings.offset
            L.offsets = max(1, len(bmvs) // 2)     # a rotation by half the loop lands the same corners
            return emit_grid_split(bmvs, span, (off + settings.offset) % len(bmvs), kind)

        def pos_key(pt):
            return tuple(round(c, 6) for c in co_of(pt))

        def loop_is_rim(pts, nrm=None):
            ''' Whether the mesh, not a hole, is what this loop encloses: the outline of an island. The
            loop winds counter-clockwise about its area normal, so what it encloses lies to the left of
            the way it runs; the faces on its one-faced edges lying there, by majority, are inside it, and
            a fill would lay over them. Points a pass created have no faces and do not vote. '''
            if nrm is None:
                nrm = loop_area_normal([ co_of(pt) for pt in pts ])
                if nrm.length_squared < 1e-18: return False
                nrm = nrm.normalized()
            faced = 0
            for a, b in zip(pts, pts[1:] + pts[:1]):
                if not (isinstance(a, BMVert) and isinstance(b, BMVert)): continue
                bme = bmvs_shared_bme(a, b)
                if bme is None or len(bme.link_faces) != 1: continue
                to_face = bme.link_faces[0].calc_center_median() - (a.co + b.co) / 2
                faced += 1 if to_face.dot(nrm.cross(b.co - a.co)) > 0 else -1
            return faced > 0

        def loop_frame(pts, forced=frozenset()):
            ''' How a hole's boundary reads for stepping: (unit normal the loop winds counter-clockwise
            about, its corners, those of them turning into the hole, the sharpest bend turning out of it
            in degrees, the signed bend at every vert), corners as indices into pts. None where there is nothing to read: a loop with
            no area, or one whose inside is the mesh rather than a hole. pts may hold points a step
            created as readily as verts; `forced` holds pos_keys of the verts the steps' rows landed on,
            corners when they bend at all sharply. '''
            n = len(pts)
            cos = [ co_of(pt) for pt in pts ]
            nrm = loop_area_normal(cos)
            if nrm.length_squared < 1e-18: return None
            nrm.normalize()
            if loop_is_rim(pts, nrm): return None
            def turn(i):
                # signed bend at pts[i]: positive turning into the hole, the convex way round for it
                d0, d1 = cos[i] - cos[i - 1], cos[(i + 1) % n] - cos[i]
                if d0.length_squared < 1e-18 or d1.length_squared < 1e-18: return 0.0
                a = angle_deg(d0.normalized(), d1.normalized())
                return a if d0.cross(d1).dot(nrm) >= 0 else -a
            turns = [ turn(i) for i in range(n) ]
            # a landing vert bending past NOTCH_ANGLE is a corner whatever the Split Angle says: stepping
            # would not build a quad across that bend, so neither should the fill. One cut off flush is not
            corners = [ i for i in range(n) if (pos_key(pts[i]) in forced and abs(turns[i]) > NOTCH_ANGLE)
                        or is_corner(pts[i], pts[i - 1], pts[(i + 1) % n]) ]
            convex = { i for i in corners if turns[i] > 0 }
            return nrm, corners, convex, max((-t for t in turns), default=0.0), turns

        def arm_candidates(pts, frame):
            ''' Every side of a notched hole that could be stepped into it: (where the far side starts,
            its edge count, the rows its rails allow), indices into pts reading forward. A far side is a
            run between two corners turning into the hole; its rails are the boundary on beyond each of
            them, which run out at the next corner either way, so a step is never deeper than the shorter
            rail. Returns nothing on a loop with no bend turning out of the hole. '''
            nrm, corners, convex, reflex, _ = frame
            n, k = len(pts), len(corners)
            if reflex <= NOTCH_ANGLE or k < 3: return []
            out = []
            for i in range(k):
                c1, c2 = corners[i], corners[(i + 1) % k]
                if c1 not in convex or c2 not in convex: continue
                m = (c2 - c1) % n
                rail0 = (c1 - corners[i - 1]) % n           # back from c1 to the corner before it
                rail2 = (corners[(i + 2) % k] - c2) % n     # on from c2 to the corner after it
                # the two rails have to land on different verts, with a loop of three or more left over
                depth = min(rail0, rail2, (n - m - 1) // 2, (n - 3) // 2)
                if depth >= 1: out.append((c1, m, depth))
            return out

        def arm_rows(pts, cand, inside):
            ''' The rows an arm's far side can be carried down its rails, the far side itself first, each
            a run from the rail vert on one side to the rail vert on the other with the points between
            them created. Stops at the first row whose quads go bad -- crossed, reaching outside the hole,
            or below the floor quad_squareness holds every quad in the tool to, a step's included -- so
            the arm runs as far as a step along the same rails would, one row into the flare where a neck
            widens into the body it hangs off, and no further. The rows are blends, not snapped: the shape
            tested is the one the fill will be asked to make, and a snap cannot make a good row out of a
            bad one. '''
            n = len(pts)
            c1, m, depth = cand
            at = lambda k: pts[k % n]
            sv1 = [ at(c1 + j) for j in range(m + 1) ]
            base = [ co_of(p) for p in sv1 ]
            def holds(q):
                return not quad_crosses_itself(q) and quad_squareness(q) is not None
            rows, why = [sv1], 'the rails ran out'
            for k in range(1, depth + 1):
                e0, e2 = at(c1 - k), at(c1 + m + k)
                off0, off2 = co_of(e0) - base[0], co_of(e2) - base[-1]
                row = [e0] + [ base[j] + off0.lerp(off2, j / m) for j in range(1, m) ] + [e2]
                if not all(inside(p) for p in row[1:-1]):
                    why = f'row {k} reaches outside the hole'
                    break
                prev = rows[-1]
                if not all(holds([ co_of(prev[j]), co_of(prev[j + 1]), co_of(row[j + 1]), co_of(row[j]) ]) for j in range(m)):
                    why = f'row {k} makes a bad quad'
                    break
                rows.append(row)
            if DEBUG_NOTCH: print(f'[notch] side at {c1}, {m} wide, rails {depth} deep: {len(rows) - 1} row(s), {why}')
            return rows

        def emit_arm(pts, cand, rows):
            ''' Build the rows as one Coons patch and hand back the loop with the arm replaced by the row
            it landed on, and the two verts that row ends on. None when the fill's own checks refused it,
            False when the vert budget is spent. '''
            n = len(pts)
            c1, m, _ = cand
            kept = len(rows) - 1
            at = lambda k: pts[k % n]
            rail0 = [ at(c1 - k) for k in range(kept, -1, -1) ]         # landing end first, up to the far side
            rail2 = [ at(c1 + m + k) for k in range(kept, -1, -1) ]
            sv1 = rows[0]
            boundary = rail0 + sv1 + rail2
            nrm = normal_fn(boundary)
            side, cap = shape_side(boundary), shape_cap(boundary)
            n0, n2 = nrm(rail0[0]), nrm(rail2[0])
            landing = ([rail0[0]] + [ new_point(p, side, blend_pair(n0, n2, j / m), cap) for j, p in enumerate(rows[-1][1:-1], 1) ]
                       + [rail2[0]])
            if not budget(m - 1): return False      # the landing row; emit_rect_grid budgets the rows inside
            at_mark = mark()
            marked = at_mark[0]
            if not emit_rect_grid(rail0, sv1, rail2, landing, 'C'): return False
            if len(L.previz) == marked:
                if DEBUG_NOTCH: print(f'[notch] arm at {c1} refused')
                return None
            # the blend fills the rows between rather than taking them as they were tested, so what was
            # built is asked the same question one more time
            if any(quad_crosses_itself([ pv.vert_co[i] for i in f ]) for pv in L.previz[marked:] for f in pv.faces):
                if DEBUG_NOTCH: print(f'[notch] arm at {c1} folds the side it steps onto')
                rewind(at_mark)
                return None
            out = [ at(c1 + m + kept + i) for i in range(n - m - 2 * kept + 1) ] + landing[1:-1]
            # A row can land on the boundary across from it, and a loop that visits a point twice fills
            # as folded quads. The quads this one just made go back with it: left in the preview with
            # the loop unchanged, the fill would cover them a second time.
            if len({ tuple(round(c, 6) for c in co_of(pt)) for pt in out }) != len(out):
                if DEBUG_NOTCH: print('[notch] the loop left over visits a point twice')
                rewind(at_mark)
                return None
            return out, (rail0[0], rail2[0])

        def sweep_arms(pts):
            ''' Step the arms off a hole one at a time, the deepest first, reading the boundary afresh
            after each so the next sees the rails and corners the last one used up. (the loop left, how
            many were stepped, pos_keys of the verts its rows landed on), or False when the budget is
            spent. The landing verts are corners of what is left whatever their bend: the row is a side
            of it, and read as one the body a neck hangs off has the four corners its pole and junction
            Solutions want, where its bends alone might give it two. '''
            loop, steps, forced = pts, 0, set()
            # every step takes at least two verts off the loop, so the sweep runs itself out; the range
            # is only there so a step that somehow left the loop as long as it found it cannot spin here
            for _ in range(len(pts)):
                if len(loop) < 3: break
                frame = loop_frame(loop, forced)
                if frame is None: break
                cos = [ co_of(p) for p in loop ]
                frm = plane_frame(frame[0], cos[1] - cos[0])
                if frm is None: break
                u, w = frm
                poly = [ Vector((co.dot(u), co.dot(w))) for co in cos ]
                eps = 1e-4 * sum((b - a).length for a, b in zip(poly, poly[1:] + poly[:1])) / len(poly)
                def inside(p):
                    # strictly: a row landing on the boundary across from it is the arm run out, not a step
                    q = Vector((p.dot(u), p.dot(w)))
                    return point_in_polygon_2d(q, poly) and all(dist2d_point_segment(q, a, b) > eps for a, b in zip(poly, poly[1:] + poly[:1]))
                # Every candidate is stepped dry and the one longest for its width built: that is what
                # makes an arm an arm, and a wide side that steps a few rows is usually the body a
                # narrower arm hangs off. One the fill's checks refuse says nothing about the rest.
                tried = [ (cand, rows) for cand in arm_candidates(loop, frame) if len(rows := arm_rows(loop, cand, inside)) > 1 ]
                tried.sort(key=lambda t: (-(len(t[1]) - 1) / t[0][1], -(len(t[1]) - 1)))
                if DEBUG_NOTCH: print(f'[notch] ranked: {[ (cand[0], cand[1], len(rows) - 1) for cand, rows in tried ]}')
                stepped = None
                for cand, rows in tried:
                    stepped = emit_arm(loop, cand, rows)
                    if stepped is False: return False
                    if stepped is not None: break
                if stepped is None: break
                loop, ends = stepped
                steps += 1
                forced |= { pos_key(v) for v in ends }
            return loop, steps, forced

        def fill_loop(loop, forced):
            ''' Fill a loop of verts and points a pass left as a loop like any other: by its corners where
            it has three or more, with every Solution that brings, else Blender's grid fill. True built,
            None refused, False when the vert budget is spent. '''
            marked = len(L.previz)
            frame = loop_frame(loop, forced)
            corners = frame[1] if frame else []
            if len(corners) >= 3:
                n, k = len(loop), len(corners)
                sides = [ [ loop[(c1 + j) % n] for j in range((c2 - c1) % n + 1) ]
                          for c1, c2 in zip(corners, corners[1:] + corners[:1]) ]
                ok = emit_sides({ 3: 'tri', 4: 'rect' }.get(k, 'ngon'), sides)
            else:
                ok = emit_grid_fill(loop, 'grid')
            if not ok: return False
            return True if len(L.previz) > marked else None

        def pass_holds(bmvs, before):
            ''' Whether what a pass built since `before` holds to the hole: a bowtie is no answer whatever
            its count, and neither is a patch reaching past the boundary. True, the pieces fused into one
            patch, since they share the verts of every side the pass created; else why not, with nothing
            changed, so the caller can take the piece at fault back and try another. '''
            pvs = L.previz[before:]
            quads = [ [ pv.vert_co[i] for i in f ] for pv in pvs for f in pv.faces ]
            if any(quad_crosses_itself(q) for q in quads): return 'a quad came out crossed'
            cos_in = [ co_of(p) for p in bmvs ]
            if loop_is_flat(cos_in):
                nrm_in = loop_area_normal(cos_in)
                if nrm_in.length_squared > 1e-18:
                    u = nrm_in.normalized()
                    # Stokes puts the signed sum of the quads at the loop's own area whatever the patch
                    # does in between, so only the unsigned sum can overrun it, and only by folding or
                    # reaching past the boundary. A quad facing the other way shows up here too, as
                    # twice its own area, which is why the slack is a share of the hole rather than a
                    # count: a sliver worth a thousandth of it is not worth dropping a whole fill for.
                    got = sum(abs(loop_area_normal(q).dot(u)) for q in quads)
                    if got > abs(nrm_in.dot(u)) * (1 + NOTCH_COVER_SLACK): return 'the quads cover more than the hole'
            L.previz[before:] = [ fuse_previz(pvs, kind='grid', hover=False) ]
            return True

        def strike_built(why):
            ''' Note the placement emit_ranked last built as one that will not do here, so the next fill
            of the same loop passes it over: True when there was one to strike. '''
            if L.solution_built is None: return False
            loop_key, key, placement = L.solution_built
            nt = L.solution_notes.get(loop_key, {}).get(key)
            if nt is None: return False
            if DEBUG_NOTCH: print(f'[notch] {why}: Solution {key[0]!r} placement {placement} struck')
            nt['invalid'].add(placement)
            nt['valid'].discard(placement)
            L.solution_built = None
            return True

        def emit_notched(bmvs):
            ''' Step every arm of a notched hole square, then fill what is left of it by its own corners
            -- which may be nothing, where the arms met and covered the hole between them. None when
            there was no arm to step, or when the fill after them was refused, which hands the loop back
            whole for the caller's own fill to try; False when the vert budget is spent. '''
            at_mark = mark()
            before = at_mark[0]
            was = (L.has_grid, L.grid_ranked, L.grid_last)
            def give_up(why):
                if DEBUG_NOTCH: print(f'[notch] gave up: {why}')
                rewind(at_mark)
                L.has_grid, L.grid_ranked, L.grid_last = was
                return None

            swept = sweep_arms(list(bmvs))
            if swept is False: return False
            loop, steps, forced = swept
            if not steps: return None
            if DEBUG_NOTCH: print(f'[notch] {steps} arm(s) stepped, {len(loop)} left')
            if len(loop) >= 3:
                # what is left is filled by its own corners. A fill of it that spills past the hole or folds
                # against the arms is struck for this loop, as a placement that refused is, and the next
                # placement or Solution tried: the arms are sound, and the pass is only given up when
                # nothing fills what they leave
                while True:
                    leftover = mark()
                    L.solution_built = None
                    ok = fill_loop(loop, forced)
                    if ok is False: return False
                    if ok is None: return give_up(f'fill of the {len(loop)} left over refused')
                    held = pass_holds(bmvs, before)
                    if held is True: return True
                    rewind(leftover)
                    if not strike_built(held): return give_up(held)
            held = pass_holds(bmvs, before)
            return True if held is True else give_up(held)

        def emit_cleft(bmvs):
            ''' Cut a hole in two at a boundary vert bending sharply into it -- the cleft of a heart, a
            fin jutting into a plate -- along a run of new verts from there to the boundary across, and
            fill each piece by its own corners. One fill laid over the whole hole runs its rows straight
            across the cleft, over the mesh. None when the hole has no such vert, no cut across it stays
            inside, or a piece refused its fill, which hands the loop back whole; False when the vert
            budget is spent. '''
            pts = list(bmvs)
            frame = loop_frame(pts)
            if frame is None: return None
            nrm, _, _, reflex, turns = frame
            if reflex <= CLEFT_ANGLE: return None
            n = len(pts)
            cos = [ co_of(p) for p in pts ]
            frm = plane_frame(nrm, cos[1] - cos[0])
            if frm is None: return None
            u, w = frm
            poly = [ Vector((co.dot(u), co.dot(w))) for co in cos ]
            lens = [ (b - a).length for a, b in zip(cos, cos[1:] + cos[:1]) ]
            mean_edge = sum(lens) / n
            if mean_edge <= 1e-9: return None
            side, cap = shape_side(pts), shape_cap(pts)
            nrm_of = normal_fn(pts)
            at_mark = mark()
            before = at_mark[0]
            was = (L.has_grid, L.grid_ranked, L.grid_last)
            def give_up(why):
                if DEBUG_NOTCH: print(f'[cleft] gave up: {why}')
                rewind(at_mark)
                L.has_grid, L.grid_ranked, L.grid_last = was
                return None

            def crosses_boundary(r, t):
                # the cut may touch the boundary only at its two ends
                for i in range(n):
                    j = (i + 1) % n
                    if r in (i, j) or t in (i, j): continue
                    if segments_cross2d(poly[r], poly[t], poly[i], poly[j]): return True
                return False

            # the sharpest cleft first, then the rest, each cut toward the boundary vert nearest the line
            # that halves its bend: that is the line the two lobes meet along
            for r in sorted((i for i in range(n) if -turns[i] > CLEFT_ANGLE), key=lambda i: turns[i]):
                a = (cos[r - 1] - cos[r]).normalized()
                b = (cos[(r + 1) % n] - cos[r]).normalized()
                bis = -(a + b)                  # a + b points out of the hole, into the mesh the cleft is cut from
                if bis.length_squared < 1e-12: continue
                bis.normalize()
                best = None
                for t in range(n):
                    if (t - r) % n < 2 or (r - t) % n < 2: continue
                    d = cos[t] - cos[r]
                    if d.length_squared < 1e-18: continue
                    off = angle_deg(bis, d.normalized())
                    if off > CLEFT_AIM: continue
                    if best is not None and off >= best[0]: continue
                    if not point_in_polygon_2d((poly[r] + poly[t]) / 2, poly) or crosses_boundary(r, t): continue
                    best = (off, t)
                if best is None:
                    if DEBUG_NOTCH: print(f'[cleft] vert {r} bends {-turns[r]:.0f} degrees but no cut across stays inside')
                    continue
                t = best[1]
                # the cut's own verts, spaced as the boundary is, one more or less so each piece comes out
                # even and can be filled with quads; both pieces are, as the whole was
                span = (cos[t] - cos[r]).length
                want = span / mean_edge - 1
                c = max(0, round(want))
                if ((t - r) % n + c + 1) % 2:
                    c = c - 1 if (c > 0 and abs(c - 1 - want) <= abs(c + 1 - want)) else c + 1
                fracs = [ k / (c + 1) for k in range(1, c + 1) ]
                cut = [ new_point(co, side, nn, cap)
                        for co, nn in arc_between(cos[r], nrm_of(pts[r]), cos[t], nrm_of(pts[t]), fracs) ]
                if not budget(c): return False
                piece_a = [ pts[(r + j) % n] for j in range((t - r) % n + 1) ] + cut[::-1]
                piece_b = [ pts[(t + j) % n] for j in range((r - t) % n + 1) ] + cut
                forced = { pos_key(pts[r]), pos_key(pts[t]) }
                if DEBUG_NOTCH: print(f'[cleft] vert {r} bends {-turns[r]:.0f} degrees: cut to vert {t}, {c} vert(s) along it, pieces of {len(piece_a)} and {len(piece_b)}')
                refused = None
                for piece in (piece_a, piece_b):
                    ok = fill_loop(piece, forced)
                    if ok is False: return False
                    if ok is None:
                        refused = f'a piece of {len(piece)} refused its fill'
                        break
                if refused:
                    give_up(refused)
                    continue
                held = pass_holds(bmvs, before)
                if held is True: return True
                give_up(held)
            return None

        def emit_ngon(kind, shape):
            ''' Fill a closed loop of three or more strips by its real corners; solutions_for has the ways. '''
            sides = chain_sides(shape)
            if not sides: return True
            return emit_sides(kind, sides)

        def emit_sides(kind, sides, rails=None):
            ''' Fill a closed loop given as its sides with the Solution chosen among solutions_for's. '''
            loop = [ v for side in sides for v in side[:-1] ]
            if rails is None and loop_is_rim(loop): return True    # the outline of an island
            return emit_ranked(solutions_for(kind, sides, rails), frozenset(pos_key(v) for v in loop))

        def solution_key(entry):
            ''' What tells one Solution of a loop from another across rebuilds. '''
            return (entry.tag, entry.split, tuple(NL.plan_key(p) for p in entry.plans))

        def emit_ranked(entries, loop_key=None):
            ''' Offer fills (FillSolution) as the Solutions of one selection, ranked: every plain quad fill
            first, then the fills that close an odd loop with one triangle or n-gon, then the degenerate
            ones, and within each as given. Builds the one chosen at the Offset asked for; a placement
            that refuses is skipped for the next on round, the way the knob was turned, and a Solution
            every placement of which refuses is dropped from the list, the one after it taking its
            number. What each placement did is noted for the selection, so it is built once to find
            out. The Offset knob is offered only once a second placement is known to build. False only
            when the vert budget is spent. '''
            nonlocal n_new
            if not entries: return True
            entries = sorted(entries, key=lambda e: (e.degenerate, e.odd))
            notes = L.solution_notes.setdefault(loop_key, {})
            def note(entry):
                return notes.setdefault(solution_key(entry), { 'valid': set(), 'invalid': set(), 'count': entry.offsets })
            def dead(entry):
                nt = note(entry)
                return not nt['valid'] and len(nt['invalid']) >= nt['count']
            alive = [ e for e in entries if not dead(e) ]
            L.grid_ranked = alive
            L.has_grid = True
            if not alive: return True
            # A setting change forgets the notes, and a Solution that was dropped may build again and take
            # back its place in the list, renumbering the one on screen; choose_solution keeps that one
            shown = L.solution_shown.get(loop_key)
            at = next((i for i, e in enumerate(alive) if solution_key(e) == shown), None) if shown is not None else None
            first = choose_solution(len(alive), None if at is None else at + 1) - 1
            asked = settings.offset
            step = 1 if asked >= L.offset_seen else -1

            def attempt(entry, off):
                ''' Build entry at placement off, keeping what it makes: True, or False with nothing kept
                when it refused, None when the budget is spent. Either way the placement is noted. '''
                nonlocal n_new
                nt = note(entry)
                at = mark()
                saved = (L.has_offset, L.has_free_step, L.has_smoothing, L.hint, n_new, dict(L.pole_pos))
                settings.offset = off
                L.offsets = entry.offsets
                ok = entry.build()
                nt['count'] = max(nt['count'], L.offsets)      # a junction counts its placements as it builds
                if ok is None: return None
                if ok:
                    nt['valid'].add(off % nt['count'])
                    return True
                nt['invalid'].add(off % nt['count'])
                nt['valid'].discard(off % nt['count'])     # a placement that built before and refuses now: the world moved under the notes
                rewind(at)
                L.has_offset, L.has_free_step, L.has_smoothing, L.hint, n_new, L.pole_pos = saved
                return False

            def would_build(entry, off):
                ''' attempt() keeping nothing either way. '''
                nonlocal n_new
                at = mark()
                saved = (L.has_offset, L.has_free_step, L.has_smoothing, L.hint, n_new, dict(L.pole_pos), settings.offset)
                ok = attempt(entry, off)
                if ok: rewind(at)
                L.has_offset, L.has_free_step, L.has_smoothing, L.hint, n_new, L.pole_pos, settings.offset = saved
                return ok

            while alive:
                idx = first % len(alive)
                entry = alive[idx]
                nt = note(entry)
                # the placement asked for, then the rest on round the way the knob was turned, those known to refuse skipped
                ok, j = False, 0
                while j < nt['count']:
                    off = asked + step * j
                    j += 1
                    if off % nt['count'] in nt['invalid']: continue
                    ok = attempt(entry, off)
                    if ok is None: return False
                    if ok: break
                if DEBUG_FILL: print(f'[fill] Solution {idx + 1} of {len(alive)} ({entry.tag}): ' + (f'built at Offset {settings.offset}' if ok else f'refused at every one of its {nt["count"]} placement(s), dropped'))
                if not ok:
                    alive.pop(idx)
                    L.grid_ranked = alive
                    settings.offset = asked
                    continue
                if settings.offset != asked: L.push_prop('offset', settings.offset, asked)
                if idx + 1 != L.solution_seen:
                    # the list wrapped, or lost entries, under the number asked for: the property follows
                    L.push_solution(idx + 1, settings.solution)
                    L.solution_seen = idx + 1
                # the knob is offered once a second placement is known to build; the unknown ones are tried, kept from nothing
                j = 1
                while nt['count'] > 1 and len(nt['valid']) < 2 and j < nt['count']:
                    off = settings.offset + j
                    j += 1
                    if off % nt['count'] in nt['invalid'] or off % nt['count'] in nt['valid']: continue
                    if would_build(entry, off) is None: return False
                L.offsets = 2 if len(nt['valid']) >= 2 else 1
                L.grid_last = (entry.tag, settings.offset)
                L.offset_seen = settings.offset
                L.solution_shown[loop_key] = solution_key(entry)
                L.solution_built = (loop_key, solution_key(entry), settings.offset % nt['count'])
                if entry.hint: L.hint = entry.hint
                return True
            return True

        def built(fn):
            # a grid builder returns False only when the vert budget is spent, and adds nothing when its checks refuse
            before = len(L.previz)
            if not fn(): return None
            return len(L.previz) > before

        def solutions_for(kind, sides, rails=None):
            ''' Every way to fill a closed loop given as its sides, runs of verts each sharing its ends with
            the next (points this fill creates as well as the mesh's verts, as a bridge's do), as
            FillSolutions in rank order. `rails` names the sides a turnout should leave through rather
            than run its rows along: the two a bridge created, or a C's back and the side closing it. '''
            counts = [ len(sv) - 1 for sv in sides ]
            total = sum(counts)
            if kind == 'rect' and counts[0] == counts[2] and counts[1] == counts[3]:
                s0, s1, s2, s3 = sides
                return [ FillSolution('rect', build=lambda: built(lambda: emit_rect_grid(s0, s1, s2[::-1], s3[::-1], 'rect'))) ]
            bmvs = [ v for sv in sides for v in sv[:-1] ]
            m = len(bmvs)
            corners, pos = [], 0
            for c in counts:
                corners.append(pos)
                pos += c
            # a created point has no index; minus one minus its place round the loop names it, an int like
            # an index so ngon_layout reads it as one of the loop's own verts (its tuple keys are the nodes
            # it makes), and stable through the rebuilds so a dragged pole stays put
            keys = [ (v.index if isinstance(v, BMVert) else -1 - i) for i, v in enumerate(bmvs) ]
            key_at = { id(v): key for v, key in zip(bmvs, keys) }
            loop = NL.Loop(tuple(keys), tuple(corners))
            bmv_of = dict(zip(keys, bmvs))
            cos = [ co_of(v) for v in bmvs ]
            sharp = turn_sharpness(cos)
            mean_edge = sum((cos[(k + 1) % m] - cos[k]).length for k in range(m)) / m

            loop_key = frozenset(loop.nodes)
            layouts = {}
            def layout_of(plan):
                if id(plan) not in layouts: layouts[id(plan)] = NL.build_layout(plan)
                return layouts[id(plan)]

            real = [ v for v in bmvs if isinstance(v, BMVert) ]
            plane_n, plane_c = fit_plane_of_verts(real) if len(real) >= 3 else (None, None)
            if plane_n is not None and plane_n.length_squared > 1e-12:
                plane_u = plane_n.orthogonal().normalized()
                plane_v = plane_n.cross(plane_u).normalized()
            else:
                plane_n = plane_u = plane_v = None

            def to_plane(p):
                return Vector(((p - plane_c).dot(plane_u), (p - plane_c).dot(plane_v)))

            poly2d = [ to_plane(c) for c in cos ] if plane_n is not None else None

            def clamp_inside(co):
                ''' The point moved inside the loop, at least NGON_POLE_MARGIN mean edges from its boundary,
                in the loop's plane: a pole on or beyond the boundary makes slivers, or a fill outside. '''
                if co is None or poly2d is None: return co
                q = to_plane(co)
                margin = NGON_POLE_MARGIN * mean_edge
                inside = False
                for a, b in zip(poly2d, poly2d[1:] + poly2d[:1]):
                    if (a.y > q.y) != (b.y > q.y) and q.x < a.x + (b.x - a.x) * (q.y - a.y) / (b.y - a.y): inside = not inside
                ccw = sum(a.x * b.y - b.x * a.y for a, b in zip(poly2d, poly2d[1:] + poly2d[:1])) > 0
                best = None
                for a, b in zip(poly2d, poly2d[1:] + poly2d[:1]):
                    ab = b - a
                    l2 = ab.length_squared
                    if l2 < 1e-18: continue
                    t = max(0.0, min(1.0, (q - a).dot(ab) / l2))
                    p = a + ab * t
                    d = (q - p).length
                    if best is None or d < best[0]:
                        best = (d, p, (Vector((-ab.y, ab.x)) if ccw else Vector((ab.y, -ab.x))).normalized())
                if best is None or (inside and best[0] >= margin): return co
                d, p, inward = best
                q2 = p + inward * margin
                return plane_c + plane_u * q2.x + plane_v * q2.y + plane_n * (co - plane_c).dot(plane_n)

            def pole_estimate(plan):
                ''' Where a plan's pole belongs before anything is built: the mean over its corner regions of
                the parallelogram completion of each region's two boundary runs, the far corner a region
                keeping its corner's shape would have, clamped inside the loop. '''
                # this separates two placements on a symmetric loop, whose split verts average to the same spot, and
                # follows the loop's shape where the edges are uneven; a radical centre of spoke count times mean edge
                # put a bridge's pole in its short side's corner with the spokes folded over
                lay = layout_of(plan)
                pole = lay.poles[0]
                helpers = { k: (a, b) for k, a, b in lay.helpers }
                def at(k):
                    key = lay.nodes[k]
                    if k in lay.existing: return co_of(bmv_of[key])
                    if k in helpers: return (at(helpers[k][0]) + at(helpers[k][1])) / 2
                    return None
                if pole in lay.existing: return at(pole)
                far = []
                for grid in lay.regions:
                    l0, l1 = len(grid), len(grid[0])
                    if l0 < 2 or l1 < 2 or grid[l0 - 1][l1 - 1] != pole: continue
                    c00, c10, c01 = at(grid[0][0]), at(grid[l0 - 1][0]), at(grid[0][l1 - 1])
                    if c00 is None or c10 is None or c01 is None: continue
                    far.append(c10 + c01 - c00)
                if far: return clamp_inside(sum(far, Vector()) / len(far))
                # a layout with no whole region round the pole: where its spokes start, averaged
                starts = [ q for line in lay.polylines if line[-1] == pole and (q := at(line[0])) is not None ]
                return clamp_inside(sum(starts, Vector()) / len(starts)) if starts else None

            def pick_candidate(cands):
                ''' (plan, where its pole goes or None) out of the plans that differ only in pole placement.
                Offset steps through them; a pole the artist dragged picks the placement nearest to where
                it was put and pins the pole there, until the Solution or Offset changes. '''
                under = (settings.solution, settings.offset)
                placed = L.pole_pos.get(loop_key)
                if placed and placed[0] != under:
                    L.pole_pos.pop(loop_key)            # changing the Solution or Offset puts the pole back
                    placed = None
                if L.pole_drag and L.pole_drag[0] == loop_key:
                    placed = L.pole_pos[loop_key] = (under, L.pole_drag[1])
                if placed is None:
                    return cands[settings.offset % len(cands)], None
                co = clamp_inside(placed[1])     # a pole dragged onto or past the boundary stops short of it
                def dist(plan):
                    est = pole_estimate(plan)
                    return (est - co).length if est is not None else float('inf')
                return min(cands, key=dist), co

            def emit_junction(which, orient):
                ''' A junction taking up a step in the row count, the loop laid over a rectangle by
                ngon_layout.orient_sides(sides, *orient): 'diamond' or 'bow' between equal rails, 'turnout'
                between rails that differ by as much as the sides do. Offset picks its position. '''
                # every new vert starts on the Coons blend of the four sides, the unequal sides sampled by fraction so
                # their rows line up with the columns, then relaxes like a spoke (build_layout_previz's seed)
                if which == 'turnout':
                    cands = NL.turnout_positions(*NL.turnout_shape(counts, orient))
                    L.offsets = len(cands)
                    k, j = cands[settings.offset % len(cands)]
                sv0, sv1, sv2, sv3 = NL.orient_sides(sides, *orient)
                ncol, nrow = len(sv0) - 1, len(sv3) - 1
                side_keys = [ [ key_at[id(v)] for v in s ] for s in (sv0, sv1, sv2, sv3) ]
                nrm = normal_fn(bmvs)
                c00, c10, c01, c11 = sv0[0], sv0[-1], sv2[0], sv2[-1]

                def along(s, t):
                    # point and normal a fraction t along side s, between the two verts either side of it
                    x = t * (len(s) - 1)
                    a = min(int(x), len(s) - 2)
                    f = x - a
                    return co_of(s[a]).lerp(co_of(s[a + 1]), f), blend_pair(nrm(s[a]), nrm(s[a + 1]), f)

                def at(pi, pj):
                    (l, nl), (rr, nr), (b, nb), (t, nt) = along(sv0, pi), along(sv2, pi), along(sv3, pj), along(sv1, pj)
                    co = coons(l, rr, b, t, co_of(c00), co_of(c10), co_of(c01), co_of(c11), pi, pj)
                    return co, blend_normal(nl, nr, nb, nt, nrm(c00), nrm(c10), nrm(c01), nrm(c11), pi, pj)

                if which == 'diamond':
                    # two of the long side's lines merge at a 5-pole and the one between them ends at a 3-pole, in one
                    # quad turned across the columns
                    cands = NL.diamond_positions(ncol, nrow)
                    L.offsets = len(cands)
                    k, j = cands[settings.offset % len(cands)]
                    layout, columns, R = NL.build_diamond(side_keys, k, j)

                    def up(c, r):
                        # how far up column c its vert r sits: the short side's spacing up to the 5-pole's column,
                        # the long side's from the 3-pole's on, and their mean on the column between, where the
                        # rows either side of the junction are already one long-side row apart
                        if c <= k: return r / nrow
                        if c >= k + 2: return r / (nrow + 2)
                        return ((r / nrow + r / (nrow + 2)) if r <= j else ((r - 1) / nrow + (r + 1) / (nrow + 2))) / 2

                    extra = { R: at((k + 1.5) / ncol, (up(k + 1, j) + up(k + 1, j + 1) + 2 * up(k + 2, j + 1)) / 4) }
                elif which == 'turnout':
                    # the extra rows leave through the longer rail past a 5-pole and a 3-pole on one column
                    short = len(sv1) - 1
                    d = nrow - short
                    layout, left, right, wedge = NL.build_turnout(side_keys, k, j)
                    w = short - j

                    def seam_pi(r):
                        # the seam runs from the top rail's vert k to the bottom rail's, at different fractions of
                        # rails that differ in count; the left block's rows space it
                        return (1 - r / nrow) * k / ncol + (r / nrow) * k / (ncol + d)

                    seed = { node: at(seam_pi(r), r / nrow) for r, node in enumerate(left[k]) if node not in layout.existing }
                    # the wedge's right side runs from the 5-pole down to the rail vert d past the seam's foot, its verts
                    # between the wedge's own spacing and the right block's rows, which they also make
                    for v in range(1, w):
                        t = v / w
                        seed[wedge[0][v]] = at(seam_pi(j) * (1 - t) + (k + d) / (ncol + d) * t, ((j / nrow) * (1 - t) + t + (j + v) / short) / 2)
                    return build_layout_previz('ngon', layout, bmv_of, bmvs, seed=seed)
                else:
                    # one line per two edges of the step leaves the short side's end verts and bows through one column,
                    # each inside the last, the long side's outer lines ending on them with two 3-poles
                    depth = (len(sv1) - len(sv3)) // 2
                    long = nrow + 2 * depth
                    # at k = 0 each end of the short side carries two quads, which share its corner's angle. A short side
                    # bending into the patch closes those corners (a rail meeting it sharply does too), and once one is
                    # under BOW_CORNER_MIN_DEG the smaller of its two quads comes out under about 30 degrees, squashed
                    # against the bow; the bow then leads from the middle column instead
                    def corner(c, a, b):
                        return angle_deg((co_of(a) - co_of(c)).normalized(), (co_of(b) - co_of(c)).normalized())
                    closed = min(corner(c00, sv0[1], sv3[1]), corner(c01, sv2[1], sv3[-2])) < BOW_CORNER_MIN_DEG
                    cands = NL.bow_positions(ncol, central=closed)
                    L.offsets = len(cands)
                    k = cands[settings.offset % len(cands)]
                    layout, columns, bows = NL.build_bow(side_keys, k, depth)
                    up = lambda c, r: r / nrow if c <= k else r / long
                    # the bows share the column out evenly, and each runs from the height of the long rail's vert its
                    # top fan quad pairs it with to that of the one its bottom fan quad does, its verts evenly between
                    extra = { node: at((k + (t + 1) / (depth + 1)) / ncol, (t + 1 + i * (long - 2 * (t + 1)) / nrow) / long)
                              for t, bow in enumerate(bows) for i, node in enumerate(bow) }
                seed = { node: at(c / ncol, up(c, r)) for c, col in enumerate(columns) for r, node in enumerate(col)
                         if node not in layout.existing }
                seed.update(extra)
                return build_layout_previz('ngon', layout, bmv_of, bmvs, seed=seed)

            odd = bool(total % 2)
            if odd:
                # no quad fill closes an odd loop: an imaginary extra vertex on one side, filled round a pole
                # and taken out again, leaves one n-gon or triangle at the pole, drawn in the warning colour.
                # Each way of taking it out is one Solution; which side carries the vertex is the pole handle.
                # A loop no side of which can carry the vertex (four sides need equal opposite sides) has
                # corners demoted first, the least sharp first, and the loop left is filled the same way: 2,3,4,4
                # becomes the 5,4,4 triangle, quads and one triangle. Those fills follow the loop's own, if any, and
                # like the even loop's demotions at most NGON_MAX_ALTERNATIVES of them are offered
                def side_len(plan):
                    # mean edge length of the side carrying the vertex, on the loop the plan fills
                    keys = [ k for k in plan.pieces[0][0].sides()[plan.phantom[1]] if k in bmv_of ]
                    return sum((co_of(bmv_of[a]) - co_of(bmv_of[b])).length for a, b in zip(keys, keys[1:])) / max(1, len(keys) - 1)
                by_rank = lambda p: (p.score, -side_len(p))
                phantoms = sorted(NL.plan_phantom(loop), key=by_rank)
                demoted = sorted(NL.plan_phantom_merges(loop, { c: sharp[c] for c in corners }), key=by_rank)
                # within one shape (ngon_layout.phantom_shape: the loop filled and the way the vertex is taken out),
                # Offset 0 is the placement that keeps the triangle or n-gon off the sides and puts its pole nearest
                # the loop's centre; the rest follow outward, ties in the order above. A shape whose best placement
                # touches a side goes behind one whose best does not, among the loop's own fills and within a demotion
                centre = sum(cos, Vector()) / m
                def off_centre(plan):
                    est = pole_estimate(plan)
                    return round((est - centre).length / mean_edge, 3) if est is not None else float('inf')
                def against_side(plan):
                    return NL.odd_face_on_boundary(layout_of(plan))
                def shape_groups(plans):
                    shapes = []
                    for p in plans:
                        if NL.phantom_shape(p) not in shapes: shapes.append(NL.phantom_shape(p))
                    return [ sorted([ p for p in plans if NL.phantom_shape(p) == sh ], key=lambda p: (against_side(p), off_centre(p))) for sh in shapes ]
                groups = sorted(shape_groups(phantoms), key=lambda g: against_side(g[0]))
                # score[1:3] is the demoted corners' turn and how many, so the least sharp demotion stays first
                groups += sorted(shape_groups(demoted), key=lambda g: (g[0].score[1:3], against_side(g[0])))[:NGON_MAX_ALTERNATIVES]
                grids = []
            else:
                poles = NL.plan_pole(loop)
                # every interior placement of the pole is one Solution with a draggable pole; the boundary ones another
                groups = [ g for g in ([ p for p in poles if p.strict ], [ p for p in poles if not p.strict ]) if g ]
                # plans of one shape, the same corners demoted or the same cut made from the other end, are one
                # Solution: Offset steps through them, or the dragged pole picks the one nearest to it
                groups += NL.group_plans(NL.plan_merges(loop, { c: sharp[c] for c in corners }))[:NGON_MAX_ALTERNATIVES]
                if not groups:
                    def cut_penalty(plan):
                        # a cut whose chord is far from its edge count times the mean edge makes long or crushed quads
                        pen = 0.0
                        for run in plan.cuts:
                            a, b = bmv_of.get(run[0]), bmv_of.get(run[-1])
                            if a is None or b is None: continue     # ends on another cut, which has no position yet
                            chord = (co_of(a) - co_of(b)).length
                            pen += abs(math.log(max(chord, 1e-9) / max((len(run) - 1) * mean_edge, 1e-9)))
                        return pen
                    key = (loop.nodes, loop.corners)
                    if key not in L.ngon_cuts:
                        if len(L.ngon_cuts) > 8: L.ngon_cuts.clear()
                        L.ngon_cuts[key] = NL.plan_cuts(loop) if m <= NGON_MAX_CUT_VERTS else []
                    cuts = list(L.ngon_cuts[key])
                    cuts.sort(key=lambda p: (p.score[:3], round(cut_penalty(p), 3)))
                    groups += NL.group_plans(cuts)[:NGON_MAX_ALTERNATIVES]
                grids = rank_grid_splits(bmvs)

            # a quad along two boundary edges at a plain boundary vert reads as a triangle on the mesh, and at a
            # corner turning against the loop it is concave; every fill that makes one ranks behind every fill
            # that does not, whatever its kind. Grid corners are judged at Offset 0 so the order holds under the knob
            corner_set = set(corners)
            winding = sum(a.x * b.y - b.x * a.y for a, b in zip(poly2d, poly2d[1:] + poly2d[:1])) if poly2d is not None else 0.0
            def reflex(p):
                if poly2d is None: return False
                a, b, c = poly2d[(p - 1) % m], poly2d[p], poly2d[(p + 1) % m]
                return ((b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x)) * winding < 0
            bad = { p for p in range(m) if p not in corner_set or reflex(p) }

            def plan_solution(group):
                def build():
                    plan, placed = pick_candidate(group)
                    return build_layout_previz('ngon', layout_of(plan), bmv_of, bmvs, handle=loop_key,
                                               pole_co=placed if placed is not None else pole_estimate(plan),
                                               pole_fixed=placed is not None, pole_clamp=clamp_inside, pole_margin=NGON_POLE_MARGIN * mean_edge)
                return FillSolution(group[0].kind, degenerate=NL.straight_through(layout_of(group[0]), loop, bad) > 0, odd=odd, build=build, plans=tuple(group),
                                    offsets=len(group))

            def grid_solution(span, off):
                hint = None
                if kind != 'rect' and not groups:
                    edit = NL.cc_hint(counts)
                    fix = (' or '.join(f'{counts[i]}→{counts[i] + d}' for i, d in edit)) if edit else None
                    hint = f'Patches: no single-pole fill for sides {tuple(counts)}' + (f'; one pole needs e.g. {fix}' if fix else '')
                return FillSolution(span, degenerate=any((off + k) % m in bad for k in (0, span, m // 2, m // 2 + span)), hint=hint, split=(span, off),
                                    build=lambda: built(lambda: emit_grid_split(bmvs, span, (off + settings.offset) % m, 'grid')), offsets=max(1, m // 2))

            def junction_solution(which, orient):
                return FillSolution(which, build=lambda: emit_junction(which, orient))

            plans = [ plan_solution(g) for g in groups ]
            if odd: return plans
            grid_fills = [ grid_solution(span, off) for span, off in grids ]
            # a junction leads where one fits: equal rails with the other sides an even number apart take the diamond
            # or the bow, which no single pole fills and an artist would draw. A four-sided loop lists its grid splits
            # before its plans, as it always did, but every one puts a grid corner at a plain vert, so emit_ranked
            # sorts them last as degenerate
            entries = grid_fills + plans if kind == 'rect' else plans + grid_fills
            if kind == 'rect':
                if (fit := NL.step_fits(counts)) is not None:
                    entries = [ junction_solution(which, (fit[0], False)) for which in NL.junctions(*fit[1:]) ] + entries
                else:
                    turnouts = NL.turnout_fits(counts)
                    if rails is not None:
                        # a bridge's rows run strip to strip: a turnout leaving through a rail is laid out that way
                        turnouts.sort(key=lambda orient: NL.oriented_index(*orient, 2) not in rails)
                    # the layings of a turnout are one mesh seen from two sides, so the first is the Solution.
                    # Demoting the corner between the two short sides always leaves a strict single 3-pole here,
                    # and its quads come out the more even at every step, so the turnout follows the plans
                    if turnouts: entries = entries + [ junction_solution('turnout', turnouts[0]) ]
            return entries

        def emit_offset(sv, bmes, *, cyclic=False, pins=None):
            ''' Rows of quads stepped out from a run of boundary edges that has nothing to fill: an open
            strip with no partner, or a closed loop whose inside is already faces. Each vert steps the
            way the quads on the run lean, or straight out where there are none; an end that turns a
            corner onto an open edge welds onto that edge's far vert. `pins` (vert index -> [(where the
            rung should land, the vert the pin's own boundary edge runs on to)]) is what a stroke's
            quads and runs beside this run ask of its ends, ahead of any weld an end finds for itself. '''
            MITER_LIMIT = 3.0   # cap on the corner stretch 1/sin(half angle); Split Angle's 135 degree cap needs 2.61
            STEP_STALL = 0.25   # a vert travelling less than this fraction of its step means the row has run out of source
            WELD_MAX_BACK = 20.0    # how far past square a weld rung may lean back over the face the run steps away from
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
            # how far a row reaches when it extrudes; a welded end lands on its weld whatever this says
            d_step = d_mean * max(0.05, settings.step_scale)

            # Which side is out, from target topology alone and before anything the source says: a
            # run with a corner to follow must never depend on the source's answer at the crease.
            def face_out(i):
                ''' Away from the faces this vert's own run edges carry, across the run. None where
                neither run edge carries a single face, which on a boundary means a wire vert. '''
                acc = Vector()
                for bme in (bmes[(i - 1) % n] if (cyclic or i > 0) else None,
                            bmes[i] if (cyclic or i < n - 1) else None):
                    if bme is None or len(bme.link_faces) != 1: continue
                    va, vb = bme.verts
                    al = vb.co - va.co
                    if al.length_squared < 1e-14: continue
                    al = al.normalized()
                    to_old = bme.link_faces[0].calc_center_median() - (va.co + vb.co) / 2
                    to_old -= al * to_old.dot(al)
                    if to_old.length_squared > 1e-14: acc -= to_old.normalized()
                return acc.normalized() if acc.length_squared > 1e-12 else None

            outs = [ face_out(i) for i in range(n) ]

            nrm = normal_fn(sv)     # the source normal under each run vert

            def source_perps():
                ''' Straight out across the run and in the surface, at every vert, signed away from
                the run's own faces, or toward the mouse when it has none. None when some vert has
                nothing to lean on. '''
                # Last resort for a wire run with no source: the plane the run itself lies in,
                # and the view direction when it is too straight to fit one.
                run_plane_n = None
                if not sources:
                    pn, _ = fit_plane_of_verts(sv)
                    if (pn is None or pn.length_squared < 1e-12) and context.region_data:
                        pn = Mi.to_3x3() @ view_forward_direction(context)
                    run_plane_n = pn.normalized() if (pn is not None and pn.length_squared > 1e-12) else None
                perps, prev_n = [], None
                for i, v in enumerate(sv):
                    # A normal facing along the run leaves no perpendicular at all, and the source
                    # hands one back wherever the nearest point is on a surface square to the run: the
                    # side wall at the end of a run in an alcove corner. As unusable as no normal, so
                    # it takes the same fallbacks rather than refusing the whole run.
                    cands = [ nrm(v) ]
                    cands += [ bmf.normal for bme in v.link_edges if bme in run_edges for bmf in bme.link_faces ]
                    cands.append(run_plane_n)
                    nv = p = None
                    for c in cands:
                        if c is None or c.length_squared < 1e-12: continue
                        q = along[i].cross(c)
                        if q.length_squared < 1e-12: continue
                        nv, p = c, q
                        break
                    if nv is None: return None      # no source, no face and no plane: nothing to lean on
                    # keep the normal continuous along the run, so two verts finding opposite faces of
                    # a thin surface do not put the row on both sides
                    if prev_n is not None and nv.dot(prev_n) < 0: nv, p = -nv, -p
                    prev_n = nv
                    perps.append(p.normalized())

                signs = [ 0 if o is None else (1 if (dt := o.dot(perps[i])) > 0 else (-1 if dt < 0 else 0))
                          for i, o in enumerate(outs) ]
                if any(signs):
                    # a vert whose own edges carry no face takes the side of the nearest one that does
                    for order in (range(n), range(n - 1, -1, -1)):
                        last = 0
                        for i in order:
                            if signs[i]: last = signs[i]
                            elif last: signs[i] = last
                    return [ p * signs[i] for i, p in enumerate(perps) ]
                # a wire run has no faces to step away from, so it steps toward the mouse
                mid_i = n // 2
                side_sign, s_mouse = mouse_side(cos[0], cos[mid_i if cyclic else -1], cos[mid_i],
                                                perps[mid_i] * d_mean)
                if s_mouse and not cyclic: L.wire_runs.append((cos[0].copy(), cos[-1].copy(), s_mouse))
                return [ -p for p in perps ] if side_sign < 0 else perps

            def lean_dirs(perps):
                ''' Step direction per vert: the quad's edge leaving the run there. Each of the vert's
                two run edges gets one vote and the two are averaged, so where the run turns between two
                poles the rail between them lands between what each side wants. A side edge running
                along the run, a non-quad, or a quad on the far side leaves that side with nothing to
                say; it then votes for the perp rather than standing aside, which would hand the whole
                direction to the other side. '''
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
                return dirs

            # A wire end has no face to be outward of. There the side the mouse is on stands in, and
            # that is the source's answer: a run with a wire end asks it now, one with faces never has to.
            perps = None
            if not cyclic and (outs[0] is None or outs[-1] is None):
                perps = source_perps()
                if perps is None: return True   # no source, no face and no plane: nothing to lean on
                outs = [ o if o is not None else p for o, p in zip(outs, perps) ]

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

            def leans_back(d, i):
                ''' Whether a rung at vert i lies back over the face the run is stepping away from,
                which would put the new quad on top of it. The limit sits past square rather than at
                it: `out` lies in the plane of that face, so a rung turning onto another surface at a
                crease has no component along it at all, and a stricter test throws out the very
                corner being looked for. '''
                return angle_deg(d, outs[i]) > 90.0 + WELD_MAX_BACK

            def keeps_shape(i_end, i_prev, w):
                ''' Whether a rung from the end vert to `w` still makes a quad worth having on the end
                edge: the parallelogram the two span, judged like any other quad. An anchor's direction
                and length are carried to the whole run, so a rung leaning far off square or reaching
                far past the run's own spacing bends and stretches every quad, not just this one. Below
                the shape floor a fresh vert makes the better quad and the end steps free. '''
                d = co_of(w) - cos[i_end]
                ok = quad_squareness([cos[i_prev], cos[i_end], cos[i_end] + d, cos[i_prev] + d]) is not None
                if DEBUG_OFFSET and not ok:
                    print(f'[offset] anchor at {sv[i_end].index} -> {w.index if isinstance(w, BMVert) else "pt"} refused: bends or stretches the run')
                return ok

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
                out = outs[i_end]
                best, best_dot = None, None
                for _bme, w in open_edges_at(v, (bmes[-1] if i_end == n - 1 else bmes[0],)):
                    if w in run_verts or w in used: continue
                    d = w.co - v.co
                    if d.length_squared < 1e-14: continue
                    d = d.normalized()
                    if leans_back(d, i_end): continue
                    # without topology to say corner, the boundary itself has to turn, or w is nothing
                    # but the run carrying on and there is no corner here to weld round
                    if not topo_corner and angle_deg(-arrive, d) >= min_angle: continue
                    if not keeps_shape(i_end, i_prev, w): continue
                    if best_dot is None or d.dot(out) > best_dot: best, best_dot = w, d.dot(out)
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

            def pinned(i_end, i_prev):
                ''' The rung a stroke asks this end to land on: the vert a quad beside the run put
                there, or the rung of a run this one carries on from. Only where what it came with
                runs straight on from this run, by Split Angle. Where the boundary turns a corner at
                this end, the quad beside it is round the corner, its vert lies straight ahead of the
                run rather than across it, and this side of the corner needs a rung of its own. '''
                if not pins: return None
                v = sv[i_end]
                arrive = v.co - sv[i_prev].co
                if arrive.length_squared < 1e-14: return None
                back = -arrive.normalized()
                for w, nb in pins.get(v.index, ()):
                    onward = nb.co - v.co
                    if onward.length_squared < 1e-14: continue
                    if angle_deg(back, onward.normalized()) < min_angle: continue
                    d = co_of(w) - v.co
                    if d.length_squared < 1e-14 or leans_back(d.normalized(), i_end): continue
                    if isinstance(w, BMVert) and w in run_verts: continue
                    if not keeps_shape(i_end, i_prev, w): continue
                    return w
                return None

            used_welds = set()
            weld0 = weld1 = None
            if not cyclic:
                weld0 = pinned(0, 1)
                weld1 = pinned(n - 1, n - 2)
                if weld0 is None: weld0 = weld_target(0, 1, used_welds)
                if weld1 is None: weld1 = weld_target(n - 1, n - 2, used_welds)
                if weld0 is not None and weld0 is weld1: return True   # both ends fold onto one vert: not a row of quads
            row0_welds = { i: w for i, w in ((0, weld0), (n - 1, weld1)) if w is not None }

            # Direction, in the order the answers are trustworthy. A weld knows where the row actually
            # goes, so it aims the whole run the way it already sets the distance: carried to each vert
            # by the run's own turn, and blended end to end when both ends weld. Only with no weld is
            # the source asked, and on a crease it answers with whichever surface is nearest.
            aimed_by_weld = False   # row 0 is going where a weld says, not where the old faces lean
            carried = {}
            for i_w, w in row0_welds.items():
                d = co_of(w) - cos[i_w]
                if d.length_squared < 1e-14: continue
                # walked out from the weld one edge at a time: neighbouring tangents never oppose each
                # other, where the two ends of a run bent into a U do
                walk = list(range(n) if i_w == 0 else range(n - 1, -1, -1))
                ds = { i_w: d.normalized() }
                for j, i in zip(walk, walk[1:]):
                    ds[i] = along[j].rotation_difference(along[i]) @ ds[j]
                carried[i_w] = [ ds[i] for i in range(n) ]
            if carried:
                # one weld aims the whole run, two blend end to end; with one, both ends of the blend
                # are the same carried direction and it falls out
                fr = cumulative_fracs(cos)
                a0 = carried.get(0) or carried[n - 1]
                a1 = carried.get(n - 1) or a0
                # two welds pointing near-opposite blend to nothing: that vert takes the first end's
                dirs = [ (a.normalized() if a.length_squared > 1e-12 else a0[i])
                         for i, a in enumerate(a0[i] * (1 - fr[i]) + a1[i] * fr[i] for i in range(n)) ]
                aimed_by_weld = True
            else:
                # no corner to follow, so the source gets to say which way is out
                if perps is None: perps = source_perps()
                if perps is None: return True   # no source, no face and no plane: nothing to lean on
                dirs = lean_dirs(perps)
            if DEBUG_OFFSET:
                print(f'[offset] run n={n} cyclic={cyclic} welds={ {i: (w.index if isinstance(w, BMVert) else "pt") for i, w in row0_welds.items()} } '
                      f'aimed={aimed_by_weld} dirs[0]={tuple(round(c, 3) for c in dirs[0])} dirs[mid]={tuple(round(c, 3) for c in dirs[n // 2])}')

            def row_base(prev_cos, welds):
                ''' Step vector for each vert of the previous row. A welded end must land exactly on its
                weld, so its own offset is used unmitered and whatever its direction could not account
                for is carried across the run, fading out. '''
                if not welds:
                    return [ dirs[i] * (d_step * miter[i]) for i in range(n) ]
                fr = cumulative_fracs(prev_cos)
                scale = lambda i, l: dirs[i] * (l * (1.0 if i in welds else miter[i]))
                if len(welds) == 1:
                    i_w, w = next(iter(welds.items()))
                    D = co_of(w) - prev_cos[i_w]
                    r = D - dirs[i_w] * D.length
                    return [ scale(i, D.length) + r * (fr[i] if i_w else 1 - fr[i]) for i in range(n) ]
                D0, D1 = co_of(welds[0]) - prev_cos[0], co_of(welds[n - 1]) - prev_cos[-1]
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
            if DEBUG_OFFSET: print(f'[offset] far_row={"yes" if far_row else "no"} steps={steps} d_step={d_step:.4f} d_mean={d_mean:.4f}')
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
                    res = complete_quad(bm, known, slots, min_squareness=WELD_FIT_MIN_SQUARENESS)
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
                    if quad_squareness([ co_of(c) for c in q ]) is None or not face_is_placeable(bm, q):
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
                used_welds |= { w for w in welds.values() if isinstance(w, BMVert) }   # a pinned point is nobody's to reuse

                base = row_base(prev_cos, welds)
                if max(b.length for b in base) < 1e-9: return True
                if k == 0 and (far_row is None or steps != 1):
                    weld_fit_row0(base, welds, [ prev_cos[i] + base[i] for i in range(n) ])

                # snap cap: a couple of this row's own steps, averaged rather than maxed so a mitered
                # corner does not set the cap for the whole row. Past it a vert stays where the step put it.
                cap = SNAP_CAP_EDGES * max(span_w, sum((M3 @ b).length for b in base) / n)

                row_free = False
                if far_row is not None and k == steps - 1:
                    row, missed = list(far_row), []   # the last row IS the far side of the hole
                else:
                    row, missed = [], []
                    for i in range(n):
                        if i in welds:
                            row.append(welds[i])
                            continue
                        # The normal test stops nearest point pulling a guessed vert onto the back of a
                        # form. A weld-aimed first row is no guess, and at a crease the run vert's normal
                        # is the surface being left, which would refuse every hit on the one stepped onto.
                        nb = None if (k == 0 and aimed_by_weld) else (source_normal(prev_row[i]) or nrm(sv[i]))
                        pt = new_point(prev_cos[i] + base[i], side, nb, cap, ray=False, missed=missed)
                        if not cyclic and i in (0, n - 1): pt = to_planes(pt, sym_axes(cos[i]) - run_axes)
                        row.append(pt)
                        row_free = True    # this vert reached out rather than landing on existing geometry
                row_cos = [ co_of(pt) for pt in row ]
                if far_row is None or k != steps - 1:
                    # a row that found no source, folded back on itself, or stopped advancing leaves the
                    # quads from here on unusable: keep what is good and stop
                    bad_miss, bad_fold = bool(sources and missed), folds_back(prev_cos, row_cos)
                    bad_stall = stalled(prev_cos, row_cos, base)
                    if bad_miss or bad_fold or bad_stall:
                        if DEBUG_OFFSET:
                            print(f'[offset] row {k} refused: missed={len(missed)} folds_back={bad_fold} stalled={bad_stall} cap={cap:.4f}')
                            print('[offset]   ' + ' '.join(f'{tuple(round(c, 3) for c in prev_cos[i])}+{base[i].length:.3f}'
                                                           f'->{tuple(round(c, 3) for c in row_cos[i])}' for i in range(n)))
                        steps = k
                        break
                rows.append(row)
                if row_free: L.has_free_step = True
                prev_row, prev_prev_cos, prev_cos = row, prev_cos, row_cos

            if not rows:
                if DEBUG_OFFSET: print('[offset] no rows kept')
                return True
            if DEBUG_OFFSET: print(f'[offset] built {len(rows)} row(s)')
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
                L.labels.append((str(steps), [ sum((co_of(verts[k]) for k in outer), Vector()) / n ]))
            add_previz('offset', verts, edges, faces,
                       [ k for k in outer if not isinstance(verts[k], BMVert) ], outer)
            return True

        def emit_quad_strip(q, kind, *, cuts=None):
            ''' One quad on four corners (BMVerts, or a Vector for a corner the fill creates), cut into
            `cuts + 1` quads across its longer dimension. Interior points are blended between the two
            short sides and snapped, as a bridge's are. `cuts` None takes the artist's count and says
            the count is theirs to set; a fixed count is for a quad whose sides are already decided. '''
            cos = [ co_of(v) for v in q ]
            la = ((cos[1] - cos[0]).length + (cos[2] - cos[3]).length) / 2   # sides 0-1 and 3-2
            lb = ((cos[3] - cos[0]).length + (cos[2] - cos[1]).length) / 2   # sides 0-3 and 1-2
            if la >= lb: sv0, sv1 = [q[0], q[3]], [q[1], q[2]]   # the strips are the short sides
            else:        sv0, sv1 = [q[0], q[1]], [q[3], q[2]]
            existing = [ v for v in q if isinstance(v, BMVert) ]
            # a cut runs from one short side to the other and splits the long sides.
            if cuts is None and any(
                isinstance(a, BMVert) and isinstance(b, BMVert) and bmvs_shared_bme(a, b)
                is not None for a, b in zip(sv0, sv1)
            ):
                cuts = 0
            n_cuts = settings.crosses if cuts is None else cuts
            if not emit_span(kind, sv0, sv1, max(1, n_cuts + 1) + 1, existing, checks=False): return False
            if cuts is None: L.has_quad = True
            return True

        def emit_tri(verts):
            ''' Three selected verts as one triangle. Nothing new is created but the face and whichever
            of its three sides are not already edges. '''
            new_edges = [ (a, b) for a, b in ((0, 1), (1, 2), (2, 0))
                          if bmvs_shared_bme(verts[a], verts[b]) is None ]
            add_previz('triangle', verts, new_edges, [(0, 1, 2)])

        def emit_ngon_face(bmvs):
            ''' Close a loop with one face. '''
            bmvs = list(bmvs)
            n = len(bmvs)
            if n < 3 or len({ v.index for v in bmvs }) != n: return
            if bm.faces.get(bmvs) is not None: return
            new_edges = []
            for i, (a, b) in enumerate(zip(bmvs, bmvs[1:] + bmvs[:1])):
                bme = bmvs_shared_bme(a, b)
                if bme is None: new_edges.append((i, (i + 1) % n))
                elif len(bme.link_faces) >= 2: return
            add_previz('ngon', bmvs, new_edges, [tuple(range(n))])

        def emit_corner_quad(bmv, pair=None):
            ''' F2's quad from a vertex: two open edges leaving a corner are two sides of a quad and the
            fourth corner is their parallelogram completion. Edges already sharing a face have no gap
            between them to fill. The cursor picks between pairings, as F2 does, unless the caller has
            settled on one. '''
            rgn, r3d = context.region, context.region_data
            mouse = Vector((mouse_at[0] - rgn.x, mouse_at[1] - rgn.y)) if (mouse_at is not None and rgn and r3d) else None
            if pair is None: pair = corner_pairing(bmv, mouse, rgn, r3d, M)
            if pair is None: return True
            va, vb = pair
            da, db = va.co - bmv.co, vb.co - bmv.co
            co = va.co + vb.co - bmv.co

            # where two strips meet at this vert the fourth corner is already there
            nbrs_b = { bme.other_vert(vb) for bme in vb.link_edges }
            corner = next((w for bme in va.link_edges
                           if (w := bme.other_vert(va)) is not bmv and w in nbrs_b), None)
            if corner is None:
                # or a point the artist already dropped about where the corner would go
                r = WELD_FIT_RADIUS * (da.length + db.length) / 2
                cands = [ w for w in L._candidates_near(context, bm, co, r) if w not in (va, vb, bmv) ]
                res = complete_quad(bm, [va, bmv, vb], [cands], min_squareness=WELD_FIT_MIN_SQUARENESS) if cands else None
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
            q = [ M @ co_of(v) for v in verts ]
            if quad_squareness(q) is None: return True
            if rgn and r3d:
                pts = [ location_3d_to_region_2d(rgn, r3d, co) for co in q ]
                if all(pts) and not is_convex_2d(pts): return True
            if not face_is_placeable(bm, verts): return True

            # Its two sides are existing edges, and cutting across would have to split one of them,
            # so there is no count here: one quad, and no Cuts in the panel or on the scroll knob.
            return emit_quad_strip(verts, 'corner', cuts=0)

        if stroke is not None:
            ##############################################
            # A stroke: everything it has collected plus what the cursor asks for now, as one rebuild.
            # Picked quads and notch quads go first, since the runs are shaped round them: a side of
            # theirs that is a mesh edge is theirs to fill, and each existing boundary corner of theirs
            # hands the vert beside it to whatever run ends there, so that run's rung IS that vert. The
            # collected edges chain into runs and step as one, their rungs blended where they meet; a run
            # is only re-stepped when it has changed. An edge on offer is stepped on its own, pinned to
            # the rung of the run it ends beside, so hovering along a long run costs one edge, not the run.
            key = L._candidate_key(context)
            if key is not None and key != L.cand_key: L._collect_candidates(bm, key)
            nverts = len(bm.verts)

            def vert(i):
                if i is None or not (0 <= i < nverts): return None
                v = bm.verts[i]
                return v if v.is_valid and not v.hide else None

            offer = L.pick_offer(context, bm, M, mouse_at) if (stroke_offer == 'pick' and mouse_at is not None) else None
            quads, corners, offer_edge = dict(stroke.quads), dict(stroke.corners), None
            if offer is not None:
                if offer[0] == 'q': quads.setdefault(frozenset(offer[1]), (offer[1], offer[2]))
                elif offer[0] == 'c': corners.setdefault(offer[1], (offer[2], offer[3]))
                else: offer_edge = frozenset(offer[1:3])

            def tag(before, src):
                for pv in L.previz[before:]:
                    pv.face_src = tuple(src for _ in pv.faces)
                    pv.hover = True

            owned, pins = set(), {}     # pins: vert index -> [(rung to land on, the vert the pin's boundary edge runs on to)]
            def claim(ring):
                for i, v in enumerate(ring):
                    if not isinstance(v, BMVert): continue
                    p, q = ring[i - 1], ring[(i + 1) % len(ring)]
                    jp = isinstance(p, BMVert) and bmvs_shared_bme(v, p) is not None
                    jq = isinstance(q, BMVert) and bmvs_shared_bme(v, q) is not None
                    if jp: owned.add(frozenset((v.index, p.index)))
                    if jq: owned.add(frozenset((v.index, q.index)))
                    if jp != jq: pins.setdefault(v.index, []).append((q, p) if jp else (p, q))

            for qkey, (ring, _cost) in quads.items():
                verts = [ vert(i) for i in ring ]
                if any(v is None for v in verts) or len(set(verts)) != len(verts): continue
                before, n = len(L.previz), len(verts)
                add_previz('nearest', verts,
                           [ (i, (i + 1) % n) for i in range(n) if bmvs_shared_bme(verts[i], verts[(i + 1) % n]) is None ],
                           [tuple(range(n))])
                tag(before, ('q', qkey))
                claim(verts)
            corner_faces = {}
            for C, (ia, ib) in corners.items():
                vc, va, vb = vert(C), vert(ia), vert(ib)
                if vc is None or va is None or vb is None: continue
                before = len(L.previz)
                emit_corner_quad(vc, pair=(va, vb))
                if len(L.previz) == before: continue
                tag(before, ('c', C))
                pv = L.previz[before]
                ring = [ (vert(pv.vert_idx[k]) if pv.vert_idx[k] is not None else pv.vert_co[k]) for k in pv.faces[0] ]
                if any(v is None for v in ring): continue
                claim(ring)
                corner_faces[C] = ([ pv.vert_idx[k] for k in pv.faces[0] ], [ pv.vert_co[k] for k in pv.faces[0] ])
            stroke.corner_faces = { C: f for C, f in corner_faces.items() if C in stroke.corners }

            def step_edge(ekey):
                if ekey in owned or len(ekey) != 2: return None
                va, vb = (vert(i) for i in ekey)
                bme = bmvs_shared_bme(va, vb) if va is not None and vb is not None else None
                return None if bme is None or bme.hide or len(bme.link_faces) >= 2 else bme

            def pin_key(v):
                return tuple(((w.index if isinstance(w, BMVert) else tuple(round(c, 6) for c in w)), nb.index)
                             for w, nb in pins.get(v.index, ()))

            def emit_run(sv, bmes, cyclic, run_pins):
                ''' emit_offset, with each face of the row tagged by the edge it came from. '''
                before = len(L.previz)
                ok = emit_offset(sv, bmes, cyclic=cyclic, pins=run_pins)
                nseg = len(bmes)
                for pv in L.previz[before:]:
                    pv.hover = True
                    # emit_offset lays a row out edge by edge, so face k came from edge k % nseg
                    pv.face_src = tuple(('e', frozenset(v.index for v in bmes[k % nseg].verts)) for k in range(len(pv.faces)))
                return ok, L.previz[before:]

            step_bmes = [ bme for ekey in stroke.edges if (bme := step_edge(ekey)) is not None ]
            sel_edges = frozenset(step_bmes)    # a run's rails may not be edges the stroke is itself stepping
            rung_pins, step_faces = {}, []      # run end vert index -> (its rung, the run vert before it)
            for sv, bmes, cyclic in edge_chains(step_bmes):
                # what a run's result depends on: its edges, what its ends are pinned to, which other stepped
                # edges meet its ends (those are barred as rails), and the settings
                ends = { sv[0].index, sv[-1].index }
                ckey = (tuple(frozenset(v.index for v in e.verts) for e in bmes), pin_key(sv[0]), pin_key(sv[-1]),
                        frozenset(e for e in stroke.edges if e & ends), cyclic, repr(settings))
                made = stroke.chains.get(ckey)
                if made is None:
                    ok, made = emit_run(sv, bmes, cyclic, pins)
                    if all(e.link_faces for e in bmes): stroke.chains[ckey] = made    # a wire run steps toward the cursor, so it is never kept
                    if not ok: break
                else:
                    L.previz.extend(made)
                    L.has_offset = True
                n = len(sv)
                for pv in made:
                    if pv.kind != 'offset' or len(pv.vert_co) < 2 * n: continue
                    if not cyclic:
                        # the row's verts follow the run's: sv[k]'s rung is vert n + k
                        for k, nb in ((0, sv[1]), (n - 1, sv[-2])):
                            i = pv.vert_idx[n + k]
                            rung = vert(i) if i is not None else pv.vert_co[n + k]
                            if rung is not None: rung_pins.setdefault(sv[k].index, []).append((rung, nb))
                    step_faces += [ (src[1], [ pv.vert_idx[i] for i in f ], [ pv.vert_co[i] for i in f ])
                                    for f, src in zip(pv.faces, pv.face_src) ]
            stroke.step_faces = step_faces
            # a row that landed on existing verts lies along existing edges: a weld round a corner, or the
            # far side of a hole it closed. Those edges are filled by this step, so they are not offered again.
            stroke.covered = { frozenset((idx[k], idx[(k + 1) % len(idx)])) for _ekey, idx, _cos in step_faces
                               for k in range(len(idx)) if idx[k] is not None and idx[(k + 1) % len(idx)] is not None } - stroke.edges

            if offer_edge is not None and offer_edge not in stroke.edges and (bme := step_edge(offer_edge)) is not None:
                va, vb = bme.verts
                both = { i: pins.get(i, []) + rung_pins.get(i, []) for i in (va.index, vb.index) }
                before = len(L.previz)
                emit_run([va, vb], [bme], False, both)
                # The footprint that offered it is a band a little deeper than a step reaches, so the faces
                # can be known; taking needs the stroke inside those faces. Outside them there is nothing to show.
                rgn = context.region
                m = Vector((mouse_at[0] - rgn.x, mouse_at[1] - rgn.y)) if (rgn and mouse_at is not None) else None
                polys = L._polys_2d(context, [ ([ pv.vert_idx[i] for i in f ], [ pv.vert_co[i] for i in f ])
                                               for pv in L.previz[before:] for f in pv.faces ])
                if m is None or not any(point_inside_face_2d(m, poly) for poly in polys):
                    del L.previz[before:]
                    offer = None

            if L.previz: L.previz = [ fuse_previz(L.previz) ]
            L.offer = offer
            L.nearest_active = True
            return

        ##############################################
        # the corners as curve control points: every loop and string, in order, with the corners marked,
        # for the curve overlay's patch corner provider

        def chain_open(shape):
            ''' Verts of an open string of strips, head to tail, or None when they do not chain. '''
            sides = [ get_verts(strip) for strip in shape ]
            for k in range(1, len(sides)):
                if k == 1 and sides[0][-1] not in (sides[1][0], sides[1][-1]): sides[0].reverse()
                if sides[k][0] != sides[k - 1][-1]: sides[k].reverse()
                if sides[k][0] != sides[k - 1][-1]: return None
            return sides

        for kind in ('eye', 'tri', 'rect', 'ngon'):
            for shape in shapes[kind]:
                sides = chain_sides(shape)
                if not sides: continue
                verts, corners = [], []
                for sv in sides:
                    corners.append(len(verts))
                    verts.extend(v.index for v in sv[:-1])
                L.corner_chains.append((verts, corners, True))
        for kind in ('I', 'L', 'C', 'else'):
            for shape in shapes[kind]:
                sides = chain_open(shape)
                if not sides: continue
                verts, corners = [], []
                for sv in sides:
                    corners.append(len(verts))
                    verts.extend(v.index for v in sv[:-1])
                verts.append(sides[-1][-1].index)
                corners.append(len(verts) - 1)
                L.corner_chains.append((verts, corners, False))

        ##############################################
        # closed loops: loft every stacked run of them, then fill what is left on its own

        cycles = []
        for kind in ('O', 'eye', 'tri', 'rect', 'ngon'):
            for shape in shapes[kind]:
                bmes = shape if kind == 'O' else [ bme for strip in shape for bme in strip ]
                bmvs = cycle_bmvs(bmes)
                if bmvs: cycles.append((kind, shape, bmvs))

        # Which loops would loft with which, worked out before anything is built so the Solve property
        # knows a loft is on offer. A loop in the middle of a stack is the boundary of the loft on each
        # side of it, so it belongs to both.
        loft_pairs = []
        if len(cycles) >= 2:
            planes = [ fit_plane_of_verts(bmvs) for _, _, bmvs in cycles ]
            order = order_rings_along_axis([ ctr for _, ctr in planes ],
                                           [ nrm for nrm, _ in planes ], align=LOFT_PARALLEL)
            for ia, ib in zip(order, order[1:]):
                bmvs_a, bmvs_b = cycles[ia][2], cycles[ib][2]
                if not (len(bmvs_a) == len(bmvs_b) >= 3): continue
                (na, ctr_a), (nb, ctr_b) = planes[ia], planes[ib]
                if not (na and nb and ctr_a and ctr_b): continue
                axis = ctr_b - ctr_a
                if axis.length <= 1e-9: continue
                axis = axis.normalized()
                # the walk already asked that the two face the same way; this asks that they are
                # stacked along that facing rather than sitting side by side
                if not (abs(na.dot(nb)) >= LOFT_PARALLEL
                        and abs(na.dot(axis)) >= LOFT_STACKED
                        and abs(nb.dot(axis)) >= LOFT_STACKED): continue
                loft_pairs.append((ia, ib, axis))

        # What this selection could be filled as, best first.
        if cycles:
            # A loop with no corners is filled by halving it into two equal sides, which an odd one
            # cannot take at all; it is left off rather than offered and silently stepped instead.
            kind0, _, bmvs0 = cycles[0]
            cornered = kind0 in ('tri', 'rect', 'ngon')
            quads = ['FILL'] if (cornered or (len(bmvs0) >= 4 and not len(bmvs0) % 2)) else []
            if L.ngon_verts is not None:
                # An n-gon being replaced by a patch. Closing it with one face is what is already there,
                # and a ring stepped round its perimeter would leave a smaller hole and no patch, so a
                # quad fill is the only thing on offer and neither of those is worth naming.
                solve = choose_solve(quads)
            else:
                # One face always fits, and on a flat loop (a hole rather than the mouth of a form) it beats stepping outward.
                # A step is offered only where its ring will build round one of the loops.
                flat = loop_is_flat([ co_of(v) for v in bmvs0 ])
                step = ['STEP'] if any((bmes := cycle_bmes(bmvs)) and dry_run(lambda: emit_offset(bmvs, bmes, cyclic=True))
                                       for _, _, bmvs in cycles) else []
                solve = choose_solve((['LOFT'] if loft_pairs else []) + quads
                                     + (['FACE'] + step if flat else step + ['FACE']))
        else:
            pair = None
            for shape_a, shape_b in combinations(shapes['I'], 2):
                sv_a = get_verts(shape_a[0])
                sv_b = strips_face(sv_a, get_verts(shape_b[0]))
                if sv_b is not None:
                    pair = sv_a + sv_b[::-1]
                    break
            if pair is None:
                # a lone run of three edges on four verts: the strip's own fill first, the quad as the one face
                solve = choose_solve([ 'STEP' if shapes['I'] else 'FILL', 'FACE' ] if quad_option is not None else [])
            elif loop_is_flat([ co_of(v) for v in pair ]):
                solve = choose_solve(['BRIDGE', 'FACE', 'STEP'])
            else:
                solve = choose_solve(['BRIDGE', 'STEP', 'FACE'])
        L.solved_as = solve or ''
        if quad_option is not None and solve == 'FACE':
            sel_quad, shapes = quad_option, { k: [] for k in shapes }    # the quad instead of the strip it lies on

        lofted = set()
        before_lofts = len(L.previz)
        if solve == 'LOFT':
            for ia, ib, axis in loft_pairs:
                before_pair = len(L.previz)
                if not emit_loft(cycles[ia][2], cycles[ib][2], axis):
                    # The stack came in as one fill, so half of it is not an answer: it would preview
                    # as a stack with gaps in it and commit that way. Drop back to the error alone.
                    del L.previz[before_lofts:]
                    lofted.clear()
                    break
                if len(L.previz) > before_pair: lofted |= {ia, ib}

        if len(lofted) < len(cycles) and not (loft_stack and solve == 'LOFT'):
            # A stack of loops was admitted above as one fill of several lofts. Filling whatever the
            # chain did not claim on its own is the expensive path that limit exists to keep shut, and
            # a loop that would not loft with its neighbours is not part of what was asked for anyway.
            # The chosen fill first, then the rest of the ranking. One that cannot build is not the
            # answer -- a patch whose every Solution refused it, a loop round the mouth of a form whose
            # verts are dragged out to the rim rather than onto anything a patch could cover -- and the
            # property follows whatever did build, so the panel never names a fill that is not there.
            filled = stepped = spent = False
            landed = solve
            refused, built_kinds = set(), set()
            for ci, (kind, shape, bmvs) in enumerate(cycles):
                if ci in lofted: continue
                before = len(L.previz)
                # One face over the whole region is a deliberate act, so it is only ever built when it
                # was asked for: falling back to it would cover a patch the checks just refused.
                for want in [solve] + [ k for k in L.solve_ranked if k not in (solve, 'FACE') ]:
                    if want == 'LOFT': continue
                    if want == 'STEP':
                        # not round an n-gon's perimeter, where a ring would leave a smaller hole and no patch
                        if L.ngon_verts is not None: break
                        bmes = cycle_bmes(bmvs)
                        if bmes and not emit_offset(bmvs, bmes, cyclic=True): spent = True
                    elif want == 'FACE':
                        emit_ngon_face(bmvs)
                    else:
                        # An arm of the hole is stepped square before anything else: a fan round a
                        # pole, or a grid split across the loop, covers ground a notched loop does
                        # not enclose. None back means there was no arm to square, or one of the
                        # steps was refused, and the loop is whole again either way.
                        notched = emit_notched(bmvs)
                        if notched is None: notched = emit_cleft(bmvs)
                        if notched is False: spent = True
                        elif notched is None:
                            if kind in ('tri', 'rect', 'ngon'):
                                # by its corners: a rectangle as a grid, anything else round a pole
                                if not emit_ngon(kind, shape): spent = True
                            # no corners to speak of: grid fill
                            elif not emit_grid_fill(bmvs, 'grid'): spent = True
                    if spent or len(L.previz) > before:
                        landed = want
                        built_kinds.add(want)
                        break
                    refused.add(want)       # tried, and it built nothing
                if spent: break
                if len(L.previz) > before:
                    if landed == 'STEP': stepped = True
                    else: filled = True
            # A kind that was tried and built for no loop is not a choice, whatever the ranking said
            # before: listed, the Type property would offer it and the fill snap back to what did build.
            # Where nothing built at all, nothing was solved as anything.
            L.solve_ranked = [ k for k in L.solve_ranked if k not in refused or k in built_kinds ]
            if not (filled or stepped or lofted): L.solved_as = ''
            # only when the whole selection went this way: a stray loop the stack would not loft is
            # not the fill that was asked for, and must not drag the property off the loft
            if landed != solve and L.solve_ranked and not lofted:
                L.solved_as = solve = landed
                L.push_prop('solve', landed, settings.solve)
            if stepped and not filled:
                # the Solutions were ranked before they were tried and none of them built: they are not
                # on offer, so the count knob and the redo panel belong to the step that replaced them
                L.has_grid, L.grid_ranked = False, []

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
            guess_a = bend_along(c10, n10, c00, n00, c11)     # c11 carried the way sv0 bends
            guess_b = bend_along(c10, n10, c11, n11, c00)     # c00 carried the way sv1 bends
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
            fracs_r = cumulative_fracs([sv0[k].co for k in range(l0 - 1, -1, -1)])   # from c11 outward
            fracs_b = cumulative_fracs([v.co for v in sv1])                          # from c00 outward

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
                p1, p2, _ = mirror_curve(p0, t0, p3)
                return ([ bezier(p0, p1, p2, p3, t) for t in fracs ],
                        [ blend_pair(n0, n3, t) for t in fracs ])

            if guide_r is not None:
                pts, ns = side_curve(c11, guide_r, n11, c01, n01, fracs_r)
                side_r = [ new_point(co, side, n, cap) for co, n in zip(pts, ns) ][::-1]   # indexed by i
            else:
                side_r = [ new_point(co, side, n, cap) for (co, n) in
                           arc_between(c01, n01, c11, n11, cumulative_fracs([v.co for v in sv0])) ]
            if guide_b is not None:
                pts, ns = side_curve(c00, guide_b, n00, c01, n01, fracs_b)
                side_b = [ new_point(co, side, n, cap) for co, n in zip(pts, ns) ]          # indexed by j
            else:
                side_b = [ new_point(co, side, n, cap) for (co, n) in
                           arc_between(c00, n00, c01, n01, fracs_b) ]
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
        # C: three strips; the missing side is the middle strip carried across by the end strips. Equal rails
        # take a grid; rails of different counts close into a four-cornered loop and take its solutions

        for shape in shapes['C']:
            s0, s1, s2 = shape
            c0, c1, c2 = map(len, shape)
            sv0, sv1, sv2 = get_verts(s0), get_verts(s1), get_verts(s2, True)
            l0, l1 = len(sv0), len(sv1)
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

            if c0 != c2:
                # no grid runs rail to rail between rails of different counts. The fourth side closes the C
                # into a four-cornered loop, which gets every closed-loop solution the way a bridge does. Its
                # edge count is what those need: the back's plus the step for the turnout leaving through it
                # and the single pole, the back's own for a junction (or, with an odd step, the fills that
                # close an odd loop with a triangle), and the back's less the step for the turnout leaving
                # through the back
                step = abs(c0 - c2)
                side, cap = shape_side(boundary), shape_cap(boundary)
                back = [ v.co for v in sv1 ]
                fracs = cumulative_fracs(back)

                def fourth(n):
                    # the created side, rail B's free end to rail A's in n edges: the back carried along the rails, sampled by length
                    pts = [sv2[0]]
                    for t in range(1, n):
                        u = 1 - t / n           # fraction along the back from rail A's corner
                        k = 0
                        while k < len(back) - 2 and fracs[k + 1] < u: k += 1
                        f = (u - fracs[k]) / max(fracs[k + 1] - fracs[k], 1e-9)
                        co = back[k].lerp(back[k + 1], f) + off0 * (1 - u) + off2 * u
                        pt = new_point(co, side, blend_pair(n00, n01, u), cap)
                        pts.append(to_planes(pt, symmetry0) if use_symmetry else pt)
                    pts.append(sv0[0])
                    return pts

                def closed(n):
                    return [ list(sv0), list(sv1), sv2[::-1], fourth(n) ]

                counts = [ c1 + step, c1 ] if step % 2 else [ c1, c1 + step ]
                if c1 > step: counts.append(c1 - step)
                entries, spent = [], False
                for n in counts:
                    if not budget(n - 1):
                        spent = True
                        break
                    entries += solutions_for('rect', closed(n), rails=(1, 3))
                if spent or not emit_ranked(entries): break
                continue

            if not budget((l0 - 1) * (l1 - 2)): break

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
        before_bridges = len(L.previz)
        for i0, shape0 in enumerate(shapes['I'] if solve != 'STEP' else ()):
            sv0 = get_verts(shape0[0])
            best_sv1, best_dist, best_i1 = None, 0, None
            for i1, shape1 in enumerate(shapes['I']):
                if i1 <= i0: continue
                sv1 = strips_face(sv0, get_verts(shape1[0]))
                if sv1 is None: continue
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
            if solve == 'FACE':
                emit_ngon_face(sv0 + sv1[::-1])
                continue
            avg0 = (sv0[0].co - sv0[-1].co).length / max(1, len(sv0) - 1)
            avg1 = (sv1[0].co - sv1[-1].co).length / max(1, len(sv1) - 1)
            gap = derive_loops(dist, max(avg0, avg1)) + 1    # edges across the gap
            step = abs(len(sv0) - len(sv1))
            # an odd step cannot cross between equal rails: its extra rows turn out through one created
            # rail, which needs an edge per row more than the other and a column on each side of the turn
            if step % 2 and settings.span_insert_mode != 'FIXED': gap = max(gap, 2)
            L.has_bridge = True
            L.loops_last = gap - 1
            boundary = sv0 + sv1

            if step:
                # uneven sides: the two sides this fill creates close the region into a four-cornered
                # loop, and it gets every closed-loop solution: a junction across the gap where the
                # counts are an even step apart, a turnout through the longer created rail where odd,
                # then a grid, a pole with a corner demoted, or cuts
                if not budget(2 * max(0, gap - 1) + (step if step % 2 else 0)): break
                side, cap = shape_side(boundary), shape_cap(boundary)
                nrm = normal_fn(boundary)
                def connect(a, b, n, _side=side, _cap=cap, _nrm=nrm):
                    # interior points of one of the created sides, from a to b, n edges long
                    return [ new_point(a.co * (1 - t / n) + b.co * (t / n), _side,
                                       blend_pair(_nrm(a), _nrm(b), t / n), _cap)
                             for t in range(1, n) ]
                def closed(gap1, gap3):
                    return [ list(sv0), [sv0[-1]] + connect(sv0[-1], sv1[-1], gap1) + [sv1[-1]],
                             list(reversed(sv1)), [sv1[0]] + connect(sv1[0], sv0[0], gap3) + [sv0[0]] ]
                entries = []
                if step % 2:
                    # the longer created rail has the room for the extra edges the turnout and the single pole need
                    longer_first = (sv0[-1].co - sv1[-1].co).length >= (sv1[0].co - sv0[0].co).length
                    entries += solutions_for('rect', closed(gap + step if longer_first else gap, gap if longer_first else gap + step), rails=(1, 3))
                    if not budget(2 * max(0, gap - 1)): break
                # equal rails: the junctions and grids of an even step, or for an odd one the fills that close the
                # odd loop with a triangle or n-gon, which rank behind the quad fills and ahead of the degenerate ones
                entries += solutions_for('rect', closed(gap, gap), rails=(1, 3))
                if not emit_ranked(entries): break
                continue

            # Smooth on a bridge is how smoothly it carries the two surfaces into each other.
            # Each run gets a direction from the faces attached to it, so a bridge off a curved surface
            # follows that curve out.
            if not emit_span('I', sv0, sv1, gap + 1, boundary,
                             bow=run_bows(sv0, sv1), relax=False): break

        # Two separate boundary edges always bridge
        if solve != 'STEP' and len(sel_verts) == 4 and len(shapes['I']) == 2 \
                and len(L.previz) == before_bridges \
                and all(len(shape[0]) == 1 for shape in shapes['I']):
            sv0, sv1 = (get_verts(shape[0]) for shape in shapes['I'])
            # pair the near ends, so the rungs across do not cross
            if ((sv0[0].co - sv1[0].co).length + (sv0[-1].co - sv1[-1].co).length
                    > (sv0[0].co - sv1[-1].co).length + (sv0[-1].co - sv1[0].co).length):
                sv1.reverse()
            ring = sv0 + sv1[::-1]
            if len({ v.index for v in ring }) == 4 and face_is_placeable(bm, ring):
                # counted off the gap exactly as a facing pair is, so Span Insert Mode reads the same
                # either side of the facing test
                dist = min((v0.co - v1.co).length for v0 in sv0 for v1 in sv1)
                avg = max((sv0[0].co - sv0[-1].co).length, (sv1[0].co - sv1[-1].co).length)
                gap = derive_loops(dist, avg) + 1
                L.has_bridge = True
                L.loops_last = gap - 1
                if emit_span('I', sv0, sv1, gap + 1, sv0 + sv1, checks=False,
                             bow=run_bows(sv0, sv1), relax=False):
                    bridged |= {0, 1}

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

        if L.previz or not ctrl_at or L.error: return
        # Two or more selected verts are a selection Blender's own F can act on, so with nothing to
        # fill the key belongs to it, not to a quad guessed from whatever the cursor is near. One
        # stray vert is not enough for Blender's F, so the pick still runs there.
        if len(sel_verts) >= 2: return
        key = L._candidate_key(context)
        if key is None: return
        if key != L.cand_key: L._collect_candidates(bm, key)
        L.nearest_active = True     # on from here whatever is offered: track_mouse re-picks per move only while this is set
        offer = L.pick_offer(context, bm, M, mouse_at)
        L.offer = offer
        if offer is None: return
        if offer[0] == 'q':
            emit_quad_strip([ bm.verts[i] for i in offer[1] ], 'nearest')
        elif offer[0] == 'e':
            v0, v1 = bm.verts[offer[1]], bm.verts[offer[2]]
            bme = bmvs_shared_bme(v0, v1)
            if bme is not None: emit_offset([v0, v1], [bme])
        else:
            emit_corner_quad(bm.verts[offer[1]], pair=(bm.verts[offer[2]], bm.verts[offer[3]]))
        src = offer_key(offer)
        for pv in L.previz:
            pv.hover = True
            pv.face_src = tuple(src for _ in pv.faces)   # a drag starting here needs to know these faces are the offer's

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
            L.offer = None
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

        if L.stroke is not None:
            # a stroke previews itself, and a change in what the cursor asks for is a rebuild
            if L.cand_key is None or L.cand_key != L._candidate_key(context):
                L.dirty = True
                return True
            try:
                bm = bmesh.from_edit_mesh(context.edit_object.data)
                bm.verts.ensure_lookup_table()
                offer = L.pick_offer(context, bm, M, L.mouse)
            except (ReferenceError, RuntimeError):
                offer = None
            if offer_key(offer) == offer_key(L.offer): return False
            L.offer = offer
            L.dirty = True
            return True

        if (L.ctrl or L.ctrl_forced) and L.nearest_active and L.cand_key is not None and L.cand_key == L._candidate_key(context):
            # Re-pick per move: the candidates are already projected and nothing here snaps a vert.
            # Only a change of offer costs a rebuild, which is what snaps what it shows; a mesh edit
            # fails the key test above and the next update() rebuilds.
            try:
                bm = bmesh.from_edit_mesh(context.edit_object.data)
                bm.verts.ensure_lookup_table()
                offer = L.pick_offer(context, bm, M, L.mouse)
            except (ReferenceError, RuntimeError):
                offer = None
            if offer_key(offer) != offer_key(L.offer):
                L.offer = offer
                L.dirty = True
                return True
            # an extend preview is showing: a wire edge among them still follows the cursor's side below

        if not L.wire_runs: return False
        mouse = Vector(mouse_from_event(event))
        for co_a, co_b, sign in L.wire_runs:
            pa, pb = location_3d_to_region_2d(rgn, r3d, M @ co_a), location_3d_to_region_2d(rgn, r3d, M @ co_b)
            if not pa or not pb: continue
            s = side2d(pa, pb, mouse)
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
        view, cached against proj_key; only the few nearest candidates of a pick are ever asked.
        Outside Retopoflow there is no source to be behind, so everything is visible. '''
        L = LegacyPatches_Logic
        if not rf_is_running(): return True
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
        REACH_3D = 2.0      # every corner within this many mean sides of the surface point under the cursor: any quad the
                            # shape test passes keeps its corners under 1.7 mean sides from every point inside it, and at 1.0
                            # a good quad failed near its own sides, leaving a larger, skewed one reaching over the cursor
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
            r = quad_from_points([pts2d[i] for i in combo], [cos3d[i] for i in combo], mouse)
            if r is None: continue
            order, score = r
            ranked.append((score, tuple(combo[o] for o in order)))
        if not ranked: return None
        ranked.sort(key=lambda e: e[0])

        # the surface point under the cursor anchors the 3D check; off the source, and outside
        # Retopoflow where there is none, the screen tests stand alone
        anchor = raycast_point_valid_sources(context, mouse) if rf_is_running() else None

        for score, quad in ranked:
            verts = [bmvs[i] for i in quad]
            if score[0] == 1:
                if strict: break
            elif bm.faces.get(verts):
                # the cursor is inside an existing face; what is left in the running are wide quads
                # reached through the outline slop from the cell next door, so offer nothing
                return None
            if not face_is_placeable(bm, verts): continue
            if anchor is not None:
                q = [cos3d[i] for i in quad]
                mean_side = sum((q[(i + 1) % 4] - q[i]).length for i in range(4)) / 4
                if any((c - anchor).length > REACH_3D * mean_side for c in q): continue
            edges_out = [ (i, (i + 1) % 4) for i in range(4)
                          if bmvs_shared_bme(verts[i], verts[(i + 1) % 4]) is None ]
            # a stroke's own quads are not in the mesh, so face_is_placeable cannot see them; the stroke can
            if L.stroke is not None and not L.stroke.allows_quad(bm, [ v.index for v in verts ], score[1]): continue
            return Previz(
                'nearest',
                [ v.index for v in verts ],
                [ v.co.copy() for v in verts ],
                edges_out,
                [(0, 1, 2, 3)],
                (),
                (),
                hover=True,
                cost=score[1],
            )
        return None

    @staticmethod
    def pick_nearest_extend(context : Context, bm, M : Matrix, mouse_win, *, footprint : bool = False) -> tuple | None:
        ''' What the cursor would extend when it is in no quad: ('vert', bmv) for a boundary corner
        near it, else ('edge', bme) for a nearby open edge, else None. The vert wins when in range: it
        is the smaller target and always the end of some edge that would otherwise win. With
        `footprint` the cursor has to be inside what the extend would make, more or less: a stroke
        takes what it runs through, so offering a step from forty pixels off shows the next face a
        whole face early. '''
        VERT_PX, EDGE_PX = 15, 40   # ui-scaled pick radii, for hovering
        FOOT_DEPTH = 1.25           # footprint: how far out from an edge, in its own screen length, a step is taken to reach
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
            return side2d(pa, pb, mouse_v) != side2d(pa, pb, pf)

        anchor = raycast_point_valid_sources(context, mouse_v) if rf_is_running() else None

        def within_reach(bmv, scale):
            # a far element that is close only on screen is not what the cursor is beside
            return anchor is None or (M @ bmv.co - anchor).length <= REACH_3D * scale

        try:
            d2 = np.nansum((px - mouse) ** 2, axis=1)
            d2 = np.where(np.isnan(px[:, 0]), np.inf, d2)
            if L.cand_open is not None:
                # a corner: two or more open edges meet there. Not while the cursor is over one of its faces.
                corner_d2 = np.where(L.cand_open >= 2, d2, np.inf)
                vert_radius = np.inf if footprint else (Drawing.scale(VERT_PX) or VERT_PX)
                for k in np.argsort(corner_d2)[:4]:
                    if not np.isfinite(corner_d2[k]) or corner_d2[k] > vert_radius * vert_radius: break
                    bmv = resolve(k)
                    if bmv is None: continue
                    if L.stroke is not None and (bmv.index in L.stroke.corners or any(
                            L.stroke.spoken_for(bmv.index, e.other_vert(bmv).index, by_faces_only=True) for e in bmv.link_edges)):
                        continue    # the stroke has closed this corner, or a quad of its already sits on one of its edges
                    if footprint:
                        # inside the notch quad it would close, on screen
                        pair = corner_pairing(bmv, mouse_v, rgn, r3d, M)
                        if pair is None: continue
                        va, vb = pair
                        co4 = va.co + vb.co - bmv.co
                        pts = [ location_3d_to_region_2d(rgn, r3d, M @ co) for co in (va.co, bmv.co, vb.co, co4) ]
                        if not (all(pts) and point_inside_face_2d(mouse_v, pts)): continue
                        # the test take() applies: a notch that cannot sit beside what the stroke holds is not shown
                        if L.stroke is not None:
                            quads, blocked = L.stroke.clashes([va.index, bmv.index, vb.index, None], [va.co, bmv.co, vb.co, co4])
                            if quads or blocked: continue
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
            t_raw = ((mouse - A) * AB).sum(axis=1) / ab2
            if footprint:
                # between the edge's ends and no further out than its step reaches: the cursor is in the
                # face the step would make. Ranked by how far out it is, nearest edge first.
                ablen = np.sqrt(ab2)
                perp = np.abs(AB[:, 0] * (mouse[1] - A[:, 1]) - AB[:, 1] * (mouse[0] - A[:, 0])) / ablen
                edge_d2 = np.where((t_raw >= 0.0) & (t_raw <= 1.0) & (perp <= FOOT_DEPTH * ablen), perp ** 2, np.inf)
            else:
                t = np.clip(t_raw, 0.0, 1.0)
                edge_d2 = ((A + AB * t[:, None] - mouse) ** 2).sum(axis=1)
            edge_d2 = np.where(np.isnan(edge_d2), np.inf, edge_d2)
            edge_radius = np.inf if footprint else (Drawing.scale(EDGE_PX) or EDGE_PX)
            for k in np.argsort(edge_d2)[:4]:
                if not np.isfinite(edge_d2[k]) or edge_d2[k] > edge_radius * edge_radius: break
                va, vb = resolve(L.cand_edges[k, 0]), resolve(L.cand_edges[k, 1])
                if va is None or vb is None: continue
                bme = bmvs_shared_bme(va, vb)
                if bme is None or bme.hide or len(bme.link_faces) >= 2: continue
                if L.stroke is not None and L.stroke.spoken_for(va.index, vb.index): continue
                elen = (M @ va.co - M @ vb.co).length
                if not (within_reach(va, elen) and within_reach(vb, elen)): continue
                if not on_open_side(bme, Vector((A[k][0], A[k][1])), Vector((B[k][0], B[k][1]))): continue
                return ('edge', bme)
            return None
        except ReferenceError:
            return None

    @staticmethod
    def pick_offer(context : Context, bm, M : Matrix, mouse_win, *, strict : bool = False):
        ''' What the cursor asks for: ('q', indices in ring order, cost) for a quad over existing verts,
        ('e', ia, ib) to step an open edge, ('c', C, va, vb) to close a notch at a corner vert; None for
        nothing. A quad wins over an extend; `strict` wants the cursor inside a quad and offers no extend. '''
        L = LegacyPatches_Logic
        # hovering may reach a little outside what it offers, so a click has something to hit, but a stroke takes what
        # it runs through, and reaching ahead of it showed the next face early: a stroke is offered only the quad the
        # cursor is inside or the extend whose footprint it is in, and the picks pass over what it holds or cannot sit beside
        drawing = L.stroke is not None
        pv = L.pick_nearest_quad(context, bm, M, mouse_win, strict=strict or drawing)
        if pv is not None: return ('q', tuple(pv.vert_idx), pv.cost)
        if strict: return None
        hit = L.pick_nearest_extend(context, bm, M, mouse_win, footprint=drawing)
        if hit is None: return None
        kind, elem = hit
        if kind == 'edge':
            v0, v1 = elem.verts
            return ('e', v0.index, v1.index)
        rgn, r3d = context.region, context.region_data
        mouse = Vector((mouse_win[0] - rgn.x, mouse_win[1] - rgn.y)) if (rgn and r3d) else None
        pair = corner_pairing(elem, mouse, rgn, r3d, M)
        return ('c', elem.index, pair[0].index, pair[1].index) if pair else None

    @staticmethod
    def _selected_quad(bm, sel_verts, rgn, r3d, M : Matrix, *, fit : bool = True) -> list | None:
        ''' Four selected verts as one quad in ring order, when they make a legal one. Ordered on
        screen when there is a view, else in the plane the four roughly lie in. `fit` tests if it's
        a good looking quad or not. '''
        MIN_SIDE = 1e-9         # a side this short is a double, and the quad on it a broken face
        MIN_AREA = 1e-12        # four verts along a straight boundary name no face, only a sliver
        pts = [ location_3d_to_region_2d(rgn, r3d, M @ v.co) for v in sel_verts ] if (rgn and r3d) else [None] * 4
        if all(pts):
            c = sum(pts, Vector((0, 0))) / 4
            order = sorted(range(4), key=lambda k: math.atan2(pts[k].y - c.y, pts[k].x - c.x))
            if fit and not is_convex_2d([pts[k] for k in order]): return None
        else:
            cos = [ v.co for v in sel_verts ]
            c = sum(cos, Vector()) / 4
            # the best-conditioned of the four triangles. Summing them instead cancels to zero
            # whenever the two diagonal pairs are adjacent in the order the verts were read in,
            # which has nothing to do with the shape
            n = max(((cos[a] - cos[d]).cross(cos[b] - cos[d])
                     for a, b in combinations(range(4), 2)
                     for d in range(4) if d not in (a, b)),
                    key=lambda v: v.length_squared)
            if n.length_squared < 1e-18: return None
            n = n.normalized()
            frame = plane_frame(n, cos[0] - c)
            if frame is None: return None
            u, w = frame
            order = sorted(range(4), key=lambda k: math.atan2((cos[k] - c).dot(w), (cos[k] - c).dot(u)))
        verts = [ sel_verts[k] for k in order ]
        ring = [ M @ v.co for v in verts ]
        if fit and quad_squareness(ring) is None: return None
        if not fit and (min((ring[(k + 1) % 4] - ring[k]).length for k in range(4)) < MIN_SIDE
                        or sum(((ring[k] - ring[0]).cross(ring[k + 1] - ring[0])).length
                               for k in (1, 2)) / 2 < MIN_AREA): return None
        if not face_is_placeable(bm, verts): return None
        return verts

    @staticmethod
    def _selected_tri(bm, sel_verts, M : Matrix) -> list | None:
        ''' Three selected verts as one triangle, when they make a real one and the mesh has room for
        it. No ordering to work out: every pair of a triangle's corners is a side of it. '''
        if not tri_shape_ok([ M @ v.co for v in sel_verts ]): return None
        if not face_is_placeable(bm, sel_verts): return None
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
    def pick_selected_vert(context : Context, event : Event, *, radius2d : float = CORNER_PICK_PX) -> int | None:
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
    def selection_is_face_patch(context : Context) -> bool:
        ''' Two or more selected faces with nothing selected beyond them: what F joins into one n-gon
        rather than fills. '''
        if not context.edit_object or context.mode != 'EDIT_MESH': return False
        bm, _ = get_bmesh_emesh(context)
        faces = [ f for f in bmops.get_all_selected_bmfaces(bm) if not f.hide ]
        if len(faces) < 2: return False
        if not all(any(f.select for f in e.link_faces) for e in bmops.get_all_selected_bmedges(bm) if not e.hide): return False
        return all(any(f.select for f in v.link_faces) for v in bm.verts if v.select and not v.hide)

    @staticmethod
    def pick_pole_handle(context : Context) -> tuple | None:
        ''' The loop key of the pole handle under the cursor, if any. '''
        L = LegacyPatches_Logic
        edit_object = context.edit_object
        if not edit_object or not L.pole_handles or L.mouse is None: return None
        rgn, r3d = context.region, context.region_data
        if not rgn or not r3d: return None
        M = edit_object.matrix_world
        mouse = Vector((L.mouse[0] - rgn.x, L.mouse[1] - rgn.y))
        best, best_d = None, (Drawing.scale(POLE_PICK_PX) or POLE_PICK_PX) ** 2
        for co, key in L.pole_handles:
            p = location_3d_to_region_2d(rgn, r3d, M @ co)
            if not p: continue
            d = (p - mouse).length_squared
            if d < best_d: best, best_d = key, d
        return best

    @staticmethod
    def start_pole_drag(context : Context, key : tuple):
        L = LegacyPatches_Logic
        L.pole_drag_prev = L.pole_pos.get(key)
        at = next((co for co, k in L.pole_handles if k == key), None)
        L.pole_drag = (key, at.copy() if at is not None else None)
        L.dirty = True

    @staticmethod
    def move_pole_drag(context : Context, event : Event):
        ''' The dragged pole follows the cursor over the source, or at its own depth when nothing is under it. '''
        L = LegacyPatches_Logic
        if L.pole_drag is None or not context.edit_object: return
        L.mouse = (event.mouse_x, event.mouse_y)
        key, prev = L.pole_drag
        M = context.edit_object.matrix_world
        xy = Vector(mouse_from_event(event))
        world = raycast_point_valid_sources(context, xy)
        if world is None:
            anchor = prev if prev is not None else next((co for co, k in L.pole_handles if k == key), None)
            if anchor is None: return
            world = region_2d_to_location_3d_stable(context.region, context.region_data, xy, M @ anchor)
            if world is None: return
        L.pole_drag = (key, M.inverted_safe() @ Vector(world))
        L.dirty = True

    @staticmethod
    def end_pole_drag(context : Context, *, cancel : bool = False):
        L = LegacyPatches_Logic
        if L.pole_drag is None: return
        key = L.pole_drag[0]
        if cancel:
            if L.pole_drag_prev is None: L.pole_pos.pop(key, None)
            else: L.pole_pos[key] = L.pole_drag_prev
        L.pole_drag = L.pole_drag_prev = None
        L.dirty = True

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
        ''' Forget every toggled corner and every placed pole: True when there was anything to forget. '''
        L = LegacyPatches_Logic
        try:
            if not context.edit_object or context.mode != 'EDIT_MESH': return False
            cleared = bool(L.pole_pos) or L.pole_drag is not None
            L.pole_pos = {}
            L.pole_drag = L.pole_drag_prev = None
            bm, em = get_bmesh_emesh(context)
            if bm.verts.layers.int.get(CORNER_LAYER) is not None:
                BMVertLayer_Int.remove(bm, CORNER_LAYER)
                bmesh.update_edit_mesh(em)
                cleared = True
            if cleared: L.dirty = True
            return cleared
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
            L.error = 'Patches: the mesh changed under the fill; try again'
            return False
        if not L.previz: return False    # L.error may say why, else there was nothing to offer
        # the rebuild after a fill previews nothing, so the redo panel and the scroll shortcuts read these
        L.filled_flags = (L.has_bridge, L.has_grid, L.has_loft, L.has_offset, L.has_quad)
        L.filled_free_step = L.has_free_step
        L.filled_smoothing = L.has_smoothing
        L.filled_offsets = L.offsets
        L.filled_solve_ranked = list(L.solve_ranked)
        L.filled_loops = L.loops_last or 0
        L.filled_solutions = max(1, len(L.grid_ranked))

        if not L._build(context, L.previz):
            L.error = L.error or 'Patches: the preview no longer matched the mesh; try again'
            return False
        return True

    @staticmethod
    def fill_contextual(context : Context) -> bool:
        ''' What Blender's own F makes of a selection. False when there is nothing to make. '''
        L = LegacyPatches_Logic
        if not context.edit_object or context.mode != 'EDIT_MESH': return False
        bm, em = get_bmesh_emesh(context)
        sel_bmfs = [ f for f in bm.faces if f.select and not f.hide ]
        geom = ([ v for v in bm.verts if v.select and not v.hide ]
                + [ e for e in bm.edges if e.select and not e.hide ]
                + sel_bmfs)
        if not geom: return False
        # the material and shading a new face takes are its neighbours', as Blender's are
        smooth = any(f.smooth for e in bm.edges if e.select for f in e.link_faces)
        try:
            made = bmesh.ops.contextual_create(bm, geom=geom, mat_nr=context.edit_object.active_material_index, use_smooth=smooth)
        except (RuntimeError, ValueError):
            return False
        # a lone selected face comes back as though made: it is not ours to rewind or reselect
        was = set(sel_bmfs)
        new_bmfs, new_bmes = [ f for f in made['faces'] if f not in was ], made['edges']
        if not new_bmfs and not new_bmes: return False
        for bmf in new_bmfs: bmf.normal_update()
        if rf_is_running():
            orient_bmf_normals(context, new_bmfs, new_faces=True)
        else:
            unsettled = wind_bmfs_to_match_neighbors(new_bmfs)
            if unsettled: check_bmf_normals(unsettled)
        bmops.deselect_all(bm)
        bmops.select_iter(bm, new_bmes)
        bmops.select_iter(bm, new_bmfs)
        BMVertLayer_Int.remove(bm, CORNER_LAYER)
        bmops.flush_selection(bm, em)
        # nothing of a patch's to redo: the panel shows the Split Angle alone, and lowering it may find
        # the corners that make this selection a patch after all
        L.filled_flags = (False, False, False, False, False)
        L.filled_free_step = L.filled_smoothing = False
        L.filled_offsets = 1
        L.filled_solve_ranked = L.solve_ranked = []
        L.solved_as = ''
        L.filled_loops, L.filled_solutions = 0, 1
        L.filled_sig = None
        L.offer = None
        L.dirty = True
        return True

    @staticmethod
    def _build(context : Context, previz : list) -> bool:
        ''' Turn a list of previews into real geometry. '''
        L = LegacyPatches_Logic
        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        Mi_build = context.edit_object.matrix_world.inverted_safe()
        nverts = len(bm.verts)

        # resolve every existing vert before creating any, since verts.new() dirties the lookup table
        existing = []
        for pv in previz:
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

        # the band the loft re-solves goes first, so its loops are bare for the loft to build on
        if L.replaced_band[0]:
            if max(i for idxs in L.replaced_band[0] for i in idxs) >= nverts \
                    or delete_band(bm, L.replaced_band) is False:
                L.dirty = True      # stale preview; the next frame rebuilds it
                return False

        # a lone n-gon goes first, and only the face: its edges stay for the patch to build on
        if L.ngon_verts is not None:
            ngon = bm.faces.get([ bm.verts[i] for i in L.ngon_verts ]) if max(L.ngon_verts) < nverts else None
            if ngon is None or not ngon.select:
                L.dirty = True      # stale preview; the next frame rebuilds it
                return False
            bmesh.ops.delete(bm, geom=[ngon], context='FACES_ONLY')

        new_bmvs, new_bmfs, built = [], [], []
        for pv, row in zip(previz, existing):
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
        for bmf in new_bmfs: bmf.normal_update()
        if rf_is_running():
            orient_bmf_normals(context, new_bmfs, new_faces=True)
        else:
            # a wire run steps out with nothing attached to agree with, so what is left over faces outwards
            unsettled = wind_bmfs_to_match_neighbors(new_bmfs)
            if unsettled: check_bmf_normals(unsettled)

        stepped = [ (pv, bmvs) for pv, bmvs in zip(previz, built) if pv.kind == 'offset' ]
        cornered = [ (pv, bmvs) for pv, bmvs in zip(previz, built) if pv.kind == 'corner' ]
        hovered = all(pv.hover for pv in previz)
        bmops.deselect_all(bm)
        if hovered:
            pass    # a cursor pick was built from nothing selected, and the next one is picked the same way
        elif stepped:
            # only the new row stays selected, so the next rebuild offers the step after it and F walks outward
            for pv, bmvs in stepped:
                bmops.select_iter(bm, [ bmvs[k] for k in pv.row_idx ])
        elif cornered:
            # F2's quad off a vert: only the two sides it created stay selected. The vert it was built
            # from is let go, so what is left reads as the next corner rather than the one just filled.
            for pv, bmvs in cornered:
                bmops.select_iter(bm, [ bmvs_shared_bme(bmvs[a], bmvs[b]) for a, b in pv.edges ])
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
        L.offer = None
        L.dirty = True
        return True

    ##############################################
    # Ctrl+LMB drag: collect what the cursor passes over, build it all when the stroke ends

    @staticmethod
    def offer_faces(context : Context, key) -> list:
        ''' The previewed faces that came from the offer with this key, as (indices, positions). '''
        L = LegacyPatches_Logic
        if key is None: return []
        return [ ([ pv.vert_idx[i] for i in f ], [ pv.vert_co[i] for i in f ])
                 for pv in L.previz for f, src in zip(pv.faces, pv.face_src) if src == key ]

    @staticmethod
    def _polys_2d(context : Context, faces : list) -> list:
        ''' Faces as screen-space outlines; one with a corner off screen is left out. '''
        edit_object = context.edit_object
        rgn, r3d = context.region, context.region_data
        if not edit_object or not rgn or not r3d: return []
        M = edit_object.matrix_world
        polys = []
        for _idx, cos in faces:
            pts = [ location_3d_to_region_2d(rgn, r3d, M @ co) for co in cos ]
            if all(pts): polys.append(pts)
        return polys

    @staticmethod
    def _run_inside(context : Context, p0, p1, polys2d) -> float:
        ''' How many pixels of a stroke segment lay inside some projected outlines. Sampled rather
        than intersected: a stroke through a corner cuts two sides at the same place, and counting
        those crossings puts the answer out by a whole side. '''
        rgn = context.region
        if not rgn or not polys2d: return 0.0
        a = Vector((p0[0] - rgn.x, p0[1] - rgn.y))
        b = Vector((p1[0] - rgn.x, p1[1] - rgn.y))
        span = (b - a).length
        if span < 0.5: return 0.0
        n_s = max(2, min(64, int(span / 2.0)))
        hits = sum(1 for k in range(n_s + 1)
                   if any(point_inside_face_2d(a + (b - a) * (k / n_s), poly) for poly in polys2d))
        return span * hits / (n_s + 1)

    @staticmethod
    def stroke_take(context : Context, offer, faces : list) -> bool:
        ''' Add an offer to the stroke. True when the stroke changed, which means a rebuild. '''
        L = LegacyPatches_Logic
        if L.stroke is None or offer is None: return False
        try:
            bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)
            if not L.stroke.take(bm, offer, faces): return False
        except ReferenceError:
            return False
        L.stroke.runs.pop(offer_key(offer), None)
        L.offer = None
        L.dirty = True
        return True

    @staticmethod
    def selected_step_edges(context : Context) -> list:
        ''' The selection as a stroke would hold it: its open edges, by vert index pair. Only meaningful
        when the selection previews a step, which is the one selection preview a stroke can carry on. '''
        L = LegacyPatches_Logic
        if not L.has_offset or L.has_grid or L.has_bridge or L.has_loft or L.has_quad: return []
        try:
            bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)
            return [ frozenset(v.index for v in bme.verts)
                     for bme in bmops.get_all_selected_bmedges(bm) if len(bme.link_faces) < 2 and not bme.hide ]
        except ReferenceError:
            return []

    @staticmethod
    def drag_start(context : Context, pt, offer, faces : list, edges : list = ()) -> bool:
        ''' The press has become a drag: from here the preview is the stroke's. A press that landed on
        what was offered takes it outright; one that landed on a selection's step preview takes those
        edges. True when the stroke starts with something in it. '''
        L = LegacyPatches_Logic
        L.stroke = Stroke()
        L.stroke.prev = (int(pt[0]), int(pt[1]))
        L.dirty = True
        if offer is None and not edges: return False
        rgn = context.region
        m = Vector((pt[0] - rgn.x, pt[1] - rgn.y)) if rgn else None
        on_it = m is not None and any(point_inside_face_2d(m, poly) for poly in L._polys_2d(context, faces))
        if not (on_it or L.mouse_over_previz(context)): return False
        if offer is not None: return L.stroke_take(context, offer, faces)
        L.stroke.edges.update(edges)
        return True

    @staticmethod
    def drag_step(context : Context, pt, offer, faces : list) -> bool:
        ''' One sample of the stroke against the offer showing there. Each sample adds the part of the
        stroke that ran inside the offer's faces to that offer's running total, and the offer is taken
        once its total passes the margin: drawing through a face reaches it almost at once, brushing a
        corner never does. Totals are kept per offer, so the pick flicking between an offer and nothing,
        or between two offers, loses no ground. True when the offer was taken. '''
        CORNER_MARGIN = 5.0     # px of stroke inside the offer; below this it only clipped a corner
        L = LegacyPatches_Logic
        stroke = L.stroke
        if stroke is None: return False
        pt = (int(pt[0]), int(pt[1]))
        prev, stroke.prev = stroke.prev, pt
        if offer is None or prev is None: return False
        key = offer_key(offer)
        if stroke.has(key): return False
        run = stroke.runs.get(key, 0.0) + L._run_inside(context, prev, pt, L._polys_2d(context, faces))
        stroke.runs[key] = run
        if run < CORNER_MARGIN: return False
        return L.stroke_take(context, offer, faces)

    @staticmethod
    def accept_along(context : Context, p0, p1) -> int:
        ''' Sample the cursor's path between two drag positions so a fast sweep skips no cell, and put
        each sample through drag_step. Only quads over existing verts are picked here: their outline
        needs no rebuild. An edge or a notch is judged at the event position, where the rebuild has
        drawn what it would make. Returns how many offers were taken. '''
        SAMPLE_PX = 6
        L = LegacyPatches_Logic
        edit_object = context.edit_object
        if not edit_object or L.stroke is None: return 0
        M = edit_object.matrix_world
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        steps = max(1, int(math.hypot(dx, dy) // SAMPLE_PX))
        made = 0
        for s in range(1, steps):
            pt = (p0[0] + dx * s / steps, p0[1] + dy * s / steps)
            try:
                key = L._candidate_key(context)
                if key is None: return made
                bm = bmesh.from_edit_mesh(edit_object.data)
                bm.verts.ensure_lookup_table()
                if key != L.cand_key or L.cand_cos is None: L._collect_candidates(bm, key)
                pv = L.pick_nearest_quad(context, bm, M, pt, strict=True)
            except (ReferenceError, RuntimeError):
                return made
            offer = ('q', tuple(pv.vert_idx), pv.cost) if pv is not None else None
            faces = [ (list(pv.vert_idx), list(pv.vert_co)) ] if pv is not None else []
            if L.drag_step(context, pt, offer, faces): made += 1
        return made

    @staticmethod
    def commit_stroke(context : Context) -> bool:
        ''' Build everything the stroke collected as one patch. The rebuild with nothing on offer is
        exactly what gets made, so what was drawn is what appears. '''
        L = LegacyPatches_Logic
        stroke = L.stroke
        if stroke is None: return False
        made = False
        try:
            if not stroke.is_empty():
                L._recompute(context, L.read_settings(context), live=True, stroke_offer=None)
                made = bool(L.previz) and L._build(context, L.previz)
        except ReferenceError:
            made = False
        finally:
            L.stroke = None
        L.offer = None
        L.cand_key = None
        L.filled_sig = None
        L.dirty = True
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
        color_open    = Color4((1.0, 1.0, 0.0, 1.0))    # the corner control points' yellow (legacy_patches.PATCH_CORNER_COLOR)
        color_mesh    = theme.face_select
        color_mark    = Color4((1.0, 1.0, 0.0, max(0.4, color_mesh[3])))    # the one non-quad an odd loop is closed with
        from ..rfoverlays.curve_overlay import KNOT_RADIUS
        OPEN_VERT_RADIUS = KNOT_RADIUS / 2    # a vert a fill will create: plainly smaller than a corner control point
        color_label   = (1, 1, 0, 1)
        color_shadow  = (0, 0, 0, 0.75)

        try:
            open_pts = []
            for pv in L.previz:
                pts = [proj(co) for co in pv.vert_co]

                marked = set(pv.mark)
                for color, which in ((color_mesh, [ f for i, f in enumerate(pv.faces) if i not in marked ]),
                                     (color_mark, [ pv.faces[i] for i in pv.mark if i < len(pv.faces) ])):
                    if not which: continue
                    with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                        draw.color(color)
                        for f in which:
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

                open_pts += [ p for k in pv.open_idx if (p := pts[k]) ]

            if open_pts:
                # the verts a fill creates on its own boundary, a bridge's rails: small discs in the corners' yellow,
                # no border, after every fill so no face colour lies over them
                Drawing.draw2D_points(context, open_pts, color_open, radius=OPEN_VERT_RADIUS)

            if len(L.drag_path) > 1:
                Drawing.draw2D_linestrip(context, [ Vector((x - rgn.x, y - rgn.y)) for x, y in smooth_path(L.drag_path) ],
                                         (1, 1, 0, 1), width=2, stipple=[5, 5])

            # the corners themselves are drawn by the curve overlay, as the control points they are

            if L.pole_handles:
                # the same mark as a curve's Automatic control point: this too is a point the artist may drag
                from ..rfoverlays.curve_overlay import KNOT_BORDER_COLOR, AUTO_KNOT_FILL_COLOR
                pts2d = [ p for co, _ in L.pole_handles if (p := proj(co)) ]
                if pts2d:
                    Drawing.draw2D_points(context, pts2d, AUTO_KNOT_FILL_COLOR, radius=KNOT_RADIUS, border=2, borderColor=KNOT_BORDER_COLOR)

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
            if L.hint:
                x = rgn.width / 2 - Drawing.get_text_width(L.hint) / 2
                Drawing.text_draw2D(L.hint, (x, rgn.height - (80 if L.error else 60)), color=(0.9, 0.9, 0.9, 1), dropshadow=color_shadow)
        except ReferenceError:
            pass


class DrawGesture:
    ''' The LMB gesture shared by Ctrl held (RFOperator_LegacyPatches_Draw) and F held from another
    tool (the quick switch): a click fills the previewed patch or toggles a corner, a drag draws a
    path and collects whatever the cursor passes over into one stroke, built when it ends. The owner
    says which modifier state may start a press; once pressed, the rest of the gesture is handled
    here whatever the modifiers do. '''

    def __init__(self):
        self.pressed = self.dragging = False
        self.press_xy = self.prev_xy = (0, 0)
        self.press_offer = None     # what was on offer under the press; taken outright if this becomes a drag
        self.press_faces = []       # its previewed faces, for telling whether the press landed on it
        self.press_edges = []       # or, with nothing on offer, the open edges of the selection whose step was previewed
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
                self.press_offer = L.offer
                if L.offer is not None:
                    self.press_faces, self.press_edges = L.offer_faces(context, offer_key(L.offer)), []
                else:
                    # a selection's own preview: a drag from it carries the selection's step into the stroke
                    self.press_edges = L.selected_step_edges(context)
                    self.press_faces = [ ([ pv.vert_idx[i] for i in f ], [ pv.vert_co[i] for i in f ])
                                         for pv in L.previz for f in pv.faces ] if self.press_edges else []
                L.drag_path = [mouse]
                L.stroke = None
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
                    L.drag_start(context, self.press_xy, self.press_offer, self.press_faces, self.press_edges)
                    if L.dirty: L.update(context)
            if self.dragging:
                L.accept_along(context, self.prev_xy, mouse)
                if L.dirty: L.update(context)     # a take along the way changes what is on offer at the end
                L.drag_step(context, mouse, L.offer, L.offer_faces(context, offer_key(L.offer)))
                if L.dirty: L.update(context)
            self.prev_xy = mouse
            if context.area: context.area.tag_redraw()
            return {'PASS_THROUGH'}

        return None

    def finish(self, context : Context):
        ''' The owner is ending: close any drag in progress and clear the drawn path. '''
        if self.dragging: self._end_drag(context)
        self.pressed = False
        LegacyPatches_Logic.drag_path = []
        LegacyPatches_Logic.stroke = None

    def _click(self, context : Context, event : Event):
        # a selected boundary vert under the cursor is a corner to toggle; otherwise the click confirms
        # whatever is previewed, wherever it lands. Both go through operators so each is one undo step
        L = LegacyPatches_Logic
        if L.pick_selected_vert(context, event) is not None:
            _ = bpy_ops_retopoflow('legacy_patches_toggle_corner', 'INVOKE_DEFAULT', True)
        elif L.previz:
            _ = bpy_ops_retopoflow('legacy_patches_fill', 'INVOKE_DEFAULT', True)

    def _end_drag(self, context : Context):
        L = LegacyPatches_Logic
        self.dragging = False
        # nothing reached the mesh while the stroke was down: build the lot now, as one undo step
        if L.commit_stroke(context):
            try:
                bpy.ops.ed.undo_push(message='Patches: draw quads')
            except RuntimeError:
                pass
        if context.area: context.area.tag_redraw()
