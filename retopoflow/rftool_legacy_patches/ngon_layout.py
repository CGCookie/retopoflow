'''
Pure topology for quad-filling an n-sided loop: Tarini's single-pole layout, plus the fallbacks
used when a loop does not admit one. Nothing here imports bpy or mathutils, so
dev/test_ngon_layout.py runs it under plain python; positions are the logic module's business.

Sides are indexed cyclically. Side i runs from corner C_i to C_{i+1} with e_i edges. The loop is
"CC-able" (Tarini, Closed-form quadrangulation of n-sided patches, Computers & Graphics 2022) when
integers s_i >= 0 solve

    e_i = s_{i-1} + s_{i+1}

Side j is then split s_{j-1} edges from C_j, spoke j runs from that split vertex to the pole with
s_j edges, and the region at each corner is a regular grid. Strict CC-ability (all s_i >= 1) puts
the pole inside; an s_i of 0 puts it on the boundary.
'''

from dataclasses import dataclass, field
from functools import lru_cache
import itertools


##############################################
# the closed-form test

def cc_solve(counts, *, strict=False):
    ''' Every s solving e_i = s_{i-1} + s_{i+1} for the given side counts, most balanced first.
    Empty when the loop is not CC-able. Walking i -> i+2 with s_{i+2} = e_{i+1} - s_i makes each
    s_j linear in the chain's starting unknown, so closing the chain either fixes it (odd n, or
    n = 2 mod 4) or leaves it free inside an interval (n = 0 mod 4), which is Tarini's k. '''
    n = len(counts)
    if n < 3 or sum(counts) % 2: return []
    lo = 1 if strict else 0

    def walk(start):
        # s_j = a_j + b_j * k for every j on the chain, b_j = +-1; returns the chain and what s_start closes to
        lin = { start: (0, 1) }
        i = start
        while True:
            j = (i + 2) % n
            a, b = lin[i]
            nxt = (counts[(i + 1) % n] - a, -b)
            if j == start: return lin, nxt
            lin[j] = nxt
            i = j

    chains = [walk(0)] if n % 2 else [walk(0), walk(1)]
    choices = []
    for lin, (ca, cb) in chains:
        if cb == 1:
            # rank deficient: the chain closes for any k iff ca == 0, then k ranges over an interval
            if ca != 0: return []
            kmin = max(lo - a for a, b in lin.values() if b > 0)
            kmax = min(a - lo for a, b in lin.values() if b < 0)
            if kmin > kmax: return []
            ks = list(range(kmin, kmax + 1))
            mid = (kmin + kmax) / 2
            ks.sort(key=lambda k: abs(k - mid))
            choices.append((lin, ks))
        else:
            # closes as ca - k == k
            if ca % 2: return []
            choices.append((lin, [ca // 2]))

    sols = []
    for ks in itertools.product(*(c[1] for c in choices)):
        s = [None] * n
        for (lin, _), k in zip(choices, ks):
            for j, (a, b) in lin.items(): s[j] = a + b * k
        if all(v >= lo for v in s) and all(counts[i] == s[i - 1] + s[(i + 1) % n] for i in range(n)):
            sols.append(s)
    return sols


@lru_cache(maxsize=4096)
def _cc_state(counts):
    ''' (strictly CC-able, non-strictly CC-able) for a tuple of side counts. '''
    if not cc_solve(list(counts)): return (False, False)
    return (bool(cc_solve(list(counts), strict=True)), True)


def cc_hint(counts):
    ''' Smallest parity-preserving change to the side counts that would make the loop CC-able:
    a list of (side index, delta), or None. Small edits first (two on one side, one each on two
    sides), then larger edits to a single side, which is what an extreme loop needs. '''
    n = len(counts)
    tries = []
    for i in range(n):
        tries.append([(i, 2)])
        if counts[i] > 2: tries.append([(i, -2)])
    for i, j in itertools.combinations(range(n), 2):
        for di, dj in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            if counts[i] + di < 1 or counts[j] + dj < 1: continue
            tries.append([(i, di), (j, dj)])
    for d in range(4, 2 * max(counts) + 1, 2):
        for i in range(n):
            tries.append([(i, d)])
            if counts[i] - d >= 1: tries.append([(i, -d)])
    for edit in tries:
        c = list(counts)
        for i, d in edit: c[i] += d
        if _cc_state(tuple(c))[1]: return edit
    return None


##############################################
# loops and plans

@dataclass(frozen=True)
class Loop:
    ''' A closed run of node keys with the positions (indices into nodes) that are corners. '''
    nodes   : tuple
    corners : tuple

    def sides(self):
        ''' Node keys of each side, consecutive sides sharing their corner. '''
        m, cs = len(self.nodes), self.corners
        out = []
        for a, b in zip(cs, cs[1:] + cs[:1]):
            k, side = a, [self.nodes[a]]
            while k != b:
                k = (k + 1) % m
                side.append(self.nodes[k])
            out.append(side)
        return out

    def counts(self):
        m, cs = len(self.nodes), self.corners
        return tuple((b - a) % m or m for a, b in zip(cs, cs[1:] + cs[:1]))


@dataclass
class Plan:
    ''' How to fill one loop: a set of pieces each with its own single pole. '''
    kind    : str                   # 'pole' | 'merge' | 'cut' | 'phantom'
    pieces  : list                  # [(Loop, s)]
    cuts    : list = field(default_factory=list)    # node key runs of the cuts this plan makes, both ends included
    demoted : tuple = ()            # node keys of corners this plan treats as ordinary boundary verts
    score   : tuple = ()            # topological rank, lower is better
    phantom : tuple | None = None    # (piece index, side j, mode): that side carries an imaginary extra vertex, taken out again by mode 'ngon' | 'full' | 'short'

    @property
    def strict(self):
        return all(min(s) >= 1 for _, s in self.pieces)

    @property
    def poles(self):
        ''' Poles this plan makes, counting only those strictly inside a piece. '''
        return sum(1 for _, s in self.pieces if min(s) >= 1)


def plan_key(plan):
    ''' What tells one plan from another of the same kind: where its poles sit. '''
    return (plan.kind, tuple(tuple(s) for _, s in plan.pieces), plan.phantom, plan.demoted,
            tuple((run[0], run[-1], len(run)) for run in plan.cuts))


def plan_pole(loop):
    ''' Single-pole plans for the loop as it is, strict first. '''
    counts = list(loop.counts())
    seen, plans = set(), []
    for strict in (True, False):
        for s in cc_solve(counts, strict=strict):
            key = tuple(s)
            if key in seen: continue
            seen.add(key)
            plans.append(Plan('pole', [(loop, s)], score=(1, 0, 0 if strict else 1, 0)))
    return plans


def plan_merges(loop, sharpness=None):
    ''' Plans that demote some corners, merging their two sides, so the fewer sides left are
    CC-able. sharpness maps a corner position to how sharply the boundary turns there; the plans
    that keep the sharp corners rank first. '''
    cs = loop.corners
    n = len(cs)
    plans = []
    for r in range(1, n - 2):
        for demote in itertools.combinations(range(n), r):
            kept = tuple(cs[k] for k in range(n) if k not in demote)
            merged = Loop(loop.nodes, kept)
            counts = list(merged.counts())
            strict_sols = cc_solve(counts, strict=True)
            sols = strict_sols or cc_solve(counts)
            if not sols: continue
            turn = sum(sharpness.get(cs[k], 0.0) for k in demote) if sharpness else 0.0
            plans.append(Plan(
                'merge', [(merged, sols[0])],
                demoted=tuple(loop.nodes[cs[k]] for k in demote),
                score=(1, 0 if strict_sols else 1, round(turn, 3), r),
            ))
    plans.sort(key=lambda p: p.score)
    return plans


PHANTOM_MODES = ('ngon', 'full', 'short')

def plan_phantom(loop):
    ''' Plans for a loop with an odd edge count, which no quad fill can close. One side is given an
    imaginary extra vertex, placed so it is that side's split vertex, and the loop is filled round a
    pole as usual; build_layout then takes the vertex out again by one of three moves, each leaving
    a single non-quad:
      'ngon'  dissolves the vertex's spoke: the two quad rows beside it become one, and the pole's
              two faces there become one pentagon (a triangle on a 3-sided loop, where the pole
              itself dissolves). The pole drops one valence.
      'full'  collapses the strip between the spoke and the column beside it, pole row included:
              one triangle beside the pole, which gains one valence.
      'short' collapses that strip but stops one quad short: the pole keeps its valence, the vertex
              beside it goes to five, and the strip's last quad is the triangle.
    'ngon' ranks first, then 'full' up to four sides (the pole stays at five or less), else 'short'.
    Strict solutions only. '''
    cs = loop.corners
    n = len(cs)
    counts = list(loop.counts())
    if sum(counts) % 2 == 0: return []
    # strict solutions only: with the pole on the boundary, taking the imaginary vertex out again
    # loses a boundary edge or leaves a face out, so those are no plans at all
    plans = []
    for j in range(n):
        padded = list(counts)
        padded[j] += 1
        for s in cc_solve(padded, strict=True):
            at = cs[j] + s[j - 1]                   # the extra vertex is side j's split vertex
            nodes = loop.nodes[:at] + (('phantom', j),) + loop.nodes[at:]
            corners = tuple(c if c < at else c + 1 for c in cs)
            piece = Loop(nodes, corners)
            for mode in PHANTOM_MODES:
                rank = 0 if mode == 'ngon' else 1 if (mode == 'full') == (n <= 4) else 2
                plans.append(Plan('phantom', [(piece, s)], phantom=(0, j, mode), score=(1, 0, rank, 0)))
    plans.sort(key=lambda p: p.score)
    return plans


def _cut_loop(loop, p, q, cut_nodes):
    ''' The two loops a cut from position p to position q makes; cut_nodes runs p -> q. '''
    m, cs = len(loop.nodes), set(loop.corners)

    def piece(a, b, cut):
        # boundary a -> b forward, then the cut back from b to a
        nodes, corners, k = [], [0], a
        nodes.append(loop.nodes[a])
        while k != b:
            k = (k + 1) % m
            if k in cs and k != b: corners.append(len(nodes))
            nodes.append(loop.nodes[k])
        corners.append(len(nodes) - 1)
        nodes.extend(cut[1:-1])
        return Loop(tuple(nodes), tuple(corners))

    return piece(p, q, cut_nodes[::-1]), piece(q, p, cut_nodes)


def _cut_score(pieces, irregular):
    boundary_poles = sum(1 for _, s in pieces if min(s) < 1)
    return (len(pieces), irregular, boundary_poles, 0)


def plan_cuts(loop, *, max_depth=2, limit=8, _cid=0, _base_corners=None):
    ''' Plans that cut the loop into CC-able pieces along new edge runs. Depth 1 is exhaustive over
    pairs of boundary positions; depth 2 only recurses into the piece that stopped the best
    depth-1 attempts. Cuts between two non-corner positions keep every corner regular; a cut that
    ends on a corner adds a boundary edge there and ranks after. '''
    m, cs = len(loop.nodes), loop.corners
    if _base_corners is None: _base_corners = { loop.nodes[c] for c in cs }
    corner_set = set(cs)
    # which sides each position lies on; a corner is on two, and a cut within one side is never useful
    sides_at = [set() for _ in range(m)]
    for k, (a, b) in enumerate(zip(cs, cs[1:] + cs[:1])):
        p = a
        while True:
            sides_at[p].add(k)
            if p == b: break
            p = (p + 1) % m

    def piece_counts(a, b):
        # side counts of the boundary walked forward from a to b, split at the corners passed
        counts, run, k = [], 0, a
        while k != b:
            k = (k + 1) % m
            run += 1
            if k in corner_set or k == b:
                counts.append(run)
                run = 0
        return counts

    def solve(counts):
        return (cc_solve(counts, strict=True) or cc_solve(counts))[0]

    plans, partial = [], []
    for p in range(m):
        for q in range(p + 1, m):
            if sides_at[p] & sides_at[q]: continue
            # the pieces' counts are arithmetic; the cut side x is at most the sum of each piece's other sides
            base_a, base_b = piece_counts(p, q), piece_counts(q, p)
            other_a, other_b = sum(base_a), sum(base_b)
            irregular = (loop.nodes[p] in _base_corners) + (loop.nodes[q] in _base_corners)
            # no side of a CC-able piece exceeds the rest combined, which bounds x both ways
            xmin = max(1, 2 * max(base_a) - other_a, 2 * max(base_b) - other_b)
            xmin += (xmin + other_a) % 2
            for x in range(xmin, min(other_a, other_b) + 1, 2):
                ok_a, ok_b = _cc_state(tuple(base_a + [x])), _cc_state(tuple(base_b + [x]))
                if not (ok_a[1] or ok_b[1]): continue
                if not (ok_a[1] and ok_b[1]) and max_depth <= 1: continue
                cut = (loop.nodes[p],) + tuple(('cut', _cid, k) for k in range(1, x)) + (loop.nodes[q],)
                a, b = _cut_loop(loop, p, q, cut)
                if ok_a[1] and ok_b[1]:
                    pieces = [(a, solve(list(a.counts()))), (b, solve(list(b.counts())))]
                    plans.append(Plan('cut', pieces, cuts=[cut], score=_cut_score(pieces, irregular)))
                else:
                    good, bad = (a, b) if ok_a[1] else (b, a)
                    partial.append((irregular, good, bad, cut))
    plans.sort(key=lambda p: p.score)
    if len(plans) >= limit or max_depth <= 1: return plans[:limit]

    partial.sort(key=lambda t: (t[0], len(t[2].corners)))
    for irregular, good, bad, cut in partial[:6]:
        for sub in plan_cuts(bad, max_depth=max_depth - 1, limit=2, _cid=_cid + 1 + len(plans),
                             _base_corners=_base_corners):
            pieces = [(good, solve(list(good.counts())))] + sub.pieces
            plans.append(Plan('cut', pieces, cuts=[cut] + sub.cuts,
                              score=_cut_score(pieces, irregular + sub.score[1])))
    plans.sort(key=lambda p: p.score)
    return plans[:limit]


##############################################
# the layout: nodes and faces for a plan

_KEY_RANK = { 'cut': 1, 'spoke': 2, 'pole': 3, 'int': 4 }

def _rank(key):
    return _KEY_RANK.get(key[0], 4) if isinstance(key, tuple) and key and isinstance(key[0], str) else 0


@dataclass
class Layout:
    nodes     : list                # canonical node keys; the loop's own keys for existing verts
    faces     : list                # node index tuples, wound consistently; quads, plus one triangle for a phantom plan
    edges     : list                # unique (a, b) node index pairs, a < b
    regions   : list                # per corner region, grid[u][v] of node indices
    polylines : list                # spokes as node index runs, split vertex first, pole last
    cuts      : list                # cut runs as node index runs, both ends included
    poles     : list                # node index of each piece's pole
    existing  : set                 # node indices that are the loop's own keys
    unused    : set                 # node indices in no face: a dissolved spoke, kept as helpers for placing the rest
    helpers   : list                # (node, a, b): imaginary boundary nodes, placed midway between a and b before anything hangs off them

    def degree(self):
        deg = [0] * len(self.nodes)
        for a, b in self.edges:
            deg[a] += 1
            deg[b] += 1
        return deg


def _dissolve_run(faces, run):
    ''' Dissolve the edges of a node run and the two-valent nodes that leaves, as Blender's dissolve
    edge loop does: the faces on either side of each edge merge, the run's inner nodes drop out of
    them, and a far end left with two faces (a 3-sided loop's pole) drops out too. Returns the new
    faces and the nodes no face uses any more. '''
    faces = [list(f) for f in faces]

    def merge(a, b):
        # f1 walks a -> b, f2 walks b -> a; the merged face walks f1 from b round to a, then f2's inside
        f1 = next((f for f in faces if any(x == a and y == b for x, y in zip(f, f[1:] + f[:1]))), None)
        f2 = next((f for f in faces if any(x == b and y == a for x, y in zip(f, f[1:] + f[:1]))), None)
        if f1 is None or f2 is None: return
        i1, i2 = f1.index(b), f2.index(a)
        f1r, f2r = f1[i1:] + f1[:i1], f2[i2:] + f2[:i2]
        faces.remove(f1)
        faces.remove(f2)
        faces.append(f1r + f2r[1:-1])

    for a, b in zip(run, run[1:]): merge(a, b)
    gone = set(run[:-1])
    if sum(1 for f in faces if run[-1] in f) <= 2: gone.add(run[-1])
    faces = [tuple(x for x in f if x not in gone) for f in faces]
    return [f for f in faces if len(f) >= 3], gone


def build_layout(plan):
    ''' Nodes and faces for a plan. Shared nodes (spokes, poles, cut runs, a pole that lands on the
    boundary) are unified by key so each appears once. '''
    parent = {}

    def find(k):
        while parent.get(k, k) != k:
            parent[k] = parent.get(parent[k], parent[k])
            k = parent[k]
        return k

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb: return
        if (_rank(ra), repr(ra)) <= (_rank(rb), repr(rb)): parent[rb] = ra
        else: parent[ra] = rb

    raw_faces, raw_regions, raw_lines, raw_poles, existing = [], [], [], [], set()
    dissolve_run, raw_helpers = None, []
    for pid, (loop, s) in enumerate(plan.pieces):
        sides = loop.sides()
        n = len(sides)
        for side in sides:
            for key in side:
                if not (isinstance(key, tuple) and key and isinstance(key[0], str)): existing.add(key)
        e = [len(side) - 1 for side in sides]
        pole = ('pole', pid)

        def spoke(j):
            # spoke j: from the split vertex of side j to the pole, s_j edges
            split = sides[j][s[j - 1]]
            return [split] + [('spoke', pid, j, k) for k in range(1, s[j])] + ([pole] if s[j] else [])

        spokes = [spoke(j) for j in range(n)]
        for j in range(n):
            if not s[j]: union(pole, spokes[j][0])       # a zero-length spoke puts the pole on the boundary
        for j in range(n):
            if len(spokes[j]) > 1: raw_lines.append(spokes[j])
        raw_poles.append(pole)

        for j in range(n):
            l0, l1 = s[j - 1] + 1, s[j] + 1
            B, Bp = sides[j], sides[j - 1]

            def keys(u, v):
                out = []
                if v == 0: out.append(B[u])
                if u == 0: out.append(Bp[e[j - 1] - v])
                if u == l0 - 1: out.append(spokes[j][v] if v < len(spokes[j]) else pole)
                if v == l1 - 1: out.append(spokes[j - 1][u] if u < len(spokes[j - 1]) else pole)
                if not out: out.append(('int', pid, j, u, v))
                return out

            grid = []
            for u in range(l0):
                row = []
                for v in range(l1):
                    ks = keys(u, v)
                    for k in ks[1:]: union(ks[0], k)
                    row.append(ks[0])
                grid.append(row)
            raw_regions.append(grid)
            if plan.phantom and plan.phantom[:2] == (pid, j) and plan.phantom[2] in ('full', 'short'):
                # collapse the imaginary vertex's spoke onto the column beside it: the quads between
                # them vanish. Taking the pole row too folds the pole's neighbour into the pole, leaving
                # a triangle in the next region; stopping short leaves the strip's last quad a triangle
                a = l0 - 2
                for v in range(l1 if plan.phantom[2] == 'full' else l1 - 1): union(grid[a][v], grid[a + 1][v])
            if plan.phantom and plan.phantom[:2] == (pid, j) and plan.phantom[2] == 'ngon':
                dissolve_run = spokes[j]
                raw_helpers.append((B[s[j - 1]], B[s[j - 1] - 1], B[s[j - 1] + 1]))   # the imaginary vertex sits between its side neighbours
            for u in range(l0 - 1):
                for v in range(l1 - 1):
                    raw_faces.append((grid[u][v], grid[u + 1][v], grid[u + 1][v + 1], grid[u][v + 1]))

    index, nodes = {}, []
    def idx(k):
        k = find(k)
        if k not in index:
            index[k] = len(nodes)
            nodes.append(k)
        return index[k]

    faces = []
    for f in raw_faces:
        fi = tuple(idx(k) for k in f)
        fi = tuple(a for a, b in zip(fi, fi[1:] + fi[:1]) if a != b)   # a collapsed edge leaves a repeated node
        if len(fi) >= 3 and len(set(fi)) == len(fi): faces.append(fi)
    unused = set()
    if dissolve_run is not None:
        faces, unused = _dissolve_run(faces, [idx(k) for k in dissolve_run])
    edges = sorted({ (min(a, b), max(a, b)) for f in faces for a, b in zip(f, f[1:] + f[:1]) })
    regions = [[[idx(k) for k in row] for row in grid] for grid in raw_regions]

    def run_of(keys):
        # a collapse can fold a run's tail into one node; the run is shortened, never dropped, since the
        # nodes still on it are placed from it
        li = [idx(k) for k in keys]
        li = [a for a, b in zip(li, li[1:] + [None]) if a != b]
        return li if len(li) >= 2 and len(set(li)) == len(li) else None

    polylines = [li for line in raw_lines if (li := run_of(line))]
    cuts = [li for run in plan.cuts if (li := run_of(run))]
    poles = [idx(k) for k in raw_poles]
    helpers = [tuple(idx(k) for k in h) for h in raw_helpers]
    return Layout(nodes, faces, edges, regions, polylines, cuts, poles, { idx(k) for k in existing }, unused, helpers)
