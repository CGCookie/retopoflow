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
import blf
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
    UI_IntValue, UI_UpdateValue,
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
        }
        return opts

    def get_view_version(self):
        m = self.actions.r3d.view_matrix
        return [v for r in m for v in r] + [self.actions.space.lens]

    def draw_postpixel(self):
        if not self.actions.r3d: return

        wtime,ctime = self.fps_time,time.time()
        self.frames += 1
        if ctime >= wtime + 1:
            self.fps = self.frames / (ctime - wtime)
            self.frames = 0
            self.fps_time = ctime
        
        if self.fps >= options['low fps threshold']: self.fps_low_start = ctime
        if ctime - self.fps_low_start > options['low fps time']:
            # exceeded allowed time for low fps
            if options['low fps warn']: self.show_lowfps_warning()

        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_LINE_SMOOTH)
        bgl.glHint(bgl.GL_LINE_SMOOTH_HINT, bgl.GL_NICEST)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        try:
            self.tool.draw_postpixel()
            self.rfwidget.draw_postpixel()
            self.window_debug_fps.set_label('FPS: %0.2f' % self.fps)
            self.window_debug_save.set_label('Time: %0.0f' % (self.time_to_save or float('inf')))
            self.window_manager.draw_postpixel()
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
                rfs.draw(view_forward, buf_matrix_target, buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj, 1.00, 0.05,
                    symmetry=self.rftarget.symmetry, symmetry_view=options['symmetry view'],
                    symmetry_effect=options['symmetry effect'], symmetry_frame=ft)
            pr.done()

        pr = profiler.start('render target')
        alpha_above,alpha_below = options['target alpha'],options['target hidden alpha']
        self.rftarget_draw.draw(view_forward, buf_matrix_target, buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj, alpha_above, alpha_below)
        pr.done()

        pr = profiler.start('render other')
        self.tool.draw_postview()
        self.rfwidget.draw_postview()
        pr.done()
        
        #time.sleep(0.5)
