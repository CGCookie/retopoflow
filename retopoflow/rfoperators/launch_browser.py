'''
Copyright (C) 2025 CG Cookie
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
from bpy.types import Context, Operator
from ..rfglobals import RFGlobals
from ..common.operator import RFRegisterClass


class RFOperator_Launch_Help(RFRegisterClass, bpy.types.Operator):
    bl_idname      : str = "retopoflow.launch_help"
    bl_label       : str = 'Launch Retopoflow Docs'
    bl_space_type  : str = "VIEW_3D"
    bl_region_type : str = "TOOLS"
    bl_options : set[str] = set()

    @classmethod
    def poll(cls, context : Context) -> bool:
        RFCore = RFGlobals.RFCore_None
        return RFCore is not None and RFCore.is_running

    def execute(self, context : Context) -> set[str]:
        RFCore = RFGlobals.RFCore_None
        if not RFCore:
            return {'CANCELLED'}

        active_tool = RFCore.selected_RFTool_idname
        if not active_tool:
            return {'CANCELLED'}

        tool_help_urls = {
            f'retopoflow.{tool}': f'https://docs.retopoflow.com/v4/{tool}.html'
            for tool in [
                'polypen', 'polystrips',
                'strokes', 'contours',
                'tweak', 'relax',
            ]
        }
        # both Patches tools share the same docs page
        tool_help_urls['retopoflow.legacy_patches'] = 'https://docs.retopoflow.com/v4/patches.html'
        tool_help_urls['retopoflow.patches'] = 'https://docs.retopoflow.com/v4/patches.html'

        fallback_url = 'https://docs.retopoflow.com/index.html'

        _ = bpy.ops.wm.url_open(
            url=tool_help_urls.get(active_tool, fallback_url)
        )

        return {'FINISHED'}


class RFOperator_Launch_NewIssue(RFRegisterClass, Operator):
    bl_idname      : str = "retopoflow.launch_newissue"
    bl_label       : str = 'Report Retopoflow Issue'
    bl_space_type  : str = "VIEW_3D"
    bl_region_type : str = "TOOLS"
    bl_options : set[str] = set()

    @classmethod
    def poll(cls, context : Context) -> bool:
        RFCore = RFGlobals.RFCore_None
        return RFCore is not None and RFCore.is_running

    def execute(self, context : Context) -> set[str]:
        _ = bpy.ops.wm.url_open(
            url='https://github.com/CGCookie/retopoflow/issues/new/choose'
        )
        return {'FINISHED'}


keymaps = []

def register():
    keyconfigs = bpy.context.window_manager.keyconfigs.addon
    if keyconfigs:
        km = keyconfigs.keymaps.new(name='3D View', space_type='VIEW_3D')
        kmi = km.keymap_items.new('retopoflow.launch_help', 'F1', 'PRESS', ctrl=False, shift=False, alt=False)
        keymaps.append((km, kmi))

        km = keyconfigs.keymaps.new(name='3D View', space_type='VIEW_3D')
        kmi = km.keymap_items.new('retopoflow.launch_newissue', 'F1', 'PRESS', ctrl=False, shift=False, alt=True)
        keymaps.append((km, kmi))

def unregister():
    for km, kmi in keymaps:
        km.keymap_items.remove(kmi)
    keymaps.clear()
