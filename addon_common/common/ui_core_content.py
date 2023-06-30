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

import re
import time
from math import floor, ceil
from concurrent.futures import ThreadPoolExecutor


from . import ui_settings  # needs to be first
from .ui_core_images    import get_loading_image, is_image_cached, load_texture, async_load_image, load_image
from .ui_core_utilities import UI_Core_Utils, helper_wraptext, convert_token_to_cursor

from .globals  import Globals
from .maths    import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .profiler import profiler, time_it

from . import html_to_unicode



class UI_Core_Content:
    def _init_content(self):
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

        # TODO: REPLACE WITH BETTER PROPERTIES AND DELETE!!
        self._preferred_width, self._preferred_height = 0,0
        self._content_width,   self._content_height   = 0,0

        self._viewing_box = Box2D(topleft=(0,0), size=(-1,-1))  # topleft+size: set by parent element
        self._inside_box  = Box2D(topleft=(0,0), size=(-1,-1))  # inside area of viewing box (less margins, paddings, borders)
        self._content_box = Box2D(topleft=(0,0), size=(-1,-1))  # topleft: set by scrollLeft, scrollTop properties
                                                                # size: determined from children and style

        # various sizes and boxes (set in self._position), used for layout and drawing
        self._preferred_size = Size2D()                         # computed preferred size, set in self._layout, used as suggestion to parent
        self._pref_content_size = Size2D()                      # size of content
        self._pref_full_size = Size2D()                         # _pref_content_size + margins + border + padding
        self._box_draw = Box2D(topleft=(0,0), size=(-1,-1))     # where UI will be drawn (restricted by parent)
        self._box_full = Box2D(topleft=(0,0), size=(-1,-1))     # where UI would draw if not restricted (offset for scrolling)


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

    @UI_Core_Utils.add_cleaning_callback('content', {'blocks', 'renderbuf', 'style'})
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
        if ui_settings.DEBUG_LIST: self._debug_list.append(f'{time.ctime()} content')

        # self.defer_dirty_propagation = True
        self._children_gen = []

        content_before = self._computed_styles_before.get('content', None) if self._computed_styles_before else None
        if content_before is not None:
            # TODO: cache this!!
            self._child_before = self.new_element(tagName=self._tagName, innerText=content_before, pseudoelement='before', _parent=self)
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
            self._child_after = self.new_element(tagName=self._tagName, innerText=content_after, pseudoelement='after', _parent=self)
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
                        for f,t in html_to_unicode.no_arrows.items(): word = word.replace(f, t)
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
            if ui_settings.ASYNC_IMAGE_LOADING and not self._pseudoelement and not is_image_cached(self.src):
                # print(f'LOADING {self.src} ASYNC')
                if self._src == 'image':
                    self._new_content = True
                elif self._src == 'image loading':
                    pass
                elif self._src == 'image loaded':
                    self._src = 'image'
                    self._image_data = load_texture(
                        self.src,
                        image=self._image_data,
                    )
                    self._new_content = True
                    self.dirty_styling()
                    self.dirty_flow()
                    self.dirty(parent=True, children=True)
                else:
                    self._src = 'image loading'
                    self._image_data = load_texture(f'image loading {self.src}', image=get_loading_image(self.src))
                    self._new_content = True
                    def callback(image):
                        self._src = 'image loaded'
                        self._image_data = image
                        self._new_content = True
                        self.dirty_styling()
                        self.dirty_flow()
                        self.dirty(parent=True, children=True)
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
            if ui_settings.DEBUG_LIST: self._debug_list.append(f'    possible new content')
            self._new_content = False
        self._dirty_properties.discard('content')
        self._dirty_callbacks['content'].clear()

        # self.defer_dirty_propagation = False

    @UI_Core_Utils.add_cleaning_callback('blocks', {'size', 'renderbuf'})
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
            for e in list(self._dirty_callbacks.get('blocks', [])): e._compute_blocks()
            self._dirty_callbacks['blocks'].clear()
            return

        self._clean_debugging['blocks'] = time.time()
        if ui_settings.DEBUG_LIST: self._debug_list.append(f'{time.ctime()} blocks')

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
            if ui_settings.DEBUG_LIST: self._debug_list.append(f'    reflowing')

        self._dirty_properties.discard('blocks')
        self._dirty_callbacks['blocks'].clear()

        # self.defer_dirty_propagation = False

    ################################################################################################
    # NOTE: COMPUTE STATIC CONTENT SIZE (TEXT, IMAGE, ETC.), NOT INCLUDING MARGIN, BORDER, PADDING
    #       WE MIGHT NOT NEED TO COMPUTE MIN AND MAX??
    @UI_Core_Utils.add_cleaning_callback('size', {'renderbuf'})
    @profiler.function
    def _compute_static_content_size(self):
        if self.defer_clean:
            return
        if not self.is_visible:
            self._dirty_properties.discard('size')
            return
        if 'size' not in self._dirty_properties:
            for e in set(self._dirty_callbacks.get('size', [])):
                e._compute_static_content_size()
                self._dirty_callbacks['size'].remove(e)
            #self._dirty_callbacks['size'].clear()
            return

        # if self.record_multicall('_compute_static_content_size'): return

        self._clean_debugging['size'] = time.time()
        if ui_settings.DEBUG_LIST: self._debug_list.append(f'{time.ctime()} static content size')

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
                try:
                    w, h = float(self._image_data['width']), float(self._image_data['height'])
                    static_content_size.set_all_widths(w * dpi_mult)
                    static_content_size.set_all_heights(h * dpi_mult)
                except:
                    pass

        else:
            static_content_size = None

        if static_content_size != self._static_content_size:
            self._static_content_size = static_content_size
            self.dirty_renderbuf(cause='static content changes might change render')
            self.dirty_flow()
            if ui_settings.DEBUG_LIST: self._debug_list.append(f'    reflowing')
        # self.defer_dirty_propagation = False
        self._dirty_properties.discard('size')
        self._dirty_callbacks['size'].clear()
