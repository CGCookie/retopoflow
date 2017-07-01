import re
import sys
import math
import json
import copy
import time
import pickle
import binascii

import bgl
import blf
import bpy
import bmesh
from bmesh.types import BMVert, BMEdge, BMFace
from mathutils.bvhtree import BVHTree
from mathutils import Matrix, Vector

from .rfcontext_actions import RFContext_Actions
from .rfcontext_spaces import RFContext_Spaces
from .rfcontext_target import RFContext_Target

from ..lib.common_utilities import get_settings
from ..common.maths import Point, Vec, Direction, Normal, Ray, XForm
from ..common.maths import Point2D, Vec2D, Direction2D

from .rfmesh import RFSource, RFTarget, RFMeshRender

from .rftool import RFTool
from .rfwidget import RFWidget


#######################################################
# import all the tools here

from .rftool_move import RFTool_Move
from .rftool_relax import RFTool_Relax

#######################################################


class RFContext(RFContext_Actions, RFContext_Spaces, RFContext_Target):
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
    
    instance = None     # reference to the current instance of RFContext
    
    undo_depth = 100    # set in RF settings?
    
    @staticmethod
    def is_valid_source(o):
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if not any(vl and ol for vl,ol in zip(bpy.context.scene.layers, o.layers)): return False
        if o.hide: return False
        if o.select and o == bpy.context.active_object: return False
        if not o.data.polygons: return False
        return True
    
    @staticmethod
    def is_valid_target(o):
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if not any(vl and ol for vl,ol in zip(bpy.context.scene.layers, o.layers)): return False
        if o.hide: return False
        if not o.select: return False
        if o != bpy.context.active_object: return False
        return True
    
    @staticmethod
    def has_valid_source():
        return any(True for o in bpy.context.scene.objects if RFContext.is_valid_source(o))
    
    @staticmethod
    def has_valid_target():
        return RFContext.get_target() is not None
    
    @staticmethod
    def get_sources():
        return [o for o in bpy.context.scene.objects if RFContext.is_valid_source(o)]
    
    @staticmethod
    def get_target():
        o = bpy.context.active_object
        return o if RFContext.is_valid_target(o) else None
    
    def __init__(self):
        RFContext.instance = self
        self.undo = []                  # undo stack of causing actions, FSM state, tool states, and rftargets
        self.redo = []                  # redo stack of causing actions, FSM state, tool states, and rftargets
        
        self._init_tools()              # set up tools and widgets used in RetopoFlow
        self._init_actions()            # set up default and user-defined actions
        self._init_usersettings()       # set up user-defined settings and key mappings
        
        self._init_target()             # set up target object
        self._init_sources()            # set up source objects
        
        self.start_time = time.time()
        self.window_time = time.time()
        self.frames = 0
        
        self.timer = None
        self.fps = 0
        self.show_fps = True
    
    def _init_usersettings(self):
        # user-defined settings
        self.settings = get_settings()
        
    def _init_tools(self):
        self.rfwidget = RFWidget.new(self)  # init widgets
        RFTool.init_tools(self)             # init tools
        
        self.tool = None
        self.set_tool(RFTool_Move())
        
        self.nav = False
    
    def _init_target(self):
        ''' target is the active object.  must be selected and visible '''
        
        # if user has modified the edit mesh, toggle into object then edit mode to update
        if bpy.context.mode == 'EDIT_MESH':
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.object.mode_set(mode='EDIT')
        
        tar_object = RFContext.get_target()
        assert tar_object, 'Could not find valid target?'
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
        self.rfsources = [RFSource.new(src) for src in RFContext.get_sources()]
        print('%d sources' % len(self.rfsources))
    
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
    
    def set_tool(self, tool):
        if self.tool == tool: return
        self.tool       = tool                  # currently selected tool
        self.tool_state = self.tool.start()     # current tool state
    
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
        self.rftarget.dirty()
        self.rftarget_draw.replace_rfmesh(self.rftarget)
    
    def undo_push(self, action, repeatable=False):
        # skip pushing to undo if action is repeatable and we are repeating actions
        if repeatable and self.undo and self.undo[-1]['action'] == action: return
        self.undo.append(self._create_state(action))
        while len(self.undo) > self.undo_depth: self.undo.pop(0)     # limit stack size
        self.redo.clear()
    
    def undo_pop(self):
        if not self.undo: return
        self.redo.append(self._create_state('undo'))
        self._restore_state(self.undo.pop())
    
    def undo_cancel(self):
        if not self.undo: return
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
        
        self._process_event(context, event)
        
        self.hit_pos,self.hit_norm,_,_ = self.raycast_sources_mouse()
        
        # user pressing nav key?
        if self.actions.using('navigate') or (self.actions.timer and self.nav):
            # let Blender handle navigation
            self.actions.unuse('navigate')  # pass-through commands do not receive a release event
            self.nav = True
            self.set_cursor('HAND')
            self.rfwidget.clear()
            return {'pass'}
        self.nav = False
        
        
        # handle undo/redo
        if self.actions.pressed('undo'):
            self.undo_pop()
            return {}
        if self.actions.pressed('redo'):
            self.redo_pop()
            return {}
        
        for action,tool in RFTool.action_tool:
            if self.actions.pressed(action):
                self.set_tool(tool())
        
        if self.actions.valid_mouse():
            self.rfwidget.update()
            self.set_cursor(self.rfwidget.mouse_cursor())
        else:
            self.rfwidget.clear()
            self.set_cursor('DEFAULT')
        
        if self.actions.pressed('select all'):
            self.select_toggle()
            return {}
        
        if self.rfwidget.modal():
            if self.tool and self.actions.valid_mouse(): self.tool.modal()
        
        if self.actions.pressed('done'):
            # all done!
            return {'confirm'}
        
        return {}
    
    
    ###################################################
    # RFSource functions
    
    def raycast_sources_Ray(self, ray:Ray):
        bp,bn,bi,bd = None,None,None,None
        for rfsource in self.rfsources:
            hp,hn,hi,hd = rfsource.raycast(ray)
            if bp is None or (hp is not None and hd < bd):
                bp,bn,bi,bd = hp,hn,hi,hd
        return (bp,bn,bi,bd)
    
    def raycast_sources_Point2D(self, xy:Point2D):
        return self.raycast_sources_Ray(self.Point2D_to_Ray(xy))
    
    def raycast_sources_mouse(self):
        return self.raycast_sources_Point2D(self.actions.mouse)
    
    def nearest_sources_Point(self, point:Point, max_dist=float('inf')): #sys.float_info.max):
        bp,bn,bi,bd = None,None,None,None
        for rfsource in self.rfsources:
            hp,hn,hi,hd = rfsource.nearest(point, max_dist=max_dist)
            if bp is None or (hp is not None and hd < bd):
                bp,bn,bi,bd = hp,bn,hi,hd
        return (bp,bn,bi,bd)
    
    
    ###################################################
    
    def draw_postpixel(self):
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_BLEND)
        
        self.rfwidget.draw_postpixel()
        
        wtime,ctime = self.window_time,time.time()
        self.frames += 1
        if ctime >= wtime + 1:
            self.fps = self.frames / (ctime - wtime)
            self.frames = 0
            self.window_time = ctime
        
        if self.show_fps:
            font_id = 0
            bgl.glColor4f(1.0, 1.0, 1.0, 0.10)
            blf.position(font_id, 5, 5, 0)
            blf.size(font_id, 12, 72)
            blf.draw(font_id, 'fps: %0.2f' % self.fps)
        
    
    def draw_postview(self):
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_BLEND)
        
        self.rftarget_draw.draw()
        self.rfwidget.draw_postview()
