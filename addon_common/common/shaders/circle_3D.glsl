struct Options {
  mat4  MVPMatrix;  // pixel matrix
  vec4  center;     // center of circle
  vec4  color;      // color of circle
  vec4  plane_x;    // x direction in plane the circle lies in
  vec4  plane_y;    // y direction in plane the circle lies in
  vec4  settings;   // radius, line width (perp to line in plane), depth range near for drawover, depth range far
};

uniform Options options;

float radius()      { return options.settings[0]; }
float width()       { return options.settings[1]; }
float depth_near()  { return options.settings[2]; }
float depth_far()   { return options.settings[3]; }


/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // x: [0,1], ratio of circumference.  y: [0,1], inner/outer radius (width)

const float TAU = 6.28318530718;

void main() {
    float ang = TAU * pos.x;
    float r = radius() + pos.y * width();
    vec3 p = vec3(options.center) + r * (vec3(options.plane_x) * cos(ang) + vec3(options.plane_y) * sin(ang));
    gl_Position = options.MVPMatrix * vec4(p, 1.0);
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

out vec4 outColor;
// out float gl_FragDepth;

const bool srgbTarget = true;
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
    outColor = options.color;
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
    gl_FragDepth = mix(depth_near(), depth_far(), gl_FragCoord.z);
}

