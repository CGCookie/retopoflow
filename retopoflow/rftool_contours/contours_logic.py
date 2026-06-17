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
from itertools import chain
from collections import defaultdict
from collections.abc import Sequence, Iterator
from math import isclose
from bmesh.types import BMVert, BMEdge, BMFace, BMesh
from bpy.types import Context, Mesh
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Matrix, Vector
from ..common.bmesh import (
    get_bmesh_emesh, get_object_bmesh,
    has_mirror_x, has_mirror_y, has_mirror_z,
    bmf_midpoint_radius, bme_other_bmf, bmf_is_quad, quad_bmf_opposite_bme,
    ensure_correct_normals,
    find_selected_cycle_or_path,
)
from ..common.maths import (
    bvec_to_point, point_to_bvec3,
    pt_x0, pt_y0, pt_z0,
    lerp, get_closest_axis, snap_plane_to_direction,
    closest_point_linesegment,
)
from ..common.raycast import raycast_ray_valid_sources, nearest_point_valid_sources, nearest_normal_valid_sources, raycast_multiple_hits
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.debug import debugger
from ...addon_common.terminal import term_printer
from ...addon_common.common.maths import Point, Plane
from ...addon_common.common.utils import iter_pairs
from ...addon_common.ext.circle_fit import hyperLSQ


CREATE_DEBUG_OBJECTS = False
PRINT_DEBUG_TIMINGS = False

class Contours_Logic:
    matrix_world : Matrix | None
    matrix_world_inv : Matrix | None
    bm : BMesh | None
    em : Mesh | None

    hit : dict[str, ...]
    hits : list[dict[str, ...]]
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
    sdf_resolution : int
    last_sdf_resolution : int | None
    sdf_subdivisions : int
    last_sdf_subdivisions : int | None
    sdf_extent_scale : float
    last_sdf_extent_scale : float | None
    last_cut_orientation : str | None

    action : str
    show_span_count : bool
    span_count : int
    show_twist : bool
    twist : float
    show_loop_count : bool
    loop_count : int
    cyclic : bool

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
                 sample_points:int=50, fast_refine_steps:int=5, sdf_refine_steps:int=3, skip_step_size:float=0.5, sdf_resolution:int=20,
                 sdf_subdivisions:int=0, sdf_extent_scale:float=1.5):
        self.hit = hit
        self.hits = hits
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
        self.sdf_resolution = sdf_resolution
        self.last_sdf_resolution = None
        self.sdf_subdivisions = sdf_subdivisions
        self.last_sdf_subdivisions = None
        self.sdf_extent_scale = sdf_extent_scale
        self.last_sdf_extent_scale = None

        self.action = ''
        self.initial = True

        self.show_span_count = False
        self.span_count = span_count

        self.show_twist = False
        self.twist = 0

        self.show_loop_count = False
        self.loop_count = 1

        self.cyclic = False
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

    def process_source(self, context:Context) -> bool:
        # process source only once, unless settings have changed
        if (not self.initial and
            self.last_process_source_method == self.process_source_method and
            self.last_fast_depth == self.fast_depth and
            self.last_sample_points == self.sample_points and
            self.last_fast_refine_steps == self.fast_refine_steps and
            self.last_sdf_refine_steps == self.sdf_refine_steps and
            self.last_skip_step_size == self.skip_step_size and
            self.last_sdf_resolution == self.sdf_resolution and
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
        self.last_sdf_resolution = self.sdf_resolution
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

    def insert(self, context:Context):
        if self.edge_ring:
            # cut in new edge loop
            self.insert_edge_ring(context)
        elif self.bridge:
            # extrude selection to cut
            self.insert_bridge(context)
        else:
            self.insert_new_cut(context)
        bmops.flush_selection(self.bm, self.em)

    def insert_edge_ring(self, context:Context):
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
        nbmelems = bmesh.ops.subdivide_edgering(self.bm, edges=list(self.edge_ring), cuts=1)['faces']
        # newly created verts will not be selected
        nbmvs = list({ bmv for bmf in nbmelems for bmv in bmf.verts if not bmv.select })

        self.finish_edgering_bridge(context, nbmelems, nbmvs)
        self.action = 'Loop Cut' if self.cyclic else 'Strip Cut'
        self.show_twist = self.cyclic

    def insert_bridge(self, context:Context):
        orig_verts = {bv for bme in self.sel_path for bv in bme.verts}

        nbmelems = bmesh.ops.extrude_edge_only(self.bm, edges=self.sel_path)['geom']
        nbmvs = [bmelem for bmelem in nbmelems if type(bmelem) is BMVert]

        self.finish_edgering_bridge(context, nbmelems, nbmvs)

        if self.loop_count > 1:
            # Add more loop cuts to the bridge
            new_verts_set = set(nbmvs)
            lateral_edges = list({
                bme
                for bmv in nbmvs
                for bme in bmv.link_edges
                if any(bv in orig_verts for bv in bme.verts)
            })
            if lateral_edges:
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
                # Find final positions before moving any vert so loop normals are accurate
                new_cos = {}
                for bmv in intermediate_verts:
                    npt_world = point_to_bvec3(self.matrix_world @ bvec_to_point(bmv.co))
                    # Find nearest surface point as reference / fallback.
                    nearest = nearest_point_valid_sources(context, npt_world, world=True, respect_clip_planes=True)
                    npt_snapped = nearest
                    # Get the outward surface normal at that nearest point.
                    surface_normal = nearest_normal_valid_sources(context, npt_world, world=True)
                    if surface_normal is not None and nearest is not None:
                        # Raycast in both directions and pick whichever hit is closest to the nearest surface.
                        hits = []
                        for sign in (1, -1):
                            ray_dir = Vector((*(surface_normal * sign), 0.0))
                            hit = raycast_ray_valid_sources(context, (Vector((*npt_world, 1.0)), ray_dir), world=True, respect_clip_planes=True)
                            if hit is not None:
                                hits.append(hit)
                        if hits:
                            npt_snapped = min(hits, key=lambda h: (h - nearest).length)
                    if npt_snapped is not None:
                        new_cos[bmv] = self.matrix_world_inv @ npt_snapped
                # Apply all positions at once.
                for bmv, co in new_cos.items():
                    bmv.co = co
                ensure_correct_normals(self.bm, result['faces'])

        self.action = 'Bridging Loop' if self.cyclic else 'Bridging Strip'
        self.show_twist = self.cyclic
        self.show_loop_count = True

    def finish_edgering_bridge(self, context:Context, nbmelems:Sequence[BMVert|BMEdge|BMFace], nbmvs:Sequence[BMVert]):
        if self.points is None or self.plane_fit is None or self.circle_fit is None:
            return

        plane_fit = self.plane_fit
        circle_fit = self.circle_fit

        # compute useful statistics about newly created geometry
        npoints = [Point(bmv.co) for bmv in nbmvs]
        try:
            if len(npoints) < 3:
                raise Exception(f'Not enough points to fit plane: {len(npoints)}')
            nplane_fit = Plane.fit_to_points(npoints)   # local space
            if plane_fit.n.dot(nplane_fit.n) < 0:
                nplane_fit.n.negate()  # make sure both planes are oriented the same
            ncircle_fit = hyperLSQ([list(nplane_fit.w2l_point(pt).xy) for pt in npoints])
        except Exception as e:
            print(f'CONTOURS WARNING: failed to fit plane/circle for bridge: {e}')
            nplane_fit = plane_fit
            ncircle_fit = circle_fit

        # identify symmetry plane verts before any transformation so we can re-pin them after
        mx, my, mz = has_mirror_x(context), has_mirror_y(context), has_mirror_z(context)
        sym_verts = set()
        if mx or my or mz:
            threshold = 1e-4
            for bmv in nbmvs:
                if mx and abs(bmv.co.x) < threshold: sym_verts.add(bmv)
                if my and abs(bmv.co.y) < threshold: sym_verts.add(bmv)
                if mz and abs(bmv.co.z) < threshold: sym_verts.add(bmv)

        # Arithmetic centroid is more stable than hyperLSQ circle center for non-circular cross-sections
        center_new = Vector((0.0, 0.0, 0.0))
        for bmv in nbmvs:
            center_new += Vector(bmv.co)
        center_new /= len(nbmvs)
        center_src = Vector((0.0, 0.0, 0.0))
        for pt in self.points:
            center_src += Vector(pt)
        center_src /= len(self.points)

        # compute xforms to roughly move new geometry to match cut
        # instead of scaling based on circle radii, scale X and Y independently based on SVD if fit?
        # the two axes of two planes might not align....  although they _should_ if we're bridging
        T0 = Matrix.Translation(-center_new)
        S  = Matrix.Scale(circle_fit[2] / ncircle_fit[2], 4) if ncircle_fit[2] > 1e-6 else Matrix.Scale(1.0, 4)
        R  = Matrix.Rotation(-plane_fit.n.angle(nplane_fit.n), 4, plane_fit.n.cross(nplane_fit.n))
        RT = Matrix.Rotation(self.twist, 4, plane_fit.n)
        T1 = Matrix.Translation(center_src)
        xform = T1 @ RT @ R @ S @ T0

        # Snap each vertex to the nearest point on the cross-section path.
        # nearest_point_valid_sources can snap to the wrong face when a vertex lands near a face boundary
        pts = self.points
        n_pts = len(pts)
        n_segs = n_pts if self.cyclic else n_pts - 1
        for bmv in nbmvs:
            bmv.co = xform @ bmv.co

            # self.points is in the retopo object's local space, so compare in local space directly.
            npt_local = bvec_to_point(bmv.co)

            best_pt = None
            best_dist2 = float('inf')
            for i in range(n_segs):
                p0 = Vector(pts[i])
                p1 = Vector(pts[(i + 1) % n_pts])
                closest = closest_point_linesegment(npt_local, p0, p1)
                if closest is not None:
                    d2 = (npt_local - closest).length_squared
                    if d2 < best_dist2:
                        best_dist2 = d2
                        best_pt = closest

            if best_pt is not None:
                bmv.co = best_pt
            else:
                npt_world = point_to_bvec3(self.matrix_world @ npt_local)
                npt_world_snapped = nearest_point_valid_sources(context, npt_world, world=True, respect_clip_planes=True)
                npt_world_new = npt_world_snapped if npt_world_snapped else npt_world
                bmv.co = self.matrix_world_inv @ npt_world_new if npt_world_new is not None else npt_local

        # re-pin any verts that were on a symmetry plane so twist can't move them off
        for bmv in sym_verts:
            if mx: bmv.co.x = 0
            if my: bmv.co.y = 0
            if mz: bmv.co.z = 0

        if not self.cyclic:
            # snap ends
            if self.edge_ring:
                bmv_ends = [bmv for bmv in nbmvs if len(bmv.link_faces) == 2]
            else:
                bmv_ends = [bmv for bmv in nbmvs if len(bmv.link_faces) == 1]

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

        # make sure face normals are correct.  cannot do this earlier, because
        # faces have no defined normal (verts overlap)
        nbmfs = [bmelem for bmelem in nbmelems if type(bmelem) is BMFace]
        ensure_correct_normals(self.bm, nbmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, nbmvs)


    def insert_new_cut(self, context:Context):
        M, Mi = self.matrix_world, self.matrix_world_inv
        path_length = self.path_length

        if self.points is None or M is None or Mi is None or path_length is None:
            return

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

        segment_count = self.span_count
        vertex_count = self.span_count if self.cyclic else self.span_count + 1
        if self.mirror_clipped_loop:
            # update vertex count, because the loop crosses mirror
            vertex_count = vertex_count // 2 + 1
            segment_count = vertex_count - 1

        # find pts for new geometry
        # note: might need to take a few attempts due to numerical precision
        true_segment_length = path_length / segment_count
        factor_min, factor_max = 0.8, 1.2
        best_npts = None
        for _ in range(10):
            factor = (factor_min + factor_max) / 2
            segment_length = true_segment_length * factor
            dist, npts = 0, []
            for pt0, pt1 in iter_pairs(points, self.cyclic):
                vec01 = pt1 - pt0
                len01 = vec01.length
                if dist > len01:
                    dist -= len01
                    continue
                dir01 = vec01 / len01
                pt = pt0
                while dist <= len01:
                    pt = pt + dir01 * dist
                    npts.append(pt)
                    len01 -= dist
                    dist = segment_length
                dist -= len01
            if not self.cyclic: npts.append(points[-1])

            if len(npts) == vertex_count:
                # found exact number of verts!
                best_npts = npts
                final_dist = (npts[0] - npts[-1]).length if self.cyclic else (npts[-1] - npts[-2]).length
                if final_dist < true_segment_length:
                    # last segment is too short; take shorter steps
                    factor_min, factor_max = factor_min, factor
                else:
                    # last segment is too long; take longer steps
                    factor_min, factor_max = factor, factor_max
                # error = sum((pt0-pt1).length - true_segment_length for (pt0, pt1) in iter_pairs(points, self.cyclic))
                # (factor_min, factor_max) = (factor_min, factor) if error < 0 else (factor, factor_max)
            elif len(npts) < vertex_count:
                # too few points found; need more points
                # reduce factor to take smaller steps
                factor_min, factor_max = factor_min, factor
            else:
                # too many points found (which is ok); try finding fewer points
                # increase factor to take larger steps
                factor_min, factor_max = factor, factor_max
                if not best_npts or len(npts) <= len(best_npts):
                    best_npts = npts
        npts = best_npts
        assert npts, f'Could not find enough points!?'
        assert len(npts) >= vertex_count

        npts = [
            (Mi @ snapped) if (
                snapped := nearest_point_valid_sources(context, M @ pt, world=True, respect_clip_planes=True)
            ) else pt for pt in npts
        ]

        # create geometry!
        nbmvs = [ self.bm.verts.new(pt) for pt in npts[:vertex_count] ]
        bmes = [self.bm.edges.new((bmv0, bmv1)) for (bmv0, bmv1) in iter_pairs(nbmvs, self.cyclic)]

        if not self.cyclic:
            # snap ends
            bmv_ends = [bmv for bmv in nbmvs if len(bmv.link_edges) == 1]
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
        bmops.select_iter(self.bm, nbmvs)


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
                corrected = []
                for p in pts_w:
                    p_plane = _on_plane(p)
                    npt = nearest_point_valid_sources(context, p_plane, world=True, respect_clip_planes=False)
                    corrected.append(_on_plane(Vector(npt)) if npt is not None else p_plane)
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
                    new_pts_w.append(_on_plane(Vector(npt)) if npt is not None else m)
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
                    new_pts_w.append(min(candidates, key=lambda h: (h - m).length_squared) if candidates else m)
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
        if PRINT_DEBUG_TIMINGS: timers = [('start', time.perf_counter())]
        plane_cut = self.plane
        center_plane, center_world = self.get_volume_center(context, plane_cut)

        if PRINT_DEBUG_TIMINGS: timers.append(('center/depth', time.perf_counter()))
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

        if PRINT_DEBUG_TIMINGS: timers.append((f'radial rays ({nsamples})', time.perf_counter()))
        points_world = self.normalize_winding(points_world, plane_cut)

        if self.fast_refine_steps > 0 and len(points_world) >= 3:
            plane_normal_world = Vector(plane_cut.l2w_direction(Vector((0, 0, 1))))
            points_world = self.refine_loop(context, points_world, plane_normal_world, self.fast_refine_steps)

        if PRINT_DEBUG_TIMINGS: timers.append((f'refinement ({self.fast_refine_steps} steps)', time.perf_counter()))
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

        if PRINT_DEBUG_TIMINGS:
            timers.append(('finalize', time.perf_counter()))
            _total = timers[-1][1] - timers[0][1]
            _report = [
                f'{t1-t0:.4f}s  {lbl}'
                for (lbl, t0), (_, t1) in zip(timers[:-1], timers[1:])
            ] + ['--------  ---------------', f'{_total:.4f}s  total']
            term_printer.boxed(*_report, title=f'FAST  depth={self.fast_depth}  samples={nsamples}  refine={self.fast_refine_steps}')
        return True

    def process_source_sdf(self, context:Context) -> bool:
        '''Build a coarse occupancy grid on the cut plane, trace the boundary, then snap and smooth that loop.'''
        if PRINT_DEBUG_TIMINGS: timers = [('start', time.perf_counter())]
        plane_cut = self.plane
        center_plane, center_world = self.get_volume_center(context, plane_cut)

        if PRINT_DEBUG_TIMINGS: timers.append(('center/depth', time.perf_counter()))
        nsamples = 25 # Only used to compute grid size, so can be sparse
        hit_local = plane_cut.w2l_point(Vector(self.hit['co_world']))
        xs = [center_plane.x, hit_local.x]
        ys = [center_plane.y, hit_local.y]
        for d in range(nsamples):
            dp = Vector((math.cos(2*math.pi*d/nsamples), math.sin(2*math.pi*d/nsamples), 0, 0))
            dw = plane_cut.l2w_direction(dp)
            rh = raycast_ray_valid_sources(context, (center_world, dw), world=True, respect_clip_planes=True)
            if rh is None: continue
            lp = plane_cut.w2l_point(rh)
            xs.append(lp.x); ys.append(lp.y)
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        width, height = xmax - xmin, ymax - ymin
        if width < 1e-6 or height < 1e-6:
            print('CONTOURS SDF: degenerate extent, falling back to Fast')
            return self.process_source_fast(context)
        # scale the bbox since exterior is usually bigger than measured interior
        _cx, _cy = (xmin + xmax) / 2, (ymin + ymax) / 2
        _scale = max(0.5, float(self.sdf_extent_scale))
        xmin, xmax = _cx - width * _scale / 2, _cx + width * _scale / 2
        ymin, ymax = _cy - height * _scale / 2, _cy + height * _scale / 2
        width, height = xmax - xmin, ymax - ymin

        if PRINT_DEBUG_TIMINGS: timers.append((f'extent ({nsamples} rays)', time.perf_counter()))
        # Grid dimensions. Resolution on the long axis, short axis by aspect ratio
        res: int = self.sdf_resolution
        if width >= height:
            res_x, res_y = res, max(3, round(res * height / width))
        else:
            res_y, res_x = res, max(3, round(res * width / height))
        fine_count: int = 3 ** max(0, int(self.sdf_subdivisions))
        RX, RY = res_x * fine_count, res_y * fine_count
        fcw, fch = width / RX, height / RY  # fine cell size
        base_radius = 0.5 * math.hypot(width / res_x, height / res_y) # coarse cell half-diagonal

        # Find cells near the surface
        near       = [[False] * RY for _ in range(RX)]
        block_size = [[fine_count]   * RY for _ in range(RX)] # effective block size per fine cell (for debug)

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
            for fi in range(fi0, fi0 + sz):
                for fj in range(fj0, fj0 + sz):
                    near[fi][fj]       = n_val
                    block_size[fi][fj] = sz

        # Large initial cells first
        for bi in range(res_x):
            for bj in range(res_y):
                n_ = classify_cell(bi * fine_count + fine_count // 2, bj * fine_count + fine_count // 2, base_radius)
                fill_block_uniform(bi * fine_count, bj * fine_count, fine_count, n_)

        # Iteratively refine by subdividing hit cells and having each smaller cell search again
        max_cell_queries = 1_000_000
        total_cell_queries = res_x * res_y  # Phase 1 already classified this many
        cur_size, cur_radius = fine_count, base_radius
        for subdiv_level in range(self.sdf_subdivisions):
            if cur_size < 3: break
            sub_size   = cur_size // 3
            sub_radius = cur_radius / 3.0
            n_bx, n_by = RX // cur_size, RY // cur_size
            to_refine = []
            for bi in range(n_bx):
                for bj in range(n_by):
                    fi_c, fj_c = bi * cur_size + cur_size // 2, bj * cur_size + cur_size // 2
                    if block_size[fi_c][fj_c] != cur_size: continue  # coarser / already finalized far block
                    if near[fi_c][fj_c]:
                        to_refine.append((bi * cur_size, bj * cur_size))
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

        if PRINT_DEBUG_TIMINGS: timers.append((f'grid classify ({RX}x{RY} cells, {res_x}x{res_y} coarse, fine_count={fine_count})', time.perf_counter()))
        # Create solid outlines to trace
        is_empty = lambda i, j: not near[i][j]
        exterior = [[False] * RY for _ in range(RX)]
        stack = []
        for i in range(RX):
            for j in (0, RY - 1):
                if is_empty(i, j) and not exterior[i][j]:
                    exterior[i][j] = True; stack.append((i, j))
        for j in range(RY):
            for i in (0, RX - 1):
                if is_empty(i, j) and not exterior[i][j]:
                    exterior[i][j] = True; stack.append((i, j))
        while stack:
            i, j = stack.pop()
            for di, dj in ((1,0),(-1,0),(0,1),(0,-1)):
                ni, nj = i + di, j + dj
                if 0 <= ni < RX and 0 <= nj < RY and not exterior[ni][nj] and is_empty(ni, nj):
                    exterior[ni][nj] = True; stack.append((ni, nj))
        solid = [[not exterior[i][j] for j in range(RY)] for i in range(RX)]

        # Isolate shape containing the original surface hit
        hi = min(RX - 1, max(0, int((hit_local.x - xmin) / fcw)))
        hj = min(RY - 1, max(0, int((hit_local.y - ymin) / fch)))
        if not solid[hi][hj]:
            best, bestd = None, None
            for i in range(RX):
                for j in range(RY):
                    if solid[i][j]:
                        dd = (i - hi) ** 2 + (j - hj) ** 2
                        if bestd is None or dd < bestd:
                            bestd, best = dd, (i, j)
            if best is None:
                print('CONTOURS SDF: no hit cells found, falling back to Fast')
                return self.process_source_fast(context)
            hi, hj = best

        blob = [[False] * RY for _ in range(RX)]
        stack = [(hi, hj)]; blob[hi][hj] = True
        touches_border = False
        while stack:
            i, j = stack.pop()
            if i == 0 or j == 0 or i == RX - 1 or j == RY - 1:
                touches_border = True
            for di, dj in ((1,0),(-1,0),(0,1),(0,-1)):
                ni, nj = i + di, j + dj
                if 0 <= ni < RX and 0 <= nj < RY and not blob[ni][nj] and solid[ni][nj]:
                    blob[ni][nj] = True; stack.append((ni, nj))

        # Trace the outer boundary as an ordered loop of lattice corners
        def blob_at(i, j):
            return 0 <= i < RX and 0 <= j < RY and blob[i][j]
        def boundary_dirs(cx, cy):
            sw, se = blob_at(cx-1, cy-1), blob_at(cx, cy-1)
            nw, ne = blob_at(cx-1, cy),   blob_at(cx, cy)
            ds = []
            if nw != ne: ds.append((0, 1))    # N
            if sw != se: ds.append((0, -1))   # S
            if se != ne: ds.append((1, 0))    # E
            if sw != nw: ds.append((-1, 0))   # W
            return ds
        right_turn = {(0,1):(1,0), (1,0):(0,-1), (0,-1):(-1,0), (-1,0):(0,1)}

        start_cell = next(((i, j) for i in range(RX) for j in range(RY) if blob[i][j]), None)
        if start_cell is None:
            print('CONTOURS SDF: empty blob, falling back to Fast')
            return self.process_source_fast(context)
        start = start_cell  # leftmost-lowest blob cell -> its lower-left corner is on the boundary
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

        if PRINT_DEBUG_TIMINGS: timers.append((f'boundary march ({len(corners)} corners)', time.perf_counter()))
        if CREATE_DEBUG_OBJECTS:
            _raw_corners = list(corners)  # save full staircase before downsample for debug path
            _debug_saved_hide = {}
            for _dname in ('SDF_Debug_Grid', 'SDF_Debug_Path', 'SDF_Debug_Snapped', 'SDF_Debug_Refined'):
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
            corners = [corners[int(round(k * step)) % len(corners)] for k in range(target_count)]

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
        deduped = []
        for p in points_world:
            if not deduped or (Vector(p) - Vector(deduped[-1])).length > merge_dist:
                deduped.append(p)
        if len(deduped) >= 2 and (Vector(deduped[0]) - Vector(deduped[-1])).length <= merge_dist:
            deduped.pop()
        points_world = deduped
        if len(points_world) < 3:
            print('CONTOURS SDF: too few points after snapping, falling back to Fast')
            return self.process_source_fast(context)

        if PRINT_DEBUG_TIMINGS: timers.append((f'snap ({len(points_world)} pts)', time.perf_counter()))
        if CREATE_DEBUG_OBJECTS:
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

            _gm = bpy.data.meshes.new('SDF_Debug_Grid')
            _bm = bmesh.new()
            _emitted = [[False] * RY for _ in range(RX)]
            for _fi in range(RX):
                for _fj in range(RY):
                    if _emitted[_fi][_fj]: continue
                    _sz = block_size[_fi][_fj]
                    # clamp so blocks that reach the grid edge don't go OOB
                    _sz_x = min(_sz, RX - _fi)
                    _sz_y = min(_sz, RY - _fj)
                    _v0 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + _fi           * fcw, ymin + _fj           * fch, 0))))
                    _v1 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + (_fi + _sz_x) * fcw, ymin + _fj           * fch, 0))))
                    _v2 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + (_fi + _sz_x) * fcw, ymin + (_fj + _sz_y) * fch, 0))))
                    _v3 = _bm.verts.new(plane_cut.l2w_point(Vector((xmin + _fi           * fcw, ymin + (_fj + _sz_y) * fch, 0))))
                    _bm.faces.new([_v0, _v1, _v2, _v3]).select = solid[_fi + _sz_x // 2][_fj + _sz_y // 2]
                    for _dfi in range(_sz_x):
                        for _dfj in range(_sz_y):
                            _emitted[_fi + _dfi][_fj + _dfj] = True
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

        if PRINT_DEBUG_TIMINGS: timers.append((f'refinement ({self.sdf_refine_steps} steps)', time.perf_counter()))
        if CREATE_DEBUG_OBJECTS and len(points_world) >= 2:
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

        points = [ self.matrix_world_inv @ pt_world for pt_world in points_world if pt_world ]
        cyclic = not touches_border

        points, mirror_clipped_loop = self.handle_mirrors(context, points)
        if mirror_clipped_loop: cyclic = False

        if len(points) < 3:
            print('CONTOURS SDF: too few points found to fit plane')
            return False

        plane_fit = Plane.fit_to_points(points)
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

        if PRINT_DEBUG_TIMINGS:
            timers.append(('finalize', time.perf_counter()))
            _total = timers[-1][1] - timers[0][1]
            _report = [
                f'{t1-t0:.4f}s  {lbl}'
                for (lbl, t0), (_, t1) in zip(timers[:-1], timers[1:])
            ] + ['--------  ---------------', f'{_total:.4f}s  total']
            term_printer.boxed(*_report, title=f'SDF  grid={res_x}x{res_y}  fine_count={fine_count}  refine={self.sdf_refine_steps}')
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
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        self.points = points
        self.cyclic = cyclic
        self.plane_fit = plane_fit                      # plane that fits cut points (target space)
        self.circle_fit = circle_fit                    # circle that fits points (plane_fit space)
        self.path_length = path_length                  # length of path of points (target space)
        self.mirror_clipped_loop = mirror_clipped_loop  # did cyclic loop cross mirror plane?

        return True

    def process_source_walk(self, context:Context):
        '''
        gathers cut info of high-res mesh (hit_obj) starting at hit_bmf
        '''
        if PRINT_DEBUG_TIMINGS: timers = [('start', time.perf_counter())]
        plane_cut = self.plane
        hit_obj = self.hit['object']
        M = hit_obj.matrix_world
        hit_bm = get_object_bmesh(hit_obj)
        face_index = self.hit['face_index']
        if face_index >= len(hit_bm.faces):
            # cache is stale, source mesh changed face count
            get_object_bmesh.cache.pop(hit_obj, None)
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

        if PRINT_DEBUG_TIMINGS: timers.append((f'face graph ({len(bmf_graph)} faces)', time.perf_counter()))
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

        if PRINT_DEBUG_TIMINGS: timers.append((f'find path/cycle ({len(path)} faces, cyclic={cyclic})', time.perf_counter()))
        ####################################################################################################
        # find points in order

        points = []
        def add_path_end(bmf:BMFace) -> list[Vector]:
            bmelem = next((
                bmelem for bmelem in bmf_intersections[bmf]
                if type(bmelem) != BMFace and len(bmelem.link_faces) == 1
            ), None)
            return [ self.matrix_world_inv @ bmf_intersections[bmf][bmelem] ] if bmelem else []
        if not cyclic:
            points += add_path_end(path[0])
        points += [
            self.matrix_world_inv @ bmf_intersections[bmf0][bmf1]
            for (bmf0, bmf1) in iter_pairs(path, cyclic)
        ]
        if not cyclic:
            points += add_path_end(path[-1])


        ####################################################################################################
        # subdivide for better circle-fitting
        subdiv = 10
        points = [
            pt
            for (p0, p1) in iter_pairs(points, cyclic)
            for pt in (lerp(i / subdiv, p0, p1) for i in range(subdiv))
        ]
        if not cyclic: points += add_path_end(path[-1])
        points = [
            p0 for (p0, p1) in iter_pairs(points, cyclic)
            if (p0 - p1).length > 0
        ]



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
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        self.points = points                            # points where cut crosses source (target space)
        self.cyclic = cyclic                            # is cut cyclic (loop) or a strip?
        self.plane_fit = plane_fit                      # plane that fits cut points (target space)
        self.circle_fit = circle_fit                    # circle that fits points (plane_fit space)
        self.path_length = path_length                  # length of path of points (target space)
        self.mirror_clipped_loop = mirror_clipped_loop  # did cyclic loop cross mirror plane?

        if PRINT_DEBUG_TIMINGS:
            timers.append(('finalize', time.perf_counter()))
            _total = timers[-1][1] - timers[0][1]
            _report = [
                f'{t1-t0:.4f}s  {lbl}'
                for (lbl, t0), (_, t1) in zip(timers[:-1], timers[1:])
            ] + ['--------  ---------------', f'{_total:.4f}s  total']
            term_printer.boxed(*_report, title=f'WALK  faces={len(hit_bm.faces)}  path={len(path)}  cyclic={cyclic}')
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
