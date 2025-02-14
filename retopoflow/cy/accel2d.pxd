# distutils: language=c++
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

cdef class Accel2D:
    cdef:
        # BMesh reference
        BPy_BMesh* py_bmesh
        BMesh* bmesh
        ARegion* region
        RegionView3D* rv3d
        int selected_only
        
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

    cdef void _build_accel_struct(self) noexcept nogil
    cdef void _reset(self) noexcept nogil
    cdef void _ensure_lookup_tables(self, object py_bmesh)
    cdef bint _filter_elem(self, BMHeader* head, int index, uint8_t* is_visible_array, uint8_t* is_selected_array) noexcept nogil

    cdef np.ndarray get_is_visible_verts_array(self)
    cdef np.ndarray get_is_visible_edges_array(self)
    cdef np.ndarray get_is_visible_faces_array(self)
    cdef np.ndarray get_is_selected_verts_array(self)
    cdef np.ndarray get_is_selected_edges_array(self)
    cdef np.ndarray get_is_selected_faces_array(self)
