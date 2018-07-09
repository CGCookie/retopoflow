
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
    "description": "A retopology-focused mode with dedicated retopology tools for Blender",
    "author":      "Jonathan Denning, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart",
    "version":     (2, 0, 0),
    "blender":     (2, 7, 8),
    "location":    "View 3D > Tool Shelf",
    "warning":     "",  # used for warning icon and text in addons panel
    "wiki_url":    "http://docs.retopoflow.com",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View"
    }

# System imports
#None!!

# Blender imports
import bpy

from .options import options

#Menus, Panels, Interface and Icons
from .interface import CGCOOKIE_OT_retopoflow2_panel, CGCOOKIE_OT_retopoflow1_panel, CGCOOKIE_OT_retopoflow_menu
from .preferences import RetopoFlowPreferences

from .icons import clear_icons
import bpy.utils.previews

#Tools
from .rfmode.rfmode import RFMode, rfmode_tools
from .rfmode.rf_recover import RFRecover, RFRecover_Clear
from .rfmode.rf_quickstart import OpenQuickStart
from .rfmode.rf_openlog import OpenLog
from .rfmode.rf_webissues import OpenWebIssues
from .rfmode.rf_webtip import OpenWebTip

from .cookiecutter.test import CookieCutter_Test

# updater import
from . import addon_updater_ops

# Used to store keymaps for addon
addon_keymaps = []

def register():
    bpy.utils.register_class(RetopoFlowPreferences)

    for idname,rft in rfmode_tools.items():
        # print('registering '+idname)
        bpy.utils.register_class(rft)

    bpy.utils.register_class(RFRecover)
    bpy.utils.register_class(RFRecover_Clear)

    bpy.utils.register_class(CGCOOKIE_OT_retopoflow2_panel)
    bpy.utils.register_class(CGCOOKIE_OT_retopoflow_menu)

    bpy.utils.register_class(OpenLog)
    bpy.utils.register_class(OpenQuickStart)
    bpy.utils.register_class(OpenWebIssues)
    bpy.utils.register_class(OpenWebTip)
    
    bpy.utils.register_class(CookieCutter_Test)

    # Create the add-on hotkeys
    kc = bpy.context.window_manager.keyconfigs.addon

    # Create the retopology menu hotkey
    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new('wm.call_menu', 'V', 'PRESS', ctrl=True, shift=True)
    kmi.properties.name = 'object.retopology_menu'
    kmi.active = True
    addon_keymaps.append((km, kmi))

    # addon updater code and configurations
    addon_updater_ops.register(bl_info)

def unregister():
    bpy.utils.unregister_class(CGCOOKIE_OT_retopoflow_menu)
    bpy.utils.unregister_class(CGCOOKIE_OT_retopoflow2_panel)

    bpy.utils.unregister_class(RFRecover_Clear)
    bpy.utils.unregister_class(RFRecover)

    for rft in rfmode_tools.values():
        bpy.utils.unregister_class(rft)

    bpy.utils.unregister_class(RetopoFlowPreferences)

    # addon updater unregister
    addon_updater_ops.unregister()

    clear_icons()

    bpy.utils.unregister_class(OpenLog)
    bpy.utils.unregister_class(OpenQuickStart)
    bpy.utils.unregister_class(OpenWebIssues)
    bpy.utils.unregister_class(OpenWebTip)

    # Remove add-on hotkeys
    for km,kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

