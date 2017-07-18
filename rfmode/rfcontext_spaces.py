import bpy

from mathutils import Matrix, Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d

from ..common.maths import Point, Vec, Direction, Normal, Ray, XForm
from ..common.maths import Point2D, Vec2D, Direction2D


class RFContext_Spaces:
    '''
    converts entities between screen space and world space
    
    Note: if 2D is not specified, then it is a 1D or 3D entity (whichever is applicable)
    '''
    
    def Point2D_to_Vec(self, xy:Point2D):
        if xy is None: return None
        return Vec(region_2d_to_vector_3d(self.actions.region, self.actions.r3d, xy))
    
    def Point2D_to_Origin(self, xy:Point2D):
        if xy is None: return None
        return Point(region_2d_to_origin_3d(self.actions.region, self.actions.r3d, xy))
    
    def Point2D_to_Ray(self, xy:Point2D):
        if xy is None: return None
        return Ray(self.Point2D_to_Origin(xy), self.Point2D_to_Vec(xy))
    
    def Point2D_to_Point(self, xy:Point2D, depth:float):
        r = self.Point2D_to_Ray(xy)
        if r is None or r.o is None or r.d is None or depth is None:
            print(r)
            print(depth)
        return Point(r.o + depth * r.d)
        #return Point(region_2d_to_location_3d(self.actions.region, self.actions.r3d, xy, depth))
    
    def Point_to_Point2D(self, xyz:Point):
        xy = location_3d_to_region_2d(self.actions.region, self.actions.r3d, xyz)
        if xy is None: return None
        return Point2D(xy)
    
    def Point_to_depth(self, xyz):
        xy = location_3d_to_region_2d(self.actions.region, self.actions.r3d, xyz)
        if xy is None: return None
        oxyz = region_2d_to_origin_3d(self.actions.region, self.actions.r3d, xy)
        return (xyz - oxyz).length
    
    def Point_to_Ray(self, xyz:Point, min_dist=0, max_dist_offset=0):
        xy = location_3d_to_region_2d(self.actions.region, self.actions.r3d, xyz)
        if not xy: return None
        o = self.Point2D_to_Origin(xy)
        d = self.Point2D_to_Vec(xy)
        dist = (o - xyz).length
        return Ray(o, d, min_dist=min_dist, max_dist=dist+max_dist_offset)
    
    def size2D_to_size(self, size2D:float, xy:Point2D, depth:float):
        # computes size of 3D object at distance (depth) as it projects to 2D size
        # TODO: there are more efficient methods of computing this!
        p3d0 = self.Point2D_to_Point(xy, depth)
        p3d1 = self.Point2D_to_Point(xy + Vec2D((size2D,0)), depth)
        return (p3d0 - p3d1).length
    
    
    #############################################
    # return camera up and right vectors
    
    def Vec_up(self):
        return self.Point2D_to_Origin((0,0)) - self.Point2D_to_Origin((0,1))
    
    def Vec_right(self):
        return self.Point2D_to_Origin((1,0)) - self.Point2D_to_Origin((0,0))
    