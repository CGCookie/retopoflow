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
    from ..preferences import RF_Prefs
    props = RF_Prefs.get_prefs(context)

    grid = layout.grid_flow(even_columns=True, even_rows=False)
    grid.use_property_split = True
    grid.use_property_decorate = False

    col = grid.column()
    row = col.row(heading='Merge')
    row.prop(props, 'cleaning_use_merge', text='By Distance')
    row = col.row()
    row.enabled = props.cleaning_use_merge
    row.prop(props, 'cleaning_merge_threshold', text='Threshold')
    col.separator()

    col = grid.column()
    row = col.row(heading='Delete')
    row.prop(props, 'cleaning_use_delete_loose', text='Loose')
    row = col.row(heading='Fill')
    row.prop(props, 'cleaning_use_fill_holes', text='Holes')
    row = col.row(heading='Recalculate')
    row.prop(props, 'cleaning_use_recalculate_normals', text='Normals')
    row = col.row(heading='Snap')
    row.prop(props, 'cleaning_use_snap', text='To Source')
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

    def draw(self, context):
        draw_cleanup_options(context, self.layout)


def register():
    bpy.utils.register_class(RFMenu_PT_MeshCleanup)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_MeshCleanup)