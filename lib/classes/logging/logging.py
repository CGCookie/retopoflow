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
from ...common_utilities import showErrorMessage
from ....options import options

class OpenLog(bpy.types.Operator):
    """Open log text files in new window"""
    bl_idname = "wm.open_log"
    bl_label = "Open Log in Text Editor"
    
    @classmethod
    def poll(cls, context):
        return options['log_filename'] in bpy.data.texts

    def execute(self, context):
        self.openTextFile(options['log_filename'])
        return {'FINISHED'}

    def openTextFile(self, filename):

        # play it safe!
        if filename not in bpy.data.texts:
            showErrorMessage('Log file not found')
            return

        # duplicate the current area then change it to a text edito
        area_dupli = bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
        win = bpy.context.window_manager.windows[-1]
        area = win.screen.areas[-1]
        area.type = 'TEXT_EDITOR'

        # load the text file into the correct space
        for space in area.spaces:
            if space.type == 'TEXT_EDITOR':
                space.text = bpy.data.texts[filename]

