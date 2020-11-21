uniform mat4 uMVPMatrix;

attribute vec2  vPos;
attribute vec4  vColor;
attribute float vDistAccum;

varying vec4  aColor;
varying float aDistAccum;


/////////////////////////////////////////////////////////////////////////
// vertex shader

#version 330

void main() {
    gl_Position = uMVPMatrix * vec4(vPos, 0.0, 1.0);
    aColor = vColor;
    aDistAccum = vDistAccum;
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

#version 330

out vec4 outColor;

void main() {
    if(mod(int(aDistAccum / 2), 4) >= 2) discard;
    outColor = aColor;
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
