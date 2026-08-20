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

import bmesh
import heapq
import math
from mathutils import Vector, Quaternion
from bpy.types import Context, Event
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d

from collections.abc import Callable

from ..common.accel import SourceCache
from ..common.bmesh import get_bmesh_emesh
from ..common.bmesh_maths import orient_bmf_normals
from ..common.curves import ordered_rungs
from ..common.topology_corners import insert_corner, remove_corner
from ..common.drawing import Drawing
from ..common.maths import view_right_direction, xform_direction, proportional_edit
from ..common.raycast import raycast_point_valid_sources, nearest_point_valid_sources, iter_all_valid_sources, mouse_from_event
from ..common.snapping import source_snap_settings, source_snap_radius
from ..common.operator import RFOperator, RFKeyMaps, execute_operator, Operator_Execute_Function
from ..rfoverlay_base import RFOverlay_Base
from ..rfglobals import RFGlobals
from ...addon_common.common import gpustate
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import Color, sign_threshold
from ..rfoverlays.curve_overlay import (
    shrink_segment, KNOT_RADIUS, TANGENT_RADIUS,
    CURVE_LINE_COLOR, CONTROL_POLYGON_COLOR, TANGENT_FILL_COLOR, TANGENT_BORDER_COLOR,
    KNOT_FILL_COLOR, KNOT_BORDER_COLOR, FREE_KNOT_FILL_COLOR, AUTO_KNOT_FILL_COLOR,
    DEBUG_SHOW_AUTO_HANDLES,
)


# dragging a handle on a closed loop only directly moves the loop's own
# verts -- a selected patch's INTERIOR verts (enclosed by the loop but not
# part of it) are interpolated instead, via graph-Laplacian relaxation over
# the real mesh edges (each interior vert -> weighted average of its
# neighbors, boundary verts pinned at their curve-driven positions). This is
# warm-started every frame (verts hold last frame's result, not reset), so
# after an initial settle a handful of iterations is enough to track a
# boundary that's only moving a little each frame; a full drag is cheap even
# though no iteration count here is a rigorous convergence guarantee.
INTERIOR_RELAX_ITERATIONS = 10
# extra settling pass on release, since a fast drag-and-release may not have
# had enough per-frame iterations to fully catch up to the final boundary shape
INTERIOR_RELAX_FINAL_ITERATIONS = 40

# how far a vert's tangent must swing (from its pre-drag direction) for the
# curve-normal correction to reach full strength -- see the deform loop in
# update(). Below this the correction ramps in proportionally; a gentle edit
# barely engages it (staying purely rigid/reversible), an extreme one snaps a
# well-fit cross-section flat into the curve's normal plane so skew can't
# accumulate. Purely a feel knob -- tune freely.
CURVE_NORMAL_EDIT_ANGLE = math.radians(90)


def _relax_interior_verts(bm, interior, iterations):
    '''
    Gauss-Seidel graph-Laplacian relaxation -- but over each vert's
    DISPLACEMENT from its own original position, not its absolute position.
    A real mesh's interior isn't generally already sitting at the flat
    "average of its neighbors" shape (it may follow curved source-surface
    detail the boundary loop alone doesn't capture) -- relaxing absolute
    position would immediately pull it toward that flat shape the instant a
    drag starts, regardless of how little the boundary has actually moved,
    which reads as a jump. Relaxing displacement instead means zero boundary
    movement propagates as zero interior displacement -- nothing moves until
    the boundary actually does, and only the CHANGE spreads inward, riding on
    top of whatever detail was already there.

    Weighted by each edge's ORIGINAL (pre-drag) length rather than uniformly,
    so a neighbor that was already close has proportionally more say than one
    that was far away -- a plain unweighted average is more prone to visible
    overlap/folding under a large deformation, since it treats a stretched-
    out neighbor exactly the same as a close one. This reduces (but -- being
    a linear method, same as Blender's own Lattice modifier -- cannot fully
    eliminate) fold-over on sufficiently extreme edits; only a non-linear,
    locally-rotation-aware scheme (As-Rigid-As-Possible-style) would.
    '''
    indices = interior['indices']
    neighbors = interior['neighbors']
    orig_co = interior['orig_co']
    displacement = interior['displacement']
    boundary_orig_co = interior['boundary_orig_co']
    for _ in range(iterations):
        for idx in indices:
            nbrs = neighbors[idx]
            if not nbrs:
                continue
            total = Vector((0.0, 0.0, 0.0))
            weight_sum = 0.0
            for (n, w) in nbrs:
                d = displacement[n] if n in displacement else (bm.verts[n].co - boundary_orig_co[n])
                total = total + d * w
                weight_sum += w
            displacement[idx] = total / weight_sum
            bm.verts[idx].co = orig_co[idx] + displacement[idx]


def _segment_arc_length(cb, fn_dist):
    return sum(d for _, _, d in cb.get_tessellate_uniform(fn_dist))


def _cumulative_lengths(cbs, segs, fn_dist):
    ''' Running total arc length at each boundary of `segs` (len(segs)+1 entries, starting at 0). '''
    cum = [0.0]
    for seg in segs:
        cum.append(cum[-1] + _segment_arc_length(cbs[seg], fn_dist))
    return cum


def _walk_free_run(start, step, nseg, cyclic, free_at_seg_p0, visited):
    '''
    Extends `visited` outward from `start` one segment at a time (`step` = -1
    backward, +1 forward) for as long as the knot crossed at each step is
    free -- see combined_segs' construction in init() below. Returns the
    newly-visited segments in walk order, nearest to `start` first; `visited`
    itself grows to include them, so a second call in the opposite direction
    won't cross back into this one.
    '''
    result = []
    cur = start
    while True:
        nxt = (cur + step) % nseg if cyclic else cur + step
        if not cyclic and not (0 <= nxt < nseg):
            break
        if nxt in visited:
            break
        # the boundary knot between cur and nxt is "at p0" of whichever one
        # comes later in forward (increasing-index) order
        if not free_at_seg_p0.get(nxt if step > 0 else cur, False):
            break
        result.append(nxt)
        visited.add(nxt)
        cur = nxt
    return result


def create_curve_edit_operator(
    opname : str,
    idname : str,
    label : str,
    description : str,
    *,
    get_overlay : Callable[[], type[RFOverlay_Base] | None],
    on_init : Callable[[Context, Event], None] | None = None,
) -> type[RFOperator]:
    ''' Shared curve-handle drag operator: works for any overlay built with
    create_curve_overlay, regardless of whether its chains come from real
    edge loops/strips or from a derived centerline (e.g. a quad strip) --
    see curves.ChainSpec for what makes a chain interchangeable
    here (deform_bmv_indices, cache_key, current_points). '''

    # NOTE: this body class deliberately does NOT inherit from RFOperator --
    # RFOperator_Base.__init_subclass__ auto-registers every subclass that
    # has a bl_idname, so inheriting it here AND combining with RFOperator
    # again below (as create_curve_overlay's own factory does, for the same
    # reason) would register two distinct classes under the identical
    # bl_idname, silently breaking which one Blender's keymap ends up
    # invoking. Only the final type(...) combination below should trigger
    # that registration, exactly once.
    class RFOperator_Curve_Edit:
        bl_idname = f'retopoflow.{idname}'
        bl_label = label
        bl_description = description
        bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

        rf_keymaps : RFKeyMaps = [
            (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS'}, None),
            # separate entries so Alt+drag-to-scale and Alt+Shift+drag-to-
            # rotate (see apply_handle) also start when their modifiers are
            # already held before the click -- Blender's keymap_items.new()
            # defaults every unlisted modifier to False, so the plain entry
            # above only ever matches with both up; once the modal operator
            # is running it keeps getting all events regardless of keymap,
            # which is why toggling a modifier mid-drag already worked
            # without this
            (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS', 'alt': True}, None),
            (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS', 'alt': True, 'shift': True}, None),
        ]

        @classmethod
        def can_start(cls, context):
            i = get_overlay().instance
            return False if not i else bool(getattr(i, 'hovering', False))

        def init(self, context, event):
            overlay_type = get_overlay()
            assert overlay_type
            overlay = overlay_type.instance
            self.curves = overlay.curves
            self.chains = overlay.chains
            chain_idx, handle_idx, snapshot = overlay.hovering
            self.chain = self.chains[chain_idx]
            self.spline = self.curves[chain_idx]
            self.handle = self.chain['handles'][handle_idx]
            self.snapshot = snapshot
            # set by apply_handle when Alt+dragging a knot -- see _scale_handles
            self.taper_scale = None
            self.taper_t = None
            # set by _recompute_typed_handles while dragging an Automatic knot
            # with two valid neighbors -- see _deform_verts's use of these to
            # push the curve-normal blend to full strength on the two segments
            # flanking the dragged knot as it nears the straight line between
            # its neighbors. No-op defaults for every other drag kind (tangent
            # drags, Aligned/Vector knot drags, Alt scale/rotate).
            self.horizon_factor = 0.0
            self.horizon_segs = frozenset()

            get_overlay().pause_update()
            get_overlay().instance.depsgraph_version = None

            mouse = mouse_from_event(event)
            M, Mi = context.edit_object.matrix_world, context.edit_object.matrix_world.inverted_safe()

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

            self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
            self.M, self.Mi = M, Mi
            self.sources = [
                (obj, obj.matrix_world, (mi := obj.matrix_world.inverted_safe()), mi.to_3x3())
                for obj in iter_all_valid_sources(context)
            ]
            self.right = xform_direction(Mi, view_right_direction(context))
            self.spline.tessellate_uniform()

            self.source_accel = SourceCache.get(context)
            if self.source_accel:
                edit_scale = max(M.to_scale())
                use_fixed, fixed_distance, proximity = source_snap_settings(context)
                self.feature_radius = source_snap_radius(
                    self.chain['avg_len'] * edit_scale,
                    use_fixed=use_fixed, fixed_distance=fixed_distance, avg_edge_factor=proximity,
                )
            else:
                self.feature_radius = 0.0

            fn_dist = lambda a, b: (a - b).length

            # segment(s) whose shape will change as this handle is dragged -- verts
            # on these need their *arc-length fraction* preserved instead of their
            # raw parameter t (which isn't proportional to arc length, so it drifts
            # spacing as a segment stretches/compresses under editing)
            nseg = len(self.spline.cbs)
            if self.handle['kind'] == 'knot':
                self.touched_segs = { seg for seg, _ in self.handle['set'] }
                # dragging a knot also live-recomputes its two ADJACENT
                # Automatic/Vector knots' arms (see _recompute_typed_handles),
                # which reshapes the segment on the far side of each neighbor
                # too -- include those so their verts get arc-length tracking
                # as well. A neighbor segment that doesn't actually change
                # (e.g. that knot is Aligned) just re-derives the same vert
                # positions, so over-inclusion is harmless.
                for seg in list(self.touched_segs):
                    for nb in (seg - 1, seg + 1):
                        if self.chain['cyclic']:
                            self.touched_segs.add(nb % nseg)
                        elif 0 <= nb < nseg:
                            self.touched_segs.add(nb)
            else:
                self.touched_segs = { self.handle['pos'][0] }
                if 'g1_peer' in self.handle:
                    # a G1-mirrored tangent arm reshapes the peer segment on the
                    # other side of the junction too (see apply_handle), so its
                    # verts need the same arc-length tracking as this handle's own
                    self.touched_segs.add(self.handle['g1_peer'][0])
                # Alt-dragging a tangent redirects to scaling/rotating the knot
                # it belongs to (see apply_handle/_knot_for_tangent), which can
                # reshape the segment on the OTHER side of that knot too -- cover
                # it here so those verts still track arc-length correctly if Alt
                # is held (or gets toggled on mid-drag). A no-op for a normal,
                # non-Alt tangent drag, since that segment's shape doesn't
                # actually change then
                knot_h = self._knot_for_tangent(self.handle)
                if knot_h:
                    self.touched_segs |= { seg for seg, _ in knot_h['move'] }

            # a "free" knot isn't a vertex -- nothing should be forced to sit
            # exactly on it, or bunch up as it moves. Its two flanking segments
            # aren't independently anchored (unlike a normal touched segment,
            # where the far end IS a real vert), so the whole run from the
            # nearest TRUE (vertex-coupled) knot on one side to the nearest true
            # knot on the other -- crossing over any other free knots along the
            # way -- is treated as one combined span. Every vert in it keeps its
            # original *proportional* position within that combined span's arc
            # length (recomputed fresh each frame in update(), since the span's
            # segments keep reshaping as the drag continues) rather than its
            # position within just one segment, so a vert near one true anchor
            # doesn't get dragged around by an edit happening near the other.
            self.combined_segs = None
            if self.handle['kind'] == 'knot' and self.handle.get('free') and len(self.handle['set']) == 2:
                free_at_seg_p0 = {
                    h['pos'][0]: h.get('free', False)
                    for h in self.chain['handles']
                    if h['kind'] == 'knot' and h['pos'][1] == 'p0'
                }
                seg_before, seg_after = self.handle['set'][0][0], self.handle['set'][1][0]
                cyclic = self.chain['cyclic']
                visited = {seg_before, seg_after}
                backward = _walk_free_run(seg_before, -1, nseg, cyclic, free_at_seg_p0, visited)
                forward = _walk_free_run(seg_after, 1, nseg, cyclic, free_at_seg_p0, visited)
                self.combined_segs = list(reversed(backward)) + [seg_before, seg_after] + forward

            bmvs = [self.bm.verts[i] for i in self.chain['deform_bmv_indices']]
            # gather neighboring geo for proportional editing
            if bmvs and use_proportional_edit:
                connected_only = context.tool_settings.use_proportional_connected
                if connected_only:
                    all_bmvs = {}
                    # NOTE: bmv.index added to tuple to break distance ties before bmvs are compared
                    queue = [(0, bmv.index, bmv) for bmv in bmvs]
                    while queue:
                        (d, _, bmv) = heapq.heappop(queue)
                        if bmv in all_bmvs: continue
                        all_bmvs[bmv] = d
                        for bme in bmv.link_edges:
                            bmv_ = bme.other_vert(bmv)
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
            bmv_selected_count = 0
            bmv_merged_2d_coords = Vector((0.0, 0.0))
            bmv_merged_3d_coords = Vector((0.0, 0.0, 0.0))
            rgn, r3d = context.region, context.region_data
            combined_cum = _cumulative_lengths(self.spline.cbs, self.combined_segs, fn_dist) if self.combined_segs else None
            # for a face strip: {vert index -> (its rung's midpoint, distance in
            # rungs from the nearest open end)} -- see ChainSpec.deform_bmv_rungs.
            # Empty for vertex-coupled chains (verts ARE the curve points).
            rung_map = self.chain.get('deform_bmv_rungs') or {}
            for (bmv, distance) in all_bmvs.items():
                # parametrize against the curve by the vert's RUNG position (the
                # perpendicular edge's midpoint, which for interior rungs is
                # itself a centerline point) rather than the vert's own nearest
                # point -- so every vert of a rung shares one t and a wide strip
                # on a tight bend can't drift its verts onto the wrong stretch of
                # curve. Falls back to the vert itself for coupled chains and
                # proportional-edit neighbors (neither is in the rung map).
                rung = rung_map.get(bmv.index)
                # the chain's own first/last rung (end-distance 0) is only
                # ever TRANSFORMED when it's a genuine mesh boundary edge. If
                # the strip is connected there instead (the SELECTION ends,
                # not the mesh -- see _quad_chain_rung_map's is_boundary),
                # those verts are shared with un-edited faces outside this
                # chain: moving them would drag that adjacent geometry along
                # with the edit, so leave them at their pre-drag position by
                # never giving them a `data` entry at all -- no data entry
                # means _deform_verts (via self.grab['only'], built from
                # data's own keys) never touches bmv.co for it.
                if rung is None or rung[1] != 0.0 or rung[2]:
                    rung_pt = rung[0] if rung else bmv.co
                    t = self.spline.approximate_t_at_point_tessellation(rung_pt, fn_dist)
                    # a strip's boundary CAP rung (end-distance 0) sits past the
                    # centerline's own endpoint -- the centerline runs face-center
                    # to face-center (_interleaved_centerline never includes the
                    # boundary edges), so the curve itself never reaches the cap
                    # and the nearest-point search above just clamps short. Rather
                    # than taper a correction around that gap, extrapolate a
                    # straight extension along the endpoint tangent out to the
                    # cap, so a cap vert's offset lands purely perpendicular to
                    # the tangent -- exactly like any interior vert -- instead of
                    # partly ALONG it. end_t/overhang are fixed per vert (cached
                    # here, like d0/z0) and re-applied against the LIVE spline
                    # each frame in _deform_verts.
                    end_t = None
                    if rung and rung[1] == 0.0:
                        end_t = 0.0 if t < nseg / 2 else float(nseg)
                    eval_t = t if end_t is None else end_t
                    # store the vert's offset from the curve plus the curve's tangent
                    # HERE (on the pre-drag spline). Each frame the offset is rotated
                    # rigidly by however much this material point's tangent has since
                    # turned (see update()), so the perpendicular cross-section rolls
                    # WITH the curve rather than with the view -- no shear, and exactly
                    # reversible. The original curve is gone once handles move, so z0
                    # must be captured now rather than recomputed later.
                    z0 = Vector(self.spline.eval_derivative(eval_t))
                    if z0.length < 1e-9: z0 = Vector((0, 0, 1))
                    z0.normalize()
                    if end_t is None:
                        o = self.spline.eval(eval_t)
                        overhang = 0.0
                    else:
                        o_end = self.spline.eval(eval_t)
                        ext_dir = z0 if end_t > 0.0 else -z0
                        overhang = (rung_pt - o_end).dot(ext_dir)
                        o = o_end + ext_dir * overhang
                    d0 = Vector(bmv.co) - o
                    # how well this vert's offset already sits in the curve's normal
                    # plane (perpendicular to the tangent) -- 1 = a clean, well-fit
                    # cross-section, 0 = the "offset" actually runs ALONG the curve
                    # (a poor fit). Gates the curve-normal correction in update() so
                    # a bad fit is left alone while a good one gets straightened out
                    # under large edits. Constant per vert, so cached here.
                    d0_len = d0.length
                    fit_w = (1.0 - abs(d0.dot(z0) / d0_len)) if d0_len > 1e-9 else 0.0
                    seg = min(int(t), nseg - 1)
                    arc_frac = None
                    combined_frac = None
                    if self.combined_segs and seg in self.combined_segs:
                        idx = self.combined_segs.index(seg)
                        local_frac = self.spline.cbs[seg].approximate_arc_length_fraction_at_t(t - seg, fn_dist)
                        dist_into_combined = combined_cum[idx] + local_frac * (combined_cum[idx + 1] - combined_cum[idx])
                        combined_frac = dist_into_combined / max(combined_cum[-1], 1e-9)
                    elif seg in self.touched_segs:
                        arc_frac = self.spline.cbs[seg].approximate_arc_length_fraction_at_t(t - seg, fn_dist)
                    data[bmv.index] = (
                        t,
                        d0,
                        Vector(bmv.co),
                        distance,
                        arc_frac,
                        combined_frac,
                        z0,
                        fit_w,
                        end_t,
                        overhang,
                    )
                if use_proportional_edit and bmv.select:
                    bmv_selected_count += 1
                    co_world = M @ bmv.co
                    bmv_merged_3d_coords += co_world
                    screen_co = location_3d_to_region_2d(rgn, r3d, co_world)
                    if screen_co:
                        bmv_merged_2d_coords += screen_co

            if use_proportional_edit and bmv_selected_count:
                self.selection_origin_3d = bmv_merged_3d_coords / bmv_selected_count
                self.selection_origin_2d = bmv_merged_2d_coords / bmv_selected_count
            else:
                self.selection_origin_3d = None
                self.selection_origin_2d = None

            # a closed loop tracing a selected patch's perimeter carries the
            # patch's own INTERIOR verts too (see LoopStripChainProvider) --
            # those aren't driven by the curve directly; instead their
            # DISPLACEMENT from this original position is relaxed each frame
            # (see _relax_interior_verts), with neighbors outside this
            # chain's own boundary+interior sets excluded so the patch can't
            # "leak" into unrelated geometry it's merely adjacent to
            self.interior = None
            interior_bmv_indices = self.chain.get('interior_bmv_indices')
            if interior_bmv_indices:
                allowed = set(self.chain['deform_bmv_indices']) | set(interior_bmv_indices)
                neighbors = {}
                orig_co = {}
                for idx in interior_bmv_indices:
                    bmv = self.bm.verts[idx]
                    orig_co[idx] = Vector(bmv.co)
                    # weighted by (original) edge length -- see
                    # _relax_interior_verts for why not a plain average
                    neighbors[idx] = [
                        (other.index, 1.0 / max((other.co - bmv.co).length, 1e-6))
                        for bme in bmv.link_edges
                        if (other := bme.other_vert(bmv)).index in allowed
                    ]
                # boundary neighbors' ORIGINAL position, needed to turn their
                # current (curve-driven) position into a displacement each
                # frame -- every boundary vert of this chain is guaranteed to
                # already be a key in `data` (built above from deform_bmv_indices)
                boundary_orig_co = {
                    idx: data[idx][2]
                    for idx in self.chain['deform_bmv_indices']
                    if idx in data
                }
                self.interior = {
                    'indices': list(interior_bmv_indices),
                    'neighbors': neighbors,
                    'orig_co': orig_co,
                    'displacement': { idx: Vector((0.0, 0.0, 0.0)) for idx in interior_bmv_indices },
                    'boundary_orig_co': boundary_orig_co,
                }

            self.grab = {
                'mouse':   Vector(mouse),
                'current': Vector(mouse),
                'data':    data,
                'only':    None,
                # per-vert ACCUMULATED cross-section rotation, updated
                # incrementally each frame in _deform_verts (see its
                # docstring) -- identity at grab time, since z1 == z0 then.
                'rot':     {bmv_idx: Quaternion() for bmv_idx in data},
            }

            if on_init:
                on_init(self, context, event)

        def finish(self, context):
            # the spline being dragged IS the overlay's cached spline object
            # (see init), so its control points already hold this drag's
            # final state -- committed (including whatever apply_handle /
            # _recompute_typed_handles did live) or, on cancel, restored from
            # the snapshot. Sync the cache's 'cos' baseline to the current
            # points -- for BOTH coupled and uncoupled chains -- so the next
            # rebuild sees "nothing changed" and reuses this exact spline (see
            # _build_curve's nothing-changed shortcut) rather than refitting.
            #
            # A refit here is NOT a safe no-op: it runs the plain best-fit
            # search (create_catmull_rom/refine_handles), which knows nothing
            # about handle types, "point-at" blending, or the deliberate
            # straight-line/mirror result a drag may have just landed on --
            # so it can visibly replace a good, intentional result with a
            # different "best fit" the instant the drag ends. The type system
            # (and the deform math for a face strip) already do everything a
            # drag needs live; there's nothing left to correct afterward. A
            # genuinely bad fit (e.g. from a LATER, unrelated edit) still
            # gets caught by _build_curve's own max_dev-driven refit/re-derive
            # the normal way, on whatever future rebuild actually sees it.
            #
            # On cancel this is moot either way: update() restored the verts
            # (and the spline snapshot) to the positions already in the cache.
            try:
                overlay = get_overlay().instance
                bm    = getattr(self, 'bm', None)
                chain = getattr(self, 'chain', None)
                if overlay is not None and chain and bm and bm.is_valid:
                    cached = getattr(overlay, '_curve_struct_cache', {}).get(chain['cache_key'])
                    if cached:
                        new_cos = chain['current_points'](bm)
                        if new_cos and len(new_cos) == len(cached['cos']):
                            cached['cos'] = new_cos
            finally:
                # finish() also runs from cancel() / stop(), where the bmesh may already be
                # gone and init may not have finished. The cache sync above is best effort, but
                # skipping unpause_update() would freeze curve handles for the rest of the session.
                get_overlay().unpause_update()
                # nothing reads these after finish() but they can crash on operator release if the bmesh is gone
                self.bm, self.em = None, None

        def apply_handle(self, context, delta, rgn, r3d, M, Mi, alt, shift):
            h = self.handle
            cbs = self.spline.cbs
            idx_of = {'p0': 0, 'p1': 1, 'p2': 2, 'p3': 3}
            def orig(seg, attr):
                return Vector(self.snapshot[seg][idx_of[attr]])

            # reset each frame -- only a knot currently being Alt-dragged
            # (without Shift) sets these (see _scale_handles), and the
            # per-vert taper in update() must turn off the instant that
            # stops being true
            self.taper_scale = None
            self.taper_t = None
            # reset each frame -- only re-set below if this frame's drag is
            # an Automatic knot with two valid neighbors (_recompute_typed_
            # handles); must not linger from a previous frame once that
            # stops being true (e.g. mid-drag type change isn't possible,
            # but a stale value must never leak into a DIFFERENT drag)
            self.horizon_factor = 0.0
            self.horizon_segs = frozenset()

            # Alt/Alt+Shift always act on a KNOT -- if the user grabbed one
            # of its tangent handles instead, redirect to the knot it
            # belongs to, so users don't have to remember which of the two
            # to click
            if alt:
                knot_h = h if h['kind'] == 'knot' else self._knot_for_tangent(h)
                if knot_h is not None:
                    kseg0, kattr0 = knot_h['pos']
                    kpt_orig = orig(kseg0, kattr0)
                    kpt_screen = location_3d_to_region_2d(rgn, r3d, M @ kpt_orig)
                    if kpt_screen is None:
                        return
                    if shift:
                        self._rotate_handles(knot_h, kseg0, kattr0, kpt_orig, kpt_screen, delta, rgn, r3d, M, Mi, orig, cbs)
                    else:
                        self._scale_handles(knot_h, kseg0, kattr0, kpt_orig, delta, rgn, r3d, M, orig, cbs)
                    return

            seg0, attr0 = h['pos']
            pt_orig = orig(seg0, attr0)
            pt_screen = location_3d_to_region_2d(rgn, r3d, M @ pt_orig)
            if pt_screen is None:
                return
            new_screen = pt_screen + delta

            if h['kind'] == 'knot':
                # knots snap to the source surface and carry their tangent arms along
                new_world = raycast_point_valid_sources(context, new_screen, respect_clip_planes=True)
                if not new_world:
                    return
                new_edit = Mi @ new_world
                # A coupled edge chain's control point is a mesh vert, so snap the control point too.
                # Control points on a face loop are never verts, so don't snap those.
                if self.chain.get('coupled', True):
                    new_edit = self.snap_co_to_feature(new_edit)
                knot_delta = new_edit - pt_orig
                for (seg, attr) in h['set']:
                    setattr(cbs[seg], attr, new_edit.copy())
                for (seg, attr) in h['move']:
                    setattr(cbs[seg], attr, orig(seg, attr) + knot_delta)
                # the rigid translate above is only the baseline (and all an
                # Aligned knot ever gets -- its rotation is the user's own):
                # Automatic/Vector arms are then recomputed from the knots'
                # CURRENT positions, every frame, for the dragged knot AND its
                # two neighbors -- Blender's own Auto/Vector handle behavior,
                # and what keeps the curve smooth as the point moves
                self._recompute_typed_handles(h, cbs)
            else:
                # tangent arms move freely in the view plane
                new_world = region_2d_to_location_3d(rgn, r3d, new_screen, M @ pt_orig)
                new_edit = Mi @ new_world
                setattr(cbs[seg0], attr0, new_edit)
                # G1: at smooth junctions, mirror the peer tangent arm to stay collinear
                if 'g1_peer' in h:
                    knot_seg, knot_attr = h['g1_knot']
                    peer_seg, peer_attr = h['g1_peer']
                    K = orig(knot_seg, knot_attr)
                    T_moved = new_edit - K
                    peer_orig_pt = orig(peer_seg, peer_attr)
                    peer_len = (peer_orig_pt - K).length
                    if T_moved.length > 1e-9 and peer_len > 1e-9:
                        setattr(cbs[peer_seg], peer_attr, K - T_moved.normalized() * peer_len)
                # grabbing a tangent handle directly is a manual, one-off
                # rotation choice. For an AUTOMATIC owner, pin it to 'aligned'
                # so a later drag of that same knot doesn't have _recompute_
                # typed_handles unconditionally overwrite both of its own
                # arms, discarding the adjustment just made here.
                #
                # A VECTOR (or forced corner/endpoint) owner does NOT need
                # this: its type is left as-is, and _recompute_typed_handles'
                # offset-preserving rotation (see its own docs) already
                # takes care of it -- the NEXT drag that touches this arm
                # (dragging the knot itself, or an adjacent Automatic knot)
                # re-snapshots from wherever this manual edit left it, so
                # that edit becomes the new baseline offset and keeps
                # tracking point-at from then on. Pinning it to 'aligned'
                # would instead FREEZE it solid, throwing that ability away
                # for no benefit -- unlike Automatic, a Vector/endpoint knot
                # is never itself the "dragged_h" that recomputes its own
                # arms, so there's no self-overwrite risk to guard against.
                overlay = get_overlay().instance
                owner = h.get('owner_vert_index')
                if overlay is not None and owner is not None:
                    owner_kh = self._knot_for_tangent(h)
                    if owner_kh is None or owner_kh.get('handle_type') != 'vector':
                        overlay.set_handle_type(self.chain['cache_key'], owner, 'aligned')

        def _knot_for_tangent(self, h):
            ''' The KNOT handle that owns this tangent handle (has it listed
            in its own 'move'), so Alt-dragging a tangent scales/rotates
            exactly as if its own knot had been grabbed instead -- users
            shouldn't need to remember which of the two to click (see
            apply_handle). Every tangent belongs to exactly one knot by
            construction (see _build_handles), so this should always find a
            match; None is only a defensive fallback. '''
            pos = h['pos']
            for other in self.chain['handles']:
                if other['kind'] == 'knot' and pos in other['move']:
                    return other
            return None

        def _recompute_typed_handles(self, dragged_h, cbs):
            '''
            Live, per-frame handle update while an AUTOMATIC knot is dragged.
            Blends our own best-FIT handles (preserved from the rest curve)
            toward Blender's "point-at" handles by how close the dragged knot
            is to the straight line between its two neighbors -- better than
            either alone:

              - Blender's pure point-at can't hold a clean U (its handles
                always aim at neighbors) and, pulled flat, straightens the
                curve but mangles the geometry the original fit captured.
              - Our pure fit holds the U and the geometry, but can't flatten
                to a truly straight line (the fitted handles stay curved).

            ONE continuous formula covers both directions of travel (an
            earlier version stitched together two separate formulas at the
            grab distance -- matched exactly only for a perfectly radial
            drag, popping otherwise for any lateral component):

              1. offset_rot = the fixed rotation from "pure point-at" to
                 "what the fit actually had", measured ONCE at grab time
                 (pad0 -> rest_off_raw). This is the fit's own signature --
                 how far it originally diverged from simply aiming at the
                 neighbors.
              2. Every frame, that rotation is SLERPed toward identity by
                 `factor` (0 at/beyond the grab distance -> full offset
                 still applies; 1 exactly on the line -> offset fully
                 dissolved, pure point-at) and applied to the CURRENT
                 (still-updating) point-at direction, not the grab-time one.

            So: moving TOWARD the line, the offset progressively dissolves
            away, reaching exactly straight (pure point-at, geometry-
            agnostic) right on it. Moving AWAY, at or beyond the grab
            distance, the full original offset applies but keeps riding on
            top of the CURRENT point-at direction as it changes -- so the
            arm keeps adapting to an increasingly extreme shape instead of
            ever freezing solid. Once the knot crosses the line, the fitted
            offset is REFLECTED (mirroring pad0/rest_off_raw through the
            line before measuring offset_rot, and reflecting the final
            result back), so dragging through to the mirrored distance
            gives a perfect mirror of the original shape. factor = 1 -
            |signed_dist| / grab_dist, symmetric about the line.

            Exact continuity is guaranteed for the natural case of
            continuous motion from the grab position (pad1 == pad0 at
            factor's own natural start); a highly non-radial drag that
            re-crosses the same |signed_dist| == grab_dist boundary later at
            a different lateral position could in principle see a small
            path-dependent difference there -- negligible for ordinary use.

            Only the dragged knot's own two arms and each neighbor's arm that
            FACES it are touched (a neighbor's far arm, and any Aligned
            neighbor, keep the user's/fit's own handle). Only knot positions
            feed the math, so dragging a tangent moves no knot and leaves
            neighbors alone, exactly like Blender.

            Point-at target per arm's owner knot: an automatic knot -> its
            own Blender Auto direction unit(b-a)+unit(c-b) (depends on b, so
            it re-aims as the knot moves; both arms collinear -> G1); a
            vector/endpoint knot -> straight at the neighbor the arm faces.

            LENGTH is handled separately from direction (see
            blender_len_ref/recompute_arm below): each arm's fit-derived
            length is scaled, unconditionally and every frame, by however
            much Blender's OWN handle length would have changed since grab
            time. This is what lets dragging a knot close to one neighbor
            shrink that side's arm (and grow the other) the way Blender does
            -- without it, a length frozen at grab time can overshoot a
            now-much-closer neighbor and kink the curve.
            '''
            # the line + blend only make sense for an auto knot flattening
            # toward the run between its two neighbors -- a vector/aligned
            # drag just keeps apply_handle's rigid translate (its own fit)
            if dragged_h.get('handle_type') != 'automatic':
                return
            knots = [hh for hh in self.chain['handles'] if hh['kind'] == 'knot']
            try:
                idx = knots.index(dragged_h)
            except ValueError:
                return
            cyclic = self.chain['cyclic']
            n = len(knots)
            idx_of = {'p0': 0, 'p1': 1, 'p2': 2, 'p3': 3}

            def cur(pos):
                seg, attr = pos
                return Vector(getattr(cbs[seg], attr))

            def snap(pos):
                seg, attr = pos
                return Vector(self.snapshot[seg][idx_of[attr]])

            def knot_at(i):
                if cyclic:
                    return knots[i % n]
                return knots[i] if 0 <= i < n else None

            prev_h, next_h = knot_at(idx - 1), knot_at(idx + 1)
            if prev_h is None or next_h is None or prev_h is next_h:
                return  # no well-defined line between two distinct neighbors

            # The line runs between the two neighbors. They don't move during
            # the drag (only the dragged knot does), so it's fixed -- take it
            # from the snapshot. The dragged knot's perpendicular distance to
            # it drives the whole blend.
            a_line = snap(prev_h['pos'])
            c_line = snap(next_h['pos'])
            u = c_line - a_line
            if u.length < 1e-9:
                return
            u.normalize()

            def perp(p):
                rel = p - a_line
                return rel - rel.dot(u) * u

            b0, b1 = snap(dragged_h['pos']), cur(dragged_h['pos'])
            off0 = perp(b0)
            grab_dist = off0.length
            if grab_dist < 1e-9:
                return  # started on the line -- no fitted offset to blend from
            nrm = off0 / grab_dist                    # unit perpendicular, grab side positive
            signed_now = perp(b1).dot(nrm)
            factor = max(0.0, min(1.0, 1.0 - abs(signed_now) / grab_dist))
            mirrored = signed_now < 0.0

            # expose this frame's horizon proximity to _deform_verts (reset
            # to 0.0/empty each frame in apply_handle before this runs),
            # scoped to just the two segments flanking the dragged knot --
            # prev_h<->dragged_h and dragged_h<->next_h -- since those are
            # the ones that actually straighten as the knot approaches the
            # line between its neighbors; segments further out are unrelated
            # to this specific line.
            nseg_local = n if cyclic else n - 1
            seg_prev = (idx - 1) % nseg_local if cyclic else idx - 1
            seg_next = idx % nseg_local if cyclic else idx
            self.horizon_factor = factor
            self.horizon_segs = frozenset((seg_prev, seg_next))

            def reflect(v):
                # mirror across the plane through the line whose normal is the
                # grab-time offset direction -- flips only the component that
                # crosses the line, so an in-plane U reflects to a clean
                # mirror while any out-of-plane part is preserved
                return v - 2.0 * v.dot(nrm) * nrm

            def point_at_dir(i, attr, pos_fn):
                ''' Blender-handle direction for knot i's `attr` arm, from
                whichever positions `pos_fn` reads (cur = live/current, snap
                = grab-time): auto -> its own unit(b-a)+unit(c-b) (arm sign
                by side); vector/endpoint -> aim at the faced neighbor. '''
                kh = knot_at(i)
                if kh is None:
                    return None
                b = pos_fn(kh['pos'])
                pk, nk = knot_at(i - 1), knot_at(i + 1)
                if kh.get('handle_type') == 'automatic' and pk is not None and nk is not None:
                    va, vc = b - pos_fn(pk['pos']), pos_fn(nk['pos']) - b
                    if va.length < 1e-9 or vc.length < 1e-9:
                        return None
                    d = va.normalized() + vc.normalized()
                    if d.length < 1e-9:
                        return None
                    d.normalize()
                    return d if attr == 'p1' else -d
                m = nk if attr == 'p1' else pk       # aim at the neighbor this arm faces
                return (pos_fn(m['pos']) - b) if m is not None else None

            def blender_len_ref(i, attr, pos_fn):
                ''' Reference quantity proportional to Blender's own handle
                LENGTH for knot i's `attr` arm (the constant factor Blender
                applies -- /3 for Vector, /2.5614 for Auto -- cancels out
                since only the ratio between two calls is ever used, to scale
                our own fit-derived length rather than replace it):
                vector/endpoint -> distance to the faced neighbor (Blender's
                Vector handle is exactly that distance / 3); auto -> that
                same distance divided by |unit(b-a)+unit(c-b)| (Blender's
                Auto handle divides by the tangent-sum magnitude, which
                shrinks/grows the handle as the knot's angle to its neighbors
                changes, not just its raw distance to them). '''
                kh = knot_at(i)
                if kh is None:
                    return None
                b = pos_fn(kh['pos'])
                pk, nk = knot_at(i - 1), knot_at(i + 1)
                m = nk if attr == 'p1' else pk
                if m is None:
                    return None
                len_x = (pos_fn(m['pos']) - b).length
                if kh.get('handle_type') == 'automatic' and pk is not None and nk is not None:
                    va, vc = b - pos_fn(pk['pos']), pos_fn(nk['pos']) - b
                    if va.length < 1e-9 or vc.length < 1e-9:
                        return None
                    t_len = (va.normalized() + vc.normalized()).length
                    if t_len < 1e-9:
                        return None
                    return len_x / t_len
                return len_x

            def recompute_arm(owner_i, attr):
                kh = knot_at(owner_i)
                arm = next((pos for pos in kh['move'] if pos[1] == attr), None)
                if arm is None:
                    return
                knot_now = cur(kh['pos'])
                # the fitted arm's ORIGINAL (unreflected) offset from its
                # knot -- the one fixed quantity everything below is built
                # from. rest_off_raw's own DIRECTION is never used directly
                # (that would be the old, removed frozen-rigid carry); only
                # its LENGTH (the fit-derived baseline scaled below -- never
                # Blender's absolute ~1/3-ish sizing) and, via offset_rot,
                # how far it originally differed from point-at.
                rest_off_raw = snap(arm) - snap(kh['pos'])
                length = rest_off_raw.length

                # scale the fit-derived length by however much Blender's OWN
                # handle length would have changed between grab and now, so
                # e.g. dragging the knot toward one neighbor shrinks that
                # side's arm (and grows the other) exactly as fast as real
                # Blender does -- without this, a frozen length can overshoot
                # a now-much-closer neighbor and kink the curve. This is
                # independent of the point-at DIRECTION blend below -- length
                # always tracks Blender's relative scale, unconditionally.
                ref0 = blender_len_ref(owner_i, attr, snap)
                ref1 = blender_len_ref(owner_i, attr, cur)
                scale = max(0.0, ref1 / ref0) if (ref0 is not None and ref0 > 1e-9 and ref1 is not None) else 1.0
                length *= scale
                final_pos = knot_now + rest_off_raw * scale   # plain rigid-carry fallback (degenerate case only)

                pad0 = point_at_dir(owner_i, attr, snap)   # point-at direction AT GRAB TIME
                pad1 = point_at_dir(owner_i, attr, cur)    # point-at direction NOW
                if length > 1e-9 and pad0 is not None and pad0.length > 1e-9 and pad1 is not None and pad1.length > 1e-9:
                    pad0n, pad1n = pad0.normalized(), pad1.normalized()
                    # the fixed rotation from "pure point-at" to "what the
                    # fit actually had", measured once at grab time
                    offset_rot = pad0n.rotation_difference(rest_off_raw.normalized())
                    # ONE continuous formula for both directions of travel,
                    # instead of two formulas stitched together at factor==0
                    # (which only matched exactly for a perfectly radial
                    # drag, popping otherwise): slerp the offset itself down
                    # to identity as the knot nears the line, so at the line
                    # (factor=1) the offset has fully dissolved into pure
                    # point-at (exactly straight), and at or beyond the grab
                    # distance (factor=0) the full original offset applies,
                    # riding on top of the CURRENT (still-updating) point-at
                    # direction rather than a value frozen at grab time.
                    blended_rot = offset_rot.slerp(Quaternion(), factor)
                    target = reflect(pad1n) if mirrored else pad1n
                    arm_dir = blended_rot @ target
                    if mirrored:
                        arm_dir = reflect(arm_dir)
                    if arm_dir.length > 1e-9:
                        final_pos = knot_now + arm_dir.normalized() * length
                elif mirrored:
                    final_pos = knot_now + reflect(rest_off_raw * scale)
                seg, a = arm
                setattr(cbs[seg], a, final_pos)

            # the dragged knot's own two arms
            recompute_arm(idx, 'p2')
            recompute_arm(idx, 'p1')
            # each neighbor's arm that faces the dragged knot -- but not an
            # Aligned neighbor (its direction is the user's own to keep)
            if prev_h.get('handle_type') in ('automatic', 'vector'):
                recompute_arm(idx - 1, 'p1')   # prev's outgoing arm faces the dragged knot
                if prev_h.get('handle_type') == 'automatic':
                    # an Automatic knot's two arms must stay exactly collinear
                    # (that's what "Automatic" means -- see point_at_dir's
                    # unit(b-a)+unit(c-b), which is the SAME direction for
                    # both of a knot's arms, sign-flipped). Only just updated
                    # its NEAR arm above; a Vector neighbor's two arms are
                    # legitimately independent (no such requirement) so this
                    # only applies when the neighbor is ALSO Automatic.
                    recompute_arm(idx - 1, 'p2')   # prev's FAR arm, kept in line with the one just updated
            if next_h.get('handle_type') in ('automatic', 'vector'):
                recompute_arm(idx + 1, 'p2')   # next's incoming arm faces the dragged knot
                if next_h.get('handle_type') == 'automatic':
                    recompute_arm(idx + 1, 'p1')   # next's FAR arm, kept in line with the one just updated

        def _handle_pivot(self, h, orig):
            ''' The knot at the FAR end of the segment referenced by this
            knot handle's first flanking tangent -- v3 PolyStrips' "outerP",
            i.e. the far corner of the affected strip. A stable,
            well-separated point to measure an Alt-drag gesture (scale or
            rotate) against, since the drag itself starts ON the knot being
            edited, leaving it unusable as its own reference (near-zero
            distance, undefined angle). Returns None if this handle has no
            flanking tangent to reference (shouldn't happen for a knot, but
            matches _scale_handles'/_rotate_handles' existing guard). '''
            if not h['move']:
                return None
            ref_seg, ref_attr = h['move'][0]
            pivot_seg, pivot_attr = (ref_seg, 'p0') if ref_attr == 'p2' else (ref_seg, 'p3')
            return orig(pivot_seg, pivot_attr)

        def _scale_handles(self, h, seg0, attr0, pt_orig, delta, rgn, r3d, M, orig, cbs):
            '''
            Alt+drag on a knot: pin the knot at its snapshot position, and
            either scale its flanking tangent handles' LENGTHS (not
            direction) by a common factor, or -- on a face-derived chain --
            taper the strip's width instead (see below); never both, so the
            two effects don't compound into what'd look like one uneven one.

            Ported from v3 PolyStrips' own corner-scale gesture: the scale
            factor is the ratio of the mouse's CURRENT screen-space distance
            from a fixed pivot (_handle_pivot) to its distance from that same
            pivot when the drag started. v3 only ever grabs the tangent
            handle itself to scale, never the knot, so its pivot and its
            drag start are already two different (and far apart) points;
            grabbing the knot here instead means the pivot has to be found
            one step further out to get that same separation. A prior
            version measured against the reference handle's own (much
            shorter) length instead, which made the gesture oversensitive --
            small mouse moves swung the scale a lot, and since growing is
            unbounded (unlike shrinking, which self-limits at 0), it was
            easy to overshoot into extreme, visibly-broken handle lengths
            well before the drag felt "done".
            '''
            pivot_orig = self._handle_pivot(h, orig)
            if pivot_orig is None:
                return
            pivot_screen = location_3d_to_region_2d(rgn, r3d, M @ pivot_orig)
            if pivot_screen is None:
                return
            mouse_start = Vector(self.grab['mouse'])
            mouse_now = mouse_start + delta
            ref_dist = (mouse_start - pivot_screen).length
            if ref_dist < 1e-6:
                return
            scale = max(0.0, (mouse_now - pivot_screen).length / ref_dist)

            # the knot itself never moves under Alt -- only whichever of
            # handles/taper applies below does
            for (seg, attr) in h['set']:
                setattr(cbs[seg], attr, pt_orig.copy())

            if self.chain.get('coupled', True):
                # a vertex-coupled (edge-loop) chain has no "width" to
                # taper -- reshape the curve itself instead, by scaling the
                # knot's own tangent handles, each from its own original
                # length as its own 100% reference (not a shared absolute
                # length), which is what "equally" means here
                for (seg, attr) in h['move']:
                    orig_h = orig(seg, attr)
                    setattr(cbs[seg], attr, pt_orig + (orig_h - pt_orig) * scale)
            else:
                # a face-derived (uncoupled) chain's knot is a derived
                # centerline point, and its handles just describe that
                # centerline's path -- reshaping them here would bend the
                # strip's spine as a side effect of tapering its width,
                # compounding into a result that isn't a clean taper. Leave
                # the curve exactly as it started instead (undoing any
                # non-Alt move from earlier in the same drag, e.g. if Alt
                # was pressed partway through) and taper the verts' width
                # against that fixed curve instead -- see update()'s
                # per-vert loop, gated on self.taper_scale/self.taper_t
                for (seg, attr) in h['move']:
                    setattr(cbs[seg], attr, orig(seg, attr))
                self.taper_scale = scale
                self.taper_t = float(seg0 if attr0 == 'p0' else seg0 + 1)

        def _rotate_handles(self, h, seg0, attr0, pt_orig, pt_screen, delta, rgn, r3d, M, Mi, orig, cbs):
            '''
            Alt+Shift-drag on a knot: pin the knot at its snapshot position
            and rotate its flanking tangent handles by a common angle around
            it, instead of moving or scaling them -- reshapes the curve's
            tangent DIRECTION at that knot while preserving each handle's
            own length. Unlike _scale_handles, this applies the SAME way
            regardless of whether the chain is face-derived: there's no
            separate "taper" concept for a rotation, since reshaping the
            curve's direction is already exactly what should happen to a
            strip's spine too, and the existing per-vert curve-following in
            update() already carries that reshape through to every vert
            (coupled or not) on its own.

            The rotation angle is measured the same way _scale_handles
            measures its scale ratio: via the same stable, far pivot
            (_handle_pivot), tracking how much the mouse's own angular
            position around THAT pivot has changed since the drag started
            -- it can't be measured around the dragged knot itself, since
            the drag starts ON the knot, leaving its own angle undefined at
            the start. The measured angle is then applied by rotating each
            handle -- from its own original screen position -- around the
            KNOT itself (its true anchor), matching v3 PolyStrips' own
            rotate gesture (a screen-space rotation, then re-settled in 3D;
            tangent handles here already move freely in the view plane
            rather than snapping to source, same as a direct drag).
            '''
            pivot_orig = self._handle_pivot(h, orig)
            if pivot_orig is None:
                return
            pivot_screen = location_3d_to_region_2d(rgn, r3d, M @ pivot_orig)
            if pivot_screen is None:
                return
            mouse_start = Vector(self.grab['mouse'])
            mouse_now = mouse_start + delta
            v0 = mouse_start - pivot_screen
            v1 = mouse_now - pivot_screen
            if v0.length < 1e-6 or v1.length < 1e-6:
                return
            angle = math.atan2(v0.x, v0.y) - math.atan2(v1.x, v1.y)
            cos_a, sin_a = math.cos(angle), math.sin(angle)

            # the knot itself never moves under Alt -- only its handles do
            for (seg, attr) in h['set']:
                setattr(cbs[seg], attr, pt_orig.copy())

            for (seg, attr) in h['move']:
                orig_h = orig(seg, attr)
                orig_h_screen = location_3d_to_region_2d(rgn, r3d, M @ orig_h)
                if orig_h_screen is None:
                    continue
                d = orig_h_screen - pt_screen
                rotated_screen = Vector((
                    pt_screen.x + d.x * cos_a - d.y * sin_a,
                    pt_screen.y + d.x * sin_a + d.y * cos_a,
                ))
                new_world = region_2d_to_location_3d(rgn, r3d, rotated_screen, M @ orig_h)
                setattr(cbs[seg], attr, Mi @ new_world)

        def _taper_weight(self, t, nseg):
            ''' 1.0 exactly at the Alt-scaled knot's own parameter, falling
            off LINEARLY to 0.0 by the adjacent knots (one full segment of
            parameter `t` away on either side) -- a localized taper centered
            on the dragged knot, not a uniform width change across the whole
            chain. Wraps around for a cyclic chain. '''
            dist = abs(t - self.taper_t)
            if self.chain['cyclic']:
                dist = min(dist, nseg - dist)
            return max(0.0, 1.0 - dist)

        def snap_co_to_feature(self, co_local):
            ''' Snap a local space coordinate onto the nearest source feature if within feature_radius.
            Returns the (possibly unchanged) local coordinate. '''
            accel = self.source_accel
            if not accel or self.feature_radius <= 0:
                return co_local
            co_world = self.M @ co_local
            corner = accel.find_corner(co_world)
            if corner and corner[2] <= self.feature_radius:
                return self.Mi @ Vector(corner[0])
            closest = accel.closest_point(co_world)
            if closest and (Vector(closest) - co_world).length <= self.feature_radius:
                return self.Mi @ Vector(closest)
            return co_local

        def _mirror_clamp(self, context, co, pt_edit_orig, M, Mi):
            ''' If `co` crossed a clipped mirror plane this frame (relative to
            `pt_edit_orig`, its position before this frame's move), iteratively
            pull it back onto the plane while keeping it snapped to source. '''
            if not self.mirror:
                return co
            th = self.mirror_threshold
            zero = {
                'x': ('x' in self.mirror and (sign_threshold(co.x, th.x) != sign_threshold(pt_edit_orig.x, th.x) or sign_threshold(pt_edit_orig.x, th.x) == 0)),
                'y': ('y' in self.mirror and (sign_threshold(co.y, th.y) != sign_threshold(pt_edit_orig.y, th.y) or sign_threshold(pt_edit_orig.y, th.y) == 0)),
                'z': ('z' in self.mirror and (sign_threshold(co.z, th.z) != sign_threshold(pt_edit_orig.z, th.z) or sign_threshold(pt_edit_orig.z, th.z) == 0)),
            }
            # iteratively zero out the component
            for _ in range(1000):
                d = 0
                if zero['x']: co.x, d = co.x * 0.95, max(abs(co.x), d)
                if zero['y']: co.y, d = co.y * 0.95, max(abs(co.y), d)
                if zero['z']: co.z, d = co.z * 0.95, max(abs(co.z), d)
                co_world = M @ Vector((*co, 1.0))
                co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True, sources=self.sources, respect_clip_planes=True)
                if not co_world_snapped: break
                co = Mi @ co_world_snapped
                if d < 0.001: break  # break out if change was below threshold
            if zero['x']: co.x = 0
            if zero['y']: co.y = 0
            if zero['z']: co.z = 0
            return co

        def _relax_interior(self, context, iterations):
            ''' Runs the interior-vert Laplacian relaxation (see
            _relax_interior_verts) if this chain has one, then snaps each
            interior vert to source and applies the same mirror clamp the
            boundary loop's own verts get, for consistency. Called after the
            boundary verts are updated each frame -- interior verts always
            follow the boundary's CURRENT shape (including whatever
            proportional-edit falloff was applied to it), never the raw
            handle delta directly. '''
            interior = self.interior
            if not interior:
                return
            bm = self.bm
            _relax_interior_verts(bm, interior, iterations)
            for idx in interior['indices']:
                bmv = bm.verts[idx]
                co = nearest_point_valid_sources(context, bmv.co, world=False, sources=self.sources, respect_clip_planes=True) or bmv.co
                bmv.co = self._mirror_clamp(context, co, interior['orig_co'][idx], self.M, self.Mi)

        def update(self, context, event):
            data = self.grab['data']
            bm, em = self.bm, self.em

            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                # a fast drag-and-release may not have accumulated enough
                # per-frame iterations to fully catch up to the final
                # boundary shape -- settle harder now that it's the last chance
                self._relax_interior(context, INTERIOR_RELAX_FINAL_ITERATIONS)
                bmesh.update_edit_mesh(em)
                return {'FINISHED'}

            if event.type in {'ESC', 'RIGHTMOUSE'}:
                for cb, pts in zip(self.spline.cbs, self.snapshot):
                    # restore snapshot
                    cb.p0, cb.p1, cb.p2, cb.p3 = (Vector(p) for p in pts)
                for bmv_idx in data:
                    bm.verts[bmv_idx].co = data[bmv_idx][2]
                if self.interior:
                    for idx, orig in self.interior['orig_co'].items():
                        bm.verts[idx].co = orig
                bmesh.update_edit_mesh(em)
                context.area.tag_redraw()
                return {'CANCELLED'}

            if event.type in {'WHEELDOWNMOUSE', 'WHEELUPMOUSE'}:
                if event.type == 'WHEELUPMOUSE':
                    context.tool_settings.proportional_distance *= 0.90
                else:
                    context.tool_settings.proportional_distance /= 0.90
                if self.grab['only']:
                    for bmv_idx in self.grab['only']:
                        bm.verts[bmv_idx].co = data[bmv_idx][2]
                self.grab['only'] = None

            mouse = mouse_from_event(event)
            self.grab['current'] = mouse
            delta = Vector(mouse) - self.grab['mouse']
            rgn, r3d = context.region, context.region_data
            M, Mi = self.M, self.Mi
            prop_dist_world = context.tool_settings.proportional_distance

            self.apply_handle(context, delta, rgn, r3d, M, Mi, event.alt, event.shift)

            if self.grab['only'] is None:
                self.grab['only'] = [
                    bmv_idx
                    for bmv_idx in data
                    if data[bmv_idx][3] <= prop_dist_world
                ]

            self._deform_verts(context, self.spline)
            self._relax_interior(context, INTERIOR_RELAX_ITERATIONS)

            bmesh.update_edit_mesh(em, loop_triangles=False)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        def _deform_verts(self, context, spline):
            ''' Repositions every vert in self.grab['only'] against `spline`,
            using each one's stored (t, offset, tangent) from init() -- see
            the per-vert fields unpacked below. POSITION is always computed
            FRESH from each vert's own pre-drag baseline (pt_edit_orig) via
            o + R@d, never incrementally from wherever it happened to land
            last frame, so every frame fully re-derives positions rather than
            compounding onto an already-moved vert.

            ROTATION (R, the per-vert cross-section rotation) is the one
            exception -- it's tracked incrementally frame-to-frame in
            self.grab['rot'], NOT recomputed fresh as a single shortest-arc
            rotation from init's z0 to the current z1. This is a deliberate,
            necessary exception: "the rotation taking z0 to z1" is not a
            well-defined function of just (z0, z1) alone once the tangent has
            actually turned by more than 180 degrees over the course of the
            drag (e.g. an adjacent endpoint's Vector handle sweeping around
            as its neighbor is dragged past it) -- shortest-arc only ever
            "sees" the two endpoints and always picks the <=180 degree way
            around, which is a DIFFERENT rotation than the curve's own
            continuous turning once the true total exceeds 180. Two verts
            whose true accumulated turn straddle that threshold (one at 179,
            one at 181) would then rotate around unrelated axes despite
            having nearly identical tangents -- a visible twist in the
            connecting geometry even though the curve/handles are perfectly
            smooth. Composing many small per-frame deltas (each well inside
            the safe range, since real mouse motion doesn't swing a tangent
            180 degrees in a single event) tracks the true total instead.

            Split into passes rather than one straight-through loop: the
            RE-CENTERING pass below needs BOTH of a rung's verts' offsets
            already computed before either can be finalized, so no vert can
            be written to bmv.co until its whole rung has been visited. '''
            data = self.grab['data']
            rot_state = self.grab['rot']
            bm = self.bm
            M, Mi = self.M, self.Mi
            prop_use = context.tool_settings.use_proportional_edit
            prop_dist_world = context.tool_settings.proportional_distance
            prop_falloff = context.tool_settings.proportional_edit_falloff
            # _scale_handles only ever sets taper_scale on a face-derived
            # (uncoupled) chain -- a vertex-coupled chain has no "width" to
            # taper, since its verts already sit ON the curve, so Alt
            # reshapes its handles instead (see _scale_handles)
            taper_active = self.taper_scale is not None
            nseg = len(spline.cbs)
            fn_dist = lambda a, b: (a - b).length
            combined_cum = _cumulative_lengths(spline.cbs, self.combined_segs, fn_dist) if self.combined_segs else None

            # Pass 1: compute each vert's (anchor, offset) exactly as before,
            # but stop short of finalizing bmv.co -- see pass 2 below.
            # Grouped by `t` (reassigned below, same value as before this
            # change): every vert of a rung is parametrized from the same
            # shared rung midpoint (see init()'s rung_map comment), so they
            # deterministically compute the identical t here -- a reliable,
            # tolerance-free grouping key.
            computed = {}
            rung_groups = {}
            for bmv_idx in self.grab['only']:
                t, d0, pt_edit_orig, distance, arc_frac, combined_frac, z0, fit_w, end_t, overhang = data[bmv_idx]
                if arc_frac is None and combined_frac is None:
                    # this vert's segment is neither touched nor part of a
                    # combined free-knot run -- its t maps into a segment whose
                    # control points this drag never moves, so eval(t) can only
                    # ever reproduce the exact same point it's already at
                    continue
                if distance > prop_dist_world: continue
                if prop_use:
                    dist = max(1 - distance / prop_dist_world, 0)
                    factor = proportional_edit(prop_falloff, dist)
                else:
                    factor = 1
                if combined_frac is not None:
                    # this vert is somewhere in the combined run spanning a free
                    # knot -- keep its proportional position within that run's
                    # *current* total arc length (recomputed above, since the
                    # run's segments keep reshaping as the drag continues)
                    target = combined_frac * combined_cum[-1]
                    idx = 0
                    while idx < len(combined_cum) - 2 and target > combined_cum[idx + 1]:
                        idx += 1
                    seg = self.combined_segs[idx]
                    seg_span = max(combined_cum[idx + 1] - combined_cum[idx], 1e-9)
                    local_frac = (target - combined_cum[idx]) / seg_span
                    t = seg + spline.cbs[seg].approximate_t_at_arc_length_fraction(local_frac, fn_dist)
                elif arc_frac is not None:
                    # this vert's segment is being reshaped -- track its original
                    # proportional position along the arc length instead of its raw
                    # parameter t, so reshaping the segment doesn't bunch verts up
                    # or spread them out relative to each other
                    seg = min(int(t), nseg - 1)
                    t = seg + spline.cbs[seg].approximate_t_at_arc_length_fraction(arc_frac, fn_dist)
                # how close the dragged Automatic knot is to the straight line
                # between its neighbors (see _recompute_typed_handles), but
                # only for verts on the two segments that line actually spans
                # -- see the curve-normal correction below.
                horizon_boost = self.horizon_factor if seg in self.horizon_segs else 0.0
                # cap verts (end_t is not None) are parametrized by their
                # END's t, not their own approximate t, and re-extrapolated
                # against the LIVE spline every frame -- see init()'s
                # end_t/overhang comment for why. overhang is fixed (cached
                # at init like d0); only the endpoint/tangent it extends from
                # is re-evaluated here as the curve reshapes.
                eval_t = t if end_t is None else end_t
                o = spline.eval(eval_t)
                z1 = Vector(spline.eval_derivative(eval_t))
                if z1.length < 1e-9: z1 = Vector((0, 0, 1))
                z1.normalize()
                # rotate the stored offset by however much this material point's
                # tangent has turned since init (z0 -> z1). A rotation applied to
                # the whole cross-section rotates it rigidly: it can't shear the
                # faces and undoes itself exactly when the curve straightens back
                # out (z1 -> z0 => identity). Independent of view, so no tangent-
                # parallel-to-camera degeneracy either.
                #
                # Tracked as a small INCREMENT from last frame's accumulated
                # rotation, not a single shortest-arc jump from init's z0 -- see
                # this method's docstring for why a fresh-each-frame shortest arc
                # from z0 directly is NOT equivalent once the true turn exceeds
                # 180 degrees over the course of the drag.
                R_prev = rot_state[bmv_idx]
                z_prev = R_prev @ z0
                if z_prev.dot(z1) < -0.9999:
                    # this frame's tangent fully reversed relative to last frame
                    # -- shortest-arc axis is undefined, so rotation_difference
                    # would pick an arbitrary one and flip the cross-section
                    # randomly. Only reachable by an extreme single-event jump
                    # (not continuous mouse motion); hold last frame's rotation
                    # rather than spin randomly.
                    delta_R = Quaternion()
                else:
                    delta_R = z_prev.rotation_difference(z1)
                R = delta_R @ R_prev
                rot_state[bmv_idx] = R
                if end_t is not None:
                    # extend along R@z0 rather than raw z1 -- identical to z1
                    # normally (R is defined to take z0 to z1 exactly), but when
                    # the guard above holds R at last frame's value (delta_R
                    # frozen to identity for one frame), this holds the anchor's
                    # extrapolation there too, instead of separately reading the
                    # (momentarily untrustworthy) live z1 and flinging the cap
                    # anchor to a different side of the endpoint than whatever
                    # the rotation below settles on that same frame.
                    ext_dir = R @ z0 if end_t > 0.0 else -(R @ z0)
                    o = o + ext_dir * overhang
                d = d0
                if taper_active:
                    w = self._taper_weight(t, nseg)
                    if w > 0:
                        # d0 is this vert's offset FROM the curve, and (nearest-
                        # point projection) is essentially perpendicular to the
                        # tangent, so scaling it directly scales the vert's own
                        # perpendicular distance from the curve -- i.e. the strip's
                        # width at this point, not its position along the curve
                        d = d0 * (1 + (self.taper_scale - 1) * w)
                d_final = R @ d
                # Rigid rotation alone preserves the original fit exactly -- great
                # for gentle edits, but any skew the fit already had is carried
                # (and amplified) through extreme edits, which can kink the faces.
                # So as the edit gets large, nudge a WELL-FIT cross-section toward
                # the curve's normal plane (drop the component running along the
                # tangent, keep the perpendicular part at full width). The nudge is
                # gated by fit_w * edit_w: a poorly-fit strip (fit_w -> 0) is left
                # untouched. A gentle edit (edit_w -> 0) stays purely rigid and
                # reversible. Only a big change to a good fit gets straightened --
                # so e.g. pulling an extreme S back out lands on much flatter
                # faces. No end-taper needed: end-cap verts get a genuinely HIGH
                # fit_w now that their anchor is extrapolated out to the cap (see
                # init()'s end_t/overhang) instead of clamped short, so their
                # offset is already close to perpendicular -- "flattening" an
                # already-flat offset is close to a no-op, not a squash. (A
                # previous fixed distance-from-end fade zeroed the correction
                # right at the caps regardless of fit, which left raw rigid
                # rotation unprotected there -- when the tangent swings hard near
                # an endpoint, e.g. an Automatic handle sweeping across the
                # horizon, that unprotected rotation could flip/twist the end
                # faces. Removed in favor of fit_w alone; the extrapolation fix
                # here is what makes fit_w alone actually correct for end caps.)
                #
                # ADDITIONALLY forced toward full strength (blend -> 1) by
                # horizon_boost as the dragged Automatic knot approaches the
                # straight line between its neighbors, on top of (not gated
                # by) fit_w * edit_w -- this is what guarantees the strip
                # actually goes perfectly flat right when that line goes
                # perfectly straight, rather than only however much fit_w *
                # edit_w happens to have reached by that point. Unlike the
                # fit_w*edit_w path, this deliberately overrides even a
                # poorly-fit vert (fit_w -> 0 no longer gates it out), since
                # the goal here is an unconditional guarantee at the straight-
                # line limit, not a conservative "only touch good fits" nudge.
                d_len = d.length
                if d_len > 1e-9:
                    edit_w = min(z0.angle(z1, 0.0) / CURVE_NORMAL_EDIT_ANGLE, 1.0)
                    blend = max(fit_w * edit_w, horizon_boost)
                    if blend > 0.0:
                        d_perp = d_final - d_final.dot(z1) * z1
                        if d_perp.length > 1e-9:
                            d_normal = d_perp * (d_len / d_perp.length)
                            d_final = d_final.lerp(d_normal, blend)
                computed[bmv_idx] = [o, d_final, horizon_boost, factor, pt_edit_orig]
                rung_groups.setdefault(t, []).append(bmv_idx)

            # Pass 2: a rung's two verts share one anchor `o`, but the curve-
            # normal correction above rescales EACH vert's offset back up to
            # its OWN original length independently -- if the two weren't
            # perfectly symmetric to begin with (an ordinary small fit
            # residual: `o` is the nearest point ON the curve to the rung's
            # midpoint, not necessarily exactly equal to it), that
            # independent rescale can leave the rung's own center off of `o`
            # even though each vert's TILT is now individually correct --
            # visible as a slight skew in the rail edge loops even on an
            # otherwise dead-straight stretch. Pull the rung's average
            # offset back to zero (recentering it on `o`), scaled by the
            # SAME horizon_boost as the tilt correction so it ramps in
            # together and never touches a rung the horizon blend doesn't
            # reach. A rung with fewer than 2 of its verts actually computed
            # this frame (e.g. one excluded by proportional-edit falloff)
            # has nothing to center against, so it's left alone.
            for idxs in rung_groups.values():
                if len(idxs) < 2:
                    continue
                boost = computed[idxs[0]][2]
                if boost <= 0.0:
                    continue
                center_off = sum((computed[i][1] for i in idxs), Vector((0.0, 0.0, 0.0))) / len(idxs)
                if center_off.length < 1e-9:
                    continue
                for i in idxs:
                    computed[i][1] = computed[i][1] - center_off * boost

            # Pass 3: finalize -- unchanged from before this split, just
            # reading back what pass 1/2 computed instead of running inline.
            for bmv_idx, (o, d_final, horizon_boost, factor, pt_edit_orig) in computed.items():
                bmv = bm.verts[bmv_idx]
                pt_edit_new = M @ (o + d_final)
                pt_edit_new = pt_edit_orig + (pt_edit_new - pt_edit_orig) * factor
                co = nearest_point_valid_sources(context, pt_edit_new, world=False, sources=self.sources, respect_clip_planes=True) or pt_edit_orig
                co = self.snap_co_to_feature(co)
                bmv.co = self._mirror_clamp(context, co, pt_edit_orig, M, Mi)

        def draw_curve(self, context):
            ''' Draw the dashed curve + control handles live while dragging. '''
            rgn, r3d = context.region, context.region_data
            if not r3d: return
            M = self.M
            cbs = self.spline.cbs
            # see curve_overlay.py's draw_postpixel_overlay -- same hiding of
            # an Automatic knot's tangent handles, kept in sync here so a
            # handle can't visibly appear/disappear the instant a drag starts
            knot_type_by_vert = {
                h['vert_index']: h.get('handle_type')
                for h in self.chain['handles'] if h['kind'] == 'knot'
            }
            hidden_tangents = set() if DEBUG_SHOW_AUTO_HANDLES else {
                h['pos']
                for h in self.chain['handles']
                if h['kind'] == 'tangent' and knot_type_by_vert.get(h['owner_vert_index']) == 'automatic'
            }
            for i, cb in enumerate(cbs):
                curve_pts = [location_3d_to_region_2d(rgn, r3d, M @ Vector(cb.eval(v / 20))) for v in range(21)]
                curve_pts = [p for p in curve_pts if p]
                draw_curve_line = True
                if draw_curve_line and len(curve_pts) >= 2:
                    Drawing.draw2D_linestrip(context, curve_pts, CURVE_LINE_COLOR, width=2, stipple=[5,5])
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
            for h in self.chain['handles']:
                seg, attr = h['pos']
                p = location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cbs[seg], attr)))
                if not p: continue
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

        def draw_postpixel(self, context):
            ''' Draw the live curve, plus the proportional edit circle in 2D space. '''
            self.draw_curve(context)
            if not context.tool_settings.use_proportional_edit: return
            if self.selection_origin_3d is None or self.selection_origin_2d is None: return
            gpustate.blend('ALPHA')
            rgn, r3d = context.region, context.region_data

            pt = self.selection_origin_3d + context.tool_settings.proportional_distance * self.right
            pt2d = location_3d_to_region_2d(rgn, r3d, pt)
            if pt2d is None: return
            radius = pt2d[0] - self.selection_origin_2d[0]
            if self.handle['kind'] == 'knot':
                center = self.selection_origin_2d
            else:
                seg, attr = self.handle['pos']
                center = location_3d_to_region_2d(rgn, r3d, self.M @ Vector(getattr(self.spline.cbs[seg], attr)))
                if center is None: return

            col_off = 20/255
            color_in = Color((0.33+col_off, 0.33+col_off, 0.33+col_off, 1.0))
            color_out = Color((0.33-col_off, 0.33-col_off, 0.33-col_off, 1.0))

            gpustate.blend('ALPHA')
            Drawing.draw2D_smooth_circle(context, center, radius, color_out, width=3)
            Drawing.draw2D_smooth_circle(context, center, radius-1, color_in, width=1)
            gpustate.blend('NONE')

    return type(opname, (RFOperator_Curve_Edit, RFOperator), {})


def create_curve_toggle_handle_type_operator(
    idname : str,
    label : str,
    description : str,
    *,
    get_overlay : Callable[[], type[RFOverlay_Base] | None],
) -> Operator_Execute_Function:
    ''' Toggling curve control points (Aligned -> Vector -> Automatic -> Aligned):
        - on an edge loop, the cycle is a pure handle-type change: no vert ever moves, so it's perfectly
            reversible. Vector creases the fit at the knot and re-aims its arms and its neighbors'.
        - on a face strip, Vector means a topological corner: entering Vector inserts a real L-junction
            in the mesh, leaving Vector removes it. Knots that can't host a corner skip the Vector step.
    Open-chain endpoints stay forced Vector and aren't togglable (pre-corner-feature behavior). '''

    def _hovered_toggleable_knot():
        overlay_type = get_overlay()
        assert overlay_type
        overlay = overlay_type.instance
        if not overlay or not overlay.hovering:
            return None
        chain_idx, handle_idx, _snapshot = overlay.hovering
        chain = overlay.chains[chain_idx]
        handle = chain['handles'][handle_idx]
        if handle['kind'] != 'knot' or not handle.get('can_toggle', False):
            return None
        return overlay, chain, handle

    def can_toggle(context):
        # Only claim the hotkey while the cursor is actually over a curve control point.
        # Returning False when nothing is hovered or the curve overlay isn't even up lets Blender's Rip work
        # everywhere except right on a control point, where V toggles the handle instead.
        RFCore = RFGlobals.RFCore_None
        if not RFCore or not RFCore.is_running:
            return False
        if not context.edit_object or context.mode != 'EDIT_MESH':
            return False
        overlay_type = get_overlay()
        overlay = overlay_type.instance if overlay_type else None
        return bool(overlay and overlay.hovering)

    def _reroute_corner(context, overlay, chain, handle):
        ''' Insert or remove a topological L-corner on a face strip. '''
        cache_key = chain['cache_key']
        # even knot (face center 2k) -> face k, keeping the knot marker in place
        # odd knot (bend rung 2k-1) -> face k, so the corner's pivot vertex lands on that bend rung.
        # Matches the eligibility indices in QuadStripChainProvider.
        ci = handle['vert_index']
        face_pos = (ci + (ci & 1)) // 2
        is_corner = handle.get('handle_type') == 'vector'

        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        try:
            faces = [bm.faces[i] for i in cache_key[1:]]
        except IndexError:
            return {'CANCELLED'}
        if not (1 <= face_pos <= len(faces) - 2):
            return {'CANCELLED'}
        rungs = ordered_rungs(faces, False)

        M = context.edit_object.matrix_world

        edit = remove_corner if is_corner else insert_corner
        result = edit(bm, faces, rungs, face_pos)
        if result is None:
            return {'CANCELLED'}  # attached to existing geometry / degenerate so leave unchanged

        # the squared corner verts were placed in-plane, pull them onto the source
        for bmv in result.get('moved_verts', ()):
            if snapped := nearest_point_valid_sources(context, M @ bmv.co, world=False, respect_clip_planes=True):
                bmv.co = snapped

        # only decide the normal after it is on the surface
        orient_bmf_normals(context, [result['new_face']] if result.get('new_face') is not None else [], new_faces=True)

        # reselect the whole resulting strip so the overlay re-detects the same chain
        new_faces = [f for f in faces if f.is_valid]
        if result.get('new_face') is not None:
            new_faces.append(result['new_face'])
        bmops.deselect_all(bm)
        bmops.select_iter(bm, new_faces)
        bmops.flush_selection(bm, em)  # also calls bmesh.update_edit_mesh

        # force the overlay to re-collect and rebuild and drop cache keyed by the now-stale face indices
        type(overlay).depsgraph_version = -42
        overlay._curve_struct_cache.pop(cache_key, None)
        overlay._handle_type_overrides.pop(cache_key, None)
        context.area.tag_redraw()
        return {'FINISHED'}

    def toggle(context):
        found = _hovered_toggleable_knot()
        if found is None:
            return {'CANCELLED'}
        overlay, chain, handle = found
        cache_key, k = chain['cache_key'], handle['vert_index']
        current = handle.get('handle_type', 'automatic')

        if chain.get('coupled', True):
            # Edge loops: the pure handle-type cycle. No vert ever moves, so the toggle is perfectly reversible.
            overlay.toggle_handle_type(cache_key, k)
            context.area.tag_redraw()
            return {'CANCELLED'}

        if current == 'aligned':
            if handle.get('corner_eligible', False):
                return _reroute_corner(context, overlay, chain, handle)  # -> vector (insert corner)
            new_type = 'automatic'  # no corner possible here: skip Vector in the cycle
        elif current == 'vector':
            if handle.get('corner_eligible', False):
                return _reroute_corner(context, overlay, chain, handle)  # -> automatic (remove corner)
            return {'CANCELLED'}  # corner attached to existing geometry so leave unchanged
        else:  # automatic
            new_type = 'aligned'
        overlay.set_handle_type(cache_key, k, new_type, reposition=True)
        context.area.tag_redraw()
        return {'CANCELLED'}

    bl_idname = f'retopoflow.{idname}'
    return execute_operator(
        idname, label, description=description, options={'INTERNAL', 'UNDO'},
        fn_poll=can_toggle,
        keymaps=[(bl_idname, {'type': 'V', 'value': 'PRESS'}, None)],
    )(toggle)
