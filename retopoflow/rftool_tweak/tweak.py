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

# pyright: reportUninitializedInstanceVariable = false


import bpy
from bpy.types import Context, Event, UILayout, WorkSpaceTool
from typing import Any

from ..rfglobals import RFGlobals
from ..rftool_base import RFTool_Base
from ..common.icons import get_path_to_blender_icon
from ..common.operator import RFOperator, OperatorPropertyWrapper, chain_rf_keymaps, execute_operator, poll_retopoflow, RFKeyMaps, BLKeyMaps
from ...addon_common.common.maths import Color
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.timerhandler import TimerHandler

from .tweak_logic import Tweak_Logic

from ..rfoperators.quickswitch import RFOperator_Relax_QuickSwitch
from ..rfoperators.maximize_watcher import RFOperator_MaximizeWatcher
from ..rfoperators.transform import sync_projection_from_blender
from ..rfoperators.topo_rotate import RFOperator_TopoRotate
from ..rfbrushes.falloff_brush import create_falloff_brush

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.masking_panel import draw_masking_panel
from ..rfpanels.mirror_panel import draw_mirror_panel, draw_mirror_popover
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.help_panel import draw_help_panel
from ..rfpanels.rfpanel_snapping import draw_snapping_panel
from ..rfpanels.relax_algorithm_panel import draw_relax_algo_options
from ..common.interface import draw_line_separator

from ..preferences import RF_Prefs

RFBrush_Tweak, RFOperator_TweakBrush_Adjust = create_falloff_brush(
    'tweak_brush',
    'Tweak Brush',
    radius=100,
    color=Color.from_ints(255, 145,  0, 255),
    fn_disable=lambda event: event.shift and not event.ctrl,
)


def poll_props(context: Context, prop: str, value: Any) -> bool:
    ws = context.workspace
    if not ws: return False
    tool = ws.tools.from_space_view3d_mode('EDIT_MESH', create=False)
    if not tool: return False
    props = tool.operator_properties('retopoflow.tweak')
    return bool(props and getattr(props, prop) == value)

def poll_loops(context): return poll_props(context, 'brush_type','NUDGE') and poll_props(context, 'nudge_loops', True)


class RFOperator_Tweak(RFOperator):
    bl_idname = "retopoflow.tweak"
    bl_label = 'Tweak'
    bl_description = 'Tweak the vertex positions'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'UNDO', 'INTERNAL'}

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS'},
            {'km_context': 'init', 'km_label': lambda ctx: 'Tweak Loops' if poll_loops(ctx) else 'Tweak', 'km_status_event_value': 'CLICK_DRAG'}
        ),
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS', 'alt': True}, # blocks Blender's Alt+LMB Move Camera
            {
                'km_context': 'init',
                'km_label': lambda ctx: 'Tweak' if poll_loops(ctx) else 'Tweak Loops',
                'km_status_event_value': 'CLICK_DRAG',
                'km_poll': lambda ctx: poll_props(ctx, 'brush_type','NUDGE')
            }
        ),
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS', 'ctrl': True}, # blocks Blender's Ctrl+LMB Select Shortest Path
            {'km_context': 'init', 'km_label': 'Invert', 'km_poll': lambda ctx: poll_props(ctx, 'brush_type','PINCH_MAGNIFY')}
        ),
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS', 'alt': True, 'ctrl': True}, None),
    ]
    rf_status : list[str] = ['LMB: Tweak']

    brush_radius: OperatorPropertyWrapper.int(
        RFBrush_Tweak, 'radius',
        name='Radius',
        description='Radius of the brush in Blender UI units before it gets projected onto the mesh',
        subtype='PIXEL',
        min=1,
        max=1000,
        default=100,
    )
    brush_falloff: OperatorPropertyWrapper.float(
        RFBrush_Tweak, 'falloff',
        name='Falloff',
        description='How much strength the outside of the brush has as compared to the center',
        min=0.0,
        max=1.00,
        default=1.00,
    )
    brush_strength: OperatorPropertyWrapper.float(
        RFBrush_Tweak, 'strength',
        name='Strength',
        description='Strength of the brush',
        min=0.01,
        max=1.00,
        default=0.75,
    )

    post_relax_steps: bpy.props.FloatProperty(
        name='Relax Factor',
        description='How frequently relax steps are applied while moving the brush. 1 = every 0.1 edge-lengths moved, 0 = disabled',
        subtype='FACTOR',
        min=0.0,
        max=1.0,
        default=0.0,
    )
    post_relax_expand: bpy.props.IntProperty(
        name='Relax Expand',
        description='How many face-steps beyond the grabbed vertices are also relaxed',
        min=0,
        max=10,
        default=1,
    )

    brush_type: bpy.props.EnumProperty(
        name='Brush Type',
        description='How the Tweak brush moves vertices',
        items=[
            ('GRAB',          'Grab',          'Classic Tweak behavior: grab and drag vertices under the brush'),
            ('NUDGE',         'Nudge',         'Nudge-style: smear vertices in the direction of the stroke without grabbing'),
            ('PINCH_MAGNIFY', 'Pinch / Magnify', 'Pull or push vertices perpendicular to the stroke direction'),
        ],
        default='NUDGE',
    )

    nudge_loops: bpy.props.BoolProperty(
        name='Loops',
        description='Find the nearest edge loop perpendicular to the stroke and smear only its vertices. Hold Alt while starting a stroke to toggle for that stroke',
        default=False,
    )

    pinch_magnify_mode: bpy.props.EnumProperty(
        name='Pinch / Magnify Mode',
        description='Magnify pushes vertices away from the brush center; Pinch pulls them toward it. Hold Ctrl while brushing to invert for that stroke',
        items=[
            ('MAGNIFY', 'Magnify', 'Push vertices away from the brush center', 'ADD',    0),
            ('PINCH',   'Pinch',   'Pull vertices toward the brush center',    'REMOVE', 1),
        ],
        default='PINCH',
    )

    algorithm_method: bpy.props.EnumProperty(
        name='Method',
        description='How Relax updates the position of the vertices',
        items=[
            ('AUTO',  'Auto',              'Automatic substep count based on enabled options and vertex count'),
            ('STEPS', 'Substeps',          'Multiple tiny incremental steps'),
            ('RK4',   'RK4 (Experimental)','Runge-Kutta integration for improved stability'),
        ],
        default='AUTO',
    )
    algorithm_iterations: bpy.props.IntProperty(
        name='Iterations',
        description='Number of iterations per relax step (Substeps mode only)',
        min=1, max=10, default=2,
    )
    algorithm_laplacian: bpy.props.BoolProperty(
        name='Algorithm: Laplacian Smooth',
        description="Average vertex locations similarly to Blender's smooth sculpting brush",
        default=True,
    )
    algorithm_average_edge_lengths: bpy.props.BoolProperty(
        name='Algorithm: Average Edge Lengths',
        description='Squash / stretch each edge toward the average edge length near the brush',
        default=False,
    )
    algorithm_straighten_edges: bpy.props.BoolProperty(
        name='Algorithm: Straighten Edges',
        description='Moves each vertex towards making its connected edges straighter',
        default=True,
    )
    algorithm_interpolate_loops: bpy.props.BoolProperty(
        name='Algorithm: Interpolate Loops',
        description='Push vertices toward positions that linearly interpolate between unaffected boundary verts',
        default=False,
    )
    algorithm_equalize_faces: bpy.props.BoolProperty(
        name='Algorithm: Equalize Faces',
        description='Moves vertices of each face to be evenly spread and equal distance from the face center',
        default=False,
    )
    algorithm_correct_flipped_faces: bpy.props.BoolProperty(
        name='Algorithm: Correct Flipped Faces',
        description='Try to move vertices so faces are not flipped',
        default=False,
    )
    algorithm_prevent_bounce: bpy.props.BoolProperty(
        name='Algorithm: Prevent Bounce',
        description='Try to prevent vertices from bouncing back and forth',
        default=False,
    )
    algorithm_max_distance_radius: bpy.props.FloatProperty(
        name='Max Distance (Radius)',
        description='Limit distance vertices are moved per iteration based on brush radius',
        min=0.001, max=1.0, default=0.10,
    )
    algorithm_max_distance_edges: bpy.props.FloatProperty(
        name='Max Distance (Edges)',
        description='Limit distance vertices are moved per iteration based on average connected edge length',
        min=0.001, max=1.0, default=0.05,
    )
    algorithm_source_corner_proximity: bpy.props.FloatProperty(
        name='Corner Proximity',
        description='Corner snap radius as a multiple of the edge snap radius',
        min=0.1, max=10.0, default=2.0,
    )

    logic : Tweak_Logic | None = None
    timer : TimerHandler | None = None

    def init(self, context : Context, event : Event):
        # print(f'STARTING POLYPEN')
        assert RFTool_Tweak.rf_brush
        RFTool_Tweak.rf_brush.update(context, event, force=True)
        self.logic = Tweak_Logic(context, event, RFTool_Tweak.rf_brush, self)
        self.tickle(context)
        self.timer = TimerHandler(120, context=context, enabled=True)

    def reset(self):
        pass

    def check(self, _context : Context) -> bool: # pyright: ignore[reportIncompatibleMethodOverride]
        return True

    def update(self, context : Context, event : Event):
        if not self.logic: return {'CANCELLED'}
        self.logic.update(context, event)

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            return {'FINISHED'}

        if event.value == 'PRESS' and event.type in {'RIGHTMOUSE', 'ESC'}:
            # Should this undo or just stop?
            self.logic.cancel(context)
            return {'CANCELLED'}

        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            # context.area.tag_redraw()
            return {'PASS_THROUGH'}

        return {'RUNNING_MODAL'} # allow other operators, such as UNDO!!!

    def finish(self, _context : Context):
        if self.timer:
            self.timer.stop()
            self.timer = None
        self.logic = None # Clear now, otherwise Blender can crash trying to clear it after the bmesh is destroyed

    def draw_postpixel(self, context : Context):
        RFCore = RFGlobals.RFCore_None
        if not RFCore or not RFCore.is_current_area(context): return
        if not self.logic: return
        self.logic.draw(context)


@execute_operator('switch_to_tweak', 'RetopoFlow: Switch to Tweak', fn_poll=poll_retopoflow)
def switch_rftool(context):
    RFTool_Tweak.activate_tool(context)


class RFTool_Tweak(RFTool_Base):
    bl_idname : str = "retopoflow.tweak"
    bl_label : str = "Tweak"
    bl_description : str = "Tweak the vertex positions"
    bl_icon : str = get_path_to_blender_icon('tweak')
    bl_widget : str | None = None
    rf_operator_idname : str | None = 'retopoflow.tweak'

    rf_brush : RFBrush_Tweak = RFBrush_Tweak()

    props = None  # needed to reset properties

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_Tweak,
        RFOperator_MaximizeWatcher,
        RFOperator_TweakBrush_Adjust,
        RFOperator_TopoRotate,
        RFOperator_Relax_QuickSwitch,
    )

    @staticmethod
    def draw_settings(context : Context, layout : UILayout, tool : WorkSpaceTool):
        props_tweak = tool.operator_properties(RFOperator_Tweak.bl_idname)
        RFTool_Tweak.props = props_tweak
        props_scene = context.scene.retopoflow
        prefs = RF_Prefs.get_prefs(context)

        # TOOL_HEADER: 3d view > toolbar
        # UI: 3d view > n-panel
        # WINDOW: properties > tool
        if context.region.type == 'TOOL_HEADER':
            # layout.label(text="Brush:")
            layout.prop(props_tweak, 'brush_radius')
            layout.prop(props_tweak, 'brush_strength', slider=True)
            layout.prop(props_tweak, 'brush_falloff', slider=True)
            layout.prop(props_tweak, 'brush_type', expand=False, text='')
            if props_tweak.brush_type == 'NUDGE':
                layout.prop(props_tweak, 'nudge_loops', toggle=False)
            if props_tweak.brush_type == 'PINCH_MAGNIFY':
                layout.prop(props_tweak, 'pinch_magnify_mode', expand=True, icon_only=True)
            if prefs.expand_masking:
                draw_line_separator(layout)
                layout.row(heading='Selected:', align=True).prop(props_scene, 'mask_selected', expand=True, icon_only=True)
                layout.separator()
                layout.row(heading='Boundary:', align=True).prop(props_scene, 'mask_boundary', expand=True, icon_only=True)
                # layout.prop(props_scene, 'mask_symmetry', text="Symmetry")  # TODO: Implement
                layout.separator()
                if prefs.setup_pinning:
                    row = layout.row(align=True)
                    row.operator('retopoflow.pinverts', text='', icon='PINNED')
                    row.operator('retopoflow.unpinverts', text='', icon='UNPINNED')
                    row.popover('RF_PT_Pinning', text='Masking')
                else:
                    layout.popover('RF_PT_Pinning', text='Masking')
            else:
                layout.popover('RF_PT_Masking')
            draw_line_separator(layout)
            layout.popover('RF_PT_Snapping', text='Snapping')
            row = layout.row(align=True)
            row.popover('RF_PT_MeshCleanup', text='Clean Up')
            row.operator("retopoflow.meshcleanup", text='', icon='PLAY').affect_all=False
            draw_mirror_popover(context, layout)
            if prefs.expand_offset:
                layout.prop(context.scene.retopoflow, 'retopo_offset', text='Overlay Offset')
            layout.popover('RF_PT_General', text='', icon='OPTIONS')
            layout.popover('RF_PT_Help', text='', icon='INFO_LARGE' if bpy.app.version >= (4,3,0) else 'INFO')

        elif context.region.type in {'UI', 'WINDOW'}:
            header, panel = layout.panel(idname='tweak_brush_panel', default_closed=False)
            header.label(text="Brush")
            if panel:
                panel.prop(props_tweak, 'brush_radius')
                panel.prop(props_tweak, 'brush_strength', slider=True)
                panel.prop(props_tweak, 'brush_falloff', slider=True)
                panel.prop(props_tweak, 'brush_type', expand=True)
                if props_tweak.brush_type == 'NUDGE':
                    panel.row().prop(props_tweak, 'nudge_loops', toggle=False)
                if props_tweak.brush_type == 'PINCH_MAGNIFY':
                    panel.row().prop(props_tweak, 'pinch_magnify_mode', expand=True, text=' ')
            header, panel = layout.panel(idname='tweak_relax_panel', default_closed=False)
            header.label(text="Relax")
            if panel:
                panel.prop(props_tweak, 'post_relax_steps', slider=True)
                if props_tweak.post_relax_steps > 0:
                    panel.prop(props_tweak, 'post_relax_expand')
                    panel.separator()
                    draw_relax_algo_options(context, panel, props=props_tweak)
            draw_masking_panel(context, layout)
            draw_snapping_panel(context, layout, idname='tweak_snapping_panel', guide_loops=True)
            draw_cleanup_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

        else:
            print(f'RFTool_Tweak.draw_settings: {context.region.type=}')

    @classmethod
    def activate(cls, context : Context):
        # TODO: some of the following might not be needed since we are creating our own transform operators
        Tweak_Logic.check_nans = True
        cls.rf_brush.set_operator(RFOperator_Tweak)

        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter('Tweak')
        if not prefs.setup_snapping:
            context.scene.retopoflow.snapping.projection = 'FOLLOW_BLENDER'
        else:
            sync_projection_from_blender(context)
        if prefs.setup_automerge:
            cls.resetter['context.tool_settings.use_mesh_automerge'] = False
        if context.scene.retopoflow.snapping.projection != 'FOLLOW_BLENDER':
            # cls.resetter['context.tool_settings.snap_elements_base'] = {'VERTEX'}
            cls.resetter.store('context.tool_settings.snap_elements_base')
            snap_elem = 'FACE_PROJECT' if context.scene.retopoflow.snapping.projection == 'SCREEN_SPACE' else 'FACE_NEAREST'
            cls.resetter['context.tool_settings.snap_elements_individual'] = {snap_elem}

    @classmethod
    def deactivate(cls, _context : Context):
        cls.resetter.reset()
        cls.rf_brush.stop()
