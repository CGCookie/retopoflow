import bpy
import bmesh
import heapq
import math
from mathutils import Matrix, Vector

from ..common.bmesh import get_bmesh_emesh, has_mirror_x, has_mirror_y, has_mirror_z
from ..common.operator import RFRegisterClass
from ...addon_common.common.maths import Plane, Point
from ...addon_common.ext.circle_fit import hyperLSQ
from ..common.maths import proportional_edit


TWIST_SENSITIVITY  = 0.05  # degrees per pixel of horizontal mouse movement
RETAIN_STEP_DEG    = 1.0   # rotation increment (degrees) for iterative retain-shape snapping


def _find_loops(sel_verts):
    '''
    Split selected verts into connected components via selected-edge adjacency.
    Returns a list of vertex lists, one per component.
    Vertices with no selected-edge neighbours form single-element components
    and are filtered out by callers that need at least 3 verts.
    '''
    sel_set = set(sel_verts)
    edges   = {e for v in sel_verts for e in v.link_edges}  # BMEdge hash = C ptr
    adj     = {}
    for e in edges:
        v0, v1 = e.verts
        if v0 not in sel_set or v1 not in sel_set:
            continue
        adj.setdefault(v0, []).append(v1)
        adj.setdefault(v1, []).append(v0)

    visited    = set()
    components = []
    for start in sel_verts:
        if start in visited:
            continue
        visited.add(start)
        component = [start]
        queue = list(adj.get(start, []))
        qi = 0
        while qi < len(queue):
            nb = queue[qi]; qi += 1
            if nb in visited:
                continue
            visited.add(nb)
            component.append(nb)
            queue.extend(adj.get(nb, []))
        components.append(component)
    return components


def _gather_proportional_verts(sel_verts, mw, radius):
    '''
    Dijkstra from sel_verts along edges, collecting all connected vertices
    within world-space distance `radius`.
    Returns {vert: geodesic_distance} — sel_verts are included at distance 0.
    '''
    visited = {}
    queue   = [(0.0, v.index, v) for v in sel_verts]
    while queue:
        d, _, v = heapq.heappop(queue)
        if v in visited:
            continue
        visited[v] = d
        for e in v.link_edges:
            nb    = e.other_vert(v)
            d_new = d + (mw @ v.co - mw @ nb.co).length
            if d_new <= radius and nb not in visited:
                heapq.heappush(queue, (d_new, nb.index, nb))
    return visited


def _trace_loop(v_start, v_second):
    '''Trace the edge loop starting with edge (v_start -> v_second) until it
    returns to v_start.  Returns the ordered cycle [v_start, v_second, ...] or
    None if it never closes (open chain, or _edge_loop_next stops at a sharp pole
    / boundary).'''
    loop = [v_start, v_second]
    seen = {v_start, v_second}
    prev, cur = v_start, v_second
    for _ in range(4096):
        nxt = _edge_loop_next(prev, cur)
        if nxt is None:
            return None
        if nxt == v_start:
            return loop
        if nxt in seen:
            return None
        loop.append(nxt)
        seen.add(nxt)
        prev, cur = cur, nxt
    return None


def _find_core_rings(component_verts):
    '''Detect the selection's cross-section rings by WALKING edge loops — never by
    tracing the selection boundary.

    A face selection's boundary detours around protrusions: with a loop of faces plus
    a few extra faces stuck on top, the outline jumps UP a level where the extra faces
    are, so using it as a ring twists wrongly.  Instead we fit the tube axis and walk
    every cross-section edge loop (the loops running perpendicular to the axis), then
    keep only the ones that close into a complete ring.  In the extra-faces case that
    is three candidates — the band's bottom loop, the band's top loop, and the loop
    along the top of the extra faces — of which only the first two close; the partial
    top loop is dropped and its verts fall through to passengers, riding the rings
    below.

    The walk uses the regular quad continuation where it's unambiguous and, at a pole
    (e.g. where the extra faces meet the band's top loop, which turns that corner into
    a junction), continues along the most axis-PERPENDICULAR forward edge — the
    cross-section direction.  That is what lets the band's top loop survive the corner:
    a strict straight-ahead gate would either divert up the rail or, on a coarse ring
    where the cross-section itself already turns >5° per vert, break the loop entirely.

    Returns (rings, passengers, levels), matching _find_rings_in_component:
      rings      – ordered vertex cycles, one per complete cross-section
      passengers – selection verts not on any complete ring (interpolated, not driven)
      levels     – per-ring metadata index (loft pairing is geometric, not level-based)
    '''
    comp_set = set(component_verts)
    axis, _  = twist_fit_axis(component_verts)
    if axis is None or axis.length < 1e-9:
        return [], list(component_verts), []
    axis = axis.normalized()

    def perp_to_axis(v_from, v_to):
        d = v_to.co - v_from.co
        if d.length < 1e-12:
            return -1.0
        return 1.0 - abs(d.normalized().dot(axis))

    def ring_edge(v):
        # Neighbour across v's most cross-sectional edge (most perpendicular to the
        # axis) — the direction that runs along a cross-section rather than the tube.
        best, best_perp = None, -1.0
        for e in v.link_edges:
            o = e.other_vert(v)
            if o not in comp_set:
                continue
            p = perp_to_axis(v, o)
            if p > best_perp:
                best_perp, best = p, o
        return best

    def step(prev, cur):
        e_in = next((e for e in cur.link_edges if e.other_vert(cur) == prev), None)
        if e_in is None:
            return None
        in_faces = set(e_in.link_faces)
        clean = [e.other_vert(cur) for e in cur.link_edges
                 if e.other_vert(cur) in comp_set and e.other_vert(cur) != prev
                 and not any(f in in_faces for f in e.link_faces)]
        if len(clean) == 1:
            return clean[0]                  # regular quad vert: topological continuation
        # Pole / junction: take the most cross-sectional forward edge (perpendicular to
        # the axis), so the loop follows the cross-section and isn't diverted up a rail.
        d_in = cur.co - prev.co
        if d_in.length < 1e-12:
            return None
        d_in.normalize()
        best, best_perp = None, -1.0
        for e in cur.link_edges:
            o = e.other_vert(cur)
            if o == prev or o not in comp_set:
                continue
            d = o.co - cur.co
            if d.length < 1e-12 or d.normalized().dot(d_in) <= 0.0:
                continue                     # forward continuations only
            p = perp_to_axis(cur, o)
            if p > best_perp:
                best_perp, best = p, o
        return best

    def trace(start, second):
        loop, seen = [start, second], {start, second}
        prev, cur  = start, second
        for _ in range(len(comp_set) + 1):
            nxt = step(prev, cur)
            if nxt is None:
                return None
            if nxt == start:
                return loop
            if nxt in seen:
                return None
            loop.append(nxt); seen.add(nxt)
            prev, cur = cur, nxt
        return None

    rings, levels, assigned = [], [], set()
    for v in component_verts:
        if v in assigned:
            continue
        o = ring_edge(v)
        if o is None:
            continue
        loop = trace(v, o)
        # Keep only complete rings (the trace closed) that don't overlap one already
        # found.  A partial cross-section (e.g. the top of the extra faces) never
        # closes, so it's skipped and its verts drop to passengers below.
        if loop is None or len(loop) < 3 or any(w in assigned for w in loop):
            continue
        rings.append(loop)
        levels.append(len(levels))
        assigned.update(loop)
    passengers = [v for v in component_verts if v not in assigned]
    return rings, passengers, levels


def _find_prop_rings(comp_prop, core_set):
    '''Find cross-section rings in the falloff zone by EDGE-LOOP TRACING.

    For each falloff vert (nearest the core first), the cross-section direction is
    seeded from its toward-core neighbour, then the edge loop through it is traced
    until it closes — a real continuous ring.  The trace follows clean 4-valence
    continuations and passes through a pole ONLY when the next edge is a near-
    straight continuation (< _POLE_STRAIGHT_DEG), so a ring is never bent at a pole
    (a bent ring would twist incorrectly).  Each loop is built once; a traced loop
    may include verts beyond the falloff radius (they ride at weight 0).

    Returns:
        rings       – list of (loop_verts_ordered, avg_world_dist, level)
        unreachable – falloff verts not on any closed loop (passengers, e.g. poles
                      at genuine corners); interpolated via the loft instead.

    Replaces the old hop-distance bucketing, which was not loop detection at all —
    near a pole it split one real cross-section across hop tiers into branchy, non-
    cycle fragments, leaving gaps in the loft.
    '''
    prop_set = set(comp_prop.keys())
    assigned = set()
    rings    = []

    def _add_ring(loop):
        in_r = [w for w in loop if w in comp_prop]
        if not in_r:
            return False
        avg_d = sum(comp_prop[w] for w in in_r) / len(in_r)
        rings.append((loop, avg_d, len(rings)))
        assigned.update(loop)
        return True

    # N-gon faces first (e.g. a cylinder's end cap): the perimeter of an n-gon is a
    # ready-made closed loop, but the edge-loop trace can't follow it — consecutive
    # boundary edges share the n-gon face (so the "no shared face" rule excludes the
    # continuation) and the perimeter curves past the pole-straight threshold.  Take
    # the perimeter (face.verts) directly as a ring so the cap is lofted properly.
    seen_faces = set()
    for v in prop_set:
        for f in v.link_faces:
            if f in seen_faces or len(f.verts) <= 4:
                continue
            seen_faces.add(f)
            loop = list(f.verts)
            if not any(w in assigned for w in loop):
                _add_ring(loop)

    # Nearest-core verts first: their toward-core neighbour is least ambiguous, so
    # each loop is discovered from its most reliable seed.
    for v in sorted(prop_set, key=lambda w: comp_prop[w]):
        if v in assigned:
            continue
        # Toward-core neighbour u: adjacent vert with the smallest distance (core
        # verts count as 0).  Edge (u, v) is the local AXIAL direction.
        u, u_d = None, None
        for e in v.link_edges:
            nb = e.other_vert(v)
            d  = 0.0 if nb in core_set else comp_prop.get(nb)
            if d is None:
                continue
            if u_d is None or d < u_d:
                u_d, u = d, nb
        if u is None:
            continue
        e_uv = next((e for e in v.link_edges if e.other_vert(v) == u), None)
        if e_uv is None:
            continue
        # Ring (cross-section) neighbours of v: neighbours other than u whose edge
        # shares a quad face with the axial edge (u, v) — i.e. perpendicular to the
        # axial direction, running along the cross-section.
        uv_faces = set(e_uv.link_faces)
        ring_nbs = [e.other_vert(v) for e in v.link_edges
                    if e.other_vert(v) != u
                    and any(f in uv_faces and len(f.verts) == 4 for f in e.link_faces)]
        # Trace the cross-section loop; accept the first that closes cleanly.
        loop = None
        for r in ring_nbs:
            loop = _trace_loop(v, r)
            if loop is not None:
                break
        if loop is None:
            continue  # v isn't on a clean closed cross-section → passenger
        if any(w in assigned for w in loop):
            continue  # overlaps an already-built ring (e.g. an n-gon perimeter)
        _add_ring(loop)

    unreachable = [v for v in prop_set if v not in assigned]
    return rings, unreachable


def _edge_loop_next(prev, cur):
    '''Edge-loop continuation through `cur` arriving from `prev`.

    For a REGULAR quad vertex the continuation is the unique edge sharing NO face
    with the incoming edge (prev, cur); the loop just follows the topology, which
    correctly tracks a curving tube even past 5°.

    At a POLE / junction that rule is ambiguous (several such edges) AND unreliable
    (the geometrically-straight continuation often DOES share a face with the
    incoming edge, so it would be wrongly excluded).  There we instead pick the
    straightest edge among ALL of cur's edges, and only continue if it deviates
    less than _POLE_STRAIGHT_DEG from straight ahead — a pole is often where loops
    change direction, and bending a ring there would twist it wrongly.

    Returns None at a boundary or when no pole continuation is straight enough.
    '''
    e_in = None
    for e in cur.link_edges:
        if e.other_vert(cur) == prev:
            e_in = e
            break
    if e_in is None:
        return None
    in_faces = set(e_in.link_faces)
    clean = [e.other_vert(cur) for e in cur.link_edges
             if e.other_vert(cur) != prev
             and not any(f in in_faces for f in e.link_faces)]
    if len(clean) == 1:
        return clean[0]   # regular vert: unique topological continuation
    # Pole / junction / boundary: straightest edge among ALL of cur's edges, gated
    # to a near-straight continuation so the ring is never bent at the pole.
    d_in = cur.co - prev.co
    if d_in.length < 1e-12:
        return None
    d_in = d_in.normalized()
    best, best_dot = None, math.cos(math.radians(_POLE_STRAIGHT_DEG))
    for e in cur.link_edges:
        o = e.other_vert(cur)
        if o == prev:
            continue
        d_out = o.co - cur.co
        if d_out.length < 1e-12:
            continue
        dot = d_in.dot(d_out.normalized())
        if dot > best_dot:
            best_dot, best = dot, o
    return best


def _selected_faces(component_verts):
    '''Return the set of faces whose vertices are all in component_verts.'''
    sel_set    = set(component_verts)
    seen_faces = set()
    result     = set()
    for v in component_verts:
        for f in v.link_faces:
            if f in seen_faces:
                continue
            seen_faces.add(f)
            if all(fv in sel_set for fv in f.verts):
                result.add(f)
    return result


def _find_rings_in_component(component_verts):
    '''Split component_verts into ring vertex-lists.

    For a face band (strip of quads), each "row" of vertices forms its own ring.
    Multi-source BFS from the selection boundary assigns a level to each vertex;
    vertices at the same level that are edge-adjacent form a single ring.

    The selection boundary is treated like a mesh boundary: edges on the border
    of the selected face region (adjacent to exactly one selected face, or to no
    face at all) define the boundary vertices at level 0.

    Returns (ring_groups, bfs_non_ring_verts):
      ring_groups        – list of vertex lists (one per BFS level × sub-loop)
      bfs_non_ring_verts – vertices unreachable by BFS (level == INF); these
                           need IDW interpolation rather than direct rotation
    Falls back to ([component_verts], []) when:
      - no enclosed faces exist (plain edge-loop / vertex-ring selection), or
      - no boundary vertices exist (fully-closed selection like a sphere).
    '''
    sel_set   = set(component_verts)
    sel_faces = _selected_faces(component_verts)

    if not sel_faces:
        # Plain edge-loop selection — no enclosed quads; treat as one loop.
        return [component_verts], [], [0]

    # Boundary vertices: touch at least one face not in sel_faces,
    # or lie on a mesh boundary edge (≤ 1 adjacent face total).
    boundary_verts = set()
    for v in component_verts:
        for f in v.link_faces:
            if f not in sel_faces:
                boundary_verts.add(v)
                break
        if v not in boundary_verts:
            for e in v.link_edges:
                if len(e.link_faces) <= 1:
                    boundary_verts.add(v)
                    break

    if not boundary_verts:
        # Closed selection (sphere, fully-closed tube) — single group.
        return [component_verts], [], [0]

    # Multi-source BFS from all boundary verts, advancing ONE EDGE per step.
    #
    # Edge-based (not face-based) propagation is essential for correctness when
    # n-gon faces are present.  A face-based BFS visits every vert in a face in
    # one step: a large n-gon that spans from boundary loop A all the way to
    # boundary loop B collapses all interior verts to level 1, merging loops
    # that should be at levels 2, 3, 4 … into one giant branching group that
    # breaks _traverse_loop_params.  Edge-based BFS counts true edge-hops so
    # each interior ring stays at its correct topological depth regardless of
    # whether the surrounding faces are quads or n-gons.
    INF   = len(component_verts) + 1
    level = {v: INF for v in component_verts}
    for v in boundary_verts:
        level[v] = 0

    queue = list(boundary_verts)
    qi    = 0
    while qi < len(queue):
        v = queue[qi]; qi += 1
        for e in v.link_edges:
            nb = e.other_vert(v)
            if nb not in sel_set:
                continue
            # Only propagate through edges that belong to the selected face
            # region (at least one adjacent face is in sel_faces).
            if not any(f in sel_faces for f in e.link_faces):
                continue
            new_lv = level[v] + 1
            if new_lv < level[nb]:
                level[nb] = new_lv
                queue.append(nb)

    # Vertices the BFS could not reach (isolated pockets, closed-off topology).
    bfs_non_ring = [v for v in component_verts if level[v] == INF]

    # Group reachable vertices by BFS level.
    by_level = {}
    for v in component_verts:
        lv = level[v]
        if lv == INF:
            continue
        by_level.setdefault(lv, []).append(v)

    # Within each level, split into edge-connected sub-loops.
    rings       = []
    ring_levels = []
    for lv in sorted(by_level.keys()):
        group     = by_level[lv]
        group_set = set(group)

        adj = {}
        for v in group:
            for e in v.link_edges:
                nb = e.other_vert(v)
                if nb not in group_set:
                    continue
                # At the boundary level (lv == 0) restrict to edges that sit on
                # the selection boundary (adjacent to at least one face outside
                # sel_faces).  Without this, unsubdivided column edges (e.g.
                # v1-w1) connect Loop A verts to Loop B verts even though both
                # are level-0 boundary verts, merging the two rings into one
                # branching sub-component that fails _traverse_loop_params.
                # Interior ring levels (lv > 0) always use all same-level edges
                # because their ring edges are entirely inside sel_faces.
                if lv == 0 and not any(f not in sel_faces for f in e.link_faces):
                    continue
                adj.setdefault(v, []).append(nb)

        # Resolve T-junction vertices at the selection boundary (lv == 0).
        #
        # An n-gon corner that lies on the main ring can have 3+ boundary
        # edges: two that continue the ring and one (or more) that branch off
        # into partial / incomplete loops.  Without resolution, the connected-
        # component BFS merges these branches into the main ring, producing a
        # non-simple (branching) component that _traverse_loop_params rejects —
        # so Ring A never forms a valid ring and falls back to a broken ring.
        #
        # Fix: at each T-junction keep only the most-opposite (most-linear)
        # pairs of edges — the ones that actually pass through the vertex as
        # part of a smooth ring — and remove the branch edge(s).  Removed-
        # branch verts form their own small connected component, which
        # _traverse_loop_params rejects as an open chain → they become broken
        # rings that the bary embedding then handles correctly.
        if lv == 0:
            for v in group:
                nbs = adj.get(v, [])
                if len(nbs) <= 2:
                    continue          # normal ring vert or dead end
                # Greedily pair neighbours by most-opposite direction through v.
                remaining = list(nbs)
                paired    = set()
                while len(remaining) >= 2:
                    best_score       = -2.0
                    best_i, best_j   = 0, 1
                    for i in range(len(remaining)):
                        for j in range(i + 1, len(remaining)):
                            a, b = remaining[i], remaining[j]
                            da = a.co - v.co
                            db = b.co - v.co
                            la, lb = da.length, db.length
                            score = (
                                -(da / la).dot(db / lb)
                                if la > 1e-12 and lb > 1e-12
                                else -1.0
                            )
                            if score > best_score:
                                best_score   = score
                                best_i, best_j = i, j
                    paired.add(remaining[best_i])
                    paired.add(remaining[best_j])
                    remaining = [remaining[k] for k in range(len(remaining))
                                 if k not in (best_i, best_j)]
                # Remove branch edges — neighbours not accepted into any pair.
                for nb in list(adj.get(v, [])):
                    if nb not in paired:
                        adj[v]  = [x for x in adj[v]  if x != nb]
                        if nb in adj:
                            adj[nb] = [x for x in adj[nb] if x != v]

        visited = set()
        for start in group:
            if start in visited:
                continue
            visited.add(start)
            ring_verts = [start]
            bq  = list(adj.get(start, []))
            bqi = 0
            while bqi < len(bq):
                nb = bq[bqi]; bqi += 1
                if nb in visited:
                    continue
                visited.add(nb)
                ring_verts.append(nb)
                bq.extend(adj.get(nb, []))
            rings.append(ring_verts)
            ring_levels.append(lv)

    return (rings if rings else [component_verts]), bfs_non_ring, (ring_levels if rings else [0])


def twist_detect_symmetry(context, sel_verts):
    mx = has_mirror_x(context)
    my = has_mirror_y(context)
    mz = has_mirror_z(context)
    sym_verts = set()
    if mx or my or mz:
        threshold = 1e-4
        for v in sel_verts:
            if mx and abs(v.co.x) < threshold: sym_verts.add(v)
            if my and abs(v.co.y) < threshold: sym_verts.add(v)
            if mz and abs(v.co.z) < threshold: sym_verts.add(v)
    return sym_verts, (mx, my, mz)


def twist_fit_axis(sel_verts):
    '''Return (normal, center) from the best-fit plane/circle through sel_verts.
    Falls back to (None, centroid) if fitting fails.'''
    points = [Point(v.co) for v in sel_verts]
    try:
        plane = Plane.fit_to_points(points)
        normal = plane.n.copy()
        try:
            circle = hyperLSQ([list(plane.w2l_point(p).xy) for p in points])
            center = Vector(plane.l2w_point(Point((circle[0], circle[1], 0))))
        except Exception:
            center = sum((v.co for v in sel_verts), Vector()) / len(sel_verts)
    except Exception:
        normal = None
        center = sum((v.co for v in sel_verts), Vector()) / len(sel_verts)
    return normal, center


def _traverse_loop_params(sel_verts, initial_cos, mw):
    '''Traverse the selected loop and return world-space arc-length parameters.

    Returns (order, cumul, total) where:
      order  – vertices in traversal order (closed loop, len == len(sel_verts))
      cumul  – cumul[i] = world-space perimeter distance before order[i]
      total  – total world-space perimeter of the original loop

    Returns None when the selection is not a simple closed loop (e.g. open
    chain, branching, or isolated verts) — callers should fall back to the
    rotate-and-snap path in that case.'''
    sel_set = set(sel_verts)
    edges   = {e for v in sel_verts for e in v.link_edges}   # BMEdge hash = C ptr
    adj     = {}
    for e in edges:
        v0, v1 = e.verts
        if v0 not in sel_set or v1 not in sel_set:
            continue
        adj.setdefault(v0, []).append(v1)
        adj.setdefault(v1, []).append(v0)

    # A simple closed loop: every vertex has exactly 2 selected neighbours
    if any(len(adj.get(v, [])) != 2 for v in sel_verts):
        return None

    start = sel_verts[0]
    order = [start]
    prev, cur = None, start
    for _ in range(len(sel_verts) - 1):
        a, b  = adj[cur]
        # Use == (BMVert.__eq__ compares C pointers) not 'is' (Python object
        # identity).  Different accesses to the same vertex can return different
        # Python wrapper objects, so 'is' would always be False and the walk
        # would zigzag back to the start instead of advancing.
        nxt  = b if (prev is not None and a == prev) else a
        if nxt == start:
            break
        order.append(nxt)
        prev, cur = cur, nxt

    # Guard against duplicate entries caused by a degenerate traversal
    if len(order) != len(sel_verts) or len(set(order)) != len(sel_verts):
        return None

    cumul = []
    dist  = 0.0
    for i, v in enumerate(order):
        cumul.append(dist)
        nxt_v = order[(i + 1) % len(order)]
        dist += (mw @ initial_cos[nxt_v] - mw @ initial_cos[v]).length
    total = dist
    return (order, cumul, total) if total > 1e-12 else None


def _arc_position(frac, order, cumul, total, initial_cos, mw):
    '''World-space point at fractional perimeter position frac (wraps at 1.0).'''
    target = (frac % 1.0) * total
    n      = len(order)
    for i in range(n):
        nxt     = (i + 1) % n
        seg_end = cumul[nxt] if nxt != 0 else total
        if target <= seg_end + 1e-12 or i == n - 1:
            seg_len = seg_end - cumul[i]
            t = max(0.0, min(1.0, (target - cumul[i]) / seg_len)) if seg_len > 1e-12 else 0.0
            a = mw @ initial_cos[order[i]]
            b = mw @ initial_cos[order[nxt]]
            return a + t * (b - a)
    return mw @ initial_cos[order[0]]


def _build_retain_segments(sel_verts, initial_cos, mw):
    '''Fallback for non-loop topologies: world-space (a, b) pairs for all
    selected edges.  Used by the iterative rotate-and-snap path only when
    _traverse_loop_params returns None.

    Deduplication uses a set of BMEdge objects (BMEdge.__hash__ = C pointer)
    to avoid the id()-recycling pitfall.'''
    sel_set  = set(sel_verts)
    edges    = {e for v in sel_verts for e in v.link_edges}
    segments = []
    for e in edges:
        v0, v1 = e.verts
        if v0 not in sel_set or v1 not in sel_set:
            continue
        a = mw @ initial_cos[v0]
        b = mw @ initial_cos[v1]
        if (b - a).length_squared < 1e-12:
            continue
        segments.append((a, b))
    return segments


def _snap_to_nearest_segment(co, segments):
    '''Return the nearest point on any (a, b) segment to co.'''
    best_d = float('inf')
    best   = co
    for a, b in segments:
        ab    = b - a
        ab_sq = ab.dot(ab)
        if ab_sq < 1e-12:
            continue
        t    = max(0.0, min(1.0, (co - a).dot(ab) / ab_sq))
        proj = a + t * ab
        d    = (co - proj).length_squared
        if d < best_d:
            best_d = d
            best   = proj
    return best


_LOFT_NORMAL_THRESHOLD = 0.34   # cos(~70°) — reject rings more-perpendicular than this
_BARY_EPS              = 0.05   # barycentric tolerance for "inside" triangle test
_POLE_STRAIGHT_DEG     = 5.0    # ring tracing only passes through a pole if the
                                # continuation deviates less than this (else the
                                # ring would bend at the pole and twist wrong)
_RING_AXIS_ALIGN       = 0.5    # min |dot(ring normal, rotation axis)| for a loop to
                                # count as a cross-section ring (cos 60°) — rejects
                                # loops facing sideways, e.g. an n-gon on the tube wall


def _ring_centroid(rd, initial_cos):
    '''Average initial position of the ring's vertices.'''
    verts = list(rd['initial_cos'].keys())
    return sum((initial_cos[v] for v in verts), Vector()) / len(verts)


def _order_rings_by_axis(all_rings):
    '''Order + VALIDATE the COMPLETE rings by an outward walk along the rotation axis.

    Lofting must bridge rings that aren't edge-connected — that's the whole point
    of the bary loft — so ordering is geometric, not topological.  The walk starts
    at the core ring (the selection) and expands outward: from each ring it steps to
    the nearest ring AHEAD along that ring's OWN rotation axis whose plane is locally
    aligned with it (|dot(normals)| >= _RING_AXIS_ALIGN).  Checking alignment against
    the PREVIOUS ring rather than a global axis is what makes a sharply curving tube
    work — only the per-step tilt matters, never the accumulated one.  When no ring
    lies ahead it walks the opposite direction from the start.

    Returns the ordered chain of VALID cross-section rings; rings the walk can't
    reach (sideways loops like a wall n-gon, or off-axis junk) are omitted so the
    caller can demote them to passengers.  Terminal rings land at the chain ends, so
    end caps go on the ends — never mid-mesh.
    '''
    rings = [rd for rd in all_rings if rd['loop_params'] is not None]
    if len(rings) < 2:
        return rings

    def centroid(rd):
        cos = rd['initial_cos']
        return sum(cos.values(), Vector()) / len(cos)
    cents = {id(rd): centroid(rd) for rd in rings}

    # Global axis fallback for rings whose own normal failed to fit (normals are
    # already sign-aligned upstream, so summing them is meaningful).
    gaxis = Vector((0.0, 0.0, 0.0))
    for rd in rings:
        if rd['normal'] is not None:
            gaxis += rd['normal']
    gaxis = gaxis.normalized() if gaxis.length > 1e-9 else Vector((0.0, 0.0, 1.0))
    def axis_of(rd):
        n = rd['normal']
        return n.normalized() if (n is not None and n.length > 1e-9) else gaxis

    start = next((rd for rd in rings if not rd.get('is_prop')), rings[0])
    used  = {id(start)}

    def walk(sign):
        chain, cur = [], start
        while True:
            c   = cents[id(cur)]
            ax  = axis_of(cur)
            n   = ax * sign
            best, best_d = None, float('inf')
            for rd in rings:
                if id(rd) in used:
                    continue
                d_vec = cents[id(rd)] - c
                if d_vec.dot(n) <= 1e-9:
                    continue                  # not ahead along this ring's axis
                if abs(axis_of(rd).dot(ax)) < _RING_AXIS_ALIGN:
                    continue                  # not aligned with THIS ring (local tilt)
                d = d_vec.length              # nearest aligned ring ahead, in 3D
                if d < best_d:
                    best_d, best = d, rd
            if best is None:
                break
            chain.append(best)
            used.add(id(best))
            cur = best
        return chain

    fwd = walk(+1)
    bwd = walk(-1)
    return list(reversed(bwd)) + [start] + fwd


def _build_loft_sequence(all_rings, initial_cos):
    '''Pair complete rings consecutively along the spatial (axis) order.

    Consecutive rings in the spatial chain are lofted together even when they are
    NOT edge-connected — bridging gaps is the whole point of the bary loft.  Near-
    perpendicular consecutive rings are bridged across (the previous ring stays the
    anchor) so one misfit ring leaves a cap-filled gap instead of breaking the chain.
    '''
    ordered = _order_rings_by_axis(all_rings)
    if len(ordered) < 2:
        return []

    pairs = []
    prev  = ordered[0]
    for rd in ordered[1:]:
        n_a = prev['normal']
        n_b = rd['normal']
        if n_a is not None and n_b is not None and abs(n_a.dot(n_b)) < _LOFT_NORMAL_THRESHOLD:
            # Near-perpendicular — skip rd as a partner but keep prev as anchor
            # so the loft bridges across it instead of leaving a hole.
            continue
        pairs.append((prev, rd))
        prev = rd

    return pairs


def _loft_rings(rd_a, rd_b, initial_cos):
    '''Zipper loft between two rings using arc-length correspondence.

    Produces exactly n + m triangles (n = len(ring_a), m = len(ring_b)) that
    together tile the cylindrical surface between the two rings.

    Alignment step: rotate ring B so its vertex closest to ring A's first vertex
    comes first, then recompute arc-length fractions from that new origin.

    Zipper step: at each of the n+m iterations, advance whichever ring has its
    next vertex sooner in arc-length (ties: advance A).
    '''
    order_a, cumul_a, total_a = rd_a['loop_params']
    order_b, cumul_b, total_b = rd_b['loop_params']
    n, m = len(order_a), len(order_b)

    # Align B to start at the vertex closest to order_a[0].
    co_a0 = initial_cos[order_a[0]]
    j0    = min(range(m), key=lambda k: (initial_cos[order_b[k]] - co_a0).length_squared)
    order_b = order_b[j0:] + order_b[:j0]
    base    = cumul_b[j0] / total_b
    frac_b  = [((cumul_b[(j0 + k) % m] / total_b) - base) % 1.0 for k in range(m)]
    frac_a  = [cumul_a[i] / total_a for i in range(n)]

    tris = []
    ia = ib = 0
    for _ in range(n + m):
        a0 = order_a[ia % n]
        b0 = order_b[ib % m]
        if ia >= n:
            # A exhausted — consume remaining B edges, closing the seam.
            tris.append((order_a[0], b0, order_b[(ib + 1) % m]))
            ib += 1
        elif ib >= m:
            # B exhausted — consume remaining A edges.
            tris.append((a0, order_a[(ia + 1) % n], order_b[0]))
            ia += 1
        elif (frac_a[(ia + 1) % n] if ia < n - 1 else 1.0) \
          <= (frac_b[(ib + 1) % m] if ib < m - 1 else 1.0):
            tris.append((a0, order_a[(ia + 1) % n], b0))   # advance A
            ia += 1
        else:
            tris.append((a0, b0, order_b[(ib + 1) % m]))   # advance B
            ib += 1
    return tris


def _cap_ring(order):
    '''Fan-triangulate a ring as an end cap (n − 2 triangles).

    Used for terminal rings (those in only one loft pair) so that geometry
    projecting "behind" the ring — e.g. a pole at the centre of an end loop —
    can find a triangle to embed in.
    '''
    return [(order[0], order[i], order[i + 1]) for i in range(1, len(order) - 1)]


def _build_loft_surface(all_rings, initial_cos):
    '''Build the loft surface between complete rings, plus end caps.

    Takes ALL ring groups (complete + broken); the broken ones only inform the
    adjacency chain so the loft can bridge across pole rings.

    Returns (bands, caps), each a list of (v0, v1, v2) BMVert triples:
      bands – triangles BETWEEN two complete rings.  They twist cleanly (a band
              quad just rotates), so verts riding them stay correct.
      caps  – fan triangles closing a terminal ring.  Under retain-shape arc-slide
              a cap SHEARS (its verts slide unequal amounts), so a vert riding it
              gets thrown sideways.  Kept separate so prop verts can avoid them.
    '''
    pairs = _build_loft_sequence(all_rings, initial_cos)
    if not pairs:
        return [], []

    bands      = []
    pair_count = {}
    for rd_a, rd_b in pairs:
        bands.extend(_loft_rings(rd_a, rd_b, initial_cos))
        pair_count[id(rd_a)] = pair_count.get(id(rd_a), 0) + 1
        pair_count[id(rd_b)] = pair_count.get(id(rd_b), 0) + 1

    # Cap terminal complete rings (those appearing in at most one pair) so geometry
    # projecting past the end of the chain still has a triangle to embed in.
    caps = []
    for rd in all_rings:
        if rd['loop_params'] is not None and pair_count.get(id(rd), 0) <= 1:
            caps.extend(_cap_ring(rd['loop_params'][0]))
    return bands, caps


def _bary_embed(co, v0, v1, v2, initial_cos):
    '''Compute barycentric coordinates + normal offset for point co in a triangle.

    Returns (w0, w1, w2, offset) where:
      w0 + w1 + w2 ≈ 1  (barycentric weights for v0, v1, v2)
      offset            signed distance from triangle plane (positive = same side
                        as the triangle normal (B-A)×(C-A))

    Uses the cross-product area method.  Returns (1/3, 1/3, 1/3, 0.0) for
    degenerate (collinear) triangles.
    '''
    A = initial_cos[v0]; B = initial_cos[v1]; C = initial_cos[v2]
    n    = (B - A).cross(C - A)
    n_sq = n.dot(n)
    if n_sq < 1e-20:
        return (1/3, 1/3, 1/3, 0.0)
    n_unit = n / math.sqrt(n_sq)
    offset = (co - A).dot(n_unit)
    proj   = co - offset * n_unit
    w0 = n.dot((C - B).cross(proj - B)) / n_sq
    w1 = n.dot((A - C).cross(proj - C)) / n_sq
    return (w0, w1, 1.0 - w0 - w1, offset)


def _find_bary_embedding(co, tris, initial_cos, inside_only=False):
    '''Find the best triangle in tris to embed local-space point co.

    Two-tier selection:
      Tier 1 — inside: triangles where min(w0,w1,w2) >= -_BARY_EPS.
               Among those, pick the one with the smallest |offset|
               (co is closest to lying on the surface).
      Tier 2 — fallback: if no inside triangle exists, pick the triangle
               whose centroid is nearest to co.

    inside_only – return None instead of the Tier-2 fallback.  Used for prop
        verts: a Tier-2 (outside-all-triangles) hit means the vert is past the
        loft's coverage, where reconstruction is unreliable; the caller routes it
        to the rigid weighted IDW fallback instead.

    Returns (v0, v1, v2, w0, w1, w2, offset) or None.
    '''
    best_in   = None;  best_in_d  = float('inf')
    best_out  = None;  best_out_d = float('inf')
    for tri in tris:
        w0, w1, w2, offset = _bary_embed(co, *tri, initial_cos)
        if min(w0, w1, w2) >= -_BARY_EPS:
            d = abs(offset)
            if d < best_in_d:
                best_in  = (*tri, w0, w1, w2, offset)
                best_in_d = d
        else:
            A = initial_cos[tri[0]]; B = initial_cos[tri[1]]; C = initial_cos[tri[2]]
            d = (co - (A + B + C) / 3).length_squared
            if d < best_out_d:
                best_out  = (*tri, w0, w1, w2, offset)
                best_out_d = d
    if best_in is not None:
        return best_in
    return None if inside_only else best_out


def _bary_reconstruct(v0, v1, v2, w0, w1, w2, offset):
    '''Reconstruct a position from the current (post-twist) positions of three
    ring verts using stored barycentric weights and normal offset.

    Reads v0.co / v1.co / v2.co directly so it picks up whatever twist_apply
    wrote in Pass 1 without needing a separate lookup.
    '''
    A = v0.co; B = v1.co; C = v2.co
    base  = w0 * A + w1 * B + w2 * C
    n     = (B - A).cross(C - A)
    n_len = n.length
    return base + offset * (n / n_len) if n_len > 1e-12 else base


def twist_apply_blend_axis(ring_data_list, non_ring_initial_cos, sym_verts, sym_axes,
                           mw, mwi, delta_degrees, retain_shape=False, vert_weights=None):
    '''Move non-ring vertices to follow the twist of the surrounding complete rings.

    vert_weights – optional {vert: falloff_weight} map (default weight 1.0).  When
        given, a vert's blend-axis rotation angle is set to weight × delta_degrees
        (ABSOLUTE) rather than the blended ring angle.  This is for proportional-edit
        falloff verts past the loft's coverage: their own falloff weight is the
        correct fraction of the full twist, independent of whichever ring is nearest
        (whose own angle is already reduced — scaling by it would double-count).
        Rotating by an angle (not lerping position) keeps it correct at any twist.

    retain_shape=False  (default)
        Pure blend-axis rotation: the rotation axis for each non-ring vert is an
        IDW blend of the surrounding rings' axes (center projected onto each
        ring's axis line, normal blended).  Gives geometrically correct angular
        motion regardless of loop shape.

    retain_shape=True
        "Follow ring neighbours": each non-ring vert is placed at the
        inverse-edge-length-weighted average of the CURRENT (post-arc-slide)
        positions of its directly edge-connected ring verts.  This makes the
        vert inherit the retain-shape behaviour of the surrounding loops — e.g.
        a column midpoint lands at the midpoint of the new column connecting
        the two arc-slid endpoints, keeping it on the original topology.
        Falls back to blend-axis rotation for any vert with no ring neighbours.
    '''
    mx, my, mz = sym_axes

    # Flat lookup: ring_vert → original position (used for retain_shape distances).
    ring_init_lookup = {}
    for rd in ring_data_list:
        ring_init_lookup.update(rd['initial_cos'])

    # ring_vert → ring index (used to detect poles vs. between-ring verts).
    ring_of_vert = {}
    for i, rd in enumerate(ring_data_list):
        for vert in rd['initial_cos']:
            ring_of_vert[vert] = i

    # Pre-compute each ring's world-space axis, vert positions, and effective
    # rotation angle.
    #
    # The effective angle is measured from how the ring verts actually moved
    # (initial_cos → v.co, already updated by Pass 1).  For retain_shape=OFF
    # (pure rotation) effective_deg ≈ delta_degrees — no change.  For
    # retain_shape=ON (arc-length slide) on a non-circular loop the ring verts
    # travel less angular distance than delta_degrees; using effective_deg in
    # the blend-axis rotation keeps non-ring verts consistent with the rings
    # they follow instead of over-rotating relative to them.
    ring_ws = []
    for rd in ring_data_list:
        if rd['normal'] is None:
            continue
        ws_center   = mw @ rd['center']
        ws_normal   = (mw.to_3x3() @ rd['normal']).normalized()
        if ws_normal.length_squared < 1e-12:
            continue
        ws_positions = [mw @ co0 for co0 in rd['initial_cos'].values()]

        # Average angular displacement of ring verts around the ring axis.
        angles = []
        for v_r, co0_r in rd['initial_cos'].items():
            p0 = mw @ co0_r
            p1 = mw @ v_r.co
            r0 = p0 - ws_center;  r0 -= ws_normal * r0.dot(ws_normal)
            r1 = p1 - ws_center;  r1 -= ws_normal * r1.dot(ws_normal)
            r0_len = r0.length;   r1_len = r1.length
            if r0_len < 1e-12 or r1_len < 1e-12:
                continue
            cos_a = max(-1.0, min(1.0, r0.dot(r1) / (r0_len * r1_len)))
            sin_a = r0.cross(r1).dot(ws_normal) / (r0_len * r1_len)
            angles.append(math.degrees(math.atan2(sin_a, cos_a)))
        effective_deg = sum(angles) / len(angles) if angles else delta_degrees

        ring_ws.append((ws_center, ws_normal, ws_positions, effective_deg))

    if not ring_ws:
        return

    for v, co0 in non_ring_initial_cos.items():
        if v in sym_verts:
            continue
        ws = mw @ co0
        vw = vert_weights.get(v, 1.0) if vert_weights else 1.0

        placed = False

        if retain_shape:
            # Find directly edge-connected ring verts and accumulate weighted
            # displacements.  We also track which distinct rings the neighbours
            # belong to.
            #
            # The displacement approach is only correct when neighbours span at
            # least TWO rings (column / triangle verts between rings).  For a
            # pole whose spokes all terminate in the SAME ring, averaging the
            # tangential displacements of ring verts produces a net radial shift
            # for any pole that is not perfectly symmetric — pulling it away from
            # the rotation axis.  Such verts fall through to blend-axis rotation,
            # which correctly keeps them near the axis regardless of spoke symmetry.
            total_w       = 0.0
            ws_displ      = Vector((0.0, 0.0, 0.0))
            neighbor_rings = set()
            for e in v.link_edges:
                nb      = e.other_vert(v)
                nb_orig = ring_init_lookup.get(nb)
                if nb_orig is None:
                    continue   # not a ring vert — skip
                neighbor_rings.add(ring_of_vert[nb])
                d = (mw @ co0 - mw @ nb_orig).length
                w = (1.0 / d) if d > 1e-12 else 1e12
                # Accumulate the DISPLACEMENT of each ring neighbour from its
                # original position, not its absolute position.  This ensures
                # the non-ring vert starts exactly at its original position when
                # delta == 0 (no snap-on-invoke), and moves by the weighted
                # average shift of the surrounding arc-slid ring verts.
                ws_displ += w * ((mw @ nb.co) - (mw @ nb_orig))
                total_w  += w
            if total_w > 1e-12 and len(neighbor_rings) > 1:
                # Follow the neighbour rings' actual displacement directly — that
                # already encodes their falloff, so no extra weight scaling here
                # (a vert genuinely between two complete rings embeds in a band, so
                # prop verts almost never reach this path anyway).
                v.co  = mwi @ (ws + ws_displ / total_w)
                placed = True
            # len(neighbor_rings) == 0: no ring neighbours → blend-axis below.
            # len(neighbor_rings) == 1: pole / inside one ring → blend-axis below.

        if not placed:
            # Blend-axis rotation.  Centre, normal, and effective rotation angle
            # are all blended with the same IDW weights so the vert follows the
            # actual motion of whichever ring(s) it is closest to.
            total_w      = 0.0
            ws_center_bl = Vector((0.0, 0.0, 0.0))
            ws_normal_bl = Vector((0.0, 0.0, 0.0))
            eff_deg_bl   = 0.0

            for ws_center, ws_normal, ws_positions, effective_deg in ring_ws:
                # Weight by nearest ring vert, not ring centroid, so a vertex
                # adjacent to a ring gets that ring's axis almost exactly.
                min_d_sq = min((ws - p).length_squared for p in ws_positions)
                # Project ws onto the ring's infinite axis line to get the nearest
                # point on that axis.  For a straight cylinder every ring's axis
                # line is the same, so axis_pt lands on the shared cylinder axis
                # at the vert's height — the correct rotation centre.  For a bent
                # tube, blending several projected points approximates the local
                # axis near the non-ring vert.
                axis_pt = ws_center + ws_normal * (ws - ws_center).dot(ws_normal)
                if min_d_sq < 1e-12:
                    # Coincident with a ring vert — use that ring's axis exactly.
                    ws_center_bl = axis_pt
                    ws_normal_bl = Vector(ws_normal)
                    eff_deg_bl   = effective_deg
                    total_w      = 1.0
                    break
                w             = 1.0 / min_d_sq
                ws_center_bl += w * axis_pt
                ws_normal_bl += w * ws_normal
                eff_deg_bl   += w * effective_deg
                total_w      += w

            if total_w < 1e-12:
                continue
            ws_center_bl /= total_w
            ws_normal_bl /= total_w
            if vert_weights:
                # Absolute: rotate by the vert's OWN falloff weight × the full
                # twist.  Using the blended ring angle × weight would double-count
                # falloff (the nearest prop ring's angle is ALREADY reduced),
                # under-rotating beyond-coverage prop verts.  Empty/None weights
                # (no proportional editing) keep the original blended-angle path.
                eff_deg_bl = delta_degrees * vw
            else:
                eff_deg_bl /= total_w
            n_len = ws_normal_bl.length
            if n_len < 1e-12:
                continue
            ws_normal_bl /= n_len

            xform = (
                Matrix.Translation(ws_center_bl)
                @ Matrix.Rotation(math.radians(eff_deg_bl), 4, ws_normal_bl)
                @ Matrix.Translation(-ws_center_bl)
            )
            v.co = mwi @ (xform @ ws)

    for v in sym_verts:
        if mx: v.co.x = 0.0
        if my: v.co.y = 0.0
        if mz: v.co.z = 0.0


def twist_apply(bm, em, mw, mwi, initial_cos, sym_verts, sym_axes, normal, center, delta_degrees, snap_fn=None, loop_params=None, retain_segments=None, finalize=True, vert_weights=None):
    '''Rotate verts by delta_degrees around normal through center.
    snap_fn(world_pt) -> snapped world-pt or None; omit for free rotation.

    Retain-shape modes (mutually exclusive, loop_params takes priority):

    loop_params – (order, cumul, total) from _traverse_loop_params.  Each vert
        advances delta/360 of the original world-space perimeter regardless of
        loop shape.  Correct for circles, ovals, and any other closed loop.

    retain_segments – fallback for non-loop topologies.  Rotation is applied in
        RETAIN_STEP_DEG increments, snapping each vert to the nearest original
        segment after each step.

    vert_weights – optional {vert: weight} map for proportional falloff.  Each
        vert advances/rotates by delta_degrees × its weight (default 1.0), so a
        ring may twist by varying amounts around its loop — e.g. a cross-section
        completed past the falloff radius keeps its out-of-radius verts (weight 0)
        fixed while its in-radius verts slide.  Sliding along the loop is per-vert
        retain-shape; weight 0 leaves a vert exactly at its original position.'''
    if not normal:
        return
    mx, my, mz = sym_axes

    if loop_params is not None:
        # Arc-length parameterised slide along the original polygon
        order, cumul, total = loop_params
        frac_advance = delta_degrees / 360.0
        orig_fracs   = {v: cumul[i] / total for i, v in enumerate(order)}
        for v in initial_cos:
            if v in sym_verts:
                continue
            w    = vert_weights.get(v, 1.0) if vert_weights else 1.0
            ws   = _arc_position(orig_fracs[v] + frac_advance * w, order, cumul, total, initial_cos, mw)
            v.co = mwi @ ws
            if snap_fn is not None:
                snapped = snap_fn(mw @ v.co)
                if snapped is not None:
                    v.co = mwi @ snapped

    elif retain_segments and delta_degrees != 0.0:
        # Fallback: iterative rotate-and-snap for non-loop topologies
        n_steps    = max(1, int(math.ceil(abs(delta_degrees) / RETAIN_STEP_DEG)))
        step_xform = (
            Matrix.Translation(center)
            @ Matrix.Rotation(math.radians(delta_degrees / n_steps), 4, normal)
            @ Matrix.Translation(-center)
        )
        cur = {v: co0.copy() for v, co0 in initial_cos.items() if v not in sym_verts}
        for _ in range(n_steps):
            for v in cur:
                ws     = mw @ (step_xform @ cur[v])
                ws     = _snap_to_nearest_segment(ws, retain_segments)
                cur[v] = mwi @ ws
        for v, co in cur.items():
            v.co = co
            if snap_fn is not None:
                snapped = snap_fn(mw @ v.co)
                if snapped is not None:
                    v.co = mwi @ snapped

    else:
        # Pure rotation — retain_shape OFF or no retain data available
        xform = (
            Matrix.Translation(center)
            @ Matrix.Rotation(math.radians(delta_degrees), 4, normal)
            @ Matrix.Translation(-center)
        )
        for v, co0 in initial_cos.items():
            if v in sym_verts:
                continue
            if vert_weights:
                # Per-vert angle for proportional falloff (weight 0 → no move).
                w = vert_weights.get(v, 1.0)
                xform_v = (
                    Matrix.Translation(center)
                    @ Matrix.Rotation(math.radians(delta_degrees * w), 4, normal)
                    @ Matrix.Translation(-center)
                )
                v.co = xform_v @ co0
            else:
                v.co = xform @ co0
            if snap_fn is not None:
                snapped = snap_fn(mw @ v.co)
                if snapped is not None:
                    v.co = mwi @ snapped

    for v in sym_verts:
        if mx: v.co.x = 0.0
        if my: v.co.y = 0.0
        if mz: v.co.z = 0.0
    if finalize:
        bm.normal_update()
        bmesh.update_edit_mesh(em, loop_triangles=False)


class RFOperator_TwistLoop(RFRegisterClass, bpy.types.Operator):
    bl_idname      = 'retopoflow.twist_loop'
    bl_label       = 'Twist Loops (Retopoflow)'
    bl_description = 'Rotate selected loop about its plane normal'
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options     = {'REGISTER', 'UNDO'}

    rf_keymaps = []

    twist_angle: bpy.props.FloatProperty(
        name='Twist',
        description='Twist angle',
        default=0.0,
        subtype='ANGLE',
    )
    retain_shape: bpy.props.BoolProperty(
        name='Retain Shape',
        description='Slide vertices along the original selection edges while twisting',
        default=True,
    )
    use_proportional_edit: bpy.props.BoolProperty(
        name='Proportional Editing',
        description='Extend twist to connected vertices within the falloff radius',
        default=False,
    )
    proportional_distance: bpy.props.FloatProperty(
        name='Proportional Size',
        description='Radius of proportional editing falloff',
        default=1.0,
        min=1e-6,
        subtype='DISTANCE',
        unit='LENGTH',
    )
    proportional_falloff: bpy.props.EnumProperty(
        name='Falloff',
        description='Curve shape used to reduce the twist angle with distance',
        # Full set supported by proportional_edit() in common/maths.py — matches
        # Blender's own proportional-edit falloff options.
        items=[
            ('SMOOTH',         'Smooth',         'Smooth falloff'),
            ('SPHERE',         'Sphere',         'Spherical falloff'),
            ('ROOT',           'Root',           'Root falloff'),
            ('INVERSE_SQUARE', 'Inverse Square', 'Inverse-square falloff'),
            ('SHARP',          'Sharp',          'Sharp falloff'),
            ('LINEAR',         'Linear',         'Linear falloff'),
            ('CONSTANT',       'Constant',       'Constant — no falloff'),
            ('RANDOM',         'Random',         'Random falloff'),
        ],
        default='SMOOTH',
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'twist_angle')
        layout.prop(self, 'retain_shape')
        layout.prop(self, 'use_proportional_edit')
        if self.use_proportional_edit:
            layout.prop(self, 'proportional_distance')
            layout.prop(self, 'proportional_falloff')

    def _build_component_data(self, context, sel_verts, mw, prop_distances=None):
        '''Build per-component twist data.

        Returns a list of component dicts, each containing:
          ring_groups      – ring dicts, one per BFS-level sub-loop; each ring
                             has its OWN per-ring rotation axis so bent/curved
                             shapes are handled correctly.
          bfs_non_ring_cos – {v: co0} for BFS-unreachable verts (poles in
                             closed pockets); these get IDW interpolation.
          bfs_non_ring_sym – sym-vert subset of the above.
          sym_axes         – (mx, my, mz) mirror flags for the component.

        loop_params and retain_segments are ALWAYS pre-computed for every ring
        group (regardless of the current retain_shape state) so that the [S]
        toggle during modal use works without a rebuild.

        For retain_shape=ON: ring groups whose loop_params failed (branching /
        pole-containing rings) are treated as IDW verts at apply time so that
        poles follow their surrounding complete loops exactly.
        '''
        components = []
        for component_verts in _find_loops(sel_verts):
            if len(component_verts) < 3:
                continue
            sym_verts, sym_axes = twist_detect_symmetry(context, component_verts)

            # Walk the cross-section edge loops to find the guide rings.  Fall back to
            # the boundary-BFS detection only when that finds none (e.g. an open patch
            # with no closed cross-section) so those selections still get drivers.
            ring_groups_verts, bfs_non_ring, ring_levels = _find_core_rings(component_verts)
            if not ring_groups_verts:
                ring_groups_verts, bfs_non_ring, ring_levels = _find_rings_in_component(component_verts)

            ring_groups = []
            ref_normal  = None   # first successfully-fitted normal; all others align to it
            for ring_idx, ring_verts in enumerate(ring_groups_verts):
                if len(ring_verts) < 3:
                    bfs_non_ring.extend(ring_verts)
                    continue
                initial_cos    = {v: v.co.copy() for v in ring_verts}
                ring_sym       = {v for v in sym_verts if v in set(ring_verts)}
                # Per-ring axis so each loop rotates about its own normal.
                normal, center = twist_fit_axis(ring_verts)
                # Plane.fit_to_points returns an arbitrary normal sign; flip any
                # ring whose normal points opposite to the first ring so that all
                # rings in the component rotate in the same direction.
                if normal is not None:
                    if ref_normal is None:
                        ref_normal = normal.copy()
                    elif normal.dot(ref_normal) < 0:
                        normal = -normal
                # Pre-compute both paths; retain_shape toggle chooses at apply time.
                lp   = _traverse_loop_params(ring_verts, initial_cos, mw)
                segs = _build_retain_segments(ring_verts, initial_cos, mw) if lp is None else None

                # _traverse_loop_params picks a traversal direction arbitrarily.
                # Ensure it winds in the same sense as the (aligned) normal so
                # the arc-length path (retain_shape=ON) and the pure-rotation
                # path (retain_shape=OFF) always rotate in the same direction.
                # Use `normal` if available, fall back to `ref_normal` for rings
                # where plane-fitting failed.
                check_normal = normal if normal is not None else ref_normal
                if lp is not None and check_normal is not None:
                    order, cumul, total = lp
                    ctr = sum((initial_cos[v] for v in order), Vector()) / len(order)
                    area_vec = Vector((0.0, 0.0, 0.0))
                    for i in range(len(order)):
                        a = initial_cos[order[i]] - ctr
                        b = initial_cos[order[(i + 1) % len(order)]] - ctr
                        area_vec += a.cross(b)
                    if area_vec.dot(check_normal) < 0:
                        # Winding is opposite to normal — reverse traversal order
                        # (keep first vert as anchor, flip the rest) and recompute
                        # world-space cumulative distances for the new order.
                        order = [order[0]] + list(reversed(order[1:]))
                        cumul = [0.0]
                        for i in range(1, len(order)):
                            seg = (mw @ initial_cos[order[i]]) - (mw @ initial_cos[order[i - 1]])
                            cumul.append(cumul[-1] + seg.length)
                        lp = (order, cumul, total)
                ring_groups.append({
                    'initial_cos':     initial_cos,
                    'sym_verts':       ring_sym,
                    'sym_axes':        sym_axes,
                    'normal':          normal,
                    'center':          center,
                    'loop_params':     lp,
                    'retain_segments': segs,
                    'bfs_level':       ring_levels[ring_idx],
                    'weight':          1.0,
                    'is_prop':         False,
                })

            # ---- Proportional ring detection ----
            # Prop verts are gathered per-component via BFS from the core, then
            # grouped into hop-distance tiers.  Each tier's edge-connected sub-
            # groups are treated as rings with their own axis, twisted by
            # angle × falloff(avg_dist).  This keeps valid prop loops rotating
            # around their own axis rather than being IDW-dragged by the core.
            prop_non_ring_weights = {}   # {vert: falloff_weight} for all prop non-ring verts
            prop_sym_verts = set()
            if prop_distances:
                prop_radius  = self.proportional_distance
                prop_falloff = self.proportional_falloff

                # BFS from core component outward through prop_distances verts
                comp_prop    = {}
                component_set = set(component_verts)
                visited_prop  = set(component_set)
                queue = list(component_verts)
                while queue:
                    v = queue.pop()
                    for e in v.link_edges:
                        nb = e.other_vert(v)
                        if nb in visited_prop:
                            continue
                        if nb in prop_distances:
                            comp_prop[nb] = prop_distances[nb]
                            visited_prop.add(nb)
                            queue.append(nb)

                if comp_prop:
                    mx, my, mz = sym_axes
                    if mx or my or mz:
                        threshold = 1e-4
                        for v in comp_prop:
                            if mx and abs(v.co.x) < threshold: prop_sym_verts.add(v)
                            if my and abs(v.co.y) < threshold: prop_sym_verts.add(v)
                            if mz and abs(v.co.z) < threshold: prop_sym_verts.add(v)

                    prop_rings, prop_unreachable = _find_prop_rings(comp_prop, component_set)
                    for v in prop_unreachable:
                        d_v     = comp_prop[v]
                        dist_in = max(1.0 - d_v / prop_radius, 0.0)
                        prop_non_ring_weights[v] = proportional_edit(prop_falloff, dist_in)
                    bfs_non_ring.extend(prop_unreachable)

                    # Each prop_rings entry is a real, complete cross-section loop
                    # (traced via edge loops and deduped in _find_prop_rings), so we
                    # build one ring driver per entry directly — no completion, no
                    # dedup, no pole special-casing.  A pole that the loop passes
                    # straight through is an ordinary member and arc-slides with the
                    # ring like any other vert.
                    for ring_verts, avg_d, hop_lv in prop_rings:
                        if len(ring_verts) < 3:
                            for v in ring_verts:
                                d_v     = comp_prop[v]
                                dist_in = max(1.0 - d_v / prop_radius, 0.0)
                                prop_non_ring_weights[v] = proportional_edit(prop_falloff, dist_in)
                            bfs_non_ring.extend(ring_verts)
                            continue
                        initial_cos = {v: v.co.copy() for v in ring_verts}
                        ring_sym    = {v for v in prop_sym_verts if v in set(ring_verts)}
                        normal, center = twist_fit_axis(ring_verts)
                        if normal is not None:
                            if ref_normal is None:
                                ref_normal = normal.copy()
                            elif normal.dot(ref_normal) < 0:
                                normal = -normal
                        # NOTE: cross-section validity (is this loop's plane aligned
                        # with the rotation axis?) is decided LATER by the outward
                        # axis walk, which checks each ring against its NEIGHBOUR's
                        # axis — see _order_rings_by_axis + the demotion below.  A
                        # global normal check here would wrongly reject the far rings
                        # of a sharply curved tube.
                        lp = _traverse_loop_params(ring_verts, initial_cos, mw)
                        # pole_ring: does the loop pass through a pole (a member with
                        # >2 edges leaving the ring)?  Diagnostic only — such a vert is
                        # a near-straight continuation (the tracer enforces < 5°), so it
                        # arc-slides correctly as a normal member.
                        pole_ring = False
                        if lp is not None:
                            ring_set = set(ring_verts)
                            pole_ring = any(
                                sum(1 for e in v.link_edges
                                    if e.other_vert(v) not in ring_set) > 2
                                for v in ring_verts
                            )
                        segs = _build_retain_segments(ring_verts, initial_cos, mw) if lp is None else None
                        # Winding fix — make the traversal wind consistently with the
                        # reference normal so all rings twist the same direction.
                        check_normal = normal if normal is not None else ref_normal
                        if lp is not None and check_normal is not None:
                            order, cumul, total = lp
                            ctr = sum((initial_cos[v] for v in order), Vector()) / len(order)
                            area_vec = Vector((0.0, 0.0, 0.0))
                            for i in range(len(order)):
                                a = initial_cos[order[i]] - ctr
                                b = initial_cos[order[(i + 1) % len(order)]] - ctr
                                area_vec += a.cross(b)
                            if area_vec.dot(check_normal) < 0:
                                order = [order[0]] + list(reversed(order[1:]))
                                cumul = [0.0]
                                for i in range(1, len(order)):
                                    seg = (mw @ initial_cos[order[i]]) - (mw @ initial_cos[order[i - 1]])
                                    cumul.append(cumul[-1] + seg.length)
                                lp = (order, cumul, total)
                        norm_d  = avg_d / prop_radius if prop_radius > 1e-12 else 0.0
                        dist_in = max(1.0 - norm_d, 0.0)
                        weight  = proportional_edit(prop_falloff, dist_in)
                        # Per-vert falloff weight: each vert twists by its OWN strength.
                        # Traced verts beyond the radius are absent from comp_prop →
                        # weight 0, so the ring is a complete loft cross-section but only
                        # its in-radius arc actually moves.
                        vert_weights = {}
                        for v in ring_verts:
                            d = comp_prop.get(v)
                            if d is None:
                                vert_weights[v] = 0.0
                            else:
                                di = max(1.0 - d / prop_radius, 0.0)
                                vert_weights[v] = proportional_edit(prop_falloff, di)
                        ring_groups.append({
                            'initial_cos':     initial_cos,
                            'sym_verts':       ring_sym,
                            'sym_axes':        sym_axes,
                            'normal':          normal,
                            'center':          center,
                            'loop_params':     lp,
                            'retain_segments': segs,
                            # bfs_level retained as metadata; loft pairing is now
                            # geometric (see _build_loft_sequence), not level-based.
                            'bfs_level':       hop_lv,
                            'weight':          weight,
                            'is_prop':         True,
                            'pole_ring':       pole_ring,
                            'vert_weights':    vert_weights,
                        })
                        if lp is None:
                            # Defensive: a traced loop should always be a clean cycle,
                            # but if loop_params somehow fails, its verts ride the loft.
                            for v in ring_verts:
                                prop_non_ring_weights[v] = vert_weights[v]

            if ring_groups:
                # Validate + order the rings with the outward axis walk (local, per-
                # neighbour alignment — robust on curved tubes).  Prop rings the walk
                # can't reach (sideways loops like a wall n-gon) are NOT cross-sections:
                # demote them to passengers so they ride the loft instead of twisting
                # around a wrong axis.  Core rings are the trusted selection and are
                # never demoted.
                ring_chain = _order_rings_by_axis(ring_groups)
                chain_ids  = {id(rd) for rd in ring_chain}
                kept = []
                for rd in ring_groups:
                    if (rd.get('is_prop') and rd['loop_params'] is not None
                            and id(rd) not in chain_ids):
                        for v, w in rd.get('vert_weights', {}).items():
                            if w > 0.0:            # in-radius vert → passenger
                                prop_non_ring_weights[v] = w
                                bfs_non_ring.append(v)
                    else:
                        kept.append(rd)
                ring_groups = kept

                # Build barycentric loft surface and embed all non-ring verts.
                #
                # active_rings_lp: rings that form complete closed loops (have
                # loop_params) — these are the "drivers" of the loft surface.
                # non_ring_cos: all other selected verts (broken rings + BFS-
                # unreachable) that need to be interpolated.
                active_rings_lp = [rd for rd in ring_groups if rd['loop_params'] is not None]

                all_ring_initial_cos = {}
                for rd in ring_groups:
                    all_ring_initial_cos.update(rd['initial_cos'])

                bary_embeddings   = {}
                bary_fallback_cos = {}

                # Separate non-ring verts by origin so core poles are never
                # embedded in prop-ring triangles (prop ring verts move at reduced
                # weight, which would pull the core pole away from full-twist).
                core_non_ring_cos = {}
                prop_non_ring_cos = {}
                for rd in ring_groups:
                    if rd['loop_params'] is None:
                        target = prop_non_ring_cos if rd.get('is_prop') else core_non_ring_cos
                        target.update(rd['initial_cos'])
                for v in bfs_non_ring:
                    co = v.co.copy()
                    if v in prop_non_ring_weights:
                        prop_non_ring_cos[v] = co
                    else:
                        core_non_ring_cos[v] = co
                # Build the loft ONCE from every complete ring (core + prop): proper
                # bands when >=2 complete rings exist, or a single end-cap when only
                # 1 does so a lone selected loop still drives its falloff verts.
                # bands and caps are kept separate (see _build_loft_surface): bands
                # twist cleanly, caps shear under arc-slide.
                if len(active_rings_lp) >= 2:
                    # Pass ALL ring groups so the adjacency chain can bridge across
                    # broken/pole rings; _build_loft_surface lofts only the complete ones.
                    bands, caps = _build_loft_surface(ring_groups, all_ring_initial_cos)
                elif len(active_rings_lp) == 1:
                    bands, caps = [], _cap_ring(active_rings_lp[0]['loop_params'][0])
                else:
                    bands, caps = [], []
                full_loft = bands + caps

                # Classify each loft triangle by whether it touches a prop ring.
                core_ring_vert_set = set()
                for rd in ring_groups:
                    if not rd.get('is_prop'):
                        core_ring_vert_set.update(rd['initial_cos'].keys())
                # Pure-core triangles (bands + caps): full-strength surface for core poles.
                core_loft = [t for t in full_loft
                             if all(v in core_ring_vert_set for v in t)]
                # Prop-touching BAND triangles only (caps excluded): bands twist
                # cleanly; caps shear under arc-slide, so verts past the last band use
                # the nearest-ring fallback below instead of riding a shearing cap.
                prop_loft = [t for t in bands
                             if any(v not in core_ring_vert_set for v in t)]

                # Core non-ring verts (poles inside the selection) stay at full
                # twist: embed only in pure-core triangles (bands + caps).
                for v, co0 in core_non_ring_cos.items():
                    result = _find_bary_embedding(co0, core_loft, all_ring_initial_cos)
                    if result is not None:
                        bary_embeddings[v] = result
                    else:
                        bary_fallback_cos[v] = co0

                # Driver verts (every chain-ring vert) with rest position + falloff
                # weight, for the "beyond the loft" fallback below.
                driver_data = []
                for rd in active_rings_lp:
                    vw = rd.get('vert_weights')
                    for dv, drest in rd['initial_cos'].items():
                        driver_data.append((dv, drest, vw.get(dv, 1.0) if vw else 1.0))

                # Prop non-ring verts ride prop BAND triangles (inside only).  Bary
                # reconstruction reads the rings' LIVE positions, so the reduced motion
                # comes from the surrounding rings' real rotation and retain-shape is
                # preserved.  A vert PAST the end of the loft (no band contains it —
                # e.g. just outside an n-gon cap) instead copies the nearest ring vert's
                # displacement, dampened by the ratio of its own falloff to that ring
                # vert's, so it tapers off cleanly rather than riding a shearing cap.
                beyond_loft = {}
                for v, co0 in prop_non_ring_cos.items():
                    result = _find_bary_embedding(co0, prop_loft, all_ring_initial_cos,
                                                  inside_only=True)
                    if result is not None:
                        bary_embeddings[v] = result
                        continue
                    best, best_d2 = None, float('inf')
                    for dv, drest, dw in driver_data:
                        d2 = (co0 - drest).length_squared
                        if d2 < best_d2:
                            best_d2, best = d2, (dv, drest, dw)
                    if best is not None and best[2] > 1e-6:
                        dv, drest, dw = best
                        bw   = prop_non_ring_weights.get(v, 0.0)
                        beyond_loft[v] = (dv, drest.copy(), co0.copy(), min(bw / dw, 1.0))
                    else:
                        bary_fallback_cos[v] = co0

                bfs_non_ring_set = set(bfs_non_ring)
                bfs_sym = {v for v in sym_verts       if v in bfs_non_ring_set}
                bfs_sym.update(v for v in prop_sym_verts if v in bfs_non_ring_set)
                components.append({
                    'ring_groups':           ring_groups,
                    'bfs_non_ring_cos':      {v: v.co.copy() for v in bfs_non_ring},
                    'bfs_non_ring_sym':      bfs_sym,
                    'sym_axes':              sym_axes,
                    'bary_embeddings':       bary_embeddings,
                    'bary_fallback_cos':     bary_fallback_cos,
                    # Verts past the end of the loft: {vert: (ring_vert, ring_rest,
                    # vert_rest, damp)} — copy ring_vert's displacement × damp.
                    'beyond_loft':           beyond_loft,
                    # Per-vert falloff weights for prop non-ring verts — used to
                    # classify passengers and to scale the IDW fallback motion.
                    'prop_non_ring_weights': prop_non_ring_weights,
                })
        return components

    def _run_apply(self, bm, em, mw, mwi, component_data):
        '''Apply the current twist_angle to all components.

        Two-pass per component:

        Pass 1 — complete rings (loop_params != None, or retain_shape=OFF):
            Arc-length slide or pure rotation; added to active_rings.

        Pass 2 — broken rings (loop_params == None while retain_shape=ON):
            If active_rings exist  → IDW so poles follow surrounding loops.
            If no active_rings     → retain_segments fallback (isolated
                                     non-loop selection with nothing to IDW from).

        BUG NOTE: the correct IDW trigger is `lp is None`, NOT
        `lp is None and segs is None`.  segs is always a list (never None)
        when lp is None — _build_component_data sets segs only when lp is
        None — so the old `and segs is None` guard made the IDW branch
        permanently unreachable; every broken ring fell through to the
        rotate-and-snap path instead.
        '''
        deg = math.degrees(self.twist_angle)
        for cd in component_data:
            # Pass 1: separate complete rings from geometrically broken ones.
            #
            # "Complete" is determined by rd['loop_params'] is not None — a stored
            # geometric fact set at invoke time by _traverse_loop_params.  Using
            # the runtime `lp` variable (which is None for ALL rings when
            # retain_shape=OFF) would incorrectly route complete rings to IDW and
            # rotate broken rings around their own misfit axis.
            active_rings = []
            broken_rings = []

            for rd in cd['ring_groups']:
                if rd['loop_params'] is None:
                    # Geometrically incomplete ring (pole region, triangle fan,
                    # open chain).  Always goes to IDW regardless of retain_shape
                    # so its verts follow the surrounding complete loops cleanly
                    # instead of rotating around a mis-fitted per-ring axis.
                    broken_rings.append(rd)
                else:
                    # Complete closed loop — arc-length or pure rotation.
                    lp  = rd['loop_params'] if self.retain_shape else None
                    rvw = rd.get('vert_weights')
                    if rvw is not None:
                        # Per-vert falloff: pass the FULL angle and let each vert
                        # scale by its own weight (uniform ring weight folded in).
                        twist_apply(bm, em, mw, mwi,
                                    rd['initial_cos'], rd['sym_verts'], rd['sym_axes'],
                                    rd['normal'], rd['center'], deg,
                                    loop_params=lp, retain_segments=None,
                                    finalize=False, vert_weights=rvw)
                    else:
                        deg_ring = deg * rd.get('weight', 1.0)
                        twist_apply(bm, em, mw, mwi,
                                    rd['initial_cos'], rd['sym_verts'], rd['sym_axes'],
                                    rd['normal'], rd['center'], deg_ring,
                                    loop_params=lp, retain_segments=None,
                                    finalize=False)
                    active_rings.append(rd)

            # Pass 2: broken rings + BFS-unreachable verts.
            if active_rings:
                # Complete rings exist.  Bary path is used for both retain_shape modes:
                # non-ring verts are reconstructed from the deformed loft surface the
                # rings drive.  The rings come from _find_core_rings (cross-section edge
                # loops), so a protrusion's partial loop is already a passenger here, not
                # a skewed driver.
                bary_embeddings     = cd.get('bary_embeddings', {})
                bary_fallback_cos   = cd.get('bary_fallback_cos', {})
                beyond_loft         = cd.get('beyond_loft', {})
                mx, my, mz = cd['sym_axes']
                sym_all = set(cd['bfs_non_ring_sym'])
                for rd in broken_rings:
                    sym_all.update(rd['sym_verts'])

                # Barycentric reconstruction from deformed loft surface.
                for v, (v0, v1, v2, w0, w1, w2, offset) in bary_embeddings.items():
                    if v in sym_all:
                        continue
                    v.co = _bary_reconstruct(v0, v1, v2, w0, w1, w2, offset)

                # Verts past the end of the loft: copy the nearest ring vert's
                # displacement (rest → now), dampened by the stored falloff ratio.
                for bv, (dv, drest, bv_rest, damp) in beyond_loft.items():
                    if bv in sym_all:
                        continue
                    bv.co = bv_rest + (dv.co - drest) * damp

                # IDW fallback for non-ring verts with no loft coverage.  Core
                # poles follow the nearest (full-strength) core rings; prop verts
                # follow the nearest (reduced) prop rings — twist_apply_blend_axis
                # measures each ring's effective angle from how its verts actually
                # moved in Pass 1, so the falloff is already baked into the motion.
                if bary_fallback_cos:
                    fallback_sym = {v for v in sym_all if v in bary_fallback_cos}
                    twist_apply_blend_axis(active_rings, bary_fallback_cos,
                                           fallback_sym, cd['sym_axes'],
                                           mw, mwi, deg,
                                           retain_shape=self.retain_shape,
                                           vert_weights=cd.get('prop_non_ring_weights'))

                # Symmetry clamp for all non-ring sym verts.
                for v in sym_all:
                    if mx: v.co.x = 0.0
                    if my: v.co.y = 0.0
                    if mz: v.co.z = 0.0
            else:
                # No complete rings at all (plain non-loop selection).
                # Fall back to per-ring rotation / retain_segments so verts move.
                for rd in broken_rings:
                    segs     = rd['retain_segments'] if self.retain_shape else None
                    deg_ring = deg * rd.get('weight', 1.0)
                    twist_apply(bm, em, mw, mwi,
                                rd['initial_cos'], rd['sym_verts'], rd['sym_axes'],
                                rd['normal'], rd['center'], deg_ring,
                                loop_params=None, retain_segments=segs,
                                finalize=False)
                # BFS non-ring verts: no reference rings → keep original position.

        bm.normal_update()
        bmesh.update_edit_mesh(em, loop_triangles=False)

    def execute(self, context):
        bm, em = get_bmesh_emesh(context)
        sel_verts = [v for v in bm.verts if v.select]
        if len(sel_verts) < 3:
            return {'CANCELLED'}
        mw  = context.edit_object.matrix_world.copy()
        mwi = mw.inverted()
        prop_distances = None
        if self.use_proportional_edit:
            prop_distances = _gather_proportional_verts(sel_verts, mw, self.proportional_distance)
        component_data = self._build_component_data(context, sel_verts, mw, prop_distances=prop_distances)
        if not component_data:
            return {'CANCELLED'}
        self._run_apply(bm, em, mw, mwi, component_data)
        return {'FINISHED'}

    def invoke(self, context, event):
        bm, em = get_bmesh_emesh(context)
        sel_verts = [v for v in bm.verts if v.select]
        if len(sel_verts) < 3:
            return {'CANCELLED'}
        self._bm  = bm
        self._em  = em
        self._mw  = context.edit_object.matrix_world.copy()
        self._mwi = self._mw.inverted()
        # Seed the redo-panel properties from the scene's current values so the
        # first run matches what the user already has configured.
        ts = context.tool_settings
        self.use_proportional_edit  = ts.use_proportional_edit
        self.proportional_distance  = ts.proportional_distance
        # proportional_edit() in common/maths.py covers every Blender falloff, so
        # take the scene's setting directly (no restricted subset).
        self.proportional_falloff   = ts.proportional_edit_falloff
        prop_distances = None
        if self.use_proportional_edit:
            prop_distances = _gather_proportional_verts(sel_verts, self._mw, self.proportional_distance)
        self._component_data = self._build_component_data(context, sel_verts, self._mw, prop_distances=prop_distances)
        if not self._component_data:
            return {'CANCELLED'}
        self._initial_mouse_x = event.mouse_x
        self.twist_angle = 0.0
        self._highlight_add(context)
        if context.area:
            context.area.header_text_set(self._header_text())
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _header_text(self):
        deg = math.degrees(self.twist_angle)
        rs  = 'ON' if self.retain_shape else 'OFF'
        return f"Twist: {deg:+.1f}°   [S] Retain Shape: {rs}   |   LMB/Enter: Confirm   RMB/Esc: Cancel"

    def _apply(self, context):
        self._run_apply(self._bm, self._em, self._mw, self._mwi, self._component_data)
        if context.area:
            context.area.header_text_set(self._header_text())

    # ---- Highlight the loft's driver rings in the viewport (relax-style) ----
    def _draw_highlights(self, context):
        try:
            from ..common.drawing import Drawing
            from ..preferences import RF_Prefs
            hl    = RF_Prefs.get_prefs(context).highlight_color
            theme = context.preferences.themes[0].view_3d
            edge  = getattr(theme, 'wire_edit', None) or getattr(theme, 'wire', None) \
                    or (0.5, 0.5, 0.5)
            for cd in self._component_data:
                rings = [rd for rd in cd['ring_groups'] if rd['loop_params'] is not None]
                if len(rings) < 2:
                    continue   # one ring / no loft → nothing meaningful to show
                for rd in rings:
                    if rd.get('is_prop'):
                        # Falloff ring: fade from the selection's highlight colour
                        # (strong falloff) toward the theme edge colour (weak), so it
                        # visually fades out toward the edge of the falloff zone.
                        w = max(0.0, min(1.0, rd.get('weight', 1.0)))
                        color = (edge[0] + (hl[0] - edge[0]) * w,
                                 edge[1] + (hl[1] - edge[1]) * w,
                                 edge[2] + (hl[2] - edge[2]) * w)
                    else:
                        color = (hl[0], hl[1], hl[2])   # inside the selection
                    Drawing.draw_loop_highlight(context, set(rd['initial_cos'].keys()),
                                                self._mw, color, skip_verts=frozenset())
        except Exception as e:
            print(f"twist: ring highlight draw failed: {e}")

    def _highlight_add(self, context):
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_highlights, (context,), 'WINDOW', 'POST_PIXEL')
        if context.area:
            context.area.tag_redraw()

    def _highlight_remove(self):
        h = getattr(self, '_draw_handle', None)
        if h is not None:
            bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
            self._draw_handle = None

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            delta_px = event.mouse_x - self._initial_mouse_x
            self.twist_angle = math.radians(delta_px * TWIST_SENSITIVITY)
            self._apply(context)
            return {'RUNNING_MODAL'}
        if event.type == 'S' and event.value == 'PRESS':
            self.retain_shape = not self.retain_shape
            self._apply(context)
            return {'RUNNING_MODAL'}
        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            self._highlight_remove()
            if context.area:
                context.area.header_text_set(None)
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            # Restore ring verts and IDW (non-ring) verts.
            for cd in self._component_data:
                for rd in cd['ring_groups']:
                    for v, co0 in rd['initial_cos'].items():
                        v.co = co0.copy()
                for v, co0 in cd['bfs_non_ring_cos'].items():
                    v.co = co0.copy()
            self._bm.normal_update()
            bmesh.update_edit_mesh(self._em, loop_triangles=False)
            self._highlight_remove()
            if context.area:
                context.area.header_text_set(None)
            return {'CANCELLED'}
        return {'PASS_THROUGH'}
