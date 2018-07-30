'''
Copyright (C) 2018 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

from .rftool import RFTool

from ..common.debug import dprint
from ..common.profiler import profiler
from ..common.logger import Logger
from ..common.maths import (
    Point, Vec, Direction,
    Point2D, Vec2D,
    Accel2D,
    clamp, mid,
)
from ..common.bezier import CubicBezierSpline, CubicBezier
from ..common.shaders import circleShader, edgeShortenShader, arrowShader
from ..common.utils import iter_pairs, iter_running_sum, min_index, max_index
from ..common.ui import (
    UI_Image, UI_Number, UI_BoolValue,
    UI_Button, UI_Label,
    UI_Container, UI_EqualContainer
    )
from ..keymaps import default_rf_keymaps
from ..options import options, themes
from ..help import help_stretch

from .rftool_stretch_utils import (
    process_stroke_filter, process_stroke_source, icp
    #find_edge_cycles,
    #find_edge_strips, get_strip_verts,
    #restroke, walk_to_corner,
)



@RFTool.is_experimental
@RFTool.action_call('stretch tool')
class RFTool_Stretch(RFTool):
    def init(self):
        self.FSM['select'] = self.modal_select
        self.FSM['deselect'] = self.modal_deselect

    def name(self): return "Stretch"
    def icon(self): return "rf_stretch_icon"
    def description(self): return 'Stretch selected geometry to fit stroke.'
    def helptext(self): return help_stretch
    def get_label(self): return 'Stretch (%s)' % ','.join(default_rf_keymaps['stretch tool'])
    def get_tooltip(self): return 'Stretch (%s)' % ','.join(default_rf_keymaps['stretch tool'])

    def start(self):
        self.rfwidget.set_widget('brush stroke', color=(0.7, 1.0, 0.7))
        self.rfwidget.set_stroke_callback(self.stroke)
        self.stroke3D = []
        self.moves3D = []
        self.process = None

    def get_ui_icon(self):
        self.ui_icon = UI_Image('stretch_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon

    def get_ui_options(self):
        pass

    @profiler.profile
    def modal_main(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        mouse = self.rfcontext.actions.mouse
        self.vis_accel = self.rfcontext.get_vis_accel()

        self.rfwidget.set_widget('brush stroke')

        if self.rfcontext.actions.timer and self.process: self.process()

        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('select')
            self.rfcontext.deselect_all()
            edge, _ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if not edge: return
            self.rfcontext.select(edge)
            return 'select'

        if self.rfcontext.actions.pressed('select add'):
            edge, _ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
            if not edge: return
            if edge.select:
                self.rfcontext.undo_push('deselect')
                return 'deselect'
            self.rfcontext.undo_push('select add')
            self.rfcontext.select(edge, supparts=False, only=False)
            return 'select'

    @profiler.profile
    def modal_select(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        if not self.rfcontext.actions.using(['select','select add']):
            return 'main'

        edge, _ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
        if not edge: return
        v0,v1 = edge.verts
        if v1.select: v0,v1 = v1,v0
        if not v0.select:
            return
        if v1.select:
            self.rfcontext.select(edge, supparts=False, only=False)
            return
        p0,p1 = Point_to_Point2D(v0.co), Point_to_Point2D(v1.co)
        v01, v0m = (p1 - p0), (self.rfcontext.actions.mouse - p0)
        l01 = v01.length
        l0m_proj = (v01/l01).dot(v0m)
        if l0m_proj / l01 < 0.25:
            return
        self.rfcontext.select(edge, supparts=False, only=False)

    @profiler.profile
    def modal_deselect(self):
        if not self.rfcontext.actions.using(['select','select add']):
            return 'main'
        edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
        if edge and edge.select: self.rfcontext.deselect(edge)


    @RFTool.dirty_when_done
    def stroke(self):
        # called when artist finishes a stroke

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        raycast_sources_Point2D = self.rfcontext.raycast_sources_Point2D
        accel_nearest2D_vert = self.rfcontext.accel_nearest2D_vert

        brushsize = self.rfwidget.size
        brushsize3d = self.rfwidget.size * self.rfwidget.scale

        # get selected verts
        visverts = self.rfcontext.visible_verts()
        selverts = self.rfcontext.get_selected_verts() & visverts
        if len(selverts) < 2:
            print('no selected verts')
            return

        # filter stroke down where each pt is at least 1px away to eliminate local wiggling
        s2d = self.rfwidget.stroke2D
        s2d = process_stroke_filter(s2d)
        s2d = process_stroke_source(s2d, raycast_sources_Point2D, Point_to_Point2D=Point_to_Point2D, clamp_point_to_symmetry=self.rfcontext.clamp_point_to_symmetry)
        s3d = [raycast_sources_Point2D(s)[0] for s in s2d]
        stroke = [s3 for (s2, s3) in zip(s2d, s3d) if s3]
        if len(stroke) < 2:
            print('no stroke')
            return
        stroke_accel = Accel2D.simple_verts(stroke, Point_to_Point2D)

        def nearestdist(v):
            return min((Point_to_Point2D(v.co) - Point_to_Point2D(sv.co)).length for sv in selverts)
        def get_neighbors(s, depth=0):
            if type(s) is not set: s = {s}
            os = set(s)
            if depth == 2: return s
            for v in os:
                s |= {ov for e in v.link_edges for ov in e.verts}
                s |= {ov for f in v.link_faces for ov in f.verts}
            s |= get_neighbors(s, depth=depth+1)
            if depth == 0: s -= os
            return s
            return self.vis_accel.get_verts(Point_to_Point2D(v.co), brushsize)
        def get_verts_near(v):
            return {ov for ov in visverts if (ov.co - v.co).length < brushsize3d}
            return self.vis_accel.get_verts(Point_to_Point2D(v.co), brushsize)

        # get all visible vertices within brush distance away
        moveverts = set(mv for sv in selverts for mv in get_verts_near(sv)) & visverts
        moveverts = {
            mv: {
                'neighbors': [
                    (ov, (Point_to_Point2D(ov.co) - Point_to_Point2D(mv.co)).length)
                    for ov in get_neighbors(mv) if ov != mv and ov in visverts
                ],
                'effect': pow(mid(0.0, 1.0, 1.0 - nearestdist(mv) / brushsize), 1.0),
            }
            for mv in moveverts
        }
        allverts = {ov for mv in moveverts for (ov,od) in moveverts[mv]['neighbors'] if ov in visverts} | set(moveverts.keys())

        self.rfcontext.undo_push('stretch')
        self.stroke3D = stroke
        self.moves3D = [(mv, moveverts[mv]['effect']) for mv in moveverts]
        # apply ICP
        fn_move = icp([Point_to_Point2D(v.co) for v in selverts], [Point_to_Point2D(s) for s in stroke], stroke_accel.nearest_vert)
        steps = 10
        iterations = 100
        force = 0.02
        vert2d = {mv:Point_to_Point2D(mv.co) for mv in visverts}
        sv_pos = [
            [(sv, vert2d[sv] + (fn_move(vert2d[sv]) - vert2d[sv]) * i / steps) for sv in selverts]
            for i in range(steps+1)
        ]

        istep = 0
        def process():
            nonlocal istep, sv_pos, vert2d, iterations, allverts, moveverts

            print(istep)
            step = sv_pos[istep]

            # move selected verts a little closer to target shape
            for sv,sv2d in step: vert2d[sv] = sv2d

            # update all other verts
            for iteration in range(iterations):
                nvert2d = {mv:Point2D(vert2d[mv]) for mv in allverts if mv in vert2d}
                for mv in moveverts:
                    e = moveverts[mv]['effect']
                    for ov,od in moveverts[mv]['neighbors']:
                        oe = moveverts[ov]['effect'] if ov in moveverts else 0.0
                        v = vert2d[ov] - vert2d[mv]
                        d = v.length
                        a = (od - d) * force / d
                        nvert2d[mv] -= v * (a * e)
                        nvert2d[ov] += v * (a * oe)
                vert2d.update(nvert2d)

            # move selected verts back to current step
            for (sv, sv2d) in step: vert2d[sv] = sv2d

            # update
            for mv in allverts: self.rfcontext.set2D_vert(mv, vert2d[mv])
            self.rfcontext.dirty()

            istep += 1
            if istep > steps:
                self.process = None
                self.moves3D = []

        self.process = process

    def draw_postpixel(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        self.drawing.point_size(10)
        bgl.glBegin(bgl.GL_POINTS)
        for (mv, e) in self.moves3D:
            bgl.glColor4f(e, 0.1, 0.1, 1.0)
            bgl.glVertex2f(*Point_to_Point2D(mv.co))
        bgl.glEnd()