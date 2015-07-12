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

import math
import os
import copy

from ..lib import common_utilities
from ..lib.common_utilities import bversion, get_object_length_scale, dprint, profiler, frange, selection_mouse, showErrorMessage
from ..lib.common_utilities import point_inside_loop2d
from ..lib.common_classes import SketchBrush, TextBox
from .. import key_maps

from .edgepatches_datastructure import EdgePatches, EPVert, EPEdge, EPPatch



class EdgePatches_UI:
    def initialize_ui(self):
        pass
    
    
    def start_ui(self, context):
        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_default_keymap_generate()
        
        self.stroke_smoothing = 0.75          # 0: no smoothing. 1: no change
        
        self.mode_pos        = (0, 0)
        self.cur_pos         = (0, 0)
        self.mode_radius     = 0
        self.action_center   = (0, 0)
        self.action_radius   = 0
        self.is_navigating   = False

        self.post_update = True
        
        # Debug level 2: time start
        check_time = profiler.start()
        self.obj_orig = bpy.data.objects[self.settings.source_object]
        # duplicate selected objected to temporary object but with modifiers applied
        if self.obj_orig.modifiers:
            # Time event
            self.me = self.obj_orig.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
            self.me.update()
            self.obj = bpy.data.objects.new('PolystripsTmp', self.me)
            bpy.context.scene.objects.link(self.obj)
            self.obj.hide = True

            # HACK
            # Comment out for now. Appears to no longer be needed.
            # bpy.ops.object.mode_set(mode='EDIT')
            # bpy.ops.object.mode_set(mode='OBJECT')
            self.obj.matrix_world = self.obj_orig.matrix_world
        else:
            self.obj = self.obj_orig

        # Debug level 2: time end
        check_time.done()


        #Create a new empty destination object for new retopo mesh
        nm_polystrips = self.obj_orig.name + "_edgepatches"
        self.dest_bme = bmesh.new()
        dest_me  = bpy.data.meshes.new(nm_polystrips)
        self.dest_obj = bpy.data.objects.new(nm_polystrips, dest_me)
        self.dest_obj.matrix_world = self.obj.matrix_world
        context.scene.objects.link(self.dest_obj)
        
        self.extension_geometry = []
        self.snap_eds = []
        self.snap_eds_vis = []
        self.hover_ed = None
        
        
        self.scale = self.obj.scale[0]
        self.length_scale = get_object_length_scale(self.obj)
        # World stroke radius
        self.stroke_radius = 0.01 * self.length_scale
        self.stroke_radius_pressure = 0.01 * self.length_scale
        # Screen_stroke_radius
        self.screen_stroke_radius = 20  # TODO, hood to settings

        self.sketch_brush = SketchBrush(context,
                                        self.settings,
                                        0, 0, #event.mouse_region_x, event.mouse_region_y,
                                        15,  # settings.quad_prev_radius,
                                        self.obj)

        self.undo_cache = []            # Clear the cache in case any is left over
        
        self.edgepatches = EdgePatches(context, self.obj, self.dest_obj)
        
        
        # help file stuff
        my_dir = os.path.split(os.path.abspath(__file__))[0]
        filename = os.path.join(my_dir, '..', 'help', 'help_edgepatches.txt')
        if os.path.isfile(filename):
            help_txt = open(filename, mode='r').read()
        else:
            help_txt = "No Help File (%s) found, please reinstall!" % filename
        self.help_box = TextBox(context,500,500,300,200,10,20, help_txt)
        if not self.settings.help_def:
            self.help_box.collapse()
        self.help_box.snap_to_corner(context, corner = [1,1])
        
        context.area.header_text_set('Edge-Patches')
        
        
        self.act_epvert = None
        self.act_epedge = None
        self.sel_epverts = set()
        self.sel_epedges = set()
    
    def end_ui(self, context):
        pass
        
    def cleanup(self, context):
        '''
        remove temporary object
        '''
        dprint('cleaning up!')

        if self.obj_orig.modifiers:
            tmpobj = self.obj  # Not always, sometimes if duplicate remains...will be .001
            meobj  = tmpobj.data

            # Delete object
            context.scene.objects.unlink(tmpobj)
            tmpobj.user_clear()
            if tmpobj.name in bpy.data.objects:
                bpy.data.objects.remove(tmpobj)

            bpy.context.scene.update()
            bpy.data.meshes.remove(meobj)
    
    
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
    

    
    ##############################
    # picking function

    def pick(self, eventd):
        x,y = eventd['mouse']
        pts = common_utilities.ray_cast_path(eventd['context'], self.obj, [(x,y)])
        if not pts:
            # user did not click on the object
            if not eventd['shift']:
                # clear selection if shift is not held
                self.act_epvert,self.act_epedge = None,None
                self.sel_epedges.clear()
                self.sel_epverts.clear()
            return ''
        pt = pts[0]

        # Select EPVert
        for epv,_ in self.edgepatches.pick_epverts(pt, maxdist=self.stroke_radius):
            if epv.is_inner():
                if self.act_epvert:
                    if epv != self.act_epvert and epv not in self.act_epvert.get_inner_epverts():
                        continue
                elif self.act_epedge:
                    if epv not in self.act_epedge.get_inner_epverts():
                        continue
                else:
                    continue
            self.act_epvert = epv
            self.act_epedge = None
            self.sel_epedges.clear()
            self.sel_epverts.clear()
            return ''
        
        # Select EPEdge
        for epe,_ in self.edgepatches.pick_epedges(pt, maxdist=self.stroke_radius):
            self.act_epvert = None
            self.act_epedge = epe
            self.sel_epedges.clear()
            self.sel_epedges.add(epe)
            self.sel_epverts.clear()
            return ''
        
        self.act_epedge,self.act_epvert = None,None
        self.sel_epedges.clear()
        self.sel_epverts.clear()