'''
Copyright (C) 2021 CG Cookie
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
        'SHIFT+PERIOD': '>',
        'SHIFT+PLUS':   '+',
        'SHIFT+MINUS':  '_',
        'SHIFT+SLASH':  '?',
        'SHIFT+BACK_SLASH':   '|',
        'SHIFT+EQUAL':        '+',
        'SHIFT+SEMI_COLON':   ':', 'SHIFT+COMMA':         '<',
        'SHIFT+LEFT_BRACKET': '{', 'SHIFT+RIGHT_BRACKET': '}',
        'SHIFT+QUOTE':        '"', 'SHIFT+ACCENT_GRAVE':  '~',
    },{
        # top-row and numpad numbers
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

        # operators and numpad operators
        'PERIOD': '.', 'NUMPAD_PERIOD':  'Num.',
        'PLUS':   '+', 'NUMPAD_PLUS':    'Num+',
        'MINUS':  '-', 'NUMPAD_MINUS':   'Num-',
        'SLASH':  '/', 'NUMPAD_SLASH':   'Num/',
                       'NUMPAD_ASTERIX': 'Num*',

        # characters that are easier to read as symbols than as their name
        'SPACE':        ' ', 'EQUAL':        '=',
        'SEMI_COLON':   ';', 'COMMA':         ',',
        'LEFT_BRACKET': '[', 'RIGHT_BRACKET': ']',
        'QUOTE':        "'", 'ACCENT_GRAVE':  '&#96;', #'`',
        'BACK_SLASH':   '\\',

        # non-printable characters
        'ESC': 'Escape',
        'BACK_SPACE': 'Backspace',
        'RET': 'Enter', 'NUMPAD_ENTER': 'NumEnter',
        'HOME': 'Home', 'END': 'End',
        'LEFT_ARROW': 'ArrowLeft', 'RIGHT_ARROW': 'ArrowRight',
        'UP_ARROW': 'ArrowUp', 'DOWN_ARROW': 'ArrowDown',
        'PAGE_UP': 'PageUp', 'PAGE_DOWN': 'PageDown',
        'DEL': 'Delete',
        'TAB': 'Tab',

        # mouse actions
        'LEFTMOUSE': 'LMB', 'MIDDLEMOUSE': 'MMB', 'RIGHTMOUSE': 'RMB',
        'WHEELUPMOUSE': 'WheelUp', 'WHEELDOWNMOUSE': 'WheelDown',

        # postfix modifiers
        'DRAG': 'Drag', 'DOUBLE': 'Double', 'CLICK': 'Click',
    }
]

# platform-specific prefix modifiers
if platform.system() == 'Darwin':
    kmi_to_humanreadable += [{
        'SHIFT': '⇧',
        'CTRL':  '^',
        'ALT':   '⌥',
        'OSKEY': '⌘',
    }]
else:
    kmi_to_humanreadable += [{
        'SHIFT': 'Shift',
        'CTRL':  'Ctrl',
        'ALT':   'Alt',
        'OSKEY': 'OSKey',
    }]


# reversed human readable dict
humanreadable_to_kmi = {
    v:k
    for s in kmi_to_humanreadable
    for (k,v) in s.items()
} # | {'Space': 'SPACE'}  # does not work in Blender 2.92
humanreadable_to_kmi['Space'] = 'SPACE'


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
    for action in actions:
        kmi = humanreadable_to_kmi.get(action, action)
        if platform.system() == 'Darwin':
            kmi = kmi.replace('^+',  'CTRL+')
            kmi = kmi.replace('⇧+', 'SHIFT+')
            kmi = kmi.replace('⌥+',  'ALT+')
            kmi = kmi.replace('⌘+', 'OSKEY+')
        else:
            kmi = kmi.replace('Ctrl+',  'CTRL+')
            kmi = kmi.replace('Shift+', 'SHIFT+')
            kmi = kmi.replace('Alt+',   'ALT+')
            kmi = kmi.replace('Cmd+',   'OSKEY+')
        ret.append(kmi)
    return ret