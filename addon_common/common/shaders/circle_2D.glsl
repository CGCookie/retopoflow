/*
draws an antialiased, stippled circle
ex: stipple [3,2]  color0 '='  color1 '-'
    produces  '===--===--===--===-'  (just wrapped as a circle!)
*/

#define PI    3.14159265359
#define TAU   6.28318530718

uniform vec2  screensize;       // width,height of screen (for antialiasing)
uniform mat4  MVPMatrix;        // pixel matrix
uniform vec2  center;           // center of circle
uniform float radius;           // radius of circle
uniform vec2  stipple;          // lengths of on/off stipple
uniform float stippleOffset;    // length to shift initial stipple of front
uniform vec4  color0;           // color of on stipple
uniform vec4  color1;           // color of off stipple
uniform float width;            // line width, perpendicular to line


/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // x: [0,1], ratio of circumference.  y: [0,1], inner/outer radius (width)

noperspective out vec2 vpos;    // position scaled by screensize
noperspective out vec2 cpos;    // center of line, scaled by screensize
noperspective out float offset; // stipple offset of individual fragment

void main() {
    float circumference = TAU * radius;
    float ang = TAU * pos.x;
    float r = radius + (pos.y - 0.5) * (width + 2.0);
    vec2 v = vec2(cos(ang), sin(ang));
    vec2 p = center + vec2(0.5,0.5) + r * v;
    vec2 cp = center + vec2(0.5,0.5) + radius * v;
    vec4 pcp = MVPMatrix * vec4(cp, 0.0, 1.0);
    gl_Position = MVPMatrix * vec4(p, 0.0, 1.0);
    offset = circumference * pos.x + stippleOffset;
    vpos = vec2(gl_Position.x * screensize.x, gl_Position.y * screensize.y);
    cpos = vec2(pcp.x * screensize.x, pcp.y * screensize.y);
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

noperspective in vec2 vpos;
noperspective in vec2 cpos;
noperspective in float offset;

out vec4 outColor;

void main() {
    // stipple
    if(stipple.y <= 0) {        // stipple disabled
        outColor = color0;
    } else {
        float t = stipple.x + stipple.y;
        float s = mod(offset, t);
        float sd = s - stipple.x;
        if(s <= 0.5 || s >= t - 0.5) {
            outColor = mix(color1, color0, mod(s + 0.5, t));
        } else if(s >= stipple.x - 0.5 && s <= stipple.x + 0.5) {
            outColor = mix(color0, color1, s - (stipple.x - 0.5));
        } else if(s < stipple.x) {
            outColor = color0;
        } else {
            outColor = color1;
        }
    }
    // antialias along edge of line
    float cdist = length(cpos - vpos);
    if(cdist > width) {
        outColor.a *= clamp(1.0 - (cdist - width), 0.0, 1.0);
    }
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}

