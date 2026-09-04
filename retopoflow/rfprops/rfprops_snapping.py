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

import math
import bpy
from ..common.accel import SourceCache


def on_source_obj_changed(self, context):
    SourceCache.mark_dirty_geometry_changed('source set changed')

def on_source_feature_changed(self, context):
    SourceCache.mark_dirty_settings_changed(context)

def on_snap_element_changed(prop_name, element):
    ''' Update callback for one snap element toggle. Returns the callback, so each property
    supplies its own RF property name and matching Blender snap_elements_base flag. '''
    def update(self, context):
        ts = context.scene.tool_settings
        base = ts.snap_elements_base
        ts.snap_elements_base = (base | {element}) if getattr(self, prop_name) else (base - {element})
        # The native transform path never touches SourceCache. So the cache can sit stale while native is on.
        # Now that RF's translate is back in play, kick a rebuild if needed.
        from ..rfoperators.transform import translate_uses_native
        if not translate_uses_native(context):
            SourceCache.get(context)
    return update


class RFProps_Snapping(bpy.types.PropertyGroup):

    """ Sources """
    snap_only_selected: bpy.props.BoolProperty(
        name='Exclude Non-selected',
        description='Only selected objects in Object Mode are considered as valid sources. This allows you to manage what you snap to in the Outliner',
        default=False,
        update=on_source_obj_changed,
    )
    snap_object: bpy.props.PointerProperty(
        name='Source Object',
        type=bpy.types.Object,
        poll= lambda self, obj: obj.mode != 'EDIT' and obj.type in ['MESH', 'CURVE', 'SURFACE', 'META', 'FONT'],
        update=on_source_obj_changed,
    )
    snap_collection: bpy.props.PointerProperty(
        name='Source Collection',
        type=bpy.types.Collection,
        poll= lambda self, collection: collection in [c for c in bpy.data.collections if bpy.context.scene.user_of_id(c)],
        update=on_source_obj_changed,
    )


    """ Feature Detection """
    source_feature_auto_rebuild: bpy.props.BoolProperty(
        name='Auto Rebuild',
        description=(
            'Automatically rebuild the source feature cache when entering RetopoFlow, when '
            'detection settings change, or when a source mesh is edited. Turn off to keep the '
            'cache frozen and rebuild only with the Rebuild Source Cache button'
        ),
        default=True,
        update=lambda self, ctx: SourceCache.mark_dirty_settings_changed(ctx) if self.source_feature_auto_rebuild else None,


    )
    source_feature_batch_power: bpy.props.IntProperty(
        name='Batch Size (12^n)',
        description=(
            'Chunk size exponent for incremental source-cache rebuilding. '
            'Actual chunk size is 12^n for both edge and vertex chunks. '
            'Higher n rebuilds faster but can reduce UI responsiveness'
        ),
        min=2,
        soft_min=2,
        soft_max=6,
        max=8,
        default=3,
        update=lambda self, ctx: SourceCache.request_rebuild(ctx, restart=True) if SourceCache.building else None,
    )
    source_edge_angle_enabled: bpy.props.BoolProperty(
        name='Use Angle Threshold',
        description='Detect sharp edges on the source mesh based on face angle',
        default=False,
        update=on_source_feature_changed,
    )
    source_edge_angle: bpy.props.FloatProperty(
        name='Angle',
        description='Snap to edges above this angle threshold on the source object',
        subtype='ANGLE',
        min=math.radians(1),
        max=math.radians(180),
        default=math.radians(45),
        update=on_source_feature_changed,
    )
    source_edge_creases: bpy.props.BoolProperty(
        name='Snap to Source Creases',
        description='Snap vertices to the creases of the high poly mesh',
        default=False,
        update=on_source_feature_changed,
    )
    source_edge_seams: bpy.props.BoolProperty(
        name='Snap to Source Seams',
        description='Snap vertices to the seams of the high poly mesh',
        default=False,
        update=on_source_feature_changed,
    )
    source_edge_sharps: bpy.props.BoolProperty(
        name='Snap to Source Sharps',
        description='Snap vertices to the sharps of the high poly mesh',
        default=False,
        update=on_source_feature_changed,
    )
    source_edge_proximity: bpy.props.FloatProperty(
        name='Proximity',
        description='How close to feature edges vertices must be to snap, as a fraction of the average edge length',
        subtype='FACTOR',
        min=0.0,
        max=1.0,
        default=0.25,
    )
    source_edge_use_fixed_distance: bpy.props.BoolProperty(
        name='Fixed Distance',
        description='Snap within a fixed world space distance instead of scaling the snap distance by the local edge length',
        default=False,
    )
    source_edge_fixed_distance: bpy.props.FloatProperty(
        name='Distance',
        description='World space distance within which vertices snap to source feature edges and corners',
        subtype='DISTANCE',
        min=0.0,
        soft_max=1.0,
        default=0.05,
    )
    source_edge_stickiness: bpy.props.FloatProperty(
        name='Stickiness',
        description='How difficult it is to drag a snapped vertex back off of a feature edge or corner',
        subtype='NONE',
        min=0,
        max=1,
        default=0.5,
    )
    source_edge_guide_loops: bpy.props.FloatProperty(
        name='Guide Loops',
        description='How strongly the nearest retopo loop is attracted to the source edge while competing loops are kept away',
        subtype='FACTOR',
        min=0,
        max=1,
        default=1.0,
    )

    """ Projection """
    projection: bpy.props.EnumProperty(
        name='Projection',
        description='How vertices are projected onto the source mesh during tweaking',
        items=[
            ('AUTO',           'Automatic',      'Automatically choose screen space or world space projection based on the selection', 'SNAP_ON', 0),
            ('SCREEN_SPACE',   'Screen Space',   'Always project using Face Project (screen space)',                                   'SNAP_FACE', 1),
            ('WORLD_SPACE',    'World Space',    'Always project using Face Nearest (world space)',                                    'SNAP_FACE_NEAREST',2),
            ('FOLLOW_BLENDER', 'Follow Blender', "Use Blender's current snap_elements_individual setting without overriding it",       'BLENDER', 3),
        ],
        default='AUTO',
        update=lambda self, context: setattr(
            context.scene.tool_settings,
            'snap_elements_individual',
            {'FACE_PROJECT'} if self.projection == 'SCREEN_SPACE' else
            {'FACE_NEAREST'} if self.projection in ('AUTO', 'WORLD_SPACE') else
            context.scene.tool_settings.snap_elements_individual
        ),
    )

    """ Face Normals """
    correct_face_normals: bpy.props.BoolProperty(
        name='Correct Face Normals',
        description=(
            'Point newly created and transformed faces outwards, matching the nearest surface on '
            'the source mesh where there is one and the surrounding faces where there is not'
        ),
        default=True,
    )

    """ Snap Elements """
    snap_vertex: bpy.props.BoolProperty(
        name='Vertex', description='Snap to vertices', default=False,
        update=on_snap_element_changed('snap_vertex', 'VERTEX'),
    )
    snap_edge: bpy.props.BoolProperty(
        name='Edge', description='Snap to edges', default=False,
        update=on_snap_element_changed('snap_edge', 'EDGE'),
    )
    snap_edge_center: bpy.props.BoolProperty(
        name='Edge Center', description='Snap to edge midpoints', default=False,
        update=on_snap_element_changed('snap_edge_center', 'EDGE_MIDPOINT'),
    )
    snap_edge_perpendicular: bpy.props.BoolProperty(
        name='Edge Perpendicular', description='Snap to perpendicular points on edges', default=False,
        update=on_snap_element_changed('snap_edge_perpendicular', 'EDGE_PERPENDICULAR'),
    )
    snap_face_center: bpy.props.BoolProperty(
        name='Face Center', description='Snap to face centers', default=False,
        update=on_snap_element_changed('snap_face_center', 'FACE_MIDPOINT'),
    )


def register():
    bpy.utils.register_class(RFProps_Snapping)

def unregister():
    bpy.utils.unregister_class(RFProps_Snapping)
