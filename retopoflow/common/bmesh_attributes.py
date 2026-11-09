'''
Copyright (C) 2026 CG Cookie
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

from collections.abc import Iterable
from enum import IntEnum, auto
from typing import Any

from bmesh.types import BMesh, BMVert, BMEdge, BMFace

from ..rfoperators.pinning import fix_interpolated_pin


class BMMarking(IntEnum):
    seam = auto()
    sharp = auto()
    crease = auto()

def is_bmedge_edgemark(bm:BMesh, bme:BMEdge, mark:BMMarking):
    match mark:
        case BMMarking.seam:
            return getattr(bme, 'seam')
        case BMMarking.sharp:
            return not getattr(bme, 'smooth')
        case BMMarking.crease:
            layer = bm.edges.layers.float.get('crease_edge')
            if not layer: return False
            return bme[layer]
    return False

def is_bmvert_on_edgemark(bm:BMesh, bmv:BMVert, mark:BMMarking) -> bool:
    match mark:
        case BMMarking.seam:
            return any( getattr(bme, 'seam') for bme in bmv.link_edges )
        case BMMarking.sharp:
            return not all( getattr(bme, 'smooth') for bme in bmv.link_edges )
        case BMMarking.crease:
            layer = bm.edges.layers.float.get('crease_edge')
            if not layer: return False
            return any( bme[layer] for bme in bmv.link_edges )
    return False


def is_bmvert_pinned(bm : BMesh, bmv: BMVert, *, ensure_lookup_table: bool = True) -> bool:
    return get_bmvert_attribute(bm, bmv, 'retopoflow_pins', 'float', ensure_lookup_table=ensure_lookup_table)

def is_bmvert_creased(bm : BMesh, bmv : BMVert, *, ensure_lookup_table: bool = True) -> bool:
    return get_bmvert_attribute(bm, bmv, 'crease_vert', 'float', ensure_lookup_table=ensure_lookup_table)


def get_bmvert_attribute(bm:BMesh, bmv:BMVert, attribute:str, data_type:str, *, ensure_lookup_table: bool = True) -> Any:  # pyright: ignore[reportExplicitAny, reportAny]
    # Callers that have already ensured the lookup table (e.g. when filtering many verts
    # in a tight loop) can pass ensure_lookup_table=False to skip this per-vert call.
    if ensure_lookup_table:
        bm.verts.ensure_lookup_table()
    layer = getattr(bm.verts.layers, data_type).get(attribute) # pyright: ignore[reportAny]
    if layer:
        return bmv[layer]  # pyright: ignore[reportAny]
    else:
        return None


def interp_bmvert_from_bmverts(bm : BMesh, bmv : BMVert, bmv0 : BMVert, bmv1 : BMVert):
    ''' Interpolate the attributes of `bmv`, which sits on or near the edge between `bmv0` and `bmv1`. '''
    d0, d1 = (bmv.co - bmv0.co).length, (bmv.co - bmv1.co).length
    fac = d0 / (d0 + d1) if d0 + d1 > 0 else 0.5
    # At exactly 0 or 1, Blender copies instead of interpolating, and the copy invalidates bmv's python reference
    fac = min(max(fac, 1e-6), 1 - 1e-6)
    bmv.copy_from_vert_interp((bmv0, bmv1), fac)
    fix_interpolated_pin(bm, bmv, (bmv0, bmv1))

def interp_bmvert_from_bmface(bm : BMesh, bmv : BMVert, bmf : BMFace):
    ''' Interpolate the attributes of `bmv`, which sits inside `bmf`, from all of `bmf`'s verts. '''
    # copy_from_face_interp projects onto the face plane and newly created faces can have a zero normal
    bmf.normal_update()
    bmv.copy_from_face_interp(bmf)
    fix_interpolated_pin(bm, bmv, bmf.verts)

def replace_bmface(bm : BMesh, bmf : BMFace, bmvs_faces : list[list[BMVert]]) -> list[BMFace]:
    ''' Replace `bmf` with a face for each vert list in `bmvs_faces`, keeping `bmf`'s face and corner attributes. '''
    # faces.new copies face attributes such as smooth and material from the example, but leaves corner attributes such as UVs empty
    bmf.normal_update()
    bmfs_new = [bm.faces.new(bmvs, bmf) for bmvs in bmvs_faces]
    for bmf_new in bmfs_new:
        bmf_new.normal_update()
        for bml in bmf_new.loops:
            bml.copy_from_face_interp(bmf, False)  # False skips vert attributes, which are interpolated separately
    bm.faces.remove(bmf)
    return bmfs_new

def bme_has_attributes(bm : BMesh, bme : BMEdge) -> bool:
    ''' True when `bme` is a seam or sharp, or has any nonzero float, int or bool attribute such as crease. '''
    if bme.seam or not bme.smooth:
        return True
    layers = bm.edges.layers
    colls = [layers.float, layers.int, getattr(layers, 'bool', None)]  # bool layers are not in every supported Blender version
    return any(bme[layer] for coll in colls if coll for layer in coll.values())

def shade_new_bmfaces(bmfs : Iterable[BMFace | None], material_index : int):
    ''' Set smooth shading on new faces from the faces around them, and give them `material_index`. '''
    # Smooth when more of the faces touching their verts are smooth than flat.
    # Only faces outside the batch count, since the rest of the batch is new too.
    bmfs_new = { bmf for bmf in bmfs if bmf and bmf.is_valid }
    bmfs_near = { bmf_near for bmf in bmfs_new for bmv in bmf.verts for bmf_near in bmv.link_faces if bmf_near not in bmfs_new }
    smooth = sum(1 for bmf_near in bmfs_near if bmf_near.smooth) * 2 > len(bmfs_near)
    for bmf in bmfs_new:
        bmf.smooth = smooth
        bmf.material_index = material_index
