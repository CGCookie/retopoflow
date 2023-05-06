'''
Copyright (C) 2022 CG Cookie
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

import bgl
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


class Knife(RFTool):
    name        = 'Knife'
    description = 'Cut complex topology into existing geometry on vertex-by-vertex basis'
    icon        = 'knife-icon.png'
    help        = 'knife.md'
    shortcut    = 'knife tool'
    quick_shortcut = 'knife quick'
    statusbar   = '{{insert}} Insert'
    ui_config   = 'knife_options.html'

    RFWidget_Default   = RFWidget_Default_Factory.create()
    RFWidget_Knife     = RFWidget_Default_Factory.create(cursor='KNIFE')
    RFWidget_Move      = RFWidget_Default_Factory.create(cursor='HAND')
    RFWidget_Hidden    = RFWidget_Hidden_Factory.create()

    @RFTool.on_init
    def init(self):
        self.rfwidgets = {
            'default': self.RFWidget_Default(self),
            'knife':   self.RFWidget_Knife(self),
            'hover':   self.RFWidget_Move(self),
            'hidden':  self.RFWidget_Hidden(self),
        }
        self.rfwidget = None
        self.first_time = True
        self.knife_start = None
        self.quick_knife = False
        self.update_state_info()
        self.previs_timer = self.actions.start_timer(120.0, enabled=False)

    @RFTool.on_reset
    def reset(self):
        if self.actions.using('knife quick'):
            self._fsm.force_set_state('quick')
            self.previs_timer.start()
        else:
            self.previs_timer.stop()

    @RFTool.on_reset
    @RFTool.on_target_change
    @RFTool.on_view_change
    @FSM.onlyinstate({'main', 'quick', 'insert'})
    def update_state_info(self):
        with profiler.code('getting selected geometry'):
            self.sel_verts = self.rfcontext.rftarget.get_selected_verts()
            self.sel_edges = self.rfcontext.rftarget.get_selected_edges()
            self.sel_faces = self.rfcontext.rftarget.get_selected_faces()

        with profiler.code('getting visible geometry'):
            self.vis_accel = self.rfcontext.get_vis_accel()
            self.vis_verts = self.rfcontext.accel_vis_verts
            self.vis_edges = self.rfcontext.accel_vis_edges
            self.vis_faces = self.rfcontext.accel_vis_faces

        if self.rfcontext.loading_done:
            self.set_next_state(force=True)

    def set_next_state(self, force=False):
        '''
        determines what the next state will be, based on selected mode, selected geometry, and hovered geometry
        '''
        if not self.actions.mouse and not force: return

        with profiler.code('getting nearest geometry'):
            self.nearest_vert,_ = self.rfcontext.accel_nearest2D_vert(max_dist=options['action dist'])
            self.nearest_edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['action dist'])
            self.nearest_face,_ = self.rfcontext.accel_nearest2D_face(max_dist=options['action dist'])
            self.nearest_geom = self.nearest_vert or self.nearest_edge or self.nearest_face

    def ensure_all_valid(self):
        self.sel_verts = [v for v in self.sel_verts if v.is_valid]
        self.sel_edges = [e for e in self.sel_edges if e.is_valid]
        self.sel_faces = [f for f in self.sel_faces if f.is_valid]

        self.vis_verts = [v for v in self.vis_verts if v.is_valid]
        self.vis_edges = [e for e in self.vis_edges if e.is_valid]
        self.vis_faces = [f for f in self.vis_faces if f.is_valid]


    @FSM.on_state('quick', 'enter')
    def quick_enter(self):
        self.quick_knife = True
        self.set_widget('knife')

    @FSM.on_state('quick')
    def quick_main(self):
        if self.actions.pressed({'confirm','cancel'}, ignoremouse=True):
            self.quick_knife = False
            self.previs_timer.stop()
            return 'main'

        if self.first_time or self.actions.mousemove_stop:
            self.set_next_state(force=True)
            self.first_time = False
            tag_redraw_all('Knife mousemove')

        if self.rfcontext.actions.pressed('knife reset'):
            self.knife_start = None
            self.rfcontext.deselect_all()
            return

        if self.rfcontext.actions.pressed({'select all', 'deselect all'}):
            self.rfcontext.undo_push('deselect all')
            self.rfcontext.deselect_all()
            return

        if self.rfcontext.actions.pressed('quick insert'):
            return 'insert'


    @FSM.on_state('main', 'enter')
    def main_enter(self):
        self.quick_knife = False
        self.update_state_info()

    @FSM.on_state('main')
    def main(self):
        if not self.actions.using_onlymods('insert'):
            self.knife_start = None

        if self.first_time or self.actions.mousemove_stop:
            self.set_next_state(force=True)
            self.first_time = False
            tag_redraw_all('Knife mousemove')

        self.previs_timer.enable(self.actions.using_onlymods('insert'))
        if self.actions.using_onlymods('insert'):
            self.set_widget('knife')
        elif self.nearest_geom and self.nearest_geom.select:
            self.set_widget('hover')
        else:
            self.set_widget('default')

        if self.handle_inactive_passthrough(): return

        if self.actions.pressed('insert'):
            return 'insert'

        if self.nearest_geom and self.nearest_geom.select:
            if self.actions.pressed('action'):
                self.rfcontext.undo_push('grab')
                self.prep_move(defer_recomputing=False)
                return 'move after select'

        if self.actions.pressed({'select path add'}):
            return self.rfcontext.select_path(
                {'edge'},
                kwargs_select={'supparts': False},
            )

        if self.actions.pressed({'select paint', 'select paint add'}, unpress=False):
            sel_only = self.actions.pressed('select paint')
            self.actions.unpress()
            return self.rfcontext.setup_smart_selection_painting(
                {'vert','edge','face'},
                selecting=not sel_only,
                deselect_all=sel_only,
                kwargs_select={'supparts': False},
                kwargs_deselect={'subparts': False},
            )

        if self.actions.pressed({'select single', 'select single add'}, unpress=False):
            sel_only = self.actions.pressed('select single')
            self.actions.unpress()
            bmv,_ = self.rfcontext.accel_nearest2D_vert(max_dist=options['select dist'])
            bme,_ = self.rfcontext.accel_nearest2D_edge(max_dist=options['select dist'])
            bmf,_ = self.rfcontext.accel_nearest2D_face(max_dist=options['select dist'])
            sel = bmv or bme or bmf
            if not sel_only and not sel: return
            self.rfcontext.undo_push('select')
            if sel_only: self.rfcontext.deselect_all()
            if not sel: return
            if sel.select: self.rfcontext.deselect(sel, subparts=False)
            else:          self.rfcontext.select(sel, supparts=False, only=sel_only)
            return

        if self.rfcontext.actions.pressed('knife reset'):
            self.knife_start = None
            self.rfcontext.deselect_all()
            return

        if self.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move'


    def set_vis_bmverts(self):
        self.vis_bmverts = [
            (bmv, self.rfcontext.Point_to_Point2D(bmv.co))
            for bmv in self.vis_verts
            if bmv.is_valid and bmv not in self.sel_verts
        ]


    @FSM.on_state('insert')
    def insert(self):
        self.rfcontext.undo_push('insert')
        return self._insert()

    def _get_edge_quad_verts(self):
        '''
        this function is used in quad-only mode to find positions of quad verts based on selected edge and mouse position
        a Desmos construction of how this works: https://www.desmos.com/geometry/5w40xowuig
        '''
        e0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
        if not e0: return (None, None, None, None)
        bmv0,bmv1 = e0.verts
        xy0 = self.rfcontext.Point_to_Point2D(bmv0.co)
        xy1 = self.rfcontext.Point_to_Point2D(bmv1.co)
        d01 = (xy0 - xy1).length
        mid01 = xy0 + (xy1 - xy0) / 2
        mid23 = self.actions.mouse
        mid0123 = mid01 + (mid23 - mid01) / 2
        between = mid23 - mid01
        if between.length < 0.0001: return (None, None, None, None)
        perp = Direction2D((-between.y, between.x))
        if perp.dot(xy1 - xy0) < 0: perp.reverse()
        #pts = intersect_line_line(xy0, xy1, mid0123, mid0123 + perp)
        #if not pts: return (None, None, None, None)
        #intersection = pts[1]
        intersection = intersection2d_line_line(xy0, xy1, mid0123, mid0123 + perp)
        if not intersection: return (None, None, None, None)
        intersection = Point2D(intersection)

        toward = Direction2D(mid23 - intersection)
        if toward.dot(perp) < 0: d01 = -d01

        # push intersection out just a bit to make it more stable (prevent crossing) when |between| < d01
        between_len = between.length * Direction2D(xy1 - xy0).dot(perp)

        for tries in range(32):
            v = toward * (d01 / 2)
            xy2, xy3 = mid23 + v, mid23 - v

            # try to prevent quad from crossing
            v03 = xy3 - xy0
            if v03.dot(between) < 0 or v03.length < between_len:
                xy3 = xy0 + Direction2D(v03) * (between_len * (-1 if v03.dot(between) < 0 else 1))
            v12 = xy2 - xy1
            if v12.dot(between) < 0 or v12.length < between_len:
                xy2 = xy1 + Direction2D(v12) * (between_len * (-1 if v12.dot(between) < 0 else 1))

            if self.rfcontext.raycast_sources_Point2D(xy2)[0] and self.rfcontext.raycast_sources_Point2D(xy3)[0]: break
            d01 /= 2
        else:
            return (None, None, None, None)

        nearest_vert,_ = self.rfcontext.nearest2D_vert(point=xy2, verts=self.vis_verts, max_dist=options['knife merge dist'])
        if nearest_vert: xy2 = self.rfcontext.Point_to_Point2D(nearest_vert.co)
        nearest_vert,_ = self.rfcontext.nearest2D_vert(point=xy3, verts=self.vis_verts, max_dist=options['knife merge dist'])
        if nearest_vert: xy3 = self.rfcontext.Point_to_Point2D(nearest_vert.co)

        return (xy0, xy1, xy2, xy3)

    @RFTool.dirty_when_done
    def _insert(self):
        self.last_delta = None
        self.move_done_pressed = None
        self.move_done_released = 'insert'
        self.move_cancelled = 'cancel'

        bmv = self.rfcontext.accel_nearest2D_vert(max_dist=options['knife snap dist'])[0]
        bme = self.rfcontext.accel_nearest2D_edge(max_dist=options['knife snap dist'])[0]
        bmf = self.rfcontext.accel_nearest2D_face(max_dist=options['knife snap dist'])[0]

        if self.knife_start is None and len(self.sel_verts) == 0:
            next_state = 'knife start'
        else:
            next_state = 'knife cut'

        if bme and any(v.select for v in bme.verts):
            # special case that we are hovering an edge has a selected vert (should split edge!)
            next_state = 'knife start'


        if next_state == 'knife start':
            if bmv:
                # just select the hovered vert
                self.rfcontext.select(bmv)
            elif bme:
                # split the hovered edge
                bmv = self.rfcontext.new2D_vert_mouse()
                if not bmv:
                    self.rfcontext.undo_cancel()
                    return 'main' if not self.quick_knife else 'quick'
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
                self.set_next_state(force=True)
                return 'main' if not self.quick_knife else 'quick'
            self.set_next_state(force=True)
            self.mousedown = self.actions.mouse
            self.bmverts = [(bmv, self.actions.mouse)] if bmv else []
            self.set_vis_bmverts()
            return 'move'

        elif next_state == 'knife cut':
            Point_to_Point2D = self.rfcontext.Point_to_Point2D
            knife_start = self.knife_start or Point_to_Point2D(next(iter(self.sel_verts)).co)
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
                self.knife_start = self.actions.mouse
                return 'main' if not self.quick_knife else 'quick'
            prev = None
            pre_e = -1
            pre_p = None
            unfaced_verts = []
            bmfs_to_shatter = set()
            for p,e,d in crosses:
                if type(e) is RFVert:
                    cur = e
                else:
                    cur = self.rfcontext.new2D_vert_point(p)
                    if type(e) is RFEdge:
                        eo,bmv = e.split()
                        cur.merge(bmv)
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
                self.mousedown = self.actions.mouse
                self.bmverts = [(prev, self.actions.mouse)] if prev else []
                self.set_vis_bmverts()
                return 'move'
            self.knife_start = self.actions.mouse
            return 'main' if not self.quick_knife else 'quick'

        return 'main' if not self.quick_knife else 'quick'


    def mergeSnapped(self):
        """ Merging colocated visible verts """

        if not options['knife automerge']: return

        # TODO: remove colocated faces
        if self.mousedown is None: return
        delta = Vec2D(self.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        update_verts = []
        merge_dist = self.rfcontext.drawing.scale(options['knife merge dist'])
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
            self.set_next_state()


    def prep_move(self, bmverts=None, defer_recomputing=True):
        if not bmverts: bmverts = self.sel_verts
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts if bmv and bmv.is_valid]
        self.set_vis_bmverts()
        self.mousedown = self.actions.mouse
        self.last_delta = None
        self.defer_recomputing = defer_recomputing

    @FSM.on_state('move after select')
    @profiler.function
    @RFTool.dirty_when_done
    def modal_move_after_select(self):
        if self.actions.released('action'):
            return 'main' if not self.quick_knife else 'quick'
        if (self.actions.mouse - self.mousedown).length > 7:
            self.last_delta = None
            self.move_done_pressed = None
            self.move_done_released = 'action'
            self.move_cancelled = 'cancel'
            self.rfcontext.undo_push('move after select')
            return 'move'

    @FSM.on_state('move', 'enter')
    def move_enter(self):
        self.move_opts = {
            'timer': self.actions.start_timer(120),
            'vis_accel': self.rfcontext.get_custom_vis_accel(selection_only=False, include_edges=False, include_faces=False),
        }
        self.rfcontext.split_target_visualization_selected()
        self.rfcontext.set_accel_defer(True)

        if options['hide cursor on tweak']: self.set_widget('hidden')

        # filter out any deleted bmverts (issue #1075) or bmverts that are not on screen
        self.bmverts = [(bmv, xy) for (bmv, xy) in self.bmverts if bmv and bmv.is_valid and xy]

    @FSM.on_state('move')
    def modal_move(self):
        if self.move_done_pressed and self.actions.pressed(self.move_done_pressed):
            self.defer_recomputing = False
            self.mergeSnapped()
            return 'main' if not self.quick_knife else 'quick'
        if self.move_done_released and self.actions.released(self.move_done_released, ignoremods=True):
            self.defer_recomputing = False
            self.mergeSnapped()
            return 'main' if not self.quick_knife else 'quick'
        if self.move_cancelled and self.actions.pressed('cancel'):
            self.defer_recomputing = False
            self.rfcontext.undo_cancel()
            return 'main' if not self.quick_knife else 'quick'

        if self.actions.mousemove or not self.actions.mousemove_prev: return
        # # only update verts on timer events and when mouse has moved
        # if not self.actions.timer: return

        if not self.actions.mousemove_stop: return
        delta = Vec2D(self.actions.mouse - self.mousedown)
        if delta == self.last_delta: return
        self.last_delta = delta
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            if not xy: continue
            xy_updated = xy + delta
            # check if xy_updated is "close" to any visible verts (in image plane)
            # if so, snap xy_updated to vert position (in image plane)
            if options['knife automerge']:
                bmv1,d = self.rfcontext.accel_nearest2D_vert(point=xy_updated, vis_accel=self.move_opts['vis_accel'], max_dist=options['knife merge dist'])
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
        self.rfcontext.dirty()

    @FSM.on_state('move', 'exit')
    def move_exit(self):
        self.move_opts['timer'].done()
        self.rfcontext.set_accel_defer(False)
        self.rfcontext.clear_split_target_visualization()

    def _get_crosses(self, p0, p1):
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
            i = intersect2d_segment_segment(p0, p1, c0, c1)
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

    def draw_crosses(self, crosses):
        with Globals.drawing.draw(CC_2D_POINTS) as draw:
            for p,e,d in crosses:
                draw.color(themes['active'] if type(e) is RFVert else themes['new'])
                draw.vertex(p)

    def draw_lines(self, coords, poly_alpha=0.2):
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

    @DrawCallbacks.on_draw('post2d')
    @FSM.onlyinstate({'main', 'quick'})
    def draw_postpixel(self):
        # TODO: put all logic into set_next_state(), such as vertex snapping, edge splitting, etc.

        if self.actions.navigating(): return

        # make sure that all our data structs contain valid data (hasn't been deleted)
        self.ensure_all_valid()

        #if self.rfcontext.nav or self.mode != 'main': return
        if self._fsm.state != 'quick':
            if not self.actions.using_onlymods('insert'): return
        hit_pos = self.actions.hit_pos

        if self.knife_start is None and len(self.sel_verts) == 0:
            next_state = 'knife start'
        else:
            next_state = 'knife cut'

        bgl.glEnable(bgl.GL_BLEND)
        CC_DRAW.stipple(pattern=[4,4])
        CC_DRAW.point_size(8)
        CC_DRAW.line_width(2)

        bmv = self.rfcontext.accel_nearest2D_vert(max_dist=options['knife snap dist'])[0]
        bme = self.rfcontext.accel_nearest2D_edge(max_dist=options['knife snap dist'])[0]
        bmf = self.rfcontext.accel_nearest2D_face(max_dist=options['knife snap dist'])[0]

        if next_state == 'knife start':
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

        elif next_state == 'knife cut':
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

