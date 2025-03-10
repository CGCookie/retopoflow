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
from ..rfpanels.mesh_cleanup_panel import draw_cleanup_options
from ..preferences import RF_Prefs


class RFOperator_MeshCleanup(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.meshcleanup"
    bl_label = "Clean Up Mesh"
    bl_description = "A handy macro for quicly running several retopology cleanup operations at once"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    rf_label = "Clean Up Mesh"
    RFCore = None

    affect_all: bpy.props.BoolProperty(
        default=False
    )

    def draw(self, context):
        draw_cleanup_options(context, self.layout, draw_operators=False)

    def get_components(self, bm):
        if self.affect_all:
            return {
                'verts': [ v for v in bm.verts if not v.hide ],
                'edges': [ e for e in bm.edges if not e.hide ],
                'faces': [ f for f in bm.faces if not f.hide ],
            }
        else:
            return {
                'verts': [ v for v in bm.verts if v.select and not v.hide ],
                'edges': [ e for e in bm.edges if e.select and not e.hide ],
                'faces': [ f for f in bm.faces if f.select and not f.hide ],
            }

    def execute(self, context):
        props = RF_Prefs.get_prefs(context)

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)

        obj = context.active_object
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)

        # This needs to be updated whenever a component gets removed
        components = self.get_components(bm)

        # Remove unnecissary verts first
        if props.cleaning_use_merge:
            bmesh.ops.remove_doubles(bm, verts=components['verts'], dist=props.cleaning_merge_threshold)
            components = self.get_components(bm)

        if props.cleaning_use_delete_loose:
            for v in components['verts']:
                if not v.link_edges:
                    bm.verts.remove(v)
            components = self.get_components(bm)

        # Clean up remaining components 
        if props.cleaning_use_fill_holes:
            bmesh.ops.holes_fill(bm, edges=components['edges'], sides=4)

        if props.cleaning_use_recalculate_normals:
            bmesh.ops.recalc_face_normals(bm, faces=components['faces'])

        if props.cleaning_flip_normals:
            for face in components['faces']:
                face.normal_flip()

        if props.cleaning_use_snap:
            for v in components['verts']:
                world_co = obj.matrix_world @ v.co
                v.co = nearest_point_valid_sources(context, world_co, world=False)

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        bm.to_mesh(mesh)
        bm.free()
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)

        return {'FINISHED'}