# distutils: language=c++
# distutils: extra_compile_args=/std:c++17
# cython: language_level=3

from libc.stdint cimport uint8_t
from libcpp.set cimport set as cpp_set
import numpy as np
cimport numpy as np

from .bmesh_fast cimport BMVert, BMEdge, BMFace, BMesh, BPy_BMesh, BMHeader
from .space cimport ARegion, RegionView3D
from .vector cimport Vector3

'''
# Define as C constants
cdef int ALL = 0
cdef int SELECTED = 1
cdef int UNSELECTED = 2

cdef extern from *:
    """
    extern "C" {
        enum SelectionState {
            ALL = 0,
            SELECTED = 1,
            UNSELECTED = 2
        };
    }
    """
    cdef enum SelectionState:
        ALL = 0
        SELECTED = 1
        UNSELECTED = 2
'''

cdef enum SelectionState:
    ALL = 0
    SELECTED = 1
    UNSELECTED = 2

cdef struct View3D:
    float[4][4] proj_matrix
    Vector3 view_pos
    bint is_persp

cdef class Accel2D:
    cdef:
        # BMesh reference
        BPy_BMesh* py_bmesh
        BMesh* bmesh
        ARegion* region
        RegionView3D* rv3d
        int selected_only

        float[4][4] matrix_world
        float[3][3] matrix_normal
        View3D view3d

        # C++ sets for storing geometry
        cpp_set[BMVert*] verts
        cpp_set[BMEdge*] edges  
        cpp_set[BMFace*] faces
        
        # Visibility arrays
        uint8_t* is_visible_vert
        uint8_t* is_visible_edge
        uint8_t* is_visible_face
        uint8_t* is_selected_vert
        uint8_t* is_selected_edge
        uint8_t* is_selected_face

    cpdef void update_matrix_world(self, object py_matrix_world)

    cdef void _update_matrices(self) noexcept nogil
    cdef void _build_accel_struct(self) noexcept nogil
    cdef void _reset(self) noexcept nogil
    cdef void _ensure_lookup_tables(self, object py_bmesh)
    cdef bint _filter_elem(self, BMHeader* head, int index, uint8_t* is_visible_array, uint8_t* is_selected_array) noexcept nogil
    # cdef void compute_geometry_visibility_in_region(self, float margin_check=0.0) noexcept nogil

    cdef np.ndarray get_is_visible_verts_array(self)
    cdef np.ndarray get_is_visible_edges_array(self)
    cdef np.ndarray get_is_visible_faces_array(self)
    cdef np.ndarray get_is_selected_verts_array(self)
    cdef np.ndarray get_is_selected_edges_array(self)
    cdef np.ndarray get_is_selected_faces_array(self)
