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
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.types import Context

from ..rfbrushes.cut_brush import RFBrush_Cut
from ..rfoverlays.loopstrip_selection_overlay import create_loopstrip_selection_overlay

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh
from ..common.drawing import Drawing
from ..common.icons import get_path_to_blender_icon
from ..common.maths import view_forward_direction
from ..common.operator import (
    invoke_operator, execute_operator,
    RFOperator, RFRegisterClass, RFOperator_Execute,
    chain_rf_keymaps, wrap_property, poll_retopoflow,
)
from ..common.raycast import (
    raycast_valid_sources,
    raycast_point_valid_sources,
    raycast_ray_valid_sources,
    mouse_from_event,
    nearest_point_valid_sources,
    ray_from_point,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender import event_modifier_check
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import Plane, Point
from ...addon_common.common.resetter import Resetter

from ..rfoperators.twist import twist_detect_symmetry, twist_apply, TWIST_SENSITIVITY
from ..common.bmesh_maths import fit_plane_of_verts
from ..rfoperators.quickswitch import RFOperator_Relax_QuickSwitch, RFOperator_Tweak_QuickSwitch
from ..rfoperators.transform import RFOperator_Translate, sync_projection_from_blender
from ..rfoperators.maximize_watcher import RFOperator_MaximizeWatcher

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel
from ..rfpanels.rfpanel_snapping import draw_snapping_panel
from ..rfpanels.mirror_panel import draw_mirror_panel, draw_mirror_popover
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.help_panel import draw_help_panel
from ..common.interface import draw_line_separator

from ..preferences import RF_Prefs

from .contours_logic import Contours_Logic
from functools import wraps
import itertools


class RFOperator_Contours_Insert_Keymaps:
    # used to collect redo shortcuts, which is filled in by redo_ fns below...
    # note: cannot use RFOperator_Contours_Insert.rf_keymaps, because RFOperator_Contours_Insert
    #       is not yet created!
    rf_keymaps = []

class RFOperator_Contours_Insert_Properties:
    '''
    bpy properties that are shared between insert operator and the modal operator
    used to prevent duplicate code across both operators
    '''

    span_count: bpy.props.IntProperty(                  # pyright: ignore [reportUninitializedInstanceVariable]
        name='Span Count',
        description='Number of vertices to create in a new cut',
        default=8,
        min=3,
        max=100,
    )

    process_source_method: bpy.props.EnumProperty(      # pyright: ignore [reportUninitializedInstanceVariable]
        name='Process Source Method',
        description="Source processing method",
        items=[
            ('walk', 'Walk', 'Process source accurately by walking the source mesh (slow but accurate)'),
            ('skip', 'Skip (experimental)', 'Process source approximately by skipping about the source mesh'),
            ('fast', 'Fast (experimental)', 'Process source approximately (fast but inaccurate)'),
        ],
        default='walk',
    )

    cut_orientation: bpy.props.EnumProperty(               # pyright: ignore [reportUninitializedInstanceVariable]
        name='Cut Orientation',
        description='How the cut plane is aligned before processing',
        items=[
            ('world',  'World',  'Align the cut to the closest world axis', 'ORIENTATION_GLOBAL', 0),
            ('local',  'Local',  'Align the cut to the closest local axis of the source object', 'ORIENTATION_LOCAL', 1),
            ('normal', 'Normal', 'Align the cut to the face normal under the stroke', 'ORIENTATION_LOCAL', 2),
            ('stroke', 'View', 'Align the cut to the direction of the stroke on screen', 'ORIENTATION_VIEW', 3),
        ],
        default='stroke',
    )


class RFOperator_Contours_Insert(
        RFOperator_Contours_Insert_Keymaps,
        RFOperator_Contours_Insert_Properties,
        RFOperator_Execute,
    ):
    bl_idname = 'retopoflow.contours_insert'
    bl_label = 'Contours: Insert Stroke'
    bl_description = 'Insert cut and extrude edges into a patch'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    twist: bpy.props.FloatProperty(
        name='Rotate Cut',
        description='Rotate cut',
        default=0.0,
        min= -math.pi / 2,
        max= math.pi / 2,
        subtype='ANGLE',
    )

    is_cycle: bpy.props.BoolProperty(
        name='Cyclic Cut',
        description='Force cut to be cyclic or strip',
        default=False,  # will be set on initial cut
    )

    loop_count: bpy.props.IntProperty(
        name='Loop Count',
        description='Number of loops to create when bridging',
        default=1,
        min=1,
        max=20,
    )

    logic : Contours_Logic
    contours_data = None

    @staticmethod
    def insert(context, hit, plane, circle_points, span_count, process_source_method, hits, cut_orientation):
        RFOperator_Contours_Insert.logic = Contours_Logic(
            context,
            hit,
            plane,
            circle_points,
            span_count,
            process_source_method,
            hits,
            cut_orientation,
        )
        RFOperator_Contours_Insert.reinsert(context)

    @staticmethod
    def reinsert(context):
        logic = RFOperator_Contours_Insert.logic
        bpy.ops.retopoflow.contours_insert(
            'INVOKE_DEFAULT', True,
            span_count=logic.span_count,
            process_source_method=logic.process_source_method,
            twist=logic.twist,
            is_cycle=logic.cyclic,
            loop_count=logic.loop_count,
        )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        logic = RFOperator_Contours_Insert.logic

        if logic.action:
            split = layout.split(factor=0.4)
            col = split.column()
            col.alignment='RIGHT'
            col.label(text='Insert')
            split.label(text=logic.action)

        layout.prop(self, 'process_source_method', text='Method')

        if logic.show_span_count:
            layout.prop(self, 'span_count', text='Spans')

        if logic.show_loop_count:
            layout.prop(self, 'loop_count', text='Loops')

        if logic.show_twist:
            layout.prop(self, 'twist', text='Twist')

        layout.row(heading='Cyclic').prop(self, 'is_cycle', text='')

    def execute(self, context):
        logic = RFOperator_Contours_Insert.logic

        logic.span_count            = self.span_count
        logic.process_source_method = self.process_source_method
        logic.twist                 = self.twist
        logic.cyclic                = self.is_cycle
        logic.loop_count            = self.loop_count

        try:
            logic.update(context)
        except Exception as e:
            # TODO: revisit how this issue (#1376) is handled.
            #       right now, the operator is simply cancelled, which could leave mesh in a weird state or remove
            #       recently added stroke!
            print(f'{type(self).__name__}.execute: Caught Exception {e}')
            debugger.print_exception()
            return {'CANCELLED'}

        self.span_count            = logic.span_count
        self.process_source_method = logic.process_source_method
        self.twist                 = logic.twist
        self.is_cycle              = logic.cyclic
        self.loop_count            = logic.loop_count

        return {'FINISHED'}

    @staticmethod
    def create_redo_operator(idname: str, description: str, keymap: dict, op_props: dict | None = None):
        # add keymap to RFOperator_Contours_Insert.rf_keymaps
        # note: still creating RFOperator_Contours_Insert, so using RFOperator_Contours_Insert_Keymaps.rf_keymaps
        def _poll(context) -> bool:
            last_op = context.window_manager.operators[-1].name if context.window_manager.operators else None
            return last_op == RFOperator_Contours_Insert.bl_label

        if op_props is not None:
            op_props['km_poll'] = _poll

        RFOperator_Contours_Insert_Keymaps.rf_keymaps.append( (f'retopoflow.{idname}', keymap, op_props) )
        def wrapper(fn):
            nonlocal _poll
            @execute_operator(idname, description, options={'INTERNAL'})
            @wraps(fn)
            def wrapped(context):
                if not _poll(context): return
                fn(context, RFOperator_Contours_Insert.logic)
                bpy.ops.ed.undo()
                RFOperator_Contours_Insert.reinsert(context)
            return wrapped
        return wrapper

    @create_redo_operator('contours_insert_spans_decreased', 'Reinsert cut with decreased spans',
                          {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1},
                          {'km_context': ('init', 'ready'), 'km_label': 'Change Spans / Loops'})
    def decrease_spans(context, logic):
        if logic.show_loop_count:
            logic.loop_count = max(1, logic.loop_count - 1)
        else:
            logic.span_count -= 1

    @create_redo_operator('contours_insert_spans_increased', 'Reinsert cut with increased spans',
                          {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'ctrl': 1})
    def increase_spans(context, logic):
        if logic.show_loop_count:
            logic.loop_count += 1
        else:
            logic.span_count += 1

    @create_redo_operator('contours_insert_twist_decreased', 'Reinsert cut with decreased twist',
                          {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'shift': 1},
                          {'km_context': ('init', 'ready'), 'km_label': 'Change Twist'})
    def decrease_twist(context, logic):
        if logic.show_twist: logic.twist = max(-math.pi / 2, logic.twist - math.radians(5))

    @create_redo_operator('contours_insert_twist_increased', 'Reinsert cut with increased twist',
                          {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'shift': 1})
    def increase_twist(context, logic):
        if logic.show_twist: logic.twist = min(math.pi / 2, logic.twist + math.radians(5))



class RFOperator_Contours(RFOperator_Contours_Insert_Properties, RFOperator):
    bl_idname = 'retopoflow.contours'
    bl_label = 'Contours'
    bl_description = 'Retopologize cylindrical forms, like arms and legs'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()

    loop_select_op = 'mesh.select_edge_loop_multi' if bpy.app.version >= (5, 1, 0) else 'mesh.loop_multi_select'

    rf_keymaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),

        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK',        'ctrl': True}, {'km_context': ('init', 'ready'), 'km_label': 'Insert Strip'}),  # prevents object selection with Ctrl+LMB Click
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK', 'ctrl': True}, None),

        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, {'km_context': 'insert', 'km_label': 'Draw Contour Stroke'}),

        (loop_select_op, {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, {'km_context': 'init', 'km_label': 'Select Strip'}),
    ]
    rf_status = {
        'ready': ('LMB: Insert', ),
        'insert': ('RMB: Cancel', )
    }

    sample_points: bpy.props.IntProperty(
        name='Samples',
        default=100,
        min=10,
        max=1000,
    )
    sample_width: bpy.props.FloatProperty(
        name='Sample Width',
        default=0.75,
        min=0.10,
        max=1.00,
    )
    select_loops: bpy.props.BoolProperty(
        name = 'Tweak Loops',
        description = 'Select and transform loops while tweaking edges with the mouse',
        default = True
    )

    def init(self, context, event):
        self.km_context = 'ready'
        RFTool_Contours.rf_brush.set_operator(self)
        self.tickle(context)

    def finish(self, context):
        self.set_statusbar_override(None)
        self.km_context = 'init'
        RFTool_Contours.rf_brush.set_operator(None)

    def reset(self):
        RFTool_Contours.rf_brush.reset()

    def v_to_point(self, v, mouse0, mouse1):
        vn = (4 * self.sample_width) * (v / 2)**3 + 0.5
        return mouse0 + (mouse1 - mouse0) * vn

    def process_cut(self, context:Context, hit:dict[str,...], plane:Plane, mouse0:Vector, mouse1:Vector):
        n = self.sample_points // 2

        hits_neg = list(itertools.takewhile(
            bool,
            (raycast_valid_sources(context, self.v_to_point(-(v+1) / n, mouse0, mouse1), respect_clip_planes=True) for v in range(n)),
        ))
        hit_mid = raycast_valid_sources(context, mouse0 + (mouse1 - mouse0) / 2, respect_clip_planes=True)
        hits_pos = list(itertools.takewhile(
            bool,
            (raycast_valid_sources(context, self.v_to_point(+(v+1) / n, mouse0, mouse1), respect_clip_planes=True) for v in range(n))
        ))
        hits = list(itertools.chain(hits_neg, [hit_mid], hits_pos))

        # gather more hits to improve
        rays_neg = [
            (Vector((*hit['co_world'], 1.0)), ray_from_point(context, hit['co_world'])[1])
            for hit in hits_neg
        ]
        pts_neg_back = [
            raycast_ray_valid_sources(context, (p + d * 0.0001, d), world=True, respect_clip_planes=True)
            for (p, d) in rays_neg if p is not None and d is not None
        ]
        rays_pos = [
            (Vector((*hit['co_world'], 1.0)), ray_from_point(context, hit['co_world'])[1])
            for hit in hits_pos
        ]
        pts_pos_back = [
            raycast_ray_valid_sources(context, (p + d * 0.0001, d), world=True, respect_clip_planes=True)
            for (p, d) in rays_pos if p is not None and d is not None
        ]
        points = list(itertools.chain(
            [hit['co_world'] for hit in hits if hit],
            pts_neg_back, pts_pos_back
        ))
        circle_points = [pt for pt in points if pt]

        RFOperator_Contours_Insert.insert(context, hit, plane, circle_points, self.span_count, self.process_source_method, hits, self.cut_orientation)

    def update(self, context, event):
        if event.value in {'CLICK', 'DOUBLE_CLICK'} and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
            return {'RUNNING_MODAL'}

        if RFTool_Contours.rf_brush.is_cancelled:
            Cursors.restore()
            self.tickle(context)
            return {'CANCELLED'}

        if RFTool_Contours.rf_brush.is_stroking():
            self.set_statusbar_override(self.rf_status['insert'])
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE', 'RIGHTMOUSE', 'ESC'}:
                self.RFCore.handle_update(context, event)
                return {'RUNNING_MODAL'}
        else:
            self.set_statusbar_override(None)
            if not event.ctrl:
                Cursors.restore()
                self.tickle(context)
                return {'FINISHED'}

        Cursors.set('CROSSHAIR')
        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!


RFOperator_Contours_Overlay = create_loopstrip_selection_overlay(
    'RFOperator_Contours_Selection_Overlay',
    'retopoflow.contours',  # must match RFTool_base.bl_idname
    'contours_overlay',
    'Contours Selected Overlay',
    False,
)

@execute_operator('switch_to_contours', 'RetopoFlow: Switch to Contours', fn_poll=poll_retopoflow)
def switch_rftool(context):
    RFTool_Contours.activate_tool(context)


class RFOperator_Contours_Twist(RFRegisterClass, bpy.types.Operator):
    bl_idname     = 'retopoflow.contours_twist'
    bl_label      = 'Contours: Adjust Twist'
    bl_description = 'Rotate selected loop about its plane (Alt R)'
    bl_options    = {'UNDO', 'INTERNAL'}

    rf_keymaps = []

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        bm, em = get_bmesh_emesh(context)
        sel_verts = [v for v in bm.verts if v.select]
        if len(sel_verts) < 3:
            return {'CANCELLED'}
        self._bm          = bm
        self._em          = em
        self._mw          = context.edit_object.matrix_world.copy()
        self._mwi         = self._mw.inverted()
        self._initial_cos = {v: v.co.copy() for v in sel_verts}
        self._sym_verts, self._sym_axes = twist_detect_symmetry(context, sel_verts)
        self._normal, self._center      = fit_plane_of_verts(sel_verts)
        self._initial_mouse_x = event.mouse_x
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            delta = event.mouse_x - self._initial_mouse_x
            twist_apply(self._bm, self._em, self._mw, self._mwi,
                        self._initial_cos, self._sym_verts, self._sym_axes,
                        self._normal, self._center, delta * TWIST_SENSITIVITY,
                        snap_fn=lambda pt: nearest_point_valid_sources(context, pt, world=True, respect_clip_planes=True))
            return {'RUNNING_MODAL'}
        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            for v, co0 in self._initial_cos.items():
                v.co = co0.copy()
            self._bm.normal_update()
            bmesh.update_edit_mesh(self._em, loop_triangles=False)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


RFOperator_Contours_Twist.rf_keymaps = [
    ('retopoflow.contours_twist', {'type': 'R', 'value': 'PRESS', 'alt': True},
     {'km_context': ('init', 'ready'), 'km_label': 'Adjust Twist'}),
]


class RFTool_Contours(RFTool_Base):
    bl_idname = "retopoflow.contours"
    bl_label = "Contours"
    bl_description = "Retopologize cylindrical forms, like arms and legs"
    bl_icon = get_path_to_blender_icon('contours')
    bl_widget = None
    bl_operator = 'retopoflow.contours'

    rf_brush = RFBrush_Cut()
    rf_overlay = RFOperator_Contours_Overlay

    props = None  # needed to reset properties

    bl_keymap = chain_rf_keymaps(
        RFOperator_Contours,
        RFOperator_Contours_Insert,
        RFOperator_Contours_Twist,
        RFOperator_MaximizeWatcher,
        RFOperator_Translate,
        RFOperator_Relax_QuickSwitch,
        RFOperator_Tweak_QuickSwitch,
    )

    def draw_settings(context, layout, tool):
        prefs = RF_Prefs.get_prefs(context)
        props_contours = tool.operator_properties(RFOperator_Contours.bl_idname)
        RFTool_Contours.props = props_contours

        if context.region.type == 'TOOL_HEADER':
            layout.label(text='Insert:')
            layout.prop(props_contours, 'span_count')
            layout.prop(props_contours, 'cut_orientation', text='')
            layout.prop(props_contours, 'process_source_method', text=f'')
            if props_contours.process_source_method == 'fast':
                layout.prop(props_contours, 'sample_points', text=f'Samples')
                layout.prop(props_contours, 'sample_width', text=f'Width')
            draw_line_separator(layout)
            row = layout.row(align=True)
            row.prop(props_contours, 'select_loops', text='Loops', toggle=True)
            row.popover('RF_PT_TweakCommon')
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
            header, panel = layout.panel(idname='contours_cut_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                panel.prop(props_contours, 'span_count')
                panel.prop(props_contours, 'cut_orientation', text='Direction')
                panel.prop(props_contours, 'process_source_method', text=f'Method')
                if props_contours.process_source_method == 'fast':
                    panel.prop(props_contours, 'sample_points', text=f'Samples')
                    panel.prop(props_contours, 'sample_width', text=f'Width')
            draw_tweaking_panel(context, layout)
            draw_snapping_panel(context, layout, idname='contours_snapping_panel')
            draw_cleanup_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context):
        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter('Contours')
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
            cls.resetter['context.tool_settings.mesh_select_mode'] = [False, True, False]

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
        cls.rf_brush.stop()
