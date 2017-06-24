import sys
import math

import bpy
import bgl
import bmesh
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from mathutils.bvhtree import BVHTree

from mathutils import Matrix, Vector
from ..common.maths import Point, Direction, Normal, Ray, XForm
from ..lib import common_drawing_bmesh as bmegl
from ..lib.common_utilities import print_exception, print_exception2, showErrorMessage


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
        bbox   = (tuple(min(v.co for v in bme.verts)), tuple(max(v.co for v in bme.verts)))
        vsum   = tuple(sum((v.co for v in bme.verts), Vector((0,0,0))))
        return (counts, bbox, vsum)
    
    
    def __init__(self):
        assert False, 'Do not create new RFMesh directly!  Use RFSource.new() or RFTarget.new()'
    
    def __deepcopy__(self, memo):
        assert False, 'Do not copy me'
    
    def __setup__(self, obj, deform=False, bme=None):
        self.obj = obj
        self.xform = XForm(self.obj.matrix_world)
        self.is_dirty = True
        self.hash = RFMesh.hash_object(self.obj)
        if bme != None:
            self.bme = bme
        else:
            eme = self.obj.to_mesh(scene=bpy.context.scene, apply_modifiers=deform, settings='PREVIEW')
            eme.update()
            self.bme = bmesh.new()
            self.bme.from_mesh(eme)
            
            #self.bme = bmesh.new()
            #self.bme.from_object(self.obj, bpy.context.scene, deform=deform)
            self.bme.select_mode = {'FACE', 'EDGE', 'VERT'}
            self.copy_editmesh_selection()
        self.store_state()
        self.make_dirty()
        self.make_clean()
    
    
    ##########################################################
    
    def copy_editmesh_selection(self):
        sel = []
        for bmv,emv in zip(self.bme.verts, self.obj.data.vertices):
            bmv.select = emv.select
            if bmv.select: sel += ['v%d' % emv.index]
        for bme,eme in zip(self.bme.edges, self.obj.data.edges):
            bme.select = eme.select
            if bme.select: sel += ['e%d' % eme.index]
        for bmf,emf in zip(self.bme.faces, self.obj.data.polygons):
            bmf.select = emf.select
            if bmf.select: sel += ['f%d' % emf.index]
        print('%s: %s' % (str(type(self)),', '.join(sel)))
    
    
    ##########################################################
    
    def make_dirty(self):
        self.is_dirty = True
        self.version = RFMesh.generate_version_number()
    
    def make_clean(self):
        if hasattr(self, 'bvh'): del self.bvh
        self.bvh = BVHTree.FromBMesh(self.bme)
        self.is_dirty = False
    
    
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
    
    def raycast(self, ray:Ray):
        if not self.bvh: return (None,None,None,None)
        ray_local = self.xform.w2l_ray(ray)
        p,n,i,_ = self.bvh.ray_cast(ray_local.o, ray_local.d, ray_local.max)
        if p is None: return (None,None,None,None)
        p,n = self.xform * Point(p), self.xform * Normal(n)
        d = (ray.o - p).length
        return (p,n,i,d)
    
    def nearest(self, point:Point, max_dist=sys.float_info.max):
        if not self.bvh: return (None,None,None,None)
        point_local = self.xform.w2l_point(point)
        p,n,i,_ = self.bvh.nearest(point_local, max_dist)
        if p is None: return (None,None,None,None)
        p,n = self.xform.l2w_point(p), self.xform.l2w_normal(n)
        d = (point - p).length
        return (p,n,i,d)
    
    
    ##########################################################
    
    def deselect_all(self):
        for bmv in self.bme.bmverts: bmv.select = False
        for bme in self.bme.bmedges: bme.select = False
        for bmf in self.bme.bmfaces: bmf.select = False
    
    def deselect(self, elems):
        if not hasattr(elems, '__len__'):
            elems.select = False
        else:
            for bmelem in elems: bmelem.select = False
    
    def select(self, elems, subparts=False, only=True):
        if only: self.deselect_all()
        if not hasattr(elems, '__len__'): elems = [elems]
        if subparts:
            nelems = set(elems)
            for elem in elems:
                t = type(elem)
                if t is BMVert:
                    pass
                elif t is BMEdge:
                    nelems.update(e for e in elem.verts)
                elif t is BMFace:
                    nelems.update(e for e in elem.verts)
                    nelems.update(e for e in elem.edges)
            elems = nelems
        for elem in elems: elem.select = True


class RFSource(RFMesh):
    '''
    RFSource is a source object for RetopoFlow.  Source objects
    are the meshes being retopologized.
    '''
    
    cache = {}
    
    @staticmethod
    def new(obj:bpy.types.Object):
        assert type(obj) is bpy.types.Object and type(obj.data) is bpy.types.Mesh, 'obj must be mesh object'
        
        # check cache
        rfsource = None
        if obj.data.name in RFSource.cache:
            # does cache match current state?
            rfsource = RFSource.cache[obj.data.name]
            if rfsource.hash != RFMesh.hash_object(obj):
                rfsource = None
        if not rfsource:
            # need to (re)generate RFSource object
            RFSource.creating = True
            rfsource = RFSource()
            del RFSource.creating
            rfsource.__setup__(obj)
            RFSource.cache[obj.data.name] = rfsource
        
        return RFSource.cache[obj.data.name]
    
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
    
    def __deepcopy__(self, memo):
        '''
        custom deepcopy method, because BMesh and BVHTree are not copyable
        '''
        rftarget = RFTarget.__new__(RFTarget)
        memo[id(self)] = rftarget
        rftarget.__setup__(self.obj, bme=self.bme.copy())
        # deepcopy all remaining settings
        for k,v in self.__dict__.items():
            if k in rftarget.__dict__: continue
            setattr(rftarget, k, copy.deepcopy(v, memo))
        return rftarget
    
    def commit(self):
        self.write_editmesh()
        self.restore_state()
    
    def cancel(self):
        self.restore_state()
    
    def write_editmesh(self):
        self.bme.to_mesh(self.obj.data)
    
    


class RFMeshRender():
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
        self.version = None
    
    def clean(self):
        # return if rfmesh hasn't changed
        if self.version == self.rfmesh.version: return
        
        self.version = self.rfmesh.version # make not dirty first in case bad things happen while drawing
        print('RMesh.version = %d' % self.version)
        
        opts = dict(self.opts)
        if 'x' in self.rfmesh.symmetry: opts['mirror x'] = True
        print(str(opts))
        
        bgl.glNewList(self.bglCallList, bgl.GL_COMPILE)
        # do not change attribs if they're not set
        bmegl.glSetDefaultOptions(opts=self.opts)
        bgl.glPushMatrix()
        bgl.glMultMatrixf(self.bglMatrix)
        bmegl.glDrawBMFaces(self.bmesh.faces, opts=opts, enableShader=False)
        bmegl.glDrawBMEdges(self.bmesh.edges, opts=opts, enableShader=False)
        bmegl.glDrawBMVerts(self.bmesh.verts, opts=opts, enableShader=False)
        bgl.glDepthRange(0, 1)
        bgl.glPopMatrix()
        bgl.glEndList()
        
        print('f:%d e:%d v:%d' % (len(self.bmesh.faces), len(self.bmesh.edges), len(self.bmesh.verts)))
    
    def draw(self):
        try:
            self.clean()
            bmegl.bmeshShader.enable()
            bgl.glCallList(self.bglCallList)
        except:
            print_exception()
            pass
        finally:
            bmegl.bmeshShader.disable()


