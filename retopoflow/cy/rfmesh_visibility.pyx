# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=False
# distutils: language=c++
# distutils: include_dirs = numpy.get_include()

import numpy as np
cimport numpy as np
from cython cimport Py_ssize_t
np.import_array()  # Initialize NumPy C-API

from libc.stdint cimport uintptr_t
from libc.math cimport sqrt, fabs
from cython.parallel cimport parallel, prange

ctypedef float real_t
ctypedef np.float32_t DTYPE_t


cdef inline real_t vec3_dot(const real_t* a, const real_t* b) noexcept nogil:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

cdef inline void vec3_normalize(real_t* v) noexcept nogil:
    cdef real_t length = sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length > 0:
        v[0] /= length
        v[1] /= length
        v[2] /= length

cdef inline void mat4_vec3_mul(const real_t[:, ::1] mat, const real_t[::1] vec, real_t[::1] result) noexcept nogil:
    result[0] = mat[0,0]*vec[0] + mat[0,1]*vec[1] + mat[0,2]*vec[2] + mat[0,3]
    result[1] = mat[1,0]*vec[0] + mat[1,1]*vec[1] + mat[1,2]*vec[2] + mat[1,3]
    result[2] = mat[2,0]*vec[0] + mat[2,1]*vec[1] + mat[2,2]*vec[2] + mat[2,3]

cdef inline void mat3_vec3_mul(const real_t[:, ::1] mat, const real_t[::1] vec, real_t[::1] result) noexcept nogil:
    result[0] = mat[0,0]*vec[0] + mat[0,1]*vec[1] + mat[0,2]*vec[2]
    result[1] = mat[1,0]*vec[0] + mat[1,1]*vec[1] + mat[1,2]*vec[2]
    result[2] = mat[2,0]*vec[0] + mat[2,1]*vec[1] + mat[2,2]*vec[2]

cdef int _compute_visible_vertices_nogil(
    const float* positions,
    const float* normals,
    const Py_ssize_t num_vertices,
    const bint process_all_verts,
    const int* vert_indices,
    const Py_ssize_t num_indices,
    const real_t[:, ::1] matrix_world,
    const real_t[:, ::1] matrix_normal,
    const real_t[:, ::1] proj_matrix,
    const real_t[::1] view_pos,
    const bint is_perspective,
    const real_t margin_check,
    unsigned char* visible,
) noexcept nogil:
    cdef:
        Py_ssize_t i, idx, vi, j, k
        real_t[3] world_pos
        real_t[3] world_normal
        real_t[3] view_dir
        real_t[4] screen_pos
        int num_visible = 0
    
    with parallel():
        for i in prange(num_vertices if process_all_verts else num_indices):
            idx = i if process_all_verts else vert_indices[i]
            vi = idx * 3  # Vertex index * 3 for xyz components
            
            # Transform position to world space
            for j in range(3):
                world_pos[j] = 0
                for k in range(3):
                    world_pos[j] += positions[vi + k] * matrix_world[k,j]
                world_pos[j] += matrix_world[3,j]
            
            # Transform normal to world space
            for j in range(3):
                world_normal[j] = 0
                for k in range(3):
                    world_normal[j] += normals[vi + k] * matrix_normal[k,j]
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
                visible[idx] = 1
                num_visible += 1

    return num_visible

cpdef np.ndarray[np.uint8_t, ndim=1] compute_visible_vertices(
    uintptr_t vert_ptr,
    uintptr_t norm_ptr,
    int num_vertices,
    bint process_all_verts,
    np.ndarray[np.int32_t, ndim=1] vert_indices,
    np.ndarray[DTYPE_t, ndim=2] matrix_world,
    np.ndarray[DTYPE_t, ndim=2] matrix_normal,
    np.ndarray[DTYPE_t, ndim=2] proj_matrix,
    np.ndarray[DTYPE_t, ndim=1] view_pos,
    bint is_perspective,
    DTYPE_t margin_check
):
    # Cast pointers to our vertex data structure
    cdef float* positions = <float*>vert_ptr
    cdef float* normals = <float*>norm_ptr

    # Create visibility array
    cdef np.ndarray[np.uint8_t, ndim=1] visible_np = np.zeros(num_vertices, dtype=np.uint8)
    cdef unsigned char* visible = <unsigned char*>visible_np.data
    
    # Get pointer to indices array
    cdef int* indices_ptr = NULL
    if not process_all_verts:
        indices_ptr = <int*>vert_indices.data
    
    # Call the nogil function and get number of visible vertices
    _compute_visible_vertices_nogil(
        positions,
        normals,
        num_vertices,
        process_all_verts,
        indices_ptr,
        len(vert_indices),
        matrix_world,
        matrix_normal,
        proj_matrix,
        view_pos,
        is_perspective,
        margin_check,
        visible,
    )

    return visible_np
