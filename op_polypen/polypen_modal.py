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
from mathutils import Vector, Matrix, Quaternion

import math

from ..lib import common_utilities
from ..lib.common_utilities import showErrorMessage, get_source_object, get_target_object
from ..lib.classes.sketchbrush.sketchbrush import SketchBrush

from ..modaloperator import ModalOperator


class CGC_Polypen(ModalOperator):
    ''' CG Cookie Polypen Modal Editor '''
    
    bl_category    = "Retopology"
    bl_idname      = "cgcookie.polypen"
    bl_label       = "Polypen"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    def __init__(self):
        FSM = {}
        self.initialize(helpText='help_polypen.txt', FSM=FSM)
    
    def start_poll(self, context):
        ''' Called when tool is invoked to determine if tool can start '''
        self.settings = common_utilities.get_settings()
        
        if context.mode == 'EDIT_MESH' and self.settings.source_object == '':
            showErrorMessage('Must specify a source object first')
            return False
        if context.mode == 'OBJECT' and self.settings.source_object == '' and not context.active_object:
            showErrorMessage('Must specify a source object or select an object')
            return False
        if get_source_object().type != 'MESH':
            showErrorMessage('Source must be a mesh object')
            return False
        if get_target_object().type != 'MESH':
            showErrorMessage('Target must be a mesh object')
            return False
        if self.settings.source_object == self.settings.target_object and self.settings.source_object and self.settings.target_object:
            showErrorMessage('Source and Target cannot be same object')
            return False
        
        return True
    
    def start(self, context):
        ''' Called when tool has been invoked '''
        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_user_keymap_generate()
        
        if context.mode == 'OBJECT':

            # Debug level 2: time start
            check_time = Profiler().start()

            self.src_object = get_source_object()
            self.mx = self.src_object.matrix_world
            is_valid = is_object_valid(self.src_object)
            if not is_valid:
                clear_mesh_cache()
                polypen_undo_cache = []
                me = self.src_object.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
                me.update()
                bme = bmesh.new()
                bme.from_mesh(me)
                bvh = BVHTree.FromBMesh(bme)
                write_mesh_cache(self.src_object, bme, bvh)
                
            # Debug level 2: time end
            check_time.done()

            #Create a new empty destination object for new retopo mesh
            nm_polypen = self.src_object.name + "_polypen"
            self.tar_bmesh = bmesh.new()

            self.tar_object = setup_target_object( nm_polypen, self.src_object, self.tar_bmesh )

            self.extension_geometry = []
            self.snap_eds = []
            self.snap_eds_vis = []
            self.hover_ed = None

        elif context.mode == 'EDIT_MESH':
            self.src_object = get_source_object()
            self.mx = self.src_object.matrix_world
            is_valid = is_object_valid(self.src_object)
    
            if not is_valid:
                clear_mesh_cache()
                polypen_undo_cache = []
                me = self.src_object.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
                me.update()
            
                bme = bmesh.new()
                bme.from_mesh(me)
                bvh = BVHTree.FromBMesh(bme)
                write_mesh_cache(self.src_object, bme, bvh)
            
            self.tar_object = get_target_object()
            self.tar_bmesh = bmesh.from_edit_mesh(context.object.data)
        
        self.scale = self.src_object.scale[0]
        self.length_scale = get_object_length_scale(self.src_object)

        #self.polypen = Polypen(context, self.src_object, self.tar_object)
        
        context.area.header_text_set('Polypen')
    
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
    
    def update(self,context):
        '''Place update stuff here'''
        pass
    def modal_wait(self, context, eventd):
        '''
        Place code here to handle commands issued by user
        Return string that corresponds to FSM key, used to change states.  For example:
        - '':     do not change state
        - 'main': transition to main state
        - 'nav':  transition to a navigation state (passing events through to 3D view)
        '''
        return ''
