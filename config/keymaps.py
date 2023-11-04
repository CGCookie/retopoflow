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


import os
import re
import copy
import json

from .options import options
from ..addon_common.common.blender_preferences import mouse_select
from ..addon_common.common.decorators import add_cache


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


################################################################
# start keymaps
# the marker above is used for prep_help_for_online.py
# DO NOT change

default_rf_keymaps = {
    # always pass these actions on to Blender (set in keymap editor only)
    'blender passthrough': [],

    'toggle full area': ['CTRL+UP_ARROW', 'CTRL+DOWN_ARROW'],

    # when mouse is hovering a widget or selected geometry, actions take precedence
    'action': ['LEFTMOUSE+DRAG'],
    'action alt0': ['SHIFT+LEFTMOUSE'],
    'action alt1': ['CTRL+SHIFT+LEFTMOUSE'],

    # selections filled in later
    'select single': [],
    'select single add': [],
    'select smart': [],
    'select smart add': [],
    'select paint': [],
    'select paint add': [],
    'select path add': [],
    'select linked': ['CTRL+L'],
    'select linked mouse': ['L'],
    'deselect linked mouse': ['SHIFT+L'],

    'select all': ['A'],
    'select invert': ['CTRL+I'],
    'deselect all': ['ALT+A'],

    # various help
    'all help': ['SHIFT+F1'],
    'general help': ['F1'],
    'tool help': ['F2'],

    'toggle ui': ['F9'],
    'reload css': ['F12'],

    'autosave': ['TIMER_AUTOSAVE'],

    'cancel': ['ESC', 'RIGHTMOUSE'],
    'confirm': ['RET', 'NUMPAD_ENTER', 'LEFTMOUSE+CLICK'],
    'confirm quick': ['SPACE'],
    'confirm drag': ['LEFTMOUSE+DRAG'],

    'done': ['TAB'],
    'done alt0': ['ESC'],

    'insert': ['CTRL+LEFTMOUSE', 'CTRL+LEFTMOUSE+DOUBLE'],
    'quick insert': ['LEFTMOUSE'],

    # general commands
    'grab': ['G'],
    'rotate': ['R'],
    'scale': ['S'],
    'delete': ['X', 'DEL', 'BACK_SPACE'],
    'delete pie menu': ['CTRL+X', 'CTRL+DEL', 'CTRL+BACK_SPACE'],
    'merge': ['M'],
    'smooth edge flow': ['SHIFT+S'],
    'rip': ['V'],
    'rip fill': ['ALT+V'],

    'hide selected': ['H'],
    'hide unselected': ['SHIFT+H'],
    'reveal hidden': ['ALT+H'],

    'increase count': ['EQUAL','SHIFT+EQUAL','SHIFT+UP_ARROW', 'SHIFT+WHEELUPMOUSE', 'PLUS'],
    'decrease count': ['MINUS','SHIFT+DOWN_ARROW','SHIFT+WHEELDOWNMOUSE'],

    # contours
    'rotate plane': ['R'],              # rotate loops about contour plane normal
    'rotate screen': ['R', 'SHIFT+R'],  # rotate loops in screen space.  note: R only works when rotating in plane

    # loops
    'slide': ['G'],     # slide loop

    # patches
    'fill': ['F', 'RET', 'NUMPAD_ENTER'],

    # knife
    'knife reset': ['E'],

    # grease pencil
    'grease clear': ['C'],

    # widget
    'brush': ['LEFTMOUSE', 'LEFTMOUSE+DOUBLE', 'LEFTMOUSE+DRAG'],
    'brush alt': ['SHIFT+LEFTMOUSE', 'SHIFT+LEFTMOUSE+DOUBLE', 'SHIFT+LEFTMOUSE+DRAG'],
    'brush radius': ['F'],
    'brush radius increase': ['RIGHT_BRACKET', 'CTRL+RIGHT_BRACKET'],
    'brush radius decrease': ['LEFT_BRACKET', 'CTRL+LEFT_BRACKET'],
    'brush falloff': ['CTRL+F'],
    'brush strength': ['SHIFT+F'],

    # pie menu
    'pie menu': ['Q', 'ACCENT_GRAVE'],
    'pie menu alt0': ['SHIFT+Q', 'SHIFT+ACCENT_GRAVE'],
    'pie menu confirm': ['LEFTMOUSE+CLICK', 'LEFTMOUSE+DRAG'],

    # pinning vertices
    'pin': ['P'],
    'unpin': ['ALT+P'],
    'unpin all': ['SHIFT+ALT+P'],

    # seams
    'mark seam': ['CTRL+E'],
    'clear seam': ['CTRL+SHIFT+E'],

    # shortcuts to tools
    'contours tool': ['ONE', 'CTRL+ALT+C'],
    'polystrips tool': ['TWO', 'CTRL+ALT+P'],
    'strokes tool': ['THREE', 'CTRL+ALT+B'],
    'patches tool': ['FOUR', 'CTRL+ALT+F'],
    'polypen tool': ['FIVE', 'CTRL+ALT+V'],
    'knife tool': ['CTRL+FIVE', 'CTRL+K'],
    'knife quick': ['K'],
    'loops tool': ['SIX', 'CTRL+ALT+Q'],
    'loops quick': ['CTRL+R'],
    'tweak tool': ['SEVEN', 'CTRL+ALT+G'],
    'tweak quick': ['C'],
    'relax tool': ['EIGHT', 'CTRL+ALT+X'],
    'relax quick': ['Z'],
    'stretch tool': ['NINE'],          # not ported from rf279, yet
    'grease pencil tool': ['ZERO'],    # not ported from rf279, yet

    'select tool':    ['W'],
    'select quick':   ['B'],
}

left_rf_keymaps = {
    'select single': ['LEFTMOUSE+CLICK'],
    'select single add': ['SHIFT+LEFTMOUSE+CLICK'],
    'select smart': ['LEFTMOUSE+DOUBLE'],
    'select smart add': ['SHIFT+LEFTMOUSE+DOUBLE'],
    'select paint': ['LEFTMOUSE+DRAG'],
    'select paint add': ['SHIFT+LEFTMOUSE+DRAG'],
    'select path add': ['CTRL+SHIFT+LEFTMOUSE+CLICK'],
    'select box':     ['LEFTMOUSE+DRAG'],
    'select box del': ['CTRL+LEFTMOUSE+DRAG'],
    'select box add': ['SHIFT+LEFTMOUSE+DRAG'],
}

right_rf_keymaps = {
    'select single': ['RIGHTMOUSE+CLICK'],
    'select single add': ['SHIFT+RIGHTMOUSE+CLICK'],
    'select smart': ['CTRL+RIGHTMOUSE', 'RIGHTMOUSE+DOUBLE'],
    'select smart add': ['CTRL+SHIFT+RIGHTMOUSE', 'SHIFT+RIGHTMOUSE+DOUBLE'],
    'select paint': ['RIGHTMOUSE+DRAG'],
    'select paint add': ['SHIFT+RIGHTMOUSE+DRAG'],
    'select path add': ['CTRL+SHIFT+RIGHTMOUSE+CLICK'],
    'select box':     ['RIGHTMOUSE+DRAG'],
    'select box del': ['CTRL+RIGHTMOUSE+DRAG'],
    'select box add': ['SHIFT+RIGHTMOUSE+DRAG'],
}

# end keymaps
# the marker above used for prep_help_for_online.py
# DO NOT CHANGE
################################################################


@add_cache('keymap', None)
@add_cache('orig', None)
def get_keymaps(*, force_reload=False):
    force_reload |= get_keymaps.keymap is None
    if force_reload:
        keymap = copy.deepcopy(default_rf_keymaps)
        keymap_lr = left_rf_keymaps if mouse_select() == 'LEFT' else right_rf_keymaps
        keymap |= { k:list(v) for (k, v) in keymap_lr.items() }
        get_keymaps.orig = copy.deepcopy(keymap)

        # apply custom keymaps
        path_custom = options.get_path('keymaps filename')
        print(f'RetopoFlow keymaps path: {path_custom}')
        if os.path.exists(path_custom):
            try:
                keymap_custom = json.load(open(path_custom, 'rt'))
                keymap |= { k:list(v) for (k, v) in keymap_custom.items() }
            except Exception as e:
                print('Exception caught while trying to read custom keymaps')
                print(str(e))

        # apply substitution
        re_sub = re.compile(r'\{(?P<name>[^}]+)\}')
        new_keymap = {}
        all_done = False
        while not all_done:
            all_done = True
            for name, keys in keymap.items():
                work = list(keys)
                new_keys = []
                while work:
                    key = work.pop(0)
                    m = re_sub.search(key)
                    if not m:
                        new_keys.append(key)
                    else:
                        all_done = False
                        sname = m.group('name')
                        assert sname in keymap, f'Could not find name {sname} in keymap'
                        for (i, newkey) in enumerate(keymap[sname]):
                            work.insert(i, key[:m.start()] + newkey + key[m.end():])
                new_keymap[name] = new_keys
            keymap = new_keymap

        get_keymaps.keymap = keymap
    return get_keymaps.keymap

def reset_all_keymaps():
    get_keymaps(force_reload=True)
    keymap, orig = get_keymaps.keymap, get_keymaps.orig
    for a in keymap.keys(): keymap[a] = list(orig[a])

def reset_keymap(action):
    get_keymaps(force_reload=True)
    get_keymaps.keymap[action] = list(get_keymaps.orig[action])

def save_custom_keymaps():
    keymap, orig = get_keymaps.keymap, get_keymaps.orig
    custom = {}
    for k in keymap.keys():
        if set(keymap[k]) == set(orig.get(k,[])): continue
        # print(f'keymap["{k}"] = {keymap[k]}')
        # print(f'orig["{k}"]   = {orig[k]}')
        custom[k] = keymap[k]
    path_custom = options.get_path('keymaps filename')
    json.dump(custom, open(path_custom, 'wt'))
    pass

