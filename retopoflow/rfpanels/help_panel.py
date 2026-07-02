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
from ..common.icons import Icon
from ..common.interface import draw_section_indent

def draw_help(context : Context, layout : UILayout):
    row = layout.row()
    draw_section_indent(context, row)
    col = row.column()

    col.operator(
        'wm.url_open', text='Read the Docs', icon='HELP'
    ).url = 'https://docs.retopoflow.com'

    col.operator(
        'wm.url_open', text='Report an Issue', icon='ERROR'
    ).url = 'https://orangeturbine.com/#contact'

    col.operator(
        "wm.url_open", text='View on Superhive', icon_value=Icon.SUPERHIVE.icon_id
    ).url = 'https://blendermarket.com/products/retopoflow'


def draw_help_panel(context : Context, layout : UILayout):
    header, panel = layout.panel(idname='help_panel_common', default_closed=True)
    header.label(text="Help")
    if panel:
        draw_help(context, panel)


class RFMenu_PT_Help(bpy.types.Panel):
    bl_label = "Help"
    bl_idname = "RF_PT_Help"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context : Context):
        if not self.layout:
            return
        draw_help(context, self.layout)

def register():
    bpy.utils.register_class(RFMenu_PT_Help)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_Help)