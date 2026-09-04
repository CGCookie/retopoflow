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

from ..common.accel import SourceCache, SourceMeshCache


def draw_source_build_button(layout, cached_names):
    if SourceCache.building:
        row = layout.row(align=True)
        pct = SourceCache.progress * 100.0
        if hasattr(row, 'progress'):
            row.progress(factor=SourceCache.progress, text=f'Building cache… {pct:.0f}%', type='BAR')
        else:
            row.label(text=f'Building cache… {pct:.0f}%')
        row.operator('retopoflow.cancel_source_cache_rebuild', text='', icon='X')
    else:
        button_text = 'Rebuild Source Cache' if cached_names else 'Build Source Cache'
        layout.operator('retopoflow.rebuild_source_cache', text=button_text, icon='FILE_REFRESH')


def draw_source_cache_controls(context, layout):
    feat_names = set(SourceCache.cached_object_names())
    walk_names = set(SourceMeshCache.cached_object_names())
    all_names  = sorted(feat_names | walk_names)
    snapping = context.scene.retopoflow.snapping

    header, panel = layout.panel(idname='RF_source_cache', default_closed=True)
    header.label(text='Source Cache')
    if not panel:
        header.operator('retopoflow.rebuild_source_cache', text='', icon='FILE_REFRESH')
        header.separator()
    if panel:
        panel.prop(snapping, 'source_feature_auto_rebuild', text='Auto Rebuild')
        # panel.prop(snapping, 'source_feature_batch_power', text='Chunk Size')
        # row = panel.row()
        # row.alignment = 'RIGHT'
        # power = int(getattr(snapping, 'source_feature_batch_power', 3))
        # row.label(text=f'{12 ** power:,} verts per frame')

        panel.separator()
        draw_source_build_button(panel, all_names)

        if all_names:
            col = panel.column(align=True)
            col.separator(type='LINE')
            col.separator()
            for obj_name in all_names:
                row = col.row(align=True)
                row.use_property_split=False
                split = row.split(factor=0.4)
                split.label(text=obj_name, icon='OBJECT_DATA')
                sub = split.row()
                tags: list[str] = []
                if obj_name in feat_names:
                    tags.extend(SourceCache.cached_types_for_object(obj_name))
                if obj_name in walk_names:
                    tags.append('Contours')
                if tags:
                    tagline = sub.row()
                    tagline.enabled=False
                    tagline.alignment='RIGHT'
                    tagline.label(text=' · '.join(tags))
                op = sub.operator('retopoflow.evict_source_cache_object', text='', icon='X')
                op.obj_name = obj_name
            col.separator()


def draw_hard_surface_snapping(layout, context, props, guide_loops:bool=False, show_cache_controls:bool=False):
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
    split = col2.split(factor=0.4)
    row = split.row()
    row.alignment = 'RIGHT'
    row.label(text='Distance')
    row = split.row(align=True)
    row.prop(props, 'source_edge_use_fixed_distance', icon='FIXED_SIZE', text='')
    if getattr(props, 'source_edge_use_fixed_distance', False):
        row.prop(props, 'source_edge_fixed_distance', text='')
    else:
        row.prop(props, 'source_edge_proximity', text='')

    col2.prop(props, 'source_edge_stickiness', text='Stickiness', slider=True)
    if guide_loops:
        col2.prop(props, 'source_edge_guide_loops', text='Guide Loops', slider=True)
    if not show_cache_controls: return # For displaying in redo panel for general tools that don't use the cache
    draw_source_cache_controls(context, layout)


def draw_native_snapping_options(context, layout):
    snapping = context.scene.retopoflow.snapping
    layout.use_property_split = False
    split = layout.split(factor=0.4)
    col = split.column()
    col.alignment = 'RIGHT'
    col.label(text='Also Snap To')
    split = split.split(align=True)
    split.prop(snapping, 'snap_vertex',             text='', icon='SNAP_VERTEX',        toggle=True, expand=True)
    row = split.column()
    row.enabled = snapping.snap_vertex
    row.prop(snapping, 'snap_edge',               text='', icon='SNAP_EDGE',          toggle=True, expand=True)
    row = split.column()
    row.enabled = snapping.snap_vertex
    row.prop(snapping, 'snap_edge_center',        text='', icon='SNAP_MIDPOINT',      toggle=True, expand=True)
    row = split.column()
    row.enabled = snapping.snap_vertex
    row.prop(snapping, 'snap_edge_perpendicular', text='', icon='SNAP_PERPENDICULAR', toggle=True, expand=True)
    if bpy.app.version >= (5, 1, 0):
        row = split.column()
        row.enabled = snapping.snap_vertex
        row.prop(snapping, 'snap_face_center',    text='', icon='SNAP_FACE_CENTER',   toggle=True, expand=True)
    layout.use_property_split = True

    if (
        snapping.snap_vertex or snapping.snap_edge or snapping.snap_edge_center
        or snapping.snap_edge_perpendicular or snapping.snap_face_center
    ):
        layout.column().prop(context.scene.tool_settings, 'snap_target', text='From', expand=True)


def draw_snapping_options(context, layout, *, guide_loops: bool = False):
    layout.use_property_split = True
    layout.use_property_decorate = False
    snapping = context.scene.retopoflow.snapping

    layout.column().prop(snapping, 'projection', text='Projection', expand=True)
    # show_steps = snapping.projection != 'SCREEN_SPACE'
    # if show_steps:
    row = layout.row()
    row.enabled = snapping.projection != 'SCREEN_SPACE' or 'FACE_NEAREST' in context.scene.tool_settings.snap_elements_individual
    row.prop(context.scene.tool_settings, 'snap_face_nearest_steps', text='Steps')

    draw_native_snapping_options(context, layout)
    use_native = (
        snapping.snap_vertex or snapping.snap_edge or snapping.snap_edge_center
        or snapping.snap_edge_perpendicular or snapping.snap_face_center
    )
    # layout.separator(factor=0.5)

    if not use_native:
        layout.prop(snapping, 'snap_object', text='Only Include')
        col = layout.column()
        col.enabled = snapping.snap_object is None
        col.prop(snapping, 'snap_collection', text=' ')
        col.prop(snapping, 'snap_only_selected', text='Selected')
        col.prop(context.tool_settings, 'use_snap_selectable', text='Selectable')
        layout.row(heading='Normals').prop(snapping, 'correct_face_normals', text='Correct')
    else:
        layout.row(heading='Only Include').prop(context.tool_settings, 'use_snap_selectable', text='Selectable')
    layout.separator(factor=0.5)

    if not use_native:
        # tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        # if tool.idname not in ['retopoflow.relax', 'retopoflow.tweak']:
        #     return
        layout.separator()
        feat_header, feat_panel = layout.panel(idname='RF_feature_detection', default_closed=True)
        feat_header.label(text='Source Feature Detection (Experimental)')
        if feat_panel:
            props = context.scene.retopoflow.snapping
            row = feat_panel.row()
            row.use_property_split = False
            row.alignment = 'CENTER'
            row.label(text='Enabling in heavy scenes is very slow', icon='ERROR')
            feat_panel.use_property_split = True
            feat_panel.use_property_decorate = False
            draw_hard_surface_snapping(feat_panel, context, props, guide_loops, show_cache_controls=True)


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
