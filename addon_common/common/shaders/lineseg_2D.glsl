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
draws an antialiased, stippled line
ex: stipple [3,2]  color0 '='  color1 '-'
    produces  '===--===--===--===-'
               |                 |
               \_pos0       pos1_/
*/

struct Options {
    mat4 MVPMatrix;     // pixel matrix
    vec4 screensize;    // width,height of screen (for antialiasing)
    vec4 pos0;          // front end of line
    vec4 pos1;          // back end of line
    vec4 color0;        // color of on stipple
    vec4 color1;        // color of off stipple
    vec4 stipple_width; // lengths for stipple (x: color0, y: color1, z: initial shift) and line width (perp to line)
};
uniform Options options;

const bool srgbTarget = true;

/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // which corner of line ([0,0], [0,1], [1,1], [1,0])

noperspective out vec2  vpos;   // position scaled by screensize
noperspective out vec2  cpos;   // center of line, scaled by screensize
noperspective out float offset; // stipple offset of individual fragment

void main() {
    vec2 v01 = options.pos1.xy - options.pos0.xy;
    vec2 d01 = normalize(v01);
    vec2 perp = vec2(-d01.y, d01.x);
    vec2 cp = options.pos0.xy + vec2(0.5,0.5) + (pos.x * v01);
    vec2 p = cp + ((options.stipple_width.w + 2.0) * (pos.y - 0.5) * perp);
    vec4 pcp = options.MVPMatrix * vec4(cp, 0.0, 1.0);
    gl_Position = options.MVPMatrix * vec4(p, 0.0, 1.0);
    offset = length(v01) * pos.x + options.stipple_width.z;
    vpos = vec2(gl_Position.x * options.screensize.x, gl_Position.y * options.screensize.y);
    cpos = vec2(pcp.x * options.screensize.x, pcp.y * options.screensize.y);
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
    if(options.stipple_width.y <= 0) {        // stipple disabled
        outColor = options.color0;
    } else {
        float t = options.stipple_width.x + options.stipple_width.y;
        float s = mod(offset, t);
        float sd = s - options.stipple_width.x;
        vec4 colors = options.color1;
        if(colors.a < (1.0/255.0)) colors.rgb = options.color0.rgb;
        if(s <= 0.5 || s >= t - 0.5) {
            outColor = mix(colors, options.color0, mod(s + 0.5, t));
        } else if(s >= options.stipple_width.x - 0.5 && s <= options.stipple_width.x + 0.5) {
            outColor = mix(options.color0, colors, s - (options.stipple_width.x - 0.5));
        } else if(s < options.stipple_width.x) {
            outColor = options.color0;
        } else {
            outColor = colors;
        }
    }
    // antialias along edge of line
    float cdist = length(cpos - vpos);
    if(cdist > options.stipple_width.w) {
        outColor.a *= clamp(1.0 - (cdist - options.stipple_width.w), 0.0, 1.0);
    }
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
