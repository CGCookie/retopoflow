'''
Copyright (C) 2013 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Patrick Moore

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

# System imports
import copy
import math
import time
from mathutils import Vector, Quaternion
from mathutils.geometry import intersect_point_line, intersect_line_plane

# Blender imports
import bgl
import blf
import bmesh
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d, region_2d_to_origin_3d

# Common imports
from . import contour_utilities
from .lib import common_utilities, common_drawing
from .cache import contour_mesh_cache, contour_undo_cache
#from development.cgc-retopology import contour_utilities

#Make the addon name and location accessible
AL = common_utilities.AddonLocator()

def object_validation(ob):
    me = ob.data
    # get object data to act as a hash
    counts = (len(me.vertices), len(me.edges), len(me.polygons), len(ob.modifiers))
    bbox   = (tuple(min(v.co for v in me.vertices)), tuple(max(v.co for v in me.vertices)))
    vsum   = tuple(sum((v.co for v in me.vertices), Vector((0,0,0))))
    return (ob.name, counts, bbox, vsum)

def is_object_valid(ob):
    if 'valid' not in contour_mesh_cache: return False
    return contour_mesh_cache['valid'] == object_validation(ob)

def write_mesh_cache(orig_ob,tmp_ob, bme):
    print('writing mesh cache')
    contour_mesh_cache['valid'] = object_validation(orig_ob)
    contour_mesh_cache['bme'] = bme
    contour_mesh_cache['tmp'] = tmp_ob

def clear_mesh_cache():
    print('clearing mesh cache')
    if 'valid' in contour_mesh_cache and contour_mesh_cache['valid']:
        del contour_mesh_cache['valid']

    if 'bme' in contour_mesh_cache and contour_mesh_cache['bme']:
        bme_old = contour_mesh_cache['bme']
        bme_old.free()
        del contour_mesh_cache['bme']

    if 'tmp' in contour_mesh_cache and contour_mesh_cache['tmp']:
        old_obj = contour_mesh_cache['tmp']
        #context.scene.objects.unlink(self.tmp_ob)
        old_me = old_obj.data
        old_obj.user_clear()
        if old_obj and old_obj.name in bpy.data.objects:
            bpy.data.objects.remove(old_obj)
        if old_me and old_me.name in bpy.data.meshes:
            bpy.data.meshes.remove(old_me)
        del contour_mesh_cache['tmp']

class Contours(object):
    def __init__(self,context, settings):
        self.settings = settings
        
        self.verts = []
        self.edges = []
        self.faces = []
        
        self.cut_lines = []
        self.cut_paths = []
        self.sketch = []
        
        self.mode = 'loop'
        self.hover_target = None
        self.sel_loop = None
        self.force_new = False
        
        self.stroke_smoothing = .5
        self.segments = settings.vertex_count
        self.guide_cuts = settings.ring_count
        
        if context.mode == 'OBJECT':
            self.mesh_data_gather_object_mode(context)
        elif 'EDIT' in context.mode:
            self.mesh_data_gather_edit_mode(context) 
            
        #potential item for snapping in 
        self.snap = []
        self.snap_circle = []
        
        handle_color = settings.theme_colors_active[settings.theme]
        self.snap_color = (handle_color[0], handle_color[1], handle_color[2], 1.00)
   
        if len(self.cut_paths) == 0:
            self.sel_path = None   #TODO: change this to selected_segment
        else:
            self.sel_path = self.cut_paths[-1] #this would be an existing path from selected geom in editmode
        
        self.cut_line_widget = None  #An object of Class "CutLineManipulator" or None
        self.widget_interaction = False  #Being in the state of interacting with a widget o
        self.hot_key = None  #Keep track of which hotkey was pressed
        self.draw = False  #Being in the state of drawing a guide stroke
        self.last_matrix = None
              
    def new_destination_obj(self,context,name, mx):
        '''
        creates new object for mesh data to enter
        '''
        dest_me = bpy.data.meshes.new(name)
        dest_ob = bpy.data.objects.new(name,dest_me) #this is an empty currently
        dest_ob.matrix_world = mx
        dest_ob.update_tag()
        dest_bme = bmesh.new()
        dest_bme.from_mesh(dest_me)
        
        return dest_ob, dest_me, dest_bme
    
    def tmp_obj_and_triangulate(self,context, bme, ngons, mx):
        '''
        ob -  input object
        bme - bmesh extracted from input object <- this will be modified by triangulation
        ngons - list of bmesh faces that are ngons
        '''
        
        if len(ngons):
            new_geom = bmesh.ops.triangulate(bme, faces = ngons, quad_method=0, ngon_method=1)
            new_faces = new_geom['faces']

        new_me = bpy.data.meshes.new('tmp_recontour_mesh')
        bme.to_mesh(new_me)
        new_me.update()
        tmp_ob = bpy.data.objects.new('ContourTMP', new_me)
        
        #ob must be linked to scene for ray casting?
        context.scene.objects.link(tmp_ob)
        tmp_ob.update_tag()
        context.scene.update()
        #however it can be unlinked to prevent user from seeing it?
        context.scene.objects.unlink(tmp_ob)
        tmp_ob.matrix_world = mx
        
        return tmp_ob
    
    def mesh_data_gather_object_mode(self,context):
        '''
        get references to object and object data
        '''
        
        self.sel_edge = None
        self.sel_verts = None
        self.existing_cut = None
        ob = context.object
        tmp_ob = None
        
        name = ob.name + '_recontour'
        self.dest_ob, self.dest_me, self.dest_bme = self.new_destination_obj(context, name, ob.matrix_world)
        
        
        is_valid = is_object_valid(context.object)
        has_tmp = 'ContourTMP' in bpy.data.objects and bpy.data.objects['ContourTMP'].data
        
        if is_valid and has_tmp:
            self.bme = contour_mesh_cache['bme']            
            tmp_ob = contour_mesh_cache['tmp']
            
        else:
            clear_mesh_cache()
            
            me = ob.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
            me.update()
            
            self.bme = bmesh.new()
            self.bme.from_mesh(me)
            ngons = [f for f in self.bme.faces if len(f.verts) > 4]
            if len(ngons) or len(ob.modifiers) > 0:
                tmp_ob= self.tmp_obj_and_triangulate(context, self.bme, ngons, ob.matrix_world)
                
        if tmp_ob:
            self.original_form = tmp_ob
        else:
            self.original_form = ob
        
        if self.settings.recover and is_valid:
            print('loading cache!')
            self.undo_action()
            return
        else:
            print('no recover or not valid or something')
            global contour_undo_cache
            contour_undo_cache = []
            
        write_mesh_cache(ob,tmp_ob, self.bme)
    
    def mesh_data_gather_edit_mode(self,context):
        '''
        get references to object and object data
        '''
        
        self.dest_ob = context.object        
        self.dest_me = self.dest_ob.data
        self.dest_bme = bmesh.from_edit_mesh(self.dest_me)
        
        ob = [obj for obj in context.selected_objects if obj.name != context.object.name][0]
        is_valid = is_object_valid(ob)
        tmp_ob = None
        
        
        if is_valid:
            self.bme = contour_mesh_cache['bme']            
            tmp_ob = contour_mesh_cache['tmp']
        else:
            clear_mesh_cache()
            me = ob.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
            me.update()
            
            self.bme = bmesh.new()
            self.bme.from_mesh(me)
            ngons = [f for f in self.bme.faces if len(f.verts) > 4]
            if len(ngons) or len(ob.modifiers) > 0:
                tmp_ob = self.tmp_obj_and_triangulate(context, self.bme, ngons, ob.matrix_world)
        
        if tmp_ob:
            print('Load form cache tmp obj, original form set')
            self.original_form = tmp_ob
        else:
            print('Load new obj, original form set')
            self.original_form = ob
        
        self.tmp_ob = tmp_ob
        
        if self.settings.recover and is_valid:
            print('loading cache!')
            self.undo_action()
            return
        
        else:
            global contour_undo_cache
            contour_undo_cache = []
            
            
        #count and collect the selected edges if any
        ed_inds = [ed.index for ed in self.dest_bme.edges if ed.select and len(ed.link_faces) < 2]
        
        self.existing_loops = []
        if len(ed_inds):
            vert_loops = contour_utilities.edge_loops_from_bmedges(self.dest_bme, ed_inds)

            if len(vert_loops) > 1:
                print('there are %i edge loops selected' % len(vert_loops))
            
            for loop in vert_loops: #multi loop support
            #loop = vert_loops[0] #until multi loops are supported, do this 
                if loop[-1] != loop[0] and len(list(set(loop))) != len(loop):
                    print('Edge loop selection has extra parts!  Excluding this loop')
                    
                else:
                    lverts = [self.dest_bme.verts[i] for i in loop]
                    
                    existing_loop =ExistingVertList(context,
                                                    lverts, 
                                                    loop, 
                                                    self.dest_ob.matrix_world,
                                                    key_type = 'INDS')
                    
                    #make a blank path with just an existing head
                    path = ContourCutSeries(context, [],
                                    cull_factor = self.settings.cull_factor, 
                                    smooth_factor = self.settings.smooth_factor,
                                    feature_factor = self.settings.feature_factor)
                
                    
                    path.existing_head = existing_loop
                    path.seg_lock = False
                    path.ring_lock = True
                    path.ring_segments = len(existing_loop.verts_simple)
                    path.connect_cuts_to_make_mesh(ob)
                    path.update_visibility(context, ob)
                
                    #path.update_visibility(context, self.original_form)
                    
                    self.cut_paths.append(path)
                    self.existing_loops.append(existing_loop)
        
        write_mesh_cache(ob,tmp_ob, self.bme)        
            
    def finish_mesh(self, context):
        back_to_edit = (context.mode == 'EDIT_MESH')
                    
        #This is where all the magic happens
        print('pushing data into bmesh')
        for path in self.cut_paths:
            path.push_data_into_bmesh(context, self.dest_ob, self.dest_bme, self.original_form, self.dest_me)
        
        if back_to_edit:
            print('updating edit mesh')
            bmesh.update_edit_mesh(self.dest_me, tessface=False, destructive=True)
        
        else:
            #write the data into the object
            print('write data into the object')
            self.dest_bme.to_mesh(self.dest_me)
        
            #remember we created a new object
            print('link destination object')
            context.scene.objects.link(self.dest_ob)
            
            print('select and make active')
            self.dest_ob.select = True
            context.scene.objects.active = self.dest_ob
            
            if context.space_data.local_view:
                view_loc = context.space_data.region_3d.view_location.copy()
                view_rot = context.space_data.region_3d.view_rotation.copy()
                view_dist = context.space_data.region_3d.view_distance
                bpy.ops.view3d.localview()
                bpy.ops.view3d.localview()
                #context.space_data.region_3d.view_matrix = mx_copy
                context.space_data.region_3d.view_location = view_loc
                context.space_data.region_3d.view_rotation = view_rot
                context.space_data.region_3d.view_distance = view_dist
                context.space_data.region_3d.update()
    
        return
    
    def create_undo_snapshot(self, action):
        '''
        saves data and operator state snapshot
        for undoing
        
        TODO:  perhaps pop/append are not fastest way
        deque?
        prepare a list and keep track of which entity to
        replace?
        '''
        
        repeated_actions = {'LOOP_SHIFT', 'PATH_SHIFT', 'PATH_SEGMENTS', 'LOOP_SEGMENTS'}
        
        if action in repeated_actions:
            if action == contour_undo_cache[-1][2]:
                print('repeatable...dont take snapshot')
                return
        
        print('undo: ' + action)    
        cut_data = copy.deepcopy(self.cut_paths)
        #perhaps I don't even need to copy this?
        state = copy.deepcopy(ContourStatePreserver(self))
        contour_undo_cache.append((cut_data, state, action))
            
        if len(contour_undo_cache) > self.settings.undo_depth:
            contour_undo_cache.pop(0)
            
    def undo_action(self):
        if len(contour_undo_cache) > 0:
            cut_data, op_state, action = contour_undo_cache.pop()
            
            self.cut_paths = cut_data
            op_state.push_state(self)
        
    def new_path_from_draw(self,context,settings):
        '''
        package all the steps needed to make a new path
        TODO: What if errors?
        '''
        path = ContourCutSeries(context, self.sketch,
                                    segments = settings.ring_count,
                                    ring_segments = settings.vertex_count,
                                    cull_factor = settings.cull_factor, 
                                    smooth_factor = settings.smooth_factor,
                                    feature_factor = settings.feature_factor)
        
        
        path.ray_cast_path(context, self.original_form)
        if len(path.raw_world) == 0:
            print('NO RAW PATH')
            return None
        
        self.create_undo_snapshot('NEW_PATH')
        path.find_knots()
        
        if self.snap != [] and not self.force_new:
            merge_series = self.snap[0]
            merge_ring = self.snap[1]
            
            path.snap_merge_into_other(merge_series, merge_ring, context, self.original_form, self.bme)
            
            return merge_series

        path.smooth_path(context, ob = self.original_form)
        path.create_cut_nodes(context)
        path.snap_to_object(self.original_form, raw = False, world = False, cuts = True)
        path.cuts_on_path(context, self.original_form, self.bme)
        path.connect_cuts_to_make_mesh(self.original_form)
        path.backbone_from_cuts(context, self.original_form, self.bme)
        path.update_visibility(context, self.original_form)
        if path.cuts:
            # TODO: should this ever be empty?
            path.cuts[-1].do_select(self.settings)
        
        self.cut_paths.append(path)
        return path

    def sketch_confirm(self,context):
        #make sure we meant it
        if len(self.sketch) < 10:
            print('too short!')
            return
        
        for path in self.cut_paths:
            path.deselect(self.settings)
        
        print('attempt a new path')                    
        self.sel_path  = self.new_path_from_draw(context, self.settings)
        if self.sel_path:
            print('a new path was made')
            self.sel_path.do_select(self.settings)
            if self.sel_path.cuts:
                self.sel_cut = self.sel_path.cuts[-1]
            else:
                self.sel_cut = None
            if self.sel_cut:
                self.sel_cut.do_select(self.settings)
        self.force_new = False
        print('we deselected everyting')
        self.sketch = []
 
    def click_new_cut(self,context, settings, x,y):
        self.create_undo_snapshot('NEW')
        stroke_color = settings.theme_colors_active[settings.theme]
        mesh_color = settings.theme_colors_mesh[settings.theme]

        new_cut = ContourCutLine(x, y)
        
        for path in self.cut_paths:
            for cut in path.cuts:
                cut.deselect(settings)
                
        new_cut.do_select(settings)
        self.cut_lines.append(new_cut)
        
        return new_cut
           
    def release_place_cut(self,context,settings, x, y):

        self.sel_loop.tail.x = x
        self.sel_loop.tail.y = y

        width = Vector((self.sel_loop.head.x, self.sel_loop.head.y)) - Vector((x,y))

        #prevent small errant strokes
        if width.length in range(5, 20): #TODO: Setting for minimum pixel width
            self.cut_lines.remove(self.sel_loop)
            self.sel_loop = None
            showErrorMessage('The drawn cut must be more than 20 pixels')
            return

        elif width.length < 5:
            self.cut_lines.remove(self.sel_loop)
            # self.sel_loop = None
            return
        else: 
            #hit the mesh for the first time
            hit = self.sel_loop.hit_object(context, self.original_form, method = 'VIEW')

            if not hit:
                self.cut_lines.remove(self.sel_loop)
                self.sel_loop = None
                showErrorMessage('The middle of the cut must be over the object!')

                return

            self.sel_loop.cut_object(context, self.original_form, self.bme)
            self.sel_loop.simplify_cross(self.segments)
            self.sel_loop.update_com()
            self.sel_loop.update_screen_coords(context)
            self.sel_loop.head = None
            self.sel_loop.tail = None

            if not len(self.sel_loop.verts) or not len(self.sel_loop.verts_simple):
                self.sel_loop = None
                showErrorMessage('The cut failed for some reason, most likely topology, try again and report bug')
                return


            if settings.debug > 1:
                print('release_place_cut')
                print('len(self.cut_paths) = %d' % len(self.cut_paths))
                print('self.force_new = ' + str(self.force_new))

            if self.cut_paths != [] and not self.force_new:
                for path in self.cut_paths:
                    if path.insert_new_cut(context, self.original_form, self.bme, self.sel_loop, search = settings.search_factor):
                        #the cut belongs to the series now
                        path.connect_cuts_to_make_mesh(self.original_form)
                        path.update_visibility(context, self.original_form)
                        path.seg_lock = True
                        path.do_select(settings)
                        path.unhighlight(settings)
                        self.sel_path = path
                        self.cut_lines.remove(self.sel_loop)
                        for other_path in self.cut_paths:
                            if other_path != self.sel_path:
                                other_path.deselect(settings)
                        # no need to search for more paths
                        return

            #create a blank segment
            path = ContourCutSeries(context, [],
                            cull_factor = settings.cull_factor,
                            smooth_factor = settings.smooth_factor,
                            feature_factor = settings.feature_factor)

            path.insert_new_cut(context, self.original_form, self.bme, self.sel_loop, search = settings.search_factor)
            path.seg_lock = False  #not locked yet...not until a 2nd cut is added in loop mode
            path.segments = 1
            path.ring_segments = len(self.sel_loop.verts_simple)
            path.connect_cuts_to_make_mesh(self.original_form)
            path.update_visibility(context, self.original_form)

            for other_path in self.cut_paths:
                other_path.deselect(settings)

            self.cut_paths.append(path)
            self.sel_path = path
            path.do_select(settings)

            self.cut_lines.remove(self.sel_loop)
            self.force_new = False

            return

    #### Hover and Selection####
    def hover_guide_mode(self,context, settings, x, y):
        '''
        handles mouse selection, hovering, highlighting
        and snapping when the mouse moves in guide
        mode
        '''
        
        handle_color = settings.theme_colors_active[settings.theme]

        #identify hover target for highlighting
        if self.cut_paths != []:
            target_at_all = False
            breakout = False
            for path in self.cut_paths:
                if not path.select:
                    path.unhighlight(settings)
                for c_cut in path.cuts:                    
                    h_target = c_cut.active_element(context,x,y)
                    if h_target:
                        path.highlight(settings)
                        target_at_all = True
                        self.hover_target = path
                        breakout = True
                        break
                
                if breakout:
                    break
                                  
            if not target_at_all:
                self.hover_target = None
        
        #assess snap points
        if self.cut_paths != [] and not self.force_new:
            rv3d = context.space_data.region_3d
            breakout = False
            snapped = False
            for path in self.cut_paths:
                
                end_cuts = []
                if not path.existing_head and len(path.cuts):
                    end_cuts.append(path.cuts[0])
                if not path.existing_tail and len(path.cuts):
                    end_cuts.append(path.cuts[-1])
                    
                if path.existing_head and not len(path.cuts):
                    end_cuts.append(path.existing_head)
                    
                for n, end_cut in enumerate(end_cuts):
                    
                    #potential verts to snap to
                    snaps = [v for i, v in enumerate(end_cut.verts_simple) if end_cut.verts_simple_visible[i]]
                    #the screen versions os those
                    screen_snaps = [location_3d_to_region_2d(context.region,rv3d,snap) for snap in snaps]
                    
                    mouse = Vector((x,y))
                    dists = [(mouse - snap).length for snap in screen_snaps]
                    
                    if len(dists):
                        best = min(dists)
                        if best < 2 * settings.extend_radius and best > 4: #TODO unify selection mouse pixel radius.

                            best_vert = screen_snaps[dists.index(best)]
                            view_z = rv3d.view_rotation * Vector((0,0,1))
                            if view_z.dot(end_cut.plane_no) > -.75 and view_z.dot(end_cut.plane_no) < .75:

                                imx = rv3d.view_matrix.inverted()
                                normal_3d = imx.transposed() * end_cut.plane_no
                                if n == 1 or len(end_cuts) == 1:
                                    normal_3d = -1 * normal_3d
                                screen_no = Vector((normal_3d[0],normal_3d[1]))
                                angle = math.atan2(screen_no[1],screen_no[0]) - 1/2 * math.pi
                                left = angle + math.pi
                                right =  angle
                                self.snap = [path, end_cut]
                                
                                if end_cut.desc == 'CUT_LINE' and len(path.cuts) > 1:
    
                                    self.snap_circle = contour_utilities.pi_slice(best_vert[0],best_vert[1],settings.extend_radius,.1 * settings.extend_radius, left,right, 20,t_fan = True)
                                    self.snap_circle.append(self.snap_circle[0])
                                else:
                                    self.snap_circle = contour_utilities.simple_circle(best_vert[0], best_vert[1], settings.extend_radius, 20)
                                    self.snap_circle.append(self.snap_circle[0])
                                    
                                breakout = True
                                if best < settings.extend_radius:
                                    snapped = True
                                    self.snap_color = (handle_color[0], handle_color[1], handle_color[2], 1.00)
                                    
                                else:
                                    alpha = 1 - best/(2*settings.extend_radius)
                                    self.snap_color = (handle_color[0], handle_color[1], handle_color[2], 0.50)
                                    
                                break
                        
                    if breakout:
                        break
                    
            if not breakout:
                self.snap = []
                self.snap_circle = []
                
    def hover_loop_mode(self,context, settings, x,y):
        '''
        Handles mouse selection and hovering
        '''
        #identify hover target for highlighting
        if self.cut_paths != []:
            new_target = False
            target_at_all = False
            
            for path in self.cut_paths:
                for c_cut in path.cuts:
                    if not c_cut.select:
                        c_cut.unhighlight(settings) 
                    
                    h_target = c_cut.active_element(context,x,y)
                    if h_target:
                        c_cut.highlight(settings)
                        target_at_all = True
                         
                        if (h_target != self.hover_target) or (h_target.select and not self.cut_line_widget):
                            
                            self.hover_target = h_target
                            if self.hover_target.desc == 'CUT_LINE':

                                if self.hover_target.select:
                                    for possible_parent in self.cut_paths:
                                        if self.hover_target in possible_parent.cuts:
                                            parent_path = possible_parent
                                            break
                                    
                                    #spawn a new widget        
                                    self.cut_line_widget = CutLineManipulatorWidget(context, 
                                                                                    settings,
                                                                                    self.original_form, self.bme,
                                                                                    self.hover_target,
                                                                                    parent_path,
                                                                                    x,
                                                                                    y)
                                    self.cut_line_widget.derive_screen(context)
                                
                                else:
                                    self.cut_line_widget = None
                            
                        else:
                            if self.cut_line_widget:
                                self.cut_line_widget.x = x
                                self.cut_line_widget.y = y
                                self.cut_line_widget.derive_screen(context)
                    #elif not c_cut.select:
                        #c_cut.geom_color = (settings.geom_rgb[0],settings.geom_rgb[1],settings.geom_rgb[2],1)          
            if not target_at_all:
                self.hover_target = None
                self.cut_line_widget = None    

    #### Non Interactive/Non Data Operators###
    
    def mode_set_guide(self):
        self.sel_loop = None  #because loop may not exist after path level operations like changing n_rings
        if self.sel_path:
            self.sel_path.highlight(self.settings)  
    
    def mode_set_loop(self):
        for path in self.cut_paths:
            for cut in path.cuts:
                cut.deselect(self.settings)
        if self.sel_path and len(self.sel_path.cuts):
            self.sel_loop = self.sel_path.cuts[-1]
            self.sel_path.cuts[-1].do_select(self.settings)
        
    #### Segment Operators####
    
    def segment_shift(self,context, up = True, s = 0.05):
        self.create_undo_snapshot('PATH_SHIFT')     
        for cut in self.sel_path.cuts:
            cut.shift += (-1 + 2 * up) * s
            cut.simplify_cross(self.sel_path.ring_segments)
                                
        self.sel_path.connect_cuts_to_make_mesh(self.original_form)
        self.sel_path.update_visibility(context, self.original_form)
        
    def segment_n_loops(self,context, path, n):
        if n < 3: return
        if not path.seg_lock:
            self.create_undo_snapshot('PATH_SEGMENTS')
            path.segments = n
            path.create_cut_nodes(context)
            path.snap_to_object(self.original_form, raw = False, world = False, cuts = True)
            path.cuts_on_path(context, self.original_form, self.bme)
            path.connect_cuts_to_make_mesh(self.original_form)
            path.update_visibility(context, self.original_form)
            path.backbone_from_cuts(context, self.original_form, self.bme)
    
    def segment_smooth(self,context, settings):
        method = settings.smooth_method
        if method not in {'PATH_NORMAL','CENTER_MASS','ENDPOINT'}: return
        
        self.create_undo_snapshot('SMOOTH')
        if method == 'PATH_NORMAL':
            #path.smooth_normals
            self.sel_path.average_normals(context, self.original_form, self.bme)
            #self.temporary_message_start(context, 'Smooth normals based on drawn path')
            
        elif method == 'CENTER_MASS':
            #smooth CoM path
            #self.temporary_message_start(context, 'Smooth normals based on CoM path')
            self.sel_path.smooth_normals_com(context, self.original_form, self.bme, iterations = 2)
        
        elif method == 'ENDPOINT':
            #path.interpolate_endpoints
            #self.temporary_message_start(context, 'Smoothly interpolate normals between the endpoints')
            self.sel_path.interpolate_endpoints(context, self.original_form, self.bme)
       
        self.sel_path.connect_cuts_to_make_mesh(self.original_form)
        self.sel_path.backbone_from_cuts(context, self.original_form, self.bme) 
                   
    def cursor_to_segment(self, context):
        half = math.floor(len(self.sel_path.cuts)/2)
                            
        if math.fmod(len(self.sel_path.cuts), 2):  #5 segments is 6 rings
            loc = 0.5 * (self.sel_path.cuts[half].plane_com + self.sel_path.cuts[half+1].plane_com)
        else:
            loc = self.sel_path.cuts[half].plane_com
                            
        context.scene.cursor_location = loc
    
    #### Loop/Cut  Operators####
    
    def loop_select(self,context,eventd):
        
        if self.hover_target and self.hover_target != self.sel_loop:
                        
            self.sel_loop = self.hover_target    
            if not eventd['shift']:
                for path in self.cut_paths:
                    for cut in path.cuts:
                        cut.deselect(self.settings)  
                    if self.sel_loop in path.cuts and path != self.sel_path:
                            path.do_select(self.settings)
                            path.unhighlight(self.settings) #TODO, don't highlight in loop mode
                            self.sel_path = path
                    else:
                        path.deselect(self.settings)
                          
            #select the ring
            self.hover_target.do_select(self.settings)
            
            return True
        else:
            return False
    
    def guide_mode_select(self):
        if self.hover_target and self.hover_target.desc == 'CUT SERIES':
            self.hover_target.do_select(self.settings)
            self.sel_path = self.hover_target
                
            for path in self.cut_paths:
                if path != self.hover_target:
                    path.deselect(self.settings)
                                                   
    def loop_shift(self,context,eventd, shift = 0.05, up = True, undo = True):    
        if undo:
            self.create_undo_snapshot('LOOP_SHIFT')
            
        self.sel_loop.shift += shift * (-1 + 2 * up)
        self.sel_loop.simplify_cross(self.sel_path.ring_segments)
        
        for path in self.cut_paths:
            if self.sel_loop in path.cuts:
                path.connect_cuts_to_make_mesh(self.original_form)
                path.update_backbone(context, self.original_form, self.bme, self.sel_loop, insert = False)
                path.update_visibility(context, self.original_form)
               
    def loop_nverts_change(self, context, eventd, n):
        if n < 3:
            n = 3
            
        self.create_undo_snapshot('RING_SEGMENTS')  
        
        for path in self.cut_paths:
            if self.sel_loop in path.cuts:
                if not path.ring_lock:
                    old_segments = path.ring_segments
                    path.ring_segments = n
                        
                    for cut in path.cuts:
                        new_bulk_shift = round(cut.shift * old_segments/path.ring_segments)
                        new_fine_shift = old_segments/path.ring_segments * cut.shift - new_bulk_shift
                        
                        
                        new_shift =  path.ring_segments/old_segments * cut.shift
                        
                        print(new_shift - new_bulk_shift - new_fine_shift)
                        cut.shift = new_shift
                        cut.simplify_cross(path.ring_segments)
                    
                    path.backbone_from_cuts(context, self.original_form, self.bme)    
                    path.connect_cuts_to_make_mesh(self.original_form)
                    path.update_visibility(context, self.original_form)
                    
                    #self.temporary_message_start(context, 'RING SEGMENTS %i' %path.ring_segments)
                    self.msg_start_time = time.time()
                #else:
                    #self.temporary_message_start(context, 'RING SEGMENTS: Can not be changed.  Path Locked')
        
    def loop_align(self,context, eventd, undo = True):
        
        if undo:
            self.create_undo_snapshot('ALIGN')
        #if not event.ctrl and not event.shift:
        act = 'BETWEEN'
        #act = 'FORWARD'
        #act = 'BACKWARD'
            
        self.sel_path.align_cut(self.sel_loop, mode = act, fine_grain = True)
        self.sel_loop.simplify_cross(self.sel_path.ring_segments)
        
        self.sel_path.connect_cuts_to_make_mesh(self.original_form)
        self.sel_path.update_backbone(context, self.original_form, self.bme, self.sel_loop, insert = False)
        self.sel_path.update_visibility(context, self.original_form)
        
    def loops_delete(self,context,loops, undo = True):
        '''
        removes a cut from a path
        if it's the only cut, removes the whole path
        ready for multipl selected cuts: TODO test
        '''
        if undo:
            self.create_undo_snapshot('DELETE')
        
        #Identify the paths
        update_paths = set()
        remove_paths = set()
        for loop in loops:
            for path in self.cut_paths:
                if loop in path.cuts:
                    if len(path.cuts) > 1 or len(path.cuts) == 1 and path.existing_head:
                        path.remove_cut(context, self.original_form, self.bme, loop)
                        if path not in update_paths:
                            update_paths.add(path)
                            
                        
                        
                    else:
                        if path not in remove_paths:
                            remove_paths.add(path)
        for u_path in update_paths - remove_paths:
            u_path.connect_cuts_to_make_mesh(self.original_form)
            u_path.update_visibility(context, self.original_form)
            u_path.backbone_from_cuts(context, self.original_form, self.bme)                
        
        
        for r_path in remove_paths:
            
            self.cut_paths.remove(r_path)
            
        self.sel_path = None
        self.sel_loop = None
    
    
    ####Interactive/Modal Operators
    
    def prepare_rotate(self,context, eventd, undo = True):
        '''
        TODO path from selected loop
        '''
        if undo:
            self.create_undo_snapshot('ROTATE')
        
        #TODO...if CoM is off screen, then what?
        x,y = eventd['mouse']
        screen_pivot = location_3d_to_region_2d(context.region,context.space_data.region_3d,self.sel_loop.plane_com)
        self.cut_line_widget = CutLineManipulatorWidget(context, self.settings, 
                                                        self.original_form, self.bme,
                                                        self.sel_loop,
                                                        self.sel_path,
                                                        screen_pivot[0],screen_pivot[1],
                                                        hotkey = True)
        self.cut_line_widget.transform_mode = 'ROTATE_VIEW'
        self.cut_line_widget.initial_x = x
        self.cut_line_widget.initial_y = y
        self.cut_line_widget.derive_screen(context)
        
    def prepare_translate(self,context, eventd, undo = True):
        '''
        TODO path from selected loop
        '''
        if undo:
            self.create_undo_snapshot('EDGE_SLIDE')
        
        x,y = eventd['mouse']
        self.cut_line_widget = CutLineManipulatorWidget(context, self.settings, 
                                                        self.original_form, self.bme,
                                                        self.sel_loop,
                                                        self.sel_path,
                                                        x,y,
                                                        hotkey = True)
        self.cut_line_widget.transform_mode = 'EDGE_SLIDE'    
        self.cut_line_widget.initial_x = x
        self.cut_line_widget.initial_y = y
        self.cut_line_widget.derive_screen(context)
    
    def prepare_widget(self, eventd):
        '''
        widget already exists
        '''
        self.create_undo_snapshot('WIDGET_TRANSFORM')
        self.cut_line_widget.derive_screen(eventd['context'])
        
    def widget_transform(self,context,settings, eventd):
        
        x,y = eventd['mouse']
        shft = eventd['shift']
        self.cut_line_widget.user_interaction(context, x, y, shift = shft)
        
        self.sel_loop.cut_object(context, self.original_form, self.bme)
        self.sel_loop.simplify_cross(self.sel_path.ring_segments)
        self.sel_loop.update_com()
        self.sel_path.align_cut(self.sel_loop, mode = 'BETWEEN', fine_grain = True)
        
        self.sel_path.connect_cuts_to_make_mesh(self.original_form)
        self.sel_path.update_visibility(context, self.original_form)
        
        #self.temporary_message_start(context, 'WIDGET_TRANSFORM: ' + str(self.cut_line_widget.transform_mode))    

    def widget_cancel(self,context):
        self.cut_line_widget.cancel_transform()
        self.sel_loop.cut_object(context, self.original_form, self.bme)
        self.sel_loop.simplify_cross(self.sel_path.ring_segments)
        self.sel_loop.update_com()  
        self.sel_path.connect_cuts_to_make_mesh(self.original_form)
        self.sel_path.update_visibility(context, self.original_form)
    
    def draw_post_pixel(self,context):

        r3d = context.space_data.region_3d
        if context.space_data.use_occlude_geometry:
            new_matrix = [v for l in r3d.view_matrix for v in l]
            if new_matrix != self.last_matrix:
                for path in self.cut_paths:
                    path.update_visibility(context, self.original_form)
                    for cut_line in path.cuts:
                        cut_line.update_visibility(context, self.original_form)
                            
            self.post_update = False
            self.last_matrix = new_matrix
            
    
        for i, c_cut in enumerate(self.cut_lines):
            if self.widget_interaction and self.drag_target == c_cut:
                interact = True
            else:
                interact = False
            
            c_cut.draw(context, self.settings)#,three_dimensional = self.navigating, interacting = interact)
    
            if c_cut.verts_simple != [] and self.settings.show_cut_indices:
                loc = location_3d_to_region_2d(context.region, context.space_data.region_3d, c_cut.verts_simple[0])
                blf.position(0, loc[0], loc[1], 0)
                blf.draw(0, str(i))
    
    
        if self.cut_line_widget and self.settings.draw_widget:
            self.cut_line_widget.draw(context)
            
        if len(self.sketch):
            common_drawing.draw_polyline_from_points(context, self.sketch, self.snap_color, 2, "GL_LINE_SMOOTH")
            
        if len(self.cut_paths):
            for path in self.cut_paths:
                path.draw(context, path = False, nodes = self.settings.show_nodes, rings = True, follows = True, backbone = self.settings.show_backbone    )
                
        if len(self.snap_circle):
            common_drawing.draw_polyline_from_points(context, self.snap_circle, self.snap_color, 2, "GL_LINE_SMOOTH")

    def draw_post_view(self,context):
        
        pass
    
class ContourCutSeries(object):  #TODO:  nomenclature consistency. Segment, SegmentCuts, SegmentCutSeries?
    def __init__(self, context, raw_points,
                 segments = 5,  #TODO:  Rename for nomenclature consistency
                 ring_segments = 10, #TDOD: nomenclature consistency
                 cull_factor = 3,
                 smooth_factor = 5,
                 feature_factor = 5):
        
        settings = common_utilities.get_settings()
        
        self.seg_lock = False
        self.ring_lock = False
        self.select = True
        self.is_highlighted = False
        self.desc = 'CUT SERIES'
        self.cuts = []
        
        #if we are bridging to selected geometry in the mesh
        #or perhaps if we are extending an existing stroke
        self.existing_head = None  #these will be type ExistingVertList
        self.existing_tail = None
        
        self.raw_screen = [] # raycast -> raw_world
        self.raw_world = []  #smoothed -> world_path
        self.world_path = []  #the data we use the most
        
        
        self.backbone = []  #a list of lists of verts, which are generated by cutting between each of the loops in the series
        
        self.knots = []  #feature points detected by RPD algo
        
        self.cut_points = [] #the evenly spaced points along the path
        self.cut_point_normals = []  #free normal and face index values from snapping
        self.cut_point_seeds = []
        
        self.verts = []
        self.edges = []
        self.faces = []
        self.follow_lines = []
        self.follow_vis = []
        
        #toss a bunch of raw pixel data
        for i, v in enumerate(raw_points):
            if not math.fmod(i, cull_factor):
                self.raw_screen.append(v)

        ####PROCESSIG CONSTANTS###
        self.segments = segments
        self.ring_segments = ring_segments
        self.cull_factor = cull_factor
        self.smooth_factor = smooth_factor
        self.feature_factor = feature_factor
        
        ###DRAWING SETTINGS###
        self.line_thickness = settings.line_thick + 1
    
    def do_select(self,settings):
        self.select = True
        self.highlight(settings)

    def deselect(self,settings):
        self.select = False
        self.unhighlight(settings)
    
    def highlight(self,settings):
        self.is_highlighted = True
        self.line_thickness = settings.line_thick + 1
    
    def unhighlight(self,settings):
        self.is_highlighted = False
        self.line_thickness = settings.line_thick      
               
    def ray_cast_path(self,context, ob):
        region = context.region
        rv3d = context.space_data.region_3d
        mx = ob.matrix_world
        settings = common_utilities.get_settings()
        rc = common_utilities.ray_cast_region2d
        hits = [rc(region,rv3d,v,ob,settings)[1] for v in self.raw_screen]
        self.raw_world = [mx*hit[0] for hit in hits if hit[2] != -1]
        
        if settings.debug > 1:
            print('ray_cast_path missed %d/%d points' % (len(self.raw_screen) - len(self.raw_world), len(self.raw_screen)))
        
    def smooth_path(self,context, ob = None):
        
        #clear the world path if need be
        self.world_path = []
        
        if ob:
            mx = ob.matrix_world
            imx = mx.inverted()
            
        if len(self.knots) > 2:
            
            #split the raw
            segments = []
            for i in range(0,len(self.knots) - 1):
                segments.append([self.raw_world[m] for m in range(self.knots[i],self.knots[i+1])])
                
        else:
            segments = [[v.copy() for v in self.raw_world]]
        
        for segment in segments:
            for n in range(self.smooth_factor - 1):
                contour_utilities.relax(segment)
                
                #resnap so we don't loose the surface
                if ob:
                    for i, vert in enumerate(segment):
                        snap = ob.closest_point_on_mesh(imx * vert)
                        segment[i] = mx * snap[0]
            
            self.world_path.extend(segment)

        #resnap everthing we can to get normals an stuff
        #TODO do this the last time on the smooth factor duh
        self.snap_to_object(ob)
        
    def snap_to_object(self,ob, raw = True, world = True, cuts = True):
        
        mx = ob.matrix_world
        imx = mx.inverted()
        if raw and len(self.raw_world):
            for i, vert in enumerate(self.raw_world):
                snap = ob.closest_point_on_mesh(imx * vert)
                self.raw_world[i] = mx * snap[0]
                
                
        if world and len(self.world_path):
            #self.path_normals = []
            #self.path_seeds = []
            for i, vert in enumerate(self.world_path):
                snap = ob.closest_point_on_mesh(imx * vert)
                self.world_path[i] = mx * snap[0]
                #self.path_normals.append(mx.to_3x3() * snap[1])
                #self.path_seeds.append(snap[2])
                
        if cuts and len(self.cut_points):
            self.cut_point_normals = []
            self.cut_point_seeds = []
            for i, vert in enumerate(self.cut_points):
                snap = ob.closest_point_on_mesh(imx * vert)
                self.cut_points[i] = mx * snap[0]
                self.cut_point_normals.append(mx.to_3x3() * snap[1])
                self.cut_point_seeds.append(snap[2])
    
    def snap_end_to_existing(self,existing_loop):
        
        #TODO make sure
        loop_length = contour_utilities.get_path_length(existing_loop.verts_simple)
        thresh = 3 * loop_length/len(existing_loop.verts_simple)
        
        snap_tip = None
        snap_tail = None
        
        for v in existing_loop.verts_simple:
            tip_v = v - self.raw_world[0]
            tail_v = v - self.raw_world[-1]
            
            if tip_v.length < thresh:
                snap_tip = existing_loop.verts_simple.index(v)
                thresh = tip_v.length
                
            if tail_v.length < thresh:
                snap_tail = existing_loop.verts_simple.index(v)
                thresh = tail_v.length

        if snap_tip:
            self.existing_head = existing_loop
            v0 = existing_loop.verts_simple[snap_tip]
        else:
            v0 = self.raw_world[0]
            
        if snap_tail:
            self.existing_tail = existing_loop
            v1 = existing_loop.verts_simple[snap_tail]
        else:
            v1 = self.raw_world[-1]
        
        if snap_tip or snap_tail:
            self.ring_segments = len(existing_loop.verts_simple)   
            self.raw_world = contour_utilities.fit_path_to_endpoints(self.raw_world, v0, v1)
                                 
    def find_knots(self):
        '''
        uses RPD method to simplify a curve using the diagonal bbox
        of the drawn path and the feature factor, which is a property
        of the cut path.
        '''
        
        if len(self.raw_world):
            box_diag = contour_utilities.diagonal_verts(self.raw_world)
            error = 1/self.feature_factor * box_diag
        
            self.knots = contour_utilities.simplify_RDP(self.raw_world, error)
        
    def create_cut_nodes(self,context, knots = False):
        '''
        Creates evenly spaced points along the cut path to generate
        contour cuts on.
        '''
        self.cut_points = [] 
        if self.segments <= 1:
            self.cut_points = [self.world_path[0],self.world_path[-1]]
            return
        
        path_length = contour_utilities.get_path_length(self.world_path)
        if path_length == 0:
            self.cut_points = [self.world_path[0], self.world_path[-1]]
            return
        cut_spacing = path_length/self.segments
        
        if len(self.knots) > 2 and knots:
            segments = []
            for i in range(0,len(self.knots) - 1):
                segments.append(self.world_path[self.knots[i]:self.knots[i+1]+1])
            
                  
        else:
            segments = [self.world_path]
            
        
        for i, segment in enumerate(segments):
            segment_length = contour_utilities.get_path_length(segment)
            n_segments = math.ceil(segment_length/cut_spacing)
            vs = contour_utilities.space_evenly_on_path(segment, [[0,1],[1,2]], n_segments, 0, debug = False)[0]
            if i > 0:
                self.cut_points.extend(vs[1:len(vs)])
            else:
                self.cut_points.extend(vs[:len(vs)])
            
    def cuts_on_path(self,context,ob,bme):
        
        settings = common_utilities.get_settings()
        
        self.cuts = []
        
        if not len(self.cut_points) or len(self.cut_points) < 3:
            return
        
        rv3d = context.space_data.region_3d
        view_z = rv3d.view_rotation * Vector((0,0,1))
        
        
        for i, loc in enumerate(self.cut_points):
            
            #leave out the first or last if connecting to
            #existing geom
            if i == 0 and self.existing_head:
                continue
            
            if i == len(self.cut_points) -1 and self.existing_tail:
                continue
            
            cut = ContourCutLine(0, 0, line_width = settings.line_thick)
            cut.seed_face_index = self.cut_point_seeds[i]
            cut.plane_pt = loc
            
            if not loc:
                print(self.cut_points)

            
            if i == 0:
                no1 = self.cut_points[i+1] - self.cut_points[i]
                no2 = self.cut_points[i+2] - self.cut_points[i]
            elif i == len(self.cut_points) -1:
                no1 = self.cut_points[i] - self.cut_points[i-1]
                no2 = self.cut_points[i] - self.cut_points[i-2]
            else:
                no1 = self.cut_points[i] - self.cut_points[i-1]
                no2 = self.cut_points[i+1] - self.cut_points[i]
                
            no1.normalize()
            no2.normalize()
            
            no = (no1 + no2).normalized()
            
            #make the cut in the view plane
            #TODO..this is not always smart!
            perp_vec = no.cross(view_z)
            final_no = view_z.cross(perp_vec)
            final_no.normalize()
                       
            cut.plane_no = final_no
            cut.cut_object(context, ob, bme)
            cut.simplify_cross(self.ring_segments)
            
            if (i == 0 and not self.existing_head) or (i == 1 and self.existing_head):
                #make sure the first loop is right handed
                curl = contour_utilities.discrete_curl(cut.verts_simple, cut.plane_no)
                if curl == None:
                    # TODO: what should happen here?
                    pass
                elif curl < 0:
                    #in this case, we reverse the verts and keep the no
                    #because the no is derived from the drawn path direction
                    cut.verts.reverse()
                    cut.verts_simple.reverse()
                    
            cut.update_com()
            cut.generic_3_axis_from_normal()
            self.cuts.append(cut)

            if i > 0:
                self.align_cut(cut, mode='BEHIND', fine_grain='TRUE')
                
        if self.existing_head:
            self.existing_head.align_to_other(self.cuts[0])
                
        if self.existing_tail:
            self.existing_tail.align_to_other(self.cuts[-1])
    
    def backbone_from_cuts(self,context,ob,bme):
        
        #TODO: be able to change just one ring
        #TODO: cyclic series
        #TODO: redistribute backbone when number of cut segments is increased/decreased
        
        #TEMPORARY FIX TO REMOVE BAD CUTS
        self.clean_cuts()
        self.backbone = []
        
        if len(self.cuts) == 0:
            return
            
        for i, cut in enumerate(self.cuts):
            
            pt = cut.verts_simple[0]
            snap = ob.closest_point_on_mesh(ob.matrix_world.inverted() * pt)
            seed = snap[2]
            surface_no = ob.matrix_world.inverted().transposed() * snap[1]
            
            
            if i == 0:
                #shoot a cut out the back
                cut_no = surface_no.cross(cut.plane_no)
                
                if self.existing_head:
                    stop_plane = [self.existing_head.plane_com, self.existing_head.plane_no]
                else:
                    stop_plane = [cut.plane_com, cut.plane_no]
                
                vertebra = contour_utilities.cross_section_seed_direction(bme, ob.matrix_world, 
                                                                      pt,cut_no, seed, 
                                                                      -cut.plane_no,
                                                                      stop_plane=stop_plane,
                                                                      max_tests=1000)[0]
                
                if vertebra:
                    vertebra3d = [ob.matrix_world * v for v in vertebra]
                else:
                    diag = contour_utilities.diagonal_verts(cut.verts_simple)
                    cast_point = cut.verts_simple[0] - diag * cut.plane_no
                    cast_sfc = ob.closest_point_on_mesh(ob.matrix_world.inverted() * cast_point)[0]
                    vertebra3d = [cut.verts_simple[0], cast_sfc]
                
                self.backbone.append(vertebra3d)
            
            elif i == len(self.cuts)-1:
                #shoot a cut out the back
                cut_no = surface_no.cross(cut.plane_no)
                
                if self.existing_tail:
                    stop_plane = [self.existing_tail.plane_com, sef.existing_tail.plane_no]
                else:
                    stop_plane = [cut.plane_com, cut.plane_no]
                
                vertebra = contour_utilities.cross_section_seed_direction(bme, ob.matrix_world, 
                                                                      pt,cut_no, seed, 
                                                                      -cut.plane_no,
                                                                      stop_plane=stop_plane,
                                                                      max_tests=1000)[0]
                
                if vertebra:
                    vertebra3d = [ob.matrix_world * v for v in vertebra]
                else:
                    diag = contour_utilities.diagonal_verts(cut.verts_simple)
                    cast_point = cut.verts_simple[0] - diag * cut.plane_no
                    cast_sfc = ob.closest_point_on_mesh(ob.matrix_world.inverted() * cast_point)[0]
                    vertebra3d = [cut.verts_simple[0], cast_sfc]
                
                self.backbone.append(vertebra3d)
            
            else:
                #cut backward to reach the other cut
                v1 = cut.verts_simple[0] - self.cuts[i-1].verts_simple[0]
                cut_no = surface_no.cross(v1)
                #alternatively....just use cut.verts_simple[1] - cut.verts_simple[0]
    
                vertebra = contour_utilities.cross_section_seed_direction(bme, ob.matrix_world, 
                                                                          pt,cut_no, seed, 
                                                                          -1 * v1,
                                                                          stop_plane = [self.cuts[i-1].plane_com, self.cuts[i-1].plane_no],
                                                                          max_tests=1000)[0]
                if vertebra:
                    vertebra3d = [ob.matrix_world * v for v in vertebra]
                else:
                    cut1 = self.cuts[i+1]
                    v0 = cut.verts_simple[0]
                    v1 = cut1.verts_simple[0]
                    vertebra3d = [v0, v1]
            
            
                self.backbone.append(vertebra3d)    
        
        
        cut_no = surface_no.cross(cut.plane_no)
        vertebra = contour_utilities.cross_section_seed_direction(bme, ob.matrix_world, 
                                                                  pt,cut_no, seed,
                                                                  cut.plane_no,
                                                                  stop_plane = [cut.plane_com, cut.plane_no],
                                                                  max_tests=1000)[0] 


        if vertebra:
            vertebra3d = [ob.matrix_world * v for v in vertebra]
            vertebra3d.reverse()
        else:
            diag = contour_utilities.diagonal_verts(cut.verts_simple)
    
            cast_point = cut.verts_simple[0] + diag * cut.plane_no
            cast_sfc = ob.closest_point_on_mesh(ob.matrix_world.inverted() * cast_point)[0]
            vertebra3d = [cast_sfc, cut.verts_simple[0]]
        
        self.backbone.append(vertebra3d)
    
    def update_backbone(self,context,ob,bme,cut, insert = False):
        '''
        update just the segments of the backbone affected by a cut
        do this after it has been inserted and aligned or after
        it has been transformed
        
        DO NOT USE FOR CUT REMOVAL, remove_cut takes care of it on it's own.
        '''
        
        ind = self.cuts.index(cut)
        pt = cut.verts_simple[0]
        snap = ob.closest_point_on_mesh(ob.matrix_world.inverted() * pt)
        seed = snap[2]
        surface_no = ob.matrix_world.inverted().transposed() * snap[1]
        
        if ind == 0:
            #shoot a cut out the back
            cut_no = surface_no.cross(cut.plane_no)
            vertebra = contour_utilities.cross_section_seed_direction(bme, ob.matrix_world, 
                                                                      pt,cut_no, seed, 
                                                                      -1 * cut.plane_no,
                                                                      stop_plane = [cut.plane_com, cut.plane_no],
                                                                      max_tests=1000)[0]
            
            if vertebra:
                vertebra3d = [ob.matrix_world * v for v in vertebra]
            
            else:
                diag = contour_utilities.diagonal_verts(self.cuts[0].verts_simple)
        
                cast_point = self.cuts[0].verts_simple[0] - diag * self.cuts[0].plane_no
                cast_sfc = ob.closest_point_on_mesh(ob.matrix_world.inverted() * cast_point)[0]
                vertebra3d = [cast_sfc, self.cuts[0].verts_simple[0]]
            
            self.backbone.pop(0)
            self.backbone.insert(0,vertebra3d)
                
        if ind > 0 and ind < len(self.backbone): #<--- was len(self.cuts)!?
            #cut backward to reach the other cut
            v1 = cut.verts_simple[0] - self.cuts[ind-1].verts_simple[0]
            cut_no = surface_no.cross(v1)
            #alternatively....just use cut.verts_simple[1] - cut.verts_simple[0]

            vertebra = contour_utilities.cross_section_seed_direction(bme, ob.matrix_world, 
                                                                      pt,cut_no, seed, 
                                                                      -1 * v1,
                                                                      stop_plane = [self.cuts[ind-1].plane_com, self.cuts[ind-1].plane_no],
                                                                      max_tests=1000)[0]
            if vertebra:
                vertebra3d = [ob.matrix_world * v for v in vertebra]
            else:
                vertebra3d = [cut.verts_simple[0], self.cuts[ind-1].verts_simple[0]]
        
            self.backbone.pop(ind)
            self.backbone.insert(ind,vertebra3d)    
        
        
        #foward cut must be updated too
        
        if ind < len(self.cuts) -1:
            v1 = self.cuts[ind+1].verts_simple[0] - cut.verts_simple[0]
            cut_no = surface_no.cross(v1)
            vertebra = contour_utilities.cross_section_seed_direction(bme, ob.matrix_world, 
                                                                      pt,cut_no, seed, 
                                                                      v1,
                                                                      stop_plane = [self.cuts[ind+1].plane_com, self.cuts[ind+1].plane_no],
                                                                      max_tests=1000)[0]
            if vertebra:
                vertebra3d = [ob.matrix_world * v for v in vertebra]
            else:
                vertebra3d = [cut.verts_simple[0], self.cuts[ind-1].verts_simple[0]]
        
            #the backbone flows opposite direction the cuts
            vertebra3d.reverse()
            if not insert:
                self.backbone.pop(ind + 1)
            self.backbone.insert(ind + 1,vertebra3d)
            
        
        if ind == len(self.cuts) - 1:
            cut_no = surface_no.cross(cut.plane_no)
            vertebra = contour_utilities.cross_section_seed_direction(bme, ob.matrix_world, 
                                                                      pt,cut_no, seed,
                                                                      cut.plane_no,
                                                                      stop_plane = [cut.plane_com, cut.plane_no],
                                                                      max_tests=1000)[0] 
    
    
            if vertebra:
                vertebra3d = [ob.matrix_world * v for v in vertebra]
                vertebra3d.reverse()
            else:
                diag = contour_utilities.diagonal_verts(cut.verts_simple)
                cast_point = cut.verts_simple[0] + diag * cut.plane_no
                cast_sfc = ob.closest_point_on_mesh(ob.matrix_world.inverted() * cast_point)[0]
                vertebra3d = [cast_sfc, cut.verts_simple[0]]
            
            if not insert:
                self.backbone.pop()
            self.backbone.append(vertebra3d)
           
    def smooth_normals_com(self,context,ob,bme,iterations = 5):
        
        com_path = []
        normals = []
        
        for cut in self.cuts:
            if not cut.plane_com:
                cut.update_com()
            com_path.append(cut.plane_com)
        
        for i, com in enumerate(com_path):
            if i == 0:
                no = com_path[i+1] - com
                
            else:
                no = com - com_path[i-1]
                
            no.normalize()
            normals.append(no)
        
        for n in range(0,iterations):
            for i, no in enumerate(normals):
                
                if i == 0:
                    print('keep end')
                    #new_no = .75 * normals[i] + .25 * normals[i+1]
                    new_no = normals[i]
                elif i == len(normals) - 1:
                    #new_no = .75 * normals[i] + .25 * normals[i-1]
                    new_no = normals[i]
                else:
                    new_no = 1/3 * (normals[i+1] +  normals[i] + normals[i-1])
                    
                new_no.normalize()
                
                normals[i] = new_no
                    
        
        for i, cut in enumerate(self.cuts):
            cut.plane_no = normals[i]
            cut.cut_object(context, ob,  bme)
            cut.simplify_cross(self.ring_segments)
            if i == 0 and self.existing_head:
                self.cuts[0].align_to_other(self.existing_head)
            if i > 0:
                self.align_cut(cut, mode='BEHIND', fine_grain='TRUE')
            cut.update_com()
            cut.generic_3_axis_from_normal()
               
    def average_normals(self,context,ob,bme):
        
        if self.seg_lock:
            self.cut_points = [cut.verts_simple[0] for cut in self.cuts]
        
        avg_normal = Vector((0,0,0))
        for i, loc in enumerate(self.cut_points):
            if i == 0:
                no1 = self.cut_points[i+1] - self.cut_points[i]
                no2 = self.cut_points[i+2] - self.cut_points[i]
            elif i == len(self.cut_points) -1:
                no1 = self.cut_points[i] - self.cut_points[i-1]
                no2 = self.cut_points[i] - self.cut_points[i-2]
            else:
                no1 = self.cut_points[i] - self.cut_points[i-1]
                no2 = self.cut_points[i+1] - self.cut_points[i]
            no1.normalize()
            no2.normalize()
            avg_normal = avg_normal + (no1 + no2).normalized()
        
        avg_normal.normalize()
        
        
        for i, cut in enumerate(self.cuts):
            cut.plane_no = avg_normal
            cut.cut_object(context, ob,  bme)
            cut.simplify_cross(self.ring_segments)
            if i == 0 and self.existing_head:
                self.cuts[0].align_to_other(self.existing_head)
            if i > 0:
                self.align_cut(cut, mode='BEHIND', fine_grain='TRUE')
            cut.update_com()
            cut.generic_3_axis_from_normal()
         
    def interpolate_endpoints(self,context,ob,bme,cut1 = None, cut2 = None):
        '''
        will interpolate normals between the endpoints of the CutSeries
        or between two selected cuts
        
        '''
        if len(self.cuts) < 3:
            print('not valid for interpolation')
            return False
        
        if cut1 and cut2 and cut1 in self.cuts and cut2 in self.cuts:
            start = self.cuts.index(cut1)
            end = self.cuts.index(cut2)
            if end < start:
                start, end = end, start
        
        else:
            start = 0
            end = len(self.cuts) - 1
            
        if self.existing_head and not cut1:
            no_initial = self.existing_head.plane_no
        else:
            no_initial = self.cuts[start].plane_no
            
        no_final = self.cuts[end].plane_no
        
        interps = end - start - 1
        
        if self.existing_head:
            self.cuts[0].align_to_other(self.existing_head)
        
        if start != 0:
            self.align_cut(self.cuts[start], mode='BEHIND', fine_grain='TRUE')
            
        for i in range(0,interps):
            print((i+1)/(end-start))
            self.cuts[start + i+1].plane_no = no_initial.lerp(no_final, (i+1)/(end-start))
            self.cuts[start + i+1].cut_object(context, ob,  bme)
            self.cuts[start + i+1].simplify_cross(self.ring_segments)
            

                    
            if start + i+1 > 0:
                self.align_cut(self.cuts[start + i+1], mode='BEHIND', fine_grain='TRUE')
            self.cuts[start + i+1].update_com()
            
        
        self.align_cut(self.cuts[end-1], mode='BEHIND', fine_grain='TRUE')
        self.align_cut(self.cuts[end], mode='BEHIND', fine_grain='TRUE')
    
    def clean_cuts(self):
        for cut in self.cuts:
            if not len(cut.verts) or not len(cut.verts_simple):
                self.cuts.remove(cut)
                print('##################################')
                print('##################################')
                print('tossed a failed cut!')
                #TODO, implement some kind of warning or visual reference
                 
    def connect_cuts_to_make_mesh(self, ob):
        '''
        This also takes care of bridging to existing vert loops
        At the end..a simple doubles removal solidifies the bridge
        
        Eventually, I will get smart enough to bridge a loop to existing
        geom by using the index math, but it's probably an hour chore and
        there are other higher priority items at the moment.
        '''
        total_verts = []
        total_edges = []
        total_faces = []
        
        #TEMPORARY FIX to TOSS OUT BAD CUTS
        self.clean_cuts()
        
        if len(self.cuts) < 2 and not (self.existing_head or self.existing_tail):
            print('waiting on other cut lines')
            self.verts = []
            self.edges = []
            self.face = []
            self.follow_lines = []
            return
        
        imx = ob.matrix_world.inverted()
        n_rings = len(self.cuts)
        
        if self.existing_head != None:
            n_rings += 1
        if self.existing_tail != None:
            n_rings += 1
            
        
        if len(self.cuts):
            n_lines = len(self.cuts[0].verts_simple)
        elif self.existing_head:
            n_lines = len(self.existing_head.verts_simple)
        
        if self.existing_head != None:
            for v in self.existing_head.verts_simple:
                total_verts.append(imx * v)
                    
        #work out the connectivity edges
        for i, cut_line in enumerate(self.cuts):
            for v in cut_line.verts_simple:
                total_verts.append(imx * v)
            for ed in cut_line.eds_simple:
                total_edges.append((ed[0]+i*n_lines,ed[1]+i*n_lines))
            
            if i < n_rings - 1:
                #make connections between loops
                for j in range(0,n_lines):
                    total_edges.append((i*n_lines + j, (i+1)*n_lines + j))

        if self.existing_tail != None:
            for v in self.existing_tail.verts_simple:
                total_verts.append(imx * v)
                
        
        if len(self.cuts):        
            cyclic = 0 in self.cuts[0].eds_simple[-1]
        elif self.existing_head:
            cyclic = 0 in self.existing_head.eds_simple[-1]
        elif self.existing_tail:
            cyclic = 0 in self.existing_tail.eds_simple[-1]
        
        #work out the connectivity faces:
        for j in range(0,n_rings - 1):
            for i in range(0,n_lines-1):
                ind0 = j * n_lines + i
                ind1 = j * n_lines + (i + 1)
                ind2 = (j + 1) * n_lines + (i + 1)
                ind3 = (j + 1) * n_lines + i
                total_faces.append((ind0,ind1,ind2,ind3))
            
            if cyclic:
                ind0 = (j + 1) * n_lines - 1
                ind1 = j * n_lines + int(math.fmod((j+1)*n_lines, n_lines))
                ind2 = ind0 + 1
                ind3 = ind0 + n_lines
                total_faces.append((ind0,ind1,ind2,ind3))
                
        
        #assert all(len(cut.verts_simple) == n_lines for cut in self.cuts)
        
        self.follow_lines = []
        for i in range(0,n_lines):
            tmp_line = []
            
            if self.existing_head:
                tmp_line.append(self.existing_head.verts_simple[i])
            
            for cut_line in self.cuts:
                tmp_line.append(cut_line.verts_simple[i])
                
            if self.existing_tail:
                tmp_line.append(self.existing_tail.verts_simple[i])
                
            self.follow_lines.append(tmp_line)


        self.verts = total_verts
        self.faces = total_faces
        self.edges = total_edges
        
    def update_visibility(self, context, ob):    
        region = context.region  
        rv3d = context.space_data.region_3d
        
        #update the individual rings
        for cut in self.cuts:
            cut.update_visibility(context, ob)
            
        if self.existing_head:
            self.existing_head.update_visibility(context, ob)
        if self.existing_tail:
            self.existing_tail.update_visibility(context, ob)
        
        #update connecting edges between ring
        if context.space_data.use_occlude_geometry:
            rv3d = context.space_data.region_3d
            is_vis = common_utilities.ray_cast_visible
            self.follow_vis = [is_vis(vert_list, ob, rv3d) for vert_list in self.follow_lines]
        else:
            self.follow_vis = [[True]*len(vert_list) for vert_list in self.follow_lines]
            
    def insert_new_cut(self,context, ob, bme, new_cut, search = 5):
        '''
        attempts to find the best placement for a new cut
        the cut should have already calced verts_simple, 
        plane_pt and plane_com.
        
        in the event that there are no existing cuts in the
        segment (eg, a new segment is created by making a single
        cut), it will simply add the cut in
        
        if there is only one cut, a simple distance threshold
        check is completed. For now, that distnace is 4x the
        bounding box diag of the existing cut in the segment
        '''
        settings = common_utilities.get_settings()
        
        if settings.debug > 1:
            print('testing for cut insertion')
            print('self.existing_head = ' + str(self.existing_head))
            print('len(self.cuts) = %d' % len(self.cuts))
        
        #no cuts, this is a trivial case
        if len(self.cuts) == 0 and not self.existing_head:
            if settings.debug > 1: print('no cuts and not self.existing_head')
            
            self.cuts.append(new_cut)
            self.world_path.append(new_cut.verts_simple[0])
            if self.ring_segments != len(new_cut.verts_simple): #TODO: Nomenclature consistency
                self.ring_segments = len(new_cut.verts_simple)
                
            self.segments = 1
            
            self.backbone_from_cuts(context, ob, bme)
            return True
        
        
        if (len(self.cuts) == 1 and not self.existing_head) or (self.existing_head and len(self.cuts) == 0):
            if settings.debug > 1: print('single cut')
            #criteria for extension existing cut to new cut
            #A) The distance between the com is < 4 * the bbox diagonal of the existing cut
            #B) The angle between the existing cut normal and the line between com's is < 60 deg
            
            cut = self.cuts[0] if self.cuts else self.existing_head
            
            bounds = contour_utilities.bound_box(cut.verts_simple)
            
            diag = 0
            for min_max in bounds:
                l = min_max[1] - min_max[0]
                diag += l * l
                
            diag = diag ** .5 
            thresh = search * diag  #TODO: Come to a decision on how to determine distance
            
            vec_between = new_cut.plane_com - cut.plane_com
            vec_dist = vec_between.length
            is_dist_large = vec_dist > thresh
            
            #absolute value of dot product between line between com and plane normal
            ang = abs(vec_between.normalized().dot(cut.plane_no.normalized()))
            is_ang_wide = ang < math.sin(math.pi/3)
            
            if settings.debug > 1:
                print('dist = %f, thresh = %f' % (vec_dist,thresh))
                print('ang = %f, thresh = %f' % (ang, math.sin(math.pi/3)))
                if is_dist_large:
                    print('distance too far')
                    print('dist = %f' % vec_dist)
                if is_ang_wide:
                    print('too wide, aim better')
                    print('ang = %f' % ang)
                    print('vec_between  = ' + str(vec_between.normalized()))
                    print('cut.plane_no = ' + str(cut.plane_no.normalized()))
            
            if not is_dist_large and not is_ang_wide:
                if settings.debug > 1:
                    print('True: vec_between.length < thresh and ang > math.sin(math.pi/3)')
                
                self.segments += 1
                self.cuts.append(new_cut)
                
                #establish path direction, order of drawn cuts
                direction = new_cut.plane_com - cut.plane_com
                
                #the original cut has no knowledge of the intended
                #cut path
                if cut.plane_no.dot(direction) < 0:
                    cut.plane_no = -1 * cut.plane_no
                        
                spin = contour_utilities.discrete_curl(cut.verts_simple,cut.plane_no)
                if spin < 0:
                    cut.verts_simple.reverse()
                    cut.verts_simple = contour_utilities.list_shift(cut.verts_simple,-1)
                    
                    if cut.desc != 'EXISTING_VERT_LIST':
                        cut.verts.reverse()
                        #TODO: cyclic vs not cyclic
                        cut.verts = contour_utilities.list_shift(cut.verts,-1)

                #neither does the new cut.
                if new_cut.plane_no.dot(direction) < 0:
                    new_cut.plane_no = -1 * new_cut.plane_no
                
                        
                spin = contour_utilities.discrete_curl(new_cut.verts_simple, new_cut.plane_no)
                if spin < 0:
                    new_cut.verts.reverse()
                    #TODO: Cyclic vs not cyclic
                    new_cut.verts = contour_utilities.list_shift(new_cut.verts,-1)
                    
                #make sure the new cut has the appropriate number of cuts
                new_cut.simplify_cross(self.ring_segments)    

                #align the cut, update the backbone etc
                self.align_cut(new_cut, mode = 'BEHIND', fine_grain = True)
                self.backbone_from_cuts(context, ob, bme)
                #self.update_backbone(context, ob, bme, new_cut, insert = True)
                return True
            
            else:
                if settings.debug > 1:
                    print('False: vec_between.length < thresh and ang > math.sin(math.pi/3)')
                return False
        
        
        if self.existing_head and self.cuts:
            if settings.debug > 1: print('True: self.existing_head and self.cuts')
            
            A = self.existing_head.plane_com  #the center of the head
            B = self.cuts[0].plane_com  #the first cut
            C = intersect_line_plane(A,B,new_cut.plane_com, new_cut.plane_no) #the intersection of a the line between the head and first cut
            
            test1 = self.existing_head.plane_no.dot(C-A) > 0
            test2 = self.cuts[0].plane_no.dot(C-B) < 0
            if C and test1 and test2:
                if settings.debug > 1: print('True: C and test1 and test2')
                valid = contour_utilities.point_inside_loop_almost3D(C, new_cut.verts_simple, new_cut.plane_no, new_cut.plane_com, threshold = .01, bbox = True)
                if valid:
                    print('found an intersection between existing head and first loop')
            
                    #check the plane normal
                    if new_cut.plane_no.dot(B-A) < 0:
                        new_cut.plane_no = -1 * new_cut.plane_no
                    
                    #check the spin    
                    spin = contour_utilities.discrete_curl(new_cut.verts_simple, new_cut.plane_no)
                    if spin < 0:
                        new_cut.verts.reverse()
                        new_cut.verts = contour_utilities.list_shift(new_cut.verts,-1)
                       
                        
                    self.cuts.insert(0, new_cut)
                    self.segments += 1
                    
                    new_cut.simplify_cross(self.ring_segments)
                    self.align_cut(new_cut, mode = 'BETWEEN', fine_grain = True)
                    self.backbone_from_cuts(context, ob, bme)
                    #self.update_backbone(context, ob, bme, new_cut, insert = True)
                    return True
            if settings.debug > 1: print('falling through')
        
        if settings.debug > 1: print('checking between cuts')
        #Assume the cuts in the series are in order
        #Check in between all the cuts
        for i in range(0,len(self.cuts) -1):
            A = self.cuts[i].plane_com
            B = self.cuts[i+1].plane_com
            
            C = intersect_line_plane(A,B,new_cut.plane_com, new_cut.plane_no)
            
            test1 = self.cuts[i].plane_no.dot(C-A) > 0
            test2 = self.cuts[i+1].plane_no.dot(C-B) < 0
            
            if C and test1 and test2:
                valid = contour_utilities.point_inside_loop_almost3D(C, new_cut.verts_simple, new_cut.plane_no, new_cut.plane_com, threshold = .01, bbox = True)
                if valid:
                    print('found an intersection at the %i loop' % i)
                    
                    if new_cut.plane_no.dot(B-A) < 0:
                        
                        new_cut.plane_no = -1 * new_cut.plane_no
                        
                    spin = contour_utilities.discrete_curl(new_cut.verts_simple, new_cut.plane_no)
                    if spin < 0:
                        new_cut.verts_simple.reverse()
                        new_cut.verts.reverse()
                        new_cut.verts = contour_utilities.list_shift(new_cut.verts,-1)
                        new_cut.verts_simple = contour_utilities.list_shift(new_cut.verts_simple,-1)
                        
                    self.cuts.insert(i+1, new_cut)
                    self.segments += 1
                    #add an element to the visibility list
                    for vis in self.follow_vis:
                        vis.insert(i+1, True)
                    
                    new_cut.simplify_cross(self.ring_segments)
                    self.align_cut(new_cut, mode = 'BETWEEN', fine_grain = True)
                    self.update_backbone(context, ob, bme, new_cut, insert = True)
                    return True
                
            #Check the enpoints
            #TODO: Unless there is an existing vert loop endpoint
            
        
        if len(self.cuts) > 1:
            spine = self.backbone[1:-1]
            spine_length = sum([contour_utilities.get_path_length(vertebra) for vertebra in spine])
            if settings.debug > 1: print('spine_length = ' + str(spine_length))
            fraction = search * spine_length /  (len(self.cuts) - 1 + 1 * (self.existing_head != None))
        elif self.existing_head and len(self.cuts) == 1:
            fraction = search * (self.existing_head.plane_com - self.cuts[0].plane_com).length  
        if settings.debug > 1: print('fraction = %f' % fraction)
        
        if not self.existing_head:
            if settings.debug > 1: print('False: self.existing_head')
            # B -> A is pointed backward out the tip of the line
            A = self.cuts[0].plane_com
            B = self.cuts[1].plane_com
            
            C = intersect_line_plane(A,B,new_cut.plane_com, new_cut.plane_no)
            
            if C:
                #this verifies the cut is "upstream"
                test1 = self.cuts[0].plane_no.dot(C-A) < 0
                test2 = (C - A).length < fraction
                
                #this doesn't work for shapes that the COM isn't inside the loop!!
                #Will check the bounding plane!!
                
                valid = contour_utilities.point_inside_loop_almost3D(C, new_cut.verts_simple, new_cut.plane_no, new_cut.plane_com, threshold = .01, bbox = True)
                if valid and test1 and test2:
                    print('inserted the new cut at the beginning')
                
                
                    if new_cut.plane_no.dot(B-A) < 0:
                        new_cut.plane_no = -1 * new_cut.plane_no
                    
                    spin = contour_utilities.discrete_curl(new_cut.verts_simple, new_cut.plane_no)
                    if spin < 0:
                        new_cut.verts_simple.reverse()
                        new_cut.verts.reverse()
                        new_cut.verts = contour_utilities.list_shift(new_cut.verts,-1)
                        new_cut.verts_simple = contour_utilities.list_shift(new_cut.verts_simple,-1)
                        
                        
                    
                    self.cuts.insert(0, new_cut)
                    self.segments += 1
                    new_cut.simplify_cross(self.ring_segments)
                    self.align_cut(new_cut, mode = 'AHEAD', fine_grain = True)
                    self.update_backbone(context, ob, bme, new_cut, insert = True)
                    return True
        
        if settings.debug > 1: print('still not inserted')
        
        if self.existing_head and len(self.cuts) == 1:
            cut_behind = self.existing_head
        else:
            cut_behind = self.cuts[-2]
        if settings.debug > 1: print('cut_behind = ' + str(cut_behind))
        
        A = self.cuts[-1].plane_com
        B = cut_behind.plane_com
        
        C = intersect_line_plane(A,B,new_cut.plane_com, new_cut.plane_no)
        
        if C:
            test1 = self.cuts[-1].plane_no.dot(C-A) > 0
            test2 = (C - A).length < fraction
            valid = contour_utilities.point_inside_loop_almost3D(C, new_cut.verts_simple, new_cut.plane_no, new_cut.plane_com, threshold = .01)
            if valid and test1 and test2:
                print('inserted the new cut at the end')
                
                if new_cut.plane_no.dot(A-B) < 0:
                    print('normal reversal to fit path')
                    new_cut.plane_no = -1 * new_cut.plane_no
                
                spin = contour_utilities.discrete_curl(new_cut.verts_simple, new_cut.plane_no)
                if spin < 0:
                    new_cut.verts_simple.reverse()
                    new_cut.verts.reverse()
                    new_cut.verts = contour_utilities.list_shift(new_cut.verts,-1)
                    new_cut.verts_simple = contour_utilities.list_shift(new_cut.verts_simple,-1)
                    print('loop reversal to fit into new path')
                
                self.cuts.append(new_cut)
                self.segments += 1
                new_cut.simplify_cross(self.ring_segments)
                self.align_cut(new_cut, mode = 'BEHIND', fine_grain = True)
                self.update_backbone(context, ob, bme, new_cut, insert = True)
                return True
        
        if settings.debug > 1: print('did not insert')
        return False
    
    def remove_cut(self,context,ob, bme, cut):
        '''
        removes a cut from the sequence
        '''
        if len(self.cuts) > 0:
            ind = self.cuts.index(cut)
            self.cuts.remove(cut)
            self.backbone.pop(ind)
            if ind < len(self.cuts) - 1:
                self.update_backbone(context, ob, bme, self.cuts[ind], insert = False)
            elif ind == 1 and len(self.cuts) == 1:
                self.backbone_from_cuts(context, ob, bme)
            
        else:
            self.cuts = []
        #update a ton of crap?
                     
    def align_cut(self, cut, mode = 'BETWEEN', fine_grain = True):
        '''
        will assess a cut with neighbors and attempt to
        align it
        '''
        if len(self.cuts) < 2 and not self.existing_head:
            print('nothing to align with')
            return
        
        if cut not in self.cuts:
            print('this cut is not connected to anything yet')
            return
        
        
        ind = self.cuts.index(cut)
        ahead = ind + 1
        behind = ind - 1
        
        
                
        if ahead != len(self.cuts):
            cut.align_to_other(self.cuts[ahead], auto_align = fine_grain)
            shift_a = cut.shift
        else:
            shift_a = False
                    
        if behind > -1:
            cut.align_to_other(self.cuts[behind], auto_align = fine_grain)
            shift_b = cut.shift
        elif behind == -1 and self.existing_head:
            print('aligned to head?')
            cut.align_to_other(self.existing_head, auto_align = fine_grain)
            shift_b = cut.shift
        else:
            shift_b = False   
        
        
        if mode == 'DIRECTION':
            #this essentially just reverses the loop if it's got an anticlockwise rotation
            if ahead != len(self.cuts):
                cut.align_to_other(self.cuts[ahead], auto_align = False, direction_only = True)
                    
            elif behind != -1:
                cut.align_to_other(self.cuts[behind], auto_align = False, direction_only = True)
            
        #align between
        if mode == 'BETWEEN':      
            if shift_a and shift_b:
                #In some circumstances this may be a problem if there is
                #an integer jump of verts around the ring
                cut.shift = .5 * (shift_a + shift_b)
                        
            #align ahead anyway
            elif shift_a:
                cut.shift = shift_a
            #align behind anyway
            else:
                cut.shift = shift_b
    
        #align ahead    
        elif mode == 'FORWARD':
            if shift_a:
                cut.shift = shift_a
                                
        #align behind    
        elif mode == 'BACKWARD':
            if shift_b:
                cut.shift = shift_b
        
        if shift_a:        
            if cut.plane_no.dot(self.cuts[ahead].plane_no) < 0:
                cut.plane_no = -1 * cut.plane_no
        
        elif shift_b:
            if cut.plane_no.dot(self.cuts[behind].plane_no) < 0:
                cut.plane_no = -1 * cut.plane_no
  
    def sort_cuts(self):
        '''
        will attempt to infer some kind of order between previously unordered
        cuts
        '''
        print('sort the cuts')
        
    def push_data_into_bmesh(self, context, reto_ob, reto_bme, orignal_form, original_me):
        
        #TODO: Bridging on bmesh level!  Hooray
        
        orig_mx  = orignal_form.matrix_world
        reto_mx  = reto_ob.matrix_world
        reto_imx = reto_mx.inverted()
        xform    = reto_imx * orig_mx
        
        reto_bme.verts.ensure_lookup_table()
        reto_bme.edges.ensure_lookup_table()
        reto_bme.faces.ensure_lookup_table()
        
        # a cheap hashing of vector with epsilon
        def h(v): return '%0.3f,%0.3f,%0.3f' % tuple(v)
        
        weld_verts = {}
        if self.existing_head:
            for i in self.existing_head.vert_inds_sorted:
                v = reto_bme.verts[i]
                v.select_set(False)
                weld_verts[h(v.co)] = v
        if self.existing_tail:
            for i in self.existing_tail.vert_inds_sorted:
                v = reto_bme.verts[i]
                v.select_set(False)
                weld_verts[h(v.co)] = v
        
        hvs = [h(vert) for vert in self.verts]
        bmverts = [weld_verts[hv] if hv in weld_verts else reto_bme.verts.new(tuple(xform * vert)) for hv,vert in zip(hvs,self.verts)]
        bmfaces = [reto_bme.faces.new(tuple(bmverts[iv] for iv in face)) for face in self.faces]
        
        # Initialize the index values of this sequence
        reto_bme.verts.index_update()
        reto_bme.edges.index_update()
        reto_bme.faces.index_update()
        
        print('data pushed into bmesh')
    
    def snap_merge_into_other(self, merge_series, merge_ring, context, ob, bme):
        '''
        Will assess other path, modify self and then place self data into the
        merge_series
        
        merg_ring can be a CutLine or ExistingVertList
        
        Prerequisites: ray_cast_path, find knots, smooth path
        '''
        
        #find closest point in snap ring to beginning of path
        #by default, only originating extensions are eligible
        #not paths which are drawn and terminate on a snap
        #ring
        
        dists = [(self.raw_world[0] - v).length for v in merge_ring.verts_simple]
        best_index = dists.index(min(dists))
    
        #snap the world path to that vert
        self.raw_world = contour_utilities.fit_path_to_endpoints(self.raw_world, merge_ring.verts_simple[best_index], self.raw_world[-1])
        self.smooth_path(context, ob = ob)
        self.ring_segments = merge_series.ring_segments
        
        if merge_ring.desc == 'EXISTING_VERT_LIST':
            
            #this can only happen with a cut series that just
            #has an existing head.
            segment_width = (merge_ring.verts_simple[1] -  merge_ring.verts_simple[0]).length
            ind = None
            print('MERGE TO EXISTING VERTS')
        
        else:
            ind = merge_series.cuts.index(merge_ring)
        
            #establish the segment length
            if len(merge_series.cuts) < 2:
                segment_width = (merge_ring.verts_simple[1] -  merge_ring.verts_simple[0]).length
                    
            else:
            
                if ind == 0:
                    segment_width = (merge_series.cuts[1].plane_com - merge_ring.plane_com).length
                else:
                    segment_width = (merge_series.cuts[-2].plane_com - merge_ring.plane_com).length
    
        path_length = contour_utilities.get_path_length(self.world_path)
        self.segments  = math.ceil(path_length/segment_width)
    
        self.create_cut_nodes(context, knots = False)
        
        
                
        
        self.snap_to_object(ob, raw = False, world = False, cuts = True)
        self.cuts_on_path(context,ob,bme)
        self.cuts.pop(0)
        
        #if one existing cut....can go either way
        #make the first cut match the path direction
        if not self.existing_head and ind == 0 and len(merge_series.cuts) == 1:
            print('MERGING TO THE ONE AND ONLY CUT')
            p_dir = self.cut_points[1] - self.cut_points[0]
            p_dir.normalize
            if merge_ring.plane_no.dot(p_dir) < 0:
                merge_ring.verts_simple.reverse()
                merge_ring.verts.reverse()
                merge_ring.verts_simple_visible.reverse()
                merge_ring.verts_simple_visible = contour_utilities.list_shift(merge_ring.verts_simple_visible,-1)
                
                merge_ring.verts = contour_utilities.list_shift(merge_ring.verts,-1)
                merge_ring.verts_simple = contour_utilities.list_shift(merge_ring.verts_simple,-1)
                merge_ring.shift *= -1
                merge_ring.plane_no = -1 * merge_ring.plane_no
    
        #join the series and align them
        if ind == 0:
            #TODO: Wasted effort in cuts on path because this does an alignment step as well!!
            self.cuts[0].align_to_other(merge_series.cuts[0],auto_align = True, direction_only = False)
            for i, cut in enumerate(self.cuts):
                if i > 0:
                    self.align_cut(cut, mode='BEHIND', fine_grain = True)
            
            #HACK: Should this happen later on a path basis?
            if len(merge_series.cuts) > 1:
                self.cuts.reverse()
                for cut in self.cuts:
                    cut.plane_no = -1 * cut.plane_no
                
                merge_series.cuts = self.cuts + merge_series.cuts
                
            else:
                merge_series.cuts.extend(self.cuts)
    
        elif not ind: #we are snapping to an existing vert list
            print('aligned other cut?')
            merge_ring.align_to_other(self.cuts[0]) #we already popped off the first one
            merge_series.cuts.extend(self.cuts)
            
        else:
            self.cuts[0].align_to_other(merge_series.cuts[-1],auto_align = True, direction_only = False)
            for i, cut in enumerate(self.cuts):
                if i > 0:
                    self.align_cut(cut, mode='BEHIND', fine_grain = True)
            
            merge_series.cuts.extend(self.cuts)
    
        #expensive recalculation of whole path
        #TODO: make this process smarter
        if any(len(cut.verts_simple)==0 for cut in merge_series.cuts):
            print('>>> error!')
            print(str([len(cut.verts_simple) for cut in merge_series.cuts]))
        merge_series.world_path = [cut.verts_simple[0] for cut in merge_series.cuts]
        merge_series.segments = len(merge_series.cuts) - 1
        merge_series.backbone_from_cuts(context,ob,bme)
        merge_series.connect_cuts_to_make_mesh(ob)
        merge_series.update_visibility(context,ob)
        
    def draw(self,context, path = True, nodes = True, rings = True, follows = True, backbone = True):
        
        settings = common_utilities.get_settings()

        stroke_color = settings.theme_colors_active[settings.theme]
        mesh_color = settings.theme_colors_mesh[settings.theme]

        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        #TODO:  Debug if None in self.world path.  How could this happen?       
        if path and self.world_path != [] and None not in self.world_path:
            
            common_drawing.draw_3d_points(context, self.world_path, (1,.5,0,1), 3)
       
        if nodes and len(self.cut_points):
            common_drawing.draw_3d_points(context, self.cut_points, (0,1,.5,1), 2)
         
        if rings:
            if len(self.cuts):
                for cut in self.cuts:
                    cut.draw(context, settings, three_dimensional = True, interacting = False)
                    
            if self.existing_head:
                self.existing_head.draw(context, settings, three_dimensional = True, interacting = False)
                
            if self.existing_tail:
                self.existing_tail.draw(context, settings, three_dimensional = True, interacting = False)
        
        if backbone and len(self.backbone):
            for vertebra3d in self.backbone:
                common_drawing.draw_3d_points(context, vertebra3d, 
                                                          (.2,.2,1, 1), 
                                                          3)   
        if self.follow_lines != [] and settings.show_edges:
            if not context.space_data.use_occlude_geometry:
                
                for follow in self.follow_lines:
                    common_drawing.draw_polyline_from_3dpoints(context, follow, 
                                                          mesh_color, 
                                                          self.line_thickness,"GL_LINE_STIPPLE")

            else:
                
                for i, line in enumerate(self.follow_lines):
                    for n in range(0,len(line)-1):
                        if self.follow_vis[i][n] and self.follow_vis[i][n+1]:
                            common_drawing.draw_polyline_from_3dpoints(context, [line[n],line[n+1]], 
                                                          mesh_color, 
                                                          self.line_thickness,"GL_LINE_STIPPLE")

            # Do the fill for vis-faces
            fl,fv = self.follow_lines, self.follow_vis
            leni,lenj = len(fl),len(fl[0])
            quad_pts = []
            i1 = leni-1
            for i0 in range(leni):
                for j0 in range(lenj-1):
                    j1 = j0 + 1
                    if fv[i0][j0] and fv[i1][j0] and fv[i1][j1] and fv[i0][j1]:
                        quad_pts += [fl[i0][j0], fl[i1][j0], fl[i1][j1], fl[i0][j1]]
                i1 = i0
            common_drawing.draw_quads_from_3dpoints(context, quad_pts, (mesh_color[0],mesh_color[1],mesh_color[2],mesh_color[3]*0.2))
                
class ContourControlPoint(object):
    
    def __init__(self, parent, x, y, color = (1,0,0,1), size = 2, mouse_radius=10):
        self.desc = 'CONTROL_POINT'
        self.x = x
        self.y = y
        self.world_position = None #to be updated later
        self.color = color
        self.size = size
        self.mouse_rad = mouse_radius
        self.parent = parent
        
    def mouse_over(self,x,y):
        dist = (self.x -x)**2 + (self.y - y)**2
        #print(dist < 100)
        if dist < 100:
            return True
        else:
            return False
        
    def screen_from_world(self,context):
        point = location_3d_to_region_2d(context.region, context.space_data.region_3d,self.world_position)
        self.x = point[0]
        self.y = point[1]
        
    def screen_to_world(self,context):
        region = context.region  
        rv3d = context.space_data.region_3d
        if self.world_position:
            self.world_position = region_2d_to_location_3d(region, rv3d, (self.x, self.y),self.world_position)

class ExistingVertList(object):
    def __init__(self, context, verts, keys, mx, key_type = 'EDGES'):
        '''
        verts - list of bmesh verts, not nesessarily in order
        
        keys - BME edges which are used to order the verts OR
             -Vert indices, which specify the orde. Eg, a list of
               incides genearted from "edge loops from edges"
               
        mx - world matrix of object bmesh belongs to.  all this happens in world
        
        key_type - enum in {'EDGES', 'INDS'}
        
        '''
        settings = common_utilities.get_settings()
        
        self.desc = 'EXISTING_VERT_LIST'
        
        #will need this later for bridging?
        self.vert_inds_unsorted = [vert.index for vert in verts]
        
        if key_type == 'EDGES':
            edge_keys = [[ed.verts[0].index, ed.verts[1].index] for ed in keys]
            remaining_keys = [i for i in range(1,len(edge_keys))]
            vert_inds_sorted = [edge_keys[0][0], edge_keys[0][1]]
        
            iterations = 0
            max_iters = math.factorial(len(remaining_keys))
            while len(remaining_keys) > 0 and iterations < max_iters:
                print(remaining_keys)
                iterations += 1
                for key_index in remaining_keys:
                    l = len(vert_inds_sorted) -1
                    key_set = set(edge_keys[key_index])
                    last_v = {vert_inds_sorted[l]}
                    if  key_set & last_v:
                        vert_inds_sorted.append(int(list(key_set - last_v)[0]))
                        remaining_keys.remove(key_index)
                        break
                    
        elif key_type == 'INDS':
            
            vert_inds_sorted = keys
        
        if vert_inds_sorted[0] == vert_inds_sorted[-1]:
            cyclic = True
            vert_inds_sorted.pop() #clean out that last vert!
            
        else:
            cyclic = False
            
        self.eds_simple = [[i,i+1] for i in range(0,len(vert_inds_sorted)-1)]
        if cyclic:
            self.eds_simple.append([len(vert_inds_sorted)-1,0])
            
        self.verts_simple = []
        for i in vert_inds_sorted:
            v = verts[self.vert_inds_unsorted.index(i)]
            self.verts_simple.append(mx * v.co)
        
        self.verts_simple_visible = [True] * len(self.verts_simple)
         
        self.plane_no = None  #TODO best fit plane?
        self.vert_inds_sorted = vert_inds_sorted
        
        self.derive_normal()
    
    def generic_3_axis_from_normal(self):
        
        (self.vec_x, self.vec_y) = contour_utilities.generic_axes_from_plane_normal(self.plane_com, self.plane_no)
                
    def derive_normal(self):
        
        if self.verts_simple != []:
            #com, normal = contour_utilities.calculate_best_plane(self.verts_simple)
            com,normal = contour_utilities.calculate_com_normal(self.verts_simple)
            
        self.plane_no = normal
        self.plane_com = com
        
        if contour_utilities.discrete_curl(self.verts_simple, self.plane_no) < 0:
            self.plane_no = -1 * self.plane_no
        
        self.generic_3_axis_from_normal()
                    
    def connectivity_analysis(self,other):
        
        
        COM_self = contour_utilities.get_com(self.verts_simple)
        COM_other = contour_utilities.get_com(other.verts_simple)
        delta_com_vect = COM_self - COM_other  #final - initial :: self - other
        delta_com_vect.normalize()
        

        
        ideal_to_com = 0
        for i, v in enumerate(self.verts_simple):
            connector = v - other.verts_simple[i]  #continue convention of final - initial :: self - other
            connector.normalize()
            align = connector.dot(delta_com_vect)
            #this shouldnt happen but it appears to be...shrug
            if align < 0:
                align *= -1    
            ideal_to_com += align
        
        ideal_to_com = 1/len(self.verts_simple) * ideal_to_com
        
        return ideal_to_com
               
    def align_to_other(self,other, auto_align = True):
        
        '''
        Modifies vert order of self to  provide best
        bridge between self verts and other loop
        '''
        if not self.plane_no:
            self.derive_normal()
            
        verts_1 = other.verts_simple
        eds_1 = other.eds_simple
        
        if 0 in eds_1[-1]:
            cyclic = True
        else:
            cyclic = False
        
        if len(verts_1) != len(self.verts_simple):
            #print(len(verts_1))
            #print(len(self.verts_simple))
            print('non uniform loops, stopping until your developer gets smarter')
            return
            
        if cyclic:
            if other.plane_no.dot(self.plane_no) < 0:
                print('reversing the raw loop')
                self.plane_no = -1* self.plane_no
                self.verts_simple.reverse()
                self.vert_inds_unsorted.reverse()
            
            edge_len_dict = {}
            for i in range(0,len(verts_1)):
                for n in range(0,len(self.verts_simple)):
                    edge = (i,n)
                    vect = self.verts_simple[n] - verts_1[i]
                    edge_len_dict[edge] = vect.length
            
            shift_lengths = []
            #shift_cross = []
            for shift in range(0,len(self.verts_simple)):
                tmp_len = 0
                #tmp_cross = 0
                for i in range(0, len(self.verts_simple)):
                    shift_mod = int(math.fmod(i+shift, len(self.verts_simple)))
                    tmp_len += edge_len_dict[(i,shift_mod)]
                shift_lengths.append(tmp_len)
                   
            final_shift = shift_lengths.index(min(shift_lengths))
            if final_shift != 0:
                #print('pre rough shift alignment % f' % self.connectivity_analysis(other))
                #print("rough shifting verts by %i segments" % final_shift)
                self.int_shift = final_shift
                self.verts_simple = contour_utilities.list_shift(self.verts_simple, final_shift)
                self.vert_inds_unsorted = contour_utilities.list_shift(self.vert_inds_unsorted, final_shift)
                #print('post rough shift alignment % f' % self.connectivity_analysis(other))    
                
        
        else:
            #if the segement is not cyclic
            #all we have to do is compare the endpoints
            Vtotal_1 = verts_1[-1] - verts_1[0]
            Vtotal_2 = self.verts_simple[-1] - self.verts_simple[0]
    
            if Vtotal_1.dot(Vtotal_2) < 0:
                #print('reversing path 2')
                self.verts_simple.reverse()
                self.vert_inds_unsorted.reverse()
                
    def update_visibility(self,context,ob):
        if context.space_data.use_occlude_geometry:
            #TODO: should the following be uncommented?
            #self.visible_poly = []
            #self.visible_u = []
            #self.visible_d = []
            rv3d = context.space_data.region_3d
            self.verts_simple_visible = common_utilities.ray_cast_visible(self.verts_simple, ob, rv3d)
        else:
            self.verts_simple_visible = [True] * len(self.verts_simple)
    
    def draw(self,context, settings, three_dimensional = True, interacting = False):
            '''
            setings are the addon preferences for contour tools
            '''
            
            debug = settings.debug
            #settings = common_utilities.get_settings()
            
            stroke_color = settings.theme_colors_active[settings.theme]
            mesh_color = settings.theme_colors_mesh[settings.theme]
       
            if debug > 1:
                if self.plane_com:
                    com_2d = location_3d_to_region_2d(context.region, context.space_data.region_3d, self.plane_com)
                    
                    common_drawing.draw_3d_points(context, [self.plane_com], (0,1,0,1), 4)
                    
                    rv3d = context.space_data.region_3d
                    imx = rv3d.view_matrix.inverted()
                    screen_z = rv3d.view_matrix.to_3x3() * Vector((0,0,1))
                    if self.vec_x and debug > 2:
                        vec_screen = imx.transposed() * self.vec_x
                        
                        factor = (1 - abs(self.vec_x.dot(screen_z)))
                        screen_pt_x = com_2d + factor * 40 * vec_screen.to_2d().normalized()
                        common_drawing.draw_polyline_from_points(context, [com_2d, screen_pt_x],(1,0,0,1), 2, 'GL_LINE_STRIP')

                    if self.vec_y and debug > 2:
                        
                        vec_screen = imx.transposed() * self.vec_y
                        factor = (1 - abs(self.vec_y.dot(screen_z)))
                        screen_pt_x = com_2d + factor * 40 * vec_screen.to_2d().normalized()
                        common_drawing.draw_polyline_from_points(context, [com_2d, screen_pt_x],(0,1,0,1), 2, 'GL_LINE_STRIP')
    
                    if self.plane_no:
                        vec_screen = imx.transposed() * self.plane_no
                        factor = (1 - abs(self.plane_no.dot(screen_z)))
                        screen_pt_x = com_2d + factor* 40 * vec_screen.to_2d().normalized()
                        common_drawing.draw_polyline_from_points(context, [com_2d, screen_pt_x],(0,0,1,1), 2, 'GL_LINE_STRIP')
                        
            if False not in self.verts_simple_visible:
                    common_drawing.draw_3d_points(context, self.verts_simple, self.vert_color, 3)
                    common_drawing.draw_polyline_from_3dpoints(context, self.verts_simple, mesh_color,  settings.line_thick, 'GL_LINE_STIPPLE')
                    
                    if 0 in self.eds_simple[-1]:
                        common_drawing.draw_polyline_from_3dpoints(context, 
                                                                      [self.verts_simple[-1],self.verts_simple[0]], 
                                                                      mesh_color,  
                                                                      settings.line_thick, 
                                                                      'GL_LINE_STIPPLE')
     
            else:
                for i, v in enumerate(self.verts_simple):
                    if self.verts_simple_visible[i]:
                        common_drawing.draw_3d_points(context, [v], mesh_color, settings.vert_size)
                            
                        if i < len(self.verts_simple) - 1 and self.verts_simple_visible[i+1]:
                            common_drawing.draw_polyline_from_3dpoints(context, [v, self.verts_simple[i+1]], mesh_color, settings.line_thick, 'GL_LINE_STIPPLE')
            
                if 0 in self.eds_simple[-1] and self.verts_simple_visible[0] and self.verts_simple_visible[-1]:
                        common_drawing.draw_polyline_from_3dpoints(context, 
                                                                      [self.verts_simple[-1],self.verts_simple[0]], 
                                                                      mesh_color,  
                                                                      settings.line_thick, 
                                                                      'GL_LINE_STIPPLE')
            
                    
            if debug:
                    
                if settings.simple_vert_inds:    
                    for i, point in enumerate(self.verts_simple):
                        loc = location_3d_to_region_2d(context.region, context.space_data.region_3d, point)
                        blf.position(0, loc[0], loc[1], 0)
                        blf.draw(0, str(i))    
                      

class ContourCutLine(object): 
    
    def __init__(self, x, y, line_width = 3):
        
        self.desc = "CUT_LINE"
        self.select = False
        self.is_highlighted = False
        self.head = ContourControlPoint(self,x,y)
        self.tail = ContourControlPoint(self,x,y)
        #self.plane_tan = ContourControlPoint(self,x,y, color = (.8,.8,.8,1))
        #self.view_dir = view_dir
        self.target = None
 
        self.updated = False
        self.plane_pt = None  #this will be a point on an object surface...calced after ray_casting
        self.plane_com = None  #this will be a point in the object interior, calced after cutting a contour
        self.plane_no = None
        
        #these points will define two orthogonal vectors
        #which lie tangent to the plane...which we can use
        #to draw a little widget on the COM
        self.plane_x = None
        self.plane_y = None
        self.plane_z = None
        
        self.vec_x = None
        self.vec_y = None
        #self.vec_z is the plane normal
        
        self.seed_face_index = None
        
        #high res coss section
        #@ resolution of original mesh
        self.verts = []
        self.verts_screen = []
        self.edges = []
        #low res derived contour
        self.verts_simple = []
        self.verts_simple_visible = []
        self.eds_simple = []
        
        #screen cache for fast selection
        self.verts_simple_screen = []
        
        #variable used to shift loop beginning on high res loop
        self.shift = 0
        self.int_shift = 0

        
    def update_screen_coords(self,context):
        self.verts_screen = [location_3d_to_region_2d(context.region, context.space_data.region_3d, loc) for loc in self.verts]
        self.verts_simple_screen = [location_3d_to_region_2d(context.region, context.space_data.region_3d, loc) for loc in self.verts_simple]
    
    def highlight(self,settings):
        self.is_highlighted = True
        #adjust thickness?
    
    def unhighlight(self,settings):
        self.is_highlighted = False 
                
    def do_select(self,settings):
        self.select = True
        self.highlight(settings) 
    
    def deselect(self,settings):
        self.select = False
        self.unhighlight(settings)
        
        
    def update_visibility(self,context,ob):
        if context.space_data.use_occlude_geometry:
            rv3d = context.space_data.region_3d
            self.verts_simple_visible  = common_utilities.ray_cast_visible(self.verts_simple, ob, rv3d)
            #TODO: should the following be uncommented?
            #self.visible_poly = []
            #self.visible_u = []
            #self.visible_d = []
            ##self.visible_world = []
        else:
            self.verts_simple_visible = [True] * len(self.verts_simple)
    
    def draw(self,context, settings, three_dimensional = True, interacting = False):
        '''
        setings are the addon preferences for contour tools
        '''
        stroke_color = settings.theme_colors_active[settings.theme]
        mesh_color = settings.theme_colors_mesh[settings.theme]

        debug = settings.debug
        #settings = common_utilities.get_settings()
        
        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        #this should be moved to only happen if the view changes :-/  I'ts only
        #a few hundred calcs even with a lot of lines. Waste not want not.
        if self.head and self.head.world_position:
            self.head.screen_from_world(context)
        if self.tail and self.tail.world_position:
            self.tail.screen_from_world(context)
        #if self.plane_tan.world_position:
            #self.plane_tan.screen_from_world(context)
            
        if debug > 1:
            if self.plane_com:
                com_2d = location_3d_to_region_2d(context.region, context.space_data.region_3d, self.plane_com)
                
                common_drawing.draw_3d_points(context, [self.plane_com], (0,1,0,1), 4)
                
                
                rv3d = context.space_data.region_3d
                imx = rv3d.view_matrix.inverted()
                screen_z = rv3d.view_matrix.to_3x3() * Vector((0,0,1))
                if self.vec_x and debug > 2:
                    vec_screen = imx.transposed() * self.vec_x
                    
                    factor = (1 - abs(self.vec_x.dot(screen_z)))
                    screen_pt_x = com_2d + factor * 40 * vec_screen.to_2d().normalized()
                    common_drawing.draw_polyline_from_points(context, [com_2d, screen_pt_x],(1,1,0,1), 2, 'GL_LINE_STRIP')

                if self.vec_y and debug > 2:
                    
                    vec_screen = imx.transposed() * self.vec_y
                    factor = (1 - abs(self.vec_y.dot(screen_z)))
                    screen_pt_x = com_2d + factor * 40 * vec_screen.to_2d().normalized()
                    common_drawing.draw_polyline_from_points(context, [com_2d, screen_pt_x],(0,1,1,1), 2, 'GL_LINE_STRIP')

                if self.plane_no:
                    vec_screen = imx.transposed() * self.plane_no
                    factor = (1 - abs(self.plane_no.dot(screen_z)))
                    screen_pt_x = com_2d + factor* 40 * vec_screen.to_2d().normalized()
                    common_drawing.draw_polyline_from_points(context, [com_2d, screen_pt_x],(1,0,1,1), 2, 'GL_LINE_STRIP')

                    
        
        #draw connecting line
        if self.head:
            points = [(self.head.x,self.head.y),(self.tail.x,self.tail.y)]
            
            common_drawing.draw_polyline_from_points(context, points, stroke_color, settings.stroke_thick, "GL_LINE_STIPPLE")
        
            #draw the two handles
            common_drawing.draw_points(context, points, stroke_color, settings.handle_size)
        
        #draw the current plane point and the handle to change plane orientation
        #if self.plane_pt and settings.draw_widget:
            #point1 = location_3d_to_region_2d(context.region, context.space_data.region_3d, self.plane_pt)
            #point2 = (self.plane_tan.x, self.plane_tan.y)

            #common_drawing.draw_polyline_from_points(context, [point1,point2], (0,.2,1,1), settings.stroke_thick, "GL_LINE_STIPPLE")
            #common_drawing.draw_points(context, [point2], self.plane_tan.color, settings.handle_size)
            #common_drawing.draw_points(context, [point1], self.head.color, settings.handle_size)
        
        #draw the raw contour vertices
        if (self.verts and self.verts_simple == []) or (debug > 0 and settings.show_verts):
            
            if three_dimensional:
                
                common_drawing.draw_3d_points(context, self.verts, mesh_color, settings.raw_vert_size)

        
        
        
        
        if False not in self.verts_simple_visible:
                common_drawing.draw_3d_points(context, self.verts_simple, mesh_color, 3)
                if self.is_highlighted:
                    common_drawing.draw_polyline_from_3dpoints(context, self.verts_simple, stroke_color,  settings.line_thick*2, 'GL_LINE_STIPPLE')
                else: 
                    common_drawing.draw_polyline_from_3dpoints(context, self.verts_simple, mesh_color,  settings.line_thick, 'GL_LINE_STIPPLE')


                if self.edges != [] and 0 in self.edges[-1]:
                    common_drawing.draw_polyline_from_3dpoints(context, 
                                                                  [self.verts_simple[-1],self.verts_simple[0]], 
                                                                  mesh_color,  
                                                                  settings.line_thick, 
                                                                  'GL_LINE_STIPPLE')
            
        else:
            for i, v in enumerate(self.verts_simple):
                if self.verts_simple_visible[i]:
                    common_drawing.draw_3d_points(context, [v], mesh_color, settings.vert_size)
                        
                    if i < len(self.verts_simple) - 1 and self.verts_simple_visible[i+1]:
                        if self.is_highlighted:
                            common_drawing.draw_polyline_from_3dpoints(context, [v, self.verts_simple[i+1]], stroke_color, settings.line_thick*2, 'GL_LINE_STIPPLE')
                        else:
                            common_drawing.draw_polyline_from_3dpoints(context, [v, self.verts_simple[i+1]], mesh_color, settings.line_thick, 'GL_LINE_STIPPLE')

            if self.edges != [] and 0 in self.edges[-1] and self.verts_simple_visible[0] and self.verts_simple_visible[-1]:
                    if self.is_highlighted:
                        common_drawing.draw_polyline_from_3dpoints(context, [self.verts_simple[-1],self.verts_simple[0]], stroke_color, settings.line_thick, 'GL_LINE_STIPPLE')
                    else:
                        common_drawing.draw_polyline_from_3dpoints(context, [self.verts_simple[-1],self.verts_simple[0]], mesh_color, settings.line_thick, 'GL_LINE_STIPPLE')


        if debug:
            if settings.vert_inds:
                for i, point in enumerate(self.verts):
                    loc = location_3d_to_region_2d(context.region, context.space_data.region_3d, point)
                    blf.position(0, loc[0], loc[1], 0)
                    blf.draw(0, str(i))
                
            if settings.simple_vert_inds:    
                for i, point in enumerate(self.verts_simple):
                    loc = location_3d_to_region_2d(context.region, context.space_data.region_3d, point)
                    blf.position(0, loc[0], loc[1], 0)
                    blf.draw(0, str(i))
    
    #draw contour points? later    
    def hit_object(self, context, ob, method = 'VIEW'):
        settings = common_utilities.get_settings()
        region = context.region  
        rv3d = context.space_data.region_3d
        
        pers_mx = rv3d.perspective_matrix  #we need the perspective matrix
        
        #the world direction vectors associated with
        #the view rotations
        view_x = rv3d.view_rotation * Vector((1,0,0))
        view_y = rv3d.view_rotation * Vector((0,1,0))
        view_z = rv3d.view_rotation * Vector((0,0,1))
        
        
        #this only happens on the first time.
        #after which everything is handled by
        #the widget
        if method == 'VIEW':
            #midpoint of the  cutline and world direction of cutline
            screen_coord = (self.head.x + self.tail.x)/2, (self.head.y + self.tail.y)/2
            cut_vec = (self.tail.x - self.head.x)*view_x + (self.tail.y - self.head.y)*view_y
            cut_vec.normalize()
            self.plane_no = cut_vec.cross(view_z).normalized()
            
            #we need to populate the 3 axis vectors
            self.vec_x = -1 * cut_vec.normalized()
            self.vec_y = self.plane_no.cross(self.vec_x)
            
            ray_vector,hit = common_utilities.ray_cast_region2d(region, rv3d, screen_coord, ob, settings)
            
            if hit[2] != -1:
                mx = ob.matrix_world
                self.head.world_position = region_2d_to_location_3d(region, rv3d, (self.head.x, self.head.y), mx * hit[0])
                self.tail.world_position = region_2d_to_location_3d(region, rv3d, (self.tail.x, self.tail.y), mx * hit[0])
                
                self.plane_pt = mx * hit[0]
                self.seed_face_index = hit[2]

                if settings.use_perspective:
    
                    cut_vec = (self.tail.x - self.head.x)*view_x + (self.tail.y - self.head.y)*view_y
                    cut_vec.normalize()
                    self.plane_no = cut_vec.cross(ray_vector).normalized()
                    self.vec_x = -1 * cut_vec.normalized()
                    self.vec_y = self.plane_no.cross(self.vec_x)
                    
                self.plane_x = self.plane_pt + self.vec_x
                self.plane_y = self.plane_pt + self.vec_y
                self.plane_z = self.plane_pt + self.plane_no
                    
            else:
                self.plane_pt = None
                self.seed_face_index = None
                self.verts = []
                self.verts_simple = []
                print('Did not hit!')
            
            return self.plane_pt
        
        elif method in {'3_AXIS_COM','3_AXIS_POINT'}:
            mx = ob.matrix_world
            imx = mx.inverted()
            y = self.vec_y
            x = self.vec_x
                  
            if method == '3_AXIS_COM':
                
                if not self.plane_com:
                    print('failed no COM')
                    return
                pt = self.plane_com


                
            else:
                if not self.plane_pt:
                    print('failed no COM')
                    return
                pt = self.plane_pt
                
            hits = [ob.ray_cast(imx * pt, imx * (pt + 5 * y)),
                    ob.ray_cast(imx * pt, imx * (pt + 5 * x)),
                    ob.ray_cast(imx * pt, imx * (pt - 5 * y)),
                    ob.ray_cast(imx * pt, imx * (pt - 5 * x))]
            

            dists = []
            inds = []
            for i, hit in enumerate(hits):
                if hit[2] != -1:
                    R = pt - hit[0]
                    dists.append(R.length)
                    inds.append(i)
            
            #make sure we had some hits!
            if any(dists):
                #pick the best one as the closest one to the pt       
                best_hit = hits[inds[dists.index(min(dists))]]       
                self.plane_pt = mx * best_hit[0]
                self.seed_face_index = best_hit[2]
                
                
            else:
                self.plane_pt = None
                self.seed_face_index = None
                self.verts = []
                self.verts_simple = []
                print('aim better')
                
            return self.plane_pt
            
    def handles_to_screen(self,context):
        
        region = context.region  
        rv3d = context.space_data.region_3d
        
        
        self.head.world_position = region_2d_to_location_3d(region, rv3d, (self.head.x, self.head.y),self.plane_pt)
        self.tail.world_position = region_2d_to_location_3d(region, rv3d, (self.tail.x, self.tail.y),self.plane_pt)
        
          
    def cut_object(self,context, ob, bme):
        
        mx = ob.matrix_world
        pt = self.plane_pt
        pno = self.plane_no
        indx = self.seed_face_index
        
        settings = common_utilities.get_settings()
        meth = settings.new_method
        if pt and pno:
            cross = contour_utilities.cross_section_seed(bme, mx, pt, pno, indx, debug = True, method = meth)   
            if cross and cross[0] and cross[1]:
                self.verts = [mx*v for v in cross[0]]
                self.edges = cross[1]   
        else:
            self.verts = []
            self.edges = []
        
    def simplify_cross(self,segments):
        if self.verts !=[] and self.edges != []:
            [self.verts_simple, self.eds_simple] = contour_utilities.space_evenly_on_path(self.verts, self.edges, segments, self.shift)
            
            if self.int_shift:
                self.verts_simple = contour_utilities.list_shift(self.verts_simple, self.int_shift)
            
    def update_com(self):
        if self.verts_simple != []:
            self.plane_com = contour_utilities.get_com(self.verts_simple)
        else:
            self.plane_com = None
    
    def adjust_cut_to_object_surface(self,ob):
        
        vecs = []
        rot = ob.matrix_world.to_quaternion()
        for v in self.verts_simple:
            closest = ob.closest_point_on_mesh(v)  #this will be in local coords!
            
            s_no = closest[1]
            
            vecs.append(self.plane_com + s_no)
        
        print(self.plane_no)    
        (com, no) = contour_utilities.calculate_best_plane(vecs)
        
        #TODO add some sanity checks
    
        #first sanity check...keep normal in same dir
        if self.plane_no.dot(rot * no) < 0:
            no *= -1
        
        self.plane_no = rot * no
        
        
        
        
    
    def generic_3_axis_from_normal(self):
        if self.plane_com:
            (self.vec_x, self.vec_y) = contour_utilities.generic_axes_from_plane_normal(self.plane_com, self.plane_no)
        
                       
    def derive_3_axis_control(self, method = 'FROM_VECS', n=0):
        '''
        args
        
        method: text enum in {'VIEW','FROM_VECS','FROM_VERT'}
        '''
        
        if len(self.verts_simple) and self.plane_com:

            
            #y vector
            y_vector = self.verts_simple[n] - self.plane_com
            y_vector.normalize()
            self.vec_y = y_vector
            
            #x vector
            x_vector = y_vector.cross(self.plane_no)
            x_vector.normalize()
            self.vec_x = x_vector
            
            
            #now the 4 points are in world space
            #we could use a vector...but transforming
            #to screen can be tricky with vectors as
            #opposed to locations.
            self.plane_x = self.plane_com + x_vector
            self.plane_y = self.plane_com + y_vector
            self.plane_z = self.plane_com + self.plane_no
            
            
            
        
    def analyze_relationship(self, other,debug = False):
        '''
        runs a series of quantitative assemsents of the spatial relationship
        to another cut line to assist in anticipating the the optimized
        connectivity data
        
        assume the other cutline has already been solidified and the only variation
        which can happen is on this line
        '''
        #requirements
        # both loops must have a verts simple
        
        
        #caclulate the center of mass of each loop using existing
        #verts simple since they are evenly spaced it will be a
        #good example
        COM_other = contour_utilities.get_com(other.verts_simple)
        COM_self = contour_utilities.get_com(self.verts_simple)
        
        #the vector pointing from the COM of the other cutline
        #to this cutline.  This will be our convention for
        #positive direciton
        delta_com_vect = COM_self - COM_other  
        #delta_com_vect.normalize()
        
        #the plane normals
        self_no = self.plane_no.copy()
        other_no = other.plane_no.copy()
        
        #if for some reason they aren't normalized...fix that
        self_no.normalize()
        other_no.normalize()
        
        #make sure the other normal is aligned with
        #the line from other to self for convention
        if other_no.dot(delta_com_vect) < 0:
            other_no = -1 * other_no
            
        #and now finally make the self normal is aligned too    
        if self_no.dot(other_no) < 0:
            self_no = -1 * self_no
        
        #how parallel are the loops?
        parallelism = self_no.dot(other_no)
        if debug > 1:
            print('loop paralellism = %f' % parallelism)
        
        #this may be important.
        avg_no = self_no.lerp(other_no, 0.5)
        
        #are the loops aimed at one another?
        #compare the delta COM vector to each normal
        self_aimed_other = self_no.dot(delta_com_vect.normalized())
        other_aimed_self = other_no.dot(delta_com_vect.normalized())
        
        aiming_difference = self_aimed_other - other_aimed_self
        if debug > 1:
            print('aiming difference = %f' % aiming_difference)
        #do we expect divergence or convergence?
        #remember other -> self is positive so enlarging
        #while traveling in this direction is divergence
        radi_self = contour_utilities.approx_radius(self.verts_simple, COM_self)
        radi_other = contour_utilities.approx_radius(other.verts_simple, COM_other)
        
        #if divergent or convergent....we will want to maximize
        #the opposite phenomenon with respect to the individual
        #connectors and teh delta COM line
        divergent = (radi_self - radi_other) > 0
        divergence = (radi_self - radi_other)**2 / ((radi_self - radi_other)**2 + delta_com_vect.length**2)
        divergence = math.pow(divergence, 0.5)
        if debug > 1:
            print('the loops are divergent: ' + str(divergent) + ' with a divergence of: ' + str(divergence))
        
        return [COM_self, delta_com_vect, divergent, divergence]
        
    def connectivity_analysis(self,other):
        
        
        COM_self = contour_utilities.get_com(self.verts_simple)
        COM_other = contour_utilities.get_com(other.verts_simple)
        delta_com_vect = COM_self - COM_other  #final - initial :: self - other
        delta_com_vect.normalize()
        

        
        ideal_to_com = 0
        for i, v in enumerate(self.verts_simple):
            connector = v - other.verts_simple[i]  #continue convention of final - initial :: self - other
            connector.normalize()
            align = connector.dot(delta_com_vect)

            #TODO: Debug statement here 
            if align < 0:
                align *= -1    
            ideal_to_com += align
        
        ideal_to_com = 1/len(self.verts_simple) * ideal_to_com
        
        return ideal_to_com
        
        
    def align_to_other(self,other, auto_align = True, direction_only = False):
        
        '''
        Modifies vert order of self to  provide best
        bridge between self verts and other loop
        '''
        verts_1 = other.verts_simple
        
        eds_1 = other.eds_simple
        
        #print('testing alignment')
        if eds_1 and 0 in eds_1[-1]:
            cyclic = True
            print('cyclic vert chain')
        else:
            cyclic = False
        
        if len(verts_1) != len(self.verts_simple):
            #print(len(verts_1))
            #print(len(self.verts_simple))
            print('non uniform loops, stopping until your developer gets smarter')
            return
            
        if cyclic:
            #another test to verify loop direction is to take
            #something reminiscint of the curl
            #since the loops in our case are guaranteed planar
            #(they come from cross sections) we can find a direction
            #from which to take the curl pretty easily
            V1_0 = verts_1[1] - verts_1[0]
            V1_1 = verts_1[2] - verts_1[1]
            
            V2_0 = self.verts_simple[1] - self.verts_simple[0]
            V2_1 = self.verts_simple[2] - self.verts_simple[1]
            
            no_1 = V1_0.cross(V1_1)
            no_1.normalize()
            no_2 = V2_0.cross(V2_1)
            no_2.normalize()
            
            #in general, we don't know that the loops are
            #oriented in the same direction.  However the contour
            #cut series class should hanlde that
            if no_1.dot(no_2) < 0:
                no_2 = -1 * no_2
            
            #average the two directions    
            ideal_direction = no_1.lerp(no_1,.5)
        
            curl_1 = contour_utilities.discrete_curl(verts_1, ideal_direction)
            curl_2 = contour_utilities.discrete_curl(self.verts_simple, ideal_direction)
            
            if curl_1 * curl_2 < 0:
                print('reversing derived loop direction')
                print('curl1: %f and curl2: %f' % (curl_1,curl_2))
                self.verts_simple.reverse()
                self.verts.reverse()
                self.shift *= -1

        else:
            #if the segement is not cyclic
            #all we have to do is compare the endpoints
            Vtotal_1 = verts_1[-1] - verts_1[0]
            Vtotal_2 = self.verts_simple[-1] - self.verts_simple[0]
    
            if Vtotal_1.dot(Vtotal_2) < 0:
                print('reversing path 2')
                self.verts_simple.reverse()
                self.verts.reverse()
                
        
        
        if not direction_only:
            #iterate all verts and "handshake problem" them
            #into a dictionary?  That's not very efficient!
            if auto_align:
                self.shift = 0
                self.int_shift = 0
                self.simplify_cross(len(self.eds_simple))
            edge_len_dict = {}
            for i in range(0,len(verts_1)):
                for n in range(0,len(self.verts_simple)):
                    edge = (i,n)
                    vect = self.verts_simple[n] - verts_1[i]
                    edge_len_dict[edge] = vect.length
            
            shift_lengths = []
            for shift in range(0,len(self.verts_simple)):
                tmp_len = 0
                #tmp_cross = 0
                for i in range(0, len(self.verts_simple)):
                    shift_mod = int(math.fmod(i+shift, len(self.verts_simple)))
                    tmp_len += edge_len_dict[(i,shift_mod)]
                shift_lengths.append(tmp_len)
                   
            final_shift = shift_lengths.index(min(shift_lengths))
            if final_shift != 0:
                #print('pre rough shift alignment % f' % self.connectivity_analysis(other))
                #print("rough shifting verts by %i segments" % final_shift)
                self.int_shift = final_shift
                self.verts_simple = contour_utilities.list_shift(self.verts_simple, final_shift)
                #print('post rough shift alignment % f' % self.connectivity_analysis(other))
            
            if auto_align and cyclic:
                alignment_quality = self.connectivity_analysis(other)
                #pct_change = 1
                left_bound = -1
                right_bound = 1
                iterations = 0
                while iterations < 20:
                    
                    iterations += 1
                    width = right_bound - left_bound
                    
                    self.shift = 0.5 * (left_bound + right_bound)
                    self.simplify_cross(len(self.eds_simple)) #TODO not sure this needs to happen here
                    #self.verts_simple = contour_utilities.list_shift(self.verts_simple, final_shift)
                    alignment_quality = self.connectivity_analysis(other)
                    
                    self.shift = left_bound
                    self.simplify_cross(len(self.eds_simple))
                    #self.verts_simple = contour_utilities.list_shift(self.verts_simple, final_shift)
                    alignment_quality_left = self.connectivity_analysis(other)
                    
                    self.shift = right_bound
                    self.simplify_cross(len(self.eds_simple))
                    #self.verts_simple = contour_utilities.list_shift(self.verts_simple, final_shift)
                    alignment_quality_right = self.connectivity_analysis(other)
                    
                    if alignment_quality_left < alignment_quality and alignment_quality_right < alignment_quality:
                        
                        left_bound += width*1/8
                        right_bound -= width*1/8
                        
                        
                    elif alignment_quality_left > alignment_quality and alignment_quality_right > alignment_quality:
                        
                        if alignment_quality_right > alignment_quality_left:
                            left_bound = right_bound - 0.75 * width
                        else:
                            right_bound = left_bound + 0.75* width
                        
                    elif alignment_quality_left < alignment_quality and alignment_quality_right > alignment_quality:
                        #print('move to the right')
                        #right becomes the new middle
                        left_bound += width * 1/4
                
                    elif alignment_quality_left > alignment_quality and alignment_quality_right < alignment_quality:
                        #print('move to the left')
                        #right becomes the new middle
                        right_bound -= width * 1/4
                        
                        
                    #print('pct change iteration %i was %f' % (iterations, pct_change))
                    #print(alignment_quality)
                    #print(alignment_quality_left)
                    #print(alignment_quality_right)
                #print('converged or didnt in %i iterations' % iterations)
                #print('final alignment quality is %f' % alignment_quality)
                self.shift += self.int_shift
                self.int_shift = 0
                
    def active_element(self,context,x,y):
        settings = common_utilities.get_settings()
        
        if self.head: #this makes sure the head and tail haven't been removed
            active_head = self.head.mouse_over(x, y)
            active_tail = self.tail.mouse_over(x, y)
        else:
            active_head = False
            active_tail = False
        #active_tan = self.plane_tan.mouse_over(x, y)
        
        

        if self.verts_simple and len(self.verts_simple):
            mouse_loc = Vector((x,y))
            #Check by testing distance to all edges
            active_self = False
            for ed in self.eds_simple:
                
                if self.verts_simple_visible[ed[0]] and self.verts_simple_visible[ed[1]]:
                    a  = location_3d_to_region_2d(context.region, context.space_data.region_3d,self.verts_simple[ed[0]])
                    b = location_3d_to_region_2d(context.region, context.space_data.region_3d,self.verts_simple[ed[1]])
                
                    if a and b:
                
                        intersect = intersect_point_line(mouse_loc.to_3d(), a.to_3d(),b.to_3d())
                    
                        if intersect:
                            dist = (intersect[0].to_2d() - mouse_loc).length_squared
                            bound = intersect[1]
                            if (dist < 100) and (bound < 1) and (bound > 0):
                                active_self = True
                                break
            
        else:
            active_self = False
            '''
            region = context.region  
            rv3d = context.space_data.region_3d
            vec = region_2d_to_vector_3d(region, rv3d, (x,y))
            loc = region_2d_to_location_3d(region, rv3d, (x,y), vec)
            
            line_a = loc
            line_b = loc + vec
            #ray to plane
            hit = intersect_line_plane(line_a, line_b, self.plane_pt, self.plane_no)
            if hit:
                mouse_in_loop = contour_utilities.point_inside_loop_almost3D(hit, self.verts_simple, self.plane_no, p_pt = self.plane_pt, threshold = .01, debug = False)
                if mouse_in_loop:
                    self.geom_color = (.8,0,.8,0.5)
                    self.line_width = 2.5 * settings.line_thick
                else:
                    self.geom_color = (0,1,0,0.5)
                    self.line_width = settings.line_thick
                
            
        mouse_loc = Vector((x,y,0))
        head_loc = Vector((self.head.x, self.head.y, 0))
        tail_loc = Vector((self.tail.x, self.tail.y, 0))
        intersect = intersect_point_line(mouse_loc, head_loc, tail_loc)
        
        dist = (intersect[0] - mouse_loc).length_squared
        bound = intersect[1]
        active_self = (dist < 100) and (bound < 1) and (bound > 0) #TODO:  make this a sensitivity setting
        '''
        #they are all clustered together
        if active_head and active_tail and active_self: 
            
            return self.head
        
        elif active_tail:
            #print('returning tail')
            return self.tail
        
        elif active_head:
            #print('returning head')
            return self.head
        
        #elif active_tan:
            #return self.plane_tan
        
        elif active_self:
            #print('returning line')
            return self
        
        else:
            #print('returning None')
            return None

class CutLineManipulatorWidget(object):
    def __init__(self,context, settings, ob, bme, 
                 cut_line,cut_path,
                 x,y,
                 hotkey = False):
        
        self.desc = 'WIDGET'
        self.cut_line = cut_line
        self.x = x
        self.y = y
        self.hotkey = hotkey
        self.initial_x = None
        self.initial_y = None
        
        #this will get set later by interaction
        self.transform = False
        self.transform_mode = None
        
        self.ob = ob
        
            
        self.color = (settings.widget_color[0], settings.widget_color[1],settings.widget_color[2],1)
        self.color2 = (settings.widget_color2[0], settings.widget_color2[1],settings.widget_color2[2],1)
        self.color3 = (settings.widget_color3[0], settings.widget_color3[1],settings.widget_color3[2],1)
        self.color4 = (settings.widget_color4[0], settings.widget_color4[1],settings.widget_color4[2],1)
        self.color5 = (settings.widget_color5[0], settings.widget_color5[1],settings.widget_color5[2],1)
        
        self.radius = settings.widget_radius
        self.inner_radius = settings.widget_radius_inner
        self.line_width = settings.widget_thickness
        self.line_width2 = settings.widget_thickness2
        self.arrow_size = settings.arrow_size
        
        self.arrow_size2 = settings.arrow_size2
        
        self.arc_radius = .5 * (self.radius + self.inner_radius)
        self.screen_no = None
        self.angle = 0
        
        #intitial conditions for "undo"
        if self.cut_line.plane_com:
            self.initial_com = self.cut_line.plane_com.copy()
        else:
            self.initial_com = None
            
        if self.cut_line.plane_pt:
            self.initial_plane_pt = self.cut_line.plane_pt.copy()
        else:
            self.initial_plane_pt = None
        
        self.vec_x = self.cut_line.vec_x.copy()
        self.vec_y = self.cut_line.vec_y.copy()
        self.initial_plane_no = self.cut_line.plane_no.copy()
        self.initial_seed = self.cut_line.seed_face_index
        self.initial_shift = self.cut_line.shift
                
        #find out where the cut is
        ind = cut_path.cuts.index(cut_line)
        self.path_behind = cut_path.backbone[ind]
        if ind+1 < len(cut_path.backbone):
            self.path_ahead = cut_path.backbone[ind+1]
        else:
            self.path_ahead = None
        
        
        if ind > 0:
            self.b = cut_path.cuts[ind-1].plane_com
            self.b_no = cut_path.cuts[ind-1].plane_no
        else:
            self.b = None
            self.b_no = None
        
        if ind < len(cut_path.cuts)-1:
            self.a = cut_path.cuts[ind+1].plane_com
            self.a_no = cut_path.cuts[ind+1].plane_no
        else:
            self.a = None
            self.a_no = None
            
        self.wedge_1 = []
        self.wedge_2 = []
        self.wedge_3 = []
        self.wedge_4 = []
        
        self.arrow_1 = []
        self.arrow_2 = []
        
        self.arc_arrow_1 = []
        self.arc_arrow_2 = []
    
    def user_interaction(self, context, mouse_x,mouse_y, shift = False):
        '''
        analyse mouse coords x,y
        return [type, transform]
        '''
        
        mouse_vec = Vector((mouse_x,mouse_y))
        
        #In hotkey mode G, this will be spawned at the mouse
        #essentially being the initial mouse
        widget_screen = Vector((self.x,self.y))
        mouse_wrt_widget = mouse_vec - widget_screen
        com_screen = location_3d_to_region_2d(context.region, context.space_data.region_3d,self.initial_com)
        
        region = context.region
        rv3d = context.space_data.region_3d
        world_mouse = region_2d_to_location_3d(region, rv3d, (mouse_x, mouse_y), self.initial_com)
        world_widget = region_2d_to_location_3d(region, rv3d, (self.x, self.y), self.initial_com)
        
        
        if not self.transform and not self.hotkey:
            #this represents a switch...since by definition we were not transforming to begin with
            if mouse_wrt_widget.length > self.inner_radius:
                self.transform = True
                
                #identify which quadrant we are in
                screen_angle = math.atan2(mouse_wrt_widget[1], mouse_wrt_widget[0])
                loc_angle = screen_angle - self.angle
                loc_angle = math.fmod(loc_angle + 4 * math.pi, 2 * math.pi)  #correct for any negatives
                
                if loc_angle >= 1/4 * math.pi and loc_angle < 3/4 * math.pi:
                    #we are in the  left quadrant...which is perpendicular
                    self.transform_mode = 'EDGE_SLIDE'
                elif loc_angle >= 3/4 * math.pi and loc_angle < 5/4 * math.pi:
                    self.transform_mode = 'ROTATE_VIEW'
                elif loc_angle >= 5/4 * math.pi and loc_angle < 7/4 * math.pi:
                    self.transform_mode = 'EDGE_SLIDE'
                else:
                    self.transform_mode = 'ROTATE_VIEW_PERPENDICULAR'
                    
                print(self.transform_mode)
                
            return {'DO_NOTHING'}  #this tells it whether to recalc things
            
        #we were transforming but went back in the circle
        if mouse_wrt_widget.length < self.inner_radius and not self.hotkey:
            
            self.cancel_transform()
            self.transform = False
            self.transform_mode = None
            
            return {'RECUT'}
            
        
        if self.transform_mode == 'EDGE_SLIDE':
            
            world_vec = world_mouse - world_widget
            screen_dist = mouse_wrt_widget.length - self.inner_radius
            
            factor = 1 if self.hotkey else screen_dist/mouse_wrt_widget.length
            if shift:
                factor *= 1/5
                
            if self.a:
                a_screen = location_3d_to_region_2d(context.region, context.space_data.region_3d,self.a)
                vec_a_screen = a_screen - com_screen
                vec_a_screen_norm = vec_a_screen.normalized()
                
                vec_a = self.a - self.initial_com
                vec_a_dir = vec_a.normalized()
                
                if mouse_wrt_widget.dot(vec_a_screen_norm) > 0 and factor * mouse_wrt_widget.dot(vec_a_screen_norm) < vec_a_screen.length:
                    translate = factor * mouse_wrt_widget.dot(vec_a_screen_norm)/vec_a_screen.length * vec_a
                    
                    if self.a_no.dot(self.initial_plane_no) < 0:
                        v = -1 * self.a_no
                    else:
                        v = self.a_no
                    
                    scale = factor * mouse_wrt_widget.dot(vec_a_screen_norm)/vec_a_screen.length
                    quat = contour_utilities.rot_between_vecs(self.initial_plane_no, v, factor = scale)
                    inter_no = quat * self.initial_plane_no
                    
                    new_com = self.initial_com + translate
                    self.cut_line.plane_com = new_com
                    self.cut_line.plane_no = inter_no
                    
                    self.cut_line.vec_x = quat * self.vec_x.copy()
                    self.cut_line.vec_y = quat * self.vec_y.copy()
                    
                    intersect = contour_utilities.intersect_path_plane(self.path_ahead, new_com, inter_no, mode = 'FIRST')
                    
                    if intersect[0]:
                        proposed_point = intersect[0]
                        snap = self.ob.closest_point_on_mesh(self.ob.matrix_world.inverted() * proposed_point)
                        self.cut_line.plane_pt = self.ob.matrix_world * snap[0]
                        self.cut_line.seed_face_index = snap[2]
                    else:
                        self.cancel_transform()
                        
                    return {'RECUT'}
                
                if not self.b and world_vec.dot(vec_a_dir) < 0:
                    translate = factor * world_vec.dot(self.initial_plane_no) * self.initial_plane_no
                    self.cut_line.plane_com = self.initial_com + translate
                    intersect = contour_utilities.intersect_path_plane(self.path_behind, self.cut_line.plane_com, self.initial_plane_no, mode = 'FIRST')
                    
                    if intersect[0]:
                        proposed_point = intersect[0]
                        snap = self.ob.closest_point_on_mesh(self.ob.matrix_world.inverted() * proposed_point)
                        self.cut_line.plane_pt = self.ob.matrix_world * snap[0]
                        self.cut_line.seed_face_index = snap[2]
                    else:
                        self.cancel_transform()
                    
                    return {'RECUT'}
            
            if self.b:
                b_screen = location_3d_to_region_2d(context.region, context.space_data.region_3d,self.b)
                vec_b_screen = b_screen - com_screen
                vec_b_screen_norm = vec_b_screen.normalized()
                
                vec_b = self.b - self.initial_com
                vec_b_dir = vec_b.normalized()
                
                if mouse_wrt_widget.dot(vec_b_screen_norm) > 0 and factor * mouse_wrt_widget.dot(vec_b_screen_norm) < vec_b_screen.length:
                    translate = factor * mouse_wrt_widget.dot(vec_b_screen_norm)/vec_b_screen.length * vec_b
                    
                    if self.b_no.dot(self.initial_plane_no) < 0:
                        v = -1 * self.b_no
                    else:
                        v = self.b_no
                    
                    scale = factor * mouse_wrt_widget.dot(vec_b_screen_norm)/vec_b_screen.length
                    quat = contour_utilities.rot_between_vecs(self.initial_plane_no, v, factor = scale)
                    inter_no = quat * self.initial_plane_no
                    
                    new_com = self.initial_com + translate
                    self.cut_line.plane_com = new_com
                    self.cut_line.plane_no = inter_no
                    self.cut_line.vec_x = quat * self.vec_x.copy()
                    self.cut_line.vec_y = quat * self.vec_y.copy()
                    
                    #TODO:  what if we don't get a proposed point?
                    proposed_point = contour_utilities.intersect_path_plane(self.path_behind, new_com, inter_no, mode = 'FIRST')[0]
                    
                    if proposed_point:
                        snap = self.ob.closest_point_on_mesh(self.ob.matrix_world.inverted() * proposed_point)
                        self.cut_line.plane_pt = self.ob.matrix_world * snap[0]
                        self.cut_line.seed_face_index = snap[2]
                    else:
                        self.cancel_transform()
                    
                    return {'RECUT'}
                    
                if not self.a and world_vec.dot(vec_b_dir) < 0:
                    translate = factor * world_vec.dot(self.initial_plane_no) * self.initial_plane_no
                    self.cut_line.plane_com = self.initial_com + translate
                    proposed_point = contour_utilities.intersect_path_plane(self.path_ahead, self.cut_line.plane_com, self.initial_plane_no, mode = 'FIRST')[0]
                    
                    if proposed_point:
                        snap = self.ob.closest_point_on_mesh(self.ob.matrix_world.inverted() * proposed_point)
                        self.cut_line.plane_pt = self.ob.matrix_world * snap[0]
                        self.cut_line.seed_face_index = snap[2]
                    else:
                        self.cancel_transform()
                    
                    return {'RECUT'}
            
            if not self.a and not self.b:
                
                translate = factor * world_vec.dot(self.initial_plane_no) * self.initial_plane_no
                self.cut_line.plane_com = self.initial_com + translate
                
                proposed_point = contour_utilities.intersect_path_plane(self.path_ahead, self.cut_line.plane_com, self.initial_plane_no, mode = 'FIRST')[0]
                if not proposed_point:
                    
                    proposed_point = contour_utilities.intersect_path_plane(self.path_behind, self.cut_line.plane_com, self.initial_plane_no, mode = 'FIRST')[0]
                if proposed_point:        
                    snap = self.ob.closest_point_on_mesh(self.ob.matrix_world.inverted() * proposed_point)
                    self.cut_line.plane_pt = self.ob.matrix_world * snap[0]
                    self.cut_line.seed_face_index = snap[2]
                else:
                    self.cancel_transform()
                
                return {'RECUT'}
            
            return {'DO_NOTHING'}
        
        if self.transform_mode == 'NORMAL_TRANSLATE':
            #the pixel distance used to scale the translation
            screen_dist = mouse_wrt_widget.length - self.inner_radius
            
            world_vec = world_mouse - world_widget
            translate = screen_dist/mouse_wrt_widget.length * world_vec.dot(self.initial_plane_no) * self.initial_plane_no
            
            self.cut_line.plane_com = self.initial_com + translate
            
            return {'REHIT','RECUT'}
        
        if self.transform_mode in {'ROTATE_VIEW_PERPENDICULAR', 'ROTATE_VIEW'}:
            
            #establish the transform axes
            axis_1  = rv3d.view_rotation * Vector((0,0,1))
            axis_1.normalize()
            
            axis_2 = self.initial_plane_no.cross(axis_1)
            axis_2.normalize()
            
            #identify which quadrant we are in
            screen_angle = math.atan2(mouse_wrt_widget[1], mouse_wrt_widget[0])
            
            if self.transform_mode == 'ROTATE_VIEW':
                if not self.hotkey:
                    rot_angle = screen_angle - self.angle #+ .5 * math.pi  #Mystery
                    rot_angle = math.fmod(rot_angle + 3 * math.pi, 2 * math.pi)  #correct for any negatives
                    
                else:
                    init_angle = math.atan2(self.initial_y - self.y, self.initial_x - self.x)
                    init_angle = math.fmod(init_angle + 4 * math.pi, 2 * math.pi)
                    rot_angle = screen_angle - init_angle
                    rot_angle = math.fmod(rot_angle + 2 * math.pi, 2 * math.pi)  #correct for any negatives
                    
                
                sin = math.sin(rot_angle/2)
                cos = math.cos(rot_angle/2)
                #quat = Quaternion((cos, sin*world_x[0], sin*world_x[1], sin*world_x[2]))
                quat = Quaternion((cos, sin*axis_1[0], sin*axis_1[1], sin*axis_1[2]))
                                    
            else:
                rot_angle = screen_angle - self.angle + math.pi #+ .5 * math.pi  #Mystery
                rot_angle = math.fmod(rot_angle + 4 * math.pi, 2 * math.pi)  #correct for any negatives
                sin = math.sin(rot_angle/2)
                cos = math.cos(rot_angle/2)
                #quat = Quaternion((cos, sin*world_y[0], sin*world_y[1], sin*world_y[2]))
                quat = Quaternion((cos, sin*axis_2[0], sin*axis_2[1], sin*axis_2[2])) 
            
            new_no = self.initial_plane_no.copy() #its not rotated yet
            new_no.rotate(quat)
            
            new_x = self.vec_x.copy() #its not rotated yet
            new_x.rotate(quat)
           
            new_y = self.vec_y.copy()
            new_y.rotate(quat)
            
            self.cut_line.vec_x = new_x
            self.cut_line.vec_y = new_y
            self.cut_line.plane_no = new_no
            
            new_pt = contour_utilities.intersect_path_plane(self.path_ahead, self.initial_com, new_no, mode = 'FIRST')
            if not new_pt[0]:
                new_pt = contour_utilities.intersect_path_plane(self.path_behind, self.initial_com, new_no, mode = 'FIRST')
            
            if new_pt[0]:
                snap = self.ob.closest_point_on_mesh(self.ob.matrix_world.inverted() * new_pt[0])
                self.cut_line.plane_pt = self.ob.matrix_world * snap[0]
                self.cut_line.seed_face_index = snap[2] 
            else:
                self.cancel_transform()
            return {'RECUT'}
        
        # unknown state
        print('ERROR: unknown self.transform_mode = "%s"' % self.transform_mode)
        return {'DO_NOTHING'}

    def derive_screen(self,context):
        rv3d = context.space_data.region_3d
        view_z = rv3d.view_rotation * Vector((0,0,1))
        if view_z.dot(self.initial_plane_no) > -.95 and view_z.dot(self.initial_plane_no) < .95:
            
            imx = rv3d.view_matrix.inverted()
            #http://www.lighthouse3d.com/tutorials/glsl-tutorial/the-normal-matrix/
            #Therefore the correct matrix to transform the normal is the 
            #transpose of the inverse of the M matrix. 
            normal_3d = imx.transposed() * self.cut_line.plane_no
            self.screen_no = Vector((normal_3d[0],normal_3d[1]))
            
            self.angle = math.atan2(self.screen_no[1],self.screen_no[0]) - 1/2 * math.pi
        else:
            self.screen_no = None
        
        
        up = self.angle + 1/2 * math.pi
        down = self.angle + 3/2 * math.pi
        left = self.angle + math.pi
        right =  self.angle
        
        deg_45 = .25 * math.pi
        
        self.wedge_1 = contour_utilities.pi_slice(self.x,self.y,self.inner_radius,self.radius,up - deg_45,up + deg_45, 10 ,t_fan = False)
        self.wedge_2 = contour_utilities.pi_slice(self.x,self.y,self.inner_radius,self.radius,left - deg_45,left + deg_45, 10 ,t_fan = False)
        self.wedge_3 = contour_utilities.pi_slice(self.x,self.y,self.inner_radius,self.radius,down - deg_45,down + deg_45, 10 ,t_fan = False)
        self.wedge_4 = contour_utilities.pi_slice(self.x,self.y,self.inner_radius,self.radius,right - deg_45,right + deg_45, 10 ,t_fan = False)
        self.wedge_1.append(self.wedge_1[0])
        self.wedge_2.append(self.wedge_2[0])
        self.wedge_3.append(self.wedge_3[0])
        self.wedge_4.append(self.wedge_4[0])
        
        
        self.arc_arrow_1 = contour_utilities.arc_arrow(self.x, self.y, self.arc_radius, left - deg_45+.2, left + deg_45-.2, 10, self.arrow_size, 2*deg_45, ccw = True)
        self.arc_arrow_2 = contour_utilities.arc_arrow(self.x, self.y, self.arc_radius, right - deg_45+.2, right + deg_45-.2, 10, self.arrow_size,2*deg_45, ccw = True)
  
        self.inner_circle = contour_utilities.simple_circle(self.x, self.y, self.inner_radius, 20)
        
        #New screen coords, leaving old ones until completely transitioned
        self.arc_arrow_rotate_ccw = contour_utilities.arc_arrow(self.x, self.y, self.radius, left - deg_45-.3, left + deg_45+.3, 10, self.arrow_size, 2*deg_45, ccw = True)
        self.arc_arrow_rotate_cw = contour_utilities.arc_arrow(self.x, self.y, self.radius, left - deg_45-.3, left + deg_45+.3, 10, self.arrow_size, 2*deg_45, ccw = False)
        
        self.inner_circle = contour_utilities.simple_circle(self.x, self.y, self.inner_radius, 20)
        self.inner_circle.append(self.inner_circle[0])
        
        self.outer_circle_1 = contour_utilities.arc_arrow(self.x, self.y, self.radius, up, down,10, self.arrow_size,2*deg_45, ccw = True)
        self.outer_circle_2 = contour_utilities.arc_arrow(self.x, self.y, self.radius, down, up,10, self.arrow_size,2*deg_45, ccw = True)
        
        b = self.arrow_size2
        self.trans_arrow_up = contour_utilities.arrow_primitive(self.x +math.cos(up) * self.radius, self.y + math.sin(up)*self.radius, right, b, b, b, b/2)
        self.trans_arrow_down = contour_utilities.arrow_primitive(self.x + math.cos(down) * self.radius, self.y + math.sin(down) * self.radius, left, b, b, b, b/2)
    
    def cancel_transform(self):
        
        #reset our initial values
        self.cut_line.plane_com = self.initial_com
        self.cut_line.plane_no = self.initial_plane_no
        self.cut_line.plane_pt = self.initial_plane_pt
        self.cut_line.shift = self.initial_shift
        self.cut_line.vec_x = self.vec_x
        self.cut_line.vec_y = self.vec_y
        self.cut_line.seed_face_index = self.initial_seed
                              
    def draw(self, context):
        
        settings = common_utilities.get_settings()
        
        if self.a:
            common_drawing.draw_3d_points(context, [self.a], self.color3, 5)
        if self.path_ahead and self.path_ahead != [] and settings.debug > 1:
            common_drawing.draw_3d_points(context, self.path_ahead, self.color5, 6)
        if self.b:
            common_drawing.draw_3d_points(context, [self.b], self.color3, 5)
        if self.path_behind and self.path_behind != [] and settings.debug > 1:
            common_drawing.draw_3d_points(context, self.path_behind, self.color3, 6)
            
        if not self.transform and not self.hotkey:
            
            l = len(self.arc_arrow_1)
            
            #draw outer circle half
            common_drawing.draw_polyline_from_points(context, self.outer_circle_1[0:l-2], self.color4, self.line_width, "GL_LINES")
            common_drawing.draw_polyline_from_points(context, self.outer_circle_2[0:l-2], self.color4, self.line_width, "GL_LINES")
            
            #draw outer translation arrows
            #common_drawing.draw_polyline_from_points(context, self.trans_arrow_up, self.color3, self.line_width, "GL_LINES")
            #common_drawing.draw_polyline_from_points(context, self.trans_arrow_down, self.color3, self.line_width, "GL_LINES")            
            
            
            common_drawing.draw_outline_or_region("GL_POLYGON", self.trans_arrow_down[:4], self.color3)
            common_drawing.draw_outline_or_region("GL_POLYGON", self.trans_arrow_up[:4], self.color3)
            common_drawing.draw_outline_or_region("GL_POLYGON", self.trans_arrow_down[4:], self.color3)
            common_drawing.draw_outline_or_region("GL_POLYGON", self.trans_arrow_up[4:], self.color3)
            
            #draw a line perpendicular to arc
            #point_1 = Vector((self.x,self.y)) + 2/3 * (self.inner_radius + self.radius) * Vector((math.cos(self.angle), math.sin(self.angle)))
            #point_2 = Vector((self.x,self.y)) + 1/3 * (self.inner_radius + self.radius) * Vector((math.cos(self.angle), math.sin(self.angle)))
            #common_drawing.draw_polyline_from_points(context, [point_1, point_2], self.color3, self.line_width, "GL_LINES")
            
            
            #try the straight red line
            point_1 = Vector((self.x,self.y)) #+ self.inner_radius * Vector((math.cos(self.angle), math.sin(self.angle)))
            point_2 = Vector((self.x,self.y)) +  self.radius * Vector((math.cos(self.angle), math.sin(self.angle)))
            common_drawing.draw_polyline_from_points(context, [point_1, point_2], self.color2, self.line_width2 , "GL_LINES")
            
            point_1 = Vector((self.x,self.y))# + -self.inner_radius * Vector((math.cos(self.angle), math.sin(self.angle)))
            point_2 = Vector((self.x,self.y)) +  -self.radius * Vector((math.cos(self.angle), math.sin(self.angle)))
            common_drawing.draw_polyline_from_points(context, [point_1, point_2], self.color2, self.line_width, "GL_LINES")
            
            #drawa arc 2
            #common_drawing.draw_polyline_from_points(context, self.arc_arrow_2[:l-1], self.color2, self.line_width, "GL_LINES")
            
            #new rotation thingy
            common_drawing.draw_polyline_from_points(context, self.arc_arrow_rotate_ccw[:l-1], self.color, self.line_width2, "GL_LINES")
            common_drawing.draw_polyline_from_points(context, self.arc_arrow_rotate_cw[:l-1], self.color, self.line_width2, "GL_LINES")
            
            #other half the tips
            common_drawing.draw_polyline_from_points(context, [self.arc_arrow_rotate_ccw[l-1],self.arc_arrow_rotate_ccw[l-3]], (0,0,1,1), self.line_width2, "GL_LINES")
            common_drawing.draw_polyline_from_points(context, [self.arc_arrow_rotate_cw[l-1],self.arc_arrow_rotate_cw[l-3]], (0,0,1,1), self.line_width2, "GL_LINES")
            
            #draw an up and down arrow
            #point_1 = Vector((self.x,self.y)) + 2/3 * (self.inner_radius + self.radius) * Vector((math.cos(self.angle + .5*math.pi), math.sin(self.angle + .5*math.pi)))
            #point_2 = Vector((self.x,self.y)) + 1/3 * (self.inner_radius + self.radius) * Vector((math.cos(self.angle + .5*math.pi), math.sin(self.angle + .5*math.pi)))
            #common_drawing.draw_polyline_from_points(context, [point_1, point_2], self.color, self.line_width, "GL_LINES")
            
            #draw little hash
            #point_1 = Vector((self.x,self.y)) + 2/3 * (self.inner_radius + self.radius) * Vector((math.cos(self.angle +  3/2 * math.pi), math.sin(self.angle +  3/2 * math.pi)))
            #point_2 = Vector((self.x,self.y)) + 1/3 * (self.inner_radius + self.radius) * Vector((math.cos(self.angle +  3/2 * math.pi), math.sin(self.angle +  3/2 * math.pi)))
            #common_drawing.draw_polyline_from_points(context, [point_1, point_2], self.color, self.line_width, "GL_LINES")
        
        elif self.transform_mode:

            #draw a small inner circle
            common_drawing.draw_polyline_from_points(context, self.inner_circle, self.color, self.line_width, "GL_LINES")
            
            
            if not settings.live_update:
                if self.transform_mode in {"NORMAL_TRANSLATE", "EDGE_SLIDE"}:
                    #draw a line representing the COM translation
                    points = [self.initial_com, self.cut_line.plane_com]
                    common_drawing.draw_3d_points(context, points, self.color3, 4)
                    common_drawing.draw_polyline_from_3dpoints(context, points, self.color ,2 , "GL_STIPPLE")
                    
                else:
                    rv3d = context.space_data.region_3d

                    p1 = self.cut_line.plane_com
                    p1_2d =  location_3d_to_region_2d(context.region, context.space_data.region_3d, p1)
                    #p2_2d =  location_3d_to_region_2d(context.region, context.space_data.region_3d, p2)
                    #p3_2d =  location_3d_to_region_2d(context.region, context.space_data.region_3d, p3)
                    
                    
                    imx = rv3d.view_matrix.inverted()
                    vec_screen = imx.transposed() * self.cut_line.plane_no
                    vec_2d = Vector((vec_screen[0],vec_screen[1]))

                    p4_2d = p1_2d + self.radius * vec_2d
                    p6_2d = p1_2d - self.radius * vec_2d
                    
                    common_drawing.draw_points(context, [p1_2d, p4_2d, p6_2d], self.color3, 5)
                    common_drawing.draw_polyline_from_points(context, [p6_2d, p4_2d], self.color ,2 , "GL_STIPPLE")
            
class ContourStatePreserver(object):
    def __init__(self, operator):
        self.mode = operator.mode

        if operator.sel_path:
            self.sel_path = operator.cut_paths.index(operator.sel_path)

        else:
            self.sel_path = None
            
        if operator.sel_loop and operator.sel_path and operator.sel_loop in operator.sel_path.cuts:
            self.sel_loop = operator.sel_path.cuts.index(operator.sel_loop)

        else:
            self.sel_loop = None
        
        #consider adding nsegments, nlopos etc....but why?
        
    def push_state(self, operator):
        
        operator.mode = self.mode
        
        if self.sel_path != None:  #because it can be a 0 integer
            operator.sel_path = operator.cut_paths[self.sel_path]
        else:
            operator.sel_path = None
        
        if self.sel_loop != None and self.sel_path != None:
            operator.sel_loop = operator.cut_paths[self.sel_path].cuts[self.sel_loop]
        else:
            operator.sel_loop = None
        