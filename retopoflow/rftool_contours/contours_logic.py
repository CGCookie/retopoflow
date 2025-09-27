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
import os
import time
import math
import bmesh
from itertools import chain, takewhile
from collections import defaultdict
from bmesh.types import BMVert, BMEdge, BMFace
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Matrix
from ..rftool_base import RFTool_Base
from ..rfbrush_base import RFBrush_Base
from ..common.bmesh import (
    get_bmesh_emesh, get_object_bmesh,
    clean_select_layers,
    NearestBMVert, NearestBMEdge,
    has_mirror_x, has_mirror_y, has_mirror_z, mirror_threshold,
    crossed_quad,
    bme_other_bmv, bmf_midpoint_radius, bme_other_bmf, bmf_is_quad, quad_bmf_opposite_bme,
    ensure_correct_normals,
    find_selected_cycle_or_path,
)
from ..common.icons import get_path_to_blender_icon
from ..common.operator import (
    invoke_operator, execute_operator,
    RFOperator, RFRegisterClass,
    chain_rf_keymaps, wrap_property,
)
from ..common.maths import (
    bvec_to_point, point_to_bvec3, vector_to_bvec3,
    pt_x0, pt_y0, pt_z0,
    lerp,
)
from ..common.raycast import (
    raycast_valid_sources, raycast_point_valid_sources, raycast_ray_valid_sources,
    nearest_point_valid_sources, nearest_normal_valid_sources, raycast_ray_valid_sources,
    ray_from_point_through_point,
    size2D_to_size,
    vec_forward,
    mouse_from_event,
    plane_normal_from_points,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.colors import Color4
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import (
    Point2D, Point, Normal, Vector, Plane, Ray,
    closest_point_segment,
)
from ...addon_common.common.profiler import time_it
from ...addon_common.common.utils import iter_pairs, rotate_cycle
from ...addon_common.ext.circle_fit import hyperLSQ
from ..common.drawing import (
    Drawing,
    CC_2D_POINTS,
    CC_2D_LINES,
    CC_2D_LINE_STRIP,
    CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES,
    CC_2D_TRIANGLE_FAN,
    CC_3D_TRIANGLES,
)



class Contours_Logic:
    def __init__(self, context, hit, plane, circle_hit, span_count, process_source_method, hits):
        self.hit = hit
        self.plane = plane
        self.circle_hit = circle_hit
        self.process_source_method = process_source_method
        self.hits = hits

        self.action = ''
        self.initial = True

        self.show_span_count = False
        self.span_count = span_count

        self.show_twist = False
        self.twist = 0

        self.cyclic = False

    def update(self, context):
        self.bm, self.em = get_bmesh_emesh(context)
        bmops.flush_selection(self.bm, self.em)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()

        try:
            if not self.process_source(context): return
            self.process_target(context)
            self.find_boundary_for_bridging(context)
            self.insert(context)
        except Exception as e:
            print(f'Exception caught: {e}')
            debugger.print_exception()

        self.initial = False

    def process_source(self, context):
        # process source only once, unless settings have changed
        if not self.initial and self.last_process_source_method == self.process_source_method:
            # print(f'skipping re-processing source')
            return True
        self.last_process_source_method = self.process_source_method

        match self.process_source_method:
            case 'fast':
                return self.process_source_fast(context)
            case 'skip':
                return self.process_source_skip(context)
            case 'walk':
                return self.process_source_walk(context)
            case _:
                assert False, f'Unhandled source processing method "{self.process_source_method}"'

    def process_target(self, context):
        # did we hit current geometry and need to insert an edge loop?
        self.edge_ring = None
        self.cyclic_ring = False
        self.sel_path = None
        self.sel_cyclic = False
        self.bridge = None

        if not self.bm.verts: return

        self.edge_ring = set()

        M = self.matrix_world
        rgn, r3d = context.region, context.region_data
        po3 = self.plane.o
        po2 = location_3d_to_region_2d(rgn, r3d, po3)

        #################################################################################
        # determine if cutting existing geometry by:
        # - find quad-only bmface that crosses the plane and is under mouse
        # - walk around geometry to find edges that should be cut
        hit_co3 = self.hit['co_local']
        hit_co2 = location_3d_to_region_2d(rgn, r3d, self.hit['co_world'])  # same as mouse unless view changes
        inf = float('inf')
        plane_fit = self.plane_fit
        def distance_to_hit(bmf):
            if not bmf_is_quad(bmf): return inf
            center3, radius3 = bmf_midpoint_radius(bmf)
            dist3 = (hit_co3 - center3).length
            if dist3 > radius3: return inf
            center2 = location_3d_to_region_2d(rgn, r3d, M @ center3)
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

    def find_boundary_for_bridging(self, context):
        if not self.bridge: return

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

    def insert(self, context):
        if self.edge_ring:
            # cut in new edge loop
            self.insert_edge_ring(context)
        elif self.bridge:
            # extrude selection to cut
            self.insert_bridge(context)
        else:
            self.insert_new_cut(context)
        bmops.flush_selection(self.bm, self.em)

    def insert_edge_ring(self, context):
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

    def insert_bridge(self, context):
        nbmelems = bmesh.ops.extrude_edge_only(self.bm, edges=self.sel_path)['geom']
        nbmvs = [bmelem for bmelem in nbmelems if type(bmelem) is BMVert]

        self.finish_edgering_bridge(context, nbmelems, nbmvs)
        self.action = 'Bridging Loop' if self.cyclic else 'Bridging Strip'
        self.show_twist = self.cyclic

    def finish_edgering_bridge(self, context, nbmelems, nbmvs):
        plane_fit = self.plane_fit
        circle_fit = self.circle_fit
        points = self.points

        # compute useful statistics about newly created geometry
        npoints = [Point(bmv.co) for bmv in nbmvs]
        nplane_fit = Plane.fit_to_points(npoints)   # local space
        if plane_fit.n.dot(nplane_fit.n) < 0: nplane_fit.n.negate()  # make sure both planes are oriented the same
        ncircle_fit = hyperLSQ([list(nplane_fit.w2l_point(pt).xy) for pt in npoints])

        # compute xforms to roughly move new geometry to match cut
        # instead of scaling based on circle radii, scale X and Y independently based on SVD if fit?
        # the two axes of two planes might not align....  although they _should_ if we're bridging
        T0 = Matrix.Translation(-nplane_fit.l2w_point(Point((ncircle_fit[0], ncircle_fit[1], 0))))
        S  = Matrix.Scale(circle_fit[2] / ncircle_fit[2], 4)
        R  = Matrix.Rotation(-plane_fit.n.angle(nplane_fit.n), 4, plane_fit.n.cross(nplane_fit.n))
        RT = Matrix.Rotation(math.radians(self.twist), 4, plane_fit.n)
        T1 = Matrix.Translation(plane_fit.l2w_point(Point((circle_fit[0], circle_fit[1], 0))))
        xform = T1 @ RT @ R @ S @ T0
        # transform points
        for bmv in nbmvs:
            bmv.co = point_to_bvec3(xform @ bvec_to_point(bmv.co))

        # find closest points between new target and cut source
        best = None
        for bmv in nbmvs:
            npt_local = bvec_to_point(bmv.co)
            npt_world = point_to_bvec3(self.matrix_world @ bvec_to_point(npt_local))
            npt_world_snapped = nearest_point_valid_sources(context, npt_world, world=True)
            npt_local_snapped = self.matrix_world_inv @ npt_world_snapped
            closest_pts = [closest_point_segment(npt_local_snapped, pt0, pt1) for (pt0,pt1) in iter_pairs(points, self.cyclic)]
            closest_pt = min(closest_pts, key=lambda pt:(pt-npt_local_snapped).length)
            dist = (npt_local - closest_pt).length
            if best and best['dist'] <= dist: continue
            best = {
                'bmv': bmv,
                'closest_pt': closest_pt,
                'dist': dist,
            }

        # raycast to nearest surface with fallback to snapping
        o_world = self.matrix_world @ bvec_to_point(plane_fit.l2w_point(Point((circle_fit[0], circle_fit[1], 0))))
        for bmv in nbmvs:
            npt_local = bvec_to_point(bmv.co)
            npt_world = point_to_bvec3(self.matrix_world @ npt_local)
            vec_in = o_world - npt_world
            ray_in_world  = ray_from_point_through_point(context, npt_world, npt_world + vec_in)
            ray_out_world = ray_from_point_through_point(context, npt_world, npt_world - vec_in)
            npt_world_in  = raycast_ray_valid_sources(context, ray_in_world,  world=True)
            npt_world_out = raycast_ray_valid_sources(context, ray_out_world, world=True)
            if npt_world_in:
                if npt_world_out:
                    # choose the closer
                    d_in = (npt_world_in - npt_world).length
                    d_out = (npt_world_out - npt_world).length
                    npt_world_new = npt_world_in if d_in < d_out else npt_world_out
                else:
                    npt_world_new = npt_world_in
            else:
                if npt_world_out:
                    npt_world_new = npt_world_out
                else:
                    # fallback to snapping
                    npt_world_new = nearest_point_valid_sources(context, npt_world, world=True)
            npt_local_snapped = self.matrix_world_inv @ npt_world_new
            if False:
                bmv.co = npt_local_snapped
            else:
                closest_pts = [closest_point_segment(npt_local_snapped, pt0, pt1) for (pt0,pt1) in iter_pairs(points, self.cyclic)]
                bmv.co = min(closest_pts, key=lambda pt:(pt-npt_local_snapped).length)


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


    def insert_new_cut(self, context):
        path_length = self.path_length
        points = []
        for pt in self.points:
            if points and (points[-1] - pt).length == 0: continue
            points += [pt]
        M, Mi = self.matrix_world, self.matrix_world_inv

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
            Mi @ nearest_point_valid_sources(context, M @ pt, world=True) for pt in npts
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

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, nbmvs)


    #######################################################
    # different methods for processing source

    def process_source_fast(self, context):
        plane_cut = self.plane
        hit_obj = self.hit['object']
        M = hit_obj.matrix_world

        center_plane = Vector((self.circle_hit[0], self.circle_hit[1], 0, 1))
        nsamples = 100
        dirs_plane = [
            Vector((math.cos(2 * math.pi * d/nsamples), math.sin(2 * math.pi * d/nsamples), 0, 0))
            for d in range(nsamples)
        ]

        center_world = plane_cut.l2w_point(center_plane)
        dirs_world = [ plane_cut.l2w_direction(dir_plane) for dir_plane in dirs_plane ]
        rays_world = [ (center_world, dir_world) for dir_world in dirs_world ]
        points_world = [
            raycast_ray_valid_sources(context, ray_world, world=True)
            for ray_world in rays_world
        ]

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

        self.points = points                            # points where cut crosses source (target space)
        self.cyclic = cyclic                            # is cut cyclic (loop) or a strip?
        self.plane_fit = plane_fit                      # plane that fits cut points (target space)
        self.circle_fit = circle_fit                    # circle that fits points (plane_fit space)
        self.path_length = path_length                  # length of path of points (target space)
        self.mirror_clipped_loop = mirror_clipped_loop  # did cyclic loop cross mirror plane?

        return True

    def process_source_skip(self, context):
        plane_cut = self.plane
        hit_obj = self.hit['object']
        M = hit_obj.matrix_world

        pt = self.hit['co_world']
        pt0, pt1 = self.hits[0]['co_world'], self.hits[-1]['co_world']
        dist = 0.5 * ((pt - pt0).length + (pt - pt1).length) / 2
        direction = (pt0 - pt).normalized()
        pt_start = pt
        dist_pre = 0

        points = [pt]
        has_shrunk = False
        for i in range(10000):
            # print(f'{pt=} {direction=}')
            pt_next = pt + direction * dist
            for _ in range(10):
                pt_next = nearest_point_valid_sources(context, pt_next, world=True)
                pt_next = plane_cut.w2l_point(pt_next)
                pt_next.z = 0
                pt_next = Vector(plane_cut.l2w_point(pt_next))
            dist_next = (pt_next - pt_start).length
            if dist_next < dist_pre:
                has_shrunk = True
            elif has_shrunk and dist_next < dist * 4:
                print(f'WRAPPED AFTER {i}!')
                break
            points += [pt_next]
            direction = (pt_next - pt).normalized()
            # print(f'{pt=} {pt_next=} {direction=}')
            pt = pt_next
            dist_pre = dist_next
        else:
            print('gah')
            return False

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

        points = [self.matrix_world_inv @ pt for pt in points]
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

    def process_source_walk(self, context):
        '''
        gathers cut info of high-res mesh (hit_obj) starting at hit_bmf
        '''
        plane_cut = self.plane
        hit_obj = self.hit['object']
        M = hit_obj.matrix_world
        hit_bm = get_object_bmesh(hit_obj)
        hit_bmf = hit_bm.faces[self.hit['face_index']]

        # TODO: walk from hit_bmf to find bmf that crosses plane_cut


        ####################################################################################################
        # walk hit object to find all geometry connected to hit_bmf that intersects cut plane
        # note: this will stop at holes that intersect the cut plane (will _not_ walk around them)

        def point_plane_signed_dist(pt): return plane_cut.signed_distance_to(pt)
        def bmv_plane_signed_dist(bmv):  return point_plane_signed_dist(M @ bmv.co)
        def bmv_intersect_plane(bmv):    return (M @ bmv.co) if bmv_plane_signed_dist(bmv) == 0 else None
        def bme_intersect_plane(bme):
            co0, co1 = (M @ bmv.co for bmv in bme.verts)
            s0, s1 = point_plane_signed_dist(co0), point_plane_signed_dist(co1)
            if (s0 <= 0 and s1 <= 0) or (s0 >= 0 and s1 >= 0): return None
            return co0 + (co1 - co0) * (s0 / (s0 - s1))
        def intersect_plane(bmelem):
            fn = bmv_intersect_plane if type(bmelem) is BMVert else bme_intersect_plane
            return fn(bmelem)

        bmf_graph = {}
        bmf_intersections = defaultdict(dict)
        working = { hit_bmf }
        while working:
            bmf = working.pop()
            if bmf in bmf_graph: continue  # already processed
            bmf_graph[bmf] = set()
            for bmelem in chain(bmf.verts, bmf.edges):
                co = intersect_plane(bmelem)
                if not co: continue
                bmfs = set(bmelem.link_faces) - {bmf}
                working |= bmfs
                bmf_graph[bmf] |= bmfs
                bmf_intersections[bmf][bmelem] = co
                for bmf_ in bmfs:
                    bmf_intersections[bmf][bmf_] = co
                    bmf_intersections[bmf_][bmf] = co

        ####################################################################################################
        # find longest cycle or path in bmf_graph

        def find_cycle_or_path():
            longest_path = []
            longest_cycle = []

            start_bmfs = {
                bmf for bmf in bmf_intersections
                if any(
                    (type(bmelem) is BMVert) or (type(bmelem) is BMEdge and len(bmelem.link_faces) == 1)
                    for bmelem in bmf_intersections[bmf]
                )
            }
            if not start_bmfs: start_bmfs = set(bmf_graph.keys())

            for start_bmf in start_bmfs:
                working = [(start_bmf, iter(bmf_graph[start_bmf]))]
                touched = { start_bmf }
                while working:
                    cur_bmf, cur_iter = working[-1]
                    next_bmf = next(cur_iter, None)

                    if not next_bmf:
                        if len(working) > len(longest_path):
                            # found new longest path!
                            longest_path = [bmf for (bmf, _) in working]

                        working.pop()
                        touched.remove(cur_bmf)
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


        ####################################################################################################
        # find points in order

        points = []
        def add_path_end(bmf):
            bmelem = next((
                bmelem for bmelem in bmf_intersections[bmf]
                if type(bmelem) != BMFace and len(bmelem.link_faces) == 1
            ), None)
            return [ self.matrix_world_inv @ bmf_intersections[bmf][bmelem] ] if bmelem else []
        if not cyclic: points += add_path_end(path[0])
        points += [
            self.matrix_world_inv @ bmf_intersections[bmf0][bmf1]
            for (bmf0, bmf1) in iter_pairs(path, cyclic)
        ]
        if not cyclic: points += add_path_end(path[-1])


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

        return True


    def handle_mirrors(self, context, points):
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

        def correct_x(co): return not mx or (1 if co.x > 0 else -1) == sx
        def correct_y(co): return not my or (1 if co.y > 0 else -1) == sy
        def correct_z(co): return not mz or (1 if co.z > 0 else -1) == sz
        def correct_xyz(co): return correct_x(co) and correct_y(co) and correct_z(co)

        if mx and any(not correct_x(pt) for pt in points) and any(correct_x(pt) for pt in points):
            l = len(points)
            idx = next((i for i in range(l) if not correct_x(points[i]) and correct_x(points[(i+1)%l])), 0)
            points = points[idx:] + points[:idx]
            idx = next((i for i in range(1, l) if correct_x(points[i-1]) and not correct_x(points[i])), 0)
            points = points[:idx+1]
            points = [pt_x0(points[0], points[1])] + points[1:-2] + [pt_x0(points[-2], points[-1])]
            mirror_clipped_loop = True

        if my and any(not correct_y(pt) for pt in points) and any(correct_y(pt) > 0 for pt in points):
            l = len(points)
            idx = next((i for i in range(l) if not correct_y(points[i]) and correct_y(points[(i+1)%l])), 0)
            points = points[idx:] + points[:idx]
            idx = next((i for i in range(1, l) if correct_y(points[i-1]) and not correct_y(points[i])), 0)
            points = points[:idx+1]
            points = [pt_y0(points[0], points[1])] + points[1:-2] + [pt_y0(points[-2], points[-1])]
            mirror_clipped_loop = True

        if mz and any(not correct_z(pt) for pt in points) and any(correct_z(pt) for pt in points):
            l = len(points)
            idx = next((i for i in range(l) if not correct_z(points[i]) and correct_z(points[(i+1)%l])), 0)
            points = points[idx:] + points[:idx]
            idx = next((i for i in range(1, l) if correct_z(points[i-1]) and not correct_z(points[i])), 0)
            points = points[:idx+1]
            points = [pt_z0(points[0], points[1])] + points[1:-2] + [pt_z0(points[-2], points[-1])]
            mirror_clipped_loop = True

        return (points, mirror_clipped_loop)

