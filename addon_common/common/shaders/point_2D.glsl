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

struct Options {
    mat4 MVPMatrix;        // pixel matrix
    vec4 screensize;       // width,height of screen (for antialiasing)
    vec4 center;           // center of point
    vec4 radius_border;
    vec4 color;            // color point
    vec4 colorBorder;      // color of border
};

uniform Options options;

const bool srgbTarget = true;

/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // four corners of point ([0,0], [0,1], [1,1], [1,0])

noperspective out vec2 vpos;    // position scaled by screensize

void main() {
    float radius_border = options.radius_border.x + options.radius_border.y;
    vec2 p = options.center.xy + (pos - vec2(0.5, 0.5)) * radius_border;
    gl_Position = options.MVPMatrix * vec4(p, 0.0, 1.0);
    vpos = gl_Position.xy * options.screensize.xy;  // just p?
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

noperspective in vec2 vpos;

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
    vec2 ctr = (options.MVPMatrix * vec4(options.center.xy, 0.0, 1.0)).xy;
    float d = distance(vpos, ctr.xy * options.screensize.xy);
    if(d > radius_border) { discard; return; }
    if(d <= options.radius_border.x) {
        float d2 = options.radius_border.x - d;
        outColor = mix(colorb, options.color, clamp(d2 - options.radius_border.y/2.0, 0.0, 1.0));
    } else {
        float d2 = d - options.radius_border.x;
        outColor = mix(colorb, vec4(colorb.rgb,0), clamp(d2 - options.radius_border.y/2.0, 0.0, 1.0));
    }
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}

