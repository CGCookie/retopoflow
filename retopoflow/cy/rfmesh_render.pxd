# distutils: language=c++
# cython: language_level=3

import numpy as np
cimport numpy as np
from libcpp.vector cimport vector
from libcpp.set cimport set as cpp_set

from .bl_types.bmesh_types cimport BMVert, BMEdge, BMFace, BMesh, BMHeader, BMLoop
from .bl_types.bmesh_py_wrappers cimport BPy_BMesh
from .bl_types.bmesh_flags cimport BMElemHFlag


cdef class MeshRenderAccel:
    cdef:
        object py_bmesh
        BPy_BMesh* bmesh_pywrapper
        BMesh* bmesh
        bint mirror_x, mirror_y, mirror_z
        object layer_pin

    cpdef bint check_bmesh(self)
    
    # Helper methods for element state
    cdef float sel_elem(self, BMHeader* head) noexcept nogil
    cdef float seam_elem(self, BMHeader* head) noexcept nogil
    cdef bint hidden_elem(self, BMHeader* head) noexcept nogil
    
    cdef float warn_vert(self, BMVert* vert) noexcept nogil
    cdef float warn_edge(self, BMEdge* edge) noexcept nogil
    cdef float warn_face(self, BMFace* face) noexcept nogil
    
    cdef float pin_vert(self, BMVert* vert) noexcept nogil
    cdef float pin_edge(self, BMEdge* edge) noexcept nogil
    cdef float pin_face(self, BMFace* face) noexcept nogil
    
    cdef float seam_vert(self, BMVert* vert) noexcept nogil
    cdef float seam_edge(self, BMEdge* edge) noexcept nogil
    cdef float seam_face(self, BMFace* face) noexcept nogil
    
    # Main data gathering methods
    cpdef dict gather_vert_data(self)
    cpdef dict gather_edge_data(self)
    cpdef dict gather_face_data(self)