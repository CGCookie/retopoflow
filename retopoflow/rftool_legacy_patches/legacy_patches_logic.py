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

# Legacy Patches: a port of the RetopoFlow 3 Patches tool.
# The algorithm (boundary strip detection, I/L/C/rect classification, grid fill) is the v3
# one, kept as close to the original as possible so it behaves the way users remember.
# Only the plumbing is v4: bmesh access, source snapping, mirror handling, drawing.
# The new v4 Patches tool lives in rftool_patches/ and is unrelated to this file.

# pyright: reportUnannotatedClassAttribute = false

import math
from dataclasses import dataclass, replace
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
from ..common.bmesh import get_bmesh_emesh, BMVertLayer_Int, mirror_threshold, is_bmvert_corner
from ..common.bpy_helper import bpy_ops_retopoflow
from ...addon_common.common.blender_preferences import mouse_drag
from ..common.bmesh_maths import orient_bmf_normals, fit_plane_of_verts, compute_n
from ..common.drawing import Drawing, CC_2D_LINES, CC_2D_POINTS, CC_2D_TRIANGLES
from ..common.operator import RFOperator
from ..common.raycast import (
    nearest_point_valid_sources, nearest_point_normal_valid_sources, raycast_ray_valid_sources,
    iter_all_valid_sources, mouse_from_event, is_point_occluded, raycast_point_valid_sources,
)
from ..common.segments import active_mirror_axes, pin_to_mirror_planes


MAIN_OP_IDNAME = 'retopoflow.legacy_patches'

# per-vert int layer holding the user's corner overrides (v3 kept these in a dict keyed by BMVert,
# which dies on every depsgraph update; a layer rides along with the mesh and with undo)
CORNER_LAYER = 'rf_legacy_patches_corner'
CORNER_AUTO, CORNER_FORCED, CORNER_SMOOTH = 0, 1, 2

DEFAULT_SPLIT_ANGLE = math.radians(60)   # how far a boundary must bend at a vert to make it a corner
DEFAULT_SMOOTH = 0
DEFAULT_SPAN_MODE = 'AVERAGE'
DEFAULT_CROSSES = 0
DEFAULT_SPAN_LENGTH = 0.1
DEFAULT_STEPS = 1

# How far a step may stretch a vert at a corner of the run to keep the new row parallel. The exact
# factor is 1/sin of the half angle, which runs away as a corner doubles back; Split Angle caps a
# bend at 135 degrees, needing 2.61, so this leaves room without letting a stray fold explode.
MITER_LIMIT = 3.0

# How little of its intended step a vert may actually travel before the row counts as stalled. Snapping
# onto a curved source shortens a step a little; running out of source stops it dead, and nearest point
# then holds every further row against the same edge, stacking rows of zero-area quads on top of it.
STEP_STALL = 0.25


PATCH_SETTING_NAMES = (
    'split_angle', 'smooth', 'span_insert_mode', 'crosses', 'span_length', 'solution', 'offset', 'twist',
    'steps',
)


@dataclass
class PatchSettings:
    ''' Everything the rebuild reads off the tool, compared as a whole to decide staleness. '''
    split_angle : float = DEFAULT_SPLIT_ANGLE   # radians, deviation from straight, like PolyStrips' Split Angle
    smooth      : int = DEFAULT_SMOOTH
    span_mode   : str = DEFAULT_SPAN_MODE
    crosses     : int = DEFAULT_CROSSES
    span_length : float = DEFAULT_SPAN_LENGTH
    solution    : int = 1     # grid fill: 1 is the best-scoring split, higher flips through the rest, wrapping
    offset      : int = 0     # grid fill: rotate the chosen corners this many verts
    twist       : int = 0     # loft: rotate the loop pairing this many verts
    steps       : int = DEFAULT_STEPS   # offset: rows of quads to step outward


MAX_SELECTED_EDGES = 1000   # same bail-out as the loop/strip selection overlay
MAX_NEW_VERTS = 20000       # each new vert costs one closest-point query per source object

# two closed loops loft only if they face the same way and are stacked along their normals;
# side-by-side holes in one plane are two separate patches, not a tube
LOFT_PARALLEL = 0.5
LOFT_STACKED  = 0.5
# how far a sharp-corner match may outweigh a closer vertex pairing when lofting
LOFT_CORNER_WEIGHT = 0.5

# How far a new vert may be projected, in mean boundary edge lengths. The old cap was the patch's
# bounding-box diagonal, some eight quad widths on a 5x6, which let a projection cross a form and
# land on its far side. PolyStrips caps its rail verts at one rung width for the same reason.
SNAP_CAP_EDGES = 2.0

# An existing edge at a free corner of an L guides the new side leaving it, unless it runs along
# the selected strip: |cos| of the angle to the strip above this counts as running along it.
GUIDE_MAX_ALONG = 0.7
# Handle lengths of a guided side, as fractions of its chord: at the attached corner and at the
# fourth corner. Shorter at the corner keeps two sides meeting there from pinching into a point.
HANDLE_ATTACHED = 0.25
HANDLE_CORNER = 0.15
# A guide tangent leaning into the patch means the side will bow inward, so the fourth corner must
# come in: by the chord times the lean (sine of the angle) times this.
CONCAVE_PULL = 0.5

# Average disagreement between neighbouring verts' snap displacements, in quad widths, past which
# the fill is treated as garbage rather than geometry. Measured on synthetic grids: a flat drape
# reads 0.0, a steep dome 0.23, a saddle 0.32, a scan-like ripple 0.31, while verts landing on
# two different walls read 1.03 and fully scattered ones 1.3 or more. 0.7 sits between the two.
MAX_SNAP_NOISE = 0.7

# NEAREST QUAD: with nothing selected, four verts near the cursor make a quad (Maya's Quad Draw).
# How far from the cursor a vert may sit and still be a candidate, in ui-scaled pixels. This is
# what "too far away" means: a screen radius rather than a world distance, so it behaves the same
# at any zoom. Generous, because the cursor-inside test below is what actually picks the quad.
NEAREST_RADIUS_PX = 250
# Candidates whose four-subsets are tried, nearest first. 8 gives 70 combinations, each a handful
# of dot products; more would start to cost something per mouse move for very little gain.
NEAREST_K = 8
# A corner angle outside this range is a thin diamond or a near-collinear sliver. Matches the
# 45-90 / 90-135 "acceptable" band mesh-quality tools use, loosened because retopo quads on a
# curved surface legitimately skew further than a finite-element mesh would.
QUAD_MIN_ANGLE = 30.0
QUAD_MAX_ANGLE = 150.0
# Longest side over shortest. Aspect alone passes a sliver whose sides are all similar, which is
# why the angle test above is there too; this one catches the long thin strip.
QUAD_MAX_EDGE_RATIO = 4.0
# Angle between the two triangle normals across either diagonal: how far the quad is folded out of
# plane. 45 degrees is well past anything a surface-following quad needs and well short of a crease.
QUAD_MAX_WARP = 45.0
# How far outside the quad's screen outline the cursor may sit, as a fraction of the mean side
# length in pixels. Strictly inside is fiddly to hit; this gives the border some thickness.
QUAD_HOVER_SLOP = 0.25
# A new side whose two ends already share a neighbour vertex runs over that vertex when the corner
# there is this straight, i.e. the side is really two existing edges end to end. The quad should
# have stopped at that vertex, so it is refused rather than drawn across it.
SIDE_OVER_VERT_ANGLE = 120.0
# How far shape may outweigh size when ranking the quads the cursor is in. Size alone kept offering
# skewed quads and made the even ones fiddly to land on, so a quad's score is the screen area it
# covers divided by how square it is, which lets a better shape earn the right to be bigger.
# The two ways of not being square are weighted differently on purpose:
#   SKEW is a rhombus, corners away from 90. Weighted hard, since this is the shape that kept
#   winning when it should not, and a leaning quad is rarely what anyone wants.
#   ASPECT is a rectangle, one pair of sides longer than the other. Weighted lightly: a 2:1 quad
#   is ordinary retopo, and punishing it sends the pick back to reaching across the mesh for a
#   distant square.
# As set: a square wins over a 45 degree rhombus up to 4x its area, over a 2:1 rectangle up to
# 1.7x, and never over another square (there, smallest still wins outright).
SKEW_WEIGHT = 2.0
ASPECT_WEIGHT = 0.75
# Squareness cannot go below this, so a quad scraping past the angle and ratio gates cannot be
# scored so badly that a far larger one wins on shape alone.
MIN_SQUARENESS = 0.15

# HOVER EXTEND: with Ctrl held, nothing selected and no quad under the cursor, the nearest open edge
# steps outward and the nearest boundary corner offers its corner quad, so the hover workflow reaches
# everything the selection workflow does. Both radii are ui-scaled pixels. The vert wins when it is
# in range: it is the smaller target and is always the end of some edge that would otherwise win.
HOVER_VERT_PX = 15
HOVER_EDGE_PX = 40

# WELD FIT: a step or a corner quad about to create a vert first looks for one that is already
# there. How far from where the new vert would have landed an existing one may sit, as a fraction of
# that step's own length, and how square the quad using it must be. Below the squareness a fresh
# vert makes a better quad than a bent one, which is the whole reason the artist dropped points.
WELD_FIT_RADIUS = 0.6
WELD_FIT_MIN_SQUARENESS = 0.45

# DRAW: a Ctrl+LMB drag is sampled this often, in pixels, so a fast sweep through a row of points
# does not skip the cell between two mouse events.
DRAW_SAMPLE_PX = 6
# ...and a patch is only made once the path has come this far through it, as a fraction of the
# patch's extent along the direction of travel. Brushing into a cell is not the same as drawing
# through it, and this is what keeps a preview from being taken the instant it appears.
DRAW_ACCEPT_FRAC = 0.25

# 3D REACH: the pick works in screen space, where a vert far away along the view can sit right next
# to the others, so what it finds is checked against the surface point under the cursor. Every
# corner of a picked quad must be within this many mean side lengths of that point (a convex quad
# containing the cursor never needs more than ~0.85), and the edge or corner the hover extends must
# be within this many of its own edge lengths.
NEAREST_3D_REACH = 1.0
HOVER_3D_REACH = 2.0


# BMEdge helpers standing in for v3's RFEdge methods
def _shared_vert(e0, e1):
    return next((v for v in e0.verts if v in e1.verts), None)

def _share_vert(e0, e1):
    return any(v in e1.verts for v in e0.verts)

def _nonshared_vert(e0, e1):
    return next((v for v in e0.verts if v not in e1.verts), None)

def _angle_deg(d0, d1):
    return math.degrees(math.acos(max(-1.0, min(1.0, d0.dot(d1)))))

def _side2d(pa, pb, p):
    ''' Which side of the screen-space line pa->pb the point p is on: +1, -1, or 0 when degenerate. '''
    c = (pb.x - pa.x) * (p.y - pa.y) - (pb.y - pa.y) * (p.x - pa.x)
    return 0 if abs(c) < 1e-6 else (1 if c > 0 else -1)

def _bmedge_between(bmv_a, bmv_b):
    if not (isinstance(bmv_a, BMVert) and isinstance(bmv_b, BMVert)): return None
    return next((e for e in bmv_a.link_edges if e.other_vert(bmv_a) is bmv_b), None)

def _pco(pt):
    return pt.co if isinstance(pt, BMVert) else pt


def _quad_is_placeable(bm, verts) -> bool:
    ''' Whether a quad on these four verts, in this order, can legally be created.

    The shape tests in _quad_from_points say the quad is a good one; this says the mesh will still
    make sense afterwards. Refuses a third face on an edge, a face that is already there, a quad
    laid across existing geometry, and a diagonal that is really an edge of the mesh.

    A corner may also be a plain Vector: a vert the fill would create. It has no edges or faces, so
    every test that asks about its history simply does not apply, and the ones about the existing
    corners still do. That is what lets a step or a corner quad be judged before it is built.
    '''
    if len({ id(v) for v in verts }) != 4: return False
    isbm = [ isinstance(v, BMVert) for v in verts ]
    if all(isbm) and bm.faces.get(verts): return False

    cos = [ _pco(v) for v in verts ]
    centre = sum(cos, Vector()) / 4
    for i in range(4):
        va, vb = verts[i], verts[(i + 1) % 4]
        if not (isbm[i] and isbm[(i + 1) % 4]): continue   # a side to a vert not yet made has no history
        bme = _bmedge_between(va, vb)
        if bme is not None:
            if len(bme.link_faces) >= 2: return False   # a third face here would be non-manifold
            if bme.link_faces:
                # This edge already has a face on one side. If the new quad falls on that same
                # side it lies over the mesh instead of filling the empty side. One side saying so
                # is enough: unlike a whole patch boundary, a single quad has no majority to take.
                mid = (va.co + vb.co) / 2
                along = (vb.co - va.co).normalized()
                to_old = bme.link_faces[0].calc_center_median() - mid
                to_new = centre - mid
                to_old -= along * to_old.dot(along)
                to_new -= along * to_new.dot(along)
                if (to_old.length_squared > 1e-14 and to_new.length_squared > 1e-14
                        and to_old.dot(to_new) > 0): return False
            continue
        # No edge here yet, so this side would be created. If the two ends already reach each other
        # through one shared neighbour lying between them, the side runs straight over that vertex
        # and the quad has skipped a whole row of the mesh. A shared neighbour off to the side is
        # a different matter and is left alone, which is what the angle at it distinguishes.
        for w in { bme.other_vert(va) for bme in va.link_edges } & { bme.other_vert(vb) for bme in vb.link_edges }:
            if w in verts: continue
            d0, d1 = va.co - w.co, vb.co - w.co
            if d0.length_squared < 1e-14 or d1.length_squared < 1e-14: continue
            if _angle_deg(d0.normalized(), d1.normalized()) >= SIDE_OVER_VERT_ANGLE: return False

    # a diagonal that already exists as a faced edge means the quad straddles a fold in the mesh:
    # the two triangles either side of that edge are the real surface here, not one quad
    for a, b in ((0, 2), (1, 3)):
        bme = _bmedge_between(verts[a], verts[b])
        if bme is not None and bme.link_faces: return False

    # Two of the quad's verts sitting on one existing face without an edge of that face joining
    # them means the line between them cuts across the face, so the quad lies over it. This is the
    # overlap the side test above cannot see: opposite corners of a face touch none of its edges.
    for a, b in combinations(range(4), 2):
        if not (isbm[a] and isbm[b]): continue
        va, vb = verts[a], verts[b]
        for bmf in set(va.link_faces) & set(vb.link_faces):
            if not any(set(bme.verts) == {va, vb} for bme in bmf.edges): return False

    # And the same question asked at each corner rather than along the sides: the wedge the quad
    # would occupy at a vertex must not run into the faces that vertex already carries. A quad can
    # clear every test above and still open out over existing geometry, because none of its own
    # edges touch it.
    for i in range(4):
        if not isbm[i]: continue
        if _corner_overlaps_faces(verts[i], cos[i - 1], cos[(i + 1) % 4]): return False

    # And nothing already there may sit inside the quad: a boundary that dips into it between two
    # of its corners (the corners are joined through the mesh, just not to each other) leaves verts
    # and edges inside the new face. The side tests above cannot see those, since neither end of
    # the side owns them.
    if _mesh_juts_into_quad(verts, cos, isbm): return False
    return True


def _mesh_juts_into_quad(verts, cos, isbm, *, depth : int = 3):
    ''' Whether an existing vert lies inside the quad, or an existing edge crosses one of its sides,
    judged in the quad's own plane. Looks a few edges out from the quad's existing corners, which is
    where a boundary running between two of them lives, plus any loose points the candidate cache
    knows about near the quad.
    '''
    centre = sum(cos, Vector()) / 4
    n = (cos[2] - cos[0]).cross(cos[3] - cos[1])
    if n.length_squared < 1e-18: return False
    n.normalize()
    u = cos[1] - cos[0]
    u = u - n * u.dot(n)
    if u.length_squared < 1e-18: return False
    u.normalize()
    w = n.cross(u)
    mean_side = sum((cos[(i + 1) % 4] - cos[i]).length for i in range(4)) / 4
    thick = 0.5 * mean_side          # how far off the plane a vert may be and still count as "in" it
    eps = 0.02 * mean_side           # verts sitting on a side are the side test's business, not this one's

    def to2d(co):
        d = co - centre
        return Vector((d.dot(u), d.dot(w))), abs(d.dot(n))
    poly = [ to2d(c)[0] for c in cos ]

    def inside(p):
        if not point_inside_face_2d(p, poly): return False
        return min(_dist2d_point_segment(p, poly[i], poly[(i + 1) % 4]) for i in range(4)) > eps

    def crosses(pa, pb):
        # strict interior crossing of segment pa-pb with any side
        for i in range(4):
            qa, qb = poly[i], poly[(i + 1) % 4]
            s1, s2 = _side2d(pa, pb, qa), _side2d(pa, pb, qb)
            s3, s4 = _side2d(qa, qb, pa), _side2d(qa, qb, pb)
            if s1 and s2 and s3 and s4 and s1 != s2 and s3 != s4: return True
        return False

    corners = { v for v, b in zip(verts, isbm) if b }
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
            if hb > thick: continue
            if crosses(pa, pb): return True

    # loose points the mesh does not lead to, from the cache when there is one
    Lg = LegacyPatches_Logic
    if Lg.cand_cos is not None and len(Lg.cand_cos):
        lo = np.array([min(c[k] for c in cos) - thick for k in range(3)])
        hi = np.array([max(c[k] for c in cos) + thick for k in range(3)])
        box = np.flatnonzero(np.all((Lg.cand_cos >= lo) & (Lg.cand_cos <= hi), axis=1))
        idx = { v.index for v in corners }
        for k in box:
            if Lg.cand_idx[k] in idx: continue
            p, h = to2d(Vector(Lg.cand_cos[k]))
            if h <= thick and inside(p): return True
    return False


def _smooth_path(pts, passes : int = 2):
    ''' A lightly smoothed copy of a polyline, endpoints kept. Three-point averaging, run a couple of
    times: enough to take the jitter out of a drawn line without pulling it off the cells it went
    through. Display only; the raw points are what the drag is judged by.
    '''
    out = list(pts)
    for _ in range(passes):
        if len(out) < 3: break
        out = [out[0]] + [ ((out[i - 1][0] + 2 * out[i][0] + out[i + 1][0]) / 4,
                            (out[i - 1][1] + 2 * out[i][1] + out[i + 1][1]) / 4)
                           for i in range(1, len(out) - 1) ] + [out[-1]]
    return out


def _quad_area3d(cos):
    # exact for a planar quad, close enough for the nearly planar ones the shape test lets through
    return 0.5 * (cos[2] - cos[0]).cross(cos[3] - cos[1]).length


def _complete_quad(bm, known, slots, *, min_squareness):
    ''' Finish a quad from existing verts instead of creating new ones.

    `known` are the corners already decided (two, a side; or three), in ring order; `slots` holds
    the candidate verts for each corner still open, in the order those corners follow the known
    ones round the ring. Every assignment is tried and judged the way the cursor pick judges its
    quads: shape in 3D, legality against the mesh, then smallest-for-its-squareness wins. Returns
    (verts, cost) in ring order, or None when no candidate makes a quad worth having. Pure enough
    to probe on its own.
    '''
    n_open = len(slots)
    if n_open not in (1, 2) or len(known) + n_open != 4: return None
    best = None

    def consider(verts):
        nonlocal best
        cos = [ _pco(v) for v in verts ]
        sq = _quad_shape_ok(cos)
        if sq is None or sq < min_squareness: return
        if not _quad_is_placeable(bm, verts): return
        cost = _quad_area3d(cos) / sq
        if best is None or cost < best[1]: best = (list(verts), cost)

    if n_open == 1:
        for w in slots[0]:
            if w in known: continue
            consider(known + [w])
    else:
        for w0 in slots[0]:
            if w0 in known: continue
            for w1 in slots[1]:
                if w1 in known or w1 is w0: continue
                consider(known + [w0, w1])
    return best


def _dist2d_point_segment(p, a, b):
    ''' Screen-space distance from p to the segment a-b. '''
    d = b - a
    dd = d.length_squared
    if dd < 1e-12: return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(d) / dd))
    return (p - (a + d * t)).length


def _quad_shape_ok(q):
    ''' Squareness of a quad given its four corners in ring order, or None when the shape is one
    not worth offering: a thin diamond, a long strip, or something folded over a crease.

    1.0 is a perfect square. The two ways of falling short are kept separate because they are
    weighted differently when ranking (see SKEW_WEIGHT). Measured in 3D, where the quad lives.
    '''
    sides = [q[(i + 1) % 4] - q[i] for i in range(4)]
    lens = [s.length for s in sides]
    if min(lens) < 1e-9: return None
    if max(lens) / min(lens) > QUAD_MAX_EDGE_RATIO: return None

    worst_corner = 0.0
    for i in range(4):
        ang = _angle_deg(-sides[i - 1].normalized(), sides[i].normalized())
        if ang < QUAD_MIN_ANGLE or ang > QUAD_MAX_ANGLE: return None
        worst_corner = max(worst_corner, abs(ang - 90.0))

    # warp: split the quad along each diagonal and compare the two triangle normals. A quad bent
    # over a crease reads high here, and bridging a crease with one quad is never what was meant.
    for d in (0, 1):
        n0 = (q[(d + 1) % 4] - q[d]).cross(q[(d + 2) % 4] - q[d])
        n1 = (q[(d + 2) % 4] - q[d]).cross(q[(d + 3) % 4] - q[d])
        if n0.length_squared < 1e-18 or n1.length_squared < 1e-18: return None
        if _angle_deg(n0.normalized(), n1.normalized()) > QUAD_MAX_WARP: return None

    return (1.0 - worst_corner / 90.0) ** SKEW_WEIGHT * (min(lens) / max(lens)) ** ASPECT_WEIGHT


def _is_convex_2d(pts):
    ''' Whether four screen points, in ring order, make a convex quad. Every turn the same way means
    convex. A zero turn is three points in a line; one turn disagreeing means a point sits inside
    the triangle of the other three, so the four have no convex quad between them, only a dart. '''
    signs = []
    for i in range(4):
        s = _side2d(pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4])
        if s == 0: return False
        signs.append(s)
    return len(set(signs)) == 1


def _corner_overlaps_faces(bmv, co_prev, co_next, *, tol_deg=5.0):
    ''' Whether the wedge a new quad would occupy at `bmv` runs into the faces already there.

    Every face around a vertex takes up a slice of the directions leaving it. A new quad takes up
    the slice between its two sides. If those slices overlap, the quad is being built out over
    geometry that exists, however its own edges happen to fall. Sharing an edge with a face is not
    an overlap, which is what the tolerance allows for.
    '''
    faces = [ f for f in bmv.link_faces if not f.hide ]
    if not faces: return False
    n = sum((f.normal for f in faces), Vector())
    if n.length_squared < 1e-18: return False
    n.normalize()

    # a frame on the surface at this vertex, so directions can be compared as angles round it
    u = co_prev - bmv.co
    u = u - n * u.dot(n)
    if u.length_squared < 1e-18: return False
    u.normalize()
    w = n.cross(u)

    def angle_of(co):
        d = co - bmv.co
        d = d - n * d.dot(n)
        if d.length_squared < 1e-18: return None
        return math.degrees(math.atan2(d.dot(w), d.dot(u)))

    def wrap(a):
        return (a + 180.0) % 360.0 - 180.0

    def arc(co_a, co_b):
        # the slice between two directions, taken the short way round: both a convex face corner
        # and a convex quad corner span less than a half turn
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


def _quad_from_points(pts2d, cos3d, mouse):
    ''' Order four points into a quad and judge whether it is one worth offering.

    `pts2d` are the verts' screen positions, `cos3d` their world positions, `mouse` the cursor.
    Returns (order, score) with `order` indexing into the inputs, or None when the four cannot make
    an acceptable quad. Lower score is better. Pure function, so it can be probed on its own.
    '''
    # Sorting by angle around the centroid is what makes the four points a simple (non
    # self-intersecting) polygon: any other order crosses itself. For four points this is exact.
    centre2d = sum(pts2d, Vector((0, 0))) / 4
    order = sorted(range(4), key=lambda k: math.atan2(pts2d[k].y - centre2d.y, pts2d[k].x - centre2d.x))
    p = [pts2d[k] for k in order]

    if not _is_convex_2d(p): return None

    # The cursor decides which quad the artist means: four points near each other can be paired up
    # several ways, and Maya resolves the same ambiguity by which face the cursor is inside. The
    # slop gives the outline some thickness so the edge of a quad is not a knife edge to hit.
    mean_side = sum((p[(i + 1) % 4] - p[i]).length for i in range(4)) / 4
    inside = point_inside_face_2d(mouse, p)
    if not inside:
        slop = QUAD_HOVER_SLOP * mean_side
        if min(_dist2d_point_segment(mouse, p[i], p[(i + 1) % 4]) for i in range(4)) > slop:
            return None

    # shape in 3D, where the quad actually lives: a quad can look square on screen and be a sliver
    # seen face-on, or look skewed and be square
    squareness = _quad_shape_ok([cos3d[k] for k in order])
    if squareness is None: return None

    # Size and squareness together. Several quads can hold the cursor at once - the cell it is in,
    # and every bigger one built around that - so the small one is usually the one meant, but size
    # alone kept offering rhombuses and long rectangles and made the even quads hard to land on.
    # See SKEW_WEIGHT for how the two are balanced. Squareness is measured in 3D, where the quad
    # lives: a square on a surface seen at an angle is still a square. Ranking by shape ALONE was
    # the first thing tried and it let a big well-proportioned quad reach clean across a row of
    # the mesh, so size has to stay in the score.
    area = abs(sum(p[i].x * p[(i + 1) % 4].y - p[(i + 1) % 4].x * p[i].y for i in range(4))) / 2
    cost = area / max(squareness, MIN_SQUARENESS)
    dist = sum((pt - mouse).length_squared for pt in p)
    return order, (0 if inside else 1, cost, dist)

def _fit_sphere_centre(p_a, n_a, p_b, n_b):
    ''' Centre of the sphere through two points with the given surface normals, or None when the
    normals are (nearly) parallel and the surface between them is flat. Same fit Relax uses for
    Interpolate Loops. The radius is signed, so a concave surface works too. '''
    d = n_b - n_a
    dd = d.dot(d)
    if dd < 1e-10: return None
    r = (p_b - p_a).dot(d) / dd
    if abs(r) < 1e-10: return None
    return p_a - n_a * r

def _arc_rotation(centre, p_a, p_b, t=1.0):
    ''' Rotation about `centre` carrying p_a onto p_b, scaled to fraction t of the way. None when the
    two are collinear with the centre. '''
    va, vb = p_a - centre, p_b - centre
    axis = va.cross(vb)
    if axis.length_squared < 1e-14 or va.length_squared < 1e-14 or vb.length_squared < 1e-14: return None
    return Matrix.Rotation(va.angle(vb) * t, 3, axis.normalized())

def _bend_along(p_a, n_a, p_b, n_b, x):
    ''' Move x the way the surface carries p_a to p_b: the rotation about the fitted sphere, which
    is the parallelogram completion bent to the surface. Flat surface: the plain translation. '''
    centre = _fit_sphere_centre(p_a, n_a, p_b, n_b) if (n_a is not None and n_b is not None) else None
    rot = _arc_rotation(centre, p_a, p_b) if centre is not None else None
    if rot is None: return x + (p_b - p_a)
    return centre + rot @ (x - centre)

def _arc_between(p_a, n_a, p_b, n_b, fracs):
    ''' Points at the given fractions along the arc from p_a to p_b on the sphere fitted to their
    normals, with the normal carried along; straight line and lerped normals when flat. '''
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

def _mirror_curve(p0, t0, p3, h0=HANDLE_ATTACHED, h3=HANDLE_CORNER):
    ''' Control points of a cubic from p0, leaving along t0, to p3, arriving along t0 mirrored across
    the chord. A tangent along the chord gives a straight line and one off it an even bow, never a
    curl. h0 and h3 are the handle lengths as fractions of the chord. Returns (p1, p2, arrival dir). '''
    chord = p3 - p0
    length = chord.length
    if length < 1e-9: return p0, p3, t0
    c = chord / length
    t3 = c * (2.0 * t0.dot(c)) - t0
    t3 = t3.normalized() if t3.length_squared > 1e-12 else c
    return p0 + t0 * (h0 * length), p3 - t3 * (h3 * length), t3

def _cumulative_fracs(cos):
    ''' Fraction of the total polyline length reached at each point, 0 at the first and 1 at the last. '''
    seg = [ (cos[k + 1] - cos[k]).length for k in range(len(cos) - 1) ]
    total = sum(seg) or 1.0
    out, acc = [0.0], 0.0
    for l in seg:
        acc += l
        out.append(acc / total)
    out[-1] = 1.0
    return out

def _turn_sharpness(cos):
    ''' How sharply a closed loop of coordinates turns at each vert: 0 straight, 2 doubled back. '''
    n = len(cos)
    out = []
    for i in range(n):
        d0 = (cos[i] - cos[(i - 1) % n]).normalized()
        d1 = (cos[(i + 1) % n] - cos[i]).normalized()
        out.append(1.0 - max(-1.0, min(1.0, d0.dot(d1))))
    return out


def _grid_snap_noise(cos, raws, l0, l1, *, cyclic_i=False):
    ''' How inconsistently snapping moved neighbouring verts, measured in quad widths.

    A patch draped over a curved surface moves a long way but moves together, so this stays
    small. A patch whose verts each find their own unrelated piece of the source moves every
    vert a different way, which is the noisy result that is not worth building.
    '''
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
    kind     : str          # 'rect' | 'L' | 'C' | 'I' | 'loft' | 'grid' | 'bridge' | 'offset' | 'corner' | 'nearest' | 'quad'
    vert_idx : list         # bm vert index for existing verts, None for verts Fill will create
    vert_co  : list         # local-space coords (copies for existing verts)
    edges    : list         # index pairs into vert_co (new edges only, for the dashed preview)
    faces    : list         # index tuples into vert_co
    open_idx : tuple = ()   # new verts sitting on the patch boundary, i.e. a side being created
    row_idx  : tuple = ()   # offset step: the row to leave selected after Fill, so the next step is
                            # offered straight away. Holds new verts and the existing verts the row
                            # welds onto, which are not themselves selected when Fill runs
    hover    : bool = False # built from the cursor with nothing selected. Fill leaves nothing
                            # selected afterwards so the cursor keeps picking, and its verts are not
                            # held to being selected since none of them are


class LegacyPatches_Logic:
    depsgraph_version : ClassVar[int] = -1
    last_settings     : ClassVar[PatchSettings | None] = None
    dirty             : ClassVar[bool] = True

    # products of the last recompute. plain data only: never BMesh element refs, which
    # invalidate on every depsgraph update (see loopstrip_selection_overlay for the same rule)
    boundary_verts : ClassVar[dict[int, Vector]] = {}      # vert index -> local co, for hover picking
    corner_indices : ClassVar[set[int]] = set()            # detected strip corners
    labels         : ClassVar[list[tuple[str, list[Vector]]]] = []
    previz         : ClassVar[list[Previz]] = []
    has_bridge     : ClassVar[bool] = False
    has_loft       : ClassVar[bool] = False
    has_grid       : ClassVar[bool] = False
    has_offset     : ClassVar[bool] = False                # a step outward is previewed
    has_quad       : ClassVar[bool] = False                # a single quad (cursor, four verts, corner) is previewed
    has_manual_corners : ClassVar[bool] = False            # any corner override on the selected boundary
    wire_runs      : ClassVar[list] = []                   # (chord co0, chord co1, mouse side sign) per
                                                           # previewed wire offset, for track_mouse
    grid_last      : ClassVar[tuple[int, int] | None] = None   # (span, offset) actually used
    grid_ranked    : ClassVar[list] = []                       # (span, offset) of every split, best first
    grid_sig       : ClassVar[tuple | None] = None             # selection the solutions were ranked for
    solution_pending : ClassVar[int | None] = None             # solution number to push into the tool property
    solution_stale   : ClassVar[int | None] = None             # what the property held when that push was scheduled
    loops_last     : ClassVar[int | None] = None               # loops the last bridge/loft used
    sel_sig        : ClassVar[tuple | None] = None             # selection the last live rebuild ran on
    steps_pending  : ClassVar[int | None] = None               # steps value written by a timer that has not landed yet
    filled_sig     : ClassVar[tuple | None] = None             # selection left behind by the last fill
    filled_flags   : ClassVar[tuple] = (False, False, False, False, False)   # (bridge, grid, loft, offset, quad) of the last fill, for its redo panel
    filled_loops   : ClassVar[int] = 0                         # loops the last fill put across a bridge or loft
    filled_solutions : ClassVar[int] = 1                       # grid solutions the last fill's loop had, for wrapping
    error          : ClassVar[str | None] = None

    # input, not a product of the rebuild: the offset of a wire run steps toward the mouse
    mouse          : ClassVar[tuple[int, int] | None] = None    # window space, from the overlay's events
    # Where the cursor was when the last fill was started. A wire run has nothing but the cursor to
    # say which side it steps to, so once the patch is made that answer is settled: the redo panel
    # re-runs the whole rebuild, and without this it would read wherever the mouse has since gone
    # and quietly flip the patch over.
    mouse_locked   : ClassVar[tuple[int, int] | None] = None

    # Nearest-quad caches. Kept across recomputes (so NOT cleared by _clear_products): they only go
    # stale when the mesh or the view changes, and rebuilding them per frame is exactly what this
    # feature must not do. Indices and copied coords only, like every other product here.
    cand_key       : ClassVar[tuple | None] = None       # (depsgraph_version, edit object name) the candidates belong to
    cand_idx       : ClassVar[list[int]] = []            # candidate vert indices
    cand_cos       : ClassVar[object] = None             # (N,3) array of their local coords
    proj_key       : ClassVar[tuple | None] = None       # cand_key + view matrix + region size
    proj_px        : ClassVar[object] = None             # (N,2) array of region pixels, NaN behind the camera
    vis_cache      : ClassVar[dict] = {}                 # candidate row -> visible, for the current proj_key
    vis_key        : ClassVar[tuple | None] = None
    cand_edges     : ClassVar[object] = None             # (M,2) rows into the candidate arrays: the open edges
    cand_open      : ClassVar[object] = None             # (N,) open edges at each candidate, for corner picking
    nearest_active : ClassVar[bool] = False              # nothing is selected, so the cursor picks a quad
    nearest_sig    : ClassVar[frozenset | None] = None   # vert indices of the quad currently offered
    hover_sig      : ClassVar[tuple | None] = None       # ('edge'|'vert', index) the hover extend is showing for
    drag_path      : ClassVar[list] = []                 # window-space points of the Ctrl+LMB drag being drawn
    drag_last      : ClassVar[list | None] = None        # local-space face outlines of the last patch a drag made:
                                                         # nothing is previewed or made until the cursor has left them
    drag_cand      : ClassVar[tuple | None] = None       # (key of the preview the drag is in, where the cursor entered it)
    # The F quick switch holds a key down already, so it stands in for Ctrl: the cursor pick runs
    # without Ctrl while it is active. Owned by the quick switch, so reset_session leaves it alone.
    ctrl_forced    : ClassVar[bool] = False
    # Ctrl held. The cursor pick only runs while it is, the way PolyPen only inserts under Ctrl:
    # a quad appearing under the cursor whenever nothing is selected is too eager, and it would
    # also fight plain clicking around the mesh.
    ctrl           : ClassVar[bool] = False
    # Ctrl at the moment the last fill was started, for the same reason mouse_locked exists: a redo
    # panel edit re-runs the whole rebuild long after the key was let go, and the quad it is
    # rebuilding only exists while Ctrl is down.
    ctrl_locked    : ClassVar[bool | None] = None

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
        L.cand_cos = None
        L.proj_key = None
        L.proj_px = None
        L.vis_cache = {}
        L.vis_key = None
        L.cand_edges = None
        L.cand_open = None
        L.nearest_active = False
        L.nearest_sig = None
        L.hover_sig = None
        L.drag_path = []
        L.drag_last = None
        L.drag_cand = None
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
        L.has_bridge = False
        L.has_loft = False
        L.has_grid = False
        L.has_offset = False
        L.has_quad = False
        L.has_manual_corners = False
        L.grid_last = None
        L.grid_ranked = []
        L.loops_last = None
        L.wire_runs = []
        L.error = None

    @staticmethod
    def selection_signature(bm, edges) -> tuple:
        # face count guards against unrelated edits that happen to leave the same edges selected
        return (len(bm.faces), frozenset(e.index for e in edges))

    @staticmethod
    def settled_steps(steps : int) -> int:
        L = LegacyPatches_Logic
        if L.steps_pending is not None:
            if steps == L.steps_pending: L.steps_pending = None
            else: return L.steps_pending
        return max(1, steps)

    @staticmethod
    def push_steps(value : int):
        # Same restriction as push_solution: the rebuild runs from a draw callback and cannot write
        # properties, so the reset goes through a timer. Until it lands, read_settings reports the
        # value being written, so a rebuild in between does not preview the old count for a frame.
        LegacyPatches_Logic.steps_pending = value
        def write():
            try:
                props = LegacyPatches_Logic.tool_props(bpy.context)
                if props is not None and props.steps != value:
                    props.steps = value
            except Exception:
                pass
            return None
        bpy.app.timers.register(write, first_interval=0.0)

    @staticmethod
    def push_solution(value : int, stale : int):
        # Writes are not allowed from the draw callback the rebuild runs in, so the property is set
        # from a timer. `stale` is what it holds now; until that changes, `value` stands in for it.
        L = LegacyPatches_Logic
        L.solution_pending, L.solution_stale = value, stale
        def write():
            try:
                props = L.tool_props(bpy.context)
                if props is not None and L.solution_pending is not None and props.solution != L.solution_pending:
                    props.solution = L.solution_pending
            except Exception:
                pass
            return None
        bpy.app.timers.register(write, first_interval=0.0)

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
        props = LegacyPatches_Logic.tool_props(context)
        if not props: return PatchSettings()
        try:
            return PatchSettings(
                split_angle = float(props.split_angle),
                smooth      = int(props.smooth),
                span_mode   = str(props.span_insert_mode),
                crosses     = int(props.crosses),
                span_length = float(props.span_length),
                solution    = int(props.solution),
                offset      = int(props.offset),
                twist       = int(props.twist),
                steps       = LegacyPatches_Logic.settled_steps(int(props.steps)),
            )
        except Exception:
            return PatchSettings()

    # Ctrl+Scroll drives the count knob, Shift+Scroll the offset knob, matching Contours.
    # Which knob is live depends on what the selection produced; a loft consumes both closed
    # loops, so a loft and a grid fill can never be on screen at the same time.

    @staticmethod
    def adjust_count(context : Context, delta : int) -> bool:
        L = LegacyPatches_Logic
        if L.has_bridge and L.loops_last is not None:
            # scrolling is an explicit count, so stop deriving one over the top of it
            props = L.tool_props(context)
            if not props: return False
            props.span_insert_mode = 'FIXED'
            props.crosses = max(0, L.loops_last + delta)
        elif L.has_grid and L.grid_ranked:
            # flip through the ranked splits, wrapping round at either end
            props = L.tool_props(context)
            if not props: return False
            count = len(L.grid_ranked)
            props.solution = (props.solution - 1 + delta) % count + 1
        elif L.has_quad:
            props = L.tool_props(context)
            if not props: return False
            props.crosses = max(0, props.crosses + delta)
        elif L.has_offset:
            # last, so a patch that is also on screen keeps the knob it has always had
            props = L.tool_props(context)
            if not props: return False
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
            props.twist = props.twist + delta
        elif L.has_grid:
            props.offset = props.offset + delta
        else:
            return False
        L.dirty = True
        return True

    @staticmethod
    def foreign_operator_running() -> bool:
        # Transform, TopoRotate and the rest move geometry every frame. v3 deferred recomputing
        # while grabbing, and the cached previz is a frame behind for as long as they run, so it
        # is neither rebuilt nor drawn until they finish. An operator that only holds a key down
        # (the F quick switch) flags itself passive, so the preview it exists to show can rebuild.
        return any(not isinstance(op, RFOverlay_Base) and not getattr(op, 'rf_patches_passive', False)
                   for op in RFOperator.active_operators)

    @staticmethod
    def update(context : Context, *, force : bool = False):
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

        if not (L.dirty or force): return
        L.dirty = False
        try:
            L._recompute(context, settings, live=True)
        except ReferenceError:
            # bmesh swapped out under us mid-frame; rebuild on the next one
            L._clear_products()
            L.dirty = True

    @staticmethod
    def _recompute(context : Context, settings : PatchSettings, *, live : bool = False):
        L = LegacyPatches_Logic
        # v3 compared the interior angle against a threshold; Split Angle is the same test stated as a
        # deviation from straight, the way PolyStrips does it
        min_angle, smooth_iterations = 180.0 - math.degrees(settings.split_angle), settings.smooth
        L.nearest_active = False
        # A live rebuild follows the cursor; a fill and every redo of it use the cursor the fill was
        # started with, so the side a wire run stepped to cannot change after the fact.
        mouse_at = L.mouse if live else (L.mouse_locked if L.mouse_locked is not None else L.mouse)
        ctrl_at = (L.ctrl or L.ctrl_forced) if live else (L.ctrl_locked if L.ctrl_locked is not None else L.ctrl)
        L._clear_products()

        edit_object = context.edit_object
        assert edit_object
        M = edit_object.matrix_world
        bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)

        # read-only here: this runs from a draw callback, so the layer is only ever created by toggle_corner()
        layer = bm.verts.layers.int.get(CORNER_LAYER)
        def override(bmv):
            return bmv[layer] if layer else CORNER_AUTO

        ##############################################
        # find edges that could be part of a strip
        edges = { e for e in bmops.get_all_selected_bmedges(bm) if len(e.link_faces) < 2 and not e.hide }
        # the selected verts, counted only as far as needed to tell none, one, four and more apart
        sel_verts = []
        for bmv in bm.verts:
            if not bmv.select or bmv.hide: continue
            sel_verts.append(bmv)
            if len(sel_verts) > 4: break
        lone_bmv = sel_quad = None

        # Four selected verts are a quad when at least one of them is loose, i.e. on no selected
        # edge. That is what tells "I picked four points" from the edge selections the strips below
        # already handle: two separate edges are a bridge with its count knob, an L or a C has every
        # vert on a selected edge. An edge plus two points, or four points, is the quad.
        if len(sel_verts) == 4 and any(not any(e in edges for e in v.link_edges) for v in sel_verts):
            sel_quad = L._selected_quad(bm, sel_verts, context.region, context.region_data, M)
            if sel_quad is not None:
                edges = set()   # the quad is the whole fill; a selected edge among the four must not also step

        if not edges and sel_quad is None and len(sel_verts) == 1:
            # nothing to fill or step, but a single vert with two open edges is a corner of a quad
            lone_bmv = sel_verts[0]
        # anything else selected but giving no preview (a stray vert, a couple of them) just falls
        # through to the cursor pick at the end
        sel_edges = frozenset(edges)    # `edges` is reused as a local name below; this one is the selection
        # the Clear Corners button only shows once there is something to clear
        L.has_manual_corners = layer is not None and any(
            bmv[layer] != CORNER_AUTO for bme in sel_edges for bmv in bme.verts)
        if len(edges) > MAX_SELECTED_EDGES:
            L.error = f'Patches: too many selected boundary edges ({len(edges)})'
            return

        sig = L.selection_signature(bm, edges)
        if edges and sig == L.filled_sig:
            # the patch we just built is still what is selected: offer nothing for it rather than
            # stacking a second patch on top. The cursor pick at the end may still have something.
            edges = set()
        if live and sig != L.sel_sig:
            # a different selection starts over at one step, so a count scrolled up for one run does
            # not silently carry onto the next. fill() never takes this path: its settings are decided
            L.sel_sig = sig
            if settings.steps != 1:
                L.push_steps(1)
                settings = replace(settings, steps=1)   # never mutate: update() holds this same object

        L.boundary_verts = { v.index: v.co.copy() for e in edges for v in e.verts }

        shapes = {
            'O':    [],     # special loop
            'eye':  [],     # loops
            'tri':  [],
            'rect': [],
            'ngon': [],
            'C':    [],     # strings
            'L':    [],
            'I':    [],
            'else': [],
        }

        ###################
        # find strips
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
                    bmv1 = _shared_vert(edge, e)
                    if bmv1 is None: continue
                    ov = override(bmv1)
                    if ov == CORNER_FORCED: continue
                    bmv0 = edge.other_vert(bmv1)
                    bmv2 = e.other_vert(bmv1)
                    d10 = (bmv0.co - bmv1.co).normalized()
                    d12 = (bmv2.co - bmv1.co).normalized()
                    if ov != CORNER_SMOOTH and _angle_deg(d10, d12) < min_angle: continue
                    neighbors[edge].append(e)
                    neighbors[e].append(edge)
                    working.add(e)
            strips.append(strip)

        ##############################################
        # order strips to find corners and O-shapes
        nstrips = []
        corners = dict()
        for sedges in strips:
            if len(sedges) == 1:
                # single edge in strip
                edge = next(iter(sedges))
                strip = [edge]
                v0, v1 = edge.verts
                nstrips.append(strip)
                corners.setdefault(v0, []).append(strip)
                corners.setdefault(v1, []).append(strip)
                continue
            end_edges = [edge for edge in sedges if len(neighbors[edge]) == 1]
            if not end_edges:
                # could not find corners: O-shaped!
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
                    # unexpected number of edges found, see GitHub issue #481
                    isbad = True
                    break
                strip.append(next_edges[0])
                rem.remove(next_edges[0])
            if isbad: continue
            v0 = strip[0].other_vert(_shared_vert(strip[0], strip[1]))
            v1 = strip[-1].other_vert(_shared_vert(strip[-1], strip[-2]))
            corners.setdefault(v0, []).append(strip)
            corners.setdefault(v1, []).append(strip)
            nstrips.append(strip)
        strips = nstrips
        for strip in strips:
            # the count sits on the strip's middle edge, so it reads as belonging to that side. A
            # single edge says nothing with its count, and next to a step's own count it read as two
            # stray ones.
            if len(strip) < 2: continue
            mid = strip[len(strip) // 2]
            L.labels.append((str(len(strip)), [(mid.verts[0].co + mid.verts[1].co) / 2]))

        ##################################################################
        # find all strings (I,L,C,else) and loops (eye,tri,rect,ngon)
        # note: all corner verts with one strip are *not* in a loop

        # ignore corners with 3+ strips
        ignore_corners = { c for c in corners if len(corners[c]) > 2 }

        def align_strips(strips):
            ''' make sure that the edges at the end of adjacent strips share a vertex '''
            if len(strips) == 1: return strips
            strip0, strip1 = strips[:2]
            if _share_vert(strip0[0], strip1[0]) or _share_vert(strip0[0], strip1[-1]): strip0.reverse()
            if not (_share_vert(strip0[-1], strip1[0]) or _share_vert(strip0[-1], strip1[-1])): return None
            for strip0, strip1 in zip(strips[:-1], strips[1:]):
                if _share_vert(strip1[-1], strip0[-1]): strip1.reverse()
                if not _share_vert(strip1[0], strip0[-1]): return None
            return strips

        remaining_corners = set(corners.keys())
        string_corners = set()
        loop_corners = set()

        # find strings
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
            if len(string_strips) == 1:
                shapes['I'].append(string_strips)
            elif len(string_strips) == 2:
                shapes['L'].append(string_strips)
            elif len(string_strips) == 3:
                shapes['C'].append(string_strips)
            else:
                shapes['else'].append(string_strips)

        # find loops
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
            # make sure loop is actually closed
            s0, s1 = loop_strips[0], loop_strips[-1]
            shared_verts = sum(1 if _share_vert(e0, e1) else 0 for e0 in s0 for e1 in s1)
            if len(loop_strips) == 2 and shared_verts != 2: continue
            if len(loop_strips) > 2 and shared_verts != 1: continue
            if len(loop_strips) == 2:
                shapes['eye'].append(loop_strips)
            elif len(loop_strips) == 3:
                shapes['tri'].append(loop_strips)
            elif len(loop_strips) == 4:
                shapes['rect'].append(loop_strips)
            else:
                shapes['ngon'].append(loop_strips)

        L.corner_indices = { c.index for c in (string_corners | loop_corners) }

        ###################
        # generate previz

        # source snapping and mirror handling, set up once per recompute
        Mi = M.inverted_safe()
        sources = [ (o, o.matrix_world, o.matrix_world.inverted_safe()) for o in iter_all_valid_sources(context) ]
        mirror_axes = active_mirror_axes(context)
        mt = mirror_threshold(context) or 0.0

        def snap(co_local, normal_world=None, cap=None, *, ray=True, missed=None):
            # v3 nearest_sources_Point. With a normal, cast along it both ways first so the point keeps
            # its in-surface position (nearest-point drags points sideways when they start off-surface);
            # the cap rejects hits on unrelated far surfaces. Nearest point is the fallback either way.
            # A step passes ray=False: it moves along the surface, so it is barely off it to begin with
            # and has nothing to gain from a ray, while a ray leaving the edge of the source carries on
            # and lands on whatever is behind it. Nearest point cannot reach past the closest surface.
            def refused():
                # the caller asked to be told when nothing was found to snap to, so it can stop
                # rather than leave a vert hanging in the air off the edge of the source
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
            # nearest point has no sense of direction: refuse anything far away or facing the other
            # way, which is how a patch used to fold onto the back of a form. An unsnapped point is
            # the lesser evil; the noise guard and Smooth deal with what is left.
            if normal_world is not None or cap:
                r = nearest_point_normal_valid_sources(context, co_world)
                if r is None: return refused()
                hit, hit_n = r
                if cap and (hit - co_world).length > cap: return refused()
                if normal_world is not None and hit_n.dot(normal_world) < 0: return refused()
                return Mi @ hit
            co = nearest_point_valid_sources(context, co_world, world=False, sources=sources)
            return Vector(co) if co else refused()

        def sym_axes(co):
            # v3 get_point_symmetry: mirror planes this point sits on
            return frozenset(a for a in mirror_axes if sign_threshold(getattr(co, a), mt) == 0)

        def to_planes(co, axes):
            # v3 snap_to_symmetry: pin onto the given planes, re-snapping so it stays on the source
            if not axes: return co
            for a in axes: setattr(co, a, 0.0)
            co = snap(co)
            for a in axes: setattr(co, a, 0.0)
            return co

        def pco(pt):
            # a boundary point is either an existing BMVert or a coordinate we will create
            return pt.co if isinstance(pt, BMVert) else pt

        def shape_side(bmvs):
            # v3 assumed the +X side. per axis, take the side the shape's own boundary is on;
            # 0 means it straddles the plane, so leave that axis alone
            side = {}
            for a in mirror_axes:
                votes = [ s for v in bmvs if (s := sign_threshold(getattr(pco(v), a), mt)) != 0 ]
                pos = sum(1 for s in votes if s > 0)
                neg = len(votes) - pos
                side[a] = 1 if not votes else (0 if (pos and neg) else (1 if pos else -1))
            return side

        def shape_cap(bmvs):
            # a few mean boundary edge lengths, in world units: a local limit on how far a new vert
            # may be projected, so it cannot cross the form and land on the far side
            cos = [ M @ pco(v) for v in bmvs ]
            lens = [ l for a, b in zip(cos, cos[1:]) if (l := (b - a).length) > 1e-9 ]
            if not lens: return None
            return SNAP_CAP_EDGES * sum(lens) / len(lens)

        def new_point(co_blend, side, normal_world=None, cap=None, *, ray=True, missed=None):
            # v3 nearest_sources_Point + clamp_point_to_symmetry
            co = snap(co_blend, normal_world, cap, ray=ray, missed=missed)
            for a, s in side.items():
                if not s: continue
                sv = sign_threshold(getattr(co, a), mt)
                if sv == 0:
                    setattr(co, a, 0.0)
                elif sv == -s:
                    # landed on the wrong side of the mirror plane: clamp onto the plane
                    co = to_planes(co, (a,))
            return co

        # boundary normals come from the source under each boundary vert (target faces may be missing or
        # flipped), blended with the same weights as positions to give each new vert a casting direction
        normal_cache = {}
        def source_normal(pt):
            key = ('v', pt.index) if isinstance(pt, BMVert) else ('c', tuple(round(c, 6) for c in pt))
            if key not in normal_cache:
                r = nearest_point_normal_valid_sources(context, M @ pco(pt))
                normal_cache[key] = r[1].normalized() if (r and r[1].length_squared > 0) else None
            return normal_cache[key]

        def make_normal_fn(bmvs):
            known = [ n for v in bmvs if (n := source_normal(v)) is not None ]
            fallback = sum(known, Vector()).normalized() if known else None
            if fallback is not None and fallback.length_squared == 0: fallback = None
            def nrm(pt):
                n = source_normal(pt)
                return n if n is not None else fallback
            return nrm, fallback

        def coons(l, r, b, t, c00, c10, c01, c11, pi, pj):
            # transfinite (Coons) blend: the two rulings minus the bilinear corner term, so every
            # boundary curve is reproduced exactly. v3 averaged the rulings, which pulled interior
            # loops halfway toward the straight chords between corners
            lr = l * (1 - pj) + r * pj
            tb = b * (1 - pi) + t * pi
            bl = c00 * ((1 - pi) * (1 - pj)) + c10 * (pi * (1 - pj)) + c01 * ((1 - pi) * pj) + c11 * (pi * pj)
            return lr + tb - bl

        def guide_direction(bmv, n, along, toward):
            ''' Direction the new side should leave a free corner in, taken from the existing edge
            there that is not selected and not running on along the strip. Usually that edge points
            the other way, into the existing mesh (the hole is open on this side), and the new side
            carries it straight on through the corner. An unselected edge that already heads into
            the hole is followed instead. None if there is no such edge.
            '''
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
                # an edge heading into the hole is an existing side and wins a tie; one heading away
                # is continued through the corner, so its reverse is the guide
                score = dt if dt > 0 else -dt * 0.999
                if score > best_score:
                    best, best_score = (d if dt > 0 else -d), score
            return best

        def blend_pair(na, nb, t):
            if na is None or nb is None: return None
            n = na * (1 - t) + nb * t
            return n.normalized() if n.length_squared > 1e-12 else None

        def blend_normal(*args):
            if any(a is None for a in args[:8]): return None
            n = coons(*args)
            return n.normalized() if n.length_squared > 1e-12 else None

        def smooth_grid(verts, normals, l0, l1, side, cap, fixed, *, cyclic_i=False):
            # Laplacian smoothing of the new verts with the boundary fixed, re-snapped after every pass.
            # Only axes with a neighbor on both sides count, so the open rows of a bridge stay put
            # instead of shrinking inward. A loft wraps around in i, so there every row qualifies.
            for _ in range(smooth_iterations):
                moved = {}
                for i in range(l0):
                    for j in range(l1):
                        k = i * l1 + j
                        if k in fixed: continue
                        acc, n = Vector(), 0
                        if cyclic_i:
                            acc += pco(verts[((i - 1) % l0) * l1 + j]) + pco(verts[((i + 1) % l0) * l1 + j])
                            n += 2
                        elif 0 < i < l0 - 1:
                            acc += pco(verts[(i - 1) * l1 + j]) + pco(verts[(i + 1) * l1 + j])
                            n += 2
                        if 0 < j < l1 - 1:
                            acc += pco(verts[i * l1 + (j - 1)]) + pco(verts[i * l1 + (j + 1)])
                            n += 2
                        if n: moved[k] = acc / n
                for k, co in moved.items():
                    verts[k] = new_point(co, side, normals[k], cap)

        def get_verts(strip, rev=False):
            if len(strip) == 1: return list(strip[0].verts)
            bmvs = [_nonshared_vert(strip[0], strip[1])]
            bmvs += [_shared_vert(e0, e1) for e0, e1 in zip(strip[:-1], strip[1:])]
            bmvs += [_nonshared_vert(strip[-1], strip[-2])]
            if rev: bmvs.reverse()
            return bmvs

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
            # cap the total number of new (snapped) verts so a huge selection can't stall the viewport
            nonlocal n_new
            n_new += count
            if n_new <= MAX_NEW_VERTS: return True
            L.error = 'Patches: selection too large to preview'
            return False

        def derive_loops(dist, avg_len):
            # loops to insert between two facing sides, counted as additions: 0 bridges them
            # with a single band of quads. Mirrors Contours' span methods.
            if settings.span_mode == 'FIXED': return max(0, settings.crosses)
            ref = settings.span_length if settings.span_mode == 'LENGTH' else avg_len
            return max(0, round(dist / max(ref, 1e-9)) - 1)

        def too_noisy(verts, raws, l0, l1, boundary, *, cyclic_i=False):
            noise = _grid_snap_noise([pco(v) for v in verts], raws, l0, l1, cyclic_i=cyclic_i)
            if noise <= MAX_SNAP_NOISE: return False
            # the snapped result bears no relation to the source here, so offer nothing to fill
            return True

        def over_existing_faces(verts, faces):
            ''' True when the patch would sit on top of the mesh rather than fill the empty side of
            its boundary, as when the outline of an island is selected. Every boundary edge already
            has a face on one side; count how many of the new faces land on that same side. '''
            same, other = 0, 0
            for f in faces:
                centre = sum((pco(verts[k]) for k in f), Vector()) / len(f)
                for a, b in zip(f, f[1:] + f[:1]):
                    va, vb = verts[a], verts[b]
                    if not (isinstance(va, BMVert) and isinstance(vb, BMVert)): continue
                    bme = next((e for e in va.link_edges if e.other_vert(va) is vb), None)
                    if bme is None or len(bme.link_faces) != 1: continue
                    mid = (va.co + vb.co) / 2
                    along = (vb.co - va.co).normalized()
                    to_old = bme.link_faces[0].calc_center_median() - mid
                    to_new = centre - mid
                    to_old -= along * to_old.dot(along)
                    to_new -= along * to_new.dot(along)
                    if to_old.length_squared < 1e-14 or to_new.length_squared < 1e-14: continue
                    if to_old.dot(to_new) > 0: same += 1
                    else: other += 1
            return same > other

        def refuse_if_covered(kind, verts, faces, boundary):
            if not over_existing_faces(verts, faces): return False
            return True

        def mouse_side(co_a, co_b, co_mid, out):
            # Sign to give `out` so a wire run steps toward the mouse: +1 keeps it, -1 flips it.
            # Also returns the side of the run's screen-space chord the mouse is on, which is what
            # track_mouse watches for a flip. (1, 0) when the mouse or the view is unknown, so the
            # run keeps whichever side its own geometry gave it.
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

        def emit_rect_grid(sv0, sv1, sv2, sv3, kind):
            # Coons-fill a four-sided region. sv0/sv2 run along i and must be equal length;
            # sv1/sv3 run along j. Sides share endpoints: sv0[0]==sv3[0], sv0[-1]==sv1[0],
            # sv2[0]==sv3[-1], sv2[-1]==sv1[-1].
            l0, l1 = len(sv0), len(sv1)
            if l0 < 2 or l1 < 2: return True
            if not budget(max(0, (l0 - 2) * (l1 - 2))): return False

            boundary = sv0 + sv1 + sv2 + sv3
            side, cap = shape_side(boundary), shape_cap(boundary)
            nrm, _ = make_normal_fn(boundary)
            # corners: (i=0,j=0) (i=end,j=0) (i=0,j=end) (i=end,j=end)
            c00, c10, c01, c11 = sv0[0], sv0[-1], sv2[0], sv2[-1]
            verts, normals, raws, edges, faces, fixed = [], [], [], [], [], set()
            for i in range(l0):
                l, r = sv0[i], sv2[i]
                for j in range(l1):
                    t, b = sv1[j], sv3[j]
                    if i == 0 or i == l0 - 1 or j == 0 or j == l1 - 1:
                        fixed.add(i * l1 + j)
                        verts += [b if i == 0 else t if i == l0 - 1 else l if j == 0 else r]
                        normals += [None]; raws += [None]
                    else:
                        pi, pj = i / (l0 - 1), j / (l1 - 1)
                        n = blend_normal(nrm(l), nrm(r), nrm(b), nrm(t), nrm(c00), nrm(c10), nrm(c01), nrm(c11), pi, pj)
                        co = coons(pco(l), pco(r), pco(b), pco(t), pco(c00), pco(c10), pco(c01), pco(c11), pi, pj)
                        verts += [new_point(co, side, n, cap)]
                        normals += [n]; raws += [co]
            if too_noisy(verts, raws, l0, l1, boundary): return True
            smooth_grid(verts, normals, l0, l1, side, cap, fixed)
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(1, l0-1) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1, l1-1) for i in range(l0-1)]
            faces += [((i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1)) for i in range(l0-1) for j in range(l1-1)]
            if refuse_if_covered(kind, verts, faces, boundary): return True
            # boundary verts that do not exist yet belong to a side this fill is creating, as in an
            # uneven bridge. They read as missing corners unless they are drawn.
            open_idx = sorted(k for k in fixed if not isinstance(verts[k], BMVert))
            add_previz(kind, verts, edges, faces, open_idx)
            return True

        def cycle_bmvs(bmes):
            # ordered verts around a closed edge cycle, or None if these edges aren't one
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

        def emit_loft(bmvs_a, bmvs_b, axis):
            # bridge two closed loops of equal count: same grid as the I strip, wrapped around
            bmvs0, bmvs1 = list(bmvs_a), list(bmvs_b)
            n = len(bmvs0)

            # wind both loops the same way around the axis, or every quad comes out crossed
            n0 = compute_n([v.co for v in bmvs0])
            n1 = compute_n([v.co for v in bmvs1])
            if n0.length_squared > 1e-12 and n0.dot(axis) < 0: bmvs0.reverse()
            if n1.length_squared > 1e-12 and n1.dot(axis) < 0: bmvs1.reverse()

            # Rotate loop B onto loop A. Closest-vertex pairing alone twists the bridge when the
            # loops differ in size or sit off-axis, so matching sharp corners gets a say too, the
            # way Contours aligns a cut's corners to the ring it lands on.
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
            l0, l1 = n, loops + 2
            L.has_bridge = True
            L.has_loft = True
            L.loops_last = loops
            if not budget(l0 * max(0, l1 - 2)): return False

            boundary = bmvs0 + bmvs1
            side, cap = shape_side(boundary), shape_cap(boundary)
            nrm, _ = make_normal_fn(boundary)
            verts, normals, raws, edges, faces, fixed = [], [], [], [], [], set()
            for i in range(l0):
                v0, v1 = bmvs0[i], bmvs1[i]
                for j in range(l1):
                    if j == 0 or j == l1 - 1:
                        fixed.add(i * l1 + j)
                        verts += [v0 if j == 0 else v1]
                        normals += [None]; raws += [None]
                    else:
                        pj = j / (l1 - 1)
                        nn = blend_pair(nrm(v0), nrm(v1), pj)
                        co = v0.co * (1 - pj) + v1.co * pj
                        verts += [new_point(co, side, nn, cap)]
                        normals += [nn]; raws += [co]
            if too_noisy(verts, raws, l0, l1, boundary, cyclic_i=True): return True
            smooth_grid(verts, normals, l0, l1, side, cap, fixed, cyclic_i=True)
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(l0) for j in range(l1-1)]
            edges += [(i*l1+j, ((i+1) % l0)*l1+j) for j in range(1, l1-1) for i in range(l0)]
            faces += [(i*l1+(j+0), ((i+1) % l0)*l1+(j+0), ((i+1) % l0)*l1+(j+1), i*l1+(j+1))
                      for i in range(l0) for j in range(l1-1)]
            if refuse_if_covered('loft', verts, faces, boundary): return True
            add_previz('loft', verts, edges, faces)
            return True

        def emit_grid_fill(bmvs, kind):
            # Blender's Grid Fill always produces a span x (half - span) rectangle; it just picks
            # where the four corners sit around the loop. Do the same and hand it to the Coons
            # fill, so an unequal-sided or non-quadrilateral loop still previews and snaps.
            n = len(bmvs)
            cos = [pco(v) for v in bmvs]
            if n < 4:
                return True
            if n % 2:
                # an odd loop cannot be closed with quads alone
                return True
            half = n // 2

            # corners should land where the loop actually bends
            sharp = _turn_sharpness(cos)
            def side_mid(a, cnt):
                # middle of the side running cnt edges from vert a
                k = a + cnt // 2
                return cos[k % n] if cnt % 2 == 0 else (cos[k % n] + cos[(k + 1) % n]) / 2

            # Every distinct split is a solution: for each span, the corner placement scoring best.
            # Ranked best first, so Solution 1 is the automatic choice and the rest flip through the
            # others in order of merit.
            ranked, seen = [], set()
            for span in range(1, half):
                best = None
                for off in range(n):
                    # Cell size measured ACROSS the patch: the distance between opposite sides divided
                    # by the quads bridging it. Edge lengths along the boundary cannot tell a 1x6
                    # strip from a 3x4 grid on a round loop; the distance across can.
                    w = (side_mid(off + span, half - span) - side_mid(off + half + span, half - span)).length / span
                    h = (side_mid(off, span) - side_mid(off + half, span)).length / (half - span)
                    # 1.0 means the quads come out square; corners at real bends are worth a lot more
                    aspect = max(w, h) / max(1e-9, min(w, h))
                    corner = sum(sharp[(off + k) % n] for k in (0, span, half, half + span))
                    score = aspect - 2.0 * corner
                    if best is None or score < best[0]: best = (score, span, off)
                if best is None: continue
                # span s and span half-s at matching offsets are the same four corners: one solution
                corners = frozenset((best[2] + k) % n for k in (0, span, half, half + span))
                if corners in seen: continue
                seen.add(corners)
                ranked.append(best)
            if not ranked: return True
            # ties go to the squarest count rather than the smallest span
            ranked.sort(key=lambda r: (round(r[0], 6), abs(r[1] - half / 2)))
            L.grid_ranked = [ (span, off) for _, span, off in ranked ]

            # a new selection always starts at Solution 1; the property is brought back to 1 to match
            sig = L.selection_signature(bm, sel_edges)
            fresh = sig != L.grid_sig
            L.grid_sig = sig
            if fresh:
                choice = 1
                if settings.solution != 1: L.push_solution(1, settings.solution)
            elif L.solution_pending is not None and settings.solution == L.solution_stale:
                choice = L.solution_pending                   # not yet landed in the property
            else:
                L.solution_pending = L.solution_stale = None  # the property has moved on: it drives
                choice = settings.solution
            span, off = L.grid_ranked[(choice - 1) % len(L.grid_ranked)]
            off = (off + settings.offset) % n     # the user's offset rotates the chosen corners
            L.has_grid = True
            L.grid_last = (span, settings.offset)

            def side_verts(a, cnt):
                return [ bmvs[(a + k) % n] for k in range(cnt + 1) ]
            sv0 = side_verts(off, span)                          # c00 -> c10
            sv1 = side_verts(off + span, half - span)            # c10 -> c11
            sv2 = side_verts(off + half, span)[::-1]             # c01 -> c11
            sv3 = side_verts(off + half + span, half - span)[::-1]   # c00 -> c01
            return emit_rect_grid(sv0, sv1, sv2, sv3, kind)

        def cycle_bmes(bmvs):
            # the edges joining a closed run of verts, in the same order; None if any is missing
            out = []
            for a, b in zip(bmvs, bmvs[1:] + bmvs[:1]):
                bme = next((e for e in a.link_edges if e.other_vert(a) is b), None)
                if bme is None: return None
                out.append(bme)
            return out

        def emit_offset(sv, bmes, *, cyclic=False):
            # Rows of quads pushed out from a run of boundary edges that has nothing to fill: an open
            # strip with no partner to bridge to, or a closed loop whose inside is already faces. Each
            # vert steps the way the quads already on the run lean (their edge leaving the run there),
            # or straight out across the run where there is no quad to follow. On an open run, an end
            # that turns a corner onto an existing open edge is not extruded at all: the row welds onto
            # the far vert of that edge, so stepping along a boundary knits into what is there already.
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
            nrm, _ = make_normal_fn(sv)
            perps, prev_n = [], None
            for i, v in enumerate(sv):
                nv = nrm(v)
                if nv is None:
                    bmfs = [ bmf for bme in v.link_edges if bme in run_edges for bmf in bme.link_faces ]
                    nv = next((f.normal for f in bmfs if f.normal.length_squared > 0), None)
                if nv is None: return True     # no source and no face: nothing to lean on
                # the normal is what can flip over, when two verts of the run find opposite faces of a
                # thin surface. Keeping it continuous keeps the whole row on one side, while leaving a
                # sharply turning run free to swing its perp round with the turn
                if prev_n is not None and nv.dot(prev_n) < 0: nv = -nv
                prev_n = nv
                p = along[i].cross(nv)
                if p.length_squared < 1e-12: return True
                perps.append(p.normalized())

            # Which side is out, settled one vert at a time: away from the faces that vert's own run
            # edges carry. Every boundary vert knows this for itself. A single vote for the whole run
            # instead trusts the perps to agree end to end, and around a form they need not: where a
            # run crosses a crease the perp can come out the other way, and the losing half of the
            # vote then steps back over the mesh it came from, inside out.
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
                mid_i = n // 2
                side_sign, s_mouse = mouse_side(cos[0], cos[mid_i if cyclic else -1], cos[mid_i],
                                                perps[mid_i] * d_mean)
                if s_mouse and not cyclic: L.wire_runs.append((cos[0].copy(), cos[-1].copy(), s_mouse))
                if side_sign < 0: perps = [ -p for p in perps ]

            # direction per vert: the quad's edge leaving the run there, averaged when two quads meet.
            # A side edge running along the run, a non-quad, or a quad on the far side falls back to the perp
            dirs = []
            for i, v in enumerate(sv):
                acc = Vector()
                for bme in (bmes[(i - 1) % n] if (cyclic or i > 0) else None,
                            bmes[i] if (cyclic or i < n - 1) else None):
                    if bme is None: continue
                    for bmf in bme.link_faces:
                        if len(bmf.verts) != 4: continue
                        side_e = next((fe for fe in bmf.edges if fe is not bme and v in fe.verts), None)
                        if side_e is None: continue     # both of the quad's edges here are run edges
                        d = v.co - side_e.other_vert(v).co
                        if d.length_squared < 1e-14: continue
                        d.normalize()
                        if abs(d.dot(along[i])) > GUIDE_MAX_ALONG: continue
                        if d.dot(perps[i]) <= 0: continue
                        acc += d
                dirs.append(acc.normalized() if acc.length_squared > 1e-12 else perps[i])

            # a vert where the run itself turns has to reach further than one where it runs straight,
            # or the new row pinches in at every corner instead of staying parallel
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
                # candidate rails leaving a vert: unselected, still open, and not folding back into
                # the face the run (or the rail so far) already occupies there
                skip = { fe for bme in skip_faces_of for bmf in bme.link_faces for fe in bmf.edges }
                for bme in bmv.link_edges:
                    if bme in sel_edges or bme.hide or len(bme.link_faces) >= 2: continue
                    if bme in skip: continue
                    yield bme, bme.other_vert(bmv)

            def weld_target(i_end, i_prev, used):
                # An open edge leaving the end of the run whose far vert lies outward. It counts as a
                # corner either topologically (a concave boundary vert) or by bending past Split Angle,
                # which is the same test the strips themselves were split with.
                v = sv[i_end]
                arrive = v.co - sv[i_prev].co
                if arrive.length_squared < 1e-14: return None
                arrive.normalize()
                topo = bool(v.link_faces) and is_bmvert_corner(v)
                out = dirs[i_end]
                best, best_dot = None, 0.0
                for _bme, w in open_edges_at(v, (bmes[-1] if i_end == n - 1 else bmes[0],)):
                    if w in run_verts or w in used: continue
                    d = w.co - v.co
                    if d.length_squared < 1e-14: continue
                    d = d.normalized()
                    if d.dot(out) <= 0: continue
                    if not topo and _angle_deg(-arrive, d) >= min_angle: continue
                    if d.dot(out) > best_dot: best, best_dot = w, d.dot(out)
                return best

            def rail_next(bmv, from_co, came_along, used):
                # Once a row has welded onto a rail, the rows after it keep following that rail for as
                # long as it runs, rather than stepping free of the mesh it just joined. Whether this
                # was a corner was settled at the run; from here it is simply the straightest way on.
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
            W0 = W1 = None
            if not cyclic:
                W0 = weld_target(0, 1, used_welds)
                W1 = weld_target(n - 1, n - 2, used_welds)
                if W0 is not None and W0 is W1: return True   # both ends fold onto one vert: not a row of quads
            row0_welds = { i: w for i, w in ((0, W0), (n - 1, W1)) if w is not None }

            def row_base(prev_cos, welds_k):
                # How far and which way each vert of the previous row steps to make the next one. A
                # welded end has to land exactly on its weld, so its own offset is used unmitered and
                # the part its direction could not account for is carried across the run, fading out.
                if not welds_k:
                    return [ dirs[i] * (d_mean * miter[i]) for i in range(n) ]
                fr = _cumulative_fracs(prev_cos)
                scale = lambda i, l: dirs[i] * (l * (1.0 if i in welds_k else miter[i]))
                if len(welds_k) == 1:
                    i_w, w = next(iter(welds_k.items()))
                    D = w.co - prev_cos[i_w]
                    r = D - dirs[i_w] * D.length
                    return [ scale(i, D.length) + r * (fr[i] if i_w else 1 - fr[i]) for i in range(n) ]
                D0, D1 = welds_k[0].co - prev_cos[0], welds_k[n - 1].co - prev_cos[-1]
                r0, r1 = D0 - dirs[0] * D0.length, D1 - dirs[-1] * D1.length
                return [ scale(i, D0.length * (1 - fr[i]) + D1.length * fr[i]) + r0 * (1 - fr[i]) + r1 * fr[i]
                         for i in range(n) ]

            def trace_boundary_loop(limit):
                # Walk the open boundary out from the far end of the run and round, looking for the
                # near end. If it comes back, the run, its two rails and the far side are all pieces
                # of one closed loop, and counting round it says exactly when a step arrives opposite.
                loop, seen, came, cur = list(sv), set(sv), None, sv[-1]
                while len(loop) < limit:
                    step_to = [ w for bme, w in open_edges_at(cur, ())
                                if bme not in run_edges and w is not came ]
                    if len(step_to) != 1: return None      # a fork or a dead end: not a simple hole
                    w = step_to[0]
                    if w is sv[0]: return loop             # closed
                    if w in seen: return None              # pinched: it met itself, not the far side
                    loop.append(w); seen.add(w)
                    came, cur = cur, w
                return None

            # Stepping across a hole runs out of hole. Beyond the row that lands opposite there is
            # nothing left to fill, so stop there; when the far side has as many edges as the run, that
            # row IS the far side and the whole thing welds shut rather than doubling it up.
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
                        # The walk goes round whatever boundary the run sits on, which for a strip is
                        # its own other side with solid mesh in between. Only a far side lying the way
                        # the run is stepping is one it is actually closing on.
                        if (sum((v.co for v in far), Vector()) / len(far) - here).dot(ahead) <= 0: break
                        if rest == nseg:
                            far_row = list(reversed(far))
                            steps = k
                        else:
                            # the two sides cannot meet in quads: stop short and leave the gap, which
                            # is a patch the artist can select both sides of and fill
                            steps = k - 1
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

            # Each row steps from the one before it and is snapped there, so a run of steps follows the
            # source round a curve instead of shooting off along the first row's straight direction, and
            # each row asks again whether its ends have a rail left to weld onto.
            rows, prev_row, prev_cos, prev_prev_cos = [], list(sv), list(cos), None
            for k in range(steps):
                if k == 0:
                    welds_k = dict(row0_welds)
                else:
                    welds_k = {}
                    if not cyclic:
                        for i_end in (0, n - 1):
                            anchor = prev_row[i_end]
                            if not isinstance(anchor, BMVert): continue   # this end stepped free already
                            came = next((e for e in anchor.link_edges
                                         if (e.other_vert(anchor).co - prev_prev_cos[i_end]).length_squared < 1e-12), None)
                            w = rail_next(anchor, prev_prev_cos[i_end], came, used_welds)
                            if w is not None: welds_k[i_end] = w
                        if len(welds_k) == 2 and welds_k[0] is welds_k[n - 1]: welds_k = {}
                used_welds |= set(welds_k.values())

                base = row_base(prev_cos, welds_k)
                if max(b.length for b in base) < 1e-9: return True

                if k == 0 and (far_row is None or steps != 1):
                    # Before making a vert, ask what the cursor pick would find if it hovered where
                    # that vert is about to land: existing points that make a good quad with this
                    # run edge are used instead of extruding over them. Only the first row can be
                    # judged this way - later rows stand on verts that are not in the mesh yet, so
                    # nothing can be said about their edges or faces - and it is the row that meets
                    # points the artist dropped. The corner welds above are already decided and
                    # count as known corners here.
                    intended = [ prev_cos[i] + base[i] for i in range(n) ]
                    proposals = {}      # run index -> [(cost, vert)]
                    for a in range(nseg):
                        b = nxt(a)
                        # the quad is sv[a], sv[b], corner at b, corner at a; open corners go last so
                        # _complete_quad can append them, which may mean rotating the ring
                        ring = [sv[a], sv[b], welds_k.get(b), welds_k.get(a)]
                        open_i = [ i for i, c in zip((b, a), ring[2:]) if c is None ]
                        if not open_i: continue
                        slots = []
                        for i in open_i:
                            r = WELD_FIT_RADIUS * base[i].length
                            slots.append([ w for w in L._candidates_near(context, bm, intended[i], r)
                                           if w not in run_verts and w not in used_welds ])
                        if not all(slots): continue
                        if len(open_i) == 1 and open_i[0] == b:
                            known = [ring[3], sv[a], sv[b]]     # rotate: the open corner is last
                        else:
                            known = [ c for c in ring if c is not None ]
                        res = _complete_quad(bm, known, slots, min_squareness=WELD_FIT_MIN_SQUARENESS)
                        if res is None: continue
                        verts_q, cost = res
                        for i, w in zip(open_i, verts_q[len(known):]):
                            proposals.setdefault(i, []).append((cost, w))
                    if proposals:
                        # each vert takes the best quad proposed for it, and no vert is landed on twice
                        chosen, taken = {}, set()
                        for i, opts in sorted(proposals.items(), key=lambda kv: min(kv[1])[0]):
                            for cost, w in sorted(opts, key=lambda cw: cw[0]):
                                if w in taken: continue
                                chosen[i] = w
                                taken.add(w)
                                break
                        # a segment whose quad no longer holds up with the corners as resolved
                        # (a neighbour's choice won) lets go of its welds and steps free
                        for a in range(nseg):
                            b = nxt(a)
                            if a not in chosen and b not in chosen: continue
                            def corner(i):
                                return chosen[i] if i in chosen else welds_k[i] if i in welds_k else intended[i]
                            q = [sv[a], sv[b], corner(b), corner(a)]
                            if _quad_shape_ok([ _pco(c) for c in q ]) is None or not _quad_is_placeable(bm, q):
                                chosen.pop(a, None)
                                chosen.pop(b, None)
                        for i, w in chosen.items():
                            welds_k[i] = w
                            base[i] = w.co - prev_cos[i]
                        used_welds |= set(chosen.values())

                # A couple of this row's own steps, in world units: how far a new vert may be pulled
                # onto the source before the hit counts as an unrelated surface. Averaged, not maxed:
                # a mitered corner reaches three times as far as the rest of the row and would other-
                # wise set the cap for all of it. Past the cap the vert stays where the step put it,
                # which off the edge of the source is better than being dragged back onto it.
                cap = SNAP_CAP_EDGES * max(span_w, sum((M3 @ b).length for b in base) / n)

                if far_row is not None and k == steps - 1:
                    row, missed = list(far_row), []   # the last row IS the far side of the hole
                else:
                    row, missed = [], []
                    for i in range(n):
                        if i in welds_k:
                            row.append(welds_k[i])
                            continue
                        nb = source_normal(prev_row[i]) or nrm(sv[i])
                        pt = new_point(prev_cos[i] + base[i], side, nb, cap, ray=False, missed=missed)
                        if not cyclic and i in (0, n - 1): pt = to_planes(pt, sym_axes(cos[i]) - run_axes)
                        row.append(pt)
                row_cos = [ pco(pt) for pt in row ]
                if far_row is None or k != steps - 1:
                    # A row that found nothing to snap to has stepped off the end of the source and is
                    # hanging in space. A concave run closes on itself as it steps. A run that has run
                    # out of source stops advancing at all. Each leaves the quads from here on unusable:
                    # keep what is good and stop. (With no source there is nothing to land on, so the
                    # first of these cannot apply.)
                    if ((sources and missed)
                            or folds_back(prev_cos, row_cos) or stalled(prev_cos, row_cos, base)):
                        steps = k
                        break
                rows.append(row)
                prev_row, prev_prev_cos, prev_cos = row, prev_cos, row_cos

            if not rows: return True        # the very first step already folded back on itself
            # no refuse_if_covered here: the step is aimed away from the run's own faces by
            # construction, so there is no side for it to land on the wrong one of
            verts = list(sv) + [ pt for row in rows for pt in row ]
            faces, edges = [], []
            for k in range(1, steps + 1):
                for i in range(nseg):
                    j = nxt(i)
                    faces.append(((k - 1) * n + i, (k - 1) * n + j, k * n + j, k * n + i))

            def is_new_edge(a, b):
                # a rung or row edge that already exists is drawn by Blender, not by the preview
                va, vb = verts[a], verts[b]
                if not (isinstance(va, BMVert) and isinstance(vb, BMVert)): return True
                return not any(bme.other_vert(va) is vb for bme in va.link_edges)
            for k in range(1, steps + 1):
                edges += [ (k * n + i, k * n + nxt(i)) for i in range(nseg)
                           if is_new_edge(k * n + i, k * n + nxt(i)) ]
                edges += [ ((k - 1) * n + i, k * n + i) for i in range(n)
                           if is_new_edge((k - 1) * n + i, k * n + i) ]

            L.has_offset = True
            outer = range(steps * n, (steps + 1) * n)
            if steps > 1:   # the default needs no announcing; the count appears once it is scrolled
                L.labels.append((str(steps), [ sum((pco(verts[k]) for k in outer), Vector()) / n ]))
            add_previz('offset', verts, edges, faces,
                       [ k for k in outer if not isinstance(verts[k], BMVert) ], outer)
            return True

        def emit_quad_strip(q, kind):
            # One quad on four corners (BMVerts, or a Vector for a corner the fill creates), cut into a
            # strip of `crosses + 1` quads across its longer dimension. Cuts default to none; they are
            # the redo panel's and Ctrl+Scroll's knob, the count a bridge has. Interior points are
            # blended between the two short sides and snapped, exactly as a bridge's are.
            cos = [ pco(v) for v in q ]
            la = ((cos[1] - cos[0]).length + (cos[2] - cos[3]).length) / 2   # sides 0-1 and 3-2
            lb = ((cos[3] - cos[0]).length + (cos[2] - cos[1]).length) / 2   # sides 0-3 and 1-2
            if la >= lb: sv0, sv1 = [q[0], q[3]], [q[1], q[2]]   # the strips are the short sides
            else:        sv0, sv1 = [q[0], q[1]], [q[3], q[2]]
            gap = max(1, settings.crosses + 1)
            l0, l1 = 2, gap + 1
            if not budget(l0 * (l1 - 2)): return False
            existing = [ v for v in q if isinstance(v, BMVert) ]
            side, cap = shape_side(existing), shape_cap(existing)
            nrm, _ = make_normal_fn(existing)

            verts, normals, fixed = [], [], set()
            for i in range(l0):
                for j in range(l1):
                    if j == 0 or j == l1 - 1:
                        fixed.add(i * l1 + j)
                        verts.append(sv0[i] if j == 0 else sv1[i])
                        normals.append(None)
                    else:
                        pj = j / (l1 - 1)
                        n = blend_pair(nrm(sv0[i]), nrm(sv1[i]), pj)
                        co = pco(sv0[i]) * (1 - pj) + pco(sv1[i]) * pj
                        verts.append(new_point(co, side, n, cap))
                        normals.append(n)
            if l1 > 2: smooth_grid(verts, normals, l0, l1, side, cap, fixed)

            def is_new(a, b):
                return _bmedge_between(verts[a], verts[b]) is None
            edges = [ (i * l1 + j, i * l1 + j + 1) for i in range(l0) for j in range(l1 - 1) if is_new(i * l1 + j, i * l1 + j + 1) ]
            edges += [ (j, l1 + j) for j in range(l1) if is_new(j, l1 + j) ]
            faces = [ (j, l1 + j, l1 + j + 1, j + 1) for j in range(l1 - 1) ]
            L.has_quad = True
            add_previz(kind, verts, edges, faces, [ k for k in sorted(fixed) if not isinstance(verts[k], BMVert) ])
            return True

        def emit_corner_quad(bmv):
            # F2's quad from a vertex: two open edges leaving a corner are two sides of a quad, and the
            # fourth corner is the parallelogram completion of them. Edges that are already two sides of
            # one face have no gap between them to fill, so they are not a pair. The cursor picks when
            # there is more than one way to pair them up, as F2 does.
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
                    # with no cursor to choose by, the squarest corner makes the best quad
                    score = abs(da.normalized().dot(db.normalized()))
                if best is None or score < best[0]: best = (score, va, vb, co)
            if best is None: return True
            _, va, vb, co = best
            da, db = va.co - bmv.co, vb.co - bmv.co

            # where two strips meet at this vert the fourth corner is already there; use it rather
            # than laying a second vert on top of it
            nbrs_b = { bme.other_vert(vb) for bme in vb.link_edges }
            corner = next((w for bme in va.link_edges
                           if (w := bme.other_vert(va)) is not bmv and w in nbrs_b), None)
            if corner is None:
                # or a point the artist has already dropped about where the corner would go: the
                # same test the cursor pick applies, so a good fit is used and a poor one is not
                r = WELD_FIT_RADIUS * (da.length + db.length) / 2
                cands = [ w for w in L._candidates_near(context, bm, co, r) if w not in (va, vb, bmv) ]
                res = _complete_quad(bm, [va, bmv, vb], [cands], min_squareness=WELD_FIT_MIN_SQUARENESS) if cands else None
                if res is not None: corner = res[0][3]
            if corner is None:
                if not budget(1): return False
                boundary = [va, bmv, vb]
                nrm, _ = make_normal_fn(boundary)
                cap = SNAP_CAP_EDGES * max((M @ va.co - M @ bmv.co).length,
                                           (M @ vb.co - M @ bmv.co).length)
                corner = new_point(co, shape_side(boundary), nrm(bmv), cap, ray=False)

            verts = [va, bmv, vb, corner]
            if len({ id(v) for v in verts }) != 4: return True

            # Hold this to the same standard as a quad picked by the cursor: convex on screen, a
            # shape worth having in 3D, and legal against the mesh (no corner opening out over faces
            # that are already there, no side on the faced side of an edge). Without these a lone
            # vert would happily offer a dart or a sliver.
            q = [ M @ pco(v) for v in verts ]
            if _quad_shape_ok(q) is None: return True
            if rgn and r3d:
                pts = [ location_3d_to_region_2d(rgn, r3d, co) for co in q ]
                if all(pts) and not _is_convex_2d(pts): return True
            if not _quad_is_placeable(bm, verts): return True

            return emit_quad_strip(verts, 'corner')

        ###################
        # closed cycles: loft a matched pair, else fill each on its own

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
                        # make sure each strip is in the correct order
                        if sv0[-1] not in sv1: sv0.reverse()
                        if sv1[-1] not in sv2: sv1.reverse()
                        if sv2[-1] not in sv1: sv2.reverse()
                        if sv3[-1] not in sv2: sv3.reverse()
                        if not emit_rect_grid(sv0, sv1, sv2, sv3, 'rect'): break
                        tried = True
                if not tried:
                    # unequal opposite sides, or a loop that isn't four-sided: fall back to a grid fill
                    if not emit_grid_fill(bmvs, 'grid'): break
                if len(L.previz) > before: continue
                # Nothing to fill inside this loop, because the inside is already faces (or the loop
                # cannot be gridded at all). Step it outward instead, growing the shape by a ring
                bmes = cycle_bmes(bmvs)
                if bmes and not emit_offset(bmvs, bmes, cyclic=True): break

        # L
        for shape in shapes['L']:
            s0, s1 = shape
            sv0, sv1 = get_verts(s0), get_verts(s1)
            l0, l1 = len(sv0), len(sv1)

            # make sure each strip is in the correct order
            if sv0[-1] not in sv1: sv0.reverse()
            if sv1[0] not in sv0: sv1.reverse()

            symmetry0 = sym_axes(sv0[0].co)
            symmetry1 = sym_axes(sv1[-1].co)
            if symmetry0 and symmetry1:
                # both are at symmetry... artist is trying to fill a triangle
                # we cannot do that, yet, so bail!
                continue
            if not budget((l0 - 1) * (l1 - 1)): break

            boundary = sv0 + sv1
            side, cap = shape_side(boundary), shape_cap(boundary)
            nrm, _ = make_normal_fn(boundary)
            n00, n10, n11 = nrm(sv0[0]), nrm(sv0[-1]), nrm(sv1[-1])

            c00, c10, c11 = sv0[0].co, sv0[-1].co, sv1[-1].co

            # Fourth corner, first guess. The flat parallelogram, c00 + (c11 - c10), leaves a curved
            # surface. Each known strip's end normals fit a sphere (the Interpolate Loops idea from
            # Relax), and the rotation about that sphere carrying one end of the strip to the other,
            # applied to the far corner of the other strip, is the same completion bent to the surface.
            guess_a = _bend_along(c10, n10, c00, n00, c11)     # c11 carried the way sv0 bends
            guess_b = _bend_along(c10, n10, c11, n11, c00)     # c00 carried the way sv1 bends

            n01 = None
            if n00 is not None and n11 is not None:
                n01 = n00 + n11
                n01 = n01.normalized() if n01.length_squared > 1e-12 else n00
            c01 = to_planes(new_point((guess_a + guess_b) / 2, side, n01, cap), symmetry0 | symmetry1)
            n01 = source_normal(c01) or n01

            # The sides, thought of as curves. Each one's handle at the attached corner follows the
            # existing edge there, so the new side carries the mesh flow on through the corner, and
            # its handle at the fourth corner mirrors that, so the side bows evenly instead of
            # curling. The corner itself stays where the curvature estimate above put it: letting
            # the curves pull it about drove it out into a needle. A corner without an existing edge
            # keeps the sphere arc.
            guide_r = guide_direction(sv1[-1], n11, (c11 - sv1[-2].co).normalized(), guess_a - c11)
            guide_b = guide_direction(sv0[0],  n00, (sv0[1].co - c00).normalized(),  guess_b - c00)
            fracs_r = _cumulative_fracs([sv0[k].co for k in range(l0 - 1, -1, -1)])   # from c11 outward
            fracs_b = _cumulative_fracs([v.co for v in sv1])                          # from c00 outward

            # A side whose tangent leans into the patch swoops inward, and two such sides meet the
            # parallelogram corner in a needle: bring the corner in along each chord by the lean. A
            # tangent leaning outward bows outward and the corner is already right, so no push.
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
                # points along the mirrored curve at the given fractions, with the normal carried along
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

            verts, normals, raws, edges, faces, fixed = [], [], [], [], [], set()
            for i in range(l0):
                for j in range(l1):
                    if i == l0 - 1 or j == 0:
                        fixed.add(i * l1 + j)
                        verts += [sv1[j] if i == l0 - 1 else sv0[i]]
                        normals += [None]; raws += [None]
                    else:
                        l, r = sv0[i].co, side_r[i]
                        t, b = sv1[j].co, side_b[j]
                        pi, pj = i / (l0 - 1), j / (l1 - 1)
                        nl, nt = nrm(sv0[i]), nrm(sv1[j])
                        n = blend_normal(nl, nl, nt, nt, n00, n10, n01, n11, pi, pj)
                        blended = coons(l, r, b, t, c00, c10, c01, c11, pi, pj)
                        point = new_point(blended, side, n, cap)
                        if i == 0:      point = to_planes(point, symmetry0)
                        if j == l1 - 1: point = to_planes(point, symmetry1)
                        raws += [blended]
                        verts += [point]
                        normals += [n]
            if too_noisy(verts, raws, l0, l1, boundary): continue
            smooth_grid(verts, normals, l0, l1, side, cap, fixed)
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(l0-1) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1, l1) for i in range(l0-1)]
            faces += [((i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1)) for i in range(l0-1) for j in range(l1-1)]
            if refuse_if_covered('L', verts, faces, boundary): continue
            add_previz('L', verts, edges, faces)

        # C
        for shape in shapes['C']:
            s0, s1, s2 = shape
            c0, c1, c2 = map(len, shape)
            if c0 != c2:
                continue
            sv0, sv1, sv2 = get_verts(s0), get_verts(s1), get_verts(s2, True)
            l0, l1 = len(sv0), len(sv1)
            if not budget((l0 - 1) * (l1 - 2)): break

            # make sure each strip is in the correct order
            if sv0[-1] not in sv1: sv0.reverse()
            if sv1[-1] not in sv2: sv1.reverse()
            if sv2[-1] not in sv1: sv2.reverse()

            symmetry0 = sym_axes(sv0[0].co)
            symmetry2 = sym_axes(sv2[0].co)
            use_symmetry = (symmetry0 == symmetry2)

            # the missing fourth side is the middle strip translated by the end strips' offsets
            off0, off2 = sv0[0].co - sv0[-1].co, sv2[0].co - sv2[-1].co
            boundary = sv0 + sv1 + sv2
            side, cap = shape_side(boundary), shape_cap(boundary)
            nrm, _ = make_normal_fn(boundary)
            c00, c10, c01, c11 = sv0[0], sv0[-1], sv2[0], sv2[-1]
            n00, n10, n01, n11 = nrm(c00), nrm(c10), nrm(c01), nrm(c11)

            verts, normals, raws, edges, faces, fixed = [], [], [], [], [], set()
            for i in range(l0):
                for j in range(l1):
                    if i == l0 - 1 or j == 0 or j == l1 - 1:
                        fixed.add(i * l1 + j)
                        verts += [sv1[j] if i == l0 - 1 else sv0[i] if j == 0 else sv2[i]]
                        normals += [None]; raws += [None]
                    else:
                        pi, pj = i / (l0 - 1), j / (l1 - 1)
                        off = off0 * (1 - pj) + off2 * pj
                        l, r = sv0[i].co, sv2[i].co
                        t, b = sv1[j].co, sv1[j].co + off
                        nb = None
                        if n00 is not None and n01 is not None:
                            nb = n00 * (1 - pj) + n01 * pj
                        n = blend_normal(nrm(sv0[i]), nrm(sv2[i]), nb, nrm(sv1[j]), n00, n10, n01, n11, pi, pj)
                        blended = coons(l, r, b, t, c00.co, c10.co, c01.co, c11.co, pi, pj)
                        raws += [blended]
                        point = new_point(blended, side, n, cap)
                        if use_symmetry and i == 0: point = to_planes(point, symmetry0)
                        verts += [point]
                        normals += [n]
            if too_noisy(verts, raws, l0, l1, boundary): continue
            smooth_grid(verts, normals, l0, l1, side, cap, fixed)
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(l0-1) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1, l1-1) for i in range(l0-1)]
            faces += [((i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1)) for i in range(l0-1) for j in range(l1-1)]
            if refuse_if_covered('C', verts, faces, boundary): continue
            add_previz('C', verts, edges, faces)

        # I: bridge pairs of parallel strips
        # TODO (from v3): check sides to make sure that we aren't creating geometry on a side that already has geometry!
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
                # make sure the I strips are good candidates for bridging
                if _angle_deg(dir0, (sv1[0].co - sv0[0].co).normalized()) < 45: continue
                if _angle_deg(dir1, (sv0[0].co - sv1[0].co).normalized()) < 45: continue
                dist = min((v0.co - v1.co).length for v0 in sv0 for v1 in sv1)
                if best_sv1 and best_dist < dist: continue
                best_sv1 = sv1
                best_dist = dist
                best_i1 = i1
            if not best_sv1: continue
            # both strips are spoken for even if this bridge is refused below: the artist lined two
            # strips up asking for a bridge, not for two of them to step outward on their own
            bridged |= {i0, best_i1}
            sv1, dist = best_sv1, best_dist
            avg0 = (sv0[0].co - sv0[-1].co).length / max(1, len(sv0) - 1)
            avg1 = (sv1[0].co - sv1[-1].co).length / max(1, len(sv1) - 1)
            gap = derive_loops(dist, max(avg0, avg1)) + 1    # edges across the gap
            L.has_bridge = True
            L.loops_last = gap - 1

            boundary = sv0 + sv1
            side, cap = shape_side(boundary), shape_cap(boundary)
            nrm, _ = make_normal_fn(boundary)

            if len(sv0) != len(sv1):
                # Uneven sides. The two sides this fill is about to create close the region into a
                # loop with four corners, so it is the same problem as an uneven enclosed patch:
                # build the loop and hand it to the grid fill.
                if (len(sv0) + len(sv1)) % 2:
                    # odd perimeter however many loops we add, so quads alone cannot close it
                    continue
                if not budget(2 * max(0, gap - 1)): break
                def connect(a, b, _gap=gap, _side=side, _cap=cap, _nrm=nrm):
                    # interior points of one of the sides being created, from a to b
                    return [ new_point(a.co * (1 - t / _gap) + b.co * (t / _gap), _side,
                                       blend_pair(_nrm(a), _nrm(b), t / _gap), _cap)
                             for t in range(1, _gap) ]
                loop = (list(sv0) + connect(sv0[-1], sv1[-1])
                        + list(reversed(sv1)) + connect(sv1[0], sv0[0]))
                if not emit_grid_fill(loop, 'bridge'): break
                continue

            l0, l1 = len(sv0), gap + 1
            if not budget(l0 * max(0, l1 - 2)): break
            verts, normals, raws, edges, faces, fixed = [], [], [], [], [], set()
            for i in range(l0):
                for j in range(l1):
                    if j == 0 or j == l1 - 1:
                        fixed.add(i * l1 + j)
                        verts += [sv0[i] if j == 0 else sv1[i]]
                        normals += [None]; raws += [None]
                    else:
                        pj = j / (l1 - 1)
                        n = blend_pair(nrm(sv0[i]), nrm(sv1[i]), pj)
                        co = sv0[i].co * (1 - pj) + sv1[i].co * pj
                        verts += [new_point(co, side, n, cap)]
                        normals += [n]; raws += [co]
            if too_noisy(verts, raws, l0, l1, boundary): continue
            smooth_grid(verts, normals, l0, l1, side, cap, fixed)
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(l0) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1, l1-1) for i in range(l0-1)]
            faces += [((i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1)) for i in range(l0-1) for j in range(l1-1)]
            if refuse_if_covered('I', verts, faces, boundary): continue
            add_previz('I', verts, edges, faces)

        # a strip with nothing to bridge to steps outward instead
        for i0, shape0 in enumerate(shapes['I']):
            if i0 in bridged: continue
            if not emit_offset(get_verts(shape0[0]), shape0[0]): break

        if sel_quad is not None: emit_quad_strip(sel_quad, 'quad')
        if lone_bmv is not None: emit_corner_quad(lone_bmv)

        ###################
        # the cursor pick: while Ctrl is held (or F, from another tool) and the SELECTION has given
        # nothing to preview, the cursor picks a quad out of the verts nearest it, or failing that
        # extends the nearest open edge or corner. Gated on the selection's preview, not on there
        # being a selection, so a stray vert left selected does not switch the hover off. What the
        # artist selected on purpose wins when it does preview something.
        L.nearest_sig = L.hover_sig = None
        if L.previz or not ctrl_at or L.error: return
        key = L._candidate_key(context)
        if key is None: return
        if key != L.cand_key: L._collect_candidates(bm, key)
        # The pick is on from here, whatever is offered: track_mouse only re-picks per move while
        # nearest_active is set and the cache is current, and a drag that has just made a patch
        # relies on exactly that to notice the cursor leaving it.
        L.nearest_active = True
        # a drag shows nothing while still inside the patch it just made
        if L.drag_last is not None and L._cursor_in_polys(context, mouse_at, L.drag_last): return
        pv = L.pick_nearest_quad(context, bm, M, mouse_at)
        if pv is not None:
            L.nearest_sig = frozenset(pv.vert_idx)
            emit_quad_strip([ bm.verts[i] for i in pv.vert_idx ], 'nearest')
        else:
            # No quad to be had here: the nearest open edge steps outward, or the nearest boundary
            # corner offers its corner quad, the same as if it had been selected.
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
    # interaction

    @staticmethod
    def track_ctrl(context : Context, event : Event) -> bool:
        ''' Follow the Ctrl key, which is what turns the cursor pick on and off. True when the
        preview changed and the caller should redraw. '''
        L = LegacyPatches_Logic
        held = bool(event.ctrl) or L.ctrl_forced
        if held == L.ctrl: return False
        L.ctrl = held
        if held:
            # a rebuild is what works out that nothing is selected and turns the pick on; it also
            # only happens once per press, so the O(V) candidate scan is not on any hot path
            L.dirty = True
        elif L.nearest_active:
            # let go: drop the offer. Only the cursor pick can be showing here, since it is the
            # one thing that runs with nothing selected
            L.previz = []
            L.nearest_sig = None
            L.hover_sig = None
            L.nearest_active = False
        return True

    @staticmethod
    def track_mouse(context : Context, event : Event) -> bool:
        # A wire run steps toward the mouse, so its side is the one thing about the preview that
        # follows the cursor. Rebuilding on every mouse move would cost a snap per vert per frame;
        # instead remember each run's screen-space chord and the side the last rebuild used, and
        # only go dirty when the mouse crosses one. True when it did, so the caller can redraw.
        L = LegacyPatches_Logic
        L.mouse = (event.mouse_x, event.mouse_y)
        if not context.edit_object: return False
        rgn, r3d = context.region, context.region_data
        if not rgn or not r3d: return False
        M = context.edit_object.matrix_world

        if (L.ctrl or L.ctrl_forced) and L.nearest_active and L.cand_key is not None and L.cand_key == L._candidate_key(context):
            if L.drag_last is not None and L._cursor_in_polys(context, L.mouse, L.drag_last):
                # A drag still inside the patch it just made shows nothing: the next cell's preview
                # kept appearing before the cursor had left this one, and flipping as it went.
                if not L.previz and L.nearest_sig is None and L.hover_sig is None: return False
                L.previz = []
                L.nearest_sig = L.hover_sig = None
                return True
            # The nearest quad follows the cursor properly, so it is re-picked on every move rather
            # than watched for a crossing. It is cheap: the candidates are already projected, and
            # nothing here creates or snaps a vert. Deliberately does NOT set dirty - a full rebuild
            # would re-scan the mesh for the same answer. A mesh edit fails the key test above and
            # the next draw's update() rebuilds instead.
            try:
                bm = bmesh.from_edit_mesh(context.edit_object.data)
                bm.verts.ensure_lookup_table()
                pv = L.pick_nearest_quad(context, bm, M, L.mouse)
                hit = L.pick_nearest_extend(context, bm, M, L.mouse) if pv is None else None
            except (ReferenceError, RuntimeError):
                pv, hit = None, None
            hsig = (hit[0], hit[1].index) if hit is not None else None
            if hsig != L.hover_sig:
                # The edge or corner under the cursor changed (or a quad took over from one). Its
                # step or corner quad snaps new verts, so only a full rebuild can build it; that
                # rebuild happens once per change of element, never per move.
                L.hover_sig = hsig
                L.dirty = True
                return True
            if hsig is None:
                sig = frozenset(pv.vert_idx) if pv is not None else None
                if sig != L.nearest_sig:
                    # Show the plain quad at once, and ask for a rebuild too: the rebuild is what
                    # snaps its cuts (see emit_quad_strip). Once per change of quad, never per move.
                    L.previz = [pv] if pv is not None else []
                    L.nearest_sig = sig
                    L.dirty = True
                    return True
                return False
            # an extend preview is showing: a wire edge among them still follows the cursor's side
            # through the chord test below

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

    @staticmethod
    def _candidate_key(context : Context) -> tuple | None:
        RFCore = RFGlobals.RFCore_None
        obj = context.edit_object
        if not RFCore or not obj: return None
        return (RFCore.depsgraph_version, obj.name)

    @staticmethod
    def _collect_candidates(bm, key : tuple):
        ''' Verts the nearest-quad search may use: the loose points the artist has dropped, and the
        verts along an open border so a couple of points can close onto existing geometry. Interior
        verts are excluded - a quad there would have to overlap the mesh. One O(V) pass, kept until
        the mesh changes, which is what stops this costing anything per mouse move.
        '''
        L = LegacyPatches_Logic
        flat, idx = [], []
        for bmv in bm.verts:
            if bmv.hide: continue
            # An isolated vert has is_wire AND is_boundary both False, so the face test has to come
            # first. is_manifold is no good here: a vert on an open border is manifold, and those
            # are exactly the ones a quad should be able to close onto.
            if bmv.link_faces and not bmv.is_boundary: continue
            idx.append(bmv.index)
            flat.extend(bmv.co)
        L.cand_idx = idx
        L.cand_cos = np.array(flat, dtype=np.float64).reshape(len(idx), 3) if idx else None
        # The open edges, for the hover extend. Both ends of an open edge are always candidates: a
        # wire edge's verts have no faces, a one-face edge's verts are on the border. Same pass
        # cost class as the vert scan, kept under the same key.
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
        ''' Candidate verts within `radius` (local units) of a point, nearest first, at most `k`.
        Refreshes the cache when the mesh has changed. Used by the emitters to ask whether a vert
        they are about to create is already there.
        '''
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
        ''' Candidates in region pixels, NaN for anything behind the camera. This is
        location_3d_to_region_2d done in one array op, cached until the view or the mesh moves.
        '''
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
        # perspective: w <= 0 is behind the eye. orthographic: w is always 1, so nothing is masked
        ok = w > 1e-6
        w = np.where(ok, w, 1.0)
        px = (clip[:, :2] / w[:, None] + 1.0) * 0.5 * np.array([rgn.width, rgn.height])
        px[~ok] = np.nan
        L.proj_px, L.proj_key = px, key
        return px

    @staticmethod
    def _visible(context : Context, k : int, bmv, M : Matrix) -> bool:
        ''' Whether candidate `k` can be seen: not behind the source from where the view is. A quad
        on the far side of the mesh must not be offered. One raycast per candidate per view, cached
        against proj_key so a still view costs nothing after the first look; only the few nearest
        candidates of a pick are ever asked, never the whole cache. X-ray disables the test.
        '''
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
        ''' The quad the cursor is sitting in, out of the candidate verts nearest it. Nothing is
        created, so there is no snapping or mirror work to do: the four verts already exist and the
        cursor only chooses between ways of joining them. `strict` drops the outline slop: a drag
        should only make the cells its path actually passes through.
        '''
        L = LegacyPatches_Logic
        rgn, r3d = context.region, context.region_data
        if mouse_win is None or not rgn or not r3d: return None
        px = L._project_candidates(context, M)
        if px is None or len(px) < 4: return None
        mouse = Vector((mouse_win[0] - rgn.x, mouse_win[1] - rgn.y))

        d2 = np.nansum((px - np.array([mouse.x, mouse.y])) ** 2, axis=1)
        d2 = np.where(np.isnan(px[:, 0]), np.inf, d2)
        radius = Drawing.scale(NEAREST_RADIUS_PX) or NEAREST_RADIUS_PX
        near = np.flatnonzero(d2 <= radius * radius)
        if len(near) < 4: return None
        near = near[np.argsort(d2[near])]

        # Resolve the cached indices now, nearest first, until NEAREST_K usable ones are in hand. A
        # coordinate that has moved means the cache predates an edit the rebuild has not caught up
        # with, and offering a quad from it would be a lie. Hidden or occluded verts are simply
        # passed over: hiding need not have bumped the version, and a vert behind the mesh is not
        # one the artist can see to be joining.
        try:
            bmvs, pts2d, cos3d = [], [], []
            nverts = len(bm.verts)
            for k in near:
                if len(bmvs) >= NEAREST_K: break
                vi = L.cand_idx[k]
                if vi >= nverts: return None
                bmv = bm.verts[vi]
                cached = L.cand_cos[k]
                if not bmv.is_valid: return None
                if bmv.hide: continue
                if (bmv.co - Vector(cached)).length_squared > 1e-8: return None
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

        # the surface point under the cursor, for the 3D check; off the source there is nothing to
        # anchor to and the screen-space tests stand alone
        anchor = raycast_point_valid_sources(context, mouse)

        for score, quad in ranked:
            verts = [bmvs[i] for i in quad]
            if score[0] == 1:
                if strict: break
            elif bm.faces.get(verts):
                # The cursor is inside a face that already exists. The quads still in the running
                # are the ones reached through the outline slop, and a bigger quad has a bigger
                # slop, so what would be offered here is a wide quad reaching over the mesh from
                # the cell next door. Offer nothing instead; the extend fallback also stays quiet
                # over a face.
                return None
            if not _quad_is_placeable(bm, verts): continue
            if anchor is not None:
                q = [cos3d[i] for i in quad]
                mean_side = sum((q[(i + 1) % 4] - q[i]).length for i in range(4)) / 4
                if any((c - anchor).length > NEAREST_3D_REACH * mean_side for c in q): continue
            edges_out = [ (i, (i + 1) % 4) for i in range(4)
                          if _bmedge_between(verts[i], verts[(i + 1) % 4]) is None ]
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
        within HOVER_VERT_PX, else ('edge', bme) for an open edge within HOVER_EDGE_PX, else None.
        Works off the projected candidate cache, so it costs a few array ops per call.
        '''
        L = LegacyPatches_Logic
        rgn, r3d = context.region, context.region_data
        if mouse_win is None or not rgn or not r3d: return None
        px = L._project_candidates(context, M)
        if px is None or len(px) == 0: return None
        mouse = np.array([mouse_win[0] - rgn.x, mouse_win[1] - rgn.y], dtype=np.float64)

        def resolve(k):
            vi = L.cand_idx[k]
            if vi >= len(bm.verts): return None
            bmv = bm.verts[vi]
            if not bmv.is_valid or bmv.hide: return None
            if (bmv.co - Vector(L.cand_cos[k])).length_squared > 1e-8: return None
            if not L._visible(context, k, bmv, M): return None    # behind the mesh: not on offer
            return bmv

        def on_open_side(bme, pa, pb):
            # The cursor says where the row goes, and a row can only go away from the face the edge
            # already has. A cursor on the faced side - hovering over the mesh - is not asking for
            # this edge to step; without this every filled quad offered to extrude its own edges.
            if not bme.link_faces: return True
            pf = location_3d_to_region_2d(rgn, r3d, M @ bme.link_faces[0].calc_center_median())
            if pf is None: return True
            m = Vector((mouse[0], mouse[1]))
            return _side2d(pa, pb, m) != _side2d(pa, pb, pf)

        anchor = raycast_point_valid_sources(context, Vector((mouse[0], mouse[1])))

        def within_reach(bmv, scale):
            # a far element close only on screen is not what the cursor is beside
            return anchor is None or (M @ bmv.co - anchor).length <= HOVER_3D_REACH * scale

        try:
            d2 = np.nansum((px - mouse) ** 2, axis=1)
            d2 = np.where(np.isnan(px[:, 0]), np.inf, d2)
            if L.cand_open is not None:
                # a corner: two or more open edges meet there, so there is a quad to complete. Not
                # while the cursor is over one of its faces, for the same reason as the edges below.
                dv = np.where(L.cand_open >= 2, d2, np.inf)
                rv = Drawing.scale(HOVER_VERT_PX) or HOVER_VERT_PX
                for k in np.argsort(dv)[:4]:
                    if dv[k] > rv * rv: break
                    bmv = resolve(k)
                    if bmv is None: continue
                    opens = [ (M @ e.other_vert(bmv).co - M @ bmv.co).length for e in bmv.link_edges if len(e.link_faces) < 2 ]
                    if opens and not within_reach(bmv, sum(opens) / len(opens)): continue
                    m = Vector((mouse[0], mouse[1]))
                    over = False
                    for bmf in bmv.link_faces:
                        pts = [ location_3d_to_region_2d(rgn, r3d, M @ v.co) for v in bmf.verts ]
                        if all(pts) and point_inside_face_2d(m, pts): over = True; break
                    if not over: return ('vert', bmv)
            if L.cand_edges is None or len(L.cand_edges) == 0: return None
            A, B = px[L.cand_edges[:, 0]], px[L.cand_edges[:, 1]]
            AB = B - A
            ab2 = (AB ** 2).sum(axis=1)
            ab2 = np.where(ab2 < 1e-12, 1.0, ab2)
            t = np.clip(((mouse - A) * AB).sum(axis=1) / ab2, 0.0, 1.0)
            de = ((A + AB * t[:, None] - mouse) ** 2).sum(axis=1)
            de = np.where(np.isnan(de), np.inf, de)
            re_ = Drawing.scale(HOVER_EDGE_PX) or HOVER_EDGE_PX
            for k in np.argsort(de)[:4]:
                if de[k] > re_ * re_: break
                va, vb = resolve(L.cand_edges[k, 0]), resolve(L.cand_edges[k, 1])
                if va is None or vb is None: continue
                bme = _bmedge_between(va, vb)
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
        ''' Four selected verts as one quad, when they make a good and legal one: the verts in ring
        order, for emit_quad_strip. Ordered on screen when there is a view (the same way the cursor
        pick orders its four), else in the plane the four roughly lie in.
        '''
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
            u = (cos[0] - c) - n * (cos[0] - c).dot(n)
            if u.length_squared < 1e-18: return None
            u.normalize()
            w = n.cross(u)
            order = sorted(range(4), key=lambda k: math.atan2((cos[k] - c).dot(w), (cos[k] - c).dot(u)))
        verts = [ sel_verts[k] for k in order ]
        if _quad_shape_ok([ M @ v.co for v in verts ]) is None: return None
        if not _quad_is_placeable(bm, verts): return None
        return verts

    @staticmethod
    def mouse_over_previz(context : Context, *, radius2d : float = 10) -> bool:
        ''' True when the cursor is inside a previewed patch, and not on a vertex whose corner the
        same click would toggle. Ctrl+click confirms the patch, but Ctrl+click also toggles a corner,
        so the toggle keeps its verts: the radius is the one pick_selected_vert uses. Only the
        selected boundary can have a corner toggled, which is why the rest of the preview is fair
        game - on a fine patch every pixel is near some vertex of it.
        '''
        L = LegacyPatches_Logic
        edit_object = context.edit_object
        rgn, r3d = context.region, context.region_data
        if not L.previz or not edit_object or not rgn or not r3d: return False
        if L.mouse is None: return False
        # The cursor pick only offers a quad when the cursor is on it in the first place, so there
        # is nothing to measure again here - and with nothing selected there is no corner for the
        # same click to toggle either. Measuring twice can only find a disagreement between the two
        # tests and swallow the click.
        if all(pv.hover for pv in L.previz): return True

        M = edit_object.matrix_world
        mouse = Vector((L.mouse[0] - rgn.x, L.mouse[1] - rgn.y))
        try:
            r = (Drawing.scale(radius2d) or radius2d) ** 2
            for co in L.boundary_verts.values():
                p = location_3d_to_region_2d(rgn, r3d, M @ co)
                if p and (p - mouse).length_squared < r: return False
            # stops at the first face the cursor is in, so a big patch usually costs a few faces
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
        # v3 accel_nearest2D_vert(max_dist=10) restricted to selected verts; the candidate set
        # (verts of selected boundary edges) is small enough that a flat 2D scan is fine
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

        # v3: a detected corner becomes forced-smooth; otherwise flip between forced-corner and forced-smooth
        if idx in L.corner_indices:
            layer[bmv] = CORNER_SMOOTH
        else:
            layer[bmv] = CORNER_SMOOTH if layer[bmv] == CORNER_FORCED else CORNER_FORCED

        # v3 pruned overrides to selected verts on every recompute; recompute runs from a draw
        # callback here and must not write, so prune whenever we're writing anyway
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

    @staticmethod
    def fill(context : Context, settings : PatchSettings | None = None) -> bool:
        L = LegacyPatches_Logic
        # Rebuild against the settings actually being applied and skip the cache: on a redo these
        # come from the redo panel, not from whatever the tool header currently shows.
        try:
            L._recompute(context, settings if settings is not None else L.read_settings(context))
        except ReferenceError:
            L._clear_products()
            L.dirty = True
            return False
        if not L.previz: return False
        # the rebuild that follows a fill previews nothing, so the redo panel and the scroll
        # shortcuts that re-run the fill read these instead
        L.filled_flags = (L.has_bridge, L.has_grid, L.has_loft, L.has_offset, L.has_quad)
        L.filled_loops = L.loops_last or 0
        L.filled_solutions = max(1, len(L.grid_ranked))

        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        nverts = len(bm.verts)

        # pass 1 (no mutation): resolve every existing vert first, since verts.new() dirties the lookup table
        existing = []
        for pv in L.previz:
            row = []
            for k, (idx, co) in enumerate(zip(pv.vert_idx, pv.vert_co)):
                if idx is None:
                    row.append(None)
                    continue
                if idx >= nverts:
                    L.dirty = True
                    return False
                bmv = bm.verts[idx]
                # A step welds onto existing verts past a corner and on along the rails, none of which
                # are selected, so it cannot be held to that test; the coordinate check below still
                # catches a stale one, and _recompute has just re-read the selection anyway.
                selected = bmv.select or pv.hover or pv.kind in ('offset', 'corner')
                if not bmv.is_valid or not selected or (bmv.co - co).length_squared > 1e-8:
                    # previz is stale; let the next frame rebuild it
                    L.dirty = True
                    return False
                row.append(bmv)
            existing.append(row)

        # pass 2: create verts and faces
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
                if bm.faces.get(vs): continue                          # already filled
                new_bmfs.append(bm.faces.new(vs))

        pin_to_mirror_planes(context, new_bmvs, active_mirror_axes(context))
        orient_bmf_normals(context, new_bmfs, new_faces=True)

        stepped = [ (pv, bmvs) for pv, bmvs in zip(L.previz, built) if pv.kind == 'offset' ]
        # a quad picked by the cursor was built from nothing selected, and the next one is picked the
        # same way: selecting its verts would switch the tool back to filling a selection
        hovered = all(pv.hover for pv in L.previz)
        bmops.deselect_all(bm)
        if hovered:
            pass
        elif stepped:
            # leave only the new row selected: it is an open strip in its own right, so the next
            # rebuild offers the step after it and F walks outward. A step alongside some other
            # patch is rare; the other patch's geometry simply ends up unselected
            for pv, bmvs in stepped:
                bmops.select_iter(bm, [ bmvs[k] for k in pv.row_idx ])
        else:
            bmops.select_iter(bm, new_bmvs)
            bmops.select_iter(bm, new_bmfs)
        BMVertLayer_Int.remove(bm, CORNER_LAYER)    # overrides only applied to the boundary we just filled
        bmops.flush_selection(bm, em)

        # remember what this left selected: the new patch's own boundary is still selected and
        # still qualifies, so without this the next rebuild would offer to fill it all over again.
        # A step is the exception: its row is meant to be offered again straight away
        if stepped or hovered:
            L.filled_sig = None
        else:
            bm.edges.index_update()
            left = [ e for e in bmops.get_all_selected_bmedges(bm) if len(e.link_faces) < 2 and not e.hide ]
            L.filled_sig = L.selection_signature(bm, left)
        L.nearest_sig = None    # the next hover picks afresh, over the mesh this fill just changed
        L.hover_sig = None
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
        ''' Create whatever is previewed under the cursor right now, the way a click would. The fill
        rebuilds against the locked cursor, so an extend preview is rebuilt for this exact spot.

        A drag is stricter than a click, in two ways. The cursor has to be INSIDE a face of the
        preview, not merely near it, so a step offered beside an edge the path brushes past is not
        made unless the path actually runs through it. And nothing is made until the cursor has left
        the last patch the drag made, so one area gets one patch: without that, the samples after a
        fill were still in the same cell and kept accepting whatever else could be squeezed in there.
        '''
        L = LegacyPatches_Logic
        L.mouse = (int(mouse_win[0]), int(mouse_win[1]))    # the caller vouches the cursor is here
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
            # the mesh changed under a cache keyed on a depsgraph version that only bumps after
            # this event; the next pick must not trust it
            L.cand_key = None
            if drag: L.drag_last = polys
        return made

    @staticmethod
    def drag_start(context : Context, pt, previz) -> bool:
        ''' The stroke began on a preview: make it, whatever the travel rule says - a stroke that
        starts on a patch means that patch. A patch built from a selection leaves its new geometry
        selected so F can walk on from it; a drag needs nothing selected, or the cursor pick that
        does the drawing never switches on, so that selection is dropped here. True when made.
        '''
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
        ''' One point of a drag against the preview showing there. A preview is a candidate from the
        point the cursor entered it, and is made once the cursor has travelled DRAW_ACCEPT_FRAC of
        the preview's extent in that direction. Nothing happens inside the last patch made.
        True when a patch was made.
        '''
        L = LegacyPatches_Logic
        pt = (int(pt[0]), int(pt[1]))
        if not previz or (L.drag_last is not None and L._cursor_in_polys(context, pt, L.drag_last)):
            L.drag_cand = None
            return False
        # Order-free: the per-move pick and the rebuilt preview list the same four verts in different
        # orders, and a key that told them apart reset the candidate on every event, so only a slow
        # stroke (whose events are too close together to sample between) ever got its quarter.
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
        if travel.length < DRAW_ACCEPT_FRAC * extent: return False
        L.previz = list(previz)
        made = L.accept_current(context, pt, drag=True)
        if made: L.drag_cand = None
        return made

    @staticmethod
    def accept_along(context : Context, p0, p1) -> int:
        ''' Walk the cursor's path between two drag positions, sampled every DRAW_SAMPLE_PX so a fast
        sweep skips none of the cells it went through, and put each sample through drag_step. Only
        quads whose four verts exist are picked here: an extend preview needs the full rebuild, and
        that happens at the event position itself. Returns how many were made. The end point is
        left for the caller.
        '''
        L = LegacyPatches_Logic
        edit_object = context.edit_object
        if not edit_object: return 0
        M = edit_object.matrix_world
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        steps = max(1, int(math.hypot(dx, dy) // DRAW_SAMPLE_PX))
        made = 0
        for s in range(1, steps):
            pt = (p0[0] + dx * s / steps, p0[1] + dy * s / steps)
            if L._cursor_in_polys(context, pt, L.drag_last): continue   # still in the last one made
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
        # styled like PolyPen's previews: theme face-select fill, highlight-colored dashed edges,
        # hollow rings on existing verts. corners are the solid highlight points
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
                    # without these the quads along a created side read as triangles
                    with Drawing.draw(context, CC_2D_POINTS) as draw:
                        draw.point_size(vertex_size)
                        draw.color(color_open)
                        for k in pv.open_idx:
                            p = pts[k]
                            if p: draw.vertex(p)

            if len(L.drag_path) > 1:
                # drawn the way Strokes draws a stroke, smoothed a little so the line is not jagged
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

            # text last, so it sits on top of the face fill rather than under it
            for text, cos in L.labels:
                pts = [p for co in cos if (p := proj(co))]
                if not pts: continue
                # centered on the shape, same as the loop and strip counts the other tools draw
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
    ''' The LMB gesture Patches shares between Ctrl held (RFOperator_LegacyPatches_Draw) and F held
    from another tool (the quick switch): a click fills the previewed patch or toggles a corner, a
    drag draws a path and makes whatever the cursor passes over. The owning modal says which
    modifier state may START a press; once pressed, the rest of the gesture is handled here whatever
    the modifiers do, so a drag cannot be left half done.
    '''
    def __init__(self):
        self.pressed = self.dragging = False
        self.press_xy = self.prev_xy = (0, 0)
        self.press_previz = []      # what was previewed under the press, made outright if this becomes a drag
        self.made = 0
        self.used = False           # a click or drag happened at all, for the owner to know

    def handle(self, context : Context, event : Event, *, accept_press : bool) -> set[str] | None:
        ''' None when the event is not this gesture's business, else what the modal should return. '''
        L = LegacyPatches_Logic
        mouse = (event.mouse_x, event.mouse_y)

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                if self.pressed or not accept_press: return None
                # the preview may not have been drawn yet (a press in the same instant the tool was
                # switched in), so make sure there is one to remember
                if not L.previz: L.update(context)
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
                # the press was ours; without this the click falls through to shortest-path select
                return {'RUNNING_MODAL'}
            return None

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'} and self.pressed:
            # The owning modal sits above the overlay, so the preview is one event behind unless it
            # is brought up to date here first.
            L.track_mouse(context, event)
            if L.dirty: L.update(context)
            L.drag_path.append(mouse)
            if not self.dragging:
                dx, dy = mouse[0] - self.press_xy[0], mouse[1] - self.press_xy[1]
                if dx * dx + dy * dy > mouse_drag() ** 2:
                    self.dragging = True
                    # the patch the stroke started on is made outright, travel rule or not
                    if L.drag_start(context, self.press_xy, self.press_previz):
                        self.made += 1
                        L.update(context)
            if self.dragging:
                # the cells swept through since the last event, then whatever is previewed here
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
        L = LegacyPatches_Logic
        # A selected boundary vert under the cursor is a corner to toggle; otherwise the click
        # confirms whatever is previewed, wherever the click lands: a step or a bridge is confirmed
        # by clicking anywhere, not only on its faces (Jonathan). Both go through their operators so
        # each is one undo step.
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
