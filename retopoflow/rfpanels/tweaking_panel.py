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
from bpy.types import Context, UILayout
from typing import cast
from ..preferences import RF_Prefs
from ..common.interface import draw_section_header
from ..rftool_base import RFTool_Base


def draw_tweaking_options(context : Context, layout : UILayout):
    if not context.space_data:
        return

    props = RF_Prefs.get_prefs(context)

    layout.use_property_split = True
    layout.use_property_decorate = False

    if context.space_data.type != 'PREFERENCES':
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        if 'retopoflow' in tool.idname:
            # get RFTool_Base class corresponding to Blender WorkSpaceTool
            # NOTE: tool.idname might not match an operator, so using rf_operator_idname
            rftool = RFTool_Base.get_rftool_by_workspacetool(tool)
            if rftool and rftool.rf_operator_idname:
                try:
                    # WorkSpaceTool.operator_properties throws a RunTime Exception if
                    # the specified tool does not have any properties (2026.06.28)
                    tool_props = tool.operator_properties(rftool.rf_operator_idname)
                except Exception as _exception:
                    tool_props = None

                if tool_props:
                    loops = hasattr(tool_props, 'select_loops')
                    curves = hasattr(tool_props, 'show_curve_handles')
                    if loops or curves:
                        col = layout.column()
                        draw_section_header(context, col, tool_props.bl_rna.name)
                        if loops: col.prop(tool_props, 'select_loops', text='Loops Mode')
                        if curves: col.prop(tool_props, 'show_curve_handles', text='Curve Handles')

    grid = layout.grid_flow(even_columns=True, even_rows=False)

    col = grid.column()
    draw_section_header(context, col, 'Selection')
    col.prop(props, 'tweaking_distance', text='Distance')
    row = col.row(heading='Auto Select')
    row.prop(props, 'tweaking_move_hovered_mouse', text='Mouse')
    col.prop(props, 'tweaking_move_hovered_keyboard', text='Keyboard')

    col = grid.column()
    draw_section_header(context, col, 'Transform')

    snapping = context.scene.retopoflow.snapping
    use_native = (
        snapping.snap_vertex or snapping.snap_edge or snapping.snap_edge_center
        or snapping.snap_edge_perpendicular or snapping.snap_face_center
    )
    if not use_native:
        col2 = col.column()
        col2.row(heading='Normals').prop(props, 'tweaking_update_normals', text='Update')
        col.separator()

    if context.area.type != 'PREFERENCES':
        col.separator()
        row = col.row(heading='Auto Merge')
        row.prop(context.scene.tool_settings, 'use_mesh_automerge', text='', toggle=False)
        row.separator(factor=0.5)
        row2 = row.row()
        row2.enabled = context.scene.tool_settings.use_mesh_automerge
        row2.prop(context.scene.tool_settings, 'double_threshold', text='')


def draw_tweaking_panel(context : Context, layout : UILayout):
    header, panel = layout.panel(idname='tweak_panel_common', default_closed=True)
    header.label(text="Tweaking")
    if panel:
        draw_tweaking_options(context, panel)


class RFMenu_PT_TweakCommon(bpy.types.Panel):
    bl_label = "Tweaking"
    bl_idname = "RF_PT_TweakCommon"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 12

    def draw(self, context : Context):
        draw_tweaking_options(context, self.layout)


def register():
    bpy.utils.register_class(RFMenu_PT_TweakCommon)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_TweakCommon)
