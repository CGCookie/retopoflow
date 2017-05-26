import sys
import math

import bpy
import bmesh
from bmesh.types import BMVert, BMEdge, BMFace
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
    
    __creating = False      # identifies that we are *probably* creating an RFMesh through proper methods
    cache = {}
    
    @classmethod
    def create(cls, obj:bpy.types.Object):
        assert obj is not None and type(obj) is bpy.types.Object, 'obj must be bpy.types.Object'
        assert type(obj.data) is bpy.types.Mesh, 'obj.data must be bpy.types.Mesh'
        
        # check cache
        gennew = False
        if obj.data.name not in cls.cache:
            gennew = True
        else:
            # does cache match current state?
            gennew = cls.cache[obj.data.name].hash != RFMesh.hash_object(obj)
        
        if gennew:
            RFMesh.__creating = True
            cls.cache[obj.data.name] = cls(obj)
            RFMesh.__creating = False
        
        return cls.cache[obj.data.name]
    
    @staticmethod
    def hash_object(obj:bpy.types.Object):
        if obj is None: return None
        assert type(obj) is bpy.types.Object, "Only call RFMesh.hash_object on mesh objects!"
        assert type(obj.data) is bpy.types.Mesh, "Only call RFMesh.hash_object on mesh objects!"
        # get object data to act as a hash
        me = ob.data
        counts = (len(me.vertices), len(me.edges), len(me.polygons), len(ob.modifiers))
        bbox   = (tuple(min(v.co for v in me.vertices)), tuple(max(v.co for v in me.vertices)))
        vsum   = tuple(sum((v.co for v in me.vertices), Vector((0,0,0))))
        xform  = tuple(e for l in obj.matrix_world for e in l)
        return (counts, bbox, vsum, xform)      # ob.name???
    
    def __init__(self, obj:bpy.types.Object):
        assert RFMesh.__creating, 'Do not create new RFMesh directly!  Use RFSource.create() or RFTarget.create()'
        self.obj = obj
        self.hash = RFMesh.hash_object(self.obj)
        self.xform = XForm(self.obj.matrix_world)
        self.eme = self.obj.to_mesh(scene=bpy.context.scene, apply_modifiers=True, settings='PREVIEW')
        self.eme.update()
        self.bme.from_mesh(self.eme)
        self.update_bvh()
        self.store_state()
    
    
    def update_bvh(self):
        self.bvh = BVHTree.FromBMesh(self.bme)
    
    def store_state(self):
        self.was_visible = not self.obj.hide
    def restore_state(self):
        self.obj.hide = not self.was_visible
    
    def hide(self):   self.obj.hide = True
    def unhide(self): self.obj.hide = False
    
    def is_valid(self):
        return self.hash == RFMesh.hash_object(self.obj)
    
    def ensure_lookup_tables(self):
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.faces.ensure_lookup_table()
    
    def raycast(self, ray:Ray):
        if not self.bvh or not self.visible or not self.hitable: return (None,None,None,None)
        ray_local = self.xform.w2l_ray(ray)
        p,n,i,_ = self.bvh.ray_cast(ray_local.o, ray_local.d, ray_local.max)
        if p is None: return (None,None,None,None)
        p,n = self.xform * Point(p), self.xform * Normal(n)
        d = (ray.o - p).length
        return (p,n,i,d)
    
    def nearest(self, point:Point, max_dist=sys.float_info.max):
        if not self.bvh or not self.visible or not self.hitable: return (None,None,None,None)
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
    
    def __init__(self, obj:bpy.types.Object):
        assert RFMesh.__creating, 'Do not create new RFSource directly!  Use RFSource.create()'
        
        super().__init__(obj)
        self.set_object(obj)
    
    def render(self):
        pass


class RFTarget(RFMesh):
    '''
    RFTarget is a target object for RetopoFlow.  Target objects
    are the retopologized meshes.
    '''
    
    def __init__(self, obj:bpy.types.Object=None):
        assert RFMesh.__creating, 'Do not create new RFTarget directly!  Use RFTarget.create()'
        
        super().__init__()
        self.set_object(obj)
        self.hide()
        
        self.symmetry = {}
        self.selection = set()
        self.active = None
        
        # the tool layer gives indication to which tool is managing
        # that vert/edge/face.  for example:
        #     0 : none (regular, unmanaged geometry)
        #     1 : contours
        #     2 : polystrips
        self.tools = {
            'v': self.bme.verts.layers.int.new('tool'),
            'e': self.bme.edges.layers.int.new('tool'),
            'f': self.bme.faces.layers.int.new('tool'),
        }
    
    def get_active(self): return self.active
    def get_select(self): return set(self.selection)
    
    def is_active(self, item): return item is self.active
    def is_select(self, item): return item in self.selection
    
    def deselect_all(self):
        # deselect all
        self.deselect(set(self.selection))
    
    def deselect(self, items):
        if '__len__' not in items.__dir__(): items = { items }
        for item in items:
            #assert item in self.selection
            if self.is_active(item): self.active = None
            item.select = False
            self.selection.remove(item)
    
    def select(self, items, subparts=False, only=True):
        if only: self.deselect_all()
        if '__len__' not in items.__dir__(): items = { items }
        if subparts:
            nitems = set(items)
            for item in items:
                t = type(item)
                if t is bmesh.types.BMVert:
                    pass
                elif t is bmesh.types.BMEdge:
                    nitems.update(item.verts)
                elif t is bmesh.types.BMFace:
                    nitems.update(item.verts)
                    nitems.update(item.edges)
            items = nitems
        for item in items:
            item.select = True
            self.selection.add(item)
            self.active = items
    
    def render(self):
        pass
