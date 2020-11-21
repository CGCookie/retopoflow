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

from .boundvar import BoundVar, BoundFloat, BoundInt
from .decorators import blender_version_wrapper
from .drawing import Drawing, ScissorStack
from .fontmanager import FontManager
from .globals import Globals
from .maths import Point2D, Vec2D, clamp, mid, Color, Box2D, Size2D, NumberUnit
from .markdown import Markdown
from .profiler import profiler, time_it
from .useractions import is_keycode
from .utils import Dict, delay_exec


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


# all html tags: https://www.w3schools.com/tags/



def button(**kwargs):
    kwargs_translate('label', 'innerText', kwargs)
    return UI_Element(tagName='button', **kwargs)

def p(**kwargs):
    return UI_Element(tagName='p', **kwargs)

def a(**kwargs):
    elem = UI_Element(tagName='a', **kwargs)
    # def mouseclick(e):
    #     nonlocal elem
    #     if not elem.href: return
    #     if Markdown.is_url(elem.href):
    #         bpy.ops.wm.url_open(url=elem.href)
    # elem.add_eventListener('on_mouseclick', mouseclick)
    return elem

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

def label(**kwargs):
    return UI_Element(tagName='label', **kwargs)

def input_radio(**kwargs):
    kwargs_translate('label', 'innerText', kwargs)
    kw_label = kwargs_splitter({'innerText'}, kwargs)
    kw_all = kwargs_splitter({'title'}, kwargs)

    # https://www.w3schools.com/howto/howto_css_custom_checkbox.asp
    ui_input = UI_Element(tagName='input', type='radio', atomic=True, **kwargs, **kw_all)
    with ui_input.defer_dirty('creating content'):
        ui_radio = UI_Element(tagName='img', classes='radio',  parent=ui_input, **kw_all)
        ui_label = UI_Element(tagName='label', parent=ui_input, **kw_label, **kw_all)
        def mouseclick(e):
            ui_input.checked = True
        def on_input(e):
            # if ui_input is checked, uncheck all others with same name
            if not ui_input.checked: return
            if ui_input.name is None: return
            ui_elements = ui_input.get_root().getElementsByName(ui_input.name)
            for ui_element in ui_elements:
                if ui_element != ui_input: ui_element.checked = False
        ui_input.add_eventListener('on_mouseclick', mouseclick)
        ui_input.add_eventListener('on_input', on_input)

    ui_proxy = UI_Proxy('input_radio', ui_input)
    ui_proxy.translate('label', 'innerText')
    ui_proxy.map_children_to(ui_label)
    ui_proxy.map('innerText', ui_label)
    ui_proxy.map_to_all({'title'})
    return ui_proxy

def input_checkbox(**kwargs):
    kwargs_translate('label', 'innerText', kwargs)
    kw_label = kwargs_splitter({'innerText'}, kwargs)
    kw_all = kwargs_splitter({'title'}, kwargs)

    # https://www.w3schools.com/howto/howto_css_custom_checkbox.asp
    ui_input = UI_Element(tagName='input', type='checkbox', atomic=True, **kwargs, **kw_all)
    with ui_input.defer_dirty('creating content'):
        ui_checkmark = UI_Element(tagName='img', classes='checkbox',  parent=ui_input, **kw_all)
        ui_label = UI_Element(tagName='label', parent=ui_input, **kw_label, **kw_all)
        def mouseclick(e):
            ui_input.checked = not bool(ui_input.checked)
        ui_input.add_eventListener('on_mouseclick', mouseclick)

    ui_proxy = UI_Proxy('input_checkbox', ui_input)
    ui_proxy.translate_map('label', 'innerText', ui_label)
    ui_proxy.translate('value', 'checked')
    ui_proxy.map_children_to(ui_label)
    ui_proxy.map('innerText', ui_label)
    ui_proxy.map_to_all({'title'})
    return ui_proxy

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

        w, W = ui_handle.width_pixels, ui_input.width_pixels
        if w == 'auto' or W == 'auto': return   # UI system is not ready yet
        W -= ui_input._mbp_width

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


def setup_scrub(ui_element, value):
    if not type(value) in {BoundInt, BoundFloat}: return
    if not value.is_bounded and not value.step_size: return

    state = {}
    def reset_state():
        nonlocal state
        state = {
            'can scrub': True,
            'pressed': False,
            'scrubbing': False,
            'down': None,
            'initval': None,
            'cancelled': False,
        }
    reset_state()

    def cancel():
        nonlocal state
        if not state['scrubbing']: return
        value.value = state['initval']
        state['cancelled'] = True

    def mousedown(e):
        nonlocal state
        if not ui_element.document: return
        if ui_element.document.activeElement and ui_element.document.activeElement.is_descendant_of(ui_element):
            # do not scrub if descendant of ui_element has focus
            return
        if e.button[2] and state['scrubbing']:
            # right mouse button cancels
            value.value = state['initval']
            state['cancelled'] = True
            e.stop_propagation()
        elif e.button[0]:
            state['pressed'] = True
            state['down'] = e.mouse
            state['initval'] = value.value
    def mouseup(e):
        nonlocal state
        if e.button[0]: return
        if state['scrubbing']: e.stop_propagation()
        reset_state()
    def mousemove(e):
        nonlocal state
        if not state['pressed']: return
        if e.button[2]:
            cancel()
            e.stop_propagation()
        if state['cancelled']: return
        state['scrubbing'] |= (e.mouse - state['down']).length > Globals.drawing.scale(5)
        if not state['scrubbing']: return

        if ui_element._document:
            ui_element._document.blur()

        if value.is_bounded:
            m, M = value.min_value, value.max_value
            p = (e.mouse.x - state['down'].x) / ui_element.width_pixels
            v = clamp(state['initval'] + (M - m) * p, m, M)
            value.value = v
        else:
            delta = Globals.drawing.unscale(e.mouse.x - state['down'].x)
            value.value = state['initval'] + delta * value.step_size
        e.stop_propagation()
    def keypress(e):
        nonlocal state
        if not state['pressed']: return
        if state['cancelled']: return
        if type(e.key) is int and is_keycode(e.key, 'ESC'):
            cancel()
            e.stop_propagation()

    ui_element.add_eventListener('on_mousemove', mousemove, useCapture=True)
    ui_element.add_eventListener('on_mousedown', mousedown, useCapture=True)
    ui_element.add_eventListener('on_mouseup',   mouseup,   useCapture=True)
    ui_element.add_eventListener('on_keypress',  keypress,  useCapture=True)

def labeled_input_text(label, value='', scrub=False, **kwargs):
    '''
    this wraps input_text with a few divs to add a label on the left.
    use for text input, but can also restrict to numbers
    if scrub == True, value must be a BoundInt or BoundFloat with min_value and max_value set!
    '''

    kw_container = kwargs_splitter({'parent', 'id'}, kwargs)
    kw_all = kwargs_splitter({'title'}, kwargs)
    ui_container = UI_Element(tagName='div', classes='labeledinputtext-container', **kw_container, **kw_all)
    with ui_container.defer_dirty('creating content'):
        ui_left  = UI_Element(tagName='div',   classes='labeledinputtext-label-container', parent=ui_container, **kw_all)
        ui_right = UI_Element(tagName='div',   classes='labeledinputtext-input-container', parent=ui_container, **kw_all)
        ui_label = UI_Element(tagName='label', classes='labeledinputtext-label', innerText=label, parent=ui_left, **kw_all)
        ui_input = input_text(parent=ui_right, value=value, **kwargs, **kw_all)

    if scrub: setup_scrub(ui_container, value)

    ui_proxy = UI_Proxy('labeled_input_text', ui_container)
    ui_proxy.translate_map('label', 'innerText', ui_label)
    ui_proxy.map('value', ui_input)
    ui_proxy.map_to_all({'title'})
    return ui_proxy

def input_text(value='', scrub=False, **kwargs):
    '''
    use for text input, but can also restrict to numbers
    if scrub == True, value must be a BoundInt or BoundFloat with min_value and max_value set!
    '''

    kw_container = kwargs_splitter({'parent'}, kwargs)
    ui_container = UI_Element(tagName='span', classes='inputtext-container', **kw_container)
    ui_input  = UI_Element(tagName='input', classes='inputtext-input', type='text', can_focus=True, atomic=True, parent=ui_container, value=value, **kwargs)
    ui_cursor = UI_Element(tagName='span', classes='inputtext-cursor', parent=ui_input, innerText='|') # │

    data = {'orig': None, 'text': None, 'idx': 0, 'pos': None}
    def preclean():
        if data['text'] is None:
            if type(ui_input.value) is float:
                ui_input.innerText = '%0.4f' % ui_input.value
            else:
                ui_input.innerText = str(ui_input.value)
        else:
            ui_input.innerText = data['text']
        #print(ui_input, type(ui_input.innerText), ui_input.innerText, type(ui_input.value), ui_input.value)
    def postflow():
        if data['text'] is None: return
        data['pos'] = ui_input.get_text_pos(data['idx'])
        ui_cursor.reposition(
            left=data['pos'].x - ui_input._mbp_left - ui_cursor._absolute_size.width / 2,
            top=data['pos'].y + ui_input._mbp_top,
            clamp_position=False,
        )
        # ui_cursor.left = data['pos'].x - ui_input._mbp_left - ui_cursor._absolute_size.width / 2
        # ui_cursor.top  = data['pos'].y + ui_input._mbp_top
        # print('input_text.postflow', ui_cursor.left, ui_cursor.top, ui_cursor.left_pixels, ui_cursor.top_pixels)
    def cursor_postflow():
        if data['text'] is None: return
        ui_input._setup_ltwh()
        ui_cursor._setup_ltwh()
        # if ui_cursor._l < ui_input._l:
        #     ui_input._scroll_offset.x = min(0, ui_input._l - ui_cursor._l)
        vl = ui_input._l + ui_input._mbp_left
        vr = ui_input._r - ui_input._mbp_right
        vw = ui_input._w - ui_input._mbp_width
        if ui_cursor._r > vr:
            dx = ui_cursor._r - vr + 2
            ui_input.scrollLeft = ui_input.scrollLeft + dx
            ui_input._setup_ltwh()
        if ui_cursor._l < vl:
            dx = ui_cursor._l - vl - 2
            ui_input.scrollLeft = ui_input.scrollLeft + dx
            ui_input._setup_ltwh()
    def set_cursor(e):
        data['idx'] = ui_input.get_text_index(e.mouse)
        data['pos'] = None
        ui_input.dirty_flow()
    def focus(e):
        set_cursor(e)
    def mouseup(e):
        if not ui_input.is_focused: return
        if type(ui_input.value) is float:
            s = '%0.4f' % ui_input.value
        else:
            s = str(ui_input.value)
        data['orig'] = data['text'] = s
        set_cursor(e)
    def mousemove(e):
        if data['text'] is None: return
        if not e.button[0]: return
        set_cursor(e)
    def mousedown(e):
        if data['text'] is None: return
        if not e.button[0]: return
        set_cursor(e)
    def blur(e):
        ui_input.value = data['text']
        data['text'] = None
        #print('container:', ui_container._dynamic_full_size, ' input:', ui_input._dynamic_full_size, type(ui_input.value), ui_input.value)
    def keypress(e):
        if data['text'] == None: return
        if type(e.key) is int:
            if is_keycode(e.key, 'BACK_SPACE'):
                if data['idx'] == 0: return
                data['text'] = data['text'][0:data['idx']-1] + data['text'][data['idx']:]
                data['idx'] -= 1
            elif is_keycode(e.key, 'RET'):
                ui_input.blur()
            elif is_keycode(e.key, 'ESC'):
                data['text'] = data['orig']
                ui_input.blur()
            elif is_keycode(e.key, 'END'):
                data['idx'] = len(data['text'])
                ui_input.dirty_flow()
            elif is_keycode(e.key, 'HOME'):
                data['idx'] = 0
                ui_input.dirty_flow()
            elif is_keycode(e.key, 'LEFT_ARROW'):
                data['idx'] = max(data['idx'] - 1, 0)
                ui_input.dirty_flow()
            elif is_keycode(e.key, 'RIGHT_ARROW'):
                data['idx'] = min(data['idx'] + 1, len(data['text']))
                ui_input.dirty_flow()
            elif is_keycode(e.key, 'DEL'):
                if data['idx'] == len(data['text']): return
                data['text'] = data['text'][0:data['idx']] + data['text'][data['idx']+1:]
            else:
                return
        else:
            data['text'] = data['text'][0:data['idx']] + e.key + data['text'][data['idx']:]
            data['idx'] += 1
        preclean()

    ui_input.preclean = preclean
    ui_input.postflow = postflow
    ui_cursor.postflow = cursor_postflow
    ui_input.add_eventListener('on_focus', focus)
    ui_input.add_eventListener('on_blur', blur)
    ui_input.add_eventListener('on_keypress', keypress)
    ui_input.add_eventListener('on_mousemove', mousemove)
    ui_input.add_eventListener('on_mousedown', mousedown)
    ui_input.add_eventListener('on_mouseup', mouseup)

    if scrub: setup_scrub(ui_container, value)

    ui_proxy = UI_Proxy('input_text', ui_container)
    ui_proxy.map(['value', 'innerText'], ui_input)
    ui_proxy.map_to_all({'title'})

    preclean()

    return ui_proxy

def collection(label, **kwargs):
    kw_inside = kwargs_splitter({'children'}, kwargs)
    ui_container = UI_Element(tagName='div', classes='collection', **kwargs)
    with ui_container.defer_dirty('creating content'):
        ui_label = div(innerText=label, classes='header', parent=ui_container)
        ui_inside = UI_Element(tagName='div', classes='inside', parent=ui_container, **kw_inside)

    ui_proxy = UI_Proxy('collection', ui_container)
    ui_proxy.map('innerText', ui_label)
    ui_proxy.translate_map('label', 'innerText', ui_label)
    ui_proxy.map_children_to(ui_inside)
    return ui_proxy


def collapsible(label, **kwargs):
    kwargs_translate('collapsed', 'checked', kwargs)
    kwargs.setdefault('checked', True)
    kw_input  = kwargs_splitter({'checked'}, kwargs)
    kw_inside = kwargs_splitter({'children'}, kwargs)
    kw_all    = kwargs_splitter({'title'}, kwargs)

    kwargs['classes'] = f"collapsible {kwargs.get('classes', '')}"
    ui_container = UI_Element(tagName='div', **kwargs, **kw_all)
    with ui_container.defer_dirty('creating content'):
        ui_label = input_checkbox(label=label, id='%s_check'%(kwargs.get('id', get_unique_ui_id('collapsible-'))), classes='header', parent=ui_container, **kw_input, **kw_all)
        ui_inside = UI_Element(tagName='div', classes='inside', parent=ui_container, **kw_inside, **kw_all)
        def toggle():
            if ui_label.checked: ui_inside.add_class('collapsed')
            else:                ui_inside.del_class('collapsed')
        ui_label.add_eventListener('on_input', toggle)
        toggle()

    ui_proxy = UI_Proxy('collapsible', ui_container)
    ui_proxy.translate_map('collapsed', 'checked', ui_label)
    ui_proxy.map(['innerText', 'label'], ui_label)
    ui_proxy.map_children_to(ui_inside)
    ui_proxy.map_to_all({'title'})
    return ui_proxy




def get_mdown_path(fn, ext=None, subfolders=None):
    # if no subfolders are given, assuming image path is <root>/icons
    # or <root>/images where <root> is the 2 levels above this file
    if subfolders is None:
        subfolders = ['help']
    if ext:
        fn = '%s.%s' % (fn,ext)
    path_here = os.path.dirname(__file__)
    path_root = os.path.join(path_here, '..', '..')
    paths = [os.path.join(path_root, p, fn) for p in subfolders]
    paths += [os.path.join(path_here, 'images', fn)]
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
        while text:
            word,text = Markdown.split_word(text)
            word_fn(word)

    def process_para(container, para, **kwargs):
        with container.defer_dirty('creating new children'):
            opts = kwargopts(kwargs, classes='')

            # break each ui_item onto it's own line
            para = re.sub(r'\n', ' ', para)     # join sentences of paragraph
            para = re.sub(r'  *', ' ', para)    # 1+ spaces => 1 space

            # TODO: revisit this, and create an actual parser
            para = para.lstrip()
            while para:
                t,m = Markdown.match_inline(para)
                if t is None:
                    word,para = Markdown.split_word(para)
                    container.append_child(span(innerText=word))
                else:
                    if t == 'br':
                        container.append_child(br())
                    elif t == 'img':
                        style = m.group('style').strip() or None
                        UI_Element(tagName='img', classes='inline', style=style, src=m.group('filename'), title=m.group('caption'), parent=container)
                    elif t == 'code':
                        container.append_child(code(innerText=m.group('text')))
                    elif t == 'link':
                        text,link = m.group('text'),m.group('link')
                        title = 'Click to open URL in default web browser' if Markdown.is_url(link) else 'Click to open help'
                        def mouseclick():
                            if Markdown.is_url(link):
                                bpy.ops.wm.url_open(url=link)
                            else:
                                set_markdown(ui_mdown, mdown_path=link, preprocess_fns=preprocess_fns, f_globals=f_globals, f_locals=f_locals)
                        process_words(text, lambda word: a(innerText=word, href=link, title=title, on_mouseclick=mouseclick, parent=container))
                    elif t == 'bold':
                        process_words(m.group('text'), lambda word: b(innerText=word, parent=container))
                    elif t == 'italic':
                        process_words(m.group('text'), lambda word: i(innerText=word, parent=container))
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
                        container.append_child(input_checkbox(label=innertext, checked=BoundVar(value, f_globals=f_globals, f_locals=f_locals)))
                    else:
                        assert False, 'Unhandled inline markdown type "%s" ("%s") with "%s"' % (str(t), str(m), line)
                    para = para[m.end():]

    if ui_mdown._document: ui_mdown._document.defer_cleaning = True
    with ui_mdown.defer_dirty('creating new children'):
        ui_mdown.clear_children()
        ui_mdown.scrollToTop(force=True)
        if ui_mdown.parent: ui_mdown.parent.scrollToTop(force=True)

        paras = mdown.split('\n\n')         # split into paragraphs
        for para in paras:
            t,m = Markdown.match_line(para)

            if t is None:
                p_element = p()
                process_para(p_element, para)
                ui_mdown.append_child(p_element)

            elif t in ['h1','h2','h3']:
                hn = {'h1':h1, 'h2':h2, 'h3':h3}[t]
                #hn(innerText=m.group('text'), parent=ui_mdown)
                ui_hn = hn()
                process_para(ui_hn, m.group('text'))
                ui_mdown.append_child(ui_hn)

            elif t == 'ul':
                ui_ul = UI_Element(tagName='ul')
                with ui_ul.defer_dirty('creating ul children'):
                    para = para[2:]
                    for litext in re.split(r'\n- ', para):
                        ui_li = UI_Element(tagName='li', parent=ui_ul)
                        UI_Element(tagName='img', classes='dot', src='radio.png', parent=ui_li)
                        span_element = UI_Element(tagName='span', classes='text', parent=ui_li)
                        process_para(span_element, litext)
                ui_mdown.append_child(ui_ul)

            elif t == 'ol':
                ui_ol = UI_Element(tagName='ol', parent=ui_mdown)
                with ui_ol.defer_dirty('creating ol children'):
                    para = para[2:]
                    for ili,litext in enumerate(re.split(r'\n\d+\. ', para)):
                        ui_li = UI_Element(tagName='li', parent=ui_ol)
                        UI_Element(tagName='span', classes='number', innerText='%d.'%(ili+1), parent=ui_li)
                        span_element = UI_Element(tagName='span', classes='text', parent=ui_li)
                        process_para(span_element, litext)
                ui_mdown.append_child(ui_ol)

            elif t == 'img':
                style = m.group('style').strip() or None
                UI_Element(tagName='img', style=style, src=m.group('filename'), title=m.group('caption'), parent=ui_mdown)

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
                table_element = table()
                with table_element.defer_dirty('creating table children'):
                    if add_header:
                        tr_element = tr(parent=table_element)
                        for c in range(cols):
                            th(innerText=header[c], parent=tr_element)
                    for r in range(rows):
                        tr_element = tr(parent=table_element)
                        for c in range(cols):
                            td_element = td(parent=tr_element)
                            process_para(td_element, data[r][c])
                ui_mdown.append_child(table_element)

            else:
                assert False, 'Unhandled markdown line type "%s" ("%s") with "%s"' % (str(t), str(m), para)
    if ui_mdown._document: ui_mdown._document.defer_cleaning = False


def markdown(mdown=None, mdown_path=None, preprocess_fns=None, f_globals=None, f_locals=None, **kwargs):
    if f_globals is None or f_locals is None:
        frame = inspect.currentframe().f_back               # get frame   of calling function
        if f_globals is None: f_globals = frame.f_globals   # get globals of calling function
        if f_locals  is None: f_locals  = frame.f_locals    # get locals  of calling function

    ui_container = UI_Element(tagName='div', classes='mdown', **kwargs)
    set_markdown(ui_container, mdown=mdown, mdown_path=mdown_path, preprocess_fns=preprocess_fns, f_globals=f_globals, f_locals=f_locals)
    return ui_container



def framed_dialog(label=None, resizable=None, resizable_x=True, resizable_y=False, closeable=True, moveable=True, hide_on_close=False, close_callback=None, clamp_to_parent=True, **kwargs):
    # TODO: always add header, and use UI_Proxy translate+map "label" to change header
    kw_inside = kwargs_splitter({'children'}, kwargs)
    ui_document = Globals.ui_document
    kwargs['classes'] = 'framed %s %s' % (kwargs.get('classes', ''), 'moveable' if moveable else '')
    kwargs['clamp_to_parent'] = clamp_to_parent
    ui_dialog = UI_Element(tagName='dialog', **kwargs)

    ui_header = UI_Element(tagName='div', classes='dialog-header', parent=ui_dialog)
    if closeable:
        def close():
            if close_callback: close_callback()
            if hide_on_close:
                ui_dialog.is_visible = False
                return
            if ui_dialog._parent is None: return
            if ui_dialog._parent == ui_dialog: return
            ui_dialog._parent.delete_child(ui_dialog)
        title = 'Close dialog' # 'Hide' if hide_on_close??
        ui_close = UI_Element(tagName='button', classes='dialog-close', title=title, on_mouseclick=close, parent=ui_header)

    ui_label = UI_Element(tagName='span', classes='dialog-title', innerText=label or '', parent=ui_header)
    if moveable:
        is_dragging = False
        mousedown_pos = None
        original_pos = None
        def mousedown(e):
            nonlocal is_dragging, mousedown_pos, original_pos, ui_dialog
            if e.target != ui_header and e.target != ui_label: return
            ui_document.ignore_hover_change = True
            is_dragging = True
            mousedown_pos = e.mouse

            l = ui_dialog.left_pixels
            if l is None or l == 'auto': l = 0
            t = ui_dialog.top_pixels
            if t is None or t == 'auto': t = 0
            original_pos = Point2D((float(l), float(t)))
        def mouseup(e):
            nonlocal is_dragging
            is_dragging = False
            ui_document.ignore_hover_change = False
        def mousemove(e):
            nonlocal is_dragging, mousedown_pos, original_pos, ui_dialog
            if not is_dragging: return
            delta = e.mouse - mousedown_pos
            new_pos = original_pos + delta
            ui_dialog.reposition(left=new_pos.x, top=new_pos.y)
        ui_header.add_eventListener('on_mousedown', mousedown)
        ui_header.add_eventListener('on_mouseup', mouseup)
        ui_header.add_eventListener('on_mousemove', mousemove)

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
    ui_proxy.translate_map('label', 'innerText', ui_label)
    ui_proxy.map_children_to(ui_inside)
    ui_proxy.map_scroll_to(ui_inside)
    return ui_proxy




# class UI_Flexbox(UI_Core):
#     '''
#     This container will resize the width/height of all children to fill the available space.
#     This element is useful for lists of children elements, growing along one dimension and filling along other dimension.
#     Children of row flexboxes will take up entire height; children of column flexboxes will take up entire width.

#     TODO: model off flexbox more closely?  https://css-tricks.com/snippets/css/a-guide-to-flexbox/
#     '''

#     style_default = '''
#         display: flexbox;
#         flex-direction: row;
#         flex-wrap: nowrap;
#         overflow: scroll;
#     '''

#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)

#     def compute_content_size(self):
#         for child in self._children:
#             pass

#     def layout_children(self):
#         for child in self._children: child.recalculate()

#         # assuming all children are drawn on top on one another
#         w,h = self._min_width,self._min_height
#         W,H = self._max_width,self._max_height
#         for child in self.get_visible_children():
#             w = max(w, child._min_width)
#             h = max(h, child._min_height)
#             W = min(W, child._max_width)
#             H = min(H, child._max_height)
#         self._min_width,self.min_height = w,h
#         self._max_width,self.max_height = W,H

#         # do not clean self if any children are still dirty (ex: they are deferring recalculation)
#         self._is_dirty = any(child._is_dirty for child in self._children)

#     def position_children(self, left, top, width, height):
#         for child in self.get_visible_children():
#             child.position(left, top, width, height)

#     def draw_children(self):
#         for child in self.get_visible_children():
#             child.draw()



# class UI_Label(UI_Core):
#     def __init__(self, label=None, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self._label = label or ''


# class UI_Button(UI_Core):
#     def __init__(self, label=None, click=None, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self._label = label or ''
#         self._click = click




# class UI_Dialog(UI_Core):
#     '''
#     a dialog window, can be shown modal
#     '''

#     def __init__(self, *args, **kwargs):
#         super().__init__()



# class UI_Body(UI_Core):
#     def __init__(self, actions, *args, **kwargs):
#         super().__init__(*args, **kwargs)

#         self._actions = actions
#         self._active = None         # element that is currently active
#         self._active_last = None
#         self._focus = None          # either active element or element under the cursor
#         self._focus_last = None

#     def modal(self, actions):
#         if self.actions.mousemove:
#             # update the tooltip's position
#             # close windows that have focus
#             pass

#         if event.type == 'MOUSEMOVE':
#             mouse = Point2D((float(event.mouse_region_x), float(event.mouse_region_y)))
#             self.tooltip_window.fn_sticky.set(mouse + self.tooltip_offset)
#             self.tooltip_window.update_pos()
#             if self.focus and self.focus_close_on_leave:
#                 d = self.focus.distance(mouse)
#                 if d > self.focus_close_distance:
#                     self.delete_window(self.focus)

#         ret = {}

#         if self.active and self.active.state != 'main':
#             ret = self.active.modal(context, event)
#             if not ret: self.active = None
#         elif self.focus:
#             ret = self.focus.modal(context, event)
#         else:
#             self.active = None
#             for win in reversed(self.windows):
#                 ret = win.modal(context, event)
#                 if ret:
#                     self.active = win
#                     break

#         if self.active != self.active_last:
#             if self.active_last and self.active_last.fn_event_handler:
#                 self.active_last.fn_event_handler(context, UI_Event('HOVER', 'LEAVE'))
#             if self.active and self.active.fn_event_handler:
#                 self.active.fn_event_handler(context, UI_Event('HOVER', 'ENTER'))
#         self.active_last = self.active

#         if self.active:
#             if self.active.fn_event_handler:
#                 self.active.fn_event_handler(context, event)
#             if self.active:
#                 tooltip = self.active.get_tooltip()
#                 self.set_tooltip_label(tooltip)
#         else:
#             self.set_tooltip_label(None)

#         return ret



