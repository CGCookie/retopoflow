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

import blf
import bmesh
import bpy
import gpu
from bmesh.types import BMVert, BMEdge, BMFace
from gpu_extras.batch import batch_for_shader
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector, Matrix

import math
from typing import List
from enum import Enum

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, get_select_layers
from ..common.operator import invoke_operator, execute_operator, RFOperator
from ..common.raycast import raycast_mouse_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4
from ...addon_common.common.utils import iter_pairs


visualizing = False
reseter = Reseter()
translate_options = {
    'snap': True,
    'use_snap_project': True,
    'use_snap_self': False, # True,
    'use_snap_edit': False, # True,
    'use_snap_nonedit': True,
    'use_snap_selectable': True,
    'snap_elements': {'FACE_PROJECT', 'FACE_NEAREST'}, #, 'VERTEX'},
    'snap_target': 'CLOSEST',
    # 'release_confirm': True,
}

class PP_Action(Enum):
    NONE = -1
    VERT = 0
    VERT_EDGE = 1
    EDGE_TRIANGLE = 2








###############################################################################################################
###############################################################################################################
###############################################################################################################





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
shader_2D_circle,   ubos_2D_circle,   batch_2D_circle   = create_shader('circle_2D.glsl', segments=100)
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

    # def draw2D_linestrip(context, points, color0, *, color1=None, width=1, stipple=None, offset=0):
    #     gpu.state.blend_set('ALPHA')
    #     if color1 is None: color1 = (*color0[:3], 0)
    #     width = Drawing.scale(width)
    #     stipple = [Drawing.scale(v) for v in stipple] if stipple else [1.0, 0.0]
    #     offset = Drawing.scale(offset)
    #     shader_2D_lineseg.bind()
    #     ubos_2D_lineseg.options.MVPMatrix = Drawing.get_pixel_matrix()
    #     ubos_2D_lineseg.options.screensize = (context.area.width, context.area.height)
    #     ubos_2D_lineseg.options.color0 = color0
    #     ubos_2D_lineseg.options.color1 = color1
    #     for p0,p1 in iter_pairs(points, False):
    #         ubos_2D_lineseg.options.pos0 = (*p0, 0, 1)
    #         ubos_2D_lineseg.options.pos1 = (*p1, 0, 1)
    #         ubos_2D_lineseg.options.stipple_width = (stipple[0], stipple[1], offset, width)
    #         ubos_2D_lineseg.update_shader()
    #         batch_2D_lineseg.draw(shader_2D_lineseg)
    #         offset += (p1 - p0).length
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




###############################################################################################################
###############################################################################################################
###############################################################################################################



class PP_Logic:
    def __init__(self, context, event):
        self.matrix_world = context.edit_object.matrix_world
        self.bm, self.em = get_bmesh_emesh(context)
        self.layer_sel_vert, self.layer_sel_edge, self.layer_sel_face = get_select_layers(self.bm)
        self.update_selection = False
        self.get_selection = True
        self.mouse = None
        self.update(context, event)

    def update(self, context, event):
        # update previsualization and commit data structures with mouse position
        # ex: if triangle is selected, determine which edge to split to make quad
        # print('UPDATE')

        if self.update_selection:
            for bmv in self.bm.verts:
                bmv.select_set(bmv[self.layer_sel_vert] == 1)
                bmv[self.layer_sel_vert] = 0
            for bme in self.bm.edges:
                if bme[self.layer_sel_edge] == 0: continue
                for bmv in bme.verts:
                    bmv.select_set(True)
                bme[self.layer_sel_edge] = 0
            for bmf in self.bm.faces:
                if bmf[self.layer_sel_face] == 0: continue
                for bmv in bmf.verts:
                    bmv.select_set(True)
                bmf[self.layer_sel_face] = 0
            bmops.flush_selection(self.bm, self.em)
            self.get_selection = True
            self.update_selection = False

        if self.get_selection:
            self.selected = bmops.get_all_selected(self.bm)

        self.mouse = (event.mouse_region_x, event.mouse_region_y)

        # update commit data structure with mouse position
        self.state = PP_Action.NONE
        self.hit = raycast_mouse_valid_sources(context, event)
        if not self.hit:
            # Cursors.restore()
            return
        # Cursors.set('NONE')

        # TODO: update previsualizations

        if len(self.selected[BMVert]) == 0:
            self.state = PP_Action.VERT

        elif len(self.selected[BMVert]) == 1:
            self.state = PP_Action.VERT_EDGE
            self.bmv = next(iter(self.selected[BMVert]), None)

        elif len(self.selected[BMVert]) == 2 and len(self.selected[BMEdge]) == 1:
            self.state = PP_Action.EDGE_TRIANGLE
            self.bme = next(iter(self.selected[BMEdge]), None)

    def draw(self, context):
        # draw previsualization
        if not self.mouse: return
        if not self.hit: return

        match self.state:
            case PP_Action.VERT:
                pt = location_3d_to_region_2d(context.region, context.region_data, self.hit)
                if not pt: return
                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(8)
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.vertex(pt)

            case PP_Action.VERT_EDGE:
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ self.bmv.co)
                pt = location_3d_to_region_2d(context.region, context.region_data, self.hit)
                if not (p0 and pt): return
                d = (pt - p0).normalized() * Drawing.scale(8)
                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(8)
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.vertex(pt)

                    draw.border(width=2, color=Color4((40/255, 255/255, 40/255, 0.5)))
                    draw.color(Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.vertex(p0)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.vertex(p0 + d).vertex(pt - d)

            case PP_Action.EDGE_TRIANGLE:
                bmv0, bmv1 = self.bme.verts
                p0 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv0.co)
                p1 = location_3d_to_region_2d(context.region, context.region_data, self.matrix_world @ bmv1.co)
                pt = location_3d_to_region_2d(context.region, context.region_data, self.hit)
                if not (p0 and p1 and pt): return
                d0t = (pt - p0).normalized() * Drawing.scale(8)
                d1t = (pt - p1).normalized() * Drawing.scale(8)
                d01 = (p1 - p0).normalized() * Drawing.scale(8)
                with Drawing.draw(context, CC_2D_POINTS) as draw:
                    draw.point_size(8)
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.vertex(pt)

                    draw.border(width=2, color=Color4((40/255, 255/255, 40/255, 0.5)))
                    draw.color(Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.vertex(p0)
                    draw.vertex(p1)

                with Drawing.draw(context, CC_2D_LINES) as draw:
                    draw.color(Color4((40/255, 255/255, 40/255, 1.0)))
                    draw.line_width(2)
                    draw.stipple(pattern=[5,5], offset=0, color=Color4((40/255, 255/255, 40/255, 0.0)))
                    draw.vertex(p0 + d0t).vertex(pt - d0t)
                    draw.vertex(p1 + d1t).vertex(pt - d1t)

                    draw.color(Color4((40/255, 255/255, 40/255, 0.5)))
                    draw.vertex(p0 + d01).vertex(p1 - d01)

            case _:
                pass


    def commit(self, context, event):
        # apply the change

        if self.state == PP_Action.NONE: return

        # make sure artist can see the vert
        bpy.ops.mesh.select_mode(type='VERT', use_extend=True, action='ENABLE')

        select_now = []     # to be selected before move
        select_later = []   # to be selected after move

        match self.state:
            case PP_Action.VERT:
                bmv = self.bm.verts.new(self.hit)
                select_now = [bmv]

            case PP_Action.VERT_EDGE:
                bmv0 = self.bmv
                bmv1 = self.bm.verts.new(self.hit)
                bme = self.bm.edges.new((bmv0, bmv1))
                select_now = [bmv1]
                select_later = [bme]

            case PP_Action.EDGE_TRIANGLE:
                bmv0, bmv1 = self.bme.verts
                bmv = self.bm.verts.new(self.hit)
                bmf = self.bm.faces.new((bmv0,bmv1,bmv))
                select_now = [bmv]
                select_later = [bmf]

            case _:
                assert False, f'Unhandled PolyPen state {self.state}'

        bmops.deselect_all(self.bm)
        for bmelem in select_now:
            bmelem.select_set(True)
        for bmelem in select_later:
            match bmelem:
                case BMVert():
                    bmelem[self.layer_sel_vert] = 1
                case BMEdge():
                    bmelem[self.layer_sel_edge] = 1
                    for bmv in bmelem.verts:
                        bmv[self.layer_sel_vert] = 1
                case BMFace():
                    bmelem[self.layer_sel_face] = 1
                    for bmv in bmelem.verts:
                        bmv[self.layer_sel_vert] = 1
        self.update_selection = bool(select_later)

        self.hit = None

        bmops.flush_selection(self.bm, self.em)
        bpy.ops.transform.transform('INVOKE_DEFAULT', mode='TRANSLATION', **translate_options)
        # NOTE: the select-later property is _not_ transferred to the vert into which the moved vert is auto-merged...
        #       this is handled if a BMEdge or BMFace is to be selected later, but it is not handled if only a BMVert
        #       is created and then merged into existing geometry


class RFOperator_PolyPen(RFOperator):
    bl_idname = "retopoflow.polypen"
    bl_label = 'PolyPen'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymap = {'type': 'LEFT_ALT', 'value': 'PRESS'}
    rf_status = ['LMB: Insert', 'MMB: (nothing)', 'RMB: (nothing)']

    def init(self, context, event):
        print(f'STARTING POLYPEN')
        self.logic = PP_Logic(context, event)

    def update(self, context, event):
        self.logic.update(context, event)

        if not event.alt:
            print(F'LEAVING POLYPEN')
            return {'FINISHED'}

        if event.type == 'LEFTMOUSE':
            self.logic.commit(context, event)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            context.area.tag_redraw()

        return {'RUNNING_MODAL'}

    def draw_postpixel(self, context):
        # print(f'post pixel')
        self.logic.draw(context)


class RFTool_PolyPen(RFTool_Base):
    bl_idname = "retopoflow.polypen"
    bl_label = "PolyPen"
    bl_description = "Create complex topology on vertex-by-vertex basis"
    bl_icon = "ops.generic.select_circle"
    bl_widget = None

    bl_keymap = (
        (RFOperator_PolyPen.bl_idname, RFOperator_PolyPen.rf_keymap, None),
    )

    @classmethod
    def activate(cls, context):
        reseter['context.scene.tool_settings.use_mesh_automerge'] = True
        reseter['context.scene.tool_settings.double_threshold'] = 0.01
        # reseter['context.scene.tool_settings.snap_elements_base'] = {'VERTEX'}
        reseter['context.scene.tool_settings.snap_elements_individual'] = {'FACE_PROJECT', 'FACE_NEAREST'}

    @classmethod
    def deactivate(cls, context):
        reseter.reset()
