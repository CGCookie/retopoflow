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
    
    
    def __init__(self):
        self.init_target()      # set up target object
        self.init_sources()     # set up source objects
        self.init_state()
        self.eventd = {}
        self.undo = []          # undo stack
    
    def init_target(self):
        tar_object = bpy.context.active_object
        assert tar_object and type(tar_object.data) is bpy.types.Mesh, 'Active object must be mesh object'
        assert tar_object.select, 'Active object must be selected'
        assert not tar_object.hide, 'Active object must be visible'
        assert any(ol and vl for ol,vl in zip(tar_object.layers, bpy.context.scene.layers)), 'Active object must be visible'
        self.rftarget = RFTarget.new(tar_object)
    
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
    
    def init_state(self):
        self.state = {
            'tool':   None,
            'select': set(),
            'active': None,
            'uidtool': dict(),
            # tool data will also store up in here
        }
    
    def update(self, context, event):
        '''
        Construct an event dictionary that is *slightly* more
        convenient than stringing together a bunch of logical
        conditions
        '''
        
        self.context = context
        
        event_ctrl  = 'CTRL+'  if event.ctrl  else ''
        event_shift = 'SHIFT+' if event.shift else ''
        event_alt   = 'ALT+'   if event.alt   else ''
        event_oskey = 'OSKEY+' if event.oskey else ''
        event_ftype = event_ctrl + event_shift + event_alt + event_oskey + event.type

        self.eventd = {
            'context': context,
            'region':  context.region,
            'r3d':     context.space_data.region_3d,

            'event':   event,

            'ctrl':    event.ctrl,
            'shift':   event.shift,
            'alt':     event.alt,
            'value':   event.value,
            'type':    event.type,

            'ftype':   event_ftype,
            'press':   event_ftype if event.value=='PRESS'   else None,
            'release': event_ftype if event.value=='RELEASE' else None,

            'mouse':   (float(event.mouse_region_x), float(event.mouse_region_y)),
            'mousepre':self.eventd.get('mouse'),
        }
        
        return self.eventd

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
        if not self.undo: return
        data = self.undo.pop()
        self.state    = data['state']
        self.rftarget = data['rftarget']
    
    def start(self):
        # hide target so we can render internally
        self.rftarget.obj_hide()
    
    def end(self):
        # reveal all previously unhidden RFMeshes
        for rfsource in self.rfsources: rfsource.restore_state()
        self.rftarget.restore_state()
    
    
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
    
