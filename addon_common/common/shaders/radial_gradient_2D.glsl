struct Options {
    mat4 MVPMatrix;     // pixel matrix
    vec4 screensize;    // width,height of screen (for antialiasing)
    vec4 center;        // center of gradient
    vec4 color_center;  // color at center
    vec4 color_edge;    // color at edge
    vec4 radius_t_easing;      // radius of circle, t value for gradient control, easing type, NONE
};

uniform Options options;

const float TAU = 6.28318530718;
const bool srgbTarget = true;

/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // x: [0,1], y: [0,1] for quad vertices

noperspective out vec2 vpos;    // position scaled by screensize
noperspective out vec2 cpos;    // center of line, scaled by screensize

float radius() { return options.radius_t_easing.x; }

void main() {
    // Calculate the position in screen space
    vec2 p = options.center.xy + vec2(0.5,0.5) + (pos * 2.0 - 1.0) * radius();
    vec2 cp = options.center.xy + vec2(0.5,0.5);
    vec4 pcp = options.MVPMatrix * vec4(cp, 0.0, 1.0);
    gl_Position = options.MVPMatrix * vec4(p, 0.0, 1.0);
    vpos = vec2(gl_Position.x * options.screensize.x, gl_Position.y * options.screensize.y);
    cpos = vec2(pcp.x * options.screensize.x, pcp.y * options.screensize.y);
}

/////////////////////////////////////////////////////////////////////////
// fragment shader

noperspective in vec2 vpos;
noperspective in vec2 cpos;

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

float radius() { return options.radius_t_easing.x; }
float t_value() { return options.radius_t_easing.y; }
float easing_type() { return options.radius_t_easing.z; }

// Easing functions
float linear_ease(float x) {
    return x;
}

float quad_ease(float x) {
    return x * x;
}

float cubic_ease(float x) {
    return x * x * x;
}

float sine_ease(float x) {
    return sin(x * 1.57079632679); // pi/2
}

float apply_easing(float x) {
    float type = floor(easing_type() + 0.5); // Round to nearest integer
    if (type == 0.0) return linear_ease(x);
    if (type == 1.0) return quad_ease(x);
    if (type == 2.0) return cubic_ease(x);
    if (type == 3.0) return sine_ease(x);
    return linear_ease(x);
}

void main() {
    // Calculate distance from center
    float dist = length(cpos - vpos);
    float max_dist = radius() * 2.0; // * options.screensize.x;
    float t = t_value();

    // Calculate falloff factor
    float falloff = 1.0 - pow(dist / max_dist, 1.0 / t);
    falloff = apply_easing(clamp(falloff, 0.0, 1.0));

    // Mix colors based on falloff
    vec4 color = mix(options.color_edge, options.color_center, falloff);
    
    // Anti-aliasing at the edge
    if (dist > max_dist) {
        color.a *= clamp(1.0 - (dist - max_dist) / (max_dist * 0.1), 0.0, 1.0);
    }
    
    // Convert to sRGB space
    outColor = blender_srgb_to_framebuffer_space(color);
}
