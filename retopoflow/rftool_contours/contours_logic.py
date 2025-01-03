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
from itertools import chain
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
    raycast_valid_sources, raycast_point_valid_sources,
    nearest_point_valid_sources, nearest_normal_valid_sources,
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
    Point2D, Point, Normal, Vector, Plane,
    closest_point_segment,
)
from ...addon_common.common.reseter import Reseter
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
    def __init__(self, context, initial, hit, plane, span_count, twist):
        self.bm, self.em = get_bmesh_emesh(context)
        bmops.flush_selection(self.bm, self.em)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.context, self.rgn, self.r3d = context, context.region, context.region_data

        self.plane = plane
        self.hit = hit

        self.action = ''
        self.span_count = span_count
        self.show_span_count = False
        self.twist = twist % 360
        self.show_twist = False

        try:
            if not self.process_source(): return
            self.process_target()
            self.insert()
        except Exception as e:
            print(f'Exception caught: {e}')
            debugger.print_exception()

    def process_source(self):
        '''
        gathers cut info of high-res mesh (hit_obj) starting at hit_bmf
        '''
        context = self.context
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



        ####################################################################################################
        # handle cutting across mirror planes

        mirror_clipped_loop = False
        if has_mirror_x(context) and any(pt.x < 0 for pt in points):
            # NOTE: considers ONLY the positive x side of mirror!
            l = len(points)
            bpoints = []
            if cyclic:
                start_indices = [i for i in range(l) if points[i].x < 0 and points[(i+1)%l].x >= 0]
                for start_index in start_indices:
                    npoints = []
                    for offset in range(l):
                        i0, i1 = (start_index + offset) % l, (start_index + offset + 1) % l
                        pt0, pt1 = points[i0], points[i1]
                        if pt0.x >= 0:
                            npoints.append(pt0)
                            if pt1.x < 0:
                                npoints.append(pt_x0(pt0, pt1))
                                break
                        elif pt1.x >= 0: npoints.append(pt_x0(pt0, pt1))
                    if len(npoints) > len(bpoints): bpoints = npoints
                mirror_clipped_loop = True
            else:
                npoints = []
                for i in range(l):
                    if points[i].x >= 0:
                        if i > 0 and points[i-1].x < 0:
                            npoints.append(pt_x0(points[i-1], points[i]))
                        npoints.append(points[i])
                    else:
                        if i > 0 and points[i-1].x >= 0:
                            npoints.append(pt_x0(points[i-1], points[i]))
                        if len(npoints) > len(bpoints): bpoints = npoints
                        npoints = []
            points = bpoints
            cyclic = False
        # TODO: handle other mirror planes!

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

    def process_target(self):
        # did we hit current geometry and need to insert an edge loop?
        self.edge_ring = None
        self.cyclic_ring = False
        self.sel_path = None
        self.sel_cyclic = False
        self.bridge = None

        if not self.bm.verts: return

        self.edge_ring = set()

        M = self.matrix_world
        rgn, r3d = self.rgn, self.r3d
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
            # update cyclic to match cut-into geometry
            # TODO: DO NOT OVERRIDE THIS HERE...
            self.cyclic = self.cyclic_ring

        # should we bridge with currently selected geometry?
        self.sel_path, self.sel_cyclic = find_selected_cycle_or_path(self.bm, hit_co3)
        self.bridge = bool(self.sel_path) and (self.cyclic == self.sel_cyclic)

    def insert(self):
        if self.edge_ring:
            # cut in new edge loop
            self.insert_edge_ring()
        elif self.bridge:
            # extrude selection to cut
            self.insert_bridge()
        else:
            self.insert_new_cut()
        bmops.flush_selection(self.bm, self.em)

    def insert_edge_ring(self):
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

        self.finish_edgering_bridge(nbmelems, nbmvs)
        self.action = 'Loop Cut' if self.cyclic else 'Strip Cut'
        self.show_twist = True

    def insert_bridge(self):
        nbmelems = bmesh.ops.extrude_edge_only(self.bm, edges=self.sel_path)['geom']
        nbmvs = [bmelem for bmelem in nbmelems if type(bmelem) is BMVert]

        self.finish_edgering_bridge(nbmelems, nbmvs)
        self.action = 'Bridging Loop' if self.cyclic else 'Bridging Strip'
        self.show_twist = True

    def finish_edgering_bridge(self, nbmelems, nbmvs):
        plane_fit = self.plane_fit
        circle_fit = self.circle_fit
        points = self.points

        # compute useful statistics about newly created geometry
        npoints = [Point(bmv.co) for bmv in nbmvs]
        nplane_fit = Plane.fit_to_points(npoints)
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
        # transform all points, then snap to surface
        for bmv in nbmvs:
            npt = xform @ bvec_to_point(bmv.co)
            npt_world = point_to_bvec3(self.matrix_world @ npt)
            npt_world_snapped = nearest_point_valid_sources(self.context, npt_world, world=True)
            npt_local_snapped = self.matrix_world_inv @ npt_world_snapped
            # should find closest point in points?
            closest_pts = [closest_point_segment(npt_local_snapped, pt0, pt1) for (pt0,pt1) in iter_pairs(points, self.cyclic)]
            bmv.co = min(closest_pts, key=lambda pt:(pt-npt_local_snapped).length)

            # bmv.co = min(((pt, (pt-npt_local_snapped).length) for pt in points), key=lambda ptd:ptd[1])[0]

            # bmv.co = self.matrix_world_inv @ npt_world

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


    def insert_new_cut(self):
        path_length = self.path_length
        points = self.points

        segment_count = self.span_count
        vertex_count = self.span_count if self.cyclic else self.span_count + 1
        if self.mirror_clipped_loop:
            # update vertex count, because the loop crosses mirror
            vertex_count = vertex_count // 2 + 1

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

