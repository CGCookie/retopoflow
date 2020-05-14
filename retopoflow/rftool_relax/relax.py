'''
Copyright (C) 2020 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import math
import time
from ..rftool import RFTool
from ..rfwidgets.rfwidget_brushfalloff import RFWidget_BrushFalloff_Relax

from ...addon_common.common.maths import (
    Vec, Vec2D,
    Point, Point2D,
    Direction,
    Accel2D,
    Color,
)
from ...addon_common.common import ui
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat
from ...addon_common.common.profiler import profiler
from ...config.options import options, themes


class RFTool_Relax(RFTool):
    name        = 'Relax'
    description = 'Relax the vertex positions to smooth out topology'
    icon        = 'relax_32.png'
    help        = 'relax.md'
    shortcut    = 'relax tool'


class Relax(RFTool_Relax):
    @RFTool_Relax.on_init
    def init(self):
        self.rfwidget = RFWidget_BrushFalloff_Relax(self)
        self._var_mask_boundary = BoundBool('''options['relax mask boundary']''')
        self._var_mask_hidden   = BoundBool('''options['relax mask hidden']''')
        self._var_mask_selected = BoundBool('''options['relax mask selected']''')

    @RFTool_Relax.on_ui_setup
    def ui(self):
        return ui.collapsible('Relax', children=[
            ui.collection('Masking Options', children=[
                ui.input_checkbox(
                    label='Boundary',
                    title='Check to mask off vertices that are along boundary of target (includes along symmetry plane)',
                    checked=self._var_mask_boundary,
                    style='display:block',
                ),
                ui.input_checkbox(
                    label='Hidden',
                    title='Check to mask off vertices that are hidden behind source',
                    checked=self._var_mask_hidden,
                    style='display:block',
                ),
                ui.input_checkbox(
                    label='Selected',
                    title='Check to mask off vertices that are selected',
                    checked=self._var_mask_selected,
                    style='display:block',
                ),
            ]),
        ])

    @RFTool_Relax.on_reset
    def reset(self):
        self.sel_only = False
        self.rfwidget.color = Color((0.5, 1.0, 0.5, 1.0))

    @RFTool_Relax.FSM_State('main')
    def main(self) :
        if self.rfcontext.actions.pressed('select single'):
            self.rfcontext.undo_push('select')
            self.rfcontext.deselect_all()
            return 'select'

        if self.rfcontext.actions.pressed('select single add'):
            face,_ = self.rfcontext.accel_nearest2D_face(max_dist=10)
            if not face: return
            if face.select:
                self.mousedown = self.rfcontext.actions.mouse
                return 'selectadd/deselect'
            return 'select'

        if self.rfcontext.actions.pressed({'select smart', 'select smart add'}, unpress=False):
            if self.rfcontext.actions.pressed('select smart'):
                self.rfcontext.deselect_all()
            self.rfcontext.actions.unpress()
            edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if not edge: return
            faces = set()
            walk = {edge}
            touched = set()
            while walk:
                edge = walk.pop()
                if edge in touched: continue
                touched.add(edge)
                nfaces = set(f for f in edge.link_faces if f not in faces and len(f.edges) == 4)
                walk |= {f.opposite_edge(edge) for f in nfaces}
                faces |= nfaces
            self.rfcontext.select(faces, only=False)
            return

        if self.rfcontext.actions.pressed(['brush', 'brush alt'], unpress=False):
            self.sel_only = self.rfcontext.actions.using('brush alt')
            self.rfcontext.actions.unpress()
            self.rfcontext.undo_push('relax')
            return 'relax'

    @RFTool_Relax.FSM_State('selectadd/deselect')
    def selectadd_deselect(self):
        if not self.rfcontext.actions.using(['select single','select single add']):
            self.rfcontext.undo_push('deselect')
            face,_ = self.rfcontext.accel_nearest2D_face()
            if face and face.select: self.rfcontext.deselect(face)
            return 'main'
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        if delta.length > self.drawing.scale(5):
            self.rfcontext.undo_push('select add')
            return 'select'

    @RFTool_Relax.FSM_State('select')
    def select(self):
        if not self.rfcontext.actions.using(['select single','select single add']):
            return 'main'
        bmf,_ = self.rfcontext.accel_nearest2D_face(max_dist=10)
        if not bmf or bmf.select: return
        self.rfcontext.select(bmf, supparts=False, only=False)

    @RFTool_Relax.FSM_State('relax', 'enter')
    def relax_enter(self):
        self._time = time.time()
        self._timer = self.actions.start_timer(120)

    @RFTool_Relax.FSM_State('relax', 'exit')
    def relax_exit(self):
        self._timer.done()

    @RFTool_Relax.FSM_State('relax')
    @RFTool.dirty_when_done
    def relax(self):
        if self.rfcontext.actions.released(['brush','brush alt']):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        if not self.rfcontext.actions.timer: return

        hit_pos = self.rfcontext.actions.hit_pos
        if not hit_pos: return

        # collect data for smoothing
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_point(hit_pos, radius)
        verts,edges,faces,vert_strength = set(),set(),set(),dict()
        for bmv,d in nearest:
            verts.add(bmv)
            edges.update(bmv.link_edges)
            faces.update(bmv.link_faces)
            vert_strength[bmv] = self.rfwidget.get_strength_dist(d) / radius
        # self.rfcontext.select(verts)

        self._relax(verts, edges, faces, vert_strength)

    def _relax(self, verts, edges, faces, vert_strength=None, vistest=True):
        if not verts or not edges: return
        vert_strength = vert_strength or {}

        # gather options
        opt_steps = options['relax steps']
        opt_mask_boundary = options['relax mask boundary']
        opt_mask_hidden = options['relax mask hidden']
        opt_mask_selected = options['relax mask selected']
        opt_edge_length = options['relax edge length']
        opt_face_radius = options['relax face radius']
        opt_face_sides = options['relax face sides']
        opt_face_angles = options['relax face angles']
        opt_mult = options['relax force multiplier']

        is_visible = lambda bmv: self.rfcontext.is_visible(bmv.co, bmv.normal)

        cur_time = time.time()
        time_delta = cur_time - self._time
        self._time = cur_time
        strength = (5.0 / opt_steps) * self.rfwidget.strength * time_delta
        radius = self.rfwidget.get_scaled_radius()

        # capture all verts involved in relaxing
        chk_verts = set(verts)
        chk_verts |= {bmv for bme in edges for bmv in bme.verts}
        chk_verts |= {bmv for bmf in faces for bmv in bmf.verts}
        chk_edges = set(bme for bmv in chk_verts for bme in bmv.link_edges)
        chk_faces = set(bmf for bmv in chk_verts for bmf in bmv.link_faces)

        # perform smoothing
        for step in range(opt_steps):
            # compute average edge length
            avg_edge_len = sum(bme.calc_length() for bme in edges) / len(edges)
            # gather coords
            displace = {bmv:Vec((0,0,0)) for bmv in chk_verts}

            # push edges closer to average edge length
            if opt_edge_length:
                for bme in chk_edges:
                    if bme not in edges: continue
                    bmv0,bmv1 = bme.verts
                    vec = bme.vector()
                    edge_len = vec.length
                    f = vec * (0.1 * (avg_edge_len - edge_len) * strength) #/ edge_len
                    displace[bmv0] -= f
                    displace[bmv1] += f

            # push verts if neighboring faces seem flipped (still WiP!)
            if options['show experimental']:
                for bmv in verts:
                    vn,fn = bmv.normal,bmv.compute_normal()
                    d = fn - vn * vn.dot(fn)
                    print(vn, fn, d)
                    displace[bmv] += d

            # attempt to "square" up the faces
            for bmf in chk_faces:
                if bmf not in faces: continue
                bmvs = bmf.verts
                cnt = len(bmvs)
                ctr = Point.average(bmv.co for bmv in bmvs)
                rels = [bmv.co - ctr for bmv in bmvs]

                # push verts toward average dist from verts to face center
                if opt_face_radius:
                    avg_rel_len = sum(rel.length for rel in rels) / cnt
                    for rel, bmv in zip(rels, bmvs):
                        rel_len = rel.length
                        f = rel * ((avg_rel_len - rel_len) * strength) #/ rel_len
                        displace[bmv] += f

                # push verts toward equal edge lengths
                if opt_face_sides:
                    avg_face_edge_len = sum(bme.length for bme in bmf.edges) / cnt
                    for bme in bmf.edges:
                        bmv0, bmv1 = bme.verts
                        vec = bme.vector()
                        edge_len = vec.length
                        f = vec * ((avg_face_edge_len - edge_len) * strength) #/ edge_len
                        displace[bmv0] -= f
                        displace[bmv1] += f

                # push verts toward equal spread
                if opt_face_angles:
                    avg_angle = 2.0 * math.pi / cnt
                    for i0 in range(cnt):
                        i1 = (i0 + 1) % cnt
                        rel0,bmv0 = rels[i0],bmvs[i0]
                        rel1,bmv1 = rels[i1],bmvs[i1]
                        vec = bmv1.co - bmv0.co
                        fvec0 = rel0.cross(vec).cross(rel0).normalize()
                        fvec1 = rel1.cross(rel1.cross(vec)).normalize()
                        vec_len = vec.length
                        angle = rel0.angle(rel1)
                        f_mag = (0.1 * (avg_angle - angle) * strength) / cnt #/ vec_len
                        displace[bmv0] -= fvec0 * f_mag
                        displace[bmv1] -= fvec1 * f_mag

            # update
            for bmv in displace:
                if bmv not in verts: continue
                if bmv not in vert_strength: continue
                if self.sel_only and not bmv.select: continue
                if opt_mask_boundary and bmv.is_boundary: continue
                if vistest and opt_mask_hidden and not is_visible(bmv): continue
                if opt_mask_selected and bmv.select: continue
                f = displace[bmv] * (opt_mult * vert_strength[bmv])
                bmv.co += f
                self.rfcontext.snap_vert(bmv)
