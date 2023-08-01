'''
Copyright (C) 2023 CG Cookie
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

from ..addon_common.common.blender import BlenderIcon, tag_redraw_all
from ..addon_common.common.fsm import FSM
from ..addon_common.common.functools import find_fns
from ..addon_common.common.drawing import DrawCallbacks, Cursors
from ..addon_common.common.boundvar import (
    BoundVar,
    BoundBool,
    BoundInt, BoundFloat,
    BoundString, BoundStringToBool,
)
from ..config.options import options, themes, visualization


rftools = {}

def rftool_callback_decorator(event, fn):
    if not hasattr(fn, '_rftool_callback'):
        fn._rftool_callback = []
    fn._rftool_callback += [event]
    return fn



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
            if False: print(f'RFTool: adding to registry at index {len(RFTool.registry)}: {cls} {cls.__name__} ')
            cls._rftool_index = len(RFTool.registry)
            RFTool.registry.append(cls)
            if not hasattr(cls, 'quick_shortcut'): cls.quick_shortcut = None
            if not hasattr(cls, 'ui_config'): cls.ui_config = None
        else:
            # update registry, but do not add new FSM
            if False: print(f'RFTool: updating registry at index {cls._rftool_index}: {cls} {cls.__name__}')
            RFTool.registry[cls._rftool_index] = cls
            pass
        super().__init_subclass__(*args, **kwargs)


    #####################################################
    # function decorators for different events

    _events = {
        'init',                 # called when RF starts up
        'quickselect start',    # called when quick select is used and tool should be started
        'quickswitch start',    # called when quick switch to tool
        'ui setup',             # called when RF is setting up UI
        'reset',                # called when RF switches into tool or undo/redo
        'timer',                # called every timer interval
        'target change',        # called whenever rftarget has changed (selection or edited)
        'view change',          # called whenever view has changed
        'mouse move',           # called whenever mouse has moved
        'mouse stop',           # called whenever mouse has stopped moving
        'new frame',            # called each frame

        # the following are filters, not events, so the decorated fns are immediately wrapped
        'once per frame',       # only called once per frame
        'not while navigating', # delay calling until after navigating
    }

    @staticmethod
    def on_init(fn): return rftool_callback_decorator('init', fn)
    @staticmethod
    def on_quickselect_start(fn): return rftool_callback_decorator('quickselect start', fn)
    @staticmethod
    def on_quickswitch_start(fn): return rftool_callback_decorator('quickswitch start', fn)
    @staticmethod
    def on_ui_setup(fn): return rftool_callback_decorator('ui setup', fn)
    @staticmethod
    def on_reset(fn): return rftool_callback_decorator('reset', fn)
    @staticmethod
    def on_timer(fn): return rftool_callback_decorator('timer', fn)
    @staticmethod
    def on_target_change(fn): return rftool_callback_decorator('target change', fn)
    @staticmethod
    def on_view_change(fn): return rftool_callback_decorator('view change', fn)
    @staticmethod
    def on_mouse_move(fn): return rftool_callback_decorator('mouse move', fn)
    @staticmethod
    def on_mouse_stop(fn): return rftool_callback_decorator('mouse stop', fn)
    @staticmethod
    def on_new_frame(fn): return rftool_callback_decorator('new frame', fn)
    @staticmethod
    def on_events(*events):
        assert not (unknown := set(events) - RFTool._events), f'Unhandled on_event {unknown}'
        def wrapper(fn):
            for event in events:
                rftool_callback_decorator(event, fn)
            return fn
        return wrapper

    @staticmethod
    def once_per_frame(fn):
        name, count = fn.__name__, None
        @wraps(fn)
        def wrapped(self, *args, **kwargs):
            nonlocal name, count
            if count == RFTool._draw_count:
                if hasattr(self, '_callback_next_frame'):
                    self._callback_next_frame.setdefault(name, lambda: fn(self, *args, **kwargs))
                    tag_redraw_all('once per frame')
            else:
                count = RFTool._draw_count
                fn(self, *args, **kwargs)
        return wrapped

    @staticmethod
    def not_while_navigating(fn):
        name = fn.__name__
        @wraps(fn)
        def wrapped(self, *args, **kwargs):
            nonlocal name
            if RFTool.actions.is_navigating:
                if hasattr(self, '_callback_after_navigating'):
                    self._callback_after_navigating.setdefault(name, lambda: fn(self, *args, **kwargs))
            else:
                fn(self, *args, **kwargs)
        return wrapped

    def _gather_callbacks(self):
        rftool_fns = find_fns(self, '_rftool_callback', full_search=True)
        self._callbacks = {
            mode: [fn for (modes, fn) in rftool_fns if mode in modes]
            for mode in self._events
        }


    def _callback(self, event, *args, **kwargs):
        ret = []
        for fn in self._callbacks.get(event, []):
            ret.append(fn(self, *args, **kwargs))
        return ret

    def call_with_self_in_context(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


    def __init__(self, rfcontext, start='main', reset_state=None):
        RFTool.rfcontext = rfcontext
        RFTool.drawing = rfcontext.drawing
        RFTool.actions = rfcontext.actions
        RFTool.document = rfcontext.document
        self.rfwidges = {}
        self.rfwidget = None
        self._fsm = FSM(self, start=start, reset_state=reset_state)
        self._draw = DrawCallbacks(self)
        self._gather_callbacks()
        self._callback('init')
        self._reset()

    def _reset(self):
        self._callback_after_navigating = {}
        self._callback_next_frame = {}
        RFTool._draw_count = -1
        self._fsm.force_reset()
        self._callback('reset')
        self._update_all()

    def _update_all(self):
        self._callback('timer')
        self._callback('target change')
        self._callback('view change')

    def _fsm_update(self):
        if   self.actions.mousemove:      self._callback('mouse move')
        elif self.actions.mousemove_prev: self._callback('mouse stop')
        return self._fsm.update()

    def _fsm_in_main(self):
        return self._fsm.state in {'main'}

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

    def _new_frame(self):
        RFTool._draw_count = self.rfcontext._draw_count
        self._callback('new frame')

        fns = list(self._callback_next_frame.values())
        self._callback_next_frame.clear()
        for fn in fns: fn()

    def _done_navigating(self):
        fns = list(self._callback_after_navigating.values())
        self._callback_after_navigating.clear()
        for fn in fns: fn()

    def _draw_pre3d(self):   self._draw.pre3d()
    def _draw_post3d(self):  self._draw.post3d()
    def _draw_post2d(self):  self._draw.post2d()

    @classmethod
    @property
    def icon_id(cls):
        return BlenderIcon.icon_id(cls.icon)

    def clear_widget(self):
        self.set_widget(None)
    def set_widget(self, widget):
        self.rfwidget = self.rfwidgets[widget] if type(widget) is str else widget
        if self.rfwidget: self.rfwidget.set_cursor()
        else: Cursors.set('DEFAULT')

    def handle_inactive_passthrough(self):
        for rfwidget in self.rfwidgets.values():
            if self.rfwidget == rfwidget: continue
            if rfwidget.inactive_passthrough():
                self.set_widget(rfwidget)
                return True
        return False
