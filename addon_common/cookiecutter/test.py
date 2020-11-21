'''
Copyright (C) 2020 CG Cookie

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

from .cookiecutter import CookieCutter

from ..common.maths import Point2D
from ..common import ui
from ..common.drawing import Drawing

class CookieCutter_Test(CookieCutter):
    bl_idname = "view3d.cookiecutter_test"
    bl_label = "CookieCutter Test (Example)"

    default_keymap = {
        'commit': 'RET',
        'cancel': 'ESC',
        'grab': 'G',
    }

    def start(self):
        opts = {
            'pos': 9,
            'movable': True,
            'bgcolor': (0.2, 0.2, 0.2, 0.8),
            'padding': 0,
            }
        win = self.wm.create_window('test', opts)
        self.lbl = win.add(ui.UI_Label('main'))
        self.ui_action = win.add(ui.UI_Label('nothing'))
        exitbuttons = win.add(ui.UI_Container(margin=0,vertical=False))
        exitbuttons.add(ui.UI_Button('commit', self.done))
        exitbuttons.add(ui.UI_Button('cancel', lambda:self.done(cancel=True)))
        #self.window_manager.set_focus(win, darken=False, close_on_leave=True)

    def update(self):
        self.ui_action.set_label('Press: %s' % (','.join(self.actions.now_pressed.keys()),))

    @CookieCutter.FSM_State('main')
    def modal_main(self):
        Drawing.set_cursor('DEFAULT')

        if self.actions.pressed('grab'):
            self.lbl.set_label('grab!')
            return 'grab'

    @CookieCutter.FSM_State('grab')
    def modal_grab(self):
        Drawing.set_cursor('HAND')

        if self.actions.pressed('commit'):
            self.lbl.set_label('commit grab')
            return 'main'
        if self.actions.pressed('cancel'):
            self.lbl.set_label('cancel grab')
            return 'main'

    @CookieCutter.Draw('pre3d')
    def draw_preview(self):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()

        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDisable(bgl.GL_DEPTH_TEST)

        bgl.glBegin(bgl.GL_QUADS)   # TODO: not use immediate mode
        bgl.glColor4f(0,0,0.2,0.5)
        bgl.glVertex2f(-1, -1)
        bgl.glVertex2f( 1, -1)
        bgl.glColor4f(0,0,0.2,0)
        bgl.glVertex2f( 1,  1)
        bgl.glVertex2f(-1,  1)
        bgl.glEnd()

        bgl.glPopMatrix()
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPopMatrix()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPopAttrib()

    @CookieCutter.Draw('post3d')
    def draw_postview(self):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()

        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDisable(bgl.GL_DEPTH_TEST)

        bgl.glBegin(bgl.GL_QUADS)   # TODO: not use immediate mode
        bgl.glColor4f(0,0,0,0)
        bgl.glVertex2f(-1, -1)
        bgl.glVertex2f( 1, -1)
        bgl.glColor4f(0,0.2,0,0.5)
        bgl.glVertex2f( 1,  1)
        bgl.glVertex2f(-1,  1)
        bgl.glEnd()

        bgl.glPopMatrix()
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPopMatrix()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPopAttrib()

    @CookieCutter.Draw('post2d')
    def draw_postpixel(self):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)

        bgl.glEnable(bgl.GL_BLEND)

        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()

        bgl.glColor4f(1,0,0,0.2)    # TODO: use window background color??
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

