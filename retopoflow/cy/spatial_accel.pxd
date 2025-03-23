# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=True

from libcpp.list cimport list as cpp_list
from libcpp.algorithm cimport sort
from libcpp cimport bool


# Define geometry types
cpdef enum GeomType:
    VERT = 0
    EDGE = 1
    FACE = 2
    ANY = 3  # New type to allow searching for any geometry type

# Geometry element structure
cdef struct GeomElement:
    void* elem          # Pointer to the actual geometry element
    size_t index           # Index in the source collection
    float x, y, depth   # 3D position (2D + depth)
    GeomType geom_type  # Type of geometry
    int cell_x, cell_y
    size_t cell_index

# Structure for element with distance information for sorting
cdef struct ElementWithDistance:
    GeomElement* element  # Pointer to the geometry element
    float distance        # Distance from query point

# Cell structure for the spatial grid
cdef struct Cell:
    int totelem
    int* elem_indices  # Indices of the elements in this cell

# Main spatial acceleration structure
cdef struct SpatialAccel:
    # Bounds of the 2D grid
    float min_x, min_y, max_x, max_y
    
    # Grid dimensions
    int grid_cols, grid_rows
    
    # Size of each cell
    float cell_size_x, cell_size_y

    # All elements added to the spatial accel structure.
    int totelem
    GeomElement* elements

    # The 2D grid of cells
    Cell** grid  # references to the pointers at cells_memory.
    Cell* cells_memory  # here we store the real cells data.

    # Whether the structure is initialized
    bint is_initialized

# Core function declarations
cdef SpatialAccel* spatial_accel_new() noexcept nogil
cdef void spatial_accel_free(SpatialAccel* accel) noexcept nogil
cdef void spatial_accel_cleanup(SpatialAccel* accel) noexcept nogil
cdef void spatial_accel_init(SpatialAccel* accel, int totelem, float min_x, float min_y, float max_x, float max_y, int grid_cols, int grid_rows) noexcept nogil
cdef void spatial_accel_reset(SpatialAccel* accel) noexcept nogil

# Element management
cdef void spatial_accel_add_element(SpatialAccel* accel, int insert_index, void* elem, int index, float x, float y, float depth, GeomType geom_type) noexcept nogil
cdef void spatial_accel_update_grid_indices(SpatialAccel* accel) noexcept nogil

# Unified search function - replaces all the separate search functions
'''cdef cpp_list[ElementWithDistance] spatial_accel_get_nearest_elements(
    SpatialAccel* accel,
    float x, float y, float depth,  # Search position
    int k,                          # Number of elements to return (k=0 means all elements within max_dist)
    float max_dist,                 # Maximum search distance (max_dist=0 means unlimited)
    GeomType geom_type              # Type of geometry to search for
) noexcept nogil'''

# Utility functions
cdef void spatial_accel_get_cell_indices(SpatialAccel* accel, float x, float y, int* cell_x, int* cell_y) noexcept nogil
cdef float spatial_accel_element_distance(SpatialAccel* accel, GeomElement* elem, float x, float y, float depth) noexcept nogil