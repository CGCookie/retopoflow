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
        component: Literal['verts', 'edges', 'faces', 'auto'] = 'auto', 
        objects: list[Object] = [], 
        is_bmesh: bool = False
    ):
    selected = {} # {'object_name': {'verts': [], 'edges': [], 'faces': []} }

    if not objects:
        objects = [context.active_object]

    if component == 'auto':
        if context.tool_settings.mesh_select_mode[:][0]:
            component = 'verts'
        elif context.tool_settings.mesh_select_mode[:][1]:
            component = 'edges'
        else:
            component = 'faces'

    for obj in objects:
        if not is_bmesh:
            bm = bmesh.from_edit_mesh(obj.data)

        if obj.name not in selected.keys():
            selected[obj.name] = {'verts': [], 'edges': [], 'faces': []}
        
        if component == 'verts':
            {selected[obj.name]['verts'].append(x.index) for x in bm.verts if x.select}
            {selected[obj.name]['faces'].append(x.index) for x in bm.faces if x.select}
        elif component == 'edges':
            {selected[obj.name]['edges'].append(x.index) for x in bm.edges if x.select}
        elif component == 'faces':
            {selected[obj.name]['faces'].append(x.index) for x in bm.faces if x.select}

        if not is_bmesh:
            bm.free()

    return selected


def restore_selected(
        context,
        selection: dict[str, dict[Literal['verts', 'edges', 'faces', 'auto'], list]],
        objects: list[Object] = [],
        is_bmesh = False,
    ):

    if not objects:
        objects = [context.active_object]

    bpy.ops.mesh.select_all(False, action='DESELECT')

    for obj in objects:
        if (
            not selection[obj.name]['verts'] and
            not selection[obj.name]['edges'] and
            not selection[obj.name]['faces']
        ):
            # Saves a bmesh conversion if not needed
            continue

        if not is_bmesh:
            bm = bmesh.from_edit_mesh(obj.data)

        if selection[obj.name]['verts']:
            components = selection[obj.name]['verts']
            bm.verts.ensure_lookup_table()
            for idx in components:
                bm.verts[idx].select_set(True)
        if selection[obj.name]['edges']:
            components = selection[obj.name]['edges']
            bm.edges.ensure_lookup_table()
            for idx in components:
                bm.edges[idx].select_set(True)
        if selection[obj.name]['faces']:
            components = selection[obj.name]['faces']
            bm.faces.ensure_lookup_table()
            for idx in components:
                bm.faces[idx].select_set(True)

        if not is_bmesh:
            bm.free()
