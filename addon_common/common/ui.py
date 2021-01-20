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

from .ui_core import UI_Element
from .ui_proxy import UI_Proxy
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
from .useractions import is_keycode
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



def button(**kwargs):
    return UI_Element(tagName='button', **kwargs)

def p(**kwargs):
    return UI_Element(tagName='p', **kwargs)

def a(**kwargs):
    return UI_Element(tagName='a', **kwargs)

def b(**kwargs):
    return UI_Element(tagName='b', **kwargs)

def i(**kwargs):
    return UI_Element(tagName='i', **kwargs)

def div(**kwargs):
    return UI_Element(tagName='div', **kwargs)

def span(**kwargs):
    return UI_Element(tagName='span', **kwargs)

def h1(**kwargs):
    return UI_Element(tagName='h1', **kwargs)

def h2(**kwargs):
    return UI_Element(tagName='h2', **kwargs)

def h3(**kwargs):
    return UI_Element(tagName='h3', **kwargs)

def pre(**kwargs):
    return UI_Element(tagName='pre', **kwargs)

def code(**kwargs):
    return UI_Element(tagName='code', **kwargs)

def br(**kwargs):
    return UI_Element(tagName='br', **kwargs)

def img(**kwargs):
    return UI_Element(tagName='img', **kwargs)

def table(**kwargs):
    return UI_Element(tagName='table', **kwargs)
def tr(**kwargs):
    return UI_Element(tagName='tr', **kwargs)
def th(**kwargs):
    return UI_Element(tagName='th', **kwargs)
def td(**kwargs):
    return UI_Element(tagName='td', **kwargs)

def textarea(**kwargs):
    return UI_Element(tagName='textarea', **kwargs)

def dialog(**kwargs):
    return UI_Element(tagName='dialog', **kwargs)

def details(**kwargs):
    return UI_Element(tagName='details', **kwargs)

def summary(**kwargs):
    return UI_Element(tagName='summary', **kwargs)

def input_text(value='', scrub=False, **kwargs):
    return UI_Element(tagName='input', type='text', value=value, can_focus=True, **kwargs)

def input_radio(**kwargs):
    return UI_Element(tagName='input', type='radio', **kwargs)

def input_checkbox(**kwargs):
    return UI_Element(tagName='input', type='checkbox', **kwargs)

def label(**kwargs):
    return UI_Element(tagName='label', **kwargs)


def input_range(value=None, min_value=None, max_value=None, step_size=None, **kwargs):
    # right now, step_size is not used
    t = type(value)
    if t in {BoundFloat, BoundInt}:
        # (possibly) override min/max/step of value
        # if not None, choose max of min_value param and value's min_value
        # if not None, choose min of max_value param and value's max_value
        # if not None, choose step_size param
        overrides = {}
        if min_value is not None: overrides['min_value'] = max(min_value, value.min_value)
        if max_value is not None: overrides['max_value'] = min(max_value, value.max_value)
        if step_size is not None: overrides['step_size'] = step_size
        if overrides: value = value.clone_with_overrides(**overrides)
    elif t in {float, int}:
        # assuming value is float!
        assert max_value is not None and min_value is not None, f'UI input range with non-bound value ({value}, {t}) must have both min and max specified ({min_value}, {max_value})'
        value = BoundFloat('value', min_value=min_value, max_value=max_value, step_size=step_size)
    else:
        assert False, f'Unhandled UI input range value type ({t})'

    kw_container = kwargs_splitter({'parent'}, kwargs)

    ui_container = UI_Element(tagName='div', classes='inputrange-container', **kw_container)
    ui_input = UI_Element(tagName='input', classes='inputrange-input', type='range', atomic=True, parent=ui_container, value=value, **kwargs)
    ui_left = UI_Element(tagName='span', classes='inputrange-left', parent=ui_input)
    ui_right = UI_Element(tagName='span', classes='inputrange-right', parent=ui_input)
    ui_handle = UI_Element(tagName='span', classes='inputrange-handle', parent=ui_input)

    state = Dict()
    state.reset = delay_exec('''state.set(grabbed=False, down=None, initval=None, cancelled=False)''')
    state.reset()
    state.cancel = delay_exec('''value.value = state.initval; state.cancelled = True''')

    def postflow():
        if not ui_input.is_visible: return
        # since ui_left, ui_right, and ui_handle are all absolutely positioned UI elements,
        # we can safely move them around without dirtying (the UI system does not need to
        # clean anything or reflow the elements)

        w, W = ui_handle.width_scissor, ui_input.width_scissor
        if w == 'auto' or W == 'auto': return   # UI system is not ready yet
        W -= ui_container._mbp_width

        mw = W - w                  # max dist the handle can move
        p = value.bounded_ratio     # convert value to [0,1] based on min,max
        hl = p * mw                 # find where handle (left side) should be
        m = hl + (w / 2)            # compute center of handle
        ui_left.width_override = math.floor(m)
        ui_right.width_override = math.floor(W-m)
        ui_right._alignment_offset = Vec2D((math.ceil(m), 0))
        ui_handle._alignment_offset = Vec2D((math.floor(hl), 0))
        ui_left.dirty(cause='input range value changed', properties='renderbuf')
        ui_right.dirty(cause='input range value changed', properties='renderbuf')

    def handle_mousedown(e):
        if e.button[2] and state['grabbed']:
            # right mouse button cancels
            state.cancel()
            e.stop_propagation()
            return
        if not e.button[0]: return
        state.set(
            grabbed=True,
            down=e.mouse,
            initval=value.value,
            cancelled=False,
        )
        e.stop_propagation()
    def handle_mouseup(e):
        if e.button[0]: return
        e.stop_propagation()
        state.reset()
    def handle_mousemove(e):
        if not state.grabbed or state.cancelled: return
        m, M = value.min_value, value.max_value
        p = (e.mouse.x - state['down'].x) / ui_input.width_pixels
        value.value = state.initval + p * (M - m)
        e.stop_propagation()
        postflow()
    def handle_keypress(e):
        if not state.grabbed or state.cancelled: return
        if type(e.key) is int and is_keycode(e.key, 'ESC'):
            state.cancel()
            e.stop_propagation()
    ui_input.add_eventListener('on_mousemove', handle_mousemove, useCapture=True)
    ui_input.add_eventListener('on_mousedown', handle_mousedown, useCapture=True)
    ui_input.add_eventListener('on_mouseup',   handle_mouseup,   useCapture=True)
    ui_input.add_eventListener('on_keypress',  handle_keypress,  useCapture=True)

    ui_handle.postflow = postflow
    value.on_change(postflow)

    ui_proxy = UI_Proxy('input_range', ui_container)
    ui_proxy.map(['value'], ui_input)
    ui_proxy.map_to_all({'title'})
    return ui_proxy





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

@profiler.function
def set_markdown(ui_mdown, mdown=None, mdown_path=None, preprocess_fns=None, f_globals=None, f_locals=None):
    if f_globals is None or f_locals is None:
        frame = inspect.currentframe().f_back               # get frame   of calling function
        if f_globals is None: f_globals = frame.f_globals   # get globals of calling function
        if f_locals  is None: f_locals  = frame.f_locals    # get locals  of calling function

    if mdown_path: mdown = load_text_file(get_mdown_path(mdown_path))
    if preprocess_fns:
        for preprocess_fn in preprocess_fns:
            mdown = preprocess_fn(mdown)
    mdown = Markdown.preprocess(mdown or '')                # preprocess mdown
    if getattr(ui_mdown, '__mdown', None) == mdown: return  # ignore updating if it's exactly the same as previous
    ui_mdown.__mdown = mdown                                # record the mdown to prevent reprocessing same

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
                    UI_Element.TEXT(innerText=build, pseudoelement='text', parent=container)
                else:
                    if t == 'br':
                        UI_Element.BR(parent=container)
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
                        UI_Element.SPAN(classes='html-arrow', innerText=f'{d}', parent=container)
                    elif t == 'img':
                        style = m.group('style').strip() or None
                        UI_Element.IMG(classes='inline', style=style, src=m.group('filename'), title=m.group('caption'), parent=container)
                    elif t == 'code':
                        UI_Element.CODE(innerText=m.group('text'), parent=container)
                    elif t == 'link':
                        text,link = m.group('text'),m.group('link')
                        title = 'Click to open URL in default web browser' if Markdown.is_url(link) else 'Click to open help'
                        def mouseclick():
                            if Markdown.is_url(link):
                                bpy.ops.wm.url_open(url=link)
                            else:
                                set_markdown(ui_mdown, mdown_path=link, preprocess_fns=preprocess_fns, f_globals=f_globals, f_locals=f_locals)
                        process_words(text, lambda word: UI_Element.A(innerText=word, href=link, title=title, on_mouseclick=mouseclick, parent=container))
                    elif t == 'bold':
                        process_words(m.group('text'), lambda word: UI_Element.B(innerText=word, parent=container))
                    elif t == 'italic':
                        process_words(m.group('text'), lambda word: UI_Element.I(innerText=word, parent=container))
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
                        UI_Element.LABEL(children=[
                            UI_Element.INPUT(type='checkbox', checked=BoundVar(value, f_globals=f_globals, f_locals=f_locals)),
                            UI_Element.TEXT(innerText=innertext, pseudoelement='text'),
                        ], parent=container)
                    else:
                        assert False, 'Unhandled inline markdown type "%s" ("%s") with "%s"' % (str(t), str(m), line)
                    para = para[m.end():]

    def process_mdown(ui_container, mdown):
        #paras = mdown.split('\n\n')         # split into paragraphs
        paras = re.split(r'\n\n(?!    )', mdown)
        for para in paras:
            t,m = Markdown.match_line(para)

            if t is None:
                p_element = UI_Element.P(parent=ui_container)
                process_para(p_element, para)

            elif t in ['h1','h2','h3']:
                hn = {'h1':UI_Element.H1, 'h2':UI_Element.H2, 'h3':UI_Element.H3}[t]
                ui_hn = hn(parent=ui_container)
                process_para(ui_hn, m.group('text'))

            elif t == 'ul':
                ui_ul = UI_Element.UL(parent=ui_container)
                with ui_ul.defer_dirty('creating ul children'):
                    # add newline at beginning so that we can skip the first item (before "- ")
                    skip_first = True
                    para = f'\n{para}'
                    for litext in re.split(r'\n- ', para):
                        if skip_first:
                            skip_first = False
                            continue
                        ui_li = UI_Element.LI(parent=ui_ul)
                        if '\n' in litext:
                            # remove leading spaces
                            litext = '\n'.join(l.lstrip() for l in litext.split('\n'))
                            process_mdown(ui_li, litext)
                        else:
                            process_para(ui_li, litext)

            elif t == 'ol':
                ui_ol = UI_Element.OL(parent=ui_container)
                with ui_ol.defer_dirty('creating ol children'):
                    # add newline at beginning so that we can skip the first item (before "- ")
                    skip_first = True
                    para = f'\n{para}'
                    for ili,litext in enumerate(re.split(r'\n\d+\. ', para)):
                        if skip_first:
                            skip_first = False
                            continue
                        ui_li = UI_Element.LI(parent=ui_ol)
                        UI_Element.SPAN(classes='number', innerText=f'{ili}.', parent=ui_li)
                        span_element = UI_Element.SPAN(classes='text', parent=ui_li)
                        process_para(span_element, litext)

            elif t == 'img':
                style = m.group('style').strip() or None
                UI_Element.IMG(style=style, src=m.group('filename'), title=m.group('caption'), parent=ui_container)

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
                table_element = UI_Element.TABLE(parent=ui_container)
                with table_element.defer_dirty('creating table children'):
                    if add_header:
                        tr_element = UI_Element.TR(parent=table_element)
                        for c in range(cols):
                            UI_Element.TH(innerText=header[c], parent=tr_element)
                    for r in range(rows):
                        tr_element = UI_Element.TR(parent=table_element)
                        for c in range(cols):
                            td_element = UI_Element.TD(parent=tr_element)
                            process_para(td_element, data[r][c])

            else:
                assert False, 'Unhandled markdown line type "%s" ("%s") with "%s"' % (str(t), str(m), para)

    if ui_mdown._document: ui_mdown._document.defer_cleaning = True
    with ui_mdown.defer_dirty('creating new children'):
        ui_mdown.clear_children()
        ui_mdown.scrollToTop(force=True)
        process_mdown(ui_mdown, mdown)
        if ui_mdown.parent: ui_mdown.parent.scrollToTop(force=True)

    if ui_mdown._document: ui_mdown._document.defer_cleaning = False


def markdown(mdown=None, mdown_path=None, preprocess_fns=None, f_globals=None, f_locals=None, ui_container=None, **kwargs):
    if f_globals is None or f_locals is None:
        frame = inspect.currentframe().f_back               # get frame   of calling function
        if f_globals is None: f_globals = frame.f_globals   # get globals of calling function
        if f_locals  is None: f_locals  = frame.f_locals    # get locals  of calling function

    if not ui_container: ui_container = UI_Element(tagName='article', classes='mdown', **kwargs)
    set_markdown(ui_container, mdown=mdown, mdown_path=mdown_path, preprocess_fns=preprocess_fns, f_globals=f_globals, f_locals=f_locals)
    return ui_container



def framed_dialog(label=None, resizable=None, resizable_x=True, resizable_y=False, closeable=True, moveable=True, hide_on_close=False, close_callback=None, clamp_to_parent=True, parent=None, **kwargs):
    # TODO: always add header, and use UI_Proxy translate+map "label" to change header
    kw_inside = kwargs_splitter({'children'}, kwargs)
    ui_document = Globals.ui_document
    classes = ['framed']
    if 'classes' in kwargs: classes.append(kwargs['classes'])
    if moveable: classes.append('moveable')
    if closeable:
        if hide_on_close: classes.append('minimizeable')
        else: classes.append('closeable')
    kwargs['classes'] = ' '.join(classes)
    kwargs['clamp_to_parent'] = clamp_to_parent

    ui_dialog = UI_Element(tagName='dialog', **kwargs)
    if close_callback:
        if hide_on_close: ui_dialog.add_eventListener('on_visibilitychange', close_callback)
        else: ui_dialog.add_eventListener('on_close', close_callback)
    ui_header = UI_Element(tagName='h1', innerText=label or '', parent=ui_dialog)

    if resizable is not None: resizable_x = resizable_y = resizable
    if resizable_x or resizable_y:
        is_resizing = False
        mousedown_pos = None
        original_size = None
        def resizing(e):
            nonlocal ui_dialog
            if not e.mouse: return False
            dpi_mult = Globals.drawing.get_dpi_mult()
            l,t,w,h = ui_dialog.left_pixels, ui_dialog.top_pixels, ui_dialog.width_pixels, ui_dialog.height_pixels
            mt,mr,mb,ml = ui_dialog._get_style_trbl('margin', scale=dpi_mult)
            bw = ui_dialog._get_style_num('border-width', def_v=NumberUnit.zero, scale=dpi_mult)
            ro = ui_dialog._relative_offset
            gl = l + ro.x + w - mr - bw
            gb = t - ro.y - h + mb + bw
            rx = resizable_x and gl <= e.mouse.x < gl + bw
            ry = resizable_y and gb >= e.mouse.y > gl - bw
            if rx and ry: return 'both'
            if rx: return 'width'
            if ry: return 'height'
            return False
        def mousedown(e):
            nonlocal is_resizing, mousedown_pos, original_size, ui_dialog
            if e.target != ui_dialog: return
            ui_document.ignore_hover_change = True
            l,t,w,h = ui_dialog.left_pixels, ui_dialog.top_pixels, ui_dialog.width_pixels, ui_dialog.height_pixels
            is_resizing = resizing(e)
            mousedown_pos = e.mouse
            original_size = (w,h)
        def mouseup(e):
            nonlocal is_resizing
            ui_document.ignore_hover_change = False
            is_resizing = False
        def mousemove(e):
            nonlocal is_resizing, mousedown_pos, original_size, ui_dialog
            if not is_resizing:
                r = resizing(e)
                if   r == 'width':  ui_dialog._computed_styles['cursor'] = 'ew-resize'
                elif r == 'height': ui_dialog._computed_styles['cursor'] = 'ns-resize'
                elif r == 'both':   ui_dialog._computed_styles['cursor'] = 'grab'
                else:               ui_dialog._computed_styles['cursor'] = 'default'
            else:
                delta = e.mouse - mousedown_pos
                minw,maxw = ui_dialog._computed_min_width,  ui_dialog._computed_max_width
                minh,maxh = ui_dialog._computed_min_height, ui_dialog._computed_max_height
                if minw == 'auto': minw = 0
                if maxw == 'auto': maxw = float('inf')
                if minh == 'auto': minh = 0
                if maxh == 'auto': maxh = float('inf')
                if is_resizing in {'width', 'both'}:
                    ui_dialog.width = clamp(original_size[0] + delta.x, minw, maxw)
                if is_resizing in {'height', 'both'}:
                    ui_dialog.height = clamp(original_size[1] - delta.y, minh, maxh)
                ui_dialog.dirty_flow()
        ui_dialog.add_eventListener('on_mousedown', mousedown)
        ui_dialog.add_eventListener('on_mouseup', mouseup)
        ui_dialog.add_eventListener('on_mousemove', mousemove)
    ui_inside = UI_Element(tagName='div', classes='inside', style='overflow-y:scroll', parent=ui_dialog, **kw_inside)

    # ui_footer = UI_Element(tagName='div', classes='dialog-footer', parent=ui_dialog)
    # ui_footer_label = UI_Element(tagName='span', innerText='footer', parent=ui_footer)

    ui_proxy = UI_Proxy('framed_dialog', ui_dialog)
    ui_proxy.translate_map('label', 'innerText', ui_header) # ui_label)
    ui_proxy.map_children_to(ui_inside)
    ui_proxy.map_scroll_to(ui_inside)
    if parent: parent.append_child(ui_proxy)
    return ui_proxy


