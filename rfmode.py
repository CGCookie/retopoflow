'''
Copyright (C) 2015 Taylor University, CG Cookie

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

from .common.rfcontext import RFContext
from .rfmode_ui        import RFMode_UI
from .rfmode_framework import RFMode_Framework
from .rfmode_utils     import RFMode_Utils

class RFMode(Operator, RFMode_Framework, RFMode_UI):
    def __init__(self):
        self.init_framework()
        self.init_contexts()
        self.init_tools()
        self.init_utils()
    
    def init_contexts(self):
        self.rfcontexts = [RFContext(ctxname) for ctxname in RFContext.get_text_names()]        # all contexts
        self.rfcontext = None       # current context
    
    def create_new_context(self, src_objects):
        self.rfcontexts += RFContext.create(src_objects)
    
    def init_tools(self):
        self.tool = None
        self.tools = {}


