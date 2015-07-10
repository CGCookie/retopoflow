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
    
    def start_poll(self, context):
        if context.mode == 'EDIT_MESH' and len(context.selected_objects) != 2:
            showErrorMessage('Must select exactly two objects')
            return False
        
        if context.mode == 'OBJECT' and len(context.selected_objects) != 1:
            showErrorMessage('Must select only one object')
            return False
        
        if context.object.type != 'MESH':
            showErrorMessage('Must select a mesh object')
            return False
        
        return True
    
    def start(self, context):
        ''' Called when tool is invoked to determine if tool can start '''
        self.ui = PolystripsUI(context, event)
    
    def end(self, context):
        ''' Called when tool is ending modal '''
        self.ui.cleanup(context)
        pass
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        pass
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        pass
    
    def draw_postview(self, context):
        ''' Place post view drawing code in here '''
        pass
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
        return self.ui.draw_callback(context)
    
    def modal_wait(self, context, eventd):
        '''
        Place code here to handle commands issued by user
        Return string that corresponds to FSM key, used to change states.  For example:
        - '':     do not change state
        - 'main': transition to main state
        - 'nav':  transition to a navigation state (passing events through to 3D view)
        '''
        ret = self.ui.modal(context, event)
        return ret

