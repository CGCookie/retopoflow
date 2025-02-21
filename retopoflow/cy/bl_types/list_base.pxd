# distutils: language=c++
# cython: language_level=3

# From DNA_listbase.h
cdef struct ListBase:
    void* first
    void* last