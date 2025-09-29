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
    has_mirror_x, has_mirror_y, has_mirror_z, mirror_threshold,
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
    xform_direction,
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
    sign_threshold,
)
from ...addon_common.common.utils import iter_pairs, enumerate_reversed, enumerate_direction, dedup

import math
from itertools import chain


r'''

Desmos demo: https://www.desmos.com/geometry/okxgsddxk2

NOT HANDLING CYCLIC STROKES, YET

'''



def trim_stroke_to_bmf(stroke, bmf, from_start, limit_bmes=None):
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
    if limit_bmes:
        bmes = limit_bmes
    else:
        bmes = bmf.edges
    if not bmes: return None
    bme = min(bmes, key=lambda bme: min(distance_point_bmedge(pt, bme) for pt in search))
    return {
        'error': None,
        'stroke': outside,
        'bmf': bmf,
        'bme': bme,
        'bme.center': bme_midpoint(bme),
        'bme.radius': bme_length(bme) / 2,
    }

def warp_stroke(context, stroke, end0, end1, fn_snap_point):
    if not stroke or (not end0 and not end1):
        return stroke
    s0, s1 = stroke[0], stroke[-1]
    if end0 and not end1:
        offset = end0 - s0
        return [ fn_snap_point(context, pt + offset) for pt in stroke ]
    elif not end0 and end1:
        offset = end1 - s1
        return [ fn_snap_point(context, pt + offset) for pt in stroke ]
    ec, es = (end0 + end1) / 2, (end0 - end1).length
    sc, ss = (s0 + s1) / 2, (s0 - s1).length
    scale = es / ss
    return [ fn_snap_point(context, ec + (pt - sc) * scale) for pt in stroke ]

def stroke_angles(stroke, width, split_angle, fn_snap_normal):
    # convert radians to degrees
    split_angle = math.degrees(split_angle)

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

    indices = [0] + [i for (i,_) in biggest] + [len(stroke)]
    return indices



class PolyStrips_Logic:
    def __init__(self, context, radius2D, stroke3D_local, is_cycle, length2D, snap_bmf0, snap_bmf1, split_angle, mirror_correct):
        # store context data to make it more convenient
        # note: this will be redone whenever create() is called
        self.update_context(context)

        # self.process_stroke() will set self.error if something went wrong
        # use this indicator to fail gracefully rather than throwing/catching exception?
        self.error = False

        # TODO: Remove this limitation!
        if is_cycle:
            self.error = True
            print(f'Warning: PolyStrips cannot handle cyclic strokes, yet')
            return

        ##############################
        # store passed parameters
        M, Mi = self.matrix_world, self.matrix_world_inv
        self.radius2D = radius2D
        self.stroke3D_local_orig = stroke3D_local
        self.is_cycle = is_cycle
        self.snap_bmf0_index = snap_bmf0.index if snap_bmf0 else None
        self.snap_bmf1_index = snap_bmf1.index if snap_bmf1 else None
        self.split_angle = split_angle  # clamp!?
        self.mirror_correct = mirror_correct
        self.show_mirror_correct = False

        #################################
        # initial settings
        self.initial = True
        self.initial_count = max(2, round(length2D / (2 * radius2D)) + 1)
        self.initial_width = self.compute_length3D(self.stroke3D_local_orig, self.is_cycle) / (self.initial_count * 2 - 1)
        self.strip_count = 0
        self.count_mins = []
        self.counts = []
        self.widths = []

        # self.count_min = 3 if (snap_bmf0 and snap_bmf1) else 2     # must be set before self.count
        # self.count = max(2, round(length2D / (2 * radius2D)) + 1)  # must be set after self.count_min
        # self.width = self.compute_length3D(self.stroke3D_local, self.is_cycle) / (self.count * 2 - 1)

    @property
    def count0(self): return self.counts[0] if self.strip_count >= 1 else 0
    @count0.setter
    def count0(self, v):
        if self.strip_count < 1: return
        self.counts[0] = max(self.count_mins[0], v)
    @property
    def count1(self): return self.counts[1] if self.strip_count >= 2 else 0
    @count1.setter
    def count1(self, v):
        if self.strip_count < 2: return
        self.counts[1] = max(self.count_mins[1], v)
    @property
    def count2(self): return self.counts[2] if self.strip_count >= 3 else 0
    @count2.setter
    def count2(self, v):
        if self.strip_count < 3: return
        self.counts[2] = max(self.count_mins[2], v)

    @property
    def width0(self): return self.widths[0] if self.strip_count >= 1 else 0
    @width0.setter
    def width0(self, v):
        if self.strip_count < 1: return
        self.widths[0] = v
    @property
    def width1(self): return self.widths[1] if self.strip_count >= 2 else 0
    @width1.setter
    def width1(self, v):
        if self.strip_count < 2: return
        self.widths[1] = v
    @property
    def width2(self): return self.widths[2] if self.strip_count >= 3 else 0
    @width2.setter
    def width2(self, v):
        if self.strip_count < 3: return
        self.widths[2] = v


    def create(self, context):
        if self.error: return
        self.update_context(context)

        ##############################
        # handle mirror
        self.stroke3D_local = self.stroke3D_local_orig
        self.mirror = set()
        if has_mirror_x(context): self.mirror.add('x')
        if has_mirror_y(context): self.mirror.add('y')
        if has_mirror_z(context): self.mirror.add('z')
        self.show_mirror_correct = bool(self.mirror)
        self.mirror_threshold = mirror_threshold(context)
        mirror_counts = {'x':[0,0,0], 'y':[0,0,0], 'z':[0,0,0]}
        self.mirror_side = Vector((1,1,1))
        if self.mirror:
            match self.mirror_correct:
                case 'FIRST':
                    if 'x' in self.mirror:
                        self.mirror_side.x = next((s for co in self.stroke3D_local if (s := sign_threshold(co.x, self.mirror_threshold)) != 0), 1)
                    if 'y' in self.mirror:
                        self.mirror_side.y = next((s for co in self.stroke3D_local if (s := sign_threshold(co.y, self.mirror_threshold)) != 0), 1)
                    if 'z' in self.mirror:
                        self.mirror_side.x = next((s for co in self.stroke3D_local if (s := sign_threshold(co.z, self.mirror_threshold)) != 0), 1)
                case 'LAST':
                    if 'x' in self.mirror:
                        self.mirror_side.x = next((s for co in self.stroke3D_local[::-1] if (s := sign_threshold(co.x, self.mirror_threshold)) != 0), 1)
                    if 'y' in self.mirror:
                        self.mirror_side.y = next((s for co in self.stroke3D_local[::-1] if (s := sign_threshold(co.y, self.mirror_threshold)) != 0), 1)
                    if 'z' in self.mirror:
                        self.mirror_side.x = next((s for co in self.stroke3D_local[::-1] if (s := sign_threshold(co.z, self.mirror_threshold)) != 0), 1)
                case 'MOST':
                    if 'x' in self.mirror:
                        count_neg = sum(1 if sign_threshold(co.x, self.mirror_threshold) < 0 else 0 for co in self.stroke3D_local)
                        count_pos = sum(1 if sign_threshold(co.x, self.mirror_threshold) > 0 else 0 for co in self.stroke3D_local)
                        if count_neg > count_pos: self.mirror_side.x = -1
                    if 'y' in self.mirror:
                        count_neg = sum(1 if sign_threshold(co.y, self.mirror_threshold) < 0 else 0 for co in self.stroke3D_local)
                        count_pos = sum(1 if sign_threshold(co.y, self.mirror_threshold) > 0 else 0 for co in self.stroke3D_local)
                        if count_neg > count_pos: self.mirror_side.y = -1
                    if 'z' in self.mirror:
                        count_neg = sum(1 if sign_threshold(co.z, self.mirror_threshold) < 0 else 0 for co in self.stroke3D_local)
                        count_pos = sum(1 if sign_threshold(co.z, self.mirror_threshold) > 0 else 0 for co in self.stroke3D_local)
                        if count_neg > count_pos: self.mirror_side.z = -1

            self.stroke3D_local = [
                co * Vector((
                    0 if 'x' in self.mirror and sign_threshold(co.x, self.mirror_threshold) != self.mirror_side.x else 1,
                    0 if 'y' in self.mirror and sign_threshold(co.y, self.mirror_threshold) != self.mirror_side.y else 1,
                    0 if 'z' in self.mirror and sign_threshold(co.z, self.mirror_threshold) != self.mirror_side.z else 1,
                ))
                for co in self.stroke3D_local
            ]



        bvh = self.bvh
        M, Mi = self.matrix_world, self.matrix_world_inv

        select_geo = []

        # deal with snapping stroke to bmfs hovered at beginning and ending of stroke
        snap_bmf_start, snap_bmf_end = None, None
        if self.snap_bmf0_index is not None:
            snap_bmf_start = self.bm.faces[self.snap_bmf0_index]
        if self.snap_bmf1_index is not None:
            snap_bmf_end = self.bm.faces[self.snap_bmf1_index]

        # break stroke into segments
        strips = stroke_angles(
            self.stroke3D_local,
            self.initial_width,
            self.split_angle,
            lambda p: nearest_normal_valid_sources(context, M @ p, world=False),
        )
        nstroke = len(self.stroke3D_local)

        # create quads based on segments
        bmfs = []
        nstrip_count = len(strips) - 1
        actual_strip_count = 0
        if self.strip_count != nstrip_count:
            # reset data
            self.count_mins, self.counts, self.widths = [], [], []
        ncount_mins, ncounts, nwidths = [], [], []
        for i_strip, (i0, i1) in enumerate(iter_pairs(strips, False)):
            if i0 == i1: continue
            stroke3D_local = self.stroke3D_local[i0:i1]

            snap_beginning = (
                i0 == 0 and 'x' in self.mirror and sign_threshold(stroke3D_local[0].x, self.mirror_threshold) == 0,
                i0 == 0 and 'y' in self.mirror and sign_threshold(stroke3D_local[0].y, self.mirror_threshold) == 0,
                i0 == 0 and 'z' in self.mirror and sign_threshold(stroke3D_local[0].z, self.mirror_threshold) == 0,
            )
            snap_ending = (
                i1 == len(self.stroke3D_local) and 'x' in self.mirror and sign_threshold(stroke3D_local[-1].x, self.mirror_threshold) == 0,
                i1 == len(self.stroke3D_local) and 'y' in self.mirror and sign_threshold(stroke3D_local[-1].y, self.mirror_threshold) == 0,
                i1 == len(self.stroke3D_local) and 'z' in self.mirror and sign_threshold(stroke3D_local[-1].z, self.mirror_threshold) == 0,
            )
            # print(snap_beginning, snap_ending)

            limit_bmes0 = None
            if i0 == 0:
                snap_bmf0 = snap_bmf_start
            else:
                snap_bmf0 = snap_bmf1
                limit_bmes0 = [
                    bme for bme in snap_bmf0.edges
                    if bme.is_boundary and any(len(bmv.link_faces)>1 for bmv in bme.verts)
                ]

            limit_bmes1 = None
            if i1 == nstroke:
                snap_bmf1 = snap_bmf_end
                if snap_bmf_end:
                    limit_bmes1 = [
                        bme for bme in snap_bmf_end.edges
                        if bme.is_boundary and any(len(bmv.link_faces)>1 for bmv in bme.verts)
                    ]
            else:
                snap_bmf1 = None
                # extend stroke by self.width
                i_end = max(0, len(stroke3D_local) - 5)
                p0,p1 = stroke3D_local[i_end], stroke3D_local[-1]
                d01 = Direction(p1 - p0)
                p2 = self.nearest_point(context, p1 + d01 * (self.initial_width / 2))
                stroke3D_local += [p2]

            snap0 = trim_stroke_to_bmf(stroke3D_local, snap_bmf0, True, limit_bmes0)
            if snap0:
                if snap0['error']:
                    self.error = True
                    print(f'ERROR: {snap0["error"]} on snap0')
                    if snap_bmf1 is None: snap_bmf1 = bmfs[-1] if bmfs else None
                    continue
                stroke3D_local = snap0['stroke']

            snap1 = trim_stroke_to_bmf(stroke3D_local, snap_bmf1, False, limit_bmes1)
            if snap1:
                if snap1['error']:
                    self.error = True
                    print(f'ERROR: {snap1["error"]} on snap1')
                    if snap_bmf1 is None: snap_bmf1 = bmfs[-1] if bmfs else None
                    continue
                stroke3D_local = snap1['stroke']

            if not stroke3D_local: continue

            if (stroke3D_local[0] - stroke3D_local[-1]).length == 0:
                print(f'ERROR: ends of stroke are at the same location {len(stroke3D_local)=} {stroke3D_local[0]=} {stroke3D_local[-1]=}')
                continue

            # warp stroke to better fit snapped geo
            stroke3D_local = warp_stroke(
                context,
                stroke3D_local,
                None if not snap0 else snap0['bme.center'],
                None if not snap1 else snap1['bme.center'],
                self.nearest_point,
            )

            if not stroke3D_local:
                print(f'ERROR: stroke is empty')
                continue

            ###########################################################################
            # sample the stroke and compute various properties of sample

            # self.width = self.compute_length3D(self.stroke3D_local, self.is_cycle) / (self.count * 2 - 1)
            if not self.counts:
                quad_count = round(((self.compute_length3D(stroke3D_local, False) / self.initial_width) + 1) / 2)
                quad_count = max(2, quad_count)
                width = self.initial_width
            else:
                quad_count = self.counts[i_strip]
                width = self.widths[i_strip]

            ncount_mins += [3 if (snap_bmf0 and snap_bmf1) else 2]
            ncounts += [quad_count]
            nwidths += [width]

            quad_count = (quad_count - 1) if snap0 and snap1 else quad_count
            nsamples = quad_count + (quad_count - 1)
            nsamples = (nsamples + 2) if not (snap0 or snap1) else nsamples
            nsamples = max(2, nsamples)
            samples = [
                find_point_at(stroke3D_local, self.is_cycle, (i / (nsamples - 1)))
                for i in range(nsamples)
            ]
            samples = [ nearest_point_valid_sources(context, M @ pt, world=False) for pt in samples ]
            normals = [ Direction(nearest_normal_valid_sources(context, M @ pt, world=False)) for pt in samples ]
            forwards = [ Direction(p1 - p0) for (p0, p1) in iter_pairs(samples, self.is_cycle) ]
            forwards += [ forwards[-1] ]
            # backwards is essentially the same as forwards, but doing it this way is slightly easier to understand
            backwards = [ Direction(p0 - p1) for (p0, p1) in iter_pairs(samples, self.is_cycle) ]
            backwards = [ backwards[0] ] + backwards
            rights = [
                (f.cross(n).normalize() + n.cross(b).normalize()).normalize()
                for (b, f, n) in zip(backwards, forwards, normals)
            ]


            ######################################
            # create bmverts

            w0 = snap0['bme.radius'] if snap0 else width
            w1 = snap1['bme.radius'] if snap1 else width
            wm = width
            bmvs = [[], []]

            # create bmverts at beginning of stroke
            p, pn = samples[0], samples[1]
            f, r = forwards[0], rights[0]
            if snap0:
                bme = snap0['bme']
                bmv0, bmv1 = bme.verts[0], bme.verts[1]
                if r.dot(bmv1.co - bmv0.co) > 0:
                    bmv0, bmv1 = bmv1, bmv0
                bmvs[0] += [bmv0]
                bmvs[1] += [bmv1]
            else:
                p0, p1 = p + r * wm, p - r * wm
                if any(snap_beginning):
                    if snap_beginning[0]: p0.x = p1.x = 0
                    if snap_beginning[1]: p0.y = p1.y = 0
                    if snap_beginning[2]: p0.z = p1.z = 0
                bmvs[0] += [ self.bm.verts.new(p0) ]
                bmvs[1] += [ self.bm.verts.new(p1) ]

            # create bmverts along stroke
            i_start = 2 if (snap0 or snap1) else 2
            i_end = len(samples) - (2 if (snap0 or snap1) else 1)
            for i in range(i_start, i_end, 2):
                pp, p, pn = samples[i-1:i+2]
                r = rights[i]

                # compute width
                if snap0 and not snap1:
                    v = i / (len(samples) - 1)
                    w = w0 + (wm - w0) * v
                elif not snap0 and snap1:
                    v = i / (len(samples) - 1)
                    w = wm + (w1 - wm) * v
                else:
                    v = 2 * i / (len(samples) - 1)
                    if v < 1: w = w0 + (wm - w0) * v
                    else:     w = wm + (w1 - wm) * (v-1)

                bmvs[0] += [ self.bm.verts.new(p + r * w) ]
                bmvs[1] += [ self.bm.verts.new(p - r * w) ]

            # create bmverts at ending of stroke
            p, pp = samples[-1], samples[-2]
            f, r = forwards[-1], rights[-1]
            if snap1:
                bme = snap1['bme']
                bmv0, bmv1 = bme.verts[0], bme.verts[1]
                if r.dot(bmv1.co - bmv0.co) > 0:
                    bmv0, bmv1 = bmv1, bmv0
                bmvs[0] += [bmv0]
                bmvs[1] += [bmv1]
            else:
                p0, p1 = p + r * wm, p - r * wm
                if any(snap_ending):
                    if snap_ending[0]: p0.x = p1.x = 0
                    if snap_ending[1]: p0.y = p1.y = 0
                    if snap_ending[2]: p0.z = p1.z = 0
                bmvs[0] += [ self.bm.verts.new(p0) ]
                bmvs[1] += [ self.bm.verts.new(p1) ]

            # snap newly created bmverts to source
            for bmv in chain(bmvs[0], bmvs[1]):
                bmv.co = nearest_point_valid_sources(context, M @ bmv.co, world=False)

            ######################################################
            # handle mirror
            m,mt = self.mirror,self.mirror_threshold
            mx,my,my = self.mirror_side
            for bmvs_ in bmvs:
                for bmv in bmvs_:
                    co = bmv.co
                    v = Vector((
                        0 if 'x' in m and sign_threshold(co.x, mt) != mx else 1,
                        0 if 'y' in m and sign_threshold(co.y, mt) != my else 1,
                        0 if 'z' in m and sign_threshold(co.z, mt) != mz else 1,
                    ))
                    bmv.co = v * co


            ######################################################
            # create bmfaces

            bmfs = []
            for i in range(0, len(bmvs[0])-1):
                bmv00, bmv01 = bmvs[0][i], bmvs[0][i+1]
                bmv10, bmv11 = bmvs[1][i], bmvs[1][i+1]
                verts = dedup(bmv00, bmv01, bmv11, bmv10)  # Fix 1588: faces.new(...): found the same (BMVert) used multiple times
                if len(verts) < 3:
                    print(f'WARNING: Cannot create face with {len(verts)=} verts {verts=}')
                    continue
                bmf = self.bm.faces.new(verts)
                bmfs += [ bmf ]
                select_geo.append(bmf)
            fwd = xform_direction(Mi, view_forward_direction(context))
            check_bmf_normals(fwd, bmfs)

            if snap_bmf1 is None: snap_bmf1 = bmfs[-1]
            actual_strip_count += 1

        ########################################
        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, select_geo)
        bmops.flush_selection(self.bm, self.em)

        self.count_mins = ncount_mins
        self.counts = ncounts
        self.widths = nwidths
        self.strip_count = actual_strip_count


    def update_context(self, context):
        # this should be called whenever the context could change

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






    #####################################################################################
    # utility functions

    def project_pt(self, context, pt):
        p = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt)
        return p.xy if p else None
    def project_bmv(self, context, bmv):
        p = self.project_pt(context, bmv.co)
        return p.xy if p else None
    def nearest_point(self, context, p):
        return self.matrix_world_inv @ nearest_point_valid_sources(context, self.matrix_world @ p)
    def bmv_closest(self, bmvs, pt3D):
        pt2D = self.project_pt(context, pt3D)
        # bmvs = [bmv for bmv in bmvs if bmv.select and (pt := self.project_bmv(bmv)) and (pt - pt2D).length_squared < 20*20]
        bmvs = [bmv for bmv in bmvs if (pt := self.project_bmv(context, bmv)) and (pt - pt2D).length_squared < 20*20]
        if not bmvs: return None
        return min(bmvs, key=lambda bmv: (bmv.co - pt3D).length_squared)
