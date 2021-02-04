'''
Copyright (C) 2021 CG Cookie
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
import asyncio
import inspect
import traceback
import contextlib
from math import floor, ceil
from inspect import signature
from itertools import dropwhile, zip_longest
from concurrent.futures import ThreadPoolExecutor

import bpy
import bgl
import blf
import gpu

from .ui_elements import UI_Element_Elements, HTML_CHAR_MAP, tags_known
from .ui_layout import UI_Layout
from .ui_markdown import UI_Markdown
from .ui_properties import UI_Element_Properties
from .ui_utilities import UI_Element_Utils
from .ui_settings import DEBUG_COLOR_CLEAN, DEBUG_PROPERTY, DEBUG_COLOR, DEBUG_DIRTY, DEBUG_LIST, CACHE_METHOD, ASYNC_IMAGE_LOADING

from .ui_draw import ui_draw
from .ui_event import UI_Event

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
from .drawing import Drawing
from .fontmanager import FontManager
from .globals import Globals
from .hasher import Hasher
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .maths import floor_if_finite, ceil_if_finite
from .profiler import profiler, time_it
from .shaders import Shader
from .utils import iter_head, any_args, join, abspath

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
    abspath('fonts'),
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
    path_here = os.path.dirname(__file__)
    path_root = os.path.join(path_here, '..', '..')
    if subfolders is None:
        path_addon_common = os.path.dirname(os.path.abspath(path_here))
        subfolders = [
            'icons',
            'images',
            'help',
            os.path.join(path_addon_common, 'common', 'images'),
        ]
    if ext: fn = f'{fn}.{ext}'
    paths = [os.path.join(path_root, subfolder, fn) for subfolder in subfolders]
    paths = [p for p in paths if os.path.exists(p)]
    found = iter_head(paths, None)
    return found



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
        # print(f'UI: Loading image "{fn}" (path={path})')
        if   ext == '.png':  img = load_image_png(path)
        elif ext == '.apng': img = load_image_apng(path)
        else: assert False, f'load_image: unhandled type ({ext}) for {fn}'
        load_image._cache[fn] = img
    return load_image._cache[fn]

@add_cache('_image', None)
def get_loading_image(fn):
    nfn = f'{os.path.splitext(fn)[0]}.thumb.png'
    if get_image_path(nfn):
        return load_image(nfn)
    if not get_loading_image._image:
        c0, c1 = [128,128,128,0], [128,128,128,128]
        w, h = 10, 10
        image = []
        for y in range(h):
            row = []
            for x in range(w):
                c = c0 if (x+y)%2 == 0 else c1
                row.append(c)
            image.append(row)
        get_loading_image._image = image
    return get_loading_image._image

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
def load_texture(fn_image, mag_filter=bgl.GL_NEAREST, min_filter=bgl.GL_LINEAR, image=None):
    if fn_image not in load_texture._cache:
        if image is None: image = load_image(fn_image)
        # print(f'UI: Buffering texture "{fn_image}"')
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
        bgl.glTexParameteri(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_WRAP_S, bgl.GL_CLAMP_TO_EDGE)
        bgl.glTexParameteri(bgl.GL_TEXTURE_2D, bgl.GL_TEXTURE_WRAP_T, bgl.GL_CLAMP_TO_EDGE)
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

def async_load_image(fn_image, callback):
    img = load_image(fn_image)
    callback(img)



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
        if DEBUG_DIRTY: self._dirty_causes.append(cause)
        if self._do_not_dirty_parent: parent = False
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
                cause = ''
                if DEBUG_DIRTY:
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
        if self._dirty_propagation['defer']: return

        if not self._dirty_propagation['children']: return

        # no need to dirty ::before, ::after, or text, because they will be reconstructed
        for child in self._children:
            child.dirty(
                cause=f'propagating {self._dirty_propagation["children"]}',
                properties=self._dirty_propagation['children'],
                parent=False,
                children=True,
            )
        for child in self._children_gen:
            child.dirty(
                cause=f'propagating {self._dirty_propagation["children"]}',
                properties=self._dirty_propagation['children'],
                parent=False,
                children=True
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

        if self._dirty_propagation['defer']: return
        if self.defer_clean: return
        if not self.is_dirty: return

        self._was_dirty = True   # used to know if postclean should get called

        self._cleaning = True

        profiler.add_note(f'pre: {self._dirty_properties}, {self._dirty_causes} {self._dirty_propagation}')
        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} clean started defer={self.defer_clean}')

        # propagate dirtiness one level down
        self.propagate_dirtiness_down()

        # self.call_cleaning_callbacks()
        self._compute_selector()
        self._compute_style()
        if self.is_visible:
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
        if self._pseudoelement == 'text':
            innerText = self._innerText.replace('\n', '\\n') if self._innerText else ''
            print(f'{sp}"{innerText}"')
        elif self._children_all:
            print(f'{sp}{tag}')
            for c in self._children_all:
                c.debug_print(d+1, already_printed)
            print(f'{sp}{tagc}')
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



class UI_Element(UI_Element_Utils, UI_Element_Properties, UI_Element_Dirtiness, UI_Element_Debug, UI_Element_PreventMultiCalls, UI_Element_Elements, UI_Markdown, UI_Layout):
    @staticmethod
    @add_cache('uid', 0)
    def get_uid():
        UI_Element.get_uid.uid += 1
        return UI_Element.get_uid.uid

    @staticmethod
    def new_element(*args, **kwargs):
        return UI_Element(*args, **kwargs)

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
        self._can_focus     = True      # True:self can take focus if focusable element (ex: <input type="text">)
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
        self._valueMax        = None
        self._valueMin        = None
        self._valueStep       = None
        self._checked         = None
        self._checked_bound   = False
        self._name            = None
        self._href            = None
        self._clamp_to_parent = False
        self._open            = False

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
        self._pseudoelement = ''        # set only if element is a pseudoelement ('::before', '::after', '::marker')

        self._style_left    = None
        self._style_top     = None
        self._style_right   = None
        self._style_bottom  = None
        self._style_width   = None
        self._style_height  = None
        self._style_z_index = None

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
        self._blocks_abs           = None
        self._children_text_min_size = None

        #######################################
        # properties for text input
        self._selectionStart       = None
        self._selectionEnd         = None
        self._ui_marker            = None       # cursor element, checkbox, radio button, etc.

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
            'on_load':          [],     # called when document is set
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
            'on_change':        [],     # occurs after blur if value has changed
            'on_toggle':        [],     # occurs when open attribute is toggled
            'on_close':         [],     # dialog is closed
            'on_visibilitychange': [],  # element became visible or hidden
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
        self._children_gen     = []     # generated children (pseudoelements)
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

        # handle innerText
        # if 'innerText' in kwargs and kwargs.get('pseudoelement', '') != 'text':
        #     innerText = kwargs['innerText']
        #     del kwargs['innerText']
        #     kwargs.setdefault('children', [])
        #     kwargs['children'] += [UI_Element(tagName='text', pseudoelement='text', innerText=innerText)]
        #     print(f'UI_Element: {kwargs["tagName"]} creating <text::text> for "{innerText}"')

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
                elif hasattr(self, k) and k not in {'parent', '_parent', 'children', 'innerText'}:
                    # need to test that a setter exists for the property
                    class_attr = getattr(type(self), k, None)
                    if type(class_attr) is property:
                        # k is a property
                        assert class_attr.fset is not None, f'Attempting to set a read-only property {k} to "{v}"'
                        setattr(self, k, v)
                    else:
                        # k is an attribute
                        print(f'>> COOKIECUTTER UI WARNING: Setting non-property attribute {k} to "{v}"')
                        setattr(self, k, v)
                else:
                    unhandled_keys.add(k)

            # handle innerText
            if 'innerText' in kwargs:
                if kwargs['innerText'] is not None:
                    self.innerText = kwargs['innerText']

            # second pass: handling parent...
            working_keys, unhandled_keys = unhandled_keys, set()
            for k in working_keys:
                v = kwargs[k]
                if k == 'parent':
                    # note: parent.append_child(self) will set self._parent
                    v.append_child(self)
                elif k == '_parent':
                    self._parent = v
                    if v: self._document = v.document
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
                elif k == 'innerText':
                    pass
                else:
                    unhandled_keys.add(k)

            # report unhandled attribs
            if unhandled_keys:
                print(f'>> COOKIECUTTER UI WARNING: When creating new UI_Element, found unhandled attribute value pairs:')
                for k in unhandled_keys:
                    print(f'  {k}={kwargs[k]}')

        self._init_element()
        self.dirty(cause='initially dirty')

    def __del__(self):
        if self._cacheRenderBuf:
            self._cacheRenderBuf.free()
            self._cacheRenderBuf = None

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        if self._innerTextAsIs is not None:
            innerTextAsIs = self._innerTextAsIs.replace('\n', '\\n') if self._innerTextAsIs else ''
            return f"'{innerTextAsIs}'"
        if self._pseudoelement == 'text':
            innerText = self.innerText.replace('\n', '\\n') if self.innerText else ''
            return f'"{innerText}"'
        tagName = f'{self.tagName}::{self._pseudoelement}' if self._pseudoelement else self.tagName
        info = ['id', 'classes', 'type', 'value', 'title']  #, 'innerText', 'innerTextAsIs'
        info = [(k, getattr(self, k)) for k in info if hasattr(self, k)]
        info = [f'{k}="{v}"' for k,v in info if v]
        # if self._pseudoelement == 'text':
        #     nl,bnl = '\n','\\n'
        #     info += [f"{k}=\"{getattr(self, k).replace(nl, bnl)}\"" for k in ['innerText', 'innerTextAsIs'] if getattr(self, k) != None]
        if self.open:     info += ['open']
        if self.is_dirty: info += ['dirty']
        if self._atomic:  info += ['atomic']
        info = ' '.join(['']+info) if info else ''
        return f'<{tagName}{info}>'

    @property
    def as_html(self):
        info = [
            'id', 'classes', 'type', 'pseudoelement',
            # 'innerText', 'innerTextAsIs',
            'href',
            'value', 'title',
        ]
        info = [(k, getattr(self, k)) for k in info if hasattr(self, k)]
        info = [f'{k}="{v}"' for k,v in info if v]
        if self.open:     info += ['open']
        if self.is_dirty: info += ['dirty']
        if self._atomic:  info += ['atomic']
        return '<%s>' % ' '.join([self.tagName] + info)

    @profiler.function
    def _rebuild_style_selector(self):
        sel_parent = (None if not self._parent else self._parent._selector) or []

        # TEST!!
        # sel_parent = [re.sub(r':(active|hover)', '', s) for s in sel_parent]


        selector_before = None
        selector_after = None
        if self._innerTextAsIs is not None:
            # this is a text element
            selector = [*sel_parent, '*text*']
        # elif self._pseudoelement:
        #     # this has a pseudoelement: ::before, ::after, ::marker
        #     selector = [*sel_parent[:-1], f'{sel_parent[-1]}::{self._pseudoelement}']
        else:
            ui_for = self.get_for_element()

            attribvals = {}
            type_val = self.type_with_for(ui_for)
            if type_val: attribvals['type'] = type_val
            value_val = self.value_with_for(ui_for)
            if value_val: attribvals['value'] = value_val
            name_val = self.name
            if name_val: attribvals['name'] = name_val

            is_disabled = False
            is_disabled |= self._value_bound and self._value.disabled
            is_disabled |= self._checked_bound and self._checked.disabled

            sel_tagName    = self._tagName
            sel_id         = f'#{self._id}' if self._id else ''
            sel_cls        = join('.', self._classes, preSep='.')
            sel_attribs    = join('][', attribvals.keys(),  preSep='[', postSep=']')
            sel_attribvals = join('][', attribvals.items(), preSep='[', postSep=']', toStr=lambda kv:f'{kv[0]}="{kv[1]}"')
            sel_pseudocls  = join(':', self.pseudoclasses_with_for(ui_for), preSep=':')
            sel_pseudoelem = f'::{self._pseudoelement}' if self._pseudoelement else ''
            if is_disabled:
                sel_pseudocls += ':disabled'
            if self.checked_with_for(ui_for):
                sel_attribs    += '[checked]'
                sel_attribvals += '[checked="checked"]'
                sel_pseudocls  += ':checked'
            if self.open:
                sel_attribs += '[open]'

            self_selector = f'{sel_tagName}{sel_id}{sel_cls}{sel_attribs}{sel_attribvals}{sel_pseudocls}{sel_pseudoelem}'
            if self._pseudoelement not in {None, '', 'text'}:
                selector = [*sel_parent[:-1], self_selector]
            else:
                selector = [*sel_parent,      self_selector]
            #selector_before = sel_parent + [sel_tagName + sel_id + sel_cls + sel_pseudocls + '::before']
            #selector_after  = sel_parent + [sel_tagName + sel_id + sel_cls + sel_pseudocls + '::after']

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
        # if self._children_text:
        #     for child in self._children_text: child._compute_selector()
        if self._children_gen:
            for child in self._children_gen: child._compute_selector()
        # if self._child_before or self._child_after:
        #     if self._child_before: self._child_before._compute_selector()
        #     if self._child_after:  self._child_after._compute_selector()
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
                for e in list(self._dirty_callbacks.get('style', [])):
                    # print(self,'->', e)
                    e._compute_style()
                for e in list(self._dirty_callbacks.get('style parent', [])):
                    # print(self,'->', e)
                    e._compute_style()
                self._dirty_callbacks['style'].clear()
                self._dirty_callbacks['style parent'].clear()
            self.defer_clean = False
            return

        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} style')

        was_visible = self.is_visible
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

            if self._pseudoelement == 'text':
                text_styles = self._parent._computed_styles if self._parent else self._computed_styles
            else:
                text_styles = self._computed_styles

            self._fontid = get_font(
                text_styles.get('font-family', UI_Element_Defaults.font_family),
                text_styles.get('font-style',  UI_Element_Defaults.font_style),
                text_styles.get('font-weight', UI_Element_Defaults.font_weight),
            )
            self._fontsize   = text_styles.get('font-size',   UI_Element_Defaults.font_size).val()
            self._fontcolor  = text_styles.get('color',       UI_Element_Defaults.font_color)
            self._whitespace = text_styles.get('white-space', UI_Element_Defaults.whitespace)
            ts = text_styles.get('text-shadow', 'none')
            self._textshadow = None if ts == 'none' else (ts[0].val(), ts[1].val(), ts[-1])

        # tell children to recompute selector
        # NOTE: self._children_all has not been constructed, yet!
        if self.is_visible:
            if self._children:
                for child in self._children: child._compute_style()
            # if self._children_text:
            #     for child in self._children_text: child._compute_style()
            if self._children_gen:
                for child in self._children_gen: child._compute_style()
            # if self._child_before or self._child_after:
            #     if self._child_before: self._child_before._compute_style()
            #     if self._child_after:  self._child_after._compute_style()

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
            if style_content_hash != getattr(self, '_style_content_hash', None) or self._children_gen:
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

        if self.is_visible != was_visible:
            self.dispatch_event('on_visibilitychange')

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
            for e in list(self._dirty_callbacks.get('content', [])): e._compute_content()
            self._dirty_callbacks['content'].clear()
            return

        self._clean_debugging['content'] = time.time()
        if DEBUG_LIST: self._debug_list.append(f'{time.ctime()} content')

        # self.defer_dirty_propagation = True
        self._children_gen = []

        content_before = self._computed_styles_before.get('content', None) if self._computed_styles_before else None
        if content_before is not None:
            # TODO: cache this!!
            self._child_before = UI_Element(tagName=self._tagName, innerText=content_before, pseudoelement='before', _parent=self)
            self._child_before.clean()
            self._new_content = True
            self._children_gen += [self._child_before]
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
            self._children_gen += [self._child_after]
        else:
            if self._child_after:
                self._child_after = None
                self._new_content = True

        if self._src and not self.src:
            self._src = None
            self._new_content = True

        if self._computed_styles.get('content', None) is not None:
            self.innerText = self._computed_styles['content']

        if self._innerText is not None:
            # TODO: cache this!!
            textwrap_opts = {
                'dpi':               Globals.drawing.get_dpi_mult(),
                'text':              self._innerText,
                'fontid':            self._fontid,
                'fontsize':          self._fontsize,
                'preserve_newlines': self._whitespace in {'pre',    'pre-line', 'pre-wrap'},
                'collapse_spaces':   self._whitespace in {'normal', 'nowrap',   'pre-line'},
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
                        ui_br = self._generate_new_ui_elem(tagName='br', text_child=True)
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
                        for f,t in HTML_CHAR_MAP: word = word.replace(f, t)
                        ui_word = self._generate_new_ui_elem(innerTextAsIs=word, text_child=True)
                        #tagName=self._tagName, pseudoelement='text',
                        for i in range(len(word)):
                            self._text_map.append({
                                'ui_element': ui_word,
                                'idx': idx,
                                'offset': i,
                                'char': word[i],
                                'pre': word[:i],
                            })
                        idx += len(word)
                # needed so cursor can reach end
                ui_end = self._generate_new_ui_elem(innerTextAsIs='', text_child=True)
                #tagName=self._tagName, pseudoelement='text',
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
            if ASYNC_IMAGE_LOADING and not self._pseudoelement and not is_image_cached(self.src):
                # print(f'LOADING {self.src} ASYNC')
                if self._src == 'image':
                    self._new_content = True
                elif self._src == 'image loading':
                    pass
                elif self._src == 'image loaded':
                    self._src = 'image'
                    self._image_data = load_texture(self.src, image=self._image_data)
                    self._new_content = True
                    self.dirty()
                else:
                    self._src = 'image loading'
                    self._image_data = load_texture(f'image loading {self.src}', image=get_loading_image(self.src), mag_filter=bgl.GL_LINEAR)
                    self._new_content = True
                    def callback(image):
                        self._src = 'image loaded'
                        self._image_data = image
                        self.dirty()
                    def load():
                        async_load_image(self.src, callback)
                    ThreadPoolExecutor().submit(load)
            else:
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
        self._children_all += self._process_children()
        if self._children_text: self._children_all += self._children_text
        if self._child_after:   self._children_all.append(self._child_after)

        self._children_all = [child for child in self._children_all if child.is_visible]

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
        blocks_abs = self._blocks_abs
        if self._computed_styles.get('display', 'inline') == 'flexbox':
            # all children are treated as flex blocks, regardless of their display
            pass
        else:
            # collect children into blocks
            blocks = []
            blocks_abs = []
            blocked_inlines = False
            def process_child(child):
                nonlocal blocks, blocks_abs, blocked_inlines
                d = child._computed_styles.get('display', 'inline')
                p = child._computed_styles.get('position', 'static')
                if p == 'absolute':
                    blocks_abs.append(child)
                # elif p == 'fixed':
                #    blocks_abs.append(child)  # need separate list for fixed elements?
                elif d in {'inline', 'table-cell'}:
                    if not blocked_inlines:
                        blocked_inlines = True
                        blocks.append([child])
                    else:
                        blocks[-1].append(child)
                else:
                    blocked_inlines = False
                    blocks.append([child])
            # if any(child._tagName == 'text' for child in self._children_all):
            #     n_children_all = []
            #     for child in self._children_all:
            #         if child._tagName != 'text':
            #             n_children_all.append(child)
            #         else:
            #             print(f'moving children of {child} ({child._children_all} / {child._children_text}) to {self}')
            #             n_children_all += child._children_all
            #     self._children_all = n_children_all
            for child in self._children_all:
                process_child(child)

        def same(ll0, ll1):
            if ll0 == None or ll1 == None: return ll0 == ll1
            if len(ll0) != len(ll1): return False
            for (l0, l1) in zip(ll0, ll1):
                if len(l0) != len(l1): return False
                if any(i0 != i1 for (i0, i1) in zip(l0, l1)): return False
            return True

        if not same(blocks, self._blocks) or not same([blocks_abs], [self._blocks_abs]):
            # content changes might have changed size
            self._blocks = blocks
            self._blocks_abs = blocks_abs
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

        elif self._src in {'image', 'image loading'}:
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
            texture_id = self._image_data['texid'] if self._src in {'image', 'image loading'} else -1
            texture_fit = self._computed_styles.get('object-fit', 'fill')
            ui_draw.draw(ol, ot, self._w, self._h, dpi_mult, self._style_cache, texture_id, texture_fit, background_override=background_override, depth=len(self._selector))

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

            with ScissorStack.wrap(il, it, iw, ih, msg=f'{self} mbp', disabled=noclip):
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
        if self._pseudoelement: return None
        if self._w < 1 or self._h < 1: return None
        if not (self._l <= p.x <= self._r and self._b <= p.y <= self._t): return None
        # p is over element
        if not self.is_visible: return None
        if not self.can_hover: return None
        # element is visible and hoverable
        if self._atomic: return self
        for child in reversed(self._children):
            under = child.get_under_mouse(p)
            if under: return under
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
        ovent = event
        event = event if event.startswith('on_') else f'on_{event}'
        assert event in self._events, f'Attempting to add unhandled event handler type "{oevent}"'
        sig = signature(callback)
        old_callback = callback
        if len(sig.parameters) == 0:
            callback = lambda e: old_callback()
        self._events[event] += [(useCapture, callback, old_callback)]

    def remove_eventListener(self, event, callback):
        # returns True if callback was successfully removed
        oevent = event
        event = event if event.startswith('on_') else f'on_{event}'
        assert event in self._events, f'Attempting to remove unhandled event handler type "{ovent}"'
        l = len(self._events[event])
        self._events[event] = [(capture,cb,old_cb) for (capture,cb,old_cb) in self._events[event] if old_cb != callback]
        return l != len(self._events[event])

    def _fire_event(self, event, details):
        ph = details.event_phase
        cap, bub, df = details.capturing, details.bubbling, not details.default_prevented
        try:
            if (cap and ph == 'capturing') or (df and ph == 'at target'):
                for (cap,cb,old_cb) in self._events[event]:
                    if not cap: continue
                    cb(details)
            if (bub and ph == 'bubbling') or (df and ph == 'at target'):
                for (cap,cb,old_cb) in self._events[event]:
                    if cap: continue
                    cb(details)
        except Exception as e:
            print(f'COOKIE CUTTER >> Exception Caught while trying to callback event handlers')
            print(f'UI_Element: {self}')
            print(f'event: {event}')
            print(f'exception: {e}')
            raise e

    @profiler.function
    def dispatch_event(self, event, mouse=None, button=None, key=None, ui_event=None, stop_at=None):
        event = event if event.startswith('on_') else f'on_{event}'
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

        if ui_event is None:
            ui_event = UI_Event(target=self, mouse=mouse, button=button, key=key)

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


def create_fn(tag):
    def create(*args, **kwargs):
        return UI_Element(tagName=tag, *args, **kwargs)
    return create
for tag in tags_known:
    setattr(UI_Element, tag.upper(), create_fn(tag))

