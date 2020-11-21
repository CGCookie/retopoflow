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

import os
import re
import sys
import math
import time
import random
import traceback
import contextlib
from math import floor, ceil
from inspect import signature
from itertools import dropwhile
from concurrent.futures import ThreadPoolExecutor

import bpy
import bgl
import blf
import gpu

from .ui_proxy import UI_Proxy

from gpu.types import GPUOffScreen
from gpu_extras.presets import draw_texture_2d
from mathutils import Vector, Matrix

from .blender import tag_redraw_all
from .ui_styling import UI_Styling, ui_defaultstylings
from .ui_utilities import helper_wraptext, convert_token_to_cursor
from .drawing import ScissorStack, FrameBuffer
from .fsm import FSM

from .useractions import ActionHandler, kmi_to_keycode

from .boundvar import BoundVar
from .debug import debugger, dprint, tprint
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .fontmanager import FontManager
from .globals import Globals
from .hasher import Hasher
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .profiler import profiler, time_it
from .shaders import Shader
from .utils import iter_head, any_args

from ..ext import png
from ..ext.apng import APNG


'''
# NOTES

dirty_styling

- clears all style caching
- always calls dirty_styling on children <== TODO!


dirty_flow

- ignored if _dirtying_flow is True already
- sets _dirtying_flow to True
- possibly calls parent's dirty_flow
- possibly calls children's dirty_flow
- _layout() returns early if _dirtying_flow is False


'''


DEBUG_COLOR_CLEAN = False
DEBUG_PROPERTY = 'style'     # selector, style, content, size, layout, blocks
DEBUG_COLOR    = 1              # 0:time since change, 1:time of change

DEBUG_LIST      = False

CACHE_METHOD = 2                # 0:none, 1:only root, 2:hierarchical, 3:text leaves


class UI_Element_Defaults:
    font_family = 'sans-serif'
    font_style  = 'normal'
    font_weight = 'normal'
    font_size   = NumberUnit(12, 'pt')
    font_color  = Color((0, 0, 0, 1))
    whitespace  = 'normal'


@add_cache('_cache', {})
@add_cache('_paths', [
    os.path.abspath(os.path.curdir),
    os.path.join(os.path.abspath(os.path.curdir), 'fonts'),
    os.path.join(os.path.dirname(__file__), 'fonts'),
])
def get_font_path(fn, ext=None):
    cache = get_font_path._cache
    if ext: fn = '%s.%s' % (fn,ext)
    if fn not in cache:
        cache[fn] = None
        for path in get_font_path._paths:
            p = os.path.join(path, fn)
            if os.path.exists(p):
                cache[fn] = p
                break
    return get_font_path._cache[fn]

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
def setup_font(fontid):
    FontManager.aspect(1, fontid)
    FontManager.enable_kerning_default(fontid)

@profiler.function
def get_font(fontfamily, fontstyle=None, fontweight=None):
    if fontfamily in fontmap:
        # translate fontfamily, fontstyle, fontweight into a .ttf
        fontfamily = fontmap[fontfamily][fontstyle or 'normal'][fontweight or 'normal']
    path = get_font_path(fontfamily)
    assert path, f'could not find font "{fontfamily}"'
    fontid = FontManager.load(path, setup_font)
    return fontid


def get_image_path(fn, ext=None, subfolders=None):
    '''
    If subfolders is not given, this function will look in folders shown below
        <addon_root>
            addon_common/
                common/
                    ui_core.py      <- this file
                    <...>
                <...>
            icons/                  <- will look here (if exists)
                <...>
            images/                 <- will look here (if exists)
                <...>
            help/                   <- will look here (if exists)
                <...>
            <...>
    '''
    if subfolders is None:
        subfolders = ['icons', 'images', 'help']
    if ext:
        fn = f'{fn}.{ext}'
    path_here = os.path.dirname(__file__)
    path_root = os.path.join(path_here, '..', '..')
    paths = [os.path.join(path_root, p, fn) for p in subfolders]
    paths += [os.path.join(path_here, 'images', fn)]
    paths = [p for p in paths if os.path.exists(p)]
    return iter_head(paths, None)

math_isinf = math.isinf
math_floor = math.floor
math_ceil = math.ceil
def floor_if_finite(v):
    return v if v is None or math_isinf(v) else math_floor(v)
def ceil_if_finite(v):
    return v if v is None or math_isinf(v) else math_ceil(v)


@contextlib.contextmanager
def temp_bglbuffer(*args):
    buf = bgl.Buffer(*args)
    yield buf
    del buf


def load_image_png(path):
    # note: assuming 4 channels (rgba) per pixel!
    w,h,d,m = png.Reader(path).asRGBA()
    img = [[r[i:i+4] for i in range(0,w*4,4)] for r in d]
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
        dprint(f'Loading image "{fn}" (path={path})')
        if   ext == '.png':  img = load_image_png(path)
        elif ext == '.apng': img = load_image_apng(path)
        load_image._cache[fn] = img
    return load_image._cache[fn]

def set_image_cache(fn, img):
    if fn in load_image._cache: return
    load_image._cache[fn] = img

def preload_image(*fns):
    return [ (fn, load_image(fn)) for fn in fns ]

@add_cache('_cache', {})
def load_texture(fn_image, mag_filter=bgl.GL_NEAREST, min_filter=bgl.GL_LINEAR):
    if fn_image not in load_texture._cache:
        image = load_image(fn_image)
        dprint('Buffering texture "%s"' % fn_image)
        height,width,depth = len(image),len(image[0]),len(image[0][0])
        assert depth == 4, 'Expected texture %s to have 4 channels per pixel (RGBA), not %d' % (fn_image, depth)
        image = reversed(image) # flip image
        image_flat = [d for r in image for c in r for d in c]
        with temp_bglbuffer(bgl.GL_INT, [1]) as buf:
            bgl.glGenTextures(1, buf)
            texid = buf[0]
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, texid)
        bgl.glTexParameterf(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MAG_FILTER, mag_filter)
        bgl.glTexParameterf(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_MIN_FILTER, min_filter)
        with temp_bglbuffer(bgl.GL_BYTE, [len(image_flat)], image_flat) as texbuffer:
            bgl.glTexImage2D(bgl.GL_TEXTURE_2D, 0, bgl.GL_RGBA, width, height, 0, bgl.GL_RGBA, bgl.GL_UNSIGNED_BYTE, texbuffer)
        bgl.glBindTexture(bgl.GL_TEXTURE_2D, 0)
        load_texture._cache[fn_image] = {
            'width': width,
            'height': height,
            'depth': depth,
            'texid': texid,
        }
    return load_texture._cache[fn_image]

class UI_Draw:
    _initialized = False
    _stylesheet = None

    @blender_version_wrapper('<=', '2.79')
    def init_draw(self):
        # TODO: test this implementation!
        assert False, 'function implementation not tested yet!!!'
        # UI_Draw._shader = Shader.load_from_file('ui', 'uielement.glsl', checkErrors=True)
        # sizeOfFloat, sizeOfInt = 4, 4
        # pos = [(0,0),(1,0),(1,1),  (0,0),(1,1),(0,1)]
        # count = len(pos)
        # buf_pos = bgl.Buffer(bgl.GL_FLOAT, [count, 2], pos)
        # vbos = bgl.Buffer(bgl.GL_INT, 1)
        # bgl.glGenBuffers(1, vbos)
        # vbo_pos = vbos[0]
        # bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, vbo_pos)
        # bgl.glBufferData(bgl.GL_ARRAY_BUFFER, count * 2 * sizeOfFloat, buf_pos, bgl.GL_STATIC_DRAW)
        # bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, 0)
        # en = UI_Draw._shader.enable
        # di = UI_Draw._shader.disable
        # eva = UI_Draw._shader.vertexAttribPointer
        # dva = UI_Draw._shader.disableVertexAttribArray
        # a = UI_Draw._shader.assign
        # def draw(left, top, width, height, style):
        #     nonlocal vbo_pos, count, en, di, eva, dva, a
        #     en()
        #     a('left',   left)
        #     a('top',    top)
        #     a('right',  left+width-1)
        #     a('bottom', top-height+1)
        #     a('margin_left',   style.get('margin-left', 0))
        #     a('margin_right',  style.get('margin-right', 0))
        #     a('margin_top',    style.get('margin-top', 0))
        #     a('margin_bottom', style.get('margin-bottom', 0))
        #     a('border_width',        style.get('border-width', 0))
        #     a('border_radius',       style.get('border-radius', 0))
        #     a('border_left_color',   style.get('border-left-color', (0,0,0,1)))
        #     a('border_right_color',  style.get('border-right-color', (0,0,0,1)))
        #     a('border_top_color',    style.get('border-top-color', (0,0,0,1)))
        #     a('border_bottom_color', style.get('border-bottom-color', (0,0,0,1)))
        #     a('background_color', style.get('background-color', (0,0,0,1)))
        #     eva(vbo_pos, 'pos', 2, bgl.GL_FLOAT)
        #     bgl.glDrawArrays(bgl.GL_TRIANGLES, 0, count)
        #     dva('pos')
        #     di()
        # UI_Draw._draw = draw

    @blender_version_wrapper('>=', '2.80')
    def init_draw(self):
        import gpu
        from gpu_extras.batch import batch_for_shader

        vertex_positions = [(0,0),(1,0),(1,1),  (1,1),(0,1),(0,0)]
        vertex_shader, fragment_shader = Shader.parse_file('ui_element.glsl', includeVersion=False)
        shader = gpu.types.GPUShader(vertex_shader, fragment_shader)
        batch = batch_for_shader(shader, 'TRIS', {"pos": vertex_positions})
        # get_pixel_matrix = Globals.drawing.get_pixel_matrix
        get_MVP_matrix = lambda: gpu.matrix.get_projection_matrix() @ gpu.matrix.get_model_view_matrix()
        def_color = (0,0,0,0)

        def draw(left, top, width, height, dpi_mult, style, texture_id, texture_fit, background_override, atex=bgl.GL_TEXTURE0):
            nonlocal shader, batch, def_color, get_MVP_matrix
            def get_v(style_key, def_val):
                v = style.get(style_key, def_val)
                if type(v) is NumberUnit: v = v.val() * dpi_mult
                return v
            shader.bind()
            # uMVPMatrix needs to be set every draw call, because it could be different
            # when rendering to FrameBuffers with their own l,b,w,h
            shader.uniform_float("uMVPMatrix",          get_MVP_matrix())
            shader.uniform_float('left',                left)
            shader.uniform_float('top',                 top)
            shader.uniform_float('right',               left + (width - 1))
            shader.uniform_float('bottom',              top - (height - 1))
            shader.uniform_float('width',               width)
            shader.uniform_float('height',              height)
            shader.uniform_float('margin_left',         get_v('margin-left', 0))
            shader.uniform_float('margin_right',        get_v('margin-right', 0))
            shader.uniform_float('margin_top',          get_v('margin-top', 0))
            shader.uniform_float('margin_bottom',       get_v('margin-bottom', 0))
            shader.uniform_float('padding_left',        get_v('padding-left', 0))
            shader.uniform_float('padding_right',       get_v('padding-right', 0))
            shader.uniform_float('padding_top',         get_v('padding-top', 0))
            shader.uniform_float('padding_bottom',      get_v('padding-bottom', 0))
            shader.uniform_float('border_width',        get_v('border-width', 0))
            shader.uniform_float('border_radius',       get_v('border-radius', 0))
            shader.uniform_float('border_left_color',   get_v('border-left-color', def_color))
            shader.uniform_float('border_right_color',  get_v('border-right-color', def_color))
            shader.uniform_float('border_top_color',    get_v('border-top-color', def_color))
            shader.uniform_float('border_bottom_color', get_v('border-bottom-color', def_color))
            if background_override:
                shader.uniform_float('background_color',    background_override)
            else:
                shader.uniform_float('background_color',    get_v('background-color', def_color))
            shader.uniform_int('image_fit', texture_fit)
            if texture_id == -1:
                shader.uniform_int('using_image', 0)
            else:
                bgl.glActiveTexture(atex)
                bgl.glBindTexture(bgl.GL_TEXTURE_2D, texture_id)
                shader.uniform_int('using_image', 1)
                shader.uniform_int('image', atex - bgl.GL_TEXTURE0)
            batch.draw(shader)

        UI_Draw._draw = draw

    def __init__(self):
        if not UI_Draw._initialized:
            self.init_draw()
            UI_Draw._initialized = True

    @staticmethod
    def load_stylesheet(path):
        UI_Draw._stylesheet = UI_Styling.from_file(path)
    @property
    def stylesheet(self):
        return self._stylesheet

    def update(self):
        ''' only need to call once every redraw '''
        pass

    texture_fit_map = {
        'fill':       0, # default.  stretch/squash to fill entire container
        'contain':    1, # scaled to maintain aspect ratio, fit within container
        'cover':      2, # scaled to maintain aspect ratio, fill entire container
        'scale-down': 3, # same as none or contain, whichever is smaller
        'none':       4, # not resized
    }
    def draw(self, left, top, width, height, dpi_mult, style, texture_id=-1, texture_fit='fill', background_override=None):
        texture_fit = self.texture_fit_map.get(texture_fit, 0)
        #if texture_id != -1: print('texture_fit', texture_fit)
        UI_Draw._draw(left, top, width, height, dpi_mult, style, texture_id, texture_fit, background_override)


ui_draw = Globals.set(UI_Draw())



'''
UI_Document manages UI_Body

example hierarchy of UI

- UI_Body: (singleton!)
    - UI_Dialog: tooltips
    - UI_Dialog: menu
        - help
        - about
        - exit
    - UI_Dialog: tools
        - UI_Button: toolA
        - UI_Button: toolB
        - UI_Button: toolC
    - UI_Dialog: options
        - option1
        - option2
        - option3


clean call order

- compute_style (only if style is dirty)
    - call compute_style on all children
    - dirtied by change in style, ID, class, pseudoclass, parent, or ID/class/pseudoclass of an ancestor
    - cleaning style dirties size
- compute_preferred_size (only if size or content are dirty)
    - determines min, max, preferred size for element (override in subclass)
    - for containers that resize based on children, whether wrapped (inline), list (block), or table, ...
        - 

'''


class UI_Element_Utils:
    executor = ThreadPoolExecutor()

    @staticmethod
    def defer_dirty_wrapper(cause, properties=None, parent=True, children=False):
        ''' prevents dirty propagation until the wrapped fn has finished '''
        def wrapper(fn):
            def wrapped(self, *args, **kwargs):
                self._defer_dirty = True
                ret = fn(self, *args, **kwargs)
                self._defer_dirty = False
                self.dirty(cause=f'dirtying deferred dirtied properties now: {cause}', properties=properties, parent=parent, children=children)
                return ret
            return wrapped
        return wrapper

    @contextlib.contextmanager
    def defer_dirty(self, cause, properties=None, parent=True, children=False):
        ''' prevents dirty propagation until the end of with has finished '''
        self._defer_dirty = True
        self.defer_dirty_propagation = True
        yield
        self.defer_dirty_propagation = False
        self._defer_dirty = False
        self.dirty(cause=f'dirtying deferred dirtied properties now: {cause}', properties=properties, parent=parent, children=children)

    _option_callbacks = {}
    @staticmethod
    def add_option_callback(option):
        def wrapper(fn):
            def wrapped(self, *args, **kwargs):
                ret = fn(self, *args, **kwargs)
                return ret
            UI_Element_Utils._option_callbacks[option] = wrapped
            return wrapped
        return wrapper

    def call_option_callback(self, option, default, *args, **kwargs):
        option = option if option not in UI_Element_Utils._option_callbacks else default
        UI_Element_Utils._option_callbacks[option](self, *args, **kwargs)

    _cleaning_graph = {}
    _cleaning_graph_roots = set()
    _cleaning_graph_nodes = set()
    @staticmethod
    def add_cleaning_callback(label, labels_dirtied=None):
        # NOTE: this function decorator does NOT call self.dirty!
        UI_Element_Utils._cleaning_graph_nodes.add(label)
        g = UI_Element_Utils._cleaning_graph
        labels_dirtied = list(labels_dirtied) if labels_dirtied else []
        for l in [label]+labels_dirtied: g.setdefault(l, {'fn':None, 'children':[], 'parents':[]})
        def wrapper(fn):
            g[label]['name'] = label
            g[label]['fn'] = fn
            g[label]['children'] = labels_dirtied
            for l in labels_dirtied: g[l]['parents'].append(label)

            # find roots of graph (any label that is not dirtied by another cleaning callback)
            UI_Element_Utils._cleaning_graph_roots = set(k for (k,v) in g.items() if not v['parents'])
            assert UI_Element_Utils._cleaning_graph_roots, 'cycle detected in cleaning callbacks'
            # TODO: also detect cycles such as: a->b->c->d->b->...
            #       done in call_cleaning_callbacks, but could be done here instead?

            return fn
        return wrapper


    #####################################################################
    # helper functions
    # these functions use self._computed_style, so these functions
    # MUST BE CALLED AFTER `compute_style()` METHOD IS CALLED!

    def _get_style_num(self, k, def_v=None, percent_of=None, scale=None):
        v = self._computed_styles.get(k, 'auto')
        if v == 'auto': v = def_v or 'auto'
        if v == 'auto': return 'auto'
        # v must be NumberUnit here!
        if v.unit == '%': scale = None
        v = v.val(base=(float(def_v) if percent_of is None else percent_of))
        v = float(v)
        if scale is not None: v *= scale
        return floor_if_finite(v)

    def _get_style_trbl(self, kb, scale=None):
        cache = self._style_trbl_cache
        key = f'{kb} {scale}'
        if key not in cache:
            t = self._get_style_num(f'{kb}-top',    def_v=NumberUnit.zero, scale=scale)
            r = self._get_style_num(f'{kb}-right',  def_v=NumberUnit.zero, scale=scale)
            b = self._get_style_num(f'{kb}-bottom', def_v=NumberUnit.zero, scale=scale)
            l = self._get_style_num(f'{kb}-left',   def_v=NumberUnit.zero, scale=scale)
            cache[key] = (t, r, b, l)
        return cache[key]


# https://www.w3schools.com/jsref/obj_event.asp
# https://javascript.info/bubbling-and-capturing
class UI_Event:
    phases = [
        'none',
        'capturing',
        'at target',
        'bubbling',
    ]

    def __init__(self, target=None, mouse=None, button=None, key=None):
        self._eventPhase = 'none'
        self._cancelBubble = False
        self._cancelCapture = False
        self._target = target
        self._mouse = mouse
        self._button = button
        self._key = key
        self._defaultPrevented = False

    def stop_propagation(self):
        self.stop_bubbling()
        self.stop_capturing()
    def stop_bubbling(self):
        self._cancelBubble = True
    def stop_capturing(self):
        self._cancelCapture = True

    def prevent_default(self):
        self._defaultPrevented = True

    @property
    def event_phase(self): return self._eventPhase
    @event_phase.setter
    def event_phase(self, v):
        assert v in self.phases, "attempting to set event_phase to unknown value (%s)" % str(v)
        self._eventPhase = v

    @property
    def bubbling(self):
        return self._eventPhase == 'bubbling' and not self._cancelBubble
    @property
    def capturing(self):
        return self._eventPhase == 'capturing' and not self._cancelCapture
    @property
    def atTarget(self):
        return self._eventPhase == 'at target'

    @property
    def target(self): return self._target

    @property
    def mouse(self): return self._mouse

    @property
    def button(self): return self._button

    @property
    def key(self): return self._key

    @property
    def default_prevented(self): return self._defaultPrevented

    @property
    def eventPhase(self): return self._eventPhase


class UI_Element_Properties:
    @property
    def tagName(self):
        return self._tagName
    @tagName.setter
    def tagName(self, ntagName):
        errmsg = 'Tagname must contain only alpha and cannot be empty'
        assert type(ntagName) is str, errmsg
        ntagName = ntagName.lower()
        assert ntagName, errmsg
        assert len(set(ntagName) - set('abcdefghijklmnopqrstuvwxyz0123456789')) == 0, errmsg
        if self._tagName == ntagName: return
        self._tagName = ntagName
        self.dirty(cause='changing tagName can affect children styles', children=True)

    @property
    def innerText(self):
        return self._innerText
    @innerText.setter
    def innerText(self, nText):
        if self._innerText == nText: return
        self._innerText = nText
        # self.dirty(cause='changing innerText makes dirty', children=True)
        self.dirty_content(cause='changing innerText')
        self.dirty_size(cause='changing innerText')
        #self.dirty('changing innerText changes content', 'content', children=True)
        #self.dirty('changing innerText changes size', 'size', children=True)
        self._new_content = True
        self.dirty_flow()

    @property
    def innerTextAsIs(self):
        return self._innerTextAsIs
    @innerTextAsIs.setter
    def innerTextAsIs(self, v):
        v = str(v) if v is not None else None
        if self._innerTextAsIs == v: return
        self._innerTextAsIs = v
        # self.dirty(cause='changing innerTextAsIs makes dirty', properties={'content', 'size'})
        self.dirty_content(cause='changing innerText')
        self.dirty_size(cause='changing innerText')
        self.dirty_flow()

    @property
    def parent(self):
        return self._parent
    def get_pathToRoot(self):
        l=[self]
        while l[-1]._parent: l.append(l[-1]._parent)
        return l
        l,cur = [],self
        while cur: l,cur = l+[cur],cur._parent
        return l
    def get_pathFromRoot(self):
        l = self.get_pathToRoot()
        l.reverse()
        return l
    def get_root(self):
        c = self
        while c._parent: c = c._parent
        return c

    def is_descendant_of(self, ancestor):
        ui_element = self
        while ui_element != ancestor and ui_element is not None:
            ui_element = ui_element._parent
        return ui_element == ancestor


    def getElementById(self, element_id):
        if element_id is None: return None
        if self._id == element_id: return self
        for child in self.children: # self._children_all:
            e = child.getElementById(element_id)
            if e is not None: return e
        return None

    def getElementsByName(self, element_name):
        if element_name is None: return None
        ret = [self] if self._name == element_name else []
        ret.extend(e for child in self.children for e in child.getElementsByName(element_name))
        return ret

    def getElementsByClassName(self, class_name):
        if class_name is None: return None
        ret = [self] if class_name in self._classes else []
        ret.extend(e for child in self.children for e in child.getElementsByClassName(class_name))
        return ret

    def getElementsByTagName(self, tag_name):
        if tag_name is None: return None
        ret = [self] if tag_name == self._tagName else []
        ret.extend(e for child in self.children for e in child.getElementsByTagName(tag_name))
        return ret

    @property
    def document(self):
        return self._document
    @document.setter
    def document(self, value):
        if self._document == value: return
        if not value:
            self._document.update_callbacks(self, force_remove=True)
        self._document = value
        if value:
            self.update_document()
        for c in self._children:
            c.document = value

    def update_document(self):
        if not self._document: return
        self._document.update_callbacks(self)


    ######################################3
    # children methods

    @property
    def children(self):
        return list(self._children)

    def _append_child(self, child):
        assert child
        if child in self._children:
            # attempting to add existing child?
            return
        if child._parent:
            # detach child from prev parent
            child._parent.delete_child(child)
        self._children.append(child)
        child._parent = self
        child.document = self.document
        child.dirty(cause='appending children', parent=False)
        self.dirty_content(cause='appending children', children=False, parent=False)
        self.dirty_flow()
        self._new_content = True
        return child
    def append_child(self, child): return self._append_child(child)

    def builder(self, children):
        t = type(children)
        if t is list:
            for child in children:
                self.builder(child)
        elif t is tuple:
            child,grandchildren = children
            self.append_child(child).builder(grandchildren)
        elif t is UI_Element or t is UI_Proxy:
            self.append_child(children)
        else:
            assert False, 'UI_Element.builder: unhandled type %s' % t
        return self

    def _delete_child(self, child):
        assert child, 'attempting to delete None child?'
        if child not in self._children:
            # child is not in children, could be wrapped in proxy
            pchildren = [pchild for pchild in self._children if type(pchild) is UI_Proxy and child in pchild._all_elements]
            assert len(pchildren) != 0, 'attempting to delete child that does not exist?'
            assert len(pchildren) == 1, 'attempting to delete child that is wrapped twice?'
            child = pchildren[0]
        self.document.removed_element(child)
        self._children.remove(child)
        child._parent = None
        child.document = None
        child.dirty(cause='deleting child from parent')
        self.dirty_content(cause='deleting child changes content')
        self._new_content = True
    def delete_child(self, child): self._delete_child(child)

    @UI_Element_Utils.defer_dirty_wrapper('clearing children')
    def _clear_children(self):
        for child in list(self._children):
            self._delete_child(child)
        self._new_content = True
    def clear_children(self): self._clear_children()

    def _count_children(self):
        return sum(child.count_children() for child in self._children)
    def count_children(self): return 1 + self._count_children()
    def _count_all_children(self):
        return sum(child.count_all_children() for child in self._children_all)
    def count_all_children(self): return 1 + self._count_all_children()

    #########################################
    # style methods

    @property
    def style(self):
        return str(self._style_str)
    @style.setter
    def style(self, style):
        style = str(style or '')
        if self._style_str == style: return
        self._style_str = style
        self._styling_custom = None
        self.dirty_style(cause=f'changing style for {self} affects style')
        # self.dirty(f'changing style for {self} affects parent content', 'content', parent=True, children=False)
        self.add_dirty_callback_to_parent(['style', 'content'])
    def add_style(self, style):
        style = f'{self._style_str};{style or ""}'
        if self._style_str == style: return
        self._style_str = style
        self._styling_custom = None
        self.dirty_style(cause=f'adding style for {self} affects style')
        # self.dirty(f'adding style for {self} affects parent content', 'content', parent=True, children=False)
        self.add_dirty_callback_to_parent(['style', 'content'])

    @property
    def id(self):
        return self._id
    @id.setter
    def id(self, nid):
        nid = '' if nid is None else nid.strip()
        if self._id == nid: return
        self._id = nid
        self.dirty_selector(cause=f'changing id for {self} affects selector', children=True)
        # self.dirty(f'changing id for {self} affects parent content', 'content', parent=True, children=False)
        self.add_dirty_callback_to_parent('selector')

    @property
    def forId(self):
        return self._forId
    @forId.setter
    def forId(self, v):
        self._forId = v

    @property
    def name(self):
        return self._name
    @name.setter
    def name(self, v):
        self._name = v

    @property
    def classes(self):
        return str(self._classes_str) # ' '.join(self._classes)
    @classes.setter
    def classes(self, classes):
        classes = ' '.join(c for c in classes.split(' ') if c) if classes else ''
        l = classes.split(' ')
        pcount = { p:0 for p in l }
        classes = []
        for p in l:
            pcount[p] += 1
            if pcount[p] == 1: classes += [p]
        classes_str = ' '.join(classes)
        if self._classes_str == classes_str: return
        self._classes_str = classes_str
        self._classes = classes
        self.dirty_selector(cause=f'changing classes to "{classes_str}" for {self} affects selector', children=True)
        self.add_dirty_callback_to_parent('content')
    def add_class(self, cls):
        assert ' ' not in cls, f'cannot add class "{cls}" to "{self._tagName}" because it has a space in it'
        if cls in self._classes: return
        self._classes.append(cls)
        self._classes_str = ' '.join(self._classes)
        self.dirty_selector(cause=f'adding class "{cls}" for {self} affects selector', children=True)
        self.add_dirty_callback_to_parent('content')
    def del_class(self, cls):
        assert ' ' not in cls, f'cannot del class "{cls}" from "{self._tagName}" because it has a space in it'
        if cls not in self._classes: return
        self._classes.remove(cls)
        self._classes_str = ' '.join(self._classes)
        self.dirty_selector(cause=f'deleting class "{cls}" for {self} affects selector', children=True)
        self.add_dirty_callback_to_parent('content')


    @property
    def clamp_to_parent(self):
        return self._clamp_to_parent

    @clamp_to_parent.setter
    def clamp_to_parent(self, val):
        self._clamp_to_parent = bool(val)

    ###################################
    # pseudoclasses methods

    @property
    def pseudoclasses(self):
        return set(self._pseudoclasses)

    def _has_affected_descendant(self):
        self._rebuild_style_selector()
        return self._children_text or UI_Styling.has_matches(self._selector+['*'], *self._styling_list)

    def clear_pseudoclass(self):
        if not self._pseudoclasses: return
        self._pseudoclasses.clear()
        self.dirty_selector(cause=f'clearing psuedoclasses for {self} affects selector', children=True) #self._has_affected_descendant())

    def add_pseudoclass(self, pseudo):
        if pseudo in self._pseudoclasses: return
        if pseudo == 'disabled':
            self._pseudoclasses.discard('active')
            self._pseudoclasses.discard('focus')
            # TODO: on_blur?
        self._pseudoclasses.add(pseudo)
        self.dirty_selector(cause=f'adding psuedoclass {pseudo} for {self} affects selector', children=True) #self._has_affected_descendant())

    def del_pseudoclass(self, pseudo):
        if pseudo not in self._pseudoclasses: return
        self._pseudoclasses.discard(pseudo)
        self.dirty_selector(cause=f'deleting psuedoclass {pseudo} for {self} affects selector', children=True) #self._has_affected_descendant())

    def has_pseudoclass(self, pseudo):
        if pseudo == 'disabled' and self._disabled: return True
        return pseudo in self._pseudoclasses

    @property
    def is_active(self): return 'active' in self._pseudoclasses
    @property
    def is_hovered(self): return 'hover' in self._pseudoclasses
    @property
    def is_focused(self): return 'focus' in self._pseudoclasses
    @property
    def is_disabled(self):
        if 'disabled' in self._pseudoclasses: return True
        if self._value_bound: return self._value.disabled
        if self._checked_bound: return self._checked.disabled
        return False
        #return 'disabled' in self._pseudoclasses

    @property
    def disabled(self): return self.is_disabled
    @disabled.setter
    def disabled(self, v):
        c = self.is_disabled
        if c == v: return
        if v: self.add_pseudoclass('disabled')
        else: self.del_pseudoclass('disabled')

    def blur(self):
        if 'focus' not in self._pseudoclasses: return
        self._document.blur()

    @property
    def pseudoelement(self):
        return self._pseudoelement
    @pseudoelement.setter
    def pseudoelement(self, v):
        v = v or ''
        if self._pseudoelement == v: return
        self._pseudoelement = v
        self.dirty_selector(cause='changing psuedoelement affects selector')

    @property
    def src(self):
        if self._src_str: return self._src_str
        src = self._computed_styles.get('background-image', 'none')
        if src == 'none': src = None
        return src
    @src.setter
    def src(self, v):
        # TODO: load the resource and do something with it!!
        if self._src_str == v: return
        self._src_str = v
        self._src = None    # force reload of image
        self._new_content = True
        self.dirty_style(cause='changing src affects content')

    @property
    def title(self):
        return self._title
    @title.setter
    def title(self, v):
        self._title = v
        # self.dirty('title changed', parent=True, children=False)

    def reposition(self, left=None, top=None, bottom=None, right=None, clamp_position=True):
        assert not bottom and not right, 'repositioning UI via bottom or right not implemented yet :('
        if clamp_position and self._relative_element:
            w,h = Globals.drawing.scale(self.width_pixels),self.height_pixels #Globals.drawing.scale(self.height_pixels)
            rw,rh = self._relative_element.width_pixels,self._relative_element.height_pixels
            mbpw,mbph = self._relative_element._mbp_width,self._relative_element._mbp_height
            if left is not None: left = clamp(left, 0, (rw - mbpw) - w)
            if top  is not None: top  = clamp(top, -(rh - mbph) + h, 0)
        if left is None: left = self._style_left
        if top  is None: top  = self._style_top
        if self._style_left != left or self._style_top != top:
            self._style_left = left
            self._style_top  = top
            self._absolute_pos = None
            self.update_position()
            # tag_redraw_all("UI_Element reposition")
            self.dirty_renderbuf(cause='repositioning', parent=True)
            self.dirty_flow()
            if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} repositioned')

    @property
    def left(self):
        l = self.style_left
        return self._relative_pos.x if self._relative_pos and l == 'auto' else l
        # return self._style_left if self._style_left is not None else self._computed_styles.get('left', 'auto')
    @left.setter
    def left(self, v):
        self.style_left = v
        self.dirty_flow()
    @property
    def style_left(self):
        if self._style_left is not None: return self._style_left
        return self._computed_styles.get('left', 'auto')
    @style_left.setter
    def style_left(self, v):
        if self._style_left == v: return
        self._style_left = v
        self.dirty_flow()

    @property
    def top(self):
        t = self.style_top
        return self._relative_pos.y if self._relative_pos and t == 'auto' else t
        # return self._style_top if self._style_top is not None else self._computed_styles.get('top', 'auto')
    @top.setter
    def top(self, v):
        self.style_top = v
        self.dirty_flow()
    @property
    def style_top(self):
        if self._style_top is not None: return self._style_top
        return self._computed_styles.get('top', 'auto')
    @style_top.setter
    def style_top(self, v):
        if self._style_top == v: return
        self._style_top = v
        self.dirty_flow()

    @property
    def right(self):
        return self._style_right if self._style_right is not None else self._computed_styles.get('right', 'auto')
    @right.setter
    def right(self, v):
        self._style_right = v
        self.dirty_flow()
    @property
    def style_right(self):
        if self._style_right is not None: return self._style_right
        return self._computed_styles.get('right', 'auto')
    @style_right.setter
    def style_right(self, v):
        if self._style_right == v: return
        self._style_right = v
        self.dirty_flow()

    @property
    def bottom(self):
        return self._style_bottom if self._style_bottom is not None else self._computed_styles.get('bottom', 'auto')
    @bottom.setter
    def bottom(self, v):
        self._style_bottom = v
        self.dirty_flow()
    @property
    def style_bottom(self):
        if self._style_bottom is not None: return self._style_bottom
        return self._computed_styles.get('bottom', 'auto')
    @style_bottom.setter
    def style_bottom(self, v):
        if self_style_bottom == v: return
        self._style_bottom = v
        self.dirty_flow()

    @property
    def width(self):
        w = self.style_width
        return self._absolute_size.width if self._absolute_size and w == 'auto' else w
    @width.setter
    def width(self, v):
        self.style_width = v
    @property
    def style_width(self):
        if self._style_width is not None: return self._style_width
        return self._computed_styles.get('width', 'auto')
    @style_width.setter
    def style_width(self, v):
        if self._style_width == v: return
        self._style_width = v
        self.dirty_flow()

    @property
    def height(self):
        h = self.style_height
        return self._absolute_size.height if self._absolute_size and h == 'auto' else h
    @height.setter
    def height(self, v):
        self.style_height = v
    @property
    def style_height(self):
        if self._style_height is not None: return self._style_height
        return self._computed_styles.get('height', 'auto')
    @style_height.setter
    def style_height(self, v):
        if self._style_height == v: return
        self._style_height = v
        self.dirty_flow()

    @property
    def left_pixels(self):
        if self._relative_element is None:   rew = self._parent_size.width if self._parent_size else 0
        elif self._relative_element == self: rew = self._parent_size.width if self._parent_size else 0
        else:                                rew = self._relative_element.width_pixels
        l = self.style_left
        if self._relative_pos and l == 'auto': l = self._relative_pos.x
        if l != 'auto':
            if type(l) is NumberUnit: l = l.val(base=rew)
        else:
            dpi_mult = Globals.drawing.get_dpi_mult()
            r = self.style_right
            w = self.width_pixels*dpi_mult if self.width_pixels != 'auto' else 0
            # if r != 'auto': print(l,rew,r,w)
            if type(r) is NumberUnit: l = rew - (w + r.val(base=rew))
            elif r != 'auto':         l = rew - (w + r)
        return l
    @property
    def left_scissor(self):
        return self._l
    @property
    def left_override(self):
        return self._left_override
    @left_override.setter
    def left_override(self, v):
        self._left_override = v

    @property
    def top_pixels(self):
        if self._relative_element is None:   reh = self._parent_size.height if self._parent_size else 0
        elif self._relative_element == self: reh = self._parent_size.height if self._parent_size else 0
        else:                                reh = self._relative_element.height_pixels
        t = self.style_top
        if self._relative_pos and t == 'auto': t = self._relative_pos.y
        if t != 'auto':
            if type(t) is NumberUnit: t = t.val(base=reh)
        else:
            dpi_mult = Globals.drawing.get_dpi_mult()
            b = self.style_bottom
            h = self.height_pixels*dpi_mult if self.height_pixels != 'auto' else 0
            if type(b) is NumberUnit: t = h + b.val(base=reh) - reh
            elif b != 'auto':         t = h + b
        return t
    @property
    def top_scissor(self):
        return self._t
    @property
    def top_override(self):
        return self._top_override
    @top_override.setter
    def top_override(self, v):
        self._top_override = v

    @property
    def width_pixels(self):
        w = self.style_width
        if self._absolute_size and w == 'auto': w = self._absolute_size.width
        if type(w) is NumberUnit:
            if   self._relative_element == self: rew = self._parent_size.width if self._parent_size else 0
            elif self._relative_element is None: rew = 0
            else:                                rew = self._relative_element.width_pixels
            if rew == 'auto': rew = 0
            w = w.val(base=rew)
        return w
    @property
    def width_scissor(self):
        return self._w
    @property
    def width_override(self):
        return self._width_override
    @width_override.setter
    def width_override(self, v):
        self._width_override = v

    @property
    def height_pixels(self):
        h = self.style_height
        if self._absolute_size and h == 'auto': h = self._absolute_size.height
        if type(h) is NumberUnit:
            if   self._relative_element == self: reh = self._parent_size.height if self._parent_size else 0
            elif self._relative_element is None: reh = 0
            else:                                reh = self._relative_element.height_pixels
            if reh == 'auto': reh = 0
            h = h.val(base=reh)
        return h
    @property
    def height_scissor(self):
        return self._h
    @property
    def height_override(self):
        return self._height_override
    @height_override.setter
    def height_override(self, v):
        self._height_override = v


    @property
    def z_index(self):
        if self._style_z_index is not None: return self._style_z_index
        v = self._computed_styles.get('z-index', 0)
        if type(v) is NumberUnit: return v.val()
        return v
    @z_index.setter
    def z_index(self, v):
        if self._style_z_index == v: return
        self._style_z_index = v
        self.dirty_flow()


    @property
    def scrollTop(self):
        # TODO: clamp value?
        return self._scroll_offset.y
    @scrollTop.setter
    def scrollTop(self, v):
        if not self._is_scrollable_y: v = 0
        v = floor(v)
        v = min(v, self._dynamic_content_size.height - self._absolute_size.height + self._mbp_height)
        v = max(v, 0)
        if self._scroll_offset.y != v:
            # print('scrollTop:', v)
            self._scroll_offset.y = v
            tag_redraw_all("UI_Element scrollTop")
            self.dirty_renderbuf(cause='scrolltop')

    def scrollToTop(self, force=False):
        if self._scroll_offset.y != 0 or force:
            self._scroll_offset.y = 0
            tag_redraw_all("UI_Element scrollToTop")
            self.dirty_renderbuf(cause='scrolltotop')

    @property
    def scrollLeft(self):
        # TODO: clamp value?
        return -self._scroll_offset.x    # negated so that positive values of scrollLeft scroll content left
    @scrollLeft.setter
    def scrollLeft(self, v):
        # TODO: clamp value?
        if not self._is_scrollable_x: v = 0
        v = floor(v)
        v = min(v, self._dynamic_content_size.width - self._absolute_size.width + self._mbp_width)
        v = max(v, 0)
        v = -v
        if self._scroll_offset.x != v:
            self._scroll_offset.x = v
            tag_redraw_all("UI_Element scrollLeft")
            self.dirty_renderbuf(cause='scrollleft')

    @property
    def is_visible(self):
        # MUST BE CALLED AFTER `compute_style()` METHOD IS CALLED!
        return self.get_is_visible() and (self._parent.is_visible if self._parent else True)
    @is_visible.setter
    def is_visible(self, v):
        if self._is_visible == v: return
        self._is_visible = v
        # self.dirty('changing visibility can affect everything', parent=True, children=True)
        self.dirty(cause='visibility changed')
        self.dirty_flow()
        self.dirty_renderbuf(cause='changing visibility can affect everything')

    # self.get_is_visible() is same as self.is_visible() except it doesn't check parent
    def get_is_visible(self):
        if self._is_visible is None:
            v = self._computed_styles.get('display', 'auto') != 'none'
        else:
            v = self._is_visible
        return v

    @property
    def is_scrollable(self):
        return self._is_scrollable_x or self._is_scrollable_y
    @property
    def is_scrollable_x(self):
        return self._is_scrollable_x
    @property
    def is_scrollable_y(self):
        return self._is_scrollable_y

    def get_visible_children(self):
        # MUST BE CALLED AFTER `compute_style()` METHOD IS CALLED!
        # NOTE: returns list of children without `display:none` style.
        #       does _NOT_ mean that the child is going to be drawn
        #       (might still be clipped with scissor or `visibility:hidden` style)
        return [child for child in self._children if child.is_visible]

    @property
    def content_width(self):
        return self._static_content_size.width
    @property
    def content_height(self):
        return self._static_content_size.height

    @property
    def type(self):
        return self._type
    @type.setter
    def type(self, v):
        self._type = v
        self.dirty_selector(cause='changing type can affect selector', children=True)

    @property
    def value(self):
        if self._value_bound:
            return self._value.value
        else:
            return self._value
    @value.setter
    def value(self, v):
        if self._value_bound:
            self._value.value = v
        elif self._value != v:
            self._value = v
            self._value_change()
    def _value_change(self):
        if not self.is_visible: return
        self.dispatch_event('on_input')
        self.dirty_selector(cause='changing value can affect selector and content', children=True)
    def value_bind(self, boundvar):
        self._value = boundvar
        self._value.on_change(self._value_change)
        self._value_bound = True
    def value_unbind(self, v=None):
        p = self._value
        self._value = v
        self._value_bound = False
        return p

    @property
    def checked(self):
        if self._checked_bound:
            return self._checked.value
        else:
            return self._checked
    @checked.setter
    def checked(self, v):
        # v = "checked" if v else None
        if self._checked_bound:
            self._checked.value = v
        elif self._checked != v:
            self._checked = v
            self._checked_change()
    def _checked_change(self):
        self.dispatch_event('on_input')
        self.dirty_selector(cause='changing checked can affect selector and content', children=True)
    def checked_bind(self, boundvar):
        self._checked = boundvar
        self._checked.on_change(self._checked_change)
        self._checked_bound = True
    def checked_unbind(self, v=None):
        p = self._checked
        self._checked = v
        self._checked_bound = False
        return p

    @property
    def href(self):
        return self._href or ''
    @href.setter
    def href(self, v):
        self._href = v

    @property
    def preclean(self):
        return self._preclean
    @preclean.setter
    def preclean(self, fn):
        self._preclean = fn
        self.update_document()

    @property
    def postclean(self):
        return self._postclean
    @postclean.setter
    def postclean(self, fn):
        self._postclean = fn
        self.update_document()

    @property
    def postflow(self):
        return self._postflow
    @postflow.setter
    def postflow(self, fn):
        self._postflow = fn
        self.update_document()

    @property
    def can_focus(self): return self._can_focus
    @can_focus.setter
    def can_focus(self, v): self._can_focus = v

    @property
    def can_hover(self): return self._can_hover
    @can_hover.setter
    def can_hover(self, v): self._can_hover = v

    @profiler.function
    def get_text_pos(self, index):
        if self._innerText is None: return None
        index = clamp(index, 0, len(self._text_map)-1)
        m = self._text_map[index]
        e = m['ui_element']
        idx = m['idx']
        offset = m['offset']
        pre = m['pre']
        tw = Globals.drawing.get_text_width(pre, fontsize=self._fontsize, fontid=self._fontid)
        e_pos = e._relative_pos + e._relative_offset + e._scroll_offset + RelPoint2D((tw, 0))
        return e_pos

    def get_text_index(self, pos):
        if self._innerText is None: return None
        size_prev = Globals.drawing.set_font_size(self._fontsize, fontid=self._fontid)
        get_text_width = Globals.drawing.get_text_width
        get_line_height = Globals.drawing.get_line_height
        self_pos = Point2D((self._l, self._t)) #+ RelPoint2D((self._mbp_left, -self._mbp_top))
        offset = RelPoint2D(pos - self_pos)
        # print('get_text_index')
        # print('  pos:', pos)
        # print('  self', self_pos)
        # print('  off', offset)
        best_dist = None
        best_index = None
        for index,m in enumerate(self._text_map):
            e = m['ui_element']
            pre = m['pre']
            char = m['char']
            pre_w = get_text_width(pre)
            char_w = get_text_width(char)-1
            char_h = get_line_height(char)
            e_pos = Point2D(e._relative_pos + e._relative_offset + e._scroll_offset + RelPoint2D((pre_w, 0)))
            cx = clamp(offset.x, e_pos.x, e_pos.x + char_w)
            cy = clamp(offset.y, e_pos.y - char_h, e_pos.y)
            dist = abs(offset.x - cx) + abs(offset.y - cy)
            # print('  ', pre, char, e_pos, e_pos+RelPoint2D((char_w,-char_h)), (cx, cy), dist)
            if best_dist is None or dist <= best_dist:
                best_dist = dist
                best_index = index
                if offset.x - e_pos.x > char_w / 2:
                    best_index += 1
        Globals.drawing.set_font_size(size_prev, fontid=self._fontid)
        return min(best_index, len(self._text_map)-1)




class UI_Element_Dirtiness:
    @profiler.function
    def dirty(self, **kwargs):
        self._dirty(**kwargs)
    @profiler.function
    def dirty_selector(self, **kwargs):
        self._dirty(properties={'selector'}, **kwargs)
    @profiler.function
    def dirty_style_parent(self, **kwargs):
        self._dirty(properties={'style parent'}, **kwargs)
    @profiler.function
    def dirty_style(self, **kwargs):
        self._dirty(properties={'style'}, **kwargs)
    @profiler.function
    def dirty_content(self, **kwargs):
        self._dirty(properties={'content'}, **kwargs)
    @profiler.function
    def dirty_blocks(self, **kwargs):
        self._dirty(properties={'blocks'}, **kwargs)
    @profiler.function
    def dirty_size(self, **kwargs):
        self._dirty(properties={'size'}, **kwargs)
    @profiler.function
    def dirty_renderbuf(self, **kwargs):
        self._dirty(properties={'renderbuf'}, **kwargs)

    def _dirty(self, *, cause=None, properties=None, parent=False, children=False, propagate_up=True):
        # assert cause
        if cause is None: cause = 'Unspecified cause'
        if properties is None: properties = set(UI_Element_Utils._cleaning_graph_nodes)
        elif type(properties) is str:  properties = {properties}
        elif type(properties) is list: properties = set(properties)
        properties -= self._dirty_properties    # ignore dirtying properties that are already dirty
        if not properties: return               # no new dirtiness
        # if getattr(self, '_cleaning', False): print(f'{self} was dirtied ({properties}) while cleaning')
        self._dirty_properties |= properties
        self._dirty_causes.append(cause)
        if parent:   self._dirty_propagation['parent']          |= properties   # dirty parent also (ex: size of self changes, so parent needs to layout)
        else:        self._dirty_propagation['parent callback'] |= properties   # let parent know self is dirty (ex: background color changes, so we need to update style of self but not parent)
        if children: self._dirty_propagation['children']        |= properties   # dirty all children also (ex: :hover pseudoclass added, so children might be affected)

        # any dirtiness _ALWAYS_ dirties renderbuf of self and parent
        self._dirty_properties.add('renderbuf')
        self._dirty_propagation['parent'].add('renderbuf')

        if propagate_up: self.propagate_dirtiness_up()
        self.dirty_flow(children=False)
        # print(f'{self} had {properties} dirtied, because {cause}')
        tag_redraw_all("UI_Element dirty")

    def add_dirty_callback(self, child, properties):
        if type(properties) is str: properties = [properties]
        if not properties: return
        propagate_props = {
            p for p in properties
            if p not in self._dirty_properties
                and child not in self._dirty_callbacks[p]
        }
        if not propagate_props: return
        for p in propagate_props: self._dirty_callbacks[p].add(child)
        self.add_dirty_callback_to_parent(propagate_props)

    def add_dirty_callback_to_parent(self, properties):
        if not self._parent: return
        if self._do_not_dirty_parent: return
        if not properties: return
        self._parent.add_dirty_callback(self, properties)


    @profiler.function
    def dirty_styling(self):
        '''
        NOTE: this function clears style cache for self and all descendants
        '''
        self._computed_styles = {}
        self._styling_parent = None
        # self._styling_custom = None
        self._style_content_hash = None
        self._style_size_hash = None
        for child in self._children_all: child.dirty_styling()
        self.dirty_style(cause='Dirtying style cache')



    @profiler.function
    def dirty_flow(self, parent=True, children=True):
        if self._dirtying_flow and self._dirtying_children_flow: return
        if not self._dirtying_flow:
            if parent and self._parent and not self._do_not_dirty_parent:
                self._parent.dirty_flow(children=False)
            self._dirtying_flow = True
        self._dirtying_children_flow |= self._computed_styles.get('display', 'block') == 'table'
        tag_redraw_all("UI_Element dirty_flow")

    @property
    def is_dirty(self):
        return any_args(
            self._dirty_properties,
            self._dirty_propagation['parent'],
            self._dirty_propagation['parent callback'],
            self._dirty_propagation['children'],
        )

    @profiler.function
    def propagate_dirtiness_up(self):
        if self._dirty_propagation['defer']: return

        if self._dirty_propagation['parent']:
            if self._parent and not self._do_not_dirty_parent:
                cause = ' -> '.join(f'{cause}' for cause in (self._dirty_causes+[
                    f"\"propagating dirtiness ({self._dirty_propagation['parent']} from {self} to parent {self._parent}\""
                ]))
                self._parent.dirty(
                    cause=cause,
                    properties=self._dirty_propagation['parent'],
                    parent=True,
                    children=False,
                )
            self._dirty_propagation['parent'].clear()

        if not self._do_not_dirty_parent:
            self.add_dirty_callback_to_parent(self._dirty_propagation['parent callback'])
        self._dirty_propagation['parent callback'].clear()

        self._dirty_causes = []

    @profiler.function
    def propagate_dirtiness_down(self):
        if not self._dirty_propagation['children']: return

        # no need to dirty ::before, ::after, or text, because they will be reconstructed
        for child in self._children:
            child.dirty(
                cause=f'propagating {self._dirty_propagation["children"]}',
                properties=self._dirty_propagation['children'],
                parent=False,
                children=True,
            )
        self._dirty_propagation['children'].clear()



    @property
    def defer_dirty_propagation(self):
        return self._dirty_propagation['defer']
    @defer_dirty_propagation.setter
    def defer_dirty_propagation(self, v):
        self._dirty_propagation['defer'] = bool(v)
        self.propagate_dirtiness_up()

    def _call_preclean(self):
        if not self.is_dirty:  return
        if not self._preclean: return
        self._preclean()
    def _call_postclean(self):
        if not self._was_dirty: return
        self._was_dirty = False
        if not self._postclean: return
        self._postclean()
    def _call_postflow(self):
        if not self._postflow: return
        if not self.is_visible: return
        self._postflow()

    @property
    def defer_clean(self):
        if not self._document: return True
        if self._document.defer_cleaning: return True
        if self._defer_clean: return True
        # if not self.is_dirty: return True
        return False
    @defer_clean.setter
    def defer_clean(self, value):
        self._defer_clean = value

    @profiler.function
    def clean(self, depth=0):
        '''
        No need to clean if
        - already clean,
        - possibly more dirtiness to propagate,
        - if deferring cleaning.
        '''

        if not self.is_dirty or self.defer_clean: return
        self._was_dirty = True   # used to know if postclean should get called

        self._cleaning = True

        profiler.add_note(f'pre: {self._dirty_properties}, {self._dirty_causes} {self._dirty_propagation}')
        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} clean started defer={self.defer_clean}')

        # propagate dirtiness one level down
        self.propagate_dirtiness_down()

        # self.call_cleaning_callbacks()
        self._compute_selector()
        self._compute_style()
        self._compute_content()
        self._compute_blocks()
        self._compute_static_content_size()
        self._renderbuf()

        profiler.add_note(f'mid: {self._dirty_properties}, {self._dirty_causes} {self._dirty_propagation}')

        for child in self._children_all:
           child.clean(depth=depth+1)

        profiler.add_note(f'post: {self._dirty_properties}, {self._dirty_causes} {self._dirty_propagation}')
        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} clean done')

        # self._debug_list.clear()

        self._cleaning = False


    @profiler.function
    def call_cleaning_callbacks(self):
        g = UI_Element_Utils._cleaning_graph
        working = set(UI_Element_Utils._cleaning_graph_roots)
        done = set()
        restarts = []
        while working:
            current = working.pop()
            curnode = g[current]
            assert current not in done, f'cycle detected in cleaning callbacks ({current})'
            if not all(p in done for p in curnode['parents']): continue
            do_cleaning = False
            do_cleaning |= current in self._dirty_properties
            do_cleaning |= bool(self._dirty_callbacks.get(current, False))
            if do_cleaning:
                curnode['fn'](self)
            redirtied = [d for d in self._dirty_properties if d in done]
            if redirtied:
                # print('UI_Core.call_cleaning_callbacks:', self, current, 'dirtied', redirtied)
                if len(restarts) < 50:
                    profiler.add_note('restarting')
                    working = set(UI_Element_Utils._cleaning_graph_roots)
                    done = set()
                    restarts.append((curnode, self._dirty_properties))
                else:
                    return
            else:
                working.update(curnode['children'])
                done.add(current)




class UI_Element_Debug:
    def debug_print(self, d, already_printed):
        sp = '    '*d
        tag = self.as_html
        tagc = f'</{self._tagName}>'
        tagsc = f'{tag[:-1]} />'
        if self in already_printed:
            print(f'{sp}{tag}...{tagc}')
            return
        already_printed.add(self)
        if self._children:
            print(f'{sp}{tag}')
            for c in self._children:
                c.debug_print(d+1, already_printed)
            print(f'{sp}{tagc}')
        elif self._innerText:
            print(f'{sp}{tag}{self._innerText}{tagc}')
        else:
            print(f'{sp}{tagsc}')

    def structure(self, depth=0, all_children=False):
        l = self._children if not all_children else self._children_all
        return '\n'.join([('  '*depth) + str(self)] + [child.structure(depth+1) for child in l])


class UI_Element_PreventMultiCalls:
    multicalls = {}

    @staticmethod
    def reset_multicalls():
        # print(UI_Element_PreventMultiCalls.multicalls)
        UI_Element_PreventMultiCalls.multicalls = {}

    def record_multicall(self, label):
        # returns True if already called!
        d = UI_Element_PreventMultiCalls.multicalls
        if label not in d: d[label] = { self._uid }
        elif self._uid not in d[label]: d[label].add(self._uid)
        else: return True
        return False



class UI_Element(UI_Element_Utils, UI_Element_Properties, UI_Element_Dirtiness, UI_Element_Debug, UI_Element_PreventMultiCalls):
    @staticmethod
    @add_cache('uid', 0)
    def get_uid():
        UI_Element.get_uid.uid += 1
        return UI_Element.get_uid.uid

    def __init__(self, **kwargs):
        ################################################################
        # attributes of UI_Element that are settable
        # set to blank defaults, will be set again later in __init__()
        self._tagName       = ''        # determines type of UI element
        self._id            = ''        # unique identifier
        self._classes_str   = ''        # list of classes (space delimited string)
        self._style_str     = ''        # custom style string
        self._innerText     = None      # text to display (converted to UI_Elements)
        self._src_str       = None      # path to resource, such as image
        self._can_focus     = False     # True:self can take focus
        self._can_hover     = True      # True:self can take hover
        self._title         = None      # tooltip
        self._forId         = None      # used for labels
        self._uid           = UI_Element.get_uid()
        self._document      = None

        # DEBUG
        self._debug_list       = []

        # attribs
        self._type            = None
        self._value           = None
        self._value_bound     = False
        self._checked         = None
        self._checked_bound   = False
        self._name            = None
        self._href            = None
        self._clamp_to_parent = False

        self._was_dirty     = False
        self._preclean      = None      # fn that's called back right before clean is started
        self._postclean     = None      # fn that's called back right after clean is done
        self._postflow      = None      # fn that's called back right after layout is done

        #################################################################
        # read-only attributes of UI_Element
        self._atomic        = False     # True:all children under self should be considered as part of self (ex: don't pass on events)
        self._parent        = None      # read-only property; set in parent.append_child(child)
        self._parent_size   = None
        self._children      = []        # read-only list of all children; append_child, delete_child, clear_children
        self._pseudoclasses = set()     # TODO: should order matter here? (make list)
                                        # updated by main ui system (hover, active, focus)
        self._pseudoelement = ''        # set only if element is a pseudoelement ('::before' or '::after')

        self._style_left    = None
        self._style_top     = None
        self._style_right   = None
        self._style_bottom  = None
        self._style_width   = None
        self._style_height  = None
        self._style_z_index = None

        self._document_elem = None      # this is actually the document.body.  TODO: rename?
        self._nonstatic_elem = None


        #################################################################################
        # boxes for viewing (wrt blender region) and content (wrt view)
        # NOTE: content box is larger than viewing => scrolling, which is
        #       managed by offsetting the content box up (y+1) or left (x-1)
        self._static_content_size  = None       # size of static content (text, image, etc.) w/o margin,border,padding
        self._dynamic_content_size = None       # size of dynamic content (static or wrapped children) w/o mbp
        self._dynamic_full_size    = None       # size of dynamic content with mbp added
        self._mbp_width            = None
        self._mbp_height           = None
        self._relative_element     = None
        self._relative_pos         = None
        self._relative_offset      = None
        self._alignment_offset     = None
        self._scroll_offset        = Vec2D((0,0))
        self._absolute_pos         = None       # abs pos of element from relative info; cached in draw
        self._absolute_size        = None       # viewing size of element; set by parent
        self._tablecell_table      = None       # table that this cell belongs to
        self._tablecell_pos        = None       # overriding position if table-cell
        self._tablecell_size       = None       # overriding size if table-cell
        self._all_lines            = None       # all children elements broken up into lines (for horizontal alignment)
        self._blocks               = None
        self._children_text_min_size = None

        self._left_override = None
        self._top_override = None
        self._width_override = None
        self._height_override = None

        self._viewing_box = Box2D(topleft=(0,0), size=(-1,-1))  # topleft+size: set by parent element
        self._inside_box  = Box2D(topleft=(0,0), size=(-1,-1))  # inside area of viewing box (less margins, paddings, borders)
        self._content_box = Box2D(topleft=(0,0), size=(-1,-1))  # topleft: set by scrollLeft, scrollTop properties
                                                                # size: determined from children and style

        ##################################################################################
        # all events with their respective callbacks
        # NOTE: values of self._events are list of tuples, where:
        #       - first item is bool indicating type of callback, where True=capturing and False=bubbling
        #       - second item is the callback function, possibly wrapped with lambda
        #       - third item is the original callback function
        self._events = {
            'on_focus':         [],     # focus is gained (:foces is added)
            'on_blur':          [],     # focus is lost (:focus is removed)
            'on_focusin':       [],     # focus is gained to self or a child
            'on_focusout':      [],     # focus is lost from self or a child
            'on_keydown':       [],     # key is pressed down
            'on_keyup':         [],     # key is released
            'on_keypress':      [],     # key is entered (down+up)
            'on_mouseenter':    [],     # mouse enters self (:hover is added)
            'on_mousemove':     [],     # mouse moves over self
            'on_mousedown':     [],     # mouse button is pressed down
            'on_mouseup':       [],     # mouse button is released
            'on_mouseclick':    [],     # mouse button is clicked (down+up while remaining on self)
            'on_mousedblclick': [],     # mouse button is pressed twice in quick succession
            'on_mouseleave':    [],     # mouse leaves self (:hover is removed)
            'on_scroll':        [],     # self is being scrolled
            'on_input':         [],     # occurs immediately after value has changed
        }

        ####################################################################
        # cached properties
        # TODO: go back through these to make sure we've caught everything
        self._classes          = []     # classes applied to element, set by self.classes property, based on self._classes_str
        self._computed_styles  = {}     # computed style UI_Style after applying all styling
        self._computed_styles_before = {}
        self._computed_styles_after = {}
        self._is_visible       = None   # indicates if self is visible, set in compute_style(), based on self._computed_styles
        self._is_scrollable_x  = False  # indicates is self is scrollable along x, set in compute_style(), based on self._computed_styles
        self._is_scrollable_y  = False  # indicates is self is scrollable along y, set in compute_style(), based on self._computed_styles
        self._static_content_size     = None   # min and max size of content, determined from children and style
        self._children_text    = []     # innerText as children
        self._child_before     = None   # ::before child
        self._child_after      = None   # ::after child
        self._children_all     = []     # all children in order
        self._children_all_sorted = []  # all children sorted by z-index
        self._innerTextWrapped = None   # <--- no longer needed?
        self._selector         = None   # full selector of self, built in compute_style()
        self._selector_last    = None   # last full selector of self, updated in compute_style()
        self._selector_before  = None   # full selector of ::before pseudoelement for self
        self._selector_after   = None   # full selector of ::after pseudoelement for self
        self._styling_trimmed  = None
        self._styling_custom   = None   #
        self._styling_parent   = None
        self._styling_list     = []
        self._innerTextAsIs    = None   # text to display as-is (no wrapping)
        self._src              = None
        self._textwrap_opts    = {}
        self._l, self._t, self._w, self._h = 0,0,0,0    # scissor position
        self._fontid           = 0
        self._fontsize         = 12
        self._fontcolor        = (0,0,0,1)
        self._textshadow       = None
        self._whitespace       = 'normal'
        self._cacheRenderBuf   = None   # GPUOffScreen buffer
        self._dirty_renderbuf  = True
        self._style_trbl_cache = {}

        ####################################################
        # dirty properties
        # used to inform parent and children to recompute
        self._dirty_properties = {              # set of dirty properties, add through self.dirty to force propagation of dirtiness
            'style',                            # force recalculations of style
            'style parent',                     # force recalculations of style if parent selector changes
            'content',                          # content of self has changed
            'blocks',                           # children are grouped into blocks
            'size',                             # force recalculations of size
            'renderbuf',                        # force re-rendering buffer (if applicable)
        }
        self._new_content = True
        self._dirtying_flow = True
        self._dirtying_children_flow = True
        self._dirty_causes = []
        self._dirty_callbacks = { k:set() for k in UI_Element_Utils._cleaning_graph_nodes }
        self._dirty_propagation = {             # contains deferred dirty propagation for parent and children; parent will be dirtied later
            'defer':           False,           # set to True to defer dirty propagation (useful when many changes are occurring)
            'parent':          set(),           # set of properties to dirty for parent
            'parent callback': set(),           # set of dirty properties to inform parent
            'children':        set(),           # set of properties to dirty for children
        }
        self._defer_clean = False               # set to True to defer cleaning (useful when many changes are occurring)
        self._clean_debugging = {}
        self._do_not_dirty_parent = False       # special situation where self._parent attrib was set specifically in __init__ (ex: UI_Elements from innerText)
        self._draw_dirty_style = 0              # keeping track of times style is dirtied since last draw

        ########################################################
        # TODO: REPLACE WITH BETTER PROPERTIES AND DELETE!!
        self._preferred_width, self._preferred_height = 0,0
        self._content_width, self._content_height = 0,0
        # various sizes and boxes (set in self._position), used for layout and drawing
        self._preferred_size = Size2D()                         # computed preferred size, set in self._layout, used as suggestion to parent
        self._pref_content_size = Size2D()                      # size of content
        self._pref_full_size = Size2D()                         # _pref_content_size + margins + border + padding
        self._box_draw = Box2D(topleft=(0,0), size=(-1,-1))     # where UI will be drawn (restricted by parent)
        self._box_full = Box2D(topleft=(0,0), size=(-1,-1))     # where UI would draw if not restricted (offset for scrolling)


        ###################################################
        # start setting properties
        # NOTE: some properties require special handling
        with self.defer_dirty('setting initial properties'):
            # NOTE: handle attribs in multiple passes, so that debug prints are more informative

            # first pass: handling events, value, checked, attribs...
            working_keys, unhandled_keys = kwargs.keys(), set()
            for k in working_keys:
                v = kwargs[k]
                if k in self._events:
                    # key is an event; set callback
                    self.add_eventListener(k, v)
                elif k == 'atomic':
                    self._atomic = v
                elif k == 'value' and isinstance(v, BoundVar):
                    self.value_bind(v)
                elif k == 'checked' and isinstance(v, BoundVar):
                    self.checked_bind(v)
                elif hasattr(self, k) and k not in {'parent', '_parent', 'children'}:
                    # need to test that a setter exists for the property
                    class_attr = getattr(type(self), k, None)
                    if type(class_attr) is property:
                        # k is a property
                        assert class_attr.fset is not None, f'Attempting to set a read-only property {k} to "{v}"'
                        setattr(self, k, v)
                    else:
                        # k is an attribute
                        print(f'Setting non-property attribute {k} to "{v}"')
                        setattr(self, k, v)
                else:
                    unhandled_keys.add(k)

            # second pass: handling parent...
            working_keys, unhandled_keys = unhandled_keys, set()
            for k in working_keys:
                v = kwargs[k]
                if k == 'parent':
                    # note: parent.append_child(self) will set self._parent
                    v.append_child(self)
                elif k == '_parent':
                    self._parent = v
                    self._document = v.document
                    self._do_not_dirty_parent = True
                else:
                    unhandled_keys.add(k)

            # third pass: handling children...
            working_keys, unhandled_keys = unhandled_keys, set()
            for k in working_keys:
                v = kwargs[k]
                if k == 'children':
                    # append each child
                    for child in kwargs['children']:
                        self.append_child(child)
                else:
                    unhandled_keys.add(k)

            # report unhandled attribs
            for k in unhandled_keys:
                print('Unhandled pair:', (k, kwargs[k]))

        self.dirty(cause='initially dirty')

    def __del__(self):
        if self._cacheRenderBuf:
            self._cacheRenderBuf.free()
            self._cacheRenderBuf = None

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        info = ['tagName', 'id', 'classes', 'type', 'innerText', 'innerTextAsIs', 'value', 'title']
        info = [(k, getattr(self, k)) for k in info if hasattr(self, k)]
        info = [f'{k}="{v}"' for k,v in info if v]
        if self.is_dirty: info += ['dirty']
        if self._atomic: info += ['atomic']
        return '<%s>' % ' '.join(['UI_Element'] + info)

    @property
    def as_html(self):
        info = [
            'id', 'classes', 'type',
            # 'innerText', 'innerTextAsIs',
            'href',
            'value', 'title',
        ]
        info = [(k, getattr(self, k)) for k in info if hasattr(self, k)]
        info = [f'{k}="{v}"' for k,v in info if v]
        if self.is_dirty: info += ['dirty']
        if self._atomic: info += ['atomic']
        return '<%s>' % ' '.join([self.tagName] + info)

    @profiler.function
    def _rebuild_style_selector(self):
        sel_parent = (None if not self._parent else self._parent._selector) or []

        # TEST!!
        # sel_parent = [re.sub(r':(active|hover)', '', s) for s in sel_parent]


        if self._pseudoelement:
            # this is either a ::before or ::after pseudoelement
            selector = sel_parent[:-1] + [sel_parent[-1] + '::' + self._pseudoelement]
            selector_before = None
            selector_after  = None
        elif self._innerTextAsIs is not None:
            # this is a text element
            selector = sel_parent + ['*text*']
            selector_before = None
            selector_after = None
        else:
            attribs = ['type', 'value']
            sel_tagName = self._tagName
            sel_id = f'#{self._id}' if self._id else ''
            sel_cls = ''.join(f'.{c}' for c in self._classes)
            sel_pseudo = ''.join(f':{p}' for p in self._pseudoclasses)
            if self._value_bound and self._value.disabled: sel_pseudo += ':disabled'
            if self._checked_bound and self._checked.disabled: sel_pseudo += ':disabled'
            sel_attribs = ''.join(f'[{p}]' for p in attribs if getattr(self,p) is not None)
            sel_attribvals = ''.join(f'[{p}="{getattr(self,p)}"]' for p in attribs if getattr(self,p) is not None)
            if self.checked:
                sel_attribs += '[checked]'
                sel_attribvals += '[checked="checked"]'
            self_selector = sel_tagName + sel_id + sel_cls + sel_pseudo + sel_attribs + sel_attribvals
            selector = sel_parent + [self_selector]
            selector_before = sel_parent + [sel_tagName + sel_id + sel_cls + sel_pseudo + '::before']
            selector_after  = sel_parent + [sel_tagName + sel_id + sel_cls + sel_pseudo + '::after']

        # if selector hasn't changed, don't recompute trimmed styling
        if selector == self._selector and selector_before == self._selector_before and selector_after == self._selector_after:
            return False
        styling_trimmed = UI_Styling.trim_styling(selector, ui_defaultstylings, ui_draw.stylesheet)

        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} selector: {" ".join(selector)}')

        self._last_selector = selector
        self._selector = selector
        self._selector_before = selector_before
        self._selector_after = selector_after
        self._styling_trimmed = styling_trimmed
        self._style_trbl_cache = {}
        if self._last_selector and self._last_selector[-1] == self._selector[-1]:
            self.dirty_style_parent(cause='changing parent selector (possibly) dirties style')
        else:
            self.dirty_style(cause='changing selector dirties style')
        return True


    @UI_Element_Utils.add_cleaning_callback('selector', {'style'})
    @profiler.function
    def _compute_selector(self):
        if self.defer_clean: return
        if 'selector' not in self._dirty_properties:
            self.defer_clean = True
            with profiler.code('selector.calling back callbacks'):
                for e in self._dirty_callbacks.get('selector', []):
                    # print(self,'->', e)
                    e._compute_selector()
                self._dirty_callbacks['selector'].clear()
            self.defer_clean = False
            return

        self._clean_debugging['selector'] = time.time()
        self._rebuild_style_selector()
        if self._children:
            for child in self._children: child._compute_selector()
        if self._children_text:
            for child in self._children_text: child._compute_selector()
        if self._child_before or self._child_after:
            if self._child_before: self._child_before._compute_selector()
            if self._child_after:  self._child_after._compute_selector()
        self._dirty_properties.discard('selector')
        self._dirty_callbacks['selector'].clear()


    @UI_Element_Utils.add_cleaning_callback('style', {'size', 'content', 'renderbuf'})
    @UI_Element_Utils.add_cleaning_callback('style parent', {'size', 'content', 'renderbuf'})
    @profiler.function
    def _compute_style(self):
        '''
        rebuilds self._selector and computes the stylesheet, propagating computation to children

        IMPORTANT: as current written, this function needs to be able to be run multiple times!
                   DO NOT PREVENT THIS, otherwise infinite loop bugs will occur!
        '''

        if self.defer_clean: return

        if all(p not in self._dirty_properties for p in ['style', 'style parent']):
            self.defer_clean = True
            with profiler.code('style.calling back callbacks'):
                for e in self._dirty_callbacks.get('style', []):
                    # print(self,'->', e)
                    e._compute_style()
                for e in self._dirty_callbacks.get('style parent', []):
                    # print(self,'->', e)
                    e._compute_style()
                self._dirty_callbacks['style'].clear()
                self._dirty_callbacks['style parent'].clear()
            self.defer_clean = False
            return

        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} style')

        self._draw_dirty_style += 1
        self._clean_debugging['style'] = time.time()

        # self.defer_dirty_propagation = True

        # self._rebuild_style_selector()

        with profiler.code('style.initialize styles in order: parent, default, custom'):
            #  default, focus, active, hover, hover+active

            # TODO: inherit parent styles with other elements (not just *text*)
            # if self._styling_parent is None:
            #     if self._parent:
            #         # keep = {
            #         #     'font-family', 'font-style', 'font-weight', 'font-size',
            #         #     'color',
            #         # }
            #         # decllist = {k:v for (k,v) in self._parent._computed_styles.items() if k in keep}
            #         # self._styling_parent = UI_Styling.from_decllist(decllist)
            #         self._styling_parent = None

            # compute custom styles
            if self._styling_custom is None and self._style_str:
                self._styling_custom = UI_Styling(f'*{{{self._style_str};}}', inline=True)

            self._styling_list = [
                self._styling_trimmed,
                # self._styling_parent,
                self._styling_custom
            ]
            self._computed_styles = UI_Styling.compute_style(self._selector, *self._styling_list)


        with profiler.code('style.filling style cache'):
            if self._is_visible and not self._pseudoelement:
                # need to compute ::before and ::after styles to know whether there is content to compute and render
                self._computed_styles_before = None # UI_Styling.compute_style(self._selector_before, *styling_list)
                self._computed_styles_after  = None # UI_Styling.compute_style(self._selector_after,  *styling_list)
            else:
                self._computed_styles_before = None
                self._computed_styles_after = None
            self._is_scrollable_x = (self._computed_styles.get('overflow-x', 'visible') == 'scroll')
            self._is_scrollable_y = (self._computed_styles.get('overflow-y', 'visible') == 'scroll')

            dpi_mult = Globals.drawing.get_dpi_mult()
            self._style_cache = {}
            sc = self._style_cache
            if self._innerTextAsIs is None:
                sc['left']   = self._computed_styles.get('left',   'auto')
                sc['right']  = self._computed_styles.get('right',  'auto')
                sc['top']    = self._computed_styles.get('top',    'auto')
                sc['bottom'] = self._computed_styles.get('bottom', 'auto')
                sc['margin-top'],  sc['margin-right'],  sc['margin-bottom'],  sc['margin-left']  = self._get_style_trbl('margin',  scale=dpi_mult)
                sc['padding-top'], sc['padding-right'], sc['padding-bottom'], sc['padding-left'] = self._get_style_trbl('padding', scale=dpi_mult)
                sc['border-width']        = self._get_style_num('border-width', def_v=NumberUnit.zero, scale=dpi_mult)
                sc['border-radius']       = self._computed_styles.get('border-radius', 0)
                sc['border-left-color']   = self._computed_styles.get('border-left-color',   Color.transparent)
                sc['border-right-color']  = self._computed_styles.get('border-right-color',  Color.transparent)
                sc['border-top-color']    = self._computed_styles.get('border-top-color',    Color.transparent)
                sc['border-bottom-color'] = self._computed_styles.get('border-bottom-color', Color.transparent)
                sc['background-color']    = self._computed_styles.get('background-color',    Color.transparent)
                sc['width']  = self._computed_styles.get('width',  'auto')
                sc['height'] = self._computed_styles.get('height', 'auto')
            else:
                sc['left']   = 'auto'
                sc['right']  = 'auto'
                sc['top']    = 'auto'
                sc['bottom'] = 'auto'
                sc['margin-top'],  sc['margin-right'],  sc['margin-bottom'],  sc['margin-left']  = 0, 0, 0, 0
                sc['padding-top'], sc['padding-right'], sc['padding-bottom'], sc['padding-left'] = 0, 0, 0, 0
                sc['border-width']        = 0
                sc['border-radius']       = 0
                sc['border-left-color']   = Color.transparent
                sc['border-right-color']  = Color.transparent
                sc['border-top-color']    = Color.transparent
                sc['border-bottom-color'] = Color.transparent
                sc['background-color']    = Color.transparent
                sc['width']  = 'auto'
                sc['height'] = 'auto'

            self._fontid = get_font(
                self._computed_styles.get('font-family', UI_Element_Defaults.font_family),
                self._computed_styles.get('font-style',  UI_Element_Defaults.font_style),
                self._computed_styles.get('font-weight', UI_Element_Defaults.font_weight),
            )
            self._fontsize   = self._computed_styles.get('font-size',   UI_Element_Defaults.font_size).val()
            self._fontcolor  = self._computed_styles.get('color',       UI_Element_Defaults.font_color)
            self._whitespace = self._computed_styles.get('white-space', UI_Element_Defaults.whitespace)
            ts = self._computed_styles.get('text-shadow', 'none')
            self._textshadow = None if ts == 'none' else (ts[0].val(), ts[1].val(), ts[-1])

        # tell children to recompute selector
        # NOTE: self._children_all has not been constructed, yet!
        if self._children:
            for child in self._children: child._compute_style()
        if self._children_text:
            for child in self._children_text: child._compute_style()
        if self._child_before or self._child_after:
            if self._child_before: self._child_before._compute_style()
            if self._child_after:  self._child_after._compute_style()

        with profiler.code('style.hashing for cache'):
            # style changes => content changes
            style_content_hash = Hasher(
                self.is_visible,
                self.src,                                       # image is loaded in compute_content
                self.innerText,                                 # innerText => UI_Elements in compute content
                self._fontid, self._fontsize, self._whitespace, # these properties affect innerText UI_Elements
                self._computed_styles_before.get('content', None) if self._computed_styles_before else None,
                self._computed_styles_after.get('content',  None) if self._computed_styles_after  else None,
            )
            if style_content_hash != getattr(self, '_style_content_hash', None):
                self.dirty_content(cause='style change might have changed content (::before / ::after)')
                self.dirty_renderbuf(cause='style change might have changed content (::before / ::after)')
                # self.dirty(cause='style change might have changed content (::before / ::after)', properties='content')
                # self.dirty(cause='style change might have changed content (::before / ::after)', properties='renderbuf')
                self.dirty_flow(children=False)
                if DEBUG_LIST: self._debug_list.append(f'    possible content change')
                # self._innerTextWrapped = None
                self._style_content_hash = style_content_hash

            # style changes => size changes
            style_size_hash = Hasher(
                self._fontid, self._fontsize, self._whitespace,
                {k:sc[k] for k in [
                    'left', 'right', 'top', 'bottom',
                    'margin-top','margin-right','margin-bottom','margin-left',
                    'padding-top','padding-right','padding-bottom','padding-left',
                    'border-width',
                    'width', 'height',  #'min-width','min-height','max-width','max-height',
                ]},
            )
            if style_size_hash != getattr(self, '_style_size_hash', None):
                self.dirty_size(cause='style change might have changed size')
                self.dirty_renderbuf(cause='style change might have changed size')
                self.dirty_flow(children=False)
                if DEBUG_LIST: self._debug_list.append(f'    possible size change')
                # self._innerTextWrapped = None
                self._style_size_hash = style_size_hash

            # style changes => render changes
            style_render_hash = Hasher(
                self._fontcolor,
                self._computed_styles.get('background-color', None),
                self._computed_styles.get('border-color', None),
            )
            if style_render_hash != getattr(self, '_style_render_hash', None):
                self.dirty_renderbuf(cause='style changed renderbuf')
                self._style_render_hash = style_render_hash

        self._dirty_properties.discard('style')
        self._dirty_properties.discard('style parent')
        self._dirty_callbacks['style'].clear()
        self._dirty_callbacks['style parent'].clear()

        # self.defer_dirty_propagation = False

    @UI_Element_Utils.add_cleaning_callback('content', {'blocks', 'renderbuf'})
    @profiler.function
    def _compute_content(self):
        if self.defer_clean:
            # print('_compute_content: cleaning deferred!')
            return
        if not self.is_visible:
            self._dirty_properties.discard('content')
            # self._innerTextWrapped = None
            # self._innerTextAsIs = None
            return
        if 'content' not in self._dirty_properties:
            for e in self._dirty_callbacks.get('content', []): e._compute_content()
            self._dirty_callbacks['content'].clear()
            return

        self._clean_debugging['content'] = time.time()
        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} content')

        # self.defer_dirty_propagation = True

        content_before = self._computed_styles_before.get('content', None) if self._computed_styles_before else None
        if content_before is not None:
            # TODO: cache this!!
            self._child_before = UI_Element(tagName=self._tagName, innerText=content_before, pseudoelement='before', _parent=self)
            self._child_before.clean()
            self._new_content = True
        else:
            if self._child_before:
                self._child_before = None
                self._new_content = True

        content_after  = self._computed_styles_after.get('content', None)  if self._computed_styles_after  else None
        if content_after is not None:
            # TODO: cache this!!
            self._child_after = UI_Element(tagName=self._tagName, innerText=content_after, pseudoelement='after', _parent=self)
            self._child_after.clean()
            self._new_content = True
        else:
            if self._child_after:
                self._child_after = None
                self._new_content = True

        if self._src and not self.src:
            self._src = None
            self._new_content = True

        if self._innerText is not None:
            # TODO: cache this!!
            textwrap_opts = {
                'dpi':               Globals.drawing.get_dpi_mult(),
                'text':              self._innerText,
                'fontid':            self._fontid,
                'fontsize':          self._fontsize,
                'preserve_newlines': self._whitespace in {'pre', 'pre-line', 'pre-wrap'},
                'collapse_spaces':   self._whitespace in {'normal', 'nowrap', 'pre-line'},
                'wrap_text':         self._whitespace in {'normal', 'pre-wrap', 'pre-line'},
            }
            # TODO: if whitespace:pre, then make self NOT wrap
            innerTextWrapped = helper_wraptext(**textwrap_opts)
            # print('"%s"' % innerTextWrapped)
            # print(self, id(self), self._innerTextWrapped, innerTextWrapped)
            rewrap = False
            rewrap |= self._innerTextWrapped != innerTextWrapped
            rewrap |= any(textwrap_opts[k] != self._textwrap_opts.get(k,None) for k in textwrap_opts.keys())
            if rewrap:
                # print(f'compute content: "{self._innerTextWrapped}" "{innerTextWrapped}"')
                self._textwrap_opts = textwrap_opts
                self._innerTextWrapped = innerTextWrapped
                self._children_text = []
                self._text_map = []
                idx = 0
                for l in self._innerTextWrapped.splitlines():
                    if self._children_text:
                        ui_br = UI_Element(tagName='br', _parent=self)
                        self._children_text.append(ui_br)
                        self._text_map.append({
                            'ui_element': ui_br,
                            'idx': idx,
                            'offset': 0,
                            'char': '\n',
                            'pre': '',
                        })
                        idx += 1
                    if self._whitespace in {'pre', 'nowrap'}:
                        words = [l]
                    else:
                        words = re.split(r'([^ \n]* +)', l)
                    for word in words:
                        if not word: continue
                        word = word.replace('&nbsp;', ' ')
                        ui_word = UI_Element(innerTextAsIs=word, _parent=self)
                        self._children_text.append(ui_word)
                        for i in range(len(word)):
                            self._text_map.append({
                                'ui_element': ui_word,
                                'idx': idx,
                                'offset': i,
                                'char': word[i],
                                'pre': word[:i],
                            })
                        idx += len(word)
                ui_end = UI_Element(innerTextAsIs='', _parent=self)     # needed so cursor can reach end
                self._children_text.append(ui_end)
                self._text_map.append({
                    'ui_element': ui_end,
                    'idx': idx,
                    'offset': 0,
                    'char': '',
                    'pre': '',
                })
                self._children_text_min_size = Size2D(width=0, height=0)
                with profiler.code('cleaning text children'):
                    for child in self._children_text: child.clean()
                    if any(child._static_content_size is None for child in self._children_text):
                        # temporarily set
                        self._children_text_min_size.width = 0
                        self._children_text_min_size.height = 0
                    else:
                        self._children_text_min_size.width  = max(child._static_content_size.width  for child in self._children_text)
                        self._children_text_min_size.height = max(child._static_content_size.height for child in self._children_text)
                self._new_content = True

        elif self.src: # and not self._src:
            with profiler.code('loading image as texture'):
                self._image_data = load_texture(self.src)
            self._src = 'image'

            self._children_text = []
            self._children_text_min_size = None
            self._innerTextWrapped = None
            self._new_content = True

        else:
            if self._children_text:
                self._new_content = True
                self._children_text = []
            self._children_text_min_size = None
            self._innerTextWrapped = None

        # collect all children into self._children_all
        # TODO: cache this!!
        # TODO: some children are "detached" from self (act as if child.parent==root or as if floating)
        self._children_all = []
        if self._child_before:  self._children_all.append(self._child_before)
        if self._children_text: self._children_all += self._children_text
        if self._children:      self._children_all += self._children
        if self._child_after:   self._children_all.append(self._child_after)

        for child in self._children_all: child._compute_content()

        # sort children by z-index
        self._children_all_sorted = sorted(self._children_all, key=lambda e:e.z_index)

        # content changes might have changed size
        if self._new_content:
            self.dirty_blocks(cause='content changes might have affected blocks')
            self.dirty_renderbuf(cause='content changes might have affected blocks')
            self.dirty_flow()
            if DEBUG_LIST: self._debug_list.append(f'    possible new content')
            self._new_content = False
        self._dirty_properties.discard('content')
        self._dirty_callbacks['content'].clear()

        # self.defer_dirty_propagation = False

    @UI_Element_Utils.add_cleaning_callback('blocks', {'size', 'renderbuf'})
    @profiler.function
    def _compute_blocks(self):
        '''
        split up all children into layout blocks

        IMPORTANT: as current written, this function needs to be able to be run multiple times!
                   DO NOT PREVENT THIS, otherwise infinite loop bugs will occur!
        '''

        if self.defer_clean:
            return
        if not self.is_visible:
            self._dirty_properties.discard('blocks')
            return
        if 'blocks' not in self._dirty_properties:
            for e in self._dirty_callbacks.get('blocks', []): e._compute_blocks()
            self._dirty_callbacks['blocks'].clear()
            return

        self._clean_debugging['blocks'] = time.time()
        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} blocks')

        # self.defer_dirty_propagation = True

        for child in self._children_all:
            child._compute_blocks()

        blocks = self._blocks
        if self._computed_styles.get('display', 'inline') == 'flexbox':
            # all children are treated as flex blocks, regardless of their display
            pass
        else:
            # collect children into blocks
            blocks = []
            blocked_inlines = False
            for child in self._children_all:
                d = child._computed_styles.get('display', 'inline')
                if d in {'inline', 'table-cell'}:
                    if not blocked_inlines:
                        blocked_inlines = True
                        blocks.append([child])
                    else:
                        blocks[-1].append(child)
                else:
                    blocked_inlines = False
                    blocks.append([child])

        def same(ll0, ll1):
            if ll0 == None or ll1 == None: return ll0 == ll1
            if len(ll0) != len(ll1): return False
            for i in range(len(ll0)):
                l0, l1 = ll0[i], ll1[i]
                if len(l0) != len(l1): return False
                for j in range(len(l0)):
                    if l0[j] != l1[j]: return False
            return True

        if not same(blocks, self._blocks):
            # content changes might have changed size
            self._blocks = blocks
            self.dirty_size(cause='block changes might have changed size')
            self.dirty_renderbuf(cause='block changes might have changed size')
            self.dirty_flow()
            if DEBUG_LIST: self._debug_list.append(f'    reflowing')

        self._dirty_properties.discard('blocks')
        self._dirty_callbacks['blocks'].clear()

        # self.defer_dirty_propagation = False

    ################################################################################################
    # NOTE: COMPUTE STATIC CONTENT SIZE (TEXT, IMAGE, ETC.), NOT INCLUDING MARGIN, BORDER, PADDING
    #       WE MIGHT NOT NEED TO COMPUTE MIN AND MAX??
    @UI_Element_Utils.add_cleaning_callback('size', {'renderbuf'})
    @profiler.function
    def _compute_static_content_size(self):
        if self.defer_clean:
            return
        if not self.is_visible:
            self._dirty_properties.discard('size')
            return
        if 'size' not in self._dirty_properties:
            for e in self._dirty_callbacks.get('size', []): e._compute_static_content_size()
            self._dirty_callbacks['size'].clear()
            return

        # if self.record_multicall('_compute_static_content_size'): return

        self._clean_debugging['size'] = time.time()
        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} static content size')

        # self.defer_dirty_propagation = True

        with profiler.code('recursing to children'):
            for child in self._children_all:
                child._compute_static_content_size()

        static_content_size = self._static_content_size

        # set size based on content (computed size)
        if self._innerTextAsIs is not None:
            with profiler.code('computing text sizes'):
                # TODO: allow word breaking?
                # size_prev = Globals.drawing.set_font_size(self._textwrap_opts['fontsize'], fontid=self._textwrap_opts['fontid'], force=True)
                size_prev = Globals.drawing.set_font_size(self._parent._fontsize, fontid=self._parent._fontid) #, force=True)
                ts = self._parent._textshadow
                if ts is None: tsx,tsy = 0,0
                else: tsx,tsy,tsc = ts

                # subtract 1/4 width of space to make text look a little nicer
                subw = (Globals.drawing.get_text_width(' ') * 0.25) if self._innerTextAsIs and self._innerTextAsIs[-1] == ' ' else 0

                static_content_size = Size2D()
                static_content_size.set_all_widths(ceil(Globals.drawing.get_text_width(self._innerTextAsIs) - subw) + abs(tsx))
                static_content_size.set_all_heights(ceil(Globals.drawing.get_line_height(self._innerTextAsIs)) + abs(tsy))
                Globals.drawing.set_font_size(size_prev, fontid=self._parent._fontid) #, force=True)
                #print(f'"{self._innerTextAsIs}": {static_content_size.width} x {static_content_size.height}')

        elif self._src == 'image':
            with profiler.code('computing image sizes'):
                # TODO: set to image size?
                dpi_mult = Globals.drawing.get_dpi_mult()
                static_content_size = Size2D()
                static_content_size.set_all_widths(self._image_data['width'] * dpi_mult)
                static_content_size.set_all_heights(self._image_data['height'] * dpi_mult)

        else:
            static_content_size = None

        if static_content_size != self._static_content_size:
            self._static_content_size = static_content_size
            self.dirty_renderbuf(cause='static content changes might change render')
            self.dirty_flow()
            if DEBUG_LIST: self._debug_list.append(f'    reflowing')
        # self.defer_dirty_propagation = False
        self._dirty_properties.discard('size')
        self._dirty_callbacks['size'].clear()

    @UI_Element_Utils.add_cleaning_callback('renderbuf')
    def _renderbuf(self):
        self._dirty_renderbuf = True
        self._dirty_properties.discard('renderbuf')



    @profiler.function
    def _layout(self, **kwargs):
        '''
        layout each block into lines.  if a content box of child element is too wide to fit in line and
        child is not only element on the current line, then end current line, start a new line, relayout the child.
        this function does not set the final position and size for element.

        through this function, we are calculating and committing to a certain width and height
        although the parent element might give us something different.  if we end up with a
        different width and height in self.position() below, we will need to improvise by
        adjusting margin (if bigger) or using scrolling (if smaller)

        TODO: allow for horizontal growth rather than biasing for vertical
        TODO: handle other types of layouts (ex: table, flex)
        TODO: allow for different line alignments (top for now; bottom, baseline)
        TODO: percent_of (style width, height, etc.) could be of last non-static element or document
        TODO: position based on bottom-right,etc.

        NOTE: parent ultimately controls layout and viewing area of child, but uses this layout function to "ask"
              child how much space it would like

        given size might by inf. given can be ignored due to style. constraints applied at end.
        positioning (with definitive size) should happen

        IMPORTANT: as current written, this function needs to be able to be run multiple times!
                   DO NOT PREVENT THIS, otherwise layout bugs will occur!
        '''

        if not self.is_visible:
            return

        #profiler.add_note('laying out %s' % str(self).replace('\n',' ')[:100])

        first_on_line  = kwargs['first_on_line']    # is self the first UI_Element on the current line?
        fitting_size   = kwargs['fitting_size']     # size from parent that we should try to fit in (only max)
        fitting_pos    = kwargs['fitting_pos']      # top-left position wrt parent where we go if not absolute or fixed
        parent_size    = kwargs['parent_size']      # size of inside of parent
        nonstatic_elem = kwargs['nonstatic_elem']   # last non-static element
        document_elem  = kwargs['document_elem']    # whole document element (root)
        table_data     = kwargs['table_data']       # data structure for current table (could be empty)
        first_run      = kwargs['first_run']

        table_elem     = table_data.get('element', None)    # parent table element
        table_index2D  = table_data.get('index2D', None)    # current position in table (i=row,j=col)
        table_cells    = table_data.get('cells', None)      # cells of table as tuples (element, size)

        styles       = self._computed_styles
        style_pos    = styles.get('position', 'static')

        self._fitting_pos = fitting_pos
        self._fitting_size = fitting_size
        self._parent_size = parent_size
        self._absolute_pos = None
        self._document_elem = document_elem
        self._nonstatic_elem = nonstatic_elem
        self._tablecell_table = None
        self._tablecell_pos = None
        self._tablecell_size = None

        self.update_position()

        if not self._dirtying_flow and not self._dirtying_children_flow and not table_data:
            return

        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} layout self={self._dirtying_flow} children={self._dirtying_children_flow} first_run={first_run} fitting_size={fitting_size}')

        if self._dirtying_children_flow:
            for child in self._children_all:
                child.dirty_flow(parent=False)
            if DEBUG_LIST: self._debug_list.append(f'    reflowing children')
            self._dirtying_children_flow = False

        self._all_lines = None

        self._clean_debugging['layout'] = time.time()

        dpi_mult      = Globals.drawing.get_dpi_mult()
        display       = styles.get('display', 'block')
        is_nonstatic  = style_pos in {'absolute','relative','fixed','sticky'}
        is_contribute = style_pos not in {'absolute', 'fixed'}
        next_nonstatic_elem = self if is_nonstatic else nonstatic_elem
        parent_width  = parent_size.get_width_midmaxmin()  or 0
        parent_height = parent_size.get_height_midmaxmin() or 0
        # --> NOTE: width,height,min_*,max_* could be 'auto'!
        width         = self._get_style_num('width',      def_v='auto', percent_of=parent_width,  scale=dpi_mult) # override_v=self._style_width)
        height        = self._get_style_num('height',     def_v='auto', percent_of=parent_height, scale=dpi_mult) # override_v=self._style_height)
        min_width     = self._get_style_num('min-width',  def_v='auto', percent_of=parent_width,  scale=dpi_mult)
        min_height    = self._get_style_num('min-height', def_v='auto', percent_of=parent_height, scale=dpi_mult)
        max_width     = self._get_style_num('max-width',  def_v='auto', percent_of=parent_width,  scale=dpi_mult)
        max_height    = self._get_style_num('max-height', def_v='auto', percent_of=parent_height, scale=dpi_mult)
        overflow_x    = styles.get('overflow-x', 'visible')
        overflow_y    = styles.get('overflow-y', 'visible')

        # border_width  = self._get_style_num('border-width', 0, scale=dpi_mult)
        # margin_top,  margin_right,  margin_bottom,  margin_left  = self._get_style_trbl('margin',  scale=dpi_mult)
        # padding_top, padding_right, padding_bottom, padding_left = self._get_style_trbl('padding', scale=dpi_mult)
        sc = self._style_cache
        margin_top,  margin_right,  margin_bottom,  margin_left  = sc['margin-top'],  sc['margin-right'],  sc['margin-bottom'],  sc['margin-left']
        padding_top, padding_right, padding_bottom, padding_left = sc['padding-top'], sc['padding-right'], sc['padding-bottom'], sc['padding-left']
        border_width = sc['border-width']
        mbp_left   = (margin_left    + border_width + padding_left)
        mbp_right  = (padding_right  + border_width + margin_right)
        mbp_top    = (margin_top     + border_width + padding_top)
        mbp_bottom = (padding_bottom + border_width + margin_bottom)
        mbp_width  = mbp_left + mbp_right
        mbp_height = mbp_top  + mbp_bottom

        self._mbp_left = mbp_left
        self._mbp_top = mbp_top
        self._mbp_right = mbp_right
        self._mbp_bottom = mbp_bottom
        self._mbp_width = mbp_width
        self._mbp_height = mbp_height

        self._computed_min_width  = min_width
        self._computed_min_height = min_height
        self._computed_max_width  = max_width
        self._computed_max_height = max_height

        inside_size = Size2D()
        if fitting_size.max_width  is not None: inside_size.max_width  = max(0, fitting_size.max_width  - mbp_width)
        if fitting_size.max_height is not None: inside_size.max_height = max(0, fitting_size.max_height - mbp_height)
        if width      != 'auto': inside_size.width      = max(0, width      - mbp_width)
        if height     != 'auto': inside_size.height     = max(0, height     - mbp_height)
        if max_width  != 'auto': inside_size.max_width  = max(0, max_width  - mbp_width)
        if max_height != 'auto': inside_size.max_height = max(0, max_height - mbp_height)
        if min_width  != 'auto': inside_size.min_width  = max(0, min_width  - mbp_width)
        if min_height != 'auto': inside_size.min_height = max(0, min_height - mbp_height)

        inside_size.width      = floor_if_finite(inside_size.width)
        inside_size.height     = floor_if_finite(inside_size.height)
        inside_size.max_width  = floor_if_finite(inside_size.max_width)
        inside_size.max_height = floor_if_finite(inside_size.max_height)
        inside_size.min_width  = floor_if_finite(inside_size.min_width)
        inside_size.min_height = floor_if_finite(inside_size.min_height)

        if self._static_content_size:
            # self has static content size
            # self has no children
            dw = self._static_content_size.width
            dh = self._static_content_size.height

            if self._src == 'image':
                def scale_dw_dh(num, den):
                    nonlocal dw,dh
                    sc = 0 if den == 0 else num / den
                    dw,dh = dw*sc,dh*sc
                # image will scale based on inside_size
                if inside_size.max_width  is not None and dw > inside_size.max_width:  scale_dw_dh(inside_size.max_width,  dw)
                if inside_size.width      is not None:                                 scale_dw_dh(inside_size.width,      dw)
                if inside_size.min_width  is not None and dw < inside_size.min_width:  scale_dw_dh(inside_size.min_width,  dw)
                if inside_size.max_height is not None and dw > inside_size.max_height: scale_dw_dh(inside_size.max_height, dh)
                if inside_size.height     is not None:                                 scale_dw_dh(inside_size.height,     dh)
                if inside_size.min_height is not None and dw < inside_size.min_height: scale_dw_dh(inside_size.min_height, dh)

        elif self._blocks:
            # self has no static content, so flow and size is determined from children
            # note: will keep track of accumulated size and possibly update inside size as needed
            # note: style size overrides passed fitting size
            if self._innerText is not None and self._whitespace in {'nowrap', 'pre'}:
                inside_size.min_width = inside_size.width = inside_size.max_width = float('inf')

            if display == 'table':
                table_elem = self
                table_index2D = Index2D(0, 0)
                table_cells = {}
                table_data = { 'elem': table_elem, 'index2D': table_index2D, 'cells': table_cells }

            working_width = (inside_size.width  if inside_size.width  is not None else (inside_size.max_width  if inside_size.max_width  is not None else float('inf')))
            working_height = (inside_size.height if inside_size.height is not None else (inside_size.max_height if inside_size.max_height is not None else float('inf')))
            if overflow_y in {'scroll', 'auto'}: working_height = float('inf')

            accum_lines, accum_width, accum_height = [], 0, 0
            # accum_width: max width for all lines;  accum_height: sum heights for all lines
            cur_line, cur_width, cur_height = [], 0, 0
            for block in self._blocks:
                # each block might be wrapped onto multiple lines
                cur_line, cur_width, cur_height = [], 0, 0
                for element in block:
                    if not element.is_visible: continue
                    position = element._computed_styles.get('position', 'static')
                    c = position not in {'absolute', 'fixed'}
                    sx = element._computed_styles.get('overflow-x', 'visible')
                    sy = element._computed_styles.get('overflow-y', 'visible')
                    while True:
                        rw, rh = working_width - cur_width, working_height - accum_height
                        remaining = Size2D(max_width=rw, max_height=rh)
                        pos = Point2D((mbp_left + cur_width, -(mbp_top + accum_height)))
                        element._layout(
                            first_on_line=(not cur_line),
                            fitting_size=remaining,
                            fitting_pos=pos,
                            parent_size=inside_size,
                            nonstatic_elem=next_nonstatic_elem,
                            document_elem=document_elem,
                            table_data=table_data,
                            first_run=first_run,
                        )
                        w, h = math.ceil(element._dynamic_full_size.width), math.ceil(element._dynamic_full_size.height)
                        element_fits = False
                        element_fits |= not cur_line                 # always add child to an empty line
                        element_fits |= c and w<=rw and h<=rh        # child fits on current line
                        element_fits |= not c                        # child does not contribute to our size
                        element_fits |= self._innerText is not None and self._whitespace in {'nowrap', 'pre'}
                        if element_fits:
                            if c: cur_line.append(element)
                            # clamp width and height only if scrolling (respectively)
                            if sx == 'scroll': w = remaining.clamp_width(w)
                            if sy == 'scroll': h = remaining.clamp_height(h)
                            w, h = math.ceil(w), math.ceil(h)
                            sz = Size2D(width=w, height=h)
                            element.set_view_size(sz)
                            if position != 'fixed':
                                cur_width += w
                                cur_height = max(cur_height, h)
                            break # done processing current element
                        else:
                            # element does not fit!  finish of current line, then reprocess current element
                            accum_lines.append((cur_line, cur_width, cur_height))
                            accum_height += cur_height
                            accum_width = max(accum_width, cur_width)
                            cur_line, cur_width, cur_height = [], 0, 0
                            element.dirty_flow(parent=False, children=True)
                if cur_line:
                    accum_lines.append((cur_line, cur_width, cur_height))
                    accum_height += cur_height
                    accum_width = max(accum_width, cur_width)
            self._all_lines = accum_lines
            dw = accum_width
            dh = accum_height

        else:
            dw = 0
            dh = 0

        # possibly override with text size
        if self._children_text_min_size:
            dw = max(dw, self._children_text_min_size.width)
            dh = max(dh, self._children_text_min_size.height)

        self._dynamic_content_size = Size2D(width=dw, height=dh)

        dw += mbp_width
        dh += mbp_height

        # override with style settings
        if width      != 'auto': dw = width
        if height     != 'auto': dh = height
        if min_width  != 'auto': dw = max(min_width,  dw)
        if min_height != 'auto': dh = max(min_height, dh)
        if max_width  != 'auto': dw = min(max_width,  dw)
        if max_height != 'auto': dh = min(max_height, dh)

        self._dynamic_full_size = Size2D(width=math.ceil(dw), height=math.ceil(dh))
        # if self._tagName == 'body': print(self._dynamic_content_size, self._dynamic_full_size)

        # handle table elements
        if display == 'table-row':
            table_index2D.update(i=0, j_off=1)
        elif display == 'table-cell':
            idx = table_index2D.to_tuple()
            table_cells[idx] = (self, self._dynamic_full_size)
            table_index2D.update(i_off=1)
        elif display == 'table':
            inds = table_cells.keys()
            ind_is = sorted({ i for (i,j) in inds })
            ind_js = sorted({ j for (i,j) in inds })
            ind_is_js = { i:sorted({ j for (_i,j) in inds if i==_i }) for i in ind_is }
            ind_js_is = { j:sorted({ i for (i,_j) in inds if j==_j }) for j in ind_js }
            ws = { i:max(table_cells[(i,j)][1].width  for j in ind_is_js[i]) for i in ind_is }
            hs = { j:max(table_cells[(i,j)][1].height for i in ind_js_is[j]) for j in ind_js }
            # override dynamic full size
            px,py = mbp_left,mbp_top
            for i in ind_is:
                for j in ind_is_js[i]:
                    element = table_cells[(i,j)][0]
                    element._tablecell_table = self
                    element._tablecell_pos = RelPoint2D((px, -py))
                    element._tablecell_size = Size2D(width=ws[i], height=hs[j])
                    py += hs[j]
                px += ws[i]
                py = mbp_top
            fw = sum(ws.values())
            fh = sum(hs.values())
            self._dynamic_content_size = Size2D(width=fw, height=fh)
            self._dynamic_full_size = Size2D(width=math.ceil(fw+mbp_width), height=math.ceil(fh+mbp_height))

        self._tmp_max_width = max_width

        # reposition
        self.update_position()

        self._dirtying_flow = False
        self._dirtying_children_flow = False

    @profiler.function
    def update_position(self):
        styles    = self._computed_styles
        style_pos = styles.get('position', 'static')
        pl,pt     = self.left_pixels,self.top_pixels
        dpi_mult = Globals.drawing.get_dpi_mult()

        # cache elements to determine if anything changed
        relative_element = self._relative_element
        relative_pos     = self._relative_pos
        relative_offset  = self._relative_offset

        # position element
        if self._tablecell_table:
            relative_element = self._tablecell_table
            relative_pos = RelPoint2D(self._tablecell_pos)
            relative_offset = RelPoint2D((0, 0))

        elif style_pos in {'fixed', 'absolute'}:
            relative_element = self._document_elem if style_pos == 'fixed' else self._nonstatic_elem
            if relative_element is None or relative_element == self:
                mbp_left = mbp_top = 0
            else:
                mbp_left = relative_element._mbp_left
                mbp_top = relative_element._mbp_top
            if pl == 'auto': pl = 0
            if pt == 'auto': pt = 0
            if relative_element is not None and relative_element != self and self._clamp_to_parent:
                parent_width  = self._parent_size.get_width_midmaxmin()  or 0
                parent_height = self._parent_size.get_height_midmaxmin() or 0
                width         = self._get_style_num('width',  def_v='auto', percent_of=parent_width,  scale=dpi_mult)
                height        = self._get_style_num('height', def_v='auto', percent_of=parent_height, scale=dpi_mult)
                w = width  if width  != 'auto' else (self.width_pixels  if self.width_pixels  != 'auto' else 0)
                h = height if height != 'auto' else (self.height_pixels if self.height_pixels != 'auto' else 0)
                pl = clamp(pl, 0, relative_element.width_pixels - relative_element._mbp_width - w)
                pt = clamp(pt, -(relative_element.height_pixels - relative_element._mbp_height - h), 0)
                # pt = clamp(pt, h + relative_element._mbp_bottom, relative_element.height_pixels - relative_element._mbp_top)
            relative_pos = RelPoint2D((pl, pt))
            relative_offset = RelPoint2D((mbp_left, -mbp_top))

        elif style_pos == 'relative':
            if pl == 'auto': pl = 0
            if pt == 'auto': pt = 0
            relative_element = self._parent
            relative_pos = RelPoint2D(self._fitting_pos)
            relative_offset = RelPoint2D((pl, pt))

        else:
            relative_element = self._parent
            relative_pos = RelPoint2D(self._fitting_pos)
            relative_offset = RelPoint2D((0, 0))

        # has anything changed?
        changed = False
        changed |= relative_element != self._relative_element
        changed |= relative_pos     != self._relative_pos
        changed |= relative_offset  != self._relative_offset
        if changed:
            self._relative_element = relative_element
            self._relative_pos     = relative_pos
            self._relative_offset  = relative_offset
            self._alignment_offset = None
            self.dirty_renderbuf(cause='position changed')

    @profiler.function
    def set_view_size(self, size:Size2D):
        # parent is telling us how big we will be.  note: this does not trigger a reflow!
        # TODO: clamp scroll
        # TODO: handle vertical and horizontal element alignment
        # TODO: handle justified and right text alignment
        if self.width_override is not None or self.height_override is not None:
            size = size.clone()
            if self.width_override  is not None: size.set_all_widths( self.width_override)
            if self.height_override is not None: size.set_all_heights(self.height_override)
        self._absolute_size = size
        self.scrollLeft = self.scrollLeft
        self.scrollTop = self.scrollTop

        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} set_view_size({size})')

        if self._all_lines:
            w = size.width - self._mbp_width
            nlines = len(self._all_lines)
            align = self._computed_styles.get("text-align", "left")
            for i_line, (line, line_width, line_height) in enumerate(self._all_lines):
                if i_line == nlines - 1:
                    # override justify text alignment, unless CSS explicitly specifies
                    align = self._computed_styles.get("text-align-last", 'left' if align == 'justify' else align)

                offset_x, offset_between = 0, 0
                if   align == 'right':   offset_x = w - line_width
                elif align == 'center':  offset_x = (w - line_width) / 2
                elif align == 'justify': offset_between = (w - line_width) / len(line)
                #if offset_x <= 0 and offset_between <= 0: continue
                offset_x = Vec2D((offset_x, 0))
                offset_between = Vec2D((offset_between, 0))
                for i,el in enumerate(line):
                    el._alignment_offset = offset_x + offset_between * i

        #if self._src_str:
        #    print(self._src_str, self._dynamic_full_size, self._dynamic_content_size, self._absolute_size)

    @UI_Element_Utils.add_option_callback('layout:flexbox')
    def layout_flexbox(self):
        style = self._computed_styles
        direction = style.get('flex-direction', 'row')
        wrap = style.get('flex-wrap', 'nowrap')
        justify = style.get('justify-content', 'flex-start')
        align_items = style.get('align-items', 'flex-start')
        align_content = style.get('align-content', 'flex-start')

    @UI_Element_Utils.add_option_callback('layout:block')
    def layout_block(self):
        pass

    @UI_Element_Utils.add_option_callback('layout:inline')
    def layout_inline(self):
        pass

    @UI_Element_Utils.add_option_callback('layout:none')
    def layout_none(self):
        pass


    # @UI_Element_Utils.add_option_callback('position:flexbox')
    # def position_flexbox(self, left, top, width, height):
    #     pass
    # @UI_Element_Utils.add_option_callback('position:block')
    # def position_flexbox(self, left, top, width, height):
    #     pass
    # @UI_Element_Utils.add_option_callback('position:inline')
    # def position_flexbox(self, left, top, width, height):
    #     pass
    # @UI_Element_Utils.add_option_callback('position:none')
    # def position_flexbox(self, left, top, width, height):
    #     pass


    # def position(self, left, top, width, height):
    #     # pos and size define where this element exists
    #     self._l, self._t = left, top
    #     self._w, self._h = width, height

    #     dpi_mult = Globals.drawing.get_dpi_mult()
    #     display = self._computed_styles.get('display', 'block')
    #     margin_top, margin_right, margin_bottom, margin_left = self._get_style_trbl('margin')
    #     padding_top, padding_right, padding_bottom, padding_left = self._get_style_trbl('padding')
    #     border_width = self._get_style_num('border-width', 0)

    #     l = left   + dpi_mult * (margin_left + border_width  + padding_left)
    #     t = top    - dpi_mult * (margin_top  + border_width  + padding_top)
    #     w = width  - dpi_mult * (margin_left + margin_right  + border_width + border_width + padding_left + padding_right)
    #     h = height - dpi_mult * (margin_top  + margin_bottom + border_width + border_width + padding_top  + padding_bottom)

    #     self.call_option_callback(('position:%s' % display), 'position:block', left, top, width, height)

    #     # wrap text
    #     wrap_opts = {
    #         'text':     self._innerText,
    #         'width':    w,
    #         'fontid':   self._fontid,
    #         'fontsize': self._fontsize,
    #         'preserve_newlines': (self._whitespace in {'pre', 'pre-line', 'pre-wrap'}),
    #         'collapse_spaces':   (self._whitespace not in {'pre', 'pre-wrap'}),
    #         'wrap_text':         (self._whitespace != 'pre'),
    #     }
    #     self._innerTextWrapped = helper_wraptext(**wrap_opts)

    @property
    def absolute_pos(self):
        return self._absolute_pos

    @profiler.function
    def _setup_ltwh(self, recurse_children=True):
        if not self.is_visible: return

        if not self._parent_size: return    # layout has not been called yet....

        # IMPORTANT! do NOT prevent this function from being called multiple times!
        # the position of input text boxes (inside the container) is set incorrectly when
        # :focus is set (might have to do with position: relative)

        # parent_pos = self._parent.absolute_pos if self._parent else Point2D((0, self._parent_size.max_height-1))
        if self._tablecell_table:
            table_pos = self._tablecell_table.absolute_pos
            # rel_pos = self._relative_pos or RelPoint2D.ZERO
            # rel_offset = self._relative_offset or RelPoint2D.ZERO
            abs_pos = table_pos + self._tablecell_pos
            abs_size = self._tablecell_size
        else:
            parent_pos = self._relative_element.absolute_pos if self._relative_element and self._relative_element != self else Point2D((0, self._parent_size.max_height - 1))
            if not parent_pos: parent_pos = RelPoint2D.ZERO
            rel_pos = self._relative_pos or RelPoint2D.ZERO
            rel_offset = self._relative_offset or RelPoint2D.ZERO
            align_offset = self._alignment_offset or RelPoint2D.ZERO
            abs_pos = parent_pos + rel_pos + rel_offset + align_offset
            abs_size = self._absolute_size

        self._absolute_pos = abs_pos + self._scroll_offset
        self._l = ceil_if_finite(abs_pos.x - 0.01)
        self._t = floor_if_finite(abs_pos.y + 0.01)
        self._w = ceil_if_finite(abs_size.width)
        self._h = ceil_if_finite(abs_size.height)
        self._r = ceil_if_finite(self._l + (self._w - 0.01))
        self._b = floor_if_finite(self._t - (self._h - 0.01))

        if recurse_children:
            for child in self._children_all:
                child._setup_ltwh()

    def _draw_real(self, offset, scissor_include_margin=True, scissor_include_padding=True):
        dpi_mult = Globals.drawing.get_dpi_mult()
        ox,oy = offset

        if DEBUG_COLOR_CLEAN:
            if DEBUG_COLOR == 0:
                t_max = 2
                t = max(0, t_max - (time.time() - self._clean_debugging.get(DEBUG_PROPERTY, 0))) / t_max
                background_override = Color( ( t, t/2, 0, 0.75 ) )
            elif DEBUG_COLOR == 1:
                t = self._clean_debugging.get(DEBUG_PROPERTY, 0)
                d = time.time() - t
                h = (t / 2) % 1
                s = 1.0
                l = max(0, 0.5 - d / 10)
                background_override = Color.HSL((h, s, l, 0.75))
        else:
            background_override = None

        bgl.glEnable(bgl.GL_BLEND)
        # bgl.glBlendFunc(bgl.GL_SRC_ALPHA, bgl.GL_ONE_MINUS_SRC_ALPHA)

        sc = self._style_cache
        margin_top,  margin_right,  margin_bottom,  margin_left  = sc['margin-top'],  sc['margin-right'],  sc['margin-bottom'],  sc['margin-left']
        padding_top, padding_right, padding_bottom, padding_left = sc['padding-top'], sc['padding-right'], sc['padding-bottom'], sc['padding-left']
        border_width = sc['border-width']

        ol, ot = int(self._l + ox), int(self._t + oy)

        with profiler.code('drawing mbp'):
            texture_id = self._image_data['texid'] if self._src == 'image' else -1
            texture_fit = self._computed_styles.get('object-fit', 'fill')
            ui_draw.draw(ol, ot, self._w, self._h, dpi_mult, self._style_cache, texture_id, texture_fit, background_override=background_override)

        with profiler.code('drawing children'):
            # compute inner scissor area
            mt,mr,mb,ml = (margin_top, margin_right, margin_bottom, margin_left)  if scissor_include_margin  else (0,0,0,0)
            pt,pr,pb,pl = (padding_top,padding_right,padding_bottom,padding_left) if scissor_include_padding else (0,0,0,0)
            bw = border_width
            il = round(self._l + (ml + bw + pl) + ox)
            it = round(self._t - (mt + bw + pt) + oy)
            iw = round(self._w - ((ml + bw + pl) + (pr + bw + mr)))
            ih = round(self._h - ((mt + bw + pt) + (pb + bw + mb)))

            with ScissorStack.wrap(il, it, iw, ih, msg=f'{self} mbp'):
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
                    # bgl.glBlendFunc(bgl.GL_SRC_ALPHA, bgl.GL_ONE_MINUS_SRC_ALPHA)
                    Globals.drawing.text_draw2D_simple(self._innerTextAsIs, (ol, ot))
                else:
                    for child in self._children_all_sorted:
                        bgl.glEnable(bgl.GL_BLEND)
                        # bgl.glBlendFunc(bgl.GL_SRC_ALPHA, bgl.GL_ONE_MINUS_SRC_ALPHA)
                        child._draw(offset)

    dfactors = [
        bgl.GL_ZERO,
        bgl.GL_ONE,
        bgl.GL_SRC_COLOR,
        bgl.GL_ONE_MINUS_SRC_COLOR,
        bgl.GL_DST_COLOR,
        bgl.GL_ONE_MINUS_DST_COLOR,
        bgl.GL_SRC_ALPHA,
        bgl.GL_ONE_MINUS_SRC_ALPHA,
        bgl.GL_DST_ALPHA,
        bgl.GL_ONE_MINUS_DST_ALPHA,
        bgl.GL_CONSTANT_COLOR,
        bgl.GL_ONE_MINUS_CONSTANT_COLOR,
        bgl.GL_CONSTANT_ALPHA,
        bgl.GL_ONE_MINUS_CONSTANT_ALPHA,
    ]
    def _draw_cache(self, offset):
        ox,oy = offset
        with ScissorStack.wrap(self._l+ox, self._t+oy, self._w, self._h):
            if self._cacheRenderBuf:
                bgl.glEnable(bgl.GL_BLEND)
                bgl.glBlendFunc(bgl.GL_ONE, bgl.GL_ONE_MINUS_SRC_ALPHA)
                texture_id = self._cacheRenderBuf.color_texture
                if True:
                    draw_texture_2d(texture_id, (self._l+ox, self._b+oy), self._w, self._h)
                else:
                    dpi_mult = Globals.drawing.get_dpi_mult()
                    texture_fit = 0
                    background_override = None
                    ui_draw.draw(self._l+ox, self._t+oy, self._w, self._h, dpi_mult, {
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
                        }, texture_id, texture_fit, background_override=background_override)
            else:
                bgl.glBlendFunc(bgl.GL_ONE, bgl.GL_ONE_MINUS_SRC_ALPHA)
                self._draw_real(offset)

    def _cache_create(self):
        if self._w < 1 or self._h < 1: return
        # (re-)create off-screen buffer
        if self._cacheRenderBuf:
            # already have a render buffer, so just resize it
            self._cacheRenderBuf.resize(self._w, self._h)
        else:
            # do not already have a render buffer, so create one
            self._cacheRenderBuf = FrameBuffer.new(self._w, self._h)

    def _cache_hierarchical(self, depth):
        if self._innerTextAsIs is not None: return   # do not cache this low level!
        if self._innerText is not None: return

        # make sure children are all cached (if applicable)
        for child in self._children_all_sorted:
            child._cache(depth=depth+1)

        self._cache_create()

        sl, st, sw, sh = 0, self._h - 1, self._w, self._h
        bgl.glClearColor(0,0,0,0)
        with self._cacheRenderBuf.bind_unbind():
            self._draw_real((-self._l, -self._b))
            # with ScissorStack.wrap(sl, st, sw, sh, clamp=False):
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
        with self._cacheRenderBuf.bind_unbind():
            self._draw_real((-self._l, -self._b))
            # with ScissorStack.wrap(sl, st, sw, sh, clamp=False):
            #     self._draw_real((-self._l, -self._b))

    def _cache_onlyroot(self, depth):
        self._cache_create()
        with self._cacheRenderBuf.bind_unbind():
            self._draw_real((0,0))

    @profiler.function
    def _cache(self, depth=0):
        if not self.is_visible: return
        if self._w <= 0 or self._h <= 0: return

        if not self._dirty_renderbuf: return   # no need to cache
        # print('caching %s' % str(self))

        if   CACHE_METHOD == 0: pass # do not cache
        elif CACHE_METHOD == 1: self._cache_onlyroot(depth)
        elif CACHE_METHOD == 2: self._cache_hierarchical(depth)
        elif CACHE_METHOD == 3: self._cache_textleaves(depth)

        self._dirty_renderbuf = False

    @profiler.function
    def _draw(self, offset=(0,0)):
        if not self.is_visible: return
        if self._w <= 0 or self._h <= 0: return
        # if self._draw_dirty_style > 1: print(self, self._draw_dirty_style)
        ox,oy = offset
        if not ScissorStack.is_box_visible(self._l+ox, self._t+oy, self._w, self._h): return
        # print('drawing %s' % str(self))
        self._draw_cache(offset)
        self._draw_dirty_style = 0

    def draw(self):
        # Globals.drawing.glCheckError('UI_Element.draw: start')
        bgl.glBlendFunc(bgl.GL_ONE, bgl.GL_ONE_MINUS_SRC_ALPHA)
        # Globals.drawing.glCheckError('UI_Element.draw: setup ltwh')
        self._setup_ltwh()
        # Globals.drawing.glCheckError('UI_Element.draw: cache')
        self._cache()
        # Globals.drawing.glCheckError('UI_Element.draw: draw')
        self._draw()
        # Globals.drawing.glCheckError('UI_Element.draw: done')

    def _draw_vscroll(self, depth=0):
        if not self.is_visible: return
        if not ScissorStack.is_box_visible(self._l, self._t, self._w, self._h): return
        if self._w <= 0 or self._h <= 0: return
        vscroll = max(0, self._dynamic_full_size.height - self._h)
        if vscroll < 1: return
        with ScissorStack.wrap(self._l, self._t, self._w, self._h, msg=str(self)):
            with profiler.code('drawing scrollbar'):
                bgl.glEnable(bgl.GL_BLEND)
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


    @profiler.function
    def get_under_mouse(self, p:Point2D):
        if not self.is_visible: return None
        if not self.can_hover: return None
        if self._w < 1 or self._h < 1: return None
        if not (self._l <= p.x <= self._r and self._b <= p.y <= self._t): return None
        if not self._atomic:
            iter_under = (child.get_under_mouse(p) for child in reversed(self._children))
            iter_under = dropwhile(lambda r: r is None, iter_under)
            under = next(iter_under, self)
            return under
        return self

    def get_mouse_distance(self, p:Point2D):
        l,t,w,h = self._l, self._t, self._w, self._h
        r,b = l+(w-1),t-(h-1)
        dx = p.x - clamp(p.x, l, r)
        dy = p.y - clamp(p.y, b, t)
        return math.sqrt(dx*dx + dy*dy)



    ################################################################################
    # event-related functionality

    def add_eventListener(self, event, callback, useCapture=False):
        assert event in self._events, 'Attempting to add unhandled event handler type "%s"' % event
        sig = signature(callback)
        old_callback = callback
        if len(sig.parameters) == 0:
            callback = lambda e: old_callback()
        self._events[event] += [(useCapture, callback, old_callback)]

    def remove_eventListener(self, event, callback):
        # returns True if callback was successfully removed
        assert event in self._events, 'Attempting to remove unhandled event handler type "%s"' % event
        l = len(self._events[event])
        self._events[event] = [(capture,cb,old_cb) for (capture,cb,old_cb) in self._events[event] if old_cb != callback]
        return l != len(self._events[event])

    def _fire_event(self, event, details):
        ph = details.event_phase
        cap, bub, df = details.capturing, details.bubbling, not details.default_prevented
        if (cap and ph == 'capturing') or (df and ph == 'at target'):
            for (cap,cb,old_cb) in self._events[event]:
                if cap: cb(details)
        if (bub and ph == 'bubbling') or (df and ph == 'at target'):
            for (cap,cb,old_cb) in self._events[event]:
                if not cap: cb(details)

    @profiler.function
    def dispatch_event(self, event, mouse=None, button=None, key=None, ui_event=None, stop_at=None):
        if self._document:
            if mouse is None:
                mouse = self._document.actions.mouse
            if button is None:
                button = (
                    self._document.actions.using('LEFTMOUSE'),
                    self._document.actions.using('MIDDLEMOUSE'),
                    self._document.actions.using('RIGHTMOUSE')
                )
        # else:
        #     if mouse is None or button is None:
        #         print(f'UI_Element.dispatch_event: {event} dispatched on {self}, but self.document = {self.document}  (root={self.get_root()}')
        if ui_event is None: ui_event = UI_Event(target=self, mouse=mouse, button=button, key=key)
        path = self.get_pathToRoot()[1:] # skipping first item, which is self
        if stop_at is not None and stop_at in path:
            path = path[:path.index(stop_at)]
        ui_event.event_phase = 'capturing'
        for cur in path[::-1]:
            cur._fire_event(event, ui_event)
            if not ui_event.capturing: return ui_event.default_prevented
        ui_event.event_phase = 'at target'
        self._fire_event(event, ui_event)
        ui_event.event_phase = 'bubbling'
        if not ui_event.bubbling: return ui_event.default_prevented
        for cur in path:
            cur._fire_event(event, ui_event)
            if not ui_event.bubbling: return ui_event.default_prevented
        return ui_event.default_prevented



