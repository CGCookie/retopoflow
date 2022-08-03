'''
Copyright (C) 2022 CG Cookie
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
from ..addon_common.common.drawing import Cursors
from ..addon_common.common.fsm import FSM
from ..addon_common.common.drawing import DrawCallbacks
from ..addon_common.common.functools import find_fns

def rfwidget_callback_decorator(event, fn):
    if not hasattr(fn, '_rfwidget_callback'):
        fn._rfwidget_callback = []
    fn._rfwidget_callback += [event]
    return fn


class RFWidget:
    '''
    Assumes that direct subclass will have singleton instance (shared FSM among all instances of that subclass and any subclasses)
    '''
    registry = []

    @classmethod
    def __init_subclass__(cls, *args, **kwargs):
        # print('rfwidget subclass', cls, super(cls))
        if not hasattr(cls, '_rfwidget_index'):
            # add cls to registry (might get updated later) and add FSM,Draw
            cls._rfwidget_index = len(RFWidget.registry)
            RFWidget.registry.append(cls)
        else:
            # update registry, but do not add new FSM
            RFWidget.registry[cls._rfwidget_index] = cls
        super().__init_subclass__(*args, **kwargs)


    #####################################################
    # function decorators for different events

    @staticmethod
    def on_init(fn): return rfwidget_callback_decorator('init', fn)
    @staticmethod
    def on_reset(fn): return rfwidget_callback_decorator('reset', fn)
    @staticmethod
    def on_timer(fn): return rfwidget_callback_decorator('timer', fn)
    @staticmethod
    def on_target_change(fn): return rfwidget_callback_decorator('target change', fn)
    @staticmethod
    def on_view_change(fn): return rfwidget_callback_decorator('view change', fn)
    @staticmethod
    def on_action(action_name):
        def wrapper(fn):
            nonlocal action_name
            fn._rfwidget_action_name = action_name
            return rfwidget_callback_decorator('action', fn)
        return wrapper
    @staticmethod
    def on_actioning(action_name):
        def wrapper(fn):
            nonlocal action_name
            fn._rfwidget_action_name = action_name
            return rfwidget_callback_decorator('actioning', fn)
        return wrapper

    def __init__(self, rftool, *, start='main', reset_state=None, **kwargs):
        self.rftool = rftool
        self.rfcontext = rftool.rfcontext
        self.actions = rftool.rfcontext.actions
        self.redraw_on_mouse = False
        self._gather_callbacks()
        self._fsm = FSM(self, start=start, reset_state=reset_state)
        self._draw = DrawCallbacks(self)
        self._callback_widget('init', **kwargs)
        # self._init_action_callback()
        self._reset()

    def _callback_widget(self, event, *args, **kwargs):
        if event != 'timer':
            #print('callback', self, event, self._widget_callbacks.get(event, []))
            pass
        if event not in self._widget_callbacks: return
        for fn in self._widget_callbacks[event]:
            fn(self, *args, **kwargs)

    def _callback_tool(self, event, action_name, *args, **kwargs):
        if event != 'timer':
            #print('callback', self, event, self._tool_callbacks.get(event, []))
            pass
        if event not in self._tool_callbacks: return
        for fn in self._tool_callbacks[event]:
            if fn._rfwidget_action_name != action_name: continue
            fn(self.rftool, *args, **kwargs)

    def _gather_callbacks(self):
        widget_fns = find_fns(self, '_rfwidget_callback')
        self._widget_callbacks = {
            mode: [fn for (modes, fn) in widget_fns if mode in modes]
            for mode in [
                'init',          # called when RF starts up
                'reset',         # called when RF switches into tool or undo/redo
                'timer',         # called every timer interval
                'target change', # called whenever rftarget has changed (selection or edited)
                'view change',   # called whenever view has changed
            ]
        }
        rftool_fns = find_fns(self.rftool, '_rfwidget_callback')
        self._tool_callbacks = {
            mode: [fn for (modes, fn) in rftool_fns if mode in modes]
            for mode in [
                'action',        # called when user performs widget action, per instance!
                'actioning',     # called when user is performing widget action, per instance!
            ]
        }

    def callback_actions(self, action_name, *args, **kwargs):
        self._callback_tool('action', action_name, *args, **kwargs)

    def callback_actioning(self, action_name, *args, **kwargs):
        self._callback_tool('actioning', action_name, *args, **kwargs)

    def _reset(self):
        self._fsm.force_reset()
        self._callback_widget('reset')
        self._update_all()

    def _fsm_update(self):
        return self._fsm.update()

    def _update_all(self):
        self._callback_widget('timer')
        self._callback_widget('target change')
        self._callback_widget('view change')

    @staticmethod
    def dirty_when_done(fn):
        def wrapper(*args, **kwargs):
            ret = fn(*args, **kwargs)
            RFWidget.rfcontext.dirty()
            return ret
        return wrapper

    def set_cursor(self):
        Cursors.set(self.rfw_cursor)

    def inactive_passthrough(self): pass

    def _draw_pre3d(self):  self._draw.pre3d()
    def _draw_post3d(self): self._draw.post3d()
    def _draw_post2d(self): self._draw.post2d()

