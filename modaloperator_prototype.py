'''
Copyright (C) 2015 Taylor University, CG Cookie

Created by Dr. Jon Denning and Spring 2015 COS 424 class

Some code copied from CG Cookie Retopoflow project
https://github.com/CGCookie/retopoflow

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

from .common import bezier_cubic_eval as curve_eval
from .common import bezier_cubic_eval_derivative as curve_der


class OP_BaseEditor(ModalOperator):
    ''' Modal Base Editor '''
    bl_idname  = "cos424.baseeditor"       # unique identifier for buttons and menu items to reference.
    bl_label   = "COS424: Base Editor"     # display name in the interface.
    bl_options = {'REGISTER', 'UNDO'}       # enable undo for the operator.
    
    def __init__(self):
        FSM = {}
        
        '''
        fill FSM with 'state':function(self, eventd) to add states to modal finite state machine
        FSM['example state'] = example_fn, where `def example_fn(self, context)`
        each state function returns a string to tell FSM into which state to transition.
        main, nav, and wait states are automatically added in initialize function, called below.
        '''
        
        self.initialize(FSM)
    
    def start(self, context):
        ''' Called when tool has been invoked '''
        pass
    
    def end(self, context):
        ''' Called when tool is ending modal '''
        pass
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        pass
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        pass
    
    def draw_postview(self, context):
        ''' Place drawing code in here '''
        pass
        
    
    def modal_wait(self, eventd):
        '''
        Place code here to handle commands issued by user
        Return string that corresponds to FSM key, used to change states.  For example:
        - '':     do not change state
        - 'main': transition to main state
        - 'nav':  transition to a navigation state (passing events through to 3D view)
        '''

        return ''
