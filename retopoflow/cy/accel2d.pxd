# distutils: language=c++
# distutils: extra_compile_args=/std:c++17
# cython: language_level=3

from libc.stdint cimport uint8_t
from libcpp.set cimport set as cpp_set
import numpy as np
cimport numpy as np

from .bmesh_fast cimport BMVert, BMEdge, BMFace, BMesh, BPy_BMesh, BMHeader
from .space cimport ARegion, RegionView3D


cdef enum SelectionState:
    ALL = 0
    SELECTED = 1
    UNSELECTED = 2

cdef struct View3D:
    float[4][4] proj_matrix
    float[3] view_pos
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
        cpp_set[BMVert*] visverts
        cpp_set[BMEdge*] visedges  
        cpp_set[BMFace*] visfaces
        size_t totvisverts
        size_t totvisedges
        size_t totvisfaces

        # Visibility arrays
        uint8_t* is_hidden_v
        uint8_t* is_hidden_e
        uint8_t* is_hidden_f
        uint8_t* is_selected_v
        uint8_t* is_selected_e
        uint8_t* is_selected_f

    # cpdef void update_matrix_world(self, object py_matrix_world)
    cdef void _update_view(self, const float[:, ::1] proj_matrix, const float[::1] view_pos, bint is_perspective) nogil
    cdef void _update_object_transform(self, const float[:, ::1] matrix_world, const float[:, ::1] matrix_normal) nogil
    # cdef void _update_matrices(self) noexcept nogil
    cdef void _build_accel_struct(self) noexcept nogil
    cdef void _reset(self) noexcept nogil
    cpdef void _ensure_lookup_tables(self, object py_bmesh)
    cdef void _classify_elem(self, BMHeader* head, size_t index, uint8_t* is_hidden_array, uint8_t* is_selected_array) noexcept nogil
    cdef int _compute_geometry_visibility_in_region(self, float margin_check) nogil

    # def get_vis_verts(self, object py_bmesh, int selected_only) -> set

    cdef np.ndarray get_is_visible_verts_array(self)
    cdef np.ndarray get_is_visible_edges_array(self)
    cdef np.ndarray get_is_visible_faces_array(self)
    cdef np.ndarray get_is_selected_verts_array(self)
    cdef np.ndarray get_is_selected_edges_array(self)
    cdef np.ndarray get_is_selected_faces_array(self)
