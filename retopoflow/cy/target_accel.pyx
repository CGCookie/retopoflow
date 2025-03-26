# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=True

import time

import numpy as np
cimport numpy as np
np.import_array()  # Required for NumPy C-API

from libc.stdint cimport uintptr_t, uint8_t
from libc.stdlib cimport malloc, free, calloc
from libc.string cimport memset, memcpy
from libc.stdio cimport printf
from libc.math cimport sqrt, fabs, fmin, fmax
from cython.parallel cimport parallel, prange
from cython.operator cimport dereference as deref, preincrement as inc
from libcpp.vector cimport vector
from libcpp.set cimport set as cpp_set
from libcpp.pair cimport pair
from libcpp.iterator cimport iterator

import cython

from .bl_types.bmesh_types cimport BMVert, BMEdge, BMFace, BMesh, BMHeader, BMLoop
from .bl_types.bmesh_py_wrappers cimport BPy_BMesh, BPy_BMVert, BPy_BMEdge, BPy_BMFace
from .bl_types.bmesh_flags cimport BMElemHFlag, BM_elem_flag_test, BM_elem_flag_set, BM_elem_flag_clear
from .bl_types cimport ARegion, RegionView3D
from .utils cimport vec3_normalize, vec3_dot, location_3d_to_region_2d
from .math_matrix cimport mul_v4_m4v4, mul_m4_v4
from .vector_utils cimport copy_v4_to_v3, div_v3_f, copy_v3f_to_v4

import mathutils

cdef float finf = <float>1e1000


@cython.binding(True)
cdef class TargetMeshAccel:

    def __cinit__(self):
        # Initialize geometry arrays
        self.visverts = NULL
        self.visedges = NULL
        self.visfaces = NULL
        self.totvisverts = 0
        self.totvisedges = 0
        self.totvisfaces = 0

        # Initialize dirty flags
        self.is_dirty_geom_vis = True
        self.is_dirty_accel = True

        self.last_totvert = 0
        self.last_totedge = 0
        self.last_totface = 0

        self.use_symmetry = bVec3(False, False, False)

        self.depth_buffer_dimensions[0] = 0
        self.depth_buffer_dimensions[1] = 0

        self.accel = spatial_accel_new()
        if self.accel == NULL:
            raise MemoryError("Failed to allocate SpatialAccel")

    def __init__(self,
        object py_object,
        object py_bmesh,
        object py_region,
        object py_space,
        object py_rv3d,
        object vert_wrapper = None,
        object edge_wrapper = None,
        object face_wrapper = None
    ):
        print(f"[CYTHON] Accel2D.__init__({py_object}, {py_bmesh}, {py_region}, {py_rv3d})")

        self.vert_wrapper = vert_wrapper
        self.edge_wrapper = edge_wrapper
        self.face_wrapper = face_wrapper

        self.py_update_object(py_object)
        self.py_update_bmesh(py_bmesh)
        self.py_update_region(py_region)
        self.py_update_view(py_space, py_rv3d)

    cpdef void update(self, float margin_check, int selection_mode, bint debug=False):
        if debug:
            # Use Python objects for timing to avoid Cython conversion issues
            start_time = time.time()
            print("[CYTHON] TargetMeshAccel.update()")

        self.ensure_bmesh()
        if debug:
            current_time = time.time()
            print(f"\t- Ensure BMesh took: {round(current_time - start_time, 5)} seconds")
            step_start_time = current_time

        if self._compute_geometry_visibility_in_region(margin_check, selection_mode) != 0:
            print("[CYTHON] Error: Failed to compute geometry visibility in region\n")
            return
        if debug:
            current_time = time.time()
            print(f"\t- Compute Geom Visibility took: {round(current_time - step_start_time, 5)} seconds")
            step_start_time = current_time

        self._build_accel_struct(debug=debug)
        if debug:
            current_time = time.time()
            print(f"\t- Build SpatialAccel struct: {round(current_time - step_start_time, 5)} seconds")
            print(f"\t- TOTAL TIME: {round(current_time - start_time, 5)} seconds")

    def __dealloc__(self):
        if self.accel != NULL:
            spatial_accel_free(self.accel)
            self.accel = NULL

        self._reset()

    cdef void _update_object_transform(self, const float[:, ::1] matrix_world, const float[:, ::1] matrix_normal) nogil:
        cdef:
            int i, j

        for i in range(4):
            for j in range(4):
                self.matrix_world[i][j] = matrix_world[i,j]
                self.matrix_normal[i][j] = matrix_normal[i,j]
        
        self.set_dirty()

    cdef void _update_view(self, const float[:, ::1] proj_matrix, const float[::1] view_pos, const float[::1] view_dir, bint is_perspective, float clip_near, float clip_far) nogil:
        cdef:
            int i, j

        # Update view3d parameters
        for i in range(4):
            for j in range(4):
                self.view3d.proj_matrix[i][j] = proj_matrix[i,j]

        for i in range(3):
            self.view3d.view_pos[i] = view_pos[i]
            self.view3d.view_dir[i] = view_dir[i]

        self.view3d.is_persp = is_perspective
        self.view3d.clip_near = clip_near
        self.view3d.clip_far = clip_far

        self.set_dirty()

    cpdef int ensure_bmesh(self):
        """Ensure lookup tables are created for the bmesh and indices are updated (sorted in ascending order).

            ### Returns:
                - `-1`, if something went wrong.
                - `0`, if all went ok and no updates were made to bmesh tables or indices.
                - `1`, if updates were made to bmesh tables or indices.
        """
        if self.bmesh == NULL:
            print(f"[CYTHON] Accel2D.ensure_bmesh() - bmesh is NULL")
            return -1

        if not self.py_bmesh.is_valid:
            print(f"[CYTHON] Accel2D.ensure_bmesh() - py_bmesh is invalid")
            return -1

        cdef:
            bint vtable_dirty = False
            bint etable_dirty = False
            bint ftable_dirty = False

            # We make up to 5 checks to be sure that the indices are updated and in order.
            int i, step
            bint vindices_dirty = False
            bint eindices_dirty = False
            bint findices_dirty = False

        if self.bmesh.vtable == NULL:
            vtable_dirty = True
        elif self.last_totvert != self.bmesh.totvert:
            vtable_dirty = True
            vindices_dirty = True
        else:
            try:
                self.py_bmesh.verts[0]
            except IndexError:
                vtable_dirty = True

        if self.bmesh.etable == NULL:
            etable_dirty = True
        elif self.last_totedge != self.bmesh.totedge:
            etable_dirty = True
            eindices_dirty = True
        else:
            try:
                self.py_bmesh.edges[0]
            except IndexError:
                etable_dirty = True

        if self.bmesh.ftable == NULL:
            ftable_dirty = True
        elif self.last_totface != self.bmesh.totface:
            ftable_dirty = True
            findices_dirty = True
        else:
            try:
                self.py_bmesh.faces[0]
            except IndexError:
                ftable_dirty = True

        if vtable_dirty:
            print(f"[CYTHON] py_bmesh.verts.ensure_lookup_table()\n")
            self.py_bmesh.verts.ensure_lookup_table()

        if etable_dirty:
            print(f"[CYTHON] py_bmesh.edges.ensure_lookup_table()\n")
            self.py_bmesh.edges.ensure_lookup_table()

        if ftable_dirty:
            print(f"[CYTHON] py_bmesh.faces.ensure_lookup_table()\n")
            self.py_bmesh.faces.ensure_lookup_table()

        if not vindices_dirty:
            # Calculate step size: if totvert is 25, step should be 5
            step = max(self.bmesh.totvert // 5, 1)  # Ensure minimum step of 1
            for i in range(0, min(self.bmesh.totvert, 5 * step), step):
                if self.py_bmesh.verts[i].index != i:
                    self.vindices_dirty = True
                    break
        
        if not eindices_dirty:
            step = max(self.bmesh.totedge // 5, 1)  # Ensure minimum step of 1
            for i in range(0, min(self.bmesh.totedge, 5 * step), step):
                if self.py_bmesh.edges[i].index != i:
                    self.eindices_dirty = True
                    break

        if not findices_dirty:
            step = max(self.bmesh.totface // 5, 1)  # Ensure minimum step of 1
            for i in range(0, min(self.bmesh.totface, 5 * step), step):
                if self.py_bmesh.faces[i].index != i:
                    self.findices_dirty = True
                    break

        if vindices_dirty:
            self.py_bmesh.verts.index_update()
            print(f"[CYTHON] py_bmesh.verts.index_update()")
        
        if eindices_dirty:
            self.py_bmesh.edges.index_update()
            print(f"[CYTHON] py_bmesh.edges.index_update()")

        if findices_dirty:
            self.py_bmesh.faces.index_update()
            print(f"[CYTHON] py_bmesh.faces.index_update()")

        if vtable_dirty or etable_dirty or ftable_dirty:
            self.set_dirty()

        self.last_totvert = self.bmesh.totvert
        self.last_totedge = self.bmesh.totedge
        self.last_totface = self.bmesh.totface

        if vtable_dirty or etable_dirty or ftable_dirty or vindices_dirty or eindices_dirty or findices_dirty:
            return 1
        return 0

    cdef int _compute_geometry_visibility_in_region(self, float margin_check, int selection_mode) noexcept nogil:
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
            int i, j, k, count = 0
            int vert_idx, edge_idx, face_idx
            float[3] world_pos
            float[3] world_normal
            float[3] view_dir
            float[4] screen_pos
            float[2] region_pos
            float depth, buff_depth
            BMVert* vert
            BMEdge* edge
            BMFace* face
            BMLoop* loop
            int totvisvert = 0
            int totvisedge = 0
            int totvisface = 0

            # Cache BMesh data before nogil section
            BMVert** vtable = self.bmesh.vtable
            BMEdge** etable = self.bmesh.etable
            BMFace** ftable = self.bmesh.ftable
            int totvert = self.bmesh.totvert
            int totedge = self.bmesh.totedge
            int totface = self.bmesh.totface
            View3D view3d = self.view3d
            bint is_persp = view3d.is_persp
        
        self._reset()

        # Allocate visibility arrays with error checking
        is_vert_visible = <uint8_t*>malloc(totvert * sizeof(uint8_t))
        is_edge_visible = <uint8_t*>malloc(totedge * sizeof(uint8_t))
        is_face_visible = <uint8_t*>malloc(totface * sizeof(uint8_t))

        if is_vert_visible == NULL or is_edge_visible == NULL or is_face_visible == NULL:
            with gil:
                print(f"[CYTHON] Error: Failed to allocate visibility arrays\n")
            if is_vert_visible != NULL:
                free(is_vert_visible)
            if is_edge_visible != NULL:
                free(is_edge_visible)
            if is_face_visible != NULL:
                free(is_face_visible)
            return -1

        # Initialize arrays to zero
        memset(is_vert_visible, 0, totvert * sizeof(uint8_t))
        memset(is_edge_visible, 0, totedge * sizeof(uint8_t))
        memset(is_face_visible, 0, totface * sizeof(uint8_t))

        # Compute visible vertices on screen (region space).
        for vert_idx in prange(totvert, nogil=True, schedule='static'):
            vert = vtable[vert_idx]
            # Skip NULL/invalid vertices.
            if vert == NULL:
                with gil:
                    print(f"[CYTHON] vert {vert_idx} is NULL")
                continue

            '''if selection_mode == SelectionState.SELECTED:
                # ONLY SELECTED
                if not BM_elem_flag_test(&vert.head, BMElemHFlag.BM_ELEM_SELECT):
                    continue
            elif selection_mode == SelectionState.UNSELECTED:
                # ONLY UNSELECTED
                if BM_elem_flag_test(&vert.head, BMElemHFlag.BM_ELEM_SELECT):
                    continue'''

            # Skip hidden vertices.
            if BM_elem_flag_test(&vert.head, BMElemHFlag.BM_ELEM_HIDDEN):
                with gil:
                    print(f"[CYTHON] vert {vert_idx} is hidden")
                continue

            if self.compute_vert_visibility(vert):
                is_vert_visible[vert.head.index] = 1
                totvisvert += 1

        # Compute visible edges and faces based on vertices.
        with parallel():
            for edge_idx in prange(totedge):
                edge = etable[edge_idx]
                if edge == NULL:
                    continue

                if BM_elem_flag_test(&edge.head, BMElemHFlag.BM_ELEM_HIDDEN):
                    continue

                if is_vert_visible[(<BMVert*>edge.v1).head.index] or\
                   is_vert_visible[(<BMVert*>edge.v2).head.index]:
                    is_edge_visible[edge.head.index] = 1
                    totvisedge += 1

            for face_idx in prange(totface):
                face = ftable[face_idx]
                if face == NULL:
                    continue
                
                if BM_elem_flag_test(&face.head, BMElemHFlag.BM_ELEM_HIDDEN):
                    continue

                loop = <BMLoop*>face.l_first
                if loop == NULL:
                    continue
                for k in range(face.len):
                    if is_vert_visible[(<BMVert*>loop.v).head.index]:
                        is_face_visible[face.head.index] = 1
                        totvisface += 1
                        break
                    else:
                        loop = <BMLoop*>loop.next
                        if loop == NULL:
                            break

        # Allocate final arrays with exact sizes
        self.visverts = <BMVert**>calloc(totvisvert, sizeof(BMVert*))
        self.visedges = <BMEdge**>calloc(totvisedge, sizeof(BMEdge*))
        self.visfaces = <BMFace**>calloc(totvisface, sizeof(BMFace*))

        if self.visverts == NULL or self.visedges == NULL or self.visfaces == NULL:

            with gil:
                print(f"[CYTHON] Error: Failed to allocate geometry arrays\n")
            # Clean up all allocations
            if self.visverts != NULL:
                free(self.visverts)
                self.visverts = NULL
            if self.visedges != NULL:
                free(self.visedges)
                self.visedges = NULL
            if self.visfaces != NULL:
                free(self.visfaces)
                self.visfaces = NULL
            free(is_vert_visible)
            free(is_edge_visible)
            free(is_face_visible)
            return -1

        # Initialize arrays
        memset(self.visverts, 0, totvisvert * sizeof(BMVert*))
        memset(self.visedges, 0, totvisedge * sizeof(BMEdge*))
        memset(self.visfaces, 0, totvisface * sizeof(BMFace*))

        vert_idx = 0
        edge_idx = 0
        face_idx = 0

        for i in range(totvert):
            vert = vtable[i]
            if is_vert_visible[vert.head.index]:
                self.visverts[vert_idx] = vert
                vert_idx += 1
        for i in range(totedge):
            edge = etable[i]
            if is_edge_visible[edge.head.index]:
                self.visedges[edge_idx] = edge
                edge_idx += 1
        for i in range(totface):
            face = ftable[i]
            if is_face_visible[face.head.index]:
                self.visfaces[face_idx] = face
                face_idx += 1


        with gil:
            print(f"[CYTHON] totvisverts: {totvisvert}")
            print(f"[CYTHON] totvisedges: {totvisedge}")
            print(f"[CYTHON] totvisfaces: {totvisface}")

        # Store vis states for verts/edges/faces.
        self.is_vert_visible = is_vert_visible
        self.is_edge_visible = is_edge_visible
        self.is_face_visible = is_face_visible

        self.totvisverts = totvisvert
        self.totvisedges = totvisedge
        self.totvisfaces = totvisface

        self.is_dirty_geom_vis = False
        self.is_dirty_accel = True

        return 0

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
        # Free and reset geometry arrays
        if self.visverts != NULL:
            free(self.visverts)
            self.visverts = NULL
        if self.visedges != NULL:
            free(self.visedges)
            self.visedges = NULL
        if self.visfaces != NULL:
            free(self.visfaces)
            self.visfaces = NULL

        self.totvisverts = 0
        self.totvisedges = 0
        self.totvisfaces = 0

        if dirty:
            self.set_dirty()

    cdef void set_dirty(self) noexcept nogil:
        """Set the dirty flag"""
        self.is_dirty_geom_vis = True
        self.is_dirty_accel = True


    # ----------------------------------------------------------------------------------------
    # Depth Buffer handling.
    # ----------------------------------------------------------------------------------------

    cdef void update_depth_buffer(self, float[:, ::1] depth_buffer, int width, int height) noexcept nogil:
        # No need to free - memoryviews are managed by Python
        self.depth_buffer = depth_buffer
        self.depth_buffer_dimensions[0] = width
        self.depth_buffer_dimensions[1] = height

    cpdef void py_update_depth_buffer(self, np.ndarray[np.float32_t, ndim=2] depth_buffer, int width, int height):
        self.update_depth_buffer(depth_buffer, width, height)

    cdef float get_depth_from_buffer(self, int x, int y) noexcept nogil:
        # Check if depth buffer exists and has valid dimensions
        cdef int width = self.depth_buffer_dimensions[0]
        cdef int height = self.depth_buffer_dimensions[1]
        
        # Check if buffer is uninitialized or dimensions are invalid
        if width <= 0 or height <= 0:
            return -1.0  # Invalid depth value
        
        # Bounds checking
        if x < 0 or x >= width or y < 0 or y >= height:
            return -1.0  # Out of bounds
        
        # Use direct 2D indexing instead of calculating 1D offset
        return self.depth_buffer[x, y]


    # ----------------------------------------------------------------------------------------
    # Space Convert Utilities.
    # ----------------------------------------------------------------------------------------

    cdef void l2w_point(self, const float[3] local_pos, float[3] world_pos) noexcept nogil:
        cdef:
            float[4] vec4
        # Local to World space transformation (l2w_point equivalent)
        # Convert to homogeneous coordinates and transform
        # v = self.mx_p @ Vector((p.x, p.y, p.z, 1.0))
        # return Point(v.xyz / v.w)
        copy_v3f_to_v4(local_pos, <float>1.0, vec4)
        mul_m4_v4(self.matrix_world, vec4)  # local to world space
        copy_v4_to_v3(vec4, world_pos)  # xyz
        w = vec4[3]  # w
        div_v3_f(world_pos, w)  # v.xyz / v.w

    cdef void project_wpoint_to_region_2d(self, float[3] world_pos, float[2] point2d) noexcept nogil:
        location_3d_to_region_2d(self.region, self.rv3d.persmat, world_pos, &point2d[0])

    cdef void project_lpoint_to_region_2d(self, float[3] local_pos, float[2] point2d) noexcept nogil:
        cdef float[3] world_pos
        self.l2w_point(local_pos, world_pos)
        self.project_wpoint_to_region_2d(world_pos, point2d)

    cdef void project_vert_to_region_2d(self, BMVert* vert, float[2] point2d) noexcept nogil:
        self.project_lpoint_to_region_2d(vert.co, point2d)

    cdef float compute_wpoint_depth(self, float[3] co) noexcept nogil:
        cdef:
            float[4] co_world
            float[4] co_view
            # float[4] co_ndc
            float view_z
            # float depth_ndc
            float near = self.view3d.clip_near
            float far = self.view3d.clip_far
            float raw_depth, linear_depth

        # Transform from world to view space
        copy_v3f_to_v4(co, <float>1.0, co_world)
        mul_v4_m4v4(co_view, self.rv3d.viewmat, co_world)

        # Get the view Z (negative because view space Z points away from the camera)
        view_z = -co_view[2]

        # Calculate depth using the near/far plane method
        # Method 1: Linear depth from view Z
        # First get normalized depth (0-1) range from view_z
        linear_depth = (view_z - near) / (far - near)

        '''
        # Transform from view to NDC space
        mul_v4_m4v4(co_ndc, self.rv3d.persmat, co_view)

        # Perform perspective divide to get normalized coordinates
        div_v3_f(co_ndc, co_ndc.w)

        # Convert NDC Z [-1, 1] to depth buffer [0, 1]
        depth_ndc = (co_ndc[2] + 1.0) * 0.5

        # Method 2: Non-linear depth from projection matrix
        # Based on the formula from common_view_lib.glsl
        if region3d.is_perspective:
            # For perspective projection
            depth_nonlinear = (-proj_matrix[3][2] / (proj_matrix[2][2] + co_ndc.z))
            depth_nonlinear = (depth_nonlinear - near) / (far - near)
        else:
            # For orthographic projection
            depth_nonlinear = (-(proj_matrix[3][2] + co_ndc.z) / proj_matrix[2][2])
            depth_nonlinear = (depth_nonlinear - near) / (far - near)
        
        # Method 3: Direct calculation using persmat (most accurate to depth buffer)
        co_clip = persmat @ co_world.to_4d()
        depth_persmat = co_clip.z / co_clip.w
        depth_buffer = (depth_persmat + 1.0) * 0.5
        '''

        return linear_depth

    cdef float compute_lpoint_depth(self, float[3] co) noexcept nogil:
        cdef float[3] world_co
        self.l2w_point(co, world_co)
        return self.compute_wpoint_depth(world_co)

    cdef float compute_vert_depth(self, BMVert* vert) noexcept nogil:
        return self.compute_lpoint_depth(vert.co)

    cdef bint compute_wpoint_visibility(self, float[3] world_pos, float[3] world_normal) noexcept nogil:
        return is_wpoint_visible(
            world_pos, 
            world_normal, 
            self.view3d.proj_matrix,
            self.view3d.view_dir,
            self.region, 
            self.rv3d, 
            self.depth_buffer, 
            self.depth_buffer_dimensions[0], 
            self.depth_buffer_dimensions[1]
        )

    cdef bint compute_lpoint_visibility(self, float[3] co, float[3] no) noexcept nogil:
        cdef:
            float[3] world_pos
            float[3] world_normal
        self.l2w_point(co, world_pos)
        self.l2w_point(no, world_normal)
        vec3_normalize(world_normal)
        return self.compute_wpoint_visibility(world_pos, world_normal)

    cdef bint compute_vert_visibility(self, BMVert* vert) noexcept nogil:
        return self.compute_lpoint_visibility(vert.co, vert.no)


    '''
    ______________________________________________________________________________________________________________
    
    Python access methods 
    ______________________________________________________________________________________________________________
    '''

    cpdef tuple[set, set, set] get_visible_geom(self, object py_bmesh, bint verts=True, bint edges=True, bint faces=True,  bint invert_selection=False, bint wrapped=True):
        """Return sets of visible geometry"""
        if not self.bmesh or not self.bmesh.vtable:
            printf("Accel2D.get_visible_geom() - bmesh or vtable is NULL\n")
            return set(), set(), set()

        cdef:
            BMVert* vert
            BMEdge* edge
            BMFace* face
            BMVert** visverts = self.visverts
            BMEdge** visedges = self.visedges
            BMFace** visfaces = self.visfaces
            set vis_py_verts = set()
            set vis_py_edges = set()
            set vis_py_faces = set()
            object py_bm_verts = py_bmesh.verts
            object py_bm_edges = py_bmesh.edges
            object py_bm_faces = py_bmesh.faces
            object vert_wrapper = self.vert_wrapper
            object edge_wrapper = self.edge_wrapper
            object face_wrapper = self.face_wrapper
            int i, j, k

        with nogil, parallel():
            if verts:
                for i in prange(self.totvisverts):
                    vert = visverts[i]
                    if vert is NULL:
                        continue
                    if wrapped:
                        with gil:
                            vis_py_verts.add(vert_wrapper(py_bm_verts[vert.head.index]))
                    else:
                        with gil:
                            vis_py_verts.add(py_bm_verts[vert.head.index])

            if edges:
                for j in prange(self.totvisedges):
                    edge = visedges[j]
                    if edge is NULL:
                        continue
                    if wrapped:
                        with gil:
                            vis_py_edges.add(edge_wrapper(py_bm_edges[edge.head.index]))
                    else:
                        with gil:
                            vis_py_edges.add(py_bm_edges[edge.head.index])

            if faces:
                for k in prange(self.totvisfaces):
                    face = visfaces[k]
                    if face is NULL:
                        continue
                    if wrapped:
                        with gil:
                            vis_py_faces.add(face_wrapper(py_bm_faces[face.head.index]))
                    else:
                        with gil:
                            vis_py_faces.add(py_bm_faces[face.head.index])

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


    # ---------------------------------------------------------------------------------------
    # Acceleration structure methods.
    # ---------------------------------------------------------------------------------------

    cdef void add_vert_to_grid(self, BMVert* vert, int insert_index) noexcept nogil:
        """Add vertex to grid"""
        cdef:
            float[3] world_pos
            float[2] screen_pos
            float depth = 0.0  # Initialize depth

        # Transform vertex to world space
        self.l2w_point(vert.co, world_pos)
        
        # Project to screen space with depth
        self._project_point_to_screen(world_pos, screen_pos, &depth)

        # Add to accel grid with proper depth
        # cdef (SpatialAccel* accel, void* elem, int index, float x, float y, float depth, GeomType geom_type)
        spatial_accel_add_element(self.accel, insert_index, <void*>vert, vert.head.index, screen_pos[0], screen_pos[1], depth, SpatialGeomType.VERT)

    cdef void add_edge_to_grid(self, BMEdge* edge, int insert_index, int num_samples) noexcept nogil:
        """Add edge samples to grid"""
        cdef:
            float[3] v1_world, v2_world, sample_pos
            float[2] screen_pos
            float depth = 0.0, t
            int i, j
            BMVert* v1 = <BMVert*>edge.v1
            BMVert* v2 = <BMVert*>edge.v2

        # Transform vertices to world space
        self.l2w_point(v1.co, v1_world)
        self.l2w_point(v2.co, v2_world)

        # Add samples along edge
        for i in range(num_samples):
            t = (<float>i + <float>1.0) / (<float>num_samples + <float>1.0)  # Exclude endpoints
            
            # Interpolate position
            for j in range(3):
                sample_pos[j] = v1_world[j] * (<float>1.0-t) + v2_world[j] * t
            
            # Project to screen space with depth
            self._project_point_to_screen(sample_pos, screen_pos, &depth)

            # Add to accel grid with proper depth
            spatial_accel_add_element(self.accel, insert_index, <void*>edge, edge.head.index, screen_pos[0], screen_pos[1], depth, SpatialGeomType.EDGE)

    cdef void add_face_to_grid(self, BMFace* face, int insert_index) noexcept nogil:
        """Add face centroid to grid"""
        cdef:
            float[3] centroid, world_centroid
            float[2] screen_pos
            float depth = 0.0
            int i, j, num_verts = 0
            BMLoop* l_iter = <BMLoop*>face.l_first
            BMVert* vert

        # Compute face centroid in local space
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

        # Divide by num_verts to get the actual centroid
        for i in range(3):
            centroid[i] /= num_verts

        # Transform to world space
        self.l2w_point(centroid, world_centroid)
        
        # Project to screen space with depth
        self._project_point_to_screen(world_centroid, screen_pos, &depth)

        # Add to accel grid with proper depth
        spatial_accel_add_element(self.accel, insert_index, <void*>face, face.head.index, screen_pos[0], screen_pos[1], depth, SpatialGeomType.FACE)

    cdef void _build_accel_struct(self, bint debug=False) noexcept nogil:
        """Build acceleration structure for efficient spatial queries"""
        if debug:
            with gil:
                print("[CYTHON] Starting _build_accel_struct()")

        if not self.is_dirty_accel:
            with gil:
                print("[CYTHON] Skipping _build_accel_struct() because accel is not dirty")
            return

        # Validate accel pointer
        if self.accel == NULL:
            with gil:
                print("[CYTHON] ERROR: self.accel is NULL!")
            return

        # Use a smaller grid to avoid memory issues
        cdef int grid_width = 64
        cdef int grid_height = 64

        # Check if region dimensions are valid
        if self.region == NULL or self.region.winx <= 0 or self.region.winy <= 0:
            with gil:
                print("[CYTHON] ERROR: Invalid region or region dimensions")
            return

        cdef:
            int edge_samples = 2
            int edge_insert_index_offset = self.totvisverts
            int face_insert_index_offset = edge_insert_index_offset + self.totvisedges * edge_samples
            int totelem = self.totvisverts + self.totvisedges * edge_samples + self.totvisfaces
            int i
            BMVert* vert
            BMEdge* edge
            BMFace* face

        # Initialize the spatial acceleration structure
        spatial_accel_init(self.accel, totelem, 0.0, 0.0, self.region.winx, self.region.winy, grid_width, grid_height)

        # Check initialization status
        if not self.accel.is_initialized or self.accel.grid == NULL:
            with gil:
                print("[CYTHON] ERROR: Failed to initialize spatial acceleration structure")
            return
        
        if debug:
            with gil:
                print(f"[CYTHON] Accel bounds: ({self.accel.min_x}, {self.accel.min_y}) -> ({self.accel.max_x}, {self.accel.max_y})")
                print(f"[CYTHON] Grid size: {grid_width}x{grid_height} with cell size: {self.accel.cell_size_x} x {self.accel.cell_size_y}")
                print(f"[CYTHON] Adding {self.totvisverts} vertices, {self.totvisedges} edges, {self.totvisfaces} faces to grid")

        # Add vertices to grid
        if self.totvisverts > 0:
            with gil:
                print("[CYTHON] Adding vertices to grid")
            for i in range(self.totvisverts):
                vert = self.visverts[i]
                if vert == NULL:
                    continue
                self.add_vert_to_grid(vert, i)

        # Add edges to grid
        if self.totvisedges > 0:
            with gil:
                print("[CYTHON] Adding edges to grid")
            for i in range(self.totvisedges):
                edge = self.visedges[i]
                if edge == NULL:
                    continue
                self.add_edge_to_grid(edge, edge_insert_index_offset + i, edge_samples)

        # Add faces to grid
        if self.totvisfaces > 0:
            with gil:
                print("[CYTHON] Adding faces to grid")
            for i in range(self.totvisfaces):
                face = self.visfaces[i]
                if face == NULL:
                    continue
                self.add_face_to_grid(face, face_insert_index_offset + i)

        self.is_dirty_accel = False

        with gil:
            print("[CYTHON] Updating grid indices")

        spatial_accel_update_grid_indices(self.accel)

        self.is_dirty_accel = False
        
        if debug:
            with gil:
                print("[CYTHON] Successfully built acceleration structure")


    # ------------------------------------------------------------------------------------
    # Select-Box Utils.
    # ------------------------------------------------------------------------------------

    cdef bint _segment2D_intersection(self, float[2] p0, float[2] p1, float[2] p2, float[2] p3) noexcept nogil:
        cdef:
            float s1_x = p1[0] - p0[0]
            float s1_y = p1[1] - p0[1]
            float s2_x = p3[0] - p2[0]
            float s2_y = p3[1] - p2[1]
            float s = (-s1_y * (p0[0] - p2[0]) + s1_x * (p0[1] - p2[1])) / (-s2_x * s1_y + s1_x * s2_y)
            float t = (s2_x * (p0[1] - p2[1]) - s2_y * (p0[0] - p2[0])) / (-s2_x * s1_y + s1_x * s2_y)

        return (s >= 0 and s <= 1 and t >= 0 and t <= 1)

    cdef bint _triangle2D_overlap(self, float[3][2] tri1, float[3][2] tri2) noexcept nogil:
        # Simple AABB overlap test for triangles
        cdef:
            float min_x1 = fmin(fmin(tri1[0][0], tri1[1][0]), tri1[2][0])
            float max_x1 = fmax(fmax(tri1[0][0], tri1[1][0]), tri1[2][0])
            float min_y1 = fmin(fmin(tri1[0][1], tri1[1][1]), tri1[2][1])
            float max_y1 = fmax(fmax(tri1[0][1], tri1[1][1]), tri1[2][1])
            float min_x2 = fmin(fmin(tri2[0][0], tri2[1][0]), tri2[2][0])
            float max_x2 = fmax(fmax(tri2[0][0], tri2[1][0]), tri2[2][0])
            float min_y2 = fmin(fmin(tri2[0][1], tri2[1][1]), tri2[2][1])
            float max_y2 = fmax(fmax(tri2[0][1], tri2[1][1]), tri2[2][1])

        return not (max_x1 < min_x2 or min_x1 > max_x2 or max_y1 < min_y2 or min_y1 > max_y2)

    cdef bint _vert_inside_box(self, BMVert* vert, float[4] box) noexcept nogil:
        """Check if vertex is inside box"""
        cdef float[2] screen_pos
        self.project_vert_to_region_2d(vert, screen_pos)
        return (box[0] <= screen_pos[0] <= box[1]) and (box[2] <= screen_pos[1] <= box[3])

    cdef bint select_box(self, float left, float right, float bottom, float top, GeomType select_geometry_type, bint use_ctrl=False, bint use_shift=False) noexcept nogil:
        """Select geometry within the given box coordinates"""

        # Update mesh vis only.
        if self.is_dirty_geom_vis:
            if self._compute_geometry_visibility_in_region(<float>1.0, <int>SelectionState.ALL) != 0:
                with gil:
                    print("[CYTHON] Error updating visible geometry when select-box!")
                return False

        cdef:
            cpp_set[BMVert*].iterator vert_it
            cpp_set[BMEdge*].iterator edge_it
            cpp_set[BMFace*].iterator face_it
            BMVert* vert
            BMEdge* edge
            BMFace* face
            BMLoop* loop
            BMHeader* head
            int i, j, k
            bint selection_changed
            float[4] box

        box[0] = left
        box[1] = right
        box[2] = bottom
        box[3] = top

        if not use_ctrl and not use_shift:
            if self.deselect_all(GeomType.BM_ALL):
                selection_changed = True

        '''print("[PYTHON] PERSPECTIVE MATRIX:")
        mat = self.py_rv3d.perspective_matrix
        for i in range(4):
            for j in range(4):
                print("\t", mat[i][j])
        print("[PYTHON]", self.py_region.width, self.py_region.height)
        print("[CYTHON] PERSPECTIVE MATRIX:")
        for i in range(4):
            for j in range(4):
                print("\t", perspmat[j][i])
        print("[CYTHON] REGION SIZE:", self.region.winx, self.region.winy)'''

        '''print("[CYTHON] MATRIX WORLD:")
        for i in range(4):
            for j in range(4):
                print("\t", mw[j][i])'''

        # Iterate over visible geometry based on type
        if select_geometry_type == GeomType.BM_VERT:
            for i in prange(self.totvisverts):
                vert = self.visverts[i]
                if self._vert_inside_box(vert, box):
                    head = &vert.head
                    if use_ctrl:
                        BM_elem_flag_clear(head, BMElemHFlag.BM_ELEM_SELECT)
                    else:
                        BM_elem_flag_set(head, BMElemHFlag.BM_ELEM_SELECT)
                    selection_changed = True

        elif select_geometry_type == GeomType.BM_EDGE:
            for j in prange(self.totvisedges):
                edge = self.visedges[j]
                # Check both vertices of the edge
                if self._vert_inside_box(<BMVert*>edge.v1, box) or\
                   self._vert_inside_box(<BMVert*>edge.v2, box):
                    # Select edge and its vertices
                    if use_ctrl:
                        BM_elem_flag_clear(&edge.head, BMElemHFlag.BM_ELEM_SELECT)
                        BM_elem_flag_clear(&(<BMVert*>edge.v1).head, BMElemHFlag.BM_ELEM_SELECT)
                        BM_elem_flag_clear(&(<BMVert*>edge.v2).head, BMElemHFlag.BM_ELEM_SELECT)
                    else:
                        BM_elem_flag_set(&edge.head, BMElemHFlag.BM_ELEM_SELECT)
                        BM_elem_flag_set(&(<BMVert*>edge.v1).head, BMElemHFlag.BM_ELEM_SELECT)
                        BM_elem_flag_set(&(<BMVert*>edge.v2).head, BMElemHFlag.BM_ELEM_SELECT)
                    selection_changed = True

        elif select_geometry_type == GeomType.BM_FACE:
            for k in prange(self.totvisfaces):
                face = self.visfaces[k]
                # Check all vertices of the face
                loop = <BMLoop*>face.l_first
                while 1:
                    if self._vert_inside_box(<BMVert*>loop.v, box):
                        if use_ctrl:
                            BM_elem_flag_clear(&face.head, BMElemHFlag.BM_ELEM_SELECT)
                        else:
                            BM_elem_flag_set(&face.head, BMElemHFlag.BM_ELEM_SELECT)
                        loop = <BMLoop*>face.l_first
                        while loop:
                            if use_ctrl:
                                BM_elem_flag_clear(&(<BMVert*>loop.v).head, BMElemHFlag.BM_ELEM_SELECT)
                                BM_elem_flag_clear(&(<BMVert*>loop.e).head, BMElemHFlag.BM_ELEM_SELECT)
                            else:
                                BM_elem_flag_set(&(<BMVert*>loop.v).head, BMElemHFlag.BM_ELEM_SELECT)
                                BM_elem_flag_set(&(<BMVert*>loop.e).head, BMElemHFlag.BM_ELEM_SELECT)
                            loop = <BMLoop*>loop.next
                            if loop == <BMLoop*>face.l_first:
                                break
                        selection_changed = True
                        break

                    loop = <BMLoop*>loop.next
                    if loop == <BMLoop*>face.l_first:
                        break

        return selection_changed

    
    # ---------------------------------------------------------------------------------------
    # Selection Utils.
    # ---------------------------------------------------------------------------------------

    cdef bint deselect_all(self, GeomType geom_type = GeomType.BM_ALL) noexcept nogil:
        if self.bmesh == NULL:
            return False

        cdef:
            int vi, ei, fi
            BMVert** vtable
            BMVert* vert
            BMEdge** etable
            BMEdge* edge
            BMFace** ftable
            BMFace* face
            bint selection_changed = False

        if (geom_type == GeomType.BM_VERT) or (geom_type == GeomType.BM_ALL):
            vtable = self.bmesh.vtable
            if vtable == NULL:
                return selection_changed
            for vi in prange(self.bmesh.totvert):
                vert = vtable[vi]
                if vert == NULL:
                    continue
                if BM_elem_flag_test(&vert.head, BMElemHFlag.BM_ELEM_SELECT):
                    BM_elem_flag_clear(&vert.head, BMElemHFlag.BM_ELEM_SELECT)
                    selection_changed = True

        if (geom_type == GeomType.BM_EDGE) or (geom_type == GeomType.BM_ALL):
            etable = self.bmesh.etable
            if etable == NULL:
                return selection_changed
            for ei in prange(self.bmesh.totedge):
                edge = etable[ei]
                if edge == NULL:
                    continue
                if BM_elem_flag_test(&edge.head, BMElemHFlag.BM_ELEM_SELECT):
                    BM_elem_flag_clear(&edge.head, BMElemHFlag.BM_ELEM_SELECT)
                    selection_changed = True

        if (geom_type == GeomType.BM_FACE) or (geom_type == GeomType.BM_ALL):
            ftable = self.bmesh.ftable
            if ftable == NULL:
                return selection_changed
            for fi in prange(self.bmesh.totface):
                face = ftable[fi]
                if face == NULL:
                    continue
                if BM_elem_flag_test(&face.head, BMElemHFlag.BM_ELEM_SELECT):
                    BM_elem_flag_clear(&face.head, BMElemHFlag.BM_ELEM_SELECT)
                    selection_changed = True

        return selection_changed


    # ---------------------------------------------------------------------------------------
    # Python exposed methods.
    # ---------------------------------------------------------------------------------------

    cpdef void py_set_dirty_accel(self):
        self.is_dirty_accel = True

    cpdef void py_set_dirty_geom_vis(self):
        self.is_dirty_geom_vis = True
        self.is_dirty_accel = True

    cpdef void py_set_symmetry(self, bint x, bint y, bint z):
        if self.use_symmetry.x != x or self.use_symmetry.y != y or self.use_symmetry.z != z:
            self.use_symmetry.x = x
            self.use_symmetry.y = y
            self.use_symmetry.z = z
            self.py_set_dirty_accel()

    cpdef void py_update_bmesh(self, object py_bmesh):
        if not hasattr(self, 'py_bmesh') or id(self.py_bmesh) != id(py_bmesh):
            self.py_bmesh = py_bmesh
            self.bmesh_pywrapper = <BPy_BMesh*><uintptr_t>id(py_bmesh)
            self.bmesh = self.bmesh_pywrapper.bm

        self.ensure_bmesh()

    cpdef void py_update_object(self, object py_object):
        cdef:
            bint is_dirty = False
            int i = 0

        self.py_object = py_object

        matrix_world = np.array(py_object.matrix_world, dtype=np.float32)
        for i in range(4):
            for j in range(4):
                if matrix_world[i][j] != self.matrix_world[i][j]:
                    is_dirty = True
                    break

        if not is_dirty:
            return

        matrix_normal = np.array(py_object.matrix_world.inverted_safe().transposed().to_3x3(), dtype=np.float32)
        self._update_object_transform(matrix_world, matrix_normal)

    cpdef void py_update_region(self, object py_region):
        if hasattr(self, 'py_region') and id(self.py_region) == id(py_region):
            return

        self.py_region = py_region
        self.region = <ARegion*><uintptr_t>py_region.as_pointer()

        # print("region size:", self.region.winx, self.region.winy)

    cpdef void py_update_view(self, object py_space, object py_rv3d):
        cdef:
            bint is_perspective
            int i, j
            bint is_dirty

        # Force view update if possible
        # if hasattr(py_rv3d, 'update'):
        #     py_rv3d.update()

        self.py_rv3d = py_rv3d
        self.rv3d = <RegionView3D*><uintptr_t>py_rv3d.as_pointer()

        # Print winmat and viewmat for debugging
        '''print("[DEBUG] ID:", id(py_rv3d))
        print("[DEBUG] winmat and viewmat:")
        print(f"\twinmat: {[list(row) for row in py_rv3d.window_matrix]}")
        print(f"\tviewmat: {[list(row) for row in py_rv3d.view_matrix]}")

        # Print raw persmat from RegionView3D struct
        print("[CY] Raw persmat from RegionView3D:")
        for i in range(4):
            print(f"\t{[self.rv3d.persmat[j][i] for j in range(4)]}")

        # Print perspective_matrix from Python
        print("[PY] perspective_matrix from Python:")
        py_persmat = np.array(py_rv3d.perspective_matrix)
        for i in range(4):
            print(f"\t{py_persmat[i]}")'''

        proj_matrix = np.array(py_rv3d.perspective_matrix.copy(), dtype=np.float32)

        # print("proj matrix:", list(proj_matrix))

        for i in range(4):
            for j in range(4):
                if proj_matrix[i][j] != self.view3d.proj_matrix[i][j]:
                    is_dirty = True
                    break

        if not is_dirty:
            return

        # print("[CYTHON] User is navigating! Updating view data...")

        is_perspective = py_rv3d.is_perspective

        if is_perspective:
            view_pos = np.array(py_rv3d.view_matrix.inverted().translation, dtype=np.float32)
        else:
            view_pos = np.array(py_rv3d.view_matrix.inverted().col[2].xyz, dtype=np.float32)
        
        view_dir = np.array((py_rv3d.view_matrix.to_3x3().inverted_safe() @ mathutils.Vector((0,0,-1))).normalized(), dtype=np.float32)

        self._update_view(proj_matrix, view_pos, view_dir, <bint>is_perspective, py_space.clip_start, py_space.clip_end)

    cpdef bint py_update_geometry_visibility(self, float margin_check, int selection_mode, bint update_accel):
        if not self.is_dirty_geom_vis:
            return True
        if self._compute_geometry_visibility_in_region(margin_check, selection_mode) == 0:
            if update_accel:
                self._build_accel_struct()
            return True
        return False

    cpdef void py_update_accel_struct(self):
        self._build_accel_struct()


    cpdef bint py_select_box(self, float left, float right, float bottom, float top, int select_geometry_type, bint use_ctrl=False, bint use_shift=False):
        self.select_box(left, right, bottom, top, <GeomType>select_geometry_type, use_ctrl, use_shift)


    cpdef object _find_nearest(self, float x, float y, float depth, SpatialGeomType geom_type, int k=1, float max_dist=finf, bint wrapped=True):
        if k < 0:
            return None

        cdef vector[SpatialElementWithDistance] result = spatial_accel_get_nearest_elements(self.accel, x, y, depth, k, max_dist, geom_type)

        if result.size() == 0:
            if k == 1:
                return None
            return []

        cdef object wrapper

        if wrapped:
            if geom_type == SpatialGeomType.VERT:
                wrapper = self.vert_wrapper
            elif geom_type == SpatialGeomType.EDGE:
                wrapper = self.edge_wrapper
            elif geom_type == SpatialGeomType.FACE:
                wrapper = self.face_wrapper
            else:
                return None
        
        cdef SpatialGeomElement* elem_data
        cdef object py_elem
        cdef list output = []
        cdef int i

        for i in range(result.size()):
            elem_data = result[i].element
            if elem_data == NULL:
                continue
            if elem_data.elem != NULL:
                py_elem = self.py_bmesh.verts[elem_data.index]
                output.append({
                    'elem': wrapper(py_elem) if wrapped else py_elem,
                    'pos': (elem_data.x, elem_data.y),
                    'depth': elem_data.depth,
                    'distance':  result[i].distance
                })

        if k == 1:
            if len(output) == 0:
                return None
            return output[0]

        return output

    cpdef object find_nearest_vert(self, float x, float y, float depth, float max_dist=finf, bint wrapped=True):
        """Find nearest visible vertex to screen position"""
        return self._find_nearest(x, y, depth, SpatialGeomType.VERT, 1, max_dist, wrapped)

    cpdef object find_nearest_edge(self, float x, float y, float depth, float max_dist=finf, bint wrapped=True):
        """Find nearest visible edge to screen position"""
        return self._find_nearest(x, y, depth, SpatialGeomType.EDGE, 1, max_dist, wrapped)

    cpdef object find_nearest_face(self, float x, float y, float depth, float max_dist=finf, bint wrapped=True):
        """Find nearest visible face to screen position"""
        return self._find_nearest(x, y, depth, SpatialGeomType.FACE, 1, max_dist, wrapped)

    cpdef tuple find_nearest_geom(self, float x, float y, float depth, float max_dist=finf, bint wrapped=False):
        """Find nearest visible face to screen position"""
        cdef object result_v = self.find_nearest_vert(x, y, depth, max_dist, wrapped)
        cdef object result_e = self.find_nearest_edge(x, y, depth, max_dist, wrapped)
        cdef object result_f = self.find_nearest_face(x, y, depth, max_dist, wrapped)
        return (result_v, result_e, result_f)

    cpdef list find_k_nearest_verts(self, float x, float y, float depth, int k=0, float max_dist=finf, bint wrapped=True):
        """Find k nearest visible vertex to screen position"""
        assert k==1, "Use k=0 for infinite possible nearest element within range or specify a value greater than 1"
        return self._find_nearest(x, y, depth, SpatialGeomType.VERT, k, max_dist, wrapped)

    cpdef list find_k_nearest_edges(self, float x, float y, float depth, int k=0, float max_dist=finf, bint wrapped=True):
        """Find k nearest visible edge to screen position"""
        assert k==1, "Use k=0 for infinite possible nearest element within range or specify a value greater than 1"
        return self._find_nearest(x, y, depth, SpatialGeomType.EDGE, k, max_dist, wrapped)

    cpdef list find_k_nearest_faces(self, float x, float y, float depth, int k=0, float max_dist=finf, bint wrapped=True):
        """Find k nearest visible face to screen position"""
        assert k==1, "Use k=0 for infinite possible nearest element within range or specify a value greater than 1"
        return self._find_nearest(x, y, depth, SpatialGeomType.FACE, k, max_dist, wrapped)



cdef bint point_visible_in_3d_view(float[3] co, float[3] no, View3D view3d) noexcept nogil:
    cdef:
        float[4] clip_pos
        float[3] view_dir = view3d.view_dir
        float dot_product
        int i, j

    # Transform vertex position to clip space
    for i in range(4):
        clip_pos[i] = 0
        for j in range(3):
            clip_pos[i] += view3d.proj_matrix[i][j] * co[j]
        clip_pos[i] += view3d.proj_matrix[i][3]  # Add the w component

    # Perspective divide to get NDC
    if clip_pos[3] != 0:
        for i in range(3):
            clip_pos[i] /= clip_pos[3]

    # Check if the vertex is within the view frustum
    if not (-1 <= clip_pos[0] <= 1 and -1 <= clip_pos[1] <= 1 and -1 <= clip_pos[2] <= 1):
        return False

    # Check if the vertex normal is facing the camera
    dot_product = 0
    for i in range(3):
        dot_product += no[i] * view_dir[i]

    return dot_product < 0


cdef bint is_wpoint_visible(float[3] world_pos, float[3] world_normal, float[4][4] proj_matrix, float[3] view_dir, 
                           ARegion* region, RegionView3D* rv3d, float[:, ::1] depth_buffer, 
                           int buffer_width, int buffer_height) noexcept nogil:
    """
    Check if a vertex is visible in the current view
    
    Args:
        world_pos: The vertex position in world space
        world_normal: The vertex normal in world space
        view3d: View3D structure with view parameters
        region: The region
        rv3d: The region view 3D
        depth_buffer: The depth buffer data
        buffer_width: The framebuffer width
        buffer_height: The framebuffer height
        
    Returns:
        bool: True if the vertex is visible, False otherwise
    """
    cdef:
        float[2] region_pos
        float[4] co_world
        float[4] co_view
        float[4] co_clip
        float view_z, clip_z, clip_w, ndc_z
        float calculated_depth, vertex_depth
        float dot_product
        int x, y, i
        float depth_tolerance = <float>0.0001
    
    # Check if the vertex is within the view frustum and facing the camera
    # This is similar to point_visible_in_3d_view
    cdef float[4] clip_pos
    
    # Transform vertex position to clip space
    for i in range(4):
        clip_pos[i] = 0
        for j in range(3):
            clip_pos[i] += proj_matrix[i][j] * world_pos[j]
        clip_pos[i] += proj_matrix[i][3]  # Add the w component

    # Perspective divide to get NDC
    if clip_pos[3] != 0:
        for i in range(3):
            clip_pos[i] /= clip_pos[3]

    # Check if the vertex is within the view frustum
    if not (-1 <= clip_pos[0] <= 1 and -1 <= clip_pos[1] <= 1 and -1 <= clip_pos[2] <= 1):
        return False

    # Check if the vertex normal is facing the camera
    dot_product = 0
    for i in range(3):
        dot_product += world_normal[i] * view_dir[i]

    if dot_product >= 0:  # If not facing camera
        return False

    # Project the 3D point to 2D screen space
    location_3d_to_region_2d(region, rv3d.persmat, world_pos, &region_pos[0])
    
    # Convert to pixel coordinates
    x = <int>region_pos[0]
    y = <int>region_pos[1]
    
    # Check if coordinates are within viewport
    if not (0 <= x < buffer_width and 0 <= y < buffer_height):
        return False  # Outside viewport
    
    # Get the depth at the vertex's screen position
    vertex_depth = depth_buffer[y, x]
    if vertex_depth < 0:
        return False  # Invalid depth value
    
    # Calculate the expected depth for this vertex
    # Transform from world to view space
    copy_v3f_to_v4(world_pos, <float>1.0, co_world)
    mul_v4_m4v4(co_view, rv3d.viewmat, co_world)
    
    # Get the view Z (negative because view space Z points away from the camera)
    view_z = -co_view[2]
    
    # Transform to clip space
    mul_v4_m4v4(co_clip, rv3d.persmat, co_world)
    
    # Get clip space z and w
    clip_z = co_clip[2]
    clip_w = co_clip[3]
    
    # Perform perspective divide to get NDC z
    if clip_w != 0:
        ndc_z = clip_z / clip_w
    else:
        ndc_z = <float>1.0
    
    # Convert NDC z to depth buffer value [0, 1]
    calculated_depth = ndc_z * <float>0.5 + <float>0.5

    # with gil:
    #     print(f"vert: {calculated_depth=}, {vertex_depth=}, = {fabs(calculated_depth - vertex_depth)}")

    # Check if the vertex is occluded (its calculated depth is greater than the stored depth)
    # We add a small tolerance to account for floating-point precision issues
    if calculated_depth > (vertex_depth + depth_tolerance):  # fabs(calculated_depth - vertex_depth) > depth_tolerance:
        return False  # Occluded
    
    return True  # Visible
