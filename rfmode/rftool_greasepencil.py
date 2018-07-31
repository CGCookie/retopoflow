'''
Copyright (C) 2018 CG Cookie
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

import bgl
import bpy
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_point_tri_2d

from .rftool import RFTool

from ..common.debug import dprint
from ..common.profiler import profiler
from ..common.logger import Logger
from ..common.maths import (
    Point, Vec, Direction,
    Point2D, Vec2D,
    Accel2D,
    clamp, mid,
)
from ..common.bezier import CubicBezierSpline, CubicBezier
from ..common.shaders import circleShader, edgeShortenShader, arrowShader
from ..common.utils import iter_pairs, iter_running_sum, min_index, max_index
from ..common.ui import (
    UI_Image, UI_Number, UI_BoolValue,
    UI_Button, UI_Label,
    UI_Container, UI_EqualContainer
    )
from ..keymaps import default_rf_keymaps
from ..options import options, themes
from ..help import help_greasepencil


@RFTool.is_experimental
@RFTool.action_call('grease pencil tool')
class RFTool_Stretch(RFTool):
    def init(self):
        pass

    def name(self): return "Grease Pencil"
    def icon(self): return "rf_greasepencil_icon"
    def description(self): return 'Mark up the source with grease pencil.'
    def helptext(self): return help_greasepencil
    def get_label(self): return 'Grease Pencil (%s)' % ','.join(default_rf_keymaps['grease pencil tool'])
    def get_tooltip(self): return 'Grease Pencil (%s)' % ','.join(default_rf_keymaps['grease pencil tool'])

    def start(self):
        self.rfwidget.set_widget('brush stroke', color=(0.5, 0.5, 0.5))
        self.rfwidget.set_stroke_callback(self.stroke)
        self.stroke3D = []
        self.moves3D = []
        self.process = None

    def get_ui_icon(self):
        self.ui_icon = UI_Image('greasepencil_32.png')
        self.ui_icon.set_size(16, 16)
        return self.ui_icon

    def get_ui_options(self):
        pass

    @profiler.profile
    def modal_main(self):
        self.rfwidget.set_widget('brush stroke')
        if self.rfcontext.actions.pressed('grease clear'):
            self.rfcontext.undo_push('grease clear')
            self.rfcontext.grease_marks = []

    @RFTool.dirty_when_done
    def stroke(self):
        # called when artist finishes a stroke

        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        raycast_sources_Point2D = self.rfcontext.raycast_sources_Point2D
        accel_nearest2D_vert = self.rfcontext.accel_nearest2D_vert

        self.rfcontext.undo_push('grease mark')

        def add_mark(mark):
            if len(mark) < 2: return
            self.rfcontext.grease_marks.append({
                'color': (0.1, 0.1, 0.1, 0.5),
                'thickness': self.rfwidget.get_scaled_size() * 0.5,
                'marks': marks,
            })

        def process_stroke_filter(stroke, min_distance=5.0, max_distance=10.0):
            ''' filter stroke to pts that are at least min_distance apart '''
            nstroke = stroke[:1]
            for p in stroke[1:]:
                v = p - nstroke[-1]
                l = v.length
                if l < min_distance: continue
                d = v / l
                while l > 0:
                    q = nstroke[-1] + d * min(l, max_distance)
                    nstroke.append(q)
                    l -= max_distance
            return nstroke

        marks = process_stroke_filter(self.rfwidget.stroke2D)
        marks = [raycast_sources_Point2D(s2d) for s2d in marks]
        marks = [(p,n) for (p,n,_,_) in marks]
        mark = []
        for (p,n) in marks:
            if not p or not n:
                add_mark(mark)
                mark = []
            else:
                mark.append((p,n))
        add_mark(mark)
