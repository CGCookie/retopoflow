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
from ..common.interface import draw_expandable_enum


def draw_pinning_options(context, layout):
    prefs = RF_Prefs.get_prefs(context)
    props = context.scene.retopoflow

    layout.use_property_split = True
    layout.use_property_decorate = False
    draw_expandable_enum(context, layout, props, 'mask_creases', text='Creases')
    draw_expandable_enum(context, layout, props, 'mask_seams', text='Seams')
    draw_expandable_enum(context, layout, props, 'mask_sharps', text='Sharps')
    layout.row(heading='Include').prop(props, 'include_corners')
    if prefs.setup_pinning:
        layout.prop(props, 'include_pinned')
    layout.prop(props, 'include_occluded')
    prefs = RF_Prefs.get_prefs(context)
    if prefs.setup_pinning:
        layout.separator()
        row = layout.row()
        row.operator('retopoflow.pinverts', text='Pin', icon='PINNED')
        row.operator('retopoflow.unpinverts', text='Unpin', icon='UNPINNED')


class RFMenu_PT_Pinning(bpy.types.Panel):
    bl_label = "Pinning"
    bl_idname = "RF_PT_Pinning"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        draw_pinning_options(context, self.layout)


def draw_masking_options(context, layout):
    props = context.scene.retopoflow

    layout.use_property_split = True
    layout.use_property_decorate = False

    draw_expandable_enum(context, layout, props, 'mask_selected', text='Selected')
    draw_expandable_enum(context, layout, props, 'mask_boundary', text='Boundary')
    # layout.prop(props, 'mask_symmetry', text="Symmetry")  # TODO: Implement
    draw_pinning_options(context, layout)

def draw_masking_panel(context, layout):
    header, panel = layout.panel(idname='tweak_panel_common', default_closed=False)
    header.label(text="Masking")
    if panel:
        draw_masking_options(context, panel)

class RFMenu_PT_Masking(bpy.types.Panel):
    bl_label = "Masking"
    bl_idname = "RF_PT_Masking"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        draw_masking_options(context, self.layout)


def register():
    bpy.utils.register_class(RFMenu_PT_Masking)
    bpy.utils.register_class(RFMenu_PT_Pinning)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_Masking)
    bpy.utils.unregister_class(RFMenu_PT_Pinning)