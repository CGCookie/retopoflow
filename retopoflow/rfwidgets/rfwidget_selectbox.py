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

import math
import random
from mathutils import Matrix, Vector

from ..rfwidget import RFWidget

from ...addon_common.common import gpustate
from ...addon_common.common.fsm import FSM
from ...addon_common.common.globals import Globals
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.drawing import DrawCallbacks
from ...addon_common.common.maths import Vec, Point, Point2D, Direction, Color
from ...config.options import themes


'''
RFWidget_LineCut handles a line cut in screen space.
When cutting, a line segment is drawn from mouse down to current mouse position with a small circle at the very center
'''

class RFWidget_SelectBox_Factory:
    '''
    This function is a class factory.  It is needed, because the FSM is shared across instances.
    RFTools might need to share RFWidgets that are independent of each other.
    '''

    @staticmethod
    def create(action_name, *, set_color=None, add_color=None, del_color=None):
        class RFWidget_SelectBox(RFWidget):
            rfw_name = 'Select Box'
            rfw_cursor = 'CROSSHAIR'

            @RFWidget.on_init
            def init(self):
                self.action_name = action_name
                self.box2D = [None, None]
                self.set_color = set_color or themes['set select']
                self.add_color = add_color or themes['add select']
                self.del_color = del_color or themes['del select']

            @FSM.on_state('main')
            def modal_main(self):
                if self.actions.pressed({'select box'}):
                    return 'box'

            def quickselect_start(self):
                self._fsm.force_set_state('box')

            @FSM.on_state('box', 'enter')
            def modal_line_enter(self):
                self.box2D = [self.actions.mouse, None]
                self.mods = None
                tag_redraw_all('Line line_enter')

            @FSM.on_state('box')
            def modal_line(self):
                if self.actions.released('select box', ignoremods=True):
                    self.callback_actions(self.action_name)
                    return 'main'

                if self.actions.pressed('cancel'):
                    self.box2D = [None, None]
                    return 'main'

                new_mods = {
                    'ctrl':  self.actions.ctrl,
                    'alt':   self.actions.alt,
                    'shift': self.actions.shift,
                    'oskey': self.actions.oskey,
                }
                if self.box2D[1] != self.actions.mouse or new_mods != self.mods:
                    self.box2D[1] = self.actions.mouse
                    self.mods = new_mods
                    tag_redraw_all('boxing')
                    self.callback_actioning(self.action_name)

            @FSM.on_state('box', 'exit')
            def modal_line_exit(self):
                tag_redraw_all('Line line_exit')

            @DrawCallbacks.on_draw('post2d')
            @FSM.onlyinstate('box')
            def draw_line(self):
                #cr,cg,cb,ca = self.line_color
                p0,p1 = self.box2D
                if not p0 or not p1: return

                x0, y0 = p0
                x1, y1 = p1
                if   self.mods['ctrl']:  c = self.del_color
                elif self.mods['shift']: c = self.add_color
                else:                    c = self.set_color

                gpustate.blend('ALPHA')
                Globals.drawing.draw2D_line((x0, y0), (x1, y0), c, width=1, stipple=[2, 2])  # self.line_color)
                Globals.drawing.draw2D_line((x1, y0), (x1, y1), c, width=1, stipple=[2, 2])  # self.line_color)
                Globals.drawing.draw2D_line((x1, y1), (x0, y1), c, width=1, stipple=[2, 2])  # self.line_color)
                Globals.drawing.draw2D_line((x0, y1), (x0, y0), c, width=1, stipple=[2, 2])  # self.line_color)

        return RFWidget_SelectBox

