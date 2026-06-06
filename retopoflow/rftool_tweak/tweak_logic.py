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

import blf
import bmesh
import bpy
import gpu
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from bmesh.utils import edge_split
from bpy.types import Context, Event, Region, RegionView3D, Mesh, PropertyGroup
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_origin_3d, region_2d_to_vector_3d
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_line_2d
from mathutils.bvhtree import BVHTree

import math
import time
from typing import Callable
from collections.abc import Sequence

from ..common.accel import EdgeMarkAccel, SourceAccel, Accel
from ..common.drawing import Drawing, CC_2D_POINTS
from ...addon_common.common.colors import Color4
from ..common.bmesh import get_bmesh_emesh, NearestBMVert, is_bmvert_boundary, is_bmvert_corner, bmv_co_isnan, get_bmv_avg_edge_len, get_bmv_next_loop_vert
from ..common.bmesh_maths import (
    is_bmvert_on_edgemark, is_bmedge_edgemark, BMMarking,
    is_bmvert_pinned, is_bmvert_creased,
)
from ..common.maths import point_to_bvec3, point_to_bvec4, direction_to_bvec3
from ..common.raycast import (
    raycast_valid_sources, raycast_point_valid_sources, nearest_point_valid_sources,
    mouse_from_event, iter_all_valid_sources,
)
from ..common.sources import to_world

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import closest_point_segment, Point, sign, sign_threshold
from ..rftool_relax.relax_logic import Relax_Logic

class Tweak_Logic:
    bm : BMesh
    em : Mesh
    matrix_world : Matrix
    matrix_world_inv : Matrix
    mirror : set[str]
    mirror_clip : bool
    mirror_threshold : Vector

    rf_options : PropertyGroup

    check_nans : bool = True

    sources : 'list[tuple[object, Matrix, Matrix, Matrix]]'

    boundary_verts : set[BMVert]
    boundary_accel : EdgeMarkAccel
    crease_verts : set[BMVert]
    crease_accel : EdgeMarkAccel
    sharp_verts : set[BMVert]
    sharp_accel : EdgeMarkAccel
    seam_verts : set[BMVert]
    seam_accel : EdgeMarkAccel
    angle_verts : set[BMVert]
    angle_edges : set[BMEdge]
    angle_accel : EdgeMarkAccel

    is_bmvert_hidden : Callable[[BMVert], bool]
    visibility_cache : dict[BMVert, bool]

    # Hard surface snapping options
    scale_avg : float # converts local distances to world so thresholds line up with the world-space source accel
    source_edge_accel : 'SourceAccel | None'
    source_sharp_proximity : float
    stroke_snap_radius : float  # fixed world-space snap radius for the whole stroke
    stickiness : float
    snapped_verts : set[BMVert]  # verts currently snapped to a source feature
    snap_target_world : 'dict[BMVert, Vector]'  # accumulated unconstrained world position for drift-based release
    vert_corner_idx : dict[BMVert, int]  # snapped-to-corner verts -> source corner index, prevents two verts on one corner
    verts_near_source_edge : 'dict[BMVert, Vector]'
    promoted_loop_verts : set[BMVert]  # loop verts elected to ride the source edge
    demoted_verts : set[BMVert]  # adjacent loop verts to be kept away from the source edge
    loop_guide_verts : 'tuple[BMVert, BMVert] | None'  # the seed edge that anchors the loop walk
    # Snapping different from Relax which snaps against tiny per-substep forces. Here we snap against direct mouse motion.
    SNAP_CORNER_PROXIMITY : float = 2.0  # corner snap radius as a multiple of the edge snap radius
    SNAP_STICK_MULT       : float = 2.0  # how far stickiness=1 extends the release radius past the snap radius

    verts_filtered : list[BMVert]
    verts : list[tuple]  # (bmv, original co, projected xy, brush strength) captured at grab time

    mouse : Vector
    mouse_prev : Vector
    _time : float


    def __init__(self, context, event, brush, tweak):
        self.brush = brush
        self.tweak = tweak

        self.rf_options = context.scene.retopoflow

        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        self._time = time.time()

        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe()

        self.mirror = set()
        self.mirror_clip = False
        self.mirror_threshold = Vector((0, 0, 0))
        for mod in context.edit_object.modifiers:
            if mod.type != 'MIRROR': continue
            if not mod.use_clip: continue
            if mod.use_axis[0]: self.mirror.add('x')
            if mod.use_axis[1]: self.mirror.add('y')
            if mod.use_axis[2]: self.mirror.add('z')
            mt, scale = mod.merge_threshold, context.edit_object.scale
            self.mirror_threshold = Vector(( mt / scale.x, mt / scale.y, mt / scale.z ))
            self.mirror_clip = mod.use_clip

        boundary, crease, sharp, seam = EdgeMarkAccel.build_all(
            self.bm, self.mirror, self.mirror_threshold, self.mirror_clip,
            slide_boundary = self.mask_opt('boundary') == 'SLIDE',
            slide_creases  = self.mask_opt('creases')  == 'SLIDE',
            slide_sharps   = self.mask_opt('sharps')   == 'SLIDE',
            slide_seams    = self.mask_opt('seams')    == 'SLIDE',
        )
        self.boundary_verts, self.boundary_accel = boundary
        self.crease_verts,   self.crease_accel   = crease
        self.sharp_verts,    self.sharp_accel    = sharp
        self.seam_verts,     self.seam_accel     = seam

        # Angle mask, mirrors Relax logic setup
        self.angle_verts : set[BMVert] = set()
        self.angle_edges : set[BMEdge] = set()
        self.angle_accel = EdgeMarkAccel([])
        if self.mask_opt('angle') in ('SLIDE', 'EXCLUDE'):
            angle_threshold = getattr(self.rf_options, 'mask_angle_threshold', math.radians(45))
            angle_bmedges = [
                bme for bme in self.bm.edges
                if len(bme.link_faces) == 2
                and bme.calc_face_angle(0.0) > angle_threshold
            ]
            _angle_accel = EdgeMarkAccel.from_bmedges(angle_bmedges)
            self.angle_verts = _angle_accel.verts
            self.angle_edges = set(angle_bmedges)
            self.angle_accel = _angle_accel

        self.sources = []
        for obj in iter_all_valid_sources(context):
            M_obj = obj.matrix_world
            Mi_obj = M_obj.inverted_safe()
            self.sources.append((obj, M_obj, Mi_obj, Mi_obj.to_3x3()))

        # For hard surface snapping, detect the source features once per stroke, cached in SourceAccel
        self.scale_avg = sum(self.matrix_world.to_scale()) / 3
        snapping = context.scene.retopoflow.snapping
        self.source_edge_accel = SourceAccel.build_from_tool(context, snapping, self.sources)
        self.source_sharp_proximity = getattr(snapping, 'source_edge_proximity', 0.25)
        self.stickiness = getattr(snapping, 'source_edge_stickiness', 0.5) if self.source_edge_accel else 0.0
        self.loops_strength = getattr(snapping, 'source_edge_guide_loops', 0.5) if self.source_edge_accel else 0.0
        self.snapped_verts = set()
        self.snap_target_world = {}
        self.vert_corner_idx = {}
        self.verts_near_source_edge = {}
        self.promoted_loop_verts = set()
        self.demoted_verts = set()
        self.loop_guide_verts = None
        self.stroke_snap_radius = 0.0  # computed after collect_verts below

        # Spatial accel over all non-hidden retopo verts for O(1) corner-occupant lookup.
        # Only built when feature snapping is active
        all_verts = [v for v in self.bm.verts if not v.hide] if self.source_edge_accel else []
        self.vert_accel : 'Accel | None' = Accel(context, all_verts, self.matrix_world) if all_verts else None

        self.collect_verts(context, event)

        # World-space snap radius from grabbed verts' avg edge lengths at stroke start.
        # Per-vert values each frame would let a vert that accidentally projects far grow a huge snap radius mid-stroke.
        # Always compute avg_lens so the relax step threshold has a consistent distance unit.
        if self.verts:
            avg_lens = [get_bmv_avg_edge_len(bmv) for (bmv, *_) in self.verts if bmv.link_edges]
            stroke_avg = (sum(avg_lens) / len(avg_lens)) if avg_lens else 1.0
            if self.source_edge_accel:
                self.stroke_snap_radius = stroke_avg * self.scale_avg * self.source_sharp_proximity
            # Convert avg world-space edge length to screen pixels for the step threshold.
            hit_scale = self.brush.hit_scale or 1e-6
            self.relax_step_px = (stroke_avg * self.scale_avg) / hit_scale
        else:
            self.relax_step_px = max(self.brush.radius * 0.1, 1.0)
        self.relax_accum_px = 0.0

    def mask_opt(self, name : str) -> str:
        return str(getattr(self.rf_options, f'mask_{name}'))  # pyright: ignore[reportAny]
    def include_opt(self, name : str) -> bool:
        return bool(getattr(self.rf_options, f'include_{name}'))  # pyright: ignore[reportAny]
    def exclude_opt(self, name : str) -> bool:
        return not bool(getattr(self.rf_options, f'include_{name}'))  # pyright: ignore[reportAny]

    def collect_verts(self, context, event):
        self.verts = []
        self.mouse = Vector(mouse_from_event(event))
        self.mouse_prev = self.mouse.copy()

        hit = raycast_valid_sources(context, self.mouse)
        if not hit: return

        M = self.matrix_world
        brush_center_world = Vector(hit['co_world'])

        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        # right now, falloff brush works in 3D... should switch to 2D?
        radius2D, radius3D = self.brush.radius, self.brush.get_scaled_radius()

        self.bm.verts.ensure_lookup_table() # Ensure here so the per-vert filters don't need to call it

        self.verts_filtered = [
            bmv for bmv in self.bm.verts
            if not bmv.hide and ((M @ bmv.co) - brush_center_world).length <= radius3D
        ]

        if Tweak_Logic.check_nans:
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not bmv_co_isnan(bmv) ]
            Tweak_Logic.check_nans = False

        # Tier 1: O(1) direct attribute reads
        if self.mask_opt('selected') == 'ONLY':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if bmv.select ]
        elif self.mask_opt('selected') == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not bmv.select ]
        # Tier 2: O(1) len() checks
        if self.exclude_opt('corners'):
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_corner(bmv) ]
        if self.mask_opt('boundary') == 'SLIDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_corner(bmv) ]
        # Tier 3: attribute check + possible hidden-edge scan
        if self.mask_opt('boundary') == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip) ]
        if self.mask_opt('symmetry') == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_symmetry_plane(bmv) ]
        # Tier 4: layer dict-lookup + vert data access
        if self.exclude_opt('pinned'): self.verts_filtered = [
            bmv for bmv in self.verts_filtered if not is_bmvert_pinned(self.bm, bmv, ensure_lookup_table=False)
        ]
        if self.mask_opt('creases') == 'EXCLUDE':
            # Needs to check both vert and edge creases and account for pins.
            if self.bm.verts.layers.float.get('crease_vert'):
                self.verts_filtered = [ bmv for bmv in self.verts_filtered if (
                    not is_bmvert_creased(self.bm, bmv, ensure_lookup_table=False) or is_bmvert_pinned(self.bm, bmv, ensure_lookup_table=False)
                )]
            if self.bm.edges.layers.float.get('crease_edge'):
                self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.crease) ]
        # Tier 5: iterate link_edges with any()/all()
        if self.mask_opt('seams') == 'EXCLUDE':
            if any(bme.seam for bme in self.bm.edges):
                self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.seam) ]
        if self.mask_opt('sharps') == 'EXCLUDE':
            if any(not bme.smooth for bme in self.bm.edges):
                self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.sharp) ]
        if self.mask_opt('angle') == 'EXCLUDE' and self.angle_verts:
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if bmv not in self.angle_verts ]
        # Tier 6: iterate link_edges calling a function per edge
        # seam_verts/sharp_verts/crease_verts are pre-built by build_all so the truthiness check is free.
        if self.mask_opt('seams') == 'SLIDE' and self.seam_verts:
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.seam) for bme in bmv.link_edges) > 2
            ]
        if self.mask_opt('sharps') == 'SLIDE' and self.sharp_verts:
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.sharp) for bme in bmv.link_edges) > 2
            ]
        if self.mask_opt('creases') == 'SLIDE' and self.crease_verts:
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.crease) for bme in bmv.link_edges) > 2
            ]
        if self.mask_opt('angle') == 'SLIDE' and self.angle_verts:
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not sum(bme in self.angle_edges for bme in bmv.link_edges) > 2
            ]

        self.visibility_cache = {}
        self.is_bmvert_hidden = lambda _bmv: False  # nop where every bmvert is visible
        if self.exclude_opt('occluded'):
            # ASSUMING WE HAVE A REGION AND REGIONVIEW3D!
            rgn : Region = context.region
            r3d : RegionView3D = context.region_data
            matrix_world = self.matrix_world
            retopology_offset : float = context.space_data.overlay.retopology_offset

            is_bmvert_hidden_list : list[Callable[[Vector, Vector, float], bool]] = []
            for obj in iter_all_valid_sources(context):
                Mi = obj.matrix_world.inverted_safe()
                def hidden_tester(ray_e_world:Vector, ray_d_world:Vector, max_distance:float, obj=obj, Mi=Mi) -> bool:
                    ray_e_local = point_to_bvec3(Mi @ ray_e_world)
                    ray_d_local = direction_to_bvec3(Mi @ ray_d_world)
                    return obj.ray_cast(ray_e_local, ray_d_local, distance=max_distance)[0]
                is_bmvert_hidden_list.append(hidden_tester)

            def ray_from_point_fast(rgn:Region, r3d:RegionView3D, point_world:Sequence[float]|Vector) -> tuple[Vector|None, Vector|None]:
                point_screen : Sequence[float]|None = location_3d_to_region_2d(rgn, r3d, point_world)  # pyright: ignore [reportAssignmentType]
                if not point_screen: return (None, None)
                return (
                    Vector((*region_2d_to_origin_3d(rgn, r3d, point_screen), 1.0)),
                    Vector((*region_2d_to_vector_3d(rgn, r3d, point_screen).normalized(), 0.0)),
                )

            def is_point_hidden_fast(point_world:Vector, *, factor:float=0.99) -> bool:
                ray_to_e_world, ray_to_d_world = ray_from_point_fast(rgn, r3d, point_world)
                if not ray_to_e_world or not ray_to_d_world: return True
                ray_from_d_world = -ray_to_d_world
                ray_from_e_world = point_world.xyz + ray_from_d_world.xyz * retopology_offset
                max_distance = (ray_to_e_world.xyz - point_world.xyz).length * factor
                return any(
                    fn(ray_from_e_world, ray_from_d_world, max_distance)
                    for fn in is_bmvert_hidden_list
                )

            def is_bmvert_hidden(bmv : BMVert) -> bool:
                if bmv not in self.visibility_cache:
                    self.visibility_cache[bmv] = is_point_hidden_fast(matrix_world @ bmv.co)
                return self.visibility_cache[bmv]

            self.is_bmvert_hidden = is_bmvert_hidden

            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not self.is_bmvert_hidden(bmv)
            ]

        self.verts = [
            (
                bmv,
                Vector(bmv.co), # original location
                self.project_bmv(context, bmv), # screen position
                self.brush.get_strength_Point(M @ bmv.co), # grab strength
            )
            for bmv in self.verts_filtered
        ]

        # Capture brush geometry at grab time for post_relax distance weighting.
        self.grab_brush_centre_world: Vector | None = Vector(self.brush.hit_p) if self.brush.hit_p else None
        self.grab_brush_radius: float = self.brush.get_scaled_radius()


    def cancel(self, context):
        if not self.verts: return
        for (bmv, co, _, _) in self.verts:
            bmv.co = co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def project_pt(self, context, pt):
        p = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt)
        return p.xy if p else None

    def project_bmv(self, context, bmv):
        p = self.project_pt(context, bmv.co)
        return p.xy if p else None


    # -------------------------------------------------------------------------
    # Hard surface snapping helpers
    # -------------------------------------------------------------------------

    def _source_corner_of_vert(self, bmv, world_threshold):
        ''' If bmv sits within `world_threshold` (world-space units) of a source corner,
        return (corner_co_world, corner_idx, distance); else None. '''
        if not self.source_edge_accel: return None
        cr = self.source_edge_accel.find_corner(to_world(bmv.co, self.matrix_world))
        if cr and cr[2] < world_threshold:
            return cr
        return None

    def _collect_verts_near_source_edge(self):
        ''' Return {bmv: local-space vector to nearest feature edge} for every grabbed vert
        that is close enough and facing the feature. Limiting to grabbed verts ensures ungrabbed
        verts don't keep the proximity dict populated when the brush pulls away. '''
        result = {}
        if not self.source_edge_accel:
            return result
        Mi = self.matrix_world_inv
        for bmv, *_ in self.verts:
            if not bmv.link_edges: continue
            bmv_world = to_world(bmv.co, self.matrix_world)
            closest_v = self.source_edge_accel.closest_point(bmv_world)
            if not closest_v: continue
            diff = Mi @ Vector(closest_v) - bmv.co
            dist = diff.length
            if dist * self.scale_avg <= self.stroke_snap_radius:
                if dist < 1e-8 or (diff / dist).dot(bmv.normal) > 0.3:
                    result[bmv] = diff
        return result

    def _seed_guide_loop(self):
        ''' Walk outward from the retopo edge nearest the brush centre that already lies on
        the source feature to elect promoted/demoted verts, matching Relax's seed_guide_loop
        logic exactly. Called once when the first verts snap to the feature. '''
        guide_edges = [
            bme for bmv in self.verts_near_source_edge
            for bme in bmv.link_edges
            if bme.other_vert(bmv) in self.verts_near_source_edge
        ]
        # Need at least one retopo edge where both endpoints are on the feature.
        if not guide_edges: return

        # Pick the seed edge whose midpoint is closest to the brush center.
        brush_co = to_world(self.verts[0][0].co, self.matrix_world) if self.verts else Vector((0, 0, 0))
        guide_edge = min(
            guide_edges,
            key=lambda e: ((e.verts[0].co + e.verts[1].co) * 0.5 - (self.matrix_world_inv @ Vector((*brush_co, 1.0))).xyz).length,
        )
        v0, v1 = guide_edge.verts[0], guide_edge.verts[1]

        def is_on_source_corner(v):
            return self._source_corner_of_vert(v, self.stroke_snap_radius * 0.05) is not None

        def is_loop_continuation(v):
            if is_on_source_corner(v):
                return False
            if any(e.is_boundary for e in v.link_edges):
                return len(v.link_edges) == 3
            return len(v.link_edges) == 4 and len(v.link_faces) == 4

        promoted = set()
        def walk_from(cur, prev):
            while cur not in promoted and len(promoted) < 100:
                promoted.add(cur)
                if not is_loop_continuation(cur): break
                nxt = get_bmv_next_loop_vert(prev, cur)
                if nxt is None: break
                prev, cur = cur, nxt

        walk_from(v0, v1)
        walk_from(v1, v0)
        if not promoted: return

        terminal_at_corner = {
            v for v in promoted
            if not is_loop_continuation(v) and (
                not any(e.is_boundary for e in v.link_edges)
                or is_on_source_corner(v)
            )
        }

        demoted = set()
        for v in promoted:
            if v in terminal_at_corner:
                all_adj = {bme.other_vert(v) for bme in v.link_edges}
                for bmf in v.link_faces:
                    if len(bmf.verts) != 4: continue
                    for fv in bmf.verts:
                        if fv is v or fv in all_adj: continue
                        if not is_bmvert_corner(fv):
                            demoted.add(fv)
            else:
                for bme in v.link_edges:
                    nb = bme.other_vert(v)
                    if nb not in promoted and is_loop_continuation(nb):
                        demoted.add(nb)

        self.promoted_loop_verts = promoted
        self.demoted_verts = demoted
        self.loop_guide_verts = (v0, v1)

    def _update_source_context(self):
        ''' Recompute which grabbed verts lie near the feature and refresh promoted/demoted.
        Called once per mouse-move event since positions have changed. '''
        self.verts_near_source_edge = self._collect_verts_near_source_edge()

        if self.loops_strength == 0:
            self.promoted_loop_verts.clear()
            self.demoted_verts.clear()
            self.loop_guide_verts = None
            return

        grabbed = {t[0] for t in self.verts}

        # If the seed edge is no longer in the grabbed set, reset so it can be re-elected.
        if self.loop_guide_verts is not None:
            gv0, gv1 = self.loop_guide_verts
            if gv0 not in grabbed or gv1 not in grabbed:
                self.promoted_loop_verts.clear()
                self.demoted_verts.clear()
                self.loop_guide_verts = None

        # If the brush is pulling away from the feature, clear the guide loop.
        if self.promoted_loop_verts:
            grabbed_promoted = self.promoted_loop_verts & grabbed
            if grabbed_promoted and not any(v in self.verts_near_source_edge for v in grabbed_promoted):
                self.promoted_loop_verts.clear()
                self.demoted_verts.clear()
                self.loop_guide_verts = None

        if self.verts_near_source_edge and not self.promoted_loop_verts:
            self._seed_guide_loop()

        # The closest snapped vert owns each corner and face-diagonal neighbours of the owner are demoted.
        if self.source_edge_accel and self.promoted_loop_verts and self.verts_near_source_edge:
            corner_owner: dict[int, tuple[float, BMVert]] = {}
            for cv in self.verts_near_source_edge:
                corner = self._source_corner_of_vert(cv, self.stroke_snap_radius * self.SNAP_CORNER_PROXIMITY)
                if not corner: continue
                _, corner_idx, dist_corner = corner
                if corner_idx not in corner_owner or dist_corner < corner_owner[corner_idx][0]:
                    corner_owner[corner_idx] = (dist_corner, cv)
            for _dist, cv in corner_owner.values():
                all_adj = {bme.other_vert(cv) for bme in cv.link_edges}
                for bmf in cv.link_faces:
                    if len(bmf.verts) != 4: continue
                    for fv in bmf.verts:
                        if fv is cv or fv in all_adj: continue
                        if fv not in self.promoted_loop_verts and not is_bmvert_corner(fv):
                            self.demoted_verts.add(fv)

    def _find_corner_occupant(self, corner_co_world, incoming_bmv, radius):
        ''' Find a vert other than incoming_bmv sitting in a source corner.
        Check snapped_verts first, fallback to accel so the full bmesh is never iterated linearly. '''
        corner_w = Vector(corner_co_world)

        # Fast path: verts snapped this stroke are the most likely occupants.
        for v in self.snapped_verts:
            if v is incoming_bmv: continue
            if (to_world(v.co, self.matrix_world) - corner_w).length <= radius:
                return v

        # Fallback: Accel covers verts snapped in previous strokes.
        # Use a tight radius - the occupant must actually be sitting at the corner.
        if self.vert_accel:
            tight_radius = radius * 0.5
            candidates = self.vert_accel.get(corner_w, tight_radius)
            best_v, best_dist = None, float('inf')
            for v in candidates:
                if v is incoming_bmv: continue
                d = (to_world(v.co, self.matrix_world) - corner_w).length
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
        kick_dir_world: Vector | None = None

        incoming_world = to_world(incoming_bmv.co, M)
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
                hit = raycast_valid_sources(context, sample_2d)
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

    def _push_crowded_edge_neighbors(self, context, stroke_disp_2d):
        ''' After grabbed verts have moved, check every snapped vert's direct neighbors.
        If a neighbor is also on the source edge and too close, push it off the edge perpendicularly '''
        if not self.source_edge_accel: return
        accel = self.source_edge_accel
        M, Mi = self.matrix_world, self.matrix_world_inv
        grabbed = {t[0] for t in self.verts}

        for bmv in list(self.snapped_verts):
            if not bmv.is_valid: continue
            bmv_world = to_world(bmv.co, M)
            snap_r = self.stroke_snap_radius
            crowd_threshold = snap_r * 0.5
            push_dist = snap_r * 1.5  # world-space distance to push off the edge

            for bme in bmv.link_edges:
                nb = bme.other_vert(bmv)
                if nb in grabbed: continue
                nb_world = to_world(nb.co, M)

                # Is neighbor sitting on the source edge?
                closest_point = accel.closest_point(nb_world)
                if not closest_point or (Vector(closest_point) - nb_world).length > snap_r: continue

                sep = (nb_world - bmv_world).length
                if sep >= crowd_threshold: continue

                nb_2d = location_3d_to_region_2d(context.region, context.region_data, nb_world)
                if nb_2d is None: continue

                # Get the screen-space edge tangent at nb's position
                tangent_result = accel.closest_point_with_tangent(nb_world)
                if tangent_result is None: continue
                _, tangent = tangent_result
                t1_2d = location_3d_to_region_2d(context.region, context.region_data, nb_world + tangent)
                if t1_2d is None: continue
                edge_2d = t1_2d - nb_2d
                if edge_2d.length < 1e-8: continue

                # Rotate 90° to get the screen-space direction perpendicular to the edge
                edge_2d_norm = edge_2d / edge_2d.length
                perp_2d = Vector((-edge_2d_norm.y, edge_2d_norm.x))

                # Estimate pixels per world unit at nb's screen position.
                p_ref = location_3d_to_region_2d(context.region, context.region_data,
                                                  nb_world + Vector((push_dist, 0, 0)))
                pix_per_unit = ((p_ref - nb_2d).length / push_dist) if p_ref else 50.0
                push_pixels = push_dist * pix_per_unit

                # Pick the side that aligns with the mouse movement
                perp_sign = 1
                if stroke_disp_2d is not None and stroke_disp_2d.length > 1e-8:
                    # stroke_disp_2d is the full stroke vector (start → current), which is
                    # stable across the stroke and won't flip on overshoots at the end.
                    if perp_2d.dot(stroke_disp_2d) < 0:
                        perp_sign = -1

                sample_2d = nb_2d + perp_2d * (perp_sign * push_pixels)
                hit = raycast_valid_sources(context, sample_2d)
                if hit is None: continue

                nb.co = Vector(hit['co_local'])
                self.snapped_verts.discard(nb)
                self.snap_target_world.pop(nb, None)


    def snap_to_source_feature(self, bmv, new_co, falloff, context=None, disp_2d=None, stroke_disp_2d=None):
        ''' Snap a dragged vert onto the nearest source feature edge/corner.
        Promoted verts use a wider snap radius and always snap  within range.
        Demoted verts are actively pushed away from the feature when they stray too close.
        Unclassified verts snap only when moving toward the feature, then stay stuck. '''

        accel = self.source_edge_accel
        if not accel or not bmv.link_edges:
            return new_co

        snap_radius = self.stroke_snap_radius * max(falloff, 0.0)
        if snap_radius <= 0.0:
            self.snapped_verts.discard(bmv)
            self.vert_corner_idx.pop(bmv, None)
            return new_co

        M, Mi = self.matrix_world, self.matrix_world_inv
        new_co_world = to_world(new_co, M)

        is_promoted = bool(self.promoted_loop_verts) and bmv in self.promoted_loop_verts
        is_demoted  = bool(self.demoted_verts)       and bmv in self.demoted_verts
        is_snapped  = bmv in self.snapped_verts

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

        # Promoted + unclassified: snap toward the feature
        promoted_base = snap_radius * 1.5
        if is_promoted:
            # Promoted verts use a wider radius but after snapped have the same stickiness as regular verts.
            snap_in_radius   = promoted_base
            release_radius   = promoted_base * (1.0 + self.stickiness * self.SNAP_STICK_MULT)
        else:
            snap_in_radius   = snap_radius
            release_radius   = snap_radius * (1.0 + self.stickiness * self.SNAP_STICK_MULT)

        effective_radius = release_radius if is_snapped else snap_in_radius

        # An edge snapped vert never moves far enough in a single step for the distance check to trigger release.
        # Tracking the cumulative unconstrained drift lets the vert release when the brush has moved far enough away.
        if is_snapped:
            if bmv not in self.snap_target_world:
                self.snap_target_world[bmv] = to_world(Vector(bmv.co), M)
            else:
                drift_local = Vector(new_co) - Vector(bmv.co)
                self.snap_target_world[bmv] = self.snap_target_world[bmv] + M.to_3x3() @ drift_local
            target_world = self.snap_target_world[bmv]
            if closest_target := accel.closest_point(target_world):
                if (target_world - Vector(closest_target)).length > effective_radius:
                    self.snapped_verts.discard(bmv)
                    self.vert_corner_idx.pop(bmv, None)
                    self.snap_target_world.pop(bmv, None)
                    return new_co
        else:
            self.snap_target_world.pop(bmv, None)

        disp_world = M.to_3x3() @ (new_co - bmv.co) # Drag dispalcement

        # Corners take priority over edges
        was_on_corner = bmv in self.vert_corner_idx
        if is_snapped:
            corner_radius = effective_radius
        else:
            corner_radius = snap_in_radius * self.SNAP_CORNER_PROXIMITY  # wider snap-in only

        snapped_to_corner = False
        snapped_co_corner = None
        if corner := accel.find_corner(new_co_world):
            co_corner, corner_idx, dist_corner = corner
            if dist_corner <= corner_radius:
                grabbed_set = {t[0] for t in self.verts}
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
                    # Direction check for all corner snapping, both snap-in and re-snap.
                    # disp_world always opposes to_corner, so the check only passes when the drag target is at the corner.
                    # A released vert passing near a different corner won't snap to it unless actually moving toward it.
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
        if closest_p := accel.closest_point(new_co_world):
            p_vec = Vector(closest_p)
            to_edge = p_vec - new_co_world
            if to_edge.length <= effective_radius:
                if is_snapped:
                    # Slide along the edge only for the screen-space parallel brush movement
                    bmv_world = to_world(bmv.co, M)
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
                                parallel_2d = disp_2d.dot(tangent_2d_norm) # Screen-space pixels moved parallel to the projected edge
                                # Tangent is in world space, so tangent_2d_len is pixels per world unit
                                # Flip to get world units per pixel
                                parallel_3d = parallel_2d / tangent_2d_len
                                candidate = point_to_bvec3(bmv_world + tangent * parallel_3d)
                                constrained = accel.closest_point(candidate)
                                if constrained is not None:
                                    self.snapped_verts.add(bmv)
                                    return Mi @ Vector(constrained)
                    # Fallback: don't slide
                    self.snapped_verts.add(bmv)
                    return Vector(bmv.co)
                # Corners sit on feature edges, so to_edge ≈ 0 even when dragging away.
                # Without this, the edge check re-snaps the vert to the corner immediately after the corner check releases.
                if (not was_on_corner and to_edge.length < 1e-8) or disp_world.dot(to_edge) > 0:
                    self.snapped_verts.add(bmv)
                    return Mi @ p_vec

        # Out of range: release
        self.snapped_verts.discard(bmv)
        self.snap_target_world.pop(bmv, None)
        return new_co


    def update(self, context, event):
        pressure = getattr(event, 'pressure', 1.0)

        if not self.verts: return
        if event.type != 'MOUSEMOVE': return

        mouse = Vector(mouse_from_event(event))
        delta = mouse - self.mouse_prev
        if delta.length_squared == 0: return

        M = self.matrix_world
        Mi = self.matrix_world_inv

        # Recompute which verts are near the feature and refresh the guide loop election.
        # Vert positions have just changed, so this must run before the per-vert snap.
        if self.source_edge_accel:
            self._update_source_context()

        for (bmv, co_orig, xy, strength) in self.verts:
            if self.mask_opt('boundary') == 'SLIDE' and bmv in self.boundary_verts:
                new_co = Vector(bmv.co)
                delta_strength = delta.length * strength * pressure
                opt_steps = max(math.ceil(delta_strength / 10), 1)
                for step in range(opt_steps):
                    pt2d = self.project_pt(context, new_co) or xy
                    new_co2 = raycast_valid_sources(context, pt2d + delta * (strength / opt_steps) * pressure)
                    if not new_co2: break
                    new_co = new_co2['co_local']
                    if self.boundary_accel:
                        p = self.boundary_accel.closest_point(new_co)
                        if p is not None:
                            new_co = p
            else:
                cur_xy = self.project_bmv(context, bmv) or xy
                new_co = raycast_valid_sources(context, cur_xy + delta * strength * pressure)
                if not new_co: continue
                new_co = new_co['co_local']
                if self.mask_opt('seams') == 'SLIDE' and bmv in self.seam_verts:
                    if self.seam_accel:
                        p = self.seam_accel.closest_point(new_co)
                        if p is not None: new_co = p
                if self.mask_opt('sharps') == 'SLIDE' and bmv in self.sharp_verts:
                    if self.sharp_accel:
                        p = self.sharp_accel.closest_point(new_co)
                        if p is not None: new_co = p
                if self.mask_opt('creases') == 'SLIDE' and bmv in self.crease_verts:
                    if self.crease_accel:
                        p = self.crease_accel.closest_point(new_co)
                        if p is not None: new_co = p
                if self.mask_opt('angle') == 'SLIDE' and bmv in self.angle_verts:
                    if self.angle_accel:
                        p = self.angle_accel.closest_point(new_co)
                        if p is not None: new_co = p
                if self.source_edge_accel:
                    new_co = self.snap_to_source_feature(bmv, new_co, strength, context, delta * strength * pressure, mouse - self.mouse)

            if self.mirror:
                co = Vector(new_co)
                t = self.mirror_threshold
                zero = {
                    'x': ('x' in self.mirror and (sign_threshold(co.x, t.x) != sign_threshold(co_orig.x, t.x) or sign_threshold(co_orig.x, t.x) == 0)),
                    'y': ('y' in self.mirror and (sign_threshold(co.y, t.y) != sign_threshold(co_orig.y, t.y) or sign_threshold(co_orig.y, t.y) == 0)),
                    'z': ('z' in self.mirror and (sign_threshold(co.z, t.z) != sign_threshold(co_orig.z, t.z) or sign_threshold(co_orig.z, t.z) == 0)),
                }
                # iteratively zero out the component
                for _ in range(1000):
                    d = 0
                    if zero['x']: co.x, d = co.x * 0.95, max(abs(co.x), d)
                    if zero['y']: co.y, d = co.y * 0.95, max(abs(co.y), d)
                    if zero['z']: co.z, d = co.z * 0.95, max(abs(co.z), d)
                    co_world = M @ Vector((*co, 1.0))
                    co_world_snapped = nearest_point_valid_sources(context, point_to_bvec3(co_world), world=True, sources=self.sources)
                    if not co_world_snapped: continue
                    co = Mi @ co_world_snapped
                    if d < 0.001: break  # break out if change was below threshold
                if zero['x']: co.x = 0
                if zero['y']: co.y = 0
                if zero['z']: co.z = 0
                new_co = co


            if new_co: bmv.co = new_co
        if self.source_edge_accel:
            self._push_crowded_edge_neighbors(context, mouse - self.mouse)

        # Live relax as the brush moves based on comparing stroke len to avg edge len
        relax_factor = float(getattr(self.tweak, 'post_relax_steps', 0.0))
        if relax_factor > 0.0:
            self.relax_accum_px += delta.length
            threshold_px = self.relax_step_px * 0.1 / relax_factor
            while self.relax_accum_px >= threshold_px:
                self.relax_accum_px -= threshold_px
                self._do_relax_step(context)

        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()
        self.mouse_prev = mouse

    def _do_relax_step(self, context):
        ''' Run one Relax iteration on grabbed verts + expanded neighbours.
        Centre verts are excluded and outer verts get full strength. '''
        if not self.verts:
            return
        expand = getattr(self.tweak, 'post_relax_expand', 1)

        centre = self.grab_brush_centre_world
        radius = self.grab_brush_radius if self.grab_brush_radius > 1e-6 else 1e-6
        vert_strength: dict[BMVert, float] = {}
        M = self.matrix_world
        for bmv, orig_co, _xy, _grab_strength in self.verts:
            if not bmv.is_valid or bmv.hide: continue
            if centre is not None:
                dist = (M @ orig_co - centre).length
                relax_s = min(dist / radius, 1.0)
            else:
                relax_s = 1.0
            if relax_s > 0.0:
                vert_strength[bmv] = relax_s

        frontier: set[BMVert] = set(vert_strength.keys())
        visited: set[BMVert] = set(frontier)
        for _ in range(expand):
            next_frontier: set[BMVert] = set()
            for bmv in frontier:
                for bmf in bmv.link_faces:
                    for nbv in bmf.verts:
                        if nbv not in visited and not nbv.hide and nbv.is_valid:
                            visited.add(nbv)
                            next_frontier.add(nbv)
                            if nbv not in vert_strength:
                                vert_strength[nbv] = 1.0
            frontier = next_frontier

        all_verts = set(vert_strength.keys())
        if not all_verts:
            return

        relax_opts = self.tweak
        engine = Relax_Logic.for_options(context, relax_opts)
        filtered = engine.filter_verts(all_verts)
        filtered_strength = {bmv: vert_strength[bmv] for bmv in filtered if bmv in vert_strength}
        engine.relax_verts(context, set(filtered_strength.keys()), filtered_strength)

    def draw(self, context: Context):
        Drawing.draw_snap_circles(context, self.snapped_verts, self.matrix_world)
        from ..preferences import RF_Prefs
        highlight = RF_Prefs.get_prefs(context).highlight_color
        Drawing.draw_loop_highlight(context, self.promoted_loop_verts, self.matrix_world, highlight)
        if self.demoted_verts:
            vertex_size = context.preferences.themes[0].view_3d.vertex_size
            M = self.matrix_world
            rgn, r3d = context.region, context.region_data
            red = Color4((1, 0, 0, 1))
            for bmv in self.demoted_verts:
                if not bmv.is_valid: continue
                p = location_3d_to_region_2d(rgn, r3d, M @ bmv.co)
                if not p: continue
                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.color(red)
                    draw.vertex(p)
