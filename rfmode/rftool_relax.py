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
from ..common.ui import (
    UI_Container, UI_Collapsible, UI_Frame,
    UI_Image, UI_Label,
    UI_BoolValue, UI_IntValue, UI_Checkbox,
)
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

    def get_ui_options(self):
        ui_mask = UI_Frame('Masking Options')
        ui_mask.add(UI_BoolValue('Boundary', *options.gettersetter('relax mask boundary'), tooltip='Enable to mask off vertices that are along boundary of target (includes along symmetry plane)'))
        ui_mask.add(UI_BoolValue('Hidden', *options.gettersetter('relax mask hidden'), tooltip='Enable to mask off vertices that are hidden behind source'))
        ui_mask.add(UI_BoolValue('Selected', *options.gettersetter('relax mask selected'), tooltip='Enable to mask off vertices that are selected'))

        ui_brush = UI_Frame('Brush Properties')
        ui_brush.add(UI_IntValue('Radius', *self.rfwidget.radius_gettersetter(), tooltip='Set radius of relax brush'))
        ui_brush.add(UI_IntValue('Falloff', *self.rfwidget.falloff_gettersetter(), tooltip='Set falloff of relax brush'))
        ui_brush.add(UI_IntValue('Strength', *self.rfwidget.strength_gettersetter(), tooltip='Set strength of relax brush'))

        ui_algorithm = UI_Collapsible('Advanced')
        ui_algorithm.add(UI_IntValue('Multiplier', *options.gettersetter('relax force multiplier', setwrap=lambda v: max(0.1, int(v*10)/10)), fn_formatter=lambda v:'%0.1f'%v, tooltip='Number of steps taken (small=fast,less accurate.  large=slow,more accurate)'))
        ui_algorithm.add(UI_IntValue('Steps', *options.gettersetter('relax steps', setwrap=lambda v: max(1, int(v))), tooltip='Number of steps taken (small=fast,less accurate.  large=slow,more accurate)'))
        ui_algorithm.add(UI_Checkbox('Edge Length', *options.gettersetter('relax edge length')))
        ui_algorithm.add(UI_Checkbox('Face Radius', *options.gettersetter('relax face radius')))
        ui_algorithm.add(UI_Checkbox('Face Sides', *options.gettersetter('relax face sides')))
        ui_algorithm.add(UI_Checkbox('Face Angles', *options.gettersetter('relax face angles')))

        return [
            ui_mask,
            ui_brush,
            ui_algorithm,
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

        time_delta = self.rfcontext.actions.time_delta
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
