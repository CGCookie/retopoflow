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


from libc.stdlib cimport malloc, free
from libc.math cimport sqrt, floor, fabs
from libcpp.vector cimport vector
from libcpp.algorithm cimport sort
from libcpp cimport bool

# Define comparison function for sorting GeomElements by distance
cdef struct ElementWithDistance:
    GeomElement element
    float distance

cdef bool compare_by_distance(const ElementWithDistance& a, const ElementWithDistance& b) nogil:
    return a.distance < b.distance

# Spatial acceleration structure
cdef class SpatialAccel:

    def __cinit__(self):
        """Minimal initialization when object is created"""
        self.grid = NULL
        self.is_initialized = False
    
    def __dealloc__(self):
        """Free all allocated memory"""
        self.cleanup()
    
    cdef void reset(self) noexcept nogil:
        """Clear all cells in the grid"""
        cdef int i, j
        for i in range(self.grid_width):
            for j in range(self.grid_height):
                if self.grid[i][j].elements != NULL:
                    free(self.grid[i][j].elements)
                self.grid[i][j].elements = NULL
                self.grid[i][j].count = 0
                self.grid[i][j].capacity = 0
    
    cdef void cleanup(self) noexcept nogil:
        """Clean up any allocated resources"""
        if not self.is_initialized:
            return
            
        cdef int i, j
        for i in range(self.grid_width):
            for j in range(self.grid_height):
                if self.grid[i][j].elements != NULL:
                    free(self.grid[i][j].elements)
            if self.grid[i] != NULL:
                free(self.grid[i])
        if self.grid != NULL:
            free(self.grid)
            self.grid = NULL
        
        self.is_initialized = False
    
    cdef void init(self, float min_x, float min_y, float max_x, float max_y, 
              int grid_width, int grid_height) noexcept nogil:
        """Initialize or re-initialize the spatial acceleration structure"""
        # Clean up any existing resources first
        self.cleanup()
        
        # Set new parameters
        self.min_x = min_x
        self.min_y = min_y
        self.max_x = max_x
        self.max_y = max_y
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.cell_size_x = (max_x - min_x) / grid_width
        self.cell_size_y = (max_y - min_y) / grid_height
        
        # Allocate grid
        self.grid = <Cell**>malloc(grid_width * sizeof(Cell*))
        cdef int i, j
        for i in range(grid_width):
            self.grid[i] = <Cell*>malloc(grid_height * sizeof(Cell))
            for j in range(grid_height):
                self.grid[i][j].elements = NULL
                self.grid[i][j].count = 0
                self.grid[i][j].capacity = 0
                
        self.is_initialized = True
        ## self.reset()

    cdef void get_cell_indices(self, float x, float y, int* cell_x, int* cell_y) noexcept nogil:
        """Get cell indices from coordinates"""
        cdef int i = <int>((x - self.min_x) / self.cell_size_x)
        cdef int j = <int>((y - self.min_y) / self.cell_size_y)
        
        # Clamp to grid bounds
        if i < 0: i = 0
        if i >= self.grid_width: i = self.grid_width - 1
        if j < 0: j = 0
        if j >= self.grid_height: j = self.grid_height - 1
        
        cell_x[0] = i
        cell_y[0] = j

    cdef void add_element(self, void* elem, float x, float y, float depth, GeomType geom_type) noexcept nogil:
        """Add a geometry element to the appropriate cell"""
        cdef:
            int k
            int cell_x, cell_y
            int new_capacity
            Cell* cell
            GeomElement* new_elements

        self.get_cell_indices(x, y, &cell_x, &cell_y)
        
        cell = &self.grid[cell_x][cell_y]
        
        # Resize if needed
        if cell.count >= cell.capacity:
            new_capacity = max(10, cell.capacity * 2)
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
        cell.elements[cell.count].x = x
        cell.elements[cell.count].y = y
        cell.elements[cell.count].depth = depth
        cell.elements[cell.count].geom_type = geom_type
        cell.count += 1
    
    cdef GeomElement* find_elem(self, float x, float y, float depth, GeomType geom_type) noexcept nogil:
        """Find an element with matching coordinates, depth and type, returns NULL if not found"""
        cdef int cell_x, cell_y
        self.get_cell_indices(x, y, &cell_x, &cell_y)
        cdef Cell* cell = &self.grid[cell_x][cell_y]
        cdef int k
        cdef float epsilon = 1e-6  # Small threshold for float comparison

        for k in range(cell.count):
            if (fabs(cell.elements[k].x - x) < epsilon and
                fabs(cell.elements[k].y - y) < epsilon and
                fabs(cell.elements[k].depth - depth) < epsilon and
                cell.elements[k].geom_type == geom_type):
                
                return &cell.elements[k]
        
        return NULL
    
    '''cpdef object py_find_elem(self, float x, float y, float depth, GeomType geom_type):
        """Python-accessible wrapper for find_elem"""
        cdef GeomElement* result = self.find_elem(x, y, depth, geom_type)
        if result == NULL:
            return None
            
        return {
            # 'elem': <object>result.elem,
            'x': result.x,
            'y': result.y,
            'depth': result.depth,
            'geom_type': result.geom_type
        }'''
    
    cdef float element_distance(self, GeomElement* elem, float x, float y, float depth) noexcept nogil:
        """Calculate distance between a point and an element"""
        cdef float dx = elem.x - x
        cdef float dy = elem.y - y
        cdef float dd = elem.depth - depth
        return sqrt(dx*dx + dy*dy + dd*dd)
    
    cdef vector[GeomElement] find_k_elem(self, float x, float y, float depth, GeomType geom_type, int k=1) noexcept nogil:
        """Find k closest elements matching the criteria"""
        cdef:
            int ni, nj, ei
            int cell_x, cell_y
            vector[ElementWithDistance] candidates
            vector[GeomElement] result
            float dist
            ElementWithDistance element_with_dist
            
        self.get_cell_indices(x, y, &cell_x, &cell_y)
        
        # Search in current cell and neighboring cells
        for ni in range(max(0, cell_x-1), min(self.grid_width, cell_x+2)):
            for nj in range(max(0, cell_y-1), min(self.grid_height, cell_y+2)):
                cell = &self.grid[ni][nj]
                
                for ei in range(cell.count):
                    if cell.elements[ei].geom_type == geom_type:
                        dist = self.element_distance(&cell.elements[ei], x, y, depth)
                        element_with_dist.element = cell.elements[ei]
                        element_with_dist.distance = dist
                        candidates.push_back(element_with_dist)
        
        # Sort by distance
        sort(candidates.begin(), candidates.end(), compare_by_distance)
        
        # Get the k closest elements
        cdef int count = min(k, <int>candidates.size())
        for i in range(count):
            result.push_back(candidates[i].element)
            
        return result

    '''cpdef list py_find_k_elem(self, float x, float y, float depth, GeomType geom_type, int k=1):
        """Python-accessible wrapper for find_k_elem"""
        cdef vector[GeomElement] results = self.find_k_elem(x, y, depth, geom_type, k)
        
        # Convert to Python list of dictionaries
        py_results = []
        for i in range(results.size()):
            py_results.append({
                # 'elem': <object>results[i].elem,
                'x': results[i].x,
                'y': results[i].y,
                'depth': results[i].depth,
                'geom_type': results[i].geom_type
            })
        
        return py_results'''
    
    cdef vector[GeomElement] find_elem_in_area(self, float x, float y, float depth, GeomType geom_type, float radius) noexcept nogil:
        """Find elements within radius of the given point"""
        cdef:
            vector[GeomElement] result
            float search_x_min = x - radius
            float search_x_max = x + radius
            float search_y_min = y - radius
            float search_y_max = y + radius
            int min_i, min_j, max_i, max_j
            int i, j, k
            float dist
            
        self.get_cell_indices(search_x_min, search_y_min, &min_i, &min_j)
        self.get_cell_indices(search_x_max, search_y_max, &max_i, &max_j)
        
        # Search cells
        for i in range(max(0, min_i), min(self.grid_width, max_i + 1)):
            for j in range(max(0, min_j), min(self.grid_height, max_j + 1)):
                cell = &self.grid[i][j]
                
                for k in range(cell.count):
                    if cell.elements[k].geom_type == geom_type:
                        # Calculate 3D distance
                        dist = self.element_distance(&cell.elements[k], x, y, depth)
                        
                        if dist <= radius:
                            result.push_back(cell.elements[k])
        
        return result
    
    '''cpdef list py_find_elem_in_area(self, float x, float y, float depth, GeomType geom_type, float radius):
        """Python-accessible wrapper for find_elem_in_area"""
        cdef vector[GeomElement] results = self.find_elem_in_area(x, y, depth, geom_type, radius)
        
        # Convert to Python list of dictionaries
        py_results = []
        for i in range(results.size()):
            py_results.append({
                # 'elem': <object>results[i].elem,
                'x': results[i].x,
                'y': results[i].y,
                'depth': results[i].depth,
                'geom_type': results[i].geom_type
            })
        
        return py_results'''
    
    cdef vector[GeomElement] find_k_elem_in_area(self, float x, float y, float depth, GeomType geom_type, float radius, int k=1) noexcept nogil:
        """Find k closest elements within radius"""
        cdef:
            vector[GeomElement] result
            vector[ElementWithDistance] candidates
            ElementWithDistance element_with_dist
            
        # Get all matching elements in the area (as internal raw data)
        cdef vector[GeomElement] elements = self.find_elem_in_area(x, y, depth, geom_type, radius)
        
        # Convert to ElementWithDistance for sorting
        for i in range(elements.size()):
            element_with_dist.element = elements[i]
            element_with_dist.distance = self.element_distance(&elements[i], x, y, depth)
            candidates.push_back(element_with_dist)
        
        # Sort by distance
        sort(candidates.begin(), candidates.end(), compare_by_distance)
        
        # Get the k closest elements
        cdef int count = min(k, <int>candidates.size())
        for i in range(count):
            result.push_back(candidates[i].element)
            
        return result
    
    '''cpdef list py_find_k_elem_in_area(self, float x, float y, float depth, GeomType geom_type, 
                                     float radius, int k=1):
        """Python-accessible wrapper for find_k_elem_in_area"""
        cdef vector[GeomElement] results = self.find_k_elem_in_area(x, y, depth, geom_type, radius, k)
        
        # Convert to Python list of dictionaries
        py_results = []
        for i in range(results.size()):
            py_results.append({
                # 'elem': <object>results[i].elem,
                'x': results[i].x,
                'y': results[i].y,
                'depth': results[i].depth,
                'geom_type': results[i].geom_type
            })
        
        return py_results'''
