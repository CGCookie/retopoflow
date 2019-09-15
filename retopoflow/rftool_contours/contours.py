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

import random

from .contours_ops import Contours_Ops
from .contours_utils import Contours_Utils
from .contours_utils import (
    find_loops,
    find_strings,
    loop_plane, loop_radius,
    Contours_Loop,
)

from ..rftool import RFTool
from ..rfwidgets.rfwidget_line import RFWidget_Line

from ...addon_common.common.drawing import Drawing, Cursors
from ...addon_common.common.maths import Point, Normal
from ...addon_common.common.utils import iter_pairs

class RFTool_Contours(RFTool):
    name        = 'Contours'
    description = 'Retopologize cylindrical forms, like arms and legs'
    icon        = 'contours_32.png'


class Contours(RFTool_Contours, Contours_Ops, Contours_Utils):
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

    def get_count(self):
        print('RFTool_Contours.get_count()!')
        return 24

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
