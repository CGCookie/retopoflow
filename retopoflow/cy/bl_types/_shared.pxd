# distutils: language=c++
# cython: language_level=3

# Common C struct definitions that are assumed to be stable across supported versions
# If any of these change between versions, they would need to be moved into the conditional blocks below.
from retopoflow.cy.bl_types.vec_types cimport rcti, rctf, BoundBox
from retopoflow.cy.bl_types.list_base cimport ListBase
from retopoflow.cy.bl_types.bmesh_types cimport BMVert, BMEdge, BMFace, BMesh, BMLoop, BMHeader, BMElem
from retopoflow.cy.bl_types.bmesh_py_wrappers cimport BPy_BMesh
from retopoflow.cy.bl_types.bmesh_flags cimport BMElemHFlag, BM_elem_flag_test
from retopoflow.cy.bl_types.gpu_py_wrappers cimport BPyGPUBuffer
