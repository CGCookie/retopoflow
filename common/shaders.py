'''
Copyright (C) 2018 CG Cookie

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


import re
import bpy
import bgl
import ctypes

from .ui import Drawing
from .debug import dprint

from ..ext.bgl_ext import VoidBufValue

# note: not all supported by user system, but we don't need latest functionality
# https://github.com/mattdesl/lwjgl-basics/wiki/GLSL-Versions
# OpenGL  GLSL    OpenGL  GLSL
#  2.0    110      2.1    120
#  3.0    130      3.1    140
#  3.2    150      3.3    330
#  4.0    400      4.1    410
#  4.2    420      4.3    430
dprint('GLSL Version: ' + bgl.glGetString(bgl.GL_SHADING_LANGUAGE_VERSION))

DEBUG_PRINT = False

vbv_zero = VoidBufValue(0)
buf_zero = vbv_zero.buf    #bgl.Buffer(bgl.GL_BYTE, 1, [0])


class Shader():
    @staticmethod
    def shader_compile(name, shader):
        '''
        logging and error-checking not quite working :(
        '''
        
        bufLen = bgl.Buffer(bgl.GL_BYTE, 4)
        bufLog = bgl.Buffer(bgl.GL_BYTE, 2000)
        
        bgl.glCompileShader(shader)
        
        # XXX: this test is a hack to determine whether the shader was compiled successfully
        # TODO: rewrite to use a more correct test (glIsShader?)
        bgl.glGetShaderInfoLog(shader, 2000, bufLen, bufLog)
        log = ''.join(chr(v) for v in bufLog.to_list() if v)
        assert not log and 'was successfully compiled' not in log, 'ERROR WHILE COMPILING SHADER %s: %s' % (name,log)
        return log
    
    def __init__(self, name, srcVertex, srcFragment, funcStart=None, funcEnd=None, checkErrors=True, bindTo0=None):
        self.drawing = Drawing.get_instance()
        
        self.name = name
        self.shaderProg = bgl.glCreateProgram()
        self.shaderVert = bgl.glCreateShader(bgl.GL_VERTEX_SHADER)
        self.shaderFrag = bgl.glCreateShader(bgl.GL_FRAGMENT_SHADER)
        
        self.checkErrors = checkErrors
        
        srcVertex   = '\n'.join(l.strip() for l in srcVertex.split('\n'))
        srcFragment = '\n'.join(l.strip() for l in srcFragment.split('\n'))
        
        bgl.glShaderSource(self.shaderVert, srcVertex)
        bgl.glShaderSource(self.shaderFrag, srcFragment)
        
        dprint('RetopoFlow Shader Info: %s (%d)' % (self.name,self.shaderProg))
        logv = self.shader_compile(name, self.shaderVert)
        logf = self.shader_compile(name, self.shaderFrag)
        if len(logv.strip()):
            dprint('  vert log:\n' + '\n'.join(('    '+l) for l in logv.splitlines()))
        if len(logf.strip()):
            dprint('  frag log:\n' + '\n'.join(('    '+l) for l in logf.splitlines()))
        
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
            print('ERROR (assign): ' + str(e))
    
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
        if self.checkErrors:
            self.drawing.glCheckError('vertexAttribPointer %s' % varName)
        if enable: bgl.glEnableVertexAttribArray(l)
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
                    self.drawing.glCheckError('using program (%d) pre' % self.shaderProg)
            bgl.glUseProgram(self.shaderProg)
            if self.checkErrors:
                self.drawing.glCheckError('using program (%d) post' % self.shaderProg)
            
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





brushStrokeShader = Shader('brushStrokeShader', '''
        #version 120
        
        uniform mat4 uMVPMatrix;
        
        attribute vec2  vPos;
        attribute vec4  vColor;
        attribute float vDistAccum;
        
        varying vec4  aColor;
        varying float aDistAccum;
        
        void main() {
            gl_Position = uMVPMatrix * vec4(vPos, 0.0, 1.0);
            aColor = vColor;
            aDistAccum = vDistAccum;
        }
    ''', '''
        #version 120
        
        varying vec4 aColor;
        varying float aDistAccum;
        
        void main() {
            if(mod(int(aDistAccum / 2), 4) >= 2) discard;
            gl_FragColor = aColor;
        }
    ''', checkErrors=False, bindTo0='vPos')

edgeShortenShader = Shader('edgeShortenShader', '''
        #version 120
        
        uniform vec2 uScreenSize;
        uniform mat4 uMVPMatrix;
        
        attribute vec4  vPos;
        attribute vec4  vFrom;
        attribute vec4  vColor;
        attribute float vRadius;
        
        varying vec4 aColor;
        
        void main() {
            vec4 p0 = uMVPMatrix * vPos;
            vec4 p1 = uMVPMatrix * vFrom;
            
            vec2 s0 = uScreenSize * p0.xy / p0.w;
            vec2 s1 = uScreenSize * p1.xy / p1.w;
            vec2 d = normalize(s1 - s0);
            vec2 s2 = s0 + d * vRadius;
            
            gl_Position = vec4(s2 / uScreenSize * p0.w, p0.z, p0.w);
            aColor = vColor;
        }
    ''', '''
        #version 120
        
        varying vec4 aColor;
        
        void main() {
            gl_FragColor = aColor;
        }
    ''', checkErrors=False, bindTo0='vPos')


def circleShaderStart(shader):
    bgl.glDisable(bgl.GL_POINT_SMOOTH)
    bgl.glEnable(bgl.GL_POINT_SPRITE)
def circleShaderEnd(shader):
    bgl.glDisable(bgl.GL_POINT_SPRITE)
circleShader = Shader('circleShader', '''
        #version 120
        
        uniform mat4 uMVPMatrix;
        
        attribute vec4 vPos;
        attribute vec4 vInColor;
        attribute vec4 vOutColor;
        
        varying vec4 aInColor;
        varying vec4 aOutColor;
        
        void main() {
            gl_Position = uMVPMatrix * vPos;
            aInColor    = vInColor;
            aOutColor   = vOutColor;
        }
    ''', '''
        #version 120
        
        uniform float uInOut;
        
        varying vec4 aInColor;
        varying vec4 aOutColor;
        
        void main() {
            float d = 2.0 * distance(gl_PointCoord, vec2(0.5, 0.5));
            if(d > 1.0) discard;
            gl_FragColor = (d > uInOut) ? aOutColor : aInColor;
        }
    ''', checkErrors=False, funcStart=circleShaderStart, funcEnd=circleShaderEnd)


arrowShader = Shader('arrowShader', '''
        #version 120

        uniform mat4 uMVPMatrix;
        
        attribute vec4 vPos;
        attribute vec4 vFrom;
        attribute vec4 vInColor;
        attribute vec4 vOutColor;

        varying float aRot;
        varying vec4 aInColor;
        varying vec4 aOutColor;

        float angle(vec2 d) { return atan(d.y, d.x); }

        void main() {
            vec4 p0 = uMVPMatrix * vFrom;
            vec4 p1 = uMVPMatrix * vPos;
            gl_Position = p1;
            aRot = angle((p1.xy / p1.w) - (p0.xy / p0.w));
            aInColor = vInColor;
            aOutColor = vOutColor;
        }
    ''', '''
        #version 120

        uniform float uInOut;
        
        varying float aRot;
        varying vec4 aInColor;
        varying vec4 aOutColor;

        float alpha(vec2 dir) {
            vec2 d0 = dir - vec2(1,1);
            vec2 d1 = dir - vec2(1,-1);
            
            float d0v = -d0.x/2.0 - d0.y;
            float d1v = -d1.x/2.0 + d1.y;
            float dv0 = length(dir);
            float dv1 = distance(dir, vec2(-2,0));
            
            if(d0v < 1.0 || d1v < 1.0) return -1.0;
            // if(dv0 > 1.0) return -1.0;
            if(dv1 < 1.3) return -1.0;
            
            if(d0v - 1.0 < (1.0 - uInOut) || d1v - 1.0 < (1.0 - uInOut)) return 0.0;
            //if(dv0 > uInOut) return 0.0;
            if(dv1 - 1.3 < (1.0 - uInOut)) return 0.0;
            return 1.0;
        }

        void main() {
            vec2 d = 2.0 * (gl_PointCoord - vec2(0.5, 0.5));
            vec2 dr = vec2(cos(aRot)*d.x - sin(aRot)*d.y, sin(aRot)*d.x + cos(aRot)*d.y);
            float a = alpha(dr);
            if(a < 0.0) discard;
            gl_FragColor = mix(aOutColor, aInColor, a);
        }
    ''', checkErrors=False)

