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

from .ui_styling import UI_Styling, ui_defaultstylings

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
from .utils import iter_head, any_args, join


class UI_Draw:
    _initialized = False
    _stylesheet = None
    _def_color = (0,0,0,0)

    def init_draw(self):
        import gpu
        from gpu_extras.batch import batch_for_shader

        vertex_positions = [(0,0),(1,0),(1,1),  (1,1),(0,1),(0,0)]
        vertex_shader, fragment_shader = gpustate.shader_parse_file('ui_element.glsl', includeVersion=False)
        print(f'Addon Common: compiling UI shader')
        with Drawing.glCheckError_wrap('compiling UI shader and batching'):
            shader, ubos = gpustate.gpu_shader(
                f'UI_Draw',
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

                    #####################################################
                    # debugging options
                    'DEBUG_COLOR_MARGINS': 'false',     # colors pixels in margin (top, left, bottom, right)
                    'DEBUG_COLOR_REGIONS': 'false',     # colors pixels based on region
                    'DEBUG_IMAGE_CHECKER': 'false',     # replaces images with checker pattern to test scaling
                    'DEBUG_IMAGE_OUTSIDE': 'false',     # shifts colors if texcoord is outside [0,1] (in padding region)
                    'DEBUG_IGNORE_ALPHA':  'false',     # snaps alpha to 0 or 1 based on 0.25 threshold
                    'DEBUG_DONT_DISCARD':  'false',
                    # colors used if DEBUG_COLOR_MARGINS or DEBUG_COLOR_REGIONS are set to true
                    'COLOR_MARGIN_LEFT':    'vec4(1.0, 0.0, 0.0, 0.25)',
                    'COLOR_MARGIN_BOTTOM':  'vec4(0.0, 1.0, 0.0, 0.25)',
                    'COLOR_MARGIN_RIGHT':   'vec4(0.0, 0.0, 1.0, 0.25)',
                    'COLOR_MARGIN_TOP':     'vec4(0.0, 1.0, 1.0, 0.25)',
                    'COLOR_BORDER_TOP':     'vec4(0.5, 0.0, 0.0, 0.25)',
                    'COLOR_BORDER_RIGHT':   'vec4(0.0, 0.5, 0.5, 0.25)',
                    'COLOR_BORDER_BOTTOM':  'vec4(0.0, 0.5, 0.5, 0.25)',
                    'COLOR_BORDER_LEFT':    'vec4(0.0, 0.5, 0.5, 0.25)',
                    'COLOR_BACKGROUND':     'vec4(0.5, 0.5, 0.0, 0.25)',
                    'COLOR_OUTSIDE':        'vec4(0.5, 0.5, 0.5, 0.25)',
                    'COLOR_ERROR':          'vec4(1.0, 0.0, 0.0, 1.00)',
                    'COLOR_ERROR_NEVER':    'vec4(1.0, 0.0, 1.0, 1.00)',
                    'COLOR_DEBUG_IMAGE':    'vec4(0.0, 0.0, 0.0, 0.00)',
                    'COLOR_CHECKER_00':     'vec4(0.0, 0.0, 0.0, 1.00)',
                    'COLOR_CHECKER_01':     'vec4(0.0, 0.0, 0.5, 1.00)',
                    'COLOR_CHECKER_02':     'vec4(0.0, 0.5, 0.0, 1.00)',
                    'COLOR_CHECKER_03':     'vec4(0.0, 0.5, 0.5, 1.00)',
                    'COLOR_CHECKER_04':     'vec4(0.5, 0.0, 0.0, 1.00)',
                    'COLOR_CHECKER_05':     'vec4(0.5, 0.0, 0.5, 1.00)',
                    'COLOR_CHECKER_06':     'vec4(0.5, 0.5, 0.0, 1.00)',
                    'COLOR_CHECKER_07':     'vec4(0.5, 0.5, 0.5, 1.00)',
                    'COLOR_CHECKER_08':     'vec4(0.3, 0.3, 0.3, 1.00)',
                    'COLOR_CHECKER_09':     'vec4(0.0, 0.0, 1.0, 1.00)',
                    'COLOR_CHECKER_10':     'vec4(0.0, 1.0, 0.0, 1.00)',
                    'COLOR_CHECKER_11':     'vec4(0.0, 1.0, 1.0, 1.00)',
                    'COLOR_CHECKER_12':     'vec4(1.0, 0.0, 0.0, 1.00)',
                    'COLOR_CHECKER_13':     'vec4(1.0, 0.0, 1.0, 1.00)',
                    'COLOR_CHECKER_14':     'vec4(1.0, 1.0, 0.0, 1.00)',
                    'COLOR_CHECKER_15':     'vec4(1.0, 1.0, 1.0, 1.00)',

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

        def _draw(left, top, width, height, dpi_mult, style, texture_id=None, gputexture=None, texture_fit='fill', background_override=None, depth=None):
            nonlocal shader, batch, get_MVP_matrix, texture_fit_map
            def get_v(style_key, def_val):
                v = style.get(style_key, def_val)
                if type(v) is NumberUnit: v = v.val() * dpi_mult
                return v
            shader.bind()
            # uMVPMatrix needs to be set every draw call, because it could be different
            # when rendering to FrameBuffers with their own (l,b,w,h)
            ubos.options.uMVPMatrix          = get_MVP_matrix()

            ubos.options.lrtb                = (float(left), float(left + (width - 1)), float(top), float(top - (height - 1)))
            ubos.options.wh                  = (float(width), float(height), 0, 0)

            ubos.options.depth               = (depth, 0, 0, 0)

            ubos.options.margin_lrtb         = [get_v(f'margin-{p}',  0) for p in ['left', 'right', 'top', 'bottom']]
            ubos.options.padding_lrtb        = [get_v(f'padding-{p}', 0) for p in ['left', 'right', 'top', 'bottom']]

            ubos.options.border_width_radius = [get_v('border-width',   0), get_v('border-radius',  0), 0, 0]
            ubos.options.border_left_color =   Color.as_vec4(get_v('border-left-color',   self._def_color))
            ubos.options.border_right_color =  Color.as_vec4(get_v('border-right-color',  self._def_color))
            ubos.options.border_top_color =    Color.as_vec4(get_v('border-top-color',    self._def_color))
            ubos.options.border_bottom_color = Color.as_vec4(get_v('border-bottom-color', self._def_color))

            ubos.options.background_color =    Color.as_vec4(background_override if background_override else get_v('background-color', self._def_color))

            ubos.options.image_use_fit = [(1 if gputexture is not None else 0), texture_fit_map.get(texture_fit, 0), 0, 0]
            if gputexture: shader.uniform_sampler('image', gputexture)

            ubos.update_shader()
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
