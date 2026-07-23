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
from bpy_extras.view3d_utils import location_3d_to_region_2d

from .maths import local_to_world, point_to_bvec3
from .raycast import raycast_valid_sources


FEATURE_RUN_MARGIN_FACTOR = 2.0 # How far beyond the brush in avg edge lengths to classify feature edges


def source_snap_settings(context):
    ''' (use_fixed, fixed_distance, proximity) for source-feature snapping, from the scene settings.
    Callers that carry their own settings supply these three values directly instead. '''
    snapping = context.scene.retopoflow.snapping
    return (
        getattr(snapping, 'source_edge_use_fixed_distance', False),
        getattr(snapping, 'source_edge_fixed_distance', 0.05),
        getattr(snapping, 'source_edge_proximity', 0.25),
    )


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


class SourceSnapMixin:
    SNAP_STICK_MULT: float = 2.0
    SNAP_CORNER_PROXIMITY: float = 2.0
    SNAP_RELEASE_FLOOR: float = 0.15

    promoted_loop_verts: set = set()
    demoted_verts: set = set()
    loops_strength: float = 0.0
    vert_feature_run: dict = {}   # BMVert -> local feature run id (transient, re-derived per frame)
    run_segments: dict = {}       # run id -> set of source segment indices
    demoted_by_runs: dict = {}    # demoted BMVert -> run ids of the loops that demoted it

    def snap_init_state(self):
        self.snapped_verts: set = set()
        self.snap_target_world: dict = {}
        self.vert_corner_idx: dict = {}

    def snap_grabbed_set(self) -> set:
        ''' Override in each subclass. Returns the set of grabbed BMVerts. '''
        return set()

    def _closest_on_own_run(self, bmv, co_world):
        ''' (closest_point, tangent) on bmv's own feature run when it has one, else on the nearest
        feature. Keeps a vert riding feature A from snapping onto a parallel feature B one face away. '''
        accel = self.source_edge_accel
        run_id = self.vert_feature_run.get(bmv) if self.vert_feature_run else None
        if run_id is not None:
            segs = self.run_segments.get(run_id)
            if segs:
                return accel.closest_point_in_segments(co_world, segs)
        return accel.closest_point_with_tangent(co_world)

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
                # Estimate pixels per world unit from the corner's projection
                p_ref = location_3d_to_region_2d(context.region, context.region_data, corner_w + Vector((occ_release_r, 0, 0)))
                pix_per_unit = ((p_ref - corner_2d).length / occ_release_r) if p_ref else 50.0
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
        snapped_p = accel.closest_point(new_occ_world)
        if snapped_p:
            new_occ_world = Vector(snapped_p)
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
            # Push away from every run whose loop demoted this vert, summed. The attribution is
            # topological and stable, so a vert between two promoted rails settles at the midline
            # instead of being bounced off whichever feature is nearest each frame.
            runs = self.demoted_by_runs.get(bmv) if self.demoted_by_runs else None
            if runs:
                total = Vector((0.0, 0.0, 0.0))
                for run_id in runs:
                    segs = self.run_segments.get(run_id)
                    if not segs: continue
                    result = accel.closest_point_in_segments(new_co_world, segs)
                    if not result: continue
                    to_edge = Vector(result[0]) - new_co_world
                    if 1e-8 < to_edge.length < push_radius:
                        # Reflect away from the edge by the same distance it has intruded.
                        total -= to_edge
                if total.length > 1e-9:
                    return Mi @ (new_co_world + total)
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
                target = self._closest_on_own_run(bmv, free_world)
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
            if dist_corner <= corner_radius:
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
            if tangent_result := self._closest_on_own_run(bmv, bmv_world):
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
                            parallel_3d = parallel_2d / tangent_2d_len
                            candidate = point_to_bvec3(bmv_world + tangent * parallel_3d)
                            constrained = self._closest_on_own_run(bmv, candidate)
                            if constrained is not None:
                                self.snapped_verts.add(bmv)
                                return Mi @ Vector(constrained[0])
                # Fallback: don't slide
                self.snapped_verts.add(bmv)
                return Vector(bmv.co)
        else:
            # snap only fires when moving toward the edge
            if closest_result := self._closest_on_own_run(bmv, new_co_world):
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
