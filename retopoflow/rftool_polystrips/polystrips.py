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
import math
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d

from ..rfbrushes.stroke_brush import create_stroke_brush
from ..rfoverlays.quadstrip_selection_overlay import create_quadstrip_selection_overlay

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, bme_midpoint, get_boundary_strips_cycles
from ..common.drawing import Drawing
from ..common.icons import get_path_to_blender_icon
from ..common.maths import point_to_bvec4, view_forward_direction, proportional_edit, xform_direction, view_right_direction
from ..common.raycast import raycast_point_valid_sources, mouse_from_event, size2D_to_size
from ..common.raycast import is_point_hidden, nearest_point_valid_sources, raycast_valid_sources
from ..common.operator import (
    execute_operator,
    RFOperator, RFOperator_Execute,
    chain_rf_keymaps,
    wrap_property, poll_retopoflow,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common import gpustate
from ...addon_common.common.blender import event_modifier_check
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import clamp, Frame, Direction2D, Color, sign_threshold
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.utils import iter_pairs

from .polystrips_logic import PolyStrips_Logic

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

import heapq
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

    rf_keymaps = []


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
    )


    @staticmethod
    def polystrips_insert(context, radius2D, stroke3D, is_cycle, length2D, snap_bmf0, snap_bmf1, split_angle, mirror_correct):
        logic = RFOperator_PolyStrips_Insert.logic
        RFOperator_PolyStrips_Insert.logic = PolyStrips_Logic(
            context,
            radius2D,
            stroke3D,
            is_cycle,
            length2D,
            snap_bmf0,
            snap_bmf1,
            split_angle,
            mirror_correct,
        )
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
        i = RFTool_PolyStrips.rf_overlay.instance
        return False if not i else getattr(i, 'hovering', False)

    def init(self, context, event):
        RFOperator_PolyStrips_Insert.logic = None

        self.curves = RFTool_PolyStrips.rf_overlay.instance.curves
        self.hovering = RFTool_PolyStrips.rf_overlay.instance.hovering
        self.strips_indices = RFTool_PolyStrips.rf_overlay.instance.strips_indices

        RFTool_PolyStrips.rf_overlay.pause_update()
        RFTool_PolyStrips.rf_overlay.instance.depsgraph_version = None

        mouse = mouse_from_event(event)
        M, Mi = context.edit_object.matrix_world, context.edit_object.matrix_world.inverted()

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

        self.bm, self.em = get_bmesh_emesh(bpy.context, ensure_lookup_tables=True)
        self.M, self.Mi = M, Mi
        self.fwd = xform_direction(Mi, view_forward_direction(context))
        self.right = xform_direction(Mi, view_right_direction(context))
        self.curve = self.curves[self.hovering[0]]
        self.curve.tessellate_uniform()
        strip_inds = self.strips_indices[self.hovering[0]]
        bmfs = [ self.bm.faces[i] for i in strip_inds]
        bmvs = [ bmv for bmf in bmfs for bmv in bmf.verts ]
        # gather neighboring geo
        if bmvs and use_proportional_edit:
            connected_only = context.tool_settings.use_proportional_connected
            if connected_only:
                all_bmvs = {}
                # NOTE: an exception is thrown if BMVerts are compared, so we are adding in bmv.index
                #       into tuple to break ties with same distances before bmvs are compared
                queue = [(0, bmv.index, bmv) for bmv in bmvs]
                while queue:
                    (d, _, bmv) = heapq.heappop(queue)
                    if bmv in all_bmvs: continue
                    all_bmvs[bmv] = d
                    for bmf in bmv.link_faces:
                        for bmv_ in bmf.verts:
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
        if use_proportional_edit:
            bmv_selected_count = 0
            bmv_merged_2d_coords = Vector((0.0, 0.0))
            bmv_merged_3d_coords = Vector((0.0, 0.0, 0.0))
            rgn, r3d = context.region, context.region_data
        for (bmv, distance) in all_bmvs.items():
            t = self.curve.approximate_t_at_point_tessellation(bmv.co)
            o = self.curve.eval(t)
            z = Vector(self.curve.eval_derivative(t)).normalized()
            f = Frame(o, x=self.fwd, z=z)
            data[bmv.index] = (
                t,
                f.w2l_point(bmv.co),
                Vector(bmv.co),
                distance,
            )
            # Proportional Edit Origin.
            if use_proportional_edit and bmv.select:
                bmv_selected_count += 1
                co_world = M @ bmv.co
                bmv_merged_3d_coords += co_world
                screen_co = location_3d_to_region_2d(rgn, r3d, co_world)
                if screen_co:
                    bmv_merged_2d_coords += screen_co

        if use_proportional_edit:
            self.selection_origin_3d = bmv_merged_3d_coords / bmv_selected_count  # used to calculate proportional edit radius.
            self.selection_origin_2d = bmv_merged_2d_coords / bmv_selected_count  # used for the 2D circle origin.

        self.grab = {
            'mouse':    Vector(mouse),
            'current':  Vector(mouse),
            'curve':    self.hovering[0],
            'handle':   self.hovering[1],
            'prev':     self.hovering[2],
            'data':     data,
            'matrices': [self.M, self.Mi],
            'fwd':      self.fwd,
            'only':     None,
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
                t, pt_curve_orig, pt_edit_orig, factor = data[bmv_idx]
                bm.verts[bmv_idx].co = pt_edit_orig
            bmesh.update_edit_mesh(em)
            context.area.tag_redraw()
            return {'CANCELLED'}
        if event.type in {'WHEELDOWNMOUSE', 'WHEELUPMOUSE'}:
            if event.type in {'WHEELUPMOUSE'}:
                context.tool_settings.proportional_distance *= 0.90
            if event.type in {'WHEELDOWNMOUSE'}:
                context.tool_settings.proportional_distance /= 0.90
            if self.grab['only']:
                for bmv_idx in self.grab['only']:
                    bm.verts[bmv_idx].co = data[bmv_idx][2]
            self.grab['only'] = None

        mouse = mouse_from_event(event)
        self.grab['current'] = mouse
        delta = Vector(mouse) - self.grab['mouse']
        rgn, r3d = context.region, context.region_data
        M, Mi = self.grab['matrices']
        fwd = self.grab['fwd']
        prop_use = context.tool_settings.use_proportional_edit
        prop_dist_world = context.tool_settings.proportional_distance
        prop_falloff = context.tool_settings.proportional_edit_falloff

        def xform(pt0_cur_edit, pt1_cur_edit=None):
            pt0_cur_world  = M @ pt0_cur_edit
            pt0_cur_screen = location_3d_to_region_2d(rgn, r3d, pt0_cur_world)
            pt0_new_screen = pt0_cur_screen + delta
            if pt1_cur_edit is None:
                pt0_new_world = region_2d_to_location_3d(rgn, r3d, pt0_new_screen, pt0_cur_world)
                pt0_new_edit  = Mi @ pt0_new_world
                return pt0_new_edit
            pt0_new_world = raycast_point_valid_sources(context, pt0_new_screen)
            if not pt0_new_world: return (pt0_cur_edit, pt1_cur_edit)
            pt0_new_edit = Mi @ pt0_new_world
            pt1_new_edit = pt1_cur_edit + (pt0_new_edit - pt0_cur_edit)
            return (pt0_new_edit, pt1_new_edit)

        p0, p1, p2, p3 = self.grab['prev']
        curve = self.curves[self.grab['curve']]
        if self.grab['handle'] == 0: curve.p0, curve.p1 = xform(p0, p1)
        if self.grab['handle'] == 1: curve.p1 = xform(p1)
        if self.grab['handle'] == 2: curve.p2 = xform(p2)
        if self.grab['handle'] == 3: curve.p3, curve.p2 = xform(p3, p2)

        if self.grab['only'] is None:
            self.grab['only'] = [
                bmv_idx
                for bmv_idx in data
                if data[bmv_idx][3] <= prop_dist_world
            ]

        for bmv_idx in self.grab['only']:
            bmv = bm.verts[bmv_idx]
            t, pt_curve_orig, pt_edit_orig, distance = data[bmv_idx]
            if distance > prop_dist_world: continue
            if prop_use:
                dist = max(1 - distance / prop_dist_world, 0)
                factor = proportional_edit(prop_falloff, dist)
            else:
                factor = 1
            o = curve.eval(t)
            z = Vector(curve.eval_derivative(t)).normalized()
            f = Frame(o, x=fwd, z=z)
            pt_edit_new = M @ f.l2w_point(pt_curve_orig)
            pt_edit_new = pt_edit_orig + (pt_edit_new - pt_edit_orig) * factor
            co = nearest_point_valid_sources(context, pt_edit_new, world=False)

            if self.mirror:
                t = self.mirror_threshold
                zero = {
                    'x': ('x' in self.mirror and (sign_threshold(co.x, t.x) != sign_threshold(pt_edit_orig.x, t.x) or sign_threshold(pt_edit_orig.x, t.x) == 0)),
                    'y': ('y' in self.mirror and (sign_threshold(co.y, t.y) != sign_threshold(pt_edit_orig.y, t.y) or sign_threshold(pt_edit_orig.y, t.y) == 0)),
                    'z': ('z' in self.mirror and (sign_threshold(co.z, t.z) != sign_threshold(pt_edit_orig.z, t.z) or sign_threshold(pt_edit_orig.z, t.z) == 0)),
                }
                # iteratively zero out the component
                for _ in range(1000):
                    d = 0
                    if zero['x']: co.x, d = co.x * 0.95, max(abs(co.x), d)
                    if zero['y']: co.y, d = co.y * 0.95, max(abs(co.y), d)
                    if zero['z']: co.z, d = co.z * 0.95, max(abs(co.z), d)
                    co_world = M @ Vector((*co, 1.0))
                    co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True)
                    co = Mi @ co_world_snapped
                    if d < 0.001: break  # break out if change was below threshold
                if zero['x']: co.x = 0
                if zero['y']: co.y = 0
                if zero['z']: co.z = 0

            bmv.co = co


        bmesh.update_edit_mesh(em)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}


    def draw_postpixel(self, context):
        ''' Draw proportional edit circle in 2D space. '''
        if not context.tool_settings.use_proportional_edit: return
        gpustate.blend('ALPHA')
        rgn, r3d = context.region, context.region_data

        pt = self.selection_origin_3d + context.tool_settings.proportional_distance * self.right
        radius = location_3d_to_region_2d(rgn, r3d, pt)[0] - self.selection_origin_2d[0]
        if self.grab['handle'] in {0, 3}:
            # Drag handles.
            center = self.selection_origin_2d
        else:
            # Curve manipulation handles.
            center = location_3d_to_region_2d(rgn, r3d, self.grab['prev'][self.grab['handle']])

        # Internally Blender proportional editing circle is based on the 3d view grid color.
        # default grid color: Color((0.33,0.33,0.33,0.5))
        col_off = 20/255
        color_in = Color((0.33+col_off,0.33+col_off,0.33+col_off,1.0))  # lighter than grid color. full alpha
        color_out = Color((0.33-col_off,0.33-col_off,0.33-col_off,1.0))  # darker than grid color. full alpha

        gpustate.blend('ALPHA')
        Drawing.draw2D_smooth_circle(context, center, radius, color_out, width=3)
        Drawing.draw2D_smooth_circle(context, center, radius-1, color_in, width=1)
        gpustate.blend('NONE')


class RFOperator_PolyStrips(RFOperator_PolyStrips_Insert_Properties, RFOperator):
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


    brush_radius: wrap_property(
        RFBrush_Strokes, 'stroke_radius', 'int',
        name='Radius',
        description='Radius of the brush in Blender UI units before it gets projected onto the mesh',
        min=1,
        max=1000,
        subtype='PIXEL',
        default=50,
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

    def process_stroke(self, context, radius2D, snap_distance, stroke2D, stroke3D, is_cycle, snapped_geo, snapped_mirror):
        snap_bmf0, snap_bmf1 = snapped_geo[2]
        if not snap_bmf0:
            l = len(stroke2D)
            p0 = stroke2D[0]
            p1 = next((s for s in stroke2D if (s - p0).length >= radius2D), None)
            if p1:
                d = Direction2D(p0 - p1)
                for i in range(1, 101):
                    p = p0 + d * (radius2D * (i / 100))
                    if not raycast_point_valid_sources(context, p): break
                    stroke2D = [p] + stroke2D
        if not snap_bmf1:
            p0 = stroke2D[-1]
            p1 = next((s for s in stroke2D[::-1] if (s - p0).length >= radius2D), None)
            if p1:
                d = Direction2D(p0 - p1)
                for i in range(1, 101):
                    p = p0 + d * (radius2D * (i / 100))
                    if not raycast_point_valid_sources(context, p): break
                    stroke2D += [p]
        length2D = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke2D, is_cycle))
        stroke3D = [raycast_point_valid_sources(context, pt, world=False) for pt in stroke2D]
        stroke3D = [pt for pt in stroke3D if pt]
        RFOperator_PolyStrips_Insert.polystrips_insert(
            context,
            radius2D,
            stroke3D,
            is_cycle,
            length2D,
            snap_bmf0, snap_bmf1,
            self.split_angle,
            self.mirror_correct,
        )

    def update(self, context, event):
        if event.value in {'CLICK', 'DOUBLE_CLICK'} and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
            # prevents object selection with Ctrl+LMB Click
            return {'RUNNING_MODAL'}

        if RFTool_PolyStrips.rf_brush.is_stroking():
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


RFOperator_PolyStrips_Overlay = create_quadstrip_selection_overlay(
    'RFOperator_PolyStrips_Selection_Overlay',
    'retopoflow.polystrips',  # must match RFTool_base.bl_idname
    'polystrips_overlay',
    'PolyStrips Selected Overlay',
    True,
)


@execute_operator('switch_to_polystrips', 'RetopoFlow: Switch to PolyStrips', fn_poll=poll_retopoflow)
def switch_rftool(context):
    import bl_ui
    bl_ui.space_toolsystem_common.activate_by_id(context, 'VIEW_3D', 'retopoflow.polystrips')  # matches bl_idname of RFTool_Base below


class RFTool_PolyStrips(RFTool_Base):
    bl_idname = "retopoflow.polystrips"
    bl_label = "PolyStrips"
    bl_description = "Insert quad strip"
    bl_icon = get_path_to_blender_icon('polystrips')
    bl_widget = None
    bl_operator = 'retopoflow.polystrips'

    rf_brush = RFBrush_Strokes()
    rf_overlay = RFOperator_PolyStrips_Overlay

    props = None  # needed to reset properties

    bl_keymap = chain_rf_keymaps(
        RFOperator_PolyStrips,
        RFOperator_PolyStrips_Insert,
        RFOperator_PolyStrips_Edit,
        RFOperator_StrokesBrush_Adjust,
        RFOperator_Translate,
        RFOperator_Relax_QuickSwitch,
        RFOperator_Tweak_QuickSwitch,
        RFOperator_Launch_Help,
        RFOperator_Launch_NewIssue,
    )

    def draw_settings(context, layout, tool):
        props_polystrips = tool.operator_properties(RFOperator_PolyStrips.bl_idname)
        RFTool_PolyStrips.props = props_polystrips

        if context.region.type == 'TOOL_HEADER':
            layout.label(text="Insert:")
            layout.prop(props_polystrips, 'brush_radius', text="Radius")
            layout.prop(props_polystrips, 'stroke_smoothing', text='Stabilize', slider=True)
            layout.prop(props_polystrips, 'split_angle')
            draw_line_separator(layout)
            layout.popover('RF_PT_TweakCommon')
            row = layout.row(align=True)
            row.popover('RF_PT_MeshCleanup', text='Clean Up')
            row.operator("retopoflow.meshcleanup", text='', icon='PLAY').affect_all=False
            draw_mirror_popover(context, layout)
            layout.popover('RF_PT_General', text='', icon='OPTIONS')
            layout.popover('RF_PT_Help', text='', icon='INFO_LARGE' if bpy.app.version >= (4,3,0) else 'INFO')

        else:
            header, panel = layout.panel(idname='polystrips_spans_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                panel.prop(props_polystrips, 'brush_radius', text="Radius")
                panel.prop(props_polystrips, 'stroke_smoothing', text='Stabilize', slider=True)
                panel.prop(props_polystrips, 'split_angle')
                panel.prop(props_polystrips, 'mirror_correct', text='Mirror Side')
            draw_tweaking_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_cleanup_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context):
        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter('PolyStrips')
        if prefs.setup_automerge:
            cls.resetter['context.tool_settings.use_mesh_automerge'] = True
        if prefs.setup_snapping:
            cls.resetter.store('context.tool_settings.snap_elements_base')
            cls.resetter['context.tool_settings.snap_elements_individual'] = {'FACE_NEAREST'}
        if prefs.setup_selection_mode:
            cls.resetter['context.tool_settings.mesh_select_mode'] = [False, False, True]

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
