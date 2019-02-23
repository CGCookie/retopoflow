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

import bpy
import bmesh

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
        # check we are in mesh editmode
        ob = context.active_object
        return (ob and ob.type == 'MESH' and context.mode == 'EDIT_MESH')

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
        #win_tools = self.wm.create_window('RetopoFlow', {'pos':7, 'movable':True, 'bgcolor':(0.5,0.5,0.5,0.9)})

    def end(self):
        self.target.hide_viewport = False

    def update(self):
        pass

    @CookieCutter.FSM_State('main')
    def modal_main(self):
        self.cursor_modal_set('CROSSHAIR')

        if self.actions.pressed('commit'):
            self.done()
            return

        if self.actions.pressed('cancel'):
            self.done(cancel=True)
            return



