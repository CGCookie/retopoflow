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

/////////////////////////////////////////////////////////////////////////
// common shader

struct Options {
    mat4 matrix_m;          // model xform matrix
    mat4 matrix_mn;         // model xform matrix for normal (inv transpose of matrix_m)
    mat4 matrix_t;          // target xform matrix
    mat4 matrix_ti;         // target xform matrix inverse
    mat4 matrix_v;          // view xform matrix
    mat4 matrix_vn;         // view xform matrix for normal
    mat4 matrix_p;          // projection matrix

    vec4 clip;
    vec4 screen_size;
    vec4 view_settings0;    // [ view_distance, perspective, focus_mult, alpha_backface ]
    vec4 view_settings1;    // [ cull_backfaces, unit_scaling_factor, normal_offset (how far to push geo along normal), constrain_offset (should constrain by focus) ]
    vec4 view_settings2;    // [ view push, xxx, xxx, xxx ]
    vec4 view_position;

    vec4 color_normal;      // color of geometry if not selected
    vec4 color_selected;    // color of geometry if selected
    vec4 color_warning;     // color of geometry if warning
    vec4 color_pinned;      // color of geometry if pinned
    vec4 color_seam;        // color of geometry if seam

    vec4 use_settings0;     // [ selection, warning, pinned, seam ]
    vec4 use_settings1;     // [ rounding, xxx, xxx, xxx ]

    vec4 mirror_settings;   // [ view (0=none; 1=edge at plane; 2=color faces on far side of plane), effect (0=no effect, 1=full), xxx, xxx ]
    vec4 mirroring;         // mirror along axis: 0=false, 1=true
    vec4 mirror_o;          // mirroring origin wrt world
    vec4 mirror_x;          // mirroring x-axis wrt world
    vec4 mirror_y;          // mirroring y-axis wrt world
    vec4 mirror_z;          // mirroring z-axis wrt world

    vec4 vert_scale;        // used for mirroring

    vec4 hidden;            // affects alpha for geometry below surface. 0=opaque, 1=transparent
    vec4 offset;
    vec4 dotoffset;

    vec4 radius;
};
uniform Options options;

const bool srgbTarget = true;
const bool debug_invert_backfacing = false;

int mirror_view()   {
    float v = options.mirror_settings[0];
    if(v > 1.5) return 2;
    if(v > 0.5) return 1;
    return 0;
}
float mirror_effect() { return options.mirror_settings[1]; }

float view_distance()       { return options.view_settings0[0]; }
bool  is_view_perspective() { return options.view_settings0[1] > 0.5; }
float focus_mult()          { return options.view_settings0[2]; }
float alpha_backface()      { return options.view_settings0[3]; }
bool  cull_backfaces()      { return options.view_settings1[0] > 0.5; }
float unit_scaling_factor() { return options.view_settings1[1]; }
float normal_offset()       { return options.view_settings1[2]; }
bool  constrain_offset()    { return options.view_settings1[3] > 0.5; }
float view_push()           { return options.view_settings2[0]; }
vec4  view_position()       { return options.view_position; }

float clip_near() { return options.clip[0]; }
float clip_far()  { return options.clip[1]; }

bool use_selection() { return options.use_settings0[0] > 0.5; }
bool use_warning()   { return options.use_settings0[1] > 0.5; }
bool use_pinned()    { return options.use_settings0[2] > 0.5; }
bool use_seam()      { return options.use_settings0[3] > 0.5; }
bool use_rounding()  { return options.use_settings1[0] > 0.5; }

float magic_offset()    { return options.offset.x; }
float magic_dotoffset() { return options.dotoffset.x; }

vec4 color_over(vec4 top, vec4 bottom) {
    float a = top.a + (1.0 - top.a) * bottom.a;
    vec3 c = (top.rgb * top.a + (1.0 - top.a) * bottom.a * bottom.rgb) / a;
    return vec4(c, a);
}

/////////////////////////////////////////////////////////////////////////
// vertex shader

vec4 get_pos(vec3 p) {
    float mult = 1.0;
    if(constrain_offset()) {
        mult = 1.0;
    } else {
        float clip_dist  = clip_far() - clip_near();
        float focus = (view_distance() - clip_near()) / clip_dist + 0.04;
        mult = focus;
    }
    vec3 norm_offset = vec3(vert_norm) * normal_offset() * mult;
    vec3 mirror = vec3(options.vert_scale);
    return vec4((p + norm_offset) * mirror, 1.0);
}

vec4 push_pos(vec4 p) {
    float clip_dist  = clip_far() - clip_near();
    float focus = (1.0 - clamp((view_distance() - clip_near()) / clip_dist, 0.0, 1.0)) * 0.1;
    return vec4( mix(view_position().xyz, p.xyz, view_push()), p.w);
}

vec4 xyz4(vec4 v) { return vec4(v.xyz / abs(v.w), sign(v.w)); }

/////////////////////////////////////////////////////////////////////////
// fragment shader

vec3 xyz3(vec4 v) { return v.xyz / v.w; }

// adjusts color based on mirroring settings and fragment position
vec4 coloring(vec4 orig) {
    vec4 mixer = vec4(0.6, 0.6, 0.6, 0.0);
    if(mirror_view() == 0) {
        // NO SYMMETRY VIEW
    } else if(mirror_view() == 1) {
        // EDGE VIEW
        float edge_width = 5.0 / options.screen_size.y;
        vec3 viewdir;
        if(is_view_perspective()) {
            viewdir = normalize(xyz3(vCPosition));
        } else {
            viewdir = vec3(0,0,1);
        }
        vec3 diffc_x = xyz3(vCTPosition_x) - xyz3(vCPosition);
        vec3 diffc_y = xyz3(vCTPosition_y) - xyz3(vCPosition);
        vec3 diffc_z = xyz3(vCTPosition_z) - xyz3(vCPosition);
        vec3 dirc_x = normalize(diffc_x);
        vec3 dirc_y = normalize(diffc_y);
        vec3 dirc_z = normalize(diffc_z);
        vec3 diffp_x = xyz3(vPTPosition_x) - xyz3(vPPosition);
        vec3 diffp_y = xyz3(vPTPosition_y) - xyz3(vPPosition);
        vec3 diffp_z = xyz3(vPTPosition_z) - xyz3(vPPosition);
        vec3 aspect = vec3(1.0, options.screen_size.y / options.screen_size.x, 0.0);

        float s = 0.0;
        if(options.mirroring.x > 0.5 && length(diffp_x * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_x)), 10.0))) {
            mixer.r = 1.0;
            s = max(s, (vTPosition.x < 0.0) ? 1.0 : 0.1);
        }
        if(options.mirroring.y > 0.5 && length(diffp_y * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_y)), 10.0))) {
            mixer.g = 1.0;
            s = max(s, (vTPosition.y > 0.0) ? 1.0 : 0.1);
        }
        if(options.mirroring.z > 0.5 && length(diffp_z * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_z)), 10.0))) {
            mixer.b = 1.0;
            s = max(s, (vTPosition.z < 0.0) ? 1.0 : 0.1);
        }
        mixer.a = mirror_effect() * s + mixer.a * (1.0 - s);
    } else if(mirror_view() == 2) {
        // FACE VIEW
        if(options.mirroring.x > 0.5 && vTPosition.x < 0.0) {
            mixer.r = 1.0;
            mixer.a = mirror_effect();
        }
        if(options.mirroring.y > 0.5 && vTPosition.y > 0.0) {
            mixer.g = 1.0;
            mixer.a = mirror_effect();
        }
        if(options.mirroring.z > 0.5 && vTPosition.z < 0.0) {
            mixer.b = 1.0;
            mixer.a = mirror_effect();
        }
    }

    float m0 = mixer.a, m1 = 1.0 - mixer.a;

    #ifdef BMESH_FACE
        return vec4(mixer.rgb * m0 + orig.rgb * orig.a * m1, m0 + orig.a * m1);
    #else
        return vec4(mixer.rgb * m0 + orig.rgb * m1, m0 + orig.a * m1);
    #endif
}

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
