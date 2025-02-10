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
)
from ..common.raycast import raycast_point_valid_sources, nearest_point_valid_sources, nearest_normal_valid_sources
from ..common.maths import view_forward_direction, lerp, point_to_bvec3, vector_to_bvec3
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bezier import interpolate_cubic
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import (
    closest_point_segment,
    segment2D_intersection,
    clamp,
    Direction,
)
from ...addon_common.common.utils import iter_pairs

import math
from itertools import chain


r'''

Desmos demo: https://www.desmos.com/geometry/okxgsddxk2

NOT HANDLING CYCLIC STROKES, YET

'''


class PolyStrips_Logic:
    def __init__(self, context, radius2D, stroke3D, is_cycle):
        # store context data to make it more convenient
        # note: this will be redone whenever create() is called
        self.update_context(context)

        # store passed parameters
        self.radius2D = radius2D
        self.stroke3D = [ pt for pt in stroke3D if pt ]
        self.is_cycle = is_cycle

        # process stroke data, such as projecting and computing length
        self.process_stroke()

        # initialize options
        self.action = ''  # will be filled in later
        self.count = max(2, round(self.length2D / (2 * radius2D)) + 1)
        self.width = self.length3D / (self.count * 2 - 1)
        print(f'{self.length2D=} {self.radius2D=} {self.length3D=} {self.count=} {self.width=}')

    @property
    def count(self): return self._count
    @count.setter
    def count(self, v): self._count = max(2, int(v))

    def create(self, context):
        self.update_context(context)

        # TODO: Remove this limitation!
        if self.is_cycle:
            print(f'Warning: PolyStrips cannot handle cyclic strokes, yet')
            return

        # compute number of samples to make on stroke
        self.npoints = self.count + (self.count - 1)
        self.points = [
            find_point_at(self.stroke3D, self.is_cycle, (i / (self.npoints - 1)))
            for i in range(self.npoints)
        ]
        M, Mi = self.matrix_world, self.matrix_world_inv
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

        # create bmverts
        bmvs = [[], []]
        # beginning of stroke
        p, pn = self.points[0], self.points[1]
        f, r = self.forwards[0], self.rights[0]
        d = (pn - p).length
        w = self.width
        bmvs[0] += [ self.bm.verts.new(p + r * w - f * d) ]
        bmvs[1] += [ self.bm.verts.new(p - r * w - f * d) ]
        # along stroke
        for i in range(1, self.npoints, 2):
            pp, p, pn = self.points[i-1:i+2]
            r = self.rights[i]
            d = ((pp - p).length + (pn - p).length) / 2
            bmvs[0] += [ self.bm.verts.new(p + r * w) ]
            bmvs[1] += [ self.bm.verts.new(p - r * w) ]
        # ending of stroke
        p, pp = self.points[-1], self.points[-2]
        f, r = self.forwards[-1], self.rights[-1]
        d = (pp - p).length
        bmvs[0] += [ self.bm.verts.new(p + r * w + f * d) ]
        bmvs[1] += [ self.bm.verts.new(p - r * w + f * d) ]

        # snap newly created bmverts to source
        for bmv in chain(bmvs[0], bmvs[1]):
            bmv.co = nearest_point_valid_sources(context, M @ bmv.co, world=False)

        bmfs = []
        for i in range(0, len(bmvs[0])-1):
            bmv00, bmv01 = bmvs[0][i], bmvs[0][i+1]
            bmv10, bmv11 = bmvs[1][i], bmvs[1][i+1]
            bmf = self.bm.faces.new((bmv00, bmv01, bmv11, bmv10))
            bmfs += [ bmf ]

        # select newly created geometry
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, bmvs[0] + bmvs[1])

        bmops.flush_selection(self.bm, self.em)


    def update_context(self, context):
        # this should be called whenever the context could change

        self.context = context
        self.rgn, self.r3d = context.region, context.region_data

        # gather bmesh data
        self.bm, self.em = get_bmesh_emesh(context)
        bmops.flush_selection(self.bm, self.em)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()

    def process_stroke(self):
        # project 3D stroke points to screen
        self.stroke2D = [self.project_pt(pt) for pt in self.stroke3D if pt]
        # compute total lengths, which will be used to find where new verts are to be created
        self.length2D = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke2D, self.is_cycle))
        self.length3D = sum((p1-p0).length for (p0,p1) in iter_pairs(self.stroke3D, self.is_cycle))




    #####################################################################################
    # utility functions

    def find_point2D(self, v):  return find_point_at(self.stroke2D, self.is_cycle, v)
    def find_point3D(self, v):  return find_point_at(self.stroke3D, self.is_cycle, v)
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
