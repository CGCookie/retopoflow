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

import bpy
import math
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec,Accel2D
from ..common.ui import UI_Image, UI_BoolValue, UI_Label
from ..options import options
from ..help import help_relax
from ..lib.classes.profiler.profiler import profiler
from .rfcontext_actions import Actions

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
    def get_tooltip(self): return 'Relax (%s)' % ','.join(Actions.default_keymap['relax tool'])
    
    def get_move_boundary(self): return options['relax boundary']
    def set_move_boundary(self, v): options['relax boundary'] = v
    
    def get_move_hidden(self): return options['relax hidden']
    def set_move_hidden(self, v): options['relax hidden'] = v
    
    def get_move_selected(self): return options['relax selected']
    def set_move_selected(self, v): options['relax selected'] = v
    
    def get_ui_options(self):
        return [
            UI_BoolValue('Selected Only', self.get_move_selected, self.set_move_selected),
            UI_BoolValue('Boundary', self.get_move_boundary, self.set_move_boundary),
            UI_BoolValue('Hidden', self.get_move_hidden, self.set_move_hidden),
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
        
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_point(hit_pos, radius)
        # collect data for smoothing
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
        
        time_delta = self.rfcontext.actions.time_delta
        strength = 100.0 * self.rfwidget.strength * time_delta
        radius = self.rfwidget.get_scaled_radius()
        mult = 1.0 / radius
        
        # compute average edge length
        avgDist = sum(bme.calc_length() for bme in edges) / len(edges)
        
        # capture all verts involved in relaxing
        chk_verts = set(verts)
        chk_verts |= {bmv for bme in edges for bmv in bme.verts}
        chk_verts |= {bmv for bmf in faces for bmv in bmf.verts}
        divco = {bmv:Point(bmv.co) for bmv in chk_verts}
        
        # perform smoothing
        touched = set()
        for bmv0 in verts:
            d = vert_strength.get(bmv0, 0)
            lbme,lbmf = bmv0.link_edges,bmv0.link_faces
            if not lbme: continue
            # push edges closer to average edge length
            for bme in lbme:
                if bme not in edges: continue
                if bme in touched: continue
                touched.add(bme)
                bmv1 = bme.other_vert(bmv0)
                diff = bmv1.co - bmv0.co
                m = (avgDist - diff.length) * (1.0 - d) * 0.1 * mult
                divco[bmv1] += diff * m * strength
                divco[bmv0] -= diff * m * strength
            # attempt to "square" up the faces
            for bmf in lbmf:
                if bmf not in faces: continue
                if bmf in touched: continue
                touched.add(bmf)
                cnt = len(bmf.verts)
                ctr = sum([bmv.co for bmv in bmf.verts], Vec((0,0,0))) / cnt
                fd = sum((ctr-bmv.co).length for bmv in bmf.verts) / cnt
                for bmv in bmf.verts:
                    diff = (bmv.co - ctr)
                    m = (fd - diff.length)* (1.0 - d) / cnt * mult
                    divco[bmv] += diff * m * strength
        
        # update
        sel_only = self.get_move_selected()
        hidden = self.get_move_hidden()
        boundary = self.get_move_boundary()
        is_visible = lambda bmv: self.rfcontext.is_visible(bmv.co, bmv.normal)
        for bmv,co in divco.items():
            if bmv not in verts: continue
            if self.sel_only and not bmv.select: continue
            if not boundary and bmv.is_boundary: continue
            if vistest and not hidden and not is_visible(bmv): continue
            bmv.co = co
            self.rfcontext.snap_vert(bmv)
