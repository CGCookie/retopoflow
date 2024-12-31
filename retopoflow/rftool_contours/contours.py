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
from ..rfbrushes.cut_brush import RFBrush_Cut
from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, nearest_bmv_world, nearest_bme_world, bme_midpoint, get_boundary_strips_cycles
from ..common.drawing import Drawing
from ..common.icons import get_path_to_blender_icon
from ..common.maths import view_forward_direction
from ..common.operator import (
    invoke_operator, execute_operator,
    RFOperator, RFRegisterClass, RFOperator_Execute,
    chain_rf_keymaps, wrap_property,
)
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event, nearest_point_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.reseter import Reseter

from ..rfoperators.transform import RFOperator_Translate_BoundaryLoop

from .contours_logic import Contours_Logic
from functools import wraps


class RFOperator_Contours_Insert_Keymaps:
    # used to collect redo shortcuts, which is filled in by redo_ fns below...
    # note: cannot use RFOperator_Contours_Insert.rf_keymaps, because RFOperator_Contours_Insert
    #       is not yet created!
    rf_keymaps = []

class RFOperator_Contours_Insert(RFOperator_Contours_Insert_Keymaps, RFOperator_Execute):
    bl_idname = 'retopoflow.contours_insert'
    bl_label = 'Contours: Insert new stroke'
    bl_description = 'Insert cut and extrude edges into a patch'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    span_count: bpy.props.IntProperty(
        name='Span Count',
        description='Number of vertices to create in a new cut',
        default=8,
        min=3,
        max=100,
    )

    contours_data = None

    @staticmethod
    def contours_insert(context, hit, plane, initial_span_count):
        RFOperator_Contours_Insert.contours_data = {
            'initial':         True,
            'action':          '',
            'hit':             hit,
            'plane':           plane,
            'show_span_count': False,
            'span_count':      initial_span_count,
        }
        RFOperator_Contours_Insert.contours_reinsert(context)

    @staticmethod
    def contours_reinsert(context):
        data = RFOperator_Contours_Insert.contours_data
        bpy.ops.retopoflow.contours_insert(
            'INVOKE_DEFAULT', True,
            span_count=data['span_count'],
        )

    def draw(self, context):
        layout = self.layout
        grid = layout.grid_flow(row_major=True, columns=2)
        data = RFOperator_Contours_Insert.contours_data

        if data['action']:
            grid.label(text=f'Inserted')
            grid.label(text=data['action'])

        if data['show_span_count']:
            grid.label(text=f'Spans')
            grid.prop(self, 'span_count', text='')

    def execute(self, context):
        data = RFOperator_Contours_Insert.contours_data
        try:
            logic = Contours_Logic(
                context,
                data['initial'],
                data['hit'],
                data['plane'],
                data['span_count'] if data['initial'] else self.span_count,
            )
            if data['initial']:
                data['initial'] = False
            data['action'] = logic.action
            data['show_span_count'] = logic.show_span_count
            data['span_count'] = logic.span_count
        except Exception as e:
            # TODO: revisit how this issue (#1376) is handled.
            #       right now, the operator is simply cancelled, which could leave mesh in a weird state or remove
            #       recently added stroke!
            print(f'{type(self).__name__}.execute: Caught Exception {e}')
            debugger.print_exception()
            return {'CANCELLED'}

        return {'FINISHED'}

    @staticmethod
    def create_redo_operator(idname, description, keymap):
        # add keymap to RFOperator_Contours_Insert.rf_keymaps
        # note: still creating RFOperator_Contours_Insert, so using RFOperator_Contours_Insert_Keymaps.rf_keymaps
        RFOperator_Contours_Insert_Keymaps.rf_keymaps.append( (f'retopoflow.{idname}', keymap, None) )
        def wrapper(fn):
            @execute_operator(idname, description, options={'INTERNAL'})
            @wraps(fn)
            def wrapped(context):
                last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
                if last_op != RFOperator_Contours_Insert.bl_label: return
                fn(context, RFOperator_Contours_Insert.contours_data)
                bpy.ops.ed.undo()
                RFOperator_Contours_Insert.contours_reinsert(context)
            return wrapped
        return wrapper

    @create_redo_operator('contours_insert_spans_decreased', 'Reinsert cut with decreased spans', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1})
    def decrease_spans(context, data):
        data['span_count'] -= 1

    @create_redo_operator('contours_insert_spans_increased', 'Reinsert cut with increased spans', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'ctrl': 1})
    def increase_spans(context, data):
        data['span_count'] += 1


class RFOperator_Contours_Overlay(RFOperator):
    bl_idname = 'retopoflow.contours_overlay'
    bl_label = 'Contours: Selected Overlay'
    bl_description = 'Overlays info about selected boundary edges'
    bl_options = { 'INTERNAL' }

    def init(self, context, event):
        self.depsgraph_version = None

    def update(self, context, event):
        is_done = (self.RFCore.selected_RFTool_idname != RFOperator_Contours.bl_idname)
        return {'CANCELLED'} if is_done else {'PASS_THROUGH'}

    def draw_postpixel_overlay(self, context):
        is_done = (self.RFCore.selected_RFTool_idname != RFOperator_Contours.bl_idname)
        if is_done: return

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



class RFOperator_Contours(RFOperator):
    bl_idname = 'retopoflow.contours'
    bl_label = 'Contours'
    bl_description = 'Retopologize cylindrical forms, like arms and legs'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
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

    initial_span_count: bpy.props.IntProperty(
        name='Initial Count',
        description='Number of vertices to create in a new cut',
        default=8,
        min=3,
        max=100,
    )

    def init(self, context, event):
        RFTool_Contours.rf_brush.set_operator(self)
        self.tickle(context)

    def finish(self, context):
        RFTool_Contours.rf_brush.set_operator(None)

    def reset(self):
        RFTool_Contours.rf_brush.reset()

    def process_cut(self, context, hit, plane):
        RFOperator_Contours_Insert.contours_insert(context, hit, plane, self.initial_span_count)

    def update(self, context, event):
        if event.value in {'CLICK', 'DOUBLE_CLICK'}:
            return {'RUNNING_MODAL'}

        if RFTool_Contours.rf_brush.is_cancelled:
            Cursors.restore()
            self.tickle(context)
            return {'CANCELLED'}
        if not RFTool_Contours.rf_brush.is_stroking():
            if not event.ctrl:
                Cursors.restore()
                self.tickle(context)
                return {'FINISHED'}

        Cursors.set('CROSSHAIR')
        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!


class RFTool_Contours(RFTool_Base):
    bl_idname = "retopoflow.contours"
    bl_label = "RetopoFlow Contours"
    bl_description = "Retopologize cylindrical forms, like arms and legs"
    bl_icon = get_path_to_blender_icon('contours')
    bl_widget = None
    bl_operator = 'retopoflow.contours'

    rf_brush = RFBrush_Cut()

    bl_keymap = chain_rf_keymaps(
        RFOperator_Contours,
        RFOperator_Contours_Insert,
        RFOperator_Translate_BoundaryLoop,
    )

    def draw_settings(context, layout, tool):
        props_contours = tool.operator_properties(RFOperator_Contours.bl_idname)

        if context.region.type == 'TOOL_HEADER':
            layout.label(text='Cut:')
            layout.prop(props_contours, 'initial_span_count')
        else:
            header, panel = layout.panel(idname='contours_cut_panel', default_closed=False)
            header.label(text="Cut")
            if panel:
                panel.prop(props_contours, 'initial_span_count')

    @classmethod
    def activate(cls, context):
        cls.reseter = Reseter('Contours')
        cls.reseter['context.tool_settings.use_mesh_automerge'] = False
        cls.reseter['context.tool_settings.snap_elements_individual'] = {'FACE_NEAREST'}
        bpy.ops.retopoflow.contours_overlay('INVOKE_DEFAULT')

    @classmethod
    def deactivate(cls, context):
        cls.reseter.reset()
