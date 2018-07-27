'''
Copyright (C) 2016 CG Cookie
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

import bmesh
import bgl
import bpy
from bpy_extras.view3d_utils import (
    location_3d_to_region_2d, region_2d_to_vector_3d
)
from bpy_extras.view3d_utils import (
    region_2d_to_location_3d, region_2d_to_origin_3d
)
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree

from .debug import dprint
from .shaders import Shader, buf_zero
from .utils import shorten_floats
from .maths import Point, Direction, Frame
from .maths import invert_matrix, matrix_normal
from .profiler import profiler



# note: not all supported by user system, but we don't need full functionality
# https://github.com/mattdesl/lwjgl-basics/wiki/GLSL-Versions
# OpenGL  GLSL    OpenGL  GLSL
#  2.0    110      2.1    120
#  3.0    130      3.1    140
#  3.2    150      3.3    330
#  4.0    400      4.1    410
#  4.2    420      4.3    430
dprint('GLSL Version: ' + bgl.glGetString(bgl.GL_SHADING_LANGUAGE_VERSION))


def setupBMeshShader(shader):
    ctx = bpy.context
    area, spc, r3d = ctx.area, ctx.space_data, ctx.space_data.region_3d
    shader.assign('perspective', 1.0 if r3d.view_perspective !=
                  'ORTHO' else 0.0)
    shader.assign('clip_start', spc.clip_start)
    shader.assign('clip_end', spc.clip_end)
    shader.assign('view_distance', r3d.view_distance)
    shader.assign('vert_scale', Vector((1, 1, 1)))
    shader.assign('screen_size', Vector((area.width, area.height)))

bmeshShader = Shader.load_from_file('bmeshShader', 'bmesh_render.glsl', funcStart=setupBMeshShader)


def glColor(color):
    if len(color) == 3:
        bgl.glColor3f(*color)
    else:
        bgl.glColor4f(*color)


def glSetDefaultOptions(opts=None):
    bgl.glEnable(bgl.GL_MULTISAMPLE)
    bgl.glEnable(bgl.GL_BLEND)
    bgl.glDisable(bgl.GL_LIGHTING)
    bgl.glEnable(bgl.GL_DEPTH_TEST)
    bgl.glEnable(bgl.GL_POINT_SMOOTH)
    bgl.glEnable(bgl.GL_LINE_SMOOTH)
    bgl.glHint(bgl.GL_LINE_SMOOTH_HINT, bgl.GL_NICEST)


def glEnableStipple(enable=True):
    if enable:
        bgl.glLineStipple(4, 0x5555)
        bgl.glEnable(bgl.GL_LINE_STIPPLE)
    else:
        bgl.glDisable(bgl.GL_LINE_STIPPLE)


# def glEnableBackfaceCulling(enable=True):
#     if enable:
#         bgl.glDisable(bgl.GL_CULL_FACE)
#         bgl.glDepthFunc(bgl.GL_GEQUAL)
#     else:
#         bgl.glDepthFunc(bgl.GL_LEQUAL)
#         bgl.glEnable(bgl.GL_CULL_FACE)


def glSetOptions(prefix, opts):
    if not opts:
        return

    prefix = '%s ' % prefix if prefix else ''

    def set_if_set(opt, cb):
        opt = '%s%s' % (prefix, opt)
        if opt in opts:
            cb(opts[opt])
    dpi_mult = opts.get('dpi mult', 1.0)
    set_if_set('offset', lambda v: bmeshShader.assign('offset', v))
    set_if_set('dotoffset', lambda v: bmeshShader.assign('dotoffset', v))
    set_if_set('color', lambda v: bmeshShader.assign('color', v))
    set_if_set('color selected',
               lambda v: bmeshShader.assign('color_selected', v))
    set_if_set('hidden', lambda v: bmeshShader.assign('hidden', v))
    set_if_set('width', lambda v: bgl.glLineWidth(v*dpi_mult))
    set_if_set('size', lambda v: bgl.glPointSize(v*dpi_mult))
    set_if_set('stipple', lambda v: glEnableStipple(v))


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


def glDrawBMFace(bmf, opts=None, enableShader=True):
    glDrawBMFaces([bmf], opts=opts, enableShader=enableShader)


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


@profiler.profile
def glDrawBMFaces(lbmf, opts=None, enableShader=True):
    opts_ = opts or {}
    nosel = opts_.get('no selection', False)
    mx = opts_.get('mirror x', False)
    my = opts_.get('mirror y', False)
    mz = opts_.get('mirror z', False)
    dn = opts_.get('normal', 0.0)
    vdict = opts_.get('vertex dict', {})

    bmeshShader.assign('focus_mult', opts_.get('focus mult', 1.0))
    bmeshShader.assign('use_selection', 0.0 if nosel else 1.0)

    @profiler.profile
    def render_general(sx, sy, sz):
        bmeshShader.assign('vert_scale', (sx, sy, sz))
        bmeshShader.assign('selected', 0.0)
        for bmf in lbmf:
            bmeshShader.assign('selected', 1.0 if bmf.select else 0.0)
            if bmf.smooth:
                for v0, v1, v2 in triangulateFace(bmf.verts):
                    if v0 not in vdict:
                        vdict[v0] = (v0.co, v0.normal)
                    if v1 not in vdict:
                        vdict[v1] = (v1.co, v1.normal)
                    if v2 not in vdict:
                        vdict[v2] = (v2.co, v2.normal)
                    (c0, n0), (c1, n1), (c2,
                                         n2) = vdict[v0], vdict[v1], vdict[v2]
                    bmeshShader.assign('vert_norm', n0)
                    bmeshShader.assign('vert_pos',  c0)
                    bmeshShader.assign('vert_norm', n1)
                    bmeshShader.assign('vert_pos',  c1)
                    bmeshShader.assign('vert_norm', n2)
                    bmeshShader.assign('vert_pos',  c2)
            else:
                bgl.glNormal3f(*bmf.normal)
                bmeshShader.assign('vert_norm', bmf.normal)
                for v0, v1, v2 in triangulateFace(bmf.verts):
                    if v0 not in vdict:
                        vdict[v0] = (v0.co, v0.normal)
                    if v1 not in vdict:
                        vdict[v1] = (v1.co, v1.normal)
                    if v2 not in vdict:
                        vdict[v2] = (v2.co, v2.normal)
                    (c0, n0), (c1, n1), (c2,
                                         n2) = vdict[v0], vdict[v1], vdict[v2]
                    bmeshShader.assign('vert_pos', c0)
                    bmeshShader.assign('vert_pos', c1)
                    bmeshShader.assign('vert_pos', c2)

    @profiler.profile
    def render_triangles(sx, sy, sz):
        # optimized for triangle-only meshes
        # (source meshes that have been triangulated)
        bmeshShader.assign('vert_scale', (sx, sy, sz))
        bmeshShader.assign('selected', 0.0)
        for bmf in lbmf:
            bmeshShader.assign('selected', 1.0 if bmf.select else 0.0)
            if bmf.smooth:
                v0, v1, v2 = bmf.verts
                if v0 not in vdict:
                    vdict[v0] = (v0.co, v0.normal)
                if v1 not in vdict:
                    vdict[v1] = (v1.co, v1.normal)
                if v2 not in vdict:
                    vdict[v2] = (v2.co, v2.normal)
                (c0, n0), (c1, n1), (c2, n2) = vdict[v0], vdict[v1], vdict[v2]
                bmeshShader.assign('vert_norm', n0)
                bmeshShader.assign('vert_pos',  c0)
                # bgl.glNormal3f(*n0)
                # bgl.glVertex3f(*c0)
                bmeshShader.assign('vert_norm', n1)
                bmeshShader.assign('vert_pos',  c1)
                # bgl.glNormal3f(*n1)
                # bgl.glVertex3f(*c1)
                bmeshShader.assign('vert_norm', n2)
                bmeshShader.assign('vert_pos',  c2)
                # bgl.glNormal3f(*n2)
                # bgl.glVertex3f(*c2)
            else:
                bgl.glNormal3f(*bmf.normal)
                v0, v1, v2 = bmf.verts
                if v0 not in vdict:
                    vdict[v0] = (v0.co, v0.normal)
                if v1 not in vdict:
                    vdict[v1] = (v1.co, v1.normal)
                if v2 not in vdict:
                    vdict[v2] = (v2.co, v2.normal)
                (c0, n0), (c1, n1), (c2, n2) = vdict[v0], vdict[v1], vdict[v2]
                bmeshShader.assign('vert_pos',  c0)
                # bgl.glVertex3f(*c0)
                bmeshShader.assign('vert_pos',  c1)
                # bgl.glVertex3f(*c1)
                bmeshShader.assign('vert_pos',  c2)
                # bgl.glVertex3f(*c2)

    render = render_triangles if opts_.get(
        'triangles only', False) else render_general

    if enableShader:
        bmeshShader.enable()

    glSetOptions('poly', opts)
    bgl.glBegin(bgl.GL_TRIANGLES)
    render(1, 1, 1)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)

    if mx or my or mz:
        glSetOptions('poly mirror', opts)
        bgl.glBegin(bgl.GL_TRIANGLES)
        if mx:
            render(-1,  1,  1)
        if my:
            render(1, -1,  1)
        if mz:
            render(1,  1, -1)
        if mx and my:
            render(-1, -1,  1)
        if mx and mz:
            render(-1,  1, -1)
        if my and mz:
            render(1, -1, -1)
        if mx and my and mz:
            render(-1, -1, -1)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)

    if enableShader:
        bmeshShader.disable()


class BGLBufferedRender:
    DEBUG_PRINT = False
    DEBUG_CHKERR = False

    def __init__(self, gltype):
        self.count = 0
        self.gltype = gltype
        self.gltype_name, self.gl_count, self.options_prefix = {
            bgl.GL_POINTS:   ('points',    1, 'point'),
            bgl.GL_LINES:    ('lines',     2, 'line'),
            bgl.GL_TRIANGLES: ('triangles', 3, 'poly'),
        }[self.gltype]

        # self.vao = bgl.Buffer(bgl.GL_INT, 1)
        # bgl.glGenVertexArrays(1, self.vao)
        # bgl.glBindVertexArray(self.vao[0])

        self.vbos = bgl.Buffer(bgl.GL_INT, 4)
        bgl.glGenBuffers(4, self.vbos)
        self.vbo_pos = self.vbos[0]
        self.vbo_norm = self.vbos[1]
        self.vbo_sel = self.vbos[2]
        self.vbo_idx = self.vbos[3]

        self.render_indices = False

    def __del__(self):
        bgl.glDeleteBuffers(4, self.vbos)
        del self.vbos

    @profiler.profile
    def buffer(self, pos, norm, sel, idx):
        sizeOfFloat, sizeOfInt = 4, 4
        self.count = 0
        count = len(pos)
        counts = list(map(len, [pos, norm, sel]))

        goodcounts = all(c == count for c in counts)
        assert goodcounts, ('All arrays must contain '
                            'the same number of elements %s' % str(counts))

        if count == 0:
            return

        try:
            buf_pos = bgl.Buffer(bgl.GL_FLOAT, [count, 3], pos)
            buf_norm = bgl.Buffer(bgl.GL_FLOAT, [count, 3], norm)
            buf_sel = bgl.Buffer(bgl.GL_FLOAT, count, sel)
            if idx:
                # WHY NO GL_UNSIGNED_INT?????
                buf_idx = bgl.Buffer(bgl.GL_INT, count, idx)
            if self.DEBUG_PRINT:
                print('buf_pos  = ' + shorten_floats(str(buf_pos)))
                print('buf_norm = ' + shorten_floats(str(buf_norm)))
        except Exception as e:
            print(
                'ERROR (buffer): caught exception while '
                'buffering to Buffer ' + str(e))
            raise e
        try:
            bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, self.vbo_pos)
            bgl.glBufferData(bgl.GL_ARRAY_BUFFER, count * 3 *
                             sizeOfFloat, buf_pos,
                             bgl.GL_STATIC_DRAW)
            self._check_error('buffer: vbo_pos')
            bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, self.vbo_norm)
            bgl.glBufferData(bgl.GL_ARRAY_BUFFER, count * 3 *
                             sizeOfFloat, buf_norm,
                             bgl.GL_STATIC_DRAW)
            self._check_error('buffer: vbo_norm')
            bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, self.vbo_sel)
            bgl.glBufferData(bgl.GL_ARRAY_BUFFER, count * 1 *
                             sizeOfFloat, buf_sel,
                             bgl.GL_STATIC_DRAW)
            self._check_error('buffer: vbo_sel')
            if idx:
                bgl.glBindBuffer(bgl.GL_ELEMENT_ARRAY_BUFFER, self.vbo_idx)
                bgl.glBufferData(bgl.GL_ELEMENT_ARRAY_BUFFER,
                                 count * sizeOfInt, buf_idx,
                                 bgl.GL_STATIC_DRAW)
                self._check_error('buffer: vbo_idx')
        except Exception as e:
            print(
                'ERROR (buffer): caught exception while '
                'buffering from Buffer ' + str(e))
            raise e
        finally:
            bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, 0)
            bgl.glBindBuffer(bgl.GL_ELEMENT_ARRAY_BUFFER, 0)
        del buf_pos, buf_norm, buf_sel
        if idx:
            del buf_idx

        if idx:
            self.count = len(idx)
            self.render_indices = True
        else:
            self.count = len(pos)
            self.render_indices = False

    @profiler.profile
    def _check_error(self, title):
        if not self.DEBUG_CHKERR:
            return

        err = bgl.glGetError()
        if err == bgl.GL_NO_ERROR:
            return

        derrs = {
            bgl.GL_INVALID_ENUM: 'invalid enum',
            bgl.GL_INVALID_VALUE: 'invalid value',
            bgl.GL_INVALID_OPERATION: 'invalid operation',
            bgl.GL_STACK_OVERFLOW: 'stack overflow',
            bgl.GL_STACK_UNDERFLOW: 'stack underflow',
            bgl.GL_OUT_OF_MEMORY: 'out of memory',
            bgl.GL_INVALID_FRAMEBUFFER_OPERATION:
                'invalid framebuffer operation',
        }
        if err in derrs:
            print('ERROR (%s): %s' % (title, derrs[err]))
        else:
            print('ERROR (%s): code %d' % (title, err))

    @profiler.profile
    def _draw(self, sx, sy, sz):
        bmeshShader.assign('vert_scale', (sx, sy, sz))
        if self.DEBUG_PRINT:
            print('==> drawing %d %s (%d)  (%d verts)' % (
                self.count / self.gl_count,
                self.gltype_name, self.gltype, self.count))
        if self.render_indices:
            bgl.glDrawElements(self.gltype, self.count,
                               bgl.GL_UNSIGNED_INT, buf_zero)
            self._check_error('_draw: glDrawElements (%d, %d, %d)' % (
                self.gltype, self.count, bgl.GL_UNSIGNED_INT))
        else:
            bgl.glDrawArrays(self.gltype, 0, self.count)
            self._check_error('_draw: glDrawArrays (%d)' % self.count)

    @profiler.profile
    def draw(self, opts):
        if self.count == 0:
            return

        if self.gltype == bgl.GL_LINES:
            if opts.get('line width', 1.0) <= 0:
                return
        elif self.gltype == bgl.GL_POINTS:
            if opts.get('point size', 1.0) <= 0:
                return

        nosel = opts.get('no selection', False)
        mx, my, mz = opts.get('mirror x', False), opts.get(
            'mirror y', False), opts.get('mirror z', False)
        focus = opts.get('focus mult', 1.0)

        bmeshShader.assign('focus_mult', focus)
        bmeshShader.assign('use_selection', 0.0 if nosel else 1.0)
        bmeshShader.assign('cull_backfaces', 1.0 if opts.get('cull backfaces', False) else 0.0)
        bmeshShader.assign('alpha_backface', opts.get('alpha backface', 0.5))
        bmeshShader.assign('normal_offset', opts.get('normal offset', 0.0))

        bmeshShader.vertexAttribPointer(
            self.vbo_pos,  'vert_pos',  3, bgl.GL_FLOAT, buf=buf_zero)
        self._check_error('draw: vertex attrib array pos')
        bmeshShader.vertexAttribPointer(
            self.vbo_norm, 'vert_norm', 3, bgl.GL_FLOAT, buf=buf_zero)
        self._check_error('draw: vertex attrib array norm')
        bmeshShader.vertexAttribPointer(
            self.vbo_sel,  'selected',  1, bgl.GL_FLOAT, buf=buf_zero)
        self._check_error('draw: vertex attrib array sel')
        bgl.glBindBuffer(bgl.GL_ELEMENT_ARRAY_BUFFER, self.vbo_idx)
        self._check_error('draw: element array buffer idx')

        glSetOptions(self.options_prefix, opts)
        self._draw(1, 1, 1)

        if mx or my or mz:
            glSetOptions('%s mirror' % self.options_prefix, opts)
            if mx:
                self._draw(-1,  1,  1)
            if my:
                self._draw(1, -1,  1)
            if mz:
                self._draw(1,  1, -1)
            if mx and my:
                self._draw(-1, -1,  1)
            if mx and mz:
                self._draw(-1,  1, -1)
            if my and mz:
                self._draw(1, -1, -1)
            if mx and my and mz:
                self._draw(-1, -1, -1)

        bmeshShader.disableVertexAttribArray('vert_pos')
        bmeshShader.disableVertexAttribArray('vert_norm')
        bmeshShader.disableVertexAttribArray('selected')
        bgl.glBindBuffer(bgl.GL_ELEMENT_ARRAY_BUFFER, 0)
        bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, 0)


@profiler.profile
def glDrawSimpleFaces(lsf, opts=None, enableShader=True):
    opts_ = opts or {}
    nosel = opts_.get('no selection', False)
    mx = opts_.get('mirror x', False)
    my = opts_.get('mirror y', False)
    mz = opts_.get('mirror z', False)
    dn = opts_.get('normal', 0.0)

    bmeshShader.assign('focus_mult', opts_.get('focus mult', 1.0))
    bmeshShader.assign('use_selection', 0.0 if nosel else 1.0)
    bmeshShader.assign('selected', 0.0)

    @profiler.profile
    def render(sx, sy, sz):
        bmeshShader.assign('vert_scale', (sx, sy, sz))
        for sf in lsf:
            for v0, v1, v2 in triangulateFace(sf):
                (c0, n0), (c1, n1), (c2, n2) = v0, v1, v2
                bgl.glNormal3f(*n0)
                bgl.glVertex3f(*c0)
                bgl.glNormal3f(*n1)
                bgl.glVertex3f(*c1)
                bgl.glNormal3f(*n2)
                bgl.glVertex3f(*c2)

    if enableShader:
        bmeshShader.enable()

    glSetOptions('poly', opts)
    bgl.glBegin(bgl.GL_TRIANGLES)
    render(1, 1, 1)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)

    if mx or my or mz:
        glSetOptions('poly mirror', opts)
        bgl.glBegin(bgl.GL_TRIANGLES)
        if mx:
            render(-1,  1,  1)
        if my:
            render(1, -1,  1)
        if mz:
            render(1,  1, -1)
        if mx and my:
            render(-1, -1,  1)
        if mx and mz:
            render(-1,  1, -1)
        if my and mz:
            render(1, -1, -1)
        if mx and my and mz:
            render(-1, -1, -1)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)

    if enableShader:
        bmeshShader.disable()


def glDrawBMFaceEdges(bmf, opts=None, enableShader=True):
    glDrawBMEdges(bmf.edges, opts=opts, enableShader=enableShader)


def glDrawBMFaceVerts(bmf, opts=None, enableShader=True):
    glDrawBMVerts(bmf.verts, opts=opts, enableShader=enableShader)


def glDrawBMEdge(bme, opts=None, enableShader=True):
    glDrawBMEdges([bme], opts=opts, enableShader=enableShader)


@profiler.profile
def glDrawBMEdges(lbme, opts=None, enableShader=True):
    opts_ = opts or {}
    if opts_.get('line width', 1.0) <= 0.0:
        return
    nosel = opts_.get('no selection', False)
    mx = opts_.get('mirror x', False)
    my = opts_.get('mirror y', False)
    mz = opts_.get('mirror z', False)
    dn = opts_.get('normal', 0.0)
    vdict = opts_.get('vertex dict', {})

    bmeshShader.assign('use_selection', 0.0 if nosel else 1.0)

    @profiler.profile
    def render(sx, sy, sz):
        bmeshShader.assign('vert_scale', (sx, sy, sz))
        for bme in lbme:
            bmeshShader.assign('selected', 1.0 if bme.select else 0.0)
            v0, v1 = bme.verts
            if v0 not in vdict:
                vdict[v0] = (v0.co, v0.normal)
            if v1 not in vdict:
                vdict[v1] = (v1.co, v1.normal)
            (c0, n0), (c1, n1) = vdict[v0], vdict[v1]
            c0, c1 = c0+n0*dn, c1+n1*dn
            bmeshShader.assign('vert_norm', n0)
            bmeshShader.assign('vert_pos',  c0)
            # bgl.glVertex3f(0,0,0)
            bmeshShader.assign('vert_norm', n1)
            bmeshShader.assign('vert_pos',  c1)
            # bgl.glVertex3f(0,0,0)

    if enableShader:
        bmeshShader.enable()

    glSetOptions('line', opts)
    bgl.glBegin(bgl.GL_LINES)
    render(1, 1, 1)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)

    if mx or my or mz:
        glSetOptions('line mirror', opts)
        bgl.glBegin(bgl.GL_LINES)
        if mx:
            render(-1,  1,  1)
        if my:
            render(1, -1,  1)
        if mz:
            render(1,  1, -1)
        if mx and my:
            render(-1, -1,  1)
        if mx and mz:
            render(-1,  1, -1)
        if my and mz:
            render(1, -1, -1)
        if mx and my and mz:
            render(-1, -1, -1)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)

    if enableShader:
        bmeshShader.disable()


def glDrawBMEdgeVerts(bme, opts=None, enableShader=True):
    glDrawBMVerts(bme.verts, opts=opts, enableShader=enableShader)


def glDrawBMVert(bmv, opts=None, enableShader=True):
    glDrawBMVerts([bmv], opts=opts, enableShader=enableShader)


@profiler.profile
def glDrawBMVerts(lbmv, opts=None, enableShader=True):
    opts_ = opts or {}
    if opts_.get('point size', 1.0) <= 0.0:
        return
    nosel = opts_.get('no selection', False)
    mx = opts_.get('mirror x', False)
    my = opts_.get('mirror y', False)
    mz = opts_.get('mirror z', False)
    dn = opts_.get('normal', 0.0)
    vdict = opts_.get('vertex dict', {})

    if enableShader:
        bmeshShader.enable()
    bmeshShader.assign('use_selection', 0.0 if nosel else 1.0)

    @profiler.profile
    def render(sx, sy, sz):
        bmeshShader.assign('vert_scale', Vector((sx, sy, sz)))
        for bmv in lbmv:
            bmeshShader.assign('selected', 1.0 if bmv.select else 0.0)
            if bmv not in vdict:
                vdict[bmv] = (bmv.co, bmv.normal)
            c, n = vdict[bmv]
            c = c + dn * n
            bmeshShader.assign('vert_norm', n)
            bmeshShader.assign('vert_pos',  c)
            # bgl.glNormal3f(*n)
            # bgl.glVertex3f(*c)

    glSetOptions('point', opts)
    bgl.glBegin(bgl.GL_POINTS)
    render(1, 1, 1)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)

    if mx or my or mz:
        glSetOptions('point mirror', opts)
        bgl.glBegin(bgl.GL_POINTS)
        if mx:
            render(-1,  1,  1)
        if my:
            render(1, -1,  1)
        if mz:
            render(1,  1, -1)
        if mx and my:
            render(-1, -1,  1)
        if mx and mz:
            render(-1,  1, -1)
        if my and mz:
            render(1, -1, -1)
        if mx and my and mz:
            render(-1, -1, -1)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)

    if enableShader:
        bmeshShader.disable()


class BMeshRender():
    @profiler.profile
    def __init__(
        self, target_obj,
        target_mx=None, source_bvh=None, source_mx=None
    ):
        self.calllist = None
        if type(target_obj) is bpy.types.Object:
            print('Creating BMeshRender for ' + target_obj.name)
            self.tar_bmesh = bmesh.new()
            self.tar_bmesh.from_object(
                target_obj, bpy.context.scene, deform=True)
            self.tar_mx = target_mx or target_obj.matrix_world
        elif type(target_obj) is bmesh.types.BMesh:
            self.tar_bmesh = target_obj
            self.tar_mx = target_mx or Matrix()
        else:
            assert False, 'Unhandled type: ' + str(type(target_obj))

        self.src_bvh = source_bvh
        self.src_mx = source_mx or Matrix()
        self.src_imx = invert_matrix(self.src_mx)
        self.src_mxnorm = matrix_normal(self.src_mx)

        self.bglMatrix = bgl.Buffer(bgl.GL_FLOAT, [16])
        for i, v in enumerate(
            v for r in self.tar_mx.transposed() for v in r
        ):
            self.bglMatrix[i] = v

        self.is_dirty = True
        self.calllist = bgl.glGenLists(1)

    def replace_target_bmesh(self, target_bmesh):
        self.tar_bmesh = target_bmesh
        self.is_dirty = True

    def __del__(self):
        if self.calllist:
            bgl.glDeleteLists(self.calllist, 1)
            self.calllist = None

    def dirty(self):
        self.is_dirty = True

    @profiler.profile
    def clean(self, opts=None):
        if not self.is_dirty:
            return

        # make not dirty first in case bad things happen while drawing
        self.is_dirty = False

        if self.src_bvh:
            # normal_update() will destroy normals of
            # verts not connected to faces :(
            self.tar_bmesh.normal_update()
            for bmv in self.tar_bmesh.verts:
                if len(bmv.link_faces) != 0:
                    continue
                _, n, _, _ = self.src_bvh.find_nearest(self.src_imx * bmv.co)
                bmv.normal = (self.src_mxnorm * n).normalized()

        bgl.glNewList(self.calllist, bgl.GL_COMPILE)
        # do not change attribs if they're not set
        glSetDefaultOptions(opts=opts)
        # bgl.glPushMatrix()
        # bgl.glMultMatrixf(self.bglMatrix)
        glDrawBMFaces(self.tar_bmesh.faces, opts=opts, enableShader=False)
        glDrawBMEdges(self.tar_bmesh.edges, opts=opts, enableShader=False)
        glDrawBMVerts(self.tar_bmesh.verts, opts=opts, enableShader=False)
        bgl.glDepthRange(0, 1)
        # bgl.glPopMatrix()
        bgl.glEndList()

    @profiler.profile
    def draw(self, opts=None):
        try:
            self.clean(opts=opts)
            bmeshShader.enable()
            bgl.glCallList(self.calllist)
        except:
            pass
        finally:
            bmeshShader.disable()
