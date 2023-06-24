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
    vec4 view_settings0;    // view_distance, perspective, focus_mult, alpha_backface
    vec4 view_settings1;    // cull_backfaces, unit_scaling_factor, normal_offset (how far to push geo along normal), constrain_offset (should constrain by focus)

    vec4 color_normal;      // color of geometry if not selected
    vec4 color_selected;    // color of geometry if selected
    vec4 color_warning;     // color of geometry if warning
    vec4 color_pinned;      // color of geometry if pinned
    vec4 color_seam;        // color of geometry if seam

    vec4 use_settings0;     // selection, warning, pinned, seam
    vec4 use_settings1;     // rounding, xxx, xxx, xxx

    vec4 mirror_settings;   // view (0=none; 1=edge at plane; 2=color faces on far side of plane), effect (0=no effect, 1=full), xxx, xxx
    vec4 mirroring;         // mirror along axis: 0=false, 1=true
    vec4 mirror_o;          // mirroring origin wrt world
    vec4 mirror_x;          // mirroring x-axis wrt world
    vec4 mirror_y;          // mirroring y-axis wrt world
    vec4 mirror_z;          // mirroring z-axis wrt world

    vec4 vert_scale;        // used for mirroring

    vec4 hidden;           // affects alpha for geometry below surface. 0=opaque, 1=transparent
    vec4 offset;
    vec4 dotoffset;

    vec4 radius;
};
uniform Options options;

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

float clip_near() { return options.clip[0]; }
float clip_far()  { return options.clip[1]; }

bool use_selection() { return options.use_settings0[0] > 0.5; }
bool use_warning()   { return options.use_settings0[1] > 0.5; }
bool use_pinned()    { return options.use_settings0[2] > 0.5; }
bool use_seam()      { return options.use_settings0[3] > 0.5; }
bool use_rounding()  { return options.use_settings1[0] > 0.5; }

float magic_offset()    { return options.offset.x; }
float magic_dotoffset() { return options.dotoffset.x; }


const bool srgbTarget = true;
const bool debug_invert_backfacing = false;

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
out vec4 vColor;            // color of geometry (considers selection)
out vec2 vPCPosition;

vec4 get_pos(vec3 p) {
    float mult = 1.0;
    if(constrain_offset()) {
        mult = 1.0;
    } else {
        float clip_dist  = clip_far() - clip_near();
        float focus = (view_distance() - clip_near()) / clip_dist + 0.04;
        mult = focus;
    }
    return vec4(
        (
            p +
            vec3(vert_norm) * normal_offset() * mult // * unit_scaling_factor
        ) * vec3(options.vert_scale),
        1.0);
}

vec4 xyz(vec4 v) {
    return vec4(v.xyz / abs(v.w), sign(v.w));
}

void main() {
    vec4 pos0 = get_pos(vec3(vert_pos0));
    vec4 pos1 = get_pos(vec3(vert_pos1));
    vec2 ppos0 = xyz(options.matrix_p * options.matrix_v * options.matrix_m * pos0).xy;
    vec2 ppos1 = xyz(options.matrix_p * options.matrix_v * options.matrix_m * pos1).xy;
    vec2 pdir0 = normalize(ppos1 - ppos0);
    vec2 pdir1 = vec2(-pdir0.y, pdir0.x);
    vec4 off = vec4((options.radius.x + 2.0) * pdir1 * 2.0 * (vert_offset.y-0.5) / options.screen_size.xy, 0, 0);

    vec4 pos = pos0 + vert_offset.x * (pos1 - pos0);
    vec3 norm = normalize(vec3(vert_norm) * vec3(options.vert_scale));

    vec4 wpos = options.matrix_m * pos;
    vec3 wnorm = normalize(mat3(options.matrix_mn) * norm);

    vec4 tpos = options.matrix_ti * wpos;
    vec3 tnorm = vec3(
        dot(wnorm, vec3(options.mirror_x)),
        dot(wnorm, vec3(options.mirror_y)),
        dot(wnorm, vec3(options.mirror_z)));

    vMPosition  = pos;
    vWPosition  = wpos;
    vCPosition  = options.matrix_v * wpos;
    vPPosition  = off + xyz(options.matrix_p * options.matrix_v * wpos);
    vPCPosition = xyz(options.matrix_p * options.matrix_v * wpos).xy;

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

    vColor = options.color_normal;

    if(use_warning()   && warning  > 0.5) vColor = mix(vColor, options.color_warning,  0.75);
    if(use_pinned()    && pinned   > 0.5) vColor = mix(vColor, options.color_pinned,   0.75);
    if(use_seam()      && seam     > 0.5) vColor = mix(vColor, options.color_seam,     0.75);
    if(use_selection() && selected > 0.5) vColor = mix(vColor, options.color_selected, 0.75);

    vColor.a *= 1.0 - options.hidden.x;

    if(debug_invert_backfacing && vCNormal.z < 0.0) {
        vColor = vec4(vec3(1,1,1) - vColor.rgb, vColor.a);
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
in vec4 vColor;            // color of geometry (considers selection)
in vec2 vPCPosition;

out vec4 outColor;
out float gl_FragDepth;

vec3 xyz(vec4 v) { return v.xyz / v.w; }

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
        vec3 aspect = vec3(1.0, options.screen_size.y / options.screen_size.x, 0.0);

        if(options.mirroring.x > 0.5 && length(diffp_x * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_x)), 10.0))) {
            float s = (vTPosition.x < 0.0) ? 1.0 : 0.1;
            mixer.r = 1.0;
            mixer.a = mirror_effect() * s + mixer.a * (1.0 - s);
        }
        if(options.mirroring.y > 0.5 && length(diffp_y * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_y)), 10.0))) {
            float s = (vTPosition.y > 0.0) ? 1.0 : 0.1;
            mixer.g = 1.0;
            mixer.a = mirror_effect() * s + mixer.a * (1.0 - s);
        }
        if(options.mirroring.z > 0.5 && length(diffp_z * aspect) < edge_width * (1.0 - pow(abs(dot(viewdir,dirc_z)), 10.0))) {
            float s = (vTPosition.z < 0.0) ? 1.0 : 0.1;
            mixer.b = 1.0;
            mixer.a = mirror_effect() * s + mixer.a * (1.0 - s);
        }
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
    return vec4(mixer.rgb * m0 + orig.rgb * m1, m0 + orig.a * m1);
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

void main() {
    float clip  = options.clip[1] - options.clip[0];
    float focus = (view_distance() - options.clip[0]) / clip + 0.04;
    vec3  rgb   = vColor.rgb;
    float alpha = vColor.a;

    float dist_from_center = length(options.screen_size.xy * (vPCPosition - vPPosition.xy));
    float alpha_mult = 1.0 - (dist_from_center - options.radius.x);
    if(alpha_mult <= 0) {
        discard;
        return;
    }
    alpha *= min(1.0, alpha_mult);

    if(is_view_perspective()) {
        // perspective projection
        vec3 v = xyz(vCPosition);
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

        float focus_push = focus_mult() * sign(focus - l_clip) * pow(abs(focus - l_clip), 4.0) * 400.0;
        float dist_push = pow(view_distance(), 3.0) * 0.000001;

        // MAGIC!
        gl_FragDepth =
            gl_FragCoord.z
            - magic_offset()    * l_clip * 200.0
            - magic_dotoffset() * l_clip * 0.0001 * (1.0 - d)
            - focus_push
            ;
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

        // MAGIC!
        gl_FragDepth =
            gl_FragCoord.z
            - magic_offset()    * l_clip * 75.0
            - magic_dotoffset() * l_clip * 0.01 * (1.0 - d)
            ;
    }

    alpha *= min(1.0, pow(max(vCNormal.z, 0.01), 0.25));
    outColor = coloring(vec4(rgb, alpha));
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}
