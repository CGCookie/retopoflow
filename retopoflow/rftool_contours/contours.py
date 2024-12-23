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
import bmesh
from mathutils import Vector, Matrix
from bpy_extras.view3d_utils import location_3d_to_region_2d
from ..rftool_base import RFTool_Base
from ..common.bmesh import get_bmesh_emesh, nearest_bmv_world, nearest_bme_world, bme_midpoint, get_boundary_strips_cycles
from ..common.drawing import Drawing
from ..common.icons import get_path_to_blender_icon
from ..common.maths import view_forward_direction
from ..common.operator import (
    invoke_operator, execute_operator,
    RFOperator, RFRegisterClass,
    chain_rf_keymaps, wrap_property,
)
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event, nearest_point_valid_sources
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.reseter import Reseter

from ..rfoperators.transform import RFOperator_Translate_BoundaryLoop

from .contours_logic import Contours_Logic



class RFOperator_Contours(RFOperator):
    bl_idname = 'retopoflow.contours'
    bl_label = 'Contours'
    bl_description = 'Retopologize cylindrical forms, like arms and legs'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None),
        (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),

        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, None),

        ('mesh.loop_multi_select', {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, None),
    ]

    rf_status = ['LMB: Insert']

    initial_cut_count: bpy.props.IntProperty(
        name='Initial Count',
        description='Number of vertices to create in a new cut',
        default=8,
        min=3,
        max=100,
    )

    def init(self, context, event):
        self.logic = Contours_Logic(context, event)
        self.tickle(context)

    def reset(self):
        self.logic.reset()

    def update(self, context, event):
        self.logic.update(context, event, self)

        if self.logic.mousedown:
            return {'RUNNING_MODAL'}

        if not event.ctrl:
            self.logic.cleanup()
            Cursors.restore()
            self.tickle(context)
            return {'FINISHED'}

        Cursors.set('CROSSHAIR')
        return {'PASS_THROUGH'} # allow other operators, such as UNDO!!!

    def draw_postpixel(self, context):
        self.logic.draw(context)


class RFOperator_Contours_Overlay(RFOperator):
    bl_idname = 'retopoflow.contours_overlay'
    bl_label = 'Contours: Selected Overlay'
    bl_description = 'Overlays info about selected boundary edges'
    bl_options = { 'INTERNAL' }

    def init(self, context, event):
        self.depsgraph_version = None

    def update(self, context, event):
        is_done = (self.RFCore.selected_RFTool_idname != RFOperator_Contours.bl_idname)
        return {'CANCELLED'} if is_done else {'PASS_THROUGH'}

    def draw_postpixel_overlay(self, context):
        M = context.edit_object.matrix_world
        rgn, r3d = context.region, context.region_data

        if self.depsgraph_version != self.RFCore.depsgraph_version:
            self.depsgraph_version = self.RFCore.depsgraph_version

            # find selected boundary strips
            bm, _ = get_bmesh_emesh(context)
            sel_bmes = [ bme for bme in bmops.get_all_selected_bmedges(bm) if bme.is_wire or bme.is_boundary ]
            strips, cycles = get_boundary_strips_cycles(sel_bmes)
            strips = [[bme_midpoint(bme) for bme in strip] for strip in strips]
            cycles = [[bme_midpoint(bme) for bme in cycle] for cycle in cycles]
            self.selected_boundaries = (strips, cycles)

        # draw info about each selected boundary strip
        for (lbl, boundaries) in zip(['Strip', 'Cycle'], self.selected_boundaries):
            for boundary in boundaries:
                mid = sum(boundary, Vector((0,0,0))) / len(boundary)
                midpt = min(boundary, key=lambda pt:(pt-mid).length)
                pos = location_3d_to_region_2d(rgn, r3d, M @ midpt)
                if not pos: continue
                text = f'{lbl}: {len(boundary)}'
                tw, th = Drawing.get_text_width(text), Drawing.get_text_height(text)
                pos -= Vector((tw / 2, -th / 2))
                Drawing.text_draw2D(text, pos.xy, color=(1,1,0,1), dropshadow=(0,0,0,0.75))


class RFTool_Contours(RFTool_Base):
    bl_idname = "retopoflow.contours"
    bl_label = "RetopoFlow Contours"
    bl_description = "Retopologize cylindrical forms, like arms and legs"
    bl_icon = get_path_to_blender_icon('contours')
    bl_widget = None
    bl_operator = 'retopoflow.contours'

    # rf_brush = RFBrush_Contours()

    bl_keymap = chain_rf_keymaps(
        RFOperator_Contours,
        RFOperator_Translate_BoundaryLoop,
    )

    def draw_settings(context, layout, tool):
        props = tool.operator_properties(RFOperator_Contours.bl_idname)
        if context.region.type == 'TOOL_HEADER':
            layout.label(text='Cut:')
            layout.prop(props, 'initial_cut_count')
        else:
            header, panel = layout.panel(idname='contours_cut_panel', default_closed=False)
            header.label(text="Cut")
            if panel:
                panel.prop(props, 'initial_cut_count')

    @classmethod
    def activate(cls, context):
        cls.reseter = Reseter('Contours')
        cls.reseter['context.tool_settings.use_mesh_automerge'] = False
        cls.reseter['context.tool_settings.snap_elements_individual'] = {'FACE_NEAREST'}
        bpy.ops.retopoflow.contours_overlay('INVOKE_DEFAULT')

    @classmethod
    def deactivate(cls, context):
        cls.reseter.reset()
