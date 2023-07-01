'''
Copyright (C) 2023 CG Cookie

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
import copy
import math
import time

import bpy
from bpy.types import Operator

from ..common.blender import perform_redraw_all
from ..common.debug import debugger, tprint
from ..common.profiler import profiler

from .cookiecutter_actions    import CookieCutter_Actions
from .cookiecutter_blender    import CookieCutter_Blender
from .cookiecutter_debug      import CookieCutter_Debug
from .cookiecutter_exceptions import CookieCutter_Exceptions
from .cookiecutter_fsm        import CookieCutter_FSM
from .cookiecutter_modal      import CookieCutter_Modal
from .cookiecutter_ui         import CookieCutter_UI


is_broken = False

class CookieCutter(
    Operator,
    CookieCutter_UI,
    CookieCutter_Actions,
    CookieCutter_FSM,
    CookieCutter_Blender,
    CookieCutter_Exceptions,
    CookieCutter_Debug,
    CookieCutter_Modal,
):
    '''
    CookieCutter is used to create advanced operators very quickly!

    To use:

    - specify CookieCutter as a subclass
    - provide appropriate values for Blender class attributes: bl_idname, bl_label, etc.
    - provide appropriate dictionary that maps user action labels to keyboard and mouse actions
    - override the start function
    - register finite state machine state callbacks with the FSM.on_state(state) function decorator
        - state can be any string that is a state in your FSM
        - Must provide at least a 'main' state
        - return values of each on_state decorated function tell FSM which state to switch into
            - None, '', or no return: stay in same state
    - register drawing callbacks with the CookieCutter.Draw(mode) function decorator
        - mode: 'pre3d', 'post3d', 'post2d'

    '''

    # registry = []
    # def __init_subclass__(cls, *args, **kwargs):
    #     super().__init_subclass__(*args, **kwargs)
    #     if not hasattr(cls, '_cookiecutter_index'):
    #         # add cls to registry (might get updated later) and add FSM,Draw
    #         cls._rfwidget_index = len(CookieCutter.registry)
    #         CookieCutter.registry.append(cls)
    #         cls.fsm = FSM()
    #         cls.drawcallbacks = DrawCallbacks()
    #     else:
    #         # update registry, but do not add new FSM
    #         CookieCutter.registry[cls._cookiecutter_index] = cls


    ############################################################################
    # override the following values and functions

    bl_idname = "view3d.cookiecutter_unnamed"
    bl_label = "CookieCutter Unnamed"

    @classmethod
    def can_start(cls, context): return True

    def prestart(self): pass
    def is_ready_to_start(self): return True
    def start(self): pass
    def update(self): pass
    def end_commit(self): pass
    def end_cancel(self): pass
    def end(self): pass
    def should_pass_through(self, context, event): return False

    ############################################################################

    @staticmethod
    def cc_break():
        global is_broken
        is_broken = True

    @classmethod
    def poll(cls, context):
        global is_broken
        if is_broken: return False
        with cls.try_exception('call can_start()'):
            return cls.can_start(context)
        print('BREAKING COOKIECUTTER')
        print(f'{cls.bl_idname}')
        cls.cc_break()
        return False

    def invoke(self, context, event):
        self._cc_stage = 'prestart'
        self.context = context
        self.event = event

        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def done(self, *, cancel=False, emergency_bail=False):
        if emergency_bail:
            self._done = 'bail'
        else:
            self._done = 'commit' if not cancel else 'cancel'




