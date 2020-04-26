'''
Copyright (C) 2020 CG Cookie
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

import os
import re
import time
import importlib
import faulthandler
from concurrent.futures import ThreadPoolExecutor


if "bpy" in locals():
    print('RetopoFlow: RELOADING!')
    # reloading RF modules
    importlib.reload(retopoflow)
    importlib.reload(options)
    importlib.reload(updater)
else:
    print('RetopoFlow: Initial load')
    from .retopoflow import retopoflow
    from .config.options import options, retopoflow_version
    from .retopoflow import updater

import bpy
from bpy.types import Menu, Operator, Panel
from bpy_extras import object_utils
from bpy.app.handlers import persistent

from .addon_common.common.blender import show_blender_text


bl_info = {
    "name":        "RetopoFlow",
    "description": "A suite of retopology tools for Blender through a unified retopology mode",
    "author":      "Jonathan Denning, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart",
    "version":     (3, 0, 0),
    "blender":     (2, 80, 0),
    "location":    "View 3D > Header",
    "warning":     "beta2 (β2)",  # used for warning icon and text in addons panel
    "doc_url":     "https://github.com/CGCookie/retopoflow/",  # "http://docs.retopoflow.com",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View",
}

faulthandler.enable()

class VIEW3D_OT_RetopoFlow_Help_QuickStart(retopoflow.RetopoFlow_OpenHelpSystem):
    """Open RetopoFlow Quick Start Guide"""
    bl_idname = "cgcookie.retopoflow_help_quickstart"
    bl_label = "Open Quick Start Guide"
    bl_description = "Open RetopoFlow Quick Start Guide"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}
    rf_startdoc = 'quick_start.md'

class VIEW3D_OT_RetopoFlow_Help_Welcome(retopoflow.RetopoFlow_OpenHelpSystem):
    """Open RetopoFlow Welcome"""
    bl_idname = "cgcookie.retopoflow_help_welcome"
    bl_label = "Open Welcome Message"
    bl_description = "Open RetopoFlow Welcome Message"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}
    rf_startdoc = 'welcome.md'


class VIEW3D_OT_RetopoFlow(retopoflow.RetopoFlow):
    """Start RetopoFlow"""
    bl_idname = "cgcookie.retopoflow"
    bl_label = "Start RetopoFlow"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'UNDO', 'BLOCKING'}


class VIEW3D_OT_RetopoFlow_NewTarget(Operator):
    """Create new target object+mesh and start RetopoFlow"""
    bl_idname = "cgcookie.retopoflow_newtarget"
    bl_label = "RF: Create new target"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nCreate new target mesh and start RetopoFlow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        auto_edit_mode = bpy.context.preferences.edit.use_enter_edit_mode # working around blender bug, see https://github.com/CGCookie/retopoflow/issues/786
        bpy.context.preferences.edit.use_enter_edit_mode = False
        for o in bpy.data.objects: o.select_set(False)
        mesh = bpy.data.meshes.new('RetopoFlow')
        obj = object_utils.object_data_add(context, mesh, name='RetopoFlow')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.context.preferences.edit.use_enter_edit_mode = auto_edit_mode
        return bpy.ops.cgcookie.retopoflow('INVOKE_DEFAULT')



def RF_Factory(starting_tool):
    class VIEW3D_OT_RetopoFlow_Tool(retopoflow.RetopoFlow):
        """Start RetopoFlow with a specific tool"""
        bl_idname = "cgcookie.retopoflow_%s" % starting_tool.lower()
        bl_label = "RF: %s" % starting_tool
        bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nStart with %s" % starting_tool
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = {'REGISTER', 'UNDO'}
        rf_starting_tool = starting_tool
    return VIEW3D_OT_RetopoFlow_Tool
customs = [
    RF_Factory(n) for n in [
        'Contours',
        'PolyStrips',
        'PolyPen',
        'Relax',
        'Tweak',
        'Loops',
        'Patches',
        'Strokes',
    ] ]


perform_backup_recovery = False
backup_executor = ThreadPoolExecutor()
@persistent
def delayed_check():
    global perform_backup_recovery, backup_executor
    time.sleep(0.2)
    if perform_backup_recovery:
        print('Performing backup')
        perform_backup_recovery = False
        retopoflow.RetopoFlow.backup_recover()
    else:
        #print('skipping backup')
        pass
    backup_executor.submit(delayed_check)
#delayed_check()

class VIEW3D_OT_RetopoFlow_Recover(Operator):
    bl_idname = 'cgcookie.retopoflow_recover'
    bl_label = 'Recover Auto Save'
    bl_description = 'Recover from RetopoFlow auto save.\nPath: %s' % options.temp_filepath('blend')
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    rf_icon = 'rf_recover_icon'

    @classmethod
    def poll(cls, context):
        #return False # THIS IS BROKEN!!!
        return retopoflow.RetopoFlow.has_backup()

    def invoke(self, context, event):
        global perform_backup_recovery
        #perform_backup_recovery = True
        retopoflow.RetopoFlow.backup_recover()
        return {'FINISHED'}


class VIEW3D_PT_RetopoFlow(Panel):
    """RetopoFlow Blender Menu"""
    bl_label = "RetopoFlow %s" % retopoflow_version
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    @staticmethod
    def is_editing_target(context):
        obj = context.active_object
        mode_string = context.mode
        edit_object = context.edit_object
        gp_edit = obj and obj.mode in {'EDIT_GPENCIL', 'PAINT_GPENCIL', 'SCULPT_GPENCIL', 'WEIGHT_GPENCIL'}
        return not gp_edit and edit_object and mode_string == 'EDIT_MESH'

    def draw(self, context):
        layout = self.layout
        if VIEW3D_PT_RetopoFlow.is_editing_target(context):
            # currently editing target, so show RF tools
            layout.label(text='Start RetopoFlow with Tool')
            col = layout.column()
            for c in customs:
                col.operator(c.bl_idname)
        else:
            layout.label(text='Start RetopoFlow')
            # currently not editing target, so show operator to create new target
            layout.operator('cgcookie.retopoflow_newtarget')
        layout.separator()
        layout.label(text='Open Help')
        layout.operator('cgcookie.retopoflow_help_quickstart')
        layout.operator('cgcookie.retopoflow_help_welcome')
        layout.separator()
        layout.operator('cgcookie.retopoflow_recover')
        layout.separator()
        #layout.label(text='RetopoFlow Updater')
        layout.label(text='RetopoFlow Updater')
        col = layout.column()
        col.operator('cgcookie.retopoflow_updater_check_now')
        col.operator('cgcookie.retopoflow_updater_update_now')

    #############################################################################
    # the following two methods add/remove RF to/from the main 3D View menu
    # NOTE: this is a total hack: hijacked the draw function!
    @staticmethod
    def menu_add():
        # for more icon options, see:
        #     https://docs.blender.org/api/current/bpy.types.UILayout.html#bpy.types.UILayout.operator
        VIEW3D_PT_RetopoFlow.menu_remove()
        VIEW3D_PT_RetopoFlow._menu_original = bpy.types.VIEW3D_MT_editor_menus.draw_collapsible
        def hijacked(context, layout):
            obj = context.active_object
            mode_string = context.mode
            edit_object = context.edit_object
            gp_edit = obj and obj.mode in {'EDIT_GPENCIL', 'PAINT_GPENCIL', 'SCULPT_GPENCIL', 'WEIGHT_GPENCIL'}

            VIEW3D_PT_RetopoFlow._menu_original(context, layout)

            row = layout.row(align=True)
            if VIEW3D_PT_RetopoFlow.is_editing_target(context):
                row.operator('cgcookie.retopoflow', text="", icon='DECORATE_KEYFRAME')
            # row.menu("VIEW3D_PT_RetopoFlow", text="RetopoFlow")
            row.popover(panel="VIEW3D_PT_RetopoFlow", text="RetopoFlow %s"%retopoflow_version)
            row.operator('cgcookie.retopoflow_help_quickstart', text="", icon='QUESTION')
        bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = hijacked
    @staticmethod
    def menu_remove():
        if not hasattr(VIEW3D_PT_RetopoFlow, '_menu_original'): return
        bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = VIEW3D_PT_RetopoFlow._menu_original
        del VIEW3D_PT_RetopoFlow._menu_original


# registration
classes = [
    VIEW3D_PT_RetopoFlow,
    VIEW3D_OT_RetopoFlow,
    VIEW3D_OT_RetopoFlow_NewTarget,
    VIEW3D_OT_RetopoFlow_Recover,
    VIEW3D_OT_RetopoFlow_Help_QuickStart,
    VIEW3D_OT_RetopoFlow_Help_Welcome,
] + customs

def register():
    for cls in classes: bpy.utils.register_class(cls)
    updater.register(bl_info)
    VIEW3D_PT_RetopoFlow.menu_add()

def unregister():
    VIEW3D_PT_RetopoFlow.menu_remove()
    updater.unregister()
    for cls in reversed(classes): bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
