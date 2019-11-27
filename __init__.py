'''
Copyright (C) 2019 CG Cookie
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

import importlib

if "bpy" in locals():
    # reloading RF modules
    importlib.reload(retopoflow)
else:
    from .retopoflow import retopoflow

import bpy
from bpy.types import Menu, Operator
from bpy_extras import object_utils


bl_info = {
    "name":        "RetopoFlow",
    "description": "A suite of retopology tools for Blender through a unified retopology mode",
    "author":      "Jonathan Denning, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart",
    "version":     (3, 0, 0),
    "blender":     (2, 80, 0),
    "location":    "View 3D > Tool Shelf",
    "warning":     "pre-alpha (pre-α)",  # used for warning icon and text in addons panel
    "wiki_url":    "http://docs.retopoflow.com",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View"
}


class VIEW3D_OT_RetopoFlow(retopoflow.RetopoFlow):
    """RetopoFlow Blender Operator"""
    bl_idname = "cgcookie.retopoflow"
    bl_label = "RetopoFlow"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}


class VIEW3D_OT_RetopoFlow_New(Operator):
    """RetopoFlow Blender Operator"""
    bl_idname = "cgcookie.retopoflow_new"
    bl_label = "RF: Create new target"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nCreate new target mesh and start RetopoFlow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        for o in bpy.data.objects: o.select_set(False)
        mesh = bpy.data.meshes.new('RetopoFlow')
        obj = object_utils.object_data_add(context, mesh, name='RetopoFlow')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        return bpy.ops.cgcookie.retopoflow('INVOKE_DEFAULT')


def RF_Factory(starting_tool):
    class VIEW3D_OT_RetopoFlow_Tool(retopoflow.RetopoFlow):
        """RetopoFlow Blender Operator"""
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


class VIEW3D_OT_RetopoFlow_Recover(Operator):
    bl_idname = 'cgcookie.retopoflow_recover'
    bl_label = 'Recover Auto Save'
    bl_description = 'Recover from RetopoFlow auto save'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    rf_icon = 'rf_recover_icon'

    @classmethod
    def poll(cls, context):
        return retopoflow.RetopoFlow.has_backup()

    def invoke(self, context, event):
        retopoflow.RetopoFlow.backup_recover()
        return {'FINISHED'}


class VIEW3D_MT_RetopoFlow(Menu):
    """RetopoFlow Blender Menu"""
    bl_label = "RetopoFlow"

    @staticmethod
    def is_editing_target(context):
        obj = context.active_object
        mode_string = context.mode
        edit_object = context.edit_object
        gp_edit = obj and obj.mode in {'EDIT_GPENCIL', 'PAINT_GPENCIL', 'SCULPT_GPENCIL', 'WEIGHT_GPENCIL'}
        return not gp_edit and edit_object and mode_string == 'EDIT_MESH'

    def draw(self, context):
        layout = self.layout
        #layout.operator('cgcookie.retopoflow')
        if VIEW3D_MT_RetopoFlow.is_editing_target(context):
            self.draw_tools(context)
        else:
            self.draw_new(context)
        layout.separator()
        layout.operator('cgcookie.retopoflow_recover')

    def draw_new(self, context):
        layout = self.layout
        layout.operator('cgcookie.retopoflow_new')

    def draw_tools(self, context):
        layout = self.layout
        for c in customs:
            layout.operator(c.bl_idname)

    #############################################################################
    # the following two methods add/remove RF to/from the main 3D View menu
    # NOTE: this is a total hack: hijacked the draw function!
    @staticmethod
    def menu_add():
        VIEW3D_MT_RetopoFlow.menu_remove()
        VIEW3D_MT_RetopoFlow._menu_original = bpy.types.VIEW3D_MT_editor_menus.draw_collapsible
        def hijacked(context, layout):
            obj = context.active_object
            mode_string = context.mode
            edit_object = context.edit_object
            gp_edit = obj and obj.mode in {'EDIT_GPENCIL', 'PAINT_GPENCIL', 'SCULPT_GPENCIL', 'WEIGHT_GPENCIL'}

            VIEW3D_MT_RetopoFlow._menu_original(context, layout)

            row = layout.row(align=True)
            if VIEW3D_MT_RetopoFlow.is_editing_target(context):
                row.operator('cgcookie.retopoflow', text="", icon='DECORATE_KEYFRAME')
            row.menu("VIEW3D_MT_RetopoFlow", text="RetopoFlow")
        bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = hijacked
    @staticmethod
    def menu_remove():
        if not hasattr(VIEW3D_MT_RetopoFlow, '_menu_original'): return
        bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = VIEW3D_MT_RetopoFlow._menu_original
        del VIEW3D_MT_RetopoFlow._menu_original


# registration
classes = [
    VIEW3D_MT_RetopoFlow,
    VIEW3D_OT_RetopoFlow,
    VIEW3D_OT_RetopoFlow_New,
    VIEW3D_OT_RetopoFlow_Recover,
] + customs

def register():
    for cls in classes: bpy.utils.register_class(cls)
    VIEW3D_MT_RetopoFlow.menu_add()

def unregister():
    VIEW3D_MT_RetopoFlow.menu_remove()
    for cls in reversed(classes): bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
