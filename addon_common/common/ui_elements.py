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
import inspect
import traceback
import contextlib
from math import floor, ceil
from inspect import signature
from itertools import dropwhile
from concurrent.futures import ThreadPoolExecutor

import bpy
import bgl
import blf
import gpu

from .ui_proxy import UI_Proxy

from mathutils import Vector, Matrix

from .boundvar import BoundVar
from .debug import debugger, dprint, tprint
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .useractions import is_keycode
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
        if type(e.key) is int and is_keycode(e.key, 'ESC'):
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

tags_selfclose = {
    'area', 'br', 'col',
    'embed', 'hr', 'iframe',
    'img', 'input', 'link',
    'meta', 'param', 'source',
    'track', 'wbr'
}
tags_known = {
    'button',
    'span', 'div', 'p',
    'a',
    'b', 'i',
    'h1', 'h2', 'h3',
    'pre', 'code',
    'br',
    'img',
    'table', 'tr', 'th', 'td',
    'dialog',
    'label', 'input',
    'details', 'summary',
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
}


class UI_Element_Elements():
    @classmethod
    def fromHTMLFile(cls, path_html, *, frame_depth=1, f_globals=None, f_locals=None):
        if not path_html: return []
        if not os.path.exists(path_html): return []
        html = open(path_html, 'rt').read()
        return cls.fromHTML(html, frame_depth=frame_depth+1, f_globals=f_globals, f_locals=f_locals)

    @classmethod
    def fromHTML(cls, html, *, frame_depth=1, f_globals=None, f_locals=None):
        # use passed global and local contexts or grab contexts from calling function
        # these contexts are needed for bound variables
        if f_globals and f_locals:
            f_globals = f_globals
            f_locals = dict(f_locals)
        else:
            frame = inspect.currentframe()
            for i in range(frame_depth): frame = frame.f_back
            f_globals = f_globals or frame.f_globals
            f_locals = dict(f_locals or frame.f_locals)

        def get_next_tag(html, tname_end, tab, hierarchy):
            m_tag = re_html_tag.search(html)
            if not m_tag: return None

            pre_html = html[:m_tag.start()].strip()
            post_html = html[m_tag.end():].lstrip()

            tname = m_tag.group('name').lower()
            attributes = m_tag.group('attributes')
            is_close = m_tag.group('close') is not None
            is_selfclose = m_tag.group('selfclose') is not None or tname in tags_selfclose

            attribs = {}
            if attributes:
                for m_attrib in re_attributes.finditer(attributes):
                    k, v = m_attrib.group('key'), m_attrib.group('value')

                    # translate HTML attribs to CC UI attribs
                    if k.lower() in {'class'}: k = 'classes'

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

                    # convert value to Python value
                    m_self  = re_self.match(v)
                    m_bound = re_bound.match(v)
                    m_int   = re_int.match(v)
                    m_float = re_float.match(v)

                    if k.lower() in events_known:
                        # attribute is an event (value is callback)
                        k = events_known[k.lower()]
                        v = delay_exec(v, f_globals=f_globals, f_locals=f_locals)
                    elif v.lower() in {'true'}:  v = True
                    elif v.lower() in {'false'}: v = False
                    elif m_self:                 v = eval(v, f_globals, f_locals)
                    elif m_bound:                v = eval(v, f_globals, f_locals)
                    elif m_int:                  v = int(v)
                    elif m_float:                v = float(v)

                    attribs[k] = v

            assert not (is_close and attribs), 'Cannot have closing tag with attributes'
            assert not (is_close and is_selfclose), f'Cannot be closing and self-closing: {m_tag.group("tag")}'
            assert not (is_close and tname != tname_end), f'Found ending tag {m_tag.group("tag")} but expecting </{tname_end}>\n{hierarchy}'
            assert tname in tags_known, f'Unhandled tag type: {m_tag.group("tag")}'

            return Dict({
                'pre_html':     pre_html,
                'post_html':    post_html,
                'tname':        tname,
                'attribs':      attribs,
                'is_close':     is_close,
                'is_selfclose': is_selfclose,
            })

        def process(html, tname_end, hierarchy=[]):
            depth = len(hierarchy)
            tab = '  '*depth
            ret = []
            while html.strip():
                tag = get_next_tag(html, tname_end, tab, hierarchy)
                if not tag:
                    return (ret + [cls(tagName='span', innerText=html)], '')

                if tag.pre_html:
                    ret += [cls(tagName='span', innerText=tag.pre_html)]

                if tag.is_close:
                    return (ret, tag.post_html)
                elif tag.is_selfclose:
                    ret += [cls(tagName=tag.tname, **tag.attribs)]
                    html = tag.post_html
                else:
                    ntag = get_next_tag(tag.post_html, tag.tname, tab, hierarchy+[tag.tname])
                    if ntag and ntag.is_close:
                        # just stick pre_html into innerText
                        ret += [cls(tagName=tag.tname, innerText=ntag.pre_html, **tag.attribs)]
                        html = ntag.post_html
                    else:
                        children, html = process(tag.post_html, tag.tname, hierarchy+[tag.tname])
                        ret += [cls(tagName=tag.tname, children=children, **tag.attribs)]
            return (ret, html.strip())

        # strip leading and trailing whitespace characters
        html = re.sub(r'^[ \n\r\t]+', '', html)
        html = re.sub(r'[ \n\r\t]+$', '', html)
        # remove HTML comments
        html = re_html_comment.sub('', html)
        lui,rest = process(html, None)
        assert not rest, f'Could not process all of HTML\nRemaining: {rest}\nHTML: {html}'
        return lui

    def _process_input_text(self):
        if self._ui_marker is None:
            # just got focus, so create a cursor element
            self._ui_marker = self._generate_new_ui_elem(
                tagName=self._tagName,
                type=self._type,
                classes=self._classes_str,
                pseudoelement='marker',
            )
            self._ui_marker.is_visible = False

            data = {'orig':None, 'text':None, 'idx':0, 'pos':None}

            def preclean():
                nonlocal data
                if data['text'] is None:
                    if type(self.value) is float:
                        self.innerText = '%0.4f' % self.value
                    else:
                        self.innerText = str(self.value)
                else:
                    self.innerText = data['text']
                self.dirty_content(cause='preclean called')

            def postflow():
                nonlocal data
                if data['text'] is None: return
                data['pos'] = self.get_text_pos(data['idx'])
                if self._ui_marker._absolute_size:
                    self._ui_marker.reposition(
                        left=data['pos'].x - self._mbp_left - self._ui_marker._absolute_size.width / 2,
                        top=data['pos'].y + self._mbp_top,
                        clamp_position=False,
                    )
                    cursor_postflow()
            def cursor_postflow():
                nonlocal data
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
                nonlocal data
                data['idx'] = self.get_text_index(e.mouse)
                data['pos'] = self.get_text_pos(data['idx'])
                self.dirty_flow()

            def focus(e):
                s = f'{self.value:0.4f}' if type(self.value) is float else str(self.value)
                data['orig'] = data['text'] = s
                self._ui_marker.is_visible = True
                set_cursor(e)
            def blur(e):
                nonlocal data
                changed = self.value == data['text']
                self.value = data['text']
                data['text'] = None
                self._ui_marker.is_visible = False
                if changed: self.dispatch('on_change')

            def mouseup(e):
                nonlocal data
                if not e.button[0]: return
                # if not self.is_focused: return
                set_cursor(e)
            def mousemove(e):
                nonlocal data
                if data['text'] is None: return
                if not e.button[0]: return
                set_cursor(e)
            def mousedown(e):
                nonlocal data
                if data['text'] is None: return
                if not e.button[0]: return
                set_cursor(e)

            def keypress(e):
                nonlocal data
                if data['text'] == None: return
                if type(e.key) is int:
                    if is_keycode(e.key, 'BACK_SPACE'):
                        if data['idx'] == 0: return
                        data['text'] = data['text'][0:data['idx']-1] + data['text'][data['idx']:]
                        data['idx'] -= 1
                    elif is_keycode(e.key, 'RET'):
                        self.blur()
                    elif is_keycode(e.key, 'ESC'):
                        data['text'] = data['orig']
                        self.blur()
                    elif is_keycode(e.key, 'END'):
                        data['idx'] = len(data['text'])
                        self.dirty_flow()
                    elif is_keycode(e.key, 'HOME'):
                        data['idx'] = 0
                        self.dirty_flow()
                    elif is_keycode(e.key, 'LEFT_ARROW'):
                        data['idx'] = max(data['idx'] - 1, 0)
                        self.dirty_flow()
                    elif is_keycode(e.key, 'RIGHT_ARROW'):
                        data['idx'] = min(data['idx'] + 1, len(data['text']))
                        self.dirty_flow()
                    elif is_keycode(e.key, 'DEL'):
                        if data['idx'] == len(data['text']): return
                        data['text'] = data['text'][0:data['idx']] + data['text'][data['idx']+1:]
                    else:
                        return
                else:
                    data['text'] = data['text'][0:data['idx']] + e.key + data['text'][data['idx']:]
                    data['idx'] += 1
                preclean()

            self.preclean = preclean
            self.postflow = postflow

            self.add_eventListener('on_focus',     focus)
            self.add_eventListener('on_blur',      blur)
            self.add_eventListener('on_keypress',  keypress)
            self.add_eventListener('on_mousedown', mousedown)
            self.add_eventListener('on_mousemove', mousemove)
            self.add_eventListener('on_mouseup',   mouseup)

            preclean()
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

    def _process_input_radio(self):
        if self._ui_marker is None:
            self._ui_marker = self._generate_new_ui_elem(
                tagName=self._tagName,
                type=self._type,
                checked=self.checked,
                classes=self._classes_str,
                pseudoelement='marker',
            )
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
                self._ui_marker = self._generate_new_ui_elem(tagName='summary', innerText='Details')
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

    def _process_children(self):
        if self._innerTextAsIs is not None: return []
        if self._pseudoelement == 'marker': return self._children

        tagtype = f'{self._tagName}{f" {self._type}" if self._type else ""}'
        processor = {
            'input radio':    self._process_input_radio,
            'input checkbox': self._process_input_checkbox,
            'input text':     self._process_input_text,
            'details':        self._process_details,
            'summary':        self._process_summary,
            'label':          self._process_label,
        }.get(tagtype, None)

        return processor() if processor else self._children
