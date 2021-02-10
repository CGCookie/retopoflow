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

import math
import bgl
import bpy
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_point_tri_2d

from ..rftool import RFTool
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_brushstroke import RFWidget_BrushStroke_Factory


from ...addon_common.common.debug import dprint
from ...addon_common.common.globals import Globals
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import (
    Point, Vec, Direction,
    Point2D, Vec2D,
    Accel2D,
    clamp, mid,
)
from ...addon_common.common.bezier import CubicBezierSpline, CubicBezier
from ...addon_common.common.shaders import circleShader, edgeShortenShader, arrowShader
from ...addon_common.common.utils import iter_pairs, iter_running_sum, min_index, max_index
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat
from ...config.options import options, themes

from .strokes_utils import (
    process_stroke_filter, process_stroke_source,
    find_edge_cycles,
    find_edge_strips, get_strip_verts,
    restroke, walk_to_corner,
)


class RFTool_Strokes(RFTool):
    name        = 'Strokes'
    description = 'Insert edge strips and extrude edges into a patch'
    icon        = 'strokes-icon.png'
    help        = 'strokes.md'
    shortcut    = 'strokes tool'
    statusbar   = '{{insert}} Insert edge strip and bridge\t{{increase count}} Increase segments\t{{decrease count}} Decrease segments'
    ui_config   = 'strokes_options.html'

class Strokes_RFWidgets:
    RFWidget_Default = RFWidget_Default_Factory.create()
    RFWidget_BrushStroke = RFWidget_BrushStroke_Factory.create(
        BoundInt('''options['strokes radius']''', min_value=1),
        outer_border_color=themes['strokes'],
    )
    RFWidget_Move = RFWidget_Default_Factory.create('HAND')

    def init_rfwidgets(self):
        self.rfwidgets = {
            'default': self.RFWidget_Default(self),
            'brush': self.RFWidget_BrushStroke(self),
            'hover':   self.RFWidget_Move(self),
        }
        self.rfwidget = None


class Strokes(RFTool_Strokes, Strokes_RFWidgets):
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

    @RFTool_Strokes.on_init
    def init(self):
        self.init_rfwidgets()
        self.strip_crosses = None
        self.strip_loops = None
        self._var_fixed_span_count = BoundInt('''options['strokes span count']''', min_value=1, max_value=128)
        self._var_cross_count = BoundInt('''self.cross_count''', min_value=1, max_value=500)
        self._var_loop_count  = BoundInt('''self.loop_count''', min_value=1, max_value=500)

    def update_span_mode(self):
        mode = options['strokes span insert mode']
        self.ui_summary.innerText = f'Strokes: {mode}'
        self.ui_insert.dirty(cause='insert mode change', children=True)

    @RFTool_Strokes.on_ui_setup
    def ui(self):
        ui_options = self.document.body.getElementById('strokes-options')
        self.ui_summary = ui_options.getElementById('strokes-summary')
        self.ui_insert = ui_options.getElementById('strokes-insert-modes')
        self.ui_radius = ui_options.getElementById('strokes-radius')
        def dirty_radius():
            self.ui_radius.dirty(cause='radius changed')
        self.rfwidgets['brush'].get_radius_boundvar().on_change(dirty_radius)
        self.update_span_mode()

    @RFTool_Strokes.on_reset
    def reset(self):
        self.replay = None
        self.strip_crosses = None
        self.strip_loops = None
        self.strip_edges = False
        self.just_created = False
        self.defer_recomputing = False
        self.hovering_edge = None
        self.hovering_sel_edge = None
        self.connection_pre = None
        self.connection_post = None
        self.update_ui()

    def update_ui(self):
        if self.replay is None:
            self._var_cross_count.disabled = True
            self._var_loop_count.disabled = True
        else:
            self._var_cross_count.disabled = self.strip_crosses is None or self.strip_edges
            self._var_loop_count.disabled = self.strip_loops is None

    @RFTool_Strokes.on_target_change
    def update_target(self):
        if self.defer_recomputing: return
        if not self.just_created: self.reset()
        else: self.just_created = False

    @RFTool_Strokes.on_target_change
    @RFTool_Strokes.on_view_change
    @profiler.function
    def update(self):
        if self.defer_recomputing: return

        self.update_ui()

        self.edge_collections = []
        edges = {e for e in self.rfcontext.get_selected_edges() if not e.is_manifold}
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

    @RFTool_Strokes.FSM_State('main')
    @profiler.function
    def modal_main(self):
        if not self.actions.using('action', ignoredrag=True):
            # only update while not pressing action, because action includes drag, and
            # the artist might move mouse off selected edge before drag kicks in!
            self.hovering_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'])
            self.hovering_sel_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'], selected_only=True)

        self.connection_pre = None
        self.connection_post = None
        if self.actions.using_onlymods('insert'):
            hovering_sel_vert,_ = self.rfcontext.accel_nearest2D_vert(max_dist=self.rfwidgets['brush'].radius)
            if hovering_sel_vert and (options['strokes snap stroke'] or hovering_sel_vert.select):
                point_to_point2d = self.rfcontext.Point_to_Point2D
                self.connection_pre = (point_to_point2d(hovering_sel_vert.co), self.actions.mouse)

        if self.actions.using_onlymods('insert'):
            self.rfwidget = self.rfwidgets['brush']
        elif self.hovering_sel_edge:
            self.rfwidget = self.rfwidgets['hover']
        else:
            self.rfwidget = self.rfwidgets['default']

        for rfwidget in self.rfwidgets.values():
            if self.rfwidget == rfwidget: continue
            if rfwidget.inactive_passthrough():
                self.rfwidget = rfwidget
                return

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

        if self.actions.pressed({'select paint', 'select paint add'}, unpress=False):
            sel_only = self.actions.pressed('select paint')
            self.actions.unpress()
            return self.rfcontext.setup_smart_selection_painting(
                {'edge'},
                selecting=not sel_only,
                deselect_all=sel_only,
                fn_filter_bmelem=self.filter_edge_selection,
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

        # if self.rfcontext.actions.pressed({'increase count', 'decrease count'}, unpress=False):
        #     print('changing count!', self.strip_crosses, self.strip_loops, self.replay)
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

    @Strokes_RFWidgets.RFWidget_BrushStroke.on_actioning
    def stroking(self):
        self.connection_post = None
        hovering_sel_vert,_ = self.rfcontext.accel_nearest2D_vert(max_dist=self.rfwidgets['brush'].radius)
        if hovering_sel_vert and (options['strokes snap stroke'] or hovering_sel_vert.select):
            point_to_point2d = self.rfcontext.Point_to_Point2D
            self.connection_post = (point_to_point2d(hovering_sel_vert.co), self.actions.mouse)

    @Strokes_RFWidgets.RFWidget_BrushStroke.on_action
    def stroke(self):
        # called when artist finishes a stroke

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        raycast_sources_Point2D = self.rfcontext.raycast_sources_Point2D
        accel_nearest2D_vert = self.rfcontext.accel_nearest2D_vert

        # filter stroke down where each pt is at least 1px away to eliminate local wiggling
        radius = self.rfwidgets['brush'].radius
        stroke = self.rfwidgets['brush'].stroke2D
        stroke = process_stroke_filter(stroke)
        #stroke = process_stroke_source(stroke, raycast_sources_Point2D, is_point_on_mirrored_side=self.rfcontext.is_point_on_mirrored_side)
        #stroke = process_stroke_source(stroke, raycast_sources_Point2D, Point_to_Point2D=Point_to_Point2D, mirror_point=self.rfcontext.mirror_point)
        stroke = process_stroke_source(stroke, raycast_sources_Point2D, Point_to_Point2D=Point_to_Point2D, clamp_point_to_symmetry=self.rfcontext.clamp_point_to_symmetry)
        stroke3D = [raycast_sources_Point2D(s)[0] for s in stroke]
        stroke3D = [s for s in stroke3D if s]

        if len(stroke3D) < 2: return

        self.strip_stroke3D = stroke3D
        self.strip_crosses = None
        self.strip_loops = None
        self.strip_edges = False
        self.replay = None

        cyclic = (stroke[0] - stroke[-1]).length < radius and any((s-stroke[0]).length > radius for s in stroke)
        extrude = not all(e.is_manifold for e in self.rfcontext.get_selected_edges())
        if extrude:
            if cyclic:
                self.replay = self.extrude_cycle
            else:
                sel_verts = self.rfcontext.get_selected_verts()
                sel_edges = self.rfcontext.get_selected_edges()
                s0,s1 = Point_to_Point2D(stroke3D[0]),Point_to_Point2D(stroke3D[-1])
                bmv0,_ = accel_nearest2D_vert(point=s0, max_dist=self.rfwidgets['brush'].radius)
                bmv1,_ = accel_nearest2D_vert(point=s1, max_dist=self.rfwidgets['brush'].radius)
                if not options['strokes snap stroke'] and bmv0 and not bmv0.select: bmv0 = None
                if not options['strokes snap stroke'] and bmv1 and not bmv1.select: bmv1 = None
                bmv0_sel = bmv0 and bmv0 in sel_verts
                bmv1_sel = bmv1 and bmv1 in sel_verts
                if bmv0_sel or bmv1_sel:
                    if not bmv0_sel or not bmv1_sel:
                        bmv = bmv0 if bmv0_sel else bmv1
                        if len(set(bmv.link_edges) & sel_edges) == 1:
                            self.replay = self.extrude_l
                        else:
                            self.replay = self.extrude_t
                    else:
                        # XXX: I-shaped extrusions?
                        self.replay = self.extrude_c
                else:
                    self.replay = self.extrude_strip
        else:
            if cyclic:
                self.replay = self.create_cycle
            else:
                self.replay = self.create_strip

        # print(self.replay)
        if self.replay: self.replay()

    @RFTool_Strokes.dirty_when_done
    def create_cycle(self):
        if self.strip_crosses is not None:
            self.rfcontext.undo_repush('create cycle')
        else:
            self.rfcontext.undo_push('create cycle')

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]
        stroke += stroke[:1]

        if self.strip_crosses is None:
            stroke_len = sum((s1 - s0).length for (s0, s1) in iter_pairs(stroke, wrap=False))
            self.strip_crosses = max(1, math.ceil(stroke_len / (2 * self.rfwidgets['brush'].radius)))
        crosses = self.strip_crosses
        percentages = [i / crosses for i in range(crosses)]
        nstroke = restroke(stroke, percentages)

        self.defer_recomputing = True

        verts = [self.rfcontext.new2D_vert_point(s) for s in nstroke]
        edges = [self.rfcontext.new_edge([v0, v1]) for (v0, v1) in iter_pairs(verts, wrap=True)]

        self.just_created = True
        self.rfcontext.select(edges)
        self.defer_recomputing = False
        self.update()

    @RFTool_Strokes.dirty_when_done
    def create_strip(self):
        if self.strip_crosses is not None:
            self.rfcontext.undo_repush('create strip')
        else:
            self.rfcontext.undo_push('create strip')

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]

        if self.strip_crosses is None:
            stroke_len = sum((s1 - s0).length for (s0, s1) in iter_pairs(stroke, wrap=False))
            self.strip_crosses = max(1, math.ceil(stroke_len / (2 * self.rfwidgets['brush'].radius)))
        crosses = self.strip_crosses
        percentages = [i / crosses for i in range(crosses+1)]
        nstroke = restroke(stroke, percentages)

        if len(nstroke) < 2: return  # too few stroke points, from a short stroke?

        snap0,_ = self.rfcontext.accel_nearest2D_vert(point=nstroke[0], max_dist=self.rfwidgets['brush'].radius)
        snap1,_ = self.rfcontext.accel_nearest2D_vert(point=nstroke[-1], max_dist=self.rfwidgets['brush'].radius)
        if not options['strokes snap stroke'] and snap0 and not snap0.select: snap0 = None
        if not options['strokes snap stroke'] and snap1 and not snap1.select: snap1 = None

        self.defer_recomputing = True

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

        self.just_created = True
        self.rfcontext.select(edges)
        self.defer_recomputing = False
        self.update()

    @RFTool_Strokes.dirty_when_done
    def extrude_cycle(self):
        if self.strip_loops is not None:
            self.rfcontext.undo_repush('extrude cycle')
        else:
            self.rfcontext.undo_push('extrude cycle')
        pass

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]
        sctr = Point2D.average(stroke)
        stroke_centered = [(s - sctr) for s in stroke]

        # make sure stroke is counter-clockwise
        winding = sum((s0.x * s1.y - s1.x * s0.y) for (s0, s1) in iter_pairs(stroke_centered, wrap=False))
        if winding < 0:
            stroke.reverse()
            stroke_centered.reverse()

        # get selected edges that we can extrude
        edges = [e for e in self.rfcontext.get_selected_edges() if not e.is_manifold]
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

        self.defer_recomputing = True

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

        self.just_created = True
        self.rfcontext.select(edges)
        self.defer_recomputing = False
        self.update()

    @RFTool_Strokes.dirty_when_done
    def extrude_c(self):
        if self.strip_crosses is not None:
            self.rfcontext.undo_repush('extrude C')
        else:
            self.rfcontext.undo_push('extrude C')

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        new2D_vert_point = self.rfcontext.new2D_vert_point
        new_face = self.rfcontext.new_face

        # get selected edges that we can extrude
        edges = set(e for e in self.rfcontext.get_selected_edges() if not e.is_manifold)
        sel_verts = {v for e in edges for v in e.verts}

        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]
        s0, s1 = stroke[0], stroke[-1]
        bmv0,_ = self.rfcontext.accel_nearest2D_vert(point=s0, max_dist=self.rfwidgets['brush'].radius)
        bmv1,_ = self.rfcontext.accel_nearest2D_vert(point=s1, max_dist=self.rfwidgets['brush'].radius)
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
            stroke_len = sum((s1 - s0).length for (s0, s1) in iter_pairs(stroke, wrap=False))
            self.strip_crosses = max(1, math.ceil(stroke_len / (2 * self.rfwidgets['brush'].radius)))
        crosses = self.strip_crosses
        percentages = [i / crosses for i in range(crosses+1)]
        nstroke = restroke(stroke, percentages)
        nsegments = len(diffs0)

        self.defer_recomputing = True

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
                    a,b,c,d = pverts[i],pverts[i+1],nverts[i+1],nverts[i]
                    if a and b and c and d:
                        new_face([a,b,c,d])
                bmv1 = nverts[0]
                nedges.append(bmv0.shared_edge(bmv1))
                bmv0 = bmv1

        self.rfcontext.select(nedges)
        self.just_created = True
        self.defer_recomputing = False
        self.update()

    @RFTool_Strokes.dirty_when_done
    def extrude_t(self):
        self.rfcontext.alert_user(
            'T-shaped extrusions are not handled, yet'
        )

    @RFTool_Strokes.dirty_when_done
    def extrude_l(self):
        if self.strip_crosses is not None:
            self.rfcontext.undo_repush('extrude L')
        else:
            self.rfcontext.undo_push('extrude L')

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        new2D_vert_point = self.rfcontext.new2D_vert_point
        new_face = self.rfcontext.new_face

        # get selected edges that we can extrude
        edges = set(e for e in self.rfcontext.get_selected_edges() if not e.is_manifold)
        sel_verts = {v for e in edges for v in e.verts}

        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]
        s0, s1 = stroke[0], stroke[-1]
        bmv0,_ = self.rfcontext.accel_nearest2D_vert(point=s0, max_dist=self.rfwidgets['brush'].radius)
        bmv1,_ = self.rfcontext.accel_nearest2D_vert(point=s1, max_dist=self.rfwidgets['brush'].radius)
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
            stroke_len = sum((s1 - s0).length for (s0, s1) in iter_pairs(stroke, wrap=False))
            self.strip_crosses = max(1, math.ceil(stroke_len / (2 * self.rfwidgets['brush'].radius)))
        crosses = self.strip_crosses
        percentages = [i / crosses for i in range(crosses+1)]
        nstroke = restroke(stroke, percentages)

        self.defer_recomputing = True

        nedges = []
        for s in nstroke[1:]:
            pverts = nverts
            nverts = [new2D_vert_point(s+d) for d in ndiffs]
            for i in range(len(nverts)-1):
                a,b,c,d = pverts[i],pverts[i+1],nverts[i+1],nverts[i]
                if a and b and c and d:
                    new_face([a,b,c,d])
            bmv1 = nverts[0]
            nedges.append(bmv0.shared_edge(bmv1))
            bmv0 = bmv1

        self.just_created = True
        self.rfcontext.select(nedges)
        self.defer_recomputing = False
        self.update()

    @RFTool_Strokes.dirty_when_done
    def extrude_strip(self):
        if self.strip_crosses is not None:
            self.rfcontext.undo_repush('extrude strip')
        else:
            self.rfcontext.undo_push('extrude strip')

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        stroke = [Point_to_Point2D(s) for s in self.strip_stroke3D]

        # get selected edges that we can extrude
        edges = [e for e in self.rfcontext.get_selected_edges() if not e.is_manifold]
        sel_verts = {v for e in edges for v in e.verts}

        s0, s1 = stroke[0], stroke[-1]
        sd = s1 - s0

        # check if verts near stroke ends connect to any of the selected strips
        bmv0,_ = self.rfcontext.accel_nearest2D_vert(point=s0, max_dist=self.rfwidgets['brush'].radius)
        bmv1,_ = self.rfcontext.accel_nearest2D_vert(point=s1, max_dist=self.rfwidgets['brush'].radius)
        if not options['strokes snap stroke'] and bmv0 and not bmv0.select: bmv0 = None
        if not options['strokes snap stroke'] and bmv1 and not bmv1.select: bmv1 = None
        edges0 = walk_to_corner(bmv0, edges) if bmv0 else None
        edges1 = walk_to_corner(bmv1, edges) if bmv1 else None
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
        assert len(nstroke) == len(verts), (
            'Tessellated stroke (%d) does not match vert count (%d)' % (len(nstroke), len(verts))
        )
        # average distance between stroke and strip
        p0, p1 = Point_to_Point2D(verts[0].co), Point_to_Point2D(verts[-1].co)
        avg_dist = ((p0 - s0).length + (p1 - s1).length) / 2

        # determine cross count
        if self.strip_crosses is None:
            if options['strokes span insert mode'] == 'Brush Size':
                self.strip_crosses = max(math.ceil(avg_dist / (2 * self.rfwidgets['brush'].radius)), 2)
            else:
                self.strip_crosses = options['strokes span count']
        crosses = self.strip_crosses + 1

        self.defer_recomputing = True

        # extrude!
        patch = []
        prev, last = None, []
        for (v0, p1) in zip(verts, nstroke):
            p0 = Point_to_Point2D(v0.co)
            cur = [v0] + [self.rfcontext.new2D_vert_point(p0 + (p1-p0) * (c / (crosses-1))) for c in range(1, crosses)]
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

        nedges = [v0.shared_edge(v1) for (v0, v1) in iter_pairs(last, wrap=False)]

        self.just_created = True
        self.rfcontext.select(nedges)
        self.defer_recomputing = False
        self.update()

    @RFTool_Strokes.FSM_State('move', 'enter')
    def move_enter(self, bmverts=None, defer_recomputing=True):
        self.rfcontext.undo_push('move grabbed')

        self.sel_verts = self.rfcontext.get_selected_verts()
        self.vis_accel = self.rfcontext.get_vis_accel()
        self.vis_verts = self.rfcontext.accel_vis_verts
        Point_to_Point2D = self.rfcontext.Point_to_Point2D

        if not bmverts: bmverts = self.sel_verts
        self.bmverts = [(bmv, Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.vis_bmverts = [(bmv, Point_to_Point2D(bmv.co)) for bmv in self.vis_verts if bmv not in self.sel_verts]
        self.mousedown = self.rfcontext.actions.mouse
        self.defer_recomputing = defer_recomputing
        self._timer = self.actions.start_timer(120)

    @RFTool_Strokes.FSM_State('move')
    @RFTool_Strokes.dirty_when_done
    @profiler.function
    def move(self):
        released = self.rfcontext.actions.released
        if self.actions.pressed(self.move_done_pressed):
            self.defer_recomputing = False
            #self.mergeSnapped()
            return 'main'
        if self.actions.released(self.move_done_released):
            self.defer_recomputing = False
            #self.mergeSnapped()
            return 'main'
        if self.actions.pressed('cancel'):
            self.defer_recomputing = False
            self.rfcontext.undo_cancel()
            return 'main'

        # only update verts on timer events and when mouse has moved
        if not self.rfcontext.actions.timer: return
        if self.actions.mouse_prev == self.actions.mouse: return

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            xy_updated = xy + delta
            # check if xy_updated is "close" to any visible verts (in image plane)
            # if so, snap xy_updated to vert position (in image plane)
            if options['polypen automerge']:
                for bmv1,xy1 in self.vis_bmverts:
                    if (xy_updated - xy1).length < self.rfcontext.drawing.scale(10):
                        set2D_vert(bmv, xy1)
                        break
                else:
                    set2D_vert(bmv, xy_updated)
            else:
                set2D_vert(bmv, xy_updated)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)

    @RFTool_Strokes.FSM_State('move', 'exit')
    def move_exit(self):
        self._timer.done()

    @RFTool_Strokes.Draw('post2d')
    def draw_postpixel(self):
        bgl.glEnable(bgl.GL_BLEND)
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

