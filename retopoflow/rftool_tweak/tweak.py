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
from ..rfwidgets.rfwidget_brushfalloff import RFWidget_BrushFalloff_Factory

from ...addon_common.common.drawing import (
    CC_DRAW,
    CC_2D_POINTS,
    CC_2D_LINES, CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES, CC_2D_TRIANGLE_FAN,
)

from ...addon_common.common import ui
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

class Tweak_RFWidgets:
    RFWidget_BrushFalloff = RFWidget_BrushFalloff_Factory.create(
        BoundFloat('''options['tweak radius']'''),
        BoundFloat('''options['tweak falloff']'''),
        BoundFloat('''options['tweak strength']'''),
        fill_color=themes['tweak'],
    )

    def init_rfwidgets(self):
        self.rfwidget = self.RFWidget_BrushFalloff(self)


class Tweak(RFTool_Tweak, Tweak_RFWidgets):
    @RFTool_Tweak.on_init
    def init(self):
        self.init_rfwidgets()

    @RFTool_Tweak.on_ui_setup
    def ui(self):
        def tweak_mask_boundary_change(e):
            if not e.target.checked: return
            options['tweak mask boundary'] = e.target.value
        def tweak_mask_symmetry_change(e):
            if not e.target.checked: return
            options['tweak mask symmetry'] = e.target.value
        def tweak_mask_hidden_change(e):
            if not e.target.checked: return
            options['tweak mask hidden'] = e.target.value
        def tweak_mask_selected_change(e):
            if not e.target.checked: return
            options['tweak mask selected'] = e.target.value
        def assign_preset_to_current(n):
            options[f'tweak preset {n} radius']   = options['tweak radius']
            options[f'tweak preset {n} strength'] = options['tweak strength']
            options[f'tweak preset {n} falloff']  = options['tweak falloff']
        def update_preset_name(n):
            nonlocal tweak_options
            ui = f'tweak-preset-{n}_summary'
            name = options[f'tweak preset {n} name']
            tweak_options.getElementById(ui).innerText = f'Preset: {name}'

        tweak_options = ui.details(summary='Tweak', children=[
            ui.collection('Masking Options', id='tweak-masking', children=[
                ui.collection('Boundary', children=[
                    ui.input_radio(
                        title='Tweak vertices not along boundary',
                        value='exclude',
                        checked=(options['tweak mask boundary']=='exclude'),
                        name='tweak-boundary',
                        classes='half-size',
                        children=[ui.label(innerText='Exclude')],
                        on_input=tweak_mask_boundary_change,
                    ),
                    ui.input_radio(
                        title='Tweak all vertices within brush, regardless of being along boundary',
                        value='include',
                        checked=(options['tweak mask boundary']=='include'),
                        name='tweak-boundary',
                        classes='half-size',
                        children=[ui.label(innerText='Include')],
                        on_input=tweak_mask_boundary_change,
                    ),
                ]),
                ui.collection('Symmetry', children=[
                    ui.input_radio(
                        title='Tweak vertices not along symmetry plane',
                        value='exclude',
                        checked=(options['tweak mask symmetry']=='exclude'),
                        name='tweak-symmetry',
                        classes='third-size',
                        children=[ui.label(innerText='Exclude')],
                        on_input=tweak_mask_symmetry_change,
                    ),
                    ui.input_radio(
                        title='Tweak vertices along symmetry plane, but keep them on symmetry plane',
                        value='maintain',
                        checked=(options['tweak mask symmetry']=='maintain'),
                        name='tweak-symmetry',
                        classes='third-size',
                        children=[ui.label(innerText='Maintain')],
                        on_input=tweak_mask_symmetry_change,
                    ),
                    ui.input_radio(
                        title='Tweak all vertices within brush, regardless of being along symmetry plane',
                        value='include',
                        checked=(options['tweak mask symmetry']=='include'),
                        name='tweak-symmetry',
                        classes='third-size',
                        children=[ui.label(innerText='Include')],
                        on_input=tweak_mask_symmetry_change,
                    ),
                ]),
                ui.collection('Hidden', children=[
                    ui.input_radio(
                        title='Tweak only visible vertices',
                        value='exclude',
                        checked=(options['tweak mask hidden']=='exclude'),
                        name='tweak-hidden',
                        classes='half-size',
                        children=[ui.label(innerText='Exclude')],
                        on_input=tweak_mask_hidden_change,
                    ),
                    ui.input_radio(
                        title='Tweak all vertices within brush, regardless of visibility',
                        value='include',
                        checked=(options['tweak mask hidden']=='include'),
                        name='tweak-hidden',
                        classes='half-size',
                        children=[ui.label(innerText='Include')],
                        on_input=tweak_mask_hidden_change,
                    ),
                ]),
                ui.collection('Selected', children=[
                    ui.input_radio(
                        title='Tweak only unselected vertices',
                        value='exclude',
                        checked=(options['tweak mask selected']=='exclude'),
                        name='tweak-selected',
                        classes='third-size',
                        children=[ui.label(innerText='Exclude')],
                        on_input=tweak_mask_selected_change,
                    ),
                    ui.input_radio(
                        title='Tweak only selected vertices',
                        value='only',
                        checked=(options['tweak mask selected']=='only'),
                        name='tweak-selected',
                        classes='third-size',
                        children=[ui.label(innerText='Only')],
                        on_input=tweak_mask_selected_change,
                    ),
                    ui.input_radio(
                        title='Tweak all vertices within brush, regardless of selection',
                        value='all',
                        checked=(options['tweak mask selected']=='all'),
                        name='tweak-selected',
                        classes='third-size',
                        children=[ui.label(innerText='All')],
                        on_input=tweak_mask_selected_change,
                    ),
                ]),
            ]),
            ui.details(summary='Brush Options', children=[
                ui.collection(label='Current', children=[
                    ui.labeled_input_text(label='Size',     title='Adjust brush size',     value=self.rfwidget.get_radius_boundvar()),
                    ui.labeled_input_text(label='Strength', title='Adjust brush strength', value=self.rfwidget.get_strength_boundvar()),
                    ui.labeled_input_text(label='Falloff',  title='Adjust brush falloff',  value=self.rfwidget.get_falloff_boundvar()),
                    ui.button(label='Reset', title='Reset brush options to defaults', on_mouseclick=delay_exec('''options.reset(keys={"tweak radius","tweak falloff","tweak strength"})''')),
                ]),
                ui.details(summary='Preset: Preset 1',    id='tweak-preset-1', children=[
                    ui.labeled_input_text(label='Name',     title='Adjust name of preset 1',            id='tweak-preset-1-name',     value=BoundString('''options['tweak preset 1 name']''',    on_change=delay_exec('''update_preset_name(1)'''))),
                    ui.labeled_input_text(label='Size',     title='Adjust brush size for preset 1',     id='tweak-preset-1-size',     value=BoundFloat('''options['tweak preset 1 radius']''',   min_value=1.0)),
                    ui.labeled_input_text(label='Strength', title='Adjust brush strength for preset 1', id='tweak-preset-1-strength', value=BoundFloat('''options['tweak preset 1 strength']''', min_value=0.01, max_value=1.0)),
                    ui.labeled_input_text(label='Falloff',  title='Adjust brush falloff for preset 1',  id='tweak-preset-1-falloff',  value=BoundFloat('''options['tweak preset 1 falloff']''',  min_value=0.0,  max_value=100.0)),
                    ui.button(label='Current to Preset',    title='Assign preset 1 setting to current brush settings', on_mouseclick=delay_exec('''assign_preset_to_current(1)'''))
                ]),
                ui.details(summary='Preset: Preset 2',    id='tweak-preset-2', children=[
                    ui.labeled_input_text(label='Name',     title='Adjust name of preset 2',            id='tweak-preset-2-name',     value=BoundString('''options['tweak preset 2 name']''',    on_change=delay_exec('''update_preset_name(2)'''))),
                    ui.labeled_input_text(label='Size',     title='Adjust brush size for preset 2',     id='tweak-preset-2-size',     value=BoundFloat('''options['tweak preset 2 radius']''',   min_value=1.0)),
                    ui.labeled_input_text(label='Strength', title='Adjust brush strength for preset 2', id='tweak-preset-2-strength', value=BoundFloat('''options['tweak preset 2 strength']''', min_value=0.01, max_value=1.0)),
                    ui.labeled_input_text(label='Falloff',  title='Adjust brush falloff for preset 2',  id='tweak-preset-2-falloff',  value=BoundFloat('''options['tweak preset 2 falloff']''',  min_value=0.0,  max_value=100.0)),
                    ui.button(label='Current to Preset',    title='Assign preset 2 setting to current brush settings', on_mouseclick=delay_exec('''assign_preset_to_current(2)'''))
                ]),
                ui.details(summary='Preset: Preset 3',    id='tweak-preset-3', children=[
                    ui.labeled_input_text(label='Name',     title='Adjust name of preset 3',            id='tweak-preset-3-name',     value=BoundString('''options['tweak preset 3 name']''',    on_change=delay_exec('''update_preset_name(3)'''))),
                    ui.labeled_input_text(label='Size',     title='Adjust brush size for preset 3',     id='tweak-preset-3-size',     value=BoundFloat('''options['tweak preset 3 radius']''',   min_value=1.0)),
                    ui.labeled_input_text(label='Strength', title='Adjust brush strength for preset 3', id='tweak-preset-3-strength', value=BoundFloat('''options['tweak preset 3 strength']''', min_value=0.01, max_value=1.0)),
                    ui.labeled_input_text(label='Falloff',  title='Adjust brush falloff for preset 3',  id='tweak-preset-3-falloff',  value=BoundFloat('''options['tweak preset 3 falloff']''',  min_value=0.0,  max_value=100.0)),
                    ui.button(label='Current to Preset',    title='Assign preset 3 setting to current brush settings', on_mouseclick=delay_exec('''assign_preset_to_current(3)'''))
                ]),
                ui.details(summary='Preset: Preset 4',    id='tweak-preset-4', children=[
                    ui.labeled_input_text(label='Name',     title='Adjust name of preset 4',            id='tweak-preset-4-name',     value=BoundString('''options['tweak preset 4 name']''',    on_change=delay_exec('''update_preset_name(4)'''))),
                    ui.labeled_input_text(label='Size',     title='Adjust brush size for preset 4',     id='tweak-preset-3-size',     value=BoundFloat('''options['tweak preset 4 radius']''',   min_value=1.0)),
                    ui.labeled_input_text(label='Strength', title='Adjust brush strength for preset 4', id='tweak-preset-3-strength', value=BoundFloat('''options['tweak preset 4 strength']''', min_value=0.01, max_value=1.0)),
                    ui.labeled_input_text(label='Falloff',  title='Adjust brush falloff for preset 4',  id='tweak-preset-3-falloff',  value=BoundFloat('''options['tweak preset 4 falloff']''',  min_value=0.0,  max_value=100.0)),
                    ui.button(label='Current to Preset',    title='Assign preset 4 setting to current brush settings', on_mouseclick=delay_exec('''assign_preset_to_current(4)'''))
                ]),
            ]),
        ])
        update_preset_name(1)
        update_preset_name(2)
        update_preset_name(3)
        update_preset_name(4)
        return tweak_options

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
                options['tweak radius']   = options[f'tweak preset {option} radius']
                options['tweak strength'] = options[f'tweak preset {option} strength']
                options['tweak falloff']  = options[f'tweak preset {option} falloff']
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
