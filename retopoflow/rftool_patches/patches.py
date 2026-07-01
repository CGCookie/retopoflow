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

import bpy
from bpy.types import (
    Context,
    UILayout,
    WorkSpaceTool,
    Event,
)
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bmesh.types import BMVert, BMEdge
from mathutils import Vector

from ..rfglobals import RFGlobals
from ..rfoperators.topo_rotate import RFOperator_TopoRotate
from ..rftool_base import RFTool_Base

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.resetter import Resetter

from ..common.bpy_helper import bpy_ops_retopoflow, BL_SPACE_TYPES, BL_REGION_TYPES
from ..common.bmesh import get_bmesh_emesh, bme_midpoint, get_boundary_strips_cycles
from ..common.drawing import Drawing
from ..common.icons import get_path_to_blender_icon
from ..common.operator import (
    execute_operator,
    RFOperator,
    RFOperator_Execute,
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



class RFOperator_Patches_Insert(RFOperator_Execute):
    bl_idname : str = 'retopoflow.patches_insert'
    bl_label : str = 'Insert Patch'
    bl_description : str = 'Fill in hole with patch'
    bl_options : set[str] = set()

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'F', 'value': 'PRESS'}, None)
    ]
    rf_status : dict[str, Sequence[str]] = { }

    def execute(self, context : Context) -> set[str]:
        print('RFOperator_Patches_Insert.execute')
        return {'FINISHED'}


class RFOperator_Patches(RFOperator):
    bl_idname : str = 'retopoflow.patches'
    bl_label : str = 'Patches'
    bl_description : str = 'Insert patch'
    bl_space_type : BL_SPACE_TYPES = 'VIEW_3D'
    bl_region_type : BL_REGION_TYPES = 'TOOLS'
    bl_options : set[str] = set()

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
    bl_options : set[str] = { 'INTERNAL' }

    depsgraph_version : int = -42

    # Points that will act as corners for patch, where keys are either a...
    # - int >= 0 corresponding to index of BMVert or
    # - int <  0 indicating a corner that is not yet associated with BMVert (will be new BMVert on commit)
    # and values are location in world space.
    #
    # IMPORTANT: must not keep reference to bmesh elements, because they will invalidate
    #       whenever depsgraph changes!  Instead, keep track of them via their indices.
    corners : dict[int, Vector] = {}

    def is_done(self):
        RFCore = RFGlobals.RFCore_None
        return RFCore.selected_RFTool_idname != 'retopoflow.patches' if RFCore else True

    @classmethod
    def activate(cls):
        _ = bpy_ops_retopoflow('patches_selection_overlay', 'INVOKE_DEFAULT')

    def init(self, _context : Context, _event : Event):
        self.depsgraph_version = -42

    def update(self, context : Context, event : Event) -> set[str]:
        return {'CANCELLED'} if self.is_done() else {'PASS_THROUGH'}

    def draw_postpixel_overlay(self):
        RFCore = RFGlobals.RFCore_None
        context = bpy.context
        if not RFCore or self.is_done() or not context.edit_object:
            return

        rgn, r3d = context.region, context.region_data
        M = context.edit_object.matrix_world

        if self.depsgraph_version != RFCore.depsgraph_version:
            self.depsgraph_version = RFCore.depsgraph_version
            bm, _ = get_bmesh_emesh(bpy.context, ensure_lookup_tables=True)
            if isinstance(bmv_active := bm.select_history.active, BMVert):
                # add active element to collection of corner BMVerts
                self.corners[bmv_active.index] = M @ bmv_active.co
            len_verts = len(bm.verts)
            self.corners = {
                i: pt
                for (i, pt) in self.corners.items()
                if i < len_verts and (bmv := bm.verts[i]) and bmv.select
            }

        Drawing.draw2D_points(
            context,
            [ location_3d_to_region_2d(rgn, r3d, pt) for pt in self.corners.values() ],
            (1, 1, 0, 1),
            radius=12,
        )






class RFTool_Patches(RFTool_Base):
    bl_idname : str = "retopoflow.patches"
    bl_label : str = "Patches"
    bl_description : str = "Retopologize holes!"
    bl_icon : str = get_path_to_blender_icon('patches')
    bl_widget : None = None
    rf_operator_idname : str | None = 'retopoflow.patches'

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_Patches,
        RFOperator_Patches_Insert,
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
