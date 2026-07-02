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
from mathutils import Vector
from bpy.types import Context, Event
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d

from collections.abc import Callable

from ..common.bmesh import get_bmesh_emesh
from ..common.drawing import Drawing
from ..common.maths import view_forward_direction, view_right_direction, xform_direction, proportional_edit
from ..common.raycast import raycast_point_valid_sources, nearest_point_valid_sources, mouse_from_event
from ..common.operator import RFOperator, RFKeyMaps
from ...addon_common.common import gpustate
from ...addon_common.common.maths import Frame, Color, sign_threshold
from ..rfoverlays.curve_overlay import (
    shrink_segment, KNOT_RADIUS, TANGENT_RADIUS,
    CURVE_LINE_COLOR, CONTROL_POLYGON_COLOR, TANGENT_FILL_COLOR, TANGENT_BORDER_COLOR,
    KNOT_FILL_COLOR, KNOT_BORDER_COLOR, FREE_KNOT_FILL_COLOR,
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
    get_overlay : Callable[[], type],
    on_init : Callable[[Context, Event], None] | None = None,
) -> type[RFOperator]:
    ''' Shared curve-handle drag operator: works for any overlay built with
    create_curve_overlay, regardless of whether its chains come from real
    edge loops/strips or from a derived centerline (e.g. a quad strip) --
    see curve_chain_providers.ChainSpec for what makes a chain interchangeable
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
            overlay = get_overlay().instance
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
            self.fwd = xform_direction(Mi, view_forward_direction(context))
            self.right = xform_direction(Mi, view_right_direction(context))
            self.spline.tessellate_uniform()

            fn_dist = lambda a, b: (a - b).length

            # segment(s) whose shape will change as this handle is dragged -- verts
            # on these need their *arc-length fraction* preserved instead of their
            # raw parameter t (which isn't proportional to arc length, so it drifts
            # spacing as a segment stretches/compresses under editing)
            nseg = len(self.spline.cbs)
            if self.handle['kind'] == 'knot':
                self.touched_segs = { seg for seg, _ in self.handle['set'] }
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
            for (bmv, distance) in all_bmvs.items():
                t = self.spline.approximate_t_at_point_tessellation(bmv.co, fn_dist)
                o = self.spline.eval(t)
                z = Vector(self.spline.eval_derivative(t))
                if z.length < 1e-9: z = Vector((0, 0, 1))
                z.normalize()
                f = Frame(o, x=self.fwd, z=z)
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
                    f.w2l_point(bmv.co),
                    Vector(bmv.co),
                    distance,
                    arc_frac,
                    combined_frac,
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
            }

            if on_init:
                on_init(self, context, event)

        def finish(self, context):
            # the spline being dragged IS the overlay's cached spline object (see
            # init), so its control points already hold this drag's final state --
            # committed or, on cancel, restored from the snapshot. But the cache's
            # 'cos' baseline still holds the PRE-drag point positions, so without
            # this sync the overlay's next rebuild would see "points moved a lot vs
            # the baseline", throw the dragged curve away, and refit it from
            # scratch -- a lossy reconstruction of a curve we're holding the exact
            # ground truth for (the verts were literally placed onto it by eval).
            # Syncing 'cos' to the chain's current points makes the next rebuild
            # see "nothing changed since this spline was built" and reuse it
            # verbatim (see _build_curve's nothing-changed shortcut). On cancel
            # this is a no-op by construction: update() restored the verts to the
            # very positions already in the cache.
            overlay = get_overlay().instance
            if overlay is not None:
                cache_key = self.chain['cache_key']
                cached = getattr(overlay, '_curve_struct_cache', {}).get(cache_key)
                if cached:
                    new_cos = self.chain['current_points'](self.bm)
                    if new_cos and len(new_cos) == len(cached['cos']):
                        cached['cos'] = new_cos
            get_overlay().unpause_update()

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
                knot_delta = new_edit - pt_orig
                for (seg, attr) in h['set']:
                    setattr(cbs[seg], attr, new_edit.copy())
                for (seg, attr) in h['move']:
                    setattr(cbs[seg], attr, orig(seg, attr) + knot_delta)
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
                co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True, respect_clip_planes=True)
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
                co = nearest_point_valid_sources(context, bmv.co, world=False, respect_clip_planes=True) or bmv.co
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
            fwd = self.fwd
            prop_use = context.tool_settings.use_proportional_edit
            prop_dist_world = context.tool_settings.proportional_distance
            prop_falloff = context.tool_settings.proportional_edit_falloff

            self.apply_handle(context, delta, rgn, r3d, M, Mi, event.alt, event.shift)

            # _scale_handles only ever sets taper_scale on a face-derived
            # (uncoupled) chain -- a vertex-coupled chain has no "width" to
            # taper, since its verts already sit ON the curve, so Alt
            # reshapes its handles instead (see _scale_handles)
            taper_active = self.taper_scale is not None

            if self.grab['only'] is None:
                self.grab['only'] = [
                    bmv_idx
                    for bmv_idx in data
                    if data[bmv_idx][3] <= prop_dist_world
                ]

            spline = self.spline
            nseg = len(spline.cbs)
            fn_dist = lambda a, b: (a - b).length
            combined_cum = _cumulative_lengths(spline.cbs, self.combined_segs, fn_dist) if self.combined_segs else None
            for bmv_idx in self.grab['only']:
                t, pt_curve_orig, pt_edit_orig, distance, arc_frac, combined_frac = data[bmv_idx]
                if arc_frac is None and combined_frac is None:
                    # this vert's segment is neither touched nor part of a
                    # combined free-knot run -- its t maps into a segment whose
                    # control points this drag never moves, so eval(t) can only
                    # ever reproduce the exact same point it's already at
                    continue
                bmv = bm.verts[bmv_idx]
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
                o = spline.eval(t)
                z = Vector(spline.eval_derivative(t))
                if z.length < 1e-9: z = Vector((0, 0, 1))
                z.normalize()
                f = Frame(o, x=fwd, z=z)
                local_pt = pt_curve_orig
                if taper_active:
                    w = self._taper_weight(t, nseg)
                    if w > 0:
                        # pt_curve_orig is already expressed as an offset FROM
                        # the curve (see Frame.w2l_point in init()), so scaling
                        # it directly scales this vert's own perpendicular
                        # distance from the curve -- i.e. the strip's width
                        # at this point, not its position along the curve
                        local_pt = pt_curve_orig * (1 + (self.taper_scale - 1) * w)
                pt_edit_new = M @ f.l2w_point(local_pt)
                pt_edit_new = pt_edit_orig + (pt_edit_new - pt_edit_orig) * factor
                co = nearest_point_valid_sources(context, pt_edit_new, world=False, respect_clip_planes=True) or pt_edit_orig
                bmv.co = self._mirror_clamp(context, co, pt_edit_orig, M, Mi)

            self._relax_interior(context, INTERIOR_RELAX_ITERATIONS)

            bmesh.update_edit_mesh(em)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        def draw_curve(self, context):
            ''' Draw the dashed curve + control handles live while dragging. '''
            rgn, r3d = context.region, context.region_data
            if not r3d: return
            M = self.M
            cbs = self.spline.cbs
            for cb in cbs:
                curve_pts = [location_3d_to_region_2d(rgn, r3d, M @ Vector(cb.eval(v / 20))) for v in range(21)]
                curve_pts = [p for p in curve_pts if p]
                draw_curve_line = True
                if draw_curve_line and len(curve_pts) >= 2:
                    Drawing.draw2D_linestrip(context, curve_pts, CURVE_LINE_COLOR, width=2, stipple=[5,5])
                p0_, p1_, p2_, p3_ = (location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cb, a))) for a in ('p0','p1','p2','p3'))
                knot_r, tan_r = Drawing.scale(KNOT_RADIUS/2), Drawing.scale(TANGENT_RADIUS/2)
                a0, a1 = shrink_segment(p0_, p1_, knot_r, tan_r)
                a2, a3 = shrink_segment(p2_, p3_, tan_r, knot_r)
                Drawing.draw2D_lines(context, [a0, a1, a2, a3], CONTROL_POLYGON_COLOR, width=2)
            knot_pts2d, free_knot_pts2d, tan_pts2d = [], [], []
            for h in self.chain['handles']:
                seg, attr = h['pos']
                p = location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cbs[seg], attr)))
                if not p: continue
                if h['kind'] != 'knot':
                    tan_pts2d.append(p)
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
