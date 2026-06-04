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
from ..common.interface import draw_section_header


def draw_relax_algo_options(context, layout):
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

    header, panel = layout.panel(idname='relax_panel_source_edges', default_closed=False)
    header.label(text='Hard Surface Snapping')
    if panel:
        panel.row(heading="Sources").prop(props, 'snap_to_source_features',  text='Detect Features')
        col = panel.column(align=False)
        col.enabled = props.snap_to_source_features
        col.prop(props, 'source_edge_angle', text='Angle')
        col.row(heading='Include').prop(props, 'source_edge_creases', text='Creases')
        col.prop(props, 'source_edge_seams', text='Seams')
        col.prop(props, 'source_edge_sharps', text='Sharps')
        col.prop(props, 'source_edge_proximity', text='Proximity')
        col.prop(props, 'source_edge_stickiness', text='Stickiness', slider=True)
        col.prop(props, 'source_edge_guide_loops', text='Guide Loops', slider=True)
        col.prop(props, 'source_edge_debug_loops', text='Highlight')

    header, panel = layout.panel(idname='relax_panel_algo_limits', default_closed=True)
    header.label(text='Limit Distance')
    if panel:
        panel.prop(props, 'algorithm_max_distance_radius', text="Brush Radius")
        panel.prop(props, 'algorithm_max_distance_edges',  text="Edge Length")
        panel.row(heading='Prevent').prop(props, 'algorithm_prevent_bounce', text='Bounce')

def draw_relax_algo_panel(context, layout):
    header, panel = layout.panel(idname='relax_panel_algo', default_closed=False)
    header.label(text="Algorithm")
    if panel:
        draw_relax_algo_options(context, panel)

class RFMenu_PT_RelaxAlgorithm(bpy.types.Panel):
    bl_label = "Algorithm"
    bl_idname = "RF_PT_RelaxAlgorithm"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw(self, context):
        draw_relax_algo_options(context, self.layout)

def register():
    bpy.utils.register_class(RFMenu_PT_RelaxAlgorithm)

def unregister():
    bpy.utils.unregister_class(RFMenu_PT_RelaxAlgorithm)