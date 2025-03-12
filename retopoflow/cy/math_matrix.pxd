# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=False
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=True


cdef void mul_v4_m4v4(float[4] r, const float[4][4] mat, const float[4] v) noexcept nogil
cdef void mul_m4_v4(const float[4][4] mat, float[4] r) noexcept nogil

cdef void transpose_matrix_4x4(const float[4][4] mat, float[4][4] result) noexcept nogil
