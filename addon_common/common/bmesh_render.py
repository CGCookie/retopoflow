'''
Copyright (C) 2022 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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


'''
notes: something is really wrong here to have such poor performance

Below are some related, interesting links

- https://machinesdontcare.wordpress.com/2008/02/02/glsl-discard-z-fighting-supersampling/
- https://developer.apple.com/library/archive/documentation/3DDrawing/Conceptual/OpenGLES_ProgrammingGuide/BestPracticesforShaders/BestPracticesforShaders.html
- https://stackoverflow.com/questions/16415037/opengl-core-profile-incredible-slowdown-on-os-x
'''


import os
import re
import math
import ctypes
import random
import traceback

import gpu
import bpy
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d, region_2d_to_vector_3d
)
from bpy_extras.view3d_utils import (
    region_2d_to_location_3d, region_2d_to_origin_3d
)
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree

from . import gpustate
from .debug import dprint
from .decorators import blender_version_wrapper, add_cache, only_in_blender_version
from .drawing import Drawing
from .maths import (Point, Direction, Frame, XForm, invert_matrix, matrix_normal)
from .profiler import profiler
from .shaders import Shader
from .utils import shorten_floats




def glSetDefaultOptions():
    gpustate.blend('ALPHA')
    gpustate.depth_test('LESS_EQUAL')


def glSetMirror(symmetry=None, view=None, effect=0.0, frame: Frame=None):
    mirroring = (0, 0, 0)
    if symmetry and frame:
        mx = 1.0 if 'x' in symmetry else 0.0
        my = 1.0 if 'y' in symmetry else 0.0
        mz = 1.0 if 'z' in symmetry else 0.0
        mirroring = (mx, my, mz)
        bmeshShader.assign('mirror_o', frame.o)
        bmeshShader.assign('mirror_x', frame.x)
        bmeshShader.assign('mirror_y', frame.y)
        bmeshShader.assign('mirror_z', frame.z)
    bmeshShader.assign('mirror_view', {'Edge': 1, 'Face': 2}.get(view, 0))
    bmeshShader.assign('mirror_effect', effect)
    bmeshShader.assign('mirroring', mirroring)

def triangulateFace(verts):
    l = len(verts)
    if l < 3: return
    if l == 3:
        yield verts
        return
    if l == 4:
        v0,v1,v2,v3 = verts
        yield (v0,v1,v2)
        yield (v0,v2,v3)
        return
    iv = iter(verts)
    v0, v2 = next(iv), next(iv)
    for v3 in iv:
        v1, v2 = v2, v3
        yield (v0, v1, v2)


#############################################################################################################
#############################################################################################################
#############################################################################################################

import gpu
from gpu_extras.batch import batch_for_shader
from .shaders import Shader

Drawing.glCheckError(f'Pre-compile check: bmesh render shader')
verts_vs, verts_fs = Shader.parse_file('bmesh_render_verts.glsl', includeVersion=False)
verts_shader = gpu.types.GPUShader(verts_vs, verts_fs)
edges_vs, edges_fs = Shader.parse_file('bmesh_render_edges.glsl', includeVersion=False)
edges_shader = gpu.types.GPUShader(edges_vs, edges_fs)
faces_vs, faces_fs = Shader.parse_file('bmesh_render_faces.glsl', includeVersion=False)
faces_shader = gpu.types.GPUShader(faces_vs, faces_fs)
Drawing.glCheckError(f'Compiled bmesh render shader')


class BufferedRender_Batch:
    _quarantine = {}

    POINTS    = 1
    LINES     = 2
    TRIANGLES = 3

    def __init__(self, drawtype):
        global faces_shader, edges_shader, verts_shader
        self.count = 0
        self.drawtype = drawtype
        self.shader, self.shader_type, self.drawtype_name, self.gl_count, self.options_prefix = {
            self.POINTS:    (verts_shader, 'POINTS', 'points',    1, 'point'),
            self.LINES:     (edges_shader, 'LINES',  'lines',     2, 'line'),
            self.TRIANGLES: (faces_shader, 'TRIS',   'triangles', 3, 'poly'),
        }[self.drawtype]
        self.batch = None
        self._quarantine.setdefault(self.shader, set())

    def buffer(self, pos, norm, sel, warn, pin, seam):
        if self.shader == None: return
        if self.shader_type == 'POINTS':
            data = {
                # repeat each value 6 times
                'vert_pos':    [p for p in pos  for __ in range(6)],
                'vert_norm':   [n for n in norm for __ in range(6)],
                'selected':    [s for s in sel  for __ in range(6)],
                'warning':     [w for w in warn for __ in range(6)],
                'pinned':      [p for p in pin  for __ in range(6)],
                'seam':        [p for p in seam for __ in range(6)],
                'vert_offset': [o for _ in pos for o in [(0,0), (1,0), (0,1), (0,1), (1,0), (1,1)]],
            }
        elif self.shader_type == 'LINES':
            data = {
                # repeat each value 6 times
                'vert_pos0':   [p0 for p0 in pos [0::2] for __ in range(6)],
                'vert_pos1':   [p1 for p1 in pos [1::2] for __ in range(6)],
                'vert_norm':   [n  for n  in norm[0::2] for __ in range(6)],
                'selected':    [s  for s  in sel [0::2] for __ in range(6)],
                'warning':     [w  for w  in warn[0::2] for __ in range(6)],
                'pinned':      [p  for p  in pin [0::2] for __ in range(6)],
                'seam':        [s  for s  in seam[0::2] for __ in range(6)],
                'vert_offset': [o for _ in pos[0::2] for o in [(0,0), (0,1), (1,1), (0,0), (1,1), (1,0)]],
        }
        elif self.shader_type == 'TRIS':
            data = {
                'vert_pos':    pos,
                'vert_norm':   norm,
                'selected':    sel,
                'pinned':      pin,
                # 'seam':        seam,
            }
        else: assert False, f'BufferedRender_Batch.buffer: Unhandled type: {self.shader_type}'
        self.batch = batch_for_shader(self.shader, 'TRIS', data)
        self.count = len(pos)

    def set_options(self, prefix, opts):
        if not opts: return
        shader = self.shader

        prefix = f'{prefix} ' if prefix else ''

        def set_if_set(opt, cb):
            opt = f'{prefix}{opt}'
            if opt not in opts: return
            cb(opts[opt])
            Drawing.glCheckError(f'setting {opt} to {opts[opt]}')

        Drawing.glCheckError('BufferedRender_Batch.set_options: start')
        dpi_mult = opts.get('dpi mult', 1.0)
        set_if_set('color',          lambda v: self.uniform_float('color', v))
        set_if_set('color selected', lambda v: self.uniform_float('color_selected', v))
        set_if_set('color warning',  lambda v: self.uniform_float('color_warning', v))
        set_if_set('color pinned',   lambda v: self.uniform_float('color_pinned', v))
        set_if_set('color seam',     lambda v: self.uniform_float('color_seam', v))
        set_if_set('hidden',         lambda v: self.uniform_float('hidden', v))
        set_if_set('offset',         lambda v: self.uniform_float('offset', v))
        set_if_set('dotoffset',      lambda v: self.uniform_float('dotoffset', v))
        if self.shader_type == 'POINTS':
            set_if_set('size',       lambda v: self.uniform_float('radius', v*dpi_mult))
        elif self.shader_type == 'LINES':
            set_if_set('width',      lambda v: self.uniform_float('radius', v*dpi_mult))

    def _draw(self, sx, sy, sz):
        self.uniform_float('vert_scale', (sx, sy, sz))
        # print(f'bmesh._draw', gpustate.get_depth_test(), gpu.state.depth_test_get(), gpustate.get_depth_mask(), gpu.state.depth_mask_get())
        self.batch.draw(self.shader)
        # Drawing.glCheckError('_draw: glDrawArrays (%d)' % self.count)

    def is_quarantined(self, k):
        return k in self._quarantine[self.shader]
    def quarantine(self, k):
        dprint(f'BufferedRender_Batch: quarantining {k} for {self.shader}')
        self._quarantine[self.shader].add(k)
    def uniform_float(self, k, v):
        if self.is_quarantined(k): return
        try: self.shader.uniform_float(k, v)
        except Exception as e: self.quarantine(k)
    def uniform_int(self, k, v):
        if self.is_quarantined(k): return
        try: self.shader.uniform_int(k, v)
        except Exception as e: self.quarantine(k)
    def uniform_bool(self, k, v):
        if self.is_quarantined(k): return
        try: self.shader.uniform_bool(k, v)
        except Exception as e: self.quarantine(k)

    def draw(self, opts):
        if self.shader == None or self.count == 0: return
        if self.drawtype == self.LINES  and opts.get('line width', 1.0) <= 0: return
        if self.drawtype == self.POINTS and opts.get('point size', 1.0) <= 0: return

        ctx = bpy.context
        area, spc, r3d = ctx.area, ctx.space_data, ctx.space_data.region_3d

        if 'blend'      in opts: gpustate.blend(opts['blend'])
        if 'depth test' in opts: gpustate.depth_test(opts['depth test'])
        if 'depth mask' in opts: gpustate.depth_mask(opts['depth mask'])

        self.shader.bind()

        # set defaults
        self.uniform_float('color',          (1.0, 1.0, 1.0, 0.5))
        self.uniform_float('color_selected', (0.5, 1.0, 0.5, 0.5))
        self.uniform_float('color_warning',  (1.0, 0.5, 0.0, 0.5))
        self.uniform_float('color_pinned',   (1.0, 0.0, 0.5, 0.5))
        self.uniform_float('color_seam',     (1.0, 0.0, 0.5, 0.5))
        self.uniform_float('hidden',         0.9)
        self.uniform_float('offset',         0.0)
        self.uniform_float('dotoffset',      0.0)
        self.uniform_float('vert_scale',     (1.0, 1.0, 1.0))
        self.uniform_float('radius',         1.0)

        self.uniform_bool('use_selection', (not opts.get('no selection', False)))
        self.uniform_bool('use_warning',   (not opts.get('no warning',   False)))
        self.uniform_bool('use_pinned',    (not opts.get('no pinned',    False)))
        self.uniform_bool('use_seam',      (not opts.get('no seam',      False)))
        self.uniform_bool('use_rounding',  (self.drawtype == self.POINTS))

        self.uniform_float('matrix_m',    opts['matrix model'])
        self.uniform_float('matrix_mn',   opts['matrix normal'])
        self.uniform_float('matrix_t',    opts['matrix target'])
        self.uniform_float('matrix_ti',   opts['matrix target inverse'])
        self.uniform_float('matrix_v',    opts['matrix view'])
        self.uniform_float('matrix_vn',   opts['matrix view normal'])
        self.uniform_float('matrix_p',    opts['matrix projection'])
        self.uniform_float('dir_forward', opts['forward direction'])
        self.uniform_float('unit_scaling_factor', opts['unit scaling factor'])

        mx, my, mz = opts.get('mirror x', False), opts.get('mirror y', False), opts.get('mirror z', False)
        symmetry = opts.get('symmetry', None)
        symmetry_frame = opts.get('symmetry frame', None)
        symmetry_view = opts.get('symmetry view', None)
        symmetry_effect = opts.get('symmetry effect', 0.0)
        mirroring = (False, False, False)
        if symmetry and symmetry_frame:
            mx = 'x' in symmetry
            my = 'y' in symmetry
            mz = 'z' in symmetry
            mirroring = (mx, my, mz)
            self.uniform_float('mirror_o', symmetry_frame.o)
            self.uniform_float('mirror_x', symmetry_frame.x)
            self.uniform_float('mirror_y', symmetry_frame.y)
            self.uniform_float('mirror_z', symmetry_frame.z)
        self.uniform_int('mirror_view', [{'Edge': 1, 'Face': 2}.get(symmetry_view, 0)])
        self.uniform_float('mirror_effect', symmetry_effect)
        self.uniform_bool('mirroring', mirroring)

        self.uniform_float('normal_offset',   opts.get('normal offset', 0.0))
        self.uniform_bool('constrain_offset', opts.get('constrain offset', True))

        self.uniform_bool('perspective', (r3d.view_perspective != 'ORTHO'))
        self.uniform_float('clip_start', spc.clip_start)
        self.uniform_float('clip_end', spc.clip_end)
        self.uniform_float('view_distance', r3d.view_distance)
        self.uniform_float('screen_size', Vector((area.width, area.height)))

        focus = opts.get('focus mult', 1.0)
        self.uniform_float('focus_mult',      focus)
        self.uniform_bool('cull_backfaces',   opts.get('cull backfaces', False))
        self.uniform_float('alpha_backface',  opts.get('alpha backface', 0.5))

        self.set_options(self.options_prefix, opts)
        self._draw(1, 1, 1)

        if opts['draw mirrored'] and (mx or my or mz):
            self.set_options(f'{self.options_prefix} mirror', opts)
            if mx:               self._draw(-1,  1,  1)
            if        my:        self._draw( 1, -1,  1)
            if               mz: self._draw( 1,  1, -1)
            if mx and my:        self._draw(-1, -1,  1)
            if mx        and mz: self._draw(-1,  1, -1)
            if        my and mz: self._draw( 1, -1, -1)
            if mx and my and mz: self._draw(-1, -1, -1)

        gpu.shader.unbind()

