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

def draw_display_options(context, layout):
    props = RF_Prefs.get_prefs(context)
    theme = context.preferences.themes[0].view_3d

    grid = layout.grid_flow(even_columns=True, even_rows=True)
    grid.use_property_split = True
    grid.use_property_decorate = False

    col = grid.column(align=True)
    col.prop(theme, 'face_retopology', text='Overlay Color')
    if hasattr(context.space_data, 'overlay'):
        col.prop(context.space_data.overlay, 'retopology_offset', text='Offset')
    #col.prop(props, 'highlight_color', text='Highlight')
    col.separator()
    col = grid.column(align=True)
    row = col.row(heading='Expand')
    row.prop(props, 'expand_tools', text='Tools')
    col.prop(props, 'expand_masking', text='Masking Options')


def draw_display_panel(context, layout):
    header, panel = layout.panel(idname='display_panel_common', default_closed=True)
    header.label(text="Display")
    if panel:
        draw_display_options(context, panel)


class RFMenu_PT_Masking(bpy.types.Panel):
    bl_label = "Display"
    bl_idname = "RF_PT_Display"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        draw_display_options(context, self.layout)

def register():
    bpy.utils.register_class(RFMenu_PT_Masking)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_Masking)