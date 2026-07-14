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

import colorsys
import hashlib
import math

import bpy
import numpy as np

from ..common.maths import (
    diffuse_graph_fields, diffusion_iters_for_radius, get_face_adjacency,
)
from ..common.operator import RFOperator_Execute

'''
Segment Mesh: seam-energy watershed segmentation (auto-remesher phase 1,
prototyped 2026-07 in dev/autoremesh_prototypes/gate1_features.py).

The mesh splits into regions whose boundaries follow ridges, crevices, and
sharp edges — the way a human would carve it:

 1. FACE-NATIVE FIELDS: a smoothed-normal ladder and a scale-adaptive signed
    cavity field are diffused over the FACE adjacency graph, seeded from raw
    triangle normals and centroids. The primary measurements never pass
    through a vertex average (a seam face's verts straddle the seam and
    blend both flanks, diluting exactly the signal this keys on).
 2. PAIRWISE SEAM ENERGY: for every shared edge, the turn RATE of the
    smoothed normals plus the cavity step rates per unit center distance —
    max of median-normalized channels. Local and crisp; no blobby field.
 3. WATERSHED: connected areas of low seam energy become seeds (skipping
    those below the size gate); regions grow by ascending waterline (energy
    decides claim order, never region ordering), never across a sharp raw
    dihedral, never into each other — fronts collide mid-seam. Still-
    unclaimed quiet components that outgrow the size gate while remaining
    unreached by any front (real seams isolate them) seed LATE; sharp-edge-
    isolated pockets become their own regions at the end.

Region count follows the seed threshold; cleanliness follows the size gate —
one job per dial, both editable in the redo panel.
'''

SHARP_ANGLE_DEG = 25.0            # lower wall tier: needs corroboration
WALL_ANGLE_DEG = 60.0             # upper wall tier: unconditional
WALL_CORROB_DEG = 4.0             # smoothed-normal angle confirming a wall
CAVITY_FRACS = (0.25, 0.35, 0.5, 0.7, 1.0, 1.4)
TURN_FRACS = (0.25, 1.0, 2.5)     # smoothed-normal ladder for turn channels
K_CAP = 400
GROWTH_STAGES = 8
CREST_VETO_FACTOR = 3.0           # band p90 >= this x interface median: veto
CREST_BAND_FRAC = 0.5             # merge-veto band depth, x feature scale


def get_mesh_triangle_arrays(me):
    ''' Triangulated numpy view of a mesh datablock via its loop triangles
        (no bmesh needed): (verts (V,3), tris (T,3) vert indices, per-tri
        loop indices (T,3) for writing corner-domain attributes). '''
    me.calc_loop_triangles()
    nv = len(me.vertices)
    co = np.empty(nv * 3)
    me.vertices.foreach_get('co', co)
    co = co.reshape(nv, 3)
    nt = len(me.loop_triangles)
    tris = np.empty(nt * 3, dtype=np.int64)
    me.loop_triangles.foreach_get('vertices', tris)
    tris = tris.reshape(nt, 3)
    lt_loops = np.empty(nt * 3, dtype=np.int64)
    me.loop_triangles.foreach_get('loops', lt_loops)
    return co, tris, lt_loops.reshape(nt, 3)


def compute_energy(co, tris, feature_scale):
    ''' Stage 1 — everything up to the threshold decision: face-native
        fields, pairwise seam energy, floor normalization, sharp walls and
        adjacency. Depends only on the mesh and the feature scale, so the
        operator caches it across redo-panel tweaks of the seed threshold
        and size gate (the expensive diffusion ladders live here). '''
    nF = len(tris)
    v0, v1, v2 = co[tris[:, 0]], co[tris[:, 1]], co[tris[:, 2]]
    cross = np.cross(v1 - v0, v2 - v0)
    cl = np.maximum(np.linalg.norm(cross, axis=1), 1e-30)
    t_normals = cross / cl[:, None]
    t_areas = 0.5 * cl
    t_centers = (v0 + v1 + v2) / 3.0

    fa, fb, everts = get_face_adjacency(tris, return_everts=True)
    dctr = np.maximum(np.linalg.norm(t_centers[fa] - t_centers[fb], axis=1),
                      1e-12)
    mean_step = float(dctr.mean())

    # --- face-native fields ---
    # smoothed-normal ladder: the fine rung feeds the cavity projection and
    # crisp seams; the coarse rungs are what let LARGE soft folds read at
    # all — diffusion cancels oscillatory bump normals (up-then-down nets
    # to zero) while a fold's net turn survives, so a gentle large-radius
    # ridge stands out once the bumps are smoothed away instead of being
    # buried under their much higher local curvature
    ns_ladder = {}
    k_ladder = {}
    ns = t_normals.copy()
    k_done = 0
    for frac in TURN_FRACS:
        k = diffusion_iters_for_radius(frac * feature_scale, mean_step,
                                        K_CAP)
        k_ladder[frac] = k
        if k > k_done:
            ns = diffuse_graph_fields(ns, fa, fb, nF, k - k_done)
            k_done = k
        ns_ladder[frac] = ns / np.maximum(
            np.linalg.norm(ns, axis=1, keepdims=True), 1e-30)
    nsf = ns_ladder[TURN_FRACS[0]]

    def cavity(fracs):
        # scale-adaptive signed cavity: per-rung DC removal (a limb's own
        # convexity is not a ridge line) + physical gamma=1 normalization,
        # signed argmax across the ladder
        pd = t_centers.copy()
        k_done = 0
        best = np.zeros(nF)
        best_mag = np.zeros(nF)
        for frac in fracs:
            k = diffusion_iters_for_radius(frac * feature_scale, mean_step,
                                            K_CAP)
            if k > k_done:
                pd = diffuse_graph_fields(pd, fa, fb, nF, k - k_done)
                k_done = k
            h = ((t_centers - pd) * nsf).sum(axis=1)
            # the DC window must stay 4x the rung RADIUS (16x iters) even
            # when the rung hits K_CAP — clamping both to the same ceiling
            # made background == signal at coarse rungs, cancelling exactly
            # the broad folds those rungs exist to catch (banana, 2026-07-13)
            h_bg = diffuse_graph_fields(h[:, None], fa, fb, nF,
                            16 * k)[:, 0]
            r = (h - h_bg) / frac
            m = np.abs(r) > best_mag
            best[m] = r[m]
            best_mag[m] = np.abs(r[m])
        return best

    hm = cavity(CAVITY_FRACS)
    hf = cavity(CAVITY_FRACS[:1])

    def mednz(x):
        a = x[x > 0]
        return max(float(np.median(a)) if len(a) else 0.0, 1e-30)

    # --- pairwise seam energy ---
    # turn channels are DC-REMOVED like the cavity rungs (tentacle lesson,
    # 2026-07-13): raw turn rate is |curvature|, which lights up an entire
    # blob/sphere as a plateau (violating the sphere test) and buries its
    # interior's quiet — on blobby meshes the interiors then overlap the
    # saddle crests and no seed threshold separates them. Subtracting each
    # rung's diffused background turn keeps only curvature ANOMALIES:
    # folds fire, constant-curvature caps read ~0.
    turns = []
    for frac in TURN_FRACS:
        nsl = ns_ladder[frac]
        t_e = np.arccos(np.clip((nsl[fa] * nsl[fb]).sum(1), -1, 1)) / dctr
        t_f = np.zeros(nF)
        cnt = np.zeros(nF)
        np.add.at(t_f, fa, t_e)
        np.add.at(t_f, fb, t_e)
        np.add.at(cnt, fa, 1.0)
        np.add.at(cnt, fb, 1.0)
        t_bg = diffuse_graph_fields(
            (t_f / np.maximum(cnt, 1.0))[:, None], fa, fb, nF,
            16 * k_ladder[frac])[:, 0]
        # normalize the anomaly against the mesh's typical RAW turn — the
        # residual's own positive-median is near-zero noise on smooth
        # meshes and normalizing by it amplified that noise to order 1
        # (banana facets fragmented, 2026-07-13)
        turns.append(np.maximum(t_e - 0.5 * (t_bg[fa] + t_bg[fb]), 0.0)
                     / mednz(t_e))
    cavm = np.abs(hm[fa] - hm[fb]) / dctr
    cavf = np.abs(hf[fa] - hf[fb]) / dctr
    # cavity CREST channel (banana lesson): a broad soft fold is a smooth
    # BAND of cavity residual — its cross-edge steps are tiny (spread over
    # the band) and its turn rate matches the body's own curvature, so no
    # rate channel ever sees it. The field VALUE does: per-rung DC removal
    # already subtracted the body's convexity, so the residual peaks on the
    # fold line itself and watershed fronts collide at the crest.
    cavv = np.maximum(np.abs(hm[fa]), np.abs(hm[fb]))

    w = np.maximum.reduce(turns
                          + [cavm / mednz(cavm), cavf / mednz(cavf),
                             cavv / mednz(cavv)])
    E_f = np.zeros(nF)
    np.maximum.at(E_f, fa, w)
    np.maximum.at(E_f, fb, w)
    # FLOOR-NORMALIZE (banana lesson, 2026-07-12): quiet background surface
    # reads ~1.0 on any mesh — the median is stable across meshes because
    # the channels are themselves median-normalized. The seed threshold is
    # an absolute multiple of this floor; anchoring to p98 made the dial
    # hostage to the single sharpest feature on the mesh (the hand-tuned
    # good settings on scorpion/boot sat at 0.49x/0.46x median while the
    # same dial value landed at 1.25x median on the banana and flooded its
    # soft ridges).
    floor = max(float(np.median(E_f)), 1e-30)
    E_f /= floor
    w /= floor

    # TWO-TIER WALLS (2026-07-13): raw dihedral >= WALL_ANGLE_DEG is a
    # wall unconditionally (authored/structural edges — also keeps
    # low-poly meshes sane, where sub-feature smoothing homogenizes all
    # normals and would erase a cube's 90-deg edges); the 25-60 deg band,
    # where decimation slivers and scan crumple live, must be CORROBORATED
    # by the smoothed-normal field (a real crease survives 0.25x-scale
    # smoothing, a sliver doesn't). The raw-25-only rule shattered scans
    # into thousands of pockets (tentacle: 9.1% sharp -> 2629 cells).
    # Stray one-off steep edges are harmless: growth floods around an
    # isolated wall edge — only closed wall rings isolate.
    cos_raw = (t_normals[fa] * t_normals[fb]).sum(1)
    cos_sm = (nsf[fa] * nsf[fb]).sum(1)
    sharp = (cos_raw < math.cos(math.radians(WALL_ANGLE_DEG))) \
        | ((cos_raw < math.cos(math.radians(SHARP_ANGLE_DEG)))
           & (cos_sm < math.cos(math.radians(WALL_CORROB_DEG))))
    adj_ns = [[] for _ in range(nF)]
    for i in range(len(fa)):
        if sharp[i]:
            continue
        a, b = int(fa[i]), int(fb[i])
        we = float(w[i])
        adj_ns[a].append((b, we))
        adj_ns[b].append((a, we))
    order_f = np.argsort(E_f, kind='stable')
    return dict(E_f=E_f, adj_ns=adj_ns, order_f=order_f, t_areas=t_areas,
                fa=fa, fb=fb, w=w, sharp=sharp, everts=everts,
                mean_step=mean_step,
                cav_multi=hm, cav_fine=hf, normals_fine=nsf,
                normals_coarse=ns_ladder[TURN_FRACS[-1]])


def watershed(energy, feature_scale, seed_threshold, seed_area):
    ''' Stage 2 — PERSISTENCE watershed (round 36; replaces staged
        flooding + timed late seeding + the pocket pass). Initial seeds:
        quiet connected components clearing the size gate, as before.
        Then ONE ascending pass over all non-wall edges (argsort — the
        waterline rises continuously, energy alone decides claim order,
        no heap): union-find pools grow; when an unclaimed pool meets a
        seeded one it is absorbed UNLESS it is a persistent basin — its
        lowest face dips at least `margin` (= seed_threshold) below the
        connecting pass and it clears the size gate — in which case it
        seeds instead and the pass edge becomes a boundary. Seeded pools
        never union: fronts collide mid-pass. Race-free by construction:
        assignment depends only on the landscape, so a fragment can
        never straddle a seam whose rim is higher than its interior —
        interior speckle makes high POINTS, not high RIMS, and a spike
        with no enclosed dip behind it can neither seed nor leak.
        Wall-isolated pockets fall out as never-connected pools.
        Returns (face_labels, initial seed labels, region count). '''
    E_f = energy['E_f']
    adj_ns = energy['adj_ns']
    t_areas = energy['t_areas']
    fa, fb = energy['fa'], energy['fb']
    w, sharp = energy['w'], energy['sharp']
    nF = len(E_f)
    thr = seed_threshold
    margin = seed_threshold
    min_seed_a = seed_area * feature_scale ** 2

    parent = np.arange(nF)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    minE = E_f.astype(np.float64).copy()   # per-root lowest face energy
    area = t_areas.astype(np.float64).copy()
    slab = np.full(nF, -1, dtype=np.int64)  # per-root seed label
    nxt = 0

    # initial seeds: quiet components clearing the gate (unchanged rule)
    seeds0 = np.full(nF, -1, dtype=np.int64)
    quiet = E_f < thr
    visited = np.zeros(nF, bool)
    for s in np.nonzero(quiet)[0]:
        s = int(s)
        if visited[s]:
            continue
        comp = [s]
        visited[s] = True
        stack = [s]
        while stack:
            f = stack.pop()
            for nb, _we in adj_ns[f]:
                if quiet[nb] and not visited[nb]:
                    visited[nb] = True
                    comp.append(nb)
                    stack.append(nb)
        if float(t_areas[comp].sum()) < min_seed_a:
            continue
        r0 = find(comp[0])
        for f in comp[1:]:
            rf = find(f)
            if rf != r0:
                parent[rf] = r0
                minE[r0] = min(minE[r0], minE[rf])
                area[r0] += area[rf]
        slab[r0] = nxt
        seeds0[comp] = nxt
        nxt += 1

    def qualifies(r, we):
        return we - minE[r] >= margin and area[r] >= min_seed_a

    def absorb(dst, src):
        parent[src] = dst
        minE[dst] = min(minE[dst], minE[src])
        area[dst] += area[src]

    # the ascending waterline: one sorted pass, persistence decides seeds
    for ei in np.argsort(w, kind='stable'):
        ei = int(ei)
        if sharp[ei]:
            continue
        a, b = find(int(fa[ei])), find(int(fb[ei]))
        if a == b:
            continue
        we = float(w[ei])
        sa, sb = slab[a] >= 0, slab[b] >= 0
        if sa and sb:
            continue                     # two fronts collide: boundary
        if not sa and not sb:
            # two unclaimed pools meet: the deeper qualifies first (its
            # dip is at least as large); if both seed, this pass is a
            # boundary; if one seeds, the other is absorbed or merged
            lo, hi = (a, b) if minE[a] <= minE[b] else (b, a)
            if qualifies(lo, we):
                slab[lo] = nxt
                nxt += 1
                if qualifies(hi, we):
                    slab[hi] = nxt
                    nxt += 1
                    continue
                absorb(lo, hi)
            elif qualifies(hi, we):
                slab[hi] = nxt
                nxt += 1
                absorb(hi, lo)
            else:
                absorb(lo, hi)
            continue
        seeded, uns = (a, b) if sa else (b, a)
        if qualifies(uns, we):
            slab[uns] = nxt              # persistent hidden basin: seed,
            nxt += 1                     # and the pass is a boundary
            continue
        absorb(seeded, uns)

    # label faces by root; never-connected pools (wall pockets, isolated
    # islands) become their own regions
    lab = np.empty(nF, dtype=np.int64)
    for f in range(nF):
        r = find(f)
        if slab[r] < 0:
            slab[r] = nxt
            nxt += 1
        lab[f] = slab[r]
    lab = np.unique(lab, return_inverse=True)[1]
    return lab, seeds0, int(lab.max()) + 1


def interface_saliency(idxs, everts, w, sharp):
    ''' Coherence saliency of one region-pair interface: order its edges
        into chains via shared mesh verts, take a 5-wide windowed median
        of the crossing energies along each chain (sharp edges read as
        walls), and return the 25th percentile — the strength of the
        weakest COHERENT stretch. A soft true seam is moderately elevated
        continuously; fragment noise alternates spikes and gaps, so its
        windowed profile collapses. AUC 0.800 vs the painted boot GT,
        where the plain median (level-only) scores 0.737. '''
    if len(idxs) < 5:
        iw = w[idxs].copy()
        iw[sharp[idxs]] = np.inf
        return float(np.median(iw))
    SENT = 1e3
    vadj = {}
    for k, i in enumerate(idxs):
        for v in everts[i]:
            vadj.setdefault(int(v), []).append(k)
    used = set()
    winmeds = []
    for k0 in range(len(idxs)):
        if k0 in used:
            continue
        chain = [k0]
        used.add(k0)
        for side, v0 in enumerate(everts[idxs[k0]]):
            v = int(v0)
            while True:
                nxts = [e for e in vadj.get(v, []) if e not in used]
                if not nxts:
                    break
                e = nxts[0]
                used.add(e)
                if side == 0:
                    chain.insert(0, e)
                else:
                    chain.append(e)
                ev = everts[idxs[e]]
                v = int(ev[0]) if int(ev[1]) == v else int(ev[1])
        prof = np.array([w[idxs[k]] if not sharp[idxs[k]] else SENT
                         for k in chain])
        if len(prof) >= 5:
            winmeds.extend(np.median(prof[max(0, j - 2):j + 3])
                           for j in range(len(prof)))
        else:
            winmeds.extend(prof.tolist())
    return float(np.percentile(winmeds, 25))


def merge_regions(labels, energy, feature_scale, merge_below):
    ''' Stage 3 — boundary-saliency merge with crest veto. The staged
        waterlines carve texture-speckled basins into fragments that meet
        at speckle-level boundaries, while real seams/saddles collide at
        high energy: dissolve region pairs whose shared interface's MEDIAN
        crossing energy sits below `merge_below` (floor units). Guards:
        pairs whose interface is substantially sharp never merge, and the
        CREST VETO — if a coherent high-energy crest runs through the band
        around a quiet interface, the territorial line is probably
        displaced from a nearby seam (a front spilled through a gap), so
        the merge is blocked instead of compounding the spill. Iterates
        until stable. Returns (merged labels, region count). '''
    n0 = int(labels.max()) + 1
    if merge_below <= 0.0 or n0 < 2:
        return labels, n0
    E_f = energy['E_f']
    fa, fb = energy['fa'], energy['fb']
    w, sharp = energy['w'], energy['sharp']
    adj_ns = energy['adj_ns']
    band_steps = max(1, round(CREST_BAND_FRAC * feature_scale
                              / max(energy['mean_step'], 1e-12)))
    parent = np.arange(n0)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _round in range(24):
        root_of = np.array([find(i) for i in range(n0)])
        ra, rb = root_of[labels[fa]], root_of[labels[fb]]
        pairs = {}
        for i in np.nonzero(ra != rb)[0]:
            i = int(i)
            key = (int(ra[i]), int(rb[i]))
            if key[0] > key[1]:
                key = (key[1], key[0])
            pairs.setdefault(key, []).append(i)
        merged_any = False
        for (a, b), idxs in pairs.items():
            if find(a) != a or find(b) != b:
                continue    # stats stale after an earlier union; next round
            # COHERENCE saliency (2026-07-13, AUC-selected): the weakest
            # coherent stretch of the interface profile — separates soft
            # continuous true seams from spike-and-gap fragment noise
            # where any level statistic overlaps. Sharp edges read as
            # walls inside the profile
            m = interface_saliency(idxs, energy['everts'], w, sharp)
            if not np.isfinite(m) or m >= merge_below:
                continue
            # crest veto: BFS a band around the interface within A+B; a
            # high-energy crest in the band means this quiet line likely
            # runs beside a real seam that one region spilled across
            band = set()
            for i in idxs:
                band.add(int(fa[i]))
                band.add(int(fb[i]))
            frontier = set(band)
            for _ in range(band_steps):
                nxt = set()
                for f in frontier:
                    for nb, _we in adj_ns[f]:
                        if nb not in band \
                                and root_of[labels[nb]] in (a, b):
                            band.add(nb)
                            nxt.add(nb)
                frontier = nxt
                if not frontier:
                    break
            crest = float(np.percentile(E_f[list(band)], 90))
            if crest >= CREST_VETO_FACTOR * max(1.0, m):
                continue
            parent[b] = a
            merged_any = True
        if not merged_any:
            break
    root_of = np.array([find(i) for i in range(n0)])
    merged = np.unique(root_of[labels], return_inverse=True)[1]
    return merged, int(merged.max()) + 1


def segment_faces(co, tris, feature_scale, seed_threshold, seed_area):
    ''' Full pipeline (energy stage + watershed) for one-shot callers.
        Returns (face_labels, per-face seam energy, region count, extras). '''
    energy = compute_energy(co, tris, feature_scale)
    lab, seeds0, n = watershed(energy, feature_scale, seed_threshold,
                                seed_area)
    return lab, energy['E_f'], n, gather_extras(energy, seeds0)


def gather_extras(energy, seeds0):
    return dict(cav_multi=energy['cav_multi'], cav_fine=energy['cav_fine'],
                normals_fine=energy['normals_fine'],
                normals_coarse=energy['normals_coarse'], seeds=seeds0,
                fa=energy['fa'], fb=energy['fb'])


def palette(n=96):
    ''' Deterministic label palette: golden-ratio hue stepping with varied
        saturation and value tiers — mutually distinguishable at hundreds
        of regions (a constant-sat/val hue wheel collides constantly). '''
    cols = np.empty((n, 4))
    for i in range(n):
        h = (i * 0.61803398875) % 1.0
        s = 0.50 + 0.45 * ((i * 0.379) % 1.0)
        v = 0.45 + 0.50 * ((i * 0.283) % 1.0)
        cols[i] = (*colorsys.hsv_to_rgb(h, s, v), 1.0)
    return cols


def region_color_indices(labels, fa, fb, pal):
    ''' Per-region palette index, assigned greedily (largest region first)
        so ADJACENT regions always get well-separated colors: a region
        keeps its default slot unless that lands too close to an already-
        colored neighbor, in which case it picks among the most distant
        palette entries (varied by region id to keep global variety). '''
    n_regions = int(labels.max()) + 1
    la, lb = labels[fa], labels[fb]
    m = (la != lb) & (la >= 0) & (lb >= 0)
    adj = [set() for _ in range(n_regions)]
    for a, b in zip(la[m], lb[m]):
        adj[int(a)].add(int(b))
        adj[int(b)].add(int(a))
    rgb = pal[:, :3]
    idx = np.full(n_regions, -1, dtype=np.int64)
    for r in np.argsort(-np.bincount(labels[labels >= 0],
                                     minlength=n_regions)):
        r = int(r)
        taken = [int(idx[nb]) for nb in adj[r] if idx[nb] >= 0]
        base = r % len(pal)
        if not taken:
            idx[r] = base
            continue
        d = np.linalg.norm(rgb[:, None, :] - rgb[None, taken, :],
                           axis=2).min(axis=1)
        if d[base] >= 0.35:
            idx[r] = base
        else:
            best = np.argsort(-d)[:8]
            idx[r] = int(best[r % len(best)])
    return idx


def write_corner_colors(me, tri_loops, name, fcol):
    # CORNER domain — every corner takes its face's color, so face-native
    # fields render as crisp per-face patches with no vertex blur
    attr = me.color_attributes.get(name)
    if attr is not None and attr.domain != 'CORNER':
        me.color_attributes.remove(attr)
        attr = None
    if attr is None:
        attr = me.color_attributes.new(name, 'FLOAT_COLOR', 'CORNER')
    colors = np.full((len(me.loops), 4), 0.15)
    colors[:, 3] = 1.0
    colors[tri_loops.ravel()] = np.repeat(fcol, 3, axis=0)
    attr.data.foreach_set('color', colors.ravel())
    return attr


def label_colors(labels, pal):
    fcol = np.full((len(labels), 4), 0.15)
    fcol[:, 3] = 1.0
    m = labels >= 0
    fcol[m] = pal[labels[m] % len(pal)]
    return fcol


def diverging_colors(vals):
    # signed field: blue = concave, red = convex, gray mid at zero
    scale = max(float(np.percentile(np.abs(vals), 98)), 1e-30)
    t = np.clip(0.5 + vals / (2.0 * scale), 0, 1)
    return np.stack([t, 0.15 + 0.2 * (1 - np.abs(2 * t - 1)), 1 - t,
                     np.ones_like(t)], axis=1)


def write_attributes(me, tri_loops, face_labels, seam_energy_f, tris,
                      extras, preview='Regions'):
    pal = palette()

    def region_colors(labels):
        # adjacency-aware colors when the face-pair arrays are available,
        # so touching regions never share a look-alike color
        if 'fa' in extras and labels.min() >= 0:
            idx = region_color_indices(labels, extras['fa'], extras['fb'],
                                       pal)
            fcol = np.empty((len(labels), 4))
            fcol[:] = pal[idx[labels]]
            return fcol
        return label_colors(labels, pal)

    attr = write_corner_colors(me, tri_loops, 'Regions',
                                region_colors(face_labels))
    if 'labels_raw' in extras:
        write_corner_colors(me, tri_loops, 'Regions Raw',
                            region_colors(extras['labels_raw']))
    write_corner_colors(me, tri_loops, 'Seeds',
                         label_colors(extras['seeds'], pal))
    write_corner_colors(me, tri_loops, 'Cavity Multi',
                         diverging_colors(extras['cav_multi']))
    write_corner_colors(me, tri_loops, 'Cavity Fine',
                         diverging_colors(extras['cav_fine']))
    for name, ns in (('Smoothed Normals', extras['normals_fine']),
                     ('Smoothed Normals Coarse', extras['normals_coarse'])):
        ncol = np.concatenate([ns * 0.5 + 0.5,
                               np.ones((len(ns), 1))], axis=1)
        write_corner_colors(me, tri_loops, name, ncol)
    # 'Seam Energy': POINT domain blue->red (max incident face energy).
    # The energy is floor-normalized (quiet background = 1.0), so a FIXED
    # 0-8x ramp makes the display comparable across meshes — a p98 ramp
    # let one sharp feature compress everything else to flat blue.
    ev = np.zeros(len(me.vertices))
    np.maximum.at(ev, tris.ravel(), np.repeat(seam_energy_f, 3))
    t = np.clip(ev / 8.0, 0, 1)
    vcol = np.stack([t, 0.15 + 0.2 * (1 - np.abs(2 * t - 1)), 1 - t,
                     np.ones_like(t)], axis=1)
    attr_e = me.color_attributes.get('Seam Energy')
    if attr_e is not None and attr_e.domain != 'POINT':
        me.color_attributes.remove(attr_e)
        attr_e = None
    if attr_e is None:
        attr_e = me.color_attributes.new('Seam Energy', 'FLOAT_COLOR',
                                         'POINT')
    attr_e.data.foreach_set('color', vcol.ravel())
    # viewport preview: selectable from the redo panel, since clicking the
    # attribute list in the Properties editor would dismiss the panel
    target = me.color_attributes.get(preview)
    me.color_attributes.active_color = target if target is not None else attr


# single-slot energy-stage cache: survives across redo-panel re-executes
# (threshold/gate tweaks), cleared on every fresh UI invocation. Holds
# detached numpy arrays only — safe across the undo rollbacks that redo
# performs between re-executes.
energy_cache = {}


class RFOperator_SegmentMesh(RFOperator_Execute):
    '''
    Segment the active mesh into regions whose boundaries follow ridges,
    crevices, and sharp edges (seam-energy watershed). Writes the 'Regions'
    color attribute plus diagnostic layers ('Seeds', 'Seam Energy',
    'Cavity Multi', 'Cavity Fine', 'Smoothed Normals', 'Smoothed Normals
    Coarse') for inspection. Runs on the mesh as-is (no modifiers, no
    decimation).
    '''
    bl_idname = 'retopoflow.segment_mesh'
    bl_label = 'Segment Mesh'
    bl_description = ('Segment the mesh into regions bounded by ridges, '
                      'crevices, and sharp edges')
    bl_options = {'REGISTER', 'UNDO'}

    seed_threshold: bpy.props.FloatProperty(
        name='Seed Threshold',
        description=('Areas below this multiple of the typical (median) '
                     'seam energy become region seeds — lower gives more '
                     'regions. 1.0 = the quiet-surface level of the mesh'),
        default=0.5, min=0.01, max=5.0, soft_max=2.0,
    )
    seed_area: bpy.props.FloatProperty(
        name='Seed Size Gate',
        description=('Minimum seed area in feature-scale² units. Smaller '
                     'quiet flecks are skipped at seeding but may still '
                     'seed later if the rising waterline grows them while '
                     'no region has reached them'),
        default=0.5, min=0.0, max=20.0,
    )
    merge_below: bpy.props.FloatProperty(
        name='Merge Below',
        description=('EXPERIMENTAL: dissolve region boundaries whose '
                     'median seam energy is below this multiple of the '
                     'typical surface energy. Soft true seams and fragment '
                     'noise overlap in energy level, so any nonzero value '
                     'trades real boundaries for cleanup — 0 (off) is the '
                     'safe default until a coherence-based criterion lands'),
        default=0.0, min=0.0, max=10.0, soft_max=4.0,
    )
    feature_scale: bpy.props.FloatProperty(
        name='Feature Scale',
        description=('Physical size of the features to segment by, in '
                     'object units. 0 = automatic (7x mean edge length)'),
        default=0.0, min=0.0,
    )
    preview: bpy.props.EnumProperty(
        name='Preview',
        description=('Which output layer to show in the viewport (sets the '
                     'active color attribute)'),
        items=[
            ('Regions', 'Regions', 'Final region labels (after merging)'),
            ('Regions Raw', 'Regions Raw',
             'Watershed regions before the merge pass'),
            ('Seeds', 'Seeds',
             'Initial seed components at the seed threshold, before growth'),
            ('Seam Energy', 'Seam Energy',
             'Floor-normalized seam energy (fixed 0-8x ramp)'),
            ('Cavity Multi', 'Cavity Multi',
             'Multi-scale signed cavity (blue concave, red convex)'),
            ('Cavity Fine', 'Cavity Fine',
             'Fine-scale signed cavity (blue concave, red convex)'),
            ('Smoothed Normals', 'Smoothed Normals',
             'Fine smoothed normals as RGB'),
            ('Smoothed Normals Coarse', 'Smoothed Normals Coarse',
             'Coarse smoothed normals as RGB'),
        ],
        default='Regions',
    )

    @classmethod
    def poll(cls, context):
        return context.active_object is not None \
            and context.active_object.type == 'MESH'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'seed_threshold')
        layout.prop(self, 'seed_area')
        layout.prop(self, 'merge_below')
        layout.prop(self, 'feature_scale')
        layout.prop(self, 'preview')

    def invoke(self, context, event):
        # a fresh UI invocation always recomputes; redo-panel re-executes
        # skip invoke and reuse the cached energy stage in execute()
        energy_cache.clear()
        return self.execute(context)

    def execute(self, context):
        me = context.active_object.data
        co, tris, tri_loops = get_mesh_triangle_arrays(me)
        if len(tris) < 4:
            self.report({'WARNING'}, 'Segment Mesh: mesh has too few faces')
            return {'CANCELLED'}
        scale = self.feature_scale
        if scale <= 0.0:
            d = co[tris[:, 0]] - co[tris[:, 1]]
            scale = 7.0 * float(np.linalg.norm(d, axis=1).mean())
        # the energy stage depends only on geometry + feature scale; the
        # geometry hash guards against stale reuse if the mesh changed
        # between scripted calls with the same counts
        key = (me.name, len(co), len(tris),
               hashlib.md5(co.tobytes()).hexdigest(), round(scale, 9))
        cached = energy_cache.get('key') == key
        if not cached:
            energy_cache.clear()
            energy_cache['energy'] = compute_energy(co, tris, scale)
            energy_cache['key'] = key
        energy = energy_cache['energy']
        # the watershed and merge results are cached too, so a preview-layer
        # change in the redo panel re-executes near-instantly
        ws_key = (self.seed_threshold, self.seed_area)
        if energy_cache.get('ws_key') != ws_key:
            energy_cache['ws'] = watershed(
                energy, scale, self.seed_threshold, self.seed_area)
            energy_cache['ws_key'] = ws_key
            energy_cache.pop('merge_key', None)
        labels_raw, seeds0, n_raw = energy_cache['ws']
        if energy_cache.get('merge_key') != self.merge_below:
            energy_cache['merged'] = merge_regions(
                labels_raw, energy, scale, self.merge_below)
            energy_cache['merge_key'] = self.merge_below
        labels, n_regions = energy_cache['merged']
        extras = gather_extras(energy, seeds0)
        extras['labels_raw'] = labels_raw
        write_attributes(me, tri_loops, labels, energy['E_f'], tris,
                         extras, preview=self.preview)
        me.update()
        self.report({'INFO'}, f'Segment Mesh: {n_regions} regions '
                              f'({n_raw} before merge, feature scale '
                              f'{scale:.4f}'
                              f'{", cached fields" if cached else ""})')
        return {'FINISHED'}
