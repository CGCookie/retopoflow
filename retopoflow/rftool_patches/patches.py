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
from mathutils import Vector


from ..rfglobals import RFGlobals
from ..rfoperators.topo_rotate import RFOperator_TopoRotate
from ..rftool_base import RFTool_Base

from ...addon_common.common.resetter import Resetter
from ..common.raycast import (
    raycast_valid_sources,
    mouse_from_event,
)

from ..common.bpy_helper import bpy_ops_retopoflow, BL_SPACE_TYPES, BL_REGION_TYPES, BL_OPTIONS
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


class RFOperator_Patches_Insert_Corner(RFOperator_Invoke):
    bl_idname : str = 'retopoflow.patches_insert_corner'
    bl_label : str = 'Insert corner'
    bl_description : str = 'Insert a new corner for patch'
    bl_options : BL_OPTIONS = { 'INTERNAL', 'UNDO' }

    rf_keymaps : RFKeyMaps = [
        (
            bl_idname,
            { 'type': 'LEFTMOUSE', 'value': 'CLICK', 'ctrl': 1, 'shift': 0 },
            None
        ),
    ]

    def invoke(self, context : Context, event : Event) -> set[str]:
        context.area.tag_redraw()
        return {'FINISHED'} if Patches_Logic.insert_corner(context, event) else {'CANCELLED'}
        # RFGlobals.RFCore.tag_redraw_areas()


class RFOperator_Patches_Commit_Patch(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_commit'
    bl_label : str = 'Create patch'
    bl_description : str = 'Create the patch'
    bl_options : BL_OPTIONS = { 'INTERNAL', 'UNDO' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'F', 'value': 'PRESS' }, None ),
    ]

    def execute(self, context : Context) -> set[str]:
        print('X'*100)
        print('committing patch')
        print('X'*100)
        Patches_Logic.commit()
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
        pass

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
    bl_description : str = "Retopologize holes!"
    bl_icon : str = get_path_to_blender_icon('patches')
    bl_widget : None = None

    rf_operator_idname : str | None = 'retopoflow.patches'

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_Patches,
        # RFOperator_Patches_Insert_Corner,
        RFOperator_Patches_Insert_Corner,
        RFOperator_Patches_Commit_Patch,
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
