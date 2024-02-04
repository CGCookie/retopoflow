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
from mathutils import Vector, Matrix, Quaternion

import math

def view_forward_direction(context):
    r3d = context.region_data
    mat = r3d.view_matrix
    return (mat.inverted() @ Vector((0,0,-1,0))).xyz
def view_right_direction(context):
    r3d = context.region_data
    mat = r3d.view_matrix
    return (mat.inverted() @ Vector((1,0,0,0))).xyz
def view_up_direction(context):
    r3d = context.region_data
    mat = r3d.view_matrix
    return (mat.inverted() @ Vector((0,1,0,0))).xyz
