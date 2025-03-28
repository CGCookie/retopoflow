# distutils: language=c++
# cython: language_level=3


from cpython.object cimport PyObject
from libc.stdint cimport uintptr_t, uint32_t

cdef struct PyObject_VAR_HEAD:
    size_t ob_refcnt
    void* ob_type
    size_t ob_size

# First, we need to declare the Python C API components
cdef extern from "Python.h":
    # PyObject_VAR_HEAD expands to these basic components
    ctypedef struct PyVarObject:
        PyObject ob_base
        Py_ssize_t ob_size  # Size of variable part

    ctypedef struct PyObject:
        Py_ssize_t ob_refcnt
        uintptr_t ob_type

# Now we can define the BPyGPUBuffer struct
cdef extern from *:
    """
    // This recreates the struct in Cython context
    typedef struct {
        PyObject_VAR_HEAD
        PyObject *parent;

        int format;
        int shape_len;
        Py_ssize_t *shape;

        union {
            char *as_byte;
            int *as_int;
            unsigned int *as_uint;
            float *as_float;
            void *as_void;
        } buf;
    } BPyGPUBuffer;
    """
    ctypedef struct BPyGPUBuffer:
        # PyVarObject components (from PyObject_VAR_HEAD)
        Py_ssize_t ob_refcnt
        uintptr_t ob_type
        Py_ssize_t ob_size
        
        # Struct members
        PyObject* parent
        int format
        int shape_len
        Py_ssize_t* shape
        
        # Union members - in Cython we access them separately
        char* buf_as_byte "buf.as_byte"
        int* buf_as_int "buf.as_int"
        uint32_t* buf_as_uint "buf.as_uint"
        float* buf_as_float "buf.as_float"
        void* buf_as_void "buf.as_void"
