'''
Copyright (C) 2017 CG Cookie
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
from ..common.debug import dprint
from ..common.profiler import profiler
from ..common.maths import Point, Vec, Direction, Normal
from ..common.maths import Ray, XForm, Plane
from ..common.maths import Point2D, Vec2D, Direction2D
from ..options import options


smallclipstart_shown = False
smallclipstart_message = '\n'.join([
    'The clip start is very small (<0.1), which can cause the brush sizes (ex: Tweak) to jump or shake as you move your mouse.',
    '',
    'You can increase the clip start in Options > General > View Options > Clip Start.',
])

class RFContext_Spaces:
    '''
    converts entities between screen space and world space

    Note: if 2D is not specified, then it is a 1D or 3D entity (whichever is applicable)
    '''

    def Point2D_to_Vec(self, xy:Point2D):
        if xy is None: return None
        return Vec(region_2d_to_vector_3d(self.actions.region, self.actions.r3d, xy))

    def Point2D_to_Direction(self, xy:Point2D):
        if xy is None: return None
        return Direction(region_2d_to_vector_3d(self.actions.region, self.actions.r3d, xy))

    def Point2D_to_Origin(self, xy:Point2D):
        if xy is None: return None
        return Point(region_2d_to_origin_3d(self.actions.region, self.actions.r3d, xy))

    def Point2D_to_Ray(self, xy:Point2D):
        if xy is None: return None
        return Ray(self.Point2D_to_Origin(xy), self.Point2D_to_Direction(xy))

    def Point2D_to_Point(self, xy:Point2D, depth:float):
        r = self.Point2D_to_Ray(xy)
        if r is None or r.o is None or r.d is None or depth is None:
            dprint(r)
            dprint(depth)
            return None
        return Point(r.o + depth * r.d)
        #return Point(region_2d_to_location_3d(self.actions.region, self.actions.r3d, xy, depth))

    def Point2D_to_Plane(self, xy0:Point2D, xy1:Point2D):
        ray0,ray1 = self.Point2D_to_Ray(xy0),self.Point2D_to_Ray(xy1)
        o = ray0.o + ray0.d
        n = Normal((ray1.o + ray1.d - o).cross(ray0.d))
        return Plane(o, n)

    def Point_to_Point2D(self, xyz:Point):
        xy = location_3d_to_region_2d(self.actions.region, self.actions.r3d, xyz)
        if xy is None: return None
        return Point2D(xy)

    def Point_to_depth(self, xyz):
        global smallclipstart_shown, smallclipstart_message
        smallclipstart = (self.actions.space.clip_start * self.unit_scaling_factor < 0.1)
        if smallclipstart and not smallclipstart_shown:
            smallclipstart_shown = True
            self.alert_user(title='Very small clip start', message=smallclipstart_message, level='Warning')
        r3d = self.actions.r3d
        view_loc, view_dist, view_rot = r3d.view_location, r3d.view_distance, r3d.view_rotation
        view_cam = Point(view_loc + view_rot * Vector((0, 0, view_dist)))
        return (view_cam - xyz).length

    @profiler.profile
    def Point_to_Ray(self, xyz:Point, min_dist=0, max_dist_offset=0):
        xy = location_3d_to_region_2d(self.actions.region, self.actions.r3d, xyz)
        if not xy: return None
        o = self.Point2D_to_Origin(xy)
        #return Ray.from_segment(o, xyz)
        d = self.Point2D_to_Vec(xy)
        dist = (o - xyz).length
        return Ray(o, d, min_dist=min_dist, max_dist=dist+max_dist_offset)

    @profiler.profile
    def Ray_through_Point(self, xyz:Point, min_dist=0):
        xy = location_3d_to_region_2d(self.actions.region, self.actions.r3d, xyz)
        if not xy: return None
        o = self.Point2D_to_Origin(xy)
        d = self.Point2D_to_Vec(xy)
        return Ray(o, d, min_dist=min_dist)

    def size2D_to_size(self, size2D:float, xy:Point2D, depth:float):
        # computes size of 3D object at distance (depth) as it projects to 2D size
        # TODO: there are more efficient methods of computing this!
        p3d0 = self.Point2D_to_Point(xy, depth)
        p3d1 = self.Point2D_to_Point(xy + Vec2D((size2D,0)), depth)
        return (p3d0 - p3d1).length

    def size_to_size2D(self, size:float, xyz:Point):
        xy = self.Point_to_Point2D(xyz)
        pt2D = self.Point_to_Point2D(xyz - self.Vec_up() * size)
        return abs(xy.y - pt2D.y)


    #############################################
    # return camera up and right vectors

    def Vec_up(self):
        # TODO: remove invert!
        return self.actions.r3d.view_matrix.to_3x3().inverted() * Vector((0,1,0))

    def Vec_right(self):
        # TODO: remove invert!
        return self.actions.r3d.view_matrix.to_3x3().inverted() * Vector((1,0,0))

    def Vec_forward(self):
        # TODO: remove invert!
        return self.actions.r3d.view_matrix.to_3x3().inverted() * Vector((0,0,-1))
