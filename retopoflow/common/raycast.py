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
from bpy_extras.view3d_utils import region_2d_to_origin_3d
from bpy_extras.view3d_utils import region_2d_to_vector_3d

def distance_between_locations(a, b):
    a = a.xyz / a.w
    b = b.xyz / b.w
    return (a - b).length

def ray_from_mouse(context, event):
    mouse = (event.mouse_region_x, event.mouse_region_y)
    if not context.region_data: return (None, None)
    return (
        Vector((*region_2d_to_origin_3d(context.region, context.region_data, mouse), 1.0)),
        Vector((*region_2d_to_vector_3d(context.region, context.region_data, mouse).normalized(), 0.0)),
    )

def ray_from_point(context, point):
    if not context.region_data: return (None, None)
    return (
        Vector((*region_2d_to_origin_3d(context.region, context.region_data, point), 1.0)),
        Vector((*region_2d_to_vector_3d(context.region, context.region_data, point).normalized(), 0.0)),
    )

def iter_all_valid_sources(context):
    yield from (
        obj
        for obj in context.scene.objects
        if (
            obj.type == 'MESH' and
            obj.mode == 'OBJECT' and
            not obj.hide_get() and
            not obj.hide_select and
            not obj.hide_viewport
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

def raycast_mouse_valid_sources(context, event, *, world=True):
    ray_world = ray_from_mouse(context, event)
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
        result, co, normal, idx = obj.ray_cast(ray_local[0].xyz / ray_local[0].w, ray_local[1].xyz)
        if not result: continue
        co_world = M @ Vector((*co, 1.0))
        dist = distance_between_locations(ray_world[0], co_world)
        # print(f'  HIT {obj.name} {co_world} {dist}')
        if dist >= best_dist: continue
        best_hit = co_world
        best_dist = dist
    if not best_hit: return None

    hit = Vector((*(best_hit.xyz / best_hit.w), 1.0))
    if not world:
        M = context.active_object.matrix_world
        Mi = M.inverted()
        hit = Mi @ hit
    return hit.xyz

def raycast_point_valid_sources(context, point, *, world=True):
    ray_world = ray_from_point(context, point)
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
        result, co, normal, idx = obj.ray_cast(ray_local[0].xyz / ray_local[0].w, ray_local[1].xyz)
        if not result: continue
        co_world = M @ Vector((*co, 1.0))
        dist = distance_between_locations(ray_world[0], co_world)
        # print(f'  HIT {obj.name} {co_world} {dist}')
        if dist >= best_dist: continue
        best_hit = co_world
        best_dist = dist
    if not best_hit: return None

    hit = Vector((*(best_hit.xyz / best_hit.w), 1.0))
    if not world:
        M = context.active_object.matrix_world
        Mi = M.inverted()
        hit = Mi @ hit
    return hit.xyz
