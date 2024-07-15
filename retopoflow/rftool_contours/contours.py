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
)
from ..common.icons import get_path_to_blender_icon
from ..common.operator import invoke_operator, execute_operator, RFOperator, RFRegisterClass, chain_rf_keymaps, wrap_property
from ..common.raycast import (
    raycast_valid_sources, raycast_point_valid_sources,
    nearest_point_valid_sources,
    size2D_to_size,
    vec_forward,
    mouse_from_event,
    plane_normal_from_points,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import Point2D, Point, Normal, Vector, Plane, closest_point_segment
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
                pm = Point2D.average((self.mouse, self.mousedown))
                self.hit = raycast_valid_sources(context, pm)

        if event.type == 'MOUSEMOVE' and self.mousedown:
            context.area.tag_redraw()

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.mousedown = self.mouse
            context.area.tag_redraw()

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            # do something with self.mousedown and self.mouse and self.hit
            if self.hit:
                t0 = time.time()
                self.new_cut(context, contours.initial_cut_count)
                print(f'time for new cut: {time.time() - t0}')
            self.mousedown = None
            self.hit = None
            context.area.tag_redraw()

    def new_cut(self, context, vertex_count):
        M_local = context.edit_object.matrix_world
        Mi_local = M_local.inverted()
        plane_cut = Plane(
            self.hit['co_world'],
            plane_normal_from_points(context, self.mousedown, self.mouse),
        )

        hit_obj = self.hit['object']
        M = hit_obj.matrix_world
        hit_bm = get_object_bmesh(hit_obj)
        print(f'{hit_bm=}')
        hit_bmf = hit_bm.faces[self.hit['face_index']]

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

        # find all geometry connected to hit_bmf that intersects cut plane
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
        print(f'{len(path)=} {cyclic=}')
        if len(path) < 2:
            print(f'PATH TOO SHORT')
            return

        # find points in order
        points = []
        def add_path_end(bmf):
            bmelem = next((
                bmelem for bmelem in bmf_intersections[bmf]
                if type(bmelem) != BMFace and len(bmelem.link_faces) == 1
            ), None)
            if not bmelem: return
            points.append(Mi_local @ bmf_intersections[bmf][bmelem])
        if not cyclic:
            add_path_end(path[0])
        for (bmf0, bmf1) in iter_pairs(path, False):
            points.append(Mi_local @ bmf_intersections[bmf0][bmf1])
        if not cyclic:
            add_path_end(path[-1])

        # handle cutting across mirror planes
        def dir01(pt0, pt1): return (v := pt1 - pt0) / v.length
        def pt_x0(pt0, pt1):
            pt = pt0 + dir01(pt0, pt1) * abs(pt0.x)
            pt.x = 0
            return pt
        def pt_y0(pt0, pt1):
            pt = pt0 + dir01(pt0, pt1) * abs(pt0.y)
            pt.y = 0
            return pt
        def pt_z0(pt0, pt1):
            pt = pt0 + dir01(pt0, pt1) * abs(pt0.z)
            pt.z = 0
            return pt

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
                vertex_count = vertex_count // 2 + 1
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

        # fit plane to points
        plane_fit = Plane.fit_to_points(points)
        circle_fit = hyperLSQ([list(plane_fit.w2l_point(pt).xy) for pt in points])
        avg_radius = sum((pt - plane_fit.o).length for pt in points) / len(points)
        print(f'{plane_fit=}')
        print(f'{avg_radius=}')
        print(f'{circle_fit=}')



        # compute length
        path_length = sum((pt0 - pt1).length for (pt0, pt1) in iter_pairs(points, cyclic))
        print(f'{path_length=}')


        # should we bridge with currently selected geometry?
        def find_selected_cycle_or_path():
            selected = bmops.get_all_selected(self.bm)

            longest_path = []
            longest_cycle = []

            def vert_selected(bme):
                yield from (bmv for bmv in bme.verts if bmv in selected[BMVert])
            def link_edge_selected(bmv):
                yield from (bme for bme in bmv.link_edges if bme in selected[BMEdge])
            def adjacent_selected_bmedges(bme):
                for bmv in bme.verts:
                    if bmv not in selected[BMVert]: continue
                    for bme_ in bmv.link_edges:
                        if bme_ not in selected[BMEdge]: continue
                        if bme_ == bme: continue
                        yield bme_
            start_bmes = {
                bme for bme in selected[BMEdge]
                if len(list(adjacent_selected_bmedges(bme))) == 1
            }
            if not start_bmes: start_bmes = selected[BMEdge]
            for start_bme in start_bmes:
                working = [(start_bme, adjacent_selected_bmedges(start_bme))]
                touched = {start_bme}
                while working:
                    cur_bme, cur_iter = working[-1]
                    next_bme = next(cur_iter, None)
                    if not next_bme:
                        if len(working) > len(longest_path):
                            longest_path = [bme for (bme,_) in working]
                        working.pop()
                        touched.remove(cur_bme)
                        continue
                    if next_bme in touched:
                        if next_bme == start_bme and len(working) > 2 and len(working) > len(longest_cycle):
                            longest_cycle = [bme for (bme,_) in working]
                        continue
                    touched.add(next_bme)
                    working.append((next_bme, adjacent_selected_bmedges(next_bme)))
                if len(longest_cycle) > 50:
                    break
            is_cyclic = len(longest_cycle) >= len(longest_path) * 0.5
            return (longest_cycle if is_cyclic else longest_path, is_cyclic)
        sel_path, sel_cyclic = find_selected_cycle_or_path()

        print(f'{len(sel_path)=} {sel_cyclic=}')
        print(f'{cyclic == sel_cyclic}')
        bridge = len(sel_path) > 0 and (cyclic == sel_cyclic)
        if bridge:
            nbmelems = bmesh.ops.extrude_edge_only(self.bm, edges=sel_path)['geom']
            nbmvs = [bmelem for bmelem in nbmelems if type(bmelem) is BMVert]
            npoints = [Point(bmv.co) for bmv in nbmvs]
            nplane_fit = Plane.fit_to_points(npoints)
            ncircle_fit = hyperLSQ([list(nplane_fit.w2l_point(pt).xy) for pt in npoints])
            navg_radius = sum((pt - nplane_fit.o).length for pt in npoints) / len(npoints)
            print(f'{nplane_fit=}')
            print(f'{navg_radius=}')
            print(f'{ncircle_fit=}')
            R = Matrix.Rotation(
                -plane_fit.n.angle(nplane_fit.n),
                4,
                plane_fit.n.cross(nplane_fit.n),
            )
            # instead of scaling based on circle radii, scale X and Y independently based on SVD if fit?
            # the two axes of two planes might not align....  although they _should_ if we're bridging
            S  = Matrix.Scale(circle_fit[2] / ncircle_fit[2], 4) # Matrix.Scale(avg_radius / navg_radius, 4)
            T0 = Matrix.Translation(-nplane_fit.l2w_point(Point((ncircle_fit[0], ncircle_fit[1], 0)))) # Matrix.Translation(-nplane_fit.o)
            T1 = Matrix.Translation(plane_fit.l2w_point(Point((circle_fit[0], circle_fit[1], 0)))) # Matrix.Translation(plane_fit.o)
            M = T1 @ R @ S @ T0
            for bmv in nbmvs:
                npt = M @ Vector((*bmv.co, 1))
                npt_world = M_local @ npt
                npt_world_snapped = nearest_point_valid_sources(context, npt_world.xyz / npt_world.w, world=True)
                bmv.co = Mi_local @ npt_world_snapped

            if not cyclic:
                # snap ends
                bmv_ends = [bmv for bmv in nbmvs if len(bmv.link_faces) == 1]
                if len(bmv_ends) != 2:
                    print(f'FOUND {len(bmv_ends)} ENDS ON NON-CYCLIC PATH!?')
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
            bmesh.ops.recalc_face_normals(self.bm, faces=nbmfs)

            select_now = nbmvs
            select_later = []
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
            return

            # vertex_count = len(sel_path) if sel_cyclic else len(sel_path)+1
            # if cyclic:
            #     # find selected BMVert that is closest to cut
            #     sel_verts = [shared_bmv(bme0, bme1) for (bme0, bme1) in iter_pairs(sel_path, True)]
            #     sel_verts = rotate_cycle(sel_verts, 1)
            #     closest = None
            #     for j, bmv in enumerate(sel_verts):
            #         for i,(pt0,pt1) in enumerate(iter_pairs(points, cyclic)):
            #             pt = closest_point_segment(bmv.co, pt0, pt1)
            #             dist = (pt - bmv.co).length
            #             if closest and closest['dist'] <= dist: continue
            #             closest = {
            #                 'bmv':  bmv,
            #                 'i':    i,
            #                 'j':    j,
            #                 'pt0':  pt0,
            #                 'pt1':  pt1,
            #                 'pt':   pt,
            #                 'dist': dist,
            #             }
            #     print(closest)
            #     points = rotate_cycle(points, -closest['i'])
            #     sel_path = rotate_cycle(sel_path, -closest['j'])
            #     sel_verts = rotate_cycle(sel_verts, -closest['j'])
            #     pt0, pt1 = points[-1], points[1]
            #     co0, co1 = sel_verts[-1].co, sel_verts[1].co
            #     if (pt0 - co0).length + (pt1 - co1).length > (pt0 - co1).length + (pt1 - co0).length:
            #         sel_path = list(sel_path[::-1])

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
        # nbmvs = [ self.bm.verts.new(co) for co in points ]  # debug: use all points
        print(f'created {len(nbmvs)} BMVerts')
        select_now = list(nbmvs)
        select_later = []
        bmes = [self.bm.edges.new((bmv0, bmv1)) for (bmv0, bmv1) in iter_pairs(nbmvs, cyclic)]
        print(f'created {len(bmes)} BMEdges')

        if not cyclic:
            # snap ends
            bmv_ends = [bmv for bmv in nbmvs if len(bmv.link_edges) == 1]
            print(f'FOUND {len(bmv_ends)} ENDS ON NON-CYCLIC PATH')
            if len(bmv_ends) == 2:
                bmv0, bmv1 = bmv_ends
                co0, co1 = bmv0.co, bmv1.co
                pt0, pt1 = points[0], points[-1]
                if (co0 - pt0).length + (co1 - pt1).length < (co0 - pt1).length + (co1 - pt0).length:
                    bmv0.co, bmv1.co = pt0, pt1
                else:
                    bmv0.co, bmv1.co = pt1, pt0

        # if bridge:
        #     bmfs = []
        #     for bme0, bme1 in zip(bmes, sel_path):
        #         if crossed_quad(bme0.verts[0].co, bme0.verts[1].co, bme1.verts[0].co, bme1.verts[1].co):
        #             bmf = self.bm.faces.new([bme0.verts[0], bme0.verts[1], bme1.verts[1], bme1.verts[0]])
        #         else:
        #             bmf = self.bm.faces.new([bme0.verts[0], bme0.verts[1], bme1.verts[0], bme1.verts[1]])
        #         bmfs.append(bmf)
        #     bmesh.ops.recalc_face_normals(self.bm, faces=bmfs)

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


# class RFOperator_Contours_Select(RFOperator):
#     bl_idname = 'retopoflow.contours_select'
#     bl_label = 'Contours Select'
#     bl_description = 'Select geometry for Contours'
#     bl_space_type = 'VIEW_3D'
#     bl_region_type = 'TOOLS'
#     bl_options = set()
#     rf_keymaps = [
#         (bl_idname, {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, None),
#     ]
#     def init(self, context, event):
#         pass
#     def update(self, context, event):

# @invoke_operator('contours_select', 'Contours Select', description='Select geometry for Contours')
# def invoke_contours_select(context, event):
#     bpy.ops.mesh.loop_multi_select(ring=False)


class RFOperator_Contours(RFOperator):
    bl_idname = 'retopoflow.contours'
    bl_label = 'Contours'
    bl_description = 'Retopologize cylindrical forms, like arms and legs'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),
        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, None),
        # ('retopoflow.contours_select', {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, None),
        ('mesh.loop_multi_select', {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, None),
    ]

    rf_status = ['LMB: Insert']

    initial_cut_count: bpy.props.IntProperty(
        name='Initial Count',
        description='Number of vertices to create in a new cut',
        default=8,
        min=3,
        max=100,
    )

    def init(self, context, event):
        self.logic = Contours_Logic(context, event)
        self.tickle(context)

    def reset(self):
        self.logic.reset()

    def update(self, context, event):
        self.logic.update(context, event, self)

        if not event.ctrl:
            self.logic.cleanup()
            Cursors.restore()
            return {'FINISHED'}
        else:
            Cursors.set('CROSSHAIR')


        if self.logic.mousedown:
            return {'RUNNING_MODAL'}


        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!

    def draw_postpixel(self, context):
        self.logic.draw(context)


class RFTool_Contours(RFTool_Base):
    bl_idname = "retopoflow.contours"
    bl_label = "Contours"
    bl_description = "Retopologize cylindrical forms, like arms and legs"
    bl_icon = get_path_to_blender_icon('contours')
    bl_widget = None
    bl_operator = 'retopoflow.contours'

    # rf_brush = RFBrush_Contours()

    bl_keymap = chain_rf_keymaps(RFOperator_Contours) #, RFOperator_Contours_Select)

    def draw_settings(context, layout, tool):
        layout.label(text='Cut:')
        props = tool.operator_properties(RFOperator_Contours.bl_idname)
        layout.prop(props, 'initial_cut_count')

    @classmethod
    def activate(cls, context):
        cls.reseter = Reseter()
        cls.reseter['context.tool_settings.use_mesh_automerge'] = False
        cls.reseter['context.tool_settings.snap_elements_individual'] = {'FACE_NEAREST'}

    @classmethod
    def deactivate(cls, context):
        cls.reseter.reset()
