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
from ..preferences import RF_Prefs
from ..common.interface import draw_section_header


def draw_tweaking_options(context, layout):
    props = RF_Prefs.get_prefs(context)
    tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
    tool_props = tool.operator_properties(tool.idname)

    grid = layout.grid_flow(even_columns=True, even_rows=False)
    grid.use_property_split = True
    grid.use_property_decorate = False

    select_loops = getattr(tool_props, 'select_loops', False)
    if select_loops:
        col = grid.column()
        draw_section_header(context, col, tool_props.bl_rna.name)
        col.prop(tool_props, 'select_loops', text='Loops Mode')

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


def draw_tweaking_panel(context, layout):
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

    def draw(self, context):
        draw_tweaking_options(context, self.layout)


def register():
    bpy.utils.register_class(RFMenu_PT_TweakCommon)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_TweakCommon)