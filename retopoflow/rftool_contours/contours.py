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
import os
import time
import bmesh
from ..rftool_base import RFTool_Base
from ..rfbrush_base import RFBrush_Base
from ..common.bmesh import (
    get_bmesh_emesh,
    get_select_layers,
    clean_select_layers,
    NearestBMVert,
    NearestBMEdge,
)
from ..common.icons import get_path_to_blender_icon
from ..common.operator import invoke_operator, execute_operator, RFOperator, RFRegisterClass, chain_rf_keymaps, wrap_property
from ..common.raycast import (
    raycast_valid_sources, raycast_point_valid_sources,
    size2D_to_size,
    vec_forward,
    mouse_from_event,
    plane_normal_from_points,
)
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import Point2D
from ...addon_common.common.reseter import Reseter
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



class Contours_Logic:
    def __init__(self, context, event):
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.update_bmesh_selection = False
        self.mouse = Point2D(mouse_from_event(event))
        self.mousedown = None
        self.hit = None
        self.reset()
        self.update(context, event)

    def reset(self):
        self.bm = None
        self.em = None
        self.selected = None

    def cleanup(self):
        clean_select_layers(self.bm)

    def update(self, context, event):
        if not self.bm or not self.bm.is_valid:
            self.bm, self.em = get_bmesh_emesh(context)
            self.layer_sel_vert, self.layer_sel_edge, self.layer_sel_face = get_select_layers(self.bm)
            self.selected = None
            self.nearest = None
            self.nearest_bme = None

        if self.update_bmesh_selection:
            self.update_bmesh_selection = False
            self.bm.select_history.validate()
            active = self.bm.select_history.active
            for bmv in self.bm.verts:
                if bmv[self.layer_sel_vert] == 0: continue
                # bmv.select_set(bmv[self.layer_sel_vert] == 1)
                bmops.select(self.bm, bmv)
                bmv[self.layer_sel_vert] = 0
            for bme in self.bm.edges:
                if bme[self.layer_sel_edge] == 0: continue
                for bmv in bme.verts:
                    # bmv.select_set(True)
                    bmops.select(self.bm, bmv)
                bme[self.layer_sel_edge] = 0
            for bmf in self.bm.faces:
                if bmf[self.layer_sel_face] == 0: continue
                for bmv in bmf.verts:
                    # bmv.select_set(True)
                    bmops.select(self.bm, bmv)
                bmf[self.layer_sel_face] = 0
            if active: bmops.reselect(self.bm, active)
            bmops.flush_selection(self.bm, self.em)
            # bpy.ops.mesh.normals_make_consistent('EXEC_DEFAULT', False)
            # bpy.ops.ed.undo_push(message='Selected geometry after move')
            self.selected = None

        self.mouse = Point2D(mouse_from_event(event))
        if self.mousedown and self.mouse:
            if (self.mousedown - self.mouse).length < Drawing.scale(8):
                self.hit = None
            else:
                pm = Point2D.average((self.mouse, self.mousedown))
                self.hit = raycast_valid_sources(context, pm)

        if event.type == 'MOUSEMOVE' and self.mousedown:
            context.area.tag_redraw()

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self.mousedown = self.mouse
            context.area.tag_redraw()

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            # do something with self.mousedown and self.mouse and self.hit
            if self.hit:
                t0 = time.time()
                self.crawl_faces(context)
                print(time.time() - t0)
            self.mousedown = None
            self.hit = None
            context.area.tag_redraw()

    def crawl_faces(self, context):
        hit_co = self.hit['co_world']
        cut_n = plane_normal_from_points(context, self.mousedown, self.mouse)

        M = self.hit['object'].matrix_world
        hit_bm = bmesh.new()
        hit_bm.from_mesh(self.hit['object'].data)
        hit_bm.faces.ensure_lookup_table()

        def bmv_sign(bmv): return cut_n.dot((M @ bmv.co) - hit_co)
        def bme_cut(bme):
            bmv0, bmv1 = bme.verts
            s0, s1 = bmv_sign(bmv0), bmv_sign(bmv1)
            return s0 == 0 or s1 == 0 or (s0 < 0) == (s1 > 0)
        def bme_cut_pt(bme):
            bmv0, bmv1 = bme.verts
            s0, s1 = bmv_sign(bmv0), bmv_sign(bmv1)
            sd = s1 - s0
            f = -s0 / sd
            v = bmv1.co - bmv0.co
            return bmv0.co + v * f

        start = hit_bm.faces[self.hit['face_index']]
        mapping = {}
        working = { start }
        while working:
            bmf = working.pop()
            if bmf in mapping: continue
            mapping[bmf] = []
            for bme in bmf.edges:
                if not bme_cut(bme): continue
                mapping[bmf].append(bme)
                for bmf_ in bme.link_faces:
                    working.add(bmf_)
        # attempt to find loop
        # cur = start
        # bmes_seen = set()
        # while True:
        #     bme = next((bme for bme in cur.edges if bme in mapping and bme not in bmes_seen), None)
        #     if not bme:
        #         print('no loop found')
        #         break
        #     cur = 
        bmes_cut = set(bme for bmes in mapping.values() for bme in bmes)
        pts = [ bme_cut_pt(bme) for bme in bmes_cut ]
        print([bmf.index for bmf in mapping])
        print(pts)


        # def bmf_cut(bmf):
        #     above, below = False, False
        #     for vidx in f.vertices:
        #         sign = vsigns[vidx]
        #         if sign == 0: return True
        #         if sign > 0: above = True
        #         else: below = True
        #     return above and below

        # faces_in_cut = { f.index for f in faces if face_in_cut(f) }
        # print(faces_in_cut)
        # print(self.hit['face_index'] in faces_in_cut)

        # vert_faces = { vidx:[] for vidx in range(len(verts)) }
        # for fidx, f in enumerate(faces):
        #     for vidx in f.vertices:
        #         vert_faces[vidx].append(fidx)

        # incut   = { self.hit['face_index'] }
        # touched = { self.hit['face_index'] }
        # working = { self.hit['face_index'] }
        # while working:
        #     fidx = working.pop()
        #     for vidx in faces[fidx].vertices:
        #         for fidx_ in vert_faces[vidx]:
        #             if fidx_ in touched: continue

    def draw(self, context):
        if not self.mousedown: return
        p0 = self.mousedown
        p1 = self.mouse
        pm = Point2D.average((p0, p1))
        d01 = (p1 - p0).normalized() * Drawing.scale(8)

        with Drawing.draw(context, CC_2D_LINES) as draw:
            draw.line_width(2)
            if self.hit:
                draw.stipple(pattern=[5,5], offset=0, color=Color4((255/255, 255/255, 40/255, 0.0)))
                draw.color(Color4((255/255, 255/255, 40/255, 0.5)))
            else:
                draw.stipple(pattern=[5,5], offset=0, color=Color4((192/255, 30/255, 30/255, 0.0)))
                draw.color(Color4((192/255, 30/255, 30/255, 0.5)))
            draw.vertex(pm-d01).vertex(p0)
            draw.vertex(pm+d01).vertex(p1)

        with Drawing.draw(context, CC_2D_POINTS) as draw:
            draw.point_size(8)
            if self.hit:
                draw.color(Color4((255/255, 255/255, 255/255, 1.0)))
            else:
                draw.color(Color4((255/255, 40/255, 40/255, 1.0)))
            draw.vertex(pm)



class RFOperator_Contours(RFOperator):
    bl_idname = 'retopoflow.contours'
    bl_label = 'Contours'
    bl_description = 'Retopologize cylindrical forms, like arms and legs'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),
    ]

    rf_status = ['LMB: Insert', 'MMB: (nothing)', 'RMB: (nothing)']

    def init(self, context, event):
        self.logic = Contours_Logic(context, event)
        self.tickle(context)

    def reset(self):
        self.logic.reset()

    def update(self, context, event):
        self.logic.update(context, event)

        if self.logic.mousedown:
            return {'RUNNING_MODAL'}

        if not event.ctrl:
            self.logic.cleanup()
            return {'FINISHED'}

        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!

    def draw_postpixel(self, context):
        self.logic.draw(context)


class RFTool_Contours(RFTool_Base):
    bl_idname = "retopoflow.contours"
    bl_label = "Contours"
    bl_description = "Retopologize cylindrical forms, like arms and legs"
    bl_icon = get_path_to_blender_icon('contours')
    bl_widget = None
    bl_operator = 'retopoflow.contours'

    # rf_brush = RFBrush_Contours()

    bl_keymap = chain_rf_keymaps(RFOperator_Contours)

    def draw_settings(context, layout, tool):
        pass

    @classmethod
    def activate(cls, context):
        cls.reseter = Reseter()
        cls.reseter['context.tool_settings.use_mesh_automerge'] = False
        cls.reseter['context.tool_settings.snap_elements_individual'] = {'FACE_NEAREST'}

    @classmethod
    def deactivate(cls, context):
        cls.reseter.reset()
