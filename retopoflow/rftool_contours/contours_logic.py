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
    shared_bmv, crossed_quad,
    bme_other_bmv,
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
    def __init__(self, context, event):
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.update_bmesh_selection = False
        self.mouse = Point2D(mouse_from_event(event))
        self.mousedown = None
        self.hit = None
        self.reset()
        self.update(context, event, 16)

    def reset(self):
        self.bm = None
        self.em = None
        self.selected = None

    def cleanup(self):
        clean_select_layers(self.bm)

    def update(self, context, event, contours):
        if not self.bm or not self.bm.is_valid:
            self.bm, self.em = get_bmesh_emesh(context)
            self.layer_sel_vert, self.layer_sel_edge, self.layer_sel_face = bmops.get_select_layers(self.bm)
            self.selected = None
            self.nearest = None
            self.nearest_bme = None

        if self.update_bmesh_selection:
            self.update_bmesh_selection = False
            self.bm.select_history.validate()
            active = self.bm.select_history.active
            for bmv in self.bm.verts:
                if bmv[self.layer_sel_vert] == 0: continue
                # bmv.select_set(bmv[self.layer_sel_vert] == 1)
                bmops.select(self.bm, bmv)
                bmv[self.layer_sel_vert] = 0
            for bme in self.bm.edges:
                if bme[self.layer_sel_edge] == 0: continue
                for bmv in bme.verts:
                    # bmv.select_set(True)
                    bmops.select(self.bm, bmv)
                bme[self.layer_sel_edge] = 0
            for bmf in self.bm.faces:
                if bmf[self.layer_sel_face] == 0: continue
                for bmv in bmf.verts:
                    # bmv.select_set(True)
                    bmops.select(self.bm, bmv)
                bmf[self.layer_sel_face] = 0
            if active: bmops.reselect(self.bm, active)
            bmops.flush_selection(self.bm, self.em)
            # bpy.ops.mesh.normals_make_consistent('EXEC_DEFAULT', False)
            # bpy.ops.ed.undo_push(message='Selected geometry after move')
            self.selected = None

        self.mouse = Point2D(mouse_from_event(event))
        if self.mousedown and self.mouse:
            if (self.mousedown - self.mouse).length < Drawing.scale(8):
                self.hit = None
            else:
                self.mousemiddle = Point2D.average((self.mouse, self.mousedown))
                self.hit = raycast_valid_sources(context, self.mousemiddle)

        if event.type == 'MOUSEMOVE' and self.mousedown:
            context.area.tag_redraw()

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.mousedown = self.mouse
            context.area.tag_redraw()

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            # do something with self.mousedown and self.mouse and self.hit
            if self.hit:
                self.new_cut(context, contours.initial_cut_count)
            self.mousedown = None
            self.hit = None
            context.area.tag_redraw()

    def generate_cut_info(self, context, plane_cut, hit_obj, hit_bmf):
        '''
        generates cut info of high-res mesh (hit_obj) starting at hit_bmf
        '''
        M = hit_obj.matrix_world

        # TODO: walk from hit_bmf to find bmf that crosses plane_cut

        ####################################################################################################
        # walk hit object to find all geometry connected to hit_bmf that intersects cut plane
        # note: this will stop at holes that intersect the cut plane (will _not_ walk around them)
        def point_plane_signed_dist(pt): return plane_cut.signed_distance_to(pt)
        def bmv_plane_signed_dist(bmv):  return point_plane_signed_dist(M @ bmv.co)
        def bmv_intersect_plane(bmv):    return (M @ bmv.co) if bmv_plane_signed_dist(bmv) == 0 else None
        def bme_intersect_plane(bme):
            bmv0, bmv1 = bme.verts
            co0, co1 = M @ bmv0.co, M @ bmv1.co
            s0, s1 = point_plane_signed_dist(co0), point_plane_signed_dist(co1)
            if (s0 <= 0 and s1 <= 0) or (s0 >= 0 and s1 >= 0): return None
            f = s0 / (s0 - s1)
            return co0 + (co1 - co0) * f
        def intersect_plane(bmelem):
            fn = bmv_intersect_plane if type(bmelem) is BMVert else bme_intersect_plane
            return fn(bmelem)
        bmf_graph = {}
        bmf_intersections = defaultdict(dict)
        working = { hit_bmf }
        while working:
            bmf = working.pop()
            if bmf in bmf_graph: continue
            bmf_graph[bmf] = set()
            for bmelem in chain(bmf.verts, bmf.edges):
                co = intersect_plane(bmelem)
                if not co: continue
                bmfs = set(bmelem.link_faces)
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
                if any(type(bmelem) is BMVert for bmelem in bmf_intersections[bmf])
                or any(type(bmelem) is BMEdge and len(bmelem.link_faces) == 1 for bmelem in bmf_intersections[bmf])
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
            return None

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
            for (bmf0, bmf1) in iter_pairs(path, False)
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
            return None


        ####################################################################################################
        # compute useful statistics about points
        plane_fit = Plane.fit_to_points(points)
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))

        return {
            'points': points,
            'cyclic': cyclic,
            'plane_fit': plane_fit,
            'circle_fit': circle_fit,
            'path_length': path_length,
            'mirror_clipped_loop': mirror_clipped_loop,
        }


    def new_cut(self, context, vertex_count):
        plane_cut = Plane(
            self.hit['co_world'],
            plane_normal_from_points(context, self.mousedown, self.mouse),
        )

        hit_obj = self.hit['object']
        M = hit_obj.matrix_world
        hit_bm = get_object_bmesh(hit_obj)
        hit_bmf = hit_bm.faces[self.hit['face_index']]

        cut_info = self.generate_cut_info(context, plane_cut, hit_obj, hit_bmf)
        if not cut_info: return
        points       = cut_info['points']
        cyclic       = cut_info['cyclic']
        plane_fit    = cut_info['plane_fit']
        circle_fit   = cut_info['circle_fit']
        path_length  = cut_info['path_length']
        if cut_info['mirror_clipped_loop']:
            # update vertex count, because the loop crosses mirror
            vertex_count = vertex_count // 2 + 1

        # did we hit current geometry and need to insert an edge loop?
        edge_ring = None
        if self.bm.verts:
            # find bmedges that cross the plane
            edge_ring = set()
            bmes = { bme for bme in self.bm.edges if plane_fit.edge_crosses((bme.verts[0].co, bme.verts[1].co)) }
            for bmf in (bmf for bme in bmes for bmf in bme.link_faces):
                if len(bmf.edges) != 4: continue
                center3 = sum((bmv.co for bmv in bmf.verts), Vector((0,0,0))) / len(bmf.verts)
                radius3 = max((bmv.co - center3).length for bmv in bmf.verts)
                dist3 = (self.hit['co_local'] - center3).length
                pts2d = [
                    location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv.co)
                    for bmv in bmf.verts
                ]
                center2 = sum(pts2d, Vector((0,0))) / len(pts2d)
                radius2 = max((pt2d - center2).length for pt2d in pts2d)
                dist2 = (self.mousemiddle - center2).length
                if dist3 > radius3 or dist2 > radius2: continue
                edge_ring = set()
                cyclic_ring = False
                first_attempt = True
                for bme in {bme for bme in bmf.edges if bme in bmes}:
                    pre_bmf = bmf
                    while True:
                        if bme in edge_ring:
                            if first_attempt:
                                cyclic_ring = True
                            break
                        edge_ring.add(bme)
                        next_bmf = next((bmf for bmf in bme.link_faces if bmf != pre_bmf), None)
                        if not next_bmf or len(next_bmf.edges) != 4: break
                        bme = next(bme_ for bme_ in next_bmf.edges if not shared_bmv(bme, bme_))
                        pre_bmf = next_bmf
                    first_attempt = False
                break
            if edge_ring:
                cyclic = cyclic_ring
                print(f'{len(edge_ring)=} {cyclic=}')

        # should we bridge with currently selected geometry?
        sel_path, sel_cyclic = find_selected_cycle_or_path(self.bm, self.hit['co_local'])
        bridge = sel_path and (cyclic == sel_cyclic)

        ####################################################################################################
        # create new geometry!

        if bridge or edge_ring:
            if edge_ring:
                # cut in new edge loop
                bmeloops = {
                    bme_
                    for bme in edge_ring
                    for bmf in bme.link_faces
                    for bme_ in bmf.edges
                } - edge_ring
                # USE SELECTION TO FIGURE OUT WHICH VERTS ARE NEW!
                bmops.deselect_all(self.bm)
                bmops.select_iter(self.bm, bmeloops)
                nbmelems = bmesh.ops.subdivide_edgering(self.bm, edges=list(edge_ring), cuts=1)['faces']
                nbmvs = list({ bmv for bmf in nbmelems for bmv in bmf.verts if not bmv.select })
                npoints = [Point(bmv.co) for bmv in nbmvs]

            elif bridge:
                # extrude selection to cut
                nbmelems = bmesh.ops.extrude_edge_only(self.bm, edges=sel_path)['geom']
                nbmvs = [bmelem for bmelem in nbmelems if type(bmelem) is BMVert]
                npoints = [Point(bmv.co) for bmv in nbmvs]

            else:
                assert False, f'Contours: should never reach here'

            # compute useful statistics about newly created geometry
            nplane_fit = Plane.fit_to_points(npoints)
            ncircle_fit = hyperLSQ([list(nplane_fit.w2l_point(pt).xy) for pt in npoints])

            # compute xforms to roughly move new geometry to match cut
            # instead of scaling based on circle radii, scale X and Y independently based on SVD if fit?
            # the two axes of two planes might not align....  although they _should_ if we're bridging
            R  = Matrix.Rotation(-plane_fit.n.angle(nplane_fit.n), 4, plane_fit.n.cross(nplane_fit.n))
            S  = Matrix.Scale(circle_fit[2] / ncircle_fit[2], 4)
            T0 = Matrix.Translation(-nplane_fit.l2w_point(Point((ncircle_fit[0], ncircle_fit[1], 0))))
            T1 = Matrix.Translation(plane_fit.l2w_point(Point((circle_fit[0], circle_fit[1], 0))))
            xform = T1 @ R @ S @ T0
            # transform all points, then snap to surface
            for bmv in nbmvs:
                npt = xform @ bvec_to_point(bmv.co)
                npt_world = point_to_bvec3(self.matrix_world @ npt)
                npt_world_snapped = nearest_point_valid_sources(context, npt_world, world=True)
                npt_local_snapped = self.matrix_world_inv @ npt_world_snapped
                # should find closest point in points?
                bmv.co = min(((pt, (pt-npt_local_snapped).length) for pt in points), key=lambda ptd:ptd[1])[0]

            if not cyclic:
                # snap ends
                if edge_ring:
                    bmv_ends = [bmv for bmv in nbmvs if len(bmv.link_faces) == 2]
                else:
                    bmv_ends = [bmv for bmv in nbmvs if len(bmv.link_faces) == 1]
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

            # make sure face normals are correct.  cannot do this earlier, because
            # faces have no defined normal (verts overlap)
            nbmfs = [bmelem for bmelem in nbmelems if type(bmelem) is BMFace]
            ensure_correct_normals(self.bm, nbmfs)

            select_now = nbmvs
            select_later = []

        else:
            # find pts for new geometry
            # note: might need to take a few attempts due to numerical precision
            segment_count = vertex_count if cyclic else (vertex_count - 1)
            true_segment_length = path_length / segment_count
            factor_min, factor_max = 0.8, 1.2
            for _ in range(100):
                factor = (factor_min + factor_max) / 2
                segment_length = true_segment_length * factor
                dist, npts = 0, []
                for pt0, pt1 in iter_pairs(points, cyclic):
                    v = pt1 - pt0
                    l = v.length
                    if dist > l:
                        dist -= l
                        continue
                    d = v / l
                    pt = pt0
                    while dist <= l:
                        pt = pt + d * dist
                        npts.append(pt)
                        l -= dist
                        dist = segment_length
                if not cyclic: npts.append(points[-1])
                diff = vertex_count - len(npts)
                if diff == 0:
                    error = sum((pt0-pt1).length - true_segment_length for (pt0, pt1) in iter_pairs(points, cyclic))
                    (factor_min, factor_max) = (factor_min, factor) if error < 0 else (factor, factor_max)
                else:
                    (factor_min, factor_max) = (factor_min, factor) if diff > 0 else (factor, factor_max)

            # create geometry!
            nbmvs = [ self.bm.verts.new(pt) for pt in npts[:vertex_count] ]
            select_now = list(nbmvs)
            select_later = []
            bmes = [self.bm.edges.new((bmv0, bmv1)) for (bmv0, bmv1) in iter_pairs(nbmvs, cyclic)]

            if not cyclic:
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

        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, select_now)
        bmops.select_later_iter(self.bm, select_later)
        self.update_bmesh_selection = bool(select_later)
        self.nearest = None
        self.hit = None
        self.selected = None

        bmops.flush_selection(self.bm, self.em)
        bmesh.update_edit_mesh(self.em)
        bpy.ops.ed.undo_push(message='Contours new cut')


    def draw(self, context):
        if not self.mousedown: return
        p0 = self.mousedown
        p1 = self.mouse
        pm = Point2D.average((p0, p1))
        d01 = (p1 - p0).normalized() * Drawing.scale(8)

        with Drawing.draw(context, CC_2D_LINES) as draw:
            draw.line_width(2)
            if self.hit:
                draw.stipple(pattern=[5,5], offset=0, color=Color4((255/255, 255/255, 40/255, 0.0)))
                draw.color(Color4((255/255, 255/255, 40/255, 0.5)))
            else:
                draw.stipple(pattern=[5,5], offset=0, color=Color4((192/255, 30/255, 30/255, 0.0)))
                draw.color(Color4((192/255, 30/255, 30/255, 0.5)))
            draw.vertex(pm-d01).vertex(p0)
            draw.vertex(pm+d01).vertex(p1)

        with Drawing.draw(context, CC_2D_POINTS) as draw:
            draw.point_size(8)
            if self.hit:
                draw.color(Color4((255/255, 255/255, 255/255, 1.0)))
            else:
                draw.color(Color4((255/255, 40/255, 40/255, 1.0)))
            draw.vertex(pm)

