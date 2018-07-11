'''
Copyright (C) 2017 CG Cookie
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
import bpy
import bpy.utils.previews

icon_collections = {}
icons_loaded = False

icon_data = {
    'rf_contours_icon':     'contours_32.png',
    'rf_polystrips_icon':   'polystrips_32.png',
    'rf_polypen_icon':      'polypen_32.png',
    'rf_tweak_icon':        'tweak_32.png',
    'rf_loops_icon':        'loops_32.png',
    'rf_loopcut_icon':      'loop_cut_32.png',
    'rf_loopdelete_icon':   'loop_delete_32.png',
    'rf_loopslide_icon':    'loop_slide_32.png',
    'rf_relax_icon':        'relax_32.png',
    'rf_recover_icon':      'recover_32.png',
    'rf_patches_icon':      'patches_32.png',
}

def load_icons():
    global icon_data, icons_loaded, icon_collections

    if not icons_loaded:
        rf_icons = bpy.utils.previews.new()
        icons_dir = os.path.join(os.path.dirname(__file__), "icons")
        for name, path in icon_data.items():
            rf_icons.load(name, os.path.join(icons_dir, path), 'IMAGE')
        icon_collections["main"] = rf_icons
        icons_loaded = True

    return icon_collections["main"]

def clear_icons():
    global icons_loaded, icon_collections
    for icon in icon_collections.values():
        bpy.utils.previews.remove(icon)
    icon_collections.clear()
    icons_loaded = False