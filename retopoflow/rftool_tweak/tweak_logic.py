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
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_origin_3d, region_2d_to_vector_3d
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
    raycast_valid_sources, nearest_point_valid_sources,
    mouse_from_event, iter_all_valid_sources, make_hidden_tester,
)

from ...addon_common.common.maths import sign_threshold
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

    nudge_loop_verts : 'set[BMVert]'  # loop elected once per Nudge-Loops stroke; empty for Brush mode
    _nudge_vert_tangents : 'dict[BMVert, Vector]'  # slide tangent per vert, locked once (at election or first encounter)

    verts_filtered : list[BMVert]
    verts : list[tuple]  # (bmv, original co, projected xy, brush strength) captured at grab time

    mouse : Vector
    mouse_prev : Vector


    def __init__(self, context, event, brush, tweak):
        self.brush = brush
        self.tweak = tweak
        # Capture Ctrl at stroke start to invert Pinch/Magnify for the whole stroke (mirrors Blender sculpt behavior).
        # The Ctrl+LMB keymap entry in rf_keymaps ensures Blender's Select Shortest Path never fires first.
        self._pinch_ctrl_flip: bool = (
            bool(getattr(event, 'ctrl', False))
            and getattr(tweak, 'brush_type', 'GRAB') == 'PINCH_MAGNIFY'
        )
        # Capture Alt at stroke start to toggle Loops mode for this stroke.
        self._nudge_loops_alt_flip: bool = (
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
        self.source_edge_accel = SourceCache.get(context)
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
        self.nudge_loop_verts: set[BMVert] = set()
        self._nudge_loop_elected: bool = False
        self._nudge_stroke_dir_2d: 'Vector | None' = None  # locked at election time
        self._nudge_vert_tangents: dict[BMVert, Vector] = {}  # locked at election or first encounter

        # Spatial accel over all non-hidden retopo verts for O(1) corner-occupant lookup.
        # Only built when feature snapping is active
        all_verts = [v for v in self.bm.verts if not v.hide] if self.source_edge_accel else []
        self.vert_accel : 'Accel | None' = Accel(context, all_verts, self.matrix_world) if all_verts else None

        # Cache mesh-wide edge-mark presence so per-vert checks in sweeps don't scan all edges.
        self._has_any_seam  = any(bme.seam for bme in self.bm.edges)
        self._has_any_sharp = any(not bme.smooth for bme in self.bm.edges)

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


    def _elect_nudge_loop(self, context, delta: Vector):
        ''' Score each screen-space edge by proximity to the mouse AND parallelism with the
        stroke direction, then walk its full loop.  Calling on the first meaningful mouse
        movement ensures stroke direction is known, so the right loop is chosen even when
        the user starts on a vertex shared by multiple loops. '''
        self.nudge_loop_verts = set()
        rgn, r3d = context.region, context.region_data
        M = self.matrix_world
        mouse_2d = self.mouse
        stroke_dir_2d = delta.normalized()
        self._nudge_stroke_dir_2d = stroke_dir_2d  # lock direction for the whole stroke

        # Score: (1 - parallelism with stroke) / (screen-space distance to edge + 1).
        # High score = edge runs perpendicular to stroke AND is close to the mouse.
        # Perpendicular edges are the cross-edges whose loop runs parallel to the stroke direction.
        best_edge: BMEdge | None = None
        best_score = -1.0
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
            if score > best_score:
                best_score = score
                best_edge = bme

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
        self._nudge_vert_tangents.clear()
        def _best_tangent_3d(bmv_):
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
            t3d_ = _best_tangent_3d(bmv_)
            if t3d_ is not None:
                self._nudge_vert_tangents[bmv_] = t3d_


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
    # Masking helpers (used by nudge / pinch sweeps)
    # -------------------------------------------------------------------------

    def _is_vert_excluded(self, bmv: BMVert) -> bool:
        ''' True if bmv must not be moved by a sweep (replicates EXCLUDE/ONLY/corner filters
        from collect_verts so that nudge and pinch respect the same masking as GRAB). '''
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
        if self.mask_opt('seams') == 'EXCLUDE' and self._has_any_seam and is_bmvert_on_edgemark(self.bm, bmv, BMMarking.seam):
            return True
        if self.mask_opt('sharps') == 'EXCLUDE' and self._has_any_sharp and is_bmvert_on_edgemark(self.bm, bmv, BMMarking.sharp):
            return True
        if self.mask_opt('angle') == 'EXCLUDE' and self.angle_verts and bmv in self.angle_verts:
            return True
        if self.exclude_opt('occluded') and self.is_bmvert_hidden(bmv):
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

    def _apply_slide_constraints(self, bmv: BMVert, new_co: Vector) -> Vector:
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

    def _apply_mirror_clip(self, context, bmv: BMVert, new_co: Vector) -> Vector:
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

    def _source_corner_of_vert(self, bmv, world_threshold):
        ''' If bmv sits within `world_threshold` (world-space units) of a source corner,
        return (corner_co_world, corner_idx, distance); else None. '''
        if not self.source_edge_accel: return None
        cr = self.source_edge_accel.find_corner(local_to_world(bmv.co, self.matrix_world))
        if cr and cr[2] < world_threshold:
            return cr
        return None

    def _is_on_source_edge(self, v):
        ''' True if v currently lies on (within snap proximity of) a source feature edge.
        Used to spare verts that legitimately ride a source edge from guide-loop demotion. '''
        if not self.source_edge_accel or not v.link_edges:
            return False
        v_world = local_to_world(v.co, self.matrix_world)
        closest = self.source_edge_accel.closest_point(v_world)
        if not closest:
            return False
        return (Vector(closest) - v_world).length <= self.stroke_snap_radius

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
            bmv_world = local_to_world(bmv.co, self.matrix_world)
            closest_v = self.source_edge_accel.closest_point(bmv_world)
            if not closest_v: continue
            diff = Mi @ Vector(closest_v) - bmv.co
            dist = diff.length
            if dist * self.scale_avg <= self.stroke_snap_radius:
                if dist < 1e-8 or (diff / dist).dot(bmv.normal) > 0.3:
                    result[bmv] = diff
        return result

    def _seed_guide_loop(self):
        ''' Pick the seed edge nearest the brush centre (among retopo edges with both ends on the
        feature) and elect the guide loop from it. Called when no loop is currently elected. '''
        guide_edges = [
            bme for bmv in self.verts_near_source_edge
            for bme in bmv.link_edges
            if bme.other_vert(bmv) in self.verts_near_source_edge
        ]
        # Need at least one retopo edge where both endpoints are on the feature.
        if not guide_edges: return

        # Pick the seed edge whose midpoint is closest to the brush center (the cursor).
        # Anchoring to the live brush center rather than an arbitrary grabbed vert means a
        # large brush elects the loop under the cursor, not one out on the brush's rim.
        if self.brush.hit_p:
            brush_co_local = (self.matrix_world_inv @ Vector((*self.brush.hit_p, 1.0))).xyz
        elif self.verts:
            brush_co_local = self.verts[0][0].co
        else:
            brush_co_local = Vector((0, 0, 0))
        guide_edge = min(
            guide_edges,
            key=lambda e: ((e.verts[0].co + e.verts[1].co) * 0.5 - brush_co_local).length,
        )
        self._elect_loop_from_edge(guide_edge.verts[0], guide_edge.verts[1])

    def _elect_loop_from_edge(self, v0, v1):
        ''' Walk the loop from seed edge (v0, v1) and derive promoted/demoted from CURRENT vert
        positions. Re-run every frame so a vert that snaps to a source corner mid-stroke is
        recognised as a corner (the loop terminates there), not only when it started on the corner. '''
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
        if not promoted:
            self.promoted_loop_verts = set()
            self.demoted_verts = set()
            self.loop_guide_verts = None
            return

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
                v_is_boundary = any(e.is_boundary for e in v.link_edges)
                for bmf in v.link_faces:
                    if len(bmf.verts) != 4: continue
                    for fv in bmf.verts:
                        if fv is v or fv in all_adj: continue
                        # A vert that itself rides a source edge (e.g. the perpendicular feature
                        # meeting the loop where it ends at a corner) belongs there, so don't demote it.
                        if is_bmvert_corner(fv) or self._is_on_source_edge(fv): continue
                        # When the loop ends at a boundary corner, never demote its fellow boundary verts.
                        if v_is_boundary and any(e.is_boundary for e in fv.link_edges): continue
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

        # Re-derive the loop from its persisted seed edge every frame so a vert that snaps to a
        # source corner mid-stroke is recognised as a corner now, not only if it started there.
        if self.loop_guide_verts is not None:
            gv0, gv1 = self.loop_guide_verts
            if gv0.is_valid and gv1.is_valid:
                self._elect_loop_from_edge(gv0, gv1)

        if self.verts_near_source_edge and not self.promoted_loop_verts:
            self._seed_guide_loop()

        # The closest snapped vert owns each corner and face-diagonal neighbours of the owner are
        # demoted, except neighbours that themselves ride a source edge.
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
                cv_is_boundary = any(e.is_boundary for e in cv.link_edges)
                for bmf in cv.link_faces:
                    if len(bmf.verts) != 4: continue
                    for fv in bmf.verts:
                        if fv is cv or fv in all_adj: continue
                        if fv in self.promoted_loop_verts or is_bmvert_corner(fv) or self._is_on_source_edge(fv): continue
                        # When the owner is a boundary corner, never demote its fellow boundary verts.
                        if cv_is_boundary and any(e.is_boundary for e in fv.link_edges): continue
                        self.demoted_verts.add(fv)

    def _find_corner_occupant(self, corner_co_world, incoming_bmv, radius):
        ''' Find a vert other than incoming_bmv sitting in a source corner.
        Check snapped_verts first, fallback to accel so the full bmesh is never iterated linearly. '''
        corner_w = Vector(corner_co_world)

        # Fast path: verts snapped this stroke are the most likely occupants.
        for v in self.snapped_verts:
            if v is incoming_bmv: continue
            if (local_to_world(v.co, self.matrix_world) - corner_w).length <= radius:
                return v

        # Fallback: Accel covers verts snapped in previous strokes.
        # Use a tight radius - the occupant must actually be sitting at the corner.
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
        kick_dir_world: Vector | None = None

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

    def _push_crowded_edge_neighbors(self, context, stroke_disp_2d):
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
                hit = raycast_valid_sources(context, sample_2d, respect_clip_planes=True)
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
        new_co_world = local_to_world(new_co, M)

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
                self.snap_target_world[bmv] = local_to_world(Vector(bmv.co), M)
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
                    bmv_world = local_to_world(bmv.co, M)
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

        is_nudge_loops = (
            getattr(self.tweak, 'brush_type', 'GRAB') == 'NUDGE'
            and (getattr(self.tweak, 'nudge_loops', False) ^ self._nudge_loops_alt_flip)
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
            self._update_source_context()

        # Snapshot world positions before moving anything so _smudge_sweep can
        # compute per-frame displacement (not accumulated stroke displacement).
        pre_frame_world: dict[BMVert, Vector] = {
            bmv: M @ bmv.co for bmv, *_ in self.verts if bmv.is_valid
        }

        is_nudge         = getattr(self.tweak, 'brush_type', 'GRAB') == 'NUDGE'
        is_pinch_magnify = getattr(self.tweak, 'brush_type', 'GRAB') == 'PINCH_MAGNIFY'
        _mode_is_pinch   = getattr(self.tweak, 'pinch_magnify_mode', 'MAGNIFY') == 'PINCH'
        is_pinch         = is_pinch_magnify and (_mode_is_pinch ^ self._pinch_ctrl_flip)
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
                new_co = raycast_valid_sources(context, cur_xy + delta * effective_strength * pressure, respect_clip_planes=True)
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
                    new_co = self.snap_to_source_feature(bmv, new_co, effective_strength, context, delta * effective_strength * pressure, mouse - self.mouse)

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
                (getattr(self.tweak, 'nudge_loops', False) ^ self._nudge_loops_alt_flip)
                and not self._nudge_loop_elected
                and delta.length > 3.0
            ):
                self._elect_nudge_loop(context, delta)
                self._nudge_loop_elected = True
            # Compute 3D displacement: raycast both the current and previous mouse positions
            # onto the source surface and take the difference as the true 3D brush motion.
            delta_3d: 'Vector | None' = None
            curr_hit = raycast_valid_sources(context, mouse, respect_clip_planes=True)
            prev_hit = raycast_valid_sources(context, self.mouse_prev, respect_clip_planes=True)
            if curr_hit and prev_hit:
                d3 = Vector(curr_hit['co_world']) - Vector(prev_hit['co_world'])
                if d3.length > 1e-8:
                    delta_3d = d3
            self._smudge_sweep(context, mouse, delta, delta_3d, pressure, pre_frame_world)
        elif is_pinch_magnify:
            self._pinch_magnify_sweep(context, mouse, delta, pressure, is_pinch=is_pinch)

        if self.source_edge_accel:
            self._push_crowded_edge_neighbors(context, mouse - self.mouse)

        # Live relax as the brush moves based on comparing stroke len to avg edge len
        relax_factor = float(getattr(self.tweak, 'post_relax_steps', 0.0))
        if relax_factor > 0.0:
            self.relax_accum_px += delta.length
            threshold_px = self.relax_step_px * 0.05 / relax_factor
            while self.relax_accum_px >= threshold_px:
                self.relax_accum_px -= threshold_px
                self._do_relax_step(context)

        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()
        self.mouse_prev = mouse

    def _smudge_sweep(self, context, mouse: Vector, delta: Vector, delta_3d: 'Vector | None', pressure: float, pre_frame_world: 'dict[BMVert, Vector]'):
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
            self._nudge_stroke_dir_2d
            if (self.nudge_loop_verts and self._nudge_stroke_dir_2d is not None)
            else delta.normalized()
        )

        M = self.matrix_world
        brush_strength = self.brush.strength

        brush_centre_2d = location_3d_to_region_2d(context.region, context.region_data, brush_centre_world)
        if brush_centre_2d is None:
            return

        # In Loops mode, precompute world positions of loop verts once for O(loop) distance queries per vert.
        loop_vert_worlds: list[Vector] = []
        if self.nudge_loop_verts:
            loop_vert_worlds = [M @ v.co for v in self.nudge_loop_verts if v.is_valid and not v.hide]

        for bmv in self.bm.verts:
            if bmv.hide or not bmv.is_valid:
                continue
            if self._is_vert_excluded(bmv):
                continue

            if self.nudge_loop_verts:
                if bmv in self.nudge_loop_verts:
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
                tangent_3d = self._nudge_vert_tangents.get(bmv)
                if tangent_3d is None:
                    # First time this vert enters the brush: compute and lock from stable positions.
                    best_t3d_c: 'Vector | None' = None

                    if bmv in self.nudge_loop_verts:
                        # Loop vert off-screen at election: use local loop tangent geometry,
                        # matching _elect_nudge_loop exactly.
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
                        self._nudge_vert_tangents[bmv] = best_t3d_c
                        tangent_3d = best_t3d_c
                if tangent_3d is not None:
                    proj_3d = delta_3d.dot(tangent_3d)
                    push_3d = tangent_3d * proj_3d * t * brush_strength * pressure
                else:
                    push_3d = delta_3d * t * brush_strength * pressure
            else:
                push_3d = delta_3d * t * brush_strength * pressure

            new_vert_world = (M @ bmv.co) + push_3d
            new_pt = nearest_point_valid_sources(context, point_to_bvec3(new_vert_world), world=True, sources=self.sources, respect_clip_planes=True)
            if new_pt is None:
                continue
            new_co = self.matrix_world_inv @ new_pt
            new_co = self._apply_slide_constraints(bmv, new_co)
            new_co = self._apply_mirror_clip(context, bmv, new_co)
            bmv.co = new_co

    def _pinch_magnify_sweep(self, context, mouse: Vector, delta: Vector, pressure: float, is_pinch: bool):
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
            if self._is_vert_excluded(bmv):
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

            new_hit = raycast_valid_sources(context, cur_2d + push_2d, respect_clip_planes=True)
            if not new_hit:
                continue
            new_co = Vector(new_hit['co_local'])
            new_co = self._apply_slide_constraints(bmv, new_co)
            new_co = self._apply_mirror_clip(context, bmv, new_co)
            bmv.co = new_co

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
        # Only verts the snapper actually locked to the source edge keep their end padding, so the
        # snap circle reads cleanly; the line runs straight through every un-snapped vert. Using
        # snapped_verts (authoritative, persists across the grab) avoids highlighting verts that
        # merely drift inside the snap radius without being snapped.
        snapped_loop = self.promoted_loop_verts & self.snapped_verts
        Drawing.draw_loop_highlight(context, self.promoted_loop_verts, self.matrix_world, highlight, skip_verts=snapped_loop)
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
