uniform mat4  MVPMatrix;        // view matrix

uniform vec3 pos0;
uniform vec4 color0;

uniform vec3 pos1;
uniform vec4 color1;

uniform vec3 pos2;
uniform vec4 color2;

const bool srgbTarget = true;


/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // x: [0,1], alpha.  y: [0,1], beta

out vec4 color;

void main() {
    float a = clamp(pos.x, 0.0, 1.0);
    float b = clamp(pos.y, 0.0, 1.0);
    float c = 1.0 - a - b;
    vec3 p = pos0 * a + pos1 * b + pos2 * c;
    gl_Position = MVPMatrix * vec4(p, 1.0);
    color = color0 * a + color1 * b + color2 * c;
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

