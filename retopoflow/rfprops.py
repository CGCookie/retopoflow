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

class RFProps(bpy.types.PropertyGroup):
    """ Clean Up Operator Properties """
    cleaning_use_snap: bpy.props.BoolProperty(
        name='Snap to Surface',
        default=True
    )
    cleaning_use_merge: bpy.props.BoolProperty(
        name='Merge by Distance',
        default=True
    )
    cleaning_merge_threshold: bpy.props.FloatProperty(
        name='Merge Threshold',
        precision=4,
        default=0.0001,
        step=0.1,
        min=0
    )
    cleaning_use_delete_loose: bpy.props.BoolProperty(
        name='Delete Loose Verts',
        default=True
    )
    cleaning_use_fill_holes: bpy.props.BoolProperty(
        name='Fill Holes',
        default=True
    )
    cleaning_use_recalculate_normals: bpy.props.BoolProperty(
        name='Recalculate Normals',
        default=True
    )


def register():
    bpy.utils.register_class(RFProps)
    bpy.types.Scene.retopoflow = bpy.props.PointerProperty(type=RFProps)

def unregister():
    bpy.utils.unregister_class(RFProps)