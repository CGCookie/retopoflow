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
from enum import IntEnum
from typing import ClassVar, cast, TypeAlias, Literal, TypeVar, overload
from collections.abc import Sequence, Generator, Iterator
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, replace
from itertools import combinations
import math
import time
from math import cos, radians

import bpy
from bpy.types import Mesh, Context, Event
from bpy_extras.view3d_utils import location_3d_to_region_2d
import bmesh
from bmesh.types import BMesh, BMVert, BMEdge, BMLayerItem
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
from ..common.bmesh import get_bmesh_emesh, BMVertLayer_IntEnum
from ..common.drawing import Drawing, CC_2D_LINES, CC_2D_POINTS, CC_2D_TRIANGLES
from ..common.raycast import (
    nearest_point_valid_sources,
    nearest_point_normal_valid_sources,
    Raycast,
    mouse_from_event,
    size2D_to_size,
)


DEBUG_PRINT : bool = False

TANGENT_RADIUS : float = 12


CO_ANY : TypeAlias = Vector
CO_LOCAL : TypeAlias = Vector
CO_WORLD : TypeAlias = Vector
CO_SCREEN : TypeAlias = Vector
NO_LOCAL : TypeAlias = Vector

RADIANS : TypeAlias = float
RADIUS : TypeAlias = float

FACTOR : TypeAlias = float  # [0, 1]
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


class Corner(IntEnum):
    UNSET  =  0 # indicates the Corner has not been set
    INNER  =  1 # inner patch corner, will become corner of 3x quads
    BRIDGE =  2 # default, not a corner, will only bridge between 2x quads
    OUTER  =  3 # outer patch corner, will become corner of 1x quad

corner_toggle = {
    Corner.UNSET:  Corner.OUTER,  # treat UNSET similar to BRIDGE

    Corner.INNER:  Corner.BRIDGE,
    Corner.BRIDGE: Corner.OUTER,
    Corner.OUTER:  Corner.INNER,
}

CornerLayer : TypeAlias = BMVertLayer_IntEnum[Corner]


class Cap(IntEnum):
    PARALLEL = 0
    CENTRAL_QUADS = 1
    CENTRAL_TRIS = 2
    NGON = 3

cap_toggle = {
    Cap.PARALLEL: Cap.CENTRAL_QUADS,
    Cap.CENTRAL_QUADS: Cap.CENTRAL_TRIS,
    Cap.CENTRAL_TRIS: Cap.NGON,
    Cap.NGON: Cap.PARALLEL,
}



# class CornerLayer(BMVertLayer_Int):
#     @staticmethod
#     def remove(bm : BMesh): # pyright: ignore[reportIncompatibleMethodOverride]
#         BMVertLayer_Int.remove(bm, 'rf_patch_corner')

#     def __init__(self, bm : BMesh):
#         super().__init__(bm, 'rf_patch_corner')

#     def __getitem__(self, bmv: BMVert) -> Corner:
#         try:
#             return Corner(super()[bmv])
#         except ValueError:
#             return Corner.BRIDGE

#     def __setitem__(self, bmv : BMVert, corner : Corner): # pyright: ignore[reportIncompatibleMethodOverride]
#         super()[bmv] = corner

#     def __iter__(self) -> Iterator[tuple[BMVert, Corner]]:
#         yield from (
#             (bmv, Corner(corner))
#             for (bmv, corner) in super()
#         )

def find_circle(p0 : CO_ANY, p1 : CO_ANY, p2 : CO_ANY) -> tuple[CO_ANY, RADIUS]:
    ''' Circumcenter/radius of the circle through p0, p1, p2 (any 3 points, coplanar by definition).
        Uses the barycentric-coordinate circumcenter formula, which works in 3D as well as 2D. '''
    v01, v02 = p1 - p0, p2 - p0
    n = v01.cross(v02)
    c = p0 + (n.cross((v01 * v02.length_squared) - (v02 * v01.length_squared))) / (2 * n.length_squared)
    r = (c - p0).length
    return (c, r)

def find_sphere_circle(p0 : CO_ANY, p1 : CO_ANY, p2 : CO_ANY, p3 : CO_ANY) -> tuple[CO_ANY, RADIUS]:
    ''' Finds the sphere passing through all four given points.
        If the points are (nearly) coplanar, no finite sphere exists, so the
        circumcircle of the points is returned instead (center lies in their plane). '''
    a, b, c = p1 - p0, p2 - p0, p3 - p0
    cross_bc = b.cross(c)
    triple = a.dot(cross_bc)

    if abs(triple) < 1e-9 or True:
        # nearly planar, so find circle instead
        best_center, best_radius = Vector(), float('inf')
        for (q0, q1, q2) in [(p0,p1,p2), (p0,p1,p3), (p0,p2,p3), (p1,p2,p3)]:
            center, radius = find_circle(q0, q1, q2)
            if radius < best_radius:
                best_center, best_radius = center, radius
        return (best_center, best_radius)

    numerator = (
        a.length_squared * cross_bc
        + b.length_squared * c.cross(a)
        + c.length_squared * a.cross(b)
    )
    center = p0 + numerator / (2.0 * triple)
    radius = (center - p0).length
    return (center, radius)

def compute_angle(ring : list[PVert], index : INDEX_PVERT) -> RADIANS:
    c = len(ring)
    i0, i1, i2 = (index - 1) % c, (index + 0) % c, (index + 1) % c
    co0, co1, co2 = ring[i0].co, ring[i1].co, ring[i2].co
    v10, v12 = co0 - co1, co2 - co1
    angle = v10.angle(v12, float('inf'))
    if ring[i1].no.dot(v12.cross(v10)) > 0:
        angle = 2.0 * math.pi - angle
    return angle

def get_ring_radius(ring : list[PVert], i0 : INDEX_PVERT, *, index_pad : int = 0) -> RADIUS:
    c = len(ring)
    if c < 4:
        return float('inf')
    return min(
        find_sphere_circle(
            ring[i0 % c].co,
            ring[(i0 + io1) % c].co,
            ring[(i0 + io2) % c].co,
            ring[(i0 + io3) % c].co,
        )[1]
        for io1 in range(1 + index_pad + 0,   c - index_pad)
        for io2 in range(1 + index_pad + io1, c - index_pad)
        for io3 in range(1 + index_pad + io2, c - index_pad)
    )



class PVert:
    """
    Convenience class that handles computing LERPed and snapped positions
    """

    _bm : ClassVar[BMesh | None] = None
    _layer : ClassVar[CornerLayer | None] = None
    _M  : ClassVar[Matrix | None] = None
    _Mi : ClassVar[Matrix | None] = None
    _Mt : ClassVar[Matrix | None] = None

    corner : Corner = Corner.UNSET
    idx : INDEX_BMVERT = -1     # BMVert index or -1 to indicate new
    _co : CO_LOCAL              # computed, snapped location of PVert
    _no : NO_LOCAL              # computed. snapped normal of PVert

    @contextmanager
    @staticmethod
    def create(bm : BMesh, layer : CornerLayer, M : Matrix) -> Generator[None, None, None]:
        try:
            PVert._bm  = bm
            PVert._layer = layer
            PVert._M   = M  # pyright: ignore[reportConstantRedefinition]
            PVert._Mi  = M.inverted_safe()
            PVert._Mt  = M.transposed()
            yield None
        finally:
            PVert._bm = None
            PVert._layer = None


    ##################################################################################
    # These __new__ methods provide type hinting for the various ways of creating    #
    # new PVert objects (specialized constructors).                                  #
    # Note: new PVerts must be created inside the PVert.create context manager!      #
    ##################################################################################

    @overload
    def __new__(cls,
        pvert : PVert,
        *,
        corner : Corner = Corner.UNSET,
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        bmv : BMVert,
        *,
        corner : Corner = Corner.UNSET,
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        index : INDEX_BMVERT,
        *,
        corner : Corner = Corner.UNSET,
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        tupled_args : PVERT_TUPLE_ARG,  # pyright: ignore[reportUnknownParameterType]
        *,
        corner : Corner = Corner.UNSET,
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        lerp : Literal['lerp'],
        pt0 : PVERT_ARG,    # pyright: ignore[reportUnknownParameterType]
        pt1 : PVERT_ARG,    # pyright: ignore[reportUnknownParameterType]
        weight: float,
        *,
        corner : Corner = Corner.UNSET,
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        average : Literal['average'],
        *pts : PVERT_ARG,   # pyright: ignore[reportUnknownParameterType]
        corner : Corner = Corner.UNSET,
    ) -> PVert:
        ...

    @overload
    def __new__(cls,
        quad : Literal['quad'],
        pt0 : PVERT_ARG,   # pyright: ignore[reportUnknownParameterType]
        pt1 : PVERT_ARG,   # pyright: ignore[reportUnknownParameterType]
        pt2 : PVERT_ARG,   # pyright: ignore[reportUnknownParameterType]
        radius : RADIUS,
        *,
        corner : Corner = Corner.UNSET,
    ) -> PVert:
        ...

    def __new__(cls,        # pyright: ignore[reportInconsistentOverload]
        *args : ...,        # pyright: ignore[reportAny]
        corner : Corner = Corner.UNSET,
    ) -> PVert:
        """
        Specialized constructor dunder function, which handles a variety of
        constructor configurations, including nested / dependencies.
        """
        bm, layer = PVert._bm, PVert._layer
        assert bm and layer, 'Must create new PVerts inside the PVert.create(bmesh) context manager'

        assert args, 'Must specify at least one, but no arguments specified'

        match args[0]:
            case PVert() as pvert:
                return pvert

            case tuple():
                assert len(args) == 1, f'Expected one argement for tuple, but instead saw {len(args)}: {args}'
                pvert = PVert(*args[0])
                if corner != Corner.UNSET:
                    pvert.corner = corner
                return pvert

            case BMVert() as bmv:
                pvert = super().__new__(cls)
                pvert.corner = layer[bmv] if corner == Corner.UNSET else corner
                pvert.idx = bmv.index
                pvert.co = bmv.co
                return pvert

            case int() as index:
                bmv = bm.verts[index]
                pvert = super().__new__(cls)
                pvert.corner = layer[bmv] if corner == Corner.UNSET else corner
                pvert.idx = index
                pvert.co = bmv.co
                return pvert

            case 'lerp':
                assert len(args) == 4, f'Expected three arguments for lerp (pt0, pt1, weight), but instead saw {args[1:]}'
                pvert0 = PVert(args[1])     # pyright: ignore[reportAny]
                pvert1 = PVert(args[2])     # pyright: ignore[reportAny]
                weight = cast(float, args[3])
                pvert = super().__new__(cls)
                pvert.corner = corner
                pvert.co = pvert0.co + (pvert1.co - pvert0.co) * weight
                return pvert

            case 'average':
                assert len(args) > 2, f'Expected at least arguments for lerp, but instead saw {args}'
                pverts = [ PVert(arg) for arg in args[1:] ]    # pyright: ignore[reportAny]
                pvert = super().__new__(cls)
                pvert.corner = corner
                pvert.co = sum((pv.co for pv in pverts), Vector((0,0,0))) / max(1, len(pverts))
                return pvert

            case 'quad':
                assert len(args) == 5, f'Expected four arguments for quad (pt0, pt1, pt2, radius), but instead saw {args[1:]}'
                pvert0 = PVert(args[1])     # pyright: ignore[reportAny]
                pvert1 = PVert(args[2])     # pyright: ignore[reportAny]
                pvert2 = PVert(args[3])     # pyright: ignore[reportAny]
                radius = cast(float, args[4])
                co0, co1, co2 = pvert0.co, pvert1.co, pvert2.co

                v10, v12 = co0 - co1, co2 - co1
                v13 = v10 + v12

                # final direction will be weighted sum of these two directions based
                # on angle between co0-co1-co2
                # - fully d13 when angle is 90 (right angle)
                # - fully din when angle is 0 or 180
                d13 = v13.normalized()
                din = (co0 - co2).cross(pvert1.no).normalized()

                # make sure d13 is pointing toward center of patch
                if d13.dot(din) < 0:
                    d13.negate()

                d10, d12 = v10.normalized(), v12.normalized()
                weight = abs(d10.dot(d12))

                d13 = (d13 * (1 - weight) + din * weight).normalized()
                co3 = co1 + d13 * radius

                pvert = super().__new__(cls)
                pvert.corner = corner
                pvert.co = co3
                return pvert

            case _: # pyright: ignore[reportAny]
                assert False, f'Unhandled arguments {args}'

    @property
    def co(self) -> CO_LOCAL:
        return self._co

    @co.setter
    def co(self, co_local : CO_LOCAL):
        M, Mi, Mt = self._M, self._Mi, self._Mt
        assert M and Mi and Mt
        co_world = M @ co_local
        cono_snapped_world = nearest_point_normal_valid_sources(bpy.context, co_world)
        assert cono_snapped_world
        co_snapped_world, no_snapped_world = cono_snapped_world
        co_snapped_local = Mi @ co_snapped_world
        no_snapped_local = Mt @ no_snapped_world
        self._co = co_snapped_local
        self._no = no_snapped_local

    @property
    def no(self) -> NO_LOCAL:
        return self._no


    @property
    def from_bmvert(self) -> bool:
        return self.idx >= 0

    def bmv(self, bm : BMesh) -> BMVert | None:
        return bm.verts[self.idx] if self.idx >= 0 else None




@dataclass
class Patch_Options:
    outer_ring_offset : int = 0

    cap : Cap = Cap.PARALLEL
    loops : int | None = None
    loops_corners : Literal['copy', 'unset'] = 'copy'

    loops_made : int | None = None  # not user-changeable, but records most recent number of loops made

    relax_enabled : bool = False
    relax_iterations : int = 100
    relax_scale_edge : float = 0.05
    relax_scale_face : float = 0.01



class Patch:
    _rings : list[list[PVert]]

    # vertices of patch, either as index of BMVert (int) or as LERP of BMVerts (tuple of inds and weights)
    # Note: these are indices into bm.verts
    _verts : list[PVert]

    # edges and faces that make up patch as indices into _verts
    # Note: these are indices into Patch._verts, **NOT** bm.verts or bm.edges or bm.faces
    _edges : list[Sequence[INDEX_PVERT]]    # always exactly two indices
    _faces : list[Sequence[INDEX_PVERT]]

    # snapped co in world space of each vert, edge, face of patch; used for toggling and drawing
    verts : list[CO_WORLD]
    edges : list[Sequence[CO_WORLD]]    # always exactly two vectors
    faces : list[Sequence[CO_WORLD]]


    def __init__(
        self,
        bm : BMesh,
        layer : CornerLayer,
        M : Matrix,
        outer_ring : list[INDEX_BMVERT],
        options : Patch_Options,
    ):
        print(f'Patch({outer_ring})')
        self.reset()

        if not outer_ring:
            return

        o = options.outer_ring_offset % len(outer_ring)
        print(f'offsetting by {o}')
        outer_ring = outer_ring[o:] + outer_ring[:o]

        with PVert.create(bm, layer, M):
            # create initial PVerts
            ring = []
            for idx in outer_ring:
                pvert = PVert(idx)
                ring.append(pvert)
                self._verts.append(pvert)
            self._rings.append(ring)

            self.create_patch(options)


            # match sides_pverts:
            #     case (side, ):                                              # loop with no corners
            #         assert side
            #         # self._fill_parallel(side)
            #         N_BORDER_LOOPS = 3
            #         for _ in range(N_BORDER_LOOPS):
            #             factor = 1 / (N_BORDER_LOOPS + 0)
            #             sides_pverts = self._border(sides_pverts, factor)

            #         # self._fill_ngon(sides_pverts)
            #         # self._fill_central_quads(sides_pverts)
            #         # self._fill_central_tris(sides_pverts)
            #         self._fill_parallel(sides_pverts)

            #     case (side, None):                                          # loop with 1 corner (teardrop)
            #         assert side
            #         pass

            #     case (side_a, side_b):                                      # 2-sided loop (2 corners)
            #         assert side_a and side_b
            #         self._process_2_sided(side_a, side_b)

            #     case (side_a, side_b, side_c):                              # 3-sided loop (3 corners)
            #         assert side_a and side_b and side_c
            #         self._process_3_sided(side_a, side_b, side_c)

            #     case (side_a, side_b, side_c, side_d):
            #         assert side_a and side_b and side_c and side_d          # 4-sided loop (4 corners)
            #         self._process_4_sided(side_a, side_b, side_c, side_d)

            #     case _:
            #         print(f'Unhandled number of sides {len(sides)}')

        self._snap_and_relax(M, options)

        self.verts = [ M @ pv.co for pv in self._verts ]
        self.edges = [ (self.verts[i0], self.verts[i1]) for (i0, i1) in self._edges ]
        self.faces = [ tuple(self.verts[i] for i in f) for f in self._faces ]


    def _snap_and_relax(self, M : Matrix, options : Patch_Options):
        print('snapping...')
        context = bpy.context
        Mi = M.inverted_safe()

        def snap(co_local : CO_LOCAL) -> CO_LOCAL:
            co_world = M @ co_local
            co_snapped_world = nearest_point_valid_sources(context, co_world) or co_world
            co_snapped_local = Mi @ co_snapped_world
            return co_snapped_local

        verts = [ pvert.co for pvert in self._verts ]

        if options and options.relax_enabled:
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

            for _iteration in range(options.relax_iterations):
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
                        forces[i] += dir_center_co * (options.relax_scale_edge * (goal - current))

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
                        forces[i0] += dir_center_com * (options.relax_scale_face * (goal - current))
                        forces[i1] += dir_center_com * (options.relax_scale_face * (goal - current))

                    for i in inds:
                        vec_center_co = verts[i] - center
                        current = vec_center_co.length
                        dir_center_co = vec_center_co / max(0.00001, current)
                        forces[i] += dir_center_co * (options.relax_scale_face * (goal - current))

                verts = [
                    co if fix else snap(co + force)
                    for (co, fix, force) in zip(verts, fixed, forces)
                ]
            t1 = time.time()
            print(f'  time: {t1-t0:0.4f}secs')

        for (pvert, co) in zip(self._verts, verts):
            pvert.co = co

    def reset(self):
        self._rings = []

        self._verts = []
        self._edges = []
        self._faces = []

        self.verts = []
        self.edges = []
        self.faces = []

    def get_pvert_index_map(self) -> dict[PVert, INDEX_PVERT]:
        return {
            pvert: index
            for (index, pvert) in enumerate(self._verts)
        }

    def create_patch(self, options : Patch_Options):
        assert self._rings

        if options.loops != 0:
            if options.loops is not None:
                self._create_loops(options)

            elif all(pvert.corner in {Corner.BRIDGE, Corner.UNSET} for pvert in self._rings[-1]):
                self._create_loops(options)

            return

        match options.cap:
            case Cap.PARALLEL:
                self._create_cap_parallel()

            case Cap.CENTRAL_QUADS:
                self._create_cap_central_quads()

            case Cap.CENTRAL_TRIS:
                self._create_cap_central_tris()

            case Cap.NGON:
                self._create_cap_ngon()


    def _create_cap_ngon(self):
        """
        Fill in rest with an n-gon
        """
        assert self._rings
        ring = self._rings[-1]
        idx = self.get_pvert_index_map()

        print(f'filling patch with {len(ring)-1}-sided ngon')
        self._faces.append(tuple(
            idx[pvert]
            for pvert in ring
        ))

    def _create_cap_central_quads(self):
        """
        Fill in rest with by adding a central point and create quad fans with
        perimeter and central point.  If perimeter is odd, there will be one
        triangle to fill in remaining.
        """
        assert self._rings
        ring = self._rings[-1]
        c = len(ring)

        print(f'filling patch with {c} verts using central point')

        # central point
        central = PVert('average', *ring)
        self._verts.append(central)

        idx = self.get_pvert_index_map()

        ic = idx[central]
        iside = [ idx[pvert] for pvert in ring ]

        for i in range(0, c, 2):
            i0 = iside[(i + 0) % c]
            i1 = iside[(i + 1) % c]
            i2 = iside[(i + 2) % c]
            if (i + 1) % c == 0:
                # handle last triangle
                self._faces.append((ic, i0, i1))
                self._edges.append((ic, i1))
            else:
                # handle quad
                self._faces.append((ic, i0, i1, i2))
                self._edges.append((i2, ic))

    def _create_cap_central_tris(self):
        """
        Fill in rest with by adding a central point and create triangle fans with
        perimeter and central point.
        """
        assert self._rings
        ring = self._rings[-1]
        c = len(ring)

        print(f'filling patch with {c} verts using central point')

        # central point
        central = PVert('average', *ring)
        self._verts.append(central)

        idx = self.get_pvert_index_map()

        ic = idx[central]
        iside = [ idx[pvert] for pvert in ring ]

        for i in range(0, c):
            i0 = iside[(i + 0) % c]
            i1 = iside[(i + 1) % c]
            self._faces.append((ic, i0, i1))
            self._edges.append((ic, i1))

    def _create_cap_parallel(self):
        assert self._rings
        ring = self._rings[-1]
        idx = self.get_pvert_index_map()
        c = len(ring)

        print(f'filling patch with {c} verts using parallel edges')
        iside = [ idx[pvert] for pvert in ring ]
        for i in range(0, (c - 1) // 2):
            i0 = iside[i + 0]
            i1 = iside[i + 1]
            i2 = iside[(c - 1) - i - 1]
            i3 = iside[(c - 1) - i - 0]
            if i1 == i2:
                # handle last triangle
                self._faces.append((i0, i1, i3))
            else:
                self._faces.append((i0, i1, i2, i3))
                if i > 0:
                    self._edges.append((i3, i0))



    def _create_loops(self, options : Patch_Options):
        """
        Generate bridged loops.

            loops: optional argument indicating how many loops to create.
                None: determine loop count; use radius and edge lengths to determine how many loops to create
                >= 0: forced loop count; generate exactly this many loos (0 means no loops)

            corners: optional argument to copy corner types to inner rings
                'copy': corner type is copied from outer ring to inner ring
                'unset': inner ring is left as Corner.UNSET, so they will be calculated
        """

        options.loops_made = 0

        assert self._rings
        ring = self._rings[-1]
        ring_outer = ring
        cos = [ pvert.co for pvert in ring ]
        c = len(ring)

        def compute_scaled_radius(ring : list[PVert], radii : list[RADIUS], index : INDEX_PVERT) -> RADIUS:
            r0 = radii[(index - 1) % c] #get_ring_radius(ring, index - 1)
            r1 = radii[(index + 0) % c] #get_ring_radius(ring, index + 0)
            r2 = radii[(index + 1) % c] #get_ring_radius(ring, index + 1)
            radius = min(r0, r1, r2) #get_ring_radius(ring, index)
            a0, a1, a2 = compute_angle(ring, index - 1), compute_angle(ring, index), compute_angle(ring, index + 1)
            # closer a1 is to 180deg, the more a0 and a2 have an affect
            # as a1 moves to 0deg or 360deg, a0 and a2 should have less affect
            # factor for a0 or a2: 180 => 1, 90 or 270 => ~0.5, 0 or 360 => 0
            # factor for a1: 180 => 1, 0 or 360 => 0
            f0 = 1 - (1 - abs(a0 - math.pi) / math.pi)**32
            f1 = 1 - (1 - abs(a1 - math.pi) / math.pi)**16
            f2 = 1 - (1 - abs(a2 - math.pi) / math.pi)**32
            return radius * f0 * f1 * f2

        loops_made = 0
        while options.loops is None or loops_made < options.loops:
            radii = [ get_ring_radius(ring, i) for i in range(c) ]
            # print(radii)

            if options.loops is not None:
                n_bridges = options.loops - loops_made

            else:
                n_bridges = 0
                for i in range(c):
                    i0, i1, i2 = (i - 1) % c, i, (i + 1) % c
                    co0, co1, co2 = cos[i0], cos[i1], cos[i2]
                    edge_length = max((co0 - co1).length, (co2 - co1).length)
                    radius = compute_scaled_radius(ring, radii, i)
                    if math.isinf(radius):
                        continue
                    ratio = 3.0 * radius // edge_length
                    n_bridges = max(n_bridges, ratio)

            n_bridges = int(n_bridges)

            if n_bridges < 1:
                break

            factor = 1.0 / (n_bridges + 0.5)

            radii = [
                compute_scaled_radius(ring, radii, i)
                for i in range(c)
            ]
            ring = [
                PVert(
                    'quad',
                    ring[(i-1)%c],
                    ring[i],
                    ring[(i+1)%c],
                    radii[i] * factor,
                )
                for i in range(c)
            ]
            i_start = len(self._verts)
            self._rings.append(ring)
            self._verts.extend(ring)
            for i in range(c):
                i0 = i_start - c + i
                i1 = i_start - c + (i + 1) % c
                i2 = i_start + (i + 1) % c
                i3 = i_start + i
                self._edges.extend([ (i1, i2), (i2, i3) ])
                self._faces.append((i0, i1, i2, i3))

            loops_made += 1
            options.loops_made += 1

        match options.loops_corners:
            case 'copy':
                for (p0, p1) in zip(ring_outer, ring):
                    p1.corner = p0.corner
            case 'unset':
                for pvert in ring:
                    pvert.corner = Corner.UNSET

        self.create_patch(replace(options, loops=0))
        return


    def _border(self, sides : PATCH_SIDES_PVERTS, factor : FACTOR) -> PATCH_SIDES_PVERTS:
        if len(sides) == 1:
            assert sides[0] is not None
            outer = sides[0][:-1]  # ignoring last PVert because it's a repeat of first
            print(f'adding border loop with {len(outer)} sides')
            c = len(outer)
            def get_radius(i0 : INDEX_PVERT) -> RADIUS:
                min_rad = float('inf')
                p0 = outer[i0].co
                IDX_DIST = 0
                for io1 in range(1 + IDX_DIST, c - IDX_DIST):
                    p1 = outer[(i0 + io1) % c].co
                    for io2 in range(io1 + 1 + IDX_DIST, c - IDX_DIST):
                        p2 = outer[(i0 + io2) % c].co
                        for io3 in range(io2 + 1 + IDX_DIST, c - IDX_DIST):
                            p3 = outer[(i0 + io3) % c].co
                            _ctr, rad = find_sphere_circle(p0, p1, p2, p3)
                            min_rad = min(min_rad, rad)
                return min_rad
            # center = sum((pv.co for pv in outer), Vector((0,0,0))) / c
            # radius = max((pv.co - center).length for pv in outer)
            inner = [
                PVert(
                    'quad',
                    outer[(i-1)%c],
                    outer[i],
                    outer[(i+1)%c],
                    get_radius(i) * factor,
                )
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
                self._edges.extend([ (i1, i2), (i2, i3) ]) #, (i3, i0) ])
                self._faces.append((i0, i1, i2, i3))
            inner += [inner[0]]  # need to repeat first PVert for correct setup
            sides = [inner]
        return sides


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
                ('lerp', side_a[-2], side_b[-2], 0.5 ),
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

    # !!! IMPORTANT
    #     Do _NOT_ keep reference to bmesh or bmesh elements, because they will invalidate
    #     whenever depsgraph changes!  Instead, keep track of them via their indices.

    # corners for patch
    corners_bmv : ClassVar[set[INDEX_BMVERT]]     = set()   # corners as indices into bm.verts (existing BMVerts)
    corners_new : ClassVar[list[CO_LOCAL]]        = []      # corners as local-space coordinates (new BMVerts)
    used_bmv    : ClassVar[set[INDEX_BMVERT]]     = set()   # indices of corner BMVerts that are used in >= sides (NOT index into corners_bmv, which is a set)
    used_new    : ClassVar[set[INDEX_CORNER_NEW]] = set()   # indices of corners_new that are used in >= sides

    # detected sides of patch, where ends of each side is a corner
    outer_ring  : ClassVar[list[INDEX_BMVERT]] = []
    sides : ClassVar[None] = None

    # detected patch based on sides
    patch : ClassVar[Patch | None] = None
    patch_options : ClassVar[Patch_Options | None] = None

    @staticmethod
    def update(*, force_rebuild : bool = False):
        RFCore = RFGlobals.RFCore
        context = bpy.context
        edit_object = context.edit_object
        assert edit_object
        M = edit_object.matrix_world

        if force_rebuild:
            Patches_Logic.patch = None

        if Patches_Logic.depsgraph_version != RFCore.depsgraph_version:
            print('depsgraph changed')
            # clear cache of "loose" BMVerts, to be regenerated in toggle_corner()
            Patches_Logic.loose_bmv_indices = None
            Patches_Logic.depsgraph_version = RFCore.depsgraph_version
            Patches_Logic.patch = None

        if Patches_Logic.patch is not None:
            return

        print('Rebuilding patch information')

        bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)
        layer = Patches_Logic.get_corner_layer(bm)
        Patches_Logic._update_corners(layer)
        Patches_Logic._update_sides(bm, layer)
        if not Patches_Logic.patch_options:
            Patches_Logic.patch_options = Patch_Options()
        Patches_Logic.patch_options.loops_made = 0
        Patches_Logic.patch = Patch(bm, layer, M, Patches_Logic.outer_ring, Patches_Logic.patch_options)

    @staticmethod
    def increase_outer_ring_offset():
        if not Patches_Logic.patch_options:
            Patches_Logic.patch_options = Patch_Options()
        Patches_Logic.patch_options.outer_ring_offset += 1

    @staticmethod
    def decrease_outer_ring_offset():
        if not Patches_Logic.patch_options:
            Patches_Logic.patch_options = Patch_Options()
        Patches_Logic.patch_options.outer_ring_offset -= 1


    @staticmethod
    def toggle_cap():
        if not Patches_Logic.patch_options:
            Patches_Logic.patch_options = Patch_Options()
        Patches_Logic.patch_options.cap = cap_toggle[Patches_Logic.patch_options.cap]

    @staticmethod
    def unset_loops():
        if not Patches_Logic.patch_options:
            Patches_Logic.patch_options = Patch_Options()
        Patches_Logic.patch_options.loops = None

    @staticmethod
    def increase_loops():
        if not Patches_Logic.patch_options:
            Patches_Logic.patch_options = Patch_Options()
        Patches_Logic.patch_options.loops = (Patches_Logic.patch_options.loops_made or 0) + 1

    @staticmethod
    def decrease_loops():
        if not Patches_Logic.patch_options:
            Patches_Logic.patch_options = Patch_Options()
        Patches_Logic.patch_options.loops = max((Patches_Logic.patch_options.loops_made or 0) - 1, 0)

    @staticmethod
    def reset():
        context = bpy.context
        edit_object = context.edit_object
        assert edit_object
        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=False)
        Patches_Logic.reset_corners(bm)
        bmesh.update_edit_mesh(em)
        Patches_Logic.patch_options = None

    @staticmethod
    def get_corner_layer(bm : BMesh) -> CornerLayer:
        return CornerLayer(bm, 'rf_patch_corner', Corner, Corner.UNSET)

    @staticmethod
    def reset_corners(bm : BMesh):
        CornerLayer.remove(bm, 'rf_patch_corner')

    @staticmethod
    def _update_corners(layer : CornerLayer):
        Patches_Logic.corners_bmv.clear()

        for (bmv, corner) in layer:
            if not bmv.select or bmv.hide:
                layer[bmv] = Corner.UNSET
                continue
            if corner == Corner.UNSET:
                # try to guess corner type based on surrounding topology
                match len(bmv.link_edges):
                    case 2:
                        layer[bmv] = Corner.INNER
                    case 3:
                        layer[bmv] = Corner.BRIDGE
                    case 4:
                        layer[bmv] = Corner.OUTER
                    case _:
                        layer[bmv] = Corner.BRIDGE
            Patches_Logic.corners_bmv.add(bmv.index)



    @staticmethod
    def _update_sides(bm : BMesh, layer : CornerLayer):
        Patches_Logic.outer_ring.clear()
        Patches_Logic.used_bmv.clear()
        Patches_Logic.used_new.clear()

        def get_biggest_selected_cycle() -> list[BMVert] | None:
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

                        if bmv1 == bmv_init:
                            # possible to not touch all corners!
                            # return sides_bmvs if len(touched_corners) == len(corners) else None
                            if not cycle or len(cycle) < len(side_bmvs):
                                cycle = side_bmvs
                            break

                        side_bmvs.append(bmv1)
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

        if (cycle_side := get_biggest_selected_cycle()):
            print(f'found cycle with {len(cycle_side)} selected verts')

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
                cycle_side.reverse()

            # rotate cycle to put one particular bmvert at the start so we have
            # some consistency and determinism across calls
            bmv_first = min(cycle_side, key=lambda bmv: (bmv.co.y, bmv.co.x, bmv.co.z))
            cycle_side = cycle_side[bmv_first.index:] + cycle_side[:bmv_first.index]


            # record sides
            Patches_Logic.outer_ring = [ bmv.index for bmv in cycle_side ]
            Patches_Logic.used_bmv = {
                bmv.index for bmv in cycle_side
            }

            return

        return

        # corners : set[BMVert] = {
        #     bmv for (bmv, corner) in layer if corner == Corner.OUTER
        # }

        # #####################################################################################
        # # first, see if there is a selected cycle with at least one corner

        # def get_biggest_cycle_with_corners() -> list[list[BMVert]] | None:
        #     cycle : list[list[BMVert]] | None = None

        #     for bmv_init in corners:
        #         bmv0 = bmv_init
        #         for bme0 in bmv0.link_edges:
        #             if bme0.hide or not bme0.select:
        #                 continue

        #             touched_corners : set[BMVert] = { bmv0 }
        #             touched_bmes : set[BMEdge] = { bme0 }
        #             sides_bmvs : list[list[BMVert]] = []
        #             side_bmvs : list[BMVert] = [ bmv0 ]

        #             while True:
        #                 bmv1 = bme0.other_vert(bmv0)
        #                 if not bmv1:
        #                     break

        #                 side_bmvs.append(bmv1)

        #                 if bmv1 in corners:
        #                     touched_corners.add(bmv1)
        #                     sides_bmvs.append(side_bmvs)
        #                     side_bmvs = [ bmv1 ]

        #                 if bmv1 == bmv_init:
        #                     # possible to not touch all corners!
        #                     # return sides_bmvs if len(touched_corners) == len(corners) else None
        #                     if not cycle or sum(len(c) for c in cycle) < sum(len(s) for s in sides_bmvs):
        #                         cycle = sides_bmvs
        #                     break

        #                 bme1 = next(
        #                     (
        #                         bme
        #                         for bme in bmv1.link_edges
        #                         if bme.select and not bme.hide and bme not in touched_bmes
        #                     ),
        #                     None
        #                 )
        #                 if not bme1:
        #                     break

        #                 bmv0, bme0 = bmv1, bme1
        #                 touched_bmes.add(bme0)

        #     return cycle

        # if (cycle_sides := get_biggest_cycle_with_corners()):
        #     print(f'found cycle with {len(cycle_sides)} sides')

        #     if len(cycle_sides) >= 2:
        #         # make sure directions of sides are consistent
        #         if cycle_sides[0][0] == cycle_sides[1][0] or cycle_sides[0][0] == cycle_sides[1][-1]:
        #             # first side is reversed
        #             cycle_sides[0].reverse()
        #         for (side0, side1) in zip(cycle_sides[:-1], cycle_sides[1:]):
        #             if side0[-1] == side1[-1]:
        #                 # reverse side1 so side0 and side1 are in same direction
        #                 side1.reverse()

        #     # check that cycle is correct direction
        #     bmvs = [ side[0] for side in cycle_sides ] if len(cycle_sides) > 1 else cycle_sides[0]
        #     co_center = sum([bmv.co for bmv in bmvs], Vector((0,0,0))) / len(bmvs)
        #     normal_patch = sum(
        #         (
        #             (bmv0.co - co_center).cross(bmv1.co - co_center)
        #             for (bmv0, bmv1) in iter_pairs(bmvs, True)
        #         ), Vector((0, 0, 0))
        #     )
        #     normal_corners = sum(
        #         ( bmv.normal for bmv in bmvs ),
        #         Vector((0, 0, 0))
        #     )
        #     if normal_patch.dot(normal_corners) < 0:
        #         # reverse cycle
        #         cycle_sides = [
        #             list(side[::-1])
        #             for side in cycle_sides[::-1]
        #         ]

        #     # record sides
        #     Patches_Logic.sides = [
        #         [ bmv.index for bmv in cycle_side ]
        #         for cycle_side in cycle_sides
        #     ]
        #     if len(Patches_Logic.sides) == 1:
        #         Patches_Logic.sides.append(None)

        #     Patches_Logic.used_bmv = {
        #         bmv.index
        #         for cycle_side in cycle_sides
        #         for bmv in cycle_side #[cycle_side[0], cycle_side[-1]]
        #     }

        #     return


        # #####################################################################################
        # # next, see if there is a selected cycle with no corners

        # def get_biggest_cycle_with_no_corners() -> list[BMVert] | None:
        #     cycle : list[BMVert] | None = None

        #     for bmv_init in bmops.get_all_selected_bmverts(bm):
        #         bmv0 = bmv_init
        #         for bme0 in bmv0.link_edges:
        #             if bme0.hide or not bme0.select:
        #                 continue

        #             touched_bmes : set[BMEdge] = { bme0 }
        #             side_bmvs : list[BMVert] = [ bmv0 ]

        #             while True:
        #                 bmv1 = bme0.other_vert(bmv0)
        #                 if not bmv1:
        #                     break

        #                 side_bmvs.append(bmv1)

        #                 if bmv1 == bmv_init:
        #                     # possible to not touch all corners!
        #                     # return sides_bmvs if len(touched_corners) == len(corners) else None
        #                     if not cycle or len(cycle) < len(side_bmvs):
        #                         cycle = side_bmvs
        #                     break

        #                 bme1 = next(
        #                     (
        #                         bme
        #                         for bme in bmv1.link_edges
        #                         if bme.select and not bme.hide and bme not in touched_bmes
        #                     ),
        #                     None
        #                 )
        #                 if not bme1:
        #                     break

        #                 bmv0, bme0 = bmv1, bme1
        #                 touched_bmes.add(bme0)

        #     return cycle

        # if (cycle_side := get_biggest_cycle_with_no_corners()):
        #     cycle_sides = [cycle_side]
        #     print(f'found cycle with {len(cycle_side)} verts and no corners')

        #     # check that cycle is correct direction
        #     bmvs = cycle_side
        #     co_center = sum([bmv.co for bmv in bmvs], Vector((0,0,0))) / len(bmvs)
        #     normal_patch = sum(
        #         (
        #             (bmv0.co - co_center).cross(bmv1.co - co_center)
        #             for (bmv0, bmv1) in iter_pairs(bmvs, True)
        #         ), Vector((0, 0, 0))
        #     )
        #     normal_corners = sum(
        #         ( bmv.normal for bmv in bmvs ),
        #         Vector((0, 0, 0))
        #     )
        #     if normal_patch.dot(normal_corners) < 0:
        #         # reverse cycle
        #         cycle_sides[0].reverse()

        #     # record sides
        #     Patches_Logic.sides = [
        #         [ bmv.index for bmv in cycle_side ]
        #         for cycle_side in cycle_sides
        #     ]
        #     Patches_Logic.used_bmv = {
        #         bmv.index
        #         for cycle_side in cycle_sides
        #         for bmv in [cycle_side[0], cycle_side[-1]]
        #     }

        #     return


        # #####################################################################################
        # # finally, see if there exists a broken cycle from corners, including either
        # # selected edges between corners or a side that needs to be created
        # #
        # #          NOT YET IMPLEMENTED!

        # graph_corners : dict[BMVert, dict[BMVert, list[BMVert]]] = {
        #     bmv: {}
        #     for bmv in corners
        # }
        # uf = UnionFind(corners)

        # for bmv_init in corners:
        #     paths : dict[BMVert, BMVert] = { bmv_init: bmv_init }
        #     touched : set[BMEdge | BMVert] = set()
        #     working : deque[BMVert] = deque([ bmv_init ])
        #     while working:
        #         bmv0 = working.popleft()
        #         for bme in bmv0.link_edges:
        #             if not bme.select or bme.hide or bme in touched:
        #                 continue
        #             touched.add(bme)

        #             bmv1 = bme.other_vert(bmv0)
        #             if not bmv1 or bmv1 in touched:
        #                 continue

        #             # touched.add(bmv1)
        #             paths[bmv1] = bmv0

        #             if bmv1 not in corners:
        #                 # have not reached corner, yet
        #                 working.append(bmv1)
        #                 continue

        #             # found a corner, add to graph
        #             bmv = bmv1
        #             path : list[BMVert] = [ bmv ]
        #             while path[-1] != bmv_init:
        #                 path.append(paths[path[-1]])
        #             path.reverse()
        #             graph_corners[bmv_init][bmv1] = path
        #             uf.connect(bmv_init, bmv1)

        # if DEBUG_PRINT:
        #     print()
        #     for bmv0 in graph_corners:
        #         print(f'{bmv0.index}')
        #         for bmv1 in graph_corners[bmv0]:
        #             print(f'  {bmv1.index}: {[bmv.index for bmv in graph_corners[bmv0][bmv1]]}')
        #     print(f'roots: {[bmv.index for bmv in uf.roots()]}')

        #     solos     = { bmv0 for bmv0 in graph_corners if len(graph_corners[bmv0]) == 0 }
        #     ends      = { bmv0 for bmv0 in graph_corners if len(graph_corners[bmv0]) == 1 }
        #     joints    = { bmv0 for bmv0 in graph_corners if len(graph_corners[bmv0]) == 2 }
        #     junctions = { bmv0 for bmv0 in graph_corners if len(graph_corners[bmv0]) >= 3 }
        #     print(f'solos:     {solos}')
        #     print(f'ends:      {ends}')
        #     print(f'joints:    {joints}')
        #     print(f'junctions: {junctions}')



        # # starts : set[BMVert] = set(corners)
        # # path : dict[BMVert, BMVert | None] = {}
        # # touched_bmes : set[BMEdge] = set()

        # # while starts:
        # #     bmv = starts.pop()

        # #     if not bmv.link_edges:
        # #         Patches_Logic.sides.append([bmv.index])
        # #         continue

        # #     path[bmv] = None
        # #     walking_queue : deque[BMVert] = deque([ bmv ])
        # #     touched : set[BMVert] = set()

        # #     while walking_queue:
        # #         bmv = walking_queue.popleft()
        # #         if bmv in touched:
        # #             continue
        # #         touched.add(bmv)

        # #         if bmv in starts:
        # #             side_bmvs : list[BMVert] = [ ]
        # #             while bmv:
        # #                 side_bmvs.append(bmv)
        # #                 bmv = path[bmv]
        # #             side_bmvs.reverse()
        # #             side_inds = [ bmv.index for bmv in side_bmvs ]
        # #             Patches_Logic.sides.append(side_inds)
        # #             continue

        # #         for bme in bmv.link_edges:
        # #             if not bme.select or bme.hide or bme in touched_bmes:
        # #                 continue
        # #             touched_bmes.add(bme)
        # #             v2 = bme.other_vert(bmv)
        # #             if not v2 or v2 in touched:
        # #                 continue
        # #             path[v2] = bmv
        # #             walking_queue.append(v2)
        # # print(Patches_Logic.sides)


    @staticmethod
    def toggle_corner(context : Context, event : Event, *, radius2d : float = 10) -> bool:
        """
        Toggles vertex under mouse as corner.
        Returns whether
        """
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

        bm, _em = get_bmesh_emesh(bpy.context, ensure_lookup_tables=True)
        layer = Patches_Logic.get_corner_layer(bm)
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
            # found a BMVert under mouse, so switch through its corner type
            bmv = bm.verts[best_idx_bmv]
            layer[bmv] = corner_toggle[layer[bmv]]

        elif best_idx_new >= 0:
            # found a new corner under mouse, so remove it
            pass
            # Patches_Logic.corners_new = (
            #     Patches_Logic.corners_new[:best_idx_new] +
            #     Patches_Logic.corners_new[best_idx_new+1:]
            # )

        else:
            # cound not find corner under mouse, so add it
            pass
            # Patches_Logic.corners_new.append(co_local)

        Patches_Logic.update(force_rebuild=True)
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
        layer = Patches_Logic.get_corner_layer(bm)

        theme = bpy.context.preferences.themes[0].view_3d
        props = RF_Prefs.get_prefs(context)
        highlight = cast(Vector, props.highlight_color)

        color_point = Color4((highlight[0], highlight[1], highlight[2], 1))
        color_point_border = Color4((highlight[0], highlight[1], highlight[2], 0.25))

        color_bridge = Color4((1, 1, 1, 1))
        color_bridge_border = Color4((highlight[0], highlight[1], highlight[2], 0.25))

        color_outer = Color4((1, 1, 0, 1))
        color_outer_border = Color4((0, 0, 1, 1))

        color_inner = Color4((0, 1, 1, 1))
        color_inner_border = Color4((1, 0, 0, 1))

        color_unused = Color4((1, 0, 0, 1))
        color_open_border = Color4((highlight[0], highlight[1], highlight[2], 1.0))
        color_stipple = Color4((theme.face_select[0], theme.face_select[1], theme.face_select[2], 0))
        color_mesh = theme.face_select
        vertex_radius = TANGENT_RADIUS
        vertex_border = 4

        # draw patch
        if (patch := Patches_Logic.patch):
            with Drawing.draw(context, CC_2D_POINTS) as draw:
                draw.color(color_point)
                draw.point_size(vertex_radius) #theme.vertex_size + 4)
                draw.border(width=vertex_border, color=color_point_border)

                for pt in patch.verts:
                    _ = draw.vertex(proj(pt))

            with Drawing.draw(context, CC_2D_LINES) as draw:
                draw.line_width(2)
                draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                draw.color(color_open_border)

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
            for idx_bmv in Patches_Logic.used_bmv:
                bmv = bm.verts[idx_bmv]
                draw.point_size(vertex_radius)
                match layer[bmv]:
                    case Corner.BRIDGE | Corner.UNSET:
                        draw.color(color_bridge)
                        draw.border(width=vertex_border, color=color_bridge_border)
                    case Corner.OUTER:
                        draw.color(color_outer)
                        draw.border(width=vertex_border, color=color_outer_border)
                    case Corner.INNER:
                        draw.color(color_inner)
                        draw.border(width=vertex_border, color=color_inner_border)
                _ = draw.vertex(proj(M @ bmv.co))

            # for idx_bmv in Patches_Logic.corners_bmv:
            #     bmv = bm.verts[idx_bmv]
            #     if idx_bmv in Patches_Logic.used_bmv:
            #         bmv = bm.verts[idx_bmv]
            #         draw.point_size(vertex_radius)
            #         match layer[bmv]:
            #             case Corner.BRIDGE | Corner.UNSET:
            #                 draw.color(color_bridge)
            #                 draw.border(width=vertex_border, color=color_bridge_border)
            #             case Corner.OUTER:
            #                 draw.color(color_outer)
            #                 draw.border(width=vertex_border, color=color_outer_border)
            #             case Corner.INNER:
            #                 draw.color(color_inner)
            #                 draw.border(width=vertex_border, color=color_inner_border)
            #         _ = draw.vertex(proj(M @ bmv.co))

            #         # draw.point_size(vertex_size + 4)
            #         # match layer[bmv]:
            #         #     case Corner.BRIDGE:
            #         #         draw.color(color_point)
            #         #     case Corner.OUTER:
            #         #         draw.color(color_outer)
            #         #     case Corner.INNER:
            #         #         draw.color(color_inner)
            #         # _ = draw.vertex(proj(M @ bmv.co))
            #         # draw.point_size(vertex_size + 1)
            #         # draw.color(color_point)
            #         # _ = draw.vertex(proj(M @ bmv.co))
            #     else:
            #         draw.point_size(vertex_radius + vertex_border)
            #         draw.color(color_unused)
            #         _ = draw.vertex(proj(M @ bmv.co))
            #         draw.point_size(vertex_radius)
            #         draw.color(color_point)
            #         _ = draw.vertex(proj(M @ bmv.co))

            # draw new corners
            for (idx_new, co) in enumerate(Patches_Logic.corners_new):
                if idx_new in Patches_Logic.used_new:
                    draw.point_size(vertex_radius + vertex_border)
                    draw.color(color_point)
                    _ = draw.vertex(proj(M @ co))
                else:
                    draw.point_size(vertex_radius + vertex_border)
                    draw.color(color_unused)
                    _ = draw.vertex(proj(M @ co))
                    draw.point_size(vertex_radius)
                    draw.color(color_point)
                    _ = draw.vertex(proj(M @ co))

        # # draw sides
        # for side in Patches_Logic.sides:
        #     if not side:
        #         continue
        #     n_verts = len(side)
        #     i0 = (n_verts - 1) // 2
        #     i1 = (i0 + 1) if n_verts % 2 == 0 else i0
        #     co = (bm.verts[side[i0]].co + bm.verts[side[i1]].co) / 2
        #     p = proj(M @ co)
        #     if p:
        #         Drawing.text_draw2D(
        #             f'{n_verts - 1}',
        #             p,
        #             color=(1,1,0,1),
        #             dropshadow=(0,0,0,1),
        #         )

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
