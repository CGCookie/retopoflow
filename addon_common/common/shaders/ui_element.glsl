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

#version 330

// // the following two lines are an attempt to solve issues #1025, #879, #753
// precision mediump float;
// precision lowp  int;   // only used to represent enum or bool

struct Options {
    mat4 uMVPMatrix;

    vec4 lrtb;
    vec4 wh;

    vec4 depth;

    vec4 margin_lrtb;
    vec4 padding_lrtb;

    vec4 border_width_radius;
    vec4 border_left_color;
    vec4 border_right_color;
    vec4 border_top_color;
    vec4 border_bottom_color;

    vec4 background_color;

    // see IMAGE_SCALE_XXX values below
    ivec4 image_settings;
};

uniform Options options;
uniform sampler2D image;


const bool srgbTarget = true;

bool image_use() { return options.image_settings[0] != 0; }
int  image_fit() { return options.image_settings[1]; }

float pos_l() { return options.lrtb[0]; }
float pos_r() { return options.lrtb[1]; }
float pos_t() { return options.lrtb[2]; }
float pos_b() { return options.lrtb[3]; }

float size_w() { return options.wh[0]; }
float size_h() { return options.wh[1]; }

float depth() { return options.depth[0]; }

float margin_l() { return options.margin_lrtb[0]; }
float margin_r() { return options.margin_lrtb[1]; }
float margin_t() { return options.margin_lrtb[2]; }
float margin_b() { return options.margin_lrtb[3]; }
float padding_l() { return options.padding_lrtb[0]; }
float padding_r() { return options.padding_lrtb[1]; }
float padding_t() { return options.padding_lrtb[2]; }
float padding_b() { return options.padding_lrtb[3]; }

float border_width()  { return options.border_width_radius[0]; }
float border_radius() { return options.border_width_radius[1]; }
vec4 border_left_color()   { return options.border_left_color; }
vec4 border_right_color()  { return options.border_right_color; }
vec4 border_top_color()    { return options.border_top_color; }
vec4 border_bottom_color() { return options.border_bottom_color; }

vec4 background_color() { return options.background_color; }


////////////////////////////////////////
// vertex shader

in vec2 pos;

out vec2 screen_pos;

void main() {
    // set vertex to bottom-left, top-left, top-right, or bottom-right location, depending on pos
    vec2 p = vec2(
        (pos.x < 0.5) ? (pos_l() - 1.0) : (pos_r() + 1.0),
        (pos.y < 0.5) ? (pos_b() - 1.0) : (pos_t() + 1.0)
    );

    // convert depth to z-order
    float zorder = 1.0 - depth() / 1000.0;

    screen_pos  = p;
    gl_Position = options.uMVPMatrix * vec4(p, zorder, 1);
}



////////////////////////////////////////
// fragment shader

in vec2 screen_pos;

out vec4 outColor;
out float gl_FragDepth;

float sqr(float s) { return s * s; }
float sumsqr(float a, float b) { return sqr(a) + sqr(b); }
float min4(float a, float b, float c, float d) { return min(min(min(a, b), c) ,d); }

vec4 mix_over(vec4 above, vec4 below) {
    vec3 a_ = above.rgb * above.a;
    vec3 b_ = below.rgb * below.a;
    float alpha = above.a + (1.0 - above.a) * below.a;
    return vec4((a_ + b_ * (1.0 - above.a)) / alpha, alpha);
}

int get_margin_region(float dist_left, float dist_right, float dist_top, float dist_bottom) {
    float dist_min = min4(dist_left, dist_right, dist_top, dist_bottom);
    if(dist_min == dist_left)   return REGION_MARGIN_LEFT;
    if(dist_min == dist_right)  return REGION_MARGIN_RIGHT;
    if(dist_min == dist_top)    return REGION_MARGIN_TOP;
    if(dist_min == dist_bottom) return REGION_MARGIN_BOTTOM;
    return REGION_ERROR;    // this should never happen
}

int get_region() {
    /* this function determines which region the fragment is in wrt properties of UI element,
       specifically: position, size, border width, border radius, margins

        v top-left
        +-----------------+
        | \             / | <- margin regions
        |   +---------+   |
        |   |\       /|   | <- border regions
        |   | +-----+ |   |
        |   | |     | |   | <- inside border region (content area + padding)
        |   | +-----+ |   |
        |   |/       \|   |
        |   +---------+   |
        | /             \ |
        +-----------------+
                          ^ bottom-right

        - margin regions
            - broken into top, right, bottom, left
            - each TRBL margin size can be different size
        - border regions
            - broken into top, right, bottom, left
            - each can have different colors, but all same size (TODO!)
        - inside border region
            - where content is drawn (image)
            - NOTE: padding takes up this space
        - ERROR region _should_ never happen, but can be returned from this fn if something goes wrong
    */

    float dist_left   = screen_pos.x - (pos_l() + margin_l());
    float dist_right  = (pos_r() - margin_r() + 1.0) - screen_pos.x;
    float dist_bottom = screen_pos.y - (pos_b() + margin_b() - 1.0);
    float dist_top    = (pos_t() - margin_t()) - screen_pos.y;
    float radwid  = max(border_radius(), border_width());
    float rad     = max(0.0, border_radius() - border_width());
    float radwid2 = sqr(radwid);
    float rad2    = sqr(rad);

    if(dist_left < 0 || dist_right < 0 || dist_top < 0 || dist_bottom < 0) return REGION_OUTSIDE;

    // margin
    int margin_region = get_margin_region(dist_left, dist_right, dist_top, dist_bottom);

    // within top and bottom, might be left or right side
    if(dist_bottom > radwid && dist_top > radwid) {
        if(dist_left > border_width() && dist_right > border_width()) return REGION_BACKGROUND;
        if(dist_left < dist_right) return REGION_BORDER_LEFT;
        return REGION_BORDER_RIGHT;
    }

    // within left and right, might be bottom or top
    if(dist_left > radwid && dist_right > radwid) {
        if(dist_bottom > border_width() && dist_top > border_width()) return REGION_BACKGROUND;
        if(dist_bottom < dist_top) return REGION_BORDER_BOTTOM;
        return REGION_BORDER_TOP;
    }

    // top-left
    if(dist_top <= radwid && dist_left <= radwid) {
        float r2 = sumsqr(dist_left - radwid, dist_top - radwid);
        if(r2 > radwid2)             return margin_region;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_left < dist_top)     return REGION_BORDER_LEFT;
        return REGION_BORDER_TOP;
    }
    // top-right
    if(dist_top <= radwid && dist_right <= radwid) {
        float r2 = sumsqr(dist_right - radwid, dist_top - radwid);
        if(r2 > radwid2)             return margin_region;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_right < dist_top)    return REGION_BORDER_RIGHT;
        return REGION_BORDER_TOP;
    }
    // bottom-left
    if(dist_bottom <= radwid && dist_left <= radwid) {
        float r2 = sumsqr(dist_left - radwid, dist_bottom - radwid);
        if(r2 > radwid2)             return margin_region;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_left < dist_bottom)  return REGION_BORDER_LEFT;
        return REGION_BORDER_BOTTOM;
    }
    // bottom-right
    if(dist_bottom <= radwid && dist_right <= radwid) {
        float r2 = sumsqr(dist_right - radwid, dist_bottom - radwid);
        if(r2 > radwid2)             return margin_region;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_right < dist_bottom) return REGION_BORDER_RIGHT;
        return REGION_BORDER_BOTTOM;
    }

    // something bad happened
    return REGION_ERROR;
}

vec4 mix_image(vec4 bg) {
    vec4 c = bg;
    // drawing space
    float dw = size_w() - (margin_l() + border_width() + padding_l() + padding_r() + border_width() + margin_r());
    float dh = size_h() - (margin_t() + border_width() + padding_t() + padding_b() + border_width() + margin_b());
    float dx = screen_pos.x - (pos_l() + (margin_l() + border_width() + padding_l()));
    float dy = -(screen_pos.y - (pos_t()  - (margin_t()  + border_width() + padding_t())));
    float dsx = (dx + 0.5) / dw;
    float dsy = (dy + 0.5) / dh;
    // texture
    vec2 tsz = vec2(textureSize(image, 0));
    float tw = tsz.x, th = tsz.y;
    float tx, ty;

    switch(image_fit()) {
        case IMAGE_SCALE_FILL:
            // object-fit: fill = stretch / squash to fill entire drawing space (non-uniform scale)
            // do nothing here
            tx = tw * dx / dw;
            ty = th * dy / dh;
            break;
        case IMAGE_SCALE_CONTAIN: {
            // object-fit: contain = uniformly scale texture to fit entirely in drawing space (will be letterboxed)
            // find smaller scaled dimension, and use that
            float _tw, _th;
            if(dw / dh < tw / th) {
                // scaling by height is too big, so scale by width
                _tw = tw;
                _th = tw * dh / dw;
            } else {
                _tw = th * dw / dh;
                _th = th;
            }
            tx = dsx * _tw - (_tw - tw) / 2.0;
            ty = dsy * _th - (_th - th) / 2.0;
            break; }
        case IMAGE_SCALE_COVER: {
            // object-fit: cover = uniformly scale texture to fill entire drawing space (will be cropped)
            // find larger scaled dimension, and use that
            float _tw, _th;
            if(dw / dh > tw / th) {
                // scaling by height is too big, so scale by width
                _tw = tw;
                _th = tw * dh / dw;
            } else {
                _tw = th * dw / dh;
                _th = th;
            }
            tx = dsx * _tw - (_tw - tw) / 2.0;
            ty = dsy * _th - (_th - th) / 2.0;
            break; }
        case IMAGE_SCALE_DOWN:
            // object-fit: scale-down = either none or contain, whichever is smaller
            if(dw >= tw && dh >= th) {
                // none
                tx = dx + (tw - dw) / 2.0;
                ty = dy + (th - dh) / 2.0;
            } else {
                float _tw, _th;
                if(dw / dh < tw / th) {
                    // scaling by height is too big, so scale by width
                    _tw = tw;
                    _th = tw * dh / dw;
                } else {
                    _tw = th * dw / dh;
                    _th = th;
                }
                tx = dsx * _tw - (_tw - tw) / 2.0;
                ty = dsy * _th - (_th - th) / 2.0;
            }
            break;
        case IMAGE_SCALE_NONE:
            // object-fit: none (no resizing)
            tx = dx + (tw - dw) / 2.0;
            ty = dy + (th - dh) / 2.0;
            break;
        default: // error!
            tx = tw / 2.0;
            ty = th / 2.0;
            break;
    }

    vec2 texcoord = vec2(tx / tw, 1 - ty / th);
    bool inside = 0.0 <= texcoord.x && texcoord.x <= 1.0 && 0.0 <= texcoord.y && texcoord.y <= 1.0;
    if(inside) {
        vec4 t = texture(image, texcoord) + COLOR_DEBUG_IMAGE;
        c = mix_over(t, c);
    }

    #ifdef DEBUG_IMAGE_CHECKER
        if(inside) {
            // generate checker pattern to test scaling
            switch((int(32.0 * texcoord.x) + 4 * int(32.0 * texcoord.y)) % 16) {
                case  0: c = COLOR_CHECKER_00; break;
                case  1: c = COLOR_CHECKER_01; break;
                case  2: c = COLOR_CHECKER_02; break;
                case  3: c = COLOR_CHECKER_03; break;
                case  4: c = COLOR_CHECKER_04; break;
                case  5: c = COLOR_CHECKER_05; break;
                case  6: c = COLOR_CHECKER_06; break;
                case  7: c = COLOR_CHECKER_07; break;
                case  8: c = COLOR_CHECKER_08; break;
                case  9: c = COLOR_CHECKER_09; break;
                case 10: c = COLOR_CHECKER_10; break;
                case 11: c = COLOR_CHECKER_11; break;
                case 12: c = COLOR_CHECKER_12; break;
                case 13: c = COLOR_CHECKER_13; break;
                case 14: c = COLOR_CHECKER_14; break;
                case 15: c = COLOR_CHECKER_15; break;
            }
        }
    #endif

    #ifdef DEBUG_IMAGE_OUTSIDE
        if(!inside) {
            c = vec4(
                1.0 - (1.0 - c.r) * 0.5,
                1.0 - (1.0 - c.g) * 0.5,
                1.0 - (1.0 - c.b) * 0.5,
                c.a
                );
        }
    #endif

    return c;
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
    vec4 c = vec4(0,0,0,0);

    int region = get_region();

    // workaround switched-discard (issue #1042)
    #ifndef DEBUG_DONT_DISCARD
        #ifndef DEBUG_COLOR_REGIONS
            #ifndef DEBUG_COLOR_MARGINS
                if(region == REGION_MARGIN_TOP)    { discard; return; }
                if(region == REGION_MARGIN_RIGHT)  { discard; return; }
                if(region == REGION_MARGIN_BOTTOM) { discard; return; }
                if(region == REGION_MARGIN_LEFT)   { discard; return; }
            #endif
            if(region == REGION_OUTSIDE)           { discard; return; }
        #endif
    #endif

    switch(region) {
        case REGION_BORDER_TOP:    c = border_top_color();    break;
        case REGION_BORDER_RIGHT:  c = border_right_color();  break;
        case REGION_BORDER_BOTTOM: c = border_bottom_color(); break;
        case REGION_BORDER_LEFT:   c = border_left_color();   break;
        case REGION_BACKGROUND:    c = background_color();    break;

        // following colors show only if DEBUG settings allow or something really unexpected happens
        case REGION_MARGIN_TOP:    c = COLOR_MARGIN_TOP;    break;
        case REGION_MARGIN_RIGHT:  c = COLOR_MARGIN_RIGHT;  break;
        case REGION_MARGIN_BOTTOM: c = COLOR_MARGIN_BOTTOM; break;
        case REGION_MARGIN_LEFT:   c = COLOR_MARGIN_LEFT;   break;
        case REGION_OUTSIDE:       c = COLOR_OUTSIDE;       break;  // keep transparent
        case REGION_ERROR:         c = COLOR_ERROR;         break;  // should never hit here
        default:                   c = COLOR_ERROR_NEVER;           // should **really** never hit here
    }

    // DEBUG_COLOR_REGIONS will mix over other colors
    #ifdef DEBUG_COLOR_REGIONS
        switch(region) {
            case REGION_BORDER_TOP:    c = mix_over(COLOR_BORDER_TOP,    c); break;
            case REGION_BORDER_RIGHT:  c = mix_over(COLOR_BORDER_RIGHT,  c); break;
            case REGION_BORDER_BOTTOM: c = mix_over(COLOR_BORDER_BOTTOM, c); break;
            case REGION_BORDER_LEFT:   c = mix_over(COLOR_BORDER_LEFT,   c); break;
            case REGION_BACKGROUND:    c = mix_over(COLOR_BACKGROUND,    c); break;
        }
    #endif

    // apply image if used
    if(image_use()) c = mix_image(c);

    c = vec4(c.rgb * c.a, c.a);

    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    c = blender_srgb_to_framebuffer_space(c);

    #ifdef DEBUG_SNAP_ALPHA
        if(c.a < 0.25) {
            c.a = 0.0;
            #ifndef DEBUG_DONT_DISCARD
                discard; return;
            #endif
        }
        else c.a = 1.0;
    #endif

    outColor = c;
    //gl_FragDepth = gl_FragDepth * 0.999999;
    gl_FragDepth = gl_FragCoord.z * 0.999999; // fix for issue #915?
}
