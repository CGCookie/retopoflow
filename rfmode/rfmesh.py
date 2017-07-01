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
from ..common.maths import Point, Direction, Normal, Ray, XForm, BBox, Point2D, Vec2D
from ..lib import common_drawing_bmesh as bmegl
from ..lib.common_utilities import print_exception, print_exception2, showErrorMessage

from .rfmesh_wrapper import BMElemWrapper, RFVert, RFEdge, RFFace


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
        return (counts, bbox, vsum, xform)      # ob.name???
    
    @staticmethod
    def hash_bmesh(bme:BMesh):
        if bme is None: return None
        assert type(bme) is BMesh, 'Only call RFMesh.hash_bmesh on BMesh objects!'
        counts = (len(bme.verts), len(bme.edges), len(bme.faces))
        bbox   = BBox(from_bmverts=self.bme.verts)
        vsum   = tuple(sum((v.co for v in bme.verts), Vector((0,0,0))))
        return (counts, tuple(bbox.min), tuple(bbox.max), vsum)
    
    
    def __init__(self):
        assert False, 'Do not create new RFMesh directly!  Use RFSource.new() or RFTarget.new()'
    
    def __deepcopy__(self, memo):
        assert False, 'Do not copy me'
    
    def __setup__(self, obj, deform=False, bme=None):
        self.obj = obj
        self.xform = XForm(self.obj.matrix_world)
        self.hash = RFMesh.hash_object(self.obj)
        if bme != None:
            self.bme = bme
        else:
            eme = self.obj.to_mesh(scene=bpy.context.scene, apply_modifiers=deform, settings='PREVIEW')
            eme.update()
            self.bme = bmesh.new()
            self.bme.from_mesh(eme)
            self.bme.select_mode = {'FACE', 'EDGE', 'VERT'}
            # copy selection from editmesh
            for bmf,emf in zip(self.bme.faces, self.obj.data.polygons):
                bmf.select = emf.select
            for bme,eme in zip(self.bme.edges, self.obj.data.edges):
                bme.select = eme.select
            for bmv,emv in zip(self.bme.verts, self.obj.data.vertices):
                bmv.select = emv.select
        self.store_state()
        self.dirty()
    
    
    ##########################################################
    
    def dirty(self):
        # TODO: add option for dirtying only selection or geo+topo
        if hasattr(self, 'bvh'): del self.bvh
        self.version = RFMesh.generate_version_number()
    
    def clean(self):
        pass
    
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
    
    def wrap_bmvert(self, bmv): return RFVert(bmv)
    def wrap_bmedge(self, bme): return RFEdge(bme)
    def wrap_bmface(self, bmf): return RFFace(bmf)
    
    def raycast(self, ray:Ray):
        ray_local = self.xform.w2l_ray(ray)
        p,n,i,d = self.get_bvh().ray_cast(ray_local.o, ray_local.d, ray_local.max)
        if p is None: return (None,None,None,None)
        if not self.get_bbox().Point_within(p, margin=1):
            return (None,None,None,None)
        p_w,n_w = self.xform.l2w_point(p), self.xform.l2w_normal(n)
        d_w = (ray.o - p_w).length
        return (p_w,n_w,i,d_w)
    
    def nearest(self, point:Point, max_dist=float('inf')): #sys.float_info.max):
        point_local = self.xform.w2l_point(point)
        p,n,i,_ = self.get_bvh().find_nearest(point_local, max_dist)
        if p is None: return (None,None,None,None)
        p,n = self.xform.l2w_point(p), self.xform.l2w_normal(n)
        d = (point - p).length
        return (p,n,i,d)
    
    def nearest_bmvert_Point(self, point:Point):
        point_local = self.xform.w2l_point(point)
        bv,bd = None,None
        for bmv in self.bme.verts:
            d3d = (bmv.co - point_local).length
            if bv is None or d3d < bd: bv,bd = bmv,d3d
        bmv_world = self.xform.l2w_point(bv.co)
        return (self.wrap_bmvert(bv),(point-bmv_world).length)
    
    def nearest_bmverts_Point(self, point:Point, dist3d:float):
        nearest = []
        for bmv in self.bme.verts:
            bmv_world = self.xform.l2w_point(bmv.co)
            d3d = (bmv_world - point).length
            if d3d > dist3d: continue
            nearest += [(self.wrap_bmvert(bmv), d3d)]
        return nearest
    
    def nearest2D_bmverts_Point2D(self, xy:Point2D, dist2D:float, Point_to_Point2D):
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        nearest = []
        for bmv in self.bme.verts:
            p2d = Point_to_Point2D(self.xform.l2w_point(bmv.co))
            if p2d is None: continue
            if (p2d - xy).length > dist2D: continue
            d3d = 0
            nearest += [(self.wrap_bmvert(bmv), d3d)]
        return nearest
    
    def nearest2D_bmvert_Point2D(self, xy:Point2D, Point_to_Point2D):
        # TODO: compute distance from camera to point
        # TODO: sort points based on 3d distance
        bv,bd = None,None
        for bmv in self.bme.verts:
            p2d = Point_to_Point2D(self.xform.l2w_point(bmv.co))
            d2d = (xy - p2d).length
            if p2d is None: continue
            if bv is None or d2d < bd: bv,bd = bmv,d2d
        if bv is None: return (None,None)
        return (self.wrap_bmvert(bv),bd)
    
    ##########################################################
    
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
        for elem in elems: elem.select = True
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
        
        # check cache
        rfsource = None
        if obj.data.name in RFSource.__cache:
            # does cache match current state?
            rfsource = RFSource.__cache[obj.data.name]
            if rfsource.hash != RFMesh.hash_object(obj):
                rfsource = None
        if not rfsource:
            # need to (re)generate RFSource object
            RFSource.creating = True
            rfsource = RFSource()
            del RFSource.creating
            rfsource.__setup__(obj)
            RFSource.__cache[obj.data.name] = rfsource
        
        return RFSource.__cache[obj.data.name]
    
    def __init__(self):
        assert hasattr(RFSource, 'creating'), 'Do not create new RFSource directly!  Use RFSource.new()'
    
    def __setup__(self, obj:bpy.types.Object):
        super().__setup__(obj, deform=True)
    


class RFTarget(RFMesh):
    '''
    RFTarget is a target object for RetopoFlow.  Target objects
    are the retopologized meshes.
    '''
    
    @staticmethod
    def new(obj:bpy.types.Object):
        assert type(obj) is bpy.types.Object and type(obj.data) is bpy.types.Mesh, 'obj must be mesh object'
        
        RFTarget.creating = True
        rftarget = RFTarget()
        del RFTarget.creating
        rftarget.__setup__(obj)
        BMElemWrapper.wrap(rftarget)
        return rftarget
    
    def __init__(self):
        assert hasattr(RFTarget, 'creating'), 'Do not create new RFTarget directly!  Use RFTarget.new()'
    
    def __setup__(self, obj:bpy.types.Object, bme:bmesh.types.BMesh=None):
        super().__setup__(obj, bme=bme)
        # if Mirror modifier is attached, set up symmetry to match
        self.symmetry = set()
        for mod in self.obj.modifiers:
            if mod.type != 'MIRROR': continue
            if not mod.show_viewport: continue
            if mod.use_x: self.symmetry.add('x')
            if mod.use_y: self.symmetry.add('y')
            if mod.use_z: self.symmetry.add('z')
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
        for bmf,emf in zip(self.bme.faces, self.obj.data.polygons):
            emf.select = bmf.select
        for bme,eme in zip(self.bme.edges, self.obj.data.edges):
            eme.select = bme.select
        for bmv,emv in zip(self.bme.verts, self.obj.data.vertices):
            emv.select = bmv.select
    
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
    
    ALWAYS_DIRTY = True
    
    def __init__(self, rfmesh, opts):
        self.opts = opts
        self.replace_rfmesh(rfmesh)
        self.bglCallList = bgl.glGenLists(1)
        self.bglMatrix = rfmesh.xform.to_bglMatrix()
    
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


