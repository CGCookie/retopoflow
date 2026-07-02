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

from __future__ import annotations

import ctypes
import _ctypes
import os
import platform
import re
from dataclasses import dataclass
from inspect import isroutine
from itertools import chain
from contextlib import contextmanager
from typing import Literal, ClassVar, Any, cast
from collections.abc import Sequence, Generator

import bpy
import gpu
from bpy.types import bpy_prop_array, Context
from gpu.types import GPUShader, GPUTexture, GPUFrameBuffer

from mathutils import Matrix, Vector
from mathutils import Color as BColor

from .blender import get_path_from_addon_common
from .globals import Globals
from .maths import mid
from .maths import Color as MColor
from .colors import Color4
from .utils import Dict
# from ..terminal import term_printer


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

BLENDMODES = Literal[
    "NONE",
    "ALPHA",
    "ALPHA_PREMULT",
    "ADDITIVE",
    "ADDITIVE_PREMULT",
    "MULTIPLY",
    "SUBTRACT",
    "INVERT",
]

DEPTHTESTMODES = Literal[
    "NONE", "ALWAYS", "LESS", "LESS_EQUAL", "EQUAL", "GREATER", "GREATER_EQUAL"
]

CULLINGMODES = Literal["NONE", "FRONT", "BACK"]


def get_blend() -> BLENDMODES:
    return gpu.state.blend_get()

def blend(
    mode : BLENDMODES,
    *,
    only : Literal['enable', 'function'] | None = None
):
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


def depth_test(mode : DEPTHTESTMODES):
    gpu.state.depth_test_set(mode)

def get_depth_test() -> str:
    return gpu.state.depth_test_get()

def depth_mask(enable : bool):
    gpu.state.depth_mask_set(enable)

def get_depth_mask() -> bool:
    return gpu.state.depth_mask_get()

def line_width(width : float):
    gpu.state.line_width_set(width)

def get_line_width() -> float:
    return gpu.state.line_width_get()

def point_size(size : float):
    gpu.state.point_size_set(size)

def scissor(left : int, bottom : int, width : int, height : int):
    gpu.state.scissor_set(left, bottom, width, height)

def get_scissor() -> tuple[int, int, int, int]:
    return gpu.state.scissor_get()

def scissor_test(enable : bool):
    gpu.state.scissor_test_set(enable)

def get_scissor_test() -> bool:
    # NOTE: no equivalent in `gpu` module as of Blender 5.1
    # return gpu.state.scissor_test_get()
    return False

def culling(mode : CULLINGMODES):
    gpu.state.face_culling_set(mode)


#########################
# opengl errors

def get_glerror(_title : str) -> bool:
    # NOTE: no equivalent in `gpu` module as of Blender 3.5.1
    return False



#######################################
# shader

# https://developer.blender.org/rB21c658b718b9
# https://developer.blender.org/T74139
def get_srgb_shim(
    force : bool = False
) -> str:
    if not force:
        return ''
    return 'vec4 blender_srgb_to_framebuffer_space(vec4 c) { return pow(c, vec4(1.0/2.2, 1.0/2.2, 1.0/2.2, 1.0)); }'

def shader_parse_string(
    string : str,
    *,
    includeVersion : bool = True,
    constant_overrides : dict[str, str] | None = None,
    define_overrides : dict[str, str] | None = None,
    force_shim : bool = False,
) -> tuple[str, str]:
    # NOTE: GEOMETRY SHADER NOT FULLY SUPPORTED, YET
    #       need to find a way to handle in/out
    uniforms : list[str] = []
    varyings : list[str] = []
    attributes : list[str] = []
    consts : list[str] = []
    vertSource : list[str] = []
    geoSource : list[str] = []
    fragSource : list[str] = []
    commonSource : list[str] = []
    vertVersion : str = ''
    geoVersion : str = ''
    fragVersion : str = ''

    mode : str = 'common'
    for i_line, line in enumerate(string.splitlines()):
        sline : str = line.lstrip()

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
            elif constant_overrides and m.group('var') in constant_overrides:
                line = 'const %s %s = %s' % (m.group('type'), m.group('var'), constant_overrides[m.group('var')])
            consts.append(line)

        elif re.match(r'#define ', sline):
            m0 = re.match(r'#define +(?P<var>[a-zA-Z0-9_]+)$', sline)
            m1 = re.match(r'#define +(?P<var>[a-zA-Z0-9_]+) +(?P<val>.+)$', sline)
            if m0 and define_overrides and m0.group('var') in define_overrides:
                if not define_overrides[m0.group('var')]:
                    line = ''
            if m1 and define_overrides and m1.group('var') in define_overrides:
                line = '#define %s %s' % (m1.group('var'), define_overrides[m1.group('var')])
            if not m0 and not m1:
                print(f'Shader could not match #define line ({i_line}): {line}')
            consts.append(line)

        elif re.match(r'#version ', sline):
            match mode:
                case 'common':
                    vertVersion, geoVersion, fragVersion = line, line, line
                case 'vert':
                    vertVersion = line
                case 'geo':
                    geoVersion  = line
                case 'frag':
                    fragVersion = line

        elif mode == 'common' and re.match(r'precision ', sline):
            commonSource.append(line)

        elif m := re.match(r'//+ +(?P<mode>common|vert(ex)?|geo(m(etry)?)?|frag(ment)?) shader', sline.lower()):
            match m['mode'][0]:
                case 'c':
                    mode = 'common'
                case 'v':
                    mode = 'vert'
                case 'g':
                    mode = 'geo'
                case 'f':
                    mode = 'frag'
                case _:
                    assert False, f'Addon Common: Unhandled mode {m["mode"]}'

        else:
            if not line.strip():
                continue
            match mode:
                case 'common':
                    commonSource.append(line)
                case 'vert':
                    vertSource.append(line)
                case 'geo':
                    geoSource.append(line)
                case 'frag':
                    fragSource.append(line)

    assert vertSource, 'Addon Common: could not detect vertex shader'
    assert fragSource, 'Addon Common: could not detect fragment shader'
    assert not geoSource, 'Addon Common: detected unhandled geometry shader'

    geoVersion = geoVersion  # used only to appease linter (unused variable)

    v_attributes : list[str] = [a.replace('attribute ', 'in ') for a in attributes]
    v_varyings : list[str] = [v.replace('varying ', 'out ') for v in varyings]
    f_varyings : list[str] = [v.replace('varying ', 'in ') for v in varyings]

    srcVertex : str = '\n'.join(chain(
        ([vertVersion] if includeVersion else []),
        uniforms,
        v_attributes,
        v_varyings,
        consts,
        commonSource,
        vertSource,
    ))

    srcFragment : str = '\n'.join(chain(
        ([fragVersion] if includeVersion else []),
        uniforms,
        f_varyings,
        consts,
        [get_srgb_shim(force=force_shim) if platform.system() == 'Darwin' else ''],
        ['/////////////////////'],
        commonSource,
        fragSource,
    ))

    return (srcVertex, srcFragment)

def shader_read_file(filename : str) -> str:
    filename_guess = get_path_from_addon_common('common', 'shaders', filename)
    if   os.path.exists(filename):
        pass
    elif os.path.exists(filename_guess):
        filename = filename_guess
    else:
        assert False, f"Shader file could not be found: {filename} ({filename_guess})"

    contents = open(filename, 'rt').read()
    while m_include := re.search(r'\n *#include +"(?P<filename>[^"]+)" *\n', contents):
        include_contents = shader_read_file(m_include['filename'])
        contents = contents[:m_include.start()] + f'\n{include_contents}\n' + contents[m_include.end():]
    return contents

def shader_parse_file(
    filename : str,
    *,
    includeVersion : bool = True,
    constant_overrides : dict[str, str] | None = None,
    define_overrides : dict[str, str] | None = None,
    force_shim : bool = False,
):
    return shader_parse_string(
        shader_read_file(filename),
        includeVersion=includeVersion,
        constant_overrides=constant_overrides,
        define_overrides=define_overrides,
        force_shim=force_shim,
    )

def clean_shader_source(source : str) -> str:
    source = source + '\n'                              # add newline at end
    source = re.sub(r'/[*](\n|.)*?[*]/', '',   source)  # remove multi-line comments
    source = re.sub(r'//.*?\n',          '\n', source)  # remove single line comments
    source = re.sub(r'\n+',              '\n', source)  # remove multiple newlines
    source = re.sub(r'[ \t]+\n',         '\n', source)  # trim end of lines
    return source

re_shader_var = re.compile((
    r'((layout *\((?P<layout>[^)]*)\))\s+)?'
    r'((?P<qualifier>noperspective|flat|smooth)\s+)?'
    r'(?P<uio>uniform|in|out)\s+'
    r'(?P<type>[a-zA-Z0-9_]+)\s+'
    r'(?P<var>[a-zA-Z0-9_]+)'
    r'(\s*=\s*(?P<defval>[^;]+))?\s*;'
))
re_shader_var_parts = ['qualifier', 'uio', 'type', 'var', 'defval', 'layout']
def split_shader_vars(source : str) -> tuple[dict[str, dict[str, str]], str]:
    shader_vars = {
        m['var']: { part: m[part] for part in re_shader_var_parts }
        for m in re_shader_var.finditer(source)
    }
    source = re_shader_var.sub('', source)
    source = '\n'.join(line for line in source.splitlines() if line.strip())
    return (shader_vars, source)


@dataclass
class ShaderStruct:
    name : str
    full : str
    attribs : list[tuple[str, str]]
    types : dict[str, str]



re_shader_struct = re.compile(r'struct\s+(?P<name>[a-zA-Z0-9_]+)\s+[{](?P<attribs>[^}]+)[}]\s*;')
re_shader_struct_attrib = re.compile(r'(?P<type>[a-zA-Z0-9_]+)\s+(?P<name>[a-zA-Z0-9_]+)\n*;')
def split_shader_structs(source : str) -> tuple[dict[str, ShaderStruct], str]:
    structs = {
        m['name']: ShaderStruct(
            name = m['name'],
            full = m.group(0),
            attribs = [ (ma['type'], ma['name']) for ma in re_shader_struct_attrib.finditer(m['attribs']) ],
            types = { ma['name']: ma['type']   for ma in re_shader_struct_attrib.finditer(m['attribs']) },
        )
        for m in re_shader_struct.finditer(source)
    }
    source = re_shader_struct.sub('', source)
    source = '\n'.join(line for line in source.splitlines() if line.strip())
    return (structs, source)

def shader_var_to_ctype(
    shader_type : str,
    shader_varname : str,
) -> tuple[str, type[ctypes.Array[Any]]]:  # pyright: ignore[reportExplicitAny]
    return (
        shader_varname,
        shader_type_to_ctype(shader_type)
    )

def shader_type_to_ctype(
    shader_type : str,
) -> type[ctypes.Array[Any]]:  # pyright: ignore[reportExplicitAny]
    match shader_type:
        case 'mat4':
            return (ctypes.c_float * 4) * 4
        case 'vec4':
            return ctypes.c_float * 4
        case 'ivec4':
            return ctypes.c_int * 4
        case _:
            assert False, f'Unhandled shader type {shader_type}'

def shader_struct_to_UBO(
    shadername : str,
    struct : ShaderStruct,
    varname : str,
):
    import ctypes
    # copied+modified from scripts/addons/mesh_snap_utitilies_line/drawing_utilities.py
    class GPU_UBO(ctypes.Structure):
        _pack_ : ClassVar[int] = 16
        _fields_ : ClassVar[Sequence[
            tuple[str, type[
                ctypes._SimpleCData[Any] |  # pyright: ignore[reportPrivateUsage, reportExplicitAny]
                ctypes._Pointer[Any] |  # pyright: ignore[reportPrivateUsage, reportExplicitAny]
                _ctypes.CFuncPtr |
                _ctypes.Union |
                _ctypes.Structure |
                ctypes.Array[Any]  # pyright: ignore[reportExplicitAny]
            ]] | tuple[str, type[
                ctypes._SimpleCData[Any] |  # pyright: ignore[reportPrivateUsage, reportExplicitAny]
                ctypes._Pointer[Any] |  # pyright: ignore[reportPrivateUsage, reportExplicitAny]
                _ctypes.CFuncPtr |
                _ctypes.Union |
                _ctypes.Structure |
                ctypes.Array[Any]  # pyright: ignore[reportExplicitAny]
            ], int]
        ]] = [
            shader_var_to_ctype(var_type, var_name)
            for (var_type, var_name) in struct.attribs
        ]
    ubo_data = GPU_UBO()
    ubo_data_size = ctypes.sizeof(ubo_data)
    ubo_data_slots = ubo_data_size // ctypes.sizeof(ctypes.c_float)
    ubo_data_object = cast(Sequence[int], cast(object, ubo_data))  # this line does nothing but solves type hinting
    # if False:
    #     term_printer.boxed(
    #         f'Struct: "{struct["name"]} {varname}" ({ubo_data_size}bytes, {ubo_data_slots}slots)',
    #         f'Attribs: ' + '; '.join(f'{k} {v}' for (k,v) in struct['attribs']),
    #         title=f'GPU Shader Struct: {shadername}',
    #     )
    ubo_buffer = gpu.types.Buffer('UBYTE', ubo_data_size, ubo_data_object)
    ubo = gpu.types.GPUUniformBuf(ubo_buffer)

    def setter(name : str, value : Matrix | Sequence[float] | Sequence[int] | Vector | Color4 | BColor | MColor | bpy_prop_array[float]):
        # print(f'UBO_Wrapper.set {name} = {value} ({type(value)})')
        shader_type = struct.types[name]
        match shader_type:
            case 'mat4':
                assert isinstance(value, Matrix), f'Expected Matrix, not {type(value)} ({value})'
                a = getattr(ubo_data, name)
                CType = shader_type_to_ctype('vec4')
                if len(value) == 3:
                    value = value.to_4x4()
                assert len(value) == 4 and len(value[0]) == 4
                a[0] = CType(value[0][0], value[1][0], value[2][0], value[3][0])
                a[1] = CType(value[0][1], value[1][1], value[2][1], value[3][1])
                a[2] = CType(value[0][2], value[1][2], value[2][2], value[3][2])
                a[3] = CType(value[0][3], value[1][3], value[2][3], value[3][3])

            case 'vec4' | 'ivec4':
                assert isinstance(value, (
                    Sequence, Vector, Color4, BColor, MColor, bpy_prop_array
                )), f'Expected Sequence, not {type(value)} ({value})'
                CType = shader_type_to_ctype(shader_type)
                l = len(value)
                assert 2 <= l <= 4, f'Expected Sequence of length 2--4, not {l} ({value})'
                if l == 2:
                    value = (*value, 0.0, 0.0)
                elif l == 3:
                    value = (*value, 0.0)
                setattr(ubo_data, name, CType(*value))

            case _:
                assert False, f'Unhandled type {shader_type}'

    class UBO_Wrapper:
        def __init__(self):
            pass

        def set_shader(self, shader : GPUShader):
            self.__dict__['_shader'] = shader

        def __setattr__(
            self,
            name : str,
            value : Matrix | Sequence[float] | Sequence[int] | Vector | Color4 | BColor | MColor | bpy_prop_array[float],
        ):
            self.assign(name, value)

        def slots_used(self):
            return ubo_data_slots

        def assign(
            self,
            name : str,
            value : Matrix | Sequence[float] | Sequence[int] | Vector | Color4 | BColor | MColor | bpy_prop_array[float],
        ):
            try:
                setter(name, value)
            except Exception as e:
                print(f'Caught Exception while trying to set {name} = {value}')
                print(f'  Shader:    {shadername}')
                print(f'  Exception: {e}')

        def update_shader(self, *, debug_print : bool = False):
            try:
                if debug_print:
                    print(f'UPDATING SHADER: {shadername} {varname}')
                shader = self.__dict__['_shader']
                buf = gpu.types.Buffer('UBYTE', ubo_data_size, ubo_data_object)
                if debug_print:
                    print(buf)
                ubo.update(buf)
                shader.uniform_block(varname, ubo)
                del buf
            except Exception as e:
                print('Caught Exception while trying to update shader')
                print(f'  Shader:    {shadername}')
                print(f'  Struct:    {struct.name}')
                print(f'  Variable:  {varname}')
                print(f'  Exception: {e}')

    return UBO_Wrapper()


GPUTYPES = Literal[
    "FLOAT",
    "VEC2",
    "VEC3",
    "VEC4",
    "MAT3",
    "MAT4",
    "UINT",
    "UVEC2",
    "UVEC3",
    "UVEC4",
    "INT",
    "IVEC2",
    "IVEC3",
    "IVEC4",
    "BOOL",
]

gpu_type_size = {
    'bool',
    'uint',  'uvec2', 'uvec3', 'uvec4',
    'int',   'ivec2', 'ivec3', 'ivec4',
    'float', 'vec2',  'vec3',  'vec4',
                      'mat3',  'mat4',
}
def glsl_to_gpu_type(t : str) -> GPUTYPES:
    return cast(GPUTYPES, t.upper() if t in gpu_type_size else t)

re_shader_location = re.compile(r'location *= *(?P<location>\d+)')
def gpu_shader(
    name: str,
    vert_source: str,
    frag_source: str,
    *,
    defines : dict[object, object] | None = None,
) -> tuple[GPUShader, Dict]:
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

    # if False:
    #     def nonetoempty(s): return s if s else ''
    #     def divider(s): return f'\n{"═"*5}╡ {s} ╞{"═"*(120-(len(s) + 4 + 5))}\n\n'
    #     term_printer.boxed(
    #         *(ss['full'] for ss in vert_shader_structs.values()),
    #         divider('Uniforms, Inputs, InOuts, Outputs'),
    #         f'{"Layout":12s} {"Qualifier":13s} {"UIO":7s} {"Type":10s} {"Var Name":20s} {"Def Val"}',
    #         f'{"-"*12        } {"-"*13         } {"-"*7   } {"-"*10    } {"-"*20        } {"-"*(120-(12+1+13+1+7+1+10+1+20+1))}',
    #         *(
    #             f'{nonetoempty(sv["layout"]):12s} '
    #             f'{nonetoempty(sv["qualifier"]):13s} '  # noperspective
    #             f'{nonetoempty(sv["uio"]):7s} '         # uniform
    #             f'{nonetoempty(sv["type"]):10s} '
    #             f'{nonetoempty(sv["var"]):20s} '
    #             f'{nonetoempty(sv["defval"])}'
    #             for sv in chain(uniform_vars.values(), in_vars.values(), inout_vars.values(), out_vars.values())
    #         ),
    #         divider('Vertex Shader'),
    #         vert_source,
    #         divider('Fragment Shader'),
    #         frag_source,
    #         title=f'GPUSader {name}'
    #     )

    shader_info = gpu.types.GPUShaderCreateInfo()

    # STRUCTS
    # Note: as of 2023.06.04, multiple structs caused compiler errors that were difficult to debug.
    #       I believe it is due to how Blender constructs the platform-specific shader from the GPU shader.
    assert len(shader_structs) <= 1, f'Cannot support shaders with more than one struct, found {len(shader_structs)} in {name}'
    for struct in shader_structs.values():
        # print(f'typedef_source("{struct["full"]}")')
        shader_info.typedef_source(struct.full)
    UBOs = Dict()
    def update_shader(*, debug_print : bool = False):
        for n in UBOs:
            if n in ['update_shader', 'set_shader']:
                continue
            UBOs[n].update_shader(debug_print=debug_print)
    UBOs.update_shader = update_shader
    def set_shader(shader : GPUShader):
        for n in UBOs:
            if n in ['update_shader', 'set_shader']:
                continue
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
                if slot is None:
                    slot = slot_samplers
                shader_info.sampler(slot, 'FLOAT_2D', uniform_var['var'])
                slot_samplers = max(slot + 1, slot_samplers)

            case t if t in gpu_type_size:
                shader_info.push_constant(glsl_to_gpu_type(uniform_var['type']), uniform_var['var'])

            case _:
                if slot is None:
                    slot = slot_structs
                shader_info.uniform_buf(slot, uniform_var['type'], uniform_var['var'])
                ubo_wrapper = shader_struct_to_UBO(name, shader_structs[uniform_var['type']], uniform_var['var'])
                UBOs[uniform_var['var']] = ubo_wrapper
                # print(f'uniform struct {uniform_var["type"]} {uniform_var["var"]} {slot=}')
                slot_structs = max(slot + ubo_wrapper.slots_used(), slot_structs)

    # if False:
    #     term_printer.boxed(
    #         str(UBOs),
    #         title=f'Uniforms'
    #     )

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

    # if False:
    #     print(shader_vars)
    #     print(vert_source)
    #     print(frag_source)

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
    _width:int = -42
    _height : int = -42
    _is_bound : bool = False
    _matrix : Matrix
    _tex_color : GPUTexture
    _tex_depth : GPUTexture
    _framebuffer : GPUFrameBuffer
    _cur_fbo : GPUFrameBuffer | None = None
    _cur_viewport : tuple[int,int,int,int] | None = None
    _cur_projection : Matrix | None = None

    def __init__(self, width : int, height : int):
        self.resize(width, height)

    def resize(self, width : int, height : int, clear_color : bool = True, clear_depth : bool = True):
        assert not self._is_bound, 'Cannot resize a bounded FrameBuffer'

        width, height = max(1, int(width)), max(1, int(height))
        if self._width == width and self._height == height:
            return
        self._width, self._height = width, height

        vx, vy, vw, vh = -1, -1, 2 / self._width, 2 / self._height
        self._matrix = Matrix([
            [vw,  0,  0, vx],
            [ 0, vh,  0, vy],
            [ 0,  0,  1,  0],
            [ 0,  0,  0,  1],
        ])

        self._tex_color = GPUTexture((self._width, self._height), format='RGBA8')
        self._tex_depth = GPUTexture((self._width, self._height), format='DEPTH_COMPONENT32F')

        self._framebuffer = GPUFrameBuffer(
            color_slots={ 'texture': self._tex_color },
            depth_slot=self._tex_depth,
        )

    @property
    def color_texture(self) -> GPUTexture:
        return self._tex_color
    @property
    def width(self) -> int:
        return self._width
    @property
    def height(self) -> int:
        return self._height

    def _set_viewport(self):
        o = self._framebuffer if False else gpu.state
        o.viewport_set(0, 0, self._width, self._height)
    def _reset_viewport(self):
        if self._cur_viewport:
            o = self._cur_fbo if False else gpu.state
            o.viewport_set(*self._cur_viewport)

    def _set_projection(self):
        gpu.matrix.load_projection_matrix(self._matrix)
    def _reset_projection(self):
        if self._cur_projection:
            gpu.matrix.load_projection_matrix(self._cur_projection)

    def _set_scissor(self):
        ScissorStack.push(0, self._height - 1, self._width, self._height, clamp=False)
    def _reset_scissor(self):
        ScissorStack.pop()

    def _clear(self):
        self._framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0), depth=1.0)

    @contextmanager
    def bind(self) -> Generator[None, None, None]:
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
            print('Caught exception while FrameBuffer was bound:')
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
    is_started : bool = False
    scissor_test_was_enabled : bool = False
    stack : None | list[tuple[int,int,int,int]] = None                        # stack of (l,t,w,h) in region-coordinates, because viewport is set to region
    msg_stack : None | list[str] = None

    @staticmethod
    def start(context:Context):
        assert not ScissorStack.is_started, 'Attempting to start a started ScissorStack'

        # region pos and size are window-coordinates
        rgn = context.region
        _rl,rb,rw,rh = rgn.x, rgn.y, rgn.width, rgn.height
        _rt = rb + rh - 1

        # remember the current scissor box settings so we can return to them when done
        ScissorStack.scissor_test_was_enabled = get_scissor_test()
        if ScissorStack.scissor_test_was_enabled:
            pl, pb, pw, ph = get_scissor() #ScissorStack.buf
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
    def end(force:bool=False):
        if not force:
            assert ScissorStack.is_started, 'Attempting to end a non-started ScissorStack'
            assert ScissorStack.stack is not None
            assert len(ScissorStack.stack) == 1, 'Attempting to end a non-empty ScissorStack (size: %d)' % (len(ScissorStack.stack)-1)
        scissor_test(ScissorStack.scissor_test_was_enabled)
        ScissorStack.is_started = False
        ScissorStack.stack = None

    @staticmethod
    def _set_scissor():
        assert ScissorStack.stack is not None and ScissorStack.is_started, 'Attempting to set scissor settings with non-started ScissorStack'
        # print(f'ScissorStack: {ScissorStack.stack}')
        l,t,w,h = ScissorStack.stack[-1]
        b = t - (h - 1)
        scissor(l, b, w, h)

    @staticmethod
    def push(nl:int, nt:int, nw:int, nh:int, *, msg:str='', clamp:bool=True):
        # note: pos and size are already in region-coordinates, but it is specified from top-left corner

        assert ScissorStack.stack is not None and ScissorStack.msg_stack is not None and ScissorStack.is_started, 'Attempting to push to a non-started ScissorStack!'

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
        assert ScissorStack.stack is not None and ScissorStack.msg_stack is not None and len(ScissorStack.stack) > 1, 'Attempting to pop from empty ScissorStack!'
        _ = ScissorStack.stack.pop()
        _ = ScissorStack.msg_stack.pop()
        ScissorStack._set_scissor()

    @staticmethod
    @contextmanager
    def wrap(nl:int, nt:int, nw:int, nh:int, *, msg:str='', clamp:bool=True, disabled:bool=False):
        if disabled:
            yield None
            return
        try:
            ScissorStack.push(nl, nt, nw, nh, msg=msg, clamp=clamp)
            yield None
            ScissorStack.pop()
        except Exception as e:
            ScissorStack.pop()
            print('Caught exception while scissoring')
            print(f'  {nl,nt,nw,nh} {msg=} {clamp=} {disabled=}')
            print(f'  Exception: {e}')
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
        if not ScissorStack.stack or not ScissorStack.msg_stack:
            return
        for i,st in enumerate(ScissorStack.stack):
            l, t, w, h = st
            #r, b = l + (w - 1), t - (h - 1)
            print(('  '*i) + str((l,t,w,h)) + ' ' + ScissorStack.msg_stack[i])

    @staticmethod
    def is_visible():
        _vl,_vt,vw,vh = ScissorStack.get_current_view()
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
