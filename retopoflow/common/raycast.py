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

import time

from mathutils import Vector
from bpy_extras.view3d_utils import (
    region_2d_to_origin_3d,
    region_2d_to_vector_3d,
    region_2d_to_location_3d,
    location_3d_to_region_2d,
)

from .maths import point_to_bvec3, vector_to_bvec3, point_to_bvec4, vector_to_bvec4

def mouse_from_event(event): return (event.mouse_region_x, event.mouse_region_y)

def vec_forward(context):
    # TODO: remove invert!
    r3d = context.space_data.region_3d
    return r3d.view_matrix.to_3x3().inverted_safe() @ Vector((0,0,-1))

def distance_between_locations(a, b):
    a, b = point_to_bvec3(a), point_to_bvec3(b)
    return (a - b).length

def point2D_to_point(context, xy, depth:float):
    r = ray_from_point(context, xy)
    return (r[0] + r[1] * depth) if r[0] and r[1] else None

def size2D_to_size(context, depth3D):
    # note: scaling then unscaling helps with numerical instability when clip_start is small
    w, h = context.region.width * 0.5, context.region.height * 0.5
    scale = min(w, h)
    # find center of screen
    xy0, xy1 = Vector((w, h)), Vector((w + scale, h))
    p3d0, p3d1 = point2D_to_point(context, xy0, depth3D), point2D_to_point(context, xy1, depth3D)
    if not p3d0 or not p3d1: return None
    return (p3d0 - p3d1).length / scale

def ray_from_mouse(context, event):
    mouse = (event.mouse_region_x, event.mouse_region_y)
    if not context.region_data: return (None, None)
    return (
        Vector((*region_2d_to_origin_3d(context.region, context.region_data, mouse), 1.0)),
        Vector((*region_2d_to_vector_3d(context.region, context.region_data, mouse).normalized(), 0.0)),
    )

def ray_from_point(context, point):
    if not context.region_data: return (None, None)
    if len(point) > 2:
        point = location_3d_to_region_2d(context.region, context.region_data, point)
        if not point: return (None, None)
    return (
        Vector((*region_2d_to_origin_3d(context.region, context.region_data, point), 1.0)),
        Vector((*region_2d_to_vector_3d(context.region, context.region_data, point).normalized(), 0.0)),
    )

def plane_normal_from_points(context, p0, p1):
    if not context.region_data: return (None, None)
    if len(p0) > 2:
        p0 = location_3d_to_region_2d(context.region, context.region_data, p0)
        if not p0: return (None, None)
    if len(p1) > 2:
        p1 = location_3d_to_region_2d(context.region, context.region_data, p1)
        if not p1: return (None, None)
    w, h = context.area.width, context.area.height
    q0 = region_2d_to_origin_3d(context.region, context.region_data, Vector((w/2, h/2)))
    q1 = region_2d_to_location_3d(context.region, context.region_data, p0, context.edit_object.location)
    q2 = region_2d_to_location_3d(context.region, context.region_data, p1, context.edit_object.location)
    d0 = (q1 - q0).normalized()
    d1 = (q2 - q0).normalized()
    # the following does _not_ work with orthographic projection, because directions are parallel
    #d0 = region_2d_to_vector_3d(context.region, context.region_data, p0).normalized()
    #d1 = region_2d_to_vector_3d(context.region, context.region_data, p1).normalized()
    return d0.cross(d1).normalized()

def iter_all_valid_sources(context):
    yield from (
        obj
        for obj in context.view_layer.objects
        if (
            obj.type == 'MESH' and
            obj.mode == 'OBJECT' and
            not obj.hide_get() and
            obj.visible_get() and
            not obj.hide_select and
            not obj.hide_viewport and
            bool(obj.data.polygons)
        )
    )

# Note: the initial call to obj.ray_cast can take a noticeable moment if obj is really big (>1m triangles)
# while the BVH is built.  Every subsequent call to obj.ray_cast is very fast due to BVH being cached.
# This function forces Blender to generate BVHs for all source objects, so we can control when they are built.
def prep_raycast_valid_sources(context):
    print(f'CACHING BVHS FOR ALL SOURCE OBJECTS')
    start = time.time()
    for obj in iter_all_valid_sources(context):
        obj.ray_cast(Vector((0,0,0)), Vector((1,0,0)))
    print(f'  {time.time() - start:0.2f}secs')

def raycast_valid_sources(context, point_world):
    ray_world = ray_from_point(context, point_world)

    # print(f'raycast_valid_sources {ray_world=}')
    if ray_world[0] is None: return None

    best = None

    Me = context.edit_object.matrix_world
    Mei = Me.inverted()
    Met = Me.transposed()
    for obj in iter_all_valid_sources(context):
        M   = obj.matrix_world
        Mi  = M.inverted()
        Mit = Mi.transposed()
        #Mt  = M.transposed()
        ray_local = (
            (Mi @ ray_world[0]),
            (Mi @ ray_world[1]).normalized(),
        )
        result, co_hit, no_hit, idx = obj.ray_cast(point_to_bvec3(ray_local[0]), vector_to_bvec3(ray_local[1]))
        if not result: continue

        no_hit = no_hit.normalized()

        co_world = point_to_bvec3(M @ point_to_bvec4(co_hit))
        no_world  = vector_to_bvec3(Mit @ vector_to_bvec4(no_hit)).normalized()
        dist = distance_between_locations(ray_world[0], co_world)
        # print(co_hit, dist)

        if best and best['distance'] <= dist: continue

        co_local = point_to_bvec3(Mei @ point_to_bvec4(co_world))
        no_local = vector_to_bvec3(Met @ vector_to_bvec4(no_world)).normalized()

        best = {
            'ray_world':  ray_world,  # ray based on point_world
            'distance':   dist,       # world distance between ray origin and hit point
            'object':     obj,       'face_index': idx,        # hit object and face index
            'co_local':   co_local,  'no_local':   no_local,   # co and normal wrt to active object
            'co_hit':     co_hit,    'no_hit':     no_hit,     # co and normal wrt to hit object
            'co_world':   co_world,  'no_world':   no_world,   # co and normal in world space
        }
    return best

    # if not best: return None

    # if not world:

    # hit = Vector((*(best_hit.xyz / best_hit.w), 1.0))
    # if not world:
    #     M = context.edit_object.matrix_world
    #     Mi = M.inverted()
    #     hit = Mi @ hit
    # return hit.xyz

def raycast_point_valid_sources(context, point_world, *, world=True):
    ray_world = ray_from_point(context, point_world)
    if ray_world[0] is None: return None

    best_hit = None
    best_dist = float('inf')
    # print(f'RAY {ray_world}')
    for obj in iter_all_valid_sources(context):
        M = obj.matrix_world
        Mi = M.inverted()
        ray_local = (
            Mi @ ray_world[0],
            (Mi @ ray_world[1]).normalized(),
        )
        result, co, normal, idx = obj.ray_cast(point_to_bvec3(ray_local[0]), vector_to_bvec3(ray_local[1]))
        if not result: continue
        co_world = M @ Vector((*co, 1.0))
        dist = distance_between_locations(ray_world[0], co_world)
        # print(f'  HIT {obj.name} {co_world} {dist}')
        if dist >= best_dist: continue
        best_hit = co_world
        best_dist = dist
    if not best_hit: return None

    hit = Vector((*point_to_bvec3(best_hit), 1.0))
    if not world:
        M = context.active_object.matrix_world
        Mi = M.inverted()
        hit = Mi @ hit
    return point_to_bvec3(hit)

def nearest_point_valid_sources(context, point, *, world=True):
    point_world = Vector((*point, 1.0))
    best_hit = None
    best_dist = float('inf')
    # print(f'RAY {ray_world}')
    for obj in iter_all_valid_sources(context):
        M = obj.matrix_world
        Mi = M.inverted()
        point_local = Mi @ Vector((*point, 1.0))
        result, co, normal, idx = obj.closest_point_on_mesh(point_local.xyz)
        if not result: continue
        co_world = M @ Vector((*co, 1.0))
        dist = distance_between_locations(point_world, co_world)
        # print(f'  HIT {obj.name} {co_world} {dist}')
        if dist >= best_dist: continue
        best_hit = co_world
        best_dist = dist
    if not best_hit: return None

    hit = Vector((*point_to_bvec3(best_hit), 1.0))
    if not world:
        M = context.active_object.matrix_world
        Mi = M.inverted()
        hit = Mi @ hit
    return point_to_bvec3(hit)

def nearest_normal_valid_sources(context, point, *, world=True):
    point_world = Vector((*point, 1.0))
    best_hit = None
    best_dist = float('inf')
    # print(f'RAY {ray_world}')
    for obj in iter_all_valid_sources(context):
        M = obj.matrix_world
        Mi = M.inverted()
        point_local = Mi @ point
        result, co, normal, idx = obj.closest_point_on_mesh(point_local)
        if not result: continue
        co_world = M @ Vector((*co, 1.0))
        no_world = M @ Vector((*normal, 0.0))
        dist = distance_between_locations(point_world, co_world)
        # print(f'  HIT {obj.name} {co_world} {dist}')
        if dist >= best_dist: continue
        best_hit = no_world
        best_dist = dist
    if not best_hit: return None

    hit = Vector((*vector_to_bvec3(best_hit), 0.0))
    if not world:
        M = context.active_object.matrix_world
        Mi = M.inverted()
        hit = Mi @ hit
    return vector_to_bvec3(hit)
