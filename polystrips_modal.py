'''
Copyright (C) 2015 CG Cookie
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
import bgl
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix
import math

from .modaloperator import ModalOperator


class CGC_Polystrips(ModalOperator):
    ''' CG Cookie Polystrips Editor '''
    bl_category = "Retopology"
    bl_idname = "cgcookie.polystrips"
    bl_label = "Retopoflow.Polystrips"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    def __init__(self):
        FSM = {}    # <-- custom states go here
        self.initialize(FSM)

    @classmethod
    def poll(cls, context):
        if context.mode not in {'EDIT_MESH', 'OBJECT'}:
            return False

        return context.object.type == 'MESH'

    def draw_callback(self, context):
        return self.ui.draw_callback(context)

    def modal(self, context, event):
        ret = self.ui.modal(context, event)
        if 'FINISHED' in ret or 'CANCELLED' in ret:
            self.ui.cleanup(context)
            common_utilities.callback_cleanup(self, context)
        return ret

    def invoke(self, context, event):

        if context.mode == 'EDIT_MESH' and len(context.selected_objects) != 2:
            showErrorMessage('Must select exactly two objects')
            return {'CANCELLED'}
        elif context.mode == 'OBJECT' and len(context.selected_objects) != 1:
            showErrorMessage('Must select only one object')
            return {'CANCELLED'}

        self.ui = PolystripsUI(context, event)

        # Switch to modal
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback, (context, ), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
