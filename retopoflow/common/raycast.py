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

from mathutils import Vector
from bpy_extras.view3d_utils import region_2d_to_origin_3d
from bpy_extras.view3d_utils import region_2d_to_vector_3d

def distance_between_locations(a, b):
    a = a.xyz / a.w
    b = b.xyz / b.w
    return (a - b).length

def ray_from_mouse(context, event):
    mouse = (event.mouse_region_x, event.mouse_region_y)
    return (
        Vector((*region_2d_to_origin_3d(context.region, context.region_data, mouse), 1.0)),
        Vector((*region_2d_to_vector_3d(context.region, context.region_data, mouse).normalized(), 0.0)),
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

def raycast_mouse_valid_sources(context, event):
    ray_world = ray_from_mouse(context, event)

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
    M = context.active_object.matrix_world
    Mi = M.inverted()
    hit = Mi @ hit
    return hit.xyz

