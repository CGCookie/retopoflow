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

from ..rfglobals import RFGlobals
from ..common.bpy_helper import bpy_ops_retopoflow
from ..common.operator import RFOperator
from ..rftool_statusbar import SharedStatusbarKeymap
from ..common.bmesh import get_bmesh_emesh
from ..common.curves import ChainProvider, ChainSpec, derive_centerline_knots
from ..common.drawing import Drawing
from ..common.raycast import is_point_hidden, mouse_from_event
from ...addon_common.common.bezier import CubicBezier, CubicBezierSpline
from ...addon_common.common.blender_cursors import Cursors


KNOT_RADIUS = 14 # UI draw size
TANGENT_RADIUS = 12

CURVE_LINE_COLOR = (1.0, 1.0, 0.0, 0.5)
CONTROL_POLYGON_COLOR = (1.0, 1.0, 1.0, 0.5)
TANGENT_FILL_COLOR = (0.0, 0.0, 0.0, 0.75)
TANGENT_BORDER_COLOR = (1.0, 1.0, 1.0, 0.5)
KNOT_FILL_COLOR = (1.0, 1.0, 1.0, 1.0)
KNOT_BORDER_COLOR = (0.0, 0.0, 0.0, 0.5)
FREE_KNOT_FILL_COLOR = (0.5, 0.5, 0.5, 1.0)
AUTO_KNOT_FILL_COLOR = (1, 1, 1, 1.0)

DEBUG_SHOW_AUTO_HANDLES = False
DEBUG_SHOW_CURVE_LINE = False

# knot placement is cached until a single vert moves beyond this factor of the avg edge length
REBUILD_DEVIATION_FACTOR = 4.0
# curve fitting is reused until a point is this fraction of the avg edge length off
SEGMENT_KEEP_FIT_TOLERANCE = 1
# min seconds between rebuilds from a UI slider drag
TUNABLE_REBUILD_THROTTLE = 0.1

MAX_HANDLE_VERTS = 250
MAX_HANDLE_SEGMENTS = 25


def _internal_bl_idname(dotted_idname : str) -> str:
    category, _, name = dotted_idname.partition('.')
    return f'{category.upper()}_OT_{name}'

# RFCore's own always-running top-level modal operator.
# See update_data's check against context.window.modal_operators.
RFCORE_OPERATOR_BL_IDNAME = _internal_bl_idname('retopoflow.core')


def shrink_segment(p_from, p_to, shrink_from, shrink_to):
    ''' Pulls both ends of a screen space segment in by `shrink_from`/`shrink_to` pixels,
    so a line into a handle dot stops at the dot's edge instead of its center. '''
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
            cls.depsgraph_version = -42
            self.curves = []
            self.chains = []
            self.label_data = []
            self._curve_struct_cache = {}  # cache_key -> {'knots', 'corner_set', 'cos'}
            self._handle_type_overrides = {} # cache_key -> { vert_index -> 'aligned' | 'vector' | 'automatic' }

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
                    self.set_statusbar_override((
                        SharedStatusbarKeymap(label='Edit Curve', icons=['MOUSE_LMB_DRAG']),
                        SharedStatusbarKeymap(label='Scale Control Point', icons=['EVENT_ALT', 'MOUSE_LMB_DRAG']),
                        SharedStatusbarKeymap(label='Rotate Control Point', icons=['EVENT_ALT', 'EVENT_SHIFT', 'MOUSE_LMB_DRAG']),
                        SharedStatusbarKeymap(label='Toggle Handle Type', icons=['EVENT_V']),
                    ))
                Cursors.set('hand')
            else:
                if was_hovering:
                    self.set_statusbar_override(None)
                Cursors.restore()

            return {'PASS_THROUGH'}

        # ------------------------------------------------------------------ data

        def _curve_props(self, context : Context):
            # scene-level so every tool shares one set of density/corner-angle/visibility settings
            return context.scene.retopoflow.curve_handles

        def _curve_handles_enabled(self, context : Context) -> bool:
            return self._curve_props(context).show_curve_handles

        def _bend_tolerance_factor(self, context : Context) -> float:
            return self._curve_props(context).bend_tolerance_factor

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

            # Some other modal op (transform, box select, loop cut, etc.) has control
            # so skip rather than rebuild on every frame of its drag.
            external_ops = [
                op.bl_idname for op in context.window.modal_operators
                if op is not self and op.bl_idname != RFCORE_OPERATOR_BL_IDNAME
            ]
            if external_ops:
                return False

            # Force a rebuild when the user changes a related value
            tunables = (self._bend_tolerance_factor(context), self._sharp_corner_angle(context))
            tunables_changed = tunables != getattr(self, '_last_tunables', None)
            if tunables_changed and time.monotonic() - getattr(self, '_last_tunables_rebuild_time', 0.0) < TUNABLE_REBUILD_THROTTLE:
                # throttle during the drag
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

            if context.edit_object.data.total_vert_sel > MAX_HANDLE_VERTS:
                return True

            bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)

            # Providers tried in priority order, first one found wins
            specs : list[ChainSpec] = []
            for provider in providers:
                result = provider.collect(context, bm)
                if result:
                    specs.extend(result)
                    break

            active_keys = set()
            for spec in specs:
                self._add_chain(spec, bend_tolerance_factor=bend_tolerance_factor, sharp_angle=sharp_angle, active_keys=active_keys)

            # Hide handles when there are too many segments to be usable
            if sum(len(spline.cbs) for spline in self.curves) > MAX_HANDLE_SEGMENTS:
                self.curves = []
                self.chains = []
                self.label_data = []
                return True

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
                cache_key=spec.cache_key, forced_sharp_indices=spec.forced_sharp_indices,
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
                'coupled': spec.coupled, # True when points are on verts, False when derived from faces
            })

        def _build_curve(self, cos, *, cyclic, avg_len, bend_tolerance_factor, sharp_angle, cache_key, forced_sharp_indices=()):
            n = len(cos)
            # rebuild when important inputs are changed
            handle_type_overrides = self._handle_type_overrides.get(cache_key, {})
            tunables = (bend_tolerance_factor, sharp_angle, tuple(sorted(handle_type_overrides.items())), tuple(sorted(forced_sharp_indices)))

            cached = self._curve_struct_cache.get(cache_key)
            knots = corner_set = None
            max_dev = None
            if cached and len(cached['cos']) == n:
                max_dev = max((a - b).length for a, b in zip(cos, cached['cos']))
                # A tunable change invalidates the cached knot even if no vert moved
                if max_dev <= avg_len * REBUILD_DEVIATION_FACTOR and cached.get('tunables') == tunables:
                    knots, corner_set = cached['knots'], cached['corner_set']

            if knots is not None and max_dev is not None and max_dev <= avg_len * 1e-6:
                # Nothing moved so reuse the cached spline/handles
                return cached['spline'], cached['handles']

            fresh_derive = knots is None
            if fresh_derive:
                knots, corner_set = derive_centerline_knots(
                    cos, cyclic=cyclic,
                    bend_tolerance_factor=bend_tolerance_factor,
                    sharp_angle=sharp_angle,
                    forced_sharp_indices=forced_sharp_indices,
                )

            # Users have some control over handle types
            forced_vector = set(corner_set) | ({0, n - 1} if not cyclic else set())
            def resolve_handle_type(k):
                return handle_type_overrides.get(k) or ('vector' if k in forced_vector else 'automatic')
            corners_for_fit = { k for k in knots if resolve_handle_type(k) == 'vector' }

            # only reached on a structural rebuild or just after an edit, never per-frame
            locked_cbs = {}
            cached_cbs = {}
            prev_cos = None
            if not fresh_derive and cached.get('spline'):
                prev_cos = cached['cos']
                locked_cbs = self._well_fit_segments(cached['spline'], cos, prev_cos, avg_len, n, cyclic, corners_for_fit)
                # candidates only (unlike locked_cbs)
                # create_catmull_rom still fit-checks each before preferring it over the vert-anchored position
                cached_cbs = dict(enumerate(cached['spline'].cbs))

            spline = CubicBezierSpline.create_catmull_rom(
                cos, knots, cyclic=cyclic, corner_indices=corners_for_fit,
                locked_cbs=locked_cbs, prev_pts=prev_cos, cached_cbs=cached_cbs,
            )

            # aligned handle arms mirror each other's rotation
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

            # always cache as we need a baseline for the next call
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
            ''' Segments of `cached_spline` worth locking. '''
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

            # a knot is 'free' (draggable without pinning a vert) at a smooth, non-endpoint junction.
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
                # p1: outgoing arm from the junction on the left of segment i
                h_p1 = {'kind':'tangent', 'pos':(i,'p1'), 'set':[(i,'p1')], 'move':[],
                        'owner_vert_index': knots[i % nknots]}
                left_j = (i - 1) % nseg if cyclic else (i - 1)
                if (cyclic or i > 0) and left_j in smooth_junctions:
                    h_p1['g1_knot'] = (i, 'p0')
                    h_p1['g1_peer'] = (left_j, 'p2')
                handles.append(h_p1)

                # p2: incoming arm to the junction on the right of segment i
                h_p2 = {'kind':'tangent', 'pos':(i,'p2'), 'set':[(i,'p2')], 'move':[],
                        'owner_vert_index': knots[(i + 1) % nknots]}
                if (cyclic or i < nseg - 1) and i in smooth_junctions:
                    h_p2['g1_knot'] = (i, 'p3')
                    h_p2['g1_peer'] = ((i + 1) % nseg, 'p1')
                handles.append(h_p2)

            return handles

        _HANDLE_TYPE_CYCLE = {'aligned': 'vector', 'vector': 'automatic', 'automatic': 'aligned'}

        def set_handle_type(self, cache_key, vert_index, handle_type, *, reposition=False) -> bool:
            ''' Sets a knot's handle-type override. 'reposition' re-aims the knot's arms to match the new type's default. '''
            overrides = self._handle_type_overrides.setdefault(cache_key, {})
            if overrides.get(vert_index) == handle_type:
                return False
            if reposition:
                self._reposition_handle(cache_key, vert_index, handle_type)
            overrides[vert_index] = handle_type
            type(self).depsgraph_version = -42
            return True

        def toggle_handle_type(self, cache_key, vert_index) -> bool:
            ''' Cycles Aligned -> Vector -> Automatic for the knot. Caller must check 'can_toggle' first. '''
            for chain in self.chains:
                if chain['cache_key'] != cache_key:
                    continue
                for h in chain['handles']:
                    if h['kind'] == 'knot' and h.get('vert_index') == vert_index:
                        current = h.get('handle_type', 'automatic')
                        return self.set_handle_type(cache_key, vert_index, self._HANDLE_TYPE_CYCLE[current], reposition=True)
            return False

        def _reposition_handle(self, cache_key, vert_index, new_type):
            ''' Re-aims a toggled knot's two tangent arms to match its new handle type, keeping each arm's length. '''
            for chain, spline in zip(self.chains, self.curves):
                if chain['cache_key'] != cache_key:
                    continue
                handle = next(
                    (h for h in chain['handles'] if h['kind'] == 'knot' and h.get('vert_index') == vert_index),
                    None,
                )
                if handle is None or len(handle.get('move', ())) != 2:
                    return  # an endpoint, one arm, nothing to re-aim
                (seg_in, attr_in), (seg_out, attr_out) = handle['move']
                cbs = spline.cbs
                knot_seg, knot_attr = handle['pos']
                knot_pos = Vector(getattr(cbs[knot_seg], knot_attr))
                arm_out = Vector(getattr(cbs[seg_out], attr_out)) - knot_pos
                arm_in = Vector(getattr(cbs[seg_in], attr_in)) - knot_pos
                len_out, len_in = arm_out.length, arm_in.length
                if len_out < 1e-9 or len_in < 1e-9:
                    return
                dir_out, dir_in = arm_out.normalized(), arm_in.normalized()

                if new_type == 'aligned':
                    # collinear: smallest rotation onto the pair's shared bisector
                    avg = dir_out.slerp(-dir_in, 0.5)
                    if avg.length < 1e-9:
                        return
                    new_out, new_in = avg.normalized(), -avg.normalized()
                elif new_type == 'vector':
                    # point at each neighbor, but apply the two arms' average
                    # offset to both so the pair's facing barely moves.
                    prev_pos = Vector(cbs[seg_in].p0)
                    next_pos = Vector(cbs[seg_out].p3)
                    pa_out, pa_in = next_pos - knot_pos, prev_pos - knot_pos
                    if pa_out.length < 1e-9 or pa_in.length < 1e-9:
                        return
                    pa_out, pa_in = pa_out.normalized(), pa_in.normalized()
                    offset_out = pa_out.rotation_difference(dir_out)
                    offset_in = pa_in.rotation_difference(dir_in)
                    avg_offset = offset_out.slerp(offset_in, 0.5)
                    new_out = (avg_offset @ pa_out).normalized()
                    new_in = (avg_offset @ pa_in).normalized()
                else:
                    return  # 'automatic' so leave as-is

                setattr(cbs[seg_out], attr_out, knot_pos + new_out * len_out)
                setattr(cbs[seg_in], attr_in, knot_pos + new_in * len_in)
                return

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
                # also covers a native transform being mid-drag
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
                # hide Automatic knots' tangent handles by default since user's can't edit them.
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
                    if DEBUG_SHOW_CURVE_LINE:
                        curve_pts = [p for v in range(21)
                                     if (p := location_3d_to_region_2d(rgn, r3d, M @ Vector(cb.eval(v / 20))))]
                        if len(curve_pts) >= 2:
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
