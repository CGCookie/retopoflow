# distutils: language=c++
# cython: language_level=3


from .bmesh_types cimport BMHeader


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
    return <bint>((head.hflag & <char>hflag) != 0)

cdef inline void BM_elem_flag_set(BMHeader* head, BMElemHFlag hflag) noexcept nogil:
    head.hflag |= <char>hflag

cdef inline void BM_elem_flag_clear(BMHeader* head, BMElemHFlag hflag) noexcept nogil:
    head.hflag &= ~<char>hflag

cdef inline void BM_elem_flag_toggle(BMHeader* head, BMElemHFlag hflag) noexcept nogil:
    head.hflag ^= <char>hflag
