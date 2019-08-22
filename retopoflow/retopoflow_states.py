'''
Copyright (C) 2019 CG Cookie
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
import bmesh
from bpy.types import WorkSpaceTool
import random

from ..addon_common.cookiecutter.cookiecutter import CookieCutter


class RetopoFlow_States(CookieCutter):
    def update(self):
        self.rftool.update()

    @CookieCutter.FSM_State('main')
    def modal_main(self):
        if self.actions.pressed('commit'):
            self.done()
            return

        if self.actions.pressed('cancel'):
            self.done(cancel=True)
            return

        # self.check_auto_save()

        # handle help actions
        if self.actions.pressed('help'):
            # show help
            return

        # handle undo/redo
        if self.actions.pressed('undo'):
            self.rfcontext.undo_pop()
            if self.rftool: self.rftool.undone()
            return
        if self.actions.pressed('redo'):
            self.redo_pop()
            if self.rftool: self.rftool.undone()
            return

        if self.actions.pressed('F2'):
            self.rftool_select(self.rftools[2])



