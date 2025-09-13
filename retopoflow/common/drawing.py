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
from typing import List, Tuple

from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4, Color
from ...addon_common.common.fontmanager import FontManager as fm
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
shader_smooth_circle_2D, ubos_smooth_circle_2D, batch_smooth_circle_2D = create_shader('smooth_circle_2D.glsl', pos=[(0,0), (1,0), (1,1), (0,0), (1,1), (0,1)])
shader_2D_triangle, ubos_2D_triangle, batch_2D_triangle = create_shader('triangle_2D.glsl', pos=[(1,0), (0,1), (0,0)])
shader_radial_gradient_2D, ubos_radial_gradient_2D, batch_radial_gradient_2D = create_shader('radial_gradient_2D.glsl', pos=[(0,0), (1,0), (1,1), (0,0), (1,1), (0,1)])


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
    @staticmethod
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
        screensize = (area.width, area.height, 0.0, 0.0)
        settings = (radius, width, depth_near, depth_far)
        f = Frame(o=center, x=x, y=y, z=n)
        radius = Drawing.scale(radius)
        width = Drawing.scale(width)

        shader_3D_circle.bind()
        ubos_3D_circle.options.MVPMatrix = Drawing.get_view_matrix(context)
        ubos_3D_circle.options.screensize = screensize
        ubos_3D_circle.options.center    = f.o
        ubos_3D_circle.options.color     = color
        ubos_3D_circle.options.plane_x   = f.x
        ubos_3D_circle.options.plane_y   = f.y
        ubos_3D_circle.options.settings  = settings
        ubos_3D_circle.update_shader()
        batch_3D_circle.draw(shader_3D_circle)
        gpu.shader.unbind()

    @staticmethod
    def draw2D_smooth_circle(context, center:Point2D | Vector | Tuple[float, float], radius:float, color:Color, *, width=0, smooth_threshold=1.5):
        '''
        Draw an anti-aliased 2D circle using a quad-based approach for efficient rendering
        
        Parameters:
            context: Blender context
            center: Center position in screen coordinates
            radius: Circle radius in pixels
            color: Circle color
            width: Line width in pixels (0 for filled circle)
            smooth_threshold: Smoothing factor for anti-aliasing (in pixels)
        '''
        area = context.area
        radius = Drawing.scale(radius)
        width = Drawing.scale(width)
        smooth_threshold = Drawing.scale(smooth_threshold)
        settings = (radius, width, smooth_threshold, 0.0)
        
        shader_smooth_circle_2D.bind()
        ubos_smooth_circle_2D.options.MVPMatrix = Drawing.get_pixel_matrix(context)
        ubos_smooth_circle_2D.options.screensize = (area.width, area.height, 0.0, 0.0)
        ubos_smooth_circle_2D.options.center = (*center, 0.0, 0.0)
        ubos_smooth_circle_2D.options.color = color
        ubos_smooth_circle_2D.options.settings = settings
        ubos_smooth_circle_2D.update_shader()
        batch_smooth_circle_2D.draw(shader_smooth_circle_2D)
        gpu.shader.unbind()

    @staticmethod
    def draw2D_radial_gradient(context, center:Point2D, radius:float, color_center:Color, color_edge:Color, *, t=1.0, easing_type=0):
        '''
        Draw a radial gradient from center to edge with easing functions
        
        Parameters:
            context: Blender context
            center: Center position in screen coordinates
            radius: Circle radius in pixels
            color_center: Color at the center of the gradient
            color_edge: Color at the edge of the gradient
            t: Controls gradient edge position (1.0 = at radius, <1.0 = softer, >1.0 = sharper)
            easing_type: Type of easing function (0: linear, 1: quadratic, 2: cubic, 3: sine)
        '''
        area = context.area
        radius = Drawing.scale(radius)
        
        shader_radial_gradient_2D.bind()
        ubos_radial_gradient_2D.options.MVPMatrix = Drawing.get_pixel_matrix(context)
        ubos_radial_gradient_2D.options.screensize = (area.width, area.height, 0.0, 0.0)
        ubos_radial_gradient_2D.options.center = (center.x, center.y, 0.0, 0.0)
        ubos_radial_gradient_2D.options.color_center = color_center
        ubos_radial_gradient_2D.options.color_edge = color_edge
        ubos_radial_gradient_2D.options.radius_t_easing = (radius, t, float(easing_type), 0.0)
        ubos_radial_gradient_2D.update_shader()
        batch_radial_gradient_2D.draw(shader_radial_gradient_2D)
        gpu.shader.unbind()

    @staticmethod
    def draw_circle_3d(position, normal, color, radius: float, thickness: float, *, scale: float=1.0, segments=None, viewport_size=None):
        """
        Draw a circle oriented by the normal vector.

        :arg position: 3D position where the circle will be drawn.
        :type position: Sequence[float]
        :arg normal: Normal vector to orient the circle.
        :type normal: Sequence[float] | Vector
        :arg color: Color of the circle (RGBA).
        To use transparency blend must be set to ``ALPHA``, see: :func:`gpu.state.blend_set`.
        :type color: Sequence[float]
        :arg radius: Radius of the circle.
        :type radius: float
        :arg segments: How many segments will be used to draw the circle.
            Higher values give better results but the drawing will take longer.
            If None or not specified, an automatic value will be calculated.
        :type segments: int | None
        """
        from math import sin, cos, pi
        import gpu
        from gpu.types import (
            GPUBatch,
            GPUVertBuf,
            GPUVertFormat,
        )

        if segments is None:
            if viewport_size is not None:
                # Heuristic for calculating segments based on viewport size (or region size) and radius.
                
                # --- Configuration ---
                base_target_segments = 32 # Target segments for ref_radius at ref_vp_dim
                ref_radius = 0.1          # Reference world-space radius
                ref_vp_dim = 1000.0       # Reference viewport dimension (min of width/height)
                min_segments = 8
                max_segments = 256
                # Scaling factor limits to prevent extreme segment counts
                radius_scale_min = 0.25
                radius_scale_max = 4.0 
                vp_scale_min = 0.5     
                vp_scale_max = 2.0     

                # --- Calculate Radius Scale ---
                # Ensure radius is positive for scaling calculation
                safe_radius = max(radius, 1e-6)
                radius_scale = max(radius_scale_min, min(radius_scale_max, safe_radius / ref_radius))

                # --- Calculate Viewport Scale ---
                min_vp_dim = min(viewport_size[0], viewport_size[1])
                vp_scale = max(vp_scale_min, min(vp_scale_max, min_vp_dim / ref_vp_dim))

                # --- Calculate Final Segments ---
                # Multiply base segments by both scale factors
                scaled_segments = int(base_target_segments * radius_scale * vp_scale)

                # --- Final Clamping ---
                segments = max(min_segments, min(max_segments, scaled_segments))

            else:
                # Logic partially based on Blender's `draw_circle_2d` preset function.
                max_pixel_error = 0.25
                # Use world radius, ensure > 0...
                calc_radius = max(radius, 1e-6)
                # Clamp input
                acos_input = max(-1.0, min(1.0, 1.0 - max_pixel_error / calc_radius))
                angle_per_segment = math.acos(acos_input)
                if angle_per_segment > 1e-7:
                    # Calculate for full circle
                    segments = int(math.ceil((2 * math.pi) / angle_per_segment))
                else:
                    segments = 256
                # Apply limits
                segments = max(8, min(256, segments))

        if segments <= 0:
            raise ValueError("Amount of segments must be greater than 0.")

        # Calc rotation matrix to align the circle with the normal.
        up = Vector((0.0, 0.0, 1.0))
        normal_vec = Vector(normal).normalized()
        if normal_vec.dot(up) > 0.9999: # Normal is already Z up
            rotation_matrix = Matrix.Identity(4)
        elif normal_vec.dot(up) < -0.9999: # Normal is Z down
            rotation_matrix = Matrix.Rotation(pi, 4, 'X')
        else:
            axis = up.cross(normal_vec)
            angle = up.angle(normal_vec)
            rotation_matrix = Matrix.Rotation(angle, 4, axis)

        with gpu.matrix.push_pop():
            # Apply translation, rotation, and scale
            gpu.matrix.translate(position)
            gpu.matrix.multiply_matrix(rotation_matrix)
            gpu.matrix.scale_uniform(radius * scale)

            # vertices for the circle on the normal plane.
            mul = (1.0 / (segments - 1)) * (pi * 2)
            verts = [(sin(i * mul), cos(i * mul), 0.0) for i in range(segments)] # Add Z coordinate

            fmt = GPUVertFormat()
            pos_id = fmt.attr_add(id="pos", comp_type='F32', len=3, fetch_mode='FLOAT') # Change len to 3
            vbo = GPUVertBuf(len=len(verts), format=fmt)
            vbo.attr_fill(id=pos_id, data=verts)

            batch = GPUBatch(type='LINE_STRIP', buf=vbo)
            shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR' if viewport_size is not None else 'UNIFORM_COLOR')
            batch.program_set(shader)
            shader.uniform_float("color", color)
            if viewport_size:
                shader.uniform_float("viewportSize", viewport_size)
                shader.uniform_float("lineWidth", thickness)

            if viewport_size is None: gpustate.line_width(thickness)
            batch.draw()
            if viewport_size is None: gpustate.line_width(1.0)

    @staticmethod
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
            ubos_2D_lineseg.options.stipple_width = (stipple[0], stipple[1], offset, width)  # offset changes
            ubos_2D_lineseg.update_shader()
            batch_2D_lineseg.draw(shader_2D_lineseg)
            offset += (p1 - p0).length
        gpu.shader.unbind()

    @staticmethod
    def draw2D_lines(context, points, color0:Color, *, color1=None, width=1, stipple=None, offset=0):
        gpu.state.blend_set('ALPHA')
        if color1 is None: color1 = (*color0[:3], 0)
        width = Drawing.scale(width)
        stipple = [Drawing.scale(v) for v in stipple] if stipple else [1.0, 0.0]
        offset = Drawing.scale(offset)
        shader_2D_lineseg.bind()
        ubos_2D_lineseg.options.MVPMatrix = Drawing.get_pixel_matrix(context)
        ubos_2D_lineseg.options.screensize = (context.area.width, context.area.height, 0, 0)
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

    @staticmethod
    def draw2D_points(context, points, color, *, radius=1, border=0, borderColor=None):
        gpu.state.blend_set('ALPHA')
        radius = Drawing.scale(radius)
        border = Drawing.scale(border)
        if borderColor is None: borderColor = (*color[:3], 0)
        shader_2D_point.bind()
        ubos_2D_point.options.MVPMatrix = Drawing.get_pixel_matrix(context)
        ubos_2D_point.options.screensize = (context.area.width, context.area.height)
        ubos_2D_point.options.radius_border = (radius, border, 0, 0)
        ubos_2D_point.options.color = color
        ubos_2D_point.options.colorBorder = borderColor
        for pt in points:
            if not pt: continue
            ubos_2D_point.options.center = (*pt, 0, 1)
            ubos_2D_point.update_shader()
            batch_2D_point.draw(shader_2D_point)
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

    fontsize = None
    last_font_key = None
    line_cache = {}
    size_cache = {}

    @staticmethod
    def set_font_size(fontsize, fontid=None, force=False):
        if fontid is None: fontid = fm._last_fontid
        else: fontid = fm.load(fontid)
        fontsize_prev = Drawing.fontsize
        fontsize, fontsize_scaled = int(fontsize), int(Drawing.scale(int(fontsize)))
        cache_key = (fontid, fontsize_scaled)
        if Drawing.last_font_key == cache_key and not force: return fontsize_prev
        fm.size(fontsize_scaled, fontid=fontid)
        if cache_key not in Drawing.line_cache:
            # cache away useful details about font (line height, line base)
            # dprint('Caching new scaled font size:', cache_key)
            all_chars = ''.join([
                'abcdefghijklmnopqrstuvwxyz',
                'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                '0123456789',
                '!@#$%%^&*()`~[}{]/?=+\\|-_\'",<.>',
                'ΑαΒβΓγΔδΕεΖζΗηΘθΙιΚκΛλΜμΝνΞξΟοΠπΡρΣσςΤτΥυΦφΧχΨψΩω',
            ])
            all_caps = all_chars.upper()
            Drawing.line_cache[cache_key] = {
                'line height': math.ceil(fm.dimensions(all_chars, fontid=fontid)[1] + Drawing.scale(4)),
                'line base': math.ceil(fm.dimensions(all_caps, fontid=fontid)[1]),
            }
        info = Drawing.line_cache[cache_key]
        Drawing.line_height = info['line height']
        Drawing.line_base = info['line base']
        Drawing.fontid = fontid
        Drawing.fontsize = fontsize
        Drawing.fontsize_scaled = fontsize_scaled
        Drawing.last_font_key = cache_key

        return fontsize_prev

    @staticmethod
    def get_text_size_info(text, item, fontsize=None, fontid=None):
        if fontsize or fontid: size_prev = Drawing.set_font_size(fontsize, fontid=fontid)

        if text is None: text, lines = '', []
        elif type(text) is list: text, lines = '\n'.join(text), text
        else: text, lines = text, text.splitlines()

        fontid = fm.load(fontid)
        key = (text, Drawing.fontsize_scaled, fontid)
        # key = (text, Drawing.fontsize_scaled, Drawing.font_id)
        if key not in Drawing.size_cache:
            d = {}
            if not text:
                d['width'] = 0
                d['height'] = 0
                d['line height'] = Drawing.line_height
            else:
                get_width = lambda t: math.ceil(fm.dimensions(t, fontid=fontid)[0])
                get_height = lambda t: math.ceil(fm.dimensions(t, fontid=fontid)[1])
                d['width'] = max(get_width(l) for l in lines)
                d['height'] = get_height(text)
                d['line height'] = Drawing.line_height * len(lines)
            Drawing.size_cache[key] = d
            if False:
                print('')
                print('--------------------------------------')
                print('> computed new size')
                print('>   key: %s' % str(key))
                print('>   size: %s' % str(d))
                print('--------------------------------------')
                print('')
        if fontsize: Drawing.set_font_size(size_prev, fontid=fontid)
        return Drawing.size_cache[key][item]

    @staticmethod
    def get_text_width(text, fontsize=None, fontid=None):
        return Drawing.get_text_size_info(text, 'width', fontsize=fontsize, fontid=fontid)
    @staticmethod
    def get_text_height(text, fontsize=None, fontid=None):
        return Drawing.get_text_size_info(text, 'height', fontsize=fontsize, fontid=fontid)
    @staticmethod
    def get_line_height(text=None, fontsize=None, fontid=None):
        return Drawing.get_text_size_info(text, 'line height', fontsize=fontsize, fontid=fontid)

    @staticmethod
    def text_color_set(color, fontid):
        if color is not None: fm.color(color, fontid=fontid)

    @staticmethod
    def text_draw2D(text, pos, *, color=None, dropshadow=None, fontsize=None, fontid=None, lineheight=True):
        if fontsize: size_prev = Drawing.set_font_size(fontsize, fontid=fontid)

        lines = str(text).splitlines()
        l,t = round(pos[0]),round(pos[1])
        lh,lb = Drawing.line_height,Drawing.line_base

        if dropshadow:
            Drawing.text_draw2D(text, (l+1,t-1), color=dropshadow, fontsize=fontsize, fontid=fontid, lineheight=lineheight)

        gpustate.blend('ALPHA')
        Drawing.text_color_set(color, fontid)
        for line in lines:
            fm.draw(line, xyz=(l, t - lb, 0), fontid=fontid)
            t -= lh if lineheight else Drawing.get_text_height(line)

        if fontsize: Drawing.set_font_size(size_prev, fontid=fontid)

    @staticmethod
    def text_draw2D_simple(text, pos:Point2D):
        l,t = round(pos[0]),round(pos[1])
        lb = Drawing.line_base
        fm.draw_simple(text, xyz=(l, t - lb, 0))

Drawing.set_font_size(12)

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

