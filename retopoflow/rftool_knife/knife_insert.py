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

import time
import random

from mathutils.geometry import intersect_line_line_2d as intersect2d_segment_segment

from ..rftool import RFTool
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_hidden  import RFWidget_Hidden_Factory
from ..rfmesh.rfmesh_wrapper import RFVert, RFEdge, RFFace

from ...addon_common.common.drawing import (
    CC_DRAW,
    CC_2D_POINTS,
    CC_2D_LINES, CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES, CC_2D_TRIANGLE_FAN,
)
from ...addon_common.common import gpustate
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import Point, Point2D, Vec2D, Vec, Direction2D, intersection2d_line_line, closest2d_point_segment
from ...addon_common.common.globals import Globals
from ...addon_common.common.fsm import FSM
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString
from ...addon_common.common.decorators import timed_call
from ...addon_common.common.drawing import DrawCallbacks


from ...config.options import options, themes


class Knife_Insert():
    @RFTool.on_quickswitch_start
    def quickswitch_start(self):
        self.quickswitch = True
        self._fsm.force_set_state('insert')

    @RFTool.on_events('target change')
    @FSM.onlyinstate('insert')
    @RFTool.not_while_navigating
    def gather_selection(self):
        self.sel_verts, self.sel_edges, self.sel_faces = self.rfcontext.get_selected_geom()

    @RFTool.on_events('target change', 'view change')
    @FSM.onlyinstate('insert')
    @RFTool.not_while_navigating
    def gather_visible(self):
        self.vis_verts, self.vis_edges, self.vis_faces = self.rfcontext.get_vis_geom()

    def gather_all(self):
        self.gather_selection()
        self.gather_visible()

    @RFTool.on_events('mouse move')
    @FSM.onlyinstate('insert')
    @RFTool.not_while_navigating
    def update_knife(self):
        tag_redraw_all('Knife mousemove')


    def ensure_all_valid(self):
        self.sel_verts = [v for v in self.sel_verts if v.is_valid]
        self.sel_edges = [e for e in self.sel_edges if e.is_valid]
        self.sel_faces = [f for f in self.sel_faces if f.is_valid]

        self.vis_verts = [v for v in self.vis_verts if v.is_valid]
        self.vis_edges = [e for e in self.vis_edges if e.is_valid]
        self.vis_faces = [f for f in self.vis_faces if f.is_valid]


    @FSM.on_state('insert', 'enter')
    def insert_enter(self):
        self.gather_all()
        self.knife_start = None
        self.set_widget('knife')
        self.rfcontext.fast_update_timer.enable(True)

        if not self.quickswitch:
            self.knife_actions = {
                'insert': (lambda: self.actions.pressed('insert')),
                'done':   (lambda: not self.actions.using_onlymods('insert')),
                'move':   (lambda: self.actions.released('insert', ignoremods=True)),
            }
        else:
            self.knife_actions = {
                'insert': (lambda: self.actions.pressed('quick insert')),
                'done':   (lambda: any([
                    self.actions.pressed('cancel'),
                    self.actions.pressed('confirm', ignoremouse=True),
                    self.actions.pressed('confirm quick'),
                ])),
                'move':   (lambda: self.actions.released('quick insert', ignoremods=True)),
            }

    @FSM.on_state('insert')
    def insert_main(self):
        # if self.handle_inactive_passthrough(): return

        if self.knife_actions['insert']():
            self.rfcontext.undo_push('insert')
            return self._insert()

        if self.knife_actions['done']():
            return 'main'

        if self.rfcontext.actions.pressed('knife reset'):
            self.knife_start = None
            self.rfcontext.deselect_all()
            return

        if self.rfcontext.actions.pressed({'select all', 'deselect all'}):
            self.rfcontext.undo_push('deselect all')
            self.rfcontext.deselect_all()
            return

    @FSM.on_state('insert', 'exit')
    def insert_exit(self):
        self.rfcontext.fast_update_timer.enable(False)


    @DrawCallbacks.on_draw('post2d')
    @FSM.onlyinstate('insert')
    @RFTool.not_while_navigating
    def draw_postpixel(self):
        # TODO: put all logic into set_next_state(), such as vertex snapping, edge splitting, etc.

        # make sure that all our data structs contain valid data (hasn't been deleted)
        self.ensure_all_valid()

        hit_pos = self.actions.hit_pos

        bmv, _ = self.rfcontext.accel_nearest2D_vert(max_dist=options['knife snap dist'])
        bme, _ = self.rfcontext.accel_nearest2D_edge(max_dist=options['knife snap dist'])
        bmf, _ = self.rfcontext.accel_nearest2D_face(max_dist=options['knife snap dist'])

        if self.knife_start is None and len(self.sel_verts) == 0:
            next_state = 'knife start'
        elif bme and any(v.select for v in bme.verts):
            # special case that we are hovering an edge has a selected vert (should split edge!)
            next_state = 'knife start'
        else:
            next_state = 'knife cut'

        gpustate.blend('ALPHA')
        CC_DRAW.stipple(pattern=[4,4])
        CC_DRAW.point_size(8)
        CC_DRAW.line_width(2)

        match next_state:
            case 'knife start':
                if bmv:
                    p, c = self.rfcontext.Point_to_Point2D(bmv.co), themes['active']
                elif bme:
                    bmv1, bmv2 = bme.verts
                    if hit_pos:
                        self.draw_lines([bmv1.co, hit_pos])
                        self.draw_lines([bmv2.co, hit_pos])
                    p, c = self.actions.mouse, themes['new']
                elif bmf:
                    p, c = self.actions.mouse, themes['new']
                else:
                    p, c = None, None
                if p and c:
                    with Globals.drawing.draw(CC_2D_POINTS) as draw:
                        draw.color(c)
                        draw.vertex(p)
            case 'knife cut':
                knife_start = self.knife_start or self.rfcontext.Point_to_Point2D(next(iter(self.sel_verts)).co)
                with Globals.drawing.draw(CC_2D_LINES) as draw:
                    draw.color(themes['stroke'])
                    draw.vertex(knife_start)
                    draw.vertex(self.actions.mouse)
                crosses = self._get_crosses(knife_start, self.actions.mouse)
                if not crosses: return
                if bmf:
                    dist_to_last = (crosses[-1][0] - self.actions.mouse).length
                    if dist_to_last > self.rfcontext.drawing.scale(options['knife snap dist']):
                        crosses += [(self.actions.mouse, bmf, 1.0)]
                elif bme:
                    dist_to_last = (crosses[-1][0] - self.actions.mouse).length
                    if dist_to_last > self.rfcontext.drawing.scale(options['knife snap dist']):
                        crosses += [(self.actions.mouse, bme, 1.0)]
                self.draw_crosses(crosses)
                if bmv:
                    pass
                elif bme:
                    bmv1, bmv2 = bme.verts
                    if hit_pos:
                        self.draw_lines([bmv1.co, hit_pos])
                        self.draw_lines([bmv2.co, hit_pos])
                    c = themes['new']
                    p = self.actions.mouse
                # print(crosses)



    @RFTool.dirty_when_done
    def _insert(self):
        # Get nearest geometry
        bmv, _ = self.rfcontext.accel_nearest2D_vert(max_dist=options['knife snap dist'])
        bme, _ = self.rfcontext.accel_nearest2D_edge(max_dist=options['knife snap dist'])
        bmf, _ = self.rfcontext.accel_nearest2D_face(max_dist=options['knife snap dist'])

        # Determine if starting new cut or continuing existing one
        if self.knife_start is None and len(self.sel_verts) == 0:
            next_state = 'knife start'
        elif bme and any(v.select for v in bme.verts):
            # special case that we are hovering an edge has a selected vert (should split edge!)
            next_state = 'knife start'
        else:
            next_state = 'knife cut'

        # Handle different cutting states
        match next_state:
            case 'knife start':
                # Starting new cut - handle vertex/edge/face creation
                if bmv:
                    # just select the hovered vert
                    self.rfcontext.select(bmv)
                elif bme:
                    # split the hovered edge
                    bmv = self.rfcontext.new2D_vert_mouse()
                    if not bmv:
                        self.rfcontext.undo_cancel()
                        return
                    bme0,bmv2 = bme.split()
                    bmv.merge(bmv2)
                    self.rfcontext.select(bmv)
                elif bmf:
                    # add point at mouse
                    bmv = self.rfcontext.new2D_vert_mouse()
                    self.rfcontext.select(bmv)
                else:
                    self.knife_start = self.actions.mouse
                    self.rfcontext.undo_cancel()    # remove undo, because no geometry was changed
                    self.gather_all()
                    return

                self.prep_move(
                    bmverts_xys=([(bmv, self.actions.mouse)] if bmv else []),
                    action_confirm=self.knife_actions['move'],
                )
                return 'move'

            case 'knife cut':
                # Continuing existing cut - handle intersections and splits
                # Get intersection points between cut line and geometry
                Point_to_Point2D = self.rfcontext.Point_to_Point2D
                knife_start = self.knife_start or Point_to_Point2D(next(iter(self.sel_verts)).co)
                if knife_start is None:
                    self.rfcontext.undo_cancel()    # remove undo, because no geometry was changed
                    self.knife_start = self.actions.mouse
                    return
                knife_start_face = self.rfcontext.accel_nearest2D_face(point=knife_start, max_dist=options['knife snap dist'])[0]
                crosses = self._get_crosses(knife_start, self.actions.mouse)
                # add additional point if mouse is hovering a face or edge
                if bmf:
                    dist_to_last = (crosses[-1][0] - self.actions.mouse).length if crosses else float('inf')
                    if dist_to_last > self.rfcontext.drawing.scale(options['knife snap dist']):
                        crosses += [(self.actions.mouse, bmf, None)]
                elif bme:
                    dist_to_last = (crosses[-1][0] - self.actions.mouse).length if crosses else float('inf')
                    if dist_to_last > self.rfcontext.drawing.scale(options['knife snap dist']):
                        crosses += [(self.actions.mouse, bme, None)]

                if not crosses:
                    self.rfcontext.undo_cancel()    # remove undo, because no geometry was changed
                    self.knife_start = self.actions.mouse
                    return

                prev = None
                pre_e = -1
                pre_p = None
                unfaced_verts = []
                bmfs_to_shatter = set()
                
                # Create new geometry at intersections
                for p,e,d in crosses:
                    # Create vertices and split edges/faces as needed
                    if type(e) is RFVert:
                        cur = e
                    else:
                        cur = self.rfcontext.new2D_vert_point(p)
                        if type(e) is RFEdge:
                            eo,bmv = e.split()
                            if cur:
                                cur.merge(bmv)
                            else:
                                cur = bmv
                        elif type(e) is RFFace:
                            pass
                    if prev:
                        cur_faces = set(cur.link_faces)
                        cur_under = cur_faces
                        if not cur_under:
                            cur_under = {self.rfcontext.accel_nearest2D_face(point=p, max_dist=options['knife snap dist'])[0]}
                        pre_faces = set(prev.link_faces)
                        pre_under = pre_faces
                        if not pre_under:
                            pre_under = {self.rfcontext.accel_nearest2D_face(point=pre_p, max_dist=options['knife snap dist'])[0]}
                        bmfs_to_shatter |= cur_under | pre_under
                        if cur_under & pre_under and not prev.share_edge(cur):
                            nedge = self.rfcontext.new_edge([prev, cur])
                        if cur_faces & pre_faces and not cur.share_edge(prev):
                            face = next(iter(cur_faces & pre_faces))
                            try:
                                face.split(prev, cur)
                            except Exception as ex:
                                print(f'Knife caught Exception while trying to split face {face} ({prev}-{cur})')
                                print(ex)

                    if not cur.link_faces:
                        unfaced_verts.append(cur)
                    prev = cur
                    pre_e = e
                    pre_p = p

                self.rfcontext.select(prev)

                for bmf in bmfs_to_shatter:
                    if bmf: bmf.shatter()

                if (pre_p - self.actions.mouse).length <= self.rfcontext.drawing.scale(options['knife snap dist']):
                    self.knife_start = None
                    self.prep_move(
                        bmverts_xys=([(prev, self.actions.mouse)] if prev else []),
                        action_confirm=self.knife_actions['move'],
                    )
                    return 'move'

                self.knife_start = self.actions.mouse

            case _:
                assert False, f'Unhandled state {next_state}'

        return


    # Find intersections between cut line and existing geometry
    def _get_crosses(self, p0, p1):
        # Calculate intersections between line segment p0-p1 and visible edges
        # Returns list of (point, intersected_element, distance) tuples
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        dist = self.rfcontext.drawing.scale(options['knife snap dist'])
        crosses = set()
        touched = set()
        #p0 = Point_to_Point2D(p0)
        #p1 = Point_to_Point2D(p1)
        v01 = Vec2D(p1 - p0)
        lv01 = max(v01.length, 0.00001)
        d01 = v01 / lv01
        def add(p, e):
            if e in touched: return
            p.freeze()
            touched.add(e)
            crosses.add((p, e, d01.dot(p - p0) / lv01))
        p0v = self.rfcontext.accel_nearest2D_vert(point=p0, max_dist=options['knife snap dist'])[0]
        if p0v and not p0v.link_edges:
            add(p0, p0v)
        for e in self.vis_edges:
            v0, v1 = e.verts
            c0, c1 = Point_to_Point2D(v0.co), Point_to_Point2D(v1.co)
            
            # Skip invalid/degenerate edges
            if (c0-c1).length < 0.000001: continue
                
            # Calculate intersection with a small epsilon to handle floating point precision
            i = intersect2d_segment_segment(p0, p1, c0, c1)
            if i:
                # Verify intersection point is actually on both segments
                ip = Point2D(i)
                on_p0p1 = (ip-p0).dot(p1-p0) >= -0.000001 and (ip-p1).dot(p0-p1) >= -0.000001
                on_c0c1 = (ip-c0).dot(c1-c0) >= -0.000001 and (ip-c1).dot(c0-c1) >= -0.000001
                if on_p0p1 and on_c0c1:
                    add(ip, e)
                    continue
                    
            # Existing snap checks
            clc0 = closest2d_point_segment(c0, p0, p1)
            clc1 = closest2d_point_segment(c1, p0, p1)
            clp0 = closest2d_point_segment(p0, c0, c1)
            clp1 = closest2d_point_segment(p1, c0, c1)
            if   (clc0 - c0).length <= dist: add(c0,   v0)
            elif (clc1 - c1).length <= dist: add(c1,   v1)
            elif (clp0 - p0).length <= dist: add(clp0, e)
            elif (clp1 - p1).length <= dist: add(clp1, e)
            elif i:                          add(Point2D(i), e)
        crosses = sorted(crosses, key=lambda cross: cross[2])
        return crosses

    ''' Drawing functions for visualization. '''

    def draw_crosses(self, crosses):
        # Draw intersection points
        with Globals.drawing.draw(CC_2D_POINTS) as draw:
            for p,e,d in crosses:
                draw.color(themes['active'] if type(e) is RFVert else themes['new'])
                draw.vertex(p)

    def draw_lines(self, coords, poly_alpha=0.2):
        # Draw preview lines and polygons
        line_color = themes['new']
        poly_color = [line_color[0], line_color[1], line_color[2], line_color[3] * poly_alpha]
        l = len(coords)
        coords = [self.rfcontext.Point_to_Point2D(co) for co in coords]
        if not all(coords): return

        if l == 1:
            with Globals.drawing.draw(CC_2D_POINTS) as draw:
                draw.color(line_color)
                for c in coords:
                    draw.vertex(c)

        elif l == 2:
            with Globals.drawing.draw(CC_2D_LINES) as draw:
                draw.color(line_color)
                draw.vertex(coords[0])
                draw.vertex(coords[1])

        else:
            with Globals.drawing.draw(CC_2D_LINE_LOOP) as draw:
                draw.color(line_color)
                for co in coords: draw.vertex(co)

            with Globals.drawing.draw(CC_2D_TRIANGLE_FAN) as draw:
                draw.color(poly_color)
                draw.vertex(coords[0])
                for co1,co2 in iter_pairs(coords[1:], False):
                    draw.vertex(co1)
                    draw.vertex(co2)
