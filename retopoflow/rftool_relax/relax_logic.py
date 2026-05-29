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
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector
from mathutils.bvhtree import BVHTree

import math
import time
from math import isnan, inf
from typing import Tuple

from ..common.bmesh import get_bmesh_emesh, is_bmedge_boundary, is_bmvert_boundary, is_bmvert_corner, is_bmvert_on_ngon, bme_midpoint, bmf_midpoint, EdgeAccel
from ..common.bmesh_maths import is_bmvert_hidden, is_bmvert_on_edgemark, is_bmedge_edgemark, get_bmvert_attribute
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
from ...addon_common.common.maths import Point, sign, sign_threshold, clamp
from ...addon_common.common.colors import Color4
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
        ix = int(clamp(int((co_world.x - self.min_x) * self._bin_scale_x), 0, max_bin_index))
        iy = int(clamp(int((co_world.y - self.min_y) * self._bin_scale_y), 0, max_bin_index))
        iz = int(clamp(int((co_world.z - self.min_z) * self._bin_scale_z), 0, max_bin_index))
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


class EdgeAccelBuilder:
    @staticmethod
    def build(bm, verts, mirror, mirror_threshold, mirror_clip, mask_boundary, mask_creases, mask_sharps, mask_seams):
        local_edges = {bme for bmv in verts for bme in bmv.link_edges}

        boundary = []
        boundary_verts = set()
        boundary_accel = None
        if mask_boundary == 'SLIDE':
            boundary_edges = [
                bme for bme in local_edges
                if is_bmedge_boundary(bme, mirror, mirror_threshold, mirror_clip)
            ]
            boundary = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in boundary_edges
            ]
            boundary_verts = {
                bmv for bme in boundary_edges for bmv in bme.verts
            }
            boundary_accel = EdgeAccel(boundary)

        crease = []
        crease_verts = set()
        crease_accel = None
        if mask_creases == 'SLIDE':
            crease_edges = [
                bme for bme in local_edges
                if is_bmedge_edgemark(bm, bme, 'crease', ensure_lookup=False)
            ]
            crease = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in crease_edges
            ]
            crease_verts = {
                bmv for bme in crease_edges for bmv in bme.verts
            }
            crease_accel = EdgeAccel(crease)

        sharp = []
        sharp_verts = set()
        sharp_accel = None
        if mask_sharps == 'SLIDE':
            sharp_edges = [
                bme for bme in local_edges
                if is_bmedge_edgemark(bm, bme, 'sharp')
            ]
            sharp = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in sharp_edges
            ]
            sharp_verts = {
                bmv for bme in sharp_edges for bmv in bme.verts
            }
            sharp_accel = EdgeAccel(sharp)

        seam = []
        seam_verts = set()
        seam_accel = None
        if mask_seams == 'SLIDE':
            seam_edges = [
                bme for bme in local_edges
                if is_bmedge_edgemark(bm, bme, 'seam')
            ]
            seam = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in seam_edges
            ]
            seam_verts = {
                bmv for bme in seam_edges for bmv in bme.verts
            }
            seam_accel = EdgeAccel(seam)

        edge_data = {
            'boundary': boundary,
            'boundary_verts': boundary_verts,
            'boundary_accel': boundary_accel,
            'crease': crease,
            'crease_verts': crease_verts,
            'crease_accel': crease_accel,
            'sharp': sharp,
            'sharp_verts': sharp_verts,
            'sharp_accel': sharp_accel,
            'seam': seam,
            'seam_verts': seam_verts,
            'seam_accel': seam_accel,
        }
        return edge_data


class RelaxStrokeCache:
    def __init__(self, cache, *, context, bm, matrix_world):
        self.cache = cache if isinstance(cache, dict) else None
        self.context = context
        self.bm = bm
        self.matrix_world = matrix_world

        self.accel_key = (
            context.edit_object.as_pointer(),
            id(bm),
            len(bm.verts),
            len(bm.edges),
            len(bm.faces),
        )

    def get_verts_accel(self):
        if not self.cache:
            return None
        cached_accel = self.cache.get('verts_accel')
        if not isinstance(cached_accel, dict):
            return None
        if cached_accel.get('key') != self.accel_key:
            return None
        if cached_accel.get('bm') is not self.bm:
            return None
        return cached_accel

    def set_verts_accel(self, *, verts_filtered, verts_accel):
        if self.cache is None:
            return
        self.cache['verts_accel'] = {
            'key': self.accel_key,
            'bm': self.bm,
            'verts_filtered': verts_filtered,
            'verts_accel': verts_accel,
        }

    def get_or_build_verts_accel(self):
        cached_accel = self.get_verts_accel()
        if cached_accel is not None:
            return cached_accel['verts_filtered'], cached_accel['verts_accel']

        context = self.context
        bm = self.bm
        verts_filtered = list(bm.verts)

        depsgraph = context.evaluated_depsgraph_get()
        object_evaluated = context.edit_object.evaluated_get(depsgraph)
        bbox = object_evaluated.bound_box
        verts_accel = Accel(verts_filtered, self.matrix_world, bbox=bbox)
        self.set_verts_accel(verts_filtered=verts_filtered, verts_accel=verts_accel)
        return verts_filtered, verts_accel


class Relax_Logic:
    def __init__(self, context, event, brush, relax, cache=None):
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe()
        self.scale_avg = sum(context.edit_object.matrix_world.to_scale()) / 3
        self.mouse = mouse_from_event(event)
        self.forward = xform_direction(self.matrix_world_inv, view_forward_direction(context))
        self.right = xform_direction(self.matrix_world_inv, view_right_direction(context))
        self.up = xform_direction(self.matrix_world_inv, view_up_direction(context))

        self.brush = brush
        self.relax = relax

        # gather options
        opt_mask_boundary    = context.scene.retopoflow.mask_boundary
        opt_mask_selected    = context.scene.retopoflow.mask_selected
        opt_mask_symmetry    = context.scene.retopoflow.mask_symmetry
        opt_mask_sharps      = context.scene.retopoflow.mask_sharps
        opt_mask_creases     = context.scene.retopoflow.mask_creases
        opt_mask_seams       = context.scene.retopoflow.mask_seams
        opt_include_corner   = context.scene.retopoflow.include_corners
        opt_include_pinned   = context.scene.retopoflow.include_pinned
        opt_include_occluded = context.scene.retopoflow.include_occluded
        opt_use_cache        = relax.algorithm_use_cache

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
        self.bm.edges.ensure_lookup_table()
        self._time = time.time()
        self.pressure = 1.0

        self.prev = {}
        self.prev_displace = {}
        self.bounce_mult = {}

        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        def is_vert_included(bmv):
            if bmv.hide: return False
            if len(bmv.link_faces) == 0: return False
            if isnan(bmv.co.x) or isnan(bmv.co.y) or isnan(bmv.co.z): return False
            if opt_mask_selected == 'EXCLUDE' and bmv.select: return False
            if opt_mask_selected == 'ONLY' and not bmv.select: return False
            if bmv.is_boundary and is_bmvert_on_ngon(bmv): return False
            if opt_include_corner == False and is_bmvert_corner(bmv): return False
            if opt_include_pinned == False and get_bmvert_attribute(self.bm, bmv, 'retopoflow_pins', 'float'):
                return False
            if opt_mask_symmetry == 'EXCLUDE' and is_bmvert_on_symmetry_plane(bmv):
                return False
            if opt_mask_creases == 'EXCLUDE' and (
                    get_bmvert_attribute(self.bm, bmv, 'crease_vert', 'float') and
                    not get_bmvert_attribute(self.bm, bmv, 'retopoflow_pins', 'float')
            ):
                return False
            if opt_mask_creases == 'EXCLUDE' and is_bmvert_on_edgemark(self.bm, bmv, 'crease', ensure_lookup=False):
                return False
            if opt_mask_seams == 'EXCLUDE' and is_bmvert_on_edgemark(self.bm, bmv, 'seam'):
                return False
            if opt_mask_sharps == 'EXCLUDE' and is_bmvert_on_edgemark(self.bm, bmv, 'sharp'):
                return False
            if opt_mask_boundary == 'EXCLUDE' and is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip):
                return False
            if opt_mask_boundary == 'SLIDE' and is_bmvert_corner(bmv):
                return False
            if opt_mask_seams == 'SLIDE' and sum(1 for bme in bmv.link_edges if is_bmedge_edgemark(self.bm, bme, 'seam')) > 2:
                return False
            if opt_mask_sharps == 'SLIDE' and sum(1 for bme in bmv.link_edges if is_bmedge_edgemark(self.bm, bme, 'sharp')) > 2:
                return False
            if opt_mask_creases == 'SLIDE' and sum(1 for bme in bmv.link_edges if is_bmedge_edgemark(self.bm, bme, 'crease', ensure_lookup=False)) > 2:
                return False
            return True

        # Cache verts and edges between strokes
        stroke_cache = RelaxStrokeCache(
            cache if opt_use_cache else None,
            context=context,
            bm=self.bm,
            matrix_world=self.matrix_world
        )
        verts, self.verts_accel = stroke_cache.get_or_build_verts_accel()
        self.verts_filtered = set([bmv for bmv in verts if is_vert_included(bmv)])
        edge_data = EdgeAccelBuilder.build(
            self.bm,
            self.verts_filtered,
            self.mirror,
            self.mirror_threshold,
            self.mirror_clip,
            opt_mask_boundary,
            opt_mask_creases,
            opt_mask_sharps,
            opt_mask_seams,
        )
        self.boundary = edge_data['boundary']
        self.boundary_verts = edge_data['boundary_verts']
        self.boundary_accel = edge_data['boundary_accel']
        self.crease = edge_data['crease']
        self.crease_verts = edge_data['crease_verts']
        self.crease_accel = edge_data['crease_accel']
        self.sharp = edge_data['sharp']
        self.sharp_verts = edge_data['sharp_verts']
        self.sharp_accel = edge_data['sharp_accel']
        self.seam = edge_data['seam']
        self.seam_verts = edge_data['seam_verts']
        self.seam_accel = edge_data['seam_accel']
        self.verts_accel_time = time.time()

        self.draw_vectors = [[],[],[]]

    def cancel(self, context):
        for (bmv, co) in self.prev.items():
            bmv.co = co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()


    def update(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            self.pressure = getattr(event, 'pressure', 1.0)
            self.mouse = mouse_from_event(event)
        elif event.type == 'TIMER':
            mouse = mouse_from_event(event)
            if mouse: self.mouse = mouse
        else:
            return

        # Limit updates so moving the mouse doesn't update faster than timer
        if time.time() - self._time < 1.0 / 120: return

        if not self.mouse: return

        hit = raycast_valid_sources(context, self.mouse)
        if not hit: return

        brush = self.brush
        relax = self.relax

        # gather options
        opt_mask_boundary    = context.scene.retopoflow.mask_boundary
        opt_mask_selected    = context.scene.retopoflow.mask_selected
        opt_mask_creases     = context.scene.retopoflow.mask_creases
        opt_mask_seams       = context.scene.retopoflow.mask_seams
        opt_mask_sharps      = context.scene.retopoflow.mask_sharps
        opt_include_occluded = context.scene.retopoflow.include_occluded
        opt_method           = relax.algorithm_method
        opt_steps            = relax.algorithm_iterations
        opt_prevent_bounce   = relax.algorithm_prevent_bounce
        opt_max_radius       = relax.algorithm_max_distance_radius
        opt_max_edges        = relax.algorithm_max_distance_edges
        opt_edge_length      = relax.algorithm_average_edge_lengths
        opt_straight_edges   = relax.algorithm_straighten_edges
        opt_equalize_faces   = relax.algorithm_equalize_faces
        opt_laplacian        = relax.algorithm_laplacian
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
        if not self.verts_filtered: return
        verts = self.verts_accel.get(hit['co_world'], radius3D)
        if not opt_include_occluded:
            # Occlusion testing is expensive, so doing it here
            # to not test the whole mesh or invalidate the cache on view change
            verts = {
                bmv
                for bmv in verts
                if not is_bmvert_hidden(context, bmv)
            }
        verts = {bmv for bmv in verts if bmv in self.verts_filtered}
        if not verts: return
        edges = { bme for bmv in verts for bme in bmv.link_edges }
        if not edges: return
        faces = { bmf for bmv in verts for bmf in bmv.link_faces }
        vert_strength = { bmv:brush.get_strength_Point(M @ bmv.co) for bmv in verts }

        cur_time = time.time()
        time_delta = min(cur_time - self._time, 0.1)
        self._time = cur_time

        strength = self.pressure

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
            options = [
                opt_laplacian,
                opt_edge_length,
                opt_straight_edges,
                opt_equalize_faces, opt_equalize_faces, opt_equalize_faces, opt_equalize_faces,
            ]
            weight_mult = 1 / len([x for x in options if x == True])
            displace[bmv] += f.xyz * vert_strength[bmv] * weight_mult
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

        def laplacian_smooth(bmv, shape_preservation=0):
            ''' Push verts towards the average of their neighbors '''
            # Skip corners
            edge_count = len(bmv.link_edges)
            if edge_count == 2: return
            if edge_count == 4 and len(bmv.link_faces) == 3: return
            if bmv.is_boundary:
                if edge_count > 4: return
                neighbors = [x.other_vert(bmv) for x in bmv.link_edges if x.is_boundary]
            else:
                neighbors = [x.other_vert(bmv) for x in bmv.link_edges]
            average_co = Vector([
                sum([x.co[0] for x in neighbors]),
                sum([x.co[1] for x in neighbors]),
                sum([x.co[2] for x in neighbors])]
            ) / len(neighbors)
            if shape_preservation:
                # Shape Preservation doesn't seem to work well with how the brush iterates
                if bmv not in self.prev: self.prev[bmv] = Vector(bmv.co)
                weighted_o = self.prev[bmv] * shape_preservation
                weighted_q = bmv.co * (1 - shape_preservation)
                displacement = average_co - (weighted_o + weighted_q)
            else:
                displacement = average_co - bmv.co
            if bmv.is_boundary: displacement /= 2
            add_force(bmv, displacement / 10, mult=40)

        def straighten_edges(bmv):
            ''' push verts to straighten edges (still WiP!) '''
            is_boundary = is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip)
            if is_boundary and opt_mask_boundary == 'EXCLUDE': return
            edge_count = len(bmv.link_edges)
            if edge_count == 2: return  # skip corners
            if edge_count == 4 and len(bmv.link_faces) == 3: return
            if is_boundary:
                if edge_count > 4: return
                connected_edges = [
                    bme for bme in bmv.link_edges if is_bmedge_boundary(
                        bme, self.mirror, self.mirror_threshold, self.mirror_clip
                )]
            else:
                connected_edges = list(bmv.link_edges)
            if not connected_edges: return
            if opt_laplacian or opt_edge_length:
                # Faster method when verts are being spread out anyway
                center = Point.average([bme.other_vert(bmv).co for bme in connected_edges])
                force_mult = 1
            else:
                # Slower method that does not spread out verts
                if len(bmv.link_edges) > 4: return
                min_length = min(bme.calc_length() for bme in connected_edges)
                directions = [(bme.other_vert(bmv).co - bmv.co).normalized() for bme in connected_edges]
                center = Point.average([bmv.co + (d * min_length) for d in directions])
                force_mult = 1
            vec = center - bmv.co
            add_force(bmv, vec * strength * force_mult / self.scale_avg, bmv.co, 1, 40)

        def average_edge_length(bme, avg_edge_len):
            ''' Expand and contract edges closer to average edge length '''
            bmv0, bmv1 = bme.verts
            vec = bme_vector(bme)
            edge_len = vec.length
            diff = avg_edge_len - edge_len
            f = vec * (diff * strength)
            add_force(bmv0, -f, bme_midpoint(bme), (avg_edge_len-edge_len), 40)
            add_force(bmv1, f, bme_midpoint(bme), (avg_edge_len-edge_len), 40)

        def average_edge_length_springs(bmv, avg_edge_len):
            # Intended to help edges not collapse around holes but
            # doesn't seem to make a significant difference and has
            # high performance cost
            if bmv not in verts: return
            spring_force = Vector((0,0,0))
            for bme in bmv.link_edges:
                edge_len = bme.calc_length()
                edge_vector = bmv.co - bme.other_vert(bmv).co
                if not edge_len: return
                # positive compression means the vert should move away from the opposite vert
                # negative means it should be pulled towards it, like a spring
                compression = (avg_edge_len - edge_len) / avg_edge_len
                if compression == 0: return
                direction = edge_vector.normalized()
                magnitude = compression * abs(avg_edge_len - edge_len) * strength
                spring_force += direction * magnitude
            if spring_force.length:
                add_force(bmv, spring_force, bmv.co, 1, 40)

        def average_face_radius(bmf, bmv_count):
            ''' push verts toward average dist from verts to face center '''
            ctr = bmf_midpoint(bmf)
            rels = [bmv.co - ctr for bmv in bmf.verts]
            avg_rel_len = sum(rel.length for rel in rels) / bmv_count
            for rel, bmv in zip(rels, bmf.verts):
                rel_len = rel.length
                diff = avg_rel_len - rel_len
                if diff > 0: diff /= 10 # Reduces shrinking
                f = rel * diff * strength * 5
                add_force(bmv, f, bmf_midpoint(bmf), (avg_rel_len - rel_len), 40)

        def average_face_sides(bmf, bmv_count):
            ''' push verts toward equal edge lengths '''
            avg_face_edge_len = sum(bme_length(bme) for bme in bmf.edges) / bmv_count
            for bme in bmf.edges:
                bmv0, bmv1 = bme.verts
                vec = bme_vector(bme)
                edge_len = vec.length
                f = vec * ((avg_face_edge_len - edge_len) * strength * 2)
                add_force(bmv0, f * -0.5, bme_midpoint(bme), (avg_face_edge_len - edge_len), 40)
                add_force(bmv1, f * 0.5, bme_midpoint(bme), (avg_face_edge_len - edge_len), 40)

        def average_face_angles(bmf, bmv_count):
            ''' push verts toward equal spread '''
            bmf_z = bmf.normal.normalized()
            if abs(bmf_z.dot(self.forward)) < 0.95:
                bmf_y = bmf_z.cross(self.forward).normalized()
                bmf_x = bmf_y.cross(bmf_z).normalized()
            else:
                bmf_x = self.up.cross(bmf_z).normalized()
                bmf_y = bmf_z.cross(bmf_x).normalized()
            sum_of_interior_angles = math.pi * (bmv_count - 2)
            angle_target = sum_of_interior_angles / bmv_count
            for i1 in range(bmv_count):
                i0 = (i1 + bmv_count - 1) % bmv_count
                i2 = (i1 + 1) % bmv_count
                bmv0, bmv1, bmv2 = bmf.verts[i0], bmf.verts[i1], bmf.verts[i2]
                v10, v12 = bmv0.co - bmv1.co, bmv2.co - bmv1.co
                d10, d12 = v10.normalized(), v12.normalized()
                d10_2 = Vector((bmf_x.dot(d10), bmf_y.dot(d10))).normalized()
                d12_2 = Vector((bmf_x.dot(d12), bmf_y.dot(d12))).normalized()
                try:
                    angle = d10_2.angle_signed(d12_2)
                    angle_diff = angle_target - angle
                    mag = angle_diff * 0.2 * strength * self.scale_avg * (v10.length + v12.length) ** 2.5
                    add_force(bmv0, d10.cross(bmf_z).normalized() * -mag, bmv0.co, angle_diff, 40)
                    add_force(bmv2, d12.cross(bmf_z).normalized() * mag, bmv1.co, angle_diff, 40)
                except Exception:
                    # Exception is thrown if d10_2 or d12_2 are 0-length
                    pass

        def average_face_areas(bmf, bmv_count, avg_vert_area):
            ''' scale faces towards the average '''
            # Useful for preserving area when faces should retain uneven sides
            diff = (bmf.calc_area() / bmv_count) - avg_vert_area
            center = Point.average(bmv.co for bmv in bmf.verts)
            for bmv in bmf.verts:
                if bmv.is_boundary and len(bmv.link_edges) == 3:
                    other_boundary_verts = [e.other_vert(bmv) for e in bmv.link_edges if e.is_boundary and e in bmf.edges]
                    if other_boundary_verts:
                        center = Point.average([bmv.co, other_boundary_verts[0].co])
                vec = (center - bmv.co) * diff * self.scale_avg * 500
                add_force(bmv, vec * strength, bmf_midpoint(bmf), 1, 40)

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
                    add_force(bmv0, vec * strength * 5, bmf_midpoint(bmf), 1, 40)
                    add_force(bmv1, vec * strength * 5, bmf_midpoint(bmf), 1, 40)

        def relax_3d():
            reset_forces()
            if opt_straight_edges or opt_laplacian:
                for bmv in verts & chk_verts:
                    if opt_laplacian: laplacian_smooth(bmv)
                    if opt_straight_edges: straighten_edges(bmv)
            if opt_edge_length:
                avg_edge_len = sum(bme_length(bme) for bme in edges) / len(edges)
                for bme in edges & chk_edges:
                    average_edge_length(bme, avg_edge_len)
            if opt_equalize_faces:
                avg_vert_area = sum(bmf.calc_area() / len(bmf.verts) for bmf in faces) / len(faces)
                for bmf in faces & chk_faces:
                    bmv_count = len(bmf.verts)
                    average_face_angles(bmf, bmv_count)
                    average_face_radius(bmf, bmv_count)
                    average_face_sides(bmf, bmv_count)
                    average_face_areas(bmf, bmv_count, avg_vert_area)
            if opt_correct_flipped: correct_flipped_faces()

        # perform smoothing
        strength_base = 10.0 * self.scale_avg * brush.strength / radius3D * time_delta * self.pressure
        if opt_method == 'AUTO':
            vert_count = len(verts)
            if opt_equalize_faces: vert_count *= 2 # It's pretty slow
            if opt_mask_boundary == 'SLIDE': vert_count *= 2 # Sliding is slow
            if opt_mask_creases == 'SLIDE': vert_count *= 2
            if opt_mask_sharps == 'SLIDE': vert_count *= 2
            if opt_mask_seams == 'SLIDE': vert_count *= 2
            steps = min(10, max(1, int(100 / vert_count)))
        elif opt_method == 'RK4':
            steps = 1
        else:
            steps = opt_steps
        for step in range(steps):
            if opt_method == 'RK4':
                original = { bmv: Vector(bmv.co) for bmv in verts }

                strength = strength_base
                relax_3d()
                k1 = displace.copy()

                for bmv in original:
                    f1 = k1[bmv] if bmv in k1 else Vector((0,0,0))
                    bmv.co = original[bmv] + f1 / 2
                strength = strength_base / 2
                relax_3d()
                k2 = displace.copy()

                for bmv in original:
                    f2 = k2[bmv] if bmv in k2 else Vector((0,0,0))
                    bmv.co = original[bmv] + f2 / 2
                strength = strength_base / 2
                relax_3d()
                k3 = displace.copy()

                for bmv in original:
                    f3 = k3[bmv] if bmv in k3 else Vector((0,0,0))
                    bmv.co = original[bmv] + f3
                strength = strength_base
                relax_3d()
                k4 = displace.copy()

                strength = strength_base / 6
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
                strength = strength_base / steps
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

                if opt_mask_boundary == 'SLIDE' and bmv in self.boundary_verts:
                    p = self.boundary_accel.closest_point(co) if self.boundary_accel else None
                    if p is not None:
                        co = p
                if opt_mask_seams == 'SLIDE' and bmv in self.seam_verts:
                    p = self.seam_accel.closest_point(co) if self.seam_accel else None
                    if p is not None:
                        co = p
                if opt_mask_creases == 'SLIDE' and bmv in self.crease_verts:
                    p = self.crease_accel.closest_point(co) if self.crease_accel else None
                    if p is not None:
                        co = p
                if opt_mask_sharps == 'SLIDE' and bmv in self.sharp_verts:
                    p = self.sharp_accel.closest_point(co) if self.sharp_accel else None
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
