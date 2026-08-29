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
from time import time
from bpy.types import Context, Event
from bmesh.types import BMVert, BMEdge, BMFace, BMesh
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector
from ..rfoverlay_base import RFOverlay_Base
from ...addon_common.common.maths import Color
from ..common.drawing import Drawing
from ...addon_common.common import gpustate


def draw_proportional_edit_circle(context: Context, center_world: Vector) -> bool:
    ''' Draw Blender's proportional-editing falloff circle at the
    world-space point `center_world`. Returns whether it drew. '''
    rgn, r3d = context.region, context.region_data
    center_2d = location_3d_to_region_2d(rgn, r3d, center_world, default=None)
    if center_2d is None:
        return False

    right = Vector(r3d.view_matrix[0][:3]).normalized()
    edge_world = center_world + right * context.tool_settings.proportional_distance
    edge_2d = location_3d_to_region_2d(rgn, r3d, edge_world, default=None)
    if edge_2d is None:
        return False

    # Blender's proportional editing circle is based on the 3D view grid color.
    grid  = context.preferences.themes[0].view_3d.grid
    color = Color((grid[0] - 20/255, grid[1] - 20/255, grid[2] - 20/255, 1.0))

    gpustate.blend('ALPHA')
    Drawing.draw2D_smooth_circle(
        context, center_2d, (edge_2d - center_2d).length, color,
        width=Drawing.scale(1), apply_ui_scale=False,
    )
    gpustate.blend('NONE')
    return True


# For breifly bringing up the overlay when not in a modal
FLASH_DURATION = 0.5  # seconds


class CircleFlash:
    ''' State for a briefly-shown falloff circle: a scroll step has no modal of its
    own to keep one on screen. '''
    handle       = None
    region       = None
    r3d          = None
    center_world = None
    view_matrix  = None
    until        = 0.0
    running      = False


def flash_expired() -> bool:
    f = CircleFlash
    if f.center_world is None or time() >= f.until:
        return True
    # an orbited circle no longer marks what it was drawn for, so end it early
    try:
        return f.r3d is None or f.r3d.view_matrix != f.view_matrix
    except ReferenceError:
        return True  # the area holding it went away


def flash_draw():
    # registered with no args, so `bpy.context` is the region currently being drawn
    f, context = CircleFlash, bpy.context
    region = getattr(context, 'region', None)
    if region is None or f.region is None:
        return
    try:
        # `==`, never `is`: bpy hands out a fresh wrapper per access, so the same
        # region compares False by identity and the circle would never draw
        if region != f.region:
            return  # only in the viewport the flash started in
    except ReferenceError:
        return
    if flash_expired():
        return
    draw_proportional_edit_circle(context, f.center_world)


def flash_stop():
    f = CircleFlash
    if f.handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(f.handle, 'WINDOW')
        f.handle = None
    f.running = False
    f.center_world = None
    try:
        if f.region: f.region.tag_redraw()  # final redraw erases the circle
    except ReferenceError:
        pass
    f.region = f.r3d = None


def flash_driver():
    # bpy.app.timers callback: keep redrawing so the circle stays up (and then
    # disappears) without needing mouse movement
    if not flash_expired():
        try:
            if CircleFlash.region: CircleFlash.region.tag_redraw()
        except ReferenceError:
            flash_stop()
            return None
        return 1.0 / 60.0
    flash_stop()
    return None


def flash_proportional_edit_circle(context: Context, center_world: Vector, duration: float = FLASH_DURATION) -> bool:
    ''' Briefly show the falloff circle at `center_world`. No-op when proportional
    editing is off, since then there is no falloff to show. Returns whether it started. '''
    if not context.tool_settings.use_proportional_edit: return False
    if center_world is None: return False
    r3d = getattr(context, 'region_data', None)
    if r3d is None or getattr(context, 'region', None) is None: return False

    f = CircleFlash
    f.center_world = Vector(center_world)
    f.region       = context.region
    f.r3d          = r3d
    f.view_matrix  = r3d.view_matrix.copy()
    f.until        = time() + duration   # a further scroll notch just extends the window
    if f.handle is None:
        f.handle = bpy.types.SpaceView3D.draw_handler_add(flash_draw, (), 'WINDOW', 'POST_PIXEL')
    if not f.running:
        f.running = True
        bpy.app.timers.register(flash_driver)
    f.region.tag_redraw()
    return True


class ProportionalEditOverlay(RFOverlay_Base):
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
                pivot_co = context.active_object.matrix_world @ (sum(sel_coords, Vector()) / len(sel_coords))
        elif pivot_point == 'ACTIVE_ELEMENT':
            active_elem = bm.select_history.active
            mw = context.active_object.matrix_world
            if isinstance(active_elem, BMVert):
                pivot_co = mw @ active_elem.co
            elif isinstance(active_elem, BMEdge):
                pivot_co = mw @ ((active_elem.verts[0].co + active_elem.verts[1].co) / 2)
            elif isinstance(active_elem, BMFace):
                pivot_co = mw @ active_elem.calc_center_median()

        # If no pivot point was set, use the object's location.
        if pivot_co is None:
            pivot_co = context.active_object.location

        self.center_3d = pivot_co
        self.center_2d = location_3d_to_region_2d(context.region, context.region_data, pivot_co)

    def draw_2d(self, context):
        if not context.tool_settings.use_proportional_edit:
            return
        if self.center_3d is None:
            return
        draw_proportional_edit_circle(context, self.center_3d)
