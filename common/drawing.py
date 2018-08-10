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
import re
import math
import time
import random
import traceback
import functools
import urllib.request
from itertools import chain
from concurrent.futures import ThreadPoolExecutor

import bpy
import bgl
# import blf
from bpy.types import BoolProperty
from mathutils import Matrix

from .decorators import blender_version_wrapper
from .fontmanager import FontManager as fm
from .maths import Point2D, Vec2D, clamp, mid
from .profiler import profiler
from .debug import dprint


class Drawing:
    _instance = None
    _dpi = 72
    _dpi_mult = 1

    @staticmethod
    @blender_version_wrapper('<','2.79')
    def update_dpi():
        Drawing._dpi = bpy.context.user_preferences.system.dpi
        if bpy.context.user_preferences.system.virtual_pixel_mode == 'DOUBLE':
            Drawing._dpi *= 2
        Drawing._dpi *= bpy.context.user_preferences.system.pixel_size
        Drawing._dpi = int(Drawing._dpi)
        Drawing._dpi_mult = Drawing._dpi / 72

    @staticmethod
    @blender_version_wrapper('>=','2.79')
    def update_dpi():
        Drawing._ui_scale = bpy.context.user_preferences.view.ui_scale
        Drawing._pixel_size = bpy.context.user_preferences.system.pixel_size
        Drawing._sysdpi = bpy.context.user_preferences.system.dpi
        Drawing._dpi = 72 # bpy.context.user_preferences.system.dpi
        Drawing._dpi *= Drawing._ui_scale
        Drawing._dpi *= Drawing._pixel_size
        Drawing._dpi = int(Drawing._dpi)
        Drawing._dpi_mult = Drawing._ui_scale * Drawing._pixel_size * Drawing._sysdpi / 72
        s = 'DPI information: scale:%0.2f, pixel:%0.2f, dpi:%d' % (Drawing._ui_scale, Drawing._pixel_size, Drawing._sysdpi)
        if s != getattr(Drawing, '_last_dpi_info', None):
            Drawing._last_dpi_info = s
            dprint(s)

    @staticmethod
    def get_instance():
        Drawing.update_dpi()
        if not Drawing._instance:
            Drawing._creating = True
            Drawing._instance = Drawing()
            del Drawing._creating
        return Drawing._instance

    def __init__(self):
        assert hasattr(self, '_creating'), "Do not instantiate directly.  Use Drawing.get_instance()"

        self.rgn,self.r3d,self.window = None,None,None
        # self.font_id = 0
        self.fontsize = None
        self.fontsize_scaled = None
        self.line_cache = {}
        self.size_cache = {}
        self.set_font_size(12)

    def set_region(self, rgn, r3d, window):
        self.rgn = rgn
        self.r3d = r3d
        self.window = window

    @staticmethod
    def set_cursor(cursor):
        # DEFAULT, NONE, WAIT, CROSSHAIR, MOVE_X, MOVE_Y, KNIFE, TEXT,
        # PAINT_BRUSH, HAND, SCROLL_X, SCROLL_Y, SCROLL_XY, EYEDROPPER
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                win.cursor_modal_set(cursor)

    def scale(self, s): return s * self._dpi_mult if s is not None else None
    def unscale(self, s): return s / self._dpi_mult if s is not None else None
    def get_dpi_mult(self): return self._dpi_mult
    def get_pixel_size(self): return self._pixel_size
    def line_width(self, width): bgl.glLineWidth(max(1, self.scale(width)))
    def point_size(self, size): bgl.glPointSize(max(1, self.scale(size)))

    def set_font_size(self, fontsize, fontid=None, force=False):
        fontsize, fontsize_scaled = int(fontsize), int(int(fontsize) * self._dpi_mult)
        if not force and fontsize_scaled == self.fontsize_scaled:
            return self.fontsize
        fontsize_prev = self.fontsize
        fontsize_scaled_prev = self.fontsize_scaled
        self.fontsize = fontsize
        self.fontsize_scaled = fontsize_scaled

        fm.size(fontsize_scaled, 72, fontid=fontid)
        # blf.size(self.font_id, fontsize_scaled, 72) #self._sysdpi)

        # cache away useful details about font (line height, line base)
        key = (self.fontsize_scaled)
        if key not in self.line_cache:
            dprint('Caching new scaled font size:', key)
            all_chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()`~[}{]/?=+\\|-_\'",<.>'
            all_caps = all_chars.upper()
            self.line_cache[key] = {
                'line height': round(fm.dimensions(all_chars, fontid=fontid)[1] + self.scale(4)),
                'line base': round(fm.dimensions(all_caps, fontid=fontid)[1]),
                # 'line height': round(blf.dimensions(self.font_id, all_chars)[1] + self.scale(4)),
                # 'line base': round(blf.dimensions(self.font_id, all_caps)[1]),
            }
        info = self.line_cache[key]
        self.line_height = info['line height']
        self.line_base = info['line base']

        return fontsize_prev

    def get_text_size_info(self, text, item, fontsize=None, fontid=None):
        if fontsize: size_prev = self.set_font_size(fontsize, fontid=fontid)

        if text is None: text, lines = '', []
        elif type(text) is list: text, lines = '\n'.join(text), text
        else: text, lines = text, text.splitlines()

        fontid = fm.load(fontid)
        key = (text, self.fontsize_scaled, fontid)
        # key = (text, self.fontsize_scaled, self.font_id)
        if key not in self.size_cache:
            d = {}
            if not text:
                d['width'] = 0
                d['height'] = 0
                d['line height'] = self.line_height
            else:
                get_width = lambda t: math.ceil(fm.dimensions(t, fontid=fontid)[0])
                get_height = lambda t: math.ceil(fm.dimensions(t, fontid=fontid)[1])
                # get_width = lambda t: math.ceil(blf.dimensions(self.font_id, t)[0])
                # get_height = lambda t: math.ceil(blf.dimensions(self.font_id, t)[1])
                d['width'] = max(get_width(l) for l in lines)
                d['height'] = get_height(text)
                d['line height'] = self.line_height * len(lines)
            self.size_cache[key] = d
        if fontsize: self.set_font_size(size_prev, fontid=fontid)
        return self.size_cache[key][item]

    def get_text_width(self, text, fontsize=None):
        return self.get_text_size_info(text, 'width', fontsize=fontsize)
    def get_text_height(self, text, fontsize=None):
        return self.get_text_size_info(text, 'height', fontsize=fontsize)
    def get_line_height(self, text=None, fontsize=None):
        return self.get_text_size_info(text, 'line height', fontsize=fontsize)

    def set_clipping(self, xmin, ymin, xmax, ymax, fontid=None):
        fm.clipping((xmin, ymin), (xmax, ymax), fontid=fontid)
        # blf.clipping(self.font_id, xmin, ymin, xmax, ymax)
        self.enable_clipping()
    def enable_clipping(self, fontid=None):
        fm.enable_clipping(fontid=fontid)
        # blf.enable(self.font_id, blf.CLIPPING)
    def disable_clipping(self, fontid=None):
        fm.disable_clipping(fontid=fontid)
        # blf.disable(self.font_id, blf.CLIPPING)

    def enable_stipple(self):
        bgl.glLineStipple(4, 0x5555)
        bgl.glEnable(bgl.GL_LINE_STIPPLE)
    def disable_stipple(self):
        bgl.glDisable(bgl.GL_LINE_STIPPLE)
    def set_stipple(self, enable):
        if enable: self.enable_stipple()
        else: self.disable_stipple()

    def text_draw2D(self, text, pos:Point2D, color, dropshadow=None, fontsize=None, fontid=None):
        if fontsize: size_prev = self.set_font_size(fontsize, fontid=fontid)

        lines = str(text).splitlines()
        l,t = round(pos[0]),round(pos[1])
        lh = self.line_height
        lb = self.line_base

        if dropshadow: self.text_draw2D(text, (l+1,t-1), dropshadow, fontsize=fontsize)

        bgl.glEnable(bgl.GL_BLEND)
        bgl.glColor4f(*color)
        for line in lines:
            th = self.get_text_height(line)
            fm.draw(line, xyz=(l, t-lb, 0), fontid=fontid)
            # blf.position(self.font_id, l, t - lb, 0)
            # blf.draw(self.font_id, line)
            t -= lh

        if fontsize: self.set_font_size(size_prev, fontid=fontid)

    def get_mvp_matrix(self, view3D=True):
        '''
        if view3D == True: returns MVP for 3D view
        else: returns MVP for pixel view
        TODO: compute separate M,V,P matrices
        '''
        if not self.r3d: return None
        if view3D:
            # 3D view
            return self.r3d.perspective_matrix
        else:
            # pixel view
            return self.get_pixel_matrix()

        mat_model = Matrix()
        mat_view = Matrix()
        mat_proj = Matrix()

        view_loc = self.r3d.view_location # vec
        view_rot = self.r3d.view_rotation # quat
        view_per = self.r3d.view_perspective # 'PERSP' or 'ORTHO'

        return mat_model,mat_view,mat_proj

    def get_pixel_matrix_list(self):
        if not self.r3d: return None
        x,y = self.rgn.x,self.rgn.y
        w,h = self.rgn.width,self.rgn.height
        ww,wh = self.window.width,self.window.height
        return [[2/w,0,0,-1],  [0,2/h,0,-1],  [0,0,1,0],  [0,0,0,1]]

    def get_pixel_matrix(self):
        '''
        returns MVP for pixel view
        TODO: compute separate M,V,P matrices
        '''
        return Matrix(self.get_pixel_matrix_list()) if self.r3d else None

    def get_pixel_matrix_buffer(self):
        if not self.r3d: return None
        return bgl.Buffer(bgl.GL_FLOAT, [4,4], self.get_pixel_matrix_list())

    def get_view_matrix_list(self):
        return list(self.get_view_matrix()) if self.r3d else None

    def get_view_matrix(self):
        return self.r3d.perspective_matrix if self.r3d else None

    def get_view_matrix_buffer(self):
        if not self.r3d: return None
        return bgl.Buffer(bgl.GL_FLOAT, [4,4], self.get_view_matrix_list())

    def textbox_draw2D(self, text, pos:Point2D, padding=5, textbox_position=7, fontid=None):
        '''
        textbox_position specifies where the textbox is drawn in relation to pos.
        ex: if textbox_position==7, then the textbox is drawn where pos is the upper-left corner
        tip: textbox_position is arranged same as numpad
                    +-----+
                    |7 8 9|
                    |4 5 6|
                    |1 2 3|
                    +-----+
        '''
        lh = self.line_height

        # TODO: wrap text!
        lines = text.splitlines()
        w = max(self.get_text_width(line) for line in lines)
        h = len(lines) * lh

        # find top-left corner (adjusting for textbox_position)
        l,t = round(pos[0]),round(pos[1])
        textbox_position -= 1
        lcr = textbox_position % 3
        tmb = int(textbox_position / 3)
        l += [w+padding,round(w/2),-padding][lcr]
        t += [h+padding,round(h/2),-padding][tmb]

        bgl.glEnable(bgl.GL_BLEND)

        bgl.glColor4f(0.0, 0.0, 0.0, 0.25)
        bgl.glBegin(bgl.GL_QUADS)
        bgl.glVertex2f(l+w+padding,t+padding)
        bgl.glVertex2f(l-padding,t+padding)
        bgl.glVertex2f(l-padding,t-h-padding)
        bgl.glVertex2f(l+w+padding,t-h-padding)
        bgl.glEnd()

        bgl.glColor4f(0.0, 0.0, 0.0, 0.75)
        self.drawing.line_width(1.0)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        bgl.glVertex2f(l+w+padding,t+padding)
        bgl.glVertex2f(l-padding,t+padding)
        bgl.glVertex2f(l-padding,t-h-padding)
        bgl.glVertex2f(l+w+padding,t-h-padding)
        bgl.glVertex2f(l+w+padding,t+padding)
        bgl.glEnd()

        bgl.glColor4f(1,1,1,0.5)
        for i,line in enumerate(lines):
            th = self.get_text_height(line)
            y = t - (i+1)*lh + int((lh-th) / 2)
            fm.draw(line, xyz=(l, y, 0), fontid=fontid)
            # blf.position(self.font_id, l, y, 0)
            # blf.draw(self.font_id, line)

    def glCheckError(self, title):
        err = bgl.glGetError()
        if err == bgl.GL_NO_ERROR: return

        derrs = {
            bgl.GL_INVALID_ENUM: 'invalid enum',
            bgl.GL_INVALID_VALUE: 'invalid value',
            bgl.GL_INVALID_OPERATION: 'invalid operation',
            bgl.GL_STACK_OVERFLOW: 'stack overflow',
            bgl.GL_STACK_UNDERFLOW: 'stack underflow',
            bgl.GL_OUT_OF_MEMORY: 'out of memory',
            bgl.GL_INVALID_FRAMEBUFFER_OPERATION: 'invalid framebuffer operation',
        }
        if err in derrs:
            print('ERROR (%s): %s' % (title, derrs[err]))
        else:
            print('ERROR (%s): code %d' % (title, err))
        traceback.print_stack()


class ScissorStack:
    context = None
    buf = bgl.Buffer(bgl.GL_INT, 4)
    box = None
    started = False
    scissor_enabled = False
    stack = None

    @staticmethod
    def start(context):
        assert not ScissorStack.started

        rgn = context.region
        ScissorStack.context = context
        ScissorStack.box = (rgn.x, rgn.y, rgn.width, rgn.height)

        bgl.glGetIntegerv(bgl.GL_SCISSOR_BOX, ScissorStack.buf)
        ScissorStack.scissor_enabled = (bgl.glIsEnabled(bgl.GL_SCISSOR_TEST) == bgl.GL_TRUE)
        ScissorStack.stack = [tuple(ScissorStack.buf)]

        ScissorStack.started = True

        if not ScissorStack.scissor_enabled:
            bgl.glEnable(bgl.GL_SCISSOR_TEST)

    @staticmethod
    def end():
        assert ScissorStack.started
        assert len(ScissorStack.stack) == 1, 'stack size = %d (not 1)' % len(ScissorStack.started)
        if not ScissorStack.scissor_enabled:
            bgl.glDisable(bgl.GL_SCISSOR_TEST)
        ScissorStack.started = False

    @staticmethod
    def _set_scissor():
        assert ScissorStack.started and ScissorStack.stack
        bgl.glScissor(*ScissorStack.stack[-1])

    @staticmethod
    def push(pos, size):
        assert ScissorStack.started, 'Attempting to push a new scissor onto stack before starting!'
        assert ScissorStack.stack

        rl,rt,rw,rh = ScissorStack.box

        nl,nt = pos
        nw,nh = size
        nl,nt,nw,nh = int(rl+nl),int(rt+nt-nh),int(nw+1),int(nh+1)
        nr,nb = nl+nw,nt+nh

        pl,pt,pw,ph = ScissorStack.stack[-1]
        pr,pb = pl+pw,pt+ph

        nl,nr,nt,nb = clamp(nl,pl,pr),clamp(nr,pl,pr),clamp(nt,pt,pb),clamp(nb,pt,pb)
        nw,nh = max(0, nr-nl),max(0, nb-nt)

        ScissorStack.stack.append((nl, nt, nw, nh))
        ScissorStack._set_scissor()

    @staticmethod
    def get_current_view():
        assert ScissorStack.started
        assert ScissorStack.stack
        rl,rt,rw,rh = ScissorStack.box
        l,t,w,h = ScissorStack.stack[-1]
        return (l-rl,t+h-rt,w,h)

    @staticmethod
    def is_visible():
        assert ScissorStack.started
        assert ScissorStack.stack
        sl,st,sw,sh = ScissorStack.stack[-1]
        return sw > 0 and sh > 0

    @staticmethod
    def is_box_visible(l,t,w,h):
        assert ScissorStack.started
        assert ScissorStack.stack
        vl, vt, vw, vh = ScissorStack.get_current_view()
        vr, vb = vl + vw, vt - vh
        r, b = l + w, t - h
        return not (l > vr or r < vl or t < vb or b > vt)
        # rl,rt,rw,rh = ScissorStack.box
        # l += rl
        # t += rt
        # r = l + w
        # b = t - h
        # sl,st,sw,sh = ScissorStack.stack[-1]
        # sr = sl + sw
        # sb = st - sh
        # if l > sr: return False
        # if r < sl: return False
        # if t < sb: return False
        # if b > st: return False
        # return True

    @staticmethod
    def pop():
        assert ScissorStack.stack, 'Attempting to pop a scissor from empty stack!'
        ScissorStack.stack.pop()
        ScissorStack._set_scissor()
