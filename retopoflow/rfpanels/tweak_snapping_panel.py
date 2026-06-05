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
from ..common.sources import draw_hard_surface_snapping


def _tweak_props(context):
    tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
    return tool.operator_properties(tool.idname) if tool else None


def draw_tweak_snapping_options(context, layout):
    props = _tweak_props(context)
    if not props: return
    layout.use_property_split = True
    layout.use_property_decorate = False
    draw_hard_surface_snapping(layout, props, guide_loops=True)


def draw_tweak_snapping_panel(context, layout):
    header, panel = layout.panel(idname='tweak_panel_source_edges', default_closed=True)
    header.label(text='Hard Surface Snapping')
    if panel:
        draw_tweak_snapping_options(context, panel)


class RFMenu_PT_TweakSnapping(bpy.types.Panel):
    bl_label = "Hard Surface Snapping"
    bl_idname = "RF_PT_TweakSnapping"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 12

    def draw(self, context):
        draw_tweak_snapping_options(context, self.layout)


def register():
    bpy.utils.register_class(RFMenu_PT_TweakSnapping)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_TweakSnapping)
