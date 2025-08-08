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

from ..common.operator import RFRegisterClass
from ..common.append import append_node
from ..common.object import clear_transforms


mirror_node_tree_name = 'Retopoflow Mirror Display'


def get_mirror_mod(obj):
    # Just uses last mirror in stack
    modifiers = list(reversed([x for x in obj.modifiers if x.type == 'MIRROR']))
    return modifiers[0] if modifiers else None


def update_nodes_preview(context, preview_mod=None):
    props = context.scene.retopoflow
    mirror_obj = context.active_object
    preview_name = mirror_obj.name + '_mirror_preview'

    if preview_name not in [x.name for x in bpy.data.objects]:
        return

    preview_obj = bpy.data.objects[preview_name]
    node_name = mirror_node_tree_name
    mod = preview_obj.modifiers[node_name] if preview_mod == None else preview_mod

    preview_obj.show_wire = props.mirror_wires and props.mirror_display == 'SOLID'
    preview_obj.show_all_edges = True
    if bpy.app.version < (4, 3, 0) and props.mirror_display == 'WIRE':
        preview_obj.display_type = 'WIRE'
    else:
        preview_obj.display_type = 'SOLID'

    mod['Socket_5'] = context.space_data.overlay.retopology_offset
    mod['Socket_6'] = props.mirror_displace
    mod['Socket_9'] = props.mirror_displace_boundaries
    mod['Socket_12'] = props.mirror_displace_connected
    mod['Socket_11'] = props.mirror_display == 'WIRE'
    mod['Socket_10'] = props.mirror_wire_thickness

    # Hack to get it to update while in other object's edit mode
    mod.show_in_editmode = True

    for i in ['X', 'Y', 'Z']:
        material = bpy.data.materials[f'.Retopoflow Mirror {i}']
        material.diffuse_color[3] = props.mirror_opacity
        material.node_tree.nodes['Principled BSDF'].inputs['Alpha'].default_value = props.mirror_opacity
        bpy.data.materials[f'.Retopoflow Wire {i}'].grease_pencil.color[3] = props.mirror_opacity


def setup_nodes_preview(context):
    props = context.scene.retopoflow
    mirror_obj = context.active_object
    mirror_mod = get_mirror_mod(mirror_obj)
    props_obj = mirror_obj.retopoflow
    node_name = mirror_node_tree_name

    if '.' + node_name not in [x.name for x in bpy.data.node_groups]:
        from ..rfcore import RFCore
        RFCore.pause()
        bpy.ops.object.mode_set(mode='OBJECT')
        node_group = append_node('.' + node_name)
        bpy.ops.object.mode_set(mode='EDIT')
        RFCore.resume()
    else:
        node_group = bpy.data.node_groups['.' + node_name]

    preview_name = mirror_obj.name + '_mirror_preview'
    if preview_name in [x.name for x in bpy.data.objects]:
        preview_obj = bpy.data.objects[preview_name]
    else:
        mesh = bpy.data.meshes.new(preview_name)
        preview_obj = bpy.data.objects.new(preview_name, mesh)
    if preview_obj.name not in context.collection.objects:
        context.collection.objects.link(preview_obj)
    clear_transforms(preview_obj)
    preview_obj.parent = mirror_obj

    if props.mirror_display == 'WIRE':
        # Workaround for grease pencil not showing up in
        # geo nodes if a GP obj isn't in the scene
        gp_name = mirror_obj.name + '_mirror_preview_gp'
        if gp_name in [x.name for x in bpy.data.objects]:
            gp_obj = bpy.data.objects[gp_name]
        else:
            gp = bpy.data.grease_pencils_v3.new(gp_name)
            gp_obj = bpy.data.objects.new(gp_name, gp)
        if gp_obj.name not in context.collection.objects:
            context.collection.objects.link(gp_obj)
        gp_obj.parent = mirror_obj

    if node_name in [x.name for x in preview_obj.modifiers]:
        mod = preview_obj.modifiers[node_name]
        props_obj.mirror_prev_edit = mod.show_in_editmode
    else:
        mod = preview_obj.modifiers.new(node_name, 'NODES')
    mod.node_group = node_group
    mod['Socket_8'] = mirror_obj

    # Drivers make it possible for the user to use the mirror modifier as usual
    # It sucks to check if drivers exist, so clearing it out and creating fresh is easier
    # Would be good to clean this up at some point though
    drv_x = mod.driver_remove('["Socket_2"]')
    drv_x = mod.driver_add('["Socket_2"]')
    drv_x.driver.type = 'AVERAGE'
    var_x = drv_x.driver.variables.new()
    var_x.targets[0].id = mirror_obj
    var_x.targets[0].data_path = mirror_mod.path_from_id() + ".use_axis[0]"

    drv_y = mod.driver_remove('["Socket_3"]')
    drv_y = mod.driver_add('["Socket_3"]')
    drv_y.driver.type = 'AVERAGE'
    var_y = drv_y.driver.variables.new()
    var_y.targets[0].id = mirror_obj
    var_y.targets[0].data_path = mirror_mod.path_from_id() + ".use_axis[1]"

    drv_z = mod.driver_remove('["Socket_4"]')
    drv_z = mod.driver_add('["Socket_4"]')
    drv_z.driver.type = 'AVERAGE'
    var_z = drv_z.driver.variables.new()
    var_z.targets[0].id = mirror_obj
    var_z.targets[0].data_path = mirror_mod.path_from_id() + ".use_axis[2]"

    update_nodes_preview(context, mod)


def cleanup_nodes_preview(context):
    mirror_obj = context.active_object
    preview_name = mirror_obj.name + '_mirror_preview'
    gp_name = mirror_obj.name + '_mirror_preview_gp'

    if preview_name in [x.name for x in bpy.data.objects]:
        preview_obj = bpy.data.objects[preview_name]
        bpy.data.meshes.remove(preview_obj.data)

    if gp_name in [x.name for x in bpy.data.objects]:
        gp_obj = bpy.data.objects[gp_name]
        bpy.data.grease_pencils_v3.remove(gp_obj.data)


def update_mirror_mod(context, modifier=None):
    props = context.scene.retopoflow
    obj = context.active_object
    props_obj = obj.retopoflow
    use_mirror = props_obj.mirror_axis[0] or props_obj.mirror_axis[1] or props_obj.mirror_axis[2]
    mod = get_mirror_mod(obj) if modifier == None else modifier

    if not mod and use_mirror:
        mod = obj.modifiers.new('Mirror', 'MIRROR')

    if mod:
        mod.use_axis = props_obj.mirror_axis
        mod.use_clip = props_obj.mirror_clipping

    if mod and use_mirror:
        if props.mirror_display == 'SOLID' or props.mirror_display=='WIRE':
            mod.show_in_editmode = False
            mod.show_on_cage = False
            setup_nodes_preview(context)
        elif props.mirror_display == 'APPLIED':
            mod.show_in_editmode = True
            mod.show_on_cage = True
            cleanup_nodes_preview(context)
        else:
            mod.show_on_cage = False
            cleanup_nodes_preview(context)
    else:
        cleanup_nodes_preview(context)


def setup_mirror(context):
    obj = context.active_object
    props_obj = obj.retopoflow

    mod = get_mirror_mod(obj)
    if mod:
        props_obj.mirror_axis = mod.use_axis
        props_obj.mirror_clipping = mod.use_clip
    else:
        props_obj.mirror_axis = (False, False, False)


def cleanup_mirror(context):
    obj = context.active_object
    props_obj = obj.retopoflow
    mod = get_mirror_mod(obj)

    cleanup_nodes_preview(context)

    if mod:
        mod.show_in_editmode = props_obj.mirror_prev_edit
        if not (mod.use_axis[0] or mod.use_axis[1] or mod.use_axis[2]):
            obj.modifiers.remove(mod)

class RFOperator_AddMirror(RFRegisterClass, bpy.types.Operator):
    bl_idname = 'retopoflow.addmirror'
    bl_label = 'Add Mirror Modifier'
    bl_description = "Add a mirror modifier"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'UNDO'}

    rf_label = "Add Mirror"
    RFCore = None

    @classmethod
    def poll(cls, context):
        if not context.active_object: return False
        return get_mirror_mod(context.active_object) is None

    def execute(self, context):
        obj = context.active_object
        obj.modifiers.new('Mirror', 'MIRROR')
        return {'FINISHED'}

class RFOperator_ApplyMirror(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.applymirror"
    bl_label = "Apply Mirror"
    bl_description = "Apply the mirror modifier while in Edit Mode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'UNDO'}

    rf_label = "Apply Mirror"
    RFCore = None

    @classmethod
    def poll(cls, context):
        if not context.active_object: return False
        return get_mirror_mod(context.active_object) is not None

    def execute(self, context):
        from ..rfcore import RFCore
        RFCore.pause()
        bpy.ops.object.mode_set(mode='OBJECT')

        obj = context.active_object
        props_obj = obj.retopoflow
        mod = get_mirror_mod(obj)
        bpy.ops.object.modifier_apply(modifier=mod.name)
        props_obj.mirror_axis = (False, False, False)

        bpy.ops.object.mode_set(mode='EDIT')
        RFCore.resume()

        return {'FINISHED'}