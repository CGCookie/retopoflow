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


class  CGC_Contours(ModalOperator):
    '''Draw Strokes Perpindicular to Cylindrical Forms to Retopologize Them'''
    bl_category = "Retopology"
    bl_idname = "retopoflow.contours"      # unique identifier for buttons and menu items to reference
    bl_label = "Contours"       # display name in the interface
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    #bl_options = {'REGISTER', 'UNDO'}       # enable undo for the operator.
    
    def __init__(self):
        FSM = {}
        FSM['main loop']    = self.modal_loop
        FSM['main guide']   = self.modal_guide
        FSM['cutting']      = self.modal_cut
        FSM['sketch']       = self.modal_sketching
        FSM['widget']       = self.modal_widget
        '''
        main, nav, and wait states are automatically added in initialize function, called below.
        '''
        self.initialize(FSM)
    
    def start_poll(self,context):
        return True
    
    def start(self, context):
        ''' Called when tool has been invoked '''
        self.contours_mode = 'loop'
        #do contours data stuff
        pass
    
    def modal_wait(self, context, eventd):
        '''
        Place code here to handle commands issued by user
        Return string that corresponds to FSM key, used to change states.  For example:
        - '':     do not change state
        - 'main': transition to main state
        - 'nav':  transition to a navigation state (passing events through to 3D view)
        '''
        #simple messaging
        if self.footer_last != self.footer:
            context.area.header_text_set('Contours: %s' % self.footer)
            self.footer_last = self.footer
        
        #contours mode toggle
        if eventd['press'] == 'TAB':
            if self.contours_mode == 'loop':
                self.contours_mode = 'guide'
            else:
                self.contours_mode = 'loop'
            return ''
        
        if self.contours_mode == 'loop':
            return self.modal_loop(context,eventd)
        else:
            return self.modal_guide(context,eventd)
         
    
    def modal_loop(self, context, eventd): 
        if self.footer != 'Loop Mode': self.footer = 'Loop Mode'
        return ''

    def modal_guide(self, context, eventd):
        if self.footer != 'Guide Mode': self.footer = 'Guide Mode'
        return ''
    
    def modal_cut(self, context, eventd):
        if self.footer != 'Cutting': self.footer = 'Cutting'
        return ''
        
    def modal_sketching(self, context, eventd):
        if self.footer != 'Sketchign': self.footer = 'Sketching'
        return ''
    
    def modal_widget(self,context,eventd):
        if self.footer != 'Widget': self.footer = 'Widget'
        return ''
    
    def update(self,context):
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
        ''' Place post view drawing code in here '''
        pass
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
        pass
    

