uniform mat4  MVPMatrix;        // pixel matrix
uniform vec3  center;           // center of circle
uniform vec4  color;            // color of circle
uniform vec3  plane_x;          // x direction in plane the circle lies in
uniform vec3  plane_y;          // y direction in plane the circle lies in
uniform float radius;           // radius of circle
uniform float width;            // line width, perpendicular to line (in plane)
uniform float depth_near;       // depth range near, to ensure drawover
uniform float depth_far;        // depth range far, to to ensure drawover


/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;                    // x: [0,1], ratio of circumference.  y: [0,1], inner/outer radius (width)

const float TAU = 6.28318530718;

void main() {
    float ang = TAU * pos.x;
    float r = radius + pos.y * width;
    vec3 p = center + r * (plane_x * cos(ang) + plane_y * sin(ang));
    gl_Position = MVPMatrix * vec4(p, 1.0);
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

out vec4 outColor;
out float outDepth;

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
    outColor = color;
    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
    outDepth = mix(depth_near, depth_far, gl_FragCoord.z);
}

