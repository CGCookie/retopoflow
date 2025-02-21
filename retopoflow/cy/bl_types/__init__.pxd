# distutils: language=c++
# cython: language_level=3

try:
    from bpy.app import version
    version_int = version[0] * 100 + version[1] * 10 + version[2]  # version[0] * 10000 + version[1] * 100 + version[2]
except ImportError:
    raise ImportError("Blender is not installed")

cdef int BLENDER_VERSION = <int>version_int
'''
from .bmesh cimport BMesh, BMHeader, BMVert, BMEdge, BMFace, BMLoop
from .bmesh_py_wrapper cimport BPy_BMesh, BPy_BMVert, BPy_BMEdge, BPy_BMFace, BPy_BMLoop, BPy_BMElemSeq, BPy_BMIter, BPy_BMElem
from .vec_types cimport rcti, rctf, BoundBox
from .bmesh_enums cimport BMElemHFlag, BM_elem_flag_test
'''
# VERSIONING
if BLENDER_VERSION >= 440:
    from .v440 cimport ARegion, RegionView3D, View2D
elif BLENDER_VERSION >= 430:
    from .v430 cimport ARegion, RegionView3D, View2D
else:
    raise ImportError(f"Unsupported Blender version: {BLENDER_VERSION}")
