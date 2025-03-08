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
    mat4 MVPMatrix;     // pixel matrix
    vec4 screensize;    // [ width, height, _, _ ] of screen (for antialiasing)
    vec4 center;        // center of circle
    vec4 color;         // color of circle
    vec4 plane_x;       // x direction in plane the circle lies in
    vec4 plane_y;       // y direction in plane the circle lies in
    vec4 settings;      // [ radius, line width (perp to line in plane), depth range near for drawover, depth range far ]
};

uniform Options options;

const float TAU = 6.28318530718;
const bool srgbTarget = true;

float radius()      { return options.settings[0]; }
float width()       { return options.settings[1]; }
float depth_near()  { return options.settings[2]; }
float depth_far()   { return options.settings[3]; }


/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // x: [0,1], ratio of circumference.  y: [0,1], inner/outer radius (width)

noperspective out vec2 vpos;    // position scaled by screensize
noperspective out vec2 cpos;    // center of line, scaled by screensize

void main() {
    float ang = TAU * pos.x;
    float r   = radius();
    float rio = r + (pos.y - 0.5) * (width() + 0.000001);
    vec3  c   = options.center.xyz;
    vec3  v   = options.plane_x.xyz * cos(ang) + options.plane_y.xyz * sin(ang);
    vec4  pp  = options.MVPMatrix * vec4(c + v * rio,  1.0);
    vec4  pcp = options.MVPMatrix * vec4(c + v * r,    1.0);

    gl_Position = pp;
    vpos = pp.xy  * options.screensize.xy;
    cpos = pcp.xy * options.screensize.xy;
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

noperspective in vec2 vpos;
noperspective in vec2 cpos;

out vec4  outColor;

// see comment note below before gl_FragDepth line
layout (depth_any) out float gl_FragDepth;

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
    // // antialias along edge of line.... NOT WORKING!
    float alpha = 1.0;
    // float cdist = length(cpos - vpos);
    // if(cdist < width()) {
    //     alpha = clamp(1.0 - (width() - cdist), 0.0, 1.0);
    // }

    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(options.color * vec4(1.0,1.0,1.0,alpha));

    // UNFORTUNATELY, as of 2025.03.08, there appears to be no way to assign to gl_FragDepth!
    // https://developer.blender.org/docs/handbook/guidelines/glsl/#driver-differences
    // implies that there is a way, but this is in Blender source, and this doesn't seem to be
    // exposed to bpy :(
    gl_FragDepth = mix(depth_far(), depth_near(), gl_FragCoord.z);
}

