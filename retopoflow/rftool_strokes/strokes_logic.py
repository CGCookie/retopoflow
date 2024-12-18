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
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import Color, Frame, closest_point_segment
from ...addon_common.common.maths import clamp, Direction, Vec, Point, Point2D, Vec2D
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.utils import iter_pairs

import math
import time
from itertools import chain

r'''
need to determine shape of extrusion
key: ╎╌ stroke
     C  corner in stroke (roughly 90° angle, but not easy to detect.  what if the stroke loops over itself?)
     ǁ= selected boundary or wire edges
     @  selected cycle
     |- unselected boundary or wire edges
     O  vertex under stroke
     X  corner vertex (edges change direction)
     +  inserted verts (interpolated from selection and stroke)
notes:
- vertex under stroke must be at beginning or ending of stroke
- vertices are "under stroke" if they are selected or if "Snap Stroke to Unselected" is enabled


Implemented:

             :  Nothing    Opposite   Extend Out    Connect     Connect
             :  Selected   Side       Selected      Sides       Selected
-------------+--------------------------------------------------------------------------
             :             Equals      T-shaped     I-shaped    D-shaped
-------------+--------------------------------------------------------------------------
             :    ╎        =======     ===O===      ===O===     O=====O
             :    ╎        + + + +     + +╎+ +      + +╎+ +     ╎+ + +╎
     Strip/  :    ╎        + + + +     + +╎+ +      + +╎+ +     ╎+ + +╎
      Quad:  :    ╎        + + + +     + +╎+ +      + +╎+ +     ╎+ + +╎
             :    ╎        ╌╌╌╌╌╌╌     + +╎+ +      ===O===     C╌╌╌╌╌C
-------------+--------------------------------------------------------------------------
             :  ╭╌╌╌╮      ╭╌╌╌╌╌╮       +++        ╔═════╗
             :  ╎   ╎      ╎+ + +╎     ++ + ++      ║+ + +║
     Cycle/  :  ╎   ╎      ╎++@++╎     +++@+++      ║++@╌╌║
   Annulus:  :  ╎   ╎      ╎+ + +╎     ++ ╎ ++      ║+ + +║
          :  :  ╰╌╌╌╯      ╰╌╌╌╌╌╯       +╎+        ╚═════╝
-------------+--------------------------------------------------------------------------


Not Implemented (yet):

    O-shape
    X=====O
    ǁ + + |
    X=====O


Connect     ...
Corners     ...
L-shaped    ...
======O     ...
|+ + +╎     ...
|+ + +╎     ...
|+ + +╎     ...
O╌╌╌╌╌C     ...


Questions/Thoughts:

- What if I-shaped did not required both sides (top/bottom) to be selected?
    - What if only one side is selected?
    - What if neither side is required to be selected?
- I-shape for Annulus (inner and outer cycles selected)
- Control how the two are spanned??
    - Can rotate stroke-cycle?

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

def find_sharpest_indices(points, *, sharp_radius_percent=0.10, second_radius_percent=0.20):
    npoints = len(points)
    length = sum((p1-p0).length for (p0,p1) in iter_pairs(points, False))
    radius = sharp_radius_percent * length  # distance to travel before estimating sharpness
    second_radius = second_radius_percent * length
    sharps = []
    for i, pt in enumerate(points):
        pt0 = next((p for p in points[i::-1] if (pt - p).length >= radius), None)
        pt1 = next((p for p in points[i:]    if (pt - p).length >= radius), None)
        if pt0 and pt1:
            sharpness = ((pt0 - pt).normalized()).dot((pt - pt1).normalized())
            sharps += [(i, sharpness)]
    sharps.sort(key=lambda s: s[1])
    i0 = sharps[0][0]
    i1 = next((i1 for (i1,_) in sharps if (points[i0] - points[i1]).length >= second_radius), i0)
    return (min(i0, i1), max(i0, i1))

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
def bme_unshared_bmv(bme, bme_other):
    bmv0, bmv1 = bme.verts
    return bmv0 if bmv1 in bme_other.verts else bmv1
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

def bmes_get_prevnext_bmvs(bmes, bmv):
    # find bmes that have bmv, keep order!
    fbmes = [bme for bme in bmes if bmv in bme.verts]
    if len(fbmes) == 2:
        return [bme_other_bmv(bme, bmv) for bme in fbmes]
    # only one bme has bmv, so must be either first or last
    bme = fbmes[0]
    if bme == bmes[0]:
        return bmv, bme_other_bmv(bme, bmv)
    else:
        return bme_other_bmv(bme, bmv), bmv

def check_bmf_normals(fwd, bmfs):
    for bmf in bmfs:
        bmf.normal_update()
        if fwd.dot(bmf.normal) > 0:
            bmf.normal_flip()

def fit_template2D(template, p0, *, target=None, along=None):
    t0, t1 = template[0], template[-1]
    vt01 = t1 - t0
    lt = vt01.length
    vp01 = (target - p0) if target else (along.normalized() * lt)
    lp = vp01.length
    scale, angle = lp / lt, vecs_screenspace_angle(vt01, vp01)
    Mt = Matrix.Translation(Vector((-t0.x, -t0.y, 0)))
    Mr = Matrix.Rotation(angle, 4, 'Z')
    Ms = Matrix.Scale(scale, 4)
    Mp = Matrix.Translation(Vector((p0.x, p0.y, 0)))
    M = Mp @ Ms @ Mr @ Mt
    fitted = [ (M @ Vector((t.x, t.y, 0, 1))).xy for t in template ]
    return fitted

def vec_screenspace_angle(v):
    return -v.angle_signed(Vector((1,0)))
def vecs_screenspace_angle(v0, v1):
    a0 = vec_screenspace_angle(v0)
    a1 = vec_screenspace_angle(v1)
    a = a0 - a1
    if a > 180: a = -(a - 180)
    if a < -180: a = -(a - 180)
    return a

def get_longest_strip_cycle(bmes):
    if not bmes: return (None, None, None, None)

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
    nstrips = len(strips)
    ncycles = len(cycles)

    longest_strip0 = strips[-1] if nstrips >= 1 else None
    longest_strip1 = strips[-2] if nstrips >= 2 else None
    longest_cycle0 = cycles[-1] if ncycles >= 1 else None
    longest_cycle1 = cycles[-2] if ncycles >= 2 else None

    if longest_strip0 and longest_strip1 and len(longest_strip0) == len(longest_strip1):
        if sum(bme_length(bme) for bme in longest_strip0) < sum(bme_length(bme) for bme in longest_strip1):
            longest_strip0, longest_strip1 = longest_strip1, longest_strip0
    if longest_cycle0 and longest_cycle1 and len(longest_cycle0) == len(longest_cycle1):
        if sum(bme_length(bme) for bme in longest_cycle0) < sum(bme_length(bme) for bme in longest_cycle1):
            longest_cycle0, longest_cycle1 = longest_cycle1, longest_cycle0

    # print(f'{strips=}')
    # print(f'{cycles=}')
    # print(f'{longest_strip0=}')
    # print(f'{longest_strip1=}')
    # print(f'{longest_cycle=}')

    return (longest_strip0, longest_strip1, longest_cycle0, longest_cycle1)



class Strokes_Logic:
    def __init__(self, context, radius, stroke3D, is_cycle, span_insert_mode, fixed_span_count, extrapolate):
        self.bm, self.em = get_bmesh_emesh(context)
        bmops.flush_selection(self.bm, self.em)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.context, self.rgn, self.r3d = context, context.region, context.region_data
        self.radius = radius
        self.stroke3D = stroke3D
        self.is_cycle = is_cycle
        self.span_insert_mode = span_insert_mode
        self.fixed_span_count = fixed_span_count
        self.extrapolate = extrapolate

        self.cut_count = None

        self.process_stroke()
        self.process_selected()
        self.process_snapped()

        # TODO: handle gracefully if these functions fail
        try:
            self.insert()
        except Exception as e:
            print(f'Exception caught: {e}')
            debugger.print_exception()
        # bpy.ops.ed.undo_push(message=f'Strokes insert {time.time()}')

    def process_stroke(self):
        # project 3D stroke points to screen
        self.stroke2D = [self.project_pt(pt) for pt in self.stroke3D if pt]
        # compute total lengths, which will be used to find where new verts are to be created
        self.length2D = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke2D, self.is_cycle))
        self.length3D = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke3D, self.is_cycle))

    def process_selected(self):
        """
        Finds and analyzes all selected geometry, which is used to determine how to interpret
        an insertion (new strip/cycle, bridging selection to stroke, etc. )
        """
        self.sel_edges = [
            bme
            for bme in bmops.get_all_selected_bmedges(self.bm)
            if bme.is_wire or bme.is_boundary
            # len(bme.link_faces) < 2
            # not is_manifold() ==> len(bme.link_faces) != 2 which includes edges with 3+ faces :(
        ]
        self.average_length = (sum(bme_length(bme) for bme in self.sel_edges) / len(self.sel_edges)) if self.sel_edges else 0
        self.longest_strip0, self.longest_strip1, self.longest_cycle0, self.longest_cycle1 = get_longest_strip_cycle(self.sel_edges)
        self.longest_strip0_length = sum(bme_length(bme) for bme in self.longest_strip0) if self.longest_strip0 else None
        self.longest_strip1_length = sum(bme_length(bme) for bme in self.longest_strip1) if self.longest_strip1 else None
        self.longest_cycle0_length = sum(bme_length(bme) for bme in self.longest_cycle0) if self.longest_cycle0 else None
        self.longest_cycle1_length = sum(bme_length(bme) for bme in self.longest_cycle1) if self.longest_cycle1 else None

    def process_snapped(self):
        self.snap_bmv0 = self.bmv_closest(self.bm.verts, self.stroke3D[0])
        self.snap_bmv1 = self.bmv_closest(self.bm.verts, self.stroke3D[-1])

        # cycle
        self.snap_bmv0_cycle0 = self.snap_bmv0 and self.longest_cycle0 and any(self.snap_bmv0 in bme.verts for bme in self.longest_cycle0)
        self.snap_bmv1_cycle0 = self.snap_bmv1 and self.longest_cycle0 and any(self.snap_bmv1 in bme.verts for bme in self.longest_cycle0)
        self.snap_bmv0_cycle1 = self.snap_bmv0 and self.longest_cycle1 and any(self.snap_bmv0 in bme.verts for bme in self.longest_cycle1)
        self.snap_bmv1_cycle1 = self.snap_bmv1 and self.longest_cycle1 and any(self.snap_bmv1 in bme.verts for bme in self.longest_cycle1)

        # strip
        self.snap_bmv0_strip0 = self.snap_bmv0 and self.longest_strip0 and any(self.snap_bmv0 in bme.verts for bme in self.longest_strip0)
        self.snap_bmv1_strip0 = self.snap_bmv1 and self.longest_strip0 and any(self.snap_bmv1 in bme.verts for bme in self.longest_strip0)
        self.snap_bmv0_strip1 = self.snap_bmv0 and self.longest_strip1 and any(self.snap_bmv0 in bme.verts for bme in self.longest_strip1)
        self.snap_bmv1_strip1 = self.snap_bmv1 and self.longest_strip1 and any(self.snap_bmv1 in bme.verts for bme in self.longest_strip1)

    def insert(self):
        # TODO: reproject stroke2D and recompute length2D

        # print(f'INSERT:')
        # print(f'    {self.is_cycle=} {bool(self.longest_cycle0)=}')
        # print(f'    {self.snap_bmv0_cycle0=}  {self.snap_bmv1_cycle0=}')
        # print(f'    {bool(self.longest_strip0)=} {bool(self.longest_strip1)=}')
        # print(f'    {self.snap_bmv0_strip0=} {self.snap_bmv0_strip1=}  {self.snap_bmv1_strip0=} {self.snap_bmv1_strip1=}')

        if self.is_cycle:
            if not self.longest_cycle0:
                self.insert_cycle()
            else:
                self.insert_cycle_equals()
        else:
            if self.snap_bmv0_cycle0 or self.snap_bmv1_cycle0:
                if self.longest_cycle1 and len(self.longest_cycle0) == len(self.longest_cycle1) and ((self.snap_bmv0_cycle0 and self.snap_bmv1_cycle1) or (self.snap_bmv0_cycle1 and self.snap_bmv1_cycle0)):
                    self.insert_cycle_I()
                else:
                    self.insert_cycle_T()
            elif self.longest_strip0:
                if self.longest_strip1 and len(self.longest_strip0) == len(self.longest_strip1) and ((self.snap_bmv0_strip0 and self.snap_bmv1_strip1) or (self.snap_bmv0_strip1 and self.snap_bmv1_strip0)):
                    self.insert_strip_I()
                elif self.snap_bmv0_strip0 or self.snap_bmv1_strip0:
                    if self.snap_bmv0_strip0 and self.snap_bmv1_strip0:
                        self.insert_strip_D()
                    # elif is_L:
                    #     self.insert_strip_L()
                    else:
                        self.insert_strip_T()
                else:
                    self.insert_strip_equals()
            else:
                self.insert_strip()

        bmops.flush_selection(self.bm, self.em)


    #####################################################################################
    # utility functions

    def find_point2D(self, v):  return find_point_at(self.stroke2D, self.is_cycle, self.length2D, v)
    def find_point3D(self, v):  return find_point_at(self.stroke3D, self.is_cycle, self.length3D, v)
    def project_pt(self, pt):
        p = location_3d_to_region_2d(self.rgn, self.r3d, self.matrix_world @ pt)
        return p.xy if p else None
    def project_bmv(self, bmv):
        p = self.project_pt(bmv.co)
        return p.xy if p else None
    def bmv_closest(self, bmvs, pt3D):
        pt2D = self.project_pt(pt3D)
        bmvs = [bmv for bmv in bmvs if bmv.select and (pt := self.project_bmv(bmv)) and (pt - pt2D).length_squared < 20*20]
        if not bmvs: return None
        return min(bmvs, key=lambda bmv: (bmv.co - pt3D).length_squared)


    #####################################################################################
    # simple insertions with no bridging

    def insert_strip(self):
        match self.span_insert_mode:
            case 'BRUSH' | 'AVERAGE':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

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
        self.cut_count = nspans

    def insert_cycle(self):
        match self.span_insert_mode:
            case 'BRUSH' | 'AVERAGE':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(3, nspans)
        nverts = nspans

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
        self.cut_count = nspans


    ##############################################################################
    # basic bridging insertions

    def insert_cycle_equals(self):
        assert self.is_cycle
        assert self.longest_cycle0

        llc = len(self.longest_cycle0)

        # make sure stroke and selected cyclic bmvs have same winding direction
        n_stroke3D = compute_n(self.stroke3D)
        n_bmvs = compute_n([bme_midpoint(bme) for bme in self.longest_cycle0])
        if n_bmvs.dot(n_stroke3D) < 0:
            # turning opposite directions
            self.stroke3D.reverse()

        # align closest points between selected cyclic bmvs and stroke
        M, Mi = self.matrix_world, self.matrix_world_inv
        closest_i, closest_pt0, closest_j, closest_pt1, closest_d = None, None, None, None, float('inf')
        for i in range(llc):
            bme_pre = self.longest_cycle0[(i-1) % llc]
            bme_cur = self.longest_cycle0[i]
            bmv = bmes_shared_bmv(bme_pre, bme_cur)
            for (j, pt) in enumerate(self.stroke3D):
                d = (bmv.co - pt).length
                if d >= closest_d: continue
                closest_i, closest_pt0, closest_j, closest_pt1, closest_d = i, bmv.co, j, pt, d
        # rotate lists so self.stroke3D[0] aligns self.longest_cycle0[0]
        self.longest_cycle0 = self.longest_cycle0[closest_i:] + self.longest_cycle0[:closest_i]
        self.stroke3D = self.stroke3D[closest_j:] + self.stroke3D[:closest_j]

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                pt0 = self.project_pt(closest_pt0)
                pt1 = self.project_pt(closest_pt1)
                nspans = round((pt0 - pt1).length / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                nspans = round((closest_pt0 - closest_pt1).length / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # build spans
        bme_pre = self.longest_cycle0[-1]
        accum_dist = 0
        bmvs = [[] for i in range(nverts)]
        for bme_cur in self.longest_cycle0:
            bmv = bmes_shared_bmv(bme_pre, bme_cur)
            spt = self.find_point3D(accum_dist / self.longest_cycle0_length)
            pt0 = self.project_bmv(bmv)
            pt1 = self.project_pt(spt)
            v = pt1 - pt0

            bmvs[0].append(bmv)
            for i in range(1, nverts):
                pt = pt0 + v * (i / (nverts - 1))
                co = raycast_point_valid_sources(self.context, pt, world=False)
                bmvs[i].append(self.bm.verts.new(co) if co else None)

            accum_dist += bme_length(bme_cur)
            bme_pre = bme_cur

        # fill in quads
        bmfs = []
        for i in range(nverts-1):
            for j in range(llc):
                bmv00 = bmvs[i+0][(j+0)%llc]
                bmv01 = bmvs[i+0][(j+1)%llc]
                bmv10 = bmvs[i+1][(j+0)%llc]
                bmv11 = bmvs[i+1][(j+1)%llc]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = Mi @ view_forward_direction(self.context)
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[-1])
        self.cut_count = nspans


    def insert_strip_equals(self):
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
        match self.span_insert_mode:
            case 'BRUSH':
                # find closest distance between selected and stroke
                closest_distance2D = min(
                    (s - self.project_bmv(bmv)).length
                    for s in self.stroke2D
                    for bme in self.longest_strip0
                    for bmv in bme.verts
                )
                nspans = round(closest_distance2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                closest_distance3D = min(
                    (s - bmv.co).length
                    for s in self.stroke3D
                    for bme in self.longest_strip0
                    for bmv in bme.verts
                )
                nspans = round(closest_distance3D / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
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
            pt0 = self.project_bmv(bmv)
            pt1 = self.project_pt(spt)
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

        # fill in quads
        bmfs = []
        for i in range(nverts-1):
            for j in range(llc):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = Mi @ view_forward_direction(self.context)
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[-1])
        self.cut_count = nspans


    def insert_strip_T(self):
        llc = len(self.longest_strip0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke and selected strip share first point at index 0
        if self.snap_bmv1_strip0:
            self.stroke2D.reverse()
            self.stroke3D.reverse()
            self.snap_bmv0, self.snap_bmv1 = self.snap_bmv1, self.snap_bmv0
            self.snap_bmv0_strip0, self.snap_bmv1_strip0 = self.snap_bmv1_strip0, self.snap_bmv0_strip0

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                nspans = round(self.length3D / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create template
        template = [ self.find_point2D(iv / (nverts - 1)) for iv in range(nverts) ]
        # get orientation of stroke to selected strip
        vx = Vector((1, 0))
        bmvp, bmvn = bmes_get_prevnext_bmvs(self.longest_strip0, self.snap_bmv0)
        pp, pn = [self.project_bmv(bmv) for bmv in [bmvp, bmvn]]
        vpn, vstroke = (pn - pp), (self.stroke2D[-1] - self.stroke2D[0])
        template_len = vstroke.length
        angle = vec_screenspace_angle(vstroke) - vec_screenspace_angle(vpn)

        # use template to build spans
        bmv0 = bme_unshared_bmv(self.longest_strip0[0], self.longest_strip0[1]) if len(self.longest_strip0) > 1 else self.longest_strip0[0].verts[0]
        bmvs = []
        for i_row, bme in enumerate(self.longest_strip0 + [None]):
            pt = self.project_bmv(bmv0)

            if self.extrapolate == 'ADAPT':
                bmvp,bmvn = bmes_get_prevnext_bmvs(self.longest_strip0, bmv0)
                vpn = self.project_bmv(bmvn) - self.project_bmv(bmvp)
                bme_angle = vec_screenspace_angle(vpn)
                along = Vector((math.cos(bme_angle + angle), -math.sin(bme_angle + angle)))
                fitted = fit_template2D(template, pt, target=(pt + (along * template_len)))
                cur_bmvs = [bmv0]
                for t in fitted[1:]:
                    co = raycast_point_valid_sources(self.context, t, world=False)
                    cur_bmvs.append(self.bm.verts.new(co) if co else None)
            else:
                cur_bmvs = [bmv0]
                offset0 = template[0]
                for offset in template[1:]:
                    co = raycast_point_valid_sources(self.context, pt + offset - offset0, world=False)
                    cur_bmvs.append(self.bm.verts.new(co) if co else None)

            bmvs.append(cur_bmvs)
            if not bme: break
            bmv0 = bme_other_bmv(bme, bmv0)
        i_sel_row = next(i for (i, r) in enumerate(bmvs) if r[0] == self.snap_bmv0)

        # fill in quads
        bmfs = []
        for i in range(llc):
            for j in range(nverts - 1):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = Mi @ view_forward_direction(self.context)
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[i_sel_row])
        self.cut_count = nspans

    def insert_cycle_T(self):
        '''
        forced on: adapt extrapolation
        '''
        llc = len(self.longest_cycle0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke and selected cycle share first point at index 0
        if self.snap_bmv1_cycle0:
            self.stroke2D.reverse()
            self.stroke3D.reverse()
            self.snap_bmv0, self.snap_bmv1 = self.snap_bmv1, self.snap_bmv0
            self.snap_bmv0_cycle0, self.snap_bmv1_cycle0 = self.snap_bmv1_cycle0, self.snap_bmv0_cycle0

        # rotate cycle so bme[1] and bme[2] have hovered vert
        # note: if rotated to bme[0] and bme[-1], there might be ambiguity in which side comes first
        idx = next((i for (i, bme) in enumerate(self.longest_cycle0) if self.snap_bmv0 in bme.verts), None)
        idx = (idx - 1) % len(self.longest_cycle0)
        self.longest_cycle0 = self.longest_cycle0[idx:] + self.longest_cycle0[:idx]

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                nspans = round(self.length3D / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create template
        template = [ self.find_point2D(iv / (nverts - 1)) for iv in range(nverts) ]
        # get orientation of stroke to selected cycle
        vx = Vector((1, 0))
        bmvp, bmvn = bmes_get_prevnext_bmvs(self.longest_cycle0, self.snap_bmv0)
        pp, pn = [self.project_bmv(bmv) for bmv in [bmvp, bmvn]]
        vpn, vstroke = (pn - pp), (self.stroke2D[-1] - self.stroke2D[0])
        template_len = vstroke.length
        angle = vec_screenspace_angle(vstroke) - vec_screenspace_angle(vpn)

        # use template to build spans
        bmv0 = bme_unshared_bmv(self.longest_cycle0[0], self.longest_cycle0[1])
        bmvs = []
        for i_row, bme in enumerate(self.longest_cycle0):
            pt = self.project_bmv(bmv0)

            bmvp, bmvn = bmes_get_prevnext_bmvs(self.longest_cycle0, bmv0)
            if i_row == 0: bmvp, bmvn = bmvn, bmvp
            vpn = self.project_bmv(bmvn) - self.project_bmv(bmvp)
            bme_angle = vec_screenspace_angle(vpn)
            along = Vector((math.cos(bme_angle + angle), -math.sin(bme_angle + angle)))
            fitted = fit_template2D(template, pt, target=(pt + (along * template_len)))
            cur_bmvs = [bmv0]
            for t in fitted[1:]:
                co = raycast_point_valid_sources(self.context, t, world=False)
                cur_bmvs.append(self.bm.verts.new(co) if co else None)

            bmvs.append(cur_bmvs)
            bmv0 = bme_other_bmv(bme, bmv0)
        i_sel_row = next(i for (i, r) in enumerate(bmvs) if r[0] == self.snap_bmv0)

        # fill in quads
        bmfs = []
        for i0 in range(llc):
            i1 = (i0 + 1) % len(self.longest_cycle0)
            for j in range(nverts - 1):
                bmv00 = bmvs[i0][j+0]
                bmv01 = bmvs[i0][j+1]
                bmv10 = bmvs[i1][j+0]
                bmv11 = bmvs[i1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = Mi @ view_forward_direction(self.context)
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[i_sel_row])
        self.cut_count = nspans


    def insert_strip_I(self):
        llc = len(self.longest_strip0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke starts on longest strip
        if self.snap_bmv0_strip1:
            self.stroke2D.reverse()
            self.stroke3D.reverse()
            self.snap_bmv0, self.snap_bmv1 = self.snap_bmv1, self.snap_bmv0
            self.snap_bmv0_strip0, self.snap_bmv0_strip1 = self.snap_bmv0_strip1, self.snap_bmv0_strip0
            self.snap_bmv1_strip0, self.snap_bmv1_strip1 = self.snap_bmv1_strip1, self.snap_bmv1_strip0

        v0 = bme_midpoint(self.longest_strip0[-1]) - bme_midpoint(self.longest_strip0[0])
        v1 = bme_midpoint(self.longest_strip1[-1]) - bme_midpoint(self.longest_strip1[0])
        if v1.dot(v0) < 0:
            self.longest_strip1.reverse()

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                nspans = round(self.length3D / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create template
        pt2D = self.find_point2D(0)
        template = [
            self.find_point2D(iv / (nverts - 1)) - pt2D
            for iv in range(nverts)
        ]
        template_length = (self.find_point2D(1) - pt2D).length

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
            pt0 = self.project_bmv(bmv0)
            pt1 = self.project_bmv(bmv1)
            fitted = fit_template2D(template, pt0, target=pt1)
            #scale = (pt1 - pt0).length / template_length
            cur_bmvs = [bmv0]
            for t in fitted[1:-1]:
                # co = raycast_point_valid_sources(self.context, pt0 + offset * scale, world=False)
                co = raycast_point_valid_sources(self.context, t, world=False)
                cur_bmvs.append(self.bm.verts.new(co) if co else None)
            cur_bmvs.append(bmv1)
            bmvs.append(cur_bmvs)
            if bmv0 == self.snap_bmv0: i_sel_row = i_row
            if not bme0: break
            bmv0 = bme_other_bmv(bme0, bmv0)
            bmv1 = bme_other_bmv(bme1, bmv1)

        # fill in quads
        bmfs = []
        for i in range(llc):
            for j in range(nverts - 1):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = Mi @ view_forward_direction(self.context)
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[i_sel_row])
        self.cut_count = nspans


    def insert_cycle_I(self):
        llc = len(self.longest_cycle0)
        M, Mi = self.matrix_world, self.matrix_world_inv

        # make sure stroke starts on longest cycle
        if self.snap_bmv0_cycle1:
            self.stroke2D.reverse()
            self.stroke3D.reverse()
            self.snap_bmv0, self.snap_bmv1 = self.snap_bmv1, self.snap_bmv0
            self.snap_bmv0_cycle0, self.snap_bmv0_cycle1 = self.snap_bmv0_cycle1, self.snap_bmv0_cycle0
            self.snap_bmv1_cycle0, self.snap_bmv1_cycle1 = self.snap_bmv1_cycle1, self.snap_bmv1_cycle0

        # make sure cycles are oriented the same
        mids0 = [bme_midpoint(bme) for bme in self.longest_cycle0]
        mids1 = [bme_midpoint(bme) for bme in self.longest_cycle1]
        mid0, mid1 = sum(mids0, Vector((0,0,0))) / llc, sum(mids1, Vector((0,0,0))) / llc
        d0 = sum(((p0 - mid0).cross(p1 - mid0).normalized() for (p0, p1) in iter_pairs(mids0, True)), Vector((0,0,0)))
        d1 = sum(((p0 - mid1).cross(p1 - mid1).normalized() for (p0, p1) in iter_pairs(mids1, True)), Vector((0,0,0)))
        if d0.dot(d1) < 0: self.longest_cycle1.reverse()

        # rotate both cycles so stroke hovers both at 0
        cycle0_bme = next((bme0 for (bme0,bme1) in iter_pairs(self.longest_cycle0, True) if bmes_shared_bmv(bme0, bme1) == self.snap_bmv0), None)
        cycle1_bme = next((bme0 for (bme0,bme1) in iter_pairs(self.longest_cycle1, True) if bmes_shared_bmv(bme0, bme1) == self.snap_bmv1), None)
        idx = self.longest_cycle0.index(cycle0_bme)
        self.longest_cycle0 = self.longest_cycle0[idx:] + self.longest_cycle0[:idx]
        idx = self.longest_cycle1.index(cycle1_bme)
        self.longest_cycle1 = self.longest_cycle1[idx:] + self.longest_cycle1[:idx]

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                nspans = round(self.length2D / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                nspans = round(self.length3D / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create template
        pt2D = self.find_point2D(0)
        template = [
            self.find_point2D(iv / (nverts - 1)) - pt2D
            for iv in range(nverts)
        ]
        template_length = (self.find_point2D(1) - pt2D).length

        # use template to build spans
        bmvs = []
        bmv0 = bme_unshared_bmv(self.longest_cycle0[0], self.longest_cycle0[1])
        bmv1 = bme_unshared_bmv(self.longest_cycle1[0], self.longest_cycle1[1])
        i_sel_row = 0
        for i_row, (bme0, bme1) in enumerate(zip(self.longest_cycle0, self.longest_cycle1)):
            pt0, pt1 = self.project_bmv(bmv0), self.project_bmv(bmv1)
            scale = (pt1 - pt0).length / template_length
            fitted = fit_template2D(template, pt0, target=pt1)
            cur_bmvs = [bmv0]
            if bmv0 == self.snap_bmv0: i_sel_row = i_row
            for t in fitted[1:-1]:
                co = raycast_point_valid_sources(self.context, t, world=False)
                cur_bmvs.append(self.bm.verts.new(co) if co else None)
            cur_bmvs.append(bmv1)
            bmvs.append(cur_bmvs)
            bmv0 = bme_other_bmv(bme0, bmv0)
            bmv1 = bme_other_bmv(bme1, bmv1)

        print(llc, nverts)
        print(len(bmvs), len(bmvs[0]))


        # fill in quads
        bmfs = []
        for i0 in range(llc):
            i1 = (i0 + 1) % llc
            for j in range(nverts - 1):
                bmv00 = bmvs[i0][j+0]
                bmv01 = bmvs[i0][j+1]
                bmv10 = bmvs[i1][j+0]
                bmv11 = bmvs[i1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)

        fwd = Mi @ view_forward_direction(self.context)
        check_bmf_normals(fwd, bmfs)

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[i_sel_row])
        self.cut_count = nspans


    def insert_strip_D(self):
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
            print('REVERSING!!!!!!!!!!!!!!!!')
            self.stroke2D.reverse()
            self.stroke3D.reverse()

        # find two corners, which are the sharpest points
        idx0, idx1 = find_sharpest_indices(self.stroke2D)
        stroke0, stroke1, stroke2 = self.stroke2D[:idx0], self.stroke2D[idx0:idx1], self.stroke2D[idx1:]
        stroke2.reverse()
        length0 = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke0, False))
        length1 = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke1, False))
        length2 = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke2, False))

        # determine number of spans
        match self.span_insert_mode:
            case 'BRUSH':
                nspans = round(min(length0, length2) / (2 * self.radius))
            case 'FIXED':
                nspans = self.fixed_span_count
            case 'AVERAGE':
                l0 = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke3D[:idx0], False))
                l2 = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke3D[idx1:], False))
                nspans = round(min(l0, l2) / self.average_length)
            case _:
                assert False, f'Unhandled {self.span_insert_mode=}'
        nspans = max(1, nspans)
        nverts = nspans + 1

        # create templates
        template0 = [find_point_at(stroke0, False, length0, iv / (nverts-1)) for iv in range(nverts)]
        template2 = [find_point_at(stroke2, False, length2, iv / (nverts-1)) for iv in range(nverts)]

        # build spans
        bmv0 = bme_unshared_bmv(self.longest_strip0[0], self.longest_strip0[1]) if len(self.longest_strip0) > 1 else self.longest_strip0[0].verts[0]
        bmvs = []
        for i, bme in enumerate(self.longest_strip0 + [None]):
            v = i / llc
            pt0 = self.project_bmv(bmv0)
            pt1 = find_point_at(stroke1, False, length1, v)
            fitted0 = fit_template2D(template0, pt0, target=pt1)
            fitted2 = fit_template2D(template2, pt0, target=pt1)
            cur_bmvs = [bmv0]
            for (p0, p2) in zip(fitted0[1:], fitted2[1:]):
                p = lerp(p0, p2, v)
                co = raycast_point_valid_sources(self.context, p, world=False)
                cur_bmvs.append(self.bm.verts.new(co) if co else None)
            bmvs.append(cur_bmvs)
            if not bme: break
            bmv0 = bme_other_bmv(bme, bmv0)

        # fill in quads
        bmfs = []
        for i in range(llc):
            for j in range(nverts - 1):
                bmv00 = bmvs[i+0][j+0]
                bmv01 = bmvs[i+0][j+1]
                bmv10 = bmvs[i+1][j+0]
                bmv11 = bmvs[i+1][j+1]
                if not (bmv00 and bmv01 and bmv10 and bmv11): continue
                bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
                bmfs.append(bmf)
        fwd = Mi @ view_forward_direction(self.context)
        check_bmf_normals(fwd, bmfs)


        self.cut_count = nspans


def lerp(p0, p1, v):
    return p0 + (p1 - p0) * v