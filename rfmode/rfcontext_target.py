from itertools import chain
from ..common.utils import iter_pairs
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

    def nearest2D_vert(self, point=None, max_dist=None, verts=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmvert_Point2D(xy, self.Point_to_Point2D, verts=verts, max_dist=max_dist)

    def nearest2D_verts(self, point=None, max_dist:float=10, verts=None):
        xy = self.get_point2D(point or self.actions.mouse)
        max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmverts_Point2D(xy, max_dist, self.Point_to_Point2D, verts=verts)

    def nearest2D_edge(self, point=None, max_dist=None, edges=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmedge_Point2D(xy, self.Point_to_Point2D, edges=edges, max_dist=max_dist)

    def nearest2D_edges(self, point=None, max_dist:float=10, edges=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmedges_Point2D(xy, max_dist, self.Point_to_Point2D, edges=edges)
    
    def nearest2D_face(self, point=None, faces=None):
        xy = self.get_point2D(point or self.actions.mouse)
        return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D, faces=faces)

    ####################
    # REWRITE BELOW!!! #
    ####################
    
    def nearest2D_face_Point2D(self, point:Point2D, faces=None):
        return self.rftarget.nearest2D_bmface_Point2D(point, self.Point_to_Point2D, faces=faces)

    def nearest2D_face_point(self, point):
        xy = self.get_point2D(point)
        return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D)

    def nearest2D_face_mouse(self):
        return self.nearest2D_face_point(self.actions.mouse)

    def nearest2D_face_point(self, point):
        # if max_dist: max_dist = self.drawing.scale(max_dist)
        xy = self.get_point2D(point)
        return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D)

    def nearest2D_face_mouse(self):
        # if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.nearest2D_face_point(self.actions.mouse)


    ########################################
    # find target entities in world space

    def get_point3D(self, point):
        if point.is_3D(): return point
        xyz,_,_,_ = self.raycast_sources_Point2D(point)
        return xyz


    def nearest_vert_point(self, point, verts=None):
        xyz = self.get_point3D(point)
        if xyz is None: return None
        return self.target.nearest_bmvert_Point(xyz, verts=verts)

    def nearest_vert_mouse(self, verts=None):
        return self.nearest_vert_point(self.actions.mouse, verts=verts)

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

    def nearest_edges_Point(self, point, max_dist:float):
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest_bmedges_Point(point, max_dist)

    def nearest_edge_Point(self, point:Point, edges=None):
        return self.rftarget.nearest_bmedge_Point(point, edges=edges)


    #######################################
    # get visible geometry

    def visible_verts(self):
        return self.rftarget.visible_verts(self.is_visible)

    def visible_edges(self, verts=None):
        return self.rftarget.visible_edges(self.is_visible, verts=verts)

    def visible_faces(self, verts=None):
        return self.rftarget.visible_faces(self.is_visible, verts=verts)


    ########################################
    # symmetry utils
    
    def clip_pointloop(self, pointloop, connected):
        # assuming loop will cross symmetry line exactly zero or two times
        l2w_point,w2l_point = self.rftarget.xform.l2w_point,self.rftarget.xform.w2l_point
        pointloop = [w2l_point(pt) for pt in pointloop]
        if 'x' in self.rftarget.symmetry and any(p.x < 0 for p in pointloop):
            if connected:
                rot_idx = next(i for i,p in enumerate(pointloop) if p.x < 0)
                pointloop = pointloop[rot_idx:] + pointloop[:rot_idx]
            npl = []
            for p0,p1 in iter_pairs(pointloop, connected):
                if p0.x < 0 and p1.x < 0: continue
                elif p0.x == 0: npl += [p0]
                elif p0.x > 0 and p1.x > 0: npl += [p0]
                else:
                    connected = False
                    npl += [p0 + (p1 - p0) * (p0.x / (p0.x - p1.x))]
            pointloop = npl
        pointloop = [l2w_point(pt) for pt in pointloop]
        return (pointloop, connected)
    
    def clamp_pointloop(self, pointloop, connected):
        return (pointloop, connected)

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

    def set2D_crawl_vert(self, vert:RFVert, xy:Point2D):
        hits = self.raycast_sources_Point2D_all(xy)
        if not hits: return
        # find closest
        co = vert.co
        p,n,_,_ = min(hits, key=lambda hit:(hit[0]-co).length)
        vert.co = p
        vert.normal = n


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
    
    
    def bridge_vertloop(self, vloop0, vloop1, connected):
        assert len(vloop0) == len(vloop1), "loops must have same vertex counts"
        faces = []
        for pair0,pair1 in zip(iter_pairs(vloop0, connected), iter_pairs(vloop1, connected)):
            v00,v01 = pair0
            v10,v11 = pair1
            faces += [self.new_face((v00,v01,v11,v10))]
        return faces
    

    def update_verts_faces(self, verts):
        self.rftarget.update_verts_faces(verts)

    def update_face_normal(self, face):
        return self.rftarget.update_face_normal(face)

    def delete_selection(self):
        self.rftarget.delete_selection()

    def delete_verts(self, verts):
        self.rftarget.delete_verts(verts)

    def delete_edges(self, edges):
        self.rftarget.delete_edges(edges)

    def delete_faces(self, faces):
        self.rftarget.delete_faces(faces)

    def clean_duplicate_bmedges(self, vert):
        return self.rftarget.clean_duplicate_bmedges(vert)

    ###################################################

    def ensure_lookup_tables(self):
        self.rftarget.ensure_lookup_tables()

    def dirty(self):
        self.rftarget.dirty()
    
    def get_target_version(self):
        return self.rftarget.get_version()

    ###################################################

    def get_selected_verts(self):
        return self.rftarget.get_selected_verts()

    def get_selected_edges(self):
        return self.rftarget.get_selected_edges()

    def get_selected_faces(self):
        return self.rftarget.get_selected_faces()
    
    def get_quadwalk_edgesequence(self, edge):
        return self.rftarget.get_quadwalk_edgesequence(edge)
    
    def get_edge_loop(self, edge):
        return self.rftarget.get_edge_loop(edge)

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
        eloop,connected = self.get_edge_loop(edge)
        self.rftarget.select(eloop, only=only)
        if self.tool: self.tool.update()
        self.update_rot_object()

    def update_rot_object(self):
        self.rot_object.location = self.rftarget.get_selection_center()
