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

from ..common.bmesh import get_bmesh_emesh, NearestBMVert, is_bmedge_boundary, is_bmvert_boundary
from ..common.bmesh_maths import is_bmvert_hidden
from ..common.maths import point_to_bvec4
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, nearest_point_valid_sources, mouse_from_event

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import closest_point_segment, Point, sign, sign_threshold

class Tweak_Logic:
    def __init__(self, context, event, brush, tweak):
        self.context, self.rgn, self.r3d = context, context.region, context.region_data

        self.bm, self.em = get_bmesh_emesh(context)
        self.bm.faces.ensure_lookup_table()
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()

        self.mirror = set()
        self.mirror_clip = False
        self.mirror_threshold = Vector((0, 0, 0))
        for mod in context.edit_object.modifiers:
            if mod.type != 'MIRROR': continue
            if not mod.use_clip: continue
            if mod.use_axis[0]: self.mirror.add('x')
            if mod.use_axis[1]: self.mirror.add('y')
            if mod.use_axis[2]: self.mirror.add('z')
            mt, scale = mod.merge_threshold, context.edit_object.scale
            self.mirror_threshold = Vector(( mt / scale.x, mt / scale.y, mt / scale.z ))
            self.mirror_clip = mod.use_clip

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
            if is_bmedge_boundary(bme, self.mirror, self.mirror_threshold, self.mirror_clip)
        ]

    def collect_verts(self, context, event):
        self.verts = []
        self.mouse = Vector(mouse_from_event(event))

        hit = raycast_valid_sources(context, self.mouse)
        if not hit: return

        offset = context.space_data.overlay.retopology_offset
        M = self.matrix_world

        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        # right now, falloff brush works in 3D... should switch to 2D?
        radius2D, radius3D = self.brush.radius, self.brush.get_scaled_radius()
        for bmv in self.bm.verts:
            if bmv.hide: continue
            # if (self.project_bmv(bmv) - mouse).length > radius2D: continue
            if ((M @ bmv.co) - (M @ hit['co_local'])).length > radius3D: continue
            if self.tweak.mask_boundary == 'EXCLUDE' and bmv.is_boundary: continue
            if self.tweak.include_corners  == False  and len(bmv.link_edges) == 2: continue
            if self.tweak.include_corners == False   and len(bmv.link_edges) == 4 and len(bmv.link_faces) == 3: continue
            if self.tweak.mask_symmetry == 'EXCLUDE' and is_bmvert_on_symmetry_plane(bmv): continue
            if self.tweak.include_occluded == False  and is_bmvert_hidden(context, bmv): continue
            if self.tweak.mask_selected == 'EXCLUDE' and bmv.select: continue
            if self.tweak.mask_selected == 'ONLY'    and not bmv.select: continue
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
        if event.type != 'MOUSEMOVE': return

        mouse = Vector(mouse_from_event(event))
        delta = mouse - self.mouse

        for (bmv, co_orig, xy, strength) in self.verts:
            if self.tweak.mask_boundary == 'SLIDE' and is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip):
                new_co = Vector(co_orig)
                delta_strength = delta.length * strength
                opt_steps = max(math.ceil(delta_strength / 10), 1)
                for step in range(opt_steps):
                    new_co2 = raycast_valid_sources(context, self.project_pt(new_co) + delta * (strength / opt_steps))
                    if not new_co2: break
                    new_co = new_co2['co_local']
                    p, d = None, None
                    for (v0, v1) in self._boundary:
                        p_ = closest_point_segment(new_co, v0, v1)
                        d_ = (p_ - new_co).length_squared
                        if p is None or d_ < d: p, d = p_, d_
                    if p is not None:
                        new_co = p
            else:
                new_co = raycast_valid_sources(context, xy + delta * strength)
                if not new_co: continue
                new_co = new_co['co_local']

            if self.mirror:
                co = Vector(new_co)
                t = self.mirror_threshold
                zero = {
                    'x': ('x' in self.mirror and (sign_threshold(co.x, t.x) != sign_threshold(co_orig.x, t.x) or sign_threshold(co_orig.x, t.x) == 0)),
                    'y': ('y' in self.mirror and (sign_threshold(co.y, t.y) != sign_threshold(co_orig.y, t.y) or sign_threshold(co_orig.y, t.y) == 0)),
                    'z': ('z' in self.mirror and (sign_threshold(co.z, t.z) != sign_threshold(co_orig.z, t.z) or sign_threshold(co_orig.z, t.z) == 0)),
                }
                # iteratively zero out the component
                for _ in range(1000):
                    d = 0
                    if zero['x']: co.x, d = co.x * 0.95, max(abs(co.x), d)
                    if zero['y']: co.y, d = co.y * 0.95, max(abs(co.y), d)
                    if zero['z']: co.z, d = co.z * 0.95, max(abs(co.z), d)
                    co_world = self.matrix_world @ Vector((*co, 1.0))
                    co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True)
                    co = self.matrix_world_inv @ co_world_snapped
                    if d < 0.001: break  # break out if change was below threshold
                if zero['x']: co.x = 0
                if zero['y']: co.y = 0
                if zero['z']: co.z = 0
                new_co = co


            if new_co: bmv.co = new_co
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

