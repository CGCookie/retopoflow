
'''
Copyright (C) 2016 CG Cookie
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
    "description": "A suite of dedicated retopology tools for Blender",
    "author":      "Jonathan Denning, Jonathan Williamson, Patrick Moore",
    "version":     (1, 3, 0),
    "blender":     (2, 7, 6),
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

#CGCookie imports
from .lib.common_utilities import bversion, check_source_target_objects
from .lib.common_utilities import register as register_common_utilities


#Menus, Panels, Interface and Icons
from .interface import CGCOOKIE_OT_retopoflow_panel, CGCOOKIE_OT_retopoflow_menu
from .preferences import RetopoFlowPreferences

from .lib.classes.logging.logging import OpenLog

if bversion() >= '002.076.000':
    from .icons import clear_icons
    import bpy.utils.previews
    
    from .icons import clear_icons
    #Tools
    from .op_polystrips.polystrips_modal import CGC_Polystrips
    from .op_contours.contours_modal import CGC_Contours
    from .op_tweak.tweak_modal import CGC_Tweak
    from .op_eyedropper.eyedropper_modal import CGC_EyeDropper
    from .op_loopcut.loopcut_modal import CGC_LoopCut
    from .op_loopslide.loopslide_modal import CGC_loopslide
    from .op_polypen.polypen_modal import CGC_Polypen

# updater import
from . import addon_updater_ops

# Used to store keymaps for addon
addon_keymaps = []

def register():
    register_common_utilities()

    bpy.utils.register_class(RetopoFlowPreferences)
    bpy.app.handlers.scene_update_post.append(check_source_target_objects)
    bpy.utils.register_class(CGCOOKIE_OT_retopoflow_panel)
    bpy.utils.register_class(CGCOOKIE_OT_retopoflow_menu)
    
    if bversion() >= '002.076.000':
        bpy.utils.register_class(CGC_Polystrips)
        bpy.utils.register_class(CGC_Tweak)
        bpy.utils.register_class(CGC_Contours)
        bpy.utils.register_class(CGC_EyeDropper)
        bpy.utils.register_class(CGC_LoopCut)
        bpy.utils.register_class(CGC_loopslide)
        bpy.utils.register_class(CGC_Polypen)
    
    bpy.utils.register_class(OpenLog)

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
    if bversion() >= '002.076.000':
        bpy.utils.unregister_class(CGC_Polystrips)
        bpy.utils.unregister_class(CGC_Tweak)
        bpy.utils.unregister_class(CGC_Contours)
        bpy.utils.unregister_class(CGC_EyeDropper)
        bpy.utils.unregister_class(CGC_LoopCut)
        bpy.utils.unregister_class(CGC_loopslide)
        bpy.utils.unregister_class(CGC_Polypen)

    bpy.utils.unregister_class(CGCOOKIE_OT_retopoflow_panel)
    bpy.utils.unregister_class(CGCOOKIE_OT_retopoflow_menu)
    bpy.app.handlers.scene_update_post.remove(check_source_target_objects)
    bpy.utils.unregister_class(RetopoFlowPreferences)

    # addon updater unregister
    addon_updater_ops.unregister()
    
    clear_icons()

    bpy.utils.unregister_class(OpenLog)
    
    # Remove add-on hotkeys
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

