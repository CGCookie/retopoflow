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


def draw_autosave(self, context, layout):
    layout.use_property_split = True
    layout.use_property_decorate = False

    layout.prop(self, 'enable_autosave', text='Enable AutoSave')
    layout.separator()

    layout.separator(type='LINE', factor=1)
    layout.separator(type='SPACE')
    layout.label(text='Retopoflow AutoSave is similar to Blender Auto-Save, except')
    layout.label(text='Blender Auto-Save does NOT run when in Edit Mode while')
    layout.label(text='Retopoflow AutoSave does.')
    layout.label(text='')
    layout.label(text='NOTE: Disable Retopoflow AutoSave', icon='WARNING_LARGE')
    layout.label(text='if you have another auto save add-on enabled or')
    layout.label(text='if you do not want auto save working in Edit Mode.')
    layout.separator(type='SPACE')
    layout.separator(type='LINE', factor=1)
