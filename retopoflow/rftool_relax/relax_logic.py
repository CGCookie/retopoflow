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

import blf
import bmesh
import bpy
import gpu
from bmesh.types import BMVert, BMEdge, BMFace
from bmesh.utils import edge_split
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_line_2d
from mathutils.bvhtree import BVHTree

import math
import time

from ..common.bmesh import get_bmesh_emesh, NearestBMVert
from ..common.maths import point_to_bvec4
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, nearest_point_valid_sources, mouse_from_event

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import closest_point_segment, Point


class Relax_Logic:
    def __init__(self, context, event, brush, relax):
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.mouse = None

        self.brush = brush
        self.relax = relax

        self.bm, self.em = get_bmesh_emesh(context)
        self.bm.faces.ensure_lookup_table()
        self._time = time.time()

        self.prev = {}

        self._boundary = []
        if relax.mask_boundary == 'SLIDE':
            self._boundary = [
                (bme.verts[0].co, bme.verts[1].co)
                for bme in self.bm.edges
                if not bme.is_manifold
            ]

    def cancel(self, context):
        for (bmv, co) in self.prev.items():
            bmv.co = co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()


    def update(self, context, event):
        if event.type != 'TIMER': return

        hit = raycast_valid_sources(context, mouse_from_event(event))
        if not hit: return

        brush = self.brush
        relax = self.relax

        # gather options
        opt_mask_boundary   = relax.mask_boundary
        opt_mask_symmetry   = relax.mask_symmetry
        opt_mask_occluded   = relax.mask_occluded
        opt_mask_selected   = relax.mask_selected
        opt_steps           = relax.algorithm_iterations
        opt_mult            = relax.algorithm_strength
        opt_edge_length     = relax.algorithm_average_edge_lengths
        opt_straight_edges  = relax.algorithm_straighten_edges
        opt_face_radius     = relax.algorithm_average_face_radius
        opt_face_sides      = relax.algorithm_average_face_lengths
        opt_face_angles     = relax.algorithm_average_face_angles
        opt_correct_flipped = relax.algorithm_correct_flipped_faces

        def is_bmvert_hidden(bmv, *, factor=0.999):
            nonlocal context
            point = self.matrix_world @ point_to_bvec4(bmv.co)
            hit = raycast_valid_sources(context, point)
            if not hit: return False
            ray_e = hit['ray_world'][0]
            return hit['distance'] < (ray_e.xyz - point.xyz).length * factor
        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        # collect data for smoothing
        radius = brush.get_scaled_radius()
        bvh = BVHTree.FromBMesh(self.bm)
        nearest_bmface_inds = { i for (v,n,i,d) in bvh.find_nearest_range(hit['co_local'], radius) }
        nearest_bmverts = { bmv for i in nearest_bmface_inds for bmv in self.bm.faces[i].verts }
        if False:
            # Debug: select all verts under brush
            bmops.deselect_all(self.bm)
            for bmelem in nearest_bmverts:
                bmops.select(self.bm, bmelem)
            bmops.flush_selection(self.bm, self.em)
        nearest = nearest_bmverts # self.rfcontext.nearest_verts_point(hit_pos, radius, bmverts=self._bmverts)
        verts,edges,faces,vert_strength = set(),set(),set(),dict()
        for bmv in nearest:
            if opt_mask_boundary == 'EXCLUDE' and bmv.is_boundary: continue
            if opt_mask_symmetry == 'EXCLUDE' and is_bmvert_on_symmetry_plane(bmv): continue
            if opt_mask_occluded == 'EXCLUDE' and is_bmvert_hidden(bmv): continue
            if opt_mask_selected == 'EXCLUDE' and bmv.select: continue
            if opt_mask_selected == 'ONLY' and not bmv.select: continue
            verts.add(bmv)
            edges.update(bmv.link_edges)
            faces.update(bmv.link_faces)
            vert_strength[bmv] = brush.get_strength_Point(self.matrix_world @ bmv.co)
        # self.rfcontext.select(verts)

        if not verts or not edges: return

        cur_time = time.time()
        time_delta = min(cur_time - self._time, 0.1)
        self._time = cur_time
        strength = (5.0 / opt_steps) * brush.strength * time_delta

        # capture all verts involved in relaxing
        chk_verts = set(verts)
        chk_verts.update({bmv for bme in edges for bmv in bme.verts})
        chk_verts.update({bmv for bmf in faces for bmv in bmf.verts})
        chk_edges = {bme for bmv in chk_verts for bme in bmv.link_edges}
        chk_faces = {bmf for bmv in chk_verts for bmf in bmv.link_faces}

        displace = {}
        def reset_forces():
            nonlocal displace
            displace.clear()
        def add_force(bmv, f):
            nonlocal displace, verts, vert_strength
            if bmv not in verts or bmv not in vert_strength: return
            displace[bmv] = displace.get(bmv, Vector((0,0,0))) + f

        def bme_length(bme):
            return bme_vector(bme).length
        def bme_vector(bme):
            # should take into account xform??
            v0, v1 = bme.verts
            return (v1.co - v0.co)
        def bme_center(bme):
            v0, v1 = bme.verts
            return Point.average([v0.co, v1.co])
        def bmf_compute_normal(bmf):
            ''' computes normal based on verts '''
            # TODO: should use loop rather than verts?
            an = Vector((0,0,0))
            vs = list(bmf.verts)
            bmv1,bmv2 = vs[-2],vs[-1]
            v1 = bmv2.co - bmv1.co
            for bmv in vs:
                bmv0,bmv1,bmv2 = bmv1,bmv2,bmv
                v0,v1 = -v1,bmv2.co-bmv1.co
                an = an + v0.cross(v1)
            return an.normalized()
        def bmf_is_flipped(bmf):
            fn = bmf_compute_normal(bmf)
            return any(v.normal.dot(fn) <= 0 for v in bmf.verts)
        def bmf_center(bmf):
            return Point.average(bmv.co for bmv in bmf.verts)

        def relax_3d():
            reset_forces()

            # compute average edge length
            avg_edge_len = sum(bme_length(bme) for bme in edges) / len(edges)

            # push edges closer to average edge length
            if opt_edge_length:
                for bme in chk_edges:
                    if bme not in edges: continue
                    bmv0,bmv1 = bme.verts
                    vec = bme_vector(bme)
                    edge_len = vec.length
                    f = vec * (0.1 * (avg_edge_len - edge_len) * strength) #/ edge_len
                    add_force(bmv0, -f)
                    add_force(bmv1, +f)

            # push verts if neighboring faces seem flipped (still WiP!)
            if opt_correct_flipped:
                bmf_flipped = { bmf for bmf in chk_faces if bmf_is_flipped(bmf) }
                for bmf in bmf_flipped:
                    # find a non-flipped neighboring face
                    for bme in bmf.edges:
                        bmfs = set(bme.link_faces)
                        bmfs.discard(bmf)
                        if len(bmfs) != 1: continue
                        bmf_other = next(iter(bmfs))
                        if bmf_other not in chk_faces: continue
                        if bmf_other in bmf_flipped: continue
                        # pull edge toward bmf_other center
                        bmf_c = bmf_center(bmf_other)
                        bme_c = bme_center(bme)
                        vec = bmf_c - bme_c
                        bmv0,bmv1 = bme.verts
                        add_force(bmv0, vec * strength * 5)
                        add_force(bmv1, vec * strength * 5)

            # push verts to straighten edges (still WiP!)
            if opt_straight_edges:
                for bmv in chk_verts:
                    if bmv.is_boundary: continue
                    bmes = bmv.link_edges
                    #if len(bmes) != 4: continue
                    center = Point.average(bme.other_vert(bmv).co for bme in bmes)
                    add_force(bmv, (center - bmv.co) * 0.1)

            # attempt to "square" up the faces
            for bmf in chk_faces:
                if bmf not in faces: continue
                bmvs = bmf.verts
                cnt = len(bmvs)
                ctr = Point.average(bmv.co for bmv in bmvs)
                rels = [bmv.co - ctr for bmv in bmvs]

                # push verts toward average dist from verts to face center
                if opt_face_radius:
                    avg_rel_len = sum(rel.length for rel in rels) / cnt
                    for rel, bmv in zip(rels, bmvs):
                        rel_len = rel.length
                        f = rel * ((avg_rel_len - rel_len) * strength * 2) #/ rel_len
                        add_force(bmv, f)

                # push verts toward equal edge lengths
                if opt_face_sides:
                    avg_face_edge_len = sum(bme_length(bme) for bme in bmf.edges) / cnt
                    for bme in bmf.edges:
                        bmv0, bmv1 = bme.verts
                        vec = bme_vector(bme)
                        edge_len = vec.length
                        f = vec * ((avg_face_edge_len - edge_len) * strength) / edge_len
                        add_force(bmv0, f * -0.5)
                        add_force(bmv1, f * 0.5)

                # push verts toward equal spread
                if opt_face_angles:
                    avg_angle = 2.0 * math.pi / cnt
                    for i0 in range(cnt):
                        i1 = (i0 + 1) % cnt
                        rel0,bmv0 = rels[i0],bmvs[i0]
                        rel1,bmv1 = rels[i1],bmvs[i1]
                        if rel0.length < 0.00001 or rel1.length < 0.00001: continue
                        vec = bmv1.co - bmv0.co
                        vec_len = vec.length
                        fvec0 = rel0.cross(vec).cross(rel0).normalized()
                        fvec1 = rel1.cross(rel1.cross(vec)).normalized()
                        angle = rel0.angle(rel1)
                        f_mag = (0.05 * (avg_angle - angle) * strength) / cnt #/ vec_len
                        add_force(bmv0, fvec0 * -f_mag)
                        add_force(bmv1, fvec1 * -f_mag)

        # perform smoothing
        for step in range(opt_steps):
            relax_3d()

            if len(displace) <= 1: continue

            # compute max displacement length
            displace_max = max(displace[bmv].length * (opt_mult * vert_strength[bmv]) for bmv in displace)
            if displace_max > radius * 0.125:
                # limit the displace_max
                mult = radius * 0.125 / displace_max
            else:
                mult = 1.0

            # update
            for bmv in displace:
                if bmv not in self.prev: self.prev[bmv] = Vector(bmv.co)
                co = bmv.co + displace[bmv] * (opt_mult * vert_strength[bmv]) * mult

                # TODO: IMPLEMENT!
                # if opt_mask_symmetry == 'maintain' and bmv.is_on_symmetry_plane():
                #     snap_to_symmetry = self.rfcontext.symmetry_planes_for_point(bmv.co)
                #     co = self.rfcontext.snap_to_symmetry(co, snap_to_symmetry)

                if opt_mask_boundary == 'SLIDE' and bmv.is_boundary:
                    p, d = None, None
                    for (v0, v1) in self._boundary:
                        p_ = closest_point_segment(co, v0, v1)
                        d_ = (p_ - co).length
                        if p is None or d_ < d: p, d = p_, d_
                    if p is not None:
                        co = p

                co_world = self.matrix_world @ Vector((*co, 1.0))
                co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True)
                bmv.co = self.matrix_world_inv @ co_world_snapped
                # self.rfcontext.snap_vert(bmv)
            # self.rfcontext.update_verts_faces(displace)
        # print(f'relaxed {len(verts)} ({len(chk_verts)}) in {time.time() - st} with {strength}')
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()


    def draw(self, context):
        if not self.mouse: return
        if not self.hit: return
        if not self.bm.is_valid: return

        pass