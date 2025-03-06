# distutils: language=c++
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
from cython.operator cimport dereference as deref, preincrement as inc
from libcpp.vector cimport vector
from libcpp.set cimport set as cpp_set
from libcpp.pair cimport pair
from libcpp.iterator cimport iterator


# from .matrix cimport mat4_invert_safe, mat4_invert, mat4_to_3x3, mat4_transpose, mat4_multiply, mat4_get_col3, mat4_get_translation
# from .view3d_utils cimport location_3d_to_region_2d

import cython

from .bl_types.bmesh_types cimport BMVert, BMEdge, BMFace, BMesh, BMHeader, BMLoop
from .bl_types.bmesh_py_wrappers cimport BPy_BMesh, BPy_BMVert, BPy_BMEdge, BPy_BMFace
from .bl_types.bmesh_flags cimport BMElemHFlag, BM_elem_flag_test
from .bl_types cimport ARegion, RegionView3D
from .utils cimport vec3_normalize, vec3_dot

# ctypedef np.uint8_t uint8

cdef float finf = <float>1e1000


@cython.binding(True)
cdef class TargetMeshAccel:

    def __cinit__(self):
        # Initialize C++ member variables
        self.is_hidden_v = NULL
        self.is_hidden_e = NULL
        self.is_hidden_f = NULL
        self.is_selected_v = NULL
        self.is_selected_e = NULL
        self.is_selected_f = NULL
        
        # Initialize grid
        self.grid = NULL
        self.grid_size_x = 0
        self.grid_size_y = 0
        
        # Initialize dirty flags
        self.is_dirty_geom_vis = True
        self.is_dirty_accel = True

    
    def __init__(self,
        object py_object,
        object py_bmesh,
        object py_region,
        object py_rv3d
    ):
        print(f"[CYTHON] Accel2D.__init__({py_object}, {py_bmesh}, {py_region}, {py_rv3d})")

        self.py_update_object(py_object)
        self.py_update_bmesh(py_bmesh)
        self.py_update_region(py_region)
        self.py_update_view(py_rv3d)

    cpdef void update(self, float margin_check):
        self._ensure_lookup_tables()
        self._ensure_indices()
        if self._compute_geometry_visibility_in_region(margin_check) != 0:
            print("[CYTHON] Error: Failed to compute geometry visibility in region\n")
            self._build_accel_struct()

    def __dealloc__(self):
        self._reset()

    cdef void _update_object_transform(self, const float[:, ::1] matrix_world, const float[:, ::1] matrix_normal) nogil:
        cdef:
            int i, j

        for i in range(4):
            for j in range(4):
                self.matrix_world[i][j] = matrix_world[i,j]
                self.matrix_normal[i][j] = matrix_normal[i,j]
        
        self.set_dirty()

    cdef void _update_view(self, const float[:, ::1] proj_matrix, const float[::1] view_pos, bint is_perspective) nogil:
        cdef:
            int i, j

        # Update view3d parameters
        for i in range(4):
            for j in range(4):
                self.view3d.proj_matrix[i][j] = proj_matrix[i,j]

        for i in range(3):
            self.view3d.view_pos[i] = view_pos[i]

        self.view3d.is_persp = is_perspective

        self.set_dirty()

    cpdef void _ensure_lookup_tables(self):
        """Ensure lookup tables are created for the bmesh"""
        try:
            self.py_bmesh.verts[0]
        except IndexError:
            print(f"[CYTHON] py_bmesh.verts.ensure_lookup_table()\n")
            self.py_bmesh.verts.ensure_lookup_table()
            self.set_dirty()
        try:
            self.py_bmesh.edges[0]
        except IndexError:
            print(f"[CYTHON] py_bmesh.edges.ensure_lookup_table()\n")
            self.py_bmesh.edges.ensure_lookup_table()
            self.set_dirty()
        try:
            self.py_bmesh.faces[0]
        except IndexError:
            print(f"[CYTHON] py_bmesh.faces.ensure_lookup_table()\n")
            self.py_bmesh.faces.ensure_lookup_table()
            self.set_dirty()

    cpdef void _ensure_indices(self):
        if self.bmesh.totvert == 0:
            return

        # We make 3 checks to be sure that the indices are updated and in order.
        cdef int i
        for i in range(max(self.bmesh.totvert, 3)):
            if self.py_bmesh.verts[i].index != i:
                self.py_bmesh.verts.update_indices()
                print(f"[CYTHON] Accel2D._ensure_indices() - verts updated")
                break

        if self.bmesh.totedge == 0:
            return

        for i in range(max(self.bmesh.totedge, 3)):
            if self.py_bmesh.edges[i].index != i:
                self.py_bmesh.edges.update_indices()
                print(f"[CYTHON] Accel2D._ensure_indices() - edges updated")
                break

        if self.bmesh.totface == 0:
            return

        for i in range(max(self.bmesh.totface, 3)):
            if self.py_bmesh.faces[i].index != i:
                self.py_bmesh.faces.update_indices()
                print(f"[CYTHON] Accel2D._ensure_indices() - faces updated")
                break

    cdef int _compute_geometry_visibility_in_region(self, float margin_check) nogil:
        if self.bmesh == NULL or self.bmesh.vtable == NULL or self.bmesh.etable == NULL or self.bmesh.ftable == NULL:
            printf("[CYTHON] Error: Accel2D._compute_geometry_visibility_in_region() - bmesh or vtable is NULL\n")
            with gil:
                print(f"[CYTHON] Error: Accel2D._compute_geometry_visibility_in_region() - bmesh or vtable is NULL\n")
            return -1

        if not self.is_dirty_geom_vis:
            return 0

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
            with gil:
                print(f"[CYTHON] Error: Failed to allocate memory\n")
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
            with gil:
                print(f"[CYTHON] Error: Failed to allocate memory\n")
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
                with gil:
                    print(f"[CYTHON] vert {vert_idx} is NULL")
                continue
            
            self._classify_elem(
                &vert.head, vert_idx,
                self.is_hidden_v,
                self.is_selected_v
            )

            # Skip hidden vertices.
            if self.is_hidden_v[vert_idx]:
                with gil:
                    print(f"[CYTHON] vert {vert_idx} is hidden")
                continue

            # Transform position to world space
            for j in range(3):
                world_pos[j] = 0
                for k in range(3):
                    world_pos[j] += vert.co[k] * self.matrix_world[k][j]
                world_pos[j] += self.matrix_world[3][j]

            # Transform normal to world space
            for j in range(3):
                world_normal[j] = 0
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
                    view_dir[j] = -view3d.view_pos[j]

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

            if screen_pos[3] <= 0:  # Behind camera
                continue
            
            # Perspective divide and bounds check
            if (fabs(screen_pos[0] / screen_pos[3]) <= margin_check and 
                fabs(screen_pos[1] / screen_pos[3]) <= margin_check):

                # TODO: project vert.co to 2D region space.
                # TODO: store vert 2d position in custom array in self (Accel2D).
                # TODO: if vertex could be projected and 2d point in inside the region bounds, then mark vertex as visible (as below).
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

        with gil:
            print(f"[CYTHON] totvisverts: {self.totvisverts}")
            print(f"[CYTHON] totvisedges: {self.totvisedges}")
            print(f"[CYTHON] totvisfaces: {self.totvisfaces}")

        # After computing visibility and populating the C++ sets, build acceleration structure
        # self._build_accel_struct()

        self.is_dirty_geom_vis = False
        self.is_dirty_accel = True
        return 0

    cdef void _classify_elem(self, BMHeader* head, size_t index, uint8_t* is_hidden_array, uint8_t* is_selected_array) noexcept nogil:
        """Classify element based on selection and visibility flags."""
        is_hidden_array[index]= BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_HIDDEN)
        is_selected_array[index] = BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_SELECT)

    cdef void _project_point_to_screen(self, const float[3] world_pos, float[2] screen_pos, float* depth) noexcept nogil:
        """Project 3D point to screen space and compute depth"""
        cdef:
            float[4] pos4d
            float[4] clip_pos
            int i
            
        # Transform to clip space
        for i in range(3):
            pos4d[i] = world_pos[i]
        pos4d[3] = <float>1.0
        
        # Apply projection
        for i in range(4):
            clip_pos[i] = 0
            for j in range(4):
                clip_pos[i] += self.view3d.proj_matrix[i][j] * pos4d[j]
                
        # Perspective divide
        if clip_pos[3] != 0:
            screen_pos[0] = (clip_pos[0] / clip_pos[3] + <float>1.0) * self.region.winx * <float>0.5
            screen_pos[1] = (clip_pos[1] / clip_pos[3] + <float>1.0) * self.region.winy * <float>0.5
            depth[0] = clip_pos[2] / clip_pos[3]
        else:
            screen_pos[0] = screen_pos[1] = <float>(-1.0)
            depth[0] = 0

    cdef void _reset(self, bint dirty=True) noexcept nogil:
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

        self._clear_grid()

        self.totvisverts = 0
        self.totvisedges = 0
        self.totvisfaces = 0

        if dirty:
            self.set_dirty()

    cdef void set_dirty(self) noexcept nogil:
        """Set the dirty flag"""
        self.is_dirty_geom_vis = True
        self.is_dirty_accel = True


    '''
    ______________________________________________________________________________________________________________
    
    Python access methods 
    ______________________________________________________________________________________________________________
    '''

    cpdef tuple[set, set, set] get_visible_geom(self, object py_bmesh, bint verts=True, bint edges=True, bint faces=True, bint invert_selection=False):
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

    cpdef tuple[set, set, set] get_selected_geom(self, object py_bmesh, bint verts=True, bint edges=True, bint faces=True, bint invert_selection=False):
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
            cpp_set[BMVert*].iterator visverts_it = self.visverts.begin()
            set py_vis_verts = set()
            BMVert* cur_visvert = NULL

        if selected_only == SelectionState.ALL:
            while visverts_it != self.visverts.end():
                cur_visvert = deref(visverts_it)
                py_vis_verts.add(py_bm_verts[cur_visvert.head.index])
                inc(visverts_it)
            return py_vis_verts
        elif selected_only == SelectionState.SELECTED:
            return {py_bm_verts[self.bmesh.vtable[i].head.index] for i in range(self.bmesh.totvert) if self.is_selected_v[i]}
        elif selected_only == SelectionState.UNSELECTED:
            return {py_bm_verts[self.bmesh.vtable[i].head.index] for i in range(self.bmesh.totvert) if not self.is_selected_v[i]}
        else:
            return set()


    # ---------------------------------------------------------------------------------------
    # Acceleration structure methods.
    # ---------------------------------------------------------------------------------------

    cdef void _init_grid(self) noexcept nogil:
        """Initialize the grid structure based on region size"""
        cdef:
            int i, j
            
        self.grid_size_x = self.region.winx // 92  # Adjust cell size as needed
        self.grid_size_y = self.region.winy // 92
        self.cell_size_x = self.region.winx / <float>self.grid_size_x
        self.cell_size_y = self.region.winy / <float>self.grid_size_y
        
        # Allocate grid
        self.grid = <GridCell**>malloc(self.grid_size_x * sizeof(GridCell*))
        for i in range(self.grid_size_x):
            self.grid[i] = <GridCell*>malloc(self.grid_size_y * sizeof(GridCell))
            for j in range(self.grid_size_y):
                self.grid[i][j].elements.clear()

    cdef void _clear_grid(self) noexcept nogil:
        """Clear and deallocate grid"""
        cdef int i
        if self.grid != NULL:
            for i in range(self.grid_size_x):
                if self.grid[i] != NULL:
                    free(self.grid[i])
            free(self.grid)
            self.grid = NULL

    cdef void _get_cell_coords(self, float x, float y, int* cell_x, int* cell_y) noexcept nogil:
        """Get grid cell coordinates for a point"""
        cell_x[0] = <int>(x / self.cell_size_x)
        cell_y[0] = <int>(y / self.cell_size_y)
        
        # Clamp to grid bounds
        if cell_x[0] < 0: cell_x[0] = 0
        if cell_y[0] < 0: cell_y[0] = 0
        if cell_x[0] >= self.grid_size_x: cell_x[0] = self.grid_size_x - 1
        if cell_y[0] >= self.grid_size_y: cell_y[0] = self.grid_size_y - 1

    cdef void _add_element_to_grid(self, GeomElement* elem) noexcept nogil:
        """Add an element to the appropriate grid cell"""
        self._get_cell_coords(elem.pos[0], elem.pos[1], &elem.cell_x, &elem.cell_y)
        self.grid[elem.cell_x][elem.cell_y].elements.push_back(elem[0])

    cdef void _find_cells_in_range(self, float x, float y, float radius, 
                                  vector[GridCell*]* cells) noexcept nogil:
        """Find all grid cells that intersect with the given circle"""
        cdef:
            int min_cell_x, min_cell_y
            int max_cell_x, max_cell_y
            int cell_x, cell_y
            # float radius_cells_x = radius / self.cell_size_x
            # float radius_cells_y = radius / self.cell_size_y

        # Get cell range that could contain points within radius
        self._get_cell_coords(x - radius, y - radius, &min_cell_x, &min_cell_y)
        self._get_cell_coords(x + radius, y + radius, &max_cell_x, &max_cell_y)
        
        # Add all cells in range
        for cell_x in range(min_cell_x, max_cell_x + 1):
            for cell_y in range(min_cell_y, max_cell_y + 1):
                if self.grid != NULL and self.grid[cell_x] != NULL:
                    cells.push_back(&self.grid[cell_x][cell_y])

    cdef float _compute_distance_2d(self, float x1, float y1, float x2, float y2) noexcept nogil:
        """Compute 2D Euclidean distance"""
        cdef:
            float dx = x2 - x1
            float dy = y2 - y1
        return sqrt(dx * dx + dy * dy)

    cdef GeomElement* _find_nearest(self, float x, float y, float max_dist, 
                                  GeomType filter_type) noexcept nogil:
        """Find nearest element of given type within max_dist"""
        cdef:
            vector[GridCell*] cells
            size_t i, j
            float dist, min_dist = max_dist
            GeomElement* nearest = NULL
            GeomElement* elem
            
        # Get cells that could contain points within max_dist
        self._find_cells_in_range(x, y, max_dist, &cells)
        
        # Search through all elements in found cells
        for i in range(cells.size()):
            for j in range(cells[i].elements.size()):
                elem = &cells[i].elements[j]
                if filter_type != NONE and elem.type != filter_type:
                    continue
                    
                dist = self._compute_distance_2d(x, y, elem.pos[0], elem.pos[1])
                if dist < min_dist:
                    min_dist = dist
                    nearest = elem
                    
        return nearest

    cdef void _find_nearest_k(self, float x, float y, int k, float max_dist,
                             GeomType filter_type, vector[GeomElement]* results) noexcept nogil:
        """Find k nearest elements of given type within max_dist"""
        cdef:
            vector[GridCell*] cells
            size_t i, j, l
            float dist
            GeomElement elem
            vector[pair[float, GeomElement]] candidates
            
        # Get cells that could contain points within max_dist
        self._find_cells_in_range(x, y, max_dist, &cells)
        
        # Collect all elements and their distances
        for i in range(cells.size()):
            for j in range(cells[i].elements.size()):
                elem = cells[i].elements[j]
                if filter_type != NONE and elem.type != filter_type:
                    continue
                    
                dist = self._compute_distance_2d(x, y, elem.pos[0], elem.pos[1])
                if dist <= max_dist:
                    candidates.push_back(pair[float, GeomElement](dist, elem))
                    
        # Sort candidates by distance
        # Note: This is a simple bubble sort, could be optimized
        cdef:
            size_t n = candidates.size()
            pair[float, GeomElement] temp
            
        for i in range(n):
            for j in range(0, n - i - 1):
                if candidates[j].first > candidates[j + 1].first:
                    temp = candidates[j]
                    candidates[j] = candidates[j + 1]
                    candidates[j + 1] = temp
                    
        # Take k nearest
        for i in range(min(k, candidates.size())):
            results.push_back(candidates[i].second)
    
    cdef void add_vert_to_grid(self, BMVert* vert) noexcept nogil:
        """Add vertex to grid"""
        cdef:
            float[3] world_pos
            float[2] screen_pos
            float depth
            GeomElement* elem
            int i

        # Transform vertex position to world space
        for i in range(3):
            world_pos[i] = vert.co[i]
            for j in range(3):
                world_pos[i] += self.matrix_world[i][j] * vert.co[j]
            world_pos[i] += self.matrix_world[i][3]

        # Project to screen space
        self._project_point_to_screen(world_pos, screen_pos, &depth)

        # Create and add element
        elem = <GeomElement*>malloc(sizeof(GeomElement))
        elem.elem = vert
        elem.pos[0] = screen_pos[0]
        elem.pos[1] = screen_pos[1]
        elem.depth = depth
        elem.type = GeomType.VERT

        self._add_element_to_grid(elem)

    cdef void add_edge_to_grid(self, BMEdge* edge, int num_samples) noexcept nogil:
        """Add edge samples to grid"""
        cdef:
            float[3] v1_world, v2_world, sample_pos
            float[2] screen_pos
            float depth, t
            GeomElement* elem
            int i, j
            BMVert* v1 = <BMVert*>edge.v1
            BMVert* v2 = <BMVert*>edge.v2

        # Transform vertices to world space
        for i in range(3):
            v1_world[i] = v1.co[i]
            v2_world[i] = v2.co[i]
            for j in range(3):
                v1_world[i] += self.matrix_world[i][j] * v1.co[j]
                v2_world[i] += self.matrix_world[i][j] * v2.co[j]
            v1_world[i] += self.matrix_world[i][3]
            v2_world[i] += self.matrix_world[i][3]

        # Add samples along edge
        for i in range(num_samples):
            t = (<float>i + <float>1.0) / (<float>num_samples + <float>1.0)  # Exclude endpoints
            
            # Interpolate position
            for j in range(3):
                sample_pos[j] = v1_world[j] * (<float>1.0-t) + v2_world[j] * t
            
            # Project to screen space
            self._project_point_to_screen(sample_pos, screen_pos, &depth)
            
            # Create and add element
            elem = <GeomElement*>malloc(sizeof(GeomElement))
            elem.elem = edge
            elem.pos[0] = screen_pos[0]
            elem.pos[1] = screen_pos[1]
            elem.depth = depth
            elem.type = GeomType.EDGE

            self._add_element_to_grid(elem)

    cdef void add_face_to_grid(self, BMFace* face) noexcept nogil:
        """Add face centroid to grid"""
        cdef:
            float[3] centroid
            float[2] screen_pos
            float depth
            GeomElement* elem
            int i, j, num_verts = 0
            BMLoop* l_iter = <BMLoop*>face.l_first
            BMVert* vert

        # Compute face centroid in world space
        for i in range(3):
            centroid[i] = 0
            
        while l_iter:
            vert = <BMVert*>l_iter.v
            for i in range(3):
                centroid[i] += vert.co[i]
            num_verts += 1
            l_iter = <BMLoop*>l_iter.next
            if l_iter == <BMLoop*>face.l_first:
                break

        if num_verts > 0:
            # Average centroid and transform to world space
            for i in range(3):
                centroid[i] /= num_verts
                for j in range(3):
                    centroid[i] += self.matrix_world[i][j] * centroid[j]
                centroid[i] += self.matrix_world[i][3]
                
            # Project to screen space
            self._project_point_to_screen(centroid, screen_pos, &depth)
            
            # Create and add element
            elem = <GeomElement*>malloc(sizeof(GeomElement))
            elem.elem = face
            elem.pos[0] = screen_pos[0]
            elem.pos[1] = screen_pos[1]
            elem.depth = depth
            elem.type = GeomType.FACE
            
            self._add_element_to_grid(elem)

    cdef void _build_accel_struct(self) noexcept nogil:
        """Build acceleration structure for efficient spatial queries"""

        if self.is_dirty_geom_vis:
            return
        if not self.is_dirty_accel:
            return

        cdef:
            cpp_set[BMVert*].iterator vert_it
            cpp_set[BMEdge*].iterator edge_it
            cpp_set[BMFace*].iterator face_it
            BMVert* vert
            BMEdge* edge
            BMFace* face
            int i, j
        
        # Clear existing grid
        self._clear_grid()

        # Initialize grid
        self._init_grid()

        # Add visible vertices
        if self.totvisverts > 0:
            vert_it = self.visverts.begin()
            while vert_it != self.visverts.end():
                vert = deref(vert_it)
                self.add_vert_to_grid(vert)
                inc(vert_it)

        # Add visible edges with samples
        if self.totvisedges > 0:
            edge_it = self.visedges.begin()
            while edge_it != self.visedges.end():
                edge = deref(edge_it)
                self.add_edge_to_grid(edge, 3)  # 3 samples along each edge
                inc(edge_it)

        # Add visible faces
        if self.totvisfaces > 0:
            face_it = self.visfaces.begin()
            while face_it != self.visfaces.end():
                face = deref(face_it)
                self.add_face_to_grid(face)  # Add face centroid
                inc(face_it)

        self.is_dirty_accel = False


    # ---------------------------------------------------------------------------------------
    # Python exposed methods.
    # ---------------------------------------------------------------------------------------

    cpdef void py_set_dirty_accel(self):
        self.is_dirty_accel = True

    cpdef void py_set_dirty_geom_vis(self):
        self.is_dirty_geom_vis = True
        self.is_dirty_accel = True

    cpdef void py_update_bmesh(self, object py_bmesh):
        if hasattr(self, 'py_bmesh') and id(self.py_bmesh) == id(py_bmesh):
            return

        self.py_bmesh = py_bmesh
        self.bmesh_pywrapper = <BPy_BMesh*><uintptr_t>id(py_bmesh)
        self.bmesh = self.bmesh_pywrapper.bm

        self._ensure_lookup_tables()
        self._ensure_indices()

    cpdef void py_update_object(self, object py_object):
        self.py_object = py_object

        matrix_world = np.array(py_object.matrix_world, dtype=np.float32)
        matrix_normal = np.array(py_object.matrix_world.inverted_safe().transposed().to_3x3(), dtype=np.float32)
        self._update_object_transform(matrix_world, matrix_normal)

    cpdef void py_update_region(self, object py_region):
        if hasattr(self, 'py_region') and id(self.py_region) == id(py_region):
            return

        self.py_region = py_region
        self.region = <ARegion*><uintptr_t>id(py_region)

    cpdef void py_update_view(self, object py_rv3d):
        cdef:
            bint is_perspective

        self.py_rv3d = py_rv3d
        self.rv3d = <RegionView3D*><uintptr_t>id(py_rv3d)

        view_matrix = py_rv3d.view_matrix
        proj_matrix = np.array(py_rv3d.window_matrix @ view_matrix, dtype=np.float32)
        is_perspective = py_rv3d.is_perspective

        if is_perspective:
            view_pos = np.array(view_matrix.inverted().translation, dtype=np.float32)
        else:
            view_pos = np.array(view_matrix.inverted().col[2].xyz, dtype=np.float32)

        self._update_view(proj_matrix, view_pos, <bint>is_perspective)

    cpdef bint py_update_geometry_visibility(self):
        if not self.is_dirty_geom_vis:
            return True
        return self._compute_geometry_visibility_in_region(<float>1.0) == 0

    cpdef void py_update_accel_struct(self):
        if self.is_dirty_geom_vis:
            if not self.py_update_geometry_visibility():
                return
        if not self.is_dirty_accel:
            return
        self._build_accel_struct()

    cpdef dict find_nearest_vert(self, float x, float y, float max_dist=finf):
        """Find nearest visible vertex to screen position"""
        cdef GeomElement* result = self._find_nearest(x, y, max_dist, GeomType.VERT)
        if result != NULL:
            return {
                'elem': <object>result.elem,
                'pos': (result.pos[0], result.pos[1]),
                'depth': result.depth
            }
        return None

    cpdef dict find_nearest_edge(self, float x, float y, float max_dist=finf):
        """Find nearest visible edge to screen position"""
        cdef GeomElement* result = self._find_nearest(x, y, max_dist, GeomType.EDGE)
        if result != NULL:
            return {
                'elem': <object>result.elem,
                'pos': (result.pos[0], result.pos[1]),
                'depth': result.depth
            }
        return None

    cpdef dict find_nearest_face(self, float x, float y, float max_dist=finf):
        """Find nearest visible face to screen position"""
        cdef GeomElement* result = self._find_nearest(x, y, max_dist, GeomType.FACE)
        if result != NULL:
            return {
                'elem': <object>result.elem,
                'pos': (result.pos[0], result.pos[1]),
                'depth': result.depth
            }
        return None

    cpdef list find_k_nearest_verts(self, float x, float y, int k, float max_dist=finf):
        """Find k nearest vertices to screen position"""
        cdef:
            vector[GeomElement] results
            list py_results = []
            size_t i
            
        self._find_nearest_k(x, y, k, max_dist, GeomType.VERT, &results)
        
        for i in range(results.size()):
            py_results.append({
                'elem': <object>results[i].elem,
                'pos': (results[i].pos[0], results[i].pos[1]),
                'depth': results[i].depth
            })
            
        return py_results

    cpdef list find_k_nearest_edges(self, float x, float y, int k, float max_dist=finf):
        """Find k nearest edges to screen position"""
        cdef:
            vector[GeomElement] results
            list py_results = []
            size_t i
            
        self._find_nearest_k(x, y, k, max_dist, GeomType.EDGE, &results)
        
        for i in range(results.size()):
            py_results.append({
                'elem': <object>results[i].elem,
                'pos': (results[i].pos[0], results[i].pos[1]),
                'depth': results[i].depth
            })
            
        return py_results

    cpdef list find_k_nearest_faces(self, float x, float y, int k, float max_dist=finf):
        """Find k nearest faces to screen position"""
        cdef:
            vector[GeomElement] results
            list py_results = []
            size_t i
            
        self._find_nearest_k(x, y, k, max_dist, GeomType.FACE, &results)
        
        for i in range(results.size()):
            py_results.append({
                'elem': <object>results[i].elem,
                'pos': (results[i].pos[0], results[i].pos[1]),
                'depth': results[i].depth
            })
            
        return py_results


    # ---------------------------------------------------------------------------------------
    # Getters for visible/selected arrays.
    # ---------------------------------------------------------------------------------------

    def get_visible_arrays(self):
        """Get visible arrays as NumPy arrays (zero-copy)"""
        cdef:
            BMesh* bmesh = self.bmesh
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
            BMesh* bmesh = self.bmesh
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
        cdef size_t size = self.bmesh.totvert
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_hidden_v)

    cdef np.ndarray get_is_visible_edges_array(self):
        """Get visible array of edges as NumPy array (zero-copy)"""
        cdef size_t size = self.bmesh.totedge
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_hidden_e)

    cdef np.ndarray get_is_visible_faces_array(self):
        """Get visible array of faces as NumPy array (zero-copy)"""
        cdef size_t size = self.bmesh.totface
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_hidden_f)

    cdef np.ndarray get_is_selected_verts_array(self):
        """Get selected array of vertices as NumPy array (zero-copy)"""
        cdef size_t size = self.bmesh.totvert
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_selected_v)

    cdef np.ndarray get_is_selected_edges_array(self):
        """Get selected array of edges as NumPy array (zero-copy)"""
        cdef size_t size = self.bmesh.totedge
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_selected_e)

    cdef np.ndarray get_is_selected_faces_array(self):
        """Get selected array of faces as NumPy array (zero-copy)"""
        cdef size_t size = self.bmesh.totface
        return np.PyArray_SimpleNewFromData(1, [size], np.NPY_UINT8, self.is_selected_f)
