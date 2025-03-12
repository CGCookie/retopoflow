# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=False
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=True


cdef void mul_v4_m4v4(float[4] r, const float[4][4] mat, const float[4] v) noexcept nogil:
    cdef float x = v[0]
    cdef float y = v[1]
    cdef float z = v[2]

    r[0] = x * mat[0][0] + y * mat[1][0] + z * mat[2][0] + mat[3][0] * v[3]
    r[1] = x * mat[0][1] + y * mat[1][1] + z * mat[2][1] + mat[3][1] * v[3]
    r[2] = x * mat[0][2] + y * mat[1][2] + z * mat[2][2] + mat[3][2] * v[3]
    r[3] = x * mat[0][3] + y * mat[1][3] + z * mat[2][3] + mat[3][3] * v[3]

cdef void mul_m4_v4(const float[4][4] mat, float[4] r) noexcept nogil:
    mul_v4_m4v4(r, mat, r)

cdef void transpose_matrix_4x4(const float[4][4] mat, float[4][4] result) noexcept nogil:
    cdef int i, j
    
    for i in range(4):
        for j in range(4):
            result[i][j] = mat[j][i]
