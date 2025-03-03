# distutils: language=c++
# cython: language_level=3

# Import directly from the local package
from bpy.app import version
cdef int BLENDER_VERSION = version[0] * 100 + version[1] * 10 + version[2]

# Import the structures directly
from retopoflow.cy.bl_types.vec_types cimport rcti, rctf, BoundBox
from retopoflow.cy.bl_types.list_base cimport ListBase
from retopoflow.cy.bl_types.bmesh_types cimport BMVert, BMEdge, BMFace, BMesh, BMLoop, BMHeader
from retopoflow.cy.bl_types.bmesh_py_wrappers cimport BPy_BMesh
from retopoflow.cy.bl_types.bmesh_flags cimport BMElemHFlag, BM_elem_flag_test

# VERSIONING - use absolute imports instead of relative
if BLENDER_VERSION >= 440:
    from .v440 cimport ARegion, RegionView3D, View2D
elif BLENDER_VERSION >= 430:
    from .v430 cimport ARegion, RegionView3D, View2D
else:
    raise ImportError(f"Unsupported Blender version: {BLENDER_VERSION}")
