'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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
'''


import gpu
from gpu_extras.presets import draw_texture_2d

from . import ui_settings  # needs to be first
from .ui_draw import ui_draw

from . import gpustate
from .globals import Globals
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .profiler import profiler, time_it


class UI_Core_Draw:

    def _draw_real(self, offset, scissor_include_margin=True, scissor_include_padding=True):
        dpi_mult = Globals.drawing.get_dpi_mult()
        ox,oy = offset

        if ui_settings.DEBUG_COLOR_CLEAN:
            if ui_settings.DEBUG_COLOR == 0:
                t_max = 2
                t = max(0, t_max - (time.time() - self._clean_debugging.get(ui_settings.DEBUG_PROPERTY, 0))) / t_max
                background_override = Color( ( t, t/2, 0, 0.75 ) )
            elif ui_settings.DEBUG_COLOR == 1:
                t = self._clean_debugging.get(ui_settings.DEBUG_PROPERTY, 0)
                d = time.time() - t
                h = (t / 2) % 1
                s = 1.0
                l = max(0, 0.5 - d / 10)
                background_override = Color.HSL((h, s, l, 0.75))
        else:
            background_override = None

        gpustate.blend('ALPHA_PREMULT', only='enable')

        sc = self._style_cache
        margin_top,  margin_right,  margin_bottom,  margin_left  = sc['margin-top'],  sc['margin-right'],  sc['margin-bottom'],  sc['margin-left']
        padding_top, padding_right, padding_bottom, padding_left = sc['padding-top'], sc['padding-right'], sc['padding-bottom'], sc['padding-left']
        border_width = sc['border-width']

        ol, ot = int(self._l + ox), int(self._t + oy)

        with profiler.code('drawing mbp'):
            texture_id = self._image_data['texid']      if self._src in {'image', 'image loading'} else None
            gputexture = self._image_data['gputexture'] if self._src in {'image', 'image loading'} else None
            texture_fit = self._computed_styles.get('object-fit', 'fill')
            ui_draw.draw(ol, ot, self._w, self._h, dpi_mult, self._style_cache, texture_id, gputexture, texture_fit, background_override=background_override, depth=len(self._selector))

        with profiler.code('drawing children'):
            # compute inner scissor area
            mt,mr,mb,ml = (margin_top, margin_right, margin_bottom, margin_left)  if scissor_include_margin  else (0,0,0,0)
            pt,pr,pb,pl = (padding_top,padding_right,padding_bottom,padding_left) if scissor_include_padding else (0,0,0,0)
            bw = border_width
            il = round(self._l + (ml + bw + pl) + ox)
            it = round(self._t - (mt + bw + pt) + oy)
            iw = round(self._w - ((ml + bw + pl) + (pr + bw + mr)))
            ih = round(self._h - ((mt + bw + pt) + (pb + bw + mb)))
            noclip = self._computed_styles.get('overflow-x', 'visible') == 'visible' and self._computed_styles.get('overflow-y', 'visible') == 'visible'

            with gpustate.ScissorStack.wrap(il, it, iw, ih, msg=f'{self} mbp', disabled=noclip):
                if self._innerText is not None:
                    size_prev = Globals.drawing.set_font_size(self._fontsize, fontid=self._fontid)
                    if self._textshadow is not None:
                        tsx,tsy,tsc = self._textshadow
                        offset2 = (int(ox + tsx), int(oy - tsy))
                        Globals.drawing.set_font_color(self._fontid, tsc)
                        for child in self._children_all_sorted:
                            child._draw(offset2)
                    Globals.drawing.set_font_color(self._fontid, self._fontcolor)
                    for child in self._children_all_sorted:
                        child._draw(offset)
                    Globals.drawing.set_font_size(size_prev, fontid=self._fontid)
                elif self._innerTextAsIs is not None:
                    Globals.drawing.text_draw2D_simple(self._innerTextAsIs, (ol, ot))
                else:
                    for child in self._children_all_sorted:
                        gpustate.blend('ALPHA_PREMULT', only='enable')
                        child._draw(offset)

    default_draw_cache_style = {
        'background-color': (0,0,0,0),
        'margin-top': 0,
        'margin-right': 0,
        'margin-bottom': 0,
        'margin-left': 0,
        'padding-top': 0,
        'padding-right': 0,
        'padding-bottom': 0,
        'padding-left': 0,
        'border-width': 0,
    }
    def _draw_cache(self, offset):
        ox,oy = offset
        with gpustate.ScissorStack.wrap(self._l+ox, self._t+oy, self._w, self._h):
            if self._cacheRenderBuf:
                gpustate.blend('ALPHA_PREMULT')
                texture_id = self._cacheRenderBuf.color_texture
                if True:
                    draw_texture_2d(texture_id, (self._l+ox, self._b+oy), self._w, self._h)
                else:
                    ui_draw.draw(
                        self._l+ox, self._t+oy, self._w, self._h,
                        Globals.drawing.get_dpi_mult(),
                        self.default_draw_cache_style,
                        texture_id, 0,
                        background_override=None,
                    )
            else:
                gpustate.blend('ALPHA_PREMULT', only='function')
                self._draw_real(offset)

    def _cache_create(self):
        if self._w < 1 or self._h < 1: return
        # (re-)create off-screen buffer
        if self._cacheRenderBuf:
            # already have a render buffer, so just resize it
            self._cacheRenderBuf.resize(self._w, self._h)
        else:
            # do not already have a render buffer, so create one
            self._cacheRenderBuf = gpustate.FrameBuffer(self._w, self._h)

    def _cache_hierarchical(self, depth):
        if self._innerTextAsIs is not None: return   # do not cache this low level!
        if self._innerText is not None: return

        # make sure children are all cached (if applicable)
        for child in self._children_all_sorted:
            child._cache(depth=depth+1)

        self._cache_create()

        sl, st, sw, sh = 0, self._h - 1, self._w, self._h
        with self._cacheRenderBuf.bind():
            self._draw_real((-self._l, -self._b))
            # with gpustate.ScissorStack.wrap(sl, st, sw, sh, clamp=False):
            #     self._draw_real((-self._l, -self._b))

    def _cache_textleaves(self, depth):
        for child in self._children_all_sorted:
            child._cache(depth=depth+1)
        if depth == 0:
            self._cache_onlyroot(depth)
            return
        if self._innerText is None:
            return
        self._cache_create()
        sl, st, sw, sh = 0, self._h - 1, self._w, self._h
        with self._cacheRenderBuf.bind():
            self._draw_real((-self._l, -self._b))
            # with gpustate.ScissorStack.wrap(sl, st, sw, sh, clamp=False):
            #     self._draw_real((-self._l, -self._b))

    def _cache_onlyroot(self, depth):
        self._cache_create()
        with self._cacheRenderBuf.bind():
            self._draw_real((0,0))

    @profiler.function
    def _cache(self, depth=0):
        if not self.is_visible: return
        if self._w <= 0 or self._h <= 0: return

        if not self._dirty_renderbuf: return   # no need to cache
        # print('caching %s' % str(self))

        if   ui_settings.CACHE_METHOD == 0: pass # do not cache
        elif ui_settings.CACHE_METHOD == 1: self._cache_onlyroot(depth)
        elif ui_settings.CACHE_METHOD == 2: self._cache_hierarchical(depth)
        elif ui_settings.CACHE_METHOD == 3: self._cache_textleaves(depth)

        self._dirty_renderbuf = False

    @profiler.function
    def _draw(self, offset=(0,0)):
        if not self.is_visible: return
        if self._w <= 0 or self._h <= 0: return
        # if self._draw_dirty_style > 1: print(self, self._draw_dirty_style)
        ox,oy = offset
        if not gpustate.ScissorStack.is_box_visible(self._l+ox, self._t+oy, self._w, self._h): return
        # print('drawing %s' % str(self))
        self._draw_cache(offset)
        self._draw_dirty_style = 0

    def draw(self):
        gpustate.blend('ALPHA_PREMULT', only='function')
        self._setup_ltwh()
        self._cache()
        self._draw()

    def _draw_vscroll(self, depth=0):
        if not self.is_visible: return
        if not gpustate.ScissorStack.is_box_visible(self._l, self._t, self._w, self._h): return
        if self._w <= 0 or self._h <= 0: return
        vscroll = max(0, self._dynamic_full_size.height - self._h)
        if vscroll < 1: return
        with gpustate.ScissorStack.wrap(self._l, self._t, self._w, self._h, msg=str(self)):
            with profiler.code('drawing scrollbar'):
                gpustate.blend('ALPHA_PREMULT', only='enable')
                w = 3
                h = self._h - (mt+bw+pt) - (mb+bw+pb) - 6
                px = self._l + self._w - (mr+bw+pr) - w/2 - 5
                py0 = self._t - (mt+bw+pt) - 3
                py1 = py0 - (h-1)
                sh = h * self._h / self._dynamic_full_size.height
                sy0 = py0 - (h-sh) * (self._scroll_offset.y / vscroll)
                sy1 = sy0 - sh
                if py0>sy0: Globals.drawing.draw2D_line(Point2D((px,py0)), Point2D((px,sy0+1)), Color((0,0,0,0.2)), width=w)
                if sy1>py1: Globals.drawing.draw2D_line(Point2D((px,sy1-1)), Point2D((px,py1)), Color((0,0,0,0.2)), width=w)
                Globals.drawing.draw2D_line(Point2D((px,sy0)), Point2D((px,sy1)), Color((1,1,1,0.2)), width=w)
        if self._innerText is None:
            for child in self._children_all_sorted:
                child._draw_vscroll(depth+1)
    def draw_vscroll(self, *args, **kwargs): return self._draw_vscroll(*args, **kwargs)

