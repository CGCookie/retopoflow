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

from __future__ import annotations

import time

import bpy
from mathutils import Vector, Matrix
from bpy.types import Context, Event
from bpy_extras.view3d_utils import location_3d_to_region_2d

from typing import ClassVar
from collections.abc import Sequence

from ..rfoverlay_base import RFOverlay_Base
from .overlays import overlay_names
from .curve_chain_providers import ChainProvider, ChainSpec

from ..rfglobals import RFGlobals
from ..common.bpy_helper import bpy_ops_retopoflow
from ..common.operator import RFOperator
from ..rftool_statusbar import SharedStatusbarKeymap
from ..common.bmesh import get_bmesh_emesh
from ..common.curve_fit import derive_centerline_knots, density_to_bend_tolerance
from ..common.maths import map_range, clamp
from ..common.drawing import Drawing
from ..common.raycast import is_point_hidden, mouse_from_event
from ...addon_common.common.bezier import CubicBezier, CubicBezierSpline
from ...addon_common.common.blender_cursors import Cursors


# AUTO_KNOT_MAX_SPAN_FACTOR and CORNER_MIN_SPACING_FACTOR (the auto-knot span
# and min corner spacing, both fractions of the chain's own total length) moved
# to common/curve_fit.py along with the knot-derivation logic that uses them.

# on-screen radii (pre Drawing.scale) of the knot/tangent handle dots, also used
# to shorten the control-polygon arm lines so they stop at each dot's edge
# instead of running into its (partially transparent) center
KNOT_RADIUS = 14
TANGENT_RADIUS = 12
# shared draw colors for the curve/handles -- used here AND by the shared
# curve-edit operator's own live-drag preview (rfoperators/curve_edit.py), so a
# handle can't visibly change color the instant a drag starts just because
# the two draw call sites drifted out of sync with each other
CURVE_LINE_COLOR = (1.0, 1.0, 0.0, 0.5)
CONTROL_POLYGON_COLOR = (1.0, 1.0, 1.0, 0.5)
TANGENT_FILL_COLOR = (0.0, 0.0, 0.0, 0.75)
TANGENT_BORDER_COLOR = (1.0, 1.0, 1.0, 0.5)
KNOT_FILL_COLOR = (1.0, 1.0, 1.0, 1.0)
KNOT_BORDER_COLOR = (0.0, 0.0, 0.0, 0.5)
# a knot whose position is NOT coupled to any vertex (see _build_handles) is
# distinguished by fill only -- its border tint is the same as a normal knot's
FREE_KNOT_FILL_COLOR = (0.5, 0.5, 0.5, 1.0)
# a knot resolved as 'automatic' (see the handle-type system in _build_curve)
# -- called out in bright yellow, distinct from free/coupled fill, so it's
# easy to spot which knots are self-recomputing vs frozen while testing
AUTO_KNOT_FILL_COLOR = (1, 1, 1, 1.0)
# an Automatic knot's own tangent handles (dots + control-polygon spokes) are
# hidden by default -- they're fully recomputed from neighbor geometry every
# frame (see _recompute_typed_handles in curve_edit.py), so showing them to
# the user invites dragging something that's about to be overwritten. Flip on
# to see them anyway while debugging that recompute.
DEBUG_SHOW_AUTO_HANDLES = False
# once a chain's knot placement (corners/auto-knots) is derived, it's cached and
# reused -- recomputing positions/handle lengths from current verts every time,
# but NOT re-running corner-detection -- so edits don't cause the control points
# themselves to jump to different verts. Only a single-vert displacement beyond
# this many average edge lengths (since the structure was last derived) forces a
# full structural rebuild.
REBUILD_DEVIATION_FACTOR = 4.0
# a segment is left untouched by a refit -- instead of being refit fresh -- if
# its interior verts already average less deviation from its existing curve
# than this fraction of the average edge length (see _well_fit_segments).
SEGMENT_KEEP_FIT_TOLERANCE = 1
# minimum seconds between rebuilds triggered by curve_handle_density/
# curve_corner_angle changing -- dragging either fires far more update_data
# calls than there are actual distinct values worth rebuilding for, so a
# rebuild mid-drag is throttled to this rate instead of running on every
# single tick; whichever value the slider is at once the throttle window
# elapses is what gets built (see update_data), not every value skipped over.
TUNABLE_REBUILD_THROTTLE = 0.1


def _internal_bl_idname(dotted_idname : str) -> str:
    '''
    Blender registers an operator's *internal* name as 'CATEGORY_OT_name',
    distinct from the dotted 'category.name' form used in Python source (as
    a class's own bl_idname, or to call bpy.ops.category.name()) -- items in
    context.window.modal_operators expose the former, not the latter, so
    comparing against a literal 'retopoflow.core' there would never match.
    '''
    category, _, name = dotted_idname.partition('.')
    return f'{category.upper()}_OT_{name}'


# RFCore's own always-running top-level modal operator -- see update_data's
# check against context.window.modal_operators.
RFCORE_OPERATOR_BL_IDNAME = _internal_bl_idname('retopoflow.core')


def shrink_segment(p_from, p_to, shrink_from, shrink_to):
    ''' Pulls both ends of a 2D screen-space segment in along its own direction
    by `shrink_from`/`shrink_to` pixels, so a line into a handle dot stops at the
    dot's edge instead of its center. '''
    if p_from is None or p_to is None:
        return p_from, p_to
    d = p_to - p_from
    length = d.length
    if length < 1e-6:
        return p_from, p_to
    d = d / length
    sf = min(shrink_from, length / 2)
    st = min(shrink_to, length / 2)
    return p_from + d * sf, p_to - d * st


def get_label_pos(context : Context, lbl : str, cos : Sequence[Vector]) -> Vector | None:
    if not context.edit_object:
        return None
    M = context.edit_object.matrix_world
    rgn, r3d = context.region, context.region_data

    pts = [pt for pt in cos if not is_point_hidden(context, pt)]
    if not pts:
        pts = list(cos)
    if not pts:
        return None

    if lbl == 'Loop':
        pts2d = [p2d for pt in pts if (p2d := location_3d_to_region_2d(rgn, r3d, M @ pt))]
        return max(pts2d, default=None, key=lambda p2d: p2d.y)

    mid = sum(pts, Vector((0,0,0))) / len(pts)
    pt3d = min(pts, key=lambda pt: (pt - mid).length)
    return location_3d_to_region_2d(rgn, r3d, M @ pt3d)


def create_curve_overlay(
    opname : str,
    rftool_idname : str,
    idname : str,
    label : str,
    providers : Sequence[ChainProvider],
) -> type[RFOverlay_Base]:

    overlay_names.add(label)

    class RFOperator_Curve_Overlay(RFOverlay_Base):
        bl_idname : ClassVar[str] = f'retopoflow.{idname}'
        bl_label : ClassVar[str] = label
        bl_description : ClassVar[str] = 'Overlay curve control handles for selected loops and strips'
        bl_options : ClassVar[set[str]] = { 'INTERNAL' }

        instance : ClassVar[object | None] = None
        depsgraph_version : ClassVar[int] = -42
        paused_update : ClassVar[bool] = False
        paused_overlay : ClassVar[bool] = False

        hovering : tuple[int, int, list] | None = None  # (chain_index, handle_index, control-point snapshot)

        curves : list[CubicBezierSpline]
        chains : list[dict]
        label_data : list[tuple[str, int, list[Vector]]]

        @classmethod
        def pause_update(cls):
            cls.paused_update = True
        @classmethod
        def unpause_update(cls):
            cls.paused_update = False

        @classmethod
        def pause_overlay(cls):
            cls.paused_overlay = True
        @classmethod
        def unpause_overlay(cls):
            cls.paused_overlay = False

        @classmethod
        def activate(cls):
            _ = bpy_ops_retopoflow(idname, 'INVOKE_DEFAULT')

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            cls = type(self)
            cls.instance = self
            cls.depsgraph_version = -42
            self.curves = []
            self.chains = []
            self.label_data = []
            self._curve_struct_cache = {}  # cache_key -> {'knots','corner_set','cos'}
            # cache_key -> {vert_index -> 'aligned'|'vector'|'automatic'} -- a
            # user's explicit handle-type choice (V-key toggle) or implicit
            # choice (dragging a tangent handle by hand pins it 'aligned'; see
            # curve_edit.py). Absent entries resolve to a default in
            # _build_curve (forced 'vector' for a sharp/endpoint knot,
            # 'automatic' otherwise) -- see resolve_type there. Kept OUTSIDE
            # _curve_struct_cache (which is a memoized BUILD RESULT, rebuilt
            # wholesale on a structural change) because this is externally-
            # mutated, always-current desired state, analogous to a scene
            # property -- see _build_curve's tunables fold-in for how a
            # change here still forces a rebuild
            self._handle_type_overrides = {}

        def init(self, _context : Context, _event : Event):
            cls = type(self)
            cls.depsgraph_version = -42
            cls.instance = self

        def finish(self, _context : Context):
            cls = type(self)
            cls.instance = None

        def update(self, context : Context, event : Event) -> set[str]:
            RFCore = RFGlobals.RFCore_None
            if not RFCore:
                return {'CANCELLED'}
            if RFCore.selected_RFTool_idname != rftool_idname:
                return {'CANCELLED'}
            if self.paused_overlay:
                return {'PASS_THROUGH'}

            mouse = mouse_from_event(event)
            was_hovering = self.hovering
            self.hovering = self.hovered_handle(context, mouse)
            if self.hovering:
                if not was_hovering:
                    # Alt/Alt+Shift work the same whether a knot or one of
                    # its tangent handles is hovered -- grabbing a tangent
                    # redirects to its own knot (see apply_handle /
                    # _knot_for_tangent), so the hint doesn't need to
                    # branch on which kind is under the mouse
                    self.set_statusbar_override((
                        SharedStatusbarKeymap(label='Edit Curve', icons=['MOUSE_LMB_DRAG']),
                        SharedStatusbarKeymap(label='Scale Control Point', icons=['EVENT_ALT', 'MOUSE_LMB_DRAG']),
                        SharedStatusbarKeymap(label='Rotate Control Point', icons=['EVENT_ALT', 'EVENT_SHIFT', 'MOUSE_LMB_DRAG']),
                    ))
                Cursors.set('hand')
            else:
                if was_hovering:
                    self.set_statusbar_override(None)
                Cursors.restore()

            return {'PASS_THROUGH'}

        # ------------------------------------------------------------------ data

        def _curve_props(self, context : Context):
            # scene-level, not a tool operator property -- every tool that
            # builds a curve overlay shares one set of density/corner-angle/
            # visibility settings, so switching tools doesn't reset them and
            # two tools editing chains from the same selection always agree
            # on how a curve is fit (see rfprops_curve_handles.py)
            return context.scene.retopoflow.curve_handles

        def _curve_handles_enabled(self, context : Context) -> bool:
            return self._curve_props(context).show_curve_handles

        def _bend_tolerance_factor(self, context : Context) -> float:
            return density_to_bend_tolerance(self._curve_props(context).curve_handle_density)

        def _sharp_corner_angle(self, context : Context) -> float:
            return self._curve_props(context).curve_corner_angle

        def update_data(self, context : Context) -> bool:
            RFCore = RFGlobals.RFCore_None
            if not RFCore: return False

            if not self._curve_handles_enabled(context):
                cls = type(self)
                if self.curves or self.chains or self.label_data:
                    cls.depsgraph_version = -42  # force rebuild when re-enabled
                    self.curves = []
                    self.chains = []
                    self.label_data = []
                return True

            # a modal operator OTHER THAN this overlay's own instance or
            # RFCore's own top-level operator currently has control -- most
            # likely a native transform (move/rotate/scale, or any other
            # transform.* variant), RF's own Translate/Slide (retopoflow.
            # translate/slide -- G is handled by RF's own operator, not
            # always Blender's native transform.translate, and it moves verts
            # every bit as much), box select, etc. Denylisting like this
            # (rather than allowlisting specific op names) also catches
            # shear/bend/loop-cut/bisect/etc. without having to enumerate
            # every vert-moving modal Blender or RF itself ships. Every one of
            # those depsgraph updates would otherwise count as "the mesh
            # changed", forcing a rebuild (RDP corner detection possibly
            # included) on every single frame of the drag, which is both slow
            # and can make the knot structure itself jump around mid-drag if a
            # big enough move crosses the structural-rebuild threshold
            # partway through. Skip entirely while one's running -- both
            # callers (draw_postpixel_overlay, hovered_handle) bail out on a
            # False return without touching any state, so the overlay just
            # doesn't draw until control returns to RF, at which point this
            # same depsgraph-version check rebuilds once, cleanly, against
            # the final settled positions.
            external_ops = [
                op.bl_idname for op in context.window.modal_operators
                if op is not self and op.bl_idname != RFCORE_OPERATOR_BL_IDNAME
            ]
            if external_ops:
                return False

            # curve_handle_density/curve_corner_angle live on a plain
            # PropertyGroup (context.scene.retopoflow.curve_handles), not
            # mesh/object data -- dragging either doesn't bump
            # depsgraph_version, so both are checked for separately here to
            # still force a rebuild
            # (see _build_curve's own check against the cached structure's
            # tunables for why that's needed too, not just bypassing this
            # early-out). Bundled as one tuple so a future third tunable is
            # one more tuple entry, not a whole new set of tracking variables.
            tunables = (self._bend_tolerance_factor(context), self._sharp_corner_angle(context))
            tunables_changed = tunables != getattr(self, '_last_tunables', None)
            if tunables_changed and time.monotonic() - getattr(self, '_last_tunables_rebuild_time', 0.0) < TUNABLE_REBUILD_THROTTLE:
                # too soon after the last tunable-driven rebuild -- most likely
                # still mid slider-drag, so keep showing the last-built curves
                # rather than paying for a full rebuild on every single tick.
                # _last_tunables is deliberately left stale here, so the very
                # next call still sees "changed" and re-checks the throttle
                # against whatever value the slider is at by then.
                tunables_changed = False

            if not tunables_changed and self.depsgraph_version == RFCore.depsgraph_version and hasattr(self, 'curves'): return True
            if self.paused_update: return False

            cls = type(self)
            cls.depsgraph_version = RFCore.depsgraph_version
            self._last_tunables = tunables
            self._last_tunables_rebuild_time = time.monotonic()
            bend_tolerance_factor, sharp_angle = tunables

            self.curves = []
            self.chains = []
            self.label_data = []

            bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)

            # providers are tried in priority order, and the first one to
            # find anything wins outright -- later providers aren't even
            # called. This is how "faces win" is implemented for the
            # PolyStrips/Strokes providers list: QuadStripChainProvider
            # first means a selection containing quad strips shows ONLY
            # strip curves, never also sprouting loop curves on the same
            # selection's boundary edges. It also means the two providers'
            # own bail-out budgets (max chains, max elements) never need to
            # be combined -- only one of them is ever actually consulted.
            specs : list[ChainSpec] = []
            for provider in providers:
                result = provider.collect(context, bm)
                if result:
                    specs.extend(result)
                    break

            active_keys = set()
            for spec in specs:
                self._add_chain(spec, bend_tolerance_factor=bend_tolerance_factor, sharp_angle=sharp_angle, active_keys=active_keys)

            # drop cached structure for chains that are no longer selected
            self._curve_struct_cache = {
                k: v for k, v in self._curve_struct_cache.items() if k in active_keys
            }
            self._handle_type_overrides = {
                k: v for k, v in self._handle_type_overrides.items() if k in active_keys
            }

            return True

        def _add_chain(self, spec : ChainSpec, *, bend_tolerance_factor, sharp_angle, active_keys):
            self.label_data.append((spec.label[0], spec.label[1], spec.points))

            if len(spec.points) < spec.min_spline_points:
                return  # not enough points in a row to build a curve

            active_keys.add(spec.cache_key)
            spline, handles = self._build_curve(
                spec.points, cyclic=spec.cyclic, avg_len=spec.avg_len,
                bend_tolerance_factor=bend_tolerance_factor, sharp_angle=sharp_angle,
                cache_key=spec.cache_key,
            )
            if spline is None or not spline.cbs:
                return

            self.curves.append(spline)
            self.chains.append({
                'deform_bmv_indices': spec.deform_bmv_indices,
                'cache_key': spec.cache_key,
                'current_points': spec.current_points,
                'cyclic': spec.cyclic,
                'avg_len': spec.avg_len,
                'handles': handles,
                'interior_bmv_indices': spec.interior_bmv_indices,
                'deform_bmv_rungs': spec.deform_bmv_rungs,
                # True when points are real verts (an edge loop/strip); False
                # when they're DERIVED from faces (e.g. a quad-strip
                # centerline) -- see the Alt-scale "taper" handle interaction,
                # which only makes sense for a chain with its own strip width
                # to narrow/widen (a vertex-coupled chain has no such width)
                'coupled': spec.coupled,
            })

        def _build_curve(self, cos, *, cyclic, avg_len, bend_tolerance_factor, sharp_angle, cache_key):
            n = len(cos)
            # a handle-type override (V-key toggle, or an implicit pin from
            # directly dragging a tangent handle -- see curve_edit.py) is
            # read fresh every call, same as bend_tolerance_factor/sharp_angle,
            # and folded into `tunables` for the exact same reason: it isn't
            # reflected by any vert moving, so without this an override
            # change wouldn't invalidate either shortcut below and the
            # rebuild it needs to take effect would never happen
            handle_type_overrides = self._handle_type_overrides.get(cache_key, {})
            tunables = (bend_tolerance_factor, sharp_angle, tuple(sorted(handle_type_overrides.items())))

            cached = self._curve_struct_cache.get(cache_key)
            knots = corner_set = None
            max_dev = None
            if cached and len(cached['cos']) == n:
                max_dev = max((a - b).length for a, b in zip(cos, cached['cos']))
                # a tunable change invalidates the cached knot placement even
                # if no vert moved -- it's not just about staying under the
                # rebuild-deviation threshold below
                if max_dev <= avg_len * REBUILD_DEVIATION_FACTOR and cached.get('tunables') == tunables:
                    knots, corner_set = cached['knots'], cached['corner_set']

            # nothing (detectably) moved since the last build -- reuse that
            # build's spline and handles outright rather than refitting, so a
            # redraw with no edits at all (e.g. just switching tools) can't
            # replace a good fit with a different one for the exact same points.
            # A handle-type override change can't slip through here: it's part
            # of `tunables` above, so a mismatch leaves knots=None. Automatic
            # arms don't need anything recomputed at rest either -- their live
            # updates happen during the drag itself (see curve_edit.py's
            # _recompute_typed_handles), so by the time a drag has ended the
            # spline already holds the final arms.
            if knots is not None and max_dev is not None and max_dev <= avg_len * 1e-6:
                return cached['spline'], cached['handles']

            fresh_derive = knots is None
            if fresh_derive:
                # sharp-angle + RDP corner detection, local-extremum snapping,
                # and long-span auto-knots all live in common/curve_fit.py now,
                # so the Adjust Segment Count operator derives knots IDENTICALLY
                # -- see derive_centerline_knots for the (verbatim-moved) logic.
                knots, corner_set = derive_centerline_knots(
                    cos, cyclic=cyclic,
                    bend_tolerance_factor=bend_tolerance_factor,
                    sharp_angle=sharp_angle,
                )

            # Resolve each knot's handle TYPE -- Aligned, Vector, or Automatic
            # (see rfoperators/curve_edit.py's V-key toggle operator) -- from
            # an explicit override if one exists, else the forced default for
            # a geometric corner or an open chain's own endpoint (both are
            # "Vector" and can't be toggled away from it), else "Automatic".
            # `corner_set` here is always the TRUE, geometry-derived sharp-
            # angle set (cached/reused as-is above) -- forced_vector is
            # deliberately computed fresh from it every call, not cached
            # itself, so a knot the user toggles to Vector doesn't get
            # mistaken for a forced one on a later build.
            forced_vector = set(corner_set) | ({0, n - 1} if not cyclic else set())
            def resolve_handle_type(k):
                return handle_type_overrides.get(k) or ('vector' if k in forced_vector else 'automatic')
            # corners_for_fit: knots create_catmull_rom should treat as
            # corners (independent arms) -- the true geometric ones plus any
            # the user explicitly toggled to Vector. For the default state
            # (no overrides) this only adds the open chain's own endpoints,
            # whose tangents already take the corner-style branch inside
            # tangent_out/tangent_in regardless (an endpoint has no far-side
            # arm to smooth against), so a chain with no toggled knots fits
            # EXACTLY as it did before handle types existed. Automatic vs
            # Aligned changes nothing at fit time -- the difference is purely
            # in live drag behavior (see curve_edit.py's
            # _recompute_typed_handles).
            corners_for_fit = { k for k in knots if resolve_handle_type(k) == 'vector' }

            # the "nothing changed" shortcut above already absorbs every redraw
            # where verts didn't actually move, so the only way to reach this
            # line is a genuine structural rebuild OR a just-completed edit --
            # both one-time events, not a per-frame cost, so refine_handles'
            # direct search (see its docstring) is affordable here. But an
            # edit usually only reshapes *part* of a multi-segment chain --
            # segments whose own points already fit their existing curve well
            # are handed to create_catmull_rom as locked, so it leaves them
            # exactly as they are instead of spending that search to land back
            # on essentially the same answer (and, for a segment flanking a
            # free knot, so a manually-placed handle isn't quietly pulled back
            # towards whatever a fresh Catmull-Rom guess would've picked).
            locked_cbs = {}
            cached_cbs = {}
            prev_cos = None
            if not fresh_derive and cached.get('spline'):
                prev_cos = cached['cos']
                locked_cbs = self._well_fit_segments(cached['spline'], cos, prev_cos, avg_len, n, cyclic, corners_for_fit)
                # handed to create_catmull_rom as *candidates* only (not taken
                # unconditionally the way locked_cbs is) -- see its own
                # cached_cbs docs for why a fresh refit still needs a
                # fit-quality check before trusting one of these over the
                # plain vert-anchored position.
                cached_cbs = dict(enumerate(cached['spline'].cbs))

            spline = CubicBezierSpline.create_catmull_rom(
                cos, knots, cyclic=cyclic, corner_indices=corners_for_fit,
                locked_cbs=locked_cbs, prev_pts=prev_cos, cached_cbs=cached_cbs,
            )

            # Build smooth_junctions: set of segment indices i where the junction
            # AFTER cbs[i] is smooth (not a corner) -- refine_handles always keeps
            # such a junction's two tangent arms pointing the same direction (see
            # its docstring), so dragging one should mirror the other to preserve
            # that.
            nseg = len(spline.cbs)
            nknots = len(knots)
            smooth_junctions = set()
            if cyclic:
                for i in range(nseg):
                    if knots[(i + 1) % nknots] not in corners_for_fit:
                        smooth_junctions.add(i)
            else:
                for i in range(min(nseg - 1, nknots - 2)):
                    if knots[i + 1] not in corners_for_fit:
                        smooth_junctions.add(i)

            handles = self._build_handles(spline, cyclic, smooth_junctions, knots, resolve_handle_type, forced_vector)

            # NOTE: the REST curve deliberately keeps its best-FIT handle
            # directions (whatever create_catmull_rom/refine_handles produced)
            # -- NOT Blender's "point-at" directions. Automatic knots only
            # take on point-at behavior LIVE, and only partway, as their knot
            # is dragged toward the line between its neighbors (see
            # curve_edit._recompute_typed_handles); at rest and at the start
            # of a drag they sit at the good fit, so selecting a curve or
            # nudging a point never mangles the geometry the fit captured.

            # cache the structure AND this build's fit/handles -- unconditionally,
            # since a "cheap refit" pass (fresh_derive=False) still produces a new
            # spline from the current cos that needs to become the new baseline
            # for the next call's "did anything change" check above
            self._curve_struct_cache[cache_key] = {
                'knots': knots,
                'corner_set': corner_set,
                'tunables': tunables,
                'cos': [Vector(co) for co in cos],
                'spline': spline,
                'handles': handles,
            }

            return spline, handles

        def _well_fit_segments(self, cached_spline, cos, prev_cos, avg_len, n, cyclic, corner_set):
            '''
            Segments of `cached_spline` worth handing to create_catmull_rom as
            locked: build the exact candidate create_catmull_rom would (a
            coupled knot's side snapped to its current vert and its tangent
            handle carried along by the same delta; a free knot's side
            carried by that same vert's own delta too, since it isn't tied to
            it exactly but still needs to track a rigid shift of its
            neighborhood -- see create_catmull_rom's own prev_pts), then check
            that candidate's own fit -- average deviation of its interior
            verts -- against SEGMENT_KEEP_FIT_TOLERANCE. A coupled vert that
            moved far enough to need more than a same-delta translation shows
            up here as a worse fit, same as any other reason the curve
            stopped matching its points, so there's no need for a separate
            raw distance check on the endpoints themselves.

            Checked per segment rather than once for the whole chain, so an
            edit that only reshaped one part of a multi-segment chain doesn't
            force a refit of the parts that never stopped fitting well.

            NOTE: a segment whose own points are byte-identical to their prior
            build might look like a safe unconditional lock, skipping this
            check entirely -- but refine_handles jointly optimizes every
            *unlocked* segment together each round (see its docstring), so
            which neighbors are locked this round changes the search landscape
            for a still-unlocked segment even when ITS points didn't move.
            That makes "did this segment's points change" the wrong question;
            only the fit check below (a pure function of this cb and these
            points) is safe to shortcut, and it isn't expensive enough on its
            own to be worth the risk of getting that subtlety wrong.
            '''
            fit_tol = avg_len * SEGMENT_KEEP_FIT_TOLERANCE
            locked = {}
            for i, (cb, (ka, kb)) in enumerate(zip(cached_spline.cbs, cached_spline.inds)):
                run = [Vector(cos[k % n]) for k in range(ka, kb + 1)]
                if CubicBezierSpline.is_free_knot(ka % n, corner_set, cyclic, n):
                    p0 = Vector(cb.p0) + (Vector(cos[ka % n]) - Vector(prev_cos[ka % n]))
                else:
                    p0 = run[0]
                if CubicBezierSpline.is_free_knot(kb % n, corner_set, cyclic, n):
                    p3 = Vector(cb.p3) + (Vector(cos[kb % n]) - Vector(prev_cos[kb % n]))
                else:
                    p3 = run[-1]
                d0, d3 = p0 - Vector(cb.p0), p3 - Vector(cb.p3)
                candidate = CubicBezier(p0, Vector(cb.p1) + d0, Vector(cb.p2) + d3, p3)
                if len(run) > 2:
                    avg_dev = CubicBezierSpline.total_distance(candidate, run) / (len(run) - 2)
                    if avg_dev > fit_tol:
                        continue
                locked[i] = cb
            return locked

        def _build_handles(self, spline, cyclic, smooth_junctions, knots, resolve_handle_type, forced_vector):
            cbs = spline.cbs
            nseg = len(cbs)
            handles = []
            if nseg == 0:
                return handles

            nknots = len(knots)

            # a knot is vertex-coupled (dragging it moves a real vert, and that
            # vert's position defines it) unless it's a smooth, non-endpoint
            # junction -- those are "free": draggable to reshape the curve
            # without pinning any vert to the exact handle position (see
            # the shared curve-edit operator's init())
            #
            # 'vert_index' is this knot's position in `knots` translated back
            # to a vert index (see the handle-type system in _build_curve) --
            # 'handle_type' its resolved Aligned/Vector/Automatic type, and
            # 'can_toggle' whether the V-key operator is allowed to cycle it
            # (False for a geometric corner or an open chain's own endpoint,
            # which are always Vector -- see forced_vector)
            if cyclic:
                for i in range(nseg):
                    j = (i - 1) % nseg
                    k = knots[i]
                    handles.append({'kind':'knot', 'pos':(i,'p0'), 'free': j in smooth_junctions,
                                    'set':[(j,'p3'), (i,'p0')], 'move':[(j,'p2'), (i,'p1')],
                                    'vert_index': k, 'handle_type': resolve_handle_type(k), 'can_toggle': k not in forced_vector})
            else:
                k0 = knots[0]
                handles.append({'kind':'knot', 'pos':(0,'p0'), 'free': False, 'set':[(0,'p0')], 'move':[(0,'p1')],
                                'vert_index': k0, 'handle_type': resolve_handle_type(k0), 'can_toggle': k0 not in forced_vector})
                for i in range(1, nseg):
                    k = knots[i]
                    handles.append({'kind':'knot', 'pos':(i,'p0'), 'free': (i - 1) in smooth_junctions,
                                    'set':[(i-1,'p3'), (i,'p0')], 'move':[(i-1,'p2'), (i,'p1')],
                                    'vert_index': k, 'handle_type': resolve_handle_type(k), 'can_toggle': k not in forced_vector})
                kN = knots[-1]
                handles.append({'kind':'knot', 'pos':(nseg-1,'p3'), 'free': False,
                                'set':[(nseg-1,'p3')], 'move':[(nseg-1,'p2')],
                                'vert_index': kN, 'handle_type': resolve_handle_type(kN), 'can_toggle': kN not in forced_vector})

            for i in range(nseg):
                # p1: outgoing arm from the junction on the LEFT of segment i
                # that junction is "after segment (i-1)%nseg" for cyclic, or (i-1) for open
                h_p1 = {'kind':'tangent', 'pos':(i,'p1'), 'set':[(i,'p1')], 'move':[],
                        'owner_vert_index': knots[i % nknots]}
                left_j = (i - 1) % nseg if cyclic else (i - 1)
                if (cyclic or i > 0) and left_j in smooth_junctions:
                    h_p1['g1_knot'] = (i, 'p0')
                    h_p1['g1_peer'] = (left_j, 'p2')
                handles.append(h_p1)

                # p2: incoming arm to the junction on the RIGHT of segment i
                # that junction is "after segment i"
                h_p2 = {'kind':'tangent', 'pos':(i,'p2'), 'set':[(i,'p2')], 'move':[],
                        'owner_vert_index': knots[(i + 1) % nknots]}
                if (cyclic or i < nseg - 1) and i in smooth_junctions:
                    h_p2['g1_knot'] = (i, 'p3')
                    h_p2['g1_peer'] = ((i + 1) % nseg, 'p1')
                handles.append(h_p2)

            return handles

        _HANDLE_TYPE_CYCLE = {'aligned': 'vector', 'vector': 'automatic', 'automatic': 'aligned'}

        def set_handle_type(self, cache_key, vert_index, handle_type) -> bool:
            ''' Sets a knot's handle type override (used by both the V-key
            toggle and, implicitly, a direct tangent-handle drag pinning its
            knot to 'aligned' -- see curve_edit.py's apply_handle). Forces the
            next update_data/build to see this as a change (see the
            handle_type_overrides fold-in to `tunables` in _build_curve) --
            without this, a rebuild wouldn't even be attempted until the mesh
            or scene tunables changed for some unrelated reason. '''
            overrides = self._handle_type_overrides.setdefault(cache_key, {})
            if overrides.get(vert_index) == handle_type:
                return False
            overrides[vert_index] = handle_type
            type(self).depsgraph_version = -42
            return True

        def toggle_handle_type(self, cache_key, vert_index) -> bool:
            ''' V-key entry point: cycles Aligned -> Vector -> Automatic ->
            Aligned for the given knot. Caller (the toggle operator) is
            responsible for checking the hovered handle's own 'can_toggle'
            first -- this doesn't re-check it, so a forced (corner/endpoint)
            knot could technically be overridden here too, same as a direct
            tangent drag can pin one to 'aligned' (see set_handle_type). '''
            for chain in self.chains:
                if chain['cache_key'] != cache_key:
                    continue
                for h in chain['handles']:
                    if h['kind'] == 'knot' and h.get('vert_index') == vert_index:
                        current = h.get('handle_type', 'automatic')
                        return self.set_handle_type(cache_key, vert_index, self._HANDLE_TYPE_CYCLE[current])
            return False

        # ----------------------------------------------------------- hit-testing

        def hovered_handle(
            self,
            context : Context,
            mouse : Sequence[float] | Vector,
            *,
            distance2D : float = 10,
        ) -> tuple[int, int, list] | None:
            if not context.edit_object:
                return None
            if not self.update_data(context):
                return None
            rgn, r3d = context.region, context.region_data
            if not r3d:
                return None
            m = Vector(mouse)
            M : Matrix = context.edit_object.matrix_world
            d = Drawing.scale(distance2D)
            if d is None:
                return None
            # knots take priority over tangents when overlapping
            for want_kind in ('knot', 'tangent'):
                for ci, (spline, chain) in enumerate(zip(self.curves, self.chains)):
                    for hi, h in enumerate(chain['handles']):
                        if h['kind'] != want_kind:
                            continue
                        seg, attr = h['pos']
                        p = location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(spline.cbs[seg], attr)))
                        if not p:
                            continue
                        if (p - m).length < d:
                            return (ci, hi, self._snapshot(spline))
            return None

        def _snapshot(self, spline):
            return [
                tuple(Vector(getattr(cb, a)) for a in ('p0','p1','p2','p3'))
                for cb in spline.cbs
            ]

        # --------------------------------------------------------------- drawing

        def draw_postpixel_overlay(self):
            RFCore = RFGlobals.RFCore_None
            if not RFCore: return
            if RFCore.selected_RFTool_idname != rftool_idname: return
            if self.paused_overlay: return

            context = bpy.context
            if not context.edit_object:
                return
            if not self.update_data(context):
                # also covers a native transform being mid-drag -- see
                # update_data's own check
                return
            rgn, r3d = context.region, context.region_data
            if not r3d:
                return
            M = context.edit_object.matrix_world

            for (lbl, count, cos) in self.label_data:
                lbl_pos = get_label_pos(context, lbl, cos)
                if not lbl_pos:
                    continue
                text = f'{lbl}: {count}'
                tw, th = Drawing.get_text_width(text), Drawing.get_text_height(text)
                lbl_pos = lbl_pos - Vector((tw / 2, -th / 2))
                Drawing.text_draw2D(text, lbl_pos.xy, color=(1,1,0,1), dropshadow=(0,0,0,0.75))

            for spline, chain in zip(self.curves, self.chains):
                cbs = spline.cbs
                # an Automatic knot's tangent handles are fully recomputed
                # from neighbor geometry every frame (_recompute_typed_
                # handles) -- hide them (dot + control-polygon spoke) by
                # default so users aren't invited to drag something that's
                # about to be overwritten; DEBUG_SHOW_AUTO_HANDLES shows them
                # anyway. A tangent only stores its owner's vert index, not
                # the owning knot dict, so look handle_type up by vert index.
                knot_type_by_vert = {
                    h['vert_index']: h.get('handle_type')
                    for h in chain['handles'] if h['kind'] == 'knot'
                }
                hidden_tangents = set() if DEBUG_SHOW_AUTO_HANDLES else {
                    h['pos']
                    for h in chain['handles']
                    if h['kind'] == 'tangent' and knot_type_by_vert.get(h['owner_vert_index']) == 'automatic'
                }
                for i, cb in enumerate(cbs):
                    curve_pts = [
                        location_3d_to_region_2d(rgn, r3d, M @ Vector(cb.eval(v / 20)))
                        for v in range(21)
                    ]
                    curve_pts = [p for p in curve_pts if p]
                    draw_curve_line = False
                    if draw_curve_line and len(curve_pts) >= 2:
                        Drawing.draw2D_linestrip(context, curve_pts, CURVE_LINE_COLOR, width=2, stipple=[5,5])
                    # control polygon: draws the two tangent arms (p0-p1 and p2-p3),
                    # shortened at each end so the line stops at the handle dot's
                    # edge instead of running into its (partially transparent) center
                    p0_, p1_, p2_, p3_ = (location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cb, a))) for a in ('p0','p1','p2','p3'))
                    knot_r, tan_r = Drawing.scale(KNOT_RADIUS/2), Drawing.scale(TANGENT_RADIUS/2)
                    arm_lines = []
                    if (i, 'p1') not in hidden_tangents:
                        arm_lines += shrink_segment(p0_, p1_, knot_r, tan_r)
                    if (i, 'p2') not in hidden_tangents:
                        arm_lines += shrink_segment(p2_, p3_, tan_r, knot_r)
                    if arm_lines:
                        Drawing.draw2D_lines(context, arm_lines, CONTROL_POLYGON_COLOR, width=2)

                knot_pts2d, free_knot_pts2d, auto_knot_pts2d, tan_pts2d = [], [], [], []
                for h in chain['handles']:
                    seg, attr = h['pos']
                    p = location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cbs[seg], attr)))
                    if not p:
                        continue
                    if h['kind'] != 'knot':
                        if h['pos'] not in hidden_tangents:
                            tan_pts2d.append(p)
                    elif h.get('handle_type') == 'automatic':
                        auto_knot_pts2d.append(p)
                    elif h.get('free'):
                        free_knot_pts2d.append(p)
                    else:
                        knot_pts2d.append(p)
                if tan_pts2d:
                    Drawing.draw2D_points(context, tan_pts2d, TANGENT_FILL_COLOR, radius=TANGENT_RADIUS, border=2, borderColor=TANGENT_BORDER_COLOR)
                if knot_pts2d:
                    Drawing.draw2D_points(context, knot_pts2d, KNOT_FILL_COLOR, radius=KNOT_RADIUS, border=2, borderColor=KNOT_BORDER_COLOR)
                if free_knot_pts2d:
                    Drawing.draw2D_points(context, free_knot_pts2d, FREE_KNOT_FILL_COLOR, radius=KNOT_RADIUS, border=2, borderColor=KNOT_BORDER_COLOR)
                if auto_knot_pts2d:
                    Drawing.draw2D_points(context, auto_knot_pts2d, AUTO_KNOT_FILL_COLOR, radius=KNOT_RADIUS, border=2, borderColor=KNOT_BORDER_COLOR)

    return type(opname, (RFOperator_Curve_Overlay, RFOperator), {})
