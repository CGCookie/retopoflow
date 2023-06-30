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
    mat4 uMVPMatrix;
    float uInOut;
}

uniform Options options;

in vec4 vPos;
in vec4 vFrom;
in vec4 vInColor;
in vec4 vOutColor;

/////////////////////////////////////////////////////////////////////////
// vertex shader

#version 330

out float aRot;
out vec4 aInColor;
out vec4 aOutColor;

float angle(vec2 d) { return atan(d.y, d.x); }

void main() {
    vec4 p0 = options.uMVPMatrix * vFrom;
    vec4 p1 = options.uMVPMatrix * vPos;
    gl_Position = p1;
    aRot = angle((p1.xy / p1.w) - (p0.xy / p0.w));
    aInColor = vInColor;
    aOutColor = vOutColor;
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

#version 330

in float aRot;
in vec4 aInColor;
in vec4 aOutColor;

out vec4 outColor;

float alpha(vec2 dir) {
    vec2 d0 = dir - vec2(1,1);
    vec2 d1 = dir - vec2(1,-1);

    float d0v = -d0.x/2.0 - d0.y;
    float d1v = -d1.x/2.0 + d1.y;
    float dv0 = length(dir);
    float dv1 = distance(dir, vec2(-2,0));

    if(d0v < 1.0 || d1v < 1.0) return -1.0;
    // if(dv0 > 1.0) return -1.0;
    if(dv1 < 1.3) return -1.0;

    if(d0v - 1.0 < (1.0 - options.uInOut) || d1v - 1.0 < (1.0 - options.uInOut)) return 0.0;
    //if(dv0 > options.uInOut) return 0.0;
    if(dv1 - 1.3 < (1.0 - options.uInOut)) return 0.0;
    return 1.0;
}

void main() {
    vec2 d = 2.0 * (gl_PointCoord - vec2(0.5, 0.5));
    vec2 dr = vec2(cos(aRot)*d.x - sin(aRot)*d.y, sin(aRot)*d.x + cos(aRot)*d.y);
    float a = alpha(dr);
    if(a < 0.0) { discard; return; }
    outColor = mix(aOutColor, aInColor, a);
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
