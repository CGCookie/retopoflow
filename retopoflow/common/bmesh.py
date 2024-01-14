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


def get_bmesh_emesh(context):
    em = context.active_object.data
    bm = bmesh.from_edit_mesh(em)
    return (bm, em)

def get_select_layers(bm):
    if 'rf: select after move' not in bm.verts.layers.int:
        bm.verts.layers.int.new('rf: select after move')
    if 'rf: select after move' not in bm.edges.layers.int:
        bm.edges.layers.int.new('rf: select after move')
    if 'rf: select after move' not in bm.faces.layers.int:
        bm.faces.layers.int.new('rf: select after move')
    layer_sel_vert = bm.verts.layers.int.get('rf: select after move')
    layer_sel_edge = bm.edges.layers.int.get('rf: select after move')
    layer_sel_face = bm.faces.layers.int.get('rf: select after move')
    return (layer_sel_vert, layer_sel_edge, layer_sel_face)
