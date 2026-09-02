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
import time
from typing import cast

import bpy
from bpy.types import Context, Event

from ..rfglobals import RFGlobals
from ..common.operator import RFOperator, RFKeyMaps
from ..common.bpy_helper import BpyOperatorCallable, bpy_ops_retopoflow


_op_prop_names_cache: dict[str, list[str]] = {}



def _get_operator_properties_from_current_tool(tool_name: str, op_idname: str) -> dict[str, ...]:
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
                property_names = [
                    name
                    for name in target_op_class.__annotations__.keys()
                    if name not in {'rna_type'} and not name.startswith('_')
                ]
            else:
                property_names = []

            _op_prop_names_cache[tool_name] = property_names

        # Build kwargs dict with current property values
        kwargs : dict[str, ...] = {}
        for prop_name in property_names:
            if hasattr(current_props, prop_name):
                kwargs[prop_name] = getattr(current_props, prop_name)

        return kwargs
    except Exception as _exception:
        pass
    return {}


def quick_switch_tool(tool_name: str):
    """Get all properties from the currently active tool that can be applied to the target operator."""
    op_idname = f'retopoflow.{tool_name}'
    _ = bpy.ops.wm.tool_set_by_id(name=op_idname)
    tool = cast(BpyOperatorCallable, getattr(bpy.ops.retopoflow, tool_name))
    tool('INVOKE_DEFAULT', **_get_operator_properties_from_current_tool(tool_name, op_idname))


class RFOperator_Relax_QuickSwitch(RFOperator):
    bl_idname      : str = 'retopoflow.quickswitch_to_relax'
    bl_label       : str = 'Retopoflow: Quick switch to Relax'
    bl_description : str = 'Quick switch to Relax'
    bl_space_type  : str = 'VIEW_3D'
    bl_region_type : str = 'TOOLS'
    bl_options : set[str] = {'INTERNAL'}

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK_DRAG', 'ctrl': 0, 'shift': 1}, None),
    ]

    running : bool # pyright: ignore[reportUninitializedInstanceVariable]
    prev_tool : str | None # pyright: ignore[reportUninitializedInstanceVariable]

    def init(self, context : Context, event : Event):
        RFCore = RFGlobals.RFCore

        self.running = False
        self.prev_tool = RFCore.selected_RFTool_idname

    def update(self, context : Context, event : Event) -> set[str]:
        RFCore = RFGlobals.RFCore

        if not self.running:
            self.running = True
            quick_switch_tool('relax')
            return {'PASS_THROUGH'}

        # since RFCore is running (above test), then there _should_ be
        # at least one modal operator active
        op = context.window.modal_operators[0]
        if 'quickswitch_to_relax' not in op.bl_idname:
            # still relaxing
            return {'PASS_THROUGH'}

        # finished relaxing
        self.running = False
        RFCore.switch_to_tool(self.prev_tool)
        return {'FINISHED'}


class RFOperator_LegacyPatches_QuickSwitch(RFOperator):
    """Fill a patch when F is tapped and get the full interactive preview when it is held. """
    bl_idname      : str = 'retopoflow.quickswitch_to_legacy_patches'
    bl_label       : str = 'Retopoflow: Quick switch to Patches'
    bl_description : str = 'Fill a patch from the selected boundary edges. Hold to preview it first'
    bl_space_type  : str = 'VIEW_3D'
    bl_region_type : str = 'TOOLS'
    bl_options : set[str] = {'INTERNAL'}

    # Patches rebuilds its preview from a draw callback and will not do so while it believes another
    # operator is moving the mesh about. Tell it this op is harmless.
    rf_patches_passive : bool = True

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'F', 'value': 'PRESS'}, {'km_label': 'Fill Patch'}),
    ]

    prev_tool : str | None # pyright: ignore[reportUninitializedInstanceVariable]
    switched : bool # pyright: ignore[reportUninitializedInstanceVariable]
    restored : bool # pyright: ignore[reportUninitializedInstanceVariable]
    started : float # pyright: ignore[reportUninitializedInstanceVariable]

    # How long F must be down before it counts as a hold rather than a tap
    HOLD_TO_PREVIEW = 0.25

    def init(self, context : Context, event : Event):
        from ..rftool_legacy_patches.legacy_patches_logic import LegacyPatches_Logic
        self.prev_tool = RFGlobals.RFCore.selected_RFTool_idname
        self.switched = self.restored = False
        self.started = time.time()
        # the cursor picks which way a wire run steps and which edges a corner vert pairs up
        LegacyPatches_Logic.mouse = (event.mouse_x, event.mouse_y)

        # A hold with a still cursor and no key repeat sends no events at all, and the preview would
        # never appear. Ask for one modal call once the threshold is past. The flag is a list rather
        # than the operator itself, so a finished operator is not kept alive by the timer.
        alive = [True]
        self._alive = alive
        def wake():
            if alive[0]:
                try:
                    RFOperator.tickle(bpy.context)
                except Exception:
                    pass
            return None
        _ = bpy.app.timers.register(wake, first_interval=self.HOLD_TO_PREVIEW)

    def update(self, context : Context, event : Event) -> set[str]:
        if event.type == 'F' and event.value == 'RELEASE':
            self._fill()
            self._restore()
            return {'FINISHED'}
        # the key repeating is the clearest sign it is being held; the clock covers a platform that
        # does not repeat, and the tickle above guarantees one event to read it on
        repeat = event.type == 'F' and event.value == 'PRESS'
        if repeat or time.time() - self.started >= self.HOLD_TO_PREVIEW:
            self._switch()
        # Swallow the repeats. Passed on, each one runs the fill again and steps the patch again,
        # which is not what holding a key to look at something should do.
        return {'RUNNING_MODAL'} if repeat else {'PASS_THROUGH'}

    def _switch(self):
        from ..rftool_legacy_patches.legacy_patches import RFTool_LegacyPatches
        if self.switched: return
        self.switched = True
        # Skip the tool's usual switch to edge select mode on the way in. This is meant to be a look
        # at the patch, not an edit of the selection, and changing select mode changes it.
        RFTool_LegacyPatches.quick_switch = True
        RFGlobals.RFCore.switch_to_tool(RFTool_LegacyPatches.bl_idname)

    def _fill(self):
        if 'FINISHED' in bpy_ops_retopoflow('legacy_patches_fill', 'INVOKE_DEFAULT'): return
        # Patches had nothing to make of this selection, so the keypress belongs to Blender's own F,
        # which is where it would have gone without us
        try:
            _ = bpy.ops.mesh.edge_face_add()
        except RuntimeError:
            pass

    def finish(self, context : Context):
        self._restore()     # also covers being cancelled out from under us

    def _restore(self):
        from ..rftool_legacy_patches.legacy_patches import RFTool_LegacyPatches
        if self.restored: return
        self.restored = True
        self._alive[0] = False
        RFTool_LegacyPatches.quick_switch = False
        if self.switched: RFGlobals.RFCore.switch_to_tool(self.prev_tool)


class RFOperator_Tweak_QuickSwitch(RFOperator):
    bl_idname      : str = 'retopoflow.quickswitch_to_tweak'
    bl_label       : str = 'Retopoflow: Quick switch to Tweak'
    bl_description : str = 'Quick switch to Tweak'
    bl_space_type  : str = 'VIEW_3D'
    bl_region_type : str = 'TOOLS'
    bl_options : set[str] = {'INTERNAL'}

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK_DRAG', 'ctrl': 1, 'shift': 1}, None),
    ]

    running : bool # pyright: ignore[reportUninitializedInstanceVariable]
    prev_tool : str | None # pyright: ignore[reportUninitializedInstanceVariable]

    def init(self, context : Context, event : Event):
        RFCore = RFGlobals.RFCore

        self.running = False
        self.prev_tool = RFCore.selected_RFTool_idname

    def update(self, context : Context, event : Event) -> set[str]:
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
