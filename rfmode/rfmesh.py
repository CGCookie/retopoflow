import sys
import math
import copy

import bpy
import bgl
import bmesh
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from mathutils import Matrix, Vector
from mathutils.geometry import normal as compute_normal, intersect_point_tri
from ..common.maths import Point, Direction, Normal
from ..common.maths import Point2D, Vec2D
from ..common.maths import Ray, XForm, BBox, Plane
from ..common.ui import Drawing
from ..common.utils import min_index
from ..lib import common_drawing_bmesh as bmegl
from ..lib.common_utilities import print_exception, print_exception2, showErrorMessage, dprint
from ..lib.classes.profiler.profiler import profiler

from .rfmesh_wrapper import BMElemWrapper, RFVert, RFEdge, RFFace, RFEdgeSequence


class RFMesh():
    '''
    RFMesh wraps a mesh object, providing extra machinery such as
    - computing hashes on the object (know when object has been modified)
    - maintaining a corresponding bmesh and bvhtree of the object
    - handling snapping and raycasting
    - translates to/from local space (transformations)
    '''

    __version = 0
    @staticmethod
    def generate_version_number():
        RFMesh.__version += 1
        return RFMesh.__version

    @staticmethod
    def hash_object(obj:bpy.types.Object):
        if obj is None: return None
        pr = profiler.start()
        assert type(obj) is bpy.types.Object, "Only call RFMesh.hash_object on mesh objects!"
        assert type(obj.data) is bpy.types.Mesh, "Only call RFMesh.hash_object on mesh objects!"
        # get object data to act as a hash
        me = obj.data
        counts = (len(me.vertices), len(me.edges), len(me.polygons), len(obj.modifiers))
        if me.vertices:
            bbox   = (tuple(min(v.co for v in me.vertices)), tuple(max(v.co for v in me.vertices)))
        else:
            bbox = (None, None)
        vsum   = tuple(sum((v.co for v in me.vertices), Vector((0,0,0))))
        xform  = tuple(e for l in obj.matrix_world for e in l)
        hashed = (counts, bbox, vsum, xform, hash(obj))      # ob.name???
        pr.done()
        return hashed

    @staticmethod
    def hash_bmesh(bme:BMesh):
        if bme is None: return None
        pr = profiler.start()
        assert type(bme) is BMesh, 'Only call RFMesh.hash_bmesh on BMesh objects!'
        counts = (len(bme.verts), len(bme.edges), len(bme.faces))
        bbox   = BBox(from_bmverts=self.bme.verts)
        vsum   = tuple(sum((v.co for v in bme.verts), Vector((0,0,0))))
        hashed = (counts, tuple(bbox.min), tuple(bbox.max), vsum)
        pr.done()
        return hashed


    def __init__(self):
        assert False, 'Do not create new RFMesh directly!  Use RFSource.new() or RFTarget.new()'

    def __deepcopy__(self, memo):
        assert False, 'Do not copy me'

    @profiler.profile
    def __setup__(self, obj, deform=False, bme=None, triangulate=False):
        self.obj = obj
        self.xform = XForm(self.obj.matrix_world)
        self.hash = RFMesh.hash_object(self.obj)
        if bme != None:
            self.bme = bme
        else:
            pr = profiler.start('edit mesh > bmesh')
            eme = self.obj.to_mesh(scene=bpy.context.scene, apply_modifiers=deform, settings='PREVIEW')
            eme.update()
            self.bme = bmesh.new()
            self.bme.from_mesh(eme)
            pr.done()

            pr = profiler.start('selection')
            self.bme.select_mode = {'FACE', 'EDGE', 'VERT'}
            # copy selection from editmesh
            for bmf,emf in zip(self.bme.faces, self.obj.data.polygons):
                bmf.select = emf.select
            for bme,eme in zip(self.bme.edges, self.obj.data.edges):
                bme.select = eme.select
            for bmv,emv in zip(self.bme.verts, self.obj.data.vertices):
                bmv.select = emv.select
            pr.done()

        if triangulate:
            pr = profiler.start('triangulation')
            faces = [face for face in self.bme.faces if len(face.verts) != 3]
            dprint('%d non-triangles' % len(faces))
            bmesh.ops.triangulate(self.bme, faces=faces)
            pr.done()

        self.selection_center = Point((0,0,0))
        self.store_state()
        self.dirty()


    ##########################################################

    def dirty(self):
        # TODO: add option for dirtying only selection or geo+topo
        if hasattr(self, 'bvh'): del self.bvh
        self.version = RFMesh.generate_version_number()

    def clean(self):
        pass
    
    def get_version(self):
        return self.version

    def get_bvh(self):
        if not hasattr(self, 'bvh') or self.bvh_version != self.version:
            self.bvh = BVHTree.FromBMesh(self.bme)
            self.bvh_version = self.version
        return self.bvh

    def get_bbox(self):
        if not hasattr(self, 'bbox') or self.bbox_version != self.version:
            self.bbox = BBox(from_bmverts=self.bme.verts)
            self.bbox_version = self.version
        return self.bbox

    def get_kdtree(self):
        if not hasattr(self, 'kdt') or self.kdt_version != self.version:
            self.kdt = KDTree(len(self.bme.verts))
            for i,bmv in enumerate(self.bme.verts):
                self.kdt.insert(bmv.co, i)
            self.kdt.balance()
            self.kdt_version = self.version
        return self.kdt

    ##########################################################

    def store_state(self):
        attributes = ['hide']       # list of attributes to remember
        self.prev_state = { attr: self.obj.__getattribute__(attr) for attr in attributes }
    def restore_state(self):
        for attr,val in self.prev_state.items(): self.obj.__setattr__(attr, val)

    def obj_hide(self):   self.obj.hide = True
    def obj_unhide(self): self.obj.hide = False

    def ensure_lookup_tables(self):
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.faces.ensure_lookup_table()


    ##########################################################

    @profiler.profile
    def plane_intersection(self, plane:Plane):
        # TODO: do not duplicate vertices!
        plane_local = self.xform.w2l_plane(plane)
        triangle_intersection = plane_local.triangle_intersection
        l2w_point = self.xform.l2w_point
        intersection = [
            (l2w_point(p0),l2w_point(p1))
            for bmf in self.bme.faces
            for p0,p1 in triangle_intersection([bmv.co for bmv in bmf.verts])
            ]
        return intersection

    def get_yz_plane(self):
        o = self.xform.l2w_point(Point((0,0,0)))
        n = self.xform.l2w_normal(Normal((1,0,0)))
        return Plane(o, n)

    @profiler.profile
    def _crawl(self, bmf, plane):
        touched = set()
        def crawl(bmf0):
            if not bmf0: return []
            assert bmf0 not in touched
            touched.add(bmf0)
            best = []
            for bme in bmf0.edges:
                # find where plane crosses edge
                bmv0,bmv1 = bme.verts
                crosses = plane.edge_intersection((bmv0.co, bmv1.co))
                if not crosses: continue
                cross = crosses[0][0]   # only care about one crossing for now (TODO: coplanar??)

                if len(bme.link_faces) == 1:
                    # non-manifold edge
                    ret = [(bmf0, bme, None, cross)]
                    if len(ret) > len(best): best = ret

                for bmf1 in bme.link_faces:
                    if bmf1 == bmf0: continue
                    if bmf1 == bmf:
                        # wrapped completely around!
                        ret = [(bmf0, bme, bmf1, cross)]
                    elif bmf1 in touched:
                        # we've seen this face before
                        continue
                    else:
                        # recursively crawl on!
                        ret = [(bmf0, bme, bmf1, cross)] + crawl(bmf1)

                    if bmf0 == bmf:
                        # on first face
                        # stop crawling if we wrapped around
                        if ret[-1][2] == bmf: return ret
                        # reverse and add to best
                        if not best:
                            best = [(f1,e,f0,c) for f0,e,f1,c in reversed(ret)]
                        else:
                            best = best + ret
                    elif len(ret) > len(best):
                        best = ret
            touched.remove(bmf0)
            return best
        return crawl(bmf)

    @profiler.profile
    def plane_intersection_crawl(self, ray:Ray, plane:Plane):
        ray,plane = self.xform.w2l_ray(ray),self.xform.w2l_plane(plane)
        _,_,i,_ = self.get_bvh().ray_cast(ray.o, ray.d, ray.max)
        bmf = self.bme.faces[i]
        ret = self._crawl(bmf, plane)
        w,l2w_point = self._wrap,self.xform.l2w_point
        ret = [(w(f0),w(e),w(f1),l2w_point(c)) for f0,e,f1,c in ret]
        return ret
    
    @profiler.profile
    def plane_intersection_walk_crawl(self, ray:Ray, plane:Plane):
        '''
        intersect object with ray, walk to plane, then crawl about
        '''
        # intersect self with ray
        ray,plane = self.xform.w2l_ray(ray),self.xform.w2l_plane(plane)
        _,_,i,_ = self.get_bvh().ray_cast(ray.o, ray.d, ray.max)
        bmf = self.bme.faces[i]
        
        # walk along verts and edges from intersection to plane
        def walk_to_plane(bmf):
            bmvs = [bmv for bmv in bmf.verts]
            bmvs_dot = [plane.signed_distance_to(bmv.co) for bmv in bmvs]
            if max(bmvs_dot) >= 0 and min(bmvs_dot) <= 0:
                # bmf crosses plane already
                return bmf
            
            idx = min_index(bmvs_dot)
            bmv,bmv_dot,sign = bmvs[idx],abs(bmvs_dot[idx]),(-1 if bmvs_dot[idx] < 0 else 1)
            touched = set()
            while True:
                touched.add(bmv)
                obmvs = [bme.other_vert(bmv) for bme in bmv.link_edges]
                obmvs = [obmv for obmv in obmvs if obmv not in touched]
                if not obmvs: return None
                obmvs_dot = [plane.signed_distance_to(obmv.co)*sign for obmv in obmvs]
                idx = min_index(obmvs_dot)
                obmv,obmv_dot = obmvs[idx],obmvs_dot[idx]
                if obmv_dot <= 0:
                    # found plane!
                    return next(iter(set(bmv.link_faces) & set(obmv.link_faces)))
                if obmv_dot > bmv_dot: return None
                bmv = obmv
                bmv_dot = obmv_dot
        
        bmf = walk_to_plane(bmf)
        
        # crawl about self along plane
        ret = self._crawl(bmf, plane)
        w,l2w_point = self._wrap,self.xform.l2w_point
        ret = [(w(f0),w(e),w(f1),l2w_point(c)) for f0,e,f1,c in ret]
        return ret
        return ret

    @profiler.profile
    def plane_intersections_crawl(self, plane:Plane):
        plane = self.xform.w2l_plane(plane)
        w,l2w_point = self._wrap,self.xform.l2w_point
        
        # find all faces that cross the plane
        pr = profiler.start('finding all edges crossing plane')
        dot = plane.n.dot
        o = dot(plane.o)
        edges = [bme for bme in self.bme.edges if (dot(bme.verts[0].co)-o) * (dot(bme.verts[1].co)-o) <= 0]
        pr.done()
        
        pr = profiler.start('finding faces crossing plane')
        faces = set(bmf for bme in edges for bmf in bme.link_faces)
        pr.done()
        
        pr = profiler.start('crawling faces along plane')
        rets = []
        touched = set()
        for bmf in faces:
            if bmf in touched: continue
            ret = self._crawl(bmf, plane)
            touched |= set(f0 for f0,_,_,_ in ret if f0)
            touched |= set(f1 for _,_,f1,_ in ret if f1)
            ret = [(w(f0),w(e),w(f1),l2w_point(c)) for f0,e,f1,c in ret]
            rets += [ret]
        pr.done()
        
        return rets


    ##########################################################

    def _wrap(self, bmelem):
        if bmelem is None: return None
        t = type(bmelem)
        if t is BMVert: return RFVert(bmelem)
        if t is BMEdge: return RFEdge(bmelem)
        if t is BMFace: return RFFace(bmelem)
        assert False
    def _wrap_bmvert(self, bmv): return RFVert(bmv)
    def _wrap_bmedge(self, bme): return RFEdge(bme)
    def _wrap_bmface(self, bmf): return RFFace(bmf)
    def _unwrap(self, elem):
        return elem if not hasattr(elem, 'bmelem') else elem.bmelem


    ##########################################################

    def raycast(self, ray:Ray):
        ray_local = self.xform.w2l_ray(ray)
        p,n,i,d = self.get_bvh().ray_cast(ray_local.o, ray_local.d, ray_local.max)
        if p is None: return (None,None,None,None)
        if not self.get_bbox().Point_within(p, margin=1):
            return (None,None,None,None)
        p_w,n_w = self.xform.l2w_point(p), self.xform.l2w_normal(n)
        d_w = (ray.o - p_w).length
        return (p_w,n_w,i,d_w)

    def raycast_all(self, ray:Ray):
        l2w_point,l2w_normal = self.xform.l2w_point,self.xform.l2w_normal
        ray_local = self.xform.w2l_ray(ray)
        hits = []
        origin,direction,maxdist = ray_local.o,ray_local.d,ray_local.max
        dist = 0
        while True:
            p,n,i,d = self.get_bvh().ray_cast(origin, direction, maxdist)
            if not p: break
            p,n = l2w_point(p),l2w_normal(n)
            d = (origin - p).length
            dist += d
            hits += [(p,n,i,dist)]
            origin += direction * (d + 0.00001)
            maxdist -= d
        return hits

    def raycast_hit(self, ray:Ray):
        ray_local = self.xform.w2l_ray(ray)
        p,_,_,_ = self.get_bvh().ray_cast(ray_local.o, ray_local.d, ray_local.max)
        return p is not None

    def nearest(self, point:Point, max_dist=float('inf')): #sys.float_info.max):
        point_local = self.xform.w2l_point(point)
        p,n,i,_ = self.get_bvh().find_nearest(point_local, max_dist)
        if p is None: return (None,None,None,None)
        p,n = self.xform.l2w_point(p), self.xform.l2w_normal(n)
        d = (point - p).length
        return (p,n,i,d)

    def nearest_bmvert_Point(self, point:Point, verts=None):
        if verts is None:
            verts = self.bme.verts
        else:
            verts = [self._unwrap(bmv) for bmv in verts]
        point_local = self.xform.w2l_point(point)
        bv,bd = None,None
        for bmv in verts:
            d3d = (bmv.co - point_local).length
            if bv is None or d3d < bd: bv,bd = bmv,d3d
        bmv_world = self.xform.l2w_point(bv.co)
        return (self._wrap_bmvert(bv),(point-bmv_world).length)

    def nearest_bmverts_Point(self, point:Point, dist3d:float):
        nearest = []
        for bmv in self.bme.verts:
            bmv_world = self.xform.l2w_point(bmv.co)
            d3d = (bmv_world - point).length
            if d3d > dist3d: continue
            nearest += [(self._wrap_bmvert(bmv), d3d)]
        return nearest

    def nearest_bmedge_Point(self, point:Point, edges=None):
        if edges is None:
            edges = self.bme.edges
        else:
            edges = [self._unwrap(bme) for bme in edges]
        l2w_point = self.xform.l2w_point
        be,bd,bpp = None,None,None
        for bme in self.bme.edges:
            bmv0,bmv1 = l2w_point(bme.verts[0].co), l2w_point(bme.verts[1].co)
            diff = bmv1 - bmv0
            l = diff.length
            d = diff / l
            pp = bmv0 + d * max(0, min(l, (point - bmv0).dot(d)))
            dist = (point - pp).length
            if be is None or dist < bd: be,bd,bpp = bme,dist,pp
        if be is None: return (None,None)
        return (self._wrap_bmedge(be), (point-self.xform.l2w_point(bpp)).length)

    def nearest_bmedges_Point(self, point:Point, dist3d:float):
        l2w_point = self.xform.l2w_point
        nearest = []
        for bme in self.bme.edges:
            bmv0,bmv1 = l2w_point(bme.verts[0].co), l2w_point(bme.verts[1].co)
            diff = bmv1 - bmv0
            l = diff.length
            d = diff / l
            pp = bmv0 + d * max(0, min(l, (point - bmv0).dot(d)))
            dist = (point - pp).length
            if dist > dist3d: continue
            nearest += [(self._wrap_bmedge(bme), dist)]
        return nearest

    def nearest2D_bmverts_Point2D(self, xy:Point2D, dist2D:float, Point_to_Point2D, verts=None):
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        if verts is None:
            verts = self.bme.verts
        else:
            verts = [self._unwrap(bmv) for bmv in verts]
        nearest = []
        for bmv in verts:
            p2d = Point_to_Point2D(self.xform.l2w_point(bmv.co))
            if p2d is None: continue
            if (p2d - xy).length > dist2D: continue
            d3d = 0
            nearest += [(self._wrap_bmvert(bmv), d3d)]
        return nearest

    def nearest2D_bmvert_Point2D(self, xy:Point2D, Point_to_Point2D, verts=None, max_dist=None):
        if not max_dist or max_dist < 0: max_dist = float('inf')
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        if verts is None:
            verts = self.bme.verts
        else:
            verts = [self._unwrap(bmv) for bmv in verts]
        l2w_point = self.xform.l2w_point
        bv,bd = None,None
        for bmv in verts:
            p2d = Point_to_Point2D(l2w_point(bmv.co))
            if p2d is None: continue
            d2d = (xy - p2d).length
            if d2d > max_dist: continue
            if bv is None or d2d < bd: bv,bd = bmv,d2d
        if bv is None: return (None,None)
        return (self._wrap_bmvert(bv),bd)

    def nearest2D_bmedges_Point2D(self, xy:Point2D, dist2D:float, Point_to_Point2D, edges=None, shorten=0.01):
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        if edges is None:
            edges = self.bme.edges
        else:
            edges = [self._unwrap(bme) for bme in edges]
        l2w_point = self.xform.l2w_point
        nearest = []
        for bme in edges:
            bmv0 = Point_to_Point2D(l2w_point(bme.verts[0].co))
            bmv1 = Point_to_Point2D(l2w_point(bme.verts[1].co))
            diff = bmv1 - bmv0
            l = diff.length
            d = diff / l
            margin = l * shorten / 2
            pp = bmv0 + d * max(margin, min(l-margin, (xy - bmv0).dot(d)))
            dist = (xy - pp).length
            if dist > dist2D: continue
            nearest += [(self._wrap_bmedge(bme), dist)]
        return nearest

    def nearest2D_bmedge_Point2D(self, xy:Point2D, Point_to_Point2D, edges=None, shorten=0.01, max_dist=None):
        if not max_dist or max_dist < 0: max_dist = float('inf')
        if edges is None:
            edges = self.bme.edges
        else:
            edges = [self._unwrap(bme) for bme in edges]
        l2w_point = self.xform.l2w_point
        be,bd,bpp = None,None,None
        for bme in edges:
            bmv0 = Point_to_Point2D(l2w_point(bme.verts[0].co))
            bmv1 = Point_to_Point2D(l2w_point(bme.verts[1].co))
            diff = bmv1 - bmv0
            l = diff.length
            if l == 0:
                dist = (xy - bmv0).length
            else:
                d = diff / l
                margin = l * shorten / 2
                pp = bmv0 + d * max(margin, min(l-margin, (xy - bmv0).dot(d)))
                dist = (xy - pp).length
            if dist > max_dist: continue
            if be is None or dist < bd: be,bd,bpp = bme,dist,pp
        if be is None: return (None,None)
        return (self._wrap_bmedge(be), (xy-bpp).length)

    def nearest2D_bmface_Point2D(self, xy:Point2D, Point_to_Point2D, faces=None):
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        if faces is None:
            faces = self.bme.faces
        else:
            faces = [self._unwrap(bmf) for bmf in faces]
        bv,bd = None,None
        for bmf in faces:
            pts = [Point_to_Point2D(self.xform.l2w_point(bmv.co)) for bmv in bmf.verts]
            pts = [pt for pt in pts if pt]
            pt0 = pts[0]
            for pt1,pt2 in zip(pts[1:-1],pts[2:]):
                if intersect_point_tri(xy, pt0, pt1, pt2):
                    return self._wrap_bmface(bmf)
            #p2d = Point_to_Point2D(self.xform.l2w_point(bmv.co))
            #d2d = (xy - p2d).length
            #if p2d is None: continue
            #if bv is None or d2d < bd: bv,bd = bmv,d2d
        #if bv is None: return (None,None)
        #return (self._wrap_bmvert(bv),bd)
        return None


    ##########################################################

    def _visible_verts(self, is_visible):
        l2w_point, l2w_normal = self.xform.l2w_point, self.xform.l2w_normal
        is_vis = lambda bmv: is_visible(l2w_point(bmv.co), l2w_normal(bmv.normal))
        return { bmv for bmv in self.bme.verts if is_vis(bmv) }

    def _visible_edges(self, is_visible, bmvs=None):
        if bmvs is None: bmvs = self._visible_verts(is_visible)
        return { bme for bme in self.bme.edges if all(bmv in bmvs for bmv in bme.verts) }

    def _visible_faces(self, is_visible, bmvs=None):
        if bmvs is None: bmvs = self._visible_verts(is_visible)
        return { bmf for bmf in self.bme.faces if all(bmv in bmvs for bmv in bmf.verts) }

    def visible_verts(self, is_visible):
        return { self._wrap_bmvert(bmv) for bmv in self._visible_verts(is_visible) }

    def visible_edges(self, is_visible, verts=None):
        bmvs = None if verts is None else { self._unwrap(bmv) for bmv in verts }
        return { self._wrap_bmedge(bme) for bme in self._visible_edges(is_visible, bmvs=bmvs) }

    def visible_faces(self, is_visible, verts=None):
        bmvs = None if verts is None else { self._unwrap(bmv) for bmv in verts }
        bmfs = { self._wrap_bmface(bmf) for bmf in self._visible_faces(is_visible, bmvs=bmvs) }
        #print('seeing %d / %d faces' % (len(bmfs), len(self.bme.faces)))
        return bmfs


    ##########################################################

    def get_verts(self): return [self._wrap_bmvert(bmv) for bmv in self.bme.verts]
    def get_edges(self): return [self._wrap_bmedge(bme) for bme in self.bme.edges]
    def get_faces(self): return [self._wrap_bmface(bmf) for bmf in self.bme.faces]

    def get_selected_verts(self):
        s = set()
        for bmv in self.bme.verts:
            if bmv.select: s.add(self._wrap_bmvert(bmv))
        return s
    def get_selected_edges(self):
        s = set()
        for bme in self.bme.edges:
            if bme.select: s.add(self._wrap_bmedge(bme))
        return s
    def get_selected_faces(self):
        s = set()
        for bmf in self.bme.faces:
            if bmf.select: s.add(self._wrap_bmface(bmf))
        return s

    def get_selection_center(self):
        v,c = Vector(),0
        for bmv in self.bme.verts:
            if not bmv.select: continue
            v += bmv.co
            c += 1
        if c: self.selection_center = v / c
        return self.xform.l2w_point(self.selection_center)

    def deselect_all(self):
        for bmv in self.bme.verts: bmv.select = False
        for bme in self.bme.edges: bme.select = False
        for bmf in self.bme.faces: bmf.select = False
        self.dirty()

    def deselect(self, elems):
        if not hasattr(elems, '__len__'):
            elems.select = False
        else:
            for bmelem in elems: bmelem.select = False
        self.dirty()

    def select(self, elems, supparts=True, subparts=True, only=True):
        if only: self.deselect_all()
        if not hasattr(elems, '__len__'): elems = [elems]
        if subparts:
            nelems = set(elems)
            for elem in elems:
                t = type(elem)
                if t is BMVert or t is RFVert:
                    pass
                elif t is BMEdge or t is RFEdge:
                    nelems.update(e for e in elem.verts)
                elif t is BMFace or t is RFFace:
                    nelems.update(e for e in elem.verts)
                    nelems.update(e for e in elem.edges)
            elems = nelems
        for elem in elems:
            if elem: elem.select = True
        if supparts:
            for elem in elems:
                t = type(elem)
                if t is not BMVert and t is not RFVert: continue
                for bme in elem.link_edges:
                    if all(bmv.select for bmv in bme.verts):
                        bme.select = True
                for bmf in elem.link_faces:
                    if all(bmv.select for bmv in bmf.verts):
                        bmf.select = True
        self.dirty()

    def get_quadwalk_edgesequence(self, edge):
        bme = self._unwrap(edge)
        touched = set()
        edges = []
        def crawl(bme0, bmv01):
            nonlocal edges
            if bme0 not in touched: edges += [bme0]
            if bmv01 in touched: return True        # wrapped around the loop
            touched.add(bmv01)
            touched.add(bme0)
            if len(bmv01.link_edges) > 4: return False
            if len(bmv01.link_faces) > 4: return False
            bmf0 = bme0.link_faces
            for bme1 in bmv01.link_edges:
                if any(f in bmf0 for f in bme1.link_faces): continue
                bmv2 = bme1.other_vert(bmv01)
                return crawl(bme1, bmv2)
            return False
        if not crawl(bme, bme.verts[0]):
            # did not loop back around, so go other direction
            edges.reverse()
            crawl(bme, bme.verts[1])
        return RFEdgeSequence(edges)
    
    def get_edge_loop(self, edge):
        bme = self._unwrap(edge)
        touched = set()
        edges = []
        def crawl(bme0, bmv01):
            nonlocal edges
            if bme0 not in touched: edges += [self._wrap_bmedge(bme0)]
            if bmv01 in touched: return True
            touched.add(bmv01)
            touched.add(bme0)
            if len(bmv01.link_edges) > 4: return False
            if len(bmv01.link_faces) > 4: return False
            bmf0 = bme0.link_faces
            for bme1 in bmv01.link_edges:
                if bme1 == bme0: continue
                if any(f in bmf0 for f in bme1.link_faces): continue
                bmv2 = bme1.other_vert(bmv01)
                return crawl(bme1, bmv2)
            return False
        if crawl(bme, bme.verts[0]): return (edges, True)
        edges.reverse()
        crawl(bme, bme.verts[1])
        return (edges, False)

    def select_all(self):
        for bmv in self.bme.verts: bmv.select = True
        for bme in self.bme.edges: bme.select = True
        for bmf in self.bme.faces: bmf.select = True
        self.dirty()

    def select_toggle(self):
        sel = False
        sel |= any(bmv.select for bmv in self.bme.verts)
        sel |= any(bme.select for bme in self.bme.edges)
        sel |= any(bmf.select for bmf in self.bme.faces)
        if sel: self.deselect_all()
        else:   self.select_all()


class RFSource(RFMesh):
    '''
    RFSource is a source object for RetopoFlow.  Source objects
    are the meshes being retopologized.
    '''

    __cache = {}

    @staticmethod
    def new(obj:bpy.types.Object):
        assert type(obj) is bpy.types.Object and type(obj.data) is bpy.types.Mesh, 'obj must be mesh object'

        pr = profiler.start()

        # check cache
        rfsource = None
        if obj.data.name in RFSource.__cache:
            # does cache match current state?
            rfsource = RFSource.__cache[obj.data.name]
            hashed = RFMesh.hash_object(obj)
            #print(str(rfsource.hash))
            #print(str(hashed))
            if rfsource.hash != hashed:
                rfsource = None
        if not rfsource:
            # need to (re)generate RFSource object
            RFSource.creating = True
            rfsource = RFSource()
            del RFSource.creating
            rfsource.__setup__(obj)
            RFSource.__cache[obj.data.name] = rfsource

        src = RFSource.__cache[obj.data.name]

        pr.done()

        return src

    def __init__(self):
        assert hasattr(RFSource, 'creating'), 'Do not create new RFSource directly!  Use RFSource.new()'

    def __setup__(self, obj:bpy.types.Object):
        super().__setup__(obj, deform=True, triangulate=True)
        self.ensure_lookup_tables()



class RFTarget(RFMesh):
    '''
    RFTarget is a target object for RetopoFlow.  Target objects
    are the retopologized meshes.
    '''

    @staticmethod
    def new(obj:bpy.types.Object):
        assert type(obj) is bpy.types.Object and type(obj.data) is bpy.types.Mesh, 'obj must be mesh object'

        pr = profiler.start()

        RFTarget.creating = True
        rftarget = RFTarget()
        del RFTarget.creating
        rftarget.__setup__(obj)
        BMElemWrapper.wrap(rftarget)

        pr.done()

        return rftarget

    def __init__(self):
        assert hasattr(RFTarget, 'creating'), 'Do not create new RFTarget directly!  Use RFTarget.new()'

    def __setup__(self, obj:bpy.types.Object, bme:bmesh.types.BMesh=None):
        super().__setup__(obj, bme=bme)
        # if Mirror modifier is attached, set up symmetry to match
        self.symmetry = set()
        self.mirror_mod = None
        for mod in self.obj.modifiers:
            if mod.type != 'MIRROR': continue
            self.mirror_mod = mod
            if not mod.show_viewport: continue
            if mod.use_x: self.symmetry.add('x')
            if mod.use_y: self.symmetry.add('y')
            if mod.use_z: self.symmetry.add('z')
        if not self.mirror_mod:
            # add mirror modifier
            bpy.ops.object.modifier_add(type='MIRROR')
            self.mirror_mod = self.obj.modifiers[-1]
            self.mirror_mod.show_on_cage = True
        self.editmesh_version = None

    def __deepcopy__(self, memo):
        '''
        custom deepcopy method, because BMesh and BVHTree are not copyable
        '''
        rftarget = RFTarget.__new__(RFTarget)
        memo[id(self)] = rftarget
        rftarget.__setup__(self.obj, bme=self.bme.copy())
        # deepcopy all remaining settings
        for k,v in self.__dict__.items():
            if k not in {'prev_state'} and k in rftarget.__dict__: continue
            setattr(rftarget, k, copy.deepcopy(v, memo))
        return rftarget

    def commit(self):
        self.write_editmesh()
        self.restore_state()

    def cancel(self):
        self.restore_state()

    def clean(self):
        super().clean()
        if self.editmesh_version == self.version: return
        self.editmesh_version = self.version
        self.bme.to_mesh(self.obj.data)
        for bmv,emv in zip(self.bme.verts, self.obj.data.vertices):
            emv.select = bmv.select
        for bme,eme in zip(self.bme.edges, self.obj.data.edges):
            eme.select = bme.select
        for bmf,emf in zip(self.bme.faces, self.obj.data.polygons):
            emf.select = bmf.select
        self.mirror_mod.use_x = 'x' in self.symmetry
        self.mirror_mod.use_y = 'y' in self.symmetry
        self.mirror_mod.use_z = 'z' in self.symmetry
    
    def enable_symmetry(self, axis): self.symmetry.add(axis)
    def disable_symmetry(self, axis): self.symmetry.discard(axis)
    def has_symmetry(self, axis): return axis in self.symmetry

    def new_vert(self, co, norm):
        bmv = self.bme.verts.new(self.xform.w2l_point(co))
        bmv.normal = self.xform.w2l_normal(norm)
        return self._wrap_bmvert(bmv)

    def new_edge(self, verts):
        verts = [self._unwrap(v) for v in verts]
        bme = self.bme.edges.new(verts)
        return self._wrap_bmedge(bme)

    def new_face(self, verts):
        verts = [self._unwrap(v) for v in verts]
        bmf = self.bme.faces.new(verts)
        self.update_face_normal(bmf)
        return self._wrap_bmface(bmf)

    def delete_selection(self, del_empty_edges=True, del_empty_verts=True):
        faces = set(f for f in self.bme.faces if f.select)
        self.delete_faces(faces, del_empty_edges=del_empty_edges, del_empty_verts=del_empty_verts)
        edges = set(e for e in self.bme.edges if e.select)
        self.delete_edges(edges, del_empty_verts=del_empty_verts)
        verts = set(v for v in self.bme.verts if v.select)
        self.delete_verts(verts)
        

    def delete_verts(self, verts):
        for bmv in map(self._unwrap, verts): self.bme.verts.remove(bmv)

    def delete_edges(self, edges, del_empty_verts=True):
        edges = set(self._unwrap(e) for e in edges)
        verts = set(v for e in edges for v in e.verts)
        for bme in edges: self.bme.edges.remove(bme)
        if del_empty_verts:
            for bmv in verts:
                if len(bmv.link_edges) == 0: self.bme.verts.remove(bmv)

    def delete_faces(self, faces, del_empty_edges=True, del_empty_verts=True):
        faces = set(self._unwrap(f) for f in faces)
        edges = set(e for f in faces for e in f.edges)
        verts = set(v for f in faces for v in f.verts)
        for bmf in faces: self.bme.faces.remove(bmf)
        if del_empty_edges:
            for bme in edges:
                if len(bme.link_faces) == 0: self.bme.edges.remove(bme)
        if del_empty_verts:
            for bmv in verts:
                if len(bmv.link_faces) == 0: self.bme.verts.remove(bmv)

    def update_verts_faces(self, verts):
        faces = set(f for v in verts for f in self._unwrap(v).link_faces)
        for bmf in faces:
            n = compute_normal(v.co for v in bmf.verts)
            vnorm = sum((v.normal for v in bmf.verts), Vector())
            if n.dot(vnorm) < 0:
                bmf.normal_flip()
            bmf.normal_update()

    def update_face_normal(self, face):
        bmf = self._unwrap(face)
        n = compute_normal(v.co for v in bmf.verts)
        vnorm = sum((v.normal for v in bmf.verts), Vector())
        if n.dot(vnorm) < 0:
            bmf.normal_flip()
        bmf.normal_update()

    def clean_duplicate_bmedges(self, vert):
        bmv = self._unwrap(vert)
        # search for two edges between the same pair of verts
        lbme = list(bmv.link_edges)
        lbme_dup = []
        for i0,bme0 in enumerate(lbme):
            for i1,bme1 in enumerate(lbme):
                if i1 <= i0: continue
                if bme0.other_vert(bmv) == bme1.other_vert(bmv):
                    lbme_dup += [(bme0,bme1)]
        mapping = {}
        for bme0,bme1 in lbme_dup:
            #if not bme0.is_valid or bme1.is_valid: continue
            l0,l1 = len(bme0.link_faces), len(bme1.link_faces)
            handled = False
            if l0 == 0:
                self.bme.edges.remove(bme0)
                handled = True
            if l1 == 0:
                self.bme.edges.remove(bme1)
                handled = True
            if l0 == 1 and l1 == 1:
                # remove bme1 and recreate attached faces
                lbmv = list(bme1.link_faces[0].verts)
                bmf = self._wrap_bmface(bme1.link_faces[0])
                self.bme.edges.remove(bme1)
                mapping[bmf] = self.new_face(lbmv)
                #self.create_face(lbmv)
                handled = True
            if not handled:
                # assert handled, 'unhandled count of linked faces %d, %d' % (l0,l1)
                print('clean_duplicate_bmedges: unhandled count of linked faces %d, %d' % (l0,l1))
        return mapping

    # def modify_bmverts(self, bmverts, update_fn):
    #     l2w = self.xform.l2w_point
    #     w2l = self.xform.w2l_point
    #     for bmv in bmverts:
    #         bmv.co = w2l(update_fn(bmv, l2w(bmv.co)))
    #     self.dirty()



class RFMeshRender():
    '''
    RFMeshRender handles rendering RFMeshes.
    '''

    ALWAYS_DIRTY = False

    def __init__(self, rfmesh, opts):
        self.opts = opts
        self.replace_rfmesh(rfmesh)
        self.bglCallList = bgl.glGenLists(1)
        self.bglMatrix = rfmesh.xform.to_bglMatrix()
        self.drawing = Drawing.get_instance()
        self.opts['dpi mult'] = self.drawing.get_dpi_mult()

    def __del__(self):
        if hasattr(self, 'bglCallList'):
            bgl.glDeleteLists(self.bglCallList, 1)
            del self.bglCallList
        if hasattr(self, 'bglMatrix'):
            del self.bglMatrix

    def replace_rfmesh(self, rfmesh):
        self.rfmesh = rfmesh
        self.bmesh = rfmesh.bme
        self.rfmesh_version = None

    def _draw(self):
        opts = dict(self.opts)
        for xyz in self.rfmesh.symmetry: opts['mirror %s'%xyz] = True

        # do not change attribs if they're not set
        bmegl.glSetDefaultOptions(opts=self.opts)
        bgl.glPushMatrix()
        bgl.glMultMatrixf(self.bglMatrix)

        bgl.glDisable(bgl.GL_CULL_FACE)

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_FALSE)
        # bgl.glEnable(bgl.GL_CULL_FACE)
        opts['poly hidden'] = 0.0
        opts['poly mirror hidden'] = 0.0
        opts['line hidden'] = 0.0
        opts['line mirror hidden'] = 0.0
        opts['point hidden'] = 0.0
        opts['point mirror hidden'] = 0.0
        bmegl.glDrawBMFaces(self.bmesh.faces, opts=opts, enableShader=False)
        bmegl.glDrawBMEdges(self.bmesh.edges, opts=opts, enableShader=False)
        bmegl.glDrawBMVerts(self.bmesh.verts, opts=opts, enableShader=False)

        bgl.glDepthFunc(bgl.GL_GREATER)
        bgl.glDepthMask(bgl.GL_FALSE)
        # bgl.glDisable(bgl.GL_CULL_FACE)
        opts['poly hidden']         = 0.95
        opts['poly mirror hidden']  = 0.95
        opts['line hidden']         = 0.95
        opts['line mirror hidden']  = 0.95
        opts['point hidden']        = 0.95
        opts['point mirror hidden'] = 0.95
        bmegl.glDrawBMFaces(self.bmesh.faces, opts=opts, enableShader=False)
        bmegl.glDrawBMEdges(self.bmesh.edges, opts=opts, enableShader=False)
        bmegl.glDrawBMVerts(self.bmesh.verts, opts=opts, enableShader=False)

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_TRUE)
        # bgl.glEnable(bgl.GL_CULL_FACE)
        bgl.glDepthRange(0, 1)
        bgl.glPopMatrix()

    def clean(self):
        # return if rfmesh hasn't changed
        self.rfmesh.clean()
        if self.rfmesh_version == self.rfmesh.version: return
        self.rfmesh_version = self.rfmesh.version   # make not dirty first in case bad things happen while drawing
        bgl.glNewList(self.bglCallList, bgl.GL_COMPILE)
        self._draw()
        bgl.glEndList()

    def draw(self):
        try:
            if self.ALWAYS_DIRTY:
                self.rfmesh.clean()
                bmegl.bmeshShader.enable()
                self._draw()
            else:
                self.clean()
                bmegl.bmeshShader.enable()
                bgl.glCallList(self.bglCallList)
        except:
            print_exception()
            pass
        finally:
            try:
                bmegl.bmeshShader.disable()
            except:
                pass
