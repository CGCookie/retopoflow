'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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

from pathlib import Path
import os
from enum import Enum, auto

from bpy.utils import previews
import bpy
from bl_ui.space_toolsystem_common import ToolSelectPanelHelper

from ..rftool_base import RFTool_Base


# (icon_name -> icon_value) map
_icon_cache = {}
ICONS_DIRPATH = Path(__file__).parent.parent.parent / 'icons'

preview_collections = {}
_icon_preview_cache = {}


def get_path_to_blender_icon(icon: str) -> str:
    return (ICONS_DIRPATH / icon).as_posix()


def get_icon_value_from_icon_handle(icon_name: str) -> int:
    global _icon_cache
    if icon_name is not None:
        assert type(icon_name) is str
        icon_value = _icon_cache.get(icon_name)
        if icon_value is None:
            filepath = (ICONS_DIRPATH / f"{icon_name}.dat").as_posix()
            try:
                icon_value = bpy.app.icons.new_triangles_from_file(filepath)
            except Exception as ex:
                if not os.path.exists(filepath):
                    print("Missing icons:", filepath, ex)
                else:
                    print("Corrupt icon:", filepath, ex)
                # Use none as a fallback (avoids layout issues).
                if icon_name != "none":
                    icon_value = ToolSelectPanelHelper._icon_value_from_icon_handle("none")
                else:
                    icon_value = 0
            _icon_cache[icon_name] = icon_value
        return icon_value
    else:
        return 0

def get_rftool_icon_value(rftool: RFTool_Base) -> int:
    return get_icon_value_from_icon_handle(rftool.rf_idname.split('.')[-1].lower())

def draw_rftool_icon(rftool: RFTool_Base, layout: bpy.types.UILayout, scale: float = 1.0) -> None:
    layout.template_icon(icon_value=get_rftool_icon_value(rftool), scale=scale)


class Icon(Enum):
    ''' Utility class to load image icons on-demand. '''
    SEPARATOR = auto()
    SUPERHIVE = auto()
    LOOP = auto()

    @property
    def icon_id(self) -> int:
        # Load icon on-request rather than on-startup!
        return Icon.load(self.name)

    @staticmethod
    def load(icon_name: str) -> int:
        global preview_collections
        if icon_name in _icon_preview_cache:
            return _icon_preview_cache[icon_name]
        icon_path = ICONS_DIRPATH / f"{icon_name}.png"
        if not icon_path.is_file():
            icon_path = ICONS_DIRPATH / f"{icon_name}-icon.png"
        if not icon_path.is_file():
            # SEPARATOR and SUPERHIVE are all caps, but some file systems are case sensitive
            icon_path = ICONS_DIRPATH / f"{icon_name.lower()}-icon.png"
        if not icon_path.is_file():
            raise FileNotFoundError(f"Icon {icon_name} not found ({icon_path})")
        preview_collections["main"].load(icon_name, icon_path.as_posix(), 'IMAGE')
        _icon_preview_cache[icon_name] = preview_collections["main"][icon_name].icon_id
        return _icon_preview_cache[icon_name]

    def draw(self, layout: bpy.types.UILayout, left_space: float = 0.0, right_space: float = 0.0) -> None:
        if left_space > 0.0:
            layout.separator(factor=left_space)
        layout.label(text='', icon_value=self.icon_id)
        if right_space > 0.0:
            layout.separator(factor=right_space)


def register():
    preview_collections["main"] = previews.new()

def unregister():
    # Clear icons cache
    _icon_cache.clear()
    _icon_preview_cache.clear()

    # Clear preview collections
    previews.remove(preview_collections["main"])
    preview_collections.clear()
