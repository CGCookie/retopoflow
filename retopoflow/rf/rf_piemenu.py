'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import math
import time
import random
from itertools import chain
from collections import deque

from ..rfmesh.rfmesh_wrapper import RFVert, RFEdge, RFFace

from ...addon_common.cookiecutter.cookiecutter import CookieCutter
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.decorators import timed_call
from ...addon_common.common.drawing import Cursors
from ...addon_common.common.fsm import FSM
from ...addon_common.common.maths import Vec2D, Point2D, RelPoint2D, Direction2D
from ...addon_common.common.profiler import profiler
from ...addon_common.common.ui_core import UI_Element
from ...addon_common.common.utils import normalize_triplequote, Dict
from ...config.options import options, retopoflow_files
from ...addon_common.common.timerhandler import StopwatchHandler

class RetopoFlow_PieMenu:
    def which_pie_menu_section(self):
        delta = self.actions.mouse - self.pie_menu_center
        if delta.length < self.pie_menu_center_size / 2: return None
        count = len(self.pie_menu_options)
        clock_deg = (math.atan2(-delta.y, delta.x) * 180 / math.pi - self.pie_menu_rotation) % 360
        section = math.floor((clock_deg + 360 / count / 2) % 360 / (360 / count))
        return section

    @staticmethod
    def _estimate_text_height(text, wrap_width):
        font_w, font_h = 6, 16                              # very rough approximation!
        line_count = 0
        for line in text.splitlines():
             text_w = max(1, len(line)) * font_w            # approx width of text w/o wrapping
             line_count += math.ceil(text_w / wrap_width)   # approx num of lines w/ wrapping
        text_h = max(1, line_count) * font_h                # approx height of text w/ wrapping
        return text_h

    @FSM.on_state('pie menu', 'enter')
    def pie_menu_enter(self):
        scale = self.drawing.scale
        doc_h = self.document.body.height_pixels
        menu = Dict(
            size   = 512, # size of full menu
            radius = 204, # size of option center ring (40% of menu)
            option =  72, # size of option
            inner  = 100, # size of inner circle
        )
        center = self.actions.mouse - Vec2D((scale(menu.size) / 2, -scale(menu.size) / 2)) - Vec2D((0, doc_h))
        ui_pie_menu_contents = self.ui_pie_menu.getElementById('pie-menu-contents')
        ui_pie_menu_contents.clear_children()
        ui_pie_menu_contents.style = ';'.join([
            f'left:{center.x}px',
            f'top:{center.y}px',
            f'width:{menu.size}px',
            f'height:{menu.size}px',
            f'border-radius:{menu.size // 2}px',
            f'padding:{menu.size // 2}px',
        ])
        count = len(self.pie_menu_options)
        self.ui_pie_sections = []
        for i_option, option in enumerate(self.pie_menu_options):
            if not option:
                self.ui_pie_sections.append(None)
                continue
            if type(option) is str:   option = (option,)
            if type(option) is tuple: option = { k:v for k,v in zip(['text', 'value', 'image'], option) }
            option.setdefault('value', option['text'])
            option.setdefault('image', '')
            self.pie_menu_options[i_option] = option['value']
            r = ((i_option / count) * 360 + self.pie_menu_rotation) * (math.pi / 180)
            left, top = scale(menu.radius) * math.cos(r) - (scale(menu.option)/2), -(scale(menu.radius) * math.sin(r) - (scale(menu.option)/2))
            label = UI_Element.DIV(classes='pie-menu-option-text', innerText=option['text'])
            image = None
            highlight_class = 'highlighted' if option['value'] == self.pie_menu_highlighted else ''
            if option['image']:
                image = UI_Element.IMG(classes='pie-menu-option-image', src=option['image'], style=f'width:{menu.option}px')
            else:
                # TODO: actually handle vertical-align: middle!
                text_h = self._estimate_text_height(option['text'], menu.option)    # very rough approximation!
                margin = (menu.option - text_h) // 2                                # offset using margin
                label.style = f'margin-top:{margin}px'
            ui = UI_Element.DIV(
                style=';'.join([
                    f'left:{int(left)}px',
                    f'top:{int(top)}px',
                    f'width:{menu.option}px',
                    f'height:{menu.option}px',
                ]),
                classes=f"pie-menu-option {highlight_class}",
                children=list(filter(None, [ label, image ])),
                parent=ui_pie_menu_contents,
            )
            self.ui_pie_sections.append(ui)

        UI_Element.DIV(
            style=';'.join([
                f'left:{-scale(menu.inner) // 2}px',
                f'top:{scale(menu.inner) // 2}px',
                f'width:{menu.inner}px',
                f'height:{menu.inner}px',
                f'border-radius:{menu.inner // 2}px',
            ]),
            classes=f'pie-menu-inner',
            parent=ui_pie_menu_contents,
        )

        self.ui_pie_menu.is_visible = True
        self.pie_menu_center = self.actions.mouse
        self.pie_menu_center_size = scale(menu.inner)
        self.pie_menu_mouse = self.actions.mouse
        self.document.focus(self.ui_pie_menu)
        self.document.force_clean(self.actions.context)

    @FSM.on_state('pie menu')
    def pie_menu_main(self):
        confirm_p = self.actions.pressed('pie menu confirm', ignoremods=True)
        confirm_r = self.actions.released(self.pie_menu_release, ignoremods=True)
        if confirm_p or confirm_r:
            # setting display to none in case callback needs to show some UI
            self.ui_pie_menu.is_visible = False
            i_option = self.which_pie_menu_section()
            option = self.pie_menu_options[i_option] if i_option is not None else None
            if option is not None or self.pie_menu_always_callback:
                self.pie_menu_callback(option)
            return 'main' if confirm_r else 'pie menu wait'
        if self.actions.pressed('cancel'):
            return 'pie menu wait'
        i_section = self.which_pie_menu_section()
        for i_s,ui in enumerate(self.ui_pie_sections):
            if not ui: continue
            if i_s == i_section:
                ui.add_pseudoclass('hover')
            else:
                ui.del_pseudoclass('hover')

    @FSM.on_state('pie menu', 'exit')
    def pie_menu_exit(self):
        self.ui_pie_menu.is_visible = False

    @FSM.on_state('pie menu wait')
    def pie_menu_wait(self):
        if self.actions.released(self.pie_menu_release, ignoremods=True):
            return 'main'
