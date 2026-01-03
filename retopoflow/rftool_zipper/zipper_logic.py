'''
Copyright (C) 2025 CG Cookie
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

from enum import Enum
import math
import time
from collections import deque

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

from ..preferences import RF_Prefs

from ..common.bmesh import (
    NearestBMVert,
    NearestBMFace,
    bme_length,
    bme_other_bmv,
    bmvs_shared_bme,
    bmfs_shared_bme,
    get_bmesh_emesh,
    is_bmedge_boundary,
    is_bmvert_boundary,
)
from ..common.bmesh_maths import is_bmvert_hidden
from ..common.maths import point_to_bvec4
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, nearest_point_valid_sources, mouse_from_event

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import closest_point_segment, Point, sign, sign_threshold
from ...addon_common.common.colors import Color4
from ...addon_common.common.utils import iter_pairs

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



MOVE_FACTOR = 0.4


class Zipper_Logic:
    def __init__(self, context, event):
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))

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

        self._init(context, event)
        self.lmb_down = False
        self.mode = 'UNKNOWN'


    def update(self, context, event) -> bool:

        if not self.nearest or not self.nearest.is_valid:
            self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
            self.matrix_world = context.edit_object.matrix_world
            self.matrix_world_inv = self.matrix_world.inverted()
            self.nearest     = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv, ensure_lookup_tables=True)
            self.nearest_bmf = NearestBMFace(self.bm, self.matrix_world, self.matrix_world_inv, ensure_lookup_tables=False)
            self.selected = bmops.get_all_selected_bmverts(self.bm)

        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        if event.type == 'LEFTMOUSE':
            if event.value == 'PRESS':
                self.commit(context, event)
                self.lmb_down = True
                self.mode = 'UNKNOWN'
                return True
            if event.value == 'RELEASE':
                self.lmb_down = False
                return True

        if event.type == 'MOUSEMOVE' or self.first:
            hit = raycast_valid_sources(context, mouse_from_event(event))
            self.hit = hit['co_local'] if hit else None
            self.nearest_bmf.update(
                context,
                self.hit,
            )
            dist = 10
            if not self.selected: dist = float('inf')
            if self.nearest_bmf.bmf: dist = float('inf')
            self.nearest.update(
                context,
                self.hit,
                distance2d=dist,
                filter_fn=lambda bmv: not is_bmvert_hidden(context, bmv),
            )
            self._update_paths()

            if self.lmb_down:
                self.commit(context, event)
                return True

        self.first = False
        return event.type == 'MOUSEMOVE'


    def _init(self, context, event):
        self.nearest = None
        self.nearest_bmf = None
        self.first = True
        self.path_unzip = None
        self.path_zip = None
        self.selected = None

    def _update_paths(self):
        self.path_unzip = None
        self.path_zip = None

        if not self.hit: return
        if not self.selected: return
        if not self.nearest: return

        if self.nearest.bmv and self.mode in {'UNKNOWN', 'UNZIPPING'}:
            working = deque(self.selected)
            path_back = { n:None for n in working }
            while working and self.nearest.bmv not in path_back:
                n = working.popleft()
                for bme in n.link_edges:
                    if len(bme.link_faces) != 2: continue
                    o = bme_other_bmv(bme, n)
                    if o in path_back: continue
                    path_back[o] = n
                    working.append(o)
            if self.nearest.bmv not in path_back: return

            c = self.nearest.bmv
            self.path_unzip = []
            while c:
                self.path_unzip.append(c)
                c = path_back[c]
            self.path_unzip.reverse()
            if len(self.path_unzip) < 2: self.path_unzip = None

        elif len(self.selected) == 1 and self.mode in {'UNKNOWN', 'ZIPPING'}:
            bmv = next(iter(self.selected))
            d = (self.hit - bmv.co).length
            bmv0, bmv1 = bmv, bmv
            pbme0, pbme1 = None, None
            self.path_zip = []
            seen = set()
            while True:
                self.path_zip.append( (bmv0, bmv1) )
                for bme in bmv0.link_edges:
                    if bme == pbme0: continue
                    if len(bme.link_faces) != 1: continue
                    if bme in seen: continue
                    seen.add(bme)
                    nbme0 = bme
                    nbmv0 = bme_other_bmv(bme, bmv0)
                    break
                else:
                    break
                for bme in bmv1.link_edges:
                    if bme == pbme1: continue
                    if len(bme.link_faces) != 1: continue
                    if bme in seen: continue
                    seen.add(bme)
                    nbme1 = bme
                    nbmv1 = bme_other_bmv(bme, bmv1)
                    break
                else:
                    break
                l = min(bme_length(nbme0), bme_length(nbme1))
                if d < l * 0.5:
                    break
                d -= l
                bmv0, bmv1 = nbmv0, nbmv1
            if len(self.path_zip) < 2: self.path_zip = None


    def commit(self, context, event):
        if not self.path_unzip and not self.path_zip: return
        if not self.nearest: return

        if self.mode in {'UNKNOWN', 'UNZIPPING'} and self.path_unzip:
            bpy.ops.ed.undo_push(message=f'Unzipping commit {time.time()}')
            select_bmv = self.nearest.bmv
            bmes = [bmvs_shared_bme(bmv0, bmv1) for (bmv0, bmv1) in iter_pairs(self.path_unzip, False)]
            res = bmesh.ops.split_edges(self.bm, edges=bmes)
            bmes = res['edges']
            verts = set(bmv for bme in bmes for bmv in bme.verts)
            nco = {}
            for bmv in verts:
                if bmv == select_bmv: print(f'FOUND IT!')
                avg = [
                    bmvo.co
                    for bme in bmv.link_edges
                    if bme not in bmes
                    if (bmvo := bme_other_bmv(bme, bmv)) is not None
                ]
                if not avg: continue
                avg = sum(avg, Vector((0,0,0))) / len(avg)
                co = bmv.co + (avg - bmv.co) * MOVE_FACTOR
                nco[bmv] = co
            for bmv, co in nco.items():
                bmv.co = co
            bmesh.update_edit_mesh(self.em)
            bmops.deselect_all(self.bm)
            bmops.select(self.bm, select_bmv)
            bmops.flush_selection(self.bm, self.em)
            self.nearest = None
            self.path_unzip = None
            self.mode = 'UNZIPPING'

        if self.mode in {'UNKNOWN', 'ZIPPING'} and self.path_zip:
            bpy.ops.ed.undo_push(message=f'Zipping commit {time.time()}')
            bmv = self.path_zip[0][0]
            pt_origin = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv.co)
            m = self.mouse
            l = len(self.path_zip) - 1
            for i, (bmv0, bmv1) in enumerate(self.path_zip[1:]):
                co = pt_origin + (m - pt_origin) * (i + 1) / l
                co = raycast_point_valid_sources(context, co, world=False)
                bmesh.ops.pointmerge(self.bm, verts=[bmv0, bmv1], merge_co=co)
            bmesh.update_edit_mesh(self.em)
            bmops.deselect_all(self.bm)
            bmops.select(self.bm, self.path_zip[-1][0])
            bmops.flush_selection(self.bm, self.em)
            self.nearest = None
            self.path_zip = None
            self.mode = 'ZIPPING'



    def draw(self, context):
        if not self.nearest: return
        if not self.nearest.is_valid: return

        theme = context.preferences.themes[0].view_3d
        props = RF_Prefs.get_prefs(context)
        highlight = props.highlight_color

        color_point =               Color4((highlight[0], highlight[1], highlight[2], 1))
        color_border_transparent =  Color4((highlight[0], highlight[1], highlight[2], 0))
        color_border_mesh =         Color4((theme.edge_select[0], theme.edge_select[1], theme.edge_select[2], 1))
        color_border_open =         Color4((highlight[0], highlight[1], highlight[2], 1.0))
        color_stipple =             Color4((theme.face_select[0], theme.face_select[1], theme.face_select[2], 0))
        color_mesh = theme.face_select
        vertex_size = theme.vertex_size

        if self.nearest.bmv:
            co = self.matrix_world @ self.nearest.bmv.co
            p = location_3d_to_region_2d(context.region, context.region_data, co)
            with Drawing.draw(context, CC_2D_POINTS) as draw:
                draw.point_size(vertex_size + 4)
                draw.border(width=2, color=color_point)
                draw.color(color_border_transparent)
                draw.vertex(p)
        if len(self.selected) == 1 and not self.path_unzip:
            bmv = next(iter(self.selected))
            co = self.matrix_world @ bmv.co
            p = location_3d_to_region_2d(context.region, context.region_data, co)
            m = self.mouse
            with Drawing.draw(context, CC_2D_LINES) as draw:
                draw.line_width(1)
                draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                draw.vertex(p).vertex(m)

        if self.path_unzip:
            with Drawing.draw(context, CC_2D_LINE_STRIP) as draw:
                draw.line_width(1)
                draw.color(color_border_mesh)
                draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                for v in self.path_unzip:
                    co = self.matrix_world @ v.co
                    p = location_3d_to_region_2d(context.region, context.region_data, co)
                    draw.vertex(p)

        if self.path_zip and len(self.path_zip) > 1:
            bmv = self.path_zip[0][0]
            if not bmv.is_valid: return
            pt_origin = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv.co)
            m = self.mouse
            with Drawing.draw(context, CC_2D_LINES) as draw:
                draw.line_width(2)
                draw.color(color_border_mesh)
                draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                ppt0, ppt1 = pt_origin, pt_origin
                for (bmv0, bmv1) in self.path_zip[1:]:
                    pt0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                    pt1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                    draw.vertex(ppt0).vertex(pt0)
                    draw.vertex(ppt1).vertex(pt1)
                    ppt0, ppt1 = pt0, pt1

                draw.line_width(1)
                draw.color(color_border_mesh)
                draw.stipple(pattern=[1,0], offset=0, color=color_border_mesh)
                l = len(self.path_zip)
                for i, (bmv0, bmv1) in enumerate(self.path_zip):
                    pt0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                    pt1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                    pt = pt_origin + (m - pt_origin) * (i / (l-1))
                    draw.vertex(pt0).vertex(pt)
                    draw.vertex(pt1).vertex(pt)
