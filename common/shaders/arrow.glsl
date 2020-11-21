uniform mat4 uMVPMatrix;
uniform float uInOut;

attribute vec4 vPos;
attribute vec4 vFrom;
attribute vec4 vInColor;
attribute vec4 vOutColor;

varying float aRot;
varying vec4 aInColor;
varying vec4 aOutColor;


/////////////////////////////////////////////////////////////////////////
// vertex shader

#version 330

float angle(vec2 d) { return atan(d.y, d.x); }

void main() {
    vec4 p0 = uMVPMatrix * vFrom;
    vec4 p1 = uMVPMatrix * vPos;
    gl_Position = p1;
    aRot = angle((p1.xy / p1.w) - (p0.xy / p0.w));
    aInColor = vInColor;
    aOutColor = vOutColor;
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

#version 330

out vec4 outColor;

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
    outColor = mix(aOutColor, aInColor, a);
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
