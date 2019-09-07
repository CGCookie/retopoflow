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

import importlib

if "bpy" in locals():
    # reloading RF modules
    importlib.reload(retopoflow)
else:
    from .retopoflow import retopoflow

import bpy
from bpy.types import Menu


bl_info = {
    "name":        "RetopoFlow",
    "description": "A suite of retopology tools for Blender through a unified retopology mode",
    "author":      "Jonathan Denning, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart",
    "version":     (3, 0, 0),
    "blender":     (2, 80, 0),
    "location":    "View 3D > Tool Shelf",
    "warning":     "pre-alpha (pre-α)",  # used for warning icon and text in addons panel
    "wiki_url":    "http://docs.retopoflow.com",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View"
}


class VIEW3D_OT_RetopoFlow(retopoflow.RetopoFlow):
    """RetopoFlow Blender Operator"""
    bl_idname = "cgcookie.retopoflow"
    bl_label = "RetopoFlow"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}


class VIEW3D_MT_RetopoFlow(Menu):
    """RetopoFlow Blender Menu"""
    bl_label = "RetopoFlow"

    def draw(self, context):
        layout = self.layout
        layout.operator('cgcookie.retopoflow')

    #############################################################################
    # the following two methods add/remove RF to/from the main 3D View menu
    # NOTE: this is a total hack: hijacked the draw function!
    @staticmethod
    def menu_add():
        VIEW3D_MT_RetopoFlow.menu_remove()
        VIEW3D_MT_RetopoFlow._menu_original = bpy.types.VIEW3D_MT_editor_menus.draw_collapsible
        def hijacked(context, layout):
            obj = context.active_object
            mode_string = context.mode
            edit_object = context.edit_object
            gp_edit = obj and obj.mode in {'EDIT_GPENCIL', 'PAINT_GPENCIL', 'SCULPT_GPENCIL', 'WEIGHT_GPENCIL'}
            VIEW3D_MT_RetopoFlow._menu_original(context, layout)
            if not gp_edit and edit_object and mode_string == 'EDIT_MESH':
                layout.menu("VIEW3D_MT_RetopoFlow", text="RetopoFlow")
        bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = hijacked
    @staticmethod
    def menu_remove():
        if not hasattr(VIEW3D_MT_RetopoFlow, '_menu_original'): return
        bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = VIEW3D_MT_RetopoFlow._menu_original
        del VIEW3D_MT_RetopoFlow._menu_original


# registration
classes = (
    VIEW3D_MT_RetopoFlow,
    VIEW3D_OT_RetopoFlow,
)

def register():
    for cls in classes: bpy.utils.register_class(cls)
    VIEW3D_MT_RetopoFlow.menu_add()

def unregister():
    VIEW3D_MT_RetopoFlow.menu_remove()
    for cls in reversed(classes): bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
