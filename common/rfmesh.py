import sys
import math

import bpy
import bmesh
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
        assert type(obj) is bpy.types.Object, "Can only call RFMesh.hash_object on bpy.types.Object"
        # get object data to act as a hash
        me = ob.data
        counts = (len(me.vertices), len(me.edges), len(me.polygons), len(ob.modifiers))
        bbox   = (tuple(min(v.co for v in me.vertices)), tuple(max(v.co for v in me.vertices)))
        vsum   = tuple(sum((v.co for v in me.vertices), Vector((0,0,0))))
        xform  = tuple(e for l in obj.matrix_world for e in l)
        return (counts, bbox, vsum, xform)      # ob.name???
    
    def __init__(self):
        self.bme = bmesh.new()
        self.xform = XForm()
        self.src = None
        self.hash = None
        self.srcme = None
        self.bvh = None
        self.visible = True
        self.hitable = True
        self.src_was_hidden = False
    
    def set_source(self, srcObject:bpy.types.Object):
        '''
        Assigns underlying bpy.types.Object to wrap
        '''
        assert self.src is None, "Can only call RFMesh.set_source once"
        if srcObject is None: return
        
        # TODO: optimize by using cache keyed on hash!
        
        self.src = srcObject
        self.src_was_hidden = self.src.hide
        self.hash = RFMesh.hash_object(self.src)
        self.xform = XForm(self.src.matrix_world)
        self.srcme = self.src.to_mesh(scene=bpy.context.scene, apply_modifiers=True, settings='PREVIEW')
        self.srcme.update()
        self.bme.from_mesh(self.srcme)
        self.update_bvh()
    
    def is_valid(self):
        return self.hash == RFMesh.hash_object(self.src)
    
    def update_bvh(self):
        self.bvh = BVHTree.FromBMesh(self.bme)
    
    def ensure_lookup_tables(self):
        self.bme.verts.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.faces.ensure_lookup_table()
    
    def raycast(self, ray:Ray):
        if not self.bvh or  not self.visible or not self.hitable: return (None,None,None,None)
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
    def __init__(self, srcObj:bpy.types.Object):
        assert srcObj, "Must specify a srcObj for RFSource"
        assert type(srcObj) is bpy.types.Object, "RFSource srcObj must be bpy.types.Object"
        super().__init__()
        self.set_source(srcObj)
    
    def render(self):
        pass


class RFTarget(RFMesh):
    '''
    RFTarget is a target object for RetopoFlow.  Target objects
    are the retopologized meshes.
    '''
    def __init__(self, src:bpy.types.Object=None):
        super().__init__()
        self.set_source(src)
        
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
        for item in self.selection: item.select = False
        self.selection.clear()
        self.active = None
    
    def deselect(self, item):
        assert item in self.selection
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
