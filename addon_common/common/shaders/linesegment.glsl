uniform vec2 uScreenSize;
uniform mat4 uMVPMatrix;

uniform vec2 uPos0;
uniform vec2 uPos1;
uniform vec4 uColor0;
uniform vec4 uColor1;
uniform float uWidth;

uniform vec2 uStipple;
uniform float uStippleOffset;

attribute vec2 aWeight;

varying vec4  vPos;
varying float vDist;

/////////////////////////////////////////////////////////////////////////
// vertex shader

#version 330

void main() {
    vec2 d01 = normalize(uPos1 - uPos0);
    vec2 perp = vec2(-d01.y, d01.x);
    float dist = distance(uPos0, uPos1);

    vec2 p =
        (1.0 - aWeight.x) * uPos0 +
        aWeight.x         * uPos1 +
        (aWeight.y - 0.5) * uWidth * perp;
    vPos = uMVPMatrix * vec4(p, 0.0, 1.0);
    vDist = dist * aWeight.x;
    gl_Position = vPos;
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

#version 330

out vec4 outColor;

void main() {
    float s = mod(vDist + uStippleOffset, uStipple.x + uStipple.y);
    if(s <= uStipple.x) {
        outColor = uColor0;
    } else {
        outColor = uColor1;
        if(uColor1.a <= 0) discard;
    }
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
