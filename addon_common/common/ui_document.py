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
import traceback
import contextlib
from math import floor, ceil
from inspect import signature
from itertools import dropwhile

import bpy
import blf
import gpu

from gpu_extras.presets import draw_texture_2d
from mathutils import Vector, Matrix

from . import gpustate

from . import ui_settings
from .gpustate import ScissorStack
from .ui_linefitter import LineFitter
from .ui_core import UI_Element
from .ui_core_preventmulticalls import UI_Core_PreventMultiCalls
from .blender import tag_redraw_all
from .ui_styling import UI_Styling, ui_defaultstylings
from .ui_core_utilities import helper_wraptext, convert_token_to_cursor
from .fsm import FSM

from .useractions import ActionHandler

from .boundvar import BoundVar
from .blender import get_view3d_area, get_view3d_region
from .debug import debugger, dprint, tprint
from .decorators import debug_test_call, blender_version_wrapper, add_cache
from .globals import Globals
from .hasher import Hasher
from .maths import Vec2D, Color, mid, Box2D, Size1D, Size2D, Point2D, RelPoint2D, Index2D, clamp, NumberUnit
from .profiler import profiler, time_it
from .utils import iter_head

from ..ext import png
from ..ext.apng import APNG



class UI_Document:
    default_keymap = {
        'commit': {'RET',},
        'cancel': {'ESC',},
        'keypress':
            {c for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'} |
            {'NUMPAD_%d'%i for i in range(10)} | {'NUMPAD_PERIOD','NUMPAD_MINUS','NUMPAD_PLUS','NUMPAD_SLASH','NUMPAD_ASTERIX'} |
            {'ZERO', 'ONE', 'TWO', 'THREE', 'FOUR', 'FIVE', 'SIX', 'SEVEN', 'EIGHT', 'NINE'} |
            {'PERIOD', 'MINUS', 'SPACE', 'SEMI_COLON', 'COMMA', 'QUOTE', 'ACCENT_GRAVE', 'PLUS', 'SLASH', 'BACK_SLASH', 'EQUAL', 'LEFT_BRACKET', 'RIGHT_BRACKET'},
        'scroll top': {'HOME'},
        'scroll bottom': {'END'},
        'scroll up': {'WHEELUPMOUSE', 'PAGE_UP', 'UP_ARROW', },
        'scroll down': {'WHEELDOWNMOUSE', 'PAGE_DOWN', 'DOWN_ARROW', },
        'scroll': {'TRACKPADPAN'},
    }

    doubleclick_time = bpy.context.preferences.inputs.mouse_double_click_time / 1000 # 0.25
    wheel_scroll_lines = 3 # bpy.context.preferences.inputs.wheel_scroll_lines, see https://developer.blender.org/rBbec583951d736776d2096368ef8d2b764287ac11
    allow_disabled_to_blur = False
    show_tooltips = True
    tooltip_delay = 0.50
    max_click_dist = 10         # allows mouse to travel off element and still register a click event
    allow_click_time = 0.50     # allows for very fast clicking. ignore max_click_dist if time(mouseup-mousedown) is at most allow_click_time

    def __init__(self):
        self._context = None
        self._area = None
        self._exception_callbacks = []
        self._ui_scale = Globals.drawing.get_dpi_mult()
        self._draw_count = 0
        self._draw_time = 0
        self._draw_fps = 0

    def add_exception_callback(self, fn):
        self._exception_callbacks += [fn]

    def _callback_exception_callbacks(self, e):
        for fn in self._exception_callbacks:
            try:
                fn(e)
            except Exception as e2:
                print(f'UI_Document: Caught exception while calling back exception callbacks: {fn.__name__}')
                print(f'    original:   {e}')
                print(f'    additional: {e2}')
                debugger.print_exception()

    @profiler.function
    def init(self, context, **kwargs):
        self._callbacks = {
            'preclean':  set(),
            'postclean': set(),
            'postflow':  set(),
            'postflow once': set(),
        }
        self.defer_cleaning = False

        self._context = context
        self._area = get_view3d_area(context)
        self.actions = ActionHandler(context, UI_Document.default_keymap)
        self._body = UI_Element(tagName='body', document=self)  # root level element
        self._tooltip = UI_Element(tagName='dialog', classes='tooltip', can_hover=False, parent=self._body)
        self._tooltip.is_visible = False
        self._tooltip_message = None
        self._tooltip_wait = None
        self._tooltip_mouse = None
        self._reposition_tooltip_before_draw = False

        self.fsm = FSM(self, start='main')

        self.ignore_hover_change = False

        self._sticky_dist = 20
        self._sticky_element = None # allows the mouse to drift a few pixels off before handling mouseleave

        self._under_mouse = None
        self._under_mousedown = None
        self._under_down = None
        self._focus = None
        self._focus_full = False

        self._last_mx = -1
        self._last_my = -1
        self._last_mouse = None
        self._last_under_mouse = None
        self._last_under_click = None
        self._last_click_time = 0
        self._last_sz = None
        self._last_w = -1
        self._last_h = -1

    def update_callbacks(self, ui_element, force_remove=False):
        for cb,fn in [('preclean', ui_element.preclean), ('postclean', ui_element.postclean), ('postflow', ui_element.postflow)]:
            if force_remove or not fn:
                self._callbacks[cb].discard(ui_element)
            else:
                self._callbacks[cb].add(ui_element)

    @property
    def body(self):
        return self._body

    @property
    def activeElement(self):
        return self._focus

    def center_on_mouse(self, element):
        # centers element under mouse, must be done between first and second layout calls
        if element is None: return
        def center():
            element._relative_pos = None
            mx, my = self.actions.mouse if self.actions.mouse else (10, 10)
            # w,h = element.width_pixels,element.height_pixels
            w, h = element.width_pixels, element._dynamic_full_size.height
            l = mx-w/2
            t = -self._body.height_pixels + my + h/2
            element.reposition(left=l, top=t)
        self._callbacks['postflow once'].add(center)

    def _reposition_tooltip(self, force=False):
        if self._tooltip_mouse == self.actions.mouse and not force: return
        self._tooltip_mouse = self.actions.mouse
        if self._tooltip.width_pixels is None or type(self._tooltip.width_pixels) is str or self._tooltip._mbp_width is None or self._tooltip.height_pixels is None or type(self._tooltip.height_pixels) is str or self._tooltip._mbp_height is None:
            ttl,ttt = self.actions.mouse
        else:
            ttl = self.actions.mouse.x if self.actions.mouse.x < self._body.width_pixels/2  else self.actions.mouse.x - (self._tooltip.width_pixels + (self._tooltip._mbp_width or 0))
            ttt = self.actions.mouse.y if self.actions.mouse.y > self._body.height_pixels/2 else self.actions.mouse.y + (self._tooltip.height_pixels + (self._tooltip._mbp_height or 0))
        hp = self._body.height_pixels if type(self._body.height_pixels) is not str else 0.0
        self._tooltip.reposition(left=ttl, top=ttt - hp)

    def removed_element(self, ui_element):
        if self._under_mouse and self._under_mouse.is_descendant_of(ui_element):
            self._under_mouse = None
        if self._under_mousedown and self._under_mousedown.is_descendant_of(ui_element):
            self._under_mousedown = None
        if self._focus and self._focus.is_descendant_of(ui_element):
            self._focus = None

    def force_dirty_all(self):
        self._body.dirty(children=True)
        self._body.dirty_styling()
        self._body.dirty_flow()
        tag_redraw_all('Force Dirty All')

    @profiler.function
    def update(self, context, event):
        self._context = context
        self._area = get_view3d_area(context)
        # if context.area != self._area: return
        # self._ui_scale = Globals.drawing.get_dpi_mult()

        UI_Core_PreventMultiCalls.reset_multicalls()

        region = get_view3d_region(context)
        w,h = region.width, region.height
        if self._last_w != w or self._last_h != h:
            # print('Document:', (self._last_w, self._last_h), (w,h))
            self._last_w,self._last_h = w,h
            self._body.dirty(cause='changed document size', children=True)
            self._body.dirty_flow()
            tag_redraw_all("UI_Element update: w,h change")

        if ui_settings.DEBUG_COLOR_CLEAN: tag_redraw_all("UI_Element DEBUG_COLOR_CLEAN")

        #self.actions.update(context, event, self._timer, print_actions=False)
        # self.actions.update(context, event, print_actions=False)

        if self._sticky_element and not self._sticky_element.is_visible:
            self._sticky_element = None

        self._mx,self._my = self.actions.mouse if self.actions.mouse else (-1,-1)
        if not self.ignore_hover_change:
            self._under_mouse = self._body.get_under_mouse(self.actions.mouse)
            if self._sticky_element:
                if self._sticky_element.get_mouse_distance(self.actions.mouse) < self._sticky_dist * self._ui_scale:
                    if self._under_mouse is None or not self._under_mouse.is_descendant_of(self._sticky_element):
                        self._under_mouse = self._sticky_element

        next_message = None
        if self._under_mouse and self._under_mouse.title_with_for(): # and not self._under_mouse.disabled:
            next_message = self._under_mouse.title_with_for()
            if self._under_mouse.disabled:
                next_message = f'(Disabled) {next_message}'
        if self._tooltip_message != next_message:
            self._tooltip_message = next_message
            self._tooltip_mouse = None
            self._tooltip_wait = time.time() + self.tooltip_delay
            self._tooltip.is_visible = False
        if self._tooltip_message and time.time() > self._tooltip_wait:
            if self._tooltip_mouse != self.actions.mouse or self._tooltip.innerText != self._tooltip_message or not self._tooltip.is_visible:
                # TODO: markdown support??
                self._tooltip.innerText = self._tooltip_message
                self._tooltip.is_visible = True and self.show_tooltips
                self._reposition_tooltip_before_draw = True
                tag_redraw_all("reposition tooltip")

        self.fsm.update()

        self._last_mx = self._mx
        self._last_my = self._my
        self._last_mouse = self.actions.mouse
        if not self.ignore_hover_change: self._last_under_mouse = self._under_mouse

        uictrld = False
        uictrld |= self._under_mouse is not None and self._under_mouse != self._body
        uictrld |= self.fsm.state != 'main'
        uictrld |= self._focus_full
        # uictrld |= self._focus is not None

        return {'hover'} if uictrld else None


    def _addrem_pseudoclass(self, pseudoclass, remove_from=None, add_to=None):
        rem = remove_from.get_pathToRoot() if remove_from else []
        add = add_to.get_pathToRoot() if add_to else []
        rem.reverse()
        add.reverse()
        roots = []
        if rem: roots.append(rem[0])
        if add: roots.append(add[0])
        while rem and add and rem[0] == add[0]:
            rem = rem[1:]
            add = add[1:]
        # print(f'addrem_pseudoclass: {pseudoclass} {rem} {add}')
        self.defer_cleaning = True
        for root in roots: root.defer_dirty_propagation = True
        for e in rem: e.del_pseudoclass(pseudoclass)
        for e in add: e.add_pseudoclass(pseudoclass)
        for root in roots: root.defer_dirty_propagation = False
        self.defer_cleaning = False

    def debug_print(self):
        print('')
        print('UI_Document.debug_print')
        self._body.debug_print(0, set())
    def debug_print_toroot(self, fromHovered=True, fromFocused=False):
        print('')
        print('UI_Document.debug_print_toroot')
        if fromHovered: self._debug_print(self._under_mouse)
        if fromFocused: self._debug_print(self._focus)
    def _debug_print(self, ui_from):
        # debug print!
        path = ui_from.get_pathToRoot()
        for i,ui_elem in enumerate(reversed(path)):
            def tprint(*args, extra=0, **kwargs):
                print('  '*(i+extra), end='')
                print(*args, **kwargs)
            tprint(str(ui_elem))
            tprint(f'selector={ui_elem._selector}', extra=1)
            tprint(f'l={ui_elem._l} t={ui_elem._t}  w={ui_elem._w} h={ui_elem._h}', extra=1)

    @property
    def sticky_element(self):
        return self._sticky_element
    @sticky_element.setter
    def sticky_element(self, element):
        self._sticky_element = element

    def clear_last_under(self):
        self._last_under_mouse = None

    def handle_hover(self, change_cursor=True):
        # handle :hover, on_mouseenter, on_mouseleave
        if self.ignore_hover_change: return

        if change_cursor and self._under_mouse and self._under_mouse._tagName != 'body':
            cursor = self._under_mouse._computed_styles.get('cursor', 'default')
            Globals.cursors.set(convert_token_to_cursor(cursor))

        if self._under_mouse == self._last_under_mouse: return
        if self._under_mouse and not self._under_mouse.can_hover: return

        self._addrem_pseudoclass('hover', remove_from=self._last_under_mouse, add_to=self._under_mouse)
        if self._last_under_mouse: self._last_under_mouse.dispatch_event('on_mouseleave')
        if self._under_mouse: self._under_mouse.dispatch_event('on_mouseenter')

    def handle_mousemove(self, ui_element=None):
        ui_element = ui_element or self._under_mouse
        if ui_element is None: return
        if self._last_mouse == self.actions.mouse: return
        ui_element.dispatch_event('on_mousemove')

    def handle_keypress(self, ui_element=None):
        ui_element = ui_element or self._focus

        if self.actions.pressed('clipboard paste') and ui_element:
            ui_element.dispatch_event('on_paste', clipboardData=bpy.context.window_manager.clipboard)

        pressed = self.actions.as_char(self.actions.just_pressed)

        if pressed and ui_element:
            ui_element.dispatch_event('on_keypress', key=pressed)


    @FSM.on_state('main', 'enter')
    def modal_main_enter(self):
        Globals.cursors.set('DEFAULT')

    @FSM.on_state('main')
    def modal_main(self):
        # print('UI_Document.main', self.actions.event_type, time.time())


        if self.actions.just_pressed:
            pressed = self.actions.just_pressed
            if pressed not in {'WINDOW_DEACTIVATE'}:
                if self._focus and self._focus_full:
                    self._focus.dispatch_event('on_keypress', key=pressed)
                elif self._under_mouse:
                    self._under_mouse.dispatch_event('on_keypress', key=pressed)

        self.handle_hover()
        self.handle_mousemove()

        if self.actions.pressed('MIDDEMOUSE'):
            return 'scroll'

        if self.actions.pressed('LEFTMOUSE', unpress=False, ignoremods=True, ignoremulti=True):
            if self._under_mouse == self._body:
                # clicking body always blurs focus
                self.blur()
            elif UI_Document.allow_disabled_to_blur and self._under_mouse and self._under_mouse.is_disabled:
                # user clicked on disabled element, so blur current focused element
                self.blur()
            return 'mousedown'

        if self.actions.pressed('SHIFT+F10'):
            profiler.clear()
            return
        if self.actions.pressed('SHIFT+F11'):
            profiler.printout()
            self.debug_print()
            return
        if self.actions.pressed('CTRL+SHIFT+F11'):
            self.debug_print_toroot()
            print(f'{self._under_mouse._computed_styles}')
            return

        # if self.actions.pressed('RIGHTMOUSE') and self._under_mouse:
        #     self._debug_print(self._under_mouse)
        #     #print('focus:', self._focus)

        if self.actions.pressed({'scroll top', 'scroll bottom'}, unpress=False):
            move = 100000 * (-1 if self.actions.pressed({'scroll top'}) else 1)
            self.actions.unpress()
            if self._get_scrollable():
                self._scroll_element.scrollTop = self._scroll_last.y + move
                self._scroll_element._setup_ltwh(recurse_children=False)

        if self.actions.pressed({'scroll', 'scroll up', 'scroll down'}, unpress=False):
            if self.actions.event_type == 'TRACKPADPAN':
                move = self.actions.scroll[1] # self.actions.mouse.y - self.actions.mouse_prev.y
                # print(f'UI_Document.update: trackpad pan {move}')
            else:
                d = self.wheel_scroll_lines * 8 * Globals.drawing.get_dpi_mult()
                move = Globals.drawing.scale(d) * (-1 if self.actions.pressed({'scroll up'}) else 1)
            self.actions.unpress()
            if self._get_scrollable():
                self._scroll_element.scrollTop = self._scroll_last.y + move
                self._scroll_element._setup_ltwh(recurse_children=False)

        # if self.actions.pressed('F8') and self._under_mouse:
        #     print('\n\n')
        #     for e in self._under_mouse.get_pathFromRoot():
        #         print(e)
        #         print(e._dirty_causes)
        #         for s in e._debug_list:
        #             print(f'    {s}')
        if False:
            print('---------------------------')
            if self._focus:      print('FOCUS', self._focus, self._focus.pseudoclasses)
            else: print('FOCUS', None)
            if self._under_down: print('DOWN',  self._under_down, self._under_down.pseudoclasses)
            else: print('DOWN', None)
            if under_mouse:      print('UNDER', under_mouse, under_mouse.pseudoclasses)
            else: print('UNDER', None)

    def _get_scrollable(self):
        # find first along root to path that can scroll
        if not self._under_mouse: return None
        self._scroll_element = next((e for e in self._under_mouse.get_pathToRoot() if e.is_scrollable_y), None)
        if self._scroll_element:
            self._scroll_last = RelPoint2D((self._scroll_element.scrollLeft, self._scroll_element.scrollTop))
        return self._scroll_element

    @FSM.on_state('scroll', 'can enter')
    def scroll_canenter(self):
        if not self._get_scrollable(): return False

    @FSM.on_state('scroll', 'enter')
    def scroll_enter(self):
        self._scroll_point = self.actions.mouse
        self.ignore_hover_change = True
        Globals.cursors.set('SCROLL_Y')

    @FSM.on_state('scroll')
    def scroll_main(self):
        if self.actions.released('MIDDLEMOUSE', ignoremods=True, ignoremulti=True):
            # done scrolling
            return 'main'
        nx = self._scroll_element.scrollLeft + (self._scroll_point.x - self._mx)
        ny = self._scroll_element.scrollTop  - (self._scroll_point.y - self._my)
        self._scroll_element.scrollLeft = nx
        self._scroll_element.scrollTop = ny
        self._scroll_point = self.actions.mouse
        self._scroll_element._setup_ltwh(recurse_children=False)

    @FSM.on_state('scroll', 'exit')
    def scroll_exit(self):
        self.ignore_hover_change = False


    @FSM.on_state('mousedown', 'can enter')
    def mousedown_canenter(self):
        return self._focus or (
                self._under_mouse and self._under_mouse != self._body and not self._under_mouse.is_disabled
            )

    @FSM.on_state('mousedown', 'enter')
    def mousedown_enter(self):
        self._mousedown_time = time.time()
        self._under_mousedown = self._under_mouse
        if not self._under_mousedown:
            # likely, self._under_mouse or an ancestor was deleted?
            # mousedown main event handler below will switch FSM back to main, effectively ignoring the mousedown event
            # see RetopoFlow issue #857
            self.blur()
            return
        self._addrem_pseudoclass('active', add_to=self._under_mousedown)
        self._under_mousedown.dispatch_event('on_mousedown')
        # print(self._under_mouse.get_pathToRoot())

        change_focus = self._focus != self._under_mouse
        if change_focus:
            if self._under_mouse.can_focus:
                # element under mouse takes focus (or whichever it's for points to)
                if self._under_mouse.forId:
                    f = self._under_mouse.get_for_element()
                    if f and f.can_focus: self.focus(f)
                    else: self.focus(self._under_mouse)
                else: self.focus(self._under_mouse)
            elif self._focus and self._is_ancestor(self._focus, self._under_mouse):
                # current focus is an ancestor of new element, so don't blur!
                pass
            else:
                self.blur()

    @FSM.on_state('mousedown')
    def mousedown_main(self):
        if not self._under_mousedown:
            return 'main'
        if self.actions.released('LEFTMOUSE', ignoremods=True, ignoremulti=True):
            # done with mousedown
            return 'focus' if self._under_mousedown.can_focus else 'main'

        if self.actions.pressed('RIGHTMOUSE', ignoremods=True, unpress=False):
            self._under_mousedown.dispatch_event('on_mousedown')

        self.handle_hover(change_cursor=False)
        self.handle_mousemove(ui_element=self._under_mousedown)
        self.handle_keypress(ui_element=self._under_mousedown)

    @FSM.on_state('mousedown', 'exit')
    def mousedown_exit(self):
        if not self._under_mousedown:
            # likely, self._under_mousedown or an ancestor was deleted while under mousedown
            # need to reset variables enough to get us back to main FSM state!
            self._last_under_click = None
            self._last_click_time = 0
            self.ignore_hover_change = False
            return
        self._under_mousedown.dispatch_event('on_mouseup')
        under_mouseclick = self._under_mousedown
        click = False
        click |= time.time() - self._mousedown_time < self.allow_click_time
        click |= self._under_mousedown.get_mouse_distance(self.actions.mouse) <= self.max_click_dist * self._ui_scale
        if not click:
            # find closest common ancestor of self._under_mouse and self._under_mousedown that is getting clicked
            ancestors0 = self._under_mousedown.get_pathFromRoot()
            ancestors1 = self._under_mouse.get_pathFromRoot() if self._under_mouse else []
            ancestors = [a0 for (a0, a1) in zip(ancestors0, ancestors1) if a0 == a1 and a0.get_mouse_distance(self.actions.mouse) < 1]
            if ancestors:
                under_mouseclick = ancestors[-1]
                click = True
        # print('mousedown_exit', time.time()-self._mousedown_time, self.allow_click_time, self.actions.mouse, self._under_mousedown.get_mouse_distance(self.actions.mouse), self.max_click_dist)
        if click:
            # old/simple: self._under_mouse == self._under_mousedown:
            dblclick = True
            dblclick &= under_mouseclick == self._last_under_click
            dblclick &= time.time() < self._last_click_time + self.doubleclick_time
            under_mouseclick.dispatch_event('on_mouseclick')
            self._last_under_click = under_mouseclick
            if dblclick:
                under_mouseclick.dispatch_event('on_mousedblclick')
                # self._last_under_click = None
            # if self._under_mousedown:
            #     # if applicable, send mouseclick events to ui_element indicated by forId
            #     ui_for = self._under_mousedown.get_for_element()
            #     print(f'mousedown_exit:')
            #     print(f'    ui under: {self._under_mousedown}')
            #     print(f'    ui for: {ui_for}')
            #     if ui_for: ui_for.dispatch_event('on_mouseclick')
            self._last_click_time = time.time()
        else:
            self._last_under_click = None
            self._last_click_time = 0
        self._addrem_pseudoclass('active', remove_from=self._under_mousedown)
        # self._under_mousedown.del_pseudoclass('active')

    def _is_ancestor(self, ancestor, descendant):
        return ancestor in descendant.get_pathToRoot()

    def blur(self, stop_at=None):
        self._focus_full = False
        if self._focus is None: return
        self._focus.del_pseudoclass('focus')
        self._focus.dispatch_event('on_blur')
        self._focus.dispatch_event('on_focusout', stop_at=stop_at)
        self._addrem_pseudoclass('active', remove_from=self._focus)
        self._focus = None

    def focus(self, ui_element, full=False):
        if ui_element is None: return
        if self._focus == ui_element: return

        stop_focus_at = None
        if self._focus:
            stop_blur_at = None
            p_focus = ui_element.get_pathFromRoot()
            p_blur = self._focus.get_pathFromRoot()
            for i in range(min(len(p_focus), len(p_blur))):
                if p_focus[i] != p_blur[i]:
                    stop_focus_at = p_focus[i]
                    stop_blur_at = p_blur[i]
                    break
            self.blur(stop_at=stop_blur_at)
            #print('focusout to', p_blur, stop_blur_at)
            #print('focusin from', p_focus, stop_focus_at)
        self._focus_full = full
        self._focus = ui_element
        self._focus.add_pseudoclass('focus')
        self._focus.dispatch_event('on_focus')
        self._focus.dispatch_event('on_focusin', stop_at=stop_focus_at)


    @FSM.on_state('focus')
    def focus_main(self):
        if not self._focus:
            return 'main'

        if self._focus_full:
            pass

        if self.actions.pressed('LEFTMOUSE', unpress=False):
            return 'mousedown'
        # if self.actions.pressed('RIGHTMOUSE'):
        #     self._debug_print(self._focus)
        # if self.actions.pressed('ESC'):
        #     self.blur()
        #     return 'main'

        self.handle_hover()
        self.handle_mousemove()
        self.handle_keypress()

        if not self._focus: return 'main'

    def force_clean(self, context):
        if self.defer_cleaning: return

        time_start = time.time()

        region = get_view3d_region(context)
        w,h = region.width, region.height
        sz = Size2D(width=w, max_width=w, height=h, max_height=h)

        UI_Core_PreventMultiCalls.reset_multicalls()

        Globals.ui_draw.update()
        if Globals.drawing.get_dpi_mult() != self._ui_scale:
            print(f'DPI CHANGED: {self._ui_scale} -> {Globals.drawing.get_dpi_mult()}')
            self._ui_scale = Globals.drawing.get_dpi_mult()
            self._body.dirty(cause='DPI changed', children=True)
            self._body.dirty_styling()
            self._body.dirty_flow(children=True)
        if (w,h) != self._last_sz:
            self._last_sz = (w,h)
            self._body.dirty_flow()
            # self._body.dirty('region size changed', 'style', children=True)

        # UI_Core_PreventMultiCalls.reset_multicalls()
        for o in self._callbacks['preclean']: o._call_preclean()
        self._body.clean()
        for o in self._callbacks['postclean']: o._call_postclean()
        self._body._layout(
            # linefitter=LineFitter(left=0, top=h-1, width=w, height=h),
            fitting_size=sz,
            fitting_pos=Point2D((0,h-1)),
            parent_size=sz,
            nonstatic_elem=self._body,
            table_data={},
        )
        self._body.set_view_size(sz)
        for o in self._callbacks['postflow']: o._call_postflow()
        for fn in self._callbacks['postflow once']: fn()
        self._callbacks['postflow once'].clear()

        # UI_Core_PreventMultiCalls.reset_multicalls()
        self._body._layout(
            # linefitter=LineFitter(left=0, top=h-1, width=w, height=h),
            fitting_size=sz,
            fitting_pos=Point2D((0,h-1)),
            parent_size=sz,
            nonstatic_elem=self._body,
            table_data={},
        )
        self._body.set_view_size(sz)
        if self._reposition_tooltip_before_draw:
            self._reposition_tooltip_before_draw = False
            self._reposition_tooltip()

    @profiler.function
    def draw(self, context):
        self._context = context
        self._area = get_view3d_area(context)
        # if self._area != context.area: return
        Globals.drawing.glCheckError('UI_Document.draw: start')

        time_start = time.time()

        self.force_clean(context)

        Globals.drawing.glCheckError('UI_Document.draw: setting options')
        ScissorStack.start(context)
        gpustate.blend('ALPHA')
        gpustate.scissor_test(True)
        gpustate.depth_test('NONE')

        Globals.drawing.glCheckError('UI_Document.draw: drawing')
        self._body.draw()
        ScissorStack.end()

        self._draw_count += 1
        self._draw_time += time.time() - time_start
        if self._draw_count % 100 == 0:
            fps = (self._draw_count / self._draw_time) if self._draw_time>0 else float('inf')
            self._draw_fps = fps
            # print('~%f fps  (%f / %d = %f)' % (self._draw_fps, self._draw_time, self._draw_count, self._draw_time / self._draw_count))
            self._draw_count = 0
            self._draw_time = 0

        Globals.drawing.glCheckError('UI_Document.draw: done')

ui_document = Globals.set(UI_Document())

