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

from pprint import pprint

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

    push_and_snap: bpy.props.BoolProperty(
        name='Push and Snap',
        default=True
    )
    push_distance: bpy.props.FloatProperty(
        name='Push Distance',
        default=0.001,
        min=0
    )
    merge_by_distance: bpy.props.BoolProperty(
        name='Merge by Distance',
        default=True
    )
    merge_threshold: bpy.props.FloatProperty(
        name='Merge Threshold',
        default=0.0001,
        min=0
    )
    delete_loose: bpy.props.BoolProperty(
        name='Delete Loose Verts',
        default=True
    )
    fill_holes: bpy.props.BoolProperty(
        name='Fill Holes',
        default=True
    )
    recalculate_normals: bpy.props.BoolProperty(
        name='Recalculate Normals',
        default=True
    )

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.use_property_split = True
        col.prop(self, 'merge_by_distance')
        row = col.row()
        row.enabled = self.merge_by_distance
        row.prop(self, 'merge_threshold', text='Threshold')
        col.separator()
        col.prop(self, 'push_and_snap', text='Snap to Surface')
        col.prop(self, 'delete_loose')
        col.prop(self, 'fill_holes')
        col.prop(self, 'recalculate_normals')

    def execute(self, context):
        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)

        mesh = context.active_object.data
        bm = bmesh.new()
        bm.from_mesh(mesh)

        verts = [ v for v in bm.verts if v.select and not v.hide ]
        edges = [ e for e in bm.edges if e.select and not e.hide ]
        faces = [ f for f in bm.faces if f.select and not f.hide ]

        if self.merge_by_distance:
            bmesh.ops.remove_doubles(bm, verts=verts, dist=self.merge_threshold)

        if self.delete_loose:
            for v in bm.verts:
                if not v.link_edges:
                    bm.verts.remove(v)

        if self.fill_holes:
            bmesh.ops.holes_fill(bm, edges=edges, sides=4)

        if self.recalculate_normals:
            bmesh.ops.recalc_face_normals(bm, faces=faces)

        if self.push_and_snap:
            for v in bm.verts:
                v.co = nearest_point_valid_sources(context, v.co)

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        bm.to_mesh(mesh)
        bm.free()
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)

        return {'FINISHED'}


def draw_cleanup_options(layout):
    layout.operator('retopoflow.meshcleanup', text='Clean Up Mesh')

def draw_cleanup_panel(layout):
    header, panel = layout.panel(idname='retopoflow_cleanup_panel', default_closed=True)
    header.label(text="Clean Up")
    if panel:
        draw_cleanup_options(panel)


class RFMenu_PT_MeshCleanup(bpy.types.Panel):
    bl_label = "Mesh Clean Up"
    bl_idname = "RF_PT_MeshCleanup"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        draw_cleanup_options(self.layout)