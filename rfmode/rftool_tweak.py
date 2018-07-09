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
from .rfcontext_actions import default_keymap
from ..common.maths import Point,Point2D,Vec2D,Vec,Accel2D
from ..common.ui import UI_Image, UI_BoolValue, UI_Label
from ..common.profiler import profiler
from ..options import options
from ..help import help_tweak

@RFTool.action_call('move tool')
class RFTool_Tweak(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['selectadd/deselect'] = self.modal_selectadd_deselect
        self.FSM['select'] = self.modal_select
        self.FSM['move'] = self.modal_move
    
    def name(self): return "Tweak"
    def icon(self): return "rf_tweak_icon"
    def description(self): return 'Moves vertices with falloff'
    def helptext(self): return help_tweak
    def get_label(self): return 'Tweak (%s)' % ','.join(default_keymap['move tool'])
    def get_tooltip(self): return 'Tweak (%s)' % ','.join(default_keymap['move tool'])
    
    def get_move_boundary(self): return options['tweak boundary']
    def set_move_boundary(self, v): options['tweak boundary'] = v
    
    def get_move_hidden(self): return options['tweak hidden']
    def set_move_hidden(self, v): options['tweak hidden'] = v
    
    def get_ui_options(self):
        return [
            UI_BoolValue('Boundary', self.get_move_boundary, self.set_move_boundary),
            UI_BoolValue('Hidden', self.get_move_hidden, self.set_move_hidden),
        ]
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('brush falloff', color=(0.5, 0.5, 1.0))
        self.sel_only = False
    
    def get_ui_icon(self):
        self.ui_icon = UI_Image('tweak_32.png')
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
            return self.prep_move()
    
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
    
    def prep_move(self):
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_mouse(radius)
        if not nearest: return
        
        self.rfcontext.undo_push('tweak move')
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        get_strength_dist = self.rfwidget.get_strength_dist
        hidden = self.get_move_hidden()
        boundary = self.get_move_boundary()
        def is_visible(bmv): return self.rfcontext.is_visible(bmv.co, bmv.normal)
        self.bmverts = [(bmv, Point_to_Point2D(bmv.co), get_strength_dist(d3d)) for bmv,d3d in nearest]
        if self.sel_only: self.bmverts = [(bmv,p2d,s) for bmv,p2d,s in self.bmverts if bmv.select]
        if not boundary:  self.bmverts = [(bmv,p2d,s) for bmv,p2d,s in self.bmverts if not bmv.is_boundary]
        if not hidden:    self.bmverts = [(bmv,p2d,s) for bmv,p2d,s in self.bmverts if is_visible(bmv)]
        self.bmfaces = set([f for bmv,_ in nearest for f in bmv.link_faces])
        self.mousedown = self.rfcontext.actions.mousedown
        return 'move'
    
    @RFTool.dirty_when_done
    def modal_move(self):
        if self.rfcontext.actions.released(['action','action alt0']):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'
        
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        update_face_normal = self.rfcontext.update_face_normal
        
        for bmv,xy,strength in self.bmverts:
            set2D_vert(bmv, xy + delta*strength)
        for bmf in self.bmfaces:
            update_face_normal(bmf)
    
    def draw_postview(self): pass
    def draw_postpixel(self): pass
    
