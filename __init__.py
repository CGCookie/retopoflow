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

bl_info = {
    "name":        "RetopoFlow",
    "description": "A suite of retopology tools for Blender through a unified retopology mode",
    "author":      "Jonathan Denning, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart",
    "version":     (3, 0, 0),  # 3.0.0
    "blender":     (2, 80, 0),
    "location":    "View 3D > Tool Shelf",
    # "warning":     "beta 2",  # used for warning icon and text in addons panel
    "wiki_url":    "http://docs.retopoflow.com",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View"
}

if "bpy" in locals():
    import importlib
    importlib.reload(VIEW3D_OT_RetopoFlow)
    importlib.reload(VIEW3D_OT_RetopoFlow_Tool)
else:
    from .retopoflow.retopoflow import (
        VIEW3D_OT_RetopoFlow,
        VIEW3D_OT_RetopoFlow_Tool
    )

import bpy
from bpy.types import Menu
from bpy.utils.toolsystem import ToolDef


@ToolDef.from_fn
def tool_RetopoFlow():
    return dict(
        idname="cgcookie.tool_retopoflow",
        label="RetopoFlow",
        description="Start RetopoFlow",
        operator="cgcookie.retopoflow",
        #icon=None,
        #widget=None,
        #keymap=None,
        #draw_settings=None,
    )


def get_tool_list(space_type, context_mode):
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    cls = ToolSelectPanelHelper._tool_class_from_space_type(space_type)
    return cls._tools[context_mode]


class VIEW3D_MT_RetopoFlow(Menu):
    bl_label = "RetopoFlow"
    def draw(self, context):
        layout = self.layout
        layout.operator('cgcookie.retopoflow')

def setupmenu():
    d = bpy.types.VIEW3D_MT_editor_menus.draw_collapsible
    def hijack(context, layout):
        obj = context.active_object
        mode_string = context.mode
        edit_object = context.edit_object
        gp_edit = obj and obj.mode in {'EDIT_GPENCIL', 'PAINT_GPENCIL', 'SCULPT_GPENCIL', 'WEIGHT_GPENCIL'}
        d(context, layout)
        if not gp_edit and edit_object and mode_string == 'EDIT_MESH':
            layout.menu("VIEW3D_MT_RetopoFlow", text="RetopoFlow")
    bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = hijack

# registration
classes = (
    VIEW3D_MT_RetopoFlow,
    VIEW3D_OT_RetopoFlow,
)

prev_tools = None
def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    setupmenu()

    if False:
        global prev_tools
        tools = get_tool_list('VIEW_3D', 'EDIT_MESH')
        for index,tool in enumerate(tools, 1):
            if isinstance(tool, ToolDef) and tool.label == 'Measure':
                break
        print('adding at ' + str(index))
        prev_tools = list(tools)
        tools[:] = [tool_RetopoFlow]
        tools[:] = prev_tools
        #tools[:index] += None, tool_RetopoFlow
        del tools

def unregister():
    if False:
        tools = get_tool_list('VIEW_3D', 'EDIT_MESH')
        index = tools.index(tool_RetopoFlow) - 1
        tools.pop(index)
        tools.remove(tool_RetopoFlow)
        del tools
        del index

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

#register,unregister = bpy.utils.register_classes_factory(classes)

if __name__ == "__main__":
    register()
    bpy.utils.register_tool(VIEW3D_OT_RetopoFlow_Tool, after={"builtin.scale_cage"}, separator=True, group=True) #, after={"builtin.scale_cage"}, separator=True, group=True)
