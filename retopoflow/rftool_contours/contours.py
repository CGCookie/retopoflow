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
from ..rfoverlays.loopstrip_selection_overlay import create_loopstrip_selection_overlay

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, nearest_bmv_world, nearest_bme_world, bme_midpoint, get_boundary_strips_cycles
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
from ...addon_common.common.resetter import Resetter
from ...addon_common.ext.circle_fit import hyperLSQ

from ..rfoperators.quickswitch import RFOperator_Relax_QuickSwitch, RFOperator_Tweak_QuickSwitch
from ..rfoperators.transform import RFOperator_Translate
from ..rfoperators.launch_browser import RFOperator_Launch_Help, RFOperator_Launch_NewIssue

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
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

    span_count: bpy.props.IntProperty(
        name='Span Count',
        description='Number of vertices to create in a new cut',
        default=8,
        min=3,
        max=100,
    )

    process_source_method: bpy.props.EnumProperty(
        name='Process Source Method',
        description="Source processing method",
        items=[
            ('fast', 'Fast (experimental)', 'Process source approximately (fast but inaccurate)'),
            ('skip', 'Skip (experimental)', 'Process source approximately by skipping about the source mesh'),
            ('walk', 'Walk', 'Process source accurately by walking the source mesh (slow but accurate)'),
        ],
        default='walk',
    )


class RFOperator_Contours_Insert(
        RFOperator_Contours_Insert_Keymaps,
        RFOperator_Contours_Insert_Properties,
        RFOperator_Execute,
    ):
    bl_idname = 'retopoflow.contours_insert'
    bl_label = 'Contours: Insert new stroke'
    bl_description = 'Insert cut and extrude edges into a patch'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    twist: bpy.props.IntProperty(
        name='Rotate Cut',
        description='Rotate cut',
        default=0,
    )

    is_cycle: bpy.props.BoolProperty(
        name='Cyclic Cut',
        description='Force cut to be cyclic or strip',
        default=False,  # will be set on initial cut
    )

    contours_data = None

    @staticmethod
    def insert(context, hit, plane, circle_hit, span_count, process_source_method, hits):
        RFOperator_Contours_Insert.logic = Contours_Logic(
            context,
            hit,
            plane,
            circle_hit,
            span_count,
            process_source_method,
            hits,
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
        )

    def draw(self, context):
        layout = self.layout
        grid = layout.grid_flow(row_major=True, columns=2)
        logic = RFOperator_Contours_Insert.logic

        grid.label(text=f'Cyclic')
        grid.prop(self, 'is_cycle', text='')

        if logic.action:
            grid.label(text=f'Inserted')
            grid.label(text=logic.action)

        if logic.show_span_count:
            grid.label(text=f'Spans')
            grid.prop(self, 'span_count', text='')

        if logic.show_twist:
            grid.label(text=f'Twist')
            grid.prop(self, 'twist', text='')

        grid.label(text=f'Method')
        grid.prop(self, 'process_source_method', text='')

    def execute(self, context):
        logic = RFOperator_Contours_Insert.logic

        logic.span_count            = self.span_count
        logic.process_source_method = self.process_source_method
        logic.twist                 = self.twist
        logic.cyclic                = self.is_cycle

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
                fn(context, RFOperator_Contours_Insert.logic)
                bpy.ops.ed.undo()
                RFOperator_Contours_Insert.reinsert(context)
            return wrapped
        return wrapper

    @create_redo_operator('contours_insert_spans_decreased', 'Reinsert cut with decreased spans', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1})
    def decrease_spans(context, logic):
        logic.span_count -= 1

    @create_redo_operator('contours_insert_spans_increased', 'Reinsert cut with increased spans', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'ctrl': 1})
    def increase_spans(context, logic):
        logic.span_count += 1

    @create_redo_operator('contours_insert_twist_decreased', 'Reinsert cut with decreased twist', {'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'shift': 1})
    def decrease_spans(context, logic):
        if logic.show_twist: logic.twist -= 5

    @create_redo_operator('contours_insert_twist_increased', 'Reinsert cut with increased twist', {'type': 'WHEELUPMOUSE',   'value': 'PRESS', 'shift': 1})
    def increase_spans(context, logic):
        if logic.show_twist: logic.twist += 5



class RFOperator_Contours(RFOperator_Contours_Insert_Properties, RFOperator):
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

    def init(self, context, event):
        RFTool_Contours.rf_brush.set_operator(self)
        self.tickle(context)

    def finish(self, context):
        RFTool_Contours.rf_brush.set_operator(None)

    def reset(self):
        RFTool_Contours.rf_brush.reset()

    def v_to_point(self, v, mouse0, mouse1):
        vn = (4 * self.sample_width) * (v / 2)**3 + 0.5
        return mouse0 + (mouse1 - mouse0) * vn

    def process_cut(self, context, hit, plane, mouse0, mouse1):
        n = self.sample_points // 2

        hits_neg = list(itertools.takewhile(
            bool,
            (raycast_valid_sources(context, self.v_to_point(-(v+1) / n, mouse0, mouse1)) for v in range(n)),
        ))
        hit_mid = raycast_valid_sources(context, mouse0 + (mouse1 - mouse0) / 2)
        hits_pos = list(itertools.takewhile(
            bool,
            (raycast_valid_sources(context, self.v_to_point(+(v+1) / n, mouse0, mouse1)) for v in range(n))
        ))
        hits = list(itertools.chain(hits_neg, [hit_mid], hits_pos))

        # gather more hits to improve
        rays_neg = [
            (Vector((*hit['co_world'], 1.0)), ray_from_point(context, hit['co_world'])[1])
            for hit in hits_neg
        ]
        pts_neg_back = [
            raycast_ray_valid_sources(context, (p + d * 0.0001, d), world=True)
            for (p, d) in rays_neg
        ]
        rays_pos = [
            (Vector((*hit['co_world'], 1.0)), ray_from_point(context, hit['co_world'])[1])
            for hit in hits_pos
        ]
        pts_pos_back = [
            raycast_ray_valid_sources(context, (p + d * 0.0001, d), world=True)
            for (p, d) in rays_pos
        ]
        points = list(itertools.chain(
            [hit['co_world'] for hit in hits if hit],
            pts_neg_back, pts_pos_back
        ))
        circle_hit = hyperLSQ([list(plane.w2l_point(pt).xy) for pt in points])

        RFOperator_Contours_Insert.insert(context, hit, plane, circle_hit, self.span_count, self.process_source_method, hits)

    def update(self, context, event):
        if event.value in {'CLICK', 'DOUBLE_CLICK'} and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
            return {'RUNNING_MODAL'}

        if RFTool_Contours.rf_brush.is_cancelled:
            Cursors.restore()
            self.tickle(context)
            return {'CANCELLED'}

        if RFTool_Contours.rf_brush.is_stroking():
            if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE'}:
                self.RFCore.handle_update(context, event)
                return {'RUNNING_MODAL'}
        else:
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
    import bl_ui
    bl_ui.space_toolsystem_common.activate_by_id(context, 'VIEW_3D', 'retopoflow.contours')  # matches bl_idname of RFTool_Base below

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
        RFOperator_Translate,
        RFOperator_Relax_QuickSwitch,
        RFOperator_Tweak_QuickSwitch,
        RFOperator_Launch_Help,
        RFOperator_Launch_NewIssue,
    )

    def draw_settings(context, layout, tool):
        props_contours = tool.operator_properties(RFOperator_Contours.bl_idname)
        RFTool_Contours.props = props_contours

        if context.region.type == 'TOOL_HEADER':
            layout.label(text='Insert:')
            layout.prop(props_contours, 'span_count')
            layout.prop(props_contours, 'process_source_method', text=f'')
            if props_contours.process_source_method == 'fast':
                layout.prop(props_contours, 'sample_points', text=f'Samples')
                layout.prop(props_contours, 'sample_width', text=f'Width')
            draw_line_separator(layout)
            row = layout.row(align=True)
            row.popover('RF_PT_MeshCleanup', text='Clean Up')
            row.operator("retopoflow.meshcleanup", text='', icon='PLAY').affect_all=False
            draw_mirror_popover(context, layout)
            layout.popover('RF_PT_General', text='', icon='OPTIONS')
            layout.popover('RF_PT_Help', text='', icon='INFO_LARGE' if bpy.app.version >= (4,3,0) else 'INFO')
        else:
            header, panel = layout.panel(idname='contours_cut_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                panel.prop(props_contours, 'span_count')
                panel.prop(props_contours, 'process_source_method', text=f'Method')
                if props_contours.process_source_method == 'fast':
                    panel.prop(props_contours, 'sample_points', text=f'Samples')
                    panel.prop(props_contours, 'sample_width', text=f'Width')
            draw_cleanup_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context):
        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter('Contours')
        if prefs.setup_automerge:
            cls.resetter['context.tool_settings.use_mesh_automerge'] = False
        if prefs.setup_snapping:
            cls.resetter.store('context.tool_settings.snap_elements_base')
            cls.resetter['context.tool_settings.snap_elements_individual'] = {'FACE_NEAREST'}
        if prefs.setup_selection_mode:
            cls.resetter['context.tool_settings.mesh_select_mode'] = [False, True, False]

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
