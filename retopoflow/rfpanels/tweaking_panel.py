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


def draw_tweaking_options(context, layout):
    props = RF_Prefs.get_prefs(context)

    grid = layout.grid_flow(even_columns=True, even_rows=False)
    grid.use_property_split = True
    grid.use_property_decorate = False

    if context.area.type != 'PREFERENCES':
        col = grid.column()
        col.label(text='Auto Merge')
        col.prop(context.scene.tool_settings, 'use_mesh_automerge', text='Enable', toggle=False)
        row = col.row()
        row.enabled = context.scene.tool_settings.use_mesh_automerge
        row.prop(context.scene.tool_settings, 'double_threshold', text='Threshold')
        col.separator()

    col = grid.column()
    col.label(text='Selection')
    col.prop(props, 'tweaking_distance', text='Distance')
    row = col.row(heading='Mouse')
    row.prop(props, 'tweaking_move_hovered_mouse', text='Auto Select')
    row = col.row(heading='Keyboard')
    row.prop(props, 'tweaking_move_hovered_keyboard', text='Auto Select')
    col.separator()

    col = grid.column()
    col.label(text='Transform')
    col.prop(props, 'tweaking_use_native', text='Native')


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

    def draw(self, context):
        draw_tweaking_options(context, self.layout)


def register():
    bpy.utils.register_class(RFMenu_PT_TweakCommon)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_TweakCommon)