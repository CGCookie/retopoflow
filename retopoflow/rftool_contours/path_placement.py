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

'''
Vert placement along a cut path.

One routine places verts for fresh cuts, loop cuts and extrusions. A base placement B (the artist's loop
projected onto the cut, or even spacing for a fresh cut) is blended toward a shape fit C by the Curvature
slider and toward even spacing E by the Space Evenly slider. Everything discrete (which corners get a vert,
which vert lands on which corner, how many verts sit between corners) is decided from geometry and vert
count alone, never from a slider, so dragging a slider only ever moves verts smoothly along the path.

Path factors are 0-1 fractions of arc length along the cut. Cyclic math is done on "unrolled" factors, a
monotone sequence starting at the first vert's factor, and wrapped with % 1.0 once at the end.
'''

import math
from dataclasses import dataclass

import numpy as np
from mathutils import Vector

from ..common.maths import sample_even, arc_path_factors, path_facs_to_positions, cyclic_even_phase


MAX_SAMPLES = 256        # Cap on path samples so the chord table stays cheap
SAMPLES_PER_VERT = 4     # But always give the solver a few candidate positions per vert
MAX_SPAN_FACTOR = 3.0    # No edge longer than this many target edge lengths
SAG_REF = 0.05           # A chord sag of 5% of the target edge length is one unit of fit cost
FLAT_BOOST = 9.0         # Deviations on flat samples cost up to (1 + FLAT_BOOST) times more
FLAT_ANGLE = 5.0         # Degrees of turn within one target edge length that still counts as flat
SHARP_ANGLE = 30.0       # Turns sharper than this are corners
CORNER_WINDOW = 0.25     # A turn of SHARP_ANGLE completed within this fraction of a target edge is a corner
DETAIL_FRAC = 0.4        # Sharp points closer than this fraction of a target edge bound sub-resolution detail
FIT_MIX = 0.7            # Fixed balance of shape fit vs edge length inside the solver
LEN_MIX = 1.0 - FIT_MIX
FLAT_EDGE_ANGLE = 5.0    # Degrees per target edge below which an edge counts as flat (transition test)
CURVED_EDGE_ANGLE = 15.0 # Degrees per target edge above which an edge counts as curved (transition test)
ANCHOR_HOLD_RAMP = 0.25  # Curvature value at which Space Evenly fully holds corners and transitions
MAX_ALIGN_SHIFT = 0.125  # Furthest a ring is slid along the path to line its corners up with the cut's (45 degrees of a loop)
ALIGN_TOL = 0.25         # A ring corner within this fraction of a target edge of a cut corner counts as paired
ALIGN_MIN_PAIRED = 0.75  # Fraction of the ring's corners that must pair up before the ring is slid


# ---------------------------------------------------------------------------------------------------------------
# Path analysis

@dataclass
class PathFit:
    '''Slider-free analysis of a cut path at a given vert count.'''
    P: np.ndarray            # (m, 3) sample positions; corner apexes sit on the virtual sharp corner
    facs: np.ndarray         # (m,) path factor of each sample along the original cut
    turn: np.ndarray         # (m,) turning angle at each sample, radians
    theta: np.ndarray        # (m,) turning within one target edge of each sample
    fit_weight: np.ndarray   # (m,) weight on chord deviation per sample, 0 = free to skip
    corner_samples: set      # sample indices that are corners
    m: int
    cyclic: bool
    path_length: float
    target_len: float
    k_t: int                 # samples per target edge
    dev_ref: float


def analyze_path(points: list, cyclic: bool, vertex_count: int, path_length: float) -> PathFit | None:
    '''Resample the cut, keep its sharp points as samples, and work out per-sample turning, flatness weights,
    corners and sub-resolution detail. Returns None when a fit is not possible (too few points or verts).'''
    n = len(points)
    if n < 3 or vertex_count < 2 or path_length < 1e-10 or vertex_count >= n:
        return None
    m = max(SAMPLES_PER_VERT * vertex_count, min(n, MAX_SAMPLES))
    samples = sample_even(points, cyclic, m, path_length)
    if not samples or len(samples) <= vertex_count:
        return None
    P = np.array([(p.x, p.y, p.z) for p in samples])
    m = len(P)
    seg_count = m if cyclic else m - 1
    facs = np.arange(m) / seg_count  # sample_even spaces samples evenly along the original path
    target_len = path_length / (vertex_count if cyclic else max(vertex_count - 1, 1))
    k_t = max(1, round(target_len * seg_count / path_length))
    sharp = math.radians(SHARP_ANGLE)

    # Sharp points of the original cut become samples, so one vert can sit exactly on a corner
    point_facs = arc_path_factors(points, cyclic)
    sharp_pts = _sharp_points(points, cyclic, sharp)
    def sample_of(i):
        return int(round(point_facs[i] * seg_count)) % m
    corner_samples = set()
    for i in sharp_pts:
        j = sample_of(i)
        if j in corner_samples:
            continue
        corner_samples.add(j)
        P[j] = (points[i].x, points[i].y, points[i].z)
        facs[j] = point_facs[i]
    if not cyclic:
        P[0] = (points[0].x, points[0].y, points[0].z)
        P[-1] = (points[-1].x, points[-1].y, points[-1].z)

    # Turning per sample and flatness: total turning within one target edge length
    turn = _turning(P, cyclic)
    theta = _windowed_sum(turn, max(1, k_t // 2), cyclic)
    if theta.max() < 1e-9:
        return None
    fit_weight = 1.0 + FLAT_BOOST * np.exp(-theta / math.radians(FLAT_ANGLE))

    # Corners at this resolution: a sharp turn completed within a small fraction of a target edge. A cut method
    # that rounds corners off leaves no sample on the true corner, so the apex sample is evaluated at the
    # virtual sharp corner where the two flats meet and its shoulders cost nothing to skip. One vert then fits
    # both flats exactly. The apex's output position stays on the cut path.
    half_c = max(1, round(CORNER_WINDOW * k_t / 2))
    for run in _runs(_windowed_sum(turn, half_c, cyclic) >= sharp, cyclic):
        apex = max(run, key=lambda r: turn[r])
        for j in _neighbourhood(apex, half_c, m, cyclic):
            if j != apex:
                fit_weight[j] = 0.0
        corner_samples.add(apex)
        _snap_to_virtual_corner(P, apex, half_c, cyclic, target_len)

    # Sub-resolution detail: sharp points closer together than a fraction of a target edge bound a feature that
    # cannot be represented at this vert count (a notch, a slot). Samples strictly inside such a run cost nothing
    # to skip, so the fit runs straight across the feature instead of averaging between it and the flats around
    # it. The run's end corners keep their weight.
    ks = len(sharp_pts)
    if ks >= 2:
        def gap(a, b):
            return ((point_facs[b] - point_facs[a]) % 1.0 if cyclic else point_facs[b] - point_facs[a]) * path_length
        close = [0 < gap(sharp_pts[g], sharp_pts[(g + 1) % ks]) < DETAIL_FRAC * target_len
                 for g in range(ks if cyclic else ks - 1)]
        for run in _runs(close, cyclic):
            s0 = sample_of(sharp_pts[run[0]])
            s1 = sample_of(sharp_pts[(run[-1] + 1) % ks])
            for d in range(1, (s1 - s0) % m if cyclic else s1 - s0):
                fit_weight[(s0 + d) % m] = 0.0

    return PathFit(P=P, facs=facs, turn=turn, theta=theta, fit_weight=fit_weight, corner_samples=corner_samples,
                   m=m, cyclic=cyclic, path_length=path_length, target_len=target_len, k_t=k_t,
                   dev_ref=SAG_REF * target_len)


def _sharp_points(points: list, cyclic: bool, min_turn: float) -> list:
    '''Indices of the original cut points that turn by at least `min_turn` radians. Open path ends are excluded.'''
    n = len(points)
    out = []
    for i in range(n):
        if not cyclic and (i == 0 or i == n - 1):
            continue
        a = points[i] - points[i - 1]
        b = points[(i + 1) % n] - points[i]
        if a.length < 1e-12 or b.length < 1e-12:
            continue
        if math.atan2(a.cross(b).length, a.dot(b)) >= min_turn:
            out.append(i)
    return out


def _turning(P: np.ndarray, cyclic: bool) -> np.ndarray:
    '''Turning angle at each sample, radians. Open path ends turn by 0.'''
    idx = np.arange(len(P))
    t1 = P - P[np.roll(idx, 1)]
    t2 = P[np.roll(idx, -1)] - P
    turn = np.arctan2(np.linalg.norm(np.cross(t1, t2), axis=1), (t1 * t2).sum(axis=1))
    if not cyclic:
        turn[0] = turn[-1] = 0.0
    return turn


def _windowed_sum(values: np.ndarray, half: int, cyclic: bool) -> np.ndarray:
    '''Sum of `values` over a window of `half` samples either side of each sample.'''
    padded = np.concatenate([values[-half:], values, values[:half]]) if cyclic else np.pad(values, half, mode='constant')
    return np.convolve(padded, np.ones(2 * half + 1), mode='valid')


def _neighbourhood(i: int, half: int, m: int, cyclic: bool) -> list:
    '''Sample indices within `half` of sample i.'''
    if cyclic:
        return [(i + d) % m for d in range(-half, half + 1)]
    return [j for j in range(i - half, i + half + 1) if 0 <= j < m]


def _runs(flags, cyclic: bool) -> list:
    '''Runs of consecutive True flags as index lists. Cyclic runs are joined across the wrap. A cyclic sequence
    that is all True has no bounded runs and yields none.'''
    flags = list(flags)
    n = len(flags)
    if not any(flags):
        return []
    if all(flags):
        return [] if cyclic else [list(range(n))]
    start = (flags.index(False) + 1) % n if cyclic else 0
    runs, run = [], []
    for step in range(n + 1):
        j = (start + step) % n
        if step < n and flags[j]:
            run.append(j)
        elif run:
            runs.append(run)
            run = []
    return runs


def _snap_to_virtual_corner(P: np.ndarray, apex: int, half: int, cyclic: bool, max_move: float) -> None:
    '''Move sample `apex` to where the lines through the samples just outside its window meet, if that point is
    within `max_move`. Leaves it alone when the two sides are parallel or the window runs off an open path.'''
    m = len(P)
    span = range(apex - half - 1, apex + half + 2)
    if cyclic:
        span = [j % m for j in span]
    elif span[0] < 0 or span[-1] >= m:
        return
    a0, a1, b0, b1 = P[span[0]], P[span[1]], P[span[-2]], P[span[-1]]
    u, v, w0 = a1 - a0, b1 - b0, a1 - b0
    uu, uv, vv, uw, vw = u @ u, u @ v, v @ v, u @ w0, v @ w0
    denom = uu * vv - uv * uv
    if denom < 1e-12 * uu * vv:
        return
    s = (uv * vw - vv * uw) / denom
    t = (uu * vw - uv * uw) / denom
    corner = 0.5 * ((a1 + s * u) + (b0 + t * v))
    if np.linalg.norm(corner - P[apex]) <= max_move:
        P[apex] = corner


# ---------------------------------------------------------------------------------------------------------------
# Shape fit: dynamic programming over chords between samples

def fit_span(pf: PathFit, i0: int, i1: int, count: int) -> tuple:
    '''Best `count` interior verts between samples i0 and i1 (inclusive ends), by dynamic programming over chords.
    Each chord costs a fixed mix of weighted deviation of the samples it skips and its length against the target.
    On a cyclic path i0 == i1 means the whole loop. Returns (sample indices including both ends, total cost),
    or (None, inf) when the span has fewer samples than verts.'''
    m = pf.m
    if pf.cyclic:
        span_n = (i1 - i0) % m if i1 != i0 else m
        seq = np.arange(i0, i0 + span_n + 1) % m
    else:
        seq = np.arange(i0, i1 + 1)
    M = len(seq)
    N = count + 2
    INF = float('inf')
    if M < N:
        return None, INF
    P = pf.P[seq]
    weight = pf.fit_weight[seq]
    arc_pos = np.concatenate([[0.0], np.cumsum(np.linalg.norm(P[1:] - P[:-1], axis=1))])
    band = min(M - 1, max(2, int(math.ceil(MAX_SPAN_FACTOR * pf.k_t))))
    if band * (N - 1) < M - 1:
        band = M - 1

    cost = np.full((M, M), INF)
    for i in range(M - 1):
        hi = min(M, i + band + 1)
        J = np.arange(i + 1, hi)
        D = P[J] - P[i]
        D2 = np.maximum((D * D).sum(axis=1), 1e-20)
        if hi - i > 2:
            # Weighted distance of every interior sample k to every chord i->j, then the worst per chord
            Q = P[i + 1:hi - 1] - P[i]
            QD = Q @ D.T
            t = np.clip(QD / D2, 0.0, 1.0)
            dist2 = (Q * Q).sum(axis=1)[:, None] - 2.0 * t * QD + t * t * D2
            dev = np.sqrt(np.maximum(dist2, 0.0)) * weight[i + 1:hi - 1, None]
            dev[np.arange(i + 1, hi - 1)[:, None] >= J[None, :]] = 0.0  # k is only skipped by chords that end past it
            fit = dev.max(axis=0)
        else:
            fit = np.zeros(len(J))
        cost[i, J] = FIT_MIX * (fit / pf.dev_ref) ** 2 + LEN_MIX * ((arc_pos[J] - arc_pos[i]) / pf.target_len) ** 2

    # best[k, j] is the cheapest way to reach sample j using k edges, solved a row at a time
    best = np.full((N, M), INF)
    back = np.zeros((N, M), dtype=int)
    best[0, 0] = 0.0
    J_all = np.arange(M)
    I_prev = J_all[:, None] - np.arange(1, band + 1)[None, :]
    valid = I_prev >= 0
    I_safe = np.where(valid, I_prev, 0)
    step_cost = np.where(valid, cost[I_safe, J_all[:, None]], INF)
    for k in range(1, N):
        total = best[k - 1][I_safe] + step_cost
        pick = np.argmin(total, axis=1)
        best[k] = total[J_all, pick]
        back[k] = I_safe[J_all, pick]
        best[k, :k] = INF
        best[k, M - (N - 1 - k):] = INF
    if best[N - 1, M - 1] == INF:
        return None, INF
    chosen = [M - 1]
    for k in range(N - 1, 0, -1):
        chosen.append(back[k, chosen[-1]])
    chosen.reverse()
    return [int(seq[c]) for c in chosen], float(best[N - 1, M - 1])


def fit_loop(pf: PathFit, count: int) -> list | None:
    '''Fit `count` verts around a cyclic path, in path order. Opening the loop forces a vert on the opening
    sample, so solve once opened at the sharpest sample and once at the vert roughly opposite, keep the cheaper.'''
    start = int(np.argmax(pf.theta))
    idx, total = fit_span(pf, start, start, count - 1)
    if idx is None:
        return None
    idx = idx[:-1]
    start_fac = pf.facs[start]
    opposite = min(idx, key=lambda s: abs(((pf.facs[s] - start_fac) % 1.0) - 0.5))
    idx2, total2 = fit_span(pf, opposite, opposite, count - 1)
    if idx2 is not None and total2 <= total:
        idx = idx2[:-1]
    return sorted(idx, key=lambda s: pf.facs[s])


def fit_global(pf: PathFit, count: int) -> list | None:
    '''Unconstrained fit at the ring's vert count, in path order. Decides which corners get a vert and, for fresh
    cuts, how many verts each corner gap gets.'''
    if pf.cyclic:
        return fit_loop(pf, count)
    idx, _ = fit_span(pf, 0, pf.m - 1, count - 2)
    return idx


# ---------------------------------------------------------------------------------------------------------------
# Placing a ring of verts

def unroll_facs(facs, cyclic: bool) -> np.ndarray:
    '''Path factors of a forward-ordered ring as a monotone sequence starting at facs[0] (cyclic wrap removed).'''
    f = np.asarray(facs, dtype=float)
    if not cyclic or len(f) == 0:
        return f
    return f[0] + ((f - f[0]) % 1.0)


def _circ(d: float) -> float:
    '''Shortest distance between two path factors that differ by d.'''
    d = abs(d % 1.0)
    return min(d, 1.0 - d)


def align_to_corners(B: np.ndarray, sharp_verts: set, anchor_facs: list) -> np.ndarray:
    '''Slide a cyclic ring along the path so the ring's own corners (`sharp_verts`, indices into B) line up with
    the cut's corners. A twisted source rotates the cut's corners away from the projected ring's corners, and
    without this the wrong verts would claim them. The slide is skipped when it would exceed MAX_ALIGN_SHIFT
    or when the corners do not clearly pair up.'''
    n = len(B)
    sharp_facs = [B[v] for v in sharp_verts if 0 <= v < n]
    if not anchor_facs or not sharp_facs:
        return B
    def residuals(shift):
        return [min(_circ(g + shift - a) for a in anchor_facs) for g in sharp_facs]
    shifts = sorted({(a - f + 0.5) % 1.0 - 0.5 for a in anchor_facs for f in sharp_facs}, key=abs)
    best_shift, best_cost = 0.0, sum(residuals(0.0))
    for shift in shifts:
        if abs(shift) > MAX_ALIGN_SHIFT:
            continue
        cost = sum(residuals(shift))
        if cost < best_cost - 1e-12:  # ties keep the smaller shift
            best_shift, best_cost = shift, cost
    paired = sum(1 for r in residuals(best_shift) if r <= ALIGN_TOL / n)
    if paired < max(2, math.ceil(ALIGN_MIN_PAIRED * len(sharp_facs))):
        return B
    return B + best_shift


def assign_anchors(B: np.ndarray, anchor_samples: list, pf: PathFit, prefer: set | None = None) -> dict:
    '''Give each anchor (a corner sample the fit chose) to one of the two base verts that bracket it along the
    path, nearest first, then re-deal so anchors and verts stay in the same order. Verts in `prefer` (corners of
    the loop being extruded) count as half as far away. Returns vert index -> (anchor sample, anchor path
    factor in the unrolled frame of B). Open paths always anchor their end verts to the path ends, with
    sample None.'''
    n = len(B)
    cyclic = pf.cyclic
    b0 = B[0]
    result = {}
    if not cyclic:
        result[0] = (None, 0.0)
        result[n - 1] = (None, 1.0)
    # Candidate verts are addressed by unrolled position 0..n; position n is vert 0 reached through the wrap gap
    candidates = []
    for s in anchor_samples:
        a = b0 + ((pf.facs[s] - b0) % 1.0) if cyclic else float(pf.facs[s])
        if not cyclic and not (0.0 < a < 1.0):
            continue
        g = int(np.searchsorted(B, a, side='right')) - 1
        if cyclic:
            g = min(max(g, 0), n - 1)
            hi_pos = g + 1
            hi_val = B[hi_pos] if hi_pos < n else B[0] + 1.0
        else:
            g = min(max(g, 0), n - 2)
            hi_pos = g + 1
            hi_val = B[hi_pos]
        for pos, d in ((g, a - B[g]), (hi_pos, hi_val - a)):
            if not cyclic and pos in (0, n - 1):
                continue
            d = abs(d) * (0.5 if prefer and (pos % n) in prefer else 1.0)
            candidates.append((d, s, pos, a))
    taken = set(result)
    assigned = {}
    for _, s, pos, a in sorted(candidates):
        if s in assigned or (pos % n) in taken:
            continue
        assigned[s] = (pos, a)
        taken.add(pos % n)
    # Re-deal in order so the ring order can never invert
    positions = sorted(pos for pos, _ in assigned.values())
    by_fac = sorted(assigned.items(), key=lambda kv: kv[1][1])
    for pos, (s, (_, a)) in zip(positions, by_fac):
        result[pos % n] = (s, a - 1.0 if pos >= n else a)
    return result


def _fit_between_anchors(pf: PathFit, A: np.ndarray, anchors: dict) -> tuple:
    '''Shape fit with the anchors fixed and each gap keeping its base vert count. Returns (C, C_idx): the fit
    factors in A's unrolled frame and the sample index behind each vert (None where a gap fell back to a
    linear spread).'''
    n = len(A)
    cyclic = pf.cyclic
    C = A.copy()
    C_idx = [None] * n
    for v, (s, _) in anchors.items():
        C_idx[v] = s if s is not None else (0 if v == 0 else pf.m - 1)
    av = sorted(anchors)
    pairs = list(zip(av, av[1:]))
    if cyclic:
        pairs.append((av[-1], av[0] + n))
    for ia, ib in pairs:
        count = ib - ia - 1
        if count <= 0:
            continue
        fa = A[ia % n]
        fb = A[ib % n] + (1.0 if ib >= n else 0.0)
        idx, _ = fit_span(pf, C_idx[ia % n], C_idx[ib % n], count)
        for k in range(1, count + 1):
            v = (ia + k) % n
            if idx is None:
                c = fa + (fb - fa) * k / (count + 1)
            else:
                C_idx[v] = idx[k]
                c = fa + ((pf.facs[idx[k]] - fa) % 1.0) if cyclic else pf.facs[idx[k]]
            C[v] = c - 1.0 if ia + k >= n else c  # verts past the seam come back to the base frame
    return C, C_idx


def _match_loop_fit(pf: PathFit, B: np.ndarray, G: list) -> tuple:
    '''For a cyclic ring with no corners: pair the fit's verts to the base verts by the rotation that moves them
    least. Returns (C, C_idx) in B's unrolled frame.'''
    n = len(B)
    Gs = np.array([pf.facs[s] for s in G])
    best_k, best_cost = 0, float('inf')
    for k in range(n):
        d = np.abs((np.roll(Gs, -k) - B) % 1.0)
        cost = np.minimum(d, 1.0 - d).sum()
        if cost < best_cost:
            best_k, best_cost = k, cost
    order = list(np.roll(np.array(G), -best_k))
    C = np.array([B[v] + ((pf.facs[order[v]] - B[v] + 0.5) % 1.0) - 0.5 for v in range(n)])
    return C, [int(s) for s in order]


def transition_verts(pf: PathFit, C_idx: list, anchored: set) -> set:
    '''Verts of the fit that sit where a flat edge meets a curved one, judged by turning per target edge on the
    two adjacent edges. Smooth loops with no flat edge yield none.'''
    n = len(C_idx)
    def edge_turn(sa, sb):
        span_n = (sb - sa) % pf.m if pf.cyclic else sb - sa
        if span_n <= 0:
            return None
        ks = np.arange(sa + 1, sa + span_n) % pf.m
        ang = math.degrees(pf.turn[ks].sum()) if len(ks) else 0.0
        length = ((pf.facs[sb] - pf.facs[sa]) % 1.0 if pf.cyclic else pf.facs[sb] - pf.facs[sa]) * pf.path_length
        return ang * pf.target_len / max(length, 1e-12)
    out = set()
    for i in range(n):
        if i in anchored or C_idx[i] is None:
            continue
        prev_i, next_i = i - 1, i + 1
        if pf.cyclic:
            prev_i, next_i = prev_i % n, next_i % n
        elif prev_i < 0 or next_i >= n:
            continue
        if C_idx[prev_i] is None or C_idx[next_i] is None:
            continue
        t_in, t_out = edge_turn(C_idx[prev_i], C_idx[i]), edge_turn(C_idx[i], C_idx[next_i])
        if t_in is None or t_out is None:
            continue
        flat_in, flat_out = t_in <= FLAT_EDGE_ANGLE, t_out <= FLAT_EDGE_ANGLE
        curved_in, curved_out = t_in >= CURVED_EDGE_ANGLE, t_out >= CURVED_EDGE_ANGLE
        if (flat_in and curved_out) or (curved_in and flat_out):
            out.add(i)
    return out


def spread_between(values: np.ndarray, held, cyclic: bool) -> np.ndarray:
    '''Copy of `values` with every vert not in `held` spread linearly (by index) between its nearest held
    neighbours. With nothing held the values come back unchanged.'''
    n = len(values)
    out = values.copy()
    held = sorted(held)
    if not held:
        return out
    pairs = list(zip(held, held[1:]))
    if cyclic:
        pairs.append((held[-1], held[0] + n))
    for a, b in pairs:
        va = values[a % n]
        vb = values[b % n] + (1.0 if b >= n else 0.0)
        for k in range(a + 1, b):
            out[k % n] = va + (vb - va) * (k - a) / (b - a) - (1.0 if k >= n else 0.0)
    return out


def even_facs(B: np.ndarray, cyclic: bool) -> np.ndarray:
    '''Even spacing for the whole ring in B's unrolled frame, phased to move the base as little as possible.'''
    n = len(B)
    if not cyclic:
        return np.arange(n) / max(n - 1, 1)
    phase = cyclic_even_phase([f % 1.0 for f in B], 1.0 / n)
    return B[0] + ((phase - B[0] + 0.5) % 1.0 - 0.5) + np.arange(n) / n


def place_ring_facs(points: list, cyclic: bool, base_facs: list, path_length: float,
                    curvature: float, space_evenly: float, pf: PathFit | None = None, G: list | None = None,
                    sharp_verts: set | None = None) -> list:
    '''Final path factor for each ring vert. `base_facs` are the verts' current factors in forward ring order.
    Curvature blends toward the shape fit, Space Evenly toward even spacing; corners the fit chose are hit at
    any slider value except when Space Evenly releases them at Curvature near 0. `sharp_verts` are the ring
    verts that were corners of the loop being extruded; the ring is slid along the path to line them up with
    the cut's corners first. See the module docstring.'''
    n = len(base_facs)
    B = unroll_facs(base_facs, cyclic)
    curvature = max(0.0, min(1.0, curvature))
    space_evenly = max(0.0, min(1.0, space_evenly))
    if pf is None:
        pf = analyze_path(points, cyclic, n, path_length)
    if pf is not None and G is None:
        G = fit_global(pf, n)

    if pf is None or G is None:
        P = B
        E = even_facs(B, cyclic)
    else:
        anchor_samples = [s for s in G if s in pf.corner_samples]
        if cyclic and sharp_verts:
            B = align_to_corners(B, sharp_verts, [pf.facs[s] for s in anchor_samples])
        anchors = assign_anchors(B, anchor_samples, pf, prefer=sharp_verts)
        A = B.copy()
        for v, (_, f) in anchors.items():
            A[v] = f
        if anchors:
            C, C_idx = _fit_between_anchors(pf, A, anchors)
        else:
            C, C_idx = _match_loop_fit(pf, B, G)
        P = A + (C - A) * curvature

        # Even spacing: pure at Curvature 0, holding corners and flat-to-curve transitions once Curvature is up
        E0 = even_facs(B, cyclic)
        features = set(anchors) | transition_verts(pf, C_idx, set(anchors))
        E1 = spread_between(P, features, cyclic) if features else E0
        hold = min(1.0, curvature / ANCHOR_HOLD_RAMP)
        E = E0 + (E1 - E0) * hold

    F = P + (E - P) * space_evenly
    if cyclic:
        F = F % 1.0
    return [float(f) for f in F]


def sample_curvature(points: list, cyclic: bool, vertex_count: int, path_length: float,
                     curvature_bias: float = 0, space_evenly: float = 0) -> list:
    '''Vert positions for a fresh cut. The base is even spacing within the gaps between the corners the shape
    fit chose, with each gap keeping the fit's vert count; the sliders then blend as for any ring.'''
    n = len(points)
    if n < 3 or vertex_count <= 0 or path_length < 1e-10:
        return sample_even(points, cyclic, vertex_count, path_length) or []
    if vertex_count >= n:
        if vertex_count == n:
            return [Vector(p) for p in points]
        # More verts requested than source points — arc-length interpolation fills the gap.
        result = sample_even(points, cyclic, vertex_count, path_length)
        return result if result and len(result) >= vertex_count else [Vector(p) for p in points]
    pf = analyze_path(points, cyclic, vertex_count, path_length)
    G = fit_global(pf, vertex_count) if pf is not None else None
    if pf is None or G is None:
        return sample_even(points, cyclic, vertex_count, path_length) or []
    anchor_pos = [k for k, s in enumerate(G) if s in pf.corner_samples]
    if anchor_pos:
        base = spread_between(unroll_facs([pf.facs[s] for s in G], cyclic), anchor_pos, cyclic) % 1.0
    else:
        base = np.arange(vertex_count) / (vertex_count if cyclic else vertex_count - 1)
    facs = place_ring_facs(points, cyclic, list(base), path_length, curvature_bias, space_evenly, pf=pf, G=G)
    return path_facs_to_positions(points, facs, cyclic)
