# distutils: language=c++
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: nonecheck=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: embedsignature=True
# cython: binding=False

from libc.stdlib cimport malloc, free
from libc.math cimport isfinite
from libc.stdint cimport uintptr_t

from .vector cimport Vector2, Vector3, Vector4
from .space cimport ARegion, RegionView3D


cdef Vector2* location_3d_to_region_2d(ARegion* region, RegionView3D* rv3d, Vector3* coord, Vector2* default_value=NULL) nogil:
    cdef:
        Vector4 vec
        Vector2* result = NULL
        float w

    # Create homogeneous coordinate
    vec.x = coord.x
    vec.y = coord.y
    vec.z = coord.z
    vec.w = 1.0

    # Apply perspective matrix
    w = (rv3d.persmat[0][3] * vec.x +
         rv3d.persmat[1][3] * vec.y +
         rv3d.persmat[2][3] * vec.z +
         rv3d.persmat[3][3])

    if w > 0.0:
        # Apply perspective divide and viewport transform
        result = <Vector2*>malloc(sizeof(Vector2))
        if result == NULL:
            return NULL

        # Perspective divide
        w = 1.0 / w
        vec.x = (rv3d.persmat[0][0] * coord.x +
                rv3d.persmat[1][0] * coord.y +
                rv3d.persmat[2][0] * coord.z +
                rv3d.persmat[3][0]) * w
        vec.y = (rv3d.persmat[0][1] * coord.x +
                rv3d.persmat[1][1] * coord.y +
                rv3d.persmat[2][1] * coord.z +
                rv3d.persmat[3][1]) * w

        # Viewport transform
        result.x = (region.winx * 0.5) * (1.0 + vec.x)
        result.y = (region.winy * 0.5) * (1.0 + vec.y)

        # Ensure result is finite
        if not (isfinite(result.x) and isfinite(result.y)):
            free(result)
            if default_value != NULL:
                result = <Vector2*>malloc(sizeof(Vector2))
                if result != NULL:
                    result.x = default_value.x
                    result.y = default_value.y
            return result

        return result

    # Return default value if point is behind camera
    if default_value != NULL:
        result = <Vector2*>malloc(sizeof(Vector2))
        if result != NULL:
            result.x = default_value.x
            result.y = default_value.y
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
        Vector3 c_coord
        Vector2 c_default
        Vector2* result
        ARegion* c_region = <ARegion*>(<uintptr_t>id(region))
        RegionView3D* c_rv3d = <RegionView3D*>(<uintptr_t>id(rv3d))

    c_coord.x = coord[0]
    c_coord.y = coord[1]
    c_coord.z = coord[2]

    if default is not None:
        c_default.x = default[0]
        c_default.y = default[1]
        result = location_3d_to_region_2d(c_region, c_rv3d, &c_coord, &c_default)
    else:
        result = location_3d_to_region_2d(c_region, c_rv3d, &c_coord, NULL)

    if result == NULL:
        return None
    
    ret = (result.x, result.y)
    free(result)
    return ret
