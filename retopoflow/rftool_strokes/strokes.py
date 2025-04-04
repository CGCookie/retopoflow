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
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d

from ..rfbrushes.stroke_brush import create_stroke_brush
from ..rfoverlays.loopstrip_selection_overlay import create_loopstrip_selection_overlay

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, bme_midpoint, get_boundary_strips_cycles
from ..common.drawing import Drawing
from ..common.icons import get_path_to_blender_icon
from ..common.raycast import raycast_point_valid_sources
from ..common.operator import (
    execute_operator,
    RFOperator, RFOperator_Execute,
    chain_rf_keymaps,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender import event_modifier_check
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import clamp
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.utils import iter_pairs

from .strokes_logic import Strokes_Logic

from ..rfoperators.transform import RFOperator_Translate_ScreenSpace

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel
from ..rfpanels.general_panel import draw_general_panel
from ..common.interface import draw_line_separator

from functools import wraps


RFBrush_Strokes, RFOperator_StrokesBrush_Adjust = create_stroke_brush(
    'strokes_brush',
    'Strokes Brush',
    radius=40,
)


class RFOperator_Stroke_Insert_Keymaps:
    # used to collect redo shortcuts, which is filled in by redo_ fns below...
    # note: cannot use RFOperator_Stroke_Insert.rf_keymaps, because RFOperator_Stroke_Insert
    #       is not yet created!
    rf_keymaps = []

class RFOperator_Stroke_Insert(RFOperator_Stroke_Insert_Keymaps, RFOperator_Execute):
    bl_idname = 'retopoflow.strokes_insert'
    bl_label = 'Insert Stroke'
    bl_description = 'Insert edge strips and extrude edges into a patch'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    extrapolate_mode: bpy.props.EnumProperty(
        name='Extrapolation',
        description='Controls how the new perpendicular edges are extrapolated from the selected edges',
        items=[
            ('FLAT',  'Flat',  'Extrudes in a straight line', 0),
            ('ADAPT', 'Adapt', 'Fans the extrusion to match the original curvature', 1),
        ],
        default='FLAT',
    )

    cut_count: bpy.props.IntProperty(
        name='Count',
        description='Number of vertices or loops to create in a new stroke',
        default=8,
        min=1,
        soft_max=32,
        max=256,
    )

    bridging_offset: bpy.props.IntProperty(
        name='Bridging Offset',
        description='Shift which edges the bridge is connected to',
        default=0,
    )

    smooth_angle: bpy.props.FloatProperty(
        name='Smoothing',
        description='Factor for how much smoothing is applied to the interpolated loops. Zero is linear.',
        default=1.0,
        min=-0.5,
        soft_min=0.0,
        soft_max=1.0,
        max=1.5,
    )

    smooth_density0: bpy.props.FloatProperty(
        name='Spacing Start',
        description='Spacing of the interpolated loops near the start of the stroke',
        default=0.5,
        min=0.0,
        max=1.0,
    )
    smooth_density1: bpy.props.FloatProperty(
        name='Spacing End',
        description='Spacing of the interpolated loops near the end of the stroke',
        default=0.5,
        min=0.0,
        max=1.0,
    )
    force_nonstripL: bpy.props.BoolProperty(
        name='Force non-L-Strip',
        description='Force T-Strip or Equals-Strip to be inserted rather than L-Strip',
        default=False,
    )

    logic = None

    @staticmethod
    def strokes_insert(context, radius, stroke3D, is_cycle, span_insert_mode, initial_cut_count, initial_extrapolate_mode, initial_smooth_angle, initial_smooth_density0, initial_smooth_density1):
        stroke3D = [pt for pt in stroke3D if pt]
        length3D = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke3D, is_cycle))
        if length3D == 0: return

        RFOperator_Stroke_Insert.logic = Strokes_Logic(
            context,
            radius,
            stroke3D,
            is_cycle,
            span_insert_mode,
            initial_cut_count,
            initial_extrapolate_mode,
            initial_smooth_angle,
            initial_smooth_density0,
            initial_smooth_density1,
        )
        RFOperator_Stroke_Insert.strokes_reinsert(context)

    @staticmethod
    def strokes_reinsert(context):
        logic = RFOperator_Stroke_Insert.logic

        bpy.ops.retopoflow.strokes_insert(
            'INVOKE_DEFAULT', True,
            extrapolate_mode=logic.extrapolate_mode,
            cut_count=logic.cut_count or 0,
            bridging_offset=logic.bridging_offset,
            smooth_angle=logic.smooth_angle,
            smooth_density0=logic.smooth_density0,
            smooth_density1=logic.smooth_density1,
            force_nonstripL=logic.force_nonstripL,
        )

    def draw(self, context):
        layout = self.layout
        grid = layout.grid_flow(row_major=True, columns=2)
        logic = RFOperator_Stroke_Insert.logic

        if logic.show_action:
            grid.label(text=f'Inserted')
            grid.label(text=logic.show_action)

        if logic.show_count:
            grid.label(text='Count')
            grid.prop(self, 'cut_count', text='')

        if logic.show_extrapolate_mode:
            grid.label(text='Extrapolation')
            grid.prop(self, 'extrapolate_mode', text='')

        if logic.show_bridging_offset:
            grid.label(text='Shift')
            grid.prop(self, 'bridging_offset', text='')

        if logic.show_smoothness:
            grid.label(text='Smoothing')
            grid.prop(self, 'smooth_angle', text='')

            grid.label(text='Spacing')
            row = grid.row(align=True)
            row.prop(self, 'smooth_density0', text='')
            row.prop(self, 'smooth_density1', text='')

        if logic.show_force_nonstripL:
            grid.label(text='Force non-L-Strip')
            grid.prop(self, 'force_nonstripL', text='')

    def execute(self, context):
        """
        NOTE: execute should not be called directly!
              call via strokes_insert or strokes_reinsert
        """

        logic = RFOperator_Stroke_Insert.logic

        logic.extrapolate_mode = self.extrapolate_mode
        logic.fixed_span_count = self.cut_count
        logic.bridging_offset  = self.bridging_offset
        logic.smooth_angle     = self.smooth_angle
        logic.smooth_density0  = self.smooth_density0
        logic.smooth_density1  = self.smooth_density1
        logic.force_nonstripL  = self.force_nonstripL

        try:
            logic.update(context)
        except Exception as e:
            # TODO: revisit how this issue (#1376) is handled.
            #       right now, the operator is simply cancelled, which could leave mesh in a weird state or remove
            #       recently added stroke!
            print(f'{type(self).__name__}.execute: Caught Exception {e}')
            debugger.print_exception()
            return {'CANCELLED'}

        self.extrapolate_mode = logic.extrapolate_mode
        self.bridging_offset  = logic.bridging_offset
        self.smooth_angle     = logic.smooth_angle
        self.smooth_density0  = logic.smooth_density0
        self.smooth_density1  = logic.smooth_density1
        self.force_nonstripL  = logic.force_nonstripL
        if logic.show_count: self.cut_count = logic.fixed_span_count

        return {'FINISHED'}

    @staticmethod
    def create_redo_operator(idname, description, keymap):
        # add keymap to RFOperator_Stroke_Insert.rf_keymaps
        # note: still creating RFOperator_Stroke_Insert, so using RFOperator_Stroke_Insert_Keymaps.rf_keymaps
        RFOperator_Stroke_Insert_Keymaps.rf_keymaps.append( (f'retopoflow.{idname}', keymap, None) )
        def wrapper(fn_action):
            @execute_operator(idname, description, options={'INTERNAL'})
            @wraps(fn_action)
            def wrapped(context):
                last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
                if last_op != RFOperator_Stroke_Insert.bl_label: return
                fn_action(context, RFOperator_Stroke_Insert.logic)
                bpy.ops.ed.undo()
                RFOperator_Stroke_Insert.strokes_reinsert(context)
            return wrapped
        return wrapper

    @create_redo_operator('strokes_insert_spans_decreased', 'Reinsert stroke with decreased spans', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1})
    def decrease_spans(context, logic):
        if logic.cut_count is None: return
        logic.cut_count -= 1

    @create_redo_operator('strokes_insert_spans_increased', 'Reinsert stroke with increased spans', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'ctrl': 1})
    def increase_spans(context, logic):
        if logic.cut_count is None: return
        logic.cut_count += 1

    @create_redo_operator('strokes_insert_shift_decreased', 'Reinsert stroke with shifted spans', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'alt': 1})
    def decrease_shift(context, logic):
        logic.bridging_offset -= 1

    @create_redo_operator('strokes_insert_shift_increased', 'Reinsert stroke with shifted spans', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'alt': 1})
    def increase_shift(context, logic):
        logic.bridging_offset += 1

    @create_redo_operator('strokes_insert_smooth_angle_decreased', 'Reinsert stroke with less smoothed angles', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'shift': 1})
    def decrease_smooth_angle(context, logic):
        logic.smooth_angle -= 0.25

    @create_redo_operator('strokes_insert_smooth_angle_increased', 'Reinsert stroke with more smoothed angles', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'shift': 1})
    def increase_smooth_angle(context, logic):
        logic.smooth_angle += 0.25


class RFOperator_Strokes(RFOperator):
    bl_idname = 'retopoflow.strokes'
    bl_label = 'Strokes'
    bl_description = 'Insert edge strips and extrude edges into a patch'
    # bl_space_type = 'VIEW_3D'
    # bl_region_type = 'TOOLS'
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),

        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK',        'ctrl': True}, None),  # prevents object selection with Ctrl+LMB Click
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK', 'ctrl': True}, None),

        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, None),

        ('mesh.loop_multi_select', {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, None),
    ]

    rf_status = ['LMB: Insert']


    span_insert_mode: bpy.props.EnumProperty(
        name='Span Count Method',
        description='Controls the number of spans when inserting',
        items=[
            ('BRUSH',   'Brush Size', 'Insert spans based on brush size', 0),
            ('FIXED',   'Fixed',      'Insert fixed number of spans',     1),
            ('AVERAGE', 'Average',    'Insert spans based on average length of selected edges (fallback: brush size)', 2),
        ],
        default='AVERAGE',
    )

    initial_cut_count: bpy.props.IntProperty(
        name='Initial Count',
        description='Number of vertices or loops to create in a new stroke',
        default=8,
        min=1,
        max=100,
    )

    extrapolate_mode: bpy.props.EnumProperty(
        name='Extrapolation',
        description='Controls how the new perpendicular edges are extrapolated from the selected edges when inserting T Strips',
        items=[
            ('FLAT',  'Flat',  'Extrudes in a straight line', 0),
            ('ADAPT', 'Adapt', 'Fans the extrusion to match the original curvature', 1),
        ],
        default='FLAT',
    )

    initial_smooth_angle: bpy.props.FloatProperty(
        name='Initial Smoothing',
        description='Factor for how much smoothing is applied to the interpolated loops when creating Equals Strips and I Strips. Zero is linear.',
        default=1.0,
        min=-0.5,
        soft_min=0.0,
        soft_max=1.0,
        max=1.5,
    )

    initial_smooth_density0: bpy.props.FloatProperty(
        name='Initial Start Spacing',
        description='Initial spacing of the interpolated loops near the start of the stroke',
        default=0.5,
        min=0.0,
        max=1.0,
    )

    initial_smooth_density1: bpy.props.FloatProperty(
        name='Initial End Spacing',
        description='Initial spacing of the interpolated loops near the end of the stroke',
        default=0.5,
        min=0.0,
        max=1.0,
    )


    def init(self, context, event):
        RFTool_Strokes.rf_brush.set_operator(self)
        RFTool_Strokes.rf_brush.reset_nearest(context)
        self.tickle(context)

    def finish(self, context):
        RFTool_Strokes.rf_brush.set_operator(None)
        RFTool_Strokes.rf_brush.reset_nearest(context)

    def reset(self):
        RFTool_Strokes.rf_brush.reset()

    def process_stroke(self, context, radius, stroke2D, is_cycle, snapped_geo):
        snap_bmv0, snap_bmv1 = snapped_geo[0]
        stroke3D = [raycast_point_valid_sources(context, pt, world=False) for pt in stroke2D]
        RFOperator_Stroke_Insert.strokes_insert(
            context,
            radius,
            stroke3D,
            is_cycle,
            self.span_insert_mode,
            self.initial_cut_count,
            self.extrapolate_mode,
            self.initial_smooth_angle,
            self.initial_smooth_density0,
            self.initial_smooth_density1,
        )

    def update(self, context, event):
        if event.value in {'CLICK', 'DOUBLE_CLICK'} and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
            # prevents object selection with Ctrl+LMB Click
            return {'RUNNING_MODAL'}

        if not RFTool_Strokes.rf_brush.is_stroking():
            if not event.ctrl:
                Cursors.restore()
                self.tickle(context)
                return {'FINISHED'}

        Cursors.set('CROSSHAIR')
        return {'PASS_THROUGH'}  # TODO: see below
        # TODO: allow only some operators to work but not all
        #       however, need a way to not hardcode LEFTMOUSE!
        return {'PASS_THROUGH'} if event.type in {'MOUSEMOVE', 'LEFTMOUSE'} else {'RUNNING_MODAL'}


RFOperator_Strokes_Overlay = create_loopstrip_selection_overlay(
    'RFOperator_Strokes_Selection_Overlay',
    'retopoflow.strokes',  # must match RFTool_base.bl_idname
    'strokes_overlay',
    'Strokes Selected Overlay',
    True,
)



class RFTool_Strokes(RFTool_Base):
    bl_idname = "retopoflow.strokes"
    bl_label = "Strokes"
    bl_description = "Insert edge strips and extrude edges into a patch"
    bl_icon = get_path_to_blender_icon('strokes')
    bl_widget = None
    bl_operator = 'retopoflow.strokes'

    rf_brush = RFBrush_Strokes()
    rf_overlay = RFOperator_Strokes_Overlay

    bl_keymap = chain_rf_keymaps(
        RFOperator_Strokes,
        RFOperator_Stroke_Insert,
        RFOperator_StrokesBrush_Adjust,
        RFOperator_Translate_ScreenSpace,
    )

    def draw_settings(context, layout, tool):
        props_strokes = tool.operator_properties(RFOperator_Strokes.bl_idname)
        props_translate = tool.operator_properties(RFOperator_Translate_ScreenSpace.bl_idname)

        if context.region.type == 'TOOL_HEADER':
            layout.label(text="Insert:")
            row = layout.row(align=True)
            row.prop(props_strokes, 'span_insert_mode', text='')
            if props_strokes.span_insert_mode == 'FIXED':
                row.prop(props_strokes, 'initial_cut_count', text="")
            layout.prop(props_strokes, 'extrapolate_mode', expand=True)
            #layout.label(text="Smoothing:")
            layout.prop(props_strokes, 'initial_smooth_angle', text='Smoothing')
            #layout.label(text="Spacing:")
            row = layout.row(align=True)
            row.prop(props_strokes, 'initial_smooth_density0', text='Spacing')
            row.prop(props_strokes, 'initial_smooth_density1', text='')
            draw_line_separator(layout)
            layout.popover('RF_PT_TweakCommon')
            row = layout.row(align=True)
            row.popover('RF_PT_MeshCleanup', text='Clean Up')
            row.operator("retopoflow.meshcleanup", text='', icon='PLAY').affect_all=False
            layout.popover('RF_PT_General', text='', icon='OPTIONS')
        else:
            header, panel = layout.panel(idname='strokes_spans_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                panel.prop(props_strokes, 'span_insert_mode', text='Count')
                if props_strokes.span_insert_mode == 'FIXED':
                    panel.prop(props_strokes, 'initial_cut_count', text=" ")
                row = panel.row()
                row.prop(props_strokes, 'extrapolate_mode', text='Extrapolation', expand=True)
                panel.prop(props_strokes, 'initial_smooth_angle', text='Smoothing')
                col = panel.column(align=True)
                col.prop(props_strokes, 'initial_smooth_density0', text='Spacing Start')
                col.prop(props_strokes, 'initial_smooth_density1', text='End')
            draw_tweaking_panel(context, layout)
            draw_cleanup_panel(context, layout)
            draw_general_panel(context, layout)

    @classmethod
    def activate(cls, context):
        cls.resetter = Resetter('Strokes')
        cls.resetter['context.tool_settings.use_mesh_automerge'] = True
        cls.resetter['context.tool_settings.mesh_select_mode'] = [True, True, False]
        cls.resetter.store('context.tool_settings.snap_elements_base')
        cls.resetter['context.tool_settings.snap_elements_individual'] = {'FACE_PROJECT'}

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
