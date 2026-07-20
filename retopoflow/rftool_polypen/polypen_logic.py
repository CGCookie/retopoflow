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
import bpy
from bpy.types import Context, Event, Mesh
from bmesh.types import BMVert, BMEdge, BMFace, BMesh, BMLayerItem
from bmesh.ops import connect_verts
from bmesh.utils import edge_split
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_line_2d

from collections import deque
from collections.abc import Iterable, Iterator
from enum import auto
from typing import Callable, cast
import time

from ..preferences import RF_Prefs

from ..common.bmesh import (
    bmvs_share_bmf, bmf_opposite_bmelem,
    bme_other_bmv, bme_other_bmf, bme_midpoint, bme_cos, bme_length,
    bmes_share_bmv, bmes_shared_bmv,
    bmf_midpoint, bmf_opposite_bme, bmf_is_quad, bmf_is_pentagon, bmf_radius_squared,
    bmf_is_tri,
    get_bmesh_emesh, get_bmv_avg_edge_len,
    clean_select_layers,
    NearestBMVert, NearestBMEdge, NearestBMFace,
    has_mirror_x, has_mirror_y, has_mirror_z, mirror_threshold,
)
from ..common.accel import SourceCache
from ..common.bmesh_maths import is_bmvert_hidden
from ..common.enums import ValueIntEnum
from ..common.raycast import (
    nearest_point_valid_sources,
    raycast_valid_sources,
    raycast_point_valid_sources,
    mouse_from_event,
    vec_forward,
)
from ..common.maths import (
    direction_to_bvec4,
    view_forward_direction,
    distance2d_point_bmvert,
    distance2d_point_bmedge,
    clamp, xform_direction,
    perpendicular_direction2,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bmesh_ops import BMElemType, BMElem
from ...addon_common.common.maths import intersection2d_line_line, sign_threshold, point_inside_face, points_of_bmface, point_inside_face_2d
from ...addon_common.common.colors import Color4
from ...addon_common.common.utils import iter_pairs


from ..common.drawing import (
    Drawing,
    CC_2D_POINTS,
    CC_2D_LINES,
    CC_2D_TRIANGLES,
)



class PP_Action(ValueIntEnum):
    NONE           = auto()  # do not do anything (could not determine what to do)

    VERT           = auto()  # create new vert (no extrusion)
    VERT_EDGE      = auto()  # create edge from selected vert to new vert under mouse

    EDGE_TRI       = auto()  # create triangle from selected edge and new/hovered vert
    EDGE_QUAD      = auto()  # create new edge and bridge with selected to create quad

    TRI_QUAD       = auto()  # create vert into edge of triangle to turn into quad (not hovering edge of tri)

    EDGE_BRIDGE    = auto()  # create quad by bridging selected and hovered edges

    SPLIT_EDGE           = auto()   # split hovered edge
    EDGE_SPLIT_EDGE      = auto()   # split selected edge and create edge from new edge-vert to new vert under mouse
    SPLIT_QUAD           = auto()   # split hovered and selected edges and split quad
    SPLIT_QUAD_CENTER    = auto()   # split hovered, selected edges, and quad (preserves quadness, insert junction)
    SPLIT_QUAD_EDGES     = auto()   # split edges of quad
    VERT_SPLIT_EDGE      = auto()   # split hovered edge and create edge from nearest selected vert to new vert
    WIRE_SPLIT_EDGE_FACE = auto()   # split hovered edge, create edge to selected vert, split face
    WIRE_VERT_SPLIT_FACE = auto()   # connect selected and nearest hovered verts and split face


# States that place a new vert freely on the source surface at the mouse position.
# Only these get snapped to nearby source features -- the knife/split states keep the
# new vert constrained to the mesh edge being cut, so feature snapping must not touch them.
PP_FEATURE_SNAP_STATES = frozenset({
    PP_Action.VERT,
    PP_Action.VERT_EDGE,
    PP_Action.EDGE_TRI,
    PP_Action.EDGE_QUAD,
    PP_Action.TRI_QUAD,
})


def get_wire(bmv : BMVert) -> list[BMVert|BMEdge]|None:
    """
    Returns wire starting at given BMVert as a list alternating between BMVert and BMEdge,
    starting with BMVert at end of wire, and ending with given BMVert.
    """
    if not bmv.is_wire: return None
    bmv_pre = bmv
    wire : list[BMVert|BMEdge] = [ bmv ]
    seen : set[BMEdge] = set()
    while wire[-1].is_wire:
        bmes : list[BMEdge] = list(set(bmv_pre.link_edges) - seen)
        if len(bmes) != 1:
            return None
        bme = bmes[0]
        seen.add(bme)
        bmv_next = bme_other_bmv(bme, bmv_pre)
        if not bmv_next:
            break
        wire += [bme, bmv_next]
        bmv_pre = bmv_next
    wire.reverse()
    return wire

def get_wire_split_face(bmv : BMVert) -> tuple[list[BMVert|BMEdge], BMFace] | None:
    wire = get_wire(bmv)
    if not wire: return None
    # find which face has bmv in it
    co = bmv.co
    for bmf in wire[0].link_faces:
        if point_inside_face(co, points_of_bmface(bmf)):
            return (wire, bmf)
    return None

def check_split_face(bmv_selected : BMVert, bmelem_hovered : BMVert | BMEdge) -> tuple[list[BMVert|BMEdge], BMFace] | None:
    wire = get_wire(bmv_selected)
    if not wire: return None
    bmfs = list(set(bmelem_hovered.link_faces) & set(wire[0].link_faces))
    if len(bmfs) == 1:
        return (wire, bmfs[0])
    if len(bmfs) == 2:
        # looping back to adjacent edge, so figure out which bmf we need to split
        bmf0_co, bmf1_co = map(bmf_midpoint, bmfs)
        wire_bmv : BMVert = wire[2]
        if (wire_bmv.co - bmf0_co).length < (wire_bmv.co - bmf1_co).length:
            return (wire, bmfs[0])
        else:
            return (wire, bmfs[1])
    return None

def find_opposite_and_corner(bme0 : BMEdge, bme1 : BMEdge) -> tuple[BMVert, BMVert] | tuple[None, None]:
    bmfs = set(bme0.link_faces) & set(bme1.link_faces)
    if len(bmfs) != 1: return (None, None)
    bmf = next(iter(bmfs))
    bmvs = set(bme0.verts) | set(bme1.verts)
    bmvo = next(bmv for bmv in bmf.verts if bmv not in bmvs)
    bmvc = bmes_shared_bmv(bme0, bme1)
    if not bmvc: return (None, None)
    return (bmvo, bmvc)

def find_opposite_and_center_wire(bmv_selected : BMVert, bme_hovered : BMEdge) -> tuple[BMVert|None, BMVert|None]:
    res = check_split_face(bmv_selected, bme_hovered)
    if not res: return (None, None)                     # not splitting a face
    wire, bmf = res
    if len(wire) != 3: return (None, None)              # only handling wire with one extra vert (center)
    if len(bmf.verts) != 5: return (None, None)         # only handling quad with one extra vert
    wire_first_bmv, wire_last_bmv, = wire[0], wire[-1]
    assert type(wire_first_bmv) is BMVert, f'Unexpected type {type(wire_first_bmv)} ({wire_first_bmv})'
    assert type(wire_last_bmv) is BMVert, f'Unexpected type {type(wire_last_bmv)} ({wire_last_bmv})'
    bmes_adj : set[BMEdge] = set(wire_first_bmv.link_edges)
    if bme_hovered in bmes_adj: return (None, None)     # cannot loop back on adjacent edge
    bme_opposite = next(
        (
            bme for bme in bmf.edges
            if not any(
                bmes_share_bmv(bme, bme_adj) for bme_adj in bmes_adj
            )
        ),
        None
    )
    if not bme_opposite: return (None, None)                # could not find oppositev edge
    if bme_hovered == bme_opposite: return (None, None)     # cannot hover opposite edge
    bmv_shared = bmes_shared_bmv(bme_hovered, bme_opposite)
    if not bmv_shared: return (None, None)                  # no BMVert in common
    bmv_opposite = bme_other_bmv(bme_opposite, bmv_shared)
    return (bmv_opposite, wire_last_bmv)

def find_crossed_edge(context: Context, matrix_world : Matrix, pt0 : Vector, pt1 : Vector, bmedges : Iterable[BMEdge]) -> tuple[BMEdge, Vector] | None:
    rgn, r3d = context.region, context.region_data
    for bme in bmedges:
        bmv0, bmv1 = bme.verts
        ptv0 = location_3d_to_region_2d(rgn, r3d, matrix_world @ bmv0.co)
        ptv1 = location_3d_to_region_2d(rgn, r3d, matrix_world @ bmv1.co)
        if not ptv0 or not ptv1: continue
        pt = intersect_line_line_2d(pt0, pt1, ptv0, ptv1)
        if not pt: continue
        return (bme, pt)
    return None

def find_bmedges_to_split(context : Context, matrix_world : Matrix, bmelem_start : BMVert|BMEdge, p0 : Vector, p1 : Vector, normal : Vector|None) -> list[tuple[BMEdge, Vector]]:
    found : list[tuple[BMEdge, Vector]] = []
    touched : set[BMEdge|BMVert] = set()
    bmfs_search : deque[BMFace] = deque()

    if type(bmelem_start) is BMVert:
        bmv = bmelem_start
        seen : set[BMVert] = set()
        while bmv.is_wire and bmv not in seen:
            seen.add(bmv)
            bmvn = next((bme_other_bmv(bme, bmv) for bme in bmv.link_edges), None)
            if bmvn is None: break
            bmv = bmvn
        bmfs_search.extend(bmv.link_faces)
        touched.update(bmelem_start.link_edges)
    elif type(bmelem_start) is BMEdge:
        bmfs_search.extend(bmelem_start.link_faces)
        touched.add(bmelem_start)
        found.append((bmelem_start, p0))
    else:
        assert False, f'Unhandled type {type(bmelem_start)} ({bmelem_start})'

    # print(f'{bmelem_start=} {bmfs_search=} {touched=}')
    while bmfs_search:
        bmf : BMFace = bmfs_search.popleft()
        if normal and normal.dot(bmf.normal) > 0:
            continue
        bmes = set(bmf.edges) - touched
        res = find_crossed_edge(context, matrix_world, p0, p1, bmes)
        if not res: continue
        bme, pt = res
        touched.update(bmes) # .add(bme)
        found.append((bme, pt))
        bmf_other = bme_other_bmf(bme, bmf)
        if bmf_other:
            bmfs_search.append(bmf_other)

    return found

def compute_quad_factor(co : Vector, a : Vector, b : Vector, c : Vector, d : Vector) -> tuple[float, float]:
    '''
    find factors u,v where e=a+(b-a)*u, f=d+(c-d)*u, co=e+(f-e)*v.
    for now, solving iteratively, but really should see if we can solve numerically!

      0  u>    1
    1 d--f-----c 1
      |  |     |
    v̂ |  o co  | v̂
      |  | /   |
    0 a--e-----b 0
      0  u>    1
    '''

    # iteratively find u
    ITERATIONS = 100
    u_min, u, u_max = 0, 0.5, 1
    ab = b - a
    for _ in range(ITERATIONS):
        e, f = a + u * (b - a), d + u * (c - d)
        ef, eco = (f - e).normalized(), (co - e).normalized()
        if ab.dot(ef) < ab.dot(eco):
            u_min = u
        else:
            u_max = u
        u = u_min + (u_max - u_min) * 0.5
    e, f = a + u * (b - a), d + u * (c - d)
    v = (co - e).length / (f - e).length
    return (u, v)


def PP_get_edge_quad_verts(context:Context, p0:Vector, p1:Vector, mouse:Vector|None, matrix_world:Matrix, parallel_stable:float, *, min_dist_ratio:float=1.1) -> tuple[Vector|None,Vector|None]:
    '''
    this function is used in quad-only mode to find positions of quad verts based on selected edge and mouse position
    a Desmos construction of how this works: https://www.desmos.com/geometry/5w40xowuig
    '''
    if not p0 or not p1 or not mouse: return (None, None)
    v01 = p1 - p0
    dist01 = v01.length
    d01 = v01 / dist01
    mid01 = p0 + v01 / 2
    mid23 = mouse
    between = mid23 - mid01
    if between.length < 0.0001: return (None, None)

    mid0123 = mid01 + between * clamp(parallel_stable, 0.01, 0.99)  # [0,1] larger => more parallel to original
    perp = Vector((-between.y, between.x))
    if perp.dot(v01) < 0: perp.negate()
    intersection = intersection2d_line_line(p0, p1, mid0123, mid0123 + perp)
    if not intersection: return (None, None)

    dist = d01.dot(intersection - mid01)
    if abs(dist) < dist01 * min_dist_ratio:
        dist = dist01 * min_dist_ratio * (1 if dist > 0 else -1)
        intersection = mid01 + d01 * dist

    toward = (mid23 - intersection).normalized()
    if toward.dot(perp) < 0: dist01 = -dist01

    # between_len = between.length * v01.normalized().dot(perp)

    for _tries in range(32):
        p2, p3 = mid23 + toward * (dist01 / 2), mid23 - toward * (dist01 / 2)
        hit2 = raycast_point_valid_sources(context, p2, respect_clip_planes=True)
        hit3 = raycast_point_valid_sources(context, p3, respect_clip_planes=True)
        if hit2 and hit3:
            Mi = matrix_world.inverted_safe()
            return (Mi @ hit2, Mi @ hit3)
        dist01 /= 2

    return (None, None)


def is_point_inside_bmface(project : Callable[[Vector|None], Vector|None], point3D : Vector, point2D : Vector, bmf : BMFace, radius_ratio : float) -> bool:
    """
    Check if given point is inside the givin BMFace.
    Note: because BMFaces need not be planar, we need to check in 2D and 3D.
    """
    pts = points_of_bmface(bmf)
    if not point_inside_face_2d(point2D, [ project(pt) for pt in pts ]):
        # point outside BMFace projected to screen
        return False

    # check if point is within BFace in 3D
    p = point_inside_face(point3D, pts, radius_ratio=radius_ratio)
    if not p:
        return False
    return True


def bme_is_interior(bme : BMEdge) -> bool:
    return len(bme.link_faces) >= 2

def bmv_is_interior(bmv : BMVert) -> bool:
    return not bmv.is_wire and not bmv.is_boundary


class PP_Logic:
    # see https://github.com/cgcookie/retopoflow/issues/1770
    ignore_splitting_backfaces : bool = True
    ignore_splitting_radius_ratio : float = 0.25

    matrix_world : Matrix
    matrix_world_inv : Matrix
    vec_forward : Vector

    bm : BMesh | None
    em : Mesh | None
    nearest : NearestBMVert | None
    nearest_bme : NearestBMEdge | None
    nearest_bmf : NearestBMFace | None
    selected : dict[BMElemType, set[BMVert]|set[BMEdge]|set[BMFace]] | None

    project : Callable[[Vector|None], Vector|None]

    state : PP_Action

    hit : Vector | None             # raycast mouse in local
    bmv : BMVert | None             # BMVert to extrude from / work with
    bme : BMEdge | None             # BMEdge to extrude from / work with
    bmf : BMFace | None             # BMFace to work with
    bme_hovered : BMEdge | None
    bme_hovered_bmvs : list[BMVert] | None
    bmv2 : BMVert | None            # EDGE_QUAD when extruding to BMVerts or hit locations
    bmv3 : BMVert | None            # ...
    hit2 : Vector | None            # ...
    hit3 : Vector | None            # ...

    update_bmesh_selection : bool
    mouse : Vector | None
    insert_mode : str | None
    quad_preserve : bool | None
    parallel_stable : float | None
    constrain_edge_vert : bool | None
    use_loop_cuts : bool | None

    layer_sel_vert : BMLayerItem    # pyright: ignore [reportMissingTypeArgument]
    layer_sel_edge : BMLayerItem    # pyright: ignore [reportMissingTypeArgument]
    layer_sel_face : BMLayerItem    # pyright: ignore [reportMissingTypeArgument]

    split_info : dict[str, ...] | None

    source_accel : object | None    # SourceAccel used for feature snapping (falsy when unavailable)
    feature_radius : float          # world-space radius within which a new vert snaps to a feature

    def __init__(self, context:Context, event:Event):
        assert context.edit_object, 'Expected to be running in edit mode'
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe()
        self.update_bmesh_selection = False
        self.mouse = None                   # pyright: ignore[reportAttributeAccessIssue]
        self.insert_mode = None
        self.quad_preserve = None
        self.parallel_stable = None
        self.constrain_edge_vert = None
        self.use_loop_cuts = None

        self.split_info = None

        self.reset()
        self.update(context, event, None, 1.00, True, False, True)

    def reset(self):
        self.bm = None
        self.em = None
        self.nearest = None
        self.nearest_bme = None
        self.nearest_bmf = None
        self.selected = None
        self.bmv = None
        self.bme = None
        self.bmf = None
        self.bme_hovered = None
        self.bme_hovered_bmvs = None
        self.bmv2 = None
        self.bmv3 = None
        self.hit2 = None                    # pyright: ignore[reportAttributeAccessIssue]
        self.hit3 = None                    # pyright: ignore[reportAttributeAccessIssue]
        self.hit = None                     # pyright: ignore[reportAttributeAccessIssue]
        self.source_accel = None
        self.feature_radius = 0.0

    def cleanup(self):
        if not self.bm or not self.bm.is_valid: return
        clean_select_layers(self.bm)

    def project_all(self, *pts : Vector) -> Iterable[Vector|None]:
        yield from map(self.project, pts)

    def snap_co_to_feature(self, co_local : Vector) -> Vector:
        ''' Snap a local space coordinate onto the nearest source feature if within feature_radius.
        Returns the (possibly unchanged) local coordinate. '''
        accel = self.source_accel
        if not accel or self.feature_radius <= 0:
            return co_local
        co_world = self.matrix_world @ co_local
        corner = accel.find_corner(co_world)
        if corner and corner[2] <= self.feature_radius:
            return self.matrix_world_inv @ Vector(corner[0])
        closest = accel.closest_point(co_world)
        if closest and (Vector(closest) - co_world).length <= self.feature_radius:
            return self.matrix_world_inv @ Vector(closest)
        return co_local

    def feature_ref_len(self) -> float:
        ''' Local space edge length used to scale the feature snap radius, taken from the
        geometry the new vert connects to so the proximity tracks the surrounding retopo density. '''
        match self.state:
            case PP_Action.EDGE_TRI | PP_Action.EDGE_QUAD | PP_Action.TRI_QUAD:
                if self.bme and self.bme.is_valid:
                    return bme_length(self.bme)
            case PP_Action.VERT_EDGE:
                if self.bmv and self.bmv.is_valid:
                    return get_bmv_avg_edge_len(self.bmv)
        # VERT (detached) and any fallback: scale off the nearest existing geometry to the cursor
        if self.nearest_bme and self.nearest_bme.bme:
            return bme_length(self.nearest_bme.bme)
        if self.nearest and self.nearest.bmv:
            return get_bmv_avg_edge_len(self.nearest.bmv)
        return 0.0

    def apply_feature_snap(self, context : Context):
        ''' Snap the free on-surface vert placements for the current state onto nearby source
        features, so both the preview and the commit land on sharp edges/corners. '''
        if self.state not in PP_FEATURE_SNAP_STATES: return
        self.source_accel = SourceCache.get(context)
        if not self.source_accel: return
        scale_avg = sum(self.matrix_world.to_scale()) / 3
        proximity = getattr(context.scene.retopoflow.snapping, 'source_edge_proximity', 0.25)
        self.feature_radius = self.feature_ref_len() * scale_avg * proximity
        if self.feature_radius <= 0: return

        if self.state == PP_Action.EDGE_QUAD:
            # the two far verts of the quad are the free placements (unless snapped to a vert)
            if self.hit2 is not None and self.bmv2 is None:
                self.hit2 = self.snap_co_to_feature(self.hit2)
            if self.hit3 is not None and self.bmv3 is None:
                self.hit3 = self.snap_co_to_feature(self.hit3)
        elif not (self.nearest and self.nearest.bmv) and self.hit is not None:
            self.hit = self.snap_co_to_feature(self.hit)

    def update(self, context:Context, event:Event, insert_mode:str|None, parallel_stable:float, quad_preserve:bool, constrain_edge_vert:bool, use_loop_cuts:bool):
        # update previsualization and commit data structures with mouse position
        # ex: if triangle is selected, determine which edge to split to make quad
        # print('UPDATE')

        M, rgn, r3d = self.matrix_world, context.region, context.region_data
        self.vec_forward = xform_direction(self.matrix_world_inv, view_forward_direction(context))
        self.project = lambda p: location_3d_to_region_2d(rgn, r3d, M @ p) if p else None

        self.insert_mode = insert_mode
        self.parallel_stable = parallel_stable
        self.quad_preserve = quad_preserve and self.insert_mode in ('TRI/QUAD', 'QUAD-ONLY')
        self.constrain_edge_vert = constrain_edge_vert
        self.use_loop_cuts = use_loop_cuts

        if not self.bm or not self.bm.is_valid:
            self.bm, self.em = get_bmesh_emesh(context)
            self.layer_sel_vert, self.layer_sel_edge, self.layer_sel_face = bmops.get_select_layers(self.bm)
            # print(type(self.layer_sel_vert), type(self.layer_sel_edge), type(self.layer_sel_face))
            self.selected = None
            self.nearest = None
            self.nearest_bme = None
            self.nearest_bmf = None

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

        if self.nearest is None or not self.nearest.is_valid:
            self.nearest = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv)
        if self.nearest_bme is None or not self.nearest_bme.is_valid:
            self.nearest_bme = NearestBMEdge(self.bm, self.matrix_world, self.matrix_world_inv)
        if self.nearest_bmf is None or not self.nearest_bmf.is_valid:
            self.nearest_bmf = NearestBMFace(self.bm, self.matrix_world, self.matrix_world_inv, ensure_lookup_tables=False)

        if self.selected is None:
            self.selected = bmops.get_all_selected(self.bm)

        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        # update commit data structure with mouse position
        self.state = PP_Action.NONE
        if hit := raycast_valid_sources(context, mouse_from_event(event), respect_clip_planes=True):
            self.hit = hit['co_local']  # pyright: ignore[reportAttributeAccessIssue]
        else:
            self.hit = None             # pyright: ignore[reportAttributeAccessIssue]

        if not self.hit: return

        self.nearest.update(
            context,
            self.hit,
            filter_fn=lambda bmv: not is_bmvert_hidden(context, bmv),
        )
        if self.nearest.bmv:
            self.hit = self.nearest.bmv.co

        self.nearest_bme.update(        # pyright: ignore [reportUnusedCallResult]
            context,
            self.hit,
            ignore_selected=False,
            filter_fn=lambda bme: not any(map(lambda bmv:is_bmvert_hidden(context, bmv), bme.verts)),
        )
        self.nearest_bmf.update(
            context,
            self.hit,
            filter_fn=lambda bmf: not any(map(lambda bmv:is_bmvert_hidden(context, bmv), bmf.verts)),
        )


        ###########################################################################################
        # determine state of polypen based on selected geo, hovered geo, and insert mode

        if insert_mode is None or insert_mode == 'VERT-ONLY':
            self.state = PP_Action.VERT
            return

        if len(self.selected[BMVert]) == 0:
            # inserting vertex
            if not self.nearest.bmv and self.nearest_bme.bme:
                self.state = PP_Action.SPLIT_EDGE
            else:
                self.state = PP_Action.VERT
            return

        if self.nearest_bme.bme and not self.nearest_bme.bme.hide:
            if self.bme and self.bme.is_valid and self.bme != self.nearest_bme.bme:
                bmfs = set(self.bme.link_faces) & set(self.nearest_bme.bme.link_faces)
                bmf = next(iter(bmfs), None)
                if bmf:
                    if self.quad_preserve and len(bmf.verts) == 4 and bmes_share_bmv(self.bme, self.nearest_bme.bme):
                        self.state = PP_Action.SPLIT_QUAD_CENTER
                    else:
                        self.state = PP_Action.SPLIT_QUAD
                    return
            if self.nearest_bme.bme.select:
                self.state = PP_Action.SPLIT_EDGE
                return
            if self.update_split_face_loop(context):
                return

        if len(self.selected[BMEdge]) == 0 or insert_mode == 'EDGE-ONLY':
            sel_bmvs : set[BMVert] = self.selected[BMVert]  # pyright: ignore[reportAssignmentType]
            self.bmv = min(
                sel_bmvs,
                key=lambda bmv:distance2d_point_bmvert(context, self.matrix_world, self.hit, bmv),
            )
            # an interior vert may only knife, otherwise it would overlap existing geometry.
            interior = bmv_is_interior(self.bmv)
            if self.nearest.bmv:
                if check_split_face(self.bmv, self.nearest.bmv) is not None:
                    self.state = PP_Action.WIRE_VERT_SPLIT_FACE
                elif interior:
                    self.state = PP_Action.NONE
                else:
                    self.state = PP_Action.VERT_EDGE  # TODO: VERT_BRIDGE???
            elif self.nearest_bme.bme:
                if check_split_face(self.bmv, self.nearest_bme.bme) is not None:
                    self.state = PP_Action.WIRE_SPLIT_EDGE_FACE
                elif any(bmv in self.nearest_bme.bme.verts for bmv in self.selected[BMVert]):
                    self.state = PP_Action.SPLIT_EDGE
                else:
                    self.state = PP_Action.VERT_SPLIT_EDGE
            elif self.update_split_face_loop(context):
                return
            elif interior:
                self.state = PP_Action.NONE
            else:
                self.state = PP_Action.VERT_EDGE
            # find closest selected BMVert from which to extrude
            return

        if insert_mode in {'TRI/QUAD', 'QUAD-ONLY'} and self.nearest_bme.bme and not self.nearest.bmv:
            # find hovered bme but make sure it doesn't share a face with selected bme
            sel_bmes : set[BMEdge] = self.selected[BMEdge]  # pyright: ignore[reportAssignmentType, reportRedeclaration]
            sel_bme : BMEdge = min(
                sel_bmes,
                key=lambda bme:distance2d_point_bmedge(context, self.matrix_world, self.hit, bme),
            )
            sel_bmf = next((bmf for bmf in sel_bme.link_faces if bmf.select), None)
            if insert_mode == 'QUAD-ONLY' or (not sel_bmf or len(sel_bmf.verts) != 3):
                hov_bme = self.nearest_bme.bme
                if not any(hov_bme in bmf.edges for bmf in sel_bme.link_faces):
                    # (nearest) selected edge and hovered edge do not share a face

                    self.bme = sel_bme
                    self.bme_hovered = hov_bme

                    bmv0, bmv1 = self.bme.verts
                    bmv2, bmv3 = self.bme_hovered.verts
                    p0, p1, p2, p3 = self.project_all(bmv0.co, bmv1.co, bmv2.co, bmv3.co)

                    if not (p0 and p1 and p2 and p3):
                        # verts do not project to screen
                        # should happen very rarely
                        # interior edges may only knife, never bridge
                        # TODO: need to check if hovered BMEdge is boundary??
                        self.state = PP_Action.NONE if bme_is_interior(self.bme) else PP_Action.EDGE_BRIDGE
                        return

                    # ensure vert order makes a nice looking quad, either CW or CCW
                    #   0 ---- 1      1 ---- 0
                    #   |      |  or  |      |
                    #   3 ---- 2      2 ---- 3
                    v01 = (p1 - p0)
                    dotdir = v01.dot(p2 - p0) - v01.dot(p3 - p0)
                    if dotdir < 0:
                        p2, p3 = p3, p2
                        bmv2, bmv3 = bmv3, bmv2
                    # but swap verts if line segments are crossing
                    if intersect_line_line_2d(p0, p3, p1, p2):
                        p2, p3 = p3, p2
                        bmv2, bmv3 = bmv3, bmv2

                    if bmv2 in sel_bme.verts or bmv3 in sel_bme.verts:
                        # hovered edge shares vert with selected edge!  (issue #1443)
                        # treat this as though the artist is hovering the other vert
                        # interior edges may only knife, never create a triangle
                        self.state = PP_Action.NONE if bme_is_interior(sel_bme) else PP_Action.EDGE_TRI
                        return

                    if self.bme.is_boundary and self.bme_hovered.is_boundary:
                        # selected and hovered BMEdges are boundary, so let's assume artist wishes to bridge
                        self.state = PP_Action.EDGE_BRIDGE
                        self.bme_hovered_bmvs = [bmv2, bmv3]
                        return

                    # find where mouse is on hovered edge, then find proportional point on selected edge
                    # if line between these points cuts a face, then we knife
                    # otherwise, we bridge edges

                    pt1 = self.project(self.hit)  # self.mouse could be None??
                    if pt1:
                        w = (p3 - p2).normalized().dot(pt1 - p2) / (p3 - p2).length
                        pt0 = p0 + (p1 - p0) * w
                        splits = find_bmedges_to_split(context, self.matrix_world, self.bme, pt0, pt1, self.vec_forward if self.ignore_splitting_backfaces else None)
                        # print(f'{w=:0.2f} {len(splits)=}')
                        # print(f'  {p0} {pt0} {p1}')
                        # print(f'  {p3} {pt1} {p2}')
                        if len(splits) > 1:
                            self.state = PP_Action.SPLIT_QUAD
                            return


        if insert_mode == 'QUAD-ONLY':
            sel_bmes : set[BMEdge] = self.selected[BMEdge]  # pyright: ignore[reportAssignmentType, reportRedeclaration]
            sel_bme = min(
                sel_bmes,
                key=(lambda bme:distance2d_point_bmedge(context, self.matrix_world, self.hit, bme)),
            )
            if bme_is_interior(sel_bme):
                # interior edge may only knife, never extrude a quad
                self.state = PP_Action.NONE
                return
            bmv0, bmv1 = sel_bme.verts
            p0, p1 = self.project_all(bmv0.co, bmv1.co)
            if p0 and p1:
                hit2, hit3 = PP_get_edge_quad_verts(context, p0, p1, self.mouse, self.matrix_world, self.parallel_stable)
                if not hit2 or not hit3: return
                p2, p3 = self.project_all(hit2, hit3)
                if not (p0 and p1 and p2 and p3): return

                # ensure verts order makes a nice looking quad
                v01 = (p1 - p0)
                dotdir = v01.dot(p2 - p0) - v01.dot(p3 - p0)
                if dotdir < 0:
                    p2, p3 = p3, p2
                    hit2, hit3 = hit3, hit2
                # but swap verts if line segments are crossing
                if intersect_line_line_2d(p0, p3, p1, p2):
                    p2, p3 = p3, p2
                    hit2, hit3 = hit3, hit2

                self.bmv2 = None
                self.bmv3 = None
                self.nearest.update(context, hit2)
                if self.nearest.bmv:
                    self.bmv2 = self.nearest.bmv
                    hit2 = self.nearest.bmv.co
                self.nearest.update(context, hit3)
                if self.nearest.bmv:
                    self.bmv3 = self.nearest.bmv
                    hit3 = self.nearest.bmv.co
                self.nearest.bmv = None

                self.state = PP_Action.EDGE_QUAD
                self.bme = sel_bme
                self.hit2 = hit2
                self.hit3 = hit3
                return

        if insert_mode == 'TRI/QUAD' and len(self.selected[BMFace]) == 1:
            sel_bmfs : set[BMFace] = self.selected[BMFace]  # pyright: ignore[reportAssignmentType]
            self.bmf = next(iter(sel_bmfs), None)
            if self.bmf and bmf_is_tri(self.bmf):
                self.state = PP_Action.TRI_QUAD
                self.bme = min(
                    self.bmf.edges,
                    key=lambda bme:distance2d_point_bmedge(context, self.matrix_world, self.hit, bme),
                )
                return

        if self.update_split_face_loop(context):
            return


        # XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
        if len(self.selected[BMEdge]) == 1 and self.nearest.bmv:
            sel_bmes : set[BMEdge] = self.selected[BMEdge]  # pyright: ignore[reportAssignmentType, reportRedeclaration]
            bme_selected : BMEdge = next(iter(sel_bmes))

            # an interior edge may only knife, never extrude
            interior = bme_is_interior(bme_selected)

            bmf : BMFace | None = next(iter(bme_selected.link_faces), None)
            bme_pt = self.project(bme_midpoint(bme_selected))
            bmv_pt = self.project(self.nearest.bmv.co)

            # A boundary edge on a sharp fold has an adjacent face that doubles back in screen space.
            # Compare the normals of the face and the hovered vert to separate this from simply backfacing.
            doubling_back = (
                bme_selected.is_boundary and bmf is not None
                and self.ignore_splitting_backfaces
                and bmf.normal.dot(self.vec_forward) > 0
                and bmf.normal.dot(self.nearest.bmv.normal) < 0
            )

            # if the segment connecting the center of the selected bme and the hovered bmv actually
            # crosses a face, then we split (knife) the selected edge
            if bme_pt and bmv_pt and not doubling_back:
                splits = find_bmedges_to_split(context, self.matrix_world, bme_selected, bme_pt, bmv_pt, None)
                if len(splits) > 1:
                    self.bme = bme_selected
                    self.state = PP_Action.EDGE_SPLIT_EDGE
                    return

            # not knifing: only non-interior edges may create new geometry
            if not interior:
                self.bme = bme_selected
                self.state = PP_Action.EDGE_TRI
            return

        if len(self.selected[BMEdge]) == 1 and self.nearest_bmf.bmf:
            sel_bmes : set[BMEdge] = self.selected[BMEdge]  # pyright: ignore[reportAssignmentType, reportRedeclaration]
            self.bme = next(iter(sel_bmes))
            self.state = PP_Action.EDGE_SPLIT_EDGE
            return

        if len(self.selected[BMVert]) == 2 and len(self.selected[BMEdge]) == 1:
            sel_bmes : set[BMEdge] = self.selected[BMEdge]  # pyright: ignore[reportAssignmentType, reportRedeclaration]
            self.bme = next(iter(sel_bmes))  # only one selected edge
            # interior edge may only knife, never create a triangle
            self.state = PP_Action.NONE if bme_is_interior(self.bme) else PP_Action.EDGE_TRI
            return

        if len(self.selected[BMEdge]) > 1:
            sel_bmes : set[BMEdge] = self.selected[BMEdge]  # pyright: ignore[reportAssignmentType]
            sel_bmes = { bme for bme in sel_bmes if bme.is_boundary }
            if sel_bmes:
                self.state = PP_Action.EDGE_TRI
                self.bme = min(
                    sel_bmes,
                    key=(lambda bme:distance2d_point_bmedge(context, self.matrix_world, self.hit, bme)),
                )
            return

    def update_split_face_loop(self, context:Context) -> bool:
        """
        find path from one of the selected BMEdges to the hovered BMEdge
        """

        if not self.use_loop_cuts or not self.nearest or not self.nearest_bme or not self.selected:
            return False
        if not self.hit or not self.mouse:
            return False

        bmes_selected : list[tuple[BMEdge, BMVert|None]] = []
        bmes_selected.extend([
            (bme, None) for bme in self.selected[BMEdge]
        ])                                              # pyright: ignore[reportArgumentType]
        # if any bmverts are selected and are adjacent to pentogan bmfaces,, consider the bmedges opposite the bmvert in the pentagon
        def bmf_pentagon_opposite_bme(bmf : BMFace, bmv : BMVert) -> BMEdge:
            bme = bmf_opposite_bmelem(bmf, bmv)
            assert isinstance(bme, BMEdge)  # should never happen!
            return bme
        bmes_selected.extend([                          # pyright: ignore[reportArgumentType]
            (bmf_pentagon_opposite_bme(bmf, bmv), bmv)        # pyright: ignore[reportArgumentType]
            for bmv in self.selected[BMVert]
            for bmf in bmv.link_faces                   # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
            if bmf_is_pentagon(bmf)
        ])
        if not bmes_selected:
            # found no bmedeges to start from
            return False

        bmv_hovered : BMVert|None = self.nearest.bmv
        bme_hovered : BMEdge|None = self.nearest_bme.bme
        bmes_selected.sort(key=lambda bme_bmv : distance2d_point_bmedge(context, self.matrix_world, self.hit, bme_bmv[0]))

        if bme_hovered and bme_hovered.is_boundary:
            # if bme_hovered is boundary and if mouse is not hovering the one bmface
            # that is adjacent to bme_hovered, then we should bridge instead of split

            bmf : BMFace = next(iter(bme_hovered.link_faces))
            bme_co = bme_midpoint(bme_hovered)
            bme_co0, bme_co1 = bme_cos(bme_hovered)
            bmf_co = bmf_midpoint(bmf)
            bmf_pt  = self.project(bmf_co)
            bme_pt, bme_pt0, bme_pt1  = self.project_all(bme_co, bme_co0, bme_co1)

            if bmf_pt and bme_pt and bme_pt0 and bme_pt1:
                # compute vector perpendicular to selected bmedge in screen space that is
                # pointing toward center of adjacent bmface
                v_bme_perp = perpendicular_direction2(bme_pt0 - bme_pt1, bmf_pt - bme_pt)

                # check if vector from center of selected bmedge to hovered bmvert is
                # pointing in same direction as perpendicular vector computed above
                if v_bme_perp.dot(self.mouse - bme_pt) < 0:
                    # hovering bmface adjacent to hovered bmedge
                    return False

        found : list[tuple[
            BMVert|None, BMEdge, BMFace,
            BMFace, BMEdge|None, BMVert|None,
            bool,
            dict[BMEdge|BMFace, BMFace|BMEdge|None],
        ]] = []
        bmv_start : BMVert | None = None
        bmv_end : BMVert | None = None
        for (bme_start, bmv_start) in bmes_selected:
            if bmes_share_bmv(bme_start, bme_hovered):
                continue

            # while a boundary bme_start will have only one, a non-boundary
            # bme_start will have two adjacent faces that we need to check
            for bmf_start in bme_start.link_faces:
                if not bmf_is_quad(bmf_start):
                    # only start walking if starting from a quad
                    continue

                # Anchor the walk to whichever side of the view this start quad is on.
                start_facing = bmf_start.normal.dot(self.vec_forward)

                path_back : dict[BMEdge|BMFace, BMFace|BMEdge|None] = {
                    bme_start: None,
                    bmf_start: bme_start,
                }

                if is_point_inside_bmface(self.project, self.hit, self.mouse, bmf_start, self.ignore_splitting_radius_ratio):
                    # bmf_start is under mouse
                    # TODO: should we raycast to find BMFaces under mouse first, and then check if bmf is in that collection?
                    found.append((bmv_start, bme_start, bmf_start, bmf_start, None, bmv_end, True, path_back))
                    continue

                bme_opposite = bmf_opposite_bme(bmf_start, bme_start)
                assert bme_opposite, f'Could not find BMEdge opposite to {bme_start} for {bmf_start}'
                path_back[bme_opposite] = bmf_start
                if bme_hovered:
                    if bme_opposite == bme_hovered:
                        found.append((bmv_start, bme_start, bmf_start, bmf_start, bme_opposite, None, False, path_back))
                        continue
                    elif bmes_share_bmv(bme_hovered, bme_opposite):
                        # opposite BMEdge is not hovered BMEdge, but they share BMVerts (should split face into corner)
                        continue

                working : list[BMEdge] = [bme_opposite]
                done_walking : bool = False
                while working:
                    bme_current = working.pop(0)

                    bmf_current : BMFace
                    for bmf_current in bme_current.link_faces:
                        if self.ignore_splitting_backfaces and bmf_current.normal.dot(self.vec_forward) * start_facing < 0:
                            # face is on the opposite side of the view from where the walk started
                            continue

                        if bmf_current in path_back:
                            # stop walking, because we have already seen / processed this bmface
                            continue

                        if bmf_is_pentagon(bmf_current):
                            if bmv_hovered and bmv_hovered == bmf_opposite_bmelem(bmf_current, bme_current): # in bmf_current.verts:
                                # special case: hit a pentagon and hovering opposite
                                path_back[bmf_current] = bme_current
                                found.append((
                                    bmv_start, bme_start, bmf_start,
                                    bmf_current, None, bmv_hovered,
                                    False,
                                    path_back,
                                ))
                                done_walking = True
                                break

                            if is_point_inside_bmface(self.project, self.hit, self.mouse, bmf_current, self.ignore_splitting_radius_ratio):
                                # found path to BMFace under mouse
                                # TODO: should we raycast to find BMFaces under mouse first, and then check if bmf_current is in that collection?
                                path_back[bmf_current] = bme_current
                                found.append((
                                    bmv_start, bme_start, bmf_start,
                                    bmf_current, None, None,
                                    True,
                                    path_back,
                                ))
                                done_walking = True
                                break

                        if not bmf_is_quad(bmf_current):
                            # stop walking, because bmface is not a quad
                            continue

                        bme_opposite = bmf_opposite_bme(bmf_current, bme_current)
                        assert bme_opposite         # should NEVER happen!

                        if bme_hovered and bme_hovered != bme_opposite and bmes_share_bmv(bme_hovered, bme_opposite):
                            # opposite BMEdge is not hovered BMEdge, but they share BMVerts (should split face into corner)
                            continue

                        path_back[bmf_current] = bme_current
                        path_back[bme_opposite] = bmf_current

                        if bme_hovered == bme_opposite:
                            # found path to hovered edge
                            found.append((
                                bmv_start, bme_start, bmf_start,
                                bmf_current, bme_hovered, None,
                                False,
                                path_back,
                            ))
                            done_walking = True
                            break

                        if is_point_inside_bmface(self.project, self.hit, self.mouse, bmf_current, self.ignore_splitting_radius_ratio):
                            # found path to BMFace under mouse
                            # TODO: should we raycast to find BMFaces under mouse first, and then check if bmf_current is in that collection?
                            found.append((
                                bmv_start, bme_start, bmf_start,
                                bmf_current, None, None,
                                True,
                                path_back,
                            ))
                            done_walking = True
                            break

                        working.append(bme_opposite)

                    if done_walking:
                        break

        if not found:
            return False

        # find "best" candidate (here, we're going with the shortest)
        bmv_start, bme_start, bmf_start, bmf_end, bme_end, bmv_end, insert_wire, path_back = min(
            found,
            key = lambda data: len(data[-1]),
        )

        # get list of BMEdges to split
        bmes_split : list[BMEdge] = []
        bmvs_split : list[tuple[BMVert, BMVert]] = []

        def add_split(bmf : BMFace, bme : BMEdge|None, *, swap=False):
            if not bme: return
            bmvs : list[BMVert] = list(bmf.verts)
            idx0, idx1 = [ bmvs.index(bmv) for bmv in bme.verts ]
            if (idx0 + 1) % len(bmvs) == idx1:
                idx0, idx1 = idx1, idx0
            if swap: idx0, idx1 = idx1, idx0
            bmes_split.append(bme)
            bmvs_split.append((bmvs[idx0], bmvs[idx1]))

        add_split(bmf_end, bme_end, swap=True)

        bmf_back : BMFace = bmf_end
        while bmf_back in path_back:
            bme_prev : BMEdge = path_back[bmf_back]     # pyright: ignore[reportAssignmentType]
            add_split(bmf_back, bme_prev)
            if bme_prev not in path_back: break
            bmf_back = path_back[bme_prev]              # pyright: ignore[reportAssignmentType]

        bmes_split.reverse()
        bmvs_split.reverse()

        # get the weights (u,v) for splitting bmes
        # get list of bmverts such that a,b,c,d are in correct order and
        #   a and d are bmverts of selected
        #   b and c are bmverts of opposite
        # u is weight from selected a/d to opposite b/c
        # v is weight along selected and opposite from a/b to d/c
        bmvs = list(bmf_end.verts)
        def wrap_idx(i : int) -> int: return i % len(bmvs)
        bme_bmf_end : BMEdge = path_back[bmf_end]                   # pyright: ignore[reportAssignmentType]
        idx0, idx1 = [ bmvs.index(bmv) for bmv in bme_bmf_end.verts ]
        idx = idx0 if wrap_idx(idx1 + 1) == idx0 else idx1
        bmvs = bmvs[idx:] + bmvs[:idx]

        a, b = self.project(bmvs[0].co), self.project(bmvs[1].co)
        c, d = self.project(bmvs[-2].co), self.project(bmvs[-1].co)

        if not self.mouse or not a or not b or not c or not d:
            return False

        if bmv_start or bmv_end:
            u = 1
            if bmv_start:
                bmf = next(bmf for bmf in bmv_start.link_faces if bme_start in bmf.edges)
                bmes = [ bme for bme in bmf.edges if bmv_start in bme.verts ]
                assert len(bmes) == 2, f'Expected {len(bmes)=} == 2  ({bmf=}, {bmv_start in bmf.verts})'
                l0, l1 = bme_length(bmes[0]), bme_length(bmes[1])
                v = 1 - l0 / (l0 + l1)
            elif bmv_end:
                bme = path_back[bmf_end]
                bmf = next(bmf for bmf in bmv_end.link_faces if bme in bmf.edges)
                bmes = [ bme for bme in bmf.edges if bmv_end in bme.verts ]
                assert len(bmes) == 2, f'Expected {len(bmes)=} == 2  ({bmf=}, {bmv_end in bmf.verts})'
                l0, l1 = bme_length(bmes[0]), bme_length(bmes[1])
                v = l0 / (l0 + l1)
            else:
                v = 0.5
        else:
            u, v = compute_quad_factor(self.mouse, a, b, c, d)

        self.state = PP_Action.SPLIT_QUAD_EDGES
        self.bme = None
        self.bme_hovered = None
        self.split_info = {
            'a,b,c,d': (a,b,c,d),
            'bme selected': bme_start,
            'bmes split': bmes_split,
            'bmvs split': bmvs_split,
            'u,v': (u, v),
            'wire': insert_wire,
            'bmv start': bmv_start,
            'bmv end': bmv_end,
        }

        return True


    def draw(self, context:Context):
        # draw previsualization
        if not self.mouse: return
        if not self.hit: return
        if not self.bm or not self.bm.is_valid: return
        if not self.nearest or not self.nearest.is_valid: return
        if not self.nearest_bme or not self.nearest_bme.is_valid: return
        if self.state in {PP_Action.EDGE_TRI, PP_Action.EDGE_QUAD, PP_Action.TRI_QUAD} and (not self.bme or not self.bme.is_valid):
            self.bme = None
            return

        self.apply_feature_snap(context)

        scaled_8px = Drawing.scale(8)
        if scaled_8px is None: return

        theme = context.preferences.themes[0].view_3d
        props = RF_Prefs.get_prefs(context)
        highlight = props.highlight_color

        color_point =               Color4((highlight[0], highlight[1], highlight[2], 1))
        color_border_transparent =  Color4((highlight[0], highlight[1], highlight[2], 0))
        color_border_mesh =         Color4((theme.edge_select[0], theme.edge_select[1], theme.edge_select[2], 1))
        color_border_open =         Color4((highlight[0], highlight[1], highlight[2], 1.0))
        color_stipple =             Color4((theme.face_select[0], theme.face_select[1], theme.face_select[2], 0))
        color_mesh = theme.face_select
        vertex_size = theme.vertex_size

        if self.nearest.bmv:
            Drawing.draw_snap_circles(context, [self.nearest.bmv], self.matrix_world)

        match self.state:
            case PP_Action.VERT:
                pt = self.project(self.hit)
                if not pt: return
                if self.nearest.bmv: return

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_point)
                    draw.vertex(pt)

            case PP_Action.SPLIT_EDGE:
                if not self.nearest_bme.bme: return
                bmv0, bmv1 = self.nearest_bme.bme.verts
                pt = self.nearest_bme.co2d
                p0, p1 = self.project(bmv0.co), self.project(bmv1.co)
                if not pt or not p0 or not p1: return
                # pt = self.project(self.bme)
                d01 = (p1 - p0).normalized() * scaled_8px

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_border_open)
                    draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    draw.vertex(p0 + d01).vertex(pt - d01)
                    draw.vertex(p1 - d01).vertex(pt + d01)

            case PP_Action.SPLIT_QUAD_EDGES:
                if not self.split_info: return
                u, v = self.split_info['u,v']
                bmv_start : BMVert = self.split_info['bmv start']
                bmv_end : BMVert = self.split_info['bmv end']
                pts = []
                if bmv_start:
                    pt = self.project(bmv_start.co)
                    pts.append(pt)
                for (bmv0, bmv1) in self.split_info['bmvs split']:
                    co = bmv0.co + v * (bmv1.co - bmv0.co)
                    pt = self.project(co)
                    pts.append(pt)
                if self.split_info['wire']:
                    pts.append(self.mouse)
                if bmv_end:
                    pt = self.project(bmv_end.co)
                    pts.append(pt)
                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    for pt in pts:
                        draw.vertex(pt)
                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                    draw.color(color_border_open)
                    for p0,p1 in iter_pairs(pts, False):
                        d01 = (p1 - p0).normalized() * scaled_8px
                        draw.vertex(p0+d01).vertex(p1-d01)

            case PP_Action.SPLIT_QUAD | PP_Action.SPLIT_QUAD_CENTER:
                bme0, bme1 = self.bme, self.nearest_bme.bme
                if not bme0 or not bme1 or not self.bme: return

                if self.state == PP_Action.SPLIT_QUAD:
                    bmv00, bmv01 = bme0.verts
                    bmv10, bmv11 = bme1.verts
                    if (bmv01.co - bmv00.co).dot(bmv11.co - bmv10.co) < 0: bmv10, bmv11 = bmv11, bmv10
                else:
                    bmv00 = bmv10 = bmes_shared_bmv(bme0, bme1)
                    if not bmv00 or not bmv10: return
                    bmv01 = bme_other_bmv(bme0, bmv00)
                    bmv11 = bme_other_bmv(bme1, bmv10)
                    if not bmv01 or not bmv11: return

                p00, p01 = self.project(bmv00.co), self.project(bmv01.co)  # selected
                p10, p11 = self.project(bmv10.co), self.project(bmv11.co)  # hovered
                pt = self.nearest_bme.co2d
                if not pt or not p00 or not p01 or not p10 or not p11: return

                v0, v1 = (p01 - p00), (p11 - p10)
                p = intersection2d_line_line(p00, p01, p10, p11)
                if not p:
                    if v0.dot(v1) < 0: p10, p11, v1 = p11, p10, -v1
                else:
                    if v0.dot(p - p00) < 0: p00, p01, v0 = p01, p00, -v0
                    if v1.dot(p - p10) < 0: p10, p11, v1 = p11, p10, -v1
                l0, l1 = v0.length, v1.length
                d0, d1 = v0 / l0, v1 / l1
                l = d1.dot(pt - p10)
                p1 = p10 + d1 * l
                p0 = p00 + v0 * (l / l1)

                splits = find_bmedges_to_split(context, self.matrix_world, self.bme, p0, p1, self.vec_forward if self.ignore_splitting_backfaces else None)

                def find_opposite_and_center_split_quad() -> tuple[Vector|None, Vector|None]:
                    if self.state != PP_Action.SPLIT_QUAD_CENTER: return (None, None)
                    bmvc = bmes_shared_bmv(bme0, bme1)
                    if not bmvc: return (None, None)
                    bmv0 = bme_other_bmv(bme0, bmvc)
                    bmv1 = bme_other_bmv(bme1, bmvc)
                    bmf = next(iter(set(bme0.link_faces) & set(bme1.link_faces)))
                    bmvo = next(iter(set(bmf.verts) - { bmv0, bmv1, bmvc }), None)
                    if not bmvo: return (None, None)
                    pc = self.project(bmvc.co)
                    po = self.project(bmvo.co)
                    if not pc or not po: return (None, None)
                    dist = ((pc - p0).length + (pc - p1).length) / 1.5
                    pnn = pc + (po - pc).normalized() * dist
                    return (po, pnn)

                po, pc = find_opposite_and_center_split_quad()

                ## pt = self.project(self.bme)
                d01 = (p1 - p0).normalized() * scaled_8px

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    # draw.color(color_border_open)
                    # draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)

                    if po and pc:
                        draw.vertex(po)
                        draw.vertex(pc)
                    for _,p in splits:
                        draw.vertex(p)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    if not po or not pc:
                        draw.vertex(p0 + d01).vertex(p1 - d01)
                    else:
                        draw.vertex(p0).vertex(pc)
                        draw.vertex(p1).vertex(pc)
                        draw.vertex(po).vertex(pc)

            case PP_Action.WIRE_VERT_SPLIT_FACE:
                if not self.bmv or not self.nearest.bmv: return
                p0 = self.project(self.bmv.co)
                pt = self.project(self.nearest.bmv.co)
                if not (p0 and pt): return
                diff = pt - p0
                d = diff.normalized() * scaled_8px

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)

                    if not self.nearest.bmv:
                        draw.color(color_border_open)
                        draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(pt)


                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                    draw.color(color_border_open)
                    draw.vertex(p0 + d).vertex(pt - d)

            case PP_Action.VERT_SPLIT_EDGE | PP_Action.WIRE_SPLIT_EDGE_FACE:
                if not self.bmv or not self.nearest_bme.bme: return
                bmv0, bmv1 = self.nearest_bme.bme.verts
                pt = self.nearest_bme.co2d
                p0 = self.project(bmv0.co)
                p1 = self.project(bmv1.co)
                pn = self.project(self.bmv.co)
                if not pt or not p0 or not p1 or not pn: return

                def find_opposite_and_center_split_edge() -> tuple[Vector|None,Vector|None]:
                    if not self.quad_preserve: return (None, None)

                    if self.state == PP_Action.WIRE_SPLIT_EDGE_FACE:
                        # special case
                        bmv_opposite, bmv_center = find_opposite_and_center_wire(self.bmv, self.nearest_bme.bme)
                        if not bmv_opposite or not bmv_center: return (None, None)
                        po = self.project(bmv_opposite.co)
                        pnn = self.project(bmv_center.co)
                        return (po, pnn)

                    bmes = [bme for bme in self.bmv.link_edges if bmes_share_bmv(bme, self.nearest_bme.bme)]
                    if len(bmes) != 1: return (None, None)

                    bmv_corner = bmes_shared_bmv(bmes[0], self.nearest_bme.bme)
                    bmf = next(iter(set(self.bmv.link_faces) & set(self.nearest_bme.bme.link_faces)), None)
                    if not bmf: return (None, None)

                    bmvs = set(bmf.verts) - set(self.nearest_bme.bme.verts) - { bme_other_bmv(bme, self.bmv) for bme in self.bmv.link_edges } - { bmv_corner, self.bmv }
                    if len(bmvs) != 1: return (None, None)

                    bmv_opposite = next(iter(bmvs))
                    po = self.project(bmv_opposite.co)
                    pc = self.project(bmv_corner.co)
                    if not po or not pc: return (None, None)
                    dist = ((pc - pt).length + (pc - pn).length) / 1.5
                    pnn = pc + (po - pc).normalized() * dist
                    return (po, pnn)
                po, pnn = find_opposite_and_center_split_edge()

                splits = find_bmedges_to_split(context, self.matrix_world, self.bmv, pn, pt, self.vec_forward if self.ignore_splitting_backfaces else None)
                splits = [
                    (bme, pt)
                    for (bme, pt) in splits
                    if bme != self.nearest_bme.bme
                ]

                # pt = self.project(self.bme)
                d01 = (p1 - p0).normalized() * scaled_8px

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_border_open)
                    draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)

                    draw.vertex(pn)
                    if po and pnn:
                        draw.vertex(po)
                        draw.vertex(pnn)
                    for (_,p) in splits:
                        draw.vertex(p)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    draw.vertex(p0 + d01).vertex(pt - d01)
                    draw.vertex(p1 - d01).vertex(pt + d01)

                    if not po or not pnn:
                        draw.vertex(pn).vertex(pt)
                    else:
                        draw.color(color_border_open)
                        draw.vertex(pnn).vertex(pt)
                        draw.vertex(pnn).vertex(pn)
                        draw.vertex(pnn).vertex(po)

            case PP_Action.VERT_EDGE | PP_Action.EDGE_SPLIT_EDGE:
                if self.state == PP_Action.VERT_EDGE:
                    if not self.bmv: return
                    p0 = self.project(self.bmv.co)
                else:  # elif self.state == PP_Action.EDGE_SPLIT_EDGE:
                    if not self.bme: return
                    bmv0, bmv1 = self.bme.verts
                    co0, co1 = bmv0.co, bmv1.co
                    co = co0 + (co1 - co0) / 2
                    p0 = self.project(co)
                if self.nearest.bmv:
                    co = self.nearest.bmv.co
                else:
                    co = self.hit
                pt = self.project(co)
                if not (p0 and pt): return
                diff = pt - p0
                d = diff.normalized() * scaled_8px

                po,pnn = None,None
                if self.state == PP_Action.VERT_EDGE and self.quad_preserve and self.nearest.bmv and self.bmv:
                    bmvs_ : set[BMVert|None] = { bmes_shared_bmv(bme0, bme1) for bme0 in self.bmv.link_edges for bme1 in self.nearest.bmv.link_edges if bmes_share_bmv(bme0, bme1) }
                    bmvs : set[BMVert] = { bmv for bmv in bmvs_ if bmv }
                    if len(bmvs) == 1:
                        bmv_corner = next(iter(bmvs))
                        bmf = next(iter(set(self.bmv.link_faces) & set(self.nearest.bmv.link_faces)), None)
                        if bmf:
                            bmvs = set(bmf.verts) - { bme_other_bmv(bme, self.nearest.bmv) for bme in self.nearest.bmv.link_edges } - { bme_other_bmv(bme, self.bmv) for bme in self.bmv.link_edges } - { bmv_corner, self.bmv, self.nearest.bmv }
                            if len(bmvs) == 1:
                                bmv_opposite = next(iter(bmvs))
                                pn = self.project(self.nearest.bmv.co)
                                po = self.project(bmv_opposite.co)
                                pc = self.project(bmv_corner.co)
                                if pn and po and pc:
                                    dist = ((pc - pt).length + (pc - pn).length) / 1.5
                                    pnn = pc + (po - pc).normalized() * dist

                splits : list[tuple[BMVert|BMEdge, Vector]] = []
                if self.state == PP_Action.VERT_EDGE and self.bmv:
                    splits.extend(find_bmedges_to_split(context, self.matrix_world, self.bmv, p0, pt, self.vec_forward if self.ignore_splitting_backfaces else None))
                elif self.bme:  # elif self.state == PP_Action.EDGE_SPLIT_EDGE:
                    splits.extend(find_bmedges_to_split(context, self.matrix_world, self.bme, p0, pt, None))

                if self.nearest.bmv:
                    splits = [
                        (bme, pt)
                        for (bme, pt) in splits
                        if bme not in self.nearest.bmv.link_edges
                    ]

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)

                    if not self.nearest.bmv:
                        draw.color(color_border_open)
                        draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)

                    if po and pnn:
                        draw.vertex(po)
                        draw.vertex(pnn)
                    for _,p in splits:
                        draw.vertex(p)

                if diff.length > scaled_8px:
                    with Drawing.draw(context, CC_2D_LINES) as draw:
                        draw.line_width(2)
                        draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                        draw.color(color_border_open)
                        if not po or not pnn:
                            draw.vertex(p0 + d).vertex(pt - d)
                        else:
                            draw.vertex(p0).vertex(pnn)
                            draw.vertex(pt).vertex(pnn)
                            draw.vertex(po).vertex(pnn)

            case PP_Action.EDGE_TRI:
                if not self.bme: return
                bmv0, bmv1 = self.bme.verts
                p0 = self.project(bmv0.co)
                p1 = self.project(bmv1.co)
                pt = self.project(self.hit)
                if not (p0 and p1 and pt): return
                d0t = (pt - p0).normalized() * scaled_8px
                d1t = (pt - p1).normalized() * scaled_8px
                d01 = (p1 - p0).normalized() * scaled_8px

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)

                    if not self.nearest.bmv:
                        draw.color(color_border_open)
                        draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    draw.vertex(p0 + d0t).vertex(pt - d0t)
                    draw.vertex(p1 + d1t).vertex(pt - d1t)

                    draw.color(color_border_open)
                    draw.vertex(p0 + d01).vertex(p1 - d01)

                with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                    draw.color(color_mesh)
                    draw.vertex(pt).vertex(p0).vertex(p1)

            case PP_Action.EDGE_BRIDGE:
                if not self.bme or not self.bme_hovered_bmvs: return
                bmv0, bmv1 = self.bme.verts
                bmv2, bmv3 = self.bme_hovered_bmvs
                p0 = self.project(bmv0.co)
                p1 = self.project(bmv1.co)
                p2 = self.project(bmv2.co)
                p3 = self.project(bmv3.co)
                if not (p0 and p1 and p2 and p3): return

                d01 = (p1 - p0).normalized() * scaled_8px
                d12 = (p2 - p1).normalized() * scaled_8px
                d23 = (p3 - p2).normalized() * scaled_8px
                d30 = (p0 - p3).normalized() * scaled_8px

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)
                    draw.vertex(p2)
                    draw.vertex(p3)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    draw.vertex(p0 - d30).vertex(p3 + d30)
                    draw.vertex(p1 + d12).vertex(p2 - d12)

                    draw.color(color_border_open)
                    draw.vertex(p0 + d01).vertex(p1 - d01)
                    draw.vertex(p2 + d23).vertex(p3 - d23)

                with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                    draw.color(color_mesh)
                    draw.vertex(p0).vertex(p1).vertex(p2)
                    draw.vertex(p0).vertex(p2).vertex(p3)

            case PP_Action.EDGE_QUAD:
                if not self.bme: return
                bmv0, bmv1 = self.bme.verts
                hit2, hit3 = self.hit2, self.hit3
                p0 = self.project(bmv0.co)
                p1 = self.project(bmv1.co)
                p2 = self.project(hit2)
                p3 = self.project(hit3)
                if not (p0 and p1 and p2 and p3): return

                v01, v12, v23, v30 = (p1 - p0), (p2 - p1), (p3 - p2), (p0 - p3)
                d01 = v01.normalized() * scaled_8px
                d12 = v12.normalized() * scaled_8px
                d23 = v23.normalized() * scaled_8px
                d30 = v30.normalized() * scaled_8px

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_border_open)
                    if not self.bmv2: draw.vertex(p2)
                    if not self.bmv3: draw.vertex(p3)
                    draw.color(color_stipple)
                    draw.border(width=2, color=color_point)
                    draw.vertex(p0)
                    draw.vertex(p1)
                    if self.bmv2: draw.vertex(p2)
                    if self.bmv3: draw.vertex(p3)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    if v30.length > scaled_8px: draw.vertex(p0 - d30).vertex(p3 + d30)
                    if v12.length > scaled_8px: draw.vertex(p1 + d12).vertex(p2 - d12)
                    draw.vertex(p2 + d23).vertex(p3 - d23)

                    draw.color(color_border_open)
                    draw.vertex(p0 + d01).vertex(p1 - d01)

                with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                    draw.color(color_mesh)
                    draw.vertex(p0).vertex(p1).vertex(p2)
                    draw.vertex(p0).vertex(p2).vertex(p3)


            case PP_Action.TRI_QUAD:
                if not self.bme or not self.bmf: return
                bmev0, bmev1 = self.bme.verts
                bmv0, bmv1, bmv2 = self.bmf.verts
                if (bmev0 == bmv0 and bmev1 == bmv1) or (bmev0 == bmv1 and bmev1 == bmv0):
                    pass
                elif (bmev0 == bmv1 and bmev1 == bmv2) or (bmev0 == bmv2 and bmev1 == bmv1):
                    bmv0, bmv1, bmv2 = bmv1, bmv2, bmv0
                else:
                    bmv0, bmv1, bmv2 = bmv2, bmv0, bmv1
                p0 = self.project(bmv0.co)
                p1 = self.project(bmv1.co)
                p2 = self.project(bmv2.co)
                pt = self.project(self.hit)
                if not (p0 and p1 and p2 and pt): return
                d0t = (pt - p0).normalized() * scaled_8px
                d1t = (pt - p1).normalized() * scaled_8px
                d01 = (p1 - p0).normalized() * scaled_8px
                d02 = (p2 - p0).normalized() * scaled_8px
                d12 = (p2 - p1).normalized() * scaled_8px

                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(vertex_size + 4)

                    if not self.nearest.bmv:
                        draw.color(color_border_open)
                        draw.vertex(pt)

                    draw.border(width=2, color=color_point)
                    draw.color(color_stipple)
                    draw.vertex(p0)
                    draw.vertex(p1)
                    draw.vertex(p2)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=color_stipple)

                    draw.color(color_border_open)
                    draw.vertex(p0 + d0t).vertex(pt - d0t)
                    draw.vertex(p1 + d1t).vertex(pt - d1t)

                    draw.color(color_border_open)
                    # draw.vertex(p0 + d01).vertex(p1 - d01)
                    draw.vertex(p0 + d02).vertex(p2 - d02)
                    draw.vertex(p1 + d12).vertex(p2 - d12)

                with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                    draw.color(color_mesh)
                    draw.vertex(p0).vertex(pt).vertex(p1)
                    draw.vertex(p0).vertex(p1).vertex(p2)

            case _:
                pass

    def correct_mirror_side(self, context, co, bmvs_based):
        # make sure co is on same side of mirror as bmvs_based
        mirror = set()
        if has_mirror_x(context): mirror.add('x')
        if has_mirror_y(context): mirror.add('y')
        if has_mirror_z(context): mirror.add('z')
        if not mirror: return co
        mt = mirror_threshold(context)
        if mt is None: return co
        signs = [
            Vector((sign_threshold(bmv.co.x, mt), sign_threshold(bmv.co.y, mt), sign_threshold(bmv.co.z, mt)))
            for bmv in bmvs_based
        ]
        sx,sy,sz = (
            next((s.x for s in signs if s.x != 0), 0),
            next((s.y for s in signs if s.y != 0), 0),
            next((s.z for s in signs if s.z != 0), 0),
        )
        # if using scale * mt * 2, the vert will be created far enough away from mirror to move freely
        # if using 0, the vert is created at mirror, and it will not be allowed to move away from mirror if clipping is enabled
        if 'x' in mirror and sx != 0 and sign_threshold(co.x, mt) != sx: co.x = 0 # sx * mt * 2
        if 'y' in mirror and sy != 0 and sign_threshold(co.y, mt) != sy: co.y = 0 # sy * mt * 2
        if 'z' in mirror and sz != 0 and sign_threshold(co.z, mt) != sz: co.z = 0 # sz * mt * 2
        return co

    def commit(self, context, event):
        # apply the change

        if self.state == PP_Action.NONE: return
        # TODO: UNDO NOT PUSHING ON MULTIPLE TIMES!?!?!
        # bpy.ops.ed.undo_push(message=f'PolyPen commit {time.time()}')

        # snap the placement onto nearby source features before creating geometry
        self.apply_feature_snap(context)

        # make sure artist can see the vert
        context.tool_settings.mesh_select_mode[0] = True

        snap_verts = []     # to be snapped before wrapping up commit
        select_now = []     # to be selected before move
        select_later = []   # to be selected after move
        free_move = not self.constrain_edge_vert

        match self.state:
            case PP_Action.VERT:
                # create new detached vertex
                if self.nearest.bmv:
                    bmv = self.nearest.bmv
                else:
                    bmv = self.bm.verts.new(self.hit)  # self.hit is on surface
                select_now = [bmv]
                free_move = True

            case PP_Action.SPLIT_EDGE:
                # split hovered edge
                bme = self.nearest_bme.bme
                bmev0, bmev1 = bme.verts
                bme_new, bmv_new = edge_split(bme, bmev0, 0.5)
                if not self.constrain_edge_vert:
                    bmv_new.co = self.hit
                else:
                    d = (bmev1.co - bmev0.co).normalized()
                    v = d * d.dot(self.hit - bmev0.co)
                    bmv_new.co = bmev0.co + v
                snap_verts.append(bmv_new)
                select_now = [bmv_new]
                select_later = []

            case PP_Action.SPLIT_QUAD:
                if not self.bm or not self.bme or not self.nearest_bme or not self.nearest_bme.bme:
                    return
                bme0 = self.bme
                bmv00, bmv01 = bme0.verts
                bme1 = self.nearest_bme.bme
                bmv10, bmv11 = bme1.verts

                p00, p01 = self.project(bmv00.co), self.project(bmv01.co)  # selected
                p10, p11 = self.project(bmv10.co), self.project(bmv11.co)  # hovered
                pt = self.nearest_bme.co2d
                if not p00 or not p01 or not p10 or not p11 or not pt:
                    return
                vec0, vec1 = p01 - p00, p11 - p10
                p = intersection2d_line_line(p00, p01, p10, p11)
                if not p:
                    if vec0.dot(vec1) < 0: p10, p11, vec1 = p11, p10, -vec1
                else:
                    if vec0.dot(p - p00) < 0: p00, p01, vec0 = p01, p00, -vec0
                    if vec1.dot(p - p10) < 0: p10, p11, vec1 = p11, p10, -vec1
                len1 = vec1.length
                percent = vec1.dot(pt - p10) / len1 / len1

                p0 = p00 + (p01 - p00) * percent
                p1 = p10 + (p11 - p10) * percent
                splits = find_bmedges_to_split(context, self.matrix_world, self.bme, p0, p1, self.vec_forward if self.ignore_splitting_backfaces else None)

                _, bmv0_new = edge_split(bme0, bmv00, percent)
                _, bmv1_new = edge_split(bme1, bmv10, percent)
                snap_verts.extend([bmv0_new, bmv1_new])
                if len(splits) > 1:
                    bmv_from = bmv0_new
                    for (bme, pt) in splits:
                        if bme == bme0 or bme == bme1: continue
                        _, bmv_new = edge_split(bme, bme.verts[0], 0.5)
                        if pt3d := raycast_point_valid_sources(context, pt, respect_clip_planes=True):     # raycast to surface
                            bmv_new.co = self.matrix_world_inv @ pt3d
                        connect_verts(self.bm, verts=[bmv_from, bmv_new])   # pyright: ignore [reportUnusedCallResult]
                        bmv_from = bmv_new
                    if bmvs_share_bmf(bmv_from, bmv1_new):
                        connect_verts(self.bm, verts=[bmv_from, bmv1_new])  # pyright: ignore [reportUnusedCallResult]
                    else:
                        self.bm.edges.new((bmv_from, bmv1_new))             # pyright: ignore [reportUnusedCallResult]
                else:
                    ret = connect_verts(self.bm, verts=[bmv0_new, bmv1_new])
                select_now = [bmv1_new]
                select_later = []

            case PP_Action.SPLIT_QUAD_EDGES:
                assert self.split_info, f'Expected a populated split_info property'
                u, v = self.split_info['u,v']
                bmv_start = self.split_info['bmv start']
                bmv_end = self.split_info['bmv end']
                bmvs_new = []
                for (bme, (bmv0, bmv1)) in zip(self.split_info['bmes split'], self.split_info['bmvs split']):
                    _, bmv_new = edge_split(bme, bmv0, v)
                    bmvs_new.append(bmv_new)
                for (bmv0, bmv1) in iter_pairs(bmvs_new, False):
                    connect_verts(self.bm, verts=[bmv0, bmv1])
                if bmv_start:
                    bmv0, bmv1 = bmv_start, bmvs_new[0]
                    connect_verts(self.bm, verts=[bmv0, bmv1])
                if bmv_end:
                    bmv0, bmv1 = bmvs_new[-1], bmv_end
                    connect_verts(self.bm, verts=[bmv0, bmv1])
                if self.split_info['wire']:
                    bmv_new = self.bm.verts.new(self.hit)  # self.hit is on surface
                    bme_new = self.bm.edges.new((bmv_new, bmvs_new[-1]))
                    select_now = [bmv_new]
                    free_move = True
                elif bmv_end:
                    select_now = [bmv_end]
                else:
                    select_now = [bmvs_new[-1]]
                snap_verts.extend(bmvs_new)
                select_later = []
                # TODO: mesh isn't updating
                # TODO: selected verts after op not correct



            case PP_Action.SPLIT_QUAD_CENTER:
                bme0, bme1 = self.bme, self.nearest_bme.bme
                bmvc = bmes_shared_bmv(bme0, bme1)
                bmv0 = bme_other_bmv(bme0, bmvc)
                bmv1 = bme_other_bmv(bme1, bmvc)
                bmf = next(iter(set(bme0.link_faces) & set(bme1.link_faces)))
                bmvo = next(iter(set(bmf.verts) - { bmv0, bmv1, bmvc }))

                po = self.project(bmvo.co)
                pc = self.project(bmvc.co)
                p0 = self.project(bmv0.co)
                p1 = self.project(bmv1.co)
                pt = self.nearest_bme.co2d

                v0, v1 = (p0 - pc), (p1 - pc)
                l0, l1 = v0.length, v1.length
                percent = v1.dot(pt - pc) / l1 / l1
                p0n, p1n = pc + v0 * percent, pc + v1 * percent

                dist = ((pc - p0n).length + (pc - p1n).length) / 1.5
                pnn = pc + (po - pc).normalized() * dist

                rc0  = raycast_point_valid_sources(context, p0n,  respect_clip_planes=True)
                rc1  = raycast_point_valid_sources(context, p1n,  respect_clip_planes=True)
                rcnn = raycast_point_valid_sources(context, pnn,  respect_clip_planes=True)
                co0  = self.matrix_world_inv @ rc0   if rc0   else None
                co1  = self.matrix_world_inv @ rc1   if rc1   else None
                conn = self.matrix_world_inv @ rcnn  if rcnn  else None

                _, bmv0_new = edge_split(bme0, bmvc, 0.5)
                _, bmv1_new = edge_split(bme1, bmvc, 0.5)

                if co0:  bmv0_new.co = co0                              # raycast to surface
                if co1:  bmv1_new.co = co1                              # raycast to surface
                bmv_new = self.bm.verts.new(conn if conn else bmvc.co)  # raycast to surface

                # split bmf into 3 quads
                self.bm.faces.remove(bmf)
                bmf0 = self.bm.faces.new([bmvc, bmv0_new, bmv_new, bmv1_new])
                bmf1 = self.bm.faces.new([bmv0_new, bmv0, bmvo, bmv_new])
                bmf2 = self.bm.faces.new([bmv1_new, bmv_new, bmvo, bmv1])

                bmf0.normal_update()
                bmf1.normal_update()
                bmf2.normal_update()
                if bmf0.normal.dot(self.vec_forward) > 0: bmf0.normal_flip()
                if bmf1.normal.dot(self.vec_forward) > 0: bmf1.normal_flip()
                if bmf2.normal.dot(self.vec_forward) > 0: bmf2.normal_flip()

                select_now = [bmv1_new]
                select_later = []


            case PP_Action.EDGE_SPLIT_EDGE:
                # split selected edge then connect new edge-vert and new vert under mouse
                bme = next(iter(self.selected[BMEdge]))
                bmv0, bmv1 = self.bme.verts
                co0, co1 = bmv0.co, bmv1.co
                co = co0 + (co1 - co0) / 2
                p0 = self.project(co)
                pt = self.project(self.hit)

                splits = find_bmedges_to_split(context, self.matrix_world, self.bme, p0, pt, None)
                create_wire = True
                if self.nearest.bmv:
                    # hovering bmvert, so do not make final split
                    bmes = set(self.nearest.bmv.link_edges)
                    while splits and splits[-1][0] in bmes:
                        splits.pop()
                    create_wire = False
                elif self.nearest_bme.bme:
                    create_wire = False

                bmv_from = None
                for (bme_split, pt_split) in splits:
                    _, bmv_split = edge_split(bme_split, bme_split.verts[0], 0.5)
                    if rc := raycast_point_valid_sources(context, pt_split, respect_clip_planes=True):
                        bmv_split.co = self.matrix_world_inv @ rc  # raycast to surface
                    if bmv_from: connect_verts(self.bm, verts=[bmv_from, bmv_split])
                    bmv_from = bmv_split

                if bmv_from is None:
                    # nothing was split, e.g. hovered vert is an endpoint of selected edge
                    return

                if create_wire:
                    bmv1 = self.bm.verts.new(self.hit)  # self.hit is on surface
                    self.bm.edges.new((bmv_from, bmv1))
                elif self.nearest.bmv:
                    connect_verts(self.bm, verts=[bmv_from, self.nearest.bmv])
                    bmv1 = self.nearest.bmv
                else:
                    # hovering an edge/face rather than a vert: the split chain already ends at bmv_from
                    bmv1 = bmv_from

                select_now = [bmv1]
                select_later = []
                free_move = True


            case PP_Action.VERT_EDGE:
                # create new edge between selected vert and current mouse position
                if not self.bmv or not self.nearest:
                    return

                bmv0 = self.bmv
                bmv_opposite, bmv_corner = None, None
                split_co = None

                pn = self.project(self.bmv.co)
                pt = self.project(self.hit)
                splits = find_bmedges_to_split(context, self.matrix_world, self.bmv, pn, pt, self.vec_forward if self.ignore_splitting_backfaces else None)
                if self.nearest.bmv:
                    splits = [
                        (bme, pt)
                        for (bme, pt) in splits
                        if bme not in self.nearest.bmv.link_edges
                    ]

                if self.nearest.bmv:
                    bmv1 = self.nearest.bmv

                    if self.quad_preserve and self.nearest.bmv:
                        bmvs = { bmes_shared_bmv(bme0, bme1) for bme0 in self.bmv.link_edges for bme1 in self.nearest.bmv.link_edges if bmes_share_bmv(bme0, bme1) }
                        if len(bmvs) == 1:
                            bmv_corner = next(iter(bmvs))
                            bmf = next(iter(set(self.bmv.link_faces) & set(self.nearest.bmv.link_faces)), None)
                            if bmf:
                                bmvs = set(bmf.verts) - { bme_other_bmv(bme, self.nearest.bmv) for bme in self.nearest.bmv.link_edges } - { bme_other_bmv(bme, self.bmv) for bme in self.bmv.link_edges } - { bmv_corner, self.bmv, self.nearest.bmv }
                                if len(bmvs) == 1:
                                    bmv_opposite = next(iter(bmvs))
                                    split_dist = ((self.bmv.co - bmv_corner.co).length + (self.nearest.bmv.co - bmv_corner.co).length) / 2
                                    split_dir = (bmv_opposite.co - bmv_corner.co).normalized()
                                    split_co = bmv_corner.co + split_dir * split_dist
                                    if snapped := nearest_point_valid_sources(context, self.matrix_world @ split_co, respect_clip_planes=True):
                                        split_co = self.matrix_world_inv @ snapped
                else:
                    co = self.correct_mirror_side(context, self.hit, [bmv0])
                    bmv1 = self.bm.verts.new(co)
                    snap_verts.append(bmv1)

                if not splits:
                    bmf_split = next((bmf for bmf in bmv0.link_faces if bmv1 in bmf.verts), None)
                    bme = None
                    if bmf_split:
                        ret = connect_verts(self.bm, verts=[bmv0, bmv1])
                        bme = next(iter(ret['edges']), None)
                        if split_co:
                            bme_cut = bme
                            _, bmv_cut = edge_split(bme_cut, self.bmv, 0.5)
                            bmv_cut.co = split_co  # already snapped to surface
                            connect_verts(self.bm, verts=[bmv_cut, bmv_opposite])
                        bme = None
                    else:
                        bme = next(iter(bmops.shared_link_edges([bmv0, bmv1])), None)
                        if not bme:
                            bme = self.bm.edges.new((bmv0, bmv1))
                            free_move = True

                        # select bme only if bmv1 not inside a face!
                        if wire := get_wire(bmv1):
                            if any( point_inside_face(bmv1.co, points_of_bmface(bmf)) for bmf in wire[0].link_faces ):
                                bme = None
                else:
                    bmv_from = self.bmv
                    bmv_first_new = None
                    for (bme_split, pt_split) in splits:
                        if bme_split == self.nearest_bme.bme: break
                        _, bmv_split = edge_split(bme_split, bme_split.verts[0], 0.5)
                        if rc := raycast_point_valid_sources(context, pt_split, respect_clip_planes=True):
                            bmv_split.co = self.matrix_world_inv @ rc  # raycast to surface
                        connect_verts(self.bm, verts=[bmv_from, bmv_split])
                        if bmv_first_new is None: bmv_first_new = bmv_split
                        bmv_from = bmv_split

                    wire = get_wire_split_face(self.bmv)
                    if wire and bmv_first_new:
                        wire, bmf_split = wire
                        self.bm.edges.new((wire[-1], bmv_first_new))

                        wire_bmvs = wire[::2] + [bmv_first_new]
                        bmf_bmvs = [ loop.vert for loop in bmf_split.loops ]    # includes new bmvert from splitting edge
                        self.bm.faces.remove(bmf_split)                         # remove face, and then rebuild it as two faces...

                        idx = bmf_bmvs.index(wire_bmvs[-1])
                        bmf0_bmvs = bmf_bmvs[idx:] + bmf_bmvs[:idx]  # rotate so wire_bmvs[-1] is bmf_bmvs[0]
                        idx = bmf0_bmvs.index(wire_bmvs[0])
                        bmf0_bmvs = wire_bmvs + bmf0_bmvs[1:idx]
                        self.bm.faces.new(bmf0_bmvs)

                        idx = bmf_bmvs.index(wire_bmvs[0])
                        bmf1_bmvs = bmf_bmvs[idx:] + bmf_bmvs[:idx]  # rotate so wire_bmvs[0] is bmf_bmvs[0]
                        idx = bmf1_bmvs.index(wire_bmvs[-1])
                        bmf1_bmvs = wire_bmvs[::-1] + bmf1_bmvs[1:idx]
                        self.bm.faces.new(bmf1_bmvs)


                    if self.nearest.bmv:
                        connect_verts(self.bm, verts=[bmv_from, bmv1])
                    else:
                        self.bm.edges.new((bmv_from, bmv1))
                        free_move = True
                    bme = None
                select_now = [bmv1]
                select_later = [bme] if bme and self.insert_mode != 'EDGE-ONLY' else []

            case PP_Action.WIRE_VERT_SPLIT_FACE | PP_Action.WIRE_SPLIT_EDGE_FACE:
                if self.state == PP_Action.WIRE_VERT_SPLIT_FACE:
                    bmv_connect = self.nearest.bmv
                    wire, bmf_split = check_split_face(self.bmv, bmv_connect)
                    bmv_opposite = None

                else:  # self.state == PP_Action.WIRE_SPLIT_EDGE_FACE
                    # split hovered edge, create new edge from selected vert to new vert, split face
                    bme = self.nearest_bme.bme
                    bmev0, bmev1 = bme.verts
                    wire, bmf_split = check_split_face(self.bmv, bme)

                    bmv_opposite, bmv_center = find_opposite_and_center_wire(self.bmv, bme) if self.quad_preserve else (None, None)

                    _, bmv_new = edge_split(bme, bmev0, 0.5)
                    if not self.constrain_edge_vert:
                        bmv_new.co = self.hit
                    else:
                        d = (bmev1.co - bmev0.co).normalized()
                        v = d * d.dot(self.hit - bmev0.co)
                        bmv_new.co = bmev0.co + v
                        snap_verts.append(bmv_new)
                    bmv_connect = bmv_new

                self.bm.edges.new((wire[-1], bmv_connect))

                wire_bmvs = wire[::2] + [bmv_connect]
                bmf_bmvs = [ loop.vert for loop in bmf_split.loops ]    # includes new bmvert from splitting edge
                self.bm.faces.remove(bmf_split)                         # remove face, and then rebuild it as two faces...

                idx = bmf_bmvs.index(wire_bmvs[-1])
                bmf0_bmvs = bmf_bmvs[idx:] + bmf_bmvs[:idx]  # rotate so wire_bmvs[-1] is bmf_bmvs[0]
                idx = bmf0_bmvs.index(wire_bmvs[0])
                bmf0_bmvs = wire_bmvs + bmf0_bmvs[1:idx]
                self.bm.faces.new(bmf0_bmvs)

                idx = bmf_bmvs.index(wire_bmvs[0])
                bmf1_bmvs = bmf_bmvs[idx:] + bmf_bmvs[:idx]  # rotate so wire_bmvs[0] is bmf_bmvs[0]
                idx = bmf1_bmvs.index(wire_bmvs[-1])
                bmf1_bmvs = wire_bmvs[::-1] + bmf1_bmvs[1:idx]
                self.bm.faces.new(bmf1_bmvs)

                if bmv_opposite:
                    connect_verts(self.bm, verts=[self.bmv, bmv_opposite])

                select_now = [bmv_connect]
                select_later = []

            case PP_Action.VERT_SPLIT_EDGE:
                # split hovered edge and create new edge from selected vert
                if not self.nearest_bme or not self.bmv or not self.hit:
                    return
                if not self.nearest_bme.bme:
                    return
                bmev0, bmev1 = self.nearest_bme.bme.verts

                pn = self.project(self.bmv.co)
                pt = self.project(self.hit)
                if not pn or not pt:
                    return
                splits = find_bmedges_to_split(context, self.matrix_world, self.bmv, pn, pt, self.vec_forward if self.ignore_splitting_backfaces else None)
                splits = [
                    (bme, pt)
                    for (bme, pt) in splits
                    if bme != self.nearest_bme.bme
                ]

                bmv_corner, bmv_opposite = None, None
                split_co = None
                if self.quad_preserve:
                    bmes = [bme for bme in self.bmv.link_edges if bmes_share_bmv(bme, self.nearest_bme.bme)]
                    if len(bmes) == 1:
                        bmv_corner = bmes_shared_bmv(bmes[0], self.nearest_bme.bme)
                        bmf = next(iter(set(self.bmv.link_faces) & set(self.nearest_bme.bme.link_faces)), None)
                        if bmf:
                            bmvs = set(bmf.verts) - set(self.nearest_bme.bme.verts) - { bme_other_bmv(bme, self.bmv) for bme in self.bmv.link_edges } - { bmv_corner, self.bmv }
                            if len(bmvs) == 1:
                                bmv_opposite = next(iter(bmvs))
                                split_dist = ((self.bmv.co - bmv_corner.co).length + (self.hit - bmv_corner.co).length) / 1.5
                                split_dir = (bmv_opposite.co - bmv_corner.co).normalized()
                                split_co = bmv_corner.co + split_dir * split_dist
                                if snapped := nearest_point_valid_sources(context, self.matrix_world @ split_co, respect_clip_planes=True):
                                    split_co = self.matrix_world_inv @ snapped
                                splits = []

                _, bmv_new = edge_split(self.nearest_bme.bme, bmev0, 0.5)
                if not self.constrain_edge_vert:
                    bmv_new.co = self.hit
                else:
                    d = (bmev1.co - bmev0.co).normalized()
                    v = d * d.dot(self.hit - bmev0.co)
                    bmv_new.co = bmev0.co + v
                    snap_verts.append(bmv_new)

                if not splits:
                    bmf_split = next((bmf for bmf in self.bmv.link_faces if bmv_new in bmf.verts), None)
                    if bmf_split:
                        ret = connect_verts(self.bm, verts=[self.bmv, bmv_new])
                        if split_co:
                            bme_cut = ret['edges'][0]
                            _, bmv_cut = edge_split(bme_cut, self.bmv, 0.5)
                            bmv_cut.co = split_co  # already snappend to surface
                            connect_verts(self.bm, verts=[bmv_cut, bmv_opposite])
                    else:
                        bme_new = self.bm.edges.new((self.bmv, bmv_new))
                else:
                    bmv_from = self.bmv
                    bmv_first_new = None
                    for (bme_split, pt_split) in splits:
                        if bme_split == self.nearest_bme.bme: break
                        _, bmv_split = edge_split(bme_split, bme_split.verts[0], 0.5)
                        if rc := raycast_point_valid_sources(context, pt_split, respect_clip_planes=True):
                            bmv_split.co = self.matrix_world_inv @ rc  # raycast to surface
                        connect_verts(self.bm, verts=[bmv_from, bmv_split])
                        if bmv_first_new is None: bmv_first_new = bmv_split
                        bmv_from = bmv_split
                    connect_verts(self.bm, verts=[bmv_from, bmv_new])

                    wire = get_wire_split_face(self.bmv)
                    if wire and bmv_first_new:
                        wire, bmf_split = wire
                        self.bm.edges.new((wire[-1], bmv_first_new))

                        wire_bmvs = wire[::2] + [bmv_first_new]
                        bmf_bmvs = [ loop.vert for loop in bmf_split.loops ]    # includes new bmvert from splitting edge
                        self.bm.faces.remove(bmf_split)                         # remove face, and then rebuild it as two faces...

                        idx = bmf_bmvs.index(wire_bmvs[-1])
                        bmf0_bmvs = bmf_bmvs[idx:] + bmf_bmvs[:idx]  # rotate so wire_bmvs[-1] is bmf_bmvs[0]
                        idx = bmf0_bmvs.index(wire_bmvs[0])
                        bmf0_bmvs = wire_bmvs + bmf0_bmvs[1:idx]
                        self.bm.faces.new(bmf0_bmvs)

                        idx = bmf_bmvs.index(wire_bmvs[0])
                        bmf1_bmvs = bmf_bmvs[idx:] + bmf_bmvs[:idx]  # rotate so wire_bmvs[0] is bmf_bmvs[0]
                        idx = bmf1_bmvs.index(wire_bmvs[-1])
                        bmf1_bmvs = wire_bmvs[::-1] + bmf1_bmvs[1:idx]
                        self.bm.faces.new(bmf1_bmvs)

                select_now = [bmv_new]
                select_later = []

            case PP_Action.EDGE_TRI:
                # create triangle from selected edge and current mouse position
                bmv0, bmv1 = self.bme.verts
                if self.nearest.bmv:
                    bmv = self.nearest.bmv
                else:
                    co = self.correct_mirror_side(context, self.hit, self.bme.verts)
                    bmv = self.bm.verts.new(co)
                    snap_verts.append(bmv)
                bmf = next(iter(bmops.shared_link_faces([bmv0, bmv1, bmv])), None)
                select_now = [bmv]
                select_later = []
                if bmf:
                    # split face
                    if not bmops.shared_link_edges([bmv0, bmv]):
                        bmf0, _ = bmesh.utils.face_split(bmf, bmv0, bmv)
                        select_later += [bmf0]
                        # don't know which face is touching bmv1 (bmvf or bmf0), so just grab again
                        bmf = next(iter(bmops.shared_link_faces([bmv1, bmv])), None)
                    if not bmops.shared_link_edges([bmv1, bmv]):
                        bmf1, _ = bmesh.utils.face_split(bmf, bmv1, bmv)
                        select_later += [bmf1]
                else:
                    bmf = self.bm.faces.new((bmv0,bmv1,bmv))
                    bmf.normal_update()
                    if xform_direction(self.matrix_world_inv, view_forward_direction(context)).dot(bmf.normal) > 0:
                        bmf.normal_flip()
                select_later += [bmf]
                free_move = True

            case PP_Action.EDGE_BRIDGE:
                # create quad between selected and hovered edges
                bmv0, bmv1 = self.bme.verts
                bmv2, bmv3 = self.bme_hovered_bmvs
                bmf = self.bm.faces.new((bmv0, bmv1, bmv2, bmv3))
                bmf.normal_update()
                if xform_direction(self.matrix_world_inv, view_forward_direction(context)).dot(bmf.normal) > 0:
                    bmf.normal_flip()
                select_now = [bmv2, bmv3]
                select_later = [bmf]

            case PP_Action.EDGE_QUAD:
                # create quad from selected edge and current mouse position
                bmv0, bmv1 = self.bme.verts
                if self.bmv2:
                    bmv2 = self.bmv2
                else:
                    co2 = self.correct_mirror_side(context, self.hit2, self.bme.verts)
                    bmv2 = self.bm.verts.new(co2)
                    snap_verts.append(bmv2)
                if self.bmv3:
                    bmv3 = self.bmv3
                else:
                    co3 = self.correct_mirror_side(context, self.hit3, self.bme.verts)
                    bmv3 = self.bm.verts.new(co3)
                    snap_verts.append(bmv3)
                bmf = self.bm.faces.new((bmv0, bmv1, bmv2, bmv3))
                bmf.normal_update()
                if xform_direction(self.matrix_world_inv, view_forward_direction(context)).dot(bmf.normal) > 0:
                    bmf.normal_flip()
                select_now = [bmv2, bmv3]
                select_later = [bmf]
                free_move = True

            case PP_Action.TRI_QUAD:
                # convert selected triangle into quad
                bmev0, bmev1 = self.bme.verts
                bmv0, bmv1, bmv2 = self.bmf.verts
                if (bmev0 == bmv0 and bmev1 == bmv1) or (bmev0 == bmv1 and bmev1 == bmv0):
                    pass
                elif (bmev0 == bmv1 and bmev1 == bmv2) or (bmev0 == bmv2 and bmev1 == bmv1):
                    bmv0, bmv1, bmv2 = bmv1, bmv2, bmv0
                else:
                    bmv0, bmv1, bmv2 = bmv2, bmv0, bmv1
                if self.nearest.bmv:
                    bmv = self.nearest.bmv
                else:
                    co = self.correct_mirror_side(context, self.hit, self.bmf.verts)
                    bmv = self.bm.verts.new(co)
                    snap_verts.append(bmv)
                _, bmv_new = edge_split(self.bme, bmev0, 0.5)
                bmesh.ops.weld_verts(self.bm, targetmap={bmv_new: bmv})
                select_now = [bmv]
                select_later = [self.bmf]
                free_move = True

            case _:
                assert False, f'Unhandled PolyPen state {PP_Action[self.state]}'

        for bmv in snap_verts:
            if not bmv.is_valid: continue
            if snapped := nearest_point_valid_sources(context, self.matrix_world @ bmv.co, respect_clip_planes=True):
                bmv.co = self.matrix_world_inv @ snapped

        bmops.deselect_all(self.bm)
        for bmelem in select_now:
            bmops.select(self.bm, bmelem)
        for bmelem in select_later:
            match bmelem:
                case BMVert():
                    bmelem[self.layer_sel_vert] = 1
                case BMEdge():
                    bmelem[self.layer_sel_edge] = 1
                    for bmv in bmelem.verts:
                        bmv[self.layer_sel_vert] = 1
                case BMFace():
                    bmelem[self.layer_sel_face] = 1
                    for bmv in bmelem.verts:
                        bmv[self.layer_sel_vert] = 1
        self.update_bmesh_selection = bool(select_later)
        self.nearest = None
        self.hit = None
        self.selected = None

        bmops.flush_selection(self.bm, self.em)

        if free_move:
            bpy.ops.retopoflow.translate('INVOKE_DEFAULT', False, move_hovered=False, snap_method='PROJECTED', use_native='FALSE')
        else:
            bpy.ops.transform.vert_slide('INVOKE_DEFAULT')  # TODO: add option to retopoflow.translate to handle this

        # NOTE: the select-later property is _not_ transferred to the vert into which the moved vert is auto-merged...
        #       this is handled if a BMEdge or BMFace is to be selected later, but it is not handled if only a BMVert
        #       is created and then merged into existing geometry
