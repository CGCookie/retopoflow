import re
import sys
import math
import json
import copy
import time
import pickle
import binascii

import bgl
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

from .rftool_tweak_move import RFTool_Tweak_Move
from .rftool_tweak_relax import RFTool_Tweak_Relax

#######################################################
# import all the widgets here

from .rfwidget_circle import RFWidget_Circle

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
        
    
    def _init_usersettings(self):
        # user-defined settings
        self.settings = get_settings()
        
    def _init_tools(self):
        RFTool.init_tools(self)     # init tools
        RFWidget.init_widgets(self) # init widgets
        
        self.tool = None
        self.set_tool(RFTool_Tweak_Move())
        
        self.nav = False
    
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
            if not obj.data.polygons: continue                              # must have at least one polygon
            self.rfsources.append( RFSource.new(obj) )                      # obj is a valid source!
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
        self.rfwidget   = self.tool.rfwidget()  # current tool widget
    
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
        
        prev_tool = self.tool
        self._process_event(context, event)
        
        self.hit_pos,self.hit_norm,_,_ = self.raycast_sources_mouse()
        
        # user pressing nav key?
        if self.actions.using('navigate') or (self.actions.timer and self.nav):
            # let Blender handle navigation
            self.actions.unuse('navigate')  # pass-through commands do not receive a release event
            self.nav = True
            self.set_cursor('HAND')
            if self.rfwidget: self.rfwidget.clear()
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
            if self.tool:
                self.rfwidget = self.tool.rfwidget()
                if self.rfwidget:
                    self.rfwidget.update()
                    self.set_cursor(self.rfwidget.mouse_cursor())
            else:
                self.rfwidget = None
                self.set_cursor('CROSSHAIR')
        else:
            self.set_cursor('DEFAULT')
            if self.rfwidget: self.rfwidget.clear()
        
        if self.actions.pressed('select all'):
            self.select_toggle()
            return {}
        #if self.eventd.press in self.events_selection:
            # handle selection
            #print('select!')
            #self.ensure_lookup_tables()
            #self.select([self.rftarget.bme.verts[i] for i in range(4)])
            #return {}
        #    pass
        
        if self.tool and self.actions.valid_mouse(): self.tool.modal()
        
        if prev_tool != self.tool:
            # tool has changed
            # set up state of new tool
            self.tool_state = self.tool.start()
        
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
        
        if self.rfwidget:
            self.rfwidget.draw_postpixel()
        
        wtime,ctime = self.window_time,time.time()
        self.frames += 1
        if ctime >= wtime + 1:
            print('%f fps' % (self.frames / (ctime - wtime)))
            self.frames = 0
            self.window_time = ctime
        
    
    def draw_postview(self):
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_BLEND)
        
        self.rftarget_draw.draw()
        if self.rfwidget:
            self.rfwidget.draw_postview()
