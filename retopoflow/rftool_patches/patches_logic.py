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
from typing import ClassVar

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bmesh.types import BMVert, BMEdge
from mathutils import Vector

from ..rfglobals import RFGlobals

from ...addon_common.common import bmesh_ops as bmops
from ..common.bmesh import get_bmesh_emesh
from ..common.drawing import Drawing



class Patches_Logic:
    depsgraph_version : ClassVar[int] = -42

    # Points that will act as corners for patch, where keys are index of BMVert
    # and values are location in world space.
    #
    # IMPORTANT: must not keep reference to bmesh elements, because they will invalidate
    #       whenever depsgraph changes!  Instead, keep track of them via their indices.
    corners : ClassVar[dict[int, Vector]] = {}

    @staticmethod
    def update():
        RFCore = RFGlobals.RFCore
        context = bpy.context
        edit_object = context.edit_object
        assert edit_object
        M = edit_object.matrix_world

        if Patches_Logic.depsgraph_version == RFCore.depsgraph_version:
            return
        Patches_Logic.depsgraph_version = RFCore.depsgraph_version

        bm, _ = get_bmesh_emesh(context, ensure_lookup_tables=True)

        if isinstance(bmv_active := bm.select_history.active, BMVert):
            # add active element to collection of corner BMVerts
            Patches_Logic.corners[bmv_active.index] = M @ bmv_active.co

        # filter previous corners to those that are still selected
        len_verts = len(bm.verts)
        Patches_Logic.corners = {
            i: (M @ bmv.co)
            for i in Patches_Logic.corners
            if i < len_verts and (bmv := bm.verts[i]) and bmv.select
        }


    @staticmethod
    def insert_corner(co_local : Vector):
        bm, em = get_bmesh_emesh(bpy.context)
        bmv = bm.verts.new(co_local)
        bmops.select(bm, bmv)
        bmops.flush_selection(bm, em)
        Patches_Logic.update()

    @staticmethod
    def draw():
        context = bpy.context
        rgn, r3d = context.region, context.region_data

        Drawing.draw2D_points(
            context,
            [
                location_3d_to_region_2d(rgn, r3d, pt)
                for pt in Patches_Logic.corners.values()
            ],
            (1, 1, 0, 1),
            radius=12,
        )
