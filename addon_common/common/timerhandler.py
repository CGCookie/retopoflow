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

