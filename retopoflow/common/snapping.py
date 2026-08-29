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

import math

from mathutils import Vector
from mathutils.bvhtree import BVHTree
from bpy_extras.view3d_utils import location_3d_to_region_2d

from .bmesh import get_bmv_avg_edge_len, get_bmv_next_loop_vert, is_bmvert_corner
from .maths import local_to_world, point_to_bvec3
from .raycast import raycast_valid_sources, raycast_ray_valid_sources, nearest_point_valid_sources


FEATURE_RUN_MARGIN_FACTOR = 2.0 # How far beyond the brush in avg edge lengths to classify feature edges
SLIDE_MAX_GAIN = 5.0 # Caps how fast a snapped vert slides along a feature as that feature turns to point at the camera.


def source_snap_settings(context):
    ''' (use_fixed, fixed_distance, proximity) for source-feature snapping, from the scene settings.
    Callers that carry their own settings supply these three values directly instead. '''
    snapping = context.scene.retopoflow.snapping
    return (
        getattr(snapping, 'source_edge_use_fixed_distance', False),
        getattr(snapping, 'source_edge_fixed_distance', 0.05),
        getattr(snapping, 'source_edge_proximity', 0.25),
    )


SOURCE_EDGE_PROP_NAMES = (
    'source_edge_angle_enabled',
    'source_edge_angle',
    'source_edge_creases',
    'source_edge_seams',
    'source_edge_sharps',
    'source_edge_proximity',
    'source_edge_use_fixed_distance',
    'source_edge_fixed_distance',
    'source_edge_stickiness',
    'source_edge_guide_loops',
)


SNAP_TO_ITEMS = [
    ('NONE',           'None',           'Do not snap vertices to any surface'),
    ('ORIGINAL_MESH',  'Original Mesh',  'Project each vertex back onto the original mesh shape before the operation'),
    ('ALL_VISIBLE',    'All Visible',    'Snap to all visible mesh objects in the scene'),
    ('ALL_SELECTABLE', 'All Selectable', 'Snap to all selectable visible mesh objects in the scene'),
    ('OBJECT',         'Object',         'Snap to a specific object'),
    ('COLLECTION',     'Collection',     'Snap to all mesh objects in a specific collection'),
]


def source_tuple(obj):
    M  = obj.matrix_world
    Mi = M.inverted_safe()
    return (obj, M, Mi, Mi.to_3x3())


def is_snap_candidate(context, obj) -> bool:
    return (
        obj != context.edit_object
        and obj.mode == 'OBJECT'
        and obj.visible_get()
        and obj.type == 'MESH'
        and bool(obj.data.polygons)
    )


def build_snap_sources(context, snap_to, *, snap_object='', snap_collection='') -> list:
    ''' [(obj, M, Mi, Mi_3x3), ...] for a `snap_to` choice, for operators that pick their
    own sources while Retopoflow is not running. Empty for NONE and ORIGINAL_MESH, which
    need no external source. Also used by draw() to warn when a choice finds nothing. '''
    match snap_to:
        case 'ALL_VISIBLE':
            objs = [obj for obj in context.view_layer.objects if is_snap_candidate(context, obj)]
        case 'ALL_SELECTABLE':
            objs = [
                obj for obj in context.view_layer.objects
                if is_snap_candidate(context, obj) and not obj.hide_select
            ]
        case 'OBJECT':
            obj = context.blend_data.objects.get(snap_object)
            objs = [obj] if obj and is_snap_candidate(context, obj) else []
        case 'COLLECTION':
            collection = context.blend_data.collections.get(snap_collection)
            objs = [
                obj for obj in collection.objects
                if is_snap_candidate(context, obj)
            ] if collection else []
        case _:
            objs = []
    return [source_tuple(obj) for obj in objs]


def draw_snap_to_props(props, context, layout, draw_warning):
    ''' The Snap To source picker, for operators that choose their own sources while
    Retopoflow is not running. `draw_warning(layout)` is called when the current choice
    resolves to no usable source. '''
    layout.prop(props, 'snap_to', text='Snap To')
    if props.snap_to == 'OBJECT':
        layout.prop_search(props, 'snap_object', context.blend_data, 'objects', text='Object')
        if props.snap_object and not build_snap_sources(context, 'OBJECT', snap_object=props.snap_object):
            draw_warning(layout)
    elif props.snap_to == 'COLLECTION':
        layout.prop_search(props, 'snap_collection', context.blend_data, 'collections', text='Collection')
        if props.snap_collection and not build_snap_sources(context, 'COLLECTION', snap_collection=props.snap_collection):
            draw_warning(layout)
    elif props.snap_to in ('ALL_VISIBLE', 'ALL_SELECTABLE'):
        if not build_snap_sources(context, props.snap_to):
            draw_warning(layout)


def build_island_bvh(matrix_world, seed_verts, rings: int = 3) -> 'BVHTree | None':
    ''' Builds a world-space BVH from the original face geometry surrounding the selected verts.
    Three face steps outwards gives enough buffer that no selected vert can project onto geometry
    outside the patch while keeping the BVH fast. '''
    face_set = {
        bmf for bmv in seed_verts
        for bmf in bmv.link_faces
        if not bmf.hide
    }
    frontier = set(face_set)

    for i in range(rings):
        next_frontier = set()
        for bmf in frontier:
            for bme in bmf.edges:
                for adj in bme.link_faces:
                    if not adj.hide and adj not in face_set:
                        next_frontier.add(adj)
        face_set |= next_frontier
        frontier = next_frontier
        if not frontier:
            break  # mesh boundary reached, nothing left to expand into

    if not face_set:
        return None

    M = matrix_world # World space matches relax_verts' projections
    poly_verts   = []
    poly_indices = []
    for bmf in face_set:
        start = len(poly_verts)
        poly_verts.extend(M @ fv.co for fv in bmf.verts)
        poly_indices.append(list(range(start, start + len(bmf.verts))))

    return BVHTree.FromPolygons(poly_verts, poly_indices)


def seed_source_snap_props(context, props):
    ''' Copy the scene's source-feature snapping settings onto an operator's matching props.
    Call from invoke() while RF is running so each fresh run starts from the tool's settings. '''
    snapping = context.scene.retopoflow.snapping
    for name in SOURCE_EDGE_PROP_NAMES:
        setattr(props, name, getattr(snapping, name))


def snap_along_normal(context, co_local, matrix_world, matrix_world_inv,
                     along_local=None, max_correction=None):
    ''' Project a local-space position onto the source, or None if nothing is in reach. '''
    # cast along the surface normal instead of taking the nearest point to reduce noise on bumpy surfaces
    co_world = matrix_world @ co_local
    if along_local is not None:
        d = (matrix_world_inv.transposed() @ Vector((*along_local, 0.0))).xyz
        if d.length_squared > 1e-12:
            d.normalize()
            hits = [
                hit
                for sign in (1, -1)
                if (hit := raycast_ray_valid_sources(
                    context, (Vector((*co_world, 1.0)), Vector((*(d * sign), 0.0))),
                    world=True, respect_clip_planes=True,
                )) is not None
            ]
            if hits:
                hit = min(hits, key=lambda h: (h - co_world).length)
                # a ray that travelled too far grazed a crease or shot past a silhouette
                if max_correction is None or (hit - co_world).length <= max_correction:
                    return matrix_world_inv @ hit
    snapped = nearest_point_valid_sources(context, co_world, respect_clip_planes=True)
    return (matrix_world_inv @ snapped) if snapped else None


def smoothed_normals(points, normals, window):
    ''' Box average of per-point source normals over +/-`window` of arclength (prefix sums, O(n)). '''
    n = len(points)
    if n <= 2 or window <= 0: return list(normals)
    cumul = [0.0]
    for i in range(1, n):
        cumul.append(cumul[-1] + (Vector(points[i]) - Vector(points[i - 1])).length)
    pre = [Vector((0.0, 0.0, 0.0))]
    for no in normals:
        pre.append(pre[-1] + Vector(no))
    out, j0, j1 = [], 0, 0
    for i in range(n):
        while j0 < i and cumul[j0] < cumul[i] - window: j0 += 1
        while j1 < n - 1 and cumul[j1 + 1] <= cumul[i] + window: j1 += 1
        v = pre[j1 + 1] - pre[j0]
        out.append(v.normalized() if v.length_squared > 0 else Vector(normals[i]))
    return out


def source_snap_radius(ref_len_world, *, use_fixed, fixed_distance, avg_edge_factor):
    ''' World space radius within which a vert snaps to a source feature.
    ref_len_world must already be world space. '''
    return fixed_distance if use_fixed else ref_len_world * avg_edge_factor


def fold_crease(p_local, p_before, n_before, p_after, n_after, matrix_world, matrix_world_inv,
                *, source_accel=None, feature_radius=0.0, max_plane_dist):
    ''' Where a rung sitting on a fold should lie. Returns (crease_point, crease_dir) in
    local space, or None to leave the rung where it is. '''
    nb, na = Vector(n_before), Vector(n_after)
    u = nb.cross(na)
    uu = u.dot(u)
    if uu < 1e-9:
        return None  # faces near parallel so no crease
    u_hat = u / math.sqrt(uu)

    # crease point: source feature edge when feature detection is on, else plane intersection
    if source_accel and feature_radius > 0:
        p_world = matrix_world @ p_local
        closest = source_accel.closest_point(p_world)
        if closest and (Vector(closest) - p_world).length <= feature_radius:
            return (matrix_world_inv @ Vector(closest), u_hat)
    # intersection of the two adjacent face planes {nb . x = d1}, {na . x = d2}
    d1, d2 = nb.dot(Vector(p_before)), na.dot(Vector(p_after))
    pt = (na.cross(u) * d1 + u.cross(nb) * d2) / uu  # a point on the intersection line
    pl = Vector(p_local)
    proj = pt + u_hat * (pl - pt).dot(u_hat)  # project the rung centerline onto the line
    if (proj - pl).length > max_plane_dist:
        return None  # implausible plane fit, keep the original position
    return (proj, u_hat)


class FeatureRunsMixin:
    ''' Shared source feature local loop runs machinery for snapping: near-vert collection,
    local run labeling, per-run guide-loop election, run-constrained lookups, and the
    demotion rules that keep parallel features from fighting over each other's verts.

    Host classes must provide: matrix_world, matrix_world_inv, scale_avg,
    source_edge_accel (SourceAccel | None), source_sharp_proximity, and the overridable
    knobs below. All run state carries safe class-level defaults so light consumers
    (e.g. RFOperator_Translate) can use SourceSnapMixin without ever populating it. '''

    SNAP_CORNER_PROXIMITY: float = 2.0
    corner_owner_factor: float = SNAP_CORNER_PROXIMITY  # Relax assigns its own per relax_verts call

    # Shared transient state, re-derived once per user-facing step.
    promoted_loop_verts    : set   = set()
    demoted_verts          : set   = set()
    loops_strength         : float = 0.0
    vert_feature_run       : dict  = {}    # BMVert -> local feature run id
    run_segments           : dict  = {}    # run id -> set of source segment indices
    run_of_seg             : dict  = {}    # source segment index -> run id
    demoted_by_runs        : dict  = {}    # demoted BMVert -> run ids of the loops that demoted it
    guide_loop_seeds       : list  = []    # [(v0, v1)] persisted seed edges, one loop each
    verts_near_source_edge : dict  = {}    # BMVert -> local diff to nearest feature
    vert_seed_seg         : dict  = {}    # BMVert -> nearest source segment index (proximity-only)

    # ------------------------------------------------------------------ knobs

    def snap_proximity_world(self, bmv) -> float:
        ''' World-space distance within which bmv counts as near a source feature.
        Tweak/Translate use a stroke-fixed radius; Relax uses a per-vert edge-length basis. '''
        raise NotImplementedError

    def bmv_avg_edge_len(self, bmv) -> float:
        ''' Average link-edge length for bmv. Relax overrides this with a per-step cache. '''
        return get_bmv_avg_edge_len(bmv)

    def feature_run_extra_margin(self) -> float:
        ''' Extra arc length for the run window. Covering at least the brush diameter means
        promoted verts anywhere under the brush find their own run's geometry beneath them,
        however sparse the seeds are. '''
        return 0.0

    def corner_snap_threshold_world(self, bmv, factor) -> float:
        ''' World-space radius for source-corner tests around bmv. '''
        return self.snap_proximity_world(bmv) * factor

    def guide_seed_edges_by_run(self, exclude_runs) -> dict:
        ''' Retopo edges whose both endpoints ride the same local feature run, grouped by run.
        Requiring a shared run keeps a rung spanning two parallel features from seeding a loop
        perpendicular to them. Each tool supplies its own candidate policy. '''
        raise NotImplementedError

    def guide_anchor_co_local(self) -> Vector:
        ''' Local-space anchor (brush centre) that seed election measures against. '''
        raise NotImplementedError

    def seed_still_valid(self, gv0, gv1, members) -> bool:
        ''' Whether a persisted seed edge may be re-elected this step. '''
        return gv0.is_valid and gv1.is_valid and gv0 in members and gv1 in members

    def keep_reelected_loop(self, promoted, members) -> bool:
        ''' Whether a re-elected loop should persist (e.g. Tweak drops loops pulling away). '''
        return True

    # ------------------------------------------------- collection & labeling

    def collect_verts_near_source_edge(self, candidates) -> dict:
        ''' Returns candidate verts and their local space vectors to the closest point on the
        source edge, length = distance to edge. Also records each vert's nearest segment index
        as a run labeling seed. '''
        result = {}
        self.vert_seed_seg = {}
        if not self.source_edge_accel:
            return result
        Mi = self.matrix_world_inv
        for bmv in candidates:
            if not bmv.link_edges: continue
            bmv_world = local_to_world(bmv.co, self.matrix_world)
            closest = self.source_edge_accel.closest_point_with_index(bmv_world)
            if not closest: continue
            closest_v, _tangent, seg_idx = closest
            diff = Mi @ Vector(closest_v) - bmv.co
            dist = diff.length
            if dist * self.scale_avg <= self.snap_proximity_world(bmv):
                # Seeds feed the run labeling and deliberately skip the normal-facing gate below
                self.vert_seed_seg[bmv] = seg_idx
                if dist < 1e-8 or (diff / dist).dot(bmv.normal) > 0.3:
                    result[bmv] = diff
        return result

    def refresh_feature_runs(self):
        ''' Label locally-connected feature runs around the near verts and tag each near vert
        with its run id. Locality is geodesic along the feature, so two parallel features or
        two windings of a spiral one face apart get distinct ids even when close together. '''
        self.vert_feature_run = {}
        self.run_segments = {}
        self.run_of_seg = {}
        if not self.source_edge_accel or not self.vert_seed_seg:
            return
        avg_lens = [self.bmv_avg_edge_len(v) for v in self.vert_seed_seg if v.link_edges]
        if not avg_lens:
            return
        margin_world = max(
            (sum(avg_lens) / len(avg_lens)) * self.scale_avg * FEATURE_RUN_MARGIN_FACTOR,
            self.feature_run_extra_margin(),
        )
        self.run_of_seg, self.run_segments = self.source_edge_accel.local_runs(set(self.vert_seed_seg.values()), margin_world)
        self.vert_feature_run = {v: self.run_of_seg[s] for v, s in self.vert_seed_seg.items() if s in self.run_of_seg}

    def feature_run_at(self, v):
        ''' Run id of the feature v currently rides, by proximity alone, or None. Deliberately
        more forgiving than the near set (no normal gate, 1.5x slack) so demotion sparing does
        not flicker off when a vert jiggles slightly off its feature. '''
        run_id = self.vert_feature_run.get(v)
        if run_id is not None:
            return run_id
        if not self.source_edge_accel or not self.run_of_seg or not v.link_edges:
            return None
        result = self.source_edge_accel.closest_point_with_index(local_to_world(v.co, self.matrix_world))
        if not result:
            return None
        pt, _tangent, seg_idx = result
        if (self.matrix_world_inv @ Vector(pt) - v.co).length * self.scale_avg > self.snap_proximity_world(v) * 1.5:
            return None
        return self.run_of_seg.get(seg_idx)

    # -------------------------------------------------- run-constrained lookups

    def closest_on_own_run(self, bmv, co_world):
        ''' (closest_point, tangent) on bmv's own feature run when it has one, else on the
        nearest feature. Keeps a vert riding feature A from targeting a parallel feature B. '''
        run_id = self.vert_feature_run.get(bmv) if self.vert_feature_run else None
        if run_id is not None:
            segs = self.run_segments.get(run_id)
            if segs:
                return self.source_edge_accel.closest_point_in_segments(co_world, segs)
        return self.source_edge_accel.closest_point_with_tangent(co_world)

    def demoted_net_push_world(self, bmv, co_world_pt, max_dist):
        ''' Total world space push vector for a demoted vert. Pushed away from every run whose loop
        demoted it (within max_dist), summed. The attribution is topological and stable, so a
        vert between two promoted rails settles at the midline instead of being bounced off whichever
        feature is nearest each step. None = no run attribution, caller falls back to the nearest-feature push. '''
        runs = self.demoted_by_runs.get(bmv) if self.demoted_by_runs else None
        if not runs: return None
        total = Vector((0.0, 0.0, 0.0))
        for run_id in runs:
            segs = self.run_segments.get(run_id)
            if not segs: continue
            result = self.source_edge_accel.closest_point_in_segments(co_world_pt, segs)
            if not result: continue
            to_edge = Vector(result[0]) - co_world_pt
            if 1e-8 < to_edge.length <= max_dist:
                total -= to_edge
        return total

    def source_corner_of_vert(self, bmv, world_threshold):
        ''' (corner_co_world, corner_idx, distance) when bmv is within world_threshold of a
        source corner, else None. '''
        if not self.source_edge_accel: return None
        cr = self.source_edge_accel.find_corner(local_to_world(bmv.co, self.matrix_world))
        if cr and cr[2] < world_threshold:
            return cr
        return None

    def is_on_source_corner(self, v) -> bool:
        return self.source_corner_of_vert(v, self.corner_snap_threshold_world(v, 0.05)) is not None

    def is_on_source_edge(self, v) -> bool:
        # True if v currently lies on (within snap proximity of) a source feature edge.
        # Lets guide-loop demotion spare verts that legitimately ride a source edge.
        if not self.source_edge_accel or not v.link_edges:
            return False
        closest = self.source_edge_accel.closest_point(local_to_world(v.co, self.matrix_world))
        if not closest:
            return False
        return (self.matrix_world_inv @ Vector(closest) - v.co).length * self.scale_avg <= self.snap_proximity_world(v)

    def corner_allowed_for_vert(self, bmv, corner_co) -> bool:
        ''' Whether bmv may snap to the corner at corner_co. A vert with a known run may only be
        captured by corners on that run, so a parallel feature's corner can't grab it. Corners
        outside the labeled window are allowed, so window edges never reject a vert's own corner. '''
        run_id = self.vert_feature_run.get(bmv) if self.vert_feature_run else None
        if run_id is None: return True
        segs = self.run_segments.get(run_id)
        if not segs: return True
        accel = self.source_edge_accel
        if accel.corner_on_segments(corner_co, segs): return True
        return not any(
            accel.corner_on_segments(corner_co, other)
            for rid, other in self.run_segments.items() if rid != run_id
        )

    # -------------------------------------------------------- loop election

    def is_loop_continuation(self, v) -> bool:
        if self.is_on_source_corner(v):
            return False
        if any(e.is_boundary for e in v.link_edges):
            return len(v.link_edges) == 3
        return len(v.link_edges) == 4 and len(v.link_faces) == 4

    def elect_loop_from_edge(self, v0, v1, run_id):
        ''' Walk the (v0, v1) retopo loop in both directions and return (promoted, demoted) or None.
        run_id is the loop's feature run so verts riding a different run are never demoted and the
        rail on a parallel feature one face away keeps its own snap. '''
        def rides_other_run(v):
            v_run = self.feature_run_at(v)
            if v_run is None:
                return False
            # On some feature with the loop's run unknown: spare, don't risk pushing it off.
            return run_id is None or v_run != run_id

        promoted = set()
        limit = 100
        def walk_from(cur, prev):
            while cur not in promoted and len(promoted) < limit:
                # The current vert is always part of the loop, including the corner the loop ends on
                promoted.add(cur)
                if not self.is_loop_continuation(cur): break
                nxt = get_bmv_next_loop_vert(prev, cur)
                if nxt is None: break
                prev, cur = cur, nxt

        walk_from(v0, v1)
        walk_from(v1, v0)
        if not promoted:
            return None  # guide edge sits on a corner/pole

        # Terminal verts are those the walk stopped on, corners, poles, and on source corners
        terminal_at_corner = {
            v for v in promoted
            if not self.is_loop_continuation(v) and (
                not any(e.is_boundary for e in v.link_edges)
                or self.is_on_source_corner(v)
            )
        }

        demoted = set()
        for v in promoted:
            if v in terminal_at_corner:
                # All direct edge-neighbors of the corner are protected
                # Face-diagonal verts, those sharing a face but not an edge with the corner, are demoted
                all_adj = {bme.other_vert(v) for bme in v.link_edges}
                v_is_boundary = any(e.is_boundary for e in v.link_edges)
                for bmf in v.link_faces:
                    if len(bmf.verts) != 4: continue
                    for fv in bmf.verts:
                        if fv is v or fv in all_adj: continue
                        # A vert that itself rides a source edge (e.g. the perpendicular feature
                        # meeting the loop where it ends at a corner) belongs there, so don't demote it.
                        if is_bmvert_corner(fv) or rides_other_run(fv) or self.is_on_source_edge(fv): continue
                        # When the loop ends at a boundary corner, never demote its fellow boundary verts.
                        if v_is_boundary and any(e.is_boundary for e in fv.link_edges): continue
                        demoted.add(fv)
            else:
                # Demote adjacent loop verts not already promoted
                for bme in v.link_edges:
                    nb = bme.other_vert(v)
                    if nb not in promoted and not rides_other_run(nb) and self.is_loop_continuation(nb):
                        demoted.add(nb)

        return promoted, demoted

    def seed_guide_loops(self, exclude_runs):
        ''' Brush mode: pick one seed edge per local feature run not in exclude_runs — the edge
        whose midpoint is closest to the brush centre. Returns [(v0, v1, run_id), ...]. '''
        run_edges = self.guide_seed_edges_by_run(exclude_runs)
        if not run_edges: return []
        anchor = self.guide_anchor_co_local()
        seeds = []
        for run_id, run_bmes in run_edges.items():
            guide_edge = min(
                run_bmes,
                key=lambda e: ((e.verts[0].co + e.verts[1].co) * 0.5 - anchor).length,
            )
            seeds.append((guide_edge.verts[0], guide_edge.verts[1], run_id))
        return seeds

    def seed_all_guide_loops(self):
        ''' Brush-less mode: elect one guide loop per local feature run near the selection,
        anchored at each run's own centroid. Recomputed every step, no seed persistence. '''
        run_edges = self.guide_seed_edges_by_run(frozenset())
        if not run_edges:
            return

        all_promoted = set()
        all_demoted = set()

        for run_id, component in run_edges.items():
            # Elect the edge whose midpoint is closest to the component's own centroid
            comp_center = sum(
                ((bme.verts[0].co + bme.verts[1].co) * 0.5 for bme in component),
                Vector((0.0, 0.0, 0.0))
            ) / len(component)
            guide_edge = min(
                component,
                key=lambda e: ((e.verts[0].co + e.verts[1].co) * 0.5 - comp_center).length,
            )
            result = self.elect_loop_from_edge(guide_edge.verts[0], guide_edge.verts[1], run_id)
            if result is None:
                continue
            promoted, demoted = result
            all_promoted.update(promoted)
            all_demoted.update(demoted)
            # The loop's run overrides the nearest-feature id for its promoted verts
            for v in promoted:
                self.vert_feature_run[v] = run_id
            # Remember which runs demoted each vert so the demoted push has a stable,
            # per-run direction (summed) instead of chasing the nearest feature.
            for v in demoted:
                self.demoted_by_runs.setdefault(v, set()).add(run_id)

        # A vert elected by one loop must not be demoted by another
        self.promoted_loop_verts = all_promoted
        self.demoted_verts = all_demoted - all_promoted
        self.guide_loop_seeds = []

    def clear_guide_state(self):
        # Fresh containers, never .clear(): the class-level defaults are shared across instances.
        self.promoted_loop_verts = set()
        self.demoted_verts = set()
        self.demoted_by_runs = {}
        self.guide_loop_seeds = []

    def release_feature_runs(self):
        ''' Drop every BMVert this mixin is holding. Call from the consumer's finish(). '''
        self.clear_guide_state()
        self.vert_seed_seg = {}
        self.vert_feature_run = {}
        self.run_segments = {}
        self.run_of_seg = {}

    def update_source_context_brush(self, members):
        ''' Brush mode: one promoted guide loop per feature run over the `members` vert set.
        Keep each elected loop's seed edge until it leaves the brush region, but re-derive
        promoted/demoted from it each step so a vert that snaps to a source corner mid-stroke is
        recognised as a corner for the rest of the stroke. '''
        self.promoted_loop_verts = set()
        self.demoted_verts = set()
        kept_seeds = []
        claimed_runs = set()
        loops = []

        # A seed is dropped when it leaves the working set or its loop no longer qualifies.
        for (gv0, gv1) in self.guide_loop_seeds:
            if not self.seed_still_valid(gv0, gv1, members): continue
            run_id = self.vert_feature_run.get(gv0)
            if run_id is None:
                run_id = self.vert_feature_run.get(gv1)
            result = self.elect_loop_from_edge(gv0, gv1, run_id)
            if result is None: continue
            promoted, demoted = result
            if not self.keep_reelected_loop(promoted, members): continue
            kept_seeds.append((gv0, gv1))
            if run_id is not None:
                claimed_runs.add(run_id)
            loops.append((run_id, promoted, demoted))

        # Elect a loop for every feature run in the working set that doesn't have one yet.
        if self.verts_near_source_edge:
            for (v0, v1, run_id) in self.seed_guide_loops(claimed_runs):
                result = self.elect_loop_from_edge(v0, v1, run_id)
                if result is None: continue
                kept_seeds.append((v0, v1))
                claimed_runs.add(run_id)
                loops.append((run_id, *result))

        self.guide_loop_seeds = kept_seeds
        for run_id, promoted, demoted in loops:
            self.promoted_loop_verts |= promoted
            self.demoted_verts |= demoted
            # The loop's run overrides the nearest-feature id for its promoted verts.
            if run_id is not None:
                for v in promoted:
                    self.vert_feature_run[v] = run_id
                # Track which runs demoted each vert. The demoted push sums these stable
                # per-run directions instead of chasing the nearest feature.
                for v in demoted:
                    self.demoted_by_runs.setdefault(v, set()).add(run_id)
        # A vert elected by one loop must not be demoted by another.
        self.demoted_verts -= self.promoted_loop_verts

    def apply_corner_owner_demotion(self):
        ''' The vert that owns each source corner demotes the face-mates that are not one step
        away, except those that themselves ride a source edge or a different run. Usually the
        diagonal opposite verts. One vert per corner, otherwise every nearby vert fans demotion
        across its faces. '''
        if not (self.source_edge_accel and self.promoted_loop_verts and self.verts_near_source_edge):
            return
        corner_owner = {}
        for cv in self.verts_near_source_edge:
            corner = self.source_corner_of_vert(cv, self.corner_snap_threshold_world(cv, self.corner_owner_factor))
            if not corner: continue
            _, corner_idx, dist_corner = corner
            if corner_idx not in corner_owner or dist_corner < corner_owner[corner_idx][0]:
                corner_owner[corner_idx] = (dist_corner, cv)
        for _dist, cv in corner_owner.values():
            # All direct neighbors of the corner must be protected
            all_adj = {bme.other_vert(cv) for bme in cv.link_edges}
            cv_is_boundary = any(e.is_boundary for e in cv.link_edges)
            cv_run = self.vert_feature_run.get(cv)
            for bmf in cv.link_faces:
                if len(bmf.verts) != 4: continue  # only meaningful for quads
                for fv in bmf.verts:
                    if fv is cv or fv in all_adj: continue
                    if fv in self.promoted_loop_verts or is_bmvert_corner(fv) or self.is_on_source_edge(fv): continue
                    fv_run = self.feature_run_at(fv)
                    if fv_run is not None and (cv_run is None or fv_run != cv_run): continue
                    # When the owner is a boundary corner, never demote its fellow boundary verts.
                    if cv_is_boundary and any(e.is_boundary for e in fv.link_edges): continue
                    self.demoted_verts.add(fv)
                    if cv_run is not None:
                        self.demoted_by_runs.setdefault(fv, set()).add(cv_run)


class SourceSnapMixin(FeatureRunsMixin):
    SNAP_STICK_MULT: float = 2.0
    SNAP_RELEASE_FLOOR: float = 0.15

    def snap_init_state(self):
        self.snapped_verts: set = set()
        self.snap_target_world: dict = {}
        self.vert_corner_idx: dict = {}

    def snap_release_state(self):
        ''' Mirror of snap_init_state, for the consumer's finish(). Same reason as
        release_feature_runs: these are keyed by BMVert and must not outlive the bmesh. '''
        self.snap_init_state()
        self.release_feature_runs()

    def snap_grabbed_set(self) -> set:
        ''' Override in each subclass. Returns the set of grabbed BMVerts. '''
        return set()

    def snap_proximity_world(self, bmv) -> float:
        ''' Mixin consumers (Tweak, Translate) use a stroke-fixed world radius. '''
        return self.stroke_snap_radius

    def find_corner_occupant(self, corner_co_world, incoming_bmv, radius):
        ''' Find a vert other than incoming_bmv sitting in a source corner.
        Check snapped_verts first, fallback to accel so the full bmesh is never iterated linearly. '''
        corner_w = Vector(corner_co_world)

        # Fast path: verts snapped this stroke are the most likely occupants
        for v in self.snapped_verts:
            if v is incoming_bmv: continue
            if (local_to_world(v.co, self.matrix_world) - corner_w).length <= radius:
                return v

        # Fallback: Accel covers verts snapped in previous strokes
        if self.vert_accel:
            tight_radius = radius * 0.5
            candidates = self.vert_accel.get(corner_w, tight_radius)
            best_v, best_dist = None, float('inf')
            for v in candidates:
                if v is incoming_bmv: continue
                d = (local_to_world(v.co, self.matrix_world) - corner_w).length
                if d < best_dist:
                    best_dist = d
                    best_v = v
            return best_v

        return None

    def kick_corner_occupant(self, occupant, corner_co, incoming_bmv, context=None, stroke_disp_2d=None):
        ''' Move vert off corner to make room for incoming vert. '''

        M, Mi = self.matrix_world, self.matrix_world_inv
        accel = self.source_edge_accel
        if not accel or context is None: return
        corner_w = Vector(corner_co)

        occ_snap_r    = self.stroke_snap_radius
        occ_release_r = occ_snap_r * (1.0 + self.stickiness * self.SNAP_STICK_MULT) * 1.1

        # Determine kick direction via a screen-space bump + raycast
        kick_dir_world = None

        incoming_world = local_to_world(incoming_bmv.co, M)
        corner_2d  = location_3d_to_region_2d(context.region, context.region_data, corner_w)
        incoming_2d = location_3d_to_region_2d(context.region, context.region_data, incoming_world)

        if corner_2d is not None and incoming_2d is not None:
            approach_2d = corner_2d - incoming_2d
            approach_2d_len = approach_2d.length
            if approach_2d_len < 1e-8 and stroke_disp_2d is not None:
                approach_2d     = stroke_disp_2d         # degenerate: fall back to stroke
                approach_2d_len = approach_2d.length
            if approach_2d_len > 1e-8:
                # Step past the corner in the kick direction by the release distance, in pixels
                kick_2d_norm = approach_2d / approach_2d_len
                # Pixels per world unit at the corner, measured perpendicular to the view direction.
                view_right = context.region_data.view_rotation @ Vector((1, 0, 0))
                p_ref = location_3d_to_region_2d(context.region, context.region_data, corner_w + view_right)
                pix_per_unit = (p_ref - corner_2d).length if p_ref is not None else 50.0
                sample_2d = corner_2d + kick_2d_norm * occ_release_r * pix_per_unit
                hit = raycast_valid_sources(context, sample_2d, respect_clip_planes=True)
                if hit:
                    sample_world = Vector(hit['co_world'])
                    d = sample_world - corner_w
                    if d.length > 1e-8:
                        kick_dir_world = d / d.length


        if kick_dir_world is None:
            # No raycast hit, use approach vector directly
            d = incoming_world - corner_w   # away from incoming
            if d.length > 1e-8:
                kick_dir_world = -(d / d.length)   # negate: we want to move away
            else:
                return  # can't determine direction

        new_occ_world = corner_w + kick_dir_world * occ_release_r
        # Re-snap the kicked occupant onto its own feature run.
        # The global nearest point could drop it onto a parallel feature one face away.
        snapped = self.closest_on_own_run(occupant, new_occ_world)
        if snapped:
            new_occ_world = Vector(snapped[0])
        occupant.co = Mi @ new_occ_world
        self.vert_corner_idx.pop(occupant, None)
        self.snapped_verts.discard(occupant)
        self.snap_target_world.pop(occupant, None)

    def snap_to_source_feature(self, bmv, new_co, falloff, context=None, disp_2d=None, stroke_disp_2d=None, free_co=None):
        ''' Snap a dragged vert onto the nearest source feature edge/corner. '''

        accel = self.source_edge_accel
        if not accel or not bmv.link_edges:
            return new_co

        snap_radius = self.stroke_snap_radius * max(falloff, 0.0)

        M, Mi = self.matrix_world, self.matrix_world_inv
        new_co_world = local_to_world(new_co, M)

        # Promoted verts use a wider snap radius and always snap within range.
        # Demoted verts are actively pushed away from the feature when they stray too close.
        # Unclassified verts snap only when moving toward the feature, then stay stuck.
        is_promoted = bool(self.promoted_loop_verts) and bmv in self.promoted_loop_verts
        is_demoted  = bool(self.demoted_verts)       and bmv in self.demoted_verts
        is_snapped  = bmv in self.snapped_verts

        if snap_radius <= 0.0:
            if not is_snapped:
                self.vert_corner_idx.pop(bmv, None) # Clean up corner state
                return new_co
            return Vector(bmv.co) # Keep it pinned

        if is_demoted:
            # Push away when they stray into the snap zone
            self.snapped_verts.discard(bmv)
            self.vert_corner_idx.pop(bmv, None)
            self.snap_target_world.pop(bmv, None)
            push_radius = snap_radius * 0.5 * self.loops_strength
            # Push away from every run whose loop demoted this vert,
            # summed and reflecting away by the distance it has intruded.
            push = self.demoted_net_push_world(bmv, new_co_world, push_radius)
            if push is not None:
                if push.length > 1e-9:
                    return Mi @ (new_co_world + push)
                return new_co
            if closest_p := accel.closest_point(new_co_world):
                to_edge = Vector(closest_p) - new_co_world
                if to_edge.length < push_radius:
                    # Reflect away from the edge by the same distance it has intruded.
                    return Mi @ (new_co_world - to_edge)
            return new_co

        if is_promoted:
            snap_in_radius = self.stroke_snap_radius * 1.5
            release_radius = self.stroke_snap_radius * 1.5 * (self.SNAP_RELEASE_FLOOR + self.stickiness * self.SNAP_STICK_MULT)
        else:
            snap_in_radius = self.stroke_snap_radius
            release_radius = self.stroke_snap_radius * (self.SNAP_RELEASE_FLOOR + self.stickiness * self.SNAP_STICK_MULT)

        # Corners snap in from a wider radius and their stay/release radius must scale the same way.
        # Otherwise the band between the two is unstable and the vert vibrates back and forth.
        corner_snap_in_radius = snap_in_radius * self.SNAP_CORNER_PROXIMITY
        corner_release_radius = release_radius * self.SNAP_CORNER_PROXIMITY

        # Release check for snapped verts
        if is_snapped and free_co is not None:
            free_world = local_to_world(free_co, M)
            if bmv in self.vert_corner_idx:
                # Corner-snapped: hold against the corner itself with the corner-scaled radius, so the
                # tighter edge release can't free it while it's still inside the corner's snap-in band.
                corner = accel.find_corner(free_world)
                released = corner is not None and corner[2] > corner_release_radius
            else:
                target = self.closest_on_own_run(bmv, free_world)
                released = target is not None and (free_world - Vector(target[0])).length > release_radius
            if released:
                self.snapped_verts.discard(bmv)
                self.vert_corner_idx.pop(bmv, None)
                self.snap_target_world.pop(bmv, None)
                return Vector(free_co)
        elif not is_snapped:
            self.snap_target_world.pop(bmv, None)

        disp_world = M.to_3x3() @ (new_co - bmv.co) # Drag dispalcement

        # Corners take priority over edges
        was_on_corner = bmv in self.vert_corner_idx
        if is_snapped:
            corner_radius = corner_release_radius
        else:
            corner_radius = corner_snap_in_radius  # wider snap-in only

        snapped_to_corner = False
        snapped_co_corner = None
        if corner := accel.find_corner(new_co_world):
            co_corner, corner_idx, dist_corner = corner
            # A vert with a known feature run may only be captured by corners on that run.
            # A corner of a parallel feature must not grab it across the gap.
            if dist_corner <= corner_radius and self.corner_allowed_for_vert(bmv, co_corner):
                grabbed_set = self.snap_grabbed_set()
                occupant = self.find_corner_occupant(co_corner, bmv, corner_radius)
                allow_snap = True
                if occupant is not None:
                    if occupant in grabbed_set:
                        # Both verts are grabbed: prevent collapse
                        allow_snap = False
                    else:
                        # Occupant is not being dragged: kick it out
                        self.kick_corner_occupant(occupant, co_corner, bmv, context, stroke_disp_2d)
                if allow_snap:
                    to_corner = Vector(co_corner) - new_co_world
                    # The direction check only gates the initial snap-in. Once on a corner,
                    # the vert is exactly on the corner, so the drag displacement always points away.
                    if was_on_corner or to_corner.length < 1e-8 or disp_world.dot(to_corner) > 0:
                        self.snapped_verts.add(bmv)
                        self.vert_corner_idx[bmv] = corner_idx
                        snapped_to_corner = True
                        snapped_co_corner = co_corner

        if snapped_to_corner:
            return Mi @ Vector(snapped_co_corner)

        self.vert_corner_idx.pop(bmv, None)
        if was_on_corner:
            self.snapped_verts.discard(bmv)
            self.snap_target_world.pop(bmv, None)
            is_snapped = False

        # Edge snapping
        if is_snapped:
            # proximity lookup so a fast cursor jump can't cause a large per-frame new_co_world that bypasses drift-based release
            bmv_world = local_to_world(bmv.co, M)
            if tangent_result := self.closest_on_own_run(bmv, bmv_world):
                # Slide along the edge only for the screen-space parallel brush movement
                if context is not None and disp_2d is not None:
                    _, tangent = tangent_result
                    p0 = location_3d_to_region_2d(context.region, context.region_data, bmv_world)
                    p1 = location_3d_to_region_2d(context.region, context.region_data, bmv_world + tangent)
                    if p0 is not None and p1 is not None:
                        tangent_2d = p1 - p0
                        tangent_2d_len = tangent_2d.length
                        if tangent_2d_len > 1e-8:
                            tangent_2d_norm = tangent_2d / tangent_2d_len
                            parallel_2d = disp_2d.dot(tangent_2d_norm)
                            # A feature running at the viewer projects to almost nothing, so dividing by that blows up the distance.
                            # Floor the divisor at the screen length of a unit world vector perpendicular to the view,
                            # so the slide tracks the cursor exactly while the feature reads on
                            # screen and tops out at SLIDE_MAX_GAIN once it does not.
                            view_right = context.region_data.view_rotation @ Vector((1, 0, 0))
                            p_ref = location_3d_to_region_2d(context.region, context.region_data, bmv_world + view_right)
                            px_per_unit = (p_ref - p0).length if p_ref is not None else 0.0
                            parallel_3d = parallel_2d / max(tangent_2d_len, px_per_unit / SLIDE_MAX_GAIN)
                            candidate = point_to_bvec3(bmv_world + tangent * parallel_3d)
                            constrained = self.closest_on_own_run(bmv, candidate)
                            if constrained is not None:
                                self.snapped_verts.add(bmv)
                                return Mi @ Vector(constrained[0])
                # Fallback: don't slide
                self.snapped_verts.add(bmv)
                return Vector(bmv.co)
        else:
            # snap only fires when moving toward the edge
            if closest_result := self.closest_on_own_run(bmv, new_co_world):
                p_vec = Vector(closest_result[0])
                to_edge = p_vec - new_co_world
                if to_edge.length <= snap_in_radius:
                    # was_on_corner guard prevents re-snapping to an edge immediately after a corner releases
                    if (not was_on_corner and to_edge.length < snap_in_radius) or disp_world.dot(to_edge) > 0:
                        self.snapped_verts.add(bmv)
                        return Mi @ p_vec

        # Out of range: release
        self.snapped_verts.discard(bmv)
        self.snap_target_world.pop(bmv, None)
        return new_co
