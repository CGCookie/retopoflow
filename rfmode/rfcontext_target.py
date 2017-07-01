from ..common.maths import Point, Vec, Direction, Normal, Ray, XForm
from ..common.maths import Point2D, Vec2D, Direction2D

class RFContext_Target:
    '''
    functions to work on RFTarget
    '''
    
    def target_nearest_bmvert_Point(self, xyz:Point):
        return self.rftarget.nearest_bmvert_Point(xyz)
    
    def target_nearest_bmvert_Point2D(self, xy:Point2D):
        p,_,_,_ = self.raycast_sources_Point2D(xy)
        if p is None: return None
        return self.target_nearest_bmvert_Point(p)
    
    def target_nearest2D_bmvert_Point2D(self, xy):
        return self.rftarget.nearest2D_bmvert_Point2D(xy, self.Point_to_Point2D)
    
    def target_nearest2D_bmvert_mouse(self):
        return self.target_nearest2D_bmvert_Point2D(self.actions.mouse)
    
    def target_nearest_bmvert_mouse(self):
        return self.target_nearest_bmvert_Point2D(self.actions.mouse)
    
    def target_nearest_bmverts_Point(self, xyz:Point, dist3D:float):
        return self.rftarget.nearest_bmverts_Point(xyz, dist3D)
    
    def target_nearest_bmverts_Point2D(self, xy:Point2D, dist3D:float):
        p,_,_,_ = self.raycast_sources_Point2D(xy)
        if p is None: return None
        return self.target_nearest_bmverts_Point(p, dist3D)
    
    def target_nearest_bmverts_mouse(self, dist3D:float):
        return self.target_nearest_bmverts_Point2D(self.actions.mouse, dist3D)
    
    def target_nearest2D_bmverts_Point2D(self, xy:Point2D, dist2D:float):
        return self.rftarget.nearest2D_bmverts_Point2D(xy, dist2D, self.Point_to_Point2D)
    
    def target_nearest2D_bmverts_mouse(self, dist2D:float):
        return self.target_nearest2D_bmverts_Point2D(self.actions.mouse, dist2D)
    
    
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