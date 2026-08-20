'''
Copyright (C) 2026 CG Cookie
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
import math
from mathutils import Matrix, Vector

from ..common.bmesh import (
    get_bmesh_emesh,
    get_bmv_next_loop_vert,
    get_faces_of_verts,
    get_falloff_verts,
    get_vert_connected,
    has_mirror_x, has_mirror_y, has_mirror_z,
)
from ..common.bmesh_maths import (
    bary_reconstruct,
    fit_plane_of_verts,
    get_bary_triangle,
    loop_arc_params,
)
from ..common.maths import closest_point_linesegment, get_co_on_arc
from ..common.operator import RFRegisterClass, RFKeyMaps


TWIST_SENSITIVITY = 0.05   # degrees per pixel of horizontal mouse movement
RETAIN_STEP_DEG = 1.0   # degree increment steps for snapping to the existing shape
LOFT_NORMAL_THRESHOLD = 0.34   # cos(~70°), reject rings more perpendicular than this
LOOP_POLE_THRESHOLD = 5.0    # degree angle under which loops can pass through poles
RING_AXIS_ALIGN = 0.5    # min dot product for a loop to count as a cross-section ring
DRAW_DEBUG_RINGS = False  # draw dashed ring highlights during the modal


def trace_loop(v_start, v_second):
    ''' Trace the edge loop starting with edge (v_start -> v_second) until it
    returns to v_start. Returns the ordered verts or None if it never closes. '''
    loop = [v_start, v_second]
    seen = {v_start, v_second}
    prev, cur = v_start, v_second
    for _ in range(4096):
        nxt = get_bmv_next_loop_vert(prev, cur, walk_boundaries=False, pole_angle_threshold=LOOP_POLE_THRESHOLD)
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


def get_core_rings(component_verts):
    ''' Detect the selection's cross-section rings by walking edge loops.
    Returns (rings, ring_indices, interpolated_verts).
    rings:               ordered vertex cycles, one per complete cross-section
    ring_indices:        per-ring index (same as position in rings list)
    interpolated_verts:  selection verts not on any complete ring
    '''
    comp_set = set(component_verts)
    axis, _  = fit_plane_of_verts(component_verts)
    if axis is None or axis.length < 1e-9:
        return [], list(component_verts), []
    axis = axis.normalized()

    def perp_to_axis(v_from, v_to):
        d = v_to.co - v_from.co
        if d.length < 1e-12:
            return -1.0
        return 1.0 - abs(d.normalized().dot(axis))

    def ring_edges(v):
        # All in-component neighbours sorted by descending perpendicularity to the axis
        candidates = []
        for e in v.link_edges:
            o = e.other_vert(v)
            if o not in comp_set:
                continue
            candidates.append((perp_to_axis(v, o), o))
        candidates.sort(key=lambda x: -x[0])
        return [o for _, o in candidates]

    def step(prev, cur):
        e_in = next((e for e in cur.link_edges if e.other_vert(cur) == prev), None)
        if e_in is None:
            return None
        in_faces = set(e_in.link_faces)
        clean = [e.other_vert(cur) for e in cur.link_edges
                 if e.other_vert(cur) in comp_set and e.other_vert(cur) != prev
                 and not any(f in in_faces for f in e.link_faces)]
        if len(clean) == 1:
            # regular quad vert: topological continuation
            return clean[0]
        # For poles, take the most straight ahead edge
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
                continue # forward continuations only
            p = perp_to_axis(cur, o)
            if p > best_perp:
                best_perp, best = p, o
        return best

    def trace(start, second):
        loop, seen = [start, second], {start, second}
        prev, cur  = start, second
        for _ in range(len(comp_set) + 1):
            nxt = step(prev, cur)
            if nxt is None: return None
            if nxt == start: return loop
            if nxt in seen: return None
            loop.append(nxt); seen.add(nxt)
            prev, cur = cur, nxt
        return None

    rings, ring_indices, assigned = [], [], set()
    for v in component_verts:
        if v in assigned: continue
        # Try each cross-section candidate in order of perpendicularity.
        # Stop at the first direction that traces a complete ring.
        # If the best direction leads to a dead end, attempt the next best.
        for o in ring_edges(v):
            loop = trace(v, o)
            if loop is None or len(loop) < 3 or any(w in assigned for w in loop):
                continue
            rings.append(loop)
            ring_indices.append(len(ring_indices))
            assigned.update(loop)
            break
    interpolated_verts = [v for v in component_verts if v not in assigned]
    return rings, ring_indices, interpolated_verts


def get_falloff_rings(comp_prop, core_set):
    ''' Find cross-section rings that touch the falloff zone. Returns:
    - rings: list of (loop_verts_ordered, avg_falloff_weight, level)
    - non_ring_verts: falloff verts not on any closed loop '''
    prop_set = set(comp_prop.keys())
    assigned = set()
    rings    = []

    def _add_ring(loop):
        in_r = [w for w in loop if w in comp_prop]
        if not in_r:
            return False
        avg_w = sum(comp_prop[w] for w in in_r) / len(in_r)
        rings.append((loop, avg_w, len(rings)))
        assigned.update(loop)
        return True

    # Check n-gon faces first, like a cylinder's end cap
    seen_faces = set()
    for v in prop_set:
        for f in v.link_faces:
            if f in seen_faces or len(f.verts) <= 4:
                continue
            seen_faces.add(f)
            loop = list(f.verts)
            if not any(w in assigned for w in loop):
                _add_ring(loop)

    # Nearest-core verts next. Their toward-core neighbour is least ambiguous,
    # so each loop is discovered from its most reliable seed.
    for v in sorted(prop_set, key=lambda w: comp_prop[w]):
        if v in assigned: continue
        # Toward-core neighbour u: adjacent vert with the smallest distance (core verts count as 0).
        # Edge (u, v) is the local axial direction.
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
        # Ring neighbours of v: neighbours other than u whose edge shares a quad face with the axial edge
        # i.e. perpendicular to the axial direction, running along the cross-section.
        uv_faces = set(e_uv.link_faces)
        ring_nbs = [e.other_vert(v) for e in v.link_edges
                    if e.other_vert(v) != u
                    and any(f in uv_faces and len(f.verts) == 4 for f in e.link_faces)]
        # Trace the cross-section loop and accept the first that closes cleanly
        loop = None
        for r in ring_nbs:
            loop = trace_loop(v, r)
            if loop is not None:
                break
        if loop is None:
            continue  # v isn't on a clean closed cross-section
        if any(w in assigned for w in loop):
            continue  # overlaps an existing ring
        _add_ring(loop)

    non_ring_verts = [v for v in prop_set if v not in assigned]
    return rings, non_ring_verts


def get_fallback_rings(component_verts):
    ''' Fallback method for determining rings to twist when no complete loops are found.
    For a face band, each row of vertices forms its own ring.
    Returns (ring_groups, ring_indices, non_ring_verts).
    Falls back to ([component_verts], [0], []) when:
      - no enclosed faces exist (plain edge loop / vertex ring selection), or
      - no boundary vertices exist (fully-closed selection like a sphere). '''
    sel_set   = set(component_verts)
    sel_faces = get_faces_of_verts(component_verts)

    if not sel_faces:
        # Plain edge-loop selection with no enclosed quads, so treat as one loop.
        return [component_verts], [], [0]

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
        # Closed selection such as a fully selected sphere or cylinder
        return [component_verts], [], [0]

    # Multi-source BFS from all boundary verts, advancing one edge per step.
    # Edge propogation is much better than face propogation when n-gons are present.
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
            # Only propagate through edges that belong to the selected face region
            if not any(f in sel_faces for f in e.link_faces):
                continue
            new_lv = level[v] + 1
            if new_lv < level[nb]:
                level[nb] = new_lv
                queue.append(nb)

    # Verts the BFS could not reach (isolated pockets, closed-off topology).
    bfs_non_ring = [v for v in component_verts if level[v] == INF]

    # Group reachable vertices by BFS level.
    by_level = {}
    for v in component_verts:
        lv = level[v]
        if lv == INF:
            continue
        by_level.setdefault(lv, []).append(v)

    # Within each level, split into edge-connected sub-loops.
    rings, ring_indices = []
    for lv in sorted(by_level.keys()):
        group = by_level[lv]
        group_set = set(group)

        adj = {}
        for v in group:
            for e in v.link_edges:
                nb = e.other_vert(v)
                if nb not in group_set:
                    continue
                # At lv == 0, restrict to selection boundary edges
                # Otherwise, a single edge between boundaries will get merged into one ring
                if lv == 0 and not any(f not in sel_faces for f in e.link_faces):
                    continue
                adj.setdefault(v, []).append(nb)

        # Resolve T-junction verts at the selection boundary (lv == 0).
        # Fixes n-gon corners at the selection boundary.
        if lv == 0:
            for v in group:
                nbs = adj.get(v, [])
                if len(nbs) <= 2: continue   # normal ring vert or dead end
                # At each T-junction keep only the most linear pairs of edges
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
            ring_indices.append(lv)

    return (rings if rings else [component_verts]), (ring_indices if rings else [0]), bfs_non_ring


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


def get_retain_segments(sel_verts, initial_coords, mw):
    ''' Fallback for non-loop topologies: world-space (a, b) pairs for all
    selected edges.  Used by the iterative rotate-and-snap path only when
    loop_arc_params returns None. '''
    sel_set  = set(sel_verts)
    edges    = {e for v in sel_verts for e in v.link_edges}
    segments = []
    for e in edges:
        v0, v1 = e.verts
        if v0 not in sel_set or v1 not in sel_set:
            continue
        a = mw @ initial_coords[v0]
        b = mw @ initial_coords[v1]
        if (b - a).length_squared < 1e-12:
            continue
        segments.append((a, b))
    return segments


def fix_loop_winding(lp, initial_coords, check_normal, mw):
    ''' Reverse lp's traversal order if it winds opposite to check_normal.
    Returns the lp tuple, unchanged if already correct.'''
    if lp is None or check_normal is None:
        return lp
    order, cumul, total = lp
    ctr = sum((initial_coords[v] for v in order), Vector()) / len(order)
    area_vec = Vector((0.0, 0.0, 0.0))
    for i in range(len(order)):
        a = initial_coords[order[i]] - ctr
        b = initial_coords[order[(i + 1) % len(order)]] - ctr
        area_vec += a.cross(b)
    if area_vec.dot(check_normal) < 0:
        # Winding is opposite to normal so reverse traversal order.
        # Keep first vert as anchor, flip the rest, and
        # recompute world space cumulative distances for the new order.
        order = [order[0]] + list(reversed(order[1:]))
        cumul = [0.0]
        for i in range(1, len(order)):
            seg = (mw @ initial_coords[order[i]]) - (mw @ initial_coords[order[i - 1]])
            cumul.append(cumul[-1] + seg.length)
        return (order, cumul, total)
    return lp


def snap_to_nearest_segment(co, segments):
    ''' Return the nearest point on any (a, b) segment to co. '''
    best_d, best = float('inf'), co
    for a, b in segments:
        proj = closest_point_linesegment(co, a, b)
        if proj is None:
            continue
        d = (co - proj).length_squared
        if d < best_d:
            best_d, best = d, proj
    return best


def order_rings_by_axis(all_rings):
    ''' Order + validate the rings by an outward walk along the rotation axis.
    Returns the ordered chain of valid cross-section rings '''
    rings = [rd for rd in all_rings if rd['loop_params'] is not None]
    if len(rings) < 2:
        return rings

    def centroid(rd):
        cos = rd['initial_coords']
        return sum(cos.values(), Vector()) / len(cos)
    cents = {id(rd): centroid(rd) for rd in rings}

    # Global axis fallback for rings whose own normal failed to fit.
    # Normals are already sign-aligned upstream, so summing them is meaningful.
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
                    continue  # not ahead along this ring's axis
                if abs(axis_of(rd).dot(ax)) < RING_AXIS_ALIGN:
                    continue   # not aligned with this ring
                d = d_vec.length   # nearest aligned ring ahead
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


def get_loft_sequence(all_rings):
    ''' Pair complete rings consecutively along the spatial axis order. '''
    ordered = order_rings_by_axis(all_rings)
    if len(ordered) < 2: return []
    pairs = []
    prev  = ordered[0]
    for rd in ordered[1:]:
        n_a = prev['normal']
        n_b = rd['normal']
        if n_a is not None and n_b is not None and abs(n_a.dot(n_b)) < LOFT_NORMAL_THRESHOLD:
            # Near perpendicular: skip rd as a partner but keep prev as anchor
            # so the loft bridges across it instead of leaving a hole.
            continue
        pairs.append((prev, rd))
        prev = rd
    return pairs


def loft_rings(rd_a, rd_b, initial_coords):
    ''' Zipper loft between two rings using arc-length correspondence. '''
    order_a, cumul_a, total_a = rd_a['loop_params']
    order_b, cumul_b, total_b = rd_b['loop_params']
    n, m = len(order_a), len(order_b)

    # Align B to start at the vertex closest to order_a[0].
    co_a0 = initial_coords[order_a[0]]
    j0    = min(range(m), key=lambda k: (initial_coords[order_b[k]] - co_a0).length_squared)
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
            # A exhausted: consume remaining B edges, closing the seam
            tris.append((order_a[0], b0, order_b[(ib + 1) % m]))
            ib += 1
        elif ib >= m:
            # B exhausted: consume remaining A edges
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


def cap_ring(order):
    ''' Fan-triangulate a ring as an end cap. Used so geometry behind the ring can find a triangle to embed in. '''
    return [(order[0], order[i], order[i + 1]) for i in range(1, len(order) - 1)]


def build_loft_surface(all_rings, initial_coords):
    ''' Build the loft surface between complete rings, plus end caps.
    Takes all ring groups (complete + broken).
    The broken ones only inform the adjacency chain so the loft can bridge across pole rings.
    Returns (bands, caps), each a list of (v0, v1, v2) BMVert triples.
    Caps are kept separate so certain verts can avoid them. '''
    pairs = get_loft_sequence(all_rings)
    if not pairs:
        return [], []

    bands      = []
    pair_count = {}
    for rd_a, rd_b in pairs:
        bands.extend(loft_rings(rd_a, rd_b, initial_coords))
        pair_count[id(rd_a)] = pair_count.get(id(rd_a), 0) + 1
        pair_count[id(rd_b)] = pair_count.get(id(rd_b), 0) + 1

    # Cap terminal complete rings
    caps = []
    for rd in all_rings:
        if rd['loop_params'] is not None and pair_count.get(id(rd), 0) <= 1:
            caps.extend(cap_ring(rd['loop_params'][0]))
    return bands, caps


def twist_apply_blend_axis(ring_data_list, non_ring_initial_coords, sym_verts, sym_axes,
                           mw, mwi, delta_degrees, retain_shape=False, vert_weights=None):
    ''' Move non-ring vertices to follow the twist of the surrounding complete rings. '''
    mx, my, mz = sym_axes

    # Flat lookup, used for retain_shape distances.
    ring_init_lookup = {}
    for rd in ring_data_list:
        ring_init_lookup.update(rd['initial_coords'])

    # ring_vert to ring index, used to detect poles vs. between ring verts.
    ring_of_vert = {}
    for i, rd in enumerate(ring_data_list):
        for vert in rd['initial_coords']:
            ring_of_vert[vert] = i

    # Pre-compute each ring's world space axis, vert positions, and effective rotation angle.
    #
    # The effective angle is measured from how the ring verts already moved.
    # For retain_shape = False, pure rotation. effective_deg ≈ delta_degrees so no change.
    # For retain_shape = True, arc-length slide. On a non-circular loop the ring verts
    # travel less angular distance than delta_degrees, so using effective_deg in
    # the blend-axis rotation keeps non-ring verts consistent with them
    ring_ws = []
    for rd in ring_data_list:
        if rd['normal'] is None:
            continue
        ws_center   = mw @ rd['center']
        ws_normal   = (mw.to_3x3() @ rd['normal']).normalized()
        if ws_normal.length_squared < 1e-12:
            continue
        ws_positions = [mw @ co0 for co0 in rd['initial_coords'].values()]

        # Average angular displacement of ring verts around the ring axis.
        angles = []
        for v_r, co0_r in rd['initial_coords'].items():
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

    if not ring_ws: return

    for v, co0 in non_ring_initial_coords.items():
        if v in sym_verts:
            continue
        ws = mw @ co0
        vw = vert_weights.get(v, 1.0) if vert_weights else 1.0

        placed = False

        if retain_shape:
            # Find directly connected ring verts and accumulate weighted displacements.
            # Also track which distinct rings the neighbours belong to.
            #
            # The displacement approach is only correct when neighbours span at least two rings.
            # For a pole whose spokes all terminate in the same ring, averaging the
            # tangential displacements of ring verts produces a net radial shift
            # for any pole that is not perfectly symmetric — pulling it away from
            # the rotation axis. Such verts fall through to blend-axis rotation,
            # which correctly keeps them near the axis regardless of spoke symmetry.
            total_w       = 0.0
            ws_displ      = Vector((0.0, 0.0, 0.0))
            neighbor_rings = set()
            for e in v.link_edges:
                nb      = e.other_vert(v)
                nb_orig = ring_init_lookup.get(nb)
                if nb_orig is None:
                    continue   # not a ring vert
                neighbor_rings.add(ring_of_vert[nb])
                d = (mw @ co0 - mw @ nb_orig).length
                w = (1.0 / d) if d > 1e-12 else 1e12
                # Accumulate the displacement of each ring neighbour from its original (not absolute) position,
                # so the non-ring vert starts exactly at its original position when delta == 0 (no snap on invoke),
                # and moves by the weighted average shift of the surrounding arc-slid ring verts.
                ws_displ += w * ((mw @ nb.co) - (mw @ nb_orig))
                total_w  += w
            if total_w > 1e-12 and len(neighbor_rings) > 1:
                # Follow the neighbour rings displacement, which already encodes their falloff.
                # A vert between two complete rings embeds in a band, so falloff verts almost never reach this.
                v.co  = mwi @ (ws + ws_displ / total_w)
                placed = True
            # len(neighbor_rings) == 0: no ring neighbours
            # len(neighbor_rings) == 1: pole or inside one ring

        if not placed:
            # Blend-axis rotation. Center, normal, and effective rotation angle are blended
            # with the same IDW weights so the vert follows the motion of the ring(s) it is closest to.
            total_w      = 0.0
            ws_center_bl = Vector((0.0, 0.0, 0.0))
            ws_normal_bl = Vector((0.0, 0.0, 0.0))
            eff_deg_bl   = 0.0

            for ws_center, ws_normal, ws_positions, effective_deg in ring_ws:
                # Weight by nearest ring vert, not ring centroid, so a vert
                # adjacent to a ring gets that ring's axis almost exactly.
                min_d_sq = min((ws - p).length_squared for p in ws_positions)
                # Project ws onto the ring's axis line.
                # For a straight cylinder every ring's axis line is the same.
                # For a bent tube, blending several projected points approximates the local axis.
                axis_pt = ws_center + ws_normal * (ws - ws_center).dot(ws_normal)
                if min_d_sq < 1e-12:
                    # Coincident with a ring vert so use that ring's axis exactly.
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
                # Rotate by the vert's own falloff weight × the full twist since
                # using the blended ring angle × weight would double count falloff.
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


def twist_apply(bm, em, mw, mwi, initial_coords, sym_verts, sym_axes, normal, center, delta_degrees,
                snap_fn=None, loop_params=None, retain_segments=None, finalize=True, vert_weights=None):
    ''' Rotate verts by delta_degrees around normal through center. '''
    if not normal: return
    mx, my, mz = sym_axes

    if loop_params is not None:
        # Arc-length parameterised slide along the original polygon
        order, cumul, total = loop_params
        frac_advance = delta_degrees / 360.0
        orig_fracs = {v: cumul[i] / total for i, v in enumerate(order)}
        for v in initial_coords:
            if v in sym_verts: continue
            w = vert_weights.get(v, 1.0) if vert_weights else 1.0
            ws = get_co_on_arc(orig_fracs[v] + frac_advance * w, order, cumul, total, initial_coords, mw)
            v.co = mwi @ ws
            if snap_fn is not None:
                snapped = snap_fn(mw @ v.co)
                if snapped is not None:
                    v.co = mwi @ snapped

    elif retain_segments and delta_degrees != 0.0:
        # Fallback to iterative rotate-and-snap for non-loop topologies
        n_steps = max(1, int(math.ceil(abs(delta_degrees) / RETAIN_STEP_DEG)))
        step_xform = (
            Matrix.Translation(center)
            @ Matrix.Rotation(math.radians(delta_degrees / n_steps), 4, normal)
            @ Matrix.Translation(-center)
        )
        cur = {v: co0.copy() for v, co0 in initial_coords.items() if v not in sym_verts}
        for _ in range(n_steps):
            for v in cur:
                ws = snap_to_nearest_segment(mw @ (step_xform @ cur[v]), retain_segments)
                cur[v] = mwi @ ws
        for v, co in cur.items():
            v.co = co
            if snap_fn is not None:
                snapped = snap_fn(mw @ v.co)
                if snapped is not None:
                    v.co = mwi @ snapped

    else:
        # Pure rotation. retain_shape False or no retain data available
        xform = (
            Matrix.Translation(center)
            @ Matrix.Rotation(math.radians(delta_degrees), 4, normal)
            @ Matrix.Translation(-center)
        )
        for v, co0 in initial_coords.items():
            if v in sym_verts: continue
            if vert_weights:
                # Per-vert angle for proportional falloff
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

    rf_keymaps : RFKeyMaps = []

    twist_angle: bpy.props.FloatProperty(
        name='Twist',
        description='Twist angle',
        default=0.0,
        subtype='ANGLE',
    )
    retain_shape: bpy.props.BoolProperty(
        name='Retain Shape',
        description='Slide vertices along the original edges while twisting',
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
        # Full set supported by proportional_edit() in common/maths.py, matches Blender
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
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'twist_angle')
        layout.row(heading='Retain').prop(self, 'retain_shape', text='Original Shape')
        prop_header, prop_panel = layout.panel('relax_selected_proportional', default_closed=False)
        prop_header.use_property_split=False
        prop_header.prop(self, 'use_proportional_edit', text='Proportional Editing')
        if prop_panel:
            prop_panel.use_property_split = True
            prop_panel.use_property_decorate = False
            prop_panel.enabled = self.use_proportional_edit
            prop_panel.prop(self, 'proportional_distance', text='Distance')
            prop_panel.prop(self, 'proportional_falloff',  text='Falloff')

    def header_modal_text(self):
        deg  = math.degrees(self.twist_angle)
        rs   = 'ON' if self.retain_shape else 'OFF'
        ts   = self._ts
        prop = f'ON ({ts.proportional_distance:.2f}m)' if ts.use_proportional_edit else 'OFF'
        return (f"Twist: {deg:+.1f}°   [R] Retain Shape: {rs}   [O] Proportional: {prop}"
                f"   |   LMB/Enter: Confirm   RMB/Esc: Cancel")

    def restore_initial_positions(self):
        for cd in self._component_data:
            for rd in cd['ring_groups']:
                for v, co0 in rd['initial_coords'].items():
                    v.co = co0.copy()
            for v, co0 in cd['bfs_non_ring_coords'].items():
                v.co = co0.copy()
        self._bm.normal_update()

    def rebuild_component_data(self, context):
        self.restore_initial_positions()
        ts = self._ts
        falloff_distances = None
        if ts.use_proportional_edit:
            falloff_distances = get_falloff_verts(
                self._sel_verts, self._mw, ts.proportional_distance, ts.proportional_edit_falloff)
        self._component_data = self.get_component_data(
            context, self._sel_verts, self._mw, falloff_distances=falloff_distances)

    def get_component_data(self, context, sel_verts, mw, falloff_distances=None):
        ''' Build per-component twist data. Returns a list of component dicts, each containing:
          ring_groups - One dict per BFS level sub-loop so each ring has its own rotation axis
          bfs_non_ring_coords - {v: co0} for BFS-unreachable verts
          bfs_non_ring_sym - sym-vert subset of the above.
          sym_axes - (mx, my, mz) mirror flags for the component. '''
        components = []
        for component_verts in get_vert_connected(sel_verts):
            if len(component_verts) < 3: continue
            sym_verts, sym_axes = twist_detect_symmetry(context, component_verts)

            # Walk the cross-section edge loops to find the guide rings.
            # Fall back to the boundary BFS detection only when that finds none
            # (e.g. an open patch with no closed cross-section) so those selections still get drivers.
            ring_groups_verts, ring_indices, bfs_non_ring = get_core_rings(component_verts)
            if not ring_groups_verts:
                ring_groups_verts, ring_indices, bfs_non_ring = get_fallback_rings(component_verts)

            ring_groups = []
            ref_normal = None # first successfully fitted normal that all others align to
            for ring_idx, ring_verts in enumerate(ring_groups_verts):
                if len(ring_verts) < 3:
                    bfs_non_ring.extend(ring_verts)
                    continue
                initial_coords = {v: v.co.copy() for v in ring_verts}
                ring_sym = {v for v in sym_verts if v in set(ring_verts)}
                # Per-ring axis so each loop rotates about its own normal.
                normal, center = fit_plane_of_verts(ring_verts) # The normal of this plane is not consistent
                # Flip rings facing opposite to reference so they all face the same direction
                if normal is not None:
                    if ref_normal is None:
                        ref_normal = normal.copy()
                    elif normal.dot(ref_normal) < 0:
                        normal = -normal
                # Pre-compute both paths. retain_shape toggle chooses at apply time.
                lp = loop_arc_params(ring_verts, initial_coords, mw)
                segs = get_retain_segments(ring_verts, initial_coords, mw) if lp is None else None

                # loop_arc_params picks a traversal direction arbitrarily.
                # Ensure it winds in the same sense as the aligned normal so the arc-length path (retain_shape True)
                # and the pure-rotation path (retain_shape False) always rotate in the same direction.
                # Use `normal` if available, fall back to `ref_normal` for rings where plane fitting failed.
                check_normal = normal if normal is not None else ref_normal
                lp = fix_loop_winding(lp, initial_coords, check_normal, mw)
                ring_groups.append({
                    'initial_coords':     initial_coords,
                    'sym_verts':       ring_sym,
                    'sym_axes':        sym_axes,
                    'normal':          normal,
                    'center':          center,
                    'loop_params':     lp,
                    'retain_segments': segs,
                    'bfs_level':       ring_indices[ring_idx],
                    'weight':          1.0,
                    'is_prop':         False,
                })

            # Find rings from falloff verts
            falloff_non_ring_weights = {}   # {vert: falloff_weight} for all prop non-ring verts
            falloff_sym_verts = set()
            if falloff_distances:
                # BFS from core component outward through falloff_distances verts
                comp_prop = {}
                component_set = set(component_verts)
                visited_prop = set(component_set)
                queue = list(component_verts)
                while queue:
                    v = queue.pop()
                    for e in v.link_edges:
                        nb = e.other_vert(v)
                        if nb in visited_prop: continue
                        if nb in falloff_distances:
                            comp_prop[nb] = falloff_distances[nb]
                            visited_prop.add(nb)
                            queue.append(nb)

                if comp_prop:
                    falloff_sym_verts, _ = twist_detect_symmetry(context, list(comp_prop.keys()))

                    prop_rings, prop_unreachable = get_falloff_rings(comp_prop, component_set)
                    for v in prop_unreachable:
                        falloff_non_ring_weights[v] = comp_prop[v]
                    bfs_non_ring.extend(prop_unreachable)

                    # Each prop_rings entry is a complete cross-section loop, so build one ring driver per entry.
                    # A pole that the loop passes straight through is an ordinary member that slides like any other vert.
                    for ring_verts, avg_w, hop_lv in prop_rings:
                        if len(ring_verts) < 3:
                            for v in ring_verts:
                                falloff_non_ring_weights[v] = comp_prop.get(v, 0.0)
                            bfs_non_ring.extend(ring_verts)
                            continue
                        initial_coords = {v: v.co.copy() for v in ring_verts}
                        ring_sym    = {v for v in falloff_sym_verts if v in set(ring_verts)}
                        normal, center = fit_plane_of_verts(ring_verts)
                        if normal is not None:
                            if ref_normal is None:
                                ref_normal = normal.copy()
                            elif normal.dot(ref_normal) < 0:
                                normal = -normal
                        # Cross-section validity (is this loop's plane aligned with the rotation axis?)
                        # is decided later by the outward axis walk, which checks each ring against its neighbors's axis.
                        # A global normal check here would wrongly reject the far rings of a sharply curved tube.
                        lp   = loop_arc_params(ring_verts, initial_coords, mw)
                        segs = get_retain_segments(ring_verts, initial_coords, mw) if lp is None else None
                        check_normal = normal if normal is not None else ref_normal
                        lp = fix_loop_winding(lp, initial_coords, check_normal, mw)
                        weight = avg_w
                        vert_weights = {v: comp_prop.get(v, 0.0) for v in ring_verts}
                        ring_groups.append({
                            'initial_coords':     initial_coords,
                            'sym_verts':       ring_sym,
                            'sym_axes':        sym_axes,
                            'normal':          normal,
                            'center':          center,
                            'loop_params':     lp,
                            'retain_segments': segs,
                            'bfs_level':       hop_lv,
                            'weight':          weight,
                            'is_prop':         True,
                            'vert_weights':    vert_weights,
                        })
                        if lp is None:
                            # Fallback for if loop_params fails, its verts ride the loft
                            for v in ring_verts:
                                falloff_non_ring_weights[v] = vert_weights[v]

            if ring_groups:
                # Validate + order the rings with the outward axis walk.
                # Falloff rings the walk can't reach (sideways loops like a wall n-gon) are not cross-sections so
                # demote them to interpolated_verts so they ride the loft instead of twisting around a wrong axis.
                # Core rings are the trusted selection and are never demoted.
                ring_chain = order_rings_by_axis(ring_groups)
                chain_ids  = {id(rd) for rd in ring_chain}
                kept = []
                for rd in ring_groups:
                    if (rd.get('is_prop') and rd['loop_params'] is not None
                            and id(rd) not in chain_ids):
                        for v, w in rd.get('vert_weights', {}).items():
                            if w > 0.0:  # in-radius vert is a passenger
                                falloff_non_ring_weights[v] = w
                                bfs_non_ring.append(v)
                    else:
                        kept.append(rd)
                ring_groups = kept

                # Build barycentric loft surface and embed all non-ring verts.
                active_rings_lp = [rd for rd in ring_groups if rd['loop_params'] is not None]

                all_ring_initial_coords = {}
                for rd in ring_groups:
                    all_ring_initial_coords.update(rd['initial_coords'])

                bary_embeddings   = {}
                bary_fallback_coords = {}

                # Separate non-ring verts by origin so core poles are never embedded in falloff-ring triangles
                # since prop ring verts move at reduced weight, which would pull the core pole away from full-twist.
                core_non_ring_coords = {}
                falloff_non_ring_coords = {}
                for rd in ring_groups:
                    if rd['loop_params'] is None:
                        target = falloff_non_ring_coords if rd.get('is_prop') else core_non_ring_coords
                        target.update(rd['initial_coords'])
                for v in bfs_non_ring:
                    co = v.co.copy()
                    if v in falloff_non_ring_weights:
                        falloff_non_ring_coords[v] = co
                    else:
                        core_non_ring_coords[v] = co
                # Build the loft once from every complete ring (core + falloff).
                # Bands and caps are kept separate since bands twist cleanly while caps shear under arc-slide.
                if len(active_rings_lp) >= 2:
                    # Pass all ring groups so the adjacency chain can bridge across broken rings.
                    # build_loft_surface lofts only the complete ones.
                    bands, caps = build_loft_surface(ring_groups, all_ring_initial_coords)
                elif len(active_rings_lp) == 1:
                    bands, caps = [], cap_ring(active_rings_lp[0]['loop_params'][0])
                else:
                    bands, caps = [], []
                full_loft = bands + caps

                # Classify each loft triangle by whether it touches a falloff ring.
                core_ring_vert_set = set()
                for rd in ring_groups:
                    if not rd.get('is_prop'):
                        core_ring_vert_set.update(rd['initial_coords'].keys())
                # Fully core triangles: full-strength surface for core poles.
                core_loft = [t for t in full_loft if all(v in core_ring_vert_set for v in t)]
                # Falloff touching band triangles only (caps excluded)
                falloff_loft = [t for t in bands if any(v not in core_ring_vert_set for v in t)]

                # Core non-ring verts stay at full twist. Embed only in pure-core triangles.
                for v, co0 in core_non_ring_coords.items():
                    result = get_bary_triangle(co0, core_loft, all_ring_initial_coords)
                    if result is not None:
                        bary_embeddings[v] = result
                    else:
                        bary_fallback_coords[v] = co0

                # Ring verts with rest position + falloff weight, for the "beyond the loft" fallback below.
                driver_data = []
                for rd in active_rings_lp:
                    vw = rd.get('vert_weights')
                    for dv, drest in rd['initial_coords'].items():
                        driver_data.append((dv, drest, vw.get(dv, 1.0) if vw else 1.0))

                # Falloff non-ring verts ride falloff band triangles.
                # Bary reconstruction reads the rings live positions, so the reduced motion
                # comes from the surrounding rings rotation and retain-shape is preserved.
                # A vert past the end of the loft instead copies the nearest ring vert's
                # displacement, dampened by the ratio of its own falloff to that ring vert's.
                beyond_loft = {}
                for v, co0 in falloff_non_ring_coords.items():
                    result = get_bary_triangle(co0, falloff_loft, all_ring_initial_coords,
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
                        bw   = falloff_non_ring_weights.get(v, 0.0)
                        beyond_loft[v] = (dv, drest.copy(), co0.copy(), min(bw / dw, 1.0))
                    else:
                        bary_fallback_coords[v] = co0

                bfs_non_ring_set = set(bfs_non_ring)
                bfs_sym = {v for v in sym_verts       if v in bfs_non_ring_set}
                bfs_sym.update(v for v in falloff_sym_verts if v in bfs_non_ring_set)
                components.append({
                    'ring_groups':              ring_groups,
                    'bfs_non_ring_coords':      {v: v.co.copy() for v in bfs_non_ring},
                    'bfs_non_ring_sym':         bfs_sym,
                    'sym_axes':                 sym_axes,
                    'bary_embeddings':          bary_embeddings,
                    'bary_fallback_coords':     bary_fallback_coords,
                    'beyond_loft':              beyond_loft,
                    'falloff_non_ring_weights': falloff_non_ring_weights,
                })
        return components

    def run_apply(self, bm, em, mw, mwi, component_data):
        ''' Apply the current twist_angle to all components. '''
        deg = math.degrees(self.twist_angle)
        for cd in component_data:
            # Pass 1: separate complete rings from broken ones.
            active_rings = []
            broken_rings = []

            for rd in cd['ring_groups']:
                if rd['loop_params'] is None:
                    # Geometrically incomplete ring (pole region, triangle fan, open chain).
                    # Always goes to IDW regardless of retain_shape so its verts follow the surrounding rings cleanly.
                    broken_rings.append(rd)
                else:
                    # Complete closed loop so arc-length or pure rotation.
                    lp  = rd['loop_params'] if self.retain_shape else None
                    rvw = rd.get('vert_weights')
                    if rvw is not None:
                        twist_apply(bm, em, mw, mwi,
                                    rd['initial_coords'], rd['sym_verts'], rd['sym_axes'],
                                    rd['normal'], rd['center'], deg,
                                    loop_params=lp, retain_segments=None,
                                    finalize=False, vert_weights=rvw)
                    else:
                        deg_ring = deg * rd.get('weight', 1.0)
                        twist_apply(bm, em, mw, mwi,
                                    rd['initial_coords'], rd['sym_verts'], rd['sym_axes'],
                                    rd['normal'], rd['center'], deg_ring,
                                    loop_params=lp, retain_segments=None,
                                    finalize=False)
                    active_rings.append(rd)

            # Pass 2: broken rings + BFS-unreachable verts.
            if active_rings:
                # Complete rings exist so bary path is used for both retain_shape modes.
                bary_embeddings      = cd.get('bary_embeddings', {})
                bary_fallback_coords = cd.get('bary_fallback_coords', {})
                beyond_loft          = cd.get('beyond_loft', {})
                mx, my, mz = cd['sym_axes']
                sym_all = set(cd['bfs_non_ring_sym'])
                for rd in broken_rings:
                    sym_all.update(rd['sym_verts'])

                # Barycentric reconstruction from deformed loft surface.
                for v, (v0, v1, v2, w0, w1, w2, offset) in bary_embeddings.items():
                    if v in sym_all: continue
                    v.co = bary_reconstruct(v0, v1, v2, w0, w1, w2, offset)

                # Verts past the end of the loft copy the nearest ring vert's displacement dampened by the falloff.
                for bv, (dv, drest, bv_rest, damp) in beyond_loft.items():
                    if bv in sym_all: continue
                    bv.co = bv_rest + (dv.co - drest) * damp

                # IDW fallback for non-ring verts with no loft coverage.
                if bary_fallback_coords:
                    fallback_sym = {v for v in sym_all if v in bary_fallback_coords}
                    twist_apply_blend_axis(active_rings, bary_fallback_coords,
                                           fallback_sym, cd['sym_axes'],
                                           mw, mwi, deg,
                                           retain_shape=self.retain_shape,
                                           vert_weights=cd.get('falloff_non_ring_weights'))

                # Symmetry clamp for all non-ring sym verts.
                for v in sym_all:
                    if mx: v.co.x = 0.0
                    if my: v.co.y = 0.0
                    if mz: v.co.z = 0.0
            else:
                # No complete rings at all (plain non-loop selection).
                # Fall back to per-ring rotation / retain_segments so verts move.
                for rd in broken_rings:
                    segs = rd['retain_segments'] if self.retain_shape else None
                    rvw  = rd.get('vert_weights')
                    if rvw is not None:
                        twist_apply(bm, em, mw, mwi,
                                    rd['initial_coords'], rd['sym_verts'], rd['sym_axes'],
                                    rd['normal'], rd['center'], deg,
                                    loop_params=None, retain_segments=segs,
                                    finalize=False, vert_weights=rvw)
                    else:
                        deg_ring = deg * rd.get('weight', 1.0)
                        twist_apply(bm, em, mw, mwi,
                                    rd['initial_coords'], rd['sym_verts'], rd['sym_axes'],
                                    rd['normal'], rd['center'], deg_ring,
                                    loop_params=None, retain_segments=segs,
                                    finalize=False)
                # BFS non-ring verts: no reference rings so keep original position.

        bm.normal_update()
        bmesh.update_edit_mesh(em, loop_triangles=False)

    def execute(self, context):
        bm, em = get_bmesh_emesh(context)
        sel_verts = [v for v in bm.verts if v.select]
        if len(sel_verts) < 3:
            return {'CANCELLED'}
        mw  = context.edit_object.matrix_world.copy()
        mwi = mw.inverted()
        falloff_distances = None
        if self.use_proportional_edit:
            falloff_distances = get_falloff_verts(sel_verts, mw, self.proportional_distance, self.proportional_falloff)
        component_data = self.get_component_data(context, sel_verts, mw, falloff_distances=falloff_distances)
        if not component_data:
            return {'CANCELLED'}
        self.run_apply(bm, em, mw, mwi, component_data)
        return {'FINISHED'}

    def invoke(self, context, event):
        bm, em = get_bmesh_emesh(context)
        sel_verts = [v for v in bm.verts if v.select]
        if len(sel_verts) < 3:
            return {'CANCELLED'}
        self._bm        = bm
        self._em        = em
        self._mw        = context.edit_object.matrix_world.copy()
        self._mwi       = self._mw.inverted()
        self._sel_verts = sel_verts
        self._ts = context.tool_settings
        self._sel_center_world = self._mw @ (sum((v.co for v in sel_verts), Vector()) / len(sel_verts))
        ts = self._ts
        falloff_distances = None
        if ts.use_proportional_edit:
            falloff_distances = get_falloff_verts(sel_verts, self._mw, ts.proportional_distance, ts.proportional_edit_falloff)
        self._component_data = self.get_component_data(context, sel_verts, self._mw, falloff_distances=falloff_distances)
        if not self._component_data:
            return {'CANCELLED'}
        self._initial_mouse_x = event.mouse_x
        self.twist_angle = 0.0
        self._highlight_add(context)
        if context.area:
            context.area.header_text_set(self.header_modal_text())
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def apply(self, context):
        self.run_apply(self._bm, self._em, self._mw, self._mwi, self._component_data)
        if context.area:
            context.area.header_text_set(self.header_modal_text())

    def draw_highlights(self, context):
        if context.tool_settings.use_proportional_edit:
            try:
                from bpy_extras.view3d_utils import location_3d_to_region_2d
                from ..common.drawing import Drawing
                from ...addon_common.common.maths import Color
                from ...addon_common.common import gpustate
                center_2d = location_3d_to_region_2d(context.region, context.region_data, self._sel_center_world)
                if center_2d is not None:
                    view_matrix  = context.region_data.view_matrix
                    right_vector = Vector(view_matrix[0][:3]).normalized()
                    prop_dist = context.tool_settings.proportional_distance
                    radius_2d = location_3d_to_region_2d(
                        context.region, context.region_data,
                        self._sel_center_world + right_vector * prop_dist / 2)
                    if radius_2d is not None:
                        radius = (radius_2d - center_2d).length
                        grid  = context.preferences.themes[0].view_3d.grid
                        color = Color((grid[0] - 20/255, grid[1] - 20/255, grid[2] - 20/255, 1.0))
                        gpustate.blend('ALPHA')
                        Drawing.draw2D_smooth_circle(context, center_2d, radius, color, width=1)
                        gpustate.blend('NONE')
            except Exception as e:
                print(f"twist: proportional circle draw failed: {e}")

        if not DRAW_DEBUG_RINGS:
            return
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
                    Drawing.draw_loop_highlight(context, set(rd['initial_coords'].keys()),
                                                self._mw, color, skip_verts=frozenset())
        except Exception as e:
            print(f"twist: ring highlight draw failed: {e}")

    def _highlight_add(self, context):
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_highlights, (context,), 'WINDOW', 'POST_PIXEL')
        if context.area:
            context.area.tag_redraw()

    def _highlight_remove(self):
        h = getattr(self, '_draw_handle', None)
        if h is not None:
            bpy.types.SpaceView3D.draw_handler_remove(h, 'WINDOW')
            self._draw_handle = None

    def release(self):
        ''' Drop the draw handler and every BMesh reference while the bmesh is still alive. '''
        try:
            self._highlight_remove()
        finally:
            self._bm = None
            self._em = None
            self._sel_verts = []
            self._component_data = []

    def cancel(self, context):
        # this operator has its own modal loop other than RFOperator's, so it needs its own cancel()
        self.release()
        if context.area:
            context.area.header_text_set(None)

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            delta_px = event.mouse_x - self._initial_mouse_x
            self.twist_angle = math.radians(delta_px * TWIST_SENSITIVITY)
            self.apply(context)
            return {'RUNNING_MODAL'}
        if event.type == 'R' and event.value == 'PRESS':
            self.retain_shape = not self.retain_shape
            self.apply(context)
            return {'RUNNING_MODAL'}
        if event.type == 'O' and event.value == 'PRESS':
            self._ts.use_proportional_edit = not self._ts.use_proportional_edit
            self.rebuild_component_data(context)
            self.apply(context)
            if context.area:
                context.area.header_text_set(self.header_modal_text())
            return {'RUNNING_MODAL'}
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and self._ts.use_proportional_edit:
            if event.type == 'WHEELUPMOUSE':
                self._ts.proportional_distance *= 0.90
            else:
                self._ts.proportional_distance /= 0.90
            self.rebuild_component_data(context)
            self.apply(context)
            if context.area:
                context.area.header_text_set(self.header_modal_text())
            return {'RUNNING_MODAL'}
        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            ts = self._ts
            self.use_proportional_edit = ts.use_proportional_edit
            self.proportional_distance = ts.proportional_distance
            self.proportional_falloff  = ts.proportional_edit_falloff
            self.release()
            if context.area:
                context.area.header_text_set(None)
            return {'FINISHED'}
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            for cd in self._component_data:
                for rd in cd['ring_groups']:
                    for v, co0 in rd['initial_coords'].items():
                        v.co = co0.copy()
                for v, co0 in cd['bfs_non_ring_coords'].items():
                    v.co = co0.copy()
            self._bm.normal_update()
            bmesh.update_edit_mesh(self._em, loop_triangles=False)
            self.release()
            if context.area:
                context.area.header_text_set(None)
            return {'CANCELLED'}
        return {'PASS_THROUGH'}
