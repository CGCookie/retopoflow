'''
Copyright (C) 2018 CG Cookie

https://github.com/CGCookie/retopoflow

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

import sys
import math
import os
import re
import time
import inspect

import bpy
import bgl
from mathutils import Matrix, Vector
from ..common.maths import BBox
from bpy.types import Operator, SpaceView3D, bpy_struct
from bpy.app.handlers import persistent, load_post

from ..lib import common_utilities
from ..lib.common_utilities import print_exception, print_exception2, showErrorMessage
from ..lib.classes.logging.logger import Logger
from ..lib.common_utilities import dprint
from ..lib.classes.profiler.profiler import profiler

from ..common.ui import set_cursor

from ..common.decorators import stats_report, stats_wrapper, blender_version_wrapper
from ..common.ui import UI_WindowManager
from ..common.useractions import Actions


from .cookiecutter_fsm import CookieCutter_FSM
from .cookiecutter_ui import CookieCutter_UI
from .cookiecutter_utils import CookieCutter_Utils


class CookieCutter(Operator, CookieCutter_UI, CookieCutter_FSM, CookieCutter_Utils):
    '''
    CookieCutter is used to create advanced operators very quickly!
    
    To use:
    
    - specify CookieCutter as a subclass
    - provide appropriate values for Blender class attributes: bl_idname, bl_label, etc.
    - provide appropriate dictionary that maps user action labels to keyboard and mouse actions
    - override the start function
    - register finite state machine state callbacks with the CookieCutter.FSM_State(state) function decorator
        - state can be any string that is a state in your FSM
        - Must provide at least a 'main' state
        - return values of each FSM_State decorated function tell FSM which state to switch into
            - None, '', or no return: stay in same state
    - register drawing callbacks with the CookieCutter.Draw(mode) function decorator
        - mode: 'pre3d', 'post3d', 'post2d'
    
    '''
    ############################################################################
    # override the following values and functions
    
    bl_idname = "view3d.cookiecutter_unnamed"
    bl_label = "CookieCutter Unnamed"
    
    default_keymap = {}
    def start(self): pass
    
    ############################################################################
    
    @classmethod
    def poll(cls, context):
        return True
    
    def invoke(self, context, event):
        self._nav = False
        self._done = False
        self.fsm_init()
        self.ui_init(context)
        self.actions_init(context)
        
        try:
            self.start()
        except Exception as e:
            print('Caught exception while trying to start')
            raise e
        
        self.ui_start()
        
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    
    def done(self, cancel=False):
        self._done = 'finish' if not cancel else 'cancel'
    
    def modal(self, context, event):
        if self._done:
            self.actions_end(context)
            self.ui_end()
            return {'FINISHED'} if self._done=='finish' else {'CANCELLED'}
        
        self.actions_update(context, event)
        
        if self.ui_update(context, event): return {'RUNNING_MODAL'}
        
        # allow window actions to pass through to Blender
        if self.actions.using('window actions'): return {'PASS_THROUGH'}
        
        # allow navigation actions to pass through to Blender
        if self.actions.navigating() or (self.actions.timer and self._nav):
            # let Blender handle navigation
            self.actions.unuse('navigate')  # pass-through commands do not receive a release event
            self._nav = True
            if not self.actions.trackpad: set_cursor('HAND')
            return {'PASS_THROUGH'}
        if self._nav:
            self._nav = False
            self._nav_time = time.time()
        
        self.fsm_update()
        return {'RUNNING_MODAL'}

    def actions_init(self, context):
        self.actions = Actions(context, self.default_keymap)
        self._timer = context.window_manager.event_timer_add(1.0 / 120, context.window)
    def actions_update(self, context, event):
        self.actions.update(context, event, self._timer, print_actions=False)
    def actions_end(self, context):
        context.window_manager.event_timer_remove(self._timer)
        del self._timer



