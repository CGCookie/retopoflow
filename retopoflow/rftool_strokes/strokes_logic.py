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

import bpy
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from ..common.bmesh import (
    get_bmesh_emesh,
    bme_midpoint, get_boundary_strips_cycles,
    bme_other_bmv,
    bmes_shared_bmv,
    bme_unshared_bmv,
    bmvs_shared_bme,
    bme_vector,
    bme_length,
)
from ..common.bmesh_maths import (
    find_point_at,
    find_closest_point,
    find_sharpest_indices,
    find_sharpest_index,
    compute_n,
    bmes_get_prevnext_bmvs,
    get_strip_bmvs,
    check_bmf_normals,
    fit_template2D,
    vec_screenspace_angle,
    vecs_screenspace_angle,
    get_boundary_cycle,
    get_boundary_strips,
    get_longest_strip_cycle,
)
from ..common.raycast import raycast_point_valid_sources, nearest_normal_valid_sources, nearest_point_valid_sources
from ..common.maths import view_forward_direction, lerp, bvec_to_point, point_to_bvec3, bvec_point_to_bvec4, bvec_vector_to_bvec4
from ..common.maths import xform_point, xform_vector, xform_direction
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bezier import interpolate_cubic
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import closest_point_segment, segment2D_intersection, Frame
from ...addon_common.common.maths import clamp, sign_threshold
from ...addon_common.common.utils import iter_pairs, rip

import math
from collections import deque
from itertools import takewhile

r'''
Table of Implemented:

             :  Nothing    Opposite   Extend Out    Connect     Connect     Connect
             :  Selected   Side       Selected      Sides       Selected    Corners
-------------+--------------------------------------------------------------------------
             :             Equals      T-shaped     I-shaped    C-shaped    L-shaped
-------------+--------------------------------------------------------------------------
             :    ┆        ═══════     ═══O═══      ═══O═══     O═════O     ╤═════O
             :    ┆        + + + +     + +┆+ +      + +┆+ +     ┆+ + +┆     │+ + +┆
     Strip/  :    ┆        + + + +     + +┆+ +      + +┆+ +     ┆+ + +┆     │+ + +┆
      Quad:  :    ┆        + + + +     + +┆+ +      + +┆+ +     ┆+ + +┆     │+ + +┆
             :    ┆        ╌╌╌╌╌╌╌     + +┆+ +      ═══O═══     C╌╌╌╌╌C     O╌╌╌╌╌C
-------------+--------------------------------------------------------------------------
             :             ╤══════                  ═══O═══
             :             │ + + +                  + +┆+ +
             :             │ + + +                  + +┆+ +
             :             │ + + +                  + +┆+ +
             :             O╌╌╌╌╌╌                  ───O───
-------------+--------------------------------------------------------------------------
             :  ╭╌╌╌╮      ╭╌╌╌╌╌╮       +++        ┌─────┐
             :  ┆   ┆      ┆+╔═╗+┆     ++╔═╗++      │+╔═╗+│
     Cycle/  :  ┆   ┆      ┆+║ ║+┆     ++║ O╌╌      │+║ O╌O
   Annulus:  :  ┆   ┆      ┆+╚═╝+┆     ++╚═╝++      │+╚═╝+│
          :  :  ╰╌╌╌╯      ╰╌╌╌╌╌╯       +++        └─────┘
-------------+--------------------------------------------------------------------------

Key:
     ┆╌ stroke
     C  corner in stroke (based on sharpness of stroke)
     ǁ═ selected boundary or wire edges
     │─ unselected boundary or wire edges
     O  vertex under stroke
     +  inserted verts (interpolated from selection and stroke)

notes:
- only considering vertices under ends of stroke (beginning/ending), not in the middle



Questions/Thoughts:

- D-strip, L-strip, and O-shape are all very similar, especially if left side of L is required to be selected
    - could we simplify by detecting how many corners are in selected strip?
- What if I-shaped did not required both sides (top/bottom) to be selected?
    - What if only one side is selected?
    - What if neither side is required to be selected?
- Control how the two are spanned??
    - Can rotate stroke-cycle?

'''

DEBUG = False


# TODO: make sure that any part of stroke that is at the mirror **SHOULD** be have a vertex!
#       for example, the shape of number 8.  right now the top and bottom points are guaranteed
#       to be on the mirror, but the middle is not.  think of them as endpoints or corners.
#       in fact, corners **SHOULD** have a vertex, too, similar to corners in PolyStrips.

# TODO: if two endpoints are on the same mirror, then all verts between them should also be on that mirror too


class Strokes_Logic:
    def __init__(self, context, radius, snap_distance, stroke3D, is_cycle, snapped_geo, snapped_mirror, span_insert_mode, fixed_span_count, extrapolate_mode, smooth_angle, smooth_density0, smooth_density1, mirror_mode, mirror_correct):
        self.radius = radius
        self.snap_distance = snap_distance
        self.stroke3D_original = stroke3D    # stroke can change, so keep a copy of original

        self.show_is_cycle = True
        self.is_cycle = is_cycle
        self.snapped_geo = snapped_geo
        self.snapped_mirror = snapped_mirror

        self.span_insert_mode = span_insert_mode
        self.fixed_span_count = fixed_span_count

        self.show_extrapolate_mode = True
        self.extrapolate_mode = extrapolate_mode

        self.show_bridging_offset = False
        self.bridging_offset = 0
        self.min_bridging_offset = 0
        self.max_bridging_offset = 0

        self.show_smoothness = False
        self.smooth_angle = smooth_angle
        self.smooth_density0 = smooth_density0
        self.smooth_density1 = smooth_density1

        self.show_force_nonstripL = False
        self.force_nonstripL = False

        self.show_untwist_bridge = False
        self.untwist_bridge = False

        self.show_mirror_mode = False
        self.mirror_mode = mirror_mode
        self.show_mirror_correct = False
        self.mirror_correct = mirror_correct

        self.show_action = ''
        self.show_count = True
        self.cut_count = None
        self.initial = True

        self.failure_message = None


    def update(self, context):
        self.bm, self.em = get_bmesh_emesh(context)
        bmops.flush_selection(self.bm, self.em)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()

        self.stroke3D = list(self.stroke3D_original)  # stroke can change, so keep a copy of original
        self.important_indices = []
        self.important_lengths = {}

        self.process_selected(context)          # gather details about selected geometry
        self.process_mirror(context)            # can change stroke, depends on selected geo
        if not self.stroke3D:
            self.failure_message = 'Stroke was not compatible with settings'
            return
        self.process_stroke_details(context)    # must happen after stroke is finalized
        self.process_snap_geometry(context)     # should probably happen after stroke is finalized

        # TODO: handle gracefully if these functions fail
        try:
            self.insert(context)
        except Exception as e:
            print(f'Exception caught: {e}')
            debugger.print_exception()
        # bpy.ops.ed.undo_push(message=f'Strokes insert {time.time()}')

        # now that we've done calculations on span count, switch to fixed so artist can adjust cut_count
        if self.cut_count is not None:
            self.span_insert_mode = 'FIXED'
            self.fixed_span_count = self.cut_count
        self.initial = False

    def get_mirror_side(self, pt3D_local):
        return (
            1 if 'x' not in self.mirror else sign_threshold(pt3D_local.x, self.mirror_threshold),
            1 if 'y' not in self.mirror else sign_threshold(pt3D_local.y, self.mirror_threshold),
            1 if 'z' not in self.mirror else sign_threshold(pt3D_local.z, self.mirror_threshold),
        )

    def process_mirror(self, context):
        self.mirror = set()
        self.mirror_clip = False
        self.mirror_threshold = 0
        for mod in context.edit_object.modifiers:
            if mod.type != 'MIRROR': continue
            if not mod.use_clip: continue
            if mod.use_axis[0]: self.mirror.add('x')
            if mod.use_axis[1]: self.mirror.add('y')
            if mod.use_axis[2]: self.mirror.add('z')
            self.mirror_threshold = mod.merge_threshold
            self.mirror_clip = mod.use_clip

        if not self.mirror or not self.mirror_clip: return  # no mirroring or clipping

        sides = [ self.get_mirror_side(pt) for pt in self.stroke3D ]
        all_sides = set(sides)

        if not self.sel_edges:
            # nothing selected, so check against where the stroke started
            if len(all_sides) == 1: return  # stroke is entirely on one side of mirror or along mirror
            match self.mirror_correct:
                case 'MOST':
                    counts = {}
                    for side in sides:
                        if 0 in side: continue
                        counts[side] = counts.get(side, 0) + 1
                    correct_side = max(counts.keys(), key=lambda k:counts[k])
                case 'FIRST':
                    correct_side = next((side for side in sides if 0 not in side))
                case 'LAST':
                    correct_side = next((side for side in sides[::-1] if 0 not in side))
            self.show_mirror_correct = True
        else:
            # check against selected geometry
            sel_sides = [ self.get_mirror_side(bmv.co) for bme in self.sel_edges for bmv in bme.verts ]
            correct_side = next(side for side in sel_sides if 0 not in side)
            if all(side == correct_side for side in all_sides if 0 not in side): return   # stroke and selected geometry all on same side of mirror (or along)

        self.show_mirror_mode = True

        new_stroke = []

        match self.mirror_mode:
            case 'CLAMP':
                # clamp to mirror
                for (pt, side) in zip(self.stroke3D, sides):
                    # snap
                    s = Vector((
                        1 if side[0] == correct_side[0] else 0,
                        1 if side[1] == correct_side[1] else 0,
                        1 if side[2] == correct_side[2] else 0,
                    ))
                    new_stroke += [pt * s]

            case 'TRIM':
                # trim to mirror
                longest_stroke = None
                current_stroke = []
                prev_pt, prev_side = self.stroke3D[0], sides[0]
                for (pt, side) in zip(self.stroke3D, sides):
                    if prev_side == side:
                        if side == correct_side: current_stroke += [pt]
                        prev_pt = pt
                        continue
                    # switched sides
                    (pt0, pt1) = (prev_pt, pt) if prev_side == correct_side else (pt, prev_pt)
                    for _ in range(100):
                        pt = pt0 + (pt1 - pt0) * 0.5
                        s = self.get_mirror_side(pt)
                        if 0 in s: break
                        (pt0, pt1) = (pt, pt1) if s == correct_side else (pt0, pt)
                    s = Vector((
                        0 if side[0] != correct_side[0] else 1,
                        0 if side[1] != correct_side[1] else 1,
                        0 if side[2] != correct_side[2] else 1,
                    ))
                    current_stroke += [s * pt]
                    if prev_side == correct_side:
                        if longest_stroke is None or len(current_stroke) > len(longest_stroke):
                            longest_stroke = current_stroke
                        current_stroke = []
                    prev_pt, prev_side = pt, side
                if longest_stroke is None or len(current_stroke) > len(longest_stroke):
                    longest_stroke = current_stroke
                new_stroke = longest_stroke

            case 'REFLECT':
                # reflect by mirror
                for (pt, side) in zip(self.stroke3D, sides):
                    # snap
                    s = Vector((
                        1 if side[0] == correct_side[0] else -1,
                        1 if side[1] == correct_side[1] else -1,
                        1 if side[2] == correct_side[2] else -1,
                    ))
                    new_stroke += [pt * s]

        self.stroke3D = new_stroke

        l = len(self.stroke3D)
        self.important_indices = {0, l-1}
        i0 = 0
        while i0 < l:
            if 0 not in self.get_mirror_side(self.stroke3D[i0]):
                # not near mirror
                i0 += 1
                continue
            # found first pt near mirror, so find next pt that's right before we leave the mirror
            i1 = next((i1 for i1 in range(i0, l-1) if 0 not in self.get_mirror_side(self.stroke3D[i1+1])), l-1)
            if i0 != l - 2: self.important_indices.add(i0)
            if i1 != 1:     self.important_indices.add(i1)
            i0 = i1 + 1
        self.important_indices = list(sorted(self.important_indices))
        self.important_lengths = {
            i:sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke3D[:i+1], False))
            for i in self.important_indices
        }
        # print(self.important_indices)
        # print([self.get_mirror_side(self.stroke3D[i]) for i in self.important_indices])


    def process_stroke_details(self, context):

        # project 3D stroke points to screen  (assuming stroke3D has no Nones)
        self.stroke2D = [ self.project_pt(context, pt3D) for pt3D in self.stroke3D ]

        # compute total lengths, which will be used to find where new verts are to be created
        self.length2D = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke2D, self.is_cycle))
        self.length3D = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke3D, self.is_cycle))

    def process_selected(self, context):
        """
        Finds and analyzes all selected geometry, which is used to determine how to interpret
        an insertion (new strip/cycle, bridging selection to stroke, etc. )
        """
        self.sel_edges = [
            bme
            for bme in bmops.get_all_selected_bmedges(self.bm)
            if bme.is_wire or bme.is_boundary
            # len(bme.link_faces) < 2
            # not is_manifold() ==> len(bme.link_faces) != 2 which includes edges with 3+ faces :(
        ]
        self.average_length = (sum(bme_length(bme) for bme in self.sel_edges) / len(self.sel_edges)) if self.sel_edges else 0
        self.longest_strip0, self.longest_strip1, self.longest_cycle0, self.longest_cycle1 = get_longest_strip_cycle(self.sel_edges)
        self.longest_strip0_length = sum(bme_length(bme) for bme in self.longest_strip0) if self.longest_strip0 else None
        self.longest_strip1_length = sum(bme_length(bme) for bme in self.longest_strip1) if self.longest_strip1 else None
        self.longest_cycle0_length = sum(bme_length(bme) for bme in self.longest_cycle0) if self.longest_cycle0 else None
        self.longest_cycle1_length = sum(bme_length(bme) for bme in self.longest_cycle1) if self.longest_cycle1 else None
        # make strips point up
        def fix_strip(strip):
            if not strip or len(strip) <= 1: return
            bmv0, bmv1 = bme_unshared_bmv(strip[0], strip[1]), bmes_shared_bmv(strip[0], strip[1])
            p0, p1 = self.project_bmv(context, bmv0), self.project_bmv(context, bmv1)
            if p0.y > p1.y: strip.reverse()
        fix_strip(self.longest_strip0)
        fix_strip(self.longest_strip1)

    def process_snap_geometry(self, context):
        self.snap_bmv0 = self.bmv_closest(context, self.bm.verts, self.stroke3D[0])
        self.snap_bmv1 = self.bmv_closest(context, self.bm.verts, self.stroke3D[-1])

        # cycle
        self.snap_bmv0_cycle0 = self.snap_bmv0 and self.longest_cycle0 and any(self.snap_bmv0 in bme.verts for bme in self.longest_cycle0)
        self.snap_bmv1_cycle0 = self.snap_bmv1 and self.longest_cycle0 and any(self.snap_bmv1 in bme.verts for bme in self.longest_cycle0)
        self.snap_bmv0_cycle1 = self.snap_bmv0 and self.longest_cycle1 and any(self.snap_bmv0 in bme.verts for bme in self.longest_cycle1)
        self.snap_bmv1_cycle1 = self.snap_bmv1 and self.longest_cycle1 and any(self.snap_bmv1 in bme.verts for bme in self.longest_cycle1)

        # strip
        self.snap_bmv0_strip0 = self.snap_bmv0 and self.longest_strip0 and any(self.snap_bmv0 in bme.verts for bme in self.longest_strip0)
        self.snap_bmv1_strip0 = self.snap_bmv1 and self.longest_strip0 and any(self.snap_bmv1 in bme.verts for bme in self.longest_strip0)
        self.snap_bmv0_strip1 = self.snap_bmv0 and self.longest_strip1 and any(self.snap_bmv0 in bme.verts for bme in self.longest_strip1)
        self.snap_bmv1_strip1 = self.snap_bmv1 and self.longest_strip1 and any(self.snap_bmv1 in bme.verts for bme in self.longest_strip1)

        # used for L-strip, only considering longest strip
        self.snap_bmv0_sel   = self.snap_bmv0 and     self.snap_bmv0_strip0
        self.snap_bmv1_sel   = self.snap_bmv1 and     self.snap_bmv1_strip0
        self.snap_bmv0_nosel = self.snap_bmv0 and not self.snap_bmv0_strip0
        self.snap_bmv1_nosel = self.snap_bmv1 and not self.snap_bmv1_strip0

    def reverse_stroke(self):
        self.stroke2D.reverse()
        self.stroke3D.reverse()
        self.snap_bmv0,         self.snap_bmv1         = self.snap_bmv1,         self.snap_bmv0
        self.snap_bmv0_cycle0,  self.snap_bmv1_cycle0  = self.snap_bmv1_cycle0,  self.snap_bmv0_cycle0
        self.snap_bmv0_cycle1,  self.snap_bmv1_cycle1  = self.snap_bmv1_cycle1,  self.snap_bmv0_cycle1
        self.snap_bmv0_strip0,  self.snap_bmv1_strip0  = self.snap_bmv1_strip0,  self.snap_bmv0_strip0
        self.snap_bmv0_strip1,  self.snap_bmv1_strip1  = self.snap_bmv1_strip1,  self.snap_bmv0_strip1
        self.snap_bmv0_sel,     self.snap_bmv1_sel     = self.snap_bmv1_sel,     self.snap_bmv0_sel
        self.snap_bmv0_nosel,   self.snap_bmv1_nosel   = self.snap_bmv1_nosel,   self.snap_bmv0_nosel
        self.snapped_mirror[0], self.snapped_mirror[1] = self.snapped_mirror[1], self.snapped_mirror[0]

    def insert(self, context):
        if DEBUG:
            def dbg(l): return len(l) if l is not None else None
            print(f'')
            print(f'{self.is_cycle=}')
            print(f'  {dbg(self.longest_cycle0)=} {dbg(self.longest_cycle1)=}')
            print(f'  {dbg(self.longest_strip0)=} {dbg(self.longest_strip1)=}')
            print(f'  {self.snap_bmv0_strip0=} {self.snap_bmv0_strip1=} {self.snap_bmv1_strip0=} {self.snap_bmv1_strip1=}')
            print(f'  {self.snap_bmv0_cycle0=} {self.snap_bmv0_cycle1=} {self.snap_bmv1_cycle0=} {self.snap_bmv1_cycle1=}')
            print(f'  {self.snap_bmv0_sel=} {self.snap_bmv1_sel=}')
            print(f'  {self.snap_bmv0_nosel=} {self.snap_bmv1_nosel=}')

        if self.is_cycle:
            if not self.longest_cycle0:
                self.insert_cycle(context)
            else:
                self.insert_cycle_equals(context)
        else:
            if self.snap_bmv0_cycle0 or self.snap_bmv1_cycle0:
                if self.longest_cycle1 and len(self.longest_cycle0) == len(self.longest_cycle1) and ((self.snap_bmv0_cycle0 and self.snap_bmv1_cycle1) or (self.snap_bmv0_cycle1 and self.snap_bmv1_cycle0)):
                    self.insert_cycle_I(context)
                else:
                    self.insert_cycle_T(context)
            elif self.longest_strip0:
                if self.longest_strip1 and len(self.longest_strip0) == len(self.longest_strip1) and ((self.snap_bmv0_strip0 and self.snap_bmv1_strip1) or (self.snap_bmv0_strip1 and self.snap_bmv1_strip0)):
                    self.insert_strip_I(context)
                elif self.snap_bmv0_strip0 or self.snap_bmv1_strip0:
                    if self.snap_bmv0_strip0 and self.snap_bmv1_strip0:
                        self.insert_strip_C(context)
                    elif (self.snap_bmv0_sel and self.snap_bmv1_nosel) or (self.snap_bmv0_nosel and self.snap_bmv1_sel):
                        self.insert_strip_L(context)
                    else:
                        self.insert_strip_T(context)
                else:
                    self.insert_strip_equals(context)
            else:
                self.insert_strip(context)

        bmops.flush_selection(self.bm, self.em)


    #####################################################################################
    # utility functions

    def find_point2D(self, v):  return find_point_at(self.stroke2D, self.is_cycle, v)
    def find_point3D(self, v):  return find_point_at(self.stroke3D, self.is_cycle, v)
    def project_pt(self, context, pt):
        p = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt)
        return p.xy if p else None
    def project_bmv(self, context, bmv):
        p = self.project_pt(context, bmv.co)
        return p.xy if p else None
    def bmv_closest(self, context, bmvs, pt3D):
        pt2D = self.project_pt(context, pt3D)
        off3D2 = context.space_data.overlay.retopology_offset ** 2  # TODO: TAKE INTO ACCOUNT OBJECT NON-UNIFORM SCALING
        # bmvs = [bmv for bmv in bmvs if bmv.select and (pt := self.project_bmv(context, bmv)) and (pt - pt2D).length_squared < 20*20]
        sd2 = self.snap_distance ** 2
        bmvs = [
            bmv
            for bmv in bmvs
            if (
                # (pt3D - bmv.co).length_squared < off3D2 and
                (pt := self.project_bmv(context, bmv)) and (pt - pt2D).length_squared <= sd2
            )
        ]
        if not bmvs: return None
        return min(bmvs, key=lambda bmv: (bmv.co - pt3D).length_squared)


    #####################################################################################
    # simple insertions with no bridging

    def insert_strip(self, context):
        match self.span_insert_mode:
            case 'BRUSH' | 'AVERAGE':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        if self.important_indices: nspans = max(nspans, len(self.important_indices)-1)
        nverts = nspans + 1

        if self.important_indices:
            len_stroke = len(self.stroke3D)
            len_spans = len(self.important_indices)
            # print(len_stroke, len_spans)
            segment_spans = [[i0, i1, self.important_lengths[i1]-self.important_lengths[i0], 1] for (i0,i1) in iter_pairs(self.important_indices, False)]
            additional_inds = nverts - len(self.important_indices)
            for _ in range(additional_inds):
                segment_spans.sort(key=lambda ss: ss[2] / ss[3])
                segment_spans[-1][3] += 1
            segment_spans.sort(key=lambda ss: ss[0])
            # print(segment_spans)

            bmvs = []
            # print(f'{nverts=}')
            if self.snap_bmv0:
                # print('snap first')
                bmvs += [self.snap_bmv0]
            else:
                bmvs += [self.bm.verts.new(self.find_point3D(0))]
            for (i0,i1,_,c) in segment_spans:
                l0 = self.important_lengths[i0]
                l1 = self.important_lengths[i1]
                for p in range(c):
                    # print(f'{i0=} {i1=} {p=} {c=}')
                    if p == c - 1 and i1 == len_stroke - 1 and self.snap_bmv1:
                        # print('snap last')
                        bmvs += [self.snap_bmv1]
                        break
                    v = (l0 + (l1 - l0) * (p + 1) / c) / self.length3D
                    pt = self.find_point3D(v)
                    bmvs += [self.bm.verts.new(pt)]
        else:
            bmvs = []
            for iv in range(nverts):
                if iv == 0 and self.snap_bmv0:
                    bmvs += [self.snap_bmv0]
                elif iv == nverts - 1 and self.snap_bmv1:
                    bmvs += [self.snap_bmv1]
                else:
                    v = iv / (nverts-1)
                    pt = self.find_point3D(v)
                    bmvs += [self.bm.verts.new(pt)]

        bmes = []
        for ie in range(nspans):
            bmv0, bmv1 = bmvs[ie], bmvs[ie+1]
            bme = next((e for e in bmv0.link_edges if e in bmv1.link_edges), None)
            if not bme:
                bme = self.bm.edges.new((bmv0, bmv1))
            bmes += [bme]

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs)

        self.cut_count = nspans
        self.show_action = 'Strip'
        self.show_count = True
        self.show_is_cycle = True
        self.show_extrapolate_mode = False

    def insert_cycle(self, context):
        if DEBUG: print(f'insert_cycle()')
        match self.span_insert_mode:
            case 'BRUSH' | 'AVERAGE':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(3, nspans)
        nverts = nspans

        bmvs = [
            self.bm.verts.new(self.find_point3D(iv / nverts))
            for iv in range(nverts)
        ]
        bmes = [
            self.bm.edges.new((bmv0, bmv1))
            for (bmv0, bmv1) in iter_pairs(bmvs, True)
        ]

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs)

        self.cut_count = nspans
        self.show_action = 'Loop'
        self.show_count = True
        self.show_is_cycle = True
        self.show_extrapolate_mode = False


    ##############################################################################
    # cycle bridging insertions

    def insert_cycle_equals(self, context):
        if DEBUG: print(f'insert_cycle_equals()')

        assert self.is_cycle
        assert self.longest_cycle0

        llc = len(self.longest_cycle0)

        # make sure stroke and selected cyclic bmvs have same winding direction
        n_stroke3D = compute_n(self.stroke3D)
        n_bmvs = compute_n([bme_midpoint(bme) for bme in self.longest_cycle0])
        if n_bmvs.dot(n_stroke3D) < 0:
            # turning opposite directions
            self.stroke3D.reverse()

        # align closest points between selected cyclic bmvs and stroke
        M, Mi = self.matrix_world, self.matrix_world_inv
        closest_i, closest_pt0, closest_j, closest_pt1, closest_d = None, None, None, None, float('inf')
        for i in range(llc):
            bme_pre = self.longest_cycle0[(i-1) % llc]
            bme_cur = self.longest_cycle0[i]
            bmv = bmes_shared_bmv(bme_pre, bme_cur)
            for (j, pt) in enumerate(self.stroke3D):
                d = (bmv.co - pt).length
                if d >= closest_d: continue
                closest_i, closest_pt0, closest_j, closest_pt1, closest_d = i, bmv.co, j, pt, d
        # rotate lists so self.stroke3D[0] aligns self.longest_cycle0[0]
        self.longest_cycle0 = self.longest_cycle0[closest_i:] + self.longest_cycle0[:closest_i]
        self.stroke3D = self.stroke3D[closest_j:] + self.stroke3D[:closest_j]

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                pt0 = self.project_pt(context, closest_pt0)
                pt1 = self.project_pt(context, closest_pt1)
                nspans = round((pt0 - pt1).length / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                nspans = round((closest_pt0 - closest_pt1).length / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # build spans
        bme_pre = self.longest_cycle0[-1]
        accum_dist = 0
        bmvs = [[] for i in range(nverts)]
        for bme_cur in self.longest_cycle0:
            bmv = bmes_shared_bmv(bme_pre, bme_cur)
            spt = self.find_point3D(accum_dist / self.longest_cycle0_length)
            pt0 = self.project_bmv(context, bmv)
            pt1 = self.project_pt(context, spt)
            v = pt1 - pt0

            bmvs[0].append(bmv)
            for i in range(1, nverts):
                pt = pt0 + v * (i / (nverts - 1))
                co = raycast_point_valid_sources(context, pt, world=False)
                bmvs[i].append(self.bm.verts.new(co) if co else None)

            accum_dist += bme_length(bme_cur)
            bme_pre = bme_cur

        # fill in quads
        bmfs = []
        for i in range(nverts-1):
            for j in range(llc):
                bmv00 = bmvs[i+0][(j+0)%llc]
                bmv01 = bmvs[i+0][(j+1)%llc]
                bmv10 = bmvs[i+1][(j+0)%llc]
                bmv11 = bmvs[i+1][(j+1)%llc]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = xform_direction(Mi, view_forward_direction(context))
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[-1])

        self.cut_count = nspans
        self.show_action = 'Equals-Loop'
        self.show_count = True
        self.show_is_cycle = False
        self.show_extrapolate_mode = False


    def insert_cycle_T(self, context):
        if DEBUG: print(f'insert_cycle_T()')

        llc = len(self.longest_cycle0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke and selected cycle share first point at index 0
        if self.snap_bmv1_cycle0: self.reverse_stroke()

        # bridge if stroke ended on another compatible cycle
        cycle1 = get_boundary_cycle(self.snap_bmv1)
        if cycle1 and len(cycle1) == llc:
            self.longest_cycle1 = cycle1
            self.insert_cycle_I()
            return

        # rotate cycle so bme[1] and bme[2] have hovered vert
        # note: if rotated to bme[0] and bme[-1], there might be ambiguity in which side comes first
        idx = next((i for (i, bme) in enumerate(self.longest_cycle0) if self.snap_bmv0 in bme.verts), None)
        idx = (idx - 1) % len(self.longest_cycle0)
        self.longest_cycle0 = self.longest_cycle0[idx:] + self.longest_cycle0[:idx]

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                nspans = round(self.length3D / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create template
        template = [ self.find_point2D(iv / (nverts - 1)) for iv in range(nverts) ]
        # get orientation of stroke to selected cycle
        vx = Vector((1, 0))
        bmvp, bmvn = bmes_get_prevnext_bmvs(self.longest_cycle0, self.snap_bmv0)
        pp, pn = [self.project_bmv(context, bmv) for bmv in [bmvp, bmvn]]
        vpn, vstroke = (pn - pp), (self.stroke2D[-1] - self.stroke2D[0])
        template_len = vstroke.length
        angle = vec_screenspace_angle(vstroke) - vec_screenspace_angle(vpn)

        # use template to build spans
        bmv0 = bme_unshared_bmv(self.longest_cycle0[0], self.longest_cycle0[1])
        bmvs = []
        for i_row, bme in enumerate(self.longest_cycle0):
            pt = self.project_bmv(context, bmv0)

            bmvp, bmvn = bmes_get_prevnext_bmvs(self.longest_cycle0, bmv0)
            if i_row == 0: bmvp, bmvn = bmvn, bmvp
            vpn = self.project_bmv(context, bmvn) - self.project_bmv(context, bmvp)
            bme_angle = vec_screenspace_angle(vpn)
            along = Vector((math.cos(bme_angle + angle), -math.sin(bme_angle + angle)))
            fitted = fit_template2D(template, pt, target=(pt + (along * template_len)))
            cur_bmvs = [bmv0]
            for t in fitted[1:]:
                co = raycast_point_valid_sources(context, t, world=False)
                cur_bmvs.append(self.bm.verts.new(co) if co else None)

            bmvs.append(cur_bmvs)
            bmv0 = bme_other_bmv(bme, bmv0)

        # fill in quads
        bmfs = []
        for i0 in range(llc):
            i1 = (i0 + 1) % len(self.longest_cycle0)
            for j in range(nverts - 1):
                bmv00 = bmvs[i0][j+0]
                bmv01 = bmvs[i0][j+1]
                bmv10 = bmvs[i1][j+0]
                bmv11 = bmvs[i1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = xform_direction(Mi, view_forward_direction(context))
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, [row[-1] for row in bmvs])

        self.cut_count = nspans
        self.show_action = 'T-Loop'
        self.show_count = True
        self.show_is_cycle = False
        self.show_extrapolate_mode = False

    def insert_cycle_I(self, context):
        if DEBUG: print(f'insert_cycle_I()')

        llc = len(self.longest_cycle0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke starts on longest cycle
        if self.snap_bmv0_cycle1:
            self.reverse_stroke()

        # make sure cycles are oriented the same
        mids0 = [bme_midpoint(bme) for bme in self.longest_cycle0]
        mids1 = [bme_midpoint(bme) for bme in self.longest_cycle1]
        mid0, mid1 = sum(mids0, Vector((0,0,0))) / llc, sum(mids1, Vector((0,0,0))) / llc
        d0 = sum(((p0 - mid0).cross(p1 - mid0).normalized() for (p0, p1) in iter_pairs(mids0, True)), Vector((0,0,0)))
        d1 = sum(((p0 - mid1).cross(p1 - mid1).normalized() for (p0, p1) in iter_pairs(mids1, True)), Vector((0,0,0)))
        if d0.dot(d1) < 0: self.longest_cycle1.reverse()

        # rotate both cycles so stroke hovers both at 0
        cycle0_bme = next((bme0 for (bme0,bme1) in iter_pairs(self.longest_cycle0, True) if bmes_shared_bmv(bme0, bme1) == self.snap_bmv0), None)
        cycle1_bme = next((bme0 for (bme0,bme1) in iter_pairs(self.longest_cycle1, True) if bmes_shared_bmv(bme0, bme1) == self.snap_bmv1), None)
        idx = self.longest_cycle0.index(cycle0_bme)
        self.longest_cycle0 = self.longest_cycle0[idx:] + self.longest_cycle0[:idx]
        idx = self.longest_cycle1.index(cycle1_bme)
        self.longest_cycle1 = self.longest_cycle1[idx:] + self.longest_cycle1[:idx]

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                nspans = round(self.length3D / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create template
        pt2D = self.find_point2D(0)
        template = [
            self.find_point2D(iv / (nverts - 1)) - pt2D
            for iv in range(nverts)
        ]
        template_length = (self.find_point2D(1) - pt2D).length

        # use template to build spans
        bmvs = []
        bmv0 = bme_unshared_bmv(self.longest_cycle0[0], self.longest_cycle0[1])
        bmv1 = bme_unshared_bmv(self.longest_cycle1[0], self.longest_cycle1[1])
        for (bme0, bme1) in zip(self.longest_cycle0, self.longest_cycle1):
            pt0, pt1 = self.project_bmv(context, bmv0), self.project_bmv(context, bmv1)
            scale = (pt1 - pt0).length / template_length
            fitted = fit_template2D(template, pt0, target=pt1)
            cur_bmvs = [bmv0]
            for t in fitted[1:-1]:
                co = raycast_point_valid_sources(context, t, world=False)
                cur_bmvs.append(self.bm.verts.new(co) if co else None)
            cur_bmvs.append(bmv1)
            bmvs.append(cur_bmvs)
            bmv0 = bme_other_bmv(bme0, bmv0)
            bmv1 = bme_other_bmv(bme1, bmv1)

        row0, row1 = [row[0].co for row in bmvs], [row[-1].co for row in bmvs]
        mid0, mid1 = sum(row0, Vector((0,0,0))) / len(row0), sum(row1, Vector((0,0,0))) / len(row1)
        rad0, rad1 = max(row0, key=lambda pt:(mid0 - pt).length), max(row1, key=lambda pt:(mid1 - pt).length)
        i_larger = 0 if rad0 > rad1 else -1

        # fill in quads
        bmfs = []
        for i0 in range(llc):
            i1 = (i0 + 1) % llc
            for j in range(nverts - 1):
                bmv00 = bmvs[i0][j+0]
                bmv01 = bmvs[i0][j+1]
                bmv10 = bmvs[i1][j+0]
                bmv11 = bmvs[i1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = xform_direction(Mi, view_forward_direction(context))
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, [row[i_larger] for row in bmvs])

        self.cut_count = nspans
        self.show_action = 'I-Loop'
        self.show_count = True
        self.show_is_cycle = False
        self.show_extrapolate_mode = False


    ##############################################################################
    # strip bridging insertions

    def insert_strip_T(self, context):
        if DEBUG: print(f'insert_strip_T()')

        llc = len(self.longest_strip0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke and selected strip share first point at index 0
        if self.snap_bmv1_strip0:
            self.reverse_stroke()

        # bridge if stroke ended on another compatible strip
        strips = get_boundary_strips(self.snap_bmv1)
        if strips and len(strips) in {1, 2}:
            # determine where on selected stroke crossed
            inds = [i for (i,bme) in enumerate(self.longest_strip0) if bme in self.snap_bmv0.link_edges]
            if len(inds) == 1:
                if inds[0] == 0: count0, count1 = 0, llc
                else:            count0, count1 = llc, 0
            else:                count0, count1 = inds[0] + 1, llc - (inds[0] + 1)

            # make sure strips and selected are pointing in same direction
            if len(self.longest_strip0) == 1:
                if self.snap_bmv0 == self.longest_strip0[0].verts[0]:
                    pt00 = self.project_pt(context, self.longest_strip0[0].verts[0].co)
                    pt01 = self.project_pt(context, self.longest_strip0[0].verts[1].co)
                else:
                    pt00 = self.project_pt(context, self.longest_strip0[0].verts[1].co)
                    pt01 = self.project_pt(context, self.longest_strip0[0].verts[0].co)
            else:
                pt00 = self.project_pt(context, bme_midpoint(self.longest_strip0[0]))
                pt01 = self.project_pt(context, bme_midpoint(self.longest_strip0[1]))
            vec01 = pt01 - pt00
            if len(strips) == 1:
                strips = [[], strips[0]] if count0 == 0 else [strips[0], []]
            elif len(strips) == 2:
                bmv0, bmv1 = bme_unshared_bmv(strips[0][0], strips[1][0]), bme_unshared_bmv(strips[1][0], strips[0][0])
                pt10, pt11 = self.project_bmv(context, bmv0), self.project_bmv(context, bmv1)
                if vec01.dot(pt10 - pt00) > vec01.dot(pt11 - pt00):
                    strips = [strips[1], strips[0]]

            if len(strips[0]) >= count0 and len(strips[1]) >= count1:
                strip0, strip1 = strips[0], strips[1]
                max0 = len(strip0) - count0
                max1 = len(strip1) - count1
                self.min_bridging_offset = -max1
                self.max_bridging_offset = max0
                self.show_bridging_offset = True
                self.bridging_offset = clamp(self.bridging_offset, self.min_bridging_offset, self.max_bridging_offset)
                full_strip = strip0[::-1] + strip1
                idx = len(strip0) - self.bridging_offset
                strip = full_strip[idx-count0:idx+count1]
                assert len(strip) == llc
                self.longest_strip1 = strip
                self.insert_strip_I(context)
                return


        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                nspans = round(self.length3D / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        if self.extrapolate_mode == 'FOLLOW':
            # create template
            template = [ self.find_point3D(iv / (nverts - 1)) for iv in range(nverts) ]

            s0, s1 = template[:2]
            d10 = (s1 - s0).normalized()
            n0 = (Mi @ bvec_vector_to_bvec4(nearest_normal_valid_sources(context, (M @ bvec_point_to_bvec4(s0)).xyz))).xyz
            frame0 = Frame(s0, y=d10, z=n0)
            bmv = bme_unshared_bmv(self.longest_strip0[0], self.longest_strip0[1]) if len(self.longest_strip0) > 1 else self.longest_strip0[0].verts[0]
            prep_data = [(bmv, frame0.w2l_point(bmv.co))]
            for bme in self.longest_strip0:
                bmv = bme_other_bmv(bme, bmv)
                prep_data += [(bmv, frame0.w2l_point(bmv.co))]
            bmvs = [[bmv for (bmv, _) in prep_data]]
            for (s0, s1, s2) in zip(template[:-1], template[1:], template[2:] + [template[-1]]):
                d20 = (s2 - s0).normalized()
                n1 = (Mi @ bvec_vector_to_bvec4(nearest_normal_valid_sources(context, (M @ bvec_point_to_bvec4(s1)).xyz))).xyz
                frame1 = Frame(s1, y=d20, z=n1)
                cur_bmvs = []
                for bmv, co_frame in prep_data:
                    co_local = frame1.l2w_point(co_frame)
                    co_local = (Mi @ bvec_point_to_bvec4(nearest_point_valid_sources(context, (M @ bvec_point_to_bvec4(co_local)).xyz))).xyz
                    cur_bmvs.append( self.bm.verts.new(co_local) )
                bmvs.append(cur_bmvs)
            #sel_idx = next((i for (i,bmv) in enumerate(bmvs[0]) if bmv == self.snap_bmv0), -1)
            #bmvs_select = [row[sel_idx] for row in bmvs]
            bmvs_select = bmvs[-1]

            # rotate bmvs so bmvs[*][0] is original selected geometry instead of bmvs[0][*]
            bmvs = [
                [ bmvs[i][j] for i in range(len(bmvs)) ]
                for j in range(len(bmvs[0]))
            ]

        else:
            # create template
            template = [ self.find_point2D(iv / (nverts - 1)) for iv in range(nverts) ]

            # get orientation of stroke to selected strip
            vx = Vector((1, 0))
            bmvp, bmvn = bmes_get_prevnext_bmvs(self.longest_strip0, self.snap_bmv0)
            pp, pn = [self.project_bmv(context, bmv) for bmv in [bmvp, bmvn]]
            vpn, vstroke = (pn - pp), (self.stroke2D[-1] - self.stroke2D[0])
            template_len = vstroke.length
            angle = vec_screenspace_angle(vstroke) - vec_screenspace_angle(vpn)

            # use template to build spans
            bmv0 = bme_unshared_bmv(self.longest_strip0[0], self.longest_strip0[1]) if len(self.longest_strip0) > 1 else self.longest_strip0[0].verts[0]
            bmvs = []
            for i_row, bme in enumerate(self.longest_strip0 + [None]):
                pt = self.project_bmv(context, bmv0)

                if self.extrapolate_mode == 'FAN':
                    bmvp,bmvn = bmes_get_prevnext_bmvs(self.longest_strip0, bmv0)
                    vpn = self.project_bmv(context, bmvn) - self.project_bmv(context, bmvp)
                    bme_angle = vec_screenspace_angle(vpn)
                    along = Vector((math.cos(bme_angle + angle), -math.sin(bme_angle + angle)))
                    fitted = fit_template2D(template, pt, target=(pt + (along * template_len)))
                    cur_bmvs = [bmv0]
                    for t in fitted[1:]:
                        co = raycast_point_valid_sources(context, t, world=False)
                        cur_bmvs.append(self.bm.verts.new(co) if co else None)

                else:
                    cur_bmvs = [bmv0]
                    offset0 = template[0]
                    for offset in template[1:]:
                        co = raycast_point_valid_sources(context, pt + offset - offset0, world=False)
                        cur_bmvs.append(self.bm.verts.new(co) if co else None)

                bmvs.append(cur_bmvs)
                if not bme: break
                bmv0 = bme_other_bmv(bme, bmv0)
            bmvs_select = [row[-1] for row in bmvs]

        side = self.get_mirror_side(bmvs[0][0].co)
        if 0 in side:
            for bmv in bmvs[0]:
                if side[0] == 0: bmv.co.x = 0
                if side[1] == 0: bmv.co.y = 0
                if side[2] == 0: bmv.co.z = 0
        side = self.get_mirror_side(bmvs[-1][0].co)
        if 0 in side:
            for bmv in bmvs[-1]:
                if side[0] == 0: bmv.co.x = 0
                if side[1] == 0: bmv.co.y = 0
                if side[2] == 0: bmv.co.z = 0
        side = self.get_mirror_side(self.stroke3D[-1])
        if 0 in side:
            for row in bmvs:
                if side[0] == 0: row[-1].co.x = 0
                if side[1] == 0: row[-1].co.y = 0
                if side[2] == 0: row[-1].co.z = 0

        # # fill in quads
        # bmfs = []
        # for i in range(llc):
        #     for j in range(nverts - 1):
        #         bmv00 = bmvs[i+0][j+0]
        #         bmv01 = bmvs[i+0][j+1]
        #         bmv10 = bmvs[i+1][j+0]
        #         bmv11 = bmvs[i+1][j+1]
        #         if not (bmv00 and bmv01 and bmv10 and bmv11): continue
        #         bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
        #         bmfs.append(bmf)
        # fill in quads
        bmfs = []
        for i in range(len(bmvs)-1):
            for j in range(len(bmvs[i]) - 1):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = xform_direction(Mi, view_forward_direction(context))
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs_select)

        self.cut_count = nspans
        self.show_action = 'T-Strip'
        self.show_count = True
        self.show_is_cycle = False
        self.show_extrapolate_mode = True


    def insert_strip_I(self, context):
        if DEBUG: print(f'insert_strip_I()')

        llc = len(self.longest_strip0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke starts on longest strip
        i_select = -1
        if self.snap_bmv0_strip1:
            i_select = 0
            self.stroke2D.reverse()
            self.stroke3D.reverse()
            self.snap_bmv0, self.snap_bmv1 = self.snap_bmv1, self.snap_bmv0
            self.snap_bmv0_strip0, self.snap_bmv0_strip1 = self.snap_bmv0_strip1, self.snap_bmv0_strip0
            self.snap_bmv1_strip0, self.snap_bmv1_strip1 = self.snap_bmv1_strip1, self.snap_bmv1_strip0

        v0 = bme_midpoint(self.longest_strip0[-1]) - bme_midpoint(self.longest_strip0[0])
        v1 = bme_midpoint(self.longest_strip1[-1]) - bme_midpoint(self.longest_strip1[0])
        if v1.dot(v0) < 0:
            self.longest_strip1.reverse()

        if self.untwist_bridge:
            self.longest_strip1.reverse()

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                nspans = round(self.length3D / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create template
        pt2D = self.find_point2D(0)
        template = [
            self.find_point2D(iv / (nverts - 1)) - pt2D
            for iv in range(nverts)
        ]
        template_length = (self.find_point2D(1) - pt2D).length

        # use template to build spans
        bmvs = []
        if llc > 1:
            bmv0 = bme_unshared_bmv(self.longest_strip0[0], self.longest_strip0[1])
            bmv1 = bme_unshared_bmv(self.longest_strip1[0], self.longest_strip1[1])
        else:
            bme0, bme1 = self.longest_strip0[0], self.longest_strip1[0]
            bmv0 = bme0.verts[0]
            bmv1 = bme1.verts[0] if bme_vector(bme0).dot(bme_vector(bme1)) > 0 else bme1.verts[1]
        i_sel_row = 0
        for i_row, (bme0, bme1) in enumerate(zip(self.longest_strip0 + [None], self.longest_strip1 + [None])):
            pt0 = self.project_bmv(context, bmv0)
            pt1 = self.project_bmv(context, bmv1)
            fitted = fit_template2D(template, pt0, target=pt1)
            #scale = (pt1 - pt0).length / template_length
            cur_bmvs = [bmv0]
            for t in fitted[1:-1]:
                # co = raycast_point_valid_sources(context, pt0 + offset * scale, world=False)
                co = raycast_point_valid_sources(context, t, world=False)
                cur_bmvs.append(self.bm.verts.new(co) if co else None)
            cur_bmvs.append(bmv1)
            bmvs.append(cur_bmvs)
            if bmv0 == self.snap_bmv0: i_sel_row = i_row
            if not bme0: break
            bmv0 = bme_other_bmv(bme0, bmv0)
            bmv1 = bme_other_bmv(bme1, bmv1)

        # fill in quads
        bmfs = []
        for i in range(llc):
            for j in range(nverts - 1):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = xform_direction(Mi, view_forward_direction(context))
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, [row[i_select] for row in bmvs])

        self.cut_count = nspans
        self.show_action = 'I-Strip'
        self.show_count = True
        self.show_is_cycle = False
        self.show_extrapolate_mode = False
        self.show_untwist_bridge = True


    def insert_strip_C(self, context):
        if DEBUG: print(f'insert_strip_C()')

        llc = len(self.longest_strip0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke and selected strip point in same direction
        v_stroke = self.stroke3D[-1] - self.stroke3D[0]
        if llc == 1:
            sel_bmv0, sel_bmv1 = self.longest_strip0[0].verts
            v_selected = sel_bmv1.co - sel_bmv0.co
        else:
            co0 = bme_midpoint(self.longest_strip0[0])
            co1 = bme_midpoint(self.longest_strip0[-1])
            v_selected = co1 - co0
        if v_stroke.dot(v_selected) < 0:
            # pointing opposite directions
            # print('REVERSING!!!!!!!!!!!!!!!!')
            self.stroke2D.reverse()
            self.stroke3D.reverse()

        # find two corners, which are the sharpest points
        idx0, idx1 = find_sharpest_indices(self.stroke2D)
        stroke0, stroke1, stroke2 = self.stroke2D[:idx0], self.stroke2D[idx0:idx1], self.stroke2D[idx1:]
        stroke2.reverse()
        length0 = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke0, False))
        length1 = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke1, False))
        length2 = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke2, False))

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                nspans = round(min(length0, length2) / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                l0 = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke3D[:idx0], False))
                l2 = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke3D[idx1:], False))
                nspans = round(min(l0, l2) / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create templates
        template0 = [find_point_at(stroke0, False, iv / (nverts-1)) for iv in range(nverts)]
        template2 = [find_point_at(stroke2, False, iv / (nverts-1)) for iv in range(nverts)]

        # build spans
        bmv0 = bme_unshared_bmv(self.longest_strip0[0], self.longest_strip0[1]) if len(self.longest_strip0) > 1 else self.longest_strip0[0].verts[0]
        bmvs = []
        for i, bme in enumerate(self.longest_strip0 + [None]):
            v = i / llc
            pt0 = self.project_bmv(context, bmv0)
            pt1 = find_point_at(stroke1, False, v)
            fitted0 = fit_template2D(template0, pt0, target=pt1)
            fitted2 = fit_template2D(template2, pt0, target=pt1)
            cur_bmvs = [bmv0]
            for (p0, p2) in zip(fitted0[1:], fitted2[1:]):
                p = lerp(v, p0, p2)
                co = raycast_point_valid_sources(context, p, world=False)
                cur_bmvs.append(self.bm.verts.new(co) if co else None)
            bmvs.append(cur_bmvs)
            if not bme: break
            bmv0 = bme_other_bmv(bme, bmv0)

        # fill in quads
        bmfs = []
        for i in range(llc):
            for j in range(nverts - 1):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)
        fwd = xform_direction(Mi, view_forward_direction(context))
        check_bmf_normals(fwd, bmfs)

        # select bottom row
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, [row[-1] for row in bmvs])

        self.cut_count = nspans
        self.show_action = 'C-Strip'
        self.show_count = True
        self.show_is_cycle = False
        self.show_extrapolate_mode = False


    def insert_strip_L(self, context):
        if DEBUG: print(f'insert_strip_L()')

        # fallback to insert_strip_T if we cannot make L-shape work
        M, Mi = self.matrix_world, self.matrix_world_inv

        if   self.snap_bmv0_sel and self.snap_bmv1_nosel: pass
        elif self.snap_bmv1_sel and self.snap_bmv0_nosel: self.reverse_stroke()
        else: return self.insert_strip_T(context)

        if self.force_nonstripL: return self.insert_strip_T(context)
        self.show_force_nonstripL = False  # will set to True if we add an L-strip
        self.force_nonstripL = False

        # if snap_bmv0 is in longest strip but not one of the ends, fallback to inserting T
        if len(self.longest_strip0) > 1:
            longest_strip0_bmv0 = bme_unshared_bmv(self.longest_strip0[ 0], self.longest_strip0[ 1])
            longest_strip0_bmv1 = bme_unshared_bmv(self.longest_strip0[-1], self.longest_strip0[-2])
            if self.snap_bmv0 != longest_strip0_bmv0 and self.snap_bmv0 != longest_strip0_bmv1: return self.insert_strip_T(context)
        # if any(self.snap_bmv0 in bme.verts for bme in self.longest_strip0[1:-2]): return self.insert_strip_T(context)

        # see if we can crawl along boundary from bmv1 and reach opposite end of longest_strip0 from bmv0
        # find opposite end of strip from bmv0
        if len(self.longest_strip0) == 1:
            strip_t = self.longest_strip0[:]
            opposite = bme_other_bmv(strip_t[0], self.snap_bmv0)
        else:
            if self.snap_bmv0 in self.longest_strip0[0].verts:
                strip_t = self.longest_strip0[::-1]
            else:
                strip_t = self.longest_strip0[:]
            opposite = bme_unshared_bmv(strip_t[0], strip_t[1])
        # crawl from bmv1 along boundary
        path, processing = {}, [self.snap_bmv1]
        while processing and opposite not in path:
            bmv = processing.pop(0)
            if bmv == self.snap_bmv0: return self.insert_strip_T(context)
            for bme in bmv.link_edges:
                if not bme.hide and (bme.is_wire or bme.is_boundary):
                    bmv_ = bme_other_bmv(bme, bmv)
                    if bmv_ not in path:
                        path[bmv_] = bmv
                        processing.append(bmv_)
        if opposite not in path: return self.insert_strip_T(context)
        strip_l = []
        cur = opposite
        while cur != self.snap_bmv1:
            next_bmv = path[cur]
            strip_l.append(bmvs_shared_bme(cur, next_bmv))
            cur = next_bmv
        llc_tb, llc_lr = len(strip_t)+1, len(strip_l)+1
        # strip_t is path from opposite to start of stroke, and strip_l is path from opposite to end of stroke

        self.show_force_nonstripL = True

        # split stroke into two sides
        idx = find_sharpest_index(self.stroke2D)
        stroke_r, stroke_b = self.stroke2D[:idx], self.stroke2D[idx:]
        stroke_b.reverse()
        length_r = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke_r, False))
        length_b = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke_b, False))

        # create templates
        strip_t_bmvs = get_strip_bmvs(strip_t, opposite)
        strip_l_bmvs = get_strip_bmvs(strip_l, opposite)
        template_t = [self.project_bmv(context, bmv) for bmv in strip_t_bmvs]
        template_l = [self.project_bmv(context, bmv) for bmv in strip_l_bmvs]
        template_b = [find_point_at(stroke_b, False, iv / (llc_tb-1)) for iv in range(llc_tb)]
        template_r = [find_point_at(stroke_r, False, iv / (llc_lr-1)) for iv in range(llc_lr)]

        # build spans
        bmvs = [[None for _ in range(llc_tb)] for _ in range(llc_lr)]
        for i_tb in range(llc_tb):
            pt, pb = template_t[i_tb], template_b[i_tb]
            fitted_l = fit_template2D(template_l, pt, target=pb)
            fitted_r = fit_template2D(template_r, pt, target=pb)
            for i_lr in range(llc_lr):
                if i_tb == 0:
                    bmvs[i_lr][i_tb] = strip_l_bmvs[i_lr]
                elif i_lr == 0:
                    bmvs[i_lr][i_tb] = strip_t_bmvs[i_tb]
                else:
                    v = i_tb / (llc_tb - 1)
                    p = lerp(v, fitted_l[i_lr], fitted_r[i_lr])
                    co = raycast_point_valid_sources(context, p, world=False)
                    bmvs[i_lr][i_tb] = self.bm.verts.new(co) if co else None

        # fill in quads
        bmfs = []
        for i in range(llc_lr - 1):
            for j in range(llc_tb - 1):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)
        fwd = xform_direction(Mi, view_forward_direction(context))
        check_bmf_normals(fwd, bmfs)

        # select bottom row
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[-1])

        self.show_action = 'L-Strip'
        self.show_is_cycle = False
        self.show_extrapolate_mode = False
        self.show_count = False


    def insert_strip_equals(self, context):
        if DEBUG: print(f'insert_strip_equals()')

        M, Mi = self.matrix_world, self.matrix_world_inv

        ###########################
        # build templates

        # find top-left and top-right corners
        if len(self.longest_strip0) > 1:
            bmv_tl  = bme_unshared_bmv(self.longest_strip0[ 0], self.longest_strip0[ 1])
            bmv_tl1 = bmes_shared_bmv( self.longest_strip0[ 0], self.longest_strip0[ 1])
            bmv_tr  = bme_unshared_bmv(self.longest_strip0[-1], self.longest_strip0[-2])
            bmv_tr1 = bmes_shared_bmv( self.longest_strip0[-1], self.longest_strip0[-2])
            if len(self.longest_strip0) % 2 == 0:
                i0 = len(self.longest_strip0) // 2 - 1
            else:
                i0 = len(self.longest_strip0) // 2
            i1 = i0 + 1
            bmv_tmid0 = bme_unshared_bmv(self.longest_strip0[i0], self.longest_strip0[i1])
            bmv_tmid1 = bmes_shared_bmv( self.longest_strip0[i0], self.longest_strip0[i1])
        else:
            bmv_tl, bmv_tr = self.longest_strip0[0].verts
            bmv_tl1, bmv_tr1 = bmv_tr, bmv_tl
            bmv_tmid0, bmv_tmid1 = bmv_tl, bmv_tr

        # build template for top edge (selected strip)
        strip_t_bmvs = get_strip_bmvs(self.longest_strip0, bmv_tl)
        llc_tb = len(strip_t_bmvs)
        template_t = [self.project_bmv(context, bmv) for bmv in strip_t_bmvs]

        # make sure stroke points in correct direction, otherwise generated geo will twist and self-intersect
        vec_tltr, vec_tls0, vec_tls1 = bmv_tr.co - bmv_tl.co, self.stroke3D[0] - bmv_tl.co, self.stroke3D[-1] - bmv_tl.co
        if segment2D_intersection(self.project_bmv(context, bmv_tl), self.stroke2D[0], self.project_bmv(context, bmv_tr), self.stroke2D[-1]):
            self.reverse_stroke()
        #if vec_tltr.dot(vec_tls0) > vec_tltr.dot(vec_tls1): self.reverse_stroke()

        if self.mirror and self.mirror_clip:
            tl_mirror, tr_mirror = self.get_mirror_side(bmv_tl.co), self.get_mirror_side(bmv_tr.co)
            bl_mirror, br_mirror = self.get_mirror_side(self.stroke3D[0]), self.get_mirror_side(self.stroke3D[-1])
            left_mirror_snap  = set(a for (tl,bl,a) in zip(tl_mirror, bl_mirror, 'xyz') if (tl == 0 == bl))
            right_mirror_snap = set(a for (tr,br,a) in zip(tr_mirror, br_mirror, 'xyz') if (tr == 0 == br))
        else:
            left_mirror_snap, right_mirror_snap = set(), set()


        # build template for bottom edge (stroke)
        template_b = [find_point_at(self.stroke2D, False, iv/(llc_tb-1)) for iv in range(llc_tb)]

        # find left and right sides
        template_l, strip_l_bmvs = None, None
        template_r, strip_r_bmvs = None, None
        if self.snap_bmv0_nosel: il, strip_l_bmvs = self.crawl_boundary({ bmv_tl }, self.snap_bmv0)
        if self.snap_bmv1_nosel: ir, strip_r_bmvs = self.crawl_boundary({ bmv_tr }, self.snap_bmv1)
        if strip_l_bmvs and strip_r_bmvs and bool(set(strip_r_bmvs[:il]) & set(strip_l_bmvs[:ir])):
            # two side strips have overlapping edges, so set both to None
            strip_l_bmvs, strip_r_bmvs = None, None
        if strip_l_bmvs and strip_r_bmvs:
            if not self.initial and self.cut_count is not None:
                ll = max(1, min(self.fixed_span_count, len(strip_l_bmvs)-1))
                lr = max(1, min(self.fixed_span_count, len(strip_r_bmvs)-1))
                ll, lr = min(ll, lr), min(ll, lr)
            else:
                ll, lr = min(il, ir)-1, min(il, ir)-1
            strip_l_bmvs, strip_r_bmvs = strip_l_bmvs[:ll+1], strip_r_bmvs[:lr+1]
            template_b = fit_template2D(template_b, self.project_bmv(context, strip_l_bmvs[-1]), target=self.project_bmv(context, strip_r_bmvs[-1]))
            template_l = [self.project_bmv(context, bmv) for bmv in strip_l_bmvs]
            template_r = [self.project_bmv(context, bmv) for bmv in strip_r_bmvs]
            llc_lr = len(strip_l_bmvs)
        elif strip_l_bmvs and not strip_r_bmvs:
            if not self.initial and self.cut_count is not None:
                ll = max(1, min(self.fixed_span_count, len(strip_l_bmvs)-1))
            else:
                ll = il - 1
            pt_prev = self.project_bmv(context, strip_l_bmvs[il-1])
            strip_l_bmvs = strip_l_bmvs[:ll+1]
            pt_next = self.project_bmv(context, strip_l_bmvs[-1])
            vec_diff = pt_next - pt_prev
            template_b = [pt+vec_diff for pt in template_b]
            template_l = [self.project_bmv(context, bmv) for bmv in strip_l_bmvs]
            llc_lr = len(strip_l_bmvs)
        elif strip_r_bmvs and not strip_l_bmvs:
            if not self.initial and self.cut_count is not None:
                lr = max(1, min(self.fixed_span_count, len(strip_r_bmvs)-1))
            else:
                lr = ir - 1
            pt_prev = self.project_bmv(context, strip_r_bmvs[ir-1])
            strip_r_bmvs = strip_r_bmvs[:lr+1]
            pt_next = self.project_bmv(context, strip_r_bmvs[-1])
            vec_diff = pt_next - pt_prev
            template_b = [pt+vec_diff for pt in template_b]
            template_r = [self.project_bmv(context, bmv) for bmv in strip_r_bmvs]
            llc_lr = len(strip_r_bmvs)
        if not template_l and not template_r:
            # determine number of spans
            match self.span_insert_mode:
                case 'BRUSH':
                    # find closest distance between selected and stroke
                    closest_distance2D = min(
                        (s - self.project_bmv(context, bmv)).length
                        for s in self.stroke2D
                        for bme in self.longest_strip0
                        for bmv in bme.verts
                    )
                    nspans = round(closest_distance2D / (2 * self.radius))
                case 'FIXED':
                    nspans = self.fixed_span_count
                case 'AVERAGE':
                    closest_distance3D = min(
                        (s - bmv.co).length
                        for s in self.stroke3D
                        for bme in self.longest_strip0
                        for bmv in bme.verts
                    )
                    nspans = round(closest_distance3D / self.average_length)
                case _:
                    assert False, f'Unhandled {self.span_insert_mode=}'
            nspans = max(1, nspans)
            llc_lr = nspans + 1
        pt_tl, pt_tr = self.project_bmv(context, bmv_tl), self.project_bmv(context, bmv_tr)
        pt_tl1, pt_tr1 = self.project_bmv(context, bmv_tl1), self.project_bmv(context, bmv_tr1)
        pt_tmid0, pt_tmid1 = self.project_bmv(context, bmv_tmid0), self.project_bmv(context, bmv_tmid1)
        pt_bl, pt_br = self.stroke2D[0], self.stroke2D[-1]
        if len(template_b) == 1:
            pt_bl1 = pt_br
            pt_br1 = pt_bl
            pt_bmid0 = pt_bl
            pt_bmid1 = pt_br
        else:
            pt_bl1 = template_b[1]
            pt_br1 = template_b[-2]
            i0 = len(template_b) // 2
            i1 = min(i0 + 1, len(template_b) -1)
            pt_bmid0 = template_b[i0]
            pt_bmid1 = template_b[i1]
        vec_tmid, vec_bmid = pt_tmid1 - pt_tmid0, pt_bmid1 - pt_bmid0
        vec_tbmid = pt_bmid0 - pt_tmid0
        negate = (Vector((vec_tmid.y, -vec_tmid.x)).dot(vec_tbmid) < 0)
        def get_t(i):
            t = i / (llc_lr - 1)
            return interpolate_cubic(0, self.smooth_density0, self.smooth_density1, 1.0, t)
        if not template_l:
            pt_lt, pt_lb = lerp(0.25, pt_tl, pt_bl), lerp(0.25, pt_bl, pt_tl)
            vec_lt, vec_lb = (pt_lt - pt_tl), (pt_lb - pt_bl)
            dir_lt, dir_lb = vec_lt.normalized(), vec_lb.normalized()
            vec_t, vec_b = pt_tl1 - pt_tl, pt_bl1 - pt_bl
            dir_t_ortho, dir_b_ortho = Vector((vec_t.y, -vec_t.x)).normalized(), Vector((-vec_b.y, vec_b.x)).normalized()
            if negate:
                dir_t_ortho.negate()
                dir_b_ortho.negate()
            angle_t = math.asin(clamp(dir_lt.x * dir_t_ortho.y - dir_lt.y * dir_t_ortho.x, -1, 1)) * self.smooth_angle
            angle_b = math.asin(clamp(dir_lb.x * dir_b_ortho.y - dir_lb.y * dir_b_ortho.x, -1, 1)) * self.smooth_angle
            vec_lt = Vector((
                vec_lt.x * math.cos(angle_t) - vec_lt.y * math.sin(angle_t),
                vec_lt.x * math.sin(angle_t) + vec_lt.y * math.cos(angle_t),
            ))
            vec_lb = Vector((
                vec_lb.x * math.cos(angle_b) - vec_lb.y * math.sin(angle_b),
                vec_lb.x * math.sin(angle_b) + vec_lb.y * math.cos(angle_b),
            ))
            pt_lt, pt_lb = pt_tl + vec_lt, pt_bl + vec_lb
            #template_l = [lerp(i/(llc_lr-1), pt_tl, pt_bl) for i in range(llc_lr)]
            template_l = [interpolate_cubic(pt_tl, pt_lt, pt_lb, pt_bl, get_t(i)) for i in range(llc_lr)]
            self.show_smoothness = True
        if not template_r:
            pt_rt, pt_rb = lerp(0.25, pt_tr, pt_br), lerp(0.25, pt_br, pt_tr)
            vec_rt, vec_rb = (pt_rt - pt_tr), (pt_rb - pt_br)
            dir_rt, dir_rb = vec_rt.normalized(), vec_rb.normalized()
            dir_t, dir_b = (pt_tr1 - pt_tr).normalized(), (pt_br1 - pt_br).normalized()
            dir_t_ortho, dir_b_ortho = Vector((-dir_t.y, dir_t.x)).normalized(), Vector((dir_b.y, -dir_b.x)).normalized()
            if negate:
                dir_t_ortho.negate()
                dir_b_ortho.negate()
            angle_t = math.asin(clamp(dir_rt.x * dir_t_ortho.y - dir_rt.y * dir_t_ortho.x, -1, 1))
            angle_b = math.asin(clamp(dir_rb.x * dir_b_ortho.y - dir_rb.y * dir_b_ortho.x, -1, 1))
            angle_t *= self.smooth_angle
            angle_b *= self.smooth_angle
            vec_rt = Vector((
                vec_rt.x * math.cos(angle_t) - vec_rt.y * math.sin(angle_t),
                vec_rt.x * math.sin(angle_t) + vec_rt.y * math.cos(angle_t),
            ))
            vec_rb = Vector((
                vec_rb.x * math.cos(angle_b) - vec_rb.y * math.sin(angle_b),
                vec_rb.x * math.sin(angle_b) + vec_rb.y * math.cos(angle_b),
            ))
            pt_rt, pt_rb = pt_tr + vec_rt, pt_br + vec_rb
            # template_r = [lerp(i/(llc_lr-1), pt_tr, pt_br) for i in range(llc_lr)]
            template_r = [interpolate_cubic(pt_tr, pt_rt, pt_rb, pt_br, get_t(i)) for i in range(llc_lr)]
            self.show_smoothness = True

        ######################
        # build spans
        bmvs = [[None for _ in range(llc_tb)] for _ in range(llc_lr)]
        for i_tb in range(llc_tb):
            pt, pb = template_t[i_tb], template_b[i_tb]
            fitted_l = fit_template2D(template_l, pt, target=pb)
            fitted_r = fit_template2D(template_r, pt, target=pb)
            at_l, at_r = (i_tb == 0), (i_tb == llc_tb - 1)
            for i_lr in range(llc_lr):
                at_t, at_b = (i_lr == 0), (i_lr == llc_lr - 1)
                if   at_t:                                   bmvs[i_lr][i_tb] = strip_t_bmvs[i_tb]
                elif at_l and strip_l_bmvs:                  bmvs[i_lr][i_tb] = strip_l_bmvs[i_lr]
                elif at_r and strip_r_bmvs:                  bmvs[i_lr][i_tb] = strip_r_bmvs[i_lr]
                elif at_b and at_l and self.snap_bmv0_nosel: bmvs[i_lr][i_tb] = self.snap_bmv0
                elif at_b and at_r and self.snap_bmv1_nosel: bmvs[i_lr][i_tb] = self.snap_bmv1
                else:
                    v = i_tb / (llc_tb - 1)
                    p = lerp(v, fitted_l[i_lr], fitted_r[i_lr])
                    co = raycast_point_valid_sources(context, p, world=False)
                    if left_mirror_snap:
                        zs = 0 if at_l else 1 # (i_tb / (llc_tb - 1))**0.25
                        if 'x' in left_mirror_snap: co.x *= zs
                        if 'y' in left_mirror_snap: co.y *= zs
                        if 'z' in left_mirror_snap: co.z *= zs
                    if right_mirror_snap and at_r:
                        zs = 0 if at_r else 1 # 1 - (i_tb / (llc_tb - 1))**0.25
                        if 'x' in right_mirror_snap: co.x *= zs
                        if 'y' in right_mirror_snap: co.y *= zs
                        if 'z' in right_mirror_snap: co.z *= zs
                    bmvs[i_lr][i_tb] = self.bm.verts.new(co) if co else None

        ######################
        # fill in quads
        bmfs = list(filter(bool, [
            self.create_quad(bmvs[i+0][j+0], bmvs[i+0][j+1], bmvs[i+1][j+1], bmvs[i+1][j+0])
            for i in range(llc_lr - 1)
            for j in range(llc_tb - 1)
        ]))
        fwd = xform_direction(Mi, view_forward_direction(context))
        check_bmf_normals(fwd, bmfs)

        # select bottom row
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[-1])

        self.show_action = 'Equals-Strip'
        self.show_extrapolate_mode = False
        self.cut_count = llc_lr - 1
        self.show_count = True # not strip_l_bmvs and not strip_r_bmvs
        self.show_is_cycle = False


    def create_quad(self, *fbmvs):
        if not all(fbmvs):
            print(f'Warning: at least one BMVert is None!  Not creating a quad!')
            return None

        ofbmvs = fbmvs
        fbmvs = tuple(bmv for (i, bmv) in enumerate(fbmvs) if fbmvs.index(bmv) == i)

        if len(fbmvs) < 3:
            print(f'Warning: attempted creating a face that has only {len(fbmvs)} BMVerts!  Not creating a quad!')
            return None

        if len(fbmvs) != 4:
            print(f'Warning: creating a BMFace with only {len(fbmvs)} BMVerts!')

        try:
            return self.bm.faces.new(fbmvs)
        except Exception as e:
            print(f'Caught and ignoring Exception {e} while attempting to create BMFace ({ofbmvs}, {fbmvs})')

        return None

    def crawl_boundary(self, bmvs_from, bmv_to):
        path, processing = {bmv_to:None}, deque([bmv_to])
        while processing:
            bmv = processing.popleft()
            if bmv in bmvs_from: break
            for bme in bmv.link_edges:
                if bme.hide or not (bme.is_wire or bme.is_boundary): continue
                bmv_next = bme_other_bmv(bme, bmv)
                if bmv_next in path: continue
                path[bmv_next] = bmv
                processing.append(bmv_next)
        else:
            return 0, None
        # bmv is now bmv_from
        bmvs = []
        while bmv:
            bmvs.append(bmv)
            bmv = path[bmv]
        l = len(bmvs)
        bmv = bmvs[-1]
        while True:
            bmvs_next = [bme_other_bmv(bme, bmv) for bme in bmv.link_edges if not bme.hide and (bme.is_wire or bme.is_boundary)]
            bmvs_next = [bmv_ for bmv_ in bmvs_next if bmv_ not in bmvs]
            if len(bmvs_next) != 1:
                break
            bmv = bmvs_next[0]
            bmvs += [bmv]
        return (l, bmvs)
