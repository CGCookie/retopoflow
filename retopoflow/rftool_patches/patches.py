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

import os
import math
from itertools import chain

import bgl

from ..rftool import RFTool
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory

from ...addon_common.common.drawing import (
    CC_DRAW,
    CC_2D_POINTS,
    CC_2D_LINES, CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES, CC_2D_TRIANGLE_FAN,
)
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import (
    Point, Vec, Direction,
    Point2D, Vec2D,
    mid,
)
from ...addon_common.common.globals import Globals
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.boundvar import BoundInt

from ...config.options import options, themes, visualization


class RFTool_Patches(RFTool):
    name        = 'Patches'
    description = 'Fill holes in your topology'
    icon        = 'patches-icon.png'
    help        = 'patches.md'
    shortcut    = 'patches tool'
    statusbar   = '{{action alt1}} Toggle vertex as a corner\t{{increase count}} Increase segments\t{{decrease count}} Decrease Segments\t{{fill}} Create patch'
    ui_config   = 'patches_options.html'

class Patches_RFWidgets:
    RFWidget_Default = RFWidget_Default_Factory.create()
    RFWidget_Move = RFWidget_Default_Factory.create('HAND')

    def init_rfwidgets(self):
        self.rfwidgets = {
            'default': self.RFWidget_Default(self),
            'hover': self.RFWidget_Move(self),
        }
        self.rfwidget = None

class Patches(RFTool_Patches, Patches_RFWidgets):
    @RFTool_Patches.on_init
    def init(self):
        self.init_rfwidgets()
        self.corners = {}
        self.crosses = None
        self._var_angle = BoundInt('''options['patches angle']''', min_value=0, max_value=180)
        self._var_crosses = BoundInt('''self.var_crosses''', min_value=1, max_value=500)

    @RFTool_Patches.on_reset
    def reset(self):
        self.defer_recomputing = False

    @property
    def var_crosses(self):
        if self.crosses is None: return 1
        return self.crosses - 1
    @var_crosses.setter
    def var_crosses(self, v):
        nv = max(1, int(v)+1)
        if self.crosses == nv: return
        self.crosses = nv
        self._recompute()

    def update_ui(self):
        self._var_crosses.disabled = (self.crosses is None)

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

    @RFTool_Patches.on_reset
    @RFTool_Patches.on_target_change
    def update(self):
        if self.defer_recomputing: return
        self.rfcontext.get_vis_accel()
        self.crosses = None
        self._recompute()
        self.update_ui()

    @RFTool_Patches.FSM_State('main')
    def main(self):
        self.hovering_sel_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'], selected_only=True)
        self.hovering_sel_face,_ = self.rfcontext.accel_nearest2D_face(max_dist=options['action dist'], selected_only=True)

        if self.hovering_sel_edge or self.hovering_sel_face:
            self.rfwidget = self.rfwidgets['hover']
        else:
            self.rfwidget = self.rfwidgets['default']

        for rfwidget in self.rfwidgets.values():
            if self.rfwidget == rfwidget: continue
            if rfwidget.inactive_passthrough():
                self.rfwidget = rfwidget
                return

        if self.hovering_sel_edge or self.hovering_sel_face:
            if self.actions.pressed('action'):
                self.move_done_pressed = None
                self.move_done_released = 'action'
                self.move_cancelled = 'cancel'
                return 'move'

        if self.rfcontext.actions.pressed('action alt1'):
            vert,_ = self.rfcontext.accel_nearest2D_vert(max_dist=10)
            if not vert or not vert.select: return
            if vert in self.shapes['corners']:
                self.corners[vert] = False
            else:
                self.corners[vert] = not self.corners.get(vert, False)
            self.update()
            return

        if self.rfcontext.actions.pressed('fill'):
            self.fill_patch()
            return

        if self.rfcontext.actions.pressed('grab'):
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move'

        if self.rfcontext.actions.pressed('increase count'):
            if self.crosses is not None:
                self.crosses += 1
                self._recompute()

        if self.rfcontext.actions.pressed('decrease count'):
            if self.crosses is not None and self.crosses > 2:
                self.crosses -= 1
                self._recompute()

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
                selecting=not sel_only,
                deselect_all=sel_only,
                fn_filter_bmelem=self.filter_edge_selection,
                kwargs_select={'supparts': False},
                kwargs_deselect={'subparts': False},
            )

        if self.actions.pressed({'select single', 'select single add'}, unpress=False):
            sel_only = self.actions.pressed('select single')
            hovering_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'])
            if not sel_only and not hovering_edge: return
            self.rfcontext.undo_push('select')
            if sel_only: self.rfcontext.deselect_all()
            if not hovering_edge: return
            if sel_only or hovering_edge.select == False:
                self.rfcontext.select(hovering_edge, supparts=False, only=False)
            else:
                self.rfcontext.deselect(hovering_edge)
            return

        if self.rfcontext.actions.pressed({'select smart', 'select smart add'}, unpress=False):
            sel_only = self.rfcontext.actions.pressed('select smart')
            self.rfcontext.actions.unpress()

            self.rfcontext.undo_push('select smart')
            selectable_edges = [e for e in self.rfcontext.visible_edges() if len(e.link_faces) < 2]
            edge,_ = self.rfcontext.nearest2D_edge(edges=selectable_edges, max_dist=options['action dist'])
            if not edge: return
            #self.rfcontext.select_inner_edge_loop(edge, supparts=False, only=sel_only)
            self.rfcontext.select_edge_loop(edge, supparts=False, only=sel_only)

    @RFTool_Patches.FSM_State('move', 'enter')
    def move_enter(self):
        self.sel_verts = self.rfcontext.get_selected_verts()
        self.vis_accel = self.rfcontext.get_vis_accel()
        self.vis_verts = self.rfcontext.accel_vis_verts
        Point_to_Point2D = self.rfcontext.Point_to_Point2D

        self.bmverts = [(bmv, Point_to_Point2D(bmv.co)) for bmv in self.sel_verts]
        self.vis_bmverts = [(bmv, Point_to_Point2D(bmv.co)) for bmv in self.vis_verts if bmv and bmv not in self.sel_verts]
        self.mousedown = self.rfcontext.actions.mouse
        self.defer_recomputing = True

        self.rfcontext.undo_push('move grabbed')

        self.rfcontext.set_accel_defer(True)

        self._timer = self.actions.start_timer(120)

    @RFTool_Patches.FSM_State('move')
    def move_main(self):
        released = self.rfcontext.actions.released
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            self.defer_recomputing = False
            self.update()
            return 'main'
        if self.actions.released(self.move_done_released, ignoredrag=True):
            self.defer_recomputing = False
            self.update()
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.defer_recomputing = False
            self.rfcontext.undo_cancel()
            return 'main'

        if not self.actions.mousemove_stop: return
        # if not self.rfcontext.actions.timer: return
        # if self.actions.mouse_prev == self.actions.mouse: return
        # # if not self.actions.mousemove: return

        delta = Vec2D(self.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            xy_updated = xy + delta
            set2D_vert(bmv, xy_updated)
            # # check if xy_updated is "close" to any visible verts (in image plane)
            # # if so, snap xy_updated to vert position (in image plane)
            # if options['polypen automerge']:
            #     for bmv1,xy1 in self.vis_bmverts:
            #         if (xy_updated - xy1).length < self.rfcontext.drawing.scale(10):
            #             set2D_vert(bmv, xy1)
            #             break
            #     else:
            #         set2D_vert(bmv, xy_updated)
            # else:
            #     set2D_vert(bmv, xy_updated)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)

        self.rfcontext.dirty()

    @RFTool_Patches.FSM_State('move', 'exit')
    def move_exit(self):
        self._timer.done()
        self.rfcontext.set_accel_defer(False)

    @RFTool.dirty_when_done
    def fill_patch(self):
        if not self.previz: return

        new_vert = self.rfcontext.new_vert_point
        new_face = self.rfcontext.new_face

        self.rfcontext.undo_push('fill')
        for previz in self.previz:
            verts,faces = previz['verts'],previz['faces']
            verts = [(new_vert(v) if type(v) is Point else v) for v in verts]
            for face in faces: new_face([verts[iv] for iv in face])

        self.update()



    def draw_previz(self, previz, poly_alpha=0.2):
        point_to_point2D = self.rfcontext.Point_to_Point2D
        line_color = themes['new']
        poly_color = [line_color[0], line_color[1], line_color[2], line_color[3] * poly_alpha]

        verts = [point_to_point2D(v if type(v) is Point else v.co) for v in previz['verts']]

        with Globals.drawing.draw(CC_2D_LINES) as draw:
            draw.color(line_color)
            for i0,i1 in previz['edges']:
                v0,v1 = verts[i0],verts[i1]
                if v0 and v1:
                    draw.vertex(v0)
                    draw.vertex(v1)

        with Globals.drawing.draw(CC_2D_TRIANGLES) as draw:
            draw.color(poly_color)
            for f in previz['faces']:
                coords = [verts[i] for i in f]
                if all(coords):
                    co0 = coords[0]
                    for i in range(1, len(coords)-1):
                        draw.vertex(co0)
                        draw.vertex(coords[i])
                        draw.vertex(coords[i+1])

    @RFTool_Patches.Draw('post2d')
    @RFTool_Patches.FSM_OnlyInState('main')
    def draw_postpixel(self):
        point_to_point2D = self.rfcontext.Point_to_Point2D
        self.rfcontext.drawing.set_font_size(12)

        def get_pos(strips):
            #xy = max((point_to_point2D(bmv.co) for strip in strips for bme in strip for bmv in bme.verts), key=lambda xy:xy.y+xy.x/2)
            bmvs = [bmv for strip in strips for bme in strip for bmv in bme.verts]
            vs = [point_to_point2D(bmv.co) for bmv in bmvs]
            vs = [Vec2D(v) for v in vs if v]
            if not vs: return None
            xy = sum(vs, Vec2D((0,0))) / len(vs)
            return xy+Vec2D((2,14))
        def text_draw2D(s, strips):
            if not strips: return
            xy = get_pos(strips)
            if not xy: return
            self.rfcontext.drawing.text_draw2D(s, xy, color=(1,1,0,1), dropshadow=(0,0,0,0.5))

        for rect_strips in self.shapes['rect']:
            c0,c1,c2,c3 = map(len, rect_strips)
            if c0==c2 and c1==c3:
                s = 'rect: %dx%d' % (c0,c1)
                text_draw2D(s, rect_strips)
            else:
                for strip in rect_strips:
                    s = 'bad rect: %d' % len(strip)
                    text_draw2D(s, [strip])

        for I_strips in self.shapes['I']:
            c = len(I_strips[0])
            s = 'I: %d' % (c,)
            text_draw2D(s, I_strips)
        for L_strips in self.shapes['L']:
            c0,c1 = map(len, L_strips)
            s = 'L: %dx%d' % (c0,c1)
            text_draw2D(s, L_strips)
        for C_strips in self.shapes['C']:
            c0,c1,c2 = map(len, C_strips)
            if c0==c2:
                s = 'C: %dx%d' % (c0,c1)
                text_draw2D(s, C_strips)
            else:
                for strip in C_strips:
                    s = 'bad C: %d' % len(strip)
                    text_draw2D(s, [strip])

        bgl.glEnable(bgl.GL_BLEND)
        CC_DRAW.stipple(pattern=[4,4])
        CC_DRAW.point_size(4)
        CC_DRAW.line_width(2)

        for previz in self.previz: self.draw_previz(previz)

        CC_DRAW.stipple()
        bgl.glEnable(bgl.GL_BLEND)
        CC_DRAW.point_size(visualization['point size highlight'])
        with Globals.drawing.draw(CC_2D_POINTS) as draw:
            draw.color(visualization['point color highlight'])
            for corner in self.shapes['corners']:
                p = point_to_point2D(corner.co)
                if p: draw.vertex(p)



    def _clear_shapes(self):
        self.shapes = {
            'O':    [],     # special loop
            'eye':  [],     # loops
            'tri':  [],
            'rect': [],
            'ngon': [],
            'C':    [],     # strings
            'L':    [],
            'I':    [],
            'else': [],
            'corners': [],
        }
        self.previz = []

    def _recompute(self):
        min_angle = options['patches angle']
        def nearest_sources_Point(p):
            p,n,i,d = self.rfcontext.nearest_sources_Point(p)
            return self.rfcontext.clamp_point_to_symmetry(p)

        self._clear_shapes()
        # remove old corners that are no longer valid or selected
        self.corners = {v:corner for (v, corner) in self.corners.items() if v.is_valid and v.select}

        ##############################################
        # find edges that could be part of a strip
        edges = set(e for e in self.rfcontext.get_selected_edges() if len(e.link_faces) < 2)


        ###################
        # find strips
        remaining_edges = set(edges)
        strips = []
        neighbors = { e:[] for e in edges }
        while remaining_edges:
            strip = set()
            working = { next(iter(remaining_edges)) }
            while working:
                edge = working.pop()
                strip.add(edge)
                remaining_edges.remove(edge)
                v0,v1 = edge.verts
                for e in chain(v0.link_edges, v1.link_edges):
                    if e not in remaining_edges: continue
                    bmv1 = edge.shared_vert(e)
                    if self.corners.get(bmv1, False): continue
                    bmv0 = edge.other_vert(bmv1)
                    bmv2 = e.other_vert(bmv1)
                    d10 = Direction(bmv0.co-bmv1.co)
                    d12 = Direction(bmv2.co-bmv1.co)
                    angle = math.degrees(math.acos(mid(-1,1,d10.dot(d12))))
                    if self.corners.get(bmv1, True) and angle < min_angle: continue
                    neighbors[edge].append(e)
                    neighbors[e].append(edge)
                    working.add(e)
            strips += [strip]


        ##############################################
        # order strips to find corners and O-shapes
        nstrips = []
        corners = dict()
        for edges in strips:
            if len(edges) == 1:
                # single edge in strip
                edge = next(iter(edges))
                strip = [edge]
                v0,v1 = edge.verts
                nstrips.append(strip)
                corners[v0] = corners.get(v0, []) + [strip]
                corners[v1] = corners.get(v1, []) + [strip]
                continue
            end_edges = [edge for edge in edges if len(neighbors[edge])==1]
            if not end_edges:
                # could not find corners: O-shaped!
                strip = [next(iter(edges))]
                strip.append(next(iter(neighbors[strip[0]])))
                remaining_edges = set(edges) - set(strip)
                isbad = False
                while remaining_edges:
                    next_edges = [edge for edge in neighbors[strip[-1]] if edge in remaining_edges]
                    if len(next_edges) != 1:
                        # unexpected number of edges found!
                        isbad = True
                        break
                    strip.append(next_edges[0])
                    remaining_edges.remove(next_edges[0])
                if isbad: continue
                self.shapes['O'].append(strip)
                continue
            strip = [end_edges[0]]
            remaining_edges = set(edges) - set(strip)
            isbad = False
            while remaining_edges:
                next_edges = [edge for edge in neighbors[strip[-1]] if edge in remaining_edges]
                if len(next_edges) != 1:
                    # unexpected number of edges found
                    # see GitHub issue #481 (https://github.com/CGCookie/retopoflow/issues/481)
                    isbad = True
                    break
                strip.append(next_edges[0])
                remaining_edges.remove(next_edges[0])
            if isbad: continue
            v0 = strip[0].other_vert(strip[0].shared_vert(strip[1]))
            v1 = strip[-1].other_vert(strip[-1].shared_vert(strip[-2]))
            corners[v0] = corners.get(v0, []) + [strip]
            corners[v1] = corners.get(v1, []) + [strip]
            nstrips.append(strip)
        strips = nstrips


        ##################################################################
        # find all strings (I,L,C,else) and loops (cat,tri,rect,ngon)
        # note: all corner verts with one strip are *not* in a loop

        # ignore corners with 3+ strips
        ignore_corners = {c for c in corners if len(corners[c]) > 2}

        def align_strips(strips):
            ''' make sure that the edges at the end of adjacent strips share a vertex '''
            if len(strips) == 1: return strips
            strip0,strip1 = strips[:2]
            if strip0[0].share_vert(strip1[0]) or strip0[0].share_vert(strip1[-1]): strip0.reverse()
            assert strip0[-1].share_vert(strip1[0]) or strip0[-1].share_vert(strip1[-1])
            for strip0,strip1 in zip(strips[:-1],strips[1:]):
                if strip1[-1].share_vert(strip0[-1]): strip1.reverse()
                assert strip1[0].share_vert(strip0[-1])
            return strips

        remaining_corners = set(corners.keys())
        string_corners = set()
        loop_corners = set()
        strings_strips = list()
        loops_strips = list(self.shapes['O'])

        # find strips
        while remaining_corners:
            c = next((c for c in remaining_corners if len(corners[c]) == 1), None)
            if not c: break
            remaining_corners.remove(c)
            string_corners.add(c)
            string_strips = [corners[c][0]]
            ignore = c in ignore_corners
            while True:
                s = string_strips[-1]
                c = next((c for c in remaining_corners if s in corners[c]), None)
                if not c: break
                ignore |= c in ignore_corners
                remaining_corners.remove(c)
                string_corners.add(c)
                if len(corners[c]) != 2: break
                ns = next(ns for ns in corners[c] if ns != s)
                string_strips.append(ns)
            string_strips = align_strips(string_strips)
            if ignore: continue
            strings_strips.append(string_strips)
            if len(string_strips) == 1:
                self.shapes['I'].append(string_strips)
            elif len(string_strips) == 2:
                self.shapes['L'].append(string_strips)
            elif len(string_strips) == 3:
                self.shapes['C'].append(string_strips)
            else:
                self.shapes['else'].append(string_strips)

        # find loops
        while remaining_corners:
            c = next(iter(remaining_corners))
            remaining_corners.remove(c)
            loop_corners.add(c)
            loop_strips = [corners[c][0]]
            ignore = c in ignore_corners
            while True:
                s = loop_strips[-1]
                c = next((c for c in remaining_corners if s in corners[c]), None)
                if not c: break
                ignore |= c in ignore_corners
                remaining_corners.remove(c)
                loop_corners.add(c)
                ns = next((ns for ns in corners[c] if ns != s), None)
                if not ns: break
                loop_strips.append(ns)
            loop_strips = align_strips(loop_strips)
            if ignore: continue
            # make sure loop is actually closed
            s0,s1 = loop_strips[0],loop_strips[-1]
            shared_verts = sum(1 if e0.share_vert(e1) else 0 for e0 in s0 for e1 in s1)
            if len(loop_strips) == 2 and shared_verts != 2: continue
            if len(loop_strips) > 2 and shared_verts != 1: continue
            loops_strips.append(loop_strips)
            if len(loop_strips) == 2:
                self.shapes['eye'].append(loop_strips)
            elif len(loop_strips) == 3:
                self.shapes['tri'].append(loop_strips)
            elif len(loop_strips) == 4:
                self.shapes['rect'].append(loop_strips)
            else:
                self.shapes['ngon'].append(loop_strips)

        self.shapes['corners'] = (string_corners | loop_corners)

        ###################
        # generate previz

        def get_verts(strip, rev=False):
            if len(strip) == 1: return list(strip[0].verts)
            bmvs = [strip[0].nonshared_vert(strip[1])]
            bmvs += [e0.shared_vert(e1) for e0,e1 in zip(strip[:-1], strip[1:])]
            bmvs += [strip[-1].nonshared_vert(strip[-2])]
            if rev: bmvs.reverse()
            return bmvs

        # rect
        for shape in self.shapes['rect']:
            s0,s1,s2,s3 = shape
            if len(s0) != len(s2) or len(s1) != len(s3): continue   # invalid rect
            sv0,sv1,sv2,sv3 = get_verts(s0),get_verts(s1),get_verts(s2,True),get_verts(s3,True)
            l0,l1 = len(sv0),len(sv1)

            # make sure each strip is in the correct order
            if sv0[-1] not in sv1: sv0.reverse()
            if sv1[-1] not in sv2: sv1.reverse()
            if sv2[-1] not in sv1: sv2.reverse()
            if sv3[-1] not in sv2: sv3.reverse()

            verts,edges,faces = [],[],[]
            for i in range(l0):
                l,r = sv0[i],sv2[i]
                for j in range(l1):
                    t,b = sv1[j],sv3[j]
                    if   i == 0:    verts += [b]
                    elif i == l0-1: verts += [t]
                    elif j == 0:    verts += [l]
                    elif j == l1-1: verts += [r]
                    else:
                        pi,pj = i / (l0-1), j / (l1-1)
                        lr = Vec(l.co)*(1-pj) + Vec(r.co)*pj
                        tb = Vec(b.co)*(1-pi) + Vec(t.co)*pi
                        verts += [nearest_sources_Point((lr+tb)/2.0)]
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(1,l0-1) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1,l1-1) for i in range(l0-1)]
            faces += [( (i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1) ) for i in range(l0-1) for j in range(l1-1)]

            self.previz += [{ 'type': 'rect', 'data': shape, 'verts': verts, 'edges': edges, 'faces': faces }]

        for shape in self.shapes['L']:
            s0,s1 = shape
            sv0,sv1 = get_verts(s0),get_verts(s1)
            l0,l1 = len(sv0),len(sv1)

            # make sure each strip is in the correct order
            if sv0[-1] not in sv1: sv0.reverse()
            if sv1[0] not in sv0: sv1.reverse()

            symmetry0 = self.rfcontext.get_point_symmetry(sv0[0].co)
            symmetry1 = self.rfcontext.get_point_symmetry(sv1[-1].co)
            if symmetry0 and symmetry1:
                # both are at symmetry... artist is trying to fill a triangle
                # we cannot do that, yet, so bail!
                continue

            off0,off1 = sv0[-1].co-sv0[0].co, sv1[-1].co-sv1[0].co

            verts,edges,faces = [],[],[]
            for i in range(l0):
                for j in range(l1):
                    if   i == l0-1: verts += [sv1[j]]
                    elif j == 0:    verts += [sv0[i]]
                    else:
                        l,r = sv0[i].co,sv0[i].co+off1
                        t,b = sv1[j].co,sv1[j].co-off0
                        pi,pj = i / (l0-1), j / (l1-1)
                        lr = Vec(l)*(1-pj) + Vec(r)*pj
                        tb = Vec(b)*(1-pi) + Vec(t)*pi
                        point = nearest_sources_Point((lr+tb)/2.0)
                        if i == 0: point = self.rfcontext.snap_to_symmetry(point, symmetry0)
                        if j == l1-1: point = self.rfcontext.snap_to_symmetry(point, symmetry1)
                        verts += [point]
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(l0-1) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1,l1) for i in range(l0-1)]
            faces += [( (i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1) ) for i in range(l0-1) for j in range(l1-1)]

            self.previz += [{ 'type': 'L', 'data': shape, 'verts': verts, 'edges': edges, 'faces': faces }]

        for shape in self.shapes['C']:
            s0,s1,s2 = shape
            if len(s0) != len(s2): continue     # invalid C-shape
            sv0,sv1,sv2 = get_verts(s0),get_verts(s1),get_verts(s2,True)
            l0,l1 = len(sv0),len(sv1)

            # make sure each strip is in the correct order
            if sv0[-1] not in sv1: sv0.reverse()
            if sv1[-1] not in sv2: sv1.reverse()
            if sv2[-1] not in sv1: sv2.reverse()

            symmetry0 = self.rfcontext.get_point_symmetry(sv0[0].co)
            symmetry2 = self.rfcontext.get_point_symmetry(sv2[0].co)
            use_symmetry = (symmetry0 == symmetry2)
            #print([v.co for v in sv0])
            #print([v.co for v in sv2])
            #print(symmetry0, symmetry2, use_symmetry)

            off0,off2 = sv0[0].co-sv0[-1].co, sv2[0].co-sv2[-1].co

            verts,edges,faces = [],[],[]
            for i in range(l0):
                for j in range(l1):
                    if   i == l0-1: verts += [sv1[j]]
                    elif j == 0:    verts += [sv0[i]]
                    elif j == l1-1: verts += [sv2[i]]
                    else:
                        pi,pj = i / (l0-1), j / (l1-1)
                        off = off0*(1-pj)+off2*pj
                        l,r = sv0[i].co,sv2[i].co
                        t,b = sv1[j].co,sv1[j].co+off
                        lr = Vec(l)*(1-pj) + Vec(r)*pj
                        tb = Vec(b)*(1-pi) + Vec(t)*pi
                        point = nearest_sources_Point((lr+tb)/2.0)
                        if use_symmetry and i == 0: point = self.rfcontext.snap_to_symmetry(point, symmetry0)
                        verts += [point]
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(l0-1) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1,l1-1) for i in range(l0-1)]
            faces += [( (i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1) ) for i in range(l0-1) for j in range(l1-1)]

            self.previz += [{ 'type': 'C', 'data': shape, 'verts': verts, 'edges': edges, 'faces': faces }]

        # TODO: check sides to make sure that we aren't creating geometry
        #       on a side that already has geometry!
        for i0,shape0 in enumerate(self.shapes['I']):
            sv0 = get_verts(shape0[0])
            dir0 = Direction(sv0[0].co-sv0[-1].co)
            best_sv1,best_dist = None,0
            for i1,shape1 in enumerate(self.shapes['I']):
                if i1 <= i0: continue
                sv1 = get_verts(shape1[0])
                dir1 = Direction(sv1[0].co-sv1[-1].co)
                if len(sv0) != len(sv1): continue
                if dir0.dot(dir1) < 0:
                    sv1 = list(reversed(sv1))
                    dir1.reverse()
                # make sure the I strip are good candidates for bridging
                # if math.degrees(dir0.angleBetween(dir1)) > 80: continue     # make sure strips are parallel enough
                if math.degrees(dir0.angleBetween(Direction(sv1[0].co-sv0[0].co))) < 45: continue
                if math.degrees(dir1.angleBetween(Direction(sv0[0].co-sv1[0].co))) < 45: continue
                dist = min((v0.co-v1.co).length for v0 in sv0 for v1 in sv1)
                if best_sv1 and best_dist < dist: continue
                best_sv1 = sv1
                best_dist = dist
            if not best_sv1: continue
            sv1,dist = best_sv1,best_dist
            avg0 = (sv0[0].co-sv0[-1].co).length / (len(sv0)-1)
            avg1 = (sv1[0].co-sv1[-1].co).length / (len(sv1)-1)

            l0 = len(sv0)
            if getattr(self, 'crosses', None) is None:
                self.crosses = max(2, math.floor(dist / max(avg0,avg1)))
            l1 = self.crosses

            verts,edges,faces = [],[],[]
            for i in range(l0):
                for j in range(l1):
                    if   j == 0:    verts += [sv0[i]]
                    elif j == l1-1: verts += [sv1[i]]
                    else:
                        pi,pj = i / (l0-1), j / (l1-1)
                        l,r = sv0[i].co,sv1[i].co
                        lr = Vec(l)*(1-pj) + Vec(r)*pj
                        verts += [nearest_sources_Point(lr)]
            edges += [(i*l1+(j+0), i*l1+(j+1)) for i in range(l0) for j in range(l1-1)]
            edges += [((i+0)*l1+j, (i+1)*l1+j) for j in range(1,l1-1) for i in range(l0-1)]
            faces += [( (i+0)*l1+(j+0), (i+1)*l1+(j+0), (i+1)*l1+(j+1), (i+0)*l1+(j+1) ) for i in range(l0-1) for j in range(l1-1)]

            self.previz += [{ 'type': 'I', 'data': shape0, 'verts': verts, 'edges': edges, 'faces': faces }]


        if False:
            print('')
            print('patches info:')
            print('  %d edges' % len(edges))
            print('  %d strips' % len(strips))
            print('  %d corners' % len(corners))
            print('  %d string corners' % len(string_corners))
            print('  %d loop corners' % len(loop_corners))
            print('  %d strings' % len(strings_strips))
            print('  %d loops' % len(loops_strips))
            for d,k in [('loop','O'),('loop','eye'),('loop','tri'),('loop','rect'),('loop','ngon'),('string','I'),('string','L'),('string','C'),('string','else')]:
                print('  %d %s-shaped %s' % (len(self.shapes[k]), k, d))

        tag_redraw_all('Patches recompute')
        self.update_ui()
