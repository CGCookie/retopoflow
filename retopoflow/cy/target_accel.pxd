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

from .bl_types.bmesh_types cimport BMVert, BMEdge, BMFace, BMesh, BMesh, BMHeader
from .bl_types.bmesh_py_wrappers cimport BPy_BMesh
from .bl_types cimport ARegion, RegionView3D


cdef enum SelectionState:
    ALL = 0
    SELECTED = 1
    UNSELECTED = 2

cdef struct View3D:
    float[4][4] proj_matrix
    float[3] view_pos
    bint is_persp

cdef enum GeomType:
    NONE = -1
    VERT = 0
    EDGE = 1
    FACE = 2

# Structure to hold geometry element info
cdef struct GeomElement:
    void* elem           # BMVert*, BMEdge*, or BMFace*
    float[2] pos        # 2D screen position
    float depth         # View depth
    GeomType type       # Type of element
    
# Structure for grid cell
cdef struct GridCell:
    vector[GeomElement] elements

cdef class TargetMeshAccel:
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

        # Accel structure.
        # Accel accel

        # Grid acceleration structure
        GridCell** grid
        int grid_size_x
        int grid_size_y
        int cell_size
        float cell_size_x
        float cell_size_y
        float min_x, min_y
        float max_x, max_y
        
    # Methods for grid operations
    cdef void _init_grid(self) noexcept nogil
    cdef void _clear_grid(self) noexcept nogil
    cdef void _get_cell_coords(self, float x, float y, int* cell_x, int* cell_y) noexcept nogil
    cdef void _add_element_to_grid(self, GeomElement* elem) noexcept nogil
    cdef float _compute_distance_2d(self, float x1, float y1, float x2, float y2) noexcept nogil
    cdef void _find_cells_in_range(self, float x, float y, float radius, 
                            vector[GridCell*]* cells) noexcept nogil
    
    # Search methods
    cdef GeomElement* _find_nearest(self, float x, float y, float max_dist, 
                                GeomType filter_type) noexcept nogil
    cdef void _find_nearest_k(self, float x, float y, int k, float max_dist,
                        GeomType filter_type, vector[GeomElement]* results) noexcept nogil

    # cpdef void update_matrix_world(self, object py_matrix_world)
    cdef void _update_view(self, const float[:, ::1] proj_matrix, const float[::1] view_pos, bint is_perspective) nogil
    cdef void _update_object_transform(self, const float[:, ::1] matrix_world, const float[:, ::1] matrix_normal) nogil
    # cdef void _build_accel_struct(self) noexcept nogil
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

    cdef void _build_accel_struct(self) noexcept nogil
    cdef void add_vert_to_grid(self, BMVert* vert) noexcept nogil
    cdef void add_edge_to_grid(self, BMEdge* edge, int num_samples) noexcept nogil
    cdef void add_face_to_grid(self, BMFace* face) noexcept nogil
    cdef void _project_point_to_screen(self, const float[3] world_pos, float[2] screen_pos, float* depth) noexcept nogil


    # ---------------------------------------------------------------------------------------
    # Python exposed methods.
    # ---------------------------------------------------------------------------------------

    # Single nearest element methods
    cpdef dict find_nearest_vert(self, float x, float y, float max_dist=*)
    cpdef dict find_nearest_edge(self, float x, float y, float max_dist=*)
    cpdef dict find_nearest_face(self, float x, float y, float max_dist=*)
    
    # k nearest elements methods
    cpdef list find_k_nearest_verts(self, float x, float y, int k, float max_dist=*)
    cpdef list find_k_nearest_edges(self, float x, float y, int k, float max_dist=*)
    cpdef list find_k_nearest_faces(self, float x, float y, int k, float max_dist=*)
