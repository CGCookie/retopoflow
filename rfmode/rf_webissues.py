'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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
from ..options import options

class OpenWebIssues(bpy.types.Operator):
    """Open Issues page in default web browser"""
    
    bl_idname = "wm.open_webissues"
    bl_label = "Issues Page"
    
    @classmethod
    def poll(cls, context): return True

    def execute(self, context):
        bpy.ops.wm.url_open(url=options['github issues url'])
        return {'FINISHED'}

