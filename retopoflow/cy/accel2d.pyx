# distutils: language=c++
# distutils: extra_compile_args=/std:c++17
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
from libc.string cimport memset, memcpy
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
from .vector cimport vec3_normalize, vec3_dot
from .matrix cimport mat4_invert_safe, mat4_invert, mat4_to_3x3, mat4_transpose, mat4_multiply, mat4_get_col3, mat4_get_translation
# from .view3d_utils cimport location_3d_to_region_2d

import cython

# from mathutils import Matrix as py_Matrix
# from bmesh.types import BMesh as py_BMesh
# from bpy.types import Region as py_Region, RegionView3D as py_RegionView3D

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

    def __init__(self, object py_bmesh, object py_object, object py_region, object py_rv3d, int selected_only):
        # print(f"Accel2D.__init__({py_bmesh}, {py_region}, {py_rv3d}, {selected_only})\n")
        self._ensure_lookup_tables(py_bmesh)
        self.py_bmesh = <BPy_BMesh*><uintptr_t>id(py_bmesh)
        self.bmesh = self.py_bmesh.bm
        self.region = <ARegion*><uintptr_t>id(py_region)
        self.rv3d = <RegionView3D*><uintptr_t>id(py_rv3d)
        self.selected_only = selected_only
        self.update_matrix_world(py_object.matrix_world)
        # self.compute_geometry_visibility_in_region(margin_check=0.0)
        self._build_accel_struct()

    def __dealloc__(self):
        self._reset()

    cpdef void update_matrix_world(self, object py_matrix_world):
        # Matrix World.
        for i in range(4):
            for j in range(4):
                self.matrix_world[i][j] = py_matrix_world[i][j]
        
        self._update_matrices()

    cdef void _update_matrices(self) noexcept nogil:
        cdef:
            float[4][4] mat_temp_1
            float[4][4] mat_temp_2
            bint is_persp

        # Matrix Normal.
        mat4_invert_safe(self.matrix_world, mat_temp_1)  # Call the function here
        mat4_transpose(mat_temp_1, mat_temp_2)
        mat4_to_3x3(mat_temp_2, self.matrix_normal)

        ############################################################
        # Pre-compute the view and projection matrices

        # Projection matrix.
        mat4_multiply(self.rv3d.winmat, self.rv3d.viewmat, self.view3d.proj_matrix)

        # Determine if the view is perspective.
        # In RegionView3D, 'is_persp' is declared as a char (non-zero means perspective).
        is_persp = self.rv3d.is_persp != 0
        self.view3d.is_persp = is_persp

        # View position.
        mat4_invert(self.rv3d.viewmat, mat_temp_1)
        if is_persp:
            mat4_get_translation(mat_temp_1, &self.view3d.view_pos)
        else:
            mat4_get_col3(mat_temp_1, 2, &self.view3d.view_pos)

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
            bint is_visible = not BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_HIDDEN)
            bint is_selected = BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_SELECT)

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
        with gil:
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
                        pass # self.verts.insert(vtable[vert_idx])

            # Process edges
            for edge_idx in prange(totedge):
                if etable[edge_idx] == NULL:
                    continue
                if self._filter_elem(&etable[edge_idx].head, edge_idx, self.is_visible_edge, self.is_selected_edge):
                    pass # self.edges.insert(etable[edge_idx])

            # Process faces
            for face_idx in prange(totface):
                if ftable[face_idx] == NULL:
                    continue
                if self._filter_elem(&ftable[face_idx].head, face_idx, self.is_visible_face, self.is_selected_face):
                    pass # self.faces.insert(ftable[face_idx])

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
    cdef void compute_geometry_visibility_in_region(self, float margin_check=0.0) noexcept nogil:
        cdef:
            uint8_t* visible_vert_indices = NULL
            uint8_t* is_vert_visible = NULL
            uint8_t* is_edge_visible = NULL
            uint8_t* is_face_visible = NULL
            size_t i, j, k, count = 0
            float[3] world_pos
            float[3] world_normal
            float[3] view_dir
            float[4] screen_pos
            BMVert* vert
            BMEdge* edge
            BMFace* face
            BMLoop* loop
            
            # Cache BMesh data before nogil section
            BMVert** vtable
            BMEdge** etable
            BMFace** ftable
            size_t totvert
            size_t totedge
            size_t totface
            View3D view3d
            float[4][4] matrix_world
            float[4][4] matrix_normal
            float[4][4] proj_matrix
            float[3] view_pos
            bint is_persp

        # Get BMesh data with GIL
        with gil:
            vtable = self.bmesh.vtable
            etable = self.bmesh.etable
            ftable = self.bmesh.ftable
            totvert = self.bmesh.totvert
            totedge = self.bmesh.totedge
            totface = self.bmesh.totface
            view3d = self.view3d
            is_persp = view3d.is_persp
            memcpy(matrix_world, self.matrix_world, sizeof(float) * 16)
            memcpy(matrix_normal, self.matrix_normal, sizeof(float) * 16)
            memcpy(proj_matrix, view3d.proj_matrix, sizeof(float) * 16)
            memcpy(view_pos, view3d.view_pos, sizeof(float) * 3)

        # Now we can use these cached values in nogil section
        # Allocate memory
        visible_vert_indices = <uint8_t*>malloc(totvert * sizeof(uint8_t))
        is_vert_visible = <uint8_t*>malloc(totvert * sizeof(uint8_t))
        is_edge_visible = <uint8_t*>malloc(totedge * sizeof(uint8_t))
        is_face_visible = <uint8_t*>malloc(totface * sizeof(uint8_t))
        if visible_vert_indices == NULL or is_vert_visible == NULL or\
            is_edge_visible == NULL or is_face_visible == NULL:
            printf("Error: Failed to allocate memory\n")
            if visible_vert_indices != NULL:
                free(visible_vert_indices)
            if is_vert_visible != NULL:
                free(is_vert_visible)
            if is_edge_visible != NULL:
                free(is_edge_visible)
            if is_face_visible != NULL:
                free(is_face_visible)
            return

        # Initialize visibility array
        with parallel():
            for i in prange(totvert):
                is_vert_visible[i] = 0
                visible_vert_indices[i] = 0
            for j in prange(totedge):
                is_edge_visible[j] = 0
            for k in prange(totface):
                is_face_visible[k] = 0

        # Compute visible vertices on screen (region space).
        for i in prange(totvert, nogil=True):
            vert = vtable[i]
            if vert == NULL:
                continue

            # Transform position to world space
            for j in range(3):
                world_pos[j] = 0
                for k in range(3):
                    world_pos[j] += vert.co[k] * matrix_world[k][j]
                world_pos[j] += matrix_world[3][j]

            # Transform normal to world space
            for j in range(3):
                world_normal[j] = 0
                for k in range(3):
                    world_normal[j] += vert.no[k] * matrix_normal[k][j]
            vec3_normalize(world_normal)

            # Calculate view direction
            if is_persp:
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
                    world_pos[0] * proj_matrix[0][j] +
                    world_pos[1] * proj_matrix[1][j] +
                    world_pos[2] * proj_matrix[2][j] +
                    proj_matrix[3][j]
                )

            if screen_pos[3] <= 0:  # Behind camera
                continue

            # Perspective divide and bounds check
            if (fabs(screen_pos[0] / screen_pos[3]) <= margin_check and 
                fabs(screen_pos[1] / screen_pos[3]) <= margin_check):
                is_vert_visible[i] = 1
                visible_vert_indices[vert.head.index] = 1

        # Compute visible edges and faces based on vertices.
        with parallel():
            for i in prange(totedge):
                edge = etable[i]
                if edge == NULL:
                    continue
                if visible_vert_indices[(<BMVert*>edge.v1).head.index] or\
                   visible_vert_indices[(<BMVert*>edge.v2).head.index]:
                    is_edge_visible[i] = 1

            for j in prange(totface):
                face = ftable[i]
                if face == NULL:
                    continue
                loop = <BMLoop*>face.l_first
                if loop == NULL:
                    continue
                for k in prange(face.len):
                    if visible_vert_indices[(<BMVert*>loop.v).head.index]:
                        is_face_visible[i] = 1
                        break
                    else:
                        loop = <BMLoop*>loop.next
                        if loop == NULL:
                            break
    '''

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
