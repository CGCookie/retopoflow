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
from ..common.selection import get_selected, restore_selected
from ..rfpanels.mesh_cleanup_panel import draw_cleanup_options


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
        props = context.scene.retopoflow

        bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)

        obj = context.active_object
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)

        components = self.get_components(bm) # Needs to be updated before ops if a component gets removed

        # Remove unnecissary components first
        if props.cleaning_use_merge:
            bmesh.ops.remove_doubles(bm, verts=components['verts'], dist=props.cleaning_merge_threshold)

        if props.cleaning_use_delete_ngons:
            for f in components['faces']:
                if f.is_valid and len(f.edges) > 4:
                    bm.faces.remove(f)

        if props.cleaning_use_delete_faceless:
            for e in components['edges']:
                if e.is_valid and e.is_wire:
                    bm.edges.remove(e)

        if props.cleaning_use_delete_loose:
            # This comes last since it cleans up verts left over from the previous operations
            for v in components['verts']:
                if v.is_valid and not v.link_edges:
                    bm.verts.remove(v)
            
        components = self.get_components(bm)

        # Add any necissary geometry
        if props.cleaning_use_triangulate_concave:
            bmesh.ops.connect_verts_concave(bm, faces=components['faces'])

        if props.cleaning_use_triangulate_nonplanar:
            bmesh.ops.connect_verts_nonplanar(bm, angle_limit=0.1, faces=components['faces']) # Angle limit is radians

        if props.cleaning_use_triangulate_concave:
            bmesh.ops.connect_verts_concave(bm, faces=components['faces'])

        if props.cleaning_use_triangulate_ngons:
            to_triangulate = []
            for f in components['faces']:
                if len(f.edges) > 4:
                    to_triangulate.append(f)
            bmesh.ops.triangulate(bm, faces=to_triangulate)

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

        # Not ideal to do outside the main bmesh section, 
        # but select interior faces is a fairly complex algorithm
        if props.cleaning_use_delete_interior:
            prev_select_mode = context.tool_settings.mesh_select_mode
            prev_selection = get_selected(context)
            prev_faces = prev_selection[obj.name]['faces']
            prev_edges = prev_selection[obj.name]['edges']
            context.tool_settings.mesh_select_mode[2] = True # At least one needs to be true to mark the others false
            context.tool_settings.mesh_select_mode[0] = False
            context.tool_settings.mesh_select_mode[1] = False
            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.mesh.select_interior_faces()
            interior_faces = get_selected(context)
            selected_interior_faces = [f for f in interior_faces[obj.name]['faces'] if f in prev_faces]
            selected_interior_edges = [e for e in interior_faces[obj.name]['edges'] if e in prev_edges]
            bm = bmesh.new()
            bm.from_mesh(mesh)
            removed = {obj.name: {'verts': [], 'edges': [], 'faces': []}}
            for f in bm.faces:
                if f.index in selected_interior_faces:
                    removed[obj.name]['faces'].append(f.index)
                    bm.faces.remove(f)
            bm.edges.ensure_lookup_table()
            for e in bm.edges:
                if e.index in selected_interior_edges and e.is_wire:
                    removed[obj.name]['edges'].append(e.index)
                    bm.edges.remove(e)
            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
            bm.to_mesh(mesh)
            bm.free()
            restore_selected(context, prev_selection, skip=removed)
            bpy.ops.object.mode_set(mode='EDIT', toggle=False)
            context.tool_settings.mesh_select_mode = prev_select_mode

        return {'FINISHED'}