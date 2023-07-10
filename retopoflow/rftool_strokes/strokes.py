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
    Accel2D,
    clamp, mid,
)
from ...addon_common.common.bezier import CubicBezierSpline, CubicBezier
from ...addon_common.common.utils import iter_pairs, iter_running_sum, min_index, max_index, has_duplicates
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat
from ...addon_common.common.drawing import DrawCallbacks
from ...addon_common.common.timerhandler import StopwatchHandler
from ...addon_common.terminal.term_printer import sprint
from ...config.options import options, themes

from .strokes_utils import (
    process_stroke_filter, process_stroke_source,
    find_edge_cycles,
    find_edge_strips, get_strip_verts,
    restroke, walk_to_corner,
)


class Strokes(RFTool):
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
        self.stopwatch_hover_edge     = StopwatchHandler(self.update_hover_edge,     time_delay=0.125)
        self.stopwatch_connection_pre = StopwatchHandler(self.update_connection_pre, time_delay=0.125)

    @contextmanager
    def defer_recomputing_while(self):
        try:
            self.defer_recomputing = True
            yield
        finally:
            self.defer_recomputing = False
            self.update()

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
        sprint(f'Strokes Reset')
        self.replay = None
        self.strip_crosses = None
        self.strip_loops = None
        self.strip_edges = False
        self.just_created = False
        self.defer_recomputing = False
        self.hovering_edge = None
        self.hovering_sel_edge = None
        self.connection_pre_last_mouse = None
        self.connection_pre = None
        self.connection_post = None
        self.update_hover_edge()
        self.update_connection_pre()
        self.update_ui()

    def update_ui(self):
        sprint(f'Strokes Update UI')
        if self.replay is None:
            self._var_cross_count.disabled = True
            self._var_loop_count.disabled = True
        else:
            self._var_cross_count.disabled = self.strip_crosses is None or self.strip_edges
            self._var_loop_count.disabled = self.strip_loops is None

    @RFTool.on_target_change
    def update_target(self):
        if self.defer_recomputing: return
        sprint(f'Strokes Update Target')
        if not self.just_created: self.reset()
        else: self.just_created = False

    @RFTool.on_target_change
    @RFTool.on_view_change
    def update(self):
        if self.defer_recomputing: return

        sprint(f'Strokes Update')

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
            ctr = Point.average(v.co for v in {v for e in current for v in e.verts})
            self.edge_collections.append({
                'edges': current,
                'center': ctr,
            })

    def filter_edge_selection(self, bme):
        return bme.select or len(bme.link_faces) < 2

    def update_hover_edge(self):
        sprint(f'Strokes Update Hover Edge')
        self.hovering_edge,_     = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'])
        self.hovering_sel_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'], selected_only=True)

    def update_connection_pre(self):
        sprint(f'Strokes Update Connection Pre')
        if self.connection_pre and self.connection_pre_last_mouse == self.actions.mouse:
            return
        self.connection_pre_last_mouse = self.actions.mouse
        self.connection_pre = None
        if not options['strokes snap stroke']: return
        hovering_sel_vert_snap, _ = self.rfcontext.accel_nearest2D_vert(max_dist=options['strokes snap dist'])
        if not hovering_sel_vert_snap: return
        self.connection_pre = (
            self.rfcontext.Point_to_Point2D(hovering_sel_vert_snap.co),
            self.actions.mouse,
        )

    @FSM.on_state('main', 'enter')
    def modal_main_enter(self):
        self.connection_post = None

    @FSM.on_state('main')
    def modal_main(self):
        sprint(f'Strokes Main')

        if self.actions.mousemove:
            if not self.actions.using('action', ignoredrag=True):
                # only update while not pressing action, because action includes drag, and
                # the artist might move mouse off selected edge before drag kicks in!
                self.stopwatch_hover_edge.reset()

            if self.actions.using_onlymods('insert'):
                self.stopwatch_connection_pre.reset()
            else:
                self.connection_pre = None

        if self.actions.using_onlymods('insert'):
            self.set_widget('brush')
        elif self.hovering_sel_edge:
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

        if self.hovering_sel_edge:
            if self.actions.pressed('action'):
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
                # fn_filter_bmelem=self.filter_edge_selection,
                kwargs_select={'supparts': False},
                kwargs_deselect={'subparts': False},
            )

        if self.actions.pressed({'select single', 'select single add'}, unpress=False):
            sel_only = self.actions.pressed('select single')
            self.actions.unpress()
            if not sel_only and not self.hovering_edge: return
            self.rfcontext.undo_push('select')
            if sel_only: self.rfcontext.deselect_all()
            if not self.hovering_edge: return
            if self.hovering_edge.select: self.rfcontext.deselect(self.hovering_edge)
            else:                         self.rfcontext.select(self.hovering_edge, supparts=False, only=sel_only)
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

    @RFWidget.on_actioning('Strokes stroke')
    def stroking(self):
        hovering_sel_vert_snap,_ = self.rfcontext.accel_nearest2D_vert(max_dist=options['strokes snap dist'])
        if options['strokes snap stroke'] and hovering_sel_vert_snap:
            self.connection_post = (
                self.rfcontext.Point_to_Point2D(hovering_sel_vert_snap.co),
                self.actions.mouse,
            )
        else:
            self.connection_post = None

    @RFWidget.on_action('Strokes stroke')
    def stroke(self):
        # called when artist finishes a stroke

        Point_to_Point2D        = self.rfcontext.Point_to_Point2D
        raycast_sources_Point2D = self.rfcontext.raycast_sources_Point2D
        accel_nearest2D_vert    = self.rfcontext.accel_nearest2D_vert

        # filter stroke down where each pt is at least 1px away to eliminate local wiggling
        radius = self.rfwidgets['brush'].radius
        stroke = self.rfwidgets['brush'].stroke2D
        stroke = process_stroke_filter(stroke)
        stroke = process_stroke_source(
            stroke,
            raycast_sources_Point2D,
            Point_to_Point2D=Point_to_Point2D,
            clamp_point_to_symmetry=self.rfcontext.clamp_point_to_symmetry,
        )
        stroke3D = [raycast_sources_Point2D(s)[0] for s in stroke]
        stroke3D = [s for s in stroke3D if s]

        # bail if there aren't enough stroke data points to work with
        if len(stroke3D) < 2: return

        sel_verts = self.rfcontext.get_selected_verts()
        sel_edges = self.rfcontext.get_selected_edges()
        s0, s1 = Point_to_Point2D(stroke3D[0]), Point_to_Point2D(stroke3D[-1])
        bmv0, _ = accel_nearest2D_vert(point=s0, max_dist=options['strokes snap dist']) # self.rfwidgets['brush'].radius)
        bmv1, _ = accel_nearest2D_vert(point=s1, max_dist=options['strokes snap dist']) # self.rfwidgets['brush'].radius)
        if not options['strokes snap stroke']:
            if bmv0 and not bmv0.select: bmv0 = None
            if bmv1 and not bmv1.select: bmv1 = None
        bmv0_sel = bmv0 and bmv0 in sel_verts
        bmv1_sel = bmv1 and bmv1 in sel_verts

        if bmv0:
            stroke3D = [bmv0.co] + stroke3D
        if bmv1:
            stroke3D = stroke3D + [bmv1.co]

        self.strip_stroke3D = stroke3D
        self.strip_crosses = None
        self.strip_loops = None
        self.strip_edges = False
        self.replay = None

        boundary_edges = self.get_edges_for_extrude()

        # are we extruding or creating a new edge strip/loop?
        extrude = bool(boundary_edges)

        # is the stroke in a circle?  note: circle must have a large enough radius
        cyclic  = (stroke[0] - stroke[-1]).length < radius
        cyclic &= any((s - stroke[0]).length > 2.0 * radius for s in stroke)

        # need to determine shape of extrusion
        # key: |- stroke  (‾_/\)
        #      C  corner in stroke (roughly 90° angle, but not easy to detect.  what if the stroke loops over itself?)
        #      ǁ= selected boundary or wire edges
        #      O  vertex under stroke
        #      X  corner vertex (edges change direction)
        # notes:
        # - vertex under stroke must be at beginning or ending of stroke
        # - vertices are "under stroke" if they are selected or if "Snap Stroke to Unselected" is enabled

        #  Strip   Cycle    L-shape   C-shape   T-shape   U-shape   I-shape   Equals   O-shape   D-shape
        #    |     /‾‾‾\    |         O------   ===O===   ǁ     ǁ   ===O===   ======   X=====O   O-----C
        #    |    |     |   |         ǁ            |      ǁ     ǁ      |               ǁ     |   ǁ     |
        #    |     \___/    O======   X======      |      O-----O   ===O===   ------   X=====O   O-----C

        # so far only Strip, Cycle, L, U, Strip are implemented.  C, T, I, O, D are not yet implemented

        # L vs C: there is a corner vertex in the edges (could we extend the L shape??)
        # D has corners in the stroke, which will be tricky to determine... use acceleration?

        face_islands = list(self.get_edge_connected_faces(boundary_edges))
        # print(f'stroke: {len(boundary_edges)} {len(face_islands)}')
        # print(face_islands)

        if extrude:
            if cyclic:
                # print(f'Extrude Cycle')
                self.replay = self.extrude_cycle
            else:
                if any([bmv0_sel, bmv1_sel]):
                    if not all([bmv0_sel, bmv1_sel]):
                        bmv = bmv0 if bmv0_sel else bmv1
                        if len(set(bmv.link_edges) & sel_edges) == 1:
                            # print(f'Extrude L or C')
                            self.replay = self.extrude_l
                        else:
                            # print(f'Extrude T')
                            self.replay = self.extrude_t
                    else:
                        # print(f'Extrude U or O or I')
                        # XXX: I-shaped extrusions?
                        self.replay = self.extrude_u
                else:
                    # print(f'Extrude Equals')
                    self.replay = self.extrude_equals
        else:
            if cyclic:
                # print(f'Create Cycle')
                self.replay = self.create_cycle
            else:
                # print(f'Create Strip')
                self.replay = self.create_strip

        # print(self.replay)
        if self.replay: self.replay()

    def get_edges_for_extrude(self, only_closest=None):
        edges = { e for e in self.rfcontext.get_selected_edges() if e.is_boundary or e.is_wire }
        if not only_closest:
            return edges
        # TODO: find vert-connected-edge-island that has the edge closest to stroke
        return edges

    def get_vert_connected_edges(self, edges):
        edges = set(edges)
        while edges:
            island = set()
            working = { next(iter(edges)) }
            while working:
                edge = working.pop()
                if edge not in edges: continue
                edges.remove(edge)
                island.add(edge)
                working |= { e for v in edge.verts for e in v.link_edges }
            yield island

    def get_edge_connected_faces(self, edges):
        edges = set(edges)
        while edges:
            island = set()
            working = { next(iter(edges)) }
            while working:
                edge = working.pop()
                if edge not in edges: continue
                edges.remove(edge)
                faces = set(edge.link_faces)
                island |= faces
                working |= { e2 for f in faces for e in f.edges for f2 in e.link_faces for e2 in f2.edges }
            yield island

    @RFTool.dirty_when_done
    def create_cycle(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]
        stroke += stroke[:1]
        if not all(stroke): return  # part of stroke cannot project

        if self.strip_crosses is not None:
            self.rfcontext.undo_repush('create cycle')
        else:
            self.rfcontext.undo_push('create cycle')

        if self.strip_crosses is None:
            if options['strokes span insert mode'] == 'Brush Size':
                stroke_len = sum((s1 - s0).length for (s0, s1) in iter_pairs(stroke, wrap=False))
                self.strip_crosses = max(1, math.ceil(stroke_len / (2 * self.rfwidgets['brush'].radius)))
            else:
                self.strip_crosses = options['strokes span count']
        crosses = self.strip_crosses
        percentages = [i / crosses for i in range(crosses)]
        nstroke = restroke(stroke, percentages)

        if len(nstroke) <= 2:
            # too few vertices for a cycle
            self.rfcontext.alert_user(
                'Could not find create cycle from stroke.  Please try again.'
            )
            return

        with self.defer_recomputing_while():
            verts = [self.rfcontext.new2D_vert_point(s) for s in nstroke]
            edges = [self.rfcontext.new_edge([v0, v1]) for (v0, v1) in iter_pairs(verts, wrap=True)]
            self.rfcontext.select(edges)
            self.just_created = True

    @RFTool.dirty_when_done
    def create_strip(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]
        if not all(stroke): return  # part of stroke cannot project

        if self.strip_crosses is not None:
            self.rfcontext.undo_repush('create strip')
        else:
            self.rfcontext.undo_push('create strip')

        self.rfcontext.get_accel_visible(force=True)

        if self.strip_crosses is None:
            if options['strokes span insert mode'] == 'Brush Size':
                stroke_len = sum((s1 - s0).length for (s0, s1) in iter_pairs(stroke, wrap=False))
                self.strip_crosses = max(1, math.ceil(stroke_len / (2 * self.rfwidgets['brush'].radius)))
            else:
                self.strip_crosses = options['strokes span count']
        crosses = self.strip_crosses
        percentages = [i / crosses for i in range(crosses+1)]
        nstroke = restroke(stroke, percentages)

        if len(nstroke) < 2: return  # too few stroke points, from a short stroke?

        snap0,_ = self.rfcontext.accel_nearest2D_vert(point=nstroke[0],  max_dist=options['strokes merge dist']) # self.rfwidgets['brush'].radius)
        snap1,_ = self.rfcontext.accel_nearest2D_vert(point=nstroke[-1], max_dist=options['strokes merge dist']) # self.rfwidgets['brush'].radius)
        if not options['strokes snap stroke'] and snap0 and not snap0.select: snap0 = None
        if not options['strokes snap stroke'] and snap1 and not snap1.select: snap1 = None

        with self.defer_recomputing_while():
            verts = [self.rfcontext.new2D_vert_point(s) for s in nstroke]
            edges = [self.rfcontext.new_edge([v0, v1]) for (v0, v1) in iter_pairs(verts, wrap=False)]

            if snap0:
                co = snap0.co
                verts[0].merge(snap0)
                verts[0].co = co
                self.rfcontext.clean_duplicate_bmedges(verts[0])
            if snap1:
                co = snap1.co
                verts[-1].merge(snap1)
                verts[-1].co = co
                self.rfcontext.clean_duplicate_bmedges(verts[-1])

            self.rfcontext.select(edges)
            self.just_created = True

    @RFTool.dirty_when_done
    def extrude_cycle(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]
        if not all(stroke): return  # part of stroke cannot project

        if self.strip_loops is not None:
            self.rfcontext.undo_repush('extrude cycle')
        else:
            self.rfcontext.undo_push('extrude cycle')
        pass

        sctr = Point2D.average(stroke)
        stroke_centered = [(s - sctr) for s in stroke]

        # make sure stroke is counter-clockwise
        winding = sum((s0.x * s1.y - s1.x * s0.y) for (s0, s1) in iter_pairs(stroke_centered, wrap=False))
        if winding < 0:
            stroke.reverse()
            stroke_centered.reverse()

        # get selected edges that we can extrude
        edges = self.get_edges_for_extrude()
        # find cycle in selection
        best = None
        best_score = None
        for edge_cycle in find_edge_cycles(edges):
            verts = get_strip_verts(edge_cycle)
            vctr = Point2D.average([Point_to_Point2D(v.co) for v in verts])
            score = (sctr - vctr).length
            if not best or score < best_score:
                best = edge_cycle
                best_score = score
        if not best:
            self.rfcontext.alert_user(
                'Could not find suitable edge cycle.  Make sure your selection is accurate.'
            )
            return

        edge_cycle = best
        vert_cycle = get_strip_verts(edge_cycle)[:-1]   # first and last verts are same---loop!
        vctr = Point2D.average([Point_to_Point2D(v.co) for v in vert_cycle])
        verts_centered = [(Point_to_Point2D(v.co) - vctr) for v in vert_cycle]

        # make sure edge cycle is counter-clockwise
        winding = sum((v0.x * v1.y - v1.x * v0.y) for (v0, v1) in iter_pairs(verts_centered, wrap=False))
        if winding < 0:
            edge_cycle.reverse()
            vert_cycle.reverse()
            verts_centered.reverse()

        # rotate cycle until first vert has smallest y
        idx = min_index(vert_cycle, lambda v:Point_to_Point2D(v.co).y)
        edge_cycle = edge_cycle[idx:] + edge_cycle[:idx]
        vert_cycle = vert_cycle[idx:] + vert_cycle[:idx]
        verts_centered = verts_centered[idx:] + verts_centered[:idx]

        # rotate stroke until first point matches best with vert_cycle
        v = verts_centered[0] / verts_centered[0].length
        idx = max_index(stroke_centered, lambda s:(s.x * v.x + s.y * v.y) / s.length)
        stroke = stroke[idx:] + stroke[:idx]
        stroke += stroke[:1]

        crosses = len(edge_cycle)
        percentages = [i / crosses for i in range(crosses)]
        nstroke = restroke(stroke, percentages)

        if self.strip_loops is None:
            self.strip_loops = max(1, math.ceil(1))  # TODO: calculate!
        loops = self.strip_loops

        with self.defer_recomputing_while():
            patch = []
            for i in range(crosses):
                v = Point_to_Point2D(vert_cycle[i].co)
                s = nstroke[i]
                cur_line = [vert_cycle[i]]
                for j in range(1, loops+1):
                    pj = j / loops
                    cur_line.append(self.rfcontext.new2D_vert_point(Point2D.weighted_average([
                        (pj, s),
                        (1 - pj, v)
                    ])))
                patch.append(cur_line)
            for i0 in range(crosses):
                i1 = (i0 + 1) % crosses
                for j0 in range(loops):
                    j1 = j0 + 1
                    self.rfcontext.new_face([patch[i0][j0], patch[i0][j1], patch[i1][j1], patch[i1][j0]])
            end_verts = [l[-1] for l in patch]
            edges = [v0.shared_edge(v1) for (v0, v1) in iter_pairs(end_verts, wrap=True)]

            self.rfcontext.select(edges)
            self.just_created = True

    @RFTool.dirty_when_done
    def extrude_u(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        new2D_vert_point = self.rfcontext.new2D_vert_point
        new_face = self.rfcontext.new_face

        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]
        if not all(stroke): return  # part of stroke cannot project

        if self.strip_crosses is not None:
            self.rfcontext.undo_repush('extrude U')
        else:
            self.rfcontext.undo_push('extrude U')

        self.rfcontext.get_accel_visible(force=True)

        # get selected edges that we can extrude
        edges = self.get_edges_for_extrude()
        sel_verts = {v for e in edges for v in e.verts}

        s0, s1 = stroke[0], stroke[-1]
        bmv0,_ = self.rfcontext.accel_nearest2D_vert(point=s0, max_dist=options['strokes merge dist']) # self.rfwidgets['brush'].radius)
        bmv1,_ = self.rfcontext.accel_nearest2D_vert(point=s1, max_dist=options['strokes merge dist']) # self.rfwidgets['brush'].radius)
        bmv0 = bmv0 if bmv0 in sel_verts else None
        bmv1 = bmv1 if bmv1 in sel_verts else None
        assert bmv0 and bmv1

        edges0,verts0 = [],[bmv0]
        while True:
            bmes = set(verts0[-1].link_edges) & edges
            if edges0: bmes.remove(edges0[-1])
            if len(bmes) != 1: break
            bme = bmes.pop()
            edges0.append(bme)
            verts0.append(bme.other_vert(verts0[-1]))
        points0 = [Point_to_Point2D(v.co) for v in verts0]
        diffs0 = [(p1 - points0[0]) for p1 in points0]

        edges1,verts1 = [],[bmv1]
        while True:
            bmes = set(verts1[-1].link_edges) & edges
            if edges1: bmes.remove(edges1[-1])
            if len(bmes) != 1: break
            bme = bmes.pop()
            edges1.append(bme)
            verts1.append(bme.other_vert(verts1[-1]))
        points1 = [Point_to_Point2D(v.co) for v in verts1]
        diffs1 = [(p1 - points1[0]) for p1 in points1]

        if len(diffs0) != len(diffs1):
            self.rfcontext.alert_user(
                'Selections must contain same number of edges'
            )
            return

        if self.strip_crosses is None:
            if options['strokes span insert mode'] == 'Brush Size':
                stroke_len = sum((s1 - s0).length for (s0, s1) in iter_pairs(stroke, wrap=False))
                self.strip_crosses = max(1, math.ceil(stroke_len / (2 * self.rfwidgets['brush'].radius)))
            else:
                self.strip_crosses = options['strokes span count']
        crosses = self.strip_crosses
        percentages = [i / crosses for i in range(crosses+1)]
        nstroke = restroke(stroke, percentages)
        nsegments = len(diffs0)

        with self.defer_recomputing_while():
            nedges = []
            nverts = None
            for istroke,s in enumerate(nstroke):
                pverts = nverts
                if istroke == 0:
                    nverts = verts0
                elif istroke == crosses:
                    nverts = verts1
                else:
                    p = istroke / crosses
                    offsets = [diffs0[i] * (1 - p) + diffs1[i] * p for i in range(nsegments)]
                    nverts = [new2D_vert_point(s + offset) for offset in offsets]
                if pverts:
                    for i in range(len(nverts)-1):
                        lst = [pverts[i], pverts[i+1], nverts[i+1], nverts[i]]
                        if all(lst) and not has_duplicates(lst):
                            new_face(lst)
                    bmv1 = nverts[0]
                    nedges.append(bmv0.shared_edge(bmv1))
                    bmv0 = bmv1

            self.rfcontext.select(nedges)
            self.just_created = True

    @RFTool.dirty_when_done
    def extrude_t(self):
        self.rfcontext.alert_user(
            'T-shaped extrusions are not handled, yet'
        )

    @RFTool.dirty_when_done
    def extrude_l(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]
        if not all(stroke): return  # part of stroke cannot project

        if self.strip_crosses is not None:
            self.rfcontext.undo_repush('extrude L')
        else:
            self.rfcontext.undo_push('extrude L')

        self.rfcontext.get_accel_visible(force=True)

        new2D_vert_point = self.rfcontext.new2D_vert_point
        new_face = self.rfcontext.new_face

        # get selected edges that we can extrude
        edges = self.get_edges_for_extrude()
        sel_verts = { v for e in edges for v in e.verts }

        s0, s1 = stroke[0], stroke[-1]
        bmv0,_ = self.rfcontext.accel_nearest2D_vert(point=s0, max_dist=options['strokes merge dist']) # self.rfwidgets['brush'].radius)
        bmv1,_ = self.rfcontext.accel_nearest2D_vert(point=s1, max_dist=options['strokes merge dist']) # self.rfwidgets['brush'].radius)
        bmv0 = bmv0 if bmv0 in sel_verts else None
        bmv1 = bmv1 if bmv1 in sel_verts else None
        if bmv1 in sel_verts:
            # reverse stroke
            stroke.reverse()
            s0, s1 = s1, s0
            bmv0, bmv1 = bmv1, None
        if not bmv0:
            # possible fix for issue #870?
            # could not find a vert to extrude from?
            self.rfcontext.undo_cancel()
            return
        nedges,nverts = [],[bmv0]
        while True:
            bmes = set(nverts[-1].link_edges) & edges
            if nedges: bmes.remove(nedges[-1])
            if len(bmes) != 1: break
            bme = next(iter(bmes))
            nedges.append(bme)
            nverts.append(bme.other_vert(nverts[-1]))
        npoints = [Point_to_Point2D(v.co) for v in nverts]
        ndiffs = [(p1 - npoints[0]) for p1 in npoints]

        if self.strip_crosses is None:
            if options['strokes span insert mode'] == 'Brush Size':
                stroke_len = sum((s1 - s0).length for (s0, s1) in iter_pairs(stroke, wrap=False))
                self.strip_crosses = max(1, math.ceil(stroke_len / (2 * self.rfwidgets['brush'].radius)))
            else:
                self.strip_crosses = options['strokes span count']
        crosses = self.strip_crosses
        percentages = [i / crosses for i in range(crosses+1)]
        nstroke = restroke(stroke, percentages)

        with self.defer_recomputing_while():
            nedges = []
            for s in nstroke[1:]:
                pverts = nverts
                nverts = [new2D_vert_point(s+d) for d in ndiffs]
                for i in range(len(nverts)-1):
                    lst = [pverts[i], pverts[i+1], nverts[i+1], nverts[i]]
                    if all(lst) and not has_duplicates(lst):
                        new_face(lst)
                bmv1 = nverts[0]
                if bmv0 and bmv1:
                    nedges.append(bmv0.shared_edge(bmv1))
                bmv0 = bmv1

            self.rfcontext.select(nedges)
            self.just_created = True

    @RFTool.dirty_when_done
    def extrude_equals(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]
        if not all(stroke): return  # part of stroke cannot project

        if self.strip_crosses is not None:
            self.rfcontext.undo_repush('extrude strip')
        else:
            self.rfcontext.undo_push('extrude strip')

        # get selected edges that we can extrude
        edges = self.get_edges_for_extrude()
        sel_verts = { v for e in edges for v in e.verts }

        self.rfcontext.get_accel_visible(force=True)

        s0, s1 = stroke[0], stroke[-1]
        sd = s1 - s0

        # check if verts near stroke ends connect to any of the selected strips
        bmv0,_ = self.rfcontext.accel_nearest2D_vert(point=s0, max_dist=options['strokes merge dist']) # self.rfwidgets['brush'].radius)
        bmv1,_ = self.rfcontext.accel_nearest2D_vert(point=s1, max_dist=options['strokes merge dist']) # self.rfwidgets['brush'].radius)
        if not options['strokes snap stroke'] and bmv0 and not bmv0.select: bmv0 = None
        if not options['strokes snap stroke'] and bmv1 and not bmv1.select: bmv1 = None
        edges0 = walk_to_corner(bmv0, edges) if bmv0 else []
        edges1 = walk_to_corner(bmv1, edges) if bmv1 else []
        edges0 = [e for e in edges0 if e.is_valid] if edges0 else None
        edges1 = [e for e in edges1 if e.is_valid] if edges1 else None
        if edges0 and edges1 and len(edges0) != len(edges1):
            self.rfcontext.alert_user(
                'Edge strips near ends of stroke have different counts.  Make sure your stroke is accurate.'
            )
            return
        if edges0:
            self.strip_crosses = len(edges0)
            self.strip_edges = True
        if edges1:
            self.strip_crosses = len(edges1)
            self.strip_edges = True
        # TODO: set best and ensure that best connects edges0 and edges1

        # check all strips for best "scoring"
        best = None
        best_score = None
        for edge_strip in find_edge_strips(edges):
            verts = get_strip_verts(edge_strip)
            p0, p1 = Point_to_Point2D(verts[0].co), Point_to_Point2D(verts[-1].co)
            if not p0 or not p1: continue
            pd = p1 - p0
            dot = pd.x * sd.x + pd.y * sd.y
            if dot < 0:
                edge_strip.reverse()
                p0, p1, pd, dot = p1, p0, -pd, -dot
            score = ((s0 - p0).length + (s1 - p1).length) #* (1 - dot)
            if not best or score < best_score:
                best = edge_strip
                best_score = score
        if not best:
            self.rfcontext.alert_user(
                'Could not determine which edge strip to extrude from.  Make sure your selection is accurate.'
            )
            return

        if len(best) == 1:
            # special case where reversing the edge strip will NOT prevent twisted faces
            verts = best[0].verts
            p0, p1 = Point_to_Point2D(verts[0].co), Point_to_Point2D(verts[-1].co)
            if p0 and p1:
                pd = p1 - p0
                dot = pd.x * sd.x + pd.y * sd.y
                if dot < 0:
                    # reverse stroke!
                    stroke.reverse()
                    s0, s1 = s1, s0
                    sd = -sd

        # tessellate stroke to match edge
        edges = best
        verts = get_strip_verts(edges)
        edge_lens = [
            (Point_to_Point2D(e.verts[0].co) - Point_to_Point2D(e.verts[1].co)).length
            for e in edges
        ]
        strip_len = sum(edge_lens)
        avg_len = strip_len / len(edges)
        per_lens = [l / strip_len for l in edge_lens]
        percentages = [0] + [max(0, min(1, s)) for (w, s) in iter_running_sum(per_lens)]
        nstroke = restroke(stroke, percentages)
        assert len(nstroke) == len(verts), f'Tessellated stroke ({len(nstroke)}) does not match vert count ({len(verts)})'

        # average distance between stroke and strip
        p0, p1 = Point_to_Point2D(verts[0].co), Point_to_Point2D(verts[-1].co)
        avg_dist = ((p0 - s0).length + (p1 - s1).length) / 2
        if isnan(avg_dist):
            self.rfcontext.alert_user(
                'Could not determine distance between stroke and selected strip.  Please try again.'
            )
            return

        # determine cross count
        if self.strip_crosses is None:
            if options['strokes span insert mode'] == 'Brush Size':
                self.strip_crosses = max(math.ceil(avg_dist / (2 * self.rfwidgets['brush'].radius)), 2)
            else:
                self.strip_crosses = options['strokes span count']
        crosses = self.strip_crosses + 1

        with self.defer_recomputing_while():
            # extrude!
            patch = []
            prev, last = None, []
            for (v0, p1) in zip(verts, nstroke):
                p0 = Point_to_Point2D(v0.co)
                cur = [v0] + [
                    self.rfcontext.new2D_vert_point(p0 + (p1-p0) * (c / (crosses-1)))
                    for c in range(1, crosses)
                ]
                patch += [cur]
                last.append(cur[-1])
                if prev:
                    for i in range(crosses-1):
                        nface = [prev[i+0], cur[i+0], cur[i+1], prev[i+1]]
                        if all(nface):
                            self.rfcontext.new_face(nface)
                        else:
                            for v0,v1 in iter_pairs(nface, True):
                                if v0 and v1 and not v0.share_edge(v1):
                                    self.rfcontext.new_edge([v0, v1])
                prev = cur

            edges0 = [e for e in edges0 if e.is_valid] if edges0 else None
            edges1 = [e for e in edges1 if e.is_valid] if edges1 else None

            if edges0:
                side_verts = get_strip_verts(edges0)
                if side_verts[1] == verts[0]: side_verts.reverse()
                for a,b in zip(side_verts[1:], patch[0][1:]):
                    co = a.co
                    b.merge(a)
                    b.co = co
                    self.rfcontext.clean_duplicate_bmedges(b)
            if edges1:
                side_verts = get_strip_verts(edges1)
                if side_verts[1] == verts[-1]: side_verts.reverse()
                for a,b in zip(side_verts[1:], patch[-1][1:]):
                    co = a.co
                    b.merge(a)
                    b.co = co
                    self.rfcontext.clean_duplicate_bmedges(b)

            nedges = [
                v0.shared_edge(v1)
                for (v0, v1) in iter_pairs(last, wrap=False)
                if v0 and v1
            ]

            self.rfcontext.select(nedges)
            self.just_created = True

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
    @profiler.function
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

    @DrawCallbacks.on_draw('post2d')
    def draw_postpixel(self):
        if self._fsm.state == 'move': return
        gpustate.blend('ALPHA')
        point_to_point2d = self.rfcontext.Point_to_Point2D
        up = self.rfcontext.Vec_up()
        size_to_size2D = self.rfcontext.size_to_size2D
        text_draw2D = self.rfcontext.drawing.text_draw2D
        self.rfcontext.drawing.set_font_size(12)

        for collection in self.edge_collections:
            l = len(collection['edges'])
            c = collection['center']
            xy = point_to_point2d(c)
            if not xy: continue
            xy.y += 10
            text_draw2D(str(l), xy, color=(1,1,0,1), dropshadow=(0,0,0,0.5))

        if self.connection_pre:
            Globals.drawing.draw2D_linestrip(self.connection_pre, themes['stroke'], width=2, stipple=[4,4])
        if self.connection_post:
            Globals.drawing.draw2D_linestrip(self.connection_post, themes['stroke'], width=2, stipple=[4,4])

