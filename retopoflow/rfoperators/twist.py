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


def _find_prop_rings(comp_prop, core_set):
    '''
    Group proportional-edit verts into ring tiers by edge-hop distance from
    the core selection, then split each tier into edge-connected sub-rings.

    Returns:
        rings       – list of (ring_verts, avg_world_dist, hop_level)
        unreachable – verts not reached by the hop BFS (edge case; normally empty)

    Hop-distance avoids the `sel_faces` dependency of _find_rings_in_component,
    which breaks when only one prop tier exists (no faces are entirely inside
    the prop region).
    '''
    prop_set = set(comp_prop.keys())

    # BFS hop count from prop verts that are directly adjacent to core
    hop   = {}
    queue = []
    for v in prop_set:
        if any(e.other_vert(v) in core_set for e in v.link_edges):
            hop[v] = 1
            queue.append(v)
    qi = 0
    while qi < len(queue):
        v = queue[qi]; qi += 1
        for e in v.link_edges:
            nb = e.other_vert(v)
            if nb not in prop_set or nb in hop:
                continue
            hop[nb] = hop[v] + 1
            queue.append(nb)

    # Group by hop level
    by_hop = {}
    for v, h in hop.items():
        by_hop.setdefault(h, []).append(v)

    # Within each hop level, split into edge-connected sub-groups
    rings = []
    for h in sorted(by_hop.keys()):
        group     = by_hop[h]
        group_set = set(group)
        visited   = set()
        for start in group:
            if start in visited:
                continue
            ring_verts = []
            q = [start]
            while q:
                v = q.pop()
                if v in visited:
                    continue
                visited.add(v)
                ring_verts.append(v)
                for e in v.link_edges:
                    nb = e.other_vert(v)
                    if nb in group_set and nb not in visited:
                        q.append(nb)
            avg_d = sum(comp_prop[v] for v in ring_verts) / len(ring_verts)
            rings.append((ring_verts, avg_d, h))

    unreachable = [v for v in prop_set if v not in hop]
    return rings, unreachable


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


def _ring_centroid(rd, initial_cos):
    '''Average initial position of the ring's vertices.'''
    verts = list(rd['initial_cos'].keys())
    return sum((initial_cos[v] for v in verts), Vector()) / len(verts)


def _build_loft_sequence(active_rings, initial_cos):
    '''Determine which pairs of active rings to loft together.

    Groups rings by BFS level, then for each level finds the nearest ring at the
    next available level (skipping levels with no active rings) and applies a
    normal-alignment quality check.  Returns a list of (rd_a, rd_b) pairs.

    Handles:
    - Gaps: BFS levels with only broken/incomplete rings are skipped; the loft
      still bridges across them.
    - Perpendicular rings: pairs whose normals are nearly perpendicular
      (abs dot product < _LOFT_NORMAL_THRESHOLD) are rejected.
    - Multiple rings at the same level: each finds its own nearest match at the
      next level independently.
    - Inverted BFS (e.g. cylinder with 5 rings at levels 0,1,2,1,0): produces
      pairs that together tile the full surface.
    '''
    by_level = {}
    for rd in active_rings:
        by_level.setdefault(rd['bfs_level'], []).append(rd)

    sorted_levels = sorted(by_level.keys())
    pairs = []
    seen  = set()

    for idx, lv in enumerate(sorted_levels):
        # Find the next level that actually has active rings.
        rings_next = []
        for nl in sorted_levels[idx + 1:]:
            if by_level[nl]:
                rings_next = by_level[nl]
                break
        # When there is no higher level to pair with, fall back to pairing rings
        # within the same BFS level.  This handles the common case where both
        # boundary loops (Ring A and Ring B) are at level 0 with no complete
        # intermediate rings between them — without this, no loft is built and
        # all non-ring verts fall through to the IDW fallback.
        if not rings_next:
            rings_next = by_level[lv]

        for rd_a in by_level[lv]:
            ctr_a = _ring_centroid(rd_a, initial_cos)
            n_a   = rd_a['normal']
            # Sort candidates by centroid distance, nearest first.
            candidates = sorted(
                rings_next,
                key=lambda r: (_ring_centroid(r, initial_cos) - ctr_a).length_squared,
            )
            for rd_b in candidates:
                if rd_b is rd_a:          # no self-pairing in same-level fallback
                    continue
                n_b = rd_b['normal']
                # Quality check: skip near-perpendicular rings.
                if n_a is not None and n_b is not None:
                    if abs(n_a.dot(n_b)) < _LOFT_NORMAL_THRESHOLD:
                        continue
                key = (id(rd_a), id(rd_b))
                rev = (id(rd_b), id(rd_a))
                if key not in seen and rev not in seen:
                    pairs.append((rd_a, rd_b))
                    seen.add(key)
                break   # take the first accepted candidate

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


def _build_loft_surface(active_rings, initial_cos):
    '''Build the full set of loft + cap triangles for a component.

    Returns a flat list of (v0, v1, v2) BMVert triples whose positions in
    initial_cos define the surface used for barycentric embedding.
    '''
    if len(active_rings) < 2:
        return []
    pairs = _build_loft_sequence(active_rings, initial_cos)
    if not pairs:
        return []

    tris       = []
    pair_count = {}
    for rd_a, rd_b in pairs:
        tris.extend(_loft_rings(rd_a, rd_b, initial_cos))
        pair_count[id(rd_a)] = pair_count.get(id(rd_a), 0) + 1
        pair_count[id(rd_b)] = pair_count.get(id(rd_b), 0) + 1

    # Add end caps for terminal rings (appear in at most one pair).
    for rd in active_rings:
        if pair_count.get(id(rd), 0) <= 1:
            tris.extend(_cap_ring(rd['loop_params'][0]))
    return tris


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


def _find_bary_embedding(co, tris, initial_cos):
    '''Find the best triangle in tris to embed local-space point co.

    Two-tier selection:
      Tier 1 — inside: triangles where min(w0,w1,w2) >= -_BARY_EPS.
               Among those, pick the one with the smallest |offset|
               (co is closest to lying on the surface).
      Tier 2 — fallback: if no inside triangle exists, pick the triangle
               whose centroid is nearest to co.

    Returns (v0, v1, v2, w0, w1, w2, offset) or None if tris is empty.
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
    return best_in if best_in is not None else best_out


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
                           mw, mwi, delta_degrees, retain_shape=False):
    '''Move non-ring vertices to follow the twist of the surrounding complete rings.

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
            eff_deg_bl   /= total_w
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


def twist_apply(bm, em, mw, mwi, initial_cos, sym_verts, sym_axes, normal, center, delta_degrees, snap_fn=None, loop_params=None, retain_segments=None, finalize=True):
    '''Rotate verts by delta_degrees around normal through center.
    snap_fn(world_pt) -> snapped world-pt or None; omit for free rotation.

    Retain-shape modes (mutually exclusive, loop_params takes priority):

    loop_params – (order, cumul, total) from _traverse_loop_params.  Each vert
        advances delta/360 of the original world-space perimeter regardless of
        loop shape.  Correct for circles, ovals, and any other closed loop.

    retain_segments – fallback for non-loop topologies.  Rotation is applied in
        RETAIN_STEP_DEG increments, snapping each vert to the nearest original
        segment after each step.'''
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
            ws   = _arc_position(orig_fracs[v] + frac_advance, order, cumul, total, initial_cos, mw)
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
        items=[
            ('SMOOTH',  'Smooth',   'Smooth falloff (3t²−2t³)'),
            ('LINEAR',  'Linear',   'Linear falloff'),
            ('SPHERE',  'Sphere',   'Spherical falloff (√(2t−t²))'),
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

                    # Offset prop ring bfs_levels above all core ring levels so
                    # _build_loft_sequence never groups core and prop rings into
                    # the same level bucket (core inner rings and prop rings both
                    # start at level 1, causing wrong adjacency pairings in the loft).
                    max_core_level = max((rd['bfs_level'] for rd in ring_groups), default=0)

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
                        lp = _traverse_loop_params(ring_verts, initial_cos, mw)
                        # Poles have > 2 edges leaving this ring group, so arc-
                        # sliding them around the ring's fitted axis produces the
                        # wrong motion.  Force them to IDW/bary instead.
                        if lp is not None:
                            ring_set = set(ring_verts)
                            if any(
                                sum(1 for e in v.link_edges
                                    if e.other_vert(v) not in ring_set) > 2
                                for v in ring_verts
                            ):
                                lp = None
                        segs = _build_retain_segments(ring_verts, initial_cos, mw) if lp is None else None
                        # Winding fix — same as core rings
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
                        ring_groups.append({
                            'initial_cos':     initial_cos,
                            'sym_verts':       ring_sym,
                            'sym_axes':        sym_axes,
                            'normal':          normal,
                            'center':          center,
                            'loop_params':     lp,
                            'retain_segments': segs,
                            'bfs_level':       max_core_level + hop_lv,
                            'weight':          weight,
                            'is_prop':         True,
                        })
                        # Broken prop rings need per-vert weights so _run_apply
                        # can lerp between original and bary/IDW positions.
                        if lp is None:
                            for v in ring_verts:
                                prop_non_ring_weights[v] = weight

            if ring_groups:
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
                non_ring_initial_cos = {**core_non_ring_cos, **prop_non_ring_cos}

                # prop_bary_lerp_embeddings: {vert: (v0,v1,v2,w0,w1,w2,offset,lerp_weight)}
                # Prop non-ring verts that couldn't embed in the prop-only loft fall
                # back to the full loft + an explicit lerp by the vert's falloff weight.
                # Using bary (not IDW) here preserves retain-shape behaviour because
                # _bary_reconstruct reads v.co from ring verts already arc-slid in Pass 1.
                prop_bary_lerp_embeddings = {}

                # Build full_loft: a proper cylinder/surface when >=2 complete rings
                # exist, or a single end-cap when only 1 exists.  The cap is used as a
                # last-resort embedding surface for prop non-ring verts so that the
                # falloff works even when the topology has no complete prop rings
                # (e.g. a pole-heavy mesh where every hop tier is broken).
                if len(active_rings_lp) >= 2:
                    full_loft = _build_loft_surface(active_rings_lp, all_ring_initial_cos)
                elif len(active_rings_lp) == 1:
                    full_loft = _cap_ring(active_rings_lp[0]['loop_params'][0])
                else:
                    full_loft = []

                # Core non-ring verts must only be embedded in all-core-ring
                # triangles.  Filter the full loft so prop-ring verts can't
                # reduce a core pole's displacement.  Requires >=2 complete rings
                # to produce a loft surface (a single-ring cap has no "between" zone).
                if core_non_ring_cos and len(active_rings_lp) >= 2:
                    core_ring_vert_set = set()
                    for rd in ring_groups:
                        if not rd.get('is_prop'):
                            core_ring_vert_set.update(rd['initial_cos'].keys())
                    core_loft = [(v0, v1, v2) for v0, v1, v2 in full_loft
                                 if v0 in core_ring_vert_set
                                 and v1 in core_ring_vert_set
                                 and v2 in core_ring_vert_set]
                    for v, co0 in core_non_ring_cos.items():
                        result = _find_bary_embedding(co0, core_loft, all_ring_initial_cos)
                        if result is not None:
                            bary_embeddings[v] = result
                        else:
                            bary_fallback_cos[v] = co0

                # Prop non-ring verts must never be embedded in core-ring triangles.
                # Build a prop-only loft so the tier-2 nearest-centroid fallback in
                # _find_bary_embedding can't assign a falloff-boundary vert to a
                # core ring triangle (which would reconstruct at full-strength twist).
                # Verts that fail the prop-only loft fall back to the full loft + an
                # explicit lerp by the vert's own falloff weight.  This path works
                # even when active_rings_lp has only 1 ring (full_loft is a cap).
                if prop_non_ring_cos and full_loft:
                    prop_rings_lp = [rd for rd in ring_groups
                                     if rd.get('is_prop') and rd['loop_params'] is not None]
                    if len(prop_rings_lp) >= 2:
                        prop_loft = _build_loft_surface(prop_rings_lp, all_ring_initial_cos)
                    elif len(prop_rings_lp) == 1:
                        prop_loft = _cap_ring(prop_rings_lp[0]['loop_params'][0])
                    else:
                        prop_loft = []
                    for v, co0 in prop_non_ring_cos.items():
                        result = _find_bary_embedding(co0, prop_loft, all_ring_initial_cos)
                        if result is not None:
                            bary_embeddings[v] = result
                        else:
                            # Can't embed in prop-only loft (vert is in the core/prop
                            # transition zone or prop loft is empty).  Fall back to
                            # the full loft + lerp so bary reconstruction uses the
                            # arc-slid ring vert positions (retain-shape correct) and
                            # the lerp applies the vert's own falloff weight.
                            result2 = _find_bary_embedding(co0, full_loft, all_ring_initial_cos)
                            w = prop_non_ring_weights.get(v, 0.0)
                            if result2 is not None:
                                prop_bary_lerp_embeddings[v] = (*result2, w)
                            else:
                                bary_fallback_cos[v] = co0

                bfs_non_ring_set = set(bfs_non_ring)
                bfs_sym = {v for v in sym_verts       if v in bfs_non_ring_set}
                bfs_sym.update(v for v in prop_sym_verts if v in bfs_non_ring_set)
                components.append({
                    'ring_groups':               ring_groups,
                    'bfs_non_ring_cos':          {v: v.co.copy() for v in bfs_non_ring},
                    'bfs_non_ring_sym':          bfs_sym,
                    'sym_axes':                  sym_axes,
                    'bary_embeddings':           bary_embeddings,
                    'bary_fallback_cos':         bary_fallback_cos,
                    'prop_bary_lerp_embeddings': prop_bary_lerp_embeddings,
                    'non_ring_initial_cos':      non_ring_initial_cos,
                    'prop_non_ring_weights':     prop_non_ring_weights,
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
                    lp      = rd['loop_params'] if self.retain_shape else None
                    deg_ring = deg * rd.get('weight', 1.0)
                    twist_apply(bm, em, mw, mwi,
                                rd['initial_cos'], rd['sym_verts'], rd['sym_axes'],
                                rd['normal'], rd['center'], deg_ring,
                                loop_params=lp, retain_segments=None,
                                finalize=False)
                    active_rings.append(rd)

            # Pass 2: broken rings + BFS-unreachable verts.
            if active_rings:
                # Complete rings exist.  The approach differs by retain_shape:
                #
                # Bary path — used for both retain_shape modes.
                # With the T-junction fix in _find_rings_in_component, the
                # outer boundary rings are now detected correctly even when
                # n-gons interrupt them, so their arc-length distribution is
                # no longer skewed by merged partial-loop branches.
                bary_embeddings   = cd.get('bary_embeddings', {})
                bary_fallback_cos = cd.get('bary_fallback_cos', {})
                mx, my, mz = cd['sym_axes']
                sym_all = set(cd['bfs_non_ring_sym'])
                for rd in broken_rings:
                    sym_all.update(rd['sym_verts'])

                # Barycentric reconstruction from deformed loft surface.
                for v, (v0, v1, v2, w0, w1, w2, offset) in bary_embeddings.items():
                    if v in sym_all:
                        continue
                    v.co = _bary_reconstruct(v0, v1, v2, w0, w1, w2, offset)

                # IDW fallback for core non-ring verts with no loft coverage.
                if bary_fallback_cos:
                    fallback_sym = {v for v in sym_all if v in bary_fallback_cos}
                    twist_apply_blend_axis(active_rings, bary_fallback_cos,
                                           fallback_sym, cd['sym_axes'],
                                           mw, mwi, deg,
                                           retain_shape=self.retain_shape)

                # Prop non-ring verts that fell back from the prop-only loft to the
                # full loft.  Reconstruct from the full-loft bary embedding (which
                # reads arc-slid ring vert positions → retain-shape correct), then
                # lerp by the stored falloff weight so verts near the falloff boundary
                # don't inherit full-strength movement from core ring verts.
                prop_bary_lerp_embeddings = cd.get('prop_bary_lerp_embeddings', {})
                if prop_bary_lerp_embeddings:
                    ni_cos = cd.get('non_ring_initial_cos', {})
                    for v, (v0, v1, v2, w0, w1, w2, offset, lerp_w) in prop_bary_lerp_embeddings.items():
                        if v in sym_all:
                            continue
                        co0 = ni_cos.get(v)
                        bary_co = _bary_reconstruct(v0, v1, v2, w0, w1, w2, offset)
                        v.co = co0 + lerp_w * (bary_co - co0) if co0 is not None else bary_co

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
        supported_falloffs = {'SMOOTH', 'LINEAR', 'SPHERE'}
        self.proportional_falloff   = (
            ts.proportional_edit_falloff
            if ts.proportional_edit_falloff in supported_falloffs
            else 'SMOOTH'
        )
        prop_distances = None
        if self.use_proportional_edit:
            prop_distances = _gather_proportional_verts(sel_verts, self._mw, self.proportional_distance)
        self._component_data = self._build_component_data(context, sel_verts, self._mw, prop_distances=prop_distances)
        if not self._component_data:
            return {'CANCELLED'}
        self._initial_mouse_x = event.mouse_x
        self.twist_angle = 0.0
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
            if context.area:
                context.area.header_text_set(None)
            return {'CANCELLED'}
        return {'PASS_THROUGH'}
