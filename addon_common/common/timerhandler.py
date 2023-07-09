'''
Copyright (C) 2023 CG Cookie
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

import bpy

from bpy.types import (
    Context,
    Window,
    WindowManager,
)

import inspect
import time
from functools import wraps

class TimerHandler:
    def __init__(self, hz:float, *, context:Context=None, wm:WindowManager=None, win:Window=None, enabled=True):
        context = context or bpy.context

        self._wm    = wm  or context.window_manager
        self._win   = win or context.window
        self._hz    = max(0.1, hz)
        self._timer = None

        self.enable(enabled)

    def __del__(self):
        self.done()

    def start(self):
        if self._timer: return
        self._timer = self._wm.event_timer_add(1.0 / self._hz, window=self._win)

    def stop(self):
        if not self._timer: return
        self._wm.event_timer_remove(self._timer)
        self._timer = None

    def done(self):
        self.stop()

    def enable(self, v):
        if v: self.start()
        else: self.stop()


class StopwatchHandler:
    def __init__(self, seconds, fn):
        self.sec = seconds
        self.fn  = lambda: fn()

    @property
    def is_going(self):
        return bpy.app.timers.is_registered(self.fn)

    def start(self):
        bpy.app.timers.register(self.fn, first_interval=self.sec)

    def stop(self):
        if self.is_going:
            bpy.app.timers.unregister(self.fn)

    def reset(self):
        self.stop()
        self.start()


class CallGovernor:
    # NOTE: bpy.app.timers.is_registered(self._call_now) does _NOT_ work!
    #       but, setting self.fn_call_now = self._call_now and then calling
    #       bpy.app.timers.is_registered(self.fn_call_now) does!

    @staticmethod
    def limit(*, time_limit=None, pause_after_call=None):
        def wrap_fn(fn):
            cg = CallGovernor(fn, time_limit=time_limit, pause_after_call=pause_after_call)
            @wraps(fn)
            def wrapper(*args, **kwargs):
                cg(*args, **kwargs)
            wrapper.unpause = cg.unpause
            return wrapper
        return wrap_fn

    def __init__(self, fn, *, time_limit=None, pause_after_call=None):
        assert time_limit is not None or pause_after_call is not None, 'Addon Common: Must specify either time_limit or pause_after_call'
        self.time_limit = time_limit
        self.pause_after_call = pause_after_call
        self.fn = fn
        self._paused = False
        self._call_when_paused = False
        self._next_call = time.time()
        self._fn_call_now = self._call_now  # THIS IS NEEDED!!!  see note above

    def unpause(self, *args):
        if not self._paused: return
        self._paused = False
        if self._call_when_paused:
            self._call_now()

    @property
    def _calling_later(self):
        return bpy.app.timers.is_registered(self._fn_call_now)

    def _call_now(self):
        if self._calling_later:
            bpy.app.timers.unregister(self._fn_call_now)
        if self.time_limit is not None:
            self._next_call = time.time() + self.time_limit
        if self.pause_after_call:
            self._paused = True
            self._call_when_paused = False
        self.fn(*self._args)

    def __call__(self, *args, now=False):
        self._args = args
        if self.time_limit is not None:
            time_to_next_call = self._next_call - time.time()
            if now or time_to_next_call <= 0:
                self._call_now()
            elif not self._calling_later:
                bpy.app.timers.register(self._fn_call_now, first_interval=time_to_next_call)
        if self.pause_after_call:
            if now or not self._paused:
                self._call_now()
            elif not self._calling_later:
                self._call_when_paused = True
