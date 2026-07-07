'''
Copyright (C) 2026 CG Cookie
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

# pyright: reportUninitializedInstanceVariable = false


from __future__ import annotations
from typing import ClassVar, cast, TypeAlias
from collections.abc import Sequence
from collections import deque

import bpy
from bpy.types import Mesh, Context, Event
from bpy_extras.view3d_utils import location_3d_to_region_2d
import bmesh
from bmesh.types import BMesh, BMVert, BMEdge
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

from ..rfglobals import RFGlobals

from ..preferences import RF_Prefs

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.colors import Color4
from ...addon_common.common.unionfind import UnionFind
from ...addon_common.common.utils import iter_pairs
from ..common.bmesh import get_bmesh_emesh
from ..common.drawing import Drawing, CC_2D_LINES, CC_2D_POINTS, CC_2D_TRIANGLES
from ..common.raycast import (
    nearest_point_valid_sources,
    Raycast,
    mouse_from_event,
    size2D_to_size,
)


DEBUG_PRINT : bool = False


LERP_WEIGHT : TypeAlias = float
INDEX_BMVERT : TypeAlias = int
INDEX_PVERT : TypeAlias = int
INDEX_CORNER_NEW : TypeAlias = int

PVERT_ARG : TypeAlias = int | tuple['PVERT_ARG', 'PVERT_ARG', float]
# Note: must quote recursive PVERT_ARG here ^^ and ^^ for Python 3.11 which is used by Blender 4.2


class PVert:
    """
    Convenience class that handles computing LERPed and snapped positions
    """

    arg : INDEX_BMVERT | tuple[PVert, PVert, LERP_WEIGHT]

    co : Vector
    co_snapped_world : Vector

    def __init__(self, context : Context, M : Matrix, bm : BMesh, arg : PVERT_ARG):
        def wrap(warg : PVERT_ARG | PVert) -> PVert:
            match warg:
                case PVert():
                    return warg
                case int() as idx:
                    return PVert(context, M, bm, idx)
                case (ia0, ia1, weight):
                    return PVert(context, M, bm, (ia0, ia1, weight))
                case _: # pyright: ignore[reportUnnecessaryComparison]
                    assert False, f'Unhandled type {type(arg)} ({arg})' # pyright: ignore[reportUnreachable]

        match arg:
            case int() as idx:
                self.arg = idx
                self.co = bm.verts[idx].co

            case (a0, a1, weight):
                assert isinstance(a0, (int, PVert, tuple)), f'Unhandled type {type(arg)} ({arg})'
                assert isinstance(a1, (int, PVert, tuple)), f'Unhandled type {type(arg)} ({arg})'
                pv0 = wrap(a0)
                pv1 = wrap(a1)
                self.arg = ( pv0, pv1, weight)
                self.co = pv0.co + (pv1.co - pv0.co) * weight

            case _: # pyright: ignore[reportUnnecessaryComparison]
                assert False, f'Unhandled type {type(arg)} ({arg})' # pyright: ignore[reportUnreachable]

        co_snapped_world = nearest_point_valid_sources(context, M @ self.co)
        assert co_snapped_world
        self.co_snapped_world = co_snapped_world

    @property
    def existing(self) -> bool:
        return isinstance(self.arg, int)

    def bmv(self, bm : BMesh) -> BMVert | None:
        return bm.verts[self.arg] if isinstance(self.arg, int) else None



class Patch:
    # vertices of patch, either as index of BMVert (int) or as LERP of BMVerts (tuple of inds and weights)
    # Note: these are indices into bm.verts
    _verts : list[PVert]

    # edges and faces that make up patch as indices into _verts
    # Note: these are indices into Patch._verts, **NOT** bm.verts or bm.edges or bm.faces
    _edges : list[Sequence[INDEX_PVERT]]    # always exactly two indices
    _faces : list[Sequence[INDEX_PVERT]]

    # snapped co in world space of each vert, edge, face of patch
    verts : list[Vector]
    edges : list[Sequence[Vector]]  # always exactly two vectors
    faces : list[Sequence[Vector]]


    def __init__(self, bm : BMesh, M : Matrix, sides : list[list[int]]):
        print('New Patch')
        self._process(bpy.context, M, bm, sides)

    def reset(self):
        self._verts = []
        self._edges = []
        self._faces = []
        self.edges = []
        self.faces = []

    def _process(self, context : Context, M : Matrix, bm : BMesh, sides : list[list[int]]):

        self.reset()

        match len(sides):
            case 4:
                self._process_quad(context, M, bm, sides)
            case _:
                print(f'Unhandled number of sides {len(sides)}')

        self.verts = [ pv.co_snapped_world for pv in self._verts ]
        self.edges = [ (self.verts[i0], self.verts[i1]) for (i0, i1) in self._edges ]
        self.faces = [ tuple(self.verts[i] for i in f) for f in self._faces ]


    def _process_quad(self, context : Context, M : Matrix, bm : BMesh, sides : list[list[int]]):
        assert len(sides) == 4

        side_a, side_b, side_c, side_d = sides
        la, lb, lc, ld = map(len, sides)

        # can only process 4-sided patch if opposite sides have same number of verts/edges
        if la != lc or lb != ld:
            return

        w, h = la, lb

        def a(i : int) -> int:
            return side_a[i]
        def b(j : int) -> int:
            return side_b[j]
        def c(i : int) -> int:
            return side_c[w-1-i]
        def d(j : int) -> int:
            return side_d[h-1-j]

        # gather info about verts of patch
        for j in range(h):
            for i in range(w):
                if j == 0:
                    # along top side (A)
                    self._verts.append(PVert(context, M, bm, a(i)))
                elif j == h - 1:
                    # along bottom side (C)
                    self._verts.append(PVert(context, M, bm, c(i)))
                elif i == 0:
                    # along left side (D)
                    self._verts.append(PVert(context, M, bm, d(j)))
                elif i == w - 1:
                    # along right side (B)
                    self._verts.append(PVert(context, M, bm, b(j)))
                else:
                    # somewhere in the middle of patch (not along side)
                    self._verts.append(PVert(
                        context, M, bm,
                        (
                            (a(i), c(i), j / (h - 1)),
                            (d(j), b(j), i / (w - 1)),
                            0.5,
                        ),
                    ))

        # gather info about edges of patch
        for j in range(h):
            for i in range(w - 1):
                self._edges.append((
                    j * w + (i + 0),
                    j * w + (i + 1),
                ))
        for j in range(h - 1):
            for i in range(w):
                self._edges.append((
                    (j + 0) * w + i,
                    (j + 1) * w + i,
                ))

        # gather info about faces of patch
        # TODO: make sure direction is correct here rather than using normals
        for j in range(h - 1):
            for i in range(w - 1):
                self._faces.append((
                    (j + 0) * w + (i + 0),
                    (j + 0) * w + (i + 1),
                    (j + 1) * w + (i + 1),
                    (j + 1) * w + (i + 0),
                ))

    def commit(self, bm : BMesh, M : Matrix):
        Mi = M.inverted_safe()

        # collect all existing BMVerts
        # IMPORTANT: must do this before creating new BMVerts so we don't trigger invalidation of indices
        verts_existing : list[BMVert | None] = [
            v.bmv(bm) if v.existing else None
            for v in self._verts
        ]

        # collect all BMVerts, creating any new BMVerts as needed
        verts_all : list[BMVert] = [
            bmv if bmv else bm.verts.new(Mi @ co_world)
            for (bmv, co_world) in zip(verts_existing, self.verts)
        ]

        # create all new BMFaces
        for f in self._faces:
            _ = bm.faces.new([ verts_all[i] for i in f ])

        self.reset()


class Patches_Logic:
    depsgraph_version : ClassVar[int] = -42                 # last depsgraph seen, used to trigger processing
    loose_bmv_indices : set[INDEX_BMVERT] | None = None     # indices of BMVerts with no linked BMFace
    active_index      : INDEX_BMVERT | None      = None     # index of last active BMVert, used to update corners

    # corners for patch
    # IMPORTANT: must not keep reference to bmesh elements, because they will invalidate
    #            whenever depsgraph changes!  Instead, keep track of them via their indices.
    corners_bmv : ClassVar[set[INDEX_BMVERT]]     = set()   # corners as indices into bm.verts (existing BMVerts)
    corners_new : ClassVar[list[Vector]]          = []      # corners as local-space coordinates (new BMVerts)
    used_bmv    : ClassVar[set[INDEX_BMVERT]]     = set()   # indices of corner BMVerts that are used in >= sides (NOT index into corners_bmv, which is a set)
    used_new    : ClassVar[set[INDEX_CORNER_NEW]] = set()   # indices of corners_new that are used in >= sides

    # detected sides of patch, where ends of each side is a corner
    sides       : ClassVar[list[list[INDEX_BMVERT]]] = []

    # detected patch based on sides
    patch       : ClassVar[Patch | None]    = None

    @staticmethod
    def update(*, just_modified_corners : bool = False):
        RFCore = RFGlobals.RFCore
        context = bpy.context
        edit_object = context.edit_object
        assert edit_object
        M = edit_object.matrix_world

        if just_modified_corners:
            pass

        elif Patches_Logic.depsgraph_version == RFCore.depsgraph_version:
            bm, _ = get_bmesh_emesh(context)
            active = bm.select_history.active
            a = active.index if isinstance(active, BMVert) else None
            if Patches_Logic.active_index == a:
                return

            print('same depsgraph but different active')
            print(f'  {Patches_Logic.active_index} {a}')
            Patches_Logic.active_index = a

        else:
            print('depsgraph changed')
            # clear cache of "loose" BMVerts, to be regenerated in insert_corner()
            Patches_Logic.loose_bmv_indices = None

        Patches_Logic.depsgraph_version = RFCore.depsgraph_version

        bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)
        if not just_modified_corners:
            Patches_Logic.update_corners(bm)
        Patches_Logic.update_sides(bm)
        Patches_Logic.patch = Patch(bm, M, Patches_Logic.sides)


    @staticmethod
    def update_corners(bm : BMesh):
        len_verts = len(bm.verts)

        # same number of BMVerts or just inserted BMVert (Patches_Logic.insert_corner)
        if isinstance(bmv_active := bm.select_history.active, BMVert):
            # add active element to collection of corner BMVerts
            Patches_Logic.corners_bmv.add(bmv_active.index)

        # keep only corners that are still selected
        Patches_Logic.corners_bmv = {
            i
            for i in Patches_Logic.corners_bmv
            if i < len_verts and (bmv := bm.verts[i]) and bmv.select
        }

    @staticmethod
    def update_sides(bm : BMesh):
        Patches_Logic.sides.clear()
        Patches_Logic.used_bmv.clear()
        Patches_Logic.used_new.clear()

        corners : set[BMVert] = {
            bm.verts[i] for i in Patches_Logic.corners_bmv
        }
        if not corners:
            if DEBUG_PRINT:
                print('no corners')
            return

        # check for cycle
        def get_biggest_cycle() -> list[list[BMVert]] | None:
            cycle : list[list[BMVert]] | None = None

            for bmv_init in corners:
                bmv0 = bmv_init
                for bme0 in bmv0.link_edges:
                    if bme0.hide or not bme0.select:
                        continue

                    touched_corners : set[BMVert] = { bmv0 }
                    touched_bmes : set[BMEdge] = { bme0 }
                    sides_bmvs : list[list[BMVert]] = []
                    side_bmvs : list[BMVert] = [ bmv0 ]

                    while True:
                        bmv1 = bme0.other_vert(bmv0)
                        if not bmv1:
                            break

                        side_bmvs.append(bmv1)

                        if bmv1 in corners:
                            touched_corners.add(bmv1)
                            sides_bmvs.append(side_bmvs)
                            side_bmvs = [ bmv1 ]

                        if bmv1 == bmv_init:
                            # possible to not touch all corners!
                            # return sides_bmvs if len(touched_corners) == len(corners) else None
                            if not cycle or sum(len(c) for c in cycle) < sum(len(s) for s in sides_bmvs):
                                cycle = sides_bmvs
                            break

                        bme1 = next(
                            (
                                bme
                                for bme in bmv1.link_edges
                                if bme.select and not bme.hide and bme not in touched_bmes
                            ),
                            None
                        )
                        if not bme1:
                            break

                        bmv0, bme0 = bmv1, bme1
                        touched_bmes.add(bme0)

            # need at least 1 side to be a cycle
            return cycle if cycle and len(cycle) >= 2 else None


        if (cycle_sides := get_biggest_cycle()):
            print('found cycle')

            # make sure direction of sides is consistent
            if cycle_sides[0][0] == cycle_sides[1][0] or cycle_sides[0][0] == cycle_sides[1][-1]:
                # first side is reversed
                cycle_sides[0].reverse()
            for (side0, side1) in zip(cycle_sides[:-1], cycle_sides[1:]):
                if side0[-1] == side1[-1]:
                    # reverse side1 so side0 and side1 are in same direction
                    side1.reverse()

            # check that cycle is correct direction
            bmvs : list[BMVert] = [ side[0] for side in cycle_sides ]
            co_center = sum([bmv.co for bmv in bmvs], Vector((0,0,0))) / len(bmvs)
            normal_patch = sum(
                (
                    (bmv0.co - co_center).cross(bmv1.co - co_center)
                    for (bmv0, bmv1) in iter_pairs(bmvs, True)
                ), Vector((0, 0, 0))
            )
            normal_corners = sum(
                ( bmv.normal for bmv in bmvs ),
                Vector((0, 0, 0))
            )
            if normal_patch.dot(normal_corners) < 0:
                # reverse cycle
                cycle_sides = [
                    list(side[::-1])
                    for side in cycle_sides[::-1]
                ]

            # record sides
            Patches_Logic.sides = [
                [ bmv.index for bmv in cycle_side ]
                for cycle_side in cycle_sides
            ]
            Patches_Logic.used_bmv = {
                bmv.index
                for cycle_side in cycle_sides
                for bmv in [cycle_side[0], cycle_side[-1]]
            }
            print(Patches_Logic.used_bmv)

            return

        graph_corners : dict[BMVert, dict[BMVert, list[BMVert]]] = {
            bmv: {}
            for bmv in corners
        }
        uf = UnionFind(corners)

        for bmv_init in corners:
            paths : dict[BMVert, BMVert] = { bmv_init: bmv_init }
            touched : set[BMEdge | BMVert] = set()
            working : deque[BMVert] = deque([ bmv_init ])
            while working:
                bmv0 = working.popleft()
                for bme in bmv0.link_edges:
                    if not bme.select or bme.hide or bme in touched:
                        continue
                    touched.add(bme)

                    bmv1 = bme.other_vert(bmv0)
                    if not bmv1 or bmv1 in touched:
                        continue

                    # touched.add(bmv1)
                    paths[bmv1] = bmv0

                    if bmv1 not in corners:
                        # have not reached corner, yet
                        working.append(bmv1)
                        continue

                    # found a corner, add to graph
                    bmv = bmv1
                    path : list[BMVert] = [ bmv ]
                    while path[-1] != bmv_init:
                        path.append(paths[path[-1]])
                    path.reverse()
                    graph_corners[bmv_init][bmv1] = path
                    uf.connect(bmv_init, bmv1)

        if DEBUG_PRINT:
            print()
            for bmv0 in graph_corners:
                print(f'{bmv0.index}')
                for bmv1 in graph_corners[bmv0]:
                    print(f'  {bmv1.index}: {[bmv.index for bmv in graph_corners[bmv0][bmv1]]}')
            print(f'roots: {[bmv.index for bmv in uf.roots()]}')

            solos     = { bmv0 for bmv0 in graph_corners if len(graph_corners[bmv0]) == 0 }
            ends      = { bmv0 for bmv0 in graph_corners if len(graph_corners[bmv0]) == 1 }
            joints    = { bmv0 for bmv0 in graph_corners if len(graph_corners[bmv0]) == 2 }
            junctions = { bmv0 for bmv0 in graph_corners if len(graph_corners[bmv0]) >= 3 }
            print(f'solos:     {solos}')
            print(f'ends:      {ends}')
            print(f'joints:    {joints}')
            print(f'junctions: {junctions}')



        # starts : set[BMVert] = set(corners)
        # path : dict[BMVert, BMVert | None] = {}
        # touched_bmes : set[BMEdge] = set()

        # while starts:
        #     bmv = starts.pop()

        #     if not bmv.link_edges:
        #         Patches_Logic.sides.append([bmv.index])
        #         continue

        #     path[bmv] = None
        #     walking_queue : deque[BMVert] = deque([ bmv ])
        #     touched : set[BMVert] = set()

        #     while walking_queue:
        #         bmv = walking_queue.popleft()
        #         if bmv in touched:
        #             continue
        #         touched.add(bmv)

        #         if bmv in starts:
        #             side_bmvs : list[BMVert] = [ ]
        #             while bmv:
        #                 side_bmvs.append(bmv)
        #                 bmv = path[bmv]
        #             side_bmvs.reverse()
        #             side_inds = [ bmv.index for bmv in side_bmvs ]
        #             Patches_Logic.sides.append(side_inds)
        #             continue

        #         for bme in bmv.link_edges:
        #             if not bme.select or bme.hide or bme in touched_bmes:
        #                 continue
        #             touched_bmes.add(bme)
        #             v2 = bme.other_vert(bmv)
        #             if not v2 or v2 in touched:
        #                 continue
        #             path[v2] = bmv
        #             walking_queue.append(v2)
        # print(Patches_Logic.sides)


    @staticmethod
    def insert_corner(context : Context, event : Event, *, radius2d : float = 10) -> bool:
        obj = context.edit_object
        if not obj:
            return False

        M = obj.matrix_world
        rgn, r3d = context.region, context.region_data
        mouse = mouse_from_event(event)
        raycast = Raycast(context, mouse, respect_clip_planes=True)
        if not raycast.hit:
            return False

        co_local = raycast.co_local
        distance = raycast.distance

        def proj(p : Vector) -> Vector | None:
            return location_3d_to_region_2d(rgn, r3d, M @ p)

        m : Vector | None = proj(co_local)  # should be same as mouse
        assert m
        radius3d : float = radius2d * (size2D_to_size(context, distance, pt=mouse) or 1)

        bm, em = get_bmesh_emesh(bpy.context, ensure_lookup_tables=True)
        bvh = BVHTree.FromBMesh(bm)

        if Patches_Logic.loose_bmv_indices is None:
            Patches_Logic.loose_bmv_indices = {
                bmv.index
                for bmv in bm.verts
                if not bmv.link_faces
            }

        best_idx_bmv : INDEX_BMVERT = -1
        best_idx_new : INDEX_CORNER_NEW = -1
        best_d2d : float = radius2d * radius2d

        def test(co : Vector, idx_bmv : INDEX_BMVERT, idx_new : INDEX_CORNER_NEW):
            nonlocal best_idx_bmv, best_idx_new, best_d2d

            p = proj(co)
            if not p:
                return

            d2d = (m - p).length_squared
            if d2d >= best_d2d:
                return

            best_idx_bmv = idx_bmv
            best_idx_new = idx_new
            best_d2d = d2d

        # check if any BMVert with at least one BMFace is under mouse
        for (_co, _no, fidx, _d3d) in bvh.find_nearest_range(co_local, radius3d):
            for bmv in bm.faces[fidx].verts:
                if not bmv.hide:
                    test(bmv.co, bmv.index, -1)

        # check if any BMVert without any BMFace is under mouse
        if Patches_Logic.loose_bmv_indices:
            for idx_bmv in Patches_Logic.loose_bmv_indices:
                if not (bmv := bm.verts[idx_bmv]).hide:
                    test(bmv.co, bmv.index, -1)

        # check if any new corner is under mouse
        for (idx_new, co) in enumerate(Patches_Logic.corners_new):
            test(co, -1, idx_new)

        # check if we found a BMVert or new corner under mouse
        if best_idx_bmv >= 0:
            # found a BMVert under mouse, so check if it is a corner
            if best_idx_bmv in Patches_Logic.corners_bmv:
                # remove BMVert as corner (do not deselect...)
                Patches_Logic.corners_bmv.discard(best_idx_bmv)
            else:
                # add BMVert as corner by (re)selecting it
                Patches_Logic.corners_bmv.add(best_idx_bmv)
                bmv = bm.verts[best_idx_bmv]
                bmops.reselect(bm, bmv)         # reselect so it is active
                bmops.flush_selection(bm, em)   # depsgraph will update...

        elif best_idx_new >= 0:
            # found a new corner under mouse, so remove it
            Patches_Logic.corners_new = (
                Patches_Logic.corners_new[:best_idx_new] +
                Patches_Logic.corners_new[best_idx_new+1:]
            )

        else:
            # cound not find corner under mouse, so add it
            Patches_Logic.corners_new.append(co_local)

        Patches_Logic.update(just_modified_corners=True)
        return True

    @staticmethod
    def draw():
        context = bpy.context
        rgn, r3d = context.region, context.region_data

        def proj(pt_world : Vector) -> Vector | None:
            return location_3d_to_region_2d(rgn, r3d, pt_world)

        edit_object = context.edit_object
        if not edit_object:
            return

        M = edit_object.matrix_world
        bm = bmesh.from_edit_mesh(cast(Mesh, edit_object.data))

        theme = bpy.context.preferences.themes[0].view_3d
        props = RF_Prefs.get_prefs(context)
        highlight = cast(Vector, props.highlight_color)
        color_point = Color4((highlight[0], highlight[1], highlight[2], 1))
        color_unused = Color4((1, 0, 0, 1))
        color_border_open = Color4((highlight[0], highlight[1], highlight[2], 1.0))
        color_stipple = Color4((theme.face_select[0], theme.face_select[1], theme.face_select[2], 0))
        color_mesh = theme.face_select
        vertex_size = theme.vertex_size

        # draw patch
        if (patch := Patches_Logic.patch):
            with Drawing.draw(context, CC_2D_LINES) as draw:
                draw.line_width(2)
                draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                draw.color(color_border_open)

                for (pt0, pt1) in patch.edges:
                    _ = draw.vertex(proj(pt0))
                    _ = draw.vertex(proj(pt1))

            with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                draw.color(color_mesh)

                for pts in patch.faces:
                    p0 = pts[0]
                    for (p1, p2) in iter_pairs(pts[1:], False):
                        _ = draw.vertex(proj(p0))
                        _ = draw.vertex(proj(p1))
                        _ = draw.vertex(proj(p2))

        # draw corners
        with Drawing.draw(context, CC_2D_POINTS) as draw:
            # draw BMVert corners
            for idx_bmv in Patches_Logic.corners_bmv:
                if idx_bmv in Patches_Logic.used_bmv:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_point)
                    _ = draw.vertex(proj(M @ bm.verts[idx_bmv].co))
                else:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_unused)
                    _ = draw.vertex(proj(M @ bm.verts[idx_bmv].co))
                    draw.point_size(vertex_size + 1)
                    draw.color(color_point)
                    _ = draw.vertex(proj(M @ bm.verts[idx_bmv].co))

            # draw new corners
            for (idx_new, co) in enumerate(Patches_Logic.corners_new):
                if idx_new in Patches_Logic.used_new:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_point)
                    _ = draw.vertex(proj(M @ co))
                else:
                    draw.point_size(vertex_size + 4)
                    draw.color(color_unused)
                    _ = draw.vertex(proj(M @ co))
                    draw.point_size(vertex_size + 1)
                    draw.color(color_point)
                    _ = draw.vertex(proj(M @ co))

        # draw sides
        for side in Patches_Logic.sides:
            n_verts = len(side)
            i0 = (n_verts - 1) // 2
            i1 = (i0 + 1) if n_verts % 2 == 0 else i0
            co = (bm.verts[side[i0]].co + bm.verts[side[i1]].co) / 2
            p = proj(M @ co)
            if p:
                Drawing.text_draw2D(
                    f'{n_verts - 1}',
                    p,
                    color=(1,1,0,1),
                    dropshadow=(0,0,0,1),
                )

    @staticmethod
    def commit():
        if not Patches_Logic.patch:
            return
        context = bpy.context
        edit_object = context.edit_object
        assert edit_object
        M = edit_object.matrix_world
        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        Patches_Logic.patch.commit(bm, M)
        bmops.flush_selection(bm, em) # depsgraph will update...
