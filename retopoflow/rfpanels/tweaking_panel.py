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
from ..rfoperators.transform import RFOperator_Translate_ScreenSpace

def draw_tweaking_options(layout, context):
    tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH')
    props_translate = tool.operator_properties(RFOperator_Translate_ScreenSpace.bl_idname)

    layout.use_property_split = True

    layout.label(text='Selection')
    layout.prop(props_translate, 'distance2d', text='Distance')
    layout.label(text='Auto Merge')
    layout.prop(context.scene.tool_settings, 'use_mesh_automerge', text='Enable', toggle=False)
    row = layout.row()
    row.enabled = context.scene.tool_settings.use_mesh_automerge
    row.prop(context.scene.tool_settings, 'double_threshold', text='Threshold')

def draw_tweaking_panel(layout, context):
    header, panel = layout.panel(idname='tweak_panel_common', default_closed=False)
    header.label(text="Tweaking")
    if panel:
        draw_tweaking_options(panel, context)

class RFMenu_PT_TweakCommon(bpy.types.Panel):
    bl_label = "Tweaking"
    bl_idname = "RF_PT_TweakCommon"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        draw_tweaking_options(self.layout, context)

def register():
    bpy.utils.register_class(RFMenu_PT_TweakCommon)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_TweakCommon)