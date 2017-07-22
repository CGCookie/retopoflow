from ..common.maths import Point, Vec, Direction, Normal, Ray, XForm
from ..common.maths import Point2D, Vec2D, Direction2D
from .rfmesh import RFMesh, RFVert, RFEdge, RFFace

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
    
    def nearest_edges_Point(self, point, max_dist:float):
        return self.rftarget.nearest_bmedges_Point(point, max_dist)
    
    def nearest_edge_Point(self, point:Point):
        return self.rftarget.nearest_bmedge_Point(point)
    
    def nearest2D_edge_Point2D(self, point:Point2D):
        return self.rftarget.nearest2D_bmedge_Point2D(point, self.Point_to_Point2D)
    
    def nearest2D_face_point(self, point):
        xy = self.get_point2D(point)
        return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D)
    
    def nearest2D_face_mouse(self):
        return self.nearest2D_face_point(self.actions.mouse)
    
    
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
    
    def nearest_edges_Point(self, point, max_dist:float):
        return self.rftarget.nearest_bmedges_Point(point, max_dist)
    
    def nearest_edge_Point(self, point:Point, edges=None):
        return self.rftarget.nearest_bmedge_Point(point, edges=edges)
    
    def nearest2D_edge_Point2D(self, point:Point2D, edges=None, max_dist=None):
        return self.rftarget.nearest2D_bmedge_Point2D(point, self.Point_to_Point2D, edges=edges, max_dist=max_dist)
    
    def nearest2D_edge_mouse(self, edges=None, max_dist=None):
        return self.nearest2D_edge_Point2D(self.actions.mouse, edges=edges, max_dist=max_dist)
    
    def nearest2D_face_point(self, point):
        xy = self.get_point2D(point)
        return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D)
    
    def nearest2D_face_mouse(self):
        return self.nearest2D_face_point(self.actions.mouse)
    
    #######################################
    
    def visible_verts(self):
        return self.rftarget.visible_verts(self.is_visible)
    
    def visible_edges(self, verts=None):
        return self.rftarget.visible_edges(self.is_visible, verts=verts)
    
    def visible_faces(self, verts=None):
        return self.rftarget.visible_faces(self.is_visible, verts=verts)
    
    
    #######################################
    # target manipulation functions
    #
    # note: these do NOT dirty the target!
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    
    def snap_vert(self, vert:RFVert):
        xyz,norm,_,_ = self.nearest_sources_Point(vert.co)
        vert.co = xyz
        vert.normal = norm
    
    def snap2D_vert(self, vert:RFVert):
        xy = self.Point_to_Point2D(vert.co)
        xyz,norm,_,_ = self.raycast_sources_Point2D()
        if xyz is None: return
        vert.co = xyz
        vert.normal = norm
    
    def offset2D_vert(self, vert:RFVert, delta_xy:Vec2D):
        xy = self.Point_to_Point2D(vert.co) + delta_xy
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        vert.co = xyz
        vert.normal = norm
    
    def set2D_vert(self, vert:RFVert, xy:Point2D):
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        vert.co = xyz
        vert.normal = norm
    
    
    def new_vert_point(self, xyz:Point):
        xyz,norm,_,_ = self.nearest_sources_Point(xyz)
        if not xyz or not norm: return None
        return self.rftarget.new_vert(xyz, norm)
    
    def new2D_vert_point(self, xy:Point2D):
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if not xyz or not norm: return None
        return self.rftarget.new_vert(xyz, norm)
    
    def new2D_vert_mouse(self):
        return self.new2D_vert_point(self.actions.mouse)
    
    def new_edge(self, verts):
        return self.rftarget.new_edge(verts)
    
    def new_face(self, verts):
        return self.rftarget.new_face(verts)
    
    def update_verts_faces(self, verts):
        self.rftarget.update_verts_faces(verts)
    
    def update_face_normal(self, face):
        return self.rftarget.update_face_normal(face)
    
    def delete_faces(self, faces):
        self.rftarget.delete_faces(faces)
    
    def clean_duplicate_bmedges(self, vert):
        return self.rftarget.clean_duplicate_bmedges(vert)
    
    ###################################################
    
    def ensure_lookup_tables(self):
        self.rftarget.ensure_lookup_tables()
    
    def dirty(self):
        self.rftarget.dirty()
    
    ###################################################
    
    def get_selected_verts(self):
        return self.rftarget.get_selected_verts()
    
    def get_selected_edges(self):
        return self.rftarget.get_selected_edges()
    
    def get_selected_faces(self):
        return self.rftarget.get_selected_faces()
    
    def deselect_all(self):
        self.rftarget.deselect_all()
        if self.tool: self.tool.update()
        self.update_rot_object()
    
    def deselect(self, elems):
        self.rftarget.deselect(elems)
        if self.tool: self.tool.update()
        self.update_rot_object()
    
    def select(self, elems, supparts=True, subparts=True, only=True):
        self.rftarget.select(elems, supparts=supparts, subparts=subparts, only=only)
        if self.tool: self.tool.update()
        self.update_rot_object()
    
    def select_toggle(self):
        self.rftarget.select_toggle()
        if self.tool: self.tool.update()
        self.update_rot_object()
    
    def select_edge_loop(self, edge, only=True):
        self.rftarget.select_edge_loop(edge, only=only)
        if self.tool: self.tool.update()
        self.update_rot_object()
    
    def update_rot_object(self):
        self.rot_object.location = self.rftarget.get_selection_center()
    
