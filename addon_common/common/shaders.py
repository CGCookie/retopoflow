'''
Copyright (C) 2022 CG Cookie

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


import os
import re
import bpy
import bgl
import ctypes
from itertools import chain

from .blender import get_path_from_addon_common
from .debug import dprint
from .globals import Globals
from .decorators import blender_version_wrapper, only_in_blender_version, warn_once
from .utils import kwargs_splitter

from ..ext.bgl_ext import VoidBufValue

# https://www.khronos.org/registry/OpenGL-Refpages/gl2.1/xhtml/glGetString.xml
@only_in_blender_version('< 3.00')
def gpu_info_shaders():
    import bgl
    return f'{bgl.glGetString(bgl.GL_VENDOR)}, {bgl.glGetString(bgl.GL_RENDERER)}, {bgl.glGetString(bgl.GL_VERSION)}, {bgl.glGetString(bgl.GL_SHADING_LANGUAGE_VERSION)}'
@only_in_blender_version('>= 3.00')
@warn_once('gpustate.gpu_info cannot get shader version!')
def gpu_info_shaders():
    import gpu
    return f'{gpu.platform.vendor_get()}, {gpu.platform.renderer_get()}, {gpu.platform.version_get()}'

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
if not bpy.app.background:
    print(f'Addon Common: (shaders) {gpu_info_shaders()}')



DEBUG_PRINT = False

vbv_zero = VoidBufValue(0)
buf_zero = vbv_zero.buf    #bgl.Buffer(bgl.GL_BYTE, 1, [0])
Globals.buf_zero = buf_zero

class Shader():
    @staticmethod
    def shader_compile(name, shader, src):
        '''
        logging and error-checking not quite working :(
        '''

        Globals.drawing.glCheckError(f'Pre shader compile')
        bgl.glCompileShader(shader)
        Globals.drawing.glCheckError(f'Post shader compile {name}')

        # report shader compilation log (if any)
        bufLogLen = bgl.Buffer(bgl.GL_INT, 1)
        bgl.glGetShaderiv(shader, bgl.GL_INFO_LOG_LENGTH, bufLogLen)
        if bufLogLen[0] > 0:
            # report log available
            bufLog = bgl.Buffer(bgl.GL_BYTE, bufLogLen)
            bgl.glGetShaderInfoLog(shader, bufLogLen[0], bufLogLen, bufLog)
            log = ''.join(chr(v) for v in bufLog.to_list() if v)
            if log:
                print(f'SHADER REPORT {name}')
                print('\n'.join([f'    {l}' for l in log.splitlines()]))
            else:
                print(f'Shader {name} has no report')
        else:
            log = ''

        # report shader compilation status
        bufStatus = bgl.Buffer(bgl.GL_INT, 1)
        bgl.glGetShaderiv(shader, bgl.GL_COMPILE_STATUS, bufStatus)
        if bufStatus[0] == 0:
            print(f'ERROR WHILE COMPILING SHADER {name}')
            print('\n'.join([f'   {(i+1): 4d}  {l}' for (i,l) in enumerate(src.splitlines())]))
            assert False

        return log

    # https://developer.blender.org/rB21c658b718b9
    # https://developer.blender.org/T74139
    @staticmethod
    @blender_version_wrapper('<', '2.83')
    def get_srgb_shim(force=False):
        return 'vec4 blender_srgb_to_framebuffer_space(vec4 c) { return c; }'
    @staticmethod
    @blender_version_wrapper('>=', '2.83')
    def get_srgb_shim(force=False):
        if not force: return ''
        return 'vec4 blender_srgb_to_framebuffer_space(vec4 c) { return pow(c, vec4(1.0/2.2, 1.0/2.2, 1.0/2.2, 1.0)); }'

    @staticmethod
    def parse_string(string, includeVersion=True, constant_overrides=None, define_overrides=None, force_shim=False):
        # NOTE: GEOMETRY SHADER NOT FULLY SUPPORTED, YET
        #       need to find a way to handle in/out
        constant_overrides = constant_overrides or {}
        define_overrides = define_overrides or {}
        uniforms, varyings, attributes, consts = [],[],[],[]
        vertSource, geoSource, fragSource, commonSource = [],[],[],[]
        vertVersion, geoVersion, fragVersion = '','',''
        mode = None
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
                if   mode == 'vert': vertVersion = line
                elif mode == 'geo':  geoVersion  = line
                elif mode == 'frag': fragVersion = line
                else: vertVersion = geoVersion = fragVersion = line
            elif mode not in {'vert', 'geo', 'frag'} and re.match(r'precision ', sline):
                commonSource.append(line)
            elif re.match(r'//+ +vert(ex)? shader', sline.lower()):
                mode = 'vert'
            elif re.match(r'//+ +geo(m(etry)?)? shader', sline.lower()):
                mode = 'geo'
            elif re.match(r'//+ +frag(ment)? shader', sline.lower()):
                mode = 'frag'
            else:
                if not line.strip(): continue
                if   mode == 'vert': vertSource.append(line)
                elif mode == 'geo':  geoSource.append(line)
                elif mode == 'frag': fragSource.append(line)
                else:                commonSource.append(line)
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
            [Shader.get_srgb_shim(force=force_shim)],
            ['/////////////////////'],
            commonSource,
            fragSource,
        ))
        return (srcVertex, srcFragment)

    @staticmethod
    def parse_file(filename, includeVersion=True, constant_overrides=None, define_overrides=None, force_shim=False):
        filename_guess = get_path_from_addon_common('common', 'shaders', filename)
        if os.path.exists(filename):
            pass
        elif os.path.exists(filename_guess):
            filename = filename_guess
        else:
            assert False, "Shader file could not be found: %s" % filename

        string = open(filename, 'rt').read()
        return Shader.parse_string(string, includeVersion=includeVersion, constant_overrides=constant_overrides, define_overrides=define_overrides, force_shim=force_shim)

    @staticmethod
    def load_from_string(name, string, *args, **kwargs):
        srcVertex, srcFragment = Shader.parse_string(string)
        return Shader(name, srcVertex, srcFragment, *args, **kwargs)

    @staticmethod
    def load_from_file(name, filename, *args, **kwargs):
        # https://www.blender.org/api/blender_python_api_2_77_1/bgl.html
        # https://en.wikibooks.org/wiki/GLSL_Programming/Blender/Shading_in_View_Space
        # https://www.khronos.org/opengl/wiki/Built-in_Variable_(GLSL)

        kwargs_parse_file = kwargs_splitter({'force_shim'}, kwargs)
        srcVertex, srcFragment = Shader.parse_file(filename, **kwargs_parse_file)
        return Shader(name, srcVertex, srcFragment, *args, **kwargs)

    def __init__(self, name, srcVertex, srcFragment, funcStart=None, funcEnd=None, checkErrors=True, bindTo0=None):
        self.drawing = Globals.drawing

        self.name = name
        self.shaderProg = bgl.glCreateProgram()
        self.shaderVert = bgl.glCreateShader(bgl.GL_VERTEX_SHADER)
        self.shaderFrag = bgl.glCreateShader(bgl.GL_FRAGMENT_SHADER)

        self._checkErrors = checkErrors

        srcVertex   = '\n'.join(l for l in srcVertex.split('\n'))
        srcFragment = '\n'.join(l for l in srcFragment.split('\n'))

        bgl.glShaderSource(self.shaderVert, srcVertex)
        bgl.glShaderSource(self.shaderFrag, srcFragment)

        if DEBUG_PRINT: print(f'RetopoFlow Shader Info: {self.name} ({self.shaderProg})')
        logv = self.shader_compile(name, self.shaderVert, srcVertex).strip()
        logf = self.shader_compile(name, self.shaderFrag, srcFragment).strip()
        if logv or logf:
            if not DEBUG_PRINT: print(f'RetopoFlow Shader Info: {self.name} ({self.shaderProg})')
            if logv:
                print('  vert log:')
                print('\n'.join(f'    {l}' for l in logv.splitlines()))
            if logf:
                print('  frag log')
                print('\n'.join(f'    {l}' for l in logf.splitlines()))

        bgl.glAttachShader(self.shaderProg, self.shaderVert)
        bgl.glAttachShader(self.shaderProg, self.shaderFrag)

        if bindTo0:
            bgl.glBindAttribLocation(self.shaderProg, 0, bindTo0)

        bgl.glLinkProgram(self.shaderProg)

        self.shaderVars = {}
        lvars = []
        lvars += [l for l in srcVertex.splitlines()   if l.startswith('in ')]
        lvars += [l for l in srcVertex.splitlines()   if l.startswith('attribute ')]
        lvars += [l for l in srcVertex.splitlines()   if l.startswith('uniform ')]
        lvars += [l for l in srcFragment.splitlines() if l.startswith('uniform ')]
        for l in lvars:
            m = re.match(r'^(?P<qualifier>[^ ]+) +(?P<type>[^ ]+) +(?P<name>[^ ;]+)', l)
            assert m
            m = m.groupdict()
            q,t,n = m['qualifier'],m['type'],m['name']
            locate = bgl.glGetAttribLocation if q in {'in','attribute'} else bgl.glGetUniformLocation
            if n in self.shaderVars: continue
            self.shaderVars[n] = {
                'qualifier': q,
                'type': t,
                'location': locate(self.shaderProg, n),
                'reported': False,
                }

        if DEBUG_PRINT:
            print('  attribs: '  + ', '.join(f'{k} ({self.shaderVars[k]["location"]})' for k in self.shaderVars if self.shaderVars[k]['qualifier'] in {'in','attribute'}))
            print('  uniforms: ' + ', '.join(f'{k} ({self.shaderVars[k]["location"]})' for k in self.shaderVars if self.shaderVars[k]['qualifier'] in {'uniform'}))

        self.funcStart = funcStart
        self.funcEnd = funcEnd
        self.mvpmatrix_buffer = bgl.Buffer(bgl.GL_FLOAT, [4,4])

    def __setitem__(self, varName, varValue): self.assign(varName, varValue)

    def checkErrors(self, title):
        if not self._checkErrors: return
        self.drawing.glCheckError(title)

    def assign_buffer(self, varName, varValue):
        return self.assign(varName, bgl.Buffer(bgl.GL_FLOAT, [4,4], varValue))

    # https://www.opengl.org/sdk/docs/man/html/glVertexAttrib.xhtml
    # https://www.khronos.org/opengles/sdk/docs/man/xhtml/glUniform.xml
    def assign(self, varName, varValue):
        assert varName in self.shaderVars, 'Variable %s not found' % varName
        try:
            v = self.shaderVars[varName]
            q,l,t = v['qualifier'],v['location'],v['type']
            if l == -1:
                if not v['reported']:
                    print(f'ASSIGNING TO UNUSED ATTRIBUTE ({self.name}): {varName} = {varValue}')
                    v['reported'] = True
                return
            if DEBUG_PRINT:
                print(f'{varName} ({q},{l},{t}) = {varValue}')
            if q in {'in','attribute'}:
                if t == 'float':
                    bgl.glVertexAttrib1f(l, varValue)
                elif t == 'int':
                    bgl.glVertexAttrib1i(l, varValue)
                elif t == 'vec2':
                    bgl.glVertexAttrib2f(l, *varValue)
                elif t == 'vec3':
                    bgl.glVertexAttrib3f(l, *varValue)
                elif t == 'vec4':
                    bgl.glVertexAttrib4f(l, *varValue)
                else:
                    assert False, f'Unhandled type {t} for attrib {varName}'
                self.checkErrors(f'assign attrib {varName} = {varValue}')
            elif q in {'uniform'}:
                # cannot set bools with BGL! :(
                if t == 'float':
                    bgl.glUniform1f(l, varValue)
                elif t == 'vec2':
                    bgl.glUniform2f(l, *varValue)
                elif t == 'vec3':
                    bgl.glUniform3f(l, *varValue)
                elif t == 'vec4':
                    bgl.glUniform4f(l, *varValue)
                elif t == 'mat3':
                    bgl.glUniformMatrix3fv(l, 1, bgl.GL_TRUE, varValue)
                elif t == 'mat4':
                    bgl.glUniformMatrix4fv(l, 1, bgl.GL_TRUE, varValue)
                else:
                    assert False, f'Unhandled type {t} for uniform {varName}'
                self.checkErrors(f'assign uniform {varName} ({t} {l}) = {varValue}')
            else:
                assert False, 'Unhandled qualifier %s for variable %s' % (q, varName)
        except Exception as e:
            print(f'ERROR Shader.assign({varName}, {varValue})): {e}')

    def assign_all(self, **kwargs):
        for k,v in kwargs.items():
            self.assign(k, v)

    def enableVertexAttribArray(self, varName):
        assert varName in self.shaderVars, 'Variable %s not found' % varName
        v = self.shaderVars[varName]
        q,l,t = v['qualifier'],v['location'],v['type']
        if l == -1:
            if not v['reported']:
                print(f'COULD NOT FIND {varName}')
                v['reported'] = True
            return
        if DEBUG_PRINT:
            print(f'enable vertattrib array: {varName} ({q},{l},{t})')
        bgl.glEnableVertexAttribArray(l)
        self.checkErrors(f'enableVertexAttribArray {varName}')

    gltype_names = {
        bgl.GL_BYTE:'byte',
        bgl.GL_SHORT:'short',
        bgl.GL_UNSIGNED_BYTE:'ubyte',
        bgl.GL_UNSIGNED_SHORT:'ushort',
        bgl.GL_FLOAT:'float',
    }
    def vertexAttribPointer(self, vbo, varName, size, gltype, normalized=bgl.GL_FALSE, stride=0, buf=buf_zero, enable=True):
        assert varName in self.shaderVars, 'Variable %s not found' % varName
        v = self.shaderVars[varName]
        q,l,t = v['qualifier'],v['location'],v['type']
        if l == -1:
            if not v['reported']:
                print(f'COULD NOT FIND {varName}')
                v['reported'] = True
            return

        if DEBUG_PRINT:
            print(f'assign (enable={enable}) vertattrib pointer: {varName} ({q},{l},{t}) = {vbo} ({size}x{self.gltype_names[gltype]},normalized={normalized},stride={stride})')
        bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, vbo)
        bgl.glVertexAttribPointer(l, size, gltype, normalized, stride, buf)
        self.checkErrors(f'vertexAttribPointer {varName}')
        if enable: bgl.glEnableVertexAttribArray(l)
        self.checkErrors(f'vertexAttribPointer {varName}')
        bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, 0)

    def disableVertexAttribArray(self, varName):
        assert varName in self.shaderVars, f'Variable {varName} not found'
        v = self.shaderVars[varName]
        q,l,t = v['qualifier'],v['location'],v['type']
        if l == -1:
            if not v['reported']:
                print(f'COULD NOT FIND {varName}')
                v['reported'] = True
            return
        if DEBUG_PRINT:
            print(f'disable vertattrib array: {varName} ({q},{l},{t})')
        bgl.glDisableVertexAttribArray(l)
        self.checkErrors(f'disableVertexAttribArray {varName}')

    def useFor(self, funcCallback):
        try:
            bgl.glUseProgram(self.shaderProg)
            if self.funcStart: self.funcStart(self)
            funcCallback(self)
        except Exception as e:
            print(f'ERROR WITH USING SHADER: {e}')
        finally:
            bgl.glUseProgram(0)

    def enable(self):
        try:
            if DEBUG_PRINT:
                print('enabling shader <==================')
            self.checkErrors(f'using program ({self.name}, {self.shaderProg}) pre')
            bgl.glUseProgram(self.shaderProg)
            self.checkErrors(f'using program ({self.name}, {self.shaderProg}) post')

            # # special uniforms
            # # - uMVPMatrix works around deprecated gl_ModelViewProjectionMatrix
            # if 'uMVPMatrix' in self.shaderVars:
            #     mvpmatrix = bpy.context.region_data.perspective_matrix
            #     mvpmatrix_buffer = bgl.Buffer(bgl.GL_FLOAT, [4,4], mvpmatrix)
            #     self.assign('uMVPMatrix', mvpmatrix_buffer)

            if self.funcStart: self.funcStart(self)
        except Exception as e:
            print(f'Addon Common: Error with using shader: {e}')
            bgl.glUseProgram(0)

    def disable(self):
        if DEBUG_PRINT:
            print('disabling shader <=================')
        self.checkErrors(f'disable program ({self.name}, {self.shaderProg}) pre')
        try:
            if self.funcEnd: self.funcEnd(self)
        except Exception as e:
            print(f'Error with shader: {e}')
        bgl.glUseProgram(0)
        self.checkErrors(f'disable program ({self.name}, {self.shaderProg}) post')



# brushStrokeShader = Shader.load_from_file('brushStrokeShader', 'brushstroke.glsl', checkErrors=False, bindTo0='vPos', force_shim=True)
# edgeShortenShader = Shader.load_from_file('edgeShortenShader', 'edgeshorten.glsl', checkErrors=False, bindTo0='vPos', force_shim=True)
# arrowShader = Shader.load_from_file('arrowShader', 'arrow.glsl', checkErrors=False, force_shim=True)

# def circleShaderStart(shader):
#     bgl.glDisable(bgl.GL_POINT_SMOOTH)
#     bgl.glEnable(bgl.GL_POINT_SPRITE)
# def circleShaderEnd(shader):
#     bgl.glDisable(bgl.GL_POINT_SPRITE)
# circleShader = Shader.load_from_file('circleShader', 'circle.glsl', checkErrors=False, funcStart=circleShaderStart, funcEnd=circleShaderEnd, force_shim=True)


