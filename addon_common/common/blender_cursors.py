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

from typing import Literal, get_args, cast

from .globals import Globals

# https://docs.blender.org/api/current/bpy.types.Window.html#bpy.types.Window.cursor_set
# https://docs.blender.org/api/4.2/bpy_types_enum_items/window_cursor_items.html#rna-enum-window-cursor-items
BLENDER_CURSORS_42 = Literal[
    "DEFAULT",
    "NONE",
    "WAIT",
    "CROSSHAIR",
    "MOVE_X",
    "MOVE_Y",
    "KNIFE",
    "TEXT",
    "PAINT_BRUSH",
    "PAINT_CROSS",
    "DOT",
    "ERASER",
    "HAND",
    "SCROLL_X",
    "SCROLL_Y",
    "SCROLL_XY",
    "EYEDROPPER",
    "PICK_AREA",
    "STOP",
    "COPY",
    "CROSS",
    "MUTE",
    "ZOOM_IN",
    "ZOOM_OUT",
]

# two new cursor items were added to Blender 4.3
# https://docs.blender.org/api/current/bpy_types_enum_items/window_cursor_items.html#rna-enum-window-cursor-items
BLENDER_CURSORS_43 = Literal[
    BLENDER_CURSORS_42,
    "HAND_POINT",
    "HAND_CLOSED",
]


class Cursors:
    @staticmethod
    def set(cursor : str):
        cursor = cursor.upper()

        if cursor in get_args(BLENDER_CURSORS_42):
            pass

        elif cursor in get_args(BLENDER_CURSORS_43) and bpy.app.version > (4, 3, 0):
            pass

        else:
            match cursor:
                case 'HAND_POINT':
                    cursor = 'HAND'
                case 'HAND_CLOSED':
                    cursor = 'HAND'
                case _:
                    cursor = 'DEFAULT'

        for wm in bpy.data.window_managers:
            for win in wm.windows:
                win.cursor_modal_set(cursor) # pyright: ignore[reportArgumentType]

    @staticmethod
    def restore():
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                win.cursor_modal_restore()

    @staticmethod
    def warp(x : int, y : int):
        bpy.context.window.cursor_warp(x, y)

Globals.set(Cursors())
