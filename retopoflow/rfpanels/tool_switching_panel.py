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

def draw_tool_switching_options(context, layout):
    prefs = RF_Prefs.get_prefs(context)

    layout.use_property_split = True
    row = layout.row(heading='Automatic')
    row.prop(prefs, 'setup_automerge')
    layout.prop(prefs, 'setup_fade_inactive')
    layout.prop(prefs, 'setup_object_wires')
    layout.prop(prefs, 'setup_retopo_overlay')
    layout.prop(prefs, 'setup_selection_mode')
    layout.prop(prefs, 'setup_snapping')

    if context.area.type == 'PREFERENCES':
        layout.separator()
        layout.label(text=('You can assign a custom hotkey for any tool by:'), icon='INFO')
        row=layout.split(factor=0.4)
        row.separator()
        col = row.column()
        col.label(text=('1. Right Clicking'))
        col.label(text=('2. Choosing Assign Shortcut'))
        col.label(text=('3. Saving Preferences'))
    else:
        layout.operator('retopoflow.applysettings')
