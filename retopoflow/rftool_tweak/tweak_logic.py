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
from ...addon_common.common.maths import closest_point_segment, Point, sign

class Tweak_Logic:
    def __init__(self, context, event, brush, tweak):
        self.context, self.rgn, self.r3d = context, context.region, context.region_data

        self.bm, self.em = get_bmesh_emesh(context)
        self.bm.faces.ensure_lookup_table()
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()

        self.mirror = set()
        for mod in context.edit_object.modifiers:
            if mod.type != 'MIRROR': continue
            if not mod.use_clip: continue
            if mod.use_axis[0]: self.mirror.add('x')
            if mod.use_axis[1]: self.mirror.add('y')
            if mod.use_axis[2]: self.mirror.add('z')

        self.brush = brush
        self.tweak = tweak

        self._time = time.time()

        self.collect_boundary()
        self.collect_verts(context, event)

    def collect_boundary(self):
        if self.tweak.mask_boundary != 'SLIDE': return
        self._boundary = [
            (Vector(bme.verts[0].co), Vector(bme.verts[1].co))
            for bme in self.bm.edges
            if not bme.is_manifold
        ]

    def collect_verts(self, context, event):
        self.verts = []
        self.mouse = Vector(mouse_from_event(event))

        hit = raycast_valid_sources(context, self.mouse)
        if not hit: return

        offset = context.space_data.overlay.retopology_offset

        def is_bmvert_hidden(bmv):
            nonlocal context
            point = self.matrix_world @ point_to_bvec4(bmv.co)
            hit = raycast_valid_sources(context, point)
            if not hit: return False
            ray_e = hit['ray_world'][0]
            return hit['distance'] < (ray_e.xyz - point.xyz).length - offset
        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        # right now, falloff brush works in 3D... should switch to 2D?
        radius2D, radius3D = self.brush.radius, self.brush.get_scaled_radius()
        for bmv in self.bm.verts:
            if bmv.hide: continue
            # if (self.project_bmv(bmv) - mouse).length > radius2D: continue
            if (bmv.co - hit['co_local']).length > radius3D: continue
            if self.tweak.mask_boundary == 'EXCLUDE' and bmv.is_boundary: continue
            if self.tweak.mask_corners  == 'EXCLUDE' and len(bmv.link_edges) == 2: continue
            if self.tweak.mask_symmetry == 'EXCLUDE' and is_bmvert_on_symmetry_plane(bmv): continue
            if self.tweak.mask_occluded == 'EXCLUDE' and is_bmvert_hidden(bmv): continue
            if self.tweak.mask_selected == 'EXCLUDE' and bmv.select: continue
            if self.tweak.mask_selected == 'ONLY' and not bmv.select: continue
            self.verts.append((
                bmv,
                Vector(bmv.co),
                self.project_bmv(bmv),
                self.brush.get_strength_Point(self.matrix_world @ bmv.co),
            ))

    def cancel(self, context):
        if not self.verts: return
        for (bmv, co, _, _) in self.verts:
            bmv.co = co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def project_pt(self, pt):
        p = location_3d_to_region_2d(self.rgn, self.r3d, self.matrix_world @ pt)
        return p.xy if p else None
    def project_bmv(self, bmv):
        p = self.project_pt(bmv.co)
        return p.xy if p else None

    def update(self, context, event):
        if not self.verts: return

        mouse = Vector(mouse_from_event(event))
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

            if self.mirror:
                if 'x' in self.mirror and sign(new_co.x) != sign(co.x): new_co.x = 0
                if 'y' in self.mirror and sign(new_co.y) != sign(co.y): new_co.y = 0
                if 'z' in self.mirror and sign(new_co.z) != sign(co.z): new_co.z = 0
                new_co = nearest_point_valid_sources(context, new_co, world=False)


            if new_co: bmv.co = new_co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

