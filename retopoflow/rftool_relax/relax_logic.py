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
from math import isnan, inf
from typing import Tuple

from ..common.bmesh import get_bmesh_emesh, NearestBMVert, is_bmedge_boundary, is_bmvert_boundary, bme_midpoint, bmf_midpoint
from ..common.bmesh_maths import is_bmvert_hidden
from ..common.maths import point_to_bvec4, view_forward_direction, view_right_direction, view_up_direction, xform_direction
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, nearest_point_valid_sources, mouse_from_event
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

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import closest_point_segment, Point, sign, sign_threshold, clamp
from ...addon_common.common.colors import Color4, Color
from ..common.iter_utils import AttrIter, CastIter


class Accel:
    BINS_COUNT: int = 10

    def __init__(self, bmverts, matrix_world, bbox=None):
        self.bmverts = bmverts
        self.matrix_world = matrix_world
        self.min_x, self.min_y, self.min_z = 0, 0, 0
        self.max_x, self.max_y, self.max_z = 0, 0, 0
        self._bin_scale_x, self._bin_scale_y, self._bin_scale_z = 0, 0, 0
        self.time = time.time() - 1000
        self.rebuild(bbox=bbox)

    def rebuild(self, *, delta=1.0):
        if time.time() - self.time < delta: return
        M = self.matrix_world
    def rebuild(self, *, bbox=None, delta=1.0) -> None:
        if time.time() - self.time < delta:
            return
        if len(self.bmverts) == 0:
            return
        if bbox is not None:
            # Check if any corner has NaN values.
            for corner in bbox:
                if isnan(corner[0]) or isnan(corner[1]) or isnan(corner[2]):
                    print('RelaxLogic.Accel.rebuild: NaN values were found in bbox: ' + str(corner))
                    bbox = None  # fallback to using bmesh verts (slower but already filtered for NaN values)
                    break

        # Initilization.
        MW = self.matrix_world
        loc_points = AttrIter(self.bmverts, 'co') if bbox is None else CastIter(bbox, Vector)
        self.time = time.time()
        self.bins = [[[[] for _ in range(Accel.BINS_COUNT)] for _ in range(Accel.BINS_COUNT)] for _ in range(Accel.BINS_COUNT)]
        self.min_x, self.min_y, self.min_z = inf, inf, inf
        self.max_x, self.max_y, self.max_z = -inf, -inf, -inf
        bins = self.bins
        get_index = self.index

        # Calculate the min/max.
        for lpt in loc_points:
            wpt = MW @ lpt
            self.min_x = min(self.min_x, wpt.x)
            self.min_y = min(self.min_y, wpt.y)
            self.min_z = min(self.min_z, wpt.z)
            self.max_x = max(self.max_x, wpt.x)
            self.max_y = max(self.max_y, wpt.y)
            self.max_z = max(self.max_z, wpt.z)

        # Calculate the size.
        dx, dy, dz = self.max_x - self.min_x, self.max_y - self.min_y, self.max_z - self.min_z
        max_Dxyz = max(dx, dy, dz)
        if dx < 0.001: self.min_x, self.max_x = self.min_x - max_Dxyz * 0.001, self.max_x + max_Dxyz * 0.001
        if dy < 0.001: self.min_y, self.max_y = self.min_y - max_Dxyz * 0.001, self.max_y + max_Dxyz * 0.001
        if dz < 0.001: self.min_z, self.max_z = self.min_z - max_Dxyz * 0.001, self.max_z + max_Dxyz * 0.001

        # Precompute bin scales.
        denom_x = max(0.001, self.max_x - self.min_x)
        denom_y = max(0.001, self.max_y - self.min_y)
        denom_z = max(0.001, self.max_z - self.min_z)
        self._bin_scale_x = Accel.BINS_COUNT / denom_x
        self._bin_scale_y = Accel.BINS_COUNT / denom_y
        self._bin_scale_z = Accel.BINS_COUNT / denom_z

        # Populate the bins.
        for bmv in self.bmverts:
            ix, iy, iz = get_index(MW @ bmv.co)
            bins[ix][iy][iz].append(bmv)

    def index(self, co_world: Vector) -> Tuple[int, int, int]:
        max_bin_index = Accel.BINS_COUNT - 1
        ix = clamp(int((co_world.x - self.min_x) * self._bin_scale_x), 0, max_bin_index)
        iy = clamp(int((co_world.y - self.min_y) * self._bin_scale_y), 0, max_bin_index)
        iz = clamp(int((co_world.z - self.min_z) * self._bin_scale_z), 0, max_bin_index)
        return (ix, iy, iz)

    def get(self, co_world, radius_world):
        M = self.matrix_world
        r2 = radius_world * radius_world
        min_ix, min_iy, min_iz = self.index(co_world - Vector((radius_world, radius_world, radius_world)))
        max_ix, max_iy, max_iz = self.index(co_world + Vector((radius_world, radius_world, radius_world)))
        return {
            v
            for ix in range(min_ix, max_ix+1)
            for iy in range(min_iy, max_iy+1)
            for iz in range(min_iz, max_iz+1)
            for v in self.bins[ix][iy][iz]
            if (M @ v.co - co_world).length_squared <= r2
        }


class Relax_Logic:
    def __init__(self, context, event, brush, relax):
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.scale_avg = sum(context.edit_object.matrix_world.to_scale()) / 3
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
        self.prev_displace = {}
        self.bounce_mult = {}

        self._boundary = []
        if relax.mask_boundary == 'SLIDE':
            self._boundary = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in self.bm.edges
                if is_bmedge_boundary(bme, self.mirror, self.mirror_threshold, self.mirror_clip)
            ]

        self.bvh = BVHTree.FromBMesh(self.bm)

        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        def is_bmvert_on_ngon(bmv):
            for bmf in bmv.link_faces:
                if len(bmf.edges) > 4:
                    return True
            return False

        # gather options
        opt_mask_boundary    = relax.mask_boundary
        opt_mask_symmetry    = relax.mask_symmetry
        opt_include_corner   = relax.include_corners
        opt_include_occluded = relax.include_occluded
        opt_mask_selected    = relax.mask_selected
        opt_method           = relax.algorithm_method
        opt_steps            = relax.algorithm_iterations
        opt_prevent_bounce   = relax.algorithm_prevent_bounce
        opt_max_radius       = relax.algorithm_max_distance_radius
        opt_max_edges        = relax.algorithm_max_distance_edges
        opt_edge_length      = relax.algorithm_average_edge_lengths
        opt_straight_edges   = relax.algorithm_straighten_edges
        opt_face_radius      = relax.algorithm_average_face_radius
        opt_face_sides       = relax.algorithm_average_face_lengths
        opt_face_angles      = relax.algorithm_average_face_angles
        opt_correct_flipped  = relax.algorithm_correct_flipped_faces

        opt_mask_boundary_exclude = opt_mask_boundary == 'EXCLUDE'
        opt_mask_symmetry_exclude = opt_mask_symmetry == 'EXCLUDE'
        opt_mask_selected_exclude = opt_mask_selected == 'EXCLUDE'
        opt_mask_selected_only = opt_mask_selected == 'ONLY'

        self.verts_filtered = []
        for bmv in self.bm.verts:
            if bmv.hide: continue
            if len(bmv.link_faces) == 0: continue
            if isnan(bmv.co.x) or isnan(bmv.co.y) or isnan(bmv.co.z): continue
            if bmv.is_boundary and is_bmvert_on_ngon(bmv): continue
            if opt_mask_boundary_exclude and is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip): continue
            if opt_include_corner == False    and len(bmv.link_edges) == 2: continue
            if opt_include_corner == False    and len(bmv.link_edges) == 4 and len(bmv.link_faces) == 3: continue
            if opt_mask_symmetry_exclude and is_bmvert_on_symmetry_plane(bmv): continue
            if opt_include_occluded == False  and is_bmvert_hidden(context, bmv): continue
            if opt_mask_selected_exclude and bmv.select: continue
            if opt_mask_selected_only and not bmv.select: continue
            self.verts_filtered.append(bmv)

        depsgraph = context.evaluated_depsgraph_get()
        object_evaluated = context.edit_object.evaluated_get(depsgraph)
        bbox = object_evaluated.bound_box
        self.verts_accel = Accel(self.verts_filtered, self.matrix_world, bbox=bbox)
        self.verts_accel_time = time.time()

        self.draw_vectors = [[],[],[]]

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
        opt_method           = relax.algorithm_method
        opt_steps            = relax.algorithm_iterations
        opt_prevent_bounce   = relax.algorithm_prevent_bounce
        opt_max_radius       = relax.algorithm_max_distance_radius
        opt_max_edges        = relax.algorithm_max_distance_edges
        opt_edge_length      = relax.algorithm_average_edge_lengths
        opt_straight_edges   = relax.algorithm_straighten_edges
        opt_face_radius      = relax.algorithm_average_face_radius
        opt_face_sides       = relax.algorithm_average_face_lengths
        opt_face_angles      = relax.algorithm_average_face_angles
        opt_correct_flipped  = relax.algorithm_correct_flipped_faces

        opt_draw_all         = False
        opt_draw_net         = False

        M = self.matrix_world
        Mi = self.matrix_world_inv

        # collect data for smoothing
        radius2D, radius3D = self.brush.radius, self.brush.get_scaled_radius()

        if False:
            # Debug: select all verts under brush
            bmops.deselect_all(self.bm)
            for bmelem in nearest_bmverts:
                bmops.select(self.bm, bmelem)
            bmops.flush_selection(self.bm, self.em)

        depsgraph = context.evaluated_depsgraph_get()
        object_evaluated = context.edit_object.evaluated_get(depsgraph)
        bbox = object_evaluated.bound_box
        self.verts_accel.rebuild(bbox=bbox)
        verts = self.verts_accel.get(hit['co_world'], radius3D)
        edges = { bme for bmv in verts for bme in bmv.link_edges }
        faces = { bmf for bmv in verts for bmf in bmv.link_faces }
        vert_strength = { bmv:brush.get_strength_Point(M @ bmv.co) for bmv in verts }

        if not verts or not edges: return

        cur_time = time.time()
        time_delta = min(cur_time - self._time, 0.1)
        self._time = cur_time
        strength = 1.0

        # capture all verts involved in relaxing
        chk_verts = set(verts)
        chk_verts.update({ bmv for bme in edges for bmv in bme.verts })
        chk_verts.update({ bmv for bmf in faces for bmv in bmf.verts })
        chk_edges = { bme for bmv in chk_verts for bme in bmv.link_edges }
        chk_faces = { bmf for bmv in chk_verts for bmf in bmv.link_faces }

        self.draw_vectors = [[],[], []]

        displace = {}
        def reset_forces():
            nonlocal displace
            displace.clear()
        def add_force(bmv, f, wrt=None, sign=0, mult=0):
            nonlocal displace, verts, vert_strength
            if bmv not in verts or bmv not in vert_strength: return
            if bmv not in displace: displace[bmv] = Vector((0,0,0))
            displace[bmv] += f.xyz * vert_strength[bmv]
            if opt_draw_all and wrt:
                if sign > 0:
                    self.draw_vectors[0].append((wrt, f.xyz * mult * vert_strength[bmv]))
                elif sign < 0:
                    self.draw_vectors[1].append((wrt, f.xyz * mult * vert_strength[bmv]))

        def bme_length(bme):
            return bme_vector(bme).length
        def bme_vector(bme):
            # should take into account xform??
            v0, v1 = bme.verts
            return (v1.co - v0.co)
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

        def relax_3d():
            reset_forces()

            # push edges closer to average edge length
            if opt_edge_length:
                # compute average edge length
                avg_edge_len = sum(bme_length(bme) for bme in edges) / len(edges)
                for bme in chk_edges:
                    if bme not in edges: continue
                    bmv0, bmv1 = bme.verts
                    vec = bme_vector(bme)
                    edge_len = vec.length
                    f = vec * (2.0 * (avg_edge_len - edge_len) * strength)
                    add_force(bmv0, -f, bme_midpoint(bme), (avg_edge_len-edge_len), 40)
                    add_force(bmv1, +f, bme_midpoint(bme), (avg_edge_len-edge_len), 40)

            # push verts if neighboring faces seem flipped (still WiP!)
            if opt_correct_flipped:
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
                        add_force(bmv0, vec * strength * 5, bmf_midpoint(bmf), 1, 40)
                        add_force(bmv1, vec * strength * 5, bmf_midpoint(bmf), 1, 40)

            # push verts to straighten edges (still WiP!)
            if opt_straight_edges:
                for bmv in chk_verts:
                    if is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip):
                        # improve handling of boundary edges and verts when straightening edges
                        # see issue #1504
                        if opt_mask_boundary == 'EXCLUDE': continue
                        if len(bmv.link_edges) == 2: continue  # ignore corners
                        center = Point.average([
                            bme.other_vert(bmv).co for bme in bmv.link_edges if is_bmedge_boundary(
                                bme, self.mirror, self.mirror_threshold, self.mirror_clip
                        )])
                    else:
                        center = Point.average(bme.other_vert(bmv).co for bme in bmv.link_edges)
                    vec = center - bmv.co
                    add_force(bmv, vec * (vec.length * strength * 5), bmv.co, 1, 40)

            # attempt to "square" up the faces
            for bmf in chk_faces:
                if bmf not in faces: continue
                bmvs = bmf.verts
                cnt = len(bmvs)
                ctr = bmf_midpoint(bmf)
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
                        f = rel * ((avg_rel_len - rel_len) * strength * 5.0)
                        add_force(bmv, f, bmf_midpoint(bmf), (avg_rel_len - rel_len), 40)

                # push verts toward equal edge lengths
                if opt_face_sides:
                    avg_face_edge_len = sum(bme_length(bme) for bme in bmf.edges) / cnt
                    for bme in bmf.edges:
                        bmv0, bmv1 = bme.verts
                        vec = bme_vector(bme)
                        edge_len = vec.length
                        f = vec * ((avg_face_edge_len - edge_len) * strength * 5.0)
                        add_force(bmv0, f * -0.5, bme_midpoint(bme), (avg_face_edge_len - edge_len), 40)
                        add_force(bmv1, f * 0.5, bme_midpoint(bme), (avg_face_edge_len - edge_len), 40)

                # push verts toward equal spread
                if opt_face_angles:
                    sum_of_interior_angles = math.pi * (cnt - 2)
                    angle_target = sum_of_interior_angles / cnt
                    for i1 in range(cnt):
                        i0 = (i1 + cnt - 1) % cnt
                        i2 = (i1 + 1) % cnt
                        bmv0, bmv1, bmv2 = bmvs[i0], bmvs[i1], bmvs[i2]
                        v10, v12 = bmv0.co - bmv1.co, bmv2.co - bmv1.co
                        d10, d12 = v10.normalized(), v12.normalized()
                        d10_2 = Vector((bmf_x.dot(d10), bmf_y.dot(d10))).normalized()
                        d12_2 = Vector((bmf_x.dot(d12), bmf_y.dot(d12))).normalized()
                        try:
                            angle = d10_2.angle_signed(d12_2)
                            angle_diff = angle_target - angle
                            mag = angle_diff * 0.2 * strength * (v10.length + v12.length) ** 2
                            add_force(bmv0, d10.cross(bmf_z).normalized() * -mag, bmv0.co, angle_diff, 40)
                            add_force(bmv2, d12.cross(bmf_z).normalized() * mag, bmv1.co, angle_diff, 40)
                        except Exception:
                            # Exception is thrown if d10_2 or d12_2 are 0-length
                            pass

        # perform smoothing
        for step in range(1 if opt_method == 'RK4' else opt_steps):
            if opt_method == 'RK4':
                original = { bmv: Vector(bmv.co) for bmv in verts }

                strength = 10.0 * self.scale_avg * brush.strength / radius3D * time_delta * self.pressure
                relax_3d()
                k1 = displace.copy()

                for bmv in original:
                    f1 = k1[bmv] if bmv in k1 else Vector((0,0,0))
                    bmv.co = original[bmv] + f1 / 2
                strength = 10.0 * self.scale_avg * brush.strength / radius3D * time_delta * self.pressure / 2
                relax_3d()
                k2 = displace.copy()

                for bmv in original:
                    f2 = k2[bmv] if bmv in k2 else Vector((0,0,0))
                    bmv.co = original[bmv] + f2 / 2
                strength = 10.0 * self.scale_avg * brush.strength / radius3D * time_delta * self.pressure / 2
                relax_3d()
                k3 = displace.copy()

                for bmv in original:
                    f3 = k3[bmv] if bmv in k3 else Vector((0,0,0))
                    bmv.co = original[bmv] + f3
                strength = 10.0 * self.scale_avg * brush.strength / radius3D * time_delta * self.pressure
                relax_3d()
                k4 = displace.copy()

                strength = 10.0 * self.scale_avg * brush.strength / radius3D * time_delta * self.pressure / 6
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
                strength = 10.0 * self.scale_avg * brush.strength / radius3D * time_delta * self.pressure / opt_steps
                relax_3d()

            if opt_prevent_bounce:
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
                mult *= min(1.0, radius3D * opt_max_radius / displace_max)
            # print(time_delta, radius3D, opt_max_radius, displace_max, mult)
            if displace_max > radius3D:
                print('Relax: Limiting distance')
                break

            # update
            update_to = {}
            for bmv in displace:
                if bmv not in self.prev: self.prev[bmv] = Vector(bmv.co)

                displace_dist = displace[bmv].length * mult
                if bmv.link_edges and displace_dist > 1e-8:
                    avg_edge_len = sum(bme_length(bme) for bme in bmv.link_edges) / len(bmv.link_edges)
                    displace_dist *= min(1.0, avg_edge_len * opt_max_edges / displace_dist)
                # displace_dist *= vert_strength[bmv]
                if opt_prevent_bounce:
                    displace_dist *= self.bounce_mult.get(bmv, 1.0)
                displace_vec = displace[bmv].normalized() * displace_dist
                co = bmv.co + displace_vec

                if opt_draw_net:
                    self.draw_vectors[2].append((bmv.co, displace_vec * 100))

                if opt_mask_boundary == 'SLIDE' and is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip):
                    p, d = None, None
                    for (v0, v1) in self._boundary:
                        p_ = closest_point_segment(co, v0, v1)
                        d_ = (p_ - co).length
                        if p is None or d_ < d: p, d = p_, d_
                    if p is not None:
                        co = p

                co_world = M @ Vector((*co.xyz, 1.0))
                co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True)
                co_local_snapped = Mi @ co_world_snapped if co_world_snapped else co

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
                        co_world = M @ Vector((*co, 1.0))
                        co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True)
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
        # print(f'relaxed {len(verts)} ({len(chk_verts)}) in {time.time() - st} with {strength}')
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()


    def draw(self, context):
        M = context.edit_object.matrix_world
        rgn, r3d = context.region, context.region_data

        with Drawing.draw(context, CC_2D_LINES) as draw:
            #draw.point_size(vertex_size + 4)
            #draw.border(width=2, color=(1,1,0))
            draw.color(Color4((0, 1, 0, 0.5)))
            for (co,v) in self.draw_vectors[0]:
                co0, co1 = co, co + v
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ co0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ co1)
                if pt0 and pt1:
                    draw.vertex(pt0)
                    draw.vertex(pt1)
            draw.color(Color4((1, 0, 0, 0.5)))
            for (co,v) in self.draw_vectors[1]:
                co0, co1 = co, co + v
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ co0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ co1)
                if pt0 and pt1:
                    draw.vertex(pt0)
                    draw.vertex(pt1)
            draw.color(Color4((1, 1, 0, 0.5)))
            for (co,v) in self.draw_vectors[2]:
                co0, co1 = co, co + v
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ co0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ co1)
                if pt0 and pt1:
                    draw.vertex(pt0)
                    draw.vertex(pt1)
