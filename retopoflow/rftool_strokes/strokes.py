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

from ..rfglobals import RFGlobals
from ..rfbrushes.stroke_brush import create_stroke_brush
from ..rfoverlays.curve_overlay import create_curve_overlay
from ..rfoverlays.curve_chain_providers import LoopStripChainProvider, QuadStripChainProvider
from ..rfoperators.curve_edit import create_curve_edit_operator, create_curve_toggle_handle_type_operator

from ..rftool_base import RFTool_Base
from ..common.icons import get_path_to_blender_icon
from ..common.operator import (
    execute_operator,
    RFOperator, RFOperator_Execute, RFKeyMaps, BLKeyMaps,
    chain_rf_keymaps,
    OperatorPropertyWrapper, poll_retopoflow,
)
from ...addon_common.common.blender import event_modifier_check
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.utils import iter_pairs

from .strokes_logic import Strokes_Logic

from ..rfoperators.quickswitch import RFOperator_Relax_QuickSwitch, RFOperator_Tweak_QuickSwitch
from ..rfoperators.transform import RFOperator_Translate, sync_projection_from_blender
from ..rfoperators.maximize_watcher import RFOperator_MaximizeWatcher
from ..rfoperators.topo_rotate import RFOperator_TopoRotate

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel, draw_tweaking_popover
from ..rfpanels.rfpanel_snapping import draw_snapping_panel
from ..rfpanels.mirror_panel import draw_mirror_panel, draw_mirror_popover
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.help_panel import draw_help_panel
from ..common.interface import draw_line_separator

from ..preferences import RF_Prefs

from functools import wraps


RFBrush_Strokes, RFOperator_StrokesBrush_Adjust = create_stroke_brush(
    'strokes_brush',
    'Strokes Brush',
    radius=50,
    smoothing=0.5,
)


class RFOperator_Stroke_Insert_Keymaps:
    # used to collect redo shortcuts, which is filled in by redo_ fns below...
    # note: cannot use RFOperator_Stroke_Insert.rf_keymaps, because RFOperator_Stroke_Insert
    #       is not yet created!
    rf_keymaps : RFKeyMaps = []

class RFOperator_Stroke_Insert_Properties:
    '''
    bpy properties that are shared between insert operator and the modal operator
    used to prevent duplicate code across both operators
    '''

    extrapolate_mode: bpy.props.EnumProperty(
        name='T-Strip Extrapolation',
        description='Controls how the new perpendicular edges are extrapolated from the selected edges when inserting T Strips',
        items=[
            ('FLAT',   'Flat',   'Extrudes in a straight line', 0),
            ('FAN',    'Fan',    'Fans the extrusion to match the curve of selected geometry', 1),
            ('FOLLOW', 'Follow', 'Rotates the inserted spans to follow the curve of the stroke', 2),
        ],
        default='FLAT',
    )

    span_insert_mode: bpy.props.EnumProperty(
        name='Span Count Method',
        description='Controls the number of spans when inserting',
        items=[
            ('BRUSH',   'Brush',   'Inserts spans the size of the brush', 0),
            ('FIXED',   'Fixed',   'Inserts a fixed number of spans', 1),
            ('AVERAGE', 'Average', 'Inserts spans based on average length of selected edges. If there are no selected edges it uses the brush radius', 2),
            ('LENGTH',  'Length',  'Inserts spans sized to match a world space distance', 3),
        ],
        default='AVERAGE',
    )

    span_length: bpy.props.FloatProperty(
        name='Segment Length',
        description='World space distance for each span when Span Count Method is set to Length',
        default=0.1,
        min=0.001,
        soft_max=10.0,
        subtype='DISTANCE',
    )

    cut_count: bpy.props.IntProperty(
        name='Cut Count',
        description='Number of vertices or loops to create in a new stroke',
        default=8,
        min=1,
        soft_max=32,
        max=256,
    )

    smooth_angle: bpy.props.FloatProperty(
        name='Smooth Blending',
        description='Factor for how much smoothing is applied to the interpolated loops when creating Equals Strips and I Strips. Zero is linear.',
        default=1.0,
        min=-0.5,
        soft_min=0.0,
        soft_max=1.0,
        max=1.5,
    )

    smooth_density0: bpy.props.FloatProperty(
        name='Start Spacing',
        description='Spacing of the interpolated loops near the start of the stroke',
        default=0.5,
        min=0.0,
        max=1.0,
    )

    smooth_density1: bpy.props.FloatProperty(
        name='End Spacing',
        description='Spacing of the interpolated loops near the end of the stroke',
        default=0.5,
        min=0.0,
        max=1.0,
    )

    to_circle: bpy.props.FloatProperty(
        name='To Circle',
        description='Blend the closed loop toward a best-fit circle on the source surface. Only affects new standalone closed loops.',
        default=0.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )

    mirror_mode: bpy.props.EnumProperty(
        name='Mirror Method',
        description='Controls what should happen to stroke that crosses a mirror',
        items=[
            ('CLAMP',   'Clamp',   'Clamp stroke to mirror',          0),
            ('REFLECT', 'Reflect', 'Reflect stroke based on mirror',  1),
            ('TRIM',    'Trim',    'Trim stroke to mirror',           2),
        ],
        default='CLAMP',
    )
    mirror_correct: bpy.props.EnumProperty(
        name='Mirror Correct Side',
        description='Select how to determine correct side of mirror',
        items=[
            ('FIRST', 'Start', 'Start of stroke determines correct side of mirror', 0),
            ('LAST',  'End',   'End of stroke determines correct side of mirror',   1),
            ('MOST',  'Most',  'Side of mirror with majority of stroke is correct', 2),
        ],
        default='FIRST',
    )

class RFOperator_Stroke_Insert(
        RFOperator_Stroke_Insert_Keymaps,
        RFOperator_Stroke_Insert_Properties,
        RFOperator_Execute,
    ):
    bl_idname = 'retopoflow.strokes_insert'
    bl_label = 'Insert Stroke'
    bl_description = 'Insert edge strips and extrude edges into a patch'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    bridging_offset: bpy.props.IntProperty(
        name='Bridging Offset',
        description='Shift which edges the bridge is connected to',
        default=0,
    )

    force_nonstripL: bpy.props.BoolProperty(
        name='Force non-L-Strip',
        description='Force T-Strip or Equals-Strip to be inserted rather than L-Strip',
        default=False,
    )

    untwist_bridge: bpy.props.BoolProperty(
        name='Untwist Bridge',
        description='Swap which ends are bridged to untwist a bridge',
        default=False,
    )

    is_cycle: bpy.props.BoolProperty(
        name='Cyclic',
        description='Force stroke to be cyclic or strip',
        default=False,
    )

    logic = None

    @staticmethod
    def strokes_insert(context, radius, snap_distance, stroke3D, is_cycle, snapped_geo, snapped_mirror,
                       span_insert_mode, cut_count, span_length, extrapolate_mode, smooth_angle, smooth_density0, smooth_density1,
                       mirror_mode, mirror_correct, to_circle=0.0, radius3D=None):
        stroke3D = [pt for pt in stroke3D if pt]
        length3D = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke3D, is_cycle))
        if length3D == 0: return

        RFOperator_Stroke_Insert.logic = Strokes_Logic(
            context,
            radius,
            snap_distance,
            stroke3D,
            is_cycle,
            snapped_geo,
            snapped_mirror,
            span_insert_mode,
            cut_count,
            span_length,
            extrapolate_mode,
            smooth_angle,
            smooth_density0,
            smooth_density1,
            mirror_mode,
            mirror_correct,
            to_circle,
            radius3D,
        )
        RFOperator_Stroke_Insert.strokes_reinsert(context)

    @staticmethod
    def strokes_reinsert(context):
        logic = RFOperator_Stroke_Insert.logic

        bpy.ops.retopoflow.strokes_insert(
            'INVOKE_DEFAULT', True,
            extrapolate_mode=logic.extrapolate_mode,
            cut_count=logic.fixed_span_count or 0,
            span_length=logic.span_length,
            bridging_offset=logic.bridging_offset,
            smooth_angle=logic.smooth_angle,
            smooth_density0=logic.smooth_density0,
            smooth_density1=logic.smooth_density1,
            force_nonstripL=logic.force_nonstripL,
            untwist_bridge=logic.untwist_bridge,
            is_cycle=logic.is_cycle,
            mirror_mode=logic.mirror_mode,
            mirror_correct=logic.mirror_correct,
            to_circle=logic.to_circle,
        )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        logic = RFOperator_Stroke_Insert.logic

        if logic.show_is_cycle and logic.action:
            layout.row(heading=logic.action).prop(self, 'is_cycle', text='Cyclic')
        else:
            if logic.action:
                split = layout.split(factor=0.4)
                col = split.column()
                col.alignment='RIGHT'
                col.label(text='Inserted')
                split.label(text=logic.action)
            if logic.show_is_cycle:
                layout.row(heading='Cyclic').prop(self, 'is_cycle', text='')

        if logic.span_insert_mode == 'LENGTH':
            layout.prop(self, 'span_length', text='Length')
        elif logic.show_count:
            layout.prop(self, 'cut_count', text='Count')

        if logic.show_extrapolate_mode:
            layout.prop(self, 'extrapolate_mode')

        if logic.show_bridging_offset:
            layout.prop(self, 'bridging_offset', text='Shift')

        if logic.show_smoothness:
            layout.prop(self, 'smooth_angle', text='Smooth Blending')
            col=layout.column(align=True)
            col.prop(self, 'smooth_density0', text='Spacing Start')
            col.prop(self, 'smooth_density1', text='End')

        if logic.show_force_nonstripL:
            layout.row(heading='Force').prop(self, 'force_nonstripL', text='Non-L-Strip')

        if logic.show_untwist_bridge:
            layout.row(heading='Untwist').prop(self, 'untwist_bridge', text='Bridge')

        if logic.action in ['Loop', 'Equals-Loop']:
            layout.prop(self, 'to_circle', text='Circle')

        if logic.show_mirror_mode:
            layout.prop(self, 'mirror_mode', text='Mirror Mode')
        if logic.show_mirror_correct:
            layout.prop(self, 'mirror_correct', text='Mirror Side')

        if logic.failure_message:
            layout.separator()
            row = layout.row()
            row.use_property_split = False
            row.label(text=logic.failure_message, icon='WARNING_LARGE')

    def execute(self, context):
        """
        NOTE: execute should not be called directly!
              call via strokes_insert or strokes_reinsert
        """

        logic = RFOperator_Stroke_Insert.logic

        logic.extrapolate_mode = self.extrapolate_mode
        logic.fixed_span_count = self.cut_count
        logic.span_length      = self.span_length
        logic.bridging_offset  = self.bridging_offset
        logic.smooth_angle     = self.smooth_angle
        logic.smooth_density0  = self.smooth_density0
        logic.smooth_density1  = self.smooth_density1
        logic.force_nonstripL  = self.force_nonstripL
        logic.untwist_bridge   = self.untwist_bridge
        logic.is_cycle         = self.is_cycle
        logic.mirror_mode      = self.mirror_mode
        logic.mirror_correct   = self.mirror_correct
        logic.to_circle        = self.to_circle

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
        self.untwist_bridge   = logic.untwist_bridge
        self.is_cycle         = logic.is_cycle
        self.mirror_mode      = logic.mirror_mode
        self.mirror_correct   = logic.mirror_correct
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
        logic.fixed_span_count -= 1

    @create_redo_operator('strokes_insert_spans_increased', 'Reinsert stroke with increased spans', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'ctrl': 1})
    def increase_spans(context, logic):
        if logic.cut_count is None: return
        logic.fixed_span_count += 1

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


class RFOperator_Strokes(RFOperator_Stroke_Insert_Properties, RFOperator):
    bl_idname = 'retopoflow.strokes'
    bl_label = 'Strokes'
    bl_description = 'Insert edge strips and extrude edges into a patch'
    # bl_space_type = 'VIEW_3D'
    # bl_region_type = 'TOOLS'
    bl_options = set()

    loop_select_op = 'mesh.select_edge_loop_multi' if bpy.app.version >= (5, 1, 0) else 'mesh.loop_multi_select'

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),

        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK', 'ctrl': True}, # prevents object selection with Ctrl+LMB Click
            {'km_context': ('init', 'ready'), 'km_label': 'Insert Stroke', 'km_status_event_value': 'CLICK_DRAG'}
        ),
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK', 'ctrl': True}, None),

        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, {'km_context': 'insert', 'km_label': 'Draw Stroke'}),

        (loop_select_op, {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, {'km_context': 'init', 'km_label': 'Select Strip'}),
    ]

    rf_status = {
        'ready': ('LMB: Insert', ),
        'insert': ('RMB: Cancel', )
    }

    brush_radius: OperatorPropertyWrapper.int(
        RFBrush_Strokes, 'stroke_radius',
        name='Radius',
        description='Radius of the brush in Blender UI units before it gets projected onto the mesh',
        min=1,
        max=1000,
        subtype='PIXEL',
        default=50,
    )
    snap_radius: OperatorPropertyWrapper.int(
        RFBrush_Strokes, 'snap_distance',
        name='Snap',
        description='Distance for brush to snap to existing geometry',
        min=5,
        max=100,
        subtype='PIXEL',
        default=12,
    )
    stroke_smoothing: bpy.props.FloatProperty(
        name='Stroke Smoothing',
        description='Stroke smoothing factor.  Zero means no smoothing, and higher means more smoothing.',
        get=lambda _: RFBrush_Strokes.get_stroke_smooth(),
        set=lambda _,v: RFBrush_Strokes.set_stroke_smooth(v),
        min=0.00,
        max=1.0,
        default=0.5,
    )
    select_loops: bpy.props.BoolProperty(
        name = 'Tweak Loops',
        description = 'Select and transform loops while tweaking edges with the mouse',
        default = False
    )
    # show_curve_handles/curve_handle_density/curve_corner_angle moved to
    # context.scene.retopoflow.curve_handles (rfprops_curve_handles.py) --
    # shared scene-level settings, not per-tool operator properties, so
    # PolyStrips' curve overlay agrees with Strokes' without needing its own
    # copies of the same three props (see RFTool_Base.rf_supports_curve_handles)

    def init(self, context, event):
        self.km_context = 'ready'
        RFTool_Strokes.rf_brush.set_operator(self)
        RFTool_Strokes.rf_brush.reset_nearest(context)
        self.tickle(context)

    def finish(self, context):
        self.set_statusbar_override(None)
        self.km_context = 'init'
        RFTool_Strokes.rf_brush.set_operator(None)
        RFTool_Strokes.rf_brush.reset_nearest(context)

    def reset(self):
        RFTool_Strokes.rf_brush.reset()

    def process_stroke(self, context, radius, snap_distance, stroke2D, stroke3D, is_cycle, snapped_geo, snapped_mirror, radius3D=None):
        RFOperator_Stroke_Insert.strokes_insert(
            context,
            radius,
            snap_distance,
            stroke3D,
            is_cycle,
            snapped_geo,
            snapped_mirror,
            self.span_insert_mode,
            self.cut_count,
            self.span_length,
            self.extrapolate_mode,
            self.smooth_angle,
            self.smooth_density0,
            self.smooth_density1,
            self.mirror_mode,
            self.mirror_correct,
            self.to_circle,
            radius3D,
        )

    def update(self, context, event):
        RFCore = RFGlobals.RFCore_None
        if not RFCore: return {'CANCELLED'}

        if event.value in {'CLICK', 'DOUBLE_CLICK'} and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
            # prevents object selection with Ctrl+LMB Click
            return {'RUNNING_MODAL'}

        if RFTool_Strokes.rf_brush.is_stroking():
            # hide curve handles while a stroke is being drawn
            RFTool_Strokes.rf_overlay.pause_overlay()
            self.set_statusbar_override(self.rf_status['insert'])
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE'}:
                RFCore.handle_update(context, event)
                return {'RUNNING_MODAL'}
        else:
            RFTool_Strokes.rf_overlay.unpause_overlay()
            self.set_statusbar_override(None)
            if not event.ctrl:
                Cursors.restore()
                self.tickle(context)
                return {'FINISHED'}

        Cursors.set('CROSSHAIR')
        return {'PASS_THROUGH'}  # TODO: see below
        # TODO: allow only some operators to work but not all
        #       however, need a way to not hardcode LEFTMOUSE!
        return {'PASS_THROUGH'} if event.type in {'MOUSEMOVE', 'LEFTMOUSE'} else {'RUNNING_MODAL'}


RFOperator_Strokes_Overlay = create_curve_overlay(
    'RFOperator_Strokes_Selection_Overlay',
    'retopoflow.strokes',  # must match RFTool_base.bl_idname
    'strokes_overlay',
    'Strokes Selected Overlay',
    # faces win: a selection containing quad strips shows only strip curves;
    # loop curves only appear when the selection is edges-only. Same list,
    # same order as PolyStrips -- one selection-driven system regardless of
    # which tool is active.
    [QuadStripChainProvider(), LoopStripChainProvider(only_boundary=True)],
)

RFOperator_Strokes_CurveEdit = create_curve_edit_operator(
    'RFOperator_Strokes_CurveEdit',
    'strokes_curve_edit',
    'Edit Stroke Curve',
    'Drag curve control handles to reshape a selected strip or loop',
    get_overlay=lambda: RFTool_Strokes.rf_overlay,
)

RFOperator_Strokes_ToggleHandleType = create_curve_toggle_handle_type_operator(
    'strokes_toggle_handle_type',
    'Toggle Curve Handle Type',
    'Cycle the hovered curve control point between Aligned, Vector, and Automatic',
    get_overlay=lambda: RFTool_Strokes.rf_overlay,
)

@execute_operator('switch_to_strokes', 'RetopoFlow: Switch to Strokes', fn_poll=poll_retopoflow)
def switch_rftool(context):
    RFTool_Strokes.activate_tool(context)



class RFTool_Strokes(RFTool_Base):
    bl_idname = "retopoflow.strokes"
    bl_label = "Strokes"
    bl_description = "Insert edge strips and extrude edges into a patch"
    bl_icon = get_path_to_blender_icon('strokes')
    bl_widget = None
    rf_operator_idname : str | None = 'retopoflow.strokes'
    rf_supports_curve_handles = True

    rf_brush = RFBrush_Strokes()
    rf_overlay = RFOperator_Strokes_Overlay

    props = None  # needed to reset properties

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_Strokes,
        RFOperator_Stroke_Insert,
        RFOperator_Strokes_CurveEdit,
        RFOperator_Strokes_ToggleHandleType,
        RFOperator_StrokesBrush_Adjust,
        RFOperator_MaximizeWatcher,
        RFOperator_Translate,
        RFOperator_Relax_QuickSwitch,
        RFOperator_Tweak_QuickSwitch,
        RFOperator_TopoRotate,
    )

    def draw_settings(context, layout, tool):
        prefs = RF_Prefs.get_prefs(context)
        props_strokes = tool.operator_properties(RFOperator_Strokes.bl_idname)
        RFTool_Strokes.props = props_strokes

        if context.region.type == 'TOOL_HEADER':
            # layout.label(text="Insert:")
            row = layout.row(align=True)
            row.prop(props_strokes, 'span_insert_mode', text='')
            if props_strokes.span_insert_mode == 'FIXED':
                row.prop(props_strokes, 'cut_count', text="")
            elif props_strokes.span_insert_mode == 'LENGTH':
                row.prop(props_strokes, 'span_length', text="")
            else:
                row.prop(props_strokes, 'brush_radius', text="")
            layout.prop(props_strokes, 'smooth_angle', text='Blending', slider=True)
            row = layout.row(heading='Extrusions:', align=False)
            row.prop(props_strokes, 'extrapolate_mode', expand=True)
            row.popover('RF_PT_StrokeOptions', text='', icon='STROKE')

            draw_line_separator(layout)

            draw_tweaking_popover(context, layout, props_strokes)
            layout.popover('RF_PT_Snapping', text='Snapping')
            row = layout.row(align=True)
            row.popover('RF_PT_MeshCleanup', text='Clean Up')
            row.operator("retopoflow.meshcleanup", text='', icon='PLAY').affect_all=False
            draw_mirror_popover(context, layout)
            if prefs.expand_offset:
                layout.prop(context.scene.retopoflow, 'retopo_offset', text='Overlay Offset')
            layout.popover('RF_PT_General', text='', icon='OPTIONS')
            layout.popover('RF_PT_Help', text='', icon='INFO_LARGE' if bpy.app.version >= (4,3,0) else 'INFO')

        else:
            header, panel = layout.panel(idname='strokes_spans_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                panel.prop(props_strokes, 'span_insert_mode', text='Method')
                if props_strokes.span_insert_mode == 'FIXED':
                    panel.prop(props_strokes, 'cut_count', text="Count")
                elif props_strokes.span_insert_mode == 'LENGTH':
                    panel.prop(props_strokes, 'span_length', text="Length")
                else:
                    panel.prop(props_strokes, 'brush_radius', text="Radius")
                panel.prop(props_strokes, 'snap_radius', text="Snap")
                panel.prop(props_strokes, 'stroke_smoothing', text='Stabilize', slider=True)
                col = panel.column(align=True)
                col.prop(props_strokes, 'smooth_density0', text='Spacing Start', slider=True)
                col.prop(props_strokes, 'smooth_density1', text='End', slider=True)
                panel.prop(props_strokes, 'smooth_angle', text='Blending', slider=True)
                panel.prop(props_strokes, 'extrapolate_mode', text='Extrusions')
            draw_tweaking_panel(context, layout)
            draw_snapping_panel(context, layout, idname='strokes_snapping_panel')
            draw_cleanup_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context):
        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter('Strokes')
        if not prefs.setup_snapping:
            context.scene.retopoflow.snapping.projection = 'FOLLOW_BLENDER'
        else:
            sync_projection_from_blender(context)
        if prefs.setup_automerge:
            cls.resetter['context.tool_settings.use_mesh_automerge'] = True
        if context.scene.retopoflow.snapping.projection != 'FOLLOW_BLENDER':
            cls.resetter.store('context.tool_settings.snap_elements_base')
            snap_elem = 'FACE_PROJECT' if context.scene.retopoflow.snapping.projection == 'SCREEN_SPACE' else 'FACE_NEAREST'
            cls.resetter['context.tool_settings.snap_elements_individual'] = {snap_elem}
        if prefs.setup_selection_mode:
            cls.resetter['context.tool_settings.mesh_select_mode'] = [True, True, False]

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
        cls.rf_brush.stop()
