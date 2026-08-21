'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import math
import bpy

from ..common.maths import map_range, clamp


class RFProps_CurveHandles(bpy.types.PropertyGroup):
    ''' Curve handle settings shared by every tool that builds a CubicBezierSpline overlay.
    Whether the handles are shown is a per tool property. '''

    curve_handle_density: bpy.props.FloatProperty(
        name = 'Density',
        description = 'How many curve handles to show on the selection',
        subtype='FACTOR',
        min = 0.1,
        max = 1,
        default = 0.5
    )
    curve_corner_angle: bpy.props.FloatProperty(
        name = 'Corner Angle',
        description = 'Deflection angle beyond which a vert always gets its own (vector) '
                       'curve handle, regardless of the Density setting',
        subtype = 'ANGLE',
        min = math.radians(10),
        max = math.radians(170),
        default = math.radians(50),
    )

    @property
    def bend_tolerance_factor(self) -> float:
        '''Proportionally maps curve_handle_density to the bend tolerance factor passed to rdp_corner_indices'''
        t = map_range(clamp(self.curve_handle_density, 0.1, 1.0), 0.1, 1.0, 0.0, 1.0)
        lo, hi = 0.5, 0.01  # lo = few control points, hi = more
        return lo * (hi / lo) ** t


def register():
    bpy.utils.register_class(RFProps_CurveHandles)

def unregister():
    bpy.utils.unregister_class(RFProps_CurveHandles)
