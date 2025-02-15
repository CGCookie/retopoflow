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
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d

from ..rfbrushes.stroke_brush import create_stroke_brush
from ..rfoverlays.quadstrip_selection_overlay import create_quadstrip_selection_overlay

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, bme_midpoint, get_boundary_strips_cycles
from ..common.drawing import Drawing
from ..common.icons import get_path_to_blender_icon
from ..common.maths import point_to_bvec4, view_forward_direction
from ..common.raycast import raycast_point_valid_sources, mouse_from_event
from ..common.raycast import is_point_hidden, nearest_point_valid_sources
from ..common.operator import (
    execute_operator,
    RFOperator, RFOperator_Execute,
    chain_rf_keymaps,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import clamp, Frame
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.utils import iter_pairs

from .polystrips_logic import PolyStrips_Logic

from ..rfoperators.transform import RFOperator_Translate_ScreenSpace

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel
from ..rfpanels.display_panel import draw_display_panel
from ..common.interface import draw_line_separator

from functools import wraps


RFBrush_Strokes, RFOperator_StrokesBrush_Adjust = create_stroke_brush(
    'polystrips_brush',
    'PolyStrips Brush',
    smoothing=0.9,
    snap=(False, False, True),
    radius=40,
)

class RFOperator_PolyStrips_Insert_Keymaps:
    # used to collect redo shortcuts, which is filled in by redo_ fns below...
    # note: cannot use RFOperator_PolyStrips_Insert.rf_keymaps, because RFOperator_PolyStrips_Insert
    #       is not yet created!
    rf_keymaps = []

class RFOperator_PolyStrips_Insert(RFOperator_PolyStrips_Insert_Keymaps, RFOperator_Execute):
    bl_idname = 'retopoflow.polystrips_insert'
    bl_label = 'Insert PolyStrip'
    bl_description = 'Insert quad strip'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    logic = None

    cut_count: bpy.props.IntProperty(
        name='Count',
        description='Number of vertices to create in a new quad strip',
        default=8,
        min=2,
        max=256,
    )
    width: bpy.props.FloatProperty(
        name='Width',
        description='Width of quad strip',
        min=0.0001,
    )

    @staticmethod
    def polystrips_insert(context, radius2D, stroke3D, is_cycle, snap_bmf0, snap_bmf1):
        RFOperator_PolyStrips_Insert.logic = PolyStrips_Logic(
            context,
            radius2D,
            stroke3D,
            is_cycle,
            snap_bmf0,
            snap_bmf1,
        )
        bpy.ops.retopoflow.polystrips_insert(
            'INVOKE_DEFAULT', True,
            cut_count=RFOperator_PolyStrips_Insert.logic.count,
            width=RFOperator_PolyStrips_Insert.logic.width,
        )

    @staticmethod
    def polystrips_reinsert(context):
        bpy.ops.retopoflow.polystrips_insert(
            'INVOKE_DEFAULT', True,
            cut_count=RFOperator_PolyStrips_Insert.logic.count,
            width=RFOperator_PolyStrips_Insert.logic.width,
        )

    def draw(self, context):
        layout = self.layout
        grid = layout.grid_flow(row_major=True, columns=2)
        logic = RFOperator_PolyStrips_Insert.logic

        if logic.action:
            grid.label(text=f'Inserted')
            grid.label(text=logic.action)

        grid.label(text=f'Count')
        grid.prop(self, 'cut_count', text='')
        grid.label(text=f'Width')
        grid.prop(self, 'width', text='')

    def execute(self, context):
        try:
            RFOperator_PolyStrips_Insert.logic.count = self.cut_count
            RFOperator_PolyStrips_Insert.logic.width = self.width
            RFOperator_PolyStrips_Insert.logic.create(context)
            self.cut_count = RFOperator_PolyStrips_Insert.logic.count
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
        # add keymap to RFOperator_PolyStrips_Insert.rf_keymaps
        # note: still creating RFOperator_PolyStrips_Insert, so using RFOperator_PolyStrips_Insert_Keymaps.rf_keymaps
        RFOperator_PolyStrips_Insert_Keymaps.rf_keymaps.append( (f'retopoflow.{idname}', keymap, None) )
        def wrapper(fn):
            @execute_operator(idname, description, options={'INTERNAL'})
            @wraps(fn)
            def wrapped(context):
                last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
                if last_op != RFOperator_PolyStrips_Insert.bl_label: return
                fn(context, RFOperator_PolyStrips_Insert.logic)
                bpy.ops.ed.undo()
                RFOperator_PolyStrips_Insert.polystrips_reinsert(context)
            return wrapped
        return wrapper

    @create_redo_operator('polystrips_insert_cut_count_decreased', 'Reinsert quad strip with decreased count', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1})
    def decrease_cut_count(context, logic):
        logic.count -= 1

    @create_redo_operator('polystrips_insert_cut_count_increased', 'Reinsert quad strip with increased count', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'ctrl': 1})
    def increase_cut_count(context, logic):
        logic.count += 1

    @create_redo_operator('polystrips_insert_width_decreased', 'Reinsert quad strip with decreased width', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'shift': 1})
    def decrease_cut_count(context, logic):
        logic.width *= 0.95

    @create_redo_operator('polystrips_insert_width_increased', 'Reinsert quad strip with increased width', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'shift': 1})
    def increase_cut_count(context, logic):
        logic.width /= 0.95


class RFOperator_PolyStrips_Edit(RFOperator):
    bl_idname = 'retopoflow.polystrips_edit'
    bl_label = 'Insert PolyStrip'
    bl_description = 'Insert quad strip'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    rf_keymaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS'}, None),
    ]

    @classmethod
    def can_start(cls, context):
        return bool(RFTool_PolyStrips.rf_overlay.instance.hovering)

    def init(self, context, event):
        self.curves = RFTool_PolyStrips.rf_overlay.instance.curves
        self.hovering = RFTool_PolyStrips.rf_overlay.instance.hovering
        self.strips_indices = RFTool_PolyStrips.rf_overlay.instance.strips_indices

        RFTool_PolyStrips.rf_overlay.pause_update()
        RFTool_PolyStrips.rf_overlay.instance.depsgraph_version = None

        mouse = mouse_from_event(event)

        self.bm, self.em = get_bmesh_emesh(bpy.context, ensure_lookup_tables=True)
        self.M, self.Mi = context.edit_object.matrix_world, context.edit_object.matrix_world.inverted()
        self.fwd = (self.Mi @ view_forward_direction(context)).normalized()
        self.curve = self.curves[self.hovering[0]]
        self.curve.tessellate_uniform()
        strip_inds = self.strips_indices[self.hovering[0]]
        bmfs = [ self.bm.faces[i] for i in strip_inds]
        bmvs = { bmv for bmf in bmfs for bmv in bmf.verts }
        # all data is local to edit!
        data = {}
        for bmv in bmvs:
            t = self.curve.approximate_t_at_point_tessellation(bmv.co)
            o = self.curve.eval(t)
            z = Vector(self.curve.eval_derivative(t)).normalized()
            f = Frame(o, x=self.fwd, z=z)
            data[bmv.index] = (t, f.w2l_point(bmv.co), Vector(bmv.co))
        self.grab = {
            'mouse':    Vector(mouse),
            'curve':    self.hovering[0],
            'handle':   self.hovering[1],
            'prev':     self.hovering[2],
            'data':     data,
            'matrices': [self.M, self.Mi],
            'fwd':      self.fwd,
        }

    def finish(self, context):
        RFTool_PolyStrips.rf_overlay.unpause_update()

    def update(self, context, event):
        curve = self.curve
        data = self.grab['data']
        bm, em = self.bm, self.em

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}

        if event.type in {'ESC', 'RIGHTMOUSE'}:
            curve.p0, curve.p1, curve.p2, curve.p3 = self.grab['prev']
            for bmv_idx in data:
                bm.verts[bmv_idx].co = data[bmv_idx][2]
            bmesh.update_edit_mesh(em)
            context.area.tag_redraw()
            return {'CANCELLED'}

        mouse = mouse_from_event(event)
        delta = Vector(mouse) - self.grab['mouse']
        rgn, r3d = context.region, context.region_data
        M, Mi = self.grab['matrices']
        fwd = self.grab['fwd']

        def xform(pt0_edit):
            pt0_world  = M @ pt0_edit
            pt0_screen = location_3d_to_region_2d(rgn, r3d, pt0_world)
            pt1_screen = pt0_screen + delta
            pt1_world  = region_2d_to_location_3d(rgn, r3d, pt1_screen, pt0_world)
            pt1_edit   = Mi @ pt1_world
            return pt1_edit

        p0, p1, p2, p3 = self.grab['prev']
        curve = self.curves[self.grab['curve']]
        if self.grab['handle'] == 0: curve.p0, curve.p1 = xform(p0), xform(p1)
        if self.grab['handle'] == 1: curve.p1 = xform(p1)
        if self.grab['handle'] == 2: curve.p2 = xform(p2)
        if self.grab['handle'] == 3: curve.p2, curve.p3 = xform(p2), xform(p3)

        for bmv_idx in data:
            bmv = bm.verts[bmv_idx]
            t, pt, _ = data[bmv_idx]
            o = curve.eval(t)
            z = Vector(curve.eval_derivative(t)).normalized()
            f = Frame(o, x=fwd, z=z)
            bmv.co = nearest_point_valid_sources(context, M @ f.l2w_point(pt), world=False)

        bmesh.update_edit_mesh(em)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}


class RFOperator_PolyStrips(RFOperator):
    bl_idname = 'retopoflow.polystrips'
    bl_label = 'PolyStrips'
    bl_description = 'Insert quad strip'
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


    stroke_smoothing: bpy.props.FloatProperty(
        name='Stroke Smoothing',
        description='Stroke smoothing factor.  Zero means no smoothing, and higher means more smoothing.',
        get=lambda _: RFBrush_Strokes.get_stroke_smooth(),
        set=lambda _,v: RFBrush_Strokes.set_stroke_smooth(v),
        min=0.00,
        soft_max=0.95,
        max=1.0,
    )


    def init(self, context, event):
        RFTool_PolyStrips.rf_brush.set_operator(self)
        RFTool_PolyStrips.rf_brush.reset_nearest(context)
        RFTool_PolyStrips.rf_overlay.pause_overlay()
        self.tickle(context)

    def finish(self, context):
        RFTool_PolyStrips.rf_brush.set_operator(None)
        RFTool_PolyStrips.rf_brush.reset_nearest(context)
        RFTool_PolyStrips.rf_overlay.unpause_overlay()

    def reset(self):
        RFTool_PolyStrips.rf_brush.reset()

    def process_stroke(self, context, radius2D, stroke2D, is_cycle, snapped_geo):
        snap_bmf0, snap_bmf1 = snapped_geo[2]
        stroke3D = [raycast_point_valid_sources(context, pt, world=False) for pt in stroke2D]
        RFOperator_PolyStrips_Insert.polystrips_insert(
            context,
            radius2D,
            stroke3D,
            is_cycle,
            snap_bmf0, snap_bmf1,
        )

    def update(self, context, event):
        if event.value in {'CLICK', 'DOUBLE_CLICK'}:
            # prevents object selection with Ctrl+LMB Click
            return {'RUNNING_MODAL'}

        if not RFTool_PolyStrips.rf_brush.is_stroking():
            if not event.ctrl:
                Cursors.restore()
                self.tickle(context)
                return {'FINISHED'}

        Cursors.set('CROSSHAIR')
        return {'PASS_THROUGH'}  # TODO: see below
        # TODO: allow only some operators to work but not all
        #       however, need a way to not hardcode LEFTMOUSE!
        return {'PASS_THROUGH'} if event.type in {'MOUSEMOVE', 'LEFTMOUSE'} else {'RUNNING_MODAL'}


RFOperator_PolyStrips_Overlay = create_quadstrip_selection_overlay(
    'RFOperator_PolyStrips_Selection_Overlay',
    'retopoflow.polystrips',  # must match RFTool_base.bl_idname
    'polystrips_overlay',
    'PolyStrips Selected Overlay',
    True,
)


class RFTool_PolyStrips(RFTool_Base):
    bl_idname = "retopoflow.polystrips"
    bl_label = "PolyStrips"
    bl_description = "Insert quad strip"
    bl_icon = get_path_to_blender_icon('polystrips')
    bl_widget = None
    bl_operator = 'retopoflow.polystrips'

    rf_brush = RFBrush_Strokes()
    rf_overlay = RFOperator_PolyStrips_Overlay

    bl_keymap = chain_rf_keymaps(
        RFOperator_PolyStrips,
        RFOperator_PolyStrips_Insert,
        RFOperator_PolyStrips_Edit,
        RFOperator_StrokesBrush_Adjust,
        RFOperator_Translate_ScreenSpace,
    )

    def draw_settings(context, layout, tool):
        props_polystrips = tool.operator_properties(RFOperator_PolyStrips.bl_idname)
        props_translate = tool.operator_properties(RFOperator_Translate_ScreenSpace.bl_idname)

        if context.region.type == 'TOOL_HEADER':
            layout.label(text="Insert:")
            layout.prop(props_polystrips, 'stroke_smoothing', text='Stroke')
            row = layout.row(align=True)
            layout.popover('RF_PT_TweakCommon')
            row = layout.row(align=True)
            row.popover('RF_PT_MeshCleanup', text='Clean Up')
            row.operator("retopoflow.meshcleanup", text='', icon='PLAY')
            layout.popover('RF_PT_Display', text='', icon='OPTIONS')
        else:
            header, panel = layout.panel(idname='polystrips_spans_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                pass
            draw_tweaking_panel(context, layout)
            draw_cleanup_panel(context, layout)
            draw_display_panel(context, layout)

    @classmethod
    def activate(cls, context):
        cls.resetter = Resetter('PolyStrips')
        cls.resetter['context.tool_settings.use_mesh_automerge'] = True
        cls.resetter['context.tool_settings.mesh_select_mode'] = [False, False, True]
        cls.resetter.store('context.tool_settings.snap_elements_base')
        cls.resetter['context.tool_settings.snap_elements_individual'] = {'FACE_PROJECT'}

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
