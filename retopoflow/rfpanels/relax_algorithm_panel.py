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
from ..common.interface import draw_section_header, draw_section_indent


def draw_relax_algo_options(context, layout, props=None):
    if props is None:
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH')
        props = tool.operator_properties(tool.idname)

    layout.use_property_split = True
    layout.use_property_decorate = False

    layout.row(heading="Smooth").prop(props, 'algorithm_laplacian', text='Vertices')
    layout.row(heading="Average").prop(props, 'algorithm_average_edge_lengths', text='Edges')
    layout.row(heading="Straighten").prop(props, 'algorithm_straighten_edges', text='Edges')
    layout.row(heading="Equalize").prop(props, 'algorithm_equalize_faces',  text='Faces')
    layout.row(heading="Correct").prop(props, 'algorithm_correct_flipped_faces', text='Flipped Faces')

    layout.separator()
    layout.row().prop(props, 'algorithm_method', expand=False, text='Integration')
    if props.algorithm_method == 'STEPS':
        layout.prop(props, 'algorithm_iterations', text="Iterations")
    layout.separator()

    header, panel = layout.panel(idname='relax_panel_algo_limits', default_closed=True)
    header.label(text='Limit Distance')
    if panel:
        panel.prop(props, 'algorithm_max_distance_radius', text="Brush Radius")
        panel.prop(props, 'algorithm_max_distance_edges',  text="Edge Length")
        panel.row(heading='Prevent').prop(props, 'algorithm_prevent_bounce', text='Bounce')

def draw_relax_algo_panel(context, layout, props=None, *, default_closed=False):
    header, panel = layout.panel(idname='relax_panel_algo', default_closed=default_closed)
    header.label(text="Algorithm")
    if panel:
        draw_relax_algo_options(context, panel, props)


def _relax_tool_props(context):
    """ Relax's operator properties, or None when Relax's own UI already covers them. """
    # The values live in Relax_Algorithm_Settings and RFBrush_Relax, which is what makes them
    # reachable at all: a tool reference only stores its own tool's settings. This is just a
    # pointer to draw them against.
    ws = context.workspace
    tool = ws.tools.from_space_view3d_mode('EDIT_MESH', create=False) if ws else None
    if not tool or tool.idname == 'retopoflow.relax': return None
    return tool.operator_properties('retopoflow.relax') or None


def draw_relax_options_all(context, layout, props):
    """ Shared by the sidebar panel and the header popover. """
    from ..rftool_relax.relax import draw_relax_options

    # the standalone operator's own settings, which the brush has no equivalent for
    op_props = context.window_manager.operator_properties_last('retopoflow.relax_selected')
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = False
    col.prop(op_props, 'shaping')
    col.prop(op_props, 'iterations')

    col = layout.column(align=True)
    draw_relax_algo_options(context, col, props)

    header, panel = layout.panel(idname='relax_panel_brush', default_closed=True)
    header.label(text="Relax Brush")
    if panel:
        draw_relax_options(context, panel, props)

    row = layout.row()
    draw_section_indent(context, row)
    row.operator('retopoflow.relax_selected', text='Relax Selected')
    row.operator('retopoflow.space_evenly', text='Even Selected')
    layout.separator()


def draw_relax_panel(context, layout):
    props = _relax_tool_props(context)
    if not props: return

    header, panel = layout.panel(idname='relax_panel', default_closed=True)
    header.label(text='Relax')
    # collapsed, the header carries the run button the open panel keeps at its bottom
    if not panel:
        sub = header.row(align=True)
        sub.alignment = 'RIGHT'
        sub.operator('retopoflow.relax_selected', text='', icon='TRIA_RIGHT')
    if panel:
        draw_relax_options_all(context, panel, props)


def draw_relax_popover(context, layout):
    if not _relax_tool_props(context): return
    row = layout.row(align=True)
    row.popover('RF_PT_Relax', text='Relax')
    row.operator('retopoflow.relax_selected', text='', icon='TRIA_RIGHT')


class RFMenu_PT_Relax(bpy.types.Panel):
    bl_label = "Relax"
    bl_idname = "RF_PT_Relax"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_ui_units_x = 12

    def draw(self, context):
        props = _relax_tool_props(context)
        if not props: return
        draw_relax_options_all(context, self.layout, props)

class RFMenu_PT_RelaxAlgorithm(bpy.types.Panel):
    bl_label = "Algorithm"
    bl_idname = "RF_PT_RelaxAlgorithm"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        draw_relax_algo_options(context, self.layout)

def register():
    bpy.utils.register_class(RFMenu_PT_Relax)
    bpy.utils.register_class(RFMenu_PT_RelaxAlgorithm)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_Relax)
    bpy.utils.unregister_class(RFMenu_PT_RelaxAlgorithm)