'''
Copyright (C) 2020 CG Cookie
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

from functools import wraps

from ..addon_common.common.fsm import FSM
from ..addon_common.common.drawing import DrawCallbacks
from ..addon_common.common.boundvar import (
    BoundVar,
    BoundBool,
    BoundInt, BoundFloat,
    BoundString, BoundStringToBool,
)
from ..config.options import options, themes, visualization


rftools = {}

class RFTool:
    '''
    Assumes that direct subclass will have singleton instance (shared FSM among all instances of that subclass and any subclasses)
    '''
    registry = []

    def __init_subclass__(cls, *args, **kwargs):
        global rftools

        rftools[cls.__name__] = cls
        if not hasattr(cls, '_rftool_index'):
            # add cls to registry (might get updated later) and add FSM
            cls._rftool_index = len(RFTool.registry)
            RFTool.registry.append(cls)
            cls._fsm = FSM()
            cls.FSM_State = cls._fsm.wrapper
            cls.FSM_OnlyInState = cls._fsm.onlyinstate_wrapper
            cls._draw = DrawCallbacks()
            cls.Draw = cls._draw.wrapper
            cls._callbacks = {
                'init':          [],    # called when RF starts up
                'ui setup':      [],    # called when RF is setting up UI
                'reset':         [],    # called when RF switches into tool or undo/redo
                'timer':         [],    # called every timer interval
                'target change': [],    # called whenever rftarget has changed (selection or edited)
                'view change':   [],    # called whenever view has changed
                'mouse move':    [],    # called whenever mouse has moved
            }
        else:
            # update registry, but do not add new FSM
            RFTool.registry[cls._rftool_index] = cls
        super().__init_subclass__(*args, **kwargs)

    #####################################################
    # function decorators for different events

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
    def on_ui_setup(cls, fn):
        return cls.callback_decorator('ui setup')(fn)

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
    def on_mouse_move(cls, fn):
        return cls.callback_decorator('mouse move')(fn)

    def _callback(self, event, *args, **kwargs):
        ret = []
        for fn in self._callbacks.get(event, []):
            ret.append(fn(self, *args, **kwargs))
        return ret

    def call_with_self_in_context(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


    def __init__(self, rfcontext):
        RFTool.rfcontext = rfcontext
        RFTool.drawing = rfcontext.drawing
        RFTool.actions = rfcontext.actions
        RFTool.document = rfcontext.document
        self.rfwidget = None
        self._last_mouse = None
        self._fsm.init(self, start='main')
        self._draw.init(self)
        self._callback('init')
        self._reset()

    def _reset(self):
        self._fsm.force_set_state('main')
        self._callback('reset')
        self._update_all()

    def _update_all(self):
        self._callback('timer')
        self._callback('target change')
        self._callback('view change')

    def _fsm_update(self):
        if self.actions.mouse != self._last_mouse:
            self._last_mouse = self.actions.mouse
            self._callback('mouse move')
        return self._fsm.update()

    @staticmethod
    def dirty_when_done(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ret = fn(*args, **kwargs)
            RFTool.rfcontext.dirty()
            return ret
        return wrapper

    def dirty(self):
        RFTool.rfcontext.dirty()

    def _draw_pre3d(self):  self._draw.pre3d()
    def _draw_post3d(self): self._draw.post3d()
    def _draw_post2d(self): self._draw.post2d()

