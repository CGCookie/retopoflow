/*
draws an antialiased, stippled line
ex: stipple [3,2]  color0 '='  color1 '-'
    produces  '===--===--===--===-'
               |                 |
               \_pos0       pos1_/
*/

uniform vec2  screensize;       // width,height of screen (for antialiasing)
uniform mat4  MVPMatrix;        // pixel matrix
uniform vec2  pos0;             // front end of line
uniform vec2  pos1;             // back end of line
uniform vec2  stipple;          // lengths of on/off stipple
uniform float stippleOffset;    // length to shift initial stipple of front
uniform vec4  color0;           // color of on stipple
uniform vec4  color1;           // color of off stipple
uniform float width;            // line width, perpendicular to line

/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // which corner of line ([0,0], [0,1], [1,1], [1,0])

noperspective out vec2  vpos;   // position scaled by screensize
noperspective out vec2  cpos;   // center of line, scaled by screensize
noperspective out float offset; // stipple offset of individual fragment

void main() {
    vec2 v01 = pos1 - pos0;
    vec2 d01 = normalize(v01);
    vec2 perp = vec2(-d01.y, d01.x);
    vec2 cp = pos0 + vec2(0.5,0.5) + (pos.x * v01);
    vec2 p = cp + ((width+2.0) * (pos.y - 0.5) * perp);
    vec4 pcp = MVPMatrix * vec4(cp, 0.0, 1.0);
    gl_Position = MVPMatrix * vec4(p, 0.0, 1.0);
    offset = length(v01) * pos.x + stippleOffset;
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
        vec4 colors = color1;
        if(colors.a < (1.0/255.0)) colors.rgb = color0.rgb;
        if(s <= 0.5 || s >= t - 0.5) {
            outColor = mix(colors, color0, mod(s + 0.5, t));
        } else if(s >= stipple.x - 0.5 && s <= stipple.x + 0.5) {
            outColor = mix(color0, colors, s - (stipple.x - 0.5));
        } else if(s < stipple.x) {
            outColor = color0;
        } else {
            outColor = colors;
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
