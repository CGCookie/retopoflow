# distutils: language=c++
# cython: language_level=3

from .bl_types cimport ARegion, RegionView3D

cdef bint location_3d_to_region_2d(const ARegion* region, const float[4][4] persp_matrix, const float[3] coord, float* result) noexcept nogil

