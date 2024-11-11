'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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

import bpy
import bmesh
import gpu
from mathutils import Vector, Matrix
from gpu_extras.batch import batch_for_shader

import math
from typing import List

from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4, Color
from ...addon_common.common.maths import Point, Normal, Direction, Frame, Point2D
from ...addon_common.common.utils import iter_pairs



def create_shader(fn_glsl, *, segments=1, pos=None):
    path_glsl = get_path_from_addon_common('common', 'shaders', fn_glsl)
    txt = open(path_glsl, 'rt').read()
    vert_source, frag_source = gpustate.shader_parse_string(txt)
    if pos is None:
        pos = [
            p
            for i0 in range(segments)
            for p in [
                ((i0 + 0) / segments, 0), ((i0 + 1) / segments, 0), ((i0 + 1) / segments, 1),
                ((i0 + 0) / segments, 0), ((i0 + 1) / segments, 1), ((i0 + 0) / segments, 1),
            ]
        ]
    try:
        shad, ubos = gpustate.gpu_shader(f'drawing {fn_glsl}', vert_source, frag_source)
        batch = batch_for_shader(shad, 'TRIS', {'pos': pos})
        return shad, ubos, batch
    except Exception as e:
        print(f'ERROR WHILE COMPILING SHADER {fn_glsl}')
        print(e)
        assert False

shader_2D_point,    ubos_2D_point,    batch_2D_point    = create_shader('point_2D.glsl')
shader_2D_lineseg,  ubos_2D_lineseg,  batch_2D_lineseg  = create_shader('lineseg_2D.glsl')
shader_2D_circle,   ubos_2D_circle,   batch_2D_circle   = create_shader('circle_2D.glsl', segments=64)
shader_3D_circle,   ubos_3D_circle,   batch_3D_circle   = create_shader('circle_3D.glsl', segments=64)
shader_2D_triangle, ubos_2D_triangle, batch_2D_triangle = create_shader('triangle_2D.glsl', pos=[(1,0), (0,1), (0,0)])


from contextlib import contextmanager

class Drawing:
    @staticmethod
    def scale(s):
        return s * (bpy.context.preferences.system.ui_scale) if s is not None else None

    @staticmethod
    def get_pixel_matrix(context):
        rgn = context.region
        # r3d = bpy.context.region_data
        w,h = rgn.width,rgn.height
        mx, my, mw, mh = -1, -1, 2 / w, 2 / h
        return Matrix([
            [ mw,  0,  0, mx],
            [  0, mh,  0, my],
            [  0,  0,  1,  0],
            [  0,  0,  0,  1]
        ])

    @staticmethod
    def get_view_matrix(context):
        r3d = context.space_data.region_3d
        return r3d.perspective_matrix if r3d else None

    @contextmanager
    @staticmethod
    def draw(context, draw_type:"CC_DRAW"):
        assert not hasattr(Drawing, '_drawing'), 'Cannot nest Drawing.draw calls'
        Drawing._draw = draw_type
        try:
            gpu.state.blend_set('ALPHA')
            draw_type.begin(context)
            yield draw_type
            draw_type.end()
        except Exception as e:
            print(f'Drawing.draw({draw_type}): Caught unexpected exception')
            print(e)
        del Drawing._draw

    # draw circle in screen space
    def draw2D_circle(context, center:Point2D, radius:float, color0:Color, *, color1=None, width=1, stipple=None, offset=0):
        if color1 is None: color1 = (color0[0],color0[1],color0[2],0)
        area = context.area
        radius = Drawing.scale(radius)
        width = Drawing.scale(width)
        stipple = [Drawing.scale(v) for v in stipple] if stipple else [1,0]
        offset = Drawing.scale(offset)
        shader_2D_circle.bind()
        ubos_2D_circle.options.MVPMatrix = Drawing.get_pixel_matrix(context)
        ubos_2D_circle.options.screensize = (area.width, area.height, 0.0, 0.0)
        ubos_2D_circle.options.center = (center.x, center.y, 0.0, 0.0)
        ubos_2D_circle.options.color0 = color0
        ubos_2D_circle.options.color1 = color1
        ubos_2D_circle.options.radius_width = (radius, width, 0.0, 0.0)
        ubos_2D_circle.options.stipple_data = (*stipple, offset, 0.0)
        ubos_2D_circle.update_shader()
        batch_2D_circle.draw(shader_2D_circle)
        gpu.shader.unbind()

    @staticmethod
    def draw3D_circle(context, center:Point, radius:float, color:Color, *, width=1, n:Normal=None, x:Direction=None, y:Direction=None, depth_near=0, depth_far=1):
        assert n is not None or x is not None or y is not None, 'Must specify at least one of n,x,y'
        area = context.area
        f = Frame(o=center, x=x, y=y, z=n)
        radius = Drawing.scale(radius)
        width = Drawing.scale(width)
        shader_3D_circle.bind()
        ubos_3D_circle.options.MVPMatrix = Drawing.get_view_matrix(context)
        ubos_3D_circle.options.screensize = (area.width, area.height, 0.0, 0.0)
        ubos_3D_circle.options.center    = f.o
        ubos_3D_circle.options.color     = color
        ubos_3D_circle.options.plane_x   = f.x
        ubos_3D_circle.options.plane_y   = f.y
        ubos_3D_circle.options.settings  = (radius, width, depth_near, depth_far)
        ubos_3D_circle.update_shader()
        batch_3D_circle.draw(shader_3D_circle)
        gpu.shader.unbind()

    def draw2D_linestrip(context, points, color0, *, color1=None, width=1, stipple=None, offset=0):
        gpu.state.blend_set('ALPHA')
        if color1 is None: color1 = (*color0[:3], 0)
        width = Drawing.scale(width)
        stipple = [Drawing.scale(v) for v in stipple] if stipple else [1.0, 0.0]
        offset = Drawing.scale(offset)
        shader_2D_lineseg.bind()
        ubos_2D_lineseg.options.MVPMatrix = Drawing.get_pixel_matrix(context)
        ubos_2D_lineseg.options.screensize = (context.area.width, context.area.height)
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

    # def draw2D_point(context, pt, color, *, radius=1, border=0, borderColor=None):
    #     gpu.state.blend_set('ALPHA')
    #     radius = Drawing.scale(radius)
    #     border = Drawing.scale(border)
    #     if borderColor is None: borderColor = (*color[:3], 0)
    #     shader_2D_point.bind()
    #     ubos_2D_point.options.screensize = (context.area.width, context.area.height, 0, 0)
    #     ubos_2D_point.options.MVPMatrix = Drawing.get_pixel_matrix()
    #     ubos_2D_point.options.radius_border = (radius, border, 0, 0)
    #     ubos_2D_point.options.color = color
    #     ubos_2D_point.options.colorBorder = borderColor
    #     ubos_2D_point.options.center = (*pt, 0, 1)
    #     ubos_2D_point.update_shader()
    #     batch_2D_point.draw(shader_2D_point)
    #     gpu.shader.unbind()

    # def draw2D_points(context, pts, color, *, radius=1, border=0, borderColor=None):
    #     gpu.state.blend_set('ALPHA')
    #     radius = Drawing.scale(radius)
    #     border = Drawing.scale(border)
    #     if borderColor is None: borderColor = (*color[:3], 0)
    #     shader_2D_point.bind()
    #     ubos_2D_point.options.screensize = (context.area.width, context.area.height, 0, 0)
    #     ubos_2D_point.options.MVPMatrix = Drawing.get_pixel_matrix()
    #     ubos_2D_point.options.radius_border = (radius, border, 0, 0)
    #     ubos_2D_point.options.color = color
    #     ubos_2D_point.options.colorBorder = borderColor
    #     for pt in pts:
    #         ubos_2D_point.options.center = (*pt, 0, 1)
    #         ubos_2D_point.update_shader()
    #         batch_2D_point.draw(shader_2D_point)
    #     gpu.shader.unbind()


# ######################################################################################################
# # The following classes mimic the immediate mode for (old-school way of) drawing geometry
# #   glBegin(GL_TRIANGLES)
# #   glColor3f(p)
# #   glVertex3f(p)
# #   glEnd()

class CC_DRAW:
    _point_size:float = 1
    _line_width:float = 1
    _border_width:float = 0
    _border_color:Color4 = Color4((0, 0, 0, 0))
    _stipple_pattern:List[float] = [1,0]
    _stipple_offset:float = 0
    _stipple_color:Color4 = Color4((0, 0, 0, 0))

    _default_color = Color4((1, 1, 1, 1))
    _default_point_size = 1
    _default_line_width = 1
    _default_border_width = 0
    _default_border_color = Color4((0, 0, 0, 0))
    _default_stipple_pattern = [1,0]
    _default_stipple_color = Color4((0, 0, 0, 0))

    @classmethod
    def reset(cls):
        scale = Drawing.scale
        CC_DRAW._point_size      = scale(CC_DRAW._default_point_size)
        CC_DRAW._line_width      = scale(CC_DRAW._default_line_width)
        CC_DRAW._border_width    = scale(CC_DRAW._default_border_width)
        CC_DRAW._border_color    = CC_DRAW._default_border_color
        CC_DRAW._stipple_offset  = 0
        CC_DRAW._stipple_pattern = [scale(v) for v in CC_DRAW._default_stipple_pattern]
        CC_DRAW._stipple_color   = CC_DRAW._default_stipple_color
        cls.update()

    @classmethod
    def update(cls): pass

    @classmethod
    def point_size(cls, size):
        CC_DRAW._point_size = Drawing.scale(size)
        cls.update()

    @classmethod
    def line_width(cls, width):
        CC_DRAW._line_width = Drawing.scale(width)
        cls.update()

    @classmethod
    def border(cls, *, width=None, color=None):
        if width is not None: CC_DRAW._border_width = Drawing.scale(width)
        if color is not None: CC_DRAW._border_color = color
        cls.update()

    @classmethod
    def stipple(cls, *, pattern=None, offset=None, color=None):
        if pattern is not None: CC_DRAW._stipple_pattern = [Drawing.scale(v) for v in pattern]
        if offset  is not None: CC_DRAW._stipple_offset  = Drawing.scale(offset)
        if color   is not None: CC_DRAW._stipple_color   = color
        cls.update()

    @classmethod
    def end(cls):
        gpu.shader.unbind()
        cls.reset()

if not bpy.app.background:
    CC_DRAW.reset()


class CC_2D_POINTS(CC_DRAW):
    @classmethod
    def begin(cls, context):
        shader_2D_point.bind()
        ubos_2D_point.options.MVPMatrix = Drawing.get_pixel_matrix(context)
        ubos_2D_point.options.screensize = (context.area.width, context.area.height, 0, 0)
        ubos_2D_point.options.color = cls._default_color
        cls.update()

    @classmethod
    def update(cls):
        ubos_2D_point.options.radius_border = (cls._point_size, cls._border_width, 0, 0)
        ubos_2D_point.options.colorBorder = cls._border_color

    @classmethod
    def color(cls, c:Color4):
        ubos_2D_point.options.color = c

    @classmethod
    def vertex(cls, p:Vector):
        if p:
            ubos_2D_point.options.center = (*p, 0, 1)
            ubos_2D_point.options.update_shader()
            batch_2D_point.draw(shader_2D_point)


class CC_2D_LINES(CC_DRAW):
    @classmethod
    def begin(cls, context):
        shader_2D_lineseg.bind()
        mvpmatrix = Drawing.get_pixel_matrix(context)
        ubos_2D_lineseg.options.MVPMatrix = mvpmatrix
        ubos_2D_lineseg.options.screensize = (context.area.width, context.area.height, 0, 0)
        ubos_2D_lineseg.options.color0 = cls._default_color
        cls.stipple(offset=0)
        cls._c = 0
        cls._last_p = None

    @classmethod
    def update(cls):
        ubos_2D_lineseg.options.color1 = cls._stipple_color
        ubos_2D_lineseg.options.stipple_width = (cls._stipple_pattern[0], cls._stipple_pattern[1], cls._stipple_offset, cls._line_width)

    @classmethod
    def color(cls, c:Color4):
        ubos_2D_lineseg.options.color0 = c

    @classmethod
    def vertex(cls, p:Vector):
        if p: ubos_2D_lineseg.options.assign(f'pos{cls._c}', (*p, 0, 1))
        cls._c = (cls._c + 1) % 2
        if cls._c == 0 and cls._last_p and p:
            ubos_2D_lineseg.update_shader()
            batch_2D_lineseg.draw(shader_2D_lineseg)
        cls._last_p = p
        return cls

    @classmethod
    def vertices(cls, ps:List[Vector]):
        for p in ps:
            cls.vertex(p)

class CC_2D_LINE_STRIP(CC_2D_LINES):
    @classmethod
    def begin(cls, context):
        super().begin()
        cls._last_p = None

    @classmethod
    def vertex(cls, p:Vector):
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
    def begin(cls, context):
        super().begin()
        cls._first_p = None
        cls._last_p = None

    @classmethod
    def vertex(cls, p:Vector):
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
    def begin(cls, context):
        shader_2D_triangle.bind()
        #shader_2D_triangle.uniform_float('screensize', (context.area.width, context.area.height))
        ubos_2D_triangle.options.MVPMatrix = Drawing.get_pixel_matrix(context)
        cls._c = 0
        cls._last_color = None
        cls._last_p0 = None
        cls._last_p1 = None

    @classmethod
    def color(cls, c:Color4):
        if c is None: return
        ubos_2D_triangle.options.assign(f'color{cls._c}', c)
        cls._last_color = c

    @classmethod
    def vertex(cls, p:Vector):
        if p: ubos_2D_triangle.options.assign(f'pos{cls._c}', (*p, 0, 1))
        cls._c = (cls._c + 1) % 3
        if cls._c == 0 and p and cls._last_p0 and cls._last_p1:
            ubos_2D_triangle.update_shader()
            batch_2D_triangle.draw(shader_2D_triangle)
        cls.color(cls._last_color)
        cls._last_p1 = cls._last_p0
        cls._last_p0 = p
        return cls

class CC_2D_TRIANGLE_FAN(CC_DRAW):
    @classmethod
    def begin(cls, context):
        shader_2D_triangle.bind()
        ubos_2D_triangle.options.MVPMatrix = Drawing.get_pixel_matrix(context)
        cls._c = 0
        cls._last_color = None
        cls._first_p = None
        cls._last_p = None
        cls._is_first = True

    @classmethod
    def color(cls, c:Color4):
        if c is None: return
        ubos_2D_triangle.options.assign(f'color{cls._c}', c)
        cls._last_color = c

    @classmethod
    def vertex(cls, p:Vector):
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
    def begin(cls, context):
        shader_3D_triangle.bind()
        ubos_3D_triangle.options.MVPMatrix = Drawing.get_view_matrix()
        cls._c = 0
        cls._last_color = None
        cls._last_p0 = None
        cls._last_p1 = None

    @classmethod
    def color(cls, c:Color4):
        if c is None: return
        ubos_3D_triangle.options.assign(f'color{cls._c}', c)
        cls._last_color = c

    @classmethod
    def vertex(cls, p:Vector):
        if p: ubos_3D_triangle.options.assign(f'pos{cls._c}', p)
        cls._c = (cls._c + 1) % 3
        if cls._c == 0 and p and cls._last_p0 and cls._last_p1:
            ubos_3D_triangle.update_shader()
            batch_3D_triangle.draw(shader_3D_triangle)
        cls.color(cls._last_color)
        cls._last_p1 = cls._last_p0
        cls._last_p0 = p

