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
import bmesh
import heapq
import math
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d

from ..rfglobals import RFGlobals
from ..rfbrushes.stroke_brush import create_stroke_brush
from ..rfoverlays.stroke_curve_overlay import create_loopstrip_curve_overlay, shrink_segment, KNOT_RADIUS, TANGENT_RADIUS, FREE_KNOT_BORDER_COLOR

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, bme_midpoint, get_boundary_strips_cycles
from ..common.drawing import Drawing
from ..common.icons import get_path_to_blender_icon
from ..common.maths import view_forward_direction, view_right_direction, xform_direction, proportional_edit
from ..common.raycast import raycast_point_valid_sources, nearest_point_valid_sources, mouse_from_event
from ..common.operator import (
    execute_operator,
    RFOperator, RFOperator_Execute, RFKeyMaps, BLKeyMaps,
    chain_rf_keymaps,
    OperatorPropertyWrapper, poll_retopoflow,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common import gpustate
from ...addon_common.common.blender import event_modifier_check
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import clamp, Frame, Color, sign_threshold
from ...addon_common.common.bezier import CubicBezierSpline
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

        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK',        'ctrl': True}, {'km_context': ('init', 'ready'), 'km_label': 'Insert Strip'}),  # prevents object selection with Ctrl+LMB Click
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
    show_curve_handles: bpy.props.BoolProperty(
        name = 'Curve Handles',
        description = 'Show Bézier curve control handles on selected edge strips and loops',
        default = False
    )
    curve_handle_density: bpy.props.FloatProperty(
        name = 'Density',
        description = 'How many curve handles to show on the selection',
        subtype='FACTOR',
        min = 0.1,
        max = 1,
        default = 0.5
    )
    curve_corner_angle: bpy.props.FloatProperty(
        name = 'Corner Angle',
        description = 'Deflection angle beyond which a vert always gets its own (vector) '
                       'curve handle, regardless of the Density setting',
        subtype = 'ANGLE',
        min = math.radians(10),
        max = math.radians(170),
        default = math.radians(50),
    )

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


def _segment_arc_length(cb, fn_dist):
    return sum(d for _, _, d in cb.get_tessellate_uniform(fn_dist))


def _cumulative_lengths(cbs, segs, fn_dist):
    ''' Running total arc length at each boundary of `segs` (len(segs)+1 entries, starting at 0). '''
    cum = [0.0]
    for seg in segs:
        cum.append(cum[-1] + _segment_arc_length(cbs[seg], fn_dist))
    return cum


def _walk_free_run(start, step, nseg, cyclic, free_at_seg_p0, visited):
    '''
    Extends `visited` outward from `start` one segment at a time (`step` = -1
    backward, +1 forward) for as long as the knot crossed at each step is
    free -- see combined_segs' construction in init() below. Returns the
    newly-visited segments in walk order, nearest to `start` first; `visited`
    itself grows to include them, so a second call in the opposite direction
    won't cross back into this one.
    '''
    result = []
    cur = start
    while True:
        nxt = (cur + step) % nseg if cyclic else cur + step
        if not cyclic and not (0 <= nxt < nseg):
            break
        if nxt in visited:
            break
        # the boundary knot between cur and nxt is "at p0" of whichever one
        # comes later in forward (increasing-index) order
        if not free_at_seg_p0.get(nxt if step > 0 else cur, False):
            break
        result.append(nxt)
        visited.add(nxt)
        cur = nxt
    return result


class RFOperator_Strokes_CurveEdit(RFOperator):
    bl_idname = 'retopoflow.strokes_curve_edit'
    bl_label = 'Edit Stroke Curve'
    bl_description = 'Drag curve control handles to reshape a selected strip or loop'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS'}, None),
    ]

    @classmethod
    def can_start(cls, context):
        i = RFTool_Strokes.rf_overlay.instance
        return False if not i else bool(getattr(i, 'hovering', False))

    def init(self, context, event):
        overlay = RFTool_Strokes.rf_overlay.instance
        self.curves = overlay.curves
        self.chains = overlay.chains
        chain_idx, handle_idx, snapshot = overlay.hovering
        self.chain = self.chains[chain_idx]
        self.spline = self.curves[chain_idx]
        self.handle = self.chain['handles'][handle_idx]
        self.snapshot = snapshot

        RFTool_Strokes.rf_overlay.pause_update()
        RFTool_Strokes.rf_overlay.instance.depsgraph_version = None

        mouse = mouse_from_event(event)
        M, Mi = context.edit_object.matrix_world, context.edit_object.matrix_world.inverted_safe()

        use_proportional_edit = context.tool_settings.use_proportional_edit

        self.mirror = set()
        self.mirror_clip = False
        self.mirror_threshold = Vector((0, 0, 0))
        for mod in context.edit_object.modifiers:
            if mod.type != 'MIRROR': continue
            if not mod.use_clip: continue
            if mod.use_axis[0]: self.mirror.add('x')
            if mod.use_axis[1]: self.mirror.add('y')
            if mod.use_axis[2]: self.mirror.add('z')
            mt, scale = mod.merge_threshold, context.edit_object.scale
            self.mirror_threshold = Vector(( mt / scale.x, mt / scale.y, mt / scale.z ))
            self.mirror_clip = mod.use_clip

        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        self.M, self.Mi = M, Mi
        self.fwd = xform_direction(Mi, view_forward_direction(context))
        self.right = xform_direction(Mi, view_right_direction(context))
        self.spline.tessellate_uniform()

        fn_dist = lambda a, b: (a - b).length

        # segment(s) whose shape will change as this handle is dragged -- verts
        # on these need their *arc-length fraction* preserved instead of their
        # raw parameter t (which isn't proportional to arc length, so it drifts
        # spacing as a segment stretches/compresses under editing)
        nseg = len(self.spline.cbs)
        if self.handle['kind'] == 'knot':
            self.touched_segs = { seg for seg, _ in self.handle['set'] }
        else:
            self.touched_segs = { self.handle['pos'][0] }
            if 'g1_peer' in self.handle:
                # a G1-mirrored tangent arm reshapes the peer segment on the
                # other side of the junction too (see apply_handle), so its
                # verts need the same arc-length tracking as this handle's own
                self.touched_segs.add(self.handle['g1_peer'][0])

        # a "free" knot isn't a vertex -- nothing should be forced to sit
        # exactly on it, or bunch up as it moves. Its two flanking segments
        # aren't independently anchored (unlike a normal touched segment,
        # where the far end IS a real vert), so the whole run from the
        # nearest TRUE (vertex-coupled) knot on one side to the nearest true
        # knot on the other -- crossing over any other free knots along the
        # way -- is treated as one combined span. Every vert in it keeps its
        # original *proportional* position within that combined span's arc
        # length (recomputed fresh each frame in update(), since the span's
        # segments keep reshaping as the drag continues) rather than its
        # position within just one segment, so a vert near one true anchor
        # doesn't get dragged around by an edit happening near the other.
        self.combined_segs = None
        if self.handle['kind'] == 'knot' and self.handle.get('free') and len(self.handle['set']) == 2:
            free_at_seg_p0 = {
                h['pos'][0]: h.get('free', False)
                for h in self.chain['handles']
                if h['kind'] == 'knot' and h['pos'][1] == 'p0'
            }
            seg_before, seg_after = self.handle['set'][0][0], self.handle['set'][1][0]
            cyclic = self.chain['cyclic']
            visited = {seg_before, seg_after}
            backward = _walk_free_run(seg_before, -1, nseg, cyclic, free_at_seg_p0, visited)
            forward = _walk_free_run(seg_after, 1, nseg, cyclic, free_at_seg_p0, visited)
            self.combined_segs = list(reversed(backward)) + [seg_before, seg_after] + forward

        bmvs = [self.bm.verts[i] for i in self.chain['bmv_indices']]
        # gather neighboring geo for proportional editing
        if bmvs and use_proportional_edit:
            connected_only = context.tool_settings.use_proportional_connected
            if connected_only:
                all_bmvs = {}
                # NOTE: bmv.index added to tuple to break distance ties before bmvs are compared
                queue = [(0, bmv.index, bmv) for bmv in bmvs]
                while queue:
                    (d, _, bmv) = heapq.heappop(queue)
                    if bmv in all_bmvs: continue
                    all_bmvs[bmv] = d
                    for bme in bmv.link_edges:
                        bmv_ = bme.other_vert(bmv)
                        heapq.heappush(queue, (d + (M @ bmv.co - M @ bmv_.co).length, bmv_.index, bmv_))
            else:
                cos_sel = [M @ bmv.co for bmv in bmvs]
                all_bmvs = {}
                for bmv in self.bm.verts:
                    co = M @ bmv.co
                    d = min((co - co_sel).length for co_sel in cos_sel)
                    all_bmvs[bmv] = d
        else:
            all_bmvs = { bmv: 0.0 for bmv in bmvs }

        # all data is local to edit!
        data = {}
        bmv_selected_count = 0
        bmv_merged_2d_coords = Vector((0.0, 0.0))
        bmv_merged_3d_coords = Vector((0.0, 0.0, 0.0))
        rgn, r3d = context.region, context.region_data
        combined_cum = _cumulative_lengths(self.spline.cbs, self.combined_segs, fn_dist) if self.combined_segs else None
        for (bmv, distance) in all_bmvs.items():
            t = self.spline.approximate_t_at_point_tessellation(bmv.co, fn_dist)
            o = self.spline.eval(t)
            z = Vector(self.spline.eval_derivative(t))
            if z.length < 1e-9: z = Vector((0, 0, 1))
            z.normalize()
            f = Frame(o, x=self.fwd, z=z)
            seg = min(int(t), nseg - 1)
            arc_frac = None
            combined_frac = None
            if self.combined_segs and seg in self.combined_segs:
                idx = self.combined_segs.index(seg)
                local_frac = self.spline.cbs[seg].approximate_arc_length_fraction_at_t(t - seg, fn_dist)
                dist_into_combined = combined_cum[idx] + local_frac * (combined_cum[idx + 1] - combined_cum[idx])
                combined_frac = dist_into_combined / max(combined_cum[-1], 1e-9)
            elif seg in self.touched_segs:
                arc_frac = self.spline.cbs[seg].approximate_arc_length_fraction_at_t(t - seg, fn_dist)
            data[bmv.index] = (
                t,
                f.w2l_point(bmv.co),
                Vector(bmv.co),
                distance,
                arc_frac,
                combined_frac,
            )
            if use_proportional_edit and bmv.select:
                bmv_selected_count += 1
                co_world = M @ bmv.co
                bmv_merged_3d_coords += co_world
                screen_co = location_3d_to_region_2d(rgn, r3d, co_world)
                if screen_co:
                    bmv_merged_2d_coords += screen_co

        if use_proportional_edit and bmv_selected_count:
            self.selection_origin_3d = bmv_merged_3d_coords / bmv_selected_count
            self.selection_origin_2d = bmv_merged_2d_coords / bmv_selected_count
        else:
            self.selection_origin_3d = None
            self.selection_origin_2d = None

        self.grab = {
            'mouse':   Vector(mouse),
            'current': Vector(mouse),
            'data':    data,
            'only':    None,
        }

    def finish(self, context):
        RFTool_Strokes.rf_overlay.unpause_update()

    def apply_handle(self, context, delta, rgn, r3d, M, Mi):
        h = self.handle
        cbs = self.spline.cbs
        idx_of = {'p0': 0, 'p1': 1, 'p2': 2, 'p3': 3}
        def orig(seg, attr):
            return Vector(self.snapshot[seg][idx_of[attr]])

        seg0, attr0 = h['pos']
        pt_orig = orig(seg0, attr0)
        pt_screen = location_3d_to_region_2d(rgn, r3d, M @ pt_orig)
        if pt_screen is None:
            return
        new_screen = pt_screen + delta

        if h['kind'] == 'knot':
            # knots snap to the source surface and carry their tangent arms along
            new_world = raycast_point_valid_sources(context, new_screen, respect_clip_planes=True)
            if not new_world:
                return
            new_edit = Mi @ new_world
            knot_delta = new_edit - pt_orig
            for (seg, attr) in h['set']:
                setattr(cbs[seg], attr, new_edit.copy())
            for (seg, attr) in h['move']:
                setattr(cbs[seg], attr, orig(seg, attr) + knot_delta)
        else:
            # tangent arms move freely in the view plane
            new_world = region_2d_to_location_3d(rgn, r3d, new_screen, M @ pt_orig)
            new_edit = Mi @ new_world
            setattr(cbs[seg0], attr0, new_edit)
            # G1: at smooth junctions, mirror the peer tangent arm to stay collinear
            if 'g1_peer' in h:
                knot_seg, knot_attr = h['g1_knot']
                peer_seg, peer_attr = h['g1_peer']
                K = orig(knot_seg, knot_attr)
                T_moved = new_edit - K
                peer_orig_pt = orig(peer_seg, peer_attr)
                peer_len = (peer_orig_pt - K).length
                if T_moved.length > 1e-9 and peer_len > 1e-9:
                    setattr(cbs[peer_seg], peer_attr, K - T_moved.normalized() * peer_len)

    def update(self, context, event):
        data = self.grab['data']
        bm, em = self.bm, self.em

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}

        if event.type in {'ESC', 'RIGHTMOUSE'}:
            for cb, pts in zip(self.spline.cbs, self.snapshot):
                # restore snapshot
                cb.p0, cb.p1, cb.p2, cb.p3 = (Vector(p) for p in pts)
            for bmv_idx in data:
                bm.verts[bmv_idx].co = data[bmv_idx][2]
            bmesh.update_edit_mesh(em)
            context.area.tag_redraw()
            return {'CANCELLED'}

        if event.type in {'WHEELDOWNMOUSE', 'WHEELUPMOUSE'}:
            if event.type == 'WHEELUPMOUSE':
                context.tool_settings.proportional_distance *= 0.90
            else:
                context.tool_settings.proportional_distance /= 0.90
            if self.grab['only']:
                for bmv_idx in self.grab['only']:
                    bm.verts[bmv_idx].co = data[bmv_idx][2]
            self.grab['only'] = None

        mouse = mouse_from_event(event)
        self.grab['current'] = mouse
        delta = Vector(mouse) - self.grab['mouse']
        rgn, r3d = context.region, context.region_data
        M, Mi = self.M, self.Mi
        fwd = self.fwd
        prop_use = context.tool_settings.use_proportional_edit
        prop_dist_world = context.tool_settings.proportional_distance
        prop_falloff = context.tool_settings.proportional_edit_falloff

        self.apply_handle(context, delta, rgn, r3d, M, Mi)

        if self.grab['only'] is None:
            self.grab['only'] = [
                bmv_idx
                for bmv_idx in data
                if data[bmv_idx][3] <= prop_dist_world
            ]

        spline = self.spline
        nseg = len(spline.cbs)
        fn_dist = lambda a, b: (a - b).length
        combined_cum = _cumulative_lengths(spline.cbs, self.combined_segs, fn_dist) if self.combined_segs else None
        for bmv_idx in self.grab['only']:
            t, pt_curve_orig, pt_edit_orig, distance, arc_frac, combined_frac = data[bmv_idx]
            if arc_frac is None and combined_frac is None:
                # this vert's segment is neither touched nor part of a
                # combined free-knot run -- its t maps into a segment whose
                # control points this drag never moves, so eval(t) can only
                # ever reproduce the exact same point it's already at
                continue
            bmv = bm.verts[bmv_idx]
            if distance > prop_dist_world: continue
            if prop_use:
                dist = max(1 - distance / prop_dist_world, 0)
                factor = proportional_edit(prop_falloff, dist)
            else:
                factor = 1
            if combined_frac is not None:
                # this vert is somewhere in the combined run spanning a free
                # knot -- keep its proportional position within that run's
                # *current* total arc length (recomputed above, since the
                # run's segments keep reshaping as the drag continues)
                target = combined_frac * combined_cum[-1]
                idx = 0
                while idx < len(combined_cum) - 2 and target > combined_cum[idx + 1]:
                    idx += 1
                seg = self.combined_segs[idx]
                seg_span = max(combined_cum[idx + 1] - combined_cum[idx], 1e-9)
                local_frac = (target - combined_cum[idx]) / seg_span
                t = seg + spline.cbs[seg].approximate_t_at_arc_length_fraction(local_frac, fn_dist)
            elif arc_frac is not None:
                # this vert's segment is being reshaped -- track its original
                # proportional position along the arc length instead of its raw
                # parameter t, so reshaping the segment doesn't bunch verts up
                # or spread them out relative to each other
                seg = min(int(t), nseg - 1)
                t = seg + spline.cbs[seg].approximate_t_at_arc_length_fraction(arc_frac, fn_dist)
            o = spline.eval(t)
            z = Vector(spline.eval_derivative(t))
            if z.length < 1e-9: z = Vector((0, 0, 1))
            z.normalize()
            f = Frame(o, x=fwd, z=z)
            pt_edit_new = M @ f.l2w_point(pt_curve_orig)
            pt_edit_new = pt_edit_orig + (pt_edit_new - pt_edit_orig) * factor
            co = nearest_point_valid_sources(context, pt_edit_new, world=False, respect_clip_planes=True) or pt_edit_orig

            if self.mirror:
                th = self.mirror_threshold
                zero = {
                    'x': ('x' in self.mirror and (sign_threshold(co.x, th.x) != sign_threshold(pt_edit_orig.x, th.x) or sign_threshold(pt_edit_orig.x, th.x) == 0)),
                    'y': ('y' in self.mirror and (sign_threshold(co.y, th.y) != sign_threshold(pt_edit_orig.y, th.y) or sign_threshold(pt_edit_orig.y, th.y) == 0)),
                    'z': ('z' in self.mirror and (sign_threshold(co.z, th.z) != sign_threshold(pt_edit_orig.z, th.z) or sign_threshold(pt_edit_orig.z, th.z) == 0)),
                }
                # iteratively zero out the component
                for _ in range(1000):
                    d = 0
                    if zero['x']: co.x, d = co.x * 0.95, max(abs(co.x), d)
                    if zero['y']: co.y, d = co.y * 0.95, max(abs(co.y), d)
                    if zero['z']: co.z, d = co.z * 0.95, max(abs(co.z), d)
                    co_world = M @ Vector((*co, 1.0))
                    co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True, respect_clip_planes=True)
                    if not co_world_snapped: break
                    co = Mi @ co_world_snapped
                    if d < 0.001: break  # break out if change was below threshold
                if zero['x']: co.x = 0
                if zero['y']: co.y = 0
                if zero['z']: co.z = 0

            bmv.co = co

        bmesh.update_edit_mesh(em)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def draw_curve(self, context):
        ''' Draw the dashed curve + control handles live while dragging. '''
        rgn, r3d = context.region, context.region_data
        if not r3d: return
        M = self.M
        cbs = self.spline.cbs
        for cb in cbs:
            curve_pts = [location_3d_to_region_2d(rgn, r3d, M @ Vector(cb.eval(v / 20))) for v in range(21)]
            curve_pts = [p for p in curve_pts if p]
            draw_curve_line = True
            if draw_curve_line and len(curve_pts) >= 2:
                Drawing.draw2D_linestrip(context, curve_pts, (1.0, 1.0, 0.0, 0.5), width=2, stipple=[5,5])
            p0_, p1_, p2_, p3_ = (location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cb, a))) for a in ('p0','p1','p2','p3'))
            knot_r, tan_r = Drawing.scale(KNOT_RADIUS/2), Drawing.scale(TANGENT_RADIUS/2)
            a0, a1 = shrink_segment(p0_, p1_, knot_r, tan_r)
            a2, a3 = shrink_segment(p2_, p3_, tan_r, knot_r)
            Drawing.draw2D_lines(context, [a0, a1, a2, a3], (1.0, 1.0, 1.0, 0.5), width=2)
        knot_pts2d, free_knot_pts2d, tan_pts2d = [], [], []
        for h in self.chain['handles']:
            seg, attr = h['pos']
            p = location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cbs[seg], attr)))
            if not p: continue
            if h['kind'] != 'knot':
                tan_pts2d.append(p)
            elif h.get('free'):
                free_knot_pts2d.append(p)
            else:
                knot_pts2d.append(p)
        if tan_pts2d:
            Drawing.draw2D_points(context, tan_pts2d, (0.0, 0.0, 0.0, 0.75), radius=TANGENT_RADIUS, border=2, borderColor=(1,1,1,0.5))
        if knot_pts2d:
            Drawing.draw2D_points(context, knot_pts2d, (1.0, 1.0, 1.0, 1.0), radius=KNOT_RADIUS, border=2, borderColor=(0,0,0,0.5))
        if free_knot_pts2d:
            Drawing.draw2D_points(context, free_knot_pts2d, (1.0, 1.0, 1.0, 1.0), radius=KNOT_RADIUS, border=2, borderColor=FREE_KNOT_BORDER_COLOR)

    def draw_postpixel(self, context):
        ''' Draw the live curve, plus the proportional edit circle in 2D space. '''
        self.draw_curve(context)
        if not context.tool_settings.use_proportional_edit: return
        if self.selection_origin_3d is None or self.selection_origin_2d is None: return
        gpustate.blend('ALPHA')
        rgn, r3d = context.region, context.region_data

        pt = self.selection_origin_3d + context.tool_settings.proportional_distance * self.right
        pt2d = location_3d_to_region_2d(rgn, r3d, pt)
        if pt2d is None: return
        radius = pt2d[0] - self.selection_origin_2d[0]
        if self.handle['kind'] == 'knot':
            center = self.selection_origin_2d
        else:
            seg, attr = self.handle['pos']
            center = location_3d_to_region_2d(rgn, r3d, self.M @ Vector(getattr(self.spline.cbs[seg], attr)))
            if center is None: return

        col_off = 20/255
        color_in = Color((0.33+col_off, 0.33+col_off, 0.33+col_off, 1.0))
        color_out = Color((0.33-col_off, 0.33-col_off, 0.33-col_off, 1.0))

        gpustate.blend('ALPHA')
        Drawing.draw2D_smooth_circle(context, center, radius, color_out, width=3)
        Drawing.draw2D_smooth_circle(context, center, radius-1, color_in, width=1)
        gpustate.blend('NONE')


RFOperator_Strokes_Overlay = create_loopstrip_curve_overlay(
    'RFOperator_Strokes_Selection_Overlay',
    'retopoflow.strokes',  # must match RFTool_base.bl_idname
    'strokes_overlay',
    'Strokes Selected Overlay',
    True,
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

    rf_brush = RFBrush_Strokes()
    rf_overlay = RFOperator_Strokes_Overlay

    props = None  # needed to reset properties

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_Strokes,
        RFOperator_Stroke_Insert,
        RFOperator_Strokes_CurveEdit,
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
