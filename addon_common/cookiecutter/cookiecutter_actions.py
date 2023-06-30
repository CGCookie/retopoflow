'''
Copyright (C) 2023 CG Cookie

https://github.com/CGCookie/retopoflow

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

import sys
import copy
import math
import time

import bpy

from ..common.useractions import ActionHandler


class CookieCutter_Actions:
    def _cc_actions_init(self):
        self._cc_actions = ActionHandler(self.context)
        self._timer = self._cc_actions.start_timer(10)

    def _cc_actions_update(self):
        self._cc_actions.update(self.context, self.event, fn_debug=self.debug_print_actions)

    def _cc_actions_end(self):
        self._timer.done()
        self._cc_actions.done()



