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

from ..common.operator import RFOperator


class RFOperator_Relax_QuickSwitch(RFOperator):
    bl_idname      = f'retopoflow.quickswitch_to_relax'
    bl_label       = f'Retopoflow: Quick switch to Relax'
    bl_description = f'Quick switch to Relax'
    bl_space_type  = 'VIEW_3D'
    bl_space_type  = 'TOOLS'
    bl_options     = {'INTERNAL'}

    rf_keymaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK_DRAG', 'ctrl': 0, 'shift': 1}, None),
    ]

    def init(self, context, event):
        self.running = False
        self.prev_tool = self.RFCore.selected_RFTool_idname

    def update(self, context, event):
        if not self.running:
            self.running = True
            bpy.ops.wm.tool_set_by_id(name='retopoflow.relax')
            bpy.ops.retopoflow.relax('INVOKE_DEFAULT')
            return {'PASS_THROUGH'}

        op = context.window.modal_operators[0]
        if 'quickswitch_to_relax' not in op.bl_idname:
            # still relaxing
            return {'PASS_THROUGH'}

        # finished relaxing
        self.running = False
        self.RFCore.switch_to_tool(self.prev_tool)
        return {'FINISHED'}

class RFOperator_Tweak_QuickSwitch(RFOperator):
    bl_idname      = f'retopoflow.quickswitch_to_tweak'
    bl_label       = f'Retopoflow: Quick switch to Tweak'
    bl_description = f'Quick switch to Tweak'
    bl_space_type  = 'VIEW_3D'
    bl_space_type  = 'TOOLS'
    bl_options     = {'INTERNAL'}

    rf_keymaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK_DRAG', 'ctrl': 1, 'shift': 1}, None),
    ]

    def init(self, context, event):
        self.running = False
        self.prev_tool = self.RFCore.selected_RFTool_idname

    def update(self, context, event):
        if not self.running:
            self.running = True
            bpy.ops.wm.tool_set_by_id(name='retopoflow.tweak')
            bpy.ops.retopoflow.tweak('INVOKE_DEFAULT')
            return {'PASS_THROUGH'}

        op = context.window.modal_operators[0]
        if 'quickswitch_to_tweak' not in op.bl_idname:
            # still tweaking
            return {'PASS_THROUGH'}

        # finished tweaking
        self.running = False
        self.RFCore.switch_to_tool(self.prev_tool)
        return {'FINISHED'}
