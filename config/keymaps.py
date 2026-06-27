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

import bpy
from bpy.types import Context, KeyMapItem

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


altered_keymap_items = []

#TODO: Cleanup: unify the functions here with those in addon_common/common/useractions.py

def store_keymap_item(km_item, altered):
    kmi = {
        'idname': km_item.idname,
        'type': km_item.type,
        'value': km_item.value,
        'any': km_item.any,
        'shift': km_item.shift,
        'ctrl': km_item.ctrl,
        'alt': km_item.alt,
        'oskey': km_item.oskey,
        'key_modifier': km_item.key_modifier,
        'altered': altered
    }
    if hasattr(km_item, 'hyper'):
        kmi['hyper'] = km_item.hyper

    altered_keymap_items.append(kmi)


def is_keymap_item_matching(km_item, saved_item):
    return (km_item.idname == saved_item['idname'] and
            km_item.type == saved_item['type'] and
            km_item.value == saved_item['value'] and
            km_item.any == saved_item['any'] and
            km_item.shift == saved_item['shift'] and
            km_item.ctrl == saved_item['ctrl'] and
            km_item.alt == saved_item['alt'] and
            km_item.oskey == saved_item['oskey'] and
            km_item.key_modifier == saved_item['key_modifier'] and
            (not hasattr(km_item, 'hyper') or km_item.hyper == saved_item['hyper'])
    )


# Returns the first matching keymap item. There could be multiple!
# Add arguments to further filter if needed
def get_user_keymap_item(context : Context, idname : str) -> KeyMapItem | None:
    user = context.window_manager.keyconfigs.user
    if not user:
        return None
    is_menu = '_MT_' in idname
    menu_idnames = ['wm.call_menu', 'wm.call_menu_pie']
    for keymap in user.keymaps:
        for km_item in keymap.keymap_items:
            if is_menu:
                if km_item.idname in menu_idnames and km_item.properties and km_item.properties['name'] == idname:
                    return km_item
            else:
                if km_item.idname == idname:
                    return km_item
    return None


def alter_user_keymaps(context):
    wm = context.window_manager
    for keymap in wm.keyconfigs.user.keymaps:
        if not hasattr(keymap, 'keymap_items'):
            continue
        for km_item in keymap.keymap_items:
            # Switches alternate pick shortest path behavior since default is blocked by RF
            if (km_item.idname == 'mesh.shortest_path_pick' and
                km_item.ctrl == True and km_item.shift == True and
                km_item.properties['use_fill'] == True
            ):
                store_keymap_item(km_item, {
                    'use_fill': True
                })
                km_item.properties['use_fill'] = False

            # Stops boundary loops at inner corners for easier selection in Strokes
            elif (km_item.idname == 'mesh.loop_select' and
                  bpy.app.version >= (5, 1, 0)
            ):
                store_keymap_item(km_item, {
                    'delimit_edge_loop': km_item.properties.delimit_edge_loop
                })
                km_item.properties.delimit_edge_loop = {'NGONS', 'OUTER_CORNERS', 'INNER_CORNERS'}

            # Prevents loop cuts from snapping to own vertices at small scales
            elif (km_item.idname == 'mesh.loopcut_slide'):
                print([x for x in km_item.properties.keys()])
                store_keymap_item(km_item, {
                    'use_snap_self': km_item.properties.TRANSFORM_OT_edge_slide.use_snap_self,
                    'use_snap_edit': km_item.properties.TRANSFORM_OT_edge_slide.use_snap_edit,
                })
                km_item.properties.TRANSFORM_OT_edge_slide.use_snap_self = False
                km_item.properties.TRANSFORM_OT_edge_slide.use_snap_edit = False


def restore_user_keymaps(context):
    keymaps_to_change = len(altered_keymap_items)
    wm = context.window_manager
    for saved_item in altered_keymap_items:
        for keymap in wm.keyconfigs.user.keymaps:
            # if not hasattr(keymap, 'keymap_items'):
            #     continue
            for km_item in keymap.keymap_items:
                if is_keymap_item_matching(km_item, saved_item):

                    if saved_item['idname'] == 'mesh.shortest_path_pick':
                        km_item.properties['use_fill'] = True
                        keymaps_to_change -= 1

                    elif saved_item['idname'] == 'mesh.loop_select':
                        for idx, delimit in enumerate(saved_item['altered']['delimit_edge_loop']):
                            km_item.properties.delimit_edge_loop = saved_item['altered']['delimit_edge_loop']
                        keymaps_to_change -= 1

                    elif saved_item['idname'] == 'mesh.loopcut_slide':
                        km_item.properties.TRANSFORM_OT_edge_slide.use_snap_self = saved_item['altered']['use_snap_self']
                        km_item.properties.TRANSFORM_OT_edge_slide.use_snap_edit = saved_item['altered']['use_snap_edit']
                        keymaps_to_change -= 1

                    if keymaps_to_change == 0:
                        return
