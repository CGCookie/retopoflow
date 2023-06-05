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

from mathutils import Matrix, Vector

from .decorators import only_in_blender_version, warn_once, add_cache
from .utils import Dict


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

re_shader_var = re.compile(r'((?P<qualifier>noperspective|flat|smooth)[ \n]+)?(?P<uio>uniform|in|out)[ \n]+(?P<type>[a-zA-Z0-9_]+)[ \n]+(?P<var>[a-zA-Z0-9_]+)([ \n]*=[ \n]*(?P<defval>[^;]+))?[ \n]*;')
re_shader_var_parts = ['qualifier', 'uio', 'type', 'var', 'defval']
def split_shader_vars(source):
    shader_vars = {
        m['var']: { part: m[part] for part in re_shader_var_parts }
        for m in re_shader_var.finditer(source)
    }
    source = re_shader_var.sub('', source)
    source = '\n'.join(l for l in source.splitlines() if l.strip())
    return (shader_vars, source)

re_struct = re.compile(r'struct[ \n]+(?P<name>[a-zA-Z0-9_]+)[ \n]+[{](?P<attribs>[^}]+)[}][ \n]*;')
re_attrib = re.compile(r'(?P<type>[a-zA-Z0-9_]+)[ \n]+(?P<name>[a-zA-Z0-9_]+)[ \n]*;')
def split_shader_structs(source):
    structs = {
        m['name']: {
            'name': m['name'],
            'full': m.group(0),
            'attribs': [(ma['type'], ma['name']) for ma in re_attrib.finditer(m['attribs'])],
            'type': {ma['name']: ma['type'] for ma in re_attrib.finditer(m['attribs'])},
        }
        for m in re_struct.finditer(source)
    }
    source = re_struct.sub('', source)
    source = '\n'.join(l for l in source.splitlines() if l.strip())
    return (structs, source)

def shader_var_to_ctype(shader_type, shader_varname):
    return (shader_varname, shader_type_to_ctype(shader_type))

def shader_type_to_ctype(shader_type):
    import ctypes
    match shader_type:
        case 'mat4':  return (ctypes.c_float * 4) * 4
        case 'mat3':  return (ctypes.c_float * 3) * 3
        case 'vec4':  return ctypes.c_float * 4
        case 'vec3':  return ctypes.c_float * 3
        case 'vec2':  return ctypes.c_float * 2
        case 'float': return ctypes.c_float
        case 'ivec4': return ctypes.c_int * 4
        case 'ivec3': return ctypes.c_int * 3
        case 'ivec2': return ctypes.c_int * 2
        case 'int':   return ctypes.c_int
        case 'bool':  return ctypes.c_bool
        case _:       assert False, f'Unhandled shader type {shader_type}'

def shader_struct_to_UBO(shadername, struct, varname):
    import ctypes
    # copied+modified from mesh_snap_utitilies_line/drawing_utilities.py
    class GPU_UBO(ctypes.Structure):
        _pack_ = 16
        _fields_ = [ shader_var_to_ctype(t, n) for (t, n) in struct['attribs'] ]
    ubo_data = GPU_UBO()
    ubo_data_size = ctypes.sizeof(ubo_data)
    if ubo_data_size % 16 != 0:
        print(f'AddonCommon: WARNING')
        print(f'Shader {shadername}')
        print(f'Struct {struct["name"]} for variable {varname}')
        print(f'Size={ubo_data_size}, which is not a multiple of 16 (mod16={ubo_data_size%16})')
        print(f'Need {16 - (ubo_data_size%16)} more bytes')
    ubo = gpu.types.GPUUniformBuf(gpu.types.Buffer('UBYTE', ubo_data_size, ubo_data))
    def setter(name, value):
        # print(f'UBO_Wrapper.set {name} = {value} ({type(value)})')
        shader_type = struct['type'][name]
        match shader_type:
            case 'mat4':
                a = getattr(ubo_data, name)
                CType = shader_type_to_ctype('vec4')
                if len(value) == 3: value = value.to_4x4()
                a[0] = CType(value[0][0], value[1][0], value[2][0], value[3][0])
                a[1] = CType(value[0][1], value[1][1], value[2][1], value[3][1])
                a[2] = CType(value[0][2], value[1][2], value[2][2], value[3][2])
                a[3] = CType(value[0][3], value[1][3], value[2][3], value[3][3])
            case 'mat3':
                a = getattr(ubo_data, name)
                CType = shader_type_to_ctype('vec3')
                a[0] = CType(value[0][0], value[1][0], value[2][0])
                a[1] = CType(value[0][1], value[1][1], value[2][1])
                a[2] = CType(value[0][2], value[1][2], value[2][2])
            case 'vec4'|'vec3'|'vec2'|'ivec4'|'ivec3'|'ivec2':
                CType = shader_type_to_ctype(shader_type)
                setattr(ubo_data, name, CType(*value))
            case 'float'|'int'|'bool':
                CType = shader_type_to_ctype(shader_type)
                setattr(ubo_data, name, CType(value))
    class UBO_Wrapper:
        def __init__(self):
            pass
        def set_shader(self, shader):
            self.__dict__['_shader'] = shader
        def __setattr__(self, name, value):
            self.assign(name, value)
        def assign(self, name, value):
            try:
                setter(name, value)
            except Exception as e:
                print(f'Caught Exception while trying to set {name} = {value}')
                print(f'  Shader:    {shadername}')
                print(f'  Exception: {e}')
        def update_shader(self, *, debug_print=False):
            try:
                if debug_print:
                    print(f'UPDATING SHADER: {shadername} {varname}')
                shader = self.__dict__['_shader']
                buf = gpu.types.Buffer('UBYTE', ubo_data_size, ubo_data)
                if debug_print:
                    print(buf)
                ubo.update(buf)
                shader.uniform_block(varname, ubo)
                del buf
            except Exception as e:
                print(f'Caught Exception while trying to update shader')
                print(f'  Shader:    {shadername}')
                print(f'  Struct:    {struct["name"]}')
                print(f'  Variable:  {varname}')
                print(f'  Exception: {e}')
    return UBO_Wrapper()

gpu_type_size = {
    'bool',
    'uint',  'uvec2', 'uvec3', 'uvec4',
    'int',   'ivec2', 'ivec3', 'ivec4',
    'float', 'vec2',  'vec3',  'vec4',
                      'mat3',  'mat4',
}
def glsl_to_gpu_type(t):
    if t in gpu_type_size:
        return t.upper()
    return t

def gpu_shader(name, vert_source, frag_source, *, defines=None):
    vert_source, frag_source = map(clean_shader_source, (vert_source, frag_source))
    vert_shader_structs, vert_source = split_shader_structs(vert_source)
    frag_shader_structs, frag_source = split_shader_structs(frag_source)
    shader_structs = vert_shader_structs | frag_shader_structs
    vert_shader_vars, vert_source = split_shader_vars(vert_source)
    frag_shader_vars, frag_source = split_shader_vars(frag_source)
    shader_vars = vert_shader_vars | frag_shader_vars

    if False:
        print(f'')
        print(f'GPUShader {name}')
        print(f'v'*100)
        print(vert_source)
        print(f'~'*100)
        print(frag_source)
        print(f'='*100)
        for ss in vert_shader_structs.values():
            print(ss['full'])
        print(f'='*100)
        def nonetoempty(s): return s if s else ''
        print(f'{"Qualifier":13s} {"UIO":7s} {"Type":10s} {"Var Name":20s} {"Def Val"}')
        for sv in shader_vars.values():
            print(
                f'{nonetoempty(sv["qualifier"]):13s} '  # noperspective
                f'{nonetoempty(sv["uio"]):7s} '         # uniform
                f'{nonetoempty(sv["type"]):10s} '
                f'{nonetoempty(sv["var"]):20s} '
                f'{nonetoempty(sv["defval"])}'
            )
        print(f'^'*100)
        print()

    shader_info = gpu.types.GPUShaderCreateInfo()

    # STRUCTS
    # Note: as of 2023.06.04, multiple structs caused compiler errors that were difficult to debug.
    #       I believe it is due to how Blender constructs the platform-specific shader from the GPU shader.
    assert len(shader_structs) <= 1, f'Cannot support shaders with more than one struct, found {len(shader_structs)} in {name}'
    for struct in shader_structs.values():
        # print(f'typedef_source("{struct["full"]}")')
        shader_info.typedef_source(struct['full'])
    UBOs = Dict()
    def update_shader(*, debug_print=False):
        for n in UBOs:
            if n in ['update_shader', 'set_shader']: continue
            UBOs[n].update_shader(debug_print=debug_print)
    UBOs.update_shader = update_shader
    def set_shader(shader):
        for n in UBOs:
            if n in ['update_shader', 'set_shader']: continue
            UBOs[n].set_shader(shader)
    UBOs.set_shader = set_shader

    slot_buffer = 0
    slot_image = 0
    slot_input = 0
    slot_output = 0

    # UNIFORMS
    for shader_var in shader_vars.values():
        if shader_var['uio'] != 'uniform': continue
        match shader_var['type']:
            case 'sampler2D':
                shader_info.sampler(slot_image, 'FLOAT_2D', shader_var['var'])
                slot_image += 1
            case t if t in gpu_type_size:
                shader_info.push_constant(glsl_to_gpu_type(shader_var['type']), shader_var['var'])
            case _:
                shader_info.uniform_buf(slot_buffer, shader_var['type'], shader_var['var'])
                ubo_wrapper = shader_struct_to_UBO(name, shader_structs[shader_var['type']], shader_var['var'])
                UBOs[shader_var['var']] = ubo_wrapper
                slot_buffer += 1
    if False:
        print(UBOs)

    # PREPROCESSING DEFINE DIRECTIVES
    if defines:
        for k,v in defines.items():
            shader_info.define(str(k), str(v))

    # INPUTS
    for shader_var in vert_shader_vars.values():
        if shader_var['uio'] == 'in':
            shader_info.vertex_in(slot_input, glsl_to_gpu_type(shader_var['type']), shader_var['var'])
            slot_input += 1

    # INTERFACE
    shader_interface = gpu.types.GPUStageInterfaceInfo('shader_interface') # NOTE: DO NOT CALL IT `interface`
    qualified_fns = {
        'noperspective': shader_interface.no_perspective,
        'flat':          shader_interface.flat,
        'smooth':        shader_interface.smooth,
        None:            shader_interface.smooth,
    }
    needs_interface = False
    for shader_var in vert_shader_vars.values():
        if shader_var['uio'] != 'out': continue
        needs_interface = True
        qualified_fn = qualified_fns[shader_var['qualifier']]
        qualified_fn(glsl_to_gpu_type(shader_var['type']), shader_var['var'])
    if needs_interface:
        shader_info.vertex_out(shader_interface)

    # OUTPUTS
    for shader_var in frag_shader_vars.values():
        if shader_var['uio'] != 'out': continue
        # if shader_var['var'] == 'gl_FragDepth': continue
        shader_info.fragment_out(slot_output, glsl_to_gpu_type(shader_var['type']), shader_var['var'])
        slot_output += 1

    shader_info.vertex_source(vert_source)
    shader_info.fragment_source(frag_source)

    shader = gpu.shader.create_from_info(shader_info)
    UBOs.set_shader(shader)
    del shader_interface
    del shader_info
    return shader, UBOs

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

