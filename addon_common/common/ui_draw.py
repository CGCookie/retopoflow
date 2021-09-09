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

import bgl

from .ui_styling import UI_Styling, ui_defaultstylings

from gpu.types import GPUOffScreen
from gpu_extras.presets import draw_texture_2d
from mathutils import Vector, Matrix

from .boundvar import BoundVar
from .debug import debugger, dprint, tprint
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .drawing import Drawing
from .fontmanager import FontManager
from .globals import Globals
from .hasher import Hasher
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .maths import floor_if_finite, ceil_if_finite
from .profiler import profiler, time_it
from .shaders import Shader
from .utils import iter_head, any_args, join, abspath


class UI_Draw:
    _initialized = False
    _stylesheet = None

    @blender_version_wrapper('<=', '2.79')
    def init_draw(self):
        # TODO: test this implementation!
        assert False, 'function implementation not tested yet!!!'
        # UI_Draw._shader = Shader.load_from_file('ui', 'uielement.glsl', checkErrors=True)
        # sizeOfFloat, sizeOfInt = 4, 4
        # pos = [(0,0),(1,0),(1,1),  (0,0),(1,1),(0,1)]
        # count = len(pos)
        # buf_pos = bgl.Buffer(bgl.GL_FLOAT, [count, 2], pos)
        # vbos = bgl.Buffer(bgl.GL_INT, 1)
        # bgl.glGenBuffers(1, vbos)
        # vbo_pos = vbos[0]
        # bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, vbo_pos)
        # bgl.glBufferData(bgl.GL_ARRAY_BUFFER, count * 2 * sizeOfFloat, buf_pos, bgl.GL_STATIC_DRAW)
        # bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, 0)
        # en = UI_Draw._shader.enable
        # di = UI_Draw._shader.disable
        # eva = UI_Draw._shader.vertexAttribPointer
        # dva = UI_Draw._shader.disableVertexAttribArray
        # a = UI_Draw._shader.assign
        # def draw(left, top, width, height, style):
        #     nonlocal vbo_pos, count, en, di, eva, dva, a
        #     en()
        #     a('left',   left)
        #     a('top',    top)
        #     a('right',  left+width-1)
        #     a('bottom', top-height+1)
        #     a('margin_left',   style.get('margin-left', 0))
        #     a('margin_right',  style.get('margin-right', 0))
        #     a('margin_top',    style.get('margin-top', 0))
        #     a('margin_bottom', style.get('margin-bottom', 0))
        #     a('border_width',        style.get('border-width', 0))
        #     a('border_radius',       style.get('border-radius', 0))
        #     a('border_left_color',   style.get('border-left-color', (0,0,0,1)))
        #     a('border_right_color',  style.get('border-right-color', (0,0,0,1)))
        #     a('border_top_color',    style.get('border-top-color', (0,0,0,1)))
        #     a('border_bottom_color', style.get('border-bottom-color', (0,0,0,1)))
        #     a('background_color', style.get('background-color', (0,0,0,1)))
        #     eva(vbo_pos, 'pos', 2, bgl.GL_FLOAT)
        #     bgl.glDrawArrays(bgl.GL_TRIANGLES, 0, count)
        #     dva('pos')
        #     di()
        # UI_Draw._draw = draw

    @blender_version_wrapper('>=', '2.80')
    def init_draw(self):
        import gpu
        from gpu_extras.batch import batch_for_shader

        vertex_positions = [(0,0),(1,0),(1,1),  (1,1),(0,1),(0,0)]
        vertex_shader, fragment_shader = Shader.parse_file('ui_element.glsl', includeVersion=False)
        print(f'Addon Common: compiling UI shader')
        shader = gpu.types.GPUShader(vertex_shader, fragment_shader) #name='RetopoFlowUIShader'
        Drawing.glCheckError(f'Compiled shader {shader}')
        print(f'Addon Common: batching for shader')
        batch = batch_for_shader(shader, 'TRIS', {"pos": vertex_positions})
        Drawing.glCheckError(f'Batched for shader {batch}')
        print(f'Addon Common: UI shader initialized')
        # get_pixel_matrix = Globals.drawing.get_pixel_matrix
        get_MVP_matrix = lambda: gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()
        def_color = (0,0,0,0)

        print(f'Addon Common: ########################################')
        print(f'              Loading shader using Shader')
        shader2 = Shader.load_from_file('uiShader', 'ui_element.glsl', force_shim=True)

        def draw(left, top, width, height, dpi_mult, style, texture_id=None, texture_fit=0, background_override=None, depth=None, atex=bgl.GL_TEXTURE0):
            nonlocal shader, batch, def_color, get_MVP_matrix
            nonlocal shader2
            def get_v(style_key, def_val):
                v = style.get(style_key, def_val)
                if type(v) is NumberUnit: v = v.val() * dpi_mult
                return v
            # shader2.enable()
            # shader2.assign_all(
            #     #uMVPMatrix = get_MVP_matrix(),
            #     left   = left,
            #     top    = top,
            #     right  = left + (width - 1),
            #     bottom = top - (height - 1),
            #     width  = width,
            #     height = height,
            #     depth  = depth,
            #     margin_left    = get_v('margin-left', 0),
            #     margin_right   = get_v('margin-right', 0),
            #     margin_top     = get_v('margin-top', 0),
            #     margin_bottom  = get_v('margin-bottom', 0),
            #     padding_left   = get_v('padding-left', 0),
            #     padding_right  = get_v('padding-right', 0),
            #     padding_top    = get_v('padding-top', 0),
            #     padding_bottom = get_v('padding-bottom', 0),
            #     border_width   = get_v('border-width', 0),
            #     border_radius  = get_v('border-radius', 0),
            #     border_left_color   = get_v('border-left-color', def_color),
            #     border_right_color  = get_v('border-right-color', def_color),
            #     border_top_color    = get_v('border-top-color', def_color),
            #     border_bottom_color = get_v('border-bottom-color', def_color),
            # )
            # shader2.disable()
            # Drawing.glCheckError(f'checking gl errors before binding shader')
            shader.bind()
            # uMVPMatrix needs to be set every draw call, because it could be different
            # when rendering to FrameBuffers with their own l,b,w,h
            shader.uniform_float("uMVPMatrix",          get_MVP_matrix())
            shader.uniform_float('left',                left)
            shader.uniform_float('top',                 top)
            shader.uniform_float('right',               left + (width - 1))
            shader.uniform_float('bottom',              top - (height - 1))
            shader.uniform_float('width',               width)
            shader.uniform_float('height',              height)
            shader.uniform_float('depth',               depth)
            shader.uniform_float('margin_left',         get_v('margin-left',    0))
            shader.uniform_float('margin_right',        get_v('margin-right',   0))
            shader.uniform_float('margin_top',          get_v('margin-top',     0))
            shader.uniform_float('margin_bottom',       get_v('margin-bottom',  0))
            shader.uniform_float('padding_left',        get_v('padding-left',   0))
            shader.uniform_float('padding_right',       get_v('padding-right',  0))
            shader.uniform_float('padding_top',         get_v('padding-top',    0))
            shader.uniform_float('padding_bottom',      get_v('padding-bottom', 0))
            shader.uniform_float('border_width',        get_v('border-width',   0))
            shader.uniform_float('border_radius',       get_v('border-radius',  0))
            shader.uniform_float('border_left_color',   Color.as_vec4(get_v('border-left-color',   def_color)))
            shader.uniform_float('border_right_color',  Color.as_vec4(get_v('border-right-color',  def_color)))
            shader.uniform_float('border_top_color',    Color.as_vec4(get_v('border-top-color',    def_color)))
            shader.uniform_float('border_bottom_color', Color.as_vec4(get_v('border-bottom-color', def_color)))
            shader.uniform_float('background_color',    Color.as_vec4(background_override if background_override else get_v('background-color', def_color)))
            shader.uniform_int(  'image_fit',           texture_fit)
            shader.uniform_int(  'using_image',         1 if texture_id is not None else 0)
            shader.uniform_int(  'image',               atex - bgl.GL_TEXTURE0)
            if texture_id is not None:
                bgl.glActiveTexture(atex)
                bgl.glBindTexture(bgl.GL_TEXTURE_2D, texture_id)
            batch.draw(shader)

        UI_Draw._draw = draw

    def __init__(self):
        if not UI_Draw._initialized:
            self.init_draw()
            UI_Draw._initialized = True

    @staticmethod
    def load_stylesheet(path):
        UI_Draw._stylesheet = UI_Styling.from_file(path)
    @property
    def stylesheet(self):
        return self._stylesheet

    def update(self):
        ''' only need to call once every redraw '''
        pass

    # note: these must correspond correctly with labeled magic numbers in `ui_element.glsl`
    texture_fit_map = {
        'fill':       0, # default.  stretch/squash to fill entire container
        'contain':    1, # scaled to maintain aspect ratio, fit within container
        'cover':      2, # scaled to maintain aspect ratio, fill entire container
        'scale-down': 3, # same as none or contain, whichever is smaller
        'none':       4, # not resized
    }
    def draw(self, left, top, width, height, dpi_mult, style, texture_id=None, texture_fit='fill', background_override=None, depth=None):
        texture_fit = self.texture_fit_map.get(texture_fit, 0)
        #if texture_id != -1: print('texture_fit', texture_fit)
        UI_Draw._draw(left, top, width, height, dpi_mult, style, texture_id, texture_fit, background_override, depth)


ui_draw = Globals.set(UI_Draw())
