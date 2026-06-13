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

from ...addon_common.common.maths import clamp, Point, Vector, Normal, Plane

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

def bvec_point_to_bvec4(v):
    return Vector((v[0], v[1], v[2], 1))
def bvec_vector_to_bvec4(v):
    return Vector((v[0], v[1], v[2], 0))
def bvec_to_point(v):
    return Point((*point_to_bvec3(v), 1.0))
def point_to_bvec3(pt : Point|Vector|Sequence[float]) -> Vector:
    if len(pt) == 4:
        x,y,z,w = pt
        return Vector((x/w, y/w, z/w))
    x,y,z = pt
    return Vector((x,y,z))
def point_to_bvec4(pt):
    return Vector((*point_to_bvec3(pt), 1))
def vector_to_bvec3(v):
    return v.xyz
def vector_to_bvec4(v):
    return Vector((*v.xyz, 0))
def direction_to_bvec3(v:Vector|Sequence[float]) -> Vector:
    x,y,z,*_ = v
    return Vector((x,y,z))
def direction_to_bvec4(v):
    return Vector((*v.xyz, 0))
def normal_to_bvec3(v):
    return v.xyz
def normal_to_bvec4(v):
    return Vector((*v.xyz, 0))

def map_range(value, from_min, from_max, to_min, to_max):
    from_span = from_max - from_min
    to_span = to_max - to_min
    scale_factor = float(to_span) / float(from_span)
    return to_min + (value - from_min) * scale_factor

def lerp(f, m, M): return m + f * (M - m)
def lerp_map(v, vm, vM, m, M):
    f = (v - vm) / (vM - vm)
    return m + f * (M - m)

def xform_point(M : Matrix, p : Vector) -> Vector:
    return point_to_bvec3(M @ bvec_point_to_bvec4(p))
def xform_vector(M : Matrix, v : Vector) -> Vector:
    return vector_to_bvec3(M @ bvec_vector_to_bvec4(v))
def xform_direction(M : Matrix, d : Vector) -> Vector:
    return vector_to_bvec3(M @ bvec_vector_to_bvec4(d)).normalized()
def xform_normal(Mit : Matrix, d : Vector) -> Vector:
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

def get_closest_axis(normal: Vector, axes: list[Vector]) -> Vector:
    '''Return the axis from `axes` (and its negatives) with the smallest angle to `normal`.'''
    best, best_dot = axes[0], -2.0
    for ax in axes:
        for candidate in (ax, -ax):
            d = normal.dot(candidate)
            if d > best_dot:
                best_dot, best = d, candidate
    return best

def snap_plane_to_direction(plane: Plane, hit: dict, orientation: str) -> Plane:
    '''Return a new plane with the same origin but with its normal aligned per `orientation`.'''
    if orientation == 'stroke':
        return plane

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