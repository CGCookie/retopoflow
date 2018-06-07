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
import bmesh
import bgl
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_point_line
from mathutils.bvhtree import BVHTree

from ..modaloperator import ModalOperator
from ..lib import common_utilities
from ..lib.common_utilities import get_source_object, get_target_object, showErrorMessage
from .. import key_maps

from .loopslide_data import loopslide
from .loopslide_ui_modal import loopslide_UI_Modal
from .loopslide_ui_draw import loopslide_UI_Draw
from .loopslide_ui_utils import loopslide_UI_fns



class CGC_loopslide(ModalOperator, loopslide_UI_fns, loopslide_UI_Modal, loopslide_UI_Draw):
    ''' Loop Slide Modal Op '''
    bl_category = "Retopology"
    bl_idname = "cgcookie.loop_slide"       # unique identifier for buttons and menu items to reference
    bl_label = "Loop Slide 1.3"  # display name in the interface
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    #bl_options = {'REGISTER', 'UNDO'}       # enable undo for the operator.
    
    def __init__(self):
        FSM = {}
        FSM['slide'] = self.modal_slide
        
        
        '''
        fill FSM with 'state':function(self, eventd) to add states to modal finite state machine
        FSM['example state'] = example_fn, where `def example_fn(self, context)`.
        each state function returns a string to tell FSM into which state to transition.
        main, nav, and wait states are automatically added in initialize function, called below.
        '''
        
        self.initialize('help_loopslide.txt', FSM)
    
    def start_poll(self, context):
        ''' Called when tool is invoked to determine if tool can start '''

        self.settings = common_utilities.get_settings()

        if context.mode == 'EDIT_MESH' and self.settings.source_object == '':
            showErrorMessage('Must specify a source object first')
            return False
        if context.mode == 'EDIT_MESH' and get_source_object() == context.active_object:
            showErrorMessage('Cannot use %s when editing the source object' % (self.bl_label))
            return False

        if get_source_object().type != 'MESH':
            showErrorMessage('Source must be a mesh object')
            return False
        if len(get_source_object().data.polygons) <= 0:
            showErrorMessage('Source must have at least one face')
            return False

        return True
    
    def start(self, context):
        ''' Called when tool has been invoked '''
        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_user_keymap_generate()
        
        self.src_obj = get_source_object()
        self.src_mx = self.src_obj.matrix_world
        self.src_bme = bmesh.new()
        self.src_bme.from_object(self.src_obj, context.scene)
        self.src_bvh = BVHTree.FromBMesh(self.src_bme)
    
        #bpy.context.scene.update() #why?
        self.trg_obj = get_target_object()
        self.trg_mx = self.trg_obj.matrix_world
        self.trg_bme = bmesh.from_edit_mesh(self.trg_obj.data)
        self.trg_bme.faces.ensure_lookup_table()
        self.trg_bme.edges.ensure_lookup_table()
        self.trg_bme.verts.ensure_lookup_table()
        self.trg_bvh = BVHTree.FromBMesh(self.trg_bme)
        
        
        self.loopslide = loopslide(context, self.trg_obj, self.trg_bvh, source_obj = self.src_obj, source_bvh = self.src_bvh)


        context.area.header_text_set('LOOP SLIDE')
        
        
    def end(self, context):
        ''' Called when tool is ending modal '''
        bpy.ops.object.editmode_toggle()
        bpy.ops.object.editmode_toggle()
        self.trg_bme.free()
        self.src_bme.free
        del self.src_bvh
        del self.trg_bvh
        context.area.header_text_set()
        pass
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        #self.loopcut.cut_loop(self.bme, select=True)
        pass
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        pass
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
        pass
    
    def update(self,context, eventd):
        '''Place update stuff here'''
        # self.loopslide.move_loop(self.bme, select=True)
        # self.trg_bvh = self.loop_slide.update_trg_bvh(self.trg_bme)
        # self.loopcut.push_to_edit_mesh(self.bme)
        # self.loopcut.clear()
        return ''

    
    
        
        