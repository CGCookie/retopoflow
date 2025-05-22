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


def get_mirror_mod(obj):
    # Just uses last mirror in stack
    modifiers = list(reversed([x for x in obj.modifiers if x.type == 'MIRROR']))
    return modifiers[0] if modifiers else None


def setup_solid_preview(context):
    from ..rfcore import RFCore
    RFCore.pause()
    bpy.ops.object.mode_set(mode='OBJECT')

    props = context.scene.retopoflow
    mirror_obj = context.active_object
    mirror_mod = get_mirror_mod(mirror_obj)
    props_obj = mirror_obj.retopoflow
    preview_name = mirror_obj.name + '_mirror_preview'
    node_name = 'Retopoflow Mirror Display'
    node_group = append_node('.' + node_name)

    if preview_name in [x.name for x in bpy.data.objects]:
        preview_obj = bpy.data.objects[preview_name]
    else:
        mesh = bpy.data.meshes.new(preview_name)
        preview_obj = bpy.data.objects.new(preview_name, mesh)

    clear_transforms(preview_obj)
    preview_obj.parent = mirror_obj
    preview_obj.show_wire = props.mirror_wires
    preview_obj.show_all_edges = props.mirror_wires
    preview_obj.display_type = 'WIRE' if props.mirror_display == 'WIRE' else 'SOLID'

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

    mod['Socket_7'] = props.mirror_colors
    mod['Socket_5'] = context.space_data.overlay.retopology_offset
    mod['Socket_6'] = props.mirror_displace
    mod['Socket_9'] = props.mirror_displace_boundaries

    if preview_obj.name not in context.collection.objects:
        context.collection.objects.link(preview_obj)

    bpy.ops.object.mode_set(mode='EDIT')
    RFCore.resume()


def cleanup_solid_preview(context):
    mirror_obj = context.active_object
    preview_name = mirror_obj.name + '_mirror_preview'

    if preview_name in [x.name for x in bpy.data.objects]:
        preview_obj = bpy.data.objects[preview_name]
    else:
        return
    
    bpy.data.meshes.remove(preview_obj.data)


def setup_mirror(context):  
    props = context.scene.retopoflow
    obj = context.active_object
    props_obj = obj.retopoflow
    
    mod = get_mirror_mod(obj)
    if mod:
        props_obj.mirror_axis = mod.use_axes
        props_obj.mirror_clipping = mod.use_clip
    else:
        props_obj.mirror_axis = (False, False, False)

    if props_obj.mirror_axis[0] or props_obj.mirror_axis[1] or props_obj.mirror_axis[2]:
        if props.mirror_display == 'SOLID' or props.mirror_display=='WIRE':
            mod.show_in_editmode = False
            mod.show_on_cage = False
            setup_solid_preview(context)
        elif props.mirror_display == 'APPLIED':
            mod.show_in_editmode = True
            mod.show_on_cage = True
            cleanup_solid_preview(context)
        else:
            mod.show_on_cage = False
            cleanup_solid_preview(context)
    else:
        cleanup_solid_preview(context)


def set_mirror_mod(context):
    props = context.scene.retopoflow
    obj = context.active_object
    props_obj = obj.retopoflow
    mod = get_mirror_mod(obj)
    use_mirror = props_obj.mirror_axis[0] or props_obj.mirror_axis[1] or props_obj.mirror_axis[2]

    if not mod and use_mirror:
        mod = obj.modifiers.new('Mirror', 'MIRROR')

    if mod:
        mod.use_axis = props_obj.mirror_axis
        mod.use_clip = props_obj.mirror_clipping

    if use_mirror:
        if props.mirror_display == 'SOLID' or props.mirror_display=='WIRE':
            mod.show_in_editmode = False
            mod.show_on_cage = False
            setup_solid_preview(context)


def cleanup_mirror(context):
    obj = context.active_object
    props_obj = obj.retopoflow
    mod = get_mirror_mod(obj)

    cleanup_solid_preview(context)

    if mod:
        mod.show_in_editmode = props_obj.mirror_prev_edit


class RFOperator_ApplyMirror(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.applymirror"
    bl_label = "Apply Mirror"
    bl_description = "Apply the mirror modifier while in Edit Mode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'UNDO'}

    rf_label = "Apply Mirror"
    RFCore = None

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