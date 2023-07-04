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

from .blender import tag_redraw_all
from .ui_styling import UI_Styling, ui_defaultstylings
from .ui_core_utilities import helper_wraptext, convert_token_to_cursor
from .fsm import FSM

from .boundvar import BoundVar
from .debug import debugger, dprint, tprint
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .drawing import Drawing
from .globals import Globals
from .hasher import Hasher
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .maths import floor_if_finite, ceil_if_finite
from .profiler import profiler, time_it
from .utils import iter_head, any_args, join


class LineFitter:
    def __init__(self, *, left, top, width, height):
        self.box          = Box2D(left=left, top=top, width=width, height=height)
        self.max_width    = 0
        self.sum_height   = 0
        self.lines        = []
        self.current_line = None
        self.new_line()

    def new_line(self):
        # width:  sum of all widths added to current line
        # height: max of all heights added to current line
        if not self.is_current_line_empty():
            self.max_width = max(self.max_width, self.current_width)
            self.sum_height = self.sum_height + self.current_height
            self.lines.append(self.current.elements)
        self.current_line = []
        self.current_width = 0
        self.current_height = 0

    def is_current_line_empty(self):
        return not self.current_line

    @property
    def remaining_width(self): return self.box.width - self.current_width
    @property
    def remaining_height(self): return self.box.height - self.sum_height

    def get_next_box(self):
        return Box2D(
            left   = self.box.left + self.current_width,
            top    = -(self.box.top + self.sum_height),
            width  = self.box.width - self.current_width,
            height = self.box.height - self.sum_height,
        )

    def add_element(self, element, size):
        # assuming element is placed in correct spot in line
        if not self.fit(size): self.new_line()
        pos = Box2D(
            left = self.box.left + self.current_width,
            top = -(self.box.top + self.sum_height),
            width = size.smallest_width(),
            height = size.smallest_height(),
        )
        self.current_line.append(element)
        self.current_width += size.smallest_width()
        self.current_height = max(self.current_height, size.smallest_height())
        return pos

    def fit(self, size):
        if size.smallest_width() > self.remaining_width: return False
        if size.smallest_height() > self.remaining_height: return False
        return True


class TableFitter:
    def __init__(self):
        self._cells = {} # keys are Index2D
        self._index = Index2D(0, 0)

    def new_row(self):
        self._index.update(i=0, j_off=1)
    def new_col(self):
        pass

