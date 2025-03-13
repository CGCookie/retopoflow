# distutils: language=c++
# cython: language_level=3


cdef struct bVec3:
    bint x
    bint y
    bint z


cdef float vec3_dot(const float* a, const float* b) noexcept nogil
cdef void vec3_normalize(float* v) noexcept nogil

cdef void copy_v4_to_v3(const float[4] vec4, float[3] vec3) noexcept nogil
cdef void copy_v3f_to_v4(const float[3] vec3, const float w, float[4] vec4) noexcept nogil

cdef void div_v3_f(float[3] vec3, const float value) noexcept nogil
