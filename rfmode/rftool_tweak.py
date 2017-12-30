'''
Copyright (C) 2017 CG Cookie
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
from ..options import options, help_tweak
from ..lib.classes.profiler.profiler import profiler

@RFTool.action_call('move tool')
class RFTool_Tweak(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['move'] = self.modal_move
        
        # following vars are for self.vis_accel
        self.defer_recomputing = False
        self.recompute = True
        self.target_version = None
        self.view_version = None
        self.vis_verts = None
        self.vis_edges = None
        self.vis_faces = None
        self.vis_accel = None
    
    def name(self): return "Tweak"
    def icon(self): return "rf_tweak_icon"
    def description(self): return 'Moves vertices with falloff'
    def helptext(self): return help_tweak
    
    def get_move_boundary(self): return options['tweak boundary']
    def set_move_boundary(self, v): options['tweak boundary'] = v
    
    def get_move_hidden(self): return options['tweak hidden']
    def set_move_hidden(self, v): options['tweak hidden'] = v
    
    def get_move_selected(self): return options['tweak selected']
    def set_move_selected(self, v): options['tweak selected'] = v
    
    def get_ui_options(self):
        return [
            UI_BoolValue('Selected Only', self.get_move_selected, self.set_move_selected),
            UI_BoolValue('Boundary', self.get_move_boundary, self.set_move_boundary),
            UI_BoolValue('Hidden', self.get_move_hidden, self.set_move_hidden),
        ]
    
    ''' Called the tool is being switched into '''
    def start(self):
        self.rfwidget.set_widget('brush falloff', color=(0.5, 0.5, 1.0))
    
    def get_ui_icon(self):
        self.ui_icon = UI_Image('tweak_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    @profiler.profile
    def update_accel_struct(self):
        target_version = self.rfcontext.get_target_version(selection=False)
        view_version = self.rfcontext.get_view_version()
        
        recompute = self.recompute
        recompute |= self.target_version != target_version
        recompute |= self.view_version != view_version
        recompute |= self.vis_verts is None
        recompute |= self.vis_edges is None
        recompute |= self.vis_faces is None
        recompute |= self.vis_accel is None
        
        self.recompute = False
        
        if recompute and not self.defer_recomputing:
            self.target_version = target_version
            self.view_version = view_version
            
            self.vis_verts = self.rfcontext.visible_verts()
            self.vis_edges = self.rfcontext.visible_edges(verts=self.vis_verts)
            self.vis_faces = self.rfcontext.visible_faces(verts=self.vis_verts)
            self.vis_accel = Accel2D(self.vis_verts, self.vis_edges, self.vis_faces, self.rfcontext.get_point2D)
    
    def modal_main(self):
        self.update_accel_struct()
        
        if self.rfcontext.actions.using(['select', 'select add']):
            self.defer_recomputing = True
            if self.rfcontext.actions.pressed('select'):
                self.rfcontext.undo_push('select')
                self.rfcontext.deselect_all()
            elif self.rfcontext.actions.pressed('select add'):
                self.rfcontext.undo_push('select add')
            pr = profiler.start('finding nearest')
            xy = self.rfcontext.get_point2D(self.rfcontext.actions.mouse)
            bmf = self.vis_accel.nearest_face(xy)
            pr.done()
            if bmf and not bmf.select:
                self.rfcontext.select(bmf, supparts=False, only=False)
            return
        
        self.defer_recomputing = False
        
        if self.rfcontext.actions.pressed('action'):
            return self.prep_move()
    
    def prep_move(self):
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_mouse(radius)
        if not nearest: return
        
        self.rfcontext.undo_push('tweak move')
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        get_strength_dist = self.rfwidget.get_strength_dist
        sel_only = self.get_move_selected()
        hidden = self.get_move_hidden()
        boundary = self.get_move_boundary()
        def is_visible(bmv): return self.rfcontext.is_visible(bmv.co, bmv.normal)
        self.bmverts = [(bmv, Point_to_Point2D(bmv.co), get_strength_dist(d3d)) for bmv,d3d in nearest]
        if sel_only:     self.bmverts = [(bmv,p2d,s) for bmv,p2d,s in self.bmverts if bmv.select]
        if not boundary: self.bmverts = [(bmv,p2d,s) for bmv,p2d,s in self.bmverts if not bmv.is_boundary]
        if not hidden:   self.bmverts = [(bmv,p2d,s) for bmv,p2d,s in self.bmverts if is_visible(bmv)]
        self.bmfaces = set([f for bmv,_ in nearest for f in bmv.link_faces])
        self.mousedown = self.rfcontext.actions.mousedown
        return 'move'
    
    @RFTool.dirty_when_done
    def modal_move(self):
        if self.rfcontext.actions.released('action'):
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
    
