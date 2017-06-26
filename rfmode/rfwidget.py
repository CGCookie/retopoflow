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
from ..common.maths import Vec, Point, Point2D

from ..common.metaclasses import SingletonRegisterClass



class RFWidget(metaclass=SingletonRegisterClass):
    @staticmethod
    def init_widgets(rfcontext):
        #class_methods = ['init', 'mouse_cursor']
        RFWidget.rfcontext = rfcontext
        for cwidget in RFWidget:
            widget = cwidget()
    
    #def __init__(self):
    #    assert False, "do not instantiate RFWidget"
    
    def update(self):
        ''' called when  '''
        pass
    
    def clear(self):
        ''' called when mouse is moved outside View3D '''
        pass
    
    def mouse_cursor(self):
        # DEFAULT, NONE, WAIT, CROSSHAIR, MOVE_X, MOVE_Y, KNIFE, TEXT, PAINT_BRUSH, HAND, SCROLL_X, SCROLL_Y, SCROLL_XY, EYEDROPPER
        return 'DEFAULT'
    
    def draw_postview(self):
        pass
    
    def draw_postpixel(self):
        pass



class RFWidget_Default(RFWidget):
    def mouse_cursor(self):
        return 'CROSSHAIR'

