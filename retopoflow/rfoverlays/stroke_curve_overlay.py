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
import math
from mathutils import Vector, Matrix
from bpy.types import Context, Event
from bpy_extras.view3d_utils import location_3d_to_region_2d

from typing import ClassVar
from collections.abc import Sequence

from ..rfoverlay_base import RFOverlay_Base
from .overlays import overlay_names

from ..rfglobals import RFGlobals
from ..common.bpy_helper import bpy_ops_retopoflow
from ..common.operator import RFOperator
from ..common.bmesh import (
    get_bmesh_emesh,
    bme_length,
    get_boundary_strips_cycles,
    bme_unshared_bmv,
    bmes_shared_bmv,
)
from ..common.bmesh_maths import get_strip_bmvs, rdp_corner_indices
from ..common.maths import map_range, clamp
from ..common.drawing import Drawing
from ..common.raycast import is_point_hidden, mouse_from_event
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bezier import CubicBezier, CubicBezierSpline
from ...addon_common.common.blender_cursors import Cursors


# how far a single cubic segment may span before an auto-knot is inserted, as
# a fraction of the whole chain's own total length (NOT vert count -- a vert
# count would make subdividing, which changes nothing about the curve's
# actual shape, insert more knots just because there are more verts to count).
# Kept deliberately >1 (effectively a no-op: no sub-span can ever exceed the
# whole chain's own length) -- bend-tolerance-driven RDP already places a
# knot at every meaningfully curving point, proportional to the chain's own
# scale, so knot count should come from that (and the user's density setting)
# alone. Lower this only if a very long, gentle, single-piece run still needs
# a backstop knot for some other reason (e.g. very stiff proportional-edit
# falloff over a long span).
AUTO_KNOT_MAX_SPAN_FACTOR = 1.5
# corner tolerance (BEND_TOLERANCE_FACTOR) and min corner spacing, as fractions
# of the chain's own total length -- same reasoning: avg edge length shrinks
# under subdivision, which would make RDP more sensitive to the exact same
# geometry. BEND_TOLERANCE_FACTOR itself is user-tunable (Strokes' "Density"
# property, curve_handle_density) rather than fixed -- see
# _bend_tolerance_factor for the density -> tolerance mapping, bounded by
# these two endpoints (min density -> loosest/fewest handles, max density ->
# tightest/most handles).
CORNER_MIN_SPACING_FACTOR = 0.01
# on-screen radii (pre Drawing.scale) of the knot/tangent handle dots, also used
# to shorten the control-polygon arm lines so they stop at each dot's edge
# instead of running into its (partially transparent) center
KNOT_RADIUS = 14
TANGENT_RADIUS = 12
# border tint for a knot whose position is NOT coupled to any vertex (see
# _build_handles) -- everything else uses the default black-ish border
FREE_KNOT_BORDER_COLOR = (1.0, 0.65, 0.0, 0.9)
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
SEGMENT_KEEP_FIT_TOLERANCE = 0.15


def density_to_bend_tolerance(density : float) -> float:
    '''
    Maps Strokes' curve_handle_density property (0.1 to 1.0) to
    BEND_TOLERANCE_FACTOR, geometrically (not linearly) interpolated between
    BEND_TOLERANCE_FACTOR_MIN and _MAX: tolerance is a threshold RDP compares
    a deviation against multiplicatively (does it exceed the tolerance, not
    by how much), so a proportional step in density should be a proportional
    -- not additive -- step in tolerance. A linear interpolation between 0.5
    and 0.01 would spend most of the slider barely changing anything and then
    collapse abruptly near the top; geometric interpolation keeps each step
    across the whole slider feeling similarly responsive.
    '''
    t = map_range(clamp(density, 0.1, 1.0), 0.1, 1.0, 0.0, 1.0)
    lo, hi = 0.5, 0.01 # lo = few control points, hi = more
    return lo * (hi / lo) ** t


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


def create_loopstrip_curve_overlay(
    opname : str,
    rftool_idname : str,
    idname : str,
    label : str,
    only_boundary : bool,
) -> type[RFOverlay_Base]:

    overlay_names.add(label)

    class RFOperator_LoopStrip_Curve_Overlay(RFOverlay_Base):
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
            self._curve_struct_cache = {}  # bmv_indices tuple -> {'knots','corner_set','cos'}

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
                    self.set_statusbar_override(('LMB: Edit Curve', ))
                Cursors.set('hand')
            else:
                if was_hovering:
                    self.set_statusbar_override(None)
                Cursors.restore()

            return {'PASS_THROUGH'}

        # ------------------------------------------------------------------ data

        def _tool_props(self, context : Context):
            active_tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
            return active_tool.operator_properties(rftool_idname)

        def _curve_handles_enabled(self, context : Context) -> bool:
            return self._tool_props(context).show_curve_handles

        def _bend_tolerance_factor(self, context : Context) -> float:
            return density_to_bend_tolerance(self._tool_props(context).curve_handle_density)

        def _sharp_corner_angle(self, context : Context) -> float:
            return self._tool_props(context).curve_corner_angle

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

            # curve_handle_density/curve_corner_angle are tool properties, not
            # scene data -- dragging either doesn't bump depsgraph_version, so
            # both are checked for separately here to still force a rebuild
            # (see _build_curve's own check against the cached structure's
            # tunables for why that's needed too, not just bypassing this
            # early-out). Bundled as one tuple so a future third tunable is
            # one more tuple entry, not a whole new set of tracking variables.
            tunables = (self._bend_tolerance_factor(context), self._sharp_corner_angle(context))
            tunables_changed = tunables != getattr(self, '_last_tunables', None)

            if not tunables_changed and self.depsgraph_version == RFCore.depsgraph_version and hasattr(self, 'curves'): return True
            if self.paused_update: return False

            cls = type(self)
            cls.depsgraph_version = RFCore.depsgraph_version
            self._last_tunables = tunables
            bend_tolerance_factor, sharp_angle = tunables

            self.curves = []
            self.chains = []
            self.label_data = []

            bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)
            sel_bmes = list(bmops.get_all_selected_bmedges(bm))
            if only_boundary or any(bme.is_wire or bme.is_boundary for bme in sel_bmes):
                sel_bmes = [bme for bme in sel_bmes if bme.is_wire or bme.is_boundary]

            if not sel_bmes or len(sel_bmes) >= 1000:
                return True

            strips, cycles = get_boundary_strips_cycles(sel_bmes)
            if len(strips) + len(cycles) > 5:
                return True

            avg_len = sum(bme_length(bme) for bme in sel_bmes) / len(sel_bmes)

            active_keys = set()
            for strip in strips:
                self._add_chain(self._strip_bmvs(strip, cyclic=False), cyclic=False, avg_len=avg_len,
                                 bend_tolerance_factor=bend_tolerance_factor, sharp_angle=sharp_angle, active_keys=active_keys)
            for cycle in cycles:
                self._add_chain(self._strip_bmvs(cycle, cyclic=True), cyclic=True, avg_len=avg_len,
                                 bend_tolerance_factor=bend_tolerance_factor, sharp_angle=sharp_angle, active_keys=active_keys)

            # drop cached structure for chains that are no longer selected
            self._curve_struct_cache = {
                k: v for k, v in self._curve_struct_cache.items() if k in active_keys
            }

            return True

        def _strip_bmvs(self, strip, *, cyclic):
            if not strip:
                return []
            if len(strip) == 1:
                return list(strip[0].verts)
            if cyclic:
                start = bmes_shared_bmv(strip[-1], strip[0])
                if not start:
                    return []
                bmvs = get_strip_bmvs(strip, start)
                if len(bmvs) > 1 and bmvs[0] == bmvs[-1]:
                    bmvs = bmvs[:-1]  # drop duplicated wrap vert
                return bmvs
            start = bme_unshared_bmv(strip[0], strip[1])
            return get_strip_bmvs(strip, start)

        def _add_chain(self, bmvs, *, cyclic, avg_len, bend_tolerance_factor, sharp_angle, active_keys):
            if not bmvs:
                return
            cos = [bmv.co.copy() for bmv in bmvs]
            if cyclic:
                self.label_data.append(('Loop', len(bmvs), cos))
            else:
                self.label_data.append(('Strip', len(bmvs) - 1, cos))

            if len(bmvs) < 5:
                return  # need 5+ verts in a row to build a curve

            cache_key = tuple(bmv.index for bmv in bmvs)
            active_keys.add(cache_key)
            spline, handles = self._build_curve(
                cos, cyclic=cyclic, avg_len=avg_len, bend_tolerance_factor=bend_tolerance_factor,
                sharp_angle=sharp_angle, cache_key=cache_key,
            )
            if spline is None or not spline.cbs:
                return

            self.curves.append(spline)
            self.chains.append({
                'bmv_indices': [bmv.index for bmv in bmvs],
                'cyclic': cyclic,
                'handles': handles,
            })

        def _build_curve(self, cos, *, cyclic, avg_len, bend_tolerance_factor, sharp_angle, cache_key):
            n = len(cos)
            tunables = (bend_tolerance_factor, sharp_angle)

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
            if knots is not None and max_dev is not None and max_dev <= avg_len * 1e-6:
                return cached['spline'], cached['handles']

            fresh_derive = knots is None
            if fresh_derive:
                # corner/span thresholds below are fractions of the chain's own
                # total length, NOT of avg_len -- avg_len is per-EDGE, so it
                # shrinks under subdivision (same shape, more/shorter edges),
                # which would make RDP more sensitive and auto-knot spans
                # trigger more often for a curve whose geometry hasn't changed
                # at all. stroke_length only depends on the curve's own shape.
                stroke_length = sum(
                    (Vector(cos[(i + 1) % n]) - Vector(cos[i])).length
                    for i in range(n if cyclic else n - 1)
                )
                tol = max(stroke_length * bend_tolerance_factor, 1e-6)

                # RDP's chord-deviation test is what decides whether a point becomes
                # a knot candidate at all -- a sharp but short kink (small arms) can
                # deviate too little from a distant chord to ever get proposed, even
                # though its own local angle is clearly a corner. Sharp verts are
                # found directly by angle first and forced in as seeds, so a genuine
                # corner always gets a knot regardless of how loose bend_tolerance_
                # factor (or its user-facing density control) is set.
                sharp_indices = self._sharp_angle_indices(cos, n, cyclic, sharp_angle)
                seed = ({0, n - 1} if not cyclic else set()) | sharp_indices
                corners = rdp_corner_indices(
                    cos, tol,
                    seed_indices=seed,
                    min_spacing=stroke_length * CORNER_MIN_SPACING_FACTOR,
                )

                # RDP picks each corner by max deviation from a chord that may span far
                # beyond its local bend, so the pick can land beside the true apex. Snap
                # each (non-endpoint) corner to the point of max deviation from the chord
                # between its own immediate neighbors -- the true local extremum. Sharp
                # verts are exact already (that's how they were found), so they're
                # locked in place along with the strip's own endpoints.
                locked = ({0, n - 1} if not cyclic else set()) | sharp_indices
                corners = self._snap_to_local_extrema(cos, corners, n, cyclic, locked)

                # Only verts with a geometrically sharp deflection angle get vector
                # (independent) handles. RDP knots at smooth verts still get G1 handles.
                corner_set = {
                    k for k in corners
                    if (angle := self._deflection_angle(cos, k, n, cyclic)) is not None and angle > sharp_angle
                }

                knots = list(corners)
                if cyclic and len(knots) < 2:
                    # ensure enough knots around a smooth loop to capture its shape
                    step = max(1, n // 4)
                    knots = sorted(set(knots) | set(range(0, n, step)))

                knots = self._insert_auto_knots(cos, knots, n, cyclic, stroke_length)

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
            if not fresh_derive and cached.get('spline'):
                locked_cbs = self._well_fit_segments(cached['spline'], cos, avg_len, n, cyclic, corner_set)

            spline = CubicBezierSpline.create_catmull_rom(
                cos, knots, cyclic=cyclic, corner_indices=corner_set, locked_cbs=locked_cbs,
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
                    if knots[(i + 1) % nknots] not in corner_set:
                        smooth_junctions.add(i)
            else:
                for i in range(min(nseg - 1, nknots - 2)):
                    if knots[i + 1] not in corner_set:
                        smooth_junctions.add(i)

            handles = self._build_handles(spline, cyclic, smooth_junctions)

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

        def _well_fit_segments(self, cached_spline, cos, avg_len, n, cyclic, corner_set):
            '''
            Segments of `cached_spline` worth handing to create_catmull_rom as
            locked: build the exact candidate create_catmull_rom would (a
            coupled knot's side snapped to its current vert and its tangent
            handle carried along by the same delta; a free knot's side left
            exactly as cached, since it was never tied to any particular vert
            -- see its is_free_knot), then check that candidate's own fit --
            average deviation of its interior verts -- against
            SEGMENT_KEEP_FIT_TOLERANCE. A coupled vert that moved far enough
            to need more than a same-delta translation shows up here as a
            worse fit, same as any other reason the curve stopped matching its
            points, so there's no need for a separate raw distance check on
            the endpoints themselves.

            Checked per segment rather than once for the whole chain, so an
            edit that only reshaped one part of a multi-segment chain doesn't
            force a refit of the parts that never stopped fitting well.
            '''
            def is_free(k):
                if k in corner_set:
                    return False
                return cyclic or (k != 0 and k != n - 1)

            fit_tol = avg_len * SEGMENT_KEEP_FIT_TOLERANCE
            locked = {}
            for i, (cb, (ka, kb)) in enumerate(zip(cached_spline.cbs, cached_spline.inds)):
                run = [Vector(cos[k % n]) for k in range(ka, kb + 1)]
                p0 = Vector(cb.p0) if is_free(ka % n) else run[0]
                p3 = Vector(cb.p3) if is_free(kb % n) else run[-1]
                d0, d3 = p0 - Vector(cb.p0), p3 - Vector(cb.p3)
                candidate = CubicBezier(p0, Vector(cb.p1) + d0, Vector(cb.p2) + d3, p3)
                if len(run) > 2:
                    avg_dev = CubicBezierSpline.total_distance(candidate, run) / (len(run) - 2)
                    if avg_dev > fit_tol:
                        continue
                locked[i] = cb
            return locked

        def _deflection_angle(self, cos, k, n, cyclic):
            '''
            Angle between vert k's incoming and outgoing edges, using its immediate
            neighbors only (not RDP or any chord) -- None for an open strip's own
            endpoint (no second arm to measure against) or a degenerate (zero-length)
            neighboring edge, where "angle" isn't a meaningful question.
            '''
            if not cyclic and (k == 0 or k == n - 1):
                return None
            prev_k = (k - 1) % n if cyclic else k - 1
            next_k = (k + 1) % n if cyclic else k + 1
            v_in  = Vector(cos[k])      - Vector(cos[prev_k])
            v_out = Vector(cos[next_k]) - Vector(cos[k])
            if v_in.length < 1e-9 or v_out.length < 1e-9:
                return None
            cos_a = max(-1.0, min(1.0, v_in.normalized().dot(v_out.normalized())))
            return math.acos(cos_a)

        def _sharp_angle_indices(self, cos, n, cyclic, sharp_angle):
            ''' Every vert whose own local deflection angle already exceeds
            `sharp_angle`, independent of RDP's chord-deviation test -- see
            its call site in _build_curve for why that independence matters. '''
            return {
                k for k in range(n)
                if (angle := self._deflection_angle(cos, k, n, cyclic)) is not None and angle > sharp_angle
            }

        def _max_dev_index(self, cos, ka, kb, n):
            '''
            Index in (ka, kb) -- an extended index range where kb may be >= n for a
            cyclic wrap -- whose vert has max perpendicular distance from chord
            cos[ka]-cos[kb]. This is the local "extremum" of that run. Returns None
            if there's no interior point.
            '''
            if kb - ka < 2:
                return None
            p0, p1 = Vector(cos[ka % n]), Vector(cos[kb % n])
            seg = p1 - p0
            seg_len2 = seg.length_squared
            best_k, best_d = None, -1.0
            for kk in range(ka + 1, kb):
                p = Vector(cos[kk % n])
                if seg_len2 < 1e-12:
                    d = (p - p0).length
                else:
                    t = max(0.0, min(1.0, (p - p0).dot(seg) / seg_len2))
                    d = (p - (p0 + t * seg)).length
                if d > best_d:
                    best_d, best_k = d, kk
            return best_k

        def _snap_to_local_extrema(self, cos, knots, n, cyclic, locked, iterations=2):
            knots = sorted(set(knots))
            if len(knots) < 3:
                return knots
            for _ in range(iterations):
                m = len(knots)
                refined = list(knots)
                changed = False
                for idx in range(m):
                    k = knots[idx]
                    if k in locked:
                        continue
                    ka = knots[(idx - 1) % m]
                    kb = knots[(idx + 1) % m]
                    if idx == 0:
                        ka -= n
                    if idx == m - 1:
                        kb += n
                    best = self._max_dev_index(cos, ka, kb, n)
                    if best is None:
                        continue
                    new_k = best % n
                    if new_k != k:
                        changed = True
                    refined[idx] = new_k
                knots = sorted(set(refined))
                if not changed:
                    break
            return knots

        def _arc_length(self, cos, ka, kb, n):
            return sum((Vector(cos[k % n]) - Vector(cos[(k - 1) % n])).length for k in range(ka + 1, kb + 1))

        def _insert_auto_knots(self, cos, knots, n, cyclic, stroke_length):
            knots = sorted(set(knots))
            if not knots:
                return knots
            # a fraction of the chain's own total length, not a vert count, so
            # subdividing (same shape, more/shorter edges) doesn't add auto-knots
            # that weren't warranted by the curve's actual geometry
            max_span = max(stroke_length * AUTO_KNOT_MAX_SPAN_FACTOR, 1e-6)
            result = set(knots)
            pairs = list(zip(knots[:-1], knots[1:]))
            if cyclic:
                pairs.append((knots[-1], knots[0] + n))  # closing run wraps past the end
            for ka, kb in pairs:
                self._split_long_span(cos, ka, kb, n, max_span, result)
            return sorted(result)

        def _split_long_span(self, cos, ka, kb, n, max_span, result):
            if self._arc_length(cos, ka, kb, n) <= max_span:
                return
            # place the extra knot at the run's true local extremum, not just its
            # midpoint by vert count, so long bends still get a knot at their apex
            best = self._max_dev_index(cos, ka, kb, n)
            if best is None or best in (ka, kb):
                mid = ka + (kb - ka) // 2
                if mid not in (ka, kb):
                    result.add(mid % n)
                return
            result.add(best % n)
            self._split_long_span(cos, ka, best, n, max_span, result)
            self._split_long_span(cos, best, kb, n, max_span, result)

        def _build_handles(self, spline, cyclic, smooth_junctions):
            cbs = spline.cbs
            nseg = len(cbs)
            handles = []
            if nseg == 0:
                return handles

            # a knot is vertex-coupled (dragging it moves a real vert, and that
            # vert's position defines it) unless it's a smooth, non-endpoint
            # junction -- those are "free": draggable to reshape the curve
            # without pinning any vert to the exact handle position (see
            # RFOperator_Strokes_CurveEdit.init)
            if cyclic:
                for i in range(nseg):
                    j = (i - 1) % nseg
                    handles.append({'kind':'knot', 'pos':(i,'p0'), 'free': j in smooth_junctions,
                                    'set':[(j,'p3'), (i,'p0')], 'move':[(j,'p2'), (i,'p1')]})
            else:
                handles.append({'kind':'knot', 'pos':(0,'p0'), 'free': False, 'set':[(0,'p0')], 'move':[(0,'p1')]})
                for i in range(1, nseg):
                    handles.append({'kind':'knot', 'pos':(i,'p0'), 'free': (i - 1) in smooth_junctions,
                                    'set':[(i-1,'p3'), (i,'p0')], 'move':[(i-1,'p2'), (i,'p1')]})
                handles.append({'kind':'knot', 'pos':(nseg-1,'p3'), 'free': False,
                                'set':[(nseg-1,'p3')], 'move':[(nseg-1,'p2')]})

            for i in range(nseg):
                # p1: outgoing arm from the junction on the LEFT of segment i
                # that junction is "after segment (i-1)%nseg" for cyclic, or (i-1) for open
                h_p1 = {'kind':'tangent', 'pos':(i,'p1'), 'set':[(i,'p1')], 'move':[]}
                left_j = (i - 1) % nseg if cyclic else (i - 1)
                if (cyclic or i > 0) and left_j in smooth_junctions:
                    h_p1['g1_knot'] = (i, 'p0')
                    h_p1['g1_peer'] = (left_j, 'p2')
                handles.append(h_p1)

                # p2: incoming arm to the junction on the RIGHT of segment i
                # that junction is "after segment i"
                h_p2 = {'kind':'tangent', 'pos':(i,'p2'), 'set':[(i,'p2')], 'move':[]}
                if (cyclic or i < nseg - 1) and i in smooth_junctions:
                    h_p2['g1_knot'] = (i, 'p3')
                    h_p2['g1_peer'] = ((i + 1) % nseg, 'p1')
                handles.append(h_p2)

            return handles

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
                for cb in cbs:
                    curve_pts = [
                        location_3d_to_region_2d(rgn, r3d, M @ Vector(cb.eval(v / 20)))
                        for v in range(21)
                    ]
                    curve_pts = [p for p in curve_pts if p]
                    draw_curve_line = False
                    if draw_curve_line and len(curve_pts) >= 2:
                        Drawing.draw2D_linestrip(context, curve_pts, (1.0, 1.0, 0.0, 0.5), width=2, stipple=[5,5])
                    # control polygon: draws the two tangent arms (p0-p1 and p2-p3),
                    # shortened at each end so the line stops at the handle dot's
                    # edge instead of running into its (partially transparent) center
                    p0_, p1_, p2_, p3_ = (location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cb, a))) for a in ('p0','p1','p2','p3'))
                    knot_r, tan_r = Drawing.scale(KNOT_RADIUS/2), Drawing.scale(TANGENT_RADIUS/2)
                    a0, a1 = shrink_segment(p0_, p1_, knot_r, tan_r)
                    a2, a3 = shrink_segment(p2_, p3_, tan_r, knot_r)
                    Drawing.draw2D_lines(context, [a0, a1, a2, a3], (1.0, 1.0, 1.0, 0.5), width=2)

                knot_pts2d, free_knot_pts2d, tan_pts2d = [], [], []
                for h in chain['handles']:
                    seg, attr = h['pos']
                    p = location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cbs[seg], attr)))
                    if not p:
                        continue
                    if h['kind'] != 'knot':
                        tan_pts2d.append(p)
                    elif h.get('free'):
                        free_knot_pts2d.append(p)
                    else:
                        knot_pts2d.append(p)
                if tan_pts2d:
                    Drawing.draw2D_points(context, tan_pts2d, (0.0, 0.0, 0.0, 0.75), radius=TANGENT_RADIUS, border=2, borderColor=(1,1,1,0.5))
                if knot_pts2d:
                    Drawing.draw2D_points(context, knot_pts2d, (1.0, 1.0, 1.0, 1.0), radius=KNOT_RADIUS, border=2, borderColor=(0,0,0,0.5))
                if free_knot_pts2d:
                    Drawing.draw2D_points(context, free_knot_pts2d, (1.0, 1.0, 1.0, 1.0), radius=KNOT_RADIUS, border=2, borderColor=FREE_KNOT_BORDER_COLOR)

    return type(opname, (RFOperator_LoopStrip_Curve_Overlay, RFOperator), {})
