uniform vec4  color;            // color of geometry if not selected
uniform vec4  color_selected;   // color of geometry if selected
uniform float use_selection;    // 0.0: ignore selected, 1.0: consider selected

uniform float use_rounding;     // 0.0: draw normally; 1.0: rounding (for points)

uniform mat4  matrix_m;         // model xform matrix
uniform mat3  matrix_mn;        // model xform matrix for normal (inv transpose of matrix_m)
uniform mat4  matrix_t;         // target xform matrix
uniform mat4  matrix_ti;        // target xform matrix inverse
uniform mat4  matrix_v;         // view xform matrix
uniform mat3  matrix_vn;        // view xform matrix for normal
uniform mat4  matrix_p;         // projection matrix

uniform float mirror_view;      // 0=none; 1=draw edge at plane; 2=color faces on far side of plane
uniform float mirror_effect;    // strength of effect: 0=none, 1=full
uniform vec3  mirroring;        // mirror along axis: 0=false, 1=true
uniform vec3  mirror_o;         // mirroring origin wrt world
uniform vec3  mirror_x;         // mirroring x-axis wrt world
uniform vec3  mirror_y;         // mirroring y-axis wrt world
uniform vec3  mirror_z;         // mirroring z-axis wrt world

uniform float hidden;           // affects alpha for geometry below surface. 0=opaque, 1=transparent
uniform vec3  vert_scale;       // used for mirroring
uniform float normal_offset;    // how far to push geometry along normal
uniform float constrain_offset; // should constrain offset by focus

uniform vec3  dir_forward;      // forward direction

uniform float perspective;
uniform float clip_start;
uniform float clip_end;
uniform float view_distance;
uniform vec2  screen_size;

uniform float focus_mult;
uniform float offset;
uniform float dotoffset;

uniform float cull_backfaces;   // 0=no, 1=yes
uniform float alpha_backface;


attribute vec3  vert_pos;       // position wrt model
attribute vec3  vert_norm;      // normal wrt model
attribute float selected;       // is vertex selected?


varying vec4 vPPosition;        // final position (projected)
varying vec4 vCPosition;        // position wrt camera
varying vec4 vWPosition;        // position wrt world
varying vec4 vMPosition;        // position wrt model
varying vec4 vTPosition;        // position wrt target
varying vec4 vWTPosition_x;     // position wrt target world
varying vec4 vWTPosition_y;     // position wrt target world
varying vec4 vWTPosition_z;     // position wrt target world
varying vec4 vCTPosition_x;     // position wrt target camera
varying vec4 vCTPosition_y;     // position wrt target camera
varying vec4 vCTPosition_z;     // position wrt target camera
varying vec4 vPTPosition_x;     // position wrt target projected
varying vec4 vPTPosition_y;     // position wrt target projected
varying vec4 vPTPosition_z;     // position wrt target projected
varying vec3 vCNormal;          // normal wrt camera
varying vec3 vWNormal;          // normal wrt world
varying vec3 vMNormal;          // normal wrt model
varying vec3 vTNormal;          // normal wrt target
varying vec4 vColor;            // color of geometry (considers selection)



/////////////////////////////////////////////////////////////////////////
// vertex shader

#version 330

bool floatnear(float v, float n) { return abs(v-n) < 0.5; }

vec4 get_pos(void) {
    float mult = 1.0;
    if(floatnear(constrain_offset, 0.0)) {
        mult = 1.0;
    } else {
        float clip_dist  = clip_end - clip_start;
        float focus = (view_distance - clip_start) / clip_dist + 0.04;
        mult = focus;
    }
    return vec4((vert_pos + vert_norm * normal_offset * mult) * vert_scale, 1.0);
}

void main() {
    vec4 pos  = get_pos();
    vec3 norm = normalize(vert_norm * vert_scale);

    vec4 wpos = matrix_m * pos;
    vec3 wnorm = normalize(matrix_mn * norm);

    vec4 tpos = matrix_ti * wpos;
    vec3 tnorm = vec3(
        dot(wnorm, mirror_x),
        dot(wnorm, mirror_y),
        dot(wnorm, mirror_z));

    vMPosition  = pos;
    vWPosition  = wpos;
    vCPosition  = matrix_v * wpos;
    vPPosition  = matrix_p * matrix_v * wpos;

    vMNormal    = norm;
    vWNormal    = wnorm;
    vCNormal    = normalize(matrix_vn * wnorm);

    vTPosition    = tpos;
    vWTPosition_x = matrix_t * vec4(0.0, tpos.y, tpos.z, 1.0);
    vWTPosition_y = matrix_t * vec4(tpos.x, 0.0, tpos.z, 1.0);
    vWTPosition_z = matrix_t * vec4(tpos.x, tpos.y, 0.0, 1.0);
    vCTPosition_x = matrix_v * vWTPosition_x;
    vCTPosition_y = matrix_v * vWTPosition_y;
    vCTPosition_z = matrix_v * vWTPosition_z;
    vPTPosition_x = matrix_p * vCTPosition_x;
    vPTPosition_y = matrix_p * vCTPosition_y;
    vPTPosition_z = matrix_p * vCTPosition_z;
    vTNormal      = tnorm;

    gl_Position = vPPosition;

    vColor = (use_selection < 0.5 || selected < 0.5) ? color : color_selected;
    vColor.a *= 1.0 - hidden;
}



/////////////////////////////////////////////////////////////////////////
// fragment shader

#version 330

out vec4 outColor;

vec3 xyz(vec4 v) { return v.xyz / v.w; }

bool floatnear(float v, float n) { return abs(v-n) < 0.5; }

// adjusts color based on mirroring settings and fragment position
vec4 coloring(vec4 orig) {
    vec4 mixer = vec4(0.6, 0.6, 0.6, 0.0);
    if(floatnear(mirror_view, 0.0)) {
        // NO SYMMETRY VIEW
    } else if(floatnear(mirror_view, 1.0)) {
        // EDGE VIEW
        float edge_width = 5.0 / screen_size.y;
        vec3 viewdir;
        if(floatnear(perspective, 1.0)) {
            viewdir = normalize(xyz(vCPosition));
        } else {
            viewdir = vec3(0,0,1);
        }
        vec3 diffc_x = xyz(vCTPosition_x) - xyz(vCPosition);
        vec3 diffc_y = xyz(vCTPosition_y) - xyz(vCPosition);
        vec3 diffc_z = xyz(vCTPosition_z) - xyz(vCPosition);
        vec3 dirc_x = normalize(diffc_x);
        vec3 dirc_y = normalize(diffc_y);
        vec3 dirc_z = normalize(diffc_z);
        vec3 diffp_x = xyz(vPTPosition_x) - xyz(vPPosition);
        vec3 diffp_y = xyz(vPTPosition_y) - xyz(vPPosition);
        vec3 diffp_z = xyz(vPTPosition_z) - xyz(vPPosition);
        vec3 aspect = vec3(1.0, screen_size.y / screen_size.x, 0.0);

        if(floatnear(mirroring.x, 1.0) && length(diffp_x * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_x)), 10.0))) {
            float s = (vTPosition.x < 0.0) ? 1.0 : 0.1;
            mixer.r = 1.0;
            mixer.a = mirror_effect * s + mixer.a * (1.0 - s);
        }
        if(floatnear(mirroring.y, 1.0) && length(diffp_y * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_y)), 10.0))) {
            float s = (vTPosition.y > 0.0) ? 1.0 : 0.1;
            mixer.g = 1.0;
            mixer.a = mirror_effect * s + mixer.a * (1.0 - s);
        }
        if(floatnear(mirroring.z, 1.0) && length(diffp_z * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_z)), 10.0))) {
            float s = (vTPosition.z < 0.0) ? 1.0 : 0.1;
            mixer.b = 1.0;
            mixer.a = mirror_effect * s + mixer.a * (1.0 - s);
        }
    } else if(floatnear(mirror_view, 2.0)) {
        // FACE VIEW
        if(floatnear(mirroring.x, 1.0) && vTPosition.x < 0.0) {
            mixer.r = 1.0;
            mixer.a = mirror_effect;
        }
        if(floatnear(mirroring.y, 1.0) && vTPosition.y > 0.0) {
            mixer.g = 1.0;
            mixer.a = mirror_effect;
        }
        if(floatnear(mirroring.z, 1.0) && vTPosition.z < 0.0) {
            mixer.b = 1.0;
            mixer.a = mirror_effect;
        }
    }
    float m0 = mixer.a, m1 = 1.0 - mixer.a;
    return vec4(mixer.rgb * m0 + orig.rgb * m1, m0 + orig.a * m1);
}

void main() {
    float clip  = clip_end - clip_start;
    float focus = (view_distance - clip_start) / clip + 0.04;
    vec3  rgb   = vColor.rgb;
    float alpha = vColor.a;

    //gl_FragColor = coloring(vColor);
    //gl_FragDepth = gl_FragCoord.z * 0.9999;
    //return;

    if(use_rounding > 0.5 && length(gl_PointCoord - vec2(0.5,0.5)) > 0.5) discard;

    if(floatnear(perspective, 1.0)) {
        // perspective projection
        vec3 v = vCPosition.xyz / vCPosition.w;
        float l = length(v);
        float l_clip = (l - clip_start) / clip;
        float d = -dot(vCNormal, v) / l;
        if(d <= 0.0) {
            if(cull_backfaces > 0.5) {
                alpha = 0.0;
                discard;
            } else {
                alpha *= alpha_backface;
            }
        }

        float focus_push = focus_mult * sign(focus - l_clip) * pow(abs(focus - l_clip), 4.0) * 400.0;
        float dist_push = pow(view_distance, 3.0) * 0.000001;

        // MAGIC!
        gl_FragDepth =
            gl_FragCoord.z
            - offset    * l_clip * 200.0
            - dotoffset * l_clip * 0.0001 * (1.0 - d)
            - focus_push
            ;
    } else {
        // orthographic projection
        vec3 v = vec3(0, 0, clip * 0.5); // + vCPosition.xyz / vCPosition.w;
        float l = length(v);
        float l_clip = (l - clip_start) / clip;
        float d = dot(vCNormal, v) / l;
        if(d <= 0.0) {
            if(cull_backfaces > 0.5) {
                alpha = 0.0;
                discard;
            } else {
                alpha *= alpha_backface;
            }
        }

        // MAGIC!
        gl_FragDepth =
            gl_FragCoord.z
            - offset    * l_clip * 1.0
            + dotoffset * l_clip * 0.000001 * (1.0 - d)
            ;
    }

    alpha *= pow(max(vCNormal.z, 0.01), 0.25);

    outColor = coloring(vec4(rgb, alpha));
}