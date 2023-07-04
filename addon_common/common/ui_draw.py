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

import bpy
import gpu

from gpu_extras.batch import batch_for_shader
from gpu_extras.presets import draw_texture_2d
from mathutils import Vector, Matrix

from .ui_styling import UI_Styling, ui_defaultstylings

from . import gpustate
from .boundvar import BoundVar
from .debug import debugger, dprint, tprint
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .drawing import Drawing
from .globals import Globals
from .hasher import Hasher
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .maths import floor_if_finite, ceil_if_finite
from .profiler import profiler, time_it
from .utils import iter_head, any_args, join

style_to_image_scale = {
    'fill':       0, # default.  stretch/squash to fill entire container
    'contain':    1, # scaled to maintain aspect ratio, fit within container
    'cover':      2, # scaled to maintain aspect ratio, fill entire container
    'scale-down': 3, # same as none or contain, whichever is smaller
    'none':       4, # not resized
}

image_scale_defines = {
    'IMAGE_SCALE_FILL':     style_to_image_scale['fill'],
    'IMAGE_SCALE_CONTAIN':  style_to_image_scale['contain'],
    'IMAGE_SCALE_COVER':    style_to_image_scale['cover'],
    'IMAGE_SCALE_DOWN':     style_to_image_scale['scale-down'],
    'IMAGE_SCALE_NONE':     style_to_image_scale['none'],
}

region_defines = {
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

# uncomment the following debug options to enable them
enabled_debug_options = [
    # 'DEBUG_COLOR_MARGINS',     # color fragments in margin (top, left, bottom, right)
    # 'DEBUG_COLOR_REGIONS',     # color fragments based on region
    # 'DEBUG_IMAGE_CHECKER',     # replace image with checker pattern to test scaling
    # 'DEBUG_IMAGE_OUTSIDE',     # shift color if texcoord is outside [0,1] (in padding region)
    # 'DEBUG_SNAP_ALPHA',        # snap alpha to 0 or 1 based on 0.25 threshold
    # 'DEBUG_DONT_DISCARD',      # keep all fragments (do not discard any fragment)
]

debug_defines = {
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

if not bpy.app.background:
    draw_data = ( 'TRIS', { 'pos': [(0,0),(1,0),(1,1),  (1,1),(0,1),(0,0)] } )
    defines = image_scale_defines | region_defines | debug_defines | { k:True for k in enabled_debug_options }
    vertex_shader, fragment_shader = gpustate.shader_parse_file('ui_element.glsl', includeVersion=False)
    ui_draw_shader, ui_draw_ubos = gpustate.gpu_shader('UI_Draw', vertex_shader, fragment_shader, defines=defines)
    ui_draw_batch = batch_for_shader(ui_draw_shader, *draw_data)


class UI_Draw:
    default_stylesheet = None

    @staticmethod
    def load_stylesheet(path):
        UI_Draw.default_stylesheet = UI_Styling.from_file(path)

    def update(self): pass

    def draw(self, left, top, width, height, dpi_mult, style, texture_id=None, gputexture=None, texture_fit='fill', background_override=None, depth=None):
        def_color = (0,0,0,0)
        def get_v(style_key, def_val):
            v = style.get(style_key, def_val)
            return v if not isinstance(v, NumberUnit) else (v.val() * dpi_mult)

        ui_draw_shader.bind()
        ui_draw_ubos.options.uMVPMatrix          = gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()
        ui_draw_ubos.options.lrtb                = (float(left), float(left + (width - 1)), float(top), float(top - (height - 1)))
        ui_draw_ubos.options.wh                  = (float(width), float(height), 0, 0)
        ui_draw_ubos.options.depth               = (depth, 0, 0, 0)
        ui_draw_ubos.options.margin_lrtb         = [ get_v(f'margin-{p}',  0) for p in ['left', 'right', 'top', 'bottom'] ]
        ui_draw_ubos.options.padding_lrtb        = [ get_v(f'padding-{p}', 0) for p in ['left', 'right', 'top', 'bottom'] ]
        ui_draw_ubos.options.border_width_radius = [ get_v('border-width', 0), get_v('border-radius', 0), 0, 0 ]
        ui_draw_ubos.options.border_left_color   = Color.as_vec4(get_v('border-left-color',   def_color))
        ui_draw_ubos.options.border_right_color  = Color.as_vec4(get_v('border-right-color',  def_color))
        ui_draw_ubos.options.border_top_color    = Color.as_vec4(get_v('border-top-color',    def_color))
        ui_draw_ubos.options.border_bottom_color = Color.as_vec4(get_v('border-bottom-color', def_color))
        ui_draw_ubos.options.background_color    = Color.as_vec4(background_override if background_override else get_v('background-color', def_color))
        ui_draw_ubos.options.image_settings      = [ (1 if gputexture is not None else 0), style_to_image_scale.get(texture_fit, 0), 0, 0 ]
        if gputexture: ui_draw_shader.uniform_sampler('image', gputexture)
        ui_draw_ubos.update_shader()
        ui_draw_batch.draw(ui_draw_shader)


ui_draw = Globals.set(UI_Draw())
