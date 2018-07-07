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

import sys
import math
import os
import re
import time

import bpy
import bgl
from mathutils import Matrix, Vector
from ..common.maths import BBox
from bpy.types import Operator, SpaceView3D, bpy_struct
from bpy.app.handlers import persistent, load_post

from ..lib import common_utilities
from ..lib.common_utilities import print_exception, print_exception2, showErrorMessage
from ..lib.classes.logging.logger import Logger
from ..lib.common_utilities import dprint
from ..lib.classes.profiler.profiler import profiler

from ..common.ui import set_cursor

from ..common.decorators import stats_report, stats_wrapper, blender_version_wrapper
from ..common.ui import UI_WindowManager


class CookieCutter_UI:
    def ui_init(self, context):
        self.__area = context.area
        self.__space = context.space_data
        self.wm = UI_WindowManager()
    
    def ui_start(self):
        self.__handle_preview = self.__space.draw_handler_add(self.draw_preview_callback, tuple(), 'WINDOW', 'PRE_VIEW')
        self.__handle_postview = self.__space.draw_handler_add(self.draw_postview_callback, tuple(), 'WINDOW', 'POST_VIEW')
        self.__handle_postpixel = self.__space.draw_handler_add(self.draw_postpixel_callback, tuple(), 'WINDOW', 'POST_PIXEL')
        self.__area.tag_redraw()
    
    def ui_modal(self, context, event):
        self.__area.tag_redraw()
        ret = self.wm.modal(context, event)
        if ret and 'hover' in ret:
            #self.rfwidget.clear()
            #if self.exit: return {'confirm'}
            return True
        if self.wm.has_focus(): return True
        return False
    
    def ui_end(self):
        self.__space.draw_handler_remove(self.__handle_preview, 'WINDOW')
        self.__space.draw_handler_remove(self.__handle_postview, 'WINDOW')
        self.__space.draw_handler_remove(self.__handle_postpixel, 'WINDOW')
        self.__area.tag_redraw()
    
    
    def draw_preview_callback(self):
        self.draw_preview()
    def draw_postview_callback(self):
        self.draw_postview()
    def draw_postpixel_callback(self):
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_POINT_SMOOTH)
        self.draw_postpixel()
        self.wm.draw_postpixel()
    
