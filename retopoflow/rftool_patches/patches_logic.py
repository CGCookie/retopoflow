'''
Copyright (C) 2026 CG Cookie
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

# pyright: reportUninitializedInstanceVariable = false


from __future__ import annotations

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bmesh.types import BMVert, BMEdge
from mathutils import Vector

from ..rfglobals import RFGlobals

from ..common.bmesh import get_bmesh_emesh
from ..common.drawing import Drawing



class Patches_Logic:
    depsgraph_version : int = -42

    # Points that will act as corners for patch, where keys are either a...
    # - int >= 0 corresponding to index of BMVert or
    # - int <  0 indicating a corner that is not yet associated with BMVert (will be new BMVert on commit)
    # and values are location in world space.
    #
    # IMPORTANT: must not keep reference to bmesh elements, because they will invalidate
    #       whenever depsgraph changes!  Instead, keep track of them via their indices.
    corners : dict[int, Vector] = {}

    def __init__(self):
        pass

    def update(self):
        RFCore = RFGlobals.RFCore_None
        if not RFCore:
            return

        if self.depsgraph_version == RFCore.depsgraph_version:
            return

        context = bpy.context
        edit_object = context.edit_object
        if not edit_object:
            return

        M = edit_object.matrix_world
        self.depsgraph_version = RFCore.depsgraph_version

        bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)

        if isinstance(bmv_active := bm.select_history.active, BMVert):
            # add active element to collection of corner BMVerts
            self.corners[bmv_active.index] = M @ bmv_active.co

        # filter previous corners to those that are still selected
        len_verts = len(bm.verts)
        self.corners = {
            i: pt
            for (i, pt) in self.corners.items()
            if i < len_verts and (bmv := bm.verts[i]) and bmv.select
        }

    def draw(self):
        context = bpy.context
        rgn, r3d = context.region, context.region_data

        Drawing.draw2D_points(
            context,
            [
                location_3d_to_region_2d(rgn, r3d, pt)
                for pt in self.corners.values()
            ],
            (1, 1, 0, 1),
            radius=12,
        )
