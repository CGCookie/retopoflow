
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
    "version":     (1, 1, 9), # artificially changed from (1, 2, 0)
    "blender":     (2, 7, 6),
    "location":    "View 3D > Tool Shelf",
    "warning":     "",  # used for warning icon and text in addons panel
    "wiki_url":    "http://cgcookiemarkets.com/blender/all-products/retopoflow/?view=docs",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View"
    }

# System imports
#None!!

# Blender imports
import bpy

#CGCookie imports
from .lib.common_utilities import bversion, check_source_target_objects


#Menus, Panels, Interface and Icon 
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
    from .op_edgeslide.edgeslide_modal import CGC_EdgeSlide
    from .op_polypen.polypen_modal import CGC_Polypen

# updater import
from .addon_updater import Updater as updater
import os


# Used to store keymaps for addon
addon_keymaps = []

def register():
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
        bpy.utils.register_class(CGC_EdgeSlide)
        bpy.utils.register_class(CGC_Polypen)
    
    bpy.utils.register_class(OpenLog)

    # Create the addon hotkeys
    kc = bpy.context.window_manager.keyconfigs.addon
   
    # create the mode switch menu hotkey
    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new('wm.call_menu', 'V', 'PRESS', ctrl=True, shift=True)
    kmi.properties.name = 'object.retopology_menu' 
    kmi.active = True
    addon_keymaps.append((km, kmi))

    # addon updater code and configurations
    register_updader()



def unregister():
    if bversion() >= '002.076.000':
        bpy.utils.unregister_class(CGC_Polystrips)
        bpy.utils.unregister_class(CGC_Tweak)
        bpy.utils.unregister_class(CGC_Contours)
        bpy.utils.unregister_class(CGC_EyeDropper)
        bpy.utils.unregister_class(CGC_LoopCut)
        bpy.utils.unregister_class(CGC_EdgeSlide)
        bpy.utils.unregister_class(CGC_Polypen)

    bpy.utils.unregister_class(CGCOOKIE_OT_retopoflow_panel)
    bpy.utils.unregister_class(CGCOOKIE_OT_retopoflow_menu)
    bpy.app.handlers.scene_update_post.remove(check_source_target_objects)
    bpy.utils.unregister_class(RetopoFlowPreferences)
    
    clear_icons()

    bpy.utils.unregister_class(OpenLog)
    
    # Remove addon hotkeys
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()


def register_updader():
    ""
    updater.user = "cgcookie"
    updater.repo = "retopoflow"
    updater.use_releases = False
    npath = os.path.join(os.path.dirname(__file__), bl_info["name"]+"_update_staging")
    print(npath)
    updater.stage_path = npath
    updater.current_version = bl_info["version"]
    #updater.set_check_frequency(enable=False,months=0,weeks=0,days=0,minutes=5)
    updater.verbose = True

    # this should NOT BE RUN in register; though it works, it 
    # delays blender startup due to retreiving updates online
    # better to use it just before a tool is used for exmaple,
    # or when the menu is ran for the first time.
    # Or, make it asynchronous. 
    (update_ready, version, link) = updater.check_for_update()
    print(update_ready, version, link)

    # **definitely** shouldn't do this, ask permission first e.g. in popup.
    # but, no values need to be passed in.. all stored in the class.
    updater.run_update(force=False)

