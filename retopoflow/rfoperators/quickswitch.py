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
import importlib

import bpy

from ..rfglobals import RFGlobals
from ..common.operator import RFOperator


_op_prop_names_cache: dict[str, list[str]] = {}



def _get_operator_properties_from_current_tool(tool_name: str, op_idname: str) -> dict:
    try:
        # Get current tool.
        current_tool = bpy.context.workspace.tools.from_space_view3d_mode('EDIT_MESH')
        if not current_tool:
            return {}

        # Only get properties if current tool is Relax or Tweak
        if current_tool.idname != op_idname:
            return {}

        # Get properties from the current tool's operator
        current_props = current_tool.operator_properties(current_tool.idname)

        if property_names := _op_prop_names_cache.get(tool_name):
            pass
        else:
            # Import the target operator class to get its property annotations
            module = importlib.import_module(f'..rftool_{tool_name}.{tool_name}', package=__package__)
            target_op_class = getattr(module, f'RFOperator_{tool_name.title()}')

            # Get all property names from the target operator class
            if hasattr(target_op_class, '__annotations__'):
                property_names = [name for name in target_op_class.__annotations__.keys() if name not in {'rna_type'} and not name.startswith('_')]
            else:
                property_names = []

            _op_prop_names_cache[tool_name] = property_names

        # Build kwargs dict with current property values
        kwargs = {}
        for prop_name in property_names:
            if hasattr(current_props, prop_name):
                kwargs[prop_name] = getattr(current_props, prop_name)

        return kwargs
    except:
        pass
    return {}

def quick_switch_tool(tool_name: str):
    """Get all properties from the currently active tool that can be applied to the target operator."""
    op_idname = f'retopoflow.{tool_name}'
    bpy.ops.wm.tool_set_by_id(name=op_idname)
    getattr(bpy.ops.retopoflow, tool_name)('INVOKE_DEFAULT', **_get_operator_properties_from_current_tool(tool_name, op_idname))


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
        RFCore = RFGlobals.RFCore

        self.running = False
        self.prev_tool = RFCore.selected_RFTool_idname

    def update(self, context, event):
        RFCore = RFGlobals.RFCore

        if not self.running:
            self.running = True
            quick_switch_tool('relax')
            return {'PASS_THROUGH'}

        op = context.window.modal_operators[0]
        if 'quickswitch_to_relax' not in op.bl_idname:
            # still relaxing
            return {'PASS_THROUGH'}

        # finished relaxing
        self.running = False
        RFCore.switch_to_tool(self.prev_tool)
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
        RFCore = RFGlobals.RFCore

        self.running = False
        self.prev_tool = RFCore.selected_RFTool_idname

    def update(self, context, event):
        RFCore = RFGlobals.RFCore

        if not self.running:
            self.running = True
            quick_switch_tool('tweak')
            return {'PASS_THROUGH'}

        op = context.window.modal_operators[0]
        if 'quickswitch_to_tweak' not in op.bl_idname:
            # still tweaking
            return {'PASS_THROUGH'}

        # finished tweaking
        self.running = False
        RFCore.switch_to_tool(self.prev_tool)
        return {'FINISHED'}
