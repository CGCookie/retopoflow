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

# pyright: reportUninitializedInstanceVariable = false
# pyright: reportImplicitOverride = false
# pyright: reportUnusedParameter = false
# pyright: reportUnannotatedClassAttribute = false

from bpy.types import (
    Context,
    UILayout,
    WorkSpaceTool,
    Event,
)

from ..rfglobals import RFGlobals
from ..rfoperators.topo_rotate import RFOperator_TopoRotate
from ..rftool_base import RFTool_Base

from ...addon_common.common.resetter import Resetter

from ..common.bpy_helper import bpy_ops_retopoflow, BL_SPACE_TYPES, BL_REGION_TYPES, BL_OPTIONS
from ..common.bmesh import get_bmesh_emesh
from ..common.icons import get_path_to_blender_icon
from ..common.operator import (
    execute_operator,
    RFOperator,
    RFOperator_Execute, RFOperator_Invoke,
    RFKeyMaps,
    chain_rf_keymaps,
    poll_retopoflow,
    BLKeyMaps,
)

from ..rfoverlay_base import RFOverlay_Base
from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel
from ..rfpanels.mirror_panel import draw_mirror_panel
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.help_panel import draw_help_panel


# from . import patches_templates
from .patches_logic import Patches_Logic


class RFOperator_Patches_Type_Toggle(RFOperator_Invoke):
    bl_idname : str = 'retopoflow.patches_type_toggle'
    bl_label : str = 'Toggle vertex type'
    bl_description : str = 'Toggle type of hovered vertex'
    bl_options : BL_OPTIONS = { 'INTERNAL', 'UNDO', 'DEPENDS_ON_CURSOR' }

    rf_keymaps : RFKeyMaps = [
        (
            bl_idname,
            { 'type': 'LEFTMOUSE', 'value': 'CLICK', 'ctrl': 1, 'shift': 0 },
            None
        ),
    ]

    def invoke(self, context : Context, event : Event) -> set[str]:
        result = Patches_Logic.pvert_type_toggle(context, event)
        context.area.tag_redraw()
        return { 'FINISHED' } if result else { 'CANCELLED' }


class RFOperator_Patches_Type_Set(RFOperator_Invoke):
    bl_idname : str = 'retopoflow.patches_type_set'
    bl_label : str = 'Set vertex type'
    bl_description : str = 'Set type of hovered vertex'
    bl_options : BL_OPTIONS = { 'INTERNAL', 'UNDO', 'DEPENDS_ON_CURSOR' }

    rf_keymaps : RFKeyMaps = [
        (
            bl_idname,
            { 'type': 'O', 'value': 'PRESS', 'ctrl': 0, 'shift': 0 },
            None
        ),
        (
            bl_idname,
            { 'type': 'ZERO', 'value': 'PRESS', 'ctrl': 0, 'shift': 0 },
            None
        ),
        (
            bl_idname,
            { 'type': 'ONE', 'value': 'PRESS', 'ctrl': 0, 'shift': 0 },
            None
        ),
        (
            bl_idname,
            { 'type': 'TWO', 'value': 'PRESS', 'ctrl': 0, 'shift': 0 },
            None
        ),
        (
            bl_idname,
            { 'type': 'THREE', 'value': 'PRESS', 'ctrl': 0, 'shift': 0 },
            None
        ),
        (
            bl_idname,
            { 'type': 'FOUR', 'value': 'PRESS', 'ctrl': 0, 'shift': 0 },
            None
        ),
    ]

    def invoke(self, context : Context, event : Event) -> set[str]:
        result = Patches_Logic.pvert_type_set(context, event)
        context.area.tag_redraw()
        return { 'FINISHED' } if result else { 'CANCELLED' }

class RFOperator_Patches_Loop_Insert(RFOperator_Invoke):
    bl_idname : str = 'retopoflow.patches_loop_insert'
    bl_label : str = 'Insert loop'
    bl_description : str = 'Inserts a loop at ring of hovered ring'
    bl_options : BL_OPTIONS = { 'INTERNAL', 'UNDO', 'DEPENDS_ON_CURSOR' }

    rf_keymaps : RFKeyMaps = [
        (
            bl_idname,
            { 'type': 'I', 'value': 'PRESS', 'ctrl': 0, 'shift': 0 },
            None
        ),
    ]

    def invoke(self, context : Context, event : Event) -> set[str]:
        print('trying to insert loop')
        result = Patches_Logic.insert_loop(context, event)
        print(f'  {result=}')
        context.area.tag_redraw()
        return { 'FINISHED' } if result else { 'CANCELLED' }


class RFOperator_Patches_Create_Patch(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_create'
    bl_label : str = 'Create patch'
    bl_description : str = 'Create the patch'
    bl_options : BL_OPTIONS = { 'INTERNAL', 'UNDO', 'REGISTER' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'F', 'value': 'PRESS' }, {'km_label': 'Insert Patch'} ),
    ]

    def execute(self, context : Context) -> set[str]:
        Patches_Logic.commit()
        return { 'FINISHED' }


class RFOperator_Patches_Reset(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_reset'
    bl_label : str = 'Reset patch info'
    bl_description : str = 'Reset patch information'
    bl_options : BL_OPTIONS = { 'INTERNAL', 'UNDO' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'ESC', 'value': 'PRESS' }, {'km_label': 'Reset Corners'} ),
    ]

    def execute(self, context : Context) -> set[str]:
        Patches_Logic.reset()
        return { 'FINISHED' }

class RFOperator_Patches_Increase_OuterRingOffset(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_increase_outerringoffset'
    bl_label : str = 'Increase Offset'
    bl_description : str = 'Increase outer ring offset in patch'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'LEFT_ARROW', 'value': 'PRESS' }, {'km_label': 'Offset+' } ),
    ]

    def execute(self, context : Context) -> set[str]:
        Patches_Logic.increase_outer_ring_offset()
        Patches_Logic.update(force_rebuild=True)
        context.area.tag_redraw()
        return { 'FINISHED' }

class RFOperator_Patches_Decrease_OuterRingOffset(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_decrease_outerringoffset'
    bl_label : str = 'Decrease Offset'
    bl_description : str = 'Decrease outer ring offset in patch'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'RIGHT_ARROW', 'value': 'PRESS' }, {'km_label': 'Offset-'} ),
    ]

    def execute(self, context : Context) -> set[str]:
        Patches_Logic.decrease_outer_ring_offset()
        Patches_Logic.update(force_rebuild=True)
        context.area.tag_redraw()
        return { 'FINISHED' }

class RFOperator_Patches_Toggle_Cap(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_toggle_cap'
    bl_label : str = 'Toggle Cap'
    bl_description : str = 'Toggle cap in patch'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'C', 'value': 'PRESS' }, {'km_label': 'Cap'} ),
    ]

    def execute(self, context : Context) -> set[str]:
        Patches_Logic.toggle_cap()
        Patches_Logic.update(force_rebuild=True)
        context.area.tag_redraw()
        return { 'FINISHED' }

class RFOperator_Patches_Unset_Loops(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_unset_loops'
    bl_label : str = 'Unset loops'
    bl_description : str = 'Unset loop count in patch'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'EQUAL', 'value': 'PRESS' }, {'km_label': 'Unset Loops'} ),
    ]

    def execute(self, context : Context) -> set[str]:
        Patches_Logic.unset_loops()
        Patches_Logic.update(force_rebuild=True)
        context.area.tag_redraw()
        return { 'FINISHED' }

class RFOperator_Patches_Increase_Loops(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_increase_loops'
    bl_label : str = 'Increase loops'
    bl_description : str = 'Increase loops in patch'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'NUMPAD_PLUS', 'value': 'PRESS' }, {'km_label': 'Loops+' } ),
    ]

    def execute(self, context : Context) -> set[str]:
        Patches_Logic.increase_loops()
        Patches_Logic.update(force_rebuild=True)
        context.area.tag_redraw()
        return { 'FINISHED' }

class RFOperator_Patches_Decrease_Loops(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_decrease_loops'
    bl_label : str = 'Decrease loops'
    bl_description : str = 'Decrease loops in patch'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'NUMPAD_MINUS', 'value': 'PRESS' }, {'km_label': 'Loops-'} ),
    ]

    def execute(self, context : Context) -> set[str]:
        Patches_Logic.decrease_loops()
        Patches_Logic.update(force_rebuild=True)
        context.area.tag_redraw()
        return { 'FINISHED' }

class RFOperator_Patches(RFOperator):
    bl_idname : str = 'retopoflow.patches'
    bl_label : str = 'Patches'
    bl_description : str = 'Insert patch'
    bl_space_type : BL_SPACE_TYPES = 'VIEW_3D'
    bl_region_type : BL_REGION_TYPES = 'TOOLS'
    bl_options : BL_OPTIONS = set()

    rf_keymaps : RFKeyMaps = []

    def init(self, context : Context, event : Event):
        print('RFOperator_Patches.init')

    def finish(self, context : Context):
        print('RFOperator_Patches.finish')

    def update(self, context : Context, event : Event) -> set[str]:
        print('RFOperator_Patches.update')
        return {'PASS_THROUGH'}


class RFOperator_Patches_Selection_Overlay(RFOverlay_Base, RFOperator):
    bl_idname : str = 'retopoflow.patches_selection_overlay'
    bl_label : str = 'Patches Selection Overlay'
    bl_description : str = 'Overlay info about selected loops and strips'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    logic : Patches_Logic

    def is_done(self):
        RFCore = RFGlobals.RFCore_None
        return RFCore.selected_RFTool_idname != 'retopoflow.patches' if RFCore else True

    @classmethod
    def activate(cls):
        _ = bpy_ops_retopoflow('patches_selection_overlay', 'INVOKE_DEFAULT')

    def init(self, _context : Context, _event : Event):
        self.logic = Patches_Logic()

    def update(self, context : Context, event : Event) -> set[str]:
        return {'CANCELLED'} if self.is_done() else {'PASS_THROUGH'}

    def draw_postpixel_overlay(self):
        self.logic.update()
        self.logic.draw()




class RFTool_Patches(RFTool_Base):
    bl_idname : str = "retopoflow.patches"
    bl_label : str = "Patches"
    bl_description : str = "Fill holes and retopologize patches."
    bl_icon : str = get_path_to_blender_icon('patches')
    bl_widget : None = None

    rf_operator_idname : str | None = 'retopoflow.patches'

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_Patches,
        RFOperator_Patches_Reset,
        RFOperator_Patches_Increase_OuterRingOffset,
        RFOperator_Patches_Decrease_OuterRingOffset,
        RFOperator_Patches_Toggle_Cap,
        RFOperator_Patches_Unset_Loops,
        RFOperator_Patches_Increase_Loops,
        RFOperator_Patches_Decrease_Loops,
        RFOperator_Patches_Type_Toggle,
        RFOperator_Patches_Type_Set,
        RFOperator_Patches_Loop_Insert,
        RFOperator_Patches_Create_Patch,

        # RFOperator_Patches_Insert_Template,
        # RFOperator_PatchesBrush_Adjust,

        RFOperator_TopoRotate,
    )

    rf_overlay : type[RFOverlay_Base] | None = RFOperator_Patches_Selection_Overlay
    # rf_brush : RFBrush_Patches = RFBrush_Patches()

    @staticmethod
    def draw_settings(context : Context, layout : UILayout, tool : WorkSpaceTool):
        # patches_templates.draw_settings(context, layout, tool)

        if context.region.type == 'TOOL_HEADER':
            pass
        else:
            draw_cleanup_panel(context, layout)
            draw_tweaking_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context : Context):
        cls.resetter = Resetter('Patches')
        # patches_templates.activate(cls, context)

    @classmethod
    def deactivate(cls, context : Context):
        if cls.resetter:
            cls.resetter.reset()

@execute_operator('switch_to_patches', 'RetopoFlow: Switch to Patches', fn_poll=poll_retopoflow)
def switch_rftool(context : Context):
    RFTool_Patches.activate_tool(context)
