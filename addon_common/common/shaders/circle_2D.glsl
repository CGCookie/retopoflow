/*
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
*/


/*
draws an antialiased, stippled circle
ex: stipple [3,2]  color0 '='  color1 '-'
    produces  '===--===--===--===-'  (just wrapped as a circle!)
*/

struct Options {
    mat4 MVPMatrix;     // pixel matrix
    vec4 screensize;    // width,height of screen (for antialiasing)
    vec4 center;        // center of circle
    vec4 color0;        // color of on stipple
    vec4 color1;        // color of off stipple
    vec4 radius_width;  // radius of circle, line width (perp to line)
    vec4 stipple_data;  // stipple lengths, offset
};

uniform Options options;

const bool srgbTarget = true;
const float TAU = 6.28318530718;

float radius() { return options.radius_width.x; }
float width()  { return options.radius_width.y; }
vec2  stipple_lengths() { return options.stipple_data.xy; }
float stipple_offset()  { return options.stipple_data.z; }


/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // x: [0,1], ratio of circumference.  y: [0,1], inner/outer radius (width)

noperspective out vec2 vpos;    // position scaled by screensize
noperspective out vec2 cpos;    // center of line, scaled by screensize
noperspective out float offset; // stipple offset of individual fragment


void main() {
    float circumference = TAU * radius();
    float ang = TAU * pos.x;
    float r = radius() + (pos.y - 0.5) * (width() + 2.0);
    vec2 v = vec2(cos(ang), sin(ang));
    vec2 p = options.center.xy + vec2(0.5,0.5) + r * v;
    vec2 cp = options.center.xy + vec2(0.5,0.5) + radius() * v;
    vec4 pcp = options.MVPMatrix * vec4(cp, 0.0, 1.0);
    gl_Position = options.MVPMatrix * vec4(p, 0.0, 1.0);
    vpos = vec2(gl_Position.x * options.screensize.x, gl_Position.y * options.screensize.y);
    cpos = vec2(pcp.x * options.screensize.x, pcp.y * options.screensize.y);
    offset = circumference * pos.x + stipple_offset();
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

noperspective in vec2 vpos;
noperspective in vec2 cpos;
noperspective in float offset;

out vec4 outColor;

vec4 blender_srgb_to_framebuffer_space(vec4 in_color)
{
  if (srgbTarget) {
    vec3 c = max(in_color.rgb, vec3(0.0));
    vec3 c1 = c * (1.0 / 12.92);
    vec3 c2 = pow((c + 0.055) * (1.0 / 1.055), vec3(2.4));
    in_color.rgb = mix(c1, c2, step(vec3(0.04045), c));
  }
  return in_color;
}

void main() {
    // stipple
    if(stipple_lengths().y <= 0) {        // stipple disabled
        outColor = options.color0;
    } else {
        float t = stipple_lengths().x + stipple_lengths().y;
        float s = mod(offset, t);
        float sd = s - stipple_lengths().x;
        if(s <= 0.5 || s >= t - 0.5) {
            outColor = mix(options.color1, options.color0, mod(s + 0.5, t));
        } else if(s >= stipple_lengths().x - 0.5 && s <= stipple_lengths().x + 0.5) {
            outColor = mix(options.color0, options.color1, s - (stipple_lengths().x - 0.5));
        } else if(s < stipple_lengths().x) {
            outColor = options.color0;
        } else {
            outColor = options.color1;
        }
    }
    // antialias along edge of line
    float cdist = length(cpos - vpos);
    if(cdist > width()) {
        outColor.a *= clamp(1.0 - (cdist - width()), 0.0, 1.0);
    }
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}

