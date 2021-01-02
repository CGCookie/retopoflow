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

import math
import time
from ..rftool import RFTool
from ..rfwidgets.rfwidget_brushfalloff import RFWidget_BrushFalloff_Factory

from ...addon_common.common.maths import (
    Vec, Vec2D,
    Point, Point2D,
    Direction,
    Accel2D,
    Color,
)
from ...addon_common.common import ui
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs, delay_exec
from ...config.options import options, themes


class RFTool_Relax(RFTool):
    name        = 'Relax'
    description = 'Relax the vertex positions to smooth out topology'
    icon        = 'relax-icon.png'
    help        = 'relax.md'
    shortcut    = 'relax tool'
    statusbar   = '{{brush}} Relax\t{{brush alt}} Relax selection\t{{brush radius}} Brush size\t{{brush strength}} Brush strength\t{{brush falloff}} Brush falloff'

class Relax_RFWidgets:
    RFWidget_BrushFalloff = RFWidget_BrushFalloff_Factory.create(
        BoundFloat('''options['relax radius']'''),
        BoundFloat('''options['relax falloff']'''),
        BoundFloat('''options['relax strength']'''),
        fill_color=themes['relax'],
    )

    def init_rfwidgets(self):
        self.rfwidget = self.RFWidget_BrushFalloff(self)

class Relax(RFTool_Relax, Relax_RFWidgets):
    @RFTool_Relax.on_init
    def init(self):
        self.init_rfwidgets()

    @RFTool_Relax.on_ui_setup
    def ui(self):
        def relax_algorithm_selected_change(e):
            if not e.target.checked: return
            options['relax algorithm'] = e.target.value
        def relax_mask_boundary_change(e):
            if not e.target.checked: return
            options['relax mask boundary'] = e.target.value
        def relax_mask_symmetry_change(e):
            if not e.target.checked: return
            options['relax mask symmetry'] = e.target.value
        def relax_mask_hidden_change(e):
            if not e.target.checked: return
            options['relax mask hidden'] = e.target.value
        def relax_mask_selected_change(e):
            if not e.target.checked: return
            options['relax mask selected'] = e.target.value

        def reset_algorithm_options():
            options.reset(keys=[
                'relax steps',
                'relax force multiplier',
                'relax edge length',
                'relax face radius',
                'relax face sides',
                'relax face angles',
                'relax correct flipped faces',
                'relax straight edges',
            ])
        def disable_all_options():
            for key in [
                    'relax edge length',
                    'relax face radius',
                    'relax face sides',
                    'relax face angles',
                    'relax correct flipped faces',
                    'relax straight edges',
                ]:
                options[key] = False

        def add_option_checkbox():
            # opt_mask_boundary   = options['relax mask boundary']
            # opt_mask_symmetry   = options['relax mask symmetry']
            # opt_mask_hidden     = options['relax mask hidden']
            # opt_mask_selected   = options['relax mask selected']

            # opt_steps           = options['relax steps']
            # opt_mult            = options['relax force multiplier']

            # opt_correct_flipped = options['relax correct flipped faces']
            # opt_edge_length     = options['relax edge length']
            # opt_face_radius     = options['relax face radius']
            # opt_face_sides      = options['relax face sides']
            # opt_face_angles     = options['relax face angles']
            pass

        def assign_preset_to_current(n):
            options[f'relax preset {n} radius']   = options['relax radius']
            options[f'relax preset {n} strength'] = options['relax strength']
            options[f'relax preset {n} falloff']  = options['relax falloff']
        def update_preset_name(n):
            nonlocal relax_options
            ui = f'relax-preset-{n}'
            name = options[f'relax preset {n} name']
            relax_options.getElementById(ui).innerText = f'Preset: {name}'

        relax_options = ui.details(children=[
            ui.summary(innerText='Relax'),
            # ui.collection('Algorithm', children=[
            #     ui.labeled_input_radio(
            #         title='Relax algorithm uses 3D position of vertices in world.  Works in general, but can be unstable',
            #         value='3D',
            #         checked=(options['relax algorithm']=='3D'),
            #         name='relax-algorithm',
            #         classes='half-size',
            #         children=[ui.label(innerText='3D')],
            #         on_input=relax_algorithm_selected_change,
            #     ),
            #     ui.labeled_input_radio(
            #         title='Relax algorithm uses 2D position of vertices in screen space.  Only works on visible, but can be more stable',
            #         value='2D',
            #         checked=(options['relax algorithm']=='2D'),
            #         name='relax-algorithm',
            #         classes='half-size',
            #         children=[ui.label(innerText='2D')],
            #         on_input=relax_algorithm_selected_change,
            #         disabled=True,
            #     ),
            # ]),
            ui.div(classes='collection', id='relax-masking', children=[
                ui.h1(innerText='Masking Options'),
                ui.div(classes='collection', children=[
                    ui.h1(innerText='Boundary'),
                    ui.label(
                        innerText='Exclude',
                        title='Relax vertices not along boundary',
                        classes='half-size',
                        children=[
                            ui.input_radio(
                                title='Relax vertices not along boundary',
                                value='exclude',
                                checked=(options['relax mask boundary']=='exclude'),
                                name='relax-boundary',
                                on_input=relax_mask_boundary_change,
                            ),
                        ],
                    ),
                    ui.label(
                        innerText='Include',
                        title='Relax all vertices within brush, regardless of being along boundary',
                        classes='half-size',
                        children=[
                            ui.input_radio(
                                title='Relax all vertices within brush, regardless of being along boundary',
                                value='include',
                                checked=(options['relax mask boundary']=='include'),
                                name='relax-boundary',
                                on_input=relax_mask_boundary_change,
                            ),
                        ],
                    ),
                ]),
                ui.div(classes='collection', children=[
                    ui.h1(innerText='Symmetry'),
                    ui.label(
                        innerText='Exclude',
                        title='Relax vertices not along symmetry plane',
                        classes='third-size',
                        children=[
                            ui.input_radio(
                                title='Relax vertices not along symmetry plane',
                                value='exclude',
                                checked=(options['relax mask symmetry']=='exclude'),
                                name='relax-symmetry',
                                on_input=relax_mask_symmetry_change,
                            ),
                        ],
                    ),
                    ui.label(
                        innerText='Maintain',
                        title='Relax vertices along symmetry plane, but keep them on symmetry plane',
                        classes='third-size',
                        children=[
                            ui.input_radio(
                                title='Relax vertices along symmetry plane, but keep them on symmetry plane',
                                value='maintain',
                                checked=(options['relax mask symmetry']=='maintain'),
                                name='relax-symmetry',
                                on_input=relax_mask_symmetry_change,
                            ),
                        ],
                    ),
                    ui.label(
                        innerText='Include',
                        title='Relax all vertices within brush, regardless of being along symmetry plane',
                        classes='third-size',
                        children=[
                            ui.input_radio(
                                title='Relax all vertices within brush, regardless of being along symmetry plane',
                                value='include',
                                checked=(options['relax mask symmetry']=='include'),
                                name='relax-symmetry',
                                on_input=relax_mask_symmetry_change,
                            ),
                        ],
                    ),
                ]),
                ui.div(classes='collection', children=[
                    ui.h1(innerText='Hidden'),
                    ui.label(
                        innerText='Exclude',
                        title='Relax only visible vertices',
                        classes='half-size',
                        children=[
                            ui.input_radio(
                                title='Relax only visible vertices',
                                value='exclude',
                                checked=(options['relax mask hidden']=='exclude'),
                                name='relax-hidden',
                                on_input=relax_mask_hidden_change,
                            ),
                        ],
                    ),
                    ui.label(
                        innerText='Include',
                        title='Relax all vertices within brush, regardless of visibility',
                        classes='half-size',
                        children=[
                            ui.input_radio(
                                title='Relax all vertices within brush, regardless of visibility',
                                value='include',
                                checked=(options['relax mask hidden']=='include'),
                                name='relax-hidden',
                                on_input=relax_mask_hidden_change,
                            ),
                        ],
                    ),
                ]),
                ui.div(classes='collection', children=[
                    ui.h1(innerText='Selected'),
                    ui.label(
                        innerText='Exclude',
                        title='Relax only unselected vertices',
                        classes='third-size',
                        children=[
                            ui.input_radio(
                                title='Relax only unselected vertices',
                                value='exclude',
                                checked=(options['relax mask selected']=='exclude'),
                                name='relax-selected',
                                on_input=relax_mask_selected_change,
                            ),
                        ],
                    ),
                    ui.label(
                        innerText='Only',
                        title='Relax only selected vertices',
                        classes='third-size',
                        children=[
                            ui.input_radio(
                                title='Relax only selected vertices',
                                value='only',
                                checked=(options['relax mask selected']=='only'),
                                name='relax-selected',
                                on_input=relax_mask_selected_change,
                            ),
                        ],
                    ),
                    ui.label(
                        innerText='All',
                        title='Relax all vertices within brush, regardless of selection',
                        classes='third-size',
                        children=[
                            ui.input_radio(
                                title='Relax all vertices within brush, regardless of selection',
                                value='all',
                                checked=(options['relax mask selected']=='all'),
                                name='relax-selected',
                                on_input=relax_mask_selected_change,
                            ),
                        ],
                    ),
                ]),
            ]),
            ui.details(id='relax-alg-options', children=[
                ui.summary(innerText='Algorithm Options'),
                ui.div(classes='collection', children=[
                    ui.h1(innerText='Iterations'),
                    ui.labeled_input_text(
                        label='Steps',
                        title='Number of times to iterate',
                        value=BoundInt('''options['relax steps']''', min_value=1, max_value=10),
                    ),
                    ui.labeled_input_text(
                        label='Strength',
                        title='Strength multiplier for each iteration',
                        value=BoundFloat('''options['relax force multiplier']''', min_value=0.1, max_value=10.0),
                    ),
                ]),
                ui.div(classes='collection', children=[
                    ui.h1(innerText='Edge'),
                    ui.input_checkbox(
                        label='Average edge length',
                        title='Squash / stretch each edge toward the average edge length',
                        checked=BoundBool('''options['relax edge length']'''),
                        style='display:block; width:100%',
                    ),
                    ui.input_checkbox(
                        label='Straighten edges',
                        title='Try to straighten edges',
                        checked=BoundBool('''options['relax straight edges']'''),
                        style='display:block; width:100%',
                    ),
                ]),
                ui.div(classes='collection', children=[
                    ui.h1(innerText='Face'),
                    ui.input_checkbox(
                        label='Face radius',
                        title='Move face vertices so their distance to face center is equalized',
                        checked=BoundBool('''options['relax face radius']'''),
                        style='display:block; width:100%',
                    ),
                    ui.input_checkbox(
                        label='Average face edge length',
                        title='Squash / stretch face edges so lengths are equal in length (WARNING: can cause faces to flip)',
                        checked=BoundBool('''options['relax face sides']'''),
                        style='display:block; width:100%',
                    ),
                    ui.input_checkbox(
                        label='Face angles',
                        title='Move face vertices so they are equally spread around face center',
                        checked=BoundBool('''options['relax face angles']'''),
                        style='display:block; width:100%',
                    ),
                ]),
                ui.div(classes='collection', children=[
                    ui.h1(innerText='Experimental'),
                    ui.input_checkbox(
                        label='Correct flipped faces',
                        title='Try to move vertices so faces are not flipped',
                        checked=BoundBool('''options['relax correct flipped faces']'''),
                        style='display:block; width:100%',
                    ),
                ]),
                ui.div(classes='collection', children=[
                    ui.h1(innerText='Presets'),
                    ui.button(
                        label='Reset',
                        title='Reset Algorithm options to default values',
                        on_mouseclick=reset_algorithm_options,
                    ),
                    ui.button(
                        label='Disable All',
                        title='Disable all Algorithm options',
                        on_mouseclick=disable_all_options,
                    ),
                ]),
            ]),
            ui.details(children=[
                ui.summary(innerText='Brush Options'),
                ui.div(classes='collection', children=[
                    ui.h1(innerText='Current'),
                    ui.labeled_input_text(label='Size',     title='Adjust brush size',     value=self.rfwidget.get_radius_boundvar()),
                    ui.labeled_input_text(label='Strength', title='Adjust brush strength', value=self.rfwidget.get_strength_boundvar()),
                    ui.labeled_input_text(label='Falloff',  title='Adjust brush falloff',  value=self.rfwidget.get_falloff_boundvar()),
                    ui.button(label='Reset', title='Reset brush options to defaults', on_mouseclick=delay_exec('''options.reset(keys={"relax radius","relax falloff","relax strength"})''')),
                ]),
                ui.details(children=[
                    ui.summary(innerText='Preset: Preset 1', id='relax-preset-1'),
                    ui.labeled_input_text(label='Name',      title='Adjust name of preset 1',            id='relax-preset-1-name',     value=BoundString('''options['relax preset 1 name']''',    on_change=delay_exec('''update_preset_name(1)'''))),
                    ui.labeled_input_text(label='Size',      title='Adjust brush size for preset 1',     id='relax-preset-1-size',     value=BoundFloat('''options['relax preset 1 radius']''',   min_value=1.0)),
                    ui.labeled_input_text(label='Strength',  title='Adjust brush strength for preset 1', id='relax-preset-1-strength', value=BoundFloat('''options['relax preset 1 strength']''', min_value=0.01, max_value=1.0)),
                    ui.labeled_input_text(label='Falloff',   title='Adjust brush falloff for preset 1',  id='relax-preset-1-falloff',  value=BoundFloat('''options['relax preset 1 falloff']''',  min_value=0.0,  max_value=100.0)),
                    ui.button(label='Current to Preset',     title='Assign preset 1 setting to current brush settings', on_mouseclick=delay_exec('''assign_preset_to_current(1)'''))
                ]),
                ui.details(children=[
                    ui.summary(innerText='Preset: Preset 2', id='relax-preset-2'),
                    ui.labeled_input_text(label='Name',      title='Adjust name of preset 2',            id='relax-preset-2-name',     value=BoundString('''options['relax preset 2 name']''',    on_change=delay_exec('''update_preset_name(2)'''))),
                    ui.labeled_input_text(label='Size',      title='Adjust brush size for preset 2',     id='relax-preset-2-size',     value=BoundFloat('''options['relax preset 2 radius']''',   min_value=1.0)),
                    ui.labeled_input_text(label='Strength',  title='Adjust brush strength for preset 2', id='relax-preset-2-strength', value=BoundFloat('''options['relax preset 2 strength']''', min_value=0.01, max_value=1.0)),
                    ui.labeled_input_text(label='Falloff',   title='Adjust brush falloff for preset 2',  id='relax-preset-2-falloff',  value=BoundFloat('''options['relax preset 2 falloff']''',  min_value=0.0,  max_value=100.0)),
                    ui.button(label='Current to Preset',     title='Assign preset 2 setting to current brush settings', on_mouseclick=delay_exec('''assign_preset_to_current(2)'''))
                ]),
                ui.details(children=[
                    ui.summary(innerText='Preset: Preset 3', id='relax-preset-3'),
                    ui.labeled_input_text(label='Name',      title='Adjust name of preset 3',            id='relax-preset-3-name',     value=BoundString('''options['relax preset 3 name']''',    on_change=delay_exec('''update_preset_name(3)'''))),
                    ui.labeled_input_text(label='Size',      title='Adjust brush size for preset 3',     id='relax-preset-3-size',     value=BoundFloat('''options['relax preset 3 radius']''',   min_value=1.0)),
                    ui.labeled_input_text(label='Strength',  title='Adjust brush strength for preset 3', id='relax-preset-3-strength', value=BoundFloat('''options['relax preset 3 strength']''', min_value=0.01, max_value=1.0)),
                    ui.labeled_input_text(label='Falloff',   title='Adjust brush falloff for preset 3',  id='relax-preset-3-falloff',  value=BoundFloat('''options['relax preset 3 falloff']''',  min_value=0.0,  max_value=100.0)),
                    ui.button(label='Current to Preset',     title='Assign preset 3 setting to current brush settings', on_mouseclick=delay_exec('''assign_preset_to_current(3)'''))
                ]),
                ui.details(children=[
                    ui.summary(innerText='Preset: Preset 4', id='relax-preset-4'),
                    ui.labeled_input_text(label='Name',      title='Adjust name of preset 4',            id='relax-preset-4-name',     value=BoundString('''options['relax preset 4 name']''',    on_change=delay_exec('''update_preset_name(4)'''))),
                    ui.labeled_input_text(label='Size',      title='Adjust brush size for preset 4',     id='relax-preset-3-size',     value=BoundFloat('''options['relax preset 4 radius']''',   min_value=1.0)),
                    ui.labeled_input_text(label='Strength',  title='Adjust brush strength for preset 4', id='relax-preset-3-strength', value=BoundFloat('''options['relax preset 4 strength']''', min_value=0.01, max_value=1.0)),
                    ui.labeled_input_text(label='Falloff',   title='Adjust brush falloff for preset 4',  id='relax-preset-3-falloff',  value=BoundFloat('''options['relax preset 4 falloff']''',  min_value=0.0,  max_value=100.0)),
                    ui.button(label='Current to Preset',     title='Assign preset 4 setting to current brush settings', on_mouseclick=delay_exec('''assign_preset_to_current(4)'''))
                ]),
            ]),
        ])
        update_preset_name(1)
        update_preset_name(2)
        update_preset_name(3)
        update_preset_name(4)
        return relax_options

    @RFTool_Relax.on_reset
    def reset(self):
        self.sel_only = False

    @RFTool_Relax.FSM_State('main')
    def main(self) :
        if self.rfcontext.actions.pressed(['brush', 'brush alt'], unpress=False):
            self.sel_only = self.rfcontext.actions.using('brush alt')
            self.rfcontext.actions.unpress()
            self.rfcontext.undo_push('relax')
            return 'relax'

        if self.rfcontext.actions.pressed('pie menu alt0', unpress=False):
            def callback(option):
                if option is None: return
                options['relax radius']   = options[f'relax preset {option} radius']
                options['relax strength'] = options[f'relax preset {option} strength']
                options['relax falloff']  = options[f'relax preset {option} falloff']
            self.rfcontext.show_pie_menu([
                (f'Preset: {options["relax preset 1 name"]}', 1),
                (f'Preset: {options["relax preset 2 name"]}', 2),
                (f'Preset: {options["relax preset 3 name"]}', 3),
                (f'Preset: {options["relax preset 4 name"]}', 4),
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

    # @RFTool_Relax.FSM_State('selectadd/deselect')
    # def selectadd_deselect(self):
    #     if not self.rfcontext.actions.using(['select single','select single add']):
    #         self.rfcontext.undo_push('deselect')
    #         face,_ = self.rfcontext.accel_nearest2D_face()
    #         if face and face.select: self.rfcontext.deselect(face)
    #         return 'main'
    #     delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
    #     if delta.length > self.drawing.scale(5):
    #         self.rfcontext.undo_push('select add')
    #         return 'select'

    # @RFTool_Relax.FSM_State('select')
    # def select(self):
    #     if not self.rfcontext.actions.using(['select single','select single add']):
    #         return 'main'
    #     bmf,_ = self.rfcontext.accel_nearest2D_face(max_dist=10)
    #     if not bmf or bmf.select: return
    #     self.rfcontext.select(bmf, supparts=False, only=False)

    @RFTool_Relax.FSM_State('relax', 'enter')
    def relax_enter(self):
        self._time = time.time()
        self._timer = self.actions.start_timer(120)

        opt_mask_boundary   = options['relax mask boundary']
        opt_mask_symmetry   = options['relax mask symmetry']
        opt_mask_hidden     = options['relax mask hidden']
        opt_mask_selected   = options['relax mask selected']
        opt_steps           = options['relax steps']
        opt_edge_length     = options['relax edge length']
        opt_face_radius     = options['relax face radius']
        opt_face_sides      = options['relax face sides']
        opt_face_angles     = options['relax face angles']
        opt_correct_flipped = options['relax correct flipped faces']
        opt_straight_edges  = options['relax straight edges']
        opt_mult            = options['relax force multiplier']
        is_visible = lambda bmv: self.rfcontext.is_visible(bmv.co, bmv.normal)

        self._bmverts = []
        for bmv in self.rfcontext.iter_verts():
            if self.sel_only and not bmv.select: continue
            if opt_mask_boundary == 'exclude' and bmv.is_on_boundary(): continue
            if opt_mask_symmetry == 'exclude' and bmv.is_on_symmetry_plane(): continue
            if opt_mask_hidden   == 'exclude' and not is_visible(bmv): continue
            if opt_mask_selected == 'exclude' and bmv.select: continue
            if opt_mask_selected == 'only' and not bmv.select: continue
            self._bmverts.append(bmv)
        print(f'Relaxing max of {len(self._bmverts)} bmverts')

    @RFTool_Relax.FSM_State('relax', 'exit')
    def relax_exit(self):
        self.rfcontext.update_verts_faces(self._bmverts)
        self._timer.done()

    @RFTool_Relax.FSM_State('relax')
    @RFTool.dirty_when_done
    def relax(self):
        st = time.time()

        if self.rfcontext.actions.released(['brush','brush alt']):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        if not self.rfcontext.actions.timer: return

        hit_pos = self.rfcontext.actions.hit_pos
        if not hit_pos: return

        # collect data for smoothing
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_point(hit_pos, radius, bmverts=self._bmverts)
        verts,edges,faces,vert_strength = set(),set(),set(),dict()
        for bmv,d in nearest:
            verts.add(bmv)
            edges.update(bmv.link_edges)
            faces.update(bmv.link_faces)
            vert_strength[bmv] = self.rfwidget.get_strength_dist(d) / radius
        # self.rfcontext.select(verts)

        if not verts or not edges: return
        vert_strength = vert_strength or {}

        # gather options
        # opt_mask_boundary   = options['relax mask boundary']
        opt_mask_symmetry   = options['relax mask symmetry']
        # opt_mask_hidden     = options['relax mask hidden']
        # opt_mask_selected   = options['relax mask selected']
        opt_steps           = options['relax steps']
        opt_edge_length     = options['relax edge length']
        opt_face_radius     = options['relax face radius']
        opt_face_sides      = options['relax face sides']
        opt_face_angles     = options['relax face angles']
        opt_correct_flipped = options['relax correct flipped faces']
        opt_straight_edges  = options['relax straight edges']
        opt_mult            = options['relax force multiplier']

        is_visible = lambda bmv: self.rfcontext.is_visible(bmv.co, bmv.normal)

        cur_time = time.time()
        time_delta = cur_time - self._time
        self._time = cur_time
        strength = (5.0 / opt_steps) * self.rfwidget.strength * time_delta
        radius = self.rfwidget.get_scaled_radius()

        # capture all verts involved in relaxing
        chk_verts = set(verts)
        chk_verts.update(self.rfcontext.get_edges_verts(edges))
        chk_verts.update(self.rfcontext.get_faces_verts(faces))
        chk_edges = self.rfcontext.get_verts_link_edges(chk_verts)
        chk_faces = self.rfcontext.get_verts_link_faces(chk_verts)

        displace = {}
        def reset_forces():
            nonlocal displace
            displace.clear()
        def add_force(bmv, f):
            nonlocal displace, verts, vert_strength
            if bmv not in verts or bmv not in vert_strength: return
            cur = displace[bmv] if bmv in displace else Vec((0,0,0))
            displace[bmv] = cur + f

        def relax_2d():
            pass

        def relax_3d():
            reset_forces()

            # compute average edge length
            avg_edge_len = sum(bme.calc_length() for bme in edges) / len(edges)

            # push edges closer to average edge length
            if opt_edge_length:
                for bme in chk_edges:
                    if bme not in edges: continue
                    bmv0,bmv1 = bme.verts
                    vec = bme.vector()
                    edge_len = vec.length
                    f = vec * (0.1 * (avg_edge_len - edge_len) * strength) #/ edge_len
                    add_force(bmv0, -f)
                    add_force(bmv1, +f)

            # push verts if neighboring faces seem flipped (still WiP!)
            if opt_correct_flipped:
                bmf_flipped = { bmf for bmf in chk_faces if bmf.is_flipped() }
                for bmf in bmf_flipped:
                    # find a non-flipped neighboring face
                    for bme in bmf.edges:
                        bmfs = set(bme.link_faces)
                        bmfs.discard(bmf)
                        if len(bmfs) != 1: continue
                        bmf_other = next(iter(bmfs))
                        if bmf_other not in chk_faces: continue
                        if bmf_other in bmf_flipped: continue
                        # pull edge toward bmf_other center
                        bmf_other_center = bmf_other.center()
                        bme_center = bme.calc_center()
                        vec = bmf_other_center - bme_center
                        bmv0,bmv1 = bme.verts
                        add_force(bmv0, vec * strength * 5)
                        add_force(bmv1, vec * strength * 5)

            # push verts to straighten edges (still WiP!)
            if opt_straight_edges:
                for bmv in chk_verts:
                    if bmv.is_boundary: continue
                    bmes = bmv.link_edges
                    #if len(bmes) != 4: continue
                    center = Point.average(bme.other_vert(bmv).co for bme in bmes)
                    add_force(bmv, (center - bmv.co) * 0.1)

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
                        f = rel * ((avg_rel_len - rel_len) * strength * 2) #/ rel_len
                        add_force(bmv, f)

                # push verts toward equal edge lengths
                if opt_face_sides:
                    avg_face_edge_len = sum(bme.length for bme in bmf.edges) / cnt
                    for bme in bmf.edges:
                        bmv0, bmv1 = bme.verts
                        vec = bme.vector()
                        edge_len = vec.length
                        f = vec * ((avg_face_edge_len - edge_len) * strength) / edge_len
                        add_force(bmv0, f * -0.5)
                        add_force(bmv1, f * 0.5)

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
                        add_force(bmv0, fvec0 * -f_mag)
                        add_force(bmv1, fvec1 * -f_mag)

        # perform smoothing
        for step in range(opt_steps):
            if options['relax algorithm'] == '3D':
                relax_3d()
            elif options['relax algorithm'] == '2D':
                relax_2d()

            # update
            for bmv in displace:
                co = bmv.co + displace[bmv] * (opt_mult * vert_strength[bmv])
                if opt_mask_symmetry == 'maintain' and bmv.is_on_symmetry_plane():
                    snap_to_symmetry = self.rfcontext.symmetry_planes_for_point(bmv.co)
                    co = self.rfcontext.snap_to_symmetry(co, snap_to_symmetry)
                bmv.co = co
                self.rfcontext.snap_vert(bmv)
            self.rfcontext.update_verts_faces(displace)
        # print(f'relaxed {len(verts)} ({len(chk_verts)}) in {time.time() - st} with {strength}')
