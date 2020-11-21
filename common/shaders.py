'''
Copyright (C) 2020 CG Cookie

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

from .debug import dprint
from .globals import Globals
from .decorators import blender_version_wrapper
from .utils import kwargs_splitter

from ..ext.bgl_ext import VoidBufValue

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
print('Addon Common: (shaders) GLSL Version:', bgl.glGetString(bgl.GL_SHADING_LANGUAGE_VERSION))

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

        bgl.glCompileShader(shader)

        # report shader compilation log (if any)
        bufLogLen = bgl.Buffer(bgl.GL_INT, 1)
        bgl.glGetShaderiv(shader, bgl.GL_INFO_LOG_LENGTH, bufLogLen)
        if bufLogLen[0] > 0:
            # report log available
            bufLog = bgl.Buffer(bgl.GL_BYTE, bufLogLen)
            bgl.glGetShaderInfoLog(shader, bufLogLen[0], bufLogLen, bufLog)
            log = ''.join(chr(v) for v in bufLog.to_list() if v)
            if log:
                print('SHADER REPORT %s' % name)
                print('\n'.join(['    %s'%l for l in log.splitlines()]))
            else:
                print('Shader %s has no report' % name)
        else:
            log = ''

        # report shader compilation status
        bufStatus = bgl.Buffer(bgl.GL_INT, 1)
        bgl.glGetShaderiv(shader, bgl.GL_COMPILE_STATUS, bufStatus)
        if bufStatus[0] == 0:
            print('ERROR WHILE COMPILING SHADER %s' % name)
            print('\n'.join(['   % 4d  %s'%(i+1,l) for (i,l) in enumerate(src.splitlines())]))
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
        assert '// vertex shader' in lines, 'could not detect vertex shader'
        assert '// fragment shader' in lines, 'could not detect fragment shader'
        for line in lines:
            if line.startswith('uniform '):
                uniforms.append(line)
            elif line.startswith('attribute '):
                attributes.append(line)
            elif line.startswith('varying '):
                varyings.append(line)
            elif line.startswith('const '):
                m = re.match(r'const +(?P<type>bool|int|float) +(?P<var>[a-zA-Z0-9_]+) *= *(?P<val>[^;]+);', line)
                if m is None:
                    print('Shader could not match const line:', line)
                elif m.group('var') in constant_overrides:
                    line = 'const %s %s = %s' % (m.group('type'), m.group('var'), constant_overrides[m.group('var')])
                consts.append(line)
            elif line.startswith('#define '):
                m0 = re.match(r'#define +(?P<var>[a-zA-Z0-9_]+)$', line)
                m1 = re.match(r'#define +(?P<var>[a-zA-Z0-9_]+) +(?P<val>.+)$', line)
                if m0 and m0.group('var') in define_overrides:
                    if not define_overrides[m0.group('var')]:
                        line = ''
                if m1 and m1.group('var') in define_overrides:
                    line = '#define %s %s' % (m1.group('var'), define_overrides[m1.group('var')])
                if not m0 and not m1:
                    print('Shader could not match #define line:', line)
                consts.append(line)
            elif line.startswith('#version '):
                if mode == 'vert':
                    vertVersion = line
                elif mode == 'geo':
                    geoVersion = line
                elif mode == 'frag':
                    fragVersion = line
            elif line == '// vertex shader':
                mode = 'vert'
            elif line == '// geometry shader':
                mode = 'geo'
            elif line == '// fragment shader':
                mode = 'frag'
            else:
                if not line.strip(): continue
                if mode == 'vert':
                    vertSource.append(line)
                elif mode == 'geo':
                    geoSource.append(line)
                elif mode == 'frag':
                    fragSource.append(line)
                else:
                    commonSource.append(line)
        v_attributes = [a.replace('attribute ', 'in ') for a in attributes]
        v_varyings = [v.replace('varying ', 'out ') for v in varyings]
        f_varyings = [v.replace('varying ', 'in ') for v in varyings]
        srcVertex = '\n'.join(
            ([vertVersion] if includeVersion else []) +
            uniforms + v_attributes + v_varyings + consts + commonSource + vertSource
        )
        srcFragment = '\n'.join(
            ([fragVersion] if includeVersion else []) +
            uniforms + f_varyings + consts +
            [Shader.get_srgb_shim(force=force_shim)] +
            ['/////////////////////'] +
            commonSource + fragSource
        )
        return (srcVertex, srcFragment)

    @staticmethod
    def parse_file(filename, includeVersion=True, constant_overrides=None, define_overrides=None, force_shim=False):
        filename_guess = os.path.join(os.path.dirname(__file__), 'shaders', filename)
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

        self.checkErrors = checkErrors

        srcVertex   = '\n'.join(l for l in srcVertex.split('\n'))
        srcFragment = '\n'.join(l for l in srcFragment.split('\n'))

        bgl.glShaderSource(self.shaderVert, srcVertex)
        bgl.glShaderSource(self.shaderFrag, srcFragment)

        dprint('RetopoFlow Shader Info: %s (%d)' % (self.name,self.shaderProg))
        logv = self.shader_compile(name, self.shaderVert, srcVertex)
        logf = self.shader_compile(name, self.shaderFrag, srcFragment)
        if len(logv.strip()):
            print('  vert log:\n' + '\n'.join(('    '+l) for l in logv.splitlines()))
        if len(logf.strip()):
            print('  frag log:\n' + '\n'.join(('    '+l) for l in logf.splitlines()))

        bgl.glAttachShader(self.shaderProg, self.shaderVert)
        bgl.glAttachShader(self.shaderProg, self.shaderFrag)

        if bindTo0:
            bgl.glBindAttribLocation(self.shaderProg, 0, bindTo0)

        bgl.glLinkProgram(self.shaderProg)

        self.shaderVars = {}
        lvars = [l for l in srcVertex.splitlines() if l.startswith('in ')]
        lvars += [l for l in srcVertex.splitlines() if l.startswith('attribute ')]
        lvars += [l for l in srcVertex.splitlines() if l.startswith('uniform ')]
        lvars += [l for l in srcFragment.splitlines() if l.startswith('uniform ')]
        for l in lvars:
            m = re.match('^(?P<qualifier>[^ ]+) +(?P<type>[^ ]+) +(?P<name>[^ ;]+)', l)
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

        dprint('  attribs: ' + ', '.join((k + ' (%d)'%self.shaderVars[k]['location']) for k in self.shaderVars if self.shaderVars[k]['qualifier'] in {'in','attribute'}))
        dprint('  uniforms: ' + ', '.join((k + ' (%d)'%self.shaderVars[k]['location']) for k in self.shaderVars if self.shaderVars[k]['qualifier'] in {'uniform'}))

        self.funcStart = funcStart
        self.funcEnd = funcEnd
        self.mvpmatrix_buffer = bgl.Buffer(bgl.GL_FLOAT, [4,4])

    def __setitem__(self, varName, varValue): self.assign(varName, varValue)

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
                    dprint('ASSIGNING TO UNUSED ATTRIBUTE (%s): %s = %s' % (self.name, varName,str(varValue)))
                    v['reported'] = True
                return
            if DEBUG_PRINT:
                print('%s (%s,%d,%s) = %s' % (varName, q, l, t, str(varValue)))
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
                    assert False, 'Unhandled type %s for attrib %s' % (t, varName)
                if self.checkErrors:
                    self.drawing.glCheckError('assign attrib %s = %s' % (varName, str(varValue)))
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
                    assert False, 'Unhandled type %s for uniform %s' % (t, varName)
                if self.checkErrors:
                    self.drawing.glCheckError('assign uniform %s (%s %d) = %s' % (varName, t, l, str(varValue)))
            else:
                assert False, 'Unhandled qualifier %s for variable %s' % (q, varName)
        except Exception as e:
            print('ERROR Shader.assign(%s, %s)): %s' % (varName, str(varValue), str(e)))

    def enableVertexAttribArray(self, varName):
        assert varName in self.shaderVars, 'Variable %s not found' % varName
        v = self.shaderVars[varName]
        q,l,t = v['qualifier'],v['location'],v['type']
        if l == -1:
            if not v['reported']:
                print('COULD NOT FIND %s' % (varName))
                v['reported'] = True
            return
        if DEBUG_PRINT:
            print('enable vertattrib array: %s (%s,%d,%s)' % (varName, q, l, t))
        bgl.glEnableVertexAttribArray(l)
        if self.checkErrors:
            self.drawing.glCheckError('enableVertexAttribArray %s' % varName)

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
                print('COULD NOT FIND %s' % (varName))
                v['reported'] = True
            return

        if DEBUG_PRINT:
            print('assign (enable=%s) vertattrib pointer: %s (%s,%d,%s) = %d (%dx%s,normalized=%s,stride=%d)' % (str(enable), varName, q, l, t, vbo, size, self.gltype_names[gltype], str(normalized),stride))
        bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, vbo)
        bgl.glVertexAttribPointer(l, size, gltype, normalized, stride, buf)
        if self.checkErrors: self.drawing.glCheckError('vertexAttribPointer %s' % varName)
        if enable: bgl.glEnableVertexAttribArray(l)
        if self.checkErrors: self.drawing.glCheckError('vertexAttribPointer %s' % varName)
        bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, 0)

    def disableVertexAttribArray(self, varName):
        assert varName in self.shaderVars, 'Variable %s not found' % varName
        v = self.shaderVars[varName]
        q,l,t = v['qualifier'],v['location'],v['type']
        if l == -1:
            if not v['reported']:
                print('COULD NOT FIND %s' % (varName))
                v['reported'] = True
            return
        if DEBUG_PRINT:
            print('disable vertattrib array: %s (%s,%d,%s)' % (varName, q, l, t))
        bgl.glDisableVertexAttribArray(l)
        if self.checkErrors:
            self.drawing.glCheckError('disableVertexAttribArray %s' % varName)

    def useFor(self,funcCallback):
        try:
            bgl.glUseProgram(self.shaderProg)
            if self.funcStart: self.funcStart(self)
            funcCallback(self)
        except Exception as e:
            print('ERROR WITH USING SHADER: ' + str(e))
        finally:
            bgl.glUseProgram(0)

    def enable(self):
        try:
            if DEBUG_PRINT:
                print('enabling shader <==================')
                if self.checkErrors:
                    self.drawing.glCheckError('using program (%s, %d) pre' % (self.name, self.shaderProg))
            bgl.glUseProgram(self.shaderProg)
            if self.checkErrors:
                self.drawing.glCheckError('using program (%s, %d) post' % (self.name, self.shaderProg))

            # special uniforms
            # - uMVPMatrix works around deprecated gl_ModelViewProjectionMatrix
            if 'uMVPMatrix' in self.shaderVars:
                mvpmatrix = bpy.context.region_data.perspective_matrix
                mvpmatrix_buffer = bgl.Buffer(bgl.GL_FLOAT, [4,4], mvpmatrix)
                self.assign('uMVPMatrix', mvpmatrix_buffer)

            if self.funcStart: self.funcStart(self)
        except Exception as e:
            print('Error with using shader: ' + str(e))
            bgl.glUseProgram(0)

    def disable(self):
        if DEBUG_PRINT:
            print('disabling shader <=================')
        if self.checkErrors:
            self.drawing.glCheckError('disable program (%d) pre' % self.shaderProg)
        try:
            if self.funcEnd: self.funcEnd(self)
        except Exception as e:
            print('Error with shader: ' + str(e))
        bgl.glUseProgram(0)
        if self.checkErrors:
            self.drawing.glCheckError('disable program (%d) post' % self.shaderProg)



brushStrokeShader = Shader.load_from_file('brushStrokeShader', 'brushstroke.glsl', checkErrors=False, bindTo0='vPos', force_shim=True)
edgeShortenShader = Shader.load_from_file('edgeShortenShader', 'edgeshorten.glsl', checkErrors=False, bindTo0='vPos', force_shim=True)
arrowShader = Shader.load_from_file('arrowShader', 'arrow.glsl', checkErrors=False, force_shim=True)

def circleShaderStart(shader):
    bgl.glDisable(bgl.GL_POINT_SMOOTH)
    bgl.glEnable(bgl.GL_POINT_SPRITE)
def circleShaderEnd(shader):
    bgl.glDisable(bgl.GL_POINT_SPRITE)
circleShader = Shader.load_from_file('circleShader', 'circle.glsl', checkErrors=False, funcStart=circleShaderStart, funcEnd=circleShaderEnd, force_shim=True)


