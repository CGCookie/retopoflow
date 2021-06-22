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
import math
import time
import types
import codecs
import struct
import random
import inspect
import traceback
import functools
import urllib.request
from itertools import chain
from concurrent.futures import ThreadPoolExecutor

import bpy
import bgl

from .ui_utilities import UIRender_Block, UIRender_Inline, get_unique_ui_id
from .utils import kwargopts, kwargs_translate, kwargs_splitter, iter_head
from .ui_styling import UI_Styling

from .boundvar import BoundVar, BoundFloat, BoundInt, BoundString, BoundStringToBool, BoundBool
from .decorators import blender_version_wrapper
from .drawing import Drawing, ScissorStack
from .fontmanager import FontManager
from .globals import Globals
from .maths import Point2D, Vec2D, clamp, mid, Color, Box2D, Size2D, NumberUnit
from .markdown import Markdown
from .profiler import profiler, time_it
from .utils import Dict, delay_exec, get_and_discard, strshort, abspath


from ..ext import png


'''
Notes about addon_common's UI system

- The system is designed similarly to how the Browser will render HTML+CSS
- All UI elements are containers
- All classes herein are simply "starter" UI elements
    - You can freely change all properties to make any element turn into another
- Styling
    - Styling specified here is base styling for UI elements of same type
    - Base styling specified here are overridden by stylesheet, which is overridden by custom styling
    - Note: changing tagname will not reset the base styling.  in other words, if the element starts off
            as a UI_Button, changing tagname to "flexbox" will not change base styling from what is
            specified in UI_Button.


Implementation details

- root element will be sized to entire 3D view region
- each element
    - is responsible for communicating with children
    - will estimate its size (min, max, preferred), but these are only suggestions for the parent
    - dictates size and position of its children
    - must submit to the sizing and position given by the parent

See top comment in `ui_utilities.py` for links to useful resources.
'''




def get_mdown_path(fn, ext=None, subfolders=None):
    # if no subfolders are given, assuming image path is <root>/icons
    # or <root>/images where <root> is the 2 levels above this file
    if subfolders is None:
        subfolders = ['help']
    if ext:
        fn = '%s.%s' % (fn,ext)
    paths = [abspath('..', '..', p, fn) for p in subfolders]
    paths += [abspath('images', fn)]
    paths = [p for p in paths if os.path.exists(p)]
    return iter_head(paths, None)

def load_text_file(path):
    try: return open(path, 'rt').read()
    except: pass
    try: return codecs.open(path, encoding='utf-8').read()
    except: pass
    try: return codecs.open(path, encoding='utf-16').read()
    except Exception as e:
        print('Could not load text file:', path)
        print('Exception:', e)
        assert False


class UI_Markdown:
    @profiler.function
    def set_markdown(self, mdown=None, mdown_path=None, preprocess_fns=None, f_globals=None, f_locals=None, frame_depth=1):
        if f_globals is None or f_locals is None:
            frame = inspect.currentframe()                      # get frame   of calling function
            for _ in range(frame_depth): frame = frame.f_back
            if f_globals is None: f_globals = frame.f_globals   # get globals of calling function
            if f_locals  is None: f_locals  = frame.f_locals    # get locals  of calling function

        self._src_mdown_path = mdown_path or ''

        if mdown_path: mdown = load_text_file(get_mdown_path(mdown_path))
        if preprocess_fns:
            for preprocess_fn in preprocess_fns:
                mdown = preprocess_fn(mdown)
        mdown = Markdown.preprocess(mdown or '')                # preprocess mdown
        if getattr(self, '__mdown', None) == mdown: return  # ignore updating if it's exactly the same as previous
        self.__mdown = mdown                                # record the mdown to prevent reprocessing same

        def process_words(text, word_fn):
            build = ''
            while text:
                word,text = Markdown.split_word(text)
                build += word
                #word_fn(word)
            word_fn(build)

        def process_para(container, para, **kwargs):
            with container.defer_dirty('creating new children'):
                opts = kwargopts(kwargs, classes='')

                # break each ui_item onto it's own line
                para = re.sub(r'\n', ' ', para)     # join sentences of paragraph
                para = re.sub(r' +', ' ', para)     # 1+ spaces => 1 space

                # TODO: revisit this, and create an actual parser
                para = para.lstrip()
                while para:
                    t,m = Markdown.match_inline(para)
                    if t is None:
                        build = ''
                        while t is None and para:
                            word,para = Markdown.split_word(para)
                            build += word
                            t,m = Markdown.match_inline(para)
                        container.append_new_child(tagName='text', innerText=build, pseudoelement='text')
                    else:
                        if t == 'br':
                            container.append_new_child(tagName='BR')
                        elif t == 'arrow':
                            d = {   # https://www.toptal.com/designers/htmlarrows/arrows/
                                'uarr': '↑',
                                'darr': '↓',
                                'larr': '←',
                                'rarr': '→',
                                'harr': '↔',
                                'varr': '↕',
                                'uArr': '⇑',
                                'dArr': '⇓',
                                'lArr': '⇐',
                                'rArr': '⇒',
                                'hArr': '⇔',
                                'vArr': '⇕',
                            }[m.group('dir')]
                            container.append_new_child(tagName='span', classes='html-arrow', innerText=f'{d}')
                        elif t == 'img':
                            style = m.group('style').strip() or None
                            container.append_new_child(tagName='img', classes='inline', style=style, src=m.group('filename'), title=m.group('caption'))
                        elif t == 'code':
                            container.append_new_child(tagName='code', innerText=m.group('text'))
                        elif t == 'link':
                            link = m.group('link')
                            title = 'Click to open URL in default web browser' if Markdown.is_url(link) else 'Click to open help'
                            def mouseclick():
                                if Markdown.is_url(link):
                                    bpy.ops.wm.url_open(url=link)
                                else:
                                    self.set_markdown(mdown_path=link, preprocess_fns=preprocess_fns, f_globals=f_globals, f_locals=f_locals)
                            process_words(m.group('text'), lambda word: container.append_new_child(tagName='a', innerText=word, href=link, title=title, on_mouseclick=mouseclick))
                        elif t == 'bold':
                            process_words(m.group('text'), lambda word: container.append_new_child(tagName='b', innerText=word))
                        elif t == 'italic':
                            process_words(m.group('text'), lambda word: container.append_new_child(tagName='i', innerText=word))
                        elif t == 'checkbox':
                            params = m.group('params')
                            innertext = m.group('innertext')
                            value = None
                            for param in re.finditer(r'(?P<key>[a-zA-Z]+)(="(?P<val>.*?)")?', params):
                                key = param.group('key')
                                val = param.group('val')
                                if key == 'type':
                                    pass
                                elif key == 'value':
                                    value = val
                                else:
                                    assert False, 'Unhandled checkbox parameter key="%s", val="%s" (%s)' % (key,val,param)
                            assert value is not None, 'Unhandled checkbox parameters: expected value (%s)' % (params)
                            # print('CREATING input_checkbox(label="%s", checked=BoundVar("%s", ...)' % (innertext, value))
                            ui_label = container.append_new_child(tagName='label')
                            ui_label.append_new_child(tagName='input', type='checkbox', checked=BoundVar(value, f_globals=f_globals, f_locals=f_locals))
                            ui_label.append_new_child(tagName='text', innerText=innertext, pseudoelement='text')
                        else:
                            assert False, 'Unhandled inline markdown type "%s" ("%s") with "%s"' % (str(t), str(m), line)
                        para = para[m.end():]

        def process_mdown(ui_container, mdown):
            #paras = mdown.split('\n\n')         # split into paragraphs
            paras = re.split(r'\n\n(?!    )', mdown)
            for para in paras:
                t,m = Markdown.match_line(para)

                if t is None:
                    p_element = ui_container.append_new_child(tagName='p')
                    process_para(p_element, para)

                elif t in ['h1','h2','h3']:
                    ui_hn = ui_container.append_new_child(tagName=t)
                    process_para(ui_hn, m.group('text'))

                elif t == 'ul':
                    ui_ul = ui_container.append_new_child(tagName='ul')
                    with ui_ul.defer_dirty('creating ul children'):
                        # add newline at beginning so that we can skip the first item (before "- ")
                        skip_first = True
                        para = f'\n{para}'
                        for litext in re.split(r'\n- ', para):
                            if skip_first:
                                skip_first = False
                                continue
                            ui_li = ui_ul.append_new_child(tagName='li')
                            if '\n' in litext:
                                # remove leading spaces
                                litext = '\n'.join(l.lstrip() for l in litext.split('\n'))
                                process_mdown(ui_li, litext)
                            else:
                                process_para(ui_li, litext)

                elif t == 'ol':
                    ui_ol = ui_container.append_new_child(tagName='ol')
                    with ui_ol.defer_dirty('creating ol children'):
                        # add newline at beginning so that we can skip the first item (before "- ")
                        skip_first = True
                        para = f'\n{para}'
                        for ili,litext in enumerate(re.split(r'\n\d+\. ', para)):
                            if skip_first:
                                skip_first = False
                                continue
                            ui_li = ui_ol.append_new_child(tagName='li')
                            #ui_li.append_new_child(tagName='span', classes='number', innerText=f'{ili}.')
                            #span_element = ui_li.append_new_child(tagName='span', classes='text')
                            if '\n' in litext:
                                # remove leading spaces
                                litext = '\n'.join(l.strip() for l in litext.split('\n'))
                                process_mdown(ui_li, litext)
                            else:
                                process_para(ui_li, litext)

                elif t == 'img':
                    style = m.group('style').strip() or None
                    ui_container.append_new_child(tagName='img', style=style, src=m.group('filename'), title=m.group('caption'))

                elif t == 'table':
                    # table!
                    def split_row(row):
                        row = re.sub(r'^\| ', r'', row)
                        row = re.sub(r' \|$', r'', row)
                        return [col.strip() for col in row.split(' | ')]
                    data = [l for l in para.split('\n')]
                    header = split_row(data[0])
                    add_header = any(header)
                    align = data[1]
                    data = [split_row(row) for row in data[2:]]
                    rows,cols = len(data),len(data[0])
                    table_element = ui_container.append_new_child(tagName='table')
                    with table_element.defer_dirty('creating table children'):
                        if add_header:
                            tr_element = table_element.append_new_child(tagName='tr')
                            for c in range(cols):
                                tr_element.append_new_child(tagName='th', innerText=header[c])
                        for r in range(rows):
                            tr_element = table_element.append_new_child(tagName='tr')
                            for c in range(cols):
                                td_element = tr_element.append_new_child(tagName='td')
                                process_para(td_element, data[r][c])

                else:
                    assert False, 'Unhandled markdown line type "%s" ("%s") with "%s"' % (str(t), str(m), para)

        if self._document: self._document.defer_cleaning = True

        self.defer_clean = True
        with self.defer_dirty('creating new children'):
            self.clear_children()
            self.scrollToTop(force=True)
            process_mdown(self, mdown)
            if self.parent: self.parent.scrollToTop(force=True)
        self.defer_clean = False

        if self._document: self._document.defer_cleaning = False



