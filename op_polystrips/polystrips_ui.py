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
from itertools import chain

from ..lib import common_utilities
from ..lib.common_utilities import get_source_object, get_target_object, setup_target_object
from ..lib.common_utilities import bversion, selection_mouse, showErrorMessage
from ..lib.common_utilities import point_inside_loop2d, get_object_length_scale, dprint, frange
from ..lib.common_utilities import ray_cast_region2d_bvh, invert_matrix
from ..lib.common_drawing_bmesh import BMeshRender
from ..lib.classes.profiler.profiler import Profiler
from ..lib.classes.sketchbrush.sketchbrush import SketchBrush
from .. import key_maps
from ..cache import mesh_cache, polystrips_undo_cache, object_validation, is_object_valid, write_mesh_cache, clear_mesh_cache

from .polystrips_datastructure import Polystrips, GVert


class Polystrips_UI:
    def initialize_ui(self):
        self.is_fullscreen  = False
        self.was_fullscreen = False
        
        if 'brush_radius' not in dir(Polystrips_UI):
            Polystrips_UI.brush_radius = 15
    
    
    def start_ui(self, context):
        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_user_keymap_generate()
        
        self.stroke_smoothing = 0.75          # 0: no smoothing. 1: no change
        
        self.mode_pos        = (0, 0)
        self.cur_pos         = (0, 0)
        self.mode_radius     = 0
        self.action_center   = (0, 0)
        self.action_radius   = 0
        self.is_navigating   = False
        self.sketch_curpos   = (0, 0)
        self.sketch          = []
        
        self.act_gvert  = None      # active gvert (operated upon)
        self.act_gedge  = None      # active gedge
        self.act_gpatch = None      # active gpatch
        
        self.sel_gverts = set()     # all selected gverts
        self.sel_gedges = set()     # all selected gedges
        
        self.hov_gvert  = None      # gvert under mouse (hover)
        
        self.tweak_data = None

        self.post_update = True

        if context.mode == 'OBJECT':

            # Debug level 2: time start
            check_time = Profiler().start()

            self.obj_orig = get_source_object()
            self.mx = self.obj_orig.matrix_world
            is_valid = is_object_valid(self.obj_orig)
            if is_valid:
                pass
                #self.bme = mesh_cache['bme']            
                #self.bvh = mesh_cache['bvh']
                
            else:
                clear_mesh_cache()
                polystrips_undo_cache = []
                me = self.obj_orig.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
                me.update()
                bme = bmesh.new()
                bme.from_mesh(me)
                bvh = BVHTree.FromBMesh(bme)
                write_mesh_cache(self.obj_orig, bme, bvh)
                
            # Debug level 2: time end
            check_time.done()

            #Create a new empty destination object for new retopo mesh
            nm_polystrips = self.obj_orig.name + "_polystrips"
            self.dest_bme = bmesh.new()

            self.dest_obj = setup_target_object( nm_polystrips, self.obj_orig, self.dest_bme )

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
                polystrips_undo_cache = []
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
            bpy.ops.mesh.hide(unselected=True)
            bpy.ops.mesh.hide(unselected=False)

        #for bmv in self.dest_bme.verts:
        #    bmv.co = self.mx * bmv.co

        self.scale = self.obj_orig.scale[0]
        self.length_scale = get_object_length_scale(self.obj_orig)
        # World stroke radius
        self.stroke_radius = 0.01 * self.length_scale
        # Screen_stroke_radius
        self.screen_stroke_radius = 20  # TODO, hook to settings

        self.sketch_brush = SketchBrush(context,
                                        self.settings,
                                        0, 0, #event.mouse_region_x, event.mouse_region_y,
                                        Polystrips_UI.brush_radius,  # settings.quad_prev_radius,
                                        mesh_cache['bvh'], self.mx,
                                        self.obj_orig.dimensions.length)

        self.polystrips = Polystrips(context, self.obj_orig, self.dest_obj)
        self.polystrips.extension_geometry_from_bme(self.dest_bme)
        
        if self.obj_orig.grease_pencil:
            self.create_polystrips_from_greasepencil()
        elif 'BezierCurve' in bpy.data.objects:
            self.create_polystrips_from_bezier(bpy.data.objects['BezierCurve'])

        if not self.is_fullscreen:
            was_fullscreen = len(context.screen.areas)==1
            if not was_fullscreen and self.settings.distraction_free:
                bpy.ops.screen.screen_full_area(use_hide_panels=True)
            self.is_fullscreen = True

        # Draw the existing bmesh geometry in our own style
        self.tar_bmeshrender = BMeshRender(self.dest_bme, self.mx)

        context.area.header_text_set('Polystrips')
    
    def end_ui(self, context):
        if not self.was_fullscreen and self.settings.distraction_free:
            bpy.ops.screen.screen_full_area(use_hide_panels=True)
            self.is_fullscreen = False
        
        Polystrips_UI.brush_radius = self.sketch_brush.pxl_rad
        
    def cleanup(self, context, cleantype=''):
        '''
        remove temporary object
        '''
        dprint('cleaning up!')
        if cleantype == 'commit':
            pass

        elif cleantype == 'cancel':
            if context.mode == 'OBJECT' and not self.settings.target_object:
                context.scene.objects.unlink(self.dest_obj)
                self.dest_obj.data.user_clear()
                bpy.data.meshes.remove(self.dest_obj.data)
                bpy.data.objects.remove(self.dest_obj)
            elif context.mode == 'EDIT_MESH':
                bpy.ops.mesh.reveal()

    ###############################
    # undo functions
    
    def create_undo_snapshot(self, action):
        '''
        unsure about all the _timers get deep copied
        and if sel_gedges and verts get copied as references
        or also duplicated, making them no longer valid.
        '''

        repeated_actions = {'count', 'zip count'}

        if action in repeated_actions and len(polystrips_undo_cache):
            if action == polystrips_undo_cache[-1]['action']:
                dprint('repeatable...dont take snapshot')
                return

        polystrips_undo_cache.append({
            'action': action,
            'polystrips data': copy.deepcopy(self.polystrips),
            'act_gvert': self.polystrips.gverts.index(self.act_gvert) if self.act_gvert else None,
            'act_gedge': self.polystrips.gedges.index(self.act_gedge) if self.act_gedge else None,
            'act_gpatch': self.polystrips.gpatches.index(self.act_gpatch) if self.act_gpatch else None,
            'sel_gverts': [self.polystrips.gverts.index(gv) for gv in self.sel_gverts],
            'sel_gedges': [self.polystrips.gedges.index(ge) for ge in self.sel_gedges],
        })

        if len(polystrips_undo_cache) > self.settings.undo_depth:
            polystrips_undo_cache.pop(0)

    def undo_action(self):
        if len(polystrips_undo_cache) == 0:
            return
        data = polystrips_undo_cache.pop()
        self.polystrips = data['polystrips data']
        self.act_gvert = self.polystrips.gverts[data['act_gvert']] if data['act_gvert'] is not None else None
        self.act_gedge = self.polystrips.gedges[data['act_gedge']] if data['act_gedge'] is not None else None
        self.act_gpatch = self.polystrips.gpatches[data['act_gpatch']] if data['act_gpatch'] is not None else None
        self.sel_gverts = set(self.polystrips.gverts[i] for i in data['sel_gverts'])
        self.sel_gedges = set(self.polystrips.gedges[i] for i in data['sel_gedges'])
        self.hov_gvert = None
    

    
    ###########################
    # mesh creation
    
    def create_mesh(self, context):
        self.settings = common_utilities.get_settings()
        verts,quads,non_quads = self.polystrips.create_mesh(self.dest_bme)

        if 'EDIT' in context.mode:  #self.dest_bme and self.dest_obj:  #EDIT MODE on Existing Mesh
            mx = self.dest_obj.matrix_world
            imx = invert_matrix(mx)

            mx2 = self.obj_orig.matrix_world
            imx2 = invert_matrix(mx2)

        else:
            #bm = bmesh.new()  #now new bmesh is created at the start
            mx2 = Matrix.Identity(4)
            imx = Matrix.Identity(4)

            self.dest_obj.update_tag()
            self.dest_obj.show_all_edges = True
            self.dest_obj.show_wire      = True
            self.dest_obj.show_x_ray     = self.settings.use_x_ray

            self.dest_obj.select = True
            context.scene.objects.active = self.dest_obj

            common_utilities.default_target_object_to_active()

        # check for symmetry and then add a mirror if needed
        if self.settings.symmetry_plane == 'x':
            if not self.dest_obj.modifiers:
                self.dest_obj.modifiers.new(type='MIRROR', name='Polystrips-Symmetry')
                self.dest_obj.modifiers['Polystrips-Symmetry'].use_clip = True
            else:
                for mod in self.dest_obj.modifiers:
                    if mod.type == 'MIRROR':
                        print('Mirror found! Skipping')
                        break
                    else:
                        print("Let's add a new mirror mod")
                        self.dest_obj.modifiers.new(type='MIRROR', name='Polystrips-Symmetry')
                        self.dest_obj.modifiers['Polystrips-Symmetry'].use_clip = True

        container_bme = bmesh.new()
        
        bmverts = [container_bme.verts.new(imx * mx2 * v) for v in verts]
        container_bme.verts.index_update()
        for q in quads: 
            try:
                container_bme.faces.new([bmverts[i] for i in q])
            except ValueError as e:
                dprint('ValueError: ' + str(e))
                pass
        for nq in non_quads:
            container_bme.faces.new([bmverts[i] for i in nq])
        
        container_bme.faces.index_update()

        if 'EDIT' in context.mode: #self.dest_bme and self.dest_obj:
            bpy.ops.object.mode_set(mode='OBJECT')
            container_bme.to_mesh(self.dest_obj.data)
            bpy.ops.object.mode_set(mode = 'EDIT')
            #bmesh.update_edit_mesh(self.dest_obj.data, tessface=False, destructive=True)
        else: 
            container_bme.to_mesh(self.dest_obj.data)
        
        self.dest_bme.free()
        container_bme.free()

    ###########################
    # fill function

    def fill(self, eventd):
        
        # GVert active
        if self.act_gvert:
            showErrorMessage('Not supported at the moment.')
            return
            lges = self.act_gvert.get_gedges()
            if self.act_gvert.is_ljunction():
                lgepairs = [(lges[0],lges[1])]
            elif self.act_gvert.is_tjunction():
                lgepairs = [(lges[0],lges[1]), (lges[3],lges[0])]
            elif self.act_gvert.is_cross():
                lgepairs = [(lges[0],lges[1]), (lges[1],lges[2]), (lges[2],lges[3]), (lges[3],lges[0])]
            else:
                showErrorMessage('GVert must be a L-junction, T-junction, or Cross type to use simple fill')
                return
            
            # find gedge pair that is not a part of a gpatch
            lgepairs = [(ge0,ge1) for ge0,ge1 in lgepairs if not set(ge0.gpatches).intersection(set(ge1.gpatches))]
            if not lgepairs:
                showErrorMessage('Could not find two GEdges that are not already patched')
                return
            
            self.sel_gedges = set(lgepairs[0])
            self.act_gedge = next(iter(self.sel_gedges))
            self.act_gvert = None
        
        lgpattempt = self.polystrips.attempt_gpatch(self.sel_gedges)
        if type(lgpattempt) is str:
            showErrorMessage(lgpattempt)
            return
        lgp = lgpattempt
        
        self.act_gvert = None
        self.act_gedge = None
        self.sel_gedges.clear()
        self.sel_gverts.clear()
        self.act_gpatch = lgp[0]
        
        for gp in lgp:
            gp.update()
        #self.polystrips.update_visibility(eventd['r3d'])



    ###########################
    # hover functions

    def hover_geom(self,eventd):
        mx,my = eventd['mouse'] 
        rgn   = eventd['context'].region
        r3d   = eventd['context'].space_data.region_3d
        
        self.help_box.hover(mx, my)
        
        self.hov_gvert = None
        _,hit = ray_cast_region2d_bvh(rgn, r3d, (mx,my), mesh_cache['bvh'], self.mx, self.settings)
        hit_pos,hit_norm,_ = hit
        for gv in chain(self.polystrips.extension_geometry, self.polystrips.gverts):
            if gv.is_inner(): continue
            c0 = location_3d_to_region_2d(rgn, r3d, gv.corner0)
            c1 = location_3d_to_region_2d(rgn, r3d, gv.corner1)
            c2 = location_3d_to_region_2d(rgn, r3d, gv.corner2)
            c3 = location_3d_to_region_2d(rgn, r3d, gv.corner3)
            inside = point_inside_loop2d([c0,c1,c2,c3],Vector((mx,my)))
            if hit_pos: inside &= gv.is_picked(hit_pos, hit_norm)
            if inside:
                self.hov_gvert = gv
                break
                print('found hover gv')
    

    ##############################
    # picking function

    def pick(self, eventd):
        mx,my = eventd['mouse']
        rgn   = eventd['context'].region
        r3d   = eventd['context'].space_data.region_3d
        _,hit = ray_cast_region2d_bvh(rgn, r3d, (mx,my), mesh_cache['bvh'], self.mx, self.settings)
        hit_pos,hit_norm,_ = hit
        if not hit_pos:
            # user did not click on the object
            if not eventd['shift']:
                # clear selection if shift is not held
                self.act_gvert,self.act_gedge,self.act_gvert = None,None,None
                self.sel_gedges.clear()
                self.sel_gverts.clear()
            return ''

        if self.act_gvert or self.act_gedge:
            # check if user is picking an inner control point
            if self.act_gedge and not self.act_gedge.zip_to_gedge:
                lcpts = [self.act_gedge.gvert1,self.act_gedge.gvert2]
            elif self.act_gvert:
                sgv = self.act_gvert
                lge = self.act_gvert.get_gedges()
                lcpts = [ge.get_inner_gvert_at(sgv) for ge in lge if ge and not ge.zip_to_gedge] + [sgv]
            else:
                lcpts = []

            for cpt in lcpts:
                if not cpt.is_picked(hit_pos,hit_norm): continue
                self.act_gedge = None
                self.sel_gedges.clear()
                self.act_gvert = cpt
                self.sel_gverts = set([cpt])
                self.act_gpatch = None
                return ''
        
        # select gvert?
        for gv in self.polystrips.gverts:
            if gv.is_unconnected(): continue
            if not gv.is_picked(hit_pos,hit_norm): continue
            self.act_gedge = None
            self.sel_gedges.clear()
            self.sel_gverts.clear()
            self.act_gvert = gv
            self.act_gpatch = None
            return ''

        # select gedge?
        for ge in self.polystrips.gedges:
            if not ge.is_picked(hit_pos,hit_norm): continue
            self.act_gvert = None
            self.act_gedge = ge
            if not eventd['shift']:
                self.sel_gedges.clear()
            self.sel_gedges.add(ge)
            self.sel_gverts.clear()
            self.act_gpatch = None
            
            for ge in self.sel_gedges:
                if ge == self.act_gedge: continue
                self.sel_gverts.add(ge.gvert0)
                self.sel_gverts.add(ge.gvert3)
            
            return ''
        
        # Select patch
        for gp in self.polystrips.gpatches:
            if not gp.is_picked(hit_pos,hit_norm): continue
            self.act_gvert = None
            self.act_gedge = None
            self.sel_gedges.clear()
            self.sel_gverts.clear()
            self.act_gpatch = gp
            return ''
        
        if not eventd['shift']:
            self.act_gedge,self.act_gvert,self.act_gpatch = None,None,None
            self.sel_gedges.clear()
            self.sel_gverts.clear()

    ###########################################################
    # functions to convert beziers and gpencils to polystrips

    def create_polystrips_from_bezier(self, ob_bezier):
        data  = ob_bezier.data
        mx    = ob_bezier.matrix_world

        def create_gvert(self, mx, co, radius):
            p0  = mx * co
            r0  = radius
            n0  = Vector((0,0,1))
            tx0 = Vector((1,0,0))
            ty0 = Vector((0,1,0))
            return GVert(self.obj_orig,self.dest_obj, p0,r0,n0,tx0,ty0)

        for spline in data.splines:
            pregv = None
            for bp0,bp1 in zip(spline.bezier_points[:-1],spline.bezier_points[1:]):
                gv0 = pregv if pregv else self.create_gvert(mx, bp0.co, 0.2)
                gv1 = self.create_gvert(mx, bp0.handle_right, 0.2)
                gv2 = self.create_gvert(mx, bp1.handle_left, 0.2)
                gv3 = self.create_gvert(mx, bp1.co, 0.2)

                ge0 = GEdge(self.obj_orig, self.dest_obj, gv0, gv1, gv2, gv3)
                ge0.recalc_igverts_approx()
                ge0.snap_igverts_to_object()

                if pregv:
                    self.polystrips.gverts += [gv1,gv2,gv3]
                else:
                    self.polystrips.gverts += [gv0,gv1,gv2,gv3]
                self.polystrips.gedges += [ge0]
                pregv = gv3

    def create_polystrips_from_greasepencil(self):
        Mx = self.obj_orig.matrix_world
        gp = self.obj_orig.grease_pencil
        gp_layers = gp.layers
        # for gpl in gp_layers: gpl.hide = True
        strokes = [[(p.co,p.pressure) for p in stroke.points] for layer in gp_layers for frame in layer.frames for stroke in frame.strokes]
        self.strokes_original = strokes

        #for stroke in strokes:
        #    self.polystrips.insert_gedge_from_stroke(stroke)



