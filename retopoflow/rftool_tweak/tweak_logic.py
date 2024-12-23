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

import blf
import bmesh
import bpy
import gpu
from bmesh.types import BMVert, BMEdge, BMFace
from bmesh.utils import edge_split
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_line_2d
from mathutils.bvhtree import BVHTree

import math
import time

from ..common.bmesh import get_bmesh_emesh, NearestBMVert
from ..common.maths import point_to_bvec4
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, nearest_point_valid_sources, mouse_from_event

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import closest_point_segment, Point

class Tweak_Logic:
    def __init__(self, context, event, brush, tweak):
        self.context, self.rgn, self.r3d = context, context.region, context.region_data
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()

        self.brush = brush
        self.tweak = tweak

        self.bm, self.em = get_bmesh_emesh(context)
        self.bm.faces.ensure_lookup_table()
        self._time = time.time()

        self._boundary = []
        if tweak.mask_boundary == 'SLIDE':
            self._boundary = [
                (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
                for bme in self.bm.edges
                if not bme.is_manifold
            ]

        self.verts = None

        bpy.ops.ed.undo_push(message='Tweak')

    def project_pt(self, pt):
        p = location_3d_to_region_2d(self.rgn, self.r3d, self.matrix_world @ pt)
        return p.xy if p else None
    def project_bmv(self, bmv):
        p = self.project_pt(bmv.co)
        return p.xy if p else None

    def update(self, context, event):
        mouse = Vector(mouse_from_event(event))
        hit = raycast_valid_sources(context, mouse)
        if not hit: return

        if self.verts is None:
            def is_bmvert_hidden(bmv, *, factor=0.999):
                nonlocal context
                point = self.matrix_world @ point_to_bvec4(bmv.co)
                hit = raycast_valid_sources(context, point)
                if not hit: return False
                ray_e = hit['ray_world'][0]
                return hit['distance'] < (ray_e.xyz - point.xyz).length * factor
            def is_bmvert_on_symmetry_plane(bmv):
                # TODO: IMPLEMENT!
                return False

            radius = self.brush.get_scaled_radius()
            verts = []
            for bmv in self.bm.verts:
                if bmv.hide: continue
                if (bmv.co - hit['co_local']).length > radius: continue
                if self.tweak.mask_boundary == 'EXCLUDE' and bmv.is_boundary: continue
                if self.tweak.mask_symmetry == 'EXCLUDE' and is_bmvert_on_symmetry_plane(bmv): continue
                if self.tweak.mask_occluded == 'EXCLUDE' and is_bmvert_hidden(bmv): continue
                if self.tweak.mask_selected == 'EXCLUDE' and bmv.select: continue
                if self.tweak.mask_selected == 'ONLY' and not bmv.select: continue
                verts.append((
                    bmv,
                    Vector(bmv.co),
                    self.project_bmv(bmv),
                    self.brush.get_strength_Point(self.matrix_world @ bmv.co),
                ))
            self.verts = verts
            self.mouse = mouse

        delta = mouse - self.mouse

        for (bmv, co, xy, strength) in self.verts:
            new_co = raycast_valid_sources(context, xy + delta * strength)
            if not new_co: continue
            new_co = new_co['co_local']

            if self.tweak.mask_boundary == 'SLIDE' and bmv.is_boundary:
                p, d = None, None
                for (v0, v1) in self._boundary:
                    p_ = closest_point_segment(new_co, v0, v1)
                    d_ = (p_ - new_co).length
                    if p is None or d_ < d: p, d = p_, d_
                if p is not None:
                    new_co = p

            if new_co: bmv.co = new_co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

