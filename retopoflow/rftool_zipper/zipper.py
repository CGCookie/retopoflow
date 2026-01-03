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

from .zipper_logic import Zipper_Logic

from ..rfoperators.quickswitch import RFOperator_Relax_QuickSwitch, RFOperator_Tweak_QuickSwitch
from ..rfoperators.maximize_watcher import RFOperator_MaximizeWatcher
from ..rfbrushes.falloff_brush import create_falloff_brush

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.masking_panel import draw_masking_panel
from ..rfpanels.mirror_panel import draw_mirror_panel, draw_mirror_popover
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.help_panel import draw_help_panel
from ..common.interface import draw_line_separator

from ..rfoperators.launch_browser import RFOperator_Launch_Help, RFOperator_Launch_NewIssue

from ..preferences import RF_Prefs


# RFBrush_Zipper, RFOperator_ZipperBrush_Adjust = create_falloff_brush(
#     'zipper_brush',
#     'Zipper Brush',
#     ignore_areas=True,
#     radius=100,
#     color=Color.from_ints(224, 128, 255, 255),
#     fn_disable=lambda event: event.shift and not event.ctrl,
# )

class RFOperator_Zipper(RFOperator):
    bl_idname = "retopoflow.zipper"
    bl_label = 'Zipper'
    bl_description = 'Zip and unzip topology'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'INTERNAL'}

    rf_keymaps = [
        (bl_idname, {'type': 'LEFT_CTRL', 'value': 'PRESS'}, {'km_context': 'init', 'km_label': ' Start Zipper'}),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),
        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, None),
    ]
    rf_status = {
        'ready': ('LMB: Zip / Unzip', ),
    }

    # rf_keymaps = [
    #     (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS'}, {'km_context': 'init', 'km_label': 'Zip'}),
    # ]
    # rf_status = ['LMB: Zip / Unzip']

    # brush_radius: wrap_property(
    #     RFBrush_Zipper, 'radius', 'int',
    #     name='Radius',
    #     description='Radius of the brush in Blender UI units before it gets projected onto the mesh',
    #     subtype='PIXEL',
    #     min=1,
    #     max=1000,
    #     default=100,
    # )
    # brush_falloff: wrap_property(
    #     RFBrush_Zipper, 'falloff', 'float',
    #     name='Falloff',
    #     description='How much strength the outside of the brush has as compared to the center',
    #     min=0.0,
    #     max=1.00,
    #     default=1.00,
    # )
    # brush_strength: wrap_property(
    #     RFBrush_Zipper, 'strength', 'float',
    #     name='Strength',
    #     description='Strength of the brush',
    #     min=0.01,
    #     max=1.00,
    #     default=0.75,
    # )


    def init(self, context, event):
        # RFTool_Zipper.rf_brush.set_operator(self)
        # RFTool_Zipper.rf_brush.update(context, event, force=True)
        # self.logic = Zipper_Logic(context, event, RFTool_Zipper.rf_brush, self)
        self.logic = Zipper_Logic(context, event)
        self.tickle(context)

    def reset(self):
        pass

    def update(self, context, event):
        if self.logic.update(context, event):
            self.tickle(context)
            context.area.tag_redraw()

        if not event.ctrl:
            return {'FINISHED'}

        # if event.type in {'RIGHTMOUSE', 'ESC'}:
        #     # Should this undo or just stop?
        #     self.logic.cancel(context)
        #     return {'CANCELLED'}

        # if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
        #     self.tickle(context)
        #     # context.area.tag_redraw()
        #     return {'PASS_THROUGH'}

        if event.type == 'Z':
            return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!
        return {'RUNNING_MODAL'}

    def finish(self, context):
        # RFTool_Zipper.rf_brush.set_operator(None)
        pass

    def draw_postpixel(self, context):
        if not self.RFCore.is_current_area(context): return
        self.logic.draw(context)


@execute_operator('switch_to_zipper', 'RetopoFlow: Switch to Zipper', fn_poll=poll_retopoflow)
def switch_rftool(context):
    RFTool_Zipper.activate_tool(context)


class RFTool_Zipper(RFTool_Base):
    bl_idname = "retopoflow.zipper"
    bl_label = "Zipper"
    bl_description = "Zipper the vertex positions"
    bl_icon = get_path_to_blender_icon('patches')  # TODO: Create!
    bl_widget = None
    bl_operator = 'retopoflow.zipper'

    # rf_brush = RFBrush_Zipper()

    props = None  # needed to reset properties

    bl_keymap = chain_rf_keymaps(
        RFOperator_Zipper,
        RFOperator_MaximizeWatcher,
        # RFOperator_ZipperBrush_Adjust,
        RFOperator_Launch_Help,
        RFOperator_Launch_NewIssue,
        RFOperator_Tweak_QuickSwitch,
        RFOperator_Relax_QuickSwitch,
    )

    def draw_settings(context, layout, tool):
        props_zipper = tool.operator_properties(RFOperator_Zipper.bl_idname)
        RFTool_Zipper.props = props_zipper
        prefs = RF_Prefs.get_prefs(context)

        # TOOL_HEADER: 3d view > toolbar
        # UI: 3d view > n-panel
        # WINDOW: properties > tool
        if context.region.type == 'TOOL_HEADER':
            # layout.label(text="Brush:")
            # layout.prop(props_zipper, 'brush_radius')
            # layout.prop(props_zipper, 'brush_strength', slider=True)
            # layout.prop(props_zipper, 'brush_falloff', slider=True)
            # if prefs.expand_masking:
            #     draw_line_separator(layout)
            #     layout.row(heading='Selected:', align=True).prop(props_zipper, 'mask_selected', expand=True, icon_only=True)
            #     layout.separator()
            #     layout.row(heading='Boundary:', align=True).prop(props_zipper, 'mask_boundary', expand=True, icon_only=True)
            #     # layout.prop(props_zipper, 'mask_symmetry', text="Symmetry")  # TODO: Implement
            #     layout.separator()
            #     layout.prop(props_zipper, 'include_corners',   text="Corners")
            #     layout.prop(props_zipper, 'include_occluded', text="Occluded")
            # else:
            #     layout.popover('RF_PT_Masking')
            draw_line_separator(layout)
            row = layout.row(align=True)
            row.popover('RF_PT_MeshCleanup', text='Clean Up')
            row.operator("retopoflow.meshcleanup", text='', icon='PLAY').affect_all=False
            draw_mirror_popover(context, layout)
            if prefs.expand_offset:
                layout.prop(context.scene.retopoflow, 'retopo_offset', text='Overlay Offset')
            layout.popover('RF_PT_General', text='', icon='OPTIONS')
            layout.popover('RF_PT_Help', text='', icon='INFO_LARGE' if bpy.app.version >= (4,3,0) else 'INFO')

        elif context.region.type in {'UI', 'WINDOW'}:
            # header, panel = layout.panel(idname='zipper_brush_panel', default_closed=False)
            # header.label(text="Brush")
            # if panel:
            #     panel.prop(props_zipper, 'brush_radius')
            #     panel.prop(props_zipper, 'brush_strength', slider=True)
            #     panel.prop(props_zipper, 'brush_falloff', slider=True)
            draw_masking_panel(context, layout)
            draw_cleanup_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

        else:
            print(f'RFTool_Zipper.draw_settings: {context.region.type=}')

    @classmethod
    def activate(cls, context):
        # TODO: some of the following might not be needed since we are creating our
        #       own transform operators
        # cls.rf_brush.set_operator(RFOperator_Zipper)

        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter('Zipper')
        if prefs.setup_automerge:
            cls.resetter['context.tool_settings.use_mesh_automerge'] = False
        if prefs.setup_snapping:
            # cls.resetter['context.tool_settings.snap_elements_base'] = {'VERTEX'}
            cls.resetter.store('context.tool_settings.snap_elements_base')
            cls.resetter['context.tool_settings.snap_elements_individual'] = {'FACE_NEAREST'}
        if prefs.setup_selection_mode:
            cls.resetter['context.tool_settings.mesh_select_mode'] = [True, True, False]

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
        # cls.rf_brush.stop()
