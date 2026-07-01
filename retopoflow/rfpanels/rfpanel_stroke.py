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


class RFMenu_PT_StrokeOptions(bpy.types.Panel):
    bl_label = 'Stroke'
    bl_idname = 'RF_PT_StrokeOptions'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    # bl_ui_units_x = 10

    def draw(self, context):
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        if not tool or tool.idname != 'retopoflow.strokes': return
        props = tool.operator_properties('retopoflow.strokes')
        layout = self.layout
        layout.use_property_decorate = False
        layout.use_property_split = True

        layout.label(text='Stroke')
        layout.prop(props, 'snap_radius', text="Snap")
        layout.prop(props, 'stroke_smoothing', text='Stabilize', slider=True)
        col = layout.column(align=True)
        col.prop(props, 'smooth_density0', text='Spacing Start', slider=True)
        col.prop(props, 'smooth_density1', text='End', slider=True)


def register():
    bpy.utils.register_class(RFMenu_PT_StrokeOptions)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_StrokeOptions)