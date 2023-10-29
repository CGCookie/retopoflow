'''
Copyright (C) 2023 CG Cookie
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
from bpy_extras.view3d_utils import region_2d_to_origin_3d
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree

from . import gpustate
from .debug import dprint
from .decorators import blender_version_wrapper, add_cache, only_in_blender_version
from .drawing import Drawing
from .maths import (Point, Direction, Frame, XForm, invert_matrix, matrix_normal)
from .profiler import profiler
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

if not bpy.app.background:
    Drawing.glCheckError(f'Pre-compile check: bmesh render shader')
    verts_vs, verts_fs = gpustate.shader_parse_file('bmesh_render_verts.glsl', includeVersion=False)
    verts_shader, verts_ubos = gpustate.gpu_shader('bmesh render: verts', verts_vs, verts_fs)
    edges_vs, edges_fs = gpustate.shader_parse_file('bmesh_render_edges.glsl', includeVersion=False)
    edges_shader, edges_ubos = gpustate.gpu_shader('bmesh render: edges', edges_vs, edges_fs)
    faces_vs, faces_fs = gpustate.shader_parse_file('bmesh_render_faces.glsl', includeVersion=False)
    faces_shader, faces_ubos = gpustate.gpu_shader('bmesh render: faces', faces_vs, faces_fs)
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
        self.shader, self.shader_ubos, self.shader_type, self.drawtype_name, self.gl_count, self.options_prefix = {
            self.POINTS:    (verts_shader, verts_ubos, 'POINTS', 'points',    1, 'point'),
            self.LINES:     (edges_shader, edges_ubos, 'LINES',  'lines',     2, 'line'),
            self.TRIANGLES: (faces_shader, faces_ubos, 'TRIS',   'triangles', 3, 'poly'),
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

        prefix = f'{prefix} ' if prefix else ''

        def set_if_set(opt, cb):
            opt = f'{prefix}{opt}'
            if opt not in opts: return
            cb(opts[opt])
            Drawing.glCheckError(f'setting {opt} to {opts[opt]}')

        Drawing.glCheckError('BufferedRender_Batch.set_options: start')
        dpi_mult = opts.get('dpi mult', 1.0)
        set_if_set('color',          lambda v: self.set_shader_option('color_normal', v))
        set_if_set('color selected', lambda v: self.set_shader_option('color_selected', v))
        set_if_set('color warning',  lambda v: self.set_shader_option('color_warning', v))
        set_if_set('color pinned',   lambda v: self.set_shader_option('color_pinned', v))
        set_if_set('color seam',     lambda v: self.set_shader_option('color_seam', v))
        set_if_set('hidden',         lambda v: self.set_shader_option('hidden', (v, 0, 0, 0)))
        set_if_set('offset',         lambda v: self.set_shader_option('offset', (v, 0, 0, 0)))
        set_if_set('dotoffset',      lambda v: self.set_shader_option('dotoffset', (v, 0, 0, 0)))
        if self.shader_type == 'POINTS':
            set_if_set('size',       lambda v: self.set_shader_option('radius', (v*dpi_mult, 0, 0, 0)))
        elif self.shader_type == 'LINES':
            set_if_set('width',      lambda v: self.set_shader_option('radius', (v*dpi_mult, 2*dpi_mult, 0, 0)))

    def _draw(self, sx, sy, sz):
        self.set_shader_option('vert_scale', (sx, sy, sz, 0))
        self.shader_ubos.update_shader()
        self.batch.draw(self.shader)

    def is_quarantined(self, k):
        return k in self._quarantine[self.shader]
    def quarantine(self, k):
        dprint(f'BufferedRender_Batch: quarantining {k} for {self.shader}')
        self._quarantine[self.shader].add(k)
    def set_shader_option(self, k, v):
        if self.is_quarantined(k): return
        try: self.shader_ubos.options.assign(k, v)
        except Exception as e: self.quarantine(k)

    def draw(self, opts):
        if self.shader == None or self.count == 0: return
        if self.drawtype == self.LINES  and opts.get('line width', 1.0) <= 0: return
        if self.drawtype == self.POINTS and opts.get('point size', 1.0) <= 0: return

        ctx = bpy.context
        area, spc, r3d = ctx.area, ctx.space_data, ctx.space_data.region_3d
        rgn = ctx.region

        if 'blend'      in opts: gpustate.blend(opts['blend'])
        if 'depth test' in opts: gpustate.depth_test(opts['depth test'])
        if 'depth mask' in opts: gpustate.depth_mask(opts['depth mask'])

        self.shader.bind()

        # set defaults
        self.set_shader_option('color_normal',   (1.0, 1.0, 1.0, 0.5))
        self.set_shader_option('color_selected', (0.5, 1.0, 0.5, 0.5))
        self.set_shader_option('color_warning',  (1.0, 0.5, 0.0, 0.5))
        self.set_shader_option('color_pinned',   (1.0, 0.0, 0.5, 0.5))
        self.set_shader_option('color_seam',     (1.0, 0.0, 0.5, 0.5))
        self.set_shader_option('hidden',         (0.9, 0, 0, 0))
        self.set_shader_option('offset',         (0.0, 0, 0, 0))
        self.set_shader_option('dotoffset',      (0.0, 0, 0, 0))
        self.set_shader_option('vert_scale',     (1.0, 1.0, 1.0))
        self.set_shader_option('radius',         (1.0, 0, 0, 0))

        use0 = [
            1.0 if (not opts.get('no selection', False)) else 0.0,
            1.0 if (not opts.get('no warning',   False)) else 0.0,
            1.0 if (not opts.get('no pinned',    False)) else 0.0,
            1.0 if (not opts.get('no seam',      False)) else 0.0,
        ]
        use1 = [
            1.0 if (self.drawtype == self.POINTS) else 0.0,
            0.0,
            0.0,
            0.0,
        ]
        self.set_shader_option('use_settings0', use0)
        self.set_shader_option('use_settings1', use1)

        self.set_shader_option('matrix_m',    opts['matrix model'])
        self.set_shader_option('matrix_mn',   opts['matrix normal'])
        self.set_shader_option('matrix_t',    opts['matrix target'])
        self.set_shader_option('matrix_ti',   opts['matrix target inverse'])
        self.set_shader_option('matrix_v',    opts['matrix view'])
        self.set_shader_option('matrix_vn',   opts['matrix view normal'])
        self.set_shader_option('matrix_p',    opts['matrix projection'])

        mx, my, mz = opts.get('mirror x', False), opts.get('mirror y', False), opts.get('mirror z', False)
        symmetry = opts.get('symmetry', None)
        symmetry_frame = opts.get('symmetry frame', None)
        symmetry_view = opts.get('symmetry view', None)
        symmetry_effect = opts.get('symmetry effect', 0.0)
        mirroring = (0, 0, 0, 0)
        if symmetry and symmetry_frame:
            mirroring = (
                1 if 'x' in symmetry else 0,
                1 if 'y' in symmetry else 0,
                1 if 'z' in symmetry else 0,
            )
            self.set_shader_option('mirror_o', symmetry_frame.o)
            self.set_shader_option('mirror_x', symmetry_frame.x)
            self.set_shader_option('mirror_y', symmetry_frame.y)
            self.set_shader_option('mirror_z', symmetry_frame.z)
        mirror_settings = [
            {'Edge': 1.0, 'Face': 2.0}.get(symmetry_view, 0.0),
            symmetry_effect,
            0.0,
            0.0,
        ]
        self.set_shader_option('mirror_settings', mirror_settings)
        self.set_shader_option('mirroring', mirroring)

        view_settings0 = [
            r3d.view_distance,
            0.0 if (r3d.view_perspective == 'ORTHO') else 1.0,
            opts.get('focus mult', 1.0),
            opts.get('alpha backface', 0.5),
        ]
        view_settings1 = [
            1.0 if opts.get('cull backfaces', False) else 0.0,
            opts['unit scaling factor'],
            opts.get('normal offset', 0.0) if symmetry_view is None else 0.05,
            1.0 if opts.get('constrain offset', True) else 0.0,
        ]
        view_settings2 = [
            0.99 if symmetry_view is None else 1.0,
            0.0,
            0.0,
            0.0,
        ]
        self.set_shader_option('view_settings0', view_settings0)
        self.set_shader_option('view_settings1', view_settings1)
        self.set_shader_option('view_settings2', view_settings2)
        self.set_shader_option('view_position', region_2d_to_origin_3d(rgn, r3d, (area.width/2, area.height/2)))

        self.set_shader_option('clip',        (spc.clip_start, spc.clip_end, 0.0, 0.0))
        self.set_shader_option('screen_size', (area.width, area.height, 0.0, 0.0))

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

