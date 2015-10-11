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
import blf
import bmesh
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree

import math
import os
import copy

from ..lib import common_utilities
from ..lib.common_utilities import bversion, get_object_length_scale, dprint, profiler, frange, selection_mouse, showErrorMessage
from ..lib.common_utilities import point_inside_loop2d, get_source_object
from ..lib.common_classes import SketchBrush
from ..lib.class_textbox import TextBox
from .. import key_maps
from ..cache import mesh_cache, clear_mesh_cache, write_mesh_cache, is_object_valid


class Tweak_UI:
    def initialize_ui(self):
        pass
    
    
    def start_ui(self, context):
        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_default_keymap_generate()
        
        self.mode_pos        = (0, 0)
        self.cur_pos         = (0, 0)
        self.mode_radius     = 0
        self.action_center   = (0, 0)
        self.action_radius   = 0
        self.is_navigating   = False
        
        self.tweak_data = None

        self.post_update = True

        self.obj_orig = get_source_object()
        self.mx = self.obj_orig.matrix_world
        
        is_valid = is_object_valid(self.obj_orig)
        
        if is_valid:
                pass
                #self.bme = mesh_cache['bme']            
                #self.bvh = mesh_cache['bvh']
                
        else:
            clear_mesh_cache()           
            me = self.obj_orig.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
            me.update()
            bme = bmesh.new()
            bme.from_mesh(me)
            bvh = BVHTree.FromBMesh(bme)
            write_mesh_cache(self.obj_orig, bme, bvh)
        
        self.dest_obj = context.object
        self.dest_bme = bmesh.from_edit_mesh(context.object.data)
        self.snap_eds = [] #EXTEND
        #self.snap_eds = [ed for ed in self.dest_bme.edges if not ed.is_manifold]
        
        
        region, r3d = context.region, context.space_data.region_3d
        dest_mx = self.dest_obj.matrix_world
        rv3d = context.space_data.region_3d
        self.snap_eds_vis = [False not in common_utilities.ray_cast_visible_bvh([dest_mx * ed.verts[0].co, dest_mx * ed.verts[1].co], mesh_cache['bvh'], self.mx, rv3d) for ed in self.snap_eds]
        self.hover_ed = None
        
        
        self.scale = self.obj_orig.scale[0]
        self.length_scale = get_object_length_scale(self.obj_orig)
        # World stroke radius
        self.stroke_radius = 0.01 * self.length_scale
        self.stroke_radius_pressure = 0.01 * self.length_scale
        # Screen_stroke_radius
        self.screen_stroke_radius = 20  # TODO, hood to settings

        self.sketch_brush = SketchBrush(context,
                                        self.settings,
                                        0, 0, #event.mouse_region_x, event.mouse_region_y,
                                        15,  # settings.quad_prev_radius,
                                        mesh_cache['bvh'], self.mx,
                                        self.obj_orig.dimensions.length)

        self.undo_cache = []            # Clear the cache in case any is left over
        
        
        # help file stuff
        my_dir = os.path.split(os.path.abspath(__file__))[0]
        filename = os.path.join(my_dir, '..', 'help', 'help_tweak.txt')
        if os.path.isfile(filename):
            help_txt = open(filename, mode='r').read()
        else:
            help_txt = "No Help File found, please reinstall!"
        self.help_box = TextBox(context,500,500,300,200,10,20, help_txt)
        if not self.settings.help_def:
            self.help_box.collapse()
        self.help_box.snap_to_corner(context, corner = [1,1])
        
        
        
        context.area.header_text_set('Tweak')
    
    def end_ui(self, context):
        pass
        
    def cleanup(self, context):
        '''
        remove temporary object
        '''
        dprint('cleaning up!')

        if self.obj_orig.modifiers:
            pass
    
    ###############################
    # undo functions
    
    def create_undo_snapshot(self, action):
        '''
        unsure about all the _timers get deep copied
        and if sel_gedges and verts get copied as references
        or also duplicated, making them no longer valid.
        '''
        
        print('create_undo_snapshot not implemented')
        return
        
        repeated_actions = {'count', 'zip count'}

        if action in repeated_actions and len(self.undo_cache):
            if action == self.undo_cache[-1][1]:
                dprint('repeatable...dont take snapshot')
                return

        p_data = copy.deepcopy(self.polystrips)

        self.undo_cache.append(([p_data, act_gvert, act_gedge, act_gvert], action))

        if len(self.undo_cache) > self.settings.undo_depth:
            self.undo_cache.pop(0)

    def undo_action(self):
        '''
        '''
        
        print('undo_action not implemented')
        return
        
        if len(self.undo_cache) > 0:
            data, action = self.undo_cache.pop()

            self.polystrips = data[0]

            if data[1]:
                self.act_gvert = self.polystrips.gverts[data[1]]
            else:
                self.act_gvert = None

            if data[2]:
                self.sel_gedge = self.polystrips.gedges[data[2]]
            else:
                self.sel_gedge = None

            if data[3]:
                self.act_gvert = self.polystrips.gverts[data[3]]
            else:
                self.act_gvert = None
    

    
