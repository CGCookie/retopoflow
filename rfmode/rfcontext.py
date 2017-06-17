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
    - event details
    
    Target object is the active object.  Source objects will be all visible objects that are not active.
    
    RFContext object is passed to tools, and tools perform manipulations through the RFContext object.
    '''
    
    undo_depth = 100 # set in RF properties?
    
    def __init__(self, tool_set, context, event):
        self.init_target()              # set up target object
        self.init_sources()             # set up source objects
        self.tool_state = None          # state of current tool
        self.undo = []                  # undo stack of causing actions, FSM state, tool states, and rftargets
        self.redo = []                  # redo stack of causing actions, FSM state, tool states, and rftargets
        self.eventd = EventDetails()    # context, event details, etc.
        self.tool_set = tool_set
        
        for tool in self.tool_set.values():
            tool.start()
        
        self.update(context, event)
    
    def init_target(self):
        ''' target is the active object.  must be selected and visible '''
        tar_object = bpy.context.active_object
        assert tar_object and type(tar_object.data) is bpy.types.Mesh, 'Active object must be mesh object'
        assert tar_object.select, 'Active object must be selected'
        assert not tar_object.hide, 'Active object must be visible'
        assert any(ol and vl for ol,vl in zip(tar_object.layers, bpy.context.scene.layers)), 'Active object must be visible'
        self.rftarget = RFTarget.new(tar_object)
    
    def init_sources(self):
        ''' find all valid source objects, which are mesh objects that are visible and not active '''
        self.rfsources = []
        visible_layers = [i for i in range(20) if bpy.context.scene.layers[i]]
        for obj in bpy.context.scene.objects:
            if type(obj.data) is not bpy.types.Mesh: continue               # only mesh objects
            if obj is bpy.context.active_object: continue                   # exclude active object
            if not any(obj.layers[i] for i in visible_layers): continue     # must be on visible layer
            if obj.hide: continue                                           # cannot be hidden
            self.rfsources.append( RFSource.new(obj) )                      # obj is a valid source!
    
    def update(self, context, event):
        self.eventd.update(context, event)
    
    def end(self):
        pass
    
    
    ###################################################
    # undo / redo stack operations
    
    def _create_state(self, action):
        return {
            'action':     action,
            'tool_state': copy.deepcopy(self.tool_state),
            'rftarget':   copy.deepcopy(self.rftarget),
            }
    def _restore_state(self, state):
        self.tool_state = state['tool_state']
        self.rftarget = state['rftarget']
    
    def undo_push(self, action, repeatable=False):
        # skip pushing to undo if action is repeatable and we are repeating actions
        if repeatable and self.undo and self.undo[-1]['action'] == action: return
        self.undo.append(self._create_state(action))
        while len(self.undo) > self.undo_depth: self.undo.pop(0)     # limit stack size
        self.redo.clear()
    
    def undo_pop(self, action):
        if not self.undo: return
        self.redo.append(self._create_state('undo'))
        self._restore_state(self.undo.pop())
    
    def redo_pop(self):
        if not self.redo: return
        self.undo.append(self._create_state('redo'))
        self._restore_state(self.redo.pop())
    
    
    ###################################################
    
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
    
    
    ###################################################
    
    def deselect_all(self):
        pass
    def deselect(self, elems):
        pass
    def select(self, elems, subparts=False, only=True):
        pass
    
    # def get_elem(self, uid): return self.rftarget.get_elem(uid)
    # def get_uid(self, elem): return self.rftarget.get_uid(elem)
    
    # def get_active_uid(self): return self.state['active']
    # def get_active_elem(self): return self.get_elem(self.state['active'])
    
    # def get_select_uid(self): return set(self.state['select'])
    # def get_select_elem(self): return set(self.get_elem(e) for e in self.state['select'])
    
    # def is_active_uid(self, uid): return uid == self.state['active']
    # def is_active_elem(self, elem): return self.is_active_uid(self.get_elem(elem))
    
    # def is_select_uid(self, uid): return uid in self.state['select']
    # def is_select_elem(self, elem): return self.is_select_uid(self.get_elem(elem))
    
    # def deselect_all(self):
    #     self.state['select'].clear()
    #     self.state['active'] = None
    # def deselect_by_uid(self, uids):
    #     if '__len__' not in uids.__dir__(): uids = { uids }
    #     if self.state['active'] and self.state['active'] in uids:
    #         self.state['active'] = None
    #     self.state['select'].difference_update(uids)
    # def deselect_by_elem(self, elems):
    #     if '__len__' not in elems.__dir__(): elems = { elems }
    #     self.deselect_by_uid(self.get_uid(elem) for elem in elems)
    
    # def select_by_uid(self, uids, subparts=False, only=True):
    #     if only: self.deselect_all()
    #     if '__len__' not in uids.__dir__(): uids = { uids }
    #     if subparts:
    #         nuids = set(uids)
    #         for uid in uids:
    #             elem = self.get_elem(uid)
    #             t = type(elem)
    #             if t is bmesh.types.BMVert:
    #                 pass
    #             elif t is bmesh.types.BMEdge:
    #                 nuids.update(self.get_uid(e) for e in elem.verts)
    #             elif t is bmesh.types.BMFace:
    #                 nuids.update(self.get_uid(e) for e in elem.verts)
    #                 nuids.update(self.get_uid(e) for e in elem.edges)
    #         uids = nuids
    #     for uid in uids:
    #         self.state['select'].add(uid)
    #         self.active = uid
    # def select_by_elem(self, elems, subparts=False, only=True):
    #     if '__len__' not in elems.__dir__(): elems = { elems }
    #     self.select_by_uid((self.get_uid(elem) for elem in elems), subparts=subparts, only=only)
    
