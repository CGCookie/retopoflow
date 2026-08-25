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
import numpy as np
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
    source_ray_cast,
    source_closest_point_on_mesh,
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
    prev_displace : 'tuple[dict[BMVert, int], object]'  # (bmv -> row into array, (T,3) array)
    bounce_mult : dict[BMVert, float]       # ...

    verts_accel : Accel
    avg_edge_len_cache : dict[BMVert, float]
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

            visibility_cache = self.visibility_cache # Bind to a local to avoid a reference cycle

            def is_bmvert_hidden(bmv : BMVert) -> bool:
                if bmv not in visibility_cache:
                    visibility_cache[bmv] = is_point_hidden_fast(matrix_world @ bmv.co)
                return visibility_cache[bmv]

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
        self.prev_displace = ({}, None)
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

        self.avg_edge_len_cache = {}
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
        self.vert_seed_seg = {}
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

    def bmv_avg_edge_len(self, bmv) -> float:
        # Cached per integration step and cleared in relax_verts
        cache = self.avg_edge_len_cache
        val = cache.get(bmv)
        if val is None:
            val = get_bmv_avg_edge_len(bmv)
            cache[bmv] = val
        return val

    def snap_proximity_world(self, bmv):
        return self.bmv_avg_edge_len(bmv) * self.scale_avg * self.source_sharp_proximity

    def corner_snap_threshold_world(self, bmv, factor):
        # Corner tests scale the raw avg edge length (no proximity factor), unlike Tweak.
        return self.bmv_avg_edge_len(bmv) * self.scale_avg * factor

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
        loop_interp_built = False

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

        # Forces accumulate into an array over verts_list so the batched algorithms below can scatter with numpy
        verts_list = list(verts)
        vert_row = { bmv: i for i, bmv in enumerate(verts_list) }
        displace_arr = np.zeros((len(verts_list), 3), dtype=np.float64)
        touched = np.zeros(len(verts_list), dtype=bool)  # rows with force applied or marked for snapping
        scalar_forces : dict[BMVert, Vector] = {}

        # Row space shared by every batched algorithm
        ext_verts = list(verts_list)
        ext_row = dict(vert_row)
        def ext_index(bmv):
            ''' Assigns rows for neighbors and face corners outside of `verts`. '''
            row = ext_row.get(bmv)
            if row is None:
                row = len(ext_verts)
                ext_row[bmv] = row
                ext_verts.append(bmv)
            return row

        last_coords = None  # ext coords from the latest relax_3d gather. None when stale (RK4) or never gathered

        def gather_ext_coords():
            flat : list[float] = []
            for bmv in ext_verts: flat.extend(bmv.co)
            return np.array(flat, dtype=np.float64).reshape(len(ext_verts), 3)

        def scatter_forces(rows, contrib):
            ''' Scatter-add pre-masked force rows into displace_arr. '''
            if not len(rows): return
            count = len(verts_list)
            # Bincount handles duplicate rows
            displace_arr[:, 0] += np.bincount(rows, weights=contrib[:, 0], minlength=count)
            displace_arr[:, 1] += np.bincount(rows, weights=contrib[:, 1], minlength=count)
            displace_arr[:, 2] += np.bincount(rows, weights=contrib[:, 2], minlength=count)
            touched[rows] = True

        def reset_forces():
            displace_arr[:] = 0.0
            touched[:] = False
            scalar_forces.clear()

        def add_force(bmv, f, wrt=None, sign=0, mult=0):
            if bmv not in vert_strength: return  # vert_strength has exactly the keys of `verts`
            if bmv not in scalar_forces: scalar_forces[bmv] = Vector((0,0,0))
            scalar_forces[bmv] += f * (vert_strength[bmv] * weight_mult)
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

        def get_laplacian_data(bmv, laplacian_cache):
            ''' (neighbors, is_boundary, 1/count) for verts laplacian applies to, else None. '''
            if bmv in laplacian_cache:
                return laplacian_cache[bmv]
            link_edges = bmv.link_edges
            edge_count = len(link_edges)
            if (
                edge_count == 2 or
                edge_count == 4 and len(bmv.link_faces) == 3
            ):
                laplacian_cache[bmv] = None
                return None
            is_boundary = bmv.is_boundary
            if is_boundary:
                if edge_count > 4:
                    laplacian_cache[bmv] = None
                    return None
                neighbors = tuple(bme.other_vert(bmv) for bme in link_edges if bme.is_boundary)
            else:
                neighbors = tuple(bme.other_vert(bmv) for bme in link_edges)
            if not neighbors:
                laplacian_cache[bmv] = None
                return None
            laplacian_data = (neighbors, is_boundary, 1.0 / len(neighbors))
            laplacian_cache[bmv] = laplacian_data
            return laplacian_data

        def laplacian_smooth(bmv, laplacian_cache, shape_preservation=0):
            ''' Push verts towards the average of their neighbors. '''
            laplacian_data = get_laplacian_data(bmv, laplacian_cache)
            if laplacian_data is None: return
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

        def make_laplacian_forces():
            ''' Flatten each vert's neighbor topology into index arrays once, then return the
            per-step force function that evaluates them all with numpy. None if no vert qualifies. '''
            bmvs : list[BMVert] = []
            nbr_rows : list[int] = []
            counts_list : list[int] = []
            boundary_list : list[bool] = []
            for bmv in verts_list:
                laplacian_data = get_laplacian_data(bmv, self.laplacian_cache)
                if laplacian_data is None: continue
                neighbors, is_boundary, _ = laplacian_data
                bmvs.append(bmv)
                nbr_rows.extend(ext_index(nb) for nb in neighbors)
                counts_list.append(len(neighbors))
                boundary_list.append(is_boundary)
            if not bmvs: return None

            counts = np.array(counts_list, dtype=np.intp)
            rows = np.array([vert_row[bmv] for bmv in bmvs], dtype=np.intp)
            nbrs = np.array(nbr_rows, dtype=np.intp)
            offsets = np.concatenate(([0], np.cumsum(counts[:-1])))  # reduceat group starts
            inv_counts = 1.0 / counts
            is_boundary = np.array(boundary_list, dtype=bool)
            scale = np.array([vert_strength[bmv] * weight_mult for bmv in bmvs], dtype=np.float64)

            def apply(coords):
                avg = np.add.reduceat(coords[nbrs], offsets, axis=0) * inv_counts[:, None]
                disp = (avg - coords[rows]) * 0.1
                disp[is_boundary] *= 0.5
                contrib = disp * scale[:, None]
                near = self.verts_near_source_edge
                if near:
                    keep_list = [bmv not in near for bmv in bmvs]
                    keep = np.array(keep_list, dtype=bool)
                    displace_arr[rows[keep]] += contrib[keep]
                    touched[rows[keep]] = True
                    # Constrained / sliding verts need the run-aware scalar path
                    for bmv, kept in zip(bmvs, keep_list):
                        if not kept: laplacian_smooth(bmv, self.laplacian_cache)
                else:
                    displace_arr[rows] += contrib
                    touched[rows] = True
            return apply

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

        def get_straighten_loops(bmv, straighten_loops_cache):
            ''' Opposing-neighbor pairs for interior 4-valence quad verts, else None. '''
            if bmv in straighten_loops_cache:
                return straighten_loops_cache[bmv]
            link_edges = list(bmv.link_edges)
            if len(link_edges) != 4 or len(bmv.link_faces) != 4:
                loops = None
            else:
                loops = get_bmv_loop_pairs(bmv)
            straighten_loops_cache[bmv] = loops
            return loops

        def straighten_loops(bmv, straighten_loops_cache):
            ''' push quad verts towards the line between opposing neighbords. '''
            if self.verts_near_source_edge and bmv in self.verts_near_source_edge:
                # Skip to preserve verts constrained to source edges
                return

            loops = get_straighten_loops(bmv, straighten_loops_cache)
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

        def make_straighten_loops_forces():
            ''' Flatten the opposing-neighbor pairs of every interior quad vert once, then return
            the per-step force function. None if no vert qualifies. '''
            bmvs : list[BMVert] = []
            pair_rows : list[tuple[int, int, int, int]] = []
            for bmv in verts_list:
                loops = get_straighten_loops(bmv, self.straighten_loops_cache)
                if not loops: continue
                (nb_a0, nb_b0), (nb_a1, nb_b1) = loops
                bmvs.append(bmv)
                pair_rows.append((ext_index(nb_a0), ext_index(nb_b0), ext_index(nb_a1), ext_index(nb_b1)))
            if not bmvs: return None

            rows = np.array([vert_row[bmv] for bmv in bmvs], dtype=np.intp)
            pairs = np.array(pair_rows, dtype=np.intp)
            # Normals are frozen here. Nothing recomputes them inside the step loop.
            nrm_flat : list[float] = []
            for bmv in bmvs: nrm_flat.extend(bmv.normal)
            normals = np.array(nrm_flat, dtype=np.float64).reshape(len(bmvs), 3)
            scale = np.array([vert_strength[bmv] * weight_mult for bmv in bmvs], dtype=np.float64)

            def apply(coords):
                co = coords[rows]
                total = np.zeros_like(co)
                for col_a, col_b in ((0, 1), (2, 3)):
                    start = coords[pairs[:, col_a]]
                    direction = coords[pairs[:, col_b]] - start
                    len_sq = np.einsum('ij,ij->i', direction, direction)
                    valid = len_sq >= 1e-12
                    t = np.einsum('ij,ij->i', co - start, direction) / np.where(valid, len_sq, 1.0)
                    force = (start + direction * t[:, None] - co) * 0.5
                    # Cancel out force in the vert's normal direction to avoid shrinking curved loops
                    force -= normals * np.einsum('ij,ij->i', force, normals)[:, None]
                    force[~valid] = 0.0
                    total += force
                contrib = total * scale[:, None]
                near = self.verts_near_source_edge
                if near:
                    # Constrained verts skip straightening entirely to preserve their snap
                    keep = np.fromiter((bmv not in near for bmv in bmvs), dtype=bool, count=len(bmvs))
                    displace_arr[rows[keep]] += contrib[keep]
                    touched[rows[keep]] = True
                else:
                    displace_arr[rows] += contrib
                    touched[rows] = True
            return apply

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

        def make_average_edge_lengths_forces():
            ''' Flatten every edge's endpoint rows and island id once, then return the per-step
            force function. Both endpoints of an edge get equal and opposite pushes. '''
            edges_list = list(edges)
            island_index : dict = {}
            isl_list : list[int] = []
            v0_list : list[int] = []
            v1_list : list[int] = []
            rows_sides : tuple[list[int], list[int]] = ([], [])
            scale_sides : tuple[list[float], list[float]] = ([], [])
            valid_sides : tuple[list[bool], list[bool]] = ([], [])
            slots_by_vert : dict[BMVert, list[tuple[int, int]]] = {}
            for ei, bme in enumerate(edges_list):
                bmv0, bmv1 = bme.verts
                isl = vert_island[bmv0]
                isl_list.append(island_index.setdefault(isl, len(island_index)))
                v0_list.append(ext_index(bmv0))
                v1_list.append(ext_index(bmv1))
                for side, bmv in enumerate((bmv0, bmv1)):
                    row = vert_row.get(bmv)
                    rows_sides[side].append(row if row is not None else 0)
                    scale_sides[side].append(vert_strength[bmv] * weight_mult if row is not None else 0.0)
                    valid_sides[side].append(row is not None)
                    if row is not None:
                        slots_by_vert.setdefault(bmv, []).append((side, ei))

            v0_rows = np.array(v0_list, dtype=np.intp)
            v1_rows = np.array(v1_list, dtype=np.intp)
            isl = np.array(isl_list, dtype=np.intp)
            isl_counts = np.bincount(isl, minlength=len(island_index)).astype(np.float64)
            rows_arr = tuple(np.array(rows, dtype=np.intp) for rows in rows_sides)
            scale_arr = tuple(np.array(scales, dtype=np.float64) for scales in scale_sides)
            valid_arr = tuple(np.array(valids, dtype=bool) for valids in valid_sides)

            def apply(coords):
                vecs = coords[v1_rows] - coords[v0_rows]
                lens = np.linalg.norm(vecs, axis=1)
                # Average edge length per island so disconnected areas of differing scale don't distort each other.
                island_avg = np.bincount(isl, weights=lens, minlength=len(isl_counts)) / isl_counts
                diff = island_avg[isl] - lens
                active = np.abs(diff) >= 1e-12
                f = vecs * (diff / 25.0 / np.maximum(lens, 1e-30))[:, None]
                near = self.verts_near_source_edge
                constrained : list[tuple[BMVert, int, int]] = []
                constrained_masks = None
                if near:
                    constrained_masks = (np.zeros(len(lens), dtype=bool), np.zeros(len(lens), dtype=bool))
                    for bmv in near:
                        for side, ei in slots_by_vert.get(bmv, ()):
                            constrained_masks[side][ei] = True
                            constrained.append((bmv, side, ei))
                for side, sign in ((0, -1.0), (1, 1.0)):
                    mask = active & valid_arr[side]
                    if constrained_masks is not None: mask &= ~constrained_masks[side]
                    scatter_forces(rows_arr[side][mask], f[mask] * (sign * scale_arr[side][mask])[:, None])
                # Constrained endpoints slide along their source edge (scalar projection path)
                for bmv, side, ei in constrained:
                    if not active[ei]: continue
                    f_vec = Vector(f[ei] if side else -f[ei])
                    if edge_proj_dir := get_edge_proj_dir(bmv):
                        f_vec = edge_proj_dir * f_vec.dot(edge_proj_dir)
                    add_force(bmv, f_vec)
            return apply

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

        def make_equalize_faces_forces():
            ''' Flatten every face's corner rows once, grouped by vert count so each group is a
            fixed-width (faces, k, 3) array, then return the per-step force function. The returned
            function applies both the area-matching and the regular-polygon shape forces.
            None when there are no faces. '''
            if not faces: return None
            faces_list = list(faces)
            island_index : dict = {}
            isl = np.array(
                [island_index.setdefault(face_island[bmf], len(island_index)) for bmf in faces_list],
                dtype=np.intp,
            )
            isl_counts = np.bincount(isl, minlength=len(island_index)).astype(np.float64)
            vert_counts = np.array([len(get_face_topology(bmf)[0]) for bmf in faces_list], dtype=np.float64)
            slots_by_vert : dict[BMVert, list[tuple[int, int, int]]] = {}   # bmv -> [(vert_count, face_local, slot)]
            group_build : dict[int, dict] = {}
            for fi, bmf in enumerate(faces_list):
                face_verts, face_edges = get_face_topology(bmf)
                k = len(face_verts)
                grp = group_build.setdefault(k, {
                    'face_idx': [], 'vrows': [], 'srows': [], 'scale': [], 'valid': [],
                    'normals': [], 'special': [], 'special_other': [],
                })
                face_local = len(grp['face_idx'])
                grp['face_idx'].append(fi)
                grp['normals'].extend(bmf.normal)   # frozen; normals are stable for the whole call
                face_edge_set = set(face_edges)
                for slot, bmv in enumerate(face_verts):
                    grp['vrows'].append(ext_index(bmv))
                    row = vert_row.get(bmv)
                    grp['srows'].append(row if row is not None else 0)
                    grp['scale'].append(vert_strength[bmv] * weight_mult if row is not None else 0.0)
                    grp['valid'].append(row is not None)
                    # 3-valence boundary verts pull toward the boundary-edge midpoint, not the face center
                    special_other = None
                    if bmv.is_boundary and len(bmv.link_edges) == 3:
                        others = [bme.other_vert(bmv) for bme in bmv.link_edges if bme.is_boundary and bme in face_edge_set]
                        if others: special_other = others[0]
                    grp['special'].append(special_other is not None)
                    grp['special_other'].append(ext_index(special_other) if special_other is not None else 0)
                    if row is not None:
                        slots_by_vert.setdefault(bmv, []).append((k, face_local, slot))
            groups = {}
            for k, grp in group_build.items():
                face_count = len(grp['face_idx'])
                groups[k] = (
                    np.array(grp['face_idx'], dtype=np.intp),
                    np.array(grp['vrows'], dtype=np.intp).reshape(face_count, k),
                    np.array(grp['srows'], dtype=np.intp).reshape(face_count, k),
                    np.array(grp['scale'], dtype=np.float64).reshape(face_count, k),
                    np.array(grp['valid'], dtype=bool).reshape(face_count, k),
                    np.array(grp['normals'], dtype=np.float64).reshape(face_count, 3),
                    np.array(grp['special'], dtype=bool).reshape(face_count, k),
                    np.array(grp['special_other'], dtype=np.intp).reshape(face_count, k),
                    2.0 * math.pi / k,   # corner angle spacing
                )

            def apply(coords):
                areas = np.fromiter((bmf.calc_area() for bmf in faces_list), dtype=np.float64, count=len(faces_list))
                per_vert_area = areas / vert_counts
                # Average face area per island for the same reason as edges above.
                island_avg = np.bincount(isl, weights=per_vert_area, minlength=len(isl_counts)) / isl_counts
                avg_area_all = island_avg[isl]
                avg_sqrt_all = np.sqrt(avg_area_all)
                near = self.verts_near_source_edge

                for k, (face_idx, vrows, srows, scale, valid, normals, special, special_other, spacing) in groups.items():
                    co = coords[vrows]                        # (F,k,3)
                    center = co.mean(axis=1)                  # face midpoint = vert average
                    rel = co - center[:, None, :]
                    avg_area = avg_area_all[face_idx]
                    avg_sqrt = avg_sqrt_all[face_idx]

                    # average_face_areas: scale faces towards the average
                    area_ok = avg_area >= 1e-20
                    diff = np.where(area_ok, per_vert_area[face_idx] - avg_area, 0.0) / np.where(area_ok, avg_area, 1.0)
                    centers_slot = np.where(
                        special[:, :, None],
                        (co + coords[special_other]) * 0.5,
                        center[:, None, :],
                    )
                    forces_area = (centers_slot - co) * (diff * 0.25)[:, None, None]

                    # average_face_shape: push verts toward their targets on a regular polygon
                    z_axis = normals / np.maximum(np.linalg.norm(normals, axis=1), 1e-30)[:, None]
                    ref = np.where((np.abs(z_axis[:, 2]) < 0.9)[:, None], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])
                    x_axis = np.cross(ref, z_axis)
                    x_axis = x_axis / np.maximum(np.linalg.norm(x_axis, axis=1), 1e-30)[:, None]
                    y_axis = np.cross(z_axis, x_axis)
                    radii = np.linalg.norm(rel, axis=2)       # (F,k)
                    avg_radius = radii.mean(axis=1)
                    x2d = np.einsum('fkj,fj->fk', rel, x_axis)
                    y2d = np.einsum('fkj,fj->fk', rel, y_axis)
                    r2d = np.sqrt(x2d * x2d + y2d * y2d)
                    ok2d = r2d > 1e-8
                    r2d_safe = np.where(ok2d, r2d, 1.0)
                    slot_idx = np.arange(k)
                    conj_k = np.exp(-1j * spacing * slot_idx)
                    unit2d = np.where(ok2d, x2d / r2d_safe, 0.0) + 1j * np.where(ok2d, y2d / r2d_safe, 0.0)
                    sum_z = (unit2d * conj_k[None, :]).sum(axis=1)
                    phase = np.arctan2(sum_z.imag, sum_z.real)
                    radius_ok = avg_radius >= 1e-8
                    scale_shape = np.where(radius_ok, avg_sqrt, 0.0) / np.where(radius_ok, avg_radius, 1.0)
                    ang = phase[:, None] + spacing * slot_idx[None, :]
                    forces_shape = (
                        np.cos(ang)[:, :, None] * (x_axis * avg_sqrt[:, None])[:, None, :]
                        + np.sin(ang)[:, :, None] * (y_axis * avg_sqrt[:, None])[:, None, :]
                        - rel * scale_shape[:, None, None]
                    )
                    forces_shape[~radius_ok] = 0.0

                    # Constrained slots leave the vectorized scatter and go through the scalar projection path
                    constrained : list[tuple[BMVert, int, int]] = []
                    cmask = None
                    if near:
                        cmask = np.zeros((len(face_idx), k), dtype=bool)
                        for bmv in near:
                            for slot_k, face_local, slot in slots_by_vert.get(bmv, ()):
                                if slot_k != k: continue
                                cmask[face_local, slot] = True
                                constrained.append((bmv, face_local, slot))
                    mask_area = valid & area_ok[:, None]
                    mask_shape = valid & radius_ok[:, None]
                    if cmask is not None:
                        mask_area &= ~cmask
                        mask_shape &= ~cmask
                    flat_rows = srows.reshape(-1)
                    flat_scale = scale.reshape(-1, 1)
                    flat_mask_area = mask_area.reshape(-1)
                    flat_mask_shape = mask_shape.reshape(-1)
                    scatter_forces(flat_rows[flat_mask_area], (forces_area.reshape(-1, 3) * flat_scale)[flat_mask_area])
                    scatter_forces(flat_rows[flat_mask_shape], (forces_shape.reshape(-1, 3) * flat_scale)[flat_mask_shape])
                    for bmv, face_local, slot in constrained:
                        edge_proj_dir = get_edge_proj_dir(bmv)
                        if area_ok[face_local]:
                            f_vec = Vector(forces_area[face_local, slot])
                            if edge_proj_dir: f_vec = edge_proj_dir * f_vec.dot(edge_proj_dir)
                            add_force(bmv, f_vec)
                        if radius_ok[face_local]:
                            f_vec = Vector(forces_shape[face_local, slot])
                            if edge_proj_dir: f_vec = edge_proj_dir * f_vec.dot(edge_proj_dir)
                            add_force(bmv, f_vec)
            return apply

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
                    dist_threshold = self.bmv_avg_edge_len(bmv) * self.source_sharp_proximity * 1.5
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

        def build_loop_interpolation_runs():
            ''' Fill loop_interp_cache for every vert, storing (P_a, n_a, t, P_b, n_b) tuples whose positions and normals
            are frozen at build time so the post-loop SLERP always uses the original anchor geometry,
            not positions that may have been displaced by subsequent Laplacian steps. '''
            MAX_DEPTH = 200          # per-member depth cap: how far a member may sit from an anchor
            MAX_RUN = 2 * MAX_DEPTH  # longer runs cannot contain a member within the cap from both ends
            loop_cache = self.loop_interp_cache
            straighten_loops_cache = self.straighten_loops_cache
            covered : dict[BMVert, int] = {}  # bitmask of pair indices already walked

            def walk_direction(seed, first, chain_set):
                ''' Walk from seed through first until leaving the selection. Returns
                (members, anchor): members are the selected verts beyond seed in order;
                anchor is the first unselected vert, or None for pole/boundary/cycle/overflow. '''
                if first not in verts:
                    return [], first
                members = []
                prev, cur = seed, first
                while True:
                    if cur in chain_set:
                        return members, None   # loop closes inside the selection
                    chain_set.add(cur)
                    members.append(cur)
                    if len(chain_set) > MAX_RUN:
                        return members, None   # depth cap unreachable for every member
                    nxt = get_bmv_next_loop_vert(prev, cur)
                    if nxt is None:
                        return members, None   # mesh boundary or pole
                    if nxt not in verts:
                        return members, nxt
                    prev, cur = cur, nxt

            for seed in verts:
                seed_pairs = get_straighten_loops(seed, straighten_loops_cache)
                if not seed_pairs: continue
                for pair_idx, (nb_a, nb_b) in enumerate(seed_pairs):
                    if covered.get(seed, 0) & (1 << pair_idx): continue
                    chain_set = {seed}
                    members_a, anchor_a = walk_direction(seed, nb_a, chain_set)
                    members_b, anchor_b = walk_direction(seed, nb_b, chain_set)
                    chain = members_a[::-1] + [seed] + members_b  # ordered from the anchor_a side
                    valid = anchor_a is not None and anchor_b is not None
                    if valid:
                        span = len(chain) + 1
                        co_a, nrm_a = Vector(anchor_a.co), bmv_compute_normal(anchor_a)
                        co_b, nrm_b = Vector(anchor_b.co), bmv_compute_normal(anchor_b)
                    # Every member's own walks would reach the same ends, so each one's
                    # matching pair is marked walked whatever the verdict.
                    for j, member in enumerate(chain):
                        member_pairs = seed_pairs if member is seed else get_straighten_loops(member, straighten_loops_cache)
                        if not member_pairs: continue
                        a_side = chain[j - 1] if j > 0 else anchor_a
                        nb_ref = a_side if a_side is not None else (chain[j + 1] if j + 1 < len(chain) else nb_a)
                        (p0a, p0b), (p1a, p1b) = member_pairs
                        if   nb_ref is p0a or nb_ref is p0b: p_idx, p_first = 0, p0a
                        elif nb_ref is p1a or nb_ref is p1b: p_idx, p_first = 1, p1a
                        else: continue
                        covered[member] = covered.get(member, 0) | (1 << p_idx)
                        if not valid: continue
                        depth_a = j + 1
                        depth_b = span - depth_a
                        if depth_a > MAX_DEPTH or depth_b > MAX_DEPTH: continue
                        axes = loop_cache.get(member)
                        if axes is None:
                            axes = []
                            loop_cache[member] = axes
                        # Match the member's own pair orientation: the arc reconstruction
                        # is not symmetric in its endpoints, so which anchor plays A matters.
                        if a_side is p_first:
                            axes.append((co_a, nrm_a, depth_a / span, co_b, nrm_b))
                        else:
                            axes.append((co_b, nrm_b, depth_b / span, co_a, nrm_a))

        def relax_3d():
            #MARK: Add forces
            nonlocal loop_interp_built, last_coords
            reset_forces()
            if batch_forces:
                coords = gather_ext_coords()
                last_coords = coords
                for batch_fn in batch_forces:
                    batch_fn(coords)
            if getattr(relax, 'algorithm_interpolate_loops', False) and not loop_interp_built:
                build_loop_interpolation_runs()
                loop_interp_built = True
            if relax.algorithm_correct_flipped_faces:
                correct_flipped_faces()
            if self.source_edge_accel and self.promoted_loop_verts:
                pull_promoted_push_demoted()

            # Merge scalar forces
            for bmv, f in scalar_forces.items():
                row = vert_row[bmv]
                displace_arr[row] += f
                touched[row] = True

            # Constrained verts may have no forces
            # so mark them touched so they still get updated for snapping
            if self.verts_near_source_edge:
                for bmv in self.verts_near_source_edge:
                    row = vert_row.get(bmv)
                    if row is not None:
                        touched[row] = True

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

        #MARK: Precompute
        # So the snap loop below doesn't have to do these computations per vert.
        M_3x3 = M.to_3x3()
        M3_np = np.array(M_3x3, dtype=np.float64)
        Mt_np = np.array(M.translation, dtype=np.float64)
        center_np = np.array(brush_center_world[:3], dtype=np.float64)
        slide_edges_opt = bool(getattr(relax, 'algorithm_slide_edges', False))
        slide_accels = [
            (mark_verts, accel)
            for name, mark_verts, accel in (
                ('boundary', self.boundary_verts, self.boundary_accel),
                ('seams',    self.seam_verts,     self.seam_accel),
                ('creases',  self.crease_verts,   self.crease_accel),
                ('sharps',   self.sharp_verts,    self.sharp_accel),
                ('angle',    self.angle_verts,    self.angle_accel),
            )
            if self.mask_opt(name) == 'SLIDE' and accel
        ]
        source_edge_accel = self.source_edge_accel
        stickiness_active = bool(source_edge_accel) and self.stickiness > 0.0
        has_sources = bool(self.sources)
        rv3d_clip = context.region_data
        clip_active = bool(rv3d_clip and rv3d_clip.use_clip_planes)
        clip_planes = [tuple(p) for p in rv3d_clip.clip_planes] if clip_active else None
        # Each tuple is (source-local <- world, world <- source-local)
        # single_source below combines both with M/Mi so the snap loop never needs to build them per vert.
        source_xforms = [(obj_s, Mi_s @ M, M_s) for (obj_s, M_s, Mi_s, _) in self.sources]
        single_source = None
        if len(self.sources) == 1 and not clip_active and not stickiness_active and snap_bvh is None:
            obj_s, M_s, Mi_s, _ = self.sources[0]
            single_source = (obj_s, Mi_s @ M, Mi @ M_s)

        #MARK: Batched forces
        # Each algorithm flattens its own topology into the shared row space and returns the
        # function that evaluates it every step, or None when it has nothing to do.
        # All of these must run before the first gather_ext_coords(), since they are what
        # assign the extra rows that the gathered coords array has to cover.
        lap_forces = make_laplacian_forces()             if relax.algorithm_laplacian            else None
        st_forces  = make_straighten_loops_forces()      if relax.algorithm_straighten_edges     else None
        ael_forces = make_average_edge_lengths_forces()  if relax.algorithm_average_edge_lengths else None
        eq_forces  = make_equalize_faces_forces()        if relax.algorithm_equalize_faces       else None
        batch_forces = [fn for fn in (lap_forces, st_forces, ael_forces, eq_forces) if fn]

        # Full neighbor topology for the snap pass: per-vert average edge length becomes one
        # reduceat per step instead of a per-vert edge scan.
        cap_batch = None
        cap_rows_list : list[int] = []
        cap_nbrs_list : list[int] = []
        cap_counts_list : list[int] = []
        for row, bmv in enumerate(verts_list):
            link_edges = bmv.link_edges
            if not link_edges: continue
            cap_rows_list.append(row)
            cap_counts_list.append(len(link_edges))
            cap_nbrs_list.extend(ext_index(bme.other_vert(bmv)) for bme in link_edges)
        if cap_rows_list:
            cap_counts = np.array(cap_counts_list, dtype=np.intp)
            cap_rows_arr = np.array(cap_rows_list, dtype=np.intp)
            cap_batch = (
                cap_rows_arr,
                np.array(cap_nbrs_list, dtype=np.intp),
                np.repeat(cap_rows_arr, cap_counts),  # self row per neighbor slot
                np.concatenate(([0], np.cumsum(cap_counts[:-1]))),
                1.0 / cap_counts,
            )

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
            self.avg_edge_len_cache.clear()
            update_source_context()
            if relax.algorithm_method == 'RK4':
                orig_flat : list[float] = []
                for bmv in verts_list: orig_flat.extend(bmv.co)
                original = np.array(orig_flat, dtype=np.float64).reshape(len(verts_list), 3)

                def set_all_cos(cos):
                    for row, bmv in zip(cos, verts_list):
                        bmv.co = Vector(row)

                strength = strength_base
                relax_3d()
                k1 = displace_arr.copy()

                set_all_cos(original + k1 * 0.5)
                strength = strength_base / 2
                relax_3d()
                k2 = displace_arr.copy()

                set_all_cos(original + k2 * 0.5)
                strength = strength_base / 2
                relax_3d()
                k3 = displace_arr.copy()

                set_all_cos(original + k3)
                strength = strength_base
                relax_3d()
                k4 = displace_arr.copy()

                strength = strength_base / 6
                displace_arr[:] = (k1 + 2.0 * k2 + 2.0 * k3 + k4) * strength
                touched[:] = True
                set_all_cos(original)
                #set_all_cos(original + displace_arr)
                last_coords = None  # k4's gather was at perturbed positions so the snap pass must re-gather

            else:
                relax_3d()

            if relax.algorithm_prevent_bounce:
                touched_idx = np.nonzero(touched)[0]
                touched_list = touched_idx.tolist()  # python ints, iterating np scalars is slow
                prev_map, prev_arr = self.prev_displace
                if prev_map:
                    prev_rows = np.fromiter(
                        (prev_map.get(verts_list[row], -1) for row in touched_list),
                        dtype=np.intp, count=len(touched_list),
                    )
                    have = prev_rows >= 0
                    if have.any():
                        v0 = prev_arr[prev_rows[have]]
                        v1 = displace_arr[touched_idx[have]]
                        bouncing = (
                            (np.einsum('ij,ij->i', v0, v0) >= 1e-8)
                            & (np.einsum('ij,ij->i', v1, v1) >= 1e-8)
                            & (np.einsum('ij,ij->i', v0, v1) < 0)
                        )
                        if bouncing.any():
                            bounce_mult = self.bounce_mult
                            for row in touched_idx[have][bouncing].tolist():
                                bmv = verts_list[row]
                                bounce_mult[bmv] = bounce_mult.get(bmv, 1.0) * 0.5
                self.prev_displace = (
                    { verts_list[row]: k for k, row in enumerate(touched_list) },
                    displace_arr[touched_idx].copy(),
                )

            if int(touched.sum()) <= 1: continue

            #MARK: Snapping
            # Verts that received no force still enter the snap pass so they are still projected
            if snap_unforced_verts:
                touched[:] = True

            # Snap-vert positions come from the coords relax_3d already gathered this step
            # Average edge lengths for the distance cap come from one reduceat over the full-neighbor topology
            snap_rows = np.nonzero(touched)[0]
            snap_bmvs = [verts_list[row] for row in snap_rows.tolist()]
            snap_count = len(snap_bmvs)
            prev_position = self.prev_position
            for bmv in snap_bmvs:
                if bmv not in prev_position: prev_position[bmv] = Vector(bmv.co)
            cap_edges = relax.algorithm_max_distance_edges
            coords_now = last_coords if last_coords is not None else gather_ext_coords()
            cos_arr = coords_now[snap_rows]
            avg_full = np.full(len(verts_list), inf, dtype=np.float64)
            if cap_batch is not None:
                cap_rows, cap_nbrs, cap_self, cap_offsets, cap_invc = cap_batch
                cap_lens = np.linalg.norm(coords_now[cap_nbrs] - coords_now[cap_self], axis=1)
                avg_full[cap_rows] = np.add.reduceat(cap_lens, cap_offsets) * cap_invc
            avg_len_snap = avg_full[snap_rows]  # inf where the vert has no edges
            edge_caps = np.where(np.isfinite(avg_len_snap), avg_len_snap * cap_edges, inf)
            disp_arr = displace_arr[snap_rows]

            mult = 1.0

            # limit the maximum displacement based on brush radius
            world_norms = np.linalg.norm(disp_arr @ M3_np.T, axis=1)
            displace_max = float(world_norms.max())
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

            local_norms = np.linalg.norm(disp_arr, axis=1)
            dists = local_norms * mult
            dists = np.where(dists > 1e-8, np.minimum(dists, edge_caps), dists)
            # dists *= vert_strengths
            dists *= pressure  # tablet pressure applied here so it isn't normalised out by the caps above
            if relax.algorithm_prevent_bounce and self.bounce_mult:
                bounce_mult = self.bounce_mult
                dists *= np.fromiter((bounce_mult.get(bmv, 1.0) for bmv in snap_bmvs), dtype=np.float64, count=snap_count)
            vec_arrs = disp_arr * (dists / np.maximum(local_norms, 1e-30))[:, None]
            newco_arrs = cos_arr + vec_arrs
            dists_list = dists.tolist()
            if stickiness_active:
                avg_len_list = avg_len_snap.tolist()
                # brush falloff for the source-feature thresholds, for all snap verts at once
                bv_world = cos_arr @ M3_np.T + Mt_np
                falloff_list = np.clip(
                    1.0 - np.linalg.norm(bv_world - center_np, axis=1) / radius3D, 0.0, 1.0,
                ).tolist()

            update_to = {}
            near_source = self.verts_near_source_edge
            promoted_verts = self.promoted_loop_verts
            demoted_verts = self.demoted_verts
            stickiness_val = self.stickiness
            for snap_i, bmv in enumerate(snap_bmvs):
                co : Vector = Vector(newco_arrs[snap_i])
                displace_vec : 'Vector | None' = None  # materialized only by the paths that need it
                disp_len : float = dists_list[snap_i]

                if slide_edges_opt and bmv.link_edges:
                    displace_vec = Vector(vec_arrs[snap_i])
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
                        disp_len = displace_vec.length

                if opt_draw_net:
                    if displace_vec is None: displace_vec = Vector(vec_arrs[snap_i])
                    self.draw_vectors_net.append((bmv.co, displace_vec * 100))

                for slide_verts, slide_accel in slide_accels:
                    if bmv in slide_verts:
                        if p := slide_accel.closest_point(co):
                            co = p

                apply_edge_snap = False
                snap_avg_edge_len = 0.0
                is_promoted_bmv = bool(promoted_verts) and bmv in promoted_verts
                if stickiness_active and bmv.link_edges:
                    snap_avg_edge_len = avg_len_list[snap_i]
                    if bmv in demoted_verts:
                        apply_edge_snap = False  # Demoted verts lose all stickiness
                    elif bmv in near_source or is_promoted_bmv:
                        # Promoted verts evaluate stickiness even outside the near set.
                        # The near set's normal-facing gate fails on a shallow crease for a vert sitting slightly off the feature,
                        # and without apply_edge_snap such a vert takes the on-edge branch below but
                        # can never actually edge-snap there.
                        if stickiness_val >= 1.0:
                            apply_edge_snap = True
                        else:
                            escape_threshold = snap_avg_edge_len * 0.005 * stickiness_val / (1.0 - stickiness_val)
                            # Only the perpendicular component of the force is compared against the threshold
                            perp = Vector(disp_arr[snap_i])
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
                co_local_snapped : 'Vector | None' = None
                if source_edge_accel and apply_edge_snap and disp_len > 1e-6:
                    co_pt = M @ co
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
                                result, co_hit, _, _ = source_ray_cast(obj, ray_o, d)
                                if not result:
                                    continue
                                hit_world = point_to_bvec3((M_obj @ Vector((*co_hit, 1.0))).xyz)
                                dist = (Vector(hit_world) - Vector(co_pt)).length
                                if dist < best_dist:
                                    best_dist = dist
                                    co_world_snapped = hit_world

                if co_world_snapped is None:
                    if single_source is not None:
                        # Fast path. One source, no clipping, no feature snapping.
                        # One combined transform in, the guarded C query, one combined transform out.
                        src_obj, to_src, to_edit = single_source
                        ok, hit_co, _n, _i = source_closest_point_on_mesh(src_obj, to_src @ co)
                        if not ok: continue  # keep the vert in place rather than fling it off the surface
                        co_local_snapped = to_edit @ hit_co
                    else:
                        co_world_q = M @ co
                        best_hit = None
                        best_dist = inf
                        for src_obj, to_src, src_to_world in source_xforms:
                            ok, hit_co, _n, _i = source_closest_point_on_mesh(src_obj, to_src @ co)
                            if not ok: continue
                            hit_world = src_to_world @ hit_co
                            if clip_active:
                                hx, hy, hz = hit_world
                                if any(p0*hx + p1*hy + p2*hz + p3 < 0 for (p0, p1, p2, p3) in clip_planes):
                                    continue
                            dist = (hit_world - co_world_q).length
                            if dist < best_dist:
                                best_hit, best_dist = hit_world, dist
                        co_world_snapped = best_hit

                        # Reproject-shape fallback: when no external source exists but the caller
                        # supplied a BVH built from the original mesh island, project onto that.
                        if not co_world_snapped and snap_bvh:
                            hit_loc, _hit_norm, _hit_idx, _hit_dist = snap_bvh.find_nearest(co_world_q)
                            if hit_loc:
                                co_world_snapped = point_to_bvec3(hit_loc)

                if co_local_snapped is None:
                    if not co_world_snapped:
                        # No source surface to snap to so keep the relaxed position.
                        # When sources are present, skip instead so a vert that
                        # failed to project isn't flung off the surface.
                        if has_sources: continue
                        co_local_snapped = co
                    else:
                        co_local_snapped = Mi @ co_world_snapped

                if (bmv in near_source or is_promoted_bmv) and snap_avg_edge_len > 0:
                    # Vert is directly on the source edge. Promoted verts always take this path.
                    # The near-set's normal-facing gate fails for a vert sitting fractionally off
                    # a fold as its normal is the fold bisector, ~ perpendicular to the direction back
                    # to the feature, and falling to the approach-gated branch would leave it
                    # unsnapped on frames where it isn't moving toward the feature.
                    co_world_pt = M @ co
                    if demoted_verts and bmv in demoted_verts:
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
                        ) * falloff_list[snap_i]
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
                elif source_edge_accel and bmv.link_edges and snap_avg_edge_len > 0:
                    # Vert is approaching the source edge.
                    # Distance is measured from the vert's world position not its projected position.
                    is_demoted  = bool(demoted_verts)  and bmv in demoted_verts
                    is_promoted = is_promoted_bmv
                    snap_threshold = source_snap_radius(
                        snap_avg_edge_len * self.scale_avg,
                        use_fixed=self.source_use_fixed, fixed_distance=self.source_fixed_distance, avg_edge_factor=self.source_sharp_proximity,
                    ) * falloff_list[snap_i]
                    if is_promoted:
                        snap_threshold *= 1.5   # wider window pulls promoted loop in sooner
                    elif is_demoted:
                        snap_threshold *= 0.5   # narrower window keeps demoted verts farther out
                    co_world_pt = M @ co
                    if is_demoted:
                        # co_world_snapped can be None at this point if snapping in local space instead
                        co_world_base = Vector(co_world_snapped) if co_world_snapped is not None else M @ co_local_snapped
                        # Demoted: push away regardless of direction, from every demoting run.
                        push = self.demoted_net_push_world(bmv, co_world_base, snap_threshold)
                        if push is not None:
                            if push.length > 1e-8:
                                co_local_snapped = Mi @ (co_world_base + push * 0.5)
                        elif closest_result := self.closest_on_own_run(bmv, co_world_pt):
                            p_vec = Vector(closest_result[0])
                            if (p_vec - co_world_pt).length <= snap_threshold:
                                to_edge_from_snapped = p_vec - co_world_base
                                co_local_snapped = Mi @ (co_world_base - to_edge_from_snapped * 0.5)
                    elif closest_result := self.closest_on_own_run(bmv, co_world_pt):
                        p_vec = Vector(closest_result[0])
                        to_edge_w = p_vec - co_world_pt
                        if to_edge_w.length <= snap_threshold:
                            # Promoted or neutral: snap only when approaching
                            if displace_vec is None: displace_vec = Vector(vec_arrs[snap_i])
                            disp_world = M_3x3 @ displace_vec
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
