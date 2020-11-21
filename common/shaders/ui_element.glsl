uniform mat4 uMVPMatrix;

uniform float left;
uniform float right;
uniform float top;
uniform float bottom;
uniform float width;
uniform float height;

uniform float margin_left;
uniform float margin_right;
uniform float margin_top;
uniform float margin_bottom;

uniform float padding_left;
uniform float padding_right;
uniform float padding_top;
uniform float padding_bottom;

uniform float border_width;
uniform float border_radius;
uniform vec4  border_left_color;
uniform vec4  border_right_color;
uniform vec4  border_top_color;
uniform vec4  border_bottom_color;

uniform vec4  background_color;

uniform int       using_image;
uniform int       image_fit;
uniform sampler2D image;

attribute vec2 pos;

varying vec2 screen_pos;

const bool DEBUG = false;
const bool DEBUG_CHECKER = true;
const bool DEBUG_IGNORE_ALPHA = false;

const int REGION_OUTSIDE_LEFT   = -4;
const int REGION_OUTSIDE_BOTTOM = -3;
const int REGION_OUTSIDE_RIGHT  = -2;
const int REGION_OUTSIDE_TOP    = -1;
const int REGION_OUTSIDE        = 0;
const int REGION_BORDER_TOP     = 1;
const int REGION_BORDER_RIGHT   = 2;
const int REGION_BORDER_BOTTOM  = 3;
const int REGION_BORDER_LEFT    = 4;
const int REGION_BACKGROUND     = 5;
const int REGION_ERROR          = -100;

/////////////////////////////////////////////////////////////////////////
// vertex shader

#version 330

precision highp float;

void main() {
    // set vertex to bottom-left, top-left, top-right, or bottom-right location, depending on pos
    vec2 p = vec2(
        (pos.x < 0.5) ? (left   - 1) : (right + 1),
        (pos.y < 0.5) ? (bottom - 1) : (top   + 1)
    );

    screen_pos  = p;
    gl_Position = uMVPMatrix * vec4(p, 0, 1);
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

#version 330

precision highp float;

out vec4 outColor;

float sqr(float s) { return s * s; }

int get_region() {
    /* return values:
          0 - outside border region
          1 - top border
          2 - right border
          3 - bottom border
          4 - left border
          5 - inside border region
         -1 - ERROR (should never happen)
    */

    float dist_left   = screen_pos.x - (left + margin_left);
    float dist_right  = (right - margin_right + 1) - screen_pos.x;
    float dist_bottom = screen_pos.y - (bottom + margin_bottom - 1);
    float dist_top    = (top - margin_top) - screen_pos.y;
    float radwid  = max(border_radius, border_width);
    float rad     = max(0, border_radius - border_width);
    float radwid2 = sqr(radwid);
    float rad2    = sqr(rad);
    float r2;

    // outside
    float dist_min = min(min(min(dist_left, dist_right), dist_top), dist_bottom);
    if(dist_min < 0) {
        if(dist_min == dist_left)   return REGION_OUTSIDE_LEFT;
        if(dist_min == dist_right)  return REGION_OUTSIDE_RIGHT;
        if(dist_min == dist_top)    return REGION_OUTSIDE_TOP;
        if(dist_min == dist_bottom) return REGION_OUTSIDE_BOTTOM;
        return REGION_ERROR;
    }

    // within top and bottom, might be left or right side
    if(dist_bottom > radwid && dist_top > radwid) {
        if(dist_left > border_width && dist_right > border_width) return REGION_BACKGROUND;
        if(dist_left < dist_right) return REGION_BORDER_LEFT;
        return REGION_BORDER_RIGHT;
    }

    // within left and right, might be bottom or top
    if(dist_left > radwid && dist_right > radwid) {
        if(dist_bottom > border_width && dist_top > border_width) return REGION_BACKGROUND;
        if(dist_bottom < dist_top) return REGION_BORDER_BOTTOM;
        return REGION_BORDER_TOP;
    }

    // top-left
    if(dist_top <= radwid && dist_left <= radwid) {
        r2 = sqr(dist_left - radwid) + sqr(dist_top - radwid);
        if(r2 > radwid2)             return REGION_OUTSIDE;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_left < dist_top)     return REGION_BORDER_LEFT;
        return REGION_BORDER_TOP;
    }
    // top-right
    if(dist_top <= radwid && dist_right <= radwid) {
        r2 = sqr(dist_right - radwid) + sqr(dist_top - radwid);
        if(r2 > radwid2)             return REGION_OUTSIDE;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_right < dist_top)    return REGION_BORDER_RIGHT;
        return REGION_BORDER_TOP;
    }
    // bottom-left
    if(dist_bottom <= radwid && dist_left <= radwid) {
        r2 = sqr(dist_left - radwid) + sqr(dist_bottom - radwid);
        if(r2 > radwid2)             return REGION_OUTSIDE;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_left < dist_bottom)  return REGION_BORDER_LEFT;
        return REGION_BORDER_BOTTOM;
    }
    // bottom-right
    if(dist_bottom <= radwid && dist_right <= radwid) {
        r2 = sqr(dist_right - radwid) + sqr(dist_bottom - radwid);
        if(r2 > radwid2)             return REGION_OUTSIDE;
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
    float dw = width  - (margin_left + border_width + padding_left + padding_right  + border_width + margin_right);
    float dh = height - (margin_top  + border_width + padding_top  + padding_bottom + border_width + margin_bottom);
    float dx = screen_pos.x - (left + (margin_left + border_width + padding_left));
    float dy = -(screen_pos.y - (top  - (margin_top  + border_width + padding_top)));
    float dsx = (dx+0.5) / dw;
    float dsy = (dy+0.5) / dh;
    // texture
    vec2 tsz = textureSize(image, 0);
    float tw = tsz.x, th = tsz.y;
    float tx, ty;
    vec4 debug_color = vec4(0,0,0,0);
    switch(image_fit) {
        case 0:
            // object-fit: fill = stretch / squash to fill entire drawing space (non-uniform scale)
            // do nothing here
            tx = tw * dx / dw;
            ty = th * dy / dh;
            break;
        case 1: {
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
        case 2: {
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
        case 3:
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
        case 4:
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
    if(0 <= texcoord.x && texcoord.x < 1 && 0 <= texcoord.y && texcoord.y < 1) {
        vec4 t = texture(image, texcoord) + debug_color;
        float a = t.a + c.a * (1.0 - t.a);
        c = vec4((t.rgb * t.a + c.rgb * c.a * (1.0 - t.a)) / a, a);

        if(DEBUG && DEBUG_CHECKER) {
            int i = (int(32 * texcoord.x) + 4 * int(32 * texcoord.y)) % 16;
                 if(i ==  0) c = vec4(0.0, 0.0, 0.0, 1);
            else if(i ==  1) c = vec4(0.0, 0.0, 0.5, 1);
            else if(i ==  2) c = vec4(0.0, 0.5, 0.0, 1);
            else if(i ==  3) c = vec4(0.0, 0.5, 0.5, 1);
            else if(i ==  4) c = vec4(0.5, 0.0, 0.0, 1);
            else if(i ==  5) c = vec4(0.5, 0.0, 0.5, 1);
            else if(i ==  6) c = vec4(0.5, 0.5, 0.0, 1);
            else if(i ==  7) c = vec4(0.5, 0.5, 0.5, 1);
            else if(i ==  8) c = vec4(0.3, 0.3, 0.3, 1);
            else if(i ==  9) c = vec4(0.0, 0.0, 1.0, 1);
            else if(i == 10) c = vec4(0.0, 1.0, 0.0, 1);
            else if(i == 11) c = vec4(0.0, 1.0, 1.0, 1);
            else if(i == 12) c = vec4(1.0, 0.0, 0.0, 1);
            else if(i == 13) c = vec4(1.0, 0.0, 1.0, 1);
            else if(i == 14) c = vec4(1.0, 1.0, 0.0, 1);
            else if(i == 15) c = vec4(1.0, 1.0, 1.0, 1);
        }
    } else if(DEBUG) {
        // vec4 t = vec4(0,1,1,0.50);
        // float a = t.a + c.a * (1.0 - t.a);
        // c = vec4((t.rgb * t.a + c.rgb * c.a * (1.0 - t.a)) / a, a);
        c = vec4(
            1.0 - (1.0 - c.r) * 0.5,
            1.0 - (1.0 - c.g) * 0.5,
            1.0 - (1.0 - c.b) * 0.5,
            c.a
            );
    }
    return c;
}

void main() {
    vec4 c = vec4(0,0,0,0);
    int region = get_region();
         if(region == REGION_OUTSIDE_TOP)    { c = vec4(1,0,0,0.25); if(!DEBUG) discard; }
    else if(region == REGION_OUTSIDE_RIGHT)  { c = vec4(0,1,0,0.25); if(!DEBUG) discard; }
    else if(region == REGION_OUTSIDE_BOTTOM) { c = vec4(0,0,1,0.25); if(!DEBUG) discard; }
    else if(region == REGION_OUTSIDE_LEFT)   { c = vec4(0,1,1,0.25); if(!DEBUG) discard; }
    else if(region == REGION_OUTSIDE)        { c = vec4(1,1,0,0.25); if(!DEBUG) discard; }
    else if(region == REGION_BORDER_TOP)       c = border_top_color;
    else if(region == REGION_BORDER_RIGHT)     c = border_right_color;
    else if(region == REGION_BORDER_BOTTOM)    c = border_bottom_color;
    else if(region == REGION_BORDER_LEFT)      c = border_left_color;
    else if(region == REGION_BACKGROUND)       c = background_color;
    else if(region == REGION_ERROR)            c = vec4(1,0,0,1);  // should never hit here
    else                                       c = vec4(1,0,1,1);  // should really never hit here
    if(using_image > 0) c = mix_image(c);
    // outColor = c;
    // outColor = vec4(c.rgb / max(0.001,c.a), c.a);
    outColor = vec4(c.rgb * c.a, c.a);

    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);
    if(DEBUG_IGNORE_ALPHA) {
        if(outColor.a < 0.25) {
            discard;
        } else {
            outColor.a = 1.0;
        }
    }
}
