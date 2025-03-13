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

from libc.stdlib cimport malloc, free
from libc.string cimport memset
from libc.math cimport sqrt, fabs
from cython.parallel cimport parallel, prange
from libcpp.vector cimport vector
from libcpp.set cimport set as cpp_set
from libc.stdint cimport uintptr_t

from .bl_types.bmesh_types cimport BMVert, BMEdge, BMFace, BMesh, BMHeader, BMLoop
from .bl_types.bmesh_py_wrappers cimport BPy_BMesh, BPy_BMVert, BPy_BMEdge, BPy_BMFace
from .bl_types.bmesh_flags cimport BMElemHFlag, BM_elem_flag_test


cdef class MeshRenderAccel:

    def __init__(self, py_bmesh, mirror_x=False, mirror_y=False, mirror_z=False, layer_pin=None):
        self.py_bmesh = py_bmesh
        self.bmesh_pywrapper = <BPy_BMesh*><uintptr_t>id(py_bmesh)
        self.bmesh = self.bmesh_pywrapper.bm
        self.mirror_x = mirror_x
        self.mirror_y = mirror_y
        self.mirror_z = mirror_z
        self.layer_pin = layer_pin

    cdef float seam_elem(self, BMHeader* head) noexcept nogil:
        return <float>1.0 if BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_SEAM) else <float>0.0

    cdef bint hidden_elem(self, BMHeader* head) noexcept nogil:
        return BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_HIDDEN)
    
    cdef float sel_elem(self, BMHeader* head) noexcept nogil:
        return <float>1.0 if BM_elem_flag_test(head, BMElemHFlag.BM_ELEM_SELECT) else <float>0.0
    
    cdef float warn_vert(self, BMVert* vert) noexcept nogil:
        if self.mirror_x and vert.co[0] <= 0.0001: return <float>0.0
        if self.mirror_y and vert.co[1] >= -0.0001: return <float>0.0
        if self.mirror_z and vert.co[2] <= 0.0001: return <float>0.0
        
        # Check if manifold and boundary - this is simplified
        # In the future, we could add more detailed checks
        return <float>0.0  # Simplified for now
    
    cdef float warn_edge(self, BMEdge* edge) noexcept nogil:
        cdef:
            BMVert* v0 = <BMVert*>edge.v1
            BMVert* v1 = <BMVert*>edge.v2
            
        if self.mirror_x and v0.co[0] <= 0.0001 and v1.co[0] <= 0.0001: return <float>0.0
        if self.mirror_y and v0.co[1] >= -0.0001 and v1.co[1] >= -0.0001: return <float>0.0
        if self.mirror_z and v0.co[2] <= 0.0001 and v1.co[2] <= 0.0001: return <float>0.0
        
        return <float>0.0  # Simplified for now
    
    cdef float warn_face(self, BMFace* face) noexcept nogil:
        return <float>1.0  # Simplified for now
    
    cdef float pin_vert(self, BMVert* vert) noexcept nogil:
        # This requires Python interaction, so we'll handle it in Python
        return <float>0.0
    
    cdef float pin_edge(self, BMEdge* edge) noexcept nogil:
        # This requires Python interaction, so we'll handle it in Python
        return <float>0.0
    
    cdef float pin_face(self, BMFace* face) noexcept nogil:
        # This requires Python interaction, so we'll handle it in Python
        return <float>0.0
    
    cdef float seam_vert(self, BMVert* vert) noexcept nogil:
        # This requires Python interaction, so we'll handle it in Python
        return <float>0.0
    
    cdef float seam_edge(self, BMEdge* edge) noexcept nogil:
        return <float>1.0 if BM_elem_flag_test(&edge.head, BMElemHFlag.BM_ELEM_SEAM) else <float>0.0
    
    cdef float seam_face(self, BMFace* face) noexcept nogil:
        return <float>0.0

    cpdef dict gather_vert_data(self):
        """Gather BMesh vert data"""
        if self.bmesh == NULL or self.bmesh.vtable == NULL:
            print("[CYTHON] Error: gather_face_edge() - bmesh or etable is NULL\n")
            return {
                'vco': np.zeros((0, 3), dtype=np.float32),
                'vno': np.zeros((0, 3), dtype=np.float32),
                'sel': np.zeros(0, dtype=np.float32),
                'warn': np.zeros(0, dtype=np.float32),
                'pin': np.zeros(0, dtype=np.float32),
                'seam': np.zeros(0, dtype=np.float32),
                'indices': np.zeros(0, dtype=np.int32),
                'count': 0
            }

        cdef:
            BMVert* vert
            int i, j
            BMVert** vtable = self.bmesh.vtable
            object py_verts = self.py_bmesh.verts
            object py_vert
            int totvalidverts = 0
            int valid_idx
            np.ndarray[np.float32_t, ndim=2] vco
            np.ndarray[np.float32_t, ndim=2] vno
            np.ndarray[np.float32_t, ndim=1] sel
            np.ndarray[np.float32_t, ndim=1] warn
            np.ndarray[np.float32_t, ndim=1] pin
            np.ndarray[np.float32_t, ndim=1] seam
            np.ndarray[np.int32_t, ndim=1] indices
            np.ndarray[np.int32_t, ndim=1] valid_indices

        # First, create an array to mark valid vertices with their index
        valid_indices = np.full(self.bmesh.totvert, -1, dtype=np.int32)

        try:
            # First pass: count valid vertices and assign indices
            for i in range(self.bmesh.totvert):
                if vtable[i] == NULL:
                    # INVALID!
                    continue
                if BM_elem_flag_test(&vtable[i].head, BMElemHFlag.BM_ELEM_HIDDEN):
                    # HIDDEN!
                    continue
                valid_indices[i] = totvalidverts
                totvalidverts += 1
        except Exception as e:
            import traceback
            print(f"Error in gather_vert_data: {str(e)}")
            print(traceback.format_exc())

        # Allocate NumPy arrays with the exact size needed
        vco = np.zeros((totvalidverts, 3), dtype=np.float32)
        vno = np.zeros((totvalidverts, 3), dtype=np.float32)
        sel = np.zeros(totvalidverts, dtype=np.float32)
        warn = np.zeros(totvalidverts, dtype=np.float32)
        pin = np.zeros(totvalidverts, dtype=np.float32)
        seam = np.zeros(totvalidverts, dtype=np.float32)
        indices = np.zeros(totvalidverts, dtype=np.int32)

        # Second pass
        for i in prange(self.bmesh.totvert, nogil=True):
            if valid_indices[i] == -1:
                continue
                
            vert = vtable[i]
            valid_idx = valid_indices[i]
            
            # Store vertex index for later reference
            indices[valid_idx] = i

            # Fill coordinate and normal data
            for j in range(3):
                vco[valid_idx, j] = vert.co[j]
                vno[valid_idx, j] = vert.no[j]

            # Fill selection state
            sel[valid_idx] = self.sel_elem(&vert.head)
            
            # Fill warning state
            warn[valid_idx] = self.warn_vert(vert)
            
            # Fill seam state
            seam[valid_idx] = self.seam_elem(&vert.head)  # TODO: self.seam_vert(vert)

        # Handle pin state which requires Python interaction
        if self.layer_pin:
            for i in range(totvalidverts):
                bmv = py_verts[indices[i]]
                pin[i] = <float>1.0 if bmv[self.layer_pin] else <float>0.0

        # Return as a dictionary of NumPy arrays
        return {
            'vco': vco,
            'vno': vno,
            'sel': sel,
            'warn': warn,
            'pin': pin,
            'seam': seam,
            'indices': indices,
            'count': totvalidverts
        }

    cpdef dict gather_edge_data(self):
        """Gather BMesh edge data"""
        if self.bmesh == NULL or self.bmesh.etable == NULL:
            print("[CYTHON] Error: gather_face_edge() - bmesh or etable is NULL\n")
            return {
                'vco': np.zeros((0, 3), dtype=np.float32),
                'vno': np.zeros((0, 3), dtype=np.float32),
                'sel': np.zeros(0, dtype=np.float32),
                'warn': np.zeros(0, dtype=np.float32),
                'pin': np.zeros(0, dtype=np.float32),
                'seam': np.zeros(0, dtype=np.float32),
                'indices': np.zeros(0, dtype=np.int32),
                'count': 0
            }

        cdef:
            BMEdge* edge
            BMVert* v0
            BMVert* v1
            int i, j, k
            float sel_val, warn_val, seam_val, pin_val
            BMEdge** etable = self.bmesh.etable
            object py_edges = self.py_bmesh.edges
            int totvalidedges = 0
            int valid_idx
            np.ndarray[np.float32_t, ndim=2] vco
            np.ndarray[np.float32_t, ndim=2] vno
            np.ndarray[np.float32_t, ndim=1] sel
            np.ndarray[np.float32_t, ndim=1] warn
            np.ndarray[np.float32_t, ndim=1] pin
            np.ndarray[np.float32_t, ndim=1] seam
            np.ndarray[np.int32_t, ndim=1] indices
            np.ndarray[np.int32_t, ndim=1] valid_indices
        
        # First, create an array to mark valid edges with their index.
        valid_indices = np.full(self.bmesh.totedge, -1, dtype=np.int32)

        # First pass: count valid edges and assign indices.
        for i in range(self.bmesh.totedge):
            if etable[i] == NULL:
                # INVALID!
                continue
            if self.hidden_elem(&etable[i].head):
                # HIDDEN!
                continue
            valid_indices[i] = totvalidedges
            totvalidedges += 1

        # Each edge has 2 vertices, so we need 2 * totvalidedges entries,
        # Allocate NumPy arrays with the exact size needed.
        vco = np.zeros((totvalidedges * 2, 3), dtype=np.float32)
        vno = np.zeros((totvalidedges * 2, 3), dtype=np.float32)
        sel = np.zeros(totvalidedges * 2, dtype=np.float32)
        warn = np.zeros(totvalidedges * 2, dtype=np.float32)
        pin = np.zeros(totvalidedges * 2, dtype=np.float32)
        seam = np.zeros(totvalidedges * 2, dtype=np.float32)
        indices = np.zeros(totvalidedges, dtype=np.int32)

        # Second pass: fill arrays.
        for i in prange(self.bmesh.totedge, nogil=True):
            if valid_indices[i] == -1:
                continue
                
            edge = etable[i]
            valid_idx = valid_indices[i]
            
            # Store edge index for later reference.
            indices[valid_idx] = i
            
            # Get vertices
            v0 = <BMVert*>edge.v1
            v1 = <BMVert*>edge.v2
            
            # Calculate array indices for the two vertices.
            k = valid_idx * 2
            
            # Fill coordinate and normal data for first vertex.
            for j in range(3):
                vco[k, j] = v0.co[j]
                vno[k, j] = v0.no[j]
            
            # Fill coordinate and normal data for second vertex.
            for j in range(3):
                vco[k+1, j] = v1.co[j]
                vno[k+1, j] = v1.no[j]
            
            # Fill selection state (same for both vertices).
            sel_val = self.sel_elem(&edge.head)
            sel[k] = sel_val
            sel[k+1] = sel_val
            
            # Fill warning state (same for both vertices).
            warn_val = self.warn_edge(edge)
            warn[k] = warn_val
            warn[k+1] = warn_val
            
            # Fill seam state (same for both vertices).
            seam_val = self.seam_edge(edge)
            seam[k] = seam_val
            seam[k+1] = seam_val

        # Handle pin state which requires Python interaction.
        if self.layer_pin:
            for i in range(totvalidedges):
                bme = py_edges[indices[i]]
                # Avoid closure by manually checking each vertex.
                pin_val = 1.0
                for v in bme.verts:
                    if not v[self.layer_pin]:
                        pin_val = 0.0
                        break
                k = i * 2
                pin[k] = pin_val
                pin[k+1] = pin_val

        # Return as a dictionary of NumPy arrays.
        return {
            'vco': vco,
            'vno': vno,
            'sel': sel,
            'warn': warn,
            'pin': pin,
            'seam': seam,
            'indices': indices,
            'count': totvalidedges
        }

    cpdef dict gather_face_data(self):
        """Gather BMesh face data"""
        if self.bmesh == NULL or self.bmesh.ftable == NULL:
            print("[CYTHON] Error: gather_face_data() - bmesh or ftable is NULL\n")
            return {
                'vco': np.zeros((0, 3), dtype=np.float32),
                'vno': np.zeros((0, 3), dtype=np.float32),
                'sel': np.zeros(0, dtype=np.float32),
                'warn': np.zeros(0, dtype=np.float32),
                'pin': np.zeros(0, dtype=np.float32),
                'seam': np.zeros(0, dtype=np.float32),
                'indices': np.zeros(0, dtype=np.int32),
                'count': 0,
                'tri_count': 0
            }

        cdef:
            BMFace* face
            BMLoop* loop
            BMLoop* l_first
            BMLoop* l_iter
            BMVert* v_first
            BMVert* v_prev
            BMVert* v_curr
            int i, j, k, v_idx, tri_idx = 0, tri_base = 0
            int valid_idx = 0
            int face_idx
            BMFace** ftable = self.bmesh.ftable
            object py_faces = self.py_bmesh.faces
            int totvalidfaces = 0
            int total_triangles = 0
            float sel_val, warn_val, seam_val
            float[3] first_co
            float[3] first_no
            float[3] prev_co
            float[3] prev_no
            np.ndarray[np.float32_t, ndim=2] vco
            np.ndarray[np.float32_t, ndim=2] vno
            np.ndarray[np.float32_t, ndim=1] sel
            np.ndarray[np.float32_t, ndim=1] warn
            np.ndarray[np.float32_t, ndim=1] pin
            np.ndarray[np.float32_t, ndim=1] seam
            np.ndarray[np.int32_t, ndim=1] indices
            np.ndarray[np.int32_t, ndim=1] valid_indices
            np.ndarray[np.int32_t, ndim=1] tri_counts
            np.ndarray[np.int32_t, ndim=1] tri_offsets
        
        # Combined first pass: count valid faces, triangles, and set up indices.
        valid_indices = np.full(self.bmesh.totface, -1, dtype=np.int32)
        
        # First pass: count and setup indices.
        for i in range(self.bmesh.totface):
            if ftable[i] == NULL:
                continue
            if self.hidden_elem(&ftable[i].head):
                continue
                
            face = ftable[i]
            valid_indices[i] = totvalidfaces
            
            # Each face with n vertices needs (n-2) triangles.
            total_triangles += face.len - 2
            totvalidfaces += 1
        
        # Allocate all arrays at once.
        indices = np.zeros(totvalidfaces, dtype=np.int32)
        tri_counts = np.zeros(totvalidfaces, dtype=np.int32)
        tri_offsets = np.zeros(totvalidfaces, dtype=np.int32)
        vco = np.zeros((total_triangles * 3, 3), dtype=np.float32)
        vno = np.zeros((total_triangles * 3, 3), dtype=np.float32)
        sel = np.zeros(total_triangles * 3, dtype=np.float32)
        warn = np.zeros(total_triangles * 3, dtype=np.float32)
        pin = np.zeros(total_triangles * 3, dtype=np.float32)
        seam = np.zeros(total_triangles * 3, dtype=np.float32)
        
        # Combined second pass: setup triangle counts and offsets.
        valid_idx = 0
        tri_idx = 0
        
        for i in range(self.bmesh.totface):
            if valid_indices[i] == -1:
                continue
                
            face = ftable[i]
            indices[valid_idx] = i
            
            # Store triangle count for this face.
            tri_count = face.len - 2
            tri_counts[valid_idx] = tri_count
            
            # Store triangle offset for this face.
            tri_offsets[valid_idx] = tri_idx
            tri_idx += tri_count
            valid_idx += 1
        
        # Third pass: fill arrays with triangulated face data in parallel.
        for i in prange(totvalidfaces, nogil=True):
            face_idx = indices[i]
            face = ftable[face_idx]
            
            # Get face properties.
            sel_val = self.sel_elem(&face.head)
            warn_val = self.warn_face(face)
            seam_val = self.seam_face(face)
            
            # Simple fan triangulation
            l_first = <BMLoop*>face.l_first
            v_first = <BMVert*>l_first.v
            
            # Store first vertex data.
            for j in range(3):
                first_co[j] = v_first.co[j]
                first_no[j] = v_first.no[j]
            
            # Move to second vertex.
            l_iter = <BMLoop*>l_first.next
            v_prev = <BMVert*>l_iter.v
            
            # Store second vertex data.
            for j in range(3):
                prev_co[j] = v_prev.co[j]
                prev_no[j] = v_prev.no[j]
            
            # Iterate through remaining vertices to create triangles.
            l_iter = <BMLoop*>l_iter.next
            
            # Get base triangle index for this face.
            tri_base = tri_offsets[i]
            
            for j in range(face.len - 2):
                v_curr = <BMVert*>l_iter.v
                
                # Calculate array index for this triangle.
                k = (tri_base + j) * 3
                
                # First vertex of triangle (pivot).
                for v_idx in range(3):
                    vco[k, v_idx] = first_co[v_idx]
                    vno[k, v_idx] = first_no[v_idx]
                
                # Second vertex of triangle.
                for v_idx in range(3):
                    vco[k+1, v_idx] = prev_co[v_idx]
                    vno[k+1, v_idx] = prev_no[v_idx]
                
                # Third vertex of triangle.
                for v_idx in range(3):
                    vco[k+2, v_idx] = v_curr.co[v_idx]
                    vno[k+2, v_idx] = v_curr.no[v_idx]
                
                # Fill properties for all three vertices.
                for v_idx in range(3):
                    sel[k+v_idx] = sel_val
                    warn[k+v_idx] = warn_val
                    seam[k+v_idx] = seam_val
                
                # Update previous vertex for next triangle.
                for v_idx in range(3):
                    prev_co[v_idx] = v_curr.co[v_idx]
                    prev_no[v_idx] = v_curr.no[v_idx]
                
                # Move to next vertex.
                l_iter = <BMLoop*>l_iter.next
        
        # Handle pin state separately (requires Python interaction)
        if self.layer_pin is not None:
            for i in range(totvalidfaces):
                face_idx = indices[i]
                bmf = py_faces[face_idx]
                
                # Check if all vertices are pinned.
                pin_val = 1.0
                for v in bmf.verts:
                    if not v[self.layer_pin]:
                        pin_val = 0.0
                        break
                
                # Apply pin value to all vertices of all triangles for this face.
                tri_idx = tri_offsets[i]
                for j in range(tri_counts[i]):
                    k = (tri_idx + j) * 3
                    pin[k] = pin_val
                    pin[k+1] = pin_val
                    pin[k+2] = pin_val
        
        # Return as a dictionary of NumPy arrays.
        return {
            'vco': vco,
            'vno': vno,
            'sel': sel,
            'warn': warn,
            'pin': pin,
            'seam': seam,
            'indices': indices,
            'count': totvalidfaces,
            'tri_count': total_triangles
        }
