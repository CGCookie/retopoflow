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

from mathutils import Vector
from bmesh.types import BMesh, BMFace
from bpy.types import Context

from collections.abc import Callable, Sequence

from ..common.bmesh import (
    bme_length,
    bme_midpoint,
    bmf_midpoint,
    bmfs_shared_bme,
    quad_bmf_opposite_bme,
    get_boundary_strips_cycles,
    bme_unshared_bmv,
    bmes_shared_bmv,
)
from ..common.bmesh_maths import get_strip_bmvs
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.utils import iter_pairs


class ChainSpec:
    '''
    Provider-agnostic description of one curve chain -- an ordered run of
    edit-space points the shared curve overlay/edit-operator builds a
    CubicBezierSpline from and deforms verts against, regardless of whether
    those points ARE real verts (an edge loop/strip, `coupled=True`) or are
    DERIVED from other geometry (e.g. a quad-strip centerline, `coupled=False`).
    '''
    __slots__ = (
        'points', 'cyclic', 'cache_key', 'deform_bmv_indices', 'label',
        'min_spline_points', 'coupled', 'avg_len', 'current_points',
        'interior_bmv_indices', 'deform_bmv_rungs',
    )

    def __init__(
        self, *,
        points : list[Vector],
        cyclic : bool,
        cache_key : tuple,
        deform_bmv_indices : list[int],
        label : tuple[str, int],
        min_spline_points : int,
        coupled : bool,
        avg_len : float,
        current_points : Callable[[BMesh], list[Vector] | None],
        interior_bmv_indices : list[int] = (),
        deform_bmv_rungs : dict[int, tuple[Vector, float, bool]] | None = None,
    ):
        self.points = points
        self.cyclic = cyclic
        self.cache_key = cache_key
        self.deform_bmv_indices = deform_bmv_indices
        self.label = label
        self.min_spline_points = min_spline_points
        self.coupled = coupled
        self.avg_len = avg_len
        self.current_points = current_points
        # for a face-derived (coupled=False) chain: maps each deform vert to
        # (midpoint of the perpendicular edge -- "rung" -- it sits on, distance
        # in rungs from the nearest open end, whether that rung is a real mesh
        # boundary edge). The edit operator parametrizes a vert against the
        # curve by its RUNG's position along the centerline (proximity of this
        # midpoint), not the vert's own nearest point -- so every vert of a
        # rung shares one t and a wide strip on a tight bend can't have its
        # verts drift onto the wrong part of the curve. Distance 0 marks the
        # chain's own first/last rung -- a genuine strip-end CAP that the edit
        # operator extrapolates the centerline out to (instead of clamping
        # short) ONLY when is_boundary is true; if the strip is connected
        # there instead (the chain's own end isn't the mesh's), those verts
        # are shared with un-edited faces outside the chain and are left
        # untouched rather than transformed. Empty for a vertex-coupled
        # chain, whose verts ARE the curve points.
        self.deform_bmv_rungs = deform_bmv_rungs or {}
        # verts of selected faces enclosed by this chain (only meaningful
        # for a cyclic, vertex-coupled chain tracing a selected patch's
        # perimeter) that aren't part of the chain itself -- dragging a
        # handle doesn't move these directly, but the edit operator
        # interpolates them from the chain's motion. Empty for chains with
        # no enclosed patch (an open strip, or a loop with nothing selected
        # inside it).
        self.interior_bmv_indices = list(interior_bmv_indices)


class ChainProvider:
    ''' Strategy interface the shared curve overlay calls into to collect
    ChainSpecs from the current selection. '''

    def collect(self, context : Context, bm : BMesh) -> list[ChainSpec] | None:
        ''' None = selection too large / not usable -- bail without adding
        any chains this update (distinct from an empty list). '''
        raise NotImplementedError


def _enclosed_selected_faces(loop_bmes, sel_bmfs : set) -> set:
    ''' Flood-fills from the selected faces touching a closed loop's edges,
    through other selected faces, without crossing the loop itself -- the
    connected component of the selection that this specific loop encloses.
    Two disjoint selected patches produce two separate loops (get_boundary_
    strips_cycles groups by edge connectivity), so seeding per-loop rather
    than flooding the whole selection at once keeps each loop's interior
    correctly scoped to just its own patch. '''
    loop_edge_set = set(loop_bmes)
    seeds = { f for bme in loop_bmes for f in bme.link_faces if f in sel_bmfs }
    visited = set(seeds)
    queue = list(seeds)
    while queue:
        f = queue.pop()
        for e in f.edges:
            if e in loop_edge_set:
                continue  # don't cross the boundary being edited
            for nf in e.link_faces:
                if nf in sel_bmfs and nf not in visited:
                    visited.add(nf)
                    queue.append(nf)
    return visited


class LoopStripChainProvider(ChainProvider):
    '''
    Selected edges on the BOUNDARY OF THE SELECTION (or, if only_boundary is
    False and none of the selected edges qualify, ANY selected edges) ->
    open strips and closed loops of BMVerts. The points ARE the verts
    themselves, so dragging a knot moves that exact vert (coupled=True).

    "Boundary of the selection" is a face-selection test, not mesh topology:
    an edge qualifies unless it's unambiguously swallowed by a larger face
    selection (BOTH its faces selected) -- a genuine mesh boundary/wire edge
    (no "other side" to compare against), a patch's own perimeter (exactly
    one face selected), and a plain edge loop selected with no face
    selection at all (NEITHER face selected -- the ordinary Alt+Click loop
    select, which doesn't mark any face as selected) all still qualify. This
    is deliberately NOT bme.is_boundary -- that would only ever match edges
    on the mesh's own boundary, so selecting a patch of faces entirely
    within the interior of a mesh (its own edges all have 2 real faces)
    would find nothing at all. Testing selection instead means a curve can
    trace the perimeter of any selected patch (interior or not) while still
    working for a plain interior edge loop that isn't part of any face
    selection.
    '''

    def __init__(self, only_boundary : bool):
        self.only_boundary = only_boundary

    def _is_selection_boundary(self, bme, sel_bmfs : set) -> bool:
        linked = bme.link_faces
        if bme.is_wire or len(linked) < 2:
            return True
        return not (linked[0] in sel_bmfs and linked[1] in sel_bmfs)

    def collect(self, context : Context, bm : BMesh) -> list[ChainSpec] | None:
        sel_bmes = list(bmops.get_all_selected_bmedges(bm))
        sel_bmfs = set(bmops.get_all_selected_bmfaces(bm))
        if self.only_boundary or any(self._is_selection_boundary(bme, sel_bmfs) for bme in sel_bmes):
            sel_bmes = [bme for bme in sel_bmes if self._is_selection_boundary(bme, sel_bmfs)]

        if not sel_bmes or len(sel_bmes) >= 1000:
            return None

        strips, cycles = get_boundary_strips_cycles(sel_bmes)
        if len(strips) + len(cycles) > 5:
            return None

        avg_len = sum(bme_length(bme) for bme in sel_bmes) / len(sel_bmes)

        specs = []
        for strip in strips:
            spec = self._make_spec(self._strip_bmvs(strip, cyclic=False), cyclic=False, avg_len=avg_len)
            if spec: specs.append(spec)
        for cycle in cycles:
            spec = self._make_spec(
                self._strip_bmvs(cycle, cyclic=True), cyclic=True, avg_len=avg_len,
                loop_bmes=cycle, sel_bmfs=sel_bmfs,
            )
            if spec: specs.append(spec)
        return specs

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

    def _make_spec(self, bmvs, *, cyclic, avg_len, loop_bmes=None, sel_bmfs=None) -> ChainSpec | None:
        if not bmvs:
            return None
        cos = [bmv.co.copy() for bmv in bmvs]
        bmv_indices = [bmv.index for bmv in bmvs]
        label = ('Loop', len(bmvs)) if cyclic else ('Strip', len(bmvs) - 1)

        interior_bmv_indices = []
        if cyclic and loop_bmes and sel_bmfs:
            enclosed = _enclosed_selected_faces(loop_bmes, sel_bmfs)
            interior_bmv_indices = sorted({v.index for f in enclosed for v in f.verts} - set(bmv_indices))

        def current_points(bm : BMesh, _indices : tuple = tuple(bmv_indices)) -> list[Vector] | None:
            return [bm.verts[i].co.copy() for i in _indices]

        return ChainSpec(
            points=cos,
            cyclic=cyclic,
            cache_key=('verts', *bmv_indices),
            deform_bmv_indices=bmv_indices,
            label=label,
            min_spline_points=5,
            coupled=True,
            avg_len=avg_len,
            current_points=current_points,
            interior_bmv_indices=interior_bmv_indices,
        )


def _interleaved_centerline(faces : list[BMFace], *, cyclic : bool) -> list[Vector]:
    '''
    Walks the faces emitting, alternately, the middle of each face and the
    midpoint of the perpendicular non-boundary edge shared with the next
    face -- treating BOTH as points, the way each vertex of an edge loop is a
    point in Strokes. The shared curve builder's own sharp-angle/RDP
    detection then finds corners from this polyline directly, with no
    separate corner bookkeeping: at a turn, a FACE CENTER lands exactly on
    the apex (its two flanking edge midpoints stay collinear with the two
    straight runs, so they don't register as corners themselves), which is
    why the corner control point ends up mid-face rather than on an edge.

    Consecutive faces are assumed edge-adjacent (true within a single walked
    chain or ring); the between-segment gap of a spatially-joined but
    topologically-disconnected chain is bridged separately, in
    _quad_chain_centerline.
    '''
    n = len(faces)
    n_edges = n if cyclic else n - 1
    pts : list[Vector] = []
    for i in range(n):
        pts.append(bmf_midpoint(faces[i]))
        if i < n_edges and (bme := bmfs_shared_bme(faces[i], faces[(i + 1) % n])):
            pts.append(bme_midpoint(bme))
    return pts


def _quad_chain_centerline(segment_faces : Sequence[list[BMFace]], *, cyclic : bool) -> list[Vector]:
    '''
    Full interleaved centerline for an open chain that may be several
    topologically-separate sub-chains joined only by spatial coincidence at
    their corners (the fallback case -- see find_quadstrip_chains). Each
    sub-chain is interleaved on its own, and consecutive sub-chains are
    bridged by their coincident outer-boundary midpoint (a real point at the
    corner apex, since neither sub-chain's own face center sits there). A
    normal single-sub-chain chain, and every ring, is just one interleaved
    run.
    '''
    if cyclic:
        return _interleaved_centerline(segment_faces[0], cyclic=True)
    pts : list[Vector] = []
    prev_faces = None
    for seg in segment_faces:
        seg_pts = _interleaved_centerline(seg, cyclic=False)
        if prev_faces is not None:
            pts.append(_corner_seam_point(
                _quad_outer_edge_midpoint(prev_faces, at_start=False),
                _quad_outer_edge_midpoint(seg, at_start=True),
                (pts[-1] + seg_pts[0]) / 2,
            ))
        pts += seg_pts
        prev_faces = seg
    return pts


def _quad_chain_rung_map(segment_faces : Sequence[list[BMFace]], *, cyclic : bool) -> dict[int, tuple[Vector, float, bool]]:
    '''
    Maps every vert of a quad chain to (its rung's midpoint, its distance in
    rungs from the nearest open end, whether that rung is a real mesh
    boundary edge). A "rung" is a perpendicular edge crossing the strip: the
    boundary cap at each open end, and the edge shared by each consecutive
    face pair in between. In a clean ladder every vert is an endpoint of
    exactly one rung, so this assigns each a single along-curve anchor -- the
    rung midpoint, which (for interior rungs) is itself a point on the
    centerline. Each topological sub-chain is handled on its own; a
    spatially-joined seam reads as an open end on both sides (conservative --
    it just leaves that corner's correction gentler).

    is_boundary (`len(bme.link_faces) == 1`) only matters for the chain's own
    first/last rung (end_dist==0): curve_edit.py only TRANSFORMS that rung's
    verts when it's true. If the strip is connected there instead (the
    SELECTION ends, not the mesh), those verts are shared with un-edited
    faces outside the chain -- moving them would drag that adjacent geometry
    along, so curve_edit.py leaves them untouched.
    '''
    rung_map : dict[int, tuple[Vector, float, bool]] = {}
    for seg in segment_faces:
        n = len(seg)
        if n < 2:
            continue  # a lone face has no in-chain neighbor to define a rung by
        rungs : list = []
        if cyclic:
            for i in range(n):
                if bme := bmfs_shared_bme(seg[i], seg[(i + 1) % n]):
                    rungs.append(bme)
        else:
            if (shared_first := bmfs_shared_bme(seg[0], seg[1])) and (cap0 := quad_bmf_opposite_bme(seg[0], shared_first)):
                rungs.append(cap0)
            for i in range(n - 1):
                if bme := bmfs_shared_bme(seg[i], seg[i + 1]):
                    rungs.append(bme)
            if (shared_last := bmfs_shared_bme(seg[-2], seg[-1])) and (capN := quad_bmf_opposite_bme(seg[-1], shared_last)):
                rungs.append(capN)
        nr = len(rungs)
        for ri, bme in enumerate(rungs):
            mid = bme_midpoint(bme)
            # cyclic ring has no ends, so nothing to protect -- use a large
            # distance so end-of-chain handling never kicks in
            end_dist = float(nr) if cyclic else float(min(ri, nr - 1 - ri))
            is_boundary = len(bme.link_faces) <= 1
            for v in bme.verts:
                # a vert on two rungs shouldn't happen in a clean ladder, but if
                # it does, keep the nearer-to-an-end anchor so the taper stays
                # conservative
                prev = rung_map.get(v.index)
                if prev is None or end_dist < prev[1]:
                    rung_map[v.index] = (mid, end_dist, is_boundary)
    return rung_map


def _quad_outer_edge_midpoint(faces : list[BMFace], *, at_start : bool) -> Vector | None:
    '''
    The TRUE location of a strip's end -- the boundary edge a corner-adjacent
    strip would touch -- as opposed to bmf_midpoint(end face), which sits at
    that face's own centroid, offset inward from the boundary by roughly
    half a quad length. Two strips meeting at a corner have wildly
    different-looking end-face centroids (each pulled toward its own
    interior) even though their actual boundary edges are coincident --
    comparing centroids for corner detection would compare the wrong points
    entirely.
    '''
    if len(faces) < 2:
        return None
    end_face, near_face = (faces[0], faces[1]) if at_start else (faces[-1], faces[-2])
    near_edge = bmfs_shared_bme(end_face, near_face)
    if not near_edge:
        return None
    far_edge = quad_bmf_opposite_bme(end_face, near_edge)
    return bme_midpoint(far_edge) if far_edge else None


#: how close two OPEN quad chains' endpoints must be, relative to their own
#: quad spacing, to treat them as meeting at a corner and continue the same
#: chain through it. A fixed absolute epsilon isn't right here: PolyStrips
#: builds each corner by repeated snapping/warping of the original stroke
#: (see polystrips_logic.py), and later corners along a multi-bend stroke
#: accumulate more floating-point drift than the first -- an absolute
#: threshold tight enough not to falsely connect unrelated geometry on a
#: large mesh ends up too tight for a strip's OWN later corners. Scaling by
#: the chain's own point spacing self-calibrates to both mesh scale and how
#: precise this particular corner's snap actually was.
CORNER_MERGE_FRACTION = 0.1
#: absolute floor under CORNER_MERGE_FRACTION, for the degenerate case of a
#: chain with ~zero point spacing (shouldn't normally happen, but a fraction
#: of zero would otherwise never accept ANY coincidence, however exact)
CORNER_MERGE_MIN_EPSILON = 1e-5


def _chain_point_scale(points : list[Vector]) -> float:
    ''' A chain's own typical point spacing -- the basis for a coincidence
    threshold that scales with both mesh size and quad density instead of
    being one fixed number for every mesh. '''
    if len(points) < 2:
        return 0.0
    return sum((a - b).length for a, b in iter_pairs(points, False)) / (len(points) - 1)


def _corner_seam_point(end_mid : Vector | None, start_mid : Vector | None, fallback : Vector) -> Vector:
    ''' The two sides of a corner have their OWN separate boundary edges (see
    _quad_outer_edge_midpoint) that merely coincide, not one shared edge --
    averaging both sides' independently-computed midpoints splits any tiny
    residual float/snap discrepancy evenly instead of privileging whichever
    side happened to be checked first. '''
    candidates = [p for p in (end_mid, start_mid) if p is not None]
    if not candidates:
        return fallback
    return sum(candidates, Vector((0, 0, 0))) / len(candidates)


def _bmfs_share_bmv(bmf0 : BMFace, bmf1 : BMFace) -> bool:
    return not set(bmf0.verts).isdisjoint(bmf1.verts)


def _flatten(segment_faces : Sequence[list[BMFace]]) -> list[BMFace]:
    return [f for seg in segment_faces for f in seg]


def _reversed_quad_chain(chain : dict) -> dict:
    seg_faces = [list(reversed(seg)) for seg in reversed(chain['segment_faces'])]
    return {
        'segment_faces': seg_faces,
        'points': _quad_chain_centerline(seg_faces, cyclic=False),
        'start_edge_mid': chain['end_edge_mid'],
        'end_edge_mid': chain['start_edge_mid'],
    }


def _join_quad_chains(a : dict, b : dict) -> dict:
    ''' a's end is already coincident with b's start (the caller reorients as
    needed) -- keep the two as separate sub-chains so the whole chain's
    interleaved centerline (rebuilt here, and again on every edit) bridges
    the seam with the true boundary-edge apex point. '''
    seg_faces = a['segment_faces'] + b['segment_faces']
    return {
        'segment_faces': seg_faces,
        'points': _quad_chain_centerline(seg_faces, cyclic=False),
        'start_edge_mid': a['start_edge_mid'],
        'end_edge_mid': b['end_edge_mid'],
    }


def _try_join_quad_chains(a : dict, b : dict) -> dict | None:
    eps = max(
        CORNER_MERGE_FRACTION * min(_chain_point_scale(a['points']), _chain_point_scale(b['points'])),
        CORNER_MERGE_MIN_EPSILON,
    )
    ea, sa = a['end_edge_mid'], a['start_edge_mid']
    eb, sb = b['end_edge_mid'], b['start_edge_mid']
    if ea is not None and sb is not None and (ea - sb).length <= eps:
        return _join_quad_chains(a, b)
    if ea is not None and eb is not None and (ea - eb).length <= eps:
        return _join_quad_chains(a, _reversed_quad_chain(b))
    if sa is not None and eb is not None and (sa - eb).length <= eps:
        return _join_quad_chains(b, a)
    if sa is not None and sb is not None and (sa - sb).length <= eps:
        return _join_quad_chains(_reversed_quad_chain(b), a)
    return None


def find_quadstrip_chains(bmfs : Sequence[BMFace]) -> tuple[list[dict], list[list[BMFace]]]:
    '''
    Discovers complete chains from selected quad faces in one pass: open
    chains (dicts of one or more edge-adjacent sub-chains of faces, joined
    where corners coincide) and closed rings (a list of faces where every
    face has exactly two in-selection neighbors and the walk loops back to
    where it started -- e.g. a full loop around a cylinder). A lone selected
    quad with zero in-selection neighbors produces neither: there's no
    direction to walk.

    No corners are marked here: the interleaved face-center/edge-midpoint
    centerline (see _interleaved_centerline) places a point at every corner
    apex, and the shared curve builder's own sharp-angle detection finds them
    from that geometry -- exactly as it does for a Strokes edge loop.

    PolyStrips splits a single freehand stroke into separate quad strips
    wherever it bends sharper than split_angle. Each new strip snaps its
    first verts onto the previous strip's end face (see polystrips_logic.py
    trim_stroke_to_bmf + the snap0 vert reuse), so consecutive strips
    usually ARE topologically connected at the corner -- but attached
    sideways, in an L, rather than continuing straight. A straight-only
    walk stops there, and worse: a multi-corner chain's INTERIOR segments
    have no free (single-neighbor) end at all, so a walk seeded only from
    free ends would never even visit them. The walk here prefers straight
    but turns through such corners, producing one continuous face sequence.

    Corners whose geometry is NOT topologically attached (e.g. the snap
    failed and the strip built its own coincident-but-separate verts) are
    caught by a second pass: chains whose outer boundary edges spatially
    coincide are joined into one (kept as separate sub-chains so the seam is
    bridged by its true boundary apex point).
    '''
    bmfs_set : set[BMFace] = set(bmfs)
    network : dict[BMFace, set[BMFace]] = {
        bmf: {
            bme.link_faces[0] if bme.link_faces[1] == bmf else bme.link_faces[1]
            for bme in bmf.edges
            if len(bme.link_faces) == 2 and all(bmef in bmfs for bmef in bme.link_faces)
        }
        for bmf in bmfs_set
    }

    def walk_chain(start : BMFace) -> list[BMFace]:
        # "straight" candidates exclude any face sharing a vert with `pre`
        # (not just `pre` itself): a straight run's next face never touches
        # the face before last, so this both keeps the walk from doubling
        # back and disambiguates a branch/T-junction. When no straight
        # candidate exists but an unvisited neighbor does, that neighbor is
        # an L-attached corner face -- turn into it and keep walking (the
        # interleaved centerline then puts the corner apex on that face's
        # own center). `visited` guards against cycling forever if the turns
        # ever close a loop.
        pre, cur = None, start
        chain = [cur]
        visited = {cur}
        while True:
            unvisited = [bmf_next for bmf_next in network[cur] if bmf_next not in visited]
            straight = [bmf_next for bmf_next in unvisited if not pre or not _bmfs_share_bmv(bmf_next, pre)]
            if straight:
                nxt = straight[0]
            elif pre and unvisited:
                nxt = unvisited[0]  # corner turn
            else:
                return chain
            pre, cur = cur, nxt
            chain.append(cur)
            visited.add(cur)

    def walk_ring(start : BMFace) -> tuple[list[BMFace], bool]:
        # a ring is a uniform degree-2 cycle -- no branch to disambiguate --
        # so `pre` is excluded by identity instead of by vertex-sharing.
        # The vertex-sharing test walk_chain relies on actively breaks a
        # SMALL ring: with few enough faces, a face two steps away can still
        # share a vertex with `pre` even though it's the legitimate forward
        # neighbor, not a doubled-back one. Second return value: True if the
        # walk looped back to `start` (a genuine closed ring), False if it
        # hit a branch point (degree != 2) or a dead end first -- not a ring.
        pre, cur = None, start
        chain = [cur]
        while True:
            if len(network[cur]) != 2:
                return chain, False
            bmfs_next = [bmf_next for bmf_next in network[cur] if bmf_next is not pre]
            if not bmfs_next:
                return chain, False
            pre, cur = cur, bmfs_next[0]
            if cur == start:
                return chain, True
            chain.append(cur)

    chains : list[list[BMFace]] = []
    touched : set[BMFace] = set()
    working = { bmf for bmf in bmfs_set if len(network[bmf]) == 1 }
    while working:
        cur = working.pop()
        if cur in touched:
            continue
        chain = walk_chain(cur)
        touched |= set(chain)
        chains.append(chain)

    rings : list[list[BMFace]] = []
    remaining = bmfs_set - touched
    while remaining:
        start = remaining.pop()
        if len(network[start]) != 2:
            continue  # not part of a uniform 2-neighbor cycle
        ring, closed = walk_ring(start)
        remaining -= set(ring)
        if closed and len(ring) >= 3:
            rings.append(ring)

    open_chains = [
        {
            'segment_faces': [chain],
            'points': _quad_chain_centerline([chain], cyclic=False),
            'start_edge_mid': _quad_outer_edge_midpoint(chain, at_start=True),
            'end_edge_mid': _quad_outer_edge_midpoint(chain, at_start=False),
        }
        for chain in chains
    ]

    # walked chains end only at genuine dead ends now, so this join pass is
    # purely the fallback for corners whose geometry is NOT topologically
    # attached: extend any chain whose outer boundary spatially coincides
    # with another's, repeating until no pair does
    joined_something = True
    while joined_something:
        joined_something = False
        for i in range(len(open_chains)):
            for j in range(len(open_chains)):
                if i == j:
                    continue
                combined = _try_join_quad_chains(open_chains[i], open_chains[j])
                if combined is None:
                    continue
                open_chains = [c for k, c in enumerate(open_chains) if k not in (i, j)] + [combined]
                joined_something = True
                break
            if joined_something:
                break

    return open_chains, rings


class QuadStripChainProvider(ChainProvider):
    '''
    Selected quad faces -> open quad chains and closed quad rings (see
    find_quadstrip_chains), each represented by its centerline. The points
    are DERIVED from faces, not real verts, so dragging a knot doesn't pin
    any one vert to it -- deform_bmv_indices covers every vert of every face
    in the chain instead (coupled=False).
    '''

    # unlike LoopStripChainProvider, PolyStrips has never capped the number
    # of chains an overlay will draw at once -- only the total face count,
    # matching its pre-refactor behavior
    MAX_FACES = 1000

    def collect(self, context : Context, bm : BMesh) -> list[ChainSpec] | None:
        sel_bmfs = [bmf for bmf in bmops.get_all_selected_bmfaces(bm) if len(bmf.edges) == 4]
        if not sel_bmfs or len(sel_bmfs) > self.MAX_FACES:
            return None

        open_chains, rings = find_quadstrip_chains(sel_bmfs)

        specs = []
        for open_chain in open_chains:
            spec = self._make_open_spec(open_chain)
            if spec: specs.append(spec)
        for ring in rings:
            spec = self._make_ring_spec(ring)
            if spec: specs.append(spec)
        return specs

    def _make_open_spec(self, open_chain : dict) -> ChainSpec | None:
        points = open_chain['points']
        if len(points) < 2:
            return None
        # per topological sub-chain, as face indices (multiple only for the
        # spatially-joined-but-disconnected fallback -- usually one)
        segments = [[f.index for f in seg] for seg in open_chain['segment_faces']]
        bmf_indices = [i for seg in segments for i in seg]
        n = sum(len(seg) for seg in open_chain['segment_faces'])
        avg_len = max(sum((a - b).length for a, b in iter_pairs(points, False)) / max(len(points) - 1, 1), 1e-6)
        deform_bmv_indices = sorted({bmv.index for f in _flatten(open_chain['segment_faces']) for bmv in f.verts})
        rung_map = _quad_chain_rung_map(open_chain['segment_faces'], cyclic=False)
        label = ('Strip', n)

        def current_points(bm : BMesh, _segments : tuple = tuple(map(tuple, segments))) -> list[Vector] | None:
            try:
                seg_faces = [[bm.faces[i] for i in seg] for seg in _segments]
            except IndexError:
                return None
            return _quad_chain_centerline(seg_faces, cyclic=False)

        return ChainSpec(
            points=points,
            cyclic=False,
            cache_key=('faces', *bmf_indices),
            deform_bmv_indices=deform_bmv_indices,
            label=label,
            min_spline_points=2,
            coupled=False,
            avg_len=avg_len,
            current_points=current_points,
            deform_bmv_rungs=rung_map,
        )

    def _make_ring_spec(self, faces : list[BMFace]) -> ChainSpec | None:
        points = _quad_chain_centerline([faces], cyclic=True)
        if len(points) < 2:
            return None
        avg_len = max(sum((a - b).length for a, b in iter_pairs(points, True)) / max(len(points), 1), 1e-6)
        bmf_indices = [bmf.index for bmf in faces]
        deform_bmv_indices = sorted({bmv.index for bmf in faces for bmv in bmf.verts})
        rung_map = _quad_chain_rung_map([faces], cyclic=True)
        label = ('Loop', len(faces))

        def current_points(bm : BMesh, _indices : tuple = tuple(bmf_indices)) -> list[Vector] | None:
            try:
                faces = [bm.faces[i] for i in _indices]
            except IndexError:
                return None
            return _quad_chain_centerline([faces], cyclic=True)

        return ChainSpec(
            points=points,
            cyclic=True,
            cache_key=('faces', *bmf_indices),
            deform_bmv_indices=deform_bmv_indices,
            label=label,
            min_spline_points=2,
            coupled=False,
            avg_len=avg_len,
            current_points=current_points,
            deform_bmv_rungs=rung_map,
        )
