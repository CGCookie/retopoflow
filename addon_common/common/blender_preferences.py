'''
Copyright (C) 2020 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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


def mouse_doubleclick():
    # time/delay (in seconds) for a double click
    return bpy.context.preferences.inputs.mouse_double_click_time / 1000

def mouse_drag():
    # number of pixels to drag before tweak/drag event is triggered
    return bpy.context.preferences.inputs.drag_threshold_mouse

def mouse_move():
    # number of pixels to move before the cursor is considered to have moved
    # (used for cycling selected items on successive clicks)
    return bpy.context.preferences.inputs.move_threshold

def mouse_select():
    # returns 'LEFT' if LMB is used for selection or 'RIGHT' if RMB is used for selection
    try:
        return bpy.context.window_manager.keyconfigs.active.preferences.select_mouse
    except:
        pass
    try:
        m = {'LEFTMOUSE': 'LEFT', 'RIGHTMOUSE': 'RIGHT'}
        return m[bpy.context.window_manager.keyconfigs.active.keymaps['3D View'].keymap_items['view3d.select'].type]
    except Exception as e:
        if not hasattr(mouse_select, 'reported'):
            print('mouse_select: Exception caught')
            print(e)
            mouse_select.reported = True


