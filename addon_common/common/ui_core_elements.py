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
from itertools import dropwhile

import bpy
import blf
import gpu

from mathutils import Vector, Matrix

from .boundvar import BoundVar, BoundInt, BoundFloat
from .blender import tag_redraw_all
from .debug import debugger, dprint, tprint
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .globals import Globals
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .profiler import profiler, time_it
from .ui_core_utilities import helper_wraptext, convert_token_to_cursor
from .utils import iter_head, any_args, join, delay_exec, Dict



def setup_scrub(ui_element, value):
    '''
    must be a BoundInt or BoundFloat with min_value and max_value set
    '''
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
        if e.key == 'ESC':
            cancel()
            e.stop_propagation()

    ui_element.add_eventListener('on_mousemove', mousemove, useCapture=True)
    ui_element.add_eventListener('on_mousedown', mousedown, useCapture=True)
    ui_element.add_eventListener('on_mouseup',   mouseup,   useCapture=True)
    ui_element.add_eventListener('on_keypress',  keypress,  useCapture=True)


# all html tags: https://www.w3schools.com/tags/

re_html_tag = re.compile(r"(?P<tag><(?P<close>/)?(?P<name>[a-zA-Z0-9\-_]+)(?P<attributes>( +(?P<key>[a-zA-Z0-9\-_]+)(?:=(?P<value>\"(?:[^\"]|\\\")*\"|[a-zA-Z0-9\-_]+|\'(?:[^']|\\\')*?\'))?)*) *(?P<selfclose>/)?>)")
re_attributes = re.compile(r" *(?P<key>[a-zA-Z0-9\-_]+)(?:=(?P<value>\"(?:[^\"]|\\\")*?\"|[a-zA-Z0-9\-]+|\'(?:[^']|\\\')*?\'))?")
re_html_comment = re.compile(r"<!--(.|\n|\r)*?-->")

re_self = re.compile(r"self\.")
re_bound = re.compile(r"^(?P<type>Bound(String|StringToBool|Bool|Int|Float))\((?P<args>.*)\)$")
re_int = re.compile(r"^[-+]?[0-9]+$")
re_float = re.compile(r"^[-+]?[0-9]*\.?[0-9]+$")
re_fstring = re.compile(r"{(?P<eval>([^}]|\\})*)}")

tags_selfclose = {
    'area', 'br', 'col',
    'embed', 'hr', 'iframe',
    'img', 'input', 'link',
    'meta', 'param', 'source',
    'track', 'wbr'
}
tags_known = {
    'article',
    'button',
    'span', 'div', 'p',
    'a',
    'b', 'i',
    'h1', 'h2', 'h3',
    'ul', 'ol', 'li',
    'pre', 'code',
    'br',
    'img',
    'progress',
    'table', 'tr', 'th', 'td',
    'dialog',
    'label', 'input',
    'details', 'summary',
    'script',
    'text',
}
events_known = {
    'focus':        'on_focus',         'onfocus':          'on_focus',         'on_focus':         'on_focus',
    'blur':         'on_blur',          'onblur':           'on_blur',          'on_blur':          'on_blur',
    'focusin':      'on_focusin',       'onfocusin':        'on_focusin',       'on_focusin':       'on_focusin',
    'focusout':     'on_focusout',      'onfocusout':       'on_focusout',      'on_focusout':      'on_focusout',
    'keydown':      'on_keydown',       'onkeydown':        'on_keydown',       'on_keydown':       'on_keydown',
    'keyup':        'on_keyup',         'onkeyup':          'on_keyup',         'on_keyup':         'on_keyup',
    'keypress':     'on_keypress',      'onkeypress':       'on_keypress',      'on_keypress':      'on_keypress',
    'mouseenter':   'on_mouseenter',    'onmouseenter':     'on_mouseenter',    'on_mouseenter':    'on_mouseenter',
    'mousemove':    'on_mousemove',     'onmousemove':      'on_mousemove',     'on_mousemove':     'on_mousemove',
    'mousedown':    'on_mousedown',     'onmousedown':      'on_mousedown',     'on_mousedown':     'on_mousedown',
    'mouseup':      'on_mouseup',       'onmouseup':        'on_mouseup',       'on_mouseup':       'on_mouseup',
    'mouseclick':   'on_mouseclick',    'onmouseclick':     'on_mouseclick',    'on_mouseclick':    'on_mouseclick',
    'mousedblclick':'on_mousedblclick', 'onmousedblclick':  'on_mousedblclick', 'on_mousedblclick': 'on_mousedblclick',
    'mouseleave':   'on_mouseleave',    'onmouseleave':     'on_mouseleave',    'on_mouseleave':    'on_mouseleave',
    'scroll':       'on_scroll',        'onscroll':         'on_scroll',        'on_scroll':        'on_scroll',
    'input':        'on_input',         'oninput':          'on_input',         'on_input':         'on_input',
    'change':       'on_change',        'onchange':         'on_change',        'on_change':        'on_change',
    'toggle':       'on_toggle',        'ontoggle':         'on_toggle',        'on_toggle':        'on_toggle',
    'visibilitychange': 'on_visibilitychange', 'onvisibilitychange': 'on_visibilitychange', 'on_visibilitychange': 'on_visibilitychange',
    'close': 'on_close', 'onclose': 'on_close', 'on_close': 'on_close',
    'load': 'on_load', 'onload': 'on_load', 'on_load': 'on_load',
}


class UI_Core_Elements():
    @classmethod
    def fromHTMLFile(cls, path_html, *, frame_depth=1, frames_deep=1, f_globals=None, f_locals=None, **kwargs):
        if not path_html: return []
        assert os.path.exists(path_html), f'Could not find HTML {path_html}'
        html = open(path_html, 'rt').read()
        return cls.fromHTML(
            html,
            frame_depth=frame_depth+1,
            frames_deep=frames_deep,
            f_globals=f_globals,
            f_locals=f_locals,
            **kwargs
        )

    @classmethod
    def fromHTML(cls, html, *, frame_depth=1, frames_deep=1, f_globals=None, f_locals=None, **kwargs):
        # use passed global and local contexts or grab contexts from calling function
        # these contexts are needed for bound variables
        if f_globals and f_locals:
            f_globals = f_globals
            f_locals = dict(f_locals)
        else:
            ff_globals, ff_locals = {}, {}
            frame = inspect.currentframe()
            for i in range(frame_depth + frames_deep):
                if i >= frame_depth:
                    ff_globals = frame.f_globals | ff_globals
                    ff_locals  = frame.f_locals  | ff_locals
                frame = frame.f_back
            f_globals = f_globals or ff_globals
            f_locals  = dict(f_locals or ff_locals)
        f_locals |= kwargs

        def next_close(html, tagName):
            m_tag = re_html_tag.search(html)
            if not m_tag: return None
            if m_tag.group('name').lower() != tagName: return None
            if not m_tag.group('close'): return None
            innerText = html[:m_tag.start()].lstrip()
            post_html = html[m_tag.end():].lstrip()
            return Dict({
                'innerText': innerText,
                'post_html': post_html
            })

        def get_next_tag(html, ui_cur, tab, hierarchy):
            m_tag = re_html_tag.search(html)
            if not m_tag: return None

            cur_tagName = ui_cur._tagName if ui_cur else None

            pre_html = html[:m_tag.start()].lstrip()
            post_html = html[m_tag.end():].lstrip()

            tname = m_tag.group('name').lower()
            attributes = m_tag.group('attributes')
            is_close = m_tag.group('close') is not None
            is_selfclose = m_tag.group('selfclose') or tname in tags_selfclose

            event_data = {
                'this': None,
            }
            def process(ui_this):
                nonlocal event_data
                event_data['this'] = ui_this

            attribs = {}
            if attributes:
                for m_attrib in re_attributes.finditer(attributes):
                    k, v = m_attrib.group('key'), m_attrib.group('value')

                    # translate HTML attribs to CC UI attribs
                    if k.lower() in {'class'}: k = 'classes'
                    if k.lower() in {'for'}:   k = 'forId'

                    ##############################################################
                    # translate HTML attrib values to CC UI attrib values

                    # if no value given, default is True
                    if v is None: v = 'True'

                    # remove wrapping quotes and un-escape any escaped quote
                    if v.startswith('"'):
                        # wrapped in double quotes
                        v = v[1:-1]
                        v = re.sub(r"\\\"", '"', v)
                    elif v.startswith("'"):
                        # wrapped in single quotes
                        v = v[1:-1]
                        v = re.sub(r"\\\'", "'", v)

                    if k.lower() in {'title', 'class', 'classes'}:
                        # apply fstring
                        while True:
                            m = re_fstring.search(v)
                            if not m: break
                            pre, post = v[:m.start()], v[m.end():]
                            nv = eval(m.group('eval'), f_globals, f_locals)
                            v = f'{pre}{nv}{post}'

                    # convert value to Python value
                    m_self  = re_self.match(v)
                    m_bound = re_bound.match(v)
                    m_int   = re_int.match(v)
                    m_float = re_float.match(v)

                    if k.lower() in events_known:
                        # attribute is an event (value is callback)
                        k = events_known[k.lower()]
                        def precall(f_locals):
                            nonlocal event_data
                            for dk,dv in event_data.items():
                                f_locals[dk] = dv
                        v = delay_exec(v, f_globals=f_globals, f_locals=f_locals, ordered_parameters=['event'], precall=precall)
                    elif v.lower() in {'true'}:  v = True
                    elif v.lower() in {'false'}: v = False
                    elif m_int:                  v = int(v)
                    elif m_float:                v = float(v)
                    elif m_self:                 v = eval(v, f_globals, f_locals)
                    elif m_bound:
                        try:
                            v = eval(v, f_globals, f_locals)
                        except Exception as e:
                            print(f'')
                            print(f'Caught Exception {e} while trying to eval {v}')
                            print(f'{f_globals=}')
                            print(f'{f_locals=}')
                            raise e

                    attribs[k] = v

            assert not (is_close and attribs), 'Cannot have closing tag with attributes'
            assert not (is_close and is_selfclose), f'Cannot be closing and self-closing: {m_tag.group("tag")}'
            assert not (is_close and tname != cur_tagName), f'Found ending tag {m_tag.group("tag")} but expecting </{cur_tagName}>\n{hierarchy}'
            assert tname in tags_known, f'Unhandled tag type: {m_tag.group("tag")}'

            return Dict({
                'pre_html':     pre_html,
                'post_html':    post_html,
                'tname':        tname,
                'attribs':      attribs,
                'is_close':     is_close,
                'is_selfclose': is_selfclose,
                'process':      process,
            })

        def create(*args, **kwargs):
            if kwargs.get('tagName', '') == 'dialog':
                kwargs.setdefault('clamp_to_parent', True)
            ui = cls(*args, **kwargs)
            def cb():
                ui.dirty(cause='BoundVar changed')
            for k,v in kwargs.items():
                if isinstance(v, BoundVar):
                    v.on_change(cb)
            return ui

        def process(html, ui_cur, hierarchy=[]):
            depth = len(hierarchy)
            tab = '  '*depth
            ret = []
            while html.strip():
                tag = get_next_tag(html, ui_cur, tab, hierarchy)
                if not tag:
                    return (ret + [create(tagName='text', pseudoelement='text', innerText=html)], '')

                if tag.pre_html.strip():
                    # <tag>found some text here  </tag>/<anothertag>/<selfclose/>...
                    #      ^                     ^ tag.tname
                    #      \_ started here: tag.pre_html
                    ui_text = create(tagName='text', pseudoelement='text', innerText=tag.pre_html)
                    ret += [ui_text]

                if tag.is_close:
                    # <tag>...</tag>
                    #      ^  ^ closing current tag
                    #      \_ started here, but this is already processed
                    return (ret, tag.post_html)
                elif tag.is_selfclose:
                    # <tag>...<selfclose/>...
                    #      ^  ^           ^ tag.post_html
                    #      |  \_ self-closing tag
                    #      \_ started here, but this is already processed
                    ui_new = create(tagName=tag.tname, **tag.attribs)
                    tag.process(ui_new)
                    ret.append(ui_new)
                    html = tag.post_html
                else:
                    # <tag>...<anothertag>...
                    #      ^  ^           ^ tag.post_html
                    #      |  \_ starting another tag
                    #      \_ started here, but this is already processed
                    # check if anothertag is immediately closed, especially looking for <script>
                    nclose = next_close(tag.post_html, tag.tname)
                    if nclose:
                        # case: <anothertag>some innerText</anothertag>...
                        if tag.tname.lower() == 'script':
                            # case anothertag=script: <script>some python code</script>
                            # TODO: check for src attribute!
                            written = []
                            f_locals['write'] = written.append
                            # print(f'executing script: {nclose.innerText}')
                            exec(nclose.innerText, f_globals, f_locals)
                            # prepend anything written out to HTML so it can be processed
                            html = '\n'.join(written) + nclose.post_html
                        else:
                            # just stick pre_html into innerText
                            innerText = nclose.innerText if nclose.innerText.strip() else None
                            ui_new = create(tagName=tag.tname, innerText=innerText, **tag.attribs)
                            tag.process(ui_new)
                            ret.append(ui_new)
                            html = nclose.post_html
                    else:
                        ui_new = create(tagName=tag.tname, **tag.attribs)
                        tag.process(ui_new)
                        children, html = process(tag.post_html, ui_new, hierarchy+[tag.tname])
                        for child in children: ui_new.append_child(child)
                        ret.append(ui_new)
            return (ret, html.strip())

        # remove HTML comments
        html = re_html_comment.sub('', html)
        # strip leading and trailing whitespace characters
        html = re.sub(r'^[ \n\r\t]+', '', html)
        html = re.sub(r'[ \n\r\t]+$', '', html)

        lui,rest = process(html, None)
        assert not rest, f'Could not process all of HTML\nRemaining: {rest}\nHTML: {html}'
        return lui

    def _init_input_box(self, input_type):
        allowed = None  # allow any character
        match input_type:
            case 'text':
                # could set
                #     allowed = '''abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 `~!@#$%^&*()[{]}\'"\\|-_;:,<.>'''
                # but that would exclude any non-US-keyboard inputs
                pass
            case 'number':
                if type(self._value) is BoundInt:
                    if self._value.min_value is not None and self._value.min_value >= 0:
                        # only non-negative ints
                        allowed = '''0123456789'''
                    else:
                        # can be negative
                        allowed = '''-0123456789'''
                else:
                    # can be float
                    allowed = '''0123456789.-'''
            case _:
                assert False, f'UI_Element.process_input_box: unhandled type {input_type}'

        data = {'orig':None, 'text':None, 'idx':0, 'pos':None}

        def preclean():
            if data['text'] is None:
                if type(self.value) is float:
                    self.innerText = f'{self.value:0.4g}'
                else:
                    self.innerText = f'{self.value}'
            else:
                self.innerText = data['text']
            # self.dirty_content(cause='preclean called')

        def postflow():
            if data['text'] is None: return
            data['pos'] = self.get_text_pos(data['idx'])
            if self._ui_marker._absolute_size:
                if data['pos']:
                    self._ui_marker.reposition(
                        left=data['pos'].x - self._ui_marker._absolute_size.width / 2,
                        top=data['pos'].y,
                        clamp_position=(self.scrollLeft <= 0),
                    )
                    cursor_postflow()
                else:
                    # sometimes, content can change too quickly, so data isn't filled
                    # in this case, just dirty ourselves so that we will re-render
                    self.dirty_content()
        def cursor_postflow():
            if data['text'] is None: return
            self._setup_ltwh()
            self._ui_marker._setup_ltwh()
            vl = self._l + self._mbp_left
            vr = self._r - self._mbp_right
            vw = self._w - self._mbp_width
            if self._ui_marker._r > vr:
                dx = self._ui_marker._r - vr + 2
                self.scrollLeft = self.scrollLeft + dx
                self._setup_ltwh()
            if self._ui_marker._l < vl:
                dx = self._ui_marker._l - vl - 2
                self.scrollLeft = self.scrollLeft + dx
                self._setup_ltwh()

        def set_cursor(e):
            data['idx'] = self.get_text_index(e.mouse)
            data['pos'] = self.get_text_pos(data['idx'])
            self.dirty_flow()

        def focus(e):
            s = f'{self.value:0.4g}' if type(self.value) is float else str(self.value)
            data['orig'] = data['text'] = s
            self._ui_marker.is_visible = True
            set_cursor(e)
        def blur(e):
            changed = data['orig'] != data['text']
            self.value = data['text']
            data['text'] = None
            self._ui_marker.is_visible = False
            if changed: self.dispatch_event('on_change')

        def mouseup(e):
            if not e.button[0]: return
            # if not self.is_focused: return
            set_cursor(e)
        def mousemove(e):
            if data['text'] is None: return
            if not e.button[0]: return
            set_cursor(e)
        def mousedown(e):
            if data['text'] is None: return
            if not e.button[0]: return
            set_cursor(e)

        def keypress(e):
            if data['text'] == None: return
            if e.key == 'Backspace':
                if data['idx'] == 0: return
                data['text'] = data['text'][0:data['idx']-1] + data['text'][data['idx']:]
                data['idx'] -= 1
            elif e.key == 'Enter':
                self.blur()
            elif e.key == 'Escape':
                data['text'] = data['orig']
                self.blur()
            elif e.key == 'End':
                data['idx'] = len(data['text'])
                self.dirty()
                self.dirty_flow()
            elif e.key == 'Home':
                data['idx'] = 0
                self.dirty()
                self.dirty_flow()
            elif e.key == 'ArrowLeft':
                data['idx'] = max(data['idx'] - 1, 0)
                self.dirty()
                self.dirty_flow()
            elif e.key == 'ArrowRight':
                data['idx'] = min(data['idx'] + 1, len(data['text']))
                self.dirty()
                self.dirty_flow()
            elif e.key == 'Delete':
                if data['idx'] == len(data['text']): return
                data['text'] = data['text'][0:data['idx']] + data['text'][data['idx']+1:]
            elif len(e.key) > 1:
                return
            elif allowed is None or e.key in allowed:
                newtext = data['text'][:data['idx']] + e.key + data['text'][data['idx']:]
                if self.maxlength is not None and len(newtext) > self.maxlength: return
                data['text'] = newtext
                data['idx'] += 1
            preclean()
        def paste(e):
            if data['text'] == None: return
            clipboardData = str(e.clipboardData)
            if allowed: clipboardData = ''.join(c for c in clipboardData if c in allowed)
            if self.maxlength is not None:
                # only insert enough chars to prevent going above maxlength
                origlen, cliplen = len(data['text']), len(clipboardData)
                if origlen + cliplen > self.maxlength:
                    clipboardData = clipboardData[:(self.maxlength - origlen)]
            data['text'] = data['text'][:data['idx']] + clipboardData + data['text'][data['idx']:]
            data['idx'] += len(clipboardData)
            preclean()

        self.preclean = preclean
        self.postflow = postflow

        self.add_eventListener('on_focus',     focus)
        self.add_eventListener('on_blur',      blur)
        self.add_eventListener('on_keypress',  keypress)
        self.add_eventListener('on_paste',     paste)
        self.add_eventListener('on_mousedown', mousedown)
        self.add_eventListener('on_mousemove', mousemove)
        self.add_eventListener('on_mouseup',   mouseup)

        preclean()

    def _process_input_box(self):
        if self._ui_marker is None:
            # just got focus, so create a cursor element
            self._ui_marker = self._generate_new_ui_elem(
                tagName=self._tagName,
                type=self._type,
                classes=self._classes_str,
                pseudoelement='marker',
            )
            self._ui_marker.is_visible = False
        else:
            self._new_content = True
            self._children_gen += [self._ui_marker]
        return [*self._children, self._ui_marker]

        is_focused, was_focused = self.is_focused, getattr(self, '_was_focused', None)
        self._was_focused = is_focused

        if not is_focused:
            # not focused, so no cursor!
            if was_focused:
                self._ui_marker = None
                self._selectionStart = None
                self._selectionEnd = None
            return self._children

        if not was_focused:
            # was not focused, but has focus now
            # store current text in case ESC is pressed to cancel (revert to original)
            self._innerText_original = self._innerText

        if not self._ui_marker:
            # just got focus, so create a cursor element
            self._ui_marker = self._generate_new_ui_elem(
                tagName=self._tagName,
                type=self._type,
                classes=self._classes_str,
                pseudoelement='marker',
            )
        else:
            self._new_content = True
            self._children_gen += [self._ui_marker]

        return [*self._children, self._ui_marker]

    def _process_input_range(self):
        assert self._value_bound, f'{self} must have bound value ({self.value})'
        if not getattr(self, '_processed_input_range', False):
            self._processed_input_range = True
            ui_left   = self.append_new_child(tagName='span', classes='inputrange-left')
            ui_handle = self.append_new_child(tagName='span', classes='inputrange-handle')
            ui_right  = self.append_new_child(tagName='span', classes='inputrange-right')

            state = Dict()
            state.reset = delay_exec('''state.set(grabbed=False, down=None, initval=None, cancelled=False)''')
            state.cancel = delay_exec('''state.value = state.initval; state.cancelled = True''')
            state.reset()

            def postflow():
                if not self.is_visible: return
                # since ui_left, ui_right, and ui_handle are all absolutely positioned UI elements,
                # we can safely move them around without dirtying (the UI system does not need to
                # clean anything or reflow the elements)

                w, W = ui_handle.width_scissor, self.width_scissor
                if w == 'auto' or W == 'auto': return   # UI system is not ready yet
                W -= self._mbp_width

                mw = W - w                      # max dist the handle can move
                p = self._value.bounded_ratio   # convert value to [0,1] based on min,max
                hl = p * mw                     # find where handle (left side) should be
                m = hl + (w / 2)                # compute center of handle

                ui_left.width_override = math.floor(m)
                ui_handle._alignment_offset = Vec2D((math.floor(hl), 0))
                ui_right.width_override = math.floor(W-m)
                ui_right._alignment_offset = Vec2D((math.ceil(m), 0))

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
                    initval=self._value.value,
                    cancelled=False,
                )
                e.stop_propagation()
            def handle_mouseup(e):
                if e.button[0]: return
                e.stop_propagation()
                state.reset()
            def handle_mousemove(e):
                if not state.grabbed or state.cancelled: return
                m, M = self._value.min_value, self._value.max_value
                p = (e.mouse.x - state['down'].x) / self.width_pixels
                self._value.value = state.initval + p * (M - m)
                e.stop_propagation()
                postflow()
            def handle_keypress(e):
                if not state.grabbed or state.cancelled: return
                if e.key == 'ESC':
                    state.cancel()
                    e.stop_propagation()
            self.add_eventListener('on_mousemove', handle_mousemove, useCapture=True)
            self.add_eventListener('on_mousedown', handle_mousedown, useCapture=True)
            self.add_eventListener('on_mouseup',   handle_mouseup,   useCapture=True)
            self.add_eventListener('on_keypress',  handle_keypress,  useCapture=True)

            ui_handle.postflow = postflow
            self._value.on_change(postflow)
        return self._children

    def _process_label(self):
        if not getattr(self, '_processed_label', False):
            self._processed_label = True
            def mouseclick(e):
                if not e.target.is_descendant_of(self): return
                ui_for = self.get_for_element()
                if not ui_for: return
                if ui_for == e.target: return
                ui_for.dispatch_event('on_mouseclick')
            self.add_eventListener('on_mouseclick', mouseclick, useCapture=True)
        return self._children


    def _process_input_checkbox(self):
        if self._ui_marker is None:
            self._ui_marker = self._generate_new_ui_elem(
                tagName=self._tagName,
                type=self._type,
                checked=self.checked,
                classes=self._classes_str,
                pseudoelement='marker',
            )
            self.add_eventListener('on_mouseclick', delay_exec('''self.checked = not bool(self.checked)'''))
        else:
            self._children_gen += [self._ui_marker]
            self._new_content = True
        return [self._ui_marker, *self._children]

    def _init_input_radio(self):
        def on_input(e):
            if not self.checked: return
            ui_elements = self.get_root().getElementsByName(self.name)
            for ui_element in ui_elements:
                if ui_element != self:
                    ui_element.checked = False
        def on_click(e):
            self.checked = True
        self.add_eventListener('on_mouseclick', on_click)
        self.add_eventListener('on_input', on_input)
    def _process_input_radio(self):
        if self._ui_marker is None:
            self._ui_marker = self._generate_new_ui_elem(
                tagName=self._tagName,
                type=self._type,
                checked=self.checked,
                classes=self._classes_str,
                pseudoelement='marker',
            )
        else:
            self._children_gen += [self._ui_marker]
            self._new_content = True
        return [self._ui_marker, *self._children]

    def _process_details(self):
        is_open, was_open = self.open, getattr(self, '_was_open', None)
        self._was_open = is_open

        if not getattr(self, '_processed_details', False):
            self._processed_details = True
            def mouseclick(e):
                doit = False
                doit |= e.target == self                                              # clicked on <details>
                doit |= e.target.tagName == 'summary' and e.target._parent == self    # clicked on <summary> of <details>
                if not doit: return
                self.open = not self.open
            self.add_eventListener('on_mouseclick', mouseclick)

        if self._get_child_tagName(0) != 'summary':
            # <details> does not have a <summary>, so create a default one
            if self._ui_marker is None:
                self._ui_marker = self.prepend_new_child(tagName='summary', innerText='Details')
            summary = self._ui_marker
            contents = self._children if is_open else []
        else:
            summary = self._children[0]
            contents = self._children[1:] if is_open else []

        # set _new_content to show contents if open is toggled
        self._new_content |= was_open != is_open
        return [summary, *contents]

    def _process_summary(self):
        marker = self._generate_new_ui_elem(
            tagName='summary',
            classes=self._classes_str,
            pseudoelement='marker'
        )
        return [marker, *self._children]

    def _process_dialog(self):
        if not self.has_class('framed'):
            return self._children

        if self._get_child_tagName(0) != 'h1':
            self.prepend_new_child(tagName='h1', innerText='Window')

        return self._children

    def _process_progress(self):
        # print('=====================')
        # print('PROCESSING PROGRESS')
        if self._ui_marker is None:
            self._ui_marker = self.append_new_child(
                tagName='progressmarker', #self._tagName,
                classes=self._classes_str,
                # pseudoelement='marker',
            )

            prev = -1

            def update_progress():
                nonlocal prev
                try:
                    percent = float(self.value or 0) / float(self.valueMax or 100)
                except Exception as e:
                    percent = random.random()
                    print(f'Caught {e} with {self.value=} and {self.valueMax=}')
                percent = int(100 * percent)
                if percent == prev: return
                prev = percent

                self._ui_marker.style = f'width:{percent}%'
                # self._ui_marker.style_width = f'{percent}%'
                self.dirty()
                self.dirty_flow()
                self._ui_marker.dirty()
                self._ui_marker.dirty_flow()
                # tag_redraw_all('update progress')
                # self.document.force_dirty_all()
            update_progress()
            self.add_eventListener('on_input', update_progress)

        # else:
        #     self._children_gen = [self._ui_marker]
        #     self._new_content = True


        return self._children # [self._ui_marker]


    def _process_h1(self):
        if self._parent and self._parent._tagName == 'dialog' and self._parent._children[0] == self:
            dialog = self._parent
            if not dialog.has_class('framed'):
                return self._children

            if not getattr(self, '_processed_dialog', False):
                self._processed_dialog = True

                # add minimize button to <h1> (only visible if dialog has minimizeable class)
                def minimize():
                    dialog.is_visible = False
                    dialog.dispatch_event('on_toggle')  # hijack the toggle event to catch minimize events
                self.prepend_new_child(tagName='button', title="Minimize dialog", classes='dialog-minimize dialog-action', on_mouseclick=minimize)

                # add close button to <h1> (only visible if dialog has closeable class)
                def close():
                    if dialog._parent is None: return
                    dialog._parent.delete_child(dialog)
                    dialog.dispatch_event('on_close')
                self.prepend_new_child(tagName='button', title="Close dialog", classes='dialog-close dialog-action', on_mouseclick=close)

                # add event handlers to <h1> for dragging window around (only moveable if dialog has moveable class)
                state = Dict(
                    is_dragging=False,
                    mousedown_pos=None,
                    original_pos=None,
                )
                def mousedown(e):
                    if not dialog.has_class('moveable'): return
                    if e.target != self and e.target != self: return
                    dialog.document.ignore_hover_change = True
                    state.is_dragging = True
                    state.mousedown_pos = e.mouse
                    l = dialog.left_pixels
                    if l is None or l == 'auto': l = 0
                    t = dialog.top_pixels
                    if t is None or t == 'auto': t = 0
                    state.original_pos = Point2D((float(l), float(t)))
                def mouseup(e):
                    if not dialog.has_class('moveable'): return
                    state.is_dragging = False
                    dialog.document.ignore_hover_change = False
                def mousemove(e):
                    if not dialog.has_class('moveable'): return
                    if not state.is_dragging: return
                    delta = e.mouse - state.mousedown_pos
                    new_pos = state.original_pos + delta
                    dialog.reposition(left=new_pos.x, top=new_pos.y)
                self.add_eventListener('on_mousedown', mousedown)
                self.add_eventListener('on_mouseup', mouseup)
                self.add_eventListener('on_mousemove', mousemove)

        return self._children

    def _process_li(self):
        if self._parent and self._parent._tagName == 'ul':
            # <ul><li>...
            if not self._ui_marker:
                self._ui_marker = self.prepend_new_child(tagName='li', classes=self._classes_str, pseudoelement='marker')
            return self._children

        elif self._parent and self._parent._tagName == 'ol':
            # <ol><li>...
            if not self._ui_marker:
                idx = next((i+1 for (i,c) in enumerate(self._parent._children) if self==c), 0)
                self._ui_marker = self.prepend_new_child(tagName='li', classes=self._classes_str, pseudoelement='marker', innerText=f'{idx}.')
            return self._children

        return self._children

    def _setup_element(self):
        processors = {
            'input text':     lambda: self._init_input_box('text'),
            'input number':   lambda: self._init_input_box('number'),
            'input radio':    self._init_input_radio,
        }
        processor = processors.get(self.tagType, None)
        return processor() if processor else None

    def _process_children(self):
        if self._innerTextAsIs is not None: return []
        if self._pseudoelement == 'marker': return self._children

        processors = {
            'input radio':    self._process_input_radio,
            'input checkbox': self._process_input_checkbox,
            'input text':     self._process_input_box,
            'input number':   self._process_input_box,
            'input range':    self._process_input_range,
            'details':        self._process_details,
            'summary':        self._process_summary,
            'label':          self._process_label,
            'dialog':         self._process_dialog,
            'h1':             self._process_h1,
            'li':             self._process_li,
            'progress':       self._process_progress,
        }
        processor = processors.get(self.tagType, None)

        return processor() if processor else self._children
