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
import bmesh
from mathutils import Vector, Matrix, Quaternion
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.types import Context
from bmesh.types import BMVert, BMEdge

import math
import numpy as np
import random
from collections.abc import Sequence
from typing import overload

from ...addon_common.common.maths import clamp, Point, Normal, Plane, Direction
from ...addon_common.common.utils import iter_pairs

def local_to_world(co: Vector, matrix_world: Matrix) -> Vector:
    return point_to_bvec3((matrix_world @ Vector((*co, 1.0))).xyz)

def view_forward_direction(context:Context) -> Vector:
    r3d = context.region_data
    mat = r3d.view_matrix
    return (mat.inverted_safe() @ Vector((0,0,-1,0))).xyz
def view_right_direction(context:Context) -> Vector:
    r3d = context.region_data
    mat = r3d.view_matrix
    return (mat.inverted_safe() @ Vector((1,0,0,0))).xyz
def view_up_direction(context:Context) -> Vector:
    r3d = context.region_data
    mat = r3d.view_matrix
    return (mat.inverted_safe() @ Vector((0,1,0,0))).xyz

def bbox_center(bmvs):
    maximum = Vector([
        max([v.co[0] for v in bmvs]),
        max([v.co[1] for v in bmvs]),
        max([v.co[2] for v in bmvs])
    ])
    minimum = Vector([
        min([v.co[0] for v in bmvs]),
        min([v.co[1] for v in bmvs]),
        min([v.co[2] for v in bmvs])
    ])
    average = (maximum - minimum) / 2
    return minimum + average

def distance_point_linesegment(pt:Vector|None, p0:Vector|None, p1:Vector|None, *, min_factor:float=0.05, max_factor:float=0.95, default:float=float('inf')) -> float:
    if not pt or not p0 or not p1:
        return default
    v01 = p1 - p0
    l01_squared = v01.length_squared
    if l01_squared <= 0.00001:
        return (pt - p0).length
    v0t = pt - p0
    f = clamp(v0t.dot(v01) / l01_squared, min_factor, max_factor)
    p = p0 + v01 * f
    return (pt - p).length

def distance_point_bmedge(pt, bme, **kwargs):
    bmv0, bmv1 = bme.verts
    return distance_point_linesegment(pt, bmv0.co, bmv1.co, **kwargs)

def distance2d_point_bmvert(context:Context, matrix:Matrix, pt3D:Vector|None, bmv:BMVert) -> float:
    if not pt3D: return float('inf')
    p = location_3d_to_region_2d(context.region, context.region_data, matrix @ pt3D)
    v = location_3d_to_region_2d(context.region, context.region_data, matrix @ bmv.co)
    return (p - v).length if p and v else float('inf')

def distance2d_point_bmedge(context:Context, matrix:Matrix, pt3D:Vector|None, bme:BMEdge) -> float:
    if not pt3D: return float('inf')
    bmv0, bmv1 = bme.verts
    p  = location_3d_to_region_2d(context.region, context.region_data, matrix @ pt3D)
    p0 = location_3d_to_region_2d(context.region, context.region_data, matrix @ bmv0.co)
    p1 = location_3d_to_region_2d(context.region, context.region_data, matrix @ bmv1.co)
    return distance_point_linesegment(p, p0, p1) if p and p0 and p1 else float('inf')

def closest_point_linesegment(pt:Vector|None, p0:Vector|None, p1:Vector|None) -> Vector|None:
    if not pt or not p0 or not p1: return None
    v01 = p1 - p0
    l01_squared = v01.length_squared
    if l01_squared < 1e-5: return p0  # p0 and p1 are basically coincident (#1581)
    f = clamp(v01.dot(pt - p0) / l01_squared, 0.0, 1.0)
    return p0 + v01 * f

def bvec_point_to_bvec4(v : Vector | Point | Sequence[float]) -> Vector:
    x, y, z, *_ = v
    return Vector((x, y, z, 1))

def bvec_vector_to_bvec4(v : Vector | Direction | Normal | Sequence[float]) -> Vector:
    x, y, z, *_ = v
    return Vector((x, y, z, 0))

def bvec_to_point(v : Point | Vector | Sequence[float]) -> Point:
    match v:
        case Point():
            return v
        case Vector():
            match len(v):
                case 3:
                    return Point(v)
                case 4:
                    x, y, z, w = v
                    return Point((x / w, y / w, z / w))
                case _:
                    assert False, f'Unhandled len of Vector {len(v)} ({v})'
        case [x, y, z]:
            return Point((x, y, z))
        case [x, y, z, w]:
            return Point((x / w, y / w, z / w))
        case _:
            assert False, f'Unhandled type {type(v)} ({v})'

def point_to_bvec3(pt : Point | Vector | Sequence[float]) -> Vector:
    match pt:
        case Point():
            return pt.as_vector()
        case Vector():
            match len(pt):
                case 3:
                    return pt
                case 4:
                    x, y, z, w = pt
                    return Vector((x / w, y / w, z / w))
                case _:
                    assert False, f'Unhandled len of Vector {len(pt)} ({pt})'
        case [x, y, z]:
            return Vector((x, y, z))
        case [x, y, z, w]:
            return Vector((x / w, y / w, z / w))
        case _:
            assert False, f'Unhandled type {type(pt)} ({pt})'

def point_to_bvec4(pt : Point | Vector | Sequence[float]) -> Vector:
    match pt:
        case Point():
            x, y, z = pt
            return Vector((x, y, z, 1))
        case Vector():
            match len(pt):
                case 3:
                    x, y, z = pt
                    return Vector((x, y, z, 1))
                case 4:
                    x, y, z, w = pt
                    return Vector((x / w, y / w, z / w, 1))
                case _:
                    assert False, f'Unhandled len of Vector {len(pt)} ({pt})'
        case [x, y, z]:
            return Vector((x, y, z, 1))
        case [x, y, z, w]:
            return Vector((x / w, y / w, z / w, 1))
        case _:
            assert False, f'Unhandled type {type(pt)} ({pt})'

def vector_to_bvec3(v : Vector | Sequence[float]) -> Vector:
    x, y, z, *_ = v
    return Vector((x, y, z))

def vector_to_bvec4(v : Vector) -> Vector:
    x, y, z, *_ = v
    return Vector((x, y, z, 0))

def direction_to_bvec3(v : Vector | Direction | Sequence[float]) -> Vector:
    x, y, z, *_ = v
    return Vector((x, y, z))

def direction_to_bvec4(v : Vector | Direction | Sequence[float]) -> Vector:
    x, y, z, *_ = v
    return Vector((x, y, z, 0))

def normal_to_bvec3(v : Normal | Vector | Sequence[float]) -> Vector:
    x, y, z, *_ = v
    return Vector((x, y, z))

def normal_to_bvec4(v : Normal | Vector | Sequence[float]) -> Vector:
    x, y, z, *_ = v
    return Vector((x, y, z, 0))

def map_range(value : float, from_min : float, from_max : float, to_min : float, to_max : float) -> float:
    from_span = from_max - from_min
    to_span = to_max - to_min
    scale_factor = float(to_span) / float(from_span)
    return to_min + (value - from_min) * scale_factor


@overload
def lerp(f : float, m : float, M : float) -> float:
    ...
@overload
def lerp(f : float, m : Vector, M : Vector) -> Vector:
    ...

def lerp(f : float, m : float | Vector, M : float | Vector) -> float | Vector:
    return m + f * (M - m)


def lerp_map(v : float, vm : float, vM : float, m : float, M : float) -> float:
    f = (v - vm) / (vM - vm)
    return m + f * (M - m)

def interp_piecewise(fracs : list[float], values : list[float], f : float, *, cyclic : bool = False) -> float:
    ''' Piecewise-linear lookup of `values`, indexed by the monotonic `fracs`
    (ascending, in [0,1]), at fraction f. Clamps to the ends outside range, unless
    `cyclic`, where the final span wraps back around to the first value. '''
    if cyclic and fracs:
        fracs = list(fracs) + [fracs[0] + 1.0]
        values = list(values) + [values[0]]
        f = fracs[0] + ((f - fracs[0]) % 1.0)
    if f <= fracs[0]:  return values[0]
    if f >= fracs[-1]: return values[-1]
    for i in range(1, len(fracs)):
        if f <= fracs[i]:
            f0, f1 = fracs[i - 1], fracs[i]
            span = f1 - f0
            t = 0.0 if span < 1e-12 else (f - f0) / span
            return values[i - 1] * (1 - t) + values[i] * t
    return values[-1]

def interp_direction(fracs : list[float], dirs : list[Vector], f : float, *, cyclic : bool = False) -> Vector | None:
    ''' Normalized lerp between the two directions bracketing fraction f. `fracs` is
    ascending in [0,1] and indexes `dirs`. A cyclic chain wraps the final span back
    around to the first direction. None if there's nothing usable to interpolate. '''
    n = min(len(fracs), len(dirs))
    if n == 0: return None
    xs = list(fracs[:n])
    vs = [Vector(d) for d in dirs[:n]]
    if n == 1:
        return vs[0].normalized() if vs[0].length > 1e-9 else None
    if cyclic:
        xs.append(xs[0] + 1.0)
        vs.append(Vector(vs[0]))
        f = xs[0] + ((f - xs[0]) % 1.0)
    if f <= xs[0]:
        v = vs[0]
    elif f >= xs[-1]:
        v = vs[-1]
    else:
        i = next(i for i in range(1, len(xs)) if f <= xs[i])
        span = xs[i] - xs[i - 1]
        t = 0.0 if span < 1e-12 else (f - xs[i - 1]) / span
        v = vs[i - 1] * (1 - t) + vs[i] * t
        if v.length < 1e-9:
            v = vs[i - 1] if t < 0.5 else vs[i]  # opposed neighbours cancelled: take the nearer
    return v.normalized() if v.length > 1e-9 else None

def xform_point(M : Matrix, p : Point | Vector) -> Vector:
    return point_to_bvec3(M @ bvec_point_to_bvec4(p))

def xform_vector(M : Matrix, v : Vector) -> Vector:
    return vector_to_bvec3(M @ bvec_vector_to_bvec4(v))

def xform_direction(M : Matrix, d : Direction | Vector) -> Vector:
    return vector_to_bvec3(M @ bvec_vector_to_bvec4(d)).normalized()

def xform_normal(Mit : Matrix, d : Normal | Vector) -> Vector:
    return vector_to_bvec3(Mit @ bvec_vector_to_bvec4(d)).normalized()


# return point on line segment where x/y/z is 0
# used for splitting line segments that cross mirror plane
def dir01(pt0, pt1): return (v := pt1 - pt0) / v.length
def pt_x0(pt0, pt1):
    d = dir01(pt0, pt1)
    if d.x == 0: return pt0
    pt = pt0 + d * (abs(pt0.x) / d.x)
    pt.x = 0
    return pt
def pt_y0(pt0, pt1):
    d = dir01(pt0, pt1)
    if d.y == 0: return pt0
    pt = pt0 + d * (abs(pt0.y) / d.y)
    pt.y = 0
    return pt
def pt_z0(pt0, pt1):
    d = dir01(pt0, pt1)
    if d.z == 0: return pt0
    pt = pt0 + d * (abs(pt0.z) / d.z)
    pt.z = 0
    return pt


def proportional_edit(falloff_type, dist):
    # see calculatePropRatio() in blender/source/blender/editors/transform/transform_generics.cc
    match falloff_type:
        case 'SMOOTH':
            return 3 * dist * dist - 2 * dist * dist * dist
        case 'SPHERE':
            return math.sqrt(2 * dist - dist * dist)
        case 'ROOT':
            return math.sqrt(dist)
        case 'INVERSE_SQUARE':
            return dist * (2 - dist)
        case 'SHARP':
            return dist * dist
        case 'LINEAR':
            return dist
        case 'CONSTANT':
            return 1
        case 'RANDOM':
            return random.random()
        case _:
            return 1

def perpendicular_direction2(vec2 : Vector, vec2_along : Vector) -> Vector:
    vec2_perp = Vector((-vec2.y, vec2.x)).normalized()
    if vec2_perp.dot(vec2_along) < 0:
        vec2_perp.negate()
    return vec2_perp


###############################################################################
# MARK: Planes
###############################################################################


def get_closest_axis(normal: Vector, axes: list[Vector]) -> Vector:
    '''Return the axis from `axes` (and its negatives) with the smallest angle to `normal`.'''
    best, best_dot = axes[0], -2.0
    for ax in axes:
        for candidate in (ax, -ax):
            d = normal.dot(candidate)
            if d > best_dot:
                best_dot, best = d, candidate
    return best

def snap_plane_x_to_direction(plane: Plane, hit: dict, orientation: str, context) -> Plane:
    '''Return a new plane with the same normal but with its local X axis snapped to `orientation`. '''
    if orientation == 'stroke': return plane

    origin  = plane.o
    normal  = Vector(plane.n)
    view_dir = view_forward_direction(context)

    # Recover approximate stroke direction (in-plane, perpendicular to view).
    stroke_dir = view_dir.cross(normal)
    if stroke_dir.length < 0.01:
        return plane  # view nearly parallel to normal, can't recover stroke direction
    stroke_dir.normalize()

    if orientation == 'world':
        axes = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
    elif orientation == 'local':
        M3 = hit['object'].matrix_world.to_3x3()
        axes = [M3.col[i].normalized() for i in range(3)]
    else:
        return plane

    best_x, best_dot = stroke_dir, -2.0
    for ax in axes:
        for candidate in (ax, -ax):
            # Project candidate onto the cut plane (remove normal component).
            proj = candidate - candidate.dot(normal) * normal
            if proj.length < 0.01:
                continue  # axis is parallel to normal, useless as an in-plane direction
            proj.normalize()
            d = stroke_dir.dot(proj)
            if d > best_dot:
                best_dot = d
                best_x = proj

    return Plane(origin, n=normal, x=best_x)


def snap_plane_to_direction(plane: Plane, hit: dict, orientation: str) -> Plane:
    '''Return a new plane with the same origin but with its normal aligned per `orientation`.'''
    if orientation == 'stroke': return plane

    origin = plane.o
    stroke_normal = Vector(plane.n)

    if orientation == 'world':
        axes = [Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))]
        new_normal = get_closest_axis(stroke_normal, axes)

    elif orientation == 'local':
        M3 = hit['object'].matrix_world.to_3x3()
        axes = [M3.col[i].normalized() for i in range(3)]
        new_normal = get_closest_axis(stroke_normal, axes)

    elif orientation == 'normal':
        face_normal = Vector(hit['no_world']).normalized()
        projected = stroke_normal - stroke_normal.dot(face_normal) * face_normal
        if projected.length > 0.01:
            new_normal = projected.normalized()
        else:
            return plane  # stroke is collinear with face normal so keep it as-is

    else:
        return plane

    return Plane(origin, new_normal)


###############################################################################
# MARK: Paths
###############################################################################


def get_co_on_arc(fac, order, cumul, total, initial_coords, mw):
    '''World space point at fractional position along a path. Wraps at 1.0.'''
    target = (fac % 1.0) * total
    n = len(order)
    for i in range(n):
        nxt = (i + 1) % n
        seg_end = cumul[nxt] if nxt != 0 else total
        if target <= seg_end + 1e-12 or i == n - 1:
            seg_len = seg_end - cumul[i]
            t = max(0.0, min(1.0, (target - cumul[i]) / seg_len)) if seg_len > 1e-12 else 0.0
            a = mw @ initial_coords[order[i]]
            b = mw @ initial_coords[order[nxt]]
            return a + t * (b - a)


def arc_path_factors(points: list, cyclic: bool) -> list:
    '''Path factor (0-1) for each point along a polyline arc.
    For cyclic paths the closing segment is included, so path_facs[-1] < 1.0.'''
    n = len(points)
    if n == 0: return []
    n_segs = n if cyclic else n - 1
    seg_lens = [(points[(i + 1) % n] - points[i]).length for i in range(n_segs)]
    total = sum(seg_lens)
    if total < 1e-10:
        return [0.0] * n
    cumul = [0.0]
    for sl in seg_lens:
        cumul.append(cumul[-1] + sl / total)
    return cumul[:n]


def path_facs_to_positions(points: list, path_facs: list, cyclic: bool) -> list:
    '''Return 3D positions on the polyline path at the given arc-length factors.'''
    n = len(points)
    if n == 0:
        return []
    n_segs = n if cyclic else n - 1
    seg_lens = [(points[(i + 1) % n] - points[i]).length for i in range(n_segs)]
    total = sum(seg_lens)
    if total < 1e-10:
        return [Vector(points[0]) for _ in path_facs]
    cumul_seg = [0.0]
    for sl in seg_lens:
        cumul_seg.append(cumul_seg[-1] + sl / total)
    result = []
    for path_fac in path_facs:
        path_fac = max(0.0, min(1.0, path_fac))
        seg_idx = n_segs - 1
        for i in range(n_segs):
            if cumul_seg[i + 1] >= path_fac - 1e-10:
                seg_idx = i
                break
        f0, f1 = cumul_seg[seg_idx], cumul_seg[seg_idx + 1]
        p0 = Vector(points[seg_idx % n])
        p1 = Vector(points[(seg_idx + 1) % n])
        if f1 - f0 < 1e-10:
            result.append(p0)
        else:
            result.append(p0.lerp(p1, max(0.0, min(1.0, (path_fac - f0) / (f1 - f0)))))
    return result


def project_to_path_fac(co, points: list, cyclic: bool, point_path_facs: list) -> float:
    '''Arc-length factor of the nearest point on the polyline to `co`.
    Requires precomputed point_path_facs from arc_path_factors().'''
    n = len(points)
    n_segs = n if cyclic else n - 1
    best_path_fac = 0.0
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
            f1 = point_path_facs[i + 1] if i + 1 < n else 1.0
            best_path_fac = point_path_facs[i] + t * (f1 - point_path_facs[i])
    return best_path_fac


def cyclic_even_phase(path_facs: list, step: float) -> float:
    '''Starting phase for an evenly spaced cyclic ring (`phase + i * step`)
    that moves the given path factors the least.'''
    n = len(path_facs)
    if n == 0: return 0.0
    # Average the residuals as unit vectors so the wrap at 0/1 does not skew the result
    sx = sy = 0.0
    for i, path_fac in enumerate(path_facs):
        angle = math.tau * ((path_fac - i * step) % 1.0)
        sx += math.cos(angle)
        sy += math.sin(angle)
    if sx * sx + sy * sy < 1e-12:
        # Residuals cancel each other out, so anchor on the member closest to the path start
        first = min(range(n), key=lambda k: path_facs[k])
        return (path_facs[first] - first * step) % 1.0
    return (math.atan2(sy, sx) / math.tau) % 1.0


def enforce_path_min_gap(path_facs: list, cyclic: bool, min_gap: float) -> list:
    '''Spread arc-length factors so no two consecutive values are closer than min_gap, staying as close to the input as possible.
    Cyclic paths are cut at their largest gap first so the wrap-around seam stays >= min_gap.'''
    n = len(path_facs)
    if n < 2 or min_gap <= 0.0 or n * min_gap >= 1.0:
        return path_facs

    if cyclic:
        gaps = [(path_facs[(i + 1) % n] - path_facs[i]) % 1.0 for i in range(n)]
        cut = max(range(n), key=lambda i: gaps[i])
        order = [(cut + 1 + k) % n for k in range(n)]
        pos = [path_facs[order[0]]]
        for k in range(1, n):
            pos.append(pos[-1] + (path_facs[order[k]] - path_facs[order[k - 1]]) % 1.0)
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
        result = list(path_facs)
        for k, idx in enumerate(order):
            result[idx] = (u_iso[k] + k * min_gap) % 1.0
        return result

    result = list(path_facs)
    lo, hi, prev = result[0], result[-1], result[0] - min_gap
    for i in range(n):
        result[i] = max(result[i], prev + min_gap); prev = result[i]
    nxt = hi + min_gap
    for i in range(n - 1, -1, -1):
        result[i] = min(result[i], nxt - min_gap); nxt = result[i]
    return result


def sample_even(points: list, cyclic: bool, vertex_count: int, path_length: float) -> list | None:
    '''Uniform arc-length sampling: iterative bisection to place exactly vertex_count points.
    Returns a list of Vectors or None on failure.'''
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


def get_face_adjacency(tris, return_everts=False):
    ''' Shared-edge face pairs (fa, fb) over a triangle index array (T,3).
        With return_everts, also returns the shared mesh-edge vert pair
        (E,2) per adjacency edge — e.g. for chaining boundary edges. '''
    edge_of = {}
    fa, fb, ev = [], [], []
    for t in range(len(tris)):
        a, b, c = int(tris[t, 0]), int(tris[t, 1]), int(tris[t, 2])
        for u, v in ((a, b), (b, c), (c, a)):
            k = (u, v) if u < v else (v, u)
            other = edge_of.pop(k, None)
            if other is None:
                edge_of[k] = t
            else:
                fa.append(other)
                fb.append(t)
                ev.append(k)
    fa = np.array(fa, dtype=np.int64)
    fb = np.array(fb, dtype=np.int64)
    if return_everts:
        return fa, fb, np.array(ev, dtype=np.int64)
    return fa, fb


def diffuse_graph_fields(fields, e0, e1, n, iters):
    ''' Repeated neighbor averaging of per-element fields (n, D) over the undirected edge lists e0/e1. '''
    deg = np.bincount(np.concatenate([e0, e1]),
                      minlength=n).astype(np.float64) + 1.0
    f = np.array(fields, dtype=np.float64)
    # k iterations approximate a geodesic Gaussian kernel of radius ~ mean_step * sqrt(k).
    for _ in range(iters):
        acc = f.copy()
        np.add.at(acc, e0, f[e1])
        np.add.at(acc, e1, f[e0])
        f = acc / deg[:, None]
    return f


def build_graph_pyramid(e0, e1, areas, centers, max_levels=6, min_nodes=400):
    ''' Gaussian pyramid over a graph for diffuse_graph_fields_pyramid:
        greedy 1-ring clustering per level (~3-4x node reduction),
        area-weighted centroids, unique super-node adjacency. Depends only
        on the graph — build once per mesh, reuse across feature scales. '''
    levels = []
    cur_e0, cur_e1 = np.asarray(e0), np.asarray(e1)
    cur_area = np.asarray(areas, dtype=np.float64)
    cur_ctr = np.asarray(centers, dtype=np.float64)
    n = len(cur_area)
    while len(levels) < max_levels and n > min_nodes:
        adj = [[] for _ in range(n)]
        for a, b in zip(cur_e0, cur_e1):
            adj[int(a)].append(int(b))
            adj[int(b)].append(int(a))
        cluster = np.full(n, -1, dtype=np.int64)
        nc = 0
        for i in range(n):
            if cluster[i] >= 0:
                continue
            cluster[i] = nc
            for nb in adj[i]:
                if cluster[nb] < 0:
                    cluster[nb] = nc
            nc += 1
        if nc >= n:
            break
        new_area = np.zeros(nc)
        np.add.at(new_area, cluster, cur_area)
        new_ctr = np.zeros((nc, 3))
        np.add.at(new_ctr, cluster, cur_ctr * cur_area[:, None])
        new_ctr /= np.maximum(new_area[:, None], 1e-30)
        ca, cb = cluster[cur_e0], cluster[cur_e1]
        m = ca != cb
        if not m.any():
            break
        pairs = np.unique(np.stack([np.minimum(ca[m], cb[m]),
                                    np.maximum(ca[m], cb[m])], axis=1),
                          axis=0)
        step = float(np.linalg.norm(new_ctr[pairs[:, 0]]
                                    - new_ctr[pairs[:, 1]], axis=1).mean())
        levels.append(dict(cluster=cluster, src_e0=cur_e0, src_e1=cur_e1,
                           src_n=n, src_area=cur_area,
                           e0=pairs[:, 0], e1=pairs[:, 1], n=nc, step=step))
        cur_e0, cur_e1, cur_area, cur_ctr, n = (pairs[:, 0], pairs[:, 1],
                                                new_area, new_ctr, nc)
    return levels


def diffuse_graph_fields_pyramid(fields, radius, e0, e1, n, mean_step,
                                 pyramid, fine_k_max=64, polish=2):
    ''' Smooth per-element fields (n, D) at geodesic `radius`. Small radii
        run exact fine-graph diffusion; large radii restrict down the
        pyramid to the coarsest level that still resolves the radius
        (step <= radius/4), smooth there with (radius/step)^2 iterations
        (bounded ~16..64 by the level choice), and prolong back up with a
        few polish iterations per level — replacing the (radius/step)^2
        fine-iteration explosion with near-constant cost. '''
    k_fine = max(1, round((radius / max(mean_step, 1e-12)) ** 2))
    if k_fine <= fine_k_max or not pyramid:
        return diffuse_graph_fields(fields, e0, e1, n, min(k_fine, 400))
    f = np.array(fields, dtype=np.float64)
    used = []
    for lvl in pyramid:
        if lvl['step'] > radius / 4.0:
            break
        w = lvl['src_area']
        acc = np.zeros((lvl['n'], f.shape[1]))
        np.add.at(acc, lvl['cluster'], f * w[:, None])
        wsum = np.zeros(lvl['n'])
        np.add.at(wsum, lvl['cluster'], w)
        f = acc / np.maximum(wsum[:, None], 1e-30)
        used.append(lvl)
    if not used:
        return diffuse_graph_fields(fields, e0, e1, n, min(k_fine, 400))
    top = used[-1]
    k = int(np.clip(round((radius / top['step']) ** 2), 1, 256))
    f = diffuse_graph_fields(f, top['e0'], top['e1'], top['n'], k)
    for lvl in reversed(used):
        f = f[lvl['cluster']]
        f = diffuse_graph_fields(f, lvl['src_e0'], lvl['src_e1'],
                                 lvl['src_n'], polish)
    return f


def diffusion_iters_for_radius(smoothing_radius, mean_step, cap=400):
    ''' Diffusion iteration count approximating a geodesic Gaussian blur of `smoothing_radius`
    on a graph whose mean adjacent-element distance is `mean_step`. '''
    return int(np.clip(round((smoothing_radius / max(mean_step, 1e-12)) ** 2), 1, cap))
