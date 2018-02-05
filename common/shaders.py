import bgl
from ..lib.common_utilities import invert_matrix, matrix_normal, dprint
from ..lib.common_shader import Shader

# note: not all supported by user system, but we don't need latest functionality
# https://github.com/mattdesl/lwjgl-basics/wiki/GLSL-Versions
# OpenGL  GLSL    OpenGL  GLSL
#  2.0    110      2.1    120
#  3.0    130      3.1    140
#  3.2    150      3.3    330
#  4.0    400      4.1    410
#  4.2    420      4.3    430
dprint('GLSL Version: ' + bgl.glGetString(bgl.GL_SHADING_LANGUAGE_VERSION))


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

