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

from .. import key_maps
from ..lib.common_utilities import get_settings
from ..common.maths import Point, Vec, Direction, Normal, Ray, XForm
from ..lib.eventdetails import EventDetails

from .rfmesh import RFSource, RFTarget, RFMeshRender

from .rftool import RFTool
from .rftool_tweak import RFTool_Tweak


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
    
    undo_depth = 100 # set in RF settings?
    
    def __init__(self):
        self.rftarget_draw = None
        self._init_usersettings()       # set up user-defined settings and key mappings
        self._init_target()             # set up target object
        self._init_sources()            # set up source objects
        self._init_toolset()            # set up tools used in RetopoFlow
        self.undo = []                  # undo stack of causing actions, FSM state, tool states, and rftargets
        self.redo = []                  # redo stack of causing actions, FSM state, tool states, and rftargets
        self.eventd = EventDetails()    # context, event details, etc.
    
    def _init_usersettings(self):
        # handle user-defined settings and key mappings
        self.settings = get_settings()
        self.keymap = key_maps.rtflow_default_keymap_generate()
        key_maps.navigation_language() # check keymap against system language
        user = key_maps.rtflow_user_keymap_generate()
        self.events_nav = user['navigate']
        self.events_selection = set()
        self.events_selection.update(user['select'])
        self.events_selection.update(user['select all'])
        self.events_confirm = user['confirm']
    
    def _init_toolset(self):
        self.tool_set = { rftool:rftool(self) for rftool in RFTool }    # create instances of each tool
        for tool in self.tool_set.values(): tool.init()                 # init each tool
        self.tool = None                                                # currently selected tool
        self.tool_state = None                                          # current tool state
    
    def _init_target(self):
        ''' target is the active object.  must be selected and visible '''
        
        # if user has modified the edit mesh, toggle into object then edit mode to update
        if bpy.context.mode == 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.mode_set(mode='EDIT')
        
        tar_object = bpy.context.active_object
        assert tar_object and type(tar_object.data) is bpy.types.Mesh, 'Active object must be mesh object'
        assert tar_object.select, 'Active object must be selected'
        assert not tar_object.hide, 'Active object must be visible'
        assert any(ol and vl for ol,vl in zip(tar_object.layers, bpy.context.scene.layers)), 'Active object must be visible'
        self.rftarget = RFTarget.new(tar_object)
        
        # HACK! TODO: FIXME!
        color_select = self.settings.theme_colors_selection[self.settings.theme]
        color_frozen = self.settings.theme_colors_frozen[self.settings.theme]
        opts = {
            'poly color': (color_frozen[0], color_frozen[1], color_frozen[2], 0.20),
            'poly color selected': (color_select[0], color_select[1], color_select[2], 0.20),
            'poly offset': 0.000010,
            'poly mirror color': (color_frozen[0], color_frozen[1], color_frozen[2], 0.10),
            'poly mirror color selected': (color_select[0], color_select[1], color_select[2], 0.10),
            'poly mirror offset': 0.000010,
            
            'line color': (color_frozen[0], color_frozen[1], color_frozen[2], 1.00),
            'line color selected': (color_select[0], color_select[1], color_select[2], 1.00),
            'line width': 2.0,
            'line offset': 0.000012,
            'line mirror stipple': False,
            'line mirror color': (color_frozen[0], color_frozen[1], color_frozen[2], 0.25),
            'line mirror color selected': (color_select[0], color_select[1], color_select[2], 0.25),
            'line mirror width': 1.5,
            'line mirror offset': 0.000012,
            'line mirror stipple': False,
            
            'point color': (color_frozen[0], color_frozen[1], color_frozen[2], 1.00),
            'point color selected': (color_select[0], color_select[1], color_select[2], 1.00),
            'point size': 5.0,
            'point offset': 0.000015,
            'point mirror color': (color_frozen[0], color_frozen[1], color_frozen[2], 0.25),
            'point mirror color selected': (color_select[0], color_select[1], color_select[2], 0.25),
            'point mirror size': 3.0,
            'point mirror offset': 0.000015,
        }
        self.rftarget_draw = RFMeshRender(self.rftarget, opts)
    
    def _init_sources(self):
        ''' find all valid source objects, which are mesh objects that are visible and not active '''
        self.rfsources = []
        visible_layers = [i for i in range(20) if bpy.context.scene.layers[i]]
        for obj in bpy.context.scene.objects:
            if type(obj.data) is not bpy.types.Mesh: continue               # only mesh objects
            if obj == bpy.context.active_object: continue                   # exclude active object
            if not any(obj.layers[i] for i in visible_layers): continue     # must be on visible layer
            if obj.hide: continue                                           # cannot be hidden
            self.rfsources.append( RFSource.new(obj) )                      # obj is a valid source!
    
    def commit(self):
        #self.rftarget.commit()
        pass
    
    def end(self):
        pass
    
    ###################################################
    # mouse cursor functions
    
    def set_cursor(self, cursor):
        # DEFAULT, NONE, WAIT, CROSSHAIR, MOVE_X, MOVE_Y, KNIFE, TEXT, PAINT_BRUSH, HAND, SCROLL_X, SCROLL_Y, SCROLL_XY, EYEDROPPER
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                win.cursor_modal_set(cursor)
    
    def restore_cursor(self): self.set_cursor('DEFAULT')
    
    ###################################################
    # undo / redo stack operations
    
    def _create_state(self, action):
        return {
            'action':       action,
            'tool':         self.tool,
            'tool_state':   copy.deepcopy(self.tool_state),
            'rftarget':     copy.deepcopy(self.rftarget),
            }
    def _restore_state(self, state):
        self.tool = state['tool']
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
    
    def modal(self, context, event):
        # returns set with actions for RFMode to perform
        #   {'confirm'}:    done with RFMode
        #   {'pass'}:       pass-through to Blender
        #   empty or None:  stay in modal
        
        prev_tool = self.tool
        self.eventd.update(context, event)
        
        if self.eventd.press in self.events_nav:
            # let Blender handle navigation
            return {'pass'}
        
        if self.eventd.press in self.events_confirm:
            # all done!
            return {'confirm'}
        
        if self.eventd.press in self.events_selection:
            # handle selection
            print('select!')
            self.rftarget.ensure_lookup_tables()
            self.rftarget.select([self.rftarget.bme.verts[i] for i in range(4)])
            return {}
        
        if self.tool: self.tool.modal()
        
        if prev_tool != self.tool:
            # tool has changed
            # set up state of new tool
            self.tool_state = self.tool_set[self.tool].start()
        
        return {}
    
    
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
    
    def deselect_all(self): self.rftarget.deselect_all()
    def deselect(self, elems): self.rftarget.deselect(elems)
    def select(self, elems, subparts=False, only=True): self.rftarget.select(elems, subparts=subparts, only=only)
    
    
    ###################################################
    
    def draw_postpixel(self):
        pass
    
    def draw_postview(self):
        self.rftarget_draw.draw()
