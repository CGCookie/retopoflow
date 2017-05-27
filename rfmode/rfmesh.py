import sys
import math

import bpy
import bmesh
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from mathutils.bvhtree import BVHTree

from mathutils import Matrix,Vector
from .maths import Point,Direction,Normal,Ray,XForm


class RFMesh():
    '''
    RFMesh wraps a mesh object, providing extra machinery such as
    - computing hashes on the object (know when object has been modified)
    - maintaining a corresponding bmesh and bvhtree of the object
    - handling snapping and raycasting
    - translates to/from local space (transformations)
    '''
    
    @staticmethod
    def hash_object(obj:bpy.types.Object):
        if obj is None: return None
        assert type(obj) is bpy.types.Object, "Only call RFMesh.hash_object on mesh objects!"
        assert type(obj.data) is bpy.types.Mesh, "Only call RFMesh.hash_object on mesh objects!"
        # get object data to act as a hash
        me = obj.data
        counts = (len(me.vertices), len(me.edges), len(me.polygons), len(ob.modifiers))
        bbox   = (tuple(min(v.co for v in me.vertices)), tuple(max(v.co for v in me.vertices)))
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
        assert False, 'Do not create new RFMesh directly!  Use RFSource.create() or RFTarget.create()'
    
    def update_bvh(self):
        if self.bvh: del self.bvh
        self.bvh = BVHTree.FromBMesh(self.bme)
    
    def store_state(self):
        attributes = ['hide']       # list of attributes to remember
        self.prev_state = { attr: self.obj.__getattribute__(attr) for attr in attributes }
    def restore_state(self):
        for k,v in self.prev_state.iteritems(): self.obj.__setattr__(k, v)
    
    def obj_hide(self):   self.obj.hide = True
    def obj_unhide(self): self.obj.hide = False
    
    def ensure_lookup_tables(self):
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.faces.ensure_lookup_table()
    
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


class RFSource(RFMesh):
    '''
    RFSource is a source object for RetopoFlow.  Source objects
    are the meshes being retopologized.
    '''
    
    @staticmethod
    def new(obj:bpy.types.Object):
        assert type(obj) is bpy.types.Object and type(obj.data) is bpy.types.Mesh, 'obj must be mesh object'
        
        # check cache
        gennew = False
        if 'cache' not in RFSource:
            # create cache
            gennew = True
            RFSource.cache = {}
        elif obj.data.name not in RFSource.cache:
            gennew = True
        else:
            # does cache match current state?
            rfm = RFSource.cache[obj.data.name]
            gennew = rfm.hash != RFMesh.hash_object(obj)
        
        if gennew:
            RFSource.creating = True
            rfm = RFSource()
            del RFSource.creating
            RFSource.cache[obj.data.name] = rfm
        
        return RFSource.cache[obj.data.name]
    
    def __init__(self, obj:bpy.types.Object):
        assert 'creating' in dir(RFSource), 'Do not create new RFSource directly!  Use RFSource.new()'
        self.obj = obj
        self.xform = XForm(self.obj.matrix_world)
        self.hash = RFMesh.hash_object(self.obj)
        self.bme = bmesh.new()
        self.bme.from_object(self.obj, bpy.context.scene, deform=True)
        self.update_bvh()
        self.store_state()
    


class RFTarget(RFMesh):
    '''
    RFTarget is a target object for RetopoFlow.  Target objects
    are the retopologized meshes.
    '''
    
    @staticmethod
    def new(obj:bpy.types.Object):
        assert type(obj) is bpy.types.Object and type(obj.data) is bpy.types.Mesh, 'obj must be mesh object'
        
        bme = bmesh.new()
        bme.from_object(obj, bpy.context.scene. deform=False)
        
        rftarget = RFTarget.__new__(RFTarget)
        rftarget.setup(obj, bme)
        rftarget.setup_symmetry()
        rftarget.store_state()
        rftarget.obj_hide()
        return rftarget
    
    def __init__(self):
        assert False, 'Do not create new RFTarget directly!  Use RFTarget.new()'
    
    def __deepcopy__(self, memo):
        '''
        custom deepcopy method, because BMesh and BVHTree are not copyable
        '''
        rftarget = RFTarget.__new__(RFTarget)
        memo[id(self)] = rftarget
        rftarget.setup(self.obj, self.bme.copy())
        # deepcopy all remaining settings
        for k,v in self.__dict__.items():
            if k in rftarget.__dict__: continue
            setattr(rftarget, k, copy.deepcopy(v, memo))
        return rftarget
        
    def setup(self, obj:bpy.types.Object, bme:Bmesh):
        self.obj = obj
        self.xform = XForm(self.obj.matrix_world)
        self.bme = bme
        self.hash = RFMesh.hash_bmesh(self.bme)
        self.update_bvh()
        
        # get ready to label all of the geometry with uids
        genuids = False
        if 'vuid' not in self.bme.verts.layers.int:
            genuids = True
            self.bme.verts.layers.int.new('vuid')
        if 'euid' not in self.bme.edges.layers.int:
            genuids = True
            self.bme.edges.layers.int.new('euid')
        if 'fuid' not in self.bme.faces.layers.int:
            genuids = True
            self.bme.faces.layers.int.new('fuid')
        # convenience attributes
        self.vuid = self.bme.verts.layers.int['vuid']
        self.euid = self.bme.edges.layers.int['euid']
        self.fuid = self.bme.faces.layers.int['fuid']
        self.vefuid = { BMVert:self.vuid, BMEdge:self.euid, BMFace:self.fuid }
        
        # maps uid to BMesh geometry
        self.uidvef = { }
        
        # TODO: assert that serialized_data == self
        if genuids:
            # label as new!
            self.uid = 0
            for v in self.bme.verts: self.set_uid(v)
            for e in self.bme.edges: self.set_uid(e)
            for f in self.bme.faces: self.set_uid(f)
        else:
            # restore data
            for v in self.bme.verts: self.uidvef[v[self.vuid]] = v
            for e in self.bme.edges: self.uidvef[e[self.euid]] = e
            for f in self.bme.faces: self.uidvef[f[self.fuid]] = f
            self.uid = max(self.uidvef.keys())
    
    def setup_symmetry(self):
        # if Mirror modifier is attached, set up symmetry to match
        self.symmetry = set()
        for mod in self.obj.modifiers:
            if mod.type != 'MIRROR': continue
            if not mod.show_viewport: continue
            if mod.use_x: self.symmetry.add('x')
            if mod.use_y: self.symmetry.add('y')
            if mod.use_z: self.symmetry.add('z')
    
    def commit(self):
        self.object_write()
        self.restore_state()
    
    def cancel(self):
        self.restore_state()
    
    def object_write(self):
        self.bme.to_mesh(self.obj.data)
    
    
    def get_uid(self, elem):
        layer = self.vefuid.get(type(elem))
        return elem[layer] if layer else None
    def get_elem(self, uid):
        return self.uidvef.get(uid)
    
    def set_uid(self, elem, uid=None):
        layer = self.vefuid.get(type(elem))
        assert layer
        if uid is None: uid = self.new_uid()
        elem[layer] = uid
        self.uidvef[uid] = elem
        return elem
    def new_uid(self):
        self.uid += 1
        return self.uid
    
    def new_vert(self, co):
        return self.set_uid(self.bme.verts.new(co))
    def new_edge(self, lbmv):
        return self.set_uid(self.bme.edges.new(lbmv))
    def new_face(self, lbmv):
        return self.set_uid(self.bme.faces.new(lbmv))
    
    def set_uids(self):
        ''' ensure all geometry has uid '''
        for v in self.bme.verts: if v[self.vuid] == 0: self.set_uid(v)
        for e in self.bme.edges: if e[self.euid] == 0: self.set_uid(e)
        for f in self.bme.faces: if f[self.fuid] == 0: self.set_uid(f)