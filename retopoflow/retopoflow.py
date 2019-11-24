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

from .rf.rf_blender    import RetopoFlow_Blender
from .rf.rf_drawing    import RetopoFlow_Drawing
from .rf.rf_grease     import RetopoFlow_Grease
from .rf.rf_instrument import RetopoFlow_Instrumentation
from .rf.rf_sources    import RetopoFlow_Sources
from .rf.rf_spaces     import RetopoFlow_Spaces
from .rf.rf_states     import RetopoFlow_States
from .rf.rf_target     import RetopoFlow_Target
from .rf.rf_tools      import RetopoFlow_Tools
from .rf.rf_ui         import RetopoFlow_UI
from .rf.rf_undo       import RetopoFlow_Undo

from ..config.keymaps import default_rf_keymaps



class RetopoFlow(
    RetopoFlow_Blender,
    RetopoFlow_Drawing,
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

    default_keymap = default_rf_keymaps

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
        bpy.ops.object.mode_set(mode='OBJECT')

        # get scaling factor to fit all sources into unit box
        self.unit_scaling_factor = self.get_unit_scaling_factor()
        self.scale_to_unit_box()

        self.setup_target()
        self.setup_sources()
        self.setup_sources_symmetry()   # must be called after self.setup_target()!!
        self.setup_rotate_about_active()

        self.setup_states()
        self.setup_rftools()
        self.setup_grease()
        self.setup_ui()                 # must be called after self.setup_target() and self.setup_rftools()!!
        self.setup_undo()               # must be called after self.setup_ui()!!

    def end(self):
        self.end_rotate_about_active()
        self.teardown_target()
        bpy.ops.object.mode_set(mode='EDIT')

