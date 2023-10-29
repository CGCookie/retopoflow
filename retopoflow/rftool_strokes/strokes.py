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

import math
import time
import bpy
from math import isnan

from contextlib import contextmanager

from mathutils import Vector, Matrix
from mathutils.geometry import intersect_point_tri_2d

from ..rftool import RFTool
from ..rfwidget import RFWidget
from ..rfwidgets.rfwidget_default     import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_brushstroke import RFWidget_BrushStroke_Factory
from ..rfwidgets.rfwidget_hidden      import RFWidget_Hidden_Factory

from ...addon_common.common import gpustate
from ...addon_common.common.debug import dprint
from ...addon_common.common.fsm import FSM
from ...addon_common.common.globals import Globals
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import (
    Point, Vec, Direction,
    Point2D, Vec2D,
    clamp, mid,
)
from ...addon_common.common.bezier import CubicBezierSpline, CubicBezier
from ...addon_common.common.utils import iter_pairs, iter_running_sum, min_index, max_index, has_duplicates
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat
from ...addon_common.common.drawing import DrawCallbacks
from ...addon_common.common.timerhandler import StopwatchHandler
from ...addon_common.terminal.term_printer import sprint
from ...config.options import options, themes

from .strokes_insert import Strokes_Insert
from .strokes_utils import (
    process_stroke_filter, process_stroke_source,
    find_edge_cycles,
    find_edge_strips, get_strip_verts,
    restroke, walk_to_corner,
)


class Strokes(RFTool, Strokes_Insert):
    name        = 'Strokes'
    description = 'Insert edge strips and extrude edges into a patch'
    icon        = 'strokes-icon.png'
    help        = 'strokes.md'
    shortcut    = 'strokes tool'
    statusbar   = '{{insert}} Insert edge strip and bridge\t{{increase count}} Increase segments\t{{decrease count}} Decrease segments'
    ui_config   = 'strokes_options.html'

    RFWidget_Default     = RFWidget_Default_Factory.create()
    RFWidget_Move        = RFWidget_Default_Factory.create(cursor='HAND')
    RFWidget_Hidden      = RFWidget_Hidden_Factory.create()
    RFWidget_BrushStroke = RFWidget_BrushStroke_Factory.create(
        'Strokes stroke',
        BoundInt('''options['strokes radius']''', min_value=1),
        outer_border_color=themes['strokes'],
    )

    def _fsm_in_main(self):
        # needed so main actions using Ctrl (ex: undo, redo, save) can still work
        return self._fsm.state in {'main', 'previs insert'}


    @property
    def cross_count(self):
        return self.strip_crosses or 0
    @cross_count.setter
    def cross_count(self, v):
        if self.strip_crosses == v: return
        if self.replay is None: return
        if self.strip_crosses is None: return
        self.strip_crosses = v
        if self.strip_crosses is not None: self.replay()

    @property
    def loop_count(self):
        return self.strip_loops or 0
    @loop_count.setter
    def loop_count(self, v):
        if self.strip_loops == v: return
        if self.replay is None: return
        if self.strip_loops is None: return
        self.strip_loops = v
        if self.strip_loops is not None: self.replay()

    @RFTool.on_init
    def init(self):
        self.rfwidgets = {
            'default': self.RFWidget_Default(self),
            'brush':   self.RFWidget_BrushStroke(self),
            'hover':   self.RFWidget_Move(self),
            'hidden':  self.RFWidget_Hidden(self),
        }
        self.rfwidget = None
        self.strip_crosses = None
        self.strip_loops = None
        self._var_fixed_span_count = BoundInt('''options['strokes span count']''', min_value=1, max_value=128)
        self._var_cross_count = BoundInt('''self.cross_count''', min_value=1, max_value=500)
        self._var_loop_count  = BoundInt('''self.loop_count''', min_value=1, max_value=500)


    def update_span_mode(self):
        mode = options['strokes span insert mode']
        self.ui_summary.innerText = f'Strokes: {mode}'
        self.ui_insert.dirty(cause='insert mode change', children=True)

    @RFTool.on_ui_setup
    def ui(self):
        ui_options = self.document.body.getElementById('strokes-options')
        self.ui_summary = ui_options.getElementById('strokes-summary')
        self.ui_insert = ui_options.getElementById('strokes-insert-modes')
        self.ui_radius = ui_options.getElementById('strokes-radius')
        def dirty_radius():
            self.ui_radius.dirty(cause='radius changed')
        self.rfwidgets['brush'].get_radius_boundvar().on_change(dirty_radius)
        self.update_span_mode()

    @RFTool.on_reset
    def reset(self):
        self.replay = None
        self.strip_crosses = None
        self.strip_loops = None
        self.strip_edges = False
        self.just_created = False
        self.defer_recomputing = False
        self.hovering_sel_edge = None
        self.connection_pre_last_mouse = None
        self.connection_pre = None
        self.connection_post = None
        self.update_hover_edge()
        self.update_ui()

    def update_ui(self):
        if self.replay is None:
            self._var_cross_count.disabled = True
            self._var_loop_count.disabled = True
        else:
            self._var_cross_count.disabled = self.strip_crosses is None or self.strip_edges
            self._var_loop_count.disabled = self.strip_loops is None

    @RFTool.on_target_change
    def update_target(self):
        if self.defer_recomputing: return
        if not self.just_created: self.reset()
        else: self.just_created = False

    @RFTool.on_target_change
    @RFTool.on_view_change
    def update(self):
        if self.defer_recomputing: return

        self.update_ui()

        self.edge_collections = []
        edges = self.get_edges_for_extrude()
        while edges:
            current = set()
            working = set([edges.pop()])
            while working:
                e = working.pop()
                if e in current: continue
                current.add(e)
                edges.discard(e)
                v0,v1 = e.verts
                working |= {e for e in (v0.link_edges + v1.link_edges) if e in edges}
            verts = {v for e in current for v in e.verts}
            self.edge_collections.append({
                'verts': verts,
                'edges': current,
                'center': Point.average(v.co for v in verts),
            })


    @DrawCallbacks.on_draw('post2d')
    def draw_postpixel_counts(self):
        gpustate.blend('ALPHA')
        point_to_point2d = self.rfcontext.Point_to_Point2D
        text_draw2D = self.rfcontext.drawing.text_draw2D
        self.rfcontext.drawing.set_font_size(12)

        for collection in self.edge_collections:
            lv = len(collection['verts'])
            le = len(collection['edges'])
            c = collection['center']
            xy = point_to_point2d(c)
            if not xy: continue
            xy.y += 10
            t = f'V:{lv}, E:{le}'
            if self.strip_crosses: t += f'\nSpan: {self.strip_crosses}'
            if self.strip_loops:   t += f'\nLoop: {self.strip_loops}'
            text_draw2D(t, xy, color=(1,1,0,1), dropshadow=(0,0,0,0.5))


    def filter_edge_selection(self, bme):
        return bme.select or len(bme.link_faces) < 2

    @RFTool.on_events('reset', 'target change', 'view change', 'mouse move')
    @RFTool.once_per_frame
    @FSM.onlyinstate('main')
    def update_hover_edge(self):
        self.hovering_sel_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'], selected_only=True)


    @FSM.on_state('main', 'enter')
    def modal_main_enter(self):
        self.connection_post = None
        self.update_hover_edge()

    @FSM.on_state('main')
    def modal_main(self):
        if self.actions.using_onlymods('insert'):
            return 'previs insert'

        if self.hovering_sel_edge:
            self.set_widget('hover')
        else:
            self.set_widget('default')


        if self.handle_inactive_passthrough(): return

        if self.rfcontext.actions.pressed('pie menu alt0'):
            def callback(option):
                if not option: return
                options['strokes span insert mode'] = option
                self.update_span_mode()
            self.rfcontext.show_pie_menu([
                'Brush Size',
                'Fixed',
            ], callback, highlighted=options['strokes span insert mode'])
            return

        if self.hovering_sel_edge and self.actions.pressed('action'):
            self.move_done_pressed = None
            self.move_done_released = 'action'
            self.move_cancelled = 'cancel'
            return 'move'

        if self.actions.pressed({'select path add'}):
            return self.rfcontext.select_path(
                {'edge'},
                fn_filter_bmelem=self.filter_edge_selection,
                kwargs_select={'supparts': False},
            )

        if self.actions.pressed({'select paint', 'select paint add'}, unpress=False):
            sel_only = self.actions.pressed('select paint')
            self.actions.unpress()
            return self.rfcontext.setup_smart_selection_painting(
                {'edge'},
                use_select_tool=True,
                selecting=not sel_only,
                deselect_all=sel_only,
                kwargs_select={'supparts': False},
                kwargs_deselect={'subparts': False},
            )

        if self.actions.pressed({'select single', 'select single add'}, unpress=False):
            sel_only = self.actions.pressed('select single')
            self.actions.unpress()
            bme,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['select dist'])
            if not sel_only and not bme: return
            self.rfcontext.undo_push('select')
            if sel_only: self.rfcontext.deselect_all()
            if not bme: return
            if bme.select: self.rfcontext.deselect(bme, subparts=False)
            else:          self.rfcontext.select(bme, supparts=False, only=sel_only)
            return


        if self.rfcontext.actions.pressed({'select smart', 'select smart add'}, unpress=False):
            sel_only = self.rfcontext.actions.pressed('select smart')
            self.rfcontext.actions.unpress()

            self.rfcontext.undo_push('select smart')
            selectable_edges = [e for e in self.rfcontext.visible_edges() if len(e.link_faces) < 2]
            edge,_ = self.rfcontext.nearest2D_edge(edges=selectable_edges, max_dist=10)
            if not edge: return
            #self.rfcontext.select_inner_edge_loop(edge, supparts=False, only=sel_only)
            self.rfcontext.select_edge_loop(edge, supparts=False, only=sel_only)

        if self.rfcontext.actions.pressed('grab'):
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move'

        if self.rfcontext.actions.pressed('increase count') and self.replay:
            # print('increase count')
            if self.strip_crosses is not None and not self.strip_edges:
                self.strip_crosses += 1
                self.replay()
            elif self.strip_loops is not None:
                self.strip_loops += 1
                self.replay()

        if self.rfcontext.actions.pressed('decrease count') and self.replay:
            # print('decrease count')
            if self.strip_crosses is not None and self.strip_crosses > 1 and not self.strip_edges:
                self.strip_crosses -= 1
                self.replay()
            elif self.strip_loops is not None and self.strip_loops > 1:
                self.strip_loops -= 1
                self.replay()

    def mergeSnapped(self):
        """ Merging colocated visible verts """

        if not options['strokes automerge']: return

        # TODO: remove colocated faces
        if self.mousedown is None: return
        delta = Vec2D(self.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        update_verts = []
        merge_dist = self.rfcontext.drawing.scale(options['strokes merge dist'])
        for bmv,xy in self.bmverts:
            if not xy: continue
            xy_updated = xy + delta
            for bmv1,xy1 in self.vis_bmverts:
                if not xy1: continue
                if bmv1 == bmv: continue
                if not bmv1.is_valid: continue
                d = (xy_updated - xy1).length
                if (xy_updated - xy1).length > merge_dist:
                    continue
                bmv1.merge_robust(bmv)
                self.rfcontext.select(bmv1)
                update_verts += [bmv1]
                break
        if update_verts:
            self.rfcontext.update_verts_faces(update_verts)
            #self.set_next_state()

    @FSM.on_state('move', 'enter')
    def move_enter(self):
        self.rfcontext.undo_push('move grabbed')

        self.move_opts = {
            'vis_accel': self.rfcontext.get_custom_vis_accel(
                selection_only=False,
                include_edges=False,
                include_faces=False,
                symmetry=False,
            ),
        }

        sel_verts = self.rfcontext.get_selected_verts()
        vis_accel = self.rfcontext.get_accel_visible()
        vis_verts = self.rfcontext.accel_vis_verts
        Point_to_Point2D = self.rfcontext.Point_to_Point2D

        bmverts = [(bmv, Point_to_Point2D(bmv.co)) for bmv in sel_verts]
        self.bmverts = [(bmv, co) for (bmv, co) in bmverts if co]
        self.vis_bmverts = [(bmv, Point_to_Point2D(bmv.co)) for bmv in vis_verts if bmv.is_valid and bmv not in sel_verts]
        self.mousedown = self.rfcontext.actions.mouse
        self.defer_recomputing = True
        self.rfcontext.split_target_visualization_selected()
        self.rfcontext.set_accel_defer(True)
        self._timer = self.actions.start_timer(120)

        if options['hide cursor on tweak']: self.set_widget('hidden')

    @FSM.on_state('move')
    @RFTool.dirty_when_done
    def move(self):
        released = self.rfcontext.actions.released
        if self.actions.pressed(self.move_done_pressed):
            self.defer_recomputing = False
            self.mergeSnapped()
            return 'main'
        if self.actions.released(self.move_done_released):
            self.defer_recomputing = False
            self.mergeSnapped()
            return 'main'
        if self.actions.pressed('cancel'):
            self.defer_recomputing = False
            self.actions.unuse(self.move_done_released, ignoremods=True, ignoremulti=True)
            self.rfcontext.undo_cancel()
            return 'main'

        # only update verts on timer events and when mouse has moved
        #if not self.rfcontext.actions.timer: return
        #if self.actions.mouse_prev == self.actions.mouse: return
        if not self.actions.mousemove_stop: return

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            xy_updated = xy + delta
            # check if xy_updated is "close" to any visible verts (in image plane)
            # if so, snap xy_updated to vert position (in image plane)
            if options['polypen automerge']:
                bmv1,d = self.rfcontext.accel_nearest2D_vert(point=xy_updated, vis_accel=self.move_opts['vis_accel'], max_dist=options['strokes merge dist'])
                if bmv1 is None:
                    set2D_vert(bmv, xy_updated)
                    continue
                xy1 = self.rfcontext.Point_to_Point2D(bmv1.co)
                if not xy1:
                    set2D_vert(bmv, xy_updated)
                    continue
                set2D_vert(bmv, xy1)
            else:
                set2D_vert(bmv, xy_updated)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)

    @FSM.on_state('move', 'exit')
    def move_exit(self):
        self._timer.done()
        self.rfcontext.set_accel_defer(False)
        self.rfcontext.clear_split_target_visualization()

