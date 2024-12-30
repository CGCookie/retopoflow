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
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from ..rfbrushes.strokes_brush import RFBrush_Strokes, RFOperator_StrokesBrush_Adjust
from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, nearest_bmv_world, nearest_bme_world, bme_midpoint, get_boundary_strips_cycles
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
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, size2D_to_size, vec_forward, mouse_from_event
from ..common.maths import view_forward_direction, lerp, lerp_map
from ..common.operator import (
    invoke_operator, execute_operator,
    RFOperator, RFOperator_Execute, RFRegisterClass,
    chain_rf_keymaps, wrap_property,
)
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event, nearest_point_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common import gpustate
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import Color, Frame, clamp
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.utils import iter_pairs

from .strokes_logic import Strokes_Logic

from ..rfoperators.transform import RFOperator_Translate_ScreenSpace


@execute_operator('strokes_insert_spans_decreased', 'Reinsert stroke with decreased spans', options={'INTERNAL'})
def strokes_spans_decrease(context):
    last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
    if last_op != RFOperator_Stroke_Insert.bl_label: return
    data = RFOperator_Stroke_Insert.stroke_data
    data['cut_count'] = max(1, data['cut_count'] - 1)
    bpy.ops.ed.undo()
    bpy.ops.retopoflow.strokes_insert('INVOKE_DEFAULT', True, extrapolate_mode=data['extrapolate'], cut_count=data['cut_count'], bridging_offset=data['bridging_offset'], smooth_angle=data['smooth_angle'], smooth_density0=data['smooth_density0'], smooth_density1=data['smooth_density1'])

@execute_operator('strokes_insert_spans_increased', 'Reinsert stroke with increased spans', options={'INTERNAL'})
def strokes_spans_increase(context):
    last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
    if last_op != RFOperator_Stroke_Insert.bl_label: return
    data = RFOperator_Stroke_Insert.stroke_data
    data['cut_count'] += 1
    bpy.ops.ed.undo()
    bpy.ops.retopoflow.strokes_insert('INVOKE_DEFAULT', True, extrapolate_mode=data['extrapolate'], cut_count=data['cut_count'], bridging_offset=data['bridging_offset'], smooth_angle=data['smooth_angle'], smooth_density0=data['smooth_density0'], smooth_density1=data['smooth_density1'])

@execute_operator('strokes_insert_shift_decreased', 'Reinsert stroke with shifted spans', options={'INTERNAL'})
def strokes_shift_decrease(context):
    last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
    if last_op != RFOperator_Stroke_Insert.bl_label: return
    data = RFOperator_Stroke_Insert.stroke_data
    data['bridging_offset'] -= 1
    bpy.ops.ed.undo()
    bpy.ops.retopoflow.strokes_insert('INVOKE_DEFAULT', True, extrapolate_mode=data['extrapolate'], cut_count=data['cut_count'], bridging_offset=data['bridging_offset'], smooth_angle=data['smooth_angle'], smooth_density0=data['smooth_density0'], smooth_density1=data['smooth_density1'])

@execute_operator('strokes_insert_shift_increased', 'Reinsert stroke with shifted spans', options={'INTERNAL'})
def strokes_shift_increase(context):
    last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
    if last_op != RFOperator_Stroke_Insert.bl_label: return
    data = RFOperator_Stroke_Insert.stroke_data
    data['bridging_offset'] += 1
    bpy.ops.ed.undo()
    bpy.ops.retopoflow.strokes_insert('INVOKE_DEFAULT', True, extrapolate_mode=data['extrapolate'], cut_count=data['cut_count'], bridging_offset=data['bridging_offset'], smooth_angle=data['smooth_angle'], smooth_density0=data['smooth_density0'], smooth_density1=data['smooth_density1'])

@execute_operator('strokes_insert_smooth_angle_decreased', 'Reinsert stroke with less smoothed angles', options={'INTERNAL'})
def strokes_smooth_angle_decrease(context):
    last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
    if last_op != RFOperator_Stroke_Insert.bl_label: return
    data = RFOperator_Stroke_Insert.stroke_data
    data['smooth_angle'] -= 0.25
    bpy.ops.ed.undo()
    bpy.ops.retopoflow.strokes_insert('INVOKE_DEFAULT', True, extrapolate_mode=data['extrapolate'], cut_count=data['cut_count'], bridging_offset=data['bridging_offset'], smooth_angle=data['smooth_angle'], smooth_density0=data['smooth_density0'], smooth_density1=data['smooth_density1'])

@execute_operator('strokes_insert_smooth_angle_increased', 'Reinsert stroke with more smoothed angles', options={'INTERNAL'})
def strokes_smooth_angle_increase(context):
    last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
    if last_op != RFOperator_Stroke_Insert.bl_label: return
    data = RFOperator_Stroke_Insert.stroke_data
    data['smooth_angle'] += 0.25
    bpy.ops.ed.undo()
    bpy.ops.retopoflow.strokes_insert('INVOKE_DEFAULT', True, extrapolate_mode=data['extrapolate'], cut_count=data['cut_count'], bridging_offset=data['bridging_offset'], smooth_angle=data['smooth_angle'], smooth_density0=data['smooth_density0'], smooth_density1=data['smooth_density1'])


class RFOperator_Stroke_Insert(RFOperator_Execute):
    bl_idname = 'retopoflow.strokes_insert'
    bl_label = 'Strokes: Insert new stroke'
    bl_description = 'Insert edge strips and extrude edges into a patch'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    rf_keymaps = [
        ('retopoflow.strokes_insert_spans_increased', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'ctrl': 1}, None),
        ('retopoflow.strokes_insert_spans_decreased', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1}, None),
        ('retopoflow.strokes_insert_shift_increased', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'alt': 1}, None),
        ('retopoflow.strokes_insert_shift_decreased', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'alt': 1}, None),
        ('retopoflow.strokes_insert_smooth_angle_increased', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'shift': 1}, None),
        ('retopoflow.strokes_insert_smooth_angle_decreased', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'shift': 1}, None),
    ]

    extrapolate_mode: bpy.props.EnumProperty(
        name='Strokes Extrapolate Mode',
        description='Controls how the strokes is extrapolated across selected edges',
        items=[
            ('FLAT',  'Flat',  'No changes to stroke', 0),
            ('ADAPT', 'Adapt', 'Adapt stroke to the angle of edges', 1),
        ],
        default='FLAT',
    )

    cut_count: bpy.props.IntProperty(
        name='Count',
        description='Number of vertices to create in a new cut',
        default=8,
        min=1,
        soft_max=32,
        max=256,
    )

    bridging_offset: bpy.props.IntProperty(
        name='Bridging Offset',
        description='Shift where bridging happens',
        default=0,
    )

    smooth_angle: bpy.props.FloatProperty(
        name='Angle',
        description='Smoothing angle',
        default=1.0,
        min=-0.5,
        soft_min=0.0,
        soft_max=1.0,
        max=1.5,
    )

    smooth_density0: bpy.props.FloatProperty(
        name='Density 0',
        description='Smoothing density 0',
        default=0.5,
        min=0.0,
        max=1.0,
    )
    smooth_density1: bpy.props.FloatProperty(
        name='Density 1',
        description='Smoothing density 1',
        default=0.5,
        min=0.0,
        max=1.0,
    )

    stroke_data = None

    @staticmethod
    def strokes_insert(context, radius, stroke3D, is_cycle, span_insert_mode, initial_cut_count, extrapolate_mode, initial_smooth_angle, initial_smooth_density0, initial_smooth_density1):
        RFOperator_Stroke_Insert.stroke_data = {
            'initial':           True,
            'action':            '',
            'radius':            radius,
            'stroke3D':          stroke3D,
            'is_cycle':          is_cycle,
            'span_insert_mode':  span_insert_mode,
            'cut_count':         initial_cut_count,
            'show_count':        True,
            'extrapolate':       extrapolate_mode,
            'show_extrapolate':  True,
            'bridging_offset':   0,
            'show_bridging_offset': False,
            'show_smoothness':    False,
            'smooth_angle':       initial_smooth_angle,
            'smooth_density0':    initial_smooth_density0,
            'smooth_density1':    initial_smooth_density1,
        }
        bpy.ops.retopoflow.strokes_insert('INVOKE_DEFAULT', True, extrapolate_mode=extrapolate_mode, smooth_angle=initial_smooth_angle, smooth_density0=initial_smooth_density0, smooth_density1=initial_smooth_density1)

    def draw(self, context):
        layout = self.layout
        colflow = layout.grid_flow(row_major=True, columns=2)
        data = RFOperator_Stroke_Insert.stroke_data

        if data['action']:
            colflow.label(text=f'Inserted')
            colflow.label(text=data['action'])

        if data['show_count']:
            colflow.label(text='Spans')
            colflow.prop(self, 'cut_count', text='')

        if data['show_extrapolate']:
            colflow.label(text='Extrapolate')
            colflow.prop(self, 'extrapolate_mode', text='')

        if data['show_bridging_offset']:
            colflow.label(text='Shift')
            colflow.prop(self, 'bridging_offset', text='')

        if data['show_smoothness']:
            colflow.label(text='Angle')
            colflow.prop(self, 'smooth_angle', text='')
            colflow.label(text='Density')
            row = colflow.row(align=True)
            row.prop(self, 'smooth_density0', text='')
            row.prop(self, 'smooth_density1', text='')

    def execute(self, context):
        data = RFOperator_Stroke_Insert.stroke_data
        stroke3D = [pt for pt in data['stroke3D'] if pt]
        if not stroke3D: return {'CANCELLED'}
        length3D = sum((p1-p0).length for (p0,p1) in iter_pairs(data['stroke3D'], data['is_cycle']))
        if length3D == 0: return {'CANCELLED'}

        try:
            logic = Strokes_Logic(
                context,
                data['initial'],
                data['radius'],
                stroke3D,
                data['is_cycle'],
                data['span_insert_mode'] if data['initial'] else 'FIXED',
                data['cut_count'] if data['initial'] else self.cut_count,
                self.extrapolate_mode,
                data['bridging_offset'] if data['initial'] else self.bridging_offset,
                self.smooth_angle,
                self.smooth_density0,
                self.smooth_density1,
            )

            if data['initial']:
                data['initial'] = False
                data['show_count'] = logic.show_count
                data['show_extrapolate'] = logic.show_extrapolate
                data['action'] = logic.show_action
                self.bridging_offset = logic.bridging_offset
                data['bridging_offset'] = self.bridging_offset
                data['show_bridging_offset'] = logic.show_bridging_offset
                data['show_smoothness'] = logic.show_smoothness
            else:
                data['extrapolate'] = self.extrapolate_mode
                self.bridging_offset = clamp(self.bridging_offset, logic.min_bridging_offset, logic.max_bridging_offset)
                data['bridging_offset'] = self.bridging_offset
            self.cut_count = logic.cut_count
            data['cut_count'] = self.cut_count
            data['smooth_angle'] = self.smooth_angle
            data['smooth_density0'] = self.smooth_density0
            data['smooth_density1'] = self.smooth_density1
        except Exception as e:
            # TODO: revisit how this issue (#1376) is handled.
            #       right now, the operator is simply cancelled, which could leave mesh in a weird state or remove
            #       recently added stroke!
            print(f'{type(self).__name__}.execute: Caught Exception {e}')
            debugger.print_exception()
            return {'CANCELLED'}

        return {'FINISHED'}


class RFOperator_Strokes_Overlay(RFOperator):
    bl_idname = 'retopoflow.strokes_overlay'
    bl_label = 'Strokes: Selected Overlay'
    bl_description = 'Overlays info about selected boundary edges'
    bl_options = { 'INTERNAL' }

    def init(self, context, event):
        self.depsgraph_version = None

    def update(self, context, event):
        is_done = (self.RFCore.selected_RFTool_idname != RFOperator_Strokes.bl_idname)
        return {'CANCELLED'} if is_done else {'PASS_THROUGH'}

    def draw_postpixel_overlay(self, context):
        M = context.edit_object.matrix_world
        rgn, r3d = context.region, context.region_data

        if self.depsgraph_version != self.RFCore.depsgraph_version:
            self.depsgraph_version = self.RFCore.depsgraph_version

            # find selected boundary strips
            bm, _ = get_bmesh_emesh(context)
            sel_bmes = [ bme for bme in bmops.get_all_selected_bmedges(bm) if bme.is_wire or bme.is_boundary ]
            strips, cycles = get_boundary_strips_cycles(sel_bmes)
            strips = [[bme_midpoint(bme) for bme in strip] for strip in strips]
            cycles = [[bme_midpoint(bme) for bme in cycle] for cycle in cycles]
            self.selected_boundaries = (strips, cycles)

        # draw info about each selected boundary strip
        for (lbl, boundaries) in zip(['Strip', 'Cycle'], self.selected_boundaries):
            for boundary in boundaries:
                mid = sum(boundary, Vector((0,0,0))) / len(boundary)
                midpt = min(boundary, key=lambda pt:(pt-mid).length)
                pos = location_3d_to_region_2d(rgn, r3d, M @ midpt)
                if not pos: continue
                text = f'{lbl}: {len(boundary)}'
                tw, th = Drawing.get_text_width(text), Drawing.get_text_height(text)
                pos -= Vector((tw / 2, -th / 2))
                Drawing.text_draw2D(text, pos.xy, color=(1,1,0,1), dropshadow=(0,0,0,0.75))


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
        name='Strokes Span Insert Mode',
        description='Controls span count when inserting',
        items=[
            ('BRUSH',   'Brush Size', 'Insert spans based on brush size', 0),
            ('FIXED',   'Fixed',      'Insert fixed number of spans',     1),
            ('AVERAGE', 'Average',    'Insert spans based on average length of selected edges (fallback: brush size)', 2),
        ],
        default='AVERAGE',
    )

    initial_cut_count: bpy.props.IntProperty(
        name='Initial Count',
        description='Number of vertices to create in a new cut',
        default=8,
        min=1,
        max=100,
    )

    extrapolate_mode: bpy.props.EnumProperty(
        name='Strokes Extrapolate Mode',
        description='Controls how the strokes is extrapolated across selected edges',
        items=[
            ('FLAT',  'Flat',  'No changes to stroke', 0),
            ('ADAPT', 'Adapt', 'Adapt stroke to the angle of edges', 1),
        ],
        default='FLAT',
    )

    initial_smooth_angle: bpy.props.FloatProperty(
        name='Initial Angle Smoothness',
        description='Smoothing angle',
        default=1.0,
        min=-0.5,
        soft_min=0.0,
        soft_max=1.0,
        max=1.5,
    )

    initial_smooth_density0: bpy.props.FloatProperty(
        name='Initial Density Smoothness 0',
        description='Smoothing density 0',
        default=0.5,
        min=0.0,
        max=1.0,
    )
    initial_smooth_density1: bpy.props.FloatProperty(
        name='Initial Density Smoothness 1',
        description='Smoothing density 1',
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

    def process_stroke(self, context, radius, stroke2D, is_cycle, snap_bmv0, snap_bmv1):
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
        if event.value in {'CLICK', 'DOUBLE_CLICK'}:
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



class RFTool_Strokes(RFTool_Base):
    bl_idname = "retopoflow.strokes"
    bl_label = "RetopoFlow Strokes"
    bl_description = "Insert edge strips and extrude edges into a patch"
    bl_icon = get_path_to_blender_icon('strokes')
    bl_widget = None
    bl_operator = 'retopoflow.strokes'

    rf_brush = RFBrush_Strokes()

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
            layout.label(text="Spans:")
            layout.prop(props_strokes, 'span_insert_mode', text='')
            if props_strokes.span_insert_mode == 'FIXED':
                layout.prop(props_strokes, 'initial_cut_count', text="Count")
            layout.prop(props_strokes, 'extrapolate_mode', text='')
        else:
            header, panel = layout.panel(idname='strokes_spans_panel', default_closed=False)
            header.label(text="Spans")
            if panel:
                panel.prop(props_strokes, 'span_insert_mode', text='Method')
                if props_strokes.span_insert_mode == 'FIXED':
                    panel.prop(props_strokes, 'initial_cut_count', text="Count")
                panel.prop(props_strokes, 'extrapolate_mode', text='Extrapolate')
                panel.prop(props_strokes, 'initial_smooth_angle', text='Angle')
                panel.prop(props_strokes, 'initial_smooth_density0', text='Density')
                panel.prop(props_strokes, 'initial_smooth_density1', text='Density')

        layout.prop(context.tool_settings, 'use_mesh_automerge', text='Auto Merge')
        layout.prop(props_translate, 'distance2d')

    @classmethod
    def activate(cls, context):
        cls.reseter = Reseter('Strokes')
        cls.reseter['context.tool_settings.use_mesh_automerge'] = True
        cls.reseter['context.tool_settings.mesh_select_mode'] = [True, True, False]
        cls.reseter['context.tool_settings.snap_elements_individual'] = {'FACE_PROJECT'}
        bpy.ops.retopoflow.strokes_overlay('INVOKE_DEFAULT')

    @classmethod
    def deactivate(cls, context):
        cls.reseter.reset()
