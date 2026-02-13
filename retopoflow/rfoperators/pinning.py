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


import bpy, bmesh
from ..common.operator import RFRegisterClass


crease_color = None


def setup_pinning(context):
    obj = context.active_object
    if obj == None: return

    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    crease_vert_layer = bm.verts.layers.float.get('crease_vert')
    if crease_vert_layer:
        for bmv in bm.verts:
            bmv[crease_vert_layer] = bmv[crease_vert_layer] / 100

    crease_edge_layer = bm.edges.layers.float.get('crease_edge')
    if crease_edge_layer:
        for bme in bm.edges:
            bme[crease_edge_layer] = bme[crease_edge_layer] / 100

    pin_vert_layer = bm.verts.layers.bool.get('retopoflow_pins')
    if pin_vert_layer:
        for bmv in bm.verts:
            # Only going up to 0.99 so the previous value is preserved
            if bmv[pin_vert_layer]:
                bmv[crease_vert_layer] += 0.99

    bmesh.update_edit_mesh(obj.data)


def restore_pinning(context):
    obj = context.active_object
    if obj == None: return

    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    crease_vert_layer = bm.verts.layers.float.get('crease_vert')
    if crease_vert_layer:
        pin_vert_layer = bm.verts.layers.bool.get('retopoflow_pins')
        for bmv in bm.verts:
            if pin_vert_layer:
                if bmv[pin_vert_layer]:
                    bmv[crease_vert_layer] -= 0.99
                # Avoids precision errors
                if bmv[crease_vert_layer] < 0.001:
                    bmv[crease_vert_layer] = 0
            bmv[crease_vert_layer] = max(min(bmv[crease_vert_layer] * 100, 1), 0)

    crease_edge_layer = bm.edges.layers.float.get('crease_edge')
    if crease_edge_layer:
        for bme in bm.edges:
            bme[crease_edge_layer] = max(min(bme[crease_edge_layer] * 100, 1), 0)

    bmesh.update_edit_mesh(obj.data)


def pin_bmvs(bm, selected_verts):
    pin_vert_layer = bm.verts.layers.bool.get('retopoflow_pins')
    if not pin_vert_layer:
        pin_vert_layer = bm.verts.layers.bool.new('retopoflow_pins')

    crease_vert_layer = bm.verts.layers.float.get('crease_vert')
    if not crease_vert_layer:
        crease_vert_layer = bm.verts.layers.float.new('crease_vert')

    for bmv in selected_verts:
        if bmv[pin_vert_layer] == False:
            bmv[pin_vert_layer] = True
            bmv[crease_vert_layer] += 0.99


def unpin_bmvs(bm, selected_verts):
    pin_vert_layer = bm.verts.layers.bool.get('retopoflow_pins')
    crease_vert_layer = bm.verts.layers.float.get('crease_vert')
    if not pin_vert_layer or not crease_vert_layer:
        return

    for bmv in selected_verts:
        if bmv[pin_vert_layer] == True:
            bmv[pin_vert_layer] = False
            bmv[crease_vert_layer] = bmv[crease_vert_layer] - 0.99
            # Avoids precision errors
            if bmv[crease_vert_layer] < 0.001:
                bmv[crease_vert_layer] = 0


class RFOperator_PinVerts(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.pinverts"
    bl_label = "Pin Verts"
    bl_description = "Add or remove pins for the selected verts"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'UNDO'}

    rf_label = "Pin Verts"
    RFCore = None

    unpin: bpy.props.BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        return context.active_object and context.mode == 'EDIT_MESH'

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        selected_verts = [x for x in bm.verts if x.select]
        if not selected_verts:
            print('Nothing was pinned because nothing was selected')
            return {'CANCELLED'}

        if self.unpin:
            unpin_bmvs(bm, selected_verts)
        else:
            pin_bmvs(bm, selected_verts)

        bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}