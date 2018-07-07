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
        print('ui_init')
        self.__area = context.area
        self.__space = context.space_data
        self.wm = UI_WindowManager()
    
    def ui_start(self):
        print('ui_start')
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
        print('ui_end')
        self.__space.draw_handler_remove(self.__handle_preview, 'WINDOW')
        self.__space.draw_handler_remove(self.__handle_postview, 'WINDOW')
        self.__space.draw_handler_remove(self.__handle_postpixel, 'WINDOW')
    
    
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
            
            bgl.glEnable(bgl.GL_MULTISAMPLE)
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glEnable(bgl.GL_POINT_SMOOTH)
            bgl.glDisable(bgl.GL_DEPTH_TEST)

            bgl.glMatrixMode(bgl.GL_MODELVIEW)
            bgl.glPushMatrix()
            bgl.glLoadIdentity()
            bgl.glMatrixMode(bgl.GL_PROJECTION)
            bgl.glPushMatrix()
            bgl.glLoadIdentity()
            
            bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)
            bgl.glMatrixMode(bgl.GL_PROJECTION)
            bgl.glPushMatrix()
            bgl.glLoadIdentity()
            bgl.glColor4f(r,g,b,0.5)    # TODO: use window background color??
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

