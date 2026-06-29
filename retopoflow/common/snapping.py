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

from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d

from .maths import local_to_world, point_to_bvec3
from .raycast import raycast_valid_sources


class SourceSnapMixin:
    SNAP_STICK_MULT: float = 2.0
    SNAP_CORNER_PROXIMITY: float = 2.0
    SNAP_RELEASE_FLOOR: float = 0.15

    promoted_loop_verts: set = set()
    demoted_verts: set = set()
    loops_strength: float = 0.0

    def snap_init_state(self):
        self.snapped_verts: set = set()
        self.snap_target_world: dict = {}
        self.vert_corner_idx: dict = {}

    def snap_grabbed_set(self) -> set:
        ''' Override in each subclass. Returns the set of grabbed BMVerts. '''
        return set()

    def _find_corner_occupant(self, corner_co_world, incoming_bmv, radius):
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

    def _kick_corner_occupant(self, occupant, corner_co, incoming_bmv, context=None, stroke_disp_2d=None):
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

        # Release check for snapped verts
        if is_snapped and free_co is not None:
            free_world = local_to_world(free_co, M)
            if closest_target := accel.closest_point(free_world):
                if (free_world - Vector(closest_target)).length > release_radius:
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
            corner_radius = release_radius
        else:
            corner_radius = snap_in_radius * self.SNAP_CORNER_PROXIMITY  # wider snap-in only

        snapped_to_corner = False
        snapped_co_corner = None
        if corner := accel.find_corner(new_co_world):
            co_corner, corner_idx, dist_corner = corner
            if dist_corner <= corner_radius:
                grabbed_set = self._snap_grabbed_set()
                occupant = self._find_corner_occupant(co_corner, bmv, corner_radius)
                allow_snap = True
                if occupant is not None:
                    if occupant in grabbed_set:
                        # Both verts are grabbed: prevent collapse
                        allow_snap = False
                    else:
                        # Occupant is not being dragged: kick it out
                        self._kick_corner_occupant(occupant, co_corner, bmv, context, stroke_disp_2d)
                if allow_snap:
                    to_corner = Vector(co_corner) - new_co_world
                    # Direction check for all corner snapping
                    if to_corner.length < 1e-8 or disp_world.dot(to_corner) > 0:
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
            if closest_p := accel.closest_point(bmv_world):
                # Slide along the edge only for the screen-space parallel brush movement
                tangent_result = accel.closest_point_with_tangent(bmv_world)
                if tangent_result is not None and context is not None and disp_2d is not None:
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
                            constrained = accel.closest_point(candidate)
                            if constrained is not None:
                                self.snapped_verts.add(bmv)
                                return Mi @ Vector(constrained)
                # Fallback: don't slide
                self.snapped_verts.add(bmv)
                return Vector(bmv.co)
        else:
            # snap only fires when moving toward the edge
            if closest_p := accel.closest_point(new_co_world):
                p_vec = Vector(closest_p)
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
