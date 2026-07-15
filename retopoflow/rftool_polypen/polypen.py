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
from bpy.types import Context, Event, UILayout, WorkSpaceTool
from mathutils import Vector

from ..rfglobals import RFGlobals
from ..rfoverlay_base import RFOverlay_Base
from ..rfoverlays.curve_overlay import create_curve_overlay
from ..common.curves import QuadStripChainProvider, LoopStripChainProvider
from ..rfoperators.curve_edit import create_curve_edit_operator, create_curve_toggle_handle_type_operator
from ..rftool_base import RFTool_Base
from ..common.icons import get_path_to_blender_icon
from ..common.operator import (
    execute_operator,
    RFOperator,
    RFRegisterClass,
    chain_rf_keymaps,
    OperatorPropertyWrapper,
    poll_retopoflow,
    RFKeyMaps,
    BLKeyMaps,
)
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.blender import event_modifier_check

from ..rfoperators.quickswitch import RFOperator_Relax_QuickSwitch, RFOperator_Tweak_QuickSwitch
from ..rfoperators.transform import RFOperator_Translate, sync_projection_from_blender
from ..rfoperators.maximize_watcher import RFOperator_MaximizeWatcher
from ..rfoperators.topo_rotate import RFOperator_TopoRotate
from ..rfoperators.zipper import RFOperator_Zipper

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel, draw_tweaking_popover
from ..rfpanels.rfpanel_snapping import draw_snapping_panel
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.mirror_panel import draw_mirror_panel, draw_mirror_popover
from ..rfpanels.help_panel import draw_help_panel
from ..common.interface import draw_line_separator
from ..common.bpy_helper import BL_SPACE_TYPES, BL_REGION_TYPES, BL_OPTIONS

from ..preferences import RF_Prefs
from ..common.raycast import mouse_from_event

from .polypen_logic import PP_Logic


class PolyPen_Insert_Modes:
    insert_modes : list[tuple[str, str, str, int]] = [
        # (identifier, name, description, icon, number)  or  (identifier, name, description, number)
        # must have number?
        # None is a separator
        ("VERT-ONLY", "Vertex", "Insert vertices only",           1),
        ("EDGE-ONLY", "Edge", "Insert edges only",                2),
        ("TRI-ONLY",  "Triangle",  "Insert triangles only",       3),  # 'MESH_DATA'
        ("TRI/QUAD",  "Tri/Quad",  "Insert triangles then quads", 0),
        ("QUAD-ONLY", "Quad", "Insert quads only",                4),
    ]
    insert_mode : int = 0

    @staticmethod
    def generate_operators():
        ops_insert : list[tuple[str,str]] = []

        def gen_insert_mode(idname : str, label : str, value : int):
            nonlocal ops_insert

            mode_idname = f'polypen_setinsertmode_{idname.lower()}'
            rf_idname = f'retopoflow.{mode_idname}'
            rf_label = label

            class RFTool_OT_PolyPen_SetInsertMode:
                bl_idname : str = rf_idname
                bl_label : str = rf_label
                bl_description : str = f'Set PolyPen Insert Mode to {label}'

                def execute(self, context : Context) -> set[str]:
                    PolyPen_Insert_Modes.set_insert_mode(value)
                    context.area.tag_redraw()
                    return {'FINISHED'}

            opname = f'RFTool_OT_PolyPen_SetInsertMode_{idname}'
            op = type(opname, (RFTool_OT_PolyPen_SetInsertMode, RFRegisterClass, bpy.types.Operator), {})
            ops_insert += [(rf_idname, rf_label)]

        gen_insert_mode('VertOnly', 'Vert-Only', 1)
        gen_insert_mode('EdgeOnly', 'Edge-Only', 2)
        gen_insert_mode('TriOnly',  'Tri-Only',  3)
        gen_insert_mode('TriQuad',  'Tri/Quad',  0)
        gen_insert_mode('QuadOnly', 'Quad-Only', 4)

    @staticmethod
    def get_insert_mode() -> int:
        return PolyPen_Insert_Modes.insert_mode

    @staticmethod
    def set_insert_mode(v : int):
        PolyPen_Insert_Modes.insert_mode = v


class PolyPen_Quad_Stability:
    quad_stability : float = 1

    @staticmethod
    def generate_operators():
        ops_insert : list[tuple[str,str]] = []

        def gen_quad_stability(idname : str, value : float):
            nonlocal ops_insert

            rf_idname = f'retopoflow.polypen_quad_stability_{idname.lower()}'
            rf_label = f'{value}'

            class RFTool_OT_PolyPen_SetQuadStability:
                bl_idname : str = rf_idname
                bl_label : str = rf_label
                bl_description : str = f'Set PolyPen Quad Stability to {value}'

                def execute(self, context : Context) -> set[str]:
                    PolyPen_Quad_Stability.set_quad_stability(value)
                    context.area.tag_redraw()
                    return {'FINISHED'}

            opname = f'RFTool_OT_PolyPen_SetQuadStability_{idname}'
            op = type(opname, (RFTool_OT_PolyPen_SetQuadStability, RFRegisterClass, bpy.types.Operator), {})
            ops_insert += [(rf_idname, rf_label)]

        gen_quad_stability('quarter', 0.25)
        gen_quad_stability('half', 0.5)
        gen_quad_stability('threequarters', 0.75)
        gen_quad_stability('full', 1.0)

    @staticmethod
    def get_quad_stability():
        return PolyPen_Quad_Stability.quad_stability

    @staticmethod
    def set_quad_stability(v : float):
        PolyPen_Quad_Stability.quad_stability = v


# TODO: DO NOT CALL THIS HERE!  SHOULD ONLY GET CALLED ONCE
#       COULD POTENTIALLY CREATE MULTIPLE OPERATORS WITH SAME NAME
PolyPen_Insert_Modes.generate_operators()
PolyPen_Quad_Stability.generate_operators()


class RFOperator_PolyPen(RFOperator):
    bl_idname : str = "retopoflow.polypen"
    bl_label : str = 'PolyPen'
    bl_description : str = 'Create complex topology on vertex-by-vertex basis'
    bl_space_type : BL_SPACE_TYPES = "VIEW_3D"
    bl_region_type : BL_REGION_TYPES = "TOOLS"
    bl_options : BL_OPTIONS = set()

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'LEFT_CTRL', 'value': 'PRESS'}, {'km_context': 'init', 'km_label': ' Start PolyPen'}),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),
        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, None),
    ]

    rf_status : dict[str, tuple[str]] = {
        'ready': ('LMB: Insert', ),
    }

    insert_mode: OperatorPropertyWrapper.enum(
        PolyPen_Insert_Modes, 'insert_mode',
        name='Insert Mode',
        description='Insertion mode for PolyPen',
        items=PolyPen_Insert_Modes.insert_modes,
        default="TRI/QUAD",
    )
    quad_stability: OperatorPropertyWrapper.float(
        PolyPen_Quad_Stability, 'quad_stability',
        name='Quad Stability',
        description='Stability of parallel edges',
        min=0.00,
        max=1.00,
        default=1.00,
    )
    quad_preserve: bpy.props.BoolProperty(
        name='Knife Junctions',
        description='Insert junctions automatically when knifing across adjacent edges in quads',
        default=True,
    )
    constrain_edge_vert: bpy.props.BoolProperty(
        name='Constrain',
        description='Snaps new verts knifed into an edge to that edge',
        default=True,
    )
    use_loop_cuts: bpy.props.BoolProperty(
        name = 'Loop Cuts',
        description = "Allow PolyPen's knife to follow along quad loops",
        default = True,
    )
    select_loops: bpy.props.BoolProperty(
        name = 'Tweak Loops',
        description = 'Select and transform loops while tweaking edges with the mouse',
        default = False
    )

    logic : PP_Logic
    done : bool
    shift_held : bool
    _prev_state : object = None  # last drawn PP_Action state, to redraw on change without mouse movement
    _last_mouse : Vector | None = None  # last processed mouse position, for the movement throttle

    @classmethod
    def can_start(cls, context):
        return not cls.is_running()

    def init(self, context : Context, event : Event):
        # print(f'STARTING POLYPEN')
        self.set_statusbar_override(self.rf_status['ready'])
        # print(f'  {self.km_context=}')
        self.logic = PP_Logic(context, event)
        self.tickle(context)
        self.done = False
        self.shift_held = False
        self._prev_state = None
        self._last_mouse = None

    def reset(self):
        self.logic.reset()

    def update(self, context : Context, event : Event) -> set[str]:
        if self.shift_held != event.shift:
            self.shift_held = event.shift
            context.area.tag_redraw()

        if not event.ctrl:
            self.done = True

        if self.done:
            if not self.is_active():
                # wait until we're active (could happen when transforming)
                return {'PASS_THROUGH'}

            self.logic.cleanup()
            self.set_statusbar_override(None)
            return {'FINISHED'}

        # Throttle per-event calculations so a tablet input can't spam them (#1574).
        # Only gate MOUSEMOVE, not the timer or click events.
        if event.type == 'INBETWEEN_MOUSEMOVE':
            return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE':
            mouse = Vector(mouse_from_event(event))
            min_distance = RF_Prefs.get_prefs(context).stroke_min_distance
            if self._last_mouse is not None and (mouse - self._last_mouse).length < min_distance:
                return {'PASS_THROUGH'}
            self._last_mouse = mouse

        self.logic.update(context, event, self.insert_mode, self.quad_stability, self.quad_preserve, self.constrain_edge_vert, self.use_loop_cuts)
        # print(f'PolyPen update: "{self.logic.state.name}"')

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
            # print(f'PolyPen commit: "{self.logic.state.name}"')
            self.logic.commit(context, event)
            return {'RUNNING_MODAL'}

        # Redraw on mouse movement, and also whenever the preview changes without movement
        # (e.g. Ctrl held stationary): the nearest-edge connection is computed every update,
        # but previously only MOUSEMOVE repainted the current area, so the connection wouldn't
        # appear until the mouse moved.
        if event.type == 'MOUSEMOVE' or self.logic.state != self._prev_state:
            context.area.tag_redraw()
        self._prev_state = self.logic.state

        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!

    def draw_postpixel(self, context : Context):
        if self.shift_held:
            return

        RFCore = RFGlobals.RFCore_None
        if not RFCore or not RFCore.is_current_area(context):
            return

        self.logic.draw(context)


@execute_operator('switch_to_polypen', 'RetopoFlow: Switch to PolyPen', fn_poll=poll_retopoflow)
def switch_rftool(context):
    RFTool_PolyPen.activate_tool(context)


RFOperator_PolyPen_Overlay = create_curve_overlay(
    'RFOperator_PolyPen_Selection_Overlay',
    'retopoflow.polypen',  # must match RFTool_base.bl_idname
    'polypen_overlay',
    'PolyPen Selected Overlay',
    # faces win: a selection containing quad strips shows only strip curves;
    # loop curves only appear when the selection is edges-only. Same list,
    # same order as Strokes/PolyStrips -- one selection-driven system
    # regardless of which tool is active.
    [QuadStripChainProvider(), LoopStripChainProvider(only_boundary=True)],
)

RFOperator_PolyPen_Edit = create_curve_edit_operator(
    'RFOperator_PolyPen_CurveEdit',
    'polypen_edit',
    'Edit PolyPen Curve',
    'Drag curve control handles to reshape a selected quad strip or edge loop',
    get_overlay=lambda: RFTool_PolyPen.rf_overlay,
)

RFOperator_PolyPen_ToggleHandleType = create_curve_toggle_handle_type_operator(
    'polypen_toggle_handle_type',
    'Toggle Curve Handle Type',
    'Cycle the hovered curve control point between Aligned, Vector, and Automatic',
    get_overlay=lambda: RFTool_PolyPen.rf_overlay,
)


class RFTool_PolyPen(RFTool_Base):
    bl_idname : str = "retopoflow.polypen"
    bl_label : str = "PolyPen"
    bl_description : str = "Create complex topology on vertex-by-vertex basis"
    bl_icon : str = get_path_to_blender_icon('polypen')
    bl_widget : str | None = None
    rf_operator_idname : str | None = 'retopoflow.polypen'
    rf_supports_curve_handles : bool = True
    rf_overlay : type[RFOverlay_Base] | None = RFOperator_PolyPen_Overlay

    props = None  # needed to reset properties

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_PolyPen,
        RFOperator_PolyPen_Edit,
        RFOperator_PolyPen_ToggleHandleType,
        RFOperator_MaximizeWatcher,
        RFOperator_Translate,
        RFOperator_Relax_QuickSwitch,
        RFOperator_Tweak_QuickSwitch,
        RFOperator_TopoRotate,
        RFOperator_Zipper,
    )

    @staticmethod
    def draw_settings(context : Context, layout : UILayout, tool : WorkSpaceTool):
        prefs = RF_Prefs.get_prefs(context)
        props_polypen = tool.operator_properties(RFOperator_PolyPen.bl_idname)
        RFTool_PolyPen.props = props_polypen

        if context.region.type == 'TOOL_HEADER':
            layout.prop(props_polypen, 'insert_mode', text='')
            if props_polypen.insert_mode == 'QUAD-ONLY':
                layout.prop(props_polypen, 'quad_stability', slider=True)
            layout.separator()
            row = layout.row(align=True)
            row.label(text='Knife:')
            row.separator()
            row.prop(props_polypen, 'constrain_edge_vert', text='Constrain')
            row.prop(props_polypen, 'use_loop_cuts', text='Loop Cuts')
            if props_polypen.insert_mode in ('TRI/QUAD', 'QUAD-ONLY'):
                row.prop(props_polypen, 'quad_preserve', text='Junctions')

            draw_line_separator(layout)

            draw_tweaking_popover(context, layout, props_polypen)
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
            header, panel = layout.panel(idname='polypen_insert_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                panel.prop(props_polypen, 'insert_mode', text='Method')
                if props_polypen.insert_mode == 'QUAD-ONLY':
                    panel.prop(props_polypen, 'quad_stability', slider=True)
                col = panel.column(align=True)
                col.row(heading='Knife').prop(props_polypen, 'constrain_edge_vert', text='Constrain')
                col.prop(props_polypen, 'use_loop_cuts', text='Loop Cuts')
                if props_polypen.insert_mode in ('TRI/QUAD', 'QUAD-ONLY'):
                    col.prop(props_polypen, 'quad_preserve', text='Junctions')
            draw_tweaking_panel(context, layout)
            draw_snapping_panel(context, layout, idname='polypen_snapping_panel')
            draw_cleanup_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context : Context):
        # TODO: some of the following might not be needed since we are creating our
        #       own transform operators
        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter("PolyPen")
        if not prefs.setup_snapping:
            context.scene.retopoflow.snapping.projection = 'FOLLOW_BLENDER'
        else:
            sync_projection_from_blender(context)
        if prefs.setup_automerge:
            cls.resetter['context.tool_settings.use_mesh_automerge'] = True
        if context.scene.retopoflow.snapping.projection != 'FOLLOW_BLENDER':
            # cls.resetter['context.tool_settings.snap_elements_base'] = {'VERTEX'}
            cls.resetter.store('context.tool_settings.snap_elements_base')
            snap_elem = 'FACE_PROJECT' if context.scene.retopoflow.snapping.projection == 'SCREEN_SPACE' else 'FACE_NEAREST'
            cls.resetter['context.tool_settings.snap_elements_individual'] = {snap_elem}
        if prefs.setup_selection_mode:
            cls.resetter['context.tool_settings.mesh_select_mode'] = [True, True, False]

    @classmethod
    def deactivate(cls, context : Context):
        cls.resetter.reset()
