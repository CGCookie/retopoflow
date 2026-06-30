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
from ..common.drawing import Drawing
from ..common.raycast import is_point_hidden, mouse_from_event
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bezier import CubicBezierSpline
from ...addon_common.common.blender_cursors import Cursors


# how many verts a single cubic segment may span before an auto-knot is inserted
AUTO_KNOT_MAX_SPAN = 20
# corner tolerance and min corner spacing as fractions of the average selected edge length
CORNER_TOLERANCE_FACTOR = 1.0
CORNER_MIN_SPACING_FACTOR = 0.5
# minimum deflection angle (between incoming and outgoing edges) for a vert to get
# independent (vector) tangent handles; below this it gets G1-aligned handles
SHARP_CORNER_ANGLE = math.radians(45)


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

        def _curve_handles_enabled(self, context : Context) -> bool:
            active_tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
            if not active_tool:
                return True
            try:
                tool_props = active_tool.operator_properties(rftool_idname)
                return getattr(tool_props, 'show_curve_handles', True)
            except Exception:
                return True

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

            if self.depsgraph_version == RFCore.depsgraph_version and hasattr(self, 'curves'): return True
            if self.paused_update: return False

            cls = type(self)
            cls.depsgraph_version = RFCore.depsgraph_version

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

            for strip in strips:
                self._add_chain(self._strip_bmvs(strip, cyclic=False), cyclic=False, avg_len=avg_len)
            for cycle in cycles:
                self._add_chain(self._strip_bmvs(cycle, cyclic=True), cyclic=True, avg_len=avg_len)

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

        def _add_chain(self, bmvs, *, cyclic, avg_len):
            if not bmvs:
                return
            cos = [bmv.co.copy() for bmv in bmvs]
            if cyclic:
                self.label_data.append(('Loop', len(bmvs), cos))
            else:
                self.label_data.append(('Strip', len(bmvs) - 1, cos))

            if len(bmvs) < 5:
                return  # need 5+ verts in a row to build a curve

            spline, handles = self._build_curve(cos, cyclic=cyclic, avg_len=avg_len)
            if spline is None or not spline.cbs:
                return

            self.curves.append(spline)
            self.chains.append({
                'bmv_indices': [bmv.index for bmv in bmvs],
                'cyclic': cyclic,
                'handles': handles,
            })

        def _build_curve(self, cos, *, cyclic, avg_len):
            n = len(cos)
            tol = max(avg_len * CORNER_TOLERANCE_FACTOR, 1e-6)
            seed = [] if cyclic else [0, n - 1]
            corners = rdp_corner_indices(
                cos, tol,
                seed_indices=seed,
                min_spacing=avg_len * CORNER_MIN_SPACING_FACTOR,
            )
            # Only verts with a geometrically sharp deflection angle get vector
            # (independent) handles. RDP knots at smooth verts still get G1 handles.
            corner_set = set()
            for k in corners:
                if not cyclic and (k == 0 or k == n - 1):
                    continue  # open-strip endpoints: no peer arm, angle is moot
                prev_k = (k - 1) % n if cyclic else k - 1
                next_k = (k + 1) % n if cyclic else k + 1
                v_in  = Vector(cos[k])      - Vector(cos[prev_k])
                v_out = Vector(cos[next_k]) - Vector(cos[k])
                if v_in.length < 1e-9 or v_out.length < 1e-9:
                    continue
                cos_a = max(-1.0, min(1.0, v_in.normalized().dot(v_out.normalized())))
                if math.acos(cos_a) > SHARP_CORNER_ANGLE:
                    corner_set.add(k)

            knots = list(corners)
            if cyclic and len(knots) < 2:
                # ensure enough knots around a smooth loop to capture its shape
                step = max(1, n // 4)
                knots = sorted(set(knots) | set(range(0, n, step)))

            knots = self._insert_auto_knots(knots, n, cyclic)
            spline = CubicBezierSpline.create_catmull_rom(cos, knots, cyclic=cyclic, corner_indices=corner_set)

            # Build smooth_junctions: set of segment indices i where the junction
            # AFTER cbs[i] is smooth (not a corner) so G1 should be enforced on drag
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
            return spline, handles

        def _insert_auto_knots(self, knots, n, cyclic, max_span=AUTO_KNOT_MAX_SPAN):
            knots = sorted(set(knots))
            if not knots:
                return knots
            result = set(knots)
            pairs = list(zip(knots[:-1], knots[1:]))
            if cyclic:
                pairs.append((knots[-1], knots[0] + n))  # closing run wraps past the end
            for ka, kb in pairs:
                span = kb - ka
                if span <= max_span:
                    continue
                ndiv = (span + max_span - 1) // max_span
                for j in range(1, ndiv):
                    result.add((ka + (span * j) // ndiv) % n)
            return sorted(result)

        def _build_handles(self, spline, cyclic, smooth_junctions):
            cbs = spline.cbs
            nseg = len(cbs)
            handles = []
            if nseg == 0:
                return handles

            if cyclic:
                for i in range(nseg):
                    j = (i - 1) % nseg
                    handles.append({'kind':'knot', 'pos':(i,'p0'),
                                    'set':[(j,'p3'), (i,'p0')], 'move':[(j,'p2'), (i,'p1')]})
            else:
                handles.append({'kind':'knot', 'pos':(0,'p0'), 'set':[(0,'p0')], 'move':[(0,'p1')]})
                for i in range(1, nseg):
                    handles.append({'kind':'knot', 'pos':(i,'p0'),
                                    'set':[(i-1,'p3'), (i,'p0')], 'move':[(i-1,'p2'), (i,'p1')]})
                handles.append({'kind':'knot', 'pos':(nseg-1,'p3'),
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
                    # control polygon: draws the two tangent arms (p0-p1 and p2-p3)
                    arms = [location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cb, a))) for a in ('p0','p1','p2','p3')]
                    Drawing.draw2D_lines(context, arms, (1.0, 1.0, 1.0, 0.5), width=2)

                knot_pts2d, tan_pts2d = [], []
                for h in chain['handles']:
                    seg, attr = h['pos']
                    p = location_3d_to_region_2d(rgn, r3d, M @ Vector(getattr(cbs[seg], attr)))
                    if not p:
                        continue
                    (knot_pts2d if h['kind'] == 'knot' else tan_pts2d).append(p)
                if tan_pts2d:
                    Drawing.draw2D_points(context, tan_pts2d, (0.0, 0.0, 0.0, 0.75), radius=12, border=2, borderColor=(1,1,1,0.5))
                if knot_pts2d:
                    Drawing.draw2D_points(context, knot_pts2d, (1.0, 1.0, 1.0, 1.0), radius=14, border=2, borderColor=(0,0,0,0.5))

    return type(opname, (RFOperator_LoopStrip_Curve_Overlay, RFOperator), {})
