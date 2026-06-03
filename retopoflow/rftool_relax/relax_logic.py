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
from bmesh.types import BMesh, BMVert, BMEdge

import math
import time
from math import isnan, inf
from typing import Callable
from collections.abc import Iterator, Sequence

from ..common.accel import EdgeMarkAccel, SourceAccel, Accel
from ..common.bmesh import (
    get_bmesh_emesh, is_bmedge_boundary, is_bmvert_boundary, is_bmvert_corner, is_bmvert_on_ngon, bme_midpoint, bmf_midpoint,
    bmv_co_isnan,
    get_bmv_loop_pairs,
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
from ...addon_common.common.maths import Point, sign_threshold, clamp_int, clamp
from ...addon_common.common.colors import Color4


class Relax_Logic:
    bm : BMesh
    em : Mesh
    matrix_world : Matrix
    matrix_world_inv : Matrix
    scale_avg : float
    mirror : set[str]
    mirror_clip : bool
    mirror_threshold : Vector

    rf_options : PropertyGroup

    check_nans : bool = True

    boundary_verts : set[BMVert]
    boundary_accel : EdgeMarkAccel
    crease_verts : set[BMVert]
    crease_accel : EdgeMarkAccel
    sharp_verts : set[BMVert]
    sharp_accel : EdgeMarkAccel
    seam_verts : set[BMVert]
    seam_accel : EdgeMarkAccel
    verts_near_source_edge: set[BMVert]

    source_edge_accel : SourceAccel | None
    source_sharp_proximity : float
    elected_loop_verts : set[BMVert]

    is_bmvert_hidden : Callable[[BMVert], bool]
    visibility_cache : dict[BMVert, bool]

    forward : Vector
    right : Vector
    up : Vector

    mouse : tuple[int, int]
    pressure : float

    prev_position : dict[BMVert, Vector]    # remember where verts were in case of cancel
    prev_displace : dict[BMVert, Vector]    # attempt at preventing verts bouncing unstably
    bounce_mult : dict[BMVert, float]       # ...

    verts_accel : Accel
    laplacian_cache : dict[BMVert, tuple[tuple[BMVert, ...], bool, float] | None]
    straighten_cache : dict[BMVert, tuple[bool, tuple[BMVert, ...], tuple[BMVert, ...], int] | None]
    straighten_loops_cache : dict[BMVert, tuple[tuple[BMVert, BMVert], ...] | None]
    face_topology_cache : dict[BMVert, tuple[tuple[BMVert, ...], tuple[BMEdge, ...]] | None]

    # debugging and profiling
    draw_vectors_positive : list[tuple[Vector,Vector]]
    draw_vectors_negative : list[tuple[Vector,Vector]]
    draw_vectors_net : list[tuple[Vector,Vector]]
    _time : float




    def set_source_accel(self, context, relax):
        source_angle  = getattr(relax, 'source_edge_angle',  math.pi)
        source_sharps = getattr(relax, 'source_edge_sharps', False)
        source_seams        = getattr(relax, 'source_edge_seams',  False)
        source_creases      = getattr(relax, 'source_edge_creases',False)
        if not (
            getattr(self.relax, 'snap_to_source_features', False) or
            source_sharps or
            source_seams or
            source_creases or
            source_angle < math.pi):
            self.source_edge_accel = None
            return
        self.source_edge_accel = SourceAccel.build(
            context, source_angle, source_sharps, source_seams, source_creases,
        )



    def mask_opt(self, name : str) -> str:
        return str(getattr(self.rf_options, f'mask_{name}'))  # pyright: ignore[reportAny]
    def include_opt(self, name : str) -> bool:
        return bool(getattr(self.rf_options, f'include_{name}'))  # pyright: ignore[reportAny]
    def exclude_opt(self, name : str) -> bool:
        return not bool(getattr(self.rf_options, f'include_{name}'))  # pyright: ignore[reportAny]

    def __init__(self, context:Context, event:Event, brush, relax, *, debug_print:bool=False):
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

        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        self._time = time.time()
        self.pressure = 1.0

        self.prev_position = {}
        self.prev_displace = {}
        self.bounce_mult = {}

        self.draw_vectors_positive = []
        self.draw_vectors_negative = []
        self.draw_vectors_net = []

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

        timings.append(('edge accels', time.time()))
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

        self.source_edge_accel = None
        self.set_source_accel(context, relax)
        self.source_sharp_proximity = getattr(relax, 'source_edge_proximity', 0.1)
        self.stickiness = getattr(relax, 'source_edge_stickiness', 0.5) if self.source_edge_accel else 0.0

        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        timings.append(('filtering: initial', time.time()))
        def bmv_is_good(bmv : BMVert) -> bool:
            if bmv.hide: return False
            if bmv.is_wire: return False
            if bmv.is_boundary and is_bmvert_on_ngon(bmv): return False
            return True
        self.verts_filtered : list[BMVert] = [ bmv for bmv in self.bm.verts if bmv_is_good(bmv) ]

        if Relax_Logic.check_nans:
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not bmv_co_isnan(bmv) ]
            Relax_Logic.check_nans = False

        timings.append(('filtering: bmvert and bmedge features', time.time()))
        if self.exclude_opt('corners'):
            self.verts_filtered = [ bmv for bmv in self.verts_filtered if not is_bmvert_corner(bmv) ]
        if self.exclude_opt('pinned'):
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
        if self.mask_opt('seams') == 'SLIDE':
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.seam) for bme in bmv.link_edges) > 2
            ]
        if self.mask_opt('sharps') == 'SLIDE':
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.sharp) for bme in bmv.link_edges) > 2
            ]
        if self.mask_opt('creases') == 'SLIDE':
            self.verts_filtered = [
                bmv for bmv in self.verts_filtered
                if not sum(is_bmedge_edgemark(self.bm, bme, BMMarking.crease) for bme in bmv.link_edges) > 2
            ]

        self.laplacian_cache = {}
        self.straighten_cache = {}
        self.straighten_loops_cache = {}
        self.face_topology_cache = {}
        self.elected_loop_verts = set() # Helps guide snapping to sharp edges

        timings.append(('filtering: setting up visibility test', time.time()))
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

            def is_point_hidden_fast(point_world:Vector, *,factor:float=0.99) -> bool:
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

            # self.verts_filtered = [
            #     bmv for bmv in self.verts_filtered
            #     if not is_point_hidden_fast(matrix_world @ bmv.co)
            # ]

        timings.append(('accel', time.time()))
        self.verts_accel = Accel(context, self.verts_filtered, self.matrix_world)

        timings.append(('finished', time.time()))
        total_time = timings[-1][1] - timings[0][1]
        report = [
            f'{time1-time0:0.3f}s {label}'
            for (label, time0), (_label, time1) in zip(timings[:-1], timings[1:])
        ] + ['------ --------------', f'{total_time:0.3f}s total']
        if debug_print:
            term_printer.boxed(*report, title='Timings for Relax_Logic.__init__()')


    def cancel(self, context):
        for (bmv, co) in self.prev_position.items():
            bmv.co = co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()


    def update(self, context:Context, event:Event, *, debug_print:bool=False):
        self.verts_accel.rebuild(context)

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

        hit = raycast_valid_sources(context, self.mouse)
        if not hit: return
        co_world : Vector = hit['co_world']  # pyright: ignore[reportAssignmentType]

        # Limit updates so moving the mouse doesn't update faster than timer
        cur_time = time.time()
        time_delta = cur_time - self._time
        if time_delta < 1.0 / 120:
            return # do not run faster than 120Hz!
        time_delta = clamp(time_delta, 0.0, 0.1)
        self._time = cur_time

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

        if not self.verts_filtered: return
        verts = self.verts_accel.get(co_world, radius3D)
        if self.exclude_opt('occluded'):
            verts = { bmv for bmv in verts if not self.is_bmvert_hidden(bmv) }
        if not verts: return
        edges = { bme for bmv in verts for bme in bmv.link_edges }
        if not edges: return
        faces = { bmf for bmv in verts for bmf in bmv.link_faces }
        vert_strength = { bmv:brush.get_strength_Point(M @ bmv.co) for bmv in verts }

        strength = self.pressure

        # capture all verts involved in relaxing
        chk_verts = set(verts)
        chk_verts.update({ bmv for bme in edges for bmv in bme.verts })
        chk_verts.update({ bmv for bmf in faces for bmv in bmf.verts })
        # chk_edges = { bme for bmv in chk_verts for bme in bmv.link_edges }
        chk_faces = { bmf for bmv in chk_verts for bmf in bmv.link_faces }

        self.verts_near_source_edge = set()

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
            enabled_algorithms_count = (
                int(relax.algorithm_laplacian) +
                int(relax.algorithm_average_edge_lengths) +
                int(relax.algorithm_straighten_edges) +
                int(relax.algorithm_equalize_faces) * 2
            )
            weight_mult = (1.0 / enabled_algorithms_count) if enabled_algorithms_count else 0.0
            displace[bmv] += f.xyz * vert_strength[bmv] * weight_mult
            if opt_draw_all and wrt:
                if sign > 0:
                    self.draw_vectors_positive.append((wrt, f.xyz * mult * vert_strength[bmv]))
                elif sign < 0:
                    self.draw_vectors_negative.append((wrt, f.xyz * mult * vert_strength[bmv]))

        def laplacian_smooth(bmv, laplacian_cache, shape_preservation=0):
            ''' Push verts towards the average of their neighbors '''
            if bmv in laplacian_cache:
                laplacian_data = laplacian_cache[bmv]
                if laplacian_data is None: return
            else:
                link_edges = bmv.link_edges
                edge_count = len(link_edges)
                if (
                    edge_count == 2 or
                    edge_count == 4 and len(bmv.link_faces) == 3
                ):
                    laplacian_cache[bmv] = None
                    return
                is_boundary = bmv.is_boundary
                if is_boundary:
                    if edge_count > 4:
                        laplacian_cache[bmv] = None
                        return
                    neighbors = tuple(bme.other_vert(bmv) for bme in link_edges if bme.is_boundary)
                else:
                    neighbors = tuple(bme.other_vert(bmv) for bme in link_edges)
                if not neighbors:
                    laplacian_cache[bmv] = None
                    return
                laplacian_data = (neighbors, is_boundary, 1.0 / len(neighbors))
                laplacian_cache[bmv] = laplacian_data
            neighbors, is_boundary, nb_reciprocal = laplacian_data

            edge_proj_dir = None
            if self.verts_near_source_edge and bmv in self.verts_near_source_edge:
                # slides snapped vertices along source edges
                edge_nbrs = [nb for nb in neighbors if nb in self.verts_near_source_edge]
                if len(edge_nbrs) >= 2:
                    v = edge_nbrs[-1].co - edge_nbrs[0].co
                    if v.length > 0:
                        edge_proj_dir = v.normalized()
                elif len(edge_nbrs) == 1:
                    v = edge_nbrs[0].co - bmv.co
                    if v.length > 0:
                        edge_proj_dir = v.normalized()
                else:
                    # no edge-constrained neighbors found
                    if is_boundary:
                        all_edge_nbrs = [
                            bme.other_vert(bmv) for bme in bmv.link_edges
                            if bme.other_vert(bmv) in self.verts_near_source_edge
                        ]
                        if all_edge_nbrs:
                            v = all_edge_nbrs[0].co - bmv.co
                            if v.length > 1e-8:
                                edge_proj_dir = v.normalized()
                    if edge_proj_dir is None:
                        return

            sum_x = sum_y = sum_z = 0.0
            for nb in neighbors:
                nb_co = nb.co
                sum_x += nb_co[0]
                sum_y += nb_co[1]
                sum_z += nb_co[2]
            average_co = Vector((sum_x * nb_reciprocal, sum_y * nb_reciprocal, sum_z * nb_reciprocal))

            bmv_co = bmv.co
            if shape_preservation:
                # Shape Preservation doesn't seem to work well with how the brush iterates
                prev_position = self.prev_position
                prev_co = prev_position.get(bmv)
                if prev_co is None:
                    prev_co = Vector(bmv_co)
                    prev_position[bmv] = prev_co
                weighted_o = prev_co * shape_preservation
                weighted_q = bmv_co * (1.0 - shape_preservation)
                displacement = average_co - (weighted_o + weighted_q)
            else:
                displacement = average_co - bmv_co
            if is_boundary: displacement *= 0.5

            if edge_proj_dir is not None:
                # Project edge constrained verts onto the edge
                displacement = edge_proj_dir * displacement.dot(edge_proj_dir)

            add_force(bmv, displacement * 0.1, mult=40)

        def straighten_edges(bmv, straighten_cache):
            ''' push verts to straighten edges (still WiP!) '''
            if self.verts_near_source_edge and bmv in self.verts_near_source_edge:
                # Skip to avoid bad pulling at constrained edges
                return

            if bmv in straighten_cache:
                straighten_data = straighten_cache[bmv]
                if straighten_data is None: return
            else:
                link_edges = bmv.link_edges
                edge_count = len(link_edges)
                face_count = len(bmv.link_faces)
                if edge_count == 2 or (edge_count == 4 and face_count == 3):
                    straighten_cache[bmv] = None
                    return
                neighbors = tuple(bme.other_vert(bmv) for bme in link_edges)
                if not neighbors:
                    straighten_cache[bmv] = None
                    return
                boundary_neighbors = tuple(
                    bme.other_vert(bmv)
                    for bme in link_edges
                    if is_bmedge_boundary(bme, self.mirror, self.mirror_threshold, self.mirror_clip)
                )
                is_boundary = is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip)
                straighten_data = (is_boundary, neighbors, boundary_neighbors, edge_count)
                straighten_cache[bmv] = straighten_data
            is_boundary, neighbors, boundary_neighbors, edge_count = straighten_data

            if is_boundary and self.mask_opt('boundary') == 'EXCLUDE': return
            if is_boundary:
                if edge_count > 4: return
                neighbors = boundary_neighbors
            if not neighbors: return

            if relax.algorithm_laplacian or relax.algorithm_average_edge_lengths:
                # Faster method when verts are being spread out anyway
                sum_x = sum_y = sum_z = 0.0
                for nb in neighbors:
                    nb_co = nb.co
                    sum_x += nb_co[0]
                    sum_y += nb_co[1]
                    sum_z += nb_co[2]
                reciprocal = 1.0 / len(neighbors)
                center = Vector((sum_x * reciprocal, sum_y * reciprocal, sum_z * reciprocal))
                force_mult = 0.5
            else:
                # Slower method that does not spread out verts
                if is_boundary:
                    # min_length pulls toward the shorter edge end (corner-slide); use centroid instead.
                    center = Point.average([nb.co for nb in neighbors])
                    force_mult = 0.5
                else:
                    if edge_count > 4: return
                    min_length = min((nb.co - bmv.co).length for nb in neighbors)
                    directions = [(nb.co - bmv.co).normalized() for nb in neighbors]
                    center = Point.average([bmv.co + (d * min_length) for d in directions])
                    force_mult = 1
            vec = (center - bmv.co) * force_mult
            add_force(bmv, vec, bmv.co, 1, 40)

        def straighten_loops(bmv, straighten_loops_cache):
            ''' push quad verts towards the line between opposing neighbords '''
            if self.verts_near_source_edge and bmv in self.verts_near_source_edge:
                # Skip to preserve verts constrained to source edges
                return

            if bmv in straighten_loops_cache:
                loops = straighten_loops_cache[bmv]
            else:
                link_edges = list(bmv.link_edges)
                if len(link_edges) != 4 or len(bmv.link_faces) != 4:
                    loops = None
                else:
                    loops = get_bmv_loop_pairs(bmv)
                straighten_loops_cache[bmv] = loops
            if not loops: return

            co = bmv.co
            for (start_pt, end_pt) in loops:
                direction  = end_pt.co - start_pt.co
                len_sq = direction.dot(direction)
                if len_sq < 1e-12: continue
                t = (co - start_pt.co).dot(direction) / len_sq
                closest = start_pt.co + direction * t
                add_force(bmv, (closest - co) * 0.5, co, 1, 40)

        def average_edge_length(bme, avg_edge_len):
            ''' Expand and contract edges closer to average edge length '''
            bmv0, bmv1 = bme.verts
            vec = bme_vector(bme)
            diff = avg_edge_len - vec.length
            if abs(diff) < 1e-12: return
            edge_midpoint = bme_midpoint(bme)
            f = vec.normalized() * diff / 25
            add_force(bmv0, -f, edge_midpoint, diff, 40)
            add_force(bmv1, f, edge_midpoint, diff, 40)

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

        def average_face_radius(bmf, avg_vert_area_sqrt, center, face_topology_cache):
            ''' push verts toward average dist from verts to face center '''
            if bmf in face_topology_cache:
                verts, edges = face_topology_cache[bmf]
            else:
                verts = tuple(bmv for bmv in bmf.verts)
                face_topology_cache[bmf] = (verts, tuple(bme for bme in bmf.edges))
            rels = [bmv.co - center for bmv in verts]
            avg_rel_len = sum(rel.length for rel in rels) / len(verts)
            for rel, bmv in zip(rels, verts):
                rel_len = rel.length
                diff = avg_rel_len - rel_len
                if diff > 0: diff /= 10 # Reduces shrinking
                f = rel.normalized() * (diff / avg_rel_len) * avg_vert_area_sqrt
                add_force(bmv, f, center, (avg_rel_len - rel_len), 40)

        def average_face_sides(bmf, avg_vert_area_sqrt, face_topology_cache):
            ''' push verts toward equal edge lengths '''
            if bmf in face_topology_cache:
                verts, edges = face_topology_cache[bmf]
            else:
                verts = tuple(bmv for bmv in bmf.verts)
                edges = tuple(bme for bme in bmf.edges)
                face_topology_cache[bmf] = (verts, edges)
            avg_face_edge_len = sum(bme_length(bme) for bme in edges) / len(verts)
            for bme in edges:
                bmv0, bmv1 = bme.verts
                vec = bme_vector(bme)
                edge_len = vec.length
                edge_diff = (avg_face_edge_len - edge_len)
                if abs(edge_diff) < 1e-12: continue
                edge_midpoint = bme_midpoint(bme)
                f = vec.normalized() * (edge_diff / avg_face_edge_len) * avg_vert_area_sqrt
                add_force(bmv0, f * -0.5, edge_midpoint, edge_diff, 40)
                add_force(bmv1, f * 0.5, edge_midpoint, edge_diff, 40)

        def average_face_angles(bmf, avg_vert_area_sqrt, face_topology_cache):
            ''' push verts toward equal spread '''
            if bmf in face_topology_cache:
                verts, edges = face_topology_cache[bmf]
            else:
                verts = tuple(bmv for bmv in bmf.verts)
                face_topology_cache[bmf] = (verts, tuple(bme for bme in bmf.edges))
            bmf_z = bmf.normal.normalized()
            if abs(bmf_z.dot(self.forward)) < 0.95:
                bmf_y = bmf_z.cross(self.forward).normalized()
                bmf_x = bmf_y.cross(bmf_z).normalized()
            else:
                bmf_x = self.up.cross(bmf_z).normalized()
                bmf_y = bmf_z.cross(bmf_x).normalized()
            vert_count = len(verts)
            sum_of_interior_angles = math.pi * (vert_count - 2)
            angle_target = sum_of_interior_angles / vert_count
            for i1 in range(vert_count):
                i0 = (i1 + vert_count - 1) % vert_count
                i2 = (i1 + 1) % vert_count
                bmv0, bmv1, bmv2 = verts[i0], verts[i1], verts[i2]
                v10, v12 = bmv0.co - bmv1.co, bmv2.co - bmv1.co
                d10, d12 = v10.normalized(), v12.normalized()
                d10_2 = Vector((bmf_x.dot(d10), bmf_y.dot(d10))).normalized()
                d12_2 = Vector((bmf_x.dot(d12), bmf_y.dot(d12))).normalized()
                try:
                    angle = d10_2.angle_signed(d12_2)
                    angle_diff = angle_target - angle
                    mag = angle_diff * avg_vert_area_sqrt / vert_count
                    add_force(bmv0, d10.cross(bmf_z).normalized() * -mag, bmv0.co, angle_diff, 40)
                    add_force(bmv2, d12.cross(bmf_z).normalized() * mag, bmv1.co, angle_diff, 40)
                except Exception:
                    # Exception is thrown if d10_2 or d12_2 are 0-length
                    pass

        def average_face_areas(bmf, avg_vert_area, center, face_topology_cache):
            ''' scale faces towards the average '''
            if bmf in face_topology_cache:
                verts, edges = face_topology_cache[bmf]
            else:
                verts = tuple(bmv for bmv in bmf.verts)
                edges = tuple(bme for bme in bmf.edges)
                face_topology_cache[bmf] = (verts, edges)
            if avg_vert_area < 1e-20: return
            diff = ((bmf.calc_area() / len(verts)) - avg_vert_area) / avg_vert_area
            for bmv in verts:
                if bmv.is_boundary and len(bmv.link_edges) == 3:
                    other_boundary_verts = [e.other_vert(bmv) for e in bmv.link_edges if e.is_boundary and e in edges]
                    if other_boundary_verts:
                        center = Point.average([bmv.co, other_boundary_verts[0].co])
                vec = (center - bmv.co) * diff * 0.25
                add_force(bmv, vec, center, 1, 40)

        def average_face_shape(bmf, avg_vert_area_sqrt, center, face_topology_cache):
            ''' push verts toward their target positions on a regular polygon '''
            if bmf in face_topology_cache:
                verts, edges = face_topology_cache[bmf]
            else:
                verts = tuple(bmv for bmv in bmf.verts)
                face_topology_cache[bmf] = (verts, tuple(bme for bme in bmf.edges))
            vert_count = len(verts)
            bmf_z = bmf.normal.normalized()
            ref = Vector((0, 0, 1)) if abs(bmf_z.z) < 0.9 else Vector((1, 0, 0))
            bmf_x = ref.cross(bmf_z).normalized()
            bmf_y = bmf_z.cross(bmf_x)
            if vert_count == 3:
                cos_s, sin_s = -0.5, 0.8660254037844387 # 2π/3, avoids trig for common cases
            elif vert_count == 4:
                cos_s, sin_s = 0.0, 1.0 # π/2
            elif vert_count == 5:
                cos_s, sin_s = 0.30901699437494742, 0.9510565162951535 # 2π/5
            else:
                spacing = 2 * math.pi / vert_count
                cos_s, sin_s = math.cos(spacing), math.sin(spacing)
            rels = []
            avg_radius = 0.0
            sum_z = complex(0.0, 0.0)
            conj_k = complex(1.0, 0.0)
            conj_step = complex(cos_s, -sin_s)
            for bmv in verts:
                rel = bmv.co - center
                rels.append(rel)
                avg_radius += rel.length
                x2d, y2d = bmf_x.dot(rel), bmf_y.dot(rel)
                r2d = math.sqrt(x2d * x2d + y2d * y2d)
                if r2d > 1e-8:
                    sum_z += complex(x2d / r2d, y2d / r2d) * conj_k
                conj_k *= conj_step
            avg_radius /= vert_count
            if avg_radius < 1e-8: return
            phase = math.atan2(sum_z.imag, sum_z.real)
            scale = avg_vert_area_sqrt / avg_radius
            bmf_x_s = bmf_x * avg_vert_area_sqrt
            bmf_y_s = bmf_y * avg_vert_area_sqrt
            current  = complex(math.cos(phase), math.sin(phase))
            step = complex(cos_s, sin_s)
            for bmv, rel in zip(verts, rels):
                f = current.real * bmf_x_s + current.imag * bmf_y_s - rel * scale
                add_force(bmv, f, center, 1, 40)
                current *= step

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
                    add_force(bmv0, vec * 5, bmf_midpoint(bmf), 1, 40)
                    add_force(bmv1, vec * 5, bmf_midpoint(bmf), 1, 40)

        def collect_verts_near_source_edge() -> set:
            result = set()
            if not self.source_edge_accel:
                return result
            for bmv in chk_verts:
                bmv_world = point_to_bvec3((M @ Vector((*bmv.co, 1.0))).xyz)
                if closest_v := self.source_edge_accel.closest_point(bmv_world):
                    if bmv.link_edges:
                        diff   = Mi @ Vector(closest_v) - bmv.co
                        dist   = diff.length
                        avg_len = sum(bme_length(bme) for bme in bmv.link_edges) / len(bmv.link_edges)
                        if dist <= avg_len * self.source_sharp_proximity:
                            # Only include verts with normals pointing towards the edge
                            if dist < 1e-8 or (diff / dist).dot(bmv.normal) > 0.3:
                                result.add(bmv)
            return result

        def collect_loop_neighbors(
            source_verts: set,
            multiplier: float,
            *,
            check_alignment: bool = False,
        ) -> set:
            result = set()
            for bmv in source_verts:
                # Reuse straighten loopse cache if possible
                loops = self.straighten_loops_cache.get(bmv) or get_bmv_loop_pairs(bmv)
                if not loops:
                    continue
                for (start_pt, end_pt) in loops:
                    for v in (start_pt, end_pt):
                        if v in source_verts or not v.link_edges:
                            continue
                        avg_len = sum(bme_length(bme) for bme in v.link_edges) / len(v.link_edges)
                        dist_threshold = avg_len * self.source_sharp_proximity * multiplier
                        closest_p = self.source_edge_accel.closest_point_in_threshold(v.co, M, Mi, dist_threshold)
                        if closest_p:
                            diff = closest_p - v.co
                            dist = diff.length
                            if not check_alignment or dist < 1e-8 or (diff / dist).dot(v.normal) > 0.3:
                                result.add(v)
            return result

        def relax_3d():
            if self.source_edge_accel:
                self.verts_near_source_edge = collect_verts_near_source_edge()

            if self.verts_near_source_edge:
                # Encourage the same loop to follow source edge when snapping by expanding its snap radius
                expanded = collect_loop_neighbors(self.verts_near_source_edge, 2.0, check_alignment=True)
                self.verts_near_source_edge.update(expanded)

                # Propogate chosen loop along source edge when snapping to it
                self.elected_loop_verts.update(self.verts_near_source_edge)
                elected_verts = collect_loop_neighbors(self.elected_loop_verts, 2.0)
                self.elected_loop_verts.update(elected_verts)

                # Kick out elected verts if they drifted too far from the source edge
                evict = set()
                for bmv in self.elected_loop_verts & chk_verts:
                    if bmv in self.verts_near_source_edge:
                        continue
                    avg_len = sum(bme_length(bme) for bme in bmv.link_edges) / len(bmv.link_edges)
                    dist_threshold = avg_len * self.source_sharp_proximity * 3.0
                    closest_p = self.source_edge_accel.closest_point_in_threshold(bmv.co, M, Mi, dist_threshold)
                    if not closest_p:
                        evict.add(bmv)
                self.elected_loop_verts -= evict

            reset_forces()
            if relax.algorithm_straighten_edges or relax.algorithm_laplacian:
                for bmv in verts & chk_verts:
                    if relax.algorithm_laplacian: laplacian_smooth(bmv, self.laplacian_cache)
                    if relax.algorithm_straighten_edges:
                        straighten_loops(bmv, self.straighten_loops_cache)
                        if self.straighten_loops_cache.get(bmv) is None:
                            # handles poles, boundaries, and other topology
                            straighten_edges(bmv, self.straighten_cache)
            if relax.algorithm_average_edge_lengths:
                avg_edge_len = sum(bme_length(bme) for bme in edges) / len(edges)
                for bme in edges:
                    average_edge_length(bme, avg_edge_len)
            if relax.algorithm_equalize_faces:
                avg_vert_area = sum(bmf.calc_area() / len(bmf.verts) for bmf in faces) / len(faces)
                avg_vert_area_sqrt = math.sqrt(avg_vert_area)
                for bmf in faces:
                    face_center = bmf_midpoint(bmf)
                    average_face_areas(bmf, avg_vert_area, face_center, self.face_topology_cache)
                    average_face_shape(bmf, avg_vert_area_sqrt, face_center, self.face_topology_cache)
            if relax.algorithm_correct_flipped_faces: correct_flipped_faces()

            if self.source_edge_accel and self.elected_loop_verts:
                # Nudge the elected loop towards the source edge and other loops away
                detect_factor = 1.5  # zone in which to apply forces
                election_strength = 0.15
                for bmv in verts:
                    if not bmv.link_edges:
                        continue
                    avg_len = sum(bme_length(bme) for bme in bmv.link_edges) / len(bmv.link_edges)
                    dist_threshold = avg_len * self.source_sharp_proximity * detect_factor
                    closest_p = self.source_edge_accel.closest_point_in_threshold(bmv.co, M, Mi, dist_threshold)
                    if not closest_p:
                        continue
                    to_edge = closest_p - bmv.co
                    dist    = to_edge.length
                    if dist < 1e-8 or (to_edge / dist).dot(bmv.normal) <= 0.3:
                        continue  # Skip when not aligned
                    if bmv in self.elected_loop_verts:
                        add_force(bmv, to_edge * election_strength)
                    elif bmv not in self.verts_near_source_edge:
                        add_force(bmv, to_edge * election_strength * -1)

            if self.verts_near_source_edge:
                # Edge constrained verts can skip forces and not be in displace
                # Adding a zero vector makes sure they're still processed
                for bmv in verts:
                    if bmv in self.verts_near_source_edge and bmv not in displace:
                        displace[bmv] = Vector((0.0, 0.0, 0.0))

        # perform smoothing
        strength_base = 20.0 * self.scale_avg * brush.strength / time_delta * self.pressure
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
        for _i_step in range(steps):
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
                displace_vec : Vector = displace[bmv].normalized() * displace_dist

                co : Vector = bmv.co + displace_vec

                if opt_draw_net:
                    self.draw_vectors_net.append((bmv.co, displace_vec * 100))

                if self.mask_opt('boundary') == 'SLIDE' and bmv in self.boundary_verts and self.boundary_accel:
                    if p := self.boundary_accel.closest_point(co):
                        co = p
                if self.mask_opt('seams') == 'SLIDE' and bmv in self.seam_verts and self.seam_accel:
                    if p := self.seam_accel.closest_point(co):
                        co = p
                if self.mask_opt('creases') == 'SLIDE' and bmv in self.crease_verts and self.crease_accel:
                    if p := self.crease_accel.closest_point(co):
                        co = p
                if self.mask_opt('sharps') == 'SLIDE' and bmv in self.sharp_verts and self.sharp_accel:
                    if p := self.sharp_accel.closest_point(co):
                        co = p

                co_world = M @ Vector((*co.xyz, 1.0))

                # Edge snap: only for verts_near_source_edge vertices (proximity + alignment).
                # Stickiness [0, 1] controls how hard the vertex clings to the edge:
                # Stickiness [0, 1]: controls escape from the source edge.
                #   0   → snap skipped entirely; vertex drifts freely off any edge.
                #   0.5 → escapes when the perpendicular-to-edge force exceeds the
                #         baseline (~half-edge-length displacement from equilibrium).
                #   1   → never escapes regardless of force.
                #
                # Only the PERPENDICULAR component of the force is compared against
                # the threshold — the along-edge component (Laplacian redistribution)
                # is invisible to the escape check so sliding always works freely.
                # Gated on stickiness > 0; snap_avg_edge_len stays 0 so the
                # downstream corner/edge snap block is also skipped at stickiness=0.
                apply_edge_snap = False
                snap_avg_edge_len = 0.0
                if self.source_edge_accel and bmv.link_edges and self.stickiness > 0.0:
                    snap_avg_edge_len = sum(bme_length(bme) for bme in bmv.link_edges) / len(bmv.link_edges)
                    if bmv in self.verts_near_source_edge:
                        if self.stickiness >= 1.0:
                            apply_edge_snap = True
                        else:
                            # Threshold scales with the hyperbola s/(1−s) so that
                            # stickiness=0.5 matches the baseline escape force.
                            escape_threshold = snap_avg_edge_len * 0.005 * self.stickiness / (1.0 - self.stickiness)
                            # Strip the along-edge component; compare only what's
                            # trying to pull the vertex off the edge perpendicularly.
                            perp = displace[bmv]
                            edge_nbrs = [bme.other_vert(bmv) for bme in bmv.link_edges
                                         if bme.other_vert(bmv) in self.verts_near_source_edge]
                            if len(edge_nbrs) >= 2:
                                ev = edge_nbrs[-1].co - edge_nbrs[0].co
                                if ev.length > 1e-8:
                                    ed = ev.normalized()
                                    perp = perp - ed * perp.dot(ed)
                            elif len(edge_nbrs) == 1:
                                ev = edge_nbrs[0].co - bmv.co
                                if ev.length > 1e-8:
                                    ed = ev.normalized()
                                    perp = perp - ed * perp.dot(ed)
                            apply_edge_snap = perp.length <= escape_threshold

                # Project onto the source surface. When the vertex was displaced into
                # the mesh, cast a ray along its normal — it exits through the near
                # face correctly. When it hasn't moved (on-surface or equilibrium), use
                # nearest-point instead: a raycast from exactly on a face is unreliable
                # (+normal misses, −normal hits the far face) and risks overhang snapping.
                co_world_snapped = None
                if self.source_edge_accel and displace_vec.length > 1e-6:
                    co_pt        = point_to_bvec3(co_world.xyz)
                    normal_world = (M.to_3x3() @ bmv.normal).normalized()
                    for obj in iter_all_valid_sources(context):
                        M_obj  = obj.matrix_world
                        Mi_obj = M_obj.inverted_safe()
                        ray_o  = (Mi_obj @ Vector((*co_pt, 1.0))).xyz
                        ray_d  = (Mi_obj.to_3x3() @ normal_world).normalized()
                        result, co_hit, _, _ = obj.ray_cast(ray_o, ray_d)
                        if result:
                            co_world_snapped = point_to_bvec3((M_obj @ Vector((*co_hit, 1.0))).xyz)
                            break
                if not co_world_snapped:
                    co_world_snapped = nearest_point_valid_sources(context, point_to_bvec3(co_world.xyz), world=True)

                if not co_world_snapped: continue
                co_local_snapped : Vector = (Mi @ co_world_snapped) if co_world_snapped else co

                if bmv in self.verts_near_source_edge and snap_avg_edge_len > 0:
                    threshold        = snap_avg_edge_len * self.scale_avg * self.source_sharp_proximity
                    corner_threshold = threshold * getattr(relax, 'algorithm_source_corner_proximity', 2.0)

                    # Corner snap: always applied for true edge vertices regardless of
                    # whether the escape fired. Correct corners must stay at their
                    # corner position even when the escape threshold is lowered.
                    snapped_to_corner = False
                    if corner_result := self.source_edge_accel.find_corner(co_world_snapped):
                        co_corner, _, dist_corner = corner_result
                        if dist_corner < corner_threshold:
                            co_local_snapped  = Mi @ Vector(co_corner)
                            snapped_to_corner = True

                    # Edge proximity snap: only when not escaped and not at a corner.
                    if apply_edge_snap and not snapped_to_corner:
                        if p := self.source_edge_accel.closest_point(co_world_snapped):
                            if (Vector(p) - Vector(co_world_snapped)).length <= threshold:
                                co_local_snapped = Mi @ Vector(p)

                elif self.source_edge_accel and bmv.link_edges and snap_avg_edge_len > 0:
                    # Approaching vertex (alignment check failed, not yet in
                    # verts_near_source_edge): snap to the edge once nearest-point lands
                    # within the threshold, but only if the displacement is directed
                    # toward the edge. Bevel vertices at rest have displacement away
                    # from or perpendicular to the edge (dot product ≤ 0).
                    threshold = snap_avg_edge_len * self.scale_avg * self.source_sharp_proximity
                    if p := self.source_edge_accel.closest_point(co_world_snapped):
                        p_vec     = Vector(p)
                        to_edge_w = p_vec - Vector(co_world_snapped)
                        if to_edge_w.length <= threshold:
                            disp_world = M.to_3x3() @ displace_vec
                            if to_edge_w.length < 1e-8 or disp_world.dot(to_edge_w) > 0:
                                co_local_snapped = Mi @ p_vec

                if self.mirror:
                    co_orig = bmv.co
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
                        co_world_snapped = nearest_point_valid_sources(context, point_to_bvec3(co_world), world=True)
                        if not co_world_snapped: continue
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

        if debug_print:
            print(f'elapsed: {time.time() - self._time:0.3f}s {1.0/time_delta:0.1f}fps v:{len(verts)} e:{len(edges)} f:{len(faces)}')


    def draw(self, context:Context):
        if not self.draw_vectors_positive and not self.draw_vectors_negative and not self.draw_vectors_net:
            return

        M = self.matrix_world
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
