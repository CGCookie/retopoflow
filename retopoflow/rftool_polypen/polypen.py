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
from ..common.icons import get_path_to_blender_icon
from ..common.operator import invoke_operator, execute_operator, RFOperator, RFRegisterClass, chain_rf_keymaps, wrap_property
from ..common.raycast import raycast_point_valid_sources
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


class PolyPen_Properties:
    insert_modes = [
        # (identifier, name, description, icon, number)  or  (identifier, name, description, number)
        # must have number?
        # None is a separator
        ("EDGE-ONLY", "Edge-Only", "Insert edges only",           1),
        ("TRI-ONLY",  "Tri-Only",  "Insert triangles only",       2),  # 'MESH_DATA'
        ("TRI/QUAD",  "Tri/Quad",  "Insert triangles then quads", 3),
        ("QUAD-ONLY", "Quad-Only", "Insert quads only",           4),
    ]
    insert_mode = 3

    rf_keymaps = []

    @staticmethod
    def generate_operators():
        ops_insert = []
        def gen_insert_mode(idname, label, value):
            nonlocal ops_insert
            rf_idname = f'retopoflow.polypen_setinsertmode_{idname.lower()}'
            rf_label = label
            class RFTool_OT_PolyPen_SetInsertMode(RFRegisterClass, bpy.types.Operator):
                bl_idname = rf_idname
                bl_label = rf_label
                bl_description = f'Set PolyPen Insert Mode to {label}'
                def execute(self, context):
                    PolyPen_Properties.set_insert_mode(None, value)
                    context.area.tag_redraw()
                    return {'FINISHED'}
            RFTool_OT_PolyPen_SetInsertMode.__name__ = f'RFTool_OT_PolyPen_SetInsertMode_{idname}'
            ops_insert += [(rf_idname, rf_label)]

        class VIEW3D_MT_PIE_PolyPen(RFRegisterClass, bpy.types.Menu):
            bl_label = 'Select PolyPen Insert Mode'

            def draw(self, context):
                nonlocal ops_insert
                layout = self.layout
                pie = layout.menu_pie()
                for bl_idname, bl_label in ops_insert:
                    pie.operator(bl_idname, text=bl_label) # icon='OBJECT_DATAMODE'
                # # 4 - LEFT
                # # 6 - RIGHT
                # # 2 - BOTTOM
                # # 8 - TOP
                # # 7 - TOP - LEFT
                # # 9 - TOP - RIGHT
                # # 1 - BOTTOM - LEFT
                # # 3 - BOTTOM - RIGHT
                # pie.separator()

        class RFTool_OT_Show_PolyPen_Pie(RFRegisterClass, bpy.types.Operator):
            bl_idname = 'retopoflow.polypen_setinsertmode_piemenu'
            bl_label = 'PolyPen Insert Mode Pie Menu'
            def execute(self, context):
                bpy.ops.wm.call_menu_pie(name="VIEW3D_MT_PIE_PolyPen")
                return {'FINISHED'}

        gen_insert_mode('EdgeOnly', 'Edge-Only', 1)
        gen_insert_mode('TriOnly',  'Tri-Only',  2)
        gen_insert_mode('TriQuad',  'Tri/Quad',  3)
        gen_insert_mode('QuadOnly', 'Quad-Only', 4)

        PolyPen_Properties.rf_keymaps += [
            (RFTool_OT_Show_PolyPen_Pie.bl_idname, {'type': 'ACCENT_GRAVE', 'shift': True, 'value': 'PRESS'}, None),
            (RFTool_OT_Show_PolyPen_Pie.bl_idname, {'type': 'Q', 'value': 'PRESS'}, None),
        ]

    @staticmethod
    def get_insert_mode(self): return PolyPen_Properties.insert_mode
    @staticmethod
    def set_insert_mode(self, v): PolyPen_Properties.insert_mode = v

# TODO: DO NOT CALL THIS HERE!  SHOULD ONLY GET CALLED ONCE
#       COULD POTENTIALLY CREATE MULTIPLE OPERATORS WITH SAME NAME
PolyPen_Properties.generate_operators()


class RFOperator_PolyPen(RFOperator):
    bl_idname = "retopoflow.polypen"
    bl_label = 'PolyPen'
    bl_description = 'Create complex topology on vertex-by-vertex basis'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None), #{'properties': [('insert_mode', 'TRI-ONLY')]},
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),
    ]
    rf_status = ['LMB: Insert', 'MMB: (nothing)', 'RMB: (nothing)']

    insert_mode: wrap_property(
        PolyPen_Properties, 'insert_mode', 'enum',
        name='Insert Mode',
        description='Insertion mode for PolyPen',
        items=PolyPen_Properties.insert_modes,
    )
    # insert_mode: bpy.props.EnumProperty(
    #     name='Insert Mode',
    #     description='Insertion mode for PolyPen',
    #     items=PolyPen_Properties.insert_modes,
    #     get=PolyPen_Properties.get_insert_mode,
    #     set=PolyPen_Properties.set_insert_mode,
    # )
    quad_stability: bpy.props.FloatProperty(
        name='Quad Stability',
        description='Stability of parallel edges',
        min=0.00,
        max=1.00,
        default=1.00,
    )

    def init(self, context, event):
        # print(f'STARTING POLYPEN')
        self.logic = PP_Logic(context, event)
        self.tickle(context)

    def reset(self):
        self.logic.reset()

    def update(self, context, event):
        self.logic.update(context, event, self.insert_mode, self.quad_stability)

        if not event.ctrl:
            # print(F'LEAVING POLYPEN')
            self.logic.cleanup()
            return {'FINISHED'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.logic.commit(context, event)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            context.area.tag_redraw()
            return {'PASS_THROUGH'}

        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!

    def draw_postpixel(self, context):
        self.logic.draw(context)



class RFTool_PolyPen(RFTool_Base):
    bl_idname = "retopoflow.polypen"
    bl_label = "PolyPen"
    bl_description = "Create complex topology on vertex-by-vertex basis"
    bl_icon = get_path_to_blender_icon('polypen')
    bl_widget = None
    bl_operator = 'retopoflow.polypen'

    bl_keymap = chain_rf_keymaps(RFOperator_PolyPen, RFOperator_Translate, PolyPen_Properties)

    def draw_settings(context, layout, tool):
        # layout.label(text="PolyPen")
        props = tool.operator_properties(RFOperator_PolyPen.bl_idname)
        layout.prop(props, 'insert_mode')
        if props.insert_mode == 'QUAD-ONLY':
            layout.prop(props, 'quad_stability', slider=True)

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
