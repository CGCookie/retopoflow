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
from ..common.operator import RFRegisterClass
from ..rftool_polypen.polypen import RFOperator_PolyPen, RFTool_PolyPen
from ..rftool_polystrips.polystrips import RFOperator_PolyStrips, RFTool_PolyStrips
from ..rftool_strokes.strokes import RFOperator_Strokes, RFTool_Strokes
from ..rftool_contours.contours import RFOperator_Contours, RFTool_Contours
from ..rftool_tweak.tweak import RFOperator_Tweak, RFTool_Tweak
from ..rftool_relax.relax import RFOperator_Relax, RFTool_Relax
from ..preferences import RF_Prefs


def reset_tool_settings(context):
    tools = {
        'PolyPen': {
            'RFTool': RFTool_PolyPen,
            'RFOperator': RFOperator_PolyPen
        },
        'PolyStrips': {
            'RFTool': RFTool_PolyStrips,
            'RFOperator': RFOperator_PolyStrips
        },
        'Strokes': {
            'RFTool': RFTool_Strokes,
            'RFOperator': RFOperator_Strokes
        },
        'Contours': {
            'RFTool': RFTool_Contours,
            'RFOperator': RFOperator_Contours
        },
        'Tweak': {
            'RFTool': RFTool_Tweak,
            'RFOperator': RFOperator_Tweak
        },
        'Relax': {
            'RFTool': RFTool_Relax,
            'RFOperator': RFOperator_Relax
        },
    }

    for tool in tools.keys():
        op_props = tools[tool]['RFOperator'].__annotations__
        tool_props = tools[tool]['RFTool'].props
        if tool_props:
            for pname in op_props:
                try:
                    setattr(tool_props, pname, op_props[pname].keywords['default'])
                except Exception as e:
                    print(f'WARNING: exception thrown while attempting to reset {tool} property {pname}: {e}')

    prefs = RF_Prefs.get_prefs(context)
    for pname in prefs.__annotations__:
        try:
            setattr(prefs, pname, prefs[pname].keywords['default'])
        except Exception as e:
            print(f'WARNING: exception thrown while attempting to reset Preferences property {pname}: {e}')



class RFOperator_ApplyRetopoSettings(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.resettoolsettings"
    bl_label = "Reset Retopoflow Tools"
    bl_description = "Reset the Retopoflow tools to their default settings"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'UNDO'}

    rf_label = "Reset Retopoflow Settings"
    RFCore = None

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def execute(self, context):
        reset_tool_settings(context)
        return {'FINISHED'}