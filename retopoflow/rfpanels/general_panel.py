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
from .interface_panel import draw_ui_options
from .tool_switching_panel import draw_tool_switching_options

def draw_general_options(context, layout):

    if hasattr(context.space_data, 'overlay'):
        header, panel = layout.panel(idname='RF_snapping_prefs', default_closed=False)
        header.label(text="Snapping")
        if panel:
            panel.use_property_split = True
            panel.use_property_decorate = False
            row = panel.row(heading='Exclude')
            row.prop(context.scene.tool_settings, 'use_snap_selectable', text='Non-Selectable')

    header, panel = layout.panel(idname='RF_interface_prefs', default_closed=False)
    header.label(text="Interface")
    if panel:
        draw_ui_options(context, panel)

    header, panel = layout.panel(idname='RF_general_tools_panel', default_closed=True)
    header.label(text='Tools')
    if panel:
        draw_tool_switching_options(context, panel)


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