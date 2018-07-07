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

import bpy
import bgl

from .operator import CookieCutter

from ..common.maths import Point2D
from ..common import ui

class CookieCutter_Test(CookieCutter):
    bl_idname = "wm.cookiecutter_test"
    bl_label = "CookieCutter Test"
    bl_category    = "CookieCutter"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    def start(self):
        opts = {
            'pos': 9,
            'movable': True,
            'bgcolor': (0.2, 0.2, 0.2, 0.8),
            #'event handler': event_handler,
            'padding': 0,
            }
        win = self.wm.create_window('test',opts)
        bigcontainer = win.add(ui.UI_Container(margin=0))
        bigcontainer.add(ui.UI_Label('foo bar'))
        #self.window_manager.set_focus(win, darken=False, close_on_leave=True)
    
    def draw_preview(self):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)
        
        bgl.glEnable(bgl.GL_BLEND)
        
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        
        bgl.glColor4f(0,0,0,0.5)    # TODO: use window background color??
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDisable(bgl.GL_DEPTH_TEST)
        bgl.glBegin(bgl.GL_QUADS)   # TODO: not use immediate mode
        bgl.glVertex2f(-1, -1)
        bgl.glVertex2f( 1, -1)
        bgl.glVertex2f( 1,  1)
        bgl.glVertex2f(-1,  1)
        bgl.glEnd()
        
        bgl.glPopMatrix()
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPopMatrix()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPopAttrib()
    
    def draw_postview(self):
        pass
    
    def draw_postpixel(self):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)
        
        bgl.glEnable(bgl.GL_BLEND)
        
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        
        bgl.glColor4f(1,0,0,0.5)    # TODO: use window background color??
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDisable(bgl.GL_DEPTH_TEST)
        bgl.glBegin(bgl.GL_QUADS)   # TODO: not use immediate mode
        bgl.glVertex2f(-1, -1)
        bgl.glVertex2f( 1, -1)
        bgl.glVertex2f( 1,  1)
        bgl.glVertex2f(-1,  1)
        bgl.glEnd()
        
        bgl.glPopMatrix()
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPopMatrix()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPopAttrib()
    
