# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=True

import numpy as np
cimport numpy as np
np.import_array()  # Required for NumPy C-API

from libc.stdint cimport uintptr_t, uint8_t
from libc.stdlib cimport malloc, free
from libc.stdio cimport printf
from libc.math cimport sqrt, fabs
from cython.parallel cimport parallel, prange
from cython.operator cimport dereference as deref
from libcpp.vector cimport vector
from libcpp.set cimport set as cpp_set
from libcpp.pair cimport pair

from .bmesh_fast cimport BMVert, BMEdge, BMFace, BMesh, BPy_BMesh, BMesh, BMHeader, BPy_BMEdge, BPy_BMFace, BPy_BMVert, BPy_BMLoop, BPy_BMElemSeq, BPy_BMElem, BMLoop, BPy_BMIter
from .bmesh_enums cimport BMElemHFlag, BM_elem_flag_test
from .space cimport ARegion, RegionView3D
# from .view3d_utils cimport location_3d_to_region_2d

import cython

# ctypedef np.uint8_t uint8


@cython.binding(True)
cdef class Accel2D:
    def __cinit__(self):
        # Initialize C++ member variables
        self.is_visible_vert = NULL
        self.is_visible_edge = NULL
        self.is_visible_face = NULL
        self.is_selected_vert = NULL
        self.is_selected_edge = NULL
        self.is_selected_face = NULL
        
    def __init__(self, object py_bmesh, object py_region, object py_rv3d, int selected_only):
        # print(f"Accel2D.__init__({py_bmesh}, {py_region}, {py_rv3d}, {selected_only})\n")
        self._ensure_lookup_tables(py_bmesh)
        self.py_bmesh = <BPy_BMesh*><uintptr_t>id(py_bmesh)
        self.bmesh = self.py_bmesh.bm
        self.region = <ARegion*><uintptr_t>id(py_region)
        self.rv3d = <RegionView3D*><uintptr_t>id(py_rv3d)
        self.selected_only = selected_only
        self._build_accel_struct()

    def __dealloc__(self):
        self._reset()

    cdef void _ensure_lookup_tables(self, object py_bmesh):
        """Ensure lookup tables are created for the bmesh"""
        try:
            py_bmesh.verts[0]
        except IndexError:
            py_bmesh.verts.ensure_lookup_table()
        try:
            py_bmesh.edges[0]
        except IndexError:
            py_bmesh.edges.ensure_lookup_table()
        try:
            py_bmesh.faces[0]
        except IndexError:
            py_bmesh.faces.ensure_lookup_table()

    cdef bint _filter_elem(self, BMHeader* head, int index, uint8_t* is_visible_array, uint8_t* is_selected_array) noexcept nogil:
        """Filter element based on selection and visibility flags."""
        cdef:
            bint is_visible
            bint is_selected

        is_visible = not BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_HIDDEN)
        is_selected = BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_SELECT)

        is_visible_array[index] = is_visible
        is_selected_array[index] = is_selected

        if is_visible:
            if self.selected_only == SelectionState.ALL:
                return True
            elif self.selected_only == SelectionState.SELECTED and is_selected:
                return True
            elif self.selected_only == SelectionState.UNSELECTED and not is_selected:
                return True

        return False

    cdef void _build_accel_struct(self) noexcept nogil:
        """Build acceleration structure for geometry visibility tests"""
        # printf("Accel2D._build_accel_struct()\n")

        if not self.bmesh or not self.bmesh.vtable:
            printf("Accel2D._build_accel_struct() - bmesh or vtable is NULL\n")
            return

        cdef:
            BMesh* bmesh = self.bmesh
            BMVert** vtable = bmesh.vtable
            BMEdge** etable = bmesh.etable
            BMFace** ftable = bmesh.ftable
            #BMVert* bmv = NULL
            #BMEdge* bme = NULL
            #BMFace* bmf = NULL
            size_t totvert = bmesh.totvert
            size_t totedge = bmesh.totedge
            size_t totface = bmesh.totface
            int vert_idx, edge_idx, face_idx

        # Free existing memory
        self._reset()

        # Allocate new memory using malloc
        self.is_visible_vert = <uint8_t*>malloc(totvert * sizeof(uint8_t))
        self.is_visible_edge = <uint8_t*>malloc(totedge * sizeof(uint8_t))
        self.is_visible_face = <uint8_t*>malloc(totface * sizeof(uint8_t))

        self.is_selected_vert = <uint8_t*>malloc(totvert * sizeof(uint8_t))
        self.is_selected_edge = <uint8_t*>malloc(totedge * sizeof(uint8_t))
        self.is_selected_face = <uint8_t*>malloc(totface * sizeof(uint8_t))

        with parallel():

            # Process vertices
            for vert_idx in prange(totvert):
                if vtable[vert_idx] != NULL:
                    if self._filter_elem(&vtable[vert_idx].head, vert_idx, self.is_visible_vert, self.is_selected_vert):
                        self.verts.insert(vtable[vert_idx])

            # Process edges
            for edge_idx in prange(totedge):
                if etable[edge_idx] == NULL:
                    continue
                if self._filter_elem(&etable[edge_idx].head, edge_idx, self.is_visible_edge, self.is_selected_edge):
                    self.edges.insert(etable[edge_idx])

            # Process faces
            for face_idx in prange(totface):
                if ftable[face_idx] == NULL:
                    continue
                if self._filter_elem(&ftable[face_idx].head, face_idx, self.is_visible_face, self.is_selected_face):
                    self.faces.insert(ftable[face_idx])

    cdef void _reset(self) noexcept nogil:
        """Reset the acceleration structure"""
        # printf("Accel2D._reset()\n")

        if self.is_visible_vert != NULL:
            free(self.is_visible_vert)
        if self.is_visible_edge != NULL:
            free(self.is_visible_edge)
        if self.is_visible_face != NULL:
            free(self.is_visible_face)
        
        if self.is_selected_vert != NULL:
            free(self.is_selected_vert)
        if self.is_selected_edge != NULL:
            free(self.is_selected_edge)
        if self.is_selected_face != NULL:
            free(self.is_selected_face)

        # Set memory views to empty
        self.is_visible_vert = NULL
        self.is_visible_edge = NULL
        self.is_visible_face = NULL
        
        self.is_selected_vert = NULL
        self.is_selected_edge = NULL
        self.is_selected_face = NULL

        # For C++ sets, we don't need to check for NULLs, just clear them!
        self.verts.clear()
        self.edges.clear()
        self.faces.clear()

    '''
    ______________________________________________________________________________________________________________
    
    Python access methods 
    ______________________________________________________________________________________________________________
    '''

    def get_visible_geom(self, object py_bmesh, bint verts=True, bint edges=True, bint faces=True, bint invert_selection=False):
        """Return sets of visible geometry"""
        if not self.bmesh or not self.bmesh.vtable:
            printf("Accel2D.get_visible_geom() - bmesh or vtable is NULL\n")
            return set(), set(), set()

        cdef:
            BMesh* bmesh = self.bmesh
            set vis_py_verts = set()
            set vis_py_edges = set()
            set vis_py_faces = set()
            object py_bm_verts = py_bmesh.verts
            object py_bm_edges = py_bmesh.edges
            object py_bm_faces = py_bmesh.faces

        if verts:
            for i in range(bmesh.totvert):
                if self.is_visible_vert[i] if not invert_selection else not self.is_visible_vert[i]:
                    vis_py_verts.add(py_bm_verts[i])

        if edges:
            for i in range(bmesh.totedge):
                if self.is_visible_edge[i] if not invert_selection else not self.is_visible_edge[i]:
                    vis_py_edges.add(py_bm_edges[i])

        if faces:
            for i in range(bmesh.totface):
                if self.is_visible_face[i] if not invert_selection else not self.is_visible_face[i]:
                    vis_py_faces.add(py_bm_faces[i])

        return vis_py_verts, vis_py_edges, vis_py_faces

    def get_selected_geom(self, object py_bmesh, bint verts=True, bint edges=True, bint faces=True, bint invert_selection=False):
        """Return sets of selected geometry"""
        if not self.bmesh or not self.bmesh.vtable:
            printf("Accel2D.get_selected_geom() - bmesh or vtable is NULL\n")
            return set(), set(), set()

        cdef:
            BMesh* bmesh = self.bmesh
            set sel_py_verts = set()
            set sel_py_edges = set()
            set sel_py_faces = set()
            object py_bm_verts = py_bmesh.verts
            object py_bm_edges = py_bmesh.edges
            object py_bm_faces = py_bmesh.faces

        if verts:
            for i in range(bmesh.totvert):
                if self.is_selected_vert[i] if not invert_selection else not self.is_selected_vert[i]:
                    sel_py_verts.add(py_bm_verts[i])

        if edges:
            for i in range(bmesh.totedge):
                if self.is_selected_edge[i] if not invert_selection else not self.is_selected_edge[i]:
                    sel_py_edges.add(py_bm_edges[i])

        if faces:
            for i in range(bmesh.totface):
                if self.is_selected_face[i] if not invert_selection else not self.is_selected_face[i]:
                    sel_py_faces.add(py_bm_faces[i])

        return sel_py_verts, sel_py_edges, sel_py_faces

    def get_nearest_verts(self, tuple point, double max_dist):
        """Get vertices within max_dist of point"""
        # Implement vertex query
        pass

    def get_nearest_edges(self, tuple point, double max_dist):
        """Get edges within max_dist of point"""
        # Implement edge query
        pass

    def get_nearest_faces(self, tuple point, double max_dist):
        """Get faces within max_dist of point"""
        # Implement face query
        pass

    def get_visible_arrays(self):
        """Get visible arrays as NumPy arrays (zero-copy)"""
        cdef:
            BMesh* bmesh = self.py_bmesh.bm
            np.npy_intp vert_size = bmesh.totvert
            np.npy_intp edge_size = bmesh.totedge
            np.npy_intp face_size = bmesh.totface

        return (
            np.PyArray_SimpleNewFromData(1, &vert_size, np.NPY_UINT8, self.is_visible_vert),
            np.PyArray_SimpleNewFromData(1, &edge_size, np.NPY_UINT8, self.is_visible_edge),
            np.PyArray_SimpleNewFromData(1, &face_size, np.NPY_UINT8, self.is_visible_face)
        )

    def get_selected_arrays(self):
        """Get selected arrays as NumPy arrays (zero-copy)"""
        cdef:
            BMesh* bmesh = self.py_bmesh.bm
            np.npy_intp vert_size = bmesh.totvert
            np.npy_intp edge_size = bmesh.totedge
            np.npy_intp face_size = bmesh.totface

        return (
            np.PyArray_SimpleNewFromData(1, &vert_size, np.NPY_UINT8, self.is_selected_vert),
            np.PyArray_SimpleNewFromData(1, &edge_size, np.NPY_UINT8, self.is_selected_edge),
            np.PyArray_SimpleNewFromData(1, &face_size, np.NPY_UINT8, self.is_selected_face)
        )

    cdef np.ndarray get_is_visible_verts_array(self):
        """Get visible array of vertices as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totvert
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_visible_vert)

    cdef np.ndarray get_is_visible_edges_array(self):
        """Get visible array of edges as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totedge
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_visible_edge)

    cdef np.ndarray get_is_visible_faces_array(self):
        """Get visible array of faces as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totface
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_visible_face)

    cdef np.ndarray get_is_selected_verts_array(self):
        """Get selected array of vertices as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totvert
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_selected_vert)

    cdef np.ndarray get_is_selected_edges_array(self):
        """Get selected array of edges as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totedge
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_selected_edge)

    cdef np.ndarray get_is_selected_faces_array(self):
        """Get selected array of faces as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totface
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_selected_face)
