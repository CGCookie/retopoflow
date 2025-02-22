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
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree
from bpy_extras.view3d_utils import location_3d_to_region_2d
from ..common.bmesh import (
    get_bmesh_emesh,
    bme_midpoint, get_boundary_strips_cycles,
    bme_other_bmv,
    bmes_shared_bmv,
    bme_unshared_bmv,
    bmvs_shared_bme,
    bme_vector,
    bme_length,
)
from ..common.bmesh_maths import (
    find_point_at,
    find_closest_point,
    find_sharpest_indices,
    find_sharpest_index,
    compute_n,
    bmes_get_prevnext_bmvs,
    get_strip_bmvs,
    check_bmf_normals,
    fit_template2D,
    vec_screenspace_angle,
    vecs_screenspace_angle,
    get_boundary_cycle,
    get_boundary_strips,
    get_longest_strip_cycle,
    generate_point_inside_bmf,
)
from ..common.raycast import raycast_point_valid_sources, nearest_point_valid_sources, nearest_normal_valid_sources
from ..common.maths import (
    view_forward_direction,
    lerp,
    point_to_bvec3,
    vector_to_bvec3,
    point_to_bvec4,
    distance_point_linesegment,
    distance_point_bmedge,
)
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bezier import interpolate_cubic
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import (
    closest_point_segment,
    segment2D_intersection,
    clamp, sign,
    Direction,
    closest_points_segments,
)
from ...addon_common.common.utils import iter_pairs, enumerate_reversed, enumerate_direction

import math
from itertools import chain


r'''

Desmos demo: https://www.desmos.com/geometry/okxgsddxk2

NOT HANDLING CYCLIC STROKES, YET

'''



def trim_stroke_to_bmf(stroke, bmf, from_start):
    if not bmf: return None

    # find the first stroke pt outside the snapped bmf
    point_inside_bmf = generate_point_inside_bmf(bmf)
    i = next((i for (i,pt) in enumerate_direction(stroke, from_start) if not point_inside_bmf(pt)), None)
    if i is None: return {'error': 'stroke totally inside the hovered face'}

    # split stroke into inside bmf and outside bmf
    if from_start: inside,  outside = stroke[:i], stroke[i:]
    else:          outside, inside  = stroke[:i], stroke[i:]
    search = inside or ([stroke[0]] if from_start else [stroke[-1]])

    # find closest bme of bmf to search part of stroke
    bme = min(bmf.edges, key=lambda bme: min(distance_point_bmedge(pt, bme) for pt in search))
    return {
        'error': None,
        'stroke': outside,
        'bmf.index': bmf.index,
        'bme.index': bme.index,
        'bme.center': bme_midpoint(bme),
        'bme.radius': bme_length(bme) / 2,
    }

def warp_stroke(stroke, end0, end1, fn_snap_point):
    if not stroke or (not end0 and not end1):
        return stroke
    s0, s1 = stroke[0], stroke[-1]
    if end0 and not end1:
        offset = end0 - s0
        return [ fn_snap_point(pt + offset) for pt in stroke ]
    elif not end0 and end1:
        offset = end1 - s1
        return [ fn_snap_point(pt + offset) for pt in stroke ]
    ec, es = (end0 + end1) / 2, (end0 - end1).length
    sc, ss = (s0 + s1) / 2, (s0 - s1).length
    scale = es / ss
    return [ fn_snap_point(ec + (pt - sc) * scale) for pt in stroke ]

def stroke_angles(stroke, width, split_angle, fn_snap_normal):
    # determine where stroke angles very strongly
    l = []
    for (i, p) in enumerate(stroke):
        pp = next((pp for pp in stroke[i::-1] if (p - pp).length >= width), None)
        pn = next((pn for pn in stroke[i:]    if (p - pn).length >= width), None)
        if not pp or not pn: continue

        n = Direction(fn_snap_normal(p))
        dp, dn = Direction(p - pp), Direction(pn - p)
        angle = math.degrees(dp.signed_angle_between(dn, n))
        if abs(angle) < split_angle: continue
        l.append((i, p, int(angle)))

    # find largest angle of connected "islands" (run of points within width of neighboring points)
    biggest = []
    for (_, pp, _), (i, p, a) in zip(l[:-1], l[1:]):
        if not biggest or (pp - p).length >= width:
            # either first point (and therefore biggest by default) or too far away from previous (disconnected)
            biggest += [(i, a)]
        else:
            # connected to previous, so find biggest angle of current island
            biggest[-1] = max(biggest[-1], (i, a), key=lambda pa: abs(pa[1]))

    return biggest



class PolyStrips_Logic:
    def __init__(self, context, radius2D, stroke3D_local, is_cycle, length2D, snap_bmf0, snap_bmf1, split_angle):
        # store context data to make it more convenient
        # note: this will be redone whenever create() is called
        self.update_context(context)

        # self.process_stroke() will set self.error if something went wrong
        # use this indicator to fail gracefully rather than throwing/catching exception?
        self.error = False

        ##############################
        # store passed parameters
        M, Mi = self.matrix_world, self.matrix_world_inv
        self.radius2D = radius2D
        self.stroke3D_local = stroke3D_local
        self.is_cycle = is_cycle
        self.snap_bmf0 = snap_bmf0
        self.snap_bmf1 = snap_bmf1
        self.split_angle = split_angle  # clamp!?

        #################################
        # initial settings
        self.count_min = 3 if (snap_bmf0 and snap_bmf1) else 2     # must be set before self.count
        self.count = max(2, round(length2D / (2 * radius2D)) + 1)  # must be set after self.count_min
        self.width = self.compute_length3D(self.stroke3D_local, self.is_cycle) / (self.count * 2 - 1)

        ######################################################################
        # process stroke data, such as projecting and computing length
        self.process_stroke(context)

        ###############################################
        # fail gracefully if something went wrong
        if self.error:
            self.count_min = 0  # must be set before self.count
            self.count = 0      # must be set after self.count_min
            self.width = 0
            return

    @property
    def count(self): return self._count
    @count.setter
    def count(self, v): self._count = max(int(v), self.count_min)

    def create(self, context):
        if self.error: return
        self.update_context(context)

        bvh = self.bvh
        M, Mi = self.matrix_world, self.matrix_world_inv

        # TODO: Remove this limitation!
        if self.is_cycle:
            print(f'Warning: PolyStrips cannot handle cyclic strokes, yet')
            return

        angles = stroke_angles(
            self.stroke3D_local,
            self.width,
            self.split_angle,
            lambda p: nearest_normal_valid_sources(context, M @ p, world=False),
        )
        print(f'{angles=}')

        ###########################################################################
        # sample the stroke and compute various properties of sample

        count = (self.count - 1) if self.snap0 and self.snap1 else self.count
        self.npoints = count + (count - 1)
        nsamples = (self.npoints + 2) if not (self.snap0 or self.snap1) else self.npoints
        self.points = [
            find_point_at(self.stroke3D_local, self.is_cycle, (i / (nsamples - 1)))
            for i in range(nsamples)
        ]
        self.points = [ nearest_point_valid_sources(context, M @ pt, world=False) for pt in self.points ]
        self.normals = [ Direction(nearest_normal_valid_sources(context, M @ pt, world=False)) for pt in self.points ]
        self.forwards = [ Direction(p1 - p0) for (p0, p1) in iter_pairs(self.points, self.is_cycle) ]
        self.forwards += [ self.forwards[-1] ]
        # backwards is essentially the same as forwards, but doing it this way is slightly easier to understand
        self.backwards = [ Direction(p0 - p1) for (p0, p1) in iter_pairs(self.points, self.is_cycle) ]
        self.backwards = [ self.backwards[0] ] + self.backwards
        self.rights = [
            (f.cross(n).normalize() + n.cross(b).normalize()).normalize()
            for (b, f, n) in zip(self.backwards, self.forwards, self.normals)
        ]


        ######################################
        # create bmverts

        w0 = self.snap0['bme.radius'] if self.snap0 else self.width
        w1 = self.snap1['bme.radius'] if self.snap1 else self.width
        wm = self.width
        bmvs = [[], []]

        # create bmverts at beginning of stroke
        p, pn = self.points[0], self.points[1]
        f, r = self.forwards[0], self.rights[0]
        if self.snap0:
            bme = self.bm.edges[self.snap0['bme.index']]
            bmv0, bmv1 = bme.verts[0], bme.verts[1]
            co0, co1 = M @ bmv0.co, M @ bmv1.co
            if r.dot(co1 - co0) > 0:
                bmv0, bmv1 = bmv1, bmv0
            bmvs[0] += [bmv0]
            bmvs[1] += [bmv1]
        else:
            bmvs[0] += [ self.bm.verts.new(p + r * wm) ]
            bmvs[1] += [ self.bm.verts.new(p - r * wm) ]

        # create bmverts along stroke
        i_start = 2 if (self.snap0 or self.snap1) else 2
        i_end = len(self.points) - (2 if (self.snap0 or self.snap1) else 1)
        for i in range(i_start, i_end, 2):
            pp, p, pn = self.points[i-1:i+2]

            # compute width
            if self.snap0 and not self.snap1:
                v = i / (len(self.points) - 1)
                w = w0 + (wm - w0) * v
            elif not self.snap0 and self.snap1:
                v = i / (len(self.points) - 1)
                w = wm + (w1 - wm) * v
            else:
                v = 2 * i / (len(self.points) - 1)
                if v < 1: w = w0 + (wm - w0) * v
                else:     w = wm + (w1 - wm) * (v-1)

            # compute offset based on bend
            # dp, dn = Direction(p - pp), Direction(pn - p)
            # angle = dp.signed_angle_between(dn, self.normals[i])
            # size = (pn - pp).length
            # offset = math.pow(math.sin(angle), 2.0) * w * (w / size)

            r = self.rights[i]
            rm0 = w # + offset
            rm1 = rm0 - 2 * w
            bmvs[0] += [ self.bm.verts.new(p + r * rm0) ]
            bmvs[1] += [ self.bm.verts.new(p + r * rm1) ]

        # create bmverts at ending of stroke
        p, pp = self.points[-1], self.points[-2]
        f, r = self.forwards[-1], self.rights[-1]
        if self.snap1:
            bme = self.bm.edges[self.snap1['bme.index']]
            bmv0, bmv1 = bme.verts[0], bme.verts[1]
            co0, co1 = M @ bmv0.co, M @ bmv1.co
            if r.dot(co1 - co0) > 0:
                bmv0, bmv1 = bmv1, bmv0
            bmvs[0] += [bmv0]
            bmvs[1] += [bmv1]
        else:
            bmvs[0] += [ self.bm.verts.new(p + r * wm) ]
            bmvs[1] += [ self.bm.verts.new(p - r * wm) ]

        # snap newly created bmverts to source
        for bmv in chain(bmvs[0], bmvs[1]):
            bmv.co = nearest_point_valid_sources(context, M @ bmv.co, world=False)

        # insert bmverts of snapped faces
        # IMPORTANT: must happen _BEFORE_ faces are created!
        bmvs_snap0 = list(self.bm.faces[self.snap0['bmf.index']].verts) if self.snap0 else []
        bmvs_snap1 = list(self.bm.faces[self.snap1['bmf.index']].verts) if self.snap1 else []


        ######################################################
        # create bmfaces

        bmfs = []
        for i in range(0, len(bmvs[0])-1):
            bmv00, bmv01 = bmvs[0][i], bmvs[0][i+1]
            bmv10, bmv11 = bmvs[1][i], bmvs[1][i+1]
            bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
            bmfs += [ bmf ]
        fwd = Mi @ view_forward_direction(self.context)
        check_bmf_normals(fwd, bmfs)


        ########################################
        # select newly created geometry

        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[0] + bmvs[1] + bmvs_snap0 + bmvs_snap1)
        bmops.flush_selection(self.bm, self.em)


    def update_context(self, context):
        # this should be called whenever the context could change

        self.context = context
        self.rgn, self.r3d = context.region, context.region_data

        # gather bmesh data
        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        bmops.flush_selection(self.bm, self.em)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.bm.verts.ensure_lookup_table()
        self.bm.edges.ensure_lookup_table()
        self.bm.faces.ensure_lookup_table()
        self.bvh = BVHTree.FromBMesh(self.bm)

    def compute_length3D(self, stroke3D_local, is_cycle):
        M = self.matrix_world
        return sum(
            ((M @ p1) - (M @ p0)).length
            for (p0, p1) in iter_pairs(stroke3D_local, is_cycle)
        )


    def process_stroke(self, context):
        M, Mi = self.matrix_world, self.matrix_world_inv

        # deal with snapping stroke to bmfs hovered at beginning and ending of stroke
        self.snap0 = trim_stroke_to_bmf(self.stroke3D_local, self.snap_bmf0, True)
        if self.snap0:
            if self.snap0['error']:
                self.error = True
                print(f'ERROR: {self.snap0["error"]}')
                return
            self.stroke3D_local = self.snap0['stroke']

        self.snap1 = trim_stroke_to_bmf(self.stroke3D_local, self.snap_bmf1, False)
        if self.snap1:
            if self.snap1['error']:
                self.error = True
                print(f'ERROR: {self.snap1["error"]}')
                return
            self.stroke3D_local = self.snap1['stroke']

        # warp stroke to better fit snapped geo
        self.stroke3D_local = warp_stroke(
            self.stroke3D_local,
            None if not self.snap0 else self.snap0['bme.center'],
            None if not self.snap1 else self.snap1['bme.center'],
            lambda p: Mi @ nearest_point_valid_sources(context, M @ p),
        )



        ###################################
        # finalize needed properties

        self.stroke3D_world = [(M @ pt) for pt in self.stroke3D_local]

        # project 3D stroke points to screen
        self.stroke2D = [self.project_pt(pt) for pt in self.stroke3D_world if pt]

        # compute total lengths, which will be used to find where new verts are to be created
        self.length2D = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke2D, self.is_cycle))
        self.length3D = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke3D_world, self.is_cycle))




    #####################################################################################
    # utility functions

    def find_point2D(self, v):  return find_point_at(self.stroke2D, self.is_cycle, v)
    def find_point3D(self, v):  return find_point_at(self.stroke3D_world, self.is_cycle, v)
    def project_pt(self, pt):
        p = location_3d_to_region_2d(self.rgn, self.r3d, self.matrix_world @ pt)
        return p.xy if p else None
    def project_bmv(self, bmv):
        p = self.project_pt(bmv.co)
        return p.xy if p else None
    def bmv_closest(self, bmvs, pt3D):
        pt2D = self.project_pt(pt3D)
        # bmvs = [bmv for bmv in bmvs if bmv.select and (pt := self.project_bmv(bmv)) and (pt - pt2D).length_squared < 20*20]
        bmvs = [bmv for bmv in bmvs if (pt := self.project_bmv(bmv)) and (pt - pt2D).length_squared < 20*20]
        if not bmvs: return None
        return min(bmvs, key=lambda bmv: (bmv.co - pt3D).length_squared)
