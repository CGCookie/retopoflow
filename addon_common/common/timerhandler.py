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
    Timer,
)

import time
from functools import wraps, partial
from contextlib import contextmanager
from collections.abc import Callable

class TimerHandler:
    _context : Context
    _wm : WindowManager
    _win : Window
    _hz : float
    _timer : Timer | None

    def __init__(
        self,
        hz:float,
        *,
        context:Context|None=None,
        wm:WindowManager|None=None,
        win:Window|None=None,
        enabled:bool=True,
    ):
        self._timer = None
        self._hz = hz
        self._context = context or bpy.context
        self._wm = self._context.window_manager
        self._win = self._context.window
        self.enabled = enabled

    @contextmanager
    def pause(self):
        was_enabled = self.enabled
        try:
            yield None
            if was_enabled:
                self.start()
        except Exception as _:
            pass

    @property
    def hz(self) -> float:
        return self._hz
    @hz.setter
    def hz(self, hz : float):
        with self.pause():
            self._hz = hz

    @property
    def context(self) -> Context:
        return self._context
    @context.setter
    def context(self, context : Context):
        with self.pause():
            self._context = context
            self._wm = context.window_manager
            self._win = context.window

    def __del__(self):
        self.stop()

    def start(self):
        if self._timer: return # already started
        delay = 1.0 / max(0.1, self._hz)
        self._timer = self._wm.event_timer_add(delay, window=self._win)

    def stop(self):
        if not self._timer: return # already stopped
        self._wm.event_timer_remove(self._timer)
        self._timer = None

    def done(self):
        self.stop()

    @property
    def enabled(self) -> bool:
        return self._timer is not None
    @enabled.setter
    def enabled(self, enable : bool):
        if enable:
            self.start()
        else:
            self.stop()


class StopwatchHandler:
    MIN_TIME_DELAY : float = 0.00001
    _fn : Callable[[...], None]
    fn : Callable[[], None] | None
    time_delay : float | None
    fn_delay : Callable[[], float] | None

    @staticmethod
    def delayed(
        *,
        time_delay : float | None = None,
        fn_delay : Callable[[], float] | None = None,
    ) -> Callable[[Callable[[], None]], Callable[[...], None]]:
        def wrap_fn(fn : Callable[[], None]) -> Callable[[...], None]:
            sw = StopwatchHandler(fn, time_delay=time_delay, fn_delay=fn_delay)
            @wraps(fn)
            def wrapper(*args : ..., **kwargs : dict[str, ...]):
                sw.start(*args, **kwargs)
            setattr(wrapper, 'is_going', sw.is_going)
            setattr(wrapper, 'cancel', sw.cancel)
            setattr(wrapper, 'reset', sw.reset)
            return wrapper
        return wrap_fn

    def __init__(
        self,
        fn : Callable[[...], None],
        *,
        time_delay : float | None = None,
        fn_delay : Callable[[], float] | None = None,
    ):
        assert time_delay is not None or fn_delay is not None, f'Addon Common: Must specify either time_delay or fn_delay'
        self._fn = fn
        self.fn = None
        self.time_delay = time_delay
        self.fn_delay = fn_delay

    @property
    def delay(self) -> float:
        if self.time_delay is not None:
            return max(self.time_delay, StopwatchHandler.MIN_TIME_DELAY)

        fn_delay : Callable[[], float] | None
        if (fn_delay := getattr(self, 'fn_delay', None)) is not None:
            return fn_delay()

        return StopwatchHandler.MIN_TIME_DELAY

    @property
    def is_going(self) -> bool:
        return self.fn and bpy.app.timers.is_registered(self.fn)

    def start(self, *args : ..., **kwargs : dict[str, ...]):
        if self.is_going:
            self.cancel()

        self.fn = partial(self._fn, *args, **kwargs)
        bpy.app.timers.register(self.fn, first_interval=self.delay)

    def cancel(self):
        if not self.is_going:
            return

        bpy.app.timers.unregister(self.fn)
        self.fn = None

    def reset(self, *args: ..., **kwargs: dict[..., ...]):
        self.cancel()
        self.start(*args, **kwargs)


class CallGovernor:
    # NOTE: bpy.app.timers.is_registered(self._call_now) does _NOT_ work!
    #       but, setting self.fn_call_now = self._call_now and then calling
    #       bpy.app.timers.is_registered(self.fn_call_now) does!

    @staticmethod
    def limit(**kwargs):
        def wrap_fn(fn):
            cg = CallGovernor(fn, **kwargs)
            @wraps(fn)
            def wrapper(*fn_args, **fn_kwargs):
                cg(*fn_args, **fn_kwargs)
            wrapper.unpause = cg.unpause
            wrapper.stop = cg.stop
            return wrapper
        return wrap_fn

    def __init__(self, fn, *, time_limit=None, fn_delay=None, pause_after_call=None):
        assert not all([
            time_limit is None,
            fn_delay is None,
            pause_after_call is None,
        ]), 'Addon Common: Must specify at least one option'
        self.time_limit = time_limit
        self.fn_delay = fn_delay
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
        self.stop()

        if self.time_limit is not None:
            self._next_call = time.time() + self.time_limit
        elif self.fn_delay is not None:
            self._next_call = time.time() + self.fn_delay()

        if self.pause_after_call:
            self._paused = True
            self._call_when_paused = False

        self.fn(*self._args)

    def __call__(self, *args, now=False):
        self._args = args

        if self.time_limit is not None or self.fn_delay is not None:
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

    def stop(self):
        if not self._calling_later: return
        bpy.app.timers.unregister(self._fn_call_now)
