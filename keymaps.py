'''
Copyright (C) 2018 CG Cookie
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


default_rf_keymaps = {
    'toggle full area': {'CTRL+UP_ARROW', 'CTRL+DOWN_ARROW'},

    'action': {'LEFTMOUSE'},
    'action alt0': {'SHIFT+LEFTMOUSE'},
    'action alt1': {'CTRL+SHIFT+LEFTMOUSE'},

    'select': {'RIGHTMOUSE'},   # TODO: update based on bpy.context.user_preferences.inputs.select_mouse
    'select add': {'SHIFT+RIGHTMOUSE'},
    'select smart': {'CTRL+RIGHTMOUSE'},
    'select smart add': {'CTRL+SHIFT+RIGHTMOUSE'},
    'select all': {'A'},

    'general help': {'F1'},
    'tool help': {'F2'},

    'autosave': {'TIMER_AUTOSAVE'},

    'cancel': {'ESC', 'RIGHTMOUSE'},
    'cancel no select': {'ESC'},
    'confirm': {'RET', 'NUMPAD_ENTER', 'LEFTMOUSE'},
    'done': {'ESC'}, #, 'RET', 'NUMPAD_ENTER'},

    'undo': {'CTRL+Z'},
    'redo': {'CTRL+SHIFT+Z'},

    'edit mode': {'TAB'},

    'insert': {'CTRL+LEFTMOUSE'},
    'insert alt0': {'SHIFT+LEFTMOUSE'},
    'insert alt1': {'CTRL+SHIFT+LEFTMOUSE'},

    'grab': {'G'},
    'delete': {'X','DELETE'},

    'increase count': {'EQUAL','SHIFT+EQUAL','SHIFT+UP_ARROW', 'SHIFT+WHEELUPMOUSE'},
    'decrease count': {'MINUS','SHIFT+DOWN_ARROW','SHIFT+WHEELDOWNMOUSE'},

    # contours
    'shift': {'S'},             # rotation of loops
    'rotate': {'SHIFT+S'},

    # loops
    'slide': {'S'},

    # patches
    'fill': {'F'},

    # widget
    'brush radius': {'F'},
    'brush size': {'F'},
    'brush falloff': {'CTRL+F'},
    'brush strength': {'SHIFT+F'},

    # shortcuts to tools
    'contours tool': {'Q'},
    'polystrips tool': {'W'},
    'polypen tool': {'E'},
    'relax tool': {'R'},
    'move tool': {'T'},
    'loops tool': {'Y'},
    'patches tool': {'U'},
    'strokes tool': {'I'},
}
