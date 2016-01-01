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
from .contours_ui_modalwait import Contours_UI_ModalWait
from ..cache import mesh_cache
from ..lib.common_utilities import get_settings


class  CGC_Contours(ModalOperator, Contours_UI_ModalWait, Contours_UI_Draw):
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
        elif context.mode == 'EDIT_MESH' and self.settings.source_object == '':
            showErrorMessage('Must specify a Source Object')
            return False

        elif context.mode == 'OBJECT' and self.settings.source_object == '' and not context.active_object:
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
    
    def start(self, context, recover = False):
        ''' Called when tool has been invoked '''
        print('did we get started')
        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_user_keymap_generate()
        self.contours = Contours(context, self.settings, recover = recover)
        return
    
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
    

class  CGC_ContoursRecover(ModalOperator, Contours_UI_ModalWait, Contours_UI_Draw):
    '''Draw Strokes Perpindicular to Cylindrical Forms to Retopologize Them'''
    bl_category = "Retopology"
    bl_idname = "cgcookie.contours_recover"      # unique identifier for buttons and menu items to reference
    bl_label = "Contours Recover"       # display name in the interface
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
        elif context.mode == 'EDIT_MESH' and self.settings.source_object == '':
            showErrorMessage('Must specify a Source Object')
            return False

        elif context.mode == 'OBJECT' and self.settings.source_object == '' and not context.active_object:
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
    
    def start(self, context, recover = True):
        ''' Called when tool has been invoked '''
        print('did we get started')
        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_user_keymap_generate()
        self.contours = Contours(context, self.settings, recover = recover)
        return
    
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