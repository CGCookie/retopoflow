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
from ..common.viewport import update_retopo_overlay
from ..rfoperators.mirror import update_nodes_preview, update_mirror_mod


class RFProps_Scene(bpy.types.PropertyGroup):
    """
    These are properties that are more general than individual tool settings
    but make sense to change from scene to scene and not save as a preference. 
    E.G. scenes of different scales would require different merge thresholds.
    """

    """ Saving """
    saved_tool: bpy.props.StringProperty(
        name='RetopoFlow Tool',
        description='RetopoFlow Tool to select after loading from file',
    )

    """ Display """
    retopo_offset: bpy.props.FloatProperty(
        name='Retopology Offset',
        description=(
            "Controls the size of Blender's retopology overlay (how much it pokes through the mesh)"
            " and some of Retopoflow's effects that are based on it"
        ),
        min=0,
        #soft_max=1,
        max=10,
        default=0.01,
        precision=3,
        step=0.001,
        subtype='DISTANCE',
        update=lambda self, context: update_retopo_overlay(context)
    )
    override_default_offset: bpy.props.BoolProperty(
        default=True
    )

    """ Cleaning """
    #region
    cleaning_use_snap: bpy.props.BoolProperty(
        name='Snap to Surface',
        description='Snaps the vertices to the visible source objects',
        default=True
    )
    cleaning_use_merge: bpy.props.BoolProperty(
        name='Merge by Distance',
        description="Finds groups of vertices closer than the threshold and merges them together",
        default=True
    )
    cleaning_merge_threshold: bpy.props.FloatProperty(
        name='Merge Threshold',
        description="Vertices less than this distance from each other will get merged together",
        precision=4,
        default=0.0001,
        step=0.1,
        min=0
    )
    cleaning_use_delete_loose: bpy.props.BoolProperty(
        name='Delete Loose Verts',
        description="Deletes vertices not connected to any edges",
        default=True
    )
    cleaning_use_delete_faceless: bpy.props.BoolProperty(
        name='Delete Faceless Edges',
        description="Deletes Edges that have no faces",
        default=True
    )
    cleaning_use_delete_interior: bpy.props.BoolProperty(
        name='Delete Interior Faces',
        description="Deletes faces that are inside manifold geometry",
        default=False
    )
    cleaning_use_delete_ngons: bpy.props.BoolProperty(
        name='Delete N-Gons',
        description="Deletes faces that have more than four sides",
        default=False
    )
    cleaning_use_fill_holes: bpy.props.BoolProperty(
        name='Fill Holes',
        description="Fills boundary edges with faces",
        default=True
    )
    cleaning_use_recalculate_normals: bpy.props.BoolProperty(
        name='Recalculate Normals',
        description="Computes an “outside” normal",
        default=True
    )
    cleaning_flip_normals: bpy.props.BoolProperty(
        name='Flip Normals',
        description="Flips the normals after they are recalculated",
        default=False
    )
    cleaning_use_triangulate_concave: bpy.props.BoolProperty(
        name='Triangulate Concave Faces',
        description="Splits concave faces so that all resulting faces are convex",
        default=False
    )
    cleaning_use_triangulate_nonplanar: bpy.props.BoolProperty(
        name='Triangulate Non-Planar Faces',
        description="Splits faces that are not flat",
        default=False
    )
    cleaning_use_triangulate_ngons: bpy.props.BoolProperty(
        name='Triangulate N-gons',
        description="Splits n-gons, into quads if possible",
        default=False
    )
    #endregion

    """ Mirror """
    #region
    mirror_display: bpy.props.EnumProperty(
        name='Display',
        description='How the mirrored geometry is previewed',
        items=[
            ('NONE', 'None', 'The mirrored geometry is not previewed'),
            ('APPLIED', 'Applied', 'The mirrored geometry is displayed as applied to the vertices'),
            ('WIRE', 'Wire', 'The mirrored geometry is overlaid as a wireframe'),
            ('SOLID', 'Solid', 'The mirrored geometry is overlaid as a solid object'),
        ],
        default='APPLIED',
        update=lambda self, context: update_mirror_mod(context)
    )
    mirror_displace: bpy.props.FloatProperty(
        name='Displace',
        description=(
            'Displaces non-boundary vertices as a factor of the retopology overlay distance for better visibility.'
            ' If the effect is too extreme, you likely need to reduce the retopology overlay distance instead.'
        ),
        min=0,
        max=1,
        default=1,
        update=lambda self, context: update_nodes_preview(context)
    )
    mirror_displace_boundaries: bpy.props.BoolProperty(
        name='Displace Boundaries',
        description='Include mesh boundaries in the displacement',
        default=True,
        update=lambda self, context: update_nodes_preview(context)
    )
    mirror_displace_connected: bpy.props.BoolProperty(
        name='Displace Connected',
        description='Include vertices connected to the original mesh (usually along the center line) in the displacement',
        default=False,
        update=lambda self, context: update_nodes_preview(context)
    )
    mirror_wires: bpy.props.BoolProperty(
        name='Wireframe',
        description='Displays the wireframe on top of the mirrored geometry',
        default=True,
        update=lambda self, context: update_nodes_preview(context)
    )
    mirror_wire_thickness: bpy.props.FloatProperty(
        name='Wire Thickness',
        description='Size of the wireframe display in world space',
        default=0.2,
        min=0.2,
        max=50,
        update=lambda self, context: update_nodes_preview(context)
    )
    mirror_opacity: bpy.props.FloatProperty(
        name='Opacity',
        description='Controls how solid or transparent the mirror preview is',
        default=0.5,
        min=0,
        max=1,
        update=lambda self, context: update_nodes_preview(context)
    )


def register():
    bpy.utils.register_class(RFProps_Scene)
    bpy.types.Scene.retopoflow = bpy.props.PointerProperty(type=RFProps_Scene)

def unregister():
    bpy.utils.unregister_class(RFProps_Scene)