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

import bpy
import math
import bmesh
import time
import numpy as np
from itertools import chain
from collections import defaultdict
from collections.abc import Sequence, Iterator
from math import isclose
from typing import Literal
from bmesh.types import BMVert, BMEdge, BMFace, BMesh
from bpy.types import Context, Mesh
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Matrix, Vector
from ..common.bmesh import (
    get_bmesh_emesh, get_object_bmesh, evict_object_bmesh,
    has_mirror_x, has_mirror_y, has_mirror_z,
    bmf_midpoint_radius, bme_other_bmf, bmf_is_quad, quad_bmf_opposite_bme,
    ensure_correct_normals,
    find_selected_cycle_or_path,
)
from ..common.maths import (
    bvec_to_point, point_to_bvec3,
    pt_x0, pt_y0, pt_z0,
    lerp, snap_plane_to_direction,
    arc_path_factors, path_facs_to_positions, project_to_path_fac, enforce_path_min_gap,
)
from ..common.accel import SourceMeshCache
from ..common.raycast import raycast_ray_valid_sources, nearest_point_valid_sources, raycast_multiple_hits
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.debug import debugger
from ...addon_common.terminal import term_printer
from ...addon_common.common.maths import Point, Plane
from ...addon_common.common.utils import iter_pairs
from ...addon_common.ext.circle_fit import hyperLSQ
from .path_placement import sample_curvature, place_ring_facs, SHARP_ANGLE

DEBUG_CREATE_OBJECTS = False     # For inspecting the cut path and plane. Currently only used for SDF method
DEBUG_SKIP_BRIDGE_SNAP = False   # Initial transform result before snapping
DEBUG_SKIP_REDISTRIBUTE = False  # Snapping result before any redistribution

DEBUG_PRINT_TIMINGS = False
DEBUG_PRINT_SNAP_PATH  = False   # How each vert ends up snapping to the cut path
DEBUG_PRINT_SPACING = False   # How the verts spread out from curvature and space evenly
DEBUG_PRINT_SDF_PATH = False  # SDF chord/path/refine/final-vert dump
SDF_DEBUG_OBJECT_NAMES = ('SDF_Debug_Grid', 'SDF_Debug_Path', 'SDF_Debug_Snapped', 'SDF_Debug_Chord', 'SDF_Debug_Refined', 'SDF_Debug_FinalVerts')


SPAN_COUNT_RANGE = (3, 500)  # Mirrors the min/max on the matching bpy props in contours.py
LOOP_COUNT_RANGE = (1, 20)

def clamp_span_count(count: float) -> int:
    lo, hi = SPAN_COUNT_RANGE
    return max(lo, min(hi, round(count)))

def clamp_loop_count(count: float) -> int:
    lo, hi = LOOP_COUNT_RANGE
    return max(lo, min(hi, round(count)))

def mean_world_edge_length(bmes, matrix_world) -> float:
    ''' Mean world-space length of the given edges; 0 when there are none. '''
    if not bmes: return 0.0
    return sum(
        ((matrix_world @ bme.verts[0].co) - (matrix_world @ bme.verts[1].co)).length
        for bme in bmes
    ) / len(bmes)

class Contours_Logic:
    matrix_world : Matrix | None
    matrix_world_inv : Matrix | None
    bm : BMesh | None
    em : Mesh | None

    hit : dict[str, ...]
    hits : list[dict[str, ...]]
    sdf_stroke_world_len : float
    plane : Plane
    plane_original : Plane
    circle_hit : tuple[float, ...]
    cut_orientation : str
    initial : bool

    process_source_method : str
    last_process_source_method : str | None
    fast_depth : int
    last_fast_depth : int | None
    sample_points : int
    last_sample_points : int | None
    fast_refine_steps : int
    last_fast_refine_steps : int | None
    sdf_refine_steps : int
    last_sdf_refine_steps : int | None
    skip_step_size : float
    last_skip_step_size : float | None
    sample_width : float
    last_sample_width : float | None
    sdf_grid_size : float
    last_sdf_grid_size : float | None
    sdf_subdivisions : int
    last_sdf_subdivisions : int | None
    sdf_extent_scale : float
    last_sdf_extent_scale : float | None
    last_cut_orientation : str | None

    action : Literal['Loop Cut', 'Strip Cut', 'Extrude Loop', 'Extrude Strip', 'New Loop', 'New Strip', '']
    show_span_count : bool
    span_count : int
    show_twist : bool
    twist : float
    show_loop_count : bool
    loop_count : int
    cyclic : bool
    flip_normals : bool
    curvature_bias : float
    space_evenly : float

    edge_ring : set[BMEdge] | None
    cyclic_ring : bool
    sel_path : list[BMEdge] | None
    sel_cyclic : bool | None
    bridge : bool | None

    points : list[Vector] | None
    plane_fit : Plane | None
    circle_fit : tuple[float, ...] | None
    path_length : float | None
    mirror_clipped_loop : bool | None

    def __init__(self, context:Context, hit:dict[str,...], plane:Plane, circle_points:list[Vector], span_count:int,
                 process_source_method:str, hits:list[dict[str, ...]], cut_orientation:str='stroke', fast_depth:int=1,
                 sample_points:int=50, fast_refine_steps:int=5, sdf_refine_steps:int=3, skip_step_size:float=0.5, sample_width:float=0.25,
                 sdf_grid_size:float=0.25, sdf_subdivisions:int=0, sdf_extent_scale:float=1.5,
                 curvature_bias:float=0.7, space_evenly:float=0.0,
                 span_insert_mode:str='FIXED', span_length:float=0.1,
                 sdf_stroke_world_len:float=0.0):
        self.hit = hit
        self.hits = hits
        self.sdf_stroke_world_len = sdf_stroke_world_len
        self.cut_orientation = cut_orientation
        self.last_cut_orientation = None
        self.plane_original = plane
        self.plane = snap_plane_to_direction(plane, hit, cut_orientation)
        self.circle_hit = hyperLSQ([list(self.plane.w2l_point(pt).xy) for pt in circle_points if pt])
        if not math.isfinite(self.circle_hit[0]) or not math.isfinite(self.circle_hit[1]):
            # fall back to the stroke hit projected onto the cut plane
            hit_local = self.plane.w2l_point(hit['co_world'])
            self.circle_hit = (hit_local.x, hit_local.y, 0.0, 0.0)
        self.process_source_method = process_source_method
        self.last_process_source_method = None
        self.fast_depth = fast_depth
        self.last_fast_depth = None
        self.sample_points = sample_points
        self.last_sample_points = None
        self.fast_refine_steps = fast_refine_steps
        self.last_fast_refine_steps = None
        self.sdf_refine_steps = sdf_refine_steps
        self.last_sdf_refine_steps = None
        self.skip_step_size = skip_step_size
        self.last_skip_step_size = None
        self.sample_width = sample_width
        self.last_sample_width = None
        self.sdf_grid_size = sdf_grid_size
        self.last_sdf_grid_size = None
        self.sdf_subdivisions = sdf_subdivisions
        self.last_sdf_subdivisions = None
        self.sdf_extent_scale = sdf_extent_scale
        self.last_sdf_extent_scale = None
        self.curvature_bias = curvature_bias
        self.space_evenly = space_evenly

        self.action = ''
        self.initial = True

        self.show_span_count = False
        self.span_count = span_count

        self.span_insert_mode = span_insert_mode
        self.span_length = span_length

        self.show_twist = False
        self.twist = 0

        self.show_loop_count = False
        self.loop_count = 1

        self.cyclic = False
        self.flip_normals = False
        self.bm, self.em = None, None
        self.matrix_world, self.matrix_world_inv = None, None

        self.edge_ring = None
        self.cyclic_ring = False
        self.sel_path = None
        self.sel_cyclic = None
        self.bridge = None
        self.points = None
        self.plane_fit = None
        self.circle_fit = None
        self.path_length = None
        self.mirror_clipped_loop = None
        self.ring_sharp_verts = set()
        self.mirror_threshold = 1e-4

    def update(self, context:Context):
        self.bm, self.em = get_bmesh_emesh(context)
        bmops.flush_selection(self.bm, self.em)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe() if self.matrix_world else None

        try:
            if not self.process_source(context): return
            self.process_target(context)
            self.find_boundary_for_bridging(context)
            self.insert(context)
        except Exception as e:
            print(f'Exception caught: {e}')
            debugger.print_exception()

        self.initial = False

    def release(self):
        """ Drop the BMesh working state to avoid stale references. """
        self.bm, self.em = None, None
        self.edge_ring = None
        self.sel_path = None
        self.bridge = None

    def process_source(self, context:Context) -> bool:
        # process source only once, unless settings have changed
        if (not self.initial and
            self.last_process_source_method == self.process_source_method and
            self.last_fast_depth == self.fast_depth and
            self.last_sample_points == self.sample_points and
            self.last_fast_refine_steps == self.fast_refine_steps and
            self.last_sdf_refine_steps == self.sdf_refine_steps and
            self.last_skip_step_size == self.skip_step_size and
            self.last_sample_width == self.sample_width and
            self.last_sdf_grid_size == self.sdf_grid_size and
            self.last_sdf_subdivisions == self.sdf_subdivisions and
            self.last_sdf_extent_scale == self.sdf_extent_scale and
            self.last_cut_orientation == self.cut_orientation
        ):
            # print(f'skipping re-processing source')
            return True
        self.last_process_source_method = self.process_source_method
        self.last_fast_depth = self.fast_depth
        self.last_sample_points = self.sample_points
        self.last_fast_refine_steps = self.fast_refine_steps
        self.last_sdf_refine_steps = self.sdf_refine_steps
        self.last_skip_step_size = self.skip_step_size
        self.last_sample_width = self.sample_width
        self.last_sdf_grid_size = self.sdf_grid_size
        self.last_sdf_subdivisions = self.sdf_subdivisions
        self.last_sdf_extent_scale = self.sdf_extent_scale
        self.last_cut_orientation = self.cut_orientation
        self.plane = snap_plane_to_direction(self.plane_original, self.hit, self.cut_orientation)

        match self.process_source_method:
            case 'fast':
                return self.process_source_fast(context)
            case 'skip':
                return self.process_source_skip(context)
            case 'walk':
                return self.process_source_walk(context)
            case 'sdf':
                return self.process_source_sdf(context)
            case _:
                assert False, f'Unhandled source processing method "{self.process_source_method}"'

    def process_target(self, context:Context):
        # did we hit current geometry and need to insert an edge loop?
        self.edge_ring = None
        self.cyclic_ring = False
        self.sel_path = None
        self.sel_cyclic = False
        self.bridge = None

        if not self.bm.verts:
            return
        if self.plane_fit is None:
            return

        M = self.matrix_world
        rgn, r3d = context.region, context.region_data

        #################################################################################
        # determine if cutting existing geometry by:
        # - find quad-only bmface that crosses the plane and is under mouse
        # - walk around geometry to find edges that should be cut
        hit_co3 = self.hit['co_local']
        hit_co2 = location_3d_to_region_2d(rgn, r3d, self.hit['co_world'])  # same as mouse unless view changes
        if hit_co2 is None:
            return

        inf = float('inf')
        plane_fit = self.plane_fit
        def distance_to_hit(bmf):
            if not bmf_is_quad(bmf): return inf
            center3, radius3 = bmf_midpoint_radius(bmf)
            dist3 = (hit_co3 - center3).length
            if dist3 > radius3: return inf
            center2 = location_3d_to_region_2d(rgn, r3d, M @ center3)
            if center2 is None:
                return inf
            return (hit_co2 - center2).length
        bmf = min(self.bm.faces, default=None, key=distance_to_hit)
        if bmf and math.isfinite(distance_to_hit(bmf)):
            # hit bmface!
            self.edge_ring = set()
            self.cyclic_ring = False
            first_attempt = True
            for bme in bmf.edges:
                if not plane_fit.bme_crosses(bme): continue  # ignore edges that do not cross plane
                pre_bmf = bmf
                while True:
                    if bme in self.edge_ring:
                        if first_attempt: self.cyclic_ring = True
                        break
                    self.edge_ring.add(bme)
                    next_bmf = bme_other_bmf(bme, pre_bmf)
                    if not next_bmf or not bmf_is_quad(next_bmf): break
                    bme = quad_bmf_opposite_bme(next_bmf, bme)
                    pre_bmf = next_bmf
                first_attempt = False
            if self.edge_ring:
                # update cyclic to match cut-into geometry
                # TODO: DO NOT OVERRIDE THIS HERE...
                self.cyclic = self.cyclic_ring

        # should we bridge with currently selected geometry?
        self.sel_path, self.sel_cyclic = find_selected_cycle_or_path(self.bm, hit_co3, only_boundary=False)
        self.bridge = bool(self.sel_path) and (self.cyclic == self.sel_cyclic)

    def find_boundary_for_bridging(self, context:Context):
        if not self.bridge or not self.sel_path:
            return

        # print(f'-----------------------------------------------------')

        sel_paths = []

        if any(len(bme.link_faces) == 0 for bme in self.sel_path):
            # all are wires; no walking needed
            return
        if all(len(bme.link_faces) == 1 for bme in self.sel_path):
            # print(f'selection is a boundary')
            sel_paths.append((self.sel_path, self.sel_cyclic))
        touched = set()
        working = set(self.sel_path)
        while working:
            # step out 1 ring
            # print(f'stepping out 1 ring {len(working)=}')
            nworking = set()
            for bme0 in working:
                if bme0 in touched: continue
                touched.add(bme0)
                for bmf in bme0.link_faces:
                    if not bmf_is_quad(bmf): continue
                    bme1 = quad_bmf_opposite_bme(bmf, bme0)
                    if bme1 in touched: continue
                    nworking.add(bme1)
            # crawl around boundary
            boundary = {
                bme for bme in nworking
                if bme.is_boundary
            }
            # print(f'{len(nworking)=} {len(boundary)=} {boundary=}')
            touched_boundary = set()
            for bme_init in boundary:
                if bme_init in touched_boundary: continue
                current = [bme_init]
                boundary_cyclic = False
                for i in range(2):
                    while True:
                        bme0 = current[-1]
                        if bme0 in touched_boundary:
                            boundary_cyclic = True
                            break
                        touched_boundary.add(bme0)
                        for bme1 in [bme for bmv in bme0.verts for bme in bmv.link_edges]:
                            if bme1 not in boundary: continue
                            if bme1 in touched_boundary: continue
                            current.append(bme1)
                            break
                    current.reverse()
                    if i == 0:
                        touched_boundary.remove(current[-1])  # remove so we can walk the other direction
                touched_boundary.add(bme_init)
                sel_paths.append((current, boundary_cyclic))
            working = nworking
        # print(f'found {len(sel_paths)} possible boundaries')
        # for p in sel_paths: print(f'- {len(p[0])=} {p}')
        best_path, best_cyclic, best_dist = None, None, float('inf')
        for (bmes, cyclic) in sel_paths:
            d = min(((self.hit['co_local'] - bmv.co).length for bme in bmes for bmv in bme.verts))
            if d > best_dist: continue
            best_path, best_cyclic, best_dist = bmes, cyclic, d
        self.sel_path, self.sel_cyclic = best_path, best_cyclic

    def insert(self, context: Context):
        if self.edge_ring:
            # cut in new edge loop
            self.insert_edge_ring(context)
        elif self.bridge:
            # extrude selection to cut
            self.insert_bridge(context)
        else:
            self.insert_new_cut(context)
        # The counts are settled, so hand AVERAGE back as FIXED and let the artist adjust the number.
        # LENGTH stays put so its distance remains live in the redo panel.
        if self.span_insert_mode == 'AVERAGE':
            self.span_insert_mode = 'FIXED'
        bmops.flush_selection(self.bm, self.em)

    def order_ring_verts(self, nbmvs_set: set) -> list:
        if not nbmvs_set: return []
        adj = {
            bmv: [bme.other_vert(bmv) for bme in bmv.link_edges if bme.other_vert(bmv) in nbmvs_set]
            for bmv in nbmvs_set
        }
        start = next((bmv for bmv in nbmvs_set if len(adj[bmv]) == 1), next(iter(nbmvs_set)))
        ordered = [start]
        visited = {start}
        while True:
            nexts = [v for v in adj[ordered[-1]] if v not in visited]
            if not nexts:
                break
            ordered.append(nexts[0])
            visited.add(nexts[0])
        return ordered

    def redistribute_ring(self, context: Context, new_bmvs: Sequence[BMVert]):
        '''Move ring verts along the cut path per the Contours settings. '''
        if not (self.points and self.path_length):
            return
        ordered_nbmvs = self.order_ring_verts(set(new_bmvs))
        n = len(ordered_nbmvs)
        if n < 2:
            return
        point_path_facs = arc_path_factors(self.points, self.cyclic)
        mx, my, mz = has_mirror_x(context), has_mirror_y(context), has_mirror_z(context)
        sym_verts = {
            bmv for bmv in ordered_nbmvs
            if (mx and abs(bmv.co.x) < self.mirror_threshold)
            or (my and abs(bmv.co.y) < self.mirror_threshold)
            or (mz and abs(bmv.co.z) < self.mirror_threshold)
        }

        base = [project_to_path_fac(Vector(v.co), self.points, self.cyclic, point_path_facs) for v in ordered_nbmvs]
        # Orient the ring forward along the path so base factors increase with ring index
        if self.cyclic:
            forward = sum((base[(i + 1) % n] - base[i]) % 1.0 for i in range(n)) <= n / 2
        else:
            forward = base[0] <= base[-1]
        if not forward:
            ordered_nbmvs.reverse()
            base.reverse()
        # The projection can occasionally land two verts out of order; nudge them apart so the gap logic holds
        base = enforce_path_min_gap(base, self.cyclic, 0.05 / n)

        sharp = {i for i, bmv in enumerate(ordered_nbmvs) if bmv in self.ring_sharp_verts}
        final = place_ring_facs(self.points, self.cyclic, base, self.path_length, self.curvature_bias, self.space_evenly,
                                sharp_verts=sharp)
        def moved(i):
            d = final[i] - base[i]
            if self.cyclic:
                d = (d + 0.5) % 1.0 - 0.5
            return abs(d) > 1e-9
        moved_idx = [i for i in range(n) if moved(i)]
        if not moved_idx:
            return
        target_pts = path_facs_to_positions(self.points, [final[i] for i in moved_idx], self.cyclic)

        # Move vert to target position and snap to source. Unmoved verts keep their projected coordinates.
        new_cos = {}
        for i, co in zip(moved_idx, target_pts):
            bmv = ordered_nbmvs[i]
            npt_world = point_to_bvec3(self.matrix_world @ bvec_to_point(Vector(co)))
            snapped = nearest_point_valid_sources(context, npt_world, world=True, respect_clip_planes=True)
            new_cos[bmv] = self.matrix_world_inv @ snapped if snapped is not None else Vector(co)
        for bmv, co in new_cos.items():
            bmv.co = co

        # Re pin to symmetry line
        for bmv in sym_verts:
            if mx: bmv.co.x = 0
            if my: bmv.co.y = 0
            if mz: bmv.co.z = 0


    def insert_edge_ring(self, context: Context):
        if self.edge_ring is None:
            return

        # USE SELECTION TO FIGURE OUT WHICH VERTS ARE NEW!
        # select only the edges on either side of cut
        bmeloops = {
            bme_
            for bme in self.edge_ring
            for bmf in bme.link_faces
            for bme_ in bmf.edges
        } - self.edge_ring
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmeloops)
        new_bm_elems = bmesh.ops.subdivide_edgering(self.bm, edges=list(self.edge_ring), cuts=1)['faces']
        # newly created verts will not be selected
        new_bmvs = list({ bmv for bmf in new_bm_elems for bmv in bmf.verts if not bmv.select })

        self.finish_edgering_bridge(context, new_bm_elems, new_bmvs)
        if DEBUG_SKIP_REDISTRIBUTE: return
        self.redistribute_ring(context, new_bmvs)
        self.bm.normal_update()

        self.action = 'Loop Cut' if self.cyclic else 'Strip Cut'
        self.show_twist = self.cyclic

    def insert_bridge(self, context:Context):
        orig_verts = {bv for bme in self.sel_path for bv in bme.verts}
        _M = self.matrix_world

        avg_ring_length = mean_world_edge_length(self.sel_path, _M)

        new_bm_elems = bmesh.ops.extrude_edge_only(self.bm, edges=self.sel_path)['geom']
        new_bmvs = [bmelem for bmelem in new_bm_elems if type(bmelem) is BMVert]

        self.finish_edgering_bridge(context, new_bm_elems, new_bmvs)
        if DEBUG_SKIP_REDISTRIBUTE: return
        self.redistribute_ring(context, new_bmvs)
        all_new_bmfs = [bmelem for bmelem in new_bm_elems if type(bmelem) is BMFace]

        new_verts_set = set(new_bmvs)
        lateral_edges = list({
            bme
            for bmv in new_bmvs
            for bme in bmv.link_edges
            if any(bv in orig_verts for bv in bme.verts)
        })
        # Mean extrusion length, measured before subdividing splits these edges
        max_correction = mean_world_edge_length(lateral_edges, _M)

        # Derive how many loops to cut so the new quads come out as even as possible.
        # Clamped to the loop_count property's range so the mesh and the redo panel can't diverge.
        match self.span_insert_mode:
            case 'AVERAGE' if avg_ring_length > 0:
                self.loop_count = clamp_loop_count(max_correction / avg_ring_length)
            case 'LENGTH' if self.span_length > 0:
                self.loop_count = clamp_loop_count(max_correction / self.span_length)

        if self.loop_count > 1 and lateral_edges:
            # Add more loop cuts to the bridge
            result = bmesh.ops.subdivide_edgering(
                self.bm,
                edges=lateral_edges,
                cuts=self.loop_count - 1,
            )
            intermediate_verts = list({
                bv
                for bmf in result['faces']
                for bv in bmf.verts
                if bv not in orig_verts and bv not in new_verts_set
            })
            self.bm.normal_update() # Important for per-vert raycasting below
            M_normal = self.matrix_world_inv.transposed()

            # Group intermediate verts by loop and find the loop plane.
            # Used to refine the loop if nearest surface snap is used.
            intermediate_set = set(intermediate_verts)
            loop_depth = {}
            frontier, seen, depth = list(orig_verts), set(orig_verts), 0
            while frontier:
                depth += 1
                next_frontier = []
                for bmv in frontier:
                    for bme in bmv.link_edges:
                        other = bme.other_vert(bmv)
                        if other in seen or other not in intermediate_set: continue
                        seen.add(other)
                        loop_depth[other] = depth
                        next_frontier.append(other)
                frontier = next_frontier

            verts_by_depth = defaultdict(list)
            for bmv, d in loop_depth.items():
                verts_by_depth[d].append(bmv)
            loop_planes = {
                d: Plane.fit_to_points([Point(bmv.co) for bmv in bmvs])
                for d, bmvs in verts_by_depth.items()
            }

            # Find final positions before moving any vert so loop normals stay accurate
            new_cos = {}
            for bmv in intermediate_verts:
                npt_world = point_to_bvec3(self.matrix_world @ bvec_to_point(bmv.co))
                # Nearest surface point
                npt_snapped = nearest_point_valid_sources(context, npt_world, world=True, respect_clip_planes=True)
                snapped_by_ray = False
                # Cast along the vert's normal
                vert_normal = (M_normal @ Vector((*bmv.normal, 0.0))).xyz
                if vert_normal.length_squared > 1e-12:
                    vert_normal.normalize()
                    # Winding is not settled until ensure_correct_normals below, so cast both ways
                    hits = []
                    for sign in (1, -1):
                        ray_dir = Vector((*(vert_normal * sign), 0.0))
                        hit = raycast_ray_valid_sources(context, (Vector((*npt_world, 1.0)), ray_dir), world=True, respect_clip_planes=True)
                        if hit is not None:
                            hits.append(hit)
                    if hits:
                        best = min(hits, key=lambda h: (h - npt_world).length)
                        # Reject a ray that grazed down a crevice and exited somewhere unrelated
                        if (best - npt_world).length <= max_correction:
                            npt_snapped = best
                            snapped_by_ray = True
                if not snapped_by_ray and npt_snapped is not None:
                    # Nearest point drags the vert along the surface, off its loop plane.
                    # Return it to the loop's plane then snap again.
                    plane = loop_planes.get(loop_depth.get(bmv))
                    if plane:
                        co_local = self.matrix_world_inv @ npt_snapped
                        lp = plane.w2l_point(co_local)
                        lp.z = 0
                        co_plane_world = point_to_bvec3(self.matrix_world @ bvec_to_point(Vector(plane.l2w_point(lp))))
                        resnapped = nearest_point_valid_sources(context, co_plane_world, world=True, respect_clip_planes=True)
                        # Only keep the second snap if it is a reasonable distance
                        if resnapped is not None and (resnapped - co_plane_world).length <= max_correction:
                            npt_snapped = resnapped
                if npt_snapped is not None:
                    new_cos[bmv] = self.matrix_world_inv @ npt_snapped
            # Apply all positions at once.
            for bmv, co in new_cos.items():
                bmv.co = co
            all_new_bmfs = result['faces']

        ensure_correct_normals(self.bm, all_new_bmfs, use_centroid=True, flip=self.flip_normals)
        self.action = 'Extrude Loop' if self.cyclic else 'Extrude Strip'
        self.show_twist = self.cyclic
        self.show_loop_count = True

    def finish_edgering_bridge(self, context:Context, new_bm_elems:Sequence[BMVert|BMEdge|BMFace], new_bmvs:Sequence[BMVert]):
        if self.points is None or self.plane_fit is None or self.circle_fit is None:
            return

        plane_fit = self.plane_fit
        circle_fit = self.circle_fit

        # compute useful statistics about newly created geometry
        npoints = [Point(bmv.co) for bmv in new_bmvs]
        try:
            if len(npoints) < 3:
                raise Exception(f'Not enough points to fit plane: {len(npoints)}')
            nplane_fit = Plane.fit_to_points(npoints)   # local space
            if not nplane_fit:
                nplane_fit = plane_fit
                ncircle_fit = circle_fit
            else:
                if plane_fit.n.dot(nplane_fit.n) < 0:
                    nplane_fit.n.negate()  # make sure both planes are oriented the same
                ncircle_fit = hyperLSQ([list(nplane_fit.w2l_point(pt).xy) for pt in npoints])
        except Exception as e:
            print(f'CONTOURS WARNING: failed to fit plane/circle for bridge: {e}')
            nplane_fit = plane_fit
            ncircle_fit = circle_fit

        # identify symmetry plane verts before any transformation so we can re-pin them after
        mx, my, mz = has_mirror_x(context), has_mirror_y(context), has_mirror_z(context)
        sym_verts = {
            bmv for bmv in new_bmvs
            if (mx and abs(bmv.co.x) < self.mirror_threshold)
            or (my and abs(bmv.co.y) < self.mirror_threshold)
            or (mz and abs(bmv.co.z) < self.mirror_threshold)
        }

        # Use world-space bbox center for both rings so T0 and T1 use the same center type.
        # Arithmetic mean drifts from the visual center on non-uniformly sampled rings.
        _M  = self.matrix_world
        _Mi = self.matrix_world_inv
        _ring_w = [_M @ Vector(bmv.co) for bmv in new_bmvs]
        _rnx = (max(p.x for p in _ring_w) + min(p.x for p in _ring_w)) * 0.5
        _rny = (max(p.y for p in _ring_w) + min(p.y for p in _ring_w)) * 0.5
        _rnz = (max(p.z for p in _ring_w) + min(p.z for p in _ring_w)) * 0.5
        center_new = _Mi @ Vector((_rnx, _rny, _rnz))
        _pts_w = [_M @ Vector(pt) for pt in self.points]
        _cx = (max(p.x for p in _pts_w) + min(p.x for p in _pts_w)) * 0.5
        _cy = (max(p.y for p in _pts_w) + min(p.y for p in _pts_w)) * 0.5
        _cz = (max(p.z for p in _pts_w) + min(p.z for p in _pts_w)) * 0.5
        center_src = _Mi @ Vector((_cx, _cy, _cz))

        # Calculate transform to roughly move new geometry to the cut
        T1 = Matrix.Translation(center_src) # translate ring center to path centroid
        RT = Matrix.Rotation(self.twist, 4, plane_fit.n) # user's twist
        nbmvs_set_s = set(new_bmvs)
        ring_perimeter = sum(
            bme.calc_length()
            for bmv in new_bmvs
            for bme in bmv.link_edges
            if bme.other_vert(bmv) in nbmvs_set_s
        ) / 2
        # Shear instead of rotate to avoid skewing!
        n1 = Vector(nplane_fit.n)
        n2 = Vector(plane_fit.n)
        cross = n1.cross(n2)
        dot_n1_n2 = n1.dot(n2)
        if cross.length > 1e-9 and abs(dot_n1_n2) > 1e-9:
            axis_vec    = cross.normalized()
            shear_dir   = n1.cross(axis_vec).normalized()
            shear_coeff = -(shear_dir.dot(n2)) / dot_n1_n2
            shear_vec   = shear_coeff * n1
            SH = Matrix.Identity(4)
            for row in range(3):
                for col in range(3):
                    SH[row][col] += shear_vec[row] * shear_dir[col]
        else:
            SH = Matrix.Identity(4)
        S  = Matrix.Scale(self.path_length / ring_perimeter, 4) if ring_perimeter > 1e-6 else Matrix.Scale(1.0, 4) # scale to match path radius
        T0 = Matrix.Translation(-center_new) # translate parent ring to origin
        xform = T1 @ RT @ SH @ S @ T0

        # Apply xform so that ring neighbor positions are fresh before normals are read
        nbmvs_set_snap = set(new_bmvs)
        for bmv in new_bmvs:
            bmv.co = xform @ bmv.co

        # Corners of the loop being extruded, measured before the projection flattens the ring onto the cut, so
        # redistribute_ring can pair them with the cut's corners even when the source shape is twisted
        self.ring_sharp_verts = set()
        for bmv in new_bmvs:
            nbrs = [e.other_vert(bmv) for e in bmv.link_edges if e.other_vert(bmv) in nbmvs_set_snap]
            if len(nbrs) != 2:
                continue
            a = bmv.co - nbrs[0].co
            b = nbrs[1].co - bmv.co
            if a.length < 1e-12 or b.length < 1e-12:
                continue
            if math.atan2(a.cross(b).length, a.dot(b)) >= math.radians(SHARP_ANGLE):
                self.ring_sharp_verts.add(bmv)

        if DEBUG_PRINT_SPACING:
            self.debug_print_bridge(center_new, center_src, plane_fit, ring_perimeter, dot_n1_n2, cross)

        if DEBUG_SKIP_BRIDGE_SNAP: return

        # Project each vert along its 2D normal onto the path.
        ON_PATH_THRESHOLD = 1e-6
        pts = self.points
        n_pts = len(pts)
        n_segs = n_pts if self.cyclic else n_pts - 1
        plane_n = n2  # cut plane normal (plane_fit.n)
        for bmv in new_bmvs:
            v = Vector(bmv.co)

            # Find nearest point on path
            nearest_pt = None
            nearest_dist = float('inf')
            for i in range(n_segs):
                a = Vector(pts[i])
                b = Vector(pts[(i + 1) % n_pts])
                ab = b - a
                ab_len2 = ab.length_squared
                if ab_len2 < 1e-10:
                    cand = a
                else:
                    f = max(0.0, min(1.0, ab.dot(v - a) / ab_len2))
                    cand = a + ab * f
                d = (cand - v).length
                if d < nearest_dist:
                    nearest_dist = d
                    nearest_pt   = cand

            # If already on the path, keep position and skip the raycast
            if nearest_dist < ON_PATH_THRESHOLD:
                if nearest_pt is not None:
                    bmv.co = nearest_pt
                if DEBUG_PRINT_SNAP_PATH:
                    self.debug_print_snap('ON_PATH', v, nearest_dist=nearest_dist)
                continue

            # Get ring tangent from the two adjacent loop verts
            ring_nbrs = [e.other_vert(bmv) for e in bmv.link_edges if e.other_vert(bmv) in nbmvs_set_snap]
            if len(ring_nbrs) >= 2:
                tangent = Vector(ring_nbrs[1].co) - Vector(ring_nbrs[0].co)
            elif len(ring_nbrs) == 1:
                tangent = Vector(ring_nbrs[0].co) - v
            else:
                tangent = None

            best_pt = None
            if tangent and tangent.length > 1e-9:
                ring_normal = plane_n.cross(tangent).normalized()

                # Check both directions and pick the shortest one
                best_dist = float('inf')
                for i in range(n_segs):
                    a = Vector(pts[i])
                    b = Vector(pts[(i + 1) % n_pts])
                    q = b - a
                    p = a - v  # vector from ray origin to segment start
                    # 3D perp-dot in the cut plane: (u × v) · plane_n
                    denom = ring_normal.cross(q).dot(plane_n)
                    if abs(denom) < 1e-9:
                        continue  # ray parallel to segment
                    s = -ring_normal.cross(p).dot(plane_n) / denom
                    if s < -1e-4 or s > 1.0 + 1e-4:
                        continue  # intersection outside segment extent
                    s = max(0.0, min(1.0, s))
                    snap_pt = a + s * q
                    dist = (snap_pt - v).length
                    if dist < best_dist:
                        best_dist = dist
                        best_pt = snap_pt

                # Test every path vert, otherwise floating point error makes the ray miss the correct segment
                for i in range(n_pts):
                    corner = Vector(pts[i])
                    to_corner = corner - v
                    t_along = to_corner.dot(ring_normal)
                    perp_dist = (to_corner - t_along * ring_normal).length
                    if perp_dist < ON_PATH_THRESHOLD * 100:
                        dist = to_corner.length
                        if dist < best_dist:
                            best_dist = dist
                            best_pt = corner

            # Fall back to nearest-point when the raycast is too far away.
            RAYCAST_NEAREST_FACTOR = 2.0

            use_ray = best_pt is not None and best_dist <= nearest_dist * RAYCAST_NEAREST_FACTOR
            if use_ray:
                bmv.co = best_pt
                if DEBUG_PRINT_SNAP_PATH:
                    self.debug_print_snap('RAYCAST', v, best_dist=best_dist, nearest_dist=nearest_dist, ring_nbrs=ring_nbrs, tangent=tangent, new_pos=Vector(bmv.co))
            elif nearest_pt is not None:
                # Fall back to nearest point if no ray hit or it hit too far away
                bmv.co = nearest_pt
                if DEBUG_PRINT_SNAP_PATH:
                    self.debug_print_snap('NEAREST_PT', v, best_pt=best_pt, best_dist=best_dist, nearest_dist=nearest_dist, nearest_factor=RAYCAST_NEAREST_FACTOR, tangent=tangent, new_pos=Vector(bmv.co))
            else:
                # World space snap as last resort
                npt_local = bvec_to_point(v)
                npt_world = point_to_bvec3(self.matrix_world @ npt_local)
                npt_world_snapped = nearest_point_valid_sources(context, npt_world, world=True, respect_clip_planes=True)
                npt_world_new = npt_world_snapped if npt_world_snapped else npt_world
                bmv.co = self.matrix_world_inv @ npt_world_new if npt_world_new is not None else npt_local
                if DEBUG_PRINT_SNAP_PATH:
                    self.debug_print_snap('WORLD_SNAP', v, new_pos=Vector(bmv.co))

        # re-pin any verts that were on a symmetry plane so twist can't move them off
        for bmv in sym_verts:
            if mx: bmv.co.x = 0
            if my: bmv.co.y = 0
            if mz: bmv.co.z = 0

        if not self.cyclic:
            # snap ends
            if self.edge_ring:
                bmv_ends = [bmv for bmv in new_bmvs if len(bmv.link_faces) == 2]
            else:
                bmv_ends = [bmv for bmv in new_bmvs if len(bmv.link_faces) == 1]

            if len(bmv_ends) != 2:
                print(f'CONTOURS WARNING: FOUND {len(bmv_ends)} ENDS ON NON-CYCLIC PATH!?')
            else:
                bmv0, bmv1 = bmv_ends
                co0, co1 = bmv0.co, bmv1.co
                pt0, pt1 = self.points[0], self.points[-1]
                if (co0 - pt0).length + (co1 - pt1).length < (co0 - pt1).length + (co1 - pt0).length:
                    bmv0.co, bmv1.co = pt0, pt1
                else:
                    bmv0.co, bmv1.co = pt1, pt0

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, new_bmvs)


    def insert_new_cut(self, context:Context):
        M, Mi = self.matrix_world, self.matrix_world_inv
        path_length = self.path_length

        if self.points is None or M is None or Mi is None or path_length is None:
            return

        if DEBUG_CREATE_OBJECTS:
            _debug_saved_hide = {}
            for _dname in SDF_DEBUG_OBJECT_NAMES:
                _dobj = bpy.data.objects.get(_dname)
                if _dobj is not None:
                    _debug_saved_hide[_dname] = _dobj.hide_viewport
                    _dobj.hide_viewport = True

        def _debug_restore_hide():
            if not DEBUG_CREATE_OBJECTS: return
            for _dname, _hide in _debug_saved_hide.items():
                _dobj = bpy.data.objects.get(_dname)
                if _dobj is not None:
                    _dobj.hide_viewport = _hide

        points : list[Vector] = []
        for pt in self.points:
            if points and (points[-1] - pt).length == 0: continue
            points += [pt]

        if self.cyclic and not self.mirror_clipped_loop and self.twist and path_length > 0:
            offset = (self.twist % (2 * math.pi)) / (2 * math.pi) * path_length
            acc = 0.0
            n = len(points)
            for i in range(n):
                pt0 = points[i]
                pt1 = points[(i + 1) % n]
                seg = (pt1 - pt0).length
                if acc + seg >= offset:
                    t = (offset - acc) / seg if seg > 0 else 0.0
                    new_start = pt0 + (pt1 - pt0) * t
                    points = [new_start] + points[i + 1:] + points[:i + 1]
                    break
                acc += seg

        if self.span_insert_mode == 'LENGTH' and self.span_length > 0:
            # Size the ring to a world space distance
            world_length = sum(
                ((M @ pt0) - (M @ pt1)).length
                for (pt0, pt1) in iter_pairs(points, self.cyclic)
            )
            # Written back so the redo panel and Ctrl+Scroll get a concrete count to work from,
            # clamped to the span_count property's range so they don't diverge.
            self.span_count = clamp_span_count(world_length / self.span_length)

        vertex_count = self.span_count if self.cyclic else self.span_count + 1
        if self.mirror_clipped_loop:
            vertex_count = vertex_count // 2 + 1 # update vert count when loop crosses mirror

        npts = sample_curvature(points, self.cyclic, vertex_count, path_length, self.curvature_bias, self.space_evenly)
        if not npts:
            print('CONTOURS: sample_curvature returned no points, skipping cut')
            _debug_restore_hide()
            return
        if len(npts) < vertex_count:
            print(f'CONTOURS: only {len(npts)}/{vertex_count} sample points. Ring may have wrong count')
            vertex_count = len(npts)
        npts = [
            Mi @ snapped if (snapped := nearest_point_valid_sources(context, M @ pt, world=True, respect_clip_planes=True)) is not None else pt
            for pt in npts
        ]

        # create geometry!
        new_bmvs = [ self.bm.verts.new(pt) for pt in npts[:vertex_count] ]
        bmes = [self.bm.edges.new((bmv0, bmv1)) for (bmv0, bmv1) in iter_pairs(new_bmvs, self.cyclic)]

        if not self.cyclic:
            # snap ends
            bmv_ends = [bmv for bmv in new_bmvs if len(bmv.link_edges) == 1]
            if len(bmv_ends) != 2:
                print(f'CONTOURS WARNING: FOUND {len(bmv_ends)} ENDS ON NON-CYCLIC PATH!?')
            else:
                bmv0, bmv1 = bmv_ends
                co0, co1 = bmv0.co, bmv1.co
                pt0, pt1 = points[0], points[-1]
                if (co0 - pt0).length + (co1 - pt1).length < (co0 - pt1).length + (co1 - pt0).length:
                    bmv0.co, bmv1.co = pt0, pt1
                else:
                    bmv0.co, bmv1.co = pt1, pt0

        if self.cyclic:
            self.action = 'New Loop'
        else:
            self.action = 'New Strip'
        self.show_span_count = True
        self.show_twist = self.cyclic

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, new_bmvs)

        if DEBUG_PRINT_SDF_PATH:
            print(f'CONTOURS DUMP: resulting vertices ({len(new_bmvs)} pts)')
            for _i, _bmv in enumerate(new_bmvs):
                _pw = M @ _bmv.co
                _lp = self.plane.w2l_point(_pw)
                print(f'  {_i:3d}  local=({_lp.x:.5f}, {_lp.y:.5f})  world=({_pw.x:.5f}, {_pw.y:.5f}, {_pw.z:.5f})')

        if DEBUG_CREATE_OBJECTS:
            # Final ring as committed to the mesh, after sample_curvature.
            _fm = bpy.data.meshes.new('SDF_Debug_FinalVerts')
            _bm_f = bmesh.new()
            _fverts = [_bm_f.verts.new(M @ bmv.co) for bmv in new_bmvs]
            _bm_f.verts.ensure_lookup_table()
            _n_f = len(_fverts)
            for _k in range(_n_f if self.cyclic else _n_f - 1):
                _bm_f.edges.new([_fverts[_k], _fverts[(_k + 1) % _n_f]])
            _bm_f.to_mesh(_fm)
            _bm_f.free()
            _fv_obj = bpy.data.objects.get('SDF_Debug_FinalVerts')
            if _fv_obj is not None:
                _old_fm = _fv_obj.data
                _fv_obj.data = _fm
                bpy.data.meshes.remove(_old_fm)
            else:
                # a fresh object defaults to visible; existing ones are restored below
                _fv_obj = bpy.data.objects.new('SDF_Debug_FinalVerts', _fm)
                bpy.context.scene.collection.objects.link(_fv_obj)
            _debug_restore_hide()


    #######################################################
    # different methods for processing source

    def refine_loop(self, context:Context, points_world:list, plane_normal_world:Vector, steps:int) -> list:
        '''Cut line surface refinement pass shared by Fast and SDF.'''
        plane_cut = self.plane

        def _on_plane(pt):
            lp = plane_cut.w2l_point(pt); lp.z = 0
            return Vector(plane_cut.l2w_point(lp))

        pts_w = [Vector(p) for p in points_world]

        # correct jagged path from SDF tracing before subdividing
        if self.process_source_method == 'sdf':
            for _ in range(steps):
                n_pts = len(pts_w)
                avg_seg = sum((pts_w[(i+1) % n_pts] - pts_w[i]).length for i in range(n_pts)) / max(1, n_pts)
                max_corr_sq = (avg_seg * 2.0) ** 2
                corrected = []
                for p in pts_w:
                    p_plane = _on_plane(p)
                    npt = nearest_point_valid_sources(context, p_plane, world=True, respect_clip_planes=False)
                    if npt is not None:
                        npt_plane = _on_plane(Vector(npt))
                        corrected.append(npt_plane if (npt_plane - p_plane).length_squared < max_corr_sq else p_plane)
                    else:
                        corrected.append(p_plane)
                pts_w = corrected

        # Subdivide the longest edges in the path (inherently the least accurate) and snap again
        for _ in range(steps):
            n_w = len(pts_w)
            lengths = [(pts_w[(i+1) % n_w] - pts_w[i]).length for i in range(n_w)]
            threshold = sorted(lengths)[int(0.75 * n_w)]
            new_pts_w = []
            for i in range(n_w):
                p0 = pts_w[i]
                p1 = pts_w[(i+1) % n_w]
                # Existing verts on the plane are left untouched.
                # Drifted verts are reprojected and re-snapped via nearest point
                if abs(plane_cut.w2l_point(p0).z) > 1e-6:
                    p0 = _on_plane(p0)
                    npt = nearest_point_valid_sources(context, p0, world=True, respect_clip_planes=False)
                    if npt is not None:
                        p0 = _on_plane(Vector(npt))
                new_pts_w.append(p0)
                if lengths[i] < threshold: continue
                m = _on_plane((p0 + p1) / 2)

                if self.process_source_method == 'sdf':
                    # Nearest-point avoids unstable 2D normals issues from the jagged grid boundary
                    npt = nearest_point_valid_sources(context, m, world=True, respect_clip_planes=False)
                    if npt is not None:
                        npt_plane = _on_plane(Vector(npt))
                        new_pts_w.append(npt_plane if (npt_plane - m).length_squared < (lengths[i] * 0.75) ** 2 else m)
                    else:
                        new_pts_w.append(m)
                else:
                    # For Fast: raycast since the 2D normals are already facing the proper direction
                    m_snapped = nearest_point_valid_sources(context, m, world=True, respect_clip_planes=False)
                    if m_snapped is not None and (Vector(m_snapped) - m).length < lengths[i] * 0.05:
                        new_pts_w.append(_on_plane(Vector(m_snapped)))
                        continue
                    seg = p1 - p0
                    inplane_n = plane_normal_world.cross(seg)
                    if inplane_n.length_squared < 1e-12:
                        new_pts_w.append(m)
                        continue
                    inplane_n.normalize()
                    nudge = max(1e-4, seg.length * 1e-3)
                    hit_a = raycast_ray_valid_sources(context, (m + inplane_n * nudge,  inplane_n),  world=True, respect_clip_planes=True)
                    hit_b = raycast_ray_valid_sources(context, (m - inplane_n * nudge, -inplane_n), world=True, respect_clip_planes=True)
                    candidates = []
                    for h in (hit_a, hit_b):
                        if h is None: continue
                        lp = plane_cut.w2l_point(h); lp.z = 0
                        candidates.append(Vector(plane_cut.l2w_point(lp)))
                    if candidates:
                        best = min(candidates, key=lambda h: (h - m).length_squared)
                        new_pts_w.append(best if (best - m).length_squared < (lengths[i] * 0.75) ** 2 else m)
                    else:
                        new_pts_w.append(m)
            pts_w = new_pts_w

        return pts_w

    def get_volume_center(self, context:Context, plane_cut) -> tuple[Vector, Vector]:
        '''Compute the plane-local and world-space center for the cut.'''
        center_plane = Vector((self.circle_hit[0], self.circle_hit[1], 0, 1))
        if self.fast_depth > 1:
            hit_world = self.hit['co_world']
            no_world = Vector(self.hit['no_world']).normalized()
            plane_n = Vector(plane_cut.n).normalized()
            # Project no_world onto the cut plane so the cast stays within the cross-section.
            inward = no_world - no_world.dot(plane_n) * plane_n
            inward.negate()
            if inward.length > 1e-6:
                n_inward = 2 * (self.fast_depth - 1) + 1
                inward_hits = raycast_multiple_hits(context, hit_world, inward.normalized(), n_inward)
                if inward_hits:
                    midpoint = (hit_world + inward_hits[-1]) / 2
                    midpoint_local = plane_cut.w2l_point(midpoint)
                    center_plane = Vector((midpoint_local.x, midpoint_local.y, 0, 1))
        center_world = plane_cut.l2w_point(center_plane)
        return center_plane, center_world

    def normalize_winding(self, points_world: list, plane_cut) -> list:
        '''Ensure the winding order of a world space loop is consistent with the cut plane normal.'''
        if len(points_world) <= 2:
            return points_world
        plane_n = Vector(plane_cut.l2w_direction(Vector((0, 0, 1))))
        comps = [abs(plane_n.x), abs(plane_n.y), abs(plane_n.z)]
        dom = comps.index(max(comps))
        want_ccw = (plane_n.x, plane_n.y, plane_n.z)[dom] > 0
        pts_local = [plane_cut.w2l_point(Vector(p)) for p in points_world]
        n_ring = len(pts_local)
        signed_area = sum(
            pts_local[i].x * pts_local[(i+1) % n_ring].y - pts_local[(i+1) % n_ring].x * pts_local[i].y
            for i in range(n_ring)
        ) / 2
        if (signed_area > 0) != want_ccw:
            return [points_world[0]] + list(reversed(points_world[1:]))
        return points_world

    def process_source_fast(self, context:Context) -> bool:
        if DEBUG_PRINT_TIMINGS: timers = [('start', time.perf_counter())]
        plane_cut = self.plane
        center_plane, center_world = self.get_volume_center(context, plane_cut)

        if DEBUG_PRINT_TIMINGS: timers.append(('center/depth', time.perf_counter()))
        nsamples = self.sample_points
        dirs_plane = [
            Vector((math.cos(2 * math.pi * d/nsamples), math.sin(2 * math.pi * d/nsamples), 0, 0))
            for d in range(nsamples)
        ]

        dirs_world = [ plane_cut.l2w_direction(dir_plane) for dir_plane in dirs_plane ]

        if self.fast_depth <= 1:
            rays_world = [ (center_world, dir_world) for dir_world in dirs_world ]
            points_world = [
                raycast_ray_valid_sources(context, ray_world, world=True, respect_clip_planes=True)
                for ray_world in rays_world
            ]
        else:
            # Pass through the first surfaces and use the next hit.
            # Depth = 2 on a solidified mesh skips the inner wall and lands on the outer wall.
            # Fall back to a shallower hit if the mesh has fewer surfaces than requested.
            points_world = []
            for dir_world in dirs_world:
                hits = raycast_multiple_hits(context, center_world, dir_world, 2 * (self.fast_depth - 1))
                points_world.append(hits[-1] if hits else None)

        points_world = [pt for pt in points_world if pt is not None]

        if DEBUG_PRINT_TIMINGS: timers.append((f'radial rays ({nsamples})', time.perf_counter()))
        points_world = self.normalize_winding(points_world, plane_cut)

        if self.fast_refine_steps > 0 and len(points_world) >= 3:
            plane_normal_world = Vector(plane_cut.l2w_direction(Vector((0, 0, 1))))
            points_world = self.refine_loop(context, points_world, plane_normal_world, self.fast_refine_steps)

        if DEBUG_PRINT_TIMINGS: timers.append((f'refinement ({self.fast_refine_steps} steps)', time.perf_counter()))
        points = [ self.matrix_world_inv @ pt_world for pt_world in points_world if pt_world ]
        cyclic = True
        mirror_clipped_loop = False

        ####################################################################################################
        # handle cutting across mirror planes

        points, mirror_clipped_loop = self.handle_mirrors(context, points)
        if mirror_clipped_loop: cyclic = False

        if len(points) < 3:
            print(f'CONTOURS: TOO FEW POINTS FOUND TO FIT PLANE')
            return False

        ####################################################################################################
        # compute useful statistics about points

        plane_fit = Plane.fit_to_points(points)
        assert plane_fit
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        if circle_fit[3] > circle_fit[2]:
            print(
                f'CONTOURS FAST: poor circle fit (sigma={circle_fit[3]:.4f} > ' +
                f'radius={circle_fit[2]:.4f}) — {len(points)} pts, depth={self.fast_depth}'
            )

        self.points = points                            # points where cut crosses source (target space)
        self.cyclic = cyclic                            # is cut cyclic (loop) or a strip?
        self.plane_fit = plane_fit                      # plane that fits cut points (target space)
        self.circle_fit = circle_fit                    # circle that fits points (plane_fit space)
        self.path_length = path_length                  # length of path of points (target space)
        self.mirror_clipped_loop = mirror_clipped_loop  # did cyclic loop cross mirror plane?

        if DEBUG_PRINT_TIMINGS:
            self.debug_print_timings(timers, f'FAST  depth={self.fast_depth}  samples={nsamples}  refine={self.fast_refine_steps}')
        return True

    def process_source_sdf(self, context:Context) -> bool:
        '''Build a coarse occupancy grid on the cut plane, trace the boundary, then snap and smooth that loop.'''
        if DEBUG_PRINT_TIMINGS: timers = [('start', time.perf_counter())]
        plane_cut = self.plane
        # Walk the occupancy grid outward from the center hitpoint
        hit_local = plane_cut.w2l_point(Vector(self.hit['co_world']))
        sx, sy = hit_local.x, hit_local.y  # seed = center of coarse cell (0, 0)

        GRID_SIZE_FACTOR = 1.0
        stroke_world_len = self.sdf_stroke_world_len
        if stroke_world_len < 1e-6:
            stroke_world_len = 2.0 * self.circle_hit[2]  # fallback: fitted diameter
        cell_size = self.sdf_grid_size * stroke_world_len * GRID_SIZE_FACTOR
        if not math.isfinite(cell_size) or cell_size < 1e-6:
            print('CONTOURS SDF: degenerate cell size, falling back to Fast')
            return self.process_source_fast(context)

        if DEBUG_PRINT_TIMINGS: timers.append(('cell size', time.perf_counter()))

        # Walk the coarse grid outward in all directions and test surface proximity
        base_radius = 0.5 * math.sqrt(2.0) * cell_size
        def coarse_near(di, dj):
            cx, cy = sx + di * cell_size, sy + dj * cell_size
            npt = nearest_point_valid_sources(context, plane_cut.l2w_point(Vector((cx, cy, 0))), world=True, respect_clip_planes=True)
            if npt is None: return False
            npt_local = plane_cut.w2l_point(Vector(npt))
            if abs(npt_local.z) >= base_radius: return False
            return math.hypot(npt_local.x - cx, npt_local.y - cy) < base_radius

        if not coarse_near(0, 0):
            print('CONTOURS SDF: seed cell missed the surface, falling back to Fast')
            return self.process_source_fast(context)

        NEIGHBORS_8 = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))
        max_cell_queries = 1_000_000
        band   = {(0, 0)}
        tested = {(0, 0)}
        stack  = [(0, 0)]
        total_cell_queries = 1
        grow_capped = False
        while stack:
            di, dj = stack.pop()
            for ddi, ddj in NEIGHBORS_8:
                nb = (di + ddi, dj + ddj)
                if nb in tested: continue
                total_cell_queries += 1
                if total_cell_queries > max_cell_queries:
                    grow_capped = True
                    break
                tested.add(nb)
                if coarse_near(*nb):
                    band.add(nb)
                    stack.append(nb)
            if grow_capped: break
        if grow_capped:
            print(f'CONTOURS SDF: region grow exceeded {max_cell_queries} queries, falling back to Fast')
            return self.process_source_fast(context)
        if len(band) < 3:
            print('CONTOURS SDF: region grow found too few cells, falling back to Fast')
            return self.process_source_fast(context)

        if DEBUG_PRINT_TIMINGS: timers.append((f'region grow ({len(band)} cells, {total_cell_queries} queries)', time.perf_counter()))
        # Pack the discovered band into the fixed grid the downstream expects, with a 1-cell empty
        # pad on every side so the exterior flood has a border ring of non-near cells.
        di_min, di_max = min(d[0] for d in band), max(d[0] for d in band)
        dj_min, dj_max = min(d[1] for d in band), max(d[1] for d in band)
        pad = 1
        res_x = (di_max - di_min + 1) + 2 * pad
        res_y = (dj_max - dj_min + 1) + 2 * pad
        fine_count: int = 3 ** max(0, int(self.sdf_subdivisions))
        RX, RY = res_x * fine_count, res_y * fine_count
        fcw = fch = cell_size / fine_count  # fine cell size
        # Origin chosen so classify_cell's coarse-block centers coincide with the grow's centers
        # (relies on fine_count being odd, which 3**k always is).
        xmin = sx + (di_min - pad - 0.5) * cell_size
        ymin = sy + (dj_min - pad - 0.5) * cell_size
        width, height = res_x * cell_size, res_y * cell_size

        # Mark cells near the surface
        near       = np.zeros((RX, RY), dtype=bool)
        block_size = np.full((RX, RY), fine_count, dtype=np.int16) # effective block size per fine cell (for debug)

        def classify_cell(fi, fj, radius):
            cx = xmin + (fi + 0.5) * fcw
            cy = ymin + (fj + 0.5) * fch
            c = plane_cut.l2w_point(Vector((cx, cy, 0)))
            npt = nearest_point_valid_sources(context, c, world=True, respect_clip_planes=True)
            if npt is None: return False
            npt_local = plane_cut.w2l_point(Vector(npt))
            if abs(npt_local.z) >= radius: return False
            return math.hypot(npt_local.x - cx, npt_local.y - cy) < radius

        def fill_block_uniform(fi0, fj0, sz, n_val):
            near[fi0:fi0 + sz, fj0:fj0 + sz] = n_val
            block_size[fi0:fi0 + sz, fj0:fj0 + sz] = sz

        # Create the initial grid from the coarse cells
        for (di, dj) in band:
            bi, bj = (di - di_min + pad), (dj - dj_min + pad)
            fill_block_uniform(bi * fine_count, bj * fine_count, fine_count, True)

        if DEBUG_PRINT_TIMINGS: timers.append((f'grid pack ({RX}x{RY} cells, {res_x}x{res_y} coarse, fine_count={fine_count})', time.perf_counter()))
        # Iteratively refine by subdividing hit cells and having each smaller cell search again
        cur_size, cur_radius = fine_count, base_radius
        for subdiv_level in range(self.sdf_subdivisions):
            if cur_size < 3: break
            sub_size   = cur_size // 3
            sub_radius = cur_radius / 3.0
            center_off = cur_size // 2
            fi_centers = np.arange(center_off, RX, cur_size, dtype=np.int32)
            fj_centers = np.arange(center_off, RY, cur_size, dtype=np.int32)
            center_block_size = block_size[np.ix_(fi_centers, fj_centers)]
            center_near = near[np.ix_(fi_centers, fj_centers)]
            bi_idx, bj_idx = np.nonzero((center_block_size == cur_size) & center_near)
            to_refine = [
                (int(fi_centers[i] - center_off), int(fj_centers[j] - center_off))
                for i, j in zip(bi_idx, bj_idx)
            ]
            if subdiv_level > 1 and total_cell_queries + len(to_refine) * 9 > max_cell_queries:
                print(f'CONTOURS SDF: pixel refinement capped (would exceed {max_cell_queries} cell queries)')
                break
            total_cell_queries += len(to_refine) * 9
            for fi0, fj0 in to_refine:
                for di in range(3):
                    for dj in range(3):
                        sfi0, sfj0 = fi0 + di * sub_size, fj0 + dj * sub_size
                        n_ = classify_cell(sfi0 + sub_size // 2, sfj0 + sub_size // 2, sub_radius)
                        fill_block_uniform(sfi0, sfj0, sub_size, n_)
            cur_size, cur_radius = sub_size, sub_radius

        if DEBUG_PRINT_TIMINGS: timers.append((f'grid classify ({RX}x{RY} cells, {res_x}x{res_y} coarse, fine_count={fine_count})', time.perf_counter()))
        # Create solid outlines to trace
        exterior = np.zeros((RX, RY), dtype=bool)
        empty = ~near
        stack = []
        for i in np.flatnonzero(empty[:, 0]):
            i = int(i)
            if not exterior[i, 0]:
                exterior[i, 0] = True
                stack.append((i, 0))
        for i in np.flatnonzero(empty[:, RY - 1]):
            i = int(i)
            if not exterior[i, RY - 1]:
                exterior[i, RY - 1] = True
                stack.append((i, RY - 1))
        for j in np.flatnonzero(empty[0, :]):
            j = int(j)
            if not exterior[0, j]:
                exterior[0, j] = True
                stack.append((0, j))
        for j in np.flatnonzero(empty[RX - 1, :]):
            j = int(j)
            if not exterior[RX - 1, j]:
                exterior[RX - 1, j] = True
                stack.append((RX - 1, j))
        while stack:
            i, j = stack.pop()
            ni = i + 1
            if ni < RX and not exterior[ni, j] and empty[ni, j]:
                exterior[ni, j] = True
                stack.append((ni, j))
            ni = i - 1
            if ni >= 0 and not exterior[ni, j] and empty[ni, j]:
                exterior[ni, j] = True
                stack.append((ni, j))
            nj = j + 1
            if nj < RY and not exterior[i, nj] and empty[i, nj]:
                exterior[i, nj] = True
                stack.append((i, nj))
            nj = j - 1
            if nj >= 0 and not exterior[i, nj] and empty[i, nj]:
                exterior[i, nj] = True
                stack.append((i, nj))
        solid = ~exterior

        # Isolate shape containing the original surface hit
        hi = int(np.clip((hit_local.x - xmin) / fcw, 0, RX - 1))
        hj = int(np.clip((hit_local.y - ymin) / fch, 0, RY - 1))
        if not solid[hi, hj]:
            idx = np.argwhere(solid)
            if idx.size == 0:
                print('CONTOURS SDF: no hit cells found, falling back to Fast')
                return self.process_source_fast(context)
            d2 = (idx[:, 0] - hi) ** 2 + (idx[:, 1] - hj) ** 2
            hi, hj = (int(v) for v in idx[np.argmin(d2)])

        blob = np.zeros((RX, RY), dtype=bool)
        stack = [(hi, hj)]; blob[hi, hj] = True
        touches_border = False
        while stack:
            i, j = stack.pop()
            if i == 0 or j == 0 or i == RX - 1 or j == RY - 1:
                touches_border = True
            ni = i + 1
            if ni < RX and not blob[ni, j] and solid[ni, j]:
                blob[ni, j] = True
                stack.append((ni, j))
            ni = i - 1
            if ni >= 0 and not blob[ni, j] and solid[ni, j]:
                blob[ni, j] = True
                stack.append((ni, j))
            nj = j + 1
            if nj < RY and not blob[i, nj] and solid[i, nj]:
                blob[i, nj] = True
                stack.append((i, nj))
            nj = j - 1
            if nj >= 0 and not blob[i, nj] and solid[i, nj]:
                blob[i, nj] = True
                stack.append((i, nj))

        # Trace the outer boundary as an ordered loop of lattice corners
        blob_pad = np.pad(blob, ((1, 1), (1, 1)), mode='constant', constant_values=False)

        def boundary_dirs(cx, cy):
            # Use a padded blob mask so corner adjacency lookups never need bounds checks.
            px, py = cx + 1, cy + 1
            sw, se = bool(blob_pad[px - 1, py - 1]), bool(blob_pad[px, py - 1])
            nw, ne = bool(blob_pad[px - 1, py]),     bool(blob_pad[px, py])
            ds = []
            if nw != ne: ds.append((0, 1))    # N
            if sw != se: ds.append((0, -1))   # S
            if se != ne: ds.append((1, 0))    # E
            if sw != nw: ds.append((-1, 0))   # W
            return ds
        right_turn = {(0,1):(1,0), (1,0):(0,-1), (0,-1):(-1,0), (-1,0):(0,1)}

        start_flat = np.flatnonzero(blob)
        if start_flat.size == 0:
            print('CONTOURS SDF: empty blob, falling back to Fast')
            return self.process_source_fast(context)
        start = tuple(int(v) for v in np.unravel_index(start_flat[0], blob.shape))  # leftmost-lowest blob cell -> its lower-left corner is on the boundary
        bdirs = boundary_dirs(*start)
        if not bdirs:
            print('CONTOURS SDF: degenerate boundary, falling back to Fast')
            return self.process_source_fast(context)
        cur_dir = (0, 1) if (0, 1) in bdirs else bdirs[0]
        corners = []
        P = start
        max_steps = 4 * (RX + 1) * (RY + 1) + 16
        for _ in range(max_steps):
            corners.append(P)
            P = (P[0] + cur_dir[0], P[1] + cur_dir[1])
            if P == start:
                break
            # Grid edge reached, break so the search doesn't bounce back
            if P[0] == 0 or P[0] == RX or P[1] == 0 or P[1] == RY:
                corners.append(P)
                break
            bdirs = boundary_dirs(*P)
            rev = (-cur_dir[0], -cur_dir[1])
            cands = [d for d in bdirs if d != rev]
            if not cands:
                break
            if len(cands) == 1:
                cur_dir = cands[0]
            else:
                rt = right_turn[cur_dir] # consistent turn keeps to one side
                cur_dir = rt if rt in cands else cands[0]

        if DEBUG_PRINT_TIMINGS: timers.append((f'boundary march ({len(corners)} corners)', time.perf_counter()))
        if DEBUG_CREATE_OBJECTS:
            _raw_corners = list(corners)  # save full staircase before downsample for debug path
            _debug_saved_hide = {}
            for _dname in SDF_DEBUG_OBJECT_NAMES:
                _dobj = bpy.data.objects.get(_dname)
                if _dobj is not None:
                    _debug_saved_hide[_dname] = _dobj.hide_viewport
                    _dobj.hide_viewport = True # Makes sure they don't get snapped to

            def _update_debug_object(name, new_mesh):
                obj = bpy.data.objects.get(name)
                if obj is not None:
                    old_mesh = obj.data
                    obj.data = new_mesh
                    bpy.data.meshes.remove(old_mesh)
                    obj.hide_viewport = _debug_saved_hide.get(name, False)
                else:
                    obj = bpy.data.objects.new(name, new_mesh)
                    bpy.context.scene.collection.objects.link(obj)

        # Downsample the staircase to avoid hundreds of zig-zag steps
        target_count = max(16, 4 * (res_x + res_y))
        if len(corners) > target_count:
            step = len(corners) / target_count
            idx = np.rint(np.arange(target_count, dtype=np.float64) * step).astype(np.int32) % len(corners)
            corners = [corners[int(i)] for i in idx]

        points_world = [
            plane_cut.l2w_point(Vector((xmin + cx * fcw, ymin + cy * fch, 0)))
            for (cx, cy) in corners
        ]

        # Snap each boundary point to the nearest surface point
        plane_normal_world = Vector(plane_cut.l2w_direction(Vector((0, 0, 1))))
        snapped = []
        for pw in points_world:
            p = Vector(pw)
            npt = nearest_point_valid_sources(context, p, world=True, respect_clip_planes=False)
            snapped.append(Vector(npt) if npt is not None else p)
        points_world = snapped

        # drop coincident neighbors as the staircase + snapping can collapse points together
        ts = context.scene.tool_settings
        merge_dist = ts.double_threshold if ts.use_mesh_automerge else 1e-6
        merge_dist_sq = merge_dist * merge_dist
        deduped = []
        for p in points_world:
            if not deduped or (p - deduped[-1]).length_squared > merge_dist_sq:
                deduped.append(p)
        if len(deduped) >= 2 and (deduped[0] - deduped[-1]).length_squared <= merge_dist_sq:
            deduped.pop()
        points_world = deduped
        if len(points_world) < 3:
            print('CONTOURS SDF: too few points after snapping, falling back to Fast')
            return self.process_source_fast(context)

        if DEBUG_PRINT_TIMINGS: timers.append((f'snap ({len(points_world)} pts)', time.perf_counter()))

        if DEBUG_CREATE_OBJECTS or DEBUG_PRINT_SDF_PATH:
            # Initial RDP chord: the farthest-apart anchor pair before refining
            _n_c = len(points_world)
            if not touches_border and _n_c >= 2:
                _centroid = Vector((0.0, 0.0, 0.0))
                for _p in points_world: _centroid += Vector(_p)
                _centroid /= _n_c
                _i0 = max(range(_n_c), key=lambda i: (Vector(points_world[i]) - _centroid).length_squared)
                _i1 = max(range(_n_c), key=lambda i: (Vector(points_world[i]) - Vector(points_world[_i0])).length_squared)
            else:
                _i0, _i1 = 0, _n_c - 1

        if DEBUG_PRINT_SDF_PATH:
            def _dump_points(label, pts):
                print(f'CONTOURS SDF DUMP: {label} ({len(pts)} pts)')
                for _i, _p in enumerate(pts):
                    _lp = plane_cut.w2l_point(Vector(_p))
                    print(f'  {_i:3d}  local=({_lp.x:.5f}, {_lp.y:.5f})  world=({_p[0]:.5f}, {_p[1]:.5f}, {_p[2]:.5f})')
            _dump_points('initial path', points_world)
            print(f'CONTOURS SDF DUMP: initial chord  i0={_i0}  i1={_i1}')

        if DEBUG_CREATE_OBJECTS:
            # Post-snap / pre-refinement path — every point here should lie exactly on the surface.
            _sm = bpy.data.meshes.new('SDF_Debug_Snapped')
            _bm_s = bmesh.new()
            _sverts = [_bm_s.verts.new(Vector(p)) for p in points_world]
            _bm_s.verts.ensure_lookup_table()
            _n_s = len(_sverts)
            for _k in range(_n_s if not touches_border else _n_s - 1):
                _bm_s.edges.new([_sverts[_k], _sverts[(_k + 1) % _n_s]])
            _bm_s.to_mesh(_sm)
            _bm_s.free()
            _update_debug_object('SDF_Debug_Snapped', _sm)

            _cm = bpy.data.meshes.new('SDF_Debug_Chord')
            _bm_c = bmesh.new()
            _cv0 = _bm_c.verts.new(Vector(points_world[_i0]))
            _cv1 = _bm_c.verts.new(Vector(points_world[_i1]))
            _bm_c.edges.new([_cv0, _cv1])
            _bm_c.to_mesh(_cm)
            _bm_c.free()
            _update_debug_object('SDF_Debug_Chord', _cm)

            _gm = bpy.data.meshes.new('SDF_Debug_Grid')
            _bm = bmesh.new()
            _emitted = np.zeros((RX, RY), dtype=bool)
            for _fi in range(RX):
                for _fj in range(RY):
                    if _emitted[_fi, _fj]: continue
                    _sz = int(block_size[_fi, _fj])
                    # clamp so blocks that reach the grid edge don't go OOB
                    _sz_x = min(_sz, RX - _fi)
                    _sz_y = min(_sz, RY - _fj)
                    # mark emitted first so empty coarse blocks are skipped in one shot
                    for _dfi in range(_sz_x):
                        for _dfj in range(_sz_y):
                            _emitted[_fi + _dfi, _fj + _dfj] = True
                    _cx, _cy = _fi + _sz_x // 2, _fj + _sz_y // 2
                    if _sz >= fine_count and not near[_cx, _cy]:
                        # coarse empty block — only show if the grow actually tested it
                        _di = (_fi // fine_count) + di_min - pad
                        _dj = (_fj // fine_count) + dj_min - pad
                        if (_di, _dj) not in tested:
                            continue
                    _v0 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + _fi           * fcw, ymin + _fj           * fch, 0))))
                    _v1 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + (_fi + _sz_x) * fcw, ymin + _fj           * fch, 0))))
                    _v2 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + (_fi + _sz_x) * fcw, ymin + (_fj + _sz_y) * fch, 0))))
                    _v3 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + _fi           * fcw, ymin + (_fj + _sz_y) * fch, 0))))
                    _bm.faces.new([_v0, _v1, _v2, _v3]).select = bool(near[_cx, _cy])
            _bm.to_mesh(_gm)
            _bm.free()
            _update_debug_object('SDF_Debug_Grid', _gm)

            # Raw traced path mesh: full pre-downsample staircase corners, edges connecting them.
            _raw_pts = [
                plane_cut.l2w_point(Vector((xmin + cx * fcw, ymin + cy * fch, 0)))
                for (cx, cy) in _raw_corners
            ]
            _pm = bpy.data.meshes.new('SDF_Debug_Path')
            _bm2 = bmesh.new()
            _pverts = [_bm2.verts.new(_p) for _p in _raw_pts]
            _bm2.verts.ensure_lookup_table()
            for _k in range(len(_pverts)):
                _bm2.edges.new([_pverts[_k], _pverts[(_k + 1) % len(_pverts)]])
            _bm2.to_mesh(_pm)
            _bm2.free()
            _update_debug_object('SDF_Debug_Path', _pm)
            # ---- END DEBUG ----

        points_world = self.normalize_winding(points_world, plane_cut)

        if self.sdf_refine_steps > 0:
            points_world = self.refine_loop(context, points_world, plane_normal_world, self.sdf_refine_steps)

        if DEBUG_PRINT_TIMINGS: timers.append((f'refinement ({self.sdf_refine_steps} steps)', time.perf_counter()))
        if DEBUG_PRINT_SDF_PATH:
            _dump_points('refined path', points_world)
        if DEBUG_CREATE_OBJECTS and len(points_world) >= 2:
            _rm = bpy.data.meshes.new('SDF_Debug_Refined')
            _bm_r = bmesh.new()
            _rverts = [_bm_r.verts.new(Vector(p)) for p in points_world]
            _bm_r.verts.ensure_lookup_table()
            _n_r = len(_rverts)
            for _k in range(_n_r if not touches_border else _n_r - 1):
                _bm_r.edges.new([_rverts[_k], _rverts[(_k + 1) % _n_r]])
            _bm_r.to_mesh(_rm)
            _bm_r.free()
            _update_debug_object('SDF_Debug_Refined', _rm)
        if DEBUG_CREATE_OBJECTS:
            # FinalVerts isn't rebuilt in this pass, so _update_debug_object never unhides it
            _fv = bpy.data.objects.get('SDF_Debug_FinalVerts')
            if _fv is not None:
                _fv.hide_viewport = _debug_saved_hide.get('SDF_Debug_FinalVerts', False)

        points = [ self.matrix_world_inv @ pt_world for pt_world in points_world if pt_world ]
        cyclic = not touches_border

        points, mirror_clipped_loop = self.handle_mirrors(context, points)
        if mirror_clipped_loop: cyclic = False

        if len(points) < 3:
            print('CONTOURS SDF: too few points found to fit plane')
            return False

        plane_fit = Plane.fit_to_points(points)
        assert plane_fit
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        if circle_fit[3] > circle_fit[2]:
            print(
                f'CONTOURS SDF: poor circle fit (sigma={circle_fit[3]:.4f} > radius={circle_fit[2]:.4f}) — ' +
                f'{len(points)} pts, grid={res_x}x{res_y}'
            )

        self.points = points
        self.cyclic = cyclic
        self.plane_fit = plane_fit
        self.circle_fit = circle_fit
        self.path_length = path_length
        self.mirror_clipped_loop = mirror_clipped_loop

        if DEBUG_PRINT_TIMINGS:
            self.debug_print_timings(timers, f'SDF  grid={res_x}x{res_y}  fine_count={fine_count}  refine={self.sdf_refine_steps}')
        return True

    def process_source_skip(self, context:Context) -> bool:
        plane_cut = self.plane

        pt = self.hit['co_world']
        pt0, pt1 = self.hits[0]['co_world'], self.hits[-1]['co_world']
        dist = ((pt - pt0).length + (pt - pt1).length) / 4 * self.skip_step_size

        init_step = pt1 - pt # pt1 = hits[-1] is the farthest positive hit
        if init_step.length_squared < 1e-12:
            print('CONTOURS SKIP: degenerate initial direction')
            return False
        direction = init_step.normalized()
        pt_start = pt
        dist_pre = 0

        points = [pt]
        has_shrunk = False
        for i in range(10000):
            # print(f'{pt=} {direction=}')
            pt_next = pt + direction * dist
            for _ in range(10):
                snapped = nearest_point_valid_sources(context, pt_next, world=True, respect_clip_planes=True)
                if snapped is None: break
                pt_next = snapped
                pt_next = plane_cut.w2l_point(pt_next)
                pt_next.z = 0
                pt_next = Vector(plane_cut.l2w_point(pt_next))
            dist_next = (pt_next - pt_start).length
            if dist_next < dist_pre:
                has_shrunk = True
            elif has_shrunk:
                if dist_next > dist * 4:
                    has_shrunk = False  # false alarm, still far from start, keep walking
                else:
                    print(f'WRAPPED AFTER {i}!')
                    break
            step = pt_next - pt
            if step.length_squared < 1e-12:
                print(f'CONTOURS SKIP: stalled at step {i}')
                return False
            points += [pt_next]
            direction = step.normalized()
            # print(f'{pt=} {pt_next=} {direction=}')
            pt = pt_next
            dist_pre = dist_next
        else:
            print('CONTOURS SKIP: did not wrap after 10000 steps. Gah!')
            return False

        cyclic = True
        mirror_clipped_loop = False

        ####################################################################################################
        # handle cutting across mirror planes

        points = [self.matrix_world_inv @ pt for pt in points]
        points, mirror_clipped_loop = self.handle_mirrors(context, points)
        if mirror_clipped_loop: cyclic = False

        if len(points) < 3:
            print(f'CONTOURS: TOO FEW POINTS FOUND TO FIT PLANE')
            return False


        ####################################################################################################
        # compute useful statistics about points
        plane_fit = Plane.fit_to_points(points)
        assert plane_fit
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        self.points = points
        self.cyclic = cyclic
        self.plane_fit = plane_fit                      # plane that fits cut points (target space)
        self.circle_fit = circle_fit                    # circle that fits points (plane_fit space)
        self.path_length = path_length                  # length of path of points (target space)
        self.mirror_clipped_loop = mirror_clipped_loop  # did cyclic loop cross mirror plane?

        return True

    def walk_bmesh(self, context:Context, timers:list) -> 'tuple[list[Vector], bool, list[Vector], str] | bool':
        ''' Graph walk using BMesh objects. Returns (points, cyclic, end_pts, timing_title) or False. '''
        plane_cut  = self.plane
        hit_obj    = self.hit['object']
        M          = hit_obj.matrix_world
        hit_bm     = get_object_bmesh(hit_obj)
        face_index = self.hit['face_index']
        if face_index >= len(hit_bm.faces):
            # cache is stale, source mesh changed face count
            evict_object_bmesh(hit_obj)
            hit_bm = get_object_bmesh(hit_obj)
        if face_index >= len(hit_bm.faces):
            print(f'CONTOURS: face_index {face_index} out of range for mesh with {len(hit_bm.faces)} faces')
            return False
        hit_bmf = hit_bm.faces[face_index]

        # TODO: walk from hit_bmf to find bmf that crosses plane_cut


        ####################################################################################################
        # walk hit object to find all geometry connected to hit_bmf that intersects cut plane
        # note: this will stop at holes that intersect the cut plane (will _not_ walk around them)

        def point_plane_signed_dist(pt : Vector) -> float:
            return plane_cut.signed_distance_to(pt)
        def bmv_plane_signed_dist(bmv:BMVert) -> float:
            return point_plane_signed_dist(M @ bmv.co)
        def bmv_intersect_plane(bmv : BMVert) -> Vector|None:
            if not isclose(bmv_plane_signed_dist(bmv), 0):
                return None
            return M @ bmv.co
        def bme_intersect_plane(bme : BMEdge) -> Vector|None:
            co0, co1 = ((M @ bmv.co) for bmv in bme.verts)
            s0, s1 = point_plane_signed_dist(co0), point_plane_signed_dist(co1)
            if (s0 <= 0 and s1 <= 0) or (s0 >= 0 and s1 >= 0):
                return None
            return co0 + (co1 - co0) * (s0 / (s0 - s1))
        def intersect_plane(bmelem : BMVert|BMEdge) -> Vector|None:
            if isinstance(bmelem, BMVert):
                return bmv_intersect_plane(bmelem)
            if isinstance(bmelem, BMEdge):
                return bme_intersect_plane(bmelem)
            assert False, f'Unexpected type {type(bmelem)} ({bmelem})'

        bmf_graph : dict[BMFace, set[BMFace]] = {}
        bmf_intersections : dict[BMFace, dict[BMVert|BMEdge|BMFace, Vector]] = defaultdict(dict)
        working : set[BMFace] = { hit_bmf }
        while working:
            bmf = working.pop()
            if bmf in bmf_graph:
                # already processed
                continue
            bmf_graph[bmf] = set()
            for bmelem in chain(bmf.verts, bmf.edges):
                co = intersect_plane(bmelem)
                if not co:
                    continue
                bmfs = set(bmelem.link_faces) - { bmf }
                working |= bmfs
                bmf_graph[bmf] |= bmfs
                bmf_intersections[bmf][bmelem] = co
                for bmf_ in bmfs:
                    bmf_intersections[bmf][bmf_] = co
                    bmf_intersections[bmf_][bmf] = co

        if DEBUG_PRINT_TIMINGS: timers.append((f'face graph ({len(bmf_graph)} faces)', time.perf_counter()))
        ####################################################################################################
        # find longest cycle or path in bmf_graph

        def find_cycle_or_path() -> tuple[list[BMFace], bool]:
            longest_path : list[BMFace] = []
            longest_cycle : list[BMFace] = []

            start_bmfs : set[BMFace] = {
                bmf for bmf in bmf_intersections
                if any(
                    (type(bmelem) is BMVert) or (type(bmelem) is BMEdge and len(bmelem.link_faces) == 1)
                    for bmelem in bmf_intersections[bmf]
                )
            }
            if not start_bmfs:
                start_bmfs = set(bmf_graph.keys())

            for start_bmf in start_bmfs:
                working : list[tuple[BMFace, Iterator[dict[BMFace, set[BMFace]]]]] = [(start_bmf, iter(bmf_graph[start_bmf]))]
                touched : set[BMFace] = { start_bmf }
                # limiting the number of finds we search for to prevent really long searches!
                # see https://github.com/CGCookie/retopoflow/issues/1773
                limit_finds = 10

                while working and limit_finds > 0:
                    cur_bmf, cur_iter = working[-1]
                    next_bmf = next(cur_iter, None)

                    if not next_bmf:
                        if len(working) > len(longest_path):
                            # found new longest path!
                            longest_path = [bmf for (bmf, _) in working]

                        working.pop()
                        touched.remove(cur_bmf)
                        limit_finds -= 1
                        continue

                    if next_bmf in touched:
                        # already in path/cycle
                        if next_bmf == start_bmf and len(working) > 2 and len(working) > len(longest_cycle):
                            # found new longest cycle!
                            longest_cycle = [bmf for (bmf, _) in working]
                        continue

                    touched.add(next_bmf)
                    working.append((next_bmf, iter(bmf_graph[next_bmf])))

                # if we found a large enough cycle, we can declare victory!
                # NOTE: we cannot do the same for path, because we might have
                #       started crawling in the middle of the path
                if len(longest_cycle) > 50:
                    break

            is_cyclic = len(longest_cycle) >= len(longest_path) * 0.5
            return (longest_cycle if is_cyclic else longest_path, is_cyclic)

        path, cyclic = find_cycle_or_path()
        if len(path) < 2:
            print(f'CONTOURS ERROR: PATH IS UNEXPECTEDLY TOO SHORT')
            return False

        if DEBUG_PRINT_TIMINGS: timers.append((f'find path/cycle ({len(path)} faces, cyclic={cyclic})', time.perf_counter()))
        ####################################################################################################
        # find points in order

        def add_path_end(bmf:BMFace) -> list[Vector]:
            bmelem = next((
                bmelem for bmelem in bmf_intersections[bmf]
                if type(bmelem) != BMFace and len(bmelem.link_faces) == 1
            ), None)
            return [ self.matrix_world_inv @ bmf_intersections[bmf][bmelem] ] if bmelem else []

        points: list[Vector] = []
        if not cyclic:
            points += add_path_end(path[0])
        points += [
            self.matrix_world_inv @ bmf_intersections[bmf0][bmf1]
            for (bmf0, bmf1) in iter_pairs(path, cyclic)
        ]
        if not cyclic:
            points += add_path_end(path[-1])

        end_pts = add_path_end(path[-1]) if not cyclic else []
        timing_title = f'WALK  faces={len(hit_bm.faces)}  path={len(path)}  cyclic={cyclic}'
        return points, cyclic, end_pts, timing_title

    def walk_accel(self, context:Context, md, face_index:int, timers:list) -> 'tuple[list[Vector], bool, list[Vector], str] | bool':
        ''' Graph walk using SourceMeshCache flat arrays. Returns (points, cyclic, end_pts, timing_title) or False. '''
        plane_cut = self.plane

        ####################################################################################################
        # Lazy per-vertex signed distance and edge intersection
        # Distances are computed on first access and memoised — no global broadcast.

        pn = np.array(plane_cut.n, dtype=np.float64)
        pd = float(plane_cut.d)
        EPS = 1e-6

        dist_cache: dict[int, float] = {}

        def vert_dist(vi: int) -> float:
            d = dist_cache.get(vi)
            if d is None:
                w = md.world[vi]
                d = float(w[0] * pn[0] + w[1] * pn[1] + w[2] * pn[2]) - pd
                dist_cache[vi] = d
            return d

        def edge_isect(ei: int) -> 'tuple[Vector, bool, bool] | None':
            ''' Returns (world_pt, is_vert0_on_plane, is_vert1_on_plane) or None if no crossing.
            "On plane" cases are tracked so callers know to propagate through the vertex. '''
            vi0, vi1 = int(md.edge_verts[ei, 0]), int(md.edge_verts[ei, 1])
            d0, d1   = vert_dist(vi0), vert_dist(vi1)
            on0, on1 = abs(d0) < EPS, abs(d1) < EPS
            if on0:
                return Vector(md.world[vi0]), True, False
            if on1:
                return Vector(md.world[vi1]), False, True
            if (d0 > 0.0) == (d1 > 0.0):
                return None  # same side
            t  = d0 / (d0 - d1)
            w0 = md.world[vi0]
            w1 = md.world[vi1]
            return Vector(w0 + t * (w1 - w0)), False, False

        def edge_face_neighbors(ei: int, exclude_fi: int) -> list[int]:
            cnt = int(md.edge_face_counts[ei])
            if cnt < 2:
                return []
            off = int(md.edge_face_offsets[ei])
            return [int(md.sorted_faces[off + k]) for k in range(cnt)
                    if int(md.sorted_faces[off + k]) != exclude_fi]

        def vert_face_neighbors(vi: int, exclude_fi: int) -> list[int]:
            cnt = int(md.vert_face_counts[vi])
            off = int(md.vert_face_offsets[vi])
            return [int(md.vert_sorted_faces[off + k]) for k in range(cnt)
                    if int(md.vert_sorted_faces[off + k]) != exclude_fi]

        ####################################################################################################
        # BFS — only visits faces the cut actually crosses

        face_graph: dict[int, set[int]] = {}
        face_isect: dict[tuple, Vector] = {}  # (fi, fj|str) → world pt

        working_set: set[int] = {face_index}
        while working_set:
            fi = working_set.pop()
            if fi in face_graph:
                continue
            face_graph[fi] = set()

            s = int(md.face_start[fi])
            t = int(md.face_total[fi])
            face_loop_edges = md.loop_edge[s : s + t]

            visited_verts_on_plane: set[int] = set()

            for ei in face_loop_edges:
                result = edge_isect(int(ei))
                if result is None:
                    continue
                pt, on_v0, on_v1 = result

                if on_v0 or on_v1:
                    # Intersection is exactly at a vertex — propagate through all faces
                    # sharing that vertex (not just the two edge-adjacent faces).
                    vi = int(md.edge_verts[ei, 0] if on_v0 else md.edge_verts[ei, 1])
                    if vi in visited_verts_on_plane:
                        continue
                    visited_verts_on_plane.add(vi)
                    face_isect[(fi, f'vert:{vi}')] = pt
                    for fj in vert_face_neighbors(vi, fi):
                        face_graph[fi].add(fj)
                        face_isect[(fi, fj)] = pt
                        face_isect[(fj, fi)] = pt
                        working_set.add(fj)
                else:
                    # Interpolated crossing — propagate only to the (up to 1) other face
                    # sharing this edge.
                    is_boundary = bool(md.boundary[ei])
                    for fj in edge_face_neighbors(int(ei), fi):
                        face_graph[fi].add(fj)
                        face_isect[(fi, fj)] = pt
                        face_isect[(fj, fi)] = pt
                        working_set.add(fj)
                    if is_boundary:
                        face_isect[(fi, f'boundary:{ei}')] = pt

        if DEBUG_PRINT_TIMINGS: timers.append((f'BFS ({len(face_graph)} faces, {len(dist_cache)} dists)', time.perf_counter()))

        ####################################################################################################
        # find longest cycle or path (same logic as bmesh walk, over int keys)

        def find_cycle_or_path() -> tuple[list[int], bool]:
            longest_path : list[int] = []
            longest_cycle: list[int] = []

            endpoint_faces: set[int] = set()
            for key in face_isect:
                if isinstance(key[0], int) and isinstance(key[1], str):
                    endpoint_faces.add(key[0])
            start_faces = endpoint_faces if endpoint_faces else set(face_graph.keys())

            for start_fi in start_faces:
                stack: list[tuple[int, Iterator]] = [(start_fi, iter(face_graph[start_fi]))]
                touched: set[int] = {start_fi}
                limit_finds = 10
                while stack and limit_finds > 0:
                    cur_fi, cur_iter = stack[-1]
                    next_fi = next(cur_iter, None)
                    if next_fi is None:
                        if len(stack) > len(longest_path):
                            longest_path = [f for (f, _) in stack]
                        stack.pop()
                        touched.discard(cur_fi)
                        limit_finds -= 1
                        continue
                    if next_fi in touched:
                        if next_fi == start_fi and len(stack) > 2 and len(stack) > len(longest_cycle):
                            longest_cycle = [f for (f, _) in stack]
                        continue
                    touched.add(next_fi)
                    stack.append((next_fi, iter(face_graph[next_fi])))
                if len(longest_cycle) > 50:
                    break

            is_cyclic = len(longest_cycle) >= len(longest_path) * 0.5
            return (longest_cycle if is_cyclic else longest_path, is_cyclic)

        path, cyclic = find_cycle_or_path()
        if len(path) < 2:
            print('CONTOURS ERROR: PATH IS UNEXPECTEDLY TOO SHORT')
            return False

        if DEBUG_PRINT_TIMINGS: timers.append((f'find path/cycle ({len(path)} faces, cyclic={cyclic})', time.perf_counter()))

        ####################################################################################################
        # ordered points

        MWI = self.matrix_world_inv

        def add_path_end(fi: int) -> list[Vector]:
            for key, pt in face_isect.items():
                if key[0] == fi and isinstance(key[1], str):
                    return [MWI @ pt]
            return []

        points: list[Vector] = []
        if not cyclic:
            points += add_path_end(path[0])
        for fi0, fi1 in iter_pairs(path, cyclic):
            pt = face_isect.get((fi0, fi1))
            if pt is not None:
                points.append(MWI @ pt)
        if not cyclic:
            points += add_path_end(path[-1])

        end_pts = add_path_end(path[-1]) if not cyclic else []
        timing_title = f'WALK(lazy)  mesh={md.n_faces}  path={len(path)}  dists={len(dist_cache)}  cyclic={cyclic}'
        return points, cyclic, end_pts, timing_title

    def process_source_walk(self, context:Context) -> bool:
        ''' Walk the mesh along the cut one face at a time until finding a boundary or returning to the start. '''
        timers     = [('start', time.perf_counter())] if DEBUG_PRINT_TIMINGS else []
        hit_obj    = self.hit['object']
        face_index = self.hit['face_index']
        skip_accel = False # For debugging / testing timing

        if not skip_accel:
            depsgraph = context.evaluated_depsgraph_get()
            md = SourceMeshCache.get(hit_obj, depsgraph)
            if md is None or face_index >= md.n_faces:
                SourceMeshCache.evict(hit_obj.name)
                md = SourceMeshCache.get(hit_obj, depsgraph)

        if skip_accel or md is None or face_index >= md.n_faces:
            print(f'CONTOURS: SourceMeshCache unavailable for {hit_obj.name!r}, falling back to bmesh walk')
            result = self.walk_bmesh(context, timers)
        else:
            # Warm any other uncached sources in the background while the user is working.
            SourceMeshCache.request_warmup(context)
            result = self.walk_accel(context, md, face_index, timers)

        if result is False: return False

        points, cyclic, end_pts, timing_title = result

        ####################################################################################################
        # subdivide for better circle-fitting
        subdiv = 10
        points = [
            pt
            for (p0, p1) in iter_pairs(points, cyclic)
            for pt in (lerp(i / subdiv, p0, p1) for i in range(subdiv))
        ]
        if not cyclic:
            points += end_pts
        points = [p0 for (p0, p1) in iter_pairs(points, cyclic) if (p0 - p1).length > 0]

        ####################################################################################################
        # handle cutting across mirror planes

        points, mirror_clipped_loop = self.handle_mirrors(context, points)
        if mirror_clipped_loop: cyclic = False

        if len(points) < 3:
            print(f'CONTOURS: TOO FEW POINTS FOUND TO FIT PLANE')
            return False


        ####################################################################################################
        # compute useful statistics about points

        plane_fit = Plane.fit_to_points(points)
        assert plane_fit
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        self.points = points                            # points where cut crosses source (target space)
        self.cyclic = cyclic                            # is cut cyclic (loop) or a strip?
        self.plane_fit = plane_fit                      # plane that fits cut points (target space)
        self.circle_fit = circle_fit                    # circle that fits points (plane_fit space)
        self.path_length = path_length                  # length of path of points (target space)
        self.mirror_clipped_loop = mirror_clipped_loop  # did cyclic loop cross mirror plane?

        if DEBUG_PRINT_TIMINGS:
            self.debug_print_timings(timers, timing_title)
        return True


    def handle_mirrors(self, context:Context, points:list[Vector]) -> tuple[list[Vector], bool]:
        mirror_clipped_loop = False

        mx, my, mz = has_mirror_x(context), has_mirror_y(context), has_mirror_z(context)

        sel_bmvs = bmops.get_all_selected_bmverts(self.bm)
        if sel_bmvs:
            # use selected geometry to find side
            sx = next(((1 if not mx or bmv.co.x > 0 else -1) for bmv in sel_bmvs if not mx or bmv.co.x != 0), 1)
            sy = next(((1 if not my or bmv.co.y > 0 else -1) for bmv in sel_bmvs if not my or bmv.co.y != 0), 1)
            sz = next(((1 if not mz or bmv.co.z > 0 else -1) for bmv in sel_bmvs if not mz or bmv.co.z != 0), 1)
        else:
            # use cut to determine side
            co = self.hit['co_local']
            sx = 1 if not mx or co.x > 0 else -1
            sy = 1 if not my or co.y > 0 else -1
            sz = 1 if not mz or co.z > 0 else -1

        def correct_x(co:Vector) -> bool:
            return not mx or (1 if co.x > 0 else -1) == sx
        def correct_y(co:Vector) -> bool:
            return not my or (1 if co.y > 0 else -1) == sy
        def correct_z(co:Vector) -> bool:
            return not mz or (1 if co.z > 0 else -1) == sz

        def clip_loop(pts, correct_fn, boundary_fn):
            l = len(pts)
            idx = next((i for i in range(l) if not correct_fn(pts[i]) and correct_fn(pts[(i+1)%l])), 0)
            pts = pts[idx:] + pts[:idx]
            cut = next((i for i in range(1, l) if correct_fn(pts[i-1]) and not correct_fn(pts[i])), None)
            if cut is None:
                if len(pts) < 2: return pts
                return [boundary_fn(pts[0], pts[1])] + pts[1:-1] + [boundary_fn(pts[-1], pts[0])]
            pts = pts[:cut+1]
            if len(pts) < 2: return pts
            return [boundary_fn(pts[0], pts[1])] + pts[1:-2] + [boundary_fn(pts[-2], pts[-1])]

        def clip_path(pts, correct_fn, boundary_fn):
            result = []
            for i, cur in enumerate(pts):
                if i == 0:
                    if correct_fn(cur): result.append(cur)
                else:
                    prev, prev_ok, cur_ok = pts[i-1], correct_fn(pts[i-1]), correct_fn(cur)
                    if not prev_ok and cur_ok:
                        result.append(boundary_fn(prev, cur))
                        result.append(cur)
                    elif prev_ok and not cur_ok:
                        result.append(boundary_fn(prev, cur))
                    elif cur_ok:
                        result.append(cur)
            return result

        for active, correct_fn, boundary_fn in [
            (mx, correct_x, pt_x0),
            (my, correct_y, pt_y0),
            (mz, correct_z, pt_z0),
        ]:
            if not active: continue
            if not any(not correct_fn(p) for p in points): continue
            if not any(correct_fn(p) for p in points): continue
            points = (clip_path if mirror_clipped_loop else clip_loop)(points, correct_fn, boundary_fn)
            mirror_clipped_loop = True

        return (points, mirror_clipped_loop)

    def debug_print_timings(self, timers, title):
        timers.append(('finalize', time.perf_counter()))
        _total = timers[-1][1] - timers[0][1]
        _report = [
            f'{t1-t0:.4f}s  {lbl}'
            for (lbl, t0), (_, t1) in zip(timers[:-1], timers[1:])
        ] + ['--------  ---------------', f'{_total:.4f}s  total']
        term_printer.boxed(*_report, title=title)

    def debug_print_bridge(self, center_new, center_src, plane_fit, ring_perimeter, dot_n1_n2, cross):
        s_val = self.path_length / ring_perimeter if ring_perimeter > 1e-6 else 1.0
        print(f'[Bridge] center_new:  {center_new}  (world bbox → local)')
        print(f'[Bridge] center_src:  {center_src}  (world bbox → local)')
        print(f'[Bridge] plane_fit.o: {Vector(plane_fit.o)}')
        print(f'[Bridge] path_length: {self.path_length:.4f}  ring_perimeter: {ring_perimeter:.4f}  S={s_val:.4f}')
        print(f'[Bridge] n1·n2 (dot): {dot_n1_n2:.4f}  cross len: {cross.length:.4f}  shear applied: {cross.length > 1e-9 and abs(dot_n1_n2) > 1e-9}')

    def debug_print_snap(self, snap_type, v, **data):
        if snap_type == 'ON_PATH':
            print(f'[SnapPass2] vert {v}  → ON-PATH  (nearest_dist={data["nearest_dist"]:.2e})')
        elif snap_type == 'RAYCAST':
            n_nbrs = len(data['ring_nbrs']) if data.get('tangent') else 0
            print(f'[SnapPass2] vert {v}  → RAYCAST  (best_dist={data["best_dist"]:.4f}  nearest_dist={data["nearest_dist"]:.4f}  ring_nbrs={n_nbrs})  new_pos={data["new_pos"]}')
        elif snap_type == 'NEAREST_PT':
            best_pt, best_dist, nearest_dist = data.get('best_pt'), data.get('best_dist'), data['nearest_dist']
            factor, tangent = data['nearest_factor'], data.get('tangent')
            if best_pt is not None:
                reason = f'ray too far ({best_dist:.4f} > {nearest_dist * factor:.4f})'
            elif not (tangent and tangent.length > 1e-9):
                reason = 'no tangent'
            else:
                reason = 'no ray hit'
            print(f'[SnapPass2] vert {v}  → NEAREST-PT fallback  ({reason}  nearest_dist={nearest_dist:.4f})  new_pos={data["new_pos"]}')
        elif snap_type == 'WORLD_SNAP':
            print(f'[SnapPass2] vert {v}  → WORLD-SNAP fallback  new_pos={data["new_pos"]}')
