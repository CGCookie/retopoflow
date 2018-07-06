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

from .rfcontext import RFContext
from .rftool import RFTool
from .rf_recover import RFRecover

from ..common.decorators import stats_report, stats_wrapper, blender_version_wrapper
from ..common.ui import UI_WindowManager

class CGCookie_UI(Operator):
    #bl_idname = "wm.open_quickstart"
    #bl_label = "Quick Start Guide"
    
    @classmethod
    def poll(cls, context): return True
    
    def ui_start(self):
        ui = UI_WindowManager()
        def draw_preview(): return self.draw_preview()
        def draw_postview(): return self.draw_postview()
        def draw_postpixel(): return self.draw_postpixel()
        self.__handle_preview = self.__space.draw_handler_add(draw_preview, tuple(), 'WINDOW', 'PRE_VIEW')
        self.__handle_postview = self.__space.draw_handler_add(draw_postview, tuple(), 'WINDOW', 'POST_VIEW')
        self.__handle_postpixel = self.__space.draw_handler_add(draw_postpixel, tuple(), 'WINDOW', 'POST_PIXEL')
        
    def ui_end(self):
        self.__space.draw_handler_remove(self.__handle_preview, 'WINDOW')
        self.__space.draw_handler_remove(self.__handle_postview, 'WINDOW')
        self.__space.draw_handler_remove(self.__handle_postpixel, 'WINDOW')
    
    def draw_preview(self):
        pass
    def draw_postview(self):
        pass
    def draw_postpixel(self):
        pass
    
    def invoke(self, context, event):
        self.__space = context.space_data
        self.ui_start()
        return {'RUNNING_MODAL'}
    
    def modal(self, context, event):
        return {'RUNNING_MODAL'}
    
class TMP:
    _cnt = 0
    @staticmethod
    def draw_postpixel(win, cnt, unreg):
        if win != bpy.context.window: return
        try:
            if win.height <= 0 or win.width <= 0:
                unreg()
                return
            
            r,g,b = [(0,0,0),(1,0,0),(0,1,0),(0,0,1),(1,1,0),(1,0,1),(0,1,1),(1,1,1)][cnt]
            
            bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)
            bgl.glMatrixMode(bgl.GL_PROJECTION)
            bgl.glPushMatrix()
            bgl.glLoadIdentity()
            bgl.glColor4f(r,g,b,0.95)    # TODO: use window background color??
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glDisable(bgl.GL_DEPTH_TEST)
            bgl.glBegin(bgl.GL_QUADS)   # TODO: not use immediate mode
            bgl.glVertex2f(-1, -1)
            bgl.glVertex2f( 1, -1)
            bgl.glVertex2f( 1,  1)
            bgl.glVertex2f(-1,  1)
            bgl.glEnd()
            bgl.glPopMatrix()
            bgl.glPopAttrib()
            
            print('postpixel %d %f ' % (cnt, random.random()))
            print('win: %s %d %d %d %d' % (str(win), win.x, win.y , win.width, win.height))
        except Exception as e:
            print('Exception: %s' % str(e))
            unreg()

    def openTextFile(self):

        # play it safe!
        if options['quickstart_filename'] not in bpy.data.texts:
            # create a log file for error writing
            bpy.data.texts.new(options['quickstart_filename'])
        
        # simple processing of help_quickstart
        t = help_quickstart
        t = re.sub(r'^\n*', r'', t)         # remove leading newlines
        t = re.sub(r'\n*$', r'', t)         # remove trailing newlines
        t = re.sub(r'\n\n+', r'\n\n', t)    # make uniform paragraph separations
        ps = t.split('\n\n')
        l = []
        for p in ps:
            if p.startswith('- '):
                l += [p]
                continue
            lines = p.split('\n')
            if len(lines) == 2 and (lines[1].startswith('---') or lines[1].startswith('===')):
                l += [p]
                continue
            l += ['  '.join(lines)]
        t = '\n\n'.join(l)
        
        # restore data, just in case
        txt = bpy.data.texts[options['quickstart_filename']]
        txt.from_string(t)
        txt.current_line_index = 0

        # duplicate the current area then change it to a text edito
        area_dupli = bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
        win = bpy.context.window_manager.windows[-1]
        area = win.screen.areas[-1]
        area.type = 'TEXT_EDITOR'

        # load the text file into the correct space
        for space in area.spaces:
            if space.type == 'TEXT_EDITOR':
                space.text = txt
                space.show_word_wrap = True
                space.top = 0
                if area.regions[0].height != 1:
                    bpy.ops.screen.header({'window':win, 'region':area.regions[2], 'area':area})
                cnt = OpenQuickStart._cnt
                handle = None
                def unreg():
                    nonlocal handle, cnt
                    print('UNREGISTERING %d!' % cnt)
                    space.draw_handler_remove(handle, "WINDOW")
                    del handle
                # ('WINDOW', 'HEADER', 'CHANNELS', 'TEMPORARY', 'UI', 'TOOLS', 'TOOL_PROPS', 'PREVIEW')
                # POST_PIXEL, POST_VIEW, PRE_VIEW
                handle = space.draw_handler_add(self.draw_postpixel, (win, cnt, unreg), 'WINDOW', 'POST_PIXEL')
                OpenQuickStart._cnt += 1

