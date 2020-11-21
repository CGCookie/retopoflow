'''
Copyright (C) 2020 CG Cookie
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

from .maths import Point2D, Vec2D
from .debug import dprint
from .decorators import blender_version_wrapper
from . import blender_preferences as bprefs


# https://www.w3schools.com/jsref/tryit.asp?filename=tryjsref_event_key_keycode2

kmi_to_keycode = {
    'BACK_SPACE':    8,
    'RET':          13,
    'NUMPAD_ENTER': 13,
    'ESC':          27,
    'END':          35,
    'HOME':         36,
    'LEFT_ARROW':   37,
    'RIGHT_ARROW':  39,
    'DEL':          46,
}

keycode_to_kmi = {
     8: {'BACK_SPACE'},
    13: {'RET', 'NUMPAD_ENTER'},
    27: {'ESC'},
    35: {'END'},
    36: {'HOME'},
    37: {'LEFT_ARROW'},
    39: {'RIGHT_ARROW'},
    46: {'DEL'},
}

def is_keycode(keycode, kmi):
    return keycode == kmi_to_keycode[kmi]

kmi_to_char = {
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
    'A':'a', 'B':'b', 'C':'c', 'D':'d',
    'E':'e', 'F':'f', 'G':'g', 'H':'h',
    'I':'i', 'J':'j', 'K':'k', 'L':'l',
    'M':'m', 'N':'n', 'O':'o', 'P':'p',
    'Q':'q', 'R':'r', 'S':'s', 'T':'t',
    'U':'u', 'V':'v', 'W':'w', 'X':'x',
    'Y':'y', 'Z':'z',
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
    'SHIFT+A':'A', 'SHIFT+B':'B', 'SHIFT+C':'C', 'SHIFT+D':'D',
    'SHIFT+E':'E', 'SHIFT+F':'F', 'SHIFT+G':'G', 'SHIFT+H':'H',
    'SHIFT+I':'I', 'SHIFT+J':'J', 'SHIFT+K':'K', 'SHIFT+L':'L',
    'SHIFT+M':'M', 'SHIFT+N':'N', 'SHIFT+O':'O', 'SHIFT+P':'P',
    'SHIFT+Q':'Q', 'SHIFT+R':'R', 'SHIFT+S':'S', 'SHIFT+T':'T',
    'SHIFT+U':'U', 'SHIFT+V':'V', 'SHIFT+W':'W', 'SHIFT+X':'X',
    'SHIFT+Y':'Y', 'SHIFT+Z':'Z',
}

# these are separated into a list so that "SHIFT+ZERO" (for example) is handled
# before the "SHIFT" gets turned into "Shift"
kmi_to_humanreadable = [
    {
        # most printable characters
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

        'BACK_SPACE': 'Backspace',
        'BACK_SLASH':   '\\',
    },{
        'SPACE':        ' ',

        'ZERO':   '0', 'NUMPAD_0':       'Num0',
        'ONE':    '1', 'NUMPAD_1':       'Num1',
        'TWO':    '2', 'NUMPAD_2':       'Num2',
        'THREE':  '3', 'NUMPAD_3':       'Num3',
        'FOUR':   '4', 'NUMPAD_4':       'Num4',
        'FIVE':   '5', 'NUMPAD_5':       'Num5',
        'SIX':    '6', 'NUMPAD_6':       'Num6',
        'SEVEN':  '7', 'NUMPAD_7':       'Num7',
        'EIGHT':  '8', 'NUMPAD_8':       'Num8',
        'NINE':   '9', 'NUMPAD_9':       'Num9',
        'PERIOD': '.', 'NUMPAD_PERIOD':  'Num.',
        'PLUS':   '+', 'NUMPAD_PLUS':    'Num+',
        'MINUS':  '-', 'NUMPAD_MINUS':   'Num-',
        'SLASH':  '/', 'NUMPAD_SLASH':   'Num/',
                       'NUMPAD_ASTERIX': 'Num*',

        'EQUAL':        '=',
        'SEMI_COLON':   ';', 'COMMA':         ',',
        'LEFT_BRACKET': '[', 'RIGHT_BRACKET': ']',
        'QUOTE':        "'", 'ACCENT_GRAVE':  '`',
        # prefix modifiers
        'SHIFT': 'Shift', 'CTRL': 'Ctrl', 'ALT': 'Alt', 'OSKEY': 'OSKey',

        # non-printable characters
        'ESC': 'Esc',
        'RET': 'Enter', 'NUMPAD_ENTER': 'Enter',
        'TAB': 'Tab',
        'DEL': 'Delete',
        'UP_ARROW': 'Up', 'DOWN_ARROW': 'Down', 'LEFT_ARROW': 'Left', 'RIGHT_ARROW': 'Right',
        # mouse
        'LEFTMOUSE': 'LMB', 'MIDDLEMOUSE': 'MMB', 'RIGHTMOUSE': 'RMB',
        'WHEELUPMOUSE': 'WheelUp', 'WHEELDOWNMOUSE': 'WheelDown',
        # postfix modifiers
        'DRAG': 'Drag', 'DOUBLE': 'Double', 'CLICK': 'Click',
    }
]


def kmi_details(kmi, event_type=None, click=False, double_click=False, drag_click=False):
    kmi_ctrl  = 'CTRL+'  if kmi.ctrl  else ''
    kmi_shift = 'SHIFT+' if kmi.shift else ''
    kmi_alt   = 'ALT+'   if kmi.alt   else ''
    kmi_os    = 'OSKEY+' if kmi.oskey else ''
    # https://docs.blender.org/api/current/bpy.types.KeyMapItem.html#bpy.types.KeyMapItem.value
    kmi_click  = '+CLICK'  if kmi.value=='CLICK'        or click        else ''
    kmi_double = '+DOUBLE' if kmi.value=='DOUBLE_CLICK' or double_click else ''
    kmi_drag   = '+DRAG'   if kmi.value=='CLICK_DRAG'   or drag_click   else ''

    kmi_type = event_type or kmi.type
    if kmi_type == 'WHEELINMOUSE':  kmi_type = 'WHEELUPMOUSE'
    if kmi_type == 'WHEELOUTMOUSE': kmi_type = 'WHEELDOWNMOUSE'

    return kmi_ctrl + kmi_shift + kmi_alt + kmi_os + kmi_type + kmi_click + kmi_double + kmi_drag


re_blenderop = re.compile(r'(?P<keymap>.+?) *\| *(?P<operator>.+)')
def translate_blenderop(action, keyconfig=None):
    m_blenderop = re_blenderop.match(action)
    if not m_blenderop: return { action }
    okeymap, oop = m_blenderop.group('keymap'), m_blenderop.group('operator')
    tkeymap, top = i18n_translate(okeymap), i18n_translate(oop)
    if keyconfig:
        keyconfigs = [keyconfig]
    else:
        window_manager = bpy.context.window_manager
        keyconfigs = window_manager.keyconfigs
        keyconfigs = [keyconfigs.user]  #[keyconfigs.active, keyconfigs.addon, keyconfigs.user]:
    ret = set()
    for keyconfig in keyconfigs:
        keymap = okeymap if okeymap in keyconfig.keymaps else tkeymap if tkeymap in keyconfig.keymaps else None
        if not keymap: continue
        for kmi in keyconfig.keymaps[keymap].keymap_items:
            if not kmi.active: continue
            if kmi.idname != oop and kmi.idname != top: continue
            ret.add(kmi_details(kmi))
    if not ret:
        print(f'Addon Common Warning: could not translate blender op "{action}" to actions ({okeymap}->{tkeymap}, {oop}->{top})')
    return ret



def strip_mods(action, ctrl=True, shift=True, alt=True, oskey=True, click=True, double_click=True, drag_click=True):
    if action is None: return None
    if ctrl:  action = action.replace('CTRL+',  '')
    if shift: action = action.replace('SHIFT+', '')
    if alt:   action = action.replace('ALT+',   '')
    if oskey: action = action.replace('OSKEY+', '')
    if click: action = action.replace('+CLICK', '')
    if double_click: action = action.replace('+DOUBLE', '')
    if drag_click:   action = action.replace('+DRAG',   '')
    return action

def i18n_translate(text):
    ''' bpy.app.translations.pgettext tries to translate the given parameter '''
    return bpy.app.translations.pgettext(text)


class TimerHandler:
    def __init__(self, wm, win, hz):
        self._wm = wm
        self._timer = wm.event_timer_add(1.0 / hz, window=win)
    def __del__(self):
        self.done()
    def done(self):
        if self._timer:
            self._wm.event_timer_remove(self._timer)
            self._timer = None


class Actions:
    # https://docs.blender.org/api/2.79/bpy.types.KeyMapItems.html
    # https://docs.blender.org/api/blender2.8/bpy.types.KeyMapItems.html
    ndof_actions = {
        'NDOF_MOTION', 'NDOF_BUTTON', 'NDOF_BUTTON_FIT',
        'NDOF_BUTTON_TOP', 'NDOF_BUTTON_BOTTOM', 'NDOF_BUTTON_LEFT', 'NDOF_BUTTON_RIGHT', 'NDOF_BUTTON_FRONT', 'NDOF_BUTTON_BACK',
        'NDOF_BUTTON_ISO1', 'NDOF_BUTTON_ISO2',
        'NDOF_BUTTON_ROLL_CW', 'NDOF_BUTTON_ROLL_CCW',
        'NDOF_BUTTON_SPIN_CW', 'NDOF_BUTTON_SPIN_CCW',
        'NDOF_BUTTON_TILT_CW', 'NDOF_BUTTON_TILT_CCW',
        'NDOF_BUTTON_ROTATE', 'NDOF_BUTTON_PANZOOM',
        'NDOF_BUTTON_DOMINANT',
        'NDOF_BUTTON_PLUS', 'NDOF_BUTTON_MINUS', 'NDOF_BUTTON_ESC',
        'NDOF_BUTTON_ALT', 'NDOF_BUTTON_SHIFT', 'NDOF_BUTTON_CTRL',
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

    timer_actions = {
        'TIMER'
    }

    mousemove_actions = {
        'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE',
    }

    trackpad_actions = {
        'TRACKPADPAN','TRACKPADZOOM',
    }

    modifier_actions = {
        'OSKEY',
        'LEFT_CTRL', 'LEFT_SHIFT', 'LEFT_ALT',
        'RIGHT_CTRL', 'RIGHT_SHIFT', 'RIGHT_ALT',
    }

    special_events = [
        {
            'name': 'navigate',
            'operators': [
                '3D View | view3d.rotate',
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
                '3D View | view3d.view_selected',         # View Selected
                '3D View | view3d.view_center_cursor',    # Center View to Cursor
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
        },
    ]

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

        # set up universal keymaps
        self.keymap = {}  # universal keymap
        self.keymap2 = {} # context keymap
        self.keymap['navigate'] = set()         # filled in more below
        self.keymap['navigate'] |= Actions.trackpad_actions
        self.keymap['navigate'] |= Actions.ndof_actions
        for action in Actions.special_events:
            name, ops = action['name'], action['operators']
            self.keymap.setdefault(name, set())
            for op in ops:
                self.keymap[name] |= translate_blenderop(op)

        self.context = context
        self.area = context.area
        self.screen = context.screen
        self.space = context.space_data
        self.region = context.region
        self.size = Vec2D((context.region.width, context.region.height))
        self.r3d = context.space_data.region_3d
        self.window = context.window

        self.actions_using = set()
        self.actions_pressed = set()
        self.actions_prevtime = dict()  # previous time when action was pressed
        self.now_pressed = {}           # currently pressed keys. key=stripped event type, value=full event type (includes modifiers)
        self.just_pressed = None
        self.last_pressed = None
        self.event_type = None

        self.trackpad = False   # is current action from trackpad?
        self.ndof     = False   # is current action from NDOF?

        # are any of the following modifier keys currently pressed?
        # note: ctrl will be true if either ctrl_left or ctrl_right are true
        self.ctrl        = False
        self.ctrl_left   = False
        self.ctrl_right  = False
        self.shift       = False
        self.shift_left  = False
        self.shift_right = False
        self.alt         = False
        self.alt_left    = False
        self.alt_right   = False

        self.mouse_select     = bprefs.mouse_select()
        self.mouse            = None    # current mouse position
        self.mouse_prev       = None    # previous mouse position
        self.mouse_lastb      = None    # last button pressed on mouse
        self.mousemove        = False   # is the current action a mouse move?
        self.mousemove_prev   = False   # was the previous action a mouse move?
        self.mousedown        = None    # mouse position when a mouse button was pressed
        self.mousedown_left   = None    # mouse position when LMB was pressed
        self.mousedown_middle = None    # mouse position when MMB was pressed
        self.mousedown_right  = None    # mouse position when RMB was pressed
        self.mousedown_drag   = False   # is user dragging?

        self.timer      = False     # is action from timer?
        self.time_delta = 0         # elapsed time since last "step" (units=seconds)
        self.time_last = time.time()

        # IMPORTANT: the following properties are updated external to Actions
        self.hit_pos  = None    # position of raytraced mouse to scene (updated externally!)
        self.hit_norm = None    # normal of raytraced mouse to scene (updated externally!)

    actions_prevtime_default = (0, 0, float('inf'))
    def get_last_press_time(self, event_type):
        return self.actions_prevtime.get(event_type, self.actions_prevtime_default)

    def update(self, context, event, print_actions=False):
        self.unpress()

        self.context = context

        if context.region and hasattr(context.space_data, 'region_3d'):
            self.region = context.region
            self.size = Vec2D((context.region.width, context.region.height))
            self.r3d = context.space_data.region_3d

        event_type, pressed = event.type, event.value=='PRESS'

        if pressed:
            _,prevtime,_ = self.get_last_press_time(event_type)
            curtime = time.time()
            self.actions_prevtime[event_type] = (prevtime, curtime, curtime - prevtime)

        self.event_type = event_type
        self.mousemove_prev = self.mousemove
        self.timer = (event_type in Actions.timer_actions)
        self.mousemove = (event_type in Actions.mousemove_actions)
        self.trackpad = (event_type in Actions.trackpad_actions)
        self.ndof = (event_type in Actions.ndof_actions)
        self.navevent = (event_type in self.keymap['navigate'])

        if event_type in self.ignore_actions: return

        if print_actions and event_type not in self.nonprintable_actions:
            print('Actions.update: (event_type, event.value) =', (event_type, event.value))

        if self.timer:
            time_cur = time.time()
            self.time_delta = self.time_last - time_cur
            self.time_last = time_cur
            self.trackpad = False
            return

        if self.mousemove:
            self.mouse_prev = self.mouse
            self.mouse = Point2D((float(event.mouse_region_x), float(event.mouse_region_y)))
            if self.mousedown is not None:
                if not self.mousedown_drag and (self.mouse - self.mousedown).length > bprefs.mouse_drag():
                    self.mousedown_drag = True
                    if   self.mousedown_left:   event_type = 'LEFTMOUSE'
                    elif self.mousedown_middle: event_type = 'MIDDLEMOUSE'
                    elif self.mousedown_right:  event_type = 'RIGHTMOUSE'
                    self.event_type = event_type
                    pressed = True
                    # print('Actions.update: dragging!')
                else:
                    return
            else:
                self.mousedown_drag = False
                return

        if event_type in self.modifier_actions:
            if event_type == 'OSKEY':
                self.oskey = pressed
            else:
                l = event_type.startswith('LEFT_')
                if event_type.endswith('_CTRL'):
                    self.ctrl = pressed
                    if l: self.ctrl_left = pressed
                    else: self.ctrl_right = pressed
                if event_type.endswith('_SHIFT'):
                    self.shift = pressed
                    if l: self.shift_left = pressed
                    else: self.shift_right = pressed
                if event_type.endswith('_ALT'):
                    self.alt = pressed
                    if l: self.alt_left = pressed
                    else: self.alt_right = pressed
            return # modifier keys do not "fire" pressed events

        mouse_event = event_type in self.mousebutton_actions and not self.navevent
        if mouse_event:
            if pressed:
                if self.mouse_lastb != event_type: self.mousedown_drag = False
                self.mousedown = Point2D((float(event.mouse_region_x), float(event.mouse_region_y)))
                if   event_type == 'LEFTMOUSE':   self.mousedown_left   = self.mousedown
                elif event_type == 'MIDDLEMOUSE': self.mousedown_middle = self.mousedown
                elif event_type == 'RIGHTMOUSE':  self.mousedown_right  = self.mousedown
                self.mouse_lastb = event_type

        ftype = kmi_details(event, event_type=event_type, drag_click=self.mousedown_drag and mouse_event)
        if pressed:
            # if event_type not in self.now_pressed:
            #     self.just_pressed = ftype
            self.just_pressed = ftype
            if 'WHEELUPMOUSE' in ftype or 'WHEELDOWNMOUSE' in ftype:
                # mouse wheel actions have no release, so handle specially
                self.just_pressed = ftype
            self.now_pressed[event_type] = ftype
            self.last_pressed = ftype
        else:
            if event_type in self.now_pressed:
                if event_type in Actions.mousebutton_actions and not self.mousedown_drag:
                    _,_,deltatime = self.get_last_press_time(event_type)
                    single = (deltatime > bprefs.mouse_doubleclick()) or (self.mouse_lastb != event_type)
                    self.just_pressed = kmi_details(event, event_type=event_type, click=single, double_click=not single)
                else:
                    del self.now_pressed[event_type]

        if mouse_event and not pressed:
            self.mousedown = None
            self.mousedown_left = None
            self.mousedown_middle = None
            self.mousedown_right = None
            self.mousedown_drag = False

        if print_actions and event_type not in self.nonprintable_actions:
            print('Actions.update: (ftype, pressed) =', (ftype, pressed), self.just_pressed, self.now_pressed, self.last_pressed)

    def convert(self, actions):
        t = type(actions)
        if   t is set:  pass                    # already a set; no need to do anything
        elif t is str:  actions = { actions }   # passed only a string
        elif t is list: actions = set(actions)  # prevent duplicate actions by converting to set
        else:           actions = { actions }   # catch all (should not happen)
        ret = set()
        for action in actions:
            ret |= (self.keymap.get(action, set()) | self.keymap2.get(action, set())) or { action }
        return ret

    def to_human_readable(self, actions, join=',', onlyfirst=None):
        ret = set()
        for action in self.convert(actions):
            for kmi2hr in kmi_to_humanreadable:
                for k,v in kmi2hr.items():
                    action = action.replace(k, v)
            ret.add(action)
        ret = sorted(ret)
        if onlyfirst is not None: ret = ret[:onlyfirst]
        return join.join(ret)


    def unuse(self, actions):
        actions = self.convert(actions)
        keys = [k for k,v in self.now_pressed.items() if v in actions]
        # print('Actions.unuse', actions, self.now_pressed, keys)
        for k in keys: del self.now_pressed[k]
        # print('unuse', self.just_pressed)
        self.mousedown = None
        self.mousedown_left = None
        self.mousedown_middle = None
        self.mousedown_right = None
        self.mousedown_drag = False
        self.unpress()

    def unpress(self):
        # print('unpress', self.just_pressed)
        # for entry in enumerate(inspect.stack()):
        #     print('  %s' % str(entry))
        if not self.just_pressed: return
        if '+CLICK' in self.just_pressed:
            del self.now_pressed[strip_mods(self.just_pressed)]
        elif '+DOUBLE' in self.just_pressed:
            del self.now_pressed[strip_mods(self.just_pressed)]
        self.just_pressed = None

    def using(self, actions, using_all=False, ignoremods=False, ignorectrl=False, ignoreshift=False, ignorealt=False, ignoreoskey=False, ignoremulti=False, ignoreclick=False, ignoredouble=False, ignoredrag=False):
        if actions is None: return False
        if ignoremods: ignorectrl,ignoreshift,ignorealt,ignoreoskey = True,True,True,True
        if ignoremulti: ignoreclick,ignoredouble,ignoredrag = True,True,True
        actions = [strip_mods(p, ctrl=ignorectrl, shift=ignoreshift, alt=ignorealt, oskey=ignoreoskey, click=ignoreclick, double_click=ignoredouble, drag_click=ignoredrag) for p in self.convert(actions)]
        quantifier_fn = all if using_all else any
        return quantifier_fn(
            strip_mods(p, ctrl=ignorectrl, shift=ignoreshift, alt=ignorealt, oskey=ignoreoskey, click=ignoreclick, double_click=ignoredouble, drag_click=ignoredrag) in actions
            for p in self.now_pressed.values()
        )

    def using_onlymods(self, actions):
        if actions is None: return False
        def action_good(action):
            for p in action.split('+'):
                if p == 'CTRL' and not self.ctrl: return False
                if p == 'SHIFT' and not self.shift: return False
                if p == 'ALT' and not self.alt: return False
            return True
        return any(action_good(action) for action in self.convert(actions))

    def navigating(self):
        actions = self.convert('navigate')
        if self.trackpad: return True
        if self.ndof: return True
        if any(p in actions for p in self.now_pressed.values()): return True
        return False

    def pressed(self, actions, unpress=True, ignoremods=False, ignorectrl=False, ignoreshift=False, ignorealt=False, ignoreoskey=False, ignoremulti=False, ignoreclick=False, ignoredouble=False, ignoredrag=False, debug=False):
        if actions is None: return False
        if ignoremods: ignorectrl,ignoreshift,ignorealt,ignoreoskey = True,True,True,True
        if ignoremulti: ignoreclick,ignoredouble,ignoredrag = True,True,True
        if debug: print('Actions.pressed 0: actions =', actions)
        actions = self.convert(actions)
        if debug: print('Actions.pressed 1: actions =', actions)
        just_pressed = strip_mods(self.just_pressed, ctrl=ignorectrl, shift=ignoreshift, alt=ignorealt, oskey=ignoreoskey, click=ignoreclick, double_click=ignoredouble, drag_click=ignoredrag)
        if debug: print('Actions.pressed 2: just_pressed =', just_pressed, self.just_pressed, ', actions =', actions)
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
        if ftype is None: return ''
        #assert ftype in kmi_to_char, 'Trying to convert unhandled key "%s"' % str(self.just_pressed)
        return kmi_to_char.get(ftype, None)

    def start_timer(self, hz):
        return TimerHandler(self.context.window_manager, self.context.window, hz)


class ActionHandler:
    _actions = None
    def __init__(self, context, keymap={}):
        if not ActionHandler._actions:
            ActionHandler._actions = Actions.get_instance(context)
        _keymap = {}
        for (k,v) in keymap.items():
            if type(v) is not set and type(v) is not list: v = { v }
            _keymap[k] = { op for action in v for op in translate_blenderop(action) }
        self.__dict__['_keymap'] = _keymap
    def __getattr__(self, key):
        ActionHandler._actions.keymap2 = self._keymap
        return getattr(ActionHandler._actions, key)
    def __setattr__(self, key, value):
        ActionHandler._actions.keymap2 = self._keymap
        return setattr(ActionHandler._actions, key, value)
    def done(self):
        ActionHandler._actions.done()
        ActionHandler._actions = None





