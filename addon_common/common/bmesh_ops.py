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
from bmesh.types import (
    BMVert, BMEdge, BMFace, BMesh,
    BMLayerAccessVert, BMLayerAccessEdge, BMLayerAccessFace,
    BMLayerItem
)


BMElemType = type[BMVert] | type[BMEdge] | type[BMFace]
BMElem = BMVert | BMEdge | BMFace
BMLayer = BMLayerAccessVert | BMLayerAccessEdge | BMLayerAccessFace


def get_layer(bm : BMesh, bmelem_type : BMElemType, layer_type : str, name : str) -> BMLayer:
    # https://docs.blender.org/api/current/bmesh.types.html#bmesh.types.bmesh.types.BMLayerAccessVert
    # BMVert has extra layer types: deform, shape, skin
    assert layer_type in { 'bool', 'color', 'float', 'float_color', 'float_vector', 'int', 'string' }, f'get_layer: Unhandled layer_type {layer_type}'
    assert bmelem_type in { BMVert, BMEdge, BMFace }, f'get_layer: Unhandled bmelem_type {bmelem_type}'
    layer = {
        BMVert: getattr(bm.verts.layers, layer_type),
        BMEdge: getattr(bm.edges.layers, layer_type),
        BMFace: getattr(bm.faces.layers, layer_type),
    }[bmelem_type]
    if name not in layer: layer.new(name)
    return layer.get(name)


def get_select_layers(bm) -> tuple[BMLayerItem, BMLayerItem, BMLayerItem]:
    if 'rf_vert_select_after_move' not in bm.verts.layers.int:
        bm.verts.layers.int.new('rf_vert_select_after_move')
    if 'rf_edge_select_after_move' not in bm.edges.layers.int:
        bm.edges.layers.int.new('rf_edge_select_after_move')
    if 'rf_face_select_after_move' not in bm.faces.layers.int:
        bm.faces.layers.int.new('rf_face_select_after_move')
    layer_sel_vert = bm.verts.layers.int.get('rf_vert_select_after_move')
    layer_sel_edge = bm.edges.layers.int.get('rf_edge_select_after_move')
    layer_sel_face = bm.faces.layers.int.get('rf_face_select_after_move')
    return (layer_sel_vert, layer_sel_edge, layer_sel_face)



def get_all_selected(bm : BMesh) -> dict[BMElemType, set[BMVert]|set[BMEdge]|set[BMFace]]:
    return {
        BMVert: get_all_selected_bmverts(bm),
        BMEdge: get_all_selected_bmedges(bm),
        BMFace: get_all_selected_bmfaces(bm),
    }

def any_selected_bmverts(bm : BMesh) -> bool:
    return any(
        bmv.select and not bmv.hide
        for bmv in bm.verts
    )

def get_all_selected_bmverts(bm : BMesh) -> set[BMVert]:
    return { bmv for bmv in bm.verts if bmv.select and not bmv.hide }
def get_all_selected_bmedges(bm : BMesh) -> set[BMEdge]:
    return { bme for bme in bm.edges if bme.select and not bme.hide }
def get_all_selected_bmfaces(bm : BMesh) -> set[BMFace]:
    return { bmf for bmf in bm.faces if bmf.select and not bmf.hide }

def deselect_all(bm):
    bm.select_history.clear()
    for bmv in bm.verts: bmv.select_set(False)
def select_set(bm, bmelem, selected):
    if not bmelem: return
    if selected: select(bm, bmelem)
    else: deselect(bm, bmelem)
def select(bm, bmelem):
    if not bmelem: return
    bm.select_history.add(bmelem)
    bmelem.select_set(True)
def deselect(bm, bmelem):
    if not bmelem: return
    bm.select_history.discard(bmelem)
    bmelem.select_set(False)
def reselect(bm, bmelem):
    if not bmelem: return
    deselect(bm, bmelem)
    select(bm, bmelem)

def deselect_iter(bm, bmelems):
    for bmelem in bmelems:
        deselect(bm, bmelem)
def select_iter(bm, bmelems):
    for bmelem in bmelems:
        select(bm, bmelem)

def select_later_iter(bm, bmelems):
    layer_sel_vert, layer_sel_edge, layer_sel_face = get_select_layers(bm)
    for bmelem in bmelems:
        match bmelem:
            case BMVert():
                bmelem[self.layer_sel_vert] = 1
            case BMEdge():
                bmelem[self.layer_sel_edge] = 1
                for bmv in bmelem.verts:
                    bmv[self.layer_sel_vert] = 1
            case BMFace():
                bmelem[self.layer_sel_face] = 1
                for bmv in bmelem.verts:
                    bmv[self.layer_sel_vert] = 1

def flush_selection(bm, emesh):
    bm.select_flush(True)
    bm.select_flush(False)
    bmesh.update_edit_mesh(emesh)

def shared_link_edges(bmvs):
    bmes = None
    for bmv in bmvs:
        if bmes is None:
            bmes = set(bmv.link_edges)
        else:
            bmes &= set(bmv.link_edges)
    return bmes

def shared_link_faces(bmvs):
    bmfs = None
    for bmv in bmvs:
        if bmfs is None:
            bmfs = set(bmv.link_faces)
        else:
            bmfs &= set(bmv.link_faces)
    return bmfs
