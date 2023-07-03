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

import bpy
import gpu
import math
import random
import itertools

from ..rftool import RFTool
from ..rfmesh.rfmesh import RFVert, RFEdge, RFFace
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_hidden  import RFWidget_Hidden_Factory

from ...addon_common.common import gpustate
from ...addon_common.common.maths import (
    Point, Vec, Normal, Direction,
    Point2D, Vec2D, Direction2D,
    Accel2D, clamp, Color, Plane,
)
from ...addon_common.common.debug import dprint
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.decorators import timed_call
from ...addon_common.common.drawing import CC_2D_LINE_STRIP, CC_2D_LINE_LOOP, CC_DRAW, DrawCallbacks
from ...addon_common.common.fsm import FSM
from ...addon_common.common.globals import Globals
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs

from ...config.options import options, themes


class Loops(RFTool):
    name        = 'Loops'
    description = 'Edge loops creation, shifting, and deletion'
    icon        = 'loops-icon.png'
    help        = 'loops.md'
    shortcut    = 'loops tool'
    quick_shortcut = 'loops quick'
    statusbar   = '{{insert}} Insert edge loop\t{{smooth edge flow}} Smooth edge flow'

    RFWidget_Default   = RFWidget_Default_Factory.create()
    RFWidget_Move      = RFWidget_Default_Factory.create(cursor='HAND')
    RFWidget_Crosshair = RFWidget_Default_Factory.create(cursor='CROSSHAIR')
    RFWidget_Hidden    = RFWidget_Hidden_Factory.create()

    @RFTool.on_init
    def init(self):
        self.rfwidgets = {
            'default': self.RFWidget_Default(self),
            'cut':     self.RFWidget_Crosshair(self),
            'hover':   self.RFWidget_Move(self),
            'hidden':  self.RFWidget_Hidden(self),
        }
        self.rfwidget = None
        self.previs_timer = self.actions.start_timer(120.0, enabled=False)

    @RFTool.on_mouse_move
    def mouse_move(self):
        tag_redraw_all('Loops mouse_move')

    @RFTool.on_reset
    def reset(self):
        if self.actions.using('loops quick'):
            self._fsm.force_set_state('quick')
            self.previs_timer.start()
        else:
            self.previs_timer.stop()

        self.nearest_edge = None
        self.set_next_state()
        self.hovering_edge = None
        self.hovering_sel_edge = None

    def filter_edge_selection(self, bme, no_verts_select=True, ratio=0.33):
        if bme.select:
            # edge is already selected
            return True
        bmv0, bmv1 = bme.verts
        s0, s1 = bmv0.select, bmv1.select
        if s0 and s1:
            # both verts are selected, so return True
            return True
        if not s0 and not s1:
            if no_verts_select:
                # neither are selected, so return True by default
                return True
            else:
                # return True if none are selected; otherwise return False
                return self.rfcontext.none_selected()
        # if mouse is at least a ratio of the distance toward unselected vert, return True
        if s1: bmv0, bmv1 = bmv1, bmv0
        p = self.actions.mouse
        p0 = self.rfcontext.Point_to_Point2D(bmv0.co)
        p1 = self.rfcontext.Point_to_Point2D(bmv1.co)
        v01 = p1 - p0
        l01 = v01.length
        d01 = v01 / l01
        dot = d01.dot(p - p0)
        return dot / l01 > ratio

    @FSM.on_state('quick', 'enter')
    def quick_enter(self):
        self.hovering_sel_edge = None
        self.set_widget('cut')

    @FSM.on_state('quick')
    def quick_main(self):
        if self.actions.pressed('cancel'):
            self.previs_timer.stop()
            return 'main'

        if self.actions.mousemove_stop:
            self.hovering_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'])
            if self.hovering_edge and not self.hovering_edge.is_valid: self.hovering_edge = None

        if self.hovering_edge and self.actions.pressed('quick insert'):
            return self.insert_edge_loop_strip()

    @FSM.on_state('main')
    def main(self):
        # if self.actions.mousemove: return  # ignore mouse moves

        if not self.actions.using('action', ignoredrag=True):
            # only update while not pressing action, because action includes drag, and
            # the artist might move mouse off selected edge before drag kicks in!
            self.hovering_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'])
            self.hovering_sel_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'], selected_only=True)
        if self.hovering_edge and not self.hovering_edge.is_valid: self.hovering_edge = None
        if self.hovering_sel_edge and not self.hovering_sel_edge.is_valid: self.hovering_sel_edge = None

        self.previs_timer.enable(self.actions.using_onlymods('insert'))
        if self.actions.using_onlymods('insert'):
            self.set_widget('cut')
        elif self.hovering_edge:
            self.set_widget('hover')
        else:
            self.set_widget('default')

        if self.handle_inactive_passthrough(): return

        if self.hovering_edge:
            #print(f'hovering edge {self.actions.using("action")} {self.hovering_edge} {self.hovering_sel_edge}')
            if self.actions.using('action'):
                #print('acting!')
                self.rfcontext.undo_push('slide edge loop/strip')
                if not self.hovering_sel_edge:
                    self.rfcontext.select_edge_loop(self.hovering_edge, supparts=False)
                    self.set_next_state()
                self.prep_edit()
                if not self.edit_ok:
                    self.rfcontext.undo_cancel()
                    return
                self.move_done_pressed = None
                self.move_done_released = 'action'
                self.move_cancelled = 'cancel'
                return 'slide'

        if self.actions.pressed('slide'):
            ''' slide edge loop or strip between neighboring edges '''
            self.rfcontext.undo_push('slide edge loop/strip')
            self.prep_edit()
            if not self.edit_ok:
                self.rfcontext.undo_cancel()
                return
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'slide'

        if self.actions.pressed('insert'):
            # insert edge loop / strip, select it, prep slide!
            return self.insert_edge_loop_strip()

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
                fn_filter_bmelem=self.filter_edge_selection,
                kwargs_select={'supparts': False},
                kwargs_deselect={'subparts': False},
            )

        if self.actions.pressed({'select smart', 'select smart add'}, unpress=False):
            sel_only = self.actions.pressed('select smart')
            self.actions.unpress()
            if not sel_only and not self.hovering_edge: return
            self.rfcontext.undo_push('select smart')
            if sel_only: self.rfcontext.deselect_all()
            if self.hovering_edge:
                self.rfcontext.select_edge_loop(self.hovering_edge, supparts=False, only=sel_only)
            return

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

    def insert_edge_loop_strip(self):
        if not self.edges_: return

        self.rfcontext.undo_push(f'insert edge {"loop" if self.edge_loop else "strip"}')

        # if quad strip is a loop, then need to connect first and last new verts
        is_looped = self.rfcontext.is_quadstrip_looped(self.nearest_edge)

        def split_face(v0, v1):
            nonlocal new_edges
            f0 = next(iter(v0.shared_faces(v1)), None)
            if not f0:
                self.rfcontext.alert_user('Something unexpected happened', level='warning')
                self.rfcontext.undo_cancel()
                return
            f1 = f0.split(v0, v1)
            new_edges.append(f0.shared_edge(f1))

        # create new verts by splitting all the edges
        new_verts, new_edges = [],[]

        def compute_percent():
            v0,v1 = self.nearest_edge.verts
            c0,c1 = self.rfcontext.Point_to_Point2D(v0.co),self.rfcontext.Point_to_Point2D(v1.co)
            a,b = c1 - c0, self.actions.mouse - c0
            adota = a.dot(a)
            if adota <= 0.0000001: return 0
            return a.dot(b) / adota;
        percent = compute_percent()

        for e,flipped in self.rfcontext.iter_quadstrip(self.nearest_edge):
            bmv0,bmv1 = e.verts
            if flipped: bmv0,bmv1 = bmv1,bmv0
            ne,nv = e.split()
            nv.co = bmv0.co + (bmv1.co - bmv0.co) * percent
            self.rfcontext.snap_vert(nv)
            if new_verts: split_face(new_verts[-1], nv)
            new_verts.append(nv)

        # connecting first and last new verts if quad strip is looped
        if is_looped and len(new_verts) > 2: split_face(new_verts[-1], new_verts[0])

        self.rfcontext.dirty()
        self.rfcontext.select(new_edges)

        self.prep_edit()
        if not self.edit_ok:
            self.rfcontext.undo_cancel()
            return
        self.move_done_pressed = None
        self.move_done_released = 'insert'
        self.move_cancelled = 'cancel'
        self.rfcontext.undo_push('slide edge loop/strip')
        return 'slide'

    @FSM.on_state('selectadd/deselect')
    def selectadd_deselect(self):
        if not self.actions.using(['select single','select single add']):
            self.rfcontext.undo_push('deselect')
            edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if edge and edge.select: self.rfcontext.deselect(edge)
            return 'main'
        delta = Vec2D(self.actions.mouse - self.mousedown)
        if delta.length > self.drawing.scale(5):
            self.rfcontext.undo_push('select add')
            return 'select'

    @FSM.on_state('select')
    def select(self):
        if not self.actions.using(['select single','select single add']):
            return 'main'
        bme,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
        if not bme or bme.select: return
        self.rfcontext.select(bme, supparts=False, only=False)

    @RFTool.on_target_change
    @RFTool.on_view_change
    @FSM.onlyinstate({'main', 'quick'})
    def update_next_state(self):
        self.set_next_state()

    @RFTool.on_mouse_stop
    @FSM.onlyinstate({'main', 'quick'})
    def update_next_state_mouse(self):
        self.set_next_state()
        tag_redraw_all('Loops mouse stop')

    @profiler.function
    def set_next_state(self):
        if self.actions.mouse is None: return
        self.edges_ = None

        self.nearest_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'])

        self.percent = 0
        self.edges = None

        if not self.nearest_edge: return

        self.edges,self.edge_loop = self.rfcontext.get_face_loop(self.nearest_edge)
        if not self.edges:
            # nearest, but no loop
            return
        vp0,vp1 = self.edges[0].verts
        cp0,cp1 = vp0.co,vp1.co
        def get(ep,ec):
            nonlocal cp0, cp1
            vc0,vc1 = ec.verts
            cc0,cc1 = vc0.co,vc1.co
            if (cp1-cp0).dot(cc1-cc0) < 0: cc0,cc1 = cc1,cc0
            cp0,cp1 = cc0,cc1
            return (ec,cc0,cc1)
        edge0 = self.edges[0]
        self.edges_ = [get(e0,e1) for e0,e1 in zip([self.edges[0]] + self.edges,self.edges)]
        c0,c1 = next(((c0,c1) for e,c0,c1 in self.edges_ if e == self.nearest_edge), (None,None))
        if c0 is None or c1 is None:
            # nearest_edge isn't in list?
            self.edges = None
            return
        c0,c1 = self.rfcontext.Point_to_Point2D(c0),self.rfcontext.Point_to_Point2D(c1)
        a,b = c1 - c0, self.actions.mouse - c0
        adota = a.dot(a)
        if adota <= 0.0000001:
            self.percent = 0
            self.edges = None
            return
        self.percent = a.dot(b) / adota;


    def prep_edit(self):
        self.edit_ok = False

        Point_to_Point2D = self.rfcontext.Point_to_Point2D

        sel_verts = self.rfcontext.get_selected_verts()
        sel_edges = self.rfcontext.get_selected_edges()

        if len(sel_verts) == 0 or len(sel_edges) == 0: return

        if True:
            # use line perpendicular to average edge direction
            vis_verts = self.rfcontext.visible_verts(verts=sel_verts)
            vis_edges = self.rfcontext.visible_edges(verts=vis_verts, edges=sel_edges)
            edge_d = None
            for edge in vis_edges:
                v0, v1 = edge.verts
                p0, p1 = Point_to_Point2D(v0.co), Point_to_Point2D(v1.co)
                if not p0 or not p1: continue
                v = Direction2D(p1 - p0)
                if not edge_d:
                    edge_d = v
                else:
                    if edge_d.dot(v) < 0: edge_d -= v
                    else: edge_d += v
            if not edge_d: return
            pts = [Point_to_Point2D(v.co) for v in vis_verts]
            pts = [pt for pt in pts if pt]
            if not pts: return
            self.slide_point = Point2D.average(pts)
            self.slide_direction = Direction2D((-edge_d.y, edge_d.x))
        else:
            # try to fit plane to data
            plane_o = Point.average(bmv.co for bmv in sel_verts)
            plane_n = Vec((0,0,0))
            for edge in sel_edges:
                v0, v1 = edge.verts
                en, ev = Normal(v0.normal + v1.normal), (v0.co - v1.co)
                perp = Direction(en.cross(ev))
                if plane_n.dot(perp) < 0: perp = -perp
                plane_n += perp
            plane_n = Normal(plane_n)
            o2d, on2d = Point_to_Point2D(plane_o), Point_to_Point2D(plane_o + plane_n)
            if not o2d or not on2d: return
            self.slide_direction = Direction2D(on2d - o2d)
            self.slide_point = o2d
        self.slide_vector = self.slide_direction * self.drawing.scale(40)

        # slide_data holds info on left,right vectors for moving
        slide_data = {}
        working = set(sel_edges)
        while working:
            crawl_set = { (next(iter(working)), 1) }
            current_strip = set()
            while crawl_set:
                bme,side = crawl_set.pop()
                v0,v1 = bme.verts
                co0,co1 = v0.co,v1.co
                if bme not in working: continue
                working.discard(bme)

                # add verts of edge if not already added
                for bmv in bme.verts:
                    if bmv in slide_data: continue
                    slide_data[bmv] = { 'left':[], 'orig':bmv.co, 'right':[], 'other':set(), 'flip': False }

                # process edge
                bmfl,bmfr = bme.get_left_right_link_faces()
                bmefln = bmfl.neighbor_edges(bme) if bmfl else None
                bmefrn = bmfr.neighbor_edges(bme) if bmfr else None
                bmel0,bmel1 = bmefln or (None, None)
                bmer0,bmer1 = bmefrn or (None, None)
                bmvl0 = bmel0.other_vert(v0) if bmel0 else None
                bmvl1 = bmel1.other_vert(v1) if bmel1 else None
                bmvr0 = bmer1.other_vert(v0) if bmer1 else None
                bmvr1 = bmer0.other_vert(v1) if bmer0 else None
                col0 = bmvl0.co if bmvl0 else None
                col1 = bmvl1.co if bmvl1 else None
                cor0 = bmvr0.co if bmvr0 else None
                cor1 = bmvr1.co if bmvr1 else None

                if   col0 and cor0: pass                # found left and right sides!
                elif col0: cor0 = co0 + (co0 - col0)    # cor0 is missing, guess
                elif cor0: col0 = co0 + (co0 - cor0)    # col0 is missing, guess
                else: continue                          # both col0 and cor0 are missing
                # instead of continuing, use edge perpendicular and length to guess at col0 and cor0
                if   col1 and cor1: pass                # found left and right sides!
                elif col1: cor1 = co1 + (co1 - col1)    # cor1 is missing, guess
                elif cor1: col1 = co1 + (co1 - cor1)    # col1 is missing, guess
                else: continue                          # both col1 and cor1 are missing
                # instead of continuing, use edge perpendicular and length to guess at col1 and cor1

                current_strip |= { v0, v1 }

                if side < 0:
                    # edge direction is reversed, so swap left and right sides
                    col0,cor0 = cor0,col0
                    col1,cor1 = cor1,col1

                if bmvl0 not in slide_data[v0]['other']:
                    slide_data[v0]['left'].append(col0-co0)
                    slide_data[v0]['other'].add(bmvl0)
                if bmvr0 not in slide_data[v0]['other']:
                    slide_data[v0]['right'].append(co0-cor0)
                    slide_data[v0]['other'].add(bmvr0)
                if bmvl1 not in slide_data[v1]['other']:
                    slide_data[v1]['left'].append(col1-co1)
                    slide_data[v1]['other'].add(bmvl1)
                if bmvr1 not in slide_data[v1]['other']:
                    slide_data[v1]['right'].append(co1-cor1)
                    slide_data[v1]['other'].add(bmvr1)

                # crawl to neighboring edges in strip/loop
                bmes_next = { bme.get_next_edge_in_strip(bmv) for bmv in bme.verts }
                for bme_next in bmes_next:
                    if bme_next not in working: continue    # note: None will skipped, too
                    v0_next,v1_next = bme_next.verts
                    side_next = side * (1 if (v1 == v0_next or v0 == v1_next) else -1)
                    crawl_set.add((bme_next, side_next))

            # check if we need to flip the strip
            def fn(bmv, side):
                if not self.rfcontext.is_visible(bmv.co, occlusion_test_override=True): return
                p0 = Point_to_Point2D(bmv.co)
                if not p0: return
                m = 1 if side == 'left' else -1
                for v in slide_data[bmv][side]:
                     p1 = Point_to_Point2D(bmv.co + v * m)
                     if p1: yield (p1 - p0)
            l = [v for bmv in current_strip for v in fn(bmv, 'left')]
            r = [v for bmv in current_strip for v in fn(bmv, 'right')]
            wrong = [v for v in l if self.slide_direction.dot(v) < 0] + [v for v in r if self.slide_direction.dot(v) > 0]
            if len(wrong) > (len(l) + len(r)) / 2:
                for bmv in current_strip:
                    slide_data[bmv]['flip'] = not slide_data[bmv]['flip']

        # nearest_vert,_ = self.rfcontext.nearest2D_vert(verts=sel_verts)
        # if not nearest_vert: return
        # if nearest_vert not in slide_data: return

        self.slide_data = slide_data
        self.mouse_down = self.actions.mouse
        self.percent_start = 0.0
        self.edit_ok = True

    @FSM.on_state('slide', 'enter')
    def slide_enter(self):
        self.previs_timer.start()
        self.rfcontext.set_accel_defer(True)
        self.set_widget('hidden' if options['hide cursor on tweak'] else 'hover')
        tag_redraw_all('entering slide')

    @FSM.on_state('slide')
    @profiler.function
    def slide(self):
        released = self.actions.released
        if self.move_done_pressed and self.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.actions.released(self.move_done_released, ignoremods=True):
            return 'main'
        if self.move_cancelled and self.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        if not self.actions.mousemove_stop: return
        # # only update loop on timer events and when mouse has moved
        # if not self.actions.timer: return
        # if self.actions.mouse_prev == self.actions.mouse: return

        mouse_delta = self.actions.mouse - self.mouse_down
        a,b = self.slide_vector, mouse_delta.project(self.slide_direction)
        percent = clamp(self.percent_start + a.dot(b) / a.dot(a), -1, 1)
        for bmv in self.slide_data.keys():
            mp = percent if not self.slide_data[bmv]['flip'] else -percent
            vecs = self.slide_data[bmv]['left' if mp > 0 else 'right']
            if len(vecs) == 0: continue
            co = self.slide_data[bmv]['orig']
            delta = sum((v * mp for v in vecs), Vec((0,0,0))) / len(vecs)
            bmv.co = co + delta
            self.rfcontext.snap_vert(bmv)

        self.rfcontext.dirty()

    @FSM.on_state('slide', 'exit')
    def slide_exit(self):
        self.previs_timer.stop()
        self.rfcontext.set_accel_defer(False)


    @DrawCallbacks.on_draw('post2d')
    @FSM.onlyinstate('slide')
    def draw_postview_slide(self):
        gpustate.blend('ALPHA')
        Globals.drawing.draw2D_line(
            self.slide_point + self.slide_vector * 1000,
            self.slide_point - self.slide_vector * 1000,
            (0.1, 1.0, 1.0, 1.0), color1=(0.1, 1.0, 1.0, 0.0),
            width=2, stipple=[2,2],
        )

    @DrawCallbacks.on_draw('post2d')
    @FSM.onlyinstate({'main', 'quick'})
    @profiler.function
    def draw_postview(self):
        if self.actions.is_navigating: return

        if self.rfcontext._nav or not self.nearest_edge: return
        if self._fsm.state != 'quick':
            if not (self.actions.ctrl and not self.actions.shift): return

        # draw new edge strip/loop
        Point_to_Point2D = self.rfcontext.Point_to_Point2D

        def draw(color):
            if not self.edges_: return
            if self.edge_loop:
                with Globals.drawing.draw(CC_2D_LINE_LOOP) as draw:
                    draw.color(color)
                    for _,c0,c1 in self.edges_:
                        c = c0 + (c1 - c0) * self.percent
                        draw.vertex(Point_to_Point2D(c))
            else:
                with Globals.drawing.draw(CC_2D_LINE_STRIP) as draw:
                    draw.color(color)
                    for _,c0,c1 in self.edges_:
                        c = c0 + (c1 - c0) * self.percent
                        draw.vertex(Point_to_Point2D(c))

        CC_DRAW.stipple(pattern=[4,4])
        CC_DRAW.point_size(5)
        CC_DRAW.line_width(2)

        gpustate.blend('ALPHA')
        gpu.state.depth_mask_set(True)
        gpustate.depth_test('LESS_EQUAL')
        draw(themes['new'])

