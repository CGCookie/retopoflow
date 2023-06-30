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

from ...addon_common.common.fsm import FSM
from ...addon_common.common.globals import Globals
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.maths import Vec, Point, Point2D, Direction, Color
from ...config.options import themes


'''
RFWidget_Default has no callbacks/actions.
This RFWidget is useful for very simple cursor setting.
'''

class RFWidget_Hidden_Factory:
    '''
    This is a class factory.  It is needed, because the FSM is shared across instances.
    RFTools might need to share RFWidgets that are independent of each other.
    '''

    @staticmethod
    def create(*, action_name=None, cursor='NONE'):
        class RFWidget_Hidden(RFWidget):
            rfw_name = 'Hidden'
            rfw_cursor = cursor

            @RFWidget.on_init
            def init(self):
                self.action_name = action_name

            @FSM.on_state('main')
            def modal_main(self):
                pass

        return RFWidget_Hidden
