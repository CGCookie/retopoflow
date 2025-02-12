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
from libc.stdint cimport uintptr_t
from libc.stdlib cimport malloc, free
from libc.stdio cimport printf
from libc.math cimport sqrt, fabs
from cython.parallel cimport parallel, prange

from .bmesh_fast cimport BMVert, BMEdge, BMLoop, BMFace, BMesh, BPy_BMesh


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
    int* num_visible
) nogil:
    cdef:
        int* visible_indices = NULL
        char* is_visible = NULL
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
        
    is_visible = <char*>malloc(vtable_tot * sizeof(char))
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
    float margin_check
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
        &num_visible
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
