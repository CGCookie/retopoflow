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
from bpy.types import Context, MirrorModifier
from mathutils import Vector
from collections.abc import Iterator


def clear_transforms(obj):
    obj.location = [0, 0, 0]
    obj.rotation_axis_angle = [0, 0, 0, 0]
    obj.rotation_euler = [0, 0, 0]
    obj.rotation_quaternion = [0, 0, 0, 0]
    obj.scale = [1, 1, 1]


def iter_mirror_modifiers(obj : bpy.types.Object|None) -> Iterator[MirrorModifier]:
    if not obj: return
    for mod in obj.modifiers:
        if mod.type != 'MIRROR': continue
        # if not isinstance(mod, MirrorModifier): continue
        if not mod.show_render and not mod.show_viewport: continue
        yield mod             # pyright: ignore [reportReturnType]

def mirror_threshold(context: Context) -> float|None:
    return next((mod.merge_threshold for mod in iter_mirror_modifiers(context.edit_object)), None)

def mirror_settings(context: Context) -> tuple[set[str], Vector, bool]:
    ''' The clipping Mirror modifier's (axes, local-space threshold, clip) for the edit object. '''
    axes, threshold, clip = set(), Vector((0, 0, 0)), False
    for mod in context.edit_object.modifiers:
        if mod.type != 'MIRROR': continue
        if not mod.use_clip: continue
        if mod.use_axis[0]: axes.add('x')
        if mod.use_axis[1]: axes.add('y')
        if mod.use_axis[2]: axes.add('z')
        mt, s = mod.merge_threshold, context.edit_object.scale
        threshold = Vector((
            mt / s.x if s.x else 0.0,
            mt / s.y if s.y else 0.0,
            mt / s.z if s.z else 0.0,
        ))
        clip = mod.use_clip
    return axes, threshold, clip

def has_mirror_x(context:Context) -> bool:
    return any(mod.use_axis[0] for mod in iter_mirror_modifiers(context.edit_object))   # pyright: ignore [reportIndexIssue]
def has_mirror_y(context:Context) -> bool:
    return any(mod.use_axis[1] for mod in iter_mirror_modifiers(context.edit_object))   # pyright: ignore [reportIndexIssue]
def has_mirror_z(context:Context) -> bool:
    return any(mod.use_axis[2] for mod in iter_mirror_modifiers(context.edit_object))   # pyright: ignore [reportIndexIssue]
