'''
Copyright (C) 2021 CG Cookie
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
from ..rfwidgets.rfwidget_brushfalloff import RFWidget_BrushFalloff_Factory

from ...addon_common.common.drawing import (
    CC_DRAW,
    CC_2D_POINTS,
    CC_2D_LINES, CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES, CC_2D_TRIANGLE_FAN,
)

from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import Point, Point2D, Vec2D, Color
from ...addon_common.common.globals import Globals
from ...addon_common.common.utils import iter_pairs, delay_exec
from ...addon_common.common.blender import tag_redraw_all

from ...config.options import options, themes


class RFTool_Tweak(RFTool):
    name        = 'Tweak'
    description = 'Adjust vertex positions with a smooth brush'
    icon        = 'tweak-icon.png'
    help        = 'tweak.md'
    shortcut    = 'tweak tool'
    statusbar   = '{{brush}} Tweak\t{{brush alt}} Tweak selection\t{{brush radius}} Brush size\t{{brush strength}} Brush strength\t{{brush falloff}} Brush falloff'
    ui_config   = 'tweak_options.html'

class Tweak_RFWidgets:
    RFWidget_BrushFalloff = RFWidget_BrushFalloff_Factory.create(
        BoundInt('''options['tweak radius']''', min_value=1),
        BoundFloat('''options['tweak falloff']''', min_value=0.00, max_value=100.0),
        BoundFloat('''options['tweak strength']''', min_value=0.01, max_value=1.0),
        fill_color=themes['tweak'],
    )

    def init_rfwidgets(self):
        self.rfwidget = self.RFWidget_BrushFalloff(self)


class Tweak(RFTool_Tweak, Tweak_RFWidgets):
    @RFTool_Tweak.on_init
    def init(self):
        self.init_rfwidgets()

    def reset_current_brush(self):
        options.reset(keys={'tweak radius', 'tweak falloff', 'tweak strength'})
        self.document.body.getElementById(f'tweak-current-radius').dirty(cause='copied preset to current brush')
        self.document.body.getElementById(f'tweak-current-strength').dirty(cause='copied preset to current brush')
        self.document.body.getElementById(f'tweak-current-falloff').dirty(cause='copied preset to current brush')

    def update_preset_name(self, n):
        name = options[f'tweak preset {n} name']
        self.document.body.getElementById(f'tweak-preset-{n}-summary').innerText = f'Preset: {name}'

    def copy_current_to_preset(self, n):
        options[f'tweak preset {n} radius']   = options['tweak radius']
        options[f'tweak preset {n} strength'] = options['tweak strength']
        options[f'tweak preset {n} falloff']  = options['tweak falloff']
        self.document.body.getElementById(f'tweak-preset-{n}-radius').dirty(cause='copied current brush to preset')
        self.document.body.getElementById(f'tweak-preset-{n}-strength').dirty(cause='copied current brush to preset')
        self.document.body.getElementById(f'tweak-preset-{n}-falloff').dirty(cause='copied current brush to preset')

    def copy_preset_to_current(self, n):
        options['tweak radius']   = options[f'tweak preset {n} radius']
        options['tweak strength'] = options[f'tweak preset {n} strength']
        options['tweak falloff']  = options[f'tweak preset {n} falloff']
        self.document.body.getElementById(f'tweak-current-radius').dirty(cause='copied preset to current brush')
        self.document.body.getElementById(f'tweak-current-strength').dirty(cause='copied preset to current brush')
        self.document.body.getElementById(f'tweak-current-falloff').dirty(cause='copied preset to current brush')

    @RFTool_Tweak.on_ui_setup
    def ui(self):
        self.update_preset_name(1)
        self.update_preset_name(2)
        self.update_preset_name(3)
        self.update_preset_name(4)

    @RFTool_Tweak.on_reset
    def reset(self):
        self.sel_only = False

    @RFTool_Tweak.FSM_State('main')
    def main(self):
        if self.rfcontext.actions.pressed(['brush', 'brush alt'], unpress=False):
            self.sel_only = self.rfcontext.actions.using('brush alt')
            self.rfcontext.actions.unpress()
            return 'move'

        if self.rfcontext.actions.pressed('pie menu alt0', unpress=False):
            def callback(option):
                if option is None: return
                self.copy_preset_to_current(option)
            self.rfcontext.show_pie_menu([
                (f'Preset: {options["tweak preset 1 name"]}', 1),
                (f'Preset: {options["tweak preset 2 name"]}', 2),
                (f'Preset: {options["tweak preset 3 name"]}', 3),
                (f'Preset: {options["tweak preset 4 name"]}', 4),
            ], callback)
            return


        # if self.rfcontext.actions.pressed('select single'):
        #     self.rfcontext.undo_push('select')
        #     self.rfcontext.deselect_all()
        #     return 'select'

        # if self.rfcontext.actions.pressed('select single add'):
        #     face,_ = self.rfcontext.accel_nearest2D_face(max_dist=10)
        #     if not face: return
        #     if face.select:
        #         self.mousedown = self.rfcontext.actions.mouse
        #         return 'selectadd/deselect'
        #     return 'select'

        # if self.rfcontext.actions.pressed({'select smart', 'select smart add'}, unpress=False):
        #     if self.rfcontext.actions.pressed('select smart'):
        #         self.rfcontext.deselect_all()
        #     self.rfcontext.actions.unpress()
        #     edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
        #     if not edge: return
        #     faces = set()
        #     walk = {edge}
        #     touched = set()
        #     while walk:
        #         edge = walk.pop()
        #         if edge in touched: continue
        #         touched.add(edge)
        #         nfaces = set(f for f in edge.link_faces if f not in faces and len(f.edges) == 4)
        #         walk |= {f.opposite_edge(edge) for f in nfaces}
        #         faces |= nfaces
        #     self.rfcontext.select(faces, only=False)
        #     return

    # @RFTool_Tweak.FSM_State('selectadd/deselect')
    # @profiler.function
    # def modal_selectadd_deselect(self):
    #     if not self.rfcontext.actions.using(['select single','select single add']):
    #         self.rfcontext.undo_push('deselect')
    #         face,_ = self.rfcontext.accel_nearest2D_face()
    #         if face and face.select: self.rfcontext.deselect(face)
    #         return 'main'
    #     delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
    #     if delta.length > self.drawing.scale(5):
    #         self.rfcontext.undo_push('select add')
    #         return 'select'

    # @RFTool_Tweak.FSM_State('select')
    # @profiler.function
    # def modal_select(self):
    #     if not self.rfcontext.actions.using(['select single','select single add']):
    #         return 'main'
    #     bmf,_ = self.rfcontext.accel_nearest2D_face(max_dist=10)
    #     if not bmf or bmf.select: return
    #     self.rfcontext.select(bmf, supparts=False, only=False)


    @RFTool_Tweak.FSM_State('move', 'can enter')
    def move_can_enter(self):
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_mouse(radius)
        if not nearest: return False

    @RFTool_Tweak.FSM_State('move', 'enter')
    def move_enter(self):
        # gather options
        opt_mask_boundary = options['tweak mask boundary']
        opt_mask_symmetry = options['tweak mask symmetry']
        opt_mask_hidden   = options['tweak mask hidden']
        opt_mask_selected = options['tweak mask selected']

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        get_strength_dist = self.rfwidget.get_strength_dist
        def is_visible(bmv):
            return self.rfcontext.is_visible(bmv.co, bmv.normal)
        def on_planes(bmv):
            return self.rfcontext.symmetry_planes_for_point(bmv.co) if opt_mask_symmetry == 'maintain' else None

        # get all verts under brush
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_mouse(radius)
        self.bmverts = [(bmv, on_planes(bmv), Point_to_Point2D(bmv.co), get_strength_dist(d3d)) for (bmv, d3d) in nearest]
        # filter verts based on options
        if self.sel_only:                  self.bmverts = [(bmv,sympl,p2d,s) for (bmv,sympl,p2d,s) in self.bmverts if bmv.select]
        if opt_mask_boundary == 'exclude': self.bmverts = [(bmv,sympl,p2d,s) for (bmv,sympl,p2d,s) in self.bmverts if not bmv.is_on_boundary()]
        if opt_mask_symmetry == 'exclude': self.bmverts = [(bmv,sympl,p2d,s) for (bmv,sympl,p2d,s) in self.bmverts if not bmv.is_on_symmetry_plane()]
        if opt_mask_hidden   == 'exclude': self.bmverts = [(bmv,sympl,p2d,s) for (bmv,sympl,p2d,s) in self.bmverts if is_visible(bmv)]
        if opt_mask_selected == 'exclude': self.bmverts = [(bmv,sympl,p2d,s) for (bmv,sympl,p2d,s) in self.bmverts if not bmv.select]
        if opt_mask_selected == 'only':    self.bmverts = [(bmv,sympl,p2d,s) for (bmv,sympl,p2d,s) in self.bmverts if bmv.select]

        self.bmfaces = set([f for bmv,_ in nearest for f in bmv.link_faces])
        self.mousedown = self.rfcontext.actions.mousedown
        self._timer = self.actions.start_timer(120.0)

        self.rfcontext.undo_push('tweak move')

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

        for bmv,sympl,xy,strength in self.bmverts:
            nco = set2D_vert(bmv, xy + delta*strength, sympl)
        for bmf in self.bmfaces:
            update_face_normal(bmf)

    @RFTool_Tweak.FSM_State('move', 'exit')
    def move_exit(self):
        self._timer.done()
