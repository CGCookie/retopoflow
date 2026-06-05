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
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from bmesh.utils import edge_split
from bpy.types import Context, Event, Region, RegionView3D, Mesh, PropertyGroup
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_origin_3d, region_2d_to_vector_3d
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_line_2d
from mathutils.bvhtree import BVHTree

import math
import time
from typing import Callable
from collections.abc import Sequence

from ..common.accel import EdgeMarkAccel
from ..common.bmesh import get_bmesh_emesh, NearestBMVert, is_bmvert_boundary, is_bmvert_corner, bmv_co_isnan
from ..common.bmesh_maths import (
    is_bmvert_on_edgemark, is_bmedge_edgemark, BMMarking,
    is_bmvert_pinned, is_bmvert_creased,
)
from ..common.maths import point_to_bvec3, point_to_bvec4, direction_to_bvec3
from ..common.raycast import (
    raycast_valid_sources, raycast_point_valid_sources, nearest_point_valid_sources,
    mouse_from_event, iter_all_valid_sources,
)

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import closest_point_segment, Point, sign, sign_threshold

class Tweak_Logic:
    bm : BMesh
    em : Mesh
    matrix_world : Matrix
    matrix_world_inv : Matrix
    mirror : set[str]
    mirror_clip : bool
    mirror_threshold : Vector

    rf_options : PropertyGroup

    check_nans : bool = True

    sources : 'list[tuple[object, Matrix, Matrix, Matrix]]'

    boundary_verts : set[BMVert]
    boundary_accel : EdgeMarkAccel
    crease_verts : set[BMVert]
    crease_accel : EdgeMarkAccel
    sharp_verts : set[BMVert]
    sharp_accel : EdgeMarkAccel
    seam_verts : set[BMVert]
    seam_accel : EdgeMarkAccel

    is_bmvert_hidden : Callable[[BMVert], bool]
    visibility_cache : dict[BMVert, bool]

    verts_filtered : list[BMVert]
    verts : list[tuple]            # (bmv, original co, projected xy, brush strength) captured at grab time

    mouse : Vector
    mouse_prev : Vector
    _time : float

    def __init__(self, context, event, brush, tweak):
        self.brush = brush
        self.tweak = tweak

        self.rf_options = context.scene.retopoflow

        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        self._time = time.time()

        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe()

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

        boundary, crease, sharp, seam = EdgeMarkAccel.build_all(
            self.bm, self.mirror, self.mirror_threshold, self.mirror_clip,
            slide_boundary = self.mask_opt('boundary') == 'SLIDE',
            slide_creases  = self.mask_opt('creases')  == 'SLIDE',
            slide_sharps   = self.mask_opt('sharps')   == 'SLIDE',
            slide_seams    = self.mask_opt('seams')    == 'SLIDE',
        )
        self.boundary_verts, self.boundary_accel = boundary
        self.crease_verts,   self.crease_accel   = crease
        self.sharp_verts,    self.sharp_accel    = sharp
        self.seam_verts,     self.seam_accel     = seam

        self.sources = []
        for obj in iter_all_valid_sources(context):
            M_obj = obj.matrix_world
            Mi_obj = M_obj.inverted_safe()
            self.sources.append((obj, M_obj, Mi_obj, Mi_obj.to_3x3()))

        self.collect_verts(context, event)

    def mask_opt(self, name : str) -> str:
        return str(getattr(self.rf_options, f'mask_{name}'))  # pyright: ignore[reportAny]
    def include_opt(self, name : str) -> bool:
        return bool(getattr(self.rf_options, f'include_{name}'))  # pyright: ignore[reportAny]
    def exclude_opt(self, name : str) -> bool:
        return not bool(getattr(self.rf_options, f'include_{name}'))  # pyright: ignore[reportAny]

    def collect_verts(self, context, event):
        self.verts = []
        self.mouse = Vector(mouse_from_event(event))
        self.mouse_prev = self.mouse.copy()

        hit = raycast_valid_sources(context, self.mouse)
        if not hit: return

        M = self.matrix_world
        brush_center_world = Vector(hit['co_world'])

        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        # right now, falloff brush works in 3D... should switch to 2D?
        radius2D, radius3D = self.brush.radius, self.brush.get_scaled_radius()

        self.bm.verts.ensure_lookup_table() # Ensure here so the per-vert filters don't need to call it

        self.verts_filtered = [
            bmv for bmv in self.bm.verts
            if not bmv.hide and ((M @ bmv.co) - brush_center_world).length <= radius3D
        ]

        if Tweak_Logic.check_nans:
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not bmv_co_isnan(bmv) ]
            Tweak_Logic.check_nans = False

        # Tier 1: O(1) direct attribute reads
        if self.mask_opt('selected') == 'ONLY':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if bmv.select ]
        elif self.mask_opt('selected') == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not bmv.select ]
        # Tier 2: O(1) len() checks
        if self.exclude_opt('corners'):
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_corner(bmv) ]
        if self.mask_opt('boundary') == 'SLIDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_corner(bmv) ]
        # Tier 3: attribute check + possible hidden-edge scan
        if self.mask_opt('boundary') == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip) ]
        if self.mask_opt('symmetry') == 'EXCLUDE':
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_symmetry_plane(bmv) ]
        # Tier 4: layer dict-lookup + vert data access
        if self.exclude_opt('pinned'): self.verts_filtered = [
            bmv for bmv in self.verts_filtered if not is_bmvert_pinned(self.bm, bmv, ensure_lookup_table=False)
        ]
        if self.mask_opt('creases') == 'EXCLUDE':
            # Needs to check both vert and edge creases and account for pins.
            if self.bm.verts.layers.float.get('crease_vert'):
                self.verts_filtered = [ bmv for bmv in self.verts_filtered if (
                    not is_bmvert_creased(self.bm, bmv, ensure_lookup_table=False) or is_bmvert_pinned(self.bm, bmv, ensure_lookup_table=False)
                )]
            if self.bm.edges.layers.float.get('crease_edge'):
                self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.crease) ]
        # Tier 5: iterate link_edges with any()/all()
        if self.mask_opt('seams') == 'EXCLUDE':
            if any(bme.seam for bme in self.bm.edges):
                self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.seam) ]
        if self.mask_opt('sharps') == 'EXCLUDE':
            if any(not bme.smooth for bme in self.bm.edges):
                self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_on_edgemark(self.bm, bmv, BMMarking.sharp) ]
        # Tier 6: iterate link_edges calling a function per edge
        # seam_verts/sharp_verts/crease_verts are pre-built by build_all so the truthiness check is free.
        if self.mask_opt('seams') == 'SLIDE' and self.seam_verts:
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.seam) for bme in bmv.link_edges) > 2
            ]
        if self.mask_opt('sharps') == 'SLIDE' and self.sharp_verts:
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.sharp) for bme in bmv.link_edges) > 2
            ]
        if self.mask_opt('creases') == 'SLIDE' and self.crease_verts:
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.crease) for bme in bmv.link_edges) > 2
            ]

        self.visibility_cache = {}
        self.is_bmvert_hidden = lambda _bmv: False  # nop where every bmvert is visible
        if self.exclude_opt('occluded'):
            # ASSUMING WE HAVE A REGION AND REGIONVIEW3D!
            rgn : Region = context.region
            r3d : RegionView3D = context.region_data
            matrix_world = self.matrix_world
            retopology_offset : float = context.space_data.overlay.retopology_offset

            is_bmvert_hidden_list : list[Callable[[Vector, Vector, float], bool]] = []
            for obj in iter_all_valid_sources(context):
                Mi = obj.matrix_world.inverted_safe()
                def hidden_tester(ray_e_world:Vector, ray_d_world:Vector, max_distance:float, obj=obj, Mi=Mi) -> bool:
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

            def is_point_hidden_fast(point_world:Vector, *, factor:float=0.99) -> bool:
                ray_to_e_world, ray_to_d_world = ray_from_point_fast(rgn, r3d, point_world)
                if not ray_to_e_world or not ray_to_d_world: return True
                ray_from_d_world = -ray_to_d_world
                ray_from_e_world = point_world.xyz + ray_from_d_world.xyz * retopology_offset
                max_distance = (ray_to_e_world.xyz - point_world.xyz).length * factor
                return any(
                    fn(ray_from_e_world, ray_from_d_world, max_distance)
                    for fn in is_bmvert_hidden_list
                )

            def is_bmvert_hidden(bmv : BMVert) -> bool:
                if bmv not in self.visibility_cache:
                    self.visibility_cache[bmv] = is_point_hidden_fast(matrix_world @ bmv.co)
                return self.visibility_cache[bmv]

            self.is_bmvert_hidden = is_bmvert_hidden

            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not self.is_bmvert_hidden(bmv)
            ]

        self.verts = [
            (
                bmv,
                Vector(bmv.co), # original location
                self.project_bmv(context, bmv), # screen position
                self.brush.get_strength_Point(M @ bmv.co), # grab strength
            )
            for bmv in self.verts_filtered
        ]


    def cancel(self, context):
        if not self.verts: return
        for (bmv, co, _, _) in self.verts:
            bmv.co = co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def project_pt(self, context, pt):
        p = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt)
        return p.xy if p else None

    def project_bmv(self, context, bmv):
        p = self.project_pt(context, bmv.co)
        return p.xy if p else None


    def update(self, context, event):
        pressure = getattr(event, 'pressure', 1.0)

        if not self.verts: return
        if event.type != 'MOUSEMOVE': return

        mouse = Vector(mouse_from_event(event))
        delta = mouse - self.mouse_prev
        if delta.length_squared == 0: return

        M = self.matrix_world
        Mi = self.matrix_world_inv

        for (bmv, co_orig, xy, strength) in self.verts:
            if self.mask_opt('boundary') == 'SLIDE' and bmv in self.boundary_verts:
                new_co = Vector(bmv.co)
                delta_strength = delta.length * strength * pressure
                opt_steps = max(math.ceil(delta_strength / 10), 1)
                for step in range(opt_steps):
                    pt2d = self.project_pt(context, new_co) or xy
                    new_co2 = raycast_valid_sources(context, pt2d + delta * (strength / opt_steps) * pressure)
                    if not new_co2: break
                    new_co = new_co2['co_local']
                    if self.boundary_accel:
                        p = self.boundary_accel.closest_point(new_co)
                        if p is not None:
                            new_co = p
            else:
                cur_xy = self.project_bmv(context, bmv) or xy
                new_co = raycast_valid_sources(context, cur_xy + delta * strength * pressure)
                if not new_co: continue
                new_co = new_co['co_local']
                if self.mask_opt('seams') == 'SLIDE' and bmv in self.seam_verts:
                    if self.seam_accel:
                        p = self.seam_accel.closest_point(new_co)
                        if p is not None: new_co = p
                if self.mask_opt('sharps') == 'SLIDE' and bmv in self.sharp_verts:
                    if self.sharp_accel:
                        p = self.sharp_accel.closest_point(new_co)
                        if p is not None: new_co = p
                if self.mask_opt('creases') == 'SLIDE' and bmv in self.crease_verts:
                    if self.crease_accel:
                        p = self.crease_accel.closest_point(new_co)
                        if p is not None: new_co = p

            if self.mirror:
                co = Vector(new_co)
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
                    co_world_snapped = nearest_point_valid_sources(context, point_to_bvec3(co_world), world=True, sources=self.sources)
                    if not co_world_snapped: continue
                    co = Mi @ co_world_snapped
                    if d < 0.001: break  # break out if change was below threshold
                if zero['x']: co.x = 0
                if zero['y']: co.y = 0
                if zero['z']: co.z = 0
                new_co = co


            if new_co: bmv.co = new_co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()
        self.mouse_prev = mouse
