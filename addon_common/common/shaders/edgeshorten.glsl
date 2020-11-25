uniform vec2 uScreenSize;
uniform mat4 uMVPMatrix;

attribute vec4  vPos;
attribute vec4  vFrom;
attribute vec4  vColor;
attribute float vRadius;

varying vec4 aColor;


/////////////////////////////////////////////////////////////////////////
// vertex shader

#version 330

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


/////////////////////////////////////////////////////////////////////////
// fragment shader

#version 330

out vec4 outColor;

void main() {
    outColor = aColor;
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
