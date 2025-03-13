# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=False

from libc.math cimport sqrt


cdef float vec3_dot(const float* a, const float* b) noexcept nogil:
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

cdef void vec3_normalize(float* v) noexcept nogil:
    cdef float length = sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if length > <float>0.0:
        v[0] /= length
        v[1] /= length
        v[2] /= length


cdef void copy_v4_to_v3(const float[4] vec4, float[3] vec3) noexcept nogil:
    vec3[0] = vec4[0]
    vec3[1] = vec4[1]
    vec3[2] = vec4[2]

cdef void copy_v3f_to_v4(const float[3] vec3, const float w, float[4] vec4) noexcept nogil:
    vec4[0] = vec3[0]
    vec4[1] = vec3[1]
    vec4[2] = vec3[2]
    vec4[3] = w

cdef void div_v3_f(float[3] vec3, const float value) noexcept nogil:
    vec3[0] = vec3[0] / value
    vec3[1] = vec3[1] / value
    vec3[2] = vec3[2] / value
