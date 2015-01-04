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

####class definitions####

import bpy
import math
from math import sin, cos
import time
import copy
from mathutils import Vector, Quaternion
from mathutils.geometry import intersect_point_line, intersect_line_plane
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d, region_2d_to_origin_3d
import bmesh
import blf, bgl
import itertools

from .lib import common_utilities
from .lib.common_utilities import iter_running_sum, dprint, get_object_length_scale, profiler, AddonLocator,frange

from .polystrips_utilities import *
from .polystrips_draw import *
from . import polystrips_utilities

#Make the addon name and location accessible
AL = AddonLocator()


class GVert:
    def __init__(self, obj, targ_obj, length_scale, position, radius, normal, tangent_x, tangent_y, from_mesh = False):
        # store info
        self.o_name       = obj.name
        self.targ_o_name  = targ_obj.name
        self.length_scale = length_scale
        
        self.position  = position
        self.radius    = radius
        self.normal    = normal
        self.tangent_x = tangent_x
        self.tangent_y = tangent_y
        
        self.snap_pos  = position
        self.snap_norm = normal
        self.snap_tanx = tangent_x
        self.snap_tany = tangent_y
        
        self.gedge0 = None
        self.gedge1 = None
        self.gedge2 = None
        self.gedge3 = None
        self.gedge_inner = None
        
        self.zip_over_gedge = None      # which gedge to zip over (which gets updated...)
        self.zip_t          = 0         # where do we attach?
        self.zip_igv        = 0
        self.zip_snap_end   = False     # do we snap to endpoint of zip_over_gedge?
        
        self.doing_update = False
        
        self.visible = True
        
        #data used when extending or emulating data
        #already within a BMesh
        self.from_mesh = from_mesh
        self.from_mesh_ind = -1 #needs to be set explicitly
        self.corner0_ind = -1
        self.corner1_ind = -1
        self.corner2_ind = -1
        self.corner3_ind = -1
        
        self.frozen = True if self.from_mesh else False
        
        self.update()
    
    def clone_detached(self):
        '''
        creates detached clone of gvert (without gedges)
        '''
        gv = GVert(bpy.data.objects[self.o_name], bpy.data.objects[self.targ_o_name], self.length_scale, Vector(self.position), self.radius, Vector(self.normal), Vector(self.tangent_x), Vector(self.tangent_y))
        gv.snap_pos = Vector(self.snap_pos)
        gv.snap_norm = Vector(self.snap_norm)
        gv.snap_tanx = Vector(self.snap_tanx)
        gv.snap_tany = Vector(self.snap_tany)
        return gv
    
    def has_0(self): return not (self.gedge0 is None)
    def has_1(self): return not (self.gedge1 is None)
    def has_2(self): return not (self.gedge2 is None)
    def has_3(self): return not (self.gedge3 is None)
    def is_inner(self): return not (self.gedge_inner is None)
    
    def count_gedges(self):   return len(self.get_gedges_notnone())
    
    def is_unconnected(self): return not (self.has_0() or self.has_1() or self.has_2() or self.has_3())
    def is_endpoint(self):    return self.has_0() and not (self.has_1() or self.has_2() or self.has_3())
    def is_endtoend(self):    return self.has_0() and self.has_2() and not (self.has_1() or self.has_3())
    def is_ljunction(self):   return self.has_0() and self.has_1() and not (self.has_2() or self.has_3())
    def is_tjunction(self):   return self.has_0() and self.has_1() and self.has_3() and not self.has_2()
    def is_cross(self):       return self.has_0() and self.has_1() and self.has_2() and self.has_3()
    
    def is_frozen(self): return self.frozen
    
    def get_gedges(self): return [self.gedge0,self.gedge1,self.gedge2,self.gedge3]
    def _set_gedges(self, ge0, ge1, ge2, ge3):
        self.gedge0,self.gedge1,self.gedge2,self.gedge3 = ge0,ge1,ge2,ge3
    def count_gedges(self):
        return sum([self.has_0(),self.has_1(),self.has_2(),self.has_3()])
    def get_gedges_notnone(self): return [ge for ge in self.get_gedges() if ge]
    
    def get_inner_gverts(self): return [ge.get_inner_gvert_at(self) for ge in self.get_gedges_notnone()]
    
    def get_zip_pair(self):
        ge = self.zip_over_gedge
        if not ge: return None
        if ge.gvert0==self: return ge.gvert3
        if ge.gvert3==self: return ge.gvert0
        assert False
    
    def disconnect_gedge(self, gedge):
        pr = profiler.start()
        if self.gedge_inner == gedge:
            self.gedge_inner = None
        else:
            l_gedges = self.get_gedges_notnone()
            assert gedge in l_gedges
            l_gedges = [ge for ge in l_gedges if ge != gedge]  #interesting way of removing
            l = len(l_gedges)
            l_gedges = [l_gedges[i] if i < l else None for i in range(4)]
            self._set_gedges(*l_gedges)
            self.update_gedges()
        pr.done()
    
    def connect_gedge_inner(self, gedge):
        assert self.is_unconnected()
        assert not self.gedge_inner
        self.gedge_inner = gedge
    
    def update_gedges(self):
        if self.is_unconnected(): return
        
        pr = profiler.start()
        
        norm = self.snap_norm
        
        l_gedges = self.get_gedges_notnone()
        l_vecs   = [ge.get_derivative_at(self).normalized() for ge in l_gedges]
        if any(v.length == 0 for v in l_vecs): print (l_vecs)
        #l_vecs = [v if v.length else Vector((1,0,0)) for v in l_vecs]
        l_gedges = sort_objects_by_angles(norm, l_gedges, l_vecs)
        l_vecs   = [ge.get_derivative_at(self).normalized() for ge in l_gedges]
        if any(v.length == 0 for v in l_vecs): print(l_vecs)
        #l_vecs = [v if v.length else Vector((1,0,0)) for v in l_vecs]
        l_angles = [vector_angle_between(v0,v1,norm) for v0,v1 in zip(l_vecs,l_vecs[1:]+[l_vecs[0]])]
        
        connect_count = len(l_gedges)
        
        if connect_count == 1:
            self._set_gedges(l_gedges[0],None,None,None)
            assert self.is_endpoint()
        elif connect_count == 2:
            d0 = abs(l_angles[0]-math.pi)
            d1 = abs(l_angles[1]-math.pi)
            if d0 < math.pi*0.2 and d1 < math.pi*0.2:
                self._set_gedges(l_gedges[0],None,l_gedges[1],None)
                assert self.is_endtoend()
            else:
                if l_angles[0] < l_angles[1]:
                    self._set_gedges(l_gedges[0],l_gedges[1],None,None)
                else:
                    self._set_gedges(l_gedges[1],l_gedges[0],None,None)
                assert self.is_ljunction()
        elif connect_count == 3:
            if l_angles[0] >= l_angles[1] and l_angles[0] >= l_angles[2]:
                self._set_gedges(l_gedges[2],l_gedges[0],None,l_gedges[1])
            elif l_angles[1] >= l_angles[0] and l_angles[1] >=  l_angles[2]:
                self._set_gedges(l_gedges[0],l_gedges[1],None,l_gedges[2])
            else:
                self._set_gedges(l_gedges[1],l_gedges[2],None,l_gedges[0])
            assert self.is_tjunction()
        elif connect_count == 4:
            self._set_gedges(*l_gedges)
            assert self.is_cross()
        else:
            assert False
        
        self.update()
        
        pr.done()
    
    
    def connect_gedge(self, gedge):
        pr = profiler.start()
        if not self.gedge0: self.gedge0 = gedge
        elif not self.gedge1: self.gedge1 = gedge
        elif not self.gedge2: self.gedge2 = gedge
        elif not self.gedge3: self.gedge3 = gedge
        else: assert False
        self.update_gedges()
        pr.done()
    
    def replace_gedge(self, gedge, ngedge):
        if self.gedge0 == gedge: self.gedge0 = ngedge
        elif self.gedge1 == gedge: self.gedge1 = ngedge
        elif self.gedge2 == gedge: self.gedge2 = ngedge
        elif self.gedge3 == gedge: self.gedge3 = ngedge
        else: assert False
    
    def snap_corners(self):
        if self.frozen: return
        pr = profiler.start()
        
        mx = bpy.data.objects[self.o_name].matrix_world
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        self.corner0 = mx * bpy.data.objects[self.o_name].closest_point_on_mesh(imx*self.corner0)[0]
        self.corner1 = mx * bpy.data.objects[self.o_name].closest_point_on_mesh(imx*self.corner1)[0]
        self.corner2 = mx * bpy.data.objects[self.o_name].closest_point_on_mesh(imx*self.corner2)[0]
        self.corner3 = mx * bpy.data.objects[self.o_name].closest_point_on_mesh(imx*self.corner3)[0]
        
        pr.done()
    
    def update(self, do_edges=True):
        if self.doing_update: return
        if self.zip_over_gedge and do_edges:
            self.zip_over_gedge.update()
            return
        
        pr = profiler.start()
        
        mx = bpy.data.objects[self.o_name].matrix_world
        imx = mx.inverted()
        mxnorm = imx.transposed().to_3x3()
        mx3x3 = mx.to_3x3()
        
        if not self.frozen:
            l,n,i = bpy.data.objects[self.o_name].closest_point_on_mesh(imx*self.position)
            self.snap_norm = (mxnorm * n).normalized()
            self.snap_pos  = mx * l
            self.position = self.snap_pos

        self.snap_tanx = self.tangent_x.normalized()
        self.snap_tany = self.snap_norm.cross(self.snap_tanx).normalized()
        # NOTE! DO NOT UPDATE NORMAL, TANGENT_X, AND TANGENT_Y
        if do_edges:
            self.doing_update = True
            for gedge in [self.gedge0,self.gedge1,self.gedge2,self.gedge3]:
                if gedge: gedge.update()
            if self.gedge_inner: self.gedge_inner.update()
            self.doing_update = False
        
        self.snap_tanx = (Vector((0.2,0.1,0.5)) if not self.gedge0 else self.gedge0.get_derivative_at(self)).normalized()
        self.snap_tany = self.snap_norm.cross(self.snap_tanx).normalized()
        if self.frozen and self.gedge0:
             vy = self.corner0 - self.corner1
             vy.normalize()
             
             vx = self.corner1 - self.corner2
             vx.normalize()
             
             test1 = vx.dot(self.snap_tanx)
             test2 = vy.dot(self.snap_tany)
            
             if test1 < -.7:
                 self.corner0, self.corner1, self.corner2, self.corner3 = self.corner2, self.corner3, self.corner0, self.corner1
                 self.corner0_ind, self.corner1_ind, self.corner2_ind, self.corner3_ind = self.corner2_ind, self.corner3_ind, self.corner0_ind, self.corner1_ind
             if test1  > -.7 and test1 < .7:
                 if test2 > .7:
                     self.corner0, self.corner1, self.corner2, self.corner3 = self.corner3, self.corner0, self.corner1, self.corner2
                     self.corner0_ind, self.corner1_ind, self.corner2_ind, self.corner3_ind = self.corner3_ind, self.corner0_ind, self.corner1_ind, self.corner2_ind
                 else:
                     self.corner0, self.corner1, self.corner2, self.corner3 = self.corner1, self.corner2, self.corner3, self.corner0  
                     self.corner0_ind, self.corner1_ind, self.corner2_ind, self.corner3_ind = self.corner1_ind, self.corner2_ind, self.corner3_ind, self.corner0_ind
        
        if not self.zip_over_gedge:
            # NOTE! DO NOT UPDATE NORMAL, TANGENT_X, AND TANGENT_Y
            
            
            #         ge2         #
            #          |          #
            #      2 --+-- 3      #
            #      |       |      #
            # ge1--+   +Y  +--ge3 #
            #      |   X   |      #
            #      1---+---0      #
            #          |          #
            #         ge0         #
            
            # TODO: make this go CCW :P
            
            def get_corner(self,dmx,dmy, igv0,r0, igv1,r1):
                if not igv0 and not igv1:
                    return self.snap_pos + self.snap_tanx*self.radius*dmx + self.snap_tany*self.radius*dmy
                if igv0 and not igv1:
                    return igv0.position + igv0.tangent_y*r0
                if igv1 and not igv0:
                    return igv1.position - igv1.tangent_y*r1
                return (igv0.position+igv0.tangent_y*r0 + igv1.position-igv1.tangent_y*r1)/2
            
            igv0 = None if not self.gedge0 else self.gedge0.get_igvert_at(self)
            igv1 = None if not self.gedge1 else self.gedge1.get_igvert_at(self)
            igv2 = None if not self.gedge2 else self.gedge2.get_igvert_at(self)
            igv3 = None if not self.gedge3 else self.gedge3.get_igvert_at(self)
            
            r0 = 0 if not igv0 else (igv0.radius*(1 if igv0.tangent_x.dot(self.snap_tanx)>0 else -1))
            r1 = 0 if not igv1 else (igv1.radius*(1 if igv1.tangent_x.dot(self.snap_tany)<0 else -1))
            r2 = 0 if not igv2 else (igv2.radius*(1 if igv2.tangent_x.dot(self.snap_tanx)<0 else -1))
            r3 = 0 if not igv3 else (igv3.radius*(1 if igv3.tangent_x.dot(self.snap_tany)>0 else -1))
            
            if not self.frozen:
                self.corner0 = get_corner(self, 1, 1, igv0,r0, igv3,r3)
                self.corner1 = get_corner(self, 1,-1, igv1,r1, igv0,r0)
                self.corner2 = get_corner(self,-1,-1, igv2,r2, igv1,r1)
                self.corner3 = get_corner(self,-1, 1, igv3,r3, igv2,r2)
        
        self.snap_corners()
        
        pr.done()
    
    def update_corners_zip(self, p0, p1, p2, p3):
        if self.zip_over_gedge == self.gedge0:
            self.corner0 = p0
            self.corner1 = p1
            self.corner2 = p2
            self.corner3 = p3
        elif self.zip_over_gedge == self.gedge1:
            self.corner1 = p0
            self.corner2 = p1
            self.corner3 = p2
            self.corner0 = p3
        elif self.zip_over_gedge == self.gedge2:
            self.corner2 = p0
            self.corner3 = p1
            self.corner0 = p2
            self.corner1 = p3
        elif self.zip_over_gedge == self.gedge3:
            self.corner3 = p0
            self.corner0 = p1
            self.corner1 = p2
            self.corner2 = p3
        else:
            assert False
    
    def update_visibility(self, r3d, update_gedges=False, hq = True):
        if hq:
            self.visible = False not in common_utilities.ray_cast_visible(self.get_corners(), bpy.data.objects[self.o_name], r3d)
        else:
            self.visible = common_utilities.ray_cast_visible([self.snap_pos], bpy.data.objects[self.o_name], r3d)[0]
        
        if not update_gedges: return
        for ge in self.get_gedges_notnone():
            ge.update_visibility(r3d)
    
    def is_visible(self): return self.visible
    
    def get_corners(self):
        return (self.corner0, self.corner1, self.corner2, self.corner3)
    
    def get_corner_inds(self):
        return (self.corner0_ind, self.corner1_ind, self.corner2_ind, self.corner3_ind)
    
    def is_picked(self, pt):
        if not self.visible: return False
        c0 = self.corner0 - pt
        c1 = self.corner1 - pt
        c2 = self.corner2 - pt
        c3 = self.corner3 - pt
        n = self.snap_norm
        d0 = c1.cross(c0).dot(n)
        d1 = c2.cross(c1).dot(n)
        d2 = c3.cross(c2).dot(n)
        d3 = c0.cross(c3).dot(n)
        return d0>0 and d1>0 and d2>0 and d3>0
    
    def get_corners_of(self, gedge):
        if gedge == self.gedge0: return (self.corner0, self.corner1)
        if gedge == self.gedge1: return (self.corner1, self.corner2)
        if gedge == self.gedge2: return (self.corner2, self.corner3)
        if gedge == self.gedge3: return (self.corner3, self.corner0)
        assert False, "GEdge is not connected"
    
    def get_back_corners_of(self, gedge):
        if gedge == self.gedge0: return (self.corner2, self.corner3)
        if gedge == self.gedge1: return (self.corner3, self.corner0)
        if gedge == self.gedge2: return (self.corner0, self.corner1)
        if gedge == self.gedge3: return (self.corner1, self.corner2)
        assert False, "GEdge is not connected"
    
    def get_cornerinds_of(self, gedge):
        if gedge == self.gedge0: return (0,1)
        if gedge == self.gedge1: return (1,2)
        if gedge == self.gedge2: return (2,3)
        if gedge == self.gedge3: return (3,0)
        assert False, "GEdge is not connected"
    
    def get_back_cornerinds_of(self, gedge):
        if gedge == self.gedge0: return (2,3)
        if gedge == self.gedge1: return (3,0)
        if gedge == self.gedge2: return (0,1)
        if gedge == self.gedge3: return (1,2)
        assert False, "GEdge is not connected"
    
    def get_side_cornerinds_of(self, gedge, side):
        '''
        return cornerinds on side that go toward gedge
        '''
        if gedge == self.gedge0: return (3,0) if side>0 else (2,1)
        if gedge == self.gedge1: return (0,1) if side>0 else (3,2)
        if gedge == self.gedge2: return (1,2) if side>0 else (0,3)
        if gedge == self.gedge3: return (2,3) if side>0 else (1,0)
        assert False, "GEdge is not connected"
    
    def toggle_corner(self):
        if (self.is_endtoend() or self.is_ljunction()):
            if self.is_ljunction():
                self._set_gedges(self.gedge0,None,self.gedge1,None)
                assert self.is_endtoend()
            else:
                self._set_gedges(self.gedge2,self.gedge0,None,None)
                assert self.is_ljunction()
            self.update()
        elif self.is_tjunction():
            self._set_gedges(self.gedge3,self.gedge0,None,self.gedge1)
            assert self.is_tjunction()
            self.update()
        else:
            print('Cannot toggle corner on GVert with %i connections' % self.count_gedges())
    
    def smooth(self, v=0.15):
        pr = profiler.start()
        
        der0 = self.gedge0.get_derivative_at(self, ignore_igverts=True).normalized() if self.gedge0 else Vector()
        der1 = self.gedge1.get_derivative_at(self, ignore_igverts=True).normalized() if self.gedge1 else Vector()
        der2 = self.gedge2.get_derivative_at(self, ignore_igverts=True).normalized() if self.gedge2 else Vector()
        der3 = self.gedge3.get_derivative_at(self, ignore_igverts=True).normalized() if self.gedge3 else Vector()
        
        if self.is_endtoend():
            angle = (math.pi - der0.angle(der2))*v
            cross = der0.cross(der2).normalized()
            
            quat0 = Quaternion(cross, -angle)
            quat1 = Quaternion(cross, angle)
            
            self.gedge0.rotate_gverts_at(self, quat0)
            self.gedge2.rotate_gverts_at(self, quat1)
            self.update()
        
        if self.is_ljunction():
            angle = (math.pi/2 - der0.angle(der1))*v
            cross = der0.cross(der1).normalized()
            
            quat0 = Quaternion(cross, -angle)
            quat1 = Quaternion(cross, angle)
            
            self.gedge0.rotate_gverts_at(self, quat0)
            self.gedge1.rotate_gverts_at(self, quat1)
            self.update()
        
        if self.is_tjunction():
            angle = (math.pi/2 - der3.angle(der0))*v
            cross = der3.cross(der0).normalized()
            self.gedge3.rotate_gverts_at(self, Quaternion(cross, -angle))
            self.gedge0.rotate_gverts_at(self, Quaternion(cross,  angle))
            
            angle = (math.pi/2 - der0.angle(der1))*v
            cross = der0.cross(der1).normalized()
            self.gedge0.rotate_gverts_at(self, Quaternion(cross, -angle))
            self.gedge1.rotate_gverts_at(self, Quaternion(cross,  angle))
            
            self.update()
        
        if self.is_cross():
            cross = self.snap_norm.normalized()
            
            ang30 = (math.pi/2 - vector_angle_between(der3,der0,cross))*v
            self.gedge3.rotate_gverts_at(self, Quaternion(cross,  ang30))
            self.gedge0.rotate_gverts_at(self, Quaternion(cross, -ang30))
            
            ang01 = (math.pi/2 - vector_angle_between(der0,der1,cross))*v
            self.gedge0.rotate_gverts_at(self, Quaternion(cross,  ang01))
            self.gedge1.rotate_gverts_at(self, Quaternion(cross, -ang01))
            
            ang12 = (math.pi/2 - vector_angle_between(der1,der2,cross))*v
            self.gedge1.rotate_gverts_at(self, Quaternion(cross,  ang12))
            self.gedge2.rotate_gverts_at(self, Quaternion(cross, -ang12))
            
            ang23 = (math.pi/2 - vector_angle_between(der2,der3,cross))*v
            self.gedge2.rotate_gverts_at(self, Quaternion(cross,  ang23))
            self.gedge3.rotate_gverts_at(self, Quaternion(cross, -ang23))
            
            self.update()
        
        pr.done()


class GEdge:
    '''
    Graph Edge (GEdge) stores end points and "way points" (cubic bezier)
    '''
    def __init__(self, obj, targ_obj, length_scale, gvert0, gvert1, gvert2, gvert3):
        # store end gvertices
        self.o_name = obj.name
        self.targ_o_name = targ_obj.name
        self.length_scale = length_scale
        self.gvert0 = gvert0
        self.gvert1 = gvert1
        self.gvert2 = gvert2
        self.gvert3 = gvert3
        
        self.force_count = False
        self.n_quads = None
        
        self.zip_to_gedge   = None
        self.zip_side       = 1
        self.zip_dir        = 1
        
        self.zip_attached   = []
        
        self.frozen = False

        self.l_ts = []
        self.gpatches = []
        
        # create caching vars
        self.cache_igverts = []             # cached interval gverts
                                            # even-indexed igverts are poly "centers"
                                            #  odd-indexed igverts are poly "edges"
        
        gvert0.connect_gedge(self)
        gvert1.connect_gedge_inner(self)
        gvert2.connect_gedge_inner(self)
        gvert3.connect_gedge(self)

    def get_count(self):
        l = len(self.cache_igverts)
        if l > 4:
            n_quads = math.floor(l/2) + 1
        else:
            n_quads = 3
        return n_quads
    
    def set_count(self, c):
        if self.force_count and self.n_quads == c:
            return
        
        self.force_count = True
        self.n_quads = c
        
        if self.gpatches:
            for gpatch in self.gpatches:
                gpatch.set_count(self)
        
        self.update()
        
    def unset_count(self):
        if self.fill_to0 or self.fill_to1:
            print('Cannot unset force count when filling')
            return
        self.force_count = None
        self.n_quads = None
        self.update()
    
    def is_zippered(self): return (self.zip_to_gedge != None)
    def has_zippered(self): return len(self.zip_attached)!=0
    
    def is_frozen(self): return self.frozen
    
    def zip_to(self, gedge):
        assert not self.zip_to_gedge
        
        self.zip_to_gedge = gedge
        gedge.zip_attached += [self]
        
        t0,_ = gedge.get_closest_point(self.gvert0.position)
        t3,_ = gedge.get_closest_point(self.gvert3.position)
        
        pos = gedge.get_position_at_t(t0)
        der = gedge.get_derivative_at_t(t0)
        nor = gedge.gvert0.snap_norm
        tny = nor.cross(der)
        
        # which side are we on and which way are we going?
        self.zip_side = 1 if tny.dot(self.gvert0.position-pos)>0 else -1
        self.zip_dir  = 1 if tny.dot(self.gvert0.snap_tany)>0 else -1
        
        self.gvert0.zip_over_gedge = self
        self.gvert0.zip_t          = t0
        self.gvert3.zip_over_gedge = self
        self.gvert3.zip_t          = t3
        
        self.update()
    
    def unzip(self):
        assert self.zip_to_gedge
        gedge = self.zip_to_gedge
        self.zip_to_gedge = None
        gedge.zip_attached = [ge for ge in gedge.zip_attached if ge != self]
        self.gvert0.zip_over_gedge = None
        self.gvert3.zip_over_gedge = None
        self.update()

    def is_gpatched(self):
        return len(self.gpatches)
    
    def attach_gpatch(self, gpatch):
        if len(self.gpatches) >= 2:
            print('Cannot attach more than two gpatches')
            return
        self.gpatches.append(gpatch)
    
    def detach_gpatch(self, gpatch):
        self.gpatches.remove(gpatch)
        for gp in self.gpatches:
            gp.update()
    
    def rotate_gverts_at(self, gv, quat):
        if gv == self.gvert0:
            v = self.gvert1.position - self.gvert0.position
            v = quat * v
            self.gvert1.position = self.gvert0.position + v
            self.gvert1.update()
        elif gv == self.gvert3:
            v = self.gvert2.position - self.gvert3.position
            v = quat * v
            self.gvert2.position = self.gvert3.position + v
            self.gvert2.update()
        else:
            assert False
    
    def disconnect(self):
        if self.zip_to_gedge:
            self.unzip()
        for ge in self.zip_attached:
            ge.unzip()
        self.gvert0.disconnect_gedge(self)
        self.gvert1.disconnect_gedge(self)
        self.gvert2.disconnect_gedge(self)
        self.gvert3.disconnect_gedge(self)
    
    def update_visibility(self, rv3d):
        lp = [gv.snap_pos for gv in self.cache_igverts]
        lv = common_utilities.ray_cast_visible(lp, bpy.data.objects[self.o_name], rv3d)
        for gv,v in zip(self.cache_igverts,lv): gv.visible = v
    
    def gverts(self):
        return [self.gvert0,self.gvert1,self.gvert2,self.gvert3]
    
    def get_derivative_at(self, gv, ignore_igverts=False):
        if not ignore_igverts and len(self.cache_igverts) < 3:
            if self.gvert0 == gv:
                return self.gvert3.position - self.gvert0.position
            if self.gvert3 == gv:
                return self.gvert0.position - self.gvert3.position
            assert False, "gv is not an endpoint"
        p0,p1,p2,p3 = self.get_positions()
        if self.gvert0 == gv:
            return cubic_bezier_derivative(p0,p1,p2,p3,0)
        if self.gvert3 == gv:
            return cubic_bezier_derivative(p3,p2,p1,p0,0)
        assert False, "gv is not an endpoint"
    
    def get_position_at_t(self, t):
        p0,p1,p2,p3 = self.get_positions()
        return cubic_bezier_blend_t(p0,p1,p2,p3,t)
    
    def get_derivative_at_t(self, t):
        p0,p1,p2,p3 = self.get_positions()
        return cubic_bezier_derivative(p0,p1,p2,p3,t)
    
    def get_inner_gvert_at(self, gv):
        if self.gvert0 == gv: return self.gvert1
        if self.gvert3 == gv: return self.gvert2
        assert False, "gv is not an endpoint"
    
    def get_outer_gvert_at(self, gv):
        if self.gvert1 == gv: return self.gvert0
        if self.gvert2 == gv: return self.gvert3
        assert False, "gv is not an inner gvert"
    
    def get_inner_gverts(self):
        return [self.gvert1, self.gvert2]
    
    def get_vector_from(self, gv):
        is_0 = (self.gvert0==gv)
        gv0 = self.gvert0 if is_0 else self.gvert3
        gv1 = self.gvert2 if is_0 else self.gvert1
        return gv1.position - gv0.position
    
    def get_igvert_at(self, gv):
        if self.gvert0 == gv:
            if len(self.cache_igverts):
                return self.cache_igverts[1]
            return None #self.gvert0
        if self.gvert3 == gv:
            if len(self.cache_igverts):
                return self.cache_igverts[-2]
            return None #self.gvert3
        assert False, "gv is not an endpoint"
    
    def get_positions(self):
        return (
            self.gvert0.position,
            self.gvert1.position,
            self.gvert2.position,
            self.gvert3.position
            )
    def get_normals(self):
        return (
            self.gvert0.normal,
            self.gvert1.normal,
            self.gvert2.normal,
            self.gvert3.normal
            )
    def get_radii(self):
        return (
            self.gvert0.radius,
            self.gvert1.radius,
            self.gvert2.radius,
            self.gvert3.radius
            )
    
    def get_length(self, precision = 64):
        p0,p1,p2,p3 = self.get_positions()
        mx = bpy.data.objects[self.o_name].matrix_world
        imx = mx.inverted()
        p3d = [cubic_bezier_blend_t(p0,p1,p2,p3,t/precision) for t in range(precision+1)]
        p3d = [mx*bpy.data.objects[self.o_name].closest_point_on_mesh(imx * p)[0] for p in p3d]
        return sum((p1-p0).length for p0,p1 in zip(p3d[:-1],p3d[1:]))
        #return cubic_bezier_length(p0,p1,p2,p3)
    
    def get_closest_point(self, pt):
        p0,p1,p2,p3 = self.get_positions()
        if len(self.cache_igverts) < 3:
            return cubic_bezier_find_closest_t_approx(p0,p1,p2,p3,pt)
        min_t,min_d = -1,-1
        i,l = 0,len(self.cache_igverts)
        for gv0,gv1 in zip(self.cache_igverts[:-1],self.cache_igverts[1:]):
            p0,p1 = gv0.position,gv1.position
            t,d = common_utilities.closest_t_and_distance_point_to_line_segment(pt, p0,p1)
            if min_t < 0 or d < min_d: min_t,min_d = (i+t)/l,d
            i += 1
        return min_t,min_d
    
    def get_igvert_from_t(self, t, next=False):
        return int((float(len(self.cache_igverts)-1)*t + (1 if next else 0))/2)*2
    
    def update_zip(self, debug=False):
        '''
        recomputes interval gverts along gedge---zipped version
        extend off of igverts of self.zip_to_gedge
        '''
        
        zip_igverts = self.zip_to_gedge.cache_igverts
        l = len(zip_igverts)
        
        t0 = self.gvert0.zip_t
        t3 = self.gvert3.zip_t
        i0 = self.zip_to_gedge.get_igvert_from_t(t0)
        i3 = self.zip_to_gedge.get_igvert_from_t(t3, next=True)
        
        self.gvert0.zip_igv = i0
        self.gvert3.zip_igv = i3
        
        dprint('zippered indices: %i (%f) %i (%f)  / %i' % (i0,t0,i3,t3,l))
        
        if i0 == i3:
            dprint('i0 == i3')
            self.cache_igverts = []
            
        else:
            if i0 < i3:
                ic = (i3-i0)+1
                if i3>len(zip_igverts):
                    dprint('%i %i %i' % (i0,i3,ic))
                loigv = [zip_igverts[i0+_i] for _i in range(ic)]
            elif i3 < i0:
                ic = (i0-i3)+1
                if i0>len(zip_igverts):
                    dprint('%i %i %i' % (i3,i0,ic))
                loigv = [zip_igverts[i3+_i] for _i in range(ic)]
                loigv.reverse()
            
            side = self.zip_side
            zdir = self.zip_dir
            
            r0,r3   = self.gvert0.radius,self.gvert3.radius
            rm      = (r3-r0)/float(ic+2)
            l_radii = [r0+rm*(_i+1)        for _i,oigv in enumerate(loigv)]
            l_pos   = [oigv.position+oigv.tangent_y*side*(oigv.radius+l_radii[_i]) for _i,oigv in enumerate(loigv)]
            l_norms = [oigv.normal         for _i,oigv in enumerate(loigv)]
            l_tanx  = [oigv.tangent_x*zdir for _i,oigv in enumerate(loigv)]
            l_tany  = [oigv.tangent_y*zdir for _i,oigv in enumerate(loigv)]
            
            self.cache_igverts = [GVert(bpy.data.objects[self.o_name], 
                                        bpy.data.objects[self.targ_o_name], 
                                        self.length_scale,p,r,n,tx,ty) for p,r,n,tx,ty in zip(l_pos,l_radii,l_norms,l_tanx,l_tany)]
            self.snap_igverts()
            
            assert len(self.cache_igverts)>=2, 'not enough! %i (%f) %i (%f) %i' % (i0,t0,i3,t3,ic)
            
            self.gvert0.position = self.cache_igverts[0].position
            self.gvert1.position = (self.cache_igverts[0].position+self.cache_igverts[-1].position)/2
            self.gvert2.position = (self.cache_igverts[0].position+self.cache_igverts[-1].position)/2
            self.gvert3.position = self.cache_igverts[-1].position
            
            def get_corners(ind, radius):
                if ind == -1:
                    p0,p1 = self.zip_to_gedge.gvert0.get_back_corners_of(self.zip_to_gedge)
                    if side<0:  p0,p1 = p0,p0+(p0-p1).normalized()*(radius*2)
                    else:       p0,p1 = p1,p1+(p1-p0).normalized()*(radius*2)
                    return (p1,p0)
                if ind == len(zip_igverts):
                    p0,p1 = self.zip_to_gedge.gvert3.get_back_corners_of(self.zip_to_gedge)
                    if side>0:  p0,p1 = p0,p0+(p0-p1).normalized()*(radius*2)
                    else:       p0,p1 = p1,p1+(p1-p0).normalized()*(radius*2)
                    return (p1,p0)
                
                igv = zip_igverts[ind]
                p0 = igv.position + igv.tangent_y*side*(igv.radius+radius*2)
                p1 = igv.position + igv.tangent_y*side*(igv.radius)
                return (p0,p1)
            
            if i0 < i3:
                p0,p1 = get_corners(i0+1,l_radii[1])
                p3,p2 = get_corners(i0-1,r0)
                if side < 0: p0,p1,p2,p3 = p1,p0,p3,p2
                self.gvert0.update_corners_zip(p0,p1,p2,p3)
                
                p0,p1 = get_corners(i3-1,l_radii[-2])
                p3,p2 = get_corners(i3+1,r3)
                if side > 0: p0,p1,p2,p3 = p1,p0,p3,p2
                self.gvert3.update_corners_zip(p0,p1,p2,p3)
            else:
                p0,p1 = get_corners(i0-1,l_radii[1])
                p3,p2 = get_corners(i0+1,r0)
                if side > 0: p0,p1,p2,p3 = p1,p0,p3,p2
                self.gvert0.update_corners_zip(p0,p1,p2,p3)
                
                p0,p1 = get_corners(i3+1,l_radii[-2])
                p3,p2 = get_corners(i3-1,r3)
                if side < 0: p0,p1,p2,p3 = p1,p0,p3,p2
                self.gvert3.update_corners_zip(p0,p1,p2,p3)
                
        
        self.gvert0.update(do_edges=False)
        self.gvert1.update(do_edges=False)
        self.gvert2.update(do_edges=False)
        self.gvert3.update(do_edges=False)
        
        for ge in self.gvert0.get_gedges_notnone()+self.gvert3.get_gedges_notnone():
            if ge != self: ge.update(debug=debug)
    
    def update_nozip(self, debug=False):
        p0,p1,p2,p3 = self.get_positions()
        r0,r1,r2,r3 = self.get_radii()
        n0,n1,n2,n3 = self.get_normals()
        
        if False:
            # attempting to smooth snapped igverts
            mx     = self.obj.matrix_world
            mxnorm = mx.transposed().inverted().to_3x3()
            mx3x3  = mx.to_3x3()
            imx    = mx.inverted()
            p3d      = [cubic_bezier_blend_t(p0,p1,p2,p3,t/16.0) for t in range(17)]
            snap     = [self.obj.closest_point_on_mesh(imx*p) for p in p3d]
            snap_pos = [mx*pos for pos,norm,idx in snap]
            bez = cubic_bezier_fit_points(snap_pos, min(r0,r3)/20, allow_split=False)
            if bez:
                _,_,p0,p1,p2,p3 = bez[0]
                _,n1,_ = self.obj.closest_point_on_mesh(imx*p1)
                _,n2,_ = self.obj.closest_point_on_mesh(imx*p2)
                n1 = mxnorm*n1
                n2 = mxnorm*n2
        
        #get s_t_map
        if self.n_quads:
            step = 20* self.n_quads
        else:
            step = 100
            
        s_t_map = polystrips_utilities.cubic_bezier_t_of_s_dynamic(p0, p1, p2, p3, initial_step = step )
        
        #l = self.get_length()  <-this is more accurate, but we need consistency
        l = max(s_t_map)
        
        if self.force_count and self.n_quads:
            # force number of segments
            
            # number of segments
            c = 2 * (self.n_quads - 1)
            
            # compute difference for smoothly interpolating radii perpendicular to GEdge
            s = (r3-r0) / float(c+1)
            
            L = c * r0 +  s*(c+1)*c/2  #integer run sum
            os = L - l
            d_os = os/c
            
            # compute interval lengths and ts
            l_widths = [0] + [r0 + s*i - d_os for i in range(c)]
            l_ts = [polystrips_utilities.closest_t_of_s(s_t_map, dist) for w,dist in iter_running_sum(l_widths)]  #pure lenght distribution
        
        else:
            # find "optimal" count for subdividing spline based on radii of two endpoints
            
            cmin,cmax = int(math.floor(l/max(r0,r3))),int(math.floor(l/min(r0,r3)))
            
            c = 0
            for ctest in range(max(4,cmin-2),cmax+2):
                s = (r3-r0) / (ctest-1)
                tot = r0*(ctest+1) + s*(ctest+1)*ctest/2
                if tot > l:
                    break
                if ctest % 2 == 1:
                    c = ctest
            if c <= 1:
                self.cache_igverts = []
                self.n_quads = 3
                return
            
            # compute difference for smoothly interpolating radii
            s = (r3-r0) / float(c-1)
            
            # compute how much space is left over (to be added to each interval)
            tot = r0*(c+1) + s*(c+1)*c/2
            o = l - tot
            oc = o / (c+1)
            
            # compute interval lengths, ts, blend weights
            l_widths = [0] + [r0+oc+i*s for i in range(c+1)]
            l_ts = [p/l for w,p in iter_running_sum(l_widths)]
        
        # compute interval pos, rad, norm, tangent x, tangent y
        l_pos   = [cubic_bezier_blend_t(p0,p1,p2,p3,t) for t in l_ts]
        l_radii = [r0 + i*s for i in range(c+2)]
        
        #Verify smooth radius interpolation
        #print('R0 %f, R3 %f, r0 %f, r3 %f ' % (r0,r3,l_radii[0],l_radii[-1]))
        l_norms = [cubic_bezier_blend_t(n0,n1,n2,n3,t).normalized() for t in l_ts]
        l_tanx  = [cubic_bezier_derivative(p0,p1,p2,p3,t).normalized() for t in l_ts]
        l_tany  = [t.cross(n).normalized() for t,n in zip(l_tanx,l_norms)]
        
        # create igverts!
        self.cache_igverts = [GVert(bpy.data.objects[self.o_name], bpy.data.objects[self.targ_o_name], self.length_scale,p,r,n,tx,ty) for p,r,n,tx,ty in zip(l_pos,l_radii,l_norms,l_tanx,l_tany)]
        if not self.force_count:
            self.n_quads = int((len(self.cache_igverts)+1)/2)
            
        self.l_ts = l_ts

        self.snap_igverts()
        
        self.gvert0.update(do_edges=False)
        self.gvert1.update(do_edges=False)
        self.gvert2.update(do_edges=False)
        self.gvert3.update(do_edges=False)
        
    
    def update(self, debug=False):
        '''
        recomputes interval gverts along gedge
        note: considering only the radii of end points
        note: approx => not snapped to surface
        '''
        
        # update inner gverts so they can be selectable
        self.gvert1.radius = self.gvert0.radius*0.7 + self.gvert3.radius*0.3
        self.gvert2.radius = self.gvert0.radius*0.3 + self.gvert3.radius*0.7
        
        if not self.frozen:
            if self.zip_to_gedge:
                self.update_zip(debug=debug)
            else:
                self.update_nozip(debug=debug)
        
        for zgedge in self.zip_attached:
            zgedge.update(debug=debug)

        for gpatch in self.gpatches:
            gpatch.update();
        
    def snap_igverts(self):
        '''
        snaps already computed igverts to surface of object ob
        '''
        mx = bpy.data.objects[self.o_name].matrix_world
        mxnorm = mx.transposed().inverted().to_3x3()
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        for igv in self.cache_igverts:
            l,n,i = bpy.data.objects[self.o_name].closest_point_on_mesh(imx * igv.position)
            igv.position = mx * l
            igv.normal = (mxnorm * n).normalized()
            igv.tangent_y = igv.normal.cross(igv.tangent_x).normalized()
            igv.snap_pos = igv.position
            igv.snap_norm = igv.normal
            igv.snap_tanx = igv.tangent_x
            igv.snap_tany = igv.tangent_y
        
    
    def is_picked(self, pt):
        for p0,p1,p2,p3 in self.iter_segments(only_visible=True):
            
            c0,c1,c2,c3 = p0-pt,p1-pt,p2-pt,p3-pt
            n = (c0-c1).cross(c2-c1)
            if c1.cross(c0).dot(n)>0 and c2.cross(c1).dot(n)>0 and c3.cross(c2).dot(n)>0 and c0.cross(c3).dot(n)>0:
                return True
        return False
    
    def iter_segments(self, only_visible=False):
        l = len(self.cache_igverts)
        if l == 0:
            cur0,cur1 = self.gvert0.get_corners_of(self)
            cur2,cur3 = self.gvert3.get_corners_of(self)
            if not only_visible or (self.gvert0.is_visible() and self.gvert3.is_visible()):
                yield (cur0,cur1,cur2,cur3)
            return
        
        prev0,prev1 = None,None
        for i,gvert in enumerate(self.cache_igverts):
            if i%2 == 0: continue
            
            if i == 1:
                gv0 = self.gvert0
                cur0,cur1 = gv0.get_corners_of(self)
            elif i == l-2:
                gv3 = self.gvert3
                cur1,cur0 = gv3.get_corners_of(self)
            else:
                cur0 = gvert.position+gvert.tangent_y*gvert.radius
                cur1 = gvert.position-gvert.tangent_y*gvert.radius
            
            if prev0 and prev1:
                if not only_visible or gvert.is_visible():
                    yield (prev0,cur0,cur1,prev1)
            prev0,prev1 = cur0,cur1
    
    def iter_igverts(self):
        l = len(self.cache_igverts)
        if l == 0: return
        
        prev0,prev1 = None,None
        for i,gvert in enumerate(self.cache_igverts):
            if i%2 == 0: continue
            
            if i == 1:
                continue
            elif i == l-2:
                continue
            else:
                yield (i,gvert)



class GPatch(object):
    def __init__(self, obj, ge0, ge1, ge2, ge3):
        # TODO: allow multiple gedges per side!!
        
        self.o_name = obj.name
        
        self.ge0 = ge0
        self.ge1 = ge1
        self.ge2 = ge2
        self.ge3 = ge3
        
        # attach gedge to gpatch
        self.ge0.attach_gpatch(self)
        self.ge1.attach_gpatch(self)
        self.ge2.attach_gpatch(self)
        self.ge3.attach_gpatch(self)
        
        # should the gedges be reversed?
        self.rev0 = self.ge0.gvert0 in [self.ge1.gvert0, self.ge1.gvert3]
        self.rev1 = self.ge1.gvert0 in [self.ge2.gvert0, self.ge2.gvert3]
        self.rev2 = self.ge2.gvert0 in [self.ge3.gvert0, self.ge3.gvert3]
        self.rev3 = self.ge3.gvert0 in [self.ge0.gvert0, self.ge0.gvert3]
        
        self.inside = True # (not self.rev0 and self.ge0.gvert3.gedge1==self.ge0) or (self.rev0 and self.ge0.gvert0.gedge1==self.ge0)
        
        self.assert_correctness()
        
        self.frozen = False
        
        # make sure opposite gedges have same count
        count02 = max(self.ge0.get_count(), self.ge2.get_count())
        count13 = max(self.ge1.get_count(), self.ge3.get_count())
        self.ge0.set_count(count02)
        self.ge2.set_count(count02)
        self.ge1.set_count(count13)
        self.ge3.set_count(count13)
        
        self.pts = []
        self.map_pts = {}
        self.visible = {}
        
        self.update()
    
    def is_frozen(self): return self.frozen
    
    def assert_correctness(self):
        cps0 = self.ge0.gverts()
        cps1 = self.ge1.gverts()
        cps2 = self.ge2.gverts()
        cps3 = self.ge3.gverts()
        
        if self.rev0:     cps0 = list(reversed(cps0))
        if self.rev1:     cps1 = list(reversed(cps1))
        if not self.rev2: cps2 = list(reversed(cps2))
        if not self.rev3: cps3 = list(reversed(cps3))
        
        assert cps0[0] == cps3[0]
        assert cps0[3] == cps1[0]
        assert cps2[0] == cps3[3]
        assert cps2[3] == cps1[3]
    
    def disconnect(self):
        self.ge0.detach_gpatch(self)
        self.ge1.detach_gpatch(self)
        self.ge2.detach_gpatch(self)
        self.ge3.detach_gpatch(self)
        
        self.ge0 = None
        self.ge1 = None
        self.ge2 = None
        self.ge3 = None
        
    
    def set_count(self, ge):
        if ge == self.ge0:
            self.ge2.set_count(ge.n_quads)
        elif ge == self.ge1:
            self.ge3.set_count(ge.n_quads)
        elif ge == self.ge2:
            self.ge0.set_count(ge.n_quads)
        elif ge == self.ge3:
            self.ge1.set_count(ge.n_quads)
        self.update()
    
    def iter_segments02(self):
        segs0 = list(p.position for i,p in enumerate(self.ge0.cache_igverts) if i%2==1)
        segs2 = list(p.position for i,p in enumerate(self.ge2.cache_igverts) if i%2==1)
        
        if self.rev0:
            segs0 = reversed(segs0)
        if not self.rev2:
            segs2 = reversed(segs2)
        
        return zip(segs0,segs2)
    
    def iter_segments13(self):
        segs1 = list(p.position for i,p in enumerate(self.ge1.cache_igverts) if i%2==1)
        segs3 = list(p.position for i,p in enumerate(self.ge3.cache_igverts) if i%2==1)
        
        if self.rev1:
            segs1 = reversed(segs1)
        if not self.rev3:
            segs3 = reversed(segs3)
        
        return zip(segs1,segs3)
    
    def update(self):
        if self.frozen: return
        
        mx = bpy.data.objects[self.o_name].matrix_world
        imx = mx.inverted()
        mxnorm = imx.transposed().to_3x3()
        mx3x3 = mx.to_3x3()
        
        cps0,lts0 = self.ge0.gverts(),self.ge0.l_ts
        cps1,lts1 = self.ge1.gverts(),self.ge1.l_ts
        cps2,lts2 = self.ge2.gverts(),self.ge2.l_ts
        cps3,lts3 = self.ge3.gverts(),self.ge3.l_ts
        
        if self.rev0:
            cps0 = list(reversed(cps0))
            lts0 = [ 1-v for v in reversed(lts0)]
            
        if self.rev1:
            cps1 = list(reversed(cps1))
            lts1 = [ 1-v for v in reversed(lts1)]
            
        if not self.rev2:
            cps2 = list(reversed(cps2))
            lts2 = [ 1-v for v in reversed(lts2)]
            
        if not self.rev3:
            cps3 = list(reversed(cps3))
            lts3 = [ 1-v for v in reversed(lts3)]
        
        #          e0
        #     0/0 1 2 3/0           00 01 02 03
        # e3  1         1  e1       10 11 12 13
        #     2         2           20 21 22 23
        #     3/0 1 2 3/3           30 31 32 33
        #          e2
        
        v00,v01,v02,v03 = cps0
        _  ,v13,v23,_   = cps1
        _  ,v10,v20,_   = cps3
        v30,v31,v32,v33 = cps2
        
        self.assert_correctness()
        
        v00,v01,v02,v03 = v00.position,v01.position,v02.position,v03.position
        v13,v23,v10,v20 = v13.position,v23.position,v10.position,v20.position
        v30,v31,v32,v33 = v30.position,v31.position,v32.position,v33.position
        
        v11 = ( (v10*2/3+v13*1/3) + (v01*2/3+v31*1/3) )/2
        v12 = ( (v10*1/3+v13*2/3) + (v02*2/3+v32*1/3) )/2
        v21 = ( (v20*2/3+v23*1/3) + (v01*1/3+v31*2/3) )/2
        v22 = ( (v20*1/3+v23*2/3) + (v02*1/3+v32*2/3) )/2
        
        lc0 = list(self.ge0.iter_segments())
        idx0 =  (0,1) if (self.rev0==self.inside) else (3,2)
        lc0 = [lc0[0][idx0[0]]] + list(_c[idx0[1]] for _c in lc0)
        if self.rev0: lc0.reverse()
        
        lc1 = list(self.ge1.iter_segments())
        idx1 =  (0,1) if (self.rev1==self.inside) else (3,2)
        lc1 = [lc1[0][idx1[0]]] + list(_c[idx1[1]] for _c in lc1)
        if self.rev1: lc1.reverse()
        
        lc2 = list(self.ge2.iter_segments())
        idx2 =  (0,1) if (self.rev2==self.inside) else (3,2)
        lc2 = [lc2[0][idx2[0]]] + list(_c[idx2[1]] for _c in lc2)
        if not self.rev2: lc2.reverse()
        
        lc3 = list(self.ge3.iter_segments())
        idx3 =  (0,1) if (self.rev3==self.inside) else (3,2)
        lc3 = [lc3[0][idx3[0]]] + list(_c[idx3[1]] for _c in lc3)
        if not self.rev3: lc3.reverse()
        
        sz0 = len(self.ge0.cache_igverts)
        sz1 = len(self.ge1.cache_igverts)
        
        if len(lc0) != len(lc2):
            # defer update for a bit
            return
        if len(lc1) != len(lc3):
            return
        
        self.pts = []
        for i0 in range(1,sz0,2):
            for i1 in range(1,sz1,2):
                if i1 == 1:
                    self.pts += [(i0,i1,lc0[(i0-1)//2])]
                    continue
                if i0 == sz0-2:
                    self.pts += [(i0,i1,lc1[(i1-1)//2])]
                    continue
                if i1 == sz1-2:
                    self.pts += [(i0,i1,lc2[(i0-1)//2])]
                    continue
                if i0 == 1:
                    self.pts += [(i0,i1,lc3[(i1-1)//2])]
                    continue
                
                p0 = i0 / (sz0-1)
                p1 = i1 / (sz1-1)
                p02 = lts0[i0]*(1-p1) + lts2[i0]*p1
                p13 = lts1[i1]*p0 + lts3[i1]*(1-p0)
                
                p = cubic_bezier_surface_t(v00,v01,v02,v03, v10,v11,v12,v13, v20,v21,v22,v23, v30,v31,v32,v33, p02,p13)
                l,n,i = bpy.data.objects[self.o_name].closest_point_on_mesh(imx * p)
                p = mx * l
                self.pts += [(i0,i1,p)]
        
        self.map_pts = {(i0,i1):p for (i0,i1,p) in self.pts }
        
    
    def is_picked(self, pt):
        for (p0,p1,p2,p3) in self.iter_segments(only_visible=True):
            c0,c1,c2,c3 = p0-pt,p1-pt,p2-pt,p3-pt
            n = (c0-c1).cross(c2-c1)
            d0,d1,d2,d3 = c1.cross(c0).dot(n),c2.cross(c1).dot(n),c3.cross(c2).dot(n),c0.cross(c3).dot(n)
            if d0>0 and d1>0 and d2>0 and d3>0:
                return True
        return False
    
    def iter_segments(self, only_visible=False):
        l0,l1 = len(self.ge0.cache_igverts),len(self.ge1.cache_igverts)
        for i0 in range(1,l0-2,2):
            for i1 in range(1,l1-2,2):
                lidxs = [(i0+0,i1+0),(i0+2,i1+0),(i0+2,i1+2),(i0+0,i1+2)]
                if not all(self.visible[idx] for idx in lidxs):
                    continue
                p0 = self.map_pts[lidxs[0]]
                p1 = self.map_pts[lidxs[1]]
                p2 = self.map_pts[lidxs[2]]
                p3 = self.map_pts[lidxs[3]]
                yield (p0,p1,p2,p3)
    
    def normal(self):
        n = Vector()
        for p0,p1,p2,p3 in self.iter_segments():
            n += (p3-p0).cross(p1-p0).normalized()
        return n.normalized()
        
    def update_visibility(self, r3d):
        lp = [p for _,_,p in self.pts]
        lv = common_utilities.ray_cast_visible(lp, bpy.data.objects[self.o_name], r3d)
        self.visible = {(pt[0],pt[1]):v for pt,v in zip(self.pts,lv)}


class PolyStrips(object):
    def __init__(self, context, obj, targ_obj):
        settings = common_utilities.get_settings()
        
        self.o_name = obj.name
        self.targ_o_name =targ_obj.name
        self.length_scale = get_object_length_scale(bpy.data.objects[self.o_name])
        
        # graph vertices and edges
        self.gverts = []
        self.gedges = []
        self.gpatches = []
        self.extension_geometry = []
        
    def disconnect_gpatch(self, gpatch):
        assert gpatch in self.gpatches
        gpatch.disconnect()
        self.gpatches = [gp for gp in self.gpatches if gp != gpatch]
    
    def disconnect_gedge(self, gedge):
        assert gedge in self.gedges
        for gp in list(gedge.gpatches):
            self.disconnect_gpatch(gp)
        gedge.disconnect()
        self.gedges = [ge for ge in self.gedges if ge != gedge]
    
    def disconnect_gvert(self, gvert):
        assert gvert in self.gverts
        if gvert.from_mesh:
            self.extension_geometry.append(gvert)
            
        if gvert.gedge0: self.disconnect_gedge(gvert.gedge0)
        if gvert.gedge0: self.disconnect_gedge(gvert.gedge0)
        if gvert.gedge0: self.disconnect_gedge(gvert.gedge0)
        if gvert.gedge0: self.disconnect_gedge(gvert.gedge0)
    
        
            
    def remove_unconnected_gverts(self):
        egvs = set(gv for gedge in self.gedges for gv in gedge.gverts())
        gvs = set(gv for gv in self.gverts if gv.is_unconnected() and gv not in egvs)
        ext_gvs = [gv for gv in self.gverts if gv.from_mesh and gv not in egvs]
        
        for gv in ext_gvs:
            if gv not in self.extension_geometry:
                self.extension_geometry.append(gv)
        
        self.gverts = [gv for gv in self.gverts if gv not in gvs]
    
    def create_gvert(self, co, radius=0.005):
        #if type(co) is not Vector: co = Vector(co)
        p0  = co
        r0  = radius
        n0  = Vector((0,0,1))
        tx0 = Vector((1,0,0))
        ty0 = Vector((0,1,0))
        gv = GVert(bpy.data.objects[self.o_name],bpy.data.objects[self.targ_o_name],self.length_scale,p0,r0,n0,tx0,ty0)
        self.gverts += [gv]
        return gv
    
    def create_gedge(self, gv0, gv1, gv2, gv3):
        ge = GEdge(bpy.data.objects[self.o_name],
                   bpy.data.objects[self.targ_o_name], 
                   self.length_scale, gv0, gv1, gv2, gv3)
        ge.update()
        self.gedges += [ge]
        return ge
    
    def create_gpatch(self, ge0, ge1, ge2, ge3):
        gp = GPatch(bpy.data.objects[self.o_name], ge0, ge1, ge2, ge3)
        gp.update()
        for ge in [ge0,ge1,ge2,ge3]:
            for gp_ in ge.gpatches:
                if gp_ != gp: gp_.update()
        self.gpatches += [gp]
        return gp

    def closest_gedge_to_point(self, p):
        min_i,min_ge,min_t,min_d = -1,None,-1,0
        for i,gedge in enumerate(self.gedges):
            p0,p1,p2,p3 = gedge.get_positions()
            t,d = cubic_bezier_find_closest_t_approx(p0,p1,p2,p3,p)
            if min_i==-1 or d < min_d:
                min_i,min_ge,min_t,min_d = i,gedge,t,d
        return (min_i,min_ge, min_t, min_d)
    
    def update_visibility(self, r3d):
        for gv in self.gverts:
            gv.update_visibility(r3d)
        for ge in self.gedges:
            ge.update_visibility(r3d)
        for gp in self.gpatches:
            gp.update_visibility(r3d)
    
    def split_gedge_at_t(self, gedge, t, connect_gvert=None):
        if gedge.zip_to_gedge or gedge.zip_attached: return
        
        p0,p1,p2,p3 = gedge.get_positions()
        r0,r1,r2,r3 = gedge.get_radii()
        cb0,cb1 = cubic_bezier_split(p0,p1,p2,p3, t, self.length_scale)
        rm = cubic_bezier_blend_t(r0,r1,r2,r3, t)
        
        if connect_gvert:
            gv_split = connect_gvert
            trans = cb0[3] - gv_split.position
            for ge in gv_split.get_gedges_notnone():
                ge.get_inner_gvert_at(gv_split).position += trans
            gv_split.position += trans
        else:
            gv_split = self.create_gvert(cb0[3], radius=rm)
        
        gv0_0 = gedge.gvert0
        gv0_1 = self.create_gvert(cb0[1], radius=rm)
        gv0_2 = self.create_gvert(cb0[2], radius=rm)
        gv0_3 = gv_split
        
        gv1_0 = gv_split
        gv1_1 = self.create_gvert(cb1[1], radius=rm)
        gv1_2 = self.create_gvert(cb1[2], radius=rm)
        gv1_3 = gedge.gvert3
        
        # want to *replace* gedge with new gedges
        lgv0ge = gv0_0.get_gedges()
        lgv3ge = gv1_3.get_gedges()
        
        self.disconnect_gedge(gedge)
        ge0 = self.create_gedge(gv0_0,gv0_1,gv0_2,gv0_3)
        ge1 = self.create_gedge(gv1_0,gv1_1,gv1_2,gv1_3)
        
        lgv0ge = [ge0 if ge==gedge else ge for ge in lgv0ge]
        lgv3ge = [ge1 if ge==gedge else ge for ge in lgv3ge]
        gv0_0.gedge0,gv0_0.gedge1,gv0_0.gedge2,gv0_0.gedge3 = lgv0ge
        gv1_3.gedge0,gv1_3.gedge1,gv1_3.gedge2,gv1_3.gedge3 = lgv3ge
        
        gv0_0.update()
        gv1_3.update()
        gv_split.update()
        gv_split.update_gedges()
        
        return (ge0,ge1,gv_split)

    def insert_gedge_between_gverts(self, gv0, gv3):
        gv1 = self.create_gvert(gv0.position*0.7 + gv3.position*0.3, radius=gv0.radius*0.7 + gv3.radius*0.3)
        gv2 = self.create_gvert(gv0.position*0.3 + gv3.position*0.7, radius=gv0.radius*0.3 + gv3.radius*0.7)
        return self.create_gedge(gv0,gv1,gv2,gv3)
    
    def extension_geometry_from_bme(self, bme):
        self.extension_geometry = []
        mx = bpy.data.objects[self.targ_o_name].matrix_world
        for f in bme.faces:
            if len(f.edges) != 4:
                continue
            for ed in f.edges:
                if len(ed.link_faces) < 2:
                    pos = mx * f.calc_center_median()
                    no = mx.transposed().inverted().to_3x3() * f.normal  #TEST THIS....can it be right?
                    no.normalize()
                    rad = 1/3 * 1/8 * sum(mx.to_scale()) * f.calc_perimeter()  #HACK...better way to estimate rad?
                    tan_x = mx * f.verts[1].co - mx * f.verts[0].co
                    tan_x.normalize()
                    tan_y = no.cross(tan_x)
                    
                    
                    gv = GVert(bpy.data.objects[self.o_name], bpy.data.objects[self.targ_o_name], self.length_scale, pos, rad, no, tan_x, tan_y, from_mesh = True)
                    #Freeze Corners
                    #Note, left handed Gvert order wrt to Normal
                    gv.corner0 = mx * f.verts[0].co 
                    gv.corner0_ind = f.verts[0].index
                    gv.corner1 = mx * f.verts[3].co
                    gv.corner1_ind = f.verts[3].index
                    gv.corner2 = mx * f.verts[2].co
                    gv.corner2_ind = f.verts[2].index
                    gv.corner3 = mx * f.verts[1].co
                    gv.corner3_ind = f.verts[1].index
                    
                    
                    
                    gv.snap_pos = gv.position
                    gv.snap_norm = gv.normal
                    gv.visible = True
                    gv.from_mesh_ind = f.index
                    self.extension_geometry.append(gv)
                    break
        
    def insert_gedge_from_stroke(self, stroke, only_ends, sgv0=None, sgv3=None, depth=0):
        '''
        stroke: list of tuples (3d location, radius)
        yikes....pressure and radius need to be reconciled!
        for now, assumes 
        '''
        if depth == 0:
            gv0 = [gv for gv in self.extension_geometry if gv.is_picked(stroke[0][0])]
            gv3 = [gv for gv in self.extension_geometry if gv.is_picked(stroke[-1][0])]
            
            if len(gv0):
                self.extension_geometry.remove(gv0[0])
                self.gverts.append(gv0[0])
                sgv0 = gv0[0]
            if len(gv3):
                self.extension_geometry.remove(gv3[0])
                self.gverts.append(gv3[0])
                sgv3 = gv3[0]
            
        assert depth < 10
        
        spc = '  '*depth + '- '
        
        # subsample stroke using linear interpolation if we have too few samples
        if len(stroke) <= 1:
            dprint(spc+'Too few samples in stroke to subsample')
            return
        # uniform subsampling
        while len(stroke) <= 40:
            stroke = [stroke[0]] + [nptpr for ptpr0,ptpr1 in zip(stroke[:-1],stroke[1:]) for nptpr in [((ptpr0[0]+ptpr1[0])/2,(ptpr0[1]+ptpr1[1])/2), ptpr1]]
        # non-uniform/detail subsampling
        done = False
        while not done:
            done = True
            nstroke = [stroke[0]]
            for ptpr0,ptpr1 in zip(stroke[:-1],stroke[1:]):
                pt0,pr0 = ptpr0
                pt1,pr1 = ptpr1
                if (pt0-pt1).length > (pr0+pr1)/20:
                    nstroke += [((pt0+pt1)/2, (pr0+pr1)/2)]
                nstroke += [ptpr1]
            done = (len(stroke) == len(nstroke))
            stroke = nstroke
        
        if sgv0 and sgv0==sgv3 and sgv0.count_gedges() >= 3:
            dprint(spc+'cannot connect stroke to same gvert (too many gedges)')
            sgv3 = None
        
        r0,r3 = stroke[0][1],stroke[-1][1]
        
        threshold_tooshort     = (r0+r3)/2 / 4
        threshold_junctiondist = (r0+r3)/2 * 2
        threshold_splitdist    = (r0+r3)/2 / 2
        
        tot_length = sum((s0[0]-s1[0]).length for s0,s1 in zip(stroke[:-1],stroke[1:]))
        dprint(spc+'stroke cnt: %i, len: %f; sgv0: %s; sgv3: %s; only_ends: %s' % (len(stroke),tot_length,'t' if sgv0 else 'f', 't' if sgv3 else 'f', 't' if only_ends else 'f'))
        if tot_length < threshold_tooshort and not (sgv0 and sgv3):
            dprint(spc+'Stroke too short (%f)' % tot_length)
            return
        
        
        # self intersection test
        min_i0,min_i1,min_dist = -1,-1,float('inf')
        for i0,info0 in enumerate(stroke):
            pt0,pr0 = info0
            # find where we start to be far enough away
            i1 = i0+1
            while i1 < len(stroke):
                pt1,pr1 = stroke[i1]
                if (pt0-pt1).length > (pr0+pr1): break
                i1 += 1
            while i1 < len(stroke):
                pt1,pr1 = stroke[i1]
                d = (pt0-pt1).length - min(pr0,pr1)
                if d < min_dist:
                    min_i0 = i0
                    min_i1 = i1
                    min_dist = d
                i1 += 1
        
        if min_dist < 0:
            i0 = min_i0
            i1 = min_i1
            
            pt0,pr0 = stroke[i0]
            pt1,pr1 = stroke[i1]
            
            # create gvert at intersecting points and recurse!
            gv_intersect = self.create_gvert(pt0, radius=pr0)
            def find_not_picking(i_start, i_direction):
                i = i_start
                while i >= 0 and i < len(stroke):
                    if not gv_intersect.is_picked(stroke[i][0]): return i
                    i += i_direction
                return -1
            i00 = find_not_picking(i0,-1)
            i01 = find_not_picking(i0, 1)
            i10 = find_not_picking(i1,-1)
            i11 = find_not_picking(i1, 1)
            dprint(spc+'stroke self intersection %i,%i => %i,%i,%i,%i' % (i0,i1,i00,i01,i10,i11))
            if i00 != -1:
                dprint(spc+'seg 0')
                self.insert_gedge_from_stroke(stroke[:i00], only_ends, sgv0=sgv0, sgv3=gv_intersect, depth=depth+1)
            if i01 != -1 and i10 != -1:
                dprint(spc+'seg 1')
                self.insert_gedge_from_stroke(stroke[i01:i10], only_ends, sgv0=gv_intersect, sgv3=gv_intersect, depth=depth+1)
            if i11 != -1:
                dprint(spc+'seg 2')
                self.insert_gedge_from_stroke(stroke[i11:], only_ends, sgv0=gv_intersect, sgv3=sgv3, depth=depth+1)
            return
        
        
        # TODO: self intersection tests!
        # check for self-intersections
        #for i0,info0 in enumerate(stroke):
        #    pt0,pr0 = info0
        #    for i1,info1 in enumerate(stroke):
        #        if i1 <= i0: continue
        #        pt1,pr1 = info1
        
        
        def threshold_distance_stroke_point(stroke, gvert, only_ends):
            if only_ends:
                # check first end
                i0,i1 = threshold_distance_stroke_point(stroke, gvert, False)
                if i0 == -1 and i1 != -1:
                    return (i0,i1)
                # check second end
                rstroke = list(stroke)
                rstroke.reverse()
                i0,i1 = threshold_distance_stroke_point(rstroke, gvert, False)
                if i0 == -1 and i1 != -1:
                    i0,i1 = (len(stroke)-1)-i1,-1
                    return (i0,i1)
                # endpoints not close enough
                return (-1,-1)
            
            min_i0,min_i1 = -1,-1
            was_close = False
            for i,info in enumerate(stroke):
                pt,pr = info
                is_close = gvert.is_picked(pt)
                if i == 0: was_close = is_close
                if not was_close and is_close:
                    min_i0 = i
                if was_close and not is_close:
                    min_i1 = i
                    break
                was_close = is_close
            return (min_i0,min_i1)
        
        def find_stroke_crossing(gedge, stroke):
            strokesegs = list(zip(stroke[:-1],stroke[1:]))
            
            def line_segment_intersection(a0,a1, b0,b1, z):
                '''
                3d line segment "intersection" testing
                
                returns None if no intersection occurs or a tuple specifying
                point of intersection and distances from a0->a1 and b0->b1
                
                note: this function projects to x,y plane perpendicular to given z
                      and then ignores (to a degree) any deviation off the plane in
                      order to find "intersection" of skewed line segments that are
                      "close enough"
                '''
                x = (b1-b0).normalized()
                y = z.cross(x)
                
                oa0,oa1,ob0,ob1 = a0,a1,b0,b1
                la1a0 = (a1-a0).length
                
                a0b0 = a0-b0
                a1b0 = a1-b0
                
                if abs(z.dot(a0b0)) > la1a0 and abs(z.dot(a1b0)) > la1a0: return None
                
                a0 = Vector((x.dot(a0b0), y.dot(a0b0)))
                a1 = Vector((x.dot(a1b0), y.dot(a1b0)))
                b1 = Vector(((b1-b0).length,0))
                b0 = Vector((0,0))
                
                va1a0 = a1 - a0
                da1a0 = va1a0.normalized()
                
                dist = a0.y / -da1a0.y
                if dist < 0 or dist > la1a0: return None
                
                cross = a0 + da1a0*dist
                if cross.x < 0 or cross.x > b1.x: return None
                
                #return (oa0+(oa1-oa0).normalized()*dist, dist, cross.x)
                return (ob0+(ob1-ob0).normalized()*cross.x, dist, cross.x)
            
            def find_crossing(lps):
                tot = sum((i0[0]-i1[0]).length for i0,i1 in zip(lps[:-1],lps[1:]))
                t = 0
                for i0,i1 in zip(lps[:-1],lps[1:]):
                    p0,r0,y0 = i0
                    p1,r1,y1 = i1
                    if r0 == 0: r0 = r1
                    
                    p0 = p0 + y0 * r0
                    p1 = p1 + y1 * r1
                    
                    z = (p1-p0).cross(y0).normalized()
                    
                    for i,strokeseg in enumerate(strokesegs):
                        pt0,pr0 = strokeseg[0]
                        pt1,pr1 = strokeseg[1]
                        
                        cross = line_segment_intersection(pt0,pt1, p0,p1, z)
                        if not cross: continue
                        
                        ptc,dpt,dp = cross
                        
                        started_inside = y0.dot(pt1-pt0)>0
                        
                        dprint(spc+'crosses: %i, %f/%f, started_inside=%s' % (i, t+dp,tot,started_inside))
                        return (i, (t+dp)/tot, started_inside)
                    
                    t += (p1-p0).length
                return None
            
            odds = [gv for i,gv in enumerate(gedge.cache_igverts) if i%2==1]
            cross0 = find_crossing([(gv.position,gv.radius, gv.tangent_y) for gv in odds])
            cross1 = find_crossing([(gv.position,gv.radius,-gv.tangent_y) for gv in odds])
            
            return sorted([x for x in [cross0,cross1] if x], key=lambda x: x[0])
        
        for i_gedge,gedge in enumerate(self.gedges):
            # check if we're close to either endpoint of gedge
            for i_gv,gv in [(0,gedge.gvert0),(3,gedge.gvert3)]:
                is_joined = False
                min_i0,min_i1 = threshold_distance_stroke_point(stroke, gv, only_ends)
                #dprint(spc+'%i.%i: min = %i, %i; gv.count = %i' % (i_gedge,i_gv,min_i0,min_i1,gv.count_gedges()))
                if min_i0 != -1 and gv.count_gedges() < 4:
                    dprint(spc+'Joining gedge[%i].gvert%i; Joining stroke at 0-%i' % (i_gedge,i_gv,min_i0))
                    self.insert_gedge_from_stroke(stroke[:min_i0], only_ends, sgv0=sgv0, sgv3=gv, depth=depth+1)
                    is_joined = True
                if min_i1 != -1 and gv.count_gedges() < 4:
                    dprint(spc+'Joining gedge[%i].gvert%i; Joining stroke at %i-%i' % (i_gedge,i_gv,min_i1,len(stroke)-1))
                    self.insert_gedge_from_stroke(stroke[min_i1:], only_ends, sgv0=gv, sgv3=sgv3, depth=depth+1)
                    is_joined = True
                if is_joined: return
            
            if only_ends:          continue         # do not split gedges when caller wants only ends
            
            if gedge.zip_to_gedge: continue         # do not split zippered gedges!
            if gedge.zip_attached: continue         # do not split zippered gedges!
            
            # check if stroke crosses any gedges
            crosses = find_stroke_crossing(gedge, stroke)
            if not crosses: continue
            
            p0,p1,p2,p3 = gedge.get_positions()
            
            num_crosses = len(crosses)
            t = sum(_t for _i,_t,_d in crosses) / num_crosses           # compute average crossing point
            dprint(spc+'stroke crosses %i gedge %ix [%s], t=%f' % (i_gedge, num_crosses, ','.join('(%i,%f,%s)'%x for x in crosses), t))
            
            cb_split = cubic_bezier_split(p0,p1,p2,p3, t, self.length_scale)
            assert len(cb_split) == 2, 'Could not split bezier (' + (','.join(str(p) for p in [p0,p1,p2,p3])) + ') at %f' % t
            cb0,cb1 = cb_split
            rm = (r0+r3)/2  #stroke radius
            rm_prime = polystrips_utilities.cubic_bezier_blend_t(gedge.gvert0.radius, gedge.gvert1.radius, gedge.gvert2.radius, gedge.gvert3.radius, t)
            
            gv_split = self.create_gvert(cb0[3], radius=rm_prime)
            gv0_0    = gedge.gvert0
            gv0_1    = self.create_gvert(cb0[1], radius=rm)
            gv0_2    = self.create_gvert(cb0[2], radius=rm)
            gv0_3    = gv_split
            gv1_0    = gv_split
            gv1_1    = self.create_gvert(cb1[1], radius=rm)
            gv1_2    = self.create_gvert(cb1[2], radius=rm)
            gv1_3    = gedge.gvert3
            
            self.disconnect_gedge(gedge)
            ge0 = self.create_gedge(gv0_0,gv0_1,gv0_2,gv0_3)
            ge1 = self.create_gedge(gv1_0,gv1_1,gv1_2,gv1_3)
            
            gv0_0.update()
            gv0_0.update_gedges()
            gv_split.update()
            gv_split.update_gedges()
            gv1_3.update()
            gv1_3.update_gedges()
            
            # debugging printout
            if (ge0.gvert1.position-ge0.gvert0.position).length == 0: dprint(spc+'ge0.der0 = 0')
            if (ge0.gvert2.position-ge0.gvert3.position).length == 0: dprint(spc+'ge0.der3 = 0')
            if (ge1.gvert1.position-ge1.gvert0.position).length == 0: dprint(spc+'ge1.der0 = 0')
            if (ge1.gvert2.position-ge1.gvert3.position).length == 0: dprint(spc+'ge1.der3 = 0')
            
            i0 = crosses[0][0]
            if num_crosses == 1:
                if crosses[0][2]:
                    # started stroke inside
                    if sgv0: dprint(spc+'Warning: sgv0 is not None!!')
                    self.insert_gedge_from_stroke(stroke[i0+1:], only_ends, sgv0=gv_split, sgv3=sgv3, depth=depth+1)
                else:
                    # started stroke outside
                    if sgv3: dprint(spc+'Warning: sgv3 is not None!!')
                    self.insert_gedge_from_stroke(stroke[:i0+0], only_ends, sgv0=sgv0, sgv3=gv_split, depth=depth+1)
                return
            
            i1 = crosses[1][0]+1
            self.insert_gedge_from_stroke(stroke[:i0], only_ends, sgv0=sgv0, sgv3=gv_split, depth=depth+1)
            self.insert_gedge_from_stroke(stroke[i1:], only_ends, sgv0=gv_split, sgv3=sgv3, depth=depth+1)
            return
            
        
        dprint(spc+'creating gedge!')
        l_bpts = cubic_bezier_fit_points([pt for pt,pr in stroke], min(r0,r3) / 20, force_split=(sgv0==sgv3 and sgv0))
        pregv,fgv = None,None
        for i,bpts in enumerate(l_bpts):
            t0,t3,bpt0,bpt1,bpt2,bpt3 = bpts
            if i == 0:
                gv0 = self.create_gvert(bpt0, radius=r0) if not sgv0 else sgv0
                fgv = gv0
            else:
                gv0 = pregv
            
            gv1 = self.create_gvert(bpt1,radius=(r0+r3)/2)
            gv2 = self.create_gvert(bpt2,radius=(r0+r3)/2)
            
            if i == len(l_bpts)-1:
                gv3 = self.create_gvert(bpt3, radius=r3) if not sgv3 else sgv3
            else:
                gv3 = self.create_gvert(bpt3, radius=r3)
            
            if (gv1.position-gv0.position).length == 0: dprint('gv01.der = 0')
            if (gv2.position-gv3.position).length == 0: dprint('gv32.der = 0')
            if (gv0.position-gv3.position).length == 0:
                dprint(spc+'gv03.der = 0')
                dprint(spc+str(l_bpts))
                dprint(spc+(str(sgv0.position) if sgv0 else 'None'))
                dprint(spc+(str(sgv3.position) if sgv3 else 'None'))
            else:
                self.create_gedge(gv0,gv1,gv2,gv3)
            pregv = gv3
            gv0.update()
            gv0.update_gedges()
        gv3.update()
        gv3.update_gedges()
        
    def dissolve_gvert(self, gvert, tessellation=20):
        if not (gvert.is_endtoend() or gvert.is_ljunction()):
            print('Cannot dissolve GVert with %i connections' % gvert.count_gedges())
            return
        
        gedge0 = gvert.gedge0
        gedge1 = gvert.gedge1 if gvert.gedge1 else gvert.gedge2
        
        p00,p01,p02,p03 = gedge0.get_positions()
        p10,p11,p12,p13 = gedge1.get_positions()
        
        pts0 = [cubic_bezier_blend_t(p00,p01,p02,p03,i/tessellation) for i in range(tessellation+1)]
        pts1 = [cubic_bezier_blend_t(p10,p11,p12,p13,i/tessellation) for i in range(tessellation+1)]
        if gedge0.gvert0 == gvert: pts0.reverse()
        if gedge1.gvert3 == gvert: pts1.reverse()
        pts = pts0 + pts1
        
        t0,t3,p0,p1,p2,p3 = cubic_bezier_fit_points(pts, self.length_scale, allow_split=False)[0]
        
        gv0 = gedge0.gvert3 if gedge0.gvert0 == gvert else gedge0.gvert0
        gv1 = self.create_gvert(p1, gvert.radius)
        gv2 = self.create_gvert(p2, gvert.radius)
        gv3 = gedge1.gvert3 if gedge1.gvert0 == gvert else gedge1.gvert0
        
        self.disconnect_gedge(gedge0)
        self.disconnect_gedge(gedge1)
        self.create_gedge(gv0,gv1,gv2,gv3)
        gv0.update()
        gv0.update_gedges()
        gv3.update()
        gv3.update_gedges()
    
    def create_mesh(self, bme):
        mx = bpy.data.objects[self.o_name].matrix_world
        imx = mx.inverted()
        
        verts = []
        quads = []
        non_quads = []
        
        igv_corner_vind = {}    # maps (igv,corner) to idx into verts
        ige_side_lvind  = {}    # maps (ige,side) to list of vert indices
        
        gv_idx = {gv:i for i,gv in enumerate(self.gverts)}
        ge_idx = {ge:i for i,ge in enumerate(self.gedges)}
        
        def create_non_quad(indices):
            non_quads.append(tuple(indices))
            
        def create_quad(iv0,iv1,iv2,iv3):
            '''
            indices are in presumptive BMesh index
            '''
            quads.append((iv0,iv1,iv2,iv3))
        
        def insert_vert(v):
            verts.append(imx*v)
            return len(verts)-1
        
        def create_Gvert(gv):
            i_gv = gv_idx[gv]
            if (i_gv,0) in igv_corner_vind: return
            
            
            liv = [insert_vert(p) if i == -1 else i for i,p in zip(gv.get_corner_inds(),gv.get_corners())] #List of Indices(bmesh) for Vertices acronym = liv
            
            
            if gv.zip_over_gedge:
                zip_ge   = gv.zip_over_gedge
                zip_dir  = zip_ge.zip_dir
                zip_side = zip_ge.zip_side
                zip_to   = zip_ge.zip_to_gedge
                zip_0    = (gv==zip_ge.gvert0)
                
                zip_v = (-1 if zip_0 else 1) * zip_dir * zip_side
                
                side_lvind = ige_side_lvind[(ge_idx[zip_to], zip_side)]
                ci0,ci1    = gv.get_side_cornerinds_of(zip_ge, zip_v)
                
                zip_igv = 1+int(gv.zip_igv/2)
                
                dprint('gv.zip_igv = %i, %i' % (gv.zip_igv,zip_igv))
                dprint(side_lvind)
                
                if (zip_0 and zip_dir>0) or (not zip_0 and zip_dir<0): ci0,ci1 = ci1,ci0
                
                liv[ci0] = side_lvind[zip_igv]
                liv[ci1] = side_lvind[zip_igv-1]
            
            igv_corner_vind[(i_gv,0)] = liv[0]  #<----because LIV has BMESH Indices, igv_corner_
            igv_corner_vind[(i_gv,1)] = liv[1]
            igv_corner_vind[(i_gv,2)] = liv[2]
            igv_corner_vind[(i_gv,3)] = liv[3]
            
            if -1 in gv.get_corner_inds():
                create_quad(liv[3],liv[2],liv[1],liv[0])
        
        
        #copy all existing mesh data into our format
        for v in bme.verts:
            insert_vert(mx * v.co)

        for f in bme.faces:
            if len(f.verts) == 4:
                create_quad(*tuple([v.index for v in f.verts]))
            else:
                create_non_quad([v.index for v in f.verts])
        
        
        done = set()                    # set of gedges that have been created
        defering = set(self.gedges)     # set of gedges that still need to be created
        while defering:
            working,defering = defering,set()
            
            for ge in working:
                if any(gv.zip_over_gedge and gv.zip_over_gedge.zip_to_gedge not in done for gv in [ge.gvert0,ge.gvert3]):
                    # defer gedge for now, because it is not ready to be created, yet
                    defering |= {ge}
                    continue
                
                create_Gvert(ge.gvert0)
                create_Gvert(ge.gvert3)
                
                i_ge = ge_idx[ge]
                l = len(ge.cache_igverts)
                
                i0 = gv_idx[ge.gvert0]
                i3 = gv_idx[ge.gvert3]
                i00,i01 = ge.gvert0.get_cornerinds_of(ge)           #  inside index of gvert0
                i02,i03 = ge.gvert0.get_back_cornerinds_of(ge)      # outside index of gvert0
                i32,i33 = ge.gvert3.get_cornerinds_of(ge)           #  inside index of gvert3
                i30,i31 = ge.gvert3.get_back_cornerinds_of(ge)      # outside index of gvert3
                
                c0,c3 = igv_corner_vind[(i0,i00)], igv_corner_vind[(i3,i33)]
                c1,c2 = igv_corner_vind[(i0,i01)], igv_corner_vind[(i3,i32)]
                
                ige_side_lvind[(i_ge, 1)] = [igv_corner_vind[(i0,i03)], c0]
                ige_side_lvind[(i_ge,-1)] = [igv_corner_vind[(i0,i02)], c1]
                
                if not ge.zip_to_gedge:
                    # creating non-zipped gedge
                    if l == 0:
                        # no segments
                        create_quad(c0,c1,c2,c3)
                    else:
                        cc0,cc1 = c0,c1
                        for i,gvert in enumerate(ge.cache_igverts):
                            if i%2 == 0: continue                       # even == quad centers
                            if i == 1:   continue                       # ignore first (generate quad with i-2 and i)
                            
                            if i == l-2:
                                cc2 = c2
                                cc3 = c3
                            else:
                                p2 = gvert.position-gvert.tangent_y*gvert.radius
                                p3 = gvert.position+gvert.tangent_y*gvert.radius
                                p2 = mx * bpy.data.objects[self.o_name].closest_point_on_mesh(imx*p2)[0]
                                p3 = mx * bpy.data.objects[self.o_name].closest_point_on_mesh(imx*p3)[0]
                                cc2 = insert_vert(p2)
                                cc3 = insert_vert(p3)
                            
                            create_quad(cc0, cc1, cc2, cc3)
                            if i < l-2:
                                ige_side_lvind[(i_ge, 1)] += [cc3]
                                ige_side_lvind[(i_ge,-1)] += [cc2]
                            
                            cc0,cc1 = cc3,cc2
                    
                
                #elif i == len(ge.cache_igverts) - 1 and ge.force_count:
                    #print('did the funky math')
                    #p2, p3 = ge.gvert3.get_corners_of(ge)
                    #cc2, cc3 = verts.index(imx * p2), verts.index(imx * p3)
                else:
                    # creating zippered gedge
                    i_zge  = ge_idx[ge.zip_to_gedge]
                    lzvind = ige_side_lvind[(i_zge,ge.zip_side)]
                    i_zgv0 = 1+int(ge.gvert0.zip_igv/2)
                    i_zgv3 = 1+int(ge.gvert3.zip_igv/2)
                    
                    if i_zgv0 < i_zgv3:
                        lzvind = lzvind[i_zgv0:i_zgv3+1]
                    else:
                        lzvind = lzvind[i_zgv3:i_zgv0+1]
                        lzvind.reverse()
                    
                    dprint('lzvind (%i) = %s' % (len(lzvind),str(lzvind)))
                    dprint('l = %i' % l)
                    
                    lzvind = lzvind[1:-1]
                    cc0,cc1 = c0,c1
                    for i,gvert in enumerate(ge.cache_igverts):
                        if i%2 == 0: continue
                        if i == 1:   continue
                        i_z = int((i-3)/2)
                        
                        if i == l-2:
                            cc2,cc3 = c2,c3
                        else:
                            if ge.zip_side*ge.zip_dir == 1:
                                p3 = gvert.position+gvert.tangent_y*gvert.radius
                                p3 = mx * bpy.data.objects[self.o_name].closest_point_on_mesh(imx*p3)[0]
                                cc3 = insert_vert(p3)
                                cc2 = lzvind[i_z]
                            else:
                                p2 = gvert.position-gvert.tangent_y*gvert.radius
                                p2 = mx * bpy.data.objects[self.o_name].closest_point_on_mesh(imx*p2)[0]
                                cc2 = insert_vert(p2)
                                cc3 = lzvind[i_z]
                        
                        dprint('new quad: %i %i %i %i' % (cc0,cc1,cc2,cc3))
                        create_quad(cc0, cc1, cc2, cc3)
                        if i < l-2:
                            ige_side_lvind[(i_ge, 1)] += [cc3]
                            ige_side_lvind[(i_ge,-1)] += [cc2]
                        
                        cc0,cc1 = cc3,cc2
                    
                
                
                ige_side_lvind[(i_ge, 1)] += [c3, igv_corner_vind[(i3,i30)]]
                ige_side_lvind[(i_ge,-1)] += [c2, igv_corner_vind[(i3,i31)]]
                
                # mark gedge as done
                done |= {ge}

        map_i0i1_vert = {}
        for gp in self.gpatches:
            i_ge0 = self.gedges.index(gp.ge0)
            i_ge1 = self.gedges.index(gp.ge1)
            i_ge2 = self.gedges.index(gp.ge2)
            i_ge3 = self.gedges.index(gp.ge3)
            sz0 = gp.ge0.n_quads
            sz1 = gp.ge1.n_quads
            print('sz: ' + str(sz0) + ' ' + str(sz1))
            for i0,i1,p in gp.pts:
                if i0%2 == 0 or i1%2 == 0: continue
                i0 = (i0-1)//2
                i1 = (i1-1)//2
                if i0 == 0:
                    i = i1+1 if gp.rev3 else sz1-1-i1
                    mto = ige_side_lvind[(i_ge3,1 if gp.rev3==gp.inside else -1)][i]
                    map_i0i1_vert[(i0,i1)] = mto
                    continue
                if i0 == sz0-2:
                    i = i1+1 if not gp.rev1 else sz1-1-i1
                    mto = ige_side_lvind[(i_ge1,1 if gp.rev1==gp.inside else -1)][i]
                    map_i0i1_vert[(i0,i1)] = mto
                    continue
                if i1 == 0:
                    i = i0+1 if not gp.rev0 else sz0-1-i0
                    mto = ige_side_lvind[(i_ge0,1 if gp.rev0==gp.inside else -1)][i]
                    map_i0i1_vert[(i0,i1)] = mto
                    continue
                if i1 == sz1-2:
                    i = i0+1 if gp.rev2 else sz0-1-i0
                    mto = ige_side_lvind[(i_ge2,1 if gp.rev2==gp.inside else -1)][i]
                    map_i0i1_vert[(i0,i1)] = mto
                    continue
                
                map_i0i1_vert[(i0,i1)] = insert_vert(p)
                print(map_i0i1_vert[(i0,i1)])
            for i0 in range(0,sz0-2):
                for i1 in range(0,sz1-2):
                    cc0 = map_i0i1_vert[(i0+0,i1+0)]
                    cc1 = map_i0i1_vert[(i0+1,i1+0)]
                    cc2 = map_i0i1_vert[(i0+1,i1+1)]
                    cc3 = map_i0i1_vert[(i0+0,i1+1)]
                    print('new quad(%i,%i): %i %i %i %i' % (i0,i1,cc0,cc1,cc2,cc3))
                    if not gp.inside:
                        create_quad(cc0,cc1,cc2,cc3)
                    else:
                        create_quad(cc0,cc3,cc2,cc1)
        
        # remove unused verts and remap quads
        vind_used = [False for v in verts]
        for q in quads:
            for vind in q:
                vind_used[vind] = True
        i_new = 0
        map_vinds = {}
        for i_vind,used in enumerate(vind_used):
            if used:
                map_vinds[i_vind] = i_new
                i_new += 1
        verts = [v for u,v in zip(vind_used,verts) if u]
        quads = [tuple(map_vinds[vind] for vind in q) for q in quads]
        
        return (verts,quads,non_quads)
    
    def rip_gvert(self, gvert):
        '''
        rips all connected gedges at gvert (duplicates given gvert)
        '''
        if gvert.is_unconnected(): return
        l_gedges = gvert.get_gedges_notnone()
        for ge in l_gedges:
            ngv = gvert.clone_detached()
            l_gv = [ngv if gv==gvert else gv for gv in ge.gverts()]
            self.disconnect_gedge(ge)
            self.create_gedge(*l_gv)
            self.gverts += [ngv]
    
    def rip_gedge(self, gedge, at_gvert=None):
        '''
        rips gedge at both ends or at given gvert (if specified)
        '''
        
        if at_gvert:
            # detach gedge at the specified at_gvert
            assert gedge.gvert0 == at_gvert or gedge.gvert3 == at_gvert
            ngv = at_gvert.clone_detached()
            l_gv = [ngv if gv==at_gvert else gv for gv in gedge.gverts()]
            self.disconnect_gedge(gedge)
            self.create_gedge(*l_gv)
            self.gverts += [ngv]
            return ngv
        
        # detach gedge at both ends
        ngv0 = gedge.gvert0.clone_detached()
        ngv3 = gedge.gvert3.clone_detached()
        l_gv = [ngv0 if gv==gedge.gvert0 else ngv3 if gv==gedge.gvert3 else gv for gv in gedge.gverts()]
        self.disconnect_gedge(gedge)
        nge = self.create_gedge(*l_gv)
        self.gverts += [ngv0,ngv3]
        return nge
    
    def merge_gverts(self, gvert0, gvert1):
        '''
        merge gvert0 into gvert1
        '''
        l_ge = gvert0.get_gedges_notnone()
        for ge in l_ge:
            l_gv = [gvert1 if gv==gvert0 else gv for gv in ge.gverts()]
            self.disconnect_gedge(ge)
            self.create_gedge(*l_gv)
        self.gverts = [gv for gv in self.gverts if gv!=gvert0]
        gvert1.update_gedges()
        return gvert1



