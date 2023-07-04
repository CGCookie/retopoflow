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
import re
import sys
import math
import time
import random
import inspect
import traceback
import contextlib
from math import floor, ceil
from inspect import signature
from functools import lru_cache
from itertools import dropwhile, zip_longest

import bpy
import blf
import gpu


from gpu_extras.presets import draw_texture_2d
from mathutils import Vector, Matrix

from .blender import tag_redraw_all
from .fsm import FSM

from .boundvar import BoundVar
from .colors import colorname_to_color
from .debug import debugger, dprint, tprint
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .drawing import Drawing
from .globals import Globals
from .hasher import Hasher
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .maths import floor_if_finite, ceil_if_finite
from .profiler import profiler, time_it
from .utils import iter_head, any_args, join

from ..ext import png
from ..ext.apng import APNG



'''
Links to useful resources

- How Browsers Work: https://www.html5rocks.com/en/tutorials/internals/howbrowserswork
- WebCore Rendering
    - https://webkit.org/blog/114/webcore-rendering-i-the-basics/
    - https://webkit.org/blog/115/webcore-rendering-ii-blocks-and-inlines/
    - https://webkit.org/blog/116/webcore-rendering-iii-layout-basics/
    - https://webkit.org/blog/117/webcore-rendering-iv-absolutefixed-and-relative-positioning/
    - https://webkit.org/blog/118/webcore-rendering-v-floats/
- Mozilla's Layout Engine: https://www-archive.mozilla.org/newlayout/doc/layout-2006-12-14/master.xhtml
- Mozilla's Notes on HTML Reflow: https://www-archive.mozilla.org/newlayout/doc/reflow.html
- How Browser Rendering Works: http://dbaron.github.io/browser-rendering/
- Render-tree Construction, Layout, and Paint: https://developers.google.com/web/fundamentals/performance/critical-rendering-path/render-tree-construction
- Beginner's Guide to Choose Between CSS Grid and Flexbox: https://medium.com/youstart-labs/beginners-guide-to-choose-between-css-grid-and-flexbox-783005dd2412
'''






class UI_Core_Utils:
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
            UI_Core_Utils._option_callbacks[option] = wrapped
            return wrapped
        return wrapper

    def call_option_callback(self, option, default, *args, **kwargs):
        option = option if option not in UI_Core_Utils._option_callbacks else default
        UI_Core_Utils._option_callbacks[option](self, *args, **kwargs)

    _cleaning_graph = {}
    _cleaning_graph_roots = set()
    _cleaning_graph_nodes = set()
    @staticmethod
    def add_cleaning_callback(label, labels_dirtied=None):
        # NOTE: this function decorator does NOT call self.dirty!
        UI_Core_Utils._cleaning_graph_nodes.add(label)
        g = UI_Core_Utils._cleaning_graph
        labels_dirtied = list(labels_dirtied) if labels_dirtied else []
        for l in [label]+labels_dirtied: g.setdefault(l, {'fn':None, 'children':[], 'parents':[]})
        def wrapper(fn):
            g[label]['name'] = label
            g[label]['fn'] = fn
            g[label]['children'] = labels_dirtied
            for l in labels_dirtied: g[l]['parents'].append(label)

            # find roots of graph (any label that is not dirtied by another cleaning callback)
            UI_Core_Utils._cleaning_graph_roots = set(k for (k,v) in g.items() if not v['parents'])
            assert UI_Core_Utils._cleaning_graph_roots, 'cycle detected in cleaning callbacks'
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




###########################################################################
# below is a helper class for drawing ui



class UIRender:
    def __init__(self):
        self._children = []
    def append_child(self, child):
        self._children.append(child)

class UIRender_Block(UIRender):
    def __init__(self):
        super.__init__(self)

class UIRender_Inline(UIRender):
    def __init__(self):
        super.__init__(self)



# dictionary to convert cursor name to Blender cursor enum
# https://docs.blender.org/api/blender2.8/bpy.types.Window.html#bpy.types.Window.cursor_modal_set
#   DEFAULT, NONE, WAIT, HAND,
#   CROSSHAIR, TEXT,
#   PAINT_BRUSH, EYEDROPPER, KNIFE,
#   MOVE_X, MOVE_Y,
#   SCROLL_X, SCROLL_Y, SCROLL_XY
cursorname_to_cursor = {
    'default': 'DEFAULT', 'auto': 'DEFAULT', 'initial': 'DEFAULT',
    'none': 'NONE',
    'wait': 'WAIT',
    'grab': 'HAND',
    'crosshair': 'CROSSHAIR', 'pointer': 'CROSSHAIR',
    'text': 'TEXT',
    'e-resize': 'MOVE_X', 'w-resize': 'MOVE_X', 'ew-resize': 'MOVE_X',
    'n-resize': 'MOVE_Y', 's-resize': 'MOVE_Y', 'ns-resize': 'MOVE_Y',
    'all-scroll': 'SCROLL_XY',
}


# @debug_test_call('rgb(  255,128,  64  )')
# @debug_test_call('rgba(255, 128, 64, 0.5)')
# @debug_test_call('hsl(0, 100%, 50%)')
# @debug_test_call('hsl(240, 100%, 50%)')
# @debug_test_call('hsl(147, 50%, 47%)')
# @debug_test_call('hsl(300, 76%, 72%)')
# @debug_test_call('hsl(39, 100%, 50%)')
# @debug_test_call('hsla(248, 53%, 58%, 0.5)')
# @debug_test_call('#FFc080')
# @debug_test_call('transparent')
# @debug_test_call('white')
# @debug_test_call('black')
def convert_token_to_color(c):
    r,g,b,a = 0,0,0,1
    if type(c) is re.Match: c = c.group(0)

    if c in colorname_to_color:
        c = colorname_to_color[c]
        if len(c) == 3: r,g,b = c
        else: r,g,b,a = c

    elif c.startswith('#'):
        r,g,b = map(lambda v:int(v,16), [c[1:3],c[3:5],c[5:7]])

    elif c.startswith('rgb(') or c.startswith('rgba('):
        c = c.replace('rgb(','').replace('rgba(','').replace(')','').replace(' ','').split(',')
        c = list(map(float, c))
        r,g,b = c[:3]
        if len(c) == 4: a = c[3]

    elif c.startswith('hsl(') or c.startswith('hsla('):
        c = c.replace('hsl(','').replace('hsla(','').replace(')','').replace(' ','').replace('%', '').split(',')
        c = list(map(float, c))
        h,s,l = c[0]/360, c[1]/100, c[2]/100
        if len(c) == 4: a = c[3]
        # https://gist.github.com/mjackson/5311256
        # TODO: use equations on https://www.rapidtables.com/convert/color/hsl-to-rgb.html
        if s <= 0.00001:
            r = g = b = l*255
        else:
            def hue2rgb(p, q, t):
                t %= 1
                if t < 1/6: return p + (q - p) * 6 * t
                if t < 1/2: return q
                if t < 2/3: return p + (q - p) * (2/3 - t) * 6
                return p
            q = (l * ( 1 + s)) if l < 0.5 else (l + s - l * s)
            p = 2 * l - q
            r = hue2rgb(p, q, h + 1/3) * 255
            g = hue2rgb(p, q, h) * 255
            b = hue2rgb(p, q, h - 1/3) * 255

    else:
        assert 'could not convert "%s" to color' % c

    c = Color((r/255, g/255, b/255, a))
    c.freeze()
    return c

def convert_token_to_cursor(c):
    if c is None: return c
    if type(c) is re.Match: c = c.group(0)
    if c in cursorname_to_cursor: return cursorname_to_cursor[c]
    if c in cursorname_to_cursor.values(): return c
    assert False, 'could not convert "%s" to cursor' % c

def convert_token_to_number(n):
    if type(n) is re.Match: n = n.group('num')
    return float(n)

def convert_token_to_numberunit(n):
    assert type(n) is re.Match
    return NumberUnit(n.group('num'), n.group('unit'))

def skip_token(n):
    return None

def convert_token_to_string(s):
    if type(s) is re.Match: s = s.group(0)
    return str(s)

def get_converter_to_string(group):
    def getter(s):
        if type(s) is re.Match: s = s.group(group)
        return str(s)
    return getter


#####################################################################################
# below are various helper functions for ui functions

@lru_cache(maxsize=1024)
def helper_wraptext(text='', width=float('inf'), fontid=0, fontsize=12, preserve_newlines=False, collapse_spaces=True, wrap_text=True, **kwargs):
    if type(text) is not str:
        assert False, 'unknown type: %s (%s)' % (str(type(text)), str(text))
    # TODO: get textwidth of space and each word rather than rebuilding the string
    size_prev = Globals.drawing.set_font_size(fontsize, fontid=fontid, force=True)
    tw = Globals.drawing.get_text_width
    wrap_text &= math.isfinite(width)

    if not preserve_newlines: text = re.sub(r'\n', ' ', text)
    if collapse_spaces: text = re.sub(r' +', ' ', text)
    if wrap_text:
        cline,*ltext = text.split(' ')
        nlines = []
        for cword in ltext:
            if not collapse_spaces and cword == '': cword = ' '
            nline = f'{cline} {cword}'
            if tw(nline) <= width: cline = nline
            else: nlines,cline = nlines+[cline],cword
        nlines += [cline]
        text = '\n'.join(nlines)

    Globals.drawing.set_font_size(size_prev, fontid=fontid, force=True)
    if False: print('wrapped ' + str(random.random()))
    return text


@add_cache('guid', 0)
def get_unique_ui_id(prefix='', postfix=''):
    get_unique_ui_id.guid += 1
    return f'{prefix}{get_unique_ui_id.guid}{postfix}'

