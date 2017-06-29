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

import sys
import math
import os
import time

import bpy
import bgl
from bpy.types import Operator
from bpy.types import SpaceView3D
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix, Euler

from ..lib.classes.textbox.textbox import TextBox
from .. import key_maps
from ..lib import common_utilities
from ..lib.common_utilities import print_exception, showErrorMessage
from ..common.metaclasses import SingletonRegisterClass
from .rfwidget import RFWidget_Default


class RFTool(metaclass=SingletonRegisterClass):
    action_tool = []
    
    @staticmethod
    def init_tools(rfcontext):
        RFTool.rfcontext = rfcontext
        toolset = { rftool:rftool() for rftool in RFTool }  # create instances of each tool
    
    @staticmethod
    def dirty_when_done(fn):
        def wrapper(*args, **kwargs):
            ret = fn(*args, **kwargs)
            RFTool.rfcontext.dirty()
            return ret
        return wrapper
    
    @staticmethod
    def action_call(action):
        def decorator(tool):
            RFTool.action_tool.append((action, tool))
            return tool
        return decorator
    
    ''' a base class for all RetopoFlow Tools '''
    def __init__(self):
        self.FSM = {}
        self.init()
        self.FSM['main'] = self.modal_main
        self.mode = 'main'
    
    def modal(self):
        nmode = self.FSM[self.mode]()
        if nmode: self.mode = nmode
    
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self): pass
    
    ''' Called the tool is being switched into. Returns initial state '''
    def start(self): return None
    
    ''' Returns type of cursor to display '''
    def rfwidget(self): return RFWidget_Default()
    
    def modal_main(self): pass
    
    def draw_postview(self): pass
    def draw_postpixel(self): pass


