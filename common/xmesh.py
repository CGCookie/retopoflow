import time
import math

import bpy
import bmesh
import bgl

from typing import List, Callable

from mathutils import Vector, Matrix, Color, kdtree
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_point_line, intersect_line_plane
from bpy_extras import view3d_utils

from .maths import Point, Normal, XForm, Ray, Vector, Point2D



class XMesh:
    def __init__(self, obj, triangulate=True):
        self.obj = obj
        self.xform = XForm(self.obj.matrix_world)
        eme = self.obj.to_mesh(scene=bpy.context.scene, apply_modifiers=deform, settings='PREVIEW')
        eme.update()
        self.bme = bmesh.new()
        self.bme.from_mesh(eme)
        if triangulate: self.triangulate()
        self.dirty()

    def dirty(self):
        self._dirty = True

    def clean(self):
        if not self._dirty: return
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.faces.ensure_lookup_table()
        self._bvh = BVHTree.FromBMesh(self.bme)
        self._dirty = False


    ###################################################################################
    # properties
    ###################################################################################

    @property
    def bvh(self):
        self.clean()
        return self._bvh


    ###################################################################################
    # simple manipulations
    ###################################################################################

    def triangulate(self):
        faces = [face for face in self.bme.faces if len(face.verts) != 3]
        #print('%d non-triangles' % len(faces))
        bmesh.ops.triangulate(self.bme, faces=faces)
        self.dirty()


    ###################################################################################
    # ray casting functions
    ###################################################################################

    def raycast(self, ray:Ray):
        ray_local = self.xform.w2l_ray(ray)
        p,n,i,d = self.bvh.ray_cast(ray_local.o, ray_local.d, ray_local.max)
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
            p,n,i,d = self.bvh.ray_cast(origin, direction, maxdist)
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
        p,n,i,d = self.bvh.ray_cast(ray_local.o, ray_local.d, ray_local.max)
        return p is not None


    ###################################################################################
    # nearest functions
    ###################################################################################

    def nearest(self, point:Point, max_dist=float('inf')): #sys.float_info.max):
        point_local = self.xform.w2l_point(point)
        p,n,i,_ = self.bvh.find_nearest(point_local, max_dist)
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
        edges = self.bme.edges if edges is None else [self._unwrap(bme) for bme in edges]
        l2w_point = self.xform.l2w_point
        nearest = []
        dist2D2 = dist2D**2
        s0,s1 = shorten/2,1-shorten/2
        proj = lambda bmv: Point_to_Point2D(l2w_point(bmv.co))
        for bme in edges:
            v0,v1 = proj(bme.verts[0]),proj(bme.verts[1])
            l = v0.distance_to(v1)
            if l == 0:
                pp = v0
            else:
                d = (v1 - v0) / l
                pp = v0 + d * max(l*s0, min(l*s1, d.dot(xy-v0)))
            dist2 = pp.distance_squared_to(xy)
            if dist2 > dist2D2: continue
            nearest.append((self._wrap_bmedge(bme), math.sqrt(dist2)))
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

    def nearest2D_bmfaces_Point2D(self, xy:Point2D, Point_to_Point2D, faces=None):
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        if faces is None:
            faces = self.bme.faces
        else:
            faces = [self._unwrap(bmf) for bmf in faces]
        nearest = []
        for bmf in faces:
            pts = [Point_to_Point2D(self.xform.l2w_point(bmv.co)) for bmv in bmf.verts]
            pts = [pt for pt in pts if pt]
            pt0 = pts[0]
            # TODO: Get dist?
            for pt1,pt2 in zip(pts[1:-1],pts[2:]):
                if intersect_point_tri(xy, pt0, pt1, pt2):
                    nearest += [(self._wrap_bmface(bmf), dist)]
            #p2d = Point_to_Point2D(self.xform.l2w_point(bmv.co))
            #d2d = (xy - p2d).length
            #if p2d is None: continue
            #if bv is None or d2d < bd: bv,bd = bmv,d2d
        #if bv is None: return (None,None)
        #return (self._wrap_bmvert(bv),bd)
        return nearest

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

    def _visible_verts(self, is_visible:Callable[[Point,Normal], bool]):
        l2w_point, l2w_normal = self.xform.l2w_point, self.xform.l2w_normal
        #is_vis = lambda bmv: is_visible(l2w_point(bmv.co), l2w_normal(bmv.normal))
        is_vis = lambda bmv: is_visible(l2w_point(bmv.co), None)
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
