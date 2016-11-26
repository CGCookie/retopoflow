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
import os


from ..modaloperator import ModalOperator
from .. import key_maps
from ..lib import common_utilities
from ..lib.common_utilities import bversion, get_object_length_scale, dprint, frange, selection_mouse
from ..lib.common_utilities import showErrorMessage, get_source_object, get_target_object
from ..lib.classes.profiler import profiler
from .contour_classes import Contours
from .contours_ui_draw import Contours_UI_Draw
from ..cache import mesh_cache
from ..lib.common_utilities import get_settings


class  CGC_Contours(ModalOperator, Contours_UI_Draw):
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
        self.initialize('help_contours.txt', FSM)
    
    def start_poll(self,context):

        self.settings = common_utilities.get_settings()

        if context.space_data.viewport_shade in {'WIREFRAME','BOUNDBOX'}:
            showErrorMessage('Viewport shading must be at least SOLID')
            return False
        if context.mode == 'EDIT_MESH' and self.settings.source_object == '':
            showErrorMessage('Must specify a Source Object')
            return False
        if context.mode == 'EDIT_MESH' and get_source_object() == context.active_object:
            showErrorMessage('Cannot use %s when editing the source object' % (self.bl_label))
            return False

        if context.mode == 'OBJECT' and self.settings.source_object == '' and not context.active_object:
            showErrorMessage('Must select an object or specifiy a Source Object')
            return False

        if self.settings.source_object == self.settings.target_object and self.settings.source_object and self.settings.target_object:
            showErrorMessage('Source and Target cannot be same object')
            return False

        if get_source_object().type != 'MESH':
            showErrorMessage('Source must be a mesh object')
            return False

        if get_target_object().type != 'MESH':
            showErrorMessage('Target must be a mesh object')
            return False

        return True
    
    def start(self, context):
        ''' Called when tool has been invoked '''
        print('did we get started')
        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_user_keymap_generate()
        self.contours = Contours(context, self.settings)
        return ''
    
    def modal_wait(self, context, eventd):
        #simple messaging
        if self.footer_last != self.footer:
            context.area.header_text_set('Contours: %s' % self.footer)
            self.footer_last = self.footer
        
        #contours mode toggle
        if eventd['press'] in self.keymap['mode']:
            if self.contours.mode == 'loop':
                self.contours.mode_set_guide()
                self.contours.mode = 'guide'
            else:
                self.contours.mode_set_loop()
                self.contours.mode = 'loop'
            return ''
        
        elif eventd['press'] in self.keymap['undo']:
            self.contours.undo_action()
            return ''
            
        if self.contours.mode == 'loop':
            return self.modal_loop(context,eventd)
        else:
            return self.modal_guide(context,eventd)
            
    def modal_loop(self, context, eventd): 
        if self.footer != 'Loop Mode': self.footer = 'Loop Mode'
        
        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering widget
            x,y = eventd['mouse']
            self.contours.hover_loop_mode(context, self.settings, x,y)
            return ''
        
        if eventd['press'] in selection_mouse(): #self.keymap['select']: # selection
            ret = self.contours.loop_select(context, eventd)
            if ret:
                return ''    
        
        if eventd['press'] in self.keymap['action']:   # cutting and widget hard coded to LMB
            if self.contours.cut_line_widget:
                self.contours.prepare_widget(eventd)
                return 'widget'
            
            else:
                self.footer = 'Cutting'
                x,y = eventd['mouse']
                self.contours.sel_loop = self.contours.click_new_cut(context, self.settings, x,y)    
                return 'cutting'
        
        if eventd['press'] in self.keymap['new']:
            self.contours.force_new = self.contours.force_new != True
            return ''
        
        ###################################
        # selected contour loop commands
        
        if self.contours.sel_loop:
            if eventd['press'] in self.keymap['delete']:
                self.contours.loops_delete(context, [self.contours.sel_loop])
                return ''
        
            if eventd['press'] in self.keymap['align']:
                self.contours.loop_align(context, eventd)
                return ''
            elif eventd['press'] in self.keymap['up shift']:
                self.contours.loop_shift(context, eventd, up = True)
                return ''        
            elif eventd['press'] in self.keymap['dn shift']:
                self.contours.loop_shift(context, eventd, up = False)
                return ''
            elif eventd['press'] in self.keymap['up count']:
                n = len(self.contours.sel_loop.verts_simple)
                self.contours.loop_nverts_change(context, eventd, n+1)    
                return ''
            elif eventd['press'] in self.keymap['dn count']:
                n = len(self.contours.sel_loop.verts_simple)
                self.contours.loop_nverts_change(context, eventd, n-1)
                return ''
        
            elif eventd['press'] in self.keymap['snap cursor']:
                context.scene.cursor_location = self.contours.sel_loop.plane_com
                return ''
            elif eventd['press'] in self.keymap['view cursor']:
                bpy.ops.view3d.view_center_cursor()
                return ''
        
            elif eventd['press'] in self.keymap['rotate']:
                self.contours.prepare_rotate(context,eventd)
                #header text handled during rotation
                return 'widget'
            
            if eventd['press'] in self.keymap['translate']:
                self.contours.prepare_translate(context, eventd)
                #header text handled during translation
                return 'widget'
        return ''

    def modal_guide(self, context, eventd):
        if self.footer != 'Guide Mode': self.footer = 'Guide Mode'
        
        if eventd['press'] in self.keymap['new']:
            self.contours.force_new = self.contours.force_new != True
            return '' 
        
        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering widget
            x,y = eventd['mouse']
            self.contours.hover_guide_mode(context, self.settings, x, y)
            return ''
        
        if eventd['press'] in self.keymap['action']: #LMB hard code for sketching
            
            self.footer = 'sketching'
            x,y = eventd['mouse']
            self.contours.sketch = [(x,y)] 
            return 'sketch'
        
        if eventd['press'] in selection_mouse(): #self.keymap['select']: # selection
            self.contours.guide_mode_select()   
            return ''
        
        if self.contours.sel_path:
            if eventd['press'] in self.keymap['delete']:
                self.contours.create_undo_snapshot('DELETE')
                self.contours.cut_paths.remove(self.contours.sel_path)
                self.contours.sel_path = None
                return ''
            
            if eventd['press'] in self.keymap['up shift']:
                self.contours.segment_shift(context, up = True)
                return ''
            
            if eventd['press'] in self.keymap['dn shift']:
                self.contours.segment_shift(context, up = False)
                return 
            
            if eventd['press'] in self.keymap['up count']:
                n = self.contours.sel_path.segments + 1
                if self.contours.sel_path.seg_lock: #TODO showError(yada yada)
                    showErrorMessage('PATH SEGMENTS: Path is locked, cannot adjust segments')
                else:
                    self.contours.segment_n_loops(context, self.contours.sel_path, n)    
                #self.temporary_message_start(context, 'PATH SEGMENTS: %i' % n)
                return ''
            
            if eventd['press'] in self.keymap['dn count']:
                n = self.contours.sel_path.segments - 1
                if self.contours.sel_path.seg_lock:
                    return ''
                    showErrorMessage('PATH SEGMENTS: Path is locked, cannot adjust segments')
                    #self.temporary_message_start(context, 'PATH SEGMENTS: Path is locked, cannot adjust segments')
                elif n < 3:
                    #self.temporary_message_start(context, 'PATH SEGMENTS: You want more segments than that!')
                    return ''
                else:
                    self.contours.segment_n_loops(context, self.contours.sel_path, n)    
                    #self.temporary_message_start(context, 'PATH SEGMENTS: %i' % n)
                return ''
            
            if eventd['press'] in self.keymap['smooth']:
                
                self.contours.segment_smooth(context, self.settings)
                #messaging handled in operator
                return ''
            
            if eventd['press'] in self.keymap['snap cursor']:
                self.contours.cursor_to_segment(context)
                #self.temporary_message_start(context, 'Cursor to Segment')
                return ''
             
             
            if eventd['press'] in self.keymap['view cursor']:
                bpy.ops.view3d.view_center_cursor()
                return ''    
        return ''
    
    def modal_cut(self, context, eventd):
        if self.footer != 'Cutting': self.footer = 'Cutting'
        
        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            self.contours.sel_loop.tail.x, self.contours.sel_loop.tail.y  = x, y    
            return ''
        
        if eventd['release'] in self.keymap['action']: #LMB hard code for cut
            print('new cut made')
            x,y = eventd['mouse']
            self.contours.release_place_cut(context, self.settings, x, y)
            return 'main'
        
        return ''
        
    def modal_sketching(self, context, eventd):
        if self.footer != 'Sketching': self.footer = 'Sketching'
        
        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            self.sketch_curpos = (x,y)
            
            if not len(self.contours.sketch):
                #somehow we got into sketching w/o sketching
                return 'main'
            
            (lx, ly) = self.contours.sketch[-1]
            #on the fly, backwards facing, smoothing
            ss0,ss1 = self.contours.stroke_smoothing,1-self.contours.stroke_smoothing
            self.contours.sketch += [(lx*ss0+x*ss1, ly*ss0+y*ss1)] #vs append?         
            return ''
        
        elif eventd['release'] in self.keymap['action']:
            
            if eventd['release'] in selection_mouse(): #selection and action overlap
                print('selection action overlap')
                dist_traveled = 0.0
                for s0,s1 in zip(self.contours.sketch[:-1],self.contours.sketch[1:]):
                    dist_traveled += (Vector(s0) - Vector(s1)).length
                    
                if dist_traveled < 5:
                    settings = get_settings()
                    x,y = eventd['mouse']
                    self.contours.hover_guide_mode(context, settings, x, y)
                    self.contours.guide_mode_select()  
                    self.contours.skecth = [] 
                    return 'main' #''
                else:
                    print('dist traveled was real sketch')
                    print(dist_traveled)
            
            self.contours.sketch_confirm(context) 
            return 'main'
        return ''
    
    def modal_widget(self,context,eventd):
        if self.footer != 'Widget': self.footer = 'Widget'
        
        if eventd['type'] == 'MOUSEMOVE':
            self.contours.widget_transform(context, self.settings, eventd)
            return ''
        
        elif eventd['release'] in self.keymap['action'] | self.keymap['modal confirm']:
            self.contours.cut_line_widget = None
            self.contours.sel_path.update_backbone(context, mesh_cache['bme'], mesh_cache['bvh'], self.contours.mx, self.contours.sel_loop, insert = False)
            return 'main'
        
        elif eventd['press'] in self.keymap['modal cancel']:
            self.contours.widget_cancel(context)
            return 'main'
        return ''
    
    def update(self,context):
        pass
    
    def end(self, context):
        ''' Called when tool is ending modal '''
        pass
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        self.contours.finish_mesh(context)
        pass
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        pass
    
