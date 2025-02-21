# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=False
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=True

from libc.stdlib cimport malloc, free
from libc.math cimport isfinite
from libc.stdint cimport uintptr_t

from .bl_types cimport ARegion, RegionView3D


cdef float* location_3d_to_region_2d(const ARegion* region, const RegionView3D* rv3d, float[3] coord, float[2] default_value) noexcept nogil:
    cdef:
        float[4] vec
        float* result = NULL
        float w
        short winx, winy

    # Store the window dimensions locally
    winx = region.winx
    winy = region.winy

    # Create homogeneous coordinate
    vec[0] = coord[0]
    vec[1] = coord[1]
    vec[2] = coord[2]
    vec[3] = <float>1.0

    # Apply perspective matrix
    w = (rv3d.persmat[0][3] * vec[0] +
         rv3d.persmat[1][3] * vec[1] +
         rv3d.persmat[2][3] * vec[2] +
         rv3d.persmat[3][3])

    if w > 0.0:
        # Apply perspective divide and viewport transform
        result = <float*>malloc(sizeof(float)*2)
        if result == NULL:
            return NULL

        # Perspective divide
        w = <float>1.0 / w
        vec[0] = (rv3d.persmat[0][0] * coord[0] +
                rv3d.persmat[1][0] * coord[1] +
                rv3d.persmat[2][0] * coord[2] +
                rv3d.persmat[3][0]) * w
        vec[1] = (rv3d.persmat[0][1] * coord[0] +
                rv3d.persmat[1][1] * coord[1] +
                rv3d.persmat[2][1] * coord[2] +
                rv3d.persmat[3][1]) * w

        # Viewport transform
        result[0] = (winx * <float>0.5) * (<float>1.0 + vec[0])
        result[1] = (winy * <float>0.5) * (<float>1.0 + vec[1])

        # Check if point is within region bounds
        if result[0] < 0 or result[0] > winx or result[1] < 0 or result[1] > winy:
            free(result)
            if default_value != NULL:
                result = <float*>malloc(sizeof(float)*2)
                if result != NULL:
                    result[0] = default_value[0]
                    result[1] = default_value[1]
            return result

        # Ensure result is finite
        if not (isfinite(result[0]) and isfinite(result[1])):
            free(result)
            if default_value != NULL:
                result = <float*>malloc(sizeof(float)*2)
                if result != NULL:
                    result[0] = default_value[0]
                    result[1] = default_value[1]
            return result

        return result

    # Return default value if point is behind camera
    if default_value != NULL:
        result = <float*>malloc(sizeof(float)*2)
        if result != NULL:
            result[0] = default_value[0]
            result[1] = default_value[1]
    return result

# Python wrapper
def py_location_3d_to_region_2d(region, rv3d, coord, default=None):
    """Return the region relative 2d location of a 3d position.
    
    Args:
        region: Region of the 3D viewport
        rv3d: 3D region data
        coord: 3d world-space location
        default: Return this value if coord is behind the origin of a perspective view
    
    Returns:
        2d location as (x, y) tuple or default value
    """
    cdef:
        float[3] c_coord
        float[2] c_default
        float* result
        ARegion* c_region = <ARegion*>(<uintptr_t>id(region))
        RegionView3D* c_rv3d = <RegionView3D*>(<uintptr_t>id(rv3d))

    c_coord[0] = coord[0]
    c_coord[1] = coord[1]
    c_coord[2] = coord[2]

    if default is not None:
        c_default[0] = default[0]
        c_default[1] = default[1]
        result = location_3d_to_region_2d(c_region, c_rv3d, c_coord, c_default)
    else:
        result = location_3d_to_region_2d(c_region, c_rv3d, c_coord, NULL)

    if result == NULL:
        return None
    
    ret = (result[0], result[1])
    free(result)
    return ret
