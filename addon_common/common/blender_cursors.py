'''
Copyright (C) 2023 CG Cookie
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

from .globals import Globals

class Cursors:
    # https://docs.blender.org/api/current/bpy.types.Window.html#bpy.types.Window.cursor_set
    _blender_cursors = [
        # https://docs.blender.org/api/current/bpy_types_enum_items/window_cursor_items.html#rna-enum-window-cursor-items
        'DEFAULT',
        'NONE',
        'WAIT',
        'CROSSHAIR',
        'MOVE_X',
        'MOVE_Y',
        'KNIFE',
        'TEXT',
        'PAINT_BRUSH',
        'PAINT_CROSS',
        'DOT',
        'ERASER',
        'HAND',
        'SCROLL_X',
        'SCROLL_Y',
        'SCROLL_XY',
        'EYEDROPPER',
        'PICK_AREA',
        'STOP',
        'COPY',
        'CROSS',
        'MUTE',
        'ZOOM_IN',
        'ZOOM_OUT',
    ]
    _cursors = { k: k for k in _blender_cursors } | { k.lower(): k for k in _blender_cursors }

    @staticmethod
    def __getattr__(cursor):
        assert cursor in Cursors._cursors
        return Cursors._cursors.get(cursor, 'DEFAULT')

    @staticmethod
    def set(cursor):
        # print('Cursors.set', cursor)
        cursor = Cursors._cursors.get(cursor, 'DEFAULT')
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                win.cursor_modal_set(cursor)

    @staticmethod
    def restore():
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                win.cursor_modal_restore()

    @property
    @staticmethod
    def cursor(): return 'DEFAULT'   # TODO: how to get??
    @cursor.setter
    @staticmethod
    def cursor(cursor): Cursors.set(cursor)

    @staticmethod
    def warp(x, y): bpy.context.window.cursor_warp(x, y)

Globals.set(Cursors())
