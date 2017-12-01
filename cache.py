#common cache for bmesh and BVH
from mathutils import Vector

from .lib.common_utilities import dprint

mesh_cache = {}

contour_cache = {}
contour_undo_cache = []
polystrips_undo_cache = []
edgepatches_undo_cache = []
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
    
