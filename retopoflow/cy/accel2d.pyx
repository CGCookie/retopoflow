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

# from cpython.ref cimport Py_INCREF, Py_DECREF
# from cpython.object cimport PyObject, PyObject_CallMethod, PyObject_GetAttr, PyObject_SetAttr


# from mathutils import Matrix as py_Matrix
# from bmesh.types import BMesh as py_BMesh
# from bpy.types import Region as py_Region, RegionView3D as py_RegionView3D

# ctypedef np.uint8_t uint8


@cython.binding(True)
cdef class Accel2D:
    def __cinit__(self):
        # Initialize C++ member variables
        self.is_hidden_v = NULL
        self.is_hidden_e = NULL
        self.is_hidden_f = NULL
        self.is_selected_v = NULL
        self.is_selected_e = NULL
        self.is_selected_f = NULL

    def __init__(self,
        object py_bmesh,
        # object py_object,
        object py_region,
        object py_rv3d,
        # int selected_only,
        np.ndarray[np.float32_t, ndim=2] matrix_world,
        np.ndarray[np.float32_t, ndim=2] matrix_normal,
        np.ndarray[np.float32_t, ndim=2] proj_matrix,
        np.ndarray[np.float32_t, ndim=1] view_pos,
        bint is_perspective
    ):
        print(f"[CYTHON] Accel2D.__init__({py_bmesh}, {py_region}, {py_rv3d}, {matrix_world}, {matrix_normal}, {proj_matrix}, {view_pos}, {is_perspective})\n")
        self._ensure_lookup_tables(py_bmesh)
        self.py_bmesh = <BPy_BMesh*><uintptr_t>id(py_bmesh)
        self.bmesh = self.py_bmesh.bm
        # check if valid BMesh and tables.
        self.region = <ARegion*><uintptr_t>id(py_region)
        self.rv3d = <RegionView3D*><uintptr_t>id(py_rv3d)
        # self.selected_only = selected_only
        # self.update_matrix_world(py_object.matrix_world)

        self._update_object_transform(matrix_world, matrix_normal)
        self._update_view(proj_matrix, view_pos, is_perspective)

        if self._compute_geometry_visibility_in_region(1.0) != 0:
            print("[CYTHON] Error: Failed to compute geometry visibility in region\n")

        # self._build_accel_struct()

    def __dealloc__(self):
        self._reset()

    cdef void _update_object_transform(self, const float[:, ::1] matrix_world, const float[:, ::1] matrix_normal) nogil:
        cdef:
            int i, j

        for i in range(4):
            for j in range(4):
                self.matrix_world[i][j] = matrix_world[i][j]

    cdef void _update_view(self, const float[:, ::1] proj_matrix, const float[::1] view_pos, bint is_perspective) nogil:
        cdef:
            int i, j

        for i in range(4):
            for j in range(4):
                self.view3d.proj_matrix[i][j] = proj_matrix[i][j]

        for i in range(3):
            self.view3d.view_pos[i] = view_pos[i]

        self.view3d.is_persp = is_perspective

    '''
    cpdef void update_matrix_world(self, object py_matrix_world):
        # Matrix World.
        print(f"[CYTHON] Accel2D.update_matrix_world({py_matrix_world})\n")
        for i in range(4):
            for j in range(4):
                self.matrix_world[i][j] = py_matrix_world[i][j]
        
        self._update_matrices()

        print(f'[CYTHON]MATRIX AND VIEW PROPS: {self.matrix_world=} {self.matrix_normal=} {self.view3d.proj_matrix=} {self.view3d.is_persp=} {self.view3d.view_pos=}')

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
            mat4_get_translation(mat_temp_1, self.view3d.view_pos)
        else:
            mat4_get_col3(mat_temp_1, 2, self.view3d.view_pos)
    '''

    cpdef void _ensure_lookup_tables(self, object py_bmesh):
        """Ensure lookup tables are created for the bmesh"""
        try:
            py_bmesh.verts[0]
        except IndexError:
            print(f"[CYTHON] py_bmesh.verts.ensure_lookup_table()\n")
            py_bmesh.verts.ensure_lookup_table()
        try:
            py_bmesh.edges[0]
        except IndexError:
            print(f"[CYTHON] py_bmesh.edges.ensure_lookup_table()\n")
            py_bmesh.edges.ensure_lookup_table()
        try:
            py_bmesh.faces[0]
        except IndexError:
            print(f"[CYTHON] py_bmesh.faces.ensure_lookup_table()\n")
            py_bmesh.faces.ensure_lookup_table()

    cdef int _compute_geometry_visibility_in_region(self, float margin_check) nogil:
        if self.bmesh == NULL or self.bmesh.vtable == NULL or self.bmesh.etable == NULL or self.bmesh.ftable == NULL:
            printf("[CYTHON] Error: Accel2D._compute_geometry_visibility_in_region() - bmesh or vtable is NULL\n")
            return -1

        cdef:
            uint8_t* visible_vert_indices = NULL
            uint8_t* is_vert_visible = NULL
            uint8_t* is_edge_visible = NULL
            uint8_t* is_face_visible = NULL
            size_t i, j, k, count = 0
            size_t vert_idx, edge_idx, face_idx
            float[3] world_pos
            float[3] world_normal
            float[3] view_dir
            float[4] screen_pos
            BMVert* vert
            BMEdge* edge
            BMFace* face
            BMLoop* loop
            size_t totvisvert = 0
            size_t totvisedge = 0
            size_t totvisface = 0
            
            # Cache BMesh data before nogil section
            BMVert** vtable = self.bmesh.vtable
            BMEdge** etable = self.bmesh.etable
            BMFace** ftable = self.bmesh.ftable
            size_t totvert = self.bmesh.totvert
            size_t totedge = self.bmesh.totedge
            size_t totface = self.bmesh.totface
            View3D view3d = self.view3d
            bint is_persp = view3d.is_persp
        
        self._reset()

        # Allocate memory
        visible_vert_indices = <uint8_t*>malloc(totvert * sizeof(uint8_t))
        is_vert_visible = <uint8_t*>malloc(totvert * sizeof(uint8_t))
        is_edge_visible = <uint8_t*>malloc(totedge * sizeof(uint8_t))
        is_face_visible = <uint8_t*>malloc(totface * sizeof(uint8_t))

        if visible_vert_indices == NULL or is_vert_visible == NULL or\
            is_edge_visible == NULL or is_face_visible == NULL:
            printf("[CYTHON] Error: Failed to allocate memory\n")
            if visible_vert_indices != NULL:
                free(visible_vert_indices)
            if is_vert_visible != NULL:
                free(is_vert_visible)
            if is_edge_visible != NULL:
                free(is_edge_visible)
            if is_face_visible != NULL:
                free(is_face_visible)
            return -1

        self.is_hidden_v = <uint8_t*>malloc(totvert * sizeof(uint8_t))
        self.is_hidden_e = <uint8_t*>malloc(totedge * sizeof(uint8_t))
        self.is_hidden_f = <uint8_t*>malloc(totface * sizeof(uint8_t))

        self.is_selected_v = <uint8_t*>malloc(totvert * sizeof(uint8_t))
        self.is_selected_e = <uint8_t*>malloc(totedge * sizeof(uint8_t))
        self.is_selected_f = <uint8_t*>malloc(totface * sizeof(uint8_t))

        if self.is_hidden_v == NULL or self.is_hidden_e == NULL or self.is_hidden_f == NULL or\
            self.is_selected_v == NULL or self.is_selected_e == NULL or self.is_selected_f == NULL:
            printf("[CYTHON]Error: Failed to allocate memory\n")
            if self.is_hidden_v != NULL:
                free(self.is_hidden_v)
            if self.is_hidden_e != NULL:
                free(self.is_hidden_e)
            if self.is_hidden_f != NULL:
                free(self.is_hidden_f)
            if self.is_selected_v != NULL:
                free(self.is_selected_v)
            if self.is_selected_e != NULL:
                free(self.is_selected_e)
            if self.is_selected_f != NULL:
                free(self.is_selected_f)
            return -1

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
        for vert_idx in prange(totvert, nogil=True, schedule='static'):
            vert = vtable[vert_idx]
            # Skip NULL/invalid vertices.
            if vert == NULL:
                continue
            
            self._classify_elem(
                &vert.head, vert_idx,
                self.is_hidden_v,
                self.is_selected_v
            )

            # Skip hidden vertices.
            if self.is_hidden_v[vert_idx]:
                continue

            # Transform position to world space
            for j in range(3):
                world_pos[j] = 0.0
                for k in range(3):
                    world_pos[j] += vert.co[k] * self.matrix_world[k][j]
                world_pos[j] += self.matrix_world[3][j]

            # Transform normal to world space
            for j in range(3):
                world_normal[j] = 0.0
                for k in range(3):
                    world_normal[j] += vert.no[k] * self.matrix_normal[k][j]
            vec3_normalize(world_normal)

            # Calculate view direction
            if is_persp:
                for j in range(3):
                    view_dir[j] = world_pos[j] - view3d.view_pos[j]
                vec3_normalize(view_dir)
            else:
                for j in range(3):
                    view_dir[j] = view3d.view_pos[j]

            # Check if facing camera
            if vec3_dot(world_normal, view_dir) > 0:
                continue

            # Project to screen space
            for j in range(4):
                screen_pos[j] = (
                    world_pos[0] * view3d.proj_matrix[0][j] +
                    world_pos[1] * view3d.proj_matrix[1][j] +
                    world_pos[2] * view3d.proj_matrix[2][j] +
                    view3d.proj_matrix[3][j]
                )

            # Check if behind camera
            if screen_pos[3] <= 0:
                continue

            # Perspective divide and bounds check
            if (fabs(screen_pos[0] / screen_pos[3]) <= margin_check and 
                fabs(screen_pos[1] / screen_pos[3]) <= margin_check):
                is_vert_visible[vert_idx] = 1
                visible_vert_indices[vert.head.index] = 1
                totvisvert += 1

        # Compute visible edges and faces based on vertices.
        with parallel():
            for edge_idx in prange(totedge):
                edge = etable[edge_idx]
                if edge == NULL:
                    continue

                self._classify_elem(
                    &edge.head, edge_idx,
                    self.is_hidden_e,
                    self.is_selected_e
                )

                if self.is_hidden_e[edge_idx]:
                    continue

                if visible_vert_indices[(<BMVert*>edge.v1).head.index] or\
                   visible_vert_indices[(<BMVert*>edge.v2).head.index]:
                    is_edge_visible[edge_idx] = 1
                    totvisedge += 1

            for face_idx in prange(totface):
                face = ftable[face_idx]
                if face == NULL:
                    continue
                
                self._classify_elem(
                    &face.head, face_idx,
                    self.is_hidden_f,
                    self.is_selected_f
                )

                if self.is_hidden_f[face_idx]:
                    continue

                loop = <BMLoop*>face.l_first
                if loop == NULL:
                    continue
                for k in range(face.len):
                    if visible_vert_indices[(<BMVert*>loop.v).head.index]:
                        is_face_visible[face_idx] = 1
                        totvisface += 1
                        break
                    else:
                        loop = <BMLoop*>loop.next
                        if loop == NULL:
                            break

        self.totvisverts = totvisvert
        self.totvisedges = totvisedge
        self.totvisfaces = totvisface

        with parallel():
            for vert_idx in prange(totvert):
                if is_vert_visible[vert_idx]:
                    self.visverts.insert(vtable[vert_idx])
            for edge_idx in prange(totedge):
                if is_edge_visible[edge_idx]:
                    self.visedges.insert(etable[edge_idx])
            for face_idx in prange(totface):
                if is_face_visible[face_idx]:
                    self.visfaces.insert(ftable[face_idx])

        return 0

    cdef void _classify_elem(self, BMHeader* head, size_t index, uint8_t* is_hidden_array, uint8_t* is_selected_array) noexcept nogil:
        """Classify element based on selection and visibility flags."""
        is_hidden_array[index]= BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_HIDDEN)
        is_selected_array[index] = BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_SELECT)

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


    cdef void _reset(self) noexcept nogil:
        """Reset the acceleration structure"""
        # printf("Accel2D._reset()\n")

        if self.is_hidden_v != NULL:
            free(self.is_hidden_v)
        if self.is_hidden_e != NULL:
            free(self.is_hidden_e)
        if self.is_hidden_f != NULL:
            free(self.is_hidden_f)
        
        if self.is_selected_v != NULL:
            free(self.is_selected_v)
        if self.is_selected_e != NULL:
            free(self.is_selected_e)
        if self.is_selected_f != NULL:
            free(self.is_selected_f)

        # Set memory views to empty
        self.is_hidden_v = NULL
        self.is_hidden_e = NULL
        self.is_hidden_f = NULL
        
        self.is_selected_v = NULL
        self.is_selected_e = NULL
        self.is_selected_f = NULL

        # For C++ sets, we don't need to check for NULLs, just clear them!
        self.visverts.clear()
        self.visedges.clear()
        self.visfaces.clear()

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
                if self.is_hidden_v[i] if not invert_selection else not self.is_hidden_v[i]:
                    vis_py_verts.add(py_bm_verts[i])

        if edges:
            for i in range(bmesh.totedge):
                if self.is_hidden_e[i] if not invert_selection else not self.is_hidden_e[i]:
                    vis_py_edges.add(py_bm_edges[i])

        if faces:
            for i in range(bmesh.totface):
                if self.is_hidden_f[i] if not invert_selection else not self.is_hidden_f[i]:
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
                if self.is_selected_v[i] if not invert_selection else not self.is_selected_v[i]:
                    sel_py_verts.add(py_bm_verts[i])

        if edges:
            for i in range(bmesh.totedge):
                if self.is_selected_e[i] if not invert_selection else not self.is_selected_e[i]:
                    sel_py_edges.add(py_bm_edges[i])

        if faces:
            for i in range(bmesh.totface):
                if self.is_selected_f[i] if not invert_selection else not self.is_selected_f[i]:
                    sel_py_faces.add(py_bm_faces[i])

        return sel_py_verts, sel_py_edges, sel_py_faces

    def get_vis_verts(self, object py_bmesh, int selected_only) -> set:
        cdef:
            object py_bm_verts = py_bmesh.verts

        if selected_only == SelectionState.ALL:
            return {py_bm_verts[self.bmesh.vtable[i].head.index] for i in range(self.bmesh.totvert)}
        elif selected_only == SelectionState.SELECTED:
            return {py_bm_verts[self.bmesh.vtable[i].head.index] for i in range(self.bmesh.totvert) if self.is_selected_v[i]}
        elif selected_only == SelectionState.UNSELECTED:
            return {py_bm_verts[self.bmesh.vtable[i].head.index] for i in range(self.bmesh.totvert) if not self.is_selected_v[i]}
        else:
            return set()

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
            np.PyArray_SimpleNewFromData(1, &vert_size, np.NPY_UINT8, self.is_hidden_v),
            np.PyArray_SimpleNewFromData(1, &edge_size, np.NPY_UINT8, self.is_hidden_e),
            np.PyArray_SimpleNewFromData(1, &face_size, np.NPY_UINT8, self.is_hidden_f)
        )

    def get_selected_arrays(self):
        """Get selected arrays as NumPy arrays (zero-copy)"""
        cdef:
            BMesh* bmesh = self.py_bmesh.bm
            np.npy_intp vert_size = bmesh.totvert
            np.npy_intp edge_size = bmesh.totedge
            np.npy_intp face_size = bmesh.totface

        return (
            np.PyArray_SimpleNewFromData(1, &vert_size, np.NPY_UINT8, self.is_selected_v),
            np.PyArray_SimpleNewFromData(1, &edge_size, np.NPY_UINT8, self.is_selected_e),
            np.PyArray_SimpleNewFromData(1, &face_size, np.NPY_UINT8, self.is_selected_f)
        )

    cdef np.ndarray get_is_visible_verts_array(self):
        """Get visible array of vertices as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totvert
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_hidden_v)

    cdef np.ndarray get_is_visible_edges_array(self):
        """Get visible array of edges as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totedge
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_hidden_e)

    cdef np.ndarray get_is_visible_faces_array(self):
        """Get visible array of faces as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totface
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_hidden_f)

    cdef np.ndarray get_is_selected_verts_array(self):
        """Get selected array of vertices as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totvert
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_selected_v)

    cdef np.ndarray get_is_selected_edges_array(self):
        """Get selected array of edges as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totedge
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_selected_e)

    cdef np.ndarray get_is_selected_faces_array(self):
        """Get selected array of faces as NumPy array (zero-copy)"""
        cdef size_t size = self.py_bmesh.bm.totface
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_selected_f)
