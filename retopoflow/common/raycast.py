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
from typing import Callable, TypeAlias, cast
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

def size2D_to_size(
    context : Context,
    depth3D : float,
    *,
    pt : Vector | Sequence[float] | None = None,
) -> float | None:
    w : float = context.region.width * 0.5
    h : float = context.region.height * 0.5
    scale = min(w, h)

    # note: scaling then unscaling helps with numerical instability when clip_start is small
    # find center of screen
    xy = Vector((pt[0], pt[1])) if pt else Vector((w, h))
    xy0, xy1 = xy + Vector((-scale, 0)), xy + Vector((scale, 0))
    xy2, xy3 = xy + Vector((0, -scale)), xy + Vector((0, scale))
    p3d = point2D_to_point(context, xy, depth3D)
    p3d0, p3d1 = point2D_to_point(context, xy0, depth3D), point2D_to_point(context, xy1, depth3D)
    p3d2, p3d3 = point2D_to_point(context, xy2, depth3D), point2D_to_point(context, xy3, depth3D)

    if not p3d or not p3d0 or not p3d1 or not p3d2 or not p3d3:
        return None

    # if not p3d0 or not p3d1: return None
    d0, d1 = (p3d0 - p3d).length, (p3d1 - p3d).length
    d2, d3 = (p3d2 - p3d).length, (p3d3 - p3d).length
    d = (d0 + d1 + d2 + d3) / 4
    # print(f'{d0} {d1} {d2} {d3}')
    return d / scale

def ray_from_mouse(context : Context, event : Event) -> tuple[Vector, Vector] | tuple[None, None]:
    mouse = (event.mouse_region_x, event.mouse_region_y)
    if not context.region_data:
        return (None, None)
    return (
        Vector((*region_2d_to_origin_3d(context.region, context.region_data, mouse), 1.0)),
        Vector((*region_2d_to_vector_3d(context.region, context.region_data, mouse).normalized(), 0.0)),
    )

def direction_from_mouse(context, event) -> Vector:
    if not context.region_data: return (None, None)
    mouse = (event.mouse_region_x, event.mouse_region_y)
    v = region_2d_to_vector_3d(context.region, context.region_data, mouse).normalized()
    return Vector(( v.x, v.y, v.z, 0.0 ))

def direction_from_point(context : Context, point_screen_or_world : Vector) -> Vector | None:
    if not context.region_data:
        return None

    if len(point_screen_or_world) > 2:
        point_screen = location_3d_to_region_2d(context.region, context.region_data, point_screen_or_world)
        if not point_screen:
            return None
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

def is_point_hidden(context : Context, co_edit : Vector, *, factor : float = 1.0, use_offset : bool = True) -> bool:
    if not context.edit_object:
        return True

    M = context.edit_object.matrix_world
    co_world : Vector = M @ point_to_bvec4(co_edit)
    hit = raycast_valid_sources(context, co_world, respect_clip_planes=True)
    if not hit:
        return False
    ray_e : Vector = hit['ray_world'][0]
    offset : float = context.space_data.overlay.retopology_offset if use_offset else 0.0
    dist : float = hit['distance']
    return dist + offset < (ray_e.xyz - co_world.xyz).length * factor

# Testing whether a CURVE/SURFACE/META/FONT object has faces requires tessellation,
# so we don't want to do this every single raycast.
has_faces_cache : dict[str, bool] = {}

def clear_has_faces_cache():
    has_faces_cache.clear()

def has_faces(context, obj):
    if obj.type == 'MESH' and bool(obj.data.polygons):
        return True
    elif obj.type in ['CURVE', 'SURFACE', 'META', 'FONT']:
        cached = has_faces_cache.get(obj.name)
        if cached is not None:
            return cached
        depsgraph = context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        if not eval_mesh:
            # Conversion to mesh can fail (e.g. invalid geometry, a curve object with an unlinked GN modifier, etc.)
            result = False
        else:
            result = bool(eval_mesh.polygons)
            eval_obj.to_mesh_clear()
        has_faces_cache[obj.name] = result
        return result
    else:
        return False


GeometryQueryResult : TypeAlias = tuple[bool, Vector, Vector, int]
GEOMETRY_QUERY_MISS : GeometryQueryResult = (False, Vector(), Vector(), -1) # (hit, location, normal, face index)

def source_ray_cast(obj : BObject, *args : ..., **kwargs : ...) -> GeometryQueryResult:
    ''' obj.ray_cast, treating a source with no evaluated mesh as a miss. '''
    try:
        return cast(GeometryQueryResult, obj.ray_cast(*args, **kwargs))
    except RuntimeError:
        has_faces_cache.pop(obj.name, None)  # stale: re-test faces on the next pass
        return GEOMETRY_QUERY_MISS

def source_closest_point_on_mesh(obj : BObject, *args : ..., **kwargs : ...) -> GeometryQueryResult:
    ''' obj.closest_point_on_mesh, treating a source with no evaluated mesh as a miss. '''
    try:
        return cast(GeometryQueryResult, obj.closest_point_on_mesh(*args, **kwargs))
    except RuntimeError:
        has_faces_cache.pop(obj.name, None)  # stale: re-test faces on the next pass
        return GEOMETRY_QUERY_MISS

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
    clear_has_faces_cache()  # sources may have changed while RF was not running
    for obj in iter_all_valid_sources(context):
        source_ray_cast(obj, Vector((0,0,0)), Vector((1,0,0)))
    print(f'  {time.time() - start:0.2f}secs')

CLIP_MAX_SKIPS = 16    # max out-of-clip-region hits to punch through before giving up
CLIP_SKIP_NUDGE = 1e-4 # world-space distance to advance the ray origin past a rejected hit

def is_point_in_clip_region(context: Context, co_world) -> bool:
    '''
    Returns True if Alt+B clip region is not used or the world-space point is inside the region.
    Accepts a 3 or 4 component sequence (e.g. a plain Vector or a homogeneous bvec4).
    Uses rv3d.clip_planes: six world-space half-plane equations (ax+by+cz+d >= 0 = inside).
    '''
    rv3d = context.region_data
    if not rv3d or not rv3d.use_clip_planes:
        return True
    x, y, z = co_world[0], co_world[1], co_world[2]
    for p in rv3d.clip_planes:
        if p[0]*x + p[1]*y + p[2]*z + p[3] < 0:
            return False
    return True

def make_hidden_tester(context: Context, obj) -> 'Callable[[Vector, Vector, float], bool]':
    '''
    Returns a fast per-object occlusion tester that calls obj.ray_cast() directly,
    bypassing raycast_valid_sources for speed, skipping hits outside the active Alt+B clip region.

    Signature of the returned callable: hidden_tester(ray_e_world, ray_d_world, max_distance) -> bool
    where ray_e_world is a ray origin, ray_d_world is a 3 or 4D direction, all in world space units.
    Returns True if the source mesh occludes this ray (hit inside clip region found).
    '''
    M  = obj.matrix_world
    Mi = M.inverted_safe()
    def hidden_tester(ray_e_world: Vector, ray_d_world: Vector, max_distance: float) -> bool:
        ray_d3      = Vector(ray_d_world[:3])          # ensure 3D: input may be 4D (w=0)
        ray_d_local = direction_to_bvec3(Mi @ ray_d_world)
        cur_e       = Vector(ray_e_world[:3])          # world-space origin, advances past clipped hits
        dist_spent  = 0.0
        for _ in range(CLIP_MAX_SKIPS):
            dist_left = max_distance - dist_spent
            if dist_left <= 0: return False
            ray_e_local = point_to_bvec3(Mi @ cur_e)
            result, co, normal, idx = source_ray_cast(obj, ray_e_local, ray_d_local, distance=dist_left)
            if not result: return False
            co_world = (M @ Vector((*co, 1.0))).to_3d()
            if not is_point_in_clip_region(context, co_world):
                dist_to_hit = (co_world - cur_e).length
                cur_e       = cur_e + ray_d3 * (dist_to_hit + CLIP_SKIP_NUDGE)
                dist_spent += dist_to_hit + CLIP_SKIP_NUDGE
                continue
            return True
        return False
    return hidden_tester


class Raycast:
    hit        : bool = False
    ray_origin : Vector = Vector()
    ray_dir    : Vector = Vector()
    ray_world  : tuple[Vector, Vector] = (Vector(), Vector())
    distance   : float = float('inf')
    object     : BObject | None = None
    face_index : int = -1
    co_local   : Vector = Vector()
    no_local   : Vector = Vector()
    co_hit     : Vector = Vector()
    no_hit     : Vector = Vector()
    co_world   : Vector = Vector()
    no_world   : Vector = Vector()

    def __init__(
        self,
        context : Context,
        point : Vector | Sequence[float] | None,
        *,
        respect_clip_planes : bool = False,
    ):
        if not point:
            return

        editobj = context.edit_object
        if not editobj:
            return

        ray_world = ray_from_point(context, point)
        ray_origin, ray_dir = ray_world  # 4D: w=1 (point) and w=0 (direction, already normalised)
        if not ray_origin or not ray_dir:
            return

        self.ray_origin = ray_origin
        self.ray_dir = ray_dir
        self.ray_world = (ray_origin, ray_dir)  # ray based on point_world

        Me = editobj.matrix_world
        Mei = Me.inverted_safe()
        Met = Me.transposed()

        for hitobj in iter_all_valid_sources(context):
            M   = hitobj.matrix_world
            Mi  = M.inverted_safe()
            Mit = Mi.transposed()
            #Mt  = M.transposed()

            current_origin = ray_origin  # 4D point, w=1, advances past rejected hits when clipping

            for _ in range(CLIP_MAX_SKIPS if respect_clip_planes else 1):
                ray_local = (
                    Mi @ current_origin,
                    (Mi @ ray_dir).normalized(),
                )
                result, co_hit, no_hit, idx = source_ray_cast(
                    hitobj,
                    point_to_bvec3(ray_local[0]),
                    vector_to_bvec3(ray_local[1]),
                )
                if not result:
                    break

                co_world = point_to_bvec3(M @ point_to_bvec4(co_hit))

                if respect_clip_planes and not is_point_in_clip_region(context, co_world):
                    # hit is outside the clipping region: advance past it and retry.
                    dist_to_hit = distance_between_locations(current_origin, co_world)
                    current_origin = current_origin + ray_dir * (dist_to_hit + CLIP_SKIP_NUDGE)
                    continue

                # Hit is valid
                no_hit = no_hit.normalized()
                no_world  = vector_to_bvec3(Mit @ vector_to_bvec4(no_hit)).normalized()
                dist = distance_between_locations(ray_origin, co_world)
                # print(co_hit, dist)

                if self.hit and self.distance <= dist:
                    break

                co_local = point_to_bvec3(Mei @ point_to_bvec4(co_world))
                no_local = vector_to_bvec3(Met @ vector_to_bvec4(no_world)).normalized()

                self.hit        = True
                self.distance   = dist      # world distance between ray origin and hit point
                self.object     = hitobj    # hit object
                self.face_index = idx       # hit face index
                self.co_local   = co_local  # co wrt edit object
                self.no_local   = no_local  # normal wrt edit object
                self.co_hit     = co_hit    # co wrt hit object
                self.no_hit     = no_hit    # normal wrt hit object
                self.co_world   = co_world  # co wrt world space
                self.no_world   = no_world  # normal wrt world space

                break


def raycast_valid_sources(
    context : Context,
    point : Vector|Sequence[float]|None,
    respect_clip_planes : bool = False
) -> dict[str,tuple[Vector,Vector]|float|int|BObject|Vector|Sequence[float]]|None:
    if not point:
        return None
    editobj = context.edit_object
    if not editobj:
        return None

    ray_world = ray_from_point(context, point)
    ray_origin, ray_dir = ray_world  # 4D: w=1 (point) and w=0 (direction, already normalised)

    # print(f'raycast_valid_sources {ray_world=}')
    if not ray_origin or not ray_dir:
        return None


    best : dict[str,tuple[Vector,Vector]|float|int|BObject|Vector|Sequence[float]]|None = None

    Me = editobj.matrix_world
    Mei = Me.inverted_safe()
    Met = Me.transposed()
    for hitobj in iter_all_valid_sources(context):
        M   = hitobj.matrix_world
        Mi  = M.inverted_safe()
        Mit = Mi.transposed()
        #Mt  = M.transposed()

        current_origin = ray_origin  # 4D point, w=1, advances past rejected hits when clipping

        for _ in range(CLIP_MAX_SKIPS if respect_clip_planes else 1):
            ray_local = (
                Mi @ current_origin,
                (Mi @ ray_dir).normalized(),
            )
            result, co_hit, no_hit, idx = source_ray_cast(
                hitobj,
                point_to_bvec3(ray_local[0]),
                vector_to_bvec3(ray_local[1]),
            )
            if not result:
                break

            co_world = point_to_bvec3(M @ point_to_bvec4(co_hit))

            if respect_clip_planes and not is_point_in_clip_region(context, co_world):
                # hit is outside the clipping region: advance past it and retry.
                dist_to_hit = distance_between_locations(current_origin, co_world)
                current_origin = current_origin + ray_dir * (dist_to_hit + CLIP_SKIP_NUDGE)
                continue

            # Hit is valid
            no_hit = no_hit.normalized()
            no_world  = vector_to_bvec3(Mit @ vector_to_bvec4(no_hit)).normalized()
            dist = distance_between_locations(ray_origin, co_world)
            # print(co_hit, dist)

            if best and cast(float, best['distance']) <= dist:
                break

            co_local = point_to_bvec3(Mei @ point_to_bvec4(co_world))
            no_local = vector_to_bvec3(Met @ vector_to_bvec4(no_world)).normalized()

            best = {
                'ray_world':  (ray_origin, ray_dir),  # ray based on point_world
                'distance':   dist,       # world distance between ray origin and hit point
                'object':     hitobj,    'face_index': idx,        # hit object and face index
                'co_local':   co_local,  'no_local':   no_local,   # co and normal wrt to edit object
                'co_hit':     co_hit,    'no_hit':     no_hit,     # co and normal wrt to hit object
                'co_world':   co_world,  'no_world':   no_world,   # co and normal in world space
            }
            break

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

def raycast_ray_valid_sources(context:Context, ray_world:tuple[Vector,Vector], *, world:bool=True, respect_clip_planes:bool=False) -> Vector|None:
    if ray_world[0] is None: return None

    best_hit = None
    best_dist = float('inf')

    ray_origin, ray_dir = ray_world  # 4D: w=1 (point) and w=0 (direction, already normalised)

    # print(f'RAY {ray_world}')
    for obj in iter_all_valid_sources(context):
        M = obj.matrix_world
        Mi = M.inverted_safe()

        current_origin = ray_origin   # 4D point, w=1, advances past rejected hits when clipping

        # Loop up to CLIP_MAX_SKIPS times only when clip-plane respecting is on
        for _ in range(CLIP_MAX_SKIPS if respect_clip_planes else 1):
            ray_local = (
                Mi @ current_origin,
                (Mi @ vector_to_bvec4(ray_dir)).normalized(),
            )
            result, co, normal, idx = source_ray_cast(obj, point_to_bvec3(ray_local[0]), vector_to_bvec3(ray_local[1]))
            if not result:
                break

            co_world = M @ Vector((*co, 1.0))

            if respect_clip_planes and not is_point_in_clip_region(context, co_world):
                # hit is outside the Alt+B clipping region: advance past it and retry.
                dist_to_hit = distance_between_locations(current_origin, co_world)
                current_origin = current_origin + ray_dir * (dist_to_hit + CLIP_SKIP_NUDGE)
                continue

            # Hit is valid (inside clipping region, or clipping not active / not respected).
            dist = distance_between_locations(ray_origin, co_world)
            # print(f'  HIT {obj.name} {co_world} {dist}')
            if dist < best_dist:
                best_hit = co_world
                best_dist = dist
            break

    if not best_hit: return None

    hit = Vector((*point_to_bvec3(best_hit), 1.0))
    if not world:
        M = context.edit_object.matrix_world
        Mi = M.inverted_safe()
        hit = Mi @ hit
    return point_to_bvec3(hit)

def raycast_multiple_hits(context:Context, origin:Vector, direction:Vector, n:int) -> list[Vector]:
    '''Cast a ray up to n times, nudging past each hit to collect subsequent intersections.'''
    hits = []
    pt = origin
    for _ in range(n):
        ray = (pt + direction * max(1e-4, pt.length * 1e-5), direction) # Scaled to improve result for huge or tiny objects
        hit = raycast_ray_valid_sources(context, ray, world=True, respect_clip_planes=True)
        if hit is None: break
        hits.append(hit)
        pt = hit
    return hits

def raycast_point_capped_valid_sources(
    context : Context,
    point_screen : Vector,
    co_world_ref : Vector,
    *,
    cap : float = 0.0,
    world : bool = False,
    sources : Sequence[tuple[BObject, Matrix, Matrix]] | None = None,
    respect_clip_planes : bool = True,
) -> Vector | None:
    ''' Screen-space project a point onto the sources, with protection against snapping to
    far away surfaces. When the hit lands farther than `cap` from `co_world_ref`
    (the point's current world position), the same screen point is reprojected onto the nearest
    source surface at that reference's view depth instead of accepting the large jump.
    cap <= 0 accepts any hit (no cap). Returns None when nothing was hit at all. '''
    hit = raycast_valid_sources(context, point_screen, respect_clip_planes=respect_clip_planes)
    hit_co = (Vector(hit['co_world']) if world else Vector(hit['co_local'])) if hit else None
    if hit and (cap <= 0 or (Vector(hit['co_world']) - co_world_ref).length <= cap):
        return hit_co
    co_plane = region_2d_to_location_3d(context.region, context.region_data, point_screen, co_world_ref)
    if co_plane:
        snapped = nearest_point_valid_sources(
            context, point_to_bvec3(co_plane), world=world, sources=sources, respect_clip_planes=respect_clip_planes
        )
        if snapped:
            return snapped
    # Nothing better available: keep the capped hit if there was one, else signal no-move.
    return hit_co

def nearest_point_valid_sources(
    context : Context,
    point_world : Vector,
    *,
    world : bool = True,
    sources : Sequence[tuple[BObject, Matrix, Matrix]] | None = None,
    respect_clip_planes : bool = False,
) -> Vector | None:

    edit_object = context.edit_object
    if not edit_object:
        return None

    point_world = Vector((*point_world, 1.0))
    best_hit = None
    best_dist = float('inf')

    # Callers in a tight per-vert loop can pass a precomputed `sources` iterable of
    # (obj, matrix_world, matrix_world_inv[, ...]) tuples to avoid re-filtering the view
    # layer and re-inverting matrices on every call.
    if sources is None:
        sources = [
            (obj, obj.matrix_world, obj.matrix_world.inverted_safe())
            for obj in iter_all_valid_sources(context)
        ]

    for src in sources:
        obj, M, Mi = src[0], src[1], src[2]
        point_local = Mi @ point_world
        result, co, _normal, _idx = source_closest_point_on_mesh(obj, point_local.xyz)
        if not result:
            continue

        co_world = M @ Vector((*co, 1.0))
        if respect_clip_planes and not is_point_in_clip_region(context, co_world):
            continue

        dist = distance_between_locations(point_world, co_world)
        if dist >= best_dist:
            continue

        best_hit = co_world
        best_dist = dist

    if not best_hit:
        return None

    hit = Vector((*point_to_bvec3(best_hit), 1.0))
    if not world:
        M_eo = edit_object.matrix_world
        Mi_eo = M_eo.inverted_safe()
        hit = Mi_eo @ hit
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
        result, co, normal, idx = source_closest_point_on_mesh(obj, point_local)
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

def nearest_point_normal_valid_sources(
    context : Context,
    point_world : Vector,
    *,
    world : bool = True,
    respect_clip_planes : bool = False,
) -> tuple[Vector, Vector] | None:
    ''' Closest point and its normal on any valid source, from a single closest_point_on_mesh query per source.
    Returns (co, no) or None. '''

    obj = context.edit_object
    if not obj:
        return None
    obj_M = obj.matrix_world

    best_co_world = None
    best_no_world = None
    best_dist = float('inf')
    for obj in iter_all_valid_sources(context):
        M = obj.matrix_world
        Mi = M.inverted_safe()
        Mit = Mi.transposed()
        point_local = point_to_bvec3(xform_point(Mi, point_world))
        result, co, normal, idx = source_closest_point_on_mesh(obj, point_local)
        if not result: continue
        co_world = xform_point(M, co)
        if respect_clip_planes and not is_point_in_clip_region(context, co_world):
            continue
        dist = distance_between_locations(point_world, co_world)
        if dist >= best_dist: continue
        best_co_world = co_world
        best_no_world = xform_normal(Mit, normal)
        best_dist = dist

    if best_co_world is None or best_no_world is None:
        return None

    if world:
        return (best_co_world, best_no_world)

    Mi = obj_M.inverted_safe()
    Mt = obj_M.transposed()
    return (point_to_bvec3(xform_point(Mi, best_co_world)), xform_direction(Mt, best_no_world))


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
            result, co, normal, idx = source_closest_point_on_mesh(obj, point_local_obj)
            if not result: continue
            co_world = matinfo_obj.l2w_point(co)
            no_world = matinfo_obj.l2w_normal(normal)
            dist = distance_between_locations(point_world, co_world)
            if dist < self.distance_world:
                self.distance_world = dist
                self.object         = obj
                self.face_index     = idx
                self.point_world    = co_world
                self.normal_world   = no_world
                self.point_local    = self.matinfo.w2l_point(co_world)
                self.normal_local   = self.matinfo.w2l_normal(no_world)
