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
from .maths import mid
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
    use_gpu_scissor = False
elif bpy.app.version < (3,5,1):
    use_bgl_default = False # gpu.platform.backend_type_get() in {'OPENGL',}
    use_gpu_default = True  # not use_bgl_default
    use_gpu_scissor = False
else:
    use_bgl_default = False # gpu.platform.backend_type_get() in {'OPENGL',}
    use_gpu_default = True  # not use_bgl_default
    use_gpu_scissor = False

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
    if use_bgl or (not use_gpu_scissor):
        import bgl
        bgl.glScissor(left, bottom, width, height)
    if use_gpu and use_gpu_scissor:
        gpu.state.scissor_set(left, bottom, width, height)
def get_scissor(*, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl or (not use_gpu_scissor):
        return bgl_get_integerv_tuple('GL_SCISSOR_BOX', 4)
    if use_gpu and use_gpu_scissor:
        return gpu.state.scissor_get()

def scissor_test(enable, *, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl or (not use_gpu_scissor):
        bgl_enable('GL_SCISSOR_TEST', enable)
    if use_gpu and use_gpu_scissor:
        gpu.state.scissor_test_set(enable)
def get_scissor_test(*, use_gpu=use_gpu_default, use_bgl=use_bgl_default):
    assert use_gpu or use_bgl
    if use_bgl or (not use_gpu_scissor):
        return bgl_is_enabled('GL_SCISSOR_TEST')
    if use_gpu and use_gpu_scissor:
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
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    shader_interface = gpu.types.GPUStageInterfaceInfo(f'interface_{safe_name}') # NOTE: DO NOT CALL IT `interface`
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
        # https://wiki.blender.org/wiki/Style_Guide/GLSL#Shared_Shader_Files:~:text=If%20fragment%20shader%20is%20writing%20to%20gl_FragDepth%2C%20usage%20must%20be%20correctly%20defined%20in%20the%20shader%27s%20create%20info%20using%20.depth_write(DepthWrite).
        if shader_var['var'] == 'gl_FragDepth':
            if bpy.app.version > (3, 6, 0):
                shader_info.depth_write('ANY')
            if gpu.platform.backend_type_get() == 'OPENGL':
                continue
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


######################################################################################################



# Ideally, would use GPUOffScreen, however it keeps flickering (creating new? deleting?)
# modified from addons/mesh_snap_utitities_line/snap_context_l/__init__.py

class FrameBuffer:
    # _null_buffer = (ctypes.c_int32 * 1).from_address(0)
    _creating = False
    _fbs = []
    _all_fbs = []

    @staticmethod
    def new(width, height):
        if FrameBuffer._fbs:
            fb = FrameBuffer._fbs.pop()
            fb.resize(width, height)
        else:
            FrameBuffer._creating = True
            fb = FrameBuffer()
            FrameBuffer._creating = False
            FrameBuffer._all_fbs.append(fb)  # add to list so that __del__ isn't called too soon!
            fb._create(width, height)

        return fb
        class FrameBufferWrapper:
            def __init__(self, fb):
                self.__dict__['_fb'] = fb
            def __del__(self):
                self.free()
            def __getattr__(self, attr):
                return getattr(self.__dict__['_fb'], attr)
            # def __setattr__(self, attr, val):
            #     setattr(self.__dict__['_fb'], attr, val)
            def free(self):
                if '_fb' not in self.__dict__: return
                # print('FrameBuffer freed (%d)' % len(FrameBuffer._fbs))
                self.__dict__['_fb'].free()
                del self.__dict__['_fb']

        return FrameBufferWrapper(fb)

    def free(self):
        FrameBuffer._fbs.append(self)

    def __init__(self):
        assert FrameBuffer._creating == True, 'do not create FrameBuffer objects directly, use FrameBuffer.new()'
        self._is_freed = False
        self._is_error = False
        self._is_bound = False

    def _create(self, width, height):
        import bgl
        get_glerror('FrameBuffer._create: start')
        self._width = max(1, int(width))
        self._height = max(1, int(height))

        self._fbo = bgl.Buffer(bgl.GL_INT, 1)
        self._buf_color = bgl.Buffer(bgl.GL_INT, 1)
        self._buf_depth = bgl.Buffer(bgl.GL_INT, 1)

        self._cur_fbo = bgl.Buffer(bgl.GL_INT, 1)
        self._cur_viewport = bgl.Buffer(bgl.GL_INT, 4)
        self._cur_projection = gpu.matrix.get_projection_matrix()

        # get_glerror('FrameBuffer._create: gen render buf, tex')
        bgl.glGenRenderbuffers(1, self._buf_depth)
        bgl.glGenTextures(1, self._buf_color)
        self._config_textures()

        # get_glerror('FrameBuffer._create: gen fb')
        bgl.glGenFramebuffers(1, self._fbo)
        # IMPORTANT: do NOT clear color/depth yet, because color and depth buffers are not attached!
        self.bind(set_viewport=False, set_projection=False, clear_color=False, clear_depth=False)
        # get_glerror('FrameBuffer._create: setup fb')
        bgl.glFramebufferRenderbuffer(bgl.GL_FRAMEBUFFER, bgl.GL_DEPTH_ATTACHMENT,bgl.GL_RENDERBUFFER, self._buf_depth[0])
        bgl.glFramebufferTexture(bgl.GL_FRAMEBUFFER, bgl.GL_COLOR_ATTACHMENT0, self._buf_color[0], 0)
        bgl.glDrawBuffers(1, bgl.Buffer(bgl.GL_INT, 1, [bgl.GL_COLOR_ATTACHMENT0]))
        # get_glerror('FrameBuffer._create: check status')
        status = bgl.glCheckFramebufferStatus(bgl.GL_FRAMEBUFFER)
        if status != bgl.GL_FRAMEBUFFER_COMPLETE:
            print("Framebuffer Invalid", status)
            self._is_error = True
        bgl.glClear(bgl.GL_COLOR_BUFFER_BIT | bgl.GL_DEPTH_BUFFER_BIT)
        # get_glerror('FrameBuffer._create: unbind')
        self.unbind(unset_viewport=False, unset_projection=False)
        get_glerror('FrameBuffer._create: done')

    def __del__(self):
        import bgl
        if self not in FrameBuffer._all_fbs: return
        assert not self._is_freed
        FrameBuffer._all_fbs.remove(self)
        # print('----> DELETING FRAMEBUFFER')
        assert not self._is_bound, 'Cannot free a bounded FrameBuffer'
        # print(self._fbo, self._buf_depth, self._buf_color)
        bgl.glDeleteFramebuffers(1, self._fbo)
        bgl.glDeleteRenderbuffers(1, self._buf_depth)
        bgl.glDeleteTextures(1, self._buf_color)
        del self._fbo
        del self._buf_color
        del self._buf_depth
        del self._cur_fbo
        del self._cur_viewport
        self._is_freed = True

    @property
    def color_texture(self):
        return self._buf_color[0]
    @property
    def width(self):
        return self._width
    @property
    def height(self):
        return self._height

    def _config_textures(self):
        import bgl
        bgl.glBindRenderbuffer(bgl.GL_RENDERBUFFER, self._buf_depth[0])
        bgl.glRenderbufferStorage(bgl.GL_RENDERBUFFER, bgl.GL_DEPTH_COMPONENT, self._width, self._height)
        bgl.glBindRenderbuffer(bgl.GL_RENDERBUFFER, 0)

        # NULL = bgl.Buffer(bgl.GL_INT, 1, self._null_buffer)
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, self._buf_color[0])
        bgl.glTexImage2D(bgl.GL_TEXTURE_2D, 0, bgl.GL_RGBA, self._width, self._height, 0, bgl.GL_RGBA, bgl.GL_UNSIGNED_BYTE, None)
        bgl.glTexParameteri(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MIN_FILTER, bgl.GL_NEAREST)
        bgl.glTexParameteri(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MAG_FILTER, bgl.GL_NEAREST)
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, 0)
        # del NULL

    def bind(self, set_viewport=True, set_projection=True, clear_color=True, clear_depth=True):
        import bgl
        assert not self._is_bound, 'Cannot bind a bounded FrameBuffer'
        assert not self._is_error, 'Cannot bind a FrameBuffer with error'
        assert not self._is_freed, 'Cannot bind a freed FrameBuffer'
        self._is_bound = True
        bgl.glGetIntegerv(bgl.GL_FRAMEBUFFER_BINDING, self._cur_fbo)
        bgl.glGetIntegerv(bgl.GL_VIEWPORT, self._cur_viewport)
        bgl.glBindFramebuffer(bgl.GL_FRAMEBUFFER, self._fbo[0])
        self._cur_projection = gpu.matrix.get_projection_matrix()
        if set_viewport:
            bgl.glViewport(0, 0, self._width, self._height)
        if set_projection:
            vx, vy, vw, vh = -1, -1, 2 / self._width, 2 / self._height
            M = Matrix([
                [vw,  0,  0, vx],
                [ 0, vh,  0, vy],
                [ 0,  0,  1,  0],
                [ 0,  0,  0,  1],
                ])
            gpu.matrix.load_projection_matrix(M)
        ScissorStack.push(0, self._height - 1, self._width, self._height, clamp=False)
        if clear_color: bgl.glClear(bgl.GL_COLOR_BUFFER_BIT)
        if clear_depth: bgl.glClear(bgl.GL_DEPTH_BUFFER_BIT)

    def unbind(self, unset_viewport=True, unset_projection=True):
        import bgl
        assert self._is_bound, 'Cannot unbind a unbounded FrameBuffer'
        assert not self._is_error, 'Cannot unbind a FrameBuffer with error'
        assert not self._is_freed, 'Cannot unbind a freed FrameBuffer'
        # get_glerror('FrameBuffer.unbind: unsetting projection, viewport')
        if unset_projection: gpu.matrix.load_projection_matrix(self._cur_projection)
        if unset_viewport: bgl.glViewport(*self._cur_viewport)
        # get_glerror('FrameBuffer.unbind: binding to prev')
        bgl.glBindFramebuffer(bgl.GL_FRAMEBUFFER, self._cur_fbo[0])
        # get_glerror('FrameBuffer.unbind: popping scissorstack')
        ScissorStack.pop()
        self._is_bound = False
        # get_glerror('FrameBuffer.unbind: done')

    @contextmanager
    def bind_unbind(self, set_viewport=True, set_projection=True, clear_color=True, clear_depth=True):
        try:
            self.bind(set_viewport=set_viewport, set_projection=set_projection, clear_color=clear_color, clear_depth=clear_depth)
            yield None
            self.unbind(unset_viewport=set_viewport, unset_projection=set_projection)
        except Exception as e:
            self.unbind(unset_viewport=set_viewport, unset_projection=set_projection)
            print('Caught exception while FrameBuffer was bound:', {'set_viewport':set_viewport, 'clear_color':clear_color, 'clear_depth':clear_depth})
            Globals.debugger.print_exception()
            raise e

    def resize(self, width, height, clear_color=True, clear_depth=True):
        assert not self._is_bound, 'Cannot resize a bounded FrameBuffer'
        assert not self._is_error, 'Cannot resize a FrameBuffer with error'
        assert not self._is_freed, 'Cannot resize a freed FrameBuffer'

        width, height = int(width), int(height)
        if self._width == width and self._height == height: return
        # with self.bind_unbind(set_viewport=False, clear_color=clear_color, clear_depth=clear_depth):
        # print('Resizing FrameBuffer from %dx%d to %dx%d' % (self._width, self._height, width, height))
        self._width, self._height = width, height
        self._config_textures()



######################################################################################################


class ScissorStack:
    is_started = False
    scissor_test_was_enabled = False
    stack = None                        # stack of (l,t,w,h) in region-coordinates, because viewport is set to region
    msg_stack = None

    @staticmethod
    def start(context):
        assert not ScissorStack.is_started, 'Attempting to start a started ScissorStack'

        # region pos and size are window-coordinates
        rgn = context.region
        rl,rb,rw,rh = rgn.x, rgn.y, rgn.width, rgn.height
        rt = rb + rh - 1

        # remember the current scissor box settings so we can return to them when done
        ScissorStack.scissor_test_was_enabled = get_scissor_test()
        get_glerror('get_scissor_test')
        if ScissorStack.scissor_test_was_enabled:
            pl, pb, pw, ph = get_scissor() #ScissorStack.buf
            get_glerror('get_scissor')
            pt = pb + ph - 1
            ScissorStack.stack = [(pl, pt, pw, ph)]
            ScissorStack.msg_stack = ['init']
            # don't need to enable, because we are already scissoring!
            # TODO: this is not tested!
        else:
            ScissorStack.stack = [(0, rh - 1, rw, rh)]
            ScissorStack.msg_stack = ['init']
            scissor_test(True)

        # we're ready to go!
        ScissorStack.is_started = True
        ScissorStack._set_scissor()

    @staticmethod
    def end(force=False):
        if not force:
            assert ScissorStack.is_started, 'Attempting to end a non-started ScissorStack'
            assert len(ScissorStack.stack) == 1, 'Attempting to end a non-empty ScissorStack (size: %d)' % (len(ScissorStack.stack)-1)
        scissor_test(ScissorStack.scissor_test_was_enabled)
        ScissorStack.is_started = False
        ScissorStack.stack = None

    @staticmethod
    def _set_scissor():
        assert ScissorStack.is_started, 'Attempting to set scissor settings with non-started ScissorStack'
        # print(f'ScissorStack: {ScissorStack.stack}')
        l,t,w,h = ScissorStack.stack[-1]
        b = t - (h - 1)
        scissor(l, b, w, h)
        get_glerror('scissor')

    @staticmethod
    def push(nl, nt, nw, nh, msg='', clamp=True):
        # note: pos and size are already in region-coordinates, but it is specified from top-left corner

        assert ScissorStack.is_started, 'Attempting to push to a non-started ScissorStack!'

        if clamp:
            # get previous scissor box
            pl, pt, pw, ph = ScissorStack.stack[-1]
            pr = pl + (pw - 1)
            pb = pt - (ph - 1)
            # compute right and bottom of new scissor box
            nr = nl + (nw - 1)
            nb = nt - (nh - 1) - 1      # sub 1 (not certain why this needs to be)
            # compute clamped l,r,t,b,w,h
            cl, cr, ct, cb = mid(nl,pl,pr), mid(nr,pl,pr), mid(nt,pt,pb), mid(nb,pt,pb)
            cw, ch = max(0, cr - cl + 1), max(0, ct - cb + 1)
            ScissorStack.stack.append((int(cl), int(ct), int(cw), int(ch)))
        else:
            ScissorStack.stack.append((int(nl), int(nt), int(nw), int(nh)))
        ScissorStack.msg_stack.append(msg)

        ScissorStack._set_scissor()

    @staticmethod
    def pop():
        assert len(ScissorStack.stack) > 1, 'Attempting to pop from empty ScissorStack!'
        ScissorStack.stack.pop()
        ScissorStack.msg_stack.pop()
        ScissorStack._set_scissor()

    @staticmethod
    @contextmanager
    def wrap(*args, disabled=False, **kwargs):
        if disabled:
            yield None
            return
        try:
            ScissorStack.push(*args, **kwargs)
            yield None
            ScissorStack.pop()
        except Exception as e:
            ScissorStack.pop()
            print(f'Caught exception while scissoring')
            print(f'{args=} {kwargs=}')
            print(f'Exception: {e}')
            Globals.debugger.print_exception()
            raise e

    @staticmethod
    def get_current_view():
        assert ScissorStack.is_started
        assert ScissorStack.stack
        l, t, w, h = ScissorStack.stack[-1]
        #r, b = l + (w - 1), t - (h - 1)
        return (l, t, w, h)

    @staticmethod
    def print_view_stack():
        for i,st in enumerate(ScissorStack.stack):
            l, t, w, h = st
            #r, b = l + (w - 1), t - (h - 1)
            print(('  '*i) + str((l,t,w,h)) + ' ' + ScissorStack.msg_stack[i])

    @staticmethod
    def is_visible():
        vl,vt,vw,vh = ScissorStack.get_current_view()
        return vw > 0 and vh > 0

    @staticmethod
    def is_box_visible(l, t, w, h):
        if w <= 0 or h <= 0: return False
        vl, vt, vw, vh = ScissorStack.get_current_view()
        if vw <= 0 or vh <= 0: return False
        vr, vb = vl + (vw - 1), vt - (vh - 1)
        r, b = l + (w - 1), t - (h - 1)
        return not (l > vr or r < vl or t < vb or b > vt)





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

