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

from .ui_core_utilities import UI_Core_Utils
from . import ui_settings

import bpy
import blf
import gpu

from .blender import tag_redraw_all
from .ui_linefitter import LineFitter
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


class UI_Core_Layout:
    '''
    layout each block into lines.  if a content box of child element is too wide to fit in line and the child
    is not the only element on the current line, then end current line, start a new line, relayout the child.

    NOTE: this function does not set the final position and size for element.

    through this function, we are calculating and committing to a certain width and height
    although the parent element might give us something different.  if we end up with a
    different width and height in self.position() below, we will need to improvise by
    adjusting margin (if bigger) or using scrolling (if smaller)

    TODO: allow for horizontal growth rather than biasing for vertical
    TODO: handle flex layouts
    TODO: allow for different line alignments other than top (bottom, baseline)
    TODO: percent_of (style width, height, etc.) could be of last non-static element or document
    TODO: position based on bottom-right,etc.

    NOTE: parent ultimately controls layout and viewing area of child, but uses this layout function to "ask"
          child how much space it would like

    given size might by inf. given can be ignored due to style. constraints applied at end.
    positioning (with definitive size) should happen

    IMPORTANT: as currently written, this function needs to be able to be run multiple times!
               DO NOT PREVENT THIS, otherwise layout bugs will occur!
    '''

    def _layout2(self, **kwargs):
        if self._defer_clean or not self.is_visible: return

        styles  = self._computed_styles
        display = styles.get('display', 'block')

        layout_fns = {
            'inline':     self._layout_inline,
            'block':      self._layout_block,
            'table':      self._layout_table,
            'table-row':  self._layout_table_row,
            'table-cell': self._layout_table_cell,
        }
        layout = layout_fns.get(display, self._layout_block)
        layout(*kwargs)


    def _layout_inline(self, **kwargs):
        pass

    def _layout_block(self, **kwargs):
        pass

    def _layout_table(self, **kwargs):
        pass

    def _layout_table_row(self, **kwargs):
        pass

    def _layout_table_cell(self, **kwargs):
        pass


    @profiler.function
    def _layout(self, **kwargs):
        if not self.is_visible: return
        if self._defer_clean: return

        # linefitter     = kwargs['linefitter']

        fitting_size   = kwargs.get('fitting_size',   None)     # size from parent that we should try to fit in (only max)
        fitting_pos    = kwargs.get('fitting_pos',    None)     # top-left position wrt parent where we go if not absolute or fixed
        parent_size    = kwargs.get('parent_size',    None)     # size of inside of parent
        nonstatic_elem = kwargs.get('nonstatic_elem', None)     # last non-static element
        tabled         = kwargs.get('table_data',     {})       # data structure for current table (could be empty)
        table_elem     = tabled.get('element',        None)     # parent table element
        table_index2D  = tabled.get('index2D',        None)     # current position in table (i=row,j=col)
        table_cells    = tabled.get('cells',          None)     # cells of table as tuples (element, size)

        styles    = self._computed_styles
        style_pos = styles.get('position', 'static')

        self._fitting_pos     = fitting_pos
        self._fitting_size    = fitting_size
        self._parent_size     = parent_size
        self._absolute_pos    = None
        self._nonstatic_elem  = nonstatic_elem
        self._tablecell_table = None
        self._tablecell_pos   = None
        self._tablecell_size  = None

        self.update_position()

        if not self._dirtying_flow and not self._dirtying_children_flow and not tabled:
            return

        if ui_settings.DEBUG_LIST:
            self._debug_list.append(f'{time.ctime()} layout self={self._dirtying_flow} children={self._dirtying_children_flow} fitting_size={fitting_size}')

        if self._dirtying_children_flow:
            for child in self._children_all:
                child.dirty_flow(parent=False)
            if ui_settings.DEBUG_LIST: self._debug_list.append(f'    reflowing children')
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

        self._mbp_left   = mbp_left
        self._mbp_top    = mbp_top
        self._mbp_right  = mbp_right
        self._mbp_bottom = mbp_bottom
        self._mbp_width  = mbp_width
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

        dw, dh = 0, 0

        if self._static_content_size:
            # self has static content size: images and text blocks

            dw, dh = self._static_content_size.size

            if self._src in {'image' ,'image loading'}:
                def scale_dw_dh(num, den):
                    nonlocal dw,dh
                    sc = 0 if den == 0 else num / den
                    dw, dh = dw*sc, dh*sc
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

            # print(f'{self} {self._blocks}')

            if self._innerText is not None and self._whitespace in {'nowrap', 'pre'}:
                inside_size.min_width = inside_size.width = inside_size.max_width = float('inf')

            if display == 'table':
                table_elem = self
                table_index2D = Index2D(0, 0)
                table_cells = {}
                tabled = { 'elem': table_elem, 'index2D': table_index2D, 'cells': table_cells }

            working_width  = (inside_size.width  if inside_size.width  is not None else (inside_size.max_width  if inside_size.max_width  is not None else float('inf')))
            working_height = (inside_size.height if inside_size.height is not None else (inside_size.max_height if inside_size.max_height is not None else float('inf')))
            if overflow_y in {'scroll', 'auto'}: working_height = float('inf')

            def flatten(block):
                if type(block) is list: return [element for e in block for element in flatten(e)]
                # assuming block is UI_Element
                if block._pseudoelement == 'text': return flatten(block._children_all)
                display = block._computed_styles.get('display', 'block')
                if display == 'none': return []
                if display in {'block', 'table', 'table-row', 'table-cell'}: return [block]
                if display in {'inline'}: return flatten(block._children_all)
                # print(f'flatten {self} {display}')
                return [block]

            # fitter = LineFitter(left=mbp_left, top=mbp_top, width=working_width, height=working_height)

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
                            # linefitter=fitter,
                            fitting_size=remaining,
                            fitting_pos=pos,
                            parent_size=inside_size,
                            nonstatic_elem=next_nonstatic_elem,
                            table_data=tabled,
                        )
                        w, h = math.ceil(element._dynamic_full_size.width), math.ceil(element._dynamic_full_size.height)
                        element_fits = False
                        element_fits |= not cur_line                 # always add child to an empty line
                        element_fits |= c and w<=rw and h<=rh        # child fits on current line
                        element_fits |= not c                        # child does not contribute to our size
                        element_fits |= self._innerText is not None and self._whitespace in {'nowrap', 'pre'}
                        if element_fits:
                            if c:
                                cur_line.append(element)
                                #cur_line.extend(flatten(element))
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
            # print(f'{self}:')
            # for l,w,h in accum_lines:
            #     print(f'   {len(l)} {l}')

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

        dw = math.ceil(dw) if math.isfinite(dw) else 100000
        dh = math.ceil(dh) if math.isfinite(dh) else 100000

        self._dynamic_full_size = Size2D(width=dw, height=dh)


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


        # reposition
        self.update_position()


        # position all absolute positioned children
        for element in self._blocks_abs:
            if not element.is_visible: continue
            position = element._computed_styles.get('position', 'static')
            if position == 'absolute':
                # fitting_size = Size2D(max_width=self._dynamic_content_size.width, max_height=self._dynamic_content_size.height)
                fitting_size = Size2D(max_width=float('inf'), max_height=float('inf'))
                parent_size = self._dynamic_full_size
            elif position == 'fixed':
                fitting_size = Size2D(max_width=self._document.body._dynamic_content_size.width, max_height=self._document.body._dynamic_content_size.height)
                parent_size = self._document.body._dynamic_full_size
            element._layout(
                # linefitter=LineFitter(),
                fitting_size=fitting_size,
                fitting_pos=Point2D((0, 0)),
                parent_size=parent_size,
                nonstatic_elem=next_nonstatic_elem,
                table_data={},
            )
            w, h = math.ceil(element._dynamic_full_size.width), math.ceil(element._dynamic_full_size.height)
            sz = Size2D(width=w, height=h)
            element.set_view_size(sz)

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
            relative_element = self._document.body if style_pos == 'fixed' else self._nonstatic_elem
            if relative_element is None or relative_element == self:
                mbp_left = mbp_top = 0
            else:
                mbp_left = relative_element._mbp_left
                mbp_top  = relative_element._mbp_top
            if pl == 'auto': pl = 0
            if pt == 'auto': pt = 0
            if relative_element and relative_element != self and self._clamp_to_parent:
                parent_width  = (relative_element._dynamic_full_size or self._parent_size).get_width_midmaxmin()  or 0
                parent_height = (relative_element._dynamic_full_size or self._parent_size).get_height_midmaxmin() or 0
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

        if ui_settings.DEBUG_LIST: self._debug_list.append(f'{time.ctime()} set_view_size({size})')

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

    # @UI_Core_Utils.add_option_callback('layout:flexbox')
    # def layout_flexbox(self):
    #     style = self._computed_styles
    #     direction = style.get('flex-direction', 'row')
    #     wrap = style.get('flex-wrap', 'nowrap')
    #     justify = style.get('justify-content', 'flex-start')
    #     align_items = style.get('align-items', 'flex-start')
    #     align_content = style.get('align-content', 'flex-start')

    # @UI_Core_Utils.add_option_callback('layout:block')
    # def layout_block(self):
    #     pass

    # @UI_Core_Utils.add_option_callback('layout:inline')
    # def layout_inline(self):
    #     pass

    # @UI_Core_Utils.add_option_callback('layout:none')
    # def layout_none(self):
    #     pass


