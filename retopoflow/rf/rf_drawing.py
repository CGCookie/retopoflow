'''
Copyright (C) 2022 CG Cookie
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

import os
import bpy
import math
import time
import urllib

from mathutils import Vector

from ...addon_common.cookiecutter.cookiecutter import CookieCutter

from ...addon_common.common import gpustate
from ...addon_common.common.drawing import DrawCallbacks
from ...addon_common.common.globals import Globals
from ...addon_common.common.profiler import profiler
from ...addon_common.common.debug import tprint
from ...addon_common.common.hasher import Hasher
from ...addon_common.common.maths import Point, Point2D, Vec2D, XForm, clamp
from ...addon_common.common.maths import matrix_normal, Direction
from ...config.options import options, visualization


class RetopoFlow_Drawing:
    def get_view_version(self):
        return Hasher(self.actions.r3d.view_matrix, self.actions.space.lens, self.actions.r3d.view_distance)

    def setup_drawing(self):
        def callback():
            Globals.drawing.update_dpi()
            source_opts = visualization.get_source_settings()
            target_opts = visualization.get_target_settings()
            self.rftarget_draw.replace_opts(target_opts)
            # self.document.body.dirty(cause='--> options changed', children=True)
            for d in self.rfsources_draw: d.replace_opts(source_opts)
        options.add_callback(callback)
        self._draw_count = 0

    @DrawCallbacks.on_predraw()
    def predraw(self):
        if not self.loading_done: return
        self.update(timer=False)
        self._draw_count += 1

    @DrawCallbacks.on_draw('post3d')
    def draw_target_and_sources(self):
        if not self.actions.r3d: return
        if not self.loading_done: return
        # if self.fps_low_warning: return     # skip drawing if low FPS warning is showing

        buf_matrix_target = self.rftarget_draw.rfmesh.xform.mx_p
        buf_matrix_target_inv = self.rftarget_draw.rfmesh.xform.imx_p
        buf_matrix_view = self.actions.r3d.view_matrix
        buf_matrix_view_invtrans = matrix_normal(self.actions.r3d.view_matrix)
        buf_matrix_proj = self.actions.r3d.window_matrix
        view_forward = self.Vec_forward()

        gpustate.blend('ALPHA')

        if options['symmetry view'] != 'None' and self.rftarget.mirror_mod.xyz:
            if options['symmetry view'] in {'Edge', 'Face'}:
                # get frame of target, used for symmetry decorations on sources
                ft = self.rftarget.get_frame()
                # render sources
                for rs,rfs in zip(self.rfsources, self.rfsources_draw):
                    rfs.draw(
                        view_forward, self.unit_scaling_factor,
                        buf_matrix_target, buf_matrix_target_inv,
                        buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj,
                        1.00, 0.05, False, 0.5,
                        False,
                        symmetry=self.rftarget.mirror_mod.xyz,
                        symmetry_view=options['symmetry view'],
                        symmetry_effect=options['symmetry effect'],
                        symmetry_frame=ft,
                    )
            elif options['symmetry view'] == 'Plane':
                # draw symmetry planes
                gpustate.depth_test('LESS_EQUAL')
                gpustate.culling('NONE')
                drawing = Globals.drawing
                a = pow(options['symmetry effect'], 2.0) # fudge this value, because effect is different with plane than edge/face
                r = (1.0, 0.2, 0.2, a)
                g = (0.2, 1.0, 0.2, a)
                b = (0.2, 0.2, 1.0, a)
                w2l = self.rftarget_draw.rfmesh.xform.w2l_point
                l2w = self.rftarget_draw.rfmesh.xform.l2w_point
                # for rfs in self.rfsources:
                #     corners = [self.Point_to_Point2D(l2w(p)) for p in rfs.get_local_bbox(w2l).corners]
                #     drawing.draw2D_lines(corners, (1,1,1,1))
                corners = [ c for s in self.rfsources for c in s.get_local_bbox(w2l).corners ]
                mx, Mx = min(c.x for c in corners), max(c.x for c in corners)
                my, My = min(c.y for c in corners), max(c.y for c in corners)
                mz, Mz = min(c.z for c in corners), max(c.z for c in corners)
                cx, cy, cz = mx + (Mx - mx) / 2, my + (My - my) / 2, mz + (Mz - mz) / 2
                mx, Mx = cx + (mx - cx) * 1.2, cx + (Mx - cx) * 1.2
                my, My = cy + (my - cy) * 1.2, cy + (My - cy) * 1.2
                mz, Mz = cz + (mz - cz) * 1.2, cz + (Mz - cz) * 1.2
                if self.rftarget.mirror_mod.x:
                    quad = [ l2w(Point((0, my, mz))), l2w(Point((0, my, Mz))), l2w(Point((0, My, Mz))), l2w(Point((0, My, mz))) ]
                    drawing.draw3D_triangles([quad[0], quad[1], quad[2], quad[0], quad[2], quad[3]], [r, r, r, r, r, r])
                if self.rftarget.mirror_mod.y:
                    quad = [ l2w(Point((mx, 0, mz))), l2w(Point((mx, 0, Mz))), l2w(Point((Mx, 0, Mz))), l2w(Point((Mx, 0, mz))) ]
                    drawing.draw3D_triangles([quad[0], quad[1], quad[2], quad[0], quad[2], quad[3]], [g, g, g, g, g, g])
                if self.rftarget.mirror_mod.z:
                    quad = [ l2w(Point((mx, my, 0))), l2w(Point((mx, My, 0))), l2w(Point((Mx, My, 0))), l2w(Point((Mx, my, 0))) ]
                    drawing.draw3D_triangles([quad[0], quad[1], quad[2], quad[0], quad[2], quad[3]], [b, b, b, b, b, b])

        # render target
        gpustate.blend('ALPHA')
        if True:
            alpha_above,alpha_below = options['target alpha'],options['target hidden alpha']
            cull_backfaces = options['target cull backfaces']
            alpha_backface = options['target alpha backface']
            self.rftarget_draw.draw(
                view_forward, self.unit_scaling_factor,
                buf_matrix_target, buf_matrix_target_inv,
                buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj,
                alpha_above, alpha_below, cull_backfaces, alpha_backface,
                True
            )

    @DrawCallbacks.on_draw('post3d')
    def draw_greasemarks(self):
        return
        # if not self.actions.r3d: return
        # # THE FOLLOWING CODE NEEDS UPDATED TO NOT USE GLBEGIN!
        # # grease marks
        # b_g_l.glBegin(b_g_l.GL_QUADS)
        # for stroke_data in self.grease_marks:
        #     b_g_l.glColor4f(*stroke_data['color'])
        #     t = stroke_data['thickness']
        #     s0,p0,n0,d0,d1 = None,None,None,None,None
        #     for s1 in stroke_data['marks']:
        #         p1,n1 = s1
        #         if p0 and p1:
        #             v01 = p1 - p0
        #             if d0 is None: d0 = Direction(v01.cross(n0))
        #             d1 = Direction(v01.cross(n1))
        #             b_g_l.glVertex3f(*(p0-d0*t+n0*0.001))
        #             b_g_l.glVertex3f(*(p0+d0*t+n0*0.001))
        #             b_g_l.glVertex3f(*(p1+d1*t+n1*0.001))
        #             b_g_l.glVertex3f(*(p1-d1*t+n1*0.001))
        #         s0,p0,n0,d0 = s1,p1,n1,d1
        # b_g_l.glEnd()


    ##################################
    # RFTool Drawing

    @DrawCallbacks.on_draw('pre3d')
    def draw_tool_pre3d(self):
        if not self.loading_done: return
        if self.fsm.state == 'pie menu': return
        self.rftool._draw_pre3d()

    @DrawCallbacks.on_draw('post3d')
    def draw_tool_post3d(self):
        if not self.loading_done: return
        if self.fsm.state == 'pie menu': return
        self.rftool._draw_post3d()

    @DrawCallbacks.on_draw('post2d')
    def draw_tool_post2d(self):
        if not self.loading_done: return
        if self.fsm.state == 'pie menu': return
        self.rftool._draw_post2d()


    #############################
    # RFWidget Drawing

    @DrawCallbacks.on_draw('pre3d')
    def draw_widget_pre3d(self):
        if not self.loading_done: return
        if not self.rftool.rfwidget: return
        if self._nav: return
        if self._hover_ui: return
        if self.fsm.state == 'pie menu': return
        self.rftool.rfwidget._draw_pre3d()

    @DrawCallbacks.on_draw('post3d')
    def draw_widget_post3d(self):
        if not self.loading_done: return
        if not self.rftool.rfwidget: return
        if self._nav: return
        if self._hover_ui: return
        if self.fsm.state == 'pie menu': return
        self.rftool.rfwidget._draw_post3d()

    @DrawCallbacks.on_draw('post2d')
    def draw_widget_post2d(self):
        if not self.loading_done: return
        if not self.rftool.rfwidget: return
        if self._nav: return
        if self._hover_ui: return
        if self.fsm.state == 'pie menu': return
        self.rftool.rfwidget._draw_post2d()

