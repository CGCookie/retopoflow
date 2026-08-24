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
from bisect import bisect_left
from collections.abc import Sequence, Iterator, Callable
from itertools import accumulate

import numpy as np
from mathutils import Vector, Matrix, kdtree

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


def fit_tangent_lengths(pts, us, t1, t2, fallback):
    '''
    Solve the 2x2 least-squares system for scalar handle lengths (alpha1, alpha2) so
    p1 = pts[0] + alpha1*t1, p2 = pts[-1] + alpha2*t2 best fits `pts`, sampled at
    chord-length parameters `us` in [0, 1]. `t1`/`t2` are fixed unit tangents (`t2`
    points back into the curve); only the lengths are solved. Returns (fallback,
    fallback) for a degenerate fit.
    Reference: Schneider, "An Algorithm for Fitting Digitized Curves", Graphics Gems I.
    '''
    p0, p3 = pts[0], pts[-1]
    c00 = c01 = c11 = x0 = x1 = 0.0
    for pt, u in zip(pts, us):
        b0, b1, b2, b3 = compute_cubic_weights(u)
        q = (b0 + b1) * p0 + (b2 + b3) * p3
        r = pt - q
        c00 += b1 * b1
        c01 += b1 * b2 * t1.dot(t2)
        c11 += b2 * b2
        x0  += b1 * t1.dot(r)
        x1  += b2 * t2.dot(r)
    det = c00 * c11 - c01 * c01
    if abs(det) < 1e-9:
        return fallback, fallback
    alpha1 = (x0 * c11 - x1 * c01) / det
    alpha2 = (c00 * x1 - c01 * x0) / det
    if alpha1 < 1e-9 or alpha2 < 1e-9:
        return fallback, fallback
    return alpha1, alpha2


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
    Fit a cubic bezier spline to points `l_co`, splitting recursively where the
    error is too high. Returns [(t0, t3, p0, p1, p2, p3)] per segment.
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
        # single-entry memo for get_tessellate_uniform / _get_arc_table -- see
        # _tess_memo_key. One entry, not a dict: within a frame every caller
        # asks about the same (unchanged) control points, and between frames
        # the old entry is dead weight, so a dict would just grow unbounded
        # over a drag.
        self._tess_memo = None

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
        ''' Linearity measure: distance from the curve midpoint to the p0-p3 midpoint,
        over half the p0-p3 distance. 0 = straight. '''
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

    def _tess_memo_key(self, split : int, fn_dist : Callable[[Vector, Vector], float]):
        ''' Identity of a tessellation result: the control points it was
        sampled from, the sample count, and the metric the segment lengths
        were measured with. Keying on the control point VALUES (rather than
        an explicit dirty flag) is what makes the memo self-invalidating --
        p0..p3 are mutated in place all over the place (every frame of a
        handle drag), and no caller announces it. '''
        return (self.p0[:], self.p1[:], self.p2[:], self.p3[:], split, fn_dist)

    def _get_arc_table(
        self,
        fn_dist : Callable[[Vector, Vector], float],
        split : int | None = None,
    ) -> tuple[list[tuple[float, Vector, float]], list[float], list[float]]:
        ''' Memoized (samples, sample ts, cumulative arc length at each
        sample). Building this costs `split` bezier evals, so it must not be
        rebuilt per vert: a handle drag asks the same segment for an
        arc-length conversion once for every vert riding on it, every frame,
        which is exactly one table's worth of work shared by all of them. '''
        split = split or self.split_default
        key = self._tess_memo_key(split, fn_dist)
        memo = self._tess_memo
        if memo is None or memo[0] != key:
            ts = [i / (split - 1) for i in range(split)]
            ps = [self.eval(t) for t in ts]
            ds = [0] + [fn_dist(p, q) for p, q in iter_pairs(ps, False)]
            memo = (key, list(zip(ts, ps, ds)), ts, list(accumulate(ds)))
            self._tess_memo = memo
        return memo[1], memo[2], memo[3]

    def approximate_arc_length_fraction_at_t(
        self,
        t : float,
        fn_dist : Callable[[Vector, Vector], float],
        split : int | None = None,
    ) -> float:
        ''' Fraction (0..1) of total arc length between p0 and eval(t).
        Inverse of approximate_t_at_arc_length_fraction. '''
        _, ts, cums = self._get_arc_table(fn_dist, split=split)
        total = cums[-1]
        if total < 1e-9:
            return 0.0
        # first sample at or past t -- ts is ascending, so bisect instead of
        # scanning all `split` of them
        i = bisect_left(ts, t)
        if i >= len(ts):
            return 1.0
        if i == 0:
            return 0.0
        prev_t, s = ts[i-1], ts[i]
        cum = cums[i-1]
        local = 0.0 if s == prev_t else (t - prev_t) / (s - prev_t)
        return (cum + (cums[i] - cum) * local) / total

    def approximate_t_at_arc_length_fraction(
        self,
        fraction : float,
        fn_dist : Callable[[Vector, Vector], float],
        split : int | None = None,
    ) -> float:
        ''' The t whose arc length from p0 is `fraction` of the total.
        Inverse of approximate_arc_length_fraction_at_t. '''
        _, ts, cums = self._get_arc_table(fn_dist, split=split)
        total = cums[-1]
        if total < 1e-9:
            return 0.0
        target = fraction * total
        # cums is nondecreasing, so the first sample whose running total
        # reaches `target` is a bisect away
        i = bisect_left(cums, target)
        if i >= len(cums):
            return 1.0
        prev_t = ts[i-1] if i else 0.0
        cum = cums[i-1] if i else 0.0
        d = cums[i] - cum
        # interpolate within the bracketing samples rather than snapping to one of
        # `split` discrete ts -- called per-frame during edits, snapping visibly pops
        local = 0.0 if d < 1e-9 else (target - cum) / d
        return prev_t + (ts[i] - prev_t) * local

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
        ''' (t, eval(t), distance from the previous sample) for `split`
        uniformly spaced ts. Memoized -- see _get_arc_table. The returned list
        is the cached one, so callers must treat it as read-only. '''
        samples, _, _ = self._get_arc_table(fn_dist, split=split)
        return samples

    def tessellate_uniform_points(
        self,
        segments : int | None = None,
    ) -> list[Vector]:
        segments = segments or self.segments_default
        ts = [i/(segments-1) for i in range(segments)]
        ps = [self.eval(t) for t in ts]
        return ps

    # NOTE: everything below requires tessellate_uniform() to have been called first

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

    def _closest_point_tessellation(self, point : Vector) -> tuple[float, float]:
        assert self.fn_dist, 'tessellate_uniform must be called first!'
        fn_dist = self.fn_dist
        bt : float | None = None
        bd : float | None = None
        for (t, q, _) in self.tessellation:
            d = fn_dist(point, q)
            if bd is None or d < bd:
                bd, bt = d, t
        assert bt is not None
        return bt, bd

    def approximate_t_at_point_tessellation(self, point : Vector) -> float:
        bt, _ = self._closest_point_tessellation(point)
        return bt

    def approximate_distance_to_point_tessellation(self, point : Vector) -> float:
        ''' Distance from `point` to its closest tessellation sample -- for
        callers needing only the distance, not the t. '''
        _, bd = self._closest_point_tessellation(point)
        return bd

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
    def is_free_knot(k, corners, cyclic, n):
        ''' Smooth, non-endpoint knots are "free": not meant to sit on any particular pts[k]. '''
        if k in corners:
            return False
        return cyclic or (k != 0 and k != n - 1)

    @staticmethod
    def acceptable_alternative(alt_score, original_score, chord_length):
        ''' Whether alt_score is close enough to original_score to prefer the
        alternative on other, non-fit-quality grounds (refine_handles' guardrails,
        create_catmull_rom's free-knot candidates). '''
        # the chord-scaled margin keeps a near-zero original score from making
        # every alternative look unacceptable
        return alt_score <= original_score * 2.0 + 0.02 * chord_length

    @staticmethod
    def create_catmull_rom(pts, knot_indices, *, cyclic=False, corner_indices=(), locked_cbs=None, prev_pts=None, cached_cbs=None):
        '''
        Build a multi-segment Bézier through `pts` with knots at `knot_indices`:
        a fast Catmull-Rom tangent fit per segment, refined by refine_handles.

        `locked_cbs`: {seg index: CubicBezier} to reuse as-is instead of refitting
        (the caller already knows it still fits); endpoints are still snapped to
        pts, handles translated along.
        `prev_pts`: the pts locked_cbs/cached_cbs were built against, so a free
        knot can follow a rigid shift of its neighborhood instead of freezing.
        `cached_cbs`: {seg index: previous build's CubicBezier}, offering a free
        knot's cached position as a candidate anchor even where a full refit is
        needed -- see the candidate pass below.
        '''
        n = len(pts)
        if n < 2:
            return CubicBezierSpline(cbs=[], inds=[])
        locked_cbs = locked_cbs or {}
        cached_cbs = cached_cbs or {}

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

        cbs, inds, runs = [], [], []

        knot_pairs = list(zip(knots[:-1], knots[1:]))
        if cyclic and knots:
            knot_pairs.append((knots[-1], knots[0]))
        nseg = len(knot_pairs)
        aligned_junction = [(kb % n) not in corners for _, kb in knot_pairs]

        # a locked handle aligned-paired with an unlocked neighbor gets re-searched
        # by refine_handles anyway -- start it from the fresh fast-fit guess, which
        # matches the neighbor's current shape, not the cached value. refine_handles
        # needs the same boundary set, so compute it once here and pass it in.
        boundary_handles = set()
        wrap_ok = cyclic and nseg >= 2
        junction_range = range(nseg) if wrap_ok else range(max(0, nseg - 1))
        for i in junction_range:
            j = (i + 1) % nseg
            if aligned_junction[i] and (i in locked_cbs) != (j in locked_cbs):
                boundary_handles.add((i, 'p2'))
                boundary_handles.add((j, 'p1'))

        for seg_i, (ka, kb) in enumerate(knot_pairs):
            if kb <= ka:
                kb += n  # cyclic wrap-around: walk forward through the seam

            # gather the run's points (in extended, possibly-wrapped index space),
            # used both by the fast baseline fit and by refine_handles afterward
            run = [Vector(pts[i % n]) for i in range(ka, kb + 1)]
            p0, p3 = run[0], run[-1]

            locked = locked_cbs.get(seg_i)
            if locked is not None:
                # snap p0/p3 to the (possibly nudged) vert, carrying the handle by
                # the same delta. A free knot was never tied to pts[k]: keep its
                # locked position, translated by its anchor vert's delta (prev_pts)
                # so a rigid move of the whole chain doesn't leave it behind.
                if CubicBezierSpline.is_free_knot(ka % n, corners, cyclic, n):
                    p0 = Vector(locked.p0)
                    if prev_pts is not None:
                        p0 = p0 + (Vector(pts[ka % n]) - Vector(prev_pts[ka % n]))
                if CubicBezierSpline.is_free_knot(kb % n, corners, cyclic, n):
                    p3 = Vector(locked.p3)
                    if prev_pts is not None:
                        p3 = p3 + (Vector(pts[kb % n]) - Vector(prev_pts[kb % n]))
                d0, d3 = p0 - Vector(locked.p0), p3 - Vector(locked.p3)
                p1, p2 = Vector(locked.p1) + d0, Vector(locked.p2) + d3
                at_p1, at_p2 = (seg_i, 'p1') in boundary_handles, (seg_i, 'p2') in boundary_handles
                if at_p1 or at_p2:
                    t1 = tangent_out(ka % n)
                    t2 = -tangent_in(kb % n)
                    fresh_p1, fresh_p2 = CubicBezierSpline.fit_segment_fast(run, p0, p3, t1, t2)
                    if at_p1:
                        p1 = fresh_p1
                    if at_p2:
                        p2 = fresh_p2
                cbs.append(CubicBezier(p0, p1, p2, p3))
            else:
                t1 = tangent_out(ka % n)
                t2 = -tangent_in(kb % n)
                p1, p2 = CubicBezierSpline.fit_segment_fast(run, p0, p3, t1, t2)
                cbs.append(CubicBezier(p0, p1, p2, p3))
            inds.append((ka, kb))
            runs.append(run)

        # a FREE knot at a locked/unlocked boundary can leave the loop above with
        # two positions for one shared point: the locked side preserved its cached
        # position, the unlocked side used pts[k] (right for a coupled knot, wrong
        # for a free one). The unlocked side inherits the locked side's position,
        # carrying its handle along by the delta.
        for i in junction_range:
            j = (i + 1) % nseg
            if (i in locked_cbs) == (j in locked_cbs):
                continue  # both or neither locked -- both already used the same rule, so they already agree
            kb_i = knot_pairs[i][1] % n
            if not CubicBezierSpline.is_free_knot(kb_i, corners, cyclic, n):
                continue  # a coupled knot: both sides already read the same pts[k]
            if i in locked_cbs:
                canonical = Vector(cbs[i].p3)
                delta = canonical - Vector(cbs[j].p0)
                cbs[j].p0 = canonical
                cbs[j].p1 = Vector(cbs[j].p1) + delta
            else:
                canonical = Vector(cbs[j].p0)
                delta = canonical - Vector(cbs[i].p3)
                cbs[i].p3 = canonical
                cbs[i].p2 = Vector(cbs[i].p2) + delta

        # a free knot flanked by two UNLOCKED segments has no locked side to defer
        # to, but cached_cbs may offer a position worth keeping. Score the cached
        # anchor against the vert-anchored fit summed across BOTH sides and swap
        # both together or neither -- deciding per side can pull the shared knot
        # apart into two positions. Falling back whenever the cached anchor doesn't
        # hold up keeps a stale position (its anchor vert can move for unrelated
        # reasons) from snapping the knot to nonsense.
        for i in junction_range:
            j = (i + 1) % nseg
            if i in locked_cbs or j in locked_cbs:
                continue  # handled by the pass above, or both coupled (no ambiguity)
            k = knot_pairs[i][1] % n
            if not CubicBezierSpline.is_free_knot(k, corners, cyclic, n):
                continue  # a coupled knot: both sides already read the same pts[k]

            cached_i, cached_j = cached_cbs.get(i), cached_cbs.get(j)
            if cached_i is None and cached_j is None:
                continue  # nothing cached to offer as an alternative -- vertex default stands

            cand_point = Vector(cached_i.p3) if cached_i is not None else Vector(cached_j.p0)
            if prev_pts is not None:
                cand_point = cand_point + (Vector(pts[k]) - Vector(prev_pts[k]))

            # dir_j: direction leaving the shared knot INTO segment j, read from the
            # cached handle (a vertex-derived tangent has no relationship to an anchor
            # sitting away from the vert); a free knot's arms are collinear, so
            # segment i's p2-arm mirrors it when j isn't cached.
            dir_j = None
            if cached_j is not None:
                d = Vector(cached_j.p1) - Vector(cached_j.p0)
                if d.length > 1e-9:
                    dir_j = d.normalized()
            if dir_j is None and cached_i is not None:
                d = Vector(cached_i.p3) - Vector(cached_i.p2)
                if d.length > 1e-9:
                    dir_j = d.normalized()
            if dir_j is None:
                continue  # both cached handles were degenerate -- nothing usable to try

            run_i, run_j = runs[i], runs[j]
            chord_i = (Vector(cbs[i].p3) - Vector(cbs[i].p0)).length
            chord_j = (Vector(cbs[j].p3) - Vector(cbs[j].p0)).length
            if chord_i < 1e-9 or chord_j < 1e-9:
                continue

            t1_i = tangent_out(knot_pairs[i][0] % n)
            cand_p1_i, cand_p2_i = CubicBezierSpline.fit_segment_fast(run_i, cbs[i].p0, cand_point, t1_i, -dir_j)
            cand_cb_i = CubicBezier(cbs[i].p0, cand_p1_i, cand_p2_i, cand_point)

            t2_j = -tangent_in(knot_pairs[j][1] % n)
            cand_p1_j, cand_p2_j = CubicBezierSpline.fit_segment_fast(run_j, cand_point, cbs[j].p3, dir_j, t2_j)
            cand_cb_j = CubicBezier(cand_point, cand_p1_j, cand_p2_j, cbs[j].p3)

            default_score = CubicBezierSpline.total_distance(cbs[i], run_i) + CubicBezierSpline.total_distance(cbs[j], run_j)
            cand_score = CubicBezierSpline.total_distance(cand_cb_i, run_i) + CubicBezierSpline.total_distance(cand_cb_j, run_j)
            if CubicBezierSpline.acceptable_alternative(cand_score, default_score, chord_i + chord_j):
                cbs[i] = cand_cb_i
                cbs[j] = cand_cb_j

        CubicBezierSpline.refine_handles(cbs, runs, aligned_junction, cyclic,
            locked_segs=set(locked_cbs.keys()), boundary_handles=boundary_handles)

        return CubicBezierSpline(cbs=cbs, inds=inds)

    @staticmethod
    def fit_segment_fast(run, p0, p3, t1, t2):
        ''' Fit p1/p2 for one knot-to-knot segment along fixed tangent directions
        `t1` (leaving p0) and `t2` (leaving p3, pointing back into the curve) --
        solves only the lengths (fit_tangent_lengths), not the directions.
        The fast starting guess for refine_handles, and used alone for the live
        per-frame preview while dragging a knot, where refining would be too slow. '''
        seglens = [0.0] + [(b - a).length for a, b in zip(run[:-1], run[1:])]
        L = max(sum(seglens), 1e-9)
        us, cum = [], 0.0
        for d in seglens:
            cum += d
            us.append(cum / L)
        alpha1, alpha2 = fit_tangent_lengths(run, us, t1, t2, fallback=L / 3)
        return p0 + t1 * alpha1, p3 + t2 * alpha2

    @staticmethod
    def hot_cold_search(evaluate, *, num_tests=10, initial_step=1.0, initial_t=0.0):
        ''' Minimize a 1D function by pattern search from `initial_t`: accelerate
        while a step improves ("hot"), reverse and shrink the step when it doesn't
        ("cold"). Runs exactly `num_tests` evaluations and returns the best t seen
        -- not the last tried, since a step can overshoot past the best point. '''
        best_t, best_score = initial_t, evaluate(initial_t)
        cur_t, cur_score = best_t, best_score
        step = initial_step
        direction = 1.0
        for _ in range(num_tests - 1):
            t = cur_t + direction * step
            score = evaluate(t)
            if score < best_score:
                best_score, best_t = score, t
            if score < cur_score:
                cur_t, cur_score = t, score
                step *= 1.5
            else:
                direction = -direction
                step *= 0.5
        return best_t

    bernstein_cache = {} # Bernstein basis sampled at `split` uniform ts, as a (split x 4) matrix

    @staticmethod
    def bernstein_weights(split):
        W = CubicBezierSpline.bernstein_cache.get(split)
        if W is None:
            ts = np.arange(split, dtype=np.float64) / (split - 1)
            t1 = 1.0 - ts
            W = np.stack((t1**3, 3.0*ts*t1**2, 3.0*ts*ts*t1, ts**3), axis=1)
            CubicBezierSpline.bernstein_cache[split] = W
        return W

    @staticmethod
    def total_distance(cb, run):
        ''' Sum of distances from every interior point of `run` to its closest position on `cb`.
        This is refine_handles' scoring function, called hundreds of times per fit. '''
        if len(run) <= 2:
            return 0.0
        W = CubicBezierSpline.bernstein_weights(CubicBezier.split_default)
        P = np.array((cb.p0, cb.p1, cb.p2, cb.p3), dtype=np.float64)
        tess = W @ P                                        # split x 3 curve samples
        R = np.array(run[1:-1], dtype=np.float64)           # interior points only
        d = R[:, None, :] - tess[None, :, :]
        d2_min = (d * d).sum(axis=2).min(axis=1)            # sqrt only after the min: same argmin
        return float(np.sqrt(d2_min).sum())

    @staticmethod
    def refine_handles(cbs, runs, aligned, cyclic, *, rounds=3, locked_segs=frozenset(), boundary_handles=frozenset()):
        '''
        Improve cbs' initial handles in place: for `rounds` passes, hot_cold_search
        every handle's length (scale pass, always independent) and direction
        (rotate pass -- jointly, as one shared direction, for the two handles
        flanking a knot marked `aligned`; independently otherwise), scored by
        total_distance against the segment's own points.

        Guardrails after each pass catch results that score marginally better but
        look broken -- degenerately short handles, overshooting long ones,
        near-perpendicular directions -- each explained at its own code block.
        Their triggers are deliberately generous: acceptable_alternative decides
        what's kept, so a wide trigger only means more candidates considered.

        `locked_segs`: segment indices whose fit is already established; their
        handles are skipped (see frozen_handles below for the exception).
        `boundary_handles`: caller-computed (seg_i, attr) handles at a
        locked/unlocked boundary (see create_catmull_rom, the sole caller).
        '''
        nseg = len(cbs)
        if nseg == 0:
            return

        def arbitrary_perpendicular(v):
            ref = Vector((1, 0, 0)) if abs(v.x) < 0.9 else Vector((0, 1, 0))
            return v.cross(ref)

        def rotation_axis(direction, reference):
            axis = reference.cross(direction)
            if axis.length < 1e-9:
                axis = arbitrary_perpendicular(direction)
            return axis.normalized()

        def significantly_better(better_score, worse_score, chord_length):
            ''' Stricter inverse of acceptable_alternative: is the improvement big
            enough to justify an over-chord-length handle. Absolute margin only --
            with few interior points both scores sit near zero, where any relative
            improvement is visually meaningless. '''
            return worse_score - better_score > 0.2 * chord_length

        wrap_ok = cyclic and nseg >= 2
        junction_range = range(nseg) if wrap_ok else range(max(0, nseg - 1))

        # A handle is frozen (skipped by scale and rotate) only if its segment is
        # locked AND it isn't aligned-paired with an unlocked neighbor -- pinning
        # half of a joint search forces a worse joint fit. boundary_handles stay
        # eligible too, and get a wider search: they start from a possibly-stale
        # cached value, and there are at most two per contiguous locked run.
        frozen_handles = set()
        for seg_i in locked_segs:
            frozen_handles.add((seg_i, 'p1'))
            frozen_handles.add((seg_i, 'p2'))
        frozen_handles -= boundary_handles

        for _ in range(rounds):
            # --- scale: every handle, always independent ---
            # scale_scores keeps each committed evaluate()'s total_distance for the
            # degenerate-length guardrail below to reuse as original_score
            scale_scores = {}
            for seg_i, (cb, run) in enumerate(zip(cbs, runs)):
                for attr, anchor_attr in (('p1', 'p0'), ('p2', 'p3')):
                    if (seg_i, attr) in frozen_handles:
                        continue
                    anchor = Vector(getattr(cb, anchor_attr))
                    vec = Vector(getattr(cb, attr)) - anchor
                    length = vec.length
                    if length < 1e-9:
                        continue
                    direction = vec / length

                    def evaluate(t, cb=cb, attr=attr, anchor=anchor, direction=direction, length=length, run=run):
                        mult = max(0.05, 1.0 + t)
                        setattr(cb, attr, anchor + direction * (length * mult))
                        return CubicBezierSpline.total_distance(cb, run)

                    at_boundary = (seg_i, attr) in boundary_handles
                    initial_t = 0.0
                    if at_boundary:
                        # the cached length was tuned for a shape the neighbor no
                        # longer has -- coarse-scan a spread of multipliers before
                        # the local search, instead of only nudging from 1x
                        initial_t, coarse_best_score = 0.0, evaluate(0.0)
                        for mult in (0.2, 0.5, 1.5, 2.0, 3.0, 5.0):
                            t = mult - 1.0
                            score = evaluate(t)
                            if score < coarse_best_score:
                                coarse_best_score, initial_t = score, t

                    best_t = CubicBezierSpline.hot_cold_search(
                        evaluate, num_tests=25 if at_boundary else 10,
                        initial_step=0.4, initial_t=initial_t,
                    )
                    scale_scores[seg_i] = evaluate(best_t)

            # a handle that shrank to near nothing relative to its counterpart reads
            # as a cusp at the knot even when it scored marginally better. Try a
            # ladder of chord-relative lengths, capped at the counterpart's, and keep
            # the longest acceptable one. Runs even on locked segments -- locking
            # means the fit was good enough, not that the handle looks sane -- and
            # the cheap ratio check below gates the expensive scoring.
            for seg_i, (cb, run) in enumerate(zip(cbs, runs)):
                len1 = (Vector(cb.p1) - Vector(cb.p0)).length
                len2 = (Vector(cb.p2) - Vector(cb.p3)).length
                if len1 <= len2:
                    short_attr, short_anchor_attr, short_len, long_len = 'p1', 'p0', len1, len2
                else:
                    short_attr, short_anchor_attr, short_len, long_len = 'p2', 'p3', len2, len1
                if long_len < 1e-9 or short_len >= 0.3 * long_len:
                    continue
                anchor = Vector(getattr(cb, short_anchor_attr))
                vec = Vector(getattr(cb, short_attr)) - anchor
                if vec.length < 1e-9:
                    continue
                direction = vec / vec.length
                original_score = scale_scores.get(seg_i)
                if original_score is None:
                    original_score = CubicBezierSpline.total_distance(cb, run)
                chord_length = (Vector(cb.p3) - Vector(cb.p0)).length
                # descending: fit only degrades as the candidate grows, so the first
                # acceptable rung is the best available -- stop there
                rungs = sorted({
                    min(f * chord_length, long_len)
                    for f in (0.15, 0.2, 0.3, 0.5, 0.75, 1.0)
                    if f * chord_length > short_len
                }, reverse=True)
                best_len = short_len
                for cand_len in rungs:
                    setattr(cb, short_attr, anchor + direction * cand_len)
                    if CubicBezierSpline.acceptable_alternative(CubicBezierSpline.total_distance(cb, run), original_score, chord_length):
                        best_len = cand_len
                        break
                setattr(cb, short_attr, anchor + direction * best_len)

            # the check above compares a handle only to its counterpart, so a
            # "balanced" pair that are BOTH pinpricks relative to their own chord
            # slips past it -- also check each against its own chord, same ladder
            for seg_i, (cb, run) in enumerate(zip(cbs, runs)):
                chord_length = (Vector(cb.p3) - Vector(cb.p0)).length
                if chord_length < 1e-9:
                    continue
                for attr, anchor_attr in (('p1', 'p0'), ('p2', 'p3')):
                    anchor = Vector(getattr(cb, anchor_attr))
                    vec = Vector(getattr(cb, attr)) - anchor
                    length = vec.length
                    if length < 1e-9 or length >= 0.15 * chord_length:
                        continue
                    direction = vec / length
                    original_score = CubicBezierSpline.total_distance(cb, run)
                    rungs = sorted(
                        (f * chord_length for f in (0.15, 0.2, 0.3, 0.5) if f * chord_length > length),
                        reverse=True,
                    )
                    best_len = length
                    for cand_len in rungs:
                        setattr(cb, attr, anchor + direction * cand_len)
                        if CubicBezierSpline.acceptable_alternative(CubicBezierSpline.total_distance(cb, run), original_score, chord_length):
                            best_len = cand_len
                            break
                    setattr(cb, attr, anchor + direction * best_len)

            # a handle much longer than its own chord risks a visible bulge or loop.
            # Half the chord is preferred (same generous margin); past the full chord
            # is kept only when clearly better (significantly_better), and never past
            # twice the chord -- an under-constrained run can keep "scoring better"
            # with length indefinitely. Also runs on locked handles, as above.
            for seg_i, (cb, run) in enumerate(zip(cbs, runs)):
                chord_length = (Vector(cb.p3) - Vector(cb.p0)).length
                if chord_length < 1e-9:
                    continue
                for attr, anchor_attr in (('p1', 'p0'), ('p2', 'p3')):
                    anchor = Vector(getattr(cb, anchor_attr))
                    vec = Vector(getattr(cb, attr)) - anchor
                    length = vec.length
                    if length <= 0.5 * chord_length:
                        continue
                    direction = vec / length
                    capped_len = min(length, 2.0 * chord_length)
                    setattr(cb, attr, anchor + direction * capped_len)
                    long_score = CubicBezierSpline.total_distance(cb, run)
                    setattr(cb, attr, anchor + direction * (0.5 * chord_length))
                    short_score = CubicBezierSpline.total_distance(cb, run)
                    if capped_len > chord_length:
                        keep_long = significantly_better(long_score, short_score, chord_length)
                    else:
                        keep_long = not CubicBezierSpline.acceptable_alternative(short_score, long_score, chord_length)
                    if keep_long:
                        setattr(cb, attr, anchor + direction * capped_len)  # earns its keep -- put it back

            # --- rotate: grouped for aligned junctions, independent otherwise ---
            groups = []  # each: ([(cb, attr, anchor_attr, run), ...], (seg_i, ...))
            paired = [[False, False] for _ in range(nseg)]  # [i][0]=p1 used, [i][1]=p2 used
            for i in junction_range:
                j = (i + 1) % nseg
                if aligned[i]:
                    groups.append(([(cbs[i], 'p2', 'p3', runs[i]), (cbs[j], 'p1', 'p0', runs[j])], (i, j)))
                    paired[i][1] = paired[j][0] = True
            for i in range(nseg):
                if not paired[i][0]:
                    groups.append(([(cbs[i], 'p1', 'p0', runs[i])], (i,)))
                if not paired[i][1]:
                    groups.append(([(cbs[i], 'p2', 'p3', runs[i])], (i,)))

            for group, seg_indices in groups:
                # skip the search only when the whole group is locked. A mixed group
                # runs the normal joint search: forcing the unlocked side to match the
                # locked side's current direction satisfies G1 too, but can settle on
                # a worse fit -- the locked fit was only ever "good enough", not
                # exact. A fully-locked group still runs the near-perpendicular
                # guardrail below.
                locked_flags = [seg_i in locked_segs for seg_i in seg_indices]
                skip_search = all(locked_flags)
                is_boundary = any(locked_flags) and not skip_search

                arms = []
                for cb, attr, anchor_attr, run in group:
                    anchor = Vector(getattr(cb, anchor_attr))
                    vec = Vector(getattr(cb, attr)) - anchor
                    length = vec.length
                    if length < 1e-9:
                        arms = []
                        break
                    # p1 points along the direction of travel, p2 against it, so a
                    # shared knot's raw vectors are opposite. `sign` maps both into
                    # travel direction for averaging, and back when writing below.
                    sign = 1.0 if attr == 'p1' else -1.0
                    arms.append((cb, attr, anchor, vec / length, length, run, sign))
                if not arms:
                    continue

                shared = Vector((0.0, 0.0, 0.0))
                for _cb, _attr, _anchor, direction, _length, _run, sign in arms:
                    shared += direction * sign
                if shared.length < 1e-9:
                    continue
                shared.normalize()

                chord = Vector(arms[0][0].p3) - Vector(arms[0][0].p0)
                axis = rotation_axis(shared, chord)

                def apply_direction(direction, arms=arms):
                    total = 0.0
                    for cb, attr, anchor, _direction, length, run, sign in arms:
                        setattr(cb, attr, anchor + direction * (sign * length))
                        total += CubicBezierSpline.total_distance(cb, run)
                    return total

                def evaluate(t, axis=axis, shared=shared, apply_direction=apply_direction):
                    rot = Matrix.Rotation(t, 3, axis)
                    return apply_direction((rot @ shared).normalized())

                if skip_search:
                    # nothing free to move -- evaluate(0.0) below just commits the
                    # current state so the guardrail has a score to compare against
                    best_t = 0.0
                else:
                    initial_t = 0.0
                    if is_boundary:
                        # a greedy local search can strand a stale cached direction
                        # behind a worse region -- coarse-scan the full circle first;
                        # affordable since boundary groups are few
                        initial_t, coarse_best_score = 0.0, evaluate(0.0)
                        for k in range(1, 12):
                            t = k * (2 * math.pi / 12)
                            score = evaluate(t)
                            if score < coarse_best_score:
                                coarse_best_score, initial_t = score, t

                    best_t = CubicBezierSpline.hot_cold_search(
                        evaluate, num_tests=25 if is_boundary else 10,
                        initial_step=math.radians(20), initial_t=initial_t,
                    )
                best_score = evaluate(best_t)

                # a handle near-perpendicular to the run's local tangent looks wrong
                # even when it scores marginally better (a slight kink can reward
                # "sideways"). If a direction near the tangent doesn't cost much fit,
                # prefer it. local_tangent: secant to each arm's nearest interior
                # point, grouped and sign-corrected like `shared`.
                local_tangent = Vector((0.0, 0.0, 0.0))
                tangent_ok = True
                for _cb, attr, _anchor, _direction, _length, run, _sign in arms:
                    if attr == 'p1':
                        ref_point = run[1] if len(run) > 2 else run[-1]
                        d = Vector(ref_point) - Vector(run[0])
                    else:
                        ref_point = run[-2] if len(run) > 2 else run[0]
                        d = Vector(run[-1]) - Vector(ref_point)
                    if d.length < 1e-9:
                        tangent_ok = False
                        break
                    local_tangent += d.normalized()
                if tangent_ok and local_tangent.length > 1e-9:
                    local_tangent.normalize()
                    committed_dir = (Matrix.Rotation(best_t, 3, axis) @ shared).normalized()
                    angle_from_tangent = math.acos(max(-1.0, min(1.0, committed_dir.dot(local_tangent))))
                    if angle_from_tangent > math.radians(50):
                        tangent_score = apply_direction(local_tangent)
                        if not CubicBezierSpline.acceptable_alternative(tangent_score, best_score, chord.length):
                            apply_direction(committed_dir)  # not worth it -- revert

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
        # optional KD-tree over the tessellation, built on request -- see
        # tessellate_kdtree / approximate_t_at_point_kdtree
        self._kd = None
        self._kd_ts = []

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

    # NOTE: everything below requires tessellate_uniform() to have been called first

    def tessellate_uniform(self, *, fn_dist=None, split=None):
        if not fn_dist: fn_dist = lambda a, b: (a - b).length
        self.tessellation.clear()
        self._kd, self._kd_ts = None, []
        for i, cb in enumerate(self.cbs):
            cb_tess = cb.get_tessellate_uniform(fn_dist, split=split)
            self.tessellation.append(cb_tess)

    def tessellate_kdtree(self):
        ''' Build a KD-tree over the cached tessellation so nearest-point
        queries can be answered by approximate_t_at_point_kdtree instead of a
        linear scan over every sample of every segment. Worth it as soon as
        more than a handful of points are queried against one fixed
        tessellation: building the tree costs about the same as three linear
        scans, and each query afterwards is ~200x cheaper.

        Requires tessellate_uniform() first (which drops any existing tree,
        since the samples it indexes are gone). '''
        pts = [
            (i + t, p)
            for i, cb_tess in enumerate(self.tessellation)
            for (t, p, _) in cb_tess
        ]
        kd = kdtree.KDTree(len(pts))
        for n, (_, p) in enumerate(pts):
            kd.insert(p, n)
        kd.balance()
        self._kd = kd
        self._kd_ts = [t for (t, _) in pts]

    def approximate_t_at_point_kdtree(self, point):
        ''' approximate_t_at_point_tessellation via the KD-tree from
        tessellate_kdtree (which must have been called first). Euclidean
        only -- there's no fn_dist hook, because a KD-tree can't answer
        nearest under an arbitrary metric. '''
        assert self._kd is not None, 'tessellate_kdtree must be called first!'
        return self._kd_ts[self._kd.find(point)[1]]

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
    ''' Generalized vector: ordered items that can be linearly combined, for
    interpolating arbitrary Bezier spline point data. '''

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
