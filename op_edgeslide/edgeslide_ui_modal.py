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

from ..lib import common_utilities
from ..lib.common_utilities import bversion, get_object_length_scale, dprint, profiler, frange, selection_mouse, showErrorMessage


class EdgeSlide_UI_Modal():
    
    def modal_wait(self, context, eventd):
        '''
        Place code here to handle commands issued by user
        Return string that corresponds to FSM key, used to change states.  For example:
        - '':     do not change state
        - 'main': transition to main state
        - 'nav':  transition to a navigation state (passing events through to 3D view)
        '''
        

        settings = common_utilities.get_settings()
        if eventd['press'] in self.keymap['confirm']:
            self.create_mesh(eventd['context'])
            return 'finish'

        if eventd['press'] in self.keymap['cancel']:
            return 'cancel'

        #####################################
        # General

        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering
            #update brush and brush size
            self.hover_edge_pick(context,eventd,settings)
            return ''

        
        if eventd['type'] in self.keymap['action']:
            
            if len(self.edgeslide.edge_loop_eds):
                return 'slide'
            
            return ''
        
    def modal_slide(self,context,eventd):
        
        if eventd['type'] in self.keymap['action'] or eventd['type'] in self.keymap['confirm']:
            return 'update'
        
        elif eventd['type'] in self.keymap['cancel']:
            self.edgeslide.clear()
            return 'main'
        
        elif eventd['type'] == 'MOUSEMOVE':
            
            return ''
        