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
Batched variant of point_2D.glsl: the point center is a per-vertex attribute
(vert_center) instead of a UBO field, so many points can be drawn in a single
batch_for_shader() call rather than one draw call per point.  Each point
contributes 6 vertices (two triangles); vert_center is repeated across all 6
and vert_offset selects the quad corner.  The rendered result is identical to
point_2D.glsl.
*/

struct Options {
    mat4 MVPMatrix;        // pixel matrix
    vec4 screensize;       // width,height of screen (for antialiasing)
    vec4 radius_border;
    vec4 color;            // color point
    vec4 colorBorder;      // color of border
};

uniform Options options;

const bool srgbTarget = true;

/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec4 vert_center;            // center of point (repeated across the 6 quad verts)
in vec2 vert_offset;            // quad corner ([0,0], [1,0], [1,1], [0,1])

noperspective out vec2 vpos;    // position scaled by screensize
flat          out vec2 vcenter; // projected center scaled by screensize

void main() {
    float radius_border = options.radius_border.x + options.radius_border.y;
    vec2 p = vert_center.xy + (vert_offset - vec2(0.5, 0.5)) * radius_border;
    gl_Position = options.MVPMatrix * vec4(p, 0.0, 1.0);
    vpos = gl_Position.xy * options.screensize.xy;
    vcenter = (options.MVPMatrix * vec4(vert_center.xy, 0.0, 1.0)).xy * options.screensize.xy;
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

noperspective in vec2 vpos;
flat          in vec2 vcenter;

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
    float radius_border = options.radius_border.x + options.radius_border.y;
    vec4 colorb = options.colorBorder;
    if(colorb.a < (1.0/255.0)) colorb.rgb = options.color.rgb;
    float d = distance(vpos, vcenter);
    if(d > radius_border) { discard; return; }
    if(d <= options.radius_border.x) {
        float d2 = options.radius_border.x - d;
        float mix_val = clamp(d2 - options.radius_border.y/2.0, 0.0, 1.0);
        outColor = mix(colorb, options.color, vec4(mix_val));
    } else {
        float d2 = d - options.radius_border.x;
        float mix_val = clamp(d2 - options.radius_border.y/2.0, 0.0, 1.0);
        outColor = mix(colorb, vec4(colorb.rgb,0), vec4(mix_val));
    }
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
