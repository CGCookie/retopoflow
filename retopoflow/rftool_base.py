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

from __future__ import annotations

import bpy
import bl_ui
from bpy.types import Context, WorkSpaceTool
from typing import Callable, ClassVar
from collections.abc import Sequence
from .preferences import RF_Prefs
from .common.operator import RFKeyMaps, BLKeyMaps
from .rfbrush_base import RFBrush_Base
from .rfoverlay_base import RFOverlay_Base
from ..addon_common.common.resetter import Resetter

class RFTool_Base(WorkSpaceTool):
    bl_idname : str = 'unlabeled'
    bl_space_type : str = 'VIEW_3D'
    bl_context_mode : str = 'EDIT_MESH'
    bl_keymap : BLKeyMaps = ()
    rf_idname : str = 'unlabeled'
    rf_brush : RFBrush_Base | None = None
    rf_overlay : type[RFOverlay_Base] | None = None
    resetter : Resetter | None = None

    _subclasses : list[type[RFTool_Base]] = []
    def __init_subclass__(cls, **kwargs):
        RFTool_Base._subclasses.append(cls)
        super().__init_subclass__(**kwargs)
        cls.rf_idname = cls.bl_idname

    @classmethod
    def activate_tool(cls, context : Context):
        bl_ui.space_toolsystem_common.activate_by_id(
            context,
            'VIEW_3D',
            cls.bl_idname,
        )

    ###########################################################
    # subclasses may overwrite these class methods

    @classmethod
    def register(cls): pass
    @classmethod
    def unregister(cls): pass

    @classmethod
    def activate(cls, _context : Context): pass
    @classmethod
    def deactivate(cls, _context : Context): pass

    @classmethod
    def depsgraph_update(cls): pass

    ###########################################################

    @staticmethod
    def get_all_RFTools() -> list[type[RFTool_Base]]:
        return RFTool_Base._subclasses
        # return RFTool_Base.__subclasses__()  # this only works if the subclass is still in scope!!!!!

    @staticmethod
    def register_all():
        prefs = RF_Prefs.get_prefs(bpy.context)
        after = "builtin.measure"
        for i, rft in enumerate(RFTool_Base.get_all_RFTools()):
            bpy.utils.register_tool(rft, separator=(i==0), after=after, group=(i==0 and not prefs.expand_tools))
            after = rft.bl_idname
            rft.register()
        print(f'RF registered {len(RFTool_Base.get_all_RFTools())} RFTools')

    @staticmethod
    def unregister_all():
        for rft in reversed(RFTool_Base.get_all_RFTools()):
            rft.unregister()
            bpy.utils.unregister_tool(rft)
