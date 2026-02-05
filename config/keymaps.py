'''
Copyright (C) 2026 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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


altered_keymap_items = set()


def alter_user_keymaps(context):
    user_keyconfigs = context.window_manager.keyconfigs.user
    for keymap in user_keyconfigs.keymaps:
        for km_item in keymap.keymap_items:
            # Switches alternate pick shortest path behavior since default is blocked by RF
            if (km_item.idname == 'mesh.shortest_path_pick' and
                km_item.ctrl == True and km_item.shift == True and
                km_item.properties['use_fill'] == True
            ):
                altered_keymap_items.add(km_item)
                km_item.properties['use_fill'] = False
                return


def restore_user_keymaps(context):
    for km_item in altered_keymap_items:
        if km_item.idname == 'mesh.shortest_path_pick':
            km_item.properties['use_fill'] = True
