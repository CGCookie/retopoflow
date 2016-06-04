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

from mathutils import Vector, Quaternion, kdtree
from mathutils.geometry import intersect_point_line, intersect_line_plane
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d

from ..lib import common_utilities
from ..lib.common_utilities import iter_running_sum, dprint, get_object_length_scale,frange
from ..lib.common_utilities import zip_pairs, closest_t_of_s, closest_t_and_distance_point_to_line_segment
from ..lib.common_utilities import sort_objects_by_angles, delta_angles, vector_angle_between, rotate_items, point_inside_loop2d
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

        self.from_bmesh = False
        self.bmesh_ind = -1  
        
    def snap(self):
        p,n,_ = EdgePatches.getClosestPoint(self.position, meth = 'BVH')
        self.snap_pos  = p
        self.snap_norm = n
    
    def update(self, do_edges=True, do_faces = True):
        if self.doing_update: return
        
        #pr = profiler.start()
        self.snap()
        if do_edges:
            self.doing_update = True
            self.update_epedges()
            self.doing_update = False
        
        if do_faces:
            self.doing_update = True
            self.update_eppatches()
            self.doing_update = False
            
        if self.is_inner():
            self.doing_update = True
            for epe in self.epedges:
                for epp in epe.eppatches:
                    print('generating geometry for adjacent patches by edge')
                    epp.generate_geometry()
            
            self.doing_update = False
        #pr.done()
    
    def update_epedges(self):
        if len(self.epedges)>2:
            ''' sort the epedges about normal '''
            l_vecs = [epe.get_outer_vector_at(self) for epe in self.epedges]
            self.epedges = sort_objects_by_angles(-self.snap_norm, self.epedges, l_vecs)  # positive snap_norm to sort clockwise
        for epe in self.epedges:
            
            if self.is_inner():
                print('updating edge for an inner vert!!')
            else:
                print('updating edge for outer vert')
            epe.update(shape = True, subdiv = True, patches = False)
    
    def update_eppatches(self):
        if len(self.eppatches)>2:
            ''' sort the eppatches about normal '''
            l_vecs = [epp.info_display_pt()-self.snap_pos for epp in self.eppatches]
            self.eppatces = sort_objects_by_angles(-self.snap_norm, self.eppatches, l_vecs)  # positive snap_norm to sort clockwise
        for epp in self.eppatches:
            print('updating patch around EPVert')
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
    def __init__(self, epvert0, epvert1, epvert2, epvert3, tess = 20, rad = None, subdiv = None, from_bme = False):
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
        
        self.from_bmesh = from_bme
        self.edge_bmverts = [] #these are for interfacing with existing and new bmesh
        
        #these are set depending on what variables are passed
        self.quad_size = None
        self.subdivision = None
        
        if rad:
            self.quad_size = rad
            self.set_quad_size()
            
        elif subdiv and not rad:
            self.subdivision = subdiv
            self.get_quad_size()
        else:
            self.subdivision = 6
            self.get_quad_size()
        
        
        epvert0.connect_epedge(self)
        epvert1.connect_epedge_inner(self)
        epvert2.connect_epedge_inner(self)
        epvert3.connect_epedge(self)
        
        if tess > 5:
            self.tessellation_count = tess
        self.update(shape = True, subdiv = True, patches = False)
    
    def epverts(self): return (self.epvert0, self.epvert1, self.epvert2, self.epvert3)
    def epverts_pos(self): return (self.epvert0.snap_pos, self.epvert1.snap_pos, self.epvert2.snap_pos, self.epvert3.snap_pos)
    
    def info_display_pt(self):
        if len(self.curve_verts) == 0: return Vector((0,0,0))
        elif len(self.curve_verts) == 1: return self.curve_verts[0]
       
        mid = math.ceil((len(self.curve_verts)-1)/2)
        
        
        if not len(self.curve_norms):
            self.update_shape()
            return self.curve_verts[mid]
        
        if len(self.curve_verts) % 2 == 0:
            pt = .5 * self.curve_verts[mid] + .5 * self.curve_verts[mid-1]
        else:
            pt = self.curve_verts[mid]
            
        no = self.curve_norms[mid]
        dir_off = no.cross(self.curve_verts[mid+1]-self.curve_verts[mid])
        dir_off.normalize()
        len_off = .1 * (self.curve_verts[-1] - self.curve_verts[0]).length
        
        info_pt = pt + len_off*dir_off
        return info_pt
    
    def update_subdiv(self):
        if self.from_bmesh:
            self.subdivision = len(self.edge_verts) - 1
            return
        getClosestPoint = EdgePatches.getClosestPoint
        p0,p1,p2,p3 = self.get_positions()
        e_v_pos = [cubic_bezier_blend_t(p0,p1,p2,p3,i/float(self.subdivision)) for i in range(self.subdivision+1)]
        
        self.edge_verts = []  #comment me out for cool looking stuff
        self.edge_vert_norms = []
        
        for pos in e_v_pos:
            p,n,i = getClosestPoint(pos, meth = 'BVH')
            self.edge_verts.append(p)
            self.edge_vert_norms.append(n)
            
    
    def update_shape(self):
        getClosestPoint = EdgePatches.getClosestPoint
        if self.from_bmesh:
            self.curve_norms = []
            self.edge_vert_norms = [] 
            for pos in self.curve_verts:
                p,n,i = getClosestPoint(pos, meth = 'BVH')
                self.edge_vert_norms.append(n)
                self.curve_norms.append(n)     
            return
        
        tessellation_count = EPEdge.tessellation_count
        p0,p1,p2,p3 = self.get_positions()
        lpos = [cubic_bezier_blend_t(p0,p1,p2,p3,i/float(tessellation_count)) for i in range(tessellation_count+1)]
        
        self.curve_verts = []
        self.curve_norms = []
        
        for pos in lpos:
            #pr3 = profiler.start()
            p,n,i = getClosestPoint(pos, meth = 'BVH')
            self.curve_verts.append(p)
            self.curve_norms.append(n)        
    
    def update(self, shape = True, subdiv = True, patches = True):
        '''
        shape:  This will re-interpolate the bezier and create a vert chain
        subdivision:  only use if number of segments has been changes (eg, wheel up mouse)
        patches:  if subdivision is changed, the patch solution by definition must change.
        '''
        print(len(self.eppatches))
        if shape:
            self.update_shape()
            
            #this now hapens at the inner gvert level because of duplicate updating
            #for epp in self.eppatches:
            #    print('generating geometry for adjacent patches by edge')
            #    epp.generate_geometry()
            
        if subdiv:
            self.update_subdiv()  
    
        elif patches and subdiv:
            for epp in self.eppatches:
                epp.ILP_intitial_solve()
                epp.generate_geometry()        
        
    def set_quad_size(self):
        '''
        sets the subdivision to a target quad size
        '''
        if len(self.curve_verts) == 0:
            self.update(shape=True, subdiv=False, patches=False)
        L = common_utilities.get_path_length(self.curve_verts)
        #print('The path length is %f' % L)
        #print('The quad size is %f' % self.quad_size)
        
        n = math.floor(L/self.quad_size)
        #print('meaning subdivisions are %d' % n)
        
        self.subdivision = max(n,2)
        self.update(shape = False, subdiv = True, patches = False)
        self.quad_size = self.get_quad_size()
        #print('Now the quad size is %f' % self.quad_size)
        
    def get_quad_size(self):
        L = common_utilities.get_path_length(self.curve_verts)
        n = self.subdivision
        quad_size = L/n
        return quad_size
                
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
        for epe in self.lepedges:
            epe.eppatches += [self]
        
        self.center = Vector()
        self.normal = Vector()

        self.L_sub_raw = [ep.subdivision for ep in self.lepedges] #this may be problem.  self.lepedges not in same order as get_edge loops
        
        
        self.t_override = dict()  #use to overide only changed through UI
        self.t_junctions = set()  #updated every time patch is updated
        
        self.concave = set()
        
        self.check_ts()
        self.L_sub_eff = [len(ed_l)-1 for ed_l in self.get_edge_loops()]
        
        
        self.patch_solution = []
        self.verts = []
        self.faces = []
        
        self.bmesh = bmesh.new()
        self.patch = None
        self.live = True
        
        self.update()
    
    def detach(self):
        for epv in self.get_epverts():
            epv.remove(self)
        for epe in self.lepedges:
            epe.eppatches.remove(self)
            
            
    def check_ts(self):
        #print('CHECKING T JUNCTIONS AND CONCAVIIES')
        self.t_junctions.clear()
        self.concave.clear()
        
        for i, (epe,fwd) in enumerate(zip(self.lepedges,self.epedge_fwd)):

            epe_prev = self.lepedges[i-1]
            
            epv_prev = epe_prev.epvert2 if self.epedge_fwd[i-1] else epe_prev.epvert1
            epv_now = epe.epvert0 if fwd else epe.epvert3
            epv_next = epe.epvert1 if fwd else epe.epvert2
        
            if epv_now in self.t_override:
                if self.t_override[epv_now]:
                    print('found override t')
                    self.t_junctions.add(epv_now)
                    
                continue
            
            v0 = epv_prev.position - epv_now.position
            v1 = epv_next.position - epv_now.position
            vec_about = -epv_now.snap_norm  
            inner_angle = vector_angle_between(v0,v1,vec_about)
            raw_angle = v0.angle(v1)
            
            v0.normalize()
            v1.normalize()
            
            parallel = -v0.dot(v1)
            
            #print('inner angle at this gvert is %f' % (180*inner_angle/math.pi))  
            #print('the raw angle at this gvert is %f'% raw_angle)
            #print('the dot product is %f' % parallel)     
            #if abs(inner_angle) > .8 * math.pi and abs(inner_angle) < 5/4* math.pi:
            if parallel > .68:
                print('adding to T junctions')#:  %f' % (180*inner_angle/math.pi))
                self.t_junctions.add(epv_now)
            #elif abs(inner_angle) >=  5/4* math.pi:
                #print('adding to  Concave Junctions')#, angle is:  %f' % (180*inner_angle/math.pi))
                #self.concave.add(epv_now)   
        if all([epv in self.t_junctions for epv in self.get_epverts()]):
            print('all verts t_junctions, need to override some')   
    
        print(len(self.t_junctions))
          
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
            p,n,_ = EdgePatches.getClosestPoint(ctr/float(cnt), meth = 'BVH')
            self.center =  p
            self.normal =  n
        else:
            self.center = Vector()
            self.normal = Vector()
        
        
        self.L_sub_raw = [epe.subdivision for epe in self.lepedges]
        self.check_ts()
        new_lsub = [len(ed_l)-1 for ed_l in self.get_edge_loops()]
        if self.L_sub_eff != new_lsub:
            self.ILP_initial_solve()
        
        if self.patch and self.patch.active_solution_index != -1 and self.live:
            self.generate_geometry()
        else:
            self.faces, self.verts = [], []
                        
    def get_outer_points(self):  #TODO, check where this is used
        def get_verts(epe,fwd):
            if fwd: return epe.curve_verts
            return reversed(epe.curve_verts)
        return [p for epe,fwd in zip(self.lepedges,self.epedge_fwd) for p in get_verts(epe,fwd)]
    
    def get_epverts(self):  #T-Junction agnostic
        return [epe.epvert0 if fwd else epe.epvert3 for epe,fwd in zip(self.lepedges,self.epedge_fwd)]

    def get_edge_loops(self):  #TODO update for T-junctions, DONE (not tested)
        
        def get_verts(epe,fwd):
            if fwd: return epe.edge_verts.copy()
            ed_verts = epe.edge_verts.copy()
            ed_verts.reverse()
            return ed_verts
        
        loops = [[]]
        for i, (epe,fwd) in enumerate(zip(self.lepedges,self.epedge_fwd)):

            
            epv_now = epe.epvert0 if fwd else epe.epvert3
            epv_next = epe.epvert3 if fwd else epe.epvert0
            vs = get_verts(epe, fwd)
            
            if epv_now in self.t_junctions:
                if i == 0:
                    #initialize an empty element
                    loops = [[]]
                    

                loops[-1] += vs[1:]

            elif i == 0:

                loops = [vs]
            else:

                loops += [vs]
                
            
            if i == len(self.lepedges) - 1 and epv_next in self.t_junctions:
                    
                loops[0] = loops[-1] + loops[0]
                loops.pop()
        
        print([len(lp)-1 for lp in loops])
        return loops
    
    def get_bme_vert_loop(self): #TODO update for T-junctions, DONE, agnostic of T-junctinos
        def get_verts(epe,fwd):
            if fwd: return epe.edge_bmverts[0:len(epe.edge_bmverts)-1]
            ed_bmverts = epe.edge_bmverts.copy()
            ed_bmverts.reverse()
            return ed_bmverts[0:len(ed_bmverts)-1]
        return list(itertools.chain(*[get_verts(epe,fwd) for epe,fwd in zip(self.lepedges,self.epedge_fwd)]))
        
    def get_corner_locations(self):#TODO update for T-junctions, DONE
        epvs = self.get_epverts()
        return [epv.snap_pos for epv in epvs if epv not in self.t_junctions]
    
    def info_display_pt(self):
        pts = self.get_epverts()
        center = Vector((0,0,0))
        for pt in pts:
            center += 1/len(pts) * pt.snap_pos
        return center
    
    def validate_patch_for_ILP(self): #TODO: Update for T-Junctions: DONE
        '''
        just check that the perimter is even
        '''
        raw_subdiv = [epe.subdivision for epe in self.lepedges]
        perim_sum = sum(raw_subdiv)
        N = len(raw_subdiv) - len(self.t_junctions)
        if perim_sum % 2: return False
        if N < 2: return False
        if N > 6: return False
        
        return True
    
    def hovered_2d(self,context,mouse_x,mouse_y):
        reg = context.region
        rv3d = context.space_data.region_3d
        #if len(self.lepedges) == 2: #expensive, test all the verts
        
        loop = self.get_outer_points()
        #else: #Cheap, test the corners
        #    loop = [epv.snap_pos for epv in self.get_epverts()]
        loop_2d = [location_3d_to_region_2d(reg, rv3d, pt) for pt in loop if pt]
        
        return point_inside_loop2d(loop_2d, (mouse_x, mouse_y))

    def ILP_initial_solve(self):
        if not self.validate_patch_for_ILP(): return
        self.patch = Patch()  #new patch starts off as not all solved
        
        #TODO, check for T-Junctions!
        self.check_ts()
        self.L_sub_eff = [len(loop) - 1 for loop in self.get_edge_loops()]
        self.patch.edge_subdivision = self.L_sub_eff
        print('Effective subdivision is ' + str(self.L_sub_eff))
        print('Raw subdivision is ' + str(self.L_sub_raw))
        self.patch.permute_and_find_first_solution()
        #sleep occasionally needed
        L, rot_dir, pat, sol = self.patch.get_active_solution()
        print(sol)
        return
      
    def generate_geometry(self):
        '''
        this creates/refreshes a bmesh which exists
        in world coords
        '''
        
        self.bmesh.free()
        
        if self.patch == None: return
        
        
        L, (n, fwd), pat, sol = self.patch.get_active_solution()
        
        if sol == None:
            print('no solution yet')
            self.verts, self.faces, self.gdict = [], [], {}
            return
        c_vs = self.get_corner_locations() #TODO T-Junctions
        N = len(c_vs)
        ed_loops = self.get_edge_loops()  #TODO T-Junctions
        
        #print('%i Sided Patch' % N)
        #print('Solved by pattern # %i' % pat)
        #print('%i side is now the 0 side' % n)
        #print('%i direction around path' % fwd)
        
        #print('Subdivisions by active solution')
        #print(L)
        
        #print('Subdivision by self.L_sub_effective (lepedges)')
        #print(self.L_sub_eff)
        
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

        elif N == 2:
            ps = vars[:2]
            if pat == 0:
                patch_fn = bi_prim_0
            elif pat == 1:
                patch_fn = bi_prim_1
            
        #All information collected, now generate the patch
        
        #First, slice off the padding from each side
        if N == 2:
            geom_dict = patch_fn(vs, ps, *vars[N:])
            self.verts, self.faces, self.gdict = geom_dict['verts'], geom_dict['faces'], geom_dict
            self.gdict['patch perimeter verts'] = geom_dict['perimeter verts']
            self.bmesh = geom_dict['bme']
            
            return
        
            
        pad_geom_dict = pad_patch_sides_method(vs, ps, L, pat)
        if not pad_geom_dict:
            print('padding failure!!')
            self.verts, self.faces, self.gdict = [], [], {}
            return
            
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
        return
            
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
        self.bmv_epv_map = dict()
        
        self.update_schedule = []
        self.update_complete = False
        self.live = False
        
        
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
            result,c,n,i = obj.closest_point_on_mesh(imx * p)
            
        else:
            bvh = mesh_cache['bvh']
            c,n,i,d = bvh.find_nearest(imx*p)
        
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
        if epv1.snap_norm.dot(nl) < 0: 
            print('snap_norm problem')
            return None
        
        return loop
    
    def clear_patches(self):
        
        for epp in self.eppatches:
            epp.verts = []
            epp.faces = []
            epp.live = False
    
    
    def create_epv_from_bmvert(self,bmvert):
        
        mx = bpy.data.objects[self.tar_name].matrix_world
        epv = self.create_epvert(mx * bmvert.co)
        epv.from_bmesh = True
        epv.bmesh_ind = bmvert.index  #keepa reference to it
        self.bmv_epv_map[bmvert.index] = epv
        
        return epv
        
        
    def extension_geometry_from_bme(self, bme):
        
        bme.faces.ensure_lookup_table()
        bme.edges.ensure_lookup_table()
        bme.verts.ensure_lookup_table()
        
        
        mx = bpy.data.objects[self.tar_name].matrix_world
        #first, check for selected verts that are part of non man edges
        #sel_bmverts = [v for v in bme.verts if v.select and any([not e.is_manifold for e in v.link_edges])]
        sel_vert_corners = [v for v in bme.verts if v.select]
        v_loops = find_edge_loops(bme, sel_vert_corners, select = False)    
    
    
        
        real_corners = set()
        for vloop in v_loops:
            pts, inds, corners = vloop
            print(inds)
            real_corners.update(corners)
        
        #add an EPVert for all the corners
        corner_bmvs = list(real_corners) 
        corner_epvs = {}  
        for v_ind in corner_bmvs:
            v = bme.verts[v_ind]
            epv = self.create_epv_from_bmvert(v)
            
            
        for vloop in v_loops:
            pt_chains, ind_chains, corners = vloop
            for pts, inds in zip(pt_chains, ind_chains):
                if len(inds) < 2: continue
                pts_wrld = [mx * v for v in pts]
                epv0 = self.bmv_epv_map[inds[0]]
                epv1 = self.create_epvert(.75*pts_wrld[0] + .25*pts_wrld[-1])
                epv2 = self.create_epvert(.25*pts_wrld[0] + .75*pts_wrld[-1])
                epv3 = self.bmv_epv_map[inds[-1]]
                
                rad = (pts_wrld[1]-pts_wrld[0]).length
                epe = self.create_epedge(epv0, epv1, epv2, epv3, rad = rad, from_bme = True)
                epe.edge_verts = pts_wrld
                epe.curve_verts = pts_wrld
                epe.edge_bmverts = inds
                epe.subdivision = len(pts_wrld) - 1
                epe.quad_size = epe.get_quad_size()
                epe.from_bmesh = True
            
    
    
    
    def smart_update_eppatches_network(self):
        '''
        when new epverts or new epedges have been inserted
        when any epv, epe or epp have been deleted
        '''
        
        if not self.live: 
            self.clear_patches() #simply turns off geometry
            return
        
        for epe in self.epedges:
            epe.update(shape = True, subdiv = True, patches = False)
            
        epp_update = set() #new and modified patches,need new solutions and new geom
        epp_remove = set() #sliced or diced patches, or epe deleted
        epp_geom = set()
        
        #walk around all the loops, perhaps this can even get more clever 
        loops = set()
        for epe in self.epedges:
            l0 = self.get_loop(epe, forward=True)
            if l0: loops.add(tuple(rotate_items(l0)))
            l1 = self.get_loop(epe, forward=False)
            if l1: loops.add(tuple(rotate_items(l1)))
        
        print('Found  %d loops' % len(loops)) 
        
        
        #compare found loops to existing loops, 
        for epp in self.eppatches:
             
            loop = tuple(epp.lepedges)
            if loop not in loops:
                epp_remove.add(epp)
                for epe in epp.lepedges:
                    if epe in self.epedge_eppatch:
                        if epp in self.epedge_eppatch[epe]:
                            self.epedge_eppatch[epe].remove(epp)
                continue
            
            l_sub = [epe.subdivision for epe in epp.lepedges]
            if l_sub != epp.L_sub_raw:  #TODO, this will reflect T junctions, but we need to find better marker for unchanged patches
                print('update this patch')
                print(l_sub, epp.L_sub_raw)
                print(l_sub, epp.L_sub_eff)
                epp_update.add(epp)
                loops.remove(loop) #no longer needed to make new one, just update subdiv
        
            elif l_sub == epp.L_sub_raw:
                print('keep this patch the same')
                loops.remove(loop) #no need to update or make new
                if epp.live == False:
                    epp.live = True
                    epp_geom.add(epp)
                
        print('removing %d no longer existing patches' % len(epp_remove))
        for epp in epp_remove:
            epp.detach()
            self.eppatches.remove(epp)
            
            
        print('Created %d new patches' % len(loops))        
        for loop in loops:
            if len(loop) < 2 or len(loop) > 10: continue
            elif all([epe.from_bmesh for epe in loop]): continue  #for now, don't repatch loops
            epp = EPPatch(loop)
            self.eppatches.add(epp)
            epp_update.add(epp)
            for epe in loop:
                if epe not in self.epedge_eppatch: self.epedge_eppatch[epe] = set()
                self.epedge_eppatch[epe].add(epp)
        
        print('Updated %d existing patches' % len(epp_update))  
        for epp in epp_update:
            epp.update()
            #epp.ILP_initial_solve()
            #epp.generate_geometry()
            
        if len(epp_update) or len(loops):
            print('patches need updating')
            self.update_complete = False
        
        print('turning geom back on for some')
        for epp in epp_geom:
            epp.generate_geometry()
                               
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
        
    
    def solve_next(self):
        if self.update_complete: return
        
        
        for epp in self.eppatches:
            if epp.patch == None: continue
            if not epp.patch.all_solved and epp.patch.any_solved:
                epp.patch.find_next_solution()
                break
        totally_solved = [epp.patch.all_solved for epp in self.eppatches if epp.patch]
        if all(totally_solved):
            print('network totally solved!')
            self.update_complete = True
            return        
        return
        
    def create_epvert(self, pos):
        epv = EPVert(pos)
        self.epverts.append(epv)
        return epv
    
    def create_epedge(self, epv0, epv1, epv2, epv3, rad = None, tess = 20, from_bme = False):
        epe = EPEdge(epv0, epv1, epv2, epv3, tess = tess, rad = rad, from_bme = from_bme)
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
    
    def split_bme_epedge_at_pt(self, epedge, pt, connect_epvert = None):
        
        if len(epedge.edge_bmverts) == 0:
            print('No edge bmverts')
            return
        
        def dist_fn(v):
            d = (v-pt).length
            return d
        
        best_pt = min(epedge.curve_verts, key = dist_fn)
        
        ind = epedge.curve_verts.index(best_pt)
        bmv_ind = epedge.edge_bmverts[ind]
        
        if ind == 0 or ind == len(epedge.curve_verts) -1:  return
        
        epv_split = self.create_epvert(best_pt)
        #map them to each other
        epv_split.bmvert = bmv_ind
        self.bmv_epv_map[bmv_ind] = epv_split
        
        epv0_0 = epedge.epvert0
        epv0_1 = self.create_epvert(epv0_0.position * 0.75 + epv_split.position * 0.25)
        epv0_2 = self.create_epvert(epv0_0.position * 0.25 + epv_split.position * 0.75)
        epv0_3 = epv_split
        
        epv1_0 = epv_split
        epv1_3 = epedge.epvert3
        epv1_1 = self.create_epvert(epv1_3.position * 0.25 + epv_split.position * 0.75)
        epv1_2 = self.create_epvert(epv1_3.position * 0.75 + epv_split.position * 0.25)
        
        bmvs = epedge.edge_bmverts
        crv_vs = epedge.curve_verts
        crv_ns = epedge.curve_norms
        ed_vs = epedge.edge_verts
        ed_ns = epedge.edge_vert_norms
        
        # want to *replace* epedge with new epedges
        lepv0epe = epv0_0.get_epedges()
        lepv3epe = epv1_3.get_epedges()
        self.disconnect_epedge(epedge)
        epe0 = self.create_epedge(epv0_0,epv0_1,epv0_2,epv0_3,rad = epedge.quad_size)
        epe0.edge_bmverts = bmvs[:ind+1]
        epe0.curve_verts = crv_vs[:ind+1]
        epe0.curve_norms = crv_ns[:ind+1]
        epe0.edge_verts = ed_vs[:ind+1]
        epe0.edge_vert_norms = ed_ns[:ind+1]
        epe0.from_bmesh = True
        
        
        
        epe1 = self.create_epedge(epv1_0,epv1_1,epv1_2,epv1_3,rad = epedge.quad_size)
        epe1.edge_bmverts = bmvs[ind:]
        epe1.curve_verts = crv_vs[ind:]
        epe1.curve_norms = crv_ns[ind:]
        epe1.edge_verts = ed_vs[ind:]
        epe1.edge_vert_norms = ed_ns[ind:]
        epe1.from_bmesh = True
        
        
        
        #lgv0ge = [ge0 if ge==epedge else ge for ge in lgv0ge]
        #lgv3ge = [ge1 if ge==epedge else ge for ge in lgv3ge]
        #gv0_0.epedge0,gv0_0.epedge1,gv0_0.epedge2,gv0_0.epedge3 = lgv0ge
        #gv1_3.epedge0,gv1_3.epedge1,gv1_3.epedge2,gv1_3.epedge3 = lgv3ge
        epv0_0.update()
        epv1_3.update()
        epv_split.update()
        epv_split.update_epedges()
        return (epe0,epe1,epv_split)

    def toggle_t(self, eppatch, pt, brush_width):
        
        def dist_fn(epv):
            d = (epv.snap_pos-pt).length
            return d
        
        best_epv = min(eppatch.get_epverts(), key = dist_fn)
        
        if dist_fn(best_epv) < brush_width:

            if best_epv in eppatch.t_override:
                eppatch.t_override[best_epv] = eppatch.t_override[best_epv] == False
                if best_epv in eppatch.t_junctions:
                    eppatch.t_junctions.remove(best_epv)
                else:
                    eppatch.t_junctions.add(best_epv)   
            else:
                if best_epv in eppatch.t_junctions:
                    eppatch.t_junctions.remove(best_epv)
                    eppatch.t_override[best_epv] = False
                else:
                    eppatch.t_override[best_epv] = True
                    eppatch.t_junctions.add(best_epv)
            
            eppatch.update()
        return ''
    
        
    def split_epedge_at_pt(self, epedge, pt, connect_epvert=None):
        
        if epedge.from_bmesh:
            return self.split_bme_epedge_at_pt(epedge, pt, connect_epvert=connect_epvert)
       
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

        epe0 = self.create_epedge(epv0_0,epv0_1,epv0_2,epv0_3,rad = epedge.quad_size)
        epe1 = self.create_epedge(epv1_0,epv1_1,epv1_2,epv1_3,rad = epedge.quad_size)
        
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
        
        rad = None
        if len(epv0.get_epedges()):
            rad = sum([epe.quad_zize for epe in epv0.get_epedges()])/len(epv0.get_epedges())
        elif len(epv0.get_epedges()):
            rad = sum([epe.quad_zize for epe in epv1.get_epedges()])/len(epv1.get_epedges())
        
        return self.create_epedge(epv0,epv1,epv2,epv3, rad= rad) #default to 6 subdivs
    
    
    def insert_epedge_from_stroke(self, stroke, error_scale=0.01, maxdist=0.05, sepv0=None, sepv3=None, depth=0):
        pts = [p for p,_ in stroke]
        radius = 2*stroke[0][1] #screw the pressure stuff for now
        
        #print('the radius is %f' % radius)
        
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
                        self.create_epedge(sepv0, epv1, epv2, epv,rad = radius)
                    self.insert_epedge_from_stroke(stroke[i1:], error_scale=error_scale, maxdist=maxdist, sepv0=epv, sepv3=sepv3, depth=depth+1)
                elif sepv0 and sepv3:
                    epv1 = self.create_epvert(sepv0.position * 0.75 + sepv3.position * 0.25)
                    epv2 = self.create_epvert(sepv0.position * 0.25 + sepv3.position * 0.75)
                    self.create_epedge(sepv0, epv1, epv2, sepv3, rad = radius)
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
            self.create_epedge(sepv0, epv1, epv2, sepv3, rad = radius)
            return
        
        #pr = profiler.start()
        start = time.time()
        lbez = cubic_bezier_fit_points(pts, error_scale)
        finish = time.time()
        #print('Took %f seconds to fit bezier to the  new stroke' % (finish - start))
            
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
            epe = self.create_epedge(epv0, epv1, epv2, epv3, rad = radius)
        if sepv3:
            epe.replace_epvert(epv3, sepv3)
            self.remove_unconnected_epverts()
        #pr.done()
    
    def insert_epedge_from_stroke_kd(self, stroke, only_ends=False, error_scale=0.01, maxdist=0.05, sepv0=None, sepv3=None, depth=0):
        if not len(stroke):
            print('nothing to work with')
            return
        
        r0,r3 = stroke[0][1],stroke[-1][1]
        threshold_tooshort     = (r0+r3)/2

        #todo, what does this mean
        assert depth < 10
        spc = '  '*depth + '- '
        
        #did we actually do anything?
        if len(stroke) <= 1:
            #print(spc+'Too few samples in stroke to subsample')
            return

        #print('our stroke started with %i points' % len(stroke))
        # uniform subsampling
        while len(stroke) <= 40:
            stroke = [stroke[0]] + [nptpr for ptpr0,ptpr1 in zip(stroke[:-1],stroke[1:]) for nptpr in [((ptpr0[0]+ptpr1[0])/2,(ptpr0[1]+ptpr1[1])/2), ptpr1]]
        
        #print('After uniform sampling, it has %i points' % len(stroke))
        # non-uniform/detail subsampling
        start = time.time()
        done = False
        iters = 0
        while not done and iters < 40:
            iters += 1
            done = True
            nstroke = [stroke[0]]
            
            eds = list(zip(stroke[:-1],stroke[1:]))
            n = 0
            while n <= len(eds)-1:
                (ptpr0, ptpr1) = eds[n]
                pt0,pr0 = ptpr0
                pt1,pr1 = ptpr1
                if (pt0-pt1).length > (pr0+pr1)/10:
                    nstroke += [((pt0+pt1)/2, (pr0+pr1)/2)]
                    
                elif (pt0-pt1).length < (pr0+pr1)/12:
                    s = (pt0-pt1).length
                    while s < (pr0+pr1)/10 and n < len(eds)-1:
                        n += 1
                        (ptpr0, ptpr1) = eds[n]
                        pt0,pr0 = ptpr0
                        pt1,pr1 = ptpr1
                        s += (pt0-pt1).length
                n += 1        
                nstroke += [ptpr1]
            done = (len(stroke) == len(nstroke))
            stroke = nstroke
        done = time.time()    
        #print('After detail up/dn sampling stroke now has %i points' % len(stroke))
        
        print('took %f sec to sample the stroke' % (done-start))
        #make sure we traveled at least the minimum distance brush length
        tot_length = sum((s0[0]-s1[0]).length for s0,s1 in zip(stroke[:-1],stroke[1:]))
        print(spc+'stroke cnt: %i, len: %f; sepv0: %s; sepv3: %s; only_ends: %s' % (len(stroke),tot_length,'t' if sepv0 else 'f', 't' if sepv3 else 'f', 't' if only_ends else 'f'))
        if tot_length < threshold_tooshort and not (sepv0 and sepv3):
            print(spc+'Stroke too short (%f)' % tot_length)
            return
        
        
        # self intersection test
        start = time.time()
        # ignore_lists is the set of neighboring points each point on the list has.
        # These points are 'near' but are not 'intersecting'
        ignore_lists = [set() for _ in range( len( stroke ) )]

        # Initialize the kd-tree that will be used to find intersecting points
        kd = kdtree.KDTree( len(stroke) )

        # fill in the ignore lists and kd-tree
        for i in range( len( stroke ) ):
            pt0,pr0 = stroke[i]

            # insert into kdtree
            kd.insert( pt0, i )

            # Add this point to its own ignore list
            ignore_lists[i].add(i)

            # add neighboring points to the ignore list
            for j in range( i + 1, len( stroke ) ):
                pt1,pr1 = stroke[j]

                # If the points are 'near' then add them to eachothers ignore list
                if (pt0-pt1).length <= min( pr0, pr1 ):
                    ignore_lists[i].add(j)
                    ignore_lists[j].add(i)
                else:
                    break

        # finalize the kd-tree
        kd.balance()
        
        
        # find intersections
        min_i0,min_i1,min_dist = -1,-1,float('inf')
        for i in range( len( stroke ) ):
            pt0,pr0 = stroke[i]
            # find all points touching the given point that are not in the ignore list
            nearby_results = kd.find_range( pt0, pr0 )
            _, nearby_indexes, _ = zip(*nearby_results)
            # XOR the nearby list and the ignore list to get non-ignored intersecting points
            intersecting_indexes = set(nearby_indexes)^ignore_lists[i]
            # track the closest two points
            for j in intersecting_indexes:
                pt1,pr1 = stroke[j]
                dist = (pt0-pt1).length - min(pr0,pr1)
                if dist < min_dist:
                    min_i0 = i
                    min_i1 = j
                    min_dist = dist
        
        if min_dist < 0:
            i0 = min_i0
            i1 = min_i1
            
            pt0,pr0 = stroke[i0]
            pt1,pr1 = stroke[i1]
            
            # create gvert at intersecting points and recurse!
            epv_intersect = self.create_epvert(pt0)
            def find_not_picking(i_start, i_direction):
                i = i_start
                while i >= 0 and i < len(stroke):
                    if not epv_intersect.is_picked(stroke[i][0]): return i
                    i += i_direction
                return -1
            i00 = find_not_picking(i0,-1)
            i01 = find_not_picking(i0, 1)
            i10 = find_not_picking(i1,-1)
            i11 = find_not_picking(i1, 1)
            dprint(spc+'stroke self intersection %i,%i => %i,%i,%i,%i' % (i0,i1,i00,i01,i10,i11))
            if i00 != -1:
                dprint(spc+'seg 0')
                self.insert_epedge_from_stroke_kd(stroke[:i00], only_ends=False, sepv0=sepv0, sepv3=epv_intersect, depth=depth+1)
            if i01 != -1 and i10 != -1:
                dprint(spc+'seg 1')
                self.insert_epedge_from_stroke_kd(stroke[i01:i10], only_ends=False, sepv0=epv_intersect, sepv3=epv_intersect, depth=depth+1)
            if i11 != -1:
                dprint(spc+'seg 2')
                self.insert_epedge_from_stroke_kd(stroke[i11:], only_ends=False, sepv0=epv_intersect, sepv3=sepv3, depth=depth+1)
            return
        
        done = time.time()
        print('took %f seconds to do self intersection' % (done-start))
        
        pts = [p for p,_ in stroke]
        radius = 2*stroke[0][1] #The seg length is diameter of brush
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
                    i0 = i #index of first point near an existing EPV
                
                else:#have already found a swing by vert
                    if dist < maxdist: continue
                    i1 = i #first vert that is further away than intersection, so we can clip it here
                    break
            if i0==-1: continue  #didnt find any swing bys
            
            if i0==0:
                print('first vert is near an EPVert')
                if i1!=-1:
                    if sepv0:
                        epv1 = self.create_epvert(sepv0.position * 0.75 + epv.position * 0.25)
                        epv2 = self.create_epvert(sepv0.position * 0.25 + epv.position * 0.75)
                        self.create_epedge(sepv0, epv1, epv2, epv,rad = radius)
                    self.insert_epedge_from_stroke_kd(stroke[i1:], only_ends = False, error_scale=error_scale, maxdist=maxdist, sepv0=epv, sepv3=sepv3, depth=depth+1)
                elif sepv0 and sepv3:
                    epv1 = self.create_epvert(sepv0.position * 0.75 + sepv3.position * 0.25)
                    epv2 = self.create_epvert(sepv0.position * 0.25 + sepv3.position * 0.75)
                    self.create_epedge(sepv0, epv1, epv2, sepv3, rad = radius)
                    
                else:
                    print('all of the stroke was within radius of swing by point so its a little tippy tail')
            else:
                self.insert_epedge_from_stroke_kd(stroke[:i0], only_ends = False, error_scale=error_scale, maxdist=maxdist, sepv0=sepv0, sepv3=epv, depth=depth+1)
                if i1!=-1:
                    self.insert_epedge_from_stroke_kd(stroke[i1:], only_ends = False, error_scale=error_scale, maxdist=maxdist, sepv0=epv, sepv3=sepv3, depth=depth+1)
            
            return
        #pr.done()
        
        # check if stroke crosses any epedges
        #pr = profiler.start()
        start = time.time()
        for epe in self.epedges:
            c = len(epe.curve_verts)
            print('curve verts %i' % c)
            if not len(epe.curve_norms) == c:
                print('why!?')
                epe.update_shape()
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
                    self.insert_epedge_from_stroke_kd(stroke, only_ends = False, error_scale=error_scale, maxdist=maxdist, sepv0=sepv0, sepv3=sepv3, depth=depth+1)
                    #pr.done()
                    return
        #pr.done()
        print('took %f seconds to check path crossings' % (time.time() - start))
        if len(pts) < 6:
            if not sepv0 or not sepv3: return
            epv1 = self.create_epvert(sepv0.position * 0.75 + sepv3.position * 0.25)
            epv2 = self.create_epvert(sepv0.position * 0.25 + sepv3.position * 0.75)
            self.create_epedge(sepv0, epv1, epv2, sepv3, rad = radius)
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
            epe = self.create_epedge(epv0, epv1, epv2, epv3, rad = radius)
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
        self.epverts = [epv for epv in self.epverts if  (not epv.is_unconnected() or epv.from_bmesh)]

    def dissolve_epvert(self, epvert, tessellation=20):
        assert not epvert.isinner, 'Attempting to dissolve an inner EPVert'
        assert len(epvert.epedges) == 2, 'Attempting to dissolve an EPVert that does not have exactly 2 connected EPEdges'
        
        epedge0,epedge1 = epvert.epedges
        
        if epedge0.from_bmesh and epedge1.from_bmesh:
            pts0 = epedge0.edge_verts
            pts1 = epedge1.edge_verts

            bmvs0 = epedge0.edge_bmverts
            bmvs1 = epedge1.edge_bmverts
            
            ns0 = epedge0.edge_vert_norms
            ns1 = epedge1.edge_vert_norms
            
            if epedge0.epvert0 == epvert: pts0.reverse(), bmvs0.reverse(), ns0.reverse()
            if epedge1.epvert3 == epvert: pts1.reverse(), bmvs1.reverse(), ns1.reverse()
        
            pts = pts0 + pts1[1:]
            print(pts)
            bmvs = bmvs0 + bmvs1[1:]
            ns = ns0 + ns1[1:]
            
            p1 = .75*pts[0] + 0.25*pts[-1]
            p2 = .25*pts[0] + 0.75*pts[-1]
            
            from_bme = True
        elif (epedge0.from_bmesh or epedge1.from_bmesh):
            print('cant dissolve a vert that links existing mesh to new mesh')
            return
        
        else:    
            p00,p01,p02,p03 = epedge0.get_positions()
            p10,p11,p12,p13 = epedge1.get_positions()
            
            pts0 = [cubic_bezier_blend_t(p00,p01,p02,p03,i/tessellation) for i in range(tessellation+1)]
            pts1 = [cubic_bezier_blend_t(p10,p11,p12,p13,i/tessellation) for i in range(tessellation+1)]
            if epedge0.epvert0 == epvert: pts0.reverse()
            if epedge1.epvert3 == epvert: pts1.reverse()
            pts = pts0 + pts1
            
            t0,t3,p0,p1,p2,p3 = cubic_bezier_fit_points(pts, self.length_scale, allow_split=False)[0]
        
            from_bme = False
            
        epv0 = epedge0.epvert3 if epedge0.epvert0 == epvert else epedge0.epvert0
        epv1 = self.create_epvert(p1)
        epv2 = self.create_epvert(p2)
        epv3 = epedge1.epvert3 if epedge1.epvert0 == epvert else epedge1.epvert0
        
        self.disconnect_epedge(epedge0)
        self.disconnect_epedge(epedge1)
        rad = .5 * (epedge0.quad_size + epedge1.quad_size)
        
        
        epe = self.create_epedge(epv0,epv1,epv2,epv3, rad = rad, from_bme = from_bme)
        
        if from_bme:
            epe.edge_verts = pts
            epe.edge_vert_norms = ns
            epe.curve_verts = pts
            epe.curve_norms = ns
            epe.edge_bmverts = bmvs
            
            
        epv0.update()
        epv0.update_epedges()
        epv3.update()
        epv3.update_epedges()
    
    def subdivide_eppatch(self, eppatch, epedge0, epedg1, t):
        pass
    
    
    def push_into_bmesh(self,context, bme):
        '''
        TODO this just puts all the patches together
        and inserts them into bme
        
        It is IMPERATIVE that this is the same unmodified
        bme since Edge Patches was started since there are
        mappings to existing geometry.  Or later, if the
        fidelity of those mappings has not changed
        
        '''
        
        tmx = bpy.data.objects[EdgePatches.tar_name].matrix_world
        me = bpy.data.objects[EdgePatches.tar_name].data
        
        itmx = tmx.inverted()
    
        L = len(bme.verts)
        new_bmverts = []
        #add in the EPVert verts as nodes
        for epv in self.epverts:
            if epv.from_bmesh: continue #alrady in there
            elif epv.is_inner(): continue  #fake, not really needed
            
            self.bmv_epv_map[L+len(new_bmverts)] = epv
            epv.bmesh_ind = L + len(new_bmverts)
            new_bmverts += [bme.verts.new(itmx * epv.snap_pos)]
            
        bme.verts.index_update()
        bme.verts.ensure_lookup_table()
            
        for epe in self.epedges:
            if epe.from_bmesh: continue
            
            epe.edge_bmverts = [epe.epvert0.bmesh_ind]
            for v in epe.edge_verts[1:len(epe.edge_verts)-1]:
                epe.edge_bmverts += [L + len(new_bmverts)]
                new_bmverts += [bme.verts.new(itmx * v)]
            epe.edge_bmverts += [epe.epvert3.bmesh_ind]
            
            
        bme.verts.index_update()
        bme.verts.ensure_lookup_table()
            
        for epp in self.eppatches:
            if epp.bmesh:
                #join_bmesh(source, target....)
                #src bmeshes in this case, do not match the "source" or reference
                #object of operatory. The individual bmesh patches, all exist in world
                #coordinates, and they are the source for this joining operation.
                #th
                
                perim_loop = epp.get_bme_vert_loop()
                print(perim_loop)
                perim_vs = [tmx*bme.verts[i].co for i in perim_loop]
                
                patch_outer_inds = find_perimeter_verts(epp.bmesh)
                
                v0 = find_coord(epp.bmesh, perim_vs[0], patch_outer_inds) 
                i0 = patch_outer_inds.index(v0)
                
                patch_outer_inds = patch_outer_inds[i0:] + patch_outer_inds[:i0]
                
                v1 = find_coord(epp.bmesh, perim_vs[1], patch_outer_inds)
                i1 = patch_outer_inds.index(v1)
                print('i1 is %i' % i1)
                if i1 != 1:
                    if i1 == len(patch_outer_inds) -1:
                        print('i1 != 1, and is == len(outer_inds) -1')
                    print('reversing')
                    patch_outer_inds.reverse()
                    patch_outer_inds = [patch_outer_inds[-1]] + patch_outer_inds[0:len(patch_outer_inds)-1]
                
                perimeter_map = {}
                print('Are these even %i,  %i' % (len(patch_outer_inds),len(perim_loop)))    
                for n, m in zip(patch_outer_inds, perim_loop):
                    perimeter_map[n] = m
                
                
                print(perimeter_map)
                join_bmesh(epp.bmesh, bme, perimeter_map, src_mx = None, trg_mx = tmx)
                epp.bmesh.free()

        if context.mode == 'OBJECT':
            bme.to_mesh(me)
        else:
            bmesh.update_edit_mesh(me)
            
        bme.free()
        bpy.app.debug = True    

                
