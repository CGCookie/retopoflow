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

import bpy
import math
from math import sin, cos
import time
import copy
from mathutils import Vector, Quaternion, kdtree
from mathutils.geometry import intersect_point_line, intersect_line_plane
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d, region_2d_to_origin_3d
import bmesh
import blf, bgl
import itertools

from ..lib import common_utilities
from ..lib.common_utilities import iter_running_sum, dprint, get_object_length_scale,frange
from ..lib.common_utilities import zip_pairs, closest_t_of_s
from ..lib.common_utilities import sort_objects_by_angles, vector_angle_between
from ..lib.classes.profiler.profiler import Profiler

from ..lib.common_bezier import cubic_bezier_blend_t, cubic_bezier_derivative, cubic_bezier_fit_points, cubic_bezier_split, cubic_bezier_t_of_s_dynamic
from ..cache import mesh_cache




###############################################################################################################
# GVert

class GVert:
    def __init__(self, obj, targ_obj, length_scale, position, radius, normal, tangent_x, tangent_y, from_mesh = False):
        
        # store info
        self.o_name       = obj.name
        self.targ_o_name  = targ_obj.name
        self.length_scale = length_scale
        self.mx = obj.matrix_world
        
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
        self.from_mesh_ind = -1 # index of face, needs to be set explicitly
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
    def is_inner(self): return (self.gedge_inner is not None)
    
    def is_fromMesh(self):    return (self.from_mesh_ind != -1)
    
    def count_gedges(self):   return len(self.get_gedges_notnone())
    
    def is_unconnected(self): return not (self.has_0() or self.has_1() or self.has_2() or self.has_3())
    def is_endpoint(self):    return self.has_0() and not (self.has_1() or self.has_2() or self.has_3())
    def is_endtoend(self):    return self.has_0() and self.has_2() and not (self.has_1() or self.has_3())
    def is_ljunction(self):   return self.has_0() and self.has_1() and not (self.has_2() or self.has_3())
    def is_tjunction(self):   return self.has_0() and self.has_1() and self.has_3() and not self.has_2()
    def is_cross(self):       return self.has_0() and self.has_1() and self.has_2() and self.has_3()
    
    def freeze(self): self.frozen = True
    def thaw(self):
        self.frozen = False
        for ge in self.get_gedges_notnone():
            ge.thaw()
        self.update()
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
        pr = Profiler().start()
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
        
        pr = Profiler().start()
        
        norm = self.snap_norm
        
        l_gedges = self.get_gedges_notnone()
        l_vecs   = [ge.get_derivative_at(self).normalized() for ge in l_gedges]
        #if any(v.length == 0 for v in l_vecs): print(l_vecs)
        #l_vecs = [v if v.length else Vector((1,0,0)) for v in l_vecs]
        l_gedges = sort_objects_by_angles(norm, l_gedges, l_vecs)
        l_vecs   = [ge.get_derivative_at(self).normalized() for ge in l_gedges]
        #if any(v.length == 0 for v in l_vecs): print(l_vecs)
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
        pr = Profiler().start()
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
        
        pr = Profiler().start()
        
        mx = self.mx
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        bvh = mesh_cache['bvh']  #any reason not to grab this from our cache, which should always be current.
        
        if Polystrips.settings.symmetry_plane == 'x':
            self.corner0.x = max(0.0, self.corner0.x)
            self.corner1.x = max(0.0, self.corner1.x)
            self.corner2.x = max(0.0, self.corner2.x)
            self.corner3.x = max(0.0, self.corner3.x)
        
        self.corner0 = mx * bvh.find(imx*self.corner0)[0]  #todo...error?
        self.corner1 = mx * bvh.find(imx*self.corner1)[0]
        self.corner2 = mx * bvh.find(imx*self.corner2)[0]
        self.corner3 = mx * bvh.find(imx*self.corner3)[0]
        
        if Polystrips.settings.symmetry_plane == 'x':
            self.corner0.x = max(0.0, self.corner0.x)
            self.corner1.x = max(0.0, self.corner1.x)
            self.corner2.x = max(0.0, self.corner2.x)
            self.corner3.x = max(0.0, self.corner3.x)
            self.position.x = max(0.0,self.position.x)
            self.snap_pos.x = max(0.0,self.snap_pos.x)
        
        pr.done()
    
    def update(self, do_edges=True):
        if self.doing_update: return
        if self.zip_over_gedge and do_edges:
            self.zip_over_gedge.update()
            return
        
        pr = Profiler().start()
        
        bvh = mesh_cache['bvh']
        mx = self.mx
        imx = mx.inverted()
        mxnorm = imx.transposed().to_3x3()
        mx3x3 = mx.to_3x3()
        
        if not self.frozen: # and not self.is_inner():
            l,n,i, d = bvh.find(imx*self.position)
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
        pr = Profiler().start()
        
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
    
    def get_gedge_to_left(self, gedge):
        if self.gedge0 == gedge: return self.gedge1
        if self.gedge1 == gedge: return self.gedge2
        if self.gedge2 == gedge: return self.gedge3
        if self.gedge3 == gedge: return self.gedge0
    def get_gedge_to_right(self, gedge):
        if self.gedge0 == gedge: return self.gedge3
        if self.gedge1 == gedge: return self.gedge0
        if self.gedge2 == gedge: return self.gedge1
        if self.gedge3 == gedge: return self.gedge2
    def get_gedge_straight(self, gedge):
        if self.gedge0 == gedge: return self.gedge2
        if self.gedge1 == gedge: return self.gedge3
        if self.gedge2 == gedge: return self.gedge0
        if self.gedge3 == gedge: return self.gedge1





###############################################################################################################
# GEdge between GVerts

class GEdge:
    '''
    Graph Edge (GEdge) stores end points and "way points" (cubic bezier)
    '''
    def __init__(self, obj, targ_obj, length_scale, gvert0, gvert1, gvert2, gvert3):
        # store end gvertices
        self.o_name = obj.name
        self.mx = obj.matrix_world
        
        self.targ_o_name = targ_obj.name
        self.length_scale = length_scale
        self.gvert0 = gvert0
        self.gvert1 = gvert1
        self.gvert2 = gvert2
        self.gvert3 = gvert3
        
        self.force_count = False
        self.n_quads = None
        
        self.changing_count = False     # indicates if we are in process of changing count
        
        self.zip_to_gedge   = None
        self.zip_side       = 1
        self.zip_dir        = 1
        
        self.zip_attached   = []
        
        self.frozen = False

        self.l_ts = []
        self.gedgeseries = []
        
        # create caching vars
        self.cache_igverts = []             # cached interval gverts
                                            # even-indexed igverts are poly "centers"
                                            #  odd-indexed igverts are poly "edges"
        
        gvert0.connect_gedge(self)
        gvert1.connect_gedge_inner(self)
        gvert2.connect_gedge_inner(self)
        gvert3.connect_gedge(self)
        
        self.from_edges = None
        self.from_build = False
        self.from_mesh  = False
        if gvert0.is_fromMesh() and gvert3.is_fromMesh():
            self.check_fromMesh();
    
    def is_fromMesh(self): return self.from_mesh
    
    def check_fromMesh(self):
        # can we walk from gvert0 to gvert3?
        
        def quad_oppositeEdges(q):
            yield (q.edges[0],q.edges[2])
            yield (q.edges[1],q.edges[3])
            yield (q.edges[2],q.edges[0])
            yield (q.edges[3],q.edges[1])
        def edge_direction(q,e):
            em = (e.verts[0].co + e.verts[1].co) / 2.0
            qm = q.calc_center_median()
            d  = em - qm        # quad center to edge center
            ed = e.verts[1].co - e.verts[0].co
            if d.cross(ed).dot(q.normal) < 0: return -1
            return 1
        
        # build walking data struct
        bm = bmesh.new()
        bm.from_mesh(bpy.data.meshes[self.targ_o_name])
        bm.faces.ensure_lookup_table()
        q0,q1 = bm.faces[self.gvert0.from_mesh_ind],bm.faces[self.gvert3.from_mesh_ind]
        
        bseq = None     # the "best" sequence of edges
        for e0,e1 in quad_oppositeEdges(q0):
            #         | quad | quad | quad | ... | quad |
            #         ^  ^^  ^                      q1
            # search: e0 q0 e1 ->
            # if we find a path from q0 to q1, then bseq will look like
            #               q0 |   q  |   q  |  ...    q1 |
            #     bseq = [ (q0,e) (q, e) (q, e) ...   (q1,e) ]
            lseq = [(q0,e1)]
            while True:
                # | q0 | ... | quad | quad | ... | q1 |
                #               ^^  ^  ^^  ^
                #               qp e0  qn  e1
                qp,e0 = lseq[-1]
                if qp == q1:
                    # (e0 is far side of q1)
                    dprint('found q1!')
                    break
                if e0.is_boundary:
                    dprint('hit boundary; no more polygons to search')
                    break
                # test that e0 has only two link_faces?
                qn = [qo for qo in e0.link_faces if qo != qp][0]
                if qn == q0:
                    dprint('wrapped back around')
                    break
                if len(qn.edges) != 4:
                    dprint('hit non-quad polygon')
                    break
                # find opposite edge
                e1 = None
                for _e0,_e1 in quad_oppositeEdges(qn):
                    if e0 == _e0: e1 = _e1
                assert e1, 'could not find opposite edge' # something unexpected happened
                lseq += [(qn,e1)]
            
            if lseq[-1][0] == q1:
                # we reached q1 by walking the loop!
                if bseq == None or len(lseq) < len(bseq):
                    bseq = lseq
        
        if bseq == None:
            dprint('gedge not from mesh')
            # not from mesh!
            return
        
        def vinds(q,e):
            li = [v.index for v in e.verts]
            if edge_direction(q,e) < 0: li.reverse()
            return li
        
        self.from_mesh   = True
        self.force_count = True
        self.frozen      = True
        self.n_quads     = len(bseq)                    # including q0 and q1
        self.from_edges  = [vinds(q,e) for q,e in bseq]
        self.from_build  = True
        
        dprint('gedge from mesh, len = %d' % (len(bseq)))
    
    def get_count(self):
        l = len(self.cache_igverts)
        if l > 4:
            n_quads = math.floor(l/2) + 1
        else:
            n_quads = 3
        return n_quads
    
    def set_count(self, c):
        c = min(c,50)
        
        if self.frozen:
            # cannot modify count of frozen gedges
            return
        
        if self.force_count and self.n_quads == c:
            # no work to be done
            return
        
        if self.changing_count:
            # already changing!  must be a bad loop
            return
        
        self.changing_count = True
        self.force_count = True
        self.n_quads = c
        for gedgeseries in self.gedgeseries:
            gedgeseries.set_count(c)
        self.changing_count = False
        
        self.update()
        
        
    def unset_count(self):
        if self.frozen:
            return
        if self.fill_to0 or self.fill_to1:
            print('Cannot unset force count when filling')
            return
        self.force_count = False
        self.n_quads = None
        self.update()
    
    def has_endpoint(self, gv): return gv==self.gvert0 or gv==self.gvert3
    def get_other_end(self, gv): return self.gvert0 if gv==self.gvert3 else self.gvert3
    
    def is_zippered(self): return (self.zip_to_gedge != None)
    def has_zippered(self): return len(self.zip_attached)!=0
    
    def freeze(self):
        self.frozen = True
        self.gvert0.freeze()
        self.gvert3.freeze()
    def thaw(self):
        self.frozen = False
        for ges in self.gedgeseries:
            ges.thaw()
        self.update()
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
        return len(self.gedgeseries)
    
    def attach_gedgeseries(self, gedgeseries):
        if len(self.gedgeseries) >= 2:
            print('Cannot attach more than two gpatches')
            return False
        self.gedgeseries.append(gedgeseries)
        return True
    
    def detach_gedgeseries(self, gedgeseries):
        self.gedgeseries.remove(gedgeseries)
        for ges in self.gedgeseries:
            ges.update()
    
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
        mx = self.mx
        bvh = mesh_cache['bvh']
        imx = mx.inverted()
        p3d = [cubic_bezier_blend_t(p0,p1,p2,p3,t/precision) for t in range(precision+1)]
        p3d = [mx*bvh.find(imx * p)[0] for p in p3d]
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
            bvh = mesh_cache['bvh']
            mx     = self.mx
            mxnorm = mx.transposed().inverted().to_3x3()
            mx3x3  = mx.to_3x3()
            imx    = mx.inverted()
            p3d      = [cubic_bezier_blend_t(p0,p1,p2,p3,t/16.0) for t in range(17)]
            snap     = [bvh.find(imx*p) for p in p3d]
            snap_pos = [mx*pos for pos,norm,idx,d in snap]
            bez = cubic_bezier_fit_points(snap_pos, min(r0,r3)/20, allow_split=False)
            if bez:
                _,_,p0,p1,p2,p3 = bez[0]
                _,n1,_,_ = bvh.find(imx*p1)
                _,n2,_,_ = bvh.find(imx*p2)
                n1 = mxnorm*n1
                n2 = mxnorm*n2
        
        #get s_t_map
        if self.n_quads:
            step = 20* self.n_quads
        else:
            step = 100
            
        s_t_map = cubic_bezier_t_of_s_dynamic(p0, p1, p2, p3, initial_step = step )
        
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
            l_ts = [closest_t_of_s(s_t_map, dist) for w,dist in iter_running_sum(l_widths)]  #pure length distribution
        
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
            c = max(3,c)
            
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
            
            if Polystrips.settings.symmetry_plane == 'x':
                # clamp to x-plane
                for igv in self.cache_igverts:
                    p0 = igv.position + igv.tangent_y*igv.radius
                    p1 = igv.position - igv.tangent_y*igv.radius
                    p0.x = max(0.0,p0.x)
                    p1.x = max(0.0,p1.x)
                    igv.position = (p0+p1)/2.0
                    igv.radius = (p0-p1).length/2.0
                    igv.tangent_y = (p0-p1).normalized()
                    
                    igv.snap_pos = igv.position
                    igv.snap_radius = igv.radius
                    igv.snap_tany = igv.tangent_y
        
        elif self.from_mesh:
            if self.from_build:
                m = bpy.data.meshes[self.targ_o_name]
                self.update_nozip(debug=debug)
                for i,igv in enumerate(self.cache_igverts):
                    if i % 2 == 0: continue
                    liv = self.from_edges[int((i-1)/2)]
                    p0,p1 = m.vertices[liv[0]].co,m.vertices[liv[1]].co
                    igv.position = (p0+p1) / 2.0
                    igv.radius = (p0-p1).length / 2.0
                    igv.tangent_y = (p1-p0).normalized()
                    igv.snap_pos = igv.position
                    igv.snap_radius = igv.radius
                    igv.snap_tany = igv.tangent_y
                self.from_build = False
        
        for zgedge in self.zip_attached:
            zgedge.update(debug=debug)

        for ges in self.gedgeseries:
            ges.update()
        
    def snap_igverts(self):
        '''
        snaps already computed igverts to surface of object ob
        '''
        
        thinSurface_maxDist = 0.05
        thinSurface_offset = 0.005
        thinSurface_opposite = -0.4
        
        bvh = mesh_cache['bvh']
        mx = self.mx
        mxnorm = mx.transposed().inverted().to_3x3()
        mx3x3 = mx.to_3x3()
        imx = mx.inverted()
        
        
        dprint('\nsnapping igverts')
        for igv in self.cache_igverts:
            if igv.is_inner(): continue
            l,n,_,_ = bvh.find(imx * igv.position)
            
            # assume that if the snapped norm is pointing opposite to the norms
            # of outer control points of gedge then we've likely snapped to the
            # wrong side of a thin surface.
            d0,d3 = n.dot(self.gvert0.snap_norm),n.dot(self.gvert3.snap_norm)
            dprint('n.dot(gv0.n) = %f, n.dot(gv3.n) = %f' % (d0, d3))
            if d0 < thinSurface_opposite or d3 < thinSurface_opposite:
                dprint('possible thin surface detected. casting ray backwards')
                hit = bvh.ray_cast(l - n * thinSurface_offset, -n, thinSurface_maxDist)
                if hit:
                    lr,nr,_,dr = hit
                    d0,d3 = nr.dot(self.gvert0.snap_norm),nr.dot(self.gvert3.snap_norm)
                    dprint('nr.dot(gv0.n) = %f, nr.dot(gv3.n) = %f, d = %f' % (d0, d3, dr))
                    if d0 >= thinSurface_opposite or d3 >= thinSurface_opposite:
                        # seems reasonable enough
                        l,n = lr,nr
            
            igv.position = mx * l
            
            if Polystrips.settings.symmetry_plane == 'x':
                # clamp to x-plane
                p0 = igv.position + igv.tangent_y*igv.radius
                p1 = igv.position - igv.tangent_y*igv.radius
                p0.x = max(0.0,p0.x)
                p1.x = max(0.0,p1.x)
                igv.position = (p0+p1)/2.0
                igv.snap_radius = (p0-p1).length/2.0
            
            
            igv.normal = (mxnorm * n).normalized()
            igv.tangent_y = igv.normal.cross(igv.tangent_x).normalized()
            igv.snap_pos = igv.position
            igv.snap_norm = igv.normal
            igv.snap_tanx = igv.tangent_x
            igv.snap_tany = igv.tangent_y
    
    
    def is_picked(self, pt):
        for p0,p1,p2,p3 in self.iter_segments():
        #for p0,p1,p2,p3 in self.iter_segments():
            c0,c1,c2,c3 = p0-pt,p1-pt,p2-pt,p3-pt
            n = (c0-c1).cross(c2-c1)
            if c1.cross(c0).dot(n)>0 and c2.cross(c1).dot(n)>0 and c3.cross(c2).dot(n)>0 and c0.cross(c3).dot(n)>0:
                return True
        return False
    
    def iter_segments(self):
        l = len(self.cache_igverts)
        if l == 0:
            cur0,cur1 = self.gvert0.get_corners_of(self)
            cur2,cur3 = self.gvert3.get_corners_of(self)
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



###############################################################################################################
# GEdgeSeries: a collection of GEdges

class GEdgeSeries:
    def __init__(self, obj, *gedges):
        self.o_name = obj.name
        self.mx = obj.matrix_world
        self.gedges = gedges
        self.ngedges = len(gedges)
        self.gpatch = None
        
        self.n_quads = 0
        self.rev = []
        self.cache_igverts = []
        self.cache_rev = []
        self.cache_gedge = []
        
        self.changing_count = False     # indicates if we are in process of changing count
        
        if len(gedges) == 1:
            self.gvert0 = gedges[0].gvert0
            self.gvert3 = gedges[0].gvert3
            self.rev = [False]
        else:
            self.gvert0 = None
            ge0 = gedges[0]
            gv0 = None
            for ge1 in gedges[1:]:
                # find following gvert (next intersection)
                if not self.gvert0:
                    # find gvert in intersection of ge0 and ge1
                    gv1 = ge0.gvert0 if ge0.gvert0 in [ge1.gvert0, ge1.gvert3] else ge0.gvert3
                    # haven't set up gvert0
                    self.gvert0 = ge0.get_other_end(gv1)
                    self.rev = [ge0.gvert0 == gv1]
                self.rev += [ge1.gvert3 == gv1]
                gv1 = ge1.get_other_end(gv1)
                self.gvert3 = gv1
        
        for ge in gedges:
            ge.attach_gedgeseries(self)
    
    def update(self):
        self.cache_igverts = []
        self.cache_rev = []
        self.cache_gedge = []
        self.n_quads = 0
        for ge,rev in zip(self.gedges,self.rev):
            l = list(ge.cache_igverts)
            if rev:
                l.reverse()
            if not self.cache_igverts:
                self.cache_igverts = l
                self.n_quads = ge.n_quads
                self.cache_rev = [rev for i in range(len(l))]
                self.cache_gedge = [(ge,(i-1)//2,rev) for i in range(1,len(l),2)]
            else:
                self.cache_igverts += l[1:]
                self.n_quads += ge.n_quads - 1
                self.cache_rev += [rev for i in range(1,len(l))]
                self.cache_gedge += [(ge,(i-1)//2,rev) for i in range(1,len(l),2)]
        
        #print(self.cache_rev)
        
        if self.gpatch:
            self.gpatch.update()
    
    def get_count(self):
        c = 0
        for ge in self.gedges:
            c += ge.get_count()
        c -= len(self.gedges)-1
        return c
    
    def set_count(self, count):
        #if self.changing_count: return
        if self.n_quads == count: return
        if self.is_frozen(): return
        
        self.changing_count = True
        if len(self.gedges) == 1:
            self.gedges[0].set_count(count)
            self.update()
            if self.gpatch:
                self.gpatch.set_count(self)
        self.changing_count = False
    
    def is_gpatched(self):
        return self.gpatch != None
    
    def attach_gpatch(self, gpatch):
        if self.gpatch:
            #print('Already attached to patch')
            return
        self.gpatch = gpatch
    
    def detach_gpatch(self, gpatch):
        if not self.gpatch:
            #print('Not attached to patch')
            return
        self.gpatch = None
    
    def freeze(self):
        for ge in self.gedges:
            ge.freeze()
    
    def is_frozen(self):
        return any(ge.is_frozen() for ge in self.gedges)
    
    def thaw(self):
        if self.gpatch:
            self.gpatch.thaw()
    
    def disconnect(self):
        for ge in self.gedges:
            ge.detach_gedgeseries(self)
        self.gpatch = None
        self.gedges = []
        self.cache_igverts = []
        self.ngedges = 0
    
    def iter_segments(self):
        l = len(self.cache_igverts)
        if l == 0:
            cur0,cur1 = self.gvert0.get_corners_of(self.gedges[0])
            cur2,cur3 = self.gvert3.get_corners_of(self.gedges[-1])
            yield (cur0,cur1,cur2,cur3)
            return
        
        prev0,prev1 = None,None
        for i,gvert in enumerate(self.cache_igverts):
            if i%2 == 0: continue
            
            if i == 1:
                gv0 = self.gvert0
                cur0,cur1 = gv0.get_corners_of(self.gedges[0])
            elif i == l-2:
                gv3 = self.gvert3
                cur1,cur0 = gv3.get_corners_of(self.gedges[-1])
            else:
                cur0 = gvert.position+gvert.tangent_y*gvert.radius
                cur1 = gvert.position-gvert.tangent_y*gvert.radius
                if self.cache_rev[i]: cur1,cur0 = cur0,cur1
            
            
            if prev0 and prev1:
                yield (prev0,cur0,cur1,prev1)
            prev0,prev1 = cur0,cur1
    
    def get_gedge_info(self, i_quad, rev):
        if rev: i_quad = len(self.cache_gedge)-1 - i_quad
        return self.cache_gedge[i_quad]




###############################################################################################################
# GPatch for handling simple fill

class GPatch:
    def __init__(self, obj, *gedgeseries):
        # TODO: allow multiple gedges per side!!
        
        self.o_name = obj.name
        self.frozen = False
        self.mx = obj.matrix_world
        
        self.gedgeseries = gedgeseries
        self.nsides = len(gedgeseries)
        
        self.count_error = False
        
        # attach gedge to gpatch
        for ges in self.gedgeseries: ges.attach_gpatch(self)
        
        # should the gedges be reversed?
        self.rev = [ges0.gvert3 not in [ges1.gvert0, ges1.gvert3] for ges0,ges1 in zip_pairs(self.gedgeseries)]
        
        # make sure gedges have proper counts
        if self.nsides == 3:
            count = min(ges.get_count() for ges in self.gedgeseries)
            if count%2==1: count += 1
            count = max(count,4)
            for ges in self.gedgeseries: ges.set_count(count)
        
        elif self.nsides == 4:
            if self.gedgeseries[0].is_frozen():
                count02 = self.gedgeseries[0].get_count()
            elif self.gedgeseries[2].is_frozen():
                count02 = self.gedgeseries[2].get_count()
            else:
                count02 = min(self.gedgeseries[0].get_count(), self.gedgeseries[2].get_count())
            if self.gedgeseries[1].is_frozen():
                count13 = self.gedgeseries[1].get_count()
            elif self.gedgeseries[3].is_frozen():
                count13 = self.gedgeseries[3].get_count()
            else:
                count13 = min(self.gedgeseries[1].get_count(), self.gedgeseries[3].get_count())
            self.gedgeseries[0].set_count(count02)
            self.gedgeseries[2].set_count(count02)
            self.gedgeseries[1].set_count(count13)
            self.gedgeseries[3].set_count(count13)
        
        elif self.nsides == 5:
            count0 = self.gedgeseries[0].get_count()-2
            if count0%2==1: count0 += 1
            count0  = max(count0,2)
            if self.gedgeseries[1].is_frozen():
                count14 = self.gedgeseries[1].get_count()
            elif self.gedgeseries[4].is_frozen():
                count14 = self.gedgeseries[4].get_count()
            else:
                count14 = min(self.gedgeseries[1].get_count(), self.gedgeseries[4].get_count())
            self.gedgeseries[0].set_count(count0+2)
            self.gedgeseries[2].set_count(count0//2+2)
            self.gedgeseries[3].set_count(count0//2+2)
            self.gedgeseries[1].set_count(count14)
            self.gedgeseries[4].set_count(count14)
        
        self.quads = []     # list of tuples of inds into self.pts
        self.pts   = []     # list of tuples of (position,visible,lookup), where lookup is either (GEdge,ind_igvert) or None
        
        self.update()
    
    def rotate_pole(self, reverse=False):
        if self.frozen: return
        
        if self.nsides != 5: return
        
        if not reverse:
            self.gedgeseries = self.gedgeseries[1:] + self.gedgeseries[:1]
        else:
            self.gedgeseries = self.gedgeseries[-1:] + self.gedgeseries[:-1]
        self.rev = [ges0.gvert3 not in [ges1.gvert0, ges1.gvert3] for ges0,ges1 in zip_pairs(self.gedgeseries)]
        
        count0 = self.gedgeseries[0].get_count()-2
        if count0%2==1: count0 += 1
        count0 = max(count0,2)
        count14 = max(self.gedgeseries[1].get_count(), self.gedgeseries[4].get_count())
        self.gedgeseries[0].set_count(count0+2)
        self.gedgeseries[2].set_count(count0//2+2)
        self.gedgeseries[3].set_count(count0//2+2)
        self.gedgeseries[1].set_count(count14)
        self.gedgeseries[4].set_count(count14)
        
        self.update()
    
    def freeze(self):
        self.frozen = True
        for ges in self.gedgeseries:
            ges.freeze()
    def thaw(self):
        self.frozen = False
        self.update()
    def is_frozen(self): return self.frozen
    
    def disconnect(self):
        #for ges in self.gedgeseries:
        #    ges.detach_gpatch(self)
        self.gedgeseries = []
        self.rev = []
        self.pts = []
        self.map_pts = {}
        self.visible = {}
    
    def set_count(self, gedgeseries):
        n_quads = gedgeseries.n_quads
        i_gedgeseries = self.gedgeseries.index(gedgeseries)
        if self.nsides == 4:
            self.gedgeseries[(i_gedgeseries+2)%4].set_count(n_quads)
        elif self.nsides == 3:
            for ges in self.gedgeseries:
                ges.set_count(n_quads)
        elif self.nsides == 5:
            if i_gedgeseries == 0:
                n_quads = max(n_quads,4)
                self.gedgeseries[2].set_count((n_quads-2) // 2 + 2)
                self.gedgeseries[3].set_count((n_quads-2) // 2 + 2)
            elif i_gedgeseries == 1:
                self.gedgeseries[4].set_count(gedgeseries.n_quads)
            elif i_gedgeseries == 2:
                self.gedgeseries[3].set_count(n_quads)
                self.gedgeseries[0].set_count((n_quads-2) * 2 + 2)
            elif i_gedgeseries == 3:
                self.gedgeseries[2].set_count(n_quads)
                self.gedgeseries[0].set_count((n_quads-2) * 2 + 2)
            elif i_gedgeseries == 4:
                self.gedgeseries[1].set_count(n_quads)
        
        # self will be updated once the set_count() calls are finished
        #self.update()
    
    def update(self):
        if self.frozen: return
        
        if self.nsides == 3:
            self._update_tri()
        elif self.nsides == 4:
            self._update_quad()
        elif self.nsides == 5:
            self._update_pent()
    
    def _update_tri(self):
        ges0,ges1,ges2 = self.gedgeseries
        rev0,rev1,rev2 = self.rev
        bvh = mesh_cache['bvh']
        closest_point_on_mesh = bvh.find
        sz0,sz1,sz2 = [len(ges.cache_igverts) for ges in self.gedgeseries]
        
        # defer update for a bit (counts don't match up!)
        if sz0 != sz1 or sz1 != sz2:
            self.count_error = True
            return
        
        mx = self.mx
        imx = mx.inverted()
        mxnorm = imx.transposed().to_3x3()
        mx3x3 = mx.to_3x3()
        
        lc0 = list(ges0.iter_segments())
        idx0 =  (0,1) if rev0 else (3,2)
        lc0 = [lc0[0][idx0[0]]] + list(_c[idx0[1]] for _c in lc0)
        if rev0: lc0.reverse()
        
        lc1 = list(ges1.iter_segments())
        idx1 =  (0,1) if rev1 else (3,2)
        lc1 = [lc1[0][idx1[0]]] + list(_c[idx1[1]] for _c in lc1)
        if rev1: lc1.reverse()
        
        lc2 = list(ges2.iter_segments())
        idx2 =  (0,1) if rev2 else (3,2)
        lc2 = [lc2[0][idx2[0]]] + list(_c[idx2[1]] for _c in lc2)
        if not rev2: lc2.reverse()
        
        wid = len(lc0)
        if wid%2==0:
            self.count_error = True
            return
        self.count_error = False
        w2 = (wid-1) // 2
        
        self.pts = []
        self.quads = []
        
        c0,c1,c2 = lc0[w2],lc1[w2],lc2[w2]
        center = (c0+c1+c2)/3.0
        
        # add pts along ge0
        self.pts += [(c,True,(0,i_c)) for i_c,c in enumerate(lc0)]
        for i in range(1,w2+1):
            pi = i/w2
            self.pts += [(lc2[i],True,(2,wid-1-i))]
            cc0 = center*pi + c0*(1-pi)
            for j in range(1,wid-1):
                if j < w2:
                    pj = j/w2
                    p = cc0*pj + lc2[i]*(1-pj)
                else:
                    pj = (j-w2)/w2
                    p = lc1[i]*pj + cc0*(1-pj)
                p = mx * closest_point_on_mesh(imx * p)[0]
                self.pts += [(p,True,None)]
            self.pts += [(lc1[i],True,(1,i))]
        
        # add pts in corner of ge1 and ge2
        chalf = len(self.pts)
        for i in range(w2+1,wid-1):
            pi = (i-w2)/w2
            self.pts += [(lc2[i],True,(2,wid-1-i))]
            cc1 = c1*pi + center*(1-pi)
            for j in range(1,w2):
                pj = j/w2
                p = cc1*pj + lc2[i]*(1-pj)
                p = mx * closest_point_on_mesh(imx * p)[0]
                self.pts += [(p,True,None)]
        for j in range(0,w2):
            self.pts += [(lc1[wid-1-j],True,(1,wid-1-j))]
        
        
        for i in range(w2):
            for j in range(wid-1):
                self.quads += [( (i+0)*wid+(j+0), (i+1)*wid+(j+0), (i+1)*wid+(j+1), (i+0)*wid+(j+1) )]
        
        for i in range(-1,w2-1):
            for j in range(w2-1):
                i0 = chalf + (i+0)*w2+(j+0)
                i1 = chalf + (i+0)*w2+(j+1)
                i2 = chalf + (i+1)*w2+(j+1)
                i3 = chalf + (i+1)*w2+(j+0)
                if i < 0:
                    i0 -= w2+1
                    i1 -= w2+1
                self.quads += [(i0,i3,i2,i1)]
        for i in range(-1,w2-1):
            i0 = chalf + (i+1)*w2+(w2-1)
            i1 = chalf + (i+0)*w2+(w2-1)
            i2 = chalf-w2 + i
            i3 = chalf-w2 + i+1
            if i < 0:
                #i0 -= w2+1
                i1 -= w2+1
            self.quads += [(i0,i3,i2,i1)]
    
    def _update_quad(self):
        bvh = mesh_cache['bvh']
        ges0,ges1,ges2,ges3 = self.gedgeseries
        rev0,rev1,rev2,rev3 = self.rev
        closest_point_on_mesh = bvh.find
        sz0,sz1,sz2,sz3 = [len(ges.cache_igverts) for ges in self.gedgeseries]
        
        # defer update for a bit (counts don't match up!)
        if sz0 != sz2 or sz1 != sz3:
            self.count_error = True
            return
        
        self.count_error = False
        
        mx = self.mx
        imx = mx.inverted()
        mxnorm = imx.transposed().to_3x3()
        mx3x3 = mx.to_3x3()
        
        self.pts = []
        self.quads = []
        
        lc0 = list(ges0.iter_segments())
        idx0 =  (0,1) if rev0 else (3,2)
        lc0 = [lc0[0][idx0[0]]] + list(_c[idx0[1]] for _c in lc0)
        if rev0: lc0.reverse()
        
        lc1 = list(ges1.iter_segments())
        idx1 =  (0,1) if rev1 else (3,2)
        lc1 = [lc1[0][idx1[0]]] + list(_c[idx1[1]] for _c in lc1)
        if rev1: lc1.reverse()
        
        lc2 = list(ges2.iter_segments())
        idx2 =  (0,1) if rev2 else (3,2)
        lc2 = [lc2[0][idx2[0]]] + list(_c[idx2[1]] for _c in lc2)
        if not rev2: lc2.reverse()
        
        lc3 = list(ges3.iter_segments())
        idx3 =  (0,1) if rev3 else (3,2)
        lc3 = [lc3[0][idx3[0]]] + list(_c[idx3[1]] for _c in lc3)
        if not rev3: lc3.reverse()
        
        wid,hei = len(lc0),len(lc1)
        
        for i0,p0 in enumerate(lc0):
            p2 = lc2[i0]
            w1 = i0 / (wid-1)
            w3 = 1.0 - w1
            for i1,p1 in enumerate(lc1):
                p3 = lc3[i1]
                w2 = i1 / (hei-1)
                w0 = 1.0 - w2
                
                if i1 == 0:
                    self.pts += [(p0, True, (0,i0))]
                    continue
                if i0 == len(lc0)-1:
                    self.pts += [(p1, True, (1,i1))]
                    continue
                if i1 == len(lc1)-1:
                    self.pts += [(p2, True, (2,wid-1-i0))]
                    continue
                if i0 == 0:
                    self.pts += [(p3, True, (3,hei-1-i1))]
                    continue
                
                p02 = p0*w0 + p2*w2
                p13 = p1*w1 + p3*w3
                
                w02,w13 = max(w0,w2),max(w1,w3)
                if w02 > w13:
                    w02 = (w02-0.5)**2 * 2 + 0.5
                    w13 = 1.0 - w02
                else:
                    w13 = (w13-0.5)**2 * 2 + 0.5
                    w02 = 1.0 - w13
                
                p = p02*w02 + p13*w13
                p = mx * closest_point_on_mesh(imx * p)[0]
                
                self.pts += [(p, True, None)]
        
        for i0 in range(wid-1):
            for i1 in range(hei-1):
                self.quads += [( (i0+0)*hei+(i1+0), (i0+0)*hei+(i1+1), (i0+1)*hei+(i1+1), (i0+1)*hei+(i1+0) )]
    
    def _update_pent(self):
        bvh = mesh_cache['bvh']
        ges0,ges1,ges2,ges3,ges4 = self.gedgeseries
        rev0,rev1,rev2,rev3,rev4 = self.rev
        closest_point_on_mesh = bvh.find
        sz0,sz1,sz2,sz3,sz4 = [(len(ges.cache_igverts)-1)//2 -1 for ges in self.gedgeseries]
        
        # defer update for a bit (counts don't match up!)
        if sz0 != sz2*2 or sz0 != sz3*2 or sz1 != sz4:
            self.count_error = True
            return
        self.count_error = False
        
        mx = self.mx
        imx = mx.inverted()
        mxnorm = imx.transposed().to_3x3()
        mx3x3 = mx.to_3x3()
        
        self.pts = []
        self.quads = []
        
        lc0 = list(ges0.iter_segments())
        idx0 =  (0,1) if rev0 else (3,2)
        lc0 = [lc0[0][idx0[0]]] + list(_c[idx0[1]] for _c in lc0)
        if rev0: lc0.reverse()
        
        lc1 = list(ges1.iter_segments())
        idx1 =  (0,1) if rev1 else (3,2)
        lc1 = [lc1[0][idx1[0]]] + list(_c[idx1[1]] for _c in lc1)
        if rev1: lc1.reverse()
        
        lc2 = list(ges2.iter_segments())
        idx2 =  (0,1) if rev2 else (3,2)
        lc2 = [lc2[0][idx2[0]]] + list(_c[idx2[1]] for _c in lc2)
        if not rev2: lc2.reverse()
        
        lc3 = list(ges3.iter_segments())
        idx3 =  (0,1) if rev3 else (3,2)
        lc3 = [lc3[0][idx3[0]]] + list(_c[idx3[1]] for _c in lc3)
        if not rev3: lc3.reverse()
        
        lc4 = list(ges4.iter_segments())
        idx4 =  (0,1) if rev4 else (3,2)
        lc4 = [lc4[0][idx4[0]]] + list(_c[idx4[1]] for _c in lc4)
        if not rev4: lc4.reverse()
        
        wid,hei = len(lc0),len(lc1)
        w2 = wid//2
        
        for i0,p0 in enumerate(lc0):
            p23 = lc3[i0] if i0 < w2 else lc2[i0-w2]
            w1 = i0 / (wid-1)
            w4 = 1.0 - w1
            for i1,p1 in enumerate(lc1):
                p4 = lc4[i1]
                w23 = i1 / (hei-1)
                w0 = 1.0 - w23
                
                if i1 == 0:
                    self.pts += [(p0, True, (0,i0))]
                    continue
                if i0 == 0:
                    self.pts += [(p4, True, (4,hei-1-i1))]
                    continue
                if i0 == len(lc0)-1:
                    self.pts += [(p1, True, (1,i1))]
                    continue
                if i1 == len(lc1)-1:
                    if i0 < w2:
                        self.pts += [(p23, True, (3,w2-i0))]
                    else:
                        self.pts += [(p23, True, (2,wid-1-i0))]
                    continue
                
                p023 = p0*w0 + p23*w23
                p14 = p1*w1 + p4*w4
                
                w023,w14 = max(w0,w23),max(w1,w4)
                if w023 > w14:
                    w023 = (w023-0.5)**2 * 2 + 0.5
                    w14  = 1.0 - w023
                else:
                    w14 = (w14-0.5)**2 * 2 + 0.5
                    w023 = 1.0 - w14
                
                p = p023*w023 + p14*w14
                p = mx * closest_point_on_mesh(imx * p)[0]
                
                self.pts += [(p, True, None)]
        
        for i0 in range(wid-1):
            for i1 in range(hei-1):
                self.quads += [( (i0+0)*hei+(i1+0), (i0+0)*hei+(i1+1), (i0+1)*hei+(i1+1), (i0+1)*hei+(i1+0) )]
    
    def get_gedge_from_gedgeseries(self, i_gedgeseries, i_quad):
        ges = self.gedgeseries[i_gedgeseries]
        rev = self.rev[i_gedgeseries]
        return ges.get_gedge_info(i_quad, rev)
    
    def is_picked(self, pt):
        for (p0,p1,p2,p3) in self.iter_segments():
            c0,c1,c2,c3 = p0-pt,p1-pt,p2-pt,p3-pt
            n = (c0-c1).cross(c2-c1)
            d0,d1,d2,d3 = c1.cross(c0).dot(n),c2.cross(c1).dot(n),c3.cross(c2).dot(n),c0.cross(c3).dot(n)
            if d0>0 and d1>0 and d2>0 and d3>0:
                return True
        return False
    
    def iter_segments(self):
        for i0,i1,i2,i3 in self.quads:
            pt0,pt1,pt2,pt3 = self.pts[i0],self.pts[i1],self.pts[i2],self.pts[i3]
            yield (pt0[0],pt1[0],pt2[0],pt3[0])
    
    def normal(self):
        n = Vector()
        for p0,p1,p2,p3 in self.iter_segments():
            n += (p3-p0).cross(p1-p0).normalized()
        return n.normalized()





###############################################################################################################
# Polystrips

class Polystrips(object):
    # class/static variable (shared across all instances)
    settings = None
    
    def __init__(self, context, obj, targ_obj):
        Polystrips.settings = common_utilities.get_settings()
        
        self.o_name = obj.name
        self.mx = obj.matrix_world
        self.targ_o_name =targ_obj.name
        self.length_scale = get_object_length_scale(bpy.data.objects[self.o_name])
        
        # graph vertices and edges
        self.gverts = []
        self.gedges = []
        self.gedgeseries = []
        self.gpatches = []
        self.extension_geometry = []
        
    def disconnect_gpatch(self, gpatch):
        assert gpatch in self.gpatches
        for ges in list(gpatch.gedgeseries):
            ges.disconnect()
            self.gedgeseries.remove(ges)
        gpatch.disconnect()
        self.gpatches = [gp for gp in self.gpatches if gp != gpatch]
    
    def disconnect_gedgeseries(self, gedgeseries):
        assert gedgeseries in self.gedgeseries
        if gedgeseries.gpatch:
            self.disconnect_gpatch(gedgeseries.gpatch)
        gedgeseries.disconnect()
        self.gedgeseries = [ges for ges in self.gedgeseries if ges != gedgeseries]
    
    def disconnect_gedge(self, gedge):
        assert gedge in self.gedges
        for ges in list(gedge.gedgeseries):
            self.disconnect_gedgeseries(ges)
        gedge.disconnect()
        self.gedges = [ge for ge in self.gedges if ge != gedge]
    
    def disconnect_gvert(self, gvert):
        assert gvert in self.gverts
        if gvert.from_mesh:
            self.extension_geometry.append(gvert)
        # repeatedly disconnect gedge until all gedges are disconnected
        while gvert.gedge0:
            self.disconnect_gedge(gvert.gedge0)
        
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
    
    def create_gedgeseries(self, *gedges):
        ges = GEdgeSeries(bpy.data.objects[self.o_name], *gedges)
        ges.update()
        self.gedgeseries += [ges]
        return ges
    
    def create_gpatch(self, *gedgeseries):
        gp = GPatch(bpy.data.objects[self.o_name], *gedgeseries)
        gp.update()
        for ges in gedgeseries:
            if ges.gpatch and ges.gpatch != gp:
                ges.gpatch.update()
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
            gv_split.radius = rm
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
        bme.faces.ensure_lookup_table()
        bme.verts.ensure_lookup_table()
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
                if da1a0.y == 0: return None
                
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
            rm_prime = cubic_bezier_blend_t(gedge.gvert0.radius, gedge.gvert1.radius, gedge.gvert2.radius, gedge.gvert3.radius, t)
            
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
            
            if (gv0.position-gv3.position).length == 0:
                dprint(spc+'gv03.der = 0')
                dprint(spc+str(l_bpts))
                dprint(spc+(str(sgv0.position) if sgv0 else 'None'))
                dprint(spc+(str(sgv3.position) if sgv3 else 'None'))
            elif (gv1.position-gv0.position).length == 0:
                dprint('gv01.der = 0')
            elif (gv2.position-gv3.position).length == 0:
                dprint('gv32.der = 0')
            else:
                self.create_gedge(gv0,gv1,gv2,gv3)
            pregv = gv3
            gv0.update()
            gv0.update_gedges()
        gv3.update()
        gv3.update_gedges()
        
    def dissolve_gvert(self, gvert, tessellation=20):
        if not (gvert.is_endtoend() or gvert.is_ljunction()):
            print('Cannot dissolve junction with %i connections' % gvert.count_gedges())
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
        bvh = mesh_cache['bvh']
        mx = self.mx
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
            if (i_gv,0) in igv_corner_vind:
                # already created this gvert, so return
                return
            
            
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
                # at least one corner (vertex) of gvert has not been created
                create_quad(liv[3],liv[2],liv[1],liv[0])
            else:
                # this gvert existed before
                pass
        
        
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
                    elif ge.is_fromMesh():
                        #ige_side_lvind[(i_ge, 1)] += [c0]
                        #ige_side_lvind[(i_ge,-1)] += [c1]
                        l = len(ge.from_edges)
                        for i,ivs in enumerate(ge.from_edges):
                            if i == 0: continue
                            if i == l-2: continue
                            if i == l-1: continue
                            ige_side_lvind[(i_ge,-1)] += [ivs[0]]
                            ige_side_lvind[(i_ge, 1)] += [ivs[1]]
                        #ige_side_lvind[(i_ge,-1)] += [c2]
                        #ige_side_lvind[(i_ge, 1)] += [c3]
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
                                p2 = mx * bvh.find(imx*p2)[0]
                                p3 = mx * bvh.find(imx*p3)[0]
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
                                p3 = mx * bvh.find(imx*p3)[0]
                                cc3 = insert_vert(p3)
                                cc2 = lzvind[i_z]
                            else:
                                p2 = gvert.position-gvert.tangent_y*gvert.radius
                                p2 = mx * bvh.find(imx*p2)[0]
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

        
        dge_i = {ge:i_ge for i_ge,ge in enumerate(self.gedges)}
        
        for gp in self.gpatches:
            map_ipt_vert = []
            
            for p,_,k in gp.pts:
                if not k:
                    map_ipt_vert += [insert_vert(p)]
                    continue
                
                i_ges,i_v_ges = k
                ge,i_v,rev2 = gp.get_gedge_from_gedgeseries(i_ges, i_v_ges)
                i_ge = dge_i[ge]
                
                rev = gp.rev[i_ges]
                rev3 = rev if not rev2 else not rev
                lverts = ige_side_lvind[(i_ge, -1 if not rev3 else 1)]
                
                idx = (i_v+1) if not rev2 else (len(lverts)-i_v-2)
                
                #print('%d %d %d  len:%d i_v:%d 0:%d 1:%d idx:%d' % (i_ges, i_ge, i_v_ges, len(lverts), i_v, i_v+1, len(lverts)-i_v-2, idx))
                if idx < len(lverts):
                    map_ipt_vert += [lverts[idx]]
                else:
                    map_ipt_vert += [-1]
            
            for li in gp.quads:
                lip = [map_ipt_vert[i] for i in li]
                if any(ip==-1 for ip in lip): continue
                create_quad(*lip)
            
        # remove unused verts and remap quads  <----#likely area of issue #116
        #if a vert is not part of a quad in the existing mesh, it gets removed
        vind_used = [False for v in verts]
        for q in quads + non_quads:
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
    
    def attempt_gpatch(self, gedges):
        if len(gedges) == 0:
            return 'No strips specified'
        
        gedges = list(gedges)
        
        if any(ge.is_zippered() for ge in gedges):
            return 'Cannot create patches with zippered strips'
        
        def getcycle(gedges):
            ge0,gv0 = None,None
            for ge in gedges:
                for gv in [ge.gvert0, ge.gvert3]:
                    ge_ = gv.get_gedge_to_right(ge)
                    if ge_:
                        # found starting point
                        gv0 = ge_.get_other_end(gv)
                        ge0 = ge_
                        break
                if ge0:
                    # found starting point
                    break
            else:
                #print('could not find starting point')
                return None
            sgedges = set(gedges)
            lgedgeseries = []
            gedgeseries = [ge0]
            ge0_ = ge0
            while sgedges:
                ge1 = gv0.get_gedge_to_right(ge0)
                if ge1:
                    if ge1 not in sgedges:
                        #print('found gedge not in selected set')
                        return None
                    # ready to start next gedgeseries
                    lgedgeseries += [gedgeseries]
                    if ge1 == ge0_:
                        if len(sgedges) != 1:
                            #print('not all selected set')
                            return None
                        if ge1 not in sgedges:
                            #print('ending not expected')
                            return None
                        return lgedgeseries
                    gedgeseries = [ge1]
                else:
                    ge1 = gv0.get_gedge_straight(ge0)
                    if not ge1:
                        #print('could not find suitable gedge')
                        return None
                    if ge1 not in sgedges:
                        #print('found gedge not in selected set')
                        return None
                    # add to current gedgeseries
                    gedgeseries += [ge1]
                ge0 = ge1
                gv0 = ge0.get_other_end(gv0)
                sgedges.remove(ge0)
            #print('could not find cycle')
            return None
        cycle = getcycle(gedges)
        if cycle:
            #print('FOUND CYCLE!!')
            return [self.create_gpatch(*[self.create_gedgeseries(*lge) for lge in cycle])]
        
        def walkabout(gedge, gvfrom):
            gefrom = gedge
            lgedges = [gefrom]
            sgvseen = set()
            while True:
                gvto = gefrom.get_other_end(gvfrom)
                if gvto in sgvseen: break
                geto = gvto.get_gedge_to_left(gefrom)
                if not geto: break
                sgvseen.add(gvto)
                lgedges.append(geto)
                gvfrom = gvto
                gefrom = geto
            if lgedges[0] == lgedges[-1] and len(lgedges) > 1:
                lgedges.reverse()
                return (lgedges[1:],True)
            # did not walk all the way around
            gefrom = lgedges[-1]
            gvfrom = gvto
            lgedges = [gefrom]
            while True:
                gvto = gefrom.get_other_end(gvfrom)
                geto = gvto.get_gedge_to_right(gefrom)
                if not geto: break
                lgedges.append(geto)
                gvfrom = gvto
                gefrom = geto
            return (lgedges,False)
        
        map_ge_idx = {ge:i_ge for i_ge,ge in enumerate(self.gedges)}
        def cycle_key(lge):
            # rotate lge to smallest idx
            liges = [map_ge_idx[ge] for ge in lge]
            siiges = liges.index(min(liges))
            liges = liges[siiges:] + liges[:siiges]
            return tuple(liges)
        def noncycle_key(lge):
            return tuple(map_ge_idx[ge] for ge in lge)
        def compute_key(lges, cycle):
            if cycle: return cycle_key(lges)
            return noncycle_key(lges)
        lgp = set(cycle_key([ge for ges in gp.gedgeseries for ge in ges.gedges]) for gp in self.gpatches)
        
        def gvert_in_common(ge0,ge1):
            return ge0.gvert0 if ge0.gvert0 == ge1.gvert0 or ge0.gvert0 == ge1.gvert3 else ge0.gvert3
        
        first = True
        fill_cycles    = set()
        fill_noncycles = set()
        
        for ge in gedges:
            lgedges0,cycle0 = walkabout(ge,ge.gvert0)
            lgedges3,cycle3 = walkabout(ge,ge.gvert3)
            key0,key3 = compute_key(lgedges0,cycle0),compute_key(lgedges3,cycle3)
            
            cycles    = set(k for c,k in [(cycle0,key0),(cycle3,key3)] if c)
            noncycles = set(k for c,k in [(cycle0,key0),(cycle3,key3)] if not c and len(k) in {2,3,4})
            
            cycles -= lgp
            
            if first:
                fill_cycles = cycles
                fill_noncycles = noncycles
                first = False
            else:
                fill_cycles &= cycles
                fill_noncycles &= noncycles
        
        if fill_cycles:
            return [self.create_gpatch(*[self.create_gedgeseries(self.gedges[kv]) for kv in k]) for k in fill_cycles]
            #return [self.create_gpatch(*[self.gedges[kv] for kv in k]) for k in fill_cycles]
        
        if len(gedges) < 2:
            return 'Must select at least two strips to fill a patch'
        
        if not fill_noncycles:
            if len(gedges) == 2 and not any(gedges[0].has_endpoint(gv) for gv in [gedges[1].gvert0,gedges[1].gvert3]):
                # two (possibly) parallel, unconnected edges
                
                ge0,ge1 = gedges
                gv00,gv03 = ge0.gvert0,ge0.gvert3
                gv10,gv13 = ge1.gvert0,ge1.gvert3
                if gv00.is_cross() or gv03.is_cross() or gv10.is_cross() or gv13.is_cross():
                    # no room to attach new gedges
                    return 'Cannot create new GEdges for quad GPatch, because at least one GVert is full'
                
                lgedge,rgedge = ge0,ge1
                tlgvert = lgedge.gvert0
                blgvert = lgedge.gvert3
                
                # create two gedges
                dl = (blgvert.position - tlgvert.position).normalized()
                d0 = (rgedge.gvert0.position - tlgvert.position).normalized()
                d3 = (rgedge.gvert3.position - tlgvert.position).normalized()
                if dl.dot(d0) > dl.dot(d3):
                    trgvert = rgedge.gvert3
                    brgvert = rgedge.gvert0
                else:
                    trgvert = rgedge.gvert0
                    brgvert = rgedge.gvert3
                tgedge = self.insert_gedge_between_gverts(tlgvert, trgvert)
                bgedge = self.insert_gedge_between_gverts(blgvert, brgvert)
                
                if tlgvert.snap_norm.dot((trgvert.snap_pos-tlgvert.snap_pos).cross(blgvert.snap_pos-tlgvert.snap_pos)) < 0:
                    lgedge,bgedge,rgedge,tgedge = lgedge,tgedge,rgedge,bgedge
                
                ges0 = self.create_gedgeseries(lgedge)
                ges1 = self.create_gedgeseries(bgedge)
                ges2 = self.create_gedgeseries(rgedge)
                ges3 = self.create_gedgeseries(tgedge)
                return [self.create_gpatch(ges0, ges1, ges2, ges3)]
            
            return 'Could not determine type of patch. Try selecting different strips'
        
        lgp = []
        for k in fill_noncycles:
            l = len(k)
            if l == 2:
                # two gedges selected adjacent at L-junction.  create fourth gvert and two connecting gedges
                sge0,sge1 = self.gedges[k[0]],self.gedges[k[1]]
                gv1 = gvert_in_common(sge0,sge1)
                gv0 = sge0.get_other_end(gv1)
                gv2 = sge1.get_other_end(gv1)
                if gv0 == gv2:
                    return 'Detected loop with end-to-end junction. Cannot create this type of patch. Change junction to L.'
                sge2 = self.insert_gedge_between_gverts(gv0,gv2)
                ges0 = self.create_gedgeseries(sge0)
                ges1 = self.create_gedgeseries(sge1)
                ges2 = self.create_gedgeseries(sge2)
                lgp += [self.create_gpatch(ges0,ges1,ges2)]
            elif l == 3:
                sge0,sge1,sge2 = self.gedges[k[0]],self.gedges[k[1]],self.gedges[k[2]]
                gv1 = gvert_in_common(sge0,sge1)
                gv0 = sge0.get_other_end(gv1)
                gv2 = gvert_in_common(sge1,sge2)
                gv3 = sge2.get_other_end(gv2)
                if gv0 == gv3:
                    return 'Detected loop with end-to-end junction. Cannot create this type of patch. Change junction to L.'
                sge3 = self.insert_gedge_between_gverts(gv0, gv3)
                ges0 = self.create_gedgeseries(sge0)
                ges1 = self.create_gedgeseries(sge1)
                ges2 = self.create_gedgeseries(sge2)
                ges3 = self.create_gedgeseries(sge3)
                lgp += [self.create_gpatch(ges0,ges1,ges2,ges3)]
            elif l == 4:
                sge0,sge1,sge2,sge3 = [self.gedges[v] for v in k]
                gv1 = gvert_in_common(sge0,sge1)
                gv0 = sge0.get_other_end(gv1)
                gv3 = gvert_in_common(sge2,sge3)
                gv4 = sge3.get_other_end(gv3)
                if gv0 == gv4:
                    return 'Detected loop with end-to-end junction. Cannot create this type of patch. Change junction to L.'
                sge4 = self.insert_gedge_between_gverts(gv0,gv4)
                ges0 = self.create_gedgeseries(sge0)
                ges1 = self.create_gedgeseries(sge1)
                ges2 = self.create_gedgeseries(sge2)
                ges3 = self.create_gedgeseries(sge3)
                ges4 = self.create_gedgeseries(sge4)
                lgp += [self.create_gpatch(ges0,ges1,ges2,ges3,ges4)]
        
        return lgp
