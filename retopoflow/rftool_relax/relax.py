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
import os
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
from ...addon_common.common.timerhandler import TimerHandler

from ..rfoperators.transform import RFOperator_Translate

from .relax_logic import Relax_Logic



class RFOperator_Relax(RFOperator):
    bl_idname = "retopoflow.relax"
    bl_label = 'Relax'
    bl_description = 'Relax the vertex positions to smooth out topology'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFTMOUSE',  'value': 'PRESS'}, None),
    ]
    # rf_status = ['LMB: Insert', 'MMB: (nothing)', 'RMB: (nothing)']

    def init(self, context, event):
        # print(f'STARTING POLYPEN')
        self.logic = Relax_Logic(context, event)
        self.tickle(context)
        self.timer = TimerHandler(120, context=context, enabled=True)

    def reset(self):
        # self.logic.reset()
        pass

    def update(self, context, event):
        self.logic.update(context, event)
        # self.logic.update(context, event, self.insert_mode)

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.timer.stop()
            return {'FINISHED'}

        # if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
        #     # self.logic.commit(context, event)
        #     return {'RUNNING_MODAL'}

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            context.area.tag_redraw()
            return {'PASS_THROUGH'}

        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!

    def draw_postpixel(self, context):
        # self.logic.draw(context)
        pass


class RFTool_Relax(RFTool_Base):
    bl_idname = "retopoflow.relax"
    bl_label = "Relax"
    bl_description = "Relax the vertex positions to smooth out topology"
    bl_icon = os.path.join(os.path.dirname(__file__), '..', '..', 'icons', 'relax')
    bl_widget = None
    bl_operator = 'retopoflow.relax'

    bl_keymap = (
        *[ keymap for keymap in RFOperator_Relax.rf_keymaps ],
    )

    def draw_settings(context, layout, tool):
        # layout.label(text="PolyPen")
        props = tool.operator_properties(RFOperator_Relax.bl_idname)
        # layout.prop(props, 'insert_mode')

    @classmethod
    def activate(cls, context):
        # TODO: some of the following might not be needed since we are creating our
        #       own transform operators
        cls.reseter = Reseter()
        cls.reseter['context.tool_settings.use_mesh_automerge'] = True
        cls.reseter['context.tool_settings.double_threshold'] = 0.01
        # cls.reseter['context.tool_settings.snap_elements_base'] = {'VERTEX'}
        cls.reseter['context.tool_settings.snap_elements_individual'] = {'FACE_PROJECT', 'FACE_NEAREST'}
        cls.reseter['context.tool_settings.mesh_select_mode'] = [True, True, True]

    @classmethod
    def deactivate(cls, context):
        cls.reseter.reset()
