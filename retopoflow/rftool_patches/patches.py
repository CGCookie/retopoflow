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


from collections.abc import Sequence

from bpy.types import (
    Context,
    UILayout,
    WorkSpaceTool,
)

from ..rfoperators.topo_rotate import RFOperator_TopoRotate
from ..rftool_base import RFTool_Base

from ...addon_common.common.resetter import Resetter

from ..common.icons import get_path_to_blender_icon
from ..common.operator import (
    execute_operator,
    RFOperator_Execute,
    RFKeyMaps,
    chain_rf_keymaps,
    poll_retopoflow,
    BLKeyMaps,
)

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel
from ..rfpanels.mirror_panel import draw_mirror_panel
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.help_panel import draw_help_panel






class RFOperator_Patches_Insert(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_insert'
    bl_label : str = 'Patches'
    bl_description : str = 'Fill in hole with patch'
    bl_options : set[str] = set()
    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'F', 'value': 'PRESS'}, None)
    ]
    rf_status : dict[str, Sequence[str]] = { }

    def execute(self, context : Context) -> set[str]:
        print('execute!')
        return {'FINISHED'}





class RFTool_Patches(RFTool_Base):
    bl_idname : str = "retopoflow.patches"
    bl_label : str = "Patches"
    bl_description : str = "Retopologize holes!"
    bl_icon : str = get_path_to_blender_icon('patches')
    bl_widget : None = None
    rf_operator_idname : str | None = 'retopoflow.patches_insert'

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_Patches_Insert,
        # RFOperator_Patches_Insert_Template,
        # RFOperator_PatchesBrush_Adjust,
        RFOperator_TopoRotate,
    )

    # rf_brush : RFBrush_Patches = RFBrush_Patches()

    @staticmethod
    def draw_settings(context : Context, layout : UILayout, tool : WorkSpaceTool):
        # props_patches : OperatorProperties = tool.operator_properties(RFOperator_Patches_Insert_Template.bl_idname)

        if context.region.type == 'TOOL_HEADER':
            pass
            # layout.label(text="Insert:")
            # row = layout.row(align=True)
            # row.prop(props_patches, 'orientation', text='')
            # if props_patches.orientation in {'RAYCAST', 'SCREEN'}:
            #     row.prop(props_patches, 'scale', text='')

        else:
            # header, panel = layout.panel(idname='patches_insert_panel', default_closed=False)
            # header.label(text="Insert")
            # if panel:
            #     panel.prop(props_patches, 'orientation', text='Method')
            #     if props_patches.orientation in {'RAYCAST', 'SCREEN'}:
            #         panel.prop(props_patches, 'scale', text='Radius')

            draw_cleanup_panel(context, layout)
            draw_tweaking_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context : Context):
        cls.resetter = Resetter('Patches')

        # attempts = 3

        # @BPY_Timers.register(first_interval=0.25)
        # def delayed_settings(): # pyright: ignore[reportUnusedFunction]
        #     nonlocal attempts

        #     assert cls.resetter

        #     space_data = context.space_data
        #     asset_libs = context.preferences.filepaths.asset_libraries

        #     if 'Retopoflow Patches Templates' not in asset_libs:
        #         _ = bpy.types.AssetLibraryCollection.new(
        #             name="Retopoflow Patches Templates",
        #             directory=ASSETS_PATH,
        #         )
        #         # asset_libs['Retopoflow Assets'].import_method = 'LINK'

        #     # this can happen if context is not quite right, so find space that we can
        #     # ex: after saving
        #     if hasattr(space_data, 'show_region_asset_shelf'):
        #         try:
        #             cls.resetter['space_data.show_region_asset_shelf'] = True
        #             return
        #         except Exception as _exception:
        #             pass

        #     attempts -= 1
        #     return 0.25 if attempts > 0 else None

        # Patches_Template.activate(context, None, None, None)  # asset shelf will have nothing selected initially
        # #return super().activate(context)

    @classmethod
    def deactivate(cls, context : Context):
        if cls.resetter:
            cls.resetter.reset()

@execute_operator('switch_to_patches', 'RetopoFlow: Switch to Patches', fn_poll=poll_retopoflow)
def switch_rftool(context : Context):
    RFTool_Patches.activate_tool(context)

