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

def draw_general_options(context, layout):
    props = RF_Prefs.get_prefs(context)
    props_scene = context.scene.retopoflow
    theme = context.preferences.themes[0].view_3d

    grid = layout.grid_flow(even_columns=True, even_rows=False)
    grid.use_property_split = True
    grid.use_property_decorate = False

    if hasattr(context.space_data, 'overlay'):
        col = grid.column()
        col.label(text='Snapping')
        row = col.row(heading='Exclude')
        row.prop(context.scene.tool_settings, 'use_snap_selectable', text='Non-Selectable')
        col.separator()

    col = grid.column()
    col.label(text='Viewport')
    if hasattr(context.space_data, 'overlay'):
        row = col.split(factor=0.4)
        row.alignment='RIGHT'
        row.label(text='Overlay')
        split = row.split(align=True, factor=1/3)
        split.prop(theme, 'face_retopology', text='')
        split.prop(props_scene, 'retopo_offset', text='')
        #split.prop(context.space_data.overlay, 'retopology_offset', text='')
        row = col.row(heading='Fade Sources')
        row.prop(context.space_data.overlay, 'show_fade_inactive', text='')
        row2 = row.row()
        row2.enabled = context.space_data.overlay.show_fade_inactive
        row2.prop(context.space_data.overlay, 'fade_inactive_alpha', text='')
    else:
        col.prop(theme, 'face_retopology', text='Overlay')
    #col.prop(props, 'highlight_color', text='Highlight')
    col.separator()

    col = grid.column(align=True)
    col.label(text='Interface')
    row = col.row(heading='Expand')
    row.prop(props, 'expand_tools', text='Tools')
    col.prop(props, 'expand_masking', text='Masking Options')
    col.prop(props, 'expand_mirror', text='Mirror Axes')


def draw_general_panel(context, layout):
    header, panel = layout.panel(idname='general_panel_common', default_closed=True)
    header.label(text="General")
    if panel:
        draw_general_options(context, panel)


class RFMenu_PT_General(bpy.types.Panel):
    bl_label = "General"
    bl_idname = "RF_PT_General"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 12

    def draw(self, context):
        draw_general_options(context, self.layout)

def register():
    bpy.utils.register_class(RFMenu_PT_General)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_General)