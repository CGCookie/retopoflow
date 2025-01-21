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

import bpy, bmesh

from ..common.operator import RFRegisterClass
from ..common.raycast import nearest_point_valid_sources


class RFOperator_MeshCleanup(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.meshcleanup"
    bl_label = "Clean Up Mesh"
    bl_description = "A handy macro for quicly running several retopology cleanup operations at once"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    rf_label = "Clean Up Mesh"

    def draw(self, context):
        draw_cleanup_options(self.layout, draw_button=False)

    def execute(self, context):
        props = bpy.context.window_manager.retopoflow

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)

        mesh = context.active_object.data
        bm = bmesh.new()
        bm.from_mesh(mesh)

        verts = [ v for v in bm.verts if v.select and not v.hide ]
        edges = [ e for e in bm.edges if e.select and not e.hide ]
        faces = [ f for f in bm.faces if f.select and not f.hide ]

        if props.cleaning_use_merge:
            bmesh.ops.remove_doubles(bm, verts=verts, dist=props.cleaning_merge_threshold)

        if props.cleaning_use_delete_loose:
            for v in bm.verts:
                if not v.link_edges:
                    bm.verts.remove(v)

        if props.cleaning_use_fill_holes:
            bmesh.ops.holes_fill(bm, edges=edges, sides=4)

        if props.cleaning_use_recalculate_normals:
            bmesh.ops.recalc_face_normals(bm, faces=faces)

        if props.cleaning_use_snap:
            for v in bm.verts:
                v.co = nearest_point_valid_sources(context, v.co)

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        bm.to_mesh(mesh)
        bm.free()
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)

        return {'FINISHED'}


def draw_cleanup_options(layout, draw_button=True):
    props = bpy.context.window_manager.retopoflow
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = False

    row = col.row(heading='Merge')
    row.prop(props, 'cleaning_use_merge', text='By Distance')
    row = col.row()
    row.enabled = props.cleaning_use_merge
    row.prop(props, 'cleaning_merge_threshold', text='Threshold')
    col.separator()

    row = col.row(heading='Delete')
    row.prop(props, 'cleaning_use_delete_loose', text='Loose')
    row = col.row(heading='Fill')
    row.prop(props, 'cleaning_use_fill_holes', text='Holes')
    row = col.row(heading='Recalculate')
    row.prop(props, 'cleaning_use_recalculate_normals', text='Normals')
    row = col.row(heading='Snap')
    row.prop(props, 'cleaning_use_snap', text='To Source')
    if draw_button:
        col.separator()
        col.operator('retopoflow.meshcleanup', text='Clean Up Mesh')
