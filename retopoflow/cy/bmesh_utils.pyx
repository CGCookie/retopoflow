# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=False

import cython
from cython.parallel import prange, parallel
from libc.stdint cimport uintptr_t
from libc.stdlib cimport malloc, free
# from cpython.ref cimport PyObject

from .bmesh_fast cimport BMVert, BMEdge, BMLoop, BMFace, BMesh, BPy_BMesh


@cython.boundscheck(False)
@cython.wraparound(False)
cdef int* find_selected_indices(BMVert** vtable, int vtable_tot, int* num_selected) nogil:
    """Fast C-level function to get indices of selected vertices"""
    cdef:
        int* selected = <int*>malloc(vtable_tot * sizeof(int))
        char* is_selected = <char*>malloc(vtable_tot * sizeof(char))
        int i, count = 0
    
    if selected == NULL or is_selected == NULL:
        if selected: free(selected)
        if is_selected: free(is_selected)
        num_selected[0] = 0
        return NULL
        
    # First pass: parallel check for selected vertices
    with parallel():
        for i in prange(vtable_tot, schedule='static'):
            if vtable[i] != NULL and vtable[i].head.hflag & 0x1:
                is_selected[i] = 1
            else:
                is_selected[i] = 0
    
    # Second pass: collect indices (must be sequential for correct order)
    for i in range(vtable_tot):
        if is_selected[i]:
            selected[count] = i
            count += 1
            
    free(is_selected)
    num_selected[0] = count
    return selected

def get_selected_verts(object bm_py):
    cdef:
        int i, num_selected = 0
        int* selected_indices
        BMesh* bmesh
        list result = []

    # Get BMesh pointer directly
    bmesh = (<BPy_BMesh*><uintptr_t>id(bm_py)).bm
    if not bmesh or not bmesh.vtable:
        return result

    # Get selected indices without GIL
    with nogil:
        selected_indices = find_selected_indices(bmesh.vtable, bmesh.vtable_tot, &num_selected)
        
    if selected_indices == NULL:
        return result
        
    # Create Python list from indices
    try:
        for i in range(num_selected):
            result.append(bm_py.verts[selected_indices[i]])
    finally:
        free(selected_indices)
        
    return result
