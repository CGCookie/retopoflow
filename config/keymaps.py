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
from bpy.types import Context, KeyMap, KeyMapItem, OperatorProperties
from typing import TypeAlias
from collections.abc import Callable

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

#TODO: Cleanup: unify the functions here with those in addon_common/common/useractions.py



KMI_OVERRIDE_OPERATOR_NAME : TypeAlias = str
KMI_OVERRIDE_TEST_FUNCTION : TypeAlias = Callable[[KeyMapItem], bool]

KMI_OVERRIDE_PROP_KEY : TypeAlias = str
KMI_OVERRIDE_PROP_VALUE : TypeAlias = ... # pyright: ignore[reportUnknownVariableType]
KMI_OVERRIDE_PROPS : TypeAlias = dict[KMI_OVERRIDE_PROP_KEY, KMI_OVERRIDE_PROP_VALUE]

KMI_OVERRIDE : TypeAlias = tuple[KMI_OVERRIDE_OPERATOR_NAME, KMI_OVERRIDE_TEST_FUNCTION, KMI_OVERRIDE_PROPS]
KMI_OVERRIDES : TypeAlias = list[KMI_OVERRIDE]

KMI_KEY : TypeAlias = tuple[...]

# Marks a property that had no value before RF's override.
# Sub-keys of a nested operator prop (e.g. mesh.loopcut_slide's TRANSFORM_OT_edge_slide)
# cannot use delete_keys, because unsetting the group would also discard sub-keys RF never touched.
KMI_PROP_UNSET = object()

# Blender can invalidate a km reference or reuse its memory for a different item
# when it rebuilds the user keyconfig, so use the data to identify it instead.
# (keymap name, space_type, region_type, kmi id, operator idname, delete_keys, reset_vals)
KMI_RESET_RECORD : TypeAlias = tuple[str, str, str, int, str, set[str], dict[str, ...]]

# Identifies a keymap item RF deactivated
# (keymap name, space_type, region_type, kmi id, operator idname)
KMI_SUPPRESS_RECORD : TypeAlias = tuple[str, str, str, int, str]


retopoflow_keymap_overrides : KMI_OVERRIDES = [  # pyright: ignore[reportUnknownVariableType]

    # Switches alternate pick shortest path behavior since default is blocked by RF
    (
        'mesh.shortest_path_pick',
        lambda kmi: bool(kmi.ctrl) and bool(kmi.shift),
        { 'use_fill': False },
    ),

    # Stops boundary loops at inner corners for easier selection in Strokes
    (
        'mesh.loop_select',
        lambda _kmi: bpy.app.version >= (5, 1, 0),
        { 'delimit_edge_loop': { 'NGONS', 'OUTER_CORNERS', 'INNER_CORNERS' } },
    ),

    # Prevents loop cuts from snapping to own vertices at small scales
    (
        'mesh.loopcut_slide',
        lambda _kmi: True,
        { 'TRANSFORM_OT_edge_slide': { 'use_snap_self': False, 'use_snap_edit': False } },
    ),
]


# Other add-ons' operators that bind keys directly in Blender's keymaps.
# Deactivated while RF runs, restored on stop. Add a line per known conflict.
conflicting_keymap_operators : tuple[str, ...] = (
    # X-Ray Selection Tools: binds B / C / L in the Mesh keymap by default
    'mesh.select_box_xray',
    'mesh.select_circle_xray',
    'mesh.select_lasso_xray',
    'mesh.select_tools_xray_toggle_select_through',
    'mesh.select_tools_xray_toggle_mesh_behavior',
    'mesh.select_tools_xray_toggle_select_backfacing',
)


reset_keymap_items : list[KMI_RESET_RECORD] = []
suppressed_keymap_items : list[KMI_SUPPRESS_RECORD] = []


# Returns the first matching keymap item. There could be multiple!
# Add arguments to further filter if needed
# km_name narrows the search to one keymap, for operators that RF also binds in a tool keymap
def get_user_keymap_item(context : Context, idname : str, km_name : str | None = None) -> KeyMapItem | None:
    user = context.window_manager.keyconfigs.user
    if not user:
        return None
    is_menu = '_MT_' in idname
    menu_idnames = ['wm.call_menu', 'wm.call_menu_pie']
    for keymap in user.keymaps:
        if km_name is not None and keymap.name != km_name:
            continue
        for km_item in keymap.keymap_items:
            if is_menu:
                if km_item.idname in menu_idnames and km_item.properties and km_item.properties.get('name', None) == idname:
                    return km_item
            else:
                if km_item.idname == idname:
                    return km_item
    return None


def _reset_kmi_properties(
    km_item : KeyMapItem,
    delete_keys : set[str],
    reset_vals : dict[str, ...],
):
    # print(f'{km_item.idname}')
    # print(f'  delete: {delete_keys}')
    # print(f'  reset:  {reset_vals}')

    kmi_props = km_item.properties

    # The km_item can be invalidated between start and restore when Blender rebuilds the user keyconfig.
    if kmi_props is None:
        return # Nothing to restore

    for key in delete_keys:
        kmi_props.property_unset(key)

    for (key, val) in reset_vals.items(): # pyright: ignore[reportAny]
        if not isinstance(val, dict):
            setattr(kmi_props, key, val)

        elif (prop := getattr(kmi_props, key, None)):
            for (k, v) in val.items(): # pyright: ignore[reportUnknownVariableType]
                if v is KMI_PROP_UNSET:
                    prop.property_unset(k)
                else:
                    setattr(prop, k, v)

def _override_kmi_properties(
    keymap : KeyMap,
    km_item : KeyMapItem,
    assign_vals : KMI_OVERRIDE_PROPS,  # pyright: ignore[reportUnknownParameterType]
):
    kmi_props = km_item.properties
    if kmi_props is None:
        return

    # store current keymap operator property and then reassign
    delete_keys : set[str] = set()
    reset_vals : dict[str, ...] = {}

    for (key, val) in assign_vals.items(): # pyright: ignore[reportUnknownVariableType]
        if key not in kmi_props:
            # NOTE: hasattr(kmi_props, key) is always True if key is a property of operator
            #       must use key in kmi_props to test if property has a value
            delete_keys.add(key)

        else:
            kmi_prop_val = getattr(kmi_props, key) # pyright: ignore[reportAny]

            if not isinstance(val, dict):
                reset_vals[key] = kmi_prop_val

            else:
                # Sub-keys with no value yet are marked so restore unsets them properly.
                reset_vals[key] = {
                    k: (getattr(kmi_prop_val, k) if k in kmi_prop_val else KMI_PROP_UNSET) # pyright: ignore[reportAny]
                    for k in val
                }

        if not isinstance(val, dict):
            # print(f'{km_item.idname}.properties.{key} = {val}')
            setattr(kmi_props, key, val)

        elif (p := getattr(kmi_props, key, None)):
            for (k, v) in val.items(): # pyright: ignore[reportUnknownVariableType]
                setattr(p, k, v)

    # Store identifying data, not the live km_item reference
    reset_keymap_items.append((
        keymap.name, keymap.space_type, keymap.region_type,
        km_item.id, km_item.idname,
        delete_keys, reset_vals,
    ))


def alter_user_keymaps(context : Context):
    user_keyconfigs = context.window_manager.keyconfigs.user
    if not user_keyconfigs:
        return

    for keymap in user_keyconfigs.keymaps:
        if not hasattr(keymap, 'keymap_items'):
            continue
        for km_item in keymap.keymap_items:
            for (op_name, test_fn, assign_vals) in retopoflow_keymap_overrides: # pyright: ignore[reportUnknownVariableType]
                if km_item.idname != op_name or not test_fn(km_item):
                    continue
                _override_kmi_properties(keymap, km_item, assign_vals)


def _find_user_kmi(
    context : Context,
    km_name : str, space_type : str, region_type : str,
    kmi_id : int, idname : str,
) -> KeyMapItem | None:
    user = context.window_manager.keyconfigs.user
    if not user:
        return None
    keymap = user.keymaps.find(km_name, space_type=space_type, region_type=region_type)
    if not keymap:
        return None
    matches = [km_item for km_item in keymap.keymap_items if km_item.idname == idname]
    # Prefer the exact item by id and fall back to a single item of the same opearator.
    # Matching idname first guarantees we never touch a different operator's item even if an id was reused.
    for km_item in matches:
        if km_item.id == kmi_id:
            return km_item
    if len(matches) == 1:
        return matches[0]
    return None


def restore_user_keymaps(context : Context):
    for (km_name, space_type, region_type, kmi_id, idname, delete_keys, reset_vals) in reset_keymap_items:
        # Resolve the item fresh rather than trusting a reference captured at alter time.
        km_item = _find_user_kmi(context, km_name, space_type, region_type, kmi_id, idname)
        if km_item is None:
            continue # Item was removed or rebuilt beyond recognition, nothing safe to restore.
        _reset_kmi_properties(km_item, delete_keys, reset_vals)
    reset_keymap_items.clear()


def suppress_conflicting_keymaps(context : Context):
    user_keyconfigs = context.window_manager.keyconfigs.user
    if not user_keyconfigs:
        return

    for keymap in user_keyconfigs.keymaps:
        if not hasattr(keymap, 'keymap_items'):
            continue
        for km_item in keymap.keymap_items:
            if km_item.idname not in conflicting_keymap_operators:
                continue
            if not km_item.active:
                continue # Already off. Recording it would turn it on for the artist at stop.
            km_item.active = False
            suppressed_keymap_items.append((
                keymap.name, keymap.space_type, keymap.region_type,
                km_item.id, km_item.idname,
            ))


def restore_conflicting_keymaps(context : Context):
    for (km_name, space_type, region_type, kmi_id, idname) in suppressed_keymap_items:
        # Resolve the item fresh rather than trusting a reference captured at suppress time.
        km_item = _find_user_kmi(context, km_name, space_type, region_type, kmi_id, idname)
        if km_item is None:
            continue # Item was removed or rebuilt beyond recognition, nothing safe to restore.
        km_item.active = True
    suppressed_keymap_items.clear()
