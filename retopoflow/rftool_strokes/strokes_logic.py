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

import bpy
import bmesh
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from ..rftool_base import RFTool_Base
from ..rfbrush_base import RFBrush_Base
from ..common.bmesh import get_bmesh_emesh, nearest_bmv_world, nearest_bme_world, NearestBMVert
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
from ..common.icons import get_path_to_blender_icon
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, size2D_to_size, vec_forward, mouse_from_event
from ..common.maths import view_forward_direction, lerp
from ..common.operator import (
    invoke_operator, execute_operator,
    RFOperator, RFRegisterClass,
    chain_rf_keymaps, wrap_property,
)
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event, nearest_point_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common import gpustate
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.maths import Color, Frame
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.utils import iter_pairs

import math

'''
need to determine shape of extrusion
key: |- stroke
     C  corner in stroke (roughly 90° angle, but not easy to detect.  what if the stroke loops over itself?)
     ǁ= selected boundary or wire edges (Ⓞ selected cycle)
     O  vertex under stroke
     X  corner vertex (edges change direction)
notes:
- vertex under stroke must be at beginning or ending of stroke
- vertices are "under stroke" if they are selected or if "Snap Stroke to Unselected" is enabled

                Strip    L-shape   U-shape   Equals   Cycle   Torus
                  |      |         ǁ     ǁ   ======   ⎛‾‾‾‾⎫   ⎛‾‾‾‾⎫
Implemented:      |      |         ǁ     ǁ            |    |   | Ⓞ |
                  |      O======   O-----O   ------   ⎝____⎭   ⎝____⎭

                C-shape   T-shape   I-shape   O-shape   D-shape
Not             O------   ===O===   ===O===   X=====O   O-----C
Implemented:    ǁ            |         |      ǁ     |   ǁ     |
(yet)           X======      |      ===O===   X=====O   O-----C


L vs C: there is a corner vertex in the edges (could we extend the L shape??)
D has corners in the stroke, which will be tricky to determine... use acceleration?
'''

def find_point(points, is_cycle, length, v):
    if v <= 0: return points[0]
    if v >= 1: return points[0] if is_cycle else points[-1]
    vt = v * length
    t = 0
    for (p0, p1) in iter_pairs(points, is_cycle):
        d01 = (p1 - p0).length
        if vt <= t + d01:
            # LERP to find point
            d0v = vt - t
            f = d0v / d01
            return p0 + (f * (p1 - p0))
        t += d01
    return points[0] if is_cycle else points[-1]


class Strokes_Logic:
    def __init__(self, context, stroke2D, is_cycle, snap_bmv0, snap_bmv1, mode, fixed_span_count, radius):
        self.bm, self.em = get_bmesh_emesh(context)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.context = context
        self.stroke2D = stroke2D
        self.is_cycle = is_cycle
        self.snap_bmv0 = snap_bmv0
        self.snap_bmv1 = snap_bmv1
        self.mode = mode
        self.fixed_span_count = fixed_span_count
        self.radius = radius

        # project 2D stroke points to sources
        self.stroke3D = [raycast_point_valid_sources(context, pt, world=False) for pt in self.stroke2D]
        # compute total lengths, which will be used to find where new verts are to be created
        self.length2D = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke2D, self.is_cycle))
        self.length3D = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke3D, self.is_cycle))

        print(f'PROCESSING {len(self.stroke2D)} {self.length2D} {self.is_cycle} {self.snap_bmv0} {self.snap_bmv1} {self.mode} {self.fixed_span_count} {self.radius}')

        # TODO: handle gracefully if these functions fail
        if not self.is_cycle:
            self.insert_strip()
        else:
            self.insert_cycle()
        bmesh.update_edit_mesh(self.em)


    def find_point2D(self, v): return find_point(self.stroke2D, self.is_cycle, self.length2D, v)
    def find_point3D(self, v): return find_point(self.stroke3D, self.is_cycle, self.length3D, v)

    def insert_strip(self):
        match self.mode:
            case 'BRUSH':
                nspans = math.ceil(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case _:
                assert False, f'Unhandled {self.mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        print(f'Inserting strip: {nspans=} {nverts=}')

        bmvs = []
        for iv in range(nverts):
            if iv == 0 and self.snap_bmv0:
                bmvs += [self.snap_bmv0]
            elif iv == nverts - 1 and self.snap_bmv1:
                bmvs += [self.snap_bmv1]
            else:
                v = iv / (nverts-1)
                pt = self.find_point3D(v)
                bmvs += [self.bm.verts.new(pt)]
        bmes = []
        for ie in range(nspans):
            bmv0, bmv1 = bmvs[ie], bmvs[ie+1]
            bme = next((e for e in bmv0.link_edges if e in bmv1.link_edges), None)
            if not bme:
                bme = self.bm.edges.new((bmv0, bmv1))
            bmes += [bme]

    def insert_cycle(self):
        match self.mode:
            case 'BRUSH':
                nspans = math.ceil(self.length2D / self.radius)
            case 'FIXED':
                nspans = self.fixed_span_count
            case _:
                assert False, f'Unhandled {self.mode=}'
        nspans = max(3, nspans)
        nverts = nspans

        print(f'Inserting cycle: {nspans=} {nverts=}')
        bmvs = [
            self.bm.verts.new(self.find_point3D(iv / nverts))
            for iv in range(nverts)
        ]
        bmes = [
            self.bm.edges.new((bmv0, bmv1))
            for (bmv0, bmv1) in iter_pairs(bmvs, True)
        ]

