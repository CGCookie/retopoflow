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
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d

from .bmesh import (
    get_bmesh_emesh,
    bme_midpoint, get_boundary_strips_cycles,
    bme_other_bmv,
    bmes_shared_bmv,
    bme_unshared_bmv,
    bmvs_shared_bme,
    bme_vector,
    bme_length,
)
from .raycast import raycast_point_valid_sources
from .maths import view_forward_direction, lerp
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bezier import interpolate_cubic
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import closest_point_segment, segment2D_intersection
from ...addon_common.common.maths import clamp
from ...addon_common.common.utils import iter_pairs

import math


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

