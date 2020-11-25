'''
Copyright (C) 2020 CG Cookie
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

import bpy
import blf
import bgl

from .debug import dprint
from .blender import get_preferences
from .profiler import profiler

# https://docs.blender.org/api/current/blf.html

class FontManager:
    _cache = {0:0}
    _last_fontid = 0
    _prefs = get_preferences()

    @staticmethod
    @property
    def last_fontid(): return FontManager._last_fontid

    @staticmethod
    def get_dpi():
        ui_scale = FontManager._prefs.view.ui_scale
        pixel_size = FontManager._prefs.system.pixel_size
        dpi = 72 # FontManager._prefs.system.dpi
        return int(dpi * ui_scale * pixel_size)

    @staticmethod
    def load(val, load_callback=None):
        if val is None:
            fontid = FontManager._last_fontid
        else:
            if val not in FontManager._cache:
                # note: loading the same file multiple times is not a problem.
                #       blender is smart enough to cache
                fontid = blf.load(val)
                print(f'Addon Common: Loaded font "{val}" as id {fontid}')
                FontManager._cache[val] = fontid
                FontManager._cache[fontid] = fontid
                if load_callback: load_callback(fontid)
            fontid = FontManager._cache[val]
        FontManager._last_fontid = fontid
        return fontid

    @staticmethod
    def unload_fontids():
        for name,fontid in FontManager._cache.items():
            print('Unloading font "%s" as id %d' % (name, fontid))
            blf.unload(name)
        FontManager._cache = {}
        FontManager._last_fontid = 0

    @staticmethod
    def unload(filename):
        assert filename in FontManager._cache
        fontid = FontManager._cache[filename]
        dprint('Unloading font "%s" as id %d' % (filename, fontid))
        blf.unload(filename)
        del FontManager._cache[filename]
        if fontid == FontManager._last_fontid:
            FontManager._last_fontid = 0

    @staticmethod
    def aspect(aspect, fontid=None):
        return blf.aspect(FontManager.load(fontid), aspect)

    @staticmethod
    def blur(radius, fontid=None):
        return blf.blur(FontManager.load(fontid), radius)

    @staticmethod
    def clipping(xymin, xymax, fontid=None):
        return blf.clipping(FontManager.load(fontid), *xymin, *xymax)

    @staticmethod
    def color(color, fontid=None):
        blf.color(FontManager.load(fontid), *color)

    @staticmethod
    def dimensions(text, fontid=None):
        return blf.dimensions(FontManager.load(fontid), text)

    @staticmethod
    def disable(option, fontid=None):
        return blf.disable(FontManager.load(fontid), option)

    @staticmethod
    def disable_rotation(fontid=None):
        return blf.disable(FontManager.load(fontid), blf.ROTATION)

    @staticmethod
    def disable_clipping(fontid=None):
        return blf.disable(FontManager.load(fontid), blf.CLIPPING)

    @staticmethod
    def disable_shadow(fontid=None):
        return blf.disable(FontManager.load(fontid), blf.SHADOW)

    @staticmethod
    def disable_kerning_default(fontid=None):
        # note: not a listed option in docs for `blf.disable`, but see `blf.word_wrap`
        return blf.disable(FontManager.load(fontid), blf.KERNING_DEFAULT)

    @staticmethod
    def disable_word_wrap(fontid=None):
        return blf.disable(FontManager.load(fontid), blf.WORD_WRAP)

    @staticmethod
    def draw(text, xyz=None, fontsize=None, dpi=None, fontid=None):
        fontid = FontManager.load(fontid)
        if xyz: blf.position(fontid, *xyz)
        if fontsize: FontManager.size(fontsize, dpi=dpi, fontid=fontid)
        return blf.draw(fontid, text)

    _pre_blend = bgl.Buffer(bgl.GL_BYTE, 1)
    _pre_src_rgb  = bgl.Buffer(bgl.GL_INT, 1)
    _pre_dst_rgb  = bgl.Buffer(bgl.GL_INT, 1)
    _pre_src_a  = bgl.Buffer(bgl.GL_INT, 1)
    _pre_dst_a  = bgl.Buffer(bgl.GL_INT, 1)
    @staticmethod
    def draw_simple(text, xyz):
        fontid = FontManager._last_fontid
        blf.position(fontid, *xyz)

        # blf.draw overwrites blend settings!  store so we can restore
        bgl.glGetBooleanv(bgl.GL_BLEND_SRC_RGB, FontManager._pre_src_rgb)
        bgl.glGetIntegerv(bgl.GL_BLEND_DST_RGB, FontManager._pre_dst_rgb)
        bgl.glGetBooleanv(bgl.GL_BLEND_SRC_ALPHA, FontManager._pre_src_a)
        bgl.glGetIntegerv(bgl.GL_BLEND_DST_ALPHA, FontManager._pre_dst_a)
        bgl.glGetIntegerv(bgl.GL_BLEND, FontManager._pre_blend)

        ret = blf.draw(fontid, text)

        # restore blend settings!
        if FontManager._pre_blend[0]: bgl.glEnable(bgl.GL_BLEND)
        else: bgl.glDisable(bgl.GL_BLEND)
        bgl.glBlendFunc(FontManager._pre_src_rgb[0], FontManager._pre_dst_rgb[0])
        #bgl.glBlendEquationSeparate(FontManager._pre_src_rgb[0], FontManager._pre_dst_rgb[0], FontManager._pre_src_a[0], FontManager._pre_dst_a[0])

        return ret

    @staticmethod
    def enable(option, fontid=None):
        return blf.enable(FontManager.load(fontid), option)

    @staticmethod
    def enable_rotation(fontid=None):
        return blf.enable(FontManager.load(fontid), blf.ROTATION)

    @staticmethod
    def enable_clipping(fontid=None):
        return blf.enable(FontManager.load(fontid), blf.CLIPPING)

    @staticmethod
    def enable_shadow(fontid=None):
        return blf.enable(FontManager.load(fontid), blf.SHADOW)

    @staticmethod
    def enable_kerning_default(fontid=None):
        return blf.enable(FontManager.load(fontid), blf.KERNING_DEFAULT)

    @staticmethod
    def enable_word_wrap(fontid=None):
        # note: not a listed option in docs for `blf.enable`, but see `blf.word_wrap`
        return blf.enable(FontManager.load(fontid), blf.WORD_WRAP)

    @staticmethod
    def position(xyz, fontid=None):
        return blf.position(FontManager.load(fontid), *xyz)

    @staticmethod
    def rotation(angle, fontid=None):
        return blf.rotation(FontManager.load(fontid), angle)

    @staticmethod
    def shadow(level, rgba, fontid=None):
        return blf.shadow(FontManager.load(fontid), level, *rgba)

    @staticmethod
    def shadow_offset(xy, fontid=None):
        return blf.shadow_offset(FontManager.load(fontid), *xy)

    @staticmethod
    def size(size, dpi=None, fontid=None):
        if not dpi: dpi = FontManager.get_dpi()
        return blf.size(FontManager.load(fontid), size, dpi)

    @staticmethod
    def word_wrap(wrap_width, fontid=None):
        return blf.word_wrap(FontManager.load(fontid), wrap_width)


