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
from mathutils.geometry import intersect_point_tri

import math
import os
import copy

from ..modaloperator import ModalOperator

from ..lib import common_utilities
from ..lib.common_utilities import showErrorMessage, get_source_object, get_target_object
from ..lib.common_utilities import setup_target_object
from ..lib.common_utilities import bversion, selection_mouse
from ..lib.common_utilities import point_inside_loop2d, get_object_length_scale, dprint, frange
from ..lib.common_utilities import closest_t_and_distance_point_to_line_segment
from ..lib.classes.profiler.profiler import Profiler
from .. import key_maps
from ..cache import mesh_cache, polystrips_undo_cache, object_validation, is_object_valid, write_mesh_cache, clear_mesh_cache

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
        if get_target_object() and get_target_object().type != 'MESH':
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
            self.src_object = get_source_object()
            nm_polypen = self.src_object.name + "_polypen"
            self.tar_object = setup_target_object( nm_polypen, self.src_object, bmesh.new() )
            self.tar_object.select = True
            bpy.context.scene.objects.active = self.tar_object
            bpy.ops.object.mode_set(mode='EDIT')
            self.was_objectmode = True
        else:
            self.was_objectmode = False
        
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

        # Hide any existing geometry
        bpy.ops.mesh.hide(unselected=True)
        bpy.ops.mesh.hide(unselected=False)

        self.tar_object = get_target_object()
        self.tar_bmesh = bmesh.from_edit_mesh(context.object.data)
        
        self.scale = self.src_object.scale[0]
        self.length_scale = get_object_length_scale(self.src_object)
        
        self.tar_bmeshrender = BMeshRender(self.tar_bmesh)
        
        self.render_normal = {
            'poly color': (1,1,1,0.5),
            'poly depth': (0, 0.999),
            
            'line width': 1.0,
            'line color': (1,1,1,1),
            'line depth': (0, 0.997),
            
            'point size':  3.0,
            'point color': (0,0,0,1),
            'point depth': (0, 0.996),
        }
        
        self.render_nearest = {
            'poly color': (1,0.7,0,1),
            'poly depth': (0, 0.995),
            
            'line color': (1,0.7,0,1),
            'line width': 2.0,
            'line depth': (0, 0.995),
            
            'point color': (1,0.7,0,1),
            'point depth': (0, 0.995),
            'point size': 4.0,
        }
        
        self.render_selected = {
            'poly color': (1,1,0,1),
            'poly depth': (0, 0.995),
            
            'line color': (1,1,0,1),
            'line width': 2.0,
            'line depth': (0, 0.995),
            
            'point color': (1,1,0,1),
            'point depth': (0, 0.995),
            'point size': 4.0,
        }
        
        self.selected_bmverts = []
        self.selected_bmedges = []
        self.selected_bmfaces = []
        
        self.nearest_bmface = None
        self.nearest_bmvert = None
        self.nearest_bmedge = None
        
        self.undo = []
        
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
        pass
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        pass
    
    def draw_postview(self, context):
        ''' Place post view drawing code in here '''
        self.tar_bmeshrender.draw(opts=self.render_normal)
        common_drawing_bmesh.glDrawBMFaces(self.selected_bmfaces, opts=self.render_selected)
        common_drawing_bmesh.glDrawBMEdges(self.selected_bmedges, opts=self.render_selected)
        common_drawing_bmesh.glDrawBMVerts(self.selected_bmverts, opts=self.render_selected)
        if self.nearest_bmface and not self.selected_bmverts and not self.selected_bmedges and not self.selected_bmfaces:
            common_drawing_bmesh.glDrawBMFace(self.nearest_bmface, opts=self.render_nearest)
        if self.nearest_bmedge:
            common_drawing_bmesh.glDrawBMEdge(self.nearest_bmedge, opts=self.render_nearest)
        if self.nearest_bmvert:
            common_drawing_bmesh.glDrawBMVert(self.nearest_bmvert, opts=self.render_nearest)
        #common_drawing_bmesh.glDrawBMVert(self.tar_bmesh.verts[0], opts=self.render_selected)
    
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
        
        if eventd['press'] == 'A':
            self.selected_bmverts = []
            self.selected_bmedges = []
            self.selected_bmfaces = []
        
        if eventd['press'] == 'X':
            if self.selected_bmfaces:
                for bmf in self.selected_bmfaces:
                    self.tar_bmesh.faces.remove(bmf)
                self.set_selection()
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
                return ''
            if self.selected_bmedges:
                try:
                    for bme in self.selected_bmedges:
                        self.tar_bmesh.edges.remove(bme)
                except:
                    pass
                self.set_selection()
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
                return ''
            if self.selected_bmverts:
                for bmv in self.selected_bmverts:
                    self.tar_bmesh.verts.remove(bmv)
                self.set_selection()
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
                return ''
        
        if eventd['press'] == 'D' and self.selected_bmedges:
            if len(self.selected_bmedges[0].link_faces) == 2:
                bmesh.utils.face_join(self.selected_bmedges[0].link_faces)
                self.set_selection()
                self.clear_nearest()
                self.tar_bmeshrender.dirty()
                return ''
        
        if eventd['press'] == 'CTRL+Z':
            self.redo(context)
            return ''
        
        if eventd['press'] == 'LEFTMOUSE':
            return self.handle_click(context, eventd)
        
        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering
            #update brush and brush size
            p3d = self.get_mouse_raycast(eventd)
            if not p3d: return ''
            
            min_bmv,md = self.closest_bmvert(p3d, max_dist=0.03)
            
            if not min_bmv:
                min_bme,md = self.closest_bmedge(p3d, max_dist=0.02)
            else:
                min_bme = None
            
            if not min_bme and not min_bmv:
                min_bmf = self.closest_bmface(p3d)
            else:
                min_bmf = None
            
            self.nearest_bmvert = min_bmv
            self.nearest_bmedge = min_bme
            self.nearest_bmface = min_bmf
        
        return ''
    
    def closest_bmvert(self, p3d, max_dist=0.0):
        min_bmv = None
        md = 0
        for bmv in self.tar_bmesh.verts:
            d = (p3d - bmv.co).length
            if max_dist > 0 and d > max_dist: continue
            if min_bmv == None or d < md:
                md = d
                min_bmv = bmv
        return (min_bmv,md)
    
    def closest_bmedge(self, p3d, lbme=None, max_dist=0.0):
        if not lbme: lbme = self.tar_bmesh.edges
        lmin_bme = []
        md = 0
        for bme in lbme:
            # if len(bme.link_faces) == 2:
            #     # bmedge has two faces, so we cannot add another face
            #     # without making non-manifold
            #     continue
            t,d = closest_t_and_distance_point_to_line_segment(p3d, bme.verts[0].co, bme.verts[1].co)
            if max_dist > 0 and d > max_dist: continue
            if not lmin_bme or d <= md + 0.0001:
                if not lmin_bme and abs(d-md) <= 0.0001:
                    lmin_bme += [bme]
                else:
                    md = d
                    lmin_bme = [bme]
        if not lmin_bme: return (None,0)
        if len(lmin_bme) == 2:
            return orthogonalest_bmedge(p3d, lmin_bme)
        return (lmin_bme[0],md)
    
    def orthogonalest_bmedge(self, p3d, lbme):
        p00,p01 = lbme[0].verts[0].co,lbme[0].verts[1].co
        p10,p11 = lbme[1].verts[0].co,lbme[1].verts[1].co
        _,d0 = closest_t_and_distance_point_to_line_segment(p3d, p00, p01)
        _,d1 = closest_t_and_distance_point_to_line_segment(p3d, p10, p11)
        
        if abs(d0-d1) > 0.0001:
            return lbme[0] if d0 < d1 else lbme[1]
        
        p001,p00p = (p01-p00).normalized(), (p3d-p00).normalized()
        p101,p10p = (p11-p10).normalized(), (p3d-p10).normalized()
        
        theta0 = abs(p00p.dot(p001))
        theta1 = abs(p10p.dot(p101))
        
        return lbme[0] if theta0 < theta1 else lbme[1]
    
    def closest_bmface(self, p3d):
        for bmf in self.tar_bmesh.faces:
            bmv0 = bmf.verts[0]
            for bmv1,bmv2 in zip(bmf.verts[1:-1], bmf.verts[2:]):
                if intersect_point_tri(p3d, bmv0.co, bmv1.co, bmv2.co):
                    return bmf
        return None
    
    def get_mouse_raycast(self, eventd):
        p3d = common_utilities.ray_cast_path_bvh(eventd['context'], mesh_cache['bvh'], self.mx, [eventd['mouse']])
        if len(p3d) == 0:
            return None
        return p3d[0]
    
    def set_selection(self, lbmv=None, lbme=None, lbmf=None):
        self.selected_bmverts = [] if not lbmv else lbmv
        self.selected_bmedges = [] if not lbme else lbme
        self.selected_bmfaces = [] if not lbmf else lbmf
    
    def clear_nearest(self):
        self.nearest_bmvert = None
        self.nearest_bmedge = None
        self.nearest_bmface = None
    
    def create_undo(self):
        liv = [v.index for v in self.selected_bmverts]
        lie = [e.index for e in self.selected_bmedges]
        lif = [f.index for f in self.selected_bmfaces]
        self.undo += [(self.tar_bmesh.copy(),liv,lie,lif)]
        if len(self.undo) > 20:
            self.undo.pop(0)
    
    def redo(self, context):
        if not self.undo: return
        bme,liv,lie,lif = self.undo.pop()
        bpy.ops.object.mode_set(mode='OBJECT')
        bme.to_mesh(self.tar_object.data)
        bpy.ops.object.mode_set(mode='EDIT')
        bme = bmesh.from_edit_mesh(context.object.data)
        bme.verts.ensure_lookup_table()
        bme.edges.ensure_lookup_table()
        bme.faces.ensure_lookup_table()
        self.selected_bmverts = [bme.verts[i] for i in liv]
        self.selected_bmedges = [bme.edges[i] for i in lie]
        self.selected_bmfaces = [bme.faces[i] for i in lif]
        self.tar_bmesh = bme
        self.tar_bmeshrender.replace_bmesh(self.tar_bmesh)
        self.clear_nearest()
    
    def handle_click(self, context, eventd, dry_run=False):
        p3d = self.get_mouse_raycast(eventd)
        if not p3d: return ''
        
        self.create_undo()
        
        sbmv,sbme,sbmf = self.selected_bmverts,self.selected_bmedges,self.selected_bmfaces
        lbmv,lbme,lbmf = len(sbmv),len(sbme),len(sbmf)
        
        if lbme >= 1:
            if self.nearest_bmedge:
                # check if edges share face
                if any(self.nearest_bmedge in f.edges for f in sbme[0].link_faces):
                    self.set_selection(lbme=[self.nearest_bmedge])
                    return ''
            if self.nearest_bmvert:
                # check if nearest bmvert belongs to lbme
                if any(self.nearest_bmvert in e.verts for e in sbme):
                    self.set_selection(lbmv=[self.nearest_bmvert])
                    return ''
                # check if nearest bmvert belongs to face adj to lbme
                if any(self.nearest_bmvert in f.verts for f in sbme[0].link_faces):
                    self.set_selection(lbmv=[self.nearest_bmvert])
                    return ''
            
            if lbme >= 2:
                min_bme = self.orthogonalest_bmedge(p3d, sbme)
                sbme = [min_bme]
            
            if self.nearest_bmedge:
                # determine if two edges share face
                bme0 = sbme[0]
                bme1 = self.nearest_bmedge
                if any(bme0 in f.edges for f in bme1.link_faces):
                    self.set_selection(lbme=[self.nearest_bmedge])
                    return ''
                # determine if two edges share vert
                sbmv = [v for v in bme1.verts if v in bme0.verts]
                if sbmv:
                    bmv0 = sbmv[0]
                    bmv1 = bme0.other_vert(bmv0)
                    bmv2 = bme1.other_vert(bmv0)
                    bmf = self.tar_bmesh.faces.new([bmv0,bmv1,bmv2])
                    lbme = [e for e in bmv2.link_edges if e in bmv1.link_edges]
                    self.set_selection(lbmf=[bmf])
                    self.tar_bmeshrender.dirty()
                    return ''
                # bridge
                bmv0,bmv1 = bme0.verts
                bmv3,bmv2 = bme1.verts
                d01 = bmv1.co - bmv0.co
                d02 = bmv2.co - bmv0.co
                d31 = bmv1.co - bmv3.co
                d32 = bmv2.co - bmv3.co
                if (d02.cross(d01)).dot(d31.cross(d32)) < 0:
                    bmv2,bmv3 = bmv3,bmv2
                
                bmf = self.tar_bmesh.faces.new([bmv0,bmv1,bmv3,bmv2])
                self.set_selection(lbmf=[bmf])
                self.tar_bmeshrender.dirty()
                return ''
            
            if self.nearest_bmvert:
                bmv = self.nearest_bmvert
            else:
                bmv = self.tar_bmesh.verts.new(p3d)
            bmf = self.tar_bmesh.faces.new([sbme[0].verts[0], sbme[0].verts[1], bmv])
            self.set_selection(lbmv=[bmv], lbmf=[bmf])
            self.tar_bmeshrender.dirty()
            return ''
        
        if lbmf == 1:
            if self.nearest_bmedge:
                # just select nearest
                self.set_selection(lbme=[self.nearest_bmedge])
                return ''
            min_bme,_ = self.closest_bmedge(p3d, lbme=sbmf[0].edges)
            bme,bmv = bmesh.utils.edge_split(min_bme, min_bme.verts[0], 0.5)
            if self.nearest_bmvert:
                # merge bmv into nearest_bmvert
                bmesh.utils.vert_splice(bmv, self.nearest_bmvert)
                bmv = self.nearest_bmvert
                lbme = [e for e in sbmf[0].edges if bmv in e.verts and len(e.link_faces) != 2]
            else:
                lbme = bmv.link_edges
                bmv.co = p3d
            self.set_selection(lbmv=[bmv], lbme=lbme)
            self.tar_bmeshrender.dirty()
            return ''
        
        if lbmv == 1:
            if self.nearest_bmedge:
                # check if bmv belongs to nearest_bmedge
                if sbmv[0] in self.nearest_bmedge.verts:
                    self.set_selection(lbme=[self.nearest_bmedge])
                    return ''
                # check if bmv belong to face adj to nearest_bmedge
                if any(sbmv[0] in f.verts for f in self.nearest_bmedge.link_faces):
                    self.set_selection(lbme=[self.nearest_bmedge])
                    return ''
            
            if self.nearest_bmvert:
                # check if we are splitting a face
                bmv0 = sbmv[0]
                bmv1 = self.nearest_bmvert
                ibmf = set(bmv0.link_faces) & set(bmv1.link_faces)
                if ibmf:
                    bmf = ibmf.pop()
                    bmesh.utils.face_split(bmf, bmv0, bmv1)
                    self.set_selection()
                    self.clear_nearest()
                    self.tar_bmeshrender.dirty()
                    return ''
            
            if self.nearest_bmedge:
                bmv0 = sbmv[0]
                bmv1 = self.nearest_bmedge.verts[0]
                bmv2 = self.nearest_bmedge.verts[1]
                bmf = self.tar_bmesh.faces.new([bmv0,bmv1,bmv2])
                self.set_selection(lbmf=[bmf])
                self.tar_bmeshrender.dirty()
                return ''
            if self.nearest_bmvert:
                bmv = self.nearest_bmvert
                ibme = [e for e in sbmv[0].link_edges if bmv in e.verts]
                if ibme:
                    create_edge = False
                    bme = ibme[0]
                else:
                    create_edge = True
            else:
                bmv = self.tar_bmesh.verts.new(p3d)
                create_edge = True
            if create_edge:
                bme = self.tar_bmesh.edges.new([sbmv[0], bmv])
            self.set_selection(lbmv=[bmv,sbmv[0]], lbme=[bme])
            self.tar_bmeshrender.dirty()
            return ''
        
        if self.nearest_bmvert:
            self.set_selection(lbmv=[self.nearest_bmvert])
            return ''
        
        if self.nearest_bmedge:
            nbme = self.nearest_bmedge
            self.set_selection(lbmv=[nbme.verts[0], nbme.verts[1]],lbme=[nbme])
            return ''
        
        if self.nearest_bmface:
            self.set_selection(lbmf=[self.nearest_bmface])
            return ''
        
        bmv = self.tar_bmesh.verts.new(p3d)
        self.set_selection(lbmv=[bmv])
        self.tar_bmeshrender.dirty()
        
        return ''
