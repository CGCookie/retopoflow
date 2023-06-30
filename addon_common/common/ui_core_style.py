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

import time

from . import ui_settings  # needs to be first

from .ui_core_defaults  import UI_Core_Defaults
from .ui_core_fonts     import get_font
from .ui_core_utilities import UI_Core_Utils
from .ui_draw           import ui_draw
from .ui_styling        import UI_Styling, ui_defaultstylings

from .globals import Globals
from .hasher import Hasher
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .profiler import profiler, time_it
from .utils import iter_head, any_args, join


class UI_Core_Style:

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
        styling_trimmed = UI_Styling.trim_styling(selector, ui_defaultstylings, ui_draw.default_stylesheet)

        if ui_settings.DEBUG_LIST: self._debug_list.append(f'{time.ctime()} selector: {" ".join(selector)}')

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


    @UI_Core_Utils.add_cleaning_callback('selector', {'style', 'style parent'})
    @profiler.function
    def _compute_selector(self):
        if self.defer_clean: return
        if 'selector' not in self._dirty_properties:
            self.defer_clean = True
            with profiler.code('selector.calling back callbacks'):
                for e in list(self._dirty_callbacks.get('selector', [])):
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


    @UI_Core_Utils.add_cleaning_callback('style', {'size', 'content', 'renderbuf'})
    @UI_Core_Utils.add_cleaning_callback('style parent', {'size', 'content', 'renderbuf'})
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

        if ui_settings.DEBUG_LIST: self._debug_list.append(f'{time.ctime()} style')

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
                text_styles.get('font-family', UI_Core_Defaults.font_family),
                text_styles.get('font-style',  UI_Core_Defaults.font_style),
                text_styles.get('font-weight', UI_Core_Defaults.font_weight),
            )
            self._fontsize   = text_styles.get('font-size',   UI_Core_Defaults.font_size).val()
            self._fontcolor  = text_styles.get('color',       UI_Core_Defaults.font_color)
            self._whitespace = text_styles.get('white-space', UI_Core_Defaults.whitespace)
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
                if ui_settings.DEBUG_LIST: self._debug_list.append(f'    possible content change')
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
                if ui_settings.DEBUG_LIST: self._debug_list.append(f'    possible size change')
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
