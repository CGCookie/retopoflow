'''
Copyright (C) 2014 CG Cookie
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

import math
from math import sin, cos
import time
import copy
import itertools

import bpy
import bmesh
import blf, bgl

from mathutils import Vector, Quaternion
from mathutils.geometry import intersect_point_line, intersect_line_plane
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d

from ..lib import common_utilities
from ..lib.common_utilities import iter_running_sum, dprint, get_object_length_scale,frange
from ..lib.common_utilities import zip_pairs, closest_t_of_s, closest_t_and_distance_point_to_line_segment
from ..lib.common_utilities import sort_objects_by_angles, vector_angle_between, rotate_items, point_inside_loop2d
from ..lib.classes.profiler.profiler import profiler
from ..lib.common_bezier import cubic_bezier_find_closest_t_approx

from ..lib.common_bezier import cubic_bezier_blend_t, cubic_bezier_derivative, cubic_bezier_fit_points, cubic_bezier_split, cubic_bezier_t_of_s_dynamic
from ..cache import mesh_cache
from ..pat_patch import Patch
from ..patch_geometry import *
from ..lib.common_mesh import join_bmesh, find_perimeter_verts

class EPVert:
    def __init__(self, position):
        self.position  = position
        self.snap_pos  = position
        self.snap_norm = Vector()
        self.visible = True
        self.epedges = []
        self.eppatches = []  # <--- like Bmesh, would be nice to keep up with this
        self.isinner = False
        self.doing_update = False
        self.update()
    
    def snap(self):
        p,n,_ = EdgePatches.getClosestPoint(self.position)
        self.snap_pos  = p
        self.snap_norm = n
    
    def update(self, do_edges=True, do_faces = True):
        if self.doing_update: return
        
        #pr = profiler.start()
        self.snap()
        if do_edges:
            self.doing_update = True
            self.update_epedges()
            for epedge in self.epedges:
                epedge.update()
            self.doing_update = False
        
        if do_faces:
            self.doing_update = True
            self.update_eppatches()
            self.doing_update = False
        #pr.done()
    
    def update_epedges(self):
        if len(self.epedges)>2:
            ''' sort the epedges about normal '''
            l_vecs = [epe.get_outer_vector_at(self) for epe in self.epedges]
            self.epedges = sort_objects_by_angles(-self.snap_norm, self.epedges, l_vecs)  # positive snap_norm to sort clockwise
        for epe in self.epedges:
            epe.update()
    
    def update_eppatches(self):
        if len(self.eppatches)>2:
            ''' sort the eppatches about normal '''
            l_vecs = [epp.info_display_pt()-self.snap_pos for epp in self.eppatches]
            self.epedges = sort_objects_by_angles(-self.snap_norm, self.eppatches, l_vecs)  # positive snap_norm to sort clockwise
        for epp in self.eppatches:
            epp.update()
            
    def connect_epedge(self, epedge):
        assert not self.isinner, 'Attempting to connect inner EPVert to EPEdge'
        assert epedge not in self.epedges, 'Attempting to reconnect EPVert to EPEdge'
        self.epedges.append(epedge)
        self.update_epedges()
    
    def connect_epedge_inner(self, epedge):
        assert not self.isinner, 'Attempting to connect inner EPVert to EPEdge as inner'
        assert len(self.epedges) == 0, 'Attempting to connect non-inner EPVert to EPEdge as inner'
        self.epedges.append(epedge)
        self.isinner = True
        self.update_epedges()
    
    def get_epedges(self):
        return list(self.epedges)
    
    def get_inner_epverts(self):
        if self.isinner: return [self]
        return [epe.get_inner_epvert_at(self) for epe in self.epedges]
        
    
    def disconnect_epedge(self, epedge):
        assert epedge in self.epedges, 'Attempting to disconnect unconnected EPEdge'
        #pr = profiler.start()
        self.epedges = [epe for epe in self.epedges if epe != epedge]
        self.isinner=False
        self.update_epedges()
        #pr.done()
    
    def is_inner(self): return self.isinner
    
    def is_picked(self, pt, maxdist=0.1):
        if not self.visible: return False
        return (pt-self.snap_pos).length < maxdist
    
    def is_unconnected(self):
        return len(self.epedges)==0
    
    def get_next_epedge(self, epedge):
        ''' returns the following (anti-clockwise) EPEdge '''
        if len(self.epedges) == 1: return None
        return self.epedges[(self.epedges.index(epedge)+1)%len(self.epedges)]


class EPEdge:
    tessellation_count = 20
    #subdivision = 8 #@JonDenning  Why are some things defined up here for the class vs the instance?
    def __init__(self, epvert0, epvert1, epvert2, epvert3, tess = 20):
        self.epvert0 = epvert0
        self.epvert1 = epvert1
        self.epvert2 = epvert2
        self.epvert3 = epvert3
        
        self.l_ts = []
        self.eppatches = []
        
        self.curve_verts = []  #these are mainly used for drawing at this point
        self.curve_norms = []
        self.edge_verts = [] #these are for patch making
        self.edge_vert_norms = []
        self.subdivision = 8
        epvert0.connect_epedge(self)
        epvert1.connect_epedge_inner(self)
        epvert2.connect_epedge_inner(self)
        epvert3.connect_epedge(self)
        
        if tess > 5:
            self.tessellation_count = tess
        self.update()
    
    def epverts(self): return (self.epvert0, self.epvert1, self.epvert2, self.epvert3)
    def epverts_pos(self): return (self.epvert0.snap_pos, self.epvert1.snap_pos, self.epvert2.snap_pos, self.epvert3.snap_pos)
    
    def info_display_pt(self):
        if len(self.curve_verts) == 0: return Vector((0,0,0))
        if len(self.curve_verts) < 3: return self.curve_verts[0]
        mid = math.ceil(self.tessellation_count/2)
        pt = self.curve_verts[mid]
        no = self.curve_norms[mid]
        dir_off = no.cross(self.curve_verts[mid+1]-self.curve_verts[mid])
        dir_off.normalize()
        len_off = .1 * (self.curve_verts[-1] - self.curve_verts[0]).length
        
        info_pt = pt + len_off*dir_off
        return info_pt
    
    def update(self):
        #pr = profiler.start()
        getClosestPoint = EdgePatches.getClosestPoint
        tessellation_count = EPEdge.tessellation_count
        p0,p1,p2,p3 = self.get_positions()
        
        #pr2 = profiler.start()
        lpos = [cubic_bezier_blend_t(p0,p1,p2,p3,i/float(tessellation_count)) for i in range(tessellation_count+1)]
        e_v_pos = [cubic_bezier_blend_t(p0,p1,p2,p3,i/float(self.subdivision)) for i in range(self.subdivision+1)]
        #pr2.done()

        self.curve_verts = []
        self.curve_norms = []
        self.edge_verts = []  #comment me out for cool looking stuff
        self.edge_vert_norms = []  
        #pr2 = profiler.start()
        for pos in lpos:
            #pr3 = profiler.start()
            p,n,i = getClosestPoint(pos)
            self.curve_verts.append(p)
            self.curve_norms.append(n)
            #pr3.done()
        
        for pos in e_v_pos:
            #pr3 = profiler.start()
            p,n,i = getClosestPoint(pos)
            self.edge_verts.append(p)
            self.edge_vert_norms.append(n)
        #pr2.done()

        #pr.done()
    
    def get_positions(self):
        return (self.epvert0.snap_pos, self.epvert1.snap_pos, self.epvert2.snap_pos, self.epvert3.snap_pos)
    
    def get_inner_epverts(self):
        return (self.epvert1, self.epvert2)
    
    def get_inner_epvert_at(self, epv03):
        assert self.epvert0 == epv03 or self.epvert3 == epv03, 'Attempting to get inner EPVert of EPEdge for not connected EPVert'
        return self.epvert1 if self.epvert0 == epv03 else self.epvert2
    
    def get_outer_epvert_at(self, epv12):
        assert self.epvert1 == epv12 or self.epvert2 == epv12, 'Attempting to get outer EPVert of EPEdge for not connected EPVert'
        return self.epvert0 if self.epvert1 == epv12 else self.epvert3
    
    def get_outer_vector_at(self, epv03):
        epv12 = self.get_inner_epvert_at(epv03)
        return epv12.snap_pos - epv03.snap_pos
    
    def get_opposite_epvert(self, epv03):
        assert self.epvert0 == epv03 or self.epvert3 == epv03, 'Attempting to get inner EPVert of EPEdge for not connected EPVert'
        return self.epvert3 if self.epvert0 == epv03 else self.epvert0
    
    def disconnect(self):
        self.epvert0.disconnect_epedge(self)
        self.epvert1.disconnect_epedge(self)
        self.epvert2.disconnect_epedge(self)
        self.epvert3.disconnect_epedge(self)
    
    def is_picked(self, pt, maxdist=0.1):
        for p0,p1 in zip_pairs(self.curve_verts):
            t,d = closest_t_and_distance_point_to_line_segment(pt, p0, p1)
            if d < maxdist: return True
        return False
    
    def has_epvert(self, epvert):
        return epvert==self.epvert0 or epvert==self.epvert1 or epvert==self.epvert2 or epvert==self.epvert3
    
    def min_dist_to_point(self, pt):
        return min(closest_t_and_distance_point_to_line_segment(pt,p0,p1)[1] for p0,p1 in zip_pairs(self.curve_verts))
    
    def replace_epvert(self, epvert_from, epvert_to):
        assert self.epvert0==epvert_from or self.epvert1==epvert_from or self.epvert2==epvert_from or self.epvert3==epvert_from
        assert self.epvert0!=epvert_to and self.epvert1!=epvert_to and self.epvert2!=epvert_to and self.epvert2!=epvert_to
        if   self.epvert0==epvert_from: self.epvert0 = epvert_to
        elif self.epvert1==epvert_from: self.epvert1 = epvert_to
        elif self.epvert2==epvert_from: self.epvert2 = epvert_to
        elif self.epvert3==epvert_from: self.epvert3 = epvert_to
        epvert_from.disconnect_epedge(self)
        epvert_to.connect_epedge(self)
    
    def get_closest_point(self, pt):
        p0,p1,p2,p3 = self.get_positions()
        if True or len(self.curve_verts) < 3:
            return cubic_bezier_find_closest_t_approx(p0,p1,p2,p3,pt)
        min_t,min_d = -1,-1
        i,l = 0,len(self.curve_verts)
        for p0,p1 in zip(self.curve_verts[:-1], self.curve_verts[1:]):
            t,d = common_utilities.closest_t_and_distance_point_to_line_segment(pt, p0,p1)
            if min_t < 0 or d < min_d: min_t,min_d = (i+t)/l,d
            i += 1
        return min_t,min_d

class EPPatch:
    def __init__(self, lepedges):
        self.lepedges = list(lepedges)
        self.epedge_fwd = [e1.has_epvert(e0.epvert3) for e0,e1 in zip_pairs(self.lepedges)]
        for epv in self.get_epverts():
            epv.eppatches += [self]
        
        
        self.center = Vector()
        self.normal = Vector()

        self.L_sub = [ep.subdivision for ep in self.lepedges] #this may be problem.  self.lepedges not in same order as get_edge loops
        self.patch_solution = []
        self.verts = []
        self.faces = []
        
        self.bmesh = bmesh.new()
        self.patch = None
        
        #add a mesh and object to the scene #TODO...don't do this
        self.me = bpy.data.meshes.new('Patch')
        self.ob = bpy.data.objects.new('Patch', self.me)
        bpy.context.scene.objects.link(self.ob)
        
        self.update()
        
    def update(self):
        ctr = Vector((0,0,0))
        cnt = 0
        for epe in self.lepedges:
            for p in epe.curve_verts:
                ctr += p
            cnt += len(epe.curve_verts)
        if cnt:
            mx  = EdgePatches.matrix
            imx = EdgePatches.matrixinv
            mxn = EdgePatches.matrixnorm
            p,n,_ = EdgePatches.getClosestPoint(ctr/float(cnt))
            self.center =  p
            self.normal =  n
        else:
            self.center = Vector()
            self.normal = Vector()
        
        
        self.L_sub = [ep.subdivision for ep in self.lepedges]
        if self.patch and self.patch.active_solution_index != -1:
            self.generate_geometry()
        else:
            self.faces, self.verts = [], []
            
            
    def get_outer_points(self):
        def get_verts(epe,fwd):
            if fwd: return epe.curve_verts
            return reversed(epe.curve_verts)
        return [p for epe,fwd in zip(self.lepedges,self.epedge_fwd) for p in get_verts(epe,fwd)]
    
    def get_epverts(self):
        return [epe.epvert0 if fwd else epe.epvert3 for epe,fwd in zip(self.lepedges,self.epedge_fwd)]

    def get_edge_loops(self):
        def get_verts(epe,fwd):
            if fwd: return epe.edge_verts
            ed_verts = epe.edge_verts.copy()
            ed_verts.reverse()
            return ed_verts
        return [get_verts(epe,fwd) for epe,fwd in zip(self.lepedges,self.epedge_fwd)]
        
    def get_corner_locations(self):
        epvs = self.get_epverts()
        return [epv.snap_pos for epv in epvs]
    
    def info_display_pt(self):
        pts = self.get_epverts()
        center = Vector((0,0,0))
        for pt in pts:
            center += 1/len(pts) * pt.snap_pos
        return center
    
    def validate_patch_for_ILP(self):
        '''
        just check that the perimter is even
        '''
        perim_sum = sum([epe.subdivision for epe in self.lepedges])
        if perim_sum % 2: return False
        return True
    
    def hovered_2d(self,context,mouse_x,mouse_y):
        reg = context.region
        rv3d = context.space_data.region_3d
        loop = [epv.snap_pos for epv in self.get_epverts()]
        loop_2d = [location_3d_to_region_2d(reg, rv3d, pt) for pt in loop if pt]
        
        return point_inside_loop2d(loop_2d, (mouse_x, mouse_y))

    def ILP_initial_solve(self):
        if not self.validate_patch_for_ILP(): return
        self.patch = Patch()
        self.patch.edge_subdivision = self.L_sub
        self.patch.permute_and_find_solutions()
        #sleep occasionally needed
        self.patch.active_solution_index = 0
        L, rot_dir, pat, sol = self.patch.get_active_solution()
        sol.report()
        
        return
    def generate_geometry(self):
        
        self.bmesh.free()
        
        if self.patch == None: return
        
        N = len(self.get_corner_locations())
        L, (n, fwd), pat, sol = self.patch.get_active_solution()
        c_vs = self.get_corner_locations()
        ed_loops = self.get_edge_loops()
        
        print('%i Sided Patch' % N)
        print('Solved by pattern # %i' % pat)
        #print('%i side is now the 0 side' % n)
        #print('%i direction around path' % fwd)
        
        print('Subdivisions by active solution')
        print(L)
        
        #print('Subdivision by self.L_sub (lepedges)')
        #print(self.L_sub)
        
        #print('Pre Corrected Subdivisions, derived from len(edge loops)')
        #print([len(loop)-1 for loop in ed_loops])
        
        if fwd == -1:
            #a = (n + 1) % N
            vs = c_vs[n:] + c_vs[:n]
            vs.reverse()
            vs = [vs[-1]] + vs[0:len(vs)-1]
            
            new_loops = [ed_l.copy() for ed_l in ed_loops]
            #if n != 0??
            if n != 0:
                new_loops = new_loops[n:] + new_loops[:n] #shift them
            
            new_loops.reverse()  #this just reverses the list of loops
            new_loops = [new_loops[-1]] + new_loops[0:len(ed_loops)-1] #make the tip the tip again
            
            #this reverses each vert chain in the loop
            for ed_l in new_loops:
                ed_l.reverse()
            
            ed_loops = new_loops
                  
        else:
            vs = c_vs[n:] + c_vs[:n]
            new_loops = [ed_l.copy() for ed_l in ed_loops]
            ed_loops = new_loops[n:] + new_loops[:n]    
        
        #print('subdivisions calced from corrected edge loops')
        #print([len(loop)-1 for loop in ed_loops])
        
        verts, fcs, geom_dict = [], [], {}
        vars = self.patch.get_active_solution_variables()
        #print(vars)
        vs = ed_loops
        
        if N == 6:
            ps = vars[:6]
            if pat == 0:
                patch_fn = hex_prim_0 #(vs, L, ps, *vars[6:])
            elif pat == 1:
                patch_fn = hex_prim_1#(vs, L, ps, *vars[6:])
            elif pat == 2:
                #vars += [0,0]
                patch_fn = hex_prim_2#(vs, L, ps, *vars[6:])
            elif pat == 3:
                #vars += [0]
                patch_fn = hex_prim_3#(vs, L, ps, *vars[6:])
        elif N == 5:
            ps = vars[:5]
            if pat == 0:
                patch_fn = pent_prim_0#(vs, L, ps)
            elif pat == 1:
                #print(vars[5:])
                #vars += [0]
                patch_fn = pent_prim_1#(vs, L, ps, *vars[5:])
            elif pat == 2:
                #vars += [0,0,0]
                patch_fn = pent_prim_2#(vs, L, ps, *vars[5:])
            elif pat == 3:
                #vars += [0,0]
                patch_fn = pent_prim_3#(vs, L, ps, *vars[5:])
        elif N == 4:
            ps = vars[:4]
            if pat == 0:
                patch_fn = quad_prim_0#(vs, L, ps)
            elif pat == 1:
                patch_fn = quad_prim_1#(vs, L, ps, *vars[4:])
            elif pat == 2:
                patch_fn = quad_prim_2#(vs, L, ps, *vars[4:])
            elif pat == 3:
                #vars += [0]
                patch_fn = quad_prim_3#(vs, L, ps, *vars[4:])
            elif pat == 4:
                #vars += [0]
                patch_fn = quad_prim_4#(vs, L, ps, *vars[4:])
        elif N == 3:
            ps = vars[:3]
            if pat == 0:
                patch_fn = tri_prim_0#(vs, L, ps)
            elif pat == 1:
                #vars += [0,0]  q1 and q2 vars now included in ILP problem
                patch_fn = tri_prim_1#(vs,L,ps,*vars[3:])

        #All information collected, now generate the patch
        
        #First, slice off the padding from each side
        pad_geom_dict = pad_patch_sides_method(vs, ps, L, pat)
        if not pad_geom_dict:
            print('padding failure!!')
            self.verts, self.faces, self.gdict = [], [], {}
            
        #make a bmesh of the padding
        pad_bme = make_bme(pad_geom_dict['verts'], pad_geom_dict['faces'])
        relax_bmesh(pad_bme, pad_geom_dict['perimeter verts'], 3, spring_power=.1, quad_power=.1)
        
        #these corners re in order, and correspond to V0, V1, V2 etc corners of the
        #entire patch/polygon
        inner_corners = [pad_bme.verts[i].co for i in pad_geom_dict['inner corners']]
    
        #take the new inner corners, and fill them with patch
        patch_geom = patch_fn(inner_corners, *vars[N:])
        patch_bme = make_bme(patch_geom['verts'], patch_geom['faces'])
        
        #correlate the outer verts of patch primitive to inner verts of padding
        
        #these outer verts are in order, but the 0 index item in the list
        #is not correlated to V0 in any way.
        outer_verts = find_perimeter_verts(patch_bme)
        #print('the outer vert indices in the patch primitive in no particular order')
        #print(outer_verts)
        
        #the patch corners, are in order, because they are found wrt 'inner corners'
        #which are in order
        patch_corners = [find_coord(patch_bme, v, outer_verts) for v in inner_corners]
        
        #print('The inner vert indices in the padding mesh')
        #print(pad_geom_dict['inner verts'])
        
        #print('The outer corner indices of the patch primitive')
        #print(patch_corners)
        
        #print('The inner corner indices of the padding mesh')
        #print(pad_geom_dict['inner corners'])
        
        
        #use patch corners to get outer verts in correct orientations
        ind0 = outer_verts.index(patch_corners[0])
        outer_verts = outer_verts[ind0:] + outer_verts[:ind0]
        
        #print('line up the 0 corner by shifting %i' % ind0)
        #print(outer_verts)
        
        #print('reverse the order?')
        ind1patch = outer_verts.index(patch_corners[1])
        ind1pad = pad_geom_dict['inner verts'].index(pad_geom_dict['inner corners'][1])
        
        ind2patch = outer_verts.index(patch_corners[2])
        ind2pad = pad_geom_dict['inner verts'].index(pad_geom_dict['inner corners'][2])
        
        if ind1patch != ind1pad or ind2patch != ind2pad:  #must check 2 inds due to symmetric case.  reverse direction with pole at exact midpoint
            #print('reverse the direction')
            outer_verts.reverse()
            outer_verts = [outer_verts[-1]] + outer_verts[0:len(outer_verts)-1]
            #print(outer_verts)
            #print(pad_geom_dict['inner verts'])
        
        perimeter_map = {}    
        for n, m in zip(outer_verts, pad_geom_dict['inner verts']):
            perimeter_map[n] = m
            
        #relax_bmesh(patch_bme, outer_verts, iterations = 3, spring_power=.1, quad_power=.2)
        #if N== 5 and pat == 2:
        #    print('special case...something here is wrong')
        #    print(perimeter_map)
        #    join_bmesh(patch_bme, pad_bme, {})
        #else:
        join_bmesh(patch_bme, pad_bme, perimeter_map) #this modifies target (pad_bme)
        
        #the pad bmesh now is completely filled, so it's good to go.
        relax_bmesh(pad_bme, exclude = pad_geom_dict['perimeter verts'], iterations = 2)
        
        pad_bme.verts.ensure_lookup_table()
        pad_bme.faces.ensure_lookup_table()
        
        
        #finally, snap everything
        for v in pad_bme.verts:
            p, _, _ = EdgePatches.getClosestPoint(v.co, meth = 'BVH')
            v.co = p
        
        geom_dict = {}
        geom_dict['bme'] = pad_bme
        geom_dict['verts'] = [v.co for v in pad_bme.verts]
        geom_dict['faces'] = [tuple(v.index for v in f.verts) for f in pad_bme.faces]
        
        #copy some relevant info from padding geom into geom dict that is accessible
        #from patch class
        geom_dict['patch primitive corners'] = pad_geom_dict['inner corners']
        geom_dict['reduced subdivision'] = pad_geom_dict['new subdivs']
        geom_dict['patch perimeter verts'] = pad_geom_dict['perimeter verts']
        #return geom_dict['verts'], geom_dict['faces'], geom_dict

        
        self.verts, self.faces, self.gdict = geom_dict['verts'], geom_dict['faces'], geom_dict
        
        #print('check indices of inner corners and inner verts')
        #print(self.gdict['patch primitive corners'])
        #print(self.gdict['patch perimeter verts'])
        
        #print('check the new subdivisions')
        #print(self.gdict['reduced subdivision'])
        
        self.bmesh = pad_bme
        self.bmesh.to_mesh(self.me)
    
            
    def rotate_solution(self,step):
        if not self.patch: return
        if self.patch.rotate_solution(step):
            self.generate_geometry()
            
    def mirror_solution(self):
        if not self.patch: return
        if self.patch.mirror_solution():
            self.generate_geometry()
   
    def change_pattern(self, n):
        if not self.patch: return
        if self.patch.change_pattern(n):
            self.generate_geometry()
        else:
            print('Pattern %i does not solve patch' % n)


    def adjust_parameter(self, param_index, delta): #perhaps maybe...use a dictionary
   
        
        success = self.patch.adjust_patch(param_index, delta)
        
        if success:
            self.generate_geometry()
       
       
    def generate_bmesh(self):
        self.bmesh = bmesh.new()
        bmverts = [self.bmesh.verts.new(v) for v in self.verts]  #TODO, matrix stuff
        self.bmesh.verts.index_update()
        
        bmfaces = [self.bmesh.faces.new(tuple(bmverts[iv] for iv in face)) for face in self.faces]
        self.bmesh.faces.index_update()
        
        self.bmesh.verts.ensure_lookup_table()
        self.bmesh.faces.ensure_lookup_table()
        
        self.bmesh.to_mesh(self.me)
        
        
    def bmesh_to_patch(self):
        
        if not self.bmesh: return
        self.verts = []
        self.faces = []
        
        self.verts = [v.co for v in self.bmesh.verts] #TODO, matrix stuff
        self.faces = [tuple([v.index for v in f.verts]) for f in self.bmesh.faces]
    
    def update_bmesh_verts(self):
        if len(self.verts) != len(self.bmesh.verts):
            print('uh oh, bmesh and verts dont match')
            return
        self.bmesh.verts.ensure_lookup_table()
        for i, v in enumerate(self.verts):
            self.bmesh.verts[i].co = v
        
        self.bmesh.to_mesh(self.me)
            
    def relax_patch(self):
        bmmesh = self.bmesh
        
        relax_verts =list(set([i for i in range(0,len(self.verts))]) - 
                          set(self.gdict['patch perimeter verts']))
        
        #relax_verts= [i for i in range(0,len(self.verts))]
        #print(relax_verts)
        
        deltas = dict()
        
        #edges as springs
        for i in relax_verts:
            bmv0 = bmmesh.verts[i]
            lbmeds = bmv0.link_edges
            
            net_f = Vector((0,0,0))
            
        
            for bme in lbmeds:
                bmv1 = bme.other_vert(bmv0)
                net_f += bmv1.co - bmv0.co
                
            deltas[bmv0.index] = .1*net_f  #todo, normalize this to average spring length?
            
        
        #cross braces on faces, try to expand face to square
        for bmf in bmmesh.faces:
            if len(bmf.verts) != 4: continue
            
            dia0 = bmf.verts[2].co - bmf.verts[0].co
            dia1 = bmf.verts[3].co - bmf.verts[1].co
            
            avg_l = .5 * dia0.length + .5 * dia1.length
            
            d0 = .5 * (dia0.length - avg_l)
            d1 = .5 * (dia1.length - avg_l)
            
            dia0.normalize()
            dia1.normalize()
            
            #only expand, no tension
            
            if bmf.verts[0].index in relax_verts:
                deltas[bmf.verts[0].index] += .3 * d0 * dia0
            if bmf.verts[2].index in relax_verts:
                deltas[bmf.verts[2].index] += -.3 * d0 * dia0
        
        
            if bmf.verts[1].index in relax_verts:
                deltas[bmf.verts[1].index] += .3 * d1 * dia1
            if bmf.verts[3].index in relax_verts:
                deltas[bmf.verts[3].index] += -.3 * d1 * dia1
                
                
                  
        for i in deltas:
            bmmesh.verts[i].co += deltas[i]    
        
        for i in deltas:
            p, _, _ = EdgePatches.getClosestPoint(bmmesh.verts[i].co, meth = 'BVH')
            bmmesh.verts[i].co = p
        
        self.bmesh.to_mesh(self.me)
        #TODOD, link bmesh to scene, update edit mesh all that shit!!!
            
                                             
class EdgePatches:
    def __init__(self, context, src_obj, tar_obj):
        # class/static variables (shared across all instances)
        EdgePatches.settings     = common_utilities.get_settings()
        EdgePatches.src_name     = src_obj.name
        EdgePatches.tar_name     = tar_obj.name
        EdgePatches.length_scale = get_object_length_scale(src_obj)
        EdgePatches.matrix       = src_obj.matrix_world
        EdgePatches.matrix3x3    = EdgePatches.matrix.to_3x3()
        EdgePatches.matrixinv    = EdgePatches.matrix.inverted()
        EdgePatches.matrixnorm   = EdgePatches.matrixinv.transposed().to_3x3()
        
        # EdgePatch verts, edges, and patches
        self.epverts   = []
        self.epedges   = []
        
        self.eppatches      = set()
        self.epedge_eppatch = dict()
    
    @classmethod
    def getSrcObject(cls):
        return bpy.data.objects[EdgePatches.src_name]
    
    @classmethod
    def getClosestPoint(cls, p, meth = 'OBJ'):
        ''' returns (p,n,i) '''
        #pr = profiler.start()
        mx  = EdgePatches.matrix
        imx = EdgePatches.matrixinv
        mxn = EdgePatches.matrixnorm
        
        if meth == 'OBJ':
            obj = EdgePatches.getSrcObject()
            c,n,i = obj.closest_point_on_mesh(imx * p)
            
        else:
            bvh = mesh_cache['bvh']
            c,n,i,d = bvh.find(imx*p)
        
        ret = (mx*c,mxn*n,i)    
        #pr.done()
        return ret
    
    def debug(self):
        print('Debug')
        print('-----------')
        print('  %d EPVerts' % len(self.epverts))
        for i,epv in enumerate(self.epverts):
            s = ','.join('%d' % self.epedges.index(epe) for epe in epv.epedges)
            print('    %d%c: %s' % (i,'.' if epv.is_inner() else '*',s))
        print('  %d EPEdges' % len(self.epedges))
        for i,epe in enumerate(self.epedges):
            i0 = self.epverts.index(epe.epvert0)
            i1 = self.epverts.index(epe.epvert1)
            i2 = self.epverts.index(epe.epvert2)
            i3 = self.epverts.index(epe.epvert3)
            print('    %d: %d--%d (%d,%d,%d,%d)' % (i, i0,i3, i0,i1,i2,i3))
        print('  %d EPPatches' % len(self.eppatches))
        for i,epp in enumerate(self.eppatches):
            s = ','.join('%d' % self.epedges.index(epe) for epe in epp.lepedges)
            print('    %d: %s' % (i,s))
    
    def get_loop(self, epedge, forward=True):
        if len(epedge.epvert0.epedges)==1 or len(epedge.epvert3.epedges)==1: return None
        epv = epedge.epvert3 if forward else epedge.epvert0
        loop = [epedge]
        lepv = [epv]
        minp,maxp = epv.snap_pos,epv.snap_pos
        while True:
            epe = epv.get_next_epedge(loop[-1])
            if epe is None:    return None
            if epe == loop[0]: break
            loop += [epe]
            epv = epe.get_opposite_epvert(epv)
            lepv += [epv]
            minp = min(minp, epv.snap_pos)
            maxp = max(maxp, epv.snap_pos)
        
        # make sure loop is anti-clockwise
        r = maxp - minp
        c = len(lepv)
        if r.x >= r.y and r.x >= r.z:
            ip1 = min(range(c), key=lambda i:lepv[i].snap_pos.x)
        elif r.y >= r.x and r.y >= r.z:
            ip1 = min(range(c), key=lambda i:lepv[i].snap_pos.y)
        else:
            ip1 = min(range(c), key=lambda i:lepv[i].snap_pos.z)
        
        epv0,epv1,epv2 = lepv[(ip1+c-1) % c], lepv[ip1], lepv[(ip1+1) % c]
        nl = (epv0.snap_pos - epv1.snap_pos).cross(epv2.snap_pos - epv1.snap_pos)
        if epv1.snap_norm.dot(nl) < 0: return None
        
        return loop
    
    def update_eppatches(self):
        for epv in self.epverts:
            epv.update_epedges()
        loops = set()
        for epe in self.epedges:
            l0 = self.get_loop(epe, forward=True)
            if l0: loops.add(tuple(rotate_items(l0)))
            l1 = self.get_loop(epe, forward=False)
            if l1: loops.add(tuple(rotate_items(l1)))
        self.eppatches = set()
        self.epedge_eppatch = dict()
        print('Created %d patches' % len(loops))
        for loop in loops:
            epp = EPPatch(loop)
            self.eppatches.add(epp)
            for epe in loop:
                if epe not in self.epedge_eppatch: self.epedge_eppatch[epe] = set()
                self.epedge_eppatch[epe].add(epp)
        
    
    def create_epvert(self, pos):
        epv = EPVert(pos)
        self.epverts.append(epv)
        return epv
    
    def create_epedge(self, epv0, epv1, epv2, epv3, tess = 20):
        epe = EPEdge(epv0, epv1, epv2, epv3, tess = tess)
        self.epedges.append(epe)
        return epe
    
    def disconnect_epedge(self, epedge):
        assert epedge in self.epedges
        epedge.disconnect()
        self.epverts.remove(epedge.epvert1)
        self.epverts.remove(epedge.epvert2)
        self.epedges.remove(epedge)
    
    def disconnect_epvert(self, epvert):
        assert epvert in self.epverts
        for epe in epvert.get_epedges():
            self.disconnect_epedge(epe)
        self.epverts.remove(epvert)
    
    def split_epedge_at_pt(self, epedge, pt, connect_epvert=None):
        t,_ = epedge.get_closest_point(pt)
        return self.split_epedge_at_t(epedge, t)
        
    
    def split_epedge_at_t(self, epedge, t, connect_epvert=None):
        p0,p1,p2,p3 = epedge.get_positions()
        cb0,cb1 = cubic_bezier_split(p0,p1,p2,p3, t, self.length_scale)
        
        if connect_epvert:
            epv_split = connect_epvert
            trans = cb0[3] - epv_split.position
            for epe in epv_split.get_epedges():
                epe.get_inner_epvert_at(epv_split).position += trans
            epv_split.position += trans
        else:
            epv_split = self.create_epvert(cb0[3])
        
        epv0_0 = epedge.epvert0
        epv0_1 = self.create_epvert(cb0[1])
        epv0_2 = self.create_epvert(cb0[2])
        epv0_3 = epv_split
        
        epv1_0 = epv_split
        epv1_1 = self.create_epvert(cb1[1])
        epv1_2 = self.create_epvert(cb1[2])
        epv1_3 = epedge.epvert3
        
        # want to *replace* epedge with new epedges
        lepv0epe = epv0_0.get_epedges()
        lepv3epe = epv1_3.get_epedges()
        
        self.disconnect_epedge(epedge)
        new_tess = math.ceil(epedge.tessellation_count/2)
        epe0 = self.create_epedge(epv0_0,epv0_1,epv0_2,epv0_3, tess = new_tess)
        epe1 = self.create_epedge(epv1_0,epv1_1,epv1_2,epv1_3, tess = new_tess)
        
        #lgv0ge = [ge0 if ge==epedge else ge for ge in lgv0ge]
        #lgv3ge = [ge1 if ge==epedge else ge for ge in lgv3ge]
        #gv0_0.epedge0,gv0_0.epedge1,gv0_0.epedge2,gv0_0.epedge3 = lgv0ge
        #gv1_3.epedge0,gv1_3.epedge1,gv1_3.epedge2,gv1_3.epedge3 = lgv3ge
        
        epv0_0.update()
        epv1_3.update()
        epv_split.update()
        epv_split.update_epedges()
        
        return (epe0,epe1,epv_split)
    
    def insert_epedge_between_epverts(self, epv0, epv3):
        epv1 = self.create_epvert(epv0.position*0.7 + epv3.position*0.3, radius=epv0.radius*0.7 + epv3.radius*0.3)
        epv2 = self.create_epvert(epv0.position*0.3 + epv3.position*0.7, radius=epv0.radius*0.3 + epv3.radius*0.7)
        return self.create_epedge(epv0,epv1,epv2,epv3)
    
    
    def insert_epedge_from_stroke(self, stroke, error_scale=0.01, maxdist=0.05, sepv0=None, sepv3=None, depth=0):
        pts = [p for p,_ in stroke]
        # check if stroke swings by any corner/end epverts
        #pr = profiler.start()
        
        start = time.time()
        for epv in self.epverts:
            if epv.isinner: continue
            i0,i1 = -1,-1
            for i,pt in enumerate(pts):
                dist = (pt-epv.snap_pos).length
                if i0==-1:
                    if dist > maxdist: continue
                    i0 = i
                else:
                    if dist < maxdist: continue
                    i1 = i
                    break
            if i0==-1: continue
            
            if i0==0:
                if i1!=-1:
                    if sepv0:
                        epv1 = self.create_epvert(sepv0.position * 0.75 + epv.position * 0.25)
                        epv2 = self.create_epvert(sepv0.position * 0.25 + epv.position * 0.75)
                        self.create_epedge(sepv0, epv1, epv2, epv)
                    self.insert_epedge_from_stroke(stroke[i1:], error_scale=error_scale, maxdist=maxdist, sepv0=epv, sepv3=sepv3, depth=depth+1)
                elif sepv0 and sepv3:
                    epv1 = self.create_epvert(sepv0.position * 0.75 + sepv3.position * 0.25)
                    epv2 = self.create_epvert(sepv0.position * 0.25 + sepv3.position * 0.75)
                    self.create_epedge(sepv0, epv1, epv2, sepv3)
            else:
                self.insert_epedge_from_stroke(stroke[:i0], error_scale=error_scale, maxdist=maxdist, sepv0=sepv0, sepv3=epv, depth=depth+1)
                if i1!=-1:
                    self.insert_epedge_from_stroke(stroke[i1:], error_scale=error_scale, maxdist=maxdist, sepv0=epv, sepv3=sepv3, depth=depth+1)
            
            return
        #pr.done()
        
        # check if stroke crosses any epedges
        #pr = profiler.start()
        for epe in self.epedges:
            c = len(epe.curve_verts)
            cp_first = epe.curve_verts[0]
            cp_last = epe.curve_verts[-1]
            for p0,p1 in zip(pts[:-1],pts[1:]):
                for i0 in range(c-1):
                    cp0,z = epe.curve_verts[i0],epe.curve_norms[i0]
                    cp1 = epe.curve_verts[i0+1]
                    #if (cp0-cp_first).length < maxdist: continue
                    #if (cp1-cp_last).length < maxdist: continue
                    if (cp0-p0).length > maxdist: continue
                    x = (cp1-cp0).normalized()
                    y = z.cross(x).normalized()
                    a = (p0-cp0).dot(y)
                    b = (p1-cp0).dot(y)
                    if a*b >= 0: continue                           # p0-p1 segment does not cross cp0,cp1 line
                    v = (p1-p0).normalized()
                    d = p0 + v * abs(a) / v.dot(y)                  # d is crossing position
                    if (cp0-d).length > (cp1-cp0).length: continue  # p0-p1 segment does not cross cp0,cp1 segment
                    
                    _,_,epv = self.split_epedge_at_pt(epe, d)
                    self.insert_epedge_from_stroke(stroke, error_scale=error_scale, maxdist=maxdist, sepv0=sepv0, sepv3=sepv3, depth=depth+1)
                    #pr.done()
                    return
        #pr.done()
        
        if len(pts) < 6:
            if not sepv0 or not sepv3: return
            epv1 = self.create_epvert(sepv0.position * 0.75 + sepv3.position * 0.25)
            epv2 = self.create_epvert(sepv0.position * 0.25 + sepv3.position * 0.75)
            self.create_epedge(sepv0, epv1, epv2, sepv3)
            return
        
        #pr = profiler.start()
        start = time.time()
        lbez = cubic_bezier_fit_points(pts, error_scale)
        finish = time.time()
        print('Took %f seconds to fit bezier to the  new stroke' % (finish - start))
            
        #pr.done()
        
        #pr = profiler.start()
        epv0 = None
        for t0,t3,p0,p1,p2,p3 in lbez:
            if epv0 is None:
                epv0 = sepv0 if sepv0 else self.create_epvert(p0)
            else:
                epv0 = sepv3
            epv1 = self.create_epvert(p1)
            epv2 = self.create_epvert(p2)
            epv3 = self.create_epvert(p3)
            epe = self.create_epedge(epv0, epv1, epv2, epv3)
        if sepv3:
            epe.replace_epvert(epv3, sepv3)
            self.remove_unconnected_epverts()
        #pr.done()
    
    
    
    def merge_epverts(self, epvert0, epvert1):
        ''' merge epvert0 into epvert1 '''
        l_epe = list(epvert0.epedges)
        for epe in l_epe:
            epe.replace_epvert(epvert0, epvert1)
        self.epverts = [epv for epv in self.epverts if epv != epvert0]
        epvert1.update_epedges()
        return epvert1
    
    def pick_epverts(self, pt, maxdist=0.1, sort=True, allowInner=True):
        lepv = []
        for epv in self.epverts:
            if not allowInner and epv.isinner: continue
            d = (epv.snap_pos-pt).length
            if d <= maxdist: lepv += [(epv,d)]
        if not sort: return lepv
        return sorted(lepv, key=lambda v: v[1])
    
    def pick_epedges(self, pt, maxdist=0.1, sort=True):
        lepe = []
        for epe in self.epedges:
            d = epe.min_dist_to_point(pt)
            if d <= maxdist: lepe += [(epe,d)]
        if not sort: return lepe
        return sorted(lepe, key=lambda v: v[1])
    
    def pick_eppatches(self, context,x,y, pt, maxdist=0.1, sort=True):
        lepp = []
        for epp in self.eppatches:
            if epp.hovered_2d(context,x,y):
                d = (epp.info_display_pt() - pt).length
                lepp += [(epp,d)]
        if not sort: return lepp
        return sorted(lepp, key=lambda v: v[1]) 
    
       
    def pick(self, pt, maxdist=0.1,sort=True):
        l = self.pick_epverts(pt,maxdist=maxdist,sort=False) + self.pick_epedges(pt,maxdist=maxdist,sort=False)
        if not sort: return l
        return sorted(l, key=lambda v:v[1])

    def remove_unconnected_epverts(self):
        self.epverts = [epv for epv in self.epverts if not epv.is_unconnected()]

    def dissolve_epvert(self, epvert, tessellation=20):
        assert not epvert.isinner, 'Attempting to dissolve an inner EPVert'
        assert len(epvert.epedges) == 2, 'Attempting to dissolve an EPVert that does not have exactly 2 connected EPEdges'
        
        epedge0,epedge1 = epvert.epedges
        
        p00,p01,p02,p03 = epedge0.get_positions()
        p10,p11,p12,p13 = epedge1.get_positions()
        
        pts0 = [cubic_bezier_blend_t(p00,p01,p02,p03,i/tessellation) for i in range(tessellation+1)]
        pts1 = [cubic_bezier_blend_t(p10,p11,p12,p13,i/tessellation) for i in range(tessellation+1)]
        if epedge0.epvert0 == epvert: pts0.reverse()
        if epedge1.epvert3 == epvert: pts1.reverse()
        pts = pts0 + pts1
        
        t0,t3,p0,p1,p2,p3 = cubic_bezier_fit_points(pts, self.length_scale, allow_split=False)[0]
        
        epv0 = epedge0.epvert3 if epedge0.epvert0 == epvert else epedge0.epvert0
        epv1 = self.create_epvert(p1)
        epv2 = self.create_epvert(p2)
        epv3 = epedge1.epvert3 if epedge1.epvert0 == epvert else epedge1.epvert0
        
        self.disconnect_epedge(epedge0)
        self.disconnect_epedge(epedge1)
        self.create_epedge(epv0,epv1,epv2,epv3)
        epv0.update()
        epv0.update_epedges()
        epv3.update()
        epv3.update_epedges()
    
    def subdivide_eppatch(self, eppatch, epedge0, epedg1, t):
        pass
    
    
    def create_mesh(self, bme):
        mx = bpy.data.objects[EdgePatches.src_name].matrix_world
        imx = mx.inverted()
        
        verts = []
        edges = []
        ngons = []
        d_epv_v = {}
        d_epe_e = {}
        d_epp_n = {}
        
        def insert_vert(p):
            verts.append(imx*p)
            return len(verts)-1
        def insert_epvert(epv):
            if epv not in d_epv_v: d_epv_v[epv] = insert_vert(epv.snap_pos)
            return d_epv_v[epv]
        
        def insert_edge(ip0,ip1):
            edges.append((ip0,ip1))
            return len(edges)-1
        def insert_epedge(epe):
            if epe not in d_epe_e: d_epe_e[epe] = insert_edge(insert_epvert(epe.epvert0), insert_epvert(epe.epvert3))
            return d_epe_e[epe]
        
        def insert_ngon(lip):
            ngons.append(tuple(reversed(tuple(lip))))
            return len(ngons)-1
        def insert_eppatch(epp):
            if epp not in d_epp_n:
                d_epp_n[epp] = insert_ngon(insert_epvert(epv) for epv in epp.get_epverts())
            return d_epp_n[epp]
        
        for epv in self.epverts:
            if not epv.isinner: insert_epvert(epv)
        for epe in self.epedges:
            insert_epedge(epe)
        for epp in self.eppatches:
            insert_eppatch(epp)
        
        return (verts,edges,ngons)





