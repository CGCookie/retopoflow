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
from ...common_utilities import bversion, invert_matrix, ray_cast_region2d_bvh, get_settings
from ....cache import is_object_valid, clear_mesh_cache, write_mesh_cache, mesh_cache

class BMeshCache():
    '''
    BMeshCache is useful for containing data related to mesh object, such as BMesh, BVH, matrices
    
    Use only with objects that do not change
    '''
    
    def __init__(self, data, mx=None):
        if type(data) is bpy.types.Object:
            assert data.type == 'MESH', 'Unhandled object type: %s' % data.type
            
            if not is_object_valid(data):
                bme = bmesh.new()
                bme.from_object(data, bpy.context.scene)
                # triangulate all faces to ensure planarity and other nice properties
                bmesh.ops.triangulate(bme, faces=bme.faces[:])
                # create bvh tree for raycasting and snapping
                bvh = BVHTree.FromBMesh(bme)
                clear_mesh_cache()
                write_mesh_cache(data, bme, bvh)
            
            self.bme = mesh_cache['bme']
            self.bvh = mesh_cache['bvh']
            self.mx = data.matrix_world
        
        elif type(data) is bmesh.types.BMesh:
            assert mx, 'Must specify matrix when data is BMesh!'
            bmesh.ops.triangulate(data, faces=data.faces[:])
            self.bme = data
            self.bvh = BVHTree.FromBMesh(self.bme)
            self.mx = mx
        
        else:
            assert False, 'Unknown data type: %s' % str(type(data))
        
        self.bvh_nearest = self.bvh.find_nearest if bversion() > '002.076.000' else self.bvh.find
        self.imx = invert_matrix(self.mx)
        self.settings = get_settings()
    
    def raycast_screen(self, loc2d, rgn, r3d):
        ray,hit = ray_cast_region2d_bvh(rgn, r3d, loc2d, self.bvh, self.mx, self.settings)
        hit_p3d,hit_norm,hit_idx = hit
        return (hit_p3d, hit_norm)
    
    def find_nearest(self, loc3d):
        p3d,norm,idx,dist = self.bvh_nearest(self.imx * loc3d)
        return (self.mx * p3d, norm, dist)
