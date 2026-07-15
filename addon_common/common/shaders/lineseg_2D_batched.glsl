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
Batched variant of lineseg_2D.glsl: the line endpoints (vert_pos0, vert_pos1)
and the stipple base offset (vert_base_offset) are per-vertex attributes instead
of UBO fields, so many segments can be drawn in a single batch_for_shader() call
rather than one draw call per segment.  Each segment contributes 6 vertices (two
triangles); the endpoints and base offset are repeated across all 6 and
vert_offset selects the quad corner.  vert_base_offset replaces the old
stipple_width.z so a line strip can keep the stipple pattern continuous across
segments (each segment gets the cumulative length of the preceding segments).
The rendered result is identical to lineseg_2D.glsl.

draws an antialiased, stippled line
ex: stipple [3,2]  color0 '='  color1 '-'
    produces  '===--===--===--===-'
               |                 |
               \_pos0       pos1_/
*/

struct Options {
    mat4 MVPMatrix;     // pixel matrix
    vec4 screensize;    // width,height of screen (for antialiasing)
    vec4 color0;        // color of on stipple
    vec4 color1;        // color of off stipple
    vec4 stipple_width; // lengths for stipple (x: color0, y: color1, z: unused) and line width (w, perp to line)
};
uniform Options options;

const bool srgbTarget = true;

/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec4  vert_pos0;             // front end of line (repeated across the 6 quad verts)
in vec4  vert_pos1;             // back end of line (repeated across the 6 quad verts)
in vec2  vert_offset;           // which corner of line ([0,0], [1,0], [1,1], [0,1])
in float vert_base_offset;      // stipple offset at this segment's start (replaces old stipple_width.z)

noperspective out vec2  vpos;   // position scaled by screensize
noperspective out vec2  cpos;   // center of line, scaled by screensize
noperspective out float offset; // stipple offset of individual fragment

void main() {
    vec2 v01 = vert_pos1.xy - vert_pos0.xy;
    vec2 d01 = normalize(v01);
    vec2 perp = vec2(-d01.y, d01.x);
    vec2 cp = vert_pos0.xy + vec2(0.5,0.5) + (vert_offset.x * v01);
    vec2 p = cp + ((options.stipple_width.w + 2.0) * (vert_offset.y - 0.5) * perp);
    vec4 pcp = options.MVPMatrix * vec4(cp, 0.0, 1.0);
    gl_Position = options.MVPMatrix * vec4(p, 0.0, 1.0);
    offset = length(v01) * vert_offset.x + vert_base_offset;
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
            float mix_val = mod(s + 0.5, t);
            outColor = mix(colors, options.color0, vec4(mix_val));
        } else if(s >= options.stipple_width.x - 0.5 && s <= options.stipple_width.x + 0.5) {
            float mix_val = s - (options.stipple_width.x - 0.5);
            outColor = mix(options.color0, colors, vec4(mix_val));
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
