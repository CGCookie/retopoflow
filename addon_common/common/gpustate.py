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


#######################################################################
# THE FOLLOWING FUNCTIONS ARE ONLY FOR THE TRANSITION FROM BGL TO GPU #
# THIS FILE **SHOULD** GO AWAY ONCE WE DROP SUPPORT FOR BLENDER 2.83  #
# AROUND JUNE 2023 AS BLENDER 2.93 HAS GPU MODULE                     #
#######################################################################

import os
import re
import traceback
from inspect import isroutine
from itertools import chain
from contextlib import contextmanager

import bpy
import gpu

from mathutils import Matrix, Vector

from .blender import get_path_from_addon_common
from .globals import Globals
from .decorators import only_in_blender_version, warn_once, add_cache
from .maths import mid
from .utils import Dict
from ..terminal import term_printer


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
    use_gpu_scissor = True

print(f'Addon Common: {use_bgl_default=} {use_gpu_default=} {use_gpu_scissor=}')

def get_blend(): return gpu.state.blend_get()
def blend(mode, *, use_gpu=use_gpu_default, use_bgl=use_bgl_default, only=None):
    assert use_gpu or use_bgl
    if use_bgl:
        import bgl
        if only != 'function':
            if mode == 'NONE':
                bgl.glDisable(bgl.GL_BLEND)
            else:
                bgl.glEnable(bgl.GL_BLEND)
        if only != 'enable':
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
        if not only:
            gpu.state.blend_set(mode)
        elif only == 'enable':
            if (mode == 'NONE') != (gpu.state.blend_get() == 'NONE'):
                # enabled-ness is different (one is enabled and other disabled)
                gpu.state.blend_set(mode)
        elif only == 'function':
            if gpu.state.blend_get() != 'NONE':
                # only set when blending is already enabled
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

def line_width(width): gpu.state.line_width_set(width)
def get_line_width(): return gpu.state.line_width_get()

def point_size(size): gpu.state.point_size_set(size)
def get_point_size(): return gpu.state.point_size_get()

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

# https://developer.blender.org/rB21c658b718b9
# https://developer.blender.org/T74139
def get_srgb_shim(force=False):
    if not force: return ''
    return 'vec4 blender_srgb_to_framebuffer_space(vec4 c) { return pow(c, vec4(1.0/2.2, 1.0/2.2, 1.0/2.2, 1.0)); }'

def shader_parse_string(string, *, includeVersion=True, constant_overrides=None, define_overrides=None, force_shim=False):
    # NOTE: GEOMETRY SHADER NOT FULLY SUPPORTED, YET
    #       need to find a way to handle in/out
    constant_overrides = constant_overrides or {}
    define_overrides = define_overrides or {}
    uniforms, varyings, attributes, consts = [],[],[],[]
    vertSource, geoSource, fragSource, commonSource = [],[],[],[]
    vertVersion, geoVersion, fragVersion = '','',''
    mode = 'common'
    lines = string.splitlines()
    for i_line,line in enumerate(lines):
        sline = line.lstrip()
        if re.match(r'uniform ', sline):
            uniforms.append(line)
        elif re.match(r'attribute ', sline):
            attributes.append(line)
        elif re.match(r'varying ', sline):
            varyings.append(line)
        elif re.match(r'const ', sline):
            m = re.match(r'const +(?P<type>bool|int|float|vec\d) +(?P<var>[a-zA-Z0-9_]+) *= *(?P<val>[^;]+);', sline)
            if m is None:
                print(f'Shader could not match const line ({i_line}): {line}')
            elif m.group('var') in constant_overrides:
                line = 'const %s %s = %s' % (m.group('type'), m.group('var'), constant_overrides[m.group('var')])
            consts.append(line)
        elif re.match(r'#define ', sline):
            m0 = re.match(r'#define +(?P<var>[a-zA-Z0-9_]+)$', sline)
            m1 = re.match(r'#define +(?P<var>[a-zA-Z0-9_]+) +(?P<val>.+)$', sline)
            if m0 and m0.group('var') in define_overrides:
                if not define_overrides[m0.group('var')]:
                    line = ''
            if m1 and m1.group('var') in define_overrides:
                line = '#define %s %s' % (m1.group('var'), define_overrides[m1.group('var')])
            if not m0 and not m1:
                print(f'Shader could not match #define line ({i_line}): {line}')
            consts.append(line)
        elif re.match(r'#version ', sline):
            match mode:
                case 'common': vertVersion, geoVersion, fragVersion = line, line, line
                case 'vert':   vertVersion = line
                case 'geo':    geoVersion  = line
                case 'frag':   fragVersion = line
                case _: assert False, f'Addon Common: Unhandled mode {mode}'
        elif mode == 'common' and re.match(r'precision ', sline):
            commonSource.append(line)
        elif m := re.match(r'//+ +(?P<mode>common|vert(ex)?|geo(m(etry)?)?|frag(ment)?) shader', sline.lower()):
            match m['mode'][0]:
                case 'c': mode = 'common'
                case 'v': mode = 'vert'
                case 'g': mode = 'geo'
                case 'f': mode = 'frag'
        else:
            if not line.strip(): continue
            match mode:
                case 'common': commonSource.append(line)
                case 'vert':   vertSource.append(line)
                case 'geo':    geoSource.append(line)
                case 'frag':   fragSource.append(line)
                case _: assert False, f'Addon Common: Unhandled mode {mode}'
    assert vertSource, f'could not detect vertex shader'
    assert fragSource, f'could not detect fragment shader'
    v_attributes = [a.replace('attribute ', 'in ') for a in attributes]
    v_varyings = [v.replace('varying ', 'out ') for v in varyings]
    f_varyings = [v.replace('varying ', 'in ') for v in varyings]
    srcVertex = '\n'.join(chain(
        ([vertVersion] if includeVersion else []),
        uniforms,
        v_attributes,
        v_varyings,
        consts,
        commonSource,
        vertSource,
    ))
    srcFragment = '\n'.join(chain(
        ([fragVersion] if includeVersion else []),
        uniforms,
        f_varyings,
        consts,
        [get_srgb_shim(force=force_shim)],
        ['/////////////////////'],
        commonSource,
        fragSource,
    ))
    return (srcVertex, srcFragment)

def shader_read_file(filename):
    filename_guess = get_path_from_addon_common('common', 'shaders', filename)
    if   os.path.exists(filename):       pass
    elif os.path.exists(filename_guess): filename = filename_guess
    else: assert False, f"Shader file could not be found: {filename} ({filename_guess})"

    contents = open(filename, 'rt').read()
    while m_include := re.search(r'\n *#include +"(?P<filename>[^"]+)" *\n', contents):
        include_contents = shader_read_file(m_include['filename'])
        contents = contents[:m_include.start()] + f'\n{include_contents}\n' + contents[m_include.end():]
    return contents

def shader_parse_file(filename, **kwargs):
    return shader_parse_string(shader_read_file(filename), **kwargs)


def clean_shader_source(source):
    source = source + '\n'                              # add newline at end
    source = re.sub(r'/[*](\n|.)*?[*]/', '',   source)  # remove multi-line comments
    source = re.sub(r'//.*?\n',          '\n', source)  # remove single line comments
    source = re.sub(r'\n+',              '\n', source)  # remove multiple newlines
    source = re.sub(r'[ \t]+\n',         '\n', source)  # trim end of lines
    return source

re_shader_var = re.compile(
    r'((layout *\((?P<layout>[^)]*)\))\s+)?'
    r'((?P<qualifier>noperspective|flat|smooth)\s+)?'
    r'(?P<uio>uniform|in|out)\s+'
    r'(?P<type>[a-zA-Z0-9_]+)\s+'
    r'(?P<var>[a-zA-Z0-9_]+)'
    r'(\s*=\s*(?P<defval>[^;]+))?\s*;'
)
re_shader_var_parts = ['qualifier', 'uio', 'type', 'var', 'defval', 'layout']
def split_shader_vars(source):
    shader_vars = {
        m['var']: { part: m[part] for part in re_shader_var_parts }
        for m in re_shader_var.finditer(source)
    }
    source = re_shader_var.sub('', source)
    source = '\n'.join(l for l in source.splitlines() if l.strip())
    return (shader_vars, source)

re_shader_struct = re.compile(r'struct\s+(?P<name>[a-zA-Z0-9_]+)\s+[{](?P<attribs>[^}]+)[}]\s*;')
re_shader_struct_attrib = re.compile(r'(?P<type>[a-zA-Z0-9_]+)\s+(?P<name>[a-zA-Z0-9_]+)\n*;')
def split_shader_structs(source):
    structs = {
        m['name']: {
            'name': m['name'],
            'full': m.group(0),
            'attribs': [ (ma['type'], ma['name']) for ma in re_shader_struct_attrib.finditer(m['attribs']) ],
            'type':    { ma['name']: ma['type']   for ma in re_shader_struct_attrib.finditer(m['attribs']) },
        }
        for m in re_shader_struct.finditer(source)
    }
    source = re_shader_struct.sub('', source)
    source = '\n'.join(l for l in source.splitlines() if l.strip())
    return (structs, source)

def shader_var_to_ctype(shader_type, shader_varname):
    return (shader_varname, shader_type_to_ctype(shader_type))

def shader_type_to_ctype(shader_type):
    import ctypes
    match shader_type:
        case 'mat4':  return (ctypes.c_float * 4) * 4
        case 'vec4':  return ctypes.c_float * 4
        case 'ivec4': return ctypes.c_int * 4
        case _:       assert False, f'Unhandled shader type {shader_type}'

def shader_struct_to_UBO(shadername, struct, varname):
    import ctypes
    # copied+modified from scripts/addons/mesh_snap_utitilies_line/drawing_utilities.py
    class GPU_UBO(ctypes.Structure):
        _pack_ = 16
        _fields_ = [ shader_var_to_ctype(t, n) for (t, n) in struct['attribs'] ]
    ubo_data = GPU_UBO()
    ubo_data_size = ctypes.sizeof(ubo_data)
    ubo_data_slots = ubo_data_size // ctypes.sizeof(ctypes.c_float)
    if False:
        term_printer.boxed(
            f'Struct: "{struct["name"]} {varname}" ({ubo_data_size}bytes, {ubo_data_slots}slots)',
            f'Attribs: ' + '; '.join(f'{k} {v}' for (k,v) in struct['attribs']),
            title=f'GPU Shader Struct: {shadername}',
        )
    ubo_buffer = gpu.types.Buffer('UBYTE', ubo_data_size, ubo_data)
    ubo = gpu.types.GPUUniformBuf(ubo_buffer)
    def setter(name, value):
        # print(f'UBO_Wrapper.set {name} = {value} ({type(value)})')
        shader_type = struct['type'][name]
        match shader_type:
            case 'mat4':
                a = getattr(ubo_data, name)
                CType = shader_type_to_ctype('vec4')
                if len(value) == 3: value = value.to_4x4()
                assert len(value) == 4 and len(value[0]) == 4
                a[0] = CType(value[0][0], value[1][0], value[2][0], value[3][0])
                a[1] = CType(value[0][1], value[1][1], value[2][1], value[3][1])
                a[2] = CType(value[0][2], value[1][2], value[2][2], value[3][2])
                a[3] = CType(value[0][3], value[1][3], value[2][3], value[3][3])
            case 'vec4'|'ivec4':
                CType = shader_type_to_ctype(shader_type)
                if   len(value) == 2: value = (*value, 0.0, 0.0)
                elif len(value) == 3: value = (*value, 0.0)
                assert len(value) == 4
                setattr(ubo_data, name, CType(*value))
    class UBO_Wrapper:
        def __init__(self):
            pass
        def set_shader(self, shader):
            self.__dict__['_shader'] = shader
        def __setattr__(self, name, value):
            self.assign(name, value)
        def slots_used(self):
            return ubo_data_slots
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

re_shader_location = re.compile(r'location *= *(?P<location>\d+)')
def gpu_shader(name, vert_source, frag_source, *, defines=None):
    vert_source, frag_source = map(clean_shader_source, (vert_source, frag_source))
    vert_shader_structs, vert_source = split_shader_structs(vert_source)
    frag_shader_structs, frag_source = split_shader_structs(frag_source)
    shader_structs = vert_shader_structs | frag_shader_structs
    vert_shader_vars, vert_source = split_shader_vars(vert_source)
    frag_shader_vars, frag_source = split_shader_vars(frag_source)
    shader_vars  = vert_shader_vars | frag_shader_vars
    uniform_vars = { k:v for (k,v) in shader_vars.items() if v['uio'] == 'uniform' }
    in_vars      = { k:v for (k,v) in vert_shader_vars.items() if v['uio'] == 'in' }
    inout_vars   = { k:v for (k,v) in vert_shader_vars.items() if v['uio'] == 'out' }
    out_vars     = { k:v for (k,v) in frag_shader_vars.items() if v['uio'] == 'out'}

    if False:
        def nonetoempty(s): return s if s else ''
        def divider(s): return f'\n{"═"*5}╡ {s} ╞{"═"*(120-(len(s) + 4 + 5))}\n\n'
        term_printer.boxed(
            *(ss['full'] for ss in vert_shader_structs.values()),
            divider('Uniforms, Inputs, InOuts, Outputs'),
            f'{"Layout":12s} {"Qualifier":13s} {"UIO":7s} {"Type":10s} {"Var Name":20s} {"Def Val"}',
            f'{"-"*12        } {"-"*13         } {"-"*7   } {"-"*10    } {"-"*20        } {"-"*(120-(12+1+13+1+7+1+10+1+20+1))}',
            *(
                f'{nonetoempty(sv["layout"]):12s} '
                f'{nonetoempty(sv["qualifier"]):13s} '  # noperspective
                f'{nonetoempty(sv["uio"]):7s} '         # uniform
                f'{nonetoempty(sv["type"]):10s} '
                f'{nonetoempty(sv["var"]):20s} '
                f'{nonetoempty(sv["defval"])}'
                for sv in chain(uniform_vars.values(), in_vars.values(), inout_vars.values(), out_vars.values())
            ),
            divider('Vertex Shader'),
            vert_source,
            divider('Fragment Shader'),
            frag_source,
            title=f'GPUSader {name}'
        )

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

    slot_samplers = 0
    slot_structs = 0
    slot_input = 0
    slot_output = 0

    # UNIFORMS
    for uniform_var in uniform_vars.values():
        slot = None
        if uniform_var['layout'] and (m_location := re_shader_location.search(uniform_var['layout'])):
            slot = int(m_location['location'])

        match uniform_var['type']:
            case 'sampler2D':
                if slot is None: slot = slot_samplers
                shader_info.sampler(slot, 'FLOAT_2D', uniform_var['var'])
                slot_samplers = max(slot + 1, slot_samplers)
            case t if t in gpu_type_size:
                shader_info.push_constant(glsl_to_gpu_type(uniform_var['type']), uniform_var['var'])
            case _:
                if slot is None: slot = slot_structs
                shader_info.uniform_buf(slot, uniform_var['type'], uniform_var['var'])
                ubo_wrapper = shader_struct_to_UBO(name, shader_structs[uniform_var['type']], uniform_var['var'])
                UBOs[uniform_var['var']] = ubo_wrapper
                # print(f'uniform struct {uniform_var["type"]} {uniform_var["var"]} {slot=}')
                slot_structs = max(slot + ubo_wrapper.slots_used(), slot_structs)
    if False:
        term_printer.boxed(
            str(UBOs),
            title=f'Uniforms'
        )

    # PREPROCESSING DEFINE DIRECTIVES
    if defines:
        for k,v in defines.items():
            shader_info.define(str(k), str(v))

    # INPUTS
    for in_var in in_vars.values():
        shader_info.vertex_in(slot_input, glsl_to_gpu_type(in_var['type']), in_var['var'])
        slot_input += 1

    # INTERFACE
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    safe_name = re.sub(r'__+', '_', safe_name)
    shader_interface = gpu.types.GPUStageInterfaceInfo(f'interface_{safe_name}') # NOTE: DO NOT CALL IT `interface`
    qualified_fns = {
        'noperspective': shader_interface.no_perspective,
        'flat':          shader_interface.flat,
        'smooth':        shader_interface.smooth,
        None:            shader_interface.smooth,
    }
    needs_interface = False
    for inout_var in inout_vars.values():
        needs_interface = True
        qualified_fn = qualified_fns[inout_var['qualifier']]
        qualified_fn(glsl_to_gpu_type(inout_var['type']), inout_var['var'])
    if needs_interface:
        shader_info.vertex_out(shader_interface)

    # OUTPUTS
    for out_var in out_vars.values():
        # https://wiki.blender.org/wiki/Style_Guide/GLSL#Shared_Shader_Files:~:text=If%20fragment%20shader%20is%20writing%20to%20gl_FragDepth%2C%20usage%20must%20be%20correctly%20defined%20in%20the%20shader%27s%20create%20info%20using%20.depth_write(DepthWrite).
        if out_var['var'] == 'gl_FragDepth':
            if hasattr(shader_info, 'depth_write'):
                # SHOULD BE INCLUDED IN 4.0, AND HOPEFULLY IN 3.6
                shader_info.depth_write('ANY')
            if bpy.app.version < (3, 4, 0) or gpu.platform.backend_type_get() == 'OPENGL':
                continue
            if bpy.app.version >= (4, 5, 0): continue
        shader_info.fragment_out(slot_output, glsl_to_gpu_type(out_var['type']), out_var['var'])
        slot_output += 1

    if False:
        print(shader_vars)
        print(vert_source)
        print(frag_source)

    shader_info.vertex_source(vert_source)
    shader_info.fragment_source(frag_source)

    try:
        shader = gpu.shader.create_from_info(shader_info)
    except Exception as e:
        print(f'Caught Exception {e} while trying to create shader')
        print(vert_source)
        print(frag_source)
        raise e

    UBOs.set_shader(shader)
    del shader_interface
    del shader_info
    return shader, UBOs

    # return gpu.types.GPUShader(vert_source, frag_source)


######################################################################################################


class FrameBuffer:
    def __init__(self, width, height):
        self._width, self._height = None, None
        self._is_bound = False
        self.resize(width, height)

    def resize(self, width, height, clear_color=True, clear_depth=True):
        assert not self._is_bound, 'Cannot resize a bounded FrameBuffer'

        width, height = max(1, int(width)), max(1, int(height))
        if self._width == width and self._height == height: return
        self._width, self._height = width, height

        vx, vy, vw, vh = -1, -1, 2 / self._width, 2 / self._height
        self._matrix = Matrix([
            [vw,  0,  0, vx],
            [ 0, vh,  0, vy],
            [ 0,  0,  1,  0],
            [ 0,  0,  0,  1],
        ])

        self._tex_color = gpu.types.GPUTexture((self._width, self._height), format='RGBA8')
        self._tex_depth = gpu.types.GPUTexture((self._width, self._height), format='DEPTH_COMPONENT32F')

        self._framebuffer = gpu.types.GPUFrameBuffer(
            color_slots={ 'texture': self._tex_color },
            depth_slot=self._tex_depth,
        )

    @property
    def color_texture(self): return self._tex_color
    @property
    def width(self): return self._width
    @property
    def height(self): return self._height

    def _set_viewport(self):
        o = self._framebuffer if False else gpu.state
        o.viewport_set(0, 0, self._width, self._height)
    def _reset_viewport(self):
        o = self._cur_fbo if False else gpu.state
        o.viewport_set(*self._cur_viewport)

    def _set_projection(self):
        gpu.matrix.load_projection_matrix(self._matrix)
    def _reset_projection(self):
        gpu.matrix.load_projection_matrix(self._cur_projection)

    def _set_scissor(self):
        ScissorStack.push(0, self._height - 1, self._width, self._height, clamp=False)
    def _reset_scissor(self):
        ScissorStack.pop()

    def _clear(self):
        self._framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0), depth=1.0)

    @contextmanager
    def bind(self):
        assert not self._is_bound, 'Cannot bind a bounded FrameBuffer'
        try:
            self._is_bound = True
            self._cur_fbo = gpu.state.active_framebuffer_get()
            self._cur_viewport = gpu.state.viewport_get()
            self._cur_projection = gpu.matrix.get_projection_matrix()
            with self._framebuffer.bind():
                self._set_viewport()
                self._set_projection()
                self._set_scissor()
                self._clear()
                yield None
        except Exception as e:
            print(f'Caught exception while FrameBuffer was bound:')
            print(f'  {e}')
            Globals.debugger.print_exception()
            raise e
        finally:
            self._reset_scissor()
            self._reset_projection()
            self._reset_viewport()
            self._cur_fbo = None
            self._cur_viewport = None
            self._cur_projection = None
            self._is_bound = False




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

# if not bpy.app.background:
#     print(f'Addon Common: {gpu_info()}')


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

