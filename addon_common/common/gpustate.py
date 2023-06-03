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


#######################################################################
# THE FOLLOWING FUNCTIONS ARE ONLY FOR THE TRANSITION FROM BGL TO GPU #
# THIS FILE **SHOULD** GO AWAY ONCE WE DROP SUPPORT FOR BLENDER 2.83  #
# AROUND JUNE 2023 AS BLENDER 2.93 HAS GPU MODULE                     #
#######################################################################


import re
import traceback
from inspect import isroutine
from itertools import chain
from contextlib import contextmanager

import bpy
import gpu

from .decorators import only_in_blender_version, warn_once, add_cache



# note: not all supported by user system, but we don't need full functionality
# https://en.wikipedia.org/wiki/OpenGL_Shading_Language#Versions
#     OpenGL  GLSL    OpenGL  GLSL
#      2.0    110      4.0    400
#      2.1    120      4.1    410
#      3.0    130      4.2    420
#      3.1    140      4.3    430
#      3.2    150      4.4    440
#      3.3    330      4.5    450
#                      4.6    460


if bpy.app.version < (3,4,0):
    use_bgl_default = True
    use_gpu_default = False
else:
    use_bgl_default = False # gpu.platform.backend_type_get() in {'OPENGL',}
    use_gpu_default = True  # not use_bgl_default

def blend(mode, *, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl:
        import bgl
        if mode == 'NONE':
            bgl.glDisable(bgl.GL_BLEND)
        else:
            bgl.glEnable(bgl.GL_BLEND)
            map_mode_bgl = {
                'ALPHA':            (bgl.GL_SRC_ALPHA,           bgl.GL_ONE_MINUS_SRC_ALPHA),
                'ALPHA_PREMULT':    (bgl.GL_ONE,                 bgl.GL_ONE_MINUS_SRC_ALPHA),
                'ADDITIVE':         (bgl.GL_SRC_ALPHA,           bgl.GL_ONE),
                'ADDITIVE_PREMULT': (bgl.GL_ONE,                 bgl.GL_ONE),
                'MULTIPLY':         (bgl.GL_DST_COLOR,           bgl.GL_ZERO),
                'SUBTRACT':         (bgl.GL_ONE,                 bgl.GL_ONE),
                'INVERT':           (bgl.GL_ONE_MINUS_DST_COLOR, bgl.GL_ZERO),
            }
            bgl.glBlendFunc(*map_mode_bgl[mode])
    if use_gpu:
        gpu.state.blend_set(mode)


def depth_test(mode, *, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl:
        import bgl
        if mode == 'NONE':
            bgl.glDisable(bgl.GL_DEPTH_TEST)
        else:
            bgl.glEnable(bgl.GL_DEPTH_TEST)
            map_mode_bgl = {
                'NEVER':         bgl.GL_NEVER,
                'LESS':          bgl.GL_LESS,
                'EQUAL':         bgl.GL_EQUAL,
                'LESS_EQUAL':    bgl.GL_LEQUAL,
                'GREATER':       bgl.GL_GREATER,
                'GREATER_EQUAL': bgl.GL_GEQUAL,
                'ALWAYS':        bgl.GL_ALWAYS,
                # NOTE: no equivalent for `bgl.GL_NOTEQUAL` in `gpu` module as of Blender 3.5.1
            }
            bgl.glDepthFunc(map_mode_bgl[mode])
    if use_gpu:
        gpu.state.depth_test_set(mode)
def get_depth_test(*, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl:
        return bgl_get_integerv('GL_DEPTH_FUNC')
    if use_gpu:
        return gpu.state.depth_test_get()

def depth_mask(enable, *, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl:
        import bgl
        bgl.glDepthMask(bgl.GL_TRUE if enable else bgl.GL_FALSE)
    if use_gpu:
        gpu.state.depth_mask_set(enable)
def get_depth_mask(*, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl:
        return bgl_get_integerv('GL_DEPTH_WRITEMASK')
    if use_gpu:
        return gpu.state.depth_mask_get()


def scissor(left, bottom, width, height, *, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl or True:
        import bgl
        bgl.glScissor(left, bottom, width, height)
    if use_gpu and False:
        gpu.state.scissor_set(left, bottom, width, height)
def get_scissor(*, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl or True:
        return bgl_get_integerv_tuple('GL_SCISSOR_BOX', 4)
    if use_gpu and False:
        return gpu.state.scissor_get()

def scissor_test(enable, *, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl or True:
        bgl_enable('GL_SCISSOR_TEST', enable)
    if use_gpu and False:
        gpu.state.scissor_test_set(enable)
def get_scissor_test(*, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl or True:
        return bgl_is_enabled('GL_SCISSOR_TEST')
    if use_gpu and False:
        # NOTE: no equivalent in `gpu` module as of Blender 3.5.1
        # return gpu.state.scissor_test_get()
        return False

def culling(mode, *, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl:
        import bgl
        if mode == 'NONE':
            bgl.glDisable(bgl.GL_CULL_FACE)
        else:
            bgl.glEnable(bgl.GL_CULL_FACE)
            map_mode_bgl = {
                'FRONT': bgl.GL_FRONT,
                'BACK':  bgl.GL_BACK,
            }
            bgl.glCullFace(map_mode_bgl[mode])
    if use_gpu:
        gpu.state.face_culling_set(mode)


#########################
# opengl errors

@add_cache('_error_check', True)
@add_cache('_error_count', 0)
@add_cache('_error_limit', 10)
def get_glerror(title, *, use_bgl=use_bgl_default):
    if not use_bgl:
        # NOTE: no equivalent in `gpu` module as of Blender 3.5.1
        return False
    if not get_glerror._error_check: return
    import bgl
    err = bgl.glGetError()
    if err == bgl.GL_NO_ERROR:
        return False
    get_glerror._error_count += 1
    if get_glerror._error_count >= get_glerror._error_limit:
        return True
    error_map = {
        getattr(bgl, k): s
        for (k,s) in [
            # https://www.khronos.org/opengl/wiki/OpenGL_Error#Meaning_of_errors
            ('GL_INVALID_ENUM', 'invalid enum'),
            ('GL_INVALID_VALUE', 'invalid value'),
            ('GL_INVALID_OPERATION', 'invalid operation'),
            ('GL_STACK_OVERFLOW', 'stack overflow'),    # does not exist in b3d 2.8x for OSX??
            ('GL_STACK_UNDERFLOW', 'stack underflow'),  # does not exist in b3d 2.8x for OSX??
            ('GL_OUT_OF_MEMORY', 'out of memory'),
            ('GL_INVALID_FRAMEBUFFER_OPERATION', 'invalid framebuffer operation'),
            ('GL_CONTEXT_LOST', 'context lost'),
            ('GL_TABLE_TOO_LARGE', 'table too large'),  # deprecated in OpenGL 3.0, removed in 3.1 core and above
        ]
        if hasattr(bgl, k)
    }
    print(f'ERROR {get_glerror._error_count}/{get_glerror._error_limit} ({title}): {error_map.get(err, f"code {err}")}')
    traceback.print_stack()
    return True



#######################################
# shader

def clean_shader_source(source):
    source = source + '\n'
    source = re.sub(r'/[*](\n|.)*?[*]/', '', source)
    source = re.sub(r'//.*?\n', '\n', source)
    source = re.sub(r'\n+', '\n', source)
    # source = '\n'.join(l.strip() for l in source.splitlines())
    return source

re_shader_var = re.compile(r'^[ \n]*((?P<qualifier>noperspective|flat|smooth)[ \n]+)?(?P<uio>uniform|in|out)[ \n]+(?P<type>mat4|mat3|mat2|vec4|vec3|vec2|float|sampler2D|int|bool)[ \n]+(?P<var>[a-zA-Z0-9_]+)(?P<defval>=.*)?[ \n]*$')
def split_shader_vars(source):
    shader_vars = {}
    parts = []
    for part in source.split(';'):
        m = re_shader_var.match(part)
        if m:
            shader_vars[m['var']] = {
                'uio':       m['uio'],
                'qualifier': m['qualifier'],
                'type':      m['type'].upper(),
                'var':       m['var'],
                'defval':    m['defval'],
            }
        else:
            parts.append(part)
    return shader_vars, ';'.join(parts)

def gpu_shader(vert_source, frag_source, *, defines=None):
    vert_source = clean_shader_source(vert_source)
    frag_source = clean_shader_source(frag_source)
    vert_shader_vars, vert_source = split_shader_vars(vert_source)
    frag_shader_vars, frag_source = split_shader_vars(frag_source)
    shader_vars = vert_shader_vars | frag_shader_vars

    if True:
        print('GPUShader')
        print('_'*100)
        print(vert_source)
        print('~'*100)
        print(frag_source)
        print('='*100)
        for vn in shader_vars:
            print(f'{vn}:{shader_vars[vn]}')
        print('^'*100)
        print()

    shader_info = gpu.types.GPUShaderCreateInfo()

    # UNIFORMS
    slot = 0
    for shader_var in shader_vars.values():
        if shader_var['uio'] != 'uniform': continue
        if shader_var['type'] == 'SAMPLER2D':
            shader_info.sampler(slot, 'FLOAT_2D', shader_var['var'])
            slot += 1
        else:
            shader_info.push_constant(shader_var['type'], shader_var['var'])

    # PREPROCESSING DEFINE DIRECTIVES
    if defines:
        for k,v in defines.items():
            shader_info.define(str(k), str(v))

    # INPUTS
    slot = 0
    for shader_var in vert_shader_vars.values():
        if shader_var['uio'] == 'in':
            shader_info.vertex_in(slot, shader_var['type'], shader_var['var'])
            slot += 1

    # INTERFACE
    shader_interface = gpu.types.GPUStageInterfaceInfo('foobar') # NOTE: DO NOT CALL IT interface
    needs_interface = False
    for shader_var in vert_shader_vars.values():
        if shader_var['uio'] != 'out': continue
        if shader_var['qualifier'] == 'noperspective':
            shader_interface.no_perspective(shader_var['type'], shader_var['var'])
            needs_interface = True
        elif shader_var['qualifier'] == 'flat':
            shader_interface.flat(shader_var['type'], shader_var['var'])
            needs_interface = True
        elif shader_var['qualifier'] == 'smooth':
            shader_interface.smooth(shader_var['type'], shader_var['var'])
            needs_interface = True
        else:
            shader_interface.smooth(shader_var['type'], shader_var['var'])
            needs_interface = True
    if needs_interface:
        shader_info.vertex_out(shader_interface)

    # OUTPUTS
    slot = 0
    for shader_var in frag_shader_vars.values():
        if shader_var['uio'] == 'out':
            shader_info.fragment_out(slot, shader_var['type'], shader_var['var'])
            slot += 1

    shader_info.vertex_source(vert_source)
    shader_info.fragment_source(frag_source)

    shader = gpu.shader.create_from_info(shader_info)
    del shader_interface
    del shader_info
    return shader

    # return gpu.types.GPUShader(vert_source, frag_source)



#######################################
# gather gpu information

# https://www.khronos.org/registry/OpenGL-Refpages/gl2.1/xhtml/glGetString.xml
@only_in_blender_version('< 3.0')
def gpu_info():
    import bgl
    return {
        'vendor':   bgl.glGetString(bgl.GL_VENDOR),
        'renderer': bgl.glGetString(bgl.GL_RENDERER),
        'version':  bgl.glGetString(bgl.GL_VERSION),
        'shading':  bgl.glGetString(bgl.GL_SHADING_LANGUAGE_VERSION),
    }

@only_in_blender_version('>= 3.0', '< 3.4')
def gpu_info():
    return {
        'vendor':   gpu.platform.vendor_get(),
        'renderer': gpu.platform.renderer_get(),
        'version':  gpu.platform.version_get(),
    }

@only_in_blender_version('>= 3.4')
def gpu_info():
    platform = {
        'backend':  gpu.platform.backend_type_get(),
        'device':   gpu.platform.device_type_get(),
        'vendor':   gpu.platform.vendor_get(),
        'renderer': gpu.platform.renderer_get(),
        'version':  gpu.platform.version_get(),
    }
    cap = [(a, getattr(gpu.capabilities, a)) for a in dir(gpu.capabilities) if 'extensions' not in a]
    cap = [(a, fn) for (a, fn) in cap if isroutine(fn)]
    capabilities = {
        a: fn() for (a, fn) in cap
    }
    return platform | capabilities

if not bpy.app.background:
    print(f'Addon Common: {gpu_info()}')


####################################
# helper functions

@contextmanager
@add_cache('_buffers', dict())
def bgl_get_temp_buffer(type_str, size):
    import bgl
    bufs, key = bgl_get_temp_buffer._buffers, (type_str, size)
    if key not in bufs:
        bufs[key] = bgl.Buffer(getattr(bgl, type_str), size)
    yield bufs[key]

def bgl_get_integerv(pname_str, *, type_str='GL_INT'):
    import bgl
    with bgl_get_temp_buffer(type_str, 1) as buf:
        bgl.glGetIntegerv(getattr(bgl, pname_str), buf)
        return buf[0]

def bgl_get_integerv_tuple(pname_str, size, *, type_str='GL_INT'):
    import bgl
    with bgl_get_temp_buffer(type_str, size) as buf:
        bgl.glGetIntegerv(getattr(bgl, pname_str), buf)
        return tuple(buf)

def bgl_is_enabled(pname_str):
    import bgl
    return (bgl.glIsEnabled(getattr(bgl, pname_str)) == bgl.GL_TRUE)

def bgl_enable(pname_str, enabled):
    import bgl
    pname = getattr(bgl, pname_str)
    if enabled: bgl.glEnable(pname)
    else:       bgl.glDisable(pname)

