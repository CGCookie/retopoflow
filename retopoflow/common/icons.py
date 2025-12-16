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

import bpy
from bl_ui.space_toolsystem_common import ToolSelectPanelHelper

from ..rftool_base import RFTool_Base

# (icon_name -> icon_value) map
_icon_cache = {}
ICONS_DIRPATH = Path(__file__).parent.parent.parent / 'icons'


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

def clear_icon_cache() -> None:
    global _icon_cache
    _icon_cache = {}
