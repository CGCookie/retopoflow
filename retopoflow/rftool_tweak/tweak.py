'''
Copyright (C) 2023 CG Cookie
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

from ..rftool import RFTool
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_brushfalloff import RFWidget_BrushFalloff_Factory

from ...addon_common.common.drawing import (
    CC_DRAW,
    CC_2D_POINTS,
    CC_2D_LINES, CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES, CC_2D_TRIANGLE_FAN,
)

from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import Point, Point2D, Vec2D, Color, closest_point_segment
from ...addon_common.common.fsm import FSM
from ...addon_common.common.globals import Globals
from ...addon_common.common.utils import iter_pairs, delay_exec
from ...addon_common.common.blender import tag_redraw_all

from ...config.options import options, themes


class Tweak(RFTool):
    name        = 'Tweak'
    description = 'Adjust vertex positions with a smooth brush'
    icon        = 'tweak-icon.png'
    help        = 'tweak.md'
    shortcut    = 'tweak tool'
    quick_shortcut = 'tweak quick'
    statusbar   = '{{brush}} Tweak\t{{brush alt}} Tweak selection\t{{brush radius}} Brush size\t{{brush strength}} Brush strength\t{{brush falloff}} Brush falloff'
    ui_config   = 'tweak_options.html'

    RFWidget_Default      = RFWidget_Default_Factory.create()
    RFWidget_BrushFalloff = RFWidget_BrushFalloff_Factory.create(
        'Tweak brush',
        BoundInt('''options['tweak radius']''', min_value=1),
        BoundFloat('''options['tweak falloff']''', min_value=0.00, max_value=100.0),
        BoundFloat('''options['tweak strength']''', min_value=0.01, max_value=1.0),
        fill_color=themes['tweak'],
    )

    @RFTool.on_init
    def init(self):
        self.rfwidgets = {
            'default':     self.RFWidget_Default(self),
            'brushstroke': self.RFWidget_BrushFalloff(self),
        }
        self.rfwidget = None

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

    @RFTool.on_ui_setup
    def ui(self):
        self.update_preset_name(1)
        self.update_preset_name(2)
        self.update_preset_name(3)
        self.update_preset_name(4)

    @RFTool.on_reset
    def reset(self):
        self.sel_only = False

    @FSM.on_state('main')
    def main(self):
        if self.actions.using_onlymods(['brush', 'brush alt', 'brush radius', 'brush falloff', 'brush strength']):
            self.set_widget('brushstroke')
        else:
            self.set_widget('default')

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


    @FSM.on_state('move', 'can enter')
    def move_can_enter(self):
        radius = self.rfwidgets['brushstroke'].get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_mouse(radius)
        if not nearest: return False

    @FSM.on_state('move', 'enter')
    def move_enter(self):
        # gather options
        opt_mask_boundary = options['tweak mask boundary']
        opt_mask_symmetry = options['tweak mask symmetry']
        opt_mask_occluded = options['tweak mask occluded']
        opt_mask_selected = options['tweak mask selected']

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        hit_pos = self.rfcontext.get_point3D(self.actions.mouse)
        def get_strength_dist(bmv):
            return self.rfwidgets['brushstroke'].get_strength_dist((bmv.co - hit_pos).length)
        is_visible = self.rfcontext.gen_is_visible(occlusion_test_override=True)  # always perform occlusion test
        is_bmvert_visible = lambda bmv: is_visible(bmv.co, bmv.normal)
        def on_planes(bmv):
            return self.rfcontext.symmetry_planes_for_point(bmv.co) if opt_mask_symmetry == 'maintain' else None

        # get all verts under brush
        radius = self.rfwidgets['brushstroke'].get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_mouse(radius)
        self.bmverts = [ bmv for (bmv, _) in nearest ]
        # filter verts based on options
        if self.sel_only:                  self.bmverts = [bmv for bmv in self.bmverts if bmv.select]
        if opt_mask_boundary == 'exclude': self.bmverts = [bmv for bmv in self.bmverts if not bmv.is_on_boundary()]
        if opt_mask_symmetry == 'exclude': self.bmverts = [bmv for bmv in self.bmverts if not bmv.is_on_symmetry_plane()]
        if opt_mask_occluded == 'exclude': self.bmverts = [bmv for bmv in self.bmverts if is_bmvert_visible(bmv)]
        if opt_mask_selected == 'exclude': self.bmverts = [bmv for bmv in self.bmverts if not bmv.select]
        if opt_mask_selected == 'only':    self.bmverts = [bmv for bmv in self.bmverts if bmv.select]

        self.bmvert_data = [
            (bmv, on_planes(bmv), Point_to_Point2D(bmv.co), Point(bmv.co), get_strength_dist(bmv))
            for bmv in self.bmverts
        ]

        if opt_mask_boundary == 'slide':
            self._boundary = [(bme.verts[0].co, bme.verts[1].co) for bme in self.rfcontext.iter_edges() if not bme.is_manifold]
        else:
            self._boundary = []

        self.bmfaces = set([f for bmv,_ in nearest for f in bmv.link_faces])
        self.mousedown = self.rfcontext.actions.mousedown
        self._timer = self.actions.start_timer(120.0)

        self.rfcontext.split_target_visualization(verts=self.bmverts)
        self.rfcontext.undo_push('tweak move')

    @FSM.on_state('move')
    def move(self):
        if self.rfcontext.actions.released(['brush','brush alt']):
            return 'main'

        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            self.actions.unuse('brush', ignoremods=True, ignoremulti=True)
            self.actions.unuse('brush alt', ignoremods=True, ignoremulti=True)
            return 'main'

    @RFTool.on_events('mouse move')
    @RFTool.once_per_frame
    @FSM.onlyinstate('move')
    @RFTool.dirty_when_done
    def move_doit(self):
        if self.actions.mouse_prev == self.actions.mouse: return

        opt_mask_boundary = options['tweak mask symmetry']
        opt_mask_boundary = options['tweak mask boundary']

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        snap_vert = self.rfcontext.snap_vert
        update_face_normal = self.rfcontext.update_face_normal

        for (bmv, sympl, xy, xyz, strength) in self.bmvert_data:
            co2D = xy + delta * strength
            match options['tweak mode']:
                case 'snap':
                    dist = self.rfcontext.Point_to_depth(xyz)
                    bmv.co = self.rfcontext.Point2D_to_Point(co2D, dist)
                    snap_vert(bmv, snap_to_symmetry=sympl)
                case 'raycast':
                    set2D_vert(bmv, co2D, sympl)
                case _:
                    assert False, f'Invalid tweak mode {options["tweak mode"]}'


            if opt_mask_boundary == 'slide' and bmv.is_on_boundary():
                co = bmv.co
                p, d = None, None
                for (v0, v1) in self._boundary:
                    p_ = closest_point_segment(co, v0, v1)
                    d_ = (p_ - co).length
                    if p is None or d_ < d: p, d = p_, d_
                if p is not None:
                    bmv.co = p
                    self.rfcontext.snap_vert(bmv)

        for bmf in self.bmfaces:
            update_face_normal(bmf)

        tag_redraw_all('Tweak mouse move')

    @FSM.on_state('move', 'exit')
    def move_exit(self):
        self.rfcontext.clear_split_target_visualization()
        self._timer.done()
