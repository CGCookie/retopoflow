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

import bgl

from ..rftool import RFTool
from ..rfwidgets import rfwidget_brushfalloff

from ...addon_common.common.drawing import (
    CC_DRAW,
    CC_2D_POINTS,
    CC_2D_LINES, CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES, CC_2D_TRIANGLE_FAN,
)

from ...addon_common.common import ui
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import Point, Point2D, Vec2D, Color
from ...addon_common.common.globals import Globals
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.blender import tag_redraw_all

from ...config.options import options, themes


class RFTool_Tweak(RFTool):
    name        = 'Tweak'
    description = 'Adjust vertex positions with a smooth brush'
    icon        = 'tweak_32.png'
    help        = 'tweak.md'
    shortcut    = 'tweak tool'

class Tweak_RFWidgets:
    RFWidget_BrushFalloff = rfwidget_brushfalloff.create_new_class()

    def init_rfwidgets(self):
        self.rfwidget = self.RFWidget_BrushFalloff(self)


class Tweak(RFTool_Tweak, Tweak_RFWidgets):
    @RFTool_Tweak.on_init
    def init(self):
        self.init_rfwidgets()
        self._var_mask_boundary = BoundBool('''options['tweak mask boundary']''')
        self._var_mask_hidden   = BoundBool('''options['tweak mask hidden']''')
        self._var_mask_selected = BoundBool('''options['tweak mask selected']''')

    @RFTool_Tweak.on_ui_setup
    def ui(self):
        return ui.collapsible('Tweak', children=[
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

    @RFTool_Tweak.on_reset
    def reset(self):
        self.sel_only = False
        self.rfwidget.color = Color((1.0, 0.5, 0.1, 1.0))

    @RFTool_Tweak.FSM_State('main')
    def main(self):
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
            return 'move'

    @RFTool_Tweak.FSM_State('selectadd/deselect')
    @profiler.function
    def modal_selectadd_deselect(self):
        if not self.rfcontext.actions.using(['select single','select single add']):
            self.rfcontext.undo_push('deselect')
            face,_ = self.rfcontext.accel_nearest2D_face()
            if face and face.select: self.rfcontext.deselect(face)
            return 'main'
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        if delta.length > self.drawing.scale(5):
            self.rfcontext.undo_push('select add')
            return 'select'

    @RFTool_Tweak.FSM_State('select')
    @profiler.function
    def modal_select(self):
        if not self.rfcontext.actions.using(['select single','select single add']):
            return 'main'
        bmf,_ = self.rfcontext.accel_nearest2D_face(max_dist=10)
        if not bmf or bmf.select: return
        self.rfcontext.select(bmf, supparts=False, only=False)


    @RFTool_Tweak.FSM_State('move', 'can enter')
    def move_can_enter(self):
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_mouse(radius)
        if not nearest: return False

    @RFTool_Tweak.FSM_State('move', 'enter')
    def move_enter(self):
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_mouse(radius)

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
        self._timer = self.actions.start_timer(120.0)

    @RFTool_Tweak.FSM_State('move')
    @RFTool_Tweak.dirty_when_done
    def move(self):
        if self.rfcontext.actions.released(['brush','brush alt']):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        # only update cut on timer events and when mouse has moved
        if not self.rfcontext.actions.timer: return
        if self.actions.mouse_prev == self.actions.mouse: return

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        update_face_normal = self.rfcontext.update_face_normal

        for bmv,xy,strength in self.bmverts:
            set2D_vert(bmv, xy + delta*strength)
        for bmf in self.bmfaces:
            update_face_normal(bmf)

    @RFTool_Tweak.FSM_State('move', 'exit')
    def move_exit(self):
        self._timer.done()
