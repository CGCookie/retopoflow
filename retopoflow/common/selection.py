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

import bpy, bmesh
from bpy.types import Context, Mesh, Object
from typing import Literal


def get_selected(
        context,
        objects: list[Object] = [], 
        bm: Object = None
    ):
    selected = {} # {'object_name': {'verts': [], 'edges': [], 'faces': []} }

    if not objects:
        objects = [context.active_object]

    for obj in objects:
        is_bmesh = bm != None
        if not is_bmesh:
            if context.mode == 'EDIT_MESH':
                bm = bmesh.from_edit_mesh(obj.data)
            else:
                bm = bmesh.from_mesh(obj.data)

        if obj.name not in selected.keys():
            selected[obj.name] = {'verts': [], 'edges': [], 'faces': []}
        
        bm.verts.index_update()
        bm.edges.index_update()
        bm.faces.index_update()
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        {selected[obj.name]['verts'].append(x.index) for x in bm.verts if x.select}
        {selected[obj.name]['edges'].append(x.index) for x in bm.edges if x.select}
        {selected[obj.name]['faces'].append(x.index) for x in bm.faces if x.select}

        if not is_bmesh:
            bm.free()

    return selected


def restore_selected(
        context,
        selection: dict[str, dict[Literal['verts', 'edges', 'faces'], list]],
        objects: list[Object] = [],
        bm: Object = None,
        skip: dict[str, dict[Literal['verts', 'edges', 'faces'], list]] = {'verts': [], 'edges': [], 'faces': []}
    ):

    if not objects:
        objects = [context.active_object]

    for obj in objects:
        if (
            not selection[obj.name]['verts'] and
            not selection[obj.name]['edges'] and
            not selection[obj.name]['faces']
        ):
            # Saves a bmesh conversion if not needed
            continue

        is_bmesh = bm != None
        if not is_bmesh:
            if context.mode == 'EDIT_MESH':
                bm = bmesh.from_edit_mesh(obj.data)
            else:
                bm = bmesh.new()
                bm.from_mesh(obj.data)

        {v.select_set(False) for v in bm.verts}
        {e.select_set(False) for e in bm.edges}
        {f.select_set(False) for f in bm.faces}

        if selection[obj.name]['verts']:
            components = selection[obj.name]['verts']
            bm.verts.ensure_lookup_table()
            for idx in components:
                if idx >= len(bm.verts) - 1: 
                    continue
                v = bm.verts[idx]
                if v.is_valid and v.index not in skip[obj.name]['verts']:
                    v.select_set(True)
        if selection[obj.name]['edges']:
            components = selection[obj.name]['edges']
            bm.edges.ensure_lookup_table()
            for idx in components:
                if idx >= len(bm.edges) - 1: 
                    continue
                e = bm.edges[idx]
                if e.is_valid and e.index not in skip[obj.name]['edges']:
                    e.select_set(True)
        if selection[obj.name]['faces']:
            components = selection[obj.name]['faces']
            bm.faces.ensure_lookup_table()
            for idx in components:
                if idx >= len(bm.faces) - 1: 
                    continue
                f = bm.faces[idx]
                if f.is_valid and f.index not in skip[obj.name]['faces']:
                    f.select_set(True)

        if not is_bmesh:
            if context.mode == 'EDIT_MESH':
                bmesh.update_edit_mesh(obj.data)
            else:
                bm.to_mesh(obj.data)
            bm.free()
