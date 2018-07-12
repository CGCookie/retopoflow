'''
Copyright (C) 2017 CG Cookie
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
import blf
from bpy.types import BoolProperty
from mathutils import Matrix

from .decorators import blender_version_wrapper
from .maths import Point2D, Vec2D, clamp, mid
from .profiler import profiler

from ..ext import png


def set_cursor(cursor):
    # DEFAULT, NONE, WAIT, CROSSHAIR, MOVE_X, MOVE_Y, KNIFE, TEXT,
    # PAINT_BRUSH, HAND, SCROLL_X, SCROLL_Y, SCROLL_XY, EYEDROPPER
    for wm in bpy.data.window_managers:
        for win in wm.windows:
            win.cursor_modal_set(cursor)


path_images = os.path.join(os.path.dirname(__file__), '..', 'icons')

def get_image_path(fn, ext=''):
    if ext: fn = '%s.%s' % (fn,ext)
    return os.path.join(path_images, fn)

def load_image_png(fn):
    if not hasattr(load_image_png, 'cache'):
        load_image_png.cache = {}
    if not fn in load_image_png.cache: 
        # assuming 4 channels per pixel!
        w,h,d,m = png.Reader(get_image_path(fn)).read()
        load_image_png.cache[fn] = [[r[i:i+4] for i in range(0,w*4,4)] for r in d]
    return load_image_png.cache[fn]


class GetSet:
    def __init__(self, fn_get, fn_set):
        self.fn_get = fn_get
        self.fn_set = fn_set
    def get(self): return self.fn_get()
    def set(self, v): return self.fn_set(v)



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
        Drawing._dpi = 72 # bpy.context.user_preferences.system.dpi
        Drawing._dpi *= bpy.context.user_preferences.view.ui_scale
        Drawing._dpi *= bpy.context.user_preferences.system.pixel_size
        Drawing._dpi = int(Drawing._dpi)
        Drawing._dpi_mult = bpy.context.user_preferences.view.ui_scale * bpy.context.user_preferences.system.pixel_size
    
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
        self.font_id = 0
        self.text_size(12)
    
    def set_region(self, rgn, r3d, window):
        self.rgn = rgn
        self.r3d = r3d
        self.window = window
    
    def scale(self, s): return s * self._dpi_mult if s is not None else None
    def unscale(self, s): return s / self._dpi_mult if s is not None else None
    def get_dpi_mult(self): return self._dpi_mult
    def line_width(self, width): bgl.glLineWidth(max(1, self.scale(width)))
    def point_size(self, size): bgl.glPointSize(max(1, self.scale(size)))
    
    def text_size(self, size):
        blf.size(self.font_id, size, self._dpi)
        self.line_height = round(blf.dimensions(self.font_id, "XMPQpqjI")[1] + 3*self._dpi_mult)
        self.line_base = round(blf.dimensions(self.font_id, "XMPQI")[1])
    
    def get_text_size(self, text):
        size = blf.dimensions(self.font_id, text)
        return (round(size[0]), round(size[1]))
    def get_text_width(self, text):
        size = blf.dimensions(self.font_id, text)
        return round(size[0])
    def get_text_height(self, text):
        size = blf.dimensions(self.font_id, text)
        return round(size[1])
    def get_line_height(self, text=None):
        if not text: return self.line_height
        return self.line_height * (1 + text.count('\n'))
    
    def set_clipping(self, xmin, ymin, xmax, ymax):
        blf.clipping(self.font_id, xmin, ymin, xmax, ymax)
        self.enable_clipping()
    def enable_clipping(self):
        blf.enable(self.font_id, blf.CLIPPING)
    def disable_clipping(self):
        blf.disable(self.font_id, blf.CLIPPING)
    
    def enable_stipple(self):
        bgl.glLineStipple(4, 0x5555)
        bgl.glEnable(bgl.GL_LINE_STIPPLE)
    def disable_stipple(self):
        bgl.glDisable(bgl.GL_LINE_STIPPLE)
    def set_stipple(self, enable):
        if enable: self.enable_stipple()
        else: self.disable_stipple()
    
    def text_draw2D(self, text, pos:Point2D, color, dropshadow=None):
        lines = str(text).split('\n')
        l,t = round(pos[0]),round(pos[1])
        lh = self.line_height
        lb = self.line_base
        
        if dropshadow: self.text_draw2D(text, (l+1,t-1), dropshadow)
        
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glColor4f(*color)
        for i,line in enumerate(lines):
            th = self.get_text_height(line)
            # x,y = l,t - (i+1)*lh + int((lh-th)/2)
            x,y = l,t - (i+1)*lh + int((lh-lb)/2+2*self._dpi_mult)
            blf.position(self.font_id, x, y, 0)
            blf.draw(self.font_id, line)
            y -= self.line_height
    
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
    
    def textbox_draw2D(self, text, pos:Point2D, padding=5, textbox_position=7):
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
        lines = text.split('\n')
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
            blf.position(self.font_id, l, y, 0)
            blf.draw(self.font_id, line)
    
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


class UI_Element:
    def __init__(self):
        self.drawing = Drawing.get_instance()
        self.context = bpy.context
        self.pos = None
        self.size = None
        self.margin = 4
        self.visible = True
        self.scissor_buffer = bgl.Buffer(bgl.GL_INT, 4)
        self.scissor_enabled = None
        self.deleted = False
    
    def delete(self):
        self.deleted = True
        self._delete()
    
    def set_scissor(self, allow_expand=False):
        l,t = self.pos
        w,h = self.size
        rgn = self.context.region
        rl,rt,rw,rh = rgn.x,rgn.y,rgn.width,rgn.height
        
        bgl.glGetIntegerv(bgl.GL_SCISSOR_BOX, self.scissor_buffer)
        self.scissor_enabled = bgl.glIsEnabled(bgl.GL_SCISSOR_TEST) == bgl.GL_TRUE
        sl,st,sw,sh = int(rl+l),int(rt+t-h),int(w+1),int(h+1)
        if self.scissor_enabled:
            if not allow_expand:
                # clamp l,t,w,h to current scissor
                cl,ct,cw,ch = self.scissor_buffer
                cr,cb = cl+cw,ct+ch
                sr,sb = sl+sw,st+sh
                sl,sr,st,sb = clamp(sl,cl,cr),clamp(sr,cl,cr),clamp(st,ct,cb),clamp(sb,ct,cb)
                sw,sh = max(0, sr - sl),max(0, sb - st)
        else:
            bgl.glEnable(bgl.GL_SCISSOR_TEST)
        bgl.glScissor(sl, st, sw, sh)
        
    def reset_scissor(self):
        if not self.scissor_enabled:
            bgl.glDisable(bgl.GL_SCISSOR_TEST)
        bgl.glScissor(*self.scissor_buffer)
    
    def hover_ui(self, mouse): return self._hover_ui(mouse)
    def _hover_ui(self, mouse): return self.__hover_ui(mouse)
    def __hover_ui(self, mouse):
        if not self.visible: return None
        if not self.pos or not self.size: return None
        x,y = mouse
        l,t = self.pos
        w,h = self.size
        if x < l or x >= l + w: return None
        if y > t or y <= t - h: return None
        return self
    
    @profiler.profile
    def draw(self, left, top, width, height):
        if not self.visible: return
        m = self.drawing.scale(self.margin)
        self.pos = Point2D((left+m, top-m))
        self.size = Vec2D((width-m*2, height-m*2))
        self.predraw()
        self.set_scissor()
        self._draw()
        self.reset_scissor()
    
    def get_width(self): return (self._get_width() + self.drawing.scale(self.margin*2)) if self.visible else 0
    def get_height(self): return (self._get_height() + self.drawing.scale(self.margin*2)) if self.visible else 0
    
    def _delete(self): return
    def _get_width(self): return 0
    def _get_height(self): return 0
    def _draw(self): pass
    def predraw(self): pass
    def mouse_enter(self): pass
    def mouse_leave(self): pass
    def mouse_down(self, mouse): pass
    def mouse_move(self, mouse): pass
    def mouse_up(self, mouse): pass
    def capture_start(self): pass
    def capture_event(self, event): pass
    
    def _get_tooltip(self, mouse): pass
    
    def mouse_cursor(self): return 'DEFAULT'


class UI_Spacer(UI_Element):
    def __init__(self, width=0, height=0):
        super().__init__()
        self.width = width
        self.height = height
        self.margin = 0
    def _get_width(self): return self.drawing.scale(self.width)
    def _get_height(self): return self.drawing.scale(self.height)


class UI_Label(UI_Element):
    def __init__(self, label, icon=None, tooltip=None, color=(1,1,1,1), bgcolor=None, align=-1, textsize=12, shadowcolor=None, margin=4):
        super().__init__()
        self.icon = icon
        self.tooltip = tooltip
        self.color = color
        self.shadowcolor = shadowcolor
        self.align = align
        self.textsize = textsize
        self.margin = margin
        self.set_label(label)
        self.set_bgcolor(bgcolor)
        self.cursor_pos = None
        self.cursor_symbol = None
        self.cursor_color = (0.1,0.7,1,1)
    
    def set_bgcolor(self, bgcolor): self.bgcolor = bgcolor
    
    def get_label(self): return self.text
    def set_label(self, label):
        self.text = str(label)
        self.drawing.text_size(self.textsize)
        self.text_width = self.drawing.get_text_width(self.text)
        self.text_height = self.drawing.get_line_height(self.text)
    
    def _get_width(self): return self.text_width
    def _get_height(self): return self.text_height
    def _get_tooltip(self, mouse): return self.tooltip
    
    @profiler.profile
    def _draw(self):
        self.drawing.text_size(self.textsize)
        l,t = self.pos
        w,h = self.size
        
        if self.bgcolor:
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glColor4f(*self.bgcolor)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glEnd()
        
        if self.shadowcolor:
            if self.align < 0:    loc = Point2D((l+2, t-2))
            elif self.align == 0: loc = Point2D((l+(w-self.text_width)/2+2, t-2))
            else:                 loc = Point2D((l+w-self.width+2, t-2))
            self.drawing.text_draw2D(self.text, loc, self.shadowcolor)
        
        if self.align < 0:    loc = Point2D((l, t))
        elif self.align == 0: loc = Point2D((l+(w-self.text_width)/2, t))
        else:                 loc = Point2D((l+w-self.width, t))
        self.drawing.text_draw2D(self.text, loc, self.color)
        if self.cursor_pos is not None and self.cursor_symbol:
            pre = self.drawing.get_text_width(self.text[:self.cursor_pos])
            cwid = self.drawing.get_text_width(self.cursor_symbol)
            cloc = Point2D((loc.x+pre-cwid/2, loc.y))
            self.drawing.text_draw2D(self.cursor_symbol, cloc, self.cursor_color)



class UI_WrappedLabel(UI_Element):
    def __init__(self, label, color=(1,1,1,1), min_size=Vec2D((600, 36)), textsize=12, bgcolor=None, margin=4, shadowcolor=None):
        super().__init__()
        self.margin = margin
        self.textsize = textsize
        self.set_label(label)
        self.set_bgcolor(bgcolor)
        self.color = color
        self.shadowcolor = shadowcolor
        self.min_size = min_size
        self.wrapped_size = min_size
        self.drawing.text_size(self.textsize)
        self.line_height = self.drawing.get_line_height()
    
    def set_bgcolor(self, bgcolor): self.bgcolor = bgcolor
    
    def set_label(self, label):
        # process message similarly to Markdown
        label = re.sub(r'^\n*', r'', label)                 # remove leading \n
        label = re.sub(r'\n*$', r'', label)                 # remove trailing \n
        label = re.sub(r'\n\n\n*', r'\n\n', label)          # 2+ \n => \n\n
        paras = label.split('\n\n')                         # split into paragraphs
        paras = [re.sub(r'\n', '  ', p) for p in paras]     # join sentences of paragraphs
        label = '\n\n'.join(paras)                          # join paragraphs
        
        self.text = str(label)
        self.last_size = None
    
    def predraw(self):
        if self.last_size == self.size: return
        self.drawing.text_size(self.textsize)
        mwidth = self.size.x
        twidth = self.drawing.get_text_width
        swidth = twidth(' ')
        wrapped = []
        def wrap(t):
            words = t.split(' ')
            words.reverse()
            lines = []
            line = []
            while words:
                word = words.pop()
                nline = line + [word]
                if line and twidth(' '.join(nline)) >= mwidth:
                    lines.append(' '.join(line))
                    line = [word]
                else:
                    line = nline
            lines.append(' '.join(line))
            return lines
        lines = self.text.split('\n')
        self.wrapped_lines = [wrapped_line for line in lines for wrapped_line in wrap(line)]
        self.last_size = self.size
        w = max(twidth(l) for l in self.wrapped_lines)
        h = self.line_height * len(self.wrapped_lines)
        self.wrapped_size = Vec2D((w, h))
        
    def _get_width(self): return max(self.wrapped_size.x, self.drawing.scale(self.min_size.x))
    def _get_height(self): return self.wrapped_size.y
    
    @profiler.profile
    def _draw(self):
        l,t = self.pos
        w,h = self.size
        twidth = self.drawing.get_text_width
        theight = self.drawing.get_text_height
        self.drawing.text_size(self.textsize)
        
        if self.bgcolor:
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glColor4f(*self.bgcolor)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glEnd()
        
        y = t
        for line in self.wrapped_lines:
            lheight = theight(line)
            if self.shadowcolor:
                self.drawing.text_draw2D(line, Point2D((l+2, y-2)), self.shadowcolor)
            self.drawing.text_draw2D(line, Point2D((l, y)), self.color)
            y -= self.line_height #lheight


class UI_Rule(UI_Element):
    def __init__(self, thickness=2, padding=0, color=(1.0,1.0,1.0,0.25)):
        super().__init__()
        self.margin = 0
        self.thickness = thickness
        self.color = color
        self.padding = padding
    def _get_width(self): return self.drawing.scale(self.padding*2 + 1)
    def _get_height(self): return self.drawing.scale(self.padding*2 + self.thickness)

    @profiler.profile
    def _draw(self):
        left,top = self.pos
        width,height = self.size
        t2 = round(self.thickness/2)
        padding = self.padding
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glColor4f(*self.color)
        self.drawing.line_width(self.thickness)
        bgl.glBegin(bgl.GL_LINES)
        bgl.glVertex2f(left+padding, top-padding-t2)
        bgl.glVertex2f(left+width-padding, top-padding-t2)
        bgl.glEnd()


class UI_Container(UI_Element):
    def __init__(self, vertical=True, background=None, margin=4):
        super().__init__()
        self.vertical = vertical
        self.ui_items = []
        self.background = background
        self.margin = margin
        self.offset = 0
    
    def _delete(self):
        for ui_item in self.ui_items:
            ui_item.delete()
    
    def _hover_ui(self, mouse):
        if not super()._hover_ui(mouse): return None
        for ui in self.ui_items:
            hover = ui.hover_ui(mouse)
            if hover: return hover
        return self
    
    def _get_width(self):
        if not self.ui_items: return 0
        fn = max if self.vertical else sum
        return fn(ui.get_width() for ui in self.ui_items)
    def _get_height(self):
        if not self.ui_items: return 0
        fn = sum if self.vertical else max
        return fn(ui.get_height() for ui in self.ui_items)
    
    @profiler.profile
    def _draw(self):
        l,t_ = self.pos
        w,h = self.size
        t = t_ + self.offset
        
        if self.background:
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glColor4f(*self.background)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l, t)
            bgl.glVertex2f(l+w, t)
            bgl.glVertex2f(l+w, t-h)
            bgl.glVertex2f(l, t-h)
            bgl.glEnd()
        
        if self.vertical:
            y = t
            for ui in self.ui_items:
                eh = ui.get_height()
                ui.draw(l,y,w,eh)
                y -= eh
        else:
            x = l
            l = len(self.ui_items)
            for i,ui in enumerate(self.ui_items):
                ew = ui.get_width() if i < l-1 else w
                ui.draw(x,t,ew,h)
                x += ew
                w -= ew
        
        if self.offset > 0:
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glColor4f(0.25, 0.25, 0.25, 1.00)
            bgl.glVertex2f(l, t_+1)
            bgl.glVertex2f(l+w, t_+1)
            bgl.glColor4f(0.25, 0.25, 0.25, 0.00)
            bgl.glVertex2f(l+w, t_-30)
            bgl.glVertex2f(l, t_-30)
            bgl.glEnd()
        if h+self.offset+self.drawing.scale(2) < self._get_height():
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glColor4f(0.25, 0.25, 0.25, 1.00)
            bgl.glVertex2f(l, t_-h)
            bgl.glVertex2f(l+w, t_-h)
            bgl.glColor4f(0.25, 0.25, 0.25, 0.00)
            bgl.glVertex2f(l+w, t_-h+30)
            bgl.glVertex2f(l, t_-h+30)
            bgl.glEnd()
        
    
    def add(self, ui_item, only=False):
        if only: self.ui_items.clear()
        self.ui_items.append(ui_item)
        return ui_item

class UI_EqualContainer(UI_Container):
    def __init__(self, vertical=True, margin=4):
        super().__init__(vertical=vertical, margin=margin)
    
    @profiler.profile
    def _draw(self):
        if len(self.ui_items) == 0: return
        l,t = self.pos
        w,h = self.size
        if self.vertical:
            y = t
            eh = math.floor(h / len(self.ui_items))
            for ui in self.ui_items:
                ui.draw(l,y,w,eh)
                y -= eh
        else:
            x = l
            l = len(self.ui_items)
            ew = math.floor(w / len(self.ui_items))
            for i,ui in enumerate(self.ui_items):
                ui.draw(x,t,ew,h)
                x += ew
                w -= ew

class UI_TableContainer(UI_Element):
    def __init__(self, nrows, ncols, background=None, margin=4):
        super().__init__()
        self.nrows = nrows
        self.ncols = ncols
        self.rows = [[UI_Element() for i in range(ncols)] for j in range(nrows)]
        self.background = background
        self.margin = margin
        self.offset = 0
    
    def _delete(self):
        for row in self.rows:
            for cell in row:
                cell.delete()
    
    def _hover_ui(self, mouse):
        if not super()._hover_ui(mouse): return None
        for row in self.rows:
            for cell in row:
                hover = cell.hover_ui(mouse)
                if hover: return hover
        return self
    
    def get_col_width(self, c):
        return max(row[c].get_width() for row in self.rows)
    def get_row_height(self, r):
        return max(cell.get_height() for cell in self.rows[r])
    
    def _get_width(self):
        return sum(self.get_col_width(c) for c in range(self.ncols))
    def _get_height(self):
        return sum(self.get_row_height(r) for r in range(self.nrows))
    
    @profiler.profile
    def _draw(self):
        l,t_ = self.pos
        w,h = self.size
        t = t_ + self.offset
        
        if self.background:
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glColor4f(*self.background)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l, t)
            bgl.glVertex2f(l+w, t)
            bgl.glVertex2f(l+w, t-h)
            bgl.glVertex2f(l, t-h)
            bgl.glEnd()
        
        widths = [self.get_col_width(c) for c in range(self.ncols)]
        heights = [self.get_row_height(r) for r in range(self.nrows)]
        y = t
        for r in range(self.nrows):
            x = l
            h = heights[r]
            for c in range(self.ncols):
                w = widths[c]
                ui = self.rows[r][c]
                ui.draw(x,y,w,h)
                x += w
            y -= h
        
        # if self.offset > 0:
        #     bgl.glEnable(bgl.GL_BLEND)
        #     bgl.glBegin(bgl.GL_QUADS)
        #     bgl.glColor4f(0.25, 0.25, 0.25, 1.00)
        #     bgl.glVertex2f(l, t_+1)
        #     bgl.glVertex2f(l+w, t_+1)
        #     bgl.glColor4f(0.25, 0.25, 0.25, 0.00)
        #     bgl.glVertex2f(l+w, t_-30)
        #     bgl.glVertex2f(l, t_-30)
        #     bgl.glEnd()
        # if h+self.offset+2 < self._get_height():
        #     bgl.glEnable(bgl.GL_BLEND)
        #     bgl.glBegin(bgl.GL_QUADS)
        #     bgl.glColor4f(0.25, 0.25, 0.25, 1.00)
        #     bgl.glVertex2f(l, t_-h)
        #     bgl.glVertex2f(l+w, t_-h)
        #     bgl.glColor4f(0.25, 0.25, 0.25, 0.00)
        #     bgl.glVertex2f(l+w, t_-h+30)
        #     bgl.glVertex2f(l, t_-h+30)
        #     bgl.glEnd()
        
    
    def set(self, row, col, ui_item):
        self.rows[row][col] = ui_item
        return ui_item


class UI_Markdown(UI_Container):
    def __init__(self, markdown, min_size=Vec2D((600, 36)), margin=0):
        super().__init__(margin=margin)
        self.min_size = self.drawing.scale(min_size)
        self.set_markdown(markdown)
    
    def set_markdown(self, mdown):
        # process message similarly to Markdown
        mdown = re.sub(r'^\n*', r'', mdown)                 # remove leading \n
        mdown = re.sub(r'\n*$', r'', mdown)                 # remove trailing \n
        mdown = re.sub(r'\n\n\n*', r'\n\n', mdown)          # 2+ \n => \n\n
        paras = mdown.split('\n\n')                         # split into paragraphs
        
        container = UI_Container()
        for p in paras:
            if p.startswith('# '):
                # h1 heading!
                h1text = re.sub(r'# +', r'', p)
                container.add(UI_Spacer(height=4))
                h1 = container.add(UI_WrappedLabel(h1text, textsize=20, shadowcolor=(0,0,0,0.5)))
                container.add(UI_Spacer(height=14))
            elif p.startswith('## '):
                # h2 heading!
                h2text = re.sub(r'## +', r'', p)
                container.add(UI_Spacer(height=8))
                h2 = container.add(UI_WrappedLabel(h2text, textsize=16, shadowcolor=(0,0,0,0.5)))
                container.add(UI_Spacer(height=4))
            elif p.startswith('- '):
                # unordered list!
                ul = container.add(UI_Container())
                for litext in p.split('\n'):
                    litext = re.sub(r'- ', r'', litext)
                    li = ul.add(UI_Container(margin=0, vertical=False))
                    li.add(UI_Label('-')).margin=0
                    li.add(UI_Spacer(width=8))
                    li.add(UI_WrappedLabel(litext, min_size=self.min_size)).margin=0
            elif p.startswith('!['):
                # image!
                m = re.match(r'^!\[(?P<caption>.*)\]\((?P<filename>.*)\)$', p)
                fn = m.group('filename')
                img = container.add(UI_Image(fn))
            elif p.startswith('| '):
                # table
                data = [l for l in p.split('\n')]
                data = [re.sub(r'^\| ', r'', l) for l in data]
                data = [re.sub(r' \|$', r'', l) for l in data]
                data = [l.split(' | ') for l in data]
                rows,cols = len(data),len(data[0])
                t = container.add(UI_TableContainer(rows, cols))
                for r in range(rows):
                    for c in range(cols):
                        if c == 0:
                            t.set(r, c, UI_Label(data[r][c]))
                        else:
                            t.set(r, c, UI_WrappedLabel(data[r][c], min_size=Vec2D((400, 12))))
            else:
                p = re.sub(r'\n', '  ', p)      # join sentences of paragraph
                container.add(UI_WrappedLabel(p, min_size=self.min_size))
        self.add(container, only=True)

class UI_OnlineMarkdown(UI_Markdown):
    def __init__(self, url, min_size=Vec2D((600,36))):
        super().__init__(margin=0)
        self.min_size = min_size
        
        response = urllib.request.urlopen(url)
        data = response.read()
        text = data.decode('utf-8')
        
        markdown = text
        
        self.set_markdown(markdown)

class UI_Button(UI_Container):
    def __init__(self, label, fn_callback, icon=None, tooltip=None, color=(1,1,1,1), align=0, bgcolor=None, bordercolor=(0,0,0,0.4), hovercolor=(1,1,1,0.1), presscolor=(0,0,0,0.2), margin=None):
        super().__init__(vertical=False)
        if icon:
            self.add(icon)
            self.add(UI_Spacer(width=4))
        self.tooltip = tooltip
        self.label = self.add(UI_Label(label, color=color, align=align))
        self.fn_callback = fn_callback
        self.pressed = False
        self.bgcolor = bgcolor
        self.bordercolor = bordercolor
        self.presscolor = presscolor
        self.hovercolor = hovercolor
        self.mouse = None
        self.hovering = False
        if margin is not None: self.margin=margin
    
    def get_label(self): return self.label.get_label()
    def set_label(self, label): self.label.set_label(label)
    
    def mouse_enter(self):
        self.hovering = True
    def mouse_leave(self):
        self.hovering = False
    def mouse_down(self, mouse):
        self.pressed = True
    def mouse_move(self, mouse):
        self.mouse = mouse
        self.pressed = self.hover_ui(mouse) is not None
    def mouse_up(self, mouse):
        if self.pressed: self.fn_callback()
        self.pressed = False
    
    def _hover_ui(self, mouse):
        #return self if self.hovering else None
        return self if super()._hover_ui(mouse) else None
    
    def mouse_cursor(self): return 'DEFAULT'
    
    @profiler.profile
    def _draw(self):
        l,t = self.pos
        w,h = self.size
        bgl.glEnable(bgl.GL_BLEND)
        self.drawing.line_width(1)
        
        if self.hovering:
            bgcolor = self.hovercolor or self.bgcolor
        else:
            bgcolor = self.bgcolor
        
        if bgcolor:
            bgl.glColor4f(*bgcolor)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glEnd()
        
        if self.pressed and self.presscolor:
            bgl.glColor4f(*self.presscolor)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glEnd()
        
        if self.bordercolor:
            bgl.glColor4f(*self.bordercolor)
            bgl.glBegin(bgl.GL_LINE_STRIP)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glVertex2f(l,t)
            bgl.glEnd()
        
        super()._draw()
    
    def _get_tooltip(self, mouse): return self.tooltip


class UI_Options(UI_EqualContainer):
    color_select = (0.27, 0.50, 0.72, 0.90)
    color_unselect = None
    
    def __init__(self, fn_get_option, fn_set_option, vertical=True, margin=4):
        super().__init__(vertical=vertical)
        self.fn_get_option = fn_get_option
        self.fn_set_option = fn_set_option
        self.options = {}
        self.values = set()
        self.margin = margin
    
    class UI_Option(UI_Container):
        def __init__(self, options, label, value, icon=None, tooltip=None, color=(1,1,1,1), align=-1, showlabel=True):
            super().__init__(vertical=False)
            self.margin = 0
            self.label = label
            self.value = value
            self.options = options
            self.tooltip = tooltip
            if not showlabel: label = None
            if icon:           self.add(icon)
            if icon and label: self.add(UI_Spacer(width=4))
            if label:          self.add(UI_Label(label, color=color, align=align))
        
        def _hover_ui(self, mouse):
            return self if super()._hover_ui(mouse) else None
        
        @profiler.profile
        def _draw(self):
            selected = self.options.fn_get_option()
            is_selected = self.value == selected
            self.background = UI_Options.color_select if is_selected else UI_Options.color_unselect
            super()._draw()
        
        def _get_tooltip(self, mouse): return self.tooltip
    
    def add_option(self, label, value=None, icon=None, tooltip=None, color=(1,1,1,1), align=-1, showlabel=True):
        if value is None: value=label
        assert value not in self.values, "All option values must be unique!"
        self.values.add(value)
        option = UI_Options.UI_Option(self, label, value, icon=icon, tooltip=tooltip, color=color, align=align, showlabel=showlabel)
        super().add(option)
        self.options[option] = value
    
    def set_option(self, value):
        if self.fn_get_option() == value: return
        self.fn_set_option(value)
    
    def add(self, *args, **kwargs):
        assert False, "Do not call UI_Options.add()"
    
    def _hover_ui(self, mouse):
        return self if super()._hover_ui(mouse) else None
    def _get_tooltip(self, mouse):
        ui = super()._hover_ui(mouse)
        return ui._get_tooltip(mouse) if ui and ui != self else None
    
    def mouse_down(self, mouse): self.mouse_up(mouse)
    def mouse_move(self, mouse): self.mouse_up(mouse)
    def mouse_up(self, mouse):
        ui = super()._hover_ui(mouse)
        if ui is None or ui == self: return
        self.set_option(self.options[ui])
    
    @profiler.profile
    def _draw(self):
        l,t = self.pos
        w,h = self.size
        bgl.glEnable(bgl.GL_BLEND)
        self.drawing.line_width(1)
        bgl.glColor4f(0,0,0,0.1)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        bgl.glVertex2f(l,t)
        bgl.glVertex2f(l,t-h)
        bgl.glVertex2f(l+w,t-h)
        bgl.glVertex2f(l+w,t)
        bgl.glVertex2f(l,t)
        bgl.glEnd()
        super()._draw()


class UI_Image(UI_Element):
    executor = ThreadPoolExecutor()
    
    def __init__(self, image_data, async=True):
        super().__init__()
        self.image_data = image_data
        self.width,self.height = 10,10 # placeholder
        self.image_width,self.image_height = 10,10
        self.size_set = False
        self.loaded = False
        self.buffered = False
        self.deleted = False
        
        self.texbuffer = bgl.Buffer(bgl.GL_INT, [1])
        bgl.glGenTextures(1, self.texbuffer)
        self.texture_id = self.texbuffer[0]
        
        if async: self.executor.submit(self.load_image)
        else: self.load_image()
    
    def load_image(self):
        image_data = self.image_data
        if type(image_data) is str: image_data = load_image_png(image_data)
        self.image_height,self.image_width,self.image_depth = len(image_data),len(image_data[0]),len(image_data[0][0])
        assert self.image_depth == 4
        self.image_flat = [d for r in image_data for c in r for d in c]
        self.loaded = True
    
    def buffer_image(self):
        if not self.loaded: return
        if self.buffered: return
        if self.deleted: return
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, self.texture_id)
        bgl.glTexEnvf(bgl.GL_TEXTURE_ENV, bgl.GL_TEXTURE_ENV_MODE, bgl.GL_MODULATE)
        bgl.glTexParameterf(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MAG_FILTER, bgl.GL_NEAREST)
        bgl.glTexParameterf(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MIN_FILTER, bgl.GL_LINEAR)
        # texbuffer = bgl.Buffer(bgl.GL_BYTE, [self.width,self.height,self.depth], image_data)
        image_size = self.image_width*self.image_height*self.image_depth
        texbuffer = bgl.Buffer(bgl.GL_BYTE, [image_size], self.image_flat)
        bgl.glTexImage2D(bgl.GL_TEXTURE_2D, 0, bgl.GL_RGBA, self.image_width, self.image_height, 0, bgl.GL_RGBA, bgl.GL_UNSIGNED_BYTE, texbuffer)
        del texbuffer
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, 0)
        self.buffered = True
    
    def __del__(self):
        self.deleted = True
        bgl.glDeleteTextures(1, self.texbuffer)
    
    def _get_width(self): return self.drawing.scale(self.width if self.size_set else self.image_width)
    def _get_height(self): return self.drawing.scale(self.height if self.size_set else self.image_height)
    
    def set_width(self, w): self.width,self.size_set = w,True
    def set_height(self, h): self.height,self.size_set = h,True
    def set_size(self, w, h): self.width,self.height,self.size_set = w,h,True
    
    @profiler.profile
    def _draw(self):
        self.buffer_image()
        if not self.buffered: return
        
        cx,cy = self.pos + self.size / 2
        w,h = self._get_width(),self._get_height()
        l,t = cx-w/2, cy-h/2
        
        bgl.glColor4f(1,1,1,1)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_TEXTURE_2D)
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, self.texture_id)
        bgl.glBegin(bgl.GL_QUADS)
        bgl.glTexCoord2f(0,0);  bgl.glVertex2f(l,  t)
        bgl.glTexCoord2f(0,1);  bgl.glVertex2f(l,  t-h)
        bgl.glTexCoord2f(1,1);  bgl.glVertex2f(l+w,t-h)
        bgl.glTexCoord2f(1,0);  bgl.glVertex2f(l+w,t)
        bgl.glEnd()
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, 0)


class UI_Graphic(UI_Element):
    def __init__(self, graphic=None):
        super().__init__()
        self._graphic = graphic
        self.width = 12
        self.height = 12
    
    def set_graphic(self, graphic): self._graphic = graphic
    
    def _get_width(self): return self.drawing.scale(self.width)
    def _get_height(self): return self.drawing.scale(self.height)
    
    @profiler.profile
    def _draw(self):
        cx = self.pos.x + self.size.x / 2
        cy = self.pos.y - self.size.y / 2
        w,h = self.drawing.scale(self.width),self.drawing.scale(self.height)
        l,t = cx-w/2, cy+h/2
        
        self.drawing.line_width(1.0)
        
        if self._graphic == 'box unchecked':
            bgl.glColor4f(1,1,1,1)
            bgl.glBegin(bgl.GL_LINE_STRIP)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glVertex2f(l,t)
            bgl.glEnd()
        
        elif self._graphic == 'box checked':
            bgl.glColor4f(0.27,0.50,0.72,0.90)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glEnd()
            bgl.glColor4f(1,1,1,1)
            bgl.glBegin(bgl.GL_LINE_STRIP)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glVertex2f(l,t)
            bgl.glEnd()
            bgl.glBegin(bgl.GL_LINE_STRIP)
            bgl.glVertex2f(l+2,cy)
            bgl.glVertex2f(cx,t-h+2)
            bgl.glVertex2f(l+w-2,t-2)
            bgl.glEnd()
        
        elif self._graphic == 'triangle right':
            bgl.glColor4f(1,1,1,1)
            bgl.glBegin(bgl.GL_TRIANGLES)
            bgl.glVertex2f(l+2,t-2)
            bgl.glVertex2f(l+2,t-h+2)
            bgl.glVertex2f(l+w-2,cy)
            bgl.glEnd()
        
        elif self._graphic == 'triangle down':
            bgl.glColor4f(1,1,1,1)
            bgl.glBegin(bgl.GL_TRIANGLES)
            bgl.glVertex2f(l+2,t-2)
            bgl.glVertex2f(cx,t-h+2)
            bgl.glVertex2f(l+w-2,t-2)
            bgl.glEnd()
        
        elif self._graphic == 'dash':
            bgl.glColor4f(1,1,1,1)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l+2,cy-2)
            bgl.glVertex2f(l+w-2,cy-2)
            bgl.glVertex2f(l+w-2,cy+2)
            bgl.glVertex2f(l+2,cy+2)
            bgl.glEnd()


class UI_Checkbox(UI_Container):
    '''
    [ ] Label
    [V] Label
    '''
    def __init__(self, label, fn_get_checked, fn_set_checked, **kwopts):
        spacing = kwopts.get('spacing', 4)
        super().__init__(vertical=False)
        self.margin = 0
        self.chk = UI_Graphic()
        self.add(self.chk)
        if label:
            self.lbl = UI_Label(label)
            self.add(UI_Spacer(width=spacing))
            self.add(self.lbl)
        self.fn_get_checked = fn_get_checked
        self.fn_set_checked = fn_set_checked
        self.tooltip = kwopts.get('tooltip', None)
    
    def _get_tooltip(self, mouse): return self.tooltip
    
    def _hover_ui(self, mouse):
        return self if super()._hover_ui(mouse) else None
    
    def mouse_up(self, mouse): self.fn_set_checked(not self.fn_get_checked())
    
    def predraw(self):
        self.chk.set_graphic('box checked' if self.fn_get_checked() else 'box unchecked')


class UI_Checkbox2(UI_Container):
    '''
    Label
    Label  <- highlighted if checked
    '''
    def __init__(self, label, fn_get_checked, fn_set_checked, **kwopts):
        super().__init__()
        self.margin = 0
        self.add(UI_Label(label, align=0))
        self.fn_get_checked = fn_get_checked
        self.fn_set_checked = fn_set_checked
        self.tooltip = kwopts.get('tooltip', None)
    
    def _get_tooltip(self, mouse): return self.tooltip
    
    def _hover_ui(self, mouse):
        return self if super()._hover_ui(mouse) else None
    def mouse_up(self, mouse): self.fn_set_checked(not self.fn_get_checked())
    
    @profiler.profile
    def _draw(self):
        l,t = self.pos
        w,h = self.size
        
        self.drawing.line_width(1.0)
        bgl.glEnable(bgl.GL_BLEND)
        
        if self.fn_get_checked():
            bgl.glColor4f(0.27,0.50,0.72,0.90)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glEnd()
        else:
            bgl.glColor4f(0,0,0,0)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glEnd()
        
        bgl.glColor4f(0,0,0,0.1)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        bgl.glVertex2f(l,t)
        bgl.glVertex2f(l,t-h)
        bgl.glVertex2f(l+w,t-h)
        bgl.glVertex2f(l+w,t)
        bgl.glVertex2f(l,t)
        bgl.glEnd()
        
        super()._draw()

class UI_BoolValue(UI_Checkbox):
    pass


class UI_IntValue(UI_Container):
    def __init__(self, label, fn_get_value, fn_set_value, fn_get_print_value=None, fn_set_print_value=None, margin=4, bgcolor=None, hovercolor=(1,1,1,0.1), presscolor=(0,0,0,0.2), **kwargs):
        assert (fn_get_print_value is None and fn_set_print_value is None) or (fn_get_print_value is not None and fn_set_print_value is not None)
        super().__init__(vertical=False, margin=margin)
        # self.margin = 0
        self.lbl = UI_Label(label)
        self.val = UI_Label(fn_get_value())
        self.add(self.lbl)
        self.add(UI_Label(':'))
        self.add(UI_Spacer(width=4))
        self.add(self.val)
        self.fn_get_value = fn_get_value
        self.fn_set_value = fn_set_value
        self.fn_get_print_value = fn_get_print_value
        self.fn_set_print_value = fn_set_print_value
        self.downed = False
        self.captured = False
        self.time_start = time.time()
        self.tooltip = kwargs.get('tooltip', None)
        self.bgcolor = bgcolor
        self.presscolor = presscolor
        self.hovercolor = hovercolor
        self.hovering = False
    
    def _get_tooltip(self, mouse): return self.tooltip
    
    def _hover_ui(self, mouse):
        return self if super()._hover_ui(mouse) else None
    
    def mouse_down(self, mouse):
        self.down_mouse = mouse
        self.down_val = self.fn_get_value()
        self.downed = True
        set_cursor('MOVE_X')
    
    def mouse_move(self, mouse):
        self.fn_set_value(self.down_val + int((mouse.x - self.down_mouse.x)/10))
    
    def mouse_up(self, mouse):
        self.downed = False
    
    def mouse_enter(self):
        self.hovering = True
    def mouse_leave(self):
        self.hovering = False
    
    def predraw(self):
        if not self.captured:
            fn = self.fn_get_print_value if self.fn_get_print_value else self.fn_get_value
            self.val.set_label(fn())
            self.val.cursor_pos = None
        else:
            self.val.cursor_pos = self.val_pos
    
    @profiler.profile
    def _draw(self):
        r,g,b,a = (0,0,0,0.1) if not (self.downed or self.captured) else (0.8,0.8,0.8,0.5)
        l,t = self.pos
        w,h = self.size
        bgl.glEnable(bgl.GL_BLEND)
        self.drawing.line_width(1)
        
        if self.hovering:
            bgcolor = self.hovercolor or self.bgcolor
        else:
            bgcolor = self.bgcolor
        
        if bgcolor:
            bgl.glColor4f(*bgcolor)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glEnd()
        
        bgl.glColor4f(r,g,b,a)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        bgl.glVertex2f(l,t)
        bgl.glVertex2f(l,t-h)
        bgl.glVertex2f(l+w,t-h)
        bgl.glVertex2f(l+w,t)
        bgl.glVertex2f(l,t)
        bgl.glEnd()
        super()._draw()
    
    def capture_start(self):
        fn = self.fn_get_print_value if self.fn_get_print_value else self.fn_get_value
        self.val_orig = fn()
        self.val_edit = str(self.val_orig)
        self.val_pos = len(self.val_edit)
        self.captured = True
        self.keys = {
            'ZERO':   '0', 'NUMPAD_0':      '0',
            'ONE':    '1', 'NUMPAD_1':      '1',
            'TWO':    '2', 'NUMPAD_2':      '2',
            'THREE':  '3', 'NUMPAD_3':      '3',
            'FOUR':   '4', 'NUMPAD_4':      '4',
            'FIVE':   '5', 'NUMPAD_5':      '5',
            'SIX':    '6', 'NUMPAD_6':      '6',
            'SEVEN':  '7', 'NUMPAD_7':      '7',
            'EIGHT':  '8', 'NUMPAD_8':      '8',
            'NINE':   '9', 'NUMPAD_9':      '9',
            'PERIOD': '.', 'NUMPAD_PERIOD': '.',
            'MINUS':  '-', 'NUMPAD_MINUS':  '-',
        }
        set_cursor('TEXT')
        return True
    
    def capture_event(self, event):
        time_delta = time.time() - self.time_start
        self.val.cursor_symbol = None if int(time_delta*10)%5 == 0 else '|'
        if event.value == 'RELEASE':
            if event.type in {'RET','NUMPAD_ENTER'}:
                self.captured = False
                try:
                    v = float(self.val_edit)
                except:
                    v = self.val_orig
                if self.fn_set_print_value: self.fn_set_print_value(v)
                else: self.fn_set_value(v)
                return True
            if event.type == 'ESC':
                self.captured = False
                return True
        if event.value == 'PRESS':
            if event.type == 'LEFT_ARROW':
                self.val_pos = max(0, self.val_pos - 1)
            if event.type == 'RIGHT_ARROW':
                self.val_pos = min(len(self.val_edit), self.val_pos + 1)
            if event.type == 'HOME':
                self.val_pos = 0
            if event.type == 'END':
                self.val_pos = len(self.val_edit)
            if event.type == 'BACK_SPACE' and self.val_pos > 0:
                self.val_edit = self.val_edit[:self.val_pos-1] + self.val_edit[self.val_pos:]
                self.val_pos -= 1
            if event.type == 'DEL' and self.val_pos < len(self.val_edit):
                self.val_edit = self.val_edit[:self.val_pos] + self.val_edit[self.val_pos+1:]
            if event.type in self.keys:
                self.val_edit = self.val_edit[:self.val_pos] + self.keys[event.type] + self.val_edit[self.val_pos:]
                self.val_pos += 1
            self.val.set_label(self.val_edit)

class UI_UpdateValue(UI_Container):
    def __init__(self, label, fn_get_value, fn_set_value, fn_update_value, fn_get_print_value=None, fn_set_print_value=None, margin=4, bgcolor=None, hovercolor=(1,1,1,0.1), presscolor=(0,0,0,0.2), **kwargs):
        assert (fn_get_print_value is None and fn_set_print_value is None) or (fn_get_print_value is not None and fn_set_print_value is not None)
        super().__init__(vertical=False, margin=margin)
        # self.margin = 0
        self.lbl = UI_Label(label)
        self.val = UI_Label(fn_get_value())
        self.add(self.lbl)
        self.add(UI_Label(':'))
        self.add(UI_Spacer(width=4))
        self.add(self.val)
        self.fn_get_value = fn_get_value
        self.fn_set_value = fn_set_value
        self.fn_update_value = fn_update_value
        self.fn_get_print_value = fn_get_print_value
        self.fn_set_print_value = fn_set_print_value
        self.downed = False
        self.captured = False
        self.time_start = time.time()
        self.tooltip = kwargs.get('tooltip', None)
        self.bgcolor = bgcolor
        self.presscolor = presscolor
        self.hovercolor = hovercolor
        self.hovering = False

    def _get_tooltip(self, mouse): return self.tooltip
    
    def _hover_ui(self, mouse):
        return self if super()._hover_ui(mouse) else None
    
    def mouse_down(self, mouse):
        self.down_mouse = mouse
        self.prev_mouse = mouse
        self.down_val = self.fn_get_value()
        self.downed = True
        set_cursor('MOVE_X')
    
    def mouse_move(self, mouse):
        self.fn_update_value((mouse.x - self.prev_mouse.x) / 10)
        self.prev_mouse = mouse
    
    def mouse_up(self, mouse):
        self.downed = False
    
    def mouse_enter(self):
        self.hovering = True
    def mouse_leave(self):
        self.hovering = False
    
    def predraw(self):
        if not self.captured:
            fn = self.fn_get_print_value if self.fn_get_print_value else self.fn_get_value
            self.val.set_label(fn())
            self.val.cursor_pos = None
        else:
            self.val.cursor_pos = self.val_pos
    
    @profiler.profile
    def _draw(self):
        r,g,b,a = (0,0,0,0.1) if not (self.downed or self.captured) else (0.8,0.8,0.8,0.5)
        l,t = self.pos
        w,h = self.size
        bgl.glEnable(bgl.GL_BLEND)
        self.drawing.line_width(1)
        
        if self.hovering:
            bgcolor = self.hovercolor or self.bgcolor
        else:
            bgcolor = self.bgcolor
        
        if bgcolor:
            bgl.glColor4f(*bgcolor)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l,t)
            bgl.glVertex2f(l,t-h)
            bgl.glVertex2f(l+w,t-h)
            bgl.glVertex2f(l+w,t)
            bgl.glEnd()
        
        bgl.glColor4f(r,g,b,a)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        bgl.glVertex2f(l,t)
        bgl.glVertex2f(l,t-h)
        bgl.glVertex2f(l+w,t-h)
        bgl.glVertex2f(l+w,t)
        bgl.glVertex2f(l,t)
        bgl.glEnd()
        super()._draw()
    
    def capture_start(self):
        fn = self.fn_get_print_value if self.fn_get_print_value else self.fn_get_value
        self.val_orig = fn()
        self.val_edit = str(self.val_orig)
        self.val_pos = len(self.val_edit)
        self.captured = True
        self.keys = {
            'ZERO':   '0', 'NUMPAD_0':      '0',
            'ONE':    '1', 'NUMPAD_1':      '1',
            'TWO':    '2', 'NUMPAD_2':      '2',
            'THREE':  '3', 'NUMPAD_3':      '3',
            'FOUR':   '4', 'NUMPAD_4':      '4',
            'FIVE':   '5', 'NUMPAD_5':      '5',
            'SIX':    '6', 'NUMPAD_6':      '6',
            'SEVEN':  '7', 'NUMPAD_7':      '7',
            'EIGHT':  '8', 'NUMPAD_8':      '8',
            'NINE':   '9', 'NUMPAD_9':      '9',
            'PERIOD': '.', 'NUMPAD_PERIOD': '.',
            'MINUS':  '-', 'NUMPAD_MINUS':  '-',
        }
        set_cursor('TEXT')
        return True
    
    def capture_event(self, event):
        time_delta = time.time() - self.time_start
        self.val.cursor_symbol = None if int(time_delta*10)%5 == 0 else '|'
        if event.value == 'RELEASE':
            if event.type in {'RET','NUMPAD_ENTER'}:
                self.captured = False
                try:
                    v = float(self.val_edit)
                except:
                    v = self.val_orig
                if self.fn_set_print_value: self.fn_set_print_value(v)
                else: self.fn_set_value(v)
                return True
            if event.type == 'ESC':
                self.captured = False
                return True
        if event.value == 'PRESS':
            if event.type == 'LEFT_ARROW':
                self.val_pos = max(0, self.val_pos - 1)
            if event.type == 'RIGHT_ARROW':
                self.val_pos = min(len(self.val_edit), self.val_pos + 1)
            if event.type == 'HOME':
                self.val_pos = 0
            if event.type == 'END':
                self.val_pos = len(self.val_edit)
            if event.type == 'BACK_SPACE' and self.val_pos > 0:
                self.val_edit = self.val_edit[:self.val_pos-1] + self.val_edit[self.val_pos:]
                self.val_pos -= 1
            if event.type == 'DEL' and self.val_pos < len(self.val_edit):
                self.val_edit = self.val_edit[:self.val_pos] + self.val_edit[self.val_pos+1:]
            if event.type in self.keys:
                self.val_edit = self.val_edit[:self.val_pos] + self.keys[event.type] + self.val_edit[self.val_pos:]
                self.val_pos += 1
            self.val.set_label(self.val_edit)



class UI_HBFContainer(UI_Container):
    '''
    container with header, body, and footer
    '''
    def __init__(self, vertical=True):
        super().__init__()
        self.margin = 0
        self.header = UI_Container()
        self.body = UI_Container(vertical=vertical)
        self.footer = UI_Container()
        # self.header.margin = 0
        # self.body.margin = 0
        # self.footer.margin = 0
        super().add(self.header)
        super().add(self.body)
        super().add(self.footer)
    
    def _hover_ui(self, mouse):
        if not super()._hover_ui(mouse): return None
        ui = self.header.hover_ui(mouse) or self.body.hover_ui(mouse) or self.footer.hover_ui(mouse)
        return ui or self
    
    def _get_width(self): return max((c.get_width() for c in self.ui_items if c.ui_items), default=0)
    def _get_height(self): return sum((c.get_height() for c in self.ui_items if c.ui_items), 0)
    
    @profiler.profile
    def _draw(self):
        l,t = self.pos
        w,h = self.size
        hh = self.header._get_height()
        fh = self.footer._get_height()
        
        if self.background:
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glColor4f(*self.background)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l, t)
            bgl.glVertex2f(l+w, t)
            bgl.glVertex2f(l+w, t-h)
            bgl.glVertex2f(l, t-h)
            bgl.glEnd()
        
        self.header.draw(l,t,w,hh)
        self.body.draw(l,t-hh,w,h-hh-fh)
        self.footer.draw(l,t-h+fh,w,fh)
    
    def add(self, ui_item, header=False, footer=False):
        if header: self.header.add(ui_item)
        elif footer: self.footer.add(ui_item)
        else: self.body.add(ui_item)
        return ui_item


class UI_Collapsible(UI_Container):
    def __init__(self, title, collapsed=True, fn_collapsed=None, equal=False, vertical=True):
        super().__init__()
        self.margin = 0
        
        self.header = UI_Container(background=(0,0,0,0.2))
        self.body = UI_Container(vertical=vertical) if not equal else UI_EqualContainer(vertical=vertical)
        self.footer = UI_Container()
        
        self.header.margin = 0
        # self.body.margin = 0
        self.footer.margin = 0
        
        self.title = self.header.add(UI_Container(vertical=False))
        self.title.margin = 0
        self.title_arrow = self.title.add(UI_Graphic('triangle down'))
        self.title_label = self.title.add(UI_Label(title))
        # self.header.add(UI_Rule(color=(0,0,0,0.25)))
        
        self.footer.add(UI_Rule(color=(0,0,0,0.25)))
        
        def get_collapsed(): return fn_collapsed.get() if fn_collapsed else self.collapsed
        def set_collapsed(v):
            if fn_collapsed:
                fn_collapsed.set(v)
                self.collapsed = fn_collapsed.get()
            else:
                self.collapsed = v
        
        self.collapsed = fn_collapsed.get() if fn_collapsed else collapsed
        self.fn_collapsed = GetSet(get_collapsed, set_collapsed)
        
        self.versions = {
            False: [self.header, self.body, self.footer],
            True: [self.header]
        }
        self.graphics = {
            False: 'triangle down',
            True: 'triangle right',
        }
        
        super().add(self.header)
    
    def expand(self): self.fn_collapsed.set(False)
    def collapse(self): self.fn_collapsed.set(True)
    
    def predraw(self):
        #self.title.set_bgcolor(self.bgcolors[self.fn_collapsed.get()])
        self.title_arrow.set_graphic(self.graphics[self.fn_collapsed.get()])
        self.ui_items = self.versions[self.fn_collapsed.get()]
    
    def _get_width(self): return max(c.get_width() for c in self.ui_items if c.ui_items)
    def _get_height(self): return sum(c.get_height() for c in self.ui_items if c.ui_items)
    
    def add(self, ui_item, header=False):
        if header: self.header.add(ui_item)
        else: self.body.add(ui_item)
        return ui_item
    
    def _hover_ui(self, mouse):
        if not super()._hover_ui(mouse): return None
        if self.fn_collapsed.get(): return self
        return self.body.hover_ui(mouse) or self
    
    def mouse_up(self, mouse):
        if self.fn_collapsed.get():
            self.expand()
        else:
            self.collapse()


class UI_Padding(UI_Element):
    def __init__(self, ui_item=None, padding=5):
        super().__init__()
        self.margin = 0
        self.padding = padding
        self.ui_item = ui_item
    
    def set_ui_item(self, ui_item): self.ui_item = ui_item
    
    def _hover_ui(self, mouse):
        if not super()._hover_ui(mouse): return None
        ui = None if not self.ui_item else self.ui_item.hover_ui(mouse)
        return ui or self
    
    def _get_width(self):
        return self.drawing.scale(self.padding*2) + (0 if not self.ui_item else self.ui_item.get_width())
    def _get_height(self):
        return self.drawing.scale(self.padding*2) + (0 if not self.ui_item else self.ui_item.get_height())
    
    @profiler.profile
    def _draw(self):
        if not self.ui_item: return
        p = self.padding
        l,t = self.pos
        w,h = self.size
        self.ui_item.draw(l+p,t-p,w-p*2,h-p*2)
    


class UI_Window(UI_Padding):
    screen_margin = 5
    
    def __init__(self, title, options):
        vertical = options.get('vertical', True)
        padding = options.get('padding', 0)
        
        super().__init__(padding=padding)
        self.margin = 0
        
        fn_sticky = options.get('fn_pos', None)
        def get_sticky(): return fn_sticky.get() if fn_sticky else self.sticky
        def set_sticky(v):
            if fn_sticky:
                fn_sticky.set(v)
                self.sticky = fn_sticky.get()
            else:
                self.sticky = v
        
        self.sticky    = fn_sticky.get() if fn_sticky else options.get('pos', 5)
        self.fn_sticky = GetSet(get_sticky, set_sticky)
        self.visible   = options.get('visible', True)
        self.movable   = options.get('movable', True)
        self.bgcolor   = options.get('bgcolor', (0,0,0,0.25))
        
        self.fn_event_handler = options.get('event handler', None)
        
        self.mouse = Point2D((0,0))
        
        self.ui_hover = None
        self.ui_grab = [self]
        self.drawing.text_size(12)
        self.hbf = UI_HBFContainer(vertical=vertical)
        self.hbf.header.margin = 1
        self.hbf.footer.margin = 0
        self.hbf.header.background = (0,0,0,0.2)
        if title:
            self.hbf_title = UI_Label(title, align=0, color=(1,1,1,0.5))
            self.hbf_title.margin = 1
            self.hbf_title_rule = UI_Rule(color=(0,0,0,0.1))
            self.hbf.add(self.hbf_title, header=True)
            self.hbf.add(self.hbf_title_rule, header=True)
            self.ui_grab += [self.hbf_title, self.hbf_title_rule]
        self.set_ui_item(self.hbf)
        
        self.update_pos()
        
        self.FSM = {}
        self.FSM['main'] = self.modal_main
        self.FSM['move'] = self.modal_move
        self.FSM['down'] = self.modal_down
        self.FSM['capture'] = self.modal_capture
        self.FSM['scroll'] = self.modal_scroll
        self.state = 'main'
    
    def show(self): self.visible = True
    def hide(self): self.visible = False
    
    def add(self, *args, **kwargs): return self.hbf.add(*args, **kwargs)
    
    def update_pos(self):
        m = self.screen_margin
        w,h = self.get_width(),self.get_height()
        rgn = self.context.region
        if not rgn: return
        sw,sh = rgn.width,rgn.height
        cw,ch = round((sw-w)/2),round((sh+h)/2)
        sticky_positions = {
            7: (0, sh), 8: (cw, sh), 9: (sw, sh),
            4: (0, ch), 5: (cw, ch), 6: (sw, ch),
            1: (0, 0),  2: (cw, 0),  3: (sw, 0),
        }
        
        sticky = self.fn_sticky.get()
        if type(sticky) is not int:
            l,t = sticky
            stick_t,stick_b = t >= sh - m, t <= m + h
            stick_l,stick_r = l <= m, l >= sw - m - w
            nsticky = None
            if stick_t:
                if stick_l: nsticky = 7
                if stick_r: nsticky = 9
            elif stick_b:
                if stick_l: nsticky = 1
                if stick_r: nsticky = 3
            if nsticky:
                self.fn_sticky.set(nsticky)
                sticky = self.fn_sticky.get()
        pos = sticky_positions[sticky] if type(sticky) is int else sticky
        
        # clamp position so window is always seen
        l,t = pos
        w = min(w, sw-m*2)
        h = min(h, sh-m*2)
        l = max(m,   min(sw-m-w,l))
        t = max(m+h, min(sh-m,  t))
        
        self.pos = Point2D((l,t))
        self.size = Vec2D((w,h))
        
        if self.hbf.body.pos and self.hbf.body.size:
            offset = self.hbf.body.offset
            l,t = self.hbf.body.pos
            w,h = self.hbf.body.size
            ah = self.hbf.body._get_height()
            offset = max(0, min(ah-h, offset))
            self.hbf.body.offset = offset
    
    def draw_postpixel(self):
        if not self.visible: return
        
        self.drawing.text_size(12)
        
        self.update_pos()
        
        l,t = self.pos
        w,h = self.size
        
        bgl.glEnable(bgl.GL_BLEND)
        
        # draw background
        bgl.glColor4f(*self.bgcolor)
        bgl.glBegin(bgl.GL_QUADS)
        bgl.glVertex2f(l,t)
        bgl.glVertex2f(l,t-h)
        bgl.glVertex2f(l+w,t-h)
        bgl.glVertex2f(l+w,t)
        bgl.glEnd()
        
        self.drawing.line_width(1.0)
        bgl.glColor4f(0,0,0,0.5)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        bgl.glVertex2f(l,t)
        bgl.glVertex2f(l,t-h)
        bgl.glVertex2f(l+w,t-h)
        bgl.glVertex2f(l+w,t)
        bgl.glVertex2f(l,t)
        bgl.glEnd()
        
        self.draw(l, t, w, h)
    
    def update_hover(self, new_elem):
        if self.ui_hover == new_elem: return
        if self.ui_hover and self.ui_hover != self: self.ui_hover.mouse_leave()
        self.ui_hover = new_elem
        if self.ui_hover and self.ui_hover != self: self.ui_hover.mouse_enter()
    
    def mouse_enter(self): self.update_hover(self.hover_ui(self.mouse))
    def mouse_leave(self): self.update_hover(None)
    
    def modal(self, context, event):
        self.mouse = Point2D((float(event.mouse_region_x), float(event.mouse_region_y)))
        self.context = context
        self.event = event
        
        if not self.visible: return
        
        nstate = self.FSM[self.state]()
        self.state = nstate or self.state
        
        return {'hover'} if self.hover_ui(self.mouse) or self.state != 'main' else {}
    
    def get_tooltip(self):
        self.mouse_enter()
        #self.ui_hover = self.hover_ui(self.mouse)
        return self.ui_hover._get_tooltip(self.mouse) if self.ui_hover else None
    
    def modal_main(self):
        self.mouse_enter()
        if not self.ui_hover: return
        set_cursor(self.ui_hover.mouse_cursor())
        
        if self.event.type == 'LEFTMOUSE' and self.event.value == 'PRESS':
            self.mouse_down = self.mouse
            if self.movable and self.ui_hover in self.ui_grab:
                self.mouse_prev = self.mouse
                self.pos_prev = self.pos
                return 'move'
            self.ui_down = self.ui_hover
            self.ui_down.mouse_down(self.mouse)
            self.mouse_moved = False
            return 'down'
        
        if self.event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'PAGE_UP', 'PAGE_DOWN', 'TRACKPADPAN'}:
            if self.event.type == 'TRACKPADPAN':
                move = self.event.mouse_y - self.event.mouse_prev_y
            else:
                move = self.drawing.scale(24) * (-1 if 'UP' in self.event.type else 1)
            offset = self.hbf.body.offset + move
            l,t = self.hbf.body.pos
            w,h = self.hbf.body.size
            ah = self.hbf.body._get_height()
            offset = max(0, min(ah-h, offset))
            self.hbf.body.offset = offset
            return
        
        if self.event.type == 'MIDDLEMOUSE' and self.event.value == 'PRESS':
            self.mouse_down = self.mouse
            self.mouse_prev = self.mouse
            return 'scroll'
    
    def modal_scroll(self):
        set_cursor('HAND')
        if self.event.type == 'MIDDLEMOUSE' and self.event.value == 'RELEASE':
            return 'main'
        move = (self.mouse.y - self.mouse_prev.y)
        offset = self.hbf.body.offset + move
        l,t = self.hbf.body.pos
        w,h = self.hbf.body.size
        ah = self.hbf.body._get_height()
        offset = max(0, min(ah-h, offset))
        self.hbf.body.offset = offset
        self.mouse_prev = self.mouse
    
    def scrollto_top(self):
        self.hbf.body.offset = 0
    def scrollto_bottom(self):
        w,h = self.hbf.body.size
        ah = self.hbf.body._get_height()
        self.hbf.body.offset = ah - h
    
    def modal_move(self):
        set_cursor('HAND')
        if self.event.type == 'LEFTMOUSE' and self.event.value == 'RELEASE':
            return 'main'
        diff = self.mouse - self.mouse_down
        self.fn_sticky.set(self.pos_prev + diff)
        self.update_pos()
        self.mouse_prev = self.mouse
    
    def modal_down(self):
        if self.event.type == 'LEFTMOUSE' and self.event.value == 'RELEASE':
            self.ui_down.mouse_up(self.mouse)
            if not self.mouse_moved and self.ui_down.capture_start(): return 'capture'
            return 'main'
        self.mouse_moved |= self.mouse_down != self.mouse
        self.ui_down.mouse_move(self.mouse)
    
    def modal_capture(self):
        if self.ui_down.capture_event(self.event): return 'main'
    
    def distance(self, pt):
        px,py = self.pos
        sx,sy = self.size
        c = Point2D((mid(px, px+sx, pt.x), mid(py, py-sy, pt.y)))
        return (pt - c).length

class UI_Event:
    def __init__(self, type, value):
        self.type = type
        self.value = value


class UI_WindowManager:
    def __init__(self, **kwargs):
        self.drawing = Drawing.get_instance()
        self.windows = []
        self.windows_unfocus = None
        self.active = None
        self.active_last = None
        self.focus = None
        self.focus_darken = True
        self.focus_close_on_leave = True
        self.focus_close_distance = self.drawing.scale(30)
        
        self.tooltip_delay = 0.75
        self.tooltip_value = None
        self.tooltip_time = time.time()
        self.tooltip_show = kwargs.get('show tooltips', True)
        self.tooltip_window = UI_Window(None, {'bgcolor':(0,0,0,0.75), 'visible':False})
        self.tooltip_label = self.tooltip_window.add(UI_Label('foo bar'))
        self.tooltip_offset = Vec2D((15, -15))
    
    def set_show_tooltips(self, v):
        self.tooltip_show = v
        if not v: self.tooltip_window.visible = v
    def set_tooltip_label(self, v):
        if not v:
            self.tooltip_window.visible = False
            self.tooltip_value = None
            return
        if self.tooltip_value != v:
            self.tooltip_window.visible = False
            self.tooltip_value = v
            self.tooltip_time = time.time()
            self.tooltip_label.set_label(v)
            return
        if time.time() >= self.tooltip_time + self.tooltip_delay:
            self.tooltip_window.visible = self.tooltip_show
        # self.tooltip_window.fn_sticky.set(self.active.pos + self.active.size)
        # self.tooltip_window.update_pos()
    
    def create_window(self, title, options):
        win = UI_Window(title, options)
        self.windows.append(win)
        return win
    
    def delete_window(self, win):
        win.fn_event_handler(None, UI_Event('WINDOW', 'CLOSE'))
        win.delete()
        if win == self.focus: self.clear_focus()
        if win == self.active: self.clear_active()
        if win in self.windows: self.windows.remove(win)
    
    def clear_active(self): self.active = None
    
    def has_focus(self): return self.focus is not None
    def set_focus(self, win, darken=True, close_on_leave=False):
        self.clear_focus()
        if win is None: return
        win.visible = True
        self.focus = win
        self.focus_darken = darken
        self.focus_close_on_leave = close_on_leave
        self.active = win
        self.windows_unfocus = [win for win in self.windows if win != self.focus]
        self.windows = [self.focus]
        
    def clear_focus(self):
        if self.focus is None: return
        self.windows += self.windows_unfocus
        self.windows_unfocus = None
        self.active = None
        self.focus = None
    
    def draw_darken(self):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        bgl.glColor4f(0,0,0,0.25)    # TODO: use window background color??
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDisable(bgl.GL_DEPTH_TEST)
        bgl.glBegin(bgl.GL_QUADS)   # TODO: not use immediate mode
        bgl.glVertex2f(-1, -1)
        bgl.glVertex2f( 1, -1)
        bgl.glVertex2f( 1,  1)
        bgl.glVertex2f(-1,  1)
        bgl.glEnd()
        bgl.glPopMatrix()
        bgl.glPopAttrib()
    
    def draw_postpixel(self):
        if self.focus:
            for win in self.windows_unfocus:
                win.draw_postpixel()
            if self.focus_darken:
                self.draw_darken()
            self.focus.draw_postpixel()
        else:
            for win in self.windows:
                win.draw_postpixel()
        self.tooltip_window.draw_postpixel()
    
    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            mouse = Point2D((float(event.mouse_region_x), float(event.mouse_region_y)))
            self.tooltip_window.fn_sticky.set(mouse + self.tooltip_offset)
            self.tooltip_window.update_pos()
            if self.focus and self.focus_close_on_leave:
                d = self.focus.distance(mouse)
                if d > self.focus_close_distance:
                    self.delete_window(self.focus)

        ret = {}
        
        if self.active and self.active.state != 'main':
            ret = self.active.modal(context, event)
            if not ret: self.active = None
        elif self.focus:
            ret = self.focus.modal(context, event)
        else:
            self.active = None
            for win in reversed(self.windows):
                ret = win.modal(context, event)
                if ret:
                    self.active = win
                    break
        
        if self.active != self.active_last:
            if self.active_last and self.active_last.fn_event_handler:
                self.active_last.fn_event_handler(context, UI_Event('HOVER', 'LEAVE'))
            if self.active and self.active.fn_event_handler:
                self.active.fn_event_handler(context, UI_Event('HOVER', 'ENTER'))
        self.active_last = self.active
        
        if self.active:
            if self.active.fn_event_handler:
                self.active.fn_event_handler(context, event)
            if self.active:
                tooltip = self.active.get_tooltip()
                self.set_tooltip_label(tooltip)
        else:
            self.set_tooltip_label(None)
        
        return ret




