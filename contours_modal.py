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
from . import key_maps

class  CGC_Contours(ModalOperator):
    '''Draw Strokes Perpindicular to Cylindrical Forms to Retopologize Them'''
    bl_category = "Retopology"
    bl_idname = "cgcookie.contours"      # unique identifier for buttons and menu items to reference
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
        if context.space_data.viewport_shade in {'WIREFRAME','BOUNDBOX'}:
            showErrorMessage('Viewport shading must be at least SOLID')
            return False
        elif context.mode == 'EDIT_MESH' and len(context.selected_objects) != 2:
            showErrorMessage('Must select exactly two objects')
            return False
        elif context.mode == 'OBJECT' and len(context.selected_objects) != 1:
            showErrorMessage('Must select only one object')
            return False
        return True
    
    def start(self, context):
        ''' Called when tool has been invoked '''
        print('did we get started')
        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_default_keymap_generate()
        self.get_help_text()
        self.contours_mode = 'loop'
        
        self.segments = settings.vertex_count
        self.guide_cuts = settings.ring_count
        
        self.contours = Contours(context, self.settings)
         
        self.draw_cache = []

        #what is the mouse over top of currently
        self.hover_target = None
        #keep track of selected cut_line and path
        self.sel_loop = None   #TODO: Change this to selected_loop
        
        print('we got started!')
        return ''
    
    def modal_wait(self, context, eventd):
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
        if self.footer != 'Sketching': self.footer = 'Sketching'
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
        self.help_box.draw()
        pass
    
    def get_help_text(self):
        my_dir = os.path.split(os.path.abspath(__file__))[0]
        filename = os.path.join(my_dir, "help/help_contours.txt")
        if os.path.isfile(filename):
            help_txt = open(filename, mode='r').read()
        else:
            help_txt = "No Help File found, please reinstall!"
        return help_txt
    
        self.help_box.raw_text = help_txt
        if not settings.help_def:
            self.help_box.collapse()
        self.help_box.snap_to_corner(context, corner = [1,1])
