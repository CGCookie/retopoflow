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

from ..common.bmesh import get_bmesh_emesh, NearestBMVert, is_bmedge_boundary, is_bmvert_boundary, is_bmvert_corner, EdgeAccel, bme_cos
from ..common.bmesh_maths import is_bmvert_hidden, is_bmvert_on_edgemark, is_bmedge_edgemark, get_bmvert_attribute, BMMarking
from ..common.maths import point_to_bvec4
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, nearest_point_valid_sources, mouse_from_event

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import closest_point_segment, Point, sign, sign_threshold

class Tweak_Logic:
    def __init__(self, context, event, brush, tweak):
        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe()

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
        self.props_scene = context.scene.retopoflow

        self._time = time.time()

        self.collect_boundary()
        self.collect_seams()
        self.collect_sharps()
        self.collect_creases()
        self.collect_verts(context, event)

    def collect_boundary(self):
        self._boundary_verts = set()
        self._boundary_accel = None
        if self.props_scene.mask_boundary != 'SLIDE': return
        boundary_edges = [
            bme for bme in self.bm.edges
            if is_bmedge_boundary(bme, self.mirror, self.mirror_threshold, self.mirror_clip)
        ]
        self._boundary_verts = {bmv for bme in boundary_edges for bmv in bme.verts}
        self._boundary_accel = EdgeAccel([bme_cos(bme) for bme in boundary_edges])

    def collect_seams(self):
        self._seam_verts = set()
        self._seam_accel = None
        if self.props_scene.mask_seams != 'SLIDE': return
        seam_edges = [bme for bme in self.bm.edges if is_bmedge_edgemark(self.bm, bme, BMMarking.seam)]
        self._seam_verts = {bmv for bme in seam_edges for bmv in bme.verts}
        self._seam_accel = EdgeAccel([bme_cos(bme) for bme in seam_edges])

    def collect_sharps(self):
        self._sharp_verts = set()
        self._sharp_accel = None
        if self.props_scene.mask_sharps != 'SLIDE': return
        sharp_edges = [bme for bme in self.bm.edges if is_bmedge_edgemark(self.bm, bme, BMMarking.sharp)]
        self._sharp_verts = {bmv for bme in sharp_edges for bmv in bme.verts}
        self._sharp_accel = EdgeAccel([bme_cos(bme) for bme in sharp_edges])

    def collect_creases(self):
        self._crease_verts = set()
        self._crease_accel = None
        if self.props_scene.mask_creases != 'SLIDE': return
        self.bm.edges.ensure_lookup_table()
        crease_edges = [bme for bme in self.bm.edges if is_bmedge_edgemark(self.bm, bme, BMMarking.crease)]
        self._crease_verts = {bmv for bme in crease_edges for bmv in bme.verts}
        self._crease_accel = EdgeAccel([bme_cos(bme) for bme in crease_edges])

    def collect_verts(self, context, event):
        self.verts = []
        self.mouse = Vector(mouse_from_event(event))
        self.mouse_prev = self.mouse.copy()

        hit = raycast_valid_sources(context, self.mouse)
        if not hit: return

        offset = context.space_data.overlay.retopology_offset
        M = self.matrix_world

        def is_bmvert_on_symmetry_plane(bmv):
            # TODO: IMPLEMENT!
            return False

        # right now, falloff brush works in 3D... should switch to 2D?
        radius2D, radius3D = self.brush.radius, self.brush.get_scaled_radius()
        props = self.props_scene
        for bmv in self.bm.verts:
            if bmv.hide: continue
            # if (self.project_bmv(bmv) - mouse).length > radius2D: continue
            if ((M @ bmv.co) - (M @ hit['co_local'])).length > radius3D: continue

            if self.props_scene.mask_boundary == 'EXCLUDE' and (
                is_bmvert_boundary(bmv, self.mirror, self.mirror_threshold, self.mirror_clip)
            ):
                continue
            if (props.include_corners  == False or self.props_scene.mask_boundary == 'SLIDE') and is_bmvert_corner(bmv):
                continue
            if props.include_pinned == False and (
                get_bmvert_attribute(self.bm, bmv, 'retopoflow_pins', 'float')
            ):
                continue
            if props.mask_creases == 'EXCLUDE' and (
                get_bmvert_attribute(self.bm, bmv, 'crease_vert', 'float') and
                not get_bmvert_attribute(self.bm, bmv, 'retopoflow_pins', 'float')
            ):
                continue
            if props.mask_creases  == 'EXCLUDE' and is_bmvert_on_edgemark(self.bm, bmv, BMMarking.crease): continue
            if props.mask_seams    == 'EXCLUDE' and is_bmvert_on_edgemark(self.bm, bmv, BMMarking.seam): continue
            if props.mask_sharps   == 'EXCLUDE' and is_bmvert_on_edgemark(self.bm, bmv, BMMarking.sharp): continue
            if props.mask_seams    == 'SLIDE'   and sum([is_bmedge_edgemark(self.bm, bme, BMMarking.seam) for bme in bmv.link_edges]) > 2: continue
            if props.mask_sharps   == 'SLIDE'   and sum([is_bmedge_edgemark(self.bm, bme, BMMarking.sharp) for bme in bmv.link_edges]) > 2: continue
            if props.mask_creases  == 'SLIDE'   and sum([is_bmedge_edgemark(self.bm, bme, BMMarking.crease) for bme in bmv.link_edges]) > 2: continue
            if props.mask_symmetry == 'EXCLUDE' and is_bmvert_on_symmetry_plane(bmv): continue
            if props.include_occluded == False  and is_bmvert_hidden(context, bmv): continue
            if props.mask_selected == 'EXCLUDE' and bmv.select: continue
            if props.mask_selected == 'ONLY'    and not bmv.select: continue

            self.verts.append((
                bmv,
                Vector(bmv.co),
                self.project_bmv(context, bmv),
                self.brush.get_strength_Point(self.matrix_world @ bmv.co),
            ))

    def cancel(self, context):
        if not self.verts: return
        for (bmv, co, _, _) in self.verts:
            bmv.co = co
        bmesh.update_edit_mesh(self.em)
        # context.area.tag_redraw()

    def project_pt(self, context, pt):
        p = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ pt)
        return p.xy if p else None
    def project_bmv(self, context, bmv):
        p = self.project_pt(context, bmv.co)
        return p.xy if p else None

    def update(self, context, event):
        pressure = getattr(event, 'pressure', 1.0)

        if not self.verts: return
        if event.type != 'MOUSEMOVE': return

        mouse = Vector(mouse_from_event(event))
        delta = mouse - self.mouse_prev
        if delta.length_squared == 0: return

        for (bmv, co_orig, xy, strength) in self.verts:
            if self.props_scene.mask_boundary == 'SLIDE' and bmv in self._boundary_verts:
                new_co = Vector(bmv.co)
                delta_strength = delta.length * strength * pressure
                opt_steps = max(math.ceil(delta_strength / 10), 1)
                for step in range(opt_steps):
                    pt2d = self.project_pt(context, new_co) or xy
                    new_co2 = raycast_valid_sources(context, pt2d + delta * (strength / opt_steps) * pressure)
                    if not new_co2: break
                    new_co = new_co2['co_local']
                    if self._boundary_accel:
                        p = self._boundary_accel.closest_point(new_co)
                        if p is not None:
                            new_co = p
            else:
                cur_xy = self.project_bmv(context, bmv) or xy
                new_co = raycast_valid_sources(context, cur_xy + delta * strength * pressure)
                if not new_co: continue
                new_co = new_co['co_local']
                if self.props_scene.mask_seams == 'SLIDE' and bmv in self._seam_verts:
                    if self._seam_accel:
                        p = self._seam_accel.closest_point(new_co)
                        if p is not None: new_co = p
                if self.props_scene.mask_sharps == 'SLIDE' and bmv in self._sharp_verts:
                    if self._sharp_accel:
                        p = self._sharp_accel.closest_point(new_co)
                        if p is not None: new_co = p
                if self.props_scene.mask_creases == 'SLIDE' and bmv in self._crease_verts:
                    if self._crease_accel:
                        p = self._crease_accel.closest_point(new_co)
                        if p is not None: new_co = p

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
        # context.area.tag_redraw()
        self.mouse_prev = mouse
