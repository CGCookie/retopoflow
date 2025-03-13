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
    
    '''
    cdef vector[TriFace] triangulate_face(self, BMFace* face) nogil:
        cdef:
            vector[TriFace] tri_faces
            TriFace tri
            BMLoop* l_first = <BMLoop*>face.l_first
            BMLoop* l_iter = l_first
            BMLoop* l_prev
            BMVert* v_first
            BMVert* v_prev
            BMVert* v_curr
            int i = 0
            
        # Simple fan triangulation for convex faces
        # For complex faces, we'd need a more robust algorithm
        v_first = <BMVert*>l_first.v
        l_iter = <BMLoop*>l_first.next
        v_prev = v_first
        
        while l_iter != l_first and i < face.len - 2:
            v_curr = <BMVert*>l_iter.v
            
            tri.face = face
            tri.verts[0] = v_first
            tri.verts[1] = v_prev
            tri.verts[2] = v_curr
            
            tri_faces.push_back(tri)
            
            v_prev = v_curr
            l_iter = <BMLoop*>l_iter.next
            i += 1
            
        return tri_faces'''

    cpdef dict gather_vert_data(self):
        """Gather vertex data in Cython for better performance"""
        if self.bmesh == NULL or self.bmesh.vtable == NULL:
            print("[CYTHON] Error: Accel2D._compute_geometry_visibility_in_region() - bmesh or vtable is NULL\n")
            return {}

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
        
        print(">>>>> 1")
        
        # First, create an array to mark valid vertices with their index
        valid_indices = np.full(self.bmesh.totvert, -1, dtype=np.int32)

        print(">>>>> 2")

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

        print(">>>>> 3")

        # Allocate NumPy arrays with the exact size needed
        vco = np.zeros((totvalidverts, 3), dtype=np.float32)
        vno = np.zeros((totvalidverts, 3), dtype=np.float32)
        sel = np.zeros(totvalidverts, dtype=np.float32)
        warn = np.zeros(totvalidverts, dtype=np.float32)
        pin = np.zeros(totvalidverts, dtype=np.float32)
        seam = np.zeros(totvalidverts, dtype=np.float32)
        indices = np.zeros(totvalidverts, dtype=np.int32)

        print(">>>>> 4")

        # Second pass
        with nogil, parallel():
            for i in prange(self.bmesh.totvert):
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

        print(">>>>> 5")

        # Handle pin state which requires Python interaction
        if self.layer_pin:
            for i in range(totvalidverts):
                bmv = py_verts[indices[i]]
                pin[i] = 1.0 if bmv[self.layer_pin] else 0.0

        print(">>>>> 6")

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

    '''cpdef gather_edge_data(self, edges):
        """Gather edge data in Cython for better performance"""
        cdef:
            vector[EdgeData] edge_data_vec
            EdgeData ed
            BMEdge* edge
            BMVert* v0
            BMVert* v1
            int i, j
            
        for bme in edges:
            if not bme.is_valid or bme.hide:
                continue
                
            edge = <BMEdge*><uintptr_t>bme.as_pointer()
            v0 = <BMVert*>edge.v1
            v1 = <BMVert*>edge.v2
            
            # Fill edge data
            for i in range(3):
                ed.co[0][i] = v0.co[i]
                ed.co[1][i] = v1.co[i]
                ed.normal[0][i] = v0.no[i]
                ed.normal[1][i] = v1.no[i]
            
            ed.sel = self.sel_elem(&edge.head)
            ed.warn = self.warn_edge(edge)
            
            # These need Python interaction
            ed.pin = 1.0 if all(v[self.layer_pin] for v in bme.verts) and self.layer_pin else 0.0
            ed.seam = self.seam_edge(edge)
            
            edge_data_vec.push_back(ed)
        
        # Convert to Python data structure
        result = {
            'vco': [],
            'vno': [],
            'sel': [],
            'warn': [],
            'pin': [],
            'seam': []
        }
        
        for i in range(edge_data_vec.size()):
            ed = edge_data_vec[i]
            result['vco'].extend([(ed.co[0][0], ed.co[0][1], ed.co[0][2]), 
                                 (ed.co[1][0], ed.co[1][1], ed.co[1][2])])
            result['vno'].extend([(ed.normal[0][0], ed.normal[0][1], ed.normal[0][2]), 
                                 (ed.normal[1][0], ed.normal[1][1], ed.normal[1][2])])
            result['sel'].extend([ed.sel, ed.sel])
            result['warn'].extend([ed.warn, ed.warn])
            result['pin'].extend([ed.pin, ed.pin])
            result['seam'].extend([ed.seam, ed.seam])
        
        return result
    
    cpdef gather_face_data(self, faces):
        """Gather face data in Cython for better performance"""
        cdef:
            vector[TriFace] tri_faces_vec
            vector[TriFace] all_tri_faces
            TriFace tri
            BMFace* face
            int i, j, k
            
        # First, triangulate all faces
        for bmf in faces:
            if not bmf.is_valid or bmf.hide:
                continue
                
            face = <BMFace*><uintptr_t>bmf.as_pointer()
            tri_faces_vec = self.triangulate_face(face)
            
            for i in range(tri_faces_vec.size()):
                all_tri_faces.push_back(tri_faces_vec[i])
        
        # Convert to Python data structure
        result = {
            'vco': [],
            'vno': [],
            'sel': [],
            'warn': [],
            'pin': [],
            'seam': [],
            'tri_faces': []
        }
        
        for i in range(all_tri_faces.size()):
            tri = all_tri_faces[i]
            face = tri.face
            
            face_sel = self.sel_elem(&face.head)
            face_warn = self.warn_face(face)
            
            # These need Python interaction
            bmf = <object>face.head.data
            face_pin = 1.0 if all(v[self.layer_pin] for v in bmf.verts) and self.layer_pin else 0.0
            face_seam = self.seam_face(face)
            
            # Add triangle vertices
            for j in range(3):
                vert = tri.verts[j]
                result['vco'].append((vert.co[0], vert.co[1], vert.co[2]))
                result['vno'].append((vert.no[0], vert.no[1], vert.no[2]))
                result['sel'].append(face_sel)
                result['warn'].append(face_warn)
                result['pin'].append(face_pin)
                result['seam'].append(face_seam)
            
            # Store the original face for reference
            result['tri_faces'].append(bmf)
        
        return result'''
