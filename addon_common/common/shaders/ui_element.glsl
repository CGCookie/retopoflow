// the following two lines are an attempt to solve issues #1025, #879, #753
precision highp float;
precision lowp  int;   // only used to represent enum or bool

uniform mat4 uMVPMatrix;

uniform float left;
uniform float right;
uniform float top;
uniform float bottom;
uniform float width;
uniform float height;

uniform float depth;

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


// debugging options
const bool DEBUG_COLOR_MARGINS = false;     // colors pixels in margin (top, left, bottom, right)
const bool DEBUG_COLOR_REGIONS = false;     // colors pixels based on region
const bool DEBUG_IMAGE_CHECKER = false;     // replaces images with checker pattern to test scaling
const bool DEBUG_IMAGE_OUTSIDE = false;     // shifts colors if texcoord is outside [0,1] (in padding region)
const bool DEBUG_IGNORE_ALPHA  = false;     // snaps alpha to 0 or 1 based on 0.25 threshold

// labeled magic numbers (enum), only used to identify which region a fragment is in relative to UI element properties
const int REGION_MARGIN_LEFT   = 0;
const int REGION_MARGIN_BOTTOM = 1;
const int REGION_MARGIN_RIGHT  = 2;
const int REGION_MARGIN_TOP    = 3;
const int REGION_BORDER_TOP    = 4;
const int REGION_BORDER_RIGHT  = 5;
const int REGION_BORDER_BOTTOM = 6;
const int REGION_BORDER_LEFT   = 7;
const int REGION_BACKGROUND    = 8;
const int REGION_ERROR         = 10;

// colors used if DEBUG_COLOR_MARGINS or DEBUG_COLOR_REGIONS are set to true
const vec4 COLOR_MARGIN_LEFT   = vec4(1.0, 0.0, 0.0, 0.25);
const vec4 COLOR_MARGIN_BOTTOM = vec4(0.0, 1.0, 0.0, 0.25);
const vec4 COLOR_MARGIN_RIGHT  = vec4(0.0, 0.0, 1.0, 0.25);
const vec4 COLOR_MARGIN_TOP    = vec4(0.0, 1.0, 1.0, 0.25);
const vec4 COLOR_BORDER_TOP    = vec4(0.5, 0.0, 0.0, 0.25);
const vec4 COLOR_BORDER_RIGHT  = vec4(0.0, 0.5, 0.5, 0.25);
const vec4 COLOR_BORDER_BOTTOM = vec4(0.0, 0.5, 0.5, 0.25);
const vec4 COLOR_BORDER_LEFT   = vec4(0.0, 0.5, 0.5, 0.25);
const vec4 COLOR_BACKGROUND    = vec4(0.5, 0.5, 0.0, 0.25);
const vec4 COLOR_ERROR         = vec4(1.0, 0.0, 0.0, 1.00);
const vec4 COLOR_ERROR_NEVER   = vec4(1.0, 0.0, 1.0, 1.00);

const vec4 DEBUG_IMAGE_COLOR   = vec4(0.0, 0.0, 0.0, 0.00);

// labeled magic numbers (enum), needs to correspond with `UI_Draw.texture_fit_map`
const int IMAGE_SCALE_FILL     = 0;
const int IMAGE_SCALE_CONTAIN  = 1;
const int IMAGE_SCALE_COVER    = 2;
const int IMAGE_SCALE_DOWN     = 3;
const int IMAGE_SCALE_NONE     = 4;


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
    gl_Position = uMVPMatrix * vec4(p, 1.0 - depth/1000.0, 1);
}


/////////////////////////////////////////////////////////////////////////
// fragment shader

#version 330

precision highp float;

out vec4 outColor;

float sqr(float s) { return s * s; }

int get_margin_region(float dist_min, float dist_left, float dist_right, float dist_top, float dist_bottom) {
    if(dist_min == dist_left)   return REGION_MARGIN_LEFT;
    if(dist_min == dist_right)  return REGION_MARGIN_RIGHT;
    if(dist_min == dist_top)    return REGION_MARGIN_TOP;
    if(dist_min == dist_bottom) return REGION_MARGIN_BOTTOM;
    return REGION_ERROR;
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

    float dist_left   = screen_pos.x - (left + margin_left);
    float dist_right  = (right - margin_right + 1) - screen_pos.x;
    float dist_bottom = screen_pos.y - (bottom + margin_bottom - 1);
    float dist_top    = (top - margin_top) - screen_pos.y;
    float radwid  = max(border_radius, border_width);
    float rad     = max(0, border_radius - border_width);
    float radwid2 = sqr(radwid);
    float rad2    = sqr(rad);
    float r2;

    // margin
    float dist_min = min(min(min(dist_left, dist_right), dist_top), dist_bottom);
    int margin_region = get_margin_region(dist_min, dist_left, dist_right, dist_top, dist_bottom);
    if(dist_min < 0) return margin_region;

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
        if(r2 > radwid2)             return margin_region;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_left < dist_top)     return REGION_BORDER_LEFT;
        return REGION_BORDER_TOP;
    }
    // top-right
    if(dist_top <= radwid && dist_right <= radwid) {
        r2 = sqr(dist_right - radwid) + sqr(dist_top - radwid);
        if(r2 > radwid2)             return margin_region;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_right < dist_top)    return REGION_BORDER_RIGHT;
        return REGION_BORDER_TOP;
    }
    // bottom-left
    if(dist_bottom <= radwid && dist_left <= radwid) {
        r2 = sqr(dist_left - radwid) + sqr(dist_bottom - radwid);
        if(r2 > radwid2)             return margin_region;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_left < dist_bottom)  return REGION_BORDER_LEFT;
        return REGION_BORDER_BOTTOM;
    }
    // bottom-right
    if(dist_bottom <= radwid && dist_right <= radwid) {
        r2 = sqr(dist_right - radwid) + sqr(dist_bottom - radwid);
        if(r2 > radwid2)             return margin_region;
        if(r2 < rad2)                return REGION_BACKGROUND;
        if(dist_right < dist_bottom) return REGION_BORDER_RIGHT;
        return REGION_BORDER_BOTTOM;
    }

    // something bad happened
    return REGION_ERROR;
}

vec4 mix_over(vec4 above, vec4 below) {
    vec3 a_ = above.rgb * above.a;
    vec3 b_ = below.rgb * below.a;
    float alpha = above.a + (1.0 - above.a) * below.a;
    return vec4((a_ + b_ * (1.0 - above.a)) / alpha, alpha);
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

    switch(image_fit) {
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
    if(0 <= texcoord.x && texcoord.x <= 1 && 0 <= texcoord.y && texcoord.y <= 1) {
        vec4 t = texture(image, texcoord) + DEBUG_IMAGE_COLOR;
        c = mix_over(t, c);

        if(DEBUG_IMAGE_CHECKER) {
            // generate checker pattern to test scaling
            switch((int(32 * texcoord.x) + 4 * int(32 * texcoord.y)) % 16) {
                case  0: c = vec4(0.0, 0.0, 0.0, 1); break;
                case  1: c = vec4(0.0, 0.0, 0.5, 1); break;
                case  2: c = vec4(0.0, 0.5, 0.0, 1); break;
                case  3: c = vec4(0.0, 0.5, 0.5, 1); break;
                case  4: c = vec4(0.5, 0.0, 0.0, 1); break;
                case  5: c = vec4(0.5, 0.0, 0.5, 1); break;
                case  6: c = vec4(0.5, 0.5, 0.0, 1); break;
                case  7: c = vec4(0.5, 0.5, 0.5, 1); break;
                case  8: c = vec4(0.3, 0.3, 0.3, 1); break;
                case  9: c = vec4(0.0, 0.0, 1.0, 1); break;
                case 10: c = vec4(0.0, 1.0, 0.0, 1); break;
                case 11: c = vec4(0.0, 1.0, 1.0, 1); break;
                case 12: c = vec4(1.0, 0.0, 0.0, 1); break;
                case 13: c = vec4(1.0, 0.0, 1.0, 1); break;
                case 14: c = vec4(1.0, 1.0, 0.0, 1); break;
                case 15: c = vec4(1.0, 1.0, 1.0, 1); break;
            }
        }
    } else if(DEBUG_IMAGE_OUTSIDE) {
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
    switch(region) {
        case REGION_MARGIN_TOP:
            if(DEBUG_COLOR_MARGINS || DEBUG_COLOR_REGIONS) c = COLOR_MARGIN_TOP;
            else discard;
            break;
        case REGION_MARGIN_RIGHT:
            if(DEBUG_COLOR_MARGINS || DEBUG_COLOR_REGIONS) c = COLOR_MARGIN_RIGHT;
            else discard;
            break;
        case REGION_MARGIN_BOTTOM:
            if(DEBUG_COLOR_MARGINS || DEBUG_COLOR_REGIONS) c = COLOR_MARGIN_BOTTOM;
            else discard;
            break;
        case REGION_MARGIN_LEFT:
            if(DEBUG_COLOR_MARGINS || DEBUG_COLOR_REGIONS) c = COLOR_MARGIN_LEFT;
            else discard;
            break;
        case REGION_BORDER_TOP:
            c = border_top_color;
            if(DEBUG_COLOR_REGIONS) c = mix_over(COLOR_BORDER_TOP, c);
            break;
        case REGION_BORDER_RIGHT:
            c = border_right_color;
            if(DEBUG_COLOR_REGIONS) c = mix_over(COLOR_BORDER_RIGHT, c);
            break;
        case REGION_BORDER_BOTTOM:
            c = border_bottom_color;
            if(DEBUG_COLOR_REGIONS) c = mix_over(COLOR_BORDER_BOTTOM, c);
            break;
        case REGION_BORDER_LEFT:
            c = border_left_color;
            if(DEBUG_COLOR_REGIONS) c = mix_over(COLOR_BORDER_LEFT, c);
            break;
        case REGION_BACKGROUND:
            c = background_color;
            if(DEBUG_COLOR_REGIONS) c = mix_over(COLOR_BACKGROUND, c);
            break;
        case REGION_ERROR:      // should never hit here
            c = COLOR_ERROR;
            break;
        default:                // should **really** never hit here
            c = COLOR_ERROR_NEVER;
    }

    // apply image if used
    if(using_image > 0) c = mix_image(c);

    outColor = vec4(c.rgb * c.a, c.a);

    // https://wiki.blender.org/wiki/Reference/Release_Notes/2.83/Python_API
    outColor = blender_srgb_to_framebuffer_space(outColor);

    if(DEBUG_IGNORE_ALPHA) {
        if(outColor.a < 0.25) discard;
        else outColor.a = 1.0;
    }

    gl_FragDepth = gl_FragDepth * 0.999999;
}
