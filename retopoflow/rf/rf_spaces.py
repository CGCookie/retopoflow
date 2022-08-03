'''
Copyright (C) 2022 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

from mathutils import Matrix, Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d

from ...config.options import options
from ...addon_common.common.blender import quat_vector_mult
from ...addon_common.common.debug import dprint
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import Point, Vec, Direction, Normal
from ...addon_common.common.maths import Ray, XForm, Plane
from ...addon_common.common.maths import Point2D, Vec2D, Direction2D
from ...addon_common.common.decorators import blender_version_wrapper


class RetopoFlow_Spaces:
    '''
    converts entities between screen space and world space

    Note: if 2D is not specified, then it is a 1D or 3D entity (whichever is applicable)
    '''

    def update_clip_settings(self, *, rescale=True):
        if options['clip auto adjust']:
            # adjust clipping settings
            view_origin = self.drawing.get_view_origin(orthographic_distance=1000)
            view_focus  = self.actions.r3d.view_location
            bbox = self.sources_bbox
            closest  = bbox.closest_Point(view_origin)
            farthest = bbox.farthest_Point(view_origin)
            self.drawing.space.clip_start = max(
                options['clip auto start min'],
                (view_origin - closest).length * options['clip auto start mult'],
            )
            self.drawing.space.clip_end = min(
                options['clip auto end max'],
                (view_origin - farthest).length * options['clip auto end mult'],
            )
            # print(f'clip auto adjusting')
            # print(f'  origin:   {view_origin}')
            # print(f'  focus:    {view_focus}')
            # print(f'  closest:  {closest}')
            # print(f'  farthest: {farthest}')
            # print(f'  dist from origin to closest:  {(view_origin - closest).length}')
            # print(f'  dist from origin to farthest: {(view_origin - farthest).length}')
            # print(f'  dist from origin to focus:    {(view_origin - view_focus).length}')
            # print(f'  clip_start: {self.drawing.space.clip_start}')
            # print(f'  clip_end:   {self.drawing.space.clip_end}')
        elif rescale:
            self.end_normalize(self.context)
            self.start_normalize()
            # self.unscale_from_unit_box()
            # self.scale_to_unit_box(
            #     clip_override=options['clip override'],
            #     clip_start=options['clip start override'],
            #     clip_end=options['clip end override'],
            # )



    def get_view_origin(self):
        # does not work in ORTHO
        view_loc = self.actions.r3d.view_location
        view_dist = self.actions.r3d.view_distance
        view_rot = self.actions.r3d.view_rotation
        view_cam = Point(view_loc + quat_vector_mult(view_rot, Vector((0,0,view_dist))))
        return view_cam

    def get_view_direction(self):
        view_rot = self.actions.r3d.view_rotation
        return Direction(quat_vector_mult(view_rot, Vector((0, 0, -1))))

    def Point2D_to_Vec(self, xy:Point2D):
        if xy is None: return None
        v = region_2d_to_vector_3d(self.actions.region, self.actions.r3d, xy)
        if v is None: return None
        return Vec(v)

    def Point2D_to_Direction(self, xy:Point2D):
        if xy is None: return None
        d = region_2d_to_vector_3d(self.actions.region, self.actions.r3d, xy)
        if d is None: return None
        return Direction(d)

    def Point2D_to_Origin(self, xy:Point2D):
        if xy is None: return None
        o = region_2d_to_origin_3d(self.actions.region, self.actions.r3d, xy)
        if o is None: return None
        return Point(o)

    def Point2D_to_Ray(self, xy:Point2D):
        if xy is None: return None
        o, d = self.Point2D_to_Origin(xy), self.Point2D_to_Direction(xy)
        if o is None or d is None: return None
        return Ray(o, d)

    def Point2D_to_Point(self, xy:Point2D, depth:float):
        r = self.Point2D_to_Ray(xy)
        if r is None or r.o is None or r.d is None or depth is None:
            dprint(r)
            dprint(depth)
            return None
        return r.eval(depth) # Point(r.o + depth * r.d)
        #return Point(region_2d_to_location_3d(self.actions.region, self.actions.r3d, xy, depth))

    def Point2D_to_Plane(self, xy0:Point2D, xy1:Point2D):
        ray0,ray1 = self.Point2D_to_Ray(xy0),self.Point2D_to_Ray(xy1)
        o = ray0.o + ray0.d
        n = Normal((ray1.o + ray1.d - o).cross(ray0.d))
        return Plane(o, n)

    def Point_to_Point2D(self, xyz:Point):
        if not xyz: return None
        xy = location_3d_to_region_2d(self.actions.region, self.actions.r3d, xyz)
        if xy is None: return None
        return Point2D(xy)

    alerted_small_clip_start = False
    def Point_to_depth(self, xyz):
        '''
        computes the distance of point (xyz) from view camera
        '''

        if not xyz: return None
        xy = self.Point_to_Point2D(xyz)
        if xy is None: return None
        oxyz = self.Point2D_to_Origin(xy)
        return (xyz - oxyz).length

    def Point_to_Direction(self, xyz:Point):
        if not xyz: return None
        xy = location_3d_to_region_2d(self.actions.region, self.actions.r3d, xyz)
        return self.Point2D_to_Direction(xy)

    @profiler.function
    def Point_to_Ray(self, xyz:Point, min_dist=0, max_dist_offset=0):
        if not xyz: return None
        xy = location_3d_to_region_2d(self.actions.region, self.actions.r3d, xyz)
        if not xy: return None
        o = self.Point2D_to_Origin(xy)
        #return Ray.from_segment(o, xyz)
        d = self.Point2D_to_Vec(xy)
        if o is None or d is None: return None
        dist = (o - xyz).length
        return Ray(o, d, min_dist=min_dist, max_dist=dist+max_dist_offset)

    def size2D_to_size(self, size2D:float, xy:Point2D, depth:float):
        # computes size of 3D object at distance (depth) as it projects to 2D size
        # TODO: there are more efficient methods of computing this!
        # note: scaling then unscaling helps with numerical instability when clip_start is small
        scale = 1000.0 # 1.0 / self.actions.space.clip_start
        if not xy: return None
        p3d0 = self.Point2D_to_Point(xy, depth)
        p3d1 = self.Point2D_to_Point(xy + Vec2D((scale * size2D, 0)), depth)
        if not p3d0 or not p3d1: return None
        return (p3d0 - p3d1).length / scale

    def size_to_size2D(self, size:float, xyz:Point):
        if not xyz: return None
        xy = self.Point_to_Point2D(xyz)
        if not xy: return None
        pt2D = self.Point_to_Point2D(xyz - self.Vec_up() * size)
        if not pt2D: return None
        return abs(xy.y - pt2D.y)


    #############################################
    # return camera up and right vectors

    @blender_version_wrapper('<', '2.80')
    def Vec_up(self):
        # TODO: remove invert!
        return self.actions.r3d.view_matrix.to_3x3().inverted_safe() * Vector((0,1,0))
    @blender_version_wrapper('>=', '2.80')
    def Vec_up(self):
        # TODO: remove invert!
        return self.actions.r3d.view_matrix.to_3x3().inverted_safe() @ Vector((0,1,0))

    @blender_version_wrapper('<', '2.80')
    def Vec_right(self):
        # TODO: remove invert!
        return self.actions.r3d.view_matrix.to_3x3().inverted_safe() * Vector((1,0,0))
    @blender_version_wrapper('>=', '2.80')
    def Vec_right(self):
        # TODO: remove invert!
        return self.actions.r3d.view_matrix.to_3x3().inverted_safe() @ Vector((1,0,0))

    @blender_version_wrapper('<', '2.80')
    def Vec_forward(self):
        # TODO: remove invert!
        return self.actions.r3d.view_matrix.to_3x3().inverted_safe() * Vector((0,0,-1))
    @blender_version_wrapper('>=', '2.80')
    def Vec_forward(self):
        # TODO: remove invert!
        return self.actions.r3d.view_matrix.to_3x3().inverted_safe() @ Vector((0,0,-1))
