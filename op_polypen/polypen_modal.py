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

from bmesh.types import BMVert, BMEdge, BMFace

from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree
from mathutils.geometry import intersect_point_tri, intersect_point_tri_2d

import math
import os
import copy

from ..modaloperator import ModalOperator

from ..lib import common_utilities
from ..lib.common_utilities import showErrorMessage, get_source_object, get_target_object
from ..lib.common_utilities import setup_target_object, invert_matrix
from ..lib.common_utilities import bversion, selection_mouse
from ..lib.common_utilities import point_inside_loop2d, get_object_length_scale, dprint, frange
from ..lib.common_utilities import closest_t_and_distance_point_to_line_segment, ray_cast_point_bvh
from ..lib.classes.profiler.profiler import Profiler
from ..cache import mesh_cache, polypen_undo_cache, object_validation, is_object_valid, write_mesh_cache, clear_mesh_cache

from ..lib.common_drawing_bmesh import BMeshRender
from ..lib import common_drawing_bmesh

class CGC_Polypen(ModalOperator):
    ''' CG Cookie Polypen Modal Editor '''
    
    bl_category    = "Retopology"
    bl_idname      = "cgcookie.polypen"
    bl_label       = "Polypen"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    def __init__(self):
        FSM = {}
        FSM['move vert'] = self.modal_move_vert
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
        if context.mode == 'EDIT_MESH' and get_source_object() == context.active_object:
            showErrorMessage('Cannot use %s when editing the source object' % (self.bl_label))
            return False
        if get_source_object().type != 'MESH':
            showErrorMessage('Source must be a mesh object')
            return False
        if len(get_source_object().data.polygons) <= 0:
            showErrorMessage('Source must have at least one face')
            return False
        if get_target_object() and get_target_object().type != 'MESH':
            showErrorMessage('Target must be a mesh object')
            return False
        if self.settings.source_object == self.settings.target_object and self.settings.source_object and self.settings.target_object:
            showErrorMessage('Source and Target cannot be same object')
            return False
        
        return True
    
    def start(self, context):
        ''' Called when tool has been invoked '''
        
        if context.mode == 'OBJECT':
            self.src_object = get_source_object()
            nm_polypen = self.src_object.name + "_polypen"
            self.tar_object = setup_target_object(nm_polypen, self.src_object, bmesh.new())
            self.tar_object.select = True
            bpy.context.scene.objects.active = self.tar_object
                
            bpy.ops.object.mode_set(mode='EDIT')
            self.was_objectmode = True
        else:
            self.was_objectmode = False
        
        self.src_object = get_source_object()
        self.mx = self.src_object.matrix_world
        self.imx = invert_matrix(self.mx)
        is_valid = is_object_valid(self.src_object)
        
        self.vis_objects = [] # [o for o in bpy.data.objects if o.type == 'MESH' and o.is_visible(context.scene)]
        self.vis_bmrender = [BMeshRender(o) for o in self.vis_objects]
        
        if not is_valid:
            clear_mesh_cache()
            polypen_undo_cache = []
            me = self.src_object.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
            me.update()
        
            bme = bmesh.new()
            bme.from_mesh(me)
            bvh = BVHTree.FromBMesh(bme)
            write_mesh_cache(self.src_object, bme, bvh)

        # Hide any existing geometry
        bpy.ops.mesh.hide(unselected=True)
        bpy.ops.mesh.hide(unselected=False)

        self.tar_object = get_target_object()
        self.tar_bmesh = bmesh.from_edit_mesh(context.object.data).copy()
        for bmv in self.tar_bmesh.verts:
            bmv.co = self.mx * bmv.co
        
        self.scale = self.src_object.scale[0]
        self.length_scale = get_object_length_scale(self.src_object)
        
        #target_bmesh, target_mx, source_bvh, source_mx
        #self.tar_object.matrix_world
        self.tar_bmeshrender = BMeshRender(self.tar_bmesh, Matrix(), mesh_cache['bvh'], self.mx)
        
        color_mesh = self.settings.theme_colors_mesh[self.settings.theme]
        color_selection = self.settings.theme_colors_selection[self.settings.theme]
        color_active = self.settings.theme_colors_active[self.settings.theme]
        
        self.render_normal = {
            'poly color': (color_mesh[0], color_mesh[1], color_mesh[2], 0.1),
            'poly offset': 0.00001,
            
            'line width': 2.0,
            'line color': (color_mesh[0], color_mesh[1], color_mesh[2], 0.3),
            'line offset': 0.00002,
            
            'point size':  5.0,
            'point color': (color_mesh[0], color_mesh[1], color_mesh[2], 0.75),
            'point offset': 0.00003,
            
            #'normal': 0.002,
        }
        
        self.render_nearest = {
            'poly color': (color_selection[0], color_selection[1], color_selection[2], 0.20),
            'poly offset': 0.00004,
            
            'line color': (color_selection[0], color_selection[1], color_selection[2], 0.75),
            'line width': 2.0,
            'line offset': 0.00004,
            
            'point color': (color_selection[0], color_selection[1], color_selection[2], 0.75),
            'point size': 5.0,
            'point offset': 0.00004,
            
            #'normal': 0.002,
        }
        
        self.render_selected = {
            'poly color': (color_selection[0], color_selection[1], color_selection[2], 0.40),
            'poly offset': 0.00004,
            
            'line color': (color_selection[0], color_selection[1], color_selection[2], 1.00),
            'line width': 2.0,
            'line offset': 0.00004,
            
            'point color': (color_selection[0], color_selection[1], color_selection[2], 1.00),
            'point size': 5.0,
            'point offset': 0.00004,
            
            #'normal': 0.002,
        }
        
        self.render_visible = {
            'poly color': (0.224, 0.224, 0.224, 0.90), # a color that matches 3d view background
            'poly offset': 0.000001,
            'poly dotoffset': 0.0,
            
            'line width': 0.0,  # ignore edges
            'point size': 0.0,  # ignore verts
        }
        
        self.selected_bmverts = []
        self.selected_bmedges = []
        self.selected_bmfaces = []
        
        self.nearest_bmface = None
        self.nearest_bmvert = None
        self.nearest_bmedge = None
        self.over_source = False
        
        self.mouse_down_left = False
        self.mouse_down_right = False
        self.mouse_downp2d = None
        self.mouse_downp3d = None
        self.mouse_downn3d = None
        self.mouse_curp2d = None
        self.mouse_curp3d = None
        self.mouse_curn3d = None
        self.mouse_travel = 0
        
        self.vert_pos = None        # used for move vert tool
        
        self.mode = 'auto'
        
        context.area.header_text_set('Polypen')
    
    def end(self, context):
        ''' Called when tool is ending modal '''
        if context.mode == 'EDIT_MESH':
            # Reveal any existing geometry
            bpy.ops.mesh.reveal()
        if self.was_objectmode:
            bpy.ops.object.mode_set(mode='OBJECT')
        
        del self.tar_bmeshrender
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        
        bme = self.tar_bmesh.copy()
        for bmv in bme.verts:
            bmv.co = self.imx * bmv.co
        
        bpy.ops.object.mode_set(mode='OBJECT')
        bme.to_mesh(self.tar_object.data)
        bpy.ops.object.mode_set(mode='EDIT')
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        pass
    
    def draw_postview(self, context):
        ''' Place post view drawing code in here '''
        self.tar_bmeshrender.draw(opts=self.render_normal)
        common_drawing_bmesh.glDrawBMFaces(self.selected_bmfaces, opts=self.render_selected)
        common_drawing_bmesh.glDrawBMEdges(self.selected_bmedges, opts=self.render_selected)
        common_drawing_bmesh.glDrawBMVerts(self.selected_bmverts, opts=self.render_selected)
        if self.nearest_bmface:
            common_drawing_bmesh.glDrawBMFace(self.nearest_bmface, opts=self.render_nearest)
        if self.nearest_bmedge:
            common_drawing_bmesh.glDrawBMEdge(self.nearest_bmedge, opts=self.render_nearest)
        if self.nearest_bmvert:
            common_drawing_bmesh.glDrawBMVert(self.nearest_bmvert, opts=self.render_nearest)
        
        for o,r in zip(self.vis_objects, self.vis_bmrender):
            if o == self.src_object: continue
            if o == self.tar_object: continue
            r.draw(opts=self.render_visible)
            
        
        bgl.glDepthRange(0.0, 1.0)
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
        pass
    
    def update(self,context):
        '''Place update stuff here'''
        pass
    
    def mouse_down(self): return self.mouse_down_left or self.mouse_down_right
    
    def modal_wait(self, context, eventd):
        '''
        Place code here to handle commands issued by user
        Return string that corresponds to FSM key, used to change states.  For example:
        - '':     do not change state
        - 'main': transition to main state
        - 'nav':  transition to a navigation state (passing events through to 3D view)
        '''
        
        self.update_mouse(eventd)
        
        if eventd['press'] in self.keymap['undo']:
            self.undo(context)
            return ''
        
        if eventd['type'] == 'MOUSEMOVE':
            #mouse movement/hovering
            if not self.over_source:
                self.clear_nearest()
            else:
                p2d,p3d = self.mouse_curp2d,self.mouse_curp3d
                min_bmv,_,_ = self.closest_bmvert(context, p2d, p3d, 5, 0.5)
                min_bme,min_bmf = None,None
                if not min_bmv:
                    min_bme,_,_ = self.closest_bmedge(context, p2d, p3d, 5, 0.5)
                if not min_bme and not min_bmv:
                    min_bmf = self.closest_bmface(context, p2d, p3d, 0.05)
                self.nearest_bmvert = min_bmv
                self.nearest_bmedge = min_bme
                self.nearest_bmface = min_bmf
        
        # SELECTION
        
        if eventd['press'] in selection_mouse():
            # Select element
            self.create_undo()
            self.select(self.nearest_bmvert, self.nearest_bmedge, self.nearest_bmface)
            return 'move vert'
        
        if eventd['press'] in self.keymap['select all']:
            self.set_selection()
            return ''
        
        
        # COMMANDS
        
        if eventd['press'] in self.keymap['translate']:
            self.create_undo()
            self.mouse_downp2d = self.mouse_curp2d
            return 'move vert'
        
        if eventd['press'] in self.keymap['delete']:
            self.create_undo()
            if self.selected_bmfaces:
                for bmf in self.selected_bmfaces:
                    self.tar_bmesh.faces.remove(bmf)
                self.set_selection()
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
            elif self.selected_bmedges:
                try:
                    for bme in self.selected_bmedges:
                        self.tar_bmesh.edges.remove(bme)
                except:
                    pass
                self.set_selection()
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
            elif self.selected_bmverts:
                for bmv in self.selected_bmverts:
                    self.tar_bmesh.verts.remove(bmv)
                self.set_selection()
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
            return ''
        
        if eventd['press'] in self.keymap['dissolve']:
            if self.selected_bmedges:
                if len(self.selected_bmedges[0].link_faces) == 2:
                    self.create_undo()
                    bmesh.utils.face_join(self.selected_bmedges[0].link_faces)
                    self.set_selection()
                    self.clear_nearest()
                    self.tar_bmeshrender.dirty()
            elif self.selected_bmverts:
                bmv = self.selected_bmverts[0]
                if len(bmv.link_edges) == 2: # and len(bmv.link_faces) == 0:
                    self.create_undo()
                    #bmesh.utils.vert_dissolve(bmv)
                    self.handle_collapse_edge(bmv.link_edges[0])
                    self.set_selection()
                    self.clear_nearest()
                    self.tar_bmeshrender.dirty()
            return ''
        
        # if eventd['press'] == 'TAB':
        #     if self.mode == 'auto':
        #         self.mode = 'edge'
        #     elif self.mode == 'edge':
        #         self.mode = 'auto'
        
        
        # ACTION
        
        if eventd['press'] in self.keymap['polypen action']:
            return self.handle_action(context, eventd)
        if eventd['press'] in self.keymap['polypen alt action']:
            return self.handle_action(context, eventd)
            # if self.mode == 'auto':
            #     return self.handle_click_auto(context, eventd)
            # elif self.mode == 'edge':
            #     return self.handle_click_edge(context, eventd)
            # assert False, "Polypen is in unknown state"
        
        return ''
    
    def modal_move_vert(self, context, eventd):
        if not self.vert_pos:
            if   self.selected_bmverts: lbmv = self.selected_bmverts
            elif self.selected_bmedges: lbmv = [bmv for bme in self.selected_bmedges for bmv in bme.verts]
            elif self.selected_bmfaces: lbmv = [bmv for bmf in self.selected_bmfaces for bmv in bmf.verts]
            else: return 'main'
            self.vert_pos = {bmv:Vector(bmv.co) for bmv in lbmv}
            self.move_cancel_right = not self.mouse_down_right
            context.area.header_text_set('Polypen: Grab')
        
        self.update_mouse(eventd)
        
        if eventd['type'] == 'MOUSEMOVE':
            rgn = context.region
            r3d = context.space_data.region_3d
            nbmvco = {}
            for bmv in self.vert_pos:
                bmvco = self.vert_pos[bmv]
                p2d = location_3d_to_region_2d(rgn, r3d, bmvco)
                p2d = p2d + self.mouse_curp2d - self.mouse_downp2d
                hit = ray_cast_point_bvh(eventd['context'], mesh_cache['bvh'], self.mx, p2d)
                if not hit: return ''
                p3d = hit[0]
                min_bmv,_,_ = self.closest_bmvert(context, p2d, p3d, 5, 0.05, exclude=self.vert_pos)
                if min_bmv:
                    # merge-able!
                    p3d = Vector(min_bmv.co)
                nbmvco[bmv] = p3d
            for bmv,co in nbmvco.items():
                bmv.co = co
            self.tar_bmeshrender.dirty()
            return ''
        
        if eventd['release']:
            commit,cancel = False,False
            if eventd['type'] in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'}:
                commit = True
            if not self.move_cancel_right and eventd['type'] in {'RIGHTMOUSE'}:
                commit = True
            if eventd['type'] in {'ESC'}:
                cancel = True
            if self.move_cancel_right and eventd['type'] in {'RIGHTMOUSE'}:
                cancel = True
            
            if commit:
                rgn = context.region
                r3d = context.space_data.region_3d
                
                for bmv0 in self.vert_pos:
                    p3d = bmv0.co
                    p2d = location_3d_to_region_2d(rgn, r3d, p3d)
                    bmv1,_,_ = self.closest_bmvert(context, p2d, p3d, 5, 0.05, exclude=self.vert_pos)
                    if bmv1:
                        # make sure verts don't share an edge
                        share_edge = [bme for bme in bmv1.link_edges if bmv0 in bme.verts]
                        share_face = [bmf for bmf in bmv1.link_faces if bmv0 in bmf.verts]
                        if not share_edge and share_face:
                            # create an edge
                            bmf = share_face[0]
                            bmesh.utils.face_split(bmf, bmv0, bmv1)
                            share_edge = [bme for bme in bmv1.link_edges if bmv0 in bme.verts]
                        if share_edge:
                            # collapse edge
                            self.handle_collapse_edge(share_edge[0])
                        if not share_edge and not share_face:
                            # merge!!!
                            bmesh.utils.vert_splice(bmv0, bmv1)
                            self.clean_duplicate_bmedges(bmv1)
                            self.set_selection(lbmv=[bmv1])
                            self.clear_nearest()
                            self.clean_bmesh()
                            self.tar_bmeshrender.dirty()
                
                self.vert_pos = None
                context.area.header_text_set('Polypen')
                return 'main'
            
            if cancel:
                for bmv in self.vert_pos:
                    bmv.co = self.vert_pos[bmv]
                self.tar_bmeshrender.dirty()
                self.vert_pos = None
                context.area.header_text_set('Polypen')
                return 'main'
        
        return ''
    
    def clean_bmesh(self):
        # make sure we don't have duplicate bmedges (same verts)
        edges_seen = set()
        edges_rem = list()
        for bme in self.tar_bmesh.edges:
            p0 = (bme.verts[0].index, bme.verts[1].index)
            p1 = (bme.verts[1].index, bme.verts[0].index)
            if bme.verts[0] == bme.verts[1] or p0 in edges_seen:
                edges_rem.append(bme)
            else:
                edges_seen.add(p0)
                edges_seen.add(p1)
        if edges_rem:
            lfvadd = []
            for e in edges_rem:
                lfvadd += [f.verts for f in e.link_faces]
                self.tar_bmesh.edges.remove(e)
            faces_seen = set(frozenset(v.index for v in bmf.verts) for bmf in self.tar_bmesh.faces)
            for fv in lfvadd:
                spi = frozenset(v.index for v in fv)
                if spi not in faces_seen:
                    faces_seen.add(spi)
                    self.tar_bmesh.faces.new(fv)
            self.tar_bmeshrender.dirty()
    
    def update_mouse(self, eventd):
        hit = ray_cast_point_bvh(eventd['context'], mesh_cache['bvh'], self.mx, eventd['mouse'])
        p3d,n3d = hit if hit else (None,None)
        self.mouse_curp2d = Vector(eventd['mouse'])
        self.mouse_curp3d = p3d
        self.mouse_curn3d = n3d
        
        self.over_source = (p3d != None)
        
        if eventd['press'] and ('LEFTMOUSE' in eventd['press'] or 'RIGHTMOUSE' in eventd['press']):
            self.mouse_downp2d = self.mouse_curp2d
            self.mouse_downp3d = self.mouse_curp3d
            self.mouse_downn3d = self.mouse_curn3d
            if 'LEFTMOUSE'  in eventd['press']: self.mouse_down_left  = True
            if 'RIGHTMOUSE' in eventd['press']: self.mouse_down_right = True
        
        if eventd['release'] and ('LEFTMOUSE' in eventd['release'] or 'RIGHTMOUSE' in eventd['release']):
            self.mouse_downp2d = None
            self.mouse_downp3d = None
            self.mouse_downn3d = None
            if 'LEFTMOUSE'  in eventd['release']: self.mouse_down_left  = False
            if 'RIGHTMOUSE' in eventd['release']: self.mouse_down_right = False
        
        if self.mouse_down():
            if self.mouse_downp2d:
                self.mouse_travel = (self.mouse_curp2d - self.mouse_downp2d).length
    
    ################################################
    # hover and selection helper functions
    
    def hover_vert(self): return self.nearest_bmvert
    def hover_edge(self): return self.nearest_bmedge
    def hover_face(self): return self.nearest_bmface
    def hover_source(self): return self.over_source and not self.nearest_bmvert and not self.nearest_bmedge and not self.nearest_bmface
    
    def set_selection(self, lbmv=None, lbme=None, lbmf=None):
        self.selected_bmverts = [] if not lbmv else lbmv
        self.selected_bmedges = [] if not lbme else lbme
        self.selected_bmfaces = [] if not lbmf else lbmf
    
    def select(self, *geo):
        self.selected_bmverts = [g for g in geo if type(g) is BMVert]
        self.selected_bmedges = [g for g in geo if type(g) is BMEdge]
        self.selected_bmfaces = [g for g in geo if type(g) is BMFace]
    
    def select_hover(self):
        self.select(self.hover_vert(), self.hover_edge(), self.hover_face())
    
    def clear_nearest(self):
        self.nearest_bmvert = None
        self.nearest_bmedge = None
        self.nearest_bmface = None
    
    
    #########################
    # undo
    
    def create_undo(self):
        liv = [v.index for v in self.selected_bmverts]
        lie = [e.index for e in self.selected_bmedges]
        lif = [f.index for f in self.selected_bmfaces]
        polypen_undo_cache.append((self.tar_bmesh.copy(),liv,lie,lif))
        if len(polypen_undo_cache) > self.settings.undo_depth:
            polypen_undo_cache.pop(0)
    
    def undo(self, context):
        if not polypen_undo_cache: return
        bme,liv,lie,lif = polypen_undo_cache.pop()
        bme = bme.copy()
        bme.verts.ensure_lookup_table()
        bme.edges.ensure_lookup_table()
        bme.faces.ensure_lookup_table()
        self.tar_bmesh = bme
        self.tar_bmeshrender.replace_target_bmesh(bme)
        self.selected_bmverts = [bme.verts[i] for i in liv]
        self.selected_bmedges = [bme.edges[i] for i in lie]
        self.selected_bmfaces = [bme.faces[i] for i in lif]
        self.clear_nearest()
    
    
    ###############################################################
    # creation, modifying, and  deletion helper functions
    
    def create_vert(self, co, normal):
        bmv = self.tar_bmesh.verts.new(co)
        bmv.normal = normal
        self.select(bmv)
        self.tar_bmeshrender.dirty()
        return bmv
    
    def create_edge(self, lbmv):
        bme = self.tar_bmesh.edges.new(lbmv)
        self.select(bme)
        self.tar_bmeshrender.dirty()
        return bme
    
    def create_face(self, lbmv):
        # check for crisscrossing and for flipped
        l = len(lbmv)
        repeat,iters = True,0
        while repeat:
            repeat,iters = False,iters+1
            assert iters < pow(l,l/1.5), 'Could not eliminate crisscrossing'
            for i0 in range(l):
                i1,i2 = (i0+1)%l,(i0+2)%l
                c0,c1,c2 = lbmv[i0].co,lbmv[i1].co,lbmv[i2].co
                d10,d12 = c0-c1,c2-c1
                n = d12.cross(d10)
                dot = n.dot(self.mouse_curn3d)
                if dot < 0:
                    # wrong direction, swap!
                    lbmv[i1],lbmv[i2] = lbmv[i2],lbmv[i1]
                    repeat = True
                    break
        bmf = self.tar_bmesh.faces.new(lbmv)
        self.select(bmf)
        self.tar_bmeshrender.dirty()
        return bmf
    
    
    
    ########################################
    # finder helper functions
    
    def closest_bmvert(self, context, p2d, p3d, max_dist2d, max_dist3d, exclude=None, onlyVisible=True):
        rgn,r3d = context.region,context.space_data.region_3d
        min_bmv = None
        min_dist2d = 0
        min_dist3d = 0
        bvh_raycast = mesh_cache['bvh'].ray_cast
        viewloc = self.imx * region_2d_to_origin_3d(rgn, r3d, p2d)
        for bmv in self.tar_bmesh.verts:
            if exclude and bmv in exclude: continue
            d3d = (bmv.co - p3d).length
            if d3d > max_dist3d: continue
            bmv2d = location_3d_to_region_2d(rgn, r3d, bmv.co)
            if not bmv2d: continue
            d2d = (p2d - bmv2d).length
            if d2d > max_dist2d: continue
            if min_bmv and (d2d >= min_dist2d or d3d >= min_dist3d): continue
            if onlyVisible:
                v = self.imx * bmv.co
                v2v = viewloc - v
                v2vl = v2v.length
                v2v /= v2vl
                if bvh_raycast(v + v2v*0.01, v2v, v2vl-0.01)[0]: continue
            min_bmv = bmv
            min_dist2d = d2d
            min_dist3d = d3d
        if not min_bmv: return (None,None,None)
        return (min_bmv, min_dist2d, min_dist3d)
    
    def closest_bmedge(self, context, p2d, p3d, max_dist2d, max_dist3d, lbme=None, onlyVisible=True):
        rgn = context.region
        r3d = context.space_data.region_3d
        if not lbme: lbme = self.tar_bmesh.edges
        lmin_bme = []
        min_dist2d = 0
        min_dist3d = 0
        bvh_raycast = mesh_cache['bvh'].ray_cast
        viewloc = self.imx * region_2d_to_origin_3d(rgn, r3d, p2d)
        
        def isVisible(co):
            v = self.imx * co
            v2v = viewloc - v
            v2vl = v2v.length
            v2v /= v2vl
            hit = bvh_raycast(v+v2v*0.01, v2v, v2vl-0.01)
            return not hit[0]
            
        for bme in lbme:
            # if len(bme.link_faces) == 2:
            #     # bmedge has two faces, so we cannot add another face
            #     # without making non-manifold
            #     continue
            bmv0,bmv1 = bme.verts[0],bme.verts[1]
            if onlyVisible and not (isVisible(bmv0.co) and isVisible(bmv1.co)): continue
            t,d3d = closest_t_and_distance_point_to_line_segment(p3d, bmv0.co, bmv1.co)
            if d3d > max_dist3d: continue
            bmv3d = bmv1.co * t + bmv0.co * (1-t)
            bmv2d = location_3d_to_region_2d(rgn, r3d, bmv3d)
            if not bmv2d: continue
            d2d = (p2d - bmv2d).length
            if d2d > max_dist2d: continue
            # if onlyVisible:
            #     v = self.imx * bmv3d
            #     v2v = viewloc - v
            #     v2vl = v2v.length
            #     v2v /= v2vl
            #     if bvh_raycast(v+v2v*0.01, v2v, v2vl-0.01)[0]: continue
            if not lmin_bme or (d3d <= min_dist3d+0.0001):
                if lmin_bme and (abs(d3d-min_dist3d) <= 0.0001):
                    lmin_bme += [bme]
                else:
                    lmin_bme = [bme]
                    min_dist2d = d2d
                    min_dist3d = d3d
        if not lmin_bme: return (None,None,None)
        if len(lmin_bme) >= 2:
            return self.orthogonalest_bmedge(p3d, lmin_bme)
        return (lmin_bme[0], min_dist2d, min_dist3d)
    
    def orthogonalest_bmedge(self, p3d, lbme):
        p00,p01 = lbme[0].verts[0].co,lbme[0].verts[1].co
        p10,p11 = lbme[1].verts[0].co,lbme[1].verts[1].co
        if (p00-p3d).length_squared > (p01-p3d).length_squared:
            p00,p01 = p01,p00
        if (p10-p3d).length_squared > (p11-p3d).length_squared:
            p10,p11 = p11,p10
        _,d0 = closest_t_and_distance_point_to_line_segment(p3d, p00, p01)
        _,d1 = closest_t_and_distance_point_to_line_segment(p3d, p10, p11)
        
        if abs(d0-d1) > 0.01:
            return (lbme[0] if d0 < d1 else lbme[1],0,0)
        
        p001,p00p = (p01-p00).normalized(), (p3d-p00).normalized()
        p101,p10p = (p11-p10).normalized(), (p3d-p10).normalized()
        
        theta0 = abs(p00p.dot(p001))
        theta1 = abs(p10p.dot(p101))
        return (lbme[0] if theta0 < theta1 else lbme[1],0,0)
    
    def closest_bmface(self, context, p2d, p3d, max_dist3d, onlyVisible=True):
        rgn = context.region
        r3d = context.space_data.region_3d
        min_dist3d,min_bmf = max_dist3d,None
        bvh_raycast = mesh_cache['bvh'].ray_cast
        viewloc = self.imx * region_2d_to_origin_3d(rgn, r3d, p2d)
        for bmf in self.tar_bmesh.faces:
            bmv0 = bmf.verts[0]
            v02d = location_3d_to_region_2d(rgn,r3d,bmv0.co)
            for bmv1,bmv2 in zip(bmf.verts[1:-1], bmf.verts[2:]):
                v12d = location_3d_to_region_2d(rgn,r3d,bmv1.co)
                v22d = location_3d_to_region_2d(rgn,r3d,bmv2.co)
                if not intersect_point_tri_2d(p2d, v02d, v12d, v22d): continue
                pt = intersect_point_tri(p3d, bmv0.co, bmv1.co, bmv2.co)
                if not pt: continue
                dist = (pt-p3d).length
                if dist >= min_dist3d: continue
                if onlyVisible:
                    v = self.imx * pt
                    v2v = viewloc - v
                    v2vl = v2v.length
                    v2v /= v2vl
                    if bvh_raycast(v+v2v*0.01, v2v, v2vl-0.01)[0]: continue
                
                min_dist3d = dist
                min_bmf = bmf
        return min_bmf
    
    def edge_between_verts(self, bmv0, bmv1):
        lbme = [bme for bme in bmv1.link_edges if bmv0 in bme.verts]
        return lbme[0] if lbme else None
    
    def face_between_verts(self, bmv0, bmv1):
        lbmf = [bmf for bmf in bmv1.link_faces if bmv0 in bmf.verts]
        return lbmf[0] if lbmf else None
    
    def vert_between_edges(self, bme0, bme1):
        lbmv = [bmv for bmv in bme1.verts if bmv in bme0.verts]
        return lbmv[0] if lbmv else None
    
    def face_between_vertedge(self, bmv, bme):
        lbmf = [bmf for bmf in bmv.link_faces if bmf in bme.link_faces]
        return lbmf[0] if lbmf else None
    
    def face_between_edges(self, bme0, bme1):
        lbmf = [bmf for bmf in bme0.link_faces if bmf in bme1.link_faces]
        return lbmf[0] if lbmf else None
    
    ##################################
    # action handlers
    
    
    def handle_action(self, context, eventd):
        self.create_undo()
        if self.selected_bmfaces:
            return self.handle_action_selface(context, eventd)
        if self.selected_bmedges:
            return self.handle_action_seledge(context, eventd)
        if self.selected_bmverts:
            return self.handle_insert_vert_and_bridge(context, eventd)
            return self.handle_action_selvert(context, eventd)          # <== not used??
        return self.handle_action_selnothing(context, eventd)
    
    def handle_action_selnothing(self, context, eventd):
        p2d,p3d,n3d = self.mouse_curp2d,self.mouse_curp3d,self.mouse_curn3d
        rgn,r3d = context.region,context.space_data.region_3d
        
        if self.hover_source():
            self.create_vert(p3d, n3d)
            return 'move vert'
        
        if self.hover_vert():
            self.select_hover()
            return 'move vert'
        
        if self.hover_edge():
            self.select_hover()
            return self.handle_insert_vert_p3d(context, eventd)
        
        if self.hover_face():
            bmf = self.nearest_bmface
            min_bme,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=bmf.edges)
            _,bmv = bmesh.utils.edge_split(min_bme, min_bme.verts[0], 0.5)
            lbme = bmv.link_edges
            bmv.co = p3d
            self.set_selection(lbmv=[bmv],lbme=lbme)
            self.clear_nearest()
            self.tar_bmeshrender.dirty()
            return 'move vert'
        
        return ''
    
    def handle_action_selvert(self, context, eventd):
        p2d,p3d,n3d = self.mouse_curp2d,self.mouse_curp3d,self.mouse_curn3d
        rgn,r3d = context.region,context.space_data.region_3d
        bmv0 = self.selected_bmverts[0]
        
        if self.hover_source():
            bmv1 = self.create_vert(p3d, n3d)
            bme = self.create_edge([bmv0, bmv1])
            self.select(bmv1, bme)
            return 'move vert'
        
        if self.hover_vert():
            bmv1 = self.hover_vert()
            if bmv0 == bmv1:
                # same vert
                return 'move vert'
            bme = self.edge_between_verts(bmv0, bmv1)
            if bme:
                # verts share edge
                self.select(bmv1)
                return 'move vert'
            bmf = self.face_between_verts(bmv0, bmv1)
            if bmf:
                # verts share face
                # split this face!
                bmesh.utils.face_split(bmf, bmv0, bmv1)
                self.select(bmv1)
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
                return 'move vert'
            # create edge between verts
            bme = self.create_edge([bmv0, bmv1])
            self.select(bmv1, bme)
            return 'move vert'
        
        if self.hover_edge():
            bme = self.hover_edge()
            if bmv0 in bme.verts:
                # vert belongs to edge
                # insert vert into edge
                self.select(bme)
                return handle_insert_vert_p3d(context, eventd)
            
            bmf = self.face_between_vertedge(bmv0, bme)
            if bmf:
                # vert and edge share face
                # insert vert and split this face!
                _,bmv1 = bmesh.utils.edge_split(bme, bme.verts[0], 0.5)
                bmesh.utils.face_split(bmf, bmv0, bmv1)
                lbme1 = bmv1.link_edges
                bmv1.co = p3d
                self.select(bmv1, *lbme1)
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
                return 'move vert'
            
            # bridge
            bmv1 = self.nearest_bmedge.verts[0]
            bmv2 = self.nearest_bmedge.verts[1]
            bmf = self.create_face([bmv0,bmv1,bmv2])
            return ''
        
        if self.hover_face():
            bmf = self.hover_face()
            p3d = bmv0.co
            p2d = location_3d_to_region_2d(rgn, r3d, bmv0.co)
            bme,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=bmf.edges)
            bmv1,bmv2 = bme.verts
            bmf = self.create_face([bmv0,bmv1,bmv2])
            return ''
        
        return ''
    
    def handle_action_seledge(self, context, eventd):
        p2d,p3d,n3d = self.mouse_curp2d,self.mouse_curp3d,self.mouse_curn3d
        rgn,r3d = context.region,context.space_data.region_3d
        
        if self.hover_source():
            bme,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=self.selected_bmedges)
            assert bme in self.selected_bmedges
            bmv0 = self.create_vert(p3d, n3d)
            bmv1,bmv2 = bme.verts
            bmf = self.create_face([bmv0,bmv1,bmv2])
            self.select(bmv0, bmf)
            return 'move vert'
        
        if self.hover_vert():
            bmv0 = self.hover_vert()
            if any(bme for bme in self.selected_bmedges if bmv0 in bme.verts):
                # vert belongs to edge
                self.select(bmv0)
                return 'move vert'
            p3d = bmv0.co
            p2d = location_3d_to_region_2d(rgn, r3d, bmv0.co)
            bme,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=self.selected_bmedges)
            bmf = self.face_between_vertedge(bmv0, bme)
            if bmf:
                # edge and vert share face
                # split this face!
                bmv1,bmv2 = bme.verts
                if not any(bme.other_vert(bmv0) == bmv1 for bme in bmv0.link_edges):
                    bmesh.utils.face_split(bmf, bmv0, bmv1)
                    bmf = self.face_between_verts(bmv0, bmv2)
                if not any(bme.other_vert(bmv0) == bmv2 for bme in bmv0.link_edges):
                    bmesh.utils.face_split(bmf, bmv0, bmv2)
                self.select(bmv0)
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
                return 'move vert'
            # bridge
            bmv1,bmv2 = bme.verts
            bmf = self.create_face([bmv0,bmv1,bmv2])
            self.select(bmv0, bmf)
            return 'move vert'
        
        if self.hover_edge():
            return self.handle_edges_edge(context, eventd)
        
        if self.hover_face():
            bme0,bme1,md = None,None,0
            for _bme0 in self.selected_bmedges:
                bmv0 = (_bme0.verts[0].co + _bme0.verts[1].co)/2.0
                for _bme1 in self.nearest_bmface.edges:
                    _,d = closest_t_and_distance_point_to_line_segment(bmv0, _bme1.verts[0].co, _bme1.verts[1].co)
                    if not bme0 or d < md:
                        bme0 = _bme0
                        bme1 = _bme1
                        md = d
            self.select(bme0)
            self.nearest_bmedge = bme1
            self.nearest_bmface = None
            return self.handle_edges_edge(context, eventd)
        
        return ''
    
    def handle_action_selface(self, context, eventd):
        p2d,p3d = self.mouse_curp2d,self.mouse_curp3d
        rgn,r3d = context.region,context.space_data.region_3d
        
        bmf = self.selected_bmfaces[0]
        
        if len(bmf.verts) == 3:
            if self.hover_source():
                return self.handle_insert_vert_p3d(context, eventd)
            if self.hover_vert():
                return self.handle_insert_vert_nearest(context, eventd)
        if self.hover_edge():
            if self.nearest_bmedge in bmf.edges:
                self.select()
                return self.handle_action_selnothing(context, eventd)
            
            # get a list of shared verts between the selected face and the
            # hovered edge.  if one vert is shared, then we need to bridge
            # between face and hovered edge
            lbmv_common = [v for v in self.nearest_bmedge.verts if v in bmf.verts]
            if len(lbmv_common) == 1:
                bmv_shared = lbmv_common[0]
                bmv_opposite = self.nearest_bmedge.other_vert(bmv_shared)
                
                # find which edge to split
                lbme = [bme for bme in bmf.edges if bmv_shared in bme.verts]
                bme,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=lbme)
                
                # split edge
                _,bmv = bmesh.utils.edge_split(bme, bme.verts[0], 0.5)
                bmv_other = [bmv_ for bme_ in bmv.link_edges for bmv_ in bme_.verts if bmv_ != bmv_shared and bmv_ != bmv][0]
                
                # merge new bmvert into bmv_opposite
                bmesh.utils.vert_splice(bmv, bmv_opposite)
                #lbme = [bme for bme in bmv_opposite.link_edges if bme != self.nearest_bmedge]
                self.clean_duplicate_bmedges(bmv_opposite)
                lbme = [bme_ for bme_ in bmv_opposite.link_edges if bme_.other_vert(bmv_opposite) == bmv_other]
                self.set_selection(lbmv=[bmv_opposite],lbme=lbme)
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
                return 'move vert'
                
        if self.hover_face():
            if self.nearest_bmface == bmf:
                self.select()
                return self.handle_action_selnothing(context, eventd)
        
        return self.handle_bridge_nearest(context, eventd)
    
    
    
    def clean_duplicate_bmedges(self, bmv):
        # search for two edges between the same pair of verts
        lbme = list(bmv.link_edges)
        lbme_dup = []
        for i0,bme0 in enumerate(lbme):
            for i1,bme1 in enumerate(lbme):
                if i1 <= i0: continue
                if bme0.other_vert(bmv) == bme1.other_vert(bmv):
                    lbme_dup += [(bme0,bme1)]
        for bme0,bme1 in lbme_dup:
            #if not bme0.is_valid or bme1.is_valid: continue
            l0,l1 = len(bme0.link_faces), len(bme1.link_faces)
            handled = False
            if l0 == 0:
                self.tar_bmesh.edges.remove(bme0)
                handled = True
            if l1 == 0:
                self.tar_bmesh.edges.remove(bme1)
                handled = True
            if l0 == 1 and l1 == 1:
                # remove bme1 and recreate attached faces
                lbmv = list(bme1.link_faces[0].verts)
                self.tar_bmesh.edges.remove(bme1)
                self.create_face(lbmv)
                handled = True
            assert handled, 'unhandled count of linked faces %d, %d' % (l0,l1)
    
    ######################################
    # action handler helpers
    
    def handle_edges_edge(self, context, eventd):
        p2d,p3d = self.mouse_curp2d,self.mouse_curp3d
        rgn,r3d = context.region,context.space_data.region_3d
        
        bme1 = self.hover_edge()
        if bme1 in self.selected_bmedges:
            # hovered edge is a selected edge
            _,bmv = bmesh.utils.edge_split(bme1, bme1.verts[0], 0.5)
            lbme = bmv.link_edges
            bmv.co = p3d
            self.set_selection(lbmv=[bmv],lbme=lbme)
            self.clear_nearest()
            self.tar_bmeshrender.dirty()
            return 'move vert'
        lbmf = [self.face_between_edges(bme0,bme1) for bme0 in self.selected_bmedges]
        lbmf = [bmf for bmf in lbmf if bmf]
        bmf = lbmf[0] if lbmf else None
        if bmf:
            # edges share face
            # split this face!
            if self.selected_bmverts:
                # insert new vert in clicked edge, split face by adding edge between selected and new verts
                bmv0 = self.selected_bmverts[0]
                _,bmv1 = bmesh.utils.edge_split(bme1, bme1.verts[0], 0.5)
                bmesh.utils.face_split(bmf, bmv0, bmv1)
                lbme1 = bmv1.link_edges
                bmv1.co = p3d
                self.select(bmv1, *lbme1)
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
                return 'move vert'
            # split face by adding edges between verts of two edges
            bme0 = self.selected_bmedges[0]
            bmv00,bmv01 = bme0.verts
            bmv10,bmv11 = bme1.verts
            if (bmv01.co - bmv00.co).dot(bmv11.co - bmv10.co) < 0:
                bmv10,bmv11 = bmv11,bmv10
            if bmv00 != bmv10:
                bmeA = self.edge_between_verts(bmv00, bmv10)
                if not bmeA:
                    bmesh.utils.face_split(bmf, bmv00, bmv10)
                    bmeA = self.edge_between_verts(bmv00, bmv10)
                    bmf = [bmf for bmf in bmeA.link_faces if bmv01 in bmf.verts][0]
            if bmv01 != bmv11:
                bmeB = self.edge_between_verts(bmv01, bmv11)
                if not bmeB:
                    bmesh.utils.face_split(bmf, bmv01, bmv11)
                    bmeB = self.edge_between_verts(bmv01, bmv11)
                    bmf = [bmf for bmf in bmeB.link_faces if bmv00 in bmf.verts][0]
            self.select(bme1)
            self.clear_nearest()
            self.tar_bmeshrender.dirty()
            return 'move vert'
        lbmv = [self.vert_between_edges(bme0,bme1) for bme0 in self.selected_bmedges]
        lbmv = [bmv for bmv in lbmv if bmv]
        bmv0 = lbmv[0] if lbmv else None
        if bmv0:
            # edges share a vert
            bme0 = [bme0 for bme0 in self.selected_bmedges if bmv0 in bme0.verts][0]
            bmv1 = bme0.other_vert(bmv0)
            bmv2 = bme1.other_vert(bmv0)
            bmf = self.create_face([bmv0,bmv1,bmv2])
            return ''
        # bridge
        p3d = (bme1.verts[0].co + bme1.verts[1].co)/2
        p2d = location_3d_to_region_2d(rgn, r3d, p3d)
        bme0,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=self.selected_bmedges)
        bmv0,bmv1 = bme0.verts
        bmv2,bmv3 = bme1.verts
        bmf = self.create_face([bmv0,bmv1,bmv2,bmv3])
        lbme = [bme for bme in bmf.edges if bme!=bme0 and bme!=bme1]
        self.select(*lbme)
        return ''
    
    def handle_bridge_nearest(self, context, eventd):
        """bridge two closest edges, one from selected_bmedges and other from nearest_bmface"""
        rgn,r3d = context.region,context.space_data.region_3d
        
        if self.nearest_bmvert:
            p3d = self.nearest_bmvert.co
            p2d = location_3d_to_region_2d(rgn, r3d, p3d)
            if self.selected_bmedges:
                lbme = self.selected_bmedges
            elif self.selected_bmfaces:
                lbme = self.selected_bmfaces[0].edges
            bme,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=lbme)
            bmv0,bmv1,bmv2 = bme.verts[0],bme.verts[1],self.nearest_bmvert
            bmf = self.create_face([bmv0, bmv1, bmv2])
            self.set_selection(lbmv=[bmv2],lbmf=[bmf])
            return 'move vert'
        
        if self.nearest_bmedge:
            bme0 = self.nearest_bmedge
            bmv0,bmv1 = bme0.verts
            p3d = (bmv0.co + bmv1.co) / 2.0
            p2d = location_3d_to_region_2d(rgn, r3d, p3d)
            if self.selected_bmedges:
                lbme1 = self.selected_bmedges
            elif self.selected_bmfaces:
                lbme1 = self.selected_bmfaces[0].edges
            bme1,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=lbme1)
            bmv2,bmv3 = bme1.verts
            bmf = self.create_face([bmv0, bmv1, bmv2, bmv3])
            self.set_selection(lbme=[bme for bme in bmf.edges if bme not in {bme0,bme1}])
            return ''
        
        if self.nearest_bmface:
            # need to find closest edges
            
            # TODO: check if edges are roughly parallel??
            
            if self.selected_bmedges:
                lbme1 = self.selected_bmedges
            elif self.selected_bmfaces:
                lbme1 = self.selected_bmfaces[0].edges
            else:
                return ''
            mbme0,mbme1,md3d = None,None,0
            for bme0 in self.nearest_bmface.edges:
                p3d = (bme0.verts[0].co + bme0.verts[0].co) / 2.0
                p2d = location_3d_to_region_2d(rgn, r3d, p3d)
                bme1,d2d,d3d = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=lbme1)
                if not mbme0 or d3d < md3d:
                    mbme0 = bme0
                    mbme1 = bme1
                    md3d = d3d
            bmv0,bmv1 = mbme0.verts
            bmv2,bmv3 = mbme1.verts
            bmf = self.create_face([bmv0, bmv1, bmv2, bmv3])
            self.set_selection(lbme=[bme for bme in bmf.edges if bme not in {mbme0,mbme1}])
            return ''
        
        print('ACK!')
        return ''
    
    def handle_bridge_p3d(self, context, eventd):
        """create vert at p3d and bridge to closest selected bmedge"""
        p2d,p3d,n3d = self.mouse_downp2d,self.mouse_downp3d,self.mouse_downn3d
        if self.selected_bmedges:
            lbme = self.selected_bmedges
        elif self.selected_bmfaces:
            lbme = self.selected_bmfaces[0].edges
        else:
            return
        bme,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=lbme)
        bmv0,bmv1,bmv2 = bme.verts[0],bme.verts[1],self.create_vert(p3d, n3d)
        bmf = self.create_face([bmv0, bmv1, bmv2])
        self.set_selection(lbmv=[bmv2],lbmf=[bmf])
        return 'move vert'
    
    def handle_insert_vert_and_bridge(self, context, eventd):
        """insert new vert at p3d, bridge to selected vert, splitting face"""
        rgn,r3d = context.region,context.space_data.region_3d
        bmv0 = self.selected_bmverts[0]
        if self.hover_edge():
            bme = self.nearest_bmedge
            if bmv0 in bme.verts:
                # vert belongs to edge. insert new vert into edge
                _,bmv1 = bmesh.utils.edge_split(bme, bmv0, 0.5)
                # find newly created edge
                lbme = [bme for bme in bmv1.link_edges if bmv0 in bme.verts if len(bme.link_faces)==1]
                self.select(bmv1, *lbme)
                self.clear_nearest()
                self.clean_bmesh()
                self.tar_bmeshrender.dirty()
                return 'move vert'
            _,bmv1 = bmesh.utils.edge_split(bme, bme.verts[0], 0.5)
            bmv1.co = self.mouse_downp3d
        elif self.hover_face():
            # find closest edge to selected vert
            p3d = bmv0.co
            p2d = location_3d_to_region_2d(rgn, r3d, p3d)
            lbme = self.nearest_bmface.edges
            bme,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=lbme)
            _,bmv1 = bmesh.utils.edge_split(bme, bme.verts[0], 0.5)
        elif self.hover_vert():
            bmv1 = self.nearest_bmvert
        else:
            bmv1 = self.create_vert(self.mouse_downp3d, self.mouse_downn3d)
        # find edges between new vert (bmv1) and previously selected vert (bmv0)
        lbme = [bme for bme in bmv1.link_edges if bmv0 in bme.verts]
        if lbme:
            # verts share an edge
            # only select edge if it has one adj face
            lbme = [bme for bme in lbme if len(bme.link_faces)==1]
            self.select(bmv1, *lbme)
            return 'move vert'
        lbmf = [bmf for bmf in bmv1.link_faces if bmv0 in bmf.verts]
        if lbmf:
            # verts share a face, so split face!
            bmesh.utils.face_split(lbmf[0], bmv0, bmv1)
            self.select(bmv1)
            self.clear_nearest()
            self.tar_bmeshrender.dirty()
            return 'move vert'
        bme = self.tar_bmesh.edges.new([bmv0,bmv1])
        if eventd['press'] in self.keymap['polypen alt action']:
            self.select(bmv1)
        else:
            self.select(bmv1,bme)
        self.tar_bmeshrender.dirty()
        return 'move vert'
    
    def handle_insert_vert_p3d(self, context, eventd):
        """invert new vert at p3d into closest selected bmedge"""
        p2d,p3d = self.mouse_downp2d,self.mouse_downp3d
        if self.selected_bmedges:
            lbme = self.selected_bmedges
        elif self.selected_bmfaces:
            lbme = self.selected_bmfaces[0].edges
        else:
            return ''
        bme,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=lbme)
        bme,bmv = bmesh.utils.edge_split(bme, bme.verts[0], 0.5)
        lbme = bmv.link_edges
        bmv.co = p3d
        self.set_selection(lbmv=[bmv],lbme=lbme)
        self.tar_bmeshrender.dirty()
        return 'move vert'
    
    def handle_insert_vert_nearest(self, context, eventd):
        """insert nearest vert into closest selected bmedge"""
        
        rgn,r3d = context.region,context.space_data.region_3d
        
        p3d = self.nearest_bmvert.co
        p2d = location_3d_to_region_2d(rgn, r3d, p3d)
        
        if self.selected_bmedges:
            lbme = self.selected_bmedges
        elif self.selected_bmfaces:
            lbme = self.selected_bmfaces[0].edges
        else:
            return ''
        bme,_,_ = self.closest_bmedge(context, p2d, p3d, float('inf'), float('inf'), lbme=lbme)
        bme,bmv = bmesh.utils.edge_split(bme, bme.verts[0], 0.5)
        bmesh.utils.vert_splice(bmv, self.nearest_bmvert)
        self.clean_duplicate_bmedges(self.nearest_bmvert)
        lbme = [bme for bme in self.nearest_bmvert.link_edges if len(bme.link_faces) == 1 and self.selected_bmfaces[0] in bme.link_faces]
        self.set_selection(lbmv=[self.nearest_bmvert],lbme=lbme)
        self.clear_nearest()
        self.clean_bmesh()
        self.tar_bmeshrender.dirty()
        return 'move vert'
    
    def handle_collapse_edge(self, bme):
        bmv0,bmv1 = bme.verts
        llbmv = [[bmv for bmv in bmf.verts if bmv != bmv0] for bmf in bme.link_faces]
        self.tar_bmesh.edges.remove(bme)
        bmesh.utils.vert_splice(bmv0, bmv1)
        #self.clean_duplicate_bmedges(bmv1)
        for lbmv in llbmv:
            if len(lbmv) > 2:
                self.tar_bmesh.faces.new(lbmv)
        self.clean_bmesh()
        self.clear_nearest()
        self.set_selection(lbmv=[bmv1])
        self.tar_bmeshrender.dirty()
        return ''


