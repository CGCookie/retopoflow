# distutils: language=c++
# cython: language_level=3

from enum import Enum
from libc.stdint cimport uint32_t

from .list_base cimport ListBase


# #BMHeader.htype (char)
class BMHeaderType(Enum):
    HTYPE_VERT = 1
    HTYPE_EDGE = 2
    HTYPE_LOOP = 4
    HTYPE_FACE = 8


# Basic structures needed for BMesh elements
cdef struct BMHeader:
    void* data
    int index
    char htype
    char hflag
    char api_flag
    # char _pad

# Just a wrapper for all elem types to get unified access to BMHeader data
cdef struct BMElem:
    BMHeader head

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
    char elem_index_dirty  # BMHeaderType
    char elem_table_dirty  # BMHeaderType
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
