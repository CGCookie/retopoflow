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
from typing import ClassVar, cast
from collections import deque
from itertools import chain

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from mathutils import Vector, Matrix

from ..rfglobals import RFGlobals

from ..preferences import RF_Prefs

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import Vec
from ...addon_common.common.unionfind import UnionFind
from ...addon_common.common.utils import iter_pairs
from ..common.bmesh import get_bmesh_emesh
from ..common.drawing import Drawing, CC_2D_LINES, CC_2D_POINTS, CC_2D_TRIANGLES
from ..common.raycast import nearest_point_normal_valid_sources

DEBUG_PRINT : bool = False


class Patch:
    verts : list[int | tuple[int, int, float, int, int, float]]
    edges : list[tuple[int, int]]
    faces : list[tuple[int, int, int, int]]
    conos : list[tuple[Vector,Vector]]

    def __init__(self, bm : BMesh, M : Matrix, sides : list[list[int]]):
        print('New Patch')

        self.verts = []
        self.conos = []
        self.edges = []
        self.faces = []

        match len(sides):
            case 4:
                self.process_quad(sides)

            case _:
                print(f'Unhandled number of sides {len(sides)}')

        self.update_pos(bm, M)

    def process_quad(self, sides : list[list[int]]):
        assert len(sides) == 4

        if len(sides[0]) != len(sides[2]) or len(sides[3]) != len(sides[1]):
            return

        w, h = len(sides[0]), len(sides[1])

        def a(i : int) -> int:
            return sides[0][i]
        def b(j : int) -> int:
            return sides[1][j]
        def c(i : int) -> int:
            return sides[2][w-1-i]
        def d(j : int) -> int:
            return sides[3][h-1-j]

        for j in range(h):
            for i in range(w):
                if j == 0:
                    self.verts.append(a(i))
                elif j == h - 1:
                    self.verts.append(c(i))
                elif i == 0:
                    self.verts.append(d(j))
                elif i == w - 1:
                    self.verts.append(b(j))
                else:
                    self.verts.append((
                        a(i), c(i), j / (h - 1),
                        d(j), b(j), i / (w - 1),
                    ))

        for j in range(h):
            for i in range(w - 1):
                self.edges.append((
                    j * w + (i + 0),
                    j * w + (i + 1),
                ))
        for j in range(h - 1):
            for i in range(w):
                self.edges.append((
                    (j + 0) * w + i,
                    (j + 1) * w + i,
                ))

        for j in range(h - 1):
            for i in range(w - 1):
                self.faces.append((
                    (j + 0) * w + (i + 0),
                    (j + 0) * w + (i + 1),
                    (j + 1) * w + (i + 1),
                    (j + 1) * w + (i + 0),
                ))

    def update_pos(self, bm : BMesh, M : Matrix):
        context = bpy.context

        for vert in self.verts:
            p : Vector

            match vert:
                case int() as i:
                    p = bm.verts[i].co

                case (ia, ic, fac, id, ib, fdb):
                    a, c = bm.verts[ia].co, bm.verts[ic].co
                    d, b = bm.verts[id].co, bm.verts[ib].co
                    ac = a + (c - a) * fac
                    db = d + (b - d) * fdb
                    p = ac + (db - ac) * 0.5

            cono = nearest_point_normal_valid_sources(context, M @ p)
            assert cono
            self.conos.append(cono)

    def commit(self, bm : BMesh, M : Matrix):
        Mi = M.inverted_safe()

        verts0 = [
            bm.verts[i] if isinstance(i, int) else None
            for i in self.verts
        ]
        verts1 = [
            bmv if bmv else bm.verts.new(Mi @ cono[0])
            for (bmv, cono) in zip(verts0, self.conos)
        ]

        for f in self.faces:
            bmf = bm.faces.new([ verts1[i] for i in f ])
            bmf.normal_update()
            no = Vec.average([ self.conos[i][1] for i in f ])
            if bmf.normal.dot(no) < 0:
                bmf.normal_flip()

        self.verts = []
        self.faces = []
        self.pos = []


class Patches_Logic:
    prev_depsgraph_version : ClassVar[int] = -42
    prev_active_index : int | None = None

    # Points that will act as corners for patch, where keys are index of BMVert
    # and values are location in world space.
    #
    # IMPORTANT: must not keep reference to bmesh elements, because they will invalidate
    #       whenever depsgraph changes!  Instead, keep track of them via their indices.
    corners : ClassVar[set[int]] = set()
    sides : ClassVar[list[list[int]]] = []
    points_world : ClassVar[dict[int, Vector]] = {}
    patch : ClassVar[Patch | None] = None

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

    @staticmethod
    def update():
        RFCore = RFGlobals.RFCore
        context = bpy.context
        edit_object = context.edit_object
        assert edit_object
        M = edit_object.matrix_world

        if Patches_Logic.prev_depsgraph_version == RFCore.depsgraph_version:
            bm, _ = get_bmesh_emesh(context)
            active = bm.select_history.active
            a = active.index if isinstance(active, BMVert) else None
            if Patches_Logic.prev_active_index == a:
                return

            print('same depsgraph but different active')
            print(f'  {Patches_Logic.prev_active_index} {a}')
            Patches_Logic.prev_active_index = a

        else:
            print('depsgraph changed')

        Patches_Logic.prev_depsgraph_version = RFCore.depsgraph_version
        bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)

        len_verts = len(bm.verts)

        # same number of BMVerts or just inserted BMVert (Patches_Logic.insert_corner)
        if isinstance(bmv_active := bm.select_history.active, BMVert):
            # add active element to collection of corner BMVerts
            Patches_Logic.corners.add(bmv_active.index)

        # keep only corners that are still selected
        Patches_Logic.corners = {
            i
            for i in Patches_Logic.corners
            if i < len_verts and (bmv := bm.verts[i]) and bmv.select
        }
        Patches_Logic.patch = None
        Patches_Logic.update_sides(bm)
        Patches_Logic.points_world = {
            i: (M @ bmv.co) # update positions because they might have moved
            for i in chain(Patches_Logic.corners, *Patches_Logic.sides)
            if (bmv := bm.verts[i]) and bmv.select
        }
        Patches_Logic.patch = Patch(bm, M, Patches_Logic.sides)


    @staticmethod
    def update_sides(bm : BMesh):
        Patches_Logic.sides = []

        corners : set[BMVert] = {
            bmv for i in Patches_Logic.corners if (bmv := bm.verts[i])
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
                bme0 : BMEdge | None = next(( bme for bme in bmv0.link_edges if bme.select and not bme.hide ), None)
                if not bme0:
                    continue

                touched_corners = { bmv0 }
                touched_bmes : set[BMEdge] = set()
                sides_bmvs : list[list[BMVert]] = []
                side_bmvs : list[BMVert] = [ bmv0 ]

                while True:
                    touched_bmes.add(bme0)
                    bmv1 : BMVert | None = bme0.other_vert(bmv0)
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
                    bme1 = next(( bme for bme in bmv1.link_edges if bme.select and not bme.hide and bme not in touched_bmes ), None)
                    if not bme1:
                        break
                    bmv0, bme0 = bmv1, bme1
            return cycle

        if (cycle_sides := get_biggest_cycle()):
            # need at least 1 side to be a cycle
            if len(cycle_sides) > 1:
                print('found cycle')
                if cycle_sides[0][0] == cycle_sides[1][0] or cycle_sides[0][0] == cycle_sides[1][-1]:
                    # first side is reversed
                    cycle_sides[0].reverse()
                for (side0, side1) in zip(cycle_sides[:-1], cycle_sides[1:]):
                    if side0[-1] == side1[-1]:
                        # reverse side1 so side0 and side1 are in same direction
                        side1.reverse()
                Patches_Logic.sides = [
                    [ bmv.index for bmv in cycle_side ]
                    for cycle_side in cycle_sides
                ]
                return
            print('found cycle with 1 side...')

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
    def insert_corner(co_local : Vector):
        bm, em = get_bmesh_emesh(bpy.context)
        bmv = bm.verts.new(co_local)
        bmops.select(bm, bmv)
        bmops.flush_selection(bm, em) # depsgraph will update...

    @staticmethod
    def draw():
        context = bpy.context
        rgn, r3d = context.region, context.region_data

        def proj(p : Vector | None) -> Vector | None:
            return location_3d_to_region_2d(rgn, r3d, p) if p else None

        corners = Patches_Logic.corners
        points_world = Patches_Logic.points_world

        theme = bpy.context.preferences.themes[0].view_3d
        props = RF_Prefs.get_prefs(context)
        highlight = cast(Vector, props.highlight_color)
        color_point = Color4((highlight[0], highlight[1], highlight[2], 1))
        color_border_open = Color4((highlight[0], highlight[1], highlight[2], 1.0))
        color_stipple = Color4((theme.face_select[0], theme.face_select[1], theme.face_select[2], 0))
        color_mesh = theme.face_select
        vertex_size = theme.vertex_size

        with Drawing.draw(context, CC_2D_POINTS) as draw:
            draw.point_size(vertex_size + 4)
            draw.color(color_point)
            for i in corners:
                _ = draw.vertex(proj(points_world[i]))

        if (patch := Patches_Logic.patch):
            with Drawing.draw(context, CC_2D_LINES) as draw:
                draw.line_width(2)
                draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                draw.color(color_border_open)

                for (i0, i1) in patch.edges:
                    pt0, pt1 = patch.conos[i0][0], patch.conos[i1][0]
                    if not pt0 or not pt1:
                        continue
                    _ = draw.vertex(proj(pt0))
                    _ = draw.vertex(proj(pt1))

            with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
                draw.color(color_mesh)

                for f in patch.faces:
                    i0 : int = -1
                    p0 : Vector | None = None
                    for (i1, i2) in iter_pairs(f, False):
                        p1 = patch.conos[i1][0]
                        if not p1:
                            continue
                        if i0 == -1:
                            i0 = i1
                            p0 = p1
                            continue
                        p2 = patch.conos[i2][0]
                        if not p0 or not p2:
                            continue
                        _ = draw.vertex(proj(p0))
                        _ = draw.vertex(proj(p1))
                        _ = draw.vertex(proj(p2))
