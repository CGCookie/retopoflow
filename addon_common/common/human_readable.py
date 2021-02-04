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
        'QUOTE':        "'", 'ACCENT_GRAVE':  '&#96;', #'`',
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

html_char = {
    '&#96;': '`',
}

def convert_actions_to_human_readable(actions, join=',', onlyfirst=None, translate_html_char=False):
    ret = set()
    for action in actions:
        for kmi2hr in kmi_to_humanreadable:
            for k,v in kmi2hr.items():
                action = action.replace(k, v)
        ret.add(action)
    if translate_html_char:
        for k,v in html_char.items():
            ret = {r.replace(k,v) for r in ret}
    ret = sorted(ret)
    if onlyfirst is not None: ret = ret[:onlyfirst]
    return join.join(ret)
