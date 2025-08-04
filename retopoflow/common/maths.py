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

import math
import numpy as np
import random

from ...addon_common.common.maths import clamp, Point, Vector, Normal

def view_forward_direction(context):
    r3d = context.region_data
    mat = r3d.view_matrix
    return (mat.inverted() @ Vector((0,0,-1,0))).xyz
def view_right_direction(context):
    r3d = context.region_data
    mat = r3d.view_matrix
    return (mat.inverted() @ Vector((1,0,0,0))).xyz
def view_up_direction(context):
    r3d = context.region_data
    mat = r3d.view_matrix
    return (mat.inverted() @ Vector((0,1,0,0))).xyz


def distance_point_linesegment(pt, p0, p1, *, min_factor=0.05, max_factor=0.95, default=float('inf')):
    if not pt or not p0 or not p1: return default
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

def distance2d_point_bmedge(context, matrix, pt, bme):
    bmv0, bmv1 = bme.verts
    p  = location_3d_to_region_2d(context.region, context.region_data, matrix @ pt)
    p0 = location_3d_to_region_2d(context.region, context.region_data, matrix @ bmv0.co)
    p1 = location_3d_to_region_2d(context.region, context.region_data, matrix @ bmv1.co)
    if not p or not p0 or not p1: return float('inf')
    return distance_point_linesegment(p, p0, p1)

def closest_point_linesegment(pt, p0, p1):
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
def point_to_bvec3(pt):
    return pt.xyz / pt.w if len(pt) == 4 else pt.xyz
def point_to_bvec4(pt):
    return Vector((*point_to_bvec3(pt), 1))
def vector_to_bvec3(v):
    return v.xyz
def vector_to_bvec4(v):
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

def xform_point(M, p):
    return point_to_bvec3(M @ bvec_point_to_bvec4(p))
def xform_vector(M, v):
    return vector_to_bvec3(M @ bvec_vector_to_bvec4(v))
def xform_direction(M, d):
    return vector_to_bvec3(M @ bvec_vector_to_bvec4(d)).normalized()
def xform_normal(Mit, d):
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