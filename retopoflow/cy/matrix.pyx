# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=False

from libc.math cimport fabs
from .vector cimport Vector3, Vector4


# Matrix3 operations
cdef void mat3_transpose(float[3][3] m, float[3][3] result) noexcept nogil:
    cdef int i, j
    for i in range(3):
        for j in range(3):
            result[i][j] = m[j][i]

cdef float mat3_determinant(float[3][3] m) noexcept nogil:
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
            m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
            m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

cdef void mat3_invert(float[3][3] m, float[3][3] result) noexcept nogil:
    cdef float det = mat3_determinant(m)
    cdef float inv_det = 1.0 / det

    result[0][0] = (m[1][1] * m[2][2] - m[1][2] * m[2][1]) * inv_det
    result[0][1] = (m[0][2] * m[2][1] - m[0][1] * m[2][2]) * inv_det
    result[0][2] = (m[0][1] * m[1][2] - m[0][2] * m[1][1]) * inv_det
    result[1][0] = (m[1][2] * m[2][0] - m[1][0] * m[2][2]) * inv_det
    result[1][1] = (m[0][0] * m[2][2] - m[0][2] * m[2][0]) * inv_det
    result[1][2] = (m[0][2] * m[1][0] - m[0][0] * m[1][2]) * inv_det
    result[2][0] = (m[1][0] * m[2][1] - m[1][1] * m[2][0]) * inv_det
    result[2][1] = (m[0][1] * m[2][0] - m[0][0] * m[2][1]) * inv_det
    result[2][2] = (m[0][0] * m[1][1] - m[0][1] * m[1][0]) * inv_det

cdef void mat3_invert_safe(float[3][3] m, float[3][3] result) noexcept nogil:
    cdef float det = mat3_determinant(m)
    cdef int i, j
    if fabs(det) < 1e-8:  # Small threshold for singular matrices
        # Return identity matrix if not invertible
        for i in range(3):
            for j in range(3):
                result[i][j] = 1.0 if i == j else 0.0
    else:
        mat3_invert(m, result)

cdef void mat3_multiply(float[3][3] a, float[3][3] b, float[3][3] result) noexcept nogil:
    cdef int i, j, k
    for i in range(3):
        for j in range(3):
            result[i][j] = 0
            for k in range(3):
                result[i][j] += a[i][k] * b[k][j]

cdef void mat3_get_col(float[3][3] m, int col, Vector3* result) noexcept nogil:
    result.x = m[0][col]
    result.y = m[1][col]
    result.z = m[2][col]

# Matrix4 operations
cdef float mat4_determinant(float[4][4] m) noexcept nogil:
    return (m[0][0] * (
        m[1][1] * (m[2][2] * m[3][3] - m[2][3] * m[3][2]) -
        m[1][2] * (m[2][1] * m[3][3] - m[2][3] * m[3][1]) +
        m[1][3] * (m[2][1] * m[3][2] - m[2][2] * m[3][1])
    ) - m[0][1] * (
        m[1][0] * (m[2][2] * m[3][3] - m[2][3] * m[3][2]) -
        m[1][2] * (m[2][0] * m[3][3] - m[2][3] * m[3][0]) +
        m[1][3] * (m[2][0] * m[3][2] - m[2][2] * m[3][0])
    ) + m[0][2] * (
        m[1][0] * (m[2][1] * m[3][3] - m[2][3] * m[3][1]) -
        m[1][1] * (m[2][0] * m[3][3] - m[2][3] * m[3][0]) +
        m[1][3] * (m[2][0] * m[3][1] - m[2][1] * m[3][0])
    ) - m[0][3] * (
        m[1][0] * (m[2][1] * m[3][2] - m[2][2] * m[3][1]) -
        m[1][1] * (m[2][0] * m[3][2] - m[2][2] * m[3][0]) +
        m[1][2] * (m[2][0] * m[3][1] - m[2][1] * m[3][0])
    ))

cdef void mat4_invert(float[4][4] m, float[4][4] result) noexcept nogil:
    cdef float det = mat4_determinant(m)
    cdef float inv_det = 1.0 / det
    
    # First row
    result[0][0] = (
        m[1][1] * (m[2][2] * m[3][3] - m[2][3] * m[3][2]) -
        m[1][2] * (m[2][1] * m[3][3] - m[2][3] * m[3][1]) +
        m[1][3] * (m[2][1] * m[3][2] - m[2][2] * m[3][1])
    ) * inv_det
    
    result[0][1] = -(
        m[0][1] * (m[2][2] * m[3][3] - m[2][3] * m[3][2]) -
        m[0][2] * (m[2][1] * m[3][3] - m[2][3] * m[3][1]) +
        m[0][3] * (m[2][1] * m[3][2] - m[2][2] * m[3][1])
    ) * inv_det
    
    result[0][2] = (
        m[0][1] * (m[1][2] * m[3][3] - m[1][3] * m[3][2]) -
        m[0][2] * (m[1][1] * m[3][3] - m[1][3] * m[3][1]) +
        m[0][3] * (m[1][1] * m[3][2] - m[1][2] * m[3][1])
    ) * inv_det
    
    result[0][3] = -(
        m[0][1] * (m[1][2] * m[2][3] - m[1][3] * m[2][2]) -
        m[0][2] * (m[1][1] * m[2][3] - m[1][3] * m[2][1]) +
        m[0][3] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
    ) * inv_det

    # Second row
    result[1][0] = -(
        m[1][0] * (m[2][2] * m[3][3] - m[2][3] * m[3][2]) -
        m[1][2] * (m[2][0] * m[3][3] - m[2][3] * m[3][0]) +
        m[1][3] * (m[2][0] * m[3][2] - m[2][2] * m[3][0])
    ) * inv_det
    
    result[1][1] = (
        m[0][0] * (m[2][2] * m[3][3] - m[2][3] * m[3][2]) -
        m[0][2] * (m[2][0] * m[3][3] - m[2][3] * m[3][0]) +
        m[0][3] * (m[2][0] * m[3][2] - m[2][2] * m[3][0])
    ) * inv_det
    
    result[1][2] = -(
        m[0][0] * (m[1][2] * m[3][3] - m[1][3] * m[3][2]) -
        m[0][2] * (m[1][0] * m[3][3] - m[1][3] * m[3][0]) +
        m[0][3] * (m[1][0] * m[3][2] - m[1][2] * m[3][0])
    ) * inv_det
    
    result[1][3] = (
        m[0][0] * (m[1][2] * m[2][3] - m[1][3] * m[2][2]) -
        m[0][2] * (m[1][0] * m[2][3] - m[1][3] * m[2][0]) +
        m[0][3] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
    ) * inv_det

    # Third row
    result[2][0] = (
        m[1][0] * (m[2][1] * m[3][3] - m[2][3] * m[3][1]) -
        m[1][1] * (m[2][0] * m[3][3] - m[2][3] * m[3][0]) +
        m[1][3] * (m[2][0] * m[3][1] - m[2][1] * m[3][0])
    ) * inv_det
    
    result[2][1] = -(
        m[0][0] * (m[2][1] * m[3][3] - m[2][3] * m[3][1]) -
        m[0][1] * (m[2][0] * m[3][3] - m[2][3] * m[3][0]) +
        m[0][3] * (m[2][0] * m[3][1] - m[2][1] * m[3][0])
    ) * inv_det
    
    result[2][2] = (
        m[0][0] * (m[1][1] * m[3][3] - m[1][3] * m[3][1]) -
        m[0][1] * (m[1][0] * m[3][3] - m[1][3] * m[3][0]) +
        m[0][3] * (m[1][0] * m[3][1] - m[1][1] * m[3][0])
    ) * inv_det
    
    result[2][3] = -(
        m[0][0] * (m[1][1] * m[2][3] - m[1][3] * m[2][1]) -
        m[0][1] * (m[1][0] * m[2][3] - m[1][3] * m[2][0]) +
        m[0][3] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    ) * inv_det

    # Fourth row
    result[3][0] = -(
        m[1][0] * (m[2][1] * m[3][2] - m[2][2] * m[3][1]) -
        m[1][1] * (m[2][0] * m[3][2] - m[2][2] * m[3][0]) +
        m[1][2] * (m[2][0] * m[3][1] - m[2][1] * m[3][0])
    ) * inv_det
    
    result[3][1] = (
        m[0][0] * (m[2][1] * m[3][2] - m[2][2] * m[3][1]) -
        m[0][1] * (m[2][0] * m[3][2] - m[2][2] * m[3][0]) +
        m[0][2] * (m[2][0] * m[3][1] - m[2][1] * m[3][0])
    ) * inv_det
    
    result[3][2] = -(
        m[0][0] * (m[1][1] * m[3][2] - m[1][2] * m[3][1]) -
        m[0][1] * (m[1][0] * m[3][2] - m[1][2] * m[3][0]) +
        m[0][2] * (m[1][0] * m[3][1] - m[1][1] * m[3][0])
    ) * inv_det
    
    result[3][3] = (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
        m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
        m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    ) * inv_det

cdef void mat4_invert_safe(float[4][4] m, float[4][4] result) noexcept nogil:
    cdef float det = mat4_determinant(m)
    cdef int i, j
    if fabs(det) < 1e-8:
        for i in range(4):
            for j in range(4):
                result[i][j] = 1.0 if i == j else 0.0
    else:
        mat4_invert(m, result)

cdef void mat4_to_3x3(float[4][4] m, float[3][3] result) noexcept nogil:
    cdef int i, j
    for i in range(3):
        for j in range(3):
            result[i][j] = m[i][j]

cdef void mat4_get_col3(float[4][4] m, int col, float* result) noexcept nogil:
    result[0] = m[0][col]
    result[1] = m[1][col]
    result[2] = m[2][col]

cdef void mat4_get_col4(float[4][4] m, int col, float* result) noexcept nogil:
    result[0] = m[0][col]
    result[1] = m[1][col]
    result[2] = m[2][col]
    result[3] = m[3][col]

cdef void mat4_transpose(float[4][4] m, float[4][4] result) noexcept nogil:
    cdef int i, j
    for i in range(4):
        for j in range(4):
            result[i][j] = m[j][i]

cdef void mat4_multiply(float[4][4] a, float[4][4] b, float[4][4] result) noexcept nogil:
    cdef int i, j, k
    for i in range(4):
        for j in range(4):
            result[i][j] = 0
            for k in range(4):
                result[i][j] += a[i][k] * b[k][j]

cdef void mat4_get_translation(float[4][4] m, float* result) noexcept nogil:
    result[0] = m[0][3]
    result[1] = m[1][3]
    result[2] = m[2][3]


################################################################
################################################################
################################################################

cdef void mul_m4_v3(const float[4][4] M, float[3] r) noexcept nogil:
    cdef:
        float x = r[0];
        float y = r[1];

    r[0] = x * M[0][0] + y * M[1][0] + M[2][0] * r[2] + M[3][0]
    r[1] = x * M[0][1] + y * M[1][1] + M[2][1] * r[2] + M[3][1]
    r[2] = x * M[0][2] + y * M[1][2] + M[2][2] * r[2] + M[3][2]

cdef void mul_v3_m4v3(float[3] r, const float[4][4] mat, const float[3] vec) noexcept nogil:
    cdef:
        float x = vec[0]
        float y = vec[1]

    r[0] = x * mat[0][0] + y * mat[1][0] + mat[2][0] * vec[2] + mat[3][0]
    r[1] = x * mat[0][1] + y * mat[1][1] + mat[2][1] * vec[2] + mat[3][1]
    r[2] = x * mat[0][2] + y * mat[1][2] + mat[2][2] * vec[2] + mat[3][2]
