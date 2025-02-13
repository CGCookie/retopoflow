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

def draw_relax_algo_options(context, layout):
    tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH')
    props = tool.operator_properties(tool.idname)

    layout.use_property_split = True
    layout.use_property_decorate = False

    layout.prop(props, 'algorithm_iterations',            text="Iterations")
    layout.prop(props, 'algorithm_strength',              text="Strength")
    col = layout.column(heading="Average")
    col.prop(props, 'algorithm_average_edge_lengths',  text='Edge Lengths')
    col.prop(props, 'algorithm_average_face_radius',   text='Face Radius')
    col.prop(props, 'algorithm_average_face_angles',   text='Face Angles')
    col.prop(props, 'algorithm_average_face_lengths',  text='Face Lengths')
    col = layout.column(heading="Straighten")
    col.prop(props, 'algorithm_straighten_edges',      text='Edges')
    col = layout.column(heading="Correct")
    col.prop(props, 'algorithm_correct_flipped_faces', text='Flipped Faces')

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