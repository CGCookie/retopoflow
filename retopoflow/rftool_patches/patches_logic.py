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
from typing import ClassVar, cast, TypeAlias, Literal, TypeVar, overload
from collections.abc import Sequence, Generator
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
import time
from math import cos, radians

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
from ...addon_common.common.maths import Plane
from ...addon_common.ext.circle_fit import standardLSQ
from ..common.bmesh import get_bmesh_emesh
from ..common.drawing import Drawing, CC_2D_LINES, CC_2D_POINTS, CC_2D_TRIANGLES
from ..common.raycast import (
    nearest_point_valid_sources,
    Raycast,
    mouse_from_event,
    size2D_to_size,
)


DEBUG_PRINT : bool = False


CO_LOCAL : TypeAlias = Vector
CO_WORLD : TypeAlias = Vector
CO_SCREEN : TypeAlias = Vector
RADIUS : TypeAlias = float

LERP_WEIGHT : TypeAlias = float
INDEX_BMVERT : TypeAlias = int
INDEX_PVERT : TypeAlias = int
INDEX_CORNER_NEW : TypeAlias = int

PATCH_SIDE : TypeAlias = Sequence[INDEX_BMVERT]
PATCH_SIDES : TypeAlias = Sequence[PATCH_SIDE | None]

# Note: because some types are not yet defined or defined recursively,
#       must create special PVERT_ARG_PVERT type and quote PVERT_ARG and PVert
PVERT_ARG_PVERT : TypeAlias = TypeVar('PVERT_ARG_PVERT', bound='PVert')     # pyright: ignore[reportUnknownVariableType]
PVERT_ARG_INT : TypeAlias = INDEX_BMVERT
PVERT_ARG_LERP : TypeAlias = tuple[ Literal['lerp'], 'PVERT_ARG', 'PVERT_ARG', float ]
PVERT_ARG_AVERAGE : TypeAlias = tuple[ Literal['average'], Sequence['PVERT_ARG'] ]
PVERT_ARG_QUAD : TypeAlias = tuple[ Literal['quad'], 'PVERT_ARG', 'PVERT_ARG', 'PVERT_ARG', RADIUS ]
PVERT_ARG : TypeAlias = PVERT_ARG_PVERT | PVERT_ARG_INT | PVERT_ARG_LERP | PVERT_ARG_AVERAGE | PVERT_ARG_QUAD  # pyright: ignore[reportUnknownVariableType]
PVERT_TUPLE_ARG : TypeAlias = tuple[PVERT_ARG_PVERT] | tuple[PVERT_ARG_INT] | tuple[PVERT_ARG_LERP] | tuple[PVERT_ARG_AVERAGE] | tuple[PVERT_ARG_QUAD]

PATCH_SIDE_PVERTS : TypeAlias = list['PVert']
PATCH_SIDES_PVERTS : TypeAlias = list[PATCH_SIDE_PVERTS | None]




class PVert:
    """
    Convenience class that handles computing LERPed and snapped positions
    """

    _bm : ClassVar[BMesh | None] = None

    co : CO_LOCAL               # computed location of PVert
    idx : INDEX_BMVERT = -1     # -1 indicates that PVert is not based on BMVert

    @contextmanager
    @staticmethod
    def create(bm : BMesh) -> Generator[None, None, None]:
        try:
            PVert._bm = bm
            yield None
        finally:
            PVert._bm = None


    ##################################################################################
    # These __new__ methods provide type hinting for the various ways of creating    #
    # new PVert objects (specialized constructors).                                  #
    # Note: new PVerts must be created inside the PVert.create context manager!      #
    ##################################################################################

    @overload
    def __new__(cls,
        pvert : PVert,
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        idx : INDEX_BMVERT,
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        lerp : Literal['lerp'],
        pt0 : PVERT_ARG,    # pyright: ignore[reportUnknownParameterType]
        pt1 : PVERT_ARG,    # pyright: ignore[reportUnknownParameterType]
        weight: float,
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        average : Literal['average'],
        *pts : PVERT_ARG,   # pyright: ignore[reportUnknownParameterType]
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        quad : Literal['quad'],
        pt0 : PVERT_ARG,   # pyright: ignore[reportUnknownParameterType]
        pt1 : PVERT_ARG,   # pyright: ignore[reportUnknownParameterType]
        pt2 : PVERT_ARG,   # pyright: ignore[reportUnknownParameterType]
        radius : RADIUS,
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        tupled_args : PVERT_TUPLE_ARG,  # pyright: ignore[reportUnknownParameterType]
    ) -> PVert:
        ...

    def __new__(cls,        # pyright: ignore[reportInconsistentOverload]
        *args : ...,        # pyright: ignore[reportAny]
    ) -> PVert:
        """
        foo
        """
        bm = PVert._bm
        assert bm, 'Must create new PVerts inside the PVert.create(bmesh) context manager'

        assert args, 'Must specify at least one, but no arguments specified'

        match args[0]:
            case tuple():
                assert len(args) == 1, f'Expected one argement for tuple, but instead saw {len(args)}: {args}'
                return PVert(*args[0])

            case PVert() as pvert:
                return pvert

            case int() as idx:
                pvert = super().__new__(cls)
                pvert.co = bm.verts[idx].co
                pvert.idx = idx
                return pvert

            case 'lerp':
                assert len(args) == 4, f'Expected three arguments for lerp (pt0, pt1, weight), but instead saw {args[1:]}'
                pvert0 = PVert(args[1])         # pyright: ignore[reportAny]
                pvert1 = PVert(args[2])         # pyright: ignore[reportAny]
                weight = cast(float, args[3])
                pvert = super().__new__(cls)
                pvert.co = pvert0.co + (pvert1.co - pvert0.co) * weight
                return pvert

            case 'average':
                assert len(args) > 2, f'Expected at least arguments for lerp, but instead saw {args}'
                pverts = [ PVert(arg) for arg in args[1:] ]     # pyright: ignore[reportAny]
                pvert = super().__new__(cls)
                pvert.co = sum((pv.co for pv in pverts), Vector((0,0,0))) / max(1, len(pverts))
                return pvert

            case 'quad':
                assert len(args) == 5, f'Expected four arguments for quad (pt0, pt1, pt2, radius), but instead saw {args[1:]}'
                pvert0 = PVert(args[1])         # pyright: ignore[reportAny]
                pvert1 = PVert(args[2])         # pyright: ignore[reportAny]
                pvert2 = PVert(args[3])         # pyright: ignore[reportAny]
                radius = cast(float, args[4])
                pvert = super().__new__(cls)
                co0, co1, co2 = pvert0.co, pvert1.co, pvert2.co
                com = co0 + (co2 - co0) / 2
                vec1m = (com - co1)
                len1m = vec1m.length
                vec10, vec12 = (co0 - co1), (co2 - co1)
                len10, len12 = vec10.length, vec12.length
                lenavg = (len10 + len12) / 2
                scale = abs(radius * 2 - lenavg) / (radius * 2 + lenavg)
                # print(f'{lenavg=} {radius=}  abs({radius*2-lenavg=}) / ({radius*2+lenavg=}) = {scale} ')

                co3_0 = co1 + vec1m * (2 * scale)
                co3_1 = co1 + vec1m * (lenavg * scale / len1m)

                # cos(  0°) =  1 -> 1
                # cos( 90°) =  0 -> 0
                # cos(180°) = -1 -> 1
                cos_angle = (vec12 / len12).dot(vec10 / len10)
                weight = abs(cos_angle)

                co3 = co3_0 + (co3_1 - co3_0) * weight
                pvert.co = co3
                return pvert

            case _: # pyright: ignore[reportAny]
                assert False, f'Unhandled arguments {args}'


    @property
    def from_bmvert(self) -> bool:
        return self.idx >= 0

    def bmv(self, bm : BMesh) -> BMVert | None:
        return bm.verts[self.idx] if self.idx >= 0 else None


@dataclass
class Relax_Options:
    enabled : bool = False
    iterations : int = 100
    scale_edge : float = 0.05
    scale_face : float = 0.01


class Patch:
    _plane : Plane

    # vertices of patch, either as index of BMVert (int) or as LERP of BMVerts (tuple of inds and weights)
    # Note: these are indices into bm.verts
    _verts : list[PVert]

    # edges and faces that make up patch as indices into _verts
    # Note: these are indices into Patch._verts, **NOT** bm.verts or bm.edges or bm.faces
    _edges : list[Sequence[INDEX_PVERT]]    # always exactly two indices
    _faces : list[Sequence[INDEX_PVERT]]

    # snapped co in world space of each vert, edge, face of patch
    verts : list[CO_WORLD]
    edges : list[Sequence[CO_WORLD]]    # always exactly two vectors
    faces : list[Sequence[CO_WORLD]]

    def __init__(
        self,
        bm : BMesh,
        M : Matrix,
        sides : PATCH_SIDES,
        *,
        relax_options : Relax_Options | None = None
    ):
        print(f'Patch({sides})')
        self.reset()

        if not sides:
            return

        with PVert.create(bm):
            # create initial PVerts
            sides_pverts = [
                [ PVert(idx) for idx in side ] if side else None
                for side in sides
            ]

            plane = Plane.fit_to_points([pv.co for side in sides_pverts if side for pv in side])
            if not plane:
                return
            self._plane = plane

            match sides_pverts:
                case (side, ):                                              # loop with no corners
                    assert side
                    # self._fill_central(side)
                    # self._fill_parallel(side)
                    sides_pverts = self._border(sides_pverts)
                    sides_pverts = self._border(sides_pverts)
                    sides_pverts = self._border(sides_pverts)

                case (side, None):                                          # loop with 1 corner (teardrop)
                    assert side
                    pass

                case (side_a, side_b):                                      # 2-sided loop (2 corners)
                    assert side_a and side_b
                    self._process_2_sided(side_a, side_b)

                case (side_a, side_b, side_c):                              # 3-sided loop (3 corners)
                    assert side_a and side_b and side_c
                    self._process_3_sided(side_a, side_b, side_c)

                case (side_a, side_b, side_c, side_d):
                    assert side_a and side_b and side_c and side_d          # 4-sided loop (4 corners)
                    self._process_4_sided(side_a, side_b, side_c, side_d)

                case _:
                    print(f'Unhandled number of sides {len(sides)}')

        self._snap_and_relax(M, relax_options)

        self.verts = [ M @ pv.co for pv in self._verts ]
        self.edges = [ (self.verts[i0], self.verts[i1]) for (i0, i1) in self._edges ]
        self.faces = [ tuple(self.verts[i] for i in f) for f in self._faces ]


    def _snap_and_relax(self, M : Matrix, relax_options : Relax_Options | None):
        print('snapping...')
        context = bpy.context
        Mi = M.inverted_safe()

        def snap(co_local : CO_LOCAL) -> CO_LOCAL:
            co_world = M @ co_local
            co_snapped_world = nearest_point_valid_sources(context, co_world) or co_world
            co_snapped_local = Mi @ co_snapped_world
            return co_snapped_local

        verts = [ snap(pvert.co) for pvert in self._verts ]

        if relax_options and relax_options.enabled:
            print('relaxing....')
            t0 = time.time()
            def get_info(inds : Sequence[int]) -> tuple[CO_LOCAL, RADIUS]:
                vs = [ verts[i] for i in inds ]
                center = sum(vs, Vector((0,0,0))) / len(vs)
                radius = sum((v - center).length for v in vs) / len(vs)
                return (center, radius)

            fixed = [ pvert.from_bmvert for pvert in self._verts ]
            link_edges : dict[INDEX_PVERT, list[int]] = { i: [] for i in range(len(verts)) }
            for (i_edge, inds) in enumerate(self._edges):
                for i in inds:
                    link_edges[i].append(i_edge)
            link_faces : dict[INDEX_PVERT, list[int]] = { i: [] for i in range(len(verts)) }
            for (i_face, inds) in enumerate(self._faces):
                for i in inds:
                    link_faces[i].append(i_face)

            for _iteration in range(relax_options.iterations):
                edge_infos = [ get_info(inds) for inds in self._edges ]
                face_infos = [ get_info(inds) for inds in self._faces ]

                forces = [Vector((0,0,0)) for _ in verts]

                for (i, co) in enumerate(verts):
                    goal = sum(edge_infos[i_edge][1] for i_edge in link_edges[i]) / len(link_edges[i])
                    for i_edge in link_edges[i]:
                        center = edge_infos[i_edge][0]
                        vec_center_co = co - center
                        current = vec_center_co.length
                        dir_center_co = vec_center_co / max(0.00001, current)
                        forces[i] += dir_center_co * (relax_options.scale_edge * (goal - current))

                for inds, info in zip(self._faces, face_infos):
                    center, R = info
                    r = R * cos(radians(180 / len(inds)))
                    goal = r
                    for (i0, i1) in iter_pairs(inds, True):
                        co0, co1 = verts[i0], verts[i1]
                        com = co0 + (co1 - co0) / 2

                        vec_center_com = com - center
                        current = vec_center_com.length
                        dir_center_com = vec_center_com / max(0.00001, current)
                        forces[i0] += dir_center_com * (relax_options.scale_face * (goal - current))
                        forces[i1] += dir_center_com * (relax_options.scale_face * (goal - current))

                    for i in inds:
                        vec_center_co = verts[i] - center
                        current = vec_center_co.length
                        dir_center_co = vec_center_co / max(0.00001, current)
                        forces[i] += dir_center_co * (relax_options.scale_face * (goal - current))

                verts = [
                    co if fix else snap(co + force)
                    for (co, fix, force) in zip(verts, fixed, forces)
                ]
            t1 = time.time()
            print(f'  time: {t1-t0:0.4f}secs')

        for (pvert, co) in zip(self._verts, verts):
            pvert.co = co

    def reset(self):
        self._verts = []
        self._edges = []
        self._faces = []

        self.verts = []
        self.edges = []
        self.faces = []

    def _compute_max_radius(self, sides : PATCH_SIDES_PVERTS) -> float:
        return 0

    def _border(self, sides : PATCH_SIDES_PVERTS) -> PATCH_SIDES_PVERTS:
        if len(sides) == 1:
            assert sides[0]
            outer = sides[0][:-1]
            c = len(outer)
            center = sum((pv.co for pv in outer), Vector((0,0,0))) / c
            radius = max((pv.co - center).length for pv in outer)
            inner = [
                PVert('quad', outer[(i-1)%c], outer[i], outer[(i+1)%c], radius)
                for i in range(c)
            ]
            i_start = len(self._verts)
            self._verts.extend(outer)
            self._verts.extend(inner)
            for i in range(c):
                i0 = i_start + i
                i1 = i_start + (i + 1) % c
                i2 = i_start + (i + 1) % c + c
                i3 = i_start + i + c
                self._edges.extend([ (i0, i1), (i2, i3), (i3, i0) ])
                self._faces.append((i0, i1, i2, i3))
            return [inner + [inner[0]]]
        return sides


    def _fill_central(self, side : PATCH_SIDE_PVERTS):
        print(f'filling loop with {len(side)-1} verts using central point')

        # assuming first and last are the same!
        self._verts.extend(side[:-1])
        c = len(side) - 1

        # central point
        self._verts.append(PVert('average', *side))
        ic = c

        for i0 in range(0, c, 2):
            i1, i2 = (i0 + 1) % c, (i0 + 2) % c
            if i1 == 0:
                # handle last triangle
                self._faces.append((ic, i0, i1))
                self._edges.extend([ (i0, i1), (i1, ic) ])
            else:
                self._faces.append((ic, i0, i1, i2))
                self._edges.extend([ (i0, i1), (i1, i2), (i2, ic) ])


    def _fill_parallel(self, side : PATCH_SIDE_PVERTS):
        print(f'filling loop with {len(side)-1} verts using parallel edges')

        # assuming first and last are the same!
        self._verts.extend(side[:-1])
        c = len(side) - 1

        for i0 in range(0, (c - 1) // 2):
            i1 = i0 + 1
            i2 = (c - 1) - i0 - 1
            i3 = (c - 1) - i0
            if i0 == 0:
                self._edges.append((i3, i0))
            if i1 == i2:
                # handle last triangle
                self._faces.append((i0, i1, i3))
                self._edges.extend([ (i0, i1), (i1, i3) ])
            else:
                self._faces.append((i0, i1, i2, i3))
                self._edges.extend([ (i0, i1), (i2, i3), (i1, i2)])

    def _process_2_sided(
        self,
        side_a : PATCH_SIDE_PVERTS,
        side_b : PATCH_SIDE_PVERTS,
    ):
        if len(side_a) == len(side_b):
            # special case
            n = len(side_a)
            c0, c1 = side_a[0], side_a[-1]
            side_b = list(side_b[::-1])

            self._verts.append(PVert(c0))                       # 1
            for (a,b) in zip(side_a[1:-1], side_b[1:-1]):       # 2*(n-2)
                self._verts.append(PVert(a))
                self._verts.append(PVert(b))
            self._verts.append(PVert(c1))                       # 1
            # ................................................... above sum = 1 + 2 * (n - 2) + 1 = 2n - 2

            self._verts.append(PVert(                           # 1
                'lerp',
                c0,
                ( 'lerp', side_a[1], side_b[1], 0.5 ),
                1.5
            ))
            for (a,b) in zip(side_a[2:-2], side_b[2:-2]):       # 2*(n-4)
                self._verts.append(PVert('lerp', a, b, 0.2))
                self._verts.append(PVert('lerp', a, b, 0.8))
            self._verts.append(PVert(                           # 1
                'lerp',
                c1,
                ( 'lerp', side_a[-2], side_b[-2], 0.5 ),
                1.5
            ))
            # ................................................... above sum = 1 + 2*(n-4) + 1

            i0 = 0
            i1 = i0 + 1 + 2 * (n - 2) + 1
            for i in range(i0+1, i1-4, 2):
                self._edges += [(i, i+2), (i+1, i+3)]
            self._edges += [(i0,i0+1), (i0,i0+2), (i0+1,i1), (i0+2, i1), (i1, i1+1), (i1, i1+2)]
            j0 = 1 + 2 * (n - 2)
            j1 = j0 + 1 + 1 + 2 * (n - 4)
            self._edges += [(j0, j0-1), (j0, j0-2), (j0-1, j1), (j0-2, j1), (j1, j1-1), (j1, j1-2)]
            for i in range(0, 2*(n-4), 2):
                if i < 2 * (n - 4) - 2:
                    self._edges += [(i1+1+i, i1+3+i), (i1+2+i, i1+4+i)]
                self._edges += [(i0+4+i, i1+2+i), (i0+3+i, i1+1+i)]

            return

        print(f'Unhandled 2-sided patch: {len(side_a)}-{len(side_b)}')

    def _process_3_sided(
        self,
        side_a : PATCH_SIDE_PVERTS,
        side_b : PATCH_SIDE_PVERTS,
        side_c : PATCH_SIDE_PVERTS,
    ):
        if len(side_a) == 2 and len(side_b) == 2 and len(side_c) == 2:
            # special case
            self._verts.append(PVert(side_a[0]))
            self._verts.append(PVert(side_b[0]))
            self._verts.append(PVert(side_c[0]))
            self._edges.append((0, 1))
            self._edges.append((1, 2))
            self._edges.append((2, 0))
            self._faces.append((0, 1, 2))
            return

        if len(side_a) == 3 and len(side_b) == 3 and len(side_c) == 3:
            # special case
            a = side_a[0]
            b = side_b[0]
            c = side_c[0]
            ab = side_a[1]
            bc = side_b[1]
            ca = side_c[1]
            self._verts.append(PVert(a ))  # 0
            self._verts.append(PVert(ab))  # 1
            self._verts.append(PVert(b ))  # 2
            self._verts.append(PVert(bc))  # 3
            self._verts.append(PVert(c ))  # 4
            self._verts.append(PVert(ca))  # 5
            self._verts.append(PVert('lerp', ('lerp', ab, bc, 0.5), ca, 0.33))  # 6
            self._edges.append((0, 1))
            self._edges.append((1, 2))
            self._edges.append((2, 3))
            self._edges.append((3, 4))
            self._edges.append((4, 5))
            self._edges.append((5, 0))
            self._edges.append((1, 6))
            self._edges.append((3, 6))
            self._edges.append((5, 6))
            self._faces.append((0, 1, 6, 5))
            self._faces.append((2, 3, 6, 1))
            self._faces.append((4, 5, 6, 3))
            return

        print(f'Unhandled 3-sided patch: {len(side_a)}-{len(side_b)}-{len(side_c)}')


    def _process_4_sided(
        self,
        side_a : PATCH_SIDE_PVERTS,
        side_b : PATCH_SIDE_PVERTS,
        side_c : PATCH_SIDE_PVERTS,
        side_d : PATCH_SIDE_PVERTS,
    ):
        # can only process 4-sided patch if opposite sides have same number of verts/edges
        if len(side_a) != len(side_c) or len(side_b) != len(side_d):
            print(f'Unhandled 4-sided patch: {len(side_a)}-{len(side_b)}-{len(side_c)}-{len(side_d)}')
            return

        w, h = len(side_a), len(side_b)

        def a(i : int) -> PVert: return side_a[i]
        def b(j : int) -> PVert: return side_b[j]
        def c(i : int) -> PVert: return side_c[w-1-i]
        def d(j : int) -> PVert: return side_d[h-1-j]

        # gather info about verts of patch
        for j in range(h):
            for i in range(w):
                if j == 0:
                    # along top side (A)
                    self._verts.append(PVert(a(i)))
                elif i == w - 1:
                    # along right side (B)
                    self._verts.append(PVert(b(j)))
                elif j == h - 1:
                    # along bottom side (C)
                    self._verts.append(PVert(c(i)))
                elif i == 0:
                    # along left side (D)
                    self._verts.append(PVert(d(j)))
                else:
                    # somewhere in the middle of patch (not along side)
                    self._verts.append(PVert(
                        'lerp',
                        ('lerp', a(i), c(i), j / (h - 1)),
                        ('lerp', d(j), b(j), i / (w - 1)),
                        0.5,
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

        # collect all existing BMVerts (note: PVert.bmv returns None if PVert was not from BMVert)
        # IMPORTANT: must do this before creating new BMVerts so we don't trigger invalidation of indices
        verts_existing = [ v.bmv(bm) for v in self._verts ]

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
    corners_new : ClassVar[list[CO_LOCAL]]        = []      # corners as local-space coordinates (new BMVerts)
    used_bmv    : ClassVar[set[INDEX_BMVERT]]     = set()   # indices of corner BMVerts that are used in >= sides (NOT index into corners_bmv, which is a set)
    used_new    : ClassVar[set[INDEX_CORNER_NEW]] = set()   # indices of corners_new that are used in >= sides

    # detected sides of patch, where ends of each side is a corner
    sides       : ClassVar[list[list[INDEX_BMVERT] | None]] = []

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
        Patches_Logic.patch = Patch(bm, M, Patches_Logic.sides, relax_options=Relax_Options())


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

        #####################################################################################
        # first, see if there is a selected cycle with at least one corner

        def get_biggest_cycle_with_corners() -> list[list[BMVert]] | None:
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

            return cycle

        if (cycle_sides := get_biggest_cycle_with_corners()):
            print(f'found cycle with {len(cycle_sides)} sides')

            if len(cycle_sides) >= 2:
                # make sure directions of sides are consistent
                if cycle_sides[0][0] == cycle_sides[1][0] or cycle_sides[0][0] == cycle_sides[1][-1]:
                    # first side is reversed
                    cycle_sides[0].reverse()
                for (side0, side1) in zip(cycle_sides[:-1], cycle_sides[1:]):
                    if side0[-1] == side1[-1]:
                        # reverse side1 so side0 and side1 are in same direction
                        side1.reverse()

            # check that cycle is correct direction
            bmvs = [ side[0] for side in cycle_sides ] if len(cycle_sides) > 1 else cycle_sides[0]
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
            if len(Patches_Logic.sides) == 1:
                Patches_Logic.sides.append(None)

            Patches_Logic.used_bmv = {
                bmv.index
                for cycle_side in cycle_sides
                for bmv in [cycle_side[0], cycle_side[-1]]
            }

            return


        #####################################################################################
        # next, see if there is a selected cycle with no corners

        def get_biggest_cycle_with_no_corners() -> list[BMVert] | None:
            cycle : list[BMVert] | None = None

            for bmv_init in bmops.get_all_selected_bmverts(bm):
                bmv0 = bmv_init
                for bme0 in bmv0.link_edges:
                    if bme0.hide or not bme0.select:
                        continue

                    touched_bmes : set[BMEdge] = { bme0 }
                    side_bmvs : list[BMVert] = [ bmv0 ]

                    while True:
                        bmv1 = bme0.other_vert(bmv0)
                        if not bmv1:
                            break

                        side_bmvs.append(bmv1)

                        if bmv1 == bmv_init:
                            # possible to not touch all corners!
                            # return sides_bmvs if len(touched_corners) == len(corners) else None
                            if not cycle or len(cycle) < len(side_bmvs):
                                cycle = side_bmvs
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

            return cycle

        if (cycle_side := get_biggest_cycle_with_no_corners()):
            cycle_sides = [cycle_side]
            print(f'found cycle with {len(cycle_side)} verts and no corners')

            # check that cycle is correct direction
            bmvs = cycle_side
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
                cycle_sides[0].reverse()

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

            return


        #####################################################################################
        # finally, see if there exists a broken cycle from corners, including either
        # selected edges between corners or a side that needs to be created
        #
        #          NOT YET IMPLEMENTED!

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

        def proj(p : CO_LOCAL) -> CO_SCREEN | None:
            return location_3d_to_region_2d(rgn, r3d, M @ p)

        m : CO_SCREEN | None = proj(co_local)  # should be same as mouse
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

        def test(co : CO_LOCAL, idx_bmv : INDEX_BMVERT, idx_new : INDEX_CORNER_NEW):
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

        def proj(pt_world : CO_WORLD) -> CO_SCREEN | None:
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
            if not side:
                continue
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
