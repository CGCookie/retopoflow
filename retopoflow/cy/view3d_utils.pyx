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
from libc.math cimport isfinite, fabs
from libc.stdint cimport uintptr_t

from .bl_types cimport ARegion, RegionView3D
from .math_matrix cimport mul_v4_m4v4


cdef bint location_3d_to_region_2d(const ARegion* region, const float[4][4] persp_matrix, const float[3] coord, float* result) noexcept nogil:
    cdef:
        float[4] vec
        float[4] prj  # Projected vector
        float w
        float width_half, height_half

    # Initialize result to -10000, -10000
    result[0] = <float>(-10000.0)
    result[1] = <float>(-10000.0)

    # Prepare homogeneous coordinates
    vec[0] = coord[0]
    vec[1] = coord[1]
    vec[2] = coord[2]
    vec[3] = <float>1.0

    mul_v4_m4v4(prj, persp_matrix, vec)

    # Check if w > 0.0 (EXACTLY like Python version - no fabs, no epsilon)
    w = prj[3]
    if w <= 0.0:
        return False

    # Calculate window coordinates exactly like Python version
    width_half = <float>region.winx / <float>2.0
    height_half = <float>region.winy / <float>2.0
    
    # EXACTLY match Python calculation
    result[0] = width_half * (prj[0] / w) + width_half
    result[1] = height_half * (prj[1] / w) + height_half

    # with gil:
    #     print(f"\t-PROJ COORD: ({prj[0]}, {prj[1]}, {prj[2]}, {prj[3]})")
    #     print("\t-RESULT", <float>(<double>width_half + <double>width_half * (prj[0] / w)), <float>(<double>height_half + <double>height_half * (prj[1] / w)))
        
    return True



'''
# WORKING PYTHON BLENDER VERSION


def location_3d_to_region_2d(region, rv3d, coord, *, default=None):
    """
    Return the *region* relative 2d location of a 3d position.

    :arg region: region of the 3D viewport, typically bpy.context.region.
    :type region: :class:`bpy.types.Region`
    :arg rv3d: 3D region data, typically bpy.context.space_data.region_3d.
    :type rv3d: :class:`bpy.types.RegionView3D`
    :arg coord: 3d world-space location.
    :type coord: 3d vector
    :arg default: Return this value if ``coord``
       is behind the origin of a perspective view.
    :return: 2d location
    :rtype: :class:`mathutils.Vector` | Any
    """
    from mathutils import Vector

    prj = rv3d.perspective_matrix @ Vector((coord[0], coord[1], coord[2], 1.0))
    if prj.w > 0.0:
        width_half = region.width / 2.0
        height_half = region.height / 2.0

        return Vector((
            width_half + width_half * (prj.x / prj.w),
            height_half + height_half * (prj.y / prj.w),
        ))
    else:
        return default

'''