'''
Copyright (C) 2022 CG Cookie
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

import bpy
import bgl

from .ui_styling import UI_Styling, ui_defaultstylings

from gpu.types import GPUOffScreen
from gpu_extras.presets import draw_texture_2d
from mathutils import Vector, Matrix

from . import gpustate
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
from .utils import iter_head, any_args, join


class UI_Draw:
    _initialized = False
    _stylesheet = None
    _def_color = (0,0,0,0)

    def init_draw(self):
        import gpu
        from gpu_extras.batch import batch_for_shader

        vertex_positions = [(0,0),(1,0),(1,1),  (1,1),(0,1),(0,0)]
        vertex_shader, fragment_shader = Shader.parse_file('ui_element.glsl', includeVersion=False)
        print(f'Addon Common: compiling UI shader')
        with Drawing.glCheckError_wrap('compiling UI shader and batching'):
            shader = gpustate.gpu_shader(
                vertex_shader, fragment_shader,
                defines={
                    'IMAGE_SCALE_FILL':     0,
                    'IMAGE_SCALE_CONTAIN':  1,
                    'IMAGE_SCALE_COVER':    2,
                    'IMAGE_SCALE_DOWN':     3,
                    'IMAGE_SCALE_NONE':     4,

                    'REGION_MARGIN_LEFT':   0,
                    'REGION_MARGIN_BOTTOM': 1,
                    'REGION_MARGIN_RIGHT':  2,
                    'REGION_MARGIN_TOP':    3,
                    'REGION_BORDER_TOP':    4,
                    'REGION_BORDER_RIGHT':  5,
                    'REGION_BORDER_BOTTOM': 6,
                    'REGION_BORDER_LEFT':   7,
                    'REGION_BACKGROUND':    8,
                    'REGION_OUTSIDE':       9,
                    'REGION_ERROR':        10,
                }
            )
            assert shader
            batch = batch_for_shader(shader, 'TRIS', {"pos": vertex_positions})
            assert batch
        print(f'Addon Common: UI shader initialized')

        get_MVP_matrix = lambda: gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()

        # note: these must correspond correctly with labeled magic numbers in `ui_element.glsl`
        texture_fit_map = {
            'fill':       0, # default.  stretch/squash to fill entire container
            'contain':    1, # scaled to maintain aspect ratio, fit within container
            'cover':      2, # scaled to maintain aspect ratio, fill entire container
            'scale-down': 3, # same as none or contain, whichever is smaller
            'none':       4, # not resized
        }

        def _draw(left, top, width, height, dpi_mult, style, texture_id=None, gputexture=None, texture_fit='fill', background_override=None, depth=None, atex=bgl.GL_TEXTURE0):
            nonlocal shader, batch, get_MVP_matrix, texture_fit_map
            def get_v(style_key, def_val):
                v = style.get(style_key, def_val)
                if type(v) is NumberUnit: v = v.val() * dpi_mult
                return v
            shader.bind()
            # uMVPMatrix needs to be set every draw call, because it could be different
            # when rendering to FrameBuffers with their own (l,b,w,h)
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
            shader.uniform_float('border_left_color',   Color.as_vec4(get_v('border-left-color',   self._def_color)))
            shader.uniform_float('border_right_color',  Color.as_vec4(get_v('border-right-color',  self._def_color)))
            shader.uniform_float('border_top_color',    Color.as_vec4(get_v('border-top-color',    self._def_color)))
            shader.uniform_float('border_bottom_color', Color.as_vec4(get_v('border-bottom-color', self._def_color)))
            shader.uniform_float('background_color',    Color.as_vec4(background_override if background_override else get_v('background-color', self._def_color)))
            shader.uniform_int(  'image_fit',           texture_fit_map.get(texture_fit, 0))
            shader.uniform_int(  'using_image',         1 if texture_id is not None else 0)
            shader.uniform_int(  'image',               atex - bgl.GL_TEXTURE0)
            if texture_id is not None:
                bgl.glActiveTexture(atex)
                bgl.glBindTexture(bgl.GL_TEXTURE_2D, texture_id)
            # if gputexture: shader.uniform_sampler('image', gputexture)
            # Drawing.glCheckError(f'checking gl errors after binding shader and setting uniforms')
            batch.draw(shader)

        UI_Draw._draw = _draw

    def __init__(self):
        if bpy.app.background: return
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

    def draw(self, left, top, width, height, dpi_mult, style, texture_id=None, gputexture=None, texture_fit='fill', background_override=None, depth=None):
        #if texture_id != -1: print('texture_fit', texture_fit)
        UI_Draw._draw(left, top, width, height, dpi_mult, style, texture_id, gputexture, texture_fit, background_override, depth)


ui_draw = Globals.set(UI_Draw())
