struct Options {
  mat4 MVPMatrix;        // view matrix
  vec4 pos0;
  vec4 color0;
  vec4 pos1;
  vec4 color1;
  vec4 pos2;
  vec4 color2;
};

uniform Options options;

const bool srgbTarget = true;


/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // x: [0,1], alpha.  y: [0,1], beta

out vec4 color;

void main() {
    float a = clamp(pos.x, 0.0, 1.0);
    float b = clamp(pos.y, 0.0, 1.0);
    float c = 1.0 - a - b;
    vec3 p = vec3(options.pos0) * a + vec3(options.pos1) * b + vec3(options.pos2) * c;
    gl_Position = options.MVPMatrix * vec4(p, 1.0);
    color = options.color0 * a + options.color1 * b + options.color2 * c;
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

in vec4 color;

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
    outColor = color;
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
}

