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

import bpy
from ..common.interface import draw_keymap_options, draw_section_header, draw_section_indent
from ...config.keymaps import get_user_keymap_item


def draw_hotkeys(self, context, layout):
    layout.use_property_split = True
    layout.use_property_decorate = False

    row = layout.row(heading='Retopoflow Pie Menu')
    pie_kmi = get_user_keymap_item(context, 'RF_MT_Tools')
    draw_keymap_options(row, pie_kmi)
    row = layout.row()
    row.enabled = pie_kmi and pie_kmi.active
    row.prop(self, 'pie_tool_context', text='Triggers From', expand=False)
    layout.separator()

    # the tool keymap binds the same operator, so narrow the lookup to the general one
    row = layout.row(heading='Fill Patches')
    fill_kmi = get_user_keymap_item(context, 'retopoflow.legacy_patches_fill', km_name='Mesh')
    draw_keymap_options(row, fill_kmi)
    row = layout.row()
    row.enabled = bool(fill_kmi and fill_kmi.active)
    row.prop(self, 'fill_tool_context', text='Triggers From', expand=False)
    layout.separator()

    row = layout.row(heading='Pin Verts')
    draw_keymap_options(row, get_user_keymap_item(context, 'retopoflow.pinverts'))
    row = layout.row(heading='Unpin Verts')
    draw_keymap_options(row, get_user_keymap_item(context, 'retopoflow.unpinverts'))
    layout.separator()

    row = layout.row(heading='Open Docs')
    draw_keymap_options(row, get_user_keymap_item(context, 'retopoflow.launch_help'))
    row = layout.row(heading='Report Issue')
    draw_keymap_options(row, get_user_keymap_item(context, 'retopoflow.launch_newissue'))
    layout.separator()

    layout.separator(type='LINE', factor=1)
    layout.separator(type='SPACE')
    draw_section_header(context, layout, 'You can change the hotkey for any other action by:')
    row = layout.row(align=True)
    draw_section_indent(context, row)
    draw_section_indent(context, row)
    col = row.column()
    col.label(text=("1. Opening Blender's keymap preferences"))
    col.label(text=('2. Searching for Retopoflow'))
    col.label(text=('3. Changing the keymap'))
    col.label(text=('3. Saving Preferences'))
    draw_section_header(context, layout, 'Hotkey adjustments cannot be guaranteed to work.')
    layout.separator(type='SPACE')
    layout.separator(type='LINE', factor=1)
