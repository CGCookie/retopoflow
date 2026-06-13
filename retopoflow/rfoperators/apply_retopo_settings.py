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


from bpy.types import Context, Operator
from ..common.operator import RFRegisterClass
from ..rfglobals import RFGlobals




class RFOperator_ApplyRetopoSettings(RFRegisterClass, Operator):
    bl_idname = "retopoflow.applysettings"
    bl_label = "Apply Retopology Settings"
    bl_description = "Apply the retopology settings from Retopoflow to Blender for use in other Edit Mode tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'UNDO'}

    rf_label = "Apply Retopology Settings"

    @classmethod
    def poll(cls, context : Context) -> bool:
        return context.mode == 'EDIT_MESH'

    def execute(self, context : Context) -> set[str]:
        RFCore = RFGlobals.RFCore_None
        if not RFCore: return {'CANCELLED'}
        RFCore.resetter_clear_all()
        return {'FINISHED'}


class RFOperator_RestoreRetopoSettings(RFRegisterClass, Operator):
    bl_idname = "retopoflow.restoresettings"
    bl_label = "Restore Retopology Settings"
    bl_description = "Restore the retopology settings to non-Retopoflow tools if you accidentally applied them"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'UNDO'}

    rf_label = "Restore Retopology Settings"

    @classmethod
    def poll(cls, context : Context) -> bool:
        return context.mode == 'EDIT_MESH'

    def execute(self, context : Context) -> set[str]:
        RFCore = RFGlobals.RFCore_None
        if not RFCore: return {'CANCELLED'}
        RFCore.resetter_restore_all()
        return {'FINISHED'}
