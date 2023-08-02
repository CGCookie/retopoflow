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
    clamp, Color, Plane,
)
from ...addon_common.common.debug import dprint
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.decorators import timed_call
from ...addon_common.common.drawing import CC_2D_LINE_STRIP, CC_2D_LINE_LOOP, CC_DRAW, DrawCallbacks
from ...addon_common.common.fsm import FSM
from ...addon_common.common.globals import Globals
from ...addon_common.common.profiler import profiler
from ...addon_common.common.timerhandler import StopwatchHandler
from ...addon_common.common.utils import iter_pairs

from ...config.options import options, themes


class Loops_Insert():
    @RFTool.on_quickswitch_start
    def quickswitch_start(self):
        self.quickswitch = True
        self._fsm.force_set_state('insert')

    @FSM.on_state('insert', 'enter')
    def modal_previs_enter(self):
        self.set_widget('cut')
        self.rfcontext.fast_update_timer.enable(True)

        if not self.quickswitch:
            self.insert_action = lambda: self.actions.pressed('insert')
            self.insert_done   = lambda: not self.actions.using_onlymods('insert')
        else:
            self.insert_action = lambda: self.actions.pressed('quick insert')
            self.insert_done   = lambda: self.actions.pressed('cancel')


    @FSM.on_state('insert')
    def modal_previs(self):
        if self.handle_inactive_passthrough():
            return

        if self.insert_action() and self.nearest_edge:
            # insert edge loop / strip, select it, prep slide!
            return self.insert_edge_loop_strip()

        if self.insert_done():
            return 'main'

    @FSM.on_state('insert', 'exit')
    def modal_previs_exit(self):
        self.rfcontext.fast_update_timer.enable(False)


    @RFTool.on_events('mouse move', 'target change', 'view change')
    @RFTool.not_while_navigating
    @RFTool.once_per_frame
    @FSM.onlyinstate('insert')
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
            r'''
                       nearest_edge is not in list, because
                  +--  this diamond quad causes problems!
                  |
                  V
            O-----O-----O
            |    / \    |
            O---O   O---O
               / \ / \
              /   O   \
             /   / \   \
            O---O   O---O
             \   \ /   /
              \   O   /
               \  |  /
                \ | /
                 \|/
                  O
            '''
            self.edges = None
            self.edges_ = None
            return
        c0,c1 = self.rfcontext.Point_to_Point2D(c0),self.rfcontext.Point_to_Point2D(c1)
        a,b = c1 - c0, self.actions.mouse - c0
        adota = a.dot(a)
        if adota <= 0.0000001:
            self.percent = 0
            self.edges = None
            self.edges_ = None
            return
        self.percent = a.dot(b) / adota

        tag_redraw_all('Loops next state set')



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


    @DrawCallbacks.on_draw('post2d')
    @RFTool.not_while_navigating
    @FSM.onlyinstate('insert')
    def draw_postview(self):
        if not self.nearest_edge: return

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
        gpustate.depth_mask(True)
        gpustate.depth_test('LESS_EQUAL')
        draw(themes['new'])

