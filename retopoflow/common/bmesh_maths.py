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

import math
from collections.abc import Sequence

import bpy
from mathutils import Vector, Matrix
from bmesh.types import BMVert, BMEdge, BMFace, BMesh
from bpy.types import Context, Region, RegionView3D

from .bmesh import (
    get_boundary_strips_cycles,
    bme_other_bmv,
    bme_length,
    wind_bmfs_to_match_neighbors,
)
from .raycast import raycast_valid_sources, MatrixInfo, FindNearest
from .maths import point_to_bvec4, view_forward_direction
from ...addon_common.common.maths import closest_point_segment, Point, Direction, Plane
from ...addon_common.ext.circle_fit import hyperLSQ
from ...addon_common.common.utils import iter_pairs

from enum import IntEnum, auto
from typing import Any


## TODO: organize and generalize this code a bit better!



def find_point_at(points, is_cycle, v):
    if v <= 0: return points[0]
    if v >= 1: return points[0] if is_cycle else points[-1]
    length = sum((p1-p0).length for (p0,p1) in iter_pairs(points, is_cycle))
    vt = v * length
    t = 0
    for (p0, p1) in iter_pairs(points, is_cycle):
        d01 = (p1 - p0).length
        if vt <= t + d01:
            # LERP to find point
            if d01 == 0:
                # Consecutive points are identical, can't lerp.
                return p0
            d0v = vt - t
            f = d0v / d01
            return p0 + (f * (p1 - p0))
        t += d01
    return points[0] if is_cycle else points[-1]

def find_closest_point(points, is_cycle, p):
    closest_p = None
    closest_d = float('inf')
    for (p0, p1) in iter_pairs(points, is_cycle):
        pt = closest_point_segment(p, p0, p1)
        d = (p - pt).length
        if not closest_p or d < closest_d:
            (closest_p, closest_d) = (pt, d)
    return closest_p

def find_sharpest_indices(points, *, sharp_radius_percent=0.10, second_radius_percent=0.20):
    npoints = len(points)
    length = sum((p1-p0).length for (p0,p1) in iter_pairs(points, False))
    radius = sharp_radius_percent * length  # distance to travel before estimating sharpness
    second_radius = second_radius_percent * length
    sharps = []
    for i, pt in enumerate(points):
        pt0 = next((p for p in points[i::-1] if (pt - p).length >= radius), None)
        pt1 = next((p for p in points[i:]    if (pt - p).length >= radius), None)
        if pt0 and pt1:
            sharpness = ((pt0 - pt).normalized()).dot((pt - pt1).normalized())
            sharps += [(i, sharpness)]
    sharps.sort(key=lambda s: s[1])
    i0 = sharps[0][0]
    i1 = next((i1 for (i1,_) in sharps if (points[i0] - points[i1]).length >= second_radius), i0)
    return (min(i0, i1), max(i0, i1))

def find_sharpest_index(points, *, sharp_radius_percent=0.10):
    npoints = len(points)
    length = sum((p1-p0).length for (p0,p1) in iter_pairs(points, False))
    radius = sharp_radius_percent * length  # distance to travel before estimating sharpness
    sharps = []
    for i, pt in enumerate(points):
        pt0 = next((p for p in points[i::-1] if (pt - p).length >= radius), None)
        pt1 = next((p for p in points[i:]    if (pt - p).length >= radius), None)
        if pt0 and pt1:
            sharpness = ((pt0 - pt).normalized()).dot((pt - pt1).normalized())
            sharps += [(i, sharpness)]
    sharps.sort(key=lambda s: s[1])
    return sharps[0][0]

def rdp_corner_indices(points, tolerance, *, seed_indices=(), min_spacing=0.0, force_endpoints=True):
    ''' Iterative Ramer-Douglas-Peucker corner finder.  Returns the sorted indices of
    points whose perpendicular distance from the chord spanning their enclosing segment exceeds `tolerance`.
    Any `seed_indices` are always included. The endpoints (0 and len-1) are too, by default
    (force_endpoints=True) -- pass False for a cyclic/closed input, where index 0 and len-1 are
    just an arbitrary seam in the array representation (wherever the walk happened to start),
    not a meaningful geometric corner; forcing them there would add a corner with no shape-based
    justification, wherever that seam happens to land. '''
    l = len(points)
    if l < 3:
        forced = set(seed_indices)
        if force_endpoints and l >= 1: forced |= {0, l - 1}
        return sorted(i for i in forced if 0 <= i < l)

    forced = set(seed_indices) | ({0, l - 1} if force_endpoints else set())
    stack = [(0, l - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 - i0 <= 1:
            continue
        p0, p1 = points[i0], points[i1]
        seg = p1 - p0
        seg_len2 = seg.length_squared
        max_dist, max_k = -1.0, i0 + 1
        for k in range(i0 + 1, i1):
            p = points[k]
            if seg_len2 < 1e-20:
                d = (p - p0).length
            else:
                t = max(0.0, min(1.0, (p - p0).dot(seg) / seg_len2))
                d = (p - (p0 + t * seg)).length
            if d > max_dist:
                max_dist, max_k = d, k
        if max_dist < tolerance:
            continue
        if min_spacing <= 0 or not any(
            (points[max_k] - points[fi]).length < min_spacing
            for fi in forced if fi != max_k
        ):
            forced.add(max_k)
        stack.append((i0, max_k))
        stack.append((max_k, i1))
    return sorted(forced)

def compute_n(points):
    p0 = points[0]
    return sum((
        (p1-p0).cross(p2-p0).normalized()
        for (p1,p2) in zip(points[1:-1], points[2:])
    ), Vector((0,0,0))).normalized()

def bmes_get_prevnext_bmvs(bmes, bmv):
    # find bmes that have bmv, keep order!
    fbmes = [bme for bme in bmes if bmv in bme.verts]
    if len(fbmes) == 2:
        return [bme_other_bmv(bme, bmv) for bme in fbmes]
    # only one bme has bmv, so must be either first or last
    bme = fbmes[0]
    if bme == bmes[0]:
        return bmv, bme_other_bmv(bme, bmv)
    else:
        return bme_other_bmv(bme, bmv), bmv
def get_strip_bmvs(strip, bmv_start):
    bmv = bmv_start
    bmvs = [bmv]
    for bme in strip:
        bmv = bme_other_bmv(bme, bmv)
        bmvs.append(bmv)
    return bmvs

def check_bmf_normals(fwd, bmfs):
    for bmf in bmfs:
        bmf.normal_update()
        if fwd.dot(bmf.normal) > 0:
            bmf.normal_flip()

def orient_bmf_normals(
    context : Context,
    bmfs : Sequence[BMFace],
    *,
    matinfo : MatrixInfo | None = None,
    new_faces : bool = False,
) -> None:
    '''
    Point newly created or freshly moved faces outwards if Correct Face Normals is on.

    Pass new_faces = True for newly created faces.

    Faces are compared against the source mesh, so call this after snapping, not before.
    Falls back to its neighbor's direction, then to the view direction, then to doing nothing.
    Blender's default is pointing away from the object origin.
    '''
    bmfs = [bmf for bmf in bmfs if bmf is not None and bmf.is_valid]
    if not bmfs: return

    if not context.scene.retopoflow.snapping.correct_face_normals:
        if new_faces: wind_bmfs_to_match_neighbors(bmfs)
        return

    if not matinfo: matinfo = MatrixInfo(context=context)
    bmfs_unresolved = []
    for bmf in bmfs:
        bmf.normal_update()
        # Sample every vert not the face midpoint. On a thin surface the midpoint lands
        # on either side more or less at random: https://github.com/CGCookie/retopoflow/issues/1762
        no_local = Vector((0, 0, 0))
        for bmv in bmf.verts:
            nearest = FindNearest(context, point_world=matinfo.l2w_point(bmv.co), matinfo=matinfo)
            if not nearest.found: continue
            no_local += nearest.normal_local
        if no_local.length_squared < 1e-12:
            # no source under the face, or the sampled normals cancelled out on a thin fin
            bmfs_unresolved.append(bmf)
            continue
        if bmf.normal.dot(no_local) < 0:
            bmf.normal_flip()
    if not bmfs_unresolved: return

    # the source had nothing to say, so agree with the surrounding faces instead
    bmfs = wind_bmfs_to_match_neighbors(bmfs_unresolved)
    if not bmfs or not new_faces: return  # whatever is left is attached to nothing settled

    check_bmf_normals(matinfo.w2l_direction(view_forward_direction(context)), bmfs)

def fit_template2D(template, p0, *, target=None, along=None):
    t0, t1 = template[0], template[-1]
    vt01 = t1 - t0
    lt = vt01.length
    vp01 = (target - p0) if target else (along.normalized() * lt)
    lp = vp01.length
    scale, angle = lp / lt, vecs_screenspace_angle(vt01, vp01)
    Mt = Matrix.Translation(Vector((-t0.x, -t0.y, 0)))
    Mr = Matrix.Rotation(angle, 4, 'Z')
    Ms = Matrix.Scale(scale, 4)
    Mp = Matrix.Translation(Vector((p0.x, p0.y, 0)))
    M = Mp @ Ms @ Mr @ Mt
    fitted = [ (M @ Vector((t.x, t.y, 0, 1))).xy for t in template ]
    return fitted

def vec_screenspace_angle(v):
    return -v.angle_signed(Vector((1,0)))
def vecs_screenspace_angle(v0, v1):
    a0 = vec_screenspace_angle(v0)
    a1 = vec_screenspace_angle(v1)
    a = a0 - a1
    if a > 180: a = -(a - 180)
    if a < -180: a = -(a - 180)
    return a

def get_boundary_cycle(bmv_start):
    if not bmv_start: return None
    cycle = None
    for bme in bmv_start.link_edges:
        if bme.hide: continue
        if not bme.is_wire and not bme.is_boundary: continue
        bmv = bmv_start
        current = []
        while True:
            current += [bme]
            bmv_next = bme_other_bmv(bme, bmv)
            if bmv_next == bmv_start:
                # found cycle!
                if not cycle or len(current) < len(cycle):
                    cycle = current
                break
            bme_next = next((
                bme_ for bme_ in bmv_next.link_edges
                if bme_ != bme and not bme_.hide and (bme_.is_wire or bme_.is_boundary)
            ), None)
            if not bme_next: break
            bmv = bmv_next
            bme = bme_next
    return cycle

def get_boundary_strips(bmv_start):
    if not bmv_start: return None
    strips = []
    for bme in bmv_start.link_edges:
        if bme.hide: continue
        if not bme.is_wire and not bme.is_boundary: continue
        bmv = bmv_start
        current = []
        while True:
            current += [bme]
            bmv_next = bme_other_bmv(bme, bmv)
            if bmv_next == bmv_start:
                # found cycle!
                return [current, current[::-1]]
            bmes_next = [
                bme_ for bme_ in bmv_next.link_edges
                if bme_ != bme and not bme_.hide and (bme_.is_wire or bme_.is_boundary)
            ]
            if len(bmes_next) != 1:
                break
            bmv = bmv_next
            bme = bmes_next[0]
        strips.append(current)
    return strips

def get_longest_strip_cycle(bmes):
    if not bmes: return (None, None, None, None)

    strips, cycles = get_boundary_strips_cycles(bmes)

    nstrips, ncycles = len(strips), len(cycles)

    longest_strip0 = strips[-1] if nstrips >= 1 else None
    longest_strip1 = strips[-2] if nstrips >= 2 else None
    longest_cycle0 = cycles[-1] if ncycles >= 1 else None
    longest_cycle1 = cycles[-2] if ncycles >= 2 else None

    if longest_strip0 and longest_strip1 and len(longest_strip0) == len(longest_strip1):
        if sum(bme_length(bme) for bme in longest_strip0) < sum(bme_length(bme) for bme in longest_strip1):
            longest_strip0, longest_strip1 = longest_strip1, longest_strip0

    if longest_cycle0 and longest_cycle1 and len(longest_cycle0) == len(longest_cycle1):
        if sum(bme_length(bme) for bme in longest_cycle0) < sum(bme_length(bme) for bme in longest_cycle1):
            longest_cycle0, longest_cycle1 = longest_cycle1, longest_cycle0

    return (longest_strip0, longest_strip1, longest_cycle0, longest_cycle1)

def generate_point_inside_bmf(bmf):
    '''
    generate function to determine if a point is inside bmf
    '''
    cos3D = [bmv.co for bmv in bmf.verts]
    o = Point.average(cos3D)
    z = Direction(bmf.normal)
    x = Direction(cos3D[0] - o)
    y = Direction(z.cross(x))
    def to2D(point):
        v = point - o
        vx, vy = x.dot(v), y.dot(v)
        return (vx, vy)
    cos2D = [ to2D(co) for co in cos3D ]
    def point_inside_bmf(point):
        # compute windings to determine if point is inside bmf
        (px, py) = to2D(point)

        # https://www.engr.colostate.edu/~dga/documents/papers/point_in_polygon.pdf
        ncos2D = [(cx-px, cy-py) for (cx,cy) in cos2D]
        crossings = 0
        for ((x0, y0), (x1, y1)) in iter_pairs(ncos2D, True):
            if y0 * y1 < 0:  # v0-v1 crosses x-axis
                # r is the x-coordinate of intersection of v0-v1 and x-axis
                r = x0 + (y0 * (x1 - x0)) / (y0 - y1)
                if r > 0:  # v0-v1 crosses positive x-axis
                    if y0 < 0: crossings += 1
                    else:      crossings -= 1
            elif y0 == 0 and x0 > 0:  # v0 is on positive x-axis
                if y1 > 0: crossings += 0.5
                else:      crossings -= 0.5
            elif y1 == 0 and x1 > 0:  # v1 is on positive x-axis
                if y0 < 0: crossings += 0.5
                else:      crossings -= 0.5
        # print(crossings)
        return (crossings % 2) == 1

        # https://ics.uci.edu/~eppstein/161/960307.html
        crossings = 0
        for ((x0, y0), (x1, y1)) in iter_pairs(cos2D, True):
            if x0 < px < x1 or x0 > px > x1:
                t = (px - x1) / (x0 - x1)
                cy = t * y0 + (1 - t) * y1
                if py == cy: return True                           # on boundary edge of face!
                if py > cy: crossings += 1
            if px == x0:
                if py == y0: return True                           # on boundary vert of face!
                if px == x1:
                    if y0 < py < y1 or y0 > py > y1: return True   # on boundary vert of face!
                elif px < x1:
                    crossings += 1
                if x1 > px: crossings += 1
        return (crossings % 2) == 1
    return point_inside_bmf

def is_bmvert_hidden(context:Context, bmv:BMVert, *, factor:float=0.99) -> bool:
    if bmv.hide: return True
    point = context.edit_object.matrix_world @ point_to_bvec4(bmv.co)
    hit = raycast_valid_sources(context, point, respect_clip_planes=True)
    if not hit: return False
    ray_e, hit_dist = hit['ray_world'][0], hit['distance']
    offset = context.space_data.overlay.retopology_offset
    return hit_dist < ((ray_e.xyz - point.xyz).length - offset) * factor


class BMMarking(IntEnum):
    seam = auto()
    sharp = auto()
    crease = auto()

def is_bmedge_edgemark(bm:BMesh, bme:BMEdge, mark:BMMarking):
    match mark:
        case BMMarking.seam:
            return getattr(bme, 'seam')
        case BMMarking.sharp:
            return not getattr(bme, 'smooth')
        case BMMarking.crease:
            layer = bm.edges.layers.float.get('crease_edge')
            if not layer: return False
            return bme[layer]
    return False

def is_bmvert_on_edgemark(bm:BMesh, bmv:BMVert, mark:BMMarking) -> bool:
    match mark:
        case BMMarking.seam:
            return any( getattr(bme, 'seam') for bme in bmv.link_edges )
        case BMMarking.sharp:
            return not all( getattr(bme, 'smooth') for bme in bmv.link_edges )
        case BMMarking.crease:
            layer = bm.edges.layers.float.get('crease_edge')
            if not layer: return False
            return any( bme[layer] for bme in bmv.link_edges )
    return False


def is_bmvert_pinned(bm : BMesh, bmv: BMVert, *, ensure_lookup_table: bool = True) -> bool:
    return get_bmvert_attribute(bm, bmv, 'retopoflow_pins', 'float', ensure_lookup_table=ensure_lookup_table)

def is_bmvert_creased(bm : BMesh, bmv : BMVert, *, ensure_lookup_table: bool = True) -> bool:
    return get_bmvert_attribute(bm, bmv, 'crease_vert', 'float', ensure_lookup_table=ensure_lookup_table)


def get_bmvert_attribute(bm:BMesh, bmv:BMVert, attribute:str, data_type:str, *, ensure_lookup_table: bool = True) -> Any:  # pyright: ignore[reportExplicitAny, reportAny]
    # Callers that have already ensured the lookup table (e.g. when filtering many verts
    # in a tight loop) can pass ensure_lookup_table=False to skip this per-vert call.
    if ensure_lookup_table:
        bm.verts.ensure_lookup_table()
    layer = getattr(bm.verts.layers, data_type).get(attribute) # pyright: ignore[reportAny]
    if layer:
        return bmv[layer]  # pyright: ignore[reportAny]
    else:
        return None


def fit_plane_of_verts(verts : Sequence[BMVert]) -> tuple[Vector|None, Vector|None]:
    ''' Best-fit plane and center for a collection of BMVerts. '''
    from ...addon_common.common.maths import Plane, Point
    from ...addon_common.ext.circle_fit import hyperLSQ
    points = [ Point(v.co) for v in verts ]
    try:
        plane  = Plane.fit_to_points(points)
        if not plane:
            return (None, None)
        normal = plane.n.copy()
        try:
            circle = hyperLSQ([list(plane.w2l_point(p).xy) for p in points])
            center = Vector(plane.l2w_point(Point((circle[0], circle[1], 0))))
        except Exception:
            center = sum((v.co for v in verts), Vector()) / len(verts)
    except Exception:
        normal = None
        center = sum((v.co for v in verts), Vector()) / len(verts)
    return normal, center


def loop_arc_params(verts, initial_coords, mw):
    ''' Arc-length parameterisation of a closed vertex loop. Returns (order, cumul, total).
    - order: vertices in traversal order (closed loop)
    - cumul: cumul[i] = world-space perimeter distance before order[i]
    - total: total world-space perimeter
    Returns None when the selection is not a simple closed loop. '''
    sel_set = set(verts)
    edges   = {e for v in verts for e in v.link_edges}
    adj     = {}
    for e in edges:
        v0, v1 = e.verts
        if v0 not in sel_set or v1 not in sel_set:
            continue
        adj.setdefault(v0, []).append(v1)
        adj.setdefault(v1, []).append(v0)

    if any(len(adj.get(v, [])) != 2 for v in verts):
        return None

    start = verts[0]
    order = [start]
    prev, cur = None, start
    for _ in range(len(verts) - 1):
        a, b = adj[cur]
        nxt  = b if (prev is not None and a == prev) else a
        if nxt == start:
            break
        order.append(nxt)
        prev, cur = cur, nxt

    if len(order) != len(verts) or len(set(order)) != len(verts):
        return None

    cumul = []
    dist  = 0.0
    for i, v in enumerate(order):
        cumul.append(dist)
        nxt_v = order[(i + 1) % len(order)]
        dist += (mw @ initial_coords[nxt_v] - mw @ initial_coords[v]).length
    total = dist
    return (order, cumul, total) if total > 1e-12 else None


def get_bary_coords(co, v0, v1, v2, initial_coords):
    ''' Barycentric coordinates and normal offset for `co` in triangle (v0, v1, v2).
    Returns (w0, w1, w2, offset) where w0+w1+w2 ≈ 1 and offset is the signed
    distance from the triangle plane (positive = same side as (B-A)x(C-A)).
    Returns (1/3, 1/3, 1/3, 0.0) for degenerate (collinear) triangles. '''
    A = initial_coords[v0]; B = initial_coords[v1]; C = initial_coords[v2]
    n    = (B - A).cross(C - A)
    n_sq = n.dot(n)
    if n_sq < 1e-20:
        return (1/3, 1/3, 1/3, 0.0)
    n_unit = n / math.sqrt(n_sq)
    offset = (co - A).dot(n_unit)
    proj   = co - offset * n_unit
    w0 = n.dot((C - B).cross(proj - B)) / n_sq
    w1 = n.dot((A - C).cross(proj - C)) / n_sq
    return (w0, w1, 1.0 - w0 - w1, offset)


def get_bary_triangle(co, tris, initial_cos, inside_only=False):
    ''' Find the best triangle in `tris` to embed local space point `co`.
    Returns (v0, v1, v2, w0, w1, w2, offset) or None. '''
    BARY_EPSILON = 0.05   # barycentric tolerance for "inside" triangle test
    best_in  = None; best_in_d  = float('inf')
    best_out = None; best_out_d = float('inf')
    for tri in tris:
        w0, w1, w2, offset = get_bary_coords(co, *tri, initial_cos)
        if min(w0, w1, w2) >= - BARY_EPSILON:
            d = abs(offset)
            if d < best_in_d:
                best_in   = (*tri, w0, w1, w2, offset)
                best_in_d = d
        else:
            A = initial_cos[tri[0]]; B = initial_cos[tri[1]]; C = initial_cos[tri[2]]
            d = (co - (A + B + C) / 3).length_squared
            if d < best_out_d:
                best_out = (*tri, w0, w1, w2, offset)
                best_out_d = d
    if best_in is not None:
        return best_in
    return None if inside_only else best_out


def bary_reconstruct(v0, v1, v2, w0, w1, w2, offset):
    ''' Reconstruct a position from barycentric weights and normal offset.
    Uses v0.co / v1.co / v2.co directly so it picks up live / post-deform
    positions without needing a separate position lookup. '''
    A = v0.co; B = v1.co; C = v2.co
    base  = w0 * A + w1 * B + w2 * C
    n     = (B - A).cross(C - A)
    n_len = n.length
    return base + offset * (n / n_len) if n_len > 1e-12 else base
