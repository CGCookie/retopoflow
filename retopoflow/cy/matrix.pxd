# distutils: language=c++
# cython: language_level=3

from .vector cimport Vector3, Vector4

# Matrix3 operations
cdef void mat3_transpose(float[3][3] m, float[3][3] result) noexcept nogil
cdef void mat3_invert(float[3][3] m, float[3][3] result) noexcept nogil
cdef void mat3_invert_safe(float[3][3] m, float[3][3] result) noexcept nogil
cdef float mat3_determinant(float[3][3] m) noexcept nogil
cdef void mat3_multiply(float[3][3] a, float[3][3] b, float[3][3] result) noexcept nogil
cdef void mat3_get_col(float[3][3] m, int col, Vector3* result) noexcept nogil

# Matrix4 operations
cdef void mat4_transpose(float[4][4] m, float[4][4] result) noexcept nogil
cdef void mat4_invert(float[4][4] m, float[4][4] result) noexcept nogil
cdef void mat4_invert_safe(float[4][4] m, float[4][4] result) noexcept nogil
cdef void mat4_to_3x3(float[4][4] m, float[3][3] result) noexcept nogil
cdef float mat4_determinant(float[4][4] m) noexcept nogil
cdef void mat4_multiply(float[4][4] a, float[4][4] b, float[4][4] result) noexcept nogil
cdef void mat4_get_translation(float[4][4] m, float* result) noexcept nogil
cdef void mat4_get_col3(float[4][4] m, int col, float* result) noexcept nogil
cdef void mat4_get_col4(float[4][4] m, int col, float* result) noexcept nogil
