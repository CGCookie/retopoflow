'''
Copyright (C) 2026 CG Cookie
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
# pyright: reportImplicitOverride = false
# pyright: reportUnusedParameter = false
# pyright: reportUnannotatedClassAttribute = false

import bpy
from bpy.types import (
    Context,
    UILayout,
    WorkSpaceTool,
    Event,
)

from ..rfglobals import RFGlobals
from ..rftool_base import RFTool_Base
from ..rfoverlay_base import RFOverlay_Base
from ..rfoverlays.overlays import overlay_names

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.resetter import Resetter

from ..common.bpy_helper import bpy_ops_retopoflow, BL_OPTIONS
from ..common.bmesh import get_bmesh_emesh
from ..common.icons import get_path_to_blender_icon
from ..common.interface import draw_line_separator
from ..common.operator import (
    execute_operator,
    RFOperator,
    RFOperator_Execute, RFOperator_Invoke,
    RFKeyMaps,
    chain_rf_keymaps,
    poll_retopoflow,
    BLKeyMaps,
)

from ..rfoperators.maximize_watcher import RFOperator_MaximizeWatcher
from ..rfoperators.quickswitch import RFOperator_Relax_QuickSwitch, RFOperator_Tweak_QuickSwitch
from ..rfoperators.topo_rotate import RFOperator_TopoRotate, get_perimeter_bmedges
from ..rfoperators.transform import RFOperator_Translate

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel, draw_tweaking_popover
from ..rfpanels.rfpanel_snapping import draw_snapping_panel
from ..rfpanels.mirror_panel import draw_mirror_panel, draw_mirror_popover
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.help_panel import draw_help_panel

from ..preferences import RF_Prefs

from .legacy_patches_logic import (
    LegacyPatches_Logic, PatchSettings, MAIN_OP_IDNAME, PATCH_SETTING_NAMES,
    DEFAULT_SPLIT_ANGLE, DEFAULT_SMOOTH, DEFAULT_SPAN_MODE, DEFAULT_CROSSES, DEFAULT_SPAN_LENGTH,
    DEFAULT_STEPS,
)


# The main operator never runs (there is no stroke or brush), so RFCore.km_context stays 'init'
# and every keymap entry that should show in the status bar needs km_context 'init'.

class LegacyPatches_Properties:
    '''
    Settings shared between the tool (where they are edited) and the fill operator (where the
    redo panel edits them again after the fact). Kept in one place so the two cannot drift.
    '''

    split_angle: bpy.props.FloatProperty(
        name='Split Angle',
        description='How far the boundary must bend at a vertex for it to count as a corner between two strips',
        subtype='ANGLE',
        default=DEFAULT_SPLIT_ANGLE,
        min=0.17453293,     # 10 degrees
        max=2.35619449,     # 135 degrees
    )
    smooth: bpy.props.IntProperty(
        name='Smooth',
        description='Relax passes applied to the new vertices before they are created, evening out the spacing of the interior loops. 0 keeps the pure interpolation',
        min=0,
        soft_max=10,
        max=50,
        default=DEFAULT_SMOOTH,
    )

    # how densely a two-sided patch (a bridge between parallel strips, or a loft between two
    # loops) is filled across the gap. Mirrors the span methods in Contours.
    span_insert_mode: bpy.props.EnumProperty(
        name='Span Count Method',
        description='Controls how many loops are created across a two-sided patch',
        items=[
            ('FIXED',   'Fixed',   'Uses the Crosses value exactly as set', 0),
            ('AVERAGE', 'Average', 'Matches the average edge length of the two sides so the new quads stay even', 1),
            ('LENGTH',  'Length',  'Sizes each loop to match a world space distance', 2),
        ],
        default=DEFAULT_SPAN_MODE,
    )
    crosses: bpy.props.IntProperty(
        name='Crosses',
        description='Loops created between the two sides, not counting the sides themselves. 0 bridges them with a single band of quads',
        min=0,
        soft_max=32,
        max=256,
        default=DEFAULT_CROSSES,
    )
    span_length: bpy.props.FloatProperty(
        name='Segment Length',
        description='World space distance for each loop across a two-sided patch',
        default=DEFAULT_SPAN_LENGTH,
        min=0.001,
        soft_max=10.0,
        subtype='DISTANCE',
    )

    # a loop whose sides are uneven, or that does not have four corners, is filled the way
    # Blender's Grid Fill does it: as a rectangle of quads, with the corners placed around the loop
    solution: bpy.props.IntProperty(
        name='Solution',
        description='Which way to divide a grid filled loop into quads. 1 is the automatic choice; higher values flip through the alternatives and wrap round',
        min=1,
        soft_max=16,
        default=1,
    )
    offset: bpy.props.IntProperty(
        name='Offset',
        description='Rotate the four corners of a grid filled patch around its loop',
        soft_min=-32,
        soft_max=32,
        default=0,
    )
    # a run of boundary edges with nothing to fill steps outward instead, by this many rows
    steps: bpy.props.IntProperty(
        name='Steps',
        description='Rows of quads to step outward from a boundary run that has nothing to fill',
        min=1,
        soft_max=16,
        max=256,
        default=DEFAULT_STEPS,
    )
    twist: bpy.props.IntProperty(
        name='Twist',
        description='Rotate which vertex of one loop pairs with which vertex of the other when lofting',
        soft_min=-32,
        soft_max=32,
        default=0,
    )


class RFOperator_LegacyPatches(LegacyPatches_Properties, RFOperator):
    # holds the tool's settings; the modal itself never runs
    bl_idname = MAIN_OP_IDNAME
    bl_label = 'Patches'
    bl_description = 'Fill holes bounded by selected boundary edge strips'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()

    loop_select_op = 'mesh.select_edge_loop_multi' if bpy.app.version >= (5, 1, 0) else 'mesh.loop_multi_select'

    rf_keymaps = [
        (loop_select_op, {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, {'km_context': 'init', 'km_label': 'Select Loop'}),
    ]

    def init(self, context : Context, event : Event):
        pass

    def finish(self, context : Context):
        pass

    def update(self, context : Context, event : Event) -> set[str]:
        return {'PASS_THROUGH'}


class RFOperator_LegacyPatches_ToggleCorner(RFOperator_Invoke):
    bl_idname : str = 'retopoflow.legacy_patches_toggle_corner'
    bl_label : str = 'Toggle Corner'
    bl_description : str = 'Toggle whether the hovered selected vertex is treated as a corner between strips'
    bl_options : BL_OPTIONS = { 'INTERNAL', 'UNDO', 'DEPENDS_ON_CURSOR' }

    rf_keymaps : RFKeyMaps = [
        (bl_idname, { 'type': 'LEFTMOUSE', 'value': 'CLICK', 'ctrl': 1, 'shift': 0 }, {'km_context': 'init', 'km_label': 'Toggle Corner'}),
        # keeps a fast double Ctrl+click from falling through to object selection
        (bl_idname, { 'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK', 'ctrl': 1, 'shift': 0 }, None),
    ]

    def invoke(self, context : Context, event : Event) -> set[str]:
        result = LegacyPatches_Logic.toggle_corner(context, event)
        context.area.tag_redraw()
        return { 'FINISHED' } if result else { 'CANCELLED' }


class RFOperator_LegacyPatches_Fill(LegacyPatches_Properties, RFOperator_Execute):
    bl_idname : str = 'retopoflow.legacy_patches_fill'
    bl_label : str = 'Fill Patch'
    bl_description : str = 'Create the previewed patch geometry'
    bl_options : BL_OPTIONS = { 'INTERNAL', 'UNDO', 'REGISTER' }

    # An unspecified modifier in a tool keymap means "not held", so the keys that have to work while
    # Ctrl is down for the cursor pick need a Ctrl twin of their own. F deliberately has none: Ctrl+F
    # is Blender's Face menu.
    # Ctrl+LMB is the other way to confirm, and it lives here rather than in an operator of its own
    # so that the click runs the very same fill the keys do, with one undo step and one redo panel.
    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'F',            'value': 'PRESS' },
          {'km_context': 'init', 'km_label': 'Fill', 'km_poll': lambda _context: bool(LegacyPatches_Logic.previz)} ),
        ( bl_idname, { 'type': 'RET',          'value': 'PRESS' }, None ),
        ( bl_idname, { 'type': 'RET',          'value': 'PRESS', 'ctrl': 1 }, None ),
        ( bl_idname, { 'type': 'NUMPAD_ENTER', 'value': 'PRESS' }, None ),
        ( bl_idname, { 'type': 'NUMPAD_ENTER', 'value': 'PRESS', 'ctrl': 1 }, None ),
        ( bl_idname, { 'type': 'LEFTMOUSE',    'value': 'CLICK', 'ctrl': 1, 'shift': 0 },
          {'km_context': 'init', 'km_label': 'Confirm',
           'km_poll': lambda _context: bool(LegacyPatches_Logic.previz)} ),
    ]

    def invoke(self, context : Context, event : Event) -> set[str]:
        # Clicking is only a fill when the cursor is on the previewed patch; anywhere else the click
        # belongs to Toggle Corner, and after that to Blender's own selection. PASS_THROUGH hands it
        # on, the same way an empty preview hands the F key back below.
        if event.type == 'LEFTMOUSE' and not LegacyPatches_Logic.mouse_over_previz(context):
            return { 'PASS_THROUGH' }

        # A fresh fill settles where the cursor was; a redo comes straight to execute and keeps that,
        # so changing Smooth or Steps after the fact cannot flip a wire run over to its other side.
        # Window space, to match what the overlay records.
        LegacyPatches_Logic.mouse_locked = (event.mouse_x, event.mouse_y)
        # `or nearest_active`: the Ctrl gate is about searching, not about filling. Once a quad is
        # previewed it stays fillable, so Enter (which cannot carry Ctrl on its own entry) and the
        # redo panel long afterwards both still rebuild it.
        LegacyPatches_Logic.ctrl_locked = bool(event.ctrl) or LegacyPatches_Logic.nearest_active

        # With nothing previewed, hand the key on so Blender's own fill gets it. This has to be
        # PASS_THROUGH from invoke, not a failing poll: Blender re-checks poll before repeating an
        # operator, and after a fill the preview is empty, so a poll would refuse every redo.
        if not LegacyPatches_Logic.previz or LegacyPatches_Logic.tool_props(context) is None:
            # Work out the patch now. Outside the Patches tool there is no overlay keeping a preview
            # alive, so whatever is cached is stale; inside it, an empty preview may simply mean the
            # overlay has not drawn yet. Either way the fill does not need a preview to do its job.
            try:
                LegacyPatches_Logic._recompute(context, LegacyPatches_Logic.read_settings(context))
            except ReferenceError:
                LegacyPatches_Logic._clear_products()
        if not LegacyPatches_Logic.previz:
            return { 'PASS_THROUGH' }
        # a fresh fill starts from whatever the tool is set to; a redo skips invoke and comes
        # straight to execute with the values the redo panel is showing
        src = LegacyPatches_Logic.tool_props(context)
        if src:
            for name in PATCH_SETTING_NAMES:
                setattr(self, name, getattr(src, name))
        return self.execute(context)

    def execute(self, context : Context) -> set[str]:
        settings = PatchSettings(
            split_angle = self.split_angle,
            smooth      = self.smooth,
            span_mode   = self.span_insert_mode,
            crosses     = self.crosses,
            span_length = self.span_length,
            solution    = self.solution,
            offset      = self.offset,
            twist       = self.twist,
            steps       = self.steps,
        )
        if not LegacyPatches_Logic.fill(context, settings):
            self.report({'WARNING'}, 'Patches: nothing to fill. Select boundary edges forming a rectangle, L, C, two parallel strips, or a single strip to step outward, or hover between four nearby vertices')
            return { 'CANCELLED' }
        context.area.tag_redraw()
        return { 'FINISHED' }

    def draw(self, context : Context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        draw_patches_props(layout, self, header=False, redo=True)


# Ctrl+Scroll is the count knob and Shift+Scroll the offset knob, the same split Contours uses.
# What each one drives depends on the selection: crosses and twist for a bridge or loft, span and
# corner offset for a grid fill.

class RFOperator_LegacyPatches_CountDecrease(RFOperator_Execute):
    bl_idname : str = 'retopoflow.legacy_patches_count_decrease'
    bl_label : str = 'Decrease Count'
    bl_description : str = 'Fill with one fewer segment across'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    # The status bar shows one "Adjust Count" entry, so only this half of the pair is labeled.
    # The arrows do the same job with one hand, which is what F held down leaves you.
    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1 },
          {'km_context': 'init', 'km_label': 'Adjust Count',
           'km_extra_icons': ['EVENT_DOWN_ARROW', 'EVENT_UP_ARROW']} ),
        ( bl_idname, { 'type': 'DOWN_ARROW', 'value': 'PRESS', 'repeat': True }, None ),
    ]

    def execute(self, context : Context) -> set[str]:
        _ctrl_scroll(context, -1)
        context.area.tag_redraw()
        return { 'FINISHED' }


class RFOperator_LegacyPatches_CountIncrease(RFOperator_Execute):
    bl_idname : str = 'retopoflow.legacy_patches_count_increase'
    bl_label : str = 'Increase Count'
    bl_description : str = 'Fill with one more segment across'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'WHEELUPMOUSE', 'value': 'PRESS', 'ctrl': 1 }, None ),
        ( bl_idname, { 'type': 'UP_ARROW', 'value': 'PRESS', 'repeat': True }, None ),
    ]

    def execute(self, context : Context) -> set[str]:
        _ctrl_scroll(context, +1)
        context.area.tag_redraw()
        return { 'FINISHED' }


def _redo_fill_with(context : Context, last, **changes) -> bool:
    ''' Re-run the fill just committed with some of its settings changed, collapsing onto one undo
    step so the redo panel stays live and consecutive scrolls do not pile up undo history. '''
    props = { name: getattr(last, name) for name in PATCH_SETTING_NAMES }
    props.update(changes)
    bpy.ops.ed.undo()
    return bpy.ops.retopoflow.legacy_patches_fill('EXEC_DEFAULT', True, **props) == {'FINISHED'}


def _ctrl_scroll(context : Context, sign : int):
    ''' Ctrl+Scroll changes the count that applies: the previewed patch's crosses, solution or steps;
    failing that, the same count on the fill just committed, while its redo panel is reachable. '''
    L = LegacyPatches_Logic
    if L.adjust_count(context, sign):
        return
    ops = context.window_manager.operators
    last = ops[-1] if ops else None
    if last is None or last.name != RFOperator_LegacyPatches_Fill.bl_label:
        return
    was_bridge, was_grid, _, was_offset = L.filled_flags
    if was_bridge:
        # scrolling is an explicit count, so the re-run stops deriving one over the top of it
        _redo_fill_with(context, last, span_insert_mode='FIXED', crosses=max(0, L.filled_loops + sign))
    elif was_grid:
        _redo_fill_with(context, last, solution=(last.solution - 1 + sign) % L.filled_solutions + 1)
    elif was_offset:
        # a step normally leaves its next step previewed, so this only runs when that one was refused
        _redo_fill_with(context, last, steps=max(1, last.steps + sign))


def _shift_scroll(context : Context, sign : int):
    ''' Shift+Scroll does the most useful rotation available, the way Contours' twist does:
    turn the previewed patch's offset or twist; failing that, re-run the fill just committed with
    its offset or twist changed, collapsing onto one undo step while the redo panel is still
    reachable; failing that, topo-rotate the selection.
    '''
    L = LegacyPatches_Logic
    if L.adjust_offset(context, sign):
        return

    ops = context.window_manager.operators
    last = ops[-1] if ops else None

    if last is not None and last.name == RFOperator_LegacyPatches_Fill.bl_label:
        _, was_grid, was_loft, _ = L.filled_flags
        if was_grid or was_loft:
            which = 'offset' if was_grid else 'twist'
            _redo_fill_with(context, last, **{which: getattr(last, which) + sign})
            return

    # Nothing of ours to turn: rotate the topology of whatever is selected instead, and only when
    # that can actually happen. Topo Rotate needs selected faces with one closed perimeter; asking
    # it otherwise raises or reports an error, and a scroll that applies to nothing should do nothing.
    if not bpy.ops.retopoflow.toporotate.poll():
        return
    bm, _ = get_bmesh_emesh(context)
    bmfs = bmops.get_all_selected_bmfaces(bm)
    if not bmfs or not get_perimeter_bmedges(bmfs):
        return
    offset = sign
    if last is not None and last.name == RFOperator_TopoRotate.bl_label:
        offset = last.offset + sign          # consecutive scrolls collapse onto one undo step
        bpy.ops.ed.undo()
    try:
        bpy.ops.retopoflow.toporotate('EXEC_DEFAULT', True, offset=offset)
    except RuntimeError:
        pass


class RFOperator_LegacyPatches_OffsetDecrease(RFOperator_Execute):
    bl_idname : str = 'retopoflow.legacy_patches_offset_decrease'
    bl_label : str = 'Decrease Offset'
    bl_description : str = 'Rotate the loft pairing or grid fill corners one vertex back, or topo-rotate the selection'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'shift': 1 }, {'km_context': 'init', 'km_label': 'Offset / Topo Rotate'} ),
    ]

    def execute(self, context : Context) -> set[str]:
        _shift_scroll(context, -1)
        context.area.tag_redraw()
        return { 'FINISHED' }


class RFOperator_LegacyPatches_OffsetIncrease(RFOperator_Execute):
    bl_idname : str = 'retopoflow.legacy_patches_offset_increase'
    bl_label : str = 'Increase Offset'
    bl_description : str = 'Rotate the loft pairing or grid fill corners one vertex forward, or topo-rotate the selection'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'WHEELUPMOUSE', 'value': 'PRESS', 'shift': 1 }, None ),
    ]

    def execute(self, context : Context) -> set[str]:
        _shift_scroll(context, +1)
        context.area.tag_redraw()
        return { 'FINISHED' }


class RFOperator_LegacyPatches_ClearCorners(RFOperator_Execute):
    bl_idname : str = 'retopoflow.legacy_patches_clear_corners'
    bl_label : str = 'Reset Corners'
    bl_description : str = 'Forget all manually toggled corners'
    bl_options : BL_OPTIONS = { 'INTERNAL', 'UNDO' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'ESC', 'value': 'PRESS' }, {'km_context': 'init', 'km_label': 'Clear Corners'} ),
    ]

    def execute(self, context : Context) -> set[str]:
        if not LegacyPatches_Logic.clear_corners(context): return { 'CANCELLED' }
        context.area.tag_redraw()
        return { 'FINISHED' }


class RFOperator_LegacyPatches_Overlay(RFOverlay_Base, RFOperator):
    bl_idname : str = 'retopoflow.legacy_patches_overlay'
    bl_label : str = 'Legacy Patches Overlay'
    bl_description : str = 'Previews the patches that Fill will create from the selected boundary edges'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    def is_done(self):
        RFCore = RFGlobals.RFCore_None
        return RFCore.selected_RFTool_idname != RFTool_LegacyPatches.bl_idname if RFCore else True

    @classmethod
    def activate(cls):
        _ = bpy_ops_retopoflow('legacy_patches_overlay', 'INVOKE_DEFAULT')

    def init(self, _context : Context, event : Event):
        LegacyPatches_Logic.reset_session()
        # so a wire run can step toward the cursor before it has moved
        LegacyPatches_Logic.mouse = (event.mouse_x, event.mouse_y)

    def update(self, context : Context, event : Event) -> set[str]:
        if self.is_done(): return {'CANCELLED'}
        # every event carries the modifier state, so Ctrl is picked up even when the mouse is still
        redraw = LegacyPatches_Logic.track_ctrl(context, event)
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            # passing an event through does not redraw, so a step that changed sides has to ask
            if LegacyPatches_Logic.track_mouse(context, event): redraw = True
        if redraw and context.area:
            context.area.tag_redraw()
        return {'PASS_THROUGH'}

    def draw_postpixel_overlay(self):
        if self.is_done(): return
        context = bpy.context
        LegacyPatches_Logic.update(context)
        LegacyPatches_Logic.draw(context)

# AutoSave skips saving while a modal operator is top-most unless it is a known overlay (keyed by label)
overlay_names.add(RFOperator_LegacyPatches_Overlay.bl_label)


def draw_patches_props(layout : UILayout, props, *, header : bool, redo : bool = False):
    L = LegacyPatches_Logic
    has_bridge, has_grid, has_loft, has_offset = (
        L.filled_flags if redo else (L.has_bridge, L.has_grid, L.has_loft, L.has_offset))

    if header and not redo:
        row = layout.row(align=True)
        row.prop(props, 'span_insert_mode', text='')
        if props.span_insert_mode == 'LENGTH':
            row.prop(props, 'span_length', text='')
        elif props.span_insert_mode == 'FIXED':
            row.prop(props, 'crosses', text='')
        layout.prop(props, 'split_angle', text='Split Angle')
        layout.prop(props, 'smooth')
        if has_offset:
            layout.prop(props, 'steps')
        if has_grid:
            layout.prop(props, 'solution', text='Solution')
            layout.prop(props, 'offset', text='Offset')
        if has_loft:
            layout.prop(props, 'twist')
        if LegacyPatches_Logic.has_manual_corners:
            layout.operator(RFOperator_LegacyPatches_ClearCorners.bl_idname, icon='X')
    else:
        layout.use_property_decorate = False
        layout.use_property_split = True
        if not redo or has_bridge:
            layout.prop(props, 'span_insert_mode', text='Method')
            if props.span_insert_mode == 'LENGTH':
                layout.prop(props, 'span_length', text='Distance')
            elif props.span_insert_mode == 'FIXED':
                layout.prop(props, 'crosses', text='Count')
        if not redo:
            layout.prop(props, 'split_angle', text='Split Angle')
        layout.prop(props, 'smooth')
        if has_offset:
            layout.prop(props, 'steps')
        if has_grid:
            layout.prop(props, 'solution', text='Solution')
            layout.prop(props, 'offset', text='Offset')
        if has_loft:
            layout.prop(props, 'twist')
        if not redo:
            if LegacyPatches_Logic.has_manual_corners:
                layout.operator(RFOperator_LegacyPatches_ClearCorners.bl_idname, icon='X')


class RFTool_LegacyPatches(RFTool_Base):
    bl_idname : str = 'retopoflow.legacy_patches'
    bl_label : str = 'Patches'
    bl_description : str = 'Fill holes bounded by selected boundary edge strips'
    bl_icon : str = get_path_to_blender_icon('patches')
    bl_widget : None = None

    rf_operator_idname : str | None = MAIN_OP_IDNAME

    props = None  # needed to reset properties

    # set while F is held from another tool: the artist is looking at a preview, not switching tools,
    # so the select mode is left exactly as they had it
    quick_switch : bool = False

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_LegacyPatches,
        # Fill first: it and Toggle Corner share Ctrl+LMB, and Fill is the one that hands the click
        # on when the cursor is not on a patch
        RFOperator_LegacyPatches_Fill,
        RFOperator_LegacyPatches_ToggleCorner,
        RFOperator_LegacyPatches_CountDecrease,
        RFOperator_LegacyPatches_CountIncrease,
        RFOperator_LegacyPatches_OffsetDecrease,
        RFOperator_LegacyPatches_OffsetIncrease,
        RFOperator_LegacyPatches_ClearCorners,
        RFOperator_MaximizeWatcher,
        RFOperator_Translate,
        RFOperator_TopoRotate,
        RFOperator_Relax_QuickSwitch,
        RFOperator_Tweak_QuickSwitch,
    )

    rf_overlay : type[RFOverlay_Base] | None = RFOperator_LegacyPatches_Overlay

    @staticmethod
    def draw_settings(context : Context, layout : UILayout, tool : WorkSpaceTool):
        prefs = RF_Prefs.get_prefs(context)
        props = tool.operator_properties(RFOperator_LegacyPatches.bl_idname)
        RFTool_LegacyPatches.props = props

        if context.region.type == 'TOOL_HEADER':
            draw_patches_props(layout, props, header=True)
            draw_line_separator(layout)
            draw_tweaking_popover(context, layout, props)
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
            header, panel = layout.panel(idname='legacy_patches_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                draw_patches_props(panel, props, header=False)

            draw_tweaking_panel(context, layout)
            draw_snapping_panel(context, layout, idname='legacy_patches_snapping_panel')
            draw_cleanup_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context : Context):
        prefs = RF_Prefs.get_prefs(context)
        cls.resetter = Resetter('LegacyPatches')
        if prefs.setup_selection_mode and not cls.quick_switch:
            # v3 Patches worked on edge selections
            cls.resetter['context.tool_settings.mesh_select_mode'] = [False, True, False]
        LegacyPatches_Logic.reset_session()

    @classmethod
    def deactivate(cls, context : Context):
        # don't leave the corner-override attribute behind in the user's mesh
        LegacyPatches_Logic.clear_corners(context)
        LegacyPatches_Logic.reset_session()
        if cls.resetter:
            cls.resetter.reset()


@execute_operator('switch_to_legacy_patches', 'RetopoFlow: Switch to Patches', fn_poll=poll_retopoflow)
def switch_rftool(context : Context):
    RFTool_LegacyPatches.activate_tool(context)
