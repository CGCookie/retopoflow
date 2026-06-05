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

from ..common.accel import EdgeMarkAccel, SourceAccel
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

    # Hard surface snapping (see ..common.sources). scale_avg converts local distances to
    # world so thresholds line up with the world-space source accel.
    scale_avg : float
    source_edge_accel : 'SourceAccel | None'
    source_sharp_proximity : float
    stickiness : float
    snapped_verts : set[BMVert]          # verts currently snapped to a source feature (for hysteresis)
    vert_corner_idx : dict[BMVert, int]  # snapped-to-corner verts -> source corner index (prevents two verts on one corner)
    verts_near_source_edge : 'dict[BMVert, Vector]'
    promoted_loop_verts : set[BMVert]    # loop verts elected to ride the source edge
    demoted_verts : set[BMVert]          # adjacent loop verts to be kept away from the source edge
    loop_guide_verts : 'tuple[BMVert, BMVert] | None'  # the seed edge that anchors the loop walk

    verts_filtered : list[BMVert]
    verts : list[tuple]            # (bmv, original co, projected xy, brush strength) captured at grab time

    mouse : Vector
    mouse_prev : Vector
    _time : float

    # Snapping tuning — intentionally different from Relax, which snaps against tiny
    # per-substep forces; here we snap against direct mouse motion.
    SNAP_CORNER_PROXIMITY : float = 2.0  # corner snap radius as a multiple of the edge snap radius
    SNAP_STICK_MULT       : float = 2.0  # how far stickiness=1 extends the release radius past the snap radius

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

        # Angle mask (mirrors Relax_Logic._setup — see there for design notes)
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

        # Hard surface snapping: detect the source feature edges/corners once per stroke
        # (cached in SourceAccel and shared with Relax when the options match).
        self.scale_avg = sum(self.matrix_world.to_scale()) / 3
        self.source_edge_accel = SourceAccel.build_from_tool(context, self.tweak, self.sources)
        self.source_sharp_proximity = getattr(self.tweak, 'source_edge_proximity', 0.25)
        self.stickiness = getattr(self.tweak, 'source_edge_stickiness', 0.5) if self.source_edge_accel else 0.0
        self.loops_strength = getattr(self.tweak, 'source_edge_guide_loops', 0.5) if self.source_edge_accel else 0.0
        self.snapped_verts = set()
        self.vert_corner_idx = {}
        self.verts_near_source_edge = {}
        self.promoted_loop_verts = set()
        self.demoted_verts = set()
        self.loop_guide_verts = None

        self.collect_verts(context, event)

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

    def _source_corner_of_vert(self, bmv, margin):
        ''' If bmv sits within `margin` (as a multiple of its local avg-edge-len * scale_avg)
        of a source corner, return (corner_co_world, corner_idx, distance); else None. '''
        if not self.source_edge_accel: return None
        cr = self.source_edge_accel.find_corner(to_world(bmv.co, self.matrix_world))
        if cr and cr[2] < get_bmv_avg_edge_len(bmv) * self.scale_avg * margin:
            return cr
        return None

    def _collect_verts_near_source_edge(self):
        ''' Return {bmv: local-space vector to nearest feature edge} for every GRABBED vert
        that is close enough and facing the feature.
        Limiting to grabbed verts (not all verts_filtered) ensures ungrabbed stationary
        verts don't keep the proximity dict populated when the user pulls the brush away. '''
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
            if dist <= get_bmv_avg_edge_len(bmv) * self.source_sharp_proximity:
                if dist < 1e-8 or (diff / dist).dot(bmv.normal) > 0.3:
                    result[bmv] = diff
        return result

    def _seed_guide_loop(self):
        ''' Walk outward from the retopo edge nearest the brush centre that already lies on
        the source feature to elect promoted/demoted verts — matching Relax's seed_guide_loop
        logic exactly.  Called once when the first verts snap to the feature. '''
        # Need at least one retopo edge where both endpoints are on the feature.
        guide_edges = [
            bme for bmv in self.verts_near_source_edge
            for bme in bmv.link_edges
            if bme.other_vert(bmv) in self.verts_near_source_edge
        ]
        if not guide_edges: return

        # Pick the seed edge whose midpoint is closest to the brush center.
        brush_co = to_world(self.verts[0][0].co, self.matrix_world) if self.verts else Vector((0, 0, 0))
        guide_edge = min(
            guide_edges,
            key=lambda e: ((e.verts[0].co + e.verts[1].co) * 0.5 - (self.matrix_world_inv @ Vector((*brush_co, 1.0))).xyz).length,
        )
        v0, v1 = guide_edge.verts[0], guide_edge.verts[1]

        def is_on_source_corner(v):
            return self._source_corner_of_vert(v, margin=0.05) is not None

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
        Called once per mouse-move event (positions have changed). '''
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
        # Detection: all grabbed promoted verts have left the proximity zone.
        # verts_near_source_edge is now grabbed-only, so this is a reliable signal that
        # the grabbed verts have actually moved away from the feature.
        if self.promoted_loop_verts:
            grabbed_promoted = self.promoted_loop_verts & grabbed
            if grabbed_promoted and not any(v in self.verts_near_source_edge for v in grabbed_promoted):
                self.promoted_loop_verts.clear()
                self.demoted_verts.clear()
                self.loop_guide_verts = None

        if self.verts_near_source_edge and not self.promoted_loop_verts:
            self._seed_guide_loop()

        # Per-corner demotion: the closest snapped vert owns each corner; face-diagonal
        # neighbours of the owner are demoted (mirrors Relax's update_source_context).
        if self.source_edge_accel and self.promoted_loop_verts and self.verts_near_source_edge:
            corner_owner: dict[int, tuple[float, BMVert]] = {}
            for cv in self.verts_near_source_edge:
                corner = self._source_corner_of_vert(cv, self.source_sharp_proximity * self.SNAP_CORNER_PROXIMITY)
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

        debug_loops_sel = getattr(self.tweak, 'source_edge_debug_loops', 'NONE')
        if debug_loops_sel != 'NONE':
            highlight = self.promoted_loop_verts if debug_loops_sel == 'PROMOTED' else self.demoted_verts
            for v in self.bm.verts:
                v.select_set(v in highlight)

    def _neighbor_on_corner(self, bmv, corner_idx):
        ''' True if a directly-connected neighbor is already snapped to the same source
        corner, so two verts don't collapse onto one corner. '''
        return any(
            self.vert_corner_idx.get(bme.other_vert(bmv)) == corner_idx
            for bme in bmv.link_edges
        )

    def snap_to_source_feature(self, bmv, new_co, falloff):
        ''' Snap a dragged vert onto the nearest source feature edge/corner.

        Promoted verts (the elected guide loop) use a wider snap radius and always snap
        when within range.  Demoted verts (adjacent competing loops) are actively pushed
        away from the feature when they stray too close.  Unclassified verts snap only when
        moving toward the feature (direction check), then stick via hysteresis. '''
        accel = self.source_edge_accel
        if not accel or not bmv.link_edges:
            return new_co

        snap_radius = get_bmv_avg_edge_len(bmv) * self.scale_avg * self.source_sharp_proximity * max(falloff, 0.0)
        if snap_radius <= 0.0:
            self.snapped_verts.discard(bmv)
            self.vert_corner_idx.pop(bmv, None)
            return new_co

        M, Mi = self.matrix_world, self.matrix_world_inv
        new_co_world = to_world(new_co, M)

        is_promoted = bool(self.promoted_loop_verts) and bmv in self.promoted_loop_verts
        is_demoted  = bool(self.demoted_verts)       and bmv in self.demoted_verts
        is_snapped  = bmv in self.snapped_verts

        # --- Demoted verts: push away when they stray into the snap zone ---
        if is_demoted:
            self.snapped_verts.discard(bmv)
            self.vert_corner_idx.pop(bmv, None)
            push_radius = snap_radius * 0.5 * self.loops_strength
            if closest_p := accel.closest_point(new_co_world):
                to_edge = Vector(closest_p) - new_co_world
                if to_edge.length < push_radius:
                    # Reflect away from the edge by the same distance it has intruded.
                    return Mi @ (new_co_world - to_edge)
            return new_co

        # --- Promoted + unclassified: snap toward the feature ---

        # Promoted verts use a wider base radius (easier to attract to the feature), but
        # once snapped the same stickiness multiplier governs release as for regular verts.
        # This means stickiness=0 lets you drag a promoted vert off just as easily as any
        # other vert, while higher stickiness values make it progressively harder to escape.
        promoted_base = snap_radius * 1.5
        if is_promoted:
            snap_in_radius   = promoted_base
            release_radius   = promoted_base * (1.0 + self.stickiness * self.SNAP_STICK_MULT)
        else:
            snap_in_radius   = snap_radius
            release_radius   = snap_radius * (1.0 + self.stickiness * self.SNAP_STICK_MULT)

        effective_radius = release_radius if is_snapped else snap_in_radius

        # Compute drag displacement once; used in both corner and edge direction checks.
        disp_world = M.to_3x3() @ (new_co - bmv.co)

        # Corners take priority over edges.
        was_on_corner = bmv in self.vert_corner_idx
        if is_snapped:
            corner_radius = effective_radius
        else:
            corner_radius = snap_in_radius * self.SNAP_CORNER_PROXIMITY  # wider snap-in only

        snapped_to_corner = False
        snapped_co_corner = None
        if corner := accel.find_corner(new_co_world):
            co_corner, corner_idx, dist_corner = corner
            if dist_corner <= corner_radius and not self._neighbor_on_corner(bmv, corner_idx):
                to_corner = Vector(co_corner) - new_co_world
                # Direction check for ALL corner snapping — both snap-in and re-snap.
                # This fixes two problems:
                # (a) A corner-snapped vert can escape: bmv.co == corner, so
                #     disp_world always opposes to_corner (their dot product is
                #     always ≤ 0), meaning the check only passes when the drag
                #     target is essentially at the corner (to_corner.length < 1e-8).
                # (b) A released vert passing near a different corner at speed
                #     won't snap to it unless actually moving toward it.
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
            is_snapped = False

        # Edge snapping.
        if closest_p := accel.closest_point(new_co_world):
            p_vec = Vector(closest_p)
            to_edge = p_vec - new_co_world
            if to_edge.length <= effective_radius:
                if is_snapped:
                    # Already snapped: stay until dragged past release radius.
                    self.snapped_verts.add(bmv)
                    return Mi @ p_vec
                # The to_edge.length < 1e-8 shortcut is intentionally skipped for
                # was_on_corner verts: corners sit on feature edges, so to_edge ≈ 0
                # even when dragging away.  Without this, the edge check re-snaps the
                # vert to the corner position immediately after the corner check releases.
                if (not was_on_corner and to_edge.length < 1e-8) or disp_world.dot(to_edge) > 0:
                    self.snapped_verts.add(bmv)
                    return Mi @ p_vec

        # Out of range -> release.
        self.snapped_verts.discard(bmv)
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
        # Vert positions have just changed, so this must run before the per-vert snap pass.
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
                # snap to the source mesh's feature edges/corners (high-poly hard surfaces)
                if self.source_edge_accel:
                    new_co = self.snap_to_source_feature(bmv, new_co, strength)

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
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()
        self.mouse_prev = mouse
