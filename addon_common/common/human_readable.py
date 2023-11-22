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

import platform

# these are separated into a list so that "SHIFT+ZERO" (for example) is handled
# before the "SHIFT" gets turned into "Shift"
kmi_to_humanreadable = [
    {
        # shifted top-row numbers
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

        # shifted punctuation
        'SHIFT+PERIOD':        '>',
        'SHIFT+PLUS':          '+',
        'SHIFT+MINUS':         '_',
        'SHIFT+SLASH':         '?',
        'SHIFT+BACK_SLASH':    '|',
        'SHIFT+EQUAL':         '+',
        'SHIFT+SEMI_COLON':    ':',
        'SHIFT+COMMA':         '<',
        'SHIFT+LEFT_BRACKET':  '{',
        'SHIFT+RIGHT_BRACKET': '}',
        'SHIFT+QUOTE':         '"',
        'SHIFT+ACCENT_GRAVE':  '~',
    },{
        # numpad numbers
        'NUMPAD_PERIOD':  'Num.',
        'NUMPAD_PLUS':    'Num+',
        'NUMPAD_MINUS':   'Num-',
        'NUMPAD_SLASH':   'Num/',
        'NUMPAD_ASTERIX': 'Num*',

        # numpad operators
        'NUMPAD_PERIOD':  'Num.',
        'NUMPAD_PLUS':    'Num+',
        'NUMPAD_MINUS':   'Num-',
        'NUMPAD_SLASH':   'Num/',
        'NUMPAD_ASTERIX': 'Num*',

        # numpad enter
        'NUMPAD_ENTER': 'NumEnter',
    },{
        'BACK_SLASH': '\\',
    },{
        # top-row numbers
        'ZERO':   '0',
        'ONE':    '1',
        'TWO':    '2',
        'THREE':  '3',
        'FOUR':   '4',
        'FIVE':   '5',
        'SIX':    '6',
        'SEVEN':  '7',
        'EIGHT':  '8',
        'NINE':   '9',

        # operators
        'PERIOD': '.',
        'PLUS':   '+',
        'MINUS':  '-',
        'SLASH':  '/',

        # characters that are easier to read as symbols than as their name
        'EQUAL':         '=',
        'SEMI_COLON':    ';',
        'COMMA':         ',',
        'LEFT_BRACKET':  '[',
        'RIGHT_BRACKET': ']',
        'QUOTE':         "'",
        'ACCENT_GRAVE':  '&#96;', #'`',

        # non-printable characters
        'ESC':         'Escape',
        'BACK_SPACE':  'Backspace',
        'RET':         'Enter',
        'HOME':        'Home',
        'END':         'End',
        'LEFT_ARROW':  'ArrowLeft',
        'RIGHT_ARROW': 'ArrowRight',
        'UP_ARROW':    'ArrowUp',
        'DOWN_ARROW':  'ArrowDown',
        'PAGE_UP':     'PageUp',
        'PAGE_DOWN':   'PageDown',
        'INSERT':      'Insert',
        'DEL':         'Delete',
        'TAB':         'Tab',

        # mouse actions
        'LEFTMOUSE':      'LMB',
        'MIDDLEMOUSE':    'MMB',
        'RIGHTMOUSE':     'RMB',
        'WHEELUPMOUSE':   'WheelUp',
        'WHEELDOWNMOUSE': 'WheelDown',

        # postfix modifiers
        'DRAG':   'Drag',
        'DOUBLE': 'Double',
        'CLICK':  'Click',
    },{
        'SPACE': 'Space',
    }
]

# platform-specific prefix modifiers
if platform.system() == 'Darwin':
    kmi_to_humanreadable += [{
        'SHIFT': '⇧ Shift',
        'CTRL':  '^ Ctrl',
        'ALT':   '⌥ Opt',
        'OSKEY': '⌘ Cmd',
    }]
else:
    kmi_to_humanreadable += [{
        'SHIFT': 'Shift',
        'CTRL':  'Ctrl',
        'ALT':   'Alt',
        'OSKEY': 'OSKey',
    }]


# reversed human readable dict
humanreadable_to_kmi = [ { v:k for (k,v) in s.items() } for s in reversed(kmi_to_humanreadable) ]
# | {'Space': 'SPACE'}  # does not work in Blender 2.92
humanreadable_to_kmi += [{'Space': 'SPACE'}]


html_char = {
    '&#96;': '`',
}

visible_char = {
    ' ': 'Space',
}

def convert_actions_to_human_readable(actions, *, sep=',', onlyfirst=None, translate_html_char=False, visible=False):
    ret = set()
    if type(actions) is str: actions = {actions}
    for action in actions:
        for kmi2hr in kmi_to_humanreadable:
            for k,v in kmi2hr.items():
                action = action.replace(k, v)
        ret.add(action)
    if visible:
        ret = { visible_char.get(r, r) for r in ret }
    if translate_html_char:
        for k,v in html_char.items():
            ret = {r.replace(k,v) for r in ret}
    ret = sorted(ret)
    if onlyfirst is not None: ret = ret[:onlyfirst]
    return sep.join(ret)

def convert_human_readable_to_actions(actions):
    ret = []
    if type(actions) is str: actions = [actions]
    for action in actions:
        if platform.system() == 'Darwin':
            action = action.replace('^ Ctrl+',  'CTRL+')
            action = action.replace('⇧ Shift+', 'SHIFT+')
            action = action.replace('⌥ Opt+',   'ALT+')
            action = action.replace('⌘ Cmd+',   'OSKEY+')
        else:
            action = action.replace('Ctrl+',  'CTRL+')
            action = action.replace('Shift+', 'SHIFT+')
            action = action.replace('Alt+',   'ALT+')
            action = action.replace('Cmd+',   'OSKEY+')
        for hr2kmi in humanreadable_to_kmi:
            kmi = hr2kmi.get(action, action)
        ret.append(kmi)
    return ret
