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
from mathutils import Vector, Quaternion, kdtree
from bpy.types import Context, Event
from bpy_extras.view3d_utils import location_3d_to_region_2d

from collections.abc import Callable

from ..common.accel import SourceCache
from ..common.bmesh import get_bmesh_emesh
from ..common.bmesh_maths import orient_bmf_normals
from ..common.curves import ordered_rungs
from ..common.topology_corners import insert_corner, remove_corner
from ..common.drawing import Drawing
from ..common.maths import proportional_edit
from ..common.raycast import raycast_point_valid_sources, nearest_point_valid_sources, iter_all_valid_sources, mouse_from_event, region_2d_to_location_3d_stable
from ..common.snapping import source_snap_settings, source_snap_radius
from ..common.operator import RFOperator, RFKeyMaps, execute_operator, Operator_Execute_Function
from ..rfoverlay_base import RFOverlay_Base
from ..rfoverlays.proportional_edit_overlay import draw_proportional_edit_circle
from ..rfglobals import RFGlobals
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import sign_threshold
from ..rfoverlays.curve_overlay import (
    shrink_segment, snap_hidden_vector_arms, KNOT_RADIUS, TANGENT_RADIUS,
    CURVE_LINE_COLOR, CONTROL_POLYGON_COLOR, TANGENT_FILL_COLOR, TANGENT_BORDER_COLOR,
    KNOT_FILL_COLOR, KNOT_BORDER_COLOR, FREE_KNOT_FILL_COLOR, AUTO_KNOT_FILL_COLOR,
    DEBUG_SHOW_AUTO_HANDLES,
)


# per-frame iterations for the interior-vert relaxation; it's warm-started, so a
# few iterations per frame track a slowly-moving boundary
INTERIOR_RELAX_ITERATIONS = 10
# extra settling on release, in case a fast drag-and-release didn't catch up
INTERIOR_RELAX_FINAL_ITERATIONS = 40

# tangent swing at which the curve-normal correction reaches full strength
# (ramps in below that) -- a feel knob, tune freely
CURVE_NORMAL_EDIT_ANGLE = math.radians(90)


def _relax_interior_verts(bm, interior, iterations):
    ''' Laplacian relaxation of a patch's interior verts as its boundary moves. '''
    # relaxes each vert's DISPLACEMENT from its original position, not its absolute
    # position, so nothing moves until the boundary does and existing surface detail
    # is preserved. Weighted by original edge length to reduce (not eliminate --
    # it's still a linear method) fold-over under large deformations.
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

def _segment_arc_length(cb):
    return sum(d for _, _, d in cb.get_tessellate_uniform())


def _cumulative_lengths(cbs, segs):
    ''' Running total arc length at each boundary of `segs` (len(segs)+1 entries, starting at 0). '''
    cumul = [0.0]
    for seg in segs:
        cumul.append(cumul[-1] + _segment_arc_length(cbs[seg]))
    return cumul


def _walk_free_run(start, step, nseg, cyclic, free_at_seg_p0, visited):
    ''' Walks `visited` outward from `start` (step = -1/+1), one segment at a time,
    for as long as the knot crossed at each step is free. Returns the new segments
    in walk order; `visited` grows so the opposite walk can't cross back in. '''
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

    # deliberately does NOT inherit RFOperator: __init_subclass__ auto-registers
    # anything with a bl_idname, so only the final type(...) combination below may
    # trigger that, exactly once
    class RFOperator_Curve_Edit:
        bl_idname = f'retopoflow.{idname}'
        bl_label = label
        bl_description = description
        bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

        rf_keymaps : RFKeyMaps = [
            (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS'}, None),
            # separate entries so Alt(+Shift) drags also start when the modifiers are
            # already held before the click -- unlisted modifiers default to False
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
            # freeze the overlay's knot-occlusion result for the whole drag
            self.knot_visible = dict(overlay.knot_visibility(context, chain_idx, self.chain))
            # set by apply_handle when Alt+dragging a knot -- see _scale_handles
            self.taper_scale = None
            self.taper_t = None
            # set by _recompute_typed_handles while dragging an Automatic knot with
            # two valid neighbors; no-op defaults for every other drag kind
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
            self.spline.tessellate_uniform()
            # Every vert below is parametrized by a nearest-point search over this tessellation.
            # With proportional editing on, "every vert" means every vert in the mesh,
            # so index it once instead.
            self.spline.tessellate_kdtree()

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


            # segments this drag reshapes -- their verts track arc-length fraction
            # instead of raw t, which drifts spacing as a segment stretches
            nseg = len(self.spline.cbs)
            if self.handle['kind'] == 'knot':
                self.touched_segs = { seg for seg, _ in self.handle['set'] }
                # a knot drag also live-recomputes adjacent Automatic/Vector knots'
                # arms, reshaping the segments past them; over-inclusion is harmless
                for seg in list(self.touched_segs):
                    for nb in (seg - 1, seg + 1):
                        if self.chain['cyclic']:
                            self.touched_segs.add(nb % nseg)
                        elif 0 <= nb < nseg:
                            self.touched_segs.add(nb)
            else:
                self.touched_segs = { self.handle['pos'][0] }
                if 'g1_peer' in self.handle:
                    # a G1-mirrored arm reshapes the peer segment too
                    self.touched_segs.add(self.handle['g1_peer'][0])
                # Alt-dragging a tangent scales/rotates its knot instead, which can
                # reshape the segment on the knot's other side -- cover it in case
                # Alt is held or toggled mid-drag
                knot_h = self._knot_for_tangent(self.handle)
                if knot_h:
                    self.touched_segs |= { seg for seg, _ in knot_h['move'] }

            # a free knot isn't a vertex, so nothing should bunch up on it as it
            # moves: treat the whole run between the nearest TRUE knots on either
            # side as one combined span, and keep each vert's proportional position
            # within that span's total arc length
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
                    # Nearest chain vert for every vert in the mesh.
                    kd = kdtree.KDTree(len(bmvs))
                    for i, bmv in enumerate(bmvs):
                        kd.insert(M @ bmv.co, i)
                    kd.balance()
                    all_bmvs = { bmv: kd.find(M @ bmv.co)[2] for bmv in self.bm.verts }
            else:
                all_bmvs = { bmv: 0.0 for bmv in bmvs }

            # all data is local to edit!
            data = {}
            combined_cumul = _cumulative_lengths(self.spline.cbs, self.combined_segs) if self.combined_segs else None
            # face strips only: {vert index -> (rung midpoint, rungs from nearest open
            # end, is_boundary)}; empty for vertex-coupled chains
            rung_map = self.chain.get('deform_bmv_rungs') or {}
            for (bmv, distance) in all_bmvs.items():
                # parametrize a strip vert by its rung's midpoint, so every vert of a
                # rung shares one t and a wide strip on a tight bend can't drift onto
                # the wrong stretch of curve; everyone else uses the vert itself
                rung = rung_map.get(bmv.index)
                # a strip's first/last rung only transforms when it's a genuine mesh
                # boundary: a connected end's verts are shared with un-edited faces
                # outside the chain, so skip their data entry and they never move
                if rung is None or rung[1] != 0.0 or rung[2]:
                    rung_pt = rung[0] if rung else bmv.co
                    t = self.spline.approximate_t_at_point_kdtree(rung_pt)
                    # a cap rung sits past the centerline's endpoint (it runs face
                    # center to face center), so extrapolate along the endpoint
                    # tangent out to the cap -- the cap vert's offset then lands
                    # perpendicular like any interior vert. Re-applied against the
                    # live spline each frame.
                    end_t = None
                    if rung and rung[1] == 0.0:
                        end_t = 0.0 if t < nseg / 2 else float(nseg)
                    eval_t = t if end_t is None else end_t
                    # capture the pre-drag tangent now (the original curve is gone once
                    # handles move); each frame the offset rotates rigidly by however
                    # much this point's tangent has turned -- no shear, exactly reversible
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
                    # 1 = offset perpendicular to the tangent (clean cross-section),
                    # 0 = offset runs along the curve (poor fit); gates the curve-normal
                    # correction so bad fits are left alone
                    d0_len = d0.length
                    fit_w = (1.0 - abs(d0.dot(z0) / d0_len)) if d0_len > 1e-9 else 0.0
                    seg = min(int(t), nseg - 1)
                    arc_frac = None
                    combined_frac = None
                    if self.combined_segs and seg in self.combined_segs:
                        idx = self.combined_segs.index(seg)
                        local_frac = self.spline.cbs[seg].approximate_arc_length_fraction_at_t(t - seg)
                        dist_into_combined = combined_cumul[idx] + local_frac * (combined_cumul[idx + 1] - combined_cumul[idx])
                        combined_frac = dist_into_combined / max(combined_cumul[-1], 1e-9)
                    elif seg in self.touched_segs:
                        arc_frac = self.spline.cbs[seg].approximate_arc_length_fraction_at_t(t - seg)
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
                        # only rung verts carry a real cross-section offset -- see the
                        # curve-normal correction gate in _deform_verts
                        rung is not None,
                    )

            # a loop around a selected patch carries the patch's interior verts too;
            # they aren't curve-driven -- their displacement is relaxed each frame,
            # with outside neighbors excluded so the patch can't leak
            self.interior = None
            interior_bmv_indices = self.chain.get('interior_bmv_indices')
            if interior_bmv_indices:
                allowed = set(self.chain['deform_bmv_indices']) | set(interior_bmv_indices)
                neighbors = {}
                orig_co = {}
                for idx in interior_bmv_indices:
                    bmv = self.bm.verts[idx]
                    orig_co[idx] = Vector(bmv.co)
                    # weighted by original edge length -- see _relax_interior_verts
                    neighbors[idx] = [
                        (other.index, 1.0 / max((other.co - bmv.co).length, 1e-6))
                        for bme in bmv.link_edges
                        if (other := bme.other_vert(bmv)).index in allowed
                    ]
                # boundary verts' original positions, to turn their curve-driven
                # positions into displacements each frame
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
            # the dragged spline IS the overlay's cached one, so sync the cache's
            # 'cos' baseline to the current points and the next rebuild reuses it
            # verbatim. A refit here is NOT a safe no-op: the plain best-fit search
            # knows nothing about handle types or a deliberate straight-line result
            # and can visibly replace it the instant the drag ends.
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

            # reset each frame; only re-set below by the drag kinds that use them
            # (Alt-scale taper, Automatic-knot horizon), so nothing lingers
            self.taper_scale = None
            self.taper_t = None
            self.horizon_factor = 0.0
            self.horizon_segs = frozenset()

            # Alt/Alt+Shift always act on a KNOT -- redirect a grabbed tangent to
            # its knot so users don't have to remember which of the two to click
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
                # the rigid translate is only the baseline (and all an Aligned knot
                # gets): Automatic/Vector arms recompute from the knots' current
                # positions every frame, for the dragged knot and its neighbors
                self._recompute_typed_handles(h, cbs)
            else:
                # tangent arms move freely in the view plane
                new_world = region_2d_to_location_3d_stable(rgn, r3d, new_screen, M @ pt_orig)
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
                # a direct tangent drag is a manual choice: pin an AUTOMATIC owner
                # to 'aligned' so a later drag of that knot doesn't overwrite the
                # adjustment. A VECTOR owner keeps its type -- the next drag
                # re-snapshots from this edit as the new baseline offset, whereas
                # pinning would freeze it solid for no benefit.
                overlay = get_overlay().instance
                owner = h.get('owner_vert_index')
                if overlay is not None and owner is not None:
                    owner_kh = self._knot_for_tangent(h)
                    if owner_kh is None or owner_kh.get('handle_type') != 'vector':
                        overlay.set_handle_type(self.chain['cache_key'], owner, 'aligned')

        def _knot_for_tangent(self, h):
            ''' The knot handle that owns this tangent handle. Every tangent belongs
            to exactly one knot by construction; None is a defensive fallback. '''
            pos = h['pos']
            for other in self.chain['handles']:
                if other['kind'] == 'knot' and pos in other['move']:
                    return other
            return None

        def _recompute_typed_handles(self, dragged_h, cbs):
            ''' Live handle update while an Automatic knot is dragged: blends the
            fitted handles toward Blender's point-at handles as the knot nears the
            straight line between its two neighbors, reaching pure point-at (exactly
            straight) right on it. Touches only the dragged knot's arms and each
            neighbor's facing arm. '''
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

            # the neighbors don't move during the drag, so the line between them is
            # fixed; the dragged knot's perpendicular distance to it drives the blend
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

            # expose this frame's horizon proximity to _deform_verts, scoped to the
            # two segments flanking the dragged knot -- the ones that straighten
            nseg_local = n if cyclic else n - 1
            seg_prev = (idx - 1) % nseg_local if cyclic else idx - 1
            seg_next = idx % nseg_local if cyclic else idx
            self.horizon_factor = factor
            self.horizon_segs = frozenset((seg_prev, seg_next))

            def reflect(v):
                # mirror across the plane through the line: flips only the component
                # crossing it, so an in-plane U reflects cleanly
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
                # the fitted arm's original offset from its knot: only its LENGTH is
                # used directly, plus (via offset_rot) how far it differed from point-at
                rest_off_raw = snap(arm) - snap(kh['pos'])
                length = rest_off_raw.length

                # scale the fit-derived length by however much Blender's own handle
                # length would have changed since grab -- a frozen length can
                # overshoot a now-much-closer neighbor and kink the curve
                ref0 = blender_len_ref(owner_i, attr, snap)
                ref1 = blender_len_ref(owner_i, attr, cur)
                scale = max(0.0, ref1 / ref0) if (ref0 is not None and ref0 > 1e-9 and ref1 is not None) else 1.0
                length *= scale
                final_pos = knot_now + rest_off_raw * scale   # plain rigid-carry fallback (degenerate case only)

                pad0 = point_at_dir(owner_i, attr, snap)   # point-at direction AT GRAB TIME
                pad1 = point_at_dir(owner_i, attr, cur)    # point-at direction NOW
                if length > 1e-9 and pad0 is not None and pad0.length > 1e-9 and pad1 is not None and pad1.length > 1e-9:
                    pad0n, pad1n = pad0.normalized(), pad1.normalized()
                    # the fixed rotation from pure point-at to what the fit had,
                    # measured once at grab time
                    offset_rot = pad0n.rotation_difference(rest_off_raw.normalized())
                    # slerp that offset to identity as the knot nears the line: at the
                    # line it's pure point-at (exactly straight), at/beyond the grab
                    # distance the full offset rides the CURRENT point-at direction
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
            # each neighbor's arm facing the dragged knot -- but not an Aligned
            # neighbor's (its direction is the user's own to keep)
            if prev_h.get('handle_type') in ('automatic', 'vector'):
                recompute_arm(idx - 1, 'p1')   # prev's outgoing arm faces the dragged knot
                if prev_h.get('handle_type') == 'automatic':
                    # an Automatic knot's arms must stay collinear, so its far arm
                    # follows; a Vector neighbor's arms are independent
                    recompute_arm(idx - 1, 'p2')
            if next_h.get('handle_type') in ('automatic', 'vector'):
                recompute_arm(idx + 1, 'p2')   # next's incoming arm faces the dragged knot
                if next_h.get('handle_type') == 'automatic':
                    recompute_arm(idx + 1, 'p1')   # next's FAR arm, kept in line with the one just updated

        def _handle_pivot(self, h, orig):
            ''' The knot at the far end of this knot's first flanking segment (v3
            PolyStrips' "outerP") -- a well-separated reference for measuring an
            Alt-drag gesture, since the drag starts on the edited knot itself. '''
            if not h['move']:
                return None
            ref_seg, ref_attr = h['move'][0]
            pivot_seg, pivot_attr = (ref_seg, 'p0') if ref_attr == 'p2' else (ref_seg, 'p3')
            return orig(pivot_seg, pivot_attr)

        def _scale_handles(self, h, seg0, attr0, pt_orig, delta, rgn, r3d, M, orig, cbs):
            ''' Alt+drag on a knot: pin the knot and either scale its arms' lengths
            by a common factor, or -- on a face-derived chain -- taper the strip's
            width instead; never both. Ported from v3 PolyStrips' corner-scale. '''
            # the factor is mouse distance from a fixed, far pivot vs at drag start;
            # measuring against the arm's own short length was oversensitive
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
                # an edge-loop chain has no width to taper -- scale the knot's own
                # arms instead, each from its own original length
                for (seg, attr) in h['move']:
                    orig_h = orig(seg, attr)
                    setattr(cbs[seg], attr, pt_orig + (orig_h - pt_orig) * scale)
            else:
                # a face strip's handles describe its spine -- scaling them would
                # bend the spine as a side effect of the taper, so hold the curve at
                # its snapshot and taper the verts' width against it instead (see
                # the taper_scale block in _deform_verts)
                for (seg, attr) in h['move']:
                    setattr(cbs[seg], attr, orig(seg, attr))
                self.taper_scale = scale
                self.taper_t = float(seg0 if attr0 == 'p0' else seg0 + 1)

        def _rotate_handles(self, h, seg0, attr0, pt_orig, pt_screen, delta, rgn, r3d, M, Mi, orig, cbs):
            ''' Alt+Shift-drag on a knot: pin the knot and rotate its arms by a
            common angle around it, preserving their lengths. Same on both chain
            kinds -- reshaping the curve's direction IS what a strip's spine wants. '''
            # angle measured around the same far pivot as _scale_handles (the drag
            # starts ON the knot, so its own angle is undefined), then applied
            # around the knot itself in screen space, matching v3 PolyStrips
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
                new_world = region_2d_to_location_3d_stable(rgn, r3d, rotated_screen, M @ orig_h)
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
            ''' Relaxes this chain's interior verts (if any) against the boundary's
            current shape, then snaps them to source with the same mirror clamp the
            boundary verts get. '''
            interior = self.interior
            if not interior:
                return
            bm = self.bm
            _relax_interior_verts(bm, interior, iterations)
            for idx in interior['indices']:
                bmv = bm.verts[idx]
                # input must be WORLD (world=False only localizes the output)
                co = nearest_point_valid_sources(context, self.M @ bmv.co, world=False, sources=self.sources, respect_clip_planes=True) or bmv.co
                bmv.co = self._mirror_clamp(context, co, interior['orig_co'][idx], self.M, self.Mi)

        def update(self, context, event):
            data = self.grab['data']
            bm, em = self.bm, self.em

            if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                # settle the interior harder -- a fast drag-and-release may not have
                # caught up to the final boundary shape
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
            # hidden vector arms are point-at handles under the hood. Re-aim
            # them at the knots' CURRENT positions every frame, so a segment
            # whose arms aren't drawn stays straight.
            snap_hidden_vector_arms(self.spline.cbs, self.chain['handles'])

            if self.grab['only'] is None:
                # arc_frac/combined_frac (indices 4/5) are both None when a vert's t falls in a
                # segment whose control points this drag never touches.
                self.grab['only'] = [
                    bmv_idx
                    for bmv_idx in data
                    if data[bmv_idx][3] <= prop_dist_world
                    and (data[bmv_idx][4] is not None or data[bmv_idx][5] is not None)
                ]

            self._deform_verts(context, self.spline)
            self._relax_interior(context, INTERIOR_RELAX_ITERATIONS)

            bmesh.update_edit_mesh(em, loop_triangles=False)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        def _deform_verts(self, context, spline):
            ''' Repositions every vert in self.grab['only'] against `spline` from
            its stored (t, offset, tangent). Positions re-derive fresh from the
            pre-drag baseline every frame; only the rotation state persists. '''
            data = self.grab['data']
            rot_state = self.grab['rot']
            bm = self.bm
            M, Mi = self.M, self.Mi
            prop_use = context.tool_settings.use_proportional_edit
            prop_dist_world = context.tool_settings.proportional_distance
            prop_falloff = context.tool_settings.proportional_edit_falloff
            # taper_scale is only ever set for a face-derived chain -- see _scale_handles
            taper_active = self.taper_scale is not None
            nseg = len(spline.cbs)
            combined_cumul = _cumulative_lengths(spline.cbs, self.combined_segs) if self.combined_segs else None

            # Pass 1: compute each vert's (anchor, offset) but don't finalize
            # bmv.co yet -- pass 2 needs a whole rung's results first. A rung's
            # verts share a parametrization point, so `t` is a reliable group key.
            computed = {}
            rung_groups = {}
            for bmv_idx in self.grab['only']:
                t, d0, pt_edit_orig, distance, arc_frac, combined_frac, z0, fit_w, end_t, overhang, is_rung = data[bmv_idx]
                if arc_frac is None and combined_frac is None:
                    # this drag never moves this vert's segment; grab['only'] already
                    # filters these out, kept as a guard
                    continue
                if distance > prop_dist_world: continue
                if prop_use:
                    dist = max(1 - distance / prop_dist_world, 0)
                    factor = proportional_edit(prop_falloff, dist)
                else:
                    factor = 1
                if combined_frac is not None:
                    # keep this vert's proportional position within the free-knot
                    # run's CURRENT total arc length
                    target = combined_frac * combined_cumul[-1]
                    idx = 0
                    while idx < len(combined_cumul) - 2 and target > combined_cumul[idx + 1]:
                        idx += 1
                    seg = self.combined_segs[idx]
                    seg_span = max(combined_cumul[idx + 1] - combined_cumul[idx], 1e-9)
                    local_frac = (target - combined_cumul[idx]) / seg_span
                    t = seg + spline.cbs[seg].approximate_t_at_arc_length_fraction(local_frac)
                elif arc_frac is not None:
                    # track arc-length fraction, not raw t, so the reshaping segment
                    # doesn't bunch its verts up or spread them out
                    seg = min(int(t), nseg - 1)
                    t = seg + spline.cbs[seg].approximate_t_at_arc_length_fraction(arc_frac)
                # how close the dragged Automatic knot is to the line between its
                # neighbors, for rung verts on the two segments that line spans
                horizon_boost = self.horizon_factor if (is_rung and seg in self.horizon_segs) else 0.0
                # cap verts (end_t set) evaluate at their end's t and re-extrapolate
                # against the live spline each frame -- see init()
                eval_t = t if end_t is None else end_t
                o = spline.eval(eval_t)
                z1 = Vector(spline.eval_derivative(eval_t))
                if z1.length < 1e-9: z1 = Vector((0, 0, 1))
                z1.normalize()
                # rotate the stored offset by however much this point's tangent has
                # turned since init: rigid, so it can't shear and undoes itself when
                # the curve straightens back out. Tracked as small per-frame deltas
                # composed into grab['rot'] -- a single shortest-arc from z0 picks
                # the wrong way around once the true total turn exceeds 180 degrees,
                # twisting adjacent verts around unrelated axes.
                R_prev = rot_state[bmv_idx]
                z_prev = R_prev @ z0
                if z_prev.dot(z1) < -0.9999:
                    # tangent fully reversed in one event: the shortest-arc axis is
                    # undefined, so hold last frame's rotation rather than spin randomly
                    delta_R = Quaternion()
                else:
                    delta_R = z_prev.rotation_difference(z1)
                R = delta_R @ R_prev
                rot_state[bmv_idx] = R
                if end_t is not None:
                    # extend along R@z0, not raw z1: identical normally, but when the
                    # guard above freezes R for a frame this keeps the cap anchor on
                    # the same side the rotation settles on
                    ext_dir = R @ z0 if end_t > 0.0 else -(R @ z0)
                    o = o + ext_dir * overhang
                d = d0
                if taper_active:
                    w = self._taper_weight(t, nseg)
                    if w > 0:
                        # d0 is essentially perpendicular to the tangent, so scaling
                        # it scales the strip's width here, not position along it
                        d = d0 * (1 + (self.taper_scale - 1) * w)
                d_final = R @ d
                # Curve-normal correction, RUNG VERTS ONLY: as the edit gets large
                # (edit_w) nudge a well-fit (fit_w) cross-section into the curve's
                # normal plane at full width, so carried-along fit skew can't kink
                # the faces; horizon_boost forces it to full strength -- bypassing
                # fit_w -- so a perfectly straight line yields a perfectly flat
                # strip. Everyone else's d0 is fit residual, not a width: rescaling
                # its perpendicular NOISE back up to full length flings the vert in
                # an arbitrary direction, so non-rung verts stay purely rigid.
                d_len = d.length
                if d_len > 1e-9 and is_rung:
                    edit_w = min(z0.angle(z1, 0.0) / CURVE_NORMAL_EDIT_ANGLE, 1.0)
                    blend = max(fit_w * edit_w, horizon_boost)
                    if blend > 0.0:
                        d_perp = d_final - d_final.dot(z1) * z1
                        if d_perp.length > 1e-9:
                            d_normal = d_perp * (d_len / d_perp.length)
                            d_final = d_final.lerp(d_normal, blend)
                computed[bmv_idx] = [o, d_final, horizon_boost, factor, pt_edit_orig]
                rung_groups.setdefault(t, []).append(bmv_idx)

            # Pass 2: the correction rescales each vert's offset independently, so
            # a slightly asymmetric rung can end up centered off its anchor `o` --
            # a subtle rail skew even on a straight stretch. Pull the rung's average
            # offset back to zero, ramped by the same horizon_boost. A rung with
            # fewer than 2 verts computed this frame has nothing to center against.
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

            # Pass 3: finalize
            for bmv_idx, (o, d_final, horizon_boost, factor, pt_edit_orig) in computed.items():
                bmv = bm.verts[bmv_idx]
                # blend in local space; the surface query below wants world input
                pt_edit_new = pt_edit_orig + ((o + d_final) - pt_edit_orig) * factor
                co = nearest_point_valid_sources(context, M @ pt_edit_new, world=False, sources=self.sources, respect_clip_planes=True) or pt_edit_orig
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
            # also hide handles with too few verts in their segment to reshape
            hidden_tangents |= {
                h['pos'] for h in self.chain['handles'] if h['kind'] == 'tangent' and h.get('inert')
            }
            # and any arm whose knot was behind the source when the drag started
            hidden_tangents |= {
                h['pos'] for h in self.chain['handles']
                if h['kind'] == 'tangent' and not self.knot_visible.get(h['owner_vert_index'], True)
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
                if h['kind'] == 'knot' and h.get('inert'): continue
                if h['kind'] == 'knot' and not self.knot_visible.get(h['vert_index'], True): continue
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
            h = self.handle
            knot_h = h if h['kind'] == 'knot' else self._knot_for_tangent(h)
            if knot_h is None: return
            seg, attr = knot_h['pos']
            # world space: the radius offset is a world-space view direction,
            # so a local-space center would scale/rotate with the object
            draw_proportional_edit_circle(context, self.M @ Vector(getattr(self.spline.cbs[seg], attr)))

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
