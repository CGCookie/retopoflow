'''
Copyright (C) 2017 Taylor University, CG Cookie

Created by Dr. Jon Denning and Spring 2015 COS 424 class

Some code copied from CG Cookie Retopoflow project
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


import math
import bgl
import random
from mathutils import Matrix, Vector
from ..common.maths import Vec, Vec2D, Point, Point2D, Direction
from ..common.ui import Drawing
from ..options import options

from .rfwidget_registry import RFWidget_Registry
from .rfwidget_default import RFWidget_Default
from .rfwidget_move import RFWidget_Move
from .rfwidget_brushfalloff import RFWidget_BrushFalloff
from .rfwidget_brushstroke import RFWidget_BrushStroke
from .rfwidget_line import RFWidget_Line
from .rfwidget_rotate import RFWidget_Rotate


class RFWidget(RFWidget_Registry, RFWidget_Default, RFWidget_BrushFalloff, RFWidget_BrushStroke, RFWidget_Move, RFWidget_Line, RFWidget_Rotate):
    instance = None
    rfcontext = None

    points = [(math.cos(d*math.pi/180.0),math.sin(d*math.pi/180.0)) for d in range(0,361,10)]
    ox = Direction((1,0,0))
    oy = Direction((0,1,0))
    oz = Direction((0,0,1))

    # brushfalloff properties
    radius = 50.0
    falloff = 1.5
    strength = 0.5

    # brushstroke properties
    size = 20.0
    tightness = 0.95
    stroke2D = []
    stroke2D_left = []
    stroke2D_right = []
    stroke_callback = None

    # line properties
    line2D = []
    line_callback = None

    scale = 0.0

    @staticmethod
    def new(rfcontext):
        RFWidget.rfcontext = rfcontext
        RFWidget.drawing = Drawing.get_instance()
        if not RFWidget.instance:
            RFWidget.creating = True
            RFWidget.instance = RFWidget()
            del RFWidget.creating
        RFWidget.instance.reset()
        return RFWidget.instance

    def __init__(self):
        assert hasattr(RFWidget, 'creating'), 'Do not create new RFWidget directly!  Use RFWidget.new()'
        self.registry_init()

        self.widgets = {
            'default': {
                'postview':     self.default_postview,
                'postpixel':    self.default_postpixel,
                'mouse_cursor': self.default_mouse_cursor,
                'modal_main':   self.default_modal_main,
                },
            'move': {
                'postview':     self.move_postview,
                'postpixel':    self.move_postpixel,
                'mouse_cursor': self.move_mouse_cursor,
                'modal_main':   self.move_modal_main,
                },
            'brush falloff': {
                'postview':     self.brushfalloff_postview,
                'postpixel':    self.brushfalloff_postpixel,
                'mouse_cursor': self.brushfalloff_mouse_cursor,
                'modal_main':   self.brushfalloff_modal_main,
                },
            'brush stroke': {
                'postview':     self.brushstroke_postview,
                'postpixel':    self.brushstroke_postpixel,
                'mouse_cursor': self.brushstroke_mouse_cursor,
                'modal_main':   self.brushstroke_modal_main,
                },
            'line': {
                'postview':     self.line_postview,
                'postpixel':    self.line_postpixel,
                'mouse_cursor': self.line_mouse_cursor,
                'modal_main':   self.line_modal_main,
                },
            }
        self.FSM = {
            'main':     lambda: self.modal_main(), # lambda'd func, because modal_main is set dynamically
            'stroke':   self.modal_stroke,
            'line':     self.modal_line,
            'change':   self.modal_change,
        }

        self.view = 'default'
        self.color = (1,1,1)

        self.change_var = None
        self.change_fn = None

        self.reset()

    def reset(self):
        self.mode = 'main'
        self.draw_mode = 'view'
        self.clear()

    def clear(self):
        ''' called when mouse is moved outside View3D '''
        self.hit = False
        self.hit_p = None
        self.hit_x = None
        self.hit_y = None
        self.hit_z = None
        self.hit_rmat = None

    def set_widget(self, name, color=None):
        assert name in self.widgets
        widget = self.widgets[name]
        self.draw_postview = widget.get('postview', self.no_draw_postview)
        self.draw_postpixel = widget.get('postpixel', self.no_draw_postpixel)
        self.mouse_cursor = widget.get('mouse_cursor', self.no_mouse_cursor)
        self.modal_main = widget.get('modal_main', self.no_modal_main)
        if color: self.color = color

    def set_stroke_callback(self, fn):
        self.stroke_callback = fn

    def set_line_callback(self, fn):
        self.line_callback = fn

    def update(self):
        p,n = self.rfcontext.actions.hit_pos,self.rfcontext.actions.hit_norm
        if p is None or n is None:
            self.clear()
            return
        depth = self.rfcontext.Point_to_depth(p)
        if depth is None:
            self.clear()
            return
        xy = self.rfcontext.actions.mouse
        rmat = Matrix.Rotation(self.oz.angle(n), 4, self.oz.cross(n))
        self.hit = True
        self.scale = self.rfcontext.size2D_to_size(1.0, xy, depth)
        self.hit_p = p
        self.hit_x = Vec(rmat * self.ox)
        self.hit_y = Vec(rmat * self.oy)
        self.hit_z = Vec(rmat * self.oz)
        self.hit_rmat = rmat

    def modal(self):
        try:
            nmode = self.FSM[self.mode]()
            if nmode: self.mode = nmode
            return self.mode == 'main'
        except Exception as e:
            self.mode = 'main'
            raise e

    # DEFAULT, NONE, WAIT, CROSSHAIR, MOVE_X, MOVE_Y, KNIFE, TEXT, PAINT_BRUSH, HAND, SCROLL_X, SCROLL_Y, SCROLL_XY, EYEDROPPER
    def no_mouse_cursor(self): return 'DEFAULT'
    def no_draw_postview(self): pass
    def no_draw_postpixel(self): pass
    def no_modal_main(self): pass


    def get_scaled_radius(self):
        return self.scale * self.radius

    def get_scaled_size(self):
        return self.scale * self.size

    def get_strength_dist(self, dist:float):
        return max(0.0, min(1.0, (1.0 - math.pow(dist / self.get_scaled_radius(), self.falloff)))) * self.strength

    def get_strength_Point(self, point:Point):
        if not self.hit_p: return 0.0
        return self.get_strength_dist((point - self.hit_p).length)


    def setup_change(self, var_to_dist, dist_to_var):
        self.change_dist_to_var = dist_to_var

        if var_to_dist:
            dist = var_to_dist()
            actions = self.rfcontext.actions
            self.change_pre = dist
            self.change_center = actions.mouse - Vec2D((dist, 0))
            self.draw_mode = 'pixel'
        else:
            self.change_pre = None
            self.change_center = None
            self.draw_mode = 'view'

    def modal_change(self):
        dist_to_var = self.change_dist_to_var
        assert dist_to_var

        actions = self.rfcontext.actions

        if actions.pressed({'cancel','confirm'}, unpress=False, ignoremods=True):
            if actions.pressed('cancel', ignoremods=True):
                dist_to_var(self.change_pre)
            actions.unpress()
            self.setup_change(None, None)
            return 'main'

        dist = (self.change_center - actions.mouse).length
        dist_to_var(dist)

