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
from mathutils import Vector, Matrix


def orientation_matrix(context, orient_type, custom_matrix=None):
    ''' 3x3 whose columns are the orientation's axes in world space. '''
    match orient_type:
        case 'CUSTOM':
            return custom_matrix
        case 'LOCAL' | 'NORMAL' | 'GIMBAL':
            # NORMAL/GIMBAL can't be determined here so NORMAL is the closest fallback
            return context.edit_object.matrix_world.to_3x3().normalized()
        case 'VIEW':
            if not context.region_data:
                #Falls back to world if the event came from a region with no 3D view
                return Matrix.Identity(3)
            return context.region_data.view_matrix.to_3x3().transposed()
        case 'CURSOR':
            return context.scene.cursor.matrix.to_3x3()
        case _:  # GLOBAL, PARENT, anything unknown
            return Matrix.Identity(3)


def reset_axis_constraint(op_cls):
    op_cls.constraint_axis = None
    op_cls.constraint_stage = 0
    op_cls.constraint_plane = False
    op_cls.constraint_dir_world = None
    op_cls.constraint_plane_axes = ()
    op_cls.constraint_label = ''


def cycle_axis_constraint(op_cls, context, axis_key, *, plane=False):
    ''' Blender-style constraint cycle: scene orientation, then
    world (or local if already world), then off. A different axis or switching
    between axis and plane mode restarts the cycle. '''
    # state lives on the drag class, not an instance, so it can outlive a single drag
    axis_idx = 'XYZ'.index(axis_key)
    same_mode = (op_cls.constraint_axis == axis_idx and op_cls.constraint_plane == plane)
    if same_mode and op_cls.constraint_stage >= 1:
        reset_axis_constraint(op_cls)
        return
    stage = (op_cls.constraint_stage + 1) if same_mode else 0
    slot = context.scene.transform_orientation_slots[0]
    custom = slot.custom_orientation
    scene_type = 'CUSTOM' if custom is not None else slot.type
    orient_type = scene_type if stage == 0 else ('GLOBAL' if scene_type != 'GLOBAL' else 'LOCAL')
    m = orientation_matrix(context, orient_type, custom.matrix.copy() if custom is not None else None,)
    axis_dir = Vector(m.col[axis_idx])
    if axis_dir.length < 1e-9:
        # degenerate custom orientation, treat the press as toggling off
        reset_axis_constraint(op_cls)
        return
    op_cls.constraint_axis = axis_idx
    op_cls.constraint_stage = stage
    op_cls.constraint_plane = plane
    op_cls.constraint_dir_world = axis_dir.normalized()
    # the constraint plane's own two axes, kept for the guide-line draw
    op_cls.constraint_plane_axes = tuple(
        (i, Vector(m.col[i]).normalized())
        for i in range(3)
        if i != axis_idx and Vector(m.col[i]).length > 1e-9
    ) if plane else ()
    if plane:
        letters = ''.join(k for k in 'XYZ' if k != axis_key)
        op_cls.constraint_label = f'{orient_type.title()} {letters} plane'
    else:
        op_cls.constraint_label = f'{orient_type.title()} {axis_key}'
