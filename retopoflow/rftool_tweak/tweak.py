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
from itertools import chain
from random import random
from bmesh.types import BMVert, BMEdge, BMFace
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

import math
import time
from typing import List
from enum import Enum

from ..rftool_base import RFTool_Base
from ..rfbrush_base import RFBrush_Base
from ..common.bmesh import get_bmesh_emesh, NearestBMVert
from ..common.drawing import (
    Drawing,
    CC_2D_POINTS,
    CC_2D_LINES,
    CC_2D_LINE_STRIP,
    CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES,
    CC_2D_TRIANGLE_FAN,
    CC_3D_TRIANGLES,
)
from ..common.icons import get_path_to_blender_icon
from ..common.operator import RFOperator, wrap_property, chain_rf_keymaps, execute_operator, poll_retopoflow
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, size2D_to_size, vec_forward, mouse_from_event
from ..common.maths import view_forward_direction, lerp
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.maths import Color, Frame
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.timerhandler import TimerHandler

from .tweak_logic import Tweak_Logic

from ..rfbrushes.falloff_brush import create_falloff_brush

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.masking_panel import draw_masking_panel
from ..rfpanels.mirror_panel import draw_mirror_panel, draw_mirror_popover
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.help_panel import draw_help_panel
from ..common.interface import draw_line_separator

from ..rfoperators.launch_browser import create_launch_browser_operator, RFOperator_Launch_NewIssue

from ..preferences import RF_Prefs

RFBrush_Tweak, RFOperator_TweakBrush_Adjust = create_falloff_brush(
    'tweak_brush',
    'Tweak Brush',
    radius=100,
    color=Color.from_ints(255, 145,  0, 255),
)

class RFOperator_Tweak(RFOperator):
    bl_idname = "retopoflow.tweak"
    bl_label = 'Tweak'
    bl_description = 'Tweak the vertex positions'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'UNDO', 'INTERNAL'}

    rf_keymaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS'}, None),
    ]
    rf_status = ['LMB: Tweak']

    brush_radius: wrap_property(
        RFBrush_Tweak, 'radius', 'int',
        name='Radius',
        description='Radius of the brush in Blender UI units before it gets projected onto the mesh',
        subtype='PIXEL',
        min=1,
        max=1000,
        default=100,
    )
    brush_falloff: wrap_property(
        RFBrush_Tweak, 'falloff', 'float',
        name='Falloff',
        description='How much strength the outside of the brush has as compared to the center',
        min=0.0,
        max=1.00,
        default=1.00,
    )
    brush_strength: wrap_property(
        RFBrush_Tweak, 'strength', 'float',
        name='Strength',
        description='Strength of the brush',
        min=0.01,
        max=1.00,
        default=0.75,
    )


    include_corners: bpy.props.BoolProperty(
        name='Corners',
        description='Include corners (vertices with exactly two edges)',
        default = True,
    )
    include_occluded: bpy.props.BoolProperty(
        name='Occluded',
        description='Include vertices that are hidden behind other geometry',
        default = False,
    )
    mask_boundary: bpy.props.EnumProperty(
        name='Mask: Boundary',
        description='How to handle boundary geometry',
        items=[
            ('INCLUDE', 'Include', 'Tweak vertices regardless of being along boundary', 'SELECT_EXTEND', 2),
            ('SLIDE',   'Slide',   'Tweak vertices along boundary, but move them by sliding along boundary', 'SNAP_MIDPOINT', 1),
            ('EXCLUDE', 'Exclude', 'Do not tweak vertices along boundary', 'SELECT_DIFFERENCE', 0),
        ],
        default='INCLUDE',
    )
    mask_symmetry: bpy.props.EnumProperty(
        name='Mask: Symmetry',
        description='How to handle geometry near symmetry plane',
        items=[
            ('INCLUDE', 'Include', 'Tweak vertices regardless of being along symmetry plane', 'SELECT_EXTEND', 2),
            ('SLIDE',   'Slide',   'Tweak vertices along symmetry plane, but move them by sliding along symmetry plane', 'SNAP_MIDPOINT', 1),
            ('EXCLUDE', 'Exclude', 'Do not tweak vertices along symmetry plane', 'SELECT_DIFFERENCE', 0),
        ],
        default='SLIDE',
    )
    mask_selected: bpy.props.EnumProperty(
        name='Mask: Selected',
        description='How to handle selected geometry',
        items=[
            ('ALL',     'All',     'Tweak vertices regardless of selection', 'SELECT_EXTEND', 2),
            ('ONLY',    'Only',    'Tweak only selected vertices', 'SELECT_INTERSECT', 1),
            ('EXCLUDE', 'Exclude', 'Tweak only unselected vertices', 'SELECT_DIFFERENCE', 0),
        ],
        default='ALL',
    )

    def init(self, context, event):
        # print(f'STARTING POLYPEN')
        self.logic = Tweak_Logic(context, event, RFTool_Tweak.rf_brush, self)
        self.tickle(context)
        self.timer = TimerHandler(120, context=context, enabled=True)

    def reset(self):
        pass

    def update(self, context, event):
        self.logic.update(context, event)

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}

        if event.value == 'PRESS' and event.type in {'RIGHTMOUSE', 'ESC'}:
            # Should this undo or just stop?
            self.logic.cancel(context)
            return {'CANCELLED'}

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            context.area.tag_redraw()
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'} # allow other operators, such as UNDO!!!

    def finish(self, context):
        self.timer.stop()

    def draw_postpixel(self, context):
        if not self.RFCore.is_current_area(context): return
        # self.logic.draw(context)

RFOperator_Tweak_Launch_Help = create_launch_browser_operator(
    'RFOperator_Tweak_Launch_Help',
    'retopoflow.tweak_launch_help',
    'Tweak: Launch Help Docs',
    'https://docs.retopoflow.com/v4/tweak.html',
    rf_keymap_press='F1',
)

@execute_operator('switch_to_tweak', 'RetopoFlow: Switch to Tweak', fn_poll=poll_retopoflow)
def switch_rftool(context):
    import bl_ui
    bl_ui.space_toolsystem_common.activate_by_id(context, 'VIEW_3D', 'retopoflow.tweak')  # matches bl_idname of RFTool_Base below




class RFTool_Tweak(RFTool_Base):
    bl_idname = "retopoflow.tweak"
    bl_label = "Tweak"
    bl_description = "Tweak the vertex positions"
    bl_icon = get_path_to_blender_icon('tweak')
    bl_widget = None
    bl_operator = 'retopoflow.tweak'

    rf_brush = RFBrush_Tweak()
    rf_brush.set_operator(RFOperator_Tweak)

    bl_keymap = chain_rf_keymaps(
        RFOperator_Tweak,
        RFOperator_TweakBrush_Adjust,
        RFOperator_Tweak_Launch_Help,
        RFOperator_Launch_NewIssue,
    )

    def draw_settings(context, layout, tool):
        props = tool.operator_properties(RFOperator_Tweak.bl_idname)
        prefs = RF_Prefs.get_prefs(context)

        # TOOL_HEADER: 3d view > toolbar
        # UI: 3d view > n-panel
        # WINDOW: properties > tool
        if context.region.type == 'TOOL_HEADER':
            layout.label(text="Brush:")
            layout.prop(props, 'brush_radius')
            layout.prop(props, 'brush_strength', slider=True)
            layout.prop(props, 'brush_falloff', slider=True)
            if prefs.expand_masking:
                draw_line_separator(layout)
                layout.row(heading='Selected:', align=True).prop(props, 'mask_selected', expand=True, icon_only=True)
                layout.separator()
                layout.row(heading='Boundary:', align=True).prop(props, 'mask_boundary', expand=True, icon_only=True)
                # layout.prop(props, 'mask_symmetry', text="Symmetry")  # TODO: Implement
                layout.separator()
                layout.prop(props, 'include_corners',   text="Corners")
                layout.prop(props, 'include_occluded', text="Occluded")
            else:
                layout.popover('RF_PT_Masking')
            draw_line_separator(layout)
            row = layout.row(align=True)
            row.popover('RF_PT_MeshCleanup', text='Clean Up')
            row.operator("retopoflow.meshcleanup", text='', icon='PLAY').affect_all=False
            draw_mirror_popover(context, layout)
            layout.popover('RF_PT_General', text='', icon='OPTIONS')
            layout.popover('RF_PT_Help', text='', icon='INFO_LARGE')

        elif context.region.type in {'UI', 'WINDOW'}:
            header, panel = layout.panel(idname='tweak_brush_panel', default_closed=False)
            header.label(text="Brush")
            if panel:
                panel.prop(props, 'brush_radius')
                panel.prop(props, 'brush_strength', slider=True)
                panel.prop(props, 'brush_falloff', slider=True)
            draw_masking_panel(context, layout)
            draw_cleanup_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

        else:
            print(f'RFTool_Tweak.draw_settings: {context.region.type=}')

    @classmethod
    def activate(cls, context):
        # TODO: some of the following might not be needed since we are creating our
        #       own transform operators
        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter('Tweak')
        if prefs.setup_automerge:
            cls.resetter['context.tool_settings.use_mesh_automerge'] = False
        if prefs.setup_snapping:
            # cls.resetter['context.tool_settings.snap_elements_base'] = {'VERTEX'}
            cls.resetter.store('context.tool_settings.snap_elements_base')
            cls.resetter['context.tool_settings.snap_elements_individual'] = {'FACE_NEAREST'}

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
