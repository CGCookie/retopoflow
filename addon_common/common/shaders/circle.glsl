uniform mat4 uMVPMatrix;
uniform float uInOut;

attribute vec4 vPos;
attribute vec4 vInColor;
attribute vec4 vOutColor;

varying vec4 aInColor;
varying vec4 aOutColor;


/////////////////////////////////////////////////////////////////////////
// vertex shader

#version 330

void main() {
    gl_Position = uMVPMatrix * vPos;
    aInColor    = vInColor;
    aOutColor   = vOutColor;
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

#version 330

out vec4 outColor;

void main() {
    float d = 2.0 * distance(gl_PointCoord, vec2(0.5, 0.5));
    if(d > 1.0) discard;
    outColor = (d > uInOut) ? aOutColor : aInColor;
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
