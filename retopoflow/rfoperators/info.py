'''Copyright (C) 2024 CG Cookie
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


class RFOperator_ShowInfo(RFRegisterClass, bpy.types.Operator):
    ''' Generic explainer popup. Draw its button with draw_info_notice, never by idname. '''
    bl_idname = 'retopoflow.show_info'
    bl_label = 'Click to Read More'
    bl_description = 'Explain this setting'
    bl_options = {'INTERNAL'}

    title:   bpy.props.StringProperty(default='')
    message: bpy.props.StringProperty(default='')
    width:   bpy.props.IntProperty(default=500)

    @classmethod
    def description(cls, context, properties):
        # Name the subject in the tooltip, so a panel with several of these stays readable on hover
        return properties.title or cls.bl_description

    def invoke(self, context, event):
        # invoke_popup shows draw() and nothing else: no OK button, no execute, dismissed by clicking away
        return context.window_manager.invoke_popup(self, width=self.width)

    def draw(self, context):
        layout = self.layout
        header = layout.row()
        header.label(text=self.title, icon='INFO')
        layout.separator()
        col = layout.column(align=True)
        for line in self.message.split('\n'):
            if line.strip():
                col.label(text=line)
            else:
                col.separator()

    def execute(self, context):
        return {'FINISHED'}
