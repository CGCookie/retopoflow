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
import bmesh
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
from ..common.raycast import raycast_ray_valid_sources, nearest_point_valid_sources, nearest_normal_valid_sources
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
from ...addon_common.common.utils import iter_pairs, dedup

import math
from itertools import chain

DEBUG_WELDS = False


r'''

Desmos demo: https://www.desmos.com/geometry/okxgsddxk2

NOT HANDLING CYCLIC STROKES, YET

'''



def final_face_entry_index(stroke, bmf):
    ''' Index of the first point of the inside-bmf run the stroke ends in, or None when the stroke
    never enters the face. '''
    # Scan backwards not forwards so we don't get an initially grazed edge
    point_inside_bmf = generate_point_inside_bmf(bmf)
    inside = [point_inside_bmf(pt) for pt in stroke]
    j = next((k for k in range(len(stroke) - 1, -1, -1) if inside[k]), None)
    if j is None: return None
    i = j
    while i > 0 and inside[i - 1]: i -= 1
    tol = 0.5 * sum(bme_length(bme) for bme in bmf.edges) / max(1, len(bmf.edges))
    k, acc = i - 1, 0.0
    while k >= 0:
        acc += (stroke[k + 1] - stroke[k]).length
        if acc > tol: break
        if inside[k]: i = k
        k -= 1
    return i

def crossed_bme_of_bmf(bmf, bmes, segment):
    ''' The candidate edge of bmf that `segment` actually crosses, projected into the face's plane.
    None when nothing is crossed. '''
    cos3D = [bmv.co for bmv in bmf.verts]
    o = sum(cos3D, Vector()) / len(cos3D)
    z, x = Vector(bmf.normal), cos3D[0] - o
    if z.length_squared == 0 or x.length_squared == 0: return None
    x = x.normalized()
    y = z.normalized().cross(x)
    to2D = lambda p: Vector(((p - o).dot(x), (p - o).dot(y)))
    a2, b2 = to2D(segment[0]), to2D(segment[1])
    d2 = b2 - a2
    if d2.length_squared == 0: return None
    d2.normalize()
    best = None
    for bme in bmes:
        e0, e1 = (to2D(bmv.co) for bmv in bme.verts)
        if segment2D_intersection(a2, b2, e0, e1) is None: continue
        e2 = e1 - e0
        if e2.length_squared == 0: continue
        score = abs(e2.normalized().dot(d2))  # 0 = perpendicular to the approach
        if best is None or score < best[0]: best = (score, bme)
    return best[1] if best else None

def trim_stroke_to_bmf(stroke, bmf, from_start, limit_bmes=None):
    if not bmf: return None

    # Connect to the edge the stroke entered through, not whichever edge the end happens to drift closest to.
    if from_start:
        # stroke begins inside the face and exits: cut at the exit
        point_inside_bmf = generate_point_inside_bmf(bmf)
        i = next((i for (i,pt) in enumerate(stroke) if not point_inside_bmf(pt)), None)
        if i is None: return {'error': 'stroke totally inside the hovered face'}
        inside, outside = stroke[:i], stroke[i:]
        search = (inside[-1:] + outside[:1]) or [stroke[0]]
        inside_pt = inside[-1] if inside else None
    else:
        # stroke enters and ends inside: cut where the run the stroke ends in was entered
        i = final_face_entry_index(stroke, bmf)
        if i == 0:
            return {'error': 'stroke totally inside the hovered face'}
        if i is None:
            # face was snapped by proximity, but the stroke never actually entered it: keep it all
            outside, search, inside_pt = stroke, stroke[-2:], None
        else:
            outside, search, inside_pt = stroke[:i], stroke[i-1:i+1], stroke[i]

    if limit_bmes:
        bmes = limit_bmes
    else:
        bmes = bmf.edges
    if not bmes: return None
    bme = crossed_bme_of_bmf(bmf, bmes, search) if (inside_pt is not None and len(search) == 2) else None
    if bme is None:
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

def smoothed_stroke_normals(stroke, normals, window):
    ''' Box average of per-point source normals over ±window of stroke arclength (prefix sums, O(n)). '''
    n = len(stroke)
    if n <= 2 or window <= 0: return list(normals)
    cumul = [0.0]
    for i in range(1, n):
        cumul.append(cumul[-1] + (stroke[i] - stroke[i - 1]).length)
    pre = [Vector((0.0, 0.0, 0.0))]
    for no in normals:
        pre.append(pre[-1] + no)
    out, j0, j1 = [], 0, 0
    for i in range(n):
        while j0 < i and cumul[j0] < cumul[i] - window: j0 += 1
        while j1 < n - 1 and cumul[j1 + 1] <= cumul[i] + window: j1 += 1
        v = pre[j1 + 1] - pre[j0]
        out.append(Direction(v) if v.length_squared > 0 else normals[i])
    return out


def stroke_angles(stroke, width, split_angle, normals):
    # convert radians to degrees
    split_angle = math.degrees(split_angle)

    # determine where stroke angles very strongly
    l = []
    for (i, p) in enumerate(stroke):
        ip = next((k for k in range(i, -1, -1)      if (p - stroke[k]).length >= width), None)
        iq = next((k for k in range(i, len(stroke)) if (p - stroke[k]).length >= width), None)
        if ip is None or iq is None: continue
        pp, pn = stroke[ip], stroke[iq]

        n = normals[i]
        np, nn = normals[ip], normals[iq]
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


def stroke_normal_bends(stroke, width, split_angle, normals):
    ''' Indices where the surface normal bends sharply along the stroke.
    Returns interior stroke indices only (never 0 or len(stroke)). '''
    n = len(stroke)
    if n < 3:
        return []
    split_angle = math.degrees(split_angle)

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
                    size_mode='BRUSH', fixed_count=8, span_length=0.1, radius3D=None, join_bmes=None,
                    cap_bme0=None, cap_bme1=None):
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
        self.cap_bme0_index = cap_bme0.index if cap_bme0 else None
        self.cap_bme1_index = cap_bme1.index if cap_bme1 else None
        self.join_bme_indices = [bme.index for bme in join_bmes if bme.is_valid] if join_bmes else []
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
        self.count_warning = None  # set when Ctrl+Scroll asks for fewer quads than the welds require
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


    def fetch_join_bmes(self, exclude_bmes):
        ''' Returns the swept edges minus the excluded ones. '''
        out = []
        for i in self.join_bme_indices:
            if not (0 <= i < len(self.bm.edges)): continue
            bme = self.bm.edges[i]
            if not bme.is_valid or bme in exclude_bmes: continue
            if bme_length(bme) == 0: continue
            out.append(bme)
        return out

    def build_weld_runs(self, join_bmes, stroke, cumlen_local, end_welds, base_width, exclude_bmes=None):
        ''' Chain the swept edges into runs, the ordered existing-vert paths the strip welds to directly.
        `end_welds` is [(bme, at_start), ...], for the edges that become the caps.
        Returns (runs sorted along the stroke, consumed end-weld edges). '''
        nstroke = len(stroke)
        total_local = cumlen_local[-1] or 1.0
        end_bmes = {bme for (bme, _) in end_welds if bme is not None}
        rails = [bme for bme in join_bmes if bme not in end_bmes]

        # An unswept edge whose both verts are swept belongs to the weld too and is considered an accidental miss.
        # But it must join two separate swept pieces, otherwise creating a U around a single quad would incorrectly add the 4th edge.
        skip = end_bmes | set(exclude_bmes or ())
        parent = {}
        def find(v):
            while parent[v] != v:
                parent[v] = parent[parent[v]]; v = parent[v]
            return v
        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb: parent[ra] = rb
        for bme in rails:
            for bmv in bme.verts: parent.setdefault(bmv, bmv)
        for bme in rails: union(*bme.verts)
        rail_set = set(rails)
        for bme in {e for bmv in list(parent) for e in bmv.link_edges}:
            if bme in rail_set or bme in skip: continue
            if not (bme.is_boundary or bme.is_wire) or bme_length(bme) == 0: continue
            v0, v1 = bme.verts
            if v0 not in parent or v1 not in parent: continue
            if find(v0) == find(v1): continue  # would close a loop
            union(v0, v1)
            rails.append(bme)
            rail_set.add(bme)
            if DEBUG_WELDS: print(f'[weld] filled gap edge e{bme.index} (both verts swept)')

        by_vert = {}
        for bme in rails:
            for bmv in bme.verts:
                by_vert.setdefault(bmv, []).append(bme)

        unused = set(rails)
        def walk(v_start, bme_start):
            chain_verts = [v_start, bme_start.other_vert(v_start)]
            unused.discard(bme_start)
            while True:
                v = chain_verts[-1]
                if len(by_vert.get(v, [])) > 2: break  # branch vert: end the chain here
                nxt = [e for e in by_vert.get(v, []) if e in unused]
                if len(nxt) != 1: break
                e = nxt[0]
                unused.discard(e)
                chain_verts.append(e.other_vert(v))
            return chain_verts
        chains = []
        for bme in rails:  # open chains first, walked from their end verts
            if bme not in unused: continue
            v_end = next((v for v in bme.verts if len(by_vert[v]) == 1), None)
            if v_end is not None: chains.append(walk(v_end, bme))
        for bme in rails:  # leftovers: cycles and branch-bounded chains
            if bme not in unused: continue
            chains.append(walk(bme.verts[0], bme))

        def closest_pt_on_stroke(pt):
            best = None
            for si in range(nstroke - 1):
                cp = closest_point_segment(pt, stroke[si], stroke[si + 1])
                d = (cp - pt).length
                if best is None or d < best[0]:
                    best = (d, cumlen_local[si] + (cp - stroke[si]).length, cp)
            return best  # (dist, local arclength, point on stroke)

        runs = []
        for verts in chains:
            feet = [closest_pt_on_stroke(v.co) for v in verts] # as in foot of the perpendicular
            als = [f[1] for f in feet]
            if als[0] > als[-1]:
                verts, feet, als = verts[::-1], feet[::-1], als[::-1]
            span = max(als) - min(als)
            run_len = sum((b.co - a.co).length for (a, b) in iter_pairs(verts, False))
            # An edge only welds when the stroke actually travels along it
            if span < 0.3 * run_len:
                if DEBUG_WELDS: print(f'[weld] dropped chain of {len(verts)-1} edges: span={span:.4f} < 0.3*len={run_len:.4f}')
                continue
            runs.append({
                'verts': verts, 'feet': feet,
                'fracs': [clamp(al / total_local, 0.0, 1.0) for al in als],
                'al0': min(als), 'al1': max(als),
                'start_bme': None, 'end_bme': None,
            })

        # Attach caps at the stroke ends that share a vert with the side rails run end
        consumed = set()
        for (bme, at_start) in end_welds:
            if bme is None: continue
            for run in runs:
                rv = run['verts']
                if bme.verts[0] in rv and bme.verts[1] in rv: continue  # edge lies inside the run
                key, end_v = ('start_bme', rv[0]) if at_start else ('end_bme', rv[-1])
                if (bme.verts[0] is end_v or bme.verts[1] is end_v) and run[key] is None:
                    run[key] = bme
                    consumed.add(bme)
                    break

        runs.sort(key=lambda r: r['al0'])
        # overlapping runs can't stack in one strip, keep the one the stroke travels along longest
        kept = []
        for run in runs:
            if kept and run['al0'] < kept[-1]['al1'] - 0.25 * base_width:
                worse = min((kept[-1], run), key=lambda r: r['al1'] - r['al0'])
                if DEBUG_WELDS: print(f'[weld] dropped overlapping run ({len(worse["verts"])-1} edges)')
                for bme in (worse['start_bme'], worse['end_bme']):
                    if bme is not None: consumed.discard(bme)
                if worse is kept[-1]: kept[-1] = run
                continue
            kept.append(run)
        return kept, consumed

    def plan_run(self, context, run):
        '''
        Decide a run's rungs and quads so the quad counts are known before the count budget is spent.
        Corner types:
        * EXTERNAL: weld inside the turn, e.g. wrapping around a quad
        * INTERNAL: weld outside the turn, e.g. wrapping inside a concave shape
        '''
        M = self.matrix_world
        verts, feet = run['verts'], run['feet']
        n = len(verts)

        # Rung direction per vert: perpendicular to the run, lying in the surface, pointing toward the stroke.
        # The existing edges define the direction, the stroke defines the side and the width.
        # "In the surface" is defined by the surface normal sampled at the vert's closest point on the stroke.
        perps, sides, nrms = [], [], []
        for i, v in enumerate(verts):
            d = verts[min(n - 1, i + 1)].co - verts[max(0, i - 1)].co
            nrm = Direction(nearest_normal_valid_sources(context, M @ feet[i][2], world=False))
            nrms.append(nrm)
            p = d.cross(nrm)
            p = p.normalized() if p.length else Vector((0.0, 0.0, 0.0))
            s = p.dot(feet[i][2] - v.co)
            sides.append(0.0 if abs(s) < 0.05 * (d.length or 1.0) else (1.0 if s > 0 else -1.0))
            perps.append(p)
        # a vert sitting on the stroke can't tell its side so inherit a neighbor's
        for i in range(n):
            if sides[i] == 0.0:
                sides[i] = next((sides[j] for j in list(range(i - 1, -1, -1)) + list(range(i + 1, n)) if sides[j] != 0.0), 1.0)
        perps = [p * s for (p, s) in zip(perps, sides)]

        corner = {}
        cos_split = math.cos(self.split_angle)
        for i in range(1, n - 1):
            d_in, d_out = verts[i].co - verts[i - 1].co, verts[i + 1].co - verts[i].co
            if d_in.length == 0 or d_out.length == 0: continue
            if d_in.normalized().dot(d_out.normalized()) > cos_split: continue
            # Sharp bend! Test if it is a bend with the surface (fold) or across the surface (corner).
            # For vert C on the crease, X = B + D - C gives us a supposed forth point to complete the quad.
            # If X is within a quarter edge len of the surface we get a corner, if not we are on a fold.
            X = verts[i - 1].co + verts[i + 1].co - verts[i].co
            if (self.nearest_point(context, X) - X).length > 0.25 * min(d_in.length, d_out.length):
                continue
            # continuing the grid through the corner lands on the strip's side only when the strip
            # is inside the wedge, i.e. the weld is on the outside of the turn
            corner[i] = 'int' if (X - verts[i].co).dot(feet[i][2] - verts[i].co) > 0 else 'ext'

        plans, quads, shared_cos = [], [], []
        i = 0
        while i < n:
            c = corner.get(i)
            # the last vert keeps its own rung when it carries the run's end rung
            if c == 'int' and plans and i < n - 1 and not (i + 1 == n - 1 and run['end_bme'] is not None):
                B, C, D = verts[i - 1], verts[i], verts[i + 1]
                sid = len(shared_cos)
                shared_cos.append((B.co + D.co - C.co, i))
                plans[-1]['outer'] = ('shared', sid)  # B's rung pinches onto the pivot
                a = len(plans)
                plans.append({'inner': D, 'outer': ('shared', sid)})
                quads.append(('int', a - 1, a, C))
                i += 2  # C carries no rung of its own; D's rung is placed
                continue
            if c == 'ext' and plans and i < n - 1:
                a = len(plans)
                plans.append({'inner': verts[i], 'outer': ('extF', i)})  # closes the incoming arm
                quads.append(('bridge', a - 1, a))
                plans.append({'inner': verts[i], 'outer': ('extG', i)})  # opens the outgoing arm
                quads.append(('ext', a, a + 1, i))
                i += 1
                continue
            if i == 0 and run['start_bme'] is not None:
                outer = ('bmv', run['start_bme'].other_vert(verts[0]))
            elif i == n - 1 and run['end_bme'] is not None:
                outer = ('bmv', run['end_bme'].other_vert(verts[-1]))
            else:
                outer = ('perp', i)
            a = len(plans)
            plans.append({'inner': verts[i], 'outer': outer})
            if a > 0: quads.append(('bridge', a - 1, a))
            i += 1
        run.update(perps=perps, nrms=nrms, corner=corner, plans=plans, quads=quads, built=len(quads), shared_cos=shared_cos)

    def emit_run(self, context, run, width_at_frac, select_geo):
        ''' Create a planned run's rungs and quads. The existing verts are the welded rail and the new
        outer verts continue the existing grid or offset perpendicular. '''
        M = self.matrix_world
        verts, perps, fracs, nrms = run['verts'], run['perps'], run['fracs'], run['nrms']

        def fw(i):  # full (rail-to-rail) width at run vert i
            return 2 * width_at_frac(fracs[i])

        def new_vert(co, i):
            # snap along run vert i's normal, not nearest surface point, so a bumpy surface can't cause tilt
            snapped = self.snap_to_source(context, co, along_local=nrms[i], max_correction=fw(i))
            return self.bm.verts.new(snapped if snapped is not None else co)

        def outer_co(i):
            v = verts[i]
            if self.interpolate_rungs:
                co = self.grid_outward_co(v, perps[i], fw(i))
                if co is not None: return co
            return v.co + perps[i] * fw(i)

        def ext_co(i, toward):
            # continue the neighboring arm's rail direction past the corner vert
            C = verts[i].co
            d = C - toward.co
            return C + (d.normalized() * fw(i) if d.length else Vector((0.0, 0.0, 0.0)))

        # a shared pivot belongs to the corner vert between the two arms it joins
        shared_verts = [new_vert(co, i) for (co, i) in run['shared_cos']]
        made = []
        for p in run['plans']:
            kind, val = p['outer']
            if   kind == 'bmv':    outer_v = val
            elif kind == 'shared': outer_v = shared_verts[val]
            elif kind == 'extF':   outer_v = new_vert(ext_co(val, verts[val + 1]), val)
            elif kind == 'extG':   outer_v = new_vert(ext_co(val, verts[val - 1]), val)
            else:                  outer_v = new_vert(outer_co(val), val)
            made.append((p['inner'], outer_v))

        new_bmfs, built = [], 0
        def make_quad(vs):
            nonlocal built
            vs = dedup(*vs)
            if len(vs) < 3:
                print('WARNING: run quad degenerate, skipped')
                return
            bmf = self.bm.faces.get(vs)
            if bmf is None:
                bmf = self.bm.faces.new(vs)
                new_bmfs.append(bmf)
            select_geo.append(bmf)
            built += 1
        for (kind, ia, ib, *rest) in run['quads']:
            a, b = made[ia], made[ib]
            if kind == 'bridge':
                make_quad((a[0], b[0], b[1], a[1]))
            elif kind == 'int':
                corner_C, = rest
                make_quad((a[0], corner_C, b[0], a[1]))  # (B, C, D, X) where X is the shared pivot
            else:  # 'ext': corner quad (F0, K, G, C) continuing the grid diagonally past C
                i_corner, = rest
                C = a[0]
                K = new_vert(a[1].co + b[1].co - C.co, i_corner)
                make_quad((a[1], K, b[1], C))
        orient_bmf_normals(context, new_bmfs, new_faces=True)

        run['first_pair'], run['last_pair'] = made[0], made[-1]
        d0 = verts[0].co - verts[1].co
        d1 = verts[-1].co - verts[-2].co
        run['out_start'] = Direction(d0) if d0.length else None
        run['out_end']   = Direction(d1) if d1.length else None
        run['built'] = built
        if DEBUG_WELDS:
            print(f'[weld] emitted run: {len(verts)} verts, {built} quads, corners={run["corner"]}, '
                  f'start_bme={run["start_bme"].index if run["start_bme"] else None} end_bme={run["end_bme"].index if run["end_bme"] else None}')

    @staticmethod
    def pair_snap(pair, outward):
        ''' Snap dict for a rung that already exists as two verts (a welded run's end rung),
        interchangeable with a trim / cap snap dict at a free span's end. '''
        v_in, v_out = pair
        return {
            'pair': pair, 'outward': outward,
            'bme.center': (v_in.co + v_out.co) / 2, 'bme.radius': (v_in.co - v_out.co).length / 2,
        }

    @staticmethod
    def grid_outward_co(bmv, dir_outward, width):
        ''' Position for a rung's outer vert, continuing the existing grid outward from the welded vert `bmv`:
        `width` along whichever of its edges best matches `dir_outward`. Returns None when it has no outgoing edge. '''
        # The edge has to agree with the rung direction to be worth continuing.
        best_dir, best_dot = None, 0.5 # 0.5 is roughly 60 degrees
        for e in bmv.link_edges:
            other = e.other_vert(bmv)
            d = bmv.co - other.co
            if d.length == 0: continue
            d = d.normalized()
            dot = d.dot(dir_outward)
            if dot > best_dot:
                best_dot, best_dir = dot, d
        if best_dir is None: return None
        return bmv.co + best_dir * width

    @staticmethod
    def rail_sizing_length(bme):
        ''' Sizing length for a swept rail edge. On a quad the stroke is parallel to, averages the perpendicular edges,
        i.e. the quad's depth. Otherwise, uses the edge length itself. '''
        quads = [bmf for bmf in bme.link_faces if len(bmf.edges) == 4]
        if not quads:
            return bme_length(bme)
        bme_verts = set(bme.verts)
        sides = [
            bme_length(e)
            for bmf in quads
            for e in bmf.edges
            # a quad's side edges share exactly one vert with bme; the opposite edge shares none
            if e is not bme and len(set(e.verts) & bme_verts) == 1
        ]
        return (sum(sides) / len(sides)) if sides else bme_length(bme)

    @staticmethod
    def snapped_edge_radius(bmf, pts):
        ''' Half-length in local space of the snapped face's edge nearest the given stroke points. '''
        if not bmf or not pts: return None
        bmes = list(bmf.edges)
        if not bmes: return None
        bme = min(bmes, key=lambda bme: min(distance_point_bmedge(pt, bme) for pt in pts))
        return bme_length(bme) / 2

    @staticmethod
    def face_entry_points(bmf, stroke_pts, from_start):
        ''' The crossing pair where the stroke exits (from_start) or enters (not from_start) the snapped face.
        Falls back to the stroke's own end when the stroke never crosses the face boundary. '''
        if not bmf or not stroke_pts: return None
        if from_start:
            point_inside_bmf = generate_point_inside_bmf(bmf)
            i = next((i for (i, pt) in enumerate(stroke_pts) if not point_inside_bmf(pt)), None)
            if i is None: return stroke_pts[:2]
            return stroke_pts[max(0, i - 1):i + 1]
        i = final_face_entry_index(stroke_pts, bmf)
        if i is None or i == 0: return stroke_pts[-2:]
        return stroke_pts[i - 1:i + 1]

    @staticmethod
    def snapped_edges_radius(bmes):
        ''' Average half-length (local space) of a set of existing edges. Returns None when there are no valid edges. '''
        lengths = [bme_length(bme) for bme in (bmes or ()) if getattr(bme, 'is_valid', False)]
        if not lengths: return None
        return (sum(lengths) / len(lengths)) / 2

    @staticmethod
    def weld_edge_outward(bme, toward_pt):
        ''' The welded edge's in-plane normal, oriented away from its face toward `toward_pt`.
        None for a degenerate edge/normal. '''
        edir = bme_vector(bme)
        nrm = Vector((0.0, 0.0, 0.0))
        for bmf in bme.link_faces:
            nrm += bmf.normal
        if edir.length == 0 or nrm.length == 0: return None
        perp = edir.normalized().cross(nrm.normalized())
        if perp.length == 0: return None
        perp.normalize()
        if perp.dot(toward_pt - bme_midpoint(bme)) < 0: perp = -perp
        return perp

    @staticmethod
    def nearest_edge_halfwidth(edges, ref_pt, *, max_dist=None, rail_sizing=False):
        ''' Half length (local space) of the edge in `edges` whose closest point to ref_pt is nearest, or None. `edges` must be pre-filtered.
        Pass max_dist (a multiple of the edge's length) to reject an edge whose nearest point is farther away than that.
        rail_sizing sizes each edge by its quad's depth instead of its own length, so pass it for rails, not caps.
        '''
        best = None
        for bme in edges:
            v0, v1 = bme.verts
            d = (closest_point_segment(ref_pt, v0.co, v1.co) - ref_pt).length
            L = (v1.co - v0.co).length
            if max_dist is not None and d > L * max_dist: continue
            if best is None or d < best[0]:
                best = (d, (PolyStrips_Logic.rail_sizing_length(bme) if rail_sizing else L) / 2)
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



        M, Mi = self.matrix_world, self.matrix_world_inv

        select_geo = []

        # deal with snapping stroke to bmfs hovered at beginning and ending of stroke
        snap_bmf_start, snap_bmf_end = None, None
        if self.snap_bmf0_index is not None:
            snap_bmf_start = self.bm.faces[self.snap_bmf0_index]
        if self.snap_bmf1_index is not None:
            snap_bmf_end = self.bm.faces[self.snap_bmf1_index]

        def fetch_cap(idx, bmf):
            if bmf is not None or idx is None or not (0 <= idx < len(self.bm.edges)): return None
            bme = self.bm.edges[idx]
            return bme if bme.is_valid else None
        cap_bme_start = fetch_cap(self.cap_bme0_index, snap_bmf_start)
        cap_bme_end   = fetch_cap(self.cap_bme1_index, snap_bmf_end)

        # the swept rail edges (the end-weld cap edges are end rungs, never rails)
        join_bmes = self.fetch_join_bmes({bme for bme in (cap_bme_start, cap_bme_end) if bme is not None})
        if DEBUG_WELDS: print(f'[weld] size_mode={self.size_mode} join_bmes={len(join_bmes)} (of {len(self.join_bme_indices)} given)')

        w_snap_start = w_snap_end = None
        if self.size_mode == 'SNAPPED':
            # size to the connection edge (where the stroke crosses the face boundary), matching trim_stroke_to_bmf
            w_snap_start = self.snapped_edge_radius(snap_bmf_start, self.face_entry_points(snap_bmf_start, self.stroke3D_local, True))
            w_snap_end   = self.snapped_edge_radius(snap_bmf_end,   self.face_entry_points(snap_bmf_end,   self.stroke3D_local, False))
            if w_snap_start is None and cap_bme_start is not None: w_snap_start = bme_length(cap_bme_start) / 2
            if w_snap_end   is None and cap_bme_end   is not None: w_snap_end   = bme_length(cap_bme_end) / 2
            # Width priority: faces and caps, then the first swept rail edge
            if (w_snap_start is None or w_snap_end is None) and join_bmes:
                # the rail edge nearest the start sets the width for the whole run,
                # so drawing past rails of varying length doesn't make the strip fluctuate.
                kloc = min(3, len(self.stroke3D_local) - 1)
                start = self.stroke3D_local[0]
                along = (self.stroke3D_local[kloc] - start) if kloc > 0 else Vector((0, 0, 0))
                along = along.normalized() if along.length else None
                def is_parallel(e):  # skip edges perpendicular to the start tangent
                    ev = e.verts[1].co - e.verts[0].co
                    return ev.length != 0 and (not along or abs(ev.normalized().dot(along)) > 0.6)
                w_par = self.nearest_edge_halfwidth([e for e in join_bmes if is_parallel(e)], start, rail_sizing=True)
                if w_snap_start is None: w_snap_start = w_par
                if w_snap_end is None: w_snap_end = w_par

        scale = sum(M.to_scale()) / 3

        # Trim the stroke onto the snapped end faces so later steps get the right stroke length
        self.count_warning = None
        limit_start = [bme for bme in snap_bmf_start.edges if bme.is_boundary] if snap_bmf_start else None
        snap_start = trim_stroke_to_bmf(self.stroke3D_local, snap_bmf_start, True, limit_start)
        if snap_start:
            if snap_start['error']:
                self.error = True
                print(f'ERROR: {snap_start["error"]} on start trim')
                return
            self.stroke3D_local = snap_start['stroke']
        limit_end = [bme for bme in snap_bmf_end.edges if bme.is_boundary] if snap_bmf_end else None
        snap_end = trim_stroke_to_bmf(self.stroke3D_local, snap_bmf_end, False, limit_end)
        if snap_end:
            if snap_end['error']:
                self.error = True
                print(f'ERROR: {snap_end["error"]} on end trim')
                return
            self.stroke3D_local = snap_end['stroke']
        if len(self.stroke3D_local) < 2 or (self.stroke3D_local[0] - self.stroke3D_local[-1]).length == 0:
            self.error = True
            print('ERROR: stroke degenerate after end trims')
            return

        def cap_snap(bme):
            # the stroke already terminates on a cap edge, so there is nothing to trim
            return {'bme': bme, 'bme.center': bme_midpoint(bme), 'bme.radius': bme_length(bme) / 2}

        # break stroke into segments. Cached, since this raycasts a normal at nearly every point
        # along the raw stroke, but its result only ever changes with split_angle or mirror settings.
        stroke_angles_key = (self.split_angle, frozenset(self.mirror), tuple(self.mirror_side), self.mirror_threshold)
        if self._stroke_angles_cache_key == stroke_angles_key:
            strips, bend_indices = self._stroke_angles_cache
        else:
            fn_normal = lambda p: nearest_normal_valid_sources(context, M @ p, world=False)
            width_local = self.initial_width / scale
            # One raycast normal per point, box-averaged at half the strip width so surface
            # bumps well below the strip scale can't read as folds.
            normals = smoothed_stroke_normals(
                self.stroke3D_local,
                [Direction(fn_normal(p)) for p in self.stroke3D_local],
                width_local * 0.5,
            )
            # Two kinds of sharp corner, each with its own geometry.
            # - TANGENT (in-plane turn, flat-surface strip corner):
            #       split the stroke into segments so the strip pivots.
            # - NORMAL (a fold over a source edge, straight in-plane):
            #       do not split (#1601) and instead force a rung onto the fold.
            strips = stroke_angles(self.stroke3D_local, width_local, self.split_angle, normals)
            corner_set = set(strips)
            bend_indices = [
                i for i in stroke_normal_bends(self.stroke3D_local, width_local, self.split_angle, normals)
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

        # NOTE: base_width is in local space, self.initial_width is world space
        base_width = self.initial_width / self.edit_scale

        # local-space arclength, for placing the weld runs
        cumlen_local = [0.0]
        for (p0, p1) in iter_pairs(self.stroke3D_local, False):
            cumlen_local.append(cumlen_local[-1] + (p1 - p0).length)
        total_local = cumlen_local[-1] or 1.0

        # --- weld map: chain the swept edges into runs, absorbing the end welds that connect ---
        start_weld = snap_start['bme'] if snap_start else cap_bme_start
        end_weld   = snap_end['bme'] if snap_end else cap_bme_end
        # a snapped end face's own edges are never rails (the brush excludes them too), so the
        # gap fill must not pull one in through the face's two swept corner verts
        snapped_face_bmes = {bme for bmf in (snap_bmf_start, snap_bmf_end) if bmf is not None for bme in bmf.edges}
        runs, consumed = self.build_weld_runs(
            join_bmes, self.stroke3D_local, cumlen_local,
            [(start_weld, True), (end_weld, False)], base_width,
            exclude_bmes=snapped_face_bmes,
        )
        for run in runs:
            self.plan_run(context, run)
        # a weld a run absorbed is that run's end rung, one left over still needs its own end quad
        start_standalone = start_weld is not None and start_weld not in consumed
        end_standalone   = end_weld is not None and end_weld not in consumed

        # ---- section plan: welded runs, and free spans (split at stroke corners) between them ----
        def idx_at_al(al):
            return next((j for j in range(nstroke) if cumlen_local[j] >= al), nstroke - 1)
        sections = []
        def add_free_sections(jA, jB):
            jA = max(0, min(jA, nstroke - 2))  # a free span needs at least two stroke points
            jB = min(nstroke, max(jB, jA + 2))
            splits = [s for s in strips if jA < s < jB]
            for (a, b) in iter_pairs([jA] + splits + [jB], False):
                if b <= a: continue
                sections.append({'kind': 'free', 'i0': a, 'i1': b})
        min_leftover = 1.5 * base_width # Anything smaller than this (base_width is half a quad) on the ends is trimmed
        cursor = 0
        for run in runs:
            j0, j1 = idx_at_al(run['al0']), idx_at_al(run['al1'])
            gap = cumlen_local[min(j0, nstroke - 1)] - cumlen_local[min(cursor, nstroke - 1)]
            need_bridge = (
                (not sections and start_standalone)     # a start weld the first run didn't absorb
                or (sections and sections[-1]['kind'] == 'run')  # two runs that don't touch
                or gap > min_leftover                   # stroke left the geometry in between
            )
            if need_bridge:
                add_free_sections(cursor, max(j0, cursor))
            sections.append({'kind': 'run', 'run': run})
            cursor = max(cursor, j1)
        tail_gap = total_local - cumlen_local[min(cursor, nstroke - 1)]
        if not sections or tail_gap > min_leftover or end_standalone:
            add_free_sections(cursor, nstroke)

        # how each free span connects at each end:
        #   face/cap = the stroke-end weld edge, pair = a welded run's end rung,
        #   pivot = a stroke-corner pivot onto the previous span's last quad, none = open
        first_kind = ('face' if snap_start else 'cap') if start_standalone else 'none'
        last_kind  = ('face' if snap_end else 'cap') if end_standalone else 'none'
        for si, sec in enumerate(sections):
            if sec['kind'] != 'free': continue
            prev_sec = sections[si - 1] if si > 0 else None
            next_sec = sections[si + 1] if si + 1 < len(sections) else None
            sec['start'] = first_kind if prev_sec is None else ('pair' if prev_sec['kind'] == 'run' else 'pivot')
            sec['end']   = last_kind  if next_sec is None else ('pair' if next_sec['kind'] == 'run' else 'pivot')
        if DEBUG_WELDS:
            print('[weld] sections=' + ', '.join(
                (f'run({len(s["run"]["verts"])}v/{s["run"]["built"]}q)' if s['kind'] == 'run'
                 else f'free[{s["i0"]}:{s["i1"]}]({s["start"]}->{s["end"]})') for s in sections))

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

        # The count budget is only for free spans, not snapped ones.
        # Reserve one quad per free-corner (pivot) end out of the requested total, then split
        # whatever's left across the free spans by length, so widening the count only grows the
        # straight portions of the strip, never stretches or shrinks the corners.
        run_quads = sum(sec['run']['built'] for sec in sections if sec['kind'] == 'run')
        free_secs = [sec for sec in sections if sec['kind'] == 'free']
        for sec in free_secs:
            i1c = min(sec['i1'], len(cumlen_at_index) - 1)
            seg_len_world = cumlen_at_index[i1c] - cumlen_at_index[sec['i0']]
            has_end_corner = sec['end'] == 'pivot'
            # w_end is a half-width. A square corner quad needs its along-strip length to match the full (rail-to-rail) width.
            w_end = width_at(cumlen_at_index[i1c] / total_length) if has_end_corner else 0.0
            reserved_world = 2 * w_end * self.edit_scale  # width is local-space
            sec['n_ends'] = 1 if has_end_corner else 0
            sec['remaining_world'] = max(0.0, seg_len_world - reserved_world)
            sec['count_min'] = 3 if (sec['start'] != 'none' and sec['end'] != 'none') else 2
        total_reserved_quads = sum(sec['n_ends'] for sec in free_secs)
        total_remaining_world = sum(sec['remaining_world'] for sec in free_secs) or 1.0
        floor_total = run_quads + sum(max(sec['count_min'], sec['n_ends']) for sec in free_secs)
        if run_quads and not self.initial and self.count_total < floor_total:
            self.count_warning = 'Snapped edges, cannot reduce count any further'
        remaining_budget = max(0, self.count_total - run_quads - total_reserved_quads)
        # largest remainder apportionment: plain per-span round() lets a short span's share
        # sit below 0.5 across a wide range of count_total and look permanently "stuck".
        raw_shares = {id(sec): remaining_budget * sec['remaining_world'] / total_remaining_world for sec in free_secs}
        for sec in free_secs: sec['quads'] = int(raw_shares[id(sec)])
        leftover = remaining_budget - sum(sec['quads'] for sec in free_secs)
        for sec in sorted(free_secs, key=lambda s: raw_shares[id(s)] - s['quads'], reverse=True)[:leftover]:
            sec['quads'] += 1
        for sec in free_secs:
            sec['quads'] += sec['n_ends']

        # ---- create welded runs first: their end rungs are the fixed geometry the free spans attach to
        actual_strip_count = 0
        ncounts_by_sec = {}
        for si, sec in enumerate(sections):
            if sec['kind'] != 'run': continue
            self.emit_run(context, sec['run'], width_at, select_geo)
            ncounts_by_sec[si] = (sec['run']['built'], sec['run']['built'])
            actual_strip_count += 1

        # ---- create the free spans
        pivot_face = None
        for si, sec in enumerate(sections):
            if sec['kind'] == 'run':
                pivot_face = None
                continue
            i0, i1 = sec['i0'], sec['i1']
            stroke3D_local = self.stroke3D_local[i0:i1]
            if len(stroke3D_local) < 2: continue
            is_first, is_last = si == 0, si == len(sections) - 1
            prev_sec = sections[si - 1] if si > 0 else None
            next_sec = sections[si + 1] if si + 1 < len(sections) else None

            # this span's own position range, for the width gradient. i1 is a slice bound (one past
            # the last valid index), so clamp it to the last cumulative-length entry
            seg_start_length = cumlen_at_index[i0]
            seg_end_length = cumlen_at_index[min(i1, len(cumlen_at_index) - 1)]
            def sample_width(v):
                # v is a fraction (0..1) along this segment's own samples
                return width_at(lerp(v, seg_start_length, seg_end_length) / total_length)

            snap_beginning = (
                is_first and 'x' in self.mirror and sign_threshold(stroke3D_local[0].x, self.mirror_threshold) == 0,
                is_first and 'y' in self.mirror and sign_threshold(stroke3D_local[0].y, self.mirror_threshold) == 0,
                is_first and 'z' in self.mirror and sign_threshold(stroke3D_local[0].z, self.mirror_threshold) == 0,
            )
            snap_ending = (
                is_last and 'x' in self.mirror and sign_threshold(stroke3D_local[-1].x, self.mirror_threshold) == 0,
                is_last and 'y' in self.mirror and sign_threshold(stroke3D_local[-1].y, self.mirror_threshold) == 0,
                is_last and 'z' in self.mirror and sign_threshold(stroke3D_local[-1].z, self.mirror_threshold) == 0,
            )

            snap0 = snap1 = None
            if sec['start'] == 'face':
                snap0 = snap_start
            elif sec['start'] == 'cap':
                snap0 = cap_snap(cap_bme_start)
            elif sec['start'] == 'pair':
                snap0 = self.pair_snap(prev_sec['run']['last_pair'], prev_sec['run']['out_end'])
            elif sec['start'] == 'pivot' and pivot_face is not None and pivot_face.is_valid:
                limit_bmes0 = [
                    bme for bme in pivot_face.edges
                    if bme.is_boundary and any(len(bmv.link_faces) > 1 for bmv in bme.verts)
                ]
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
                snap0 = trim_stroke_to_bmf(stroke3D_local, pivot_face, True, limit_bmes0)
                if snap0:
                    if snap0['error']:
                        self.error = True
                        print(f'ERROR: {snap0["error"]} on corner pivot')
                        continue
                    stroke3D_local = snap0['stroke']

            if sec['end'] == 'face':
                snap1 = snap_end
            elif sec['end'] == 'cap':
                snap1 = cap_snap(cap_bme_end)
            elif sec['end'] == 'pair':
                snap1 = self.pair_snap(next_sec['run']['first_pair'], next_sec['run']['out_start'])
            elif sec['end'] == 'pivot':
                # extend the stroke by half a width to reserve a square corner for the pivot
                i_end = max(0, len(stroke3D_local) - 5)
                p0, p1 = stroke3D_local[i_end], stroke3D_local[-1]
                p1_world = M @ p1
                d01_world = Direction(p1_world - (M @ p0))
                p2_world = p1_world + d01_world * (self.initial_width / 2)  # self.initial_width is world space
                p2 = self.nearest_point(context, Mi @ p2_world)
                stroke3D_local = stroke3D_local + [p2]

            if DEBUG_WELDS:
                def _kind(k, sn):
                    if not sn: return k.upper()
                    if sn.get('bmf') is not None: return f"{'FACE' if k == 'face' else 'PIVOT'}(f{sn['bmf'].index} via e{sn['bme'].index})"
                    if sn.get('pair'): return f"PAIR(v{sn['pair'][0].index}/v{sn['pair'][1].index})"
                    if sn.get('bme') is not None: return f"CAP(e{sn['bme'].index})"
                    return k.upper()
                print(f'[weld] sec {si} [{i0}:{i1}] start={_kind(sec["start"], snap0)} end={_kind(sec["end"], snap1)}')

            # true only when this end is welded to pre-existing geometry (a pivot welds to this
            # strip's own just-built quad, not real pre-existing geometry, so it's excluded)
            real_snap0 = bool(snap0) and sec['start'] in ('face', 'cap', 'pair')
            real_snap1 = bool(snap1) and sec['end'] in ('face', 'cap', 'pair')

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

            count_min = 3 if (snap0 and snap1) else 2
            quad_count = max(count_min, sec.get('quads', 0))

            ncounts_by_sec[si] = (quad_count, count_min)

            # NOTE: nsamples is always odd (rungs land at samples[0,2,4,...,nsamples-1], i.e. n_rungs = (nsamples+1)//2).
            # This relies on quad_count >= 3 whenever both ends are snapped, which count_min above already guarantees.
            # Don't loosen that clamp without rechecking the rung math below.
            # A real weld reuses an existing edge as its rung instead of building one.
            # A pivot weld reuses a rung too, but a newly created one not a pre-existing one, so it must not get that discount.
            quad_count = (quad_count - 1) if real_snap0 and real_snap1 else quad_count
            nsamples = quad_count + (quad_count - 1)
            nsamples = (nsamples + 2) if not (real_snap0 or real_snap1) else nsamples
            nsamples = max(2, nsamples)

            n_rungs = (nsamples + 1) // 2
            seg_len_local = sum((p1 - p0).length for (p0, p1) in iter_pairs(stroke3D_local, self.is_cycle)) or 1.0

            # cumulative arc length at each sample, for fold-crease placement
            cumul = [0.0]
            for (a, b) in iter_pairs(stroke3D_local, self.is_cycle):
                cumul.append(cumul[-1] + (b - a).length)
            seg_total = cumul[-1] or 1.0

            # NORMAL-corner: force a rung onto every fold that falls inside this segment. No splitting (#1601).
            fold_sample_indices = []
            seg_creases = [ci for ci in bend_indices if i0 < ci < i1]
            if not seg_creases:
                # A pivot end reserves its last interval for the local width, so squaring it here squares the corner.
                rung_fracs = self.reserved_rung_factors(
                    n_rungs, seg_len_local,
                    0.0,
                    2 * sample_width(1) if sec['end'] == 'pivot' else 0.0,
                )
            else:
                # Pin a rung at each fold and re-space the rest evenly around them.
                guard = 0.5 / max(1, n_rungs)  # ~half a uniform span
                crease_fracs = []
                for ci in seg_creases:
                    crease_pt = self.stroke3D_local[ci]
                    j = min(range(len(stroke3D_local)), key=lambda j: (stroke3D_local[j] - crease_pt).length)
                    crease_fracs.append(cumul[j] / seg_total)
                pins = [0.0, 1.0]
                if sec['end'] == 'pivot':
                    pins.append(1.0 - min(0.45, (2 * sample_width(1)) / seg_len_local))
                kept_creases = []
                for cf in sorted(crease_fracs):
                    # drop folds that would sit on an endpoint, reserved pin, or another fold
                    if not (guard < cf < 1.0 - guard): continue
                    if any(abs(cf - p) < guard for p in pins + kept_creases): continue
                    kept_creases.append(cf)
                rung_fracs = self.rung_factors_with_pins(n_rungs, pins + kept_creases)
                n_rungs = len(rung_fracs)
                nsamples = 2 * n_rungs - 1
                # sample index of each fold rung, so its centerline + direction can be pinned to the source crease once the samples are built.
                fold_sample_indices = [2 * rung_fracs.index(cf) for cf in kept_creases]

            if DEBUG_WELDS:
                print(f'[weld] sec {si} [{i0}:{i1}] start={sec["start"]} end={sec["end"]} '
                      f'n_rungs={n_rungs} quads={n_rungs-1} creases={len(fold_sample_indices)}')

            fracs = [0.0] * nsamples
            for k, f in enumerate(rung_fracs):
                fracs[2 * k] = f
            for i in range(1, nsamples - 1, 2):
                fracs[i] = (fracs[i - 1] + fracs[i + 1]) / 2

            samples = [
                find_point_at(stroke3D_local, self.is_cycle, fracs[i])
                for i in range(nsamples)
            ]
            normals_raw = [ Direction(nearest_normal_valid_sources(context, M @ pt, world=False)) for pt in samples ]
            # Averaged normals improves rung direction on bumpy scan surfaces
            normals = smoothed_stroke_normals(samples, normals_raw, 2 * base_width)
            resnapped = [
                self.snap_to_source(context, pt, along_local=n, max_correction=2 * base_width)
                for (pt, n) in zip(samples, normals)
            ]
            samples = [pt if co is None else co for (pt, co) in zip(samples, resnapped)]
            # Pin each fold rung's centerline onto the actual source crease when detection is on,
            # else the intersection of the two adjacent face planes if detection is off.
            # Done before forwards/backwards/rights so the cross-section reflects the move.
            fold_crease_dirs = {}
            for k in fold_sample_indices:
                if not (0 < k < len(samples) - 1): continue
                crease = self.fold_crease_point(
                    samples[k], samples[k - 1], normals_raw[k - 1], samples[k + 1], normals_raw[k + 1],
                    max_plane_dist=2 * base_width,
                )
                if crease is not None:
                    samples[k], fold_crease_dirs[k] = crease

            # How hard a welded end pulls the strip square onto its edge
            WELD_EASE_POS = 0.6       # eases the samples next to the weld onto the edge's outward-normal ray
            WELD_EASE_DIR = [0.4]     # fans the adjacent rung's direction toward the edge direction
            WELD_EASE_WINDOW = 4      # samples affected by the position ease

            # Ease the samples next to a welded end onto the weld's outward ray, with decaying
            # weights, so a diagonal approach squares up into the weld instead of shearing across it.
            for snap_at, at_start in ((snap0 if real_snap0 else None, True), (snap1 if real_snap1 else None, False)):
                if not snap_at: continue
                # never wider than half the segment, or a short span gets fully splayed outward
                window = min(WELD_EASE_WINDOW, (len(samples) - 1) // 2)
                idxs = list(range(len(samples))) if at_start else list(range(len(samples) - 1, -1, -1))
                probe_i = idxs[min(window, len(idxs) - 1)]
                if snap_at.get('pair'):
                    perp = snap_at.get('outward')  # a run's end rung: leave along the run's own direction
                else:
                    perp = self.weld_edge_outward(snap_at['bme'], samples[probe_i])
                if perp is None: continue
                end_pt = samples[idxs[0]]
                acc = 0.0
                for j in range(1, min(window + 1, len(idxs))):
                    i_prev, i_cur = idxs[j - 1], idxs[j]
                    acc += (samples[i_cur] - samples[i_prev]).length
                    if i_cur in fold_crease_dirs: continue  # fold rungs stay on their crease
                    t = WELD_EASE_POS * (1 - j / (window + 1))
                    target = end_pt + perp * acc
                    samples[i_cur] = self.nearest_point(context, samples[i_cur] + (target - samples[i_cur]) * t)

            # A rung runs perpendicular to the centerline tangent.
            # Averaged over the size of about a quad to account for bumpy surfaces.
            # Capped to avoid smoothing actual corners in short spans.
            cumul_samples = [0.0]
            for (a, b) in iter_pairs(samples, self.is_cycle):
                cumul_samples.append(cumul_samples[-1] + (b - a).length)
            baseline = min(2 * base_width, 0.25 * (cumul_samples[-1] or 1.0))
            def tangent_at(i):
                j0, j1 = i, i
                while j0 > 0 and cumul_samples[i] - cumul_samples[j0] < baseline: j0 -= 1
                while j1 < len(samples) - 1 and cumul_samples[j1] - cumul_samples[i] < baseline: j1 += 1
                d = samples[j1] - samples[j0]
                if d.length == 0:  # degenerate window: fall back to the nearest distinct samples
                    d = samples[min(i + 1, len(samples) - 1)] - samples[max(i - 1, 0)]
                return Direction(d)
            rights = []
            for (i, n) in enumerate(normals):
                r = tangent_at(i).cross(n)
                # a zero cross would collapse the rung, so keep the previous rung's direction
                rights.append(Direction(r) if r.length > 1e-9 else (rights[-1] if rights else Direction((1, 0, 0))))
            # A fold rung must lie along the crease so both its verts land on the edge.
            # Replace the fold rung's direction with the crease direction.
            # Skip if the strip only grazes the crease.
            for k, cdir in fold_crease_dirs.items():
                align = cdir.dot(rights[k])
                if abs(align) < 0.2: continue
                rights[k] = Direction(cdir if align >= 0 else -cdir)

            # Fan the rung(s) beside a welded end partway toward the welded edge's direction,
            # so the connection quad reads as a fan wedge rather than a sheared parallelogram.
            for snap_at, at_start in ((snap0 if real_snap0 else None, True), (snap1 if real_snap1 else None, False)):
                if not snap_at: continue
                pair = snap_at.get('pair')
                edir_f = (pair[1].co - pair[0].co) if pair else bme_vector(snap_at['bme'])
                if edir_f.length == 0: continue
                edir_f = Direction(edir_f)
                for k, t in enumerate(WELD_EASE_DIR, start=1):
                    idx = 2 * k if at_start else (len(samples) - 1 - 2 * k)
                    if not (0 < idx < len(samples) - 1): continue
                    if idx in fold_crease_dirs: continue  # fold rungs stay on their crease
                    e = edir_f if edir_f.dot(rights[idx]) >= 0 else -edir_f
                    v = rights[idx] * (1 - t) + e * t
                    if v.length > 0: rights[idx] = Direction(v)


            ######################################
            # create bmverts

            # w0/w1 anchor a taper only where this end is welded to real pre-existing
            # geometry; everywhere else (a fresh end, or a corner pivot) just
            # follows the start/end width gradient directly, so widths stay consistent
            # across corners no matter how the count/segmentation changes
            w0 = snap0['bme.radius'] if real_snap0 else sample_width(0)
            w1 = snap1['bme.radius'] if real_snap1 else sample_width(1)
            bmvs = [[], []]
            rail_snaps = []  # (bmv, rung normal or None, max correction) for the surface snap below

            def make_rail_verts(p, r, w, n, clamp=None):
                ''' Build the two rail verts (bmvs[0]=+r side, bmvs[1]=-r side) for one rung.
                `n` is the rung's surface normal, the line the verts get snapped along.
                `clamp` zeroes verts onto an active mirror plane.'''
                def clamped(co):
                    if clamp:
                        if clamp[0]: co.x = 0
                        if clamp[1]: co.y = 0
                        if clamp[2]: co.z = 0
                    return co
                made = (self.bm.verts.new(clamped(p + r * w)), self.bm.verts.new(clamped(p - r * w)))
                rail_snaps.extend((bmv, n, 2 * w) for bmv in made)
                return made

            def end_rung_verts(sn, r):
                ''' The two existing verts of a welded end rung, oriented onto the rails. '''
                bmv0, bmv1 = sn['pair'] if sn.get('pair') else sn['bme'].verts
                if r.dot(bmv1.co - bmv0.co) > 0:
                    bmv0, bmv1 = bmv1, bmv0
                return bmv0, bmv1

            # create bmverts at beginning of stroke
            p, r = samples[0], rights[0]
            if snap0:
                bmv0, bmv1 = end_rung_verts(snap0, r)
                bmvs[0] += [bmv0]
                bmvs[1] += [bmv1]
                rail_snaps.extend((bmv, None, None) for bmv in (bmv0, bmv1))
            else:
                v0, v1 = make_rail_verts(p, r, w0, normals[0], clamp=snap_beginning)
                bmvs[0] += [ v0 ]; bmvs[1] += [ v1 ]

            # create bmverts along stroke
            i_end = len(samples) - (2 if (snap0 or snap1) else 1)
            for i in range(2, i_end, 2):
                p = samples[i]
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

                v0, v1 = make_rail_verts(p, r, w, normals[i])
                bmvs[0] += [ v0 ]; bmvs[1] += [ v1 ]

            # create bmverts at ending of stroke
            p, r = samples[-1], rights[-1]
            if snap1:
                bmv0, bmv1 = end_rung_verts(snap1, r)
                bmvs[0] += [bmv0]
                bmvs[1] += [bmv1]
                rail_snaps.extend((bmv, None, None) for bmv in (bmv0, bmv1))
            else:
                v0, v1 = make_rail_verts(p, r, w1, normals[-1], clamp=snap_ending)
                bmvs[0] += [ v0 ]; bmvs[1] += [ v1 ]

            # project every rail vert onto the source, then pull onto nearby source features.
            # Verts reused from a welded end rung are projected too, but never feature snapped.
            existing_bmvs = set()
            if snap0: existing_bmvs.update((bmvs[0][0], bmvs[1][0]))
            if snap1: existing_bmvs.update((bmvs[0][-1], bmvs[1][-1]))
            for (bmv, along, max_corr) in rail_snaps:
                if (co := self.snap_to_source(context, bmv.co, along_local=along, max_correction=max_corr)) is not None:
                    bmv.co = co

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
                    None if (bmv in existing_bmvs) else self.feature_snap_candidate(bmv.co)
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
                    run_id = seg_run.get(cands[i][0]['seg'])
                    # No run topology to compare against: assume one run and veto rather than collapse.
                    if seg_run and run_id != seg_run.get(cands[i][1]['seg']): continue
                    by_run.setdefault(run_id, []).append(i)
                for rungs_ in by_run.values():
                    d0 = sum(cands[i][0]['dist'] for i in rungs_)
                    d1 = sum(cands[i][1]['dist'] for i in rungs_)
                    drop = 1 if d0 <= d1 else 0
                    for i in rungs_: cands[i][drop] = None

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
                    if bmv in existing_bmvs: continue
                    co = bmv.co
                    v = Vector((
                        0 if 'x' in m and sign_threshold(co.x, mt) != mx else 1,
                        0 if 'y' in m and sign_threshold(co.y, mt) != my else 1,
                        0 if 'z' in m and sign_threshold(co.z, mt) != mz else 1,
                    ))
                    bmv.co = v * co


            ######################################################
            # create bmfaces

            sec_bmfs = []
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
                elif DEBUG_WELDS:
                    print(f'[weld] sec {si}: quad {i} already exists, reusing {bmf.index=}')
                sec_bmfs += [ bmf ]
                select_geo.append(bmf)
            orient_bmf_normals(context, new_bmfs, new_faces=True)

            if sec_bmfs: pivot_face = sec_bmfs[-1]
            actual_strip_count += 1

        ########################################
        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, select_geo)
        bmops.flush_selection(self.bm, self.em)
        # Welding can select all verts of a face that shouldn't be selected.
        # Re-limit face and edge selection to the strip itself.
        strip_bmfs = set(select_geo)
        strip_bmes = {bme for bmf in strip_bmfs for bme in bmf.edges}
        sel_bmvs = {bmv for bmf in strip_bmfs for bmv in bmf.verts}
        for bmf in {f for bmv in sel_bmvs for f in bmv.link_faces}:
            if bmf.select and bmf not in strip_bmfs: bmf.select = False
        for bme in {e for bmv in sel_bmvs for e in bmv.link_edges}:
            if bme.select and bme not in strip_bmes: bme.select = False
        bmesh.update_edit_mesh(self.em)

        ncount_pairs = [ncounts_by_sec[si] for si in sorted(ncounts_by_sec)]
        self.counts = [c for (c, m) in ncount_pairs]
        self.count_mins = [m for (c, m) in ncount_pairs]
        self.strip_count = actual_strip_count
        has_runs = any(sec['kind'] == 'run' for sec in sections)
        has_free_secs = any(sec['kind'] == 'free' for sec in sections)
        self.count_locked = has_runs and not has_free_secs  # Fully welded: the count is fixed by the geometry and must not be editable.
        self.attached = has_runs # Any run weld: the redo panel's Align Snapped option is relevant
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

    def snap_to_source(self, context, co_local, along_local=None, max_correction=None):
        ''' Project a local-space position onto the source, returning None if nothing is in reach.
        `along_local` is the surface normal at this vert's rung. Falls back to nearest
        point when the ray finds nothing, or travels more than `max_correction`. '''
        M, Mi = self.matrix_world, self.matrix_world_inv
        co_world = M @ co_local
        if along_local is not None:
            d = (Mi.transposed() @ Vector((*along_local, 0.0))).xyz
            if d.length_squared > 1e-12:
                d.normalize()
                hits = [
                    hit
                    for sign in (1, -1)
                    if (hit := raycast_ray_valid_sources(
                        context, (Vector((*co_world, 1.0)), Vector((*(d * sign), 0.0))),
                        world=True, respect_clip_planes=True,
                    )) is not None
                ]
                if hits:
                    hit = min(hits, key=lambda h: (h - co_world).length)
                    if max_correction is None or (hit - co_world).length <= max_correction:
                        return Mi @ hit
        snapped = nearest_point_valid_sources(context, co_world, respect_clip_planes=True)
        return (Mi @ snapped) if snapped else None
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
