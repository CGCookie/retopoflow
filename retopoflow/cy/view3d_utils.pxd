# distutils: language=c++
# cython: language_level=3

from .bl_types cimport ARegion, RegionView3D

# Match the exact signature from the .pyx file
cdef float* location_3d_to_region_2d(const ARegion* region, const RegionView3D* rv3d, const float[3] coord, const float[2] default_value) noexcept nogil

