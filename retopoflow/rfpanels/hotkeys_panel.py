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
    layout.use_property_split = False
    layout.use_property_decorate = False

    pie_kmi = get_user_keymap_item(context, 'RF_MT_Tools')
    draw_keymap_options(self, layout, pie_kmi, 'Retopoflow Pie Menu', in_RF_tools='optional')
    layout.separator()

    # each of these also binds inside individual RF tools' own keymaps, so narrow to the general one
    fill_kmi = get_user_keymap_item(context, 'retopoflow.legacy_patches_fill', km_name='Mesh')
    draw_keymap_options(self, layout, fill_kmi, 'Auto Fill', in_RF_tools='optional', trigger_prop='fill_tool_context')
    topo_rotate_kmi = get_user_keymap_item(context, 'retopoflow.toporotate', km_name='Mesh')
    draw_keymap_options(self, layout, topo_rotate_kmi, 'Rotate Topology', in_RF_tools='optional', trigger_prop='toporotate_tool_context')
    twist_loop_kmi = get_user_keymap_item(context, 'retopoflow.twist_loop', km_name='Mesh')
    draw_keymap_options(self, layout, twist_loop_kmi, 'Twist Loops', in_RF_tools='optional', trigger_prop='twist_loop_tool_context')
    diamond_bevel_kmi = get_user_keymap_item(context, 'retopoflow.insert_diamond_junction', km_name='Mesh')
    draw_keymap_options(self, layout, diamond_bevel_kmi, 'Diamond Bevel', in_RF_tools='optional', trigger_prop='diamond_bevel_tool_context')
    relax_kmi = get_user_keymap_item(context, 'retopoflow.relax_selected', km_name='Mesh')
    draw_keymap_options(self, layout, relax_kmi, 'Relax', in_RF_tools='optional', trigger_prop='relax_tool_context')
    even_kmi = get_user_keymap_item(context, 'retopoflow.space_evenly', km_name='Mesh')
    draw_keymap_options(self, layout, even_kmi, 'Even', in_RF_tools='optional', trigger_prop='even_tool_context')
    # poll blocks it whenever RF is running, so it only ever fires outside a Retopoflow tool
    edit_as_curve_kmi = get_user_keymap_item(context, 'retopoflow.edit_as_curve', km_name='Mesh')
    draw_keymap_options(self, layout, edit_as_curve_kmi, 'Edit as Curve', in_RF_tools='never')
    layout.separator()

    # poll requires RFCore to be running, so these only ever fire inside a Retopoflow tool
    pinverts_kmi = get_user_keymap_item(context, 'retopoflow.pinverts')
    draw_keymap_options(self, layout, pinverts_kmi, 'Pin Verts', in_RF_tools='only')
    unpinverts_kmi = get_user_keymap_item(context, 'retopoflow.unpinverts')
    draw_keymap_options(self, layout, unpinverts_kmi, 'Unpin Verts', in_RF_tools='only')
    layout.separator()

    # poll requires RFCore to be running, so these only ever fire inside a Retopoflow tool
    launch_help_kmi = get_user_keymap_item(context, 'retopoflow.launch_help')
    draw_keymap_options(self, layout, launch_help_kmi, 'Open Docs', in_RF_tools='only')
    launch_newissue_kmi = get_user_keymap_item(context, 'retopoflow.launch_newissue')
    draw_keymap_options(self, layout, launch_newissue_kmi, 'Report Issue', in_RF_tools='only')
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
