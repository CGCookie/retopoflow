# distutils: language=c++

from libc.stdint cimport uint8_t, uint32_t, uintptr_t



# Python object header structure
cdef struct ListBase:
    void* first
    void* last

cdef struct PyObject_VAR_HEAD:
    size_t ob_refcnt
    void* ob_type
    size_t ob_size

# Basic structures needed for BMesh elements
cdef struct BMHeader:
    void* data
    int index
    char htype
    char hflag
    char api_flag
    char _pad

# Disk link structure used by edges
cdef struct BMDiskLink:
    void* next  # BMEdge*
    void* prev  # BMEdge*

# Core BMesh element structures
cdef struct BMVert:
    BMHeader head
    float[3] co
    float[3] no
    void* e    # BMEdge*

cdef struct BMEdge:
    BMHeader head
    void* v1   # BMVert*
    void* v2   # BMVert*
    void* l    # BMLoop*
    BMDiskLink v1_disk_link
    BMDiskLink v2_disk_link

cdef struct BMLoop:
    BMHeader head
    void* v    # BMVert*
    void* e    # BMEdge*
    void* f    # BMFace*
    void* radial_next  # BMLoop*
    void* radial_prev  # BMLoop*
    void* next  # BMLoop*
    void* prev  # BMLoop*

cdef struct BMFace:
    BMHeader head
    void* l_first  # BMLoop*
    int len  # number of vertices in the face
    float[3] no
    short mat_nr
    # short _pad[3]  # Commented out as it's commented in original

# Main BMesh structure
cdef struct BMesh:
    int totvert, totedge, totloop, totface
    int totvertsel, totedgesel, totfacesel
    char elem_index_dirty
    char elem_table_dirty
    void* vpool  # BLI_mempool*
    void* epool  # BLI_mempool*
    void* lpool  # BLI_mempool*
    void* fpool  # BLI_mempool*
    BMVert** vtable  # BMVert**
    BMEdge** etable  # BMEdge**
    BMFace** ftable  # BMFace**
    int vtable_tot
    int etable_tot
    int ftable_tot
    void* vtoolflagpool  # BLI_mempool*
    void* etoolflagpool  # BLI_mempool*
    void* ftoolflagpool  # BLI_mempool*
    uint32_t use_toolflags  # uint
    int toolflag_index
    void* lnor_spacearr  # MLoopNorSpaceArray*
    char spacearr_dirty
    short selectmode
    int shapenr
    int totflags
    ListBase selected
    void* act_face  # BMFace*
    ListBase errorstack
    void* py_handle  # Python object reference

# Python wrapper structures
cdef struct BPy_BMGeneric:
    PyObject_VAR_HEAD py_object
    BMesh* bm

cdef struct BPy_BMElem:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* ele  # BMElem*

cdef struct BPy_BMesh:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    int flag

cdef struct BPy_BMVert:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* v  # BMVert*

cdef struct BPy_BMEdge:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* e  # BMEdge*

cdef struct BPy_BMFace:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* f  # BMFace*

cdef struct BPy_BMLoop:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* l  # BMLoop*

cdef struct BPy_BMElemSeq:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    BPy_BMElem* py_ele
    short itype

cdef struct BPy_BMIter:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* iter  # BMIter
