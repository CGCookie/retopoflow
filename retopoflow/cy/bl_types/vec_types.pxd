# distutils: language=c++
# cython: language_level=3

# From DNA_vec_types.h
cdef struct rcti:
    int xmin, xmax
    int ymin, ymax

cdef struct rctf:
    float xmin, xmax
    float ymin, ymax

cdef struct BoundBox:
    float[8][3] vec
