'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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
import math
from collections.abc import Sequence, Iterator, Callable

from mathutils import Vector, Matrix

from .maths import Point, Vec
from .utils import iter_running_sum, iter_pairs


def compute_quadratic_weights(t):
    t0, t1 = t, (1-t)
    return (t1**2, 2*t0*t1, t0**2)


def compute_cubic_weights(t):
    t0, t1 = t, (1-t)
    return (t1**3, 3*t0*t1**2, 3*t0**2*t1, t0**3)


def interpolate_cubic(v0, v1, v2, v3, t):
    b0, b1, b2, b3 = compute_cubic_weights(t)
    return v0*b0 + v1*b1 + v2*b2 + v3*b3


def compute_cubic_error(v0, v1, v2, v3, l_v, l_t):
    return math.sqrt(sum(
        (interpolate_cubic(v0, v1, v2, v3, t) - v)**2
        for v, t in zip(l_v, l_t)
    ))


def fit_cubicbezier(l_v, l_t):
    #########################################################
    # http://nbviewer.ipython.org/gist/anonymous/5688579

    # make the summation functions for A (16 of them)
    A_fns = [
        lambda l_t: sum([2*t**0*(t-1)**6 for t in l_t]),
        lambda l_t: sum([-6*t**1*(t-1)**5 for t in l_t]),
        lambda l_t: sum([6*t**2*(t-1)**4 for t in l_t]),
        lambda l_t: sum([-2*t**3*(t-1)**3 for t in l_t]),

        lambda l_t: sum([-6*t**1*(t-1)**5 for t in l_t]),
        lambda l_t: sum([18*t**2*(t-1)**4 for t in l_t]),
        lambda l_t: sum([-18*t**3*(t-1)**3 for t in l_t]),
        lambda l_t: sum([6*t**4*(t-1)**2 for t in l_t]),

        lambda l_t: sum([6*t**2*(t-1)**4 for t in l_t]),
        lambda l_t: sum([-18*t**3*(t-1)**3 for t in l_t]),
        lambda l_t: sum([18*t**4*(t-1)**2 for t in l_t]),
        lambda l_t: sum([-6*t**5*(t-1)**1 for t in l_t]),

        lambda l_t: sum([-2*t**3*(t-1)**3 for t in l_t]),
        lambda l_t: sum([6*t**4*(t-1)**2 for t in l_t]),
        lambda l_t: sum([-6*t**5*(t-1)**1 for t in l_t]),
        lambda l_t: sum([2*t**6*(t-1)**0 for t in l_t])
    ]

    # make the summation functions for b (4 of them)
    b_fns = [
        lambda l_t, l_v: sum(v * (-2 * (t**0) * ((t-1)**3))
                             for t, v in zip(l_t, l_v)),
        lambda l_t, l_v: sum(v * (6 * (t**1) * ((t-1)**2))
                             for t, v in zip(l_t, l_v)),
        lambda l_t, l_v: sum(v * (-6 * (t**2) * ((t-1)**1))
                             for t, v in zip(l_t, l_v)),
        lambda l_t, l_v: sum(v * (2 * (t**3) * ((t-1)**0))
                             for t, v in zip(l_t, l_v)),
    ]

    # compute the data we will put into matrix A
    A_values = [fn(l_t) for fn in A_fns]
    # fill the A matrix with data
    A_matrix = Matrix(tuple(zip(*[iter(A_values)]*4)))
    try:
        A_inv = A_matrix.inverted_safe()
    except:
        return (float('inf'), l_v[0], l_v[0], l_v[0], l_v[0])

    # compute the data we will put into the b vector
    b_values = [fn(l_t, l_v) for fn in b_fns]
    # fill the b vector with data
    b_vector = Vector(b_values)

    # solve for the unknowns in vector x
    v0, v1, v2, v3 = A_inv @ b_vector

    err = compute_cubic_error(v0, v1, v2, v3, l_v, l_t) #/ len(l_v)

    return (err, v0, v1, v2, v3)


def fit_cubicbezier_spline(
    l_co, error_scale, depth=0,
    t0=0, t3=-1, allow_split=True, force_split=False,
    min_count_split=15, max_depth_split=4,
):
    '''
    fits cubic bezier to given points
    returns list of tuples of (t0,t3,p0,p1,p2,p3)
    that best fits the given points l_co
    where t0 and t3 are the passed-in t0 and t3
    and p0,p1,p2,p3 are the control points of bezier
    '''
    count = len(l_co)
    if t3 == -1:
        t3 = count-1
    assert count > 2, "Need at least 2 points to fit cubic bezier"
    if count == 2:
        # special case: line
        p0, p3 = l_co[0], l_co[-1]
        diff = p3 - p0
        return [(t0, t3, p0, p0+diff*0.33, p0+diff*0.66, p3)]
    if count == 3:
        new_co = [
            l_co[0],
            Point.average(l_co[:2]),
            l_co[1],
            Point.average(l_co[1:]),
            l_co[2]
        ]
        return fit_cubicbezier_spline(
            new_co, error_scale,
            depth=depth,
            t0=t0, t3=t3,
            allow_split=allow_split, force_split=force_split
        )
    l_d = [0] + [(v0-v1).length for v0, v1 in zip(l_co[:-1], l_co[1:])]
    l_ad = [s for d, s in iter_running_sum(l_d)]
    dist = sum(l_d)
    if dist <= 0:
        # print(spc + 'fit_cubicbezier_spline: returning []')
        return []  # [(t0,t3,l_co[0],l_co[0],l_co[0],l_co[0])]
    l_t = [ad/dist for ad in l_ad]

    ex, x0, x1, x2, x3 = fit_cubicbezier([co[0] for co in l_co], l_t)
    ey, y0, y1, y2, y3 = fit_cubicbezier([co[1] for co in l_co], l_t)
    ez, z0, z1, z2, z3 = fit_cubicbezier([co[2] for co in l_co], l_t)
    tot_error = ex+ey+ez
    #print(f'error={tot_error}  max={error_scale}  force={force_split}  allow={allow_split}') #, l=4)

    if not force_split:
        do_not_split = tot_error < error_scale
        do_not_split |= depth == max_depth_split
        do_not_split |= len(l_co) <= min_count_split
        do_not_split |= not allow_split
        if do_not_split:
            p0, p1 = Point((x0, y0, z0)), Point((x1, y1, z1))
            p2, p3 = Point((x2, y2, z2)), Point((x3, y3, z3))
            return [(t0, t3, p0, p1, p2, p3)]

    # too much error in fit.  split sequence in two, and fit each sub-sequence

    # find a good split point
    ind_split = -1
    mindot = 1.0
    for ind in range(5, len(l_co)-5):
        if l_t[ind] < 0.4:
            continue
        if l_t[ind] > 0.6:
            break
        # if l_ad[ind] < 0.1: continue
        # if l_ad[ind] > dist-0.1: break

        v0 = l_co[ind-4]
        v1 = l_co[ind+0]
        v2 = l_co[ind+4]
        d0 = (v1-v0).normalized()
        d1 = (v2-v1).normalized()
        dot01 = d0.dot(d1)
        if ind_split == -1 or dot01 < mindot:
            ind_split = ind
            mindot = dot01

    if ind_split == -1:
        # did not find a good splitting point!
        p0, p1, p2, p3 = Point((x0, y0, z0)), Point(
            (x1, y1, z1)), Point((x2, y2, z2)), Point((x3, y3, z3))
        #p0,p3 = Point(l_co[0]),Point(l_co[-1])
        return [(t0, t3, p0, p1, p2, p3)]

    #print(spc + 'splitting at %d' % ind_split)

    l_co0, l_co1 = l_co[:ind_split+1], l_co[ind_split:]   # share split point
    tsplit = ind_split  # / (len(l_co)-1)
    bezier0 = fit_cubicbezier_spline(
        l_co0, error_scale, depth=depth+1, t0=t0, t3=tsplit)
    bezier1 = fit_cubicbezier_spline(
        l_co1, error_scale, depth=depth+1, t0=tsplit, t3=t3)
    return bezier0 + bezier1


class CubicBezier:
    split_default : int = 100
    segments_default : int = 100
    p0 : Vector
    p1 : Vector
    p2 : Vector
    p3 : Vector
    tessellation : list[Vector]
    fn_dist : Callable[[Vector, Vector], float] | None

    @staticmethod
    def create_from_points(pts_list : Sequence[Vector]) -> CubicBezier:
        '''
        Estimates best spline to fit given points
        '''
        match pts_list:
            case [] | [_]:
                assert False, 'Must have at least 2 points to create CubicBezier'

            case [p0, p3]:
                diff = p3 - p0
                p1 = p0 + diff * 0.33
                p2 = p0 + diff * 0.66
                return CubicBezier(p0, p1, p2, p3)

            case [p0, p03, p3]:
                d003, d303 = (p03 - p0), (p03 - p3)
                p1 = p0 + d003 * 0.5
                p2 = p3 + d303 * 0.5
                return CubicBezier(p0, p1, p2, p3)

            case _:
                pass

        l_d = [0] + [
            (p0 - p1).length
            for (p0, p1) in zip(pts_list[:-1], pts_list[1:])
        ]
        l_ad = [s for d, s in iter_running_sum(l_d)]
        dist = sum(l_d)
        if dist <= 0:
            p0 = pts_list[0]
            return CubicBezier(p0, p0, p0, p0)
        l_t = [ad/dist for ad in l_ad]

        ex, x0, x1, x2, x3 = fit_cubicbezier([pt[0] for pt in pts_list], l_t)
        ey, y0, y1, y2, y3 = fit_cubicbezier([pt[1] for pt in pts_list], l_t)
        ez, z0, z1, z2, z3 = fit_cubicbezier([pt[2] for pt in pts_list], l_t)
        p0 = Point((x0, y0, z0))
        p1 = Point((x1, y1, z1))
        p2 = Point((x2, y2, z2))
        p3 = Point((x3, y3, z3))
        return CubicBezier(p0, p1, p2, p3)

    def __init__(self, p0 : Vector, p1 : Vector, p2 : Vector, p3 : Vector):
        self.p0, self.p1, self.p2, self.p3 = p0, p1, p2, p3
        self.tessellation = []
        self.fn_dist = None

    def __iter__(self) -> Iterator[Vector]:
        yield self.p0
        yield self.p1
        yield self.p2
        yield self.p3

    def points(self) -> tuple[Vector, Vector, Vector, Vector]:
        return (self.p0, self.p1, self.p2, self.p3)

    def copy(self) -> CubicBezier:
        ''' shallow copy '''
        return CubicBezier(self.p0, self.p1, self.p2, self.p3)

    def eval(self, t) -> Point:
        p0, p1, p2, p3 = self.p0, self.p1, self.p2, self.p3
        b0, b1, b2, b3 = compute_cubic_weights(t)
        return Point.weighted_average([
            (b0, p0), (b1, p1), (b2, p2), (b3, p3)
        ])

    def eval_derivative(self, t : float) -> Vector:
        p0, p1, p2, p3 = self.p0, self.p1, self.p2, self.p3
        q0, q1, q2 = 3*(p1-p0), 3*(p2-p1), 3*(p3-p2)
        b0, b1, b2 = compute_quadratic_weights(t)
        return q0 * b0 + q1 * b1 + q2 * b2

    def subdivide(self, iters : int = 1) -> list[CubicBezier]:
        if iters == 0:
            return [self]
        # de casteljau subdivide
        p0, p1, p2, p3 = self.p0, self.p1, self.p2, self.p3
        q0, q1, q2 = (p0+p1)/2, (p1+p2)/2, (p2+p3)/2
        r0, r1 = (q0+q1)/2, (q1+q2)/2
        s = (r0+r1)/2
        cb0, cb1 = CubicBezier(p0, q0, r0, s), CubicBezier(s, r1, q2, p3)
        if iters == 1:
            return [cb0, cb1]
        return cb0.subdivide(iters=iters-1) + cb1.subdivide(iters=iters-1)

    def compute_linearity(self, fn_dist : Callable[[Vector, Vector], float]) -> float:
        '''
        Estimating measure of linearity as ratio of distances
        of curve mid-point and mid-point of end control points
        over half the distance between end control points
          p1 _
            / ﹨
           |   ﹨
        p0 *    ﹨   * p3
                 ﹨_/
                 p2
        '''
        p0 = Vector(self.p0)
        p1 = Vector(self.p1)
        p2 = Vector(self.p2)
        p3 = Vector(self.p3)
        q0, q1, q2 = (p0+p1)/2, (p1+p2)/2, (p2+p3)/2
        r0, r1 = (q0+q1)/2, (q1+q2)/2
        s = (r0+r1)/2
        m = (p0+p3)/2
        d03 = fn_dist(p0, p3)
        dsm = fn_dist(s, m)
        return 2 * dsm / d03

    def subdivide_linesegments(
        self,
        fn_dist : Callable[[Vector, Vector], float],
        max_linearity : float | None = None,
    ) -> list[CubicBezier]:
        if self.compute_linearity(fn_dist) < (max_linearity or 0.1):
            return [self]
        # de casteljau subdivide:
        p0 = Vector(self.p0)
        p1 = Vector(self.p1)
        p2 = Vector(self.p2)
        p3 = Vector(self.p3)
        q0, q1, q2 = (p0+p1)/2, (p1+p2)/2, (p2+p3)/2
        r0, r1 = (q0+q1)/2, (q1+q2)/2
        s = (r0+r1)/2
        cbs = CubicBezier(p0, q0, r0, s), CubicBezier(s, r1, q2, p3)
        segs0, segs1 = [
            cb.subdivide_linesegments(fn_dist, max_linearity=max_linearity)
            for cb in cbs
        ]
        return segs0 + segs1

    def length(
        self,
        fn_dist : Callable[[Vector, Vector], float],
        max_linearity : float | None = None,
    ) -> float:
        cbs = self.subdivide_linesegments(fn_dist, max_linearity=max_linearity)
        return sum(fn_dist(cb.p0, cb.p3) for cb in cbs)

    def approximate_length_uniform(
        self,
        fn_dist : Callable[[Vector, Vector], float],
        split : int | None = None,
    ) -> float:
        split = split or self.split_default
        p = self.p0
        d = 0
        for i in range(split):
            q = self.eval((i+1) / split)
            d += fn_dist(p, q)
            p = q
        return d

    def approximate_t_at_interval_uniform(
        self,
        interval : float,  # should be int?
        fn_dist : Callable[[Vector, Vector], float],
        split : int | None = None,
    ) -> float:
        split = split or self.split_default
        p = self.p0
        d = 0
        for i in range(split):
            percent = (i+1) / split
            q = self.eval(percent)
            d += fn_dist(p, q)
            if interval <= d:
                return percent
            p = q
        return 1

    def approximate_ts_at_intervals_uniform(
        self,
        intervals : list[float],  # should be int?
        fn_dist : Callable[[Vector, Vector], float],
        split : int | None = None,
    ) -> list[float]:
        self_approx = self.approximate_t_at_interval_uniform
        def approx(i : float) -> float:
            return self_approx(i, fn_dist, split=None)
        return [ approx(interval) for interval in intervals ]

    def get_tessellate_uniform(
        self,
        fn_dist : Callable[[Vector, Vector], float],
        split : int | None = None,
    ) -> list[tuple[float, Vector, float]]:
        split = split or self.split_default
        ts = [i / (split - 1) for i in range(split)]
        ps = [self.eval(t) for t in ts]
        ds = [0] + [fn_dist(p, q) for p, q in iter_pairs(ps, False)]
        return [(t, p, d) for (t, p, d) in zip(ts, ps, ds)]

    def tessellate_uniform_points(
        self,
        segments : int | None = None,
    ) -> list[Vector]:
        segments = segments or self.segments_default
        ts = [i/(segments-1) for i in range(segments)]
        ps = [self.eval(t) for t in ts]
        return ps

    #########################################
    #                                       #
    # the following code **requires** that  #
    # self.tessellate_uniform() is called   #
    # beforehand!                           #
    #                                       #
    #########################################

    def tessellate_uniform(
        self,
        *,
        fn_dist : Callable[[Vector, Vector], float] | None = None,
        split : int | None = None,
    ):
        if not fn_dist:
            fn_dist = lambda a, b: (a - b).length
        self.fn_dist = fn_dist
        self.tessellation = self.get_tessellate_uniform(fn_dist, split=split)

    def approximate_t_at_point_tessellation(self, point : Vector) -> float:
        assert self.fn_dist, 'tessellate_uniform must be called first!'
        fn_dist = self.fn_dist
        bt : float | None = None
        bd : float | None = None
        for (t, q, _) in self.tessellation:
            d = fn_dist(point, q)
            if bd is None or d < bd:
                bd, bt = d, t
        assert bt is not None
        return bt

    def approximate_totlength_tessellation(self) -> float:
        return sum(self.approximate_lengths_tessellation())

    def approximate_lengths_tessellation(self) -> list[float]:
        return [d for (_, _, d) in self.tessellation]


class CubicBezierSpline:

    @staticmethod
    def create_from_points(pts_list, max_error, **kwargs):
        '''
        Estimates best spline to fit given points
        '''
        cbs = []
        inds = []
        for pts in pts_list:
            cbs_pts = fit_cubicbezier_spline(pts, max_error, **kwargs)
            cbs += [CubicBezier(p0, p1, p2, p3) for _, _, p0, p1, p2, p3 in cbs_pts]
            inds += [(ind0, ind1) for ind0, ind1, _, _, _, _ in cbs_pts]
        return CubicBezierSpline(cbs=cbs, inds=inds)

    @staticmethod
    def create_from_knots(pts, knot_indices, *, cyclic=False, corner_indices=()):
        '''Build a multi-segment poly-Bezier through `pts` with knots placed exactly at `knot_indices`.'''
        n = len(pts)
        knots = sorted({ i for i in knot_indices if 0 <= i < n })
        corners = { i % n for i in corner_indices }
        cbs, inds = [], []

        for ka, kb in zip(knots[:-1], knots[1:]):
            sub = pts[ka:kb + 1]
            if len(sub) < 2: continue
            cbs.append(CubicBezier.create_from_points(sub))
            inds.append((ka, kb))

        if cyclic and knots:
            ka = knots[-1]
            sub = list(pts[ka:]) + list(pts[:knots[0] + 1])
            if len(sub) >= 2:
                cbs.append(CubicBezier.create_from_points(sub))
                inds.append((ka, knots[0]))

        spline = CubicBezierSpline(cbs=cbs, inds=inds)
        nseg = len(cbs)
        if nseg == 0:
            return spline

        # the per-run fits may drift the shared endpoints slightly apart. Snap each
        # junction's two control points to their midpoint so knots are exactly shared
        for i in range(nseg - 1):
            shared = (Vector(cbs[i].p3) + Vector(cbs[i + 1].p0)) / 2
            cbs[i].p3 = shared
            cbs[i + 1].p0 = shared
        if cyclic and nseg >= 2:
            shared = (Vector(cbs[-1].p3) + Vector(cbs[0].p0)) / 2
            cbs[-1].p3 = shared
            cbs[0].p0 = shared

        def smooth_junction(cb_in, cb_out):
            # make the in/out tangents collinear through the shared knot (G1),
            # preserving each tangent's arm length
            K = Vector(cb_in.p3)
            din, dout = (K - Vector(cb_in.p2)), (Vector(cb_out.p1) - K)
            li, lo = din.length, dout.length
            if li < 1e-9 or lo < 1e-9: return
            d = din.normalized() + dout.normalized()
            if d.length < 1e-9: return
            d.normalize()
            cb_in.p2 = K - d * li
            cb_out.p1 = K + d * lo

        for i in range(nseg - 1):
            if (inds[i][1] % n) not in corners:
                smooth_junction(cbs[i], cbs[i + 1])
        if cyclic and nseg >= 2 and (knots[0] % n) not in corners:
            smooth_junction(cbs[-1], cbs[0])

        return spline

    @staticmethod
    def create_catmull_rom(pts, knot_indices, *, cyclic=False, corner_indices=()):
        '''Build a multi-segment Bézier through pts using Catmull-Rom tangents.'''
        n = len(pts)
        if n < 2:
            return CubicBezierSpline(cbs=[], inds=[])

        knots = sorted({ i for i in knot_indices if 0 <= i < n })
        corners = { i % n for i in corner_indices }

        def prev_v(k):
            return (k - 1) % n if cyclic else max(0, k - 1)

        def next_v(k):
            return (k + 1) % n if cyclic else min(n - 1, k + 1)

        def tangent_out(k):
            pk, nk = prev_v(k), next_v(k)
            if k in corners or pk == k:
                d = Vector(pts[nk]) - Vector(pts[k])
            else:
                d = Vector(pts[nk]) - Vector(pts[pk])
            return d.normalized() if d.length > 1e-9 else Vector((0, 0, 1))

        def tangent_in(k):
            pk, nk = prev_v(k), next_v(k)
            if k in corners or nk == k:
                d = Vector(pts[k]) - Vector(pts[pk])
            else:
                d = Vector(pts[nk]) - Vector(pts[pk])
            return d.normalized() if d.length > 1e-9 else Vector((0, 0, 1))

        cbs, inds = [], []

        knot_pairs = list(zip(knots[:-1], knots[1:]))
        if cyclic and knots:
            knot_pairs.append((knots[-1], knots[0]))

        for ka, kb in knot_pairs:
            p0 = Vector(pts[ka])
            p3 = Vector(pts[kb])

            if ka < kb:
                L = sum((Vector(pts[i + 1]) - Vector(pts[i])).length for i in range(ka, kb))
            else:
                # cyclic wrap-around: ka → n-1 → 0 → kb
                L  = sum((Vector(pts[i + 1]) - Vector(pts[i])).length for i in range(ka, n - 1))
                L += (Vector(pts[0]) - Vector(pts[n - 1])).length
                L += sum((Vector(pts[i + 1]) - Vector(pts[i])).length for i in range(0, kb))
            L = max(L, 1e-9)

            p1 = p0 + tangent_out(ka) * (L / 3)
            p2 = p3 - tangent_in(kb)  * (L / 3)

            cbs.append(CubicBezier(p0, p1, p2, p3))
            inds.append((ka, kb))

        return CubicBezierSpline(cbs=cbs, inds=inds)

    def __init__(self, cbs=None, inds=None):
        if cbs is None:
            cbs = []
        if inds is None:
            inds = []
        if type(cbs) is CubicBezierSpline:
            cbs = [cb.copy() for cb in cbs.cbs]
        assert type(cbs) is list, "expected list"
        self.cbs = cbs
        self.inds = inds
        self.tessellation = []

    def copy(self):
        return CubicBezierSpline(
            cbs=[cb.copy() for cb in self.cbs],
            inds=list(self.inds)
        )

    def __add__(self, other):
        t = type(other)
        if t is CubicBezierSpline:
            return CubicBezierSpline(
                self.cbs + other.cbs,
                self.inds + other.inds
            )
        if t is CubicBezier:
            return CubicBezierSpline(self.cbs + [other])
        if t is list:
            return CubicBezierSpline(self.cbs + other)
        assert False, "unhandled type: %s (%s)" % (str(other), str(t))

    def __iadd__(self, other):
        t = type(other)
        if t is CubicBezierSpline:
            self.cbs += other.cbs
            self.inds += other.inds
        elif t is CubicBezier:
            self.cbs += [other]
            self.inds = []
        elif t is list:
            self.cbs += other
            self.inds = []
        else:
            assert False, "unhandled type: %s (%s)" % (str(other), str(t))

    def __len__(self): return len(self.cbs)

    def __iter__(self): return self.cbs.__iter__()

    def __getitem__(self, idx): return self.cbs[idx]

    def eval(self, t):
        if t < 0.0:
            t = 0
            idx = 0
        elif t >= len(self):
            t = 1
            idx = len(self)-1
        else:
            idx = int(t)
            t = t - idx
        return self.cbs[idx].eval(t)

    def eval_derivative(self, t):
        if t < 0.0:
            t = 0
            idx = 0
        elif t >= len(self):
            t = 1
            idx = len(self)-1
        else:
            idx = int(t)
            t = t - idx
        return self.cbs[idx].eval_derivative(t)

    def approximate_totlength_uniform(self, fn_dist, split=None):
        return sum(self.approximate_lengths_uniform(fn_dist, split=split))

    def approximate_lengths_uniform(self, fn_dist, split=None):
        return [
            cb.approximate_length_uniform(fn_dist, split=split)
            for cb in self.cbs
        ]

    def approximate_ts_at_intervals_uniform(
        self, intervals, fn_dist, split=None
    ):
        lengths = self.approximate_lengths_uniform(fn_dist, split=split)
        totlength = sum(lengths)
        ts = []
        for interval in intervals:
            if interval < 0:
                ts.append(0)
                continue
            if interval >= totlength:
                ts.append(len(self.cbs))
                continue
            for i, length in enumerate(lengths):
                if interval <= length:
                    t = self.cbs[i].approximate_t_at_interval_uniform(
                        interval, fn_dist, split=split)
                    ts.append(i + t)
                    break
                interval -= length
            else:
                assert False
        return ts

    def subdivide_linesegments(self, fn_dist, max_linearity=None):
        return CubicBezierSpline(cbi
                                 for cb in self.cbs
                                 for cbi in cb.subdivide_linesegments(
                                     fn_dist,
                                     max_linearity=max_linearity
                                 ))

    #########################################
    #                                       #
    # the following code **requires** that  #
    # self.tessellate_uniform() is called   #
    # beforehand!                           #
    #                                       #
    #########################################

    def tessellate_uniform(self, *, fn_dist=None, split=None):
        if not fn_dist: fn_dist = lambda a, b: (a - b).length
        self.tessellation.clear()
        for i, cb in enumerate(self.cbs):
            cb_tess = cb.get_tessellate_uniform(fn_dist, split=split)
            self.tessellation.append(cb_tess)

    def approximate_totlength_tessellation(self):
        return sum(self.approximate_lengths_tessellation())

    def approximate_lengths_tessellation(self):
        return [sum(d for _, _, d in cb_tess) for cb_tess in self.tessellation]

    def approximate_ts_at_intervals_tessellation(self, intervals):
        lengths = self.approximate_lengths_tessellation()
        totlength = sum(lengths)
        ts = []
        for interval in intervals:
            if interval < 0:
                ts.append(0)
                continue
            if interval >= totlength:
                ts.append(len(self.cbs))
                continue
            for i, length in enumerate(lengths):
                if interval > length:
                    interval -= length
                    continue
                cb_tess = self.tessellation[i]
                for t, p, d in cb_tess:
                    if interval > d:
                        interval -= d
                        continue
                    ts.append(i+t)
                    break
                else:
                    assert False
                break
            else:
                assert False
        return ts

    def approximate_ts_at_points_tessellation(self, points, fn_dist):
        ts = []
        for p in points:
            bd, bt = None, None
            for i, cb_tess in enumerate(self.tessellation):
                for t, q, _ in cb_tess:
                    d = fn_dist(p, q)
                    if bd is None or d < bd:
                        bd, bt = d, i+t
            ts.append(bt)
        return ts

    def approximate_t_at_point_tessellation(self, point, fn_dist):
        bd, bt = None, None
        for i, cb_tess in enumerate(self.tessellation):
            for t, q, _ in cb_tess:
                d = fn_dist(point, q)
                if bd is None or d < bd:
                    bd, bt = d, i+t
        return bt


class GenVector(list):
    '''
    Generalized Vector, allows for some simple ordered items to be linearly combined
    which is useful for interpolating arbitrary points of Bezier Spline.
    '''

    def __mul__(self, scalar: float):  # ->GVector:
        for idx in range(len(self)):
            self[idx] *= scalar
        return self

    def __rmul__(self, scalar: float):  # ->GVector:
        return self.__mul__(scalar)

    def __add__(self, other: list):  # ->GVector:
        for idx in range(len(self)):
            self[idx] += other[idx]
        return self


if __name__ == '__main__':
    # run tests

    print('-'*50)
    l = GenVector([Vector((1, 2, 3)), 23])
    print(l)
    print(l * 2)
    print(4 * l)

    l2 = GenVector([Vector((0, 0, 1)), 10])
    print(l + l2)
    print(2 * l + l2 * 4)
