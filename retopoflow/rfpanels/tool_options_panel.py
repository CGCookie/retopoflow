'''
Copyright (C) 2026 CG Cookie
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

# One popover covering every tool's own settings, so the tools pie can raise the active tool's
# options from its section header. It draws the same body that tool's sidebar Insert or Brush
# panel draws, and nothing else: the shared panels underneath it there (Tweaking, Masking, Clean
# Up, Mirror, Snapping, General, Help) have their own homes in the pie already.

import bpy
from bpy.types import Context, Panel, WorkSpaceTool

from ..common.bpy_helper import BL_SPACE_TYPES, BL_REGION_TYPES

from ..rftool_polypen.polypen import draw_polypen_options
from ..rftool_polystrips.polystrips import draw_polystrips_options
from ..rftool_strokes.strokes import draw_strokes_options
from ..rftool_tweak.tweak import draw_tweak_options
from ..rftool_relax.relax import draw_relax_options
from ..rftool_contours.contours import draw_contours_props
from ..rftool_legacy_patches.legacy_patches import draw_patches_props


# Contours and Patches already had their settings extracted, on their own terms, so those two are
# adapted rather than reshaped. `None` for Contours means "not a redo panel".
TOOL_OPTIONS = {
    'retopoflow.polypen':        draw_polypen_options,
    'retopoflow.polystrips':     draw_polystrips_options,
    'retopoflow.strokes':        draw_strokes_options,
    'retopoflow.tweak':          draw_tweak_options,
    'retopoflow.relax':          draw_relax_options,
    'retopoflow.contours':       lambda context, layout, props: draw_contours_props(context, layout, props, None),
    'retopoflow.legacy_patches': lambda context, layout, props: draw_patches_props(layout, props, header=False),
}


def has_tool_options(tool : WorkSpaceTool | None) -> bool:
    return bool(tool) and tool.idname in TOOL_OPTIONS


class RFMenu_PT_ToolOptions(Panel):
    bl_label : str = 'Tool Options'
    bl_idname : str = 'RF_PT_ToolOptions'
    bl_space_type : BL_SPACE_TYPES = 'VIEW_3D'
    bl_region_type : BL_REGION_TYPES = 'HEADER'
    bl_ui_units_x : int = 11

    def draw(self, context : Context):
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        draw = TOOL_OPTIONS.get(tool.idname) if tool else None
        if not draw or not self.layout: return
        draw(context, self.layout, tool.operator_properties(tool.idname))


def register():
    bpy.utils.register_class(RFMenu_PT_ToolOptions)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_ToolOptions)
