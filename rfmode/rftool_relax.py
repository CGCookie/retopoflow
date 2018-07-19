'''
Copyright (C) 2018 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

import bpy

from .rftool import RFTool

from ..common.maths import (
    Vec, Vec2D,
    Point, Point2D,
    Direction,
    Accel2D
)
from ..common.ui import UI_Image, UI_BoolValue, UI_Label, UI_IntValue, UI_Container
from ..common.profiler import profiler
from ..keymaps import default_rf_keymaps
from ..options import options
from ..help import help_relax

@RFTool.action_call('relax tool')
class RFTool_Relax(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['selectadd/deselect'] = self.modal_selectadd_deselect
        self.FSM['select'] = self.modal_select
        self.FSM['relax'] = self.modal_relax

    def name(self): return "Relax"
    def icon(self): return "rf_relax_icon"
    def description(self): return 'Relax topology by changing length of edges to average'
    def helptext(self): return help_relax
    def get_label(self): return 'Relax (%s)' % ','.join(default_rf_keymaps['relax tool'])
    def get_tooltip(self): return 'Relax (%s)' % ','.join(default_rf_keymaps['relax tool'])

    def get_move_boundary(self): return options['relax boundary']
    def set_move_boundary(self, v): options['relax boundary'] = v

    def get_move_hidden(self): return options['relax hidden']
    def set_move_hidden(self, v): options['relax hidden'] = v

    def get_step_count(self): return options['relax steps']
    def set_step_count(self, v): options['relax steps'] = max(1, v)

    def get_ui_options(self):
        ui_mask = UI_Container()
        ui_mask.add(UI_Label('Masking Options:', margin=0))
        ui_mask.add(UI_BoolValue('Boundary', self.get_move_boundary, self.set_move_boundary, margin=0, tooltip='Enable to relax vertices that are along boundary of target (includes along symmetry plane)'))
        ui_mask.add(UI_BoolValue('Hidden', self.get_move_hidden, self.set_move_hidden, margin=0, tooltip='Enable to relax vertices that are hidden behind source'))

        ui_brush = UI_Container()
        ui_brush.add(UI_Label('Brush Properties:', margin=0))
        ui_brush.add(UI_IntValue('Radius', *self.rfwidget.radius_gettersetter(), margin=0, tooltip='Set radius of relax brush'))
        ui_brush.add(UI_IntValue('Falloff', *self.rfwidget.falloff_gettersetter(), margin=0, tooltip='Set falloff of relax brush'))
        ui_brush.add(UI_IntValue('Strength', *self.rfwidget.strength_gettersetter(), margin=0, tooltip='Set strength of relax brush'))

        return [
            UI_IntValue('Steps', self.get_step_count, self.set_step_count, tooltip='Number of steps taken (small=fast,less accurate.  large=slow,more accurate)'),
            ui_mask,
            ui_brush,
        ]

    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('brush falloff', color=(0.5, 1.0, 0.5))
        self.sel_only = False

    def get_ui_icon(self):
        self.ui_icon = UI_Image('relax_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon

    def modal_main(self):
        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('select')
            self.rfcontext.deselect_all()
            return 'select'

        if self.rfcontext.actions.pressed('select add'):
            face = self.rfcontext.accel_nearest2D_face(max_dist=10)
            if not face: return
            if face.select:
                self.mousedown = self.rfcontext.actions.mouse
                return 'selectadd/deselect'
            return 'select'

        if self.rfcontext.actions.pressed(['action', 'action alt0'], unpress=False):
            self.sel_only = self.rfcontext.actions.using('action alt0')
            self.rfcontext.actions.unpress()
            self.rfcontext.undo_push('relax')
            return 'relax'

    @profiler.profile
    def modal_selectadd_deselect(self):
        if not self.rfcontext.actions.using(['select','select add']):
            self.rfcontext.undo_push('deselect')
            face = self.rfcontext.accel_nearest2D_face()
            if face and face.select: self.rfcontext.deselect(face)
            return 'main'
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        if delta.length > self.drawing.scale(5):
            self.rfcontext.undo_push('select add')
            return 'select'

    @profiler.profile
    def modal_select(self):
        if not self.rfcontext.actions.using(['select','select add']):
            return 'main'
        bmf = self.rfcontext.accel_nearest2D_face(max_dist=10)
        if not bmf or bmf.select: return
        self.rfcontext.select(bmf, supparts=False, only=False)

    @RFTool.dirty_when_done
    def modal_relax(self):
        if self.rfcontext.actions.released(['action','action alt0']):
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
            vert_strength[bmv] = self.rfwidget.get_strength_dist(d) #/radius

        self._relax(verts, edges, faces, vert_strength)

    def _relax(self, verts, edges, faces, vert_strength=None, vistest=True):
        if not verts or not edges: return
        vert_strength = vert_strength or {}

        hidden = self.get_move_hidden()
        boundary = self.get_move_boundary()
        is_visible = lambda bmv: self.rfcontext.is_visible(bmv.co, bmv.normal)
        steps = self.get_step_count()

        time_delta = self.rfcontext.actions.time_delta
        strength = (5.0 / steps) * self.rfwidget.strength * time_delta
        radius = self.rfwidget.get_scaled_radius()

        # capture all verts involved in relaxing
        chk_verts = set(verts)
        chk_verts |= {bmv for bme in edges for bmv in bme.verts}
        chk_verts |= {bmv for bmf in faces for bmv in bmf.verts}
        chk_edges = set(bme for bmv in chk_verts for bme in bmv.link_edges)
        chk_faces = set(bmf for bmv in chk_verts for bmf in bmv.link_faces)

        # perform smoothing
        for step in range(steps):
            # compute average edge length
            avg_edge_len = sum(bme.calc_length() for bme in edges) / len(edges)
            # gather coords
            displace = {bmv:Vec((0,0,0)) for bmv in chk_verts}

            # push edges closer to average edge length
            for bme in chk_edges:
                if bme not in edges: continue
                bmv0,bmv1 = bme.verts
                vec = bme.vector()
                edge_len = vec.length
                f = vec * (0.1 * (avg_edge_len - edge_len) * strength) #/ edge_len
                #displace[bmv0] -= f
                #displace[bmv1] += f

            # attempt to "square" up the faces
            for bmf in chk_faces:
                if bmf not in faces: continue
                verts = bmf.verts
                cnt = len(verts)
                ctr = Point.average(bmv.co for bmv in verts)
                rels = [bmv.co - ctr for bmv in verts]

                # push verts toward average dist from verts to face center
                avg_rel_len = sum(rel.length for rel in rels) / cnt
                for rel, bmv in zip(rels, verts):
                    rel_len = rel.length
                    f = rel * ((avg_rel_len - rel_len) * strength) #/ rel_len
                    #displace[bmv] += f

                # push verts toward equal spread
                avg_angle = 2.0 * math.pi / cnt
                for i0 in range(cnt):
                    i1 = (i0 + 1) % cnt
                    rel0,bmv0 = rels[i0],verts[i0]
                    rel1,bmv1 = rels[i1],verts[i1]
                    vec = bmv1.co - bmv0.co
                    fvec0 = rel0.cross(vec).cross(rel0).normalize()
                    fvec1 = rel1.cross(rel1.cross(vec)).normalize()
                    vec_len = vec.length
                    angle = rel0.angle(rel1)
                    f_mag = ((avg_angle - angle) * strength) / cnt #/ vec_len
                    displace[bmv0] -= fvec0 * f_mag
                    displace[bmv1] -= fvec1 * f_mag

            # update
            for bmv in displace:
                if bmv not in verts: mag = 0
                elif self.sel_only and not bmv.select: mag = 0
                elif not boundary and bmv.is_boundary: mag = 0
                elif vistest and not hidden and not is_visible(bmv): mag = 0
                else: mag = vert_strength.get(bmv, 0)
                displace[bmv] *= mag
                bmv.co += displace[bmv]
                self.rfcontext.snap_vert(bmv)
