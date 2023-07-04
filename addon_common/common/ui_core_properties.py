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

import bpy
import blf
import gpu

from .ui_core_utilities import UI_Core_Utils

from gpu_extras.presets import draw_texture_2d
from mathutils import Vector, Matrix

from . import ui_settings
from .blender import tag_redraw_all
from .ui_styling import UI_Styling, ui_defaultstylings
from .ui_core_utilities import helper_wraptext, convert_token_to_cursor, get_unique_ui_id
from .fsm import FSM

from .boundvar import BoundVar
from .debug import debugger, dprint, tprint
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .drawing import Drawing
from .globals import Globals
from .hasher import Hasher
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .profiler import profiler, time_it
from .utils import iter_head, any_args, join

from ..ext import png
from ..ext.apng import APNG


class UI_Core_Properties:
    def _init_properties(self):
        # attributes of UI_Element that are settable
        # set to blank defaults, will be set again later in __init__()
        self._tagName       = ''        # determines type of UI element
        self._id            = ''        # unique identifier
        self._classes_str   = ''        # list of classes (space delimited string)
        self._style_str     = ''        # custom style string
        self._innerText     = None      # text to display (converted to UI_Elements)
        self._src_str       = None      # path to resource, such as image
        self._can_focus     = None      # None/True:self can take focus if focusable element (ex: <input type="text">)
        self._can_hover     = True      # True:self can take hover
        self._title         = None      # tooltip
        self._forId         = None      # used for labels
        self._uid           = get_unique_ui_id()
        self._document      = None

        # attribs
        self._type            = None
        self._value           = None
        self._value_bound     = False
        self._maxlength       = None
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

        # properties for text input
        self._selectionStart       = None
        self._selectionEnd         = None
        self._ui_marker            = None       # cursor element, checkbox, radio button, etc.

        # cached properties
        # TODO: go back through these to make sure we've caught everything
        self._classes          = []                     # classes applied to element, set by self.classes property, based on self._classes_str
        self._computed_styles  = {}                     # computed style UI_Style after applying all styling
        self._computed_styles_before = {}
        self._computed_styles_after = {}
        self._is_visible       = None                   # indicates if self is visible, set in compute_style(), based on self._computed_styles
        self._is_scrollable_x  = False                  # indicates is self is scrollable along x, set in compute_style(), based on self._computed_styles
        self._is_scrollable_y  = False                  # indicates is self is scrollable along y, set in compute_style(), based on self._computed_styles
        self._static_content_size     = None            # min and max size of content, determined from children and style
        self._children_text    = []                     # innerText as children
        self._children_gen     = []                     # generated children (pseudoelements)
        self._child_before     = None                   # ::before child
        self._child_after      = None                   # ::after child
        self._children_all     = []                     # all children in order
        self._children_all_sorted = []                  # all children sorted by z-index
        self._innerTextWrapped = None                   # <--- no longer needed?
        self._selector         = None                   # full selector of self, built in compute_style()
        self._selector_last    = None                   # last full selector of self, updated in compute_style()
        self._selector_before  = None                   # full selector of ::before pseudoelement for self
        self._selector_after   = None                   # full selector of ::after pseudoelement for self
        self._styling_trimmed  = None
        self._styling_custom   = None
        self._styling_parent   = None
        self._styling_list     = []
        self._innerTextAsIs    = None                   # text to display as-is (no wrapping)
        self._src              = None
        self._textwrap_opts    = {}
        self._l, self._t, self._w, self._h = (0,0,0,0)  # scissor position
        self._fontid           = 0
        self._fontsize         = 12
        self._fontcolor        = (0,0,0,1)
        self._textshadow       = None
        self._whitespace       = 'normal'
        self._cacheRenderBuf   = None   # GPUOffScreen buffer
        self._dirty_renderbuf  = True
        self._style_trbl_cache = {}

        # overrides
        self._left_override = None
        self._top_override = None
        self._width_override = None
        self._height_override = None



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
    def tagType(self):
        return self._tagName if not self._type else f'{self._tagName} {self._type}'

    @property
    def innerText(self):
        if self._pseudoelement == 'text': return self._innerText
        t = [child._innerText for child in self._children if child._pseudoelement == 'text' and child._innerText is not None]
        if not t: return None
        return '\n'.join(t)
    @innerText.setter
    def innerText(self, nText):
        if self._pseudoelement == 'text':
            if self._innerText == nText: return
            self._innerText = nText
            # self.dirty(cause='changing innerText makes dirty', children=True)
            self.dirty_content(cause='changing innerText')
            self.dirty_size(cause='changing innerText')
            #self.dirty('changing innerText changes content', 'content', children=True)
            #self.dirty('changing innerText changes size', 'size', children=True)
            self._new_content = True
            self.dirty_flow()
            if self._parent: self._parent.dirty_content(cause='changing innerText')
        elif len(self._children) == 1 and self._children[0]._pseudoelement == 'text':
            self._children[0].innerText = nText
        else:
            self.clear_children()
            self.append_new_child(tagName='text', pseudoelement='text', innerText=nText)

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
        if element_name is None: return []
        ret = [self] if self._name == element_name else []
        ret.extend(e for child in self.children for e in child.getElementsByName(element_name))
        return ret

    def getElementsByClassName(self, class_name):
        if class_name is None: return []
        ret = [self] if class_name in self._classes else []
        ret.extend(e for child in self.children for e in child.getElementsByClassName(class_name))
        return ret

    def getElementsByTagName(self, tag_name):
        if tag_name is None: return []
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
        if value:
            self.dispatch_event('on_load')

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
    def append_children(self, children):
        for child in children: self._append_child(child)
    def prepend_child(self, child):
        assert child
        if child in self._children:
            # attempting to add existing child?
            return
        if child._parent:
            # detach child from prev parent
            child._parent.delete_child(child)
        self._children.insert(0, child)
        child._parent = self
        child.document = self.document
        child.dirty(cause='prepending children', parent=False)
        self.dirty_content(cause='prepending children', children=False, parent=False)
        self.dirty_flow()
        self._new_content = True
        return child

    # create and append/prepend new child, similar to:
    # self.append_child(UI_Element(...)) or UI_Element(..., parent=self)
    def append_new_child(self, *args, **kwargs):
        ui = self.new_element(*args, **kwargs)
        self.append_child(ui)
        return ui
    def append_new_children_fromHTML(self, html, **kwargs):
        ui = self.fromHTML(html, frame_depth=2, **kwargs)
        self.append_children(ui)
        return ui
    def prepend_new_child(self, *args, **kwargs):
        ui = self.new_element(*args, **kwargs)
        self.prepend_child(ui)
        return ui

    # generates new UI_Element child and adds to self._children_gen
    def _generate_new_ui_elem(self, *args, gen_child=True, text_child=False, **kwargs):
        kwargs.setdefault('_parent', self)
        ui = self.new_element(*args, **kwargs)
        ui.clean()
        if kwargs['_parent']:
            if gen_child:  kwargs['_parent']._children_gen  += [ui]
            if text_child: kwargs['_parent']._children_text += [ui]
            kwargs['_parent']._new_content = True
        return ui



    def builder(self, children):
        t = type(children)
        if t is list:
            for child in children:
                self.builder(child)
        elif t is tuple:
            child,grandchildren = children
            self.append_child(child).builder(grandchildren)
        else:
            assert False, 'UI_Element.builder: unhandled type %s' % t
        return self

    def _delete_child(self, child):
        assert child, 'attempting to delete None child?'
        assert child in self._children, f'Attempted to delete non-child {child} from {self}'
        if self.document: self.document.removed_element(child)
        self._children.remove(child)
        child._parent = None
        child.document = None
        child.dirty(cause='deleting child from parent')
        self.dirty_content(cause='deleting child changes content')
        self._new_content = True
    def delete_child(self, child): self._delete_child(child)

    @UI_Core_Utils.defer_dirty_wrapper('clearing children')
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


    # returns tagName of child at specified idx
    def _get_child_tagName(self, idx):
        if not self._children: return None
        return self._children[idx]._tagName

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
        if self._document:
            self._document.body.dirty()
    def add_style(self, style):
        style = f'{self._style_str};{style or ""}'
        if self._style_str == style: return
        self._style_str = style
        self._styling_custom = None
        self.dirty_style(cause=f'adding style for {self} affects style')
        # self.dirty(f'adding style for {self} affects parent content', 'content', parent=True, children=False)
        self.add_dirty_callback_to_parent(['style', 'content'])
        if self._document:
            self._document.body.dirty()

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

    def get_for_element(self):
        if self._tagName == 'label' and not self._forId:
            # this is a label, but no for attribute was specified, so we'll go with the first input child
            return next((child for child in self._children if child._tagName == 'input'), None)
        return self.get_root().getElementById(self._forId)

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
    def has_class(self, cls):
        return cls in self._classes

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
        if self._pseudoelement:
            return self._parent._pseudoclasses | self._pseudoclasses
        return set(self._pseudoclasses)

    def pseudoclasses_with_for(self, ui_for=None):
        if not ui_for: ui_for = self.get_for_element()
        if not ui_for: return self.pseudoclasses
        return self._pseudoclasses | ui_for._pseudoclasses

    def _has_affected_descendant(self):
        self._rebuild_style_selector()
        return self._children_text or UI_Styling.has_matches(self._selector+['*'], *self._styling_list)

    def clear_pseudoclass(self):
        if self._pseudoclasses:
            self._pseudoclasses.clear()
            self.dirty_selector(cause=f'clearing pseudoclasses for {self} affects selector', children=True)
            if self._tagName == 'input':
                self.dirty(cause='changing checked can affect selector and content', children=True)
        ui_for = self.get_for_element()
        if ui_for: ui_for.clear_pseudoclass()

    def add_pseudoclass(self, pseudo):
        if pseudo not in self._pseudoclasses:
            if pseudo == 'disabled':
                self._pseudoclasses.discard('active')
                self._pseudoclasses.discard('focus')
                # TODO: on_blur?
            self._pseudoclasses.add(pseudo)
            self.dirty_selector(cause=f'adding pseudoclass {pseudo} for {self} affects selector', children=True)
            if self._tagName == 'input':
                self.dirty(cause='changing checked can affect selector and content', children=True)
        ui_for = self.get_for_element()
        if ui_for: ui_for.add_pseudoclass(pseudo)

    def del_pseudoclass(self, pseudo):
        if pseudo in self._pseudoclasses:
            self._pseudoclasses.discard(pseudo)
            self.dirty_selector(cause=f'deleting pseudoclass {pseudo} for {self} affects selector', children=True)
            if self._tagName == 'input':
                self.dirty(cause='changing checked can affect selector and content', children=True)
        ui_for = self.get_for_element()
        if ui_for: ui_for.del_pseudoclass(pseudo)

    def has_pseudoclass(self, pseudo):
        if pseudo == 'disabled' and self._disabled: return True
        return pseudo in self.pseudoclasses_with_for()

    @property
    def is_active(self): return 'active' in self.pseudoclasses_with_for()
    @property
    def is_hovered(self): return 'hover' in self.pseudoclasses_with_for()
    @property
    def is_focused(self): return 'focus' in self.pseudoclasses_with_for()
    @property
    def is_disabled(self):
        ui_for = self.get_for_element()
        if 'disabled' in self.pseudoclasses_with_for(ui_for): return True
        if self._value_bound   and self._value.disabled:      return True
        if self._checked_bound and self._checked.disabled:    return True
        if ui_for: return ui_for.is_disabled
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
        self.dirty_selector(cause='changing pseudoelement affects selector')

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
    def title_with_for(self, ui_for=None):
        if not ui_for: ui_for = self.get_for_element()
        if not ui_for: return self.title
        return self.title or ui_for.title


    @property
    def selectionStart(self):
        if not self._ui_cursor: return None
        return self._selectionStart
    @selectionStart.setter
    def selectionStart(self, v):
        if self._innerText is None: return
        self._selectionStart = clamp(v, 0, len(self._innerText))
        self._selectionEnd = None

    @property
    def selectionEnd(self):
        if not self._ui_cursor: return None
        return self._selectionStart if self._selectionEnd is None else self._selectionEnd
    @selectionEnd.setter
    def selectionEnd(self, v):
        if self._innerText is None: return
        if v is None:
            self._selectionEnd = None
            return
        s,e = self._selectionStart, clamp(v, 0, len(self._innerText))
        self._selectionStart = min(s, e)
        self._selectionEnd =  max(s, e)

    def setSelectionRange(start, end=None):
        if self._innerText is None: return
        self.selectionStart = start
        self.selectionEnd = end

    def select(self):
        if self._innerText is None: return
        self.selectionStart = 0
        self.selectionEnd = len(self._innerText)


    def reposition(self, left=None, top=None, bottom=None, right=None, clamp_position=True):
        assert not bottom and not right, 'repositioning UI via bottom or right not implemented yet :('
        if clamp_position and self._relative_element:
            try:
                w,h = Globals.drawing.scale(self.width_pixels),self.height_pixels #Globals.drawing.scale(self.height_pixels)
            except Exception as e:
                # sometimes the code above crashes, because self.width_pixels is not a float
                print(f'>>>>>>>>> {self.width_pixels} {self.height_pixels}')
                print(e)
                w,h = 0,0
            mymbph = self._mbp_height or 0
            rw,rh = self._relative_element.width_pixels,self._relative_element.height_pixels
            mbpw,mbph = self._relative_element._mbp_width or 0,self._relative_element._mbp_height or 0
            # print(f'reposition: top={top} h={h} mymbp={mymbph} r={self._relative_element} rh={rh} rmbp={mbph} min={-(rh-mbph)+h+mymbph} max=0')
            if left is not None: left = clamp(left, 0, (rw - mbpw) - w)
            if top  is not None: top  = clamp(top, -(rh - mbph) + h + mymbph, 0)
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
            if ui_settings.DEBUG_LIST: self._debug_list.append(f'{time.ctime()} repositioned')

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
        if reh is None: reh = 0
        t = self.style_top
        if self._relative_pos and t == 'auto': t = self._relative_pos.y
        if t != 'auto':
            if type(t) is NumberUnit: t = t.val(base=reh)
        else:
            dpi_mult = Globals.drawing.get_dpi_mult()
            b = self.style_bottom
            h = self.height_pixels*dpi_mult if self.height_pixels != 'auto' else 0
            if type(b) is NumberUnit: t = reh - b.val(base=reh)
            elif b != 'auto':         t = h + b
            # if type(b) is NumberUnit: t = h + b.val(base=reh) - reh
            # elif b != 'auto':         t = h + b
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
        if self._parent:
            if not self._parent.is_visible: return False
            if self._tagName != 'summary' and self._parent._tagName == 'details' and not self._parent.open: return False
        return self.get_is_visible()
    @is_visible.setter
    def is_visible(self, v):
        if self._is_visible == v: return
        self._is_visible = v
        self.dispatch_event('on_visibilitychange')
        # self.dirty('changing visibility can affect everything', parent=True, children=True)
        self.dirty(cause='visibility changed')
        self.dirty_flow()
        self.dirty_renderbuf(cause='changing visibility can affect everything')
        if self._document:
            self._document.body.dirty()

    # self.get_is_visible() is same as self.is_visible() except it doesn't check parent
    def get_is_visible(self):
        if self._is_visible is None:
            v = self._computed_styles.get('display', 'auto') != 'none'
        else:
            v = self._is_visible
        return v

    @property
    def is_scrollable(self):
        return self.is_scrollable_x or self.is_scrollable_y
    @property
    def is_scrollable_x(self):
        return self._is_scrollable_x and self.is_clipped_x
    @property
    def is_scrollable_y(self):
        return self._is_scrollable_y and self.is_clipped_y

    @property
    def is_clipped(self):
        return self.is_clipped_x or self.is_clipped_y
    @property
    def is_clipped_x(self):
        if not self._dynamic_content_size or not self._absolute_size: return False
        return self._dynamic_content_size.width > self._absolute_size.width
    @property
    def is_clipped_y(self):
        if not self._dynamic_content_size or not self._absolute_size: return False
        return self._dynamic_content_size.height > self._absolute_size.height

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
    def type_with_for(self, ui_for=None):
        if not ui_for: ui_for = self.get_for_element()
        if not ui_for: return self._type
        return self._type or ui_for._type

    @property
    def open(self):
        return bool(self._open)
    @open.setter
    def open(self, v):
        v = bool(v)
        if self._open == v: return
        self._open = v
        self.dirty_selector(cause='changing open can affect selector', children=False)
        self.dirty_style(cause='changing open can affect styling', children=False)
        self.dirty_content(cause='changing open can affect content')
        if self._tagName == 'details':
            for child in self._children:
                child.dirty_selector(cause='changing open can affect selector', children=False)
                child.dirty_style(cause='changing open can affect styling', children=False)
                child.dirty_content(cause='changing open can affect content', children=False)
        self.dirty_style(cause='changing open can affect style', children=True)
        self.dispatch_event('on_toggle')

    @property
    def value(self):
        if self._pseudoelement: return self._parent.value
        if self._value_bound:   return self._value.value
        return self._value
    @value.setter
    def value(self, v):
        if self._pseudoelement: self._parent.value = v
        if self._value_bound:   self._value.value = v
        elif self._value != v:
            self._value = v
            self._value_change()
    def value_with_for(self, ui_for=None):
        if not ui_for: ui_for = self.get_for_element()
        if not ui_for: return self.value
        return self.value or ui_for.value
    def _value_change(self):
        if not self.is_visible: return
        self.dispatch_event('on_input')
        self.dirty(cause='changing value can affect selector and content', children=True)
        self.dirty_flow()
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
    def maxlength(self):
        return self._maxlength
    @maxlength.setter
    def maxlength(self, v):
        self._maxlength = max(0, int(v))

    @property
    def valueMax(self):
        if self._pseudoelement: return self._parent.valueMax
        if self._value_bound:   return self._value.max_value
        return self._valueMax
    @valueMax.setter
    def valueMax(self, v):
        if self._pseudoelement:   self._parent.valueMax = v
        elif self._value_bound:   self._value.max_value = v
        elif self._valueMax != v: self._valueMax = v

    @property
    def valueMin(self):
        if self._pseudoelement: return self._parent.valueMin
        if self._value_bound:   return self._value.max_value
        return self._valueMin
    @valueMin.setter
    def valueMin(self, v):
        if   self._pseudoelement: self._parent.valueMin = v
        elif self._value_bound:   self._value.min_value = v
        elif self._valueMin != v: self._valueMin = v

    @property
    def valueStep(self):
        if   self._pseudoelement: return self._parent.valueStep
        elif self._value_bound:   return self._value.max_value
        return self._valueStep
    @valueStep.setter
    def valueStep(self, v):
        if   self._pseudoelement:  self._parent.valueStep = v
        elif self._value_bound:    self._value.min_value = v
        elif self._valueStep != v: self._valueStep = v

    @property
    def checked(self):
        if self._pseudoelement: return self._parent.checked
        if self._checked_bound:
            if not self._value_bound and self._value is not None:
                return self._checked.value == self._value
            return self._checked.value
        else:
            return self._checked
    @checked.setter
    def checked(self, v):
        if self._checked_bound:
            if not self._value_bound and self._value is not None:
                if bool(v) and self._checked.value != self._value:
                    self._checked.value = self._value
                    self._checked_change()
            elif self._checked.value != v:
                self._checked.value = v
                self._checked_change()
        elif self._checked != v:
            self._checked = v
            self._checked_change()
    def checked_with_for(self, ui_for=None):
        if not ui_for: ui_for = self.get_for_element()
        if not ui_for: return self.checked
        return self.checked or ui_for.checked
    def _checked_change(self):
        self.dispatch_event('on_input')
        self.dirty(cause='changing checked can affect selector and content', children=True)
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
    def can_focus(self):
        if self._can_focus is not None: return bool(self._can_focus)
        if self._tagName == 'input' and self._type in {'text', 'number'}: return True
        if self._forId:
            f = self.get_for_element()
            if f: return f.can_focus
        return False
        # return (self._can_focus is None and self._tagName == 'input' and self._type in {'text', 'number'}) or bool(self._can_focus)
    @can_focus.setter
    def can_focus(self, v): self._can_focus = v

    @property
    def can_hover(self): return self._can_hover
    @can_hover.setter
    def can_hover(self, v): self._can_hover = v

    @profiler.function
    def get_text_pos(self, index):
        if self._pseudoelement != 'text':
            ui_text = next((child for child in self._children if child._pseudoelement == 'text'), None)
            if not ui_text: return None
            return ui_text.get_text_pos(index)
        if self._innerText is None: return None
        index = clamp(index, 0, len(self._text_map)-1)
        m = self._text_map[index]
        e = m['ui_element']
        idx = m['idx']
        offset = m['offset']
        pre = m['pre']
        tw = Globals.drawing.get_text_width(pre, fontsize=self._fontsize, fontid=self._fontid)
        if e._relative_pos is None: return None
        if e._relative_offset is None: return None
        if e._scroll_offset is None: return None
        e_pos = e._relative_pos + e._relative_offset + e._scroll_offset + RelPoint2D((tw, 0))
        return e_pos

    def get_text_index(self, pos):
        if self._pseudoelement != 'text':
            ui_text = next((child for child in self._children if child._pseudoelement == 'text'), None)
            if not ui_text: return None
            return ui_text.get_text_index(pos)
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
