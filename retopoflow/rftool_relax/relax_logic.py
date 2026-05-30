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
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_origin_3d, region_2d_to_vector_3d
from bpy.types import Context, Event, Region, RegionView3D, Mesh, PropertyGroup
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from bmesh.types import BMesh, BMVert

import math
import time
from math import isnan, inf
from typing import Callable
from collections.abc import Iterator, Sequence

from ..common.bmesh import (
    get_bmesh_emesh, is_bmedge_boundary, is_bmvert_boundary, is_bmvert_corner, is_bmvert_on_ngon, bme_midpoint, bmf_midpoint, EdgeAccel,
    bme_vector, bme_length,
    bmf_is_flipped,
)
from ..common.bmesh_maths import (
    is_bmvert_on_edgemark, is_bmedge_edgemark, BMMarking,
    is_bmvert_pinned,
    is_bmvert_creased,
)
from ..common.maths import (
    view_forward_direction, view_right_direction, view_up_direction,
    xform_direction,
    point_to_bvec3,
    direction_to_bvec3,
)
from ..common.raycast import (
    raycast_valid_sources,
    nearest_point_valid_sources,
    mouse_from_event,
    iter_all_valid_sources,
)
from ..common.drawing import (
    Drawing,
    CC_2D_LINES,
)

from ...addon_common.terminal import term_printer
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import Point, sign_threshold, clamp_int
from ...addon_common.common.colors import Color4
from ..common.iter_utils import AttrIter, CastIter


class Accel:
    BINS_COUNT: int = 10

    bmverts : list[BMVert]
    matrix_world : Matrix
    min_x : float
    min_y : float
    min_z : float
    max_x : float
    max_y : float
    max_z : float
    _bin_scale_x : float
    _bin_scale_y : float
    _bin_scale_z : float
    time : float
    bins : list[list[list[list[BMVert]]]]

    def __init__(self, bmverts:list[BMVert], matrix_world:Matrix, *, bbox:tuple[Vector,Vector]|None=None):
        self.bmverts = bmverts
        self.matrix_world = matrix_world
        self.min_x, self.min_y, self.min_z = 0, 0, 0
        self.max_x, self.max_y, self.max_z = 0, 0, 0
        self._bin_scale_x, self._bin_scale_y, self._bin_scale_z = 0, 0, 0
        self.time = time.time() - 1000
        self.rebuild(bbox=bbox)

    def rebuild(self, *, bbox:tuple[Vector,Vector]|None=None, delta:float=1.0):
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
        loc_points : Iterator[Vector] = AttrIter(self.bmverts, 'co') if bbox is None else CastIter(bbox, Vector)
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

    def index(self, co_world: Vector) -> tuple[int, int, int]:
        max_bin_index = Accel.BINS_COUNT - 1
        ix = clamp_int(int((co_world.x - self.min_x) * self._bin_scale_x), 0, max_bin_index)
        iy = clamp_int(int((co_world.y - self.min_y) * self._bin_scale_y), 0, max_bin_index)
        iz = clamp_int(int((co_world.z - self.min_z) * self._bin_scale_z), 0, max_bin_index)
        return (ix, iy, iz)

    def get(self, co_world:Vector, radius_world:float) -> set[BMVert]:
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
                if is_bmedge_edgemark(bm, bme, BMMarking.crease)
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
                if is_bmedge_edgemark(bm, bme, BMMarking.sharp)
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
                if is_bmedge_edgemark(bm, bme, BMMarking.seam)
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
    bm : BMesh
    em : Mesh
    bvh : BVHTree
    matrix_world : Matrix
    matrix_world_inv : Matrix
    scale_avg : float
    mirror : set[str]
    mirror_clip : bool
    mirror_threshold : Vector

    rf_options : PropertyGroup

    boundary : list[tuple[Vector,Vector]]
    boundary_verts : set[BMVert]
    boundary_accel : EdgeAccel | None
    crease : list[tuple[Vector,Vector]]
    crease_verts : set[BMVert]
    crease_accel : EdgeAccel | None
    sharp : list[tuple[Vector,Vector]]
    sharp_verts : set[BMVert]
    sharp_accel : EdgeAccel | None
    seam : list[tuple[Vector,Vector]]
    seam_verts : set[BMVert]
    seam_accel : EdgeAccel | None

    forward : Vector
    right : Vector
    up : Vector

    mouse : tuple[int, int]
    pressure : float

    prev_position : dict[BMVert, Vector]    # remember where verts were in case of cancel
    prev_displace : dict[BMVert, Vector]    # attempt at preventing verts bouncing unstably
    bounce_mult : dict[BMVert, float]       # ...

    verts_accel : Accel
    verts_accel_time : float

    # debugging and profiling
    draw_vectors_positive : list[tuple[Vector,Vector]]
    draw_vectors_negative : list[tuple[Vector,Vector]]
    draw_vectors_net : list[tuple[Vector,Vector]]
    _time : float

    def mask_opt(self, name : str) -> str:
        return str(getattr(self.rf_options, f'mask_{name}'))
    def include_opt(self, name : str) -> bool:
        return bool(getattr(self.rf_options, f'include_{name}'))

    def __init__(self, context:Context, event:Event, brush, relax, cache=None):
        timings : list[tuple[str,float]] = [('start', time.time())]

        assert context.edit_object, 'Expected to be editing a mesh object'

        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe()
        self.scale_avg = sum(self.matrix_world.to_scale()) / 3
        self.mouse = mouse_from_event(event)
        self.forward = xform_direction(self.matrix_world_inv, view_forward_direction(context))
        self.right = xform_direction(self.matrix_world_inv, view_right_direction(context))
        self.up = xform_direction(self.matrix_world_inv, view_up_direction(context))

        self.brush = brush
        self.relax = relax

        # gather options
        self.rf_options = context.scene.retopoflow
        # opt_use_cache = relax.algorithm_use_cache

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

        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        self._time = time.time()
        self.pressure = 1.0

        self.prev_position = {}
        self.prev_displace = {}
        self.bounce_mult = {}

        self.draw_vectors_positive = []
        self.draw_vectors_negative = []
        self.draw_vectors_net = []


        timings.append(('boundaries', time.time()))
        self.boundary = []
        self.boundary_verts = set()
        self.boundary_accel = None
        if self.mask_opt('boundary') == 'SLIDE':
            boundary_edges = [
                bme
                for bme in self.bm.edges
                if is_bmedge_boundary(bme, self.mirror, self.mirror_threshold, self.mirror_clip)
            ]
            self.boundary = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in boundary_edges
            ]
            self.boundary_verts = {
                bmv
                for bme in boundary_edges
                for bmv in bme.verts
            }
            self.boundary_accel = EdgeAccel(self.boundary)

        timings.append(('creases', time.time()))
        self.crease = []
        self.crease_verts = set()
        self.crease_accel = None
        if self.mask_opt('creases') == 'SLIDE':
            crease_edges = [
                bme
                for bme in self.bm.edges
                if is_bmedge_edgemark(self.bm, bme, BMMarking.crease)
            ]
            self.crease = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in crease_edges
            ]
            self.crease_verts = {
                bmv
                for bme in crease_edges
                for bmv in bme.verts
            }
            self.crease_accel = EdgeAccel(self.crease)

        timings.append(('sharps', time.time()))
        self.sharp = []
        self.sharp_verts = set()
        self.sharp_accel = None
        if self.mask_opt('sharps') == 'SLIDE':
            sharp_edges = [
                bme
                for bme in self.bm.edges
                if is_bmedge_edgemark(self.bm, bme, BMMarking.sharp)
            ]
            self.sharp = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in sharp_edges
            ]
            self.sharp_verts = {
                bmv
                for bme in sharp_edges
                for bmv in bme.verts
            }
            self.sharp_accel = EdgeAccel(self.sharp)

        timings.append(('seams', time.time()))
        self.seam = []
        self.seam_verts = set()
        self.seam_accel = None
        if self.mask_opt('seams') == 'SLIDE':
            seam_edges = [
                bme
                for bme in self.bm.edges
                if is_bmedge_edgemark(self.bm, bme, BMMarking.seam)
            ]
            self.seam = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in seam_edges
            ]
            self.seam_verts = {
                bmv
                for bme in seam_edges
                for bmv in bme.verts
            }
            self.seam_accel = EdgeAccel(self.seam)

        timings.append(('bvh', time.time()))
        self.bvh = BVHTree.FromBMesh(self.bm)

        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        ##########################################################################################
        # denning

        timings.append(('filtering: all but occlusion', time.time()))
        self.verts_filtered : list[BMVert] = [
            bmv for bmv in self.bm.verts
            if all([
                not bmv.hide,
                len(bmv.link_faces) > 0,
                not any(isnan(v) for v in bmv.co),
                not (bmv.is_boundary and is_bmvert_on_ngon(bmv)),
            ])
        ]
        if not self.include_opt('corners'):
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_corner(bmv) ]
        if not self.include_opt('pinned'):
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_pinned(self.bm, bmv) ]
        if self.mask_opt('creases') == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_creased(self.bm, bmv) or is_bmvert_pinned(self.bm, bmv) ]
        if self.mask_opt('creases')  == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.crease) ]
        if self.mask_opt('seams')    == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.seam) ]
        if self.mask_opt('sharps')   == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.sharp) ]
        if self.mask_opt('boundary') == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip) ]
        if self.mask_opt('symmetry') == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_symmetry_plane(bmv) ]
        if self.mask_opt('selected') == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not bmv.select ]
        if self.mask_opt('selected') == 'ONLY':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if bmv.select ]
        if self.mask_opt('boundary') == 'SLIDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_corner(bmv) ]
        if self.mask_opt('seams')    == 'SLIDE':
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if sum(is_bmedge_edgemark(self.bm, bme, BMMarking.seam) for bme in bmv.link_edges) <= 2
            ]
        if self.mask_opt('sharps')   == 'SLIDE':
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if sum(is_bmedge_edgemark(self.bm, bme, BMMarking.sharp) for bme in bmv.link_edges) >= 2
            ]
        if self.mask_opt('creases')  == 'SLIDE':
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if sum(is_bmedge_edgemark(self.bm, bme, BMMarking.crease) for bme in bmv.link_edges) >= 2
            ]

        timings.append(('filtering: only occlusion', time.time()))
        if not self.include_opt('occluded'):
            # ASSUMING WE HAVE A REGION AND REGIONVIEW3D!
            rgn : Region = context.region
            r3d : RegionView3D = context.region_data
            matrix_world = self.matrix_world
            retopology_offset : float = context.space_data.overlay.retopology_offset

            is_bmvert_hidden_list : list[Callable[[Vector, Vector, float], bool]] = []
            for obj in iter_all_valid_sources(context):
                Mi = obj.matrix_world.inverted_safe()
                def hidden_tester(ray_e_world:Vector, ray_d_world:Vector, max_distance:float) -> bool:
                    ray_e_local = point_to_bvec3(Mi @ ray_e_world)
                    ray_d_local = direction_to_bvec3(Mi @ ray_d_world)
                    return obj.ray_cast(ray_e_local, ray_d_local, distance=max_distance)[0]
                is_bmvert_hidden_list.append(hidden_tester)

            def ray_from_point_fast(rgn:Region, r3d:RegionView3D, point_world:Sequence[float]|Vector) -> tuple[Vector|None, Vector|None]:
                point_screen : Sequence[float]|None = location_3d_to_region_2d(rgn, r3d, point_world)  # pyright: ignore [reportAssignmentType]
                if not point_screen: return (None, None)
                return (
                    Vector((*region_2d_to_origin_3d(rgn, r3d, point_screen), 1.0)),
                    Vector((*region_2d_to_vector_3d(rgn, r3d, point_screen).normalized(), 0.0)),
                )

            def is_bmvert_hidden_fast(point_world:Vector, *,factor:float=0.99) -> bool:
                ray_to_e_world, ray_to_d_world = ray_from_point_fast(rgn, r3d, point_world)
                if not ray_to_e_world or not ray_to_d_world: return True
                ray_from_d_world = -ray_to_d_world
                ray_from_e_world = point_world.xyz + ray_from_d_world.xyz * retopology_offset
                max_distance = (ray_to_e_world.xyz - point_world.xyz).length * factor
                return any(
                    fn(ray_from_e_world, ray_from_d_world, max_distance)
                    for fn in is_bmvert_hidden_list
                )

            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not is_bmvert_hidden_fast(matrix_world @ bmv.co)
            ]

        timings.append(('depsgraph and bbox', time.time()))
        depsgraph = context.evaluated_depsgraph_get()
        object_evaluated = context.edit_object.evaluated_get(depsgraph)
        bbox = object_evaluated.bound_box

        timings.append(('accel', time.time()))
        self.verts_accel = Accel(self.verts_filtered, self.matrix_world, bbox=bbox)
        self.verts_accel_time = time.time()

        # timings.append(('kdtree', time.time()))
        # kdt = KDTree(len(self.bm.verts))
        # for i, bmv in enumerate(self.bm.verts):
        #     kdt.insert(bmv.co, i)


        timings.append(('finished', time.time()))
        total_time = timings[-1][1] - timings[0][1]
        report = [
            f'{time1-time0:0.3f}s {label}'
            for (label, time0), (_label, time1) in zip(timings[:-1], timings[1:])
        ] + [f'{total_time:0.3f}s Total']
        term_printer.boxed(*report, title='Timings for Relax_Logic.__init__()')


        # denning
        ##########################################################################################
        # lampel


        # def is_vert_included(bmv):
        #     if bmv.hide: return False
        #     if len(bmv.link_faces) == 0: return False
        #     if isnan(bmv.co.x) or isnan(bmv.co.y) or isnan(bmv.co.z): return False
        #     if self.mask_opt('selected') == 'EXCLUDE' and bmv.select: return False
        #     if self.mask_opt('selected') == 'ONLY' and not bmv.select: return False
        #     if bmv.is_boundary and is_bmvert_on_ngon(bmv): return False
        #     if self.include_opt('corner') == False and is_bmvert_corner(bmv): return False
        #     if self.include_opt('pinned') == False and get_bmvert_attribute(self.bm, bmv, 'retopoflow_pins', 'float'):
        #         return False
        #     if self.mask_opt('symmetry') == 'EXCLUDE' and is_bmvert_on_symmetry_plane(bmv):
        #         return False
        #     if self.mask_opt('creases') == 'EXCLUDE' and (
        #             get_bmvert_attribute(self.bm, bmv, 'crease_vert', 'float') and
        #             not get_bmvert_attribute(self.bm, bmv, 'retopoflow_pins', 'float')
        #     ):
        #         return False
        #     if self.mask_opt('creases') == 'EXCLUDE' and is_bmvert_on_edgemark(self.bm, bmv, 'crease', ensure_lookup=False):
        #         return False
        #     if self.mask_opt('seams') == 'EXCLUDE' and is_bmvert_on_edgemark(self.bm, bmv, 'seam'):
        #         return False
        #     if self.mask_opt('sharps') == 'EXCLUDE' and is_bmvert_on_edgemark(self.bm, bmv, 'sharp'):
        #         return False
        #     if self.mask_opt('boundary') == 'EXCLUDE' and is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip):
        #         return False
        #     if self.mask_opt('boundary') == 'SLIDE' and is_bmvert_corner(bmv):
        #         return False
        #     if self.mask_opt('seams') == 'SLIDE' and sum(1 for bme in bmv.link_edges if is_bmedge_edgemark(self.bm, bme, 'seam')) > 2:
        #         return False
        #     if self.mask_opt('sharps') == 'SLIDE' and sum(1 for bme in bmv.link_edges if is_bmedge_edgemark(self.bm, bme, 'sharp')) > 2:
        #         return False
        #     if self.mask_opt('creases') == 'SLIDE' and sum(1 for bme in bmv.link_edges if is_bmedge_edgemark(self.bm, bme, 'crease', ensure_lookup=False)) > 2:
        #         return False
        #     return True

        # Cache verts and edges between strokes
        # stroke_cache = RelaxStrokeCache(
        #     cache if opt_use_cache else None,
        #     context=context,
        #     bm=self.bm,
        #     matrix_world=self.matrix_world
        # )
        # verts, self.verts_accel = stroke_cache.get_or_build_verts_accel()
        # self.verts_filtered = set([bmv for bmv in verts if is_vert_included(bmv)])
        # edge_data = EdgeAccelBuilder.build(
        #     self.bm,
        #     self.verts_filtered,
        #     self.mirror,
        #     self.mirror_threshold,
        #     self.mirror_clip,
        #     self.mask_opt('boundary'),
        #     self.mask_opt('creases'),
        #     self.mask_opt('sharps'),
        #     self.mask_opt('seams'),
        # )
        # self.boundary = edge_data['boundary']
        # self.boundary_verts = edge_data['boundary_verts']
        # self.boundary_accel = edge_data['boundary_accel']
        # self.crease = edge_data['crease']
        # self.crease_verts = edge_data['crease_verts']
        # self.crease_accel = edge_data['crease_accel']
        # self.sharp = edge_data['sharp']
        # self.sharp_verts = edge_data['sharp_verts']
        # self.sharp_accel = edge_data['sharp_accel']
        # self.seam = edge_data['seam']
        # self.seam_verts = edge_data['seam_verts']
        # self.seam_accel = edge_data['seam_accel']
        # self.verts_accel_time = time.time()

        # self.occlusion_cache = {}

        # end
        ##########################################################################################



    def cancel(self, context):
        for (bmv, co) in self.prev_position.items():
            bmv.co = co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()


    def update(self, context:Context, event:Event):
        match event.type:
            case 'MOUSEMOVE':
                self.pressure = getattr(event, 'pressure', 1.0)
                self.mouse = mouse_from_event(event)
            case 'TIMER':
                mouse = mouse_from_event(event)
                if mouse: self.mouse = mouse
            case 'INBETWEEN_MOUSEMOVE':
                # explicitly ignoring!!
                return
            case _:
                return

        # Limit updates so moving the mouse doesn't update faster than timer
        if time.time() - self._time < 1.0 / 120: return

        if not self.mouse: return

        hit = raycast_valid_sources(context, self.mouse)
        if not hit: return

        # debugging options
        opt_draw_all         = False
        opt_draw_net         = False

        M = self.matrix_world
        Mi = self.matrix_world_inv
        brush = self.brush
        relax = self.relax
        radius3D = self.brush.get_scaled_radius()

        # # Debug: select all verts under brush
        # bmops.deselect_all(self.bm)
        # for bmelem in nearest_bmverts:
        #     bmops.select(self.bm, bmelem)
        # bmops.flush_selection(self.bm, self.em)

        depsgraph = context.evaluated_depsgraph_get()
        object_evaluated = context.edit_object.evaluated_get(depsgraph)
        bbox = object_evaluated.bound_box
        self.verts_accel.rebuild(bbox=bbox)
        if not self.verts_filtered: return
        verts = self.verts_accel.get(hit['co_world'], radius3D)
        # verts = {bmv for bmv in verts if bmv in self.verts_filtered}
        # if not self.include_opt('occluded'):
        #     # Occlusion testing is expensive so only test each vert once per stroke
        #     visible_verts = set()
        #     for bmv in verts:
        #         is_hidden = self.occlusion_cache.get(bmv)
        #         if is_hidden is None:
        #             is_hidden = is_bmvert_hidden(context, bmv)
        #             self.occlusion_cache[bmv] = is_hidden
        #         if not is_hidden:
        #             visible_verts.add(bmv)
        #     verts = visible_verts
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

        self.draw_vectors_positive.clear()
        self.draw_vectors_negative.clear()
        self.draw_vectors_net.clear()

        displace = {}
        def reset_forces():
            nonlocal displace
            displace.clear()
        def add_force(bmv, f, wrt=None, sign=0, mult=0):
            nonlocal displace, verts, vert_strength
            if bmv not in verts or bmv not in vert_strength: return
            if bmv not in displace: displace[bmv] = Vector((0,0,0))
            options = [
                relax.algorithm_laplacian,
                relax.algorithm_average_edge_lengths,
                relax.algorithm_straighten_edges,
                relax.algorithm_equalize_faces, relax.algorithm_equalize_faces, relax.algorithm_equalize_faces, relax.algorithm_equalize_faces,
            ]
            weight_mult = 1 / len([x for x in options if x == True])
            displace[bmv] += f.xyz * vert_strength[bmv] * weight_mult
            if opt_draw_all and wrt:
                if sign > 0:
                    self.draw_vectors_positive.append((wrt, f.xyz * mult * vert_strength[bmv]))
                elif sign < 0:
                    self.draw_vectors_negative.append((wrt, f.xyz * mult * vert_strength[bmv]))

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
                if bmv not in self.prev_position: self.prev_position[bmv] = Vector(bmv.co)
                weighted_o = self.prev_position[bmv] * shape_preservation
                weighted_q = bmv.co * (1 - shape_preservation)
                displacement = average_co - (weighted_o + weighted_q)
            else:
                displacement = average_co - bmv.co
            if bmv.is_boundary: displacement /= 2
            add_force(bmv, displacement / 10, mult=40)

        def straighten_edges(bmv):
            ''' push verts to straighten edges (still WiP!) '''
            is_boundary = is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip)
            if is_boundary and self.mask_opt('boundary') == 'EXCLUDE': return
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
            if relax.algorithm_laplacian or relax.algorithm_average_edge_lengths:
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
            if relax.algorithm_straighten_edges or relax.algorithm_laplacian:
                for bmv in verts & chk_verts:
                    if relax.algorithm_laplacian: laplacian_smooth(bmv)
                    if relax.algorithm_straighten_edges: straighten_edges(bmv)
            if relax.algorithm_average_edge_lengths:
                avg_edge_len = sum(bme_length(bme) for bme in edges) / len(edges)
                for bme in edges & chk_edges:
                    average_edge_length(bme, avg_edge_len)
            if relax.algorithm_equalize_faces:
                avg_vert_area = sum(bmf.calc_area() / len(bmf.verts) for bmf in faces) / len(faces)
                for bmf in faces & chk_faces:
                    bmv_count = len(bmf.verts)
                    average_face_angles(bmf, bmv_count)
                    average_face_radius(bmf, bmv_count)
                    average_face_sides(bmf, bmv_count)
                    average_face_areas(bmf, bmv_count, avg_vert_area)
            if relax.algorithm_correct_flipped_faces: correct_flipped_faces()

        # perform smoothing
        strength_base = 10.0 * self.scale_avg * brush.strength / radius3D * time_delta * self.pressure
        if relax.algorithm_method == 'AUTO':
            vert_count = len(verts)
            if relax.algorithm_equalize_faces: vert_count *= 2 # It's pretty slow
            if self.mask_opt('boundary') == 'SLIDE': vert_count *= 2 # Sliding is slow
            if self.mask_opt('creases') == 'SLIDE': vert_count *= 2
            if self.mask_opt('sharps') == 'SLIDE': vert_count *= 2
            if self.mask_opt('seams') == 'SLIDE': vert_count *= 2
            steps = min(10, max(1, int(100 / vert_count)))
        elif relax.algorithm_method == 'RK4':
            steps = 1
        else:
            steps = relax.algorithm_iterations
        for step in range(steps):
            if relax.algorithm_method == 'RK4':
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

            if relax.algorithm_prevent_bounce:
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
                mult *= min(1.0, radius3D * relax.algorithm_max_distance_radius / displace_max)
            # print(time_delta, radius3D, relax.algorithm_max_distance_radius, displace_max, mult)
            if displace_max > radius3D:
                print('Relax: Limiting distance')
                break

            # update
            update_to = {}
            for bmv in displace:
                if bmv not in self.prev_position: self.prev_position[bmv] = Vector(bmv.co)

                displace_dist = displace[bmv].length * mult
                if bmv.link_edges and displace_dist > 1e-8:
                    avg_edge_len = sum(bme_length(bme) for bme in bmv.link_edges) / len(bmv.link_edges)
                    displace_dist *= min(1.0, avg_edge_len * relax.algorithm_max_distance_edges / displace_dist)
                # displace_dist *= vert_strength[bmv]
                if relax.algorithm_prevent_bounce:
                    displace_dist *= self.bounce_mult.get(bmv, 1.0)
                displace_vec = displace[bmv].normalized() * displace_dist
                co = bmv.co + displace_vec

                if opt_draw_net:
                    self.draw_vectors_net.append((bmv.co, displace_vec * 100))

                if self.mask_opt('boundary') == 'SLIDE' and bmv in self.boundary_verts:
                    p = self.boundary_accel.closest_point(co) if self.boundary_accel else None
                    if p is not None:
                        co = p
                if self.mask_opt('seams') == 'SLIDE' and bmv in self.seam_verts:
                    p = self.seam_accel.closest_point(co) if self.seam_accel else None
                    if p is not None:
                        co = p
                if self.mask_opt('creases') == 'SLIDE' and bmv in self.crease_verts:
                    p = self.crease_accel.closest_point(co) if self.crease_accel else None
                    if p is not None:
                        co = p
                if self.mask_opt('sharps') == 'SLIDE' and bmv in self.sharp_verts:
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
            for (co,v) in self.draw_vectors_positive:
                co0, co1 = co, co + v
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ co0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ co1)
                if pt0 and pt1:
                    draw.vertex(pt0)
                    draw.vertex(pt1)
            draw.color(Color4((1, 0, 0, 0.5)))
            for (co,v) in self.draw_vectors_negative:
                co0, co1 = co, co + v
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ co0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ co1)
                if pt0 and pt1:
                    draw.vertex(pt0)
                    draw.vertex(pt1)
            draw.color(Color4((1, 1, 0, 0.5)))
            for (co,v) in self.draw_vectors_net:
                co0, co1 = co, co + v
                pt0 = location_3d_to_region_2d(rgn, r3d, M @ co0)
                pt1 = location_3d_to_region_2d(rgn, r3d, M @ co1)
                if pt0 and pt1:
                    draw.vertex(pt0)
                    draw.vertex(pt1)
