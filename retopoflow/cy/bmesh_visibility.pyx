# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=False

import numpy as np
cimport numpy as np
np.import_array()  # Required for NumPy C-API

from libc.stdint cimport uintptr_t
from libc.stdlib cimport malloc, free
from libc.stdio cimport printf
from libc.math cimport sqrt, fabs
from cython.parallel cimport parallel, prange

from .bmesh_fast cimport BMVert, BMEdge, BMLoop, BMFace, BMesh, BPy_BMesh, BPy_BMEdge, BPy_BMElemSeq, BPy_BMElem

# At the top of the file, add global cache variables
cdef:
    int* _cached_visibility = NULL
    int _cached_size = 0
    bint _cache_valid = False

# Function to clear the cache
def clear_visibility_cache():
    global _cached_visibility, _cached_size, _cache_valid
    if _cached_visibility != NULL:
        free(_cached_visibility)
        _cached_visibility = NULL
    _cached_size = 0
    _cache_valid = False

cdef inline float vec3_dot(const float* a, const float* b) noexcept nogil:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

cdef inline void vec3_normalize(float* v) noexcept nogil:
    cdef float length = sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length > 0:
        v[0] /= length
        v[1] /= length
        v[2] /= length


cdef int* _compute_visible_vertices_nogil(
    BMVert** vtable,
    int vtable_tot,
    const float[:, ::1] matrix_world,
    const float[:, ::1] matrix_normal,
    const float[:, ::1] proj_matrix,
    const float[::1] view_pos,
    bint is_perspective,
    float margin_check,
    int* num_visible,
    bint cache_visibility
) nogil:
    cdef:
        int* visible_indices = NULL
        int* is_visible = NULL
        int i, j, k, count = 0
        float[3] world_pos
        float[3] world_normal
        float[3] view_dir
        float[4] screen_pos
        BMVert* vert

    # Allocate memory
    visible_indices = <int*>malloc(vtable_tot * sizeof(int))
    if visible_indices == NULL:
        printf("Error: Failed to allocate visible_indices\n")
        num_visible[0] = 0
        return NULL
        
    is_visible = <int*>malloc(vtable_tot * sizeof(int))
    if is_visible == NULL:
        printf("Error: Failed to allocate is_visible\n")
        free(visible_indices)
        num_visible[0] = 0
        return NULL
    
    # Initialize visibility array
    for i in range(vtable_tot):
        is_visible[i] = 0
    
    with parallel():
        for i in prange(vtable_tot, schedule='static'):
            vert = vtable[i]
            if vert == NULL:
                continue
            
            # Transform position to world space
            for j in range(3):
                world_pos[j] = 0
                for k in range(3):
                    world_pos[j] += vert.co[k] * matrix_world[k,j]
                world_pos[j] += matrix_world[3,j]
            
            # Transform normal to world space
            for j in range(3):
                world_normal[j] = 0
                for k in range(3):
                    world_normal[j] += vert.no[k] * matrix_normal[k,j]
            vec3_normalize(world_normal)
            
            # Calculate view direction
            if is_perspective:
                for j in range(3):
                    view_dir[j] = world_pos[j] - view_pos[j]
                vec3_normalize(view_dir)
            else:
                for j in range(3):
                    view_dir[j] = view_pos[j]
            
            # Check if facing camera
            if vec3_dot(world_normal, view_dir) > 0:
                continue
            
            # Project to screen space
            for j in range(4):
                screen_pos[j] = (
                    world_pos[0] * proj_matrix[0,j] +
                    world_pos[1] * proj_matrix[1,j] +
                    world_pos[2] * proj_matrix[2,j] +
                    proj_matrix[3,j]
                )
            
            if screen_pos[3] <= 0:  # Behind camera
                continue
            
            # Perspective divide and bounds check
            if (fabs(screen_pos[0] / screen_pos[3]) <= margin_check and 
                fabs(screen_pos[1] / screen_pos[3]) <= margin_check):
                is_visible[i] = 1

    # Collect indices sequentially
    count = 0
    for i in range(vtable_tot):
        if is_visible[i]:
            visible_indices[count] = i
            count += 1
    
    if cache_visibility:
        global _cached_visibility, _cached_size, _cache_valid
        # Free old cache if size doesn't match
        if _cached_visibility != NULL and _cached_size != vtable_tot:
            free(_cached_visibility)
            _cached_visibility = NULL

        # Save to cache
        _cached_visibility = is_visible
        _cached_size = vtable_tot
        _cache_valid = True
    else:
        free(is_visible)

    num_visible[0] = count
    return visible_indices


def compute_visible_vertices(
    object bm_py,
    list rf_verts,
    np.ndarray[np.float32_t, ndim=2] matrix_world,
    np.ndarray[np.float32_t, ndim=2] matrix_normal,
    np.ndarray[np.float32_t, ndim=2] proj_matrix,
    np.ndarray[np.float32_t, ndim=1] view_pos,
    bint is_perspective,
    float margin_check,
    bint cache_visibility
):
    cdef:
        BMesh* bmesh = (<BPy_BMesh*><uintptr_t>id(bm_py)).bm
        int i, num_visible = 0
        int* visible_indices = NULL
        set result = set()
        object bm_verts = bm_py.verts

    if not bmesh or bmesh.vtable == NULL or bmesh.vtable_tot <= 0:
        printf("Error: Invalid bmesh or vtable\n")
        return set()

    visible_indices = _compute_visible_vertices_nogil(
        bmesh.vtable,
        bmesh.vtable_tot,
        matrix_world,
        matrix_normal,
        proj_matrix,
        view_pos,
        is_perspective,
        margin_check,
        &num_visible,
        cache_visibility
    )

    if visible_indices == NULL:
        printf("Error: visible_indices is NULL\n")
        return set()

    # Create Python set from indices
    try:
        if len(rf_verts) == 0:
            # printf("num_visible: %d\n", num_visible)
            result = {bm_verts[visible_indices[i]] for i in range(num_visible)}
        else:
            result = {rf_verts[visible_indices[i]] for i in range(num_visible)}
    finally:
        free(visible_indices)
    
    return result


def get_visible_edges_from_verts_vis_cache(
    object bm_py
):
    cdef:
        BMesh* bmesh = (<BPy_BMesh*><uintptr_t>id(bm_py)).bm
        BMEdge* edge
        BMVert* v1
        BMVert* v2
        int i, v1_idx, v2_idx
        int* cached_vis = _cached_visibility
        int cached_size = _cached_size
        list visible_edges = []
        object bm_py_edges = bm_py.edges
        int visible_count = 0

    if not bmesh or bmesh.etable == NULL or bmesh.etable_tot <= 0:
        printf("Error: Invalid bmesh or etable\n")
        return set()

    if not _cache_valid or cached_vis == NULL:
        printf("Error: No valid visibility cache\n")
        return set()

    # printf("Cache size: %d, Total edges: %d\n", cached_size, bmesh.etable_tot)
    
    # Process edges without GIL
    for i in range(bmesh.etable_tot):
        edge = bmesh.etable[i]
        if edge == NULL:
            continue
            
        v1 = <BMVert*>edge.v1
        v2 = <BMVert*>edge.v2
        
        v1_idx = v1.head.index
        v2_idx = v2.head.index

        if (
            ((0 <= v1_idx < cached_size) and cached_vis[v1_idx]) or
            ((0 <= v2_idx < cached_size) and cached_vis[v2_idx])
        ):
            visible_count += 1
            visible_edges.append(bm_py_edges[i])

    # printf("Total visible edges found: %d\n", visible_count)
    return set(visible_edges)


def get_visible_faces_from_verts_vis_cache(
    object bm_py
):
    cdef:
        BMesh* bmesh = (<BPy_BMesh*><uintptr_t>id(bm_py)).bm
        BMLoop* loop
        BMVert* vert
        BMFace* face
        int i, v1_idx, v2_idx
        int* cached_vis = _cached_visibility
        int cached_size = _cached_size
        list visible_faces = []
        object bm_py_faces = bm_py.faces
        int visible_count = 0

    if not bmesh or bmesh.ftable == NULL or bmesh.ftable_tot <= 0:
        printf("Error: Invalid bmesh or ftable\n")
        return set()

    if not _cache_valid or cached_vis == NULL:
        printf("Error: No valid visibility cache\n")
        return set()

    # printf("Cache size: %d, Total faces: %d\n", cached_size, bmesh.ftable_tot)

    # Process edges without GIL
    for i in range(bmesh.ftable_tot):
        face = <BMFace*>bmesh.ftable[i]
        if face == NULL:
            continue

        loop = <BMLoop*>face.l_first
        if loop == NULL:
            continue

        for v_index in range(face.len):
            vert = <BMVert*>loop.v

            if (
                ((0 <= vert.head.index < cached_size) and cached_vis[vert.head.index])
            ):
                visible_count += 1
                visible_faces.append(bm_py_faces[face.head.index])

            loop = <BMLoop*>loop.next

    # printf("Total visible faces found: %d\n", visible_count)
    return set(visible_faces)


'''
# Add a function to check if vertex is visible (using cache)
def is_vertex_visible_safe(int vert_idx):
    if not _cache_valid or _cached_visibility == NULL:
        return False
    if vert_idx < 0 or vert_idx >= _cached_size:
        return False
    return _cached_visibility[vert_idx] == 1

def is_vertex_visible(int vert_idx):
    return _cached_visibility[vert_idx] == 1

def is_edge_visible_safe(BMEdge* edge):
    return is_vertex_visible_safe((<BMVert*>edge.v1).head.index) or is_vertex_visible_safe((<BMVert*>edge.v2).head.index)

def is_edge_visible(BMEdge* edge):
    return is_vertex_visible((<BMVert*>edge.v1).head.index) or is_vertex_visible((<BMVert*>edge.v2).head.index)
'''

# Add cleanup function to be called when shutting down
def cleanup_visibility_cache():
    clear_visibility_cache()
