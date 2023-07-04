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

import os

from .blender import tag_redraw_all, get_path_from_addon_common, get_path_from_addon_root
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .fontmanager import FontManager


fontmap = {
    'serif': {
        'normal': {
            'normal': 'DroidSerif-Regular.ttf',
            'bold':   'DroidSerif-Bold.ttf',
        },
        'italic': {
            'normal': 'DroidSerif-Italic.ttf',
            'bold':   'DroidSerif-BoldItalic.ttf',
        },
    },
    'sans-serif': {
        'normal': {
            'normal': 'DroidSans-Blender.ttf',
            'bold':   'OpenSans-Bold.ttf',
        },
        'italic': {
            'normal': 'OpenSans-Italic.ttf',
            'bold':   'OpenSans-BoldItalic.ttf',
        },
    },
    'monospace': {
        'normal': {
            'normal': 'DejaVuSansMono.ttf',
            'bold':   'DejaVuSansMono.ttf',
        },
        'italic': {
            'normal': 'DejaVuSansMono.ttf',
            'bold':   'DejaVuSansMono.ttf',
        },
    },
}


@add_cache('_cache', {})
@add_cache('_paths', [
    get_path_from_addon_common('common', 'fonts'),
    get_path_from_addon_common('common'),
    get_path_from_addon_root('fonts'),
])
def get_font_path(fn, ext=None):
    cache = get_font_path._cache
    if ext: fn = f'{fn}.{ext}'
    if fn not in cache:
        cache[fn] = None
        for path in get_font_path._paths:
            p = os.path.join(path, fn)
            if os.path.exists(p):
                cache[fn] = p
                break
    return get_font_path._cache[fn]

def setup_font(fontid):
    FontManager.aspect(1, fontid)

def get_font(fontfamily, fontstyle=None, fontweight=None):
    if not fontstyle:  fontstyle = 'normal'
    if not fontweight: fontweight = 'normal'
    # translate fontfamily, fontstyle, fontweight into a .ttf
    if fontfamily in fontmap: fontfamily = fontmap[fontfamily][fontstyle][fontweight]
    path = get_font_path(fontfamily)
    assert path, f'could not find font "{fontfamily}"'
    fontid = FontManager.load(path, setup_font)
    return fontid

