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
from bpy.types import Menu


class RF_MT_ContextMenu(Menu):
    bl_idname = 'RF_MT_ContextMenu'
    bl_label = 'Retopoflow'

    def draw(self, context):
        layout = self.layout
        layout.operator("retopoflow.relax_selected", text="Relax Vertices")
        layout.operator_context = 'INVOKE_REGION_WIN'
        layout.operator("retopoflow.twist_loop", text="Twist Loops")
        # INVOKE (from the line above) is required here -- this operator's
        # invoke() seeds its `count` from the selected strip's actual current
        # count, which EXEC would skip, leaving `count` at a stale/default value
        layout.operator("retopoflow.adjust_segment_count", text="Adjust Segment Count")


def draw_context_menu_items(self, context):
    self.layout.menu(RF_MT_ContextMenu.bl_idname)
    self.layout.separator()


def register():
    bpy.utils.register_class(RF_MT_ContextMenu)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.prepend(draw_context_menu_items)


def unregister():
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(draw_context_menu_items)
    bpy.utils.unregister_class(RF_MT_ContextMenu)
