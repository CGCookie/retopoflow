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

from ..rfoverlay_base import RFOverlay_Base
from ..rfglobals import RFGlobals

from ..rfbrushes.stroke_brush import create_stroke_brush
from ..rfoverlays.curve_overlay import create_curve_overlay
from ..common.curves import QuadStripChainProvider, LoopStripChainProvider
from ..rfoperators.curve_edit import create_curve_edit_operator, create_curve_toggle_handle_type_operator

from ..rftool_base import RFTool_Base
from ..common.icons import get_path_to_blender_icon
from ..common.raycast import raycast_point_valid_sources
from ..common.operator import (
    execute_operator,
    RFOperator, RFOperator_Execute, RFKeyMap, RFKeyMaps, BLKeyMaps,
    chain_rf_keymaps,
    OperatorPropertyWrapper, poll_retopoflow,
)
from ...addon_common.common.blender import event_modifier_check
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import Direction2D
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.utils import iter_pairs

from .polystrips_logic import PolyStrips_Logic

from ..rfoperators.quickswitch import RFOperator_Relax_QuickSwitch, RFOperator_Tweak_QuickSwitch
from ..rfoperators.transform import RFOperator_Translate, sync_projection_from_blender
from ..rfoperators.maximize_watcher import RFOperator_MaximizeWatcher
from ..rfoperators.topo_rotate import RFOperator_TopoRotate
from ..rfoperators.adjust_segment_count import RFOperator_AdjustSegmentCount
from ..rfoperators.adjust_strip_width import RFOperator_AdjustStripWidth

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
    'polystrips_brush',
    'PolyStrips Brush',
    smoothing=0.5,
    snap=(False, False, True),
    radius=50,
    draw_leftright=True,
)

def _adjust_selected_strip(context, sign):
    '''
    Ctrl+Scroll fallback once the just-inserted strip's redo state is gone:
    resegment the SELECTED strip via the generic Adjust Segment Count operator.
    Consecutive scrolls collapse onto one undo step -- if the last operator is
    already an adjust, undo it and re-run at the new absolute count (reading
    .count back also respects an F9 edit), mirroring the insert-redo mechanism.
    '''
    ops = context.window_manager.operators
    last = ops[-1] if ops else None
    if last is not None and last.name == RFOperator_AdjustSegmentCount.bl_label:
        target = last.count + sign
        bpy.ops.ed.undo()
        # explicit `True` (undo) arg, matching polystrips_reinsert above --
        # required for a REGISTER|UNDO op invoked via a nested bpy.ops call
        # (from inside this operator's own execute) to properly register
        # itself as the "last operator" so its F9 redo panel works
        bpy.ops.retopoflow.adjust_segment_count('INVOKE_DEFAULT', True, count=target)
    else:
        bpy.ops.retopoflow.adjust_segment_count('INVOKE_DEFAULT', True, delta=sign)


def _adjust_selected_strip_width(context, sign):
    factor = 0.95 if sign < 0 else 1 / 0.95
    ops = context.window_manager.operators
    last = ops[-1] if ops else None
    if last is not None and last.name == RFOperator_AdjustStripWidth.bl_label:
        target_start = last.scale_start * factor
        target_end = last.scale_end * factor
        bpy.ops.ed.undo()
        bpy.ops.retopoflow.adjust_strip_width('INVOKE_DEFAULT', True, scale_start=target_start, scale_end=target_end)
    else:
        bpy.ops.retopoflow.adjust_strip_width('INVOKE_DEFAULT', True, delta_factor=factor)


class RFOperator_PolyStrips_Insert_Keymaps:
    '''
    collection of keymaps, used to collect redo shortcuts created by @create_redo_operator
    note: cannot use RFOperator_PolyStrips_Insert.rf_keymaps, because RFOperator_PolyStrips_Insert
          is not yet created!
    '''

    rf_keymaps : RFKeyMaps = []


class RFOperator_PolyStrips_Insert_Properties:
    '''
    bpy properties that are shared between insert operator and the modal operator
    used to prevent duplicate code across both operators
    '''

    split_angle: bpy.props.FloatProperty(
        name='Split Angle',
        description='Angle threshold (in degrees) where the stroke is split to create a corner',
        subtype='ANGLE',
        default=1.04719755,
        min=0.78539816,
        max=2.35619449,
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


class RFOperator_PolyStrips_Insert(
        RFOperator_PolyStrips_Insert_Keymaps,
        RFOperator_PolyStrips_Insert_Properties,
        RFOperator_Execute,
    ):
    bl_idname = 'retopoflow.polystrips_insert'
    bl_label = 'Insert PolyStrip'
    bl_description = 'Insert quad strip'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    logic = None

    count: bpy.props.IntProperty(
        name='Count',
        description='Total number of quads in the strip. Cannot go lower than the number of corners.',
        default=8,
        min=2,
        max=256,
    )
    scale_start: bpy.props.FloatProperty(
        name='Start Scale',
        description='Width scale factor at the start of the stroke.',
        default=1.0,
        min=0.0,
        soft_min=0.0,
        soft_max=5.0,
        precision=3,
    )
    scale_end: bpy.props.FloatProperty(
        name='End Scale',
        description='Width scale factor at the end of the stroke.',
        default=1.0,
        min=0.0,
        soft_min=0.0,
        soft_max=5.0,
        precision=3,
    )
    width_interpolation: bpy.props.EnumProperty(
        name='Interpolation',
        description='How the width scale transitions from the start of the stroke to the end',
        items=[
            ('LINEAR', 'Linear', 'Width scale changes at a constant rate from start to end'),
            ('SMOOTH', 'Smooth', 'Width scale eases in and out at the start and end'),
        ],
        default='LINEAR',
    )


    @staticmethod
    def polystrips_insert(context, radius2D, stroke3D, point3D_0, point3D_1, is_cycle, length2D, snap_bmf0, snap_bmf1, split_angle, mirror_correct, radius3D=None):
        RFOperator_PolyStrips_Insert.logic = PolyStrips_Logic(
            context,
            radius2D,
            stroke3D, point3D_0, point3D_1,
            is_cycle,
            length2D,
            snap_bmf0,
            snap_bmf1,
            split_angle,
            mirror_correct,
            radius3D=radius3D,
        )
        logic = RFOperator_PolyStrips_Insert.logic
        if logic.error: return
        bpy.ops.retopoflow.polystrips_insert(
            'INVOKE_DEFAULT', True,
            count=logic.count, scale_start=logic.scale_start, scale_end=logic.scale_end,
            width_interpolation=logic.width_interpolation,
            split_angle=logic.split_angle,
            mirror_correct=logic.mirror_correct,
        )

    @staticmethod
    def polystrips_reinsert(context):
        logic = RFOperator_PolyStrips_Insert.logic
        if not logic or logic.error: return
        bpy.ops.retopoflow.polystrips_insert(
            'INVOKE_DEFAULT', True,
            count=logic.count, scale_start=logic.scale_start, scale_end=logic.scale_end,
            width_interpolation=logic.width_interpolation,
            split_angle=logic.split_angle,
            mirror_correct=logic.mirror_correct,
        )

    def draw(self, context):
        logic = RFOperator_PolyStrips_Insert.logic
        if not logic: return

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        if logic.strip_count >= 1:
            layout.prop(self, 'count')
            layout.prop(self, 'scale_start')
            layout.prop(self, 'scale_end')
            layout.prop(self, 'width_interpolation')
            layout.prop(self, 'split_angle')

        if logic.show_mirror_correct:
            layout.prop(self, 'mirror_correct', text='Mirror Side')

    def execute(self, context):
        try:
            logic = RFOperator_PolyStrips_Insert.logic
            logic.count = self.count
            logic.scale_start = self.scale_start
            logic.scale_end = self.scale_end
            logic.width_interpolation = self.width_interpolation
            logic.split_angle = self.split_angle
            logic.mirror_correct = self.mirror_correct
            logic.create(context)
            self.count = logic.count
            self.scale_start, self.scale_end = logic.scale_start, logic.scale_end
            self.mirror_correct = logic.mirror_correct
        except Exception as e:
            # TODO: revisit how this issue (#1376) is handled.
            #       right now, the operator is simply cancelled, which could leave mesh in a weird state or remove
            #       recently added stroke!
            print(f'{type(self).__name__}.execute: Caught Exception {e}')
            debugger.print_exception()
            return {'CANCELLED'}

        return {'FINISHED'}

    @staticmethod
    def create_redo_operator(idname : str, description : str, keymap : RFKeyMap, *, fallback=None):
        # add keymap to RFOperator_PolyStrips_Insert.rf_keymaps
        # note: still creating RFOperator_PolyStrips_Insert, so using RFOperator_PolyStrips_Insert_Keymaps.rf_keymaps
        RFOperator_PolyStrips_Insert_Keymaps.rf_keymaps.append( (f'retopoflow.{idname}', keymap, None) )
        def wrapper(fn):
            @execute_operator(idname, description, options={'INTERNAL'})
            @wraps(fn)
            def wrapped(context):
                last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
                logic = RFOperator_PolyStrips_Insert.logic
                redo_accessible = (last_op == RFOperator_PolyStrips_Insert.bl_label) and logic and not logic.error
                if not redo_accessible:
                    # the just-inserted strip's redo panel is no longer reachable
                    # -- hand off to the generic adjuster (count only), else no-op
                    if fallback: fallback(context)
                    return
                fn(context, logic)
                bpy.ops.ed.undo()
                RFOperator_PolyStrips_Insert.polystrips_reinsert(context)
            return wrapped
        return wrapper

    @create_redo_operator('polystrips_insert_count0_decreased', 'Decrease quad strip count', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1}, fallback=lambda context: _adjust_selected_strip(context, -1))
    def decrease_count0(context, logic):
        logic.count -= 1

    @create_redo_operator('polystrips_insert_count0_increased', 'Increase quad strip count', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'ctrl': 1}, fallback=lambda context: _adjust_selected_strip(context, +1))
    def increase_count0(context, logic):
        logic.count += 1

    @create_redo_operator('polystrips_insert_width0_decreased', 'Decrease quad strip width', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'shift': 1}, fallback=lambda context: _adjust_selected_strip_width(context, -1))
    def decrease_width0(context, logic):
        # scales both ends together, preserving the start/end gradient shape
        logic.scale_start *= 0.95
        logic.scale_end *= 0.95

    @create_redo_operator('polystrips_insert_width0_increased', 'Increase quad strip width', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'shift': 1}, fallback=lambda context: _adjust_selected_strip_width(context, +1))
    def increase_width1(context, logic):
        logic.scale_start /= 0.95
        logic.scale_end /= 0.95



def _reset_insert_logic(self, context, event):
    # a fresh curve edit invalidates the redo-panel state of whatever strip
    # insertion produced this geometry -- wheel-scroll count/width redo
    # shortcuts (see RFOperator_PolyStrips_Insert.create_redo_operator) must
    # not resurrect a stale insert after the strip's curve has been reshaped
    RFOperator_PolyStrips_Insert.logic = None


class RFOperator_PolyStrips(RFOperator_PolyStrips_Insert_Properties, RFOperator):
    bl_idname = 'retopoflow.polystrips'
    bl_label = 'PolyStrips'
    bl_description = 'Insert quad strip'
    # bl_space_type = 'VIEW_3D'
    # bl_region_type = 'TOOLS'
    bl_options = set()

    loop_select_op = 'mesh.loop_select' if bpy.app.version >= (5, 1, 0) else 'mesh.loop_multi_select'

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),

        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK', 'ctrl': True}, # prevents object selection with Ctrl+LMB Click
            {'km_context': ('init', 'ready'), 'km_label': 'Insert Strip', 'km_status_event_value': 'CLICK_DRAG'}
        ),
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK', 'ctrl': True}, None),

        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, {'km_context': 'insert', 'km_label': 'Draw Strip'}),

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

    stroke_smoothing: bpy.props.FloatProperty(
        name='Stabilize',
        description='Stroke smoothing factor.  Zero means no smoothing, and higher means more smoothing.',
        get=lambda _: RFBrush_Strokes.get_stroke_smooth(),
        set=lambda _,v: RFBrush_Strokes.set_stroke_smooth(v),
        min=0.00,
        max=1.0,
        default=0.5,
    )


    def init(self, context, event):
        self.km_context = 'ready'
        RFTool_PolyStrips.rf_brush.set_operator(self)
        RFTool_PolyStrips.rf_brush.reset_nearest(context)
        RFTool_PolyStrips.rf_overlay.pause_overlay()
        self.tickle(context)

    def finish(self, context):
        self.set_statusbar_override(None)
        self.km_context = 'init'
        RFTool_PolyStrips.rf_brush.set_operator(None)
        RFTool_PolyStrips.rf_brush.reset_nearest(context)
        RFTool_PolyStrips.rf_overlay.unpause_overlay()

    def reset(self):
        RFTool_PolyStrips.rf_brush.reset()

    def process_stroke(self, context, radius2D, snap_distance, stroke2D, stroke3D, is_cycle, snapped_geo, snapped_mirror, radius3D=None):
        snap_bmf0, snap_bmf1 = snapped_geo[2]
        p3D_0, p3D_1 = stroke3D[0], stroke3D[-1]

        def extend_cap(pts2D, from_start):
            # Extend the stroke past its unsnapped end by one brush radius in 3D
            # so the cap lands about where the brush circle ended on the mesh.
            p0 = pts2D[0] if from_start else pts2D[-1]
            search = pts2D if from_start else reversed(pts2D)
            p1 = next((s for s in search if (s - p0).length >= radius2D), None)
            if not p1: return pts2D
            d = Direction2D(p0 - p1)
            step = radius2D / 100
            prev3D = raycast_point_valid_sources(context, p0, world=False, respect_clip_planes=True)
            dist3D = 0.0
            extension = []
            for i in range(1, 1001):
                p = p0 + d * (step * i)
                pt3D = raycast_point_valid_sources(context, p, world=False, respect_clip_planes=True)
                if not pt3D: break
                if prev3D: dist3D += (pt3D - prev3D).length
                prev3D = pt3D
                extension.append(p)
                if radius3D:
                    if dist3D >= radius3D: break
                elif step * i >= radius2D:
                    break
            if not extension: return pts2D
            return (list(reversed(extension)) + pts2D) if from_start else (pts2D + extension)

        if not snap_bmf0:
            stroke2D = extend_cap(stroke2D, True)
        if not snap_bmf1:
            stroke2D = extend_cap(stroke2D, False)
        length2D = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke2D, is_cycle))
        stroke3D = [raycast_point_valid_sources(context, pt, world=False, respect_clip_planes=True) for pt in stroke2D]
        stroke3D = [pt for pt in stroke3D if pt]
        RFOperator_PolyStrips_Insert.polystrips_insert(
            context,
            radius2D,
            stroke3D, p3D_0, p3D_1,
            is_cycle,
            length2D,
            snap_bmf0, snap_bmf1,
            self.split_angle,
            self.mirror_correct,
            radius3D=radius3D,
        )

    def update(self, context, event):
        RFCore = RFGlobals.RFCore_None
        if not RFCore: return {'CANCELLED'}

        if event.value in {'CLICK', 'DOUBLE_CLICK'} and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
            # prevents object selection with Ctrl+LMB Click
            return {'RUNNING_MODAL'}

        if RFTool_PolyStrips.rf_brush.is_stroking():
            self.set_statusbar_override(self.rf_status['insert'])
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE'}:
                RFCore.handle_update(context, event)
                return {'RUNNING_MODAL'}
        else:
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



@execute_operator('switch_to_polystrips', 'RetopoFlow: Switch to PolyStrips', fn_poll=poll_retopoflow)
def switch_rftool(context):
    RFTool_PolyStrips.activate_tool(context)


RFOperator_PolyStrips_Overlay = create_curve_overlay(
    'RFOperator_PolyStrips_Selection_Overlay',
    'retopoflow.polystrips',  # must match RFTool_base.bl_idname
    'polystrips_overlay',
    'PolyStrips Selected Overlay',
    # faces win: a selection containing quad strips shows only strip curves;
    # loop curves only appear when the selection is edges-only. Same list,
    # same order as Strokes -- one selection-driven system regardless of
    # which tool is active.
    [QuadStripChainProvider(), LoopStripChainProvider(only_boundary=True)],
)

RFOperator_PolyStrips_Edit = create_curve_edit_operator(
    'RFOperator_PolyStrips_CurveEdit',
    'polystrips_edit',
    'Edit PolyStrip',
    'Drag curve control handles to reshape a selected quad strip',
    get_overlay=lambda: RFTool_PolyStrips.rf_overlay,
    on_init=_reset_insert_logic,
)

RFOperator_PolyStrips_ToggleHandleType = create_curve_toggle_handle_type_operator(
    'polystrips_toggle_handle_type',
    'Toggle Curve Handle Type',
    'Cycle the hovered curve control point between Aligned, Vector, and Automatic',
    get_overlay=lambda: RFTool_PolyStrips.rf_overlay,
)


class RFTool_PolyStrips(RFTool_Base):
    bl_idname : str = "retopoflow.polystrips"
    bl_label : str = "PolyStrips"
    bl_description : str = "Insert quad strip"
    bl_icon : str = get_path_to_blender_icon('polystrips')
    bl_widget : str | None = None

    rf_operator_idname : str | None = 'retopoflow.polystrips'
    rf_supports_curve_handles = True
    rf_brush = RFBrush_Strokes()
    rf_overlay : type[RFOverlay_Base] | None = RFOperator_PolyStrips_Overlay

    props = None  # needed to reset properties

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_PolyStrips,
        RFOperator_PolyStrips_Insert,
        RFOperator_PolyStrips_Edit,
        RFOperator_PolyStrips_ToggleHandleType,
        RFOperator_MaximizeWatcher,
        RFOperator_StrokesBrush_Adjust,
        RFOperator_Translate,
        RFOperator_Relax_QuickSwitch,
        RFOperator_Tweak_QuickSwitch,
        RFOperator_TopoRotate,
    )

    def draw_settings(context, layout, tool):
        prefs = RF_Prefs.get_prefs(context)
        props_polystrips = tool.operator_properties(RFOperator_PolyStrips.bl_idname)
        RFTool_PolyStrips.props = props_polystrips

        if context.region.type == 'TOOL_HEADER':
            # layout.label(text="Insert:")
            layout.prop(props_polystrips, 'brush_radius', text="Radius")
            layout.prop(props_polystrips, 'stroke_smoothing', slider=True)
            layout.prop(props_polystrips, 'split_angle')

            draw_line_separator(layout)

            draw_tweaking_popover(context, layout, props_polystrips)
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
            header, panel = layout.panel(idname='polystrips_spans_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                panel.prop(props_polystrips, 'brush_radius', text="Radius")
                panel.prop(props_polystrips, 'stroke_smoothing', slider=True)
                panel.prop(props_polystrips, 'split_angle')
            draw_tweaking_panel(context, layout)
            draw_snapping_panel(context, layout, idname='polystrips_snapping_panel')
            draw_cleanup_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context):
        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter('PolyStrips')
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
            cls.resetter['context.tool_settings.mesh_select_mode'] = [False, False, True]

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
        cls.rf_brush.stop()
