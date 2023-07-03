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
from ..rftool import RFTool
from ..rfwidget import RFWidget
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_selectbox import RFWidget_SelectBox_Factory


from ...addon_common.common.maths import (
    Vec, Vec2D,
    Point, Point2D,
    Direction,
    Accel2D,
    Color,
    closest_point_segment,
)
from ...addon_common.common.fsm import FSM
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs, delay_exec
from ...config.options import options, themes


class Select(RFTool):
    name        = 'Select'
    description = 'Select geometry'
    icon        = 'relax-icon.png'
    help        = 'select.md'
    shortcut    = 'select tool'
    quick_shortcut = 'select quick'
    statusbar   = '{{select box}} Select'
    ui_config   = 'select_options.html'

    RFWidget_Default   = RFWidget_Default_Factory.create()
    RFWidget_SelectBox = RFWidget_SelectBox_Factory.create('Select: Box')

    @RFTool.on_init
    def init(self):
        self.rfwidgets = {
            'default':   self.RFWidget_Default(self),
            'selectbox': self.RFWidget_SelectBox(self),
            # circle select????
        }
        self.rfwidget = None

    @RFTool.on_quickselect_start
    def quickselect_start(self):
        self.rfwidgets['selectbox'].quickselect_start()

    @FSM.on_state('main')
    def main(self):
        self.set_widget('selectbox')

        # if self.rfcontext.actions.pressed(['brush', 'brush alt'], unpress=False):
        #     self.sel_only = self.rfcontext.actions.using('brush alt')
        #     self.rfcontext.actions.unpress()
        #     self.rfcontext.undo_push('relax')
        #     return 'relax'

    @RFWidget.on_action('Select: Box')
    @RFTool.dirty_when_done
    def selectbox(self):
        box = self.rfwidgets['selectbox']
        p0, p1 = box.box2D
        if not p0 or not p1: return

        (x0, y0), (x1, y1) = p0, p1
        left, right = min(x0, x1), max(x0, x1)
        bottom, top = min(y0, y1), max(y0, y1)
        get_point2D = self.rfcontext.get_point2D
        def inside(v):
            p = get_point2D(v.co)
            return left <= p.x <= right and bottom <= p.y <= top
        verts_inside = { v for v in self.rfcontext.visible_verts() if inside(v) }

        if box.mods['ctrl']:
            # deselect verts inside
            verts_selected = self.rfcontext.get_selected_verts()
            self.rfcontext.select(verts_selected - verts_inside, only=True)
        else:
            self.rfcontext.select(verts_inside, only=not box.mods['shift'])
