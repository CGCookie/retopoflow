# spatial_accel.pyx
# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=True

# Import the structs and types from the .pxd file
from retopoflow.cy.spatial_accel cimport GeomType, GeomElement, Cell, SpatialAccel, ElementWithDistance
from retopoflow.cy.bl_types.bmesh_types cimport BMElem

from libc.stdlib cimport malloc, free
from libc.math cimport sqrt, floor, fabs
from libcpp.vector cimport vector
from libcpp.algorithm cimport sort
from libcpp cimport bool


cdef float finf = <float>1e1000

# C helper functions for use in nogil context
cdef int c_min(int a, int b) noexcept nogil:
    return a if a < b else b

cdef int c_max(int a, int b) noexcept nogil:
    return a if a > b else b

cdef float c_fabs(float a) noexcept nogil:
    return a if a >= 0 else -a


cdef bool compare_by_distance(const ElementWithDistance& a, const ElementWithDistance& b) noexcept nogil:
    return a.distance < b.distance

# Create a new SpatialAccel
cdef SpatialAccel* spatial_accel_new() noexcept nogil:
    cdef SpatialAccel* accel = <SpatialAccel*>malloc(sizeof(SpatialAccel))
    accel.grid = NULL
    accel.is_initialized = False
    return accel

# Free a SpatialAccel
cdef void spatial_accel_free(SpatialAccel* accel) noexcept nogil:
    if accel != NULL:
        spatial_accel_cleanup(accel)
        free(accel)

# Clear all cells in the grid
cdef void spatial_accel_reset(SpatialAccel* accel) noexcept nogil:
    cdef int i, j
    for i in range(accel.grid_width):
        for j in range(accel.grid_height):
            if accel.grid[i][j].elements != NULL:
                free(accel.grid[i][j].elements)
            accel.grid[i][j].elements = NULL
            accel.grid[i][j].count = 0
            accel.grid[i][j].capacity = 0

# Clean up any allocated resources
cdef void spatial_accel_cleanup(SpatialAccel* accel) noexcept nogil:
    if not accel.is_initialized:
        return
        
    cdef int i, j
    for i in range(accel.grid_width):
        for j in range(accel.grid_height):
            if accel.grid[i][j].elements != NULL:
                free(accel.grid[i][j].elements)
        if accel.grid[i] != NULL:
            free(accel.grid[i])
    if accel.grid != NULL:
        free(accel.grid)
        accel.grid = NULL
    
    accel.is_initialized = False

# Initialize or re-initialize the spatial acceleration structure
cdef void spatial_accel_init(SpatialAccel* accel, float min_x, float min_y, float max_x, float max_y, 
          int grid_width, int grid_height) noexcept nogil:
    # Clean up any existing resources first
    spatial_accel_cleanup(accel)
    
    # Set new parameters
    accel.min_x = min_x
    accel.min_y = min_y
    accel.max_x = max_x
    accel.max_y = max_y
    accel.grid_width = grid_width
    accel.grid_height = grid_height
    accel.cell_size_x = (max_x - min_x) / grid_width
    accel.cell_size_y = (max_y - min_y) / grid_height
    
    # Allocate grid
    accel.grid = <Cell**>malloc(grid_width * sizeof(Cell*))
    cdef int i, j
    for i in range(grid_width):
        accel.grid[i] = <Cell*>malloc(grid_height * sizeof(Cell))
        for j in range(grid_height):
            accel.grid[i][j].elements = NULL
            accel.grid[i][j].count = 0
            accel.grid[i][j].capacity = 0
            
    accel.is_initialized = True

# Get cell indices from coordinates
cdef void spatial_accel_get_cell_indices(SpatialAccel* accel, float x, float y, int* cell_x, int* cell_y) noexcept nogil:
    cdef int i = <int>((x - accel.min_x) / accel.cell_size_x)
    cdef int j = <int>((y - accel.min_y) / accel.cell_size_y)
    
    # Clamp to grid bounds
    if i < 0: i = 0
    if i >= accel.grid_width: i = accel.grid_width - 1
    if j < 0: j = 0
    if j >= accel.grid_height: j = accel.grid_height - 1
    
    cell_x[0] = i
    cell_y[0] = j

# Add a geometry element to the appropriate cell
cdef void spatial_accel_add_element(SpatialAccel* accel, void* elem, int index, float x, float y, float depth, GeomType geom_type) noexcept nogil:
    cdef:
        int k
        int cell_x, cell_y
        int new_capacity
        Cell* cell
        GeomElement* new_elements

    spatial_accel_get_cell_indices(accel, x, y, &cell_x, &cell_y)
    
    cell = &accel.grid[cell_x][cell_y]
    
    # Resize if needed
    if cell.count >= cell.capacity:
        new_capacity = c_max(10, cell.capacity * 2)
        new_elements = <GeomElement*>malloc(new_capacity * sizeof(GeomElement))
        
        # Copy existing elements
        for k in range(cell.count):
            new_elements[k] = cell.elements[k]
        
        # Free old array and update
        if cell.elements != NULL:
            free(cell.elements)
        cell.elements = new_elements
        cell.capacity = new_capacity

    # Add new element
    cell.elements[cell.count].elem = elem
    cell.elements[cell.count].index = index  # (<BMElem*>elem).head.index
    cell.elements[cell.count].x = x
    cell.elements[cell.count].y = y
    cell.elements[cell.count].depth = depth
    cell.elements[cell.count].geom_type = geom_type
    cell.count += 1

# Find an element with matching coordinates, depth and type, returns NULL if not found
cdef ElementWithDistance spatial_accel_find_elem(SpatialAccel* accel, float x, float y, float depth, float max_dist, GeomType geom_type, bint use_epsilon):
    cdef int cell_x, cell_y
    spatial_accel_get_cell_indices(accel, x, y, &cell_x, &cell_y)
    cdef Cell* cell = &accel.grid[cell_x][cell_y]
    cdef int k
    cdef float epsilon = <float>1e-6  # Small threshold for float comparison
    cdef float closest_dist = finf
    cdef ElementWithDistance closest_elem_with_dist
    cdef float dist = finf

    for k in range(cell.count):
        if use_epsilon:
            if (c_fabs(cell.elements[k].x - x) < epsilon and
                c_fabs(cell.elements[k].y - y) < epsilon and
                c_fabs(cell.elements[k].depth - depth) < epsilon and
                cell.elements[k].geom_type == geom_type):
                closest_elem_with_dist.element = &cell.elements[k]
                closest_elem_with_dist.distance = 0.0  # Distance is zero if found
                return closest_elem_with_dist
        else:
            dist = spatial_accel_element_distance(accel, &cell.elements[k], x, y, depth)
            if dist <= max_dist and dist < closest_dist:
                closest_dist = dist
                closest_elem_with_dist.element = &cell.elements[k]
                closest_elem_with_dist.distance = closest_dist

    return closest_elem_with_dist

# Calculate distance between a point and an element
cdef float spatial_accel_element_distance(SpatialAccel* accel, GeomElement* elem, float x, float y, float depth) noexcept nogil:
    cdef float dx = elem.x - x
    cdef float dy = elem.y - y
    cdef float dd = elem.depth - depth
    return sqrt(dx*dx + dy*dy + dd*dd)

# Find k closest elements matching the criteria
cdef vector[ElementWithDistance] spatial_accel_find_k_elem(SpatialAccel* accel, float x, float y, float max_dist, float depth, GeomType geom_type, int k):
    cdef:
        int ni, nj, ei, i
        int cell_x, cell_y
        vector[ElementWithDistance] candidates
        vector[ElementWithDistance] result
        float dist
        ElementWithDistance element_with_dist
        Cell* cell
        int min_ni, max_ni, min_nj, max_nj
        int candidates_size, count
        
    spatial_accel_get_cell_indices(accel, x, y, &cell_x, &cell_y)
    
    # Calculate neighbor cell bounds
    min_ni = c_max(0, cell_x-1)
    max_ni = c_min(accel.grid_width, cell_x+2)
    min_nj = c_max(0, cell_y-1)
    max_nj = c_min(accel.grid_height, cell_y+2)
    
    # Search in current cell and neighboring cells
    for ni in range(min_ni, max_ni):
        for nj in range(min_nj, max_nj):
            cell = &accel.grid[ni][nj]
            
            for ei in range(cell.count):
                if cell.elements[ei].geom_type == geom_type:
                    dist = spatial_accel_element_distance(accel, &cell.elements[ei], x, y, depth)
                    element_with_dist.element = &cell.elements[ei]
                    element_with_dist.distance = dist
                    candidates.push_back(element_with_dist)
    
    # Sort by distance
    sort(candidates.begin(), candidates.end(), compare_by_distance)
    
    # Get the k closest elements
    candidates_size = candidates.size()
    count = c_min(k, candidates_size)
    for i in range(count):
        result.push_back(candidates[i])

    return result

# Find elements within radius of the given point
cdef vector[GeomElement*] spatial_accel_find_elem_in_area(SpatialAccel* accel, float x, float y, float depth, GeomType geom_type, float radius):
    cdef:
        vector[GeomElement*] result
        float search_x_min = x - radius
        float search_x_max = x + radius
        float search_y_min = y - radius
        float search_y_max = y + radius
        int min_i, min_j, max_i, max_j
        int i, j, k
        float dist
        Cell* cell
        int min_i_safe, max_i_safe, min_j_safe, max_j_safe
        
    spatial_accel_get_cell_indices(accel, search_x_min, search_y_min, &min_i, &min_j)
    spatial_accel_get_cell_indices(accel, search_x_max, search_y_max, &max_i, &max_j)
    
    # Calculate safe bounds
    min_i_safe = c_max(0, min_i)
    max_i_safe = c_min(accel.grid_width, max_i + 1)
    min_j_safe = c_max(0, min_j)
    max_j_safe = c_min(accel.grid_height, max_j + 1)
    
    # Search cells
    for i in range(min_i_safe, max_i_safe):
        for j in range(min_j_safe, max_j_safe):
            cell = &accel.grid[i][j]
            
            for k in range(cell.count):
                if cell.elements[k].geom_type == geom_type:
                    # Calculate 3D distance
                    dist = spatial_accel_element_distance(accel, &cell.elements[k], x, y, depth)
                    
                    if dist <= radius:
                        result.push_back(&cell.elements[k])
    
    return result

# Find k closest elements within radius
cdef vector[GeomElement*] spatial_accel_find_k_elem_in_area(SpatialAccel* accel, float x, float y, float depth, GeomType geom_type, float radius, int k):
    cdef:
        vector[GeomElement*] result
        vector[ElementWithDistance] candidates
        ElementWithDistance element_with_dist
        int i
        vector[GeomElement*] elements
        int elements_size, count
        
    # Get all matching elements in the area
    elements = spatial_accel_find_elem_in_area(accel, x, y, depth, geom_type, radius)
    elements_size = elements.size()
    
    # Convert to ElementWithDistance for sorting
    for i in range(elements_size):
        element_with_dist.element = elements[i]
        element_with_dist.distance = spatial_accel_element_distance(accel, elements[i], x, y, depth)
        candidates.push_back(element_with_dist)
    
    # Sort by distance
    sort(candidates.begin(), candidates.end(), compare_by_distance)
    
    # Get the k closest elements
    count = c_min(k, candidates.size())
    for i in range(count):
        result.push_back(candidates[i].element)
        
    return result

# Simple Python wrapper if still needed
'''class PySpatialAccel:
    def __init__(self):
        self._ptr = spatial_accel_new()
    
    def __del__(self):
        if self._ptr is not None:
            spatial_accel_free(self._ptr)
            self._ptr = None
    
    def init(self, min_x, min_y, max_x, max_y, grid_width, grid_height):
        spatial_accel_init(self._ptr, min_x, min_y, max_x, max_y, grid_width, grid_height)
    
    def add_element(self, elem_ptr, x, y, depth, geom_type):
        spatial_accel_add_element(self._ptr, <void*>elem_ptr, x, y, depth, geom_type)
'''