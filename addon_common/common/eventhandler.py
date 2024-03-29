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

import re
import time
import inspect
from copy import deepcopy

import bpy

from .debug import dprint
from .decorators import blender_version_wrapper
from .human_readable import convert_actions_to_human_readable, convert_human_readable_to_actions
from .maths import Point2D, Vec2D
from .timerhandler import TimerHandler
from . import blender_preferences as bprefs


###
###
### The classes here will _eventually_ replace those in useractions.py
###
###


'''
copied from:
- https://docs.blender.org/api/current/bpy.types.Event.html
- https://docs.blender.org/api/current/bpy.types.KeyMapItem.html

direction: { 'ANY', 'NORTH', 'NORTH_EAST', 'EAST', 'SOUTH_EAST', 'SOUTH', 'SOUTH_WEST', 'WEST', 'NORTH_WEST' }
type: {
    'NONE',

    # System
    'WINDOW_DEACTIVATE',  # window lost focus (minimized, switch away from, etc.)
    'ACTIONZONE_AREA', 'ACTIONZONE_REGION', 'ACTIONZONE_FULLSCREEN',

    # Mouse
    'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE', 'BUTTON4MOUSE', 'BUTTON5MOUSE', 'BUTTON6MOUSE', 'BUTTON7MOUSE',
    'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE',
    'MOUSEROTATE', 'MOUSESMARTZOOM', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE',
    'PEN', 'ERASER',
    'TRACKPADPAN', 'TRACKPADZOOM',

    # Keyboard
    'LEFT_CTRL', 'LEFT_ALT', 'LEFT_SHIFT', 'RIGHT_ALT', 'RIGHT_CTRL', 'RIGHT_SHIFT', 'OSKEY',
    'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z',
    'ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE',
    'SEMI_COLON', 'PERIOD', 'COMMA', 'QUOTE', 'ACCENT_GRAVE', 'MINUS', 'PLUS', 'SLASH', 'BACK_SLASH', 'EQUAL', 'LEFT_BRACKET', 'RIGHT_BRACKET',
    'GRLESS',
    'NUMPAD_2', 'NUMPAD_4', 'NUMPAD_6', 'NUMPAD_8', 'NUMPAD_1', 'NUMPAD_3', 'NUMPAD_5', 'NUMPAD_7', 'NUMPAD_9',
    'NUMPAD_PERIOD', 'NUMPAD_SLASH', 'NUMPAD_ASTERIX', 'NUMPAD_0', 'NUMPAD_MINUS', 'NUMPAD_ENTER', 'NUMPAD_PLUS',
    'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12', 'F13', 'F14', 'F15', 'F16', 'F17', 'F18', 'F19', 'F20', 'F21', 'F22', 'F23', 'F24',
    'PAUSE', 'INSERT',
    'HOME', 'PAGE_UP', 'PAGE_DOWN', 'END',
    'MEDIA_PLAY', 'MEDIA_STOP', 'MEDIA_FIRST', 'MEDIA_LAST',
    'ESC', 'TAB', 'RET', 'SPACE', 'LINE_FEED', 'BACK_SPACE', 'DEL',
    'LEFT_ARROW', 'DOWN_ARROW', 'RIGHT_ARROW', 'UP_ARROW',

    # ???
    'APP',

    # Text Input
    'TEXTINPUT',

    # Timer
    'TIMER', 'TIMER0', 'TIMER1', 'TIMER2', 'TIMER_JOBS', 'TIMER_AUTOSAVE', 'TIMER_REPORT', 'TIMERREGION',

    # NDOF
    'NDOF_MOTION', 'NDOF_BUTTON_MENU', 'NDOF_BUTTON_FIT', 'NDOF_BUTTON_TOP', 'NDOF_BUTTON_BOTTOM', 'NDOF_BUTTON_LEFT', 'NDOF_BUTTON_RIGHT',
    'NDOF_BUTTON_FRONT', 'NDOF_BUTTON_BACK', 'NDOF_BUTTON_ISO1', 'NDOF_BUTTON_ISO2', 'NDOF_BUTTON_ROLL_CW', 'NDOF_BUTTON_ROLL_CCW',
    'NDOF_BUTTON_SPIN_CW', 'NDOF_BUTTON_SPIN_CCW', 'NDOF_BUTTON_TILT_CW', 'NDOF_BUTTON_TILT_CCW', 'NDOF_BUTTON_ROTATE', 'NDOF_BUTTON_PANZOOM',
    'NDOF_BUTTON_DOMINANT', 'NDOF_BUTTON_PLUS', 'NDOF_BUTTON_MINUS',
    'NDOF_BUTTON_1', 'NDOF_BUTTON_2', 'NDOF_BUTTON_3', 'NDOF_BUTTON_4', 'NDOF_BUTTON_5', 'NDOF_BUTTON_6', 'NDOF_BUTTON_7', 'NDOF_BUTTON_8', 'NDOF_BUTTON_9', 'NDOF_BUTTON_10',
    'NDOF_BUTTON_A', 'NDOF_BUTTON_B', 'NDOF_BUTTON_C',

    # ???
    'XR_ACTION'
}
value: { 'ANY', 'PRESS', 'RELEASE', 'CLICK', 'DOUBLE_CLICK', 'CLICK_DRAG', 'NOTHING' }

class bpy.types.Event:
    alt                 True when the Alt/Option key is held  (unless both alt keys pressed and one is released)
    ascii               single ASCII character for this event
    ctrl                True when Ctrl key is held  (unless both ctrl keys pressed and one is released)
    direction           drag direction  (never used?)
    is_mouse_absolute   last motion event was an absolute input
    is_repeat           event is generated by holding a key down
    is_tablet           event has tablet data
    mouse_prev_press_x  window relative location of the last press event  (most recent press)
    mouse_prev_press_y
    mouse_prev_x        window relative location of mouse (in last event?)
    mouse_prev_y
    mouse_region_x      region relative location of mouse
    mouse_region_y
    mouse_x             window relative location of mouse
    mouse_y
    oskey               True when Cmd key is held
    pressure            pressure of tablet or 1.0 if no tablet present
    shift               True when Shift key is held  (unless both shift keys pressed and one is released)
    tilt                pressure (tilt?) of tablet or zeros if no tablet present ([float, float])
    type                (Type of event?)
    type_prev:          (type of last event?)
    unicode:            single unicode character for this event
    value:              type of event, only applies to some
    value_prev:         type of (last?) event, only applies to some
    xr:                 XR event data

class bpy.types.KeyMapItem:
    active              True when KMI is active
    alt                 Alt key pressed (int), -1 for any state
    alt_ui              (bool)
    any                 any modifier keys pressed
    ctrl                Control key pressed (int), -1 for any state
    ctrl_ui             (bool)
    direction           drag direction
    id                  ID of item (int [-32768, 32767], default 0)
    idname              identifier of operator to call on input event
    is_user_defined     True if KMI is user defined (doesn't just replace a builtin item)
    is_user_modified    True if KMI is modified by user
    key_modifier        Regular key pressed as a modifier (see type above)
    map_type            type of event mapping, { 'KEYBOARD', 'MOUSE', 'NDOF', 'TEXTINPUT', 'TIMER' }
    name                name of operator (translated) to call on input event
    oskey               Operating System Key pressed (int), -1 for any state
    oskey_ui            (bool)
    properties          Properties to set when the operator is called
    propvalue           the value this event translates to in a modal keymap
    repeat              active on key-repeat events (when key is held)
    shift               Shift key pressed (int), -1 for any state
    shift_ui            (bool)
    show_expanded       Show key map event and property details in the user interface
    type                type of event
    value               (value of event?)

bprefs.mouse_doubleclick()
bprefs.mouse_drag()
bprefs.mouse_move()
bprefs.mouse_select()

notes:

* if lshift is pressed, then shift is True. if rshift is pressed, then shift will still be True.
  if lshift or rshift are released, shift will be False!  but, this isn't an issue, as blender handles it in the same way.

* if modal operator invokes another operator on action, modal operator will only see the release of the action in (type_prev, value_prev)

* mouse_prev_press_* will hold location of mouse at most recent press (keyboard, mouse, anything!)

'''

class EventHandler:
    keyboard_modifier_types = {
        'LEFT_CTRL', 'LEFT_ALT', 'LEFT_SHIFT', 'RIGHT_ALT', 'RIGHT_CTRL', 'RIGHT_SHIFT', 'OSKEY',
    }
    keyboard_alpha_types = {
        'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M',
        'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z',
    }
    keyboard_number_types = {
        'ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE',
        'NUMPAD_2', 'NUMPAD_4', 'NUMPAD_6', 'NUMPAD_8', 'NUMPAD_1', 'NUMPAD_3', 'NUMPAD_5', 'NUMPAD_7', 'NUMPAD_9', 'NUMPAD_0',
    }
    keyboard_numpad_types = {
        'NUMPAD_2', 'NUMPAD_4', 'NUMPAD_6', 'NUMPAD_8', 'NUMPAD_1', 'NUMPAD_3', 'NUMPAD_5', 'NUMPAD_7', 'NUMPAD_9', 'NUMPAD_0',
        'NUMPAD_PERIOD', 'NUMPAD_SLASH', 'NUMPAD_ASTERIX', 'NUMPAD_MINUS', 'NUMPAD_PLUS',
        'NUMPAD_ENTER',
    }
    keyboard_function_types = {
        'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
        'F13', 'F14', 'F15', 'F16', 'F17', 'F18', 'F19', 'F20', 'F21', 'F22', 'F23', 'F24',
    }
    keyboard_symbols_types = {
        'SEMI_COLON', 'PERIOD', 'COMMA', 'QUOTE', 'ACCENT_GRAVE', 'MINUS', 'PLUS', 'SLASH', 'BACK_SLASH', 'EQUAL', 'LEFT_BRACKET', 'RIGHT_BRACKET',
        'NUMPAD_PERIOD', 'NUMPAD_SLASH', 'NUMPAD_ASTERIX', 'NUMPAD_MINUS', 'NUMPAD_PLUS',
        'GRLESS',
    }
    keyboard_media_types = {
        'MEDIA_PLAY', 'MEDIA_STOP', 'MEDIA_FIRST', 'MEDIA_LAST',
        'PAUSE',  # ???
    }
    keyboard_movement_types = {
        'HOME', 'PAGE_UP', 'PAGE_DOWN', 'END',
        'LEFT_ARROW', 'DOWN_ARROW', 'RIGHT_ARROW', 'UP_ARROW',
    }
    keyboard_escape_types = {
        'ESC',
        # 'TAB', ???
    }
    keyboard_edit_types = {
        'INSERT', 'TAB', 'RET', 'SPACE', 'LINE_FEED', 'BACK_SPACE', 'DEL',
    }
    keyboard_drag_types = {
        *keyboard_alpha_types,
        *keyboard_number_types,
        *keyboard_numpad_types,
        *keyboard_symbols_types,
    }
    keyboard_types = {
        *keyboard_modifier_types,
        *keyboard_alpha_types,
        *keyboard_number_types,
        *keyboard_numpad_types,
        *keyboard_function_types,
        *keyboard_symbols_types,
        *keyboard_media_types,
        *keyboard_movement_types,
        *keyboard_edit_types,
    }

    mouse_button_types = {
        'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE', 'BUTTON4MOUSE', 'BUTTON5MOUSE', 'BUTTON6MOUSE', 'BUTTON7MOUSE',
        'MOUSEROTATE', 'MOUSESMARTZOOM', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE',
        'PEN', 'ERASER',
        'TRACKPADPAN', 'TRACKPADZOOM',
    }
    mouse_move_types = {
        'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE',
    }
    mouse_types = { *mouse_button_types, *mouse_move_types, }

    ndof_types = {
        'NDOF_MOTION',
        'NDOF_BUTTON_MENU', 'NDOF_BUTTON_FIT', 'NDOF_BUTTON_TOP', 'NDOF_BUTTON_BOTTOM', 'NDOF_BUTTON_LEFT', 'NDOF_BUTTON_RIGHT',
        'NDOF_BUTTON_FRONT', 'NDOF_BUTTON_BACK', 'NDOF_BUTTON_ISO1', 'NDOF_BUTTON_ISO2', 'NDOF_BUTTON_ROLL_CW', 'NDOF_BUTTON_ROLL_CCW',
        'NDOF_BUTTON_SPIN_CW', 'NDOF_BUTTON_SPIN_CCW', 'NDOF_BUTTON_TILT_CW', 'NDOF_BUTTON_TILT_CCW', 'NDOF_BUTTON_ROTATE', 'NDOF_BUTTON_PANZOOM',
        'NDOF_BUTTON_DOMINANT', 'NDOF_BUTTON_PLUS', 'NDOF_BUTTON_MINUS',
        'NDOF_BUTTON_1', 'NDOF_BUTTON_2', 'NDOF_BUTTON_3', 'NDOF_BUTTON_4', 'NDOF_BUTTON_5', 'NDOF_BUTTON_6', 'NDOF_BUTTON_7', 'NDOF_BUTTON_8', 'NDOF_BUTTON_9', 'NDOF_BUTTON_10',
        'NDOF_BUTTON_A', 'NDOF_BUTTON_B', 'NDOF_BUTTON_C',
    }

    timer_types = {
        'TIMER', 'TIMER0', 'TIMER1', 'TIMER2', 'TIMER_JOBS', 'TIMER_AUTOSAVE', 'TIMER_REPORT', 'TIMERREGION',
    }


    scrollable_types = {
        'HOME', 'PAGE_UP', 'PAGE_DOWN', 'END',
        'LEFT_ARROW', 'DOWN_ARROW', 'RIGHT_ARROW', 'UP_ARROW',
        'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE',
        'TRACKPADPAN',
    }

    pressable_types = {
        # pressable also means releasable, clickable, double-clickable
        *keyboard_types,
        *mouse_button_types,
        *ndof_types
    }

    special_types = {
        'mousemove':  { 'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE' },
        'timer':      { 'TIMER', 'TIMER_REPORT', 'TIMERREGION' },
        'deactivate': { 'WINDOW_DEACTIVATE' },
    }

    modifier_keys = {
        'alt', 'ctrl', 'shift', 'oskey',
    }

    def __init__(self, context, *, allow_keyboard_dragging=False):
        self._allow_keyboard_dragging = allow_keyboard_dragging

        self.reset()

    def reset(self):
        # current states
        self.mods = { mod: False for mod in self.modifier_keys }
        self.mouse = None
        self.mouse_prev = None
        self._held = {}          # types that are currently held.  {event.type: time of first held}
        self._is_dragging = False
        self.is_navigating = False # <- need this???

        # memory
        self._first_held = None  # contains details of when first held action happened (held type, mouse loc, time)
        self._last_event_type = None
        self._just_released = None # keep track of last pressed for double click



    # these properties are for very temporal state changes
    @property
    def is_mousemove(self):
        return self._last_event_type in self.special_types['mousemove']
    @property
    def is_timer(self):
        return self._last_event_type in self.special_types['timer']
    @property
    def is_deactivate(self):
        return self._last_event_type in self.special_types['deactivate']


    def is_draggable(self, event):
        if self._allow_keyboard_dragging and event.type in self.keyboard_drag_types:
            return True
        if event.type in self.mouse_button_types:
            return True
        return False

    def is_double_click(self, *, event=None):
        if event and event.type != self.get_just_held('type'):
            return False
        delta = self.get_just_held('time') - time.time()
        return delta < prefs.mouse_doubleclick()

    def is_dragging(self, *, event=None):
        return get_held(event.type, prop='dragging') if event else self.get_first_held(prop='dragging')

    def holding_non_modifiers(self):
        return bool(t for t in self._held if t not in self.keyboard_modifier_types)

    def get_held(self, etype, *, prop=None, default=None):
        if etype not in self._held: return default
        d = self._held[etype]
        return d[prop] if prop else d

    def get_first_held(self, *, ignore_mods=True, prop=None, default=None):
        held = self._held
        if ignore_mods:
            held = {htype:held[htype] for htype in held if htype not in self.keyboard_modifier_types}
        if not held: return default
        d = min(held, key=lambda htype: held[htype]['time'])
        return d[prop] if prop else d

    def get_just_held(self, *, prop=None, default=None):
        return self._first_held[prop] if self._first_held else default

    def _update_press(self, event):
        # ignore non-pressable events
        if event.type not in self.pressable_types:
            return

        # FIRST, if nothing is held (ignoring modifiers), record first held details
        if not self.holding_non_modifiers():
            self._first_held = {
                'type':     event.type,
                'time':     time.time(),
                'mouse':    self.mouse,
                'dragging': False,
                'can drag': self.is_type_draggable(event),
                'double':   self.is_double_click(event),
            }

        self._held[event.type] = {
            'type':     event.type,
            'time':     time.time(),
            'mouse':    self.mouse,
            'dragging': False,
            'can drag': self.is_type_draggable(event),
            'double':   self.is_double_click(event),
        }

    def _update_release(self, event, *, prev=False):
        etype = event.type if not prev else event.prev_type

        if etype == self.get_first_held(prop='type'):
            self._just_released = self._first_held
            self._first_held = None

        if etype in self.held:
            del self._held[etype]

    def _update_drag(self, event):
        first_held = self.get_first_held()
        if first_held['dragging'] or not first_held['can drag']:
            return

        # has mouse moved far enough?
        mouse_travel = (first_held['mouse'] - self.mouse).length
        if mouse_travel > bprefs.mouse_drag():
            self._first_held['dragging'] = True

        fhtype = self._first_held['type']
        if self._allow_keyboard_dragging and fhtype in self.keyboard_drag_types:
            self._first_held['dragging'] = True
        elif fhtype in self.mouse_button_types:
            self._first_held['dragging'] = True

    def update(self, context, event):
        self._last_event_type = event.type

        if self.is_deactivate:
            # any time these actions are received, all action states will be flushed
            self.reset()

        self.mods['alt']   = event.alt
        self.mods['ctrl']  = event.ctrl
        self.mods['oskey'] = event.oskey
        self.mods['shift'] = event.shift
        self.mouse = Point2D((event.mouse_x, event.mouse_y))
        self.mouse_prev = Point2D((event.mouse_prev_x, event.mouse_prev_y))

        if event.value_prev == 'RELEASE':
            self._update_release(event, prev=True)

        if event.value == 'PRESS':
            self._update_press(event)
        elif event.value == 'RELEASE':
            self._update_release(event)
        elif event.value == 'NOTHING':
            if event.type == 'MOUSEMOVE':
                pass

        if event.type not in self.mouse_move_types:
            self._update_drag(event)

