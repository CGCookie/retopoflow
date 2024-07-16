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

def distance_point_bmedge(pt, bme):
    bmv0, bmv1 = bme.verts
    return distance_point_linesegment(pt, bmv0.co, bmv1.co)

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
    v0t = pt - p0
    f = clamp(v0t.dot(v01) / l01_squared, 0.0, 1.0)
    return p0 + v01 * f

def bvec_to_point(v):
    return Point((*point_to_bvec3(v), 1.0))
def point_to_bvec3(pt):
    return pt.xyz / pt.w if len(pt) == 4 else pt.xyz
def vector_to_bvec3(v):
    return v.xyz

def lerp(f, m, M): return m + f * (M - m)



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
