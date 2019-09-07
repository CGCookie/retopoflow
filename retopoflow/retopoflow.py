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

from .retopoflow_parts.retopoflow_blender    import RetopoFlow_Blender
from .retopoflow_parts.retopoflow_grease     import RetopoFlow_Grease
from .retopoflow_parts.retopoflow_instrument import RetopoFlow_Instrumentation
from .retopoflow_parts.retopoflow_sources    import RetopoFlow_Sources
from .retopoflow_parts.retopoflow_spaces     import RetopoFlow_Spaces
from .retopoflow_parts.retopoflow_states     import RetopoFlow_States
from .retopoflow_parts.retopoflow_target     import RetopoFlow_Target
from .retopoflow_parts.retopoflow_tools      import RetopoFlow_Tools
from .retopoflow_parts.retopoflow_ui         import RetopoFlow_UI
from .retopoflow_parts.retopoflow_undo       import RetopoFlow_Undo

# from .rfcontext.rfcontext import RFContext


class RetopoFlow(
    RetopoFlow_Blender,
    RetopoFlow_Grease,
    RetopoFlow_Instrumentation,
    RetopoFlow_Sources,
    RetopoFlow_Spaces,
    RetopoFlow_States,
    RetopoFlow_Target,
    RetopoFlow_Tools,
    RetopoFlow_UI,
    RetopoFlow_Undo,
):

    instance = None

    default_keymap = {
        'undo': {'CTRL+Z'},
        'redo': {'CTRL+SHIFT+Z'},
        'commit': {'TAB',},
        'cancel': {'ESC',},
        'help': {'F1'},
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
        RetopoFlow.instance = self

        # get scaling factor to fit all sources into unit box
        self.unit_scaling_factor = self.get_unit_scaling_factor()
        self.scale_to_unit_box()

        self.target = self.get_target()
        print('target: %s' % self.target.name)

        self.setup_rftools()
        self.setup_ui()
        self.setup_grease()
        self.setup_target()
        self.setup_sources()
        self.setup_sources_symmetry()   # must be called after self.setup_target()!!
        self.setup_rotate_about_active()
        self.setup_undo()

    def end(self):
        self.end_rotate_about_active()
        self.target.hide_viewport = False



