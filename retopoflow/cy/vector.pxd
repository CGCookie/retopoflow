# distutils: language=c++
# cython: language_level=3

cdef struct Vector2:
    float x
    float y

cdef struct Vector3:
    float x
    float y
    float z

cdef struct Vector4:
    float x
    float y
    float z
    float w

# From DNA_vec_types.h
cdef struct rcti:
    int xmin, xmax
    int ymin, ymax

cdef struct rctf:
    float xmin, xmax
    float ymin, ymax

cdef struct BoundBox:
    float[8][3] vec

cdef inline float vec3_dot(const float* a, const float* b) noexcept nogil
cdef inline void vec3_normalize(float* v) noexcept nogil
