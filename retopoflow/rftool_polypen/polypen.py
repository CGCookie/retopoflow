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

import blf
import bmesh
import bpy
import gpu
from bmesh.types import BMVert, BMEdge, BMFace
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

import math
import time
from typing import List
from enum import Enum

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, get_select_layers, NearestBMVert
from ..common.operator import invoke_operator, execute_operator, RFOperator
from ..common.raycast import raycast_mouse_valid_sources, raycast_point_valid_sources
from ..common.maths import view_forward_direction
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import clamp
from ...addon_common.common.utils import iter_pairs

from ..rfoperators.transform import RFOperator_Translate

from .polypen_logic import PP_Logic

reseter = Reseter()


class RFOperator_PolyPen(RFOperator):
    bl_idname = "retopoflow.polypen"
    bl_label = 'PolyPen'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymap = {'type': 'LEFT_CTRL', 'value': 'PRESS'}
    rf_status = ['LMB: Insert', 'MMB: (nothing)', 'RMB: (nothing)']

    def init(self, context, event):
        print(f'STARTING POLYPEN')
        self.logic = PP_Logic(context, event)

    def reset(self):
        self.logic.reset()

    def update(self, context, event):
        self.logic.update(context, event)

        if not event.ctrl:
            print(F'LEAVING POLYPEN')
            return {'FINISHED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.logic.commit(context, event)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            context.area.tag_redraw()

        return {'PASS_THROUGH'}

    def draw_postpixel(self, context):
        self.logic.draw(context)


class RFTool_PolyPen(RFTool_Base):
    bl_idname = "retopoflow.polypen"
    bl_label = "PolyPen"
    bl_description = "Create complex topology on vertex-by-vertex basis"
    bl_icon = "ops.generic.select_circle"
    bl_widget = None

    bl_keymap = (
        (RFOperator_PolyPen.bl_idname, RFOperator_PolyPen.rf_keymap, None),
        (RFOperator_Translate.bl_idname, RFOperator_Translate.rf_keymap, None),
    )

    @classmethod
    def activate(cls, context):
        # TODO: some of the following might not be needed since we are creating our
        #       own transform operators
        reseter['context.tool_settings.use_mesh_automerge'] = True4
        reseter['context.tool_settings.double_threshold'] = 0.01
        # reseter['context.tool_settings.snap_elements_base'] = {'VERTEX'}
        reseter['context.tool_settings.snap_elements_individual'] = {'FACE_PROJECT', 'FACE_NEAREST'}
        reseter['context.tool_settings.mesh_select_mode'] = [True, True, True]

    @classmethod
    def deactivate(cls, context):
        reseter.reset()
