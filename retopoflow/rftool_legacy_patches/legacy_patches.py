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
from ...addon_common.common.blender import event_modifier_check
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

from .legacy_patches_logic import LegacyPatches_Logic, DrawGesture, PatchSettings, MAIN_OP_IDNAME, PATCH_SETTING_NAMES


# The main operator never runs (there is no stroke or brush), so RFCore.km_context stays 'init' and
# every keymap entry that should show in the status bar needs km_context 'init'.

class LegacyPatches_Properties:
    ''' Settings shared by the tool, where they are edited, and the fill operator, where the redo
    panel edits them again. '''

    split_angle: bpy.props.FloatProperty(
        name='Split Angle',
        description='How far the boundary must bend at a vertex for it to count as a corner between two strips',
        subtype='ANGLE',
        default=PatchSettings.split_angle,
        min=0.17453293,     # 10 degrees
        max=2.35619449,     # 135 degrees
    )
    smooth: bpy.props.IntProperty(
        name='Smooth',
        description='Relax passes applied to the new vertices before they are created, evening out the spacing of the interior loops. 0 keeps the pure interpolation',
        min=0,
        soft_max=10,
        max=50,
        default=PatchSettings.smooth,
    )

    # how densely a two-sided patch (a bridge or a loft) is filled across the gap; mirrors Contours
    span_insert_mode: bpy.props.EnumProperty(
        name='Span Count Method',
        description='Controls how many loops are created across a two-sided patch',
        items=[
            ('FIXED',   'Fixed',   'Uses the Crosses value exactly as set', 0),
            ('AVERAGE', 'Average', 'Matches the average edge length of the two sides so the new quads stay even', 1),
            ('LENGTH',  'Length',  'Sizes each loop to match a world space distance', 2),
        ],
        default=PatchSettings.span_insert_mode,
    )
    crosses: bpy.props.IntProperty(
        name='Crosses',
        description='Loops created between the two sides, not counting the sides themselves. 0 bridges them with a single band of quads',
        min=0,
        soft_max=32,
        max=256,
        default=PatchSettings.crosses,
    )
    span_length: bpy.props.FloatProperty(
        name='Segment Length',
        description='World space distance for each loop across a two-sided patch',
        default=PatchSettings.span_length,
        min=0.001,
        soft_max=10.0,
        subtype='DISTANCE',
    )

    # a loop with uneven sides or without four corners is filled like Blender's Grid Fill
    solution: bpy.props.IntProperty(
        name='Solution',
        description='Which way to divide a grid filled loop into quads. 1 is the automatic choice; higher values flip through the alternatives and wrap round',
        min=1,
        soft_max=16,
        default=PatchSettings.solution,
    )
    offset: bpy.props.IntProperty(
        name='Offset',
        description='Rotate the four corners of a grid filled patch around its loop',
        soft_min=-32,
        soft_max=32,
        default=PatchSettings.offset,
    )
    steps: bpy.props.IntProperty(
        name='Steps',
        description='Rows of quads to step outward from a boundary run that has nothing to fill',
        min=1,
        soft_max=16,
        max=256,
        default=PatchSettings.steps,
    )
    step_scale: bpy.props.FloatProperty(
        name='Distance',
        description=('How far each stepped row reaches, against the spacing of the run it steps from. '
                     'Only the rows that extrude are affected: one that lands on existing geometry still lands on it'),
        min=0.05,
        soft_min=0.25,
        soft_max=4.0,
        max=16.0,
        default=PatchSettings.step_scale,
    )
    twist: bpy.props.IntProperty(
        name='Twist',
        description='Rotate which vertex of one loop pairs with which vertex of the other when lofting',
        soft_min=-32,
        soft_max=32,
        default=PatchSettings.twist,
    )


class RFOperator_LegacyPatches(LegacyPatches_Properties, RFOperator):
    ''' Holds the tool's settings; the modal itself never runs. '''
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

    # no keymap of its own: RFOperator_LegacyPatches_Draw invokes this when a Ctrl+LMB click lands on a selected boundary vert
    rf_keymaps : RFKeyMaps = []

    def invoke(self, context : Context, event : Event) -> set[str]:
        result = LegacyPatches_Logic.toggle_corner(context, event)
        context.area.tag_redraw()
        return { 'FINISHED' } if result else { 'CANCELLED' }


def fill_patches_owns_f(context : Context) -> bool:
    ''' Whether F belongs to Patches here. Inside a Retopoflow tool it always does; anywhere else it
    is the artist's choice, the same one the pie menu offers. '''
    if context.mode != 'EDIT_MESH': return False
    prefs = RF_Prefs.get_prefs(context)
    if prefs.fill_tool_context == 'ANY_TOOL': return True
    tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
    return tool is not None and tool.idname.split('.')[0] == 'retopoflow'


class RFOperator_LegacyPatches_Fill(LegacyPatches_Properties, RFOperator_Execute):
    bl_idname : str = 'retopoflow.legacy_patches_fill'
    bl_label : str = 'Fill Patches'
    bl_description : str = ('Fill the holes bounded by the selected boundary edges. '
                            'Whatever this cannot fill falls through to Blender\'s own New Edge/Face')
    bl_options : BL_OPTIONS = { 'UNDO', 'REGISTER' }

    # An unspecified modifier in a tool keymap means "not held", so keys that must work while Ctrl is
    # down for the cursor pick need a Ctrl twin. F has none: Ctrl+F is Blender's Face menu. Ctrl+LMB
    # also fills, but lives in RFOperator_LegacyPatches_Draw, which owns the mouse while Ctrl is held.
    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'F',            'value': 'PRESS' },
          {'km_context': 'init', 'km_label': 'Fill', 'km_poll': lambda _context: bool(LegacyPatches_Logic.previz)} ),
        ( bl_idname, { 'type': 'RET',          'value': 'PRESS' }, None ),
        ( bl_idname, { 'type': 'RET',          'value': 'PRESS', 'ctrl': 1 }, None ),
        ( bl_idname, { 'type': 'NUMPAD_ENTER', 'value': 'PRESS' }, None ),
        ( bl_idname, { 'type': 'NUMPAD_ENTER', 'value': 'PRESS', 'ctrl': 1 }, None ),
    ]

    # set on the keymap item only, so fill_patches_owns_f governs the key and not the menu entry
    hotkey: bpy.props.BoolProperty(
        name='From Hotkey',
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def invoke(self, context : Context, event : Event) -> set[str]:
        # Outside a Retopoflow tool the key is the artist's unless they have said otherwise. The tool
        # keymaps, the menu entry and Enter carry no hotkey flag, so this never stands in their way.
        if self.hotkey and not fill_patches_owns_f(context):
            return { 'PASS_THROUGH' }

        # A fresh fill settles where the cursor was and whether Ctrl was down; a redo skips invoke and
        # keeps both, so changing Smooth or Steps after the fact cannot flip a wire run to its other side.
        # Once a quad is previewed it stays fillable, so Enter and the redo panel also count as Ctrl.
        LegacyPatches_Logic.mouse_locked = (event.mouse_x, event.mouse_y)
        LegacyPatches_Logic.ctrl_locked = (bool(event.ctrl) or LegacyPatches_Logic.nearest_active
                                           or LegacyPatches_Logic.ctrl_forced)

        # With nothing previewed, rebuild here: outside the tool no overlay keeps a preview alive, and
        # inside it the overlay may not have drawn yet.
        if not LegacyPatches_Logic.previz or LegacyPatches_Logic.tool_props(context) is None:
            try:
                LegacyPatches_Logic._recompute(context, LegacyPatches_Logic.read_settings(context))
            except ReferenceError:
                LegacyPatches_Logic._clear_products()
        # Still nothing: hand the key on so Blender's own fill gets it. This must be PASS_THROUGH from
        # invoke, not a failing poll: Blender re-checks poll before a redo, when the preview is empty.
        if not LegacyPatches_Logic.previz:
            return { 'PASS_THROUGH' }
        # a fresh fill starts from the tool's settings; a redo comes straight to execute with the redo panel's
        src = LegacyPatches_Logic.tool_props(context)
        if src:
            for name in PATCH_SETTING_NAMES:
                setattr(self, name, getattr(src, name))
        else:
            self.steps = PatchSettings.steps
            self.step_scale = PatchSettings.step_scale
        return self.execute(context)

    def execute(self, context : Context) -> set[str]:
        settings = PatchSettings(**{ name: getattr(self, name) for name in PATCH_SETTING_NAMES })
        if not LegacyPatches_Logic.fill(context, settings):
            self.report({'WARNING'}, 'Patches: nothing to fill. Select boundary edges forming a rectangle, L, C, two parallel strips, a single strip to step outward, or four vertices, or hold Ctrl and hover between four nearby vertices')
            return { 'CANCELLED' }
        context.area.tag_redraw()
        return { 'FINISHED' }

    def draw(self, context : Context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        draw_patches_props(layout, self, header=False, redo=True)


class RFOperator_LegacyPatches_EdgeFaceAdd(RFOperator_Execute):
    ''' Blender's own F, moved to Alt+F wherever Patches has taken F. Poll-gated on the same test, so
    where Patches does not own F this falls through to whatever Alt+F normally does. '''
    bl_idname : str = 'retopoflow.legacy_patches_edge_face_add'
    bl_label : str = 'New Edge/Face from Vertices'
    bl_description : str = 'Add an edge or face to the selected vertices'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = []     # its keymap item is registered with the fill's, in the Mesh keymap

    @classmethod
    def poll(cls, context : Context) -> bool:
        return poll_retopoflow(context) and fill_patches_owns_f(context)

    def execute(self, context : Context) -> set[str]:
        # `True` is the call's undo argument: this shim is INTERNAL and pushes nothing itself, so
        # without it the face lands with no undo step and no redo panel at all
        try:
            return bpy.ops.mesh.edge_face_add('INVOKE_DEFAULT', True)
        except RuntimeError:
            return { 'CANCELLED' }


class RFOperator_LegacyPatches_Draw(RFOperator):
    ''' Owns the mouse while Ctrl is held: a click fills the previewed patch or toggles a corner, a
    drag draws a path and creates whatever the cursor passes over.

    A modal rather than a Ctrl+LMB keymap item because Blender only synthesizes a CLICK when nothing
    took the PRESS, which made a CLICK binding unreliable. PolyPen, Strokes, Contours and PolyStrips
    take Ctrl+LMB the same way: a modal started by Ctrl PRESS that consumes the LMB PRESS and
    swallows the later CLICK so shortest-path select cannot fire on it. '''
    bl_idname : str = 'retopoflow.legacy_patches_draw'
    bl_label : str = 'Patches Draw'
    bl_description : str = 'Ctrl+LMB fills the previewed patch; Ctrl+LMB drag creates every patch the cursor passes over'
    bl_space_type : str = 'VIEW_3D'
    bl_region_type : str = 'TOOLS'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_patches_passive : bool = True    # only reads the mouse, so the preview may keep rebuilding while this runs

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, {'km_context': 'init', 'km_label': 'Pick / Draw'}),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),
        (bl_idname, {'type': 'MOUSEMOVE',  'value': 'ANY', 'ctrl': True}, None),    # Ctrl already down when the cursor enters the area
    ]

    gesture : DrawGesture | None = None

    @classmethod
    def can_start(cls, context : Context) -> bool:
        return not cls.is_running()

    def init(self, context : Context, event : Event):
        self.gesture = DrawGesture()

    def finish(self, context : Context):
        if self.gesture: self.gesture.finish(context)    # closes any drag in progress

    def update(self, context : Context, event : Event) -> set[str]:
        if not event.ctrl:
            return {'FINISHED'}
        ctrl_only = event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False)
        assert self.gesture
        ret = self.gesture.handle(context, event, accept_press=ctrl_only)
        return ret if ret is not None else {'PASS_THROUGH'}


# Ctrl+Scroll is the count knob and Shift+Scroll the offset knob, the same split Contours uses. What
# each drives depends on the preview: crosses and twist for a bridge or loft, solution and corner
# offset for a grid fill, steps for an offset. With nothing previewed, the fill just committed is
# re-run with the changed value instead, collapsing onto one undo step so its redo panel stays live.

def _refill_with(context : Context, last, **changes) -> bool:
    props = { name: getattr(last, name) for name in PATCH_SETTING_NAMES }
    props.update(changes)
    bpy.ops.ed.undo()
    return bpy.ops.retopoflow.legacy_patches_fill('EXEC_DEFAULT', True, **props) == {'FINISHED'}

def _last_fill(context : Context):
    ops = context.window_manager.operators
    last = ops[-1] if ops else None
    return last if last is not None and last.name == RFOperator_LegacyPatches_Fill.bl_label else None

def _scroll_count(context : Context, sign : int):
    L = LegacyPatches_Logic
    if L.adjust_count(context, sign): return
    last = _last_fill(context)
    if last is None: return
    was_bridge, was_grid, _, was_offset, was_quad = L.filled_flags
    if was_bridge:
        _refill_with(context, last, span_insert_mode='FIXED', crosses=max(0, L.filled_loops + sign))    # an explicit count stops deriving one
    elif was_grid:
        _refill_with(context, last, solution=(last.solution - 1 + sign) % L.filled_solutions + 1)
    elif was_quad:
        _refill_with(context, last, crosses=max(0, last.crosses + sign))
    elif was_offset:
        _refill_with(context, last, steps=max(1, last.steps + sign))   # a step normally leaves its next step previewed, so this only runs when that was refused

def _scroll_offset(context : Context, sign : int):
    L = LegacyPatches_Logic
    if L.adjust_offset(context, sign): return
    last = _last_fill(context)
    if last is not None:
        _, was_grid, was_loft, _, _ = L.filled_flags
        if was_grid or was_loft:
            which = 'offset' if was_grid else 'twist'
            _refill_with(context, last, **{which: getattr(last, which) + sign})
            return
        if L.filled_free_step:
            _refill_with(context, last, step_scale=L.scaled_step(last.step_scale, sign))
            return
    # nothing of ours to turn: topo-rotate the selection, when that can actually happen (it needs
    # selected faces with one closed perimeter, and raises or reports otherwise)
    if not bpy.ops.retopoflow.toporotate.poll(): return
    bm, _ = get_bmesh_emesh(context)
    bmfs = bmops.get_all_selected_bmfaces(bm)
    if not bmfs or not get_perimeter_bmedges(bmfs): return
    offset = sign
    ops = context.window_manager.operators
    last = ops[-1] if ops else None
    if last is not None and last.name == RFOperator_TopoRotate.bl_label:
        offset = last.offset + sign          # consecutive scrolls collapse onto one undo step
        bpy.ops.ed.undo()
    try:
        bpy.ops.retopoflow.toporotate('EXEC_DEFAULT', True, offset=offset)
    except RuntimeError:
        pass


class RFOperator_LegacyPatches_CountDecrease(RFOperator_Execute):
    bl_idname : str = 'retopoflow.legacy_patches_count_decrease'
    bl_label : str = 'Decrease Count'
    bl_description : str = 'Fill with one fewer segment across'
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    # only this half of the pair is labeled, so the status bar shows one "Adjust Count" entry. The
    # arrows do the same job with one hand, which is what holding F leaves you.
    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'ctrl': 1 },
          {'km_context': 'init', 'km_label': 'Adjust Count',
           'km_extra_icons': ['EVENT_DOWN_ARROW', 'EVENT_UP_ARROW']} ),
        ( bl_idname, { 'type': 'DOWN_ARROW', 'value': 'PRESS', 'repeat': True }, None ),
    ]

    def execute(self, context : Context) -> set[str]:
        _scroll_count(context, -1)
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
        _scroll_count(context, +1)
        context.area.tag_redraw()
        return { 'FINISHED' }


class RFOperator_LegacyPatches_OffsetDecrease(RFOperator_Execute):
    bl_idname : str = 'retopoflow.legacy_patches_offset_decrease'
    bl_label : str = 'Decrease Offset'
    bl_description : str = ('Rotate the loft pairing or grid fill corners one vertex back, shorten a stepped row '
                            'that extrudes, or topo-rotate the selection')
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'WHEELDOWNMOUSE', 'value': 'PRESS', 'shift': 1 }, {'km_context': 'init', 'km_label': 'Offset / Distance'} ),
    ]

    def execute(self, context : Context) -> set[str]:
        _scroll_offset(context, -1)
        context.area.tag_redraw()
        return { 'FINISHED' }


class RFOperator_LegacyPatches_OffsetIncrease(RFOperator_Execute):
    bl_idname : str = 'retopoflow.legacy_patches_offset_increase'
    bl_label : str = 'Increase Offset'
    bl_description : str = ('Rotate the loft pairing or grid fill corners one vertex forward, lengthen a stepped row '
                            'that extrudes, or topo-rotate the selection')
    bl_options : BL_OPTIONS = { 'INTERNAL' }

    rf_keymaps : RFKeyMaps = [
        ( bl_idname, { 'type': 'WHEELUPMOUSE', 'value': 'PRESS', 'shift': 1 }, None ),
    ]

    def execute(self, context : Context) -> set[str]:
        _scroll_offset(context, +1)
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
        LegacyPatches_Logic.mouse = (event.mouse_x, event.mouse_y)    # so a wire run can step toward the cursor before it moves

    def update(self, context : Context, event : Event) -> set[str]:
        if self.is_done(): return {'CANCELLED'}
        redraw = LegacyPatches_Logic.track_ctrl(context, event)    # every event carries the modifier state
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            if LegacyPatches_Logic.track_mouse(context, event): redraw = True
        if redraw and context.area:
            context.area.tag_redraw()    # passing an event through does not redraw on its own
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
    has_bridge, has_grid, has_loft, has_offset, has_quad = (
        L.filled_flags if redo else (L.has_bridge, L.has_grid, L.has_loft, L.has_offset, L.has_quad))

    if header:
        row = layout.row(align=True)
        row.prop(props, 'span_insert_mode', text='')
        if props.span_insert_mode == 'LENGTH':
            row.prop(props, 'span_length', text='')
        elif props.span_insert_mode == 'FIXED':
            row.prop(props, 'crosses', text='')
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
    if not redo or L.filled_smoothing:
        layout.prop(props, 'smooth')

    has_options = has_quad or has_offset or has_grid or has_loft
    if has_options:
        if header:
            layout.separator(type='LINE')
        elif not redo:
            layout.separator()
        if has_quad:
            layout.prop(props, 'crosses', text='Cuts')
        if has_offset:
            layout.prop(props, 'steps')
        if (L.filled_free_step if redo else L.has_free_step):
            layout.prop(props, 'step_scale')
        if has_grid:
            layout.prop(props, 'solution', text='Solution')
            layout.prop(props, 'offset', text='Offset')
        if has_loft:
            layout.prop(props, 'twist')
        if not header and not redo:
            layout.separator()

    if not redo and L.has_manual_corners:
        layout.operator(RFOperator_LegacyPatches_ClearCorners.bl_idname, icon='X')


class RFTool_LegacyPatches(RFTool_Base):
    bl_idname : str = 'retopoflow.legacy_patches'
    bl_label : str = 'Patches'
    bl_description : str = 'Fill holes bounded by selected boundary edge strips'
    bl_icon : str = get_path_to_blender_icon('patches')
    bl_widget : None = None

    rf_operator_idname : str | None = MAIN_OP_IDNAME
    rf_overlay : type[RFOverlay_Base] | None = RFOperator_LegacyPatches_Overlay

    props = None  # needed to reset properties

    # set while F is held from another tool: a look at a preview, not a tool switch, so the select mode is left alone
    quick_switch : bool = False

    bl_keymap : BLKeyMaps = chain_rf_keymaps(
        RFOperator_LegacyPatches,
        RFOperator_LegacyPatches_Draw,
        RFOperator_LegacyPatches_Fill,
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
            cls.resetter['context.tool_settings.mesh_select_mode'] = [True, True, False]    # v3 Patches worked on edge selections
        LegacyPatches_Logic.reset_session()

    @classmethod
    def deactivate(cls, context : Context):
        LegacyPatches_Logic.clear_corners(context)    # don't leave the corner-override layer in the user's mesh
        LegacyPatches_Logic.reset_session()
        if cls.resetter:
            cls.resetter.reset()


@execute_operator('switch_to_legacy_patches', 'RetopoFlow: Switch to Patches', fn_poll=poll_retopoflow)
def switch_rftool(context : Context):
    RFTool_LegacyPatches.activate_tool(context)


# F outside a Patches tool keymap: addon items in the Mesh keymap, which Blender checks before its
# own F. Both items stay put whatever the preference says; each hands the key back when it is not
# theirs, so it falls through to Blender's own F as if these were never here.
keymaps = []

def register():
    keyconfigs = bpy.context.window_manager.keyconfigs.addon
    if not keyconfigs: return
    km = keyconfigs.keymaps.new(name='Mesh')
    kmi = km.keymap_items.new(RFOperator_LegacyPatches_Fill.bl_idname, 'F', 'PRESS', ctrl=False, shift=False, alt=False)
    kmi.properties.hotkey = True
    keymaps.append((km, kmi))
    # Blender puts Fill on Alt+F, but with F taken there is nowhere else for New Edge/Face to go
    kmi = km.keymap_items.new(RFOperator_LegacyPatches_EdgeFaceAdd.bl_idname, 'F', 'PRESS', ctrl=False, shift=False, alt=True)
    keymaps.append((km, kmi))

def unregister():
    for km, kmi in keymaps:
        km.keymap_items.remove(kmi)
    keymaps.clear()
