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
from itertools import dropwhile, zip_longest
from concurrent.futures import ThreadPoolExecutor

import bpy
import blf
import gpu

from gpu_extras.presets import draw_texture_2d
from mathutils import Vector, Matrix

from . import ui_settings  # needs to be first

from .ui_core_content           import UI_Core_Content
from .ui_core_debug             import UI_Core_Debug
from .ui_core_dirtiness         import UI_Core_Dirtiness
from .ui_core_draw              import UI_Core_Draw
from .ui_core_elements          import UI_Core_Elements, tags_known
from .ui_core_events            import UI_Core_Events
from .ui_core_fonts             import get_font
from .ui_core_images            import get_loading_image, is_image_cached, load_texture, async_load_image, load_image
from .ui_core_layout            import UI_Core_Layout
from .ui_core_markdown          import UI_Core_Markdown
from .ui_core_preventmulticalls import UI_Core_PreventMultiCalls
from .ui_core_properties        import UI_Core_Properties
from .ui_core_style             import UI_Core_Style
from .ui_core_utilities         import UI_Core_Utils, helper_wraptext, convert_token_to_cursor

from .ui_draw import ui_draw
from .ui_event import UI_Event
from .ui_styling import UI_Styling, ui_defaultstylings

from . import gpustate
from .blender import tag_redraw_all, get_path_from_addon_common, get_path_from_addon_root
from .boundvar import BoundVar
from .debug import debugger, dprint, tprint
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .drawing import Drawing
from .fsm import FSM
from .globals import Globals
from .hasher import Hasher
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .maths import floor_if_finite, ceil_if_finite
from .profiler import profiler, time_it
from .utils import iter_head, any_args, join, kwargs_splitter


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
        - ...

'''



class UI_Element(
        UI_Core_Content,
        UI_Core_Debug,
        UI_Core_Dirtiness,
        UI_Core_Draw,
        UI_Core_Elements,
        UI_Core_Events,
        UI_Core_Layout,
        UI_Core_Markdown,
        UI_Core_PreventMultiCalls,
        UI_Core_Properties,
        UI_Core_Style,
        UI_Core_Utils,
):

    @staticmethod
    def new_element(*args, **kwargs):
        return UI_Element(*args, **kwargs)

    def __init__(self, **kwargs):
        self._init_debug()
        self._init_properties()
        self._init_events()
        self._init_dirtiness()
        self._init_content()

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

            kwargs_events    = kwargs_splitter(kwargs, keys=self._events.keys())
            kwargs_special0  = kwargs_splitter(kwargs, keys={'atomic', 'max', 'min', 'value', 'checked'})
            kwargs_special1  = kwargs_splitter(kwargs, keys={'innerText', 'parent', '_parent', 'children'})
            kwargs_unhandled = kwargs_splitter(kwargs, fn=(lambda k,_: not hasattr(self, k)))

            # handle special properties
            for k, v in kwargs_special0.items():
                match k:
                    case 'atomic':
                        self._atomic = v
                    case 'max':
                        self.valueMax = v
                    case 'min':
                        self.valueMin = v
                    case 'value':
                        if isinstance(v, BoundVar): self.value_bind(v)
                        else: self.value = v
                    case 'checked':
                        if isinstance(v, BoundVar): self.checked_bind(v)
                        else: self.checked = v

            # handle other properties
            cls = type(self)
            for k, v in kwargs.items():
                # need to test that a setter exists for the property
                class_attr = getattr(cls, k, None)
                if type(class_attr) is property:
                    # k is a property
                    assert class_attr.fset is not None, f'Attempting to set a read-only property {k} to "{v}"'
                    setattr(self, k, v)
                else:
                    # k is an attribute
                    print(f'>> COOKIECUTTER UI WARNING: Setting non-property attribute {k} to "{v}"')
                    setattr(self, k, v)

            # handle special connections
            if kwargs_special1.get('innerText', None) is not None:
                self.innerText = kwargs_special1['innerText']
            if kwargs_special1.get('parent', None) is not None:
                # note: parent.append_child(self) will set self._parent
                kwargs_special1['parent'].append_child(self)
            if kwargs_special1.get('_parent', None) is not None:
                self._parent = kwargs_special1['_parent']
                self._document = self._parent.document
                self._do_not_dirty_parent = True
            if kwargs_special1.get('children', None):
                for child in kwargs_special1['children']:
                    self.append_child(child)

            # handle events
            for k, v in kwargs_events.items():
                # key is an event name, v is callback
                self.add_eventListener(k, v)

            # report unhandled attribs
            if kwargs_unhandled:
                print(f'>> COOKIECUTTER UI WARNING: When creating new UI_Element, found unhandled attribute value pairs:')
                print(f'    {kwargs_unhandled}')

        self._setup_element()    # NOTE: this must be done _after_ tag and type are set

        self.dirty(cause='initially dirty')

    def __del__(self):
        if self._cacheRenderBuf:
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

    @UI_Core_Utils.add_cleaning_callback('renderbuf')
    def _renderbuf(self):
        self._dirty_renderbuf = True
        self._dirty_properties.discard('renderbuf')




    # @UI_Core_Utils.add_option_callback('position:flexbox')
    # def position_flexbox(self, left, top, width, height):
    #     pass
    # @UI_Core_Utils.add_option_callback('position:block')
    # def position_flexbox(self, left, top, width, height):
    #     pass
    # @UI_Core_Utils.add_option_callback('position:inline')
    # def position_flexbox(self, left, top, width, height):
    #     pass
    # @UI_Core_Utils.add_option_callback('position:none')
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

    @profiler.function
    def get_under_mouse(self, p:Point2D):
        if p is None: return None
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




def create_fn(tag):
    def create(*args, **kwargs):
        return UI_Element(tagName=tag, *args, **kwargs)
    return create
for tag in tags_known:
    setattr(UI_Element, tag.upper(), create_fn(tag))

