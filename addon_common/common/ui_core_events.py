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

from inspect import signature

from .ui_event import UI_Event

from .profiler import profiler, time_it


class UI_Core_Events:
    def _init_events(self):
        # all events with their respective callbacks
        # NOTE: values of self._events are list of tuples, where:
        #       - first item is bool indicating type of callback, where True=capturing and False=bubbling
        #       - second item is the callback function, possibly wrapped with lambda
        #       - third item is the original callback function
        self._events = {
            'on_load':          [],     # called when document is set
            'on_focus':         [],     # focus is gained (:foces is added)
            'on_blur':          [],     # focus is lost (:focus is removed)
            'on_focusin':       [],     # focus is gained to self or a child
            'on_focusout':      [],     # focus is lost from self or a child
            'on_keydown':       [],     # key is pressed down
            'on_keyup':         [],     # key is released
            'on_keypress':      [],     # key is entered (down+up)
            'on_paste':         [],     # user is pasting from clipboard
            'on_mouseenter':    [],     # mouse enters self (:hover is added)
            'on_mousemove':     [],     # mouse moves over self
            'on_mousedown':     [],     # mouse button is pressed down
            'on_mouseup':       [],     # mouse button is released
            'on_mouseclick':    [],     # mouse button is clicked (down+up while remaining on self)
            'on_mousedblclick': [],     # mouse button is pressed twice in quick succession
            'on_mouseleave':    [],     # mouse leaves self (:hover is removed)
            'on_scroll':        [],     # self is being scrolled
            'on_input':         [],     # occurs immediately after value has changed
            'on_change':        [],     # occurs after blur if value has changed
            'on_toggle':        [],     # occurs when open attribute is toggled
            'on_close':         [],     # dialog is closed
            'on_visibilitychange': [],  # element became visible or hidden
        }


    def add_eventListener(self, event, callback, useCapture=False):
        ovent = event
        event = event if event.startswith('on_') else f'on_{event}'
        assert event in self._events, f'Attempting to add unhandled event handler type "{oevent}"'
        sig = signature(callback)
        old_callback = callback
        if len(sig.parameters) == 0:
            callback = lambda e: old_callback()
        self._events[event] += [(useCapture, callback, old_callback)]

    def remove_eventListener(self, event, callback):
        # returns True if callback was successfully removed
        oevent = event
        event = event if event.startswith('on_') else f'on_{event}'
        assert event in self._events, f'Attempting to remove unhandled event handler type "{ovent}"'
        l = len(self._events[event])
        self._events[event] = [(capture,cb,old_cb) for (capture,cb,old_cb) in self._events[event] if old_cb != callback]
        return l != len(self._events[event])

    def _fire_event(self, event, details):
        ph = details.event_phase
        cap, bub, df = details.capturing, details.bubbling, not details.default_prevented
        try:
            if (cap and ph == 'capturing') or (df and ph == 'at target'):
                for (cap,cb,old_cb) in self._events[event]:
                    if not cap: continue
                    cb(details)
            if (bub and ph == 'bubbling') or (df and ph == 'at target'):
                for (cap,cb,old_cb) in self._events[event]:
                    if cap: continue
                    cb(details)
        except Exception as e:
            print(f'COOKIE CUTTER >> Exception Caught while trying to callback event handlers')
            print(f'UI_Element: {self}')
            print(f'event: {event}')
            print(f'exception: {e}')
            raise e

    @profiler.function
    def dispatch_event(self, event, mouse=None, button=None, key=None, clipboardData=None, ui_event=None, stop_at=None):
        event = event if event.startswith('on_') else f'on_{event}'
        if self._document:
            if mouse is None:
                mouse = self._document.actions.mouse
            if button is None:
                button = (
                    self._document.actions.using('LEFTMOUSE'),
                    self._document.actions.using('MIDDLEMOUSE'),
                    self._document.actions.using('RIGHTMOUSE')
                )
        # else:
        #     if mouse is None or button is None:
        #         print(f'UI_Element.dispatch_event: {event} dispatched on {self}, but self.document = {self.document}  (root={self.get_root()}')

        if ui_event is None:
            ui_event = UI_Event(target=self, mouse=mouse, button=button, key=key, clipboardData=clipboardData)

        path = self.get_pathToRoot()[1:] # skipping first item, which is self
        if stop_at is not None and stop_at in path:
            path = path[:path.index(stop_at)]

        ui_event.event_phase = 'capturing'
        for cur in path[::-1]:
            cur._fire_event(event, ui_event)
            if not ui_event.capturing: return ui_event.default_prevented

        ui_event.event_phase = 'at target'
        self._fire_event(event, ui_event)

        ui_event.event_phase = 'bubbling'
        if not ui_event.bubbling: return ui_event.default_prevented
        for cur in path:
            cur._fire_event(event, ui_event)
            if not ui_event.bubbling: return ui_event.default_prevented

        return ui_event.default_prevented
