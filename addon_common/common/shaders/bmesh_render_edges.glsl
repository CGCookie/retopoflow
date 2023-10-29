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

#include "bmesh_render_prefix.glsl"


/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec4  vert_pos0;      // position wrt model
in vec4  vert_pos1;      // position wrt model
in vec2  vert_offset;
in vec4  vert_norm;      // normal wrt model
in float selected;       // is edge selected?  0=no; 1=yes
in float warning;        // is edge warning?  0=no; 1=yes
in float pinned;         // is edge pinned?  0=no; 1=yes
in float seam;           // is edge on seam?  0=no; 1=yes

out vec4 vPPosition;        // final position (projected)
out vec4 vCPosition;        // position wrt camera
out vec4 vWPosition;        // position wrt world
out vec4 vMPosition;        // position wrt model
out vec4 vTPosition;        // position wrt target
out vec4 vWTPosition_x;     // position wrt target world
out vec4 vWTPosition_y;     // position wrt target world
out vec4 vWTPosition_z;     // position wrt target world
out vec4 vCTPosition_x;     // position wrt target camera
out vec4 vCTPosition_y;     // position wrt target camera
out vec4 vCTPosition_z;     // position wrt target camera
out vec4 vPTPosition_x;     // position wrt target projected
out vec4 vPTPosition_y;     // position wrt target projected
out vec4 vPTPosition_z;     // position wrt target projected
out vec3 vCNormal;          // normal wrt camera
out vec3 vWNormal;          // normal wrt world
out vec3 vMNormal;          // normal wrt model
out vec3 vTNormal;          // normal wrt target
out vec4 vColorIn;          // color of geometry inside
out vec4 vColorOut;         // color of geometry outside (considers selection)
out vec2 vPCPosition;

bool is_warning()   { return use_warning()   && warning  > 0.5; }
bool is_pinned()    { return use_pinned()    && pinned   > 0.5; }
bool is_seam()      { return use_seam()      && seam     > 0.5; }
bool is_selection() { return use_selection() && selected > 0.5; }

void main() {
    vec4 pos0 = get_pos(vec3(vert_pos0));
    vec4 pos1 = get_pos(vec3(vert_pos1));
    vec2 ppos0 = xyz4(options.matrix_p * options.matrix_v * options.matrix_m * pos0).xy;
    vec2 ppos1 = xyz4(options.matrix_p * options.matrix_v * options.matrix_m * pos1).xy;
    vec2 pdir0 = normalize(ppos1 - ppos0);
    vec2 pdir1 = vec2(-pdir0.y, pdir0.x);
    vec4 off = vec4((options.radius.x + options.radius.y + 2.0) * pdir1 * 2.0 * (vert_offset.y-0.5) / options.screen_size.xy, 0, 0);

    vec4 pos = pos0 + vert_offset.x * (pos1 - pos0);
    vec3 norm = normalize(vec3(vert_norm) * vec3(options.vert_scale));

    vec4 wpos = push_pos(options.matrix_m * pos);
    vec3 wnorm = normalize(mat3(options.matrix_mn) * norm);

    vec4 tpos = options.matrix_ti * wpos;
    vec3 tnorm = vec3(
        dot(wnorm, vec3(options.mirror_x)),
        dot(wnorm, vec3(options.mirror_y)),
        dot(wnorm, vec3(options.mirror_z)));

    vMPosition  = pos;
    vWPosition  = wpos;
    vCPosition  = options.matrix_v * wpos;
    vPPosition  = off + xyz4(options.matrix_p * options.matrix_v * wpos);
    vPCPosition = xyz4(options.matrix_p * options.matrix_v * wpos).xy;

    vMNormal    = norm;
    vWNormal    = wnorm;
    vCNormal    = normalize(mat3(options.matrix_vn) * wnorm);

    vTPosition    = tpos;
    vWTPosition_x = options.matrix_t * vec4(0.0, tpos.y, tpos.z, 1.0);
    vWTPosition_y = options.matrix_t * vec4(tpos.x, 0.0, tpos.z, 1.0);
    vWTPosition_z = options.matrix_t * vec4(tpos.x, tpos.y, 0.0, 1.0);
    vCTPosition_x = options.matrix_v * vWTPosition_x;
    vCTPosition_y = options.matrix_v * vWTPosition_y;
    vCTPosition_z = options.matrix_v * vWTPosition_z;
    vPTPosition_x = options.matrix_p * vCTPosition_x;
    vPTPosition_y = options.matrix_p * vCTPosition_y;
    vPTPosition_z = options.matrix_p * vCTPosition_z;
    vTNormal      = tnorm;

    gl_Position = vPPosition;

    vColorIn  = options.color_normal;
    vColorOut = vec4(options.color_normal.rgb, 0.0);

    if(is_selection()) {
        vColorIn  = color_over(options.color_selected, vColorIn);
        vColorOut = vec4(options.color_selected.rgb, 0.0);
    }
    if(is_warning())   vColorOut = color_over(options.color_warning,  vColorOut);
    if(is_pinned())    vColorOut = color_over(options.color_pinned,   vColorOut);
    if(is_seam())      vColorOut = color_over(options.color_seam,     vColorOut);

    vColorIn.a  *= 1.0 - options.hidden.x;
    vColorOut.a *= 1.0 - options.hidden.x;

    if(debug_invert_backfacing && vCNormal.z < 0.0) {
        vColorIn  = vec4(vec3(1,1,1) - vColorIn.rgb,  vColorIn.a);
        vColorOut = vec4(vec3(1,1,1) - vColorOut.rgb, vColorOut.a);
    }
}



/////////////////////////////////////////////////////////////////////////
// fragment shader

in vec4 vPPosition;        // final position (projected)
in vec4 vCPosition;        // position wrt camera
in vec4 vWPosition;        // position wrt world
in vec4 vMPosition;        // position wrt model
in vec4 vTPosition;        // position wrt target
in vec4 vWTPosition_x;     // position wrt target world
in vec4 vWTPosition_y;     // position wrt target world
in vec4 vWTPosition_z;     // position wrt target world
in vec4 vCTPosition_x;     // position wrt target camera
in vec4 vCTPosition_y;     // position wrt target camera
in vec4 vCTPosition_z;     // position wrt target camera
in vec4 vPTPosition_x;     // position wrt target projected
in vec4 vPTPosition_y;     // position wrt target projected
in vec4 vPTPosition_z;     // position wrt target projected
in vec3 vCNormal;          // normal wrt camera
in vec3 vWNormal;          // normal wrt world
in vec3 vMNormal;          // normal wrt model
in vec3 vTNormal;          // normal wrt target
in vec4 vColorIn;          // color of geometry inside (considers selection)
in vec4 vColorOut;         // color of geometry outside
in vec2 vPCPosition;

out vec4 outColor;
out float gl_FragDepth;

void main() {
    float clip  = options.clip[1] - options.clip[0];
    float focus = (view_distance() - options.clip[0]) / clip + 0.04;

    float dist_from_center = length(options.screen_size.xy * (vPCPosition - vPPosition.xy));
    float alpha_mult = 1.0 - (dist_from_center - (options.radius.x + options.radius.y));
    if(alpha_mult <= 0) {
        discard;
        return;
    }

    float mix_in_out = clamp(dist_from_center - options.radius.x, 0.0, 1.0);
    vec4  vColor = mix(vColorIn, vColorOut, mix_in_out);
    vec3  rgb    = vColor.rgb;
    float alpha  = vColor.a * min(1.0, alpha_mult);

    if(is_view_perspective()) {
        // perspective projection
        vec3 v = xyz3(vCPosition);
        float l = length(v);
        float l_clip = (l - options.clip[0]) / clip;
        float d = -dot(vCNormal, v) / l;
        if(d <= 0.0) {
            if(cull_backfaces()) {
                alpha = 0.0;
                discard;
                return;
            } else {
                alpha *= min(1.0, alpha_backface());
            }
        }
    } else {
        // orthographic projection
        vec3 v = vec3(0, 0, clip * 0.5); // + vCPosition.xyz / vCPosition.w;
        float l = length(v);
        float l_clip = (l - options.clip[0]) / clip;
        float d = dot(vCNormal, v) / l;
        if(d <= 0.0) {
            if(cull_backfaces()) {
                alpha = 0.0;
                discard;
                return;
            } else {
                alpha *= min(1.0, alpha_backface());
            }
        }
    }

    alpha *= min(1.0, pow(max(vCNormal.z, 0.01), 0.25));
    outColor = coloring(vec4(rgb, alpha));
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
