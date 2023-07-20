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

import gpu

from .blender import tag_redraw_all, get_path_from_addon_common, get_path_from_addon_root
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .utils import iter_head, any_args, join

from ..ext import png
from ..ext.apng import APNG


def get_image_path(fn, ext=None, subfolders=None):
    '''
    If subfolders is not given, this function will look in folders shown below
        <addon_root>
            addon_common/
                common/
                    ui_core.py      <- this file
                    images/         <- will look here
                    <...>
                <...>
            icons/                  <- and here (if exists)
                <...>
            images/                 <- and here (if exists)
                <...>
            help/                   <- and here (if exists)
                <...>
            <...>
    returns first path where fn is found
    order of search: <addon_root>/icons, <addon_root>/images, <addon_root>/help, <addon_root>/addon_common/common/images
    '''
    assert not subfolders, f'Subfolders arg for get_image_path not implemented, yet'
    if ext: fn = f'{fn}.{ext}'
    return iter_head(
        [
            path
            for path in [
                get_path_from_addon_root('icons', fn),
                get_path_from_addon_root('images', fn),
                get_path_from_addon_root('help', fn),
                get_path_from_addon_root('help', 'images', fn),
                get_path_from_addon_common('common', 'images', fn),
            ]
            if os.path.exists(path)
        ],
        default=None,
    )

def load_image_png(path):
    # note: assuming 4 channels (rgba) per pixel!
    width, height, data, m = png.Reader(path).asRGBA()
    img = [[row[i:i+4] for i in range(0, width*4, 4)] for row in data]
    return img

def load_image_apng(path):
    im_apng = APNG.open(path)
    print('load_image_apng', path, im_apng, im_apng.frames, im_apng.num_plays)
    im,control = im_apng.frames[0]
    w,h = control.width,control.height
    img = [[r[i:i+4] for i in range(0,w*4,4)] for r in d]
    return img

@add_cache('_cache', {})
def load_image(fn):
    # important: assuming all images have distinct names!
    if fn not in load_image._cache:
        # have not seen this image before
        path = get_image_path(fn)
        _,ext = os.path.splitext(fn)
        # print(f'UI: Loading image "{fn}" (path={path})')
        if   ext == '.png':  img = load_image_png(path)
        elif ext == '.apng': img = load_image_apng(path)
        else: assert False, f'load_image: unhandled type ({ext}) for {fn}'
        load_image._cache[fn] = img
    return load_image._cache[fn]

@add_cache('_image', None)
def get_unfound_image():
    if not get_unfound_image._image:
        c0, c1 = [128,128,128,0], [128,128,128,128]
        w, h = 10, 10
        image = []
        for y in range(h):
            row = []
            for x in range(w):
                c = c0 if (x+y)%2 == 0 else c1
                row.append(c)
            image.append(row)
        get_unfound_image._image = image
    return get_unfound_image._image

@add_cache('_image', None)
def get_loading_image(fn):
    base, _ = os.path.splitext(fn)
    nfn = f'{base}.thumb.png'
    return load_image(nfn) if get_image_path(nfn) else get_unfound_image()

def is_image_cached(fn):
    return fn in load_image._cache

def has_thumbnail(fn):
    nfn = f'{os.path.splitext(fn)[0]}.thumb.png'
    return get_image_path(nfn) is not None

def set_image_cache(fn, img):
    if fn in load_image._cache: return
    load_image._cache[fn] = img

def preload_image(*fns):
    return [ (fn, load_image(fn)) for fn in fns ]

@add_cache('_cache', {})
def load_texture(fn_image, image=None):
    if fn_image not in load_texture._cache:
        if image is None: image = load_image(fn_image)
        # print(f'UI: Buffering texture "{fn_image}"')
        height,width,depth = len(image),len(image[0]),len(image[0][0])
        assert depth == 4, 'Expected texture %s to have 4 channels per pixel (RGBA), not %d' % (fn_image, depth)
        image = reversed(image) # flip image
        image_flat = [d for r in image for c in r for d in c]
        buffer = gpu.types.Buffer('FLOAT', (width * height * 4), [v / 255.0 for v in image_flat])
        gputexture = gpu.types.GPUTexture((width, height), format='RGBA16F', data=buffer)

        load_texture._cache[fn_image] = {
            'width':  width,
            'height': height,
            'depth':  depth,
            'texid':  None, #texid,
            'gputexture': gputexture,
        }
    return load_texture._cache[fn_image]

def async_load_image(fn_image, callback):
    img = load_image(fn_image)
    callback(img)

