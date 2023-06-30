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

import bpy

from ..common.debug import debugger
from ..common.fsm import FSM
from ..common.timerhandler import TimerHandler

class CookieCutter_FSM:
    def _cc_fsm_init(self):
        self.fsm = FSM(self, start='main')
        self.fsm.add_exception_callback(lambda e: self._handle_exception(e, 'handle exception caught by FSM'))
        # def callback(e): self._handle_exception(e, 'handle exception caught by FSM')
        # self.fsm.add_exception_callback(callback)

    def _cc_fsm_update(self):
        self.fsm.update()

    def _cc_fsm_force_event(self):
        # add some NOP event to event queue to force modal operator to be called again right away

        # # warp cursor to same spot
        # # DOES NOT WORK: (event.mouse_x, event.mouse_y) might be incorrect!!!
        # self.context.window.cursor_warp(self.event.mouse_x, self.event.mouse_y)

        # # simulate an event
        # # DOES NOT WORK: only works with `--enable-event-simulate`, but then Blender cannot accept any input!!!
        # self.context.window.event_simulate(type='NONE', value='NOTHING')

        # # register a short-lived timer (only returns `None`)
        # # DOES NOT WORK: these timers do NOT cause modal operator to be called for some reason :(
        # bpy.app.timers.register(lambda:None, first_interval=0.01)

        # create a short-lived WindowManager timer
        # self.actions might not yet be created!
        if not hasattr(self, '_cc_force_event_handler'):
            self._cc_force_event_handler = TimerHandler(120, context=self.context, enabled=False)
        self._cc_force_event_handler.start()

    def _cc_fsm_stop_force_event(self):
        if hasattr(self, '_cc_force_event_handler'):
            self._cc_force_event_handler.stop()
