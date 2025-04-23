# distutils: language=c++
# cython: language_level=3


from cpython.object cimport PyObject
from libc.stdint cimport uintptr_t, uint32_t

# Now we can define the BPyGPUBuffer struct
cdef extern from *:
    """
    // This recreates the struct in Cython context from gpu_py_buffer.hh
    // We assume PyObject_VAR_HEAD expands to:
    // Py_ssize_t ob_refcnt; PyTypeObject *ob_type; Py_ssize_t ob_size;
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
        # Explicitly define layout matching C struct for robustness
        Py_ssize_t ob_refcnt
        uintptr_t ob_type # Use uintptr_t for PyTypeObject*
        Py_ssize_t ob_size
        PyObject* parent

        # Struct members
        int format
        int shape_len
        Py_ssize_t* shape
        
        # Union members - mapped directly from C union 'buf'
        char* buf_as_byte "buf.as_byte"
        int* buf_as_int "buf.as_int"
        uint32_t* buf_as_uint "buf.as_uint" # Use uint32_t for unsigned int*
        float* buf_as_float "buf.as_float"
        void* buf_as_void "buf.as_void"
