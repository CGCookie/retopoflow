# distutils: language=c++
# cython: language_level=3

from .vector cimport Vector2, Vector3
from .space cimport ARegion, RegionView3D

# Match the exact signature from the .pyx file
cdef Vector2* location_3d_to_region_2d(ARegion* region, RegionView3D* rv3d, Vector3* coord, Vector2* default_value=?) except? NULL nogil
