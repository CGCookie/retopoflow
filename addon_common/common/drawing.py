'''
Copyright (C) 2023 CG Cookie
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
import ctypes
import random
from typing import List
import traceback
import functools
import contextlib
import urllib.request
from functools import wraps
from itertools import chain

import bpy
import gpu
from bpy.types import BoolProperty
from mathutils import Matrix, Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d

from .blender import bversion, get_path_from_addon_root, get_path_from_addon_common
from .blender_cursors import Cursors
from .blender_preferences import get_preferences
from .debug import dprint, debugger
from .decorators import blender_version_wrapper, add_cache, only_in_blender_version
from .fontmanager import FontManager as fm
from .functools import find_fns
from .globals import Globals
from .hasher import Hasher
from .maths import Point2D, Vec2D, Point, Ray, Direction, mid, Color, Normal, Frame
from .profiler import profiler
from .utils import iter_pairs
from . import gpustate


class Drawing:
    _instance = None
    _dpi_mult = 1
    _custom_dpi_mult = 1
    _prefs = get_preferences()
    _error_check = True
    _error_count = 0
    _error_limit = 10 # after this many check errors, no more will be reported to console

    @staticmethod
    def get_custom_dpi_mult():
        return Drawing._custom_dpi_mult
    @staticmethod
    def set_custom_dpi_mult(v):
        Drawing._custom_dpi_mult = v
        Drawing.update_dpi()

    @staticmethod
    def update_dpi():
        # print(f'view.ui_scale={Drawing._prefs.view.ui_scale}, system.ui_scale={Drawing._prefs.system.ui_scale}, system.dpi={Drawing._prefs.system.dpi}')
        Drawing._dpi_mult = (
            1.0
            * Drawing._custom_dpi_mult
            # * Drawing._prefs.view.ui_scale
            * max(0.25, Drawing._prefs.system.ui_scale) # math.floor(Drawing._prefs.system.ui_scale))
            # * (72.0 / Drawing._prefs.system.dpi)
            # * Drawing._prefs.system.pixel_size
        )

    @staticmethod
    def initialize():
        Drawing.update_dpi()
        if Globals.is_set('drawing'): return
        Drawing._creating = True
        Globals.set(Drawing())
        del Drawing._creating
        Drawing._instance = Globals.drawing

    def __init__(self):
        assert hasattr(self, '_creating'), "Do not instantiate directly.  Use Drawing.get_instance()"

        self.area,self.space,self.rgn,self.r3d,self.window = None,None,None,None,None
        # self.font_id = 0
        self.last_font_key = None
        self.fontid = 0
        self.fontsize = None
        self.fontsize_scaled = None
        self.line_cache = {}
        self.size_cache = {}
        self.set_font_size(12)
        self._pixel_matrix = None

    def set_region(self, area, space, rgn, r3d, window):
        self.area = area
        self.space = space
        self.rgn = rgn
        self.r3d = r3d
        self.window = window

    @staticmethod
    def set_cursor(cursor): Cursors.set(cursor)

    def scale(self, s): return s * self._dpi_mult if s is not None else None
    def unscale(self, s): return s / self._dpi_mult if s is not None else None
    def get_dpi_mult(self): return self._dpi_mult
    def get_pixel_size(self): return self._pixel_size
    def line_width(self, width): gpustate.line_width(max(1, self.scale(width)))
    def point_size(self, size): gpustate.point_size(max(1, self.scale(size)))

    def set_font_color(self, fontid, color):
        fm.color(color, fontid=fontid)

    def set_font_size(self, fontsize, fontid=None, force=False):
        if fontid is None: fontid = fm._last_fontid
        else: fontid = fm.load(fontid)
        fontsize_prev = self.fontsize
        fontsize, fontsize_scaled = int(fontsize), int(int(fontsize) * self._dpi_mult)
        cache_key = (fontid, fontsize_scaled)
        if self.last_font_key == cache_key and not force: return fontsize_prev
        fm.size(fontsize_scaled, fontid=fontid)
        if cache_key not in self.line_cache:
            # cache away useful details about font (line height, line base)
            dprint('Caching new scaled font size:', cache_key)
            all_chars = ''.join([
                'abcdefghijklmnopqrstuvwxyz',
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                '0123456789',
                '!@#$%%^&*()`~[}{]/?=+\\|-_\'",<.>',
                'ΑαΒβΓγΔδΕεΖζΗηΘθΙιΚκΛλΜμΝνΞξΟοΠπΡρΣσςΤτΥυΦφΧχΨψΩω',
            ])
            all_caps = all_chars.upper()
            self.line_cache[cache_key] = {
                'line height': math.ceil(fm.dimensions(all_chars, fontid=fontid)[1] + self.scale(4)),
                'line base': math.ceil(fm.dimensions(all_caps, fontid=fontid)[1]),
            }
        info = self.line_cache[cache_key]
        self.line_height = info['line height']
        self.line_base = info['line base']
        self.fontid = fontid
        self.fontsize = fontsize
        self.fontsize_scaled = fontsize_scaled
        self.last_font_key = cache_key

        return fontsize_prev

    def get_text_size_info(self, text, item, fontsize=None, fontid=None):
        if fontsize or fontid: size_prev = self.set_font_size(fontsize, fontid=fontid)

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
                d['width'] = max(get_width(l) for l in lines)
                d['height'] = get_height(text)
                d['line height'] = self.line_height * len(lines)
            self.size_cache[key] = d
            if False:
                print('')
                print('--------------------------------------')
                print('> computed new size')
                print('>   key: %s' % str(key))
                print('>   size: %s' % str(d))
                print('--------------------------------------')
                print('')
        if fontsize: self.set_font_size(size_prev, fontid=fontid)
        return self.size_cache[key][item]

    def get_text_width(self, text, fontsize=None, fontid=None):
        return self.get_text_size_info(text, 'width', fontsize=fontsize, fontid=fontid)
    def get_text_height(self, text, fontsize=None, fontid=None):
        return self.get_text_size_info(text, 'height', fontsize=fontsize, fontid=fontid)
    def get_line_height(self, text=None, fontsize=None, fontid=None):
        return self.get_text_size_info(text, 'line height', fontsize=fontsize, fontid=fontid)

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

    def text_color_set(self, color, fontid):
        if color is not None: fm.color(color, fontid=fontid)

    def text_draw2D(self, text, pos:Point2D, *, color=None, dropshadow=None, fontsize=None, fontid=None, lineheight=True):
        if fontsize: size_prev = self.set_font_size(fontsize, fontid=fontid)

        lines = str(text).splitlines()
        l,t = round(pos[0]),round(pos[1])
        lh,lb = self.line_height,self.line_base

        if dropshadow:
            self.text_draw2D(text, (l+1,t-1), color=dropshadow, fontsize=fontsize, fontid=fontid, lineheight=lineheight)

        gpustate.blend('ALPHA')
        self.text_color_set(color, fontid)
        for line in lines:
            fm.draw(line, xyz=(l, t - lb, 0), fontid=fontid)
            t -= lh if lineheight else self.get_text_height(line)

        if fontsize: self.set_font_size(size_prev, fontid=fontid)

    def text_draw2D_simple(self, text, pos:Point2D):
        l,t = round(pos[0]),round(pos[1])
        lb = self.line_base
        fm.draw_simple(text, xyz=(l, t - lb, 0))


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

    def load_pixel_matrix(self, m):
        self._pixel_matrix = m

    @add_cache('_cache', {'w':-1, 'h':-1, 'm':None})
    def get_pixel_matrix(self):
        '''
        returns MVP for pixel view
        TODO: compute separate M,V,P matrices
        '''
        if not self.r3d: return None
        if self._pixel_matrix: return self._pixel_matrix
        w,h = self.rgn.width,self.rgn.height
        cache = self.get_pixel_matrix._cache
        if cache['w'] != w or cache['h'] != h:
            mx, my, mw, mh = -1, -1, 2 / w, 2 / h
            cache['w'],cache['h'] = w,h
            cache['m'] = Matrix([
                [ mw,  0,  0, mx],
                [  0, mh,  0, my],
                [  0,  0,  1,  0],
                [  0,  0,  0,  1]
            ])
        return cache['m']

    def get_view_matrix_list(self):
        return list(self.get_view_matrix()) if self.r3d else None

    def get_view_matrix(self):
        return self.r3d.perspective_matrix if self.r3d else None

    def get_view_version(self):
        if not self.r3d: return None
        return Hasher(self.r3d.view_matrix, self.space.lens, self.r3d.view_distance)

    @staticmethod
    def glCheckError(title, **kwargs):
        return gpustate.get_glerror(title, **kwargs)

    @staticmethod
    @contextlib.contextmanager
    def glCheckError_wrap(title, *, stop_on_error=False):
        if Drawing.glCheckError(f'addon common: pre {title}') and stop_on_error: return True
        yield None
        if Drawing.glCheckError(f'addon common: post {title}') and stop_on_error: return True
        return False

    def get_view_origin(self, *, orthographic_distance=1000):
        focus = self.r3d.view_location
        rot = self.r3d.view_rotation
        dist = self.r3d.view_distance if self.r3d.is_perspective else orthographic_distance
        return focus + (rot @ Vector((0, 0, dist)))

        # # the following fails in weird ways when in orthographic projection
        # center = Point2D((self.area.width / 2, self.area.height / 2))
        # return Point(region_2d_to_origin_3d(self.rgn, self.r3d, center))

    def Point2D_to_Ray(self, p2d):
        o = Point(region_2d_to_origin_3d(self.rgn, self.r3d, p2d))
        d = Direction(region_2d_to_vector_3d(self.rgn, self.r3d, p2d))
        return Ray(o, d)

    def Point_to_Point2D(self, p3d):
        return Point2D(location_3d_to_region_2d(self.rgn, self.r3d, p3d))

    @blender_version_wrapper('>=', '2.80')
    def draw2D_point(self, pt:Point2D, color:Color, *, radius=1, border=0, borderColor=None):
        radius = self.scale(radius)
        border = self.scale(border)
        if borderColor is None: borderColor = (0,0,0,0)
        shader_2D_point.bind()
        ubos_2D_point.options.screensize = (self.area.width, self.area.height, 0, 0)
        ubos_2D_point.options.mvpmatrix = self.get_pixel_matrix()
        ubos_2D_point.options.radius_border = (radius, border, 0, 0)
        ubos_2D_point.options.color = color
        ubos_2D_point.options.colorBorder = borderColor
        ubos_2D_point.options.center = (*pt, 0, 1)
        ubos_2D_point.update_shader()
        batch_2D_point.draw(shader_2D_point)
        gpu.shader.unbind()

    @blender_version_wrapper('>=', '2.80')
    def draw2D_points(self, pts:[Point2D], color:Color, *, radius=1, border=0, borderColor=None):
        radius = self.scale(radius)
        border = self.scale(border)
        if borderColor is None: borderColor = (0,0,0,0)
        shader_2D_point.bind()
        ubos_2D_point.options.screensize = (self.area.width, self.area.height, 0, 0)
        ubos_2D_point.options.mvpmatrix = self.get_pixel_matrix()
        ubos_2D_point.options.radius_border = (radius, border, 0, 0)
        ubos_2D_point.options.color = color
        ubos_2D_point.options.colorBorder = borderColor
        for pt in pts:
            ubos_2D_point.options.center = (*pt, 0, 1)
            ubos_2D_point.update_shader()
            batch_2D_point.draw(shader_2D_point)
        gpu.shader.unbind()

    # draw line segment in screen space
    def draw2D_line(self, p0:Point2D, p1:Point2D, color0:Color, *, color1=None, width=1, stipple=None, offset=0):
        if color1 is None: color1 = (color0[0],color0[1],color0[2],0)
        width = self.scale(width)
        stipple = [self.scale(v) for v in stipple] if stipple else [1.0, 0.0]
        offset = self.scale(offset)
        shader_2D_lineseg.bind()
        ubos_2D_lineseg.options.MVPMatrix = self.get_pixel_matrix()
        ubos_2D_lineseg.options.screensize = (self.area.width, self.area.height, 0, 0)
        ubos_2D_lineseg.options.pos0 = (*p0, 0, 1)
        ubos_2D_lineseg.options.color0 = color0
        ubos_2D_lineseg.options.pos1 = (*p1, 0, 1)
        ubos_2D_lineseg.options.color1 = color1
        ubos_2D_lineseg.options.stipple_width = (stipple[0], stipple[1], offset, width)
        ubos_2D_lineseg.update_shader()
        batch_2D_lineseg.draw(shader_2D_lineseg)
        gpu.shader.unbind()

    def draw2D_lines(self, points, color0:Color, *, color1=None, width=1, stipple=None, offset=0):
        self.glCheckError('starting draw2D_lines')
        if color1 is None: color1 = (color0[0],color0[1],color0[2],0)
        width = self.scale(width)
        stipple = [self.scale(v) for v in stipple] if stipple else [1.0, 0.0]
        offset = self.scale(offset)
        shader_2D_lineseg.bind()
        ubos_2D_lineseg.options.MVPMatrix = self.get_pixel_matrix()
        ubos_2D_lineseg.options.screensize = (self.area.width, self.area.height, 0, 0)
        ubos_2D_lineseg.options.color0 = color0
        ubos_2D_lineseg.options.color1 = color1
        ubos_2D_lineseg.options.stipple_width = (stipple[0], stipple[1], offset, width)
        for i in range(len(points)//2):
            p0,p1 = points[i*2:i*2+2]
            if p0 is None or p1 is None: continue
            ubos_2D_lineseg.options.pos0 = (*p0, 0, 1)
            ubos_2D_lineseg.options.pos1 = (*p1, 0, 1)
            ubos_2D_lineseg.update_shader()
            batch_2D_lineseg.draw(shader_2D_lineseg)
        gpu.shader.unbind()
        self.glCheckError('done with draw2D_lines')

    def draw3D_lines(self, points, color0:Color, *, color1=None, width=1, stipple=None, offset=0):
        self.glCheckError('starting draw3D_lines')
        if color1 is None: color1 = (color0[0],color0[1],color0[2],0)
        width = self.scale(width)
        stipple = [self.scale(v) for v in stipple] if stipple else [1.0, 0.0]
        offset = self.scale(offset)
        shader_2D_lineseg.bind()
        ubos_2D_lineseg.options.screensize = (self.area.width, self.area.height)
        ubos_2D_lineseg.options.color0 = color0
        ubos_2D_lineseg.options.color1 = color1
        ubos_2D_lineseg.options.stipple_width = (stipple[0], stipple[1], offset, width)
        ubos_2D_lineseg.options.MVPMatrix = self.get_view_matrix()
        for i in range(len(points)//2):
            p0,p1 = points[i*2:i*2+2]
            if p0 is None or p1 is None: continue
            ubos_2D_lineseg.options.pos0 = (*p0, 0, 1)
            ubos_2D_lineseg.options.pos1 = (*p1, 0, 1)
            ubos_2D_lineseg.update_shader()
            batch_2D_lineseg.draw(shader_2D_lineseg)
        gpu.shader.unbind()
        self.glCheckError('done with draw3D_lines')

    def draw2D_linestrip(self, points, color0:Color, *, color1=None, width=1, stipple=None, offset=0):
        if color1 is None: color1 = (color0[0],color0[1],color0[2],0)
        width = self.scale(width)
        stipple = [self.scale(v) for v in stipple] if stipple else [1.0, 0.0]
        offset = self.scale(offset)
        shader_2D_lineseg.bind()
        ubos_2D_lineseg.options.MVPMatrix = self.get_pixel_matrix()
        ubos_2D_lineseg.options.screensize = (self.area.width, self.area.height)
        ubos_2D_lineseg.options.color0 = color0
        ubos_2D_lineseg.options.color1 = color1
        for p0,p1 in iter_pairs(points, False):
            ubos_2D_lineseg.options.pos0 = (*p0, 0, 1)
            ubos_2D_lineseg.options.pos1 = (*p1, 0, 1)
            ubos_2D_lineseg.options.stipple_width = (stipple[0], stipple[1], offset, width)
            ubos_2D_lineseg.update_shader()
            batch_2D_lineseg.draw(shader_2D_lineseg)
            offset += (p1 - p0).length
        gpu.shader.unbind()

    # draw circle in screen space
    def draw2D_circle(self, center:Point2D, radius:float, color0:Color, *, color1=None, width=1, stipple=None, offset=0):
        if color1 is None: color1 = (color0[0],color0[1],color0[2],0)
        radius = self.scale(radius)
        width = self.scale(width)
        stipple = [self.scale(v) for v in stipple] if stipple else [1,0]
        offset = self.scale(offset)
        shader_2D_circle.bind()
        ubos_2D_circle.options.MVPMatrix = self.get_pixel_matrix()
        ubos_2D_circle.options.screensize = (self.area.width, self.area.height, 0.0, 0.0)
        ubos_2D_circle.options.center = (center.x, center.y, 0.0, 0.0)
        ubos_2D_circle.options.color0 = color0
        ubos_2D_circle.options.color1 = color1
        ubos_2D_circle.options.radius_width = (radius, width, 0.0, 0.0)
        ubos_2D_circle.options.stipple_data = (*stipple, offset, 0.0)
        ubos_2D_circle.update_shader()
        batch_2D_circle.draw(shader_2D_circle)
        gpu.shader.unbind()

    def draw3D_circle(self, center:Point, radius:float, color:Color, *, width=1, n:Normal=None, x:Direction=None, y:Direction=None, depth_near=0, depth_far=1):
        assert n is not None or x is not None or y is not None, 'Must specify at least one of n,x,y'
        f = Frame(o=center, x=x, y=y, z=n)
        radius = self.scale(radius)
        width = self.scale(width)
        shader_3D_circle.bind()
        ubos_3D_circle.options.MVPMatrix = self.get_view_matrix()
        ubos_3D_circle.options.screensize = (self.area.width, self.area.height, 0.0, 0.0)
        ubos_3D_circle.options.center    = f.o
        ubos_3D_circle.options.color     = color
        ubos_3D_circle.options.plane_x   = f.x
        ubos_3D_circle.options.plane_y   = f.y
        ubos_3D_circle.options.settings  = (radius, width, depth_near, depth_far)
        ubos_3D_circle.update_shader()
        batch_3D_circle.draw(shader_3D_circle)
        gpu.shader.unbind()

    def draw3D_triangles(self, points:[Point], colors:[Color]):
        self.glCheckError('starting draw3D_triangles')
        shader_3D_triangle.bind()
        ubos_3D_triangle.options.MVPMatrix = self.get_view_matrix()
        for i in range(0, len(points), 3):
            p0,p1,p2 = points[i:i+3]
            c0,c1,c2 = colors[i:i+3]
            if p0 is None or p1 is None or p2 is None: continue
            if c0 is None or c1 is None or c2 is None: continue
            ubos_3D_triangle.options.pos0   = p0
            ubos_3D_triangle.options.color0 = c0
            ubos_3D_triangle.options.pos1   = p1
            ubos_3D_triangle.options.color1 = c1
            ubos_3D_triangle.options.pos2   = p2
            ubos_3D_triangle.options.color2 = c2
            ubos_3D_triangle.update_shader()
            batch_3D_triangle.draw(shader_3D_triangle)
        gpu.shader.unbind()
        self.glCheckError('done with draw3D_triangles')

    @contextlib.contextmanager
    def draw(self, draw_type:"CC_DRAW"):
        assert getattr(self, '_draw', None) is None, 'Cannot nest Drawing.draw calls'
        self._draw = draw_type
        self.glCheckError('starting draw')
        try:
            draw_type.begin()
            yield draw_type
            draw_type.end()
        except Exception as e:
            print('Exception caught while in Drawing.draw with %s' % str(draw_type))
            debugger.print_exception()
        self.glCheckError('done with draw')
        self._draw = None

if not bpy.app.background:
    Drawing.glCheckError(f'pre-init check: Drawing')
    Drawing.initialize()
    Drawing.glCheckError(f'post-init check: Drawing')




if not bpy.app.background and bpy.app.version >= (3, 2, 0):
    import gpu
    from gpu_extras.batch import batch_for_shader

    # https://docs.blender.org/api/blender2.8/gpu.html#triangle-with-custom-shader

    def create_shader(fn_glsl):
        path_glsl = get_path_from_addon_common('common', 'shaders', fn_glsl)
        txt = open(path_glsl, 'rt').read()
        vert_source, frag_source = gpustate.shader_parse_string(txt)
        try:
            Drawing.glCheckError(f'pre-compile check: {fn_glsl}')
            ret = gpustate.gpu_shader(f'drawing {fn_glsl}', vert_source, frag_source)
            Drawing.glCheckError(f'post-compile check: {fn_glsl}')
            return ret
        except Exception as e:
            print('ERROR WHILE COMPILING SHADER %s' % fn_glsl)
            assert False

    Drawing.glCheckError(f'Pre-compile check: point, lineseg, circle, triangle shaders')

    # 2D point
    shader_2D_point, ubos_2D_point = create_shader('point_2D.glsl')
    batch_2D_point = batch_for_shader(shader_2D_point, 'TRIS', {"pos": [(0,0), (1,0), (1,1), (0,0), (1,1), (0,1)]})

    # 2D line segment
    shader_2D_lineseg, ubos_2D_lineseg = create_shader('lineseg_2D.glsl')
    batch_2D_lineseg = batch_for_shader(shader_2D_lineseg, 'TRIS', {"pos": [(0,0), (1,0), (1,1), (0,0), (1,1), (0,1)]})

    # 2D circle
    shader_2D_circle, ubos_2D_circle = create_shader('circle_2D.glsl')
    # create batch to draw large triangle that covers entire clip space (-1,-1)--(+1,+1)
    cnt = 100
    pts = [
        p for i0 in range(cnt)
        for p in [
            ((i0+0)/cnt,0), ((i0+1)/cnt,0), ((i0+1)/cnt,1),
            ((i0+0)/cnt,0), ((i0+1)/cnt,1), ((i0+0)/cnt,1),
        ]
    ]
    batch_2D_circle = batch_for_shader(shader_2D_circle, 'TRIS', {"pos": pts})

    # 3D circle
    shader_3D_circle, ubos_3D_circle = create_shader('circle_3D.glsl')
    # create batch to draw large triangle that covers entire clip space (-1,-1)--(+1,+1)
    cnt = 100
    pts = [
        p for i0 in range(cnt)
        for p in [
            ((i0+0)/cnt,0), ((i0+1)/cnt,0), ((i0+1)/cnt,1),
            ((i0+0)/cnt,0), ((i0+1)/cnt,1), ((i0+0)/cnt,1),
        ]
    ]
    batch_3D_circle = batch_for_shader(shader_3D_circle, 'TRIS', {"pos": pts})

    # 3D triangle
    shader_3D_triangle, ubos_3D_triangle = create_shader('triangle_3D.glsl')
    batch_3D_triangle = batch_for_shader(shader_3D_triangle, 'TRIS', {'pos': [(1,0), (0,1), (0,0)]})

    # 3D triangle
    shader_2D_triangle, ubos_2D_triangle = create_shader('triangle_2D.glsl')
    batch_2D_triangle = batch_for_shader(shader_2D_triangle, 'TRIS', {'pos': [(1,0), (0,1), (0,0)]})

    Drawing.glCheckError(f'Compiled point, lineseg, circle shaders')


######################################################################################################
# The following classes mimic the immediate mode for (old-school way of) drawing geometry
#   glBegin(GL_TRIANGLES)
#   glColor3f(p)
#   glVertex3f(p)
#   glEnd()

class CC_DRAW:
    _point_size:float = 1
    _line_width:float = 1
    _border_width:float = 0
    _border_color:Color = Color((0, 0, 0, 0))
    _stipple_pattern:List[float] = [1,0]
    _stipple_offset:float = 0
    _stipple_color:Color = Color((0, 0, 0, 0))

    _default_color = Color((1, 1, 1, 1))
    _default_point_size = 1
    _default_line_width = 1
    _default_border_width = 0
    _default_border_color = Color((0, 0, 0, 0))
    _default_stipple_pattern = [1,0]
    _default_stipple_color = Color((0, 0, 0, 0))

    @classmethod
    def reset(cls):
        s = Drawing._instance.scale
        CC_DRAW._point_size = s(CC_DRAW._default_point_size)
        CC_DRAW._line_width = s(CC_DRAW._default_line_width)
        CC_DRAW._border_width = s(CC_DRAW._default_border_width)
        CC_DRAW._border_color = CC_DRAW._default_border_color
        CC_DRAW._stipple_offset = 0
        CC_DRAW._stipple_pattern = [s(v) for v in CC_DRAW._default_stipple_pattern]
        CC_DRAW._stipple_color = CC_DRAW._default_stipple_color
        cls.update()

    @classmethod
    def update(cls): pass

    @classmethod
    def point_size(cls, size):
        s = Drawing._instance.scale
        CC_DRAW._point_size = s(size)
        cls.update()

    @classmethod
    def line_width(cls, width):
        s = Drawing._instance.scale
        CC_DRAW._line_width = s(width)
        cls.update()

    @classmethod
    def border(cls, *, width=None, color=None):
        s = Drawing._instance.scale
        if width is not None:
            CC_DRAW._border_width = s(width)
        if color is not None:
            CC_DRAW._border_color = color
        cls.update()

    @classmethod
    def stipple(cls, *, pattern=None, offset=None, color=None):
        s = Drawing._instance.scale
        if pattern is not None:
            CC_DRAW._stipple_pattern = [s(v) for v in pattern]
        if offset is not None:
            CC_DRAW._stipple_offset = s(offset)
        if color is not None:
            CC_DRAW._stipple_color = color
        cls.update()

    @classmethod
    def end(cls):
        gpu.shader.unbind()

if not bpy.app.background:
    CC_DRAW.reset()


class CC_2D_POINTS(CC_DRAW):
    @classmethod
    def begin(cls):
        shader_2D_point.bind()
        ubos_2D_point.options.MVPMatrix = Drawing._instance.get_pixel_matrix()
        ubos_2D_point.options.screensize = (Drawing._instance.area.width, Drawing._instance.area.height, 0, 0)
        ubos_2D_point.options.color = cls._default_color
        cls.update()

    @classmethod
    def update(cls):
        ubos_2D_point.options.radius_border = (cls._point_size, cls._border_width, 0, 0)
        ubos_2D_point.options.colorBorder = cls._border_color

    @classmethod
    def color(cls, c:Color):
        ubos_2D_point.options.color = c

    @classmethod
    def vertex(cls, p:Point2D):
        if p:
            ubos_2D_point.options.center = (*p, 0, 1)
            ubos_2D_point.options.update_shader()
            batch_2D_point.draw(shader_2D_point)


class CC_2D_LINES(CC_DRAW):
    @classmethod
    def begin(cls):
        shader_2D_lineseg.bind()
        mvpmatrix = Drawing._instance.get_pixel_matrix()
        ubos_2D_lineseg.options.MVPMatrix = mvpmatrix
        ubos_2D_lineseg.options.screensize = (Drawing._instance.area.width, Drawing._instance.area.height, 0, 0)
        ubos_2D_lineseg.options.color0 = cls._default_color
        cls.stipple(offset=0)
        cls._c = 0
        cls._last_p = None

    @classmethod
    def update(cls):
        ubos_2D_lineseg.options.color1 = cls._stipple_color
        ubos_2D_lineseg.options.stipple_width = (cls._stipple_pattern[0], cls._stipple_pattern[1], cls._stipple_offset, cls._line_width)

    @classmethod
    def color(cls, c:Color):
        ubos_2D_lineseg.options.color0 = c

    @classmethod
    def vertex(cls, p:Point2D):
        if p: ubos_2D_lineseg.options.assign(f'pos{cls._c}', (*p, 0, 1))
        cls._c = (cls._c + 1) % 2
        if cls._c == 0 and cls._last_p and p:
            ubos_2D_lineseg.update_shader()
            batch_2D_lineseg.draw(shader_2D_lineseg)
        cls._last_p = p

class CC_2D_LINE_STRIP(CC_2D_LINES):
    @classmethod
    def begin(cls):
        super().begin()
        cls._last_p = None

    @classmethod
    def vertex(cls, p:Point2D):
        if cls._last_p is None:
            cls._last_p = p
        else:
            if cls._last_p and p:
                ubos_2D_lineseg.options.pos0 = (*cls._last_p, 0, 1)
                ubos_2D_lineseg.options.pos1 = (*p, 0, 1)
                ubos_2D_lineseg.update_shader()
                batch_2D_lineseg.draw(shader_2D_lineseg)
            cls._last_p = p

class CC_2D_LINE_LOOP(CC_2D_LINES):
    @classmethod
    def begin(cls):
        super().begin()
        cls._first_p = None
        cls._last_p = None

    @classmethod
    def vertex(cls, p:Point2D):
        if cls._first_p is None:
            cls._first_p = cls._last_p = p
        else:
            if cls._last_p and p:
                ubos_2D_lineseg.options.pos0 = (*cls._last_p, 0, 1)
                ubos_2D_lineseg.options.pos1 = (*p, 0, 1)
                ubos_2D_lineseg.update_shader()
                batch_2D_lineseg.draw(shader_2D_lineseg)
            cls._last_p = p

    @classmethod
    def end(cls):
        if cls._last_p and cls._first_p:
            ubos_2D_lineseg.options.pos0 = (*cls._last_p, 0, 1)
            ubos_2D_lineseg.options.pos1 = (*cls._first_p, 0, 1)
            ubos_2D_lineseg.update_shader()
            batch_2D_lineseg.draw(shader_2D_lineseg)
        super().end()


class CC_2D_TRIANGLES(CC_DRAW):
    @classmethod
    def begin(cls):
        shader_2D_triangle.bind()
        #shader_2D_triangle.uniform_float('screensize', (Drawing._instance.area.width, Drawing._instance.area.height))
        ubos_2D_triangle.options.MVPMatrix = Drawing._instance.get_pixel_matrix()
        cls._c = 0
        cls._last_color = None
        cls._last_p0 = None
        cls._last_p1 = None

    @classmethod
    def color(cls, c:Color):
        if c is None: return
        ubos_2D_triangle.options.assign(f'color{cls._c}', c)
        cls._last_color = c

    @classmethod
    def vertex(cls, p:Point2D):
        if p: ubos_2D_triangle.options.assign(f'pos{cls._c}', (*p, 0, 1))
        cls._c = (cls._c + 1) % 3
        if cls._c == 0 and p and cls._last_p0 and cls._last_p1:
            ubos_2D_triangle.update_shader()
            batch_2D_triangle.draw(shader_2D_triangle)
        cls.color(cls._last_color)
        cls._last_p1 = cls._last_p0
        cls._last_p0 = p

class CC_2D_TRIANGLE_FAN(CC_DRAW):
    @classmethod
    def begin(cls):
        shader_2D_triangle.bind()
        ubos_2D_triangle.options.MVPMatrix = Drawing._instance.get_pixel_matrix()
        cls._c = 0
        cls._last_color = None
        cls._first_p = None
        cls._last_p = None
        cls._is_first = True

    @classmethod
    def color(cls, c:Color):
        if c is None: return
        ubos_2D_triangle.options.assign(f'color{cls._c}', c)
        cls._last_color = c

    @classmethod
    def vertex(cls, p:Point2D):
        if p: ubos_2D_triangle.options.assign(f'pos{cls._c}', (*p, 0, 1))
        cls._c += 1
        if cls._c == 3:
            if p and cls._first_p and cls._last_p:
                ubos_2D_triangle.update_shader()
                batch_2D_triangle.draw(shader_2D_triangle)
            cls._c = 1
        cls.color(cls._last_color)
        if cls._is_first:
            cls._first_p = p
            cls._is_first = False
        else: cls._last_p = p

class CC_3D_TRIANGLES(CC_DRAW):
    @classmethod
    def begin(cls):
        shader_3D_triangle.bind()
        ubos_3D_triangle.options.MVPMatrix = Drawing._instance.get_view_matrix()
        cls._c = 0
        cls._last_color = None
        cls._last_p0 = None
        cls._last_p1 = None

    @classmethod
    def color(cls, c:Color):
        if c is None: return
        ubos_3D_triangle.options.assign(f'color{cls._c}', c)
        cls._last_color = c

    @classmethod
    def vertex(cls, p:Point):
        if p: ubos_3D_triangle.options.assign(f'pos{cls._c}', p)
        cls._c = (cls._c + 1) % 3
        if cls._c == 0 and p and cls._last_p0 and cls._last_p1:
            ubos_3D_triangle.update_shader()
            batch_3D_triangle.draw(shader_3D_triangle)
        cls.color(cls._last_color)
        cls._last_p1 = cls._last_p0
        cls._last_p0 = p


class DrawCallbacks:
    @staticmethod
    def on_draw(mode):
        def wrapper(fn):
            nonlocal mode
            assert mode in {'predraw', 'pre3d', 'post3d', 'post2d'}, f'DrawCallbacks: unexpected draw mode {mode} for {fn}'
            @wraps(fn)
            def wrapped(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    print(f'DrawCallbacks: caught exception in on_draw with {fn}')
                    debugger.print_exception()
                    print(e)
                    return
            setattr(wrapped, f'_on_{mode}', True)
            return wrapped
        return wrapper

    @staticmethod
    def on_predraw():
        return DrawCallbacks.on_draw('predraw')

    def __init__(self, obj):
        self.obj = obj
        self._fns = {
            'pre':    [ fn for (_, fn) in find_fns(obj, '_on_predraw') ],
            'pre3d':  [ fn for (_, fn) in find_fns(obj, '_on_pre3d'  ) ],
            'post3d': [ fn for (_, fn) in find_fns(obj, '_on_post3d' ) ],
            'post2d': [ fn for (_, fn) in find_fns(obj, '_on_post2d' ) ],
        }
        self.reset_pre()

    def reset_pre(self):
        self._called_pre = False

    def _call(self, n, *, call_predraw=True):
        if not self._called_pre:
            self._called_pre = True
            for fn in self._fns['pre']: fn(self.obj)
        for fn in self._fns[n]: fn(self.obj)

    def pre3d(self):  self._call('pre3d')
    def post3d(self): self._call('post3d')
    def post2d(self): self._call('post2d')


