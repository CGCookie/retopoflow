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

import math

import bpy
import bgl

from ..common.ui import UI_WindowManager


class CookieCutter_UI:
    class Draw:
        def __init__(self, mode):
            assert mode in {'pre3d','post3d','post2d'}
            self.mode = mode
        def __call__(self, fn):
            self.fn = fn
            self.fnname = fn.__name__
            def run(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    print('Caught exception in drawing "%s", calling "%s"' % (self.mode, self.fnname))
                    print(e)
                    return None
            run.fnname = self.fnname
            run.drawmode = self.mode
            return run
    
    def ui_init(self):
        self._area = self.context.area
        self._space = self.context.space_data
        self.wm = UI_WindowManager()
        fns = {'pre3d':[], 'post3d':[], 'post2d':[]}
        for m,fn in self.find_fns('drawmode'): fns[m].append(fn)
        def draw(fns):
            for fn in fns: fn(self)
        self._draw_pre3d = lambda:draw(fns['pre3d'])
        self._draw_post3d = lambda:draw(fns['post3d'])
        self._draw_post2d = lambda:draw(fns['post2d'])
        self._area.tag_redraw()
    
    def ui_start(self):
        def preview():
            self._draw_pre3d()
        def postview():
            self._draw_post3d()
        def postpixel():
            bgl.glEnable(bgl.GL_MULTISAMPLE)
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glEnable(bgl.GL_POINT_SMOOTH)
            
            self._draw_post2d()
            
            try:
                self.wm.draw_postpixel()
            except Exception as e:
                print('Caught exception while trying to draw window UI')
                print(e)
        
        self._handle_preview = self._space.draw_handler_add(preview, tuple(), 'WINDOW', 'PRE_VIEW')
        self._handle_postview = self._space.draw_handler_add(postview, tuple(), 'WINDOW', 'POST_VIEW')
        self._handle_postpixel = self._space.draw_handler_add(postpixel, tuple(), 'WINDOW', 'POST_PIXEL')
        self._area.tag_redraw()
    
    def ui_update(self):
        self._area.tag_redraw()
        ret = self.wm.modal(self.context, self.event)
        if self.wm.has_focus(): return True
        if ret and 'hover' in ret: return True
        return False
    
    def ui_end(self):
        self._space.draw_handler_remove(self._handle_preview, 'WINDOW')
        self._space.draw_handler_remove(self._handle_postview, 'WINDOW')
        self._space.draw_handler_remove(self._handle_postpixel, 'WINDOW')
        self._area.tag_redraw()
    
    ####################################################################
    # common Blender UI functions
    
    def header_text_set(self, s=None):
        self.context.area.header_text_set(s)
    
    def cursor_modal_set(self, v):
        self.context.window.cursor_modal_set(v)
    
    def cursor_modal_restore(self):
        self.context.window.cursor_modal_restore()
