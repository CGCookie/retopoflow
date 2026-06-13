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

import time
from collections import deque
from collections.abc import Iterable

import bpy
import bmesh

from bpy.types import Mesh
from mathutils import Vector, Matrix
from bmesh.types import BMVert, BMesh
from bpy_extras.view3d_utils import location_3d_to_region_2d

from ..rfglobals import RFGlobals
from ..common.bmesh import (
    bmvs_shared_bme,
    bme_other_bmv,
    bme_length,
    get_bmesh_emesh,
    NearestBMVert,
    NearestBMFace,
)
from ..common.bmesh_maths import is_bmvert_hidden
from ..common.drawing import (
    Drawing,
    CC_2D_POINTS,
    CC_2D_LINES,
    CC_2D_LINE_STRIP,
)
from ..common.operator import RFOperator
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import clamp
from ...addon_common.common.utils import iter_pairs

from ..preferences import RF_Prefs


MOVE_FACTOR = 0.4


def get_neighbors(start : Iterable[BMVert], *, max_distance : int = 1) -> set[BMVert]:
    '''
    find BMVerts that are <= max_distance away from any of the start BMVerts.
    traversal: BMVert -> BMFace -> BMVerts
    '''
    neighbors = set(start)
    working = list((bmv,0) for bmv in start)
    while working:
        n,d = working.pop(0)
        if d > max_distance: continue
        for bmf in n.link_faces:
            for bmv in bmf.verts:
                if bmv in neighbors: continue
                working.append((bmv, d+1))
                neighbors.add(bmv)
    return neighbors - set(start)


class Zipper_Logic:
    bm : BMesh
    em : Mesh
    matrix_world     : Matrix
    matrix_world_inv : Matrix
    nearest     : NearestBMVert
    nearest_bmf : NearestBMFace
    selected : set[BMVert]

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

        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted_safe()
        self.nearest     = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv, ensure_lookup_tables=True)
        self.nearest_bmf = NearestBMFace(self.bm, self.matrix_world, self.matrix_world_inv, ensure_lookup_tables=False)
        self.selected = bmops.get_all_selected_bmverts(self.bm)
        self.first = True
        self.path_unzip = None
        self.path_zip = None
        self.lmb_down = False
        self.mode = 'UNKNOWN'

    def update(self, context, event) -> bool:
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
            hit = raycast_valid_sources(context, mouse_from_event(event), respect_clip_planes=True)
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


    def guess(self) -> str:
        if self.mode != 'UNKNOWN': return self.mode
        if not self.selected: return 'UNKNOWN'

        if len(self.selected) == 1:
            bmv = next(iter(self.selected))
            co = bmv.co
            bmv0, bmv1 = bmv, bmv
        elif len(self.selected) == 2:
            bmv0, bmv1 = self.selected
            co = (bmv0.co + bmv1.co) / 2
        else:
            return 'UNKNOWN'
        d = (self.hit - co).length
        zip_dir = (co - self.hit).normalized()

        nbmes = [
            bme
            for bme in bmv0.link_edges
        ]
        if not nbmes: return 'UNKNOWN'
        def bme0_key(bme):
            o = bme_other_bmv(bme, bmv0)
            d = (o.co - bmv0.co).normalized()
            return d.dot(zip_dir)
        nbmes.sort(key=bme0_key)
        nbme0 = nbmes[0]
        nbmv0 = bme_other_bmv(nbme0, bmv0)

        nbmes = [
            bme
            for bme in bmv1.link_edges
        ]
        if not nbmes: return 'UNKNOWN'
        def bme1_key(bme):
            o = bme_other_bmv(bme, bmv1)
            d = (o.co - bmv1.co).normalized()
            return d.dot(zip_dir)
        nbmes.sort(key=bme1_key)
        nbme1 = nbmes[0]
        nbmv1 = bme_other_bmv(nbme1, bmv1)
        if len(nbme0.link_faces) == 1 or len(nbme1.link_faces) == 1:
            return 'ZIPPING'
        else:
            return 'UNZIPPING'


    def _update_paths(self):
        self.path_unzip = None
        self.path_zip = None

        if not self.hit: return
        if not self.selected: return
        if not self.nearest: return

        mode = self.guess()

        if self.nearest.bmv and mode in {'UNKNOWN', 'UNZIPPING'}:
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

        elif self.selected and mode in {'UNKNOWN', 'ZIPPING'}:
            if len(self.selected) == 1:
                bmv = next(iter(self.selected))
                co = bmv.co
                bmv0, bmv1 = bmv, bmv
            elif len(self.selected) == 2:
                bmv0, bmv1 = self.selected
                co = (bmv0.co + bmv1.co) / 2
            else:
                return
            d = (self.hit - co).length
            zip_dir = (co - self.hit).normalized()
            self.path_zip = []
            seen = set()
            while True:
                self.path_zip.append( (bmv0, bmv1) )

                nbmes = [
                    bme
                    for bme in bmv0.link_edges
                    if len(bme.link_faces) == 1 and bme not in seen
                ]
                if not nbmes: break
                def bme0_key(bme):
                    o = bme_other_bmv(bme, bmv0)
                    d = (o.co - bmv0.co).normalized()
                    return d.dot(zip_dir)
                nbmes.sort(key=bme0_key)
                nbme0 = nbmes[0]
                nbmv0 = bme_other_bmv(nbme0, bmv0)
                seen.add(nbme0)

                nbmes = [
                    bme
                    for bme in bmv1.link_edges
                    if len(bme.link_faces) == 1 and bme not in seen
                ]
                if not nbmes: break
                def bme1_key(bme):
                    o = bme_other_bmv(bme, bmv1)
                    d = (o.co - bmv1.co).normalized()
                    return d.dot(zip_dir)
                nbmes.sort(key=bme1_key)
                nbme1 = nbmes[0]
                nbmv1 = bme_other_bmv(nbme1, bmv1)
                seen.add(nbme1)

                l = min(bme_length(nbme0), bme_length(nbme1))
                if d < l:
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
            bmes = [
                bmvs_shared_bme(bmv0, bmv1)
                for (bmv0, bmv1) in iter_pairs(self.path_unzip, False)
            ]
            bmes = bmesh.ops.split_edges(self.bm, edges=bmes)['edges']
            verts = set(bmv for bme in bmes for bmv in bme.verts)
            neighbors = get_neighbors(verts)

            nco = {}
            for bmv in verts:
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
            for bmv in neighbors:
                avg = [
                    bmv.co + (n.co - nco[n]) * (1 - clamp((bmv.co - n.co).length / 0.2, 0.0, 1.0))
                    for n in verts
                    if n in nco
                ]
                if not avg: continue
                nco[bmv] = sum(avg, Vector((0,0,0))) / len(avg)
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
            bmv0, bmv1 = self.path_zip[0]
            co = (bmv0.co + bmv1.co) / 2
            pt_origin = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ co)
            m = self.mouse
            l = len(self.path_zip)
            verts = [v for vs in self.path_zip for v in vs]
            neighbors = get_neighbors(verts)
            oco = { v: v.co for v in verts }
            nco = {}
            for i, (bmv0, bmv1) in enumerate(self.path_zip):
                if bmv0 == bmv1: continue
                co = pt_origin + (m - pt_origin) * i / (l - 1)
                co = raycast_point_valid_sources(context, co, world=False, respect_clip_planes=True)
                if not co: continue
                oco[bmv0] = bmv0.co
                oco[bmv1] = bmv1.co
                bmesh.ops.pointmerge(self.bm, verts=[bmv0, bmv1], merge_co=co)
                nco[bmv0] = co
                nco[bmv1] = co
            for bmv in neighbors:
                avg = [
                    bmv.co + (nco[n] - oco[n]) * (1 - clamp((bmv.co - oco[n]).length / 0.2, 0.0, 1.0))
                    for n in verts
                    if n in oco and n in nco
                ]
                if not avg: continue
                bmv.co = sum(avg, Vector((0,0,0))) / len(avg)
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

        if len(self.selected) in {1,2} and not self.path_unzip:
            if len(self.selected) == 1:
                bmv = next(iter(self.selected))
                co = self.matrix_world @ bmv.co
            else:
                bmv0, bmv1 = self.selected
                co = (bmv0.co + bmv1.co) / 2
                co = self.matrix_world @ co
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
            bmv0, bmv1 = self.path_zip[0]
            if not bmv0.is_valid or not bmv1.is_valid: return
            co = (bmv0.co + bmv1.co) / 2
            pt_origin = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ co)
            m = self.mouse
            with Drawing.draw(context, CC_2D_LINES) as draw:
                draw.line_width(1)
                draw.color(color_border_mesh)
                draw.stipple(pattern=[1,0], offset=0, color=color_border_mesh)
                ppt0, ppt1 = None, None
                for (bmv0, bmv1) in self.path_zip[1:]:
                    pt0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                    pt1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                    if ppt0 and ppt1:
                        draw.vertex(ppt0).vertex(pt0)
                        draw.vertex(ppt1).vertex(pt1)
                    ppt0, ppt1 = pt0, pt1

                draw.line_width(2)
                draw.color(color_border_mesh)
                draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
                l = len(self.path_zip)
                for i, (bmv0, bmv1) in enumerate(self.path_zip):
                    pt0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                    pt1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                    pt = pt_origin + (m - pt_origin) * (i / (l-1))
                    draw.vertex(pt0).vertex(pt)
                    draw.vertex(pt1).vertex(pt)


class RFOperator_Zipper(RFOperator):
    bl_idname = "retopoflow.zipper"
    bl_label = 'Zipper'
    bl_description = 'Zip and unzip topology'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'INTERNAL'}

    rf_keymaps = [
        (bl_idname, {'type': 'Z', 'value': 'PRESS', 'ctrl': True, 'alt': True}, {'km_context': 'init', 'km_label': ' Start Zipper'}),
    ]
    rf_status = {
        'ready': ('LMB: Zip / Unzip', ),
    }


    def init(self, context, event):
        self.logic = Zipper_Logic(context, event)
        self.tickle(context)

    def reset(self):
        pass

    def update(self, context, event):
        print(f'zip {time.time()}')
        if self.logic.update(context, event):
            self.tickle(context)
            context.area.tag_redraw()

        if not event.ctrl or not event.alt:
            return {'FINISHED'}

        # if event.type == 'Z':
        #     return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!
        return {'RUNNING_MODAL'}

    def draw_postpixel(self, context):
        RFCore = RFGlobals.RFCore_None
        if not RFCore or not RFCore.is_current_area(context): return
        self.logic.draw(context)
