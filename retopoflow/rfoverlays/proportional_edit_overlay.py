'''
Copyright (C) 2025 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel, JF Matheu

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

import bpy
from bpy.types import Context, Event
from bmesh.types import BMVert, BMEdge, BMFace, BMesh
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector
from ...addon_common.common.maths import Color
from ..common.drawing import Drawing
from ...addon_common.common import gpustate


class ProportionalEditOverlay:
    center_2d: Vector | None = None
    center_3d: Vector | None = None

    def __init__(self, context: Context, event: Event, bm: BMesh):
        if not context.tool_settings.use_proportional_edit:
            return

        # Based on the pivot point, we should calculate the proportional editing circle graphic center.
        pivot_point = context.tool_settings.transform_pivot_point
        pivot_co = None

        if pivot_point == 'BOUNDING_BOX_CENTER':
            ob = context.active_object
            bb = ob.bound_box
            # Calculate bounding box center in local coordinates.
            center_local = Vector((
                (min(v[0] for v in bb) + max(v[0] for v in bb)) / 2,
                (min(v[1] for v in bb) + max(v[1] for v in bb)) / 2,
                (min(v[2] for v in bb) + max(v[2] for v in bb)) / 2
            ))
            # Convert to world coordinates.
            pivot_co = ob.matrix_world @ center_local
        elif pivot_point == 'CURSOR':
            pivot_co = context.scene.cursor.location
        elif pivot_point in {'INDIVIDUAL_ORIGINS', 'MEDIAN_POINT'}:
            sel_coords = []
            for bmv in bm.verts:
                if bmv.select:
                    sel_coords.append(bmv.co)
            if sel_coords:
                pivot_co = sum(sel_coords, Vector()) / len(sel_coords)
        elif pivot_point == 'ACTIVE_ELEMENT':
            active_elem = bm.select_history.active
            if isinstance(active_elem, BMVert):
                pivot_co = active_elem.co
            elif isinstance(active_elem, BMEdge):
                pivot_co = (active_elem.verts[0].co + active_elem.verts[1].co) / 2
            elif isinstance(active_elem, BMFace):
                pivot_co = active_elem.calc_center_median()

        # If no pivot point was set, use the object's location.
        if pivot_co is None:
            pivot_co = context.active_object.location

        self.center_3d = pivot_co
        self.center_2d = location_3d_to_region_2d(context.region, context.region_data, pivot_co)

    def draw_2d(self, context):
        if not context.tool_settings.use_proportional_edit:
            return
        if self.center_2d is None or self.center_3d is None:
            return

        prop_dist_world = context.tool_settings.proportional_distance

        # Use view's right vector to ensure consistent screen-space projection regardless of view angle to calculate the final radius.
        # This way we virtually have a 3D circle (`center_3d` as center, `radius_3d_point` as radius) that we can project to 2D.
        view_matrix = context.region_data.view_matrix
        right_vector = Vector((view_matrix[0][0], view_matrix[1][0], view_matrix[2][0])).normalized()
        radius_3d_point = self.center_3d + right_vector * prop_dist_world
        radius_2d_point = location_3d_to_region_2d(context.region, context.region_data, radius_3d_point, default=None)

        if radius_2d_point is None:
            return

        # Calculate 2D radius as the distance between projected center and radius point
        radius = (radius_2d_point - self.center_2d).length

        # Internally Blender proportional editing circle is based on the 3d view grid color.
        grid = context.preferences.themes[0].view_3d.grid
        col_off = 20/255
        color_in = Color((grid[0]+col_off, grid[1]+col_off, grid[2]+col_off, 1.0))  # lighter than grid color. full alpha
        color_out = Color((grid[0]-col_off, grid[1]-col_off, grid[2]-col_off, 1.0))  # darker than grid color. full alpha

        gpustate.blend('ALPHA')
        Drawing.draw2D_smooth_circle(context, self.center_2d, radius, color_out, width=3)
        Drawing.draw2D_smooth_circle(context, self.center_2d, radius-1, color_in, width=1)
        gpustate.blend('NONE')
