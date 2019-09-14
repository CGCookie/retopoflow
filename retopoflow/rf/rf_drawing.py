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
from ...addon_common.common.hasher import Hasher
from ...addon_common.common.maths import Point, Point2D, Vec2D, XForm, clamp
from ...addon_common.common.maths import matrix_normal, Direction
from ...config.options import options

# from ..keymaps import default_rf_keymaps


class RetopoFlow_Drawing:
    def get_view_version(self):
        return Hasher(self.actions.r3d.view_matrix, self.actions.space.lens)

    @CookieCutter.Draw('post3d')
    def draw_postview(self):
        if not self.actions.r3d: return
        # if self.fps_low_warning: return     # skip drawing if low FPS warning is showing

        buf_matrix_target = self.rftarget_draw.buf_matrix_model
        buf_matrix_target_inv = self.rftarget_draw.buf_matrix_inverse
        buf_matrix_view = XForm.to_bglMatrix(self.actions.r3d.view_matrix)
        buf_matrix_view_invtrans = XForm.to_bglMatrix(matrix_normal(self.actions.r3d.view_matrix))
        buf_matrix_proj = XForm.to_bglMatrix(self.actions.r3d.window_matrix)
        view_forward = self.Vec_forward()  # self.actions.r3d.view_rotation * Vector((0,0,-1))

        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_LINE_SMOOTH)
        bgl.glHint(bgl.GL_LINE_SMOOTH_HINT, bgl.GL_NICEST)
        bgl.glEnable(bgl.GL_BLEND)
        # bgl.glEnable(bgl.GL_POINT_SMOOTH)

        if options['symmetry view'] != 'None' and self.rftarget.mirror_mod.symmetry:
            # get frame of target, used for symmetry decorations on sources
            ft = self.rftarget.get_frame()
            with profiler.code('render sources'):
                for rs,rfs in zip(self.rfsources, self.rfsources_draw):
                    rfs.draw(
                        view_forward,
                        buf_matrix_target, buf_matrix_target_inv,
                        buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj,
                        1.00, 0.05, False, 0.5,
                        symmetry=self.rftarget.mirror_mod.symmetry,
                        symmetry_view=options['symmetry view'],
                        symmetry_effect=options['symmetry effect'],
                        symmetry_frame=ft,
                    )

        with profiler.code('render target'):
            alpha_above,alpha_below = options['target alpha'],options['target hidden alpha']
            cull_backfaces = options['target cull backfaces']
            alpha_backface = options['target alpha backface']
            self.rftarget_draw.draw(
                view_forward,
                buf_matrix_target, buf_matrix_target_inv,
                buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj,
                alpha_above, alpha_below, cull_backfaces, alpha_backface
            )

        # pr = profiler.start('grease marks')
        # bgl.glBegin(bgl.GL_QUADS)
        # for stroke_data in self.grease_marks:
        #     bgl.glColor4f(*stroke_data['color'])
        #     t = stroke_data['thickness']
        #     s0,p0,n0,d0,d1 = None,None,None,None,None
        #     for s1 in stroke_data['marks']:
        #         p1,n1 = s1
        #         if p0 and p1:
        #             v01 = p1 - p0
        #             if d0 is None: d0 = Direction(v01.cross(n0))
        #             d1 = Direction(v01.cross(n1))
        #             bgl.glVertex3f(*(p0-d0*t+n0*0.001))
        #             bgl.glVertex3f(*(p0+d0*t+n0*0.001))
        #             bgl.glVertex3f(*(p1+d1*t+n1*0.001))
        #             bgl.glVertex3f(*(p1-d1*t+n1*0.001))
        #         s0,p0,n0,d0 = s1,p1,n1,d1
        # bgl.glEnd()
        # pr.done()

        # pr = profiler.start('render other')
        # self.tool.draw_postview()
        # self.rfwidget.draw_postview()
        # pr.done()

        #time.sleep(0.5)


    ##################################
    # RFTool Drawing

    @CookieCutter.Draw('pre3d')
    def draw_tool_pre3d(self):
        self.rftool._draw_pre3d()

    @CookieCutter.Draw('post3d')
    def draw_tool_post3d(self):
        self.rftool._draw_post3d()

    @CookieCutter.Draw('post2d')
    def draw_tool_post2d(self):
        self.rftool._draw_post2d()


    #############################
    # RFWidget Drawing

    @CookieCutter.Draw('pre3d')
    def draw_widget_pre3d(self):
        if self.rftool.rfwidget:
            self.rftool.rfwidget._draw_pre3d()

    @CookieCutter.Draw('post3d')
    def draw_widget_post3d(self):
        if self.rftool.rfwidget:
            self.rftool.rfwidget._draw_post3d()

    @CookieCutter.Draw('post2d')
    def draw_widget_post2d(self):
        if self.rftool.rfwidget:
            self.rftool.rfwidget._draw_post2d()


    @profiler.function
    def draw_postpixel2(self):
        if not self.actions.r3d: return

        wtime,ctime = self.fps_time,time.time()
        self.frames += 1
        if ctime >= wtime + 1:
            self.fps = self.frames / (ctime - wtime)
            self.fps_list = self.fps_list[1:] + [self.fps]
            self.frames = 0
            self.fps_time = ctime

        if self.fps >= options['low fps threshold']: self.fps_low_start = ctime
        if ctime - self.fps_low_start > options['low fps time']:
            # exceeded allowed time for low fps
            if options['low fps warn'] and not hasattr(self, 'fps_warning_shown_already'):
                self.fps_warning_shown_already = True
                self.show_lowfps_warning()

        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_LINE_SMOOTH)
        bgl.glHint(bgl.GL_LINE_SMOOTH_HINT, bgl.GL_NICEST)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        try:
            rgn = self.actions.region
            sw,sh = rgn.width,rgn.height
            m = self.drawing.get_dpi_mult()

            if options['visualize counts']:
                count_str = 'v:%d  e:%d  f:%d' % self.get_target_geometry_counts()
                tw = self.drawing.get_text_width(count_str)
                th = self.drawing.get_text_height(count_str)
                self.drawing.text_draw2D(count_str, Point2D((sw-tw-10,th+10)), (1,1,1,0.25), dropshadow=(0,0,0,0.5), fontsize=12)

            if options['visualize fps'] and self.actions.region:
                with profiler.code('fps postpixel'):
                    bgl.glEnable(bgl.GL_BLEND)
                    lw,lh = len(self.fps_list),60
                    def p(x, y): return (sw - 10 + (-lw + x) * m, 30 + y * m)
                    def v(x, y): bgl.glVertex2f(*p(x,y))

                    bgl.glBegin(bgl.GL_QUADS)
                    bgl.glColor4f(0,0,0,0.2)
                    v(0, 0); v(lw, 0); v(lw, lh); v(0, lh)
                    bgl.glEnd()

                    bgl.glBegin(bgl.GL_LINES)
                    bgl.glColor4f(0.2,0.2,0.2,0.3)
                    for i in [10,20,30,40,50]:
                        v(0, i); v(lw, i)
                    bgl.glEnd()

                    if options['low fps warn']:
                        fw = options['low fps time']
                        fh = options['low fps threshold']
                        bgl.glBegin(bgl.GL_QUADS)
                        bgl.glColor4f(0.5,0.1,0.1,0.3)
                        v(lw - fw, 0); v(lw, 0); v(lw, fh); v(lw - fw, fh)
                        bgl.glEnd()

                    bgl.glBegin(bgl.GL_LINE_STRIP)
                    bgl.glColor4f(0.1,0.8,1.0,0.3)
                    for i in range(lw):
                        v(i, min(lh, self.fps_list[i]))
                    bgl.glEnd()

                    bgl.glBegin(bgl.GL_LINE_STRIP)
                    bgl.glColor4f(0,0,0,0.5)
                    v(0, 0); v(lw, 0); v(lw, lh); v(0, lh); v(0, 0)
                    bgl.glEnd()

                    self.drawing.text_draw2D('%2.2f' % self.fps, Point2D(p(2, lh - 2)), (1,1,1,0.5), fontsize=12)

            if not self.draw_ui:
                k = next(iter(default_rf_keymaps['toggle ui']))
                self.drawing.text_draw2D('Press %s to show UI' % k, Point2D((10, sh-10)), (1,1,1,0.25), fontsize=12)

            with profiler.code('tool draw postpixel'):
                self.tool.draw_postpixel()

            with profiler.code('widget draw postpixel'):
                self.rfwidget.draw_postpixel()

            with profiler.code('window manager draw postpixel'):
                self.window_debug_fps.set_label('FPS: %0.2f' % self.fps)
                self.window_debug_save.set_label('Time: %0.0f' % (self.time_to_save or float('inf')))
                self.window_manager.draw_postpixel(self.actions.context)

        except AssertionError as e:
            message,h = Globals.debugger.get_exception_info_and_hash()
            print(message)
            message = '\n'.join('- %s'%l for l in message.splitlines())
            self.alert_user(message=message, level='assert', msghash=h)
        except Exception as e:
            message,h = Globals.debugger.get_exception_info_and_hash()
            print(message)
            message = '\n'.join('- %s'%l for l in message.splitlines())
            self.alert_user(message=message, level='exception', msghash=h)
            #raise e

    @profiler.function
    def draw_preview2(self):
        if not self.actions.r3d: return

        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_LINE_SMOOTH)
        bgl.glHint(bgl.GL_LINE_SMOOTH_HINT, bgl.GL_NICEST)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_POINT_SMOOTH)
        bgl.glDisable(bgl.GL_DEPTH_TEST)

        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()

        if options['background gradient']:
            bgl.glBegin(bgl.GL_TRIANGLES)
            for i in range(0,360,10):
                r0,r1 = i*math.pi/180.0, (i+10)*math.pi/180.0
                x0,y0 = math.cos(r0)*2,math.sin(r0)*2
                x1,y1 = math.cos(r1)*2,math.sin(r1)*2
                bgl.glColor4f(0,0,0.01,0.0)
                bgl.glVertex2f(0,0)
                bgl.glColor4f(0,0,0.01,0.8)
                bgl.glVertex2f(x0,y0)
                bgl.glVertex2f(x1,y1)
            bgl.glEnd()

        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPopMatrix()
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPopMatrix()

    @profiler.function
    def draw_postview2(self):
        if not self.actions.r3d: return
        if self.fps_low_warning: return     # skip drawing if low FPS warning is showing

        buf_matrix_target = self.rftarget_draw.buf_matrix_model
        buf_matrix_target_inv = self.rftarget_draw.buf_matrix_inverse
        buf_matrix_view = XForm.to_bglMatrix(self.actions.r3d.view_matrix)
        buf_matrix_view_invtrans = XForm.to_bglMatrix(matrix_normal(self.actions.r3d.view_matrix))
        buf_matrix_proj = XForm.to_bglMatrix(self.actions.r3d.window_matrix)
        view_forward = self.actions.r3d.view_rotation * Vector((0,0,-1))

        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_LINE_SMOOTH)
        bgl.glHint(bgl.GL_LINE_SMOOTH_HINT, bgl.GL_NICEST)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        # get frame of target, used for symmetry decorations on sources
        ft = self.rftarget.get_frame()

        if options['symmetry view'] != 'None' and self.rftarget.symmetry:
            with profiler.code('render sources'):
                for rs,rfs in zip(self.rfsources, self.rfsources_draw):
                    rfs.draw(
                        view_forward,
                        buf_matrix_target, buf_matrix_target_inv,
                        buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj,
                        1.00, 0.05, False, 0.5,
                        symmetry=self.rftarget.symmetry, symmetry_view=options['symmetry view'],
                        symmetry_effect=options['symmetry effect'], symmetry_frame=ft
                    )

        with profiler.code('render target'):
            alpha_above,alpha_below = options['target alpha'],options['target hidden alpha']
            cull_backfaces = options['target cull backfaces']
            alpha_backface = options['target alpha backface']
            self.rftarget_draw.draw(
                view_forward,
                buf_matrix_target, buf_matrix_target_inv,
                buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj,
                alpha_above, alpha_below, cull_backfaces, alpha_backface
            )

        with profiler.code('grease marks'):
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

        with profiler.code('render other'):
            self.tool.draw_postview()
            self.rfwidget.draw_postview()

        # artificially slow down rendering (for testing purposes only)
        #time.sleep(0.5)
