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
from ..common.bmesh import get_bmesh_emesh, nearest_bmv_world, nearest_bme_world
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
from ..common.maths import view_forward_direction, lerp
from ..common.operator import (
    invoke_operator, execute_operator,
    RFOperator, RFOperator_Execute, RFRegisterClass,
    chain_rf_keymaps, wrap_property,
)
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event, nearest_point_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common import gpustate
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.maths import Color, Frame
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D
from ...addon_common.common.reseter import Reseter

from .strokes_logic import Strokes_Logic

from ..rfoperators.transform import RFOperator_Translate_BoundaryLoop


@execute_operator('strokes_insert_decreased', 'Reinsert stroke with decreased spans')
def strokes_spans_decrease(context):
    last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
    if last_op != RFOperator_Stroke_Insert.bl_label: return
    data = RFOperator_Stroke_Insert.stroke_data
    data['cut_count'] = max(1, data['cut_count'] - 1)
    bpy.ops.ed.undo()
    bpy.ops.retopoflow.strokes_insert('INVOKE_DEFAULT', True, extrapolate_mode=data['extrapolate'], cut_count=data['cut_count'])

@execute_operator('strokes_insert_increased', 'Reinsert stroke with increased spans')
def strokes_spans_increase(context):
    last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
    if last_op != RFOperator_Stroke_Insert.bl_label: return
    data = RFOperator_Stroke_Insert.stroke_data
    data['cut_count'] += 1
    bpy.ops.ed.undo()
    bpy.ops.retopoflow.strokes_insert('INVOKE_DEFAULT', True, extrapolate_mode=data['extrapolate'], cut_count=data['cut_count'])


class RFOperator_Stroke_Insert(RFOperator_Execute):
    bl_idname = 'retopoflow.strokes_insert'
    bl_label = 'Strokes: Insert new stroke'
    bl_description = 'Insert edge strips and extrude edges into a patch'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    rf_keymaps = [
        ('retopoflow.strokes_insert_increased', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'ctrl': 1}, None),
        ('retopoflow.strokes_insert_decreased', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1}, None),
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

    stroke_data = None

    @staticmethod
    def strokes_insert(context, radius, stroke3D, is_cycle, span_insert_mode, initial_cut_count, extrapolate_mode):
        RFOperator_Stroke_Insert.stroke_data = {
            'initial':           True,
            'radius':            radius,
            'stroke3D':          stroke3D,
            'is_cycle':          is_cycle,
            'span_insert_mode':  span_insert_mode,
            'cut_count':         initial_cut_count,
            'extrapolate':       extrapolate_mode,
        }
        bpy.ops.retopoflow.strokes_insert('INVOKE_DEFAULT', True, extrapolate_mode=extrapolate_mode)

    # def draw(self, context):
    #     layout = self.layout
    #     layout.prop(self, 'extrapolate_mode')

    def execute(self, context):
        data = RFOperator_Stroke_Insert.stroke_data
        stroke3D = [pt for pt in data['stroke3D'] if pt]
        if not stroke3D:
            return {'CANCELLED'}

        logic = Strokes_Logic(
            context,
            data['radius'],
            stroke3D,
            data['is_cycle'],
            data['span_insert_mode'] if data['initial'] else 'FIXED',
            data['cut_count'] if data['initial'] else self.cut_count,
            self.extrapolate_mode,
        )
        if data['initial']:
            self.cut_count = logic.cut_count
            data['cut_count'] = self.cut_count
            data['initial'] = False
        else:
            data['extrapolate'] = self.extrapolate_mode

        return {'FINISHED'}


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
            ('BRUSH', 'Brush Size', 'Insert spans based on brush size', 0),
            ('FIXED', 'Fixed',      'Insert fixed number of spans',     1),
        ],
        default='BRUSH',
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


    def init(self, context, event):
        RFTool_Strokes.rf_brush.set_operator(self, context)
        self.tickle(context)

    def finish(self, context):
        RFTool_Strokes.rf_brush.set_operator(None, context)

    def reset(self):
        print('STROKES RESET')
        RFTool_Strokes.rf_brush.reset()

    def process_stroke(self, context, radius, stroke2D, is_cycle, snap_bmv0, snap_bmv1):
        stroke3D = [raycast_point_valid_sources(context, pt, world=False) for pt in stroke2D]
        RFOperator_Stroke_Insert.strokes_insert(context, radius, stroke3D, is_cycle, self.span_insert_mode, self.initial_cut_count, self.extrapolate_mode)

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

    def draw_postpixel(self, context):
        # self.logic.draw(context)
        pass



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
        # RFOperator_Translate_BoundaryLoop,
    )

    def draw_settings(context, layout, tool):
        props = tool.operator_properties(RFOperator_Strokes.bl_idname)
        if context.region.type == 'TOOL_HEADER':
            layout.label(text="Spans:")
            layout.prop(props, 'span_insert_mode', text='')
            if props.span_insert_mode == 'FIXED':
                layout.prop(props, 'initial_cut_count', text="Count")
            layout.prop(props, 'extrapolate_mode', text='')
        else:
            header, panel = layout.panel(idname='strokes_spans_panel', default_closed=False)
            header.label(text="Spans")
            if panel:
                panel.prop(props, 'span_insert_mode', text='Method')
                if props.span_insert_mode == 'FIXED':
                    panel.prop(props, 'initial_cut_count', text="Count")
                panel.prop(props, 'extrapolate_mode', text='Extrapolate')

    @classmethod
    def activate(cls, context):
        cls.reseter = Reseter('Strokes')
        cls.reseter['context.tool_settings.use_mesh_automerge'] = True
        cls.reseter['context.tool_settings.snap_elements_individual'] = {'FACE_PROJECT'}

    @classmethod
    def deactivate(cls, context):
        cls.reseter.reset()
