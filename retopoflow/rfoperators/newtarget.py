'''
Copyright (C) 2024 CG Cookie
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
import bl_ui

from bpy_extras.object_utils import object_data_add


class RFCore_NewTarget_Cursor(bpy.types.Operator):
    """Create new target object+mesh at the 3D Cursor and start RetopoFlow"""
    bl_idname = "retopoflow.newtarget_cursor"
    bl_label = "RF: New target at Cursor"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nCreate new target mesh based on the cursor and start RetopoFlow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    rf_label = "New target at Cursor"
    rf_icon = 'CURSOR'

    RFCore = None

    @staticmethod
    def draw_menu_item(self, context):
        self.layout.operator(
            RFCore_NewTarget_Cursor.bl_idname,
            text=RFCore_NewTarget_Cursor.rf_label,
            icon=RFCore_NewTarget_Cursor.rf_icon,
        )

    @classmethod
    def poll(cls, context):
        if not context.region or context.region.type != 'WINDOW': return False
        if not context.space_data or context.space_data.type != 'VIEW_3D': return False
        # check we are not in mesh editmode
        if context.mode == 'EDIT_MESH': return False
        # make sure we have source meshes
        # if not retopoflow.RetopoFlow.get_sources(): return False
        # all seems good!
        return True

    def invoke(self, context, event):
        auto_edit_mode = context.preferences.edit.use_enter_edit_mode # working around blender bug, see https://github.com/CGCookie/retopoflow/issues/786
        context.preferences.edit.use_enter_edit_mode = False

        # for o in bpy.data.objects: o.select_set(False)
        for o in context.view_layer.objects: o.select_set(False)

        mesh = bpy.data.meshes.new('RetopoFlow')
        obj = object_data_add(context, mesh, name='RetopoFlow')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        # if matrix_world:
        #     obj.matrix_world = matrix_world

        bpy.ops.object.mode_set(mode='EDIT')

        bpy.context.preferences.edit.use_enter_edit_mode = auto_edit_mode

        bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', self.RFCore.default_RFTool.bl_idname)

        return {'FINISHED'}


class RFCore_NewTarget_Active(bpy.types.Operator):
    """Create new target object+mesh at the 3D Cursor and start RetopoFlow"""
    bl_idname = "retopoflow.newtarget_active"
    bl_label = "RF: New target at Active"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nCreate new target mesh based on the cursor and start RetopoFlow"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    rf_label = "New target at Active"
    rf_icon = 'PIVOT_ACTIVE' # 'MOD_MESHDEFORM'

    RFCore = None

    @staticmethod
    def draw_menu_item(self, context):
        self.layout.operator(
            RFCore_NewTarget_Active.bl_idname,
            text=RFCore_NewTarget_Active.rf_label,
            icon=RFCore_NewTarget_Active.rf_icon,
        )

    @classmethod
    def poll(cls, context):
        if not context.region or context.region.type != 'WINDOW': return False
        if not context.space_data or context.space_data.type != 'VIEW_3D': return False
        # check we are not in mesh editmode
        if context.mode == 'EDIT_MESH': return False
        if not context.view_layer.objects.active: return False
        # make sure we have source meshes
        # if not retopoflow.RetopoFlow.get_sources(): return False
        # all seems good!
        return True

    def invoke(self, context, event):
        matrix_world = context.view_layer.objects.active.matrix_world

        auto_edit_mode = context.preferences.edit.use_enter_edit_mode # working around blender bug, see https://github.com/CGCookie/retopoflow/issues/786
        context.preferences.edit.use_enter_edit_mode = False

        # for o in bpy.data.objects: o.select_set(False)
        for o in context.view_layer.objects: o.select_set(False)

        mesh = bpy.data.meshes.new('RetopoFlow')
        obj = object_data_add(context, mesh, name='RetopoFlow')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        obj.matrix_world = matrix_world

        bpy.ops.object.mode_set(mode='EDIT')

        bpy.context.preferences.edit.use_enter_edit_mode = auto_edit_mode

        bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', self.RFCore.default_RFTool.bl_idname)

        return {'FINISHED'}
