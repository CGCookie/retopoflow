'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

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
import random
import binascii
import importlib
from copy import deepcopy

import bgl
import blf
import bpy
import bmesh
from bmesh.types import BMVert, BMEdge, BMFace
from mathutils.bvhtree import BVHTree
from mathutils import Matrix, Vector

from .rfcontext_drawing import RFContext_Drawing
from .rfcontext_ui import RFContext_UI
from .rfcontext_spaces import RFContext_Spaces
from .rfcontext_target import RFContext_Target
from .rfcontext_sources import RFContext_Sources

from ..common.utils import get_settings
from ..common.debug import dprint, debugger
from ..common.profiler import profiler
from ..common.maths import Point, Vec, Direction, Normal, BBox
from ..common.maths import Ray, Plane, XForm
from ..common.maths import Point2D, Vec2D, Direction2D
from ..common.ui import set_cursor
from ..common.decorators import stats_wrapper, blender_version_wrapper
from ..common.useractions import Actions

from ..options import options, themes
from ..keymaps import default_rf_keymaps

from .rfmesh import RFSource, RFTarget
from .rfmesh_render import RFMeshRender

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
                    dprint('************* ERROR! *************')
                    dprint('>>>>> Could not import ' + rft)
                    dprint(e)
                pass
    return found
assert find_all_rftools(), 'Could not find RFTools'


#######################################################


class RFContext(RFContext_Drawing, RFContext_UI, RFContext_Spaces, RFContext_Target, RFContext_Sources):
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
    @blender_version_wrapper('<','2.80')
    def is_valid_source(o):
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if not any(vl and ol for vl,ol in zip(bpy.context.scene.layers, o.layers)): return False
        if o.hide: return False
        if o.select and o == bpy.context.active_object: return False
        if not o.data.polygons: return False
        return True
    
    @staticmethod
    @blender_version_wrapper('>=','2.80')
    def is_valid_source(o):
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if o.select_get() and o == bpy.context.active_object: return False
        if not o.data.polygons: return False
        return True

    @staticmethod
    @blender_version_wrapper('<','2.80')
    def is_valid_target(o):
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if not any(vl and ol for vl,ol in zip(bpy.context.scene.layers, o.layers)): return False
        if o.hide: return False
        if not o.select: return False
        if o != bpy.context.active_object: return False
        return True
    
    @staticmethod
    @blender_version_wrapper('>=','2.80')
    def is_valid_target(o):
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if not o.select_get(): return False
        if o != bpy.context.active_object: return False
        return True

    @staticmethod
    def has_valid_source():
        return any(RFContext.is_valid_source(o) for o in bpy.context.scene.objects)

    @staticmethod
    def has_valid_target():
        return RFContext.get_target() is not None

    @staticmethod
    def is_in_valid_mode():
        for area in bpy.context.screen.areas:
            if area.type != 'VIEW_3D': continue
            if area.spaces[0].local_view:
                # currently in local view
                return False
        return True

    @staticmethod
    def get_sources():
        return [o for o in bpy.context.scene.objects if RFContext.is_valid_source(o)]

    @staticmethod
    def get_target():
        o = bpy.context.active_object
        return o if RFContext.is_valid_target(o) else None

    @stats_wrapper
    @profiler.profile
    def __init__(self, rfmode, starting_tool):
        RFContext.instance = self
        self.undo = []  # undo stack of causing actions, FSM state, tool states, and rftargets
        self.redo = []  # redo stack of causing actions, FSM state, tool states, and rftargets
        self.rfmode = rfmode
        self.FSM = {'main': self.modal_main}
        self.mode = 'main'
        self._init_tools()              # set up tools and widgets used in RetopoFlow
        self._init_actions()            # set up default and user-defined actions
        self._init_usersettings()       # set up user-defined settings and key mappings
        self._init_ui()                 # set up user interface
        self._init_target()             # set up target object
        self._init_sources()            # set up source objects, must call *AFTER* target is initialized!
        self._init_rotate_about_active()    # must call *AFTER* target is initialized!
        self.fps_time = time.time()
        self.frames = 0
        self.timer = None
        self.time_to_save = None
        self.fps = 0
        self.fps_low_start = time.time()    # time when low fps started
        self.fps_low_warning = False        # are we showing a low-fps warning?
        self.exit = False
        self.tool = None
        self.tool_setting = False
        self.set_tool(starting_tool)
        
        # touching undo stack to work around weird bug
        # to reproduce:
        #     start PS, select a strip, drag a handle but then cancel, exit RF
        #     start PS again, drag (already selected) handle... but strip does not move
        # i believe the bug has something to do with caching of RFMesh, but i'm not sure
        # pushing and then canceling an undo will flush the cache enough to circumvent it
        self.undo_push('initial')
        self.undo_cancel()

    def _init_usersettings(self):
        # user-defined settings
        self.settings = get_settings()

    def _init_tools(self):
        self.rfwidget = RFWidget.new(self)  # init widgets
        RFTool.init_tools(self)             # init tools
        self.nav = False                    # not currently navigating
        self.nav_time = time.time()         # last time nav happened

    def _init_actions(self):
        self.actions = Actions(self.rfmode.context, default_rf_keymaps)

    def _process_event(self, context, event):
        self.actions.update(context, event, self.timer, print_actions=options['debug actions'])

    def _init_rotate_about_active(self):
        self._end_rotate_about_active()
        o = bpy.data.objects.new('RetopoFlow_Rotate', None)
        bpy.context.scene.objects.link(o)
        o.select = True
        bpy.context.scene.objects.active = o
        self.rot_object = o
        self.update_rot_object()

    def _end_rotate_about_active(self):
        if 'RetopoFlow_Rotate' not in bpy.data.objects: return
        # need to remove empty object for rotation
        bpy.data.objects.remove(bpy.data.objects['RetopoFlow_Rotate'], do_unlink=True)
        bpy.context.scene.objects.active = self.tar_object
        self.rot_object = None

    @profiler.profile
    def replace_opts(self, target=True, sources=False):
        if not hasattr(self, 'rftarget_draw'): return
        if target:
            target_opts = self.get_target_render_options()
            self.rftarget_draw.replace_opts(target_opts)
        if sources:
            source_opts = self.get_source_render_options()
            for rfsd in self.rfsources_draw:
               rfsd.replace_opts(source_opts)
    
    def commit(self):
        #self.rftarget.commit()
        pass

    def end(self):
        self._end_rotate_about_active()

    ###################################################
    # mouse cursor functions

    def set_tool(self, tool, forceUpdate=False, changeTool=True):
        if self.tool_setting: return
        if not forceUpdate and hasattr(self, 'tool') and self.tool == tool: return
        if changeTool or not self.tool:
            self.tool_setting = True
            self.tool = tool
            # update tool window
            self.tool_selection_min.set_option(tool.name())
            self.tool_selection_max.set_option(tool.name())
            self.tool.update_tool_options()
            self.tool_setting = False
        self.tool.start()
        self.tool.update()

    ###################################################
    # undo / redo stack operations

    def _create_state(self, action):
        return {
            'action':       action,
            'tool':         self.tool,
            'rftarget':     copy.deepcopy(self.rftarget),
            }
    def _restore_state(self, state):
        self.rftarget = state['rftarget']
        self.rftarget.rewrap()
        self.rftarget.dirty()
        self.rftarget_draw.replace_rfmesh(self.rftarget)
        self.set_tool(state['tool'], forceUpdate=True, changeTool=options['undo change tool'])

    def undo_push(self, action, repeatable=False):
        # skip pushing to undo if action is repeatable and we are repeating actions
        if repeatable and self.undo and self.undo[-1]['action'] == action: return
        self.undo.append(self._create_state(action))
        while len(self.undo) > self.undo_depth: self.undo.pop(0)     # limit stack size
        self.redo.clear()
        self.instrument_write(action)

    def undo_pop(self):
        if not self.undo: return
        self.redo.append(self._create_state('undo'))
        self._restore_state(self.undo.pop())
        self.instrument_write('undo')

    def undo_cancel(self):
        if not self.undo: return
        self._restore_state(self.undo.pop())
        self.instrument_write('cancel (undo)')

    def redo_pop(self):
        if not self.redo: return
        self.undo.append(self._create_state('redo'))
        self._restore_state(self.redo.pop())
        self.instrument_write('redo')

    def instrument_write(self, action):
        if not options['instrument']: return
        
        tb_name = options['instrument_filename']
        if tb_name not in bpy.data.texts: bpy.data.texts.new(tb_name)
        tb = bpy.data.texts[tb_name]
        
        target_json = self.rftarget.to_json()
        data = {'action': action, 'target': target_json}
        data_str = json.dumps(data, separators=[',',':'])
        
        # write data to end of textblock
        tb.write('')        # position cursor to end
        tb.write(data_str)
        tb.write('\n')

    ###################################################
    # auto save

    def check_auto_save(self):
        use_auto_save_temporary_files = context.user_preferences.filepaths.use_auto_save_temporary_files
        auto_save_time = context.user_preferences.filepaths.auto_save_time * 60
        if not use_auto_save_temporary_files: return
        if self.time_to_save is None:
            self.time_to_save = auto_save_time
        else:
            self.time_to_save -= self.actions.time_delta
        if self.time_to_save > 0: return
        self.rfmode.backup_save()
        self.time_to_save = auto_save_time

    ###################################################

    def modal(self, context, event):
        # returns set with actions for RFMode to perform
        #   {'confirm'}:    done with RFMode
        #   {'pass'}:       pass-through to Blender
        #   empty or None:  stay in modal

        self._process_event(context, event)

        self.actions.hit_pos,self.actions.hit_norm,_,_ = self.raycast_sources_mouse()

        if self.actions.using('window actions'):
            return {'pass'}

        if self.actions.using('autosave'):
            return {'pass'}
        
        if self.actions.pressed('general help'):
            self.toggle_general_help()
            return {}
        if self.actions.pressed('tool help'):
            self.toggle_tool_help()
            return {}

        use_auto_save_temporary_files = context.user_preferences.filepaths.use_auto_save_temporary_files
        auto_save_time = context.user_preferences.filepaths.auto_save_time * 60
        if use_auto_save_temporary_files and event.type == 'TIMER':
            if self.time_to_save is None: self.time_to_save = auto_save_time
            else: self.time_to_save -= self.actions.time_delta
            if self.time_to_save <= 0:
                # tempdir = bpy.app.tempdir
                filepath = options.temp_filepath('blend')
                dprint('auto saving to %s' % filepath)
                if os.path.exists(filepath): os.remove(filepath)
                bpy.ops.wm.save_as_mainfile(filepath=filepath, check_existing=False, copy=True)
                self.time_to_save = auto_save_time

        try:
            ret = self.window_manager.modal(context, event)
            if ret and 'hover' in ret:
                self.rfwidget.clear()
                if self.exit: return {'confirm'}
                return {}
        except Exception as e:
            message,h = debugger.get_exception_info_and_hash()
            print(message)
            message = '\n'.join('- %s'%l for l in message.splitlines())
            self.alert_user(message=message, level='exception', msghash=h)
            #raise e
        
        if self.window_manager.has_focus(): return {}
        
        # user pressing nav key?
        if self.actions.navigating() or (self.actions.timer and self.nav):
            # let Blender handle navigation
            self.actions.unuse('navigate')  # pass-through commands do not receive a release event
            self.nav = True
            if not self.actions.trackpad: set_cursor('HAND')
            self.rfwidget.clear()
            return {'pass'}
        if self.nav:
            self.nav = False
            self.nav_time = time.time()
            self.rfwidget.update()
        
        try:
            nmode = self.FSM[self.mode]()
            if nmode: self.mode = nmode
        except AssertionError as e:
            message,h = debugger.get_exception_info_and_hash()
            print(message)
            message = '\n'.join('- %s'%l for l in message.splitlines())
            self.alert_user(message=message, level='assert', msghash=h)
        except Exception as e:
            message,h = debugger.get_exception_info_and_hash()
            print(message)
            message = '\n'.join('- %s'%l for l in message.splitlines())
            self.alert_user(message=message, level='exception', msghash=h)
            #raise e

        if self.actions.pressed('done') or self.exit:
            # all done!
            return {'confirm'}

        if self.actions.pressed('edit mode'):
            # leave to edit mode
            return {'confirm', 'edit mode'}

        return {}


    def modal_main(self):
        # handle undo/redo
        if self.actions.pressed('undo'):
            self.undo_pop()
            if self.tool: self.tool.undone()
            return
        if self.actions.pressed('redo'):
            self.redo_pop()
            if self.tool: self.tool.undone()
            return
        
        if self.actions.pressed('F3'):
            profiler.printout()
            return
        if self.actions.pressed('F4'):
            print('Clearing profiler')
            profiler.clear()
            return

        #if self.actions.pressed('F5'):
        #    assert False, 'this is a test!'
        #    return

        # handle tool shortcut
        for action,tool in RFTool.action_tool:
            if self.actions.pressed(action):
                self.set_tool(tool())
                return

        # handle selection
        if self.actions.pressed('select all'):
            self.undo_push('select all')
            self.select_toggle()
            return

        # handle delete/dissolve
        if self.actions.pressed('delete'):
            self.option_user([
                ('Delete',  ['Vertices', 'Edges', 'Faces', 'Only Edges & Faces', 'Only Faces']),
                ('Dissolve',['Vertices', 'Edges', 'Faces', 'Loops']),
                # 'Limited Dissolve',
                # 'Edge Collapse', 'Edge Loops',
                ], self.delete_dissolve_option)
            return
        
        # update rfwidget and cursor
        if self.actions.valid_mouse():
            self.rfwidget.update()
            set_cursor(self.rfwidget.mouse_cursor())
        else:
            self.rfwidget.clear()
            set_cursor('DEFAULT')

        if self.rfwidget.modal():
            if self.tool and self.actions.valid_mouse():
                self.tool.modal()
