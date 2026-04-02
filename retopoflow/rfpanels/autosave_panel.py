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

    layout.prop(self, 'enable_autosave', text='Edit Mode Auto-Save')
    layout.separator()

    layout.separator(type='LINE', factor=1)
    layout.separator(type='SPACE')
    if context.region.width > 1000:
        layout.label(text="Blender's Auto-Save does NOT run when in Edit Mode. Retopoflow's AutoSave does.")
    else:
        layout.label(text="Blender's Auto-Save does NOT run when in Edit Mode.")
        layout.label(text="Retopoflow's Auto-Save does.")
    layout.separator(type='SPACE')
    if context.region.width > 1750:
        layout.label(text=(
            'Disable Retopoflow AutoSave if you have another auto save add-on enabled, '
            'notice too much lag, or do not want auto save working in Edit Mode.'
        ))
    elif context.region.width > 1000:
        layout.label(text='Disable Retopoflow AutoSave if you have another auto save add-on enabled, ')
        layout.label(text='notice too much lag, or do not want auto save working in Edit Mode.')
    else:
        layout.separator(type='SPACE')
        layout.label(text='Disable Retopoflow AutoSave if you')
        layout.label(text='• have another auto save add-on enabled,')
        layout.label(text='• notice too much lag, or')
        layout.label(text='• do not want auto save working in Edit Mode.')
    layout.separator(type='SPACE')
    layout.separator(type='LINE', factor=1)
