'''
Copyright (C) 2020 CG Cookie
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

from ..common.fsm import FSM
from ..common.debug import debugger

class CookieCutter_FSM:
    fsm = FSM()
    FSM_State = fsm.wrapper

    def _cc_fsm_init(self):
        self.fsm.init(self, start='main')
        def callback(e): self._handle_exception(e, 'handle exception caught by FSM')
        #self.fsm.add_exception_callback(callback)

    def _cc_fsm_update(self):
        self.fsm.update()

