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

import bmesh
import bpy
from bmesh.types import BMesh, BMVert, BMEdge
from bpy.types import Context, Event, Region, RegionView3D, Mesh, PropertyGroup
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_origin_3d, region_2d_to_vector_3d, region_2d_to_location_3d
from mathutils import Vector, Matrix

import math
from typing import Callable
from collections.abc import Sequence

from ..common.accel import EdgeMarkAccel, SourceAccel, Accel, SourceCache
from ..common.drawing import Drawing, CC_2D_POINTS
from ...addon_common.common.colors import Color4
from ..common.bmesh import get_bmesh_emesh, is_bmvert_boundary, is_bmvert_corner, bmv_co_isnan, get_bmv_avg_edge_len, get_bmv_next_loop_vert
from ..common.bmesh_maths import (
    is_bmvert_on_edgemark, is_bmedge_edgemark, BMMarking,
    is_bmvert_pinned, is_bmvert_creased,
)
from ..common.maths import point_to_bvec3, direction_to_bvec3, local_to_world
from ..common.raycast import (
    raycast_valid_sources, nearest_point_valid_sources, raycast_point_capped_valid_sources,
    mouse_from_event, iter_all_valid_sources, make_hidden_tester,
)

from ...addon_common.common.maths import sign_threshold
from ..rftool_relax.relax_logic import Relax_Logic
from ..common.snapping import SourceSnapMixin, source_snap_radius, source_snap_settings

class Tweak_Logic(SourceSnapMixin):
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
    # run/guide-loop state (verts_near_source_edge, promoted/demoted, vert_feature_run, ...)
    # is declared on FeatureRunsMixin

    nudge_loop_verts : 'set[BMVert]'  # loop elected once per Nudge-Loops stroke; empty for Brush mode
    nudge_vert_tangents : 'dict[BMVert, Vector]'  # slide tangent per vert, locked once (at election or first encounter)

    verts_filtered : list[BMVert]
    verts : list[tuple]  # (bmv, original co, projected xy, brush strength) captured at grab time
    active_island : 'set[BMVert] | None'  # verts of the island under the brush, or None when not isolating

    mouse : Vector
    mouse_prev : Vector


    def __init__(self, context, event, brush, tweak):
        self.brush = brush
        self.tweak = tweak
        # Capture Ctrl at stroke start to invert Pinch/Magnify for the whole stroke (mirrors Blender sculpt behavior).
        # The Ctrl+LMB keymap entry in rf_keymaps ensures Blender's Select Shortest Path never fires first.
        self.pinch_ctrl_flip: bool = (
            bool(getattr(event, 'ctrl', False))
            and getattr(tweak, 'brush_type', 'GRAB') == 'PINCH_MAGNIFY'
        )
        # Capture Alt at stroke start to toggle Loops mode for this stroke.
        self.nudge_loops_alt_flip: bool = (
            bool(getattr(event, 'alt', False))
            and getattr(tweak, 'brush_type', 'GRAB') == 'NUDGE'
        )

        self.rf_options = context.scene.retopoflow

        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)

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
            angle_accel = EdgeMarkAccel.from_bmedges(angle_bmedges)
            self.angle_verts = angle_accel.verts
            self.angle_edges = set(angle_bmedges)
            self.angle_accel = angle_accel

        self.sources = []
        for obj in iter_all_valid_sources(context):
            M_obj = obj.matrix_world
            Mi_obj = M_obj.inverted_safe()
            self.sources.append((obj, M_obj, Mi_obj, Mi_obj.to_3x3()))

        # For hard surface snapping, detect the source features once per stroke, cached in SourceAccel
        self.scale_avg = sum(self.matrix_world.to_scale()) / 3
        snapping = context.scene.retopoflow.snapping
        self.source_edge_accel = SourceCache.get(context)
        self.source_use_fixed, self.source_fixed_distance, self.source_sharp_proximity = source_snap_settings(context)
        self.stickiness = getattr(snapping, 'source_edge_stickiness', 0.5) if self.source_edge_accel else 0.0
        self.loops_strength = getattr(snapping, 'source_edge_guide_loops', 0.5) if self.source_edge_accel else 0.0
        self.snap_init_state()
        self.verts_near_source_edge = {}
        self.promoted_loop_verts = set()
        self.demoted_verts = set()
        self.guide_loop_seeds = []
        self.vert_feature_run = {}
        self.run_segments = {}
        self.run_of_seg = {}
        self.demoted_by_runs = {}
        self.vert_seed_seg = {}
        self.stroke_snap_radius = 0.0  # computed after collect_verts below
        self.nudge_loop_verts: set[BMVert] = set()
        self.nudge_loop_elected: bool = False
        self.nudge_stroke_dir_2d: 'Vector | None' = None  # locked at election time
        self.nudge_vert_tangents: dict[BMVert, Vector] = {}  # locked at election or first encounter

        # Spatial accel over all non-hidden retopo verts for O(1) corner-occupant lookup.
        # Only built when feature snapping is active
        all_verts = [v for v in self.bm.verts if not v.hide] if self.source_edge_accel else []
        self.vert_accel : 'Accel | None' = Accel(context, all_verts, self.matrix_world) if all_verts else None

        # Cache mesh-wide edge-mark presence so per-vert checks in sweeps don't scan all edges.
        self.has_any_seam  = any(bme.seam for bme in self.bm.edges)
        self.has_any_sharp = any(not bme.smooth for bme in self.bm.edges)

        self.collect_verts(context, event)

        # World-space snap radius from grabbed verts' avg edge lengths at stroke start.
        # Per-vert values each frame would let a vert that accidentally projects far grow a huge snap radius mid-stroke.
        # Always compute avg_lens so the relax step threshold has a consistent distance unit.
        if self.verts:
            avg_lens = [get_bmv_avg_edge_len(bmv) for (bmv, *_) in self.verts if bmv.link_edges]
            stroke_avg = (sum(avg_lens) / len(avg_lens)) if avg_lens else 1.0
            if self.source_edge_accel:
                self.stroke_snap_radius = source_snap_radius(
                    stroke_avg * self.scale_avg,
                    use_fixed=self.source_use_fixed, fixed_distance=self.source_fixed_distance, avg_edge_factor=self.source_sharp_proximity,
                )
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
        self.active_island = None  # set below when isolating to one island
        self.mouse = Vector(mouse_from_event(event))
        self.mouse_prev = self.mouse.copy()

        hit = raycast_valid_sources(context, self.mouse, respect_clip_planes=True)
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

            is_bmvert_hidden_list : list[Callable[[Vector, Vector, float], bool]] = [
                make_hidden_tester(context, obj)
                for obj in iter_all_valid_sources(context)
            ]

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

        # Keep focused on one mesh island at a time to prevent spillover unless "All Islands" masking option is on.
        if self.verts_filtered and not self.include_opt('all_islands'):
            nearest = min(self.verts_filtered, key=lambda v: ((M @ v.co) - brush_center_world).length_squared)
            self.active_island = self.flood_island(nearest)
            self.verts_filtered = [bmv for bmv in self.verts_filtered if bmv in self.active_island]

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

    def flood_island(self, seed: BMVert) -> 'set[BMVert]':
        ''' All verts reachable from seed through edges, i.e. the whole connected mesh island.
        Locked once at stroke start so the sweep stays on the starting island even as the brush moves. '''
        island = {seed}
        stack = [seed]
        while stack:
            v = stack.pop()
            for bme in v.link_edges:
                nb = bme.other_vert(v)
                if nb not in island:
                    island.add(nb)
                    stack.append(nb)
        return island


    def elect_nudge_loop(self, context, delta: Vector):
        ''' Score each screen-space edge by proximity to the mouse AND parallelism with the
        stroke direction, then walk its full loop.  Calling on the first meaningful mouse
        movement ensures stroke direction is known, so the right loop is chosen even when
        the user starts on a vertex shared by multiple loops. '''
        self.nudge_loop_verts = set()
        rgn, r3d = context.region, context.region_data
        M = self.matrix_world
        mouse_2d = self.mouse
        stroke_dir_2d = delta.normalized()
        self.nudge_stroke_dir_2d = stroke_dir_2d  # lock direction for the whole stroke

        # Score: (1 - parallelism with stroke) / (screen-space distance to edge + 1).
        # High score = edge runs perpendicular to stroke AND is close to the mouse.
        # Perpendicular edges are the cross-edges whose loop runs parallel to the stroke direction.
        check_occluded = self.exclude_opt('occluded')
        scored: 'list[tuple[float, BMEdge]]' = []
        for bme in self.bm.edges:
            if bme.verts[0].hide or bme.verts[1].hide: continue
            p0 = location_3d_to_region_2d(rgn, r3d, M @ bme.verts[0].co)
            p1 = location_3d_to_region_2d(rgn, r3d, M @ bme.verts[1].co)
            if p0 is None or p1 is None: continue
            seg_vec = p1 - p0
            seg_len = seg_vec.length
            if seg_len < 1e-4: continue
            t = max(0.0, min(1.0, (mouse_2d - p0).dot(seg_vec) / (seg_len * seg_len)))
            dist = (p0 + seg_vec * t - mouse_2d).length
            parallelism = abs((seg_vec / seg_len).dot(stroke_dir_2d))
            score = (1.0 - parallelism) / (dist + 1.0)
            scored.append((score, bme))

        if not scored:
            return

        best_edge: BMEdge | None = None
        if not check_occluded:
            best_edge = max(scored, key=lambda se: se[0])[1]
        else:
            scored.sort(key=lambda se: -se[0])
            for score, bme in scored:
                if self.is_bmvert_hidden(bme.verts[0]) or self.is_bmvert_hidden(bme.verts[1]): continue
                best_edge = bme
                break

        if best_edge is None:
            return

        v0, v1 = best_edge.verts[0], best_edge.verts[1]

        # For a boundary guide loop the walk must stop at corners so it spans only the
        # segment between two corner anchors.  Interior loops continue as before.
        is_boundary_loop = best_edge.is_boundary

        # Walk both directions from the seed edge to collect the full loop.
        loop_verts: set[BMVert] = set()
        def walk_from(cur, prev):
            while cur not in loop_verts and len(loop_verts) < 500:
                loop_verts.add(cur)
                # Corner verts on a boundary loop are anchor points — include them
                # but don't walk past them.
                if is_boundary_loop and is_bmvert_corner(cur):
                    break
                nxt = get_bmv_next_loop_vert(prev, cur)
                if nxt is None: break
                prev, cur = cur, nxt

        walk_from(v0, v1)
        walk_from(v1, v0)
        self.nudge_loop_verts = loop_verts

        # Precompute a locked slide tangent for every loop vert from stable (pre-movement)
        # positions.  The tangent is the cross-edge direction (perpendicular to the loop)
        # derived from local loop geometry so curved loops work correctly.
        self.nudge_vert_tangents.clear()
        def best_tangent_3d(bmv_):
            # Build local loop tangent from this vert's loop-direction neighbors.
            loop_nbs_ = [bme_.other_vert(bmv_) for bme_ in bmv_.link_edges
                         if not bme_.other_vert(bmv_).hide
                         and bme_.other_vert(bmv_) in loop_verts]
            if len(loop_nbs_) >= 2:
                lt_ = (M @ loop_nbs_[1].co) - (M @ loop_nbs_[0].co)
            elif len(loop_nbs_) == 1:
                lt_ = (M @ loop_nbs_[0].co) - (M @ bmv_.co)
            else:
                return None
            if lt_.length < 1e-8: return None
            lt_ = lt_ / lt_.length
            # Among cross-edge (non-loop) neighbors, pick the one whose 3D direction
            # is most perpendicular to the local loop tangent.  This is correct for
            # any loop curvature; stroke_dir_2d is not used for selection here.
            best_perp_ = -1.0
            best_t3d_: 'Vector | None' = None
            for bme_ in bmv_.link_edges:
                nb_ = bme_.other_vert(bmv_)
                if nb_.hide or nb_ in loop_verts: continue
                d3d_ = (M @ nb_.co) - (M @ bmv_.co)
                if d3d_.length < 1e-8: continue
                d3d_n_ = d3d_ / d3d_.length
                perp_ = 1.0 - abs(d3d_n_.dot(lt_))
                if perp_ > best_perp_:
                    best_perp_ = perp_
                    best_t3d_ = d3d_n_  # sign is irrelevant: projection handles direction
            return best_t3d_
        for bmv_ in loop_verts:
            t3d_ = best_tangent_3d(bmv_)
            if t3d_ is not None:
                self.nudge_vert_tangents[bmv_] = t3d_

    def nudge_companion_verts(self, reach: float) -> 'set[BMVert]':
        ''' The elected loop plus every vert within `reach` of it from walking along mesh edges.
        Allows topologically close vertices to be nudged even if occluded. '''
        if not self.nudge_loop_verts:
            return set()

        M = self.matrix_world
        dist: dict[BMVert, float] = {v: 0.0 for v in self.nudge_loop_verts if v.is_valid and not v.hide}
        frontier = list(dist)
        while frontier:
            advanced = []
            for bmv in frontier:
                d_bmv = dist[bmv]
                bmv_world = M @ bmv.co
                for bme in bmv.link_edges:
                    nb = bme.other_vert(bmv)
                    if nb.hide or not nb.is_valid: continue
                    d_nb = d_bmv + ((M @ nb.co) - bmv_world).length
                    if d_nb > reach: continue
                    if nb in dist and dist[nb] <= d_nb: continue
                    dist[nb] = d_nb
                    advanced.append(nb)
            frontier = advanced

        return set(dist)


    def cancel(self, context):
        if not self.verts: return
        for (bmv, co, _, _) in self.verts:
            bmv.co = co
        bmesh.update_edit_mesh(self.em)
        # context.area.tag_redraw()

    def project_pt(self, context, pt):
        p = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt)
        return p.xy if p else None

    def project_bmv(self, context, bmv):
        p = self.project_pt(context, bmv.co)
        return p.xy if p else None

    def raycast_capped(self, context, bmv, screen_xy):
        ''' Screen space project bmv onto the source, capped at one brush radius so a vert
        whose screen point slides off the foreground silhouette doesn't teleport onto a far
        background object.  Returns a local-space co, or None. '''
        return raycast_point_capped_valid_sources(
            context, screen_xy, self.matrix_world @ bmv.co,
            cap=self.brush.get_scaled_radius(), sources=self.sources,
        )


    # -------------------------------------------------------------------------
    # Masking helpers (used by nudge / pinch sweeps)
    # -------------------------------------------------------------------------

    def is_vert_excluded(self, bmv: BMVert, *, ignore_occluded: bool = False) -> bool:
        ''' True if bmv must not be moved by a sweep (replicates EXCLUDE/ONLY/corner filters
        from collect_verts so that nudge and pinch respect the same masking as GRAB).
        ignore_occluded skips only the occlusion test, for verts that move as a unit,
        i.e. a nudged loop and its neighbors. '''
        if self.active_island is not None and bmv not in self.active_island:
            return True
        if self.mask_opt('selected') == 'ONLY' and not bmv.select:
            return True
        if self.mask_opt('selected') == 'EXCLUDE' and bmv.select:
            return True
        if self.exclude_opt('corners') and is_bmvert_corner(bmv):
            return True
        if self.mask_opt('boundary') == 'SLIDE' and is_bmvert_corner(bmv):
            return True
        if self.mask_opt('boundary') == 'EXCLUDE' and is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip):
            return True
        if self.exclude_opt('pinned') and is_bmvert_pinned(self.bm, bmv, ensure_lookup_table=False):
            return True
        if self.mask_opt('creases') == 'EXCLUDE':
            if self.bm.verts.layers.float.get('crease_vert') and is_bmvert_creased(self.bm, bmv, ensure_lookup_table=False) and not is_bmvert_pinned(self.bm, bmv, ensure_lookup_table=False):
                return True
            if self.bm.edges.layers.float.get('crease_edge') and is_bmvert_on_edgemark(self.bm, bmv, BMMarking.crease):
                return True
        if self.mask_opt('seams') == 'EXCLUDE' and self.has_any_seam and is_bmvert_on_edgemark(self.bm, bmv, BMMarking.seam):
            return True
        if self.mask_opt('sharps') == 'EXCLUDE' and self.has_any_sharp and is_bmvert_on_edgemark(self.bm, bmv, BMMarking.sharp):
            return True
        if self.mask_opt('angle') == 'EXCLUDE' and self.angle_verts and bmv in self.angle_verts:
            return True
        if not ignore_occluded and self.exclude_opt('occluded') and self.is_bmvert_hidden(bmv):
            return True
        # SLIDE intersection verts (> 2 marked edges) are also immovable (same as collect_verts Tier 6)
        if self.mask_opt('seams') == 'SLIDE' and self.seam_verts and bmv in self.seam_verts:
            if sum(is_bmedge_edgemark(self.bm, bme, BMMarking.seam) for bme in bmv.link_edges) > 2:
                return True
        if self.mask_opt('sharps') == 'SLIDE' and self.sharp_verts and bmv in self.sharp_verts:
            if sum(is_bmedge_edgemark(self.bm, bme, BMMarking.sharp) for bme in bmv.link_edges) > 2:
                return True
        if self.mask_opt('creases') == 'SLIDE' and self.crease_verts and bmv in self.crease_verts:
            if sum(is_bmedge_edgemark(self.bm, bme, BMMarking.crease) for bme in bmv.link_edges) > 2:
                return True
        if self.mask_opt('angle') == 'SLIDE' and self.angle_verts and bmv in self.angle_verts:
            if sum(bme in self.angle_edges for bme in bmv.link_edges) > 2:
                return True
        return False

    def apply_slide_constraints(self, bmv: BMVert, new_co: Vector) -> Vector:
        ''' Snap new_co (local space) onto the nearest feature mark if bmv is a SLIDE vert. '''
        if self.mask_opt('boundary') == 'SLIDE' and bmv in self.boundary_verts:
            if self.boundary_accel:
                p = self.boundary_accel.closest_point(new_co)
                if p is not None:
                    return p
        if self.mask_opt('seams') == 'SLIDE' and bmv in self.seam_verts:
            if self.seam_accel:
                p = self.seam_accel.closest_point(new_co)
                if p is not None:
                    return p
        if self.mask_opt('sharps') == 'SLIDE' and bmv in self.sharp_verts:
            if self.sharp_accel:
                p = self.sharp_accel.closest_point(new_co)
                if p is not None:
                    return p
        if self.mask_opt('creases') == 'SLIDE' and bmv in self.crease_verts:
            if self.crease_accel:
                p = self.crease_accel.closest_point(new_co)
                if p is not None:
                    return p
        if self.mask_opt('angle') == 'SLIDE' and bmv in self.angle_verts:
            if self.angle_accel:
                p = self.angle_accel.closest_point(new_co)
                if p is not None:
                    return p
        return new_co

    def apply_mirror_clip(self, context, bmv: BMVert, new_co: Vector) -> Vector:
        ''' Apply mirror plane clamping to new_co (local space). Uses bmv.co as the
        reference side so verts that start on a mirror plane stay on it. '''
        if not self.mirror:
            return new_co
        M, Mi = self.matrix_world, self.matrix_world_inv
        co_orig = Vector(bmv.co)
        co = Vector(new_co)
        t = self.mirror_threshold
        zero = {
            'x': ('x' in self.mirror and (sign_threshold(co.x, t.x) != sign_threshold(co_orig.x, t.x) or sign_threshold(co_orig.x, t.x) == 0)),
            'y': ('y' in self.mirror and (sign_threshold(co.y, t.y) != sign_threshold(co_orig.y, t.y) or sign_threshold(co_orig.y, t.y) == 0)),
            'z': ('z' in self.mirror and (sign_threshold(co.z, t.z) != sign_threshold(co_orig.z, t.z) or sign_threshold(co_orig.z, t.z) == 0)),
        }
        if not any(zero.values()):
            return new_co
        for _ in range(1000):
            d = 0
            if zero['x']: co.x, d = co.x * 0.95, max(abs(co.x), d)
            if zero['y']: co.y, d = co.y * 0.95, max(abs(co.y), d)
            if zero['z']: co.z, d = co.z * 0.95, max(abs(co.z), d)
            co_world = M @ Vector((*co, 1.0))
            co_world_snapped = nearest_point_valid_sources(context, point_to_bvec3(co_world), world=True, sources=self.sources, respect_clip_planes=True)
            if not co_world_snapped: continue
            co = Mi @ co_world_snapped
            if d < 0.001: break
        if zero['x']: co.x = 0
        if zero['y']: co.y = 0
        if zero['z']: co.z = 0
        return co


    # -------------------------------------------------------------------------
    # Hard surface snapping helpers
    # -------------------------------------------------------------------------

    def feature_run_extra_margin(self):
        return self.brush.get_scaled_radius() * 2.0

    def guide_seed_edges_by_run(self, exclude_runs):
        run_edges: 'dict[int, set]' = {}
        for bmv in self.verts_near_source_edge:
            run_id = self.vert_feature_run.get(bmv)
            if run_id is None or run_id in exclude_runs: continue
            for bme in bmv.link_edges:
                if self.vert_feature_run.get(bme.other_vert(bmv)) == run_id:
                    run_edges.setdefault(run_id, set()).add(bme)
        return run_edges

    def guide_anchor_co_local(self):
        # Anchoring to the live brush center rather than an arbitrary grabbed vert means a
        # large brush elects the loop under the cursor, not one out on the brush's rim.
        if self.brush.hit_p:
            return (self.matrix_world_inv @ Vector((*self.brush.hit_p, 1.0))).xyz
        if self.verts:
            return self.verts[0][0].co
        return Vector((0, 0, 0))

    def keep_reelected_loop(self, promoted, members):
        # Drop a loop that is pulling away from the feature so it can be re-elected fresh.
        grabbed_promoted = promoted & members
        return not grabbed_promoted or any(v in self.verts_near_source_edge for v in grabbed_promoted)

    def update_source_context(self):
        ''' Recompute which grabbed verts lie near the feature, re-label local feature runs, and
        re-derive one promoted guide loop per run (union across loops feeds the mixin and drawing).
        Called once per mouse-move event since positions have changed. '''
        self.verts_near_source_edge = self.collect_verts_near_source_edge(bmv for bmv, *_ in self.verts)
        self.refresh_feature_runs()
        self.demoted_by_runs = {}

        if self.loops_strength == 0:
            self.clear_guide_state()
            return

        grabbed = {t[0] for t in self.verts}
        self.update_source_context_brush(grabbed)
        self.apply_corner_owner_demotion()

    def snap_grabbed_set(self):
        return {t[0] for t in self.verts}

    def push_crowded_edge_neighbors(self, context, stroke_disp_2d):
        ''' After grabbed verts have moved, check every snapped vert's direct neighbors.
        If a neighbor is also on the source edge and too close, push it off the edge perpendicularly '''
        if not self.source_edge_accel: return
        accel = self.source_edge_accel
        M, Mi = self.matrix_world, self.matrix_world_inv
        grabbed = {t[0] for t in self.verts}

        for bmv in list(self.snapped_verts):
            if not bmv.is_valid: continue
            bmv_world = local_to_world(bmv.co, M)
            snap_r = self.stroke_snap_radius
            crowd_threshold = snap_r * 0.5
            push_dist = snap_r * 1.5  # world-space distance to push off the edge

            for bme in bmv.link_edges:
                nb = bme.other_vert(bmv)
                if nb in grabbed: continue
                nb_world = local_to_world(nb.co, M)

                # Is neighbor sitting on the source edge?
                closest_point = accel.closest_point(nb_world)
                if not closest_point or (Vector(closest_point) - nb_world).length > snap_r: continue

                sep = (nb_world - bmv_world).length
                if sep >= crowd_threshold: continue

                nb_2d = location_3d_to_region_2d(context.region, context.region_data, nb_world)
                if nb_2d is None: continue

                # Get the screen-space edge tangent at nb's position
                # Tangent from the neighbor's own run: the push direction is derived from this,
                # and the globally nearest feature could be a parallel one across the gap.
                tangent_result = self.closest_on_own_run(nb, nb_world)
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
                hit = raycast_valid_sources(context, sample_2d, respect_clip_planes=True)
                if hit is None: continue

                nb.co = Vector(hit['co_local'])
                self.snapped_verts.discard(nb)
                self.snap_target_world.pop(nb, None)


    def update(self, context, event):
        pressure = getattr(event, 'pressure', 1.0)

        is_nudge_loops = (
            getattr(self.tweak, 'brush_type', 'GRAB') == 'NUDGE'
            and (getattr(self.tweak, 'nudge_loops', False) ^ self.nudge_loops_alt_flip)
        )
        # Nudge+Loops sweeps self.bm.verts directly so it works even with an empty brush.
        if not self.verts and not is_nudge_loops: return
        if event.type != 'MOUSEMOVE': return

        mouse = Vector(mouse_from_event(event))
        delta = mouse - self.mouse_prev
        if delta.length_squared == 0: return

        M = self.matrix_world
        Mi = self.matrix_world_inv

        # Recompute which verts are near the feature and refresh the guide loop election.
        # Vert positions have just changed, so this must run before the per-vert snap.
        if self.source_edge_accel:
            self.update_source_context()

        # Snapshot world positions before moving anything so smudge_sweep can
        # compute per-frame displacement (not accumulated stroke displacement).
        pre_frame_world: dict[BMVert, Vector] = {
            bmv: M @ bmv.co for bmv, *_ in self.verts if bmv.is_valid
        }

        is_nudge         = getattr(self.tweak, 'brush_type', 'GRAB') == 'NUDGE'
        is_pinch_magnify = getattr(self.tweak, 'brush_type', 'GRAB') == 'PINCH_MAGNIFY'
        mode_is_pinch   = getattr(self.tweak, 'pinch_magnify_mode', 'MAGNIFY') == 'PINCH'
        is_pinch         = is_pinch_magnify and (mode_is_pinch ^ self.pinch_ctrl_flip)

        for (bmv, co_orig, xy, strength) in self.verts:
            effective_strength = 0.0 if (is_nudge or is_pinch_magnify) else strength
            if self.mask_opt('boundary') == 'SLIDE' and bmv in self.boundary_verts:
                new_co = Vector(bmv.co)
                delta_strength = delta.length * effective_strength * pressure
                opt_steps = max(math.ceil(delta_strength / 10), 1)
                for step in range(opt_steps):
                    pt2d = self.project_pt(context, new_co) or xy
                    pt = pt2d + delta * (effective_strength / opt_steps) * pressure
                    new_co2 = raycast_valid_sources(context, pt, respect_clip_planes=True)
                    if not new_co2: break
                    new_co = new_co2['co_local']
                    if self.boundary_accel:
                        p = self.boundary_accel.closest_point(new_co)
                        if p is not None:
                            new_co = p
            else:
                cur_xy = self.project_bmv(context, bmv) or xy
                new_co = self.raycast_capped(context, bmv, cur_xy + delta * effective_strength * pressure)
                if new_co is None: continue
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
                    snap_new_co = new_co
                    if is_nudge:
                        # In Nudge the per-frame move differs from the brush move and we need the distance travelled per-vert.
                        capped = self.raycast_capped(context, bmv, cur_xy + delta * strength * pressure)
                        if capped is not None:
                            snap_new_co = capped
                    # Velocity-independent release signal: where the vert would be if unconstrained over the whole stroke.
                    # Capped too, so a snapped vert doesn't teleport to a background object the moment it releases.
                    free_co = self.raycast_capped(context, bmv, xy + (mouse - self.mouse) * strength * pressure)
                    snapped_co = self.snap_to_source_feature(bmv, snap_new_co, strength, context, delta * strength * pressure, mouse - self.mouse, free_co)
                    # In Nudge, snap_new_co is only a probe, showing where the vert would be IF it were dragged full strength.
                    # Only verts the source feature snap actually holds take its result and the rest move via the smudge sweep.
                    if not is_nudge or bmv in self.snapped_verts:
                        new_co = snapped_co

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
                    co_world_snapped = nearest_point_valid_sources(context, point_to_bvec3(co_world), world=True, sources=self.sources, respect_clip_planes=True)
                    if not co_world_snapped: continue
                    co = Mi @ co_world_snapped
                    if d < 0.001: break  # break out if change was below threshold
                if zero['x']: co.x = 0
                if zero['y']: co.y = 0
                if zero['z']: co.z = 0
                new_co = co


            if new_co: bmv.co = new_co

        if is_nudge:
            # Loops mode: defer election to the first meaningful movement so stroke direction
            # is known and the most parallel nearby edge can be scored.
            if (
                (getattr(self.tweak, 'nudge_loops', False) ^ self.nudge_loops_alt_flip)
                and not self.nudge_loop_elected
                and delta.length > 3.0
            ):
                self.elect_nudge_loop(context, delta)
                self.nudge_loop_elected = True
            # Compute 3D displacement: raycast both the current and previous mouse positions
            # onto the source surface and take the difference as the true 3D brush motion.
            delta_3d: 'Vector | None' = None
            curr_hit = raycast_valid_sources(context, mouse, respect_clip_planes=True)
            prev_hit = raycast_valid_sources(context, self.mouse_prev, respect_clip_planes=True)
            if curr_hit and prev_hit:
                d3 = Vector(curr_hit['co_world']) - Vector(prev_hit['co_world'])
                # Reject a movement spike from a bad projection
                world_per_px = self.brush.hit_scale or 0.0
                spike = world_per_px > 0.0 and d3.length > delta.length * world_per_px * 3.0
                if d3.length > 1e-8 and not spike:
                    delta_3d = d3
            self.smudge_sweep(context, mouse, delta, delta_3d, pressure, pre_frame_world)
        elif is_pinch_magnify:
            self.pinch_magnify_sweep(context, mouse, delta, pressure, is_pinch=is_pinch)

        if self.source_edge_accel:
            self.push_crowded_edge_neighbors(context, mouse - self.mouse)

        # Live relax as the brush moves based on comparing stroke len to avg edge len
        relax_factor = float(getattr(self.tweak, 'post_relax_steps', 0.0))
        if relax_factor > 0.0:
            self.relax_accum_px += delta.length
            threshold_px = self.relax_step_px * 0.05 / relax_factor
            while self.relax_accum_px >= threshold_px:
                self.relax_accum_px -= threshold_px
                self.do_relax_step(context)

        bmesh.update_edit_mesh(self.em)
        # context.area.tag_redraw()
        self.mouse_prev = mouse

    def smudge_sweep(self, context, mouse: Vector, delta: Vector, delta_3d: 'Vector | None', pressure: float, pre_frame_world: 'dict[BMVert, Vector]'):
        ''' Nudge-style smear: every vert under the brush is pushed in the 3D stroke
        direction this frame, snapped back onto the source mesh via nearest-point projection.
        - Smooth-step falloff (t²(3-2t)) for a rounded profile.
        - Small lateral spread (10% of forward push) to avoid bunching.
        - Strength controlled by brush.strength only; smudge_factor is on/off + grab blend. '''
        if not self.brush.hit_p:
            return
        brush_centre_world = Vector(self.brush.hit_p)
        radius3D = self.brush.get_scaled_radius()
        if radius3D <= 0:
            return

        if delta.length < 1e-4:
            return
        # In Loops mode use the direction locked at election time so the loop slides
        # in a straight line regardless of how the brush moves after the first tick.
        stroke_dir_2d = (
            self.nudge_stroke_dir_2d
            if (self.nudge_loop_verts and self.nudge_stroke_dir_2d is not None)
            else delta.normalized()
        )

        M = self.matrix_world
        brush_strength = self.brush.strength

        brush_centre_2d = location_3d_to_region_2d(context.region, context.region_data, brush_centre_world)
        if brush_centre_2d is None:
            return

        # In Loops mode, precompute world positions of loop verts once for O(loop) distance queries per vert.
        loop_vert_worlds: list[Vector] = []
        companions: 'set[BMVert]' = set()
        if self.nudge_loop_verts:
            loop_vert_worlds = [M @ v.co for v in self.nudge_loop_verts if v.is_valid and not v.hide]
            companions = self.nudge_companion_verts(radius3D)

        for bmv in self.bm.verts:
            if bmv.hide or not bmv.is_valid:
                continue
            # The elected loop and the verts beside it move even where they dip behind the source.
            # Occlusion gates which loop gets elected, not which verts follow it.
            is_loop_vert = bmv in self.nudge_loop_verts
            if self.is_vert_excluded(bmv, ignore_occluded=(is_loop_vert or bmv in companions)):
                continue

            if self.nudge_loop_verts:
                if is_loop_vert:
                    # Loop vert: always pushed at full strength.
                    t_lin = 1.0
                    t = 1.0
                else:
                    # Non-loop vert: falloff from the nearest loop vert in world space,
                    # as if every loop vert were its own brush center.
                    if not loop_vert_worlds:
                        continue
                    bmv_world = M @ bmv.co
                    dist_to_loop = min((bmv_world - lw).length for lw in loop_vert_worlds)
                    if dist_to_loop > radius3D:
                        continue
                    t_lin = 1.0 - dist_to_loop / radius3D
                    t = t_lin
            else:
                dist = (M @ bmv.co - brush_centre_world).length
                if dist > radius3D:
                    continue
                t_lin = 1.0 - dist / radius3D
                vert_str = self.brush.get_strength_Point(M @ bmv.co)
                t = vert_str / brush_strength if brush_strength > 1e-8 else t_lin

            cur_2d = self.project_bmv(context, bmv)
            if cur_2d is None:
                continue

            if delta_3d is None:
                continue

            if self.nudge_loop_verts:
                # Loops mode: use the 3D tangent locked at election time (loop verts) or cached on
                # first encounter (surrounding verts).  Never recompute from live positions —
                # that caused diagonal-stroke flipping as edges drifted between frames.
                tangent_3d = self.nudge_vert_tangents.get(bmv)
                if tangent_3d is None:
                    # First time this vert enters the brush: compute and lock from stable positions.
                    best_t3d_c: 'Vector | None' = None

                    if is_loop_vert:
                        # Loop vert off-screen at election: use local loop tangent geometry,
                        # matching elect_nudge_loop exactly.
                        loop_nbs_c = [bme.other_vert(bmv) for bme in bmv.link_edges
                                      if not bme.other_vert(bmv).hide
                                      and bme.other_vert(bmv) in self.nudge_loop_verts]
                        lt_c: 'Vector | None' = None
                        if len(loop_nbs_c) >= 2:
                            lt_c = (M @ loop_nbs_c[1].co) - (M @ loop_nbs_c[0].co)
                        elif len(loop_nbs_c) == 1:
                            lt_c = (M @ loop_nbs_c[0].co) - (M @ bmv.co)
                        if lt_c is not None and lt_c.length > 1e-8:
                            lt_c = lt_c / lt_c.length
                            best_perp_c = -1.0
                            for bme in bmv.link_edges:
                                nb = bme.other_vert(bmv)
                                if nb.hide or nb in self.nudge_loop_verts: continue
                                d3d_c = (M @ nb.co) - (M @ bmv.co)
                                if d3d_c.length < 1e-8: continue
                                d3d_c_n = d3d_c / d3d_c.length
                                perp_c = 1.0 - abs(d3d_c_n.dot(lt_c))
                                if perp_c > best_perp_c:
                                    best_perp_c = perp_c
                                    best_t3d_c = d3d_c_n
                    else:
                        # Adjacent (non-loop) vert: the edge toward a loop vert IS the
                        # perpendicular direction by definition, regardless of how the loop
                        # curves.  Pick by largest projected screen length (most visible)
                        # rather than stroke alignment, so curved loops work correctly.
                        best_vis_c = -1.0
                        for bme in bmv.link_edges:
                            nb = bme.other_vert(bmv)
                            if nb.hide or nb not in self.nudge_loop_verts: continue
                            d3d_c = (M @ nb.co) - (M @ bmv.co)
                            if d3d_c.length < 1e-8: continue
                            p_nb_c = self.project_bmv(context, nb)
                            if p_nb_c is None: continue
                            vis_c = (Vector(p_nb_c) - Vector(cur_2d)).length
                            if vis_c > best_vis_c:
                                best_vis_c = vis_c
                                best_t3d_c = d3d_c / d3d_c.length
                        if best_t3d_c is None:
                            # No visible loop-vert neighbor; fall back to best stroke alignment.
                            best_dot_fb = -1.0
                            for bme in bmv.link_edges:
                                nb = bme.other_vert(bmv)
                                if nb.hide: continue
                                p_nb_c = self.project_bmv(context, nb)
                                if p_nb_c is None: continue
                                d2d_c = Vector(p_nb_c) - Vector(cur_2d)
                                if d2d_c.length < 1e-4: continue
                                dot_fb = abs((d2d_c / d2d_c.length).dot(stroke_dir_2d))
                                if dot_fb > best_dot_fb:
                                    best_dot_fb = dot_fb
                                    d3d_c = (M @ nb.co) - (M @ bmv.co)
                                    if d3d_c.length > 1e-8:
                                        best_t3d_c = d3d_c / d3d_c.length

                    if best_t3d_c is not None:
                        self.nudge_vert_tangents[bmv] = best_t3d_c
                        tangent_3d = best_t3d_c
                if tangent_3d is not None:
                    proj_3d = delta_3d.dot(tangent_3d)
                    push_3d = tangent_3d * proj_3d * t * brush_strength * pressure
                else:
                    push_3d = delta_3d * t * brush_strength * pressure
            else:
                push_3d = delta_3d * t * brush_strength * pressure

            # Cap the per-frame push to one brush radius
            if push_3d.length > radius3D:
                push_3d = push_3d * (radius3D / push_3d.length)
            new_vert_world = (M @ bmv.co) + push_3d
            new_pt = nearest_point_valid_sources(context, point_to_bvec3(new_vert_world), world=True, sources=self.sources, respect_clip_planes=True)
            if new_pt is None:
                continue
            new_co = self.matrix_world_inv @ new_pt
            new_co = self.apply_slide_constraints(bmv, new_co)
            new_co = self.apply_mirror_clip(context, bmv, new_co)
            bmv.co = new_co

    def pinch_magnify_sweep(self, context, mouse: Vector, delta: Vector, pressure: float, is_pinch: bool):
        ''' Pinch/Magnify: every vert under the brush is pulled toward (Pinch) or pushed
        away from (Magnify) the brush center in screen space each frame, then raycasted
        back onto the source mesh.  Movement magnitude scales with mouse speed (delta.length),
        brush strength, pressure, and the per-vert falloff weight so verts at the brush
        periphery are nudged less than those at the center.
        Only verts whose screen-space offset from the brush center is perpendicular to the
        stroke direction are affected (weight = |sin θ|), so stroking along a loop does not
        shrink the loop itself but only draws in the surrounding cross-edges. '''
        if not self.brush.hit_p:
            return
        brush_centre_world = Vector(self.brush.hit_p)
        radius3D = self.brush.get_scaled_radius()
        if radius3D <= 0:
            return

        if delta.length < 1e-4:
            return

        stroke_dir_2d = delta.normalized()  # unit vector along the stroke in screen space

        M = self.matrix_world
        brush_strength = self.brush.strength

        brush_centre_2d = location_3d_to_region_2d(context.region, context.region_data, brush_centre_world)
        if brush_centre_2d is None:
            return

        for bmv in self.bm.verts:
            if bmv.hide or not bmv.is_valid:
                continue
            if self.is_vert_excluded(bmv):
                continue
            dist = (M @ bmv.co - brush_centre_world).length
            if dist > radius3D:
                continue

            # Derive a 0→1 spatial weight from the brush falloff curve.
            t_lin = 1.0 - dist / radius3D
            vert_str = self.brush.get_strength_Point(M @ bmv.co)
            t = vert_str / brush_strength if brush_strength > 1e-8 else t_lin

            cur_2d = self.project_bmv(context, bmv)
            if cur_2d is None:
                continue

            # Radial direction relative to the brush center in screen space.
            radial_2d = Vector(brush_centre_2d) - Vector(cur_2d)
            radial_len = radial_2d.length
            if radial_len < 1e-4:
                # Vert is already at the brush center; skip to avoid zero-length direction.
                continue

            # Perpendicular weight: |sin θ| between the vert's radial offset and the stroke.
            # = 1.0 when vert is fully perpendicular to stroke (cross-edges → full effect).
            # = 0.0 when vert is parallel to stroke (the loop being stroked → no effect).
            along = radial_2d.dot(stroke_dir_2d)
            perp_2d = radial_2d - stroke_dir_2d * along
            perp_weight = perp_2d.length / radial_len  # equivalent to |sin(θ)|

            if perp_weight < 1e-4:
                continue

            radial_dir_2d = radial_2d / radial_len
            if not is_pinch:
                radial_dir_2d = -radial_dir_2d  # Magnify: push outward

            push_2d = radial_dir_2d * delta.length * t * brush_strength * pressure * perp_weight * 0.25

            new_co = self.raycast_capped(context, bmv, cur_2d + push_2d)
            if new_co is None:
                continue
            new_co = self.apply_slide_constraints(bmv, new_co)
            new_co = self.apply_mirror_clip(context, bmv, new_co)
            bmv.co = new_co

    def do_relax_step(self, context):
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
        # Only verts the snapper actually locked to the source edge keep their end padding, so the
        # snap circle reads cleanly; the line runs straight through every un-snapped vert. Using
        # snapped_verts (authoritative, persists across the grab) avoids highlighting verts that
        # merely drift inside the snap radius without being snapped.
        snapped_loop = self.promoted_loop_verts & self.snapped_verts
        Drawing.draw_loop_highlight(context, self.promoted_loop_verts, self.matrix_world, highlight, skip_verts=snapped_loop, vert_groups=self.vert_feature_run)
        Drawing.draw_loop_highlight(context, self.nudge_loop_verts, self.matrix_world, highlight, skip_verts=frozenset())
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
