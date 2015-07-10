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
        FSM['widget']       = self.modal_widget_tool
        '''
        main, nav, and wait states are automatically added in initialize function, called below.
        '''
        self.initialize(FSM)
    
    
    def modal_wait(self, eventd):
        
        
        
    def modal_loop(self, eventd): 
        self.footer = 'Loop Mode'
        
        #############################################
        # general navigation
        nmode = self.modal_nav(eventd)
        if nmode:
            return nmode  #stop here and tell parent modal to 'PASS_THROUGH'
        
        if eventd['press'] in self.keymap['help']:
            if  self.help_box.is_collapsed:
                self.help_box.uncollapse()
            else:
                self.help_box.collapse()
            self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
        
        if eventd['press'] in self.keymap['confirm']:
            self.finish_mesh(eventd['context'])
            eventd['context'].area.header_text_set()
            return 'finish'
        
        if eventd['press'] in self.keymap['cancel']:
            eventd['context'].area.header_text_set()
            return 'cancel'
        
        #####################################
        # general, non modal commands
        if eventd['press'] in self.keymap['undo']:
            print('undo it!')
            self.undo_action()
            self.temporary_message_start(eventd['context'], "UNDO: %i steps in undo_cache" % len(contour_undo_cache))
            return ''
        
        if eventd['press'] in self.keymap['mode']:
            self.footer = 'Guide Mode'
            self.mode_set_guide(eventd['context'])
            return 'main guide'
     
        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering widget
            x,y = eventd['mouse']
            self.hover_loop_mode(eventd['context'], self.settings, x,y)
            return ''
        
        if eventd['press'] in selection_mouse(): #self.keymap['select']: # selection
            ret = self.loop_select(eventd['context'], eventd)
            if ret:
                return ''
        
   
        if eventd['press'] in self.keymap['action']:   # cutting and widget hard coded to LMB
            if self.help_box.is_hovered:
                if  self.help_box.is_collapsed:
                    self.help_box.uncollapse()
                else:
                    self.help_box.collapse()
                self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
            
                return ''
            
            if self.cut_line_widget:
                self.prepare_widget(eventd)
                
                return 'widget'
            
            else:
                self.footer = 'Cutting'
                x,y = eventd['mouse']
                self.sel_loop = self.click_new_cut(eventd['context'], self.settings, x,y)    
                return 'cutting'
        
        if eventd['press'] in self.keymap['new']:
            self.force_new = self.force_new != True
            return ''
        ###################################
        # selected contour loop commands
        
        if self.sel_loop:
            if eventd['press'] in self.keymap['delete']:
                
                self.loops_delete(eventd['context'], [self.sel_loop])
                self.temporary_message_start(eventd['context'], 'DELETE')
                return ''
            

            if eventd['press'] in self.keymap['rotate']:
                self.prepare_rotate(eventd['context'],eventd)
                #header text handled during rotation
                return 'widget'
            
            if eventd['press'] in self.keymap['translate']:
                self.prepare_translate(eventd['context'], eventd)
                #header text handled during translation
                return 'widget'
            
            if eventd['press'] in self.keymap['align']:
                self.loop_align(eventd['context'], eventd)
                self.temporary_message_start(eventd['context'], 'ALIGN LOOP')
                return ''
            
            if eventd['press'] in self.keymap['up shift']:
                self.loop_shift(eventd['context'], eventd, up = True)
                self.temporary_message_start(eventd['context'], 'SHIFT: ' + str(self.sel_loop.shift))
                return ''
            
            if eventd['press'] in self.keymap['dn shift']:
                self.loop_shift(eventd['context'], eventd, up = False)
                self.temporary_message_start(eventd['context'], 'SHIFT: ' + str(self.sel_loop.shift))
                return ''
            
            if eventd['press'] in self.keymap['up count']:
                n = len(self.sel_loop.verts_simple)
                self.loop_nverts_change(eventd['context'], eventd, n+1)
                #message handled within op
                return ''
            
            if eventd['press'] in self.keymap['dn count']:
                n = len(self.sel_loop.verts_simple)
                self.loop_nverts_change(eventd['context'], eventd, n-1)
                #message handled within op
                return ''
            
            if eventd['press'] in self.keymap['snap cursor']:
                eventd['context'].scene.cursor_location = self.sel_loop.plane_com
                self.temporary_message_start(eventd['context'], "Cursor to loop")
                return ''
            
            if eventd['press'] in self.keymap['view cursor']:
                bpy.ops.view3d.view_center_cursor()
                self.temporary_message_start(eventd['context'], "View to cursor")
                return ''
                
        return ''
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
        ''' Place post view drawing code in here '''
        pass
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
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
