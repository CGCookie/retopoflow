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

import blf
from bpy.types import Preferences

from typing import ClassVar
from collections.abc import Callable, Sequence

from . import gpustate
from .blender_preferences import get_preferences
from .debug import dprint

# https://docs.blender.org/api/current/blf.html

class FontManager:
    _cache : ClassVar[dict[str|int, int]] = {0:0}
    _last_fontid : ClassVar[int] = 0
    _prefs : ClassVar[Preferences] = get_preferences()

    @staticmethod
    def get_dpi() -> int:
        ui_scale = FontManager._prefs.view.ui_scale
        pixel_size = FontManager._prefs.system.pixel_size
        dpi = 72 # FontManager._prefs.system.dpi
        return int(dpi * ui_scale * pixel_size)

    @staticmethod
    def load(val : str | int | None, load_callback : Callable[[int], None] | None = None) -> int:
        if val is None:
            fontid = FontManager._last_fontid
        else:
            if val not in FontManager._cache:
                # note: loading the same file multiple times is not a problem.
                #       blender is smart enough to cache
                fontid = blf.load(val)
                print(f'Addon Common: Loaded font id={fontid}: {val}')
                FontManager._cache[val] = fontid
                FontManager._cache[fontid] = fontid
                if load_callback: load_callback(fontid)
            fontid = FontManager._cache[val]
        FontManager._last_fontid = fontid
        return fontid

    @staticmethod
    def unload_fontids():
        for (name, fontid) in FontManager._cache.items():
            if isinstance(name, int):
                continue
            print('Unloading font "%s" as id %d' % (name, fontid))
            blf.unload(name)
        FontManager._cache = {}
        FontManager._last_fontid = 0

    @staticmethod
    def unload(filename : str):
        assert filename in FontManager._cache
        fontid = FontManager._cache[filename]
        dprint('Unloading font "%s" as id %d' % (filename, fontid))
        blf.unload(filename)
        del FontManager._cache[filename]
        del FontManager._cache[fontid]
        if fontid == FontManager._last_fontid:
            FontManager._last_fontid = 0

    @staticmethod
    def aspect(aspect : float, fontid : str | int | None = None):
        blf.aspect(FontManager.load(fontid), aspect)

    @staticmethod
    def clipping(xymin : Sequence[float], xymax : Sequence[float], fontid : str | int | None = None):
        blf.clipping(FontManager.load(fontid), *xymin, *xymax)

    @staticmethod
    def color(color : Sequence[float], fontid : str | int | None = None):
        blf.color(FontManager.load(fontid), *color)

    @staticmethod
    def dimensions(text : str, fontid : str | int | None = None) -> tuple[float, float]:
        return blf.dimensions(FontManager.load(fontid), text)

    @staticmethod
    def disable(option : int, fontid : str | int | None = None):
        assert option in {blf.ROTATION, blf.CLIPPING, blf.SHADOW, blf.MONOCHROME, blf.WORD_WRAP}, f'Expected {option=} to be blf.ROTATION, blf.CLIPPING, blf.SHADOW, blf.MONOCHROME, blf.WORD_WRAP'
        blf.disable(FontManager.load(fontid), option)

    @staticmethod
    def disable_rotation(fontid : str | int | None = None):
        blf.disable(FontManager.load(fontid), blf.ROTATION)

    @staticmethod
    def disable_clipping(fontid : str | int | None = None):
        blf.disable(FontManager.load(fontid), blf.CLIPPING)

    @staticmethod
    def disable_shadow(fontid : str | int | None = None):
        blf.disable(FontManager.load(fontid), blf.SHADOW)

    @staticmethod
    def disable_word_wrap(fontid : str | int | None = None):
        blf.disable(FontManager.load(fontid), blf.WORD_WRAP)

    @staticmethod
    def draw(text : str, xyz : Sequence[float] | None = None, fontsize : float | None = None, fontid : int | str | None = None):
        fontid = FontManager.load(fontid)
        if xyz: blf.position(fontid, *xyz)
        if fontsize: FontManager.size(fontsize, fontid=fontid)
        blf.draw(fontid, text)

    @staticmethod
    def draw_simple(text : str, xyz : Sequence[float]):
        fontid = FontManager._last_fontid
        blf.position(fontid, *xyz)
        blend_eqn = gpustate.get_blend()   # storing blend settings, because blf.draw used to overwrite them (not sure if still applies)
        blf.draw(fontid, text)
        gpustate.blend(blend_eqn)      # restore blend settings

    @staticmethod
    def enable(option : int, fontid : str | int | None = None):
        assert option in {blf.ROTATION, blf.CLIPPING, blf.SHADOW, blf.MONOCHROME, blf.WORD_WRAP}, f'Expected {option=} to be blf.ROTATION, blf.CLIPPING, blf.SHADOW, blf.MONOCHROME, blf.WORD_WRAP'
        blf.enable(FontManager.load(fontid), option)

    @staticmethod
    def enable_rotation(fontid : str | int | None = None):
        blf.enable(FontManager.load(fontid), blf.ROTATION)

    @staticmethod
    def enable_clipping(fontid : str | int | None = None):
        blf.enable(FontManager.load(fontid), blf.CLIPPING)

    @staticmethod
    def enable_shadow(fontid : str | int | None = None):
        blf.enable(FontManager.load(fontid), blf.SHADOW)

    @staticmethod
    def enable_word_wrap(fontid : str | int | None = None):
        blf.enable(FontManager.load(fontid), blf.WORD_WRAP)

    @staticmethod
    def position(xyz : Sequence[float], fontid : str | int | None = None):
        blf.position(FontManager.load(fontid), *xyz)

    @staticmethod
    def rotation(angle : float, fontid : str | int | None = None):
        blf.rotation(FontManager.load(fontid), angle)

    @staticmethod
    def shadow(level : int, rgba : Sequence[float], fontid : str | int | None = None):
        assert level in {0, 3, 5, 6}, f'Expected {level=} to be 0, 3, 5, 6'
        blf.shadow(FontManager.load(fontid), level, *rgba)

    @staticmethod
    def shadow_offset(xy : Sequence[int], fontid : str | int | None = None):
        blf.shadow_offset(FontManager.load(fontid), *xy)

    @staticmethod
    def size(size : float, fontid : str | int | None = None):
        blf.size(FontManager.load(fontid), size)

    @staticmethod
    def word_wrap(wrap_width : int, fontid : str | int | None = None):
        blf.word_wrap(FontManager.load(fontid), wrap_width)
