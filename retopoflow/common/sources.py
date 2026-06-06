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

# Shared "hard surface snapping" helpers used by both Relax and Tweak: detecting feature
# edges/corners on the source mesh and snapping retopo verts onto them.  Tool-agnostic on
# purpose — callers pass in their own matrices/options so the logic stays identical in both
# tools.  (File name is provisional; grouping by concern for now.)

from mathutils import Vector, Matrix
import math

from .maths import point_to_bvec3


def to_world(co:Vector, matrix_world:Matrix) -> Vector:
    ''' Local bmesh coordinate -> world-space Vector. '''
    return point_to_bvec3((matrix_world @ Vector((*co, 1.0))).xyz)


# ------------------------------------------------------------------------------------------
# UI
# ------------------------------------------------------------------------------------------

def draw_hard_surface_snapping(layout, props, *, guide_loops:bool=False):
    ''' Shared "Hard Surface Snapping" option body for the Relax and Tweak panels.  Draws
    straight into `layout`, so the caller owns the panel/popover wrapper and its header.
    `guide_loops` adds the Relax-only loop-guiding controls (Tweak has no forces, so it
    pulls verts onto features directly without electing guide loops). '''
    col = layout.column()
    row = col.row(align=True, heading='Angles')
    row.prop(props, 'source_edge_angle_enabled', text='')
    sub = row.row()
    sub.enabled = getattr(props, 'source_edge_angle_enabled', True)
    sub.prop(props, 'source_edge_angle', text='')
    col.prop(props, 'source_edge_creases', text='Creases')
    col.prop(props, 'source_edge_seams',   text='Seams')
    col.prop(props, 'source_edge_sharps',  text='Sharps')
    angle_enabled = getattr(props, 'source_edge_angle_enabled', True)
    angle = getattr(props, 'source_edge_angle', math.pi)
    col2 = col.column()
    col2.enabled = (
        angle_enabled and angle != math.radians(180) or
        getattr(props, 'source_edge_creases', False) or
        getattr(props, 'source_edge_seams',   False) or
        getattr(props, 'source_edge_sharps',  False)
    )
    col2.separator()
    col2.prop(props, 'source_edge_proximity', text='Proximity')
    col2.prop(props, 'source_edge_stickiness', text='Stickiness', slider=True)
    if guide_loops:
        col2.prop(props, 'source_edge_guide_loops', text='Guide Loops', slider=True)
