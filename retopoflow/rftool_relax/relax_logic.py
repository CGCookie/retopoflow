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

from ..common.bmesh import get_bmesh_emesh, NearestBMVert, is_bmedge_boundary, is_bmvert_boundary
from ..common.bmesh_maths import is_bmvert_hidden
from ..common.maths import point_to_bvec4, view_forward_direction, view_right_direction, view_up_direction, xform_direction
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, nearest_point_valid_sources, mouse_from_event

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import closest_point_segment, Point, sign, sign_threshold


class Relax_Logic:
    def __init__(self, context, event, brush, relax):
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.mouse = None
        self.forward = xform_direction(self.matrix_world_inv, view_forward_direction(context))
        self.right = xform_direction(self.matrix_world_inv, view_right_direction(context))
        self.up = xform_direction(self.matrix_world_inv, view_up_direction(context))

        self.brush = brush
        self.relax = relax

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

        self.bm, self.em = get_bmesh_emesh(context)
        self.bm.faces.ensure_lookup_table()
        self._time = time.time()
        self.pressure = 1.0

        self.prev = {}

        self._boundary = []
        if relax.mask_boundary == 'SLIDE':
            self._boundary = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in self.bm.edges
                if is_bmedge_boundary(bme, self.mirror, self.mirror_threshold, self.mirror_clip)
            ]

        self.bvh = BVHTree.FromBMesh(self.bm)

    def cancel(self, context):
        for (bmv, co) in self.prev.items():
            bmv.co = co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()


    def update(self, context, event):
        if event.type == 'PEN': self.pressure = event.pressure

        if event.type != 'TIMER': return

        hit = raycast_valid_sources(context, mouse_from_event(event))
        if not hit: return

        brush = self.brush
        relax = self.relax

        # gather options
        opt_mask_boundary    = relax.mask_boundary
        opt_mask_symmetry    = relax.mask_symmetry
        opt_include_corner   = relax.include_corners
        opt_include_occluded = relax.include_occluded
        opt_mask_selected    = relax.mask_selected
        opt_steps            = relax.algorithm_iterations
        opt_mult             = relax.algorithm_strength
        opt_edge_length      = relax.algorithm_average_edge_lengths
        opt_straight_edges   = relax.algorithm_straighten_edges
        opt_face_radius      = relax.algorithm_average_face_radius
        opt_face_sides       = relax.algorithm_average_face_lengths
        opt_face_angles      = relax.algorithm_average_face_angles
        opt_correct_flipped  = relax.algorithm_correct_flipped_faces

        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False
        
        def is_bmvert_on_ngon(bmv):
            for bmf in bmv.link_faces:
                if len(bmf.edges) > 4:
                    return True
            return False

        # collect data for smoothing
        radius2D, radius3D = self.brush.radius, self.brush.get_scaled_radius()

        if False:
            # Debug: select all verts under brush
            bmops.deselect_all(self.bm)
            for bmelem in nearest_bmverts:
                bmops.select(self.bm, bmelem)
            bmops.flush_selection(self.bm, self.em)

        verts,edges,faces,vert_strength = set(),set(),set(),dict()
        for bmv in self.bm.verts:
            if bmv.hide: continue
            if len(bmv.link_faces) == 0: continue
            if bmv.is_boundary and is_bmvert_on_ngon(bmv): continue
            if (bmv.co - hit['co_local']).length > radius3D: continue
            if opt_mask_boundary == 'EXCLUDE' and bmv.is_boundary: continue
            if opt_include_corner == False    and len(bmv.link_edges) == 2: continue
            if opt_include_corner == False    and len(bmv.link_edges) == 4 and len(bmv.link_faces) == 3: continue
            if opt_mask_symmetry == 'EXCLUDE' and is_bmvert_on_symmetry_plane(bmv): continue
            if opt_include_occluded == False  and is_bmvert_hidden(context, bmv): continue
            if opt_mask_selected == 'EXCLUDE' and bmv.select: continue
            if opt_mask_selected == 'ONLY'    and not bmv.select: continue
            verts.add(bmv)
            edges.update(bmv.link_edges)
            faces.update(bmv.link_faces)
            vert_strength[bmv] = brush.get_strength_Point(self.matrix_world @ bmv.co)
        # self.rfcontext.select(verts)

        if not verts or not edges: return

        cur_time = time.time()
        time_delta = min(cur_time - self._time, 0.1)
        self._time = cur_time
        strength = (5.0 / opt_steps) * brush.strength * time_delta * self.pressure

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
            if bmv not in displace: displace[bmv] = Vector((0,0,0))
            displace[bmv] += f

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
            bmv1, bmv2 = vs[-2], vs[-1]
            v1 = bmv2.co - bmv1.co
            for bmv in vs:
                bmv0, bmv1, bmv2 = bmv1, bmv2, bmv
                v0, v1 = -v1, bmv2.co - bmv1.co
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
                    bmv0, bmv1 = bme.verts
                    vec = bme_vector(bme)
                    edge_len = vec.length
                    f = vec * (10.0 * (avg_edge_len - edge_len) * strength) #/ edge_len
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
                    if bmv.is_boundary:
                        # improve handling of boundary edges and verts when straightening edges
                        # see issue #1504
                        if opt_mask_boundary == 'EXCLUDE': continue
                        if len(bmv.link_edges) == 2: continue  # ignore corners
                        center = Point.average(bme.other_vert(bmv).co for bme in bmv.link_edges if bme.is_boundary)
                    else:
                        center = Point.average(bme.other_vert(bmv).co for bme in bmv.link_edges)
                    add_force(bmv, (center - bmv.co) * 0.1)

            # attempt to "square" up the faces
            for bmf in chk_faces:
                if bmf not in faces: continue
                bmvs = bmf.verts
                cnt = len(bmvs)
                ctr = Point.average(bmv.co for bmv in bmvs)
                rels = [bmv.co - ctr for bmv in bmvs]
                bmf_z = bmf.normal.normalized()
                if abs(bmf_z.dot(self.forward)) < 0.95:
                    bmf_y = bmf_z.cross(self.forward).normalized()
                    bmf_x = bmf_y.cross(bmf_z).normalized()
                else:
                    bmf_x = self.up.cross(bmf_z).normalized()
                    bmf_y = bmf_z.cross(bmf_x).normalized()

                # push verts toward average dist from verts to face center
                if opt_face_radius:
                    avg_rel_len = sum(rel.length for rel in rels) / cnt
                    for rel, bmv in zip(rels, bmvs):
                        rel_len = rel.length
                        f = rel * ((avg_rel_len - rel_len) * strength * 5.0) / rel_len
                        add_force(bmv, f)

                # push verts toward equal edge lengths
                if opt_face_sides:
                    avg_face_edge_len = sum(bme_length(bme) for bme in bmf.edges) / cnt
                    for bme in bmf.edges:
                        bmv0, bmv1 = bme.verts
                        vec = bme_vector(bme)
                        edge_len = vec.length
                        f = vec * ((avg_face_edge_len - edge_len) * strength * 5.0) / edge_len
                        add_force(bmv0, f * -0.5)
                        add_force(bmv1, f * 0.5)

                # push verts toward equal spread
                if opt_face_angles:
                    angle_target = (cnt - 2) * math.pi / cnt
                    for i1 in range(cnt):
                        i0 = (i1 + cnt - 1) % cnt
                        i2 = (i1 + 1) % cnt
                        bmv0, bmv1, bmv2 = bmvs[i0], bmvs[i1], bmvs[i2]
                        v10, v12 = bmv0.co - bmv1.co, bmv2.co - bmv1.co
                        d10, d12 = v10.normalized(), v12.normalized()
                        d10_2 = Vector((bmf_x.dot(d10), bmf_y.dot(d10))).normalized()
                        d12_2 = Vector((bmf_x.dot(d12), bmf_y.dot(d12))).normalized()
                        angle = d10_2.angle_signed(d12_2)
                        angle_diff = angle_target - angle
                        mag = angle_diff * 0.05 * strength
                        add_force(bmv0, d10.cross(bmf_z).normalized() * -mag)
                        add_force(bmv2, d12.cross(bmf_z).normalized() * mag)

        # perform smoothing
        for step in range(opt_steps):
            relax_3d()

            if len(displace) <= 1: continue

            # compute max displacement length
            displace_max = max(displace[bmv].length * (opt_mult * vert_strength[bmv]) for bmv in displace)
            if displace_max > radius3D * 0.125:
                # limit the displace_max
                mult = radius3D * 0.125 / displace_max
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

                if opt_mask_boundary == 'SLIDE' and is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip):
                    p, d = None, None
                    for (v0, v1) in self._boundary:
                        p_ = closest_point_segment(co, v0, v1)
                        d_ = (p_ - co).length
                        if p is None or d_ < d: p, d = p_, d_
                    if p is not None:
                        co = p

                co_world = self.matrix_world @ Vector((*co, 1.0))
                co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True)
                co_local_snapped = self.matrix_world_inv @ co_world_snapped

                if self.mirror:
                    co_orig = self.prev[bmv]
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
                        co_world = self.matrix_world @ Vector((*co, 1.0))
                        co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True)
                        co = self.matrix_world_inv @ co_world_snapped
                        if d < 0.001: break  # break out if change was below threshold
                    if zero['x']: co.x = 0
                    if zero['y']: co.y = 0
                    if zero['z']: co.z = 0
                    co_local_snapped = co

                bmv.co = co_local_snapped
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