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
from ..common.sources import draw_hard_surface_snapping


def draw_snapping_options(context, layout, *, guide_loops: bool = False):
    layout.use_property_split = True
    layout.use_property_decorate = False
    snapping = context.scene.retopoflow.snapping

    layout.prop(snapping, 'snap_object', text='Only Include')
    col = layout.column()
    col.enabled = snapping.snap_object is None
    col.prop(snapping, 'snap_collection', text=' ')
    col.prop(snapping, 'snap_only_selected', text='Selected')
    col.prop(context.tool_settings, 'use_snap_selectable', text='Selectable')
    layout.separator(factor=0.5)

    layout.column().prop(snapping, 'projection', text='Projection', expand=False)
    show_steps = snapping.projection == 'WORLD_SPACE' or snapping.projection == 'FOLLOW_BLENDER'
    if show_steps:
        row = layout.row()
        row.enabled = snapping.projection == 'WORLD_SPACE' or 'FACE_NEAREST' in context.scene.tool_settings.snap_elements_individual
        row.prop(context.scene.tool_settings, 'snap_face_nearest_steps', text='Steps')

    layout.use_property_split = False
    split = layout.split(factor=0.4)
    col = split.column()
    col.alignment = 'RIGHT'
    col.label(text='Also Snap To')
    row = split.split(align=True)
    row.prop(snapping, 'snap_vertex',             text='', icon='SNAP_VERTEX',        toggle=True, expand=True)
    row.prop(snapping, 'snap_edge',               text='', icon='SNAP_EDGE',          toggle=True, expand=True)
    row.prop(snapping, 'snap_edge_center',        text='', icon='SNAP_MIDPOINT',      toggle=True, expand=True)
    row.prop(snapping, 'snap_edge_perpendicular', text='', icon='SNAP_PERPENDICULAR', toggle=True, expand=True)
    if bpy.app.version >= (5, 1, 0):
        row.prop(snapping, 'snap_face_center',    text='', icon='SNAP_FACE_CENTER',   toggle=True, expand=True)
    layout.use_property_split = True

    if (
        snapping.snap_vertex or snapping.snap_edge or snapping.snap_edge_center
        or snapping.snap_edge_perpendicular or snapping.snap_face_center
    ):
        layout.column().prop(context.scene.tool_settings, 'snap_target', text='From', expand=True)

    # tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
    # if tool.idname not in ['retopoflow.relax', 'retopoflow.tweak']:
    #     return
    feat_header, feat_panel = layout.panel(idname='RF_feature_detection', default_closed=False)
    feat_header.label(text='Brush Feature Detection')
    if feat_panel:
        props = context.scene.retopoflow.snapping
        feat_panel.use_property_split = True
        feat_panel.use_property_decorate = False
        draw_hard_surface_snapping(feat_panel, props, guide_loops=guide_loops)


def draw_snapping_panel(context, layout, *, idname: str, guide_loops: bool = False):
    header, panel = layout.panel(idname=idname, default_closed=True)
    header.label(text='Snapping')
    if panel:
        draw_snapping_options(context, panel, guide_loops=guide_loops)


class RFMenu_PT_Snapping(bpy.types.Panel):
    bl_label = 'Snapping'
    bl_idname = 'RF_PT_Snapping'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 12

    def draw(self, context):
        draw_snapping_options(context, self.layout, guide_loops=True)


def register():
    bpy.utils.register_class(RFMenu_PT_Snapping)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_Snapping)
