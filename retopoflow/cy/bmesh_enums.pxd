# distutils: language=c++
# distutils: extra_compile_args=/std:c++17
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=False

from .bmesh_fast cimport BMHeader

# Define as C constants
cdef enum BMElemHFlag:
    BM_ELEM_SELECT       = (1 << 0)  # 1
    BM_ELEM_HIDDEN       = (1 << 1)  # 2
    BM_ELEM_SEAM         = (1 << 2)  # 4
    BM_ELEM_SMOOTH       = (1 << 3)  # 8
    BM_ELEM_TAG          = (1 << 4)  # 16
    BM_ELEM_DRAW         = (1 << 5)  # 32
    BM_ELEM_TAG_ALT      = (1 << 6)  # 64
    BM_ELEM_INTERNAL_TAG = (1 << 7)  # 128


# Helper functions to check flags
cdef inline bint BM_elem_flag_test(BMHeader* head, BMElemHFlag hflag) noexcept nogil:
    return head.hflag & hflag

cdef inline void BM_elem_flag_set(BMHeader* head, BMElemHFlag hflag) noexcept nogil:
    head.hflag |= hflag

cdef inline void BM_elem_flag_clear(BMHeader* head, BMElemHFlag hflag) noexcept nogil:
    head.hflag &= ~hflag

cdef inline void BM_elem_flag_toggle(BMHeader* head, BMElemHFlag hflag) noexcept nogil:
    head.hflag ^= hflag
