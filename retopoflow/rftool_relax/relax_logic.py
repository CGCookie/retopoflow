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
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_origin_3d, region_2d_to_vector_3d
from bpy.types import Context, Event, Region, RegionView3D, Mesh, PropertyGroup
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from bmesh.types import BMesh, BMVert, BMEdge

import math
import time
from math import isnan, inf, acos, tan
from typing import Callable
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from ..common.accel import EdgeMarkAccel, SourceAccel, Accel, SourceCache
from ..common.snapping import FeatureRunsMixin, source_snap_radius, source_snap_settings
from ..common.bmesh import (
    get_bmesh_emesh, is_bmedge_boundary, is_bmvert_boundary, is_bmvert_corner, is_bmvert_on_ngon,
    bmv_is_interior, bme_midpoint, bmf_midpoint,
    bmv_co_isnan, bmv_compute_normal,
    get_bmv_loop_pairs, get_bmv_avg_edge_len, get_bmv_next_loop_vert,
    bme_vector, bme_length,
    bmf_is_flipped,
)
from ..common.bmesh_maths import (
    is_bmvert_on_edgemark, is_bmedge_edgemark, BMMarking,
    is_bmvert_pinned,
    is_bmvert_creased,
)
from ..common.maths import (
    view_forward_direction, view_right_direction, view_up_direction,
    xform_direction, local_to_world,
    point_to_bvec3,
)
from ..common.raycast import (
    raycast_valid_sources,
    nearest_point_valid_sources,
    mouse_from_event,
    iter_all_valid_sources,
    make_hidden_tester,
)
from ..common.drawing import (
    Drawing,
    CC_2D_LINES,
    CC_2D_POINTS,
)

from ...addon_common.terminal import term_printer
from ...addon_common.common.maths import Point, sign_threshold, clamp_int, clamp
from ...addon_common.common.colors import Color4


@dataclass
class RelaxOptions:
    algorithm_method: str = 'AUTO' # 'AUTO' | 'STEPS' | 'RK4'
    algorithm_iterations: int = 2
    algorithm_max_distance_radius: float = 0.10
    algorithm_max_distance_edges: float = 0.05
    algorithm_prevent_bounce: bool = False
    algorithm_laplacian: bool = True
    algorithm_average_edge_lengths: bool = False
    algorithm_straighten_edges: bool = True
    algorithm_equalize_faces: bool = False
    algorithm_correct_flipped_faces: bool = False
    algorithm_interpolate_loops: bool = False
    algorithm_slide_edges: bool = False
    algorithm_source_corner_proximity: float = 2.0
    source_edge_angle: float = math.radians(45)
    source_edge_seams: bool = False
    source_edge_creases: bool = False
    source_edge_sharps: bool = False
    source_edge_proximity: float = 0.25
    source_edge_use_fixed_distance: bool = False
    source_edge_fixed_distance: float = 0.05
    source_edge_stickiness: float = 0.5
    source_edge_guide_loops: float = 1.0


class Relax_Logic(FeatureRunsMixin):
    bm : BMesh
    em : Mesh
    matrix_world : Matrix
    matrix_world_inv : Matrix
    scale_avg : float
    mirror : set[str]
    mirror_clip : bool
    mirror_threshold : Vector

    rf_options : PropertyGroup

    check_nans : bool = True

    sources : 'list[tuple[object, Matrix, Matrix, Matrix]]'

    vert_filter_cache_key   : 'tuple | None' = None
    vert_filter_cache : 'list[BMVert] | None' = None

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
    verts_near_source_edge: 'dict[BMVert, Vector]'
    snapped_verts: 'set[BMVert]'

    is_bmvert_hidden : Callable[[BMVert], bool]
    visibility_cache : dict[BMVert, bool]

    source_edge_accel : SourceAccel | None
    source_sharp_proximity : float
    source_use_fixed : bool
    source_fixed_distance : float
    # run/guide-loop state (promoted/demoted, vert_feature_run, ...) is declared on FeatureRunsMixin

    forward : Vector
    right : Vector
    up : Vector

    mouse : tuple[int, int]
    pressure : float

    prev_position : dict[BMVert, Vector]    # remember where verts were in case of cancel
    prev_displace : dict[BMVert, Vector]    # attempt at preventing verts bouncing unstably
    bounce_mult : dict[BMVert, float]       # ...

    verts_accel : Accel
    laplacian_cache : dict[BMVert, tuple[tuple[BMVert, ...], bool, float] | None]
    straighten_cache : dict[BMVert, tuple[bool, tuple[BMVert, ...], tuple[BMVert, ...], int] | None]
    straighten_loops_cache : dict[BMVert, tuple[tuple[BMVert, BMVert], ...] | None]
    loop_interp_cache : dict[BMVert, 'list[tuple] | None']
    face_topology_cache : dict[BMVert, tuple[tuple[BMVert, ...], tuple[BMEdge, ...]] | None]

    # debugging and profiling
    draw_vectors_positive : list[tuple[Vector,Vector]]
    draw_vectors_negative : list[tuple[Vector,Vector]]
    draw_vectors_net : list[tuple[Vector,Vector]]
    _time : float


    def __init__(self, context:Context, event:Event, brush, relax, *, debug_print:bool=False): #MARK: Init
        timings : list[tuple[str,float]] = [('start', time.time())]

        assert context.edit_object, 'Expected to be editing a mesh object'

        self.initial_setup(context, relax)
        timings.append(('initial setup', time.time()))

        self.brush = brush
        self._time = time.time()
        self.mouse = mouse_from_event(event)
        self.pressure = 1.0

        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        self.bm.verts.ensure_lookup_table() # So we can skip this in the per vert fns below

        self.verts_filtered = [
            bmv for bmv in self.bm.verts
            if not bmv.is_wire and not (bmv.is_boundary and is_bmvert_on_ngon(bmv))
        ]

        if Relax_Logic.check_nans:
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not bmv_co_isnan(bmv) ]
            Relax_Logic.check_nans = False

        # Tier 1: O(1) direct attribute reads
        self.verts_filtered = [ bmv for bmv in self.verts_filtered if not bmv.hide ]
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
            if self.bm.verts.layers.float.get('crease_vert'): #TODO: Make sure this works in older versions of Blender. Before this was generic attr?
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
        # Tier 6: iterate link_edges calling a function per edge. Edge marks are pre-built so truthiness check is free.
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

        timings.append(('filtering', time.time()))
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

            def is_point_hidden_fast(point_world:Vector, *,factor:float=0.99) -> bool:
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

            # self.verts_filtered = [
            #     bmv for bmv in self.verts_filtered
            #     if not is_point_hidden_fast(matrix_world @ bmv.co)
            # ]

        timings.append(('verts accel', time.time()))
        self.verts_accel = Accel(context, self.verts_filtered, self.matrix_world)

        timings.append(('finished', time.time()))
        total_time = timings[-1][1] - timings[0][1]
        report = [
            f'{time1-time0:0.3f}s {label}'
            for (label, time0), (_label, time1) in zip(timings[:-1], timings[1:])
        ] + ['------ --------------', f'{total_time:0.3f}s total']
        if debug_print:
            term_printer.boxed(*report, title='Timings for Relax_Logic.__init__()')


    def initial_setup(self, context:Context, relax, rf_options=None): #MARK: Initial setup
        self.relax = relax
        self.rf_options = rf_options if rf_options is not None else context.scene.retopoflow

        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        self.warned_limiting = False

        self.prev_position = {}
        self.prev_displace = {}
        self.bounce_mult = {}

        self.draw_vectors_positive = []
        self.draw_vectors_negative = []
        self.draw_vectors_net = []

        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe()
        # View directions are only needed by average_face_angles
        Mi = self.matrix_world_inv
        if context.region_data:
            self.forward = xform_direction(Mi, view_forward_direction(context))
            self.right   = xform_direction(Mi, view_right_direction(context))
            self.up      = xform_direction(Mi, view_up_direction(context))
        else:
            # Fall back to world-space defaults when there is no 3D view
            self.forward = xform_direction(Mi, Vector((0, 0, -1)))
            self.right   = xform_direction(Mi, Vector((1, 0,  0)))
            self.up      = xform_direction(Mi, Vector((0, 1,  0)))
        self.scale_avg = sum(self.matrix_world.to_scale()) / 3

        self.mirror = set()
        self.mirror_clip = False
        self.mirror_threshold = Vector((0, 0, 0))
        for mod in context.edit_object.modifiers:
            # last one in stack is the one that shows up
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

        # Angle mask computed from angles between adjacent faces, not a stored BMesh attribute
        self.angle_verts = set()
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

        snapping = context.scene.retopoflow.snapping
        self.source_edge_accel = SourceCache.get(context)
        self.source_use_fixed, self.source_fixed_distance, self.source_sharp_proximity = source_snap_settings(context)
        self.stickiness = getattr(snapping, 'source_edge_stickiness', 0.5) if self.source_edge_accel else 0.0

        self.laplacian_cache = {}
        self.straighten_cache = {}
        self.straighten_loops_cache = {}
        self.loop_interp_cache = {}
        self.face_topology_cache = {}
        self.promoted_loop_verts = set()
        self.demoted_verts = set()
        self.guide_loop_seeds = []
        self.vert_feature_run = {}
        self.run_segments = {}
        self.run_of_seg = {}
        self.demoted_by_runs = {}
        self._vert_seed_seg = {}
        self.verts_near_source_edge = {}
        self.snapped_verts = set()

    @classmethod
    def for_options(cls, context:Context, relax, rf_options=None) -> 'Relax_Logic':
        ''' Build a brush-less instance for callers that bring their own verts.
        The brush-only spatial-query/occlusion state is intentionally left unset, so update()
        must NOT be called on an instance built this way... drive relax_verts() directly. '''
        self = cls.__new__(cls)
        self.initial_setup(context, relax, rf_options=rf_options)
        return self

    def mask_opt(self, name : str) -> str:
        return str(getattr(self.rf_options, f'mask_{name}', 'INCLUDE'))  # pyright: ignore[reportAny]
    def include_opt(self, name : str) -> bool:
        return bool(getattr(self.rf_options, f'include_{name}', True))  # pyright: ignore[reportAny]
    def exclude_opt(self, name : str) -> bool:
        return not bool(getattr(self.rf_options, f'include_{name}', True))  # pyright: ignore[reportAny]

    def filter_verts(self, verts:'set[BMVert]') -> 'set[BMVert]':
        ''' Apply scene masking options to an externally-supplied vert set.
        Used by non-brush callers so they get the same masking as the Relax brush. '''
        filtered : list[BMVert] = [bmv for bmv in verts if not bmv.hide]

        # Tier 2: O(1) len() checks
        if self.exclude_opt('corners'):
            filtered = [ bmv for bmv in filtered if not is_bmvert_corner(bmv) ]
        if self.mask_opt('boundary') == 'SLIDE':
            filtered = [ bmv for bmv in filtered if not is_bmvert_corner(bmv) ]
        # Tier 3: attribute check
        if self.mask_opt('boundary') == 'EXCLUDE':
            filtered = [ bmv for bmv in filtered if not is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip) ]
        # Tier 4: layer dict-lookup
        if self.exclude_opt('pinned'):
            filtered = [ bmv for bmv in filtered if not is_bmvert_pinned(self.bm, bmv, ensure_lookup_table=False) ]
        if self.mask_opt('creases') == 'EXCLUDE':
            if self.bm.verts.layers.float.get('crease_vert'):
                filtered = [ bmv for bmv in filtered if (
                    not is_bmvert_creased(self.bm, bmv, ensure_lookup_table=False)
                    or is_bmvert_pinned(self.bm, bmv, ensure_lookup_table=False)
                )]
            if self.bm.edges.layers.float.get('crease_edge'):
                filtered = [ bmv for bmv in filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.crease) ]
        # Tier 5
        if self.mask_opt('seams') == 'EXCLUDE':
            if any(bme.seam for bme in self.bm.edges):
                filtered = [ bmv for bmv in filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.seam) ]
        if self.mask_opt('sharps') == 'EXCLUDE':
            if any(not bme.smooth for bme in self.bm.edges):
                filtered = [ bmv for bmv in filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.sharp) ]
        if self.mask_opt('angle') == 'EXCLUDE' and self.angle_verts:
            filtered = [ bmv for bmv in filtered if bmv not in self.angle_verts ]
        # Tier 6
        if self.mask_opt('seams') == 'SLIDE' and self.seam_verts:
            filtered = [ bmv for bmv in filtered if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.seam)   for bme in bmv.link_edges) > 2 ]
        if self.mask_opt('sharps') == 'SLIDE' and self.sharp_verts:
            filtered = [ bmv for bmv in filtered if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.sharp)  for bme in bmv.link_edges) > 2 ]
        if self.mask_opt('creases') == 'SLIDE' and self.crease_verts:
            filtered = [ bmv for bmv in filtered if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.crease) for bme in bmv.link_edges) > 2 ]
        if self.mask_opt('angle') == 'SLIDE' and self.angle_verts:
            filtered = [ bmv for bmv in filtered if not sum(bme in self.angle_edges for bme in bmv.link_edges) > 2 ]

        return set(filtered)

    def snap_proximity_world(self, bmv):
        return get_bmv_avg_edge_len(bmv) * self.scale_avg * self.source_sharp_proximity

    def corner_snap_threshold_world(self, bmv, factor):
        # Corner tests scale the raw avg edge length (no proximity factor), unlike Tweak.
        return get_bmv_avg_edge_len(bmv) * self.scale_avg * factor

    def feature_run_extra_margin(self):
        return self.loop_run_margin

    def guide_seed_edges_by_run(self, exclude_runs):
        run_edges: 'dict[int, list]' = {}
        for bme in self.guide_candidate_edges:
            # Election still requires the normal-checked near set while seeds don't.
            # A loop must never be elected onto a feature on the far side of a thin source.
            if bme.verts[0] not in self.verts_near_source_edge: continue
            if bme.verts[1] not in self.verts_near_source_edge: continue
            r0 = self.vert_feature_run.get(bme.verts[0])
            if r0 is None or r0 in exclude_runs: continue
            if self.vert_feature_run.get(bme.verts[1]) != r0: continue
            run_edges.setdefault(r0, []).append(bme)
        return run_edges

    def guide_anchor_co_local(self):
        return (self.matrix_world_inv @ Vector((*self.guide_anchor_world, 1.0))).xyz

    def seed_still_valid(self, gv0, gv1, members):
        if not super().seed_still_valid(gv0, gv1, members):
            return False
        # The seed edge itself must still exist between the two verts.
        return any(e.other_vert(gv0) is gv1 for e in gv0.link_edges)

    def update(self, context:Context, event:Event, *, debug_print:bool=False): #MARK: Update
        match event.type:
            case 'MOUSEMOVE':
                self.pressure = getattr(event, 'pressure', 1.0)
                self.mouse = mouse_from_event(event)
            case 'TIMER':
                mouse = mouse_from_event(event)
                if mouse: self.mouse = mouse
            case 'INBETWEEN_MOUSEMOVE':
                # explicitly ignoring!!
                return
            case _:
                return

        # Throttle to 120 Hz so we don't raycast_valid_sources hundreds of times per second
        # self.mouse is already updated above so we always act on the latest position
        cur_time = time.time()
        time_delta = cur_time - self._time
        if time_delta < 1.0 / 120: return
        time_delta = clamp(time_delta, 0.0, 0.1)
        self._time = cur_time
        self.verts_accel.rebuild(context)

        hit = raycast_valid_sources(context, self.mouse, respect_clip_planes=True)
        if not hit: return
        co_world : Vector = hit['co_world']  # pyright: ignore[reportAssignmentType]
        brush_center_world = Vector(co_world.xyz)  # save before inner loop overwrites co_world

        M = self.matrix_world
        radius3D = self.brush.get_scaled_radius()

        # # Debug: select all verts under brush
        # bmops.deselect_all(self.bm)
        # for bmelem in nearest_bmverts:
        #     bmops.select(self.bm, bmelem)
        # bmops.flush_selection(self.bm, self.em)

        if not self.verts_filtered: return
        verts = self.verts_accel.get(co_world, radius3D)
        if self.exclude_opt('occluded'):
            verts = { bmv for bmv in verts if not self.is_bmvert_hidden(bmv) }
        if not verts: return
        vert_strength = { bmv: self.brush.get_strength_Point(M @ bmv.co) for bmv in verts }

        self.relax_verts(
            context, verts, vert_strength,
            brush_center_world = brush_center_world,
            radius3D           = radius3D,
            pressure           = self.pressure,
            global_strength    = self.brush.strength,
            time_delta         = time_delta,
            debug_print        = debug_print,
        )

    def relax_verts(self, context:Context, verts:'set[BMVert]', vert_strength:'dict[BMVert, float]', *,
                    iterations:'int|None'=None,
                    brush_center_world:'Vector|None'=None,
                    radius3D:'float|None'=None,
                    pressure:float=1.0,
                    global_strength:float=1.0,
                    time_delta:float=1.0/60,
                    debug_print:bool=False,
                    snap_bvh:'BVHTree|None'=None,
                    snap_unforced_verts:bool=False): #MARK: Relax core
        # Brush-only parameters have fallbacks so non-brush callers can omit them
        relax = self.relax
        M = self.matrix_world
        Mi = self.matrix_world_inv

        # debugging options
        opt_draw_all         = False
        opt_draw_net         = False

        edges = { bme for bmv in verts for bme in bmv.link_edges }
        if not edges: return
        faces = { bmf for bmv in verts for bmf in bmv.link_faces }

        # Keep focused on one mesh island at a time to prevent spillover
        is_brush_call = brush_center_world is not None
        isolate_island = is_brush_call and not self.include_opt('all_islands')
        vert_island = {}   # bmv -> island root
        face_island = {}   # bmf -> island root
        if relax.algorithm_average_edge_lengths or relax.algorithm_equalize_faces or isolate_island:
            parent = {}
            def _find(v):
                root = v
                while parent[root] != root:
                    root = parent[root]
                while parent[v] != root:  # path compression
                    parent[v], v = root, parent[v]
                return root
            for bme in edges:
                v0, v1 = bme.verts
                if v0 not in parent: parent[v0] = v0
                if v1 not in parent: parent[v1] = v1
                r0, r1 = _find(v0), _find(v1)
                if r0 != r1: parent[r0] = r1
            vert_island = { v: _find(v) for v in parent }

            if isolate_island:
                # relax only the island under the brush center
                nearest = min(verts, key=lambda v: (M @ v.co - brush_center_world).length_squared)
                active_island = vert_island.get(nearest)
                if active_island is not None:
                    verts = { v for v in verts if vert_island.get(v) == active_island }
                    vert_strength = { v: s for v, s in vert_strength.items() if v in verts }
                    edges = { bme for bmv in verts for bme in bmv.link_edges }
                    faces = { bmf for bmv in verts for bmf in bmv.link_faces }

            if relax.algorithm_equalize_faces:
                for bmf in faces:
                    face_island[bmf] = next(
                        (vert_island[v] for v in bmf.verts if v in vert_island), None
                    )

        # Boundary vert references must be cleared because `verts` changes as the brush moves, invalidating prior boundary traces.
        self.loop_interp_cache.clear()

        # Non-brush callers fall back to the vert set's own bounds
        # so the distance caps and snap falloff still have meaningful values.
        if brush_center_world is None or radius3D is None:
            world_cos = [M @ bmv.co for bmv in verts]
            center = sum(world_cos, Vector((0.0, 0.0, 0.0))) / len(world_cos)
            if brush_center_world is None: brush_center_world = center
            if radius3D is None:           radius3D = max((wc - center).length for wc in world_cos) or 1.0

        strength = pressure

        # capture all verts involved in relaxing
        chk_verts = set(verts)
        chk_verts.update({ bmv for bme in edges for bmv in bme.verts })
        chk_verts.update({ bmv for bmf in faces for bmv in bmf.verts })
        # chk_edges = { bme for bmv in chk_verts for bme in bmv.link_edges }
        chk_faces = { bmf for bmv in chk_verts for bmf in bmv.link_faces } if relax.algorithm_correct_flipped_faces else set()

        enabled_algorithms_count = (
            int(relax.algorithm_laplacian) +
            int(relax.algorithm_average_edge_lengths) +
            int(relax.algorithm_straighten_edges) +
            int(relax.algorithm_equalize_faces) * 2 +
            int(getattr(relax, 'algorithm_interpolate_loops', False))
        )
        weight_mult = (1.0 / enabled_algorithms_count) if enabled_algorithms_count else 0.0
        loops_strength  = getattr(relax, 'source_edge_guide_loops', getattr(context.scene.retopoflow.snapping, 'source_edge_guide_loops', 0.5))

        self.loops_strength = loops_strength
        self.loop_run_margin = (radius3D or 0.0) * 2.0
        self.guide_candidate_edges = edges
        self.guide_anchor_world = brush_center_world
        self.corner_owner_factor = self.source_sharp_proximity * getattr(relax, 'algorithm_source_corner_proximity', 2.0)

        self.verts_near_source_edge = {}
        self.snapped_verts = set()

        if opt_draw_all or opt_draw_net:
            self.draw_vectors_positive.clear()
            self.draw_vectors_negative.clear()
            self.draw_vectors_net.clear()

        displace = {}

        def reset_forces():
            nonlocal displace
            displace.clear()

        def add_force(bmv, f, wrt=None, sign=0, mult=0):
            nonlocal displace
            if bmv not in vert_strength: return  # vert_strength has exactly the keys of `verts`
            if bmv not in displace: displace[bmv] = Vector((0,0,0))
            displace[bmv] += f * (vert_strength[bmv] * weight_mult)
            if opt_draw_all and wrt:
                if sign > 0:
                    self.draw_vectors_positive.append((wrt, f.xyz * mult * vert_strength[bmv]))
                elif sign < 0:
                    self.draw_vectors_negative.append((wrt, f.xyz * mult * vert_strength[bmv]))

        def edge_constrained_neighbors(bmv):
            ''' Neighbors riding the same feature run as bmv. '''
            bmv_run = self.vert_feature_run.get(bmv)
            return [
                other for bme in bmv.link_edges
                if (other := bme.other_vert(bmv)) in self.verts_near_source_edge
                and (bmv_run is None or self.vert_feature_run.get(other) == bmv_run)
            ]

        def get_edge_proj_dir(bmv):
            ''' The along-source-edge direction for a snapped vert, or None. '''
            if not (self.verts_near_source_edge and bmv in self.verts_near_source_edge):
                return None
            edge_nbrs = edge_constrained_neighbors(bmv)
            if len(edge_nbrs) >= 2:
                v = edge_nbrs[-1].co - edge_nbrs[0].co
                if v.length > 1e-8:
                    return v.normalized()
            if edge_nbrs:
                v = edge_nbrs[0].co - bmv.co
                if v.length > 1e-8:
                    return v.normalized()
            return None

        def source_corner_of_vert(bmv, margin):
            return self.source_corner_of_vert(bmv, self.corner_snap_threshold_world(bmv, margin))

        def get_face_topology(bmf):
            cached = self.face_topology_cache.get(bmf)
            if cached is None:
                cached = (tuple(bmf.verts), tuple(bmf.edges))
                self.face_topology_cache[bmf] = cached
            return cached

        #MARK: Sim algos

        def laplacian_smooth(bmv, laplacian_cache, shape_preservation=0):
            ''' Push verts towards the average of their neighbors '''
            if bmv in laplacian_cache:
                laplacian_data = laplacian_cache[bmv]
                if laplacian_data is None: return
            else:
                link_edges = bmv.link_edges
                edge_count = len(link_edges)
                if (
                    edge_count == 2 or
                    edge_count == 4 and len(bmv.link_faces) == 3
                ):
                    laplacian_cache[bmv] = None
                    return
                is_boundary = bmv.is_boundary
                if is_boundary:
                    if edge_count > 4:
                        laplacian_cache[bmv] = None
                        return
                    neighbors = tuple(bme.other_vert(bmv) for bme in link_edges if bme.is_boundary)
                else:
                    neighbors = tuple(bme.other_vert(bmv) for bme in link_edges)
                if not neighbors:
                    laplacian_cache[bmv] = None
                    return
                laplacian_data = (neighbors, is_boundary, 1.0 / len(neighbors))
                laplacian_cache[bmv] = laplacian_data
            neighbors, is_boundary, nb_reciprocal = laplacian_data

            edge_proj_dir = None # slide snapped vertices along source edges
            if self.verts_near_source_edge and bmv in self.verts_near_source_edge:
                # A perpendicular neighbor on its own parallel feature must not contribute to this vert's along-edge direction.
                bmv_run = self.vert_feature_run.get(bmv)
                edge_nbrs = [
                    nb for nb in neighbors
                    if nb in self.verts_near_source_edge
                    and (bmv_run is None or self.vert_feature_run.get(nb) == bmv_run)
                ]
                if len(edge_nbrs) >= 2:
                    v = edge_nbrs[-1].co - edge_nbrs[0].co
                    if v.length > 0:
                        edge_proj_dir = v.normalized()
                elif len(edge_nbrs) == 1:
                    v = edge_nbrs[0].co - bmv.co
                    to_edge = self.verts_near_source_edge[bmv]
                    to_edge_len = to_edge.length
                    if to_edge_len > 1e-8:
                        # bmv is not yet on the edge so make the projection is purely tangential
                        to_edge_dir = to_edge / to_edge_len
                        v_tangent = v - to_edge_dir * v.dot(to_edge_dir)
                        if v_tangent.length > 1e-8:
                            edge_proj_dir = v_tangent.normalized()
                    elif v.length > 1e-8:
                        # bmv is already on the edge and direction to neighbour is along it
                        edge_proj_dir = v.normalized()
                else:
                    # no edge-constrained neighbors found
                    if is_boundary:
                        all_edge_nbrs = edge_constrained_neighbors(bmv)
                        if all_edge_nbrs:
                            v = all_edge_nbrs[0].co - bmv.co
                            if v.length > 1e-8:
                                edge_proj_dir = v.normalized()
                    if edge_proj_dir is None:
                        return

            sum_x = sum_y = sum_z = 0.0
            for nb in neighbors:
                nb_co = nb.co
                sum_x += nb_co[0]
                sum_y += nb_co[1]
                sum_z += nb_co[2]
            average_co = Vector((sum_x * nb_reciprocal, sum_y * nb_reciprocal, sum_z * nb_reciprocal))

            bmv_co = bmv.co
            if shape_preservation:
                # Shape Preservation doesn't seem to work well with how the brush iterates
                prev_position = self.prev_position
                prev_co = prev_position.get(bmv)
                if prev_co is None:
                    prev_co = Vector(bmv_co)
                    prev_position[bmv] = prev_co
                weighted_o = prev_co * shape_preservation
                weighted_q = bmv_co * (1.0 - shape_preservation)
                displacement = average_co - (weighted_o + weighted_q)
            else:
                displacement = average_co - bmv_co
            if is_boundary: displacement *= 0.5

            if edge_proj_dir is not None:
                # Project edge constrained verts onto the edge
                displacement = edge_proj_dir * displacement.dot(edge_proj_dir)

            add_force(bmv, displacement * 0.1, mult=40)

        def straighten_edges(bmv, straighten_cache):
            ''' push verts to straighten edges (still WiP!) '''
            if self.verts_near_source_edge and bmv in self.verts_near_source_edge:
                # Skip to avoid bad pulling at constrained edges
                return

            if bmv in straighten_cache:
                straighten_data = straighten_cache[bmv]
                if straighten_data is None: return
            else:
                link_edges = bmv.link_edges
                edge_count = len(link_edges)
                face_count = len(bmv.link_faces)
                if edge_count == 2 or (edge_count == 4 and face_count == 3):
                    straighten_cache[bmv] = None
                    return
                neighbors = tuple(bme.other_vert(bmv) for bme in link_edges)
                if not neighbors:
                    straighten_cache[bmv] = None
                    return
                boundary_neighbors = tuple(
                    bme.other_vert(bmv)
                    for bme in link_edges
                    if is_bmedge_boundary(bme, self.mirror, self.mirror_threshold, self.mirror_clip)
                )
                is_boundary = is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip)
                straighten_data = (is_boundary, neighbors, boundary_neighbors, edge_count)
                straighten_cache[bmv] = straighten_data
            is_boundary, neighbors, boundary_neighbors, edge_count = straighten_data

            if is_boundary and self.mask_opt('boundary') == 'EXCLUDE': return
            if is_boundary:
                if edge_count > 4: return
                neighbors = boundary_neighbors
            if not neighbors: return

            if relax.algorithm_laplacian or relax.algorithm_average_edge_lengths:
                # Faster method when verts are being spread out anyway
                sum_x = sum_y = sum_z = 0.0
                for nb in neighbors:
                    nb_co = nb.co
                    sum_x += nb_co[0]
                    sum_y += nb_co[1]
                    sum_z += nb_co[2]
                reciprocal = 1.0 / len(neighbors)
                center = Vector((sum_x * reciprocal, sum_y * reciprocal, sum_z * reciprocal))
                force_mult = 0.5
            elif is_boundary:
                # min_length pulls toward the shorter edge end (corner-slide) so use centroid instead
                center = Point.average([nb.co for nb in neighbors])
                force_mult = 0.5
            else:
                # Slower method that does not spread out verts
                if edge_count > 4: return
                min_length = min((nb.co - bmv.co).length for nb in neighbors)
                directions = [(nb.co - bmv.co).normalized() for nb in neighbors]
                center = Point.average([bmv.co + (d * min_length) for d in directions])
                force_mult = 1
            vec = (center - bmv.co) * force_mult
            add_force(bmv, vec, bmv.co, 1, 40)

        def straighten_loops(bmv, straighten_loops_cache):
            ''' push quad verts towards the line between opposing neighbords '''
            if self.verts_near_source_edge and bmv in self.verts_near_source_edge:
                # Skip to preserve verts constrained to source edges
                return

            if bmv in straighten_loops_cache:
                loops = straighten_loops_cache[bmv]
            else:
                link_edges = list(bmv.link_edges)
                if len(link_edges) != 4 or len(bmv.link_faces) != 4:
                    loops = None
                else:
                    loops = get_bmv_loop_pairs(bmv)
                straighten_loops_cache[bmv] = loops
            if not loops: return

            if straighten_loops_cache.get(bmv) is None:
                # handles poles, boundaries, and other topology
                straighten_edges(bmv, self.straighten_cache)
                return

            co = bmv.co
            normal = bmv.normal
            for (start_pt, end_pt) in loops:
                direction  = end_pt.co - start_pt.co
                len_sq = direction.dot(direction)
                if len_sq < 1e-12: continue
                t = (co - start_pt.co).dot(direction) / len_sq
                closest = start_pt.co + direction * t
                force = (closest - co) * 0.5
                # Cancel out force in the vert's normal direction to avoid shrinking curved loops
                force -= normal * force.dot(normal)
                add_force(bmv, force, co, 1, 40)

        def walk_loop_to_selection_boundary(bmv, first_step, max_depth=200):
            ''' Walk the loop from origin through first_step to the first
            unselected vert in that direction. Returns (depth, first_unselected_vert):
              depth=1, first_step  — first_step is already outside verts
              depth=k, vert        — vert is k hops away and unselected
            Returns None for poles, mesh boundaries, or closed loops that never exit the selection. '''
            if first_step not in verts:
                # first_step is unselected, it is the immediate anchor
                return 1, first_step
            prev, cur = bmv, first_step
            depth = 1
            seen = {bmv}
            while True:
                seen.add(cur)
                nxt = get_bmv_next_loop_vert(prev, cur)
                if nxt is None:
                    return None              # mesh boundary or pole
                if nxt in seen:
                    return None              # closed loop entirely inside selection
                if nxt not in verts:
                    return depth + 1, nxt   # nxt is the first unselected vert
                if depth >= max_depth:
                    return None              # depth guard
                prev, cur = cur, nxt
                depth += 1

        def average_edge_length(bme, avg_edge_len):
            ''' Expand and contract edges closer to average edge length '''
            bmv0, bmv1 = bme.verts
            vec = bme_vector(bme)
            diff = avg_edge_len - vec.length
            if abs(diff) < 1e-12: return
            edge_midpoint = bme_midpoint(bme) if opt_draw_all else None  # only needed for debug draw
            f = vec.normalized() * diff / 25
            f0 = -f
            if edge_proj_dir := get_edge_proj_dir(bmv0):
                f0 = edge_proj_dir * f0.dot(edge_proj_dir)
            add_force(bmv0, f0, edge_midpoint, diff, 40)
            f1 = f
            if edge_proj_dir := get_edge_proj_dir(bmv1):
                f1 = edge_proj_dir * f1.dot(edge_proj_dir)
            add_force(bmv1, f1, edge_midpoint, diff, 40)

        def average_edge_length_springs(bmv, avg_edge_len):
            # Intended to help edges not collapse around holes but
            # doesn't seem to make a significant difference and has
            # high performance cost
            if bmv not in verts: return
            spring_force = Vector((0,0,0))
            for bme in bmv.link_edges:
                edge_len = bme.calc_length()
                edge_vector = bmv.co - bme.other_vert(bmv).co
                if not edge_len: continue
                # positive compression means the vert should move away from the opposite vert
                # negative means it should be pulled towards it, like a spring
                compression = (avg_edge_len - edge_len) / avg_edge_len
                if compression == 0: continue
                direction = edge_vector.normalized()
                magnitude = compression * abs(avg_edge_len - edge_len) * strength
                spring_force += direction * magnitude
            if spring_force.length:
                add_force(bmv, spring_force, bmv.co, 1, 40)

        def average_face_radius(bmf, avg_vert_area_sqrt, center):
            ''' push verts toward average dist from verts to face center '''
            face_verts, face_edges = get_face_topology(bmf)
            rels = [bmv.co - center for bmv in face_verts]
            avg_rel_len = sum(rel.length for rel in rels) / len(face_verts)
            for rel, bmv in zip(rels, face_verts):
                rel_len = rel.length
                diff = avg_rel_len - rel_len
                if diff > 0: diff /= 10 # Reduces shrinking
                f = rel.normalized() * (diff / avg_rel_len) * avg_vert_area_sqrt
                add_force(bmv, f, center, (avg_rel_len - rel_len), 40)

        def average_face_sides(bmf, avg_vert_area_sqrt):
            ''' push verts toward equal edge lengths '''
            face_verts, face_edges = get_face_topology(bmf)
            avg_face_edge_len = sum(bme_length(bme) for bme in face_edges) / len(face_verts)
            for bme in face_edges:
                bmv0, bmv1 = bme.verts
                vec = bme_vector(bme)
                edge_len = vec.length
                edge_diff = (avg_face_edge_len - edge_len)
                if abs(edge_diff) < 1e-12: continue
                edge_midpoint = bme_midpoint(bme)
                f = vec.normalized() * (edge_diff / avg_face_edge_len) * avg_vert_area_sqrt
                add_force(bmv0, f * -0.5, edge_midpoint, edge_diff, 40)
                add_force(bmv1, f * 0.5, edge_midpoint, edge_diff, 40)

        def average_face_angles(bmf, avg_vert_area_sqrt):
            ''' push verts toward equal spread '''
            face_verts, face_edges = get_face_topology(bmf)
            bmf_z = bmf.normal.normalized()
            if abs(bmf_z.dot(self.forward)) < 0.95:
                bmf_y = bmf_z.cross(self.forward).normalized()
                bmf_x = bmf_y.cross(bmf_z).normalized()
            else:
                bmf_x = self.up.cross(bmf_z).normalized()
                bmf_y = bmf_z.cross(bmf_x).normalized()
            vert_count = len(face_verts)
            sum_of_interior_angles = math.pi * (vert_count - 2)
            angle_target = sum_of_interior_angles / vert_count
            for i1 in range(vert_count):
                i0 = (i1 + vert_count - 1) % vert_count
                i2 = (i1 + 1) % vert_count
                bmv0, bmv1, bmv2 = face_verts[i0], face_verts[i1], face_verts[i2]
                v10, v12 = bmv0.co - bmv1.co, bmv2.co - bmv1.co
                d10, d12 = v10.normalized(), v12.normalized()
                d10_2 = Vector((bmf_x.dot(d10), bmf_y.dot(d10))).normalized()
                d12_2 = Vector((bmf_x.dot(d12), bmf_y.dot(d12))).normalized()
                try:
                    angle = d10_2.angle_signed(d12_2)
                    angle_diff = angle_target - angle
                    mag = angle_diff * avg_vert_area_sqrt / vert_count
                    add_force(bmv0, d10.cross(bmf_z).normalized() * -mag, bmv0.co, angle_diff, 40)
                    add_force(bmv2, d12.cross(bmf_z).normalized() * mag, bmv1.co, angle_diff, 40)
                except Exception:
                    # Exception is thrown if d10_2 or d12_2 are 0-length
                    pass

        def average_face_areas(bmf, avg_vert_area, center):
            ''' scale faces towards the average '''
            face_verts, face_edges = get_face_topology(bmf)
            if avg_vert_area < 1e-20: return
            diff = ((bmf.calc_area() / len(face_verts)) - avg_vert_area) / avg_vert_area
            for bmv in face_verts:
                if bmv.is_boundary and len(bmv.link_edges) == 3:
                    other_boundary_verts = [e.other_vert(bmv) for e in bmv.link_edges if e.is_boundary and e in face_edges]
                    if other_boundary_verts:
                        bmv_center = Point.average([bmv.co, other_boundary_verts[0].co])
                    else:
                        bmv_center = center
                else:
                    bmv_center = center
                vec = (bmv_center - bmv.co) * diff * 0.25
                if edge_proj_dir := get_edge_proj_dir(bmv):
                    vec = edge_proj_dir * vec.dot(edge_proj_dir)
                add_force(bmv, vec, bmv_center, 1, 40)

        def average_face_shape(bmf, avg_vert_area_sqrt, center):
            ''' push verts toward their target positions on a regular polygon '''
            face_verts, face_edges = get_face_topology(bmf)
            vert_count = len(face_verts)
            bmf_z = bmf.normal.normalized()
            ref = Vector((0, 0, 1)) if abs(bmf_z.z) < 0.9 else Vector((1, 0, 0))
            bmf_x = ref.cross(bmf_z).normalized()
            bmf_y = bmf_z.cross(bmf_x)
            if vert_count == 3:
                cos_s, sin_s = -0.5, 0.8660254037844387 # 2π/3, avoids trig for common cases
            elif vert_count == 4:
                cos_s, sin_s = 0.0, 1.0 # π/2
            elif vert_count == 5:
                cos_s, sin_s = 0.30901699437494742, 0.9510565162951535 # 2π/5
            else:
                spacing = 2 * math.pi / vert_count
                cos_s, sin_s = math.cos(spacing), math.sin(spacing)
            rels = []
            avg_radius = 0.0
            sum_z = complex(0.0, 0.0)
            conj_k = complex(1.0, 0.0)
            conj_step = complex(cos_s, -sin_s)
            for bmv in face_verts:
                rel = bmv.co - center
                rels.append(rel)
                avg_radius += rel.length
                x2d, y2d = bmf_x.dot(rel), bmf_y.dot(rel)
                r2d = math.sqrt(x2d * x2d + y2d * y2d)
                if r2d > 1e-8:
                    sum_z += complex(x2d / r2d, y2d / r2d) * conj_k
                conj_k *= conj_step
            avg_radius /= vert_count
            if avg_radius < 1e-8: return
            phase = math.atan2(sum_z.imag, sum_z.real)
            scale = avg_vert_area_sqrt / avg_radius
            bmf_x_s = bmf_x * avg_vert_area_sqrt
            bmf_y_s = bmf_y * avg_vert_area_sqrt
            current  = complex(math.cos(phase), math.sin(phase))
            step = complex(cos_s, sin_s)
            for bmv, rel in zip(face_verts, rels):
                f = current.real * bmf_x_s + current.imag * bmf_y_s - rel * scale
                if edge_proj_dir := get_edge_proj_dir(bmv):
                    f = edge_proj_dir * f.dot(edge_proj_dir)
                add_force(bmv, f, center, 1, 40)
                current *= step

        def correct_flipped_faces():
            ''' push verts if neighboring faces seem flipped (still WiP!) '''
            bmf_flipped = { bmf for bmf in chk_faces if bmf_is_flipped(bmf) }
            for bmf in bmf_flipped:
                # find a non-flipped neighboring face
                for bme in bmf.edges:
                    bmfs = { f for f in bme.link_faces if f not in bmf_flipped }
                    if len(bmfs) != 1: continue
                    bmf_other = next(iter(bmfs))
                    if bmf_other not in chk_faces: continue
                    # pull edge toward bmf_other center
                    vec = bmf_midpoint(bmf_other) - bme_midpoint(bme)
                    bmv0,bmv1 = bme.verts
                    bmf_center = bmf_midpoint(bmf) if opt_draw_all else None  # only needed for debug draw
                    add_force(bmv0, vec * 5, bmf_center, 1, 40)
                    add_force(bmv1, vec * 5, bmf_center, 1, 40)

        def pull_promoted_push_demoted():
            pull_strength  = loops_strength * global_strength
            corner_prox    = getattr(relax, 'algorithm_source_corner_proximity', 2.0)

            # Corners already owned by a snapped vert are considered occupied.
            occupied_corners = set()
            for _sv in self.verts_near_source_edge:
                if cr := source_corner_of_vert(_sv, self.source_sharp_proximity * corner_prox):
                    occupied_corners.add(cr[1])

            for bmv in verts:
                if bmv in self.promoted_loop_verts:
                    bmv_world = local_to_world(bmv.co, M)
                    # Prefer an unoccupied corner within range.
                    target_local = None
                    if cr := source_corner_of_vert(bmv, self.source_sharp_proximity * corner_prox):
                        co_corner, corner_idx, _ = cr
                        if corner_idx not in occupied_corners:
                            target_local = Mi @ Vector(co_corner)
                    # Fall back to the nearest point on the vert's own feature run.
                    if target_local is None:
                        closest_result = self.closest_on_own_run(bmv, bmv_world)
                        if not closest_result: continue
                        target_local = Mi @ Vector(closest_result[0])
                    to_target = target_local - bmv.co
                    dist = to_target.length
                    if dist < 1e-8:
                        continue
                    add_force(bmv, to_target * pull_strength)

                elif bmv in self.demoted_verts:
                    # Only push demoted verts when they are close enough to actually intrude on the source edge.
                    dist_threshold = get_bmv_avg_edge_len(bmv) * self.source_sharp_proximity * 1.5
                    runs = self.demoted_by_runs.get(bmv)
                    if runs:
                        # Push away from every demoting run.
                        # A vert between two promoted rails settles at the midline instead of bouncing off the nearest feature.
                        bmv_world = local_to_world(bmv.co, M)
                        total = Vector((0.0, 0.0, 0.0))
                        for run_id in runs:
                            segs = self.run_segments.get(run_id)
                            if not segs: continue
                            result = self.source_edge_accel.closest_point_in_segments(bmv_world, segs)
                            if not result: continue
                            to_edge = (Mi @ Vector(result[0])) - bmv.co
                            if 1e-8 < to_edge.length <= dist_threshold:
                                total -= to_edge
                        if total.length > 1e-9:
                            add_force(bmv, total * loops_strength)
                        continue
                    closest_p = self.source_edge_accel.closest_point_in_threshold(bmv.co, M, Mi, dist_threshold)
                    if not closest_p:
                        continue
                    to_edge = closest_p - bmv.co
                    if to_edge.length < 1e-8:
                        continue
                    add_force(bmv, to_edge * loops_strength * -1)

        def update_source_context():
            ''' Recompute which verts lie near/on the source edge and re-derive the promoted/demoted guide loops.
            This is position-dependent but only needs to run once per step and not once per RK4 sub-evaluation '''
            if self.source_edge_accel:
                self.verts_near_source_edge = self.collect_verts_near_source_edge(chk_verts)
            else:
                self.verts_near_source_edge = {}
            self.refresh_feature_runs()
            self.demoted_by_runs = {}

            if loops_strength == 0:
                self.clear_guide_state()
            elif is_brush_call:
                self.update_source_context_brush(chk_verts)
            else:
                # Not a brush so recompute every step. One elected loop per local feature run.
                self.promoted_loop_verts = set()
                self.demoted_verts = set()
                if self.verts_near_source_edge:
                    self.seed_all_guide_loops()

            self.apply_corner_owner_demotion()

        def build_loop_interpolation_cache(bmv, loop_cache):
            ''' The cache stores (P_a, n_a, t, P_b, n_b) tuples with positions
            and normals frozen at build time so the post-loop SLERP always uses
            the original anchor geometry, not positions that may have been
            displaced by subsequent Laplacian steps. '''
            if bmv not in loop_cache:
                lps = get_bmv_loop_pairs(bmv)
                if not lps:
                    loop_cache[bmv] = None
                else:
                    axes = []
                    for nb_a, nb_b in lps:
                        result_a = walk_loop_to_selection_boundary(bmv, nb_a)
                        if result_a is None:
                            continue
                        result_b = walk_loop_to_selection_boundary(bmv, nb_b)
                        if result_b is None:
                            continue
                        depth_a, anchor_a = result_a
                        depth_b, anchor_b = result_b
                        # t = 0 at anchor_a, t = 1 at anchor_b
                        # span = depth_a + depth_b (hops across the full selection width)
                        t = depth_a / (depth_a + depth_b)
                        # Capture position and normal so compute_loop_arc_target
                        # always reconstructs from the correct geometry.
                        axes.append((Vector(anchor_a.co), bmv_compute_normal(anchor_a),
                                     t,
                                     Vector(anchor_b.co), bmv_compute_normal(anchor_b)))
                    loop_cache[bmv] = axes if axes else None

        def relax_3d():
            #MARK: Add forces
            reset_forces()
            if relax.algorithm_straighten_edges or relax.algorithm_laplacian:
                for bmv in verts:
                    if relax.algorithm_laplacian:
                        laplacian_smooth(bmv, self.laplacian_cache)
                    if relax.algorithm_straighten_edges:
                        straighten_loops(bmv, self.straighten_loops_cache)
            if getattr(relax, 'algorithm_interpolate_loops', False):
                for bmv in verts:
                    build_loop_interpolation_cache(bmv, self.loop_interp_cache)
            if relax.algorithm_average_edge_lengths:
                # Average edge length per island so disconnected areas of differing scale don't distort each other.
                len_sums, len_counts = {}, {}
                for bme in edges:
                    isl = vert_island[bme.verts[0]]
                    len_sums[isl]   = len_sums.get(isl, 0.0) + bme_length(bme)
                    len_counts[isl] = len_counts.get(isl, 0) + 1
                island_avg_len = { isl: len_sums[isl] / len_counts[isl] for isl in len_sums }
                for bme in edges:
                    average_edge_length(bme, island_avg_len[vert_island[bme.verts[0]]])
            if relax.algorithm_equalize_faces:
                # Average face area per island for the same reason as edges above.
                area_sums, area_counts = {}, {}
                for bmf in faces:
                    isl = face_island[bmf]
                    area_sums[isl]   = area_sums.get(isl, 0.0) + bmf.calc_area() / len(bmf.verts)
                    area_counts[isl] = area_counts.get(isl, 0) + 1
                island_avg_area = { isl: area_sums[isl] / area_counts[isl] for isl in area_sums }
                for bmf in faces:
                    avg_vert_area = island_avg_area[face_island[bmf]]
                    avg_vert_area_sqrt = math.sqrt(avg_vert_area)
                    face_center = bmf_midpoint(bmf)
                    average_face_areas(bmf, avg_vert_area, face_center)
                    average_face_shape(bmf, avg_vert_area_sqrt, face_center)
            if relax.algorithm_correct_flipped_faces:
                correct_flipped_faces()
            if self.source_edge_accel and self.promoted_loop_verts:
                pull_promoted_push_demoted()

            # Constrained verts may have no forces
            # so assign a 0 vector so they still get updated for snapping
            if self.verts_near_source_edge:
                for bmv in verts:
                    if bmv in self.verts_near_source_edge and bmv not in displace:
                        displace[bmv] = Vector((0.0, 0.0, 0.0))

        def compute_loop_arc_target(bmv, axes):
            ''' Return the averaged arc target on the curved surface
            from a bmv and a list of (P_a, n_a, t, P_b, n_b) tuples whose
            positions and normals were frozen at cache-build time. '''
            ideals = []
            P_cur = Vector(bmv.co)

            for P_a, n_a, t, P_b, n_b in axes:

                # Reconstruct sphere from boundary vert normals
                n_diff    = n_b - n_a
                n_diff_sq = n_diff.dot(n_diff)
                if n_diff_sq < 1e-10:
                    # Normals nearly parallel — flat surface, lerp positions.
                    ideals.append(P_a.lerp(P_b, t))
                    continue

                R = (P_b - P_a).dot(n_diff) / n_diff_sq
                if abs(R) < 1e-10:
                    ideals.append(P_a.lerp(P_b, t))
                    continue
                C = P_a - n_a * R   # sphere centre

                # Find the circle's plane axis using bmv as third point
                chord = P_b - P_a
                arm   = P_cur - P_a
                k     = chord.cross(arm)
                k_len = k.length
                if k_len < 1e-8:
                    # bmv is collinear with anchors so fall back to the 3D SLERP between the normals
                    dot       = max(-1.0, min(1.0, n_a.dot(n_b)))
                    omega     = acos(dot)
                    sin_omega = math.sin(omega)
                    if sin_omega < 1e-6:
                        n_t = n_a.lerp(n_b, t).normalized()
                    else:
                        n_t = (math.sin((1.0 - t) * omega) / sin_omega) * n_a \
                            + (math.sin(       t  * omega) / sin_omega) * n_b
                    ideals.append(C + n_t * R)
                    continue
                k = k / k_len

                # Small-circle geometry
                # Ring center: foot of perpendicular from sphere center onto the plane
                C_ring = C + (P_a - C).dot(k) * k

                v_a = P_a - C_ring
                v_b = P_b - C_ring
                r_a = v_a.length
                if r_a < 1e-8:
                    ideals.append(P_a.lerp(P_b, t))
                    continue

                # Project v_b into the ring plane, strip the k component
                v_b_in_plane = v_b - v_b.dot(k) * k
                r_b = v_b_in_plane.length
                if r_b < 1e-8:
                    ideals.append(P_a.lerp(P_b, t))
                    continue

                e_a = v_a / r_a
                e_b = v_b_in_plane / r_b

                # 2D SLERP in the ring plane
                cos_theta = max(-1.0, min(1.0, e_a.dot(e_b)))
                theta     = acos(cos_theta)
                sin_theta = math.sin(theta)
                if sin_theta < 1e-6:
                    e_t = e_a.lerp(e_b, t).normalized() if cos_theta > 0 else e_a
                else:
                    e_t = (math.sin((1.0 - t) * theta) / sin_theta) * e_a \
                        + (math.sin(       t  * theta) / sin_theta) * e_b

                r_ring = (r_a + r_b) / 2.0
                ideals.append(C_ring + e_t * r_ring)

            if not ideals:
                return None
            return sum(ideals, Vector((0.0, 0.0, 0.0))) / len(ideals)

        #MARK: Smoothing
        strength_base = 20.0 * self.scale_avg * global_strength / time_delta
        if relax.algorithm_method == 'AUTO':
            vert_count = len(verts)
            if relax.algorithm_equalize_faces: vert_count *= 2 # It's pretty slow
            if self.mask_opt('boundary') == 'SLIDE': vert_count *= 2 # Sliding is slow
            if self.mask_opt('creases') == 'SLIDE': vert_count *= 2
            if self.mask_opt('sharps') == 'SLIDE': vert_count *= 2
            if self.mask_opt('seams') == 'SLIDE': vert_count *= 2
            if getattr(relax, 'algorithm_slide_edges', False): vert_count *= 2
            steps = min(10, max(1, int(100 / vert_count)))
        elif relax.algorithm_method == 'RK4':
            steps = 1
        else:
            steps = relax.algorithm_iterations

        # Lets non-brush callers ask for an exact number of integration steps
        if iterations is not None:
            steps = iterations

        for i in range(steps):
            update_source_context()
            if relax.algorithm_method == 'RK4':
                original = { bmv: Vector(bmv.co) for bmv in verts }

                strength = strength_base
                relax_3d()
                k1 = displace.copy()

                for bmv in original:
                    f1 = k1[bmv] if bmv in k1 else Vector((0,0,0))
                    bmv.co = original[bmv] + f1 / 2
                strength = strength_base / 2
                relax_3d()
                k2 = displace.copy()

                for bmv in original:
                    f2 = k2[bmv] if bmv in k2 else Vector((0,0,0))
                    bmv.co = original[bmv] + f2 / 2
                strength = strength_base / 2
                relax_3d()
                k3 = displace.copy()

                for bmv in original:
                    f3 = k3[bmv] if bmv in k3 else Vector((0,0,0))
                    bmv.co = original[bmv] + f3
                strength = strength_base
                relax_3d()
                k4 = displace.copy()

                strength = strength_base / 6
                displace.clear()
                for bmv in original:
                    f1 = k1[bmv] if bmv in k1 else Vector((0,0,0))
                    f2 = k2[bmv] if bmv in k2 else Vector((0,0,0))
                    f3 = k3[bmv] if bmv in k3 else Vector((0,0,0))
                    f4 = k4[bmv] if bmv in k4 else Vector((0,0,0))
                    displace[bmv] = (f1 + 2 * f2 + 2 * f3 + f4) * strength
                    bmv.co = original[bmv]
                    #bmv.co = original[bmv] + (f1 + 2 * f2 + 2 * f3 + f4) * strength

            else:
                relax_3d()

            if relax.algorithm_prevent_bounce:
                for (bmv, v1) in displace.items():
                    if bmv not in self.prev_displace: continue
                    v0 = self.prev_displace[bmv]
                    if v0.length_squared < 1e-8 or v1.length_squared < 1e-8 or v0.dot(v1) >= 0: continue
                    self.bounce_mult[bmv] = self.bounce_mult.get(bmv, 1.0) * 0.5
                self.prev_displace = displace

            if len(displace) <= 1: continue

            mult = 1.0

            # limit the maximum displacement based on brush radius
            displace_max = max(
                (M @ Vector((*displace[bmv], 0.0))).length
                for bmv in displace
            )
            if displace_max > 1e-8:
                mult *= min(1.0, radius3D * relax.algorithm_max_distance_radius / displace_max)
            # print(time_delta, radius3D, relax.algorithm_max_distance_radius, displace_max, mult)
            if displace_max > radius3D:
                if not self.warned_limiting:
                    print('Relax: Limiting distance')
                    self.warned_limiting = True
                break

            # Pre-compute which verts occupy each source corner.
            # Keyed by kd-tree index so two verts at the same corner share an id.
            # Prevents snapping to a corner that a direct neighbor is already on.
            vert_to_corner_idx = {}
            if self.source_edge_accel and self.verts_near_source_edge:
                for corner_bmv in self.verts_near_source_edge:
                    if cr := source_corner_of_vert(corner_bmv, 0.05): # Tight fixed margin, 5% of local edge length
                        vert_to_corner_idx[corner_bmv] = cr[1]

            #MARK: Snapping
            # Ensure verts that received no algorithmic force still enter the snap pass
            # so they are projected onto the source surface from their current position.
            if snap_unforced_verts:
                for bmv in verts:
                    if bmv not in displace:
                        displace[bmv] = Vector((0.0, 0.0, 0.0))
            update_to = {}
            for bmv in displace:
                if bmv not in self.prev_position: self.prev_position[bmv] = Vector(bmv.co)

                displace_dist = displace[bmv].length * mult
                if bmv.link_edges and displace_dist > 1e-8:
                    avg_edge_len = get_bmv_avg_edge_len(bmv)
                    displace_dist *= min(1.0, avg_edge_len * relax.algorithm_max_distance_edges / displace_dist)
                # displace_dist *= vert_strength[bmv]
                displace_dist *= pressure  # tablet pressure applied here so it isn't normalised out by the caps above
                if relax.algorithm_prevent_bounce:
                    displace_dist *= self.bounce_mult.get(bmv, 1.0)
                displace_vec : Vector = displace[bmv].normalized() * displace_dist

                co : Vector = bmv.co + displace_vec

                if getattr(relax, 'algorithm_slide_edges', False) and bmv.link_edges:
                    best_dir = None
                    best_abs_dot = 0.0
                    for bme in bmv.link_edges:
                        edge_vec = bme.other_vert(bmv).co - bmv.co
                        edge_len = edge_vec.length
                        if edge_len < 1e-8:
                            continue
                        edge_dir = edge_vec / edge_len
                        abs_dot = abs(displace_vec.dot(edge_dir))
                        if abs_dot > best_abs_dot:
                            best_abs_dot = abs_dot
                            best_dir = edge_dir
                    if best_dir is not None:
                        displace_vec = best_dir * displace_vec.dot(best_dir)
                        co = bmv.co + displace_vec

                if opt_draw_net:
                    self.draw_vectors_net.append((bmv.co, displace_vec * 100))

                if self.mask_opt('boundary') == 'SLIDE' and bmv in self.boundary_verts and self.boundary_accel:
                    if p := self.boundary_accel.closest_point(co):
                        co = p
                if self.mask_opt('seams') == 'SLIDE' and bmv in self.seam_verts and self.seam_accel:
                    if p := self.seam_accel.closest_point(co):
                        co = p
                if self.mask_opt('creases') == 'SLIDE' and bmv in self.crease_verts and self.crease_accel:
                    if p := self.crease_accel.closest_point(co):
                        co = p
                if self.mask_opt('sharps') == 'SLIDE' and bmv in self.sharp_verts and self.sharp_accel:
                    if p := self.sharp_accel.closest_point(co):
                        co = p
                if self.mask_opt('angle') == 'SLIDE' and bmv in self.angle_verts and self.angle_accel:
                    if p := self.angle_accel.closest_point(co):
                        co = p

                co_world = M @ Vector((*co.xyz, 1.0))

                apply_edge_snap = False
                snap_avg_edge_len = 0.0
                is_promoted_bmv = bool(self.promoted_loop_verts) and bmv in self.promoted_loop_verts
                if self.source_edge_accel and bmv.link_edges and self.stickiness > 0.0:
                    snap_avg_edge_len = get_bmv_avg_edge_len(bmv)
                    if bmv in self.demoted_verts:
                        apply_edge_snap = False  # Demoted verts lose all stickiness
                    elif bmv in self.verts_near_source_edge or is_promoted_bmv:
                        # Promoted verts evaluate stickiness even outside the near set.
                        # The near set's normal-facing gate fails on a shallow crease for a vert sitting slightly off the feature,
                        # and without apply_edge_snap such a vert takes the on-edge branch below but
                        # can never actually edge-snap there.
                        if self.stickiness >= 1.0:
                            apply_edge_snap = True
                        else:
                            escape_threshold = snap_avg_edge_len * 0.005 * self.stickiness / (1.0 - self.stickiness)
                            # Only the perpendicular component of the force is compared against the threshold
                            perp = displace[bmv]
                            edge_nbrs = edge_constrained_neighbors(bmv)
                            if len(edge_nbrs) >= 2:
                                ev = edge_nbrs[-1].co - edge_nbrs[0].co
                                if ev.length > 1e-8:
                                    ed = ev.normalized()
                                    perp = perp - ed * perp.dot(ed)
                            elif len(edge_nbrs) == 1:
                                ev = edge_nbrs[0].co - bmv.co
                                if ev.length > 1e-8:
                                    ed = ev.normalized()
                                    perp = perp - ed * perp.dot(ed)
                            apply_edge_snap = perp.length <= escape_threshold

                co_world_snapped = None
                if self.source_edge_accel and displace_vec.length > 1e-6:
                    co_pt = point_to_bvec3(co_world.xyz)
                    if apply_edge_snap:
                        # Sticky verts project straight to their own feature run
                        result = self.closest_on_own_run(bmv, co_pt)
                        if result is not None:
                            co_world_snapped = Vector(result[0])
                        elif bmv_is_interior(bmv):
                            # Fallback (no feature data for this vert): project along normals,
                            # better than nearest-surface for interior verts that can shrink
                            # inward during smoothing. Not used for boundary or wire verts since
                            # the normals can graze a 90 degree angle.
                            normal_world = (Mi.transposed().to_3x3() @ bmv.normal).normalized()
                            best_dist = inf
                            for obj, M_obj, Mi_obj, Mi_obj_3x3 in self.sources:
                                ray_o  = (Mi_obj @ Vector((*co_pt, 1.0))).xyz
                                ray_d  = (Mi_obj_3x3 @ normal_world).normalized()
                                for d in (ray_d, -ray_d):
                                    result, co_hit, _, _ = obj.ray_cast(ray_o, d)
                                    if not result:
                                        continue
                                    hit_world = point_to_bvec3((M_obj @ Vector((*co_hit, 1.0))).xyz)
                                    dist = (Vector(hit_world) - Vector(co_pt)).length
                                    if dist < best_dist:
                                        best_dist = dist
                                        co_world_snapped = hit_world
                    else:
                        co_world_snapped = nearest_point_valid_sources(
                            context, co_pt, world=True, sources=self.sources, respect_clip_planes=True
                        )
                if not co_world_snapped:
                    # Feature snapping off, or closest_point / both rays returned nothing
                    co_world_snapped = nearest_point_valid_sources(
                        context, point_to_bvec3(co_world.xyz), world=True, sources=self.sources, respect_clip_planes=True
                    )

                # Reproject-shape fallback: when no external source exists but the caller
                # supplied a BVH built from the original mesh island, project onto that.
                if not co_world_snapped and snap_bvh:
                    hit_loc, _hit_norm, _hit_idx, _hit_dist = snap_bvh.find_nearest(point_to_bvec3(co_world.xyz))
                    if hit_loc:
                        co_world_snapped = point_to_bvec3(hit_loc)

                if not co_world_snapped:
                    # No source surface to snap to so keep the relaxed position.
                    # When sources are present, skip instead so a vert that
                    # failed to project isn't flung off the surface.
                    if self.sources: continue
                    co_local_snapped : Vector = co
                else:
                    co_local_snapped : Vector = Mi @ co_world_snapped

                _bv_world = (M @ Vector((*bmv.co, 1.0))).xyz
                _dist_to_brush = (Vector(_bv_world) - brush_center_world).length
                brush_snap_falloff = clamp(1.0 - _dist_to_brush / radius3D, 0.0, 1.0)

                if (bmv in self.verts_near_source_edge or is_promoted_bmv) and snap_avg_edge_len > 0:
                    # Vert is directly on the source edge. Promoted verts always take this path.
                    # The near-set's normal-facing gate fails for a vert sitting fractionally off
                    # a fold as its normal is the fold bisector, ~ perpendicular to the direction back
                    # to the feature, and falling to the approach-gated branch would leave it
                    # unsnapped on frames where it isn't moving toward the feature.
                    co_world_pt = point_to_bvec3(co_world.xyz)
                    if self.demoted_verts and bmv in self.demoted_verts:
                        # Demoted vert entered the snap zone so push it back out
                        max_push_dist = snap_avg_edge_len * self.scale_avg * self.source_sharp_proximity
                        push = self.demoted_net_push_world(bmv, Vector(co_world_pt), max_push_dist)
                        if push is not None:
                            if push.length > 1e-8:
                                co_local_snapped = Mi @ (Vector(co_world_pt) + push * 0.5)
                        elif closest_p := self.source_edge_accel.closest_point(co_world_pt):
                            to_edge_w = Vector(closest_p) - Vector(co_world_pt)
                            if to_edge_w.length > 1e-8:
                                co_local_snapped = Mi @ (Vector(co_world_pt) - to_edge_w * 0.5)
                    else:
                        # Promoted or no guide loops active - normal snapping
                        snap_threshold = source_snap_radius(
                            snap_avg_edge_len * self.scale_avg,
                            use_fixed=self.source_use_fixed, fixed_distance=self.source_fixed_distance, avg_edge_factor=self.source_sharp_proximity,
                        ) * brush_snap_falloff
                        corner_threshold = snap_threshold * getattr(relax, 'algorithm_source_corner_proximity', 2.0)
                        snapped_to_corner = False
                        if corner_result := self.source_edge_accel.find_corner(co_world_pt):
                            co_corner, corner_idx, dist_corner = corner_result
                            # A vert with a known feature run may only be captured by corners on that run
                            # A corner of a parallel feature must not grab it.
                            if dist_corner < corner_threshold and self.corner_allowed_for_vert(bmv, co_corner):
                                # Only snap to the corner if no direct neighbor is already there.
                                neighbor_at_corner = any(
                                    vert_to_corner_idx.get(bme.other_vert(bmv)) == corner_idx
                                    for bme in bmv.link_edges
                                )
                                if not neighbor_at_corner:
                                    co_local_snapped  = Mi @ Vector(co_corner)
                                    snapped_to_corner = True
                                    self.snapped_verts.add(bmv)
                        if apply_edge_snap and not snapped_to_corner:
                            if closest_result := self.closest_on_own_run(bmv, co_world_pt):
                                closest_p = Vector(closest_result[0])
                                if (closest_p - Vector(co_world_pt)).length <= snap_threshold:
                                    co_local_snapped = Mi @ closest_p
                                    self.snapped_verts.add(bmv)
                elif self.source_edge_accel and bmv.link_edges and snap_avg_edge_len > 0:
                    # Vert is approaching the source edge.
                    # Distance is measured from the vert's world position not its projected position.
                    is_demoted  = bool(self.demoted_verts)  and bmv in self.demoted_verts
                    is_promoted = bool(self.promoted_loop_verts) and bmv in self.promoted_loop_verts
                    snap_threshold = source_snap_radius(
                        snap_avg_edge_len * self.scale_avg,
                        use_fixed=self.source_use_fixed, fixed_distance=self.source_fixed_distance, avg_edge_factor=self.source_sharp_proximity,
                    ) * brush_snap_falloff
                    if is_promoted:
                        snap_threshold *= 1.5   # wider window pulls promoted loop in sooner
                    elif is_demoted:
                        snap_threshold *= 0.5   # narrower window keeps demoted verts farther out
                    co_world_pt = point_to_bvec3(co_world.xyz)
                    if is_demoted:
                        # Demoted: push away regardless of direction, from every demoting run.
                        push = self.demoted_net_push_world(bmv, Vector(co_world_snapped), snap_threshold)
                        if push is not None:
                            if push.length > 1e-8:
                                co_local_snapped = Mi @ (Vector(co_world_snapped) + push * 0.5)
                        elif closest_result := self.closest_on_own_run(bmv, co_world_pt):
                            p_vec = Vector(closest_result[0])
                            if (p_vec - co_world_pt).length <= snap_threshold:
                                to_edge_from_snapped = p_vec - Vector(co_world_snapped)
                                co_local_snapped = Mi @ (Vector(co_world_snapped) - to_edge_from_snapped * 0.5)
                    elif closest_result := self.closest_on_own_run(bmv, co_world_pt):
                        p_vec = Vector(closest_result[0])
                        to_edge_w = p_vec - co_world_pt
                        if to_edge_w.length <= snap_threshold:
                            # Promoted or neutral: snap only when approaching
                            disp_world = M.to_3x3() @ displace_vec
                            if to_edge_w.length < 1e-8 or disp_world.dot(to_edge_w) > 0:
                                co_local_snapped = Mi @ p_vec

                if self.mirror:
                    co_orig = bmv.co
                    co = Vector(co_local_snapped)
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
                    co_local_snapped = co

                update_to[bmv] = co_local_snapped
                # self.rfcontext.snap_vert(bmv)

            for (bmv, co) in update_to.items():
                bmv.co = co
            # self.rfcontext.update_verts_faces(displace)

        # Hard snap once per relax_verts call, outside the per-step loop.
        if getattr(relax, 'algorithm_interpolate_loops', False):
            # Collect interior verts that have cached axes
            interp_verts = [bmv for bmv in verts if self.loop_interp_cache.get(bmv)]

            # Save starting positions before convergence moves anything
            orig_positions = { bmv: Vector(bmv.co) for bmv in interp_verts }

            # Converge to the ideal via a fixed number of full snaps
            CONVERGENCE_STEPS = 5
            for _ in range(CONVERGENCE_STEPS):
                # Compute all targets before applying any move, so
                # one snap cannot shift the anchor of a neighbouring vert.
                step_targets = {}
                for bmv in interp_verts:
                    ideal = compute_loop_arc_target(bmv, self.loop_interp_cache[bmv])
                    if ideal is not None:
                        step_targets[bmv] = ideal
                for bmv, ideal in step_targets.items():
                    bmv.co = ideal   # full snap, refines P_cur for next pass

            self.bm.normal_update() # Refresh normals so the viewport shading is correct

            # Apply strength-scaled fraction of the total correction
            for bmv in interp_verts:
                orig     = orig_positions[bmv]
                converged = Vector(bmv.co)
                bmv.co   = orig          # restore before blending

                delta     = converged - orig
                delta_len = delta.length
                if delta_len < 1e-10:
                    continue

                snap_dist = delta_len * vert_strength[bmv] * pressure
                if relax.algorithm_prevent_bounce:
                    snap_dist *= self.bounce_mult.get(bmv, 1.0)
                if snap_dist > 1e-10:
                    bmv.co = orig + delta / delta_len * min(snap_dist, delta_len)

        # print(f'relaxed {len(verts)} ({len(chk_verts)}) in {time.time() - st} with {strength}')
        bmesh.update_edit_mesh(self.em, loop_triangles=False)
        # if context.area: context.area.tag_redraw()

        if debug_print:
            print(f'elapsed: {time.time() - self._time:0.3f}s {1.0/time_delta:0.1f}fps v:{len(verts)} e:{len(edges)} f:{len(faces)}')


    def draw(self, context:Context):
        Drawing.draw_snap_circles(context, self.snapped_verts, self.matrix_world)
        from ..preferences import RF_Prefs
        highlight = RF_Prefs.get_prefs(context).highlight_color
        snapped_loop = self.promoted_loop_verts & self.snapped_verts
        Drawing.draw_loop_highlight(context, self.promoted_loop_verts, self.matrix_world, highlight,
                                    skip_verts=snapped_loop, vert_groups=self.vert_feature_run)
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

        if not self.draw_vectors_positive and not self.draw_vectors_negative and not self.draw_vectors_net:
            return

        M = self.matrix_world
        rgn, r3d = context.region, context.region_data

        with Drawing.draw(context, CC_2D_LINES) as draw:
            #draw.point_size(vertex_size + 4)
            #draw.border(width=2, color=(1,1,0))
            draw.color(Color4((0, 1, 0, 0.5)))
            for (co,v) in self.draw_vectors_positive:
                co0, co1 = co, co + v
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ co0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ co1)
                if pt0 and pt1:
                    draw.vertex(pt0)
                    draw.vertex(pt1)
            draw.color(Color4((1, 0, 0, 0.5)))
            for (co,v) in self.draw_vectors_negative:
                co0, co1 = co, co + v
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ co0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ co1)
                if pt0 and pt1:
                    draw.vertex(pt0)
                    draw.vertex(pt1)
            draw.color(Color4((1, 1, 0, 0.5)))
            for (co,v) in self.draw_vectors_net:
                co0, co1 = co, co + v
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ co0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ co1)
                if pt0 and pt1:
                    draw.vertex(pt0)
                    draw.vertex(pt1)


    def finish(self, context):
        bmesh.update_edit_mesh(self.em, loop_triangles=False)
        # context.area.tag_redraw()

    def cancel(self, context):
        for (bmv, co) in self.prev_position.items():
            bmv.co = co
        bmesh.update_edit_mesh(self.em, loop_triangles=False)
        # context.area.tag_redraw()
