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
from ..common.maths import Point,Point2D,Vec2D,Vec,Accel2D
from ..common.ui import UI_Image, UI_BoolValue, UI_Label, UI_Container, UI_IntValue, UI_Frame
from ..common.profiler import profiler
from ..keymaps import default_rf_keymaps
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
    def get_label(self): return 'Tweak (%s)' % ','.join(default_rf_keymaps['move tool'])
    def get_tooltip(self): return 'Tweak (%s)' % ','.join(default_rf_keymaps['move tool'])

    def get_ui_options(self):
        ui_mask = UI_Frame('Masking Options')
        ui_mask.add(UI_BoolValue('Boundary', *options.gettersetter('tweak mask boundary'), tooltip='Enable to mask off vertices that are along boundary of target (includes along symmetry plane)'))
        ui_mask.add(UI_BoolValue('Hidden', *options.gettersetter('tweak mask hidden'), tooltip='Enable to mask off vertices that are hidden behind source'))
        ui_mask.add(UI_BoolValue('Selected', *options.gettersetter('tweak mask selected'), tooltip='Enable to mask off vertices that are selected'))

        ui_brush = UI_Container('Brush Properties')
        ui_brush.add(UI_IntValue('Radius', *self.rfwidget.radius_gettersetter(), tooltip='Set radius of tweak brush'))
        ui_brush.add(UI_IntValue('Falloff', *self.rfwidget.falloff_gettersetter(), tooltip='Set falloff of tweak brush'))
        ui_brush.add(UI_IntValue('Strength', *self.rfwidget.strength_gettersetter(), tooltip='Set strength of tweak brush'))

        return [
            ui_mask,
            ui_brush,
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

        # gather options
        opt_mask_hidden = options['tweak mask hidden']
        opt_mask_boundary = options['tweak mask boundary']
        opt_mask_selected = options['tweak mask selected']

        self.rfcontext.undo_push('tweak move')
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        get_strength_dist = self.rfwidget.get_strength_dist
        def is_visible(bmv): return self.rfcontext.is_visible(bmv.co, bmv.normal)
        self.bmverts = [(bmv, Point_to_Point2D(bmv.co), get_strength_dist(d3d)) for bmv,d3d in nearest]
        if self.sel_only: self.bmverts = [(bmv,p2d,s) for bmv,p2d,s in self.bmverts if bmv.select]
        if opt_mask_boundary: self.bmverts = [(bmv,p2d,s) for bmv,p2d,s in self.bmverts if not bmv.is_boundary]
        if opt_mask_hidden:   self.bmverts = [(bmv,p2d,s) for bmv,p2d,s in self.bmverts if is_visible(bmv)]
        if opt_mask_selected: self.bmverts = [(bmv,p2d,s) for bmv,p2d,s in self.bmverts if not bmv.select]
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

