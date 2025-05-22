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

import os, bpy


def append_path(file_name, data_type):
    return bpy.path.native_pathsep(os.path.join(
        os.path.dirname(__file__), '..', '..', 'assets', f"{file_name}\\{data_type}\\"
    ))

  
def append_node(node_tree_name, nodes=None, is_geo_node=True):
    if any(x.name == node_tree_name for x in bpy.data.node_groups):
        # No need to append if it already exists
        appended_group = bpy.data.node_groups[node_tree_name]
    else:
        initial_nodetrees = set(bpy.data.node_groups)
        bpy.ops.wm.append(filename=node_tree_name, directory=append_path('nodes.blend', 'NodeTree'))
        appended_nodetrees = set(bpy.data.node_groups) - initial_nodetrees
        appended_group = [x for x in appended_nodetrees if node_tree_name in x.name][0]

    if nodes:
        if is_geo_node:
            node_group = nodes.new("GeometryNodeGroup")
        else:
            node_group = nodes.new("ShaderNodeGroup")
        node_group.node_tree = bpy.data.node_groups[appended_group.name]
        node_group.node_tree.name = node_tree_name
        node_group.name = node_tree_name
        return node_group
    else:
        return appended_group