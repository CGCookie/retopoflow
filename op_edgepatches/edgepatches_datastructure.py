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
from ..lib.common_utilities import zip_pairs, closest_t_of_s
from ..lib.common_utilities import sort_objects_by_angles, vector_angle_between

from ..lib.common_bezier import cubic_bezier_blend_t, cubic_bezier_derivative, cubic_bezier_fit_points, cubic_bezier_split, cubic_bezier_t_of_s_dynamic


class EPVert:
    def __init__(self, position, from_mesh = False):
        self.position  = position
        self.snap_pos  = position
        self.snap_norm = Vector()
        self.visible = True
        self.epedges = []
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

class EPEdge:
    pass

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