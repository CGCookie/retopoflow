#define PI    3.14159265359
#define TAU   6.28318530718

uniform mat4  MVPMatrix;        // pixel matrix
uniform vec3  center;           // center of circle
uniform vec4  color;            // color of circle
uniform vec3  plane_x;          // x direction in plane the circle lies in
uniform vec3  plane_y;          // y direction in plane the circle lies in
uniform float radius;           // radius of circle
uniform float width;            // line width, perpendicular to line (in plane)


/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // x: [0,1], ratio of circumference.  y: [0,1], inner/outer radius (width)

void main() {
    float ang = TAU * pos.x;
    float r = radius + pos.y * width;
    vec3 p = center + r * (plane_x * cos(ang) + plane_y * sin(ang));
    gl_Position = MVPMatrix * vec4(p, 1.0);
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

out vec4 outColor;

void main() {
    outColor = color;
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}

