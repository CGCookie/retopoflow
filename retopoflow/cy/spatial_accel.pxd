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
    float x
    float y
    float depth
    GeomType geom_type

# Cell structure containing geometry elements
cdef struct Cell:
    GeomElement* elements
    int count
    int capacity

cdef class SpatialAccel:
    cdef:
        float min_x, min_y, max_x, max_y
        int grid_width, grid_height
        float cell_size_x, cell_size_y
        Cell** grid
        bint is_initialized
    
    cdef void cleanup(self) noexcept nogil
    cdef void init(self, float min_x, float min_y, float max_x, float max_y, int grid_width, int grid_height) noexcept nogil
    cdef void reset(self) noexcept nogil
    cdef void get_cell_indices(self, float x, float y, int* cell_x, int* cell_y) noexcept nogil
    cdef void add_element(self, void* elem, float x, float y, float depth, GeomType geom_type) noexcept nogil
    
    # Find functions with nogil and C++ return types
    cdef GeomElement* find_elem(self, float x, float y, float depth, GeomType geom_type) noexcept nogil
    cdef float element_distance(self, GeomElement* elem, float x, float y, float depth) noexcept nogil
    cdef vector[GeomElement] find_k_elem(self, float x, float y, float depth, GeomType geom_type, int k=*) noexcept nogil
    cdef vector[GeomElement] find_elem_in_area(self, float x, float y, float depth, GeomType geom_type, float radius) noexcept nogil
    cdef vector[GeomElement] find_k_elem_in_area(self, float x, float y, float depth, GeomType geom_type, float radius, int k=*) noexcept nogil
    
    # Python-accessible wrappers
    # cpdef object py_find_elem(self, float x, float y, float depth, GeomType geom_type)
    # cpdef list py_find_k_elem(self, float x, float y, float depth, GeomType geom_type, int k=*)
    # cpdef list py_find_elem_in_area(self, float x, float y, float depth, GeomType geom_type, float radius)
    # cpdef list py_find_k_elem_in_area(self, float x, float y, float depth, GeomType geom_type, float radius, int k=*)
