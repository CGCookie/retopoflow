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
from ..rfoperators.mirror import get_mirror_mod


def draw_mirror_options(context, layout, draw_operators=True):
    props = context.scene.retopoflow
    obj = context.active_object
    props_obj = obj.retopoflow
    mod = get_mirror_mod(obj)

    layout.use_property_split = True
    layout.use_property_decorate = False

    layout.label(text='Modifier')

    row=layout.row(align=True, heading='Axis')
    if mod:
        row.prop(mod, 'use_axis', index=0, text='X', toggle=True)
        row.prop(mod, 'use_axis', index=1, text='Y', toggle=True)
        row.prop(mod, 'use_axis', index=2, text='Z', toggle=True)
        col = layout.column()
        col.enabled = mod.use_axis[0] or mod.use_axis[1] or mod.use_axis[2]
        col.prop(mod, 'use_clip', text='Clipping')
    else:
        row.prop(props_obj, 'mirror_axis', index=0, text='X', toggle=True)
        row.prop(props_obj, 'mirror_axis', index=1, text='Y', toggle=True)
        row.prop(props_obj, 'mirror_axis', index=2, text='Z', toggle=True)
        col = layout.column()
        col.enabled = props_obj.mirror_axis[0] or props_obj.mirror_axis[1] or props_obj.mirror_axis[2]

    if mod:
        col.label(text='Preview')
        col.prop(props, 'mirror_display')

        if props.mirror_display == 'SOLID' or props.mirror_display == 'WIRE':
            col.prop(props, 'mirror_opacity', text='Opacity', slider=True)
            if props.mirror_display == 'SOLID':
                col.prop(props, 'mirror_wires')
            if props.mirror_display == 'WIRE' and bpy.app.version >= (4, 3, 0):
                col.prop(props, 'mirror_wire_thickness', text='Thickness')
            col.separator()

            col.prop(props, 'retopo_offset', text='Overlay')
            col.prop(props, 'mirror_displace', slider=True)
            row = col.row()
            row.enabled = props.mirror_displace != 0
            row.prop(props, 'mirror_displace_boundaries', text='Boundaries')
            row = col.row()
            row.enabled = props.mirror_displace != 0 and props.mirror_displace_boundaries
            row.prop(props, 'mirror_displace_connected', text='Connected')

            if context.space_data.shading.color_type not in ['MATERIAL', 'TEXTURE']:
                col.separator()
                box = col.box()
                message = box.column(align=True)
                row=message.row()
                row.alignment='CENTER'
                row.label(text=('Axis colors can only be seen when'))
                row=message.row()
                row.alignment='CENTER'
                row.label(text=('viewport is set to Material or Texture'))

        layout.separator()
        layout.operator('retopoflow.applymirror')
    else:
        layout.operator('retopoflow.addmirror')


def draw_mirror_panel(context, layout):
    header, panel = layout.panel(idname='retopoflow_mirror_panel', default_closed=True)
    header.label(text="Mirror")
    if panel:
        draw_mirror_options(context, panel)


def draw_mirror_popover(context, layout):
    prefs = RF_Prefs.get_prefs(context)
    obj = context.active_object
    mod = get_mirror_mod(obj)

    row = layout.row(align=True)
    if prefs.expand_mirror:
        button = row.row(align=True)
        button.scale_x = 0.75
        if mod:
            button.prop(mod, 'use_axis', index=0, text='X', toggle=True)
            button.prop(mod, 'use_axis', index=1, text='Y', toggle=True)
            button.prop(mod, 'use_axis', index=2, text='Z', toggle=True)
        else:
            button.prop(obj.retopoflow, 'mirror_axis', index=0, text='X', toggle=True)
            button.prop(obj.retopoflow, 'mirror_axis', index=1, text='Y', toggle=True)
            button.prop(obj.retopoflow, 'mirror_axis', index=2, text='Z', toggle=True)
    row.popover('RF_PT_Mirror', text='', icon='MOD_MIRROR')


class RFMenu_PT_Mirror(bpy.types.Panel):
    bl_label = "Mirror"
    bl_idname = "RF_PT_Mirror"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 12

    def draw(self, context):
        draw_mirror_options(context, self.layout)


def register():
    bpy.utils.register_class(RFMenu_PT_Mirror)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_Mirror)