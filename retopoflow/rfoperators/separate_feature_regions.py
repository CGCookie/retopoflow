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

SHARP_ANGLE_DEG = 25.0            # absolute sharp-edge wall (density-proof)
CAVITY_FRACS = (0.25, 0.35, 0.5, 0.7, 1.0, 1.4)
TURN_FRACS = (0.25, 1.0, 2.5)     # smoothed-normal ladder for turn channels
K_CAP = 400
GROWTH_STAGES = 8


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

    fa, fb = get_face_adjacency(tris)
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
    ns = t_normals.copy()
    k_done = 0
    for frac in TURN_FRACS:
        k = diffusion_iters_for_radius(frac * feature_scale, mean_step,
                                        K_CAP)
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
            h_bg = diffuse_graph_fields(h[:, None], fa, fb, nF,
                            min(16 * k, K_CAP))[:, 0]
            r = (h - h_bg) / frac
            m = np.abs(r) > best_mag
            best[m] = r[m]
            best_mag[m] = np.abs(r[m])
        return best

    hm = cavity(CAVITY_FRACS)
    hf = cavity(CAVITY_FRACS[:1])

    # --- pairwise seam energy ---
    turns = [np.arccos(np.clip((ns_ladder[f][fa] * ns_ladder[f][fb]).sum(1),
                               -1, 1)) / dctr
             for f in TURN_FRACS]
    cavm = np.abs(hm[fa] - hm[fb]) / dctr
    cavf = np.abs(hf[fa] - hf[fb]) / dctr
    # cavity CREST channel (banana lesson): a broad soft fold is a smooth
    # BAND of cavity residual — its cross-edge steps are tiny (spread over
    # the band) and its turn rate matches the body's own curvature, so no
    # rate channel ever sees it. The field VALUE does: per-rung DC removal
    # already subtracted the body's convexity, so the residual peaks on the
    # fold line itself and watershed fronts collide at the crest.
    cavv = np.maximum(np.abs(hm[fa]), np.abs(hm[fb]))

    def mednz(x):
        a = x[x > 0]
        return max(float(np.median(a)) if len(a) else 0.0, 1e-30)

    w = np.maximum.reduce([t / mednz(t) for t in turns]
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

    cosw = math.cos(math.radians(SHARP_ANGLE_DEG))
    sharp = (t_normals[fa] * t_normals[fb]).sum(1) < cosw
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
                cav_multi=hm, cav_fine=hf, normals_fine=nsf,
                normals_coarse=ns_ladder[TURN_FRACS[-1]])


def watershed(energy, feature_scale, seed_threshold, seed_area):
    ''' Stage 2 — seeding and growth over a precomputed energy stage.
        Cheap relative to stage 1; reruns on every redo-panel tweak.
        Returns (face_labels, initial seed labels, region count). '''
    E_f = energy['E_f']
    adj_ns = energy['adj_ns']
    order_f = energy['order_f']
    t_areas = energy['t_areas']
    nF = len(E_f)
    thr = seed_threshold
    min_seed_a = seed_area * feature_scale ** 2
    lab = np.full(nF, -1, dtype=np.int64)
    nxt = 0

    def seed_components(mask, skip_front_adjacent):
        # components of `mask` seed if they clear the size gate; LATE seeds
        # additionally require that no front has reached them (a front-
        # adjacent quiet fleck just gets claimed naturally)
        nonlocal nxt
        visited = np.zeros(nF, bool)
        for s in np.nonzero(mask)[0]:
            s = int(s)
            if visited[s] or lab[s] >= 0:
                continue
            comp = [s]
            visited[s] = True
            stack = [s]
            touches = False
            while stack:
                f = stack.pop()
                for nb, _we in adj_ns[f]:
                    if lab[nb] >= 0:
                        touches = True
                    elif mask[nb] and not visited[nb]:
                        visited[nb] = True
                        comp.append(nb)
                        stack.append(nb)
            if float(t_areas[comp].sum()) >= min_seed_a \
                    and not (skip_front_adjacent and touches):
                for f in comp:
                    lab[f] = nxt
                nxt += 1

    seed_components(E_f < thr, False)
    seeds0 = lab.copy()
    above = E_f[E_f >= thr]
    stage_ts = np.percentile(above, np.linspace(100.0 / GROWTH_STAGES,
                                                100.0, GROWTH_STAGES)) \
        if len(above) else np.array([np.inf])
    for t_stage in stage_ts:
        # ascending sweeps up to this stage's waterline: energy decides
        # claim order, never region ordering
        for _sweep in range(64):
            changed = False
            for f in order_f:
                f = int(f)
                if lab[f] >= 0 or E_f[f] > t_stage:
                    continue
                best_w, best_l = np.inf, -1
                for nb, we in adj_ns[f]:
                    if lab[nb] >= 0 and we < best_w:
                        best_w, best_l = we, int(lab[nb])
                if best_l >= 0:
                    lab[f] = best_l
                    changed = True
            if not changed:
                break
        seed_components((E_f <= t_stage) & (lab < 0), True)
    # sharp-edge-isolated pockets become their own regions
    for s in np.nonzero(lab < 0)[0]:
        s = int(s)
        if lab[s] >= 0:
            continue
        lab[s] = nxt
        stack = [s]
        while stack:
            f = stack.pop()
            for nb, _we in adj_ns[f]:
                if lab[nb] < 0:
                    lab[nb] = nxt
                    stack.append(nb)
        nxt += 1
    lab = np.unique(lab, return_inverse=True)[1]
    return lab, seeds0, int(lab.max()) + 1


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
                normals_coarse=energy['normals_coarse'], seeds=seeds0)


def palette(n=60):
    ''' Deterministic label palette (hue wheel, prototype-style). '''
    rng = np.random.default_rng(11)
    cols = np.empty((n, 4))
    for i, hue in enumerate(rng.random(n)):
        r = np.clip(abs(hue * 6.0 - 3.0) - 1.0, 0, 1)
        g = np.clip(2.0 - abs(hue * 6.0 - 2.0), 0, 1)
        b = np.clip(2.0 - abs(hue * 6.0 - 4.0), 0, 1)
        cols[i] = (r * 0.6 + 0.35, g * 0.6 + 0.35, b * 0.6 + 0.35, 1.0)
    return cols


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
    attr = write_corner_colors(me, tri_loops, 'Regions',
                                label_colors(face_labels, pal))
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
            ('Regions', 'Regions', 'Final region labels'),
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
        # the watershed result is cached too, so a preview-layer change
        # in the redo panel re-executes near-instantly
        ws_key = (self.seed_threshold, self.seed_area)
        if energy_cache.get('ws_key') != ws_key:
            energy_cache['ws'] = watershed(
                energy, scale, self.seed_threshold, self.seed_area)
            energy_cache['ws_key'] = ws_key
        labels, seeds0, n_regions = energy_cache['ws']
        write_attributes(me, tri_loops, labels, energy['E_f'], tris,
                          gather_extras(energy, seeds0), preview=self.preview)
        me.update()
        self.report({'INFO'}, f'Segment Mesh: {n_regions} regions '
                              f'(feature scale {scale:.4f}'
                              f'{", cached fields" if cached else ""})')
        return {'FINISHED'}
