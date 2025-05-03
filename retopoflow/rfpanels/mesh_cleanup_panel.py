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


def draw_cleanup_options(context, layout, draw_operators=True):
    props = context.scene.retopoflow

    grid = layout.grid_flow(even_columns=True, even_rows=False)
    grid.use_property_split = True
    grid.use_property_decorate = False
    
    col = grid.column()
    row = col.row(heading='Merge')
    row = col.row(heading='Snap')
    row.prop(props, 'cleaning_use_snap', text='To Surface')
    col.separator()

    col = grid.column()
    row = col.row(heading='Merge')
    row.prop(props, 'cleaning_use_merge', text='By Distance')
    row = col.row()
    row.enabled = props.cleaning_use_merge
    row.prop(props, 'cleaning_merge_threshold', text='Threshold')
    col.separator()

    col = grid.column(align=True)
    row = col.row(heading='Normals')
    row.prop(props, 'cleaning_use_recalculate_normals', text='Recalculate')
    row = col.row()
    row.enabled = props.cleaning_use_recalculate_normals
    row.prop(props, 'cleaning_flip_normals', text='Inside')
    col.separator()

    col = grid.column()
    row = col.row(heading='Delete')
    row.prop(props, 'cleaning_use_delete_loose', text='Loose Vertices')
    col.prop(props, 'cleaning_use_delete_faceless', text='Faceless Edges')
    col.prop(props, 'cleaning_use_delete_interior', text='Interior Faces')
    col.prop(props, 'cleaning_use_delete_ngons', text='N-Gons')
    col.separator()

    col = grid.column()
    row = col.row(heading='Triangulate')
    row.prop(props, 'cleaning_use_triangulate_concave', text='Concave Faces')
    col.prop(props, 'cleaning_use_triangulate_nonplanar', text='Non-Planar Faces')
    row = col.row()
    row.enabled = not props.cleaning_use_delete_ngons
    row.prop(props, 'cleaning_use_triangulate_ngons', text='N-Gons')
    col.separator()

    row = col.row(heading='Fill')
    row.prop(props, 'cleaning_use_fill_holes', text='Holes')

    if draw_operators:
        layout.separator()
        row = layout.row()
        row.operator('retopoflow.meshcleanup', text='Selected').affect_all=False
        row.operator('retopoflow.meshcleanup', text='All').affect_all=True


def draw_cleanup_panel(context, layout):
    header, panel = layout.panel(idname='retopoflow_cleanup_panel', default_closed=True)
    header.label(text="Clean Up")
    if panel:
        draw_cleanup_options(context, panel)


class RFMenu_PT_MeshCleanup(bpy.types.Panel):
    bl_label = "Mesh Clean Up"
    bl_idname = "RF_PT_MeshCleanup"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 11

    def draw(self, context):
        draw_cleanup_options(context, self.layout)


def register():
    bpy.utils.register_class(RFMenu_PT_MeshCleanup)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_MeshCleanup)