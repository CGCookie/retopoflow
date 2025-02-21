# distutils: language=c++
# cython: language_level=3

cdef float vec3_dot(const float* a, const float* b) noexcept nogil
cdef void vec3_normalize(float* v) noexcept nogil
