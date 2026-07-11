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

from bpy.types import Context, UILayout, bpy_struct


def draw_autosave(self : bpy_struct, context : Context, layout : UILayout):
    layout.use_property_split = True
    layout.use_property_decorate = False

    layout.prop(self, 'enable_autosave', text='Edit Mode Auto-Save')
    layout.separator()

    layout.separator(type='LINE', factor=1)
    layout.separator(type='SPACE')

    if context.region.width > 1000:
        layout.label(text="Blender's Auto-Save does NOT run in Edit Mode. Retopoflow's Auto-Save does.")
    else:
        layout.label(text="Blender's Auto-Save does NOT run in Edit Mode.")
        layout.label(text="Retopoflow's Auto-Save does.")

    if context.region.width > 1750:
        layout.label(text=(
            'Disable Retopoflow Auto-Save if you have another auto-save add-on enabled, '
            'notice too much lag, enjoy risk, or do not want to Auto-Save in Edit Mode.'
        ))
    elif context.region.width > 1000:
        layout.label(text='Disable Retopoflow Auto-Save if you have another auto-save add-on enabled, ')
        layout.label(text='notice too much lag, enjoy risk, or do not want to auto-save in Edit Mode.')
    else:
        layout.separator(type='SPACE')
        col = layout.column(align=True)
        col.label(text='Disable Retopoflow Auto-Save if you')
        col.label(text='• have another auto-save add-on enabled')
        col.label(text='• notice too much lag')
        col.label(text='• enjoy risk or')
        col.label(text='• do not want to auto-save in Edit Mode.')

    layout.separator(type='SPACE')
    layout.separator(type='LINE', factor=1)
