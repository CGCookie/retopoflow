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


def fit_tangent_lengths(pts, us, t1, t2, fallback):
    '''
    Given a run of points `pts` (p0 = pts[0], p3 = pts[-1]) sampled at chord-length
    parameters `us` in [0, 1], and fixed unit tangent directions `t1` (leaving p0)
    and `t2` (leaving p3, pointing back into the curve), solves the 2x2
    least-squares system for the scalar handle lengths alpha1, alpha2 such that
        p1 = p0 + alpha1 * t1
        p2 = p3 + alpha2 * t2
    best fits `pts` -- i.e. each handle is scaled independently to match how the
    points actually behave on its side, rather than both sides sharing one
    uniform third-of-the-run length.

    Reference: Schneider, "An Algorithm for Fitting Digitized Curves",
    Graphics Gems I -- the tangent directions are fixed (already known to be
    locally correct), only their lengths are solved for.

    Falls back to `fallback` for both lengths if the run is degenerate (too few
    points, or the fit yields a non-positive length).
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

    def approximate_arc_length_fraction_at_t(
        self,
        t : float,
        fn_dist : Callable[[Vector, Vector], float],
        split : int | None = None,
    ) -> float:
        '''
        Returns the fraction (0 to 1) of this curve's total arc length that lies
        between p0 and eval(t). Inverse of approximate_t_at_arc_length_fraction --
        used to capture a point's proportional position along the curve so it can
        be preserved (instead of its raw parameter t, which isn't proportional to
        arc length) as the curve's shape changes under editing.
        '''
        samples = self.get_tessellate_uniform(fn_dist, split=split)
        total = sum(d for _, _, d in samples)
        if total < 1e-9:
            return 0.0
        cum = 0.0
        prev_t = 0.0
        for s, _, d in samples:
            if s >= t:
                local = 0.0 if s == prev_t else (t - prev_t) / (s - prev_t)
                return (cum + d * local) / total
            cum += d
            prev_t = s
        return 1.0

    def approximate_t_at_arc_length_fraction(
        self,
        fraction : float,
        fn_dist : Callable[[Vector, Vector], float],
        split : int | None = None,
    ) -> float:
        '''
        Returns the t whose arc length from p0 is `fraction` of the curve's
        total arc length. Inverse of approximate_arc_length_fraction_at_t.

        Interpolates within the bracketing tessellation samples rather than
        snapping to the nearest one (as approximate_t_at_interval_uniform does)
        -- needed because this is called every frame while a segment's shape is
        changing continuously under editing; snapping to one of only `split`
        discrete t values would make the result visibly pop between those steps
        instead of sliding smoothly.
        '''
        samples = self.get_tessellate_uniform(fn_dist, split=split)
        total = sum(d for _, _, d in samples)
        if total < 1e-9:
            return 0.0
        target = fraction * total
        cum = 0.0
        prev_t = 0.0
        for s, _, d in samples:
            if cum + d >= target:
                local = 0.0 if d < 1e-9 else (target - cum) / d
                return prev_t + (s - prev_t) * local
            cum += d
            prev_t = s
        return 1.0

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
        ''' Distance from `point` to its closest position on the tessellation --
        for a caller that only needs the distance, not eval(t) + fn_dist() on the
        t approximate_t_at_point_tessellation would return (the search already
        computes this distance to find that t). '''
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
    def create_catmull_rom(pts, knot_indices, *, cyclic=False, corner_indices=(), locked_cbs=None, prev_pts=None):
        '''
        Build a multi-segment Bézier through pts: first a fast Catmull-Rom
        tangent fit for every segment as a starting guess, then refine_handles
        directly searches for the length and rotation that actually fit each
        segment's own points best (see its docstring).

        `locked_cbs`, if given, maps a segment index to a CubicBezier to reuse
        for that segment instead of fitting it fresh -- for a caller that's
        already established (by some outside measure) that a previous fit is
        still a good match for that segment's current points, so redoing the
        work would just spend time to land back on the same answer. The
        segment's endpoints are still snapped to pts (a coupled knot's vert
        may have nudged slightly), translating its handles along with them;
        refine_handles then leaves it untouched entirely.

        `prev_pts`, if given (parallel to `pts`, the positions locked_cbs was
        last built against), lets a *free* knot -- not tied to any particular
        vert, so it doesn't snap onto one the way a coupled knot's side does
        -- still track a rigid shift of its own neighborhood: it's translated
        by however far the vert at that same index moved, rather than staying
        frozen at its old absolute position while everything around it moves.
        Without `prev_pts`, a free knot's side is left exactly as cached.
        '''
        n = len(pts)
        if n < 2:
            return CubicBezierSpline(cbs=[], inds=[])
        locked_cbs = locked_cbs or {}

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

        # a locked segment whose handle is aligned-paired with an unlocked
        # neighbor's is about to be re-searched by refine_handles anyway (see
        # its docstring) -- starting that handle from the fresh fast-fit guess
        # a fully-unlocked segment gets, instead of the cached value, gives
        # that search a starting point that actually matches the neighbor's
        # current shape rather than whatever shape it was cached against.
        # refine_handles needs this same boundary set for its own search, so
        # it's computed once here (in its (seg_i, attr) form) and passed in.
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
                # a coupled knot's vert may have nudged slightly -- snap p0/p3
                # to it and carry the tangent handle along by the same delta.
                # A free knot was never tied to pts[k] in the first place (the
                # whole point of it being free), so its side keeps the locked
                # position exactly as given instead of snapping to whichever
                # vert happens to be at that index now -- except it's still
                # carried along by that same vert's own delta, if prev_pts
                # says how far that is, so a rigid move of the whole chain
                # doesn't leave it behind while everything around it shifts.
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

        CubicBezierSpline.refine_handles(cbs, runs, aligned_junction, cyclic,
            locked_segs=set(locked_cbs.keys()), boundary_handles=boundary_handles)

        return CubicBezierSpline(cbs=cbs, inds=inds)

    @staticmethod
    def fit_segment_fast(run, p0, p3, t1, t2):
        '''
        Fits the two interior control points (p1, p2) for a single knot-to-knot
        segment along the *fixed* Catmull-Rom directions `t1` (leaving p0) and
        `t2` (leaving p3, pointing back into the curve) -- solving only for
        each handle's length (see fit_tangent_lengths), not its direction.

        This is the cheap starting guess create_catmull_rom hands to
        refine_handles, and is also used directly (with no refinement) for the
        live per-frame handle preview while dragging a knot -- see
        RFOperator_Strokes_CurveEdit, where refining every frame would be too
        slow for something that's discarded and rebuilt properly once the drag
        ends anyway.
        '''
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
        '''
        Minimizes a 1D function via "hot and cold" pattern search: starts at
        `initial_t` (0.0, the current/unmodified value, unless the caller has
        reason to start somewhere else -- e.g. the result of a coarser scan)
        and tries a step in one direction, accelerating in that direction
        while it keeps improving ("hot"), or reversing direction and shrinking
        the step when it doesn't ("cold"). Runs for exactly `num_tests` calls
        to `evaluate(t)` and returns whichever `t` scored lowest across all of
        them -- not just the last one tried, since a step can overshoot past
        the best point on its way to discovering that stepping further is
        worse.
        '''
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

    @staticmethod
    def total_distance(cb, run):
        ''' Sum of distances from every interior point of `run` to its closest position on `cb`. '''
        if len(run) <= 2:
            return 0.0
        fn_dist = lambda a, b: (a - b).length
        cb.tessellate_uniform(fn_dist=fn_dist)
        return sum(cb.approximate_distance_to_point_tessellation(pt) for pt in run[1:-1])

    @staticmethod
    def refine_handles(cbs, runs, aligned, cyclic, *, rounds=3, locked_segs=frozenset(), boundary_handles=frozenset()):
        '''
        Improves on cbs' initial (fast Catmull-Rom) handles in place by
        directly searching for the length and direction that best fit each
        segment's own points, alternating:
          - scale: every handle's length, always independently -- G1
            continuity only requires the two handles at a shared knot to point
            in the same direction, not have the same length
          - rotate: every handle's direction -- *together*, as a single shared
            direction, for the two handles flanking a knot marked `aligned`;
            independently for everything else (corners, and the ends of an
            open strip)
        for `rounds` passes. Each handle (or aligned pair) is optimized with
        hot_cold_search: 10 candidate values tested, keeping whichever gives
        the lowest total_distance for the vert(s) that specific handle (or
        pair) actually affects.

        This replaces trying many arbitrary starting guesses and hoping one
        lands somewhere good: every test is judged by the same fit-to-the-
        actual-points criterion, so the search always moves toward a better
        fit instead of occasionally landing on a worse one that then needs a
        separate pass to detect and undo.

        Four guardrails run after each pass, since raw fit-to-points score
        alone can settle on a technically-marginally-better result that looks
        visually broken: after scale, a handle that ended up under 3/10ths its
        counterpart's length is tried at the counterpart's length instead, if
        that doesn't cost much fit quality (see acceptable_alternative);
        independent of its counterpart, a handle under 15% of its own
        segment's chord is also tried at increasing fractions of that chord
        (a pair can sit at a "balanced" ratio to each other while both are an
        absolute pinprick, which the counterpart check alone can't see); a
        handle longer than half its own segment's chord is tried at half
        instead, under the same generous margin, and a handle beyond the
        *full* chord length is held to a much stricter bar (needs to be a
        clearly better fit, not merely acceptable, to earn keeping that much
        overshoot -- and even then, never past twice the chord length, since
        a run with too few interior points to pin the curve down can
        otherwise keep "improving" without limit); after rotate, a handle
        within 40 degrees of perpendicular to its own run's local tangent is
        similarly tried aligned with that tangent. All the
        "acceptable_alternative" triggers are deliberately generous -- that
        check is what actually decides whether the alternative is kept, so a
        wider trigger only means
        more candidates get *considered*, not more get accepted.

        A segment index in `locked_segs` is a caller-established good fit
        already -- skip its handles entirely in the scale pass, and skip the
        rotate pass too for any aligned-pair group where *both* sides are
        locked (nothing there is free to move regardless). A group with only
        one side locked still runs the normal joint search -- forcing the
        unlocked side to match the locked side's exact current direction
        would also satisfy G1 alignment, but can settle on a worse fit for
        the unlocked side than letting both sides move to find it together.

        `boundary_handles` is the (seg_i, attr) set of handles sitting right at
        a locked/unlocked boundary -- the caller already had to compute this
        same set to know which handles to re-fit fresh instead of translating
        from cache (see create_catmull_rom), so it's passed in rather than
        re-derived here.
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

        def acceptable_alternative(alt_score, original_score, chord_length):
            ''' Whether alt_score is close enough to original_score to prefer the
            alternative on other (non-fit-quality) grounds -- e.g. a degenerately
            short or near-perpendicular handle that technically scored best. Allows
            up to double the original score, plus a small margin scaled to the
            segment's own chord so an original score near zero doesn't make every
            alternative look unacceptably worse by comparison. '''
            return alt_score <= original_score * 2.0 + 0.02 * chord_length

        def significantly_better(better_score, worse_score, chord_length):
            ''' The inverse, much stricter bar from acceptable_alternative --
            whether better_score improves on worse_score by enough to justify
            keeping something as visually disruptive as an over-chord-length
            handle (see the long-handle guardrail). Deliberately an absolute
            margin only, not a ratio: a run with very few interior points can
            have both scores sitting near zero, where even a 10x-or-more
            relative improvement is still visually meaningless -- the gap has
            to be a real fraction of the segment's own chord to be worth an
            overshoot this size. '''
            return worse_score - better_score > 0.2 * chord_length

        wrap_ok = cyclic and nseg >= 2
        junction_range = range(nseg) if wrap_ok else range(max(0, nseg - 1))

        # A handle is frozen (skipped by both scale and rotate) only if its own
        # segment is locked AND it isn't paired at an aligned junction with an
        # unlocked segment. An unpaired locked handle (a corner or an open
        # strip's end) has no neighbor to accommodate, so it stays frozen. One
        # that IS paired with an unlocked neighbor needs to stay eligible for
        # both -- pinning its length while only its direction can move is its
        # own source of forcing a worse joint fit, the same issue as pinning
        # direction outright.
        # `boundary_handles` (a caller-computed (seg_i, attr) set -- see
        # create_catmull_rom, the sole caller) marks handles right at a
        # locked/unlocked boundary. These start the search from whatever the
        # locked side happened to have cached, not the fresh Catmull-Rom guess
        # a fully-unlocked handle gets -- give them a wider search so a
        # possibly-stale starting point doesn't strand them in a worse local
        # optimum than a from-scratch fit would have found. They stay eligible
        # despite their segment being locked -- pinning them like the rest of
        # a locked segment's handles is its own source of forcing a worse
        # joint fit with the unlocked neighbor, the same issue as pinning
        # direction outright (see the rotate-pass note above). These are few
        # (at most two per contiguous locked run), so searching them harder
        # doesn't meaningfully undercut the savings from skipping the rest of
        # a locked region entirely.
        frozen_handles = set()
        for seg_i in locked_segs:
            frozen_handles.add((seg_i, 'p1'))
            frozen_handles.add((seg_i, 'p2'))
        frozen_handles -= boundary_handles

        for _ in range(rounds):
            # --- scale: every handle, always independent ---
            # scale_scores[seg_i] tracks the total_distance each committed
            # evaluate() call below already computed, so the degenerate-length
            # guardrail just after this loop can reuse it as `original_score`
            # instead of recomputing the same thing fresh.
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
                        # same reasoning as the rotate pass's coarse scan: this
                        # handle's cached length was tuned for a shape its
                        # neighbor no longer has, so try a spread of multipliers
                        # first instead of only ever nudging from 1x
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

            # a handle that shrank to near nothing relative to its counterpart
            # looks visually broken (the curve makes an abrupt transition right
            # at the knot) even though the scale search, per handle, found it
            # technically fits marginally better there. Jumping straight to the
            # counterpart's own length is often too far a stretch to be
            # acceptable (the two handles can legitimately need very different
            # lengths), which would make this guardrail give up and leave the
            # degenerate length in place even when a much more modest stretch
            # was well within budget. Try a ladder of chord-relative rungs
            # instead, capped at the counterpart's length, and keep the
            # longest one that doesn't cost much fit quality -- so a handle
            # that can't reach its counterpart at least stops looking like a
            # cusp.
            #
            # This runs even for a frozen (locked) segment's handles -- locking
            # only means the fit-to-points was good enough to skip the search
            # above, and a run with very few interior points can have plenty
            # of degenerate-looking handle configurations that all score just
            # as well as a reasonable-looking one (see the long-handle
            # guardrail's own note on this). A visually broken handle
            # shouldn't get to survive indefinitely just because it happened
            # to be "locked in" once. The cheap ratio check just below still
            # gates the (tessellation-based) score comparisons, so this only
            # costs anything extra for the rare handle that actually looks
            # degenerate, not for the common case of an already-fine locked
            # segment.
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
                # descending: fit quality only gets worse as the candidate
                # gets longer (confirmed empirically -- see this guardrail's
                # own history), so the first (largest) rung that's acceptable
                # is guaranteed to be the best one available, and everything
                # smaller than it would also pass without needing to check.
                # Stopping there instead of testing the whole ladder saves a
                # total_distance call (tessellation + closest-point search)
                # per rung that would've just confirmed what's already known.
                rungs = sorted({
                    min(f * chord_length, long_len)
                    for f in (0.15, 0.2, 0.3, 0.5, 0.75, 1.0)
                    if f * chord_length > short_len
                }, reverse=True)
                best_len = short_len
                for cand_len in rungs:
                    setattr(cb, short_attr, anchor + direction * cand_len)
                    if acceptable_alternative(CubicBezierSpline.total_distance(cb, run), original_score, chord_length):
                        best_len = cand_len
                        break
                setattr(cb, short_attr, anchor + direction * best_len)

            # the guardrail above only compares a handle to its OWN
            # counterpart, so a pair sitting at, say, a 0.3:1 ratio to each
            # other never triggers it -- even when BOTH are an absolute
            # pinprick relative to their own chord (seen in practice: two
            # handles under 1% of the chord, "balanced" enough to slip past
            # the ratio check entirely). That symmetric case looks just as
            # broken at the knot as the asymmetric one above, so each handle
            # is also checked independently against its own chord here,
            # using the same descending, break-on-first-acceptable ladder.
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
                        if acceptable_alternative(CubicBezierSpline.total_distance(cb, run), original_score, chord_length):
                            best_len = cand_len
                            break
                    setattr(cb, attr, anchor + direction * best_len)

            # a handle much longer than its own segment's chord risks a visible
            # bulge or loop overshooting the curve, even when the search found
            # it fits the points marginally better. Half the chord is
            # preferred (using the same generous acceptable_alternative margin
            # as the other guardrails); beyond the full chord length is
            # discouraged much more strongly -- kept only when it's a clearly
            # *better* fit, not merely an acceptable one. A run with very few
            # interior points is under-constrained enough that "longer keeps
            # scoring better" can continue indefinitely (nothing else pins the
            # curve down) without the length ever reflecting a real visual
            # need -- so regardless of score, a handle is never let past twice
            # the chord length; "significantly better" only ever gets to
            # choose between half the chord and that hard cap, never the raw
            # (possibly far longer) search result directly.
            #
            # Also runs on frozen (locked) handles, same reasoning as the
            # short-handle guardrail above.
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
                        keep_long = not acceptable_alternative(short_score, long_score, chord_length)
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
                # skip the (expensive) search for a group that's *entirely*
                # locked -- nothing there can move regardless. A group with a
                # mix of locked and unlocked arms runs the same search as a
                # fully-unlocked one: forcing the unlocked side to match the
                # locked side's exact current direction would satisfy G1
                # alignment too, but with no room for the locked side to also
                # give a little, that can settle on a worse fit for the
                # unlocked side than a real joint search would -- and the
                # locked side's own fit was only ever established as *good
                # enough* (within tolerance), not perfect, so there was never
                # a hard requirement to hold it at exactly its current value
                # in the first place. A fully-locked group still runs the
                # near-perpendicular guardrail below, though (skip_search
                # only bypasses the search, not that check) -- same reasoning
                # as the scale-pass guardrails above: locking is about
                # fit-to-points, not about the handle direction looking sane.
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
                    # p1 points away from its knot in the curve's direction of
                    # travel; p2 points backward against it -- so at a shared
                    # knot the two handles' raw vectors are supposed to be
                    # opposite, not equal. `sign` converts each into a common
                    # "direction of travel" so they can be averaged/rotated as
                    # one, and converts back when writing the result below.
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
                    # nothing here is free to move -- evaluate(0.0) just
                    # confirms the arms' current (already-aligned, since
                    # `shared` is their own combined direction) state without
                    # spending a search on it, so the guardrail below still
                    # has a committed_dir/best_score to compare against.
                    best_t = 0.0
                else:
                    initial_t = 0.0
                    if is_boundary:
                        # hot_cold_search is a greedy local search: starting at
                        # the locked side's cached direction, it can get stuck
                        # without ever finding a much-better direction on "the
                        # other side" of a worse one in between. A coarse scan
                        # around the full circle first finds roughly the right
                        # neighborhood for the normal search to then refine
                        # from -- affordable here since boundary groups are few.
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

                # a handle nearly perpendicular to the curve's own local tangent
                # looks visually wrong even if the search found it technically
                # fits marginally better -- e.g. a slight kink right at this
                # knot can make a handle pointing "sideways" score well for the
                # few nearby points without looking anything like the curve's
                # actual direction of travel there. local_tangent is a simple,
                # run-only estimate of that direction (the secant to each arm's
                # nearest interior point, or its chord if it has none), grouped
                # and sign-corrected the same way `shared` is. If a direction
                # closer to it doesn't cost much fit quality, prefer that over
                # a near-perpendicular (or reversed) result.
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
                        if not acceptable_alternative(tangent_score, best_score, chord.length):
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
