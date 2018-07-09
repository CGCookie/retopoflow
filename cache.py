'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

#common cache for bmesh and BVH
from mathutils import Vector

from .common.debug import dprint

mesh_cache = {}

contour_cache = {}
contour_undo_cache = []
polystrips_undo_cache = [] #TODO, implement this
polypen_undo_cache = []
tweak_undo_cache = []

def object_validation(ob):
    me = ob.data
    # get object data to act as a hash
    counts = (len(me.vertices), len(me.edges), len(me.polygons), len(ob.modifiers))
    bbox   = (tuple(min(v.co for v in me.vertices)), tuple(max(v.co for v in me.vertices)))
    vsum   = tuple(sum((v.co for v in me.vertices), Vector((0,0,0))))
    return (ob.name, counts, bbox, vsum)

def is_object_valid(ob):
    if 'valid' not in mesh_cache: return False
    return mesh_cache['valid'] == object_validation(ob)

def write_mesh_cache(orig_ob, bme, bvh):
    dprint('writing mesh cache')
    mesh_cache['valid'] = object_validation(orig_ob)
    mesh_cache['bme'] = bme
    mesh_cache['bvh'] = bvh

def clear_mesh_cache():
    dprint('clearing mesh cache')
    if 'valid' in mesh_cache and mesh_cache['valid']:
        del mesh_cache['valid']

    if 'bme' in mesh_cache and mesh_cache['bme']:
        bme_old = mesh_cache['bme']
        bme_old.free()
        del mesh_cache['bme']

    if 'bvh' in mesh_cache and mesh_cache['bvh']:
        bvh_old = mesh_cache['bvh']
        del bvh_old
    
