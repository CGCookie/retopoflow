
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
    "version":     (2, 0, 1),
    "blender":     (2, 7, 9),
    "location":    "View 3D > Tool Shelf",
    # "warning":     "beta 2",  # used for warning icon and text in addons panel
    "wiki_url":    "http://docs.retopoflow.com",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View"
}

import sys
from datetime import datetime
import traceback

# Blender imports
import bpy
import bpy.utils.previews
from bpy.types import Panel, Operator

from .common.debug import Debugger
from .common.blender import create_and_show_blender_text, show_blender_text

from .options import (
    retopoflow_version, retopoflow_version_git,
    build_platform,
    platform_system,platform_node,platform_release,platform_version,platform_machine,platform_processor,
    gpu_vendor,gpu_renderer,gpu_version,gpu_shading,
)


addon_keymaps = []          # Used to store keymaps for addon
register_classes = []       # RF classes to register



# in case something breaks while registering...
retopoflow_is_broken = False
retopoflow_broken_message = None
class RF_OpenBrokenMessage(Operator):
    """Open RetopoFlow Broken Message in new window"""

    bl_category = 'Retopology'
    bl_idname = 'cgcookie.rf_open_brokenmessage'
    bl_label = "Open RetopoFlow Broken Message"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    @classmethod
    def poll(cls, context):
        global retopoflow_is_broken
        return retopoflow_is_broken

    def execute(self, context):
        self.openTextFile()
        return {'FINISHED'}

    def openTextFile(self):
        global retopoflow_broken_message
        txtname = 'retopoflow broken message'
        # simple processing of help_quickstart
        if txtname not in bpy.data.texts:
            bpy.data.texts.new(txtname)
        txt = bpy.data.texts[txtname]
        txt.from_string(retopoflow_broken_message)
        txt.current_line_index = 0
        show_blender_text(txtname)

class RF_OpenWebIssues(Operator):
    """Open RetopoFlow Issues page in default web browser"""

    bl_category = 'Retopology'
    bl_idname = "cgcookie.rf_open_webissues"
    bl_label = "Open RetopoFlow Issues Page"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        from .options import options
        bpy.ops.wm.url_open(url=options['github issues url'])
        return {'FINISHED'}


class RF_Panel_Broken(Panel):
    bl_category = "Retopology"
    bl_label = "RetopoFlow %s" % retopoflow_version
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.label('RetopoFlow broke while registering.', icon="ERROR")
        col.label('Click Open button below to view message.')
        col.operator('cgcookie.rf_open_brokenmessage', 'View Error Message')
        col.operator("cgcookie.rf_open_webissues",  "Report an Issue")




# attempt to import some Python packages that are sometimes missing from the
# system Python3 install (but should be included in Blender's Python)
try:
    import numpy
    import urllib.request
    # import doesnotexist
except Exception as e:
    i,h = Debugger.get_exception_info_and_hash()
    blender_version = '%d.%02d.%d' % bpy.app.version
    blender_branch = bpy.app.build_branch.decode('utf-8')
    blender_date = bpy.app.build_commit_date.decode('utf-8')
    text = []
    text += ['COULD NOT FIND PYTHON PACKAGES']
    text += ['']
    text += ['Environment:']
    text += ['- RetopoFlow: %s' % (retopoflow_version,)]
    if retopoflow_version_git:
        text += ['- RF git: %s' % (retopoflow_version_git,)]
    text += ['- Blender: %s %s %s' % (blender_version, blender_branch, blender_date)]
    text += ['- Platform: %s' % (', '.join([platform_system,platform_release,platform_version,platform_machine,platform_processor]), )]
    text += ['- GPU: %s' % (', '.join([gpu_vendor, gpu_renderer, gpu_version, gpu_shading]), )]
    text += ['- Timestamp: %s' % datetime.today().isoformat(' ')]
    text += ['- Sys Path:'] + ['\n'.join('    %s'%l for l in sys.path)]
    text += ['']
    text += ['Exception: %s' % str(e)]
    text += ['Error Hash: %s' % h]
    text += ['Trace:'] + ['\n'.join('    %s'%l for l in i.splitlines())]
    text = '\n'.join(text)

    print('\n\n')
    print('='*100)
    print(text)
    print('='*100)
    print('\n\n')

    retopoflow_is_broken = True
    retopoflow_broken_message = text
    #create_and_show_blender_text(text)
    #raise Exception(text)


if not retopoflow_is_broken:
    try:
        from .common.debug import debugger
        from .common.profiler import profiler
        from .common.logger import logger

        from .options import options

        # Operators, Menus, Panels, Icons
        from .interface import (
            RF_SnapObjects,
            RF_Preferences,
            RF_Recover, RF_Recover_Clear,
            RF_Panel,
            RF_Menu,
            RF_OpenLog,
            RF_OpenQuickStart,
            RF_OpenWebTip,
        )
        from .icons import clear_icons

        #Tools
        from .rfmode.rfmode import rfmode_tools

        from .cookiecutter.test import CookieCutter_Test

        # updater import
        from . import addon_updater_ops

        register_classes += [
            RF_SnapObjects,
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

    except Exception as e:
        i,h = Debugger.get_exception_info_and_hash()
        blender_version = '%d.%02d.%d' % bpy.app.version
        blender_branch = bpy.app.build_branch.decode('utf-8')
        blender_date = bpy.app.build_commit_date.decode('utf-8')
        text = []
        text += ['COULD NOT IMPORT RETOPOFLOW MODULES']
        text += ['']
        text += ['Environment:']
        text += ['- RetopoFlow: %s' % (retopoflow_version,)]
        if retopoflow_version_git:
            text += ['- RF git: %s' % (retopoflow_version_git,)]
        text += ['- Blender: %s %s %s' % (blender_version, blender_branch, blender_date)]
        text += ['- Platform: %s' % (', '.join([platform_system,platform_release,platform_version,platform_machine,platform_processor]), )]
        text += ['- GPU: %s' % (', '.join([gpu_vendor, gpu_renderer, gpu_version, gpu_shading]), )]
        text += ['- Timestamp: %s' % datetime.today().isoformat(' ')]
        text += ['- Sys Path:'] + ['\n'.join('    %s'%l for l in sys.path)]
        text += ['']
        text += ['Exception: %s' % str(e)]
        text += ['Error Hash: %s' % h]
        text += ['Trace:'] + ['\n'.join('    %s'%l for l in i.splitlines())]
        text = '\n'.join(text)
        retopoflow_is_broken = True
        retopoflow_broken_message = text

        print('\n\n')
        print('='*100)
        print(text)
        print('='*100)
        print('\n\n')

        #raise e






def register():
    global register_classes, addon_keymaps
    global retopoflow_is_broken, retopoflow_broken_message

    if retopoflow_is_broken:
        for c in [RF_OpenBrokenMessage, RF_Panel_Broken, RF_OpenWebIssues]:
            bpy.utils.register_class(c)
        #raise Exception(retopoflow_broken_message)
        #create_and_show_blender_text(retopoflow_broken_message)
        return

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

    bpy.types.Scene.snapobjects = bpy.props.PointerProperty(type=RF_SnapObjects)

def unregister():
    global register_classes, addon_keymaps
    global retopoflow_is_broken, retopoflow_broken_message

    if retopoflow_is_broken: return

    clear_icons()

    del bpy.types.Scene.snapobjects

    # unregister all of the classes in reverse order
    for c in reversed(register_classes):
        bpy.utils.unregister_class(c)

    # addon updater unregister
    addon_updater_ops.unregister()

    # Remove add-on hotkeys
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()
