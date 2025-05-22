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

from ..rfoperators.mirror import set_mirror_mod


class RFProps_Object(bpy.types.PropertyGroup):
    """
    These are properties that need to be unique per object
    """

    """ Mirror """
    #region
    mirror_x: bpy.props.BoolProperty(
        name='Mirror X',
        description='Enables mirroring the edited meshes across the X axis',
        default=False, 
        update=lambda self, context: set_mirror_mod(context)
    )
    mirror_y: bpy.props.BoolProperty(
        name='Mirror Y',
        description='Enables mirroring the edited meshes across the Y axis',
        default=False, 
        update=lambda self, context: set_mirror_mod(context)
    )
    mirror_z: bpy.props.BoolProperty(
        name='Mirror Z',
        description='Enables mirroring the edited meshes across the Z axis',
        default=False, 
        update=lambda self, context: set_mirror_mod(context)
    )
    mirror_clipping: bpy.props.BoolProperty(
        name='Clipping',
        description='Keeps vertices stuck to the mirror axis during transforms',
        default=True, 
        update=lambda self, context: set_mirror_mod(context)
    )
    mirror_prev_edit: bpy.props.BoolProperty(default=True)

def register():
    bpy.utils.register_class(RFProps_Object)
    bpy.types.Object.retopoflow = bpy.props.PointerProperty(type=RFProps_Object)

def unregister():
    bpy.utils.unregister_class(RFProps_Object)
