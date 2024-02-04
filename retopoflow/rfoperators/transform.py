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

import blf
import bmesh
import bpy
import gpu
from bmesh.types import BMVert, BMEdge, BMFace
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

import math
import time
from typing import List
from enum import Enum

from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, get_select_layers, NearestBMVert
from ..common.operator import invoke_operator, execute_operator, RFOperator
from ..common.raycast import raycast_mouse_valid_sources, raycast_point_valid_sources
from ..common.maths import view_forward_direction
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.reseter import Reseter
from ...addon_common.common.blender import get_path_from_addon_common
from ...addon_common.common import gpustate
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import clamp
from ...addon_common.common.utils import iter_pairs


class RFOperator_Translate(RFOperator):
    bl_idname = "retopoflow.translate"
    bl_label = 'Translate'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymap = {'type': 'G', 'value': 'PRESS'}
    rf_status = ['LMB: Commit', 'MMB: (nothing)', 'RMB: Cancel']

    def init(self, context, event):
        print(f'STARTING TRANSLATE')
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.bm, self.em = get_bmesh_emesh(context)
        self.nearest = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv)

        self.bmvs = [(bmv, Vector(bmv.co))     for bmv in bmops.get_all_selected_bmverts(self.bm)]
        self.bmfs = [(bmf, Vector(bmf.normal)) for bmf in { bmf for (bmv,_) in self.bmvs for bmf in bmv.link_faces }]
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        Cursors.set('NONE')  # PAINT_CROSS

    def update(self, context, event):
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.cancel_reset(context, event)
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE':
            # HANDLE MERGE!!!
            # bpy.ops.mesh.remove_doubles('EXEC_DEFAULT', use_unselected=True)
            self.automerge(context, event)
            return {'FINISHED'}

        if event.type == 'MOUSEMOVE':
            self.translate(context, event)

        return {'RUNNING_MODAL'}

    def automerge(self, context, event):
        merging = {}
        for bmv, _ in self.bmvs:
            self.nearest.update(context, bmv.co)
            if not self.nearest.bmv: continue
            bmv_into = self.nearest.bmv
            if bmv_into not in merging: merging[bmv_into] = [bmv_into]
            merging[bmv_into].append(bmv)
        for bmvs in merging.values():
            bmesh.ops.pointmerge(self.bm, verts=bmvs, merge_co=bmvs[0].co)

        self.update_normals(context, event)

        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def cancel_reset(self, context, event):
        for bmv, co_orig in self.bmvs:
            bmv.co = co_orig
        for bmf, norm_orig in self.bmfs:
            bmf.normal_update()
            if norm_orig.dot(bmf.normal) < 0: bmf.normal_flip()
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def translate(self, context, event):
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        delta = mouse - self.mouse

        for bmv, co_orig in self.bmvs:
            co = (self.matrix_world @ Vector((*co_orig, 1.0))).xyz
            point = location_3d_to_region_2d(context.region, context.region_data, co)
            if not point: continue
            co = raycast_point_valid_sources(context, event, point + delta, world=False)
            if not co: continue
            self.nearest.update(context, co)
            if self.nearest.bmv: co = self.nearest.bmv.co
            bmv.co = co

        self.update_normals(context, event)

        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def update_normals(self, context, event):
        forward = (self.matrix_world_inv @ Vector((*view_forward_direction(context), 0.0))).xyz
        for bmf, _ in self.bmfs:
            bmf.normal_update()
            if forward.dot(bmf.normal) > 0:
                bmf.normal_flip()


