'''
Copyright (C) 2018 CG Cookie

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

import bpy
import bgl
from .cookiecutter import CookieCutter
from ..common.maths import Point2D
from ..common import ui

from .test_fsm import CookieCutter_Test_FSM
from .test_ui import CookieCutter_Test_UI

class CookieCutter_Test(CookieCutter, CookieCutter_Test_FSM, CookieCutter_Test_UI):
    bl_idname = "view3d.cookiecutter_test"
    bl_label = "CookieCutter Tester"
    
    default_keymap = {
        'commit': 'RET',
        'cancel': 'ESC',
        'grab': 'G',
    }
    
    def start(self):
        opts = {
            'pos': 9,
            'movable': True,
            'bgcolor': (0.2, 0.2, 0.2, 0.8),
            'padding': 0,
            }
        win = self.wm.create_window('test',opts)
        bigcontainer = win.add(ui.UI_Container(margin=0))
        bigcontainer.add(ui.UI_Label('foo bar'))
        bigcontainer.add(ui.UI_Button('exit', self.done))
        #self.window_manager.set_focus(win, darken=False, close_on_leave=True)
    
