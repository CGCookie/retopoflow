'''
Copyright (C) 2019 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import os

import bpy
import bmesh

from ..addon_common.common import drawing
from ..addon_common.cookiecutter.cookiecutter import CookieCutter
from ..addon_common.common import ui

class VIEW3D_OT_RetopoFlow(CookieCutter):
    """Tooltip"""
    bl_idname = "cgcookie.retopoflow"
    bl_label = "RetopoFlow"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    default_keymap = {
        'commit': {'RET',},
        'cancel': {'ESC',},
    }

    @classmethod
    def can_start(cls, context):
        # check that the context is correct
        if not context.region or context.region.type != 'WINDOW': return False
        if not context.space_data or context.space_data.type != 'VIEW_3D': return False
        # check we are in mesh editmode
        if context.mode != 'EDIT_MESH': return False
        # make sure we are editing a mesh object
        ob = context.active_object
        if not ob or ob.type != 'MESH': return False
        # all seems good!
        return True

    def start(self):
        self.target = bpy.context.active_object
        self.sources = [o for o in bpy.data.objects if o != self.target and o.type == "MESH" and o.visible_get()]
        print('sources: %s' % ', '.join(o.name for o in self.sources))
        print('target: %s' % self.target.name)
        self.manipulator_hide()
        self.panels_hide()
        self.overlays_hide()
        self.region_darken()
        self.header_text_set('RetopoFlow')
        self.target.hide_viewport = True

        path = os.path.join(os.path.dirname(__file__), '..', 'config', 'ui.css')
        try:
            self.stylesheet = ui.UI_Styling.from_file(path)
        except AssertionError as e:
            # TODO: show proper dialog to user here!!
            print('caught exception!')
            print(e)
            self.stylesheet = None

        self.ui_elem = ui.UI_Button(stylesheet=self.stylesheet)

        #win_tools = self.wm.create_window('RetopoFlow', {'pos':7, 'movable':True, 'bgcolor':(0.5,0.5,0.5,0.9)})

    def end(self):
        self.target.hide_viewport = False

    def update(self):
        mx,my = self.actions.mouse if self.actions.mouse else (0,0)
        n = 'button'
        if 500 <= mx <= 500+200 and 420-300 <= my <= 420:
            self.ui_elem.add_pseudoclass('hover')
            if self.actions.using('LEFTMOUSE'):
                self.ui_elem.add_pseudoclass('active')
            else:
                self.ui_elem.del_pseudoclass('active')
        else:
            self.ui_elem.clear_pseudoclass()

    @CookieCutter.Draw('post2d')
    def draw_stuff(self):
        # will be done by ui system
        self.ui_elem._ui_draw.update()
        self.ui_elem.recalculate()
        self.ui_elem.position(500, 420, 200, 200)
        self.ui_elem.draw()
        #self.ui_elem._ui_draw.draw(500, 420, 200, 300, style)
        #style = ui.styling.get_style([n])
        #ui.ui_draw.draw()

    @CookieCutter.FSM_State('main')
    def modal_main(self):
        self.cursor_modal_set('CROSSHAIR')

        if self.actions.pressed('commit'):
            self.done()
            return

        if self.actions.pressed('cancel'):
            self.done(cancel=True)
            return



