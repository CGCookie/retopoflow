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

import bpy
import bmesh
import heapq
import math
from mathutils import Vector, Quaternion, kdtree
from bpy.types import Context, Event, SpaceView3D
from bpy_extras.view3d_utils import location_3d_to_region_2d

from typing import ClassVar
from collections.abc import Callable

from ..rfglobals import RFGlobals
from ...addon_common.common.maths import sign_threshold
from ...addon_common.common.blender_cursors import Cursors
from ..common.accel import SourceCache
from ..common.bmesh import get_bmesh_emesh
from ..common.drawing import Drawing
from ..common.maths import proportional_edit
from ..common.snapping import source_snap_settings, source_snap_radius, SNAP_TO_ITEMS, build_snap_sources, build_island_bvh
from ..common.operator import RFOperator, RFOperator_Invoke, RFKeyMaps, execute_operator, Operator_Execute_Function, rf_is_running
from ..common.orientation import cycle_axis_constraint, reset_axis_constraint
from ..common.raycast import (
    raycast_point_valid_sources, nearest_point_valid_sources, iter_all_valid_sources,
    mouse_from_event, region_2d_to_location_3d_stable, ray_from_point
)
from ..common.curves import (
    QuadStripChainProvider, LoopStripChainProvider,
    relax_interior_verts, cumulative_lengths, walk_free_run, toggle_hovered_handle,
)
from ..rfoverlay_base import RFOverlay_Base
from ..rfoverlays.proportional_edit_overlay import draw_proportional_edit_circle
from ..rfoverlays.curve_overlay import (
    shrink_segment, snap_hidden_vector_arms, KNOT_RADIUS, TANGENT_RADIUS,
    CURVE_LINE_COLOR, CONTROL_POLYGON_COLOR, TANGENT_FILL_COLOR, TANGENT_BORDER_COLOR,
    KNOT_FILL_COLOR, KNOT_BORDER_COLOR, FREE_KNOT_FILL_COLOR, AUTO_KNOT_FILL_COLOR,
    DEBUG_SHOW_AUTO_HANDLES, create_curve_overlay_logic, _internal_bl_idname,
)


def create_curve_edit_logic(idname : str, label : str, description : str, *,
                            get_overlay : Callable[[], type[RFOverlay_Base] | None],
                            on_init : Callable[[Context, Event], None] | None = None
                            ) -> type:
    ''' Shared curve handle drag logic for any chain from create_curve_overlay(_logic). '''
    class RFOperator_Curve_Edit:
        # deliberately does NOT inherit RFOperator because __init_subclass__ auto-registers anything with a bl_idname,
        # so only the final class combination should trigger that, exactly once
        bl_idname = f'retopoflow.{idname}'
        bl_label = label
        bl_description = description
        bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

        rf_keymaps : RFKeyMaps = [
            (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS'}, None),
            (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS', 'alt': True}, None),
            (bl_idname, {'type': 'LEFTMOUSE', 'value': 'PRESS', 'alt': True, 'shift': True}, None),
        ]

        constraint_axis = None
        constraint_stage = 0
        constraint_plane = False
        constraint_dir_world = None
        constraint_plane_axes = ()  # ((axis_idx, dir_world), ...) for the plane mode guide draw
        constraint_label = ''
        constraint_persists = False

        @classmethod
        def can_start(cls, context):
            i = get_overlay().instance
            return False if not i else bool(getattr(i, 'hovering', False))

        def _gather_sources(self, context):
            return [
                (obj, obj.matrix_world, (mi := obj.matrix_world.inverted_safe()), mi.to_3x3())
                for obj in iter_all_valid_sources(context)
            ]

        def _place_knot(self, context, new_screen, pt_orig):
            ''' New local-space position for a dragged knot, or None to leave it put. '''
            new_world = raycast_point_valid_sources(context, new_screen, respect_clip_planes=True)
            return (self.Mi @ new_world) if new_world else None

        def _snap_deformed(self, context, pt_edit_new, pt_edit_orig):
            ''' Snap a curve-deformed vert to the target surface (local space). '''
            return nearest_point_valid_sources(
                context, self.M @ pt_edit_new,
                world=False, sources=self.sources, respect_clip_planes=True,
            ) or pt_edit_orig

        # ------------------------------------------------- axis constraints

        def _constrained_pos(self, context, new_screen, pt_orig):
            ''' Closest point to the mouse ray on the constraint line through the
            handle's pre-drag position (local space), or None when the axis runs
            straight into the view and there is no stable solution. '''
            ray_o, ray_d = ray_from_point(context, new_screen)
            if ray_o is None or ray_d is None:
                return None
            p1, d1 = self.M @ pt_orig, self.constraint_dir_world
            p2, d2 = ray_o.xyz, ray_d.xyz
            w0 = p1 - p2
            a, b, c = d1.dot(d1), d1.dot(d2), d2.dot(d2)
            denom = a * c - b * b
            if denom < 1e-9:
                return None
            t = (b * d2.dot(w0) - c * d1.dot(w0)) / denom
            return self.Mi @ (p1 + d1 * t)

        def _constrained_plane_pos(self, context, new_screen, pt_orig):
            ''' Mouse ray intersected with the constraint plane through the handle's
            pre-drag position (plane normal = the excluded axis), local space, or
            None when the ray runs parallel to the plane. '''
            ray_o, ray_d = ray_from_point(context, new_screen)
            if ray_o is None or ray_d is None:
                return None
            n = self.constraint_dir_world
            p0 = self.M @ pt_orig
            o, d = ray_o.xyz, ray_d.xyz
            dn = d.dot(n)
            if abs(dn) < 1e-9:
                return None
            t = (p0 - o).dot(n) / dn
            return self.Mi @ (o + d * t)

        def _constrained_tangent_pos(self, context, new_screen, pt_orig, h, orig):
            ''' New local-space position for a dragged tangent arm under an axis
            constraint -- a plane through the owner knot, never the line a knot
            gets (see below), or None when the view-plane move fails. '''
            rgn, r3d = context.region, context.region_data
            new_world = region_2d_to_location_3d_stable(rgn, r3d, new_screen, self.M @ pt_orig)
            if new_world is None:
                return None
            knot_h = self._knot_for_tangent(h)
            if knot_h is None:
                return self.Mi @ new_world
            knot_w = self.M @ orig(*knot_h['pos'])
            arm_w = (self.M @ pt_orig) - knot_w
            # a tangent arm's gesture is a rotation around its knot, so a line
            # constraint would deadlock it; this plane (through the arm and the
            # axis) swings freely while still driving the points along the axis
            n = arm_w.cross(self.constraint_dir_world)
            if n.length < 1e-9:
                # the arm already runs along the axis: every containing plane works,
                # so leave the move free and let the vert projection constrain
                return self.Mi @ new_world
            n.normalize()
            new_world = new_world - n * ((new_world - knot_w).dot(n))
            return self.Mi @ new_world

        def draw_constraint_axis(self, context):
            if self.constraint_dir_world is None:
                return
            rgn, r3d = context.region, context.region_data
            if not r3d:
                return
            h = self.handle # anchored at the knot
            anchor_h = h if h['kind'] == 'knot' else (self._knot_for_tangent(h) or h)
            seg0, attr0 = anchor_h['pos']
            anchor = self.M @ Vector(getattr(self.spline.cbs[seg0], attr0))
            p0 = location_3d_to_region_2d(rgn, r3d, anchor)
            if p0 is None:
                return
            # plane mode draws the plane's own two axes, like Blender's transform
            lines = self.constraint_plane_axes if self.constraint_plane else \
                    ((self.constraint_axis, self.constraint_dir_world),)
            ext = rgn.width + rgn.height
            ui = bpy.context.preferences.themes[0].user_interface
            for axis_idx, dir_world in lines:
                p1 = location_3d_to_region_2d(rgn, r3d, anchor + dir_world)
                if p1 is None:
                    continue
                d = p1 - p0
                if d.length < 1e-3:
                    continue  # this axis is parallel to the view
                d = d / d.length
                r, g, b = (ui.axis_x, ui.axis_y, ui.axis_z)[axis_idx]
                Drawing.draw2D_lines(context, [p0 - d * ext, p0 + d * ext], (r, g, b, 0.8), width=1)

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
            self.taper_scale = None
            self.taper_t = None
            self.horizon_factor = 0.0 # for automatic knots only
            self.horizon_segs = frozenset()
            if not self.constraint_persists:
                # constraints persist when used via menu modal, not via RF active tool
                reset_axis_constraint(type(self))

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
            self.sources = self._gather_sources(context)
            self.spline.tessellate_uniform()
            # Every vert below is parametrized by a nearest-point search over this tessellation.
            # With proportional editing on, "every vert" means every vert in the mesh, so index it only once.
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


            # segments this drag reshapes.
            nseg = len(self.spline.cbs)
            if self.handle['kind'] == 'knot':
                self.touched_segs = { seg for seg, _ in self.handle['set'] }
                # a knot drag also live-recomputes adjacent Automatic/Vector knots'
                # arms, reshaping the segments past them. Over-inclusion is harmless
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
                # Alt-dragging a tangent scales/rotates its knot instead,
                # which can reshape the segment on the knot's other side.
                # Cover it in case Alt is toggled mid-drag.
                knot_h = self._knot_for_tangent(self.handle)
                if knot_h:
                    self.touched_segs |= { seg for seg, _ in knot_h['move'] }

            # a free knot isn't a vertex, so nothing should bunch up on it as it moves:
            # combined_segs spans the whole run between the nearest true knots,
            # and each vert keeps its proportional position within that span
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
                backward = walk_free_run(seg_before, -1, nseg, cyclic, free_at_seg_p0, visited)
                forward = walk_free_run(seg_after, 1, nseg, cyclic, free_at_seg_p0, visited)
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
            combined_cumul = cumulative_lengths(self.spline.cbs, self.combined_segs) if self.combined_segs else None
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
                    # a cap rung sits past the centerline's endpoint (face-center to
                    # face-center); extrapolate along the endpoint tangent to it, then
                    # re-evaluate that offset against the live spline every frame
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
                    # weighted by original edge length -- see relax_interior_verts
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
            # 'cos' baseline to the current points for the next rebuild to reuse
            # verbatim -- a refit here would lose handle-type/straight-line intent
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
                if self.constraint_dir_world is not None:
                    # a constraint wins over surface and feature snapping: the knot
                    # slides along the constraint line, or within the plane
                    if self.constraint_plane:
                        new_edit = self._constrained_plane_pos(context, new_screen, pt_orig)
                    else:
                        new_edit = self._constrained_pos(context, new_screen, pt_orig)
                else:
                    # knots snap to the source surface and carry their tangent arms along
                    new_edit = self._place_knot(context, new_screen, pt_orig)
                if new_edit is None:
                    return
                # A coupled edge chain's control point is a mesh vert, so snap the control point too.
                # Control points on a face loop are never verts, so don't snap those.
                if self.chain.get('coupled', True) and self.constraint_dir_world is None:
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
                if self.constraint_dir_world is not None:
                    # never a line for a tangent arm -- it must stay able to swing;
                    # the points themselves are constrained in _deform_verts
                    if self.constraint_plane:
                        new_edit = self._constrained_plane_pos(context, new_screen, pt_orig)
                    else:
                        new_edit = self._constrained_tangent_pos(context, new_screen, pt_orig, h, orig)
                    if new_edit is None:
                        return
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
                # a direct tangent drag pins an AUTOMATIC owner to 'aligned' so a
                # later knot drag doesn't overwrite it; a VECTOR owner keeps its
                # type since the next drag re-snapshots from this edit anyway
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
            ''' Live handle update while an Automatic knot is dragged: blends its
            arms and each neighbor's facing arm toward Blender's point-at handles
            as the knot nears the straight line between its two neighbors. '''
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
                ''' Blender-handle direction for knot i's `attr` arm (auto: own
                tangent-sum unit(b-a)+unit(c-b); vector/endpoint: aim at the
                faced neighbor), read via `pos_fn` (cur = live, snap = grab-time). '''
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
                ''' Reference proportional to Blender's own handle LENGTH for knot
                i's `attr` arm -- only the ratio between two calls is ever used,
                so Blender's own constant factor (/3 Vector, /2.5614 Auto) cancels. '''
                kh = knot_at(i)
                if kh is None:
                    return None
                b = pos_fn(kh['pos'])
                pk, nk = knot_at(i - 1), knot_at(i + 1)
                m = nk if attr == 'p1' else pk
                if m is None:
                    return None
                # vector/endpoint: Blender's Vector handle is exactly this distance / 3
                len_x = (pos_fn(m['pos']) - b).length
                if kh.get('handle_type') == 'automatic' and pk is not None and nk is not None:
                    va, vc = b - pos_fn(pk['pos']), pos_fn(nk['pos']) - b
                    if va.length < 1e-9 or vc.length < 1e-9:
                        return None
                    t_len = (va.normalized() + vc.normalized()).length
                    if t_len < 1e-9:
                        return None
                    # auto: Blender also divides by the tangent-sum magnitude, so the
                    # handle scales with the knot's angle to its neighbors, not just distance
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
                # a face strip's handles describe its spine, so scaling them would
                # bend it as a side effect; hold the curve at its snapshot and taper
                # the verts' width against it instead (see taper_scale in _deform_verts)
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
            ''' 1.0 at the Alt-scaled knot's own parameter, falling off linearly
            to 0.0 by the adjacent knots (one segment of `t` either side); wraps
            for a cyclic chain. A localized taper, not a uniform width change. '''
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
            relax_interior_verts(bm, interior, iterations)
            for idx in interior['indices']:
                bmv = bm.verts[idx]
                # constrained displacements stay axis-pure through the relax (it's a
                # linear combination of axis-pure boundary displacements), so only
                # snap when unconstrained -- snapping would pull them off-axis
                co = bmv.co if self.constraint_dir_world is not None else self._snap_deformed(context, bmv.co, bmv.co)
                bmv.co = self._mirror_clamp(context, co, interior['orig_co'][idx], self.M, self.Mi)

        def update(self, context, event):
            INTERIOR_RELAX_ITERATIONS = 10 # per frame
            INTERIOR_RELAX_FINAL_ITERATIONS = 40 # on release

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

            if event.value == 'PRESS' and event.type in {'X', 'Y', 'Z'} and not (event.ctrl or event.alt or event.oskey):
                # Shift+axis = plane constraint, like Blender's transform
                cycle_axis_constraint(type(self), context, event.type, plane=event.shift)
                # fall through: apply_handle below repositions against the new
                # constraint using this event's mouse position

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
            combined_cumul = cumulative_lengths(spline.cbs, self.combined_segs) if self.combined_segs else None

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
                # rotate the stored offset by how much this point's tangent has
                # turned since init: rigid, so it can't shear and undoes itself
                # as the curve straightens back out
                R_prev = rot_state[bmv_idx]
                # composed from small per-frame deltas, not a one-shot shortest-arc
                # from z0, which would pick the wrong way past a 180-degree turn
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
                # Curve-normal correction, rung verts only: as the edit grows,
                # nudge a well-fit cross-section fully into the curve's normal
                # plane so carried-along fit skew can't kink the faces.
                d_len = d.length
                if d_len > 1e-9 and is_rung:
                    # non-rung d0 is fit residual, not a width -- rescaling it to
                    # full length would fling the vert in an arbitrary direction
                    # feel knob: tangent swing for full-strength correction (ramps in below)
                    CURVE_NORMAL_EDIT_ANGLE = math.radians(90)
                    edit_w = min(z0.angle(z1, 0.0) / CURVE_NORMAL_EDIT_ANGLE, 1.0)
                    # max(), not fit_w*edit_w alone: horizon_boost bypasses fit_w
                    # entirely, so a perfectly straight line yields a flat strip
                    blend = max(fit_w * edit_w, horizon_boost)
                    if blend > 0.0:
                        d_perp = d_final - d_final.dot(z1) * z1
                        if d_perp.length > 1e-9:
                            d_normal = d_perp * (d_len / d_perp.length)
                            d_final = d_final.lerp(d_normal, blend)
                computed[bmv_idx] = [o, d_final, horizon_boost, factor, pt_edit_orig]
                rung_groups.setdefault(t, []).append(bmv_idx)

            # Pass 2: the correction rescales each vert independently, so an
            # asymmetric rung can skew off its anchor `o`; pull the rung's
            # average offset back to zero, ramped by the same horizon_boost.
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
            axis = self.constraint_dir_world
            for bmv_idx, (o, d_final, horizon_boost, factor, pt_edit_orig) in computed.items():
                bmv = bm.verts[bmv_idx]
                # blend in local space; the surface query inside _snap_deformed wants world input
                pt_edit_new = pt_edit_orig + ((o + d_final) - pt_edit_orig) * factor
                if axis is not None:
                    # the constraint proper: each POINT moves only along the axis
                    # (or within the plane perpendicular to it), whatever the
                    # handles did; snapping would pull it back off-constraint
                    orig_w = M @ pt_edit_orig
                    disp = (M @ pt_edit_new) - orig_w
                    along = axis * disp.dot(axis)
                    co = Mi @ (orig_w + ((disp - along) if self.constraint_plane else along))
                else:
                    co = self._snap_deformed(context, pt_edit_new, pt_edit_orig)
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
            self.draw_constraint_axis(context)
            self.draw_curve(context)
            if not context.tool_settings.use_proportional_edit: return
            h = self.handle
            knot_h = h if h['kind'] == 'knot' else self._knot_for_tangent(h)
            if knot_h is None: return
            seg, attr = knot_h['pos']
            # world space: the radius offset is a world-space view direction,
            # so a local-space center would scale/rotate with the object
            draw_proportional_edit_circle(context, self.M @ Vector(getattr(self.spline.cbs[seg], attr)))

    return RFOperator_Curve_Edit


def create_curve_edit_operator(
    opname : str,
    idname : str,
    label : str,
    description : str,
    *,
    get_overlay : Callable[[], type[RFOverlay_Base] | None],
    on_init : Callable[[Context, Event], None] | None = None,
) -> type[RFOperator]:
    logic = create_curve_edit_logic(
        idname, label, description,
        get_overlay=get_overlay, on_init=on_init,
    )
    return type(opname, (logic, RFOperator), {})


def create_curve_toggle_handle_type_operator(
    idname : str,
    label : str,
    description : str,
    *,
    get_overlay : Callable[[], type[RFOverlay_Base] | None],
) -> Operator_Execute_Function:
    ''' Registers the V-key operator that cycles the hovered knot's handle type
    (Aligned -> Vector -> Automatic -> Aligned); see toggle_hovered_handle in
    common/curves.py for what each cycle step does on each chain kind. '''

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

    def toggle(context):
        overlay_type = get_overlay()
        return toggle_hovered_handle(context, overlay_type.instance if overlay_type else None)

    bl_idname = f'retopoflow.{idname}'
    return execute_operator(
        idname, label, description=description, options={'INTERNAL', 'UNDO'},
        fn_poll=can_toggle,
        keymaps=[(bl_idname, {'type': 'V', 'value': 'PRESS'}, None)],
    )(toggle)


# =============================================================================
# Edit as Curve: standalone modal, usable outside RF mode.
# =============================================================================

# (icons, label) rows for the status bar, rendered like SharedStatusbarKeymap._draw_icons.
# The active constraint is named in the viewport header instead of highlighted here.
EDIT_AS_CURVE_STATUS_KEYMAP = (
    (('MOUSE_LMB_DRAG',), 'Edit Curve'),
    (('EVENT_ALT', 'MOUSE_LMB_DRAG'), 'Scale Control Point'),
    (('EVENT_ALT', 'EVENT_SHIFT', 'MOUSE_LMB_DRAG'), 'Rotate Control Point'),
    (('EVENT_X', 'EVENT_Y', 'EVENT_Z'), 'Axis'),
    (('EVENT_SHIFT', 'EVENT_X', 'EVENT_Y', 'EVENT_Z'), 'Plane'),
    (('EVENT_V',), 'Toggle Handle Type'),
    (('EVENT_CTRL', 'EVENT_Z'), 'Undo'),
    (('EVENT_RETURN',), 'Confirm'),
    (('EVENT_ESC',), 'Cancel'),
)

# icons that render wider than a single-key icon (at least on macOS), so the
# following label needs breathing room
EDIT_AS_CURVE_STATUS_ICON_EXTRA_SPACE = { 'EVENT_ESC': 1.0 }

def draw_edit_as_curve_statusbar(header, context):
    layout = header.layout
    for icons, label in EDIT_AS_CURVE_STATUS_KEYMAP:
        row = layout.row(align=True)
        for icon in icons:
            row.label(text='', icon=icon)
            if (extra := EDIT_AS_CURVE_STATUS_ICON_EXTRA_SPACE.get(icon)):
                row.separator(factor=extra)
        row.label(text=label)
        layout.separator()


# ---------------------------------------------------------------- overlay

EditAsCurveOverlayLogic = create_curve_overlay_logic(
    'retopoflow.edit_as_curve', 'edit_as_curve_overlay', 'Edit as Curve',
    # same provider list and order as the RF tools: faces win, so a selection
    # containing quad strips shows only strip curves; loop curves appear only
    # when the selection is edges-only
    [QuadStripChainProvider(), LoopStripChainProvider(only_boundary=True)],
)

class EditAsCurve_Overlay(EditAsCurveOverlayLogic):
    ''' Selection-driven curve handles, hosted by the Edit as Curve modal instead
    of RFCore. A plain object owned by the host operator, never registered. '''

    # the host must not pause rebuilds; the drag op deliberately DOES (it draws
    # the live curve itself while update_data self-suppresses the idle overlay)
    ignore_modal_bl_idnames : ClassVar[set[str]] = { _internal_bl_idname('retopoflow.edit_as_curve') }

    def _curve_handles_enabled(self, context : Context) -> bool:
        # no workspace-tool prop to consult outside RF: handles are the whole point
        return True

    def _own_tool_modal_running(self, context : Context) -> bool:
        # the RF gate hides the control points while the owning tool's own insert
        # modal is up; standalone, the always-running host modal IS the "own tool"
        # operator, so that gate would hide the handles for the whole session
        return False

    def _dirty_version(self) -> int | None:
        # class-level reads only: the host instance's attributes are unreadable
        # once its operator RNA dies, and this can outlive an aborted host
        host_cls = RFOperator_EditAsCurve
        return host_cls.version if host_cls._is_running else None


# ----------------------------------------------------------------- drag op

class EditAsCurveDragBase(RFOperator_Invoke):
    ''' Bridges the curve-edit mixin's RFOperator-style lifecycle (init/update/
    finish/draw_postpixel) onto RFOperator_Invoke's plain invoke/modal/cancel.
    No bl_idname, so this base itself never registers. '''

    _draw_handle = None

    def invoke(self, context, event):
        host = RFOperator_EditAsCurve.active
        if host is None or not type(self).can_start(context):
            return {'CANCELLED'}
        try:
            self.init(context, event)
        except Exception as e:
            print(f'{type(self).__name__}: caught Exception in init: {e}')
            self.finish(context)  # exception-safe; unpauses the overlay
            return {'CANCELLED'}
        host.record_drag_originals(self)
        self._draw_handle = SpaceView3D.draw_handler_add(
            self.draw_postpixel, (context,), 'WINDOW', 'POST_PIXEL'
        )
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if context.mode != 'EDIT_MESH':
            self._teardown(context)
            return {'CANCELLED'}
        ret = self.update(context, event)
        if ret & {'FINISHED', 'CANCELLED'}:
            host = RFOperator_EditAsCurve.active
            if host is not None:
                if 'FINISHED' in ret:
                    # before _teardown: the commit diffs against the live bmesh
                    host.commit_drag_undo(self)
                else:
                    host.discard_drag_undo()  # the drag restored itself already
            self._teardown(context)
        return ret

    def cancel(self, context):
        ''' Blender-forced end (the area closes, etc.). '''
        host = RFOperator_EditAsCurve.active
        if host is not None:
            host.discard_drag_undo()
        self._teardown(context)

    def _teardown(self, context):
        if self._draw_handle:
            SpaceView3D.draw_handler_remove(self._draw_handle, 'WINDOW')
            self._draw_handle = None
        self.finish(context)  # cache sync + unpause_update; already exception-safe


EditAsCurveDragLogic = create_curve_edit_logic(
    'edit_as_curve_drag', 'Edit Curve Handle',
    'Drag a curve control handle to reshape the selection',
    get_overlay=lambda: EditAsCurve_Overlay,
)

class RFOperator_EditAsCurve_Drag(EditAsCurveDragLogic, EditAsCurveDragBase):
    # the mixin declares REGISTER/UNDO for its RF composition; here the whole
    # session commits as ONE undo step when the host finishes, so no per-drag undo
    bl_options = { 'INTERNAL' }

    # the X/Y/Z axis constraint belongs to the SESSION: the host resets it at
    # invoke, toggles it while idle, and every drag picks it up as-is
    constraint_persists = True

    def init(self, context, event):
        super().init(context, event)
        host = RFOperator_EditAsCurve.active
        if host and host.snap_to == 'NONE':
            # NONE skips snapping entirely, source features included -- the mixin
            # seeds feature_radius from SourceCache, which can persist from an
            # earlier RF-mode run; zero disables snap_co_to_feature completely
            self.feature_radius = 0.0

    def _gather_sources(self, context):
        host = RFOperator_EditAsCurve.active
        return host.snap_sources if host else []

    def _place_knot(self, context, new_screen, pt_orig):
        host = RFOperator_EditAsCurve.active
        if host is None:
            return None
        if host.snap_sources:
            w = raycast_point_valid_sources(
                context, new_screen,
                sources=host.snap_sources, respect_clip_planes=True,
            )
            if w:
                return self.Mi @ w
            return None  # snapping requested but the cursor is off the surface
        # no snap surface: move in the view plane at the knot's original depth
        # (the same primitive tangent arms use), clamped to the island BVH when
        # snapping to the original mesh shape
        w = region_2d_to_location_3d_stable(
            context.region, context.region_data, new_screen, self.M @ pt_orig,
        )
        if w is None:
            return None
        if host.snap_bvh:
            hit, _, _, _ = host.snap_bvh.find_nearest(w)
            if hit:
                w = Vector(hit)
        return self.Mi @ w

    def _snap_deformed(self, context, pt_edit_new, pt_edit_orig):
        host = RFOperator_EditAsCurve.active
        if host is None:
            return pt_edit_new
        if host.snap_sources:
            return super()._snap_deformed(context, pt_edit_new, pt_edit_orig)
        if host.snap_bvh:
            hit, _, _, _ = host.snap_bvh.find_nearest(self.M @ pt_edit_new)
            return (self.Mi @ Vector(hit)) if hit else pt_edit_new
        return pt_edit_new  # snap_to NONE: pure curve deform


# -------------------------------------------------------------------- host

# Module functions over class-level state, not bound methods: a dead
# operator's bound method raises ReferenceError on any attribute access and
# can never unregister itself, so a leaked registration would spam forever.

def edit_as_curve_on_depsgraph_update(scene, depsgraph):
    if not RFOperator_EditAsCurve._is_running:
        return
    # hover raycasts fire phantom depsgraph events with empty updates every
    # mouse move, so gate the version bump on updates actually existing
    if not depsgraph.updates:
        return
    RFOperator_EditAsCurve.version += 1

def edit_as_curve_draw_overlay_handler():
    if not RFOperator_EditAsCurve._is_running:
        return
    overlay = EditAsCurve_Overlay.instance
    if overlay is None:
        return
    # runs for every 3D region and projects with that region's own matrices,
    # same as the RF-mode overlay's draw handler; draw_overlay bails on its
    # own when the drawing region has no region_data
    overlay.draw_overlay(bpy.context)


class RFOperator_EditAsCurve(RFOperator_Invoke):
    bl_idname = 'retopoflow.edit_as_curve'
    bl_label = 'Edit as Curve (Retopoflow)'
    bl_description = 'Edit the selected edge loops and quad strips with Bezier curve handles until Enter confirms'
    bl_space_type = 'VIEW_3d'
    bl_region_type = 'TOOLS'
    bl_options = { 'REGISTER', 'UNDO' }

    active : ClassVar[RFOperator_EditAsCurve | None] = None
    _is_running : ClassVar[bool] = False
    # class-level so the module-level depsgraph handler and the overlay's
    # _dirty_version never have to touch the operator instance
    version : ClassVar[int] = 0
    _draw_handle : ClassVar[object | None] = None

    # Only used while RF is not running (poll blocks the operator inside RF,
    # where the tools already provide live curve handles with RF's own sources).
    snap_to: bpy.props.EnumProperty(
        name='Snap To',
        description='Surface to keep the curve-deformed vertices on',
        items=SNAP_TO_ITEMS,
        # NONE = pure curve deform, no surface or feature snapping at all; the
        # other choices remain for scripting (ORIGINAL_MESH clamps edits back
        # onto the pre-drag surface, which reads as "stuck", so never default it)
        default='NONE',
    )
    snap_object: bpy.props.StringProperty(
        name='Object',
        description='Name of the object to snap vertices to',
        default='',
    )
    snap_collection: bpy.props.StringProperty(
        name='Collection',
        description='Name of the collection to snap vertices to',
        default='',
    )

    @classmethod
    def register(cls):
        # sweep out any handler an earlier load of this module left behind --
        # see the note above edit_as_curve_on_depsgraph_update for why those can't self-remove
        handlers = bpy.app.handlers.depsgraph_update_post
        for h in list(handlers):
            fn = getattr(h, '__func__', h)  # method attrs are safe; only the op's own attrs are RNA-routed
            if getattr(fn, '__module__', None) == __name__ and h is not edit_as_curve_on_depsgraph_update:
                handlers.remove(h)

    @classmethod
    def unregister(cls):
        # disabling the addon mid-session must not leave the live handler behind
        handlers = bpy.app.handlers.depsgraph_update_post
        if edit_as_curve_on_depsgraph_update in handlers:
            handlers.remove(edit_as_curve_on_depsgraph_update)
        if cls._draw_handle:
            SpaceView3D.draw_handler_remove(cls._draw_handle, 'WINDOW')
            cls._draw_handle = None
        cls._is_running = False
        cls.active = None

    @classmethod
    def poll(cls, context):
        if not super().poll(context): return False
        if rf_is_running(): return False   # RF tools already provide curve handles
        if cls._is_running: return False
        # hover/drag math is screen-space, so this only means anything in a 3D view.
        # space_data rather than region_data: menus draw in their own region, which has none.
        if not context.space_data or context.space_data.type != 'VIEW_3D': return False
        if not context.edit_object.data.total_vert_sel: return False
        return True

    def invoke(self, context, event):
        if not context.region_data:
            self.report({'ERROR'}, 'Edit as Curve: needs a 3D viewport')
            return {'CANCELLED'}

        # discrete pre-session baseline: the Esc topology-escalation path (below)
        # undoes back to exactly this step
        bpy.ops.ed.undo_push(message='Edit as Curve')

        self.snap_sources = build_snap_sources(
            context, self.snap_to,
            snap_object=self.snap_object, snap_collection=self.snap_collection,
        )
        self.snap_bvh = None
        type(self).version = 1
        self._bvh_keys = None
        self._orig_cos = {}
        self._undo_stack = []
        self._pending_undo = None
        self._topology_dirty = False
        self._ops_len = len(context.window_manager.operators)
        self._hand_cursor = False

        type(self).active = self
        type(self)._is_running = True

        # RFOverlay_Base.__init__ sets cls.instance; the chains build lazily on the
        # first hover/draw (both call update_data), so nothing here can half-fail
        self.overlay = EditAsCurve_Overlay()
        type(self.overlay).paused_update = False
        type(self.overlay).paused_overlay = False

        if edit_as_curve_on_depsgraph_update not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(edit_as_curve_on_depsgraph_update)
        type(self)._draw_handle = SpaceView3D.draw_handler_add(
            edit_as_curve_draw_overlay_handler, (), 'WINDOW', 'POST_PIXEL'
        )
        reset_axis_constraint(RFOperator_EditAsCurve_Drag)  # constraints are per session
        self._area = context.area
        self._shown_label = None
        if context.workspace:
            context.workspace.status_text_set(draw_edit_as_curve_statusbar)
        self._refresh_feedback(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _refresh_feedback(self, context):
        ''' Show the active constraint in the viewport header. '''
        # a modal event can arrive from a different area (mouse over a side
        # panel), so target the STORED invoking 3D view, never context.area
        label = RFOperator_EditAsCurve_Drag.constraint_label
        self._shown_label = label
        area = self._area
        if area:
            try:
                area.header_text_set('Edit as Curve' + (f'   |   along {label}' if label else ''))
                area.tag_redraw()
            except ReferenceError:
                self._area = None

    # ----------------------------------------------------------------- modal

    def _hover(self, context, event):
        ''' Recompute hover fresh from this event's mouse position. '''
        # safe even right after a selection change: hovered_handle runs
        # update_data itself, so stale chain indices can't leak through
        self.overlay.hovering = self.overlay.hovered_handle(context, mouse_from_event(event))
        return self.overlay.hovering

    def _refresh_snap_bvh(self, context):
        ''' Rebuild the ORIGINAL_MESH island BVH when the selection changed. '''
        if self.snap_to != 'ORIGINAL_MESH':
            return
        # keyed on the chains' cache keys, not the version counter: a drag's
        # own mesh edits bump the version every frame, but the BVH must stay
        # on the ORIGINAL shape for as long as the same loops are being edited
        keys = frozenset(chain['cache_key'] for chain in self.overlay.chains)
        if keys == self._bvh_keys:
            return
        self._bvh_keys = keys
        bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)
        seed = { bmv for bmv in bm.verts if bmv.select }
        self.snap_bvh = build_island_bvh(context.edit_object.matrix_world, seed) if seed else None

    def modal(self, context, event):
        if context.mode != 'EDIT_MESH':
            # can happen when something drops back to OBJECT mode; the bmesh is gone with it
            self.release(context)
            return {'CANCELLED'}

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            self.release(context)
            return {'FINISHED'}  # the UNDO flag pushes the single session undo step

        if event.type == 'ESC' and event.value == 'PRESS':
            topology_dirty = self._topology_dirty
            if not topology_dirty:
                self._restore_original_cos(context)
            # release first: the undo below rebuilds the mesh, so no handler or
            # overlay may still be looking at it when that happens
            self.release(context)
            if topology_dirty:
                self._revert_by_undo(context)
            return {'CANCELLED'}

        if event.type == 'Z' and (event.ctrl or event.oskey):
            # system undo/redo mid-session would desync the revert ledger and the
            # baseline, so it stays blocked; plain Ctrl/Cmd+Z instead pops the
            # session's own stack of individual handle edits
            if event.value == 'PRESS' and not event.shift:
                self._undo_last(context)
            return {'RUNNING_MODAL'}

        if event.type in {'X', 'Y', 'Z'} and event.value == 'PRESS' \
                and not (event.ctrl or event.alt or event.oskey):
            # session-persistent constraint, toggleable before any drag; Shift+axis
            # is the plane variant. Shadows delete/split/shading (and their Shift
            # forms) for the session, same as Blender's own transform modals.
            cycle_axis_constraint(RFOperator_EditAsCurve_Drag, context, event.type, plane=event.shift)
            self._refresh_feedback(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self._hover(context, event):
                self._refresh_snap_bvh(context)
                bpy.ops.retopoflow.edit_as_curve_drag('INVOKE_DEFAULT')
                # press consumed: never doubles as a selection click; the drag op
                # is stacked above this modal and takes every event until release
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type == 'V' and event.value == 'PRESS':
            if self._hover(context, event):
                ret = toggle_hovered_handle(context, self.overlay)
                if 'FINISHED' in ret:
                    self._topology_dirty = True  # a real corner was inserted/removed
                    self._undo_stack.clear()     # its vert indices died with it
                # consume V even when nothing toggled, so Rip can't fire on a handle
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE':
            if RFOperator_EditAsCurve_Drag.constraint_label != self._shown_label:
                # a mid-drag X/Y/Z toggle happened inside the drag operator, where
                # this modal never saw the keypress; catch up on the next move
                self._refresh_feedback(context)
            was_hovering = bool(self.overlay.hovering)
            hovering = bool(self._hover(context, event))
            if hovering != was_hovering:
                if hovering:
                    Cursors.set('hand')
                else:
                    Cursors.restore()
                self._hand_cursor = hovering
                if context.area:
                    context.area.tag_redraw()
            return {'PASS_THROUGH'}

        # click/box/lasso/loop select, grow/shrink, navigation, ... all work; a
        # selection change fires the depsgraph handler, bumping version, and the
        # next update_data re-collects the providers over the new selection
        return {'PASS_THROUGH'}

    # ------------------------------------------------------- session revert

    UNDO_STACK_MAX = 100

    @staticmethod
    def _spline_points(spline):
        return [
            (Vector(cb.p0), Vector(cb.p1), Vector(cb.p2), Vector(cb.p3))
            for cb in spline.cbs
        ] if spline is not None else None

    def _snapshot_struct(self, cache_key):
        ''' Field-wise snapshot of the chain's cached curve baseline, or None. '''
        cached = self.overlay._curve_struct_cache.get(cache_key)
        if cached is None:
            return None
        # the entry holds the LIVE spline, which drags mutate in place and whose
        # tessellation KDTree can't deepcopy -- keep the object by reference and
        # snapshot its control-point VALUES instead, to write back on undo
        spline = cached.get('spline')
        return {
            'knots': list(cached['knots']),
            'corner_set': set(cached['corner_set']),
            'tunables': cached.get('tunables'),
            'handle_tunables': cached.get('handle_tunables'),
            'cos': [Vector(co) for co in cached['cos']],
            'spline': spline,
            'spline_points': self._spline_points(spline),
            'handles': cached.get('handles'),  # regenerates on the forced rebuild
        }

    def record_drag_originals(self, drag):
        ''' Called by the drag operator at drag start: stages this drag's
        pre-state for the Esc full revert and the session undo stack. '''
        pre = {}
        for idx, tup in drag.grab['data'].items():
            co = Vector(tup[2])  # tup[2] = pre-drag co
            self._orig_cos.setdefault(idx, co.copy())  # first writer wins, across any number of drags
            pre[idx] = co
        if drag.interior:
            for idx, co in drag.interior['orig_co'].items():
                v = Vector(co)
                self._orig_cos.setdefault(idx, v.copy())
                pre[idx] = v
        # a drag can also re-aim arms or pin an Automatic knot to Aligned, so the
        # undo entry needs the chain's curve structure and overrides too, not just cos
        cache_key = drag.chain['cache_key']
        self._pending_undo = {
            'cache_key': cache_key,
            'pre_cos': pre,
            'struct': self._snapshot_struct(cache_key),
            'overrides': dict(o) if (o := self.overlay._handle_type_overrides.get(cache_key)) else None,
        }

    def commit_drag_undo(self, drag):
        ''' The drag finished: keep only what it actually changed, or nothing. '''
        pending, self._pending_undo = self._pending_undo, None
        if pending is None or self.overlay is None:
            return
        bm = drag.bm
        if bm is None or not bm.is_valid:
            return
        nverts = len(bm.verts)
        pending['pre_cos'] = {
            idx: co for idx, co in pending['pre_cos'].items()
            if idx < nverts and (bm.verts[idx].co - co).length_squared > 1e-18
        }
        key = pending['cache_key']
        struct = pending['struct']
        # the recorded spline object is the live one drags mutate in place, so
        # comparing its current points against the snapshot detects curve changes
        struct_changed = struct is not None and self._spline_points(struct['spline']) != struct['spline_points']
        overrides_changed = (self.overlay._handle_type_overrides.get(key) or {}) != (pending['overrides'] or {})
        if not pending['pre_cos'] and not struct_changed and not overrides_changed:
            return  # a click without movement: nothing to undo
        self._undo_stack.append(pending)
        del self._undo_stack[:-self.UNDO_STACK_MAX]

    def discard_drag_undo(self):
        self._pending_undo = None

    def _undo_last(self, context):
        ''' Pop one handle edit off the session's own undo stack: restore the
        verts it moved and the chain's cached curve baseline, then rebuild. '''
        if not self._undo_stack:
            return
        entry = self._undo_stack.pop()
        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        nverts = len(bm.verts)
        for idx, co in entry['pre_cos'].items():
            if idx < nverts:
                bm.verts[idx].co = co
        overlay = self.overlay
        key = entry['cache_key']
        struct = entry['struct']
        if struct is None:
            overlay._curve_struct_cache.pop(key, None)
        else:
            spline, points = struct.pop('spline'), struct.pop('spline_points')
            if spline is not None and points is not None:
                for cb, (p0, p1, p2, p3) in zip(spline.cbs, points):
                    cb.p0, cb.p1, cb.p2, cb.p3 = p0, p1, p2, p3
            struct['spline'] = spline
            overlay._curve_struct_cache[key] = struct
        if entry['overrides'] is None:
            overlay._handle_type_overrides.pop(key, None)
        else:
            overlay._handle_type_overrides[key] = entry['overrides']
        bmesh.update_edit_mesh(em)
        overlay.hovering = None
        type(overlay).depsgraph_version = -42  # rebuild from the restored baseline
        if context.area:
            context.area.tag_redraw()

    def _restore_original_cos(self, context):
        ''' Index-based restore; only valid while the session made no topology edits. '''
        if not self._orig_cos:
            return
        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        nverts = len(bm.verts)
        for idx, co in self._orig_cos.items():
            if idx < nverts:
                bm.verts[idx].co = co
        bmesh.update_edit_mesh(em)

    def _revert_by_undo(self, context):
        ''' Step the undo stack back to the invoke-time baseline. Used when a
        corner insert/remove killed vert indices, so the cos ledger can't revert. '''
        self.unguard_modal()  # idempotent; drop the guards before the mesh rebuild
        # also step past any undo steps that passed-through native ops pushed
        wm_ops = context.window_manager.operators
        external_pushes = sum(
            1 for op in wm_ops[self._ops_len:]
            if 'UNDO' in (getattr(op, 'bl_options', None) or set())
        )
        for _ in range(1 + external_pushes):
            bpy.ops.ed.undo()

    # --------------------------------------------------------------- teardown

    def release(self, context):
        cls = type(self)
        cls._is_running = False
        cls.active = None
        if cls._draw_handle:
            SpaceView3D.draw_handler_remove(cls._draw_handle, 'WINDOW')
            cls._draw_handle = None
        if edit_as_curve_on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(edit_as_curve_on_depsgraph_update)
        if context.workspace:
            context.workspace.status_text_set(None)
        area = getattr(self, '_area', None) or context.area
        if area:
            try:
                area.header_text_set(None)
                area.tag_redraw()
            except ReferenceError:
                pass
        self._area = None
        if self._hand_cursor:
            Cursors.restore()
            self._hand_cursor = False
        if self.overlay:
            type(self.overlay).instance = None
            self.overlay = None
        self._orig_cos = {}
        self.snap_bvh = None
        self.snap_sources = []

    def cancel(self, context):
        ''' Blender calls this when it ends the modal operator itself (ex: the window closes). '''
        self.release(context)
