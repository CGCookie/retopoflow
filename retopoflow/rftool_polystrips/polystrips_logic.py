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
from mathutils.bvhtree import BVHTree
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
    has_mirror_x, has_mirror_y, has_mirror_z, mirror_threshold,
)
from ..common.bmesh_maths import (
    find_point_at,
    find_closest_point,
    find_sharpest_indices,
    find_sharpest_index,
    compute_n,
    bmes_get_prevnext_bmvs,
    get_strip_bmvs,
    orient_bmf_normals,
    fit_template2D,
    vec_screenspace_angle,
    vecs_screenspace_angle,
    get_boundary_cycle,
    get_boundary_strips,
    get_longest_strip_cycle,
    generate_point_inside_bmf,
)
from ..common.raycast import raycast_point_valid_sources, nearest_point_valid_sources, nearest_normal_valid_sources
from ..common.accel import SourceCache
from ..common.snapping import source_snap_radius, source_snap_settings, fold_crease
from ..common.maths import (
    lerp,
    point_to_bvec3,
    vector_to_bvec3,
    point_to_bvec4,
    distance_point_linesegment,
    distance_point_bmedge,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bezier import interpolate_cubic
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import (
    closest_point_segment,
    segment2D_intersection,
    clamp, sign,
    Direction,
    closest_points_segments,
    sign_threshold,
)
from ...addon_common.common.utils import iter_pairs, enumerate_reversed, enumerate_direction, dedup

import math
from itertools import chain

DEBUG_SIDEJOIN = False


r'''

Desmos demo: https://www.desmos.com/geometry/okxgsddxk2

NOT HANDLING CYCLIC STROKES, YET

'''



def trim_stroke_to_bmf(stroke, bmf, from_start, limit_bmes=None):
    if not bmf: return None

    # find the first stroke pt outside the snapped bmf
    point_inside_bmf = generate_point_inside_bmf(bmf)
    i = next((i for (i,pt) in enumerate_direction(stroke, from_start) if not point_inside_bmf(pt)), None)
    if i is None: return {'error': 'stroke totally inside the hovered face'}

    # split stroke into inside bmf and outside bmf
    if from_start: inside,  outside = stroke[:i], stroke[i:]
    else:          outside, inside  = stroke[:i], stroke[i:]

    # Connect to the edge the stroke entered through, not whichever edge the end happens to drift closest to.
    if from_start: # stroke begins inside the face and exits
        search = inside[-1:] + outside[:1]
    else: # stroke enters and ends inside
        search = inside[:2]
    search = search or ([stroke[0]] if from_start else [stroke[-1]])

    # find closest bme of bmf to search part of stroke
    if limit_bmes:
        bmes = limit_bmes
    else:
        bmes = bmf.edges
    if not bmes: return None
    bme = min(bmes, key=lambda bme: min(distance_point_bmedge(pt, bme) for pt in search))
    return {
        'error': None,
        'stroke': outside,
        'bmf': bmf,
        'bme': bme,
        'bme.center': bme_midpoint(bme),
        'bme.radius': bme_length(bme) / 2,
    }

def warp_stroke(context, stroke, end0, end1, fn_snap_point):
    if not stroke or (not end0 and not end1):
        return stroke
    s0, s1 = stroke[0], stroke[-1]
    if end0 and not end1:
        offset = end0 - s0
        return [ fn_snap_point(context, pt + offset) for pt in stroke ]
    elif not end0 and end1:
        offset = end1 - s1
        return [ fn_snap_point(context, pt + offset) for pt in stroke ]
    ec, es = (end0 + end1) / 2, (end0 - end1).length
    sc, ss = (s0 + s1) / 2, (s0 - s1).length
    scale = es / ss
    return [ fn_snap_point(context, ec + (pt - sc) * scale) for pt in stroke ]

def stroke_angles(stroke, width, split_angle, fn_snap_normal):
    # convert radians to degrees
    split_angle = math.degrees(split_angle)

    # determine where stroke angles very strongly
    l = []
    for (i, p) in enumerate(stroke):
        pp = next((pp for pp in stroke[i::-1] if (p - pp).length >= width), None)
        pn = next((pn for pn in stroke[i:]    if (p - pn).length >= width), None)
        if not pp or not pn: continue

        n = Direction(fn_snap_normal(p))
        np, nn = Direction(fn_snap_normal(pp)), Direction(fn_snap_normal(pn))
        if math.degrees(np.angle_between(nn)) > split_angle: continue
        dp, dn = Direction(p - pp), Direction(pn - p)
        angle = math.degrees(dp.signed_angle_between(dn, n))
        if abs(angle) < split_angle: continue
        l.append((i, p, int(angle)))

    # find largest angle of connected "islands" (run of points within width of neighboring points)
    biggest = []
    for (_, pp, _), (i, p, a) in zip(l[:-1], l[1:]):
        if not biggest or (pp - p).length >= width:
            # either first point (and therefore biggest by default) or too far away from previous (disconnected)
            biggest += [(i, a)]
        else:
            # connected to previous, so find biggest angle of current island
            biggest[-1] = max(biggest[-1], (i, a), key=lambda pa: abs(pa[1]))

    indices = [0] + [i for (i,_) in biggest] + [len(stroke)]
    return indices


def stroke_normal_bends(stroke, width, split_angle, fn_snap_normal):
    ''' Indices where the surface normal bends sharply along the stroke.
    Returns interior stroke indices only (never 0 or len(stroke)). '''
    n = len(stroke)
    if n < 3:
        return []
    split_angle = math.degrees(split_angle)

    # one normal per stroke point (reused for both detection and localization)
    normals = [Direction(fn_snap_normal(p)) for p in stroke]

    def idx_at_least(i, step):
        # first index walking in `step` direction whose point is >= width from stroke[i]
        p, k = stroke[i], i + step
        while 0 <= k < n:
            if (p - stroke[k]).length >= width:
                return k
            k += step
        return None

    candidates = [
        i for i in range(n)
        if (ib := idx_at_least(i, -1)) is not None
        and (iff := idx_at_least(i, +1)) is not None
        and math.degrees(normals[ib].angle_between(normals[iff])) >= split_angle
    ]
    if not candidates:
        return []

    # group candidates whose points are within width of each other into one island per fold
    islands = [[candidates[0]]]
    for i in candidates[1:]:
        if (stroke[i] - stroke[islands[-1][-1]]).length < width:
            islands[-1].append(i)
        else:
            islands.append([i])

    def local_turn(i):
        return normals[max(0, i - 1)].angle_between(normals[min(n - 1, i + 1)])

    bends = []
    for island in islands:
        apex = max(island, key=local_turn)
        if 0 < apex < n - 1:
            bends.append(apex)
    return bends



class PolyStrips_Logic:
    def __init__(self, context, radius2D, stroke3D_local, point3D_0, point3D_1, is_cycle, length2D,
                    snap_bmf0, snap_bmf1, split_angle, mirror_correct,
                    size_mode='BRUSH', fixed_count=8, span_length=0.1, radius3D=None, join_vert_idx=None):
        # store context data to make it more convenient
        # note: this will be redone whenever create() is called
        self.update_context(context)

        # self.process_stroke() will set self.error if something went wrong
        # use this indicator to fail gracefully rather than throwing/catching exception?
        self.error = False

        self.source_accel = None
        self.feature_radius = 0.0

        # TODO: Remove this limitation!
        if is_cycle:
            self.error = True
            print(f'Warning: PolyStrips cannot handle cyclic strokes, yet')
            return

        ##############################
        # store passed parameters
        M, Mi = self.matrix_world, self.matrix_world_inv
        self.radius2D = radius2D
        self.stroke3D_local_orig = stroke3D_local
        self.point3D_0 = point3D_0
        self.point3D_1 = point3D_1
        self.is_cycle = is_cycle
        self.snap_bmf0_index = snap_bmf0.index if snap_bmf0 else None
        self.snap_bmf1_index = snap_bmf1.index if snap_bmf1 else None
        self.join_vert_indices = list(join_vert_idx) if join_vert_idx else []
        self.split_angle = split_angle  # clamp!?
        self.mirror_correct = mirror_correct
        self.show_mirror_correct = False

        #################################
        # initial settings
        self.initial = True
        self.radius3D = radius3D
        self.size_mode = size_mode
        self.fixed_count = fixed_count
        self.span_length = max(0.001, span_length)
        # NOTE: self.initial_width is in world space
        length3D_world = self.compute_length3D(self.stroke3D_local_orig, self.is_cycle)
        if size_mode == 'FIXED':
            self.initial_count = max(2, fixed_count)
        elif size_mode == 'LENGTH':
            self.initial_count = max(2, round(length3D_world / self.span_length) + 1)
        elif radius3D:
            length3D_local = sum(
                (p1 - p0).length
                for (p0, p1) in iter_pairs(self.stroke3D_local_orig, self.is_cycle)
            )
            self.initial_count = max(2, round(length3D_local / (2 * radius3D)) + 1) # radius3D is in local space
        else:
            self.initial_count = max(2, round(length2D / (2 * radius2D)) + 1)
        self.initial_width = length3D_world / (self.initial_count * 2 - 1)
        self.strip_count = 0
        self.count_mins = []
        self.counts = []
        self.count_locked = False  # True when every rung is welded to existing edges
        self.attached = False      # True when any rung welds to existing edges
        self.interpolate_rungs = True
        self.count_total = self.initial_count
        self.scale_start = 1.0
        self.scale_end = 1.0
        self.width_interpolation = 'LINEAR'

        self._stroke_angles_cache_key = None
        self._stroke_angles_cache = None

        # self.count_min = 3 if (snap_bmf0 and snap_bmf1) else 2     # must be set before self.count
        # self.count = max(2, round(length2D / (2 * radius2D)) + 1)  # must be set after self.count_min
        # self.width = self.compute_length3D(self.stroke3D_local, self.is_cycle) / (self.count * 2 - 1)

    @property
    def count(self):
        return self.count_total
    @count.setter
    def count(self, v):
        self.count_total = v

    @staticmethod
    def reserved_rung_factors(n_rungs, seg_len, reserved_start, reserved_end):
        ''' Fractional arc-length positions for `n_rungs` rungs along a segment of length `seg_len`. '''
        fracs = [i / max(1, n_rungs - 1) for i in range(n_rungs)]
        if n_rungs < 3 or seg_len <= 0:
            return fracs

        lo_i, hi_i = 1, n_rungs - 2
        lo_f = min(0.45, reserved_start / seg_len) if reserved_start > 0 else None
        hi_f = 1 - min(0.45, reserved_end / seg_len) if reserved_end > 0 else None
        if lo_f is not None and hi_f is not None and lo_i >= hi_i:
            # only one interior rung available -- can't honor both ends distinctly
            lo_f, hi_f = None, None

        start_i, start_f = (lo_i, lo_f) if lo_f is not None else (0, 0.0)
        end_i, end_f = (hi_i, hi_f) if hi_f is not None else (n_rungs - 1, 1.0)
        if lo_f is not None: fracs[lo_i] = lo_f
        if hi_f is not None: fracs[hi_i] = hi_f
        for k in range(start_i + 1, end_i):
            t = (k - start_i) / (end_i - start_i)
            fracs[k] = start_f + t * (end_f - start_f)
        return fracs

    @staticmethod
    def rung_factors_with_pins(n_rungs, pins):
        ''' `n_rungs` rung factors (0-1) that include every pin, filling the gaps
        between consecutive pins with uniformly spaced rungs apportioned by gap length.
        Keeps a forced rung from bunching the spacing. '''
        pins = sorted(p for p in set(pins) if 0.0 <= p <= 1.0)
        if not pins or pins[0] > 0.0: pins = [0.0] + pins
        if pins[-1] < 1.0: pins = pins + [1.0]
        n_pins = len(pins)
        n_rungs = max(n_rungs, n_pins)
        gaps = [pins[i + 1] - pins[i] for i in range(n_pins - 1)]
        extra = n_rungs - n_pins  # interior rungs to spread across the gaps
        total = sum(gaps) or 1.0
        raw = [extra * g / total for g in gaps]
        add = [int(r) for r in raw]
        for i in sorted(range(len(gaps)), key=lambda i: raw[i] - add[i], reverse=True)[:extra - sum(add)]:
            add[i] += 1
        fracs = [pins[0]]
        for i in range(n_pins - 1):
            a, b, subdiv = pins[i], pins[i + 1], add[i] + 1
            fracs += [a + (b - a) * s / subdiv for s in range(1, subdiv)]
            fracs += [b]
        return fracs


    @staticmethod
    def rung_factors_locked(pins, locked_gaps, extra):
        ''' Like rung_factors_with_pins, but only subdivides gaps whose `locked_gaps[i]` is False.
        `extra` intermediate rungs are spread across the free gaps by length.
        `pins` must be sorted and include 0.0 and 1.0. '''
        n = len(pins)
        gaps = [pins[i + 1] - pins[i] for i in range(n - 1)]
        free = [i for i in range(n - 1) if not locked_gaps[i]]
        add = [0] * (n - 1)
        if free and extra > 0:
            total = sum(gaps[i] for i in free) or 1.0
            raw = {i: extra * gaps[i] / total for i in free}
            for i in free: add[i] = int(raw[i])
            leftover = extra - sum(add[i] for i in free)
            for i in sorted(free, key=lambda i: raw[i] - add[i], reverse=True)[:leftover]:
                add[i] += 1
        fracs = [pins[0]]
        for i in range(n - 1):
            a, b, subdiv = pins[i], pins[i + 1], add[i] + 1
            fracs += [a + (b - a) * s / subdiv for s in range(1, subdiv)]
            fracs += [b]
        return fracs

    @staticmethod
    def free_from_anchor(anchor_bmv, dir_toward_free, width):
        ''' Position for the unwelded vert of a rung whose opposite side is welded to `anchor_bmv`.
        `dir_toward_free` is the stroke's outward direction on the free side, used to pick/orient the outgoing edge.
        Returns None (fall back to the stroke offset) when the anchor has no suitable outgoing edge. '''
        best_dir, best_dot = None, 1e-4  # ignore edges along the boundary (dot ~ 0) or pointing inward
        for e in anchor_bmv.link_edges:
            other = e.other_vert(anchor_bmv)
            d = anchor_bmv.co - other.co
            if d.length == 0: continue
            d = d.normalized()
            dot = d.dot(dir_toward_free)
            if dot > best_dot:
                best_dot, best_dir = dot, d
        if best_dir is None: return None
        return anchor_bmv.co + best_dir * width

    @staticmethod
    def snapped_edge_radius(bmf, pts):
        ''' Half-length in local space of the snapped face's edge nearest the given stroke points. '''
        if not bmf or not pts: return None
        bmes = list(bmf.edges)
        if not bmes: return None
        bme = min(bmes, key=lambda bme: min(distance_point_bmedge(pt, bme) for pt in pts))
        return bme_length(bme) / 2

    @staticmethod
    def snapped_edges_radius(bmes):
        ''' Average half-length (local space) of a set of existing edges. Returns None when there are no valid edges. '''
        lengths = [bme_length(bme) for bme in (bmes or ()) if getattr(bme, 'is_valid', False)]
        if not lengths: return None
        return (sum(lengths) / len(lengths)) / 2

    @staticmethod
    def nearest_edge_halfwidth(edges, ref_pt, *, max_dist=None):
        ''' Half-length (local space) of the edge in `edges` whose closest point to ref_pt is nearest, or None. `edges` must be pre-filtered.
        Pass max_dist (a multiple of the edge's length) to reject an edge whose nearest point is farther away than that.
        '''
        best = None
        for bme in edges:
            v0, v1 = bme.verts
            d = (closest_point_segment(ref_pt, v0.co, v1.co) - ref_pt).length
            L = (v1.co - v0.co).length
            if max_dist is not None and d > L * max_dist: continue
            if best is None or d < best[0]: best = (d, L / 2)
        return best[1] if best else None


    def create(self, context):
        if self.error: return
        self.update_context(context)

        ##############################
        # handle mirror
        self.stroke3D_local = self.stroke3D_local_orig
        self.mirror = set()
        if has_mirror_x(context): self.mirror.add('x')
        if has_mirror_y(context): self.mirror.add('y')
        if has_mirror_z(context): self.mirror.add('z')
        self.show_mirror_correct = bool(self.mirror)
        self.mirror_threshold = mirror_threshold(context)
        mirror_counts = {'x':[0,0,0], 'y':[0,0,0], 'z':[0,0,0]}
        self.mirror_side = Vector((1,1,1))
        if self.mirror:
            match self.mirror_correct:
                case 'FIRST':
                    if 'x' in self.mirror:
                        self.mirror_side.x = sign_threshold(self.point3D_0.x, self.mirror_threshold) or 1
                        # self.mirror_side.x = next((s for co in self.stroke3D_local if (s := sign_threshold(co.x, self.mirror_threshold)) != 0), 1)
                    if 'y' in self.mirror:
                        self.mirror_side.y = sign_threshold(self.point3D_0.y, self.mirror_threshold) or 1
                        # self.mirror_side.y = next((s for co in self.stroke3D_local if (s := sign_threshold(co.y, self.mirror_threshold)) != 0), 1)
                    if 'z' in self.mirror:
                        self.mirror_side.z = sign_threshold(self.point3D_0.z, self.mirror_threshold) or 1
                        # self.mirror_side.z = next((s for co in self.stroke3D_local if (s := sign_threshold(co.z, self.mirror_threshold)) != 0), 1)
                case 'LAST':
                    if 'x' in self.mirror:
                        self.mirror_side.x = sign_threshold(self.point3D_1.x, self.mirror_threshold) or 1
                        # self.mirror_side.x = next((s for co in self.stroke3D_local[::-1] if (s := sign_threshold(co.x, self.mirror_threshold)) != 0), 1)
                    if 'y' in self.mirror:
                        self.mirror_side.y = sign_threshold(self.point3D_1.y, self.mirror_threshold) or 1
                        # self.mirror_side.y = next((s for co in self.stroke3D_local[::-1] if (s := sign_threshold(co.y, self.mirror_threshold)) != 0), 1)
                    if 'z' in self.mirror:
                        self.mirror_side.z = sign_threshold(self.point3D_1.z, self.mirror_threshold) or 1
                        # self.mirror_side.z = next((s for co in self.stroke3D_local[::-1] if (s := sign_threshold(co.z, self.mirror_threshold)) != 0), 1)
                case 'MOST':
                    if 'x' in self.mirror:
                        count_neg = sum(1 if sign_threshold(co.x, self.mirror_threshold) < 0 else 0 for co in self.stroke3D_local)
                        count_pos = sum(1 if sign_threshold(co.x, self.mirror_threshold) > 0 else 0 for co in self.stroke3D_local)
                        if count_neg > count_pos: self.mirror_side.x = -1
                    if 'y' in self.mirror:
                        count_neg = sum(1 if sign_threshold(co.y, self.mirror_threshold) < 0 else 0 for co in self.stroke3D_local)
                        count_pos = sum(1 if sign_threshold(co.y, self.mirror_threshold) > 0 else 0 for co in self.stroke3D_local)
                        if count_neg > count_pos: self.mirror_side.y = -1
                    if 'z' in self.mirror:
                        count_neg = sum(1 if sign_threshold(co.z, self.mirror_threshold) < 0 else 0 for co in self.stroke3D_local)
                        count_pos = sum(1 if sign_threshold(co.z, self.mirror_threshold) > 0 else 0 for co in self.stroke3D_local)
                        if count_neg > count_pos: self.mirror_side.z = -1

            self.stroke3D_local = [
                co * Vector((
                    0 if 'x' in self.mirror and sign_threshold(co.x, self.mirror_threshold) != self.mirror_side.x else 1,
                    0 if 'y' in self.mirror and sign_threshold(co.y, self.mirror_threshold) != self.mirror_side.y else 1,
                    0 if 'z' in self.mirror and sign_threshold(co.z, self.mirror_threshold) != self.mirror_side.z else 1,
                ))
                for co in self.stroke3D_local
            ]



        bvh = self.bvh
        M, Mi = self.matrix_world, self.matrix_world_inv

        select_geo = []

        # deal with snapping stroke to bmfs hovered at beginning and ending of stroke
        snap_bmf_start, snap_bmf_end = None, None
        if self.snap_bmf0_index is not None:
            snap_bmf_start = self.bm.faces[self.snap_bmf0_index]
        if self.snap_bmf1_index is not None:
            snap_bmf_end = self.bm.faces[self.snap_bmf1_index]

        join_anchor_bmvs = [
            self.bm.verts[i]
            for i in self.join_vert_indices
            if 0 <= i < len(self.bm.verts) and self.bm.verts[i].is_valid
        ]
        join_anchor_set = set(join_anchor_bmvs)  # to tell an existing (welded) vert from a new free one
        if DEBUG_SIDEJOIN: print(f'[sidejoin] size_mode={self.size_mode} join_vert_indices={len(self.join_vert_indices)} anchors={len(join_anchor_bmvs)}')

        w_snap_start = w_snap_end = None
        if self.size_mode == 'SNAPPED':
            w_snap_start = self.snapped_edge_radius(snap_bmf_start, self.stroke3D_local[:3])
            w_snap_end   = self.snapped_edge_radius(snap_bmf_end,   self.stroke3D_local[-3:])
            # Adjust the brush radius to match the snapped geometry. Priority:
            # Start and end faces, start and end caps, then first parallel rail only
            if (w_snap_start is None or w_snap_end is None) and join_anchor_bmvs:
                anchor_set = set(join_anchor_bmvs)
                anchor_edges = {
                    e for bmv in join_anchor_bmvs for e in bmv.link_edges
                    if e.other_vert(bmv) in anchor_set
                }
                cap_dist = 1.5 * (self.radius3D or (self.initial_width / self.edit_scale))
                def cap_halfwidth(end_pt, along):
                    along = along.normalized() if along.length else None
                    best = None
                    for e in anchor_edges:
                        v0, v1 = e.verts
                        ev = (v1.co - v0.co)
                        L2 = ev.length_squared
                        if L2 == 0: continue
                        if along and abs(ev.normalized().dot(along)) > 0.6: continue  # parallel rail, not a cap
                        # the stroke end must terminate into the edge / project onto its interior
                        t = (end_pt - v0.co).dot(ev) / L2
                        if not (0.15 <= t <= 0.85): continue
                        d = ((v0.co + ev * t) - end_pt).length
                        if d > cap_dist: continue
                        if best is None or d < best[0]: best = (d, bme_length(e) / 2)
                    return best[1] if best else None
                nloc = len(self.stroke3D_local)
                kloc = min(3, nloc - 1)
                # the parallel side rail anchor edge nearest the start sets the width for the whole run,
                # so drawing past rails of varying length doesn't make the strip fluctuate.
                def first_parallel_halfwidth():
                    start = self.stroke3D_local[0]
                    along = (self.stroke3D_local[kloc] - start) if kloc > 0 else Vector((0, 0, 0))
                    along = along.normalized() if along.length else None
                    def is_parallel(e):  # skip edges perpendicular to the start tangent (those are caps)
                        ev = e.verts[1].co - e.verts[0].co
                        return ev.length != 0 and (not along or abs(ev.normalized().dot(along)) > 0.6)
                    return self.nearest_edge_halfwidth([e for e in anchor_edges if is_parallel(e)], start)
                if w_snap_start is None and kloc > 0:
                    w_snap_start = cap_halfwidth(self.stroke3D_local[0], self.stroke3D_local[kloc] - self.stroke3D_local[0])
                if w_snap_end is None and kloc > 0:
                    w_snap_end = cap_halfwidth(self.stroke3D_local[-1], self.stroke3D_local[-1] - self.stroke3D_local[-1 - kloc])
                w_par = first_parallel_halfwidth()
                if w_snap_start is None: w_snap_start = w_par
                if w_snap_end is None: w_snap_end = w_par

        scale = sum(M.to_scale()) / 3

        # break stroke into segments. Cached, since this raycasts a normal at nearly every point
        # along the raw stroke, but its result only ever changes with split_angle or mirror settings.
        stroke_angles_key = (self.split_angle, frozenset(self.mirror), tuple(self.mirror_side), self.mirror_threshold)
        if self._stroke_angles_cache_key == stroke_angles_key:
            strips, bend_indices = self._stroke_angles_cache
        else:
            fn_normal = lambda p: nearest_normal_valid_sources(context, M @ p, world=False)
            width_local = self.initial_width / scale
            # Two kinds of sharp corner, each with its own geometry.
            # - TANGENT (in-plane turn, flat-surface strip corner):
            #       split the stroke into segments so the strip pivots.
            # - NORMAL (a fold over a source edge, straight in-plane):
            #       do not split (#1601) and instead force a rung onto the fold.
            strips = stroke_angles(self.stroke3D_local, width_local, self.split_angle, fn_normal)
            corner_set = set(strips)
            bend_indices = [
                i for i in stroke_normal_bends(self.stroke3D_local, width_local, self.split_angle, fn_normal)
                if i not in corner_set
            ]
            self._stroke_angles_cache_key = stroke_angles_key
            self._stroke_angles_cache = (strips, bend_indices)
        nstroke = len(self.stroke3D_local)

        # cumulative world space length at each stroke index and the overall length
        cumlen_at_index = [0.0]
        for (p0, p1) in iter_pairs(self.stroke3D_local, False):
            cumlen_at_index.append(cumlen_at_index[-1] + ((M @ p1) - (M @ p0)).length)
        total_length = cumlen_at_index[-1] or 1.0

        # When side joining, force a split where the attached boundary turns past the split threshold.
        # Otherwise a slightly too smooth stroke will create a mess
        if join_anchor_bmvs:
            anchor_set = set(join_anchor_bmvs)
            # anchor verts where the two attached-boundary neighbors turn past split_angle
            turn_anchor_cos = []
            for v in join_anchor_bmvs:
                nbrs = [e.other_vert(v) for e in v.link_edges if e.other_vert(v) in anchor_set]
                if len(nbrs) != 2: continue
                d_in, d_out = v.co - nbrs[0].co, nbrs[1].co - v.co
                if d_in.length == 0 or d_out.length == 0: continue
                if d_in.normalized().dot(d_out.normalized()) > math.cos(self.split_angle): continue  # ~straight
                turn_anchor_cos.append(v.co)

            anchor_edge_lens = [
                bme_length(e)
                for v in join_anchor_bmvs for e in v.link_edges
                if e.other_vert(v) in anchor_set and v.index < e.other_vert(v).index
            ]
            weld_spacing = (sum(anchor_edge_lens) / len(anchor_edge_lens)) * self.edit_scale if anchor_edge_lens else 0.0
            margin = max(self.initial_width, 1.5 * weld_spacing)

            # force a stroke split at each boundary corner, clear of the ends and of existing splits
            new_strips = list(strips)
            for co in turn_anchor_cos:
                j = min(range(nstroke), key=lambda k: (self.stroke3D_local[k] - co).length)
                lj = cumlen_at_index[min(j, nstroke - 1)]
                if lj < margin or lj > total_length - margin: continue
                if any(abs(lj - cumlen_at_index[min(s, nstroke - 1)]) < margin for s in new_strips): continue
                new_strips.append(j)
            if len(new_strips) > len(strips):
                strips = sorted(new_strips)
                if DEBUG_SIDEJOIN: print(f'[sidejoin] forced corner splits -> strips={strips}')

            # Merge splits closer than about a quad since a jittery corner can create sliver segments
            if len(strips) > 2:
                clusters = []
                for j in strips[1:-1]:
                    lj = cumlen_at_index[min(j, nstroke - 1)]
                    lp = cumlen_at_index[min(clusters[-1][-1], nstroke - 1)] if clusters else None
                    if clusters and abs(lj - lp) < margin:
                        clusters[-1].append(j)
                    else:
                        clusters.append([j])
                if any(len(cl) > 1 for cl in clusters):
                    merged = []
                    for cl in clusters:
                        if len(cl) == 1:
                            merged.append(cl[0])
                        elif turn_anchor_cos:
                            merged.append(min(cl, key=lambda j: min(
                                (self.stroke3D_local[min(j, nstroke - 1)] - co).length for co in turn_anchor_cos)))
                        else:
                            merged.append(cl[len(cl) // 2])
                    strips = [strips[0]] + merged + [strips[-1]]
                    if DEBUG_SIDEJOIN: print(f'[sidejoin] merged sliver splits -> strips={strips}')

        # Snapped mode sizes quads to the snapped edge width. Re-derive the quad count from that width
        # on the first build only, and afterwards the artist's Count / Ctrl+Scroll must win.
        if self.size_mode == 'SNAPPED' and self.initial:
            snapped_world = [w * self.edit_scale for w in (w_snap_start, w_snap_end) if w]
            if snapped_world:
                avg_w = sum(snapped_world) / len(snapped_world)
                if avg_w > 0:
                    self.count_total = max(2, round(total_length / (2 * avg_w)) + 1)

        self.source_accel = SourceCache.get(context)
        if self.source_accel:
            use_fixed, fixed_distance, proximity = source_snap_settings(context)
            self.feature_radius = source_snap_radius(
                total_length / max(1, self.count_total),
                use_fixed=use_fixed, fixed_distance=fixed_distance, avg_edge_factor=proximity,
            )
        else:
            self.feature_radius = 0.0

        # NOTE: base_width is in local space (self.initial_width is world space)
        base_width = self.initial_width / self.edit_scale

        base0 = base1 = base_width
        if self.size_mode == 'SNAPPED':
            if w_snap_start and w_snap_end:
                base0, base1 = w_snap_start, w_snap_end
            elif w_snap_start:
                base0 = base1 = w_snap_start
            elif w_snap_end:
                base0 = base1 = w_snap_end
            # else: neither end snapped -> keep the brush-derived base_width

        def width_at(t):
            t = clamp(t, 0, 1)
            if self.width_interpolation == 'SMOOTH':
                t = t * t * (3 - 2 * t)  # smoothstep: eases in/out at both ends instead of a constant rate
            return lerp(t, base0, base1) * lerp(t, self.scale_start, self.scale_end)

        # Reserve one quad per corner end (sized to the local width) out of the requested total count,
        # then split whatever's left across the remaining (non-corner) length. So widening the count
        # only grows the straight portions of the strip, never stretches or shrinks the corners.
        seg_specs = []
        for (i0, i1) in iter_pairs(strips, False):
            if i0 == i1:
                seg_specs.append(None)
                continue
            # Only a segment's end needs reserving, never its start.
            # At a corner, this segment's ending rail edge gets reused as the next segment's very first rung,
            # so squaring this segment's last quad is what makes the next segment's first cross-section the correct width.
            # The next segment's own start isn't itself a distinct corner and should size like a regular quad.
            has_end_corner = i1 != nstroke
            i1_clamped = min(i1, len(cumlen_at_index) - 1)
            seg_len_world = cumlen_at_index[i1_clamped] - cumlen_at_index[i0]
            w_end = width_at(cumlen_at_index[i1_clamped] / total_length) if has_end_corner else 0.0
            # w_end is a half-width. A square corner quad needs its along-strip length to match the full (rail-to-rail) width.
            reserved_world = 2 * w_end * self.edit_scale  # width is local-space
            seg_specs.append({
                'n_ends': 1 if has_end_corner else 0,
                'remaining_world': max(0.0, seg_len_world - reserved_world),
            })
        total_reserved_quads = sum(s['n_ends'] for s in seg_specs if s)
        total_remaining_world = sum(s['remaining_world'] for s in seg_specs if s) or 1.0
        remaining_budget = max(0, self.count_total - total_reserved_quads)

        # largest remainder apportionment: plain per-segment round() lets a short segment's share
        # sit below 0.5 (and so get rounded to the same value) across a wide range of count_total.
        # It can look permanently "stuck" while longer segments increase. Floor everyone first, then hand out
        # the few leftover quads to whoever's fractional share is largest, so every
        # segment's count is monotonically non-decreasing as the total grows.
        valid = [i for i, s in enumerate(seg_specs) if s]
        raw_shares = {i: remaining_budget * seg_specs[i]['remaining_world'] / total_remaining_world for i in valid}
        remaining_quads = {i: int(raw_shares[i]) for i in valid}
        leftover = remaining_budget - sum(remaining_quads.values())
        for i in sorted(valid, key=lambda i: raw_shares[i] - remaining_quads[i], reverse=True)[:leftover]:
            remaining_quads[i] += 1
        precomputed_quad_counts = [
            (seg_specs[i]['n_ends'] + remaining_quads[i]) if i in remaining_quads else 0
            for i in range(len(seg_specs))
        ]

        # create quads based on segments
        bmfs = []
        actual_strip_count = 0
        ncount_mins, ncounts = [], []
        # track whether any rung is welded to existing edges and whether any free rungs remain
        has_anchor = has_free = False
        concave_corner_bmv = None  # interior-corner welded vert whose end rung the next segment reuses

        # Side joining: assign each anchor vert to the single nearest stroke segment.
        # The corner vert falls to the earlier segment as its end anchor.
        anchor_by_strip = {}
        for bmv in join_anchor_bmvs:
            best = None  # (dist, i_strip, seg_frac)
            for i_strip, (i0, i1) in enumerate(iter_pairs(strips, False)):
                if i0 == i1: continue
                seg_pts = self.stroke3D_local[i0:i1]
                seglens = [(seg_pts[si + 1] - seg_pts[si]).length for si in range(len(seg_pts) - 1)]
                seg_tot = sum(seglens) or 1.0
                al = 0.0
                for si in range(len(seg_pts) - 1):
                    cp = closest_point_segment(bmv.co, seg_pts[si], seg_pts[si + 1])
                    d = (cp - bmv.co).length
                    if best is None or d < best[0]:
                        best = (d, i_strip, (al + (cp - seg_pts[si]).length) / seg_tot)
                    al += seglens[si]
            if best is None: continue
            _, owner, frac = best
            # A vert near the start of an internal-corner segment sits at the corner. The next segment's nap0 reuse
            # owns that start rung and would drop the anchor, so move it to the previous segment as its end anchor
            if owner > 0 and frac < 0.2:
                owner -= 1
            anchor_by_strip.setdefault(owner, []).append(bmv)
        if DEBUG_SIDEJOIN: print(f'[sidejoin] strips={list(iter_pairs(strips, False))} anchors_per_segment={ {k: len(v) for k, v in anchor_by_strip.items()} }')

        for i_strip, (i0, i1) in enumerate(iter_pairs(strips, False)):
            if i0 == i1: continue
            stroke3D_local = self.stroke3D_local[i0:i1]
            seg_anchors = anchor_by_strip.get(i_strip, [])  # this segment's side-join anchors

            # this segment's own overall-position range, for the width gradient as a
            # slice bound, one past the last valid point index, so clamp it to the last cumulative-length entry
            seg_start_length = cumlen_at_index[i0]
            seg_end_length = cumlen_at_index[min(i1, len(cumlen_at_index) - 1)]
            def sample_width(v):
                # v is a fraction (0..1) along this segment's own samples
                return width_at(lerp(v, seg_start_length, seg_end_length) / total_length)

            # side joining corner classification:
            # * CONVEX (turns toward the welded side, e.g. wrapping around a patch corner):
            #       Extension + a corner quad one quad past corner vert C. C pins the quad's near rung and
            #       the next segment pivots off the quad's welded-side rail edge.
            # * CONCAVE (turn away from the welded side, next segment keeps welding):
            #       No corner quad. C sits on the end rung and the next segment reuses that same rung.
            # * HALF-WELD L (Corner shape where only one side is welded):
            #       End at C, pivot off the free rail
            prev_concave_bmv = concave_corner_bmv  # set by the previous segment (its shared end rung)
            concave_corner_bmv = None
            convex_corner_bmv = None
            convex_wrap = False
            if seg_anchors and i1 != nstroke and len(seg_anchors) >= 2:
                corner_pt = self.stroke3D_local[min(i1, nstroke - 1)]
                next_anchors = anchor_by_strip.get(i_strip + 1, [])
                corner_anchor = min(
                    set(seg_anchors) | set(next_anchors),
                    key=lambda bmv: (bmv.co - corner_pt).length,
                )
                if (corner_anchor.co - corner_pt).length <= 3 * (2 * sample_width(1)):
                    def stroke_pt_at(idx_from, step, dist):
                        j, acc = idx_from, 0.0
                        while 0 <= j + step < nstroke and acc < dist:
                            acc += (self.stroke3D_local[j + step] - self.stroke3D_local[j]).length
                            j += step
                        return self.stroke3D_local[j]
                    d_ref = 2 * sample_width(1)
                    incoming = corner_pt - stroke_pt_at(min(i1, nstroke - 1), -1, d_ref)
                    outgoing = stroke_pt_at(min(i1, nstroke - 1), +1, d_ref) - corner_pt
                    if incoming.length and outgoing.length:
                        n_corner = Direction(nearest_normal_valid_sources(context, M @ corner_pt, world=False))
                        right = incoming.normalized().cross(n_corner)
                        weld_ref = sum((bmv.co for bmv in seg_anchors), Vector()) / len(seg_anchors)
                        side_weld = right.dot(weld_ref - corner_pt)
                        side_turn = right.dot(outgoing)
                        if side_weld * side_turn > 0:
                            convex_wrap = True
                            convex_corner_bmv = corner_anchor
                        elif next_anchors:
                            concave_corner_bmv = corner_anchor

            snap_beginning = (
                i0 == 0 and 'x' in self.mirror and sign_threshold(stroke3D_local[0].x, self.mirror_threshold) == 0,
                i0 == 0 and 'y' in self.mirror and sign_threshold(stroke3D_local[0].y, self.mirror_threshold) == 0,
                i0 == 0 and 'z' in self.mirror and sign_threshold(stroke3D_local[0].z, self.mirror_threshold) == 0,
            )
            snap_ending = (
                i1 == len(self.stroke3D_local) and 'x' in self.mirror and sign_threshold(stroke3D_local[-1].x, self.mirror_threshold) == 0,
                i1 == len(self.stroke3D_local) and 'y' in self.mirror and sign_threshold(stroke3D_local[-1].y, self.mirror_threshold) == 0,
                i1 == len(self.stroke3D_local) and 'z' in self.mirror and sign_threshold(stroke3D_local[-1].z, self.mirror_threshold) == 0,
            )
            # print(snap_beginning, snap_ending)

            limit_bmes0 = None
            if i0 == 0:
                snap_bmf0 = snap_bmf_start
            else:
                snap_bmf0 = snap_bmf1
                limit_bmes0 = [
                    bme for bme in snap_bmf0.edges
                    if bme.is_boundary and any(len(bmv.link_faces)>1 for bmv in bme.verts)
                ]
                if prev_concave_bmv is not None and prev_concave_bmv.is_valid:
                    # interior welded corner. Both arms share the corner rung so restrict the
                    # reusable edges to those containing the welded corner vert (the previous end rung)
                    containing = [bme for bme in limit_bmes0 if prev_concave_bmv in bme.verts]
                    if containing:
                        limit_bmes0 = containing
                if len(limit_bmes0) > 1 and len(stroke3D_local) > 1:
                    # At sharp angle splits the corner sits about equidistant from both sides,
                    # so connect to the edge in the direction of the stroke instead of closest one.
                    corner = self.stroke3D_local[i0]
                    incoming = Direction(corner - self.stroke3D_local[i0 - 1])
                    outgoing = Direction(stroke3D_local[1] - stroke3D_local[0])
                    normal = Direction(nearest_normal_valid_sources(context, M @ corner, world=False))
                    side = Direction(incoming.cross(normal))
                    outgoing_sign = 1 if side.dot(outgoing) >= 0 else -1
                    limit_bmes0 = [max(limit_bmes0, key=lambda bme: outgoing_sign * side.dot(bme_midpoint(bme) - corner))]

            limit_bmes1 = None
            if i1 == nstroke:
                snap_bmf1 = snap_bmf_end
                if snap_bmf_end:
                    limit_bmes1 = [
                        bme for bme in snap_bmf_end.edges
                        if bme.is_boundary and any(len(bmv.link_faces)>1 for bmv in bme.verts)
                    ]
            else:
                snap_bmf1 = None
                # extend the stroke to reserve a square corner
                end_pt = stroke3D_local[-1]
                welds_corner = any((bmv.co - end_pt).length < 2 * sample_width(1) for bmv in seg_anchors)
                if convex_wrap or not welds_corner:
                    # extend stroke by self.width
                    i_end = max(0, len(stroke3D_local) - 5)
                    p0,p1 = stroke3D_local[i_end], stroke3D_local[-1]
                    p1_world = M @ p1
                    d01_world = Direction(p1_world - (M @ p0))
                    p2_world = p1_world + d01_world * (self.initial_width / 2) # self.initial_width is world space
                    p2 = self.nearest_point(context, Mi @ p2_world)
                    stroke3D_local += [p2]

            snap0 = trim_stroke_to_bmf(stroke3D_local, snap_bmf0, True, limit_bmes0)
            if snap0:
                if snap0['error']:
                    self.error = True
                    print(f'ERROR: {snap0["error"]} on snap0')
                    if snap_bmf1 is None: snap_bmf1 = bmfs[-1] if bmfs else None
                    continue
                stroke3D_local = snap0['stroke']

            snap1 = trim_stroke_to_bmf(stroke3D_local, snap_bmf1, False, limit_bmes1)
            if snap1:
                if snap1['error']:
                    self.error = True
                    print(f'ERROR: {snap1["error"]} on snap1')
                    if snap_bmf1 is None: snap_bmf1 = bmfs[-1] if bmfs else None
                    continue
                stroke3D_local = snap1['stroke']

            # true only when this end is snapped to pre-existing geometry
            real_snap0 = bool(snap0) and i0 == 0
            real_snap1 = bool(snap1) and i1 == nstroke

            if not stroke3D_local: continue

            if (stroke3D_local[0] - stroke3D_local[-1]).length == 0:
                print(f'ERROR: ends of stroke are at the same location {len(stroke3D_local)=} {stroke3D_local[0]=} {stroke3D_local[-1]=}')
                continue

            # warp stroke to better fit snapped geo
            stroke3D_local = warp_stroke(
                context,
                stroke3D_local,
                None if not snap0 else snap0['bme.center'],
                None if not snap1 else snap1['bme.center'],
                self.nearest_point,
            )

            if not stroke3D_local:
                print(f'ERROR: stroke is empty')
                continue

            ###########################################################################
            # sample the stroke and compute various properties of sample

            count_min = 3 if (snap_bmf0 and snap_bmf1) else 2
            quad_count = max(count_min, precomputed_quad_counts[i_strip])

            ncount_mins += [count_min]
            ncounts += [quad_count]

            # NOTE: nsamples is always odd (rungs land at samples[0,2,4,...,nsamples-1], i.e. n_rungs = (nsamples+1)//2)
            # This relies on quad_count >= 3 whenever both ends are snapped, which count_min above already guarantees.
            # Don't loosen that clamp without rechecking the rung math below.
            quad_count = (quad_count - 1) if snap0 and snap1 else quad_count
            nsamples = quad_count + (quad_count - 1)
            nsamples = (nsamples + 2) if not (snap0 or snap1) else nsamples
            nsamples = max(2, nsamples)

            # Only the interval at this segment's own end gets pinned to the local width.
            # Its rail edge is what the next segment reuses as its own first rung, so
            # squaring it here is what makes the corner correct. The start is never pinned.
            n_rungs = (nsamples + 1) // 2
            seg_len_local = sum((p1 - p0).length for (p0, p1) in iter_pairs(stroke3D_local, self.is_cycle)) or 1.0

            # cumulative arc length at each sample, shared by fold-crease and side-join projection
            cumul = [0.0]
            for (a, b) in iter_pairs(stroke3D_local, self.is_cycle):
                cumul.append(cumul[-1] + (b - a).length)
            seg_total = cumul[-1] or 1.0

            # side joining: project this segment's own anchors onto its centerline. Each kept one becomes a pinned rung.
            anchor_fracs = []
            if seg_anchors:
                max_join_dist = 1.5 * (2 * sample_width(0.5))  # ~1.5x the local full (rail-to-rail) width
                for bmv in seg_anchors:
                    best_d, best_al = None, 0.0
                    for si in range(len(stroke3D_local) - 1):
                        cp = closest_point_segment(bmv.co, stroke3D_local[si], stroke3D_local[si + 1])
                        d = (cp - bmv.co).length
                        if best_d is None or d < best_d:
                            best_d, best_al = d, cumul[si] + (cp - stroke3D_local[si]).length
                    if best_d is None or best_d > max_join_dist: continue
                    f = best_al / seg_total
                    anchor_fracs.append((f, bmv))

            # NORMAL-corner: force a rung onto every fold that falls inside this segment. No splitting (#1601).
            fold_sample_indices = []
            anchor_sample_bmvs = {}  # sample index -> [bmv, ...] existing verts to reuse at that rung
            seg_creases = [ci for ci in bend_indices if i0 < ci < i1]
            if not seg_creases and not anchor_fracs:
                rung_fracs = self.reserved_rung_factors(
                    n_rungs, seg_len_local,
                    0.0,
                    2 * sample_width(1) if i1 != nstroke else 0.0,
                )
                has_free = True  # no anchors -> count fully controls this segment
                if DEBUG_SIDEJOIN: print(f'[sidejoin] seg {i_strip} [{i0}:{i1}] FREE (no anchors/folds) n_rungs={n_rungs} quads={n_rungs-1}')
            else:
                # Pin a rung at each fold / side-join anchor and re-space the rest evenly around them.
                guard = 0.5 / max(1, n_rungs)  # ~half a uniform span
                crease_fracs = []
                for ci in seg_creases:
                    crease_pt = self.stroke3D_local[ci]
                    j = min(range(len(stroke3D_local)), key=lambda j: (stroke3D_local[j] - crease_pt).length)
                    crease_fracs.append(cumul[j] / seg_total)

                anchor_list = sorted(anchor_fracs, key=lambda fb: fb[0])
                # Does the last anchor weld this segment's end? At an internal corner the shared corner vert
                # can project ~ a span short, so reach generously there and at the stroke's final end use the tight guard.
                # A convex wrap is the opposite, its corner vert stays an interior pin and the reserved end gap becomes the corner quad.
                end_reach = (3 * guard if i1 != nstroke else guard)
                has_end_anchor = (not snap1) and (not convex_wrap) and bool(anchor_list) and anchor_list[-1][0] >= 1.0 - end_reach
                if convex_wrap and anchor_list:
                    # keep the corner vert an interior pin
                    f_last, v_last = anchor_list[-1]
                    anchor_list[-1] = (min(f_last, 1.0 - 2 * guard), v_last)
                pins = [0.0, 1.0]
                if i1 != nstroke and not has_end_anchor and not convex_wrap:
                    pins.append(1.0 - min(0.45, (2 * sample_width(1)) / seg_len_local))
                kept_creases = []
                for cf in sorted(crease_fracs):
                    # drop folds that would sit on an endpoint, reserved pin, or another fold
                    if not (guard < cf < 1.0 - guard): continue
                    if any(abs(cf - p) < guard for p in pins + kept_creases): continue
                    kept_creases.append(cf)

                # Interior anchors become pinned rungs and an anchor near an end reuses this segment's first/last rung instead
                # (unless that end is already snapped to a face / internal corner, which owns that rung).
                # A left and a right anchor within guard merge onto one pin so one rung reuses both existing verts.
                kept_anchor_pins = []   # (frac, [bmv, ...]) interior pinned rungs
                start_anchor_bmvs = []  # reuse at this segment's first rung (sample 0)
                end_anchor_bmvs = []    # reuse at this segment's last rung (sample nsamples-1)
                force_end_idx = (len(anchor_list) - 1) if has_end_anchor else -1
                for idx, (f, bmv) in enumerate(anchor_list):
                    if idx == force_end_idx:
                        end_anchor_bmvs.append(bmv)  # the corner weld, even if it projects a span short
                        continue
                    if f <= guard:
                        if not snap0: start_anchor_bmvs.append(bmv)
                        continue
                    if f >= 1.0 - guard:
                        if not snap1: end_anchor_bmvs.append(bmv)
                        continue
                    merged = next((ap for ap in kept_anchor_pins if abs(ap[0] - f) < guard), None)
                    if merged is not None:
                        merged[1].append(bmv)
                        continue
                    if any(abs(f - p) < guard for p in pins + kept_creases): continue
                    kept_anchor_pins.append((f, [bmv]))

                # Interior corner: the end rung is the existing edge C-D (D = C's welded neighbor on the next arm).
                # Both verts reused, so the corner becomes one quad welding both boundary edges at C,
                # and the next segment pivots off that quad's free rail edge (its only remaining boundary edge).
                if concave_corner_bmv is not None and concave_corner_bmv in end_anchor_bmvs:
                    next_set = set(anchor_by_strip.get(i_strip + 1, []))
                    D_next = next((e.other_vert(concave_corner_bmv) for e in concave_corner_bmv.link_edges
                                   if e.other_vert(concave_corner_bmv) in next_set), None)
                    if D_next is not None and D_next not in end_anchor_bmvs:
                        end_anchor_bmvs.append(D_next)

                # existing verts reused at each pin (empty for fold / reserved-end / plain pins)
                pin_verts = {0.0: list(start_anchor_bmvs), 1.0: list(end_anchor_bmvs)}
                # A snapped/internal-corner end reuses the neighbor's rail edge (snap0/snap1) as its first/last rung.
                # Record those existing verts so that gap can lock against an adjacent anchor, otherwise the count would
                # insert a mistaken free quad between the corner or snapped edge and the first/last welded edge of a run-along arm.
                if snap0: pin_verts[0.0] += list(snap0['bme'].verts)
                if snap1: pin_verts[1.0] += list(snap1['bme'].verts)
                for (f, bmvs_here) in kept_anchor_pins:
                    pin_verts.setdefault(f, []).extend(bmvs_here)

                pins = sorted(set(pins + kept_creases + [ap[0] for ap in kept_anchor_pins]))
                n_rungs = max(n_rungs, len(pins))

                def verts_adjacent(av, bv):
                    for u in av:
                        neighbors = {e.other_vert(u) for e in u.link_edges}
                        if any(v in neighbors for v in bv): return True
                    return False
                locked_gaps = [
                    bool(pin_verts.get(pins[gi])) and bool(pin_verts.get(pins[gi + 1]))
                    and verts_adjacent(pin_verts[pins[gi]], pin_verts[pins[gi + 1]])
                    for gi in range(len(pins) - 1)
                ]
                if convex_wrap and locked_gaps:
                    locked_gaps[-1] = True # Never subdivide the corner quad.

                rung_fracs = self.rung_factors_locked(pins, locked_gaps, max(0, n_rungs - len(pins)))
                n_rungs = len(rung_fracs)
                nsamples = 2 * n_rungs - 1
                # sample index of each fold rung, so its centerline + direction can be pinned to the source crease once the samples are built.
                fold_sample_indices = [2 * rung_fracs.index(cf) for cf in kept_creases]
                # sample index of each anchored rung -> existing verts to reuse
                for (f, bmvs_here) in kept_anchor_pins:
                    anchor_sample_bmvs[2 * rung_fracs.index(f)] = bmvs_here
                if start_anchor_bmvs:
                    anchor_sample_bmvs[0] = start_anchor_bmvs
                if end_anchor_bmvs:
                    anchor_sample_bmvs[nsamples - 1] = end_anchor_bmvs
                if DEBUG_SIDEJOIN:
                    print(f'[sidejoin] seg {i_strip} [{i0}:{i1}] snap0={bool(snap0)} snap1={bool(snap1)} '
                          f'seg_anchors={len(seg_anchors)} anchor_fracs={len(anchor_fracs)} '
                          f'start={len(start_anchor_bmvs)} end={len(end_anchor_bmvs)} interior_pins={len(kept_anchor_pins)} '
                          f'creases={len(kept_creases)} pins={len(pins)} n_rungs={n_rungs} quads={n_rungs-1} '
                          f'convex_wrap={convex_wrap} concave={concave_corner_bmv is not None} '
                          f'locked_gaps={locked_gaps}')

                if any(pin_verts.get(p) for p in pins): has_anchor = True
                if any(not lg for lg in locked_gaps): has_free = True

            fracs = [0.0] * nsamples
            for k, f in enumerate(rung_fracs):
                fracs[2 * k] = f
            for i in range(1, nsamples - 1, 2):
                fracs[i] = (fracs[i - 1] + fracs[i + 1]) / 2

            samples = [
                find_point_at(stroke3D_local, self.is_cycle, fracs[i])
                for i in range(nsamples)
            ]
            samples = [
                nearest_point_valid_sources(context, M @ pt, world=False, respect_clip_planes=True) or pt
                for pt in samples
            ]
            normals = [ Direction(nearest_normal_valid_sources(context, M @ pt, world=False)) for pt in samples ]
            # Pin each fold rung's centerline onto the actual source crease when detection is on,
            # else the intersection of the two adjacent face planes if detection is off.
            # Done before forwards/backwards/rights so the cross-section reflects the move.
            fold_crease_dirs = {}
            for k in fold_sample_indices:
                if not (0 < k < len(samples) - 1): continue
                crease = self.fold_crease_point(
                    samples[k], samples[k - 1], normals[k - 1], samples[k + 1], normals[k + 1],
                    max_plane_dist=2 * base_width,
                )
                if crease is not None:
                    samples[k], fold_crease_dirs[k] = crease
            forwards = [ Direction(p1 - p0) for (p0, p1) in iter_pairs(samples, self.is_cycle) ]
            forwards += [ forwards[-1] ]
            # backwards is essentially the same as forwards, but doing it this way is slightly easier to understand
            backwards = [ Direction(p0 - p1) for (p0, p1) in iter_pairs(samples, self.is_cycle) ]
            backwards = [ backwards[0] ] + backwards
            rights = [
                (f.cross(n).normalize() + n.cross(b).normalize()).normalize()
                for (b, f, n) in zip(backwards, forwards, normals)
            ]
            # A fold rung must lie along the crease so both its verts land on the edge.
            # Replace the fold rung's direction with the crease direction.
            # Skip if the strip only grazes the crease.
            for k, cdir in fold_crease_dirs.items():
                align = cdir.dot(rights[k])
                if abs(align) < 0.2: continue
                rights[k] = Direction(cdir if align >= 0 else -cdir)

            # Side joining: classify each anchored existing vert onto the +r (bmvs[0]) or -r (bmvs[1]) rail
            # using the rung's cross-section direction. A merged pin holds one vert per side.
            rung_anchor = {}  # sample index -> [left_bmv_or_None, right_bmv_or_None]
            for i, bmvs_here in anchor_sample_bmvs.items():
                if not (0 <= i < len(samples)): continue
                r = rights[i]
                slot = [None, None]
                for bmv in bmvs_here:
                    side = 0 if r.dot(bmv.co - samples[i]) >= 0 else 1
                    if slot[side] is None:
                        slot[side] = bmv
                rung_anchor[i] = slot

            # which rail (0/1) does this segment weld its anchors to?
            # Majority side, ignoring the corner rung at sample 0, whose side is ill-defined.
            # Used to orient a reused corner edge so its welded vert lands on the same rail as the anchors.
            welded_side = None
            if rung_anchor:
                s0 = sum(1 for i, sl in rung_anchor.items() if i != 0 and sl[0])
                s1 = sum(1 for i, sl in rung_anchor.items() if i != 0 and sl[1])
                if s0 != s1: welded_side = 0 if s0 > s1 else 1


            ######################################
            # create bmverts

            # w0/w1 anchor a taper only where this end is snapped to real pre-existing
            # geometry; everywhere else (a fresh end, or an internal corner join) just
            # follows the start/end width gradient directly, so widths stay consistent
            # across corners no matter how the count/segmentation changes
            w0 = snap0['bme.radius'] if real_snap0 else sample_width(0)
            w1 = snap1['bme.radius'] if real_snap1 else sample_width(1)
            bmvs = [[], []]
            reused_bmvs = set()  # side join: existing verts reused as rail verts

            def make_rail_verts(sample_index, p, r, w, clamp=None):
                ''' Build the two rail verts (bmvs[0]=+r side, bmvs[1]=-r side) for one rung.
                `clamp` zeroes free verts onto an active mirror plane.'''
                a_left, a_right = rung_anchor.get(sample_index, (None, None))
                full_w = 2 * w
                def clamped(co):
                    if clamp:
                        if clamp[0]: co.x = 0
                        if clamp[1]: co.y = 0
                        if clamp[2]: co.z = 0
                    return co
                # Fan the free rail out along the anchor's existing edge like an extrude if interpolating rungs
                fan = self.interpolate_rungs
                if a_left is not None and a_left.is_valid:
                    v0 = a_left; reused_bmvs.add(a_left)
                else:
                    co = self.free_from_anchor(a_right, r, full_w) if (fan and a_right is not None and a_right.is_valid) else None
                    v0 = self.bm.verts.new(clamped(co if co is not None else p + r * w))
                if a_right is not None and a_right.is_valid:
                    v1 = a_right; reused_bmvs.add(a_right)
                else:
                    co = self.free_from_anchor(a_left, -r, full_w) if (fan and a_left is not None and a_left.is_valid) else None
                    v1 = self.bm.verts.new(clamped(co if co is not None else p - r * w))
                return v0, v1

            # create bmverts at beginning of stroke
            p, pn = samples[0], samples[1]
            f, r = forwards[0], rights[0]
            if snap0:
                bme = snap0['bme']
                bmv0, bmv1 = bme.verts[0], bme.verts[1]
                # Side joining: If this segment welds anchors, put the reused corner's welded (existing) vert
                # on the same rail as those anchors, so the welded rail is continuous around the corner.
                welded_vert = next((v for v in (bmv0, bmv1) if v in join_anchor_set), None)
                if welded_vert is not None and welded_side is not None:
                    other = bmv1 if welded_vert is bmv0 else bmv0
                    if welded_side == 0: bmv0, bmv1 = welded_vert, other
                    else:                bmv0, bmv1 = other, welded_vert
                    if DEBUG_SIDEJOIN: print(f'[sidejoin] seg {i_strip}: corner reuse -> welded vert on rail {welded_side}')
                elif r.dot(bmv1.co - bmv0.co) > 0:
                    bmv0, bmv1 = bmv1, bmv0
                bmvs[0] += [bmv0]
                bmvs[1] += [bmv1]
            else:
                # Side joining: An existing vert brushed near the stroke start reuses this rung's rail.
                v0, v1 = make_rail_verts(0, p, r, w0, clamp=snap_beginning)
                bmvs[0] += [ v0 ]; bmvs[1] += [ v1 ]

            # create bmverts along stroke
            i_start = 2 if (snap0 or snap1) else 2
            i_end = len(samples) - (2 if (snap0 or snap1) else 1)
            for i in range(i_start, i_end, 2):
                pp, p, pn = samples[i-1:i+2]
                r = rights[i]

                # Computing width: Blend from a real snap's width toward the gradient value at this sample.
                # With no real snap on either end, just use the gradient value directly.
                # Use the actual (possibly corner-reserved, non-uniform) arc-length fraction this sample sits at,
                # not a uniform index fraction, or the width gradient falls out of sync with where the vertex really is.
                v = fracs[i]
                wg = sample_width(v)
                if self.size_mode == 'SNAPPED':
                    w = wg # the gradient already encodes the snapped widths
                elif real_snap0 and not real_snap1:
                    w = w0 + (wg - w0) * v
                elif not real_snap0 and real_snap1:
                    w = wg + (w1 - wg) * v
                elif real_snap0 and real_snap1:
                    v2 = 2 * v
                    if v2 < 1: w = w0 + (wg - w0) * v2
                    else:      w = wg + (w1 - wg) * (v2 - 1)
                else:
                    w = wg

                # Side joining: Reuse the brushed existing vert on an anchored rail.
                # The opposite rail fans out from the anchor's existing edge.
                v0, v1 = make_rail_verts(i, p, r, w)
                bmvs[0] += [ v0 ]; bmvs[1] += [ v1 ]

            # create bmverts at ending of stroke
            p, pp = samples[-1], samples[-2]
            f, r = forwards[-1], rights[-1]
            if snap1:
                bme = snap1['bme']
                bmv0, bmv1 = bme.verts[0], bme.verts[1]
                if r.dot(bmv1.co - bmv0.co) > 0:
                    bmv0, bmv1 = bmv1, bmv0
                bmvs[0] += [bmv0]
                bmvs[1] += [bmv1]
            else:
                # Side joining: An existing vert brushed near the stroke end reuses this rung's rail.
                v0, v1 = make_rail_verts(len(samples) - 1, p, r, w1, clamp=snap_ending)
                bmvs[0] += [ v0 ]; bmvs[1] += [ v1 ]

            # Corner squaring for a convex wrap weld: Place the corner quad's free verts by continuing
            # the existing grid through the corner vert C. Get the direction from C's existing edges
            # (B = C's welded neighbor on this arm, D = on the next arm), and the width from the strip's own rung width.
            if convex_wrap and convex_corner_bmv is not None and convex_corner_bmv.is_valid \
                    and len(bmvs[0]) >= 2 and len(bmvs[1]) >= 2 \
                    and (convex_corner_bmv is bmvs[0][-2] or convex_corner_bmv is bmvs[1][-2]):
                corner_C = convex_corner_bmv
                seg_set = set(seg_anchors)
                next_set = set(anchor_by_strip.get(i_strip + 1, []))
                B = next((e.other_vert(corner_C) for e in corner_C.link_edges if e.other_vert(corner_C) in seg_set), None)
                D = next((e.other_vert(corner_C) for e in corner_C.link_edges if e.other_vert(corner_C) in next_set), None)
                cr = 0 if bmvs[0][-2] is corner_C else 1
                F0, G, K = bmvs[1 - cr][-2], bmvs[cr][-1], bmvs[1 - cr][-1]
                w2 = 2 * sample_width(1)
                along = Direction(corner_C.co - B.co) * w2 if B is not None else None
                perp = (Direction(corner_C.co - D.co) if D is not None else Direction(F0.co - corner_C.co)) * w2
                if D is not None and F0 not in reused_bmvs: F0.co = corner_C.co + perp
                if along is not None:
                    if G not in reused_bmvs: G.co = corner_C.co + along
                    if K not in reused_bmvs: K.co = corner_C.co + along + perp

            # snap newly created bmverts to source, then pull onto nearby source features.
            # Verts reused from a snapped edge are surface-projected as before but never feature snapped.
            # Side join anchors reuse pre-existing verts and are left completely untouched.
            existing_bmvs = set()
            if snap0: existing_bmvs.update((bmvs[0][0], bmvs[1][0]))
            if snap1: existing_bmvs.update((bmvs[0][-1], bmvs[1][-1]))
            for bmv in chain(bmvs[0], bmvs[1]):
                if bmv in reused_bmvs: continue
                if snapped := nearest_point_valid_sources(context, M @ bmv.co, world=False, respect_clip_planes=True):
                    bmv.co = snapped

            # Feature snapping is decided a rung at a time, then compared across rungs.
            #  - a feature parallel to the stroke may take one rail from every rung it reaches, but never both of a rung's rails,
            #    or else that rung collapses to no width. Per feature run.
            #  - a feature perpendicular to the stroke may take both of that rung's rails, but only for the single rung nearest
            #    it, or else the neighboring rungs pile onto the same edge. Per feature run.
            #  - and whatever the classification, a single point (a corner, the end of a run) may take
            #    only one vert, or else the strip fans onto it.
            FEATURE_SNAP_PARALLEL = 0.866 # How parallel a feature must be to a rung before both of the rung's rail verts are allowed to snap to it
            cands = []       # per rung: [candidate or None, candidate or None]
            rung_lengths = [] # world length of each rung, parallel to cands
            crosswise = []   # (rung index, side) whose candidate feature lies along the rung
            lengthwise = []  # rung indices whose two rails both snap to features lying across the rungs
            for i in range(len(bmvs[0])):
                pair = [
                    None if (bmv in reused_bmvs or bmv in existing_bmvs) else self.feature_snap_candidate(bmv.co)
                    for bmv in (bmvs[0][i], bmvs[1][i])
                ]
                cands += [ pair ]
                rung = (M @ bmvs[1][i].co) - (M @ bmvs[0][i].co)
                rung_lengths += [ rung.length ]
                if rung.length < 1e-9: continue # same vert on both rails: either snap writes the same co
                rung_dir = Direction(rung)
                along = [ bool(c and c['tangent'] and abs(c['tangent'].dot(rung_dir)) >= FEATURE_SNAP_PARALLEL) for c in pair ]
                crosswise += [ (i, side) for side in (0, 1) if along[side] ]
                if pair[0] and pair[1] and not all(along): lengthwise += [ i ]

            # Label the feature runs around every rung in question in a single pass, so the ids are
            # comparable strip-wide and the two limits below can be applied per run.
            involved = { i for (i, _) in crosswise } | set(lengthwise)
            if involved and self.source_accel:
                seeds = { s for i in involved for c in cands[i] if c and (s := c['seg']) is not None }
                margin = 2 * max(rung_lengths[i] for i in involved) # reach enough feature to connect a rung's two feet
                seg_run, _ = self.source_accel.local_runs(seeds, margin)

                # Across the rungs: keep, per run, the rail that is nearer to it overall.
                # Deciding per rung instead would zigzag the surviving rail from side to side when the feature runs down the middle of the strip.
                # Deciding per strip would force one rail on a strip that runs alongside one feature and then another.
                by_run = {}
                for i in lengthwise:
                    run = seg_run.get(cands[i][0]['seg'])
                    # No run topology to compare against: assume one run and veto rather than collapse.
                    if seg_run and run != seg_run.get(cands[i][1]['seg']): continue
                    by_run.setdefault(run, []).append(i)
                for rungs in by_run.values():
                    d0 = sum(cands[i][0]['dist'] for i in rungs)
                    d1 = sum(cands[i][1]['dist'] for i in rungs)
                    drop = 1 if d0 <= d1 else 0
                    for i in rungs: cands[i][drop] = None

                # Along a rung: keep only the nearest rung per run. A fold rung is already sitting on its
                # crease, so it wins over its neighbors on distance alone.
                by_run = {}
                for (i, side) in crosswise:
                    if not cands[i][side]: continue # already dropped as the farther rail
                    by_run.setdefault(seg_run.get(cands[i][side]['seg']), []).append((i, side))
                for entries in by_run.values():
                    nearest = {}
                    for (i, side) in entries:
                        d = cands[i][side]['dist']
                        nearest[i] = min(d, nearest.get(i, d))
                    keep = min(nearest, key=nearest.get)
                    for (i, side) in entries:
                        if i != keep: cands[i][side] = None

            # Only one vert should be allowed per feature corner
            def local_edge_length(i, side):
                ''' World length of the shortest strip edge meeting this rail vert, measured before any
                feature snapping. This is the scale a collapse has to beat. '''
                co = M @ bmvs[side][i].co
                nbrs = [ bmvs[1 - side][i] ] + [ bmvs[side][j] for j in (i - 1, i + 1) if 0 <= j < len(bmvs[side]) ]
                return min(((M @ nbr.co) - co).length for nbr in nbrs)
            claimed = []

            FEATURE_SNAP_MIN_SEPARATION = 0.25 # How far apart two snapped verts must stay, as a fraction of the shortest strip edge meeting them.
            for (i, side) in sorted(
                ( (i, side) for i, pair in enumerate(cands) for side in (0, 1) if pair[side] ),
                key=lambda e: cands[e[0]][e[1]]['dist'],
            ):
                cand = cands[i][side]
                min_sep = FEATURE_SNAP_MIN_SEPARATION * local_edge_length(i, side)
                for (co, dist) in [ (cand['co'], cand['dist']) ] + ([ cand['edge'] ] if cand['edge'] else []):
                    target = M @ co
                    if all((target - taken).length >= min_sep for taken in claimed):
                        cand['co'], cand['dist'] = co, dist
                        claimed += [ target ]
                        break
                else:
                    cands[i][side] = None

            for i, pair in enumerate(cands):
                for side, cand in enumerate(pair):
                    if cand: bmvs[side][i].co = cand['co']

            ######################################################
            # handle mirror
            m,mt = self.mirror,self.mirror_threshold
            mx,my,mz = self.mirror_side
            for bmvs_ in bmvs:
                for bmv in bmvs_:
                    if bmv in reused_bmvs: continue
                    co = bmv.co
                    v = Vector((
                        0 if 'x' in m and sign_threshold(co.x, mt) != mx else 1,
                        0 if 'y' in m and sign_threshold(co.y, mt) != my else 1,
                        0 if 'z' in m and sign_threshold(co.z, mt) != mz else 1,
                    ))
                    bmv.co = v * co


            ######################################################
            # create bmfaces

            bmfs = []
            new_bmfs = []
            for i in range(0, len(bmvs[0])-1):
                bmv00, bmv01 = bmvs[0][i], bmvs[0][i+1]
                bmv10, bmv11 = bmvs[1][i], bmvs[1][i+1]
                verts = dedup(bmv00, bmv01, bmv11, bmv10)  # Fix 1588: faces.new(...): found the same (BMVert) used multiple times
                if len(verts) < 3:
                    print(f'WARNING: Cannot create face with {len(verts)=} verts {verts=}')
                    continue
                # Existing faces can join the strip as-is
                bmf = self.bm.faces.get(verts)
                if bmf is None:
                    bmf = self.bm.faces.new(verts)
                    new_bmfs.append(bmf)
                elif DEBUG_SIDEJOIN:
                    print(f'[sidejoin] seg {i_strip}: quad {i} already exists, reusing {bmf.index=}')
                bmfs += [ bmf ]
                select_geo.append(bmf)
            orient_bmf_normals(context, new_bmfs, new_faces=True)

            if snap_bmf1 is None: snap_bmf1 = bmfs[-1]
            actual_strip_count += 1

        ########################################
        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, select_geo)
        bmops.flush_selection(self.bm, self.em)

        self.count_mins = ncount_mins
        self.counts = ncounts
        self.strip_count = actual_strip_count
        self.count_locked = has_anchor and not has_free  # Fully welded: the count is fixed by the geometry and must not be editable.
        self.attached = has_anchor # Any weld at all: the redo panel's Interpolate Rungs option is relevant
        self.count_total = sum(self.counts) # Keeps the displayed/scrollable total in sync with what's actually built.

        # the snapped-derived count and any other first-build-only sizing is now baked into count_total.
        # Subsequent (redo/scroll) builds must respect the artist's adjustments instead of re-deriving.
        self.initial = False


    def release(self):
        """ Drop the BMesh working state to avoid stale references. """
        self.bm, self.em = None, None

    def update_context(self, context):
        # this should be called whenever the context could change

        # gather bmesh data
        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        bmops.flush_selection(self.bm, self.em)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe()
        self.edit_scale = max(self.matrix_world.to_scale())
        self.bm.verts.ensure_lookup_table()
        self.bm.edges.ensure_lookup_table()
        self.bm.faces.ensure_lookup_table()
        self.bvh = BVHTree.FromBMesh(self.bm)

    def compute_length3D(self, stroke3D_local, is_cycle):
        M = self.matrix_world
        return sum(
            ((M @ p1) - (M @ p0)).length
            for (p0, p1) in iter_pairs(stroke3D_local, is_cycle)
        )






    #####################################################################################
    # utility functions

    def project_pt(self, context, pt):
        p = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt)
        return p.xy if p else None
    def project_bmv(self, context, bmv):
        p = self.project_pt(context, bmv.co)
        return p.xy if p else None
    def nearest_point(self, context, p):
        snapped = nearest_point_valid_sources(context, self.matrix_world @ p, respect_clip_planes=True)
        return self.matrix_world_inv @ snapped if snapped else p
    def feature_snap_candidate(self, co_local):
        ''' Nearest source feature to a local-space coordinate, or None when nothing is within
        feature_radius. Never write this straight onto a vert. The caller has to arbitrate between
        the rung's two rails and its neighbouring rungs first. Returns a dict of:
            co, dist        the snap target in local space and its world distance — the nearest
                            corner when one is in range, else the nearest point on a feature edge
            tangent, seg    direction and segment index of the nearest feature edge, given even
                            when a corner won the target, so callers can tell which way the
                            feature runs and which run it belongs to
            edge            the feature edge target as (co, dist), for a caller that has to give
                            up a corner but wants to stay on the feature. None when the target
                            already is the edge, or no edge is in range. '''
        accel = self.source_accel
        if not accel or self.feature_radius <= 0:
            return None
        co_world = self.matrix_world @ co_local
        found = accel.closest_point_with_index(co_world)
        tangent, seg = (Direction(found[1]), found[2]) if found else (None, None)
        edge = None
        if found and (dist := (Vector(found[0]) - co_world).length) <= self.feature_radius:
            edge = (self.matrix_world_inv @ Vector(found[0]), dist)
        corner = accel.find_corner(co_world)
        if corner and corner[2] <= self.feature_radius:
            co, dist, fallback = self.matrix_world_inv @ Vector(corner[0]), corner[2], edge
        elif edge:
            co, dist, fallback = edge[0], edge[1], None
        else:
            return None
        return { 'co': co, 'dist': dist, 'tangent': tangent, 'seg': seg, 'edge': fallback }
    def fold_crease_point(self, p_local, p_before, n_before, p_after, n_after, *, max_plane_dist):
        ''' Thin wrapper over common.snapping.fold_crease using this tool's source accel /
        feature radius. Returns (crease_point, crease_dir) in local space, or None. '''
        return fold_crease(
            p_local, p_before, n_before, p_after, n_after,
            self.matrix_world, self.matrix_world_inv,
            source_accel=self.source_accel, feature_radius=self.feature_radius,
            max_plane_dist=max_plane_dist,
        )
    def bmv_closest(self, bmvs, pt3D):
        pt2D = self.project_pt(context, pt3D)
        # bmvs = [bmv for bmv in bmvs if bmv.select and (pt := self.project_bmv(bmv)) and (pt - pt2D).length_squared < 20*20]
        bmvs = [bmv for bmv in bmvs if (pt := self.project_bmv(context, bmv)) and (pt - pt2D).length_squared < 20*20]
        if not bmvs: return None
        return min(bmvs, key=lambda bmv: (bmv.co - pt3D).length_squared)
