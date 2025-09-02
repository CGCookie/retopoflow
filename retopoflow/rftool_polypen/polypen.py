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
from ..common.bmesh import get_bmesh_emesh, NearestBMVert
from ..common.icons import get_path_to_blender_icon
from ..common.operator import invoke_operator, execute_operator, RFOperator, RFRegisterClass, chain_rf_keymaps, wrap_property, poll_retopoflow
from ..common.raycast import raycast_point_valid_sources
from ..common.maths import view_forward_direction
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.blender import get_path_from_addon_common, event_modifier_check
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import clamp
from ...addon_common.common.utils import iter_pairs

from ..rfoperators.quickswitch import RFOperator_Relax_QuickSwitch, RFOperator_Tweak_QuickSwitch
from ..rfoperators.transform import RFOperator_Translate
from ..rfoperators.launch_browser import RFOperator_Launch_Help, RFOperator_Launch_NewIssue

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.mirror_panel import draw_mirror_panel, draw_mirror_popover
from ..rfpanels.help_panel import draw_help_panel
from ..common.interface import draw_line_separator

from ..preferences import RF_Prefs

from .polypen_logic import PP_Logic


class PolyPen_Insert_Modes:
    insert_modes = [
        # (identifier, name, description, icon, number)  or  (identifier, name, description, number)
        # must have number?
        # None is a separator
        ("VERT-ONLY", "Vertex", "Insert vertices only",           1),
        ("EDGE-ONLY", "Edge", "Insert edges only",                2),
        ("TRI-ONLY",  "Triangle",  "Insert triangles only",       3),  # 'MESH_DATA'
        ("TRI/QUAD",  "Tri/Quad",  "Insert triangles then quads", 0),
        ("QUAD-ONLY", "Quad", "Insert quads only",                4),
    ]
    insert_mode = 0

    @staticmethod
    def generate_operators():
        ops_insert = []
        def gen_insert_mode(idname, label, value):
            nonlocal ops_insert
            rf_idname = f'retopoflow.polypen_setinsertmode_{idname.lower()}'
            rf_label = label
            class RFTool_OT_PolyPen_SetInsertMode:
                bl_idname = rf_idname
                bl_label = rf_label
                bl_description = f'Set PolyPen Insert Mode to {label}'
                def execute(self, context):
                    PolyPen_Insert_Modes.set_insert_mode(None, value)
                    context.area.tag_redraw()
                    return {'FINISHED'}
            opname = f'RFTool_OT_PolyPen_SetInsertMode_{idname}'
            op = type(opname, (RFTool_OT_PolyPen_SetInsertMode, RFRegisterClass, bpy.types.Operator), {})
            ops_insert += [(rf_idname, rf_label)]

        gen_insert_mode('VertOnly', 'Vert-Only', 1)
        gen_insert_mode('EdgeOnly', 'Edge-Only', 2)
        gen_insert_mode('TriOnly',  'Tri-Only',  3)
        gen_insert_mode('TriQuad',  'Tri/Quad',  0)
        gen_insert_mode('QuadOnly', 'Quad-Only', 4)

    @staticmethod
    def get_insert_mode(self): return PolyPen_Insert_Modes.insert_mode
    @staticmethod
    def set_insert_mode(self, v): PolyPen_Insert_Modes.insert_mode = v

class PolyPen_Quad_Stability:
    quad_stability = 1

    @staticmethod
    def generate_operators():
        ops_insert = []
        def gen_quad_stability(idname, label, value):
            nonlocal ops_insert
            rf_idname = f'retopoflow.polypen_quad_stability_{idname.lower()}'
            rf_label = label
            class RFTool_OT_PolyPen_SetQuadStability:
                bl_idname = rf_idname
                bl_label = rf_label
                bl_description = f'Set PolyPen Quad Stability to {label}'
                def execute(self, context):
                    PolyPen_Quad_Stability.set_quad_stability(None, float(label))
                    context.area.tag_redraw()
                    return {'FINISHED'}
            opname = f'RFTool_OT_PolyPen_SetQuadStability_{idname}'
            op = type(opname, (RFTool_OT_PolyPen_SetQuadStability, RFRegisterClass, bpy.types.Operator), {})
            ops_insert += [(rf_idname, rf_label)]

        gen_quad_stability('quarter',  '0.25',  0)
        gen_quad_stability('half', '0.5', 1)
        gen_quad_stability('threequarters', '0.75', 2)
        gen_quad_stability('full',  '1',  3)

    @staticmethod
    def get_quad_stability(self): return PolyPen_Quad_Stability.quad_stability
    @staticmethod
    def set_quad_stability(self, v): PolyPen_Quad_Stability.quad_stability = v


# TODO: DO NOT CALL THIS HERE!  SHOULD ONLY GET CALLED ONCE
#       COULD POTENTIALLY CREATE MULTIPLE OPERATORS WITH SAME NAME
PolyPen_Insert_Modes.generate_operators()
PolyPen_Quad_Stability.generate_operators()


class RFOperator_PolyPen(RFOperator):
    bl_idname = "retopoflow.polypen"
    bl_label = 'PolyPen'
    bl_description = 'Create complex topology on vertex-by-vertex basis'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),
        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, None),
    ]
    rf_status = ['LMB: Insert', 'MMB: (nothing)', 'RMB: (nothing)']

    insert_mode: wrap_property(
        PolyPen_Insert_Modes, 'insert_mode', 'enum',
        name='Insert Mode',
        description='Insertion mode for PolyPen',
        items=PolyPen_Insert_Modes.insert_modes,
        default="TRI/QUAD",
    )
    quad_stability: wrap_property(
        PolyPen_Quad_Stability, 'quad_stability', 'float',
        name='Quad Stability',
        description='Stability of parallel edges',
        min=0.00,
        max=1.00,
        default=1.00,
    )

    @classmethod
    def can_start(cls, context):
        return not cls.is_running()

    def init(self, context, event):
        # print(f'STARTING POLYPEN')
        self.logic = PP_Logic(context, event)
        self.tickle(context)
        self.done = False
        self.shift_held = False

    def reset(self):
        self.logic.reset()

    def update(self, context, event):
        if self.shift_held != event.shift:
            self.shift_held = event.shift
            context.area.tag_redraw()
        if not event.ctrl:
            self.done = True
        if self.done:
            if not self.is_active():
                # wait until we're active (could happen when transforming)
                return {'PASS_THROUGH'}
            self.logic.cleanup()
            return {'FINISHED'}

        self.logic.update(context, event, self.insert_mode, self.quad_stability)

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
            self.logic.commit(context, event)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            context.area.tag_redraw()

        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!

    def draw_postpixel(self, context):
        if not self.RFCore.is_current_area(context): return
        if self.shift_held: return
        self.logic.draw(context)


@execute_operator('switch_to_polypen', 'RetopoFlow: Switch to PolyPen', fn_poll=poll_retopoflow)
def switch_rftool(context):
    import bl_ui
    bl_ui.space_toolsystem_common.activate_by_id(context, 'VIEW_3D', 'retopoflow.polypen')  # matches bl_idname of RFTool_Base below


class RFTool_PolyPen(RFTool_Base):
    bl_idname = "retopoflow.polypen"
    bl_label = "PolyPen"
    bl_description = "Create complex topology on vertex-by-vertex basis"
    bl_icon = get_path_to_blender_icon('polypen')
    bl_widget = None
    bl_operator = 'retopoflow.polypen'

    props = None  # needed to reset properties

    bl_keymap = chain_rf_keymaps(
        RFOperator_PolyPen,
        RFOperator_Translate,
        RFOperator_Launch_Help,
        RFOperator_Launch_NewIssue,
        RFOperator_Relax_QuickSwitch,
        RFOperator_Tweak_QuickSwitch,
    )

    def draw_settings(context, layout, tool):
        props_polypen = tool.operator_properties(RFOperator_PolyPen.bl_idname)
        RFTool_PolyPen.props = props_polypen

        if context.region.type == 'TOOL_HEADER':
            layout.prop(props_polypen, 'insert_mode', text='Insert')
            if props_polypen.insert_mode == 'QUAD-ONLY':
                layout.prop(props_polypen, 'quad_stability', slider=True)
            draw_line_separator(layout)
            layout.popover('RF_PT_TweakCommon', text='Tweaking')
            row = layout.row(align=True)
            row.popover('RF_PT_MeshCleanup', text='Clean Up')
            row.operator("retopoflow.meshcleanup", text='', icon='PLAY').affect_all=False
            draw_mirror_popover(context, layout)
            layout.popover('RF_PT_General', text='', icon='OPTIONS')
            layout.popover('RF_PT_Help', text='', icon='INFO_LARGE' if bpy.app.version >= (4,3,0) else 'INFO')

        else:
            header, panel = layout.panel(idname='polypen_insert_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                panel.prop(props_polypen, 'insert_mode', text='Method')
                if props_polypen.insert_mode == 'QUAD-ONLY':
                    panel.prop(props_polypen, 'quad_stability', slider=True)
            draw_cleanup_panel(context, layout)
            draw_tweaking_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context):
        # TODO: some of the following might not be needed since we are creating our
        #       own transform operators
        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter("PolyPen")
        if prefs.setup_automerge:
            cls.resetter['context.tool_settings.use_mesh_automerge'] = True
        if prefs.setup_snapping:
            # cls.resetter['context.tool_settings.snap_elements_base'] = {'VERTEX'}
            cls.resetter.store('context.tool_settings.snap_elements_base')
            cls.resetter['context.tool_settings.snap_elements_individual'] = {'FACE_NEAREST'}
        if prefs.setup_selection_mode:
            cls.resetter['context.tool_settings.mesh_select_mode'] = [True, True, False]

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
