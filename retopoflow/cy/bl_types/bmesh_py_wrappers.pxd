# distutils: language=c++
# cython: language_level=3


from .bmesh_types cimport BMesh


# Python wrapper structures
cdef struct PyObject_VAR_HEAD:
    size_t ob_refcnt
    void* ob_type
    size_t ob_size

cdef struct BPy_BMGeneric:
    PyObject_VAR_HEAD py_object
    BMesh* bm

cdef struct BPy_BMElem:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* ele  # BMElem*

cdef struct BPy_BMesh:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    int flag

cdef struct BPy_BMVert:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* v  # BMVert*

cdef struct BPy_BMEdge:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* e  # BMEdge*

cdef struct BPy_BMFace:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* f  # BMFace*

cdef struct BPy_BMLoop:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* l  # BMLoop*

cdef struct BPy_BMElemSeq:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    BPy_BMElem* py_ele
    short itype

cdef struct BPy_BMIter:
    PyObject_VAR_HEAD py_object
    BMesh* bm
    void* iter  # BMIter
