uniform vec4  color;            // color of geometry if not selected
uniform vec4  color_selected;   // color of geometry if selected

uniform bool  use_selection;    // false: ignore selected, true: consider selected
uniform bool  use_rounding;

uniform mat4  matrix_m;         // model xform matrix
uniform mat3  matrix_mn;        // model xform matrix for normal (inv transpose of matrix_m)
uniform mat4  matrix_t;         // target xform matrix
uniform mat4  matrix_ti;        // target xform matrix inverse
uniform mat4  matrix_v;         // view xform matrix
uniform mat3  matrix_vn;        // view xform matrix for normal
uniform mat4  matrix_p;         // projection matrix

uniform int   mirror_view;      // 0=none; 1=draw edge at plane; 2=color faces on far side of plane
uniform float mirror_effect;    // strength of effect: 0=none, 1=full
uniform bvec3 mirroring;        // mirror along axis: 0=false, 1=true
uniform vec3  mirror_o;         // mirroring origin wrt world
uniform vec3  mirror_x;         // mirroring x-axis wrt world
uniform vec3  mirror_y;         // mirroring y-axis wrt world
uniform vec3  mirror_z;         // mirroring z-axis wrt world

uniform float hidden;           // affects alpha for geometry below surface. 0=opaque, 1=transparent
uniform vec3  vert_scale;       // used for mirroring
uniform float normal_offset;    // how far to push geometry along normal
uniform bool  constrain_offset; // should constrain offset by focus

uniform vec3  dir_forward;      // forward direction
uniform float unit_scaling_factor;

uniform bool  perspective;
uniform float clip_start;
uniform float clip_end;
uniform float view_distance;
uniform vec2  screen_size;

uniform float focus_mult;
uniform float offset;
uniform float dotoffset;

uniform bool  cull_backfaces;
uniform float alpha_backface;

uniform float radius;


attribute vec3  vert_pos0;      // position wrt model
attribute vec3  vert_pos1;      // position wrt model
attribute vec2  vert_offset;
attribute vec3  vert_norm;      // normal wrt model
attribute float selected;       // is vertex selected?  0=no; 1=yes


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
varying vec2 vPCPosition;


/////////////////////////////////////////////////////////////////////////
// vertex shader

vec4 get_pos(vec3 p) {
    float mult = 1.0;
    if(constrain_offset) {
        mult = 1.0;
    } else {
        float clip_dist  = clip_end - clip_start;
        float focus = (view_distance - clip_start) / clip_dist + 0.04;
        mult = focus;
    }
    return vec4((p + vert_norm * normal_offset * mult * unit_scaling_factor) * vert_scale, 1.0);
}

vec4 xyz(vec4 v) {
    return vec4(v.xyz / abs(v.w), sign(v.w));
}

void main() {
    vec4 pos0 = get_pos(vert_pos0);
    vec4 pos1 = get_pos(vert_pos1);
    vec2 ppos0 = xyz(matrix_p * matrix_v * matrix_m * pos0).xy;
    vec2 ppos1 = xyz(matrix_p * matrix_v * matrix_m * pos1).xy;
    vec2 pdir0 = normalize(ppos1 - ppos0);
    vec2 pdir1 = vec2(-pdir0.y, pdir0.x);
    vec4 off = vec4((radius + 2.0) * pdir1 * 2.0 * (vert_offset.y-0.5) / screen_size, 0, 0);

    vec4 pos = pos0 + vert_offset.x * (pos1 - pos0);
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
    vPPosition  = off + xyz(matrix_p * matrix_v * wpos);
    vPCPosition = xyz(matrix_p * matrix_v * wpos).xy;

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

    vColor = (!use_selection || selected < 0.5) ? color : color_selected;
    vColor.a *= (selected > 0.5) ? 1.0 : 1.0 - hidden;
    //vColor.a *= 1.0 - hidden;
}



/////////////////////////////////////////////////////////////////////////
// fragment shader

layout(location = 0) out vec4 outColor;

vec3 xyz(vec4 v) { return v.xyz / v.w; }

// adjusts color based on mirroring settings and fragment position
vec4 coloring(vec4 orig) {
    vec4 mixer = vec4(0.6, 0.6, 0.6, 0.0);
    if(mirror_view == 0) {
        // NO SYMMETRY VIEW
    } else if(mirror_view == 1) {
        // EDGE VIEW
        float edge_width = 5.0 / screen_size.y;
        vec3 viewdir;
        if(perspective) {
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

        if(mirroring.x && length(diffp_x * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_x)), 10.0))) {
            float s = (vTPosition.x < 0.0) ? 1.0 : 0.1;
            mixer.r = 1.0;
            mixer.a = mirror_effect * s + mixer.a * (1.0 - s);
        }
        if(mirroring.y && length(diffp_y * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_y)), 10.0))) {
            float s = (vTPosition.y > 0.0) ? 1.0 : 0.1;
            mixer.g = 1.0;
            mixer.a = mirror_effect * s + mixer.a * (1.0 - s);
        }
        if(mirroring.z && length(diffp_z * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_z)), 10.0))) {
            float s = (vTPosition.z < 0.0) ? 1.0 : 0.1;
            mixer.b = 1.0;
            mixer.a = mirror_effect * s + mixer.a * (1.0 - s);
        }
    } else if(mirror_view == 2) {
        // FACE VIEW
        if(mirroring.x && vTPosition.x < 0.0) {
            mixer.r = 1.0;
            mixer.a = mirror_effect;
        }
        if(mirroring.y && vTPosition.y > 0.0) {
            mixer.g = 1.0;
            mixer.a = mirror_effect;
        }
        if(mirroring.z && vTPosition.z < 0.0) {
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

    float dist_from_center = length(screen_size * (vPCPosition - vPPosition.xy));
    float alpha_mult = 1.0 - (dist_from_center - radius);
    if(alpha_mult <= 0) {
        discard;
        return;
    }
    alpha *= alpha_mult;

    if(perspective) {
        // perspective projection
        vec3 v = xyz(vCPosition);
        float l = length(v);
        float l_clip = (l - clip_start) / clip;
        float d = -dot(vCNormal, v) / l;
        if(d <= 0.0) {
            if(cull_backfaces) {
                alpha = 0.0;
                discard;
                return;
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
            if(cull_backfaces) {
                alpha = 0.0;
                discard;
                return;
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
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
