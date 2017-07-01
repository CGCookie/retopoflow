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
from mathutils import Matrix, Vector
from ..common.maths import Vec, Point, Point2D, Direction

from .rfwidget_default import RFWidget_Default
from .rfwidget_brushfalloff import RFWidget_BrushFalloff


class RFWidget(RFWidget_Default, RFWidget_BrushFalloff):
    instance = None
    rfcontext = None
    
    @staticmethod
    def new(rfcontext):
        RFWidget.rfcontext = rfcontext
        if not RFWidget.instance:
            RFWidget.creating = True
            RFWidget.instance = RFWidget()
            del RFWidget.creating
        RFWidget.instance.reset()
        return RFWidget.instance
    
    def __init__(self):
        assert hasattr(RFWidget, 'creating'), 'Do not create new RFWidget directly!  Use RFWidget.new()'
        
        self.points = [(math.cos(d*math.pi/180.0),math.sin(d*math.pi/180.0)) for d in range(0,361,10)]
        self.ox = Direction((1,0,0))
        self.oy = Direction((0,1,0))
        self.oz = Direction((0,0,1))
        
        self.widgets = {
            'default': {
                'postview':     self.default_postview,
                'postpixel':    self.default_postpixel,
                'mouse_cursor': self.default_mouse_cursor,
                'modal_main':   self.default_modal_main,
                },
            'brush falloff': {
                'postview':     self.brushfalloff_postview,
                'postpixel':    self.brushfalloff_postpixel,
                'mouse_cursor': self.brushfalloff_mouse_cursor,
                'modal_main':   self.brushfalloff_modal_main,
                },
            }
        self.FSM = {
            'main':     lambda: self.modal_main(), # lambda'd func, because modal_main is set dynamically
            'size':     self.modal_size,
            'strength': self.modal_strength,
            'falloff':  self.modal_falloff,
        }
        
        self.view = 'brush falloff'
        self.radius = 50.0
        self.falloff = 1.5
        self.strength = 0.5
        
        self.color = (1,1,1)
        
        self.reset()
    
    def reset(self):
        self.mode = 'main'
        self.draw_mode = 'view'
        self.clear()
    
    def clear(self):
        ''' called when mouse is moved outside View3D '''
        self.hit = False
        self.p = None
        self.s = 0.0
        self.x = None
        self.y = None
        self.z = None
        self.rmat = None
    
    def set_widget(self, name, color=None):
        assert name in self.widgets
        widget = self.widgets[name]
        self.draw_postview = widget.get('postview', self.no_draw_postview)
        self.draw_postpixel = widget.get('postpixel', self.no_draw_postpixel)
        self.mouse_cursor = widget.get('mouse_cursor', self.no_mouse_cursor)
        self.modal_main = widget.get('modal_main', self.no_modal_main)
        if color: self.color = color
        
    def update(self):
        p,n = self.rfcontext.hit_pos,self.rfcontext.hit_norm
        if p is None or n is None:
            self.clear()
            return
        xy = self.rfcontext.actions.mouse
        rmat = Matrix.Rotation(self.oz.angle(n), 4, self.oz.cross(n))
        self.p = p
        self.s = self.rfcontext.size2D_to_size(1.0, xy, self.rfcontext.Point_to_depth(p))
        self.x = Vec(rmat * self.ox)
        self.y = Vec(rmat * self.oy)
        self.z = Vec(rmat * self.oz)
        self.rmat = rmat
        self.hit = True
    
    def modal(self):
        nmode = self.FSM[self.mode]()
        if nmode: self.mode = nmode
        return self.mode == 'main'
    
    # DEFAULT, NONE, WAIT, CROSSHAIR, MOVE_X, MOVE_Y, KNIFE, TEXT, PAINT_BRUSH, HAND, SCROLL_X, SCROLL_Y, SCROLL_XY, EYEDROPPER
    def no_mouse_cursor(self): return 'DEFAULT'
    def no_draw_postview(self): pass
    def no_draw_postpixel(self): pass
    def no_modal_main(self): pass
    
    
    def get_scaled_radius(self):
        return self.s * self.radius
    
    def get_strength_dist(self, dist:float):
        return (1.0 - math.pow(dist / self.get_scaled_radius(), self.falloff)) * self.strength
    
    def get_strength_Point(self, point:Point):
        if not self.p: return 0.0
        return self.get_strength_dist((point - self.p).length)
    
    
    def modal_size(self):
        actions = self.rfcontext.actions
        w,h = actions.size
        center = Point2D((w/2, h/2))
        
        if self.draw_mode == 'view':
            # first time
            self.mousepre = Point2D(actions.mouse)
            actions.warp_mouse(Point2D((w/2 + self.radius, h/2)))
            self.draw_mode = 'pixel'
            self.radiuspre = self.radius
            return ''
        
        if actions.pressed({'cancel','confirm'}, unpress=False):
            if actions.pressed('cancel'): self.radius = self.radiuspre
            actions.unpress()
            self.draw_mode = 'view'
            actions.warp_mouse(self.mousepre)
            return 'main'
        
        self.radius = (center - actions.mouse).length
        return ''
    
    def modal_falloff(self):
        actions = self.rfcontext.actions
        w,h = actions.size
        center = Point2D((w/2, h/2))
        
        if self.draw_mode == 'view':
            # first time
            self.mousepre = Point2D(actions.mouse)
            actions.warp_mouse(Point2D((w/2 + self.radius * math.pow(0.5, 1.0 / self.falloff), h/2)))
            self.draw_mode = 'pixel'
            self.falloffpre = self.falloff
            return ''
        
        if actions.pressed('cancel'):
            self.falloff = self.falloffpre
            self.draw_mode = 'view'
            actions.warp_mouse(self.mousepre)
            return 'main'
        
        if actions.pressed('confirm'):
            self.draw_mode = 'view'
            actions.warp_mouse(self.mousepre)
            return 'main'
        
        dist = (center - actions.mouse).length
        ratio = max(0.0001, min(0.9999, dist / self.radius))
        
        self.falloff = math.log(0.5) / math.log(ratio)
        return ''
    
    def modal_strength(self):
        actions = self.rfcontext.actions
        w,h = actions.size
        center = Point2D((w/2, h/2))
        
        if self.draw_mode == 'view':
            # first time
            self.mousepre = Point2D(actions.mouse)
            actions.warp_mouse(Point2D((w/2 + self.radius * self.strength, h/2)))
            self.draw_mode = 'pixel'
            self.strengthpre = self.strength
            return ''
        
        if actions.pressed('cancel'):
            self.strength = self.strengthpre
            self.draw_mode = 'view'
            actions.warp_mouse(self.mousepre)
            return 'main'
        
        if actions.pressed('confirm'):
            self.draw_mode = 'view'
            actions.warp_mouse(self.mousepre)
            return 'main'
        
        dist = (center - actions.mouse).length
        ratio = max(0.0001, min(1.0, dist / self.radius))
        
        self.strength = ratio
        return ''
        


