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
import math


from ..modaloperator import ModalOperator
from ..lib import common_utilities
from ..lib.common_utilities import get_source_object, get_target_object, showErrorMessage
from .. import key_maps

from .loopcut_data import LoopCut
from .loopcut_ui_modal import LoopCut_UI_ModalWait
from .loopcut_ui_draw import LoopCut_UI_Draw



class CGC_LoopCut(ModalOperator,LoopCut_UI_ModalWait,LoopCut_UI_Draw):
    ''' Loop Cut Modal Op '''
    bl_category = "Retopology"
    bl_idname = "cgcookie.loop_cut"        # unique identifier for buttons and menu items to reference
    bl_label = "RetopoFlow Loop Cut"       # display name in the interface
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    #bl_options = {'REGISTER', 'UNDO'}       # enable undo for the operator.
    
    def __init__(self):
        FSM = {}
        FSM['update'] = self.update
        
        '''
        fill FSM with 'state':function(self, eventd) to add states to modal finite state machine
        FSM['example state'] = example_fn, where `def example_fn(self, context)`.
        each state function returns a string to tell FSM into which state to transition.
        main, nav, and wait states are automatically added in initialize function, called below.
        '''
        
        self.initialize(FSM)
    
    def start_poll(self, context):
        ''' Called when tool is invoked to determine if tool can start '''

        self.settings = common_utilities.get_settings()

        if context.mode == 'EDIT_MESH' and self.settings.source_object == '':
            showErrorMessage('Must specify a source object first')
            return False

        return True
    
    def start(self, context):
        ''' Called when tool has been invoked '''
        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_user_keymap_generate()
        self.trg_obj = get_target_object()
        self.src_obj = get_source_object()
        bpy.context.scene.update()
        self.bme = bmesh.from_edit_mesh(self.trg_obj.data)
        self.loopcut = LoopCut(context, self.trg_obj, self.src_obj)
        self.loopcut.slide = self.settings.use_pressure
        
        
        context.area.header_text_set('LOOP CUT')
        
        
    def end(self, context):
        ''' Called when tool is ending modal '''
        bpy.ops.object.editmode_toggle()
        bpy.ops.object.editmode_toggle()
        self.bme.free()
        context.area.header_text_set()
        pass
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        self.loopcut.cut_loop(self.bme, select=True)
        pass
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        pass
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
        pass
    
    def update(self,context, eventd):
        '''Place update stuff here'''
        self.loopcut.cut_loop(self.bme, select=True)
        self.loopcut.push_to_edit_mesh(self.bme)
        self.loopcut.clear()
        return 'main'

    
    def hover_target(self,context,eventd,settings):
        x,y = eventd['mouse']
        region = context.region
        region = eventd['region']
        r3d = eventd['r3d']
        
        bpy.ops.object.editmode_toggle()
        hit = common_utilities.ray_cast_region2d(region, r3d, (x,y), self.trg_obj, settings)[1]
        bpy.ops.object.editmode_toggle()
        
        self.bme = bmesh.from_edit_mesh(self.trg_obj.data)
        self.bme.faces.ensure_lookup_table()
        self.bme.edges.ensure_lookup_table()
        self.bme.verts.ensure_lookup_table()
        
        if hit[2] != -1: #TODO store the ed in loopcut class and only recalc if it's different
            pt = hit[0]
            def ed_dist(ed):
                p0 = ed.verts[0].co
                p1 = ed.verts[1].co
                pmin, pct = intersect_point_line(pt, p0, p1)   
                dist = pmin - pt
                return dist.length, pct
            
            f = self.bme.faces[hit[2]]
            eds = [ed for ed in f.edges]
            test_edge = min(eds, key = ed_dist)
            d, pct = ed_dist(test_edge)
            
            if self.loopcut.slide:
                self.loopcut.pct = pct
                
            self.loopcut.find_face_loop(self.bme,test_edge)
            self.loopcut.calc_snaps(self.bme)
        else:
            self.loopcut.clear()
        
        