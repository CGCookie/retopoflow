'''
Copyright (C) 2021 CG Cookie
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

import os
import bpy
import copy
import glob
import time

from .rf.rf_helpsystem import RetopoFlow_HelpSystem

from ..addon_common.common.globals import Globals
from ..addon_common.common import ui_core
from ..addon_common.common.useractions import ActionHandler
from ..addon_common.common.fsm import FSM

from ..addon_common.cookiecutter.cookiecutter import CookieCutter

from ..config.keymaps import get_keymaps
from ..config.options import options


class RetopoFlow_OpenHelpSystem(CookieCutter, RetopoFlow_HelpSystem):
    @classmethod
    def can_start(cls, context):
        return True

    def blender_ui_set(self):
        self.viewaa_simplify()
        # self.manipulator_hide()
        self.panels_hide()
        # self.overlays_hide()
        self.quadview_hide()
        self.region_darken()
        self.header_text_set('RetopoFlow')

    def start(self):
        ui_core.ASYNC_IMAGE_LOADING = options['async image loading']

        # preload_help_images.paused = True
        keymaps = get_keymaps()
        self.actions = ActionHandler(self.context, keymaps)
        self.reload_stylings()
        self.blender_ui_set()
        self.helpsystem_open(self.rf_startdoc, done_on_esc=True, closeable=True, on_close=self.done)
        Globals.ui_document.body.dirty(cause='changed document size', children=True)

    def end(self):
        self._cc_blenderui_end()

    # def update(self):
    #     preload_help_images.paused = False

    @FSM.on_state('main')
    def main(self):
        # print(f'Help System main')
        if self.actions.pressed({'done', 'done alt0'}):
            self.done()
            return
        if self.actions.pressed({'F12'}):
            self.reload_stylings()
            return
