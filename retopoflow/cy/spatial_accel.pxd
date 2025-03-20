# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=True

from libcpp.vector cimport vector


# Define geometry types
cpdef enum GeomType:
    VERT = 0
    EDGE = 1
    FACE = 2

# Geometry element structure
cdef struct GeomElement:
    void* elem
    int index
    float x
    float y
    float depth
    GeomType geom_type

# Define comparison function for sorting GeomElements by distance
cdef struct ElementWithDistance:
    GeomElement* element
    float distance

# Cell structure containing geometry elements
cdef struct Cell:
    GeomElement* elements
    int count
    int capacity

# Convert to struct instead of class
cdef struct SpatialAccel:
    float min_x, min_y, max_x, max_y
    int grid_width, grid_height
    float cell_size_x, cell_size_y
    Cell** grid
    bint is_initialized

# Function declarations that operate on the SpatialAccel struct
cdef void spatial_accel_cleanup(SpatialAccel* accel) noexcept nogil
cdef void spatial_accel_init(SpatialAccel* accel, float min_x, float min_y, float max_x, float max_y, int grid_width, int grid_height) noexcept nogil
cdef void spatial_accel_reset(SpatialAccel* accel) noexcept nogil
cdef void spatial_accel_get_cell_indices(SpatialAccel* accel, float x, float y, int* cell_x, int* cell_y) noexcept nogil
cdef void spatial_accel_add_element(SpatialAccel* accel, void* elem, int index, float x, float y, float depth, GeomType geom_type) noexcept nogil
cdef ElementWithDistance spatial_accel_find_elem(SpatialAccel* accel, float x, float y, float depth, float max_dist, GeomType geom_type, bint use_epsilon)
cdef float spatial_accel_element_distance(SpatialAccel* accel, GeomElement* elem, float x, float y, float depth) noexcept nogil
cdef vector[ElementWithDistance] spatial_accel_find_k_elem(SpatialAccel* accel, float x, float y, float depth, float max_dist, GeomType geom_type, int k)
cdef vector[GeomElement*] spatial_accel_find_elem_in_area(SpatialAccel* accel, float x, float y, float depth, GeomType geom_type, float radius)
cdef vector[GeomElement*] spatial_accel_find_k_elem_in_area(SpatialAccel* accel, float x, float y, float depth, GeomType geom_type, float radius, int k)

# Global pointer to current SpatialAccel instance
# cdef:
#     SpatialAccel* global_accel

# Functions to create and destroy SpatialAccel
cdef SpatialAccel* spatial_accel_new() noexcept nogil
cdef void spatial_accel_free(SpatialAccel* accel) noexcept nogil