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
from retopoflow.cy.spatial_accel cimport GeomType, GeomElement, Cell, SpatialAccel, ElementWithDistance, cpp_list
from retopoflow.cy.bl_types.bmesh_types cimport BMElem

from libc.stdlib cimport malloc, free
from libc.math cimport sqrt, floor, fabs, isfinite
from libcpp.algorithm cimport sort
from libcpp cimport bool

from cython.parallel cimport parallel, prange

# Utility constants
cdef float FLOAT_INFINITY = <float>1e6
cdef float EPSILON = <float>1e-6

# C helper functions for nogil context
cdef inline int c_min(int a, int b) noexcept nogil:
    return a if a < b else b

cdef inline int c_max(int a, int b) noexcept nogil:
    return a if a > b else b

cdef inline float c_fmin(float a, float b) noexcept nogil:
    return a if a < b else b

cdef inline float c_fmax(float a, float b) noexcept nogil:
    return a if a > b else b

cdef inline float c_fabs(float a) noexcept nogil:
    return a if a >= 0 else -a

# Comparison function for sorting elements by distance
cdef bool compare_by_distance(const ElementWithDistance& a, const ElementWithDistance& b) noexcept nogil:
    if a.element == NULL or b.element == NULL:
        return False
    return a.distance < b.distance

# ======================================================================================
# Memory Management Functions
# ======================================================================================

cdef SpatialAccel* spatial_accel_new() noexcept nogil:
    """
    Allocate a new SpatialAccel structure and initialize all fields.
    
    Returns:
        A pointer to the newly allocated SpatialAccel structure, or NULL if allocation failed.
    """
    cdef SpatialAccel* accel = <SpatialAccel*>malloc(sizeof(SpatialAccel))
    if accel != NULL:
        # Initialize all fields to safe values
        accel.grid = NULL
        accel.is_initialized = False
        accel.grid_cols = 0
        accel.grid_rows = 0
        accel.min_x = 0.0
        accel.min_y = 0.0
        accel.max_x = 0.0
        accel.max_y = 0.0
        accel.cell_size_x = 0.0
        accel.cell_size_y = 0.0
    return accel

cdef void spatial_accel_free(SpatialAccel* accel) noexcept nogil:
    """Free a SpatialAccel structure and its resources."""
    if accel != NULL:
        spatial_accel_cleanup(accel)
        free(accel)

cdef void spatial_accel_reset(SpatialAccel* accel) noexcept nogil:
    """Clear all cells in the grid without deallocating the grid itself."""
    if accel == NULL or not accel.is_initialized or accel.grid == NULL:
        return

    cdef int i, j
    # TODO: reset elements and grid elements.

cdef void spatial_accel_cleanup(SpatialAccel* accel) noexcept nogil:
    """Clean up all allocated resources in a SpatialAccel structure."""
    if accel == NULL or not accel.is_initialized:
        return

    cdef int cell_idx
    cdef Cell* cell  # Declare as pointer since we're accessing a Cell struct

    # Free the contiguous cell memory
    if accel.cells_memory != NULL:
        # Free indices.
        for cell_idx in range(accel.grid_cols * accel.grid_rows):
            cell = &accel.cells_memory[cell_idx]  # Get pointer to the cell
            if cell.elem_indices != NULL:
                free(cell.elem_indices)
                cell.elem_indices = NULL
                cell.totelem = 0

        free(accel.cells_memory)
        accel.cells_memory = NULL

    if accel.grid != NULL:
        free(accel.grid)
        accel.grid = NULL

    if accel.elements != NULL:
        free(accel.elements)
        accel.elements = NULL

    # Reset all other fields
    accel.is_initialized = False
    accel.totelem = 0
    accel.grid_cols = 0
    accel.grid_rows = 0
    accel.min_x = 0.0
    accel.min_y = 0.0
    accel.max_x = 0.0
    accel.max_y = 0.0
    accel.cell_size_x = 0.0
    accel.cell_size_y = 0.0


# ======================================================================================
# Grid Initialization and Setup
# ======================================================================================

cdef void spatial_accel_init(SpatialAccel* accel, int totelem, float min_x, float min_y, float max_x, float max_y, 
                             int grid_cols, int grid_rows) noexcept nogil:
    """
    Initialize or reinitialize the spatial acceleration grid with robust error checking
    
    Args:
        accel: Pointer to the SpatialAccel structure to initialize
        totelem: Total of elements to be added (for performance and memory management purposes)
        min_x, min_y: Minimum bounds of the grid
        max_x, max_y: Maximum bounds of the grid
        grid_cols, grid_rows: Dimensions of the grid in cells
    """
    # Safety checks
    if accel == NULL:
        return

    # Prevent issues with invalid dimensions
    if grid_cols <= 0 or grid_rows <= 0 or max_x <= min_x or max_y <= min_y:
        return

    # Check if we only need to reset (same dimensions) or fully reinitialize
    '''if accel.is_initialized and accel.grid_cols == grid_cols and accel.grid_rows == grid_rows and accel.totelem == totelem:
        # Update bounds and reset cells
        accel.min_x = min_x
        accel.min_y = min_y
        accel.max_x = max_x
        accel.max_y = max_y
        accel.cell_size_x = (max_x - min_x) / grid_cols
        accel.cell_size_y = (max_y - min_y) / grid_rows
        
        # Clear all cells without reallocating
        spatial_accel_reset(accel)
        return'''

    # Dimensions have changed or not initialized yet - do full cleanup and init
    spatial_accel_cleanup(accel)

    # Set new grid parameters
    accel.min_x = min_x
    accel.min_y = min_y
    accel.max_x = max_x
    accel.max_y = max_y
    accel.grid_cols = grid_cols
    accel.grid_rows = grid_rows
    accel.cell_size_x = (max_x - min_x) / grid_cols
    accel.cell_size_y = (max_y - min_y) / grid_rows
    
    # Allocate all cells in a single contiguous block
    cdef Cell* all_cells = <Cell*>malloc(grid_cols * grid_rows * sizeof(Cell))
    if all_cells == NULL:
        # Failed to allocate memory
        accel.is_initialized = False
        return

    # Allocate row pointers
    accel.grid = <Cell**>malloc(grid_cols * sizeof(Cell*))
    if accel.grid == NULL:
        # Failed to allocate memory for row pointers
        free(all_cells)
        accel.is_initialized = False
        return
    
    # Set up row pointers to point to appropriate places in the contiguous block
    cdef int i
    for i in range(grid_cols):
        accel.grid[i] = &all_cells[i * grid_rows]
    
    # Store the contiguous block pointer for later cleanup
    accel.cells_memory = all_cells  # You'll need to add this field to your struct

    # Allocate memory for elements.
    accel.totelem = totelem
    accel.elements = <GeomElement*>malloc(totelem * sizeof(GeomElement))

    accel.is_initialized = True


# ======================================================================================
# Utility Functions
# ======================================================================================

cdef void spatial_accel_get_cell_indices(SpatialAccel* accel, float x, float y, int* cell_x, int* cell_y) noexcept nogil:
    """Convert world coordinates to cell indices with proper bounds checking."""
    # Default to invalid values.
    cell_x[0] = -1
    cell_y[0] = -1
    
    # Check for NULL pointers and valid initialization
    if accel == NULL or not accel.is_initialized or cell_x == NULL or cell_y == NULL:
        return
    
    # Check for valid grid dimensions
    if accel.grid_cols <= 0 or accel.grid_rows <= 0:
        return
        
    # Check for valid cell sizes to avoid division by zero
    cdef float cell_width = accel.cell_size_x
    cdef float cell_height = accel.cell_size_y
    if cell_width <= 0.0 or cell_height <= 0.0:
        return
    
    # Calculate indices with bounds checking for input coordinates
    cdef float bounded_x = c_fmax(accel.min_x, c_fmin(accel.max_x, x))
    cdef float bounded_y = c_fmax(accel.min_y, c_fmin(accel.max_y, y))
    
    # Calculate cell indices
    cdef int i = <int>((bounded_x - accel.min_x) / cell_width)
    cdef int j = <int>((bounded_y - accel.min_y) / cell_height)
    
    # Clamp to grid bounds in case of numerical issues
    i = c_max(0, c_min(accel.grid_cols - 1, i))
    j = c_max(0, c_min(accel.grid_rows - 1, j))
    
    cell_x[0] = i
    cell_y[0] = j

cdef float spatial_accel_element_distance(SpatialAccel* accel, GeomElement* elem, float x, float y, float depth) noexcept nogil:
    """
    Calculate the 3D distance between a point and an element with robust error handling.
    
    Args:
        accel: The spatial acceleration structure
        elem: The geometry element to measure distance to
        x, y: 2D screen coordinates to measure from
        depth: Depth of the point to measure from
        
    Returns:
        The 3D distance, or FLOAT_INFINITY if measurement isn't possible
    """
    if accel == NULL or elem == NULL:
        return FLOAT_INFINITY
    
    # Check for valid coordinates
    if (not isfinite(x) or not isfinite(y) or not isfinite(depth) or 
        not isfinite(elem.x) or not isfinite(elem.y) or not isfinite(elem.depth)):
        return FLOAT_INFINITY
        
    # Calculate 3D distance
    cdef float dx = elem.x - x
    cdef float dy = elem.y - y
    cdef float dz = elem.depth - depth
    return sqrt(dx*dx + dy*dy + dz*dz)

# ======================================================================================
# Element Management
# ======================================================================================

cdef void spatial_accel_add_element(SpatialAccel* accel, int insert_index, void* elem, int index, float x, float y, float depth, GeomType geom_type) noexcept nogil:
    """
    Add a geometry element to the appropriate cell in the grid
    
    Args:
        accel: Pointer to spatial acceleration structure
        insert_index: 
        elem: Pointer to the geometry element (BMVert*, BMEdge*, or BMFace*)
        elem_index: index of the element it
        x, y: Screen coordinates
        geom_type: Type of geometry (VERT, EDGE, FACE)
        depth: Depth value for sorting (Z-ordering)
    """
    # Skip if coordinates are out of bounds
    if x < accel.min_x or x > accel.max_x or y < accel.min_y or y > accel.max_y:
        return

    # Skip if element pointer is NULL
    if elem == NULL:
        return

    # Use a pointer to the element in the array
    cdef GeomElement* element = &accel.elements[insert_index]

    # Fill element data
    element.elem = elem
    element.index = index
    element.x = x
    element.y = y
    element.depth = depth
    element.geom_type = geom_type

    # Get Cell XY.
    spatial_accel_get_cell_indices(accel, x, y, &element.cell_x, &element.cell_y)

    # Add index of the element in the target Cell.
    element.cell_index = accel.grid[element.cell_x][element.cell_y].totelem

    # Increase element count in target Cell.
    accel.grid[element.cell_x][element.cell_y].totelem += 1


cdef void spatial_accel_update_grid_indices(SpatialAccel* accel) noexcept nogil:
    cdef:
        int cell_idx
        int elem_idx
        Cell* cell
        GeomElement* elem
        int cx, cy

    # Init Cell elements indices based on total amount of elements added to it.
    for cell_idx in prange(accel.grid_cols * accel.grid_rows):
        cell = &accel.cells_memory[cell_idx]
        if cell.totelem > 0:  # Only allocate if needed
            cell.elem_indices = <int*>malloc(cell.totelem * sizeof(int))
        else:
            cell.elem_indices = NULL

    # Add element indices to Cells.
    for elem_idx in range(accel.totelem):  # Remove prange to avoid race conditions
        elem = &accel.elements[elem_idx]

        # Validate cell coordinates
        cx = elem.cell_x
        cy = elem.cell_y
        if cx < 0 or cx >= accel.grid_cols or cy < 0 or cy >= accel.grid_rows:
            continue  # Skip invalid cell coordinates

        cell = &accel.grid[cx][cy]
        if cell == NULL:
            continue  # Skip NULL cells

        if elem.cell_index >= cell.totelem:
            continue  # Skip if index is out of bounds

        if cell.elem_indices == NULL:
            continue  # Skip if indices array wasn't allocated

        cell.elem_indices[elem.cell_index] = elem_idx


# ======================================================================================
# Unified Search Function
# ======================================================================================
'''
cdef cpp_list[ElementWithDistance] spatial_accel_get_nearest_elements(
    SpatialAccel* accel,
    float x, float y, float depth,
    int k,
    float max_dist,
    GeomType geom_type
) noexcept nogil:
    """
    Unified function to find nearest elements. Can find:
    - Single nearest element (k=1)
    - K nearest elements (k>1)
    - All elements in an area (k=0, max_dist>0)
    - K nearest elements in an area (k>0, max_dist>0)
    """
    cdef cpp_list[ElementWithDistance] result
    
    # Input validation
    if accel == NULL or not accel.is_initialized:
        return result
    
    # Handle special cases
    if k < 0:
        return result
        
    # Use infinite distance if not specified
    if max_dist <= 0:
        max_dist = FLOAT_INFINITY
    
    cdef:
        int cell_x, cell_y
        int radius = 1  # Start with a 1-cell radius search
        int max_radius = c_max(accel.grid_width, accel.grid_height)
        int i, j, ni, nj
        vector[ElementWithDistance] candidates
        ElementWithDistance element_with_dist
        float dist
        Cell* cell
        size_t ei, vector_size
        int min_i, max_i, min_j, max_j
        bint found_elements = False
        GeomElement* elem_ptr
        GeomElement elem
    
    # Get the starting cell
    spatial_accel_get_cell_indices(accel, x, y, &cell_x, &cell_y)
    
    # Progressively expand search radius until we find enough elements or reach grid bounds
    while radius <= max_radius:
        # Calculate the bounds for this search radius
        min_i = c_max(0, cell_x - radius)
        max_i = c_min(accel.grid_width - 1, cell_x + radius)
        min_j = c_max(0, cell_y - radius)
        max_j = c_min(accel.grid_height - 1, cell_y + radius)
        
        # Search cells in this radius
        for i in range(min_i, max_i + 1):
            for j in range(min_j, max_j + 1):
                # Skip if we've already searched this cell in a previous radius
                if (radius > 1 and i > min_i and i < max_i and j > min_j and j < max_j):
                    continue
                
                # Get cell and check elements
                cell = &accel.grid[i][j]
                
                # Iterate through the list - note this is different from vector iteration
                # For C++ list, we need to use iterators
                # Since we can't easily iterate through a list in Cython with nogil,
                # we'll adapt this code to work with the element list
                
                # For each element in the cell's list
                # Note: C++ list doesn't support random access, we access by iterating
                for elem in cell.elements:
                    # Match geometry type (or ANY type)
                    if geom_type == GeomType.ANY or elem.geom_type == geom_type:
                        # Calculate distance
                        dist = spatial_accel_element_distance(accel, &elem, x, y, depth)
                        
                        # Only consider elements within max_dist
                        if dist <= max_dist:
                            found_elements = True
                            element_with_dist.element = &elem  # This will be a reference to a copy
                            element_with_dist.distance = dist
                            candidates.push_back(element_with_dist)
        
        # If we found elements and k > 0, check if we have enough
        if found_elements and k > 0 and candidates.size() >= <size_t>k:
            break
            
        # Expand search radius
        radius += 1
    
    # If we found candidates, sort them by distance
    if candidates.size() > 0:
        sort(candidates.begin(), candidates.end(), compare_by_distance)
    
    # Take the k nearest elements (or all if k=0)
    cdef size_t num_results = candidates.size()
    if k > 0:
        num_results = c_min(<size_t>k, candidates.size())
    
    # Copy the elements to the result vector
    for i in range(<int>num_results):
        if i < <int>candidates.size():  # Safety check
            result.push_back(candidates[i])
    
    return result
'''
