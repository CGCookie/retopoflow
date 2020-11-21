uniform mat4 MVPMatrix;     // pixel matrix
uniform vec2 screensize;    // width,height of screen (for antialiasing)

uniform vec2 pos0;
uniform vec4 color0;

uniform vec2 pos1;
uniform vec4 color1;

uniform vec2 pos2;
uniform vec4 color2;


/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                // x: [0,1], alpha.  y: [0,1], beta

out vec4 color;

void main() {
    float a = clamp(pos.x, 0.0, 1.0);
    float b = clamp(pos.y, 0.0, 1.0);
    float c = 1.0 - a - b;
    vec2 p = pos0 * a + pos1 * b + pos2 * c;
    gl_Position = MVPMatrix * vec4(p, 0.0, 1.0);
    color = color0 * a + color1 * b + color2 * c;
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

in vec4 color;

out vec4 outColor;

void main() {
    outColor = color;
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}

