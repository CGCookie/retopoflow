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
from .common import operator


'''
TODO:

- custom WorkSpaceTool icons! https://github.com/blender/blender/blob/main/release/datafiles/blender_icons_geom.py

'''

class RFTool_Base(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'EDIT_MESH'

    @classmethod
    def register(cls): pass
    @classmethod
    def unregister(cls): pass

    @classmethod
    def activate(cls, context): pass
    @classmethod
    def deactivate(cls, context): pass


def get_all_RFTools():
    return RFTool_Base.__subclasses__()


def register():
    operator.register()

def unregister():
    operator.unregister()

