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


# https://www.w3schools.com/jsref/obj_event.asp
# https://javascript.info/bubbling-and-capturing
class UI_Event:
    phases = [
        'none',
        'capturing',
        'at target',
        'bubbling',
    ]

    def __init__(self, target=None, mouse=None, button=None, key=None, clipboardData=None):
        self._eventPhase = 'none'
        self._cancelBubble = False
        self._cancelCapture = False
        self._target = target
        self._mouse = mouse
        self._button = button
        self._key = key
        self._clipboardData = clipboardData
        self._defaultPrevented = False

    def stop_propagation(self):
        self.stop_bubbling()
        self.stop_capturing()
    def stop_bubbling(self):
        self._cancelBubble = True
    def stop_capturing(self):
        self._cancelCapture = True

    def prevent_default(self):
        self._defaultPrevented = True

    @property
    def event_phase(self): return self._eventPhase
    @event_phase.setter
    def event_phase(self, v):
        assert v in self.phases, "attempting to set event_phase to unknown value (%s)" % str(v)
        self._eventPhase = v

    @property
    def bubbling(self):
        return self._eventPhase == 'bubbling' and not self._cancelBubble
    @property
    def capturing(self):
        return self._eventPhase == 'capturing' and not self._cancelCapture
    @property
    def atTarget(self):
        return self._eventPhase == 'at target'

    @property
    def target(self): return self._target

    @property
    def mouse(self): return self._mouse

    @property
    def button(self): return self._button

    @property
    def key(self): return self._key

    @property
    def clipboardData(self): return self._clipboardData

    @property
    def default_prevented(self): return self._defaultPrevented

    @property
    def eventPhase(self): return self._eventPhase
