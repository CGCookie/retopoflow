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
    wrap_property, poll_retopoflow,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender import event_modifier_check
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import clamp
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.utils import iter_pairs

from .strokes_logic import Strokes_Logic

from ..rfoperators.quickswitch import RFOperator_Relax_QuickSwitch, RFOperator_Tweak_QuickSwitch
from ..rfoperators.transform import RFOperator_Translate
from ..rfoperators.launch_browser import RFOperator_Launch_Help, RFOperator_Launch_NewIssue

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel
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
    rf_keymaps = []

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
            ('BRUSH',   'Brush Radius', 'Inserts spans the size of the brush', 0),
            ('FIXED',   'Fixed',        'Inserts a fixed number of spans',     1),
            ('AVERAGE', 'Average',      'Inserts spans based on average length of selected edges. If there are no selected edges it uses the brush radius', 2),
        ],
        default='AVERAGE',
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
    def strokes_insert(context, radius, snap_distance, stroke3D, is_cycle, snapped_geo, snapped_mirror, span_insert_mode, cut_count, extrapolate_mode, smooth_angle, smooth_density0, smooth_density1, mirror_mode, mirror_correct):
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
            extrapolate_mode,
            smooth_angle,
            smooth_density0,
            smooth_density1,
            mirror_mode,
            mirror_correct,
        )
        RFOperator_Stroke_Insert.strokes_reinsert(context)

    @staticmethod
    def strokes_reinsert(context):
        logic = RFOperator_Stroke_Insert.logic

        bpy.ops.retopoflow.strokes_insert(
            'INVOKE_DEFAULT', True,
            extrapolate_mode=logic.extrapolate_mode,
            cut_count=logic.fixed_span_count or 0,
            bridging_offset=logic.bridging_offset,
            smooth_angle=logic.smooth_angle,
            smooth_density0=logic.smooth_density0,
            smooth_density1=logic.smooth_density1,
            force_nonstripL=logic.force_nonstripL,
            untwist_bridge=logic.untwist_bridge,
            is_cycle=logic.is_cycle,
            mirror_mode=logic.mirror_mode,
            mirror_correct=logic.mirror_correct,
        )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        logic = RFOperator_Stroke_Insert.logic

        if logic.show_action:
            split = layout.split(factor=0.4)
            col = split.column()
            col.alignment='RIGHT'
            col.label(text='Inserted')
            split.label(text=logic.show_action)

        if logic.failure_message:
            layout.label(text=logic.failure_message, icon='WARNING_LARGE')

        if logic.show_count:
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

        if logic.show_is_cycle:
            layout.row(heading='Cyclic').prop(self, 'is_cycle', text='')

        if logic.show_force_nonstripL:
            layout.row(heading='Force').prop(self, 'force_nonstripL', text='Non-L-Strip')

        if logic.show_untwist_bridge:
            layout.row(heading='Untwist').prop(self, 'untwist_bridge', text='Bridge')

        if logic.show_mirror_mode:
            layout.prop(self, 'mirror_mode', text='Mirror Mode')
        if logic.show_mirror_correct:
            layout.prop(self, 'mirror_correct', text='Mirror Side')

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
        logic.untwist_bridge   = self.untwist_bridge
        logic.is_cycle         = self.is_cycle
        logic.mirror_mode      = self.mirror_mode
        logic.mirror_correct   = self.mirror_correct

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

    brush_radius: wrap_property(
        RFBrush_Strokes, 'stroke_radius', 'int',
        name='Radius',
        description='Radius of the brush in Blender UI units before it gets projected onto the mesh',
        min=1,
        max=1000,
        subtype='PIXEL',
        default=50,
    )
    snap_radius: wrap_property(
        RFBrush_Strokes, 'snap_distance', 'int',
        name='Snap',
        description='Distance for brush to snap to existing geometry',
        min=5,
        max=100,
        subtype='PIXEL',
        default=10,
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

    def init(self, context, event):
        RFTool_Strokes.rf_brush.set_operator(self)
        RFTool_Strokes.rf_brush.reset_nearest(context)
        self.tickle(context)

    def finish(self, context):
        RFTool_Strokes.rf_brush.set_operator(None)
        RFTool_Strokes.rf_brush.reset_nearest(context)

    def reset(self):
        RFTool_Strokes.rf_brush.reset()

    def process_stroke(self, context, radius, snap_distance, stroke2D, stroke3D, is_cycle, snapped_geo, snapped_mirror):
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
            self.extrapolate_mode,
            self.smooth_angle,
            self.smooth_density0,
            self.smooth_density1,
            self.mirror_mode,
            self.mirror_correct,
        )

    def update(self, context, event):
        if event.value in {'CLICK', 'DOUBLE_CLICK'} and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
            # prevents object selection with Ctrl+LMB Click
            return {'RUNNING_MODAL'}

        if RFTool_Strokes.rf_brush.is_stroking():
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE'}:
                self.RFCore.handle_update(context, event)
                return {'RUNNING_MODAL'}
        else:
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

@execute_operator('switch_to_strokes', 'RetopoFlow: Switch to Strokes', fn_poll=poll_retopoflow)
def switch_rftool(context):
    import bl_ui
    bl_ui.space_toolsystem_common.activate_by_id(context, 'VIEW_3D', 'retopoflow.strokes')  # matches bl_idname of RFTool_Base below



class RFTool_Strokes(RFTool_Base):
    bl_idname = "retopoflow.strokes"
    bl_label = "Strokes"
    bl_description = "Insert edge strips and extrude edges into a patch"
    bl_icon = get_path_to_blender_icon('strokes')
    bl_widget = None
    bl_operator = 'retopoflow.strokes'

    rf_brush = RFBrush_Strokes()
    rf_overlay = RFOperator_Strokes_Overlay

    props = None  # needed to reset properties

    bl_keymap = chain_rf_keymaps(
        RFOperator_Strokes,
        RFOperator_Stroke_Insert,
        RFOperator_StrokesBrush_Adjust,
        RFOperator_Translate,
        RFOperator_Relax_QuickSwitch,
        RFOperator_Tweak_QuickSwitch,
        RFOperator_Launch_Help,
        RFOperator_Launch_NewIssue,
    )

    def draw_settings(context, layout, tool):
        props_strokes = tool.operator_properties(RFOperator_Strokes.bl_idname)
        RFTool_Strokes.props = props_strokes

        if context.region.type == 'TOOL_HEADER':
            layout.label(text="Insert:")
            row = layout.row(align=True)
            row.prop(props_strokes, 'span_insert_mode', text='')
            if props_strokes.span_insert_mode == 'FIXED':
                row.prop(props_strokes, 'cut_count', text="")
            else:
                row.prop(props_strokes, 'brush_radius', text="")
            # layout.label(text="Smooth Blending:")
            layout.prop(props_strokes, 'stroke_smoothing', text='Stabilize', slider=True)
            layout.prop(props_strokes, 'smooth_angle', text='Blending', slider=True)
            # layout.label(text="Spacing:")
            # row = layout.row(align=True)
            # row.prop(props_strokes, 'smooth_density0', text='', slider=True)
            # row.prop(props_strokes, 'smooth_density1', text='', slider=True)
            row = layout.row(heading='T-Strips:', align=False)
            row.prop(props_strokes, 'extrapolate_mode', expand=True)

            draw_line_separator(layout)
            layout.popover('RF_PT_TweakCommon')
            row = layout.row(align=True)
            row.popover('RF_PT_MeshCleanup', text='Clean Up')
            row.operator("retopoflow.meshcleanup", text='', icon='PLAY').affect_all=False
            draw_mirror_popover(context, layout)
            layout.popover('RF_PT_General', text='', icon='OPTIONS')
            layout.popover('RF_PT_Help', text='', icon='INFO_LARGE' if bpy.app.version >= (4,3,0) else 'INFO')

        else:
            header, panel = layout.panel(idname='strokes_spans_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                panel.prop(props_strokes, 'span_insert_mode', text='Method')
                if props_strokes.span_insert_mode == 'FIXED':
                    panel.prop(props_strokes, 'cut_count', text="Count")
                else:
                    panel.prop(props_strokes, 'brush_radius', text="Radius")
                panel.prop(props_strokes, 'snap_radius', text="Snap")
                panel.prop(props_strokes, 'stroke_smoothing', text='Stabilize', slider=True)
                panel.prop(props_strokes, 'smooth_angle', text='Blending', slider=True)
                col = panel.column(align=True)
                col.prop(props_strokes, 'smooth_density0', text='Spacing Start', slider=True)
                col.prop(props_strokes, 'smooth_density1', text='End', slider=True)
                panel.label(text='T-Strips')
                panel.prop(props_strokes, 'extrapolate_mode', text='Extrapolation')
                panel.label(text='Mirror')
                panel.prop(props_strokes, 'mirror_mode', text='Mode')
                panel.prop(props_strokes, 'mirror_correct', text='Side')
            draw_tweaking_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_cleanup_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context):
        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter('Strokes')
        if prefs.setup_automerge:
            cls.resetter['context.tool_settings.use_mesh_automerge'] = True
        if prefs.setup_snapping:
            cls.resetter.store('context.tool_settings.snap_elements_base')
            cls.resetter['context.tool_settings.snap_elements_individual'] = {'FACE_NEAREST'}
        if prefs.setup_selection_mode:
            cls.resetter['context.tool_settings.mesh_select_mode'] = [True, True, False]

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
