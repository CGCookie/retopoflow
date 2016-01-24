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
from ..lib.common_utilities import bversion, get_object_length_scale, dprint, frange, selection_mouse, showErrorMessage
from ..lib.common_utilities import get_source_object, get_target_object, setup_target_object
from ..lib.common_utilities import point_inside_loop2d, get_source_object
from ..lib.classes.profiler.profiler import profiler
from ..lib.classes.textbox.textbox import TextBox
from ..lib.classes.sketchbrush.sketchbrush import SketchBrush
from .. import key_maps
from ..cache import mesh_cache, clear_mesh_cache, write_mesh_cache, is_object_valid, edgepatches_undo_cache

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
        
        
        if context.mode == 'OBJECT':
            # Debug level 2: time start
            #check_time = profiler.start()
            self.obj_orig = get_source_object()
            self.mx = self.obj_orig.matrix_world
            is_valid = is_object_valid(self.obj_orig)
            if not is_valid:
                clear_mesh_cache()
                edgepatches_undo_cahce = []           
                me = self.obj_orig.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
                me.update()
                bme = bmesh.new()
                bme.from_mesh(me)
                bvh = BVHTree.FromBMesh(bme)
                write_mesh_cache(self.obj_orig, bme, bvh)
                # Debug level 2: time end
                #check_time.done()


            #Create a new empty destination object for new retopo mesh
            nm_edgepatches= self.obj_orig.name + "_edgepatches"
            self.dest_bme = bmesh.new()
            self.dest_obj = setup_target_object(nm_edgepatches, self.obj_orig, self.dest_bme )
        
            self.extension_geometry = []
            self.snap_eds = []
            self.snap_eds_vis = []
            self.hover_ed = None
        
        elif context.mode == 'EDIT_MESH':
            self.obj_orig = get_source_object()
            self.mx = self.obj_orig.matrix_world
            is_valid = is_object_valid(self.obj_orig)
    
            if is_valid:
                pass
                #self.bme = mesh_cache['bme']            
                #self.bvh = mesh_cache['bvh']
            
            else:
                clear_mesh_cache()
                edgepatches_undo_cahce = []
                me = self.obj_orig.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
                me.update()
            
                bme = bmesh.new()
                bme.from_mesh(me)
                bvh = BVHTree.FromBMesh(bme)
                write_mesh_cache(self.obj_orig, bme, bvh)
            
            self.dest_obj = get_target_object()
            self.dest_bme = bmesh.from_edit_mesh(context.object.data)
            self.snap_eds = [] #EXTEND
                   
            #self.snap_eds = [ed for ed in self.dest_bme.edges if not ed.is_manifold]
            region, r3d = context.region, context.space_data.region_3d
            dest_mx = self.dest_obj.matrix_world
            rv3d = context.space_data.region_3d
            
            #TODO snap_eds_vis?  #careful with the 2 matrices. One is the source object mx, the other is the target object mx
            self.snap_eds_vis = [False not in common_utilities.ray_cast_visible_bvh([dest_mx * ed.verts[0].co, dest_mx * ed.verts[1].co], mesh_cache['bvh'], self.mx, rv3d) for ed in self.snap_eds]
            self.hover_ed = None

            # Hide any existng geometry so as to draw nicely via BmeshRender
            #bpy.ops.mesh.hide(unselected=True)
            #bpy.ops.mesh.hide(unselected=False)
        
        
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

        self.edgepatches = EdgePatches(context, self.obj_orig, self.dest_obj)
        self.edgepatches.extension_geometry_from_bme(self.dest_bme)
        
        
        context.area.header_text_set('Edge-Patches')
        
        self.act_epvert = None
        self.act_epedge = None
        self.act_eppatch = None
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
            pass
            #tmpobj = self.obj  # Not always, sometimes if duplicate remains...will be .001
            #meobj  = tmpobj.data

            # Delete object
            #context.scene.objects.unlink(tmpobj)
            #tmpobj.user_clear()
            #if tmpobj.name in bpy.data.objects:
            #    bpy.data.objects.remove(tmpobj)

            #bpy.context.scene.update()
            #bpy.data.meshes.remove(meobj)
    
    
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
        pts = common_utilities.ray_cast_path(eventd['context'], self.obj_orig, [(x,y)])
        #pts = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'],self.mx, [(x,y)])
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
            self.act_eppatch = None
            self.sel_epedges.clear()
            self.sel_epverts.clear()
            return ''
        
        # Select EPEdge
        for epe,_ in self.edgepatches.pick_epedges(pt, maxdist=self.stroke_radius):
            self.act_epvert = None
            self.act_eppatch = None
            self.act_epedge = epe
            self.sel_epedges.clear()
            self.sel_epedges.add(epe)
            self.sel_epverts.clear()
            return ''
        
        
        #select EPPatch
        lsepp = self.edgepatches.pick_eppatches(eventd['context'], x,y,pt, maxdist=self.stroke_radius)
        if len(lsepp):
            epp, d = lsepp[0]
            self.act_eppatch = epp
            self.act_epvert = None
            self.act_epedge = None
            self.sel_epedges.clear()
            self.sel_epverts.clear()
            return ''
        self.act_epedge,self.act_epvert = None,None
        self.sel_epedges.clear()
        self.sel_epverts.clear()
    
    
    ###########################
    # mesh creation
    
    def create_mesh(self, context):
        
        self.edgepatches.push_into_bmesh(context)
        '''
        verts,edges,ngons = self.edgepatches.create_mesh(self.dest_bme)
        #bm = bmesh.new()  #now new bmesh is created at the start
        mx2 = Matrix.Identity(4)
        imx = Matrix.Identity(4)

        self.dest_obj.update_tag()
        self.dest_obj.show_all_edges = True
        self.dest_obj.show_wire      = True
        self.dest_obj.show_x_ray     = True
     
        self.dest_obj.select = True
        context.scene.objects.active = self.dest_obj
    
        container_bme = bmesh.new()
        
        bmverts = [container_bme.verts.new(imx * mx2 * v) for v in verts]
        container_bme.verts.index_update()
        for edge in edges:
            container_bme.edges.new([bmverts[i] for i in edge])
        for ngon in ngons:
            container_bme.faces.new([bmverts[i] for i in ngon])
        
        container_bme.faces.index_update()

        container_bme.to_mesh(self.dest_obj.data)
        
        self.dest_bme.free()
        container_bme.free()
        '''
    