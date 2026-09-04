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

import bpy
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.types import Context

from collections.abc import Sequence

from ..rfglobals import RFGlobals
from ..common.bmesh import get_bmesh_emesh, bme_midpoint, get_boundary_strips_cycles
from ..common.drawing import Drawing
from ..common.raycast import is_point_hidden
from ...addon_common.common import bmesh_ops as bmops


def get_label_pos(context : Context, label : str, mids : Sequence[Vector], corners : Sequence[Vector]) -> Vector | None:
    if not context.edit_object:
        return None

    M = context.edit_object.matrix_world
    rgn, r3d = context.region, context.region_data

    boundary = [pt for pt in mids if not is_point_hidden(context, pt)]
    if len(boundary) == 0:
        boundary = [pt for pt in corners if not is_point_hidden(context, pt)]
        if len(boundary) == 0:
            return None

    match label:
        case 'Strip':
            mid = sum(boundary, Vector((0,0,0))) / len(boundary)
            pt3d = min(boundary, key=lambda pt:(pt - mid).length)
            return location_3d_to_region_2d(rgn, r3d, M @ pt3d)

        case 'Loop':
            pts2d = [pt2d for pt in boundary if (pt2d := location_3d_to_region_2d(rgn, r3d, M @ pt)) is not None]
            return max(pts2d, default=None, key=lambda pt2d:pt2d.y)

        case _:
            assert False, f'Unhandled {label=}'


def draw_loopstrip_selection_labels(host, *, only_boundary : bool):
    ''' Count labels for each selected strip and loop, called from a host overlay's
    draw_postpixel_overlay. The host holds the cache in loopstrip_depsgraph_version and
    loopstrip_boundaries so it does not have to inherit an overlay class to get these labels,
    which matters when it already inherits one. '''
    RFCore = RFGlobals.RFCore_None
    if not RFCore:
        return

    if host.loopstrip_depsgraph_version != RFCore.depsgraph_version:
        # depsgraph changed, so recollect boundary details

        host.loopstrip_depsgraph_version = RFCore.depsgraph_version

        # find selected boundary strips
        bm, _ = get_bmesh_emesh(bpy.context)
        sel_bmes = [ bme for bme in bmops.get_all_selected_bmedges(bm) ]
        if only_boundary or any(bme.is_wire or bme.is_boundary for bme in sel_bmes):
            # filter selected edges to only boundaries
            sel_bmes = [ bme for bme in sel_bmes if bme.is_wire or bme.is_boundary ]
        if len(sel_bmes) < 1000:
            bmes_strips, bmes_cycles = get_boundary_strips_cycles(sel_bmes)
            # copy makes sure this cache doesn't hold a stale pointer to a vert
            strips = [
                ([bme_midpoint(bme) for bme in strip], [bmv.co.copy() for bme in strip for bmv in bme.verts])
                for strip in bmes_strips
            ]
            cycles = [
                ([bme_midpoint(bme) for bme in cycle], [bmv.co.copy() for bme in cycle for bmv in bme.verts])
                for cycle in bmes_cycles
            ]
            if len(strips) + len(cycles) <= 5:
                host.loopstrip_boundaries = (strips, cycles)
            else:
                host.loopstrip_boundaries = ([], [])
        else:
            host.loopstrip_boundaries = ([], [])

    # draw info about each selected boundary strip
    is_vertex_select = bpy.context.tool_settings.mesh_select_mode[0]
    for (lbl, boundaries) in zip(['Strip', 'Loop'], host.loopstrip_boundaries):
        for (mids, corners) in boundaries:
            lbl_pos = get_label_pos(bpy.context, lbl, mids, corners)
            if not lbl_pos:
                continue
            count = len(mids)
            if is_vertex_select and lbl != 'Loop':
                count += 1
            if count == 1:
                continue
            text = f'{lbl}: {count}' if lbl == 'Loop' else str(count)
            tw, th = Drawing.get_text_width(text), Drawing.get_text_height(text)
            lbl_pos -= Vector((tw / 2, -th / 2))
            Drawing.text_draw2D(text, lbl_pos.xy, color=(1,1,0,1), dropshadow=(0,0,0,0.75))
