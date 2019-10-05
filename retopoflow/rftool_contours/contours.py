'''
Copyright (C) 2019 CG Cookie
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
import random

from mathutils import Matrix

from ..rftool import RFTool
from ..rfwidgets.rfwidget_line import RFWidget_Line

from ...addon_common.common.blender import matrix_vector_mult
from ...addon_common.common.drawing import Drawing, Cursors
from ...addon_common.common.maths import Point, Normal, Vec2D, Plane, Vec
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.boundvar import BoundVar, BoundInt

from ...config.options import options

class RFTool_Contours(RFTool):
    name        = 'Contours'
    description = 'Retopologize cylindrical forms, like arms and legs'
    icon        = 'contours_32.png'


################################################################################################
# following imports must happen *after* the above class, because each subclass depends on
# above class to be defined

from .contours_ops import Contours_Ops
from .contours_props import Contours_Props
from .contours_ui import Contours_UI
from .contours_utils import Contours_Utils
from .contours_utils import (
    find_loops,
    find_strings,
    loop_plane, loop_radius,
    Contours_Loop,
)

class Contours(RFTool_Contours, Contours_Ops, Contours_Props, Contours_Utils, Contours_UI):
    @RFTool_Contours.on_init
    def init(self):
        self.rfwidget = RFWidget_Line(self)


    @RFTool_Contours.on_reset
    def reset(self):
        self.show_cut = False
        self.show_arrows = False
        self.pts = []
        self.cut_pts = []
        self.connected = False
        self.cuts = []

    @RFTool_Contours.on_target_change
    def update_target(self):
        sel_edges = self.rfcontext.get_selected_edges()
        #sel_faces = self.rfcontext.get_selected_faces()

        # find verts along selected loops and strings
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges)

        # filter out any loops or strings that are in the middle of a selected patch
        def in_middle(bmvs, is_loop):
            return any(len(bmv0.shared_edge(bmv1).link_faces) > 1 for bmv0,bmv1 in iter_pairs(bmvs, is_loop))
        sel_loops = [loop for loop in sel_loops if not in_middle(loop, True)]
        sel_strings = [string for string in sel_strings if not in_middle(string, False)]

        # filter out long loops that wrap around patches, sharing edges with other strings
        bmes = {bmv0.shared_edge(bmv1) for string in sel_strings for bmv0,bmv1 in iter_pairs(string,False)}
        sel_loops = [loop for loop in sel_loops if not any(bmv0.shared_edge(bmv1) in bmes for bmv0,bmv1 in iter_pairs(loop,True))]

        mirror_mod = self.rfcontext.rftarget.mirror_mod
        symmetry_threshold = mirror_mod.symmetry_threshold
        def get_string_length(string):
            nonlocal mirror_mod, symmetry_threshold
            c = len(string)
            if c == 0: return 0
            touches_mirror = False
            (x0,y0,z0),(x1,y1,z1) = string[0].co,string[-1].co
            if mirror_mod.x:
                if abs(x0) < symmetry_threshold or abs(x1) < symmetry_threshold:
                    c = (c - 1) * 2
                    touches_mirror = True
            if mirror_mod.y:
                if abs(y0) < symmetry_threshold or abs(y1) < symmetry_threshold:
                    c = (c - 1) * 2
                    touches_mirror = True
            if mirror_mod.z:
                if abs(z0) < symmetry_threshold or abs(z1) < symmetry_threshold:
                    c = (c - 1) * 2
                    touches_mirror = True
            if not touches_mirror: c -= 1
            return c

        self.loops_data = [{
            'loop': loop,
            'plane': loop_plane(loop),
            'count': len(loop),
            'radius': loop_radius(loop),
            'cl': Contours_Loop(loop, True),
            } for loop in sel_loops]
        self.strings_data = [{
            'string': string,
            'plane': loop_plane(string),
            'count': get_string_length(string),
            'cl': Contours_Loop(string, False),
            } for string in sel_strings]
        self.sel_loops = [Contours_Loop(loop, True) for loop in sel_loops]

        self._var_cut_count.disabled = True
        if len(self.loops_data) == 1 and len(self.strings_data) == 0:
            self._var_cut_count_value = self.loops_data[0]['count']
            self._var_cut_count.disabled = False
        if len(self.strings_data) == 1 and len(self.loops_data) == 0:
            self._var_cut_count_value = self.strings_data[0]['count']
            self._var_cut_count.disabled = False


    @RFTool_Contours.FSM_State('main')
    def main(self):
        Cursors.set('CROSSHAIR')

        if self.actions.pressed({'select', 'select add'}):
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
            self.rfcontext.select_edge_loop(edge, only=sel_only, supparts=False)
            return

        if self.rfcontext.actions.pressed({'grab', 'action'}, unpress=False):
            ''' grab for translations '''
            return 'move'

        if self.rfcontext.actions.pressed('shift'):
            ''' rotation of loops about plane normal '''
            return 'shift'

        if self.rfcontext.actions.pressed('rotate'):
            ''' screen-space rotation of loops about plane origin '''
            return 'rotate'

        if self.rfcontext.actions.pressed('fill'):
            self.fill()
            return

        if self.rfcontext.actions.pressed({'increase count', 'decrease count'}, unpress=False):
            self.rfcontext.undo_push('change segment count', repeatable=True)
            self.change_count(delta=1 if self.rfcontext.actions.using('increase count') else -1)
            return


    @RFTool_Contours.FSM_State('shift', 'can enter')
    def shift_can_enter(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        if not sel_loops: return False

        self.move_cloops = [Contours_Loop(loop, True) for loop in sel_loops]
        self.move_verts = [[bmv for bmv in cloop.verts] for cloop in self.move_cloops]
        self.move_pts = [[Point(pt) for pt in cloop.pts] for cloop in self.move_cloops]
        self.move_dists = [list(cloop.dists) for cloop in self.move_cloops]
        self.move_circumferences = [cloop.circumference for cloop in self.move_cloops]
        self.move_origins = [cloop.plane.o for cloop in self.move_cloops]
        self.move_proj_dists = [list(cloop.proj_dists) for cloop in self.move_cloops]

        self.move_cuts = []
        for cloop in self.move_cloops:
            xy = self.rfcontext.Point_to_Point2D(cloop.plane.o)
            ray = self.rfcontext.Point2D_to_Ray(xy)
            crawl = self.rfcontext.plane_intersection_crawl(ray, cloop.plane, walk=True)
            if not crawl:
                dprint('could not crawl around sources for loop')
                self.move_cuts += [None]
                continue
            crawl_pts = [c for _,_,_,c in crawl]
            connected = cloop.connected         # XXX why was `crawl[0][0] is not None` here?
            crawl_pts,connected = self.rfcontext.clip_pointloop(crawl_pts, connected)
            if not crawl_pts or connected != cloop.connected:
                dprint('could not clip loop to symmetry')
                self.move_cuts += [None]
                continue
            cl_cut = Contours_Loop(crawl_pts, connected)
            cl_cut.align_to(cloop)
            self.move_cuts += [cl_cut]
        if not any(self.move_cuts):
            dprint('Found no loops to shift')
            return False

    @RFTool_Contours.FSM_State('shift', 'enter')
    def shift_enter(self):
        self.rot_axis = Vec((0,0,0))
        self.rot_origin = Point.average(cut.get_origin() for cut in self.move_cuts if cut)
        self.shift_about = self.rfcontext.Point_to_Point2D(self.rot_origin)
        for cut in self.move_cuts:
            if not cut: continue
            a = cut.get_normal()
            o = cut.get_origin()
            if self.rot_axis.dot(a) < 0: a = -a
            self.rot_axis += a
        self.rot_axis.normalize()
        p0 = next(iter(cut.get_origin() for cut in self.move_cuts if cut))
        p1 = p0 + self.rot_axis * 0.001
        self.rot_axis2D = (self.rfcontext.Point_to_Point2D(p1) - self.rfcontext.Point_to_Point2D(p0))
        self.rot_axis2D.normalize()
        self.rot_perp2D = Vec2D((self.rot_axis2D.y, -self.rot_axis2D.x))
        print(self.rot_axis, self.rot_axis2D, self.rot_perp2D)

        self.rfcontext.undo_push('shift contours')

        self.mousedown = self.rfcontext.actions.mouse
        self.move_prevmouse = None
        self.move_done_pressed = 'confirm'
        self.move_done_released = None
        self.move_cancelled = 'cancel'


    @RFTool_Contours.FSM_State('shift')
    @RFTool_Contours.dirty_when_done
    @profiler.function
    def modal_shift(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        # only update cut on timer events and when mouse has moved
        if not self.rfcontext.actions.timer: return
        if self.move_prevmouse == self.rfcontext.actions.mouse: return
        self.move_prevmouse = self.rfcontext.actions.mouse

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        shift_offset = self.rfcontext.drawing.unscale(self.rot_perp2D.dot(delta)) / 1000
        up_dir = self.rfcontext.Vec_up()

        raycast,project = self.rfcontext.raycast_sources_Point2D,self.rfcontext.Point_to_Point2D
        for i_cloop in range(len(self.move_cloops)):
            cloop  = self.move_cloops[i_cloop]
            cl_cut = self.move_cuts[i_cloop]
            if not cl_cut: continue
            shift_dir = 1 if cl_cut.get_normal().dot(self.rot_axis) > 0 else -1

            verts  = self.move_verts[i_cloop]
            dists  = self.move_dists[i_cloop]
            proj_dists = self.move_proj_dists[i_cloop]
            circumference = self.move_circumferences[i_cloop]

            lc = cl_cut.circumference
            shft = (cl_cut.offset + shift_offset * shift_dir * lc) % lc
            ndists = [shft] + [0.999 * lc * (d/circumference) for d in dists]
            i,dist = 0,ndists[0]
            l = len(ndists)-1 if cloop.connected else len(ndists)
            for c0,c1 in cl_cut.iter_pts(repeat=True):
                d = (c1-c0).length
                while dist - d <= 0:
                    # create new vert between c0 and c1
                    p = c0 + (c1 - c0) * (dist / d) + (cloop.plane.n * proj_dists[i])
                    p,n,_,_ = self.rfcontext.nearest_sources_Point(p)
                    verts[i].co = p
                    verts[i].normal = n
                    i += 1
                    if i == l: break
                    dist += ndists[i]
                dist -= d
                if i == l: break

            self.rfcontext.update_verts_faces(verts)


    @RFTool_Contours.FSM_State('move', 'can enter')
    def move_can_enter(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges, min_length=2)
        return sel_loops or sel_strings

    @RFTool_Contours.FSM_State('move', 'enter')
    def move_enter(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges, min_length=2)
        after_action = self.rfcontext.actions.pressed('action')

        # prefer to move loops over strings
        if sel_loops: self.move_cloops = [Contours_Loop(loop, True) for loop in sel_loops]
        else: self.move_cloops = [Contours_Loop(string, False) for string in sel_strings]
        self.move_verts = [[bmv for bmv in cloop.verts] for cloop in self.move_cloops]
        self.move_pts = [[Point(pt) for pt in cloop.pts] for cloop in self.move_cloops]
        self.move_dists = [list(cloop.dists) for cloop in self.move_cloops]
        self.move_circumferences = [cloop.circumference for cloop in self.move_cloops]
        self.move_origins = [cloop.plane.o for cloop in self.move_cloops]
        self.move_proj_dists = [list(cloop.proj_dists) for cloop in self.move_cloops]

        self.rfcontext.undo_push('move contours')

        self.mousedown = self.rfcontext.actions.mouse
        self.move_prevmouse = None
        if after_action:
            self.move_done_pressed = None
            self.move_done_released = 'action'
        else:
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
        self.move_cancelled = 'cancel'

    @RFTool_Contours.FSM_State('move')
    @RFTool_Contours.dirty_when_done
    @profiler.function
    def move(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        # only update cut on timer events and when mouse has moved
        if not self.rfcontext.actions.timer: return
        if self.move_prevmouse == self.rfcontext.actions.mouse: return
        self.move_prevmouse = self.rfcontext.actions.mouse

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)

        raycast,project = self.rfcontext.raycast_sources_Point2D,self.rfcontext.Point_to_Point2D
        for i_cloop in range(len(self.move_cloops)):
            cloop  = self.move_cloops[i_cloop]
            verts  = self.move_verts[i_cloop]
            pts    = self.move_pts[i_cloop]
            dists  = self.move_dists[i_cloop]
            origin = self.move_origins[i_cloop]
            proj_dists = self.move_proj_dists[i_cloop]
            circumference = self.move_circumferences[i_cloop]

            depth = self.rfcontext.Point_to_depth(origin)
            origin2D_new = self.rfcontext.Point_to_Point2D(origin) + delta
            origin_new = self.rfcontext.Point2D_to_Point(origin2D_new, depth)
            plane_new = Plane(origin_new, cloop.plane.n)
            ray_new = self.rfcontext.Point2D_to_Ray(origin2D_new)
            crawl = self.rfcontext.plane_intersection_crawl(ray_new, plane_new, walk=True)
            if not crawl: continue
            crawl_pts = [c for _,_,_,c in crawl]
            connected = crawl[0][0] is not None
            crawl_pts,connected = self.rfcontext.clip_pointloop(crawl_pts, connected)
            if not crawl_pts or connected != cloop.connected: continue
            cl_cut = Contours_Loop(crawl_pts, connected)

            cl_cut.align_to(cloop)
            lc = cl_cut.circumference
            ndists = [cl_cut.offset] + [0.999 * lc * (d/circumference) for d in dists]
            i,dist = 0,ndists[0]
            l = len(ndists)-1 if cloop.connected else len(ndists)
            for c0,c1 in cl_cut.iter_pts(repeat=True):
                d = max(0.000001, (c1-c0).length)
                while dist - d <= 0:
                    # create new vert between c0 and c1
                    p = c0 + (c1 - c0) * (dist / d) + (cloop.plane.n * proj_dists[i])
                    p,_,_,_ = self.rfcontext.nearest_sources_Point(p)
                    verts[i].co = p
                    i += 1
                    if i == l: break
                    dist += ndists[i]
                dist -= d
                if i == l: break

            self.rfcontext.update_verts_faces(verts)


    @RFTool_Contours.FSM_State('rotate', 'can enter')
    def rotate_can_enter(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges, min_length=2)
        return sel_loops or sel_strings

    @RFTool_Contours.FSM_State('rotate', 'enter')
    def rotate_enter(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges, min_length=2)

        # prefer to move loops over strings
        if sel_loops: self.move_cloops = [Contours_Loop(loop, True) for loop in sel_loops]
        else: self.move_cloops = [Contours_Loop(string, False) for string in sel_strings]
        self.move_verts = [[bmv for bmv in cloop.verts] for cloop in self.move_cloops]
        self.move_pts = [[Point(pt) for pt in cloop.pts] for cloop in self.move_cloops]
        self.move_dists = [list(cloop.dists) for cloop in self.move_cloops]
        self.move_circumferences = [cloop.circumference for cloop in self.move_cloops]
        self.move_origins = [cloop.plane.o for cloop in self.move_cloops]
        self.move_proj_dists = [list(cloop.proj_dists) for cloop in self.move_cloops]

        self.rfcontext.undo_push('rotate contours')

        self.mousedown = self.rfcontext.actions.mouse

        self.rotate_about = self.rfcontext.Point_to_Point2D(sum(self.move_origins, Vec((0,0,0))) / len(self.move_origins))
        self.rotate_start = math.atan2(self.rotate_about.y - self.mousedown.y, self.rotate_about.x - self.mousedown.x)

        self.move_prevmouse = None
        self.move_done_pressed = 'confirm'
        self.move_done_released = None
        self.move_cancelled = 'cancel'

    @RFTool_Contours.FSM_State('rotate')
    @RFTool_Contours.dirty_when_done
    @profiler.function
    def modal_rotate(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        # only update cut on timer events and when mouse has moved
        if not self.rfcontext.actions.timer: return
        if self.move_prevmouse == self.rfcontext.actions.mouse: return
        self.move_prevmouse = self.rfcontext.actions.mouse

        delta = Vec2D(self.rfcontext.actions.mouse - self.rotate_about)
        rotate = (math.atan2(delta.y, delta.x) - self.rotate_start + math.pi) % (math.pi * 2)

        raycast,project = self.rfcontext.raycast_sources_Point2D,self.rfcontext.Point_to_Point2D
        for i_cloop in range(len(self.move_cloops)):
            cloop  = self.move_cloops[i_cloop]
            verts  = self.move_verts[i_cloop]
            pts    = self.move_pts[i_cloop]
            dists  = self.move_dists[i_cloop]
            origin = self.move_origins[i_cloop]
            proj_dists = self.move_proj_dists[i_cloop]
            circumference = self.move_circumferences[i_cloop]

            origin2D = self.rfcontext.Point_to_Point2D(origin)
            ray = self.rfcontext.Point_to_Ray(origin)
            rmat = Matrix.Rotation(rotate, 4, -ray.d)
            normal = matrix_vector_mult(rmat, cloop.plane.n)
            plane = Plane(cloop.plane.o, normal)
            ray = self.rfcontext.Point2D_to_Ray(origin2D)
            crawl = self.rfcontext.plane_intersection_crawl(ray, plane, walk=True)
            if not crawl: continue
            crawl_pts = [c for _,_,_,c in crawl]
            connected = crawl[0][0] is not None
            crawl_pts,connected = self.rfcontext.clip_pointloop(crawl_pts, connected)
            if not crawl_pts or connected != cloop.connected: continue
            cl_cut = Contours_Loop(crawl_pts, connected)

            cl_cut.align_to(cloop)
            lc = cl_cut.circumference
            ndists = [cl_cut.offset] + [0.999 * lc * (d/circumference) for d in dists]
            i,dist = 0,ndists[0]
            l = len(ndists)-1 if cloop.connected else len(ndists)
            for c0,c1 in cl_cut.iter_pts(repeat=True):
                d = (c1-c0).length
                d = max(0.00000001, d)
                while dist - d <= 0:
                    # create new vert between c0 and c1
                    p = c0 + (c1 - c0) * (dist / d) + (cloop.plane.n * proj_dists[i])
                    p,_,_,_ = self.rfcontext.nearest_sources_Point(p)
                    verts[i].co = p
                    i += 1
                    if i == l: break
                    dist += ndists[i]
                dist -= d
                if i == l: break

            self.rfcontext.update_verts_faces(verts)



    @RFWidget_Line.on_action
    def new_line(self):
        xy0,xy1 = self.rfwidget.line2D
        if (xy1-xy0).length < 0.001: return
        xy01 = xy0 + (xy1-xy0) / 2
        plane = self.rfcontext.Point2D_to_Plane(xy0, xy1)
        ray = self.rfcontext.Point2D_to_Ray(xy01)
        self.new_cut(ray, plane, walk=False, check_hit=xy01)


    @RFTool_Contours.Draw('post2d')
    def draw_postpixel(self):
        point_to_point2d = self.rfcontext.Point_to_Point2D
        up = self.rfcontext.Vec_up()
        size_to_size2D = self.rfcontext.size_to_size2D
        text_draw2D = self.rfcontext.drawing.text_draw2D
        self.rfcontext.drawing.set_font_size(12)

        bmv_count = {}

        for loop_data in self.loops_data:
            loop = loop_data['loop']
            radius = loop_data['radius']
            count = loop_data['count']
            plane = loop_data['plane']
            cl = loop_data['cl']

            # draw segment count label
            cos = [point_to_point2d(vert.co) for vert in loop]
            if any(cos):
                loop = [(bmv,co) for bmv,co in zip(loop,cos) if co]
                bmv = max(loop, key=lambda bmvp2d:bmvp2d[1].y)[0]
                if bmv not in bmv_count: bmv_count[bmv] = []
                bmv_count[bmv].append( (count, True) )

            # draw arrows
            if self.show_arrows:
                self.drawing.line_width(2.0)
                p0 = point_to_point2d(plane.o)
                p1 = point_to_point2d(plane.o+plane.n*0.02)
                if p0 and p1:
                    bgl.glColor4f(1,1,0,0.5)
                    draw2D_arrow(p0, p1)
                p1 = point_to_point2d(plane.o+cl.up_dir*0.02)
                if p0 and p1:
                    bgl.glColor4f(1,0,1,0.5)
                    draw2D_arrow(p0, p1)

        for string_data in self.strings_data:
            string = string_data['string']
            count = string_data['count']
            plane = string_data['plane']

            # draw segment count label
            cos = [point_to_point2d(vert.co) for vert in string]
            if any(cos):
                string = [(bmv,co) for bmv,co in zip(string,cos) if co]
                bmv = max(string, key=lambda bmvp2d:bmvp2d[1].y)[0]
                if bmv not in bmv_count: bmv_count[bmv] = []
                bmv_count[bmv].append( (count, False) )

            # draw arrows
            if self.show_arrows:
                p0 = point_to_point2d(plane.o)
                p1 = point_to_point2d(plane.o+plane.n*0.02)
                if p0 and p1:
                    bgl.glColor4f(1,1,0,0.5)
                    draw2D_arrow(p0, p1)
                p1 = point_to_point2d(plane.o+cl.up_dir*0.02)
                if p0 and p1:
                    bgl.glColor4f(1,0,1,0.5)
                    draw2D_arrow(p0, p1)

        for bmv in bmv_count.keys():
            counts = bmv_count[bmv]
            counts = sorted([c for c,_ in counts])
            s = ','.join(map(str, counts))
            xy = point_to_point2d(bmv.co)
            xy.y += 10
            text_draw2D(s, xy, color=(1,1,0,1), dropshadow=(0,0,0,0.5))

        # # draw new cut info
        # if self.show_cut:
        #     for cl in self.cuts:
        #         plane = cl.plane
        #         self.drawing.line_width(2.0)
        #         p0 = point_to_point2d(plane.o)
        #         p1 = point_to_point2d(plane.o+plane.n*0.02)
        #         if p0 and p1:
        #             bgl.glColor4f(1,1,0,0.5)
        #             draw2D_arrow(p0, p1)
        #         p1 = point_to_point2d(plane.o+cl.up_dir*0.02)
        #         if p0 and p1:
        #             bgl.glColor4f(1,0,1,0.5)
        #             draw2D_arrow(p0, p1)

        # if self.mode == 'rotate' and self.rotate_about:
        #     bgl.glEnable(bgl.GL_BLEND)
        #     bgl.glColor4f(1,1,0.1,1)
        #     self.drawing.enable_stipple()
        #     self.drawing.line_width(2.0)
        #     bgl.glBegin(bgl.GL_LINES)
        #     bgl.glVertex2f(*self.rotate_about)
        #     bgl.glVertex2f(*self.rfcontext.actions.mouse)
        #     bgl.glEnd()
        #     self.drawing.disable_stipple()

        # if self.mode == 'shift' and self.shift_about:
        #     bgl.glEnable(bgl.GL_BLEND)
        #     bgl.glColor4f(1,1,0.1,1)
        #     self.drawing.enable_stipple()
        #     self.drawing.line_width(2.0)
        #     bgl.glBegin(bgl.GL_LINES)
        #     bgl.glVertex2f(*(self.shift_about + self.rot_axis2D * 1000))
        #     bgl.glVertex2f(*(self.shift_about - self.rot_axis2D * 1000))
        #     bgl.glEnd()
        #     self.drawing.disable_stipple()
