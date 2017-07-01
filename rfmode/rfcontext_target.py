from ..common.maths import Point, Vec, Direction, Normal, Ray, XForm
from ..common.maths import Point2D, Vec2D, Direction2D

class RFContext_Target:
    '''
    functions to work on RFTarget
    '''
    
    #########################################
    # find target entities in screen space
    
    def get_point2D(self, point):
        if point.is_2D(): return point
        return self.Point_to_Point2D(point)
    
    def nearest2D_vert_point(self, point):
        xy = self.get_point2D(point)
        return self.rftarget.nearest2D_bmvert_Point2D(xy, self.Point_to_Point2D)
    
    def nearest2D_vert_mouse(self):
        return self.nearest2D_vert_point(self.actions.mouse)
    
    def nearest2D_verts_point(self, point, max_dist:float):
        xy = self.get_point2D(point or self.actions.mouse)
        return self.rftarget.nearest2D_bmverts_Point2D(xy, max_dist, self.Point_to_Point2D)
    
    def nearest2D_verts_mouse(self, max_dist:float):
        return self.nearest2D_verts_point(self.actions.mouse, max_dist)
    
    
    ########################################
    # find target entities in world space
    
    def get_point3D(self, point):
        if point.is_3D(): return point
        xyz,_,_,_ = self.raycast_sources_Point2D(point)
        return xyz
    
    def nearest_vert_point(self, point):
        xyz = self.get_point3D(point)
        if xyz is None: return None
        return self.target.nearest_bmvert_Point(xyz)
    
    def nearest_vert_mouse(self):
        return self.nearest_vert_point(self.actions.mouse)
    
    def nearest_verts_point(self, point, max_dist:float):
        xyz = self.get_point3D(point)
        if xyz is None: return None
        return self.rftarget.nearest_bmverts_Point(xyz, max_dist)
    
    def nearest_verts_mouse(self, max_dist:float):
        return self.nearest_verts_point(self.actions.mouse, max_dist)
    
    
    
    ###################################################
    
    def ensure_lookup_tables(self):
        self.rftarget.ensure_lookup_tables()
    
    def dirty(self):
        self.rftarget.dirty()
    
    ###################################################
    
    def deselect_all(self):
        self.rftarget.deselect_all()
    
    def deselect(self, elems):
        self.rftarget.deselect(elems)
    
    def select(self, elems, supparts=True, subparts=True, only=True):
        self.rftarget.select(elems, supparts=supparts, subparts=subparts, only=only)
    
    def select_toggle(self):
        self.rftarget.select_toggle()