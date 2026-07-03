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
from ..rfoverlays.curve_chain_providers import QuadStripChainProvider, LoopStripChainProvider
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

    count0: bpy.props.IntProperty(
        name='Count',
        description='Number of quads in the first quad strip',
        default=8,
        min=2,
        max=256,
    )
    width0: bpy.props.FloatProperty(
        name='Width',
        description='Width of quads in the first quad strip',
        min=0.0001,
        precision=4,
        step=0.01,

    )

    count1: bpy.props.IntProperty(
        name='Count',
        description='Number of quads in the second quad strip',
        default=8,
        min=2,
        max=256,
    )
    width1: bpy.props.FloatProperty(
        name='Width',
        description='Width of quads in the second quad strip',
        min=0.0001,
        precision=4,
        step=0.01,
    )

    count2: bpy.props.IntProperty(
        name='Count',
        description='Number of quads in the third quad strip',
        default=8,
        min=2,
        max=256,
    )
    width2: bpy.props.FloatProperty(
        name='Width',
        description='Width of quads in the third quad strip',
        min=0.0001,
        precision=4,
        step=0.01,
    )


    @staticmethod
    def polystrips_insert(context, radius2D, stroke3D, point3D_0, point3D_1, is_cycle, length2D, snap_bmf0, snap_bmf1, split_angle, mirror_correct):
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
        )
        logic = RFOperator_PolyStrips_Insert.logic
        if logic.error: return
        bpy.ops.retopoflow.polystrips_insert(
            'INVOKE_DEFAULT', True,
            count0=logic.count0, width0=logic.width0,
            count1=logic.count1, width1=logic.width1,
            count2=logic.count2, width2=logic.width2,
            split_angle=logic.split_angle,
            mirror_correct=logic.mirror_correct,
        )

    @staticmethod
    def polystrips_reinsert(context):
        logic = RFOperator_PolyStrips_Insert.logic
        if not logic or logic.error: return
        bpy.ops.retopoflow.polystrips_insert(
            'INVOKE_DEFAULT', True,
            count0=logic.count0, width0=logic.width0,
            count1=logic.count1, width1=logic.width1,
            count2=logic.count2, width2=logic.width2,
            split_angle=logic.split_angle,
            mirror_correct=logic.mirror_correct,
        )

    def draw(self, context):
        logic = RFOperator_PolyStrips_Insert.logic
        if not logic: return

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        if logic.strip_count == 1:
            layout.prop(self, 'count0')
            layout.prop(self, 'width0')
            layout.prop(self, 'split_angle')

        elif logic.strip_count >= 1:
            col = layout.column(align=True)
            col.prop(self, 'count0', text='Strip 1 Count')
            col.prop(self, 'width0')

            if logic.strip_count >= 2:
                col = layout.column(align=True)
                col.prop(self, 'count1', text='Strip 2 Count')
                col.prop(self, 'width1')

            if logic.strip_count >= 3:
                col = layout.column(align=True)
                col.prop(self, 'count2', text='Strip 3 Count')
                col.prop(self, 'width2')

            layout.prop(self, 'split_angle')

        if logic.show_mirror_correct:
            layout.prop(self, 'mirror_correct', text='Mirror Side')

    def execute(self, context):
        try:
            logic = RFOperator_PolyStrips_Insert.logic
            logic.count0, logic.width0 = self.count0, self.width0
            logic.count1, logic.width1 = self.count1, self.width1
            logic.count2, logic.width2 = self.count2, self.width2
            logic.split_angle = self.split_angle
            logic.mirror_correct = self.mirror_correct
            logic.create(context)
            self.count0, self.width0 = logic.count0, logic.width0
            self.count1, self.width1 = logic.count1, logic.width1
            self.count2, self.width2 = logic.count2, logic.width2
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
    def create_redo_operator(idname : str, description : str, keymap : RFKeyMap):
        # add keymap to RFOperator_PolyStrips_Insert.rf_keymaps
        # note: still creating RFOperator_PolyStrips_Insert, so using RFOperator_PolyStrips_Insert_Keymaps.rf_keymaps
        RFOperator_PolyStrips_Insert_Keymaps.rf_keymaps.append( (f'retopoflow.{idname}', keymap, None) )
        def wrapper(fn):
            @execute_operator(idname, description, options={'INTERNAL'})
            @wraps(fn)
            def wrapped(context):
                last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
                if last_op != RFOperator_PolyStrips_Insert.bl_label: return
                logic = RFOperator_PolyStrips_Insert.logic
                if not logic or logic.error: return
                fn(context, logic)
                bpy.ops.ed.undo()
                RFOperator_PolyStrips_Insert.polystrips_reinsert(context)
            return wrapped
        return wrapper

    @create_redo_operator('polystrips_insert_count0_decreased', 'Decrease count of quads in first quad strip', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1})
    def decrease_count0(context, logic):
        logic.count0 -= 1

    @create_redo_operator('polystrips_insert_count0_increased', 'Increase count of quads in first quad strip', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'ctrl': 1})
    def increase_count0(context, logic):
        logic.count0 += 1

    @create_redo_operator('polystrips_insert_width0_decreased', 'Decrease width of quads in first quad strip', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'shift': 1})
    def decrease_width0(context, logic):
        logic.width0 *= 0.95

    @create_redo_operator('polystrips_insert_width0_increased', 'Increase width of quads in first quad strip', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'shift': 1})
    def increase_width1(context, logic):
        logic.width0 /= 0.95



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

    def process_stroke(self, context, radius2D, snap_distance, stroke2D, stroke3D, is_cycle, snapped_geo, snapped_mirror, **kwargs):
        snap_bmf0, snap_bmf1 = snapped_geo[2]
        p3D_0, p3D_1 = stroke3D[0], stroke3D[-1]
        if not snap_bmf0:
            l = len(stroke2D)
            p0 = stroke2D[0]
            p1 = next((s for s in stroke2D if (s - p0).length >= radius2D), None)
            if p1:
                d = Direction2D(p0 - p1)
                for i in range(1, 101):
                    p = p0 + d * (radius2D * (i / 100))
                    if not raycast_point_valid_sources(context, p, respect_clip_planes=True): break
                    stroke2D = [p] + stroke2D
        if not snap_bmf1:
            p0 = stroke2D[-1]
            p1 = next((s for s in stroke2D[::-1] if (s - p0).length >= radius2D), None)
            if p1:
                d = Direction2D(p0 - p1)
                for i in range(1, 101):
                    p = p0 + d * (radius2D * (i / 100))
                    if not raycast_point_valid_sources(context, p, respect_clip_planes=True): break
                    stroke2D += [p]
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
