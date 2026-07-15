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
    build_graph_pyramid, diffuse_graph_fields, diffuse_graph_fields_pyramid,
    get_face_adjacency,
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
CREST_WALK_DOM = 0.85             # walk face >= this x its transverse max
CREST_TURN_MIN_DEG = 1.0          # min raw bend, deg per scale of travel
CREST_NODE_STEP = 0.25            # trace-node spacing target, x scale
CREST_MARCH_STEP = 0.25           # marching step length, x scale
CREST_MARCH_KEEP = 0.35           # keep marching vs own median level
CREST_MARCH_COAST = 3             # tolerated consecutive bad probes
CREST_GROW_Q = 12                 # new band faces per curve-growth step
CREST_RATE_WIN = 0.02             # band area between rate checks, x scale^2
CREST_PATH_COST = 3.0             # off-crest penalty in band paths
CREST_PROFILE_X = 1.0             # transverse profile half-width, x rung
CREST_CLAIM_R = 0.35              # curve claim radius, x scale
CREST_SEED_SPACING = 1.0          # min seed separation, x scale
CREST_SEED_CAP = 512              # max marching seeds per polarity
CREST_FUSE_GAP = 1.0              # max fragment fusion gap, x scale
CREST_RELAX_ITERS = 6             # active-contour relaxation passes
CREST_CURVE_PEAK_MIN = 0.6        # min fraction of peaked profiles
CREST_CURVE_WIGGLE_MAX = 35.0     # max mean turning per point, deg
CREST_ELONG_MIN = 6.0             # length/width ratio that locks a line
CREST_LOCK_LEN = 0.5              # min length to lock, x scale
CREST_FAT_X = 1.75                # stop when width > this x own lock width
CREST_COLL_COS = 0.7              # collinearity cone for feature joins
CREST_MIN_LEN = 0.75              # minimum open-chain length, x scale
CREST_LOOP_MIN_FACES = 6          # minimum faces for a closed loop
CREST_CONE_COS = 0.5              # bridge-walk cone (~60 deg half-angle)
CREST_TENSOR_RAD_X = 1.0          # structure-tensor smoothing, x rung
CREST_TENSOR_PRE_X = 0.5          # field pre-smooth, x rung radius
CREST_ANISO_MIN = 0.15            # orientation coherence gate for lines
CREST_NMS_COS = 0.75              # across-cone: past the ~45 deg zigzag
CREST_STEP_COS = 0.3              # walker step alignment with line axis
CLUSTER_MAX_AREA_X = 4.0          # feature-blob size cap, x scale^2
CLUSTER_MIN_AREA_X = 0.25         # feature-blob size floor, x scale^2
CLUSTER_NORMAL_MIN = 0.6          # min |mean normal| of a feature blob
CLUSTER_MAX_FRACTION = 0.01       # blob size cap, x total surface area
CLUSTER_ISO_MIN = 0.3             # min 4*pi*A/P^2 (1 = circle) of a blob
CREST_CYCLE_BLOBS = False         # WiP: graph-cycle rings as blob source
SNAP_DIV_REF_DEG = 10.0           # ladder divergence for full snap budget


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
    # MULTIGRID (round 38): all large-radius smoothing runs on a Gaussian
    # pyramid of the face graph — the (radius/step)^2 fine-iteration
    # explosion becomes near-constant, and radii no longer saturate at an
    # iteration cap (K_CAP retired), so large Feature Scales stay honest
    # on dense meshes. Fine radii (< ~8 steps) remain exact.
    pyramid = build_graph_pyramid(fa, fb, t_areas, t_centers)

    def smooth(fields, radius):
        return diffuse_graph_fields_pyramid(fields, radius, fa, fb, nF,
                                            mean_step, pyramid)

    # smoothed-normal ladder: the fine rung feeds the cavity projection and
    # crisp seams; the coarse rungs are what let LARGE soft folds read at
    # all — diffusion cancels oscillatory bump normals (up-then-down nets
    # to zero) while a fold's net turn survives, so a gentle large-radius
    # ridge stands out once the bumps are smoothed away instead of being
    # buried under their much higher local curvature
    ns_ladder = {}
    for frac in TURN_FRACS:
        ns = smooth(t_normals, frac * feature_scale)
        ns_ladder[frac] = ns / np.maximum(
            np.linalg.norm(ns, axis=1, keepdims=True), 1e-30)
    nsf = ns_ladder[TURN_FRACS[0]]

    def cavity(fracs, collect=None):
        # scale-adaptive signed cavity: per-rung DC removal (a limb's own
        # convexity is not a ridge line) + physical gamma=1 normalization,
        # signed argmax across the ladder; the DC window is 4x the rung
        # RADIUS (the 16x-iteration convention, expressed as radius)
        best = np.zeros(nF)
        best_mag = np.zeros(nF)
        win = np.zeros(nF)
        for frac in fracs:
            pd = smooth(t_centers, frac * feature_scale)
            h = ((t_centers - pd) * nsf).sum(axis=1)
            h_bg = smooth(h[:, None], 4.0 * frac * feature_scale)[:, 0]
            r = (h - h_bg) / frac
            if collect is not None:
                collect.append(r)
            m = np.abs(r) > best_mag
            best[m] = r[m]
            best_mag[m] = np.abs(r[m])
            win[m] = frac
        return best, win

    # the LADDER itself is the crest tracer's substrate (per-curve rung
    # tracing): every feature lives at its own scale, and any per-face
    # argmax composite both starves narrow features of their rung and
    # jumps rungs mid-feature. hm remains the argmax for the energy
    # channels and displays; hf is exactly the finest rung.
    ladder = []
    hm, win_m = cavity(CAVITY_FRACS, collect=ladder)
    hf = ladder[0]
    ladder = np.stack(ladder)

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
        t_bg = smooth((t_f / np.maximum(cnt, 1.0))[:, None],
                      4.0 * frac * feature_scale)[:, 0]
        # normalize the anomaly against the mesh's typical RAW turn — the
        # residual's own positive-median is near-zero noise on smooth
        # meshes and normalizing by it amplified that noise to order 1
        # (banana facets fragmented, 2026-07-13)
        turns.append(np.maximum(t_e - 0.5 * (t_bg[fa] + t_bg[fb]), 0.0)
                     / mednz(t_e))
    cavm = np.abs(hm[fa] - hm[fb]) / dctr
    cavf = np.abs(hf[fa] - hf[fb]) / dctr
    # cavity CREST channel (banana lesson): a broad soft fold is a smooth
    # BAND of cavity residual whose steps and turn rate never see it; the
    # VALUE peaks on the fold line. NOTE (horse-mane round, probe-refereed):
    # steps localize on flanks for monopole features, but removing them
    # (v2) or sign-gating them (v3) LOWERED boot precision 0.95->0.93/0.92
    # — the steps SHARPEN wide value plateaus and pin front collisions.
    # Exact on-crest placement is the job of an explicit coarse-to-fine
    # refinement pass, not channel algebra.
    cavv = np.maximum(np.abs(hm[fa]), np.abs(hm[fb]))

    R = np.stack(turns + [cavm / mednz(cavm), cavf / mednz(cavf),
                          cavv / mednz(cavv)])
    w = R.max(axis=0)
    ch_e = R.argmax(axis=0)
    # per-edge DETECTION RADIUS (adaptive snap, round 43): the blur of
    # the winning channel bounds how far its placement can have drifted
    # — turn rungs at their own frac, cavity channels at the winning
    # rung of the multi ladder, fine cavity at the fine rung
    cav_rad_e = np.maximum(np.maximum(win_m[fa], win_m[fb]),
                           0.25) * feature_scale
    fine_rad = np.full(len(fa), 0.25 * feature_scale)
    edge_rad = np.choose(ch_e, [
        np.full(len(fa), TURN_FRACS[0] * feature_scale),
        np.full(len(fa), TURN_FRACS[1] * feature_scale),
        np.full(len(fa), TURN_FRACS[2] * feature_scale),
        cav_rad_e, fine_rad, cav_rad_e])
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
    # per-face snap budget: the detecting channel's blur radius (a priori
    # bound), shrunk where coarse and fine ladder normals AGREE — a
    # symmetric feature does not shift under blur, so its boundary should
    # barely move (a posteriori evidence)
    detect_rad = np.zeros(nF)
    m_ = w >= E_f[fa] * (1.0 - 1e-9)
    np.maximum.at(detect_rad, fa[m_], edge_rad[m_])
    m_ = w >= E_f[fb] * (1.0 - 1e-9)
    np.maximum.at(detect_rad, fb[m_], edge_rad[m_])
    div = np.arccos(np.clip((ns_ladder[TURN_FRACS[0]]
                             * ns_ladder[TURN_FRACS[-1]]).sum(1), -1, 1))
    div_f = np.clip(div / math.radians(SNAP_DIV_REF_DEG), 0.25, 1.0)
    snap_rad = np.maximum(detect_rad * div_f, 0.25 * feature_scale)

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
                snap_rad=snap_rad, pyramid=pyramid,
                mean_step=mean_step, t_centers=t_centers,
                t_normals=t_normals, verts=co, tris=tris,
                cav_multi=hm, cav_fine=hf, ladder=ladder,
                normals_fine=nsf,
                normals_coarse=ns_ladder[TURN_FRACS[-1]])


def harvest_line_faces(hs, bend_ok, adj_e, t_areas, t_centers,
                       feature_scale, nF):
    ''' PERIMETER-DESCRIPTOR harvest (round 52): the sweep contains the
        lines — a human watching Cavity Multi flood sees every one — so
        extraction quality lives entirely in the component descriptors.
        Bbox chord + area/chord measured GLOBAL straightness: a welt
        wrapping the heel stopped growing in chord while its area rose,
        read as "fattening", and died mid-line; a tread lattice grew in
        both bbox directions and read isotropic though it is thin at
        every point. A human judges LOCAL thinness, which for a surface
        region is the perimeter: width = 2*area/perimeter (mean local
        thickness, curvature-proof), length = perimeter/2. Both update
        incrementally in the union-find. A component LOCKS as a line
        when length >= CREST_LOCK_LEN x scale and length >=
        CREST_ELONG_MIN x width (cumulative shape ratio — no rate
        windows); it records its OWN width at lock, and STOPS when its
        width passes CREST_FAT_X x that personal baseline (the flanks
        arriving, measured against the line's own thinness at its own
        level). Curved lines, closed rings, and lattices all read
        correctly with no special cases. Union identity rules: two
        TRACING components join only when COLLINEAR (bbox axes + the
        centroid offset agree — crossings stay junctions, side-by-side
        parallels stay separate); a young pool always joins (its width
        contribution IS the stop signal) but is marked only when it
        lies along the line's axis; STOPPED never joins a live line.
        Perimeter caveat: contact accumulated between components that
        earlier REFUSED to union is not discounted if they later merge
        (rare; overestimates width, erring toward stopping sooner).
        bend_ok is the BENDING-REALITY gate: only faces whose smoothed
        normals actually turn may enter the sweep — DC-removal halos on
        flat faces beside sub-scale features carry cavity amplitude
        comparable to the features themselves (beveled cube: flat-
        interior |hm| p50 2.6e-2 vs 2.3e-2 on the bevels) but bend
        nothing (~0.2 deg vs several), and an elongated halo band
        otherwise locks as a ghost line.
        Returns the marked-face mask. '''
    lock_len = CREST_LOCK_LEN * feature_scale
    order = np.argsort(-hs, kind='stable')
    order = order[(hs[order] > 0.0) & bend_ok[order]]
    parent = np.full(nF, -1, dtype=np.int64)
    area, perim, bb_lo, bb_hi, csum, members = {}, {}, {}, {}, {}, {}
    state = {}                      # 0 young/blob, 1 tracing, 2 stopped
    w_lock = {}                     # width at lock, per tracing feature
    line = np.zeros(nF, bool)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def axis_of(r):
        d = bb_hi[r] - bb_lo[r]
        dl = float(np.linalg.norm(d))
        return d / dl if dl > 1e-12 else d

    def offset_dir(ra, rb):
        off = csum[rb] / area[rb] - csum[ra] / area[ra]
        ol = float(np.linalg.norm(off))
        return off / ol if ol > 1e-12 else None

    for f in order:
        f = int(f)
        parent[f] = f
        c = t_centers[f]
        a0 = float(t_areas[f])
        area[f], perim[f] = a0, 0.0
        bb_lo[f], bb_hi[f] = c.copy(), c.copy()
        csum[f] = c * a0
        members[f], state[f] = [f], 0
        r = f
        for nb, _ei in adj_e[f]:
            elen = float(np.linalg.norm(t_centers[nb] - t_centers[f]))
            if parent[nb] < 0:
                r = find(r)
                perim[r] += elen    # boundary toward inactive ground
                continue
            r2 = find(int(nb))
            r = find(r)
            if r2 == r:
                perim[r] -= elen    # edge became interior (nb side was
                continue            # counted at nb's activation)
            s1, s2 = state[r], state[r2]
            mark2 = None            # faces to mark if the union happens
            refuse = False
            if s1 == 1 and s2 == 1:
                ax1, ax2 = axis_of(r), axis_of(r2)
                off = offset_dir(r, r2)
                if off is None or abs(float(ax1 @ ax2)) < CREST_COLL_COS \
                        or abs(float(ax1 @ off)) < CREST_COLL_COS \
                        or abs(float(ax2 @ off)) < CREST_COLL_COS:
                    refuse = True   # junction or parallel: keep apart
            elif (s1, s2) in ((1, 2), (2, 1)):
                refuse = True       # a stopped feature never joins a line
            elif 1 in (s1, s2):
                # young pool joins a tracing line: mark it only if it
                # lies along the axis (the line's own continuation)
                rt, rp = (r, r2) if s1 == 1 else (r2, r)
                off = offset_dir(rt, rp)
                if off is not None and abs(float(axis_of(rt) @ off)) \
                        >= CREST_COLL_COS:
                    mark2 = list(members[rp])
            if refuse:
                perim[r] += elen    # boundary on both sides now
                continue
            # the surviving feature keeps the larger side's lock width
            wl1, wl2 = w_lock.get(r), w_lock.get(r2)
            if wl1 is not None and wl2 is not None:
                wl = wl1 if area[r] >= area[r2] else wl2
            else:
                wl = wl1 if wl1 is not None else wl2
            if len(members[r2]) > len(members[r]):
                r, r2 = r2, r
            parent[r2] = r
            w_lock.pop(r2, None)
            ck.pop(r2, None)
            if wl is not None:
                w_lock[r] = wl
            state[r] = max(state[r], state.pop(r2))
            area[r] += area.pop(r2)
            perim[r] = perim[r] + perim.pop(r2) - elen
            np.minimum(bb_lo[r], bb_lo.pop(r2), out=bb_lo[r])
            np.maximum(bb_hi[r], bb_hi.pop(r2), out=bb_hi[r])
            csum[r] = csum[r] + csum.pop(r2)
            members[r].extend(members.pop(r2))
            if mark2 is not None and state[r] == 1:
                line[mark2] = True
        r = find(f)
        if state[r] == 1:
            line[f] = True
        P = perim[r]
        if P > 1e-12:
            W = 2.0 * area[r] / P
            L = 0.5 * P
            if state[r] == 0:
                if L >= lock_len and L >= CREST_ELONG_MIN * W:
                    state[r] = 1
                    w_lock[r] = W
                    line[members[r]] = True
            elif state[r] == 1 and W > CREST_FAT_X * w_lock[r]:
                state[r] = 2
    return line


def trace_crest_lines(h, sign, bend_ok, adj_e, t_areas, t_centers,
                      t_normals, across, aniso, feature_scale, nF):
    ''' FIELD-FOLLOWING ridge tracing on a SIGNED field (crest lines
        v5): the growth-signature harvest supplies a per-feature support
        set (each line connected at its own level — no global floor);
        oriented NMS survivors within it SEED chains (strongest first);
        the walker then follows the FIELD inside the harvest — step
        along the line axis, take the strongest in-cone neighbor
        (transverse re-centering), stop when no forward face is still
        harvested ridge. The v3 mask-confined walker manufactured dashes
        the field never had (a global 1.5x-median support cut dropped
        weaker ring sections while Cavity Multi ran unbroken); the
        harvest removes the global cut, and strict per-step transverse
        dominance keeps the walk from flooding flanks.
        Returns (line_mask, chains); chains are maximal paths between
        endpoints/junctions plus closed loops, as face lists. '''
    hs = h * sign
    pos = hs > 0
    if not pos.any():
        return np.zeros(nF, bool), []
    harvest = harvest_line_faces(hs, bend_ok, adj_e, t_areas, t_centers,
                                 feature_scale, nF)
    if not harvest.any():
        return np.zeros(nF, bool), []
    support = harvest & (aniso >= CREST_ANISO_MIN)

    line_dir = np.cross(t_normals, across)
    line_dir = line_dir / np.maximum(
        np.linalg.norm(line_dir, axis=1, keepdims=True), 1e-12)

    # directional NMS: compare against the NEAREST face inside a tight
    # across cone on each side. The cone must exclude the along-strip
    # zigzag (tri centers wobble ~45 deg around the line axis, so a
    # loose cone makes spine faces kill each other and dash the line),
    # and the 1-ring alone often has no true across face at all (an
    # "up" triangle only borders one side) — hence the 2-ring.
    crest = np.zeros(nF, bool)
    for f in np.nonzero(support)[0]:
        f = int(f)
        A = across[f]
        cand = set()
        for nb, _ei in adj_e[f]:
            cand.add(nb)
            for nb2, _ei2 in adj_e[nb]:
                if nb2 != f:
                    cand.add(nb2)
        best_p = best_m = -1
        dist_p = dist_m = 1e30
        for nb in cand:
            d = t_centers[nb] - t_centers[f]
            dl = np.linalg.norm(d)
            if dl < 1e-12:
                continue
            a = float(d @ A) / dl
            if a >= CREST_NMS_COS and dl < dist_p:
                dist_p, best_p = dl, nb
            elif a <= -CREST_NMS_COS and dl < dist_m:
                dist_m, best_m = dl, nb
        if best_p >= 0 and hs[best_p] > hs[f]:
            continue
        if best_m >= 0 and hs[best_m] > hs[f]:
            continue
        crest[f] = True

    # chain assembly: FIELD-FOLLOWING walker — from each seed, step
    # roughly along the line axis (sign-matched to travel, blended with
    # momentum) and take the STRONGEST in-cone HARVESTED neighbor;
    # picking by field value re-centers the walk onto the spine, so NMS
    # membership never breaks a line. A single dead face may be hopped
    # if the ridge resumes beyond it. Each face joins at most one chain.
    claimed = np.zeros(nF, bool)

    # ridge-ness of a walk face: within CREST_WALK_DOM of its transverse
    # max (nearest across-cone neighbor per side, as in the NMS). Kept
    # SOFT (0.85): the harvest mask already bounds the walk, and the
    # strict 1.0 test measured as the dominant break cause on the boot
    # welt (73% of chain endpoints had harvested, strong continuation
    # the walker refused — one face of spine wobble failed every
    # forward candidate).
    ridge_cache = {}

    def ridge_ok(f):
        r = ridge_cache.get(f)
        if r is None:
            A = across[f]
            cand = set()
            for nb, _ei in adj_e[f]:
                cand.add(nb)
                for nb2, _ei2 in adj_e[nb]:
                    if nb2 != f:
                        cand.add(nb2)
            dist_p = dist_m = 1e30
            hs_p = hs_m = -1e30
            for nb in cand:
                d = t_centers[nb] - t_centers[f]
                dl = np.linalg.norm(d)
                if dl < 1e-12:
                    continue
                a = float(d @ A) / dl
                if a >= CREST_NMS_COS and dl < dist_p:
                    dist_p, hs_p = dl, hs[nb]
                elif a <= -CREST_NMS_COS and dl < dist_m:
                    dist_m, hs_m = dl, hs[nb]
            r = hs[f] >= CREST_WALK_DOM * max(hs_p, hs_m)
            ridge_cache[f] = r
        return r

    def step_cands(cur, ref):
        cands = []
        for nb, _ei in adj_e[cur]:
            if claimed[nb] or not harvest[nb]:
                continue
            d = t_centers[nb] - t_centers[cur]
            dl = np.linalg.norm(d)
            if dl < 1e-12:
                continue
            d = d / dl
            if float(d @ ref) > CREST_STEP_COS and ridge_ok(nb):
                cands.append((hs[nb], nb, d, None))
        if not cands:
            # hop a single dead face if the ridge resumes in-line
            for nb, _ei in adj_e[cur]:
                if claimed[nb]:
                    continue
                for nb2, _ei2 in adj_e[nb]:
                    if nb2 == cur or claimed[nb2] or not harvest[nb2]:
                        continue
                    d2 = t_centers[nb2] - t_centers[cur]
                    dl2 = np.linalg.norm(d2)
                    if dl2 < 1e-12:
                        continue
                    d2 = d2 / dl2
                    if float(d2 @ ref) > 0.5 and ridge_ok(nb2):
                        cands.append((hs[nb2], nb2, d2, nb))
        return cands

    def walk(start_f):
        chain = [start_f]
        claimed[start_f] = True
        for _dirsign in (1, -1):
            cur = chain[-1] if _dirsign == 1 else chain[0]
            if len(chain) >= 2:
                a_, b_ = (chain[-2], chain[-1]) if _dirsign == 1 \
                    else (chain[1], chain[0])
                pd = t_centers[b_] - t_centers[a_]
                pl = np.linalg.norm(pd)
                prev_dir = pd / pl if pl > 1e-12 \
                    else _dirsign * line_dir[cur]
            else:
                prev_dir = _dirsign * line_dir[start_f]
            while True:
                L = line_dir[cur]
                if float(L @ prev_dir) < 0.0:
                    L = -L
                ref = 0.6 * prev_dir + 0.4 * L
                rl = np.linalg.norm(ref)
                ref = ref / rl if rl > 1e-12 else L
                cands = step_cands(cur, ref)
                if not cands:
                    break
                _v, nb, d, via = max(cands, key=lambda c: c[0])
                if via is not None:
                    claimed[via] = True
                    if _dirsign == 1:
                        chain.append(via)
                    else:
                        chain.insert(0, via)
                claimed[nb] = True
                if _dirsign == 1:
                    chain.append(nb)
                else:
                    chain.insert(0, nb)
                prev_dir = 0.7 * ref + 0.3 * d
                pl = np.linalg.norm(prev_dir)
                prev_dir = prev_dir / pl if pl > 1e-12 else d
                cur = nb
        is_loop = len(chain) > 3 and any(
            nb == chain[0] for nb, _ei in adj_e[chain[-1]])
        return chain, is_loop

    chains = []
    seeds = np.nonzero(crest)[0]
    for f in seeds[np.argsort(-hs[seeds], kind='stable')]:
        f = int(f)
        if not claimed[f]:
            chains.append(walk(f))
    line_mask = np.zeros(nF, bool)
    line_mask[[f for ch, _ in chains for f in ch]] = True
    return line_mask, chains


def march_crest_curves(rungs, bend_ok, surf, t_centers, t_normals,
                       adj_e, feature_scale, nF):
    ''' MARCHING TRACER with PER-CURVE RUNG (round 59): every feature
        lives at its own scale, so each curve traces ONE rung of the
        cavity ladder — the rung that detected its seed — with a
        profile width matched to that rung. Any per-face argmax
        composite both starves narrow features (a sewing crease is a
        0.25-rung feature that coarse-only search never saw) and jumps
        rungs mid-feature (value discontinuities along a continuous
        groove). rungs = [dict(hs, across, line_dir, aniso, prof)] per
        ladder rung, already polarity-signed. Seeds gathered across
        ALL rungs, strongest first (rung values share units via the
        1/frac normalization), spatially thinned per rung (nested
        features at different scales are legitimate), claims SHARED
        across rungs (the same feature seeded at adjacent rungs traces
        once, from its strongest seed). March/correct/stop logic as
        round 56. Returns [(points Nx3, is_loop, rung_idx)]. '''
    step = CREST_MARCH_STEP * feature_scale
    claim_r = CREST_CLAIM_R * feature_scale
    cell = claim_r

    def cell_of(p):
        return (int(np.floor(p[0] / cell)), int(np.floor(p[1] / cell)),
                int(np.floor(p[2] / cell)))

    claim = {}

    def near_claim(p):
        cx, cy, cz = cell_of(p)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for q in claim.get((cx + dx, cy + dy, cz + dz), ()):
                        if float(np.linalg.norm(p - q)) < claim_r:
                            return True
        return False

    # seeds: bend-gated, orientation-coherent 1-ring maxima of EVERY
    # rung, pooled and sorted by strength, thinned per rung
    cand = []
    for k, R in enumerate(rungs):
        hs, aniso = R.get('hs_seed', R['hs']), R['aniso']
        pos = hs > 0.0
        if not pos.any():
            continue
        # rank in FLOOR UNITS OF THE RUNG: the 1/frac normalization
        # makes fine rungs numerically hot (x4 at 0.25), and raw-value
        # ranking let rung-0 grain maxima consume the whole seed cap
        # while real coarse features starved (boot: 200 -> 26 curves)
        med = max(float(np.median(hs[pos])), 1e-30)
        ok = pos & bend_ok & (aniso >= CREST_ANISO_MIN)
        for f in np.nonzero(ok)[0]:
            f = int(f)
            if all(hs[f] >= hs[nb] for nb, _ei in adj_e[f]):
                cand.append((float(hs[f]) / med, f, k))
    cand.sort(reverse=True)
    scell = CREST_SEED_SPACING * feature_scale
    taken = [{} for _ in rungs]
    seeds = []
    for _v, f, k in cand:
        p = t_centers[f]
        c = (int(np.floor(p[0] / scell)), int(np.floor(p[1] / scell)),
             int(np.floor(p[2] / scell)))
        clash = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for q in taken[k].get((c[0] + dx, c[1] + dy,
                                           c[2] + dz), ()):
                        if float(np.linalg.norm(p - q)) < scell:
                            clash = True
                            break
        if clash:
            continue
        taken[k].setdefault(c, []).append(p)
        seeds.append((f, k))
        if len(seeds) >= CREST_SEED_CAP:
            break

    curves = []
    for sf, kr in seeds:
        R = rungs[kr]
        hs, across = R['hs'], R['across']
        line_dir, prof = R['line_dir'], R['prof']
        p0 = t_centers[sf].astype(np.float64)
        if near_claim(p0):
            continue
        own = [p0]
        level = [float(hs[sf])]

        def march(d0):
            pts = []
            p, fi = p0.copy(), sf
            heading = d0.copy()
            looped = False
            pending = []
            streak = 0
            for _it in range(1500):
                n = t_normals[fi]
                d = heading - n * float(heading @ n)
                dl = float(np.linalg.norm(d))
                if dl < 1e-9:
                    break
                d = d / dl
                loc, fi2 = surf(p + d * step)
                A = across[fi2] - t_normals[fi2] \
                    * float(across[fi2] @ t_normals[fi2])
                al = float(np.linalg.norm(A))
                if al < 1e-9:
                    break
                A = A / al
                vals = np.empty(len(prof))
                for k2, t_ in enumerate(prof):
                    _lq, fq = surf(loc + A * t_)
                    vals[k2] = hs[fq]
                kmax = int(np.argmax(vals))
                wgt = np.maximum(vals - float(vals.min()), 0.0)
                ws = float(wgt.sum())
                bad = (kmax == 0 or kmax == len(prof) - 1
                       or ws <= 1e-30)
                if not bad:
                    t_pk = float((wgt * prof).sum() / ws)
                    p_new, fi_new = surf(loc + A * t_pk)
                    v = float(hs[fi_new])
                    med = float(np.median(level[-48:]))
                    bad = v <= 0.0 or v < CREST_MARCH_KEEP * med
                if bad:
                    # COAST: a single bad probe is noise, not evidence
                    # the feature ended — continue straight for up to
                    # CREST_MARCH_COAST steps; sustained failure stops,
                    # a recovered crest flushes the coasted points in
                    streak += 1
                    if streak >= CREST_MARCH_COAST:
                        break
                    pending.append(loc)
                    p, fi = loc, fi2
                    continue
                if near_claim(p_new):
                    break           # merged into an existing curve
                if len(own) > 8:
                    dd = np.linalg.norm(np.asarray(own[:-8]) - p_new,
                                        axis=1)
                    if float(dd.min()) < claim_r:
                        looped = True
                        break
                mv = p_new - p
                ml = float(np.linalg.norm(mv))
                if ml < 0.2 * step:
                    break           # stalled
                heading = mv / ml
                L = line_dir[fi_new]
                if float(L @ heading) < 0.0:
                    L = -L
                heading = 0.6 * heading + 0.4 * L
                hl = float(np.linalg.norm(heading))
                heading = heading / hl if hl > 1e-12 else mv / ml
                streak = 0
                if pending:
                    pts.extend(pending)
                    own.extend(pending)
                    pending = []
                pts.append(p_new)
                own.append(p_new)
                level.append(v)
                p, fi = p_new, fi_new
            return pts, looped

        h1, l1 = march(line_dir[sf])
        h2, l2 = march(-line_dir[sf])
        pts = h2[::-1] + [p0] + h1
        if len(pts) < 3:
            continue
        arr = np.asarray(pts)
        for q in pts:
            claim.setdefault(cell_of(q), []).append(q)
        curves.append((arr, bool(l1 or l2), kr))
    return curves

def refine_crest_curves(curves, hs, across, surf, t_normals,
                        feature_scale):
    ''' Curve-level stage (rounds 57/60): FUSE facing fragments, RELAX
        each curve as an active contour on the SWEEP FIELD with a
        transverse profile sized by the curve's own band width, PRUNE
        whole curves by global quality. curves and the return value are
        [(points, is_loop, half_width)]. '''
    step = CREST_MARCH_STEP * feature_scale
    fuse_gap = CREST_FUSE_GAP * feature_scale

    def resample(pts, looped):
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        if looped:
            seg = np.append(seg, np.linalg.norm(pts[0] - pts[-1]))
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        L = float(cum[-1])
        if L < 1e-12:
            return pts
        n = max(4, int(round(L / step)) + (0 if looped else 1))
        targets = np.linspace(0.0, L, n, endpoint=not looped)
        src = np.vstack([pts, pts[:1]]) if looped else pts
        out = np.empty((len(targets), 3))
        j = 0
        for i, t in enumerate(targets):
            while j < len(seg) - 1 and cum[j + 1] < t:
                j += 1
            d = cum[j + 1] - cum[j]
            a = 0.0 if d <= 1e-12 else (t - cum[j]) / d
            out[i] = src[j] * (1.0 - a) + src[j + 1] * a
        return out

    # --- fuse open fragments end-to-end ---
    loops = [(np.asarray(p), True, hw) for p, l, hw in curves if l]
    open_c = [(np.asarray(p), hw) for p, l, hw in curves
              if not l and len(p) >= 3]
    ends = []
    for ci, (p, _hw) in enumerate(open_c):
        for q, t in ((p[0], p[0] - p[min(2, len(p) - 1)]),
                     (p[-1], p[-1] - p[-min(3, len(p))])):
            tl = float(np.linalg.norm(t))
            ends.append((q, t / tl if tl > 1e-12 else t))
    cands = []
    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            if i // 2 == j // 2:
                continue
            pi_, ti = ends[i]
            pj_, tj = ends[j]
            gap = float(np.linalg.norm(pj_ - pi_))
            if gap > fuse_gap or gap < 1e-12:
                continue
            d = (pj_ - pi_) / gap
            if float(ti @ d) > 0.4 and float(tj @ -d) > 0.4:
                cands.append((gap, i, j))
    cands.sort()
    match = {}
    for _gap, i, j in cands:
        if i in match or j in match:
            continue
        match[i] = j
        match[j] = i
    visited = [False] * len(open_c)
    fused = []
    for start in range(len(open_c)):
        if visited[start]:
            continue
        cur, entry = start, 0
        seen = {start}
        cycle = False
        while True:
            k = match.get(2 * cur + entry)
            if k is None:
                break
            nc, np_ = divmod(k, 2)
            if nc in seen:
                cycle = True
                break
            seen.add(nc)
            cur, entry = nc, 1 - np_
        pts_list = []
        hw_max = 0.0
        forward = (entry == 0)
        first = cur
        while True:
            visited[cur] = True
            seg_p, seg_hw = open_c[cur]
            hw_max = max(hw_max, seg_hw)
            pts_list.append(seg_p if forward else seg_p[::-1])
            k = match.get(2 * cur + (1 if forward else 0))
            if k is None:
                break
            nc, np_ = divmod(k, 2)
            if visited[nc]:
                cycle = cycle or nc == first
                break
            cur = nc
            forward = (np_ == 0)
        pts = np.vstack(pts_list)
        looped = cycle
        if not looped and len(pts) >= 6:
            g = float(np.linalg.norm(pts[0] - pts[-1]))
            if 1e-12 < g <= fuse_gap:
                d = (pts[0] - pts[-1]) / g
                te = pts[-1] - pts[-3]
                te = te / max(float(np.linalg.norm(te)), 1e-12)
                if float(te @ d) > 0.4:
                    looped = True
        fused.append((pts, looped, hw_max))
    fused.extend(loops)

    # --- relax + prune ---
    result = []
    for pts, looped, hw in fused:
        prof = np.linspace(-1.0, 1.0, 7) * hw
        pts = resample(pts, looped)
        n = len(pts)
        peak_frac = 1.0
        for _it in range(CREST_RELAX_ITERS):
            newp = pts.copy()
            n_peak = n_tot = 0
            for i in range(n):
                if not looped and (i == 0 or i == n - 1):
                    continue
                mid = 0.5 * (pts[(i - 1) % n] + pts[(i + 1) % n])
                loc, fi = surf(pts[i])
                A = across[fi] - t_normals[fi] * float(
                    across[fi] @ t_normals[fi])
                al = float(np.linalg.norm(A))
                t_pk = 0.0
                if al > 1e-9:
                    A = A / al
                    vals = np.empty(len(prof))
                    for k2, t_ in enumerate(prof):
                        _q, fq = surf(loc + A * t_)
                        vals[k2] = hs[fq]
                    km = int(np.argmax(vals))
                    n_tot += 1
                    if 0 < km < len(prof) - 1:
                        n_peak += 1
                        wgt = np.maximum(vals - float(vals.min()), 0.0)
                        ws = float(wgt.sum())
                        if ws > 1e-30:
                            t_pk = float((wgt * prof).sum() / ws)
                    tgt = loc + (mid - loc) * 0.35 + A * (0.6 * t_pk)
                else:
                    tgt = mid
                newp[i], _fi = surf(tgt)
            pts = newp
            if n_tot:
                peak_frac = n_peak / n_tot
        seg = np.diff(pts, axis=0)
        if looped:
            seg = np.vstack([seg, (pts[0] - pts[-1])[None]])
        sl = np.linalg.norm(seg, axis=1)
        if float(sl.sum()) < CREST_MIN_LEN * feature_scale:
            continue
        sn = seg / np.maximum(sl[:, None], 1e-12)
        dots = (sn[:-1] * sn[1:]).sum(axis=1)
        if looped and len(sn) > 1:
            dots = np.append(dots, float(sn[-1] @ sn[0]))
        wig = float(np.degrees(np.arccos(np.clip(dots, -1, 1))).mean()) \
            if len(dots) else 0.0
        if peak_frac < CREST_CURVE_PEAK_MIN \
                or wig > CREST_CURVE_WIGGLE_MAX:
            continue
        result.append((pts, looped, hw))
    return result

def sweep_crest_curves(hs, bend_ok, adj_e, t_areas, t_centers,
                       feature_scale, nF):
    ''' SWEEP-NATIVE curve tracing (round 60, Jonathan's design): use
        the cavity sweep DIRECTLY. The descending-level union-find with
        the perimeter growth classifier (v7) supplies per-feature BANDS
        at their own levels; each TRACING component carries its CURVE
        through the sweep — born as the band's graph-farthest spine at
        lock time, then grown incrementally: at each growth quantum the
        farthest new band face (graph distance within the band) extends
        its CLOSEST curve endpoint via a crest-hugging shortest path,
        both ends independently — so a horseshoe grows around its arc
        instead of collapsing to its Euclidean chord. Component merges
        join curves end-to-end through the merged band; fattening
        (flanks arriving) freezes the curve. Every operation is GLOBAL
        (threshold sets, BFS, shortest paths) — no sequential local
        accept/reject exists for noise to veto, which is why marching
        could never match the sweep. Returns
        [(curve_faces, is_loop, band_halfwidth)]. '''
    import heapq
    lock_len = CREST_LOCK_LEN * feature_scale
    order = np.argsort(-hs, kind='stable')
    order = order[(hs[order] > 0.0) & bend_ok[order]]
    parent = np.full(nF, -1, dtype=np.int64)
    area, perim, bb_lo, bb_hi, csum, members = {}, {}, {}, {}, {}, {}
    state, w_lock, peak = {}, {}, {}
    curve, pend, looped_r, ck = {}, {}, {}, {}
    rate_win = CREST_RATE_WIN * feature_scale ** 2
    line_dummy = np.zeros(nF, bool)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def axis_of(r):
        d = bb_hi[r] - bb_lo[r]
        dl = float(np.linalg.norm(d))
        return d / dl if dl > 1e-12 else d

    def offset_dir(ra, rb):
        off = csum[rb] / area[rb] - csum[ra] / area[ra]
        ol = float(np.linalg.norm(off))
        return off / ol if ol > 1e-12 else None

    def band_bfs(srcs, memberset):
        dist = {f: 0 for f in srcs}
        frontier = list(srcs)
        while frontier:
            nxt = []
            for u in frontier:
                for nb, _ei in adj_e[u]:
                    if nb in memberset and nb not in dist:
                        dist[nb] = dist[u] + 1
                        nxt.append(nb)
            frontier = nxt
        return dist

    def crest_path(src, dst, memberset, pk):
        # shortest path through the band, cheap where the field is
        # strong: continuity is inherited from the band, placement
        # follows the crest
        if src == dst:
            return [src]
        dist = {src: 0.0}
        prev = {}
        pq = [(0.0, src)]
        while pq:
            dcur, u = heapq.heappop(pq)
            if u == dst:
                break
            if dcur > dist.get(u, np.inf):
                continue
            for nb, _ei in adj_e[u]:
                if nb not in memberset:
                    continue
                elen = float(np.linalg.norm(t_centers[nb]
                                            - t_centers[u]))
                c = dcur + elen * (1.0 + CREST_PATH_COST
                                   * (1.0 - min(hs[nb] / pk, 1.0)))
                if c < dist.get(nb, np.inf):
                    dist[nb] = c
                    prev[nb] = u
                    heapq.heappush(pq, (c, nb))
        if dst not in prev and dst != src:
            return None
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])
        return path[::-1]

    def init_curve(r):
        memberset = set(members[r])
        pk = peak[r]
        start = max(members[r], key=lambda f: hs[f])
        d1 = band_bfs({start}, memberset)
        f1 = max(d1, key=d1.get)
        d2 = band_bfs({f1}, memberset)
        f2 = max(d2, key=d2.get)
        cp = crest_path(f1, f2, memberset, pk)
        curve[r] = [cp if cp else [start]]
        pend[r] = []
        looped_r[r] = [False]

    def grow_curve(r):
        # Jonathan's rule, multi-curve form: the farthest new band face
        # extends its closest curve ENDPOINT — but only if the move is
        # LONGITUDINAL (endpoint distance ~ curve distance; a lateral
        # point beside the curve's middle is a BRANCH, and dragging an
        # end around to it is how a web band becomes one giant snake).
        # Lateral mass far from every curve SPAWNS a new curve in the
        # same component; the refine stage fuses collinear ends later.
        paths = curve[r]
        newf = pend[r]
        pend[r] = []
        if not newf or not paths:
            return
        memberset = set(members[r])
        pk = peak[r]
        allfaces = set(f2 for pth in paths for f2 in pth)
        dcur = band_bfs(allfaces, memberset)
        # labelled BFS from all open-path endpoints
        dist, lab = {}, {}
        frontier = []
        for pi, pth in enumerate(paths):
            if looped_r[r][pi]:
                continue
            for endi, f2 in ((0, pth[0]), (1, pth[-1])):
                dist[f2] = 0
                lab[f2] = (pi, endi)
                frontier.append(f2)
        while frontier:
            nxt = []
            for u in frontier:
                for nb, _ei in adj_e[u]:
                    if nb in memberset and nb not in dist:
                        dist[nb] = dist[u] + 1
                        lab[nb] = lab[u]
                        nxt.append(nb)
            frontier = nxt
        grown = {}
        spawn, spawn_d = None, 4
        for f2 in newf:
            dc = dcur.get(f2)
            if dc is None or dc <= 2:
                continue
            de = dist.get(f2)
            if de is not None and de <= 1.5 * dc + 2:
                key = lab[f2]
                if dc > grown.get(key, (None, 2))[1]:
                    grown[key] = (f2, dc)
            elif dc > spawn_d:
                spawn, spawn_d = f2, dc
        for (pi, endi), (f2, _dc) in grown.items():
            pth = paths[pi]
            src = pth[0] if endi == 0 else pth[-1]
            px = crest_path(src, f2, memberset, pk)
            if not px or len(px) < 2:
                continue
            paths[pi] = (px[::-1][:-1] + pth) if endi == 0 \
                else (pth + px[1:])
        if spawn is not None:
            paths.append([spawn])
            looped_r[r].append(False)
        # ring closure per path
        for pi, pth in enumerate(paths):
            if looped_r[r][pi] or len(pth) <= 10:
                continue
            dend = band_bfs({pth[0]}, memberset)
            if dend.get(pth[-1], 99) <= 2:
                looped_r[r][pi] = True

    order_faces = order
    for f in order_faces:
        f = int(f)
        parent[f] = f
        c = t_centers[f]
        a0 = float(t_areas[f])
        area[f], perim[f] = a0, 0.0
        bb_lo[f], bb_hi[f] = c.copy(), c.copy()
        csum[f] = c * a0
        members[f], state[f] = [f], 0
        peak[f] = float(hs[f])
        r = f
        for nb, _ei in adj_e[f]:
            elen = float(np.linalg.norm(t_centers[nb] - t_centers[f]))
            if parent[nb] < 0:
                r = find(r)
                perim[r] += elen
                continue
            r2 = find(int(nb))
            r = find(r)
            if r2 == r:
                perim[r] -= elen
                continue
            s1, s2 = state[r], state[r2]
            refuse = False
            if s1 == 1 and s2 == 1:
                ax1, ax2 = axis_of(r), axis_of(r2)
                off = offset_dir(r, r2)
                if off is None or abs(float(ax1 @ ax2)) < CREST_COLL_COS \
                        or abs(float(ax1 @ off)) < CREST_COLL_COS \
                        or abs(float(ax2 @ off)) < CREST_COLL_COS:
                    refuse = True
            elif (s1, s2) in ((1, 2), (2, 1)):
                refuse = True
            if refuse:
                perim[r] += elen
                continue
            if len(members[r2]) > len(members[r]):
                r, r2 = r2, r
            parent[r2] = r
            wl1, wl2 = w_lock.get(r), w_lock.get(r2)
            wl = (wl1 if area[r] >= area[r2] else wl2) \
                if (wl1 is not None and wl2 is not None) \
                else (wl1 if wl1 is not None else wl2)
            w_lock.pop(r2, None)
            if wl is not None:
                w_lock[r] = wl
            state[r] = max(state[r], state.pop(r2))
            area[r] += area.pop(r2)
            perim[r] = perim[r] + perim.pop(r2) - elen
            np.minimum(bb_lo[r], bb_lo.pop(r2), out=bb_lo[r])
            np.maximum(bb_hi[r], bb_hi.pop(r2), out=bb_hi[r])
            csum[r] = csum[r] + csum.pop(r2)
            peak[r] = max(peak[r], peak.pop(r2))
            c1, c2 = curve.pop(r, None), curve.pop(r2, None)
            p1 = pend.pop(r, [])
            p2 = pend.pop(r2, [])
            l1 = looped_r.pop(r, [])
            l2 = looped_r.pop(r2, [])
            m2 = members.pop(r2)
            if c1 is not None or c2 is not None:
                # components keep ALL their curves; end-to-end joining
                # happens downstream in the refine fusion stage
                curve[r] = (c1 or []) + (c2 or [])
                looped_r[r] = (l1 or []) + (l2 or [])
                if c1 is None:
                    p1 = p1 + members[r]   # curve-less side = growth mass
                elif c2 is None:
                    p1 = p1 + m2
            members[r].extend(m2)
            pend[r] = p1 + p2
        r = find(f)
        if state[r] == 1:
            pend.setdefault(r, []).append(f)
        P = perim[r]
        if P > 1e-12:
            W = 2.0 * area[r] / P
            L = 0.5 * P
            if state[r] == 0:
                if L >= lock_len and L >= CREST_ELONG_MIN * W:
                    state[r] = 1
                    w_lock[r] = W
                    ck[r] = (area[r], L, W)
                    init_curve(r)
            elif state[r] == 1:
                # freeze only when the band fattens FASTER than it
                # lengthens (Jonathan's rate rule) — some fattening is
                # expected; an absolute width ceiling froze features
                # whose genuine width varies along their run
                frozen = False
                cA, cL, cW = ck.get(r, (area[r], L, W))
                if area[r] - cA >= rate_win:
                    dL, dW = L - cL, W - cW
                    if dW > max(dL, 0.0):
                        state[r] = 2
                        grow_curve(r)
                        frozen = True
                    else:
                        ck[r] = (area[r], L, W)
                if not frozen and len(pend.get(r, ())) >= CREST_GROW_Q:
                    grow_curve(r)
    out = []
    for r in list(curve.keys()):
        if find(r) != r or state.get(r, 0) == 0:
            continue
        if pend.get(r):
            grow_curve(r)
        hw = min(max(2.0 * w_lock.get(r, 0.25 * feature_scale),
                     0.25 * feature_scale), 1.0 * feature_scale)
        for pi, cv in enumerate(curve[r]):
            if len(cv) >= 3:
                out.append((cv, bool(looped_r[r][pi]), hw))
    return out


def complete_crests(energy, feature_scale, bridge_gap):
    """ Stage 1b — crest lines v3 (round 48): traced on the SIGNED cavity
        fields with ORIENTED NMS, per polarity (ridge/valley) and per
        scale (fine + multi), replacing thresholded energy bands — the
        aggregate energy mixes scales (a mane fills solid at coarse
        scale), merges polarities, and puts strength on flanks; the
        signed fields draw features as clean thin lines along their
        structure-tensor axis. Open CURVES extend along their tangent
        to sharp walls or same-polarity curves (terminating ON the
        crease; the walked edges are stamped so the rim persists) —
        the curve-stage replacement for face-walk bridging. CLOSED
        LOOPS of small
        enclosed area are FEATURE BLOBS (an eye = a valley ring around a
        dome): loop + interior become a pre-labeled watershed seed.
        Returns a shallow-copied energy dict with stamped w/E_f plus
        'ridge_line'/'valley_line'/'crest_bridge'/'crest_cluster' masks
        (crest_band = line union, for the preview layer). """
    out = dict(energy)
    nF = len(energy['E_f'])
    for k in ('crest_band', 'crest_bridge', 'crest_cluster',
              'ridge_line', 'valley_line'):
        out[k] = np.zeros(nF, bool)
    if bridge_gap <= 0.0:
        return out
    E_f = energy['E_f']
    fa, fb = energy['fa'], energy['fb']
    w, sharp = energy['w'].copy(), energy['sharp']
    mean_step = energy['mean_step']
    t_centers = energy['t_centers']
    t_areas = energy['t_areas']
    t_normals = energy['t_normals']
    hm = energy['cav_multi']
    hf = energy['cav_fine']

    adj_e = [[] for _ in range(nF)]
    for i in range(len(fa)):
        if sharp[i]:
            continue
        a, b = int(fa[i]), int(fb[i])
        adj_e[a].append((b, i))
        adj_e[b].append((a, i))
    wall_touch = np.zeros(nF, bool)
    wm = sharp.nonzero()[0]
    wall_touch[fa[wm]] = True
    wall_touch[fb[wm]] = True

    # --- per-field across-line axis from the PRE-SMOOTHED field's
    # gradient structure tensor: the axis comes from the FLANK
    # gradients aggregated over the band (the gradient AT the crest
    # vanishes), and the pre-smooth is what makes it work — raw
    # face-pair differences measured near-isotropic (aniso ~0.10, hm's
    # winner-takes-all rung switching adds spikes), the smoothed-normal
    # turn tensor was mesh-density-sensitive (horse 0.28 / scorpion
    # 0.12), while presmoothed-h gradients measured 0.39 / 0.22 with
    # matching chain gains on both. Polarity drops out of the outer
    # product, so one tensor per field serves both signs. ---
    pyramid = energy['pyramid']
    ns_ = ~sharp
    fa_ns, fb_ns = fa[ns_], fb[ns_]
    dvec = t_centers[fb_ns] - t_centers[fa_ns]
    dlen = np.maximum(np.linalg.norm(dvec, axis=1), 1e-12)
    dvec = dvec / dlen[:, None]
    sym_idx = ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))

    # --- bending-reality gate, POLARITY-SIGNED: a ridge must bend
    # convexly, a valley concavely. DC-removal halos beside sub-scale
    # features carry cavity amplitude comparable to the features
    # themselves but no bending of their OWN polarity — an unsigned
    # gate measured WORSE on the beveled cube because halo rows inherit
    # one high-turn edge from the convex bevel next door and pass; the
    # signed gate makes valley harvest literally empty on a convex-
    # everywhere solid. RAW normals (smoothed turn bleeds a blur radius
    # onto the flats, exactly where halos live), rate per SCALE of
    # travel (honest on clean meshes at any density, inert on noisy
    # scans whose faceting is tens of deg/scale). ---
    # Implemented as SMOOTHED SIGNED MEAN CURVATURE. Two measured dead
    # ends first: max-per-edge rates let convex-quad triangulation
    # diagonals through (micro-concave ~0.1 deg but amplified by
    # scale/dlen on skinny faces — cube net rates hit 3000+ deg/scale
    # from ~0.0006 center distances), and net-sum per face inherited
    # the same 1/dlen explosion. So: weight each edge's signed angle BY
    # its length (degenerate edges are suppressed instead of
    # amplified), divide by face area — integrated mean-curvature
    # density — then diffuse at quarter scale so alternating +- fold
    # noise cancels while real creases reinforce. Units after x scale:
    # degrees of coherent turn per scale of travel.
    cosb = np.clip((t_normals[fa_ns] * t_normals[fb_ns]).sum(axis=1),
                   -1.0, 1.0)
    dn = t_normals[fb_ns] - t_normals[fa_ns]
    conv = np.sign((dn * dvec).sum(axis=1))   # +1 convex, -1 concave
    theta = np.degrees(np.arccos(cosb)) * conv
    D = np.zeros(nF)
    np.add.at(D, fa_ns, theta * dlen)
    np.add.at(D, fb_ns, theta * dlen)
    D = D / np.maximum(2.0 * t_areas, 1e-30)
    Ds = diffuse_graph_fields_pyramid(
        D[:, None], 0.25 * feature_scale, fa, fb, nF,
        mean_step, pyramid)[:, 0] * feature_scale
    bend_r = Ds >= CREST_TURN_MIN_DEG
    bend_v = Ds <= -CREST_TURN_MIN_DEG

    # --- MARCHING TRACER (round 56, Jonathan's architecture): build
    # the curve in SPACE — geometric steps, transverse peak correction,
    # continuation against the curve's own level — and apply it to
    # faces only at the end. The graph machinery (states, cones, node
    # hops) gave every element a veto and no single mechanism dominated
    # the measured breaks; the curve entity removes the vetoes. ---
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    bvh = BVHTree.FromPolygons(energy['verts'].tolist(),
                               energy['tris'].tolist())

    def surf(p):
        loc, _n, fi, _d = bvh.find_nearest(
            Vector((float(p[0]), float(p[1]), float(p[2]))))
        return np.asarray(loc, dtype=np.float64), int(fi)

    def across_axes(h, rung_rad):
        h_r = diffuse_graph_fields_pyramid(
            h[:, None], CREST_TENSOR_PRE_X * rung_rad, fa, fb, nF,
            mean_step, pyramid)[:, 0]
        g2 = ((h_r[fb_ns] - h_r[fa_ns]) / dlen) ** 2
        O = np.empty((len(g2), 6))
        for k, (i, j) in enumerate(sym_idx):
            O[:, k] = g2 * dvec[:, i] * dvec[:, j]
        T = np.zeros((nF, 6))
        np.add.at(T, fa_ns, O)
        np.add.at(T, fb_ns, O)
        T = diffuse_graph_fields_pyramid(
            T, CREST_TENSOR_RAD_X * rung_rad, fa, fb, nF, mean_step,
            pyramid)
        M = np.empty((nF, 3, 3))
        for k, (i, j) in enumerate(sym_idx):
            M[:, i, j] = T[:, k]
            M[:, j, i] = T[:, k]
        # tangent-plane projection: dominant eigenvector = across axis
        n_ = t_normals
        nM = n_[:, None, :] @ M
        Mn = M @ n_[:, :, None]
        nMn = (n_[:, None, :] @ Mn)[:, 0, 0]
        M_t = (M - n_[:, :, None] * nM - Mn * n_[:, None, :]
               + nMn[:, None, None] * (n_[:, :, None] * n_[:, None, :]))
        evals, evecs = np.linalg.eigh(M_t)
        across = evecs[:, :, 2]
        across = across - n_ * (across * n_).sum(axis=1, keepdims=True)
        across = across / np.maximum(
            np.linalg.norm(across, axis=1, keepdims=True), 1e-12)
        aniso = (evals[:, 2] - evals[:, 1]) / np.maximum(
            evals[:, 2] + evals[:, 1], 1e-30)
        return across, aniso

    # ONE tensor from the sweep field itself (hm): the tracer now
    # consumes exactly what the Cavity Multi sweep displays
    across, aniso = across_axes(hm, 0.5 * feature_scale)

    def paint_chain(pts, looped):
        # apply the curve to faces at the last step: subsample segments
        # and collect the faces under them, ordered, deduped
        faces = []
        last = -1
        sub = 0.75 * mean_step
        segs = list(zip(pts[:-1], pts[1:]))
        if looped and len(pts) > 2:
            segs.append((pts[-1], pts[0]))
        for a_, b_ in segs:
            seg = b_ - a_
            sl = float(np.linalg.norm(seg))
            k = max(1, int(np.ceil(sl / sub)))
            for j in range(k):
                _q, fq = surf(a_ + seg * ((j + 0.5) / k))
                if fq != last:
                    faces.append(fq)
                    last = fq
        seen = set()
        out_f = []
        for f2 in faces:
            if f2 not in seen:
                seen.add(f2)
                out_f.append(f2)
        return out_f

    all_chains = []      # (faces, is_loop, sign)
    out['crest_curves'] = []   # (points Nx3, is_loop, sign)
    min_len = CREST_MIN_LEN * feature_scale
    step_len = CREST_MARCH_STEP * feature_scale

    def extend_end(pts_arr, at_end, own_faces, pol_faces):
        # CURVE-STAGE wall/junction connection (replaces the face-walk
        # bridge pass): march the endpoint straight along its tangent,
        # surface-projected, until it reaches a sharp wall or another
        # same-polarity curve within the bridge_gap budget. The curve
        # itself terminates ON the crease/junction; no face-walk, no
        # invisible targets.
        a_, b_ = (pts_arr[-2], pts_arr[-1]) if at_end \
            else (pts_arr[1], pts_arr[0])
        t = b_ - a_
        tl = float(np.linalg.norm(t))
        if tl < 1e-12:
            return None
        t = t / tl
        p = b_.copy()
        sub = 0.5 * step_len
        walked_pts = []
        walked_faces = []
        for _ in range(max(2, int(round(bridge_gap * feature_scale
                                        / sub)))):
            loc, fi = surf(p + t * sub)
            mv = loc - p
            ml = float(np.linalg.norm(mv))
            if ml < 1e-9:
                return None
            t = mv / ml         # follow the surface
            p = loc
            walked_pts.append(loc)
            if fi in own_faces:
                continue
            walked_faces.append(fi)
            if wall_touch[fi] or pol_faces[fi]:
                return walked_pts, walked_faces
        return None

    for sign in (1.0, -1.0):
        hs_p = hm * sign
        bend_ok = bend_r if sign > 0 else bend_v
        bands = sweep_crest_curves(hs_p, bend_ok, adj_e, t_areas,
                                   t_centers, feature_scale, nF)
        curves = [(t_centers[np.asarray(cf, dtype=np.int64)], lp, hw)
                  for cf, lp, hw in bands if len(cf) >= 3]
        curves = refine_crest_curves(curves, hs_p, across, surf,
                                     t_normals, feature_scale)
        entries = []
        pol_faces = np.zeros(nF, bool)
        for pts, looped, _hw in curves:
            if len(pts) < 3:
                continue
            if float(np.linalg.norm(np.diff(pts, axis=0),
                                    axis=1).sum()) < min_len:
                continue
            faces = paint_chain(pts, looped)
            if len(faces) < 3:
                continue
            entries.append([pts, looped, faces])
            pol_faces[faces] = True
        for e in entries:
            pts, looped, faces = e
            if looped:
                continue
            own = set(faces)
            stamp = float(np.median(E_f[faces]))
            for at_end in (True, False):
                ext = extend_end(pts, at_end, own, pol_faces)
                if ext is None:
                    continue
                w_pts, w_faces = ext
                if at_end:
                    pts = np.vstack([pts, np.asarray(w_pts)])
                    faces = faces + [f2 for f2 in w_faces
                                     if f2 not in own]
                else:
                    pts = np.vstack([np.asarray(w_pts)[::-1], pts])
                    faces = [f2 for f2 in w_faces
                             if f2 not in own][::-1] + faces
                for f2 in w_faces:
                    own.add(f2)
                    out['crest_bridge'][f2] = True
                    pol_faces[f2] = True
                    for _nb, ei in adj_e[f2]:
                        if w[ei] < stamp:
                            w[ei] = stamp
                e[0], e[2] = pts, faces
        for pts, looped, faces in entries:
            out['crest_curves'].append((pts, looped, sign))
            all_chains.append((faces, looped, sign))
    cycle_r = np.zeros(nF, bool)
    cycle_v = np.zeros(nF, bool)
    for ch, _l, sign in all_chains:
        (cycle_r if sign > 0 else cycle_v)[ch] = True
    ridge = out['ridge_line']
    valley = out['valley_line']
    for ch, _l, sign in all_chains:
        (ridge if sign > 0 else valley)[ch] = True
    out['crest_band'] = ridge | valley

    # --- closed cycles in the line network = feature blobs ---
    # The WALKER almost never returns closed loops on real meshes: any
    # contact with another line claims part of a ring, and the remainder
    # walks as an open arc (horse eye: 0 loops across all four passes).
    # Loop-ness is a GRAPH property: BFS spanning forest per polarity
    # mask; every non-tree edge closes one fundamental cycle; cycles
    # under the blob perimeter enclosing a small coherent side qualify.
    max_blob_area = min(CLUSTER_MAX_AREA_X * feature_scale ** 2,
                        CLUSTER_MAX_FRACTION * float(t_areas.sum()))
    perim_cap = int(1.5 * 2.0 * np.sqrt(np.pi * max_blob_area)
                    / max(mean_step, 1e-12)) + 4

    def consider_ring(cyc):
        pts = t_centers[cyc]
        perim = float(np.linalg.norm(np.roll(pts, -1, axis=0) - pts,
                                     axis=1).sum())
        sides = []
        seen = set(cyc)
        for f0 in cyc:
            for nb, _ei in adj_e[f0]:
                if nb in seen:
                    continue
                comp = [nb]
                seen.add(nb)
                stack = [nb]
                area = float(t_areas[nb])
                overflow = False
                while stack:
                    f = stack.pop()
                    for nb2, _ei2 in adj_e[f]:
                        if nb2 not in seen:
                            seen.add(nb2)
                            comp.append(nb2)
                            stack.append(nb2)
                            area += float(t_areas[nb2])
                            if area > max_blob_area:
                                overflow = True
                                break
                    if overflow:
                        break
                if not overflow:
                    sides.append(comp)
        for comp in sides:
            # a blob ring is circle-ish: corridor cells between
            # parallel lines are elongated and fail isoperimetry
            area = float(t_areas[comp].sum())
            if area < CLUSTER_MIN_AREA_X * feature_scale ** 2:
                continue
            if 4.0 * np.pi * area / max(perim, 1e-12) ** 2 \
                    < CLUSTER_ISO_MIN:
                continue
            blob = comp + cyc
            band_area = float(t_areas[blob].sum())
            nsum = (t_normals[blob]
                    * t_areas[blob][:, None]).sum(axis=0)
            if float(np.linalg.norm(nsum)) / max(band_area, 1e-30) \
                    < CLUSTER_NORMAL_MIN:
                continue
            out['crest_cluster'][blob] = True

    for ch, is_loop, _sign in all_chains:
        if is_loop:
            consider_ring(ch)

    # WiP, gated: graph-cycle rings fix the walker's blindness to rings
    # that touch other lines (horse eye: 0 walker loops in all four
    # passes), but on smooth noisy scans the traced web is so dense
    # (support floor = 1.5x a NOISE median there) that its cells blob
    # half the mesh, and the boot referee loses 3 precision points.
    # Re-enable once line support is feature-relative, not noise-relative
    # (e.g. flank-contrast pruning of chains).
    if CREST_CYCLE_BLOBS:
        for cyc_mask in (cycle_r, cycle_v):
            parent, depth = {}, {}
            extra = []
            for s in np.nonzero(cyc_mask)[0]:
                s = int(s)
                if s in parent:
                    continue
                parent[s], depth[s] = -1, 0
                queue = [s]
                for u in queue:
                    for nb, _ei in adj_e[u]:
                        if not cyc_mask[nb]:
                            continue
                        if nb not in parent:
                            parent[nb], depth[nb] = u, depth[u] + 1
                            queue.append(nb)
                        elif nb != parent[u] \
                                and (depth[nb], nb) < (depth[u], u):
                            extra.append((u, nb))
            cands = []
            for u, v in extra:
                path_u, path_v = [u], [v]
                a, b = u, v
                ok = True
                while a != b:
                    if len(path_u) + len(path_v) > perim_cap:
                        ok = False
                        break
                    if depth[a] >= depth[b]:
                        a = parent[a]
                        path_u.append(a)
                    else:
                        b = parent[b]
                        path_v.append(b)
                if not ok:
                    continue
                cyc = path_u + path_v[-2::-1]  # LCA appears once
                if CREST_LOOP_MIN_FACES <= len(cyc) <= perim_cap:
                    cands.append(cyc)
            cands.sort(key=len)
            processed = np.zeros(nF, bool)
            for cyc in cands:
                if int(processed[cyc].sum()) * 2 > len(cyc):
                    continue  # mostly the same ring as an earlier cycle
                processed[cyc] = True
                consider_ring(cyc)

    E2 = np.zeros(nF)
    np.maximum.at(E2, fa, w)
    np.maximum.at(E2, fb, w)
    out['w'] = w
    out['E_f'] = E2
    return out


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

    seeds0 = np.full(nF, -1, dtype=np.int64)
    # FEATURE-BLOB SEEDS (round 45): each detected blob of dense detail
    # is pre-labeled as its own seed — its front flows downhill onto the
    # quiet ground and collides with the ground's basins at the energy
    # drop-off, placing the boundary on the feature's outer contour.
    # Connected pieces (blobs can be split by walls) seed separately.
    blob = energy.get('crest_cluster')
    if blob is not None and blob.any():
        visited_b = np.zeros(nF, bool)
        for s_ in np.nonzero(blob)[0]:
            s_ = int(s_)
            if visited_b[s_]:
                continue
            comp = [s_]
            visited_b[s_] = True
            stack = [s_]
            while stack:
                f = stack.pop()
                for nb, _we in adj_ns[f]:
                    if blob[nb] and not visited_b[nb]:
                        visited_b[nb] = True
                        comp.append(nb)
                        stack.append(nb)
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

    # initial seeds: quiet components clearing the gate (unchanged rule;
    # blob-seeded faces excluded)
    quiet = (E_f < thr) & (seeds0 < 0)
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


def refine_boundaries(labels, energy, feature_scale, snap_radius):
    ''' Stage 2b — coarse-to-fine boundary refinement (round 43,
        ADAPTIVE): each boundary face carries its own snap budget — the
        blur radius of the channel that detected it (we know the size of
        the gaussians), shrunk where the smoothing ladder agrees with the
        fine field (symmetric features do not drift). Freeze labels
        outside the budgeted band (plus each region's quietest face as an
        anchor), rebuild a SHARP band-local energy — fine cavity crest for
        monopoles, fine sign-crossings for doublet welts, a small phantom
        bump on the original line so boundaries stay when nothing better
        exists — and re-run the ascending assignment: fronts re-collide
        on the fine feature lines. `snap_radius` is a multiplier on the
        local budget (0 disables). '''
    nF = len(labels)
    if snap_radius <= 0.0:
        return labels
    fa, fb = energy['fa'], energy['fb']
    sharp = energy['sharp']
    hf = energy['cav_fine']
    hm = energy['cav_multi']
    E_f = energy['E_f']
    adj_ns = energy['adj_ns']
    t_centers = energy['t_centers']
    mean_step = energy['mean_step']
    snap_rad = energy['snap_rad']
    lab = labels.copy()

    bnd_edges = np.nonzero(lab[fa] != lab[fb])[0]
    if not len(bnd_edges):
        return labels
    budgets = {}
    for i in bnd_edges:
        for f in (int(fa[i]), int(fb[i])):
            b = int(round(snap_radius * snap_rad[f]
                          / max(mean_step, 1e-12)))
            if b > budgets.get(f, -1):
                budgets[f] = b
    maxb = max(budgets.values())
    if maxb <= 0:
        return labels
    remaining = np.full(nF, -1, dtype=np.int64)
    band = np.zeros(nF, bool)
    buckets = [[] for _ in range(maxb + 1)]
    for f, b in budgets.items():
        remaining[f] = b
        band[f] = True
        buckets[b].append(f)
    for r in range(maxb, 0, -1):
        for f in buckets[r]:
            if remaining[f] != r:
                continue
            for nb, _we in adj_ns[f]:
                if remaining[nb] < r - 1:
                    remaining[nb] = r - 1
                    band[nb] = True
                    buckets[r - 1].append(nb)

    # each region's quietest face stays frozen: an anchor per region
    seen = set()
    for f in np.argsort(E_f, kind='stable'):
        l = int(lab[int(f)])
        if l not in seen:
            seen.add(l)
            band[int(f)] = False

    dctr = np.maximum(np.linalg.norm(t_centers[fa] - t_centers[fb],
                                     axis=1), 1e-12)
    # POLARITY GATE (Jonathan, big-island lesson): the fine crest may
    # only attract where its SIGN agrees with the coarse field that
    # placed the boundary — a boundary on a ridge must snap to the
    # center of THAT ridge, never to a nearby valley. Sign-crossings
    # stay ungated: a doublet center legitimately involves both signs
    pick = np.abs(hf[fa]) >= np.abs(hf[fb])
    f_dom = np.where(pick, fa, fb)
    agree = (hf[f_dom] * hm[f_dom]) > 0.0
    cavv = np.maximum(np.abs(hf[fa]), np.abs(hf[fb])) * agree
    cavx = np.where(hf[fa] * hf[fb] < 0.0,
                    np.abs(hf[fa] - hf[fb]) / dctr, 0.0)

    def mednz(x):
        a = x[x > 0]
        return max(float(np.median(a)) if len(a) else 0.0, 1e-30)

    e_ref = np.maximum(cavv / mednz(cavv), cavx / mednz(cavx))
    # phantom bump on the ORIGINAL line: stay when nothing better exists,
    # lose to any genuine crest in reach
    e_ref[bnd_edges] += 0.5

    parent = np.arange(nF)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    slab = lab.copy()
    slab[band] = -1
    cand = np.nonzero((band[fa] | band[fb]) & ~sharp)[0]
    for ei in cand[np.argsort(e_ref[cand], kind='stable')]:
        ei = int(ei)
        a, b = find(int(fa[ei])), find(int(fb[ei]))
        if a == b:
            continue
        la_, lb_ = int(slab[a]), int(slab[b])
        if la_ >= 0 and lb_ >= 0:
            continue        # fronts collide: the refined boundary
        parent[b] = a
        if la_ < 0:
            slab[a] = lb_
    out = lab.copy()
    for f in np.nonzero(band)[0]:
        l = int(slab[find(int(f))])
        if l >= 0:
            out[int(f)] = l
    return np.unique(out, return_inverse=True)[1]


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


def segment_faces(co, tris, feature_scale, seed_threshold, seed_area,
                  bridge_gap=2.0):
    ''' Full pipeline (energy + crest completion + watershed) for one-shot
        callers. Returns (face_labels, energy, region count, extras). '''
    energy = complete_crests(compute_energy(co, tris, feature_scale),
                             feature_scale, bridge_gap)
    lab, seeds0, n = watershed(energy, feature_scale, seed_threshold,
                                seed_area)
    return lab, energy['E_f'], n, gather_extras(energy, seeds0)


def gather_extras(energy, seeds0):
    return dict(cav_multi=energy['cav_multi'], cav_fine=energy['cav_fine'],
                normals_fine=energy['normals_fine'],
                normals_coarse=energy['normals_coarse'], seeds=seeds0,
                fa=energy['fa'], fb=energy['fb'],
                crest_band=energy.get('crest_band'),
                crest_bridge=energy.get('crest_bridge'),
                crest_cluster=energy.get('crest_cluster'),
                ridge_line=energy.get('ridge_line'),
                valley_line=energy.get('valley_line'))


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


def build_crest_curve_object(context, target, crest_curves):
    ''' Publish the marched polylines as a POLY-spline curve object
        ("<target>.CrestCurves", replaced on each run) so the traced
        lines can be inspected directly, independent of any face
        painting. Loops become cyclic splines. Ridge splines get radius
        1.0, valleys 0.5 (visible with a curve bevel if wanted). '''
    name = f'{target.name}.CrestCurves'
    cd = bpy.data.curves.get(name)
    if cd is None:
        cd = bpy.data.curves.new(name, 'CURVE')
    cd.splines.clear()
    cd.dimensions = '3D'
    cd.bevel_depth = 0.005
    cd.use_fill_caps = True
    for pts, looped, sign in crest_curves:
        sp = cd.splines.new('POLY')
        sp.points.add(len(pts) - 1)
        flat = np.empty((len(pts), 4))
        flat[:, :3] = pts
        flat[:, 3] = 1.0
        sp.points.foreach_set('co', flat.ravel())
        sp.points.foreach_set(
            'radius', [1.0 if sign > 0 else 0.5] * len(pts))
        sp.use_cyclic_u = bool(looped)
    ob = bpy.data.objects.get(name)
    if ob is None or ob.data is not cd:
        if ob is not None:
            bpy.data.objects.remove(ob)
        ob = bpy.data.objects.new(name, cd)
        coll = (target.users_collection[0] if target.users_collection
                else context.scene.collection)
        coll.objects.link(ob)
    ob.matrix_world = target.matrix_world.copy()


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
    if extras.get('crest_band') is not None:
        # ridge lines orange, valley lines blue, bridges green, feature
        # blobs (closed loops + interiors) cyan, rest dark
        ccol = np.full((len(extras['crest_band']), 4), 0.15)
        ccol[:, 3] = 1.0
        if extras.get('crest_cluster') is not None:
            ccol[extras['crest_cluster']] = (0.15, 0.75, 0.85, 1.0)
        if extras.get('ridge_line') is not None:
            ccol[extras['ridge_line']] = (0.9, 0.55, 0.15, 1.0)
            ccol[extras['valley_line']] = (0.25, 0.45, 1.0, 1.0)
        else:
            ccol[extras['crest_band']] = (0.9, 0.55, 0.15, 1.0)
        ccol[extras['crest_bridge']] = (0.2, 1.0, 0.3, 1.0)
        write_corner_colors(me, tri_loops, 'Crest Lines', ccol)
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
    bl_label = 'Separate Features'
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
    bridge_gap: bpy.props.FloatProperty(
        name='Bridge Gaps',
        description=('Extract coherent seam lines and bridge gaps where '
                     'they fade out, up to this many feature-scale units — '
                     'keeps basins fenced at fading seam ends (banana-tip '
                     'horseshoes). 0 disables'),
        default=2.0, min=0.0, max=6.0,
    )
    snap_radius: bpy.props.FloatProperty(
        name='Snap Boundaries',
        description=('Coarse-to-fine refinement: re-place each region '
                     'boundary onto the sharpest nearby fine-scale feature '
                     'line, searching within the detecting blur radius '
                     'times this multiplier (the drift bound the energy '
                     'itself implies). 0 disables'),
        default=1.0, min=0.0, max=3.0,
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
            ('Crest Lines', 'Crest Lines',
             'Ridge lines (orange), valley lines (blue), bridges (green), '
             'feature blobs (cyan)'),
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
        layout.prop(self, 'bridge_gap')
        layout.prop(self, 'snap_radius')
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
        # the crest, watershed, and merge stages are cached too, so a
        # preview-layer change in the redo panel re-executes near-instantly
        if energy_cache.get('crest_key') != self.bridge_gap:
            energy_cache['crested'] = complete_crests(energy, scale,
                                                      self.bridge_gap)
            energy_cache['crest_key'] = self.bridge_gap
            energy_cache.pop('ws_key', None)
        crested = energy_cache['crested']
        ws_key = (self.seed_threshold, self.seed_area)
        if energy_cache.get('ws_key') != ws_key:
            energy_cache['ws'] = watershed(
                crested, scale, self.seed_threshold, self.seed_area)
            energy_cache['ws_key'] = ws_key
            energy_cache.pop('merge_key', None)
        labels_raw, seeds0, n_raw = energy_cache['ws']
        if energy_cache.get('refine_key') != self.snap_radius:
            energy_cache['refined'] = refine_boundaries(
                labels_raw, crested, scale, self.snap_radius)
            energy_cache['refine_key'] = self.snap_radius
            energy_cache.pop('merge_key', None)
        labels_ref = energy_cache['refined']
        if energy_cache.get('merge_key') != self.merge_below:
            energy_cache['merged'] = merge_regions(
                labels_ref, crested, scale, self.merge_below)
            energy_cache['merge_key'] = self.merge_below
        labels, n_regions = energy_cache['merged']
        extras = gather_extras(crested, seeds0)
        extras['labels_raw'] = labels_raw
        write_attributes(me, tri_loops, labels, crested['E_f'], tris,
                         extras, preview=self.preview)
        me.update()
        build_crest_curve_object(context, context.active_object,
                                 crested.get('crest_curves', []))
        self.report({'INFO'}, f'Segment Mesh: {n_regions} regions '
                              f'({n_raw} before merge, feature scale '
                              f'{scale:.4f}'
                              f'{", cached fields" if cached else ""})')
        return {'FINISHED'}
