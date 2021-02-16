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

from ..addon_common.common.blender_preferences import mouse_select


'''
Standard US 101 QWERTY Keyboard
+-----------------------------------------------------------+
| ESC  F1 F2 F3 F4  F5 F6 F7 F8  F9 F10 F11 F12             |
| `~  1 2 3 4 5 6 7 8 9 0 - = BKSP  INS HOM PUP  NL / * -   |
| TAB  Q W E R T Y U I O P [ ] \\   DEL END PDN   7 8 9 +   |
| CAPS  A S D F G H J K L ; ' ENTR                4 5 6     |
| SHFT   Z X C V B N M , . /  SHFT      UP        1 2 3 ENT |
| CTRL OSK ALT   SPACE    ALT CTRL   LT DN RT     0   .     |
+-----------------------------------------------------------+
'''


default_rf_keymaps = {
    'toggle full area': {'CTRL+UP_ARROW', 'CTRL+DOWN_ARROW'},

    # when mouse is hovering a widget or selected geometry, actions take precedence
    'action': {'LEFTMOUSE+DRAG'},
    'action alt0': {'SHIFT+LEFTMOUSE'},
    'action alt1': {'CTRL+SHIFT+LEFTMOUSE'},

    # selections filled in later
    'select single': {},
    'select single add': {},
    'select smart': {},
    'select smart add': {},
    'select paint': {},
    'select paint add': {},

    'select all': {'A'},
    'select invert': {'CTRL+I'},
    'deselect all': {'ALT+A'},

    # various help
    'all help': {'SHIFT+F1'},
    'general help': {'F1'},
    'tool help': {'F2'},

    'toggle ui': {'F9'},

    'autosave': {'TIMER_AUTOSAVE'},

    'cancel': {'ESC', 'RIGHTMOUSE'},
    'confirm': {'RET', 'NUMPAD_ENTER', 'LEFTMOUSE+CLICK'},

    'done': {'TAB'},
    'done alt0': {'ESC'},

    'insert': {'CTRL+LEFTMOUSE', 'CTRL+LEFTMOUSE+DOUBLE'},
    'insert alt0': {'SHIFT+LEFTMOUSE', 'SHIFT+LEFTMOUSE+DOUBLE'},
    'insert alt1': {'CTRL+SHIFT+LEFTMOUSE', 'CTRL+SHIFT+LEFTMOUSE+DOUBLE'},
    'quick insert': {'LEFTMOUSE'},

    # general commands
    'grab': {'G'},
    'rotate': {'R'},
    'scale': {'S'},
    'delete': {'X', 'DEL', 'BACK_SPACE'},
    'delete pie menu': {'CTRL+X', 'CTRL+DEL', 'CTRL+BACK_SPACE'},
    'smooth edge flow': {'SHIFT+S'},

    'hide selected': {'H'},
    'hide unselected': {'SHIFT+H'},
    'reveal hidden': {'ALT+H'},

    'increase count': {'EQUAL','SHIFT+EQUAL','SHIFT+UP_ARROW', 'SHIFT+WHEELUPMOUSE'},
    'decrease count': {'MINUS','SHIFT+DOWN_ARROW','SHIFT+WHEELDOWNMOUSE'},

    # contours
    'rotate plane': {'R'},              # rotate loops about contour plane normal
    'rotate screen': {'R', 'SHIFT+R'},  # rotate loops in screen space.  note: R only works when rotating in plane

    # loops
    'slide': {'G'},     # slide loop

    # patches
    'fill': {'F', 'RET', 'NUMPAD_ENTER'},

    # knife
    'knife reset': {'E'},

    # grease pencil
    'grease clear': {'C'},

    # widget
    'brush': {'LEFTMOUSE', 'LEFTMOUSE+DOUBLE', 'LEFTMOUSE+DRAG'},
    'brush alt': {'SHIFT+LEFTMOUSE', 'SHIFT+LEFTMOUSE+DOUBLE', 'SHIFT+LEFTMOUSE+DRAG'},
    'brush radius': {'F'},
    'brush falloff': {'CTRL+F'},
    'brush strength': {'SHIFT+F'},

    # pie menu
    'pie menu': {'Q'},
    'pie menu alt0': {'SHIFT+Q'},
    'pie menu confirm': {'LEFTMOUSE+CLICK', 'LEFTMOUSE+DRAG'},

    # shortcuts to tools
    'contours tool': {'ONE', 'CTRL+ALT+C'},
    'polystrips tool': {'TWO', 'CTRL+ALT+P'},
    'strokes tool': {'THREE', 'CTRL+ALT+B'},
    'patches tool': {'FOUR', 'CTRL+ALT+F'},
    'polypen tool': {'FIVE', 'CTRL+ALT+V'},
    'knife tool': {'CTRL+FIVE', 'CTRL+K'},
    'knife quick': {'K'},
    'loops tool': {'SIX', 'CTRL+ALT+Q'},
    'loops quick': {'CTRL+R'},
    'tweak tool': {'SEVEN', 'CTRL+ALT+G'},
    'tweak quick': {'C'},
    'relax tool': {'EIGHT', 'CTRL+ALT+X'},
    'relax quick': {'Z'},
    'stretch tool': {'NINE'},          # not ported from rf279, yet
    'grease pencil tool': {'ZERO'},    # not ported from rf279, yet
}

left_rf_keymaps = {
    'select single': {'LEFTMOUSE+CLICK'},
    'select single add': {'SHIFT+LEFTMOUSE+CLICK'},
    'select smart': {'LEFTMOUSE+DOUBLE'},
    'select smart add': {'SHIFT+LEFTMOUSE+DOUBLE'},
    'select paint': {'LEFTMOUSE+DRAG'},
    'select paint add': {'SHIFT+LEFTMOUSE+DRAG'},
}

right_rf_keymaps = {
    'select single': {'RIGHTMOUSE+CLICK'},
    'select single add': {'SHIFT+RIGHTMOUSE+CLICK'},
    'select smart': {'CTRL+RIGHTMOUSE', 'RIGHTMOUSE+DOUBLE'},
    'select smart add': {'CTRL+SHIFT+RIGHTMOUSE', 'SHIFT+RIGHTMOUSE+DOUBLE'},
    'select paint': {'RIGHTMOUSE+DRAG'},
    'select paint add': {'SHIFT+RIGHTMOUSE+DRAG'},
}

def get_keymaps():
    keymap = default_rf_keymaps
    keymap_replace = left_rf_keymaps if mouse_select() == 'LEFT' else right_rf_keymaps
    for k,v in keymap_replace.items():
        keymap[k] = v
    return keymap
