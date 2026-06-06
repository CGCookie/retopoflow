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
import math
from typing import Callable
from collections.abc import Sequence, Iterable

from bpy.types import Context, Event, Scene, Region, RegionView3D
from bpy.types import Object as BObject
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import (
    region_2d_to_origin_3d,
    region_2d_to_vector_3d,
    region_2d_to_location_3d,
    location_3d_to_region_2d,
)

from .maths import (
    point_to_bvec3, vector_to_bvec3, point_to_bvec4, vector_to_bvec4, direction_to_bvec3,
    xform_point, xform_vector, xform_direction, xform_normal,
)

def mouse_from_event(event:Event) -> tuple[int, int]:
    return (event.mouse_region_x, event.mouse_region_y)

def vec_forward(context : Context) -> Vector:
    # TODO: remove invert!
    r3d = context.space_data.region_3d
    return r3d.view_matrix.to_3x3().inverted_safe() @ Vector((0,0,-1))
def vec_right(context : Context) -> Vector:
    # TODO: remove invert!
    r3d = context.space_data.region_3d
    return r3d.view_matrix.to_3x3().inverted_safe() @ Vector((1,0,0))
def vec_up(context : Context) -> Vector:
    # TODO: remove invert!
    r3d = context.space_data.region_3d
    return r3d.view_matrix.to_3x3().inverted_safe() @ Vector((0,1,0))

def distance_between_locations(a:Vector, b:Vector) -> float:
    a, b = point_to_bvec3(a), point_to_bvec3(b)
    return (a - b).length

def point2D_to_point(context, xy, depth:float):
    r = ray_from_point(context, xy)
    return (r[0] + r[1] * depth) if r[0] and r[1] else None

def size2D_to_size_point(context, point_screen, depth_location):
    # this function is not working correctly...
    w, h = context.region.width * 0.5, context.region.height * 0.5
    # note: scaling then unscaling helps with numerical instability when clip_start is small
    scale = min(w, h)
    # find center of screen
    xy0, xy1 = Vector(point_screen), Vector((point_screen[0] + scale, point_screen[1]))
    p3d0 = region_2d_to_location_3d(context.region, context.region_data, xy0, depth_location)
    p3d1 = region_2d_to_location_3d(context.region, context.region_data, xy1, depth_location)
    if not p3d0 or not p3d1: return None
    return (p3d0 - p3d1).length / scale

def prettyprint_matrices(*args, format='% 7.3f'):
    # assuming all matrices and labels are same size!!
    # assuming all values are -100 < v < 100
    # https://en.wikipedia.org/wiki/Box-drawing_characters
    count = len(args) // 2
    labels   = args[0::2]
    matrices = args[1::2]
    l = len(matrices[0])
    spc = ' ' * len(labels[0])

    line = []
    for j in range(count):
        w = len(matrices[j])
        line.append(spc + '┌' + (' '*(w*8-1)) + ' ┐')
    print('  '.join(line))

    for i in range(l):
        line = []
        for j in range(count):
            label, M = labels[j], matrices[j]
            lbl = label if i==(l-1)//2 else spc
            vals = ' '.join(format%v for v in M[i])
            line.append(lbl + '│' + vals + ' │')
        print('  '.join(line))

    line = []
    for j in range(count):
        w = len(matrices[j])
        line.append(spc + '└' + (' '*(w*8-1)) + ' ┘')
    print('  '.join(line))

def size2D_to_size(context, depth3D, *, pt=None):
    w, h = context.region.width * 0.5, context.region.height * 0.5
    scale = min(w, h)

    # note: scaling then unscaling helps with numerical instability when clip_start is small
    # find center of screen
    if not pt:
        pt = Vector((w, h))
    else:
        pt = Vector((pt[0], pt[1]))
    xy = pt
    xy0, xy1 = xy + Vector((-scale, 0)), xy + Vector((scale, 0))
    xy2, xy3 = xy + Vector((0, -scale)), xy + Vector((0, scale))
    p3d = point2D_to_point(context, xy, depth3D)
    p3d0, p3d1 = point2D_to_point(context, xy0, depth3D), point2D_to_point(context, xy1, depth3D)
    p3d2, p3d3 = point2D_to_point(context, xy2, depth3D), point2D_to_point(context, xy3, depth3D)
    if not p3d or not p3d0 or not p3d1 or not p3d2 or not p3d3: return None
    # if not p3d0 or not p3d1: return None
    d0, d1 = (p3d0 - p3d).length, (p3d1 - p3d).length
    d2, d3 = (p3d2 - p3d).length, (p3d3 - p3d).length
    d = (d0 + d1 + d2 + d3) / 4
    # print(f'{d0} {d1} {d2} {d3}')
    return d / scale

def ray_from_mouse(context, event):
    mouse = (event.mouse_region_x, event.mouse_region_y)
    if not context.region_data: return (None, None)
    return (
        Vector((*region_2d_to_origin_3d(context.region, context.region_data, mouse), 1.0)),
        Vector((*region_2d_to_vector_3d(context.region, context.region_data, mouse).normalized(), 0.0)),
    )

def direction_from_mouse(context, event) -> Vector:
    if not context.region_data: return (None, None)
    mouse = (event.mouse_region_x, event.mouse_region_y)
    v = region_2d_to_vector_3d(context.region, context.region_data, mouse).normalized()
    return Vector(( v.x, v.y, v.z, 0.0 ))

def direction_from_point(context, point_screen_or_world) -> Vector:
    if not context.region_data: return (None, None)
    if len(point_screen_or_world) > 2:
        point_screen = location_3d_to_region_2d(context.region, context.region_data, point_screen_or_world)
        if not point_screen: return (None, None)
    else:
        point_screen = point_screen_or_world
    v = region_2d_to_vector_3d(context.region, context.region_data, point_screen).normalized()
    return Vector(( v.x, v.y, v.z, 0.0 ))

def ray_from_point(context:Context, point_screen_or_world:Vector|Sequence[float]) -> tuple[Vector|None, Vector|None]:
    # if point is 2d, treat as being in screen space
    # if 3d, treat as world space
    if not context.region_data or not point_screen_or_world: return (None, None)
    if len(point_screen_or_world) > 2:
        point_screen : Sequence[float] = location_3d_to_region_2d(context.region, context.region_data, point_screen_or_world)
        if not point_screen: return (None, None)
    else:
        point_screen : Sequence[float] = point_screen_or_world
    return (
        Vector((*region_2d_to_origin_3d(context.region, context.region_data, point_screen), 1.0)),
        Vector((*region_2d_to_vector_3d(context.region, context.region_data, point_screen).normalized(), 0.0)),
    )

def ray_from_point_through_point(context, pt0_world, pt1_world):
    if not context.region_data: return (None, None)
    d01 = (pt1_world - pt0_world).normalized()
    return (
        Vector((pt0_world[0], pt0_world[1], pt0_world[2], 1.0)),
        Vector((d01[0], d01[1], d01[2], 0.0)),
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

def is_point_hidden(context, co_edit, *, factor=1.0, use_offset=True):
    M = context.edit_object.matrix_world
    co_world = M @ point_to_bvec4(co_edit)
    hit = raycast_valid_sources(context, co_world)
    if not hit: return False
    ray_e = hit['ray_world'][0]
    offset = context.space_data.overlay.retopology_offset if use_offset else 0.0
    return hit['distance'] + offset < (ray_e.xyz - co_world.xyz).length * factor

def has_faces(context, obj):
    if obj.type == 'MESH' and bool(obj.data.polygons):
        return True
    elif obj.type in ['CURVE', 'SURFACE', 'META', 'FONT']:
        depsgraph = context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        if not eval_mesh:
            # Conversion to mesh can fail (e.g. invalid geometry, as in the case of a curve object with an unlinked GN modifier); treat as empty.
            return False
        result = bool(eval_mesh.polygons)
        eval_obj.to_mesh_clear()
        return result
    else:
        return False

def is_valid_source(context:Context, obj:BObject) -> bool:
    scene : Scene|None = context.scene
    if not scene: return False
    ts = scene.tool_settings
    props = getattr(scene, 'retopoflow').snapping
    if obj.mode != 'OBJECT': return False
    if not obj.visible_get(): return False
    if not has_faces(context, obj): return False
    if props.snap_object:
        return obj == props.snap_object
    else:
        if props.snap_collection and obj not in [x for x in props.snap_collection.objects]:
            return False
        if ts.use_snap_selectable and obj.hide_select:
            return False
        if props.snap_only_selected and not obj.select_get():
            return False
        return True

def iter_all_valid_sources(context:Context) -> Iterable[BObject]:
    yield from (
        obj
        for obj in context.view_layer.objects
        if is_valid_source(context, obj)
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

def raycast_valid_sources(context : Context, point : Vector|Sequence[float]|None) -> dict[str,tuple[Vector,Vector]|float|int|object|Vector|Sequence[float]]|None:
    if not point:
        return None

    ray_world = ray_from_point(context, point)

    # print(f'raycast_valid_sources {ray_world=}')
    if ray_world[0] is None: return None

    best = None

    Me = context.edit_object.matrix_world
    Mei = Me.inverted_safe()
    Met = Me.transposed()
    for obj in iter_all_valid_sources(context):
        M   = obj.matrix_world
        Mi  = M.inverted_safe()
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



def raycast_point_valid_sources(context:Context, point_screen_or_world:Vector, **kwargs) -> Vector|None:
    ray_e_world, ray_d_world = ray_from_point(context, point_screen_or_world)
    if not ray_e_world or not ray_d_world: return None
    return raycast_ray_valid_sources(context, (ray_e_world, ray_d_world), **kwargs)

def raycast_ray_valid_sources(context:Context, ray_world:tuple[Vector,Vector], *, world:bool=True) -> Vector|None:
    if ray_world[0] is None: return None

    best_hit = None
    best_dist = float('inf')
    # print(f'RAY {ray_world}')
    for obj in iter_all_valid_sources(context):
        M = obj.matrix_world
        Mi = M.inverted_safe()
        ray_local = (
            Mi @ ray_world[0],
            (Mi @ vector_to_bvec4(ray_world[1])).normalized(),
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
        M = context.edit_object.matrix_world
        Mi = M.inverted_safe()
        hit = Mi @ hit
    return point_to_bvec3(hit)

def nearest_point_valid_sources(context:Context, point_world:Vector, *, world:bool=True, sources=None) -> Vector|None:
    point_world = Vector((*point_world, 1.0))
    best_hit = None
    best_dist = float('inf')

    # Callers in a tight per-vert loop can pass a precomputed `sources` iterable of
    # (obj, matrix_world, matrix_world_inv[, ...]) tuples to avoid re-filtering the view
    # layer and re-inverting matrices on every call.
    if sources is None:
        sources = ((obj, obj.matrix_world, obj.matrix_world.inverted_safe()) for obj in iter_all_valid_sources(context))

    # print(f'RAY {ray_world}')
    for src in sources:
        obj, M, Mi = src[0], src[1], src[2]
        point_local = Mi @ point_world
        result, co, normal, idx = obj.closest_point_on_mesh(point_local.xyz)
        if not result: continue
        co_world = M @ Vector((*co, 1.0))
        dist = distance_between_locations(point_world, co_world)
        # print(f'  HIT {obj.name} {co_world} {dist}')
        if dist >= best_dist: continue
        best_hit = co_world
        best_dist = dist

    if not best_hit:
        return None

    hit = Vector((*point_to_bvec3(best_hit), 1.0))
    if not world:
        M = context.edit_object.matrix_world
        Mi = M.inverted_safe()
        hit = Mi @ hit
    return point_to_bvec3(hit)

def nearest_normal_valid_sources(context, point_world, *, world=True):
    best_no_world = None
    best_dist = float('inf')
    # print(f'RAY {ray_world}')
    for obj in iter_all_valid_sources(context):
        M = obj.matrix_world
        Mi = M.inverted_safe()
        Mit = Mi.transposed()
        point_local = point_to_bvec3(xform_point(Mi, point_world))
        result, co, normal, idx = obj.closest_point_on_mesh(point_local)
        if not result: continue
        co_world = xform_point(M, co)
        no_world = xform_normal(Mit, normal)
        dist = distance_between_locations(point_world, co_world)
        # print(f'  HIT {obj.name} {co_world} {dist}')
        if dist >= best_dist: continue
        best_no_world = no_world
        best_dist = dist
    if not best_no_world: return None

    if world: return best_no_world

    M = context.edit_object.matrix_world
    Mt = M.transposed()
    return xform_direction(Mt, best_no_world)


class MatrixInfo:
    M   : Matrix
    Mi  : Matrix
    Mt  : Matrix
    Mit : Matrix

    def __init__(self, *, context:Context|None=None, matrix:Matrix|None=None, object:BObject|None=None):
        assert context or matrix or object, 'Must specify either context, matrix, or object'
        if context:
            object = context.edit_object
        if object:
            matrix = object.matrix_world
        self.M   = matrix
        self.Mi  = matrix.inverted_safe()
        self.Mt  = matrix.transposed()
        self.Mit = self.Mi.transposed()

    def l2w_point(self, point:Vector) -> Vector:
        return xform_point(self.M, point)

    def l2w_normal(self, normal:Vector) -> Vector:
        return xform_normal(self.Mit, normal)

    def l2w_vector(self, vector:Vector) -> Vector:
        return xform_vector(self.M, vector)

    def l2w_direction(self, direction:Vector) -> Vector:
        return xform_direction(self.M, direction)

    def w2l_point(self, point:Vector) -> Vector:
        return xform_point(self.Mi, point)

    def w2l_normal(self, normal:Vector) -> Vector:
        return xform_normal(self.Mt, normal)

    def w2l_vector(self, vector:Vector) -> Vector:
        return xform_vector(self.Mi, vector)

    def w2l_direction(self, direction:Vector) -> Vector:
        return xform_direction(self.Mi, direction)



class FindNearest:
    matinfo : MatrixInfo

    from_point_world : Vector
    from_point_local : Vector

    distance_world : float
    object         : BObject | None
    face_index     : int    | None
    point_world    : Vector | None
    normal_world   : Vector | None
    point_local    : Vector | None
    normal_local   : Vector | None

    @property
    def found(self):
        return math.isfinite(self.distance_world)

    def __init__(self, context:Context, *, point_world:Vector|None=None, point_local:Vector|None=None, matinfo:MatrixInfo|None=None):
        assert point_world or point_local, f'Must specify either point_world or point_local'

        self.matinfo = matinfo if matinfo else MatrixInfo(context=context)

        if point_world:
            self.from_point_world = point_world
            self.from_point_local = self.matinfo.w2l_point(point_world)
        elif point_local:
            self.from_point_local = point_local
            self.from_point_world = self.matinfo.l2w_point(point_local)

        self.distance_world = float('inf')
        self.object         = None
        self.face_index     = None
        self.point_world    = None
        self.normal_world   = None
        self.point_local    = None
        self.normal_local   = None

        # print(f'RAY {ray_world}')
        for obj in iter_all_valid_sources(context):
            matinfo_obj = MatrixInfo(object=obj)
            point_local_obj = matinfo_obj.w2l_point(point_world)
            result, co, normal, idx = obj.closest_point_on_mesh(point_local_obj)
            if not result: continue
            co_world = matinfo_obj.l2w_point(co)
            no_world = matinfo_obj.l2w_point(normal)
            dist = distance_between_locations(point_world, co_world)
            if dist < self.distance_world:
                self.distance_world = dist
                self.object         = obj
                self.face_index     = idx
                self.point_world    = co_world
                self.normal_world   = no_world
                self.point_local    = self.matinfo.w2l_point(co_world)
                self.normal_local   = self.matinfo.w2l_normal(no_world)



def nearest_point_normal_valid_sources(context, point_world, *, world=True):
    point_world = Vector((*point_world, 1.0))
    best_hit = None
    best_no_world = None
    best_dist = float('inf')

    for obj in iter_all_valid_sources(context):
        M = obj.matrix_world
        Mi = M.inverted_safe()
        Mit = Mi.transposed()
        point_local = Mi @ point_world
        result, co, normal, idx = obj.closest_point_on_mesh(point_local.xyz)
        if not result: continue
        co_world = M @ Vector((*co, 1.0))
        no_world = xform_normal(Mit, normal)
        dist = distance_between_locations(point_world, co_world)
        # print(f'  HIT {obj.name} {co_world} {dist}')
        if dist >= best_dist: continue
        best_hit = co_world
        best_no_world = no_world
        best_dist = dist

    if not best_hit: return (None, None)

    hit = Vector((*point_to_bvec3(best_hit), 1.0))
    if world:
        return (point_to_bvec3(hit), best_no_world)

    M = context.edit_object.matrix_world
    Mt = M.transposed()
    Mi = M.inverted_safe()
    hit = Mi @ hit
    return (point_to_bvec3(hit), xform_direction(Mt, best_no_world))
