'''
Copyright (C) 2021 CG Cookie
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
import bgl
import math
import time
import urllib

from mathutils import Vector

from ...addon_common.cookiecutter.cookiecutter import CookieCutter

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

    @CookieCutter.PreDraw
    def predraw(self):
        if not self.loading_done: return
        self.update(timer=False)

    @CookieCutter.Draw('post3d')
    def draw_target_and_sources(self):
        if not self.actions.r3d: return
        if not self.loading_done: return
        # if self.fps_low_warning: return     # skip drawing if low FPS warning is showing

        buf_matrix_target = self.rftarget_draw.rfmesh.xform.mx_p # self.rftarget_draw.buf_matrix_model
        buf_matrix_target_inv = self.rftarget_draw.rfmesh.xform.imx_p # self.rftarget_draw.buf_matrix_inverse
        buf_matrix_view = self.actions.r3d.view_matrix # XForm.to_bglMatrix(self.actions.r3d.view_matrix)
        buf_matrix_view_invtrans = matrix_normal(self.actions.r3d.view_matrix) # XForm.to_bglMatrix(matrix_normal(self.actions.r3d.view_matrix))
        buf_matrix_proj = self.actions.r3d.window_matrix # XForm.to_bglMatrix(self.actions.r3d.window_matrix)
        view_forward = self.Vec_forward()  # self.actions.r3d.view_rotation * Vector((0,0,-1))

        # bgl.glEnable(bgl.GL_MULTISAMPLE)
        # bgl.glEnable(bgl.GL_LINE_SMOOTH)
        # bgl.glHint(bgl.GL_LINE_SMOOTH_HINT, bgl.GL_NICEST)
        bgl.glEnable(bgl.GL_BLEND)
        # bgl.glEnable(bgl.GL_POINT_SMOOTH)

        if options['symmetry view'] != 'None' and self.rftarget.mirror_mod.xyz:
            # get frame of target, used for symmetry decorations on sources
            ft = self.rftarget.get_frame()
            # render sources
            for rs,rfs in zip(self.rfsources, self.rfsources_draw):
                rfs.draw(
                    view_forward, self.unit_scaling_factor,
                    buf_matrix_target, buf_matrix_target_inv,
                    buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj,
                    1.00, 0.05, False, 0.5,
                    symmetry=self.rftarget.mirror_mod.xyz,
                    symmetry_view=options['symmetry view'],
                    symmetry_effect=options['symmetry effect'],
                    symmetry_frame=ft,
                )

        # render target
        # bgl.glEnable(bgl.GL_MULTISAMPLE)
        # bgl.glEnable(bgl.GL_LINE_SMOOTH)
        # bgl.glHint(bgl.GL_LINE_SMOOTH_HINT, bgl.GL_NICEST)
        bgl.glEnable(bgl.GL_BLEND)
        if True:
            alpha_above,alpha_below = options['target alpha'],options['target hidden alpha']
            cull_backfaces = options['target cull backfaces']
            alpha_backface = options['target alpha backface']
            self.rftarget_draw.draw(
                view_forward, self.unit_scaling_factor,
                buf_matrix_target, buf_matrix_target_inv,
                buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj,
                alpha_above, alpha_below, cull_backfaces, alpha_backface
            )

    @CookieCutter.Draw('post3d')
    def draw_greasemarks(self):
        return
        if not self.actions.r3d: return
        # THE FOLLOWING CODE NEEDS UPDATED TO NOT USE GLBEGIN!
        # grease marks
        bgl.glBegin(bgl.GL_QUADS)
        for stroke_data in self.grease_marks:
            bgl.glColor4f(*stroke_data['color'])
            t = stroke_data['thickness']
            s0,p0,n0,d0,d1 = None,None,None,None,None
            for s1 in stroke_data['marks']:
                p1,n1 = s1
                if p0 and p1:
                    v01 = p1 - p0
                    if d0 is None: d0 = Direction(v01.cross(n0))
                    d1 = Direction(v01.cross(n1))
                    bgl.glVertex3f(*(p0-d0*t+n0*0.001))
                    bgl.glVertex3f(*(p0+d0*t+n0*0.001))
                    bgl.glVertex3f(*(p1+d1*t+n1*0.001))
                    bgl.glVertex3f(*(p1-d1*t+n1*0.001))
                s0,p0,n0,d0 = s1,p1,n1,d1
        bgl.glEnd()


    ##################################
    # RFTool Drawing

    @CookieCutter.Draw('pre3d')
    def draw_tool_pre3d(self):
        if not self.loading_done: return
        if self.fsm.state == 'pie menu': return
        self.rftool._draw_pre3d()

    @CookieCutter.Draw('post3d')
    def draw_tool_post3d(self):
        if not self.loading_done: return
        if self.fsm.state == 'pie menu': return
        self.rftool._draw_post3d()

    @CookieCutter.Draw('post2d')
    def draw_tool_post2d(self):
        if not self.loading_done: return
        if self.fsm.state == 'pie menu': return
        self.rftool._draw_post2d()


    #############################
    # RFWidget Drawing

    @CookieCutter.Draw('pre3d')
    def draw_widget_pre3d(self):
        if not self.loading_done: return
        if not self.rftool.rfwidget: return
        if self._nav: return
        if self._hover_ui: return
        if self.fsm.state == 'pie menu': return
        self.rftool.rfwidget._draw_pre3d()

    @CookieCutter.Draw('post3d')
    def draw_widget_post3d(self):
        if not self.loading_done: return
        if not self.rftool.rfwidget: return
        if self._nav: return
        if self._hover_ui: return
        if self.fsm.state == 'pie menu': return
        self.rftool.rfwidget._draw_post3d()

    @CookieCutter.Draw('post2d')
    def draw_widget_post2d(self):
        if not self.loading_done: return
        if not self.rftool.rfwidget: return
        if self._nav: return
        if self._hover_ui: return
        if self.fsm.state == 'pie menu': return
        self.rftool.rfwidget._draw_post2d()

