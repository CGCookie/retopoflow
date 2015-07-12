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
from ..lib.common_utilities import iter_running_sum, dprint, get_object_length_scale, profiler, AddonLocator,frange
from ..lib.common_utilities import zip_pairs, closest_t_of_s, closest_t_and_distance_point_to_line_segment
from ..lib.common_utilities import sort_objects_by_angles, vector_angle_between

from ..lib.common_bezier import cubic_bezier_blend_t, cubic_bezier_derivative, cubic_bezier_fit_points, cubic_bezier_split, cubic_bezier_t_of_s_dynamic


class EPVert:
    def __init__(self, position):
        self.position  = position
        self.snap_pos  = position
        self.snap_norm = Vector()
        self.visible = True
        self.epedges = []
        self.isinner = False
        self.doing_update = False
        self.update()
    
    def snap(self):
        p,n,_ = EdgePatches.getClosestPoint(self.position)
        self.snap_pos  = p
        self.snap_norm = n
    
    def update(self, do_edges=True):
        if self.doing_update: return
        
        pr = profiler.start()
        self.snap()
        if do_edges:
            self.doing_update = True
            for epedge in self.epedges:
                epedge.update()
            self.doing_update = False
        pr.done()
    
    def update_epedges(self):
        for epe in self.epedges:
            epe.update()
    
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
    
    def disconnect_epedge(self, epedge):
        assert epedge in self.epedges, 'Attempting to disconnect unconnected EPEdge'
        pr = profiler.start()
        self.epedges = [epe for epe in self.epedges if epe != epedge]
        self.update_epedges()
        pr.done()
    
    def is_inner(self): return self.isinner
    
    def is_picked(self, pt, maxdist=0.1):
        if not self.visible: return False
        return (pt-self.snap_pos).length < maxdist


class EPEdge:
    def __init__(self, epvert0, epvert1, epvert2, epvert3):
        self.epvert0 = epvert0
        self.epvert1 = epvert1
        self.epvert2 = epvert2
        self.epvert3 = epvert3
        
        self.l_ts = []
        self.eppatches = []
        
        self.curve_verts = []
        
        epvert0.connect_epedge(self)
        epvert1.connect_epedge_inner(self)
        epvert2.connect_epedge_inner(self)
        epvert3.connect_epedge(self)
        
        self.update()
    
    def epverts(self): return (self.epvert0, self.epvert1, self.epvert2, self.epvert3)
    
    def update(self):
        p0,p1,p2,p3 = self.get_positions()
        self.curve_verts = [cubic_bezier_blend_t(p0, p1, p2, p3, i / 100.0) for i in range(101)]
        self.curve_verts = [EdgePatches.getClosestPoint(p)[0] for p in self.curve_verts]
    
    def get_positions(self):
        return (self.epvert0.snap_pos, self.epvert1.snap_pos, self.epvert2.snap_pos, self.epvert3.snap_pos)
    
    def get_inner_epvert_at(self, epv03):
        assert self.epvert0 == epv03 or self.epvert3 == epv03, 'Attempting to get inner EPVert of EPEdge for not connected EPVert'
        return self.epvert1 if self.epvert0 == epv03 else self.epvert2
    
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
    
    def replace_epvert(self, epvert_from, epvert_to):
        assert self.epvert0==epvert_from or self.epvert1==epvert_from or self.epvert2==epvert_from or self.epvert3==epvert_from
        assert self.epvert0!=epvert_to and self.epvert1!=epvert_to and self.epvert2!=epvert_to and self.epvert2!=epvert_to
        if   self.epvert0==epvert_from: self.epvert0 = epvert_to
        elif self.epvert1==epvert_from: self.epvert1 = epvert_to
        elif self.epvert2==epvert_from: self.epvert2 = epvert_to
        elif self.epvert3==epvert_from: self.epvert3 = epvert_to
        epvert_from.disconnect_epedge(self)
        epvert_to.connect_epedge(self)


class EPPatch:
    pass



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
        self.eppatches = []
        
        epv0 = self.create_epvert(Vector((-1.0,-0.2,0)))
        epv1 = self.create_epvert(Vector((-0.9,0.5,-0.2)))
        epv2 = self.create_epvert(Vector(( 0.9,0.5,-0.2)))
        epv3 = self.create_epvert(Vector(( 1.0,-0.2,0)))
        epe = self.create_epedge(epv0, epv1, epv2, epv3)
    
    @classmethod
    def getSrcObject(cls):
        return bpy.data.objects[EdgePatches.src_name]
    
    @classmethod
    def getClosestPoint(cls, p):
        ''' returns (p,n,i) '''
        mx  = EdgePatches.matrix
        imx = EdgePatches.matrixinv
        mxn = EdgePatches.matrixnorm
        obj = EdgePatches.getSrcObject()
        
        pr = profiler.start()
        c,n,i = obj.closest_point_on_mesh(imx * p)
        pr.done()
        
        return (mx*c,mxn*n,i)
    
    def create_epvert(self, pos):
        epv = EPVert(pos)
        self.epverts.append(epv)
        return epv
    
    def create_epedge(self, epv0, epv1, epv2, epv3):
        epe = EPEdge(epv0, epv1, epv2, epv3)
        self.epedges.append(epe)
        return epe
    
    def disconnect_eppatch(self, eppatch):
        print('EdgePatches.disconnect_eppatch not implemented!')
    
    def disconnect_epedge(self, epedge):
        assert epedge in self.epedges
        for gp in list(epedge.eppatches):
            self.disconnect_eppatch(gp)
        epedge.disconnect()
        self.epedges = [epe for epe in self.epedges if epe != epedge]
        
    
    def split_epedge_at_t(self, epedge, t, connect_epvert=None):
        p0,p1,p2,p3 = gedge.get_positions()
        cb0,cb1 = cubic_bezier_split(p0,p1,p2,p3, t, self.length_scale)
        
        if connect_epvert:
            epv_split = connect_epvert
            trans = cb0[3] - epv_split.position
            for ge in epv_split.get_gedges_notnone():
                ge.get_inner_epvert_at(epv_split).position += trans
            epv_split.position += trans
        else:
            epv_split = self.create_gvert(cb0[3])
        
        epv0_0 = gedge.epvert0
        epv0_1 = self.create_epvert(cb0[1])
        epv0_2 = self.create_epvert(cb0[2])
        epv0_3 = epv_split
        
        epv1_0 = epv_split
        epv1_1 = self.create_epvert(cb1[1])
        epv1_2 = self.create_epvert(cb1[2])
        epv1_3 = gedge.epvert3
        
        # want to *replace* gedge with new gedges
        lepv0epe = epv0_0.get_epedges()
        lepv3epe = epv1_3.get_epedges()
        
        self.disconnect_epedge(gedge)
        epe0 = self.create_epedge(epv0_0,epv0_1,epv0_2,epv0_3)
        epe1 = self.create_epedge(epv1_0,epv1_1,epv1_2,epv1_3)
        
        #lgv0ge = [ge0 if ge==gedge else ge for ge in lgv0ge]
        #lgv3ge = [ge1 if ge==gedge else ge for ge in lgv3ge]
        #gv0_0.gedge0,gv0_0.gedge1,gv0_0.gedge2,gv0_0.gedge3 = lgv0ge
        #gv1_3.gedge0,gv1_3.gedge1,gv1_3.gedge2,gv1_3.gedge3 = lgv3ge
        
        epv0_0.update()
        epv1_3.update()
        epv_split.update()
        epv_split.update_gedges()
        
        return (epe0,epe1,epv_split)
    
    def insert_epedge_between_epverts(self, epv0, epv3):
        epv1 = self.create_epvert(epv0.position*0.7 + epv3.position*0.3, radius=epv0.radius*0.7 + epv3.radius*0.3)
        epv2 = self.create_epvert(epv0.position*0.3 + epv3.position*0.7, radius=epv0.radius*0.3 + epv3.radius*0.7)
        return self.create_epedge(epv0,epv1,epv2,epv3)
    
    
    def insert_gedge_from_stroke(self, stroke, only_ends, sepv0=None, sepv3=None, depth=0):
        '''
        stroke: list of tuples (3d location, radius)
        yikes....pressure and radius need to be reconciled!
        for now, assumes 
        '''
        pts = [p for p,_ in stroke]
        lbez = cubic_bezier_fit_points(pts, (pts[0]-pts[1]).length / 10)
        epv0 = None
        for t0,t3,p0,p1,p2,p3 in lbez:
            if epv0 is None:
                epv0 = self.create_epvert(p0)
            else:
                epv0 = epv3
            epv1 = self.create_epvert(p1)
            epv2 = self.create_epvert(p2)
            epv3 = self.create_epvert(p3)
            epe = self.create_epedge(epv0, epv1, epv2, epv3)

    def merge_epverts(self, epvert0, epvert1):
        ''' merge epvert0 into epvert1 '''
        l_epe = list(epvert0.epedges)
        for epe in l_epe:
            epe.replace_epvert(epvert0, epvert1)
        self.epverts = [epv for epv in self.epverts if epv != epvert0]
        epvert1.update_epedges()
        return epvert1




