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

from .rftool import RFTool

from ..common.profiler import profiler
from ..common.maths import Point, Point2D, Vec2D, XForm, clamp
from ..common.ui import Drawing
from ..common.ui import (
    UI_WindowManager,
    UI_Button, UI_Image,
    UI_Options,
    UI_Checkbox, UI_Checkbox2,
    UI_Label, UI_WrappedLabel, UI_Markdown,
    UI_Spacer, UI_Rule,
    UI_Container, UI_Collapsible, UI_EqualContainer,
    UI_IntValue,
    GetSet,
    )
from ..common import bmesh_render as bmegl
from ..common.globals import debugger
from ..common.maths import matrix_normal

from ..options import (
    retopoflow_version,
    retopoflow_profiler,
    retopoflow_issues_url,
    retopoflow_tip_url,
    options,
    themes,
    )

from ..help import help_general, firsttime_message


class RFContext_Drawing:
    def get_source_render_options(self):
        opts = {
            'poly color': (0.0, 0.0, 0.0, 0.0),
            'poly offset': 0.000008,
            'poly dotoffset': 1.0,
            'line width': 0.0,
            'point size': 0.0,
            'load edges': False,
            'load verts': False,
            'no selection': True,
            'no below': True,
            'triangles only': True,     # source bmeshes are triangles only!
            'cull backfaces': True,

            'normal offset': 0.0005,
            'focus mult': 0.01,
        }
        return opts

    def get_target_render_options(self):
        color_select = themes['select'] # self.settings.theme_colors_selection[options['color theme']]
        color_frozen = themes['frozen'] # self.settings.theme_colors_frozen[options['color theme']]
        opts = {
            'poly color': (color_frozen[0], color_frozen[1], color_frozen[2], 0.20),
            'poly color selected': (color_select[0], color_select[1], color_select[2], 0.20),
            'poly offset': 0.000010,
            'poly dotoffset': 1.0,
            'poly mirror color': (color_frozen[0], color_frozen[1], color_frozen[2], 0.10),
            'poly mirror color selected': (color_select[0], color_select[1], color_select[2], 0.10),
            'poly mirror offset': 0.000010,
            'poly mirror dotoffset': 1.0,

            'line color': (color_frozen[0], color_frozen[1], color_frozen[2], 1.00),
            'line color selected': (color_select[0], color_select[1], color_select[2], 1.00),
            'line width': 2.0,
            'line offset': 0.000012,
            'line dotoffset': 1.0,
            'line mirror stipple': False,
            'line mirror color': (color_frozen[0], color_frozen[1], color_frozen[2], 0.25),
            'line mirror color selected': (color_select[0], color_select[1], color_select[2], 0.25),
            'line mirror width': 1.5,
            'line mirror offset': 0.000012,
            'line mirror dotoffset': 1.0,
            'line mirror stipple': False,

            'point color': (color_frozen[0], color_frozen[1], color_frozen[2], 1.00),
            'point color selected': (color_select[0], color_select[1], color_select[2], 1.00),
            'point size': 5.0,
            'point offset': 0.000015,
            'point dotoffset': 1.0,
            'point mirror color': (color_frozen[0], color_frozen[1], color_frozen[2], 0.25),
            'point mirror color selected': (color_select[0], color_select[1], color_select[2], 0.25),
            'point mirror size': 3.0,
            'point mirror offset': 0.000015,
            'point mirror dotoffset': 1.0,

            'focus mult': 1.0,
            'normal offset': 0.001,
        }
        return opts

    def get_view_version(self):
        m = self.actions.r3d.view_matrix
        return [v for r in m for v in r] + [self.actions.space.lens]

    @profiler.profile
    def draw_postpixel(self):
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
            if options['visualize fps'] and self.actions.region:
                pr = profiler.start('fps postpixel')
                rgn = self.actions.region
                sw,sh = rgn.width,rgn.height
                lw,lh = len(self.fps_list),60
                m = self.drawing.get_dpi_mult()
                def p(x, y): return (sw - 10 + (-lw + x) * m, 10 + y * m)
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
                pr.done()

            pr = profiler.start('tool draw postpixel')
            self.tool.draw_postpixel()
            pr.done()

            pr = profiler.start('widget draw postpixel')
            self.rfwidget.draw_postpixel()
            pr.done()

            pr = profiler.start('window manager draw postpixel')
            self.window_debug_fps.set_label('FPS: %0.2f' % self.fps)
            self.window_debug_save.set_label('Time: %0.0f' % (self.time_to_save or float('inf')))
            if True:
                self.window_manager.draw_postpixel(self.actions.context)
            pr.done()

        except AssertionError as e:
            message,h = debugger.get_exception_info_and_hash()
            print(message)
            message = '\n'.join('- %s'%l for l in message.splitlines())
            self.alert_user(message=message, level='assert', msghash=h)
        except Exception as e:
            message,h = debugger.get_exception_info_and_hash()
            print(message)
            message = '\n'.join('- %s'%l for l in message.splitlines())
            self.alert_user(message=message, level='exception', msghash=h)
            #raise e

    @profiler.profile
    def draw_preview(self):
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

    @profiler.profile
    def draw_postview(self):
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
            pr = profiler.start('render sources')
            for rs,rfs in zip(self.rfsources, self.rfsources_draw):
                rfs.draw(
                    view_forward,
                    buf_matrix_target, buf_matrix_target_inv,
                    buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj,
                    1.00, 0.05, False, 0.5,
                    symmetry=self.rftarget.symmetry, symmetry_view=options['symmetry view'],
                    symmetry_effect=options['symmetry effect'], symmetry_frame=ft
                )
            pr.done()

        pr = profiler.start('render target')
        alpha_above,alpha_below = options['target alpha'],options['target hidden alpha']
        cull_backfaces = options['target cull backfaces']
        alpha_backface = options['target alpha backface']
        self.rftarget_draw.draw(
            view_forward,
            buf_matrix_target, buf_matrix_target_inv,
            buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj,
            alpha_above, alpha_below, cull_backfaces, alpha_backface
        )
        pr.done()

        pr = profiler.start('render other')
        self.tool.draw_postview()
        self.rfwidget.draw_postview()
        pr.done()

        #time.sleep(0.5)
