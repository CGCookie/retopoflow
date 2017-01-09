'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning and Jonathan Williamson

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

import bpy, blf, bgl, bmesh
from mathutils.bvhtree import BVHTree
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from ...common_utilities import bversion, dprint
from ...common_utilities import invert_matrix, matrix_normal
#from ...common_utilities import ray_cast_region2d_bvh
from ....cache import is_object_valid, clear_mesh_cache, write_mesh_cache, mesh_cache

class BMeshCache():
    '''
    BMeshCache is useful for containing data related to mesh object, such as BMesh, BVH, matrices
    
    Use only with objects that do not change
    '''
    
    def __init__(self, data, mx=None):
        if type(data) is str:
            data = bpy.data.objects[data]
        
        if type(data) is bpy.types.Object:
            assert data.type == 'MESH', 'Unhandled object type: %s' % data.type
            
            if not is_object_valid(data):
                dprint('Creating BMesh from Mesh Object')
                bme = bmesh.new()
                bme.from_object(data, bpy.context.scene)
                # triangulate all faces to ensure planarity and other nice properties
                dprint('Triangulating BMesh')
                bmesh.ops.triangulate(bme, faces=bme.faces[:])
                # create bvh tree for raycasting and snapping
                dprint('Creating BVH Tree')
                bvh = BVHTree.FromBMesh(bme)
                dprint('Writing to mesh cache')
                clear_mesh_cache()
                write_mesh_cache(data, bme, bvh)
            
            self.bme = mesh_cache['bme']
            self.bvh = mesh_cache['bvh']
            self.mx  = data.matrix_world
        
        elif type(data) is bmesh.types.BMesh:
            assert mx, 'Must specify matrix when data is BMesh!'
            bmesh.ops.triangulate(data, faces=data.faces[:])
            self.bme = data
            self.bvh = BVHTree.FromBMesh(self.bme)
            self.mx  = mx
        
        else:
            assert False, 'Unknown data type: %s' % str(type(data))
        
        self.bvh_raycast = self.bvh.ray_cast
        self.bvh_nearest = self.bvh.find_nearest if bversion() > '002.076.000' else self.bvh.find
        self.imx = invert_matrix(self.mx)
        self.nmx = matrix_normal(self.mx)
        self.imx3x3 = self.imx.to_3x3()
    
    def __del__(self):
        #self.bme.free()  # do NOT free! may be shared!
        del self.bme
        del self.bvh
    
    def raycast_screen(self, loc2d, rgn, r3d):
        o,d = region_2d_to_origin_3d(rgn, r3d, loc2d),region_2d_to_vector_3d(rgn, r3d, loc2d)
        back = 0 if r3d.is_perspective else 100
        p3d,n3d,idx,dist = self.bvh_raycast(self.imx * (o-d*back), self.imx3x3 * d)
        p3d = self.mx * p3d if p3d else None
        n3d = self.nmx * n3d if n3d else None
        return (p3d, n3d)
    
    def find_nearest(self, loc3d):
        p3d,n3d,idx,dist = self.bvh_nearest(self.imx * loc3d)
        p3d = self.mx * p3d if p3d else None
        n3d = self.nmx * n3d if n3d else None
        # Note: dist is computed, but it is wrt to local space
        return (p3d, n3d, (p3d-loc3d).length)
