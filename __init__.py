
'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

bl_info = {
    "name":        "RetopoFlow",
    "description": "A suite of retopology tools for Blender through a unified retopology mode",
    "author":      "Jonathan Denning, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart",
    "version":     (2, 0, 0),
    "blender":     (2, 7, 9),
    "location":    "View 3D > Tool Shelf",
    # "warning":     "beta 2",  # used for warning icon and text in addons panel
    "wiki_url":    "http://docs.retopoflow.com",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View"
}

# Blender imports
import bpy
import bpy.utils.previews

try:
    from .common.debug import debugger
    from .common.profiler import profiler
    from .common.logger import logger

    from .options import options

    # Operators, Menus, Panels, Icons
    from .interface import (
        RF_Panel,
        RF_Menu,
        RF_Preferences,
        RF_Recover, RF_Recover_Clear,
        RF_OpenLog,
        RF_OpenWebTip,
        RF_OpenWebIssues,
        RF_OpenQuickStart,
    )
    from .icons import clear_icons

    #Tools
    from .rfmode.rfmode import rfmode_tools

    from .cookiecutter.test import CookieCutter_Test

    # updater import
    from . import addon_updater_ops

except Exception as e:
    raise e


# Used to store keymaps for addon
addon_keymaps = []

register_classes = [
    RF_Preferences,
    RF_Recover,
    RF_Recover_Clear,
    RF_Panel,
    RF_Menu,
    RF_OpenLog,
    RF_OpenQuickStart,
    RF_OpenWebIssues,
    RF_OpenWebTip,
    CookieCutter_Test,
]
register_classes += [rft for (idname, rft) in rfmode_tools.items()]

def register():
    global register_classes, addon_keymaps

    # register all of the classes
    for c in register_classes:
        bpy.utils.register_class(c)

    # Create the add-on hotkeys
    kc = bpy.context.window_manager.keyconfigs.addon
    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new('wm.call_menu', 'V', 'PRESS', ctrl=True, shift=True)
    kmi.properties.name = 'object.retopology_menu'
    kmi.active = True
    addon_keymaps.append((km, kmi))

    # addon updater code and configurations
    addon_updater_ops.register(bl_info)

def unregister():
    global register_classes, addon_keymaps

    clear_icons()

    # unregister all of the classes in reverse order
    for c in reversed(register_classes):
        bpy.utils.unregister_class(c)

    # addon updater unregister
    addon_updater_ops.unregister()

    # Remove add-on hotkeys
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
