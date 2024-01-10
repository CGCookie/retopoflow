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
import bmesh

from mathutils import Vector
from bpy_extras.view3d_utils import region_2d_to_origin_3d
from bpy_extras.view3d_utils import region_2d_to_vector_3d

from ..rftool_base import RFTool_Base, invoke_operator, execute_operator


def distance_between_locations(a, b):
    a = a.xyz / a.w
    b = b.xyz / b.w
    return (a - b).length

def raycast_mouse_objects(context, event):
    mouse = (event.mouse_region_x, event.mouse_region_y)
    ray_world = (
        Vector((*region_2d_to_origin_3d(context.region, context.region_data, mouse), 1.0)),
        Vector((*region_2d_to_vector_3d(context.region, context.region_data, mouse), 0.0)),
    )
    best_hit = None
    best_dist = float('inf')
    print(f'RAY {ray_world}')
    for obj in context.scene.objects:
        if obj.type != 'MESH': continue
        if obj.mode != 'OBJECT': continue
        if obj.hide_get(): continue
        if obj.hide_select: continue
        if obj.hide_viewport: continue
        M = obj.matrix_world
        Mi = M.inverted()
        ray_local = (
            Mi @ ray_world[0],
            (Mi @ ray_world[1]).normalized(),
        )
        result, loc, normal, idx = obj.ray_cast(ray_local[0].xyz / ray_local[0].w, ray_local[1].xyz)
        if not result: continue
        loc_world = M @ Vector((*loc, 1.0))
        dist = distance_between_locations(ray_world[0], loc_world)
        print(f'  HIT {obj.name} {loc_world} {dist}')
        if dist >= best_dist: continue
        best_hit = loc_world
        best_dist = dist

    if not best_hit: return None

    hit = Vector((*(best_hit.xyz / best_hit.w), 1.0))
    M = context.active_object.matrix_world
    Mi = M.inverted()
    hit = Mi @ hit
    return hit.xyz

@invoke_operator('PolyPen_Insert', 'polypen_insert', 'PolyPon: Insert')
def pp_insert(context, event):
    print('INSERT!')

    hit = raycast_mouse_objects(context, event)
    if not hit: return {'CANCELLED'}

    bme = bmesh.from_edit_mesh(context.active_object.data)
    for bmv in bme.select_history: bmv.select_set(False)
    bmv = bme.verts.new(hit)
    bme.select_history.add(bmv)
    bmv.select_set(True)
    bme.select_flush(True)
    bme.select_flush(False)
    bmesh.update_edit_mesh(context.active_object.data)

    bpy.ops.transform.transform(
        'INVOKE_DEFAULT',
        mode='TRANSLATION',
        snap=True,
        use_snap_project=True,
        use_snap_self=False,
        use_snap_edit=False,
        use_snap_nonedit=True,
        use_snap_selectable=True,
        snap_elements={'FACE_PROJECT', 'FACE_NEAREST'},
        snap_target='CLOSEST',
        # release_confirm=True,
    )

@execute_operator('PolyPen_InsertStart', 'polypen_insert_start', 'PolyPon: Insert Start')
def pp_insert_start(context):
    print('START INSERT VIZ!')
    # context.scene.tool_settings.use_snap = True
    # context.scene.tool_settings.snap_target = 'CLOSEST'
    # # context.scene.tool_settings.snap_elements_base = {'FACE'}
    # context.scene.tool_settings.snap_elements_individual = {'FACE_PROJECT', 'FACE_NEAREST'}
    # context.scene.tool_settings.use_snap_self = False
    # context.scene.tool_settings.use_snap_edit = False
    # context.scene.tool_settings.use_snap_nonedit = True
    # context.scene.tool_settings.use_snap_selectable = True

@execute_operator('PolyPen_InsertEnd', 'polypen_insert_end', 'PolyPon: Insert End')
def pp_insert_end(context):
    print('END INSERT VIZ!')




class RFTool_PolyPen(RFTool_Base):
    bl_idname = "retopoflow.polypen"
    bl_label = "PolyPen"
    bl_description = "PolyPen"
    bl_icon = "ops.generic.select_circle"
    bl_widget = None

    bl_keymap = (
        (pp_insert.bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS', 'alt': True}, None),
        (pp_insert_start.bl_idname, {'type': 'LEFT_ALT', 'value': 'PRESS'}, None),
        (pp_insert_end.bl_idname, {'type': 'LEFT_ALT', 'value': 'RELEASE'}, None),
        ('transform.translate', {'type': 'LEFTMOUSE', 'value': 'CLICK_DRAG'}, {'properties':[
            ('snap', True),
            ('use_snap_project', True),
            ('use_snap_self', False),
            ('use_snap_edit', False),
            ('use_snap_nonedit', True),
            ('use_snap_selectable', True),
            ('snap_elements', {'FACE_PROJECT', 'FACE_NEAREST'}),
            ('snap_target', 'CLOSEST')
        ]}),
    )


