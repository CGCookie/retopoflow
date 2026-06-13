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
from ..rfglobals import RFGlobals
from ..preferences import RF_Prefs
from ..common.interface import draw_section_header, draw_section_indent

def draw_tool_switching_options(context, layout):
    prefs = RF_Prefs.get_prefs(context)

    layout.use_property_split = True

    col = layout.column(align=True)
    row = col.row(heading='Automatic')
    row.prop(prefs, 'setup_automerge')
    col.prop(prefs, 'setup_component_size')
    col.prop(prefs, 'setup_fade_inactive')
    col.prop(prefs, 'setup_object_wires')
    col.prop(prefs, 'setup_retopo_overlay')
    col.prop(prefs, 'setup_pinning')
    col.prop(prefs, 'setup_selection_adjustments')
    col.prop(prefs, 'setup_selection_mode')
    col.prop(prefs, 'setup_snapping')

    if context.area.type == 'PREFERENCES':
        layout.separator(type='SPACE')
        layout.separator(type='LINE', factor=1)
        layout.separator(type='SPACE')
        draw_section_header(context, layout, text='You can assign a custom hotkey for any tool by:', icon='INFO')
        row = layout.row(align=True)
        draw_section_indent(context, row)
        draw_section_indent(context, row)
        col = row.column()
        col.label(text=('1. Right Clicking'))
        col.label(text=('2. Choosing Assign Shortcut'))
        col.label(text=('3. Saving Preferences'))
        layout.separator(type='SPACE')
        layout.separator(type='LINE', factor=1)
    else:
        RFCore = RFGlobals.RFCore_None

        row = layout.row()
        draw_section_indent(context, row)
        col = row.column()
        col.separator(type='SPACE', factor=2)

        row2 = col.row(align=False)
        row2.operator('retopoflow.applysettings')
        col2 = row2.column()
        col2.enabled = RFCore and RFCore.resetter._backup != {}
        col2.operator('retopoflow.restoresettings', text='', icon='RECOVER_LAST')

        col.separator(type='LINE', factor=4)
        col.operator('retopoflow.resettoolsettings', icon='LOOP_BACK')
        col.separator(type='SPACE')
