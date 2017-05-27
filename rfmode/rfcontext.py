import re
import sys
import math
import json
import copy
import pickle
import binascii

import bpy
import bmesh
from mathutils.bvhtree import BVHTree
from mathutils import Matrix, Vector

from ..common.maths import Point, Vec, Direction, Normal, Ray, XForm

from .rfmesh import RFSource, RFTarget


class RFContext:
    '''
    RFContext contains data and functions that are useful across all of RetopoFlow, such as:
    
    - RetopoFlow settings
    - xform matrices, xfrom functions (raycast from screen space coord, etc.)
    - list of source objects, along with associated BVH, BMesh
    - undo stack
    - current state in FSM
    
    Each RetopoFlow target will have its own RFContext.  The context is stored in a text block
    so work can be resumed after saving and quitting (context is saved in .blend), or even for
    debugging purposes.
    
    NOTE: the source objects will be based on what is visible
    
    RFContext object is passed to tools, and tools perform manipulations through the RFContext object.
    '''
    
    
    def __init__(self):
        obj = bpy.context.active_object
        assert obj and type(obj.data) is bpy.types.Mesh, 'Active object must be mesh object'
        assert obj.select, 'Active object must be selected'
        assert not obj.hide, 'Active object must be visible'
        assert any(ol and vl for ol,vl in zip(obj.layers, bpy.context.scene.layers)), 'Active object must be visible'
        
        # set up source objects
        self.init_sources()
        
        # set up state object
        self.tbname = 'RetopoFlow_Context.%s' % (obj.data.name)
        self.state = None
        if self.tbname not in bpy.data.texts:
            bpy.data.texts.new(self.tbname)
        else:
            self.textblock_read()   # attempt to read from text block
        if not self.state:
            self.init_state()
        
        self.undo = []      # undo stack
        
        # set up target object
        self.targetobj = obj
        self.rftarget = RFTarget.new(self.targetobj)
    
    def init_state(self):
        self.state = {
            'tool':   None,
            'select': set(),
            'active': None,
            'uidtool': dict(),
            # tool data will also store up in here
        }
    
    def init_sources(self):
        '''
        find all valid source objects
        note: can be called multiple times
        '''
        self.rfsources = []
        visible_layers = [i for i in range(20) if bpy.context.scene.layers[i]]
        for obj in bpy.context.scene.objects:
            if type(obj.data) is not bpy.types.Mesh: continue               # only mesh objects
            if obj is bpy.context.active_object: continue                   # exclude active object
            if not any(obj.layers[i] for i in visible_layers): continue     # must be on visible layer
            if obj.hide: continue                                           # cannot be hidden
            self.rfsources.append( RFSource.new(obj) )                      # obj is a valid source!
    
    def undo_push(self, action, repeatable=False):
        # if action is repeatable and we are repeating actions, skip pushing to undo stack
        if repeatable and self.undo and self.undo[-1]['action'] == action: return
        self.undo.append({
            'action':   action,
            'state':    copy.deepcopy(self.state),
            'rftarget': copy.deepcopy(self.rftarget),
        })
        while len(self.undo) > undo_depth: self.undo.pop(0)     # limit stack size
    
    def undo_pop(self, action):
        if len(self.undo) == 0: return
        data = self.undo.pop()
        self.state    = data['state']
        self.rftarget = data['rftarget']
    
    def textblock_write(self):
        # write current state to text block
        # https://docs.python.org/3/library/binascii.html
        b = pickle.dumps(self.state)
        a = binascii.b2a_hex(p).decode('utf-8')
        bpy.data.texts[self.tbname].from_string(a)
        # update editmesh to match!
        self.rftarget.object_write()
    
    def textblock_read(self):
        # read current state from text block
        # https://docs.python.org/3/library/binascii.html
        try:
            a = bpy.data.texts[self.tbname].as_string()
            b = binascii.a2b_hex(a)
            self.state = pickle.loads(b)
            # NOTE: READ STATE MAY DIFFER FROM EDITMESH!!!!! TODO: FIX ME!!! XXXX
        except Error:
            self.state = None
    
    def start(self):
        # hide all unhidden sources so we can render internally
        pass
    
    def end(self):
        # reveal all previously unhidden sources
        pass
    
    
    def raycast_sources(self, ray:Ray):
        bp,bn,bi,bd = None,None,None,None
        for rfsource in self.rfsources:
            hp,hn,hi,hd = rfsource.raycast(ray)
            if bp is None or (hd is not None and hd < bd):
                bp,bn,bi,bd = hp,bn,hi,hd
        return (bp,bn,bi,bd)
    
    def nearest_sources(self, point:Point, max_dist=sys.float_info.max):
        bp,bn,bi,bd = None,None,None,None
        for rfsource in self.rfsources:
            hp,hn,hi,hd = rfsource.nearest(point, max_dist=max_dist)
            if bp is None or (hd is not None and hd < bd):
                bp,bn,bi,bd = hp,bn,hi,hd
        return (bp,bn,bi,bd)

    def get_elem(self, uid): return self.rftarget.get_elem(uid)
    def get_uid(self, elem): return self.rftarget.get_uid(elem)
    
    def get_active_uid(self): return self.state['active']
    def get_active_elem(self): return self.get_elem(self.state['active'])
    
    def get_select_uid(self): return set(self.state['select'])
    def get_select_elem(self): return set(self.get_elem(e) for e in self.state['select'])
    
    def is_active_uid(self, uid): return uid == self.state['active']
    def is_active_elem(self, elem): return self.is_active_uid(self.get_elem(elem))
    
    def is_select_uid(self, uid): return uid in self.state['select']
    def is_select_elem(self, elem): return self.is_select_uid(self.get_elem(elem))
    
    def deselect_all(self):
        self.state['select'].clear()
        self.state['active'] = None
    def deselect_by_uid(self, uids):
        if '__len__' not in uids.__dir__(): uids = { uids }
        if self.state['active'] and self.state['active'] in uids:
            self.state['active'] = None
        self.state['select'].difference_update(uids)
    def deselect_by_elem(self, elems):
        if '__len__' not in elems.__dir__(): elems = { elems }
        self.deselect_by_uid(self.get_uid(elem) for elem in elems)
    
    def select_by_uid(self, uids, subparts=False, only=True):
        if only: self.deselect_all()
        if '__len__' not in uids.__dir__(): uids = { uids }
        if subparts:
            nuids = set(uids)
            for uid in uids:
                elem = self.get_elem(uid)
                t = type(elem)
                if t is bmesh.types.BMVert:
                    pass
                elif t is bmesh.types.BMEdge:
                    nuids.update(self.get_uid(e) for e in elem.verts)
                elif t is bmesh.types.BMFace:
                    nuids.update(self.get_uid(e) for e in elem.verts)
                    nuids.update(self.get_uid(e) for e in elem.edges)
            uids = nuids
        for uid in uids:
            self.state['select'].add(uid)
            self.active = uid
    def select_by_elem(self, elems, subparts=False, only=True):
        if '__len__' not in elems.__dir__(): elems = { elems }
        self.select_by_uid((self.get_uid(elem) for elem in elems), subparts=subparts, only=only)
    
