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
from ...addon_common.common.maths import Color, Frame, closest_point_segment
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.utils import iter_pairs

import math
import time

'''
need to determine shape of extrusion
key: |- stroke
     C  corner in stroke (roughly 90° angle, but not easy to detect.  what if the stroke loops over itself?)
     ǁ= selected boundary or wire edges (Ⓞ selected cycle)
     O  vertex under stroke
     X  corner vertex (edges change direction)
     +  inserted verts (interpolated from selection and stroke)
notes:
- vertex under stroke must be at beginning or ending of stroke
- vertices are "under stroke" if they are selected or if "Snap Stroke to Unselected" is enabled

                Strip   Equals    T-shape   I-shape
Implemented       |     ======    ===O===   ===O===
Strip             |     + + +     + +|+ +   + +|+ +
                  |     ------    + +|+ +   ===O===

                Cycle    Annulus
Implemented     ⎛‾‾‾‾⎫   ⎛‾‾‾‾⎫ (vert inserted)
Cycle           |    |   | Ⓞ | (but not drawn)
                ⎝____⎭   ⎝____⎭ (in ascii art)

                O-shape   D-shape
Not             X=====O   O-----C
Implemented:    ǁ + + |   ǁ + + |
(yet)           X=====O   O-----C

What if two cycles of same length are selected, and stroke goes from a vert in one to a vert in the other?
Control how the two are spanned??


L/T vs C/I: there is a corner vertex in the edges
D has corners in the stroke, which will be tricky to determine... use acceleration?
'''


def find_point_at(points, is_cycle, length, v):
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

def find_closest_point(points, is_cycle, p):
    closest_p = None
    closest_d = float('inf')
    for (p0, p1) in iter_pairs(points, is_cycle):
        pt = closest_point_segment(p, p0, p1)
        d = (p - pt).length
        if not closest_p or d < closest_d:
            (closest_p, closest_d) = (pt, d)
    return closest_p

def compute_n(points):
    p0 = points[0]
    return sum((
        (p1-p0).cross(p2-p0).normalized()
        for (p1,p2) in zip(points[1:-1], points[2:])
    ), Vector((0,0,0))).normalized()

def is_bmv_end(bmv, bmes):
    return len(set(bmv.link_edges) & bmes) != 2
def bme_other_bmv(bme, bmv):
    bmv0, bmv1 = bme.verts
    return bmv0 if bmv1 == bmv else bmv1
def bmes_shared_bmv(bme0, bme1):
    return next(iter(set(bme0.verts) & set(bme1.verts)), None)
def bme_unshared_bmv(bme0, bme1):
    bmv0, bmv1 = bme0.verts
    return bmv0 if bmv1 in bme1.verts else bmv1
def bmes_share_bmv(bme0, bme1):
    return bool(set(bme0.verts) & set(bme1.verts))

def bme_vector(bme):
    return (bmv1.co - bmv0.co)
def bme_length(bme):
    bmv0,bmv1 = bme.verts
    return (bmv0.co - bmv1.co).length
def bme_midpoint(bme):
    bmv0,bmv1 = bme.verts
    return (bmv0.co + bmv1.co) / 2

def get_longest_strip_cycle(bmes):
    if not bmes: return (None, None, None)

    bmes = set(bmes)

    strips, cycles = [], []

    # first start with bmvert ends to find strips
    bmv_ends = { bmv for bme in bmes for bmv in bme.verts if is_bmv_end(bmv, bmes) }
    while True:
        current_strip = []
        bmv = next(( bmv for bme in bmes for bmv in bme.verts if bmv in bmv_ends ), None)
        if not bmv: break
        bme = None
        while True:
            bme = next(iter(set(bmv.link_edges) & bmes - {bme}), None)
            current_strip += [bme]
            bmv = bme_other_bmv(bme, bmv)
            if bmv in bmv_ends: break
        bmes -= set(current_strip)
        strips += [current_strip]

    # some of the strips may actually be cycles...
    for strip in list(strips):
        if len(strip) > 3 and bmes_share_bmv(strip[0], strip[-1]):
            strips.remove(strip)
            cycles.append(strip)

    # any bmedges still in bmes _should_ be part of cycles
    while True:
        current_cycle = []
        bmv = next(( bmv for bme in bmes for bmv in bme.verts ), None)
        if not bmv: break
        bme = None
        while True:
            bme = next(iter(set(bmv.link_edges) & bmes - {bme}), None)
            if not bme or bme in current_cycle: break
            current_cycle += [bme]
            bmv = bme_other_bmv(bme, bmv)
        bmes -= set(current_cycle)
        cycles += [current_cycle]

    strips.sort(key=lambda strip:len(strip))
    cycles.sort(key=lambda cycle:len(cycle))

    longest_strip0 = strips[-1] if strips else None
    longest_strip1 = strips[-2] if len(strips) >= 2 else None
    longest_cycle = cycles[-1] if cycles else None

    print(f'{strips=}')
    print(f'{cycles=}')
    print(f'{longest_strip0=}')
    print(f'{longest_strip1=}')
    print(f'{longest_cycle=}')

    return (longest_strip0, longest_strip1, longest_cycle)



class Strokes_Logic:
    def __init__(self, context, stroke2D, is_cycle, snap_bmv0, snap_bmv1, mode, fixed_span_count, radius):
        self.bm, self.em = get_bmesh_emesh(context)
        bmops.flush_selection(self.bm, self.em)
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

        self.process_selected()

        print(f'PROCESSING {len(self.stroke2D)} {self.length2D} {self.is_cycle} {self.snap_bmv0} {self.snap_bmv1} {self.mode} {self.fixed_span_count} {self.radius}')

        # TODO: handle gracefully if these functions fail
        self.insert()

        bpy.ops.ed.undo_push(message=f'Strokes insert {time.time()}')
        bmops.flush_selection(self.bm, self.em)

    def insert(self):
        print(f'{self.is_cycle=}')
        print(f'{self.longest_cycle=}')
        print(f'{self.longest_strip0=}')
        print(f'{self.longest_strip1=}')
        print(f'{self.snap_sel00=} {self.snap_sel01=}')
        if self.is_cycle:
            if not self.longest_cycle:
                self.insert_cycle()
            else:
                self.insert_annulus()
        else:
            if self.longest_strip0:
                if self.longest_strip1 and len(self.longest_strip0) == len(self.longest_strip1):
                    if (self.snap_sel00 and self.snap_sel11) or (self.snap_sel01 and self.snap_sel10):
                        self.insert_I()
                        return

                if self.snap_sel00 or self.snap_sel01:
                    self.insert_T()
                else:
                    self.insert_equals()
            else:
                self.insert_strip()

    def process_selected(self):
        """
        Finds and analyzes all selected geometry, which is used to determine how to interpret
        an insertion (new strip/cycle, bridging selection to stroke, etc. )
        """
        print(self.bm, self.bm.is_valid)
        self.sel_edges = [
            bme
            for bme in bmops.get_all_selected_bmedges(self.bm)
            if bme.is_wire or bme.is_boundary
            # len(bme.link_faces) < 2
            # not is_manifold() ==> len(bme.link_faces) != 2 which includes edges with 3+ faces :(
        ]
        print(self.sel_edges)
        self.longest_strip0, self.longest_strip1, self.longest_cycle = get_longest_strip_cycle(self.sel_edges)
        # compute 3D length
        self.longest_strip0_length = sum(bme_length(bme) for bme in self.longest_strip0) if self.longest_strip0 else None
        self.longest_strip1_length = sum(bme_length(bme) for bme in self.longest_strip1) if self.longest_strip1 else None
        self.longest_cycle_length  = sum(bme_length(bme) for bme in self.longest_cycle) if self.longest_cycle else None

        self.snap_sel00 = self.snap_bmv0 and self.longest_strip0 and any(self.snap_bmv0 in bme.verts for bme in self.longest_strip0)
        self.snap_sel10 = self.snap_bmv1 and self.longest_strip0 and any(self.snap_bmv1 in bme.verts for bme in self.longest_strip0)
        self.snap_sel01 = self.snap_bmv0 and self.longest_strip1 and any(self.snap_bmv0 in bme.verts for bme in self.longest_strip1)
        self.snap_sel11 = self.snap_bmv1 and self.longest_strip1 and any(self.snap_bmv1 in bme.verts for bme in self.longest_strip1)

    def find_point2D(self, v): return find_point_at(self.stroke2D, self.is_cycle, self.length2D, v)
    def find_point3D(self, v): return find_point_at(self.stroke3D, self.is_cycle, self.length3D, v)


    #####################################################################################
    # simple insertions with no bridging

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

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs)

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

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs)


    ##############################################################################
    # basic bridging insertions

    def insert_annulus(self):
        assert self.is_cycle
        assert self.longest_cycle

        llc = len(self.longest_cycle)

        # make sure stroke and selected cyclic bmvs have same winding direction
        n_stroke3D = compute_n(self.stroke3D)
        n_bmvs = compute_n([bme_midpoint(bme) for bme in self.longest_cycle])
        if n_bmvs.dot(n_stroke3D) < 0:
            # turning opposite directions
            self.stroke3D.reverse()

        # align closest points between selected cyclic bmvs and stroke
        M, Mi = self.matrix_world, self.matrix_world_inv
        closest_i, closest_pt0, closest_j, closest_pt1, closest_d = None, None, None, None, float('inf')
        for i in range(llc):
            bme_pre = self.longest_cycle[(i-1) % llc]
            bme_cur = self.longest_cycle[i]
            bmv = bmes_shared_bmv(bme_pre, bme_cur)
            for (j, pt) in enumerate(self.stroke3D):
                d = (bmv.co - pt).length
                if d >= closest_d: continue
                closest_i, closest_pt0, closest_j, closest_pt1, closest_d = i, bmv.co, j, pt, d
        # rotate lists so self.stroke3D[0] aligns self.longest_cycle[0]
        self.longest_cycle = self.longest_cycle[closest_i:] + self.longest_cycle[:closest_i]
        self.stroke3D = self.stroke3D[closest_j:] + self.stroke3D[:closest_j]

        # determine number of spans
        match self.mode:
            case 'BRUSH':
                pt0 = location_3d_to_region_2d(self.context.region, self.context.region_data, M @ closest_pt0)
                pt1 = location_3d_to_region_2d(self.context.region, self.context.region_data, M @ closest_pt1)
                nspans = math.ceil((pt0 - pt1).length / self.radius)
                print(f'{(pt0-pt1).length=} / {self.radius=} = {nspans=}')
            case 'FIXED':
                nspans = self.fixed_span_count
            case _:
                assert False, f'Unhandled {self.mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        bme_pre = self.longest_cycle[-1]
        accum_dist = 0
        bmvs = [[] for i in range(nverts)]
        for bme_cur in self.longest_cycle:
            bmv = bmes_shared_bmv(bme_pre, bme_cur)
            spt = self.find_point3D(accum_dist / self.longest_cycle_length)
            pt0 = location_3d_to_region_2d(self.context.region, self.context.region_data, M @ bmv.co)
            pt1 = location_3d_to_region_2d(self.context.region, self.context.region_data, M @ spt)
            v = pt1 - pt0

            bmvs[0].append(bmv)
            for i in range(1, nverts):
                pt = pt0 + v * (i / (nverts - 1))
                co = raycast_point_valid_sources(self.context, pt, world=False)
                bmvs[i].append(self.bm.verts.new(co) if co else None)

            accum_dist += bme_length(bme_cur)
            bme_pre = bme_cur
        bmfs = []
        for i in range(nverts-1):
            for j in range(llc):
                bmv00 = bmvs[i+0][(j+0)%llc]
                bmv01 = bmvs[i+0][(j+1)%llc]
                bmv10 = bmvs[i+1][(j+0)%llc]
                bmv11 = bmvs[i+1][(j+1)%llc]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmf.normal_update()
                if view_forward_direction(self.context).dot(bmf.normal) > 0:
                    bmf.normal_flip()
                bmfs.append(bmf)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[-1])


    def insert_equals(self):
        llc = len(self.longest_strip0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke and selected strip point in same direction
        v_stroke = self.stroke3D[-1] - self.stroke3D[0]
        if llc == 1:
            sel_bmv0, sel_bmv1 = self.longest_strip0[0].verts
            v_selected = sel_bmv1.co - sel_bmv0.co
        else:
            co0 = bme_midpoint(self.longest_strip0[0])
            co1 = bme_midpoint(self.longest_strip0[-1])
            v_selected = co1 - co0
        if v_stroke.dot(v_selected) < 0:
            # pointing opposite directions
            self.stroke3D.reverse()

        # determine number of spans
        match self.mode:
            case 'BRUSH':
                # find closest distance between selected and stroke
                rgn, r3d = self.context.region, self.context.region_data
                closest_distance2D = min(
                    (s - location_3d_to_region_2d(rgn, r3d, M @ bmv.co)).length
                    for s in self.stroke2D
                    for bme in self.longest_strip0
                    for bmv in bme.verts
                )
                nspans = math.ceil(closest_distance2D / self.radius)
            case 'FIXED':
                nspans = self.fixed_span_count
            case _:
                assert False, f'Unhandled {self.mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # find first vert
        if llc == 1:
            bmv = self.longest_strip0[0].verts[0]
        else:
            bmv = bme_unshared_bmv(self.longest_strip0[0], self.longest_strip0[1])
        accum_dist = 0
        bmvs = [[] for i in range(nverts)]
        for bme_cur in self.longest_strip0 + [None]:
            spt = self.find_point3D(accum_dist / self.longest_strip0_length)
            pt0 = location_3d_to_region_2d(self.context.region, self.context.region_data, M @ bmv.co)
            pt1 = location_3d_to_region_2d(self.context.region, self.context.region_data, M @ spt)
            v = pt1 - pt0

            bmvs[0].append(bmv)
            for i in range(1, nverts):
                pt = pt0 + v * (i / (nverts - 1))
                co = raycast_point_valid_sources(self.context, pt, world=False)
                bmvs[i].append(self.bm.verts.new(co) if co else None)

            if not bme_cur: break
            accum_dist += bme_length(bme_cur)
            bmv = bme_other_bmv(bme_cur, bmv)

        if self.snap_bmv0:
            bmesh.ops.pointmerge(self.bm, verts=[bmvs[-1][0], self.snap_bmv0], merge_co=self.snap_bmv0.co)
        if self.snap_bmv1:
            bmesh.ops.pointmerge(self.bm, verts=[bmvs[-1][-1], self.snap_bmv1], merge_co=self.snap_bmv1.co)

        bmfs = []
        for i in range(nverts-1):
            for j in range(llc):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmf.normal_update()
                if view_forward_direction(self.context).dot(bmf.normal) > 0:
                    bmf.normal_flip()
                bmfs.append(bmf)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[-1])

    def insert_T(self):
        llc = len(self.longest_strip0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke and selected strip share first point at index 0
        if self.snap_sel01:
            self.stroke2D.reverse()
            self.stroke3D.reverse()
            self.snap_bmv0, self.snap_bmv1 = self.snap_bmv1, self.snap_bmv0
            self.snap_sel00, self.snap_sel01 = self.snap_sel01, self.snap_sel00

        # determine number of spans
        match self.mode:
            case 'BRUSH':
                nspans = math.ceil(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case _:
                assert False, f'Unhandled {self.mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create template
        pt2D = self.find_point2D(0)
        template = [
            self.find_point2D(iv / (nverts - 1)) - pt2D
            for iv in range(1, nverts)
        ]

        # use template to build spans
        bmvs = []
        bmv = bme_unshared_bmv(self.longest_strip0[0], self.longest_strip0[1]) if len(self.longest_strip0) > 1 else self.longest_strip0[0].verts[0]
        i_sel_row = 0
        for i_row, bme in enumerate(self.longest_strip0 + [None]):
            pt = location_3d_to_region_2d(self.context.region, self.context.region_data, M @ bmv.co)
            cur_bmvs = [bmv]
            if bmv == self.snap_bmv0: i_sel_row = i_row
            for offset in template:
                co = raycast_point_valid_sources(self.context, pt + offset, world=False)
                cur_bmvs.append(self.bm.verts.new(co) if co else None)
            bmvs.append(cur_bmvs)
            if not bme: break
            bmv = bme_other_bmv(bme, bmv)

        bmfs = []
        for i in range(llc):
            for j in range(nverts - 1):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmf.normal_update()
                if view_forward_direction(self.context).dot(bmf.normal) > 0:
                    bmf.normal_flip()
                bmfs.append(bmf)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[i_sel_row])

    def insert_I(self):
        llc = len(self.longest_strip0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke and selected strip share first point at index 0
        if self.snap_sel01:
            self.stroke2D.reverse()
            self.stroke3D.reverse()
            self.snap_bmv0, self.snap_bmv1 = self.snap_bmv1, self.snap_bmv0
            self.snap_sel00, self.snap_sel01 = self.snap_sel01, self.snap_sel00
            self.snap_sel10, self.snap_sel11 = self.snap_sel11, self.snap_sel10

        v0 = bme_midpoint(self.longest_strip0[-1]) - bme_midpoint(self.longest_strip0[0])
        v1 = bme_midpoint(self.longest_strip1[-1]) - bme_midpoint(self.longest_strip1[0])
        if v1.dot(v0) < 0:
            self.longest_strip1.reverse()

        # determine number of spans
        match self.mode:
            case 'BRUSH':
                nspans = math.ceil(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case _:
                assert False, f'Unhandled {self.mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create template
        pt2D = self.find_point2D(0)
        template = [
            self.find_point2D(iv / (nverts - 1)) - pt2D
            for iv in range(1, nverts - 1)
        ]
        template_length = (self.find_point2D(1) - pt2D).length
        print(template, template_length)
        print(self.stroke2D[0], self.stroke2D[-1])

        # use template to build spans
        bmvs = []
        if llc > 1:
            bmv0 = bme_unshared_bmv(self.longest_strip0[0], self.longest_strip0[1])
            bmv1 = bme_unshared_bmv(self.longest_strip1[0], self.longest_strip1[1])
        else:
            bme0, bme1 = self.longest_strip0[0], self.longest_strip1[0]
            bmv0 = bme0.verts[0]
            bmv1 = bme1.verts[0] if bme_vector(bme0).dot(bme_vector(bme1)) > 0 else bme1.verts[1]
        i_sel_row = 0
        for i_row, (bme0, bme1) in enumerate(zip(self.longest_strip0 + [None], self.longest_strip1 + [None])):
            pt0 = location_3d_to_region_2d(self.context.region, self.context.region_data, M @ bmv0.co)
            pt1 = location_3d_to_region_2d(self.context.region, self.context.region_data, M @ bmv1.co)
            scale = (pt1 - pt0).length / template_length
            cur_bmvs = [bmv0]
            if bmv0 == self.snap_bmv0: i_sel_row = i_row
            for offset in template:
                co = raycast_point_valid_sources(self.context, pt0 + offset * scale, world=False)
                print(pt0 + offset*scale, co)
                cur_bmvs.append(self.bm.verts.new(co) if co else None)
            cur_bmvs.append(bmv1)
            bmvs.append(cur_bmvs)
            if not bme0: break
            bmv0 = bme_other_bmv(bme0, bmv0)
            bmv1 = bme_other_bmv(bme1, bmv1)

        print(bmvs)

        bmfs = []
        for i in range(llc):
            for j in range(nverts - 1):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmf.normal_update()
                if view_forward_direction(self.context).dot(bmf.normal) > 0:
                    bmf.normal_flip()
                bmfs.append(bmf)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[i_sel_row])

