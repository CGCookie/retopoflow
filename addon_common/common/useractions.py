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

from .blender import get_view3d_area, get_view3d_space, get_view3d_region
from .debug import dprint
from .decorators import blender_version_wrapper
from .human_readable import convert_actions_to_human_readable, convert_human_readable_to_actions
from .maths import Point2D, Vec2D
from .timerhandler import TimerHandler
from .utils import Dict
from . import blender_preferences as bprefs


action_to_char = {
    'ZERO':   '0', 'NUMPAD_0':       '0',
    'ONE':    '1', 'NUMPAD_1':       '1',
    'TWO':    '2', 'NUMPAD_2':       '2',
    'THREE':  '3', 'NUMPAD_3':       '3',
    'FOUR':   '4', 'NUMPAD_4':       '4',
    'FIVE':   '5', 'NUMPAD_5':       '5',
    'SIX':    '6', 'NUMPAD_6':       '6',
    'SEVEN':  '7', 'NUMPAD_7':       '7',
    'EIGHT':  '8', 'NUMPAD_8':       '8',
    'NINE':   '9', 'NUMPAD_9':       '9',
    'PERIOD': '.', 'NUMPAD_PERIOD':  '.',
    'PLUS':   '+', 'NUMPAD_PLUS':    '+',
    'MINUS':  '-', 'NUMPAD_MINUS':   '-',
    'SLASH':  '/', 'NUMPAD_SLASH':   '/',
                   'NUMPAD_ASTERIX': '*',
    'BACK_SLASH':   '\\',
    'SPACE':        ' ',
    'EQUAL':        '=',
    'SEMI_COLON':   ';', 'COMMA':         ',',
    'LEFT_BRACKET': '[', 'RIGHT_BRACKET': ']',
    'QUOTE':        "'", 'ACCENT_GRAVE':  '`',
    'GRLESS':       '>',

    'A':'a', 'B':'b', 'C':'c', 'D':'d',
    'E':'e', 'F':'f', 'G':'g', 'H':'h',
    'I':'i', 'J':'j', 'K':'k', 'L':'l',
    'M':'m', 'N':'n', 'O':'o', 'P':'p',
    'Q':'q', 'R':'r', 'S':'s', 'T':'t',
    'U':'u', 'V':'v', 'W':'w', 'X':'x',
    'Y':'y', 'Z':'z',

    'SHIFT+A':'A', 'SHIFT+B':'B', 'SHIFT+C':'C', 'SHIFT+D':'D',
    'SHIFT+E':'E', 'SHIFT+F':'F', 'SHIFT+G':'G', 'SHIFT+H':'H',
    'SHIFT+I':'I', 'SHIFT+J':'J', 'SHIFT+K':'K', 'SHIFT+L':'L',
    'SHIFT+M':'M', 'SHIFT+N':'N', 'SHIFT+O':'O', 'SHIFT+P':'P',
    'SHIFT+Q':'Q', 'SHIFT+R':'R', 'SHIFT+S':'S', 'SHIFT+T':'T',
    'SHIFT+U':'U', 'SHIFT+V':'V', 'SHIFT+W':'W', 'SHIFT+X':'X',
    'SHIFT+Y':'Y', 'SHIFT+Z':'Z',

    'SHIFT+ZERO':   ')',
    'SHIFT+ONE':    '!',
    'SHIFT+TWO':    '@',
    'SHIFT+THREE':  '#',
    'SHIFT+FOUR':   '$',
    'SHIFT+FIVE':   '%',
    'SHIFT+SIX':    '^',
    'SHIFT+SEVEN':  '&',
    'SHIFT+EIGHT':  '*',
    'SHIFT+NINE':   '(',
    'SHIFT+PERIOD': '>',
    'SHIFT+PLUS':   '+',
    'SHIFT+MINUS':  '_',
    'SHIFT+SLASH':  '?',
    'SHIFT+BACK_SLASH':   '|',
    'SHIFT+EQUAL':        '+',
    'SHIFT+SEMI_COLON':   ':', 'SHIFT+COMMA':         '<',
    'SHIFT+LEFT_BRACKET': '{', 'SHIFT+RIGHT_BRACKET': '}',
    'SHIFT+QUOTE':        '"', 'SHIFT+ACCENT_GRAVE':  '~',
    'SHIFT+GRLESS':       '<',

    'ESC':        'Escape',
    'BACK_SPACE': 'Backspace',
    'RET':        'Enter',      'NUMPAD_ENTER': 'Enter',
    'HOME':       'Home',       'END':          'End',
    'LEFT_ARROW': 'ArrowLeft',  'RIGHT_ARROW':  'ArrowRight',
    'UP_ARROW':   'ArrowUp',    'DOWN_ARROW':   'ArrowDown',
    'PAGE_UP':    'PageUp',     'PAGE_DOWN':    'PageDown',
    'DEL':        'Delete',
    'TAB':        'Tab',
}

translate_action = {
    'WHEELINMOUSE':  'WHEELUPMOUSE',
    'WHEELOUTMOUSE': 'WHEELDOWNMOUSE',
}

re_blenderop = re.compile(r'(?P<keymap>.+?) *\| *(?P<operator>.+)')


# https://docs.blender.org/api/current/bpy.types.KeyMapItems.html
# https://docs.blender.org/api/current/bpy_types_enum_items/event_type_items.html
# https://docs.blender.org/api/current/bpy_types_enum_items/event_value_items.html
ndof_actions = {
    'NDOF_MOTION',

    'NDOF_BUTTON',       'NDOF_BUTTON_FIT',
    'NDOF_BUTTON_TOP',   'NDOF_BUTTON_BOTTOM',
    'NDOF_BUTTON_LEFT',  'NDOF_BUTTON_RIGHT',
    'NDOF_BUTTON_FRONT', 'NDOF_BUTTON_BACK',

    'NDOF_BUTTON_ISO1', 'NDOF_BUTTON_ISO2',

    'NDOF_BUTTON_ROLL_CW', 'NDOF_BUTTON_ROLL_CCW',
    'NDOF_BUTTON_SPIN_CW', 'NDOF_BUTTON_SPIN_CCW',
    'NDOF_BUTTON_TILT_CW', 'NDOF_BUTTON_TILT_CCW',
    'NDOF_BUTTON_ROTATE',  'NDOF_BUTTON_PANZOOM',

    'NDOF_BUTTON_DOMINANT',

    'NDOF_BUTTON_PLUS', 'NDOF_BUTTON_MINUS', 'NDOF_BUTTON_ESC',
    'NDOF_BUTTON_ALT',  'NDOF_BUTTON_SHIFT', 'NDOF_BUTTON_CTRL',

    'NDOF_BUTTON_1', 'NDOF_BUTTON_2', 'NDOF_BUTTON_3', 'NDOF_BUTTON_4', 'NDOF_BUTTON_5',
    'NDOF_BUTTON_6', 'NDOF_BUTTON_7', 'NDOF_BUTTON_8', 'NDOF_BUTTON_9', 'NDOF_BUTTON_10',
    'NDOF_BUTTON_A', 'NDOF_BUTTON_B', 'NDOF_BUTTON_C',
}

mousebutton_actions = {
    'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE',
    'BUTTON4MOUSE', 'BUTTON5MOUSE', 'BUTTON6MOUSE', 'BUTTON7MOUSE',
}

ignore_actions = {}

nonprintable_actions = {
    'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE',
    'TIMER', 'TIMER_REPORT', 'TIMERREGION',
}

reset_actions = {
    # any time these actions are received, all action states will be flushed
    'WINDOW_DEACTIVATE',
}

timer_actions = {
    'TIMER'
}

mousemove_actions = {
    'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE',
}

trackpad_actions = {
    'TRACKPADPAN', 'TRACKPADZOOM',
    'MOUSEROTATE', 'MOUSESMARTZOOM',
}

modifier_actions = {
    'OSKEY',
    'LEFT_CTRL', 'LEFT_SHIFT', 'LEFT_ALT',
    'RIGHT_CTRL', 'RIGHT_SHIFT', 'RIGHT_ALT',
}

blender_operator_keymaps = [
    {
        'name': 'navigate',
        'operators': [
            '3D View | view3d.rotate',                # Rotate View
            '3D View | view3d.move',                  # Move View
            '3D View | view3d.zoom',                  # Zoom View
            '3D View | view3d.dolly',                 # Dolly View
            '3D View | view3d.view_pan',              # View Pan
            '3D View | view3d.view_orbit',            # View Orbit
            '3D View | view3d.view_persportho',       # View Persp/Ortho
            '3D View | view3d.viewnumpad',            # View Numpad
            '3D View | view3d.view_axis',             # View Axis
            '3D View | view2d.ndof',                  # NDOF Pan Zoom
            '3D View | view3d.ndof_orbit_zoom',       # NDOF Orbit View with Zoom
            '3D View | view3d.ndof_orbit',            # NDOF Orbit View
            '3D View | view3d.ndof_pan',              # NDOF Pan View
            '3D View | view3d.ndof_all',              # NDOF Move View
            '3D View | view3d.view_roll',             # NDOF View Roll
            '3D View | view3d.view_selected',         # View Selected
            '3D View | view3d.view_center_cursor',    # Center View to Cursor
            '3D View | view3d.view_center_pick',      # Center View to Mouse
            # '3D View | view3d.navigate',              # View Navigation
        ],
    }, {
        'name': 'blender window action',
        'operators': [
            # COMMENTED OUT, BECAUSE THERE IS A BUG WITH CONTEXT CHANGING!!
            # 'Screen | screen.screen_full_area',
            # 'Window | wm.window_fullscreen_toggle',
        ],
    }, {
        'name': 'blender save',
        'operators': [
            'Window | wm.save_mainfile',
        ],
    }, {
        'name': 'blender undo',
        'operators': [
            'Screen | ed.undo',
        ],
    }, {
        'name': 'blender redo',
        'operators': [
            'Screen | ed.redo',
        ],
    }, {
        'name': 'clipboard paste',
        'operators': [
            'Text | text.paste',
            '3D View | view3d.pastebuffer',
            'Console | console.paste',
        ],
    },
]

def get_kmi_properties(kmi):
    return {
        k: getattr(kmi.properties, k)
        for k in dir(kmi.properties)
        if k not in {'__doc__', '__module__', '__slots__', 'bl_rna', 'rna_type'}
    }

def event_match_blenderop(event, blenderop):
    for kmi in blenderop_to_kmis(blenderop):
        if event.ctrl  != kmi.ctrl_ui:  continue
        if event.alt   != kmi.alt_ui:   continue
        if event.shift != kmi.shift_ui: continue
        if event.oskey != kmi.oskey_ui: continue
        if event.type  != kmi.type:     continue
        if event.value != kmi.value:    continue
        # print(kmi)
        # for k in dir(kmi):
        #     print(f'  {k}={getattr(kmi,k)}')
        #     if k == 'properties':
        #         for k2 in dir(kmi.properties):
        #             print(f'    {k2}={getattr(kmi.properties, k2)}')
        return kmi
    return None

def blenderop_to_kmis(blenderop):
    keymaps = bpy.context.window_manager.keyconfigs.user.keymaps
    i18n_translate = bpy.app.translations.pgettext                  # bpy.app.translations.pgettext tries to translate the given parameter

    m = re_blenderop.match(blenderop)
    if not m:
        print(f'blenderop_to_kmis: {blenderop}')
        return set()
    okeymap, ooperator = m['keymap'], m['operator']
    tkeymap, toperator = i18n_translate(okeymap), i18n_translate(ooperator)
    keymap = keymaps.get(okeymap, None) or keymaps.get(tkeymap, None)
    if not keymap: return set()
    return {
        kmi
        for kmi in keymap.keymap_items
        if all([
            kmi.active,
            kmi.idname in {ooperator, toperator},
            getattr(kmi, 'direction', 'ANY') == 'ANY'
        ])
    }

def kmi_to_op_properties(kmi):
    path = kmi.idname.split('.')
    op = getattr(getattr(bpy.ops, path[0]), path[1])
    props = { k: kmi.path_resolve(f'properties.{k}') for k in kmi.properties.keys() }
    return (op, props)

def blenderop_to_actions(blenderop):
    return { kmi_to_action(kmi) for kmi in blenderop_to_kmis(blenderop) }

def action_strip_mods(action, *, ctrl=True, shift=True, alt=True, oskey=True, click=True, double_click=True, drag_click=True, mouse=False):
    if action is None: return None
    if mouse and 'MOUSE' in action: return ''
    if ctrl:  action = action.replace('CTRL+',  '')
    if shift: action = action.replace('SHIFT+', '')
    if alt:   action = action.replace('ALT+',   '')
    if oskey: action = action.replace('OSKEY+', '')
    if click: action = action.replace('+CLICK', '')
    if double_click: action = action.replace('+DOUBLE', '')
    if drag_click:   action = action.replace('+DRAG',   '')
    return action

def action_add_mods(action, *, ctrl=False, shift=False, alt=False, oskey=False, click=False, double_click=False, drag_click=False):
    if not action: return action
    action = translate_action.get(action, action)
    return ''.join([
        ('CTRL+'  if ctrl  else ''),
        ('SHIFT+' if shift else ''),
        ('ALT+'   if alt   else ''),
        ('OSKEY+' if oskey else ''),
        action,
        ('+CLICK'  if click and not (double_click or drag_click) else ''),
        ('+DOUBLE' if double_click and not drag_click else ''),
        ('+DRAG'   if drag_click else ''),
    ])

def kmi_to_action(kmi, *, event_type=None, click=False, double_click=False, drag_click=False):
    return action_add_mods(
        event_type or kmi.type,
        ctrl=kmi.ctrl, shift=kmi.shift, alt=kmi.alt, oskey=kmi.oskey,
        click=(kmi.value=='CLICK' or click),
        double_click=(kmi.value=='DOUBLE_CLICK' or double_click),
        drag_click=(kmi.value=='CLICK_DRAG' or drag_click),
    )



class Actions:
    @staticmethod
    def get_instance(context):
        if not hasattr(Actions, '_instance'):
            Actions._create = True
            Actions._instance = Actions(context)
            del Actions._create
        return Actions._instance

    @staticmethod
    def done():
        if not hasattr(Actions, '_instance'): return
        del Actions._instance

    def __init__(self, context):
        assert hasattr(Actions, '_create'), 'Do not create new instance of Actions.  Instead, use Actions.get_instance()'
        assert not hasattr(Actions, '_instance'), 'Only create one instance of Actions!  Then use Actions.get_instance()'

        self.update_context(context)

        # keymaps
        self.keymaps_universal  = Dict(get_default_fn=set)
        self.keymaps_contextual = Dict(get_default_fn=set)

        self.keymaps_blender_operators = Dict(get_default_fn=list)

        # fill in universal and action keymaps
        self.keymaps_universal['navigate'] = trackpad_actions | ndof_actions
        for group in blender_operator_keymaps:
            group_name, blenderops = group['name'], group['operators']

            # self.keymaps_universal.setdefault(group_name, set())
            self.keymaps_universal[group_name] |= {
                action
                for blenderop in blenderops
                for action in blenderop_to_actions(blenderop)
            }

            for blenderop in blenderops:
                for kmi in blenderop_to_kmis(blenderop):
                    action, op_props = kmi_to_action(kmi), kmi_to_op_properties(kmi)
                    self.keymaps_blender_operators[action] += [op_props]

        self.timer      = False     # is action from timer?
        self.time_delta = 0         # elapsed time since last "step" (units=seconds)
        self.time_last  = time.time()

        # IMPORTANT: the following properties are updated external to Actions
        self.hit_pos  = None    # position of raytraced mouse to scene (updated externally!)
        self.hit_norm = None    # normal of raytraced mouse to scene (updated externally!)

        self.reset_state(all_state=True)

    def update_context(self, context):
        self.context = context
        self.screen  = context.screen
        self.window  = context.window

        # try to find area, region, space, region_3d
        try:
            self.area   = get_view3d_area(context)
            self.region = get_view3d_region(context)
            self.space  = get_view3d_space(context)
            self.size   = Vec2D((self.region.width, self.region.height))
            self.r3d    = self.space.region_3d
        except Exception as e:
            print(f'******************************************')
            print(f'Addon Common: Could not find VIEW_3D area!')
            print(f'Exception: {e}')
            self.area   = None
            self.region = None
            self.size   = None
            self.r3d    = None


    def reset_state(self, all_state=False):
        self.actions_using    = set()
        self.actions_pressed  = set()
        self.actions_prevtime = dict()  # previous time when action was pressed
        self.now_pressed      = dict()  # currently pressed keys. key=stripped event type, value=full event type (includes modifiers)
        self.just_pressed     = None
        self.last_pressed     = None
        self.event_type       = None

        # indicates if modifier keys are currently pressed
        self.ctrl        = False  # note: will be true if either ctrl_left or ctrl_right are true
        self.ctrl_left   = False
        self.ctrl_right  = False
        self.shift       = False
        self.shift_left  = False
        self.shift_right = False
        self.alt         = False
        self.alt_left    = False
        self.alt_right   = False

        # non-keyboard and non-mouse properties
        self.trackpad = False   # is current action from trackpad?
        self.ndof     = False   # is current action from NDOF?
        self.scroll   = (0, 0)

        # mouse-related properties
        if all_state:
            self.mouse_select = bprefs.mouse_select()
            self.mouse        = None    # current mouse position
        self.mouse_prev       = None    # previous mouse position
        self.mouse_lastb      = None    # last button pressed on mouse
        self.mousemove        = False   # is the current action a mouse move?
        self.mousemove_prev   = False   # was the previous action a mouse move?
        self.mousemove_stop   = False   # did the mouse just stop moving?
        self.mousedown        = None    # mouse position when a mouse button was pressed
        self.mousedown_left   = None    # mouse position when LMB was pressed
        self.mousedown_middle = None    # mouse position when MMB was pressed
        self.mousedown_right  = None    # mouse position when RMB was pressed
        self.mousedown_drag   = False   # is user dragging?

        # indicates if currently navigating
        self.is_navigating = False

    def call_action_operator(self, action, *args, **kwargs):
        ops_props = self.keymaps_blender_operators[action]
        if not ops_props: return
        try:
            op, props = ops_props[0]
            # print(f'Invoking {action} {op} {props}')
            ret = op('INVOKE_DEFAULT', *args, **kwargs, **props)
        except Exception as e:
            print(f'Actions.call_action_operator: Caught Exception while calling Blender operator')
            print(f'  {action=}')
            print(f'  {op=}')
            print(f'  {props=}')
            print(e)
            ret = None
        return ret

    actions_prevtime_default = (0, 0, float('inf'))
    def get_last_press_time(self, event_type):
        return self.actions_prevtime.get(event_type, self.actions_prevtime_default)

    def update(self, context, event, fn_debug=None):
        if event.type in reset_actions:
            # print(f'Actions.update: resetting state')
            self.reset_state()
            return

        self.unpress()

        self.update_context(context)

        event_type, pressed = event.type, (event.value == 'PRESS')

        if pressed:
            _,prevtime,_ = self.get_last_press_time(event_type)
            curtime = time.time()
            self.actions_prevtime[event_type] = (prevtime, curtime, curtime - prevtime)

        self.event_type     = event_type
        self.mousemove_prev = self.mousemove
        self.timer          = (event_type in timer_actions)
        self.mousemove      = (event_type in mousemove_actions)
        self.trackpad       = (event_type in trackpad_actions)
        self.ndof           = (event_type in ndof_actions)
        self.mousemove_stop = not self.mousemove and self.mousemove_prev
        self.scroll         = (0, 0)    # to be set below

        # record held modifiers
        self.ctrl  = event.ctrl
        self.alt   = event.alt
        self.shift = event.shift
        self.oskey = event.oskey

        # handle completely ignorable actions (if any)
        if event_type in ignore_actions: return

        if fn_debug and event_type not in nonprintable_actions:
            fn_debug('update start', event_type=event_type, event_value=event.value)

        # ignore modifier key presses, as they do not "fire" pressed events
        if event_type in modifier_actions:
            return

        # handle timer event
        if self.timer:
            time_cur = time.time()
            self.time_delta = self.time_last - time_cur
            self.time_last = time_cur
            return

        self.is_navigating = False

        # handle mouse move event
        if self.mousemove:
            self.mouse_prev = self.mouse
            self.mouse = Point2D((float(event.mouse_region_x), float(event.mouse_region_y)))

            if not self.mousedown:
                self.mousedown_drag = False
                return
            if self.mousedown_drag: return
            if (self.mouse - self.mousedown).length <= bprefs.mouse_drag(): return

            self.mousedown_drag = True
            # can user drag non-mouse keys??
            if   self.mousedown_left:   event_type = 'LEFTMOUSE'
            elif self.mousedown_middle: event_type = 'MIDDLEMOUSE'
            elif self.mousedown_right:  event_type = 'RIGHTMOUSE'
            self.event_type = event_type
            pressed = True
        elif event_type in {'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE'} and not pressed:
            # release drag when mouse button is released
            # can user drag non-mouse keys??
            self.mousedown_drag = False

        # handle trackpad event
        if self.trackpad:
            pressed = True
            self.scroll = (event.mouse_x - event.mouse_prev_x, event.mouse_y - event.mouse_prev_y)

        # handle navigation event
        full_event_type = action_add_mods(
            event_type,
            ctrl=self.ctrl, alt=self.alt,
            shift=self.shift, oskey=self.oskey,
            drag_click=self.mousedown_drag,
        )

        self.is_navigating = (full_event_type in self.keymaps_universal['navigate'])
        if self.is_navigating:
            self.unuse(full_event_type)

        mouse_event = event_type in mousebutton_actions and not self.is_navigating
        if mouse_event:
            if pressed:
                if self.mouse_lastb != event_type: self.mousedown_drag = False
                self.mousedown = Point2D((float(event.mouse_region_x), float(event.mouse_region_y)))
                if   event_type == 'LEFTMOUSE':   self.mousedown_left   = self.mousedown
                elif event_type == 'MIDDLEMOUSE': self.mousedown_middle = self.mousedown
                elif event_type == 'RIGHTMOUSE':  self.mousedown_right  = self.mousedown
                self.mouse_lastb = event_type
            else:
                self.mousedown = None
                self.mousedown_left = None
                self.mousedown_middle = None
                self.mousedown_right = None
                self.mousedown_drag = False

        ftype = kmi_to_action(event, event_type=event_type, drag_click=self.mousedown_drag and mouse_event)
        if pressed:
            # if event_type not in self.now_pressed:
            #     self.just_pressed = ftype
            self.just_pressed = ftype
            if 'WHEELUPMOUSE' in ftype or 'WHEELDOWNMOUSE' in ftype:
                # mouse wheel actions have no release, so handle specially
                self.just_pressed = ftype
            else:
                self.now_pressed[event_type] = ftype
            self.last_pressed = ftype
        else:
            if event_type in self.now_pressed:
                if event_type in mousebutton_actions and not self.mousedown_drag:
                    _,_,deltatime = self.get_last_press_time(event_type)
                    single = (deltatime > bprefs.mouse_doubleclick()) or (self.mouse_lastb != event_type)
                    self.just_pressed = kmi_to_action(event, event_type=event_type, click=single, double_click=not single)
                else:
                    del self.now_pressed[event_type]

        if fn_debug and event_type not in nonprintable_actions:
            fn_debug(
                'update end',
                ftype=ftype,
                pressed=pressed,
                just_pressed=self.just_pressed,
                now_pressed=self.now_pressed,
                last_pressed=self.last_pressed,
            )

    def _convert(self, action):
        return (self.keymaps_universal[action] | self.keymaps_contextual[action]) or { action }
    def convert(self, actions):
        match actions:
            case set():  pass                     # already a set; no need to do anything
            case str():  actions = { actions }    # passed only a string
            case list(): actions = set(actions)   # prevent duplicate actions by converting to set
            case _:      actions = { actions }    # catch all (should not happen)
        return { a for action in actions for a in self._convert(action) }

    def to_human_readable(self, actions, *, sep=',', onlyfirst=None, visible=False):
        if type(actions) is str: actions = { actions }
        actions = [ act for action in actions for act in self.convert(action) ]
        return convert_actions_to_human_readable(actions, sep=sep, onlyfirst=onlyfirst, visible=visible)

    def from_human_readable(self, actions):
        return convert_human_readable_to_actions(actions)


    def unuse(self, actions, ignoremods=False, ignorectrl=False, ignoreshift=False, ignorealt=False, ignoreoskey=False, ignoremulti=False, ignoreclick=False, ignoredouble=False, ignoredrag=False):
        if not actions: return
        strip_mods = lambda p: action_strip_mods(
            p,
            ctrl         = ignorectrl   or ignoremods,
            shift        = ignoreshift  or ignoremods,
            alt          = ignorealt    or ignoremods,
            oskey        = ignoreoskey  or ignoremods,
            click        = ignoreclick  or ignoremulti,
            double_click = ignoredouble or ignoremulti,
            drag_click   = ignoredrag   or ignoremulti,
        )
        actions = [ strip_mods(p) for p in self.convert(actions) ]
        keys = [k for k,v in self.now_pressed.items() if strip_mods(v) in actions]
        for k in keys: del self.now_pressed[k]
        self.mousedown = None
        self.mousedown_left = None
        self.mousedown_middle = None
        self.mousedown_right = None
        self.mousedown_drag = False
        self.unpress()

    def unpress(self):
        if not self.just_pressed: return
        just_pressed_no_mods = action_strip_mods(self.just_pressed)
        if just_pressed_no_mods in self.now_pressed:
            if '+CLICK' in self.just_pressed:
                del self.now_pressed[just_pressed_no_mods]
            elif '+DOUBLE' in self.just_pressed:
                del self.now_pressed[just_pressed_no_mods]
        self.just_pressed = None

    def using(self, actions, using_all=False, ignoremods=False, ignorectrl=False, ignoreshift=False, ignorealt=False, ignoreoskey=False, ignoremulti=False, ignoreclick=False, ignoredouble=False, ignoredrag=False):
        if actions is None: return False
        strip_mods = lambda p: action_strip_mods(
            p,
            ctrl         = ignorectrl   or ignoremods,
            shift        = ignoreshift  or ignoremods,
            alt          = ignorealt    or ignoremods,
            oskey        = ignoreoskey  or ignoremods,
            click        = ignoreclick  or ignoremulti,
            double_click = ignoredouble or ignoremulti,
            drag_click   = ignoredrag   or ignoremulti,
        )
        actions = [ strip_mods(p) for p in self.convert(actions) ]
        results = [ strip_mods(p) in actions for p in self.now_pressed.values() ]
        return all(results) if using_all else any(results)

    def using_onlymods(self, actions, exact=True):
        if actions is None: return False
        def action_good(action):
            nonlocal exact
            act_c = 'CTRL+'  in action
            act_s = 'SHIFT+' in action
            act_a = 'ALT+'   in action
            ret = True
            if exact:
                ret &= act_c == self.ctrl
                ret &= act_s == self.shift
                ret &= act_a == self.alt
            else:
                ret &= not (act_c and self.ctrl)
                ret &= not (act_s and self.shift)
                ret &= not (act_a and self.alt)
            return ret
        return any(action_good(action) for action in self.convert(actions))

    def pressed(self, actions, unpress=True, ignoremods=False, ignorectrl=False, ignoreshift=False, ignorealt=False, ignoreoskey=False, ignoremulti=False, ignoreclick=False, ignoredouble=False, ignoredrag=False, ignoremouse=False):
        if actions is None: return False
        if not self.just_pressed: return False
        actions = self.convert(actions)
        just_pressed = action_strip_mods(
            self.just_pressed,
            ctrl         = ignorectrl   or ignoremods,
            shift        = ignoreshift  or ignoremods,
            alt          = ignorealt    or ignoremods,
            oskey        = ignoreoskey  or ignoremods,
            click        = ignoreclick  or ignoremulti,
            double_click = ignoredouble or ignoremulti,
            drag_click   = ignoredrag   or ignoremulti,
            mouse        = ignoremouse,
        )
        if not just_pressed: return False
        ret = just_pressed in actions
        if ret and unpress: self.unpress()
        return ret

    def released(self, actions, released_all=False, ignoredrag=True, **kwargs):
        if actions is None: return False
        return not self.using(actions, using_all=released_all, ignoredrag=ignoredrag, **kwargs)

    def warp_mouse(self, xy:Point2D):
        rx,ry = self.region.x,self.region.y
        mx,my = xy
        self.context.window.cursor_warp(rx + mx, ry + my)

    def valid_mouse(self):
        if self.mouse is None: return False
        mx,my = self.mouse
        sx,sy = self.size
        return 0 <= mx < sx and 0 <= my < sy

    def as_char(self, ftype):
        return action_to_char.get(ftype, '')

    def start_timer(self, hz, enabled=True):
        return TimerHandler(hz, context=self.context, enabled=enabled)


class ActionHandler:
    _actions = None

    def __init__(self, context, keymap={}):
        if not ActionHandler._actions:
            ActionHandler._actions = Actions.get_instance(context)

        self.__dict__['_keymap'] = Dict({
            k: ({actions} if type(actions) is str else set(actions))
            for (k, actions) in keymap.items()
        }, get_default_fn=set)

    def __getattr__(self, key):
        if not ActionHandler._actions: return None
        ActionHandler._actions.keymaps_contextual = self._keymap
        return getattr(ActionHandler._actions, key)

    def __setattr__(self, key, value):
        if not ActionHandler._actions: return
        ActionHandler._actions.keymaps_contextual = self._keymap
        return setattr(ActionHandler._actions, key, value)

    def done(self):
        if not ActionHandler._actions: return
        ActionHandler._actions.done()
        ActionHandler._actions = None





