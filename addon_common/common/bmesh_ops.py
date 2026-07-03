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

from typing import cast, Literal, TypeAlias
from collections.abc import Sequence

from bpy.types import Mesh
import bmesh
from bmesh.types import (
    BMVert, BMEdge, BMFace, BMesh,
    BMVertSeq, BMEdgeSeq, BMFaceSeq,
    BMLayerCollection,
    BMLayerAccessVert, BMLayerAccessEdge, BMLayerAccessFace,
    BMLayerItem
)


BMElemType : TypeAlias = type[BMVert] | type[BMEdge] | type[BMFace]
BMElem : TypeAlias = BMVert | BMEdge | BMFace
BMLayer : TypeAlias = BMLayerAccessVert | BMLayerAccessEdge | BMLayerAccessFace
BMLayerType : TypeAlias = Literal[
    'bool',
    'color',
    'float',
    'float_color',
    'float_vector',
    'int',
    'string',

    # BMVert has extra layer types: deform, shape, skin
    # 'deform',
    # 'shape',
    # 'skin',
]
BMLayerCollection_General : TypeAlias = BMLayerCollection # pyright: ignore[reportMissingTypeArgument]

def get_layer(bm : BMesh, bmelem_type : BMElemType, layer_type : BMLayerType, name : str) -> BMLayerItem:
    # https://docs.blender.org/api/current/bmesh.types.html#bmesh.types.bmesh.types.BMLayerAccessVert
    assert layer_type in { 'bool', 'color', 'float', 'float_color', 'float_vector', 'int', 'string' }, f'get_layer: Unhandled layer_type {layer_type}'
    assert bmelem_type in { BMVert, BMEdge, BMFace }, f'get_layer: Unhandled bmelem_type {bmelem_type}'

    def getcollection(  # pyright: ignore[reportUnknownParameterType]
        seq : BMVertSeq | BMEdgeSeq | BMFaceSeq
    ) -> BMLayerCollection_General:
        return cast(  # pyright: ignore[reportUnknownVariableType]
            BMLayerCollection_General,
            getattr(seq.layers, layer_type)
        )

    match bmelem_type:
        case bmesh.types.BMVert:
            seq = bm.verts
        case bmesh.types.BMEdge:
            seq = bm.edges
        case bmesh.types.BMFace:
            seq = bm.faces
        case _:
            assert False, f'Unhandled bmesh element type {bmelem_type}'

    layer = getcollection(seq)  # pyright: ignore[reportUnknownVariableType]
    return (
        cast(BMLayerItem, layer.get(name))
        if name in layer else
        layer.new(name)
    )


def get_select_layers(bm : BMesh) -> tuple[BMLayerItem, BMLayerItem, BMLayerItem]:
    return (
        get_layer(bm, BMVert, 'int', 'rf_vert_select_after_move'),
        get_layer(bm, BMEdge, 'int', 'rf_edge_select_after_move'),
        get_layer(bm, BMFace, 'int', 'rf_face_select_after_move'),
    )



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

def deselect_all(bm : BMesh):
    bm.select_history.clear()
    for bmv in bm.verts:
        bmv.select_set(False)

def select_set(bm : BMesh, bmelem : BMElem, selected : bool):
    if bmelem:
        if selected:
            select(bm, bmelem)
        else:
            deselect(bm, bmelem)

def select(bm : BMesh, bmelem : BMElem | None):
    if bmelem:
        bm.select_history.add(bmelem)
        bmelem.select_set(True)

def deselect(bm : BMesh, bmelem : BMElem | None):
    if bmelem:
        bm.select_history.discard(bmelem)
        bmelem.select_set(False)

def reselect(bm : BMesh, bmelem : BMElem | None):
    if bmelem:
        deselect(bm, bmelem)
        select(bm, bmelem)

def deselect_iter(bm : BMesh, bmelems : Sequence[BMElem]):
    for bmelem in bmelems:
        deselect(bm, bmelem)

def select_iter(bm : BMesh, bmelems : Sequence[BMElem]):
    for bmelem in bmelems:
        select(bm, bmelem)

def select_later_iter(bm : BMesh, bmelems : Sequence[BMElem]):
    layer_sel_vert, layer_sel_edge, layer_sel_face = get_select_layers(bm)

    for bmelem in bmelems:
        match bmelem:
            case BMVert():
                bmelem[layer_sel_vert] = 1

            case BMEdge():
                bmelem[layer_sel_edge] = 1
                for bmv in bmelem.verts:
                    bmv[layer_sel_vert] = 1

            case BMFace():
                bmelem[layer_sel_face] = 1
                for bmv in bmelem.verts:
                    bmv[layer_sel_vert] = 1

def flush_selection(bm : BMesh, emesh : Mesh):
    bm.select_flush(True)
    bm.select_flush(False)
    bmesh.update_edit_mesh(emesh)

def shared_link_edges(bmvs : Sequence[BMVert]) -> set[BMEdge] | None:
    bmes = None
    for bmv in bmvs:
        if bmes is None:
            bmes = set(bmv.link_edges)
        else:
            bmes &= set(bmv.link_edges)
    return bmes

def shared_link_faces(bmvs : Sequence[BMVert]) -> set[BMFace] | None:
    bmfs = None
    for bmv in bmvs:
        if bmfs is None:
            bmfs = set(bmv.link_faces)
        else:
            bmfs &= set(bmv.link_faces)
    return bmfs
