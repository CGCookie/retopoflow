/*
Copyright (C) 2025 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created for RetopoFlow

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

struct Options {
    mat4 MVPMatrix;     // pixel matrix for positioning
    vec4 screensize;    // width,height of screen
    vec4 center;        // center of circle (x,y,0,0)
    vec4 color;         // color of circle
    vec4 settings;      // [radius, thickness, smooth_threshold, 0]
};

uniform Options options;

const bool srgbTarget = true;

// Accessor functions for clarity
float radius() { return options.settings[0]; }
float thickness() { return options.settings[1]; }
float smooth_thresh() { return options.settings[2]; }

/////////////////////////////////////////////////////////////////////////
// vertex shader

in vec2 pos;   // UV coordinates [0,1]x[0,1] for quad

noperspective out vec2 vuv;  // Normalized UV coords centered at 0 with range [-1,1]

void main() {
    // Expand UV coords from [0,1] to [-1,1]
    vuv = pos * 2.0 - 1.0;
    
    // Calculate quad size to match circle diameter
    float size = radius() * 2.0;
    
    // Calculate position in screen space
    vec2 position = options.center.xy + vuv * radius();
    
    // Convert to clip space
    gl_Position = options.MVPMatrix * vec4(position, 0.0, 1.0);
}

/////////////////////////////////////////////////////////////////////////
// fragment shader

noperspective in vec2 vuv;

out vec4 outColor;

vec4 blender_srgb_to_framebuffer_space(vec4 in_color) {
    if (srgbTarget) {
        vec3 c = max(in_color.rgb, vec3(0.0));
        vec3 c1 = c * (1.0 / 12.92);
        vec3 c2 = pow((c + 0.055) * (1.0 / 1.055), vec3(2.4));
        in_color.rgb = mix(c1, c2, step(vec3(0.04045), c));
    }
    return in_color;
}

void main() {
    // Distance from center in UV space
    float dist = length(vuv);
    
    // Anti-aliasing smooth factor
    float smoothFactor = smooth_thresh() / radius();

    // Calculate alpha based on distance and thickness
    float alpha = 1.0;

    float outer_edge = 1.0 - smoothFactor;
    
    if (thickness() <= 0.0) {
        // Filled circle - just smooth outer edge
        alpha = 1.0 - smoothstep(1.0 - smoothFactor, 1.0, dist);
    } else {
        // Ring with thickness
        float normalizedThickness = thickness() / radius();
        float innerRadius = max(0.0, outer_edge - normalizedThickness);
        
        if (dist > outer_edge) {
            // Outside the outer edge - fade out
            alpha = 1.0 - smoothstep(outer_edge, 1.0, dist);
        } else if (dist < innerRadius) {
            // Inside the inner edge - fade out
            alpha = smoothstep(innerRadius - smoothFactor, innerRadius, dist);
        }
    }
    
    // Discard fully transparent fragments
    if (alpha <= 0.0) discard;
    
    // Output color with calculated alpha
    outColor = blender_srgb_to_framebuffer_space(options.color * vec4(1.0, 1.0, 1.0, alpha));
}
