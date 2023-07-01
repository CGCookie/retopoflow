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
import random

import bpy
from bpy.types import Operator

from ..common.blender import perform_redraw_all, get_view3d_area
from ..common.debug import debugger, tprint
from ..common.profiler import profiler


class CookieCutter_Modal:
    def modal(self, context, event):
        self.context = context
        self.event = event

        if self._cc_stage == 'quit': return {'FINISHED'}

        # if we're not yet in the main loop, create a NOP event so that we can
        # work our way through the initialization stuff as quickly as possible!
        if self._cc_stage != 'main loop': self._cc_fsm_force_event()
        else: self._cc_fsm_stop_force_event()

        # get the method corresponding to the current stage
        fn_modal = {
            'prestart':          self.modal_prestart,
            'start when ready':  self.modal_start_when_ready,
            'init CC internals': self.modal_init_cc_internals,
            'init CC start':     self.modal_init_cc_start,
            'init CC UI':        self.modal_init_cc_ui,
            'main loop':         self.modal_mainloop,
        }.get(self._cc_stage, None)
        assert fn_modal, f"Unhandled CC stage: '{self._cc_stage}'"

        ret = fn_modal()
        # if ret == {'PASS_THROUGH'}:
        #     print(f'passing through {random.random()}')
        return ret

    def modal_prestart(self):
        with self.try_exception('prestarting'):
            self.prestart()
            self._cc_stage = 'start when ready'
            return {'RUNNING_MODAL'}
        self.cc_break()
        return {'CANCELLED'}

    def modal_start_when_ready(self):
        with self.try_exception('waiting for start readiness'):
            if self.is_ready_to_start():
                self._cc_stage = 'init CC internals'
            return {'RUNNING_MODAL'}
        self.cc_break()
        return {'CANCELLED'}

    def modal_init_cc_internals(self):
        with self.try_exception('initialize internals (Exception Callbacks, FSM, UI, Actions)'):
            self._nav        = False
            self._nav_time   = 0
            self._done       = False
            self._start_time = time.time()
            self._tmp_time   = self._start_time
            self._cc_exception_init()
            self._cc_fsm_init()
            self._cc_ui_init()
            self._cc_actions_init()
            self._cc_stage = 'init CC start'
            return {'RUNNING_MODAL'}
        self.cc_break()
        return {'CANCELLED'}

    def modal_init_cc_start(self):
        with self.try_exception('initialize start'):
            self.start()
            self._cc_stage = 'init CC UI'
            return {'RUNNING_MODAL'}
        self.cc_break()
        return {'CANCELLED'}

    def modal_init_cc_ui(self):
        with self.try_exception('initialize ui'):
            self._cc_ui_start()
            self._cc_stage = 'main loop'
            return {'RUNNING_MODAL'}
        self.cc_break()
        return {'CANCELLED'}

    def modal_mainloop(self):
        self.drawcallbacks.reset_pre()

        if time.time() - self._tmp_time >= 1:
            self._tmp_time = time.time()
            # print('--- %d ---' % int(self._tmp_time - self._start_time))
            profiler.printfile()

        if self._done:
            self.modal_maindone()
            self._cc_ui_end()
            self._cc_actions_end()
            self._cc_exception_done()
            return {'FINISHED'} if self._done=='finish' else {'CANCELLED'}

        ret = None

        if self._nav:
            self._nav = False
            self._nav_time = time.time()
        self._cc_actions_update()

        if self._cc_ui_update():
            # UI handled the action
            ret = {'RUNNING_MODAL'}
        elif self._cc_actions.using('blender window action'):
            # allow window actions to pass through to Blender
            ret = {'PASS_THROUGH'}
        elif self._cc_actions.is_navigating or (self._cc_actions.timer and self._nav):
            self._nav = True
            return {'PASS_THROUGH'}

        with self.try_exception('call update'):
            self.update()
            if self.should_pass_through(self.context, self.event):
                ret = {'PASS_THROUGH'}

        if not ret:
            self._cc_fsm_update()
            ret = {'RUNNING_MODAL'}

        perform_redraw_all(only_area=get_view3d_area(self.context))
        return ret

    def modal_maindone(self):
        if self._done == 'bail':
            return

        try:
            fn_end = self.end_commit if self._done == 'commit' else self.end_cancel
            fn_end()
            self.end()
        except Exception as e:
            self._handle_exception(e, 'call end() with %s' % self._done)


