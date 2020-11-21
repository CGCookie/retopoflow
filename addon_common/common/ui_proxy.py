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

import bpy
import bgl
import blf
import gpu

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
from .utils import iter_head


class UI_Proxy:
    def __init__(self, label, default_element, other_elements=None):
        # NOTE: use self.__dict__ here!!!
        self.__dict__['_proxy_label'] = label
        self.__dict__['_proxy_default_element'] = default_element
        self.__dict__['_proxy_mapping'] = {}
        self.__dict__['_proxy_translate'] = {}
        self.__dict__['_proxy_mapall'] = { 'document' }
        self.__dict__['_proxy_all_elements'] = { default_element }
        self.__dict__['_proxy_other_elements'] = set()
        if other_elements:
            self._proxy_all_elements.update(other_elements)
            self._proxy_other_elements.update(other_elements)

    def __str__(self):
        l = self._proxy_all_elements
        return f'<UI_Proxy label="{self._proxy_label}" def={self._proxy_default_element} others={self._proxy_other_elements}>'

    def __repr__(self):
        return self.__str__()

    def __dir__(self):
        return dir(self._proxy_default_element)

    @property
    def proxy_default_element(self):
        return self._proxy_default_element

    def map_to_all(self, attribs):
        if type(attribs) is str: self._proxy_mapall.add(attribs)
        else: self._proxy_mapall.update(attribs)

    def map(self, attribs, ui_element):
        if type(attribs) is str: attribs = [attribs]
        t = self._proxy_translate
        attribs = [t.get(a, a) for a in attribs]
        for attrib in attribs: self._proxy_mapping[attrib] = ui_element
        self._proxy_all_elements.add(ui_element)
        self._proxy_other_elements.add(ui_element)
        assert ui_element.is_descendant_of(self._proxy_default_element)

    def map_children_to(self, ui_element):
        self.map(['children', 'append_child', 'delete_child', 'clear_children', 'builder'], ui_element)
    def map_scroll_to(self, ui_element):
        self.map(['scrollToTop', 'scrollTop', 'scrollLeft'], ui_element)

    def translate(self, attrib_from, attrib_to):
        self._proxy_translate[attrib_from] = attrib_to

    def translate_map(self, attrib_from, attrib_to, ui_element):
        self.translate(attrib_from, attrib_to)
        self.map([attrib_to], ui_element)
        self._proxy_all_elements.add(ui_element)
        self._proxy_other_elements.add(ui_element)
        assert ui_element.is_descendant_of(self._proxy_default_element)

    def unmap(self, attribs):
        if type(attribs) is str: attribs = [attribs]
        for attrib in attribs: self._proxy_mapping[attrib] = None


    def __getattr__(self, attrib):
        # ignore mapping for attribs with _ prefix
        if attrib.startswith('_') or attrib in self._proxy_mapall:
            return getattr(self._proxy_default_element, attrib)
        attrib = self._proxy_translate.get(attrib, attrib)                                      # translate attrib key (if applicable)
        ui_element = self._proxy_mapping.get(attrib, None) or self._proxy_default_element       # get ui_element associated with attrib key
        return getattr(ui_element, attrib)

    def __setattr__(self, attrib, val):
        # ignore mapping for attribs with _ prefix
        if attrib.startswith('_'):
            return setattr(self._proxy_default_element, attrib, val)
        attrib = self._proxy_translate.get(attrib, attrib)                                      # translate attrib key (if applicable)
        if attrib in self._proxy_mapall:
            for ui_element in self._proxy_other_elements:
                setattr(ui_element, attrib, val)
            return setattr(self._proxy_default_element, attrib, val)
        ui_element = self._proxy_mapping.get(attrib, None) or self._proxy_default_element
        return setattr(ui_element, attrib, val)


    def debug_print(self, d, already_printed):
        sp0 = '    '*d
        sp1 = '    '*(d+1)
        if self in already_printed:
            print('%s<proxy>...</proxy>' % (sp))
            return
        already_printed.add(self)
        print('%s<proxy label="%s">' % (sp0, self._proxy_label))
        print('%s<default>' % sp1)
        self._proxy_default_element.debug_print(d+2, already_printed)
        print('%s</default>' % sp1)
        print('%s<other>' % sp1)
        for c in self._proxy_other_elements:
            c.debug_print(d+2, already_printed)
        print('%s</other>' % sp1)
        print('%s</proxy>' % sp0)

