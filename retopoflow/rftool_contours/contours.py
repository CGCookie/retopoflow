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

from ..rfglobals import RFGlobals
from ..rfbrushes.cut_brush import RFBrush_Cut
from ..rfoverlays.loopstrip_selection_overlay import create_loopstrip_selection_overlay

from ..rftool_base import RFTool_Base
from ..common.accel import SourceAccel
from ..common.bmesh import get_bmesh_emesh
from ..common.drawing import Drawing
from ..common.icons import get_path_to_blender_icon
from ..common.maths import view_forward_direction
from ..common.operator import (
    execute_operator,
    RFOperator, RFRegisterClass, RFOperator_Execute, RFKeyMaps, BLKeyMaps,
    chain_rf_keymaps, wrap_property, poll_retopoflow,
)
from ..common.raycast import (
    raycast_valid_sources,
    raycast_point_valid_sources,
    raycast_ray_valid_sources,
    mouse_from_event,
    ray_from_point,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender import event_modifier_check
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import Plane, Point
from ...addon_common.common.resetter import Resetter

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


def warmup_cache_on_change(cls):
    # Skip warmup when the property changes via the redo panel (insert operator)
    if type(cls).__name__ == 'RETOPOFLOW_OT_contours_insert': return

    # The slight delay keeps Blender from seeing the default as current immediately on switch
    def warmup_if_walk():
        ws = bpy.context.workspace
        if not ws: return
        tool = ws.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        if ((props := tool.operator_properties('retopoflow.contours')) and
            props.process_source_method == 'walk'
        ):
            SourceAccel.warmup(bpy.context, 3)
        # Returns None to unregister itself after first fire

    bpy.app.timers.register(warmup_if_walk, first_interval= 0.1)


class RFOperator_Contours_Insert_Keymaps:
    # used to collect redo shortcuts, which is filled in by redo_ fns below...
    # note: cannot use RFOperator_Contours_Insert.rf_keymaps, because RFOperator_Contours_Insert
    #       is not yet created!
    rf_keymaps : RFKeyMaps = []

class RFOperator_Contours_Insert_Properties:
    '''
    bpy properties that are shared between insert operator and the modal operator
    used to prevent duplicate code across both operators
    '''

    span_count: bpy.props.IntProperty(                  # pyright: ignore [reportUninitializedInstanceVariable]
        name='Span Count',
        description='Number of vertices to create in a new cut',
        default=16,
        min=3,
        max=500,
    )
    loop_count: bpy.props.IntProperty(
        name='Loop Count',
        description='Number of loops to create when bridging',
        default=1,
        min=1,
        max=20,
    )
    process_source_method: bpy.props.EnumProperty(      # pyright: ignore [reportUninitializedInstanceVariable]
        name='Process Source Method',
        description="Source processing method",
        items=[
            ('walk', 'Walk', 'Walks every face along the source mesh. \n'
                'Slow on high res models but very accurate. \n'
                'Only supports manifold geometry.'),
            # ('skip', 'Skip',
            #     'Process source by making many small jumps along the source mesh and snapping back to it. ' +
            #     '\nWorks best on dense meshes of low complexity.'
            # ),
            ('sdf', 'SDF',
                'Builds a coarse occupancy grid on the cut plane, traces its boundary, then snaps to the source and refines. \n'
                'It can process extremely high poly sources fairly quickly. \n'
                'It works great aross flipped normals, split edges, and overhangs.',
            ),
            ('fast', 'Fast',
                'Raycasts into the mesh to find its volume center, raycasts in a circle to find the surface, then refines that result with... more raycasts. \n'
                'Very fast but less accurate, especially with thin extrusions and overhangs.',
            ),
        ],
        default='walk',
        update=lambda self, ctx: warmup_cache_on_change(self),
    )
    cut_orientation: bpy.props.EnumProperty(                  # pyright: ignore [reportUninitializedInstanceVariable]
        name='Cut Orientation',
        description='How the cut plane normal is aligned. Controls which axis the loop encircles',
        items=[
            ('world',  'World',  'Align to the closest world axis', 'ORIENTATION_GLOBAL', 0),
            ('local',  'Local',  'Align to the closest local axis of the source object', 'ORIENTATION_LOCAL', 1),
            ('normal', 'Normal', 'Align to the face normal under the stroke', 'ORIENTATION_LOCAL', 2),
            ('stroke', 'View',   'Align to the stroke direction on screen', 'ORIENTATION_VIEW', 3),
        ],
        default='stroke',
    )
    fast_depth: bpy.props.IntProperty(                   # pyright: ignore [reportUninitializedInstanceVariable]
        name='Depth',
        description='Number of surfaces to pass through when raycasting. \n' \
            'For example, a regular cylinder needs 1 while a solidified cylinder needs 2. \n' \
            'Increase when the loop gets stuck inside the source or decrease if it gets stuck to background surfaces.',
        default=1,
        min=1,
        max=5,
    )
    fast_refine_steps: bpy.props.IntProperty(             # pyright: ignore [reportUninitializedInstanceVariable]
        name='Refinement Steps',
        description="Number of adaptive subdivision passes and raycasts to refine the cut along the surface.",
        default=5,
        min=0,
        max=10,
    )
    sample_points: bpy.props.IntProperty(                # pyright: ignore [reportUninitializedInstanceVariable]
        name='Samples',
        description='The number of rays to fire from the volume center to find the surface',
        default=50,
        min=10,
        max=250,
    )
    sample_width: bpy.props.FloatProperty(               # pyright: ignore [reportUninitializedInstanceVariable]
        name='Sample Width',
        description='The width of extra 2 sample points along the stroke that help compute the volume center.',
        default=0.25,
        min=0.10,
        max=1.00,
    )
    skip_step_size: bpy.props.FloatProperty(             # pyright: ignore [reportUninitializedInstanceVariable]
        name='Step Size',
        description='Multiplier for how far each step travels along the cross-section. Smaller values trace detailed surfaces more accurately but require more steps',
        default=0.5,
        min=0.1,
        max=1.0,
    )
    sdf_resolution: bpy.props.IntProperty(               # pyright: ignore [reportUninitializedInstanceVariable]
        name='Resolution',
        description='Number of grid cells along the longest axis of the cross-section. Higher resolves finer detail at more cost',
        default=50,
        min=10,
        max=100,
    )
    sdf_subdivisions: bpy.props.IntProperty(       # pyright: ignore [reportUninitializedInstanceVariable]
        name='Pixel Refine',
        description='Adaptive 3x3 subdivision passes over cells near the boundary. \n' \
            'Raise to separate thin surfaces or objects that are close to but not quite touching.',
        default=1,
        min=0,
        max=3,
    )
    sdf_refine_steps: bpy.props.IntProperty(              # pyright: ignore [reportUninitializedInstanceVariable]
        name='Refinement Steps',
        description="Number of adaptive subdivision passes and raycasts to refine the cut along the surface.",
        default=5,
        min=0,
        max=10,
    )
    sdf_extent_scale: bpy.props.FloatProperty(           # pyright: ignore [reportUninitializedInstanceVariable]
        name='Grid Scale',
        description='How large the boundary of the grid is compared to the measured volume. \n' \
            'Smaller is more accurate for the same performance but more likely to miss areas in complex objects',
        default=3,
        min=0.5,
        max=5.0,
        step=10,
    )
    spacing_method: bpy.props.EnumProperty(              # pyright: ignore [reportUninitializedInstanceVariable]
        name='Spacing Method',
        description='How new vertices are distributed along the cut cross-section',
        items=[
            ('EVEN',        'Even',        'Space vertices at equal arc-length intervals regardless of surface shape'),
            ('CURVATURE',   'Curvature',   'Place vertices at the sharpest corners first, then fill remaining spots evenly between them'),
            ('INTERPOLATE', 'Interpolate', 'Match the spacing of surrounding loops when cutting into existing faces, falling back to Even for the first cut'),
        ],
        default='INTERPOLATE',
    )
    curvature_bias: bpy.props.FloatProperty(             # pyright: ignore [reportUninitializedInstanceVariable]
        name='Curvature Bias',
        description='Blend between even spacing (0.0) and pure curvature/RDP placement (1.0). '
                    'At 0.5, high-deviation points are placed by shape and low-deviation points spread evenly',
        default=0.7,
        min=0.0,
        max=1.0,
        step=1,
        precision=2,
    )
    interpolation_factor: bpy.props.FloatProperty(       # pyright: ignore [reportUninitializedInstanceVariable]
        name='Interpolation Factor',
        description='Blend between even spacing (0.0) and matching the spacing of surrounding loops (1.0)',
        default=1.0,
        min=0.0,
        max=1.0,
        step=1,
        precision=2,
    )


def draw_contours_method_options(context, layout, props):
    layout.use_property_decorate = False
    use_row = context.region.width > 1000 # usually only true for popover, but fine for really wide panel too
    if use_row:
        layout.use_property_split = False
        layout.row().prop(props, 'process_source_method', text='Method', expand=True)
    else:
        layout.use_property_split = True
        layout.row().prop(props, 'process_source_method', text='Method', expand=True)
    layout.use_property_split = True

    if props.process_source_method in ['fast', 'sdf', 'skip']:
        header, panel = layout.panel(idname='contours_quality_panel', default_closed=False)
        header.label(text="Quality")
        if panel:
            col = panel.column(align=False)
            if props.process_source_method == 'fast':
                col.prop(props, 'sample_points', text='Samples')
                col.prop(props, 'fast_refine_steps', text='Refinement')
            elif props.process_source_method == 'sdf':
                col.prop(props, 'sdf_subdivisions', text='SDF Subdiv')
                col.prop(props, 'sdf_refine_steps', text='Refinement')
            elif props.process_source_method == 'skip':
                panel.prop(props, 'skip_step_size', text='Step Size')
            col.separator()

    if props.process_source_method in ['fast', 'sdf']:
        header, panel = layout.panel(idname='contours_source_panel', default_closed=False)
        header.label(text="Source Detection")
        if panel:
            col = panel.column(align=False)
            col.prop(props, 'sample_width',  text='Sample Width')
            col.prop(props, 'fast_depth',    text='Ray Depth')
            if props.process_source_method == 'sdf':
                col.prop(props, 'sdf_extent_scale', text='Search Scale')
            col.separator()


def draw_contours_props(context, layout, props, logic):
    layout.use_property_split = True
    layout.use_property_decorate = False
    if logic: # only available in redo panel after stroke
        layout.row(heading=logic.action).prop(props, 'is_cycle', text='Cyclic')
    layout.prop(props, 'cut_orientation', text='Orientation')
    if not logic or logic.show_span_count:
        layout.prop(props, 'span_count', text='Spans')
    if not logic or logic.show_loop_count:
        layout.prop(props, 'loop_count', text='Cuts')
    if logic and logic.show_twist: # Only makes sense in redo panel
        layout.prop(props, 'twist', text='Twist')
    layout.prop(props, 'curvature_bias', text='Curvature', slider=True)
    layout.prop(props, 'interpolation_factor', text='Interpolation', slider=True)
    draw_contours_method_options(context, layout, props)


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

    logic : Contours_Logic
    contours_data = None

    @staticmethod
    def insert(context, hit, plane, circle_points, span_count, process_source_method, hits, cut_orientation,
               fast_depth=1, sample_points=50, fast_refine_steps=5, sdf_refine_steps=3, skip_step_size=1.0,
               sdf_resolution=20, sdf_subdivisions=0, sdf_extent_scale=1.5,
               spacing_method='INTERPOLATE', curvature_bias=0.7, interpolation_factor=1.0):
        RFOperator_Contours_Insert.logic = Contours_Logic(
            context,
            hit,
            plane,
            circle_points,
            span_count,
            process_source_method,
            hits,
            cut_orientation,
            fast_depth,
            sample_points,
            fast_refine_steps,
            sdf_refine_steps,
            skip_step_size,
            sdf_resolution,
            sdf_subdivisions,
            sdf_extent_scale,
            spacing_method,
            curvature_bias,
            interpolation_factor,
        )
        RFOperator_Contours_Insert.reinsert(context)

    @staticmethod
    def reinsert(context):
        logic = RFOperator_Contours_Insert.logic
        bpy.ops.retopoflow.contours_insert(
            'INVOKE_DEFAULT', True,
            span_count=logic.span_count,
            process_source_method=logic.process_source_method,
            fast_depth=logic.fast_depth,
            sample_points=logic.sample_points,
            fast_refine_steps=logic.fast_refine_steps,
            sdf_refine_steps=logic.sdf_refine_steps,
            skip_step_size=logic.skip_step_size,
            sdf_resolution=logic.sdf_resolution,
            sdf_subdivisions=logic.sdf_subdivisions,
            sdf_extent_scale=logic.sdf_extent_scale,
            twist=logic.twist,
            is_cycle=logic.cyclic,
            loop_count=logic.loop_count,
            cut_orientation=logic.cut_orientation,
            spacing_method=logic.spacing_method,
            curvature_bias=logic.curvature_bias,
            interpolation_factor=logic.interpolation_factor,
        )

    def draw(self, context):
        logic = RFOperator_Contours_Insert.logic
        draw_contours_props(context, self.layout, self, logic)

    def execute(self, context):
        logic = RFOperator_Contours_Insert.logic

        logic.span_count            = self.span_count
        logic.process_source_method = self.process_source_method
        logic.fast_depth            = self.fast_depth
        logic.sample_points         = self.sample_points
        logic.fast_refine_steps     = self.fast_refine_steps
        logic.sdf_refine_steps      = self.sdf_refine_steps
        logic.skip_step_size        = self.skip_step_size
        logic.sdf_resolution        = self.sdf_resolution
        logic.sdf_subdivisions = self.sdf_subdivisions
        logic.sdf_extent_scale      = self.sdf_extent_scale
        logic.twist                 = self.twist
        logic.cyclic                = self.is_cycle
        logic.loop_count            = self.loop_count
        logic.cut_orientation       = self.cut_orientation
        logic.spacing_method        = self.spacing_method
        logic.curvature_bias        = self.curvature_bias
        logic.interpolation_factor  = self.interpolation_factor

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
        self.fast_depth            = logic.fast_depth
        self.sample_points         = logic.sample_points
        self.fast_refine_steps     = logic.fast_refine_steps
        self.sdf_refine_steps      = logic.sdf_refine_steps
        self.skip_step_size        = logic.skip_step_size
        self.sdf_resolution        = logic.sdf_resolution
        self.sdf_subdivisions = logic.sdf_subdivisions
        self.sdf_extent_scale      = logic.sdf_extent_scale
        self.twist                 = logic.twist
        self.is_cycle              = logic.cyclic
        self.loop_count            = logic.loop_count
        self.spacing_method        = logic.spacing_method
        self.curvature_bias        = logic.curvature_bias
        self.interpolation_factor  = logic.interpolation_factor

        return {'FINISHED'}

    @staticmethod
    def create_redo_operator(idname: str, description: str, keymap: dict, op_props: dict | None = None):
        # add keymap to RFOperator_Contours_Insert.rf_keymaps
        # note: still creating RFOperator_Contours_Insert, so using RFOperator_Contours_Insert_Keymaps.rf_keymaps
        def _poll(context:Context) -> bool:
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

    rf_keymaps : RFKeyMaps = [
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
        n = 25

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

        RFOperator_Contours_Insert.insert(context, hit, plane, circle_points, self.span_count, self.process_source_method, hits,
                                          self.cut_orientation, self.fast_depth, self.sample_points, self.fast_refine_steps,
                                          self.sdf_refine_steps, self.skip_step_size, self.sdf_resolution, self.sdf_subdivisions,
                                          self.sdf_extent_scale, self.spacing_method, self.curvature_bias, self.interpolation_factor)

    def update(self, context, event):
        RFCore = RFGlobals.RFCore_None
        if not RFCore: return {'CANCELLED'}

        if event.value in {'CLICK', 'DOUBLE_CLICK'} and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
            return {'RUNNING_MODAL'}

        if RFTool_Contours.rf_brush.is_cancelled:
            Cursors.restore()
            self.tickle(context)
            return {'CANCELLED'}

        if RFTool_Contours.rf_brush.is_stroking():
            self.set_statusbar_override(self.rf_status['insert'])
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE', 'RIGHTMOUSE', 'ESC'}:
                RFCore.handle_update(context, event)
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

    rf_keymaps : RFKeyMaps = []

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        return bpy.ops.retopoflow.twist_loop('INVOKE_DEFAULT')


RFOperator_Contours_Twist.rf_keymaps = [
    (
        'retopoflow.contours_twist',
        {'type': 'R', 'value': 'PRESS', 'alt': True},
        {'km_context': ('init', 'ready'), 'km_label': 'Adjust Twist'}
    ),
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

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
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
            # layout.label(text='Insert:')
            layout.prop(props_contours, 'cut_orientation', text='')
            layout.prop(props_contours, 'span_count', text='Spans')
            layout.prop(props_contours, 'loop_count', text='Cuts')
            layout.prop(props_contours, 'curvature_bias', text='Curvature', slider=True)
            layout.prop(props_contours, 'interpolation_factor', text='Interpolation', slider=True)
            method_name = props_contours.bl_rna.properties['process_source_method'].enum_items[props_contours.process_source_method].name
            layout.popover('RF_PT_ContoursMethod', text=method_name)
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
                draw_contours_props(context, panel, props_contours, logic=None)

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

        # Kick SourceMeshCache warmup when Walk is the active method
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH')
        props = tool.operator_properties('retopoflow.contours') if tool else None
        if props and props.process_source_method == 'walk':
            warmup_cache_on_change(cls)

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
        cls.rf_brush.stop()
