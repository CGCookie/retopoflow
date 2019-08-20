'''
Copyright (C) 2019 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import os

import bpy
import bmesh
from bpy.types import WorkSpaceTool
import random

from .retopoflow_ui import RetopoFlow_UI
from .retopoflow_tools import RetopoFlow_Tools

from ..addon_common.common.globals import Globals
from ..addon_common.common import drawing
from ..addon_common.common.drawing import ScissorStack
from ..addon_common.cookiecutter.cookiecutter import CookieCutter
from ..addon_common.common import ui
from ..addon_common.common.profiler import profiler
from ..addon_common.common.ui_styling import load_defaultstylings

class VIEW3D_OT_RetopoFlow(CookieCutter, RetopoFlow_Tools, RetopoFlow_UI):
    """Tooltip"""
    bl_idname = "cgcookie.retopoflow"
    bl_label = "RetopoFlow"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    default_keymap = {
        'commit': {'TAB',},
        'cancel': {'ESC',},
    }

    @classmethod
    def can_start(cls, context):
        # check that the context is correct
        if not context.region or context.region.type != 'WINDOW': return False
        if not context.space_data or context.space_data.type != 'VIEW_3D': return False
        # check we are in mesh editmode
        if context.mode != 'EDIT_MESH': return False
        # make sure we are editing a mesh object
        ob = context.active_object
        if not ob or ob.type != 'MESH': return False
        # all seems good!
        return True

    def start(self):
        self.target = bpy.context.active_object
        self.sources = [o for o in bpy.data.objects if o != self.target and o.type == "MESH" and o.visible_get()]
        print('sources: %s' % ', '.join(o.name for o in self.sources))
        print('target: %s' % self.target.name)

        self.setup_tools()
        self.setup_ui()

        self.ui_tools = self.document.body.getElementsByName('tool')

    def end(self):
        self.target.hide_viewport = False

    def update(self):
        self.selected_tool.update()

    @CookieCutter.FSM_State('main')
    def modal_main(self):
        # self.cursor_modal_set('CROSSHAIR')

        if self.actions.pressed('commit'):
            self.done()
            return

        if self.actions.pressed('cancel'):
            self.done(cancel=True)
            return




class VIEW3D_OT_RetopoFlow_Tool(WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'

    # The prefix of the idname should be your add-on name.
    bl_idname = "cgcookie.retopoflow"
    bl_label = "RetopoFlow"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode"
    bl_icon = "ops.mesh.polybuild_hover"
    bl_widget = None
    bl_keymap = (
        ("view3d.select_circle",
            {"type": 'LEFTMOUSE', "value": 'PRESS'},
            {"properties": [("wait_for_input", False)]}
        ),
        ("view3d.select_circle",
            {"type": 'LEFTMOUSE', "value": 'PRESS', "ctrl": True},
            {"properties": [("mode", 'SUB'), ("wait_for_input", False)]}
        ),
    )

    def draw_settings(context, layout, tool):
        props = tool.operator_properties("view3d.select_circle")
        layout.prop(props, "mode")
        layout.prop(props, "radius")


# class MyOtherTool(WorkSpaceTool):
#     bl_space_type='VIEW_3D'
#     bl_context_mode='OBJECT'

#     bl_idname = "my_template.my_other_select"
#     bl_label = "My Lasso Tool Select"
#     bl_description = (
#         "This is a tooltip\n"
#         "with multiple lines"
#     )
#     bl_icon = "ops.generic.select_lasso"
#     bl_widget = None
#     bl_keymap = (
#         ("view3d.select_lasso", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
#         ("view3d.select_lasso", {"type": 'LEFTMOUSE', "value": 'PRESS', "ctrl": True},
#          {"properties": [("mode", 'SUB')]}),
#     )

#     def draw_settings(context, layout, tool):
#         props = tool.operator_properties("view3d.select_lasso")
#         layout.prop(props, "mode")


# def register():
#     bpy.utils.register_tool(MyTool, after={"builtin.scale_cage"}, separator=True, group=True)
#     bpy.utils.register_tool(MyOtherTool, after={MyTool.bl_idname})

# def unregister():
#     bpy.utils.unregister_tool(MyTool)
#     bpy.utils.unregister_tool(MyOtherTool)

# if __name__ == "__main__":
#     register()


