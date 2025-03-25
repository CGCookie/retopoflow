# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=False
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=True

from libc.stdint cimport uint8_t
from libcpp.set cimport set as cpp_set
import numpy as np
cimport numpy as np
from libcpp.vector cimport vector
from cpython.object cimport PyObject

from .bl_types.bmesh_types cimport BMVert, BMEdge, BMFace, BMesh, BMesh, BMHeader, BMElem
from .bl_types.bmesh_py_wrappers cimport BPy_BMesh
from .bl_types cimport ARegion, RegionView3D
from .vector_utils cimport bVec3
from .bl_types.vec_types cimport rcti, rctf
from .spatial_accel cimport SpatialAccel, spatial_accel_new, spatial_accel_free, spatial_accel_init, spatial_accel_cleanup, spatial_accel_reset
from .spatial_accel cimport spatial_accel_add_element, spatial_accel_update_grid_indices, spatial_accel_get_nearest_elements
from .spatial_accel cimport GeomType as SpatialGeomType, GeomElement as SpatialGeomElement, ElementWithDistance as SpatialElementWithDistance


cdef enum SelectionState:
    ALL = 0
    SELECTED = 1
    UNSELECTED = 2

cdef struct View3D:
    float[4][4] proj_matrix
    float[3] view_pos
    float[3] view_dir
    bint is_persp

cdef enum GeomType:
    BM_NONE = -1
    BM_VERT = 0
    BM_EDGE = 1
    BM_FACE = 2
    BM_ALL = 3


cdef class TargetMeshAccel:
    cdef:
        bint is_dirty_geom_vis
        bint is_dirty_accel

        object py_object
        object py_region
        object py_rv3d
        object py_bmesh

        object vert_wrapper
        object edge_wrapper
        object face_wrapper

        # BMesh reference
        BPy_BMesh* bmesh_pywrapper
        BMesh* bmesh
        ARegion* region
        RegionView3D* rv3d

        int selected_only
        bVec3 use_symmetry

        float[4][4] matrix_world
        float[3][3] matrix_normal
        View3D view3d

        float screen_margin

        # Store latest values of totvert, totedge, totface.
        int last_totvert
        int last_totedge
        int last_totface

        uint8_t* is_vert_visible
        uint8_t* is_edge_visible
        uint8_t* is_face_visible

        # Change C++ sets to C arrays for storing geometry
        BMVert** visverts
        BMEdge** visedges  
        BMFace** visfaces

        # Verts/Edges/Faces count.
        int totvisverts
        int totvisedges
        int totvisfaces

        # Grid acceleration structure
        SpatialAccel* accel

    # Space-conversion utilities.
    cdef void l2w_point(self, const float[3] point3d, float[2] point2d) noexcept nogil
    cdef void project_wpoint_to_region_2d(self, float[3] world_pos, float[2] point2d) noexcept nogil
    cdef void project_lpoint_to_region_2d(self, float[3] local_pos, float[2] point2d) noexcept nogil
    cdef void project_vert_to_region_2d(self, BMVert* vert, float[2] point2d) noexcept nogil

    # Selection utils.
    cdef bint deselect_all(self, GeomType geom_type=*) noexcept nogil

    cdef void _update_view(self, const float[:, ::1] proj_matrix, const float[::1] view_pos, const float[::1] view_dir, bint is_perspective) nogil
    cdef void _update_object_transform(self, const float[:, ::1] matrix_world, const float[:, ::1] matrix_normal) nogil
    cdef void _reset(self, bint dirty=*) noexcept nogil
    cdef void set_dirty(self) noexcept nogil
    cdef int _compute_geometry_visibility_in_region(self, float margin_check, int selection_mode) noexcept nogil

    cdef void _build_accel_struct(self, bint debug=*) noexcept nogil
    cdef void add_vert_to_grid(self, BMVert* vert, int insert_index) noexcept nogil
    cdef void add_edge_to_grid(self, BMEdge* edge, int insert_index, int num_samples) noexcept nogil
    cdef void add_face_to_grid(self, BMFace* face, int insert_index) noexcept nogil
    cdef void _project_point_to_screen(self, const float[3] world_pos, float[2] screen_pos, float* depth) noexcept nogil

    # ---------------------------------------------------------------------------------------
    # Python exposed methods.
    # ---------------------------------------------------------------------------------------

    cpdef void update(self, float margin_check, int selection_mode, bint debug=*)

    cpdef int ensure_bmesh(self)

    cpdef void py_set_dirty_accel(self)
    cpdef void py_set_dirty_geom_vis(self)
    cpdef void py_set_symmetry(self, bint x, bint y, bint z)

    cpdef void py_update_object(self, object py_target_object)
    cpdef void py_update_region(self, object py_region)
    cpdef void py_update_view(self, object py_rv3d)
    cpdef void py_update_bmesh(self, object py_bmesh)

    cpdef bint py_update_geometry_visibility(self, float margin_check, int selection_mode, bint update_accel)
    cpdef void py_update_accel_struct(self)

    # Base nearest search method.
    cpdef object _find_nearest(self, float x, float y, float depth, SpatialGeomType geom_type, int k=*, float max_dist=*, bint wrapped=*)

    # Single nearest element methods
    cpdef object find_nearest_vert(self, float x, float y, float depth, float max_dist=*, bint wrapped=*)
    cpdef object find_nearest_edge(self, float x, float y, float depth, float max_dist=*, bint wrapped=*)
    cpdef object find_nearest_face(self, float x, float y, float depth, float max_dist=*, bint wrapped=*)
    cpdef tuple find_nearest_geom(self, float x, float y, float depth, float max_dist=*, bint wrapped=*)

    # k nearest elements methods
    cpdef list find_k_nearest_verts(self, float x, float y, float depth, int k=*, float max_dist=*, bint wrapped=*)
    cpdef list find_k_nearest_edges(self, float x, float y, float depth, int k=*, float max_dist=*, bint wrapped=*)
    cpdef list find_k_nearest_faces(self, float x, float y, float depth, int k=*, float max_dist=*, bint wrapped=*)

    cpdef tuple[set, set, set] get_visible_geom(self, object py_bmesh, bint verts=*, bint edges=*, bint faces=*, bint invert_selection=*, bint wrapped=*)
    cpdef tuple[set, set, set] get_selected_geom(self, object py_bmesh, bint verts=*, bint edges=*, bint faces=*, bint invert_selection=*)

    # Select-Box.
    cdef bint _segment2D_intersection(self, float[2] p0, float[2] p1, float[2] p2, float[2] p3) noexcept nogil
    cdef bint _triangle2D_overlap(self, float[3][2] tri1, float[3][2] tri2) noexcept nogil
    cdef bint select_box(self, float left, float right, float bottom, float top, GeomType select_geometry_type, bint use_ctrl=*, bint use_shift=*) noexcept nogil
    cdef bint _vert_inside_box(self, BMVert* vert, float[4] box) noexcept nogil
    cpdef bint py_select_box(self, float left, float right, float bottom, float top, int select_geometry_type, bint use_ctrl=*, bint use_shift=*)
