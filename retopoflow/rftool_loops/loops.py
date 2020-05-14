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
import bpy
import math
import random

from ..rftool import RFTool
from ..rfmesh.rfmesh import RFVert, RFEdge, RFFace

from ..rfwidgets.rfwidget_default import RFWidget_Default
from ..rfwidgets.rfwidget_move import RFWidget_Move
from ..rfwidgets.rfwidget_line import RFWidget_Line

from ...addon_common.common.maths import Point,Point2D,Vec2D,Vec,Accel2D,Direction2D, clamp, Color
from ...addon_common.common.debug import dprint
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.drawing import CC_2D_LINE_STRIP, CC_2D_LINE_LOOP, CC_DRAW
from ...addon_common.common.globals import Globals
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs

from ...config.options import options


class RFTool_Loops(RFTool):
    name        = 'Loops'
    description = 'Edge loops creation, shifting, and deletion'
    icon        = 'loops_32.png'
    help        = 'loops.md'
    shortcut    = 'loops tool'


class Loops(RFTool_Loops):
    @RFTool_Loops.on_init
    def init(self):
        self.rfwidgets = {
            'default': RFWidget_Default(self),
            'cut': RFWidget_Line(self),
            'hover': RFWidget_Move(self),
        }
        self.rfwidget = None

    @RFTool_Loops.on_mouse_move
    def mouse_move(self):
        tag_redraw_all('Loops mouse_move')

    @RFTool_Loops.on_reset
    def reset(self):
        self.nearest_edge = None
        self.set_next_state()
        self.hovering_edge = None

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


    @RFTool_Loops.FSM_State('main')
    def main(self):
        if not self.actions.using('action', ignoredrag=True):
            # only update while not pressing action, because action includes drag, and
            # the artist might move mouse off selected edge before drag kicks in!
            self.hovering_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'])
            self.hovering_sel_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'], select_only=True)

        if self.hovering_edge:
            self.rfwidget = self.rfwidgets['hover']
        elif self.actions.using_onlymods('insert'):
            self.rfwidget = self.rfwidgets['cut']
        else:
            self.rfwidget = self.rfwidgets['default']

        if self.hovering_edge:
            if self.rfcontext.actions.pressed({'action', 'action alt0'}, unpress=False):
                self.rfcontext.undo_push('slide edge loop/strip')
                if not self.hovering_sel_edge:
                    only = self.rfcontext.actions.pressed('action')
                    self.rfcontext.select_edge_loop(self.hovering_edge, supparts=False, only=only)
                    self.set_next_state()
                self.prep_edit()
                if not self.edit_ok:
                    self.rfcontext.undo_cancel()
                    return
                self.move_done_pressed = None
                self.move_done_released = 'action'
                self.move_cancelled = 'cancel'
                return 'slide'

        if self.rfcontext.actions.pressed('slide'):
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

        if self.rfcontext.actions.pressed('insert'):
            # insert edge loop / strip, select it, prep slide!
            if not self.edges_: return

            self.rfcontext.undo_push('insert edge %s' % ('loop' if self.edge_loop else 'strip'))

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
                a,b = c1 - c0, self.rfcontext.actions.mouse - c0
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
            self.move_done_released = ['insert', 'insert alt0']
            self.move_cancelled = 'cancel'
            self.rfcontext.undo_push('slide edge loop/strip')
            return 'slide'

        if self.rfcontext.actions.pressed({'select paint'}):
            print('Loops selection painting')
            return self.rfcontext.setup_selection_painting(
                'edge',
                fn_filter_bmelem=self.filter_edge_selection,
                kwargs_select={'supparts': False},
                kwargs_deselect={'subparts': False},
            )

        if self.rfcontext.actions.pressed(['select smart', 'select smart add'], unpress=False):
            sel_only = self.rfcontext.actions.pressed('select smart')
            self.rfcontext.actions.unpress()
            self.rfcontext.undo_push('select smart')
            edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if not edge:
                if sel_only: self.rfcontext.deselect_all()
                return
            self.rfcontext.select_edge_loop(edge, supparts=False, only=sel_only)
            return

        if self.rfcontext.actions.pressed('select single add'):
            edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if not edge: return
            if edge.select:
                self.mousedown = self.rfcontext.actions.mouse
                return 'selectadd/deselect'
            return 'select'

        if self.rfcontext.actions.pressed('select single'):
            self.rfcontext.undo_push('select')
            self.rfcontext.deselect_all()
            return 'select'



    @RFTool_Loops.FSM_State('selectadd/deselect')
    def selectadd_deselect(self):
        if not self.rfcontext.actions.using(['select single','select single add']):
            self.rfcontext.undo_push('deselect')
            edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if edge and edge.select: self.rfcontext.deselect(edge)
            return 'main'
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        if delta.length > self.drawing.scale(5):
            self.rfcontext.undo_push('select add')
            return 'select'

    @RFTool_Loops.FSM_State('select')
    def select(self):
        if not self.rfcontext.actions.using(['select single','select single add']):
            return 'main'
        bme,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
        if not bme or bme.select: return
        self.rfcontext.select(bme, supparts=False, only=False)

    @RFTool_Loops.on_target_change
    @RFTool_Loops.on_view_change
    @RFTool_Loops.on_mouse_move
    @RFTool_Loops.FSM_OnlyInState('main')
    def update_next_state(self):
        self.set_next_state()

    @profiler.function
    def set_next_state(self):
        if self.actions.mouse is None: return
        self.edges_ = None

        self.nearest_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)

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
        a,b = c1 - c0, self.rfcontext.actions.mouse - c0
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

        # slide_data holds info on left,right vectors for moving
        slide_data = {}
        working = set(sel_edges)
        while working:
            nearest_edge,_ = self.rfcontext.nearest2D_edge(edges=working)
            crawl_set = { (nearest_edge, 1) }
            while crawl_set:
                bme,side = crawl_set.pop()
                v0,v1 = bme.verts
                co0,co1 = v0.co,v1.co
                if bme not in working: continue
                working.discard(bme)

                # add verts of edge if not already added
                for bmv in bme.verts:
                    if bmv in slide_data: continue
                    slide_data[bmv] = { 'left':[], 'orig':bmv.co, 'right':[], 'other':set() }

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
                if col0 and cor0: pass              # found left and right sides!
                elif col0: cor0 = co0 + (co0 - col0)  # cor0 is missing, guess
                elif cor0: col0 = co0 + (co0 - cor0)  # col0 is missing, guess
                else:                               # both col0 and cor0 are missing
                    # use edge perpendicular and length to guess at col0 and cor0
                    #assert False, "XXX: Not implemented yet!"
                    continue
                if col1 and cor1: pass              # found left and right sides!
                elif col1: cor1 = co1 + (co1 - col1)  # cor1 is missing, guess
                elif cor1: col1 = co1 + (co1 - cor1)  # col1 is missing, guess
                else:                               # both col1 and cor1 are missing
                    # use edge perpendicular and length to guess at col1 and cor1
                    #assert False, "XXX: Not implemented yet!"
                    continue
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

        # find nearest selected edge
        #   vector is perpendicular to edge
        #   tangent is vector with unit length
        nearest_edge,_ = self.rfcontext.nearest2D_edge(edges=sel_edges)
        if not nearest_edge: return
        bmv0,bmv1 = nearest_edge.verts
        co0,co1 = self.rfcontext.Point_to_Point2D(bmv0.co),self.rfcontext.Point_to_Point2D(bmv1.co)
        diff = co1 - co0
        if diff.length_squared <= 0.0000001:
            # nearest edge has no length!
            return
        self.tangent = Direction2D((-diff.y, diff.x))
        self.vector = self.tangent * self.drawing.scale(40)
        if self.vector.length_squared <= 0.0000001:
            # nearest edge has no length!
            return
        self.slide_data = slide_data
        self.mouse_down = self.rfcontext.actions.mouse
        self.percent_start = 0.0
        self.edit_ok = True

    @RFTool_Loops.FSM_State('slide', 'enter')
    def slide_enter(self):
        self._timer = self.actions.start_timer(120)

    @RFTool_Loops.FSM_State('slide')
    @RFTool_Loops.dirty_when_done
    @profiler.function
    def slide(self):
        released = self.rfcontext.actions.released
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        # only update loop on timer events and when mouse has moved
        if not self.rfcontext.actions.timer: return
        if self.actions.mouse_prev == self.actions.mouse: return

        mouse_delta = self.rfcontext.actions.mouse - self.mouse_down
        a,b = self.vector, mouse_delta.project(self.tangent)
        percent = clamp(self.percent_start + a.dot(b) / a.dot(a), -1, 1)
        for bmv in self.slide_data.keys():
            vecs = self.slide_data[bmv]['left' if percent > 0 else 'right']
            if len(vecs) == 0: continue
            co = self.slide_data[bmv]['orig']
            delta = sum((v*percent for v in vecs), Vec((0,0,0))) / len(vecs)
            bmv.co = co + delta
            self.rfcontext.snap_vert(bmv)

    @RFTool_Loops.FSM_State('slide', 'exit')
    def slide_exit(self):
        self._timer.done()


    @RFTool_Loops.Draw('post2d')
    @RFTool_Loops.FSM_OnlyInState('main')
    @profiler.function
    def draw_postview(self):
        if self.rfcontext._nav or not self.nearest_edge: return
        if not (self.rfcontext.actions.ctrl and not self.rfcontext.actions.shift): return

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

        #self.drawing.point_size(5.0)
        #self.drawing.line_width(2.0)
        # bgl.glDisable(bgl.GL_CULL_FACE)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDepthMask(bgl.GL_FALSE)
        bgl.glDepthRange(0, 0.9990)     # squeeze depth just a bit

        # draw above
        bgl.glEnable(bgl.GL_DEPTH_TEST)
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        draw(Color((0.15, 1.00, 0.15, 1.00)))

        # draw below
        bgl.glDepthFunc(bgl.GL_GREATER)
        draw(Color((0.15, 1.00, 0.15, 0.25)))

        # bgl.glEnable(bgl.GL_CULL_FACE)
        bgl.glDepthMask(bgl.GL_TRUE)
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthRange(0, 1)

