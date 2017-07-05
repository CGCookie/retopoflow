import re
import os
import sys
import math
import json
import copy
import time
import glob
import inspect
import pickle
import binascii
import importlib

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

def find_all_rftools(root=None):
    if not root:
        addons = bpy.context.user_preferences.addons
        folderpath = os.path.dirname(os.path.abspath(__file__))
        while folderpath:
            rootpath,foldername = os.path.split(folderpath)
            if foldername in addons: break
            folderpath = rootpath
        else:
            assert False, 'Could not find root folder'
        return find_all_rftools(folderpath)
    
    if not hasattr(find_all_rftools, 'touched'):
        find_all_rftools.touched = set()
    root = os.path.abspath(root)
    if root in find_all_rftools.touched: return
    find_all_rftools.touched.add(root)
    
    found = False
    for path in glob.glob(os.path.join(root, '*')):
        if os.path.isdir(path):
            # recurse?
            found |= find_all_rftools(path)
        elif os.path.splitext(path)[1] == '.py':
            rft = os.path.splitext(os.path.basename(path))[0]
            try:
                tmp = importlib.__import__(rft, globals(), locals(), [], level=1)
                for k in dir(tmp):
                    v = tmp.__getattribute__(k)
                    if inspect.isclass(v) and v is not RFTool and issubclass(v, RFTool):
                        # v is an RFTool, so add it to the global namespace
                        globals()[k] = v
                        found = True
            except Exception as e:
                if 'rftool' in rft:
                    print('Could not import ' + rft)
                    print(e)
                pass
    return found
assert find_all_rftools(), 'Could not find RFTools'


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
    
    def __init__(self, starting_tool):
        RFContext.instance = self
        self.undo = []                  # undo stack of causing actions, FSM state, tool states, and rftargets
        self.redo = []                  # redo stack of causing actions, FSM state, tool states, and rftargets
        
        self._init_tools()              # set up tools and widgets used in RetopoFlow
        self._init_actions()            # set up default and user-defined actions
        self._init_usersettings()       # set up user-defined settings and key mappings
        
        self._init_target()             # set up target object
        self._init_sources()            # set up source objects
        
        if starting_tool:
            self.set_tool(starting_tool)
        else:
            self.set_tool(RFTool_Move())
        
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
        self.nav = False                    # not currently navigating
        #self.set_tool(RFTool_Move())        # set default tool
    
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
        
        zy_plane = self.rftarget.get_yz_plane()
        self.zy_intersections = []
        for rfs in self.rfsources:
            self.zy_intersections += rfs.plane_intersection(zy_plane)
    
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
        if hasattr(self, 'tool') and self.tool == tool: return
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
        
        if self.actions.using('maximize area'):
            return {'pass'}
        
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
        
        self.tool.draw_postpixel()
        self.rfwidget.draw_postpixel()
        
        wtime,ctime = self.window_time,time.time()
        self.frames += 1
        if ctime >= wtime + 1:
            self.fps = self.frames / (ctime - wtime)
            self.frames = 0
            self.window_time = ctime
        
        font_id = 0
        
        if self.show_fps:
            bgl.glColor4f(1.0, 1.0, 1.0, 0.10)
            blf.size(font_id, 12, 72)
            blf.position(font_id, 5, 5, 0)
            blf.draw(font_id, 'fps: %0.2f' % self.fps)
        
        bgl.glColor4f(1.0, 1.0, 1.0, 0.5)
        blf.size(font_id, 12, 72)
        lh = int(blf.dimensions(font_id, "XMPQpqjI")[1] * 1.5)
        w = max(int(blf.dimensions(font_id, rft().name())[0]) for rft in RFTool)
        h = lh * len(RFTool)
        l,t = 10,self.actions.size[1] - 10
        
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glColor4f(0.0, 0.0, 0.0, 0.25)
        bgl.glBegin(bgl.GL_QUADS)
        bgl.glVertex2f(l+w+5,t+5)
        bgl.glVertex2f(l-5,t+5)
        bgl.glVertex2f(l-5,t-h-5)
        bgl.glVertex2f(l+w+5,t-h-5)
        bgl.glEnd()
        
        bgl.glColor4f(0.0, 0.0, 0.0, 0.75)
        bgl.glLineWidth(1.0)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        bgl.glVertex2f(l+w+5,t+5)
        bgl.glVertex2f(l-5,t+5)
        bgl.glVertex2f(l-5,t-h-5)
        bgl.glVertex2f(l+w+5,t-h-5)
        bgl.glVertex2f(l+w+5,t+5)
        bgl.glEnd()
        
        for i,rft in enumerate(RFTool):
            if type(self.tool) is rft:
                bgl.glColor4f(1.0, 1.0, 0.0, 1.0)
            else:
                bgl.glColor4f(1.0, 1.0, 1.0, 0.5)
            th = int(blf.dimensions(font_id, rft().name())[1])
            y = t - (i+1) * lh + int((lh - th) / 2.0)
            blf.position(font_id, l, y, 0)
            blf.draw(font_id, rft().name())
        
    
    def draw_postview(self):
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_BLEND)
        
        self.draw_yz_mirror()
        
        self.rftarget_draw.draw()
        self.tool.draw_postview()
        self.rfwidget.draw_postview()
    
    def draw_yz_mirror(self):
        bgl.glLineWidth(3.0)
        bgl.glDepthMask(bgl.GL_FALSE)
        
        bgl.glColor4f(1, 0.5, 0.5, 0.25)
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glBegin(bgl.GL_LINES)
        for p0,p1 in self.zy_intersections:
            bgl.glVertex3f(*p0)
            bgl.glVertex3f(*p1)
        bgl.glEnd()
        
        bgl.glColor4f(1, 0.5, 0.5, 0.02)
        bgl.glDepthFunc(bgl.GL_GREATER)
        bgl.glBegin(bgl.GL_LINES)
        for p0,p1 in self.zy_intersections:
            bgl.glVertex3f(*p0)
            bgl.glVertex3f(*p1)
        bgl.glEnd()
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_TRUE)
