'''
Copyright (C) 2019 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

from ..addon_common.common.debug import debugger
from ..addon_common.common.fsm import FSM
from ..addon_common.common.drawing import DrawCallbacks
from ..addon_common.common.utils import find_fns

class RFWidget:
    '''
    Assumes that direct subclass will have singleton instance (shared FSM among all instances of that subclass and any subclasses)
    '''
    registry = []

    def __init_subclass__(cls, *args, **kwargs):
        if not hasattr(cls, '_rfwidget_index'):
            # add cls to registry (might get updated later) and add FSM
            cls._rfwidget_index = len(RFWidget.registry)
            RFWidget.registry.append(cls)
            cls._fsm = FSM()
            cls.FSM_State = cls._fsm.wrapper
            cls.FSM_OnlyInState = cls._fsm.onlyinstate_wrapper
            cls._draw = DrawCallbacks()
            cls.Draw = cls._draw.wrapper
            cls._callbacks = {
                'init':          [],    # called when RF starts up
                'reset':         [],    # called when RF switches into tool or undo/redo
                'timer':         [],    # called every timer interval
                'target change': [],    # called whenever rftarget has changed (selection or edited)
                'view change':   [],    # called whenever view has changed
                'action':        [],    # called when user performs widget action, per instance!
            }
        else:
            # update registry, but do not add new FSM
            RFWidget.registry[cls._rfwidget_index] = cls
        super().__init_subclass__(*args, **kwargs)

    @classmethod
    def callback_decorator(cls, event):
        def wrapper(fn):
            if event not in cls._callbacks: cls._callbacks[event] = []
            cls._callbacks[event] += [fn]
            return fn
        return wrapper
    @classmethod
    def on_init(cls, fn):
        return cls.callback_decorator('init')(fn)
    @classmethod
    def on_reset(cls, fn):
        return cls.callback_decorator('reset')(fn)
    @classmethod
    def on_timer(cls, fn):
        return cls.callback_decorator('timer')(fn)
    @classmethod
    def on_target_change(cls, fn):
        return cls.callback_decorator('target change')(fn)
    @classmethod
    def on_view_change(cls, fn):
        return cls.callback_decorator('view change')(fn)
    @classmethod
    def on_action(cls, fn):
        fn._widget_action = True
        return cls.callback_decorator('action')(fn)

    def _callback(self, event, *args, **kwargs):
        for fn in self._callbacks.get(event, []):
            fn(self, *args, **kwargs)


    def __init__(self, rftool, **kwargs):
        self.rftool = rftool
        self.rfcontext = rftool.rfcontext
        self.actions = rftool.rfcontext.actions
        self.redraw_on_mouse = False
        self._fsm.init(self, start='main')
        self._draw.init(self)
        self._callback('init', **kwargs)
        self._init_action_callback()
        self._reset()

    def _init_action_callback(self):
        self._action_callbacks = [fn for (_,fn) in find_fns(self.rftool, '_widget_action')]
    def register_action_callback(self, fn):
        self._action_callbacks += [fn]
    def callback_actions(self, *args, **kwargs):
        for fn in self._action_callbacks:
            fn(self.rftool, *args, **kwargs)

    def _reset(self):
        self._fsm.force_set_state('main')
        self._callback('reset')
        self._update_all()

    def _fsm_update(self):
        return self._fsm.update()

    def _update_all(self):
        self._callback('timer')
        self._callback('target change')
        self._callback('view change')

    @staticmethod
    def dirty_when_done(fn):
        def wrapper(*args, **kwargs):
            ret = fn(*args, **kwargs)
            RFWidget.rfcontext.dirty()
            return ret
        return wrapper

    def _draw_pre3d(self):  self._draw.pre3d()
    def _draw_post3d(self): self._draw.post3d()
    def _draw_post2d(self): self._draw.post2d()

